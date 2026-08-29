#
# ABOUT
# MQTT bridge for TilauScope sensors. Transport delegated to artisanlib.mqttport
# (Artisan native paho stack); feeds MQTTDatabase instead of readings[].

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# TiLau 2025-2026

import base64
import time
import logging
import json

from enum import Enum, auto
from typing import Final, Any, TYPE_CHECKING

from PyQt6.QtCore import pyqtSignal, QObject, QSettings, pyqtSlot
from PyQt6.QtWidgets import QApplication

from dataclasses import dataclass, field
from mashumaro import DataClassDictMixin, field_options

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage

from artisanlib.mqttport import mqttport as _mqttport_base
from artisanlib.util import convertTemp
from tilauscope.tilauscope_types import MQTTSensor, MQTT_SENSORS_KEY, MQTTSensorConfig

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # pylint: disable=unused-import

_logd: Final[logging.Logger] = logging.getLogger("tilau")

# Grace delay before naming the sensor topics that have not produced a single
# message yet. Long enough for a slow-reporting node, short enough to be read
# before the roast starts.
_PENDING_REPORT_DELAY_MS: Final[int] = 30000

# Polling. The floor protects the mesh: Z-Wave is slow and narrow, and a roast
# is a long series of cycles. A target that produces nothing after this many
# consecutive polls leaves the rotation — a sleeping battery node answers on its
# own wake schedule and cannot be polled at all.
_POLL_MIN_INTERVAL_S: Final[int] = 10
_POLL_MISS_LIMIT: Final[int] = 3


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MQTTTopicValue(DataClassDictMixin):
    topic: str
    value: Any
    timestamp: float = field(default_factory=lambda: time.time())


@dataclass
class MQTTDatabase(DataClassDictMixin):
    """Thread-safe topic → value cache. Updated from paho thread, read from sampling thread."""
    values: dict[str, MQTTTopicValue] = field(default_factory=dict)
    _lock: Any = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        import threading as _threading
        object.__setattr__(self, '_lock', _threading.Lock())

    def update(self, topic: str, payload: Any) -> None:
        entry = MQTTTopicValue(topic=topic, value=payload)
        with self._lock:
            self.values[topic] = entry

    def get_value(self, topic: str) -> Any | None:
        with self._lock:
            entry = self.values.get(topic)
        return entry.value if entry else None

    def get_timestamp(self, topic: str) -> float | None:
        """Arrival time of the last message on `topic`, None if never received.
        The poller compares it across cycles to tell a live target from a silent one."""
        with self._lock:
            entry = self.values.get(topic)
        return entry.timestamp if entry else None


@dataclass
class MQTTConfig(DataClassDictMixin):
    broker_url: str = "localhost"
    port: int = 1883
    topic: str = "/#"
    client_id: str = "Tilauscope"
    username_encoded: str = ""
    # Legacy, read-only: migrated to the keychain on first access, then dropped.
    password_encoded: str = field(default="",
                                  metadata=field_options(serialize="omit"))
    _username: str = field(default="mqtt", repr=False)
    # Session cache for the keychain value. Never serialised.
    _password: str = field(default="", repr=False,
                           metadata=field_options(serialize="omit"))
    keepalive: int = 60
    qos: int = 1
    tls: bool = False  # encrypted broker; the CA bundle is the system one, self-signed certificates are rejected
    protocol_version: int = 1  # index into mqttport.PROTOCOL_VERSIONS: 0 = v3.1, 1 = v3.1.1, 2 = v5
    connect_timeout: float = 3.0  # seconds waited for the broker to confirm the connection
    # Gateway API topic a read request is published on, empty when the broker
    # offers nothing of the sort. Z-Wave JS UI: zwave/_CLIENTS/<gateway>/api/pollValue/set
    poll_topic: str = ""
    poll_interval: int = 0  # seconds, 0 = no polling

    @property
    def username(self) -> str:
        if self.username_encoded:
            try:
                return base64.b64decode(self.username_encoded).decode('utf-8')
            except Exception:
                return self._username
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        if value is not None:
            self._username = value
            self.username_encoded = base64.b64encode(value.encode('utf-8')).decode('utf-8')

    def _stored_password(self) -> str:
        """The password as the keychain holds it, cached. No migration, no writes.

        Kept apart from the property so the setter can ask what is already
        stored without re-entering the legacy adoption below — which calls the
        setter, and would not come back.
        """
        if self._password:
            return self._password
        from tilauscope.tilau_secrets import get_secret, mqtt_account  # noqa: PLC0415
        stored = get_secret(mqtt_account(self.username, self.broker_url, self.port))
        if stored:
            self._password = stored
        return stored

    @property
    def password(self) -> str:
        """The broker password, from the keychain rather than the settings.

        A password kept in the settings travels with an exported ``.aset``,
        which is how a machine setup is shared. This one does not.
        """
        stored = self._stored_password()
        if stored:
            return stored

        # Nothing in the keychain: an installation that still keeps it in the
        # settings. Move it, once, then answer from the keychain.
        if self.password_encoded:
            try:
                legacy = base64.b64decode(self.password_encoded).decode('utf-8')
            except Exception:  # noqa: BLE001
                return ""
            if legacy:
                self.password = legacy
                return legacy
        return ""

    @password.setter
    def password(self, value: str) -> None:
        if value is None:
            return
        # The configuration dialog writes every field back on OK, changed or
        # not. Going to the keychain for a value it already holds costs an
        # access the operating system may well ask the operator to approve.
        if value == self._stored_password():
            return
        from tilauscope.tilau_secrets import (  # noqa: PLC0415
            delete_secret, mqtt_account, set_secret,
        )
        self._password = value
        account = mqtt_account(self.username, self.broker_url, self.port)
        if value:
            set_secret(account, value)
        else:
            delete_secret(account)
        # The settings copy is superseded the moment the keychain holds it.
        self.password_encoded = ""


# ---------------------------------------------------------------------------
# Polling — asking the gateway for a reading instead of waiting for one
# ---------------------------------------------------------------------------

@dataclass
class _PollTarget:
    """One sensor topic and the request that makes the gateway publish on it."""
    topic: str
    request: dict[str, Any]
    last_seen: float | None = None
    misses: int = 0


def derive_poll_request(topic: str) -> dict[str, Any] | None:
    """Build a Z-Wave JS UI pollValue request from the topic a sensor publishes on.

    A value topic ends with nodeId/commandClass/endpoint/property, whatever the
    prefix before it: zwave/135/49/0/Power -> node 135, class 49, endpoint 0,
    property "Power". The gateway sanitises value names for the topic, turning
    spaces into underscores, while its API expects the original label — so the
    underscores are put back. Returns None for a topic that is not of that shape,
    which simply means the sensor cannot be polled.
    """
    parts = [p for p in topic.strip("/").split("/") if p]
    if len(parts) < 5:  # at least one prefix segment plus the four value segments
        return None
    node, command_class, endpoint, prop = parts[-4:]
    if not (node.isdigit() and command_class.isdigit() and endpoint.isdigit()) or not prop:
        return None
    return {"args": [{
        "nodeId": int(node),
        "commandClass": int(command_class),
        "endpoint": int(endpoint),
        "property": prop.replace("_", " "),
    }]}


# ---------------------------------------------------------------------------
# Transport subclass — overrides mqttport handlers (slots-safe)
# ---------------------------------------------------------------------------

class _TilauMqttTransport(_mqttport_base):
    """mqttport subclass that routes messages into MQTTDatabase.
    Overrides handler methods instead of instance-assigning them (slots-safe).
    owner is set by TilauscopeMQTTClient after construction.
    """

    def __init__(self, aw: 'ApplicationWindow') -> None:
        super().__init__(aw)
        self.owner: 'TilauscopeMQTTClient | None' = None  # set by owner after construction

    def on_message_handler(self, _client: Any, _userdata: Any, message: MQTTMessage) -> None:  # type: ignore[override]
        if self.owner is None:
            return
        try:
            payload_str = message.payload.decode("utf-8")
            try:
                data = json.loads(payload_str)
            except json.JSONDecodeError:
                data = payload_str
            if message.topic == self.owner.poll_response_topic:
                self.owner.on_poll_response(data)
                return
            self.owner.db.update(message.topic, data)
            # First message of a topic is logged once: until it arrives the channel
            # reads -1 and nothing else in the chain says why.
            if message.topic not in self.owner.seen_topics:
                self.owner.seen_topics.add(message.topic)
                _logd.info("TilauMQTT first message on %s: %s", message.topic, data)
        except ValueError:
            _logd.error("TilauMQTT: failed to parse payload: %s", message.payload)

    def on_connect_handler(self, client: Any, _userdata: Any, _flags: Any, status: Any, _properties: Any) -> None:  # type: ignore[override]
        if self.owner is None:
            return
        if status == 0:
            self.owner.is_connected = True
            full_topic = self.topic
            if not full_topic.endswith("/#"):
                full_topic = full_topic.rstrip("/") + "/#"
            try:
                client.subscribe(full_topic, qos=self.owner.config.qos)
            except Exception as e:
                _logd.error("TilauMQTT subscribe failed: %s", e)
            # Sensor topics usually sit outside the configured base topic
            # (zwave/…, zigbee2mqtt/…) so they are subscribed one by one, and from
            # inside this handler: paho reconnects on its own, and a reconnect
            # would otherwise drop every sensor subscription for good.
            for sensor_topic in self.owner.sensor_topics:
                try:
                    client.subscribe(sensor_topic, qos=self.owner.config.qos)
                except Exception as e:
                    _logd.error("TilauMQTT subscribe %s failed: %s", sensor_topic, e)
            if self.owner.poll_response_topic:
                try:
                    client.subscribe(self.owner.poll_response_topic, qos=self.owner.config.qos)
                except Exception as e:
                    _logd.error("TilauMQTT subscribe %s failed: %s", self.owner.poll_response_topic, e)
            self.owner.connected_signal.emit()
        else:
            _logd.error("TilauMQTT connection failed, code: %s", status)

    def on_disconnect_handler(self, _client: Any, _userdata: Any, _flags: Any, _status: Any, _properties: Any) -> None:  # type: ignore[override]
        if self.owner is None:
            return
        self.owner.is_connected = False
        self.owner.disconnected_signal.emit()


# ---------------------------------------------------------------------------
# Client — owns MQTTDatabase, exposes Qt signals, delegates transport
# ---------------------------------------------------------------------------

class TilauscopeMQTTClient(QObject):
    """MQTT client for TilauScope sensors.

    Delegates all paho transport to _TilauMqttTransport (mqttport subclass).
    Maintains its own broker connection (separate from Artisan's aw.mqtt).
    Incoming messages are stored in self.db (MQTTDatabase) instead of readings[].
    """
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()

    def __init__(self, config: MQTTConfig, aw: 'ApplicationWindow') -> None:
        super().__init__()
        self.config = config
        self.db = MQTTDatabase()
        self.is_connected: bool = False
        # Sensor topics are held here, not in the transport, because they have to
        # be re-subscribed on every (re)connection — see on_connect_handler.
        self.sensor_topics: list[str] = []
        self.seen_topics: set[str] = set()
        self._poll_targets: list[_PollTarget] = []
        self._poll_timer: Any = None

        self._port = _TilauMqttTransport(aw)
        self._port.owner = self  # back-reference for callbacks
        self._port.host = config.broker_url
        self._port.port = config.port
        self._port.keepalive = config.keepalive
        self._port.tls = config.tls
        self._port.protocol_version = config.protocol_version
        self._port.user = config.username
        self._port.password = config.password
        self._port.topic = config.topic if config.topic else "/#"

    @property
    def poll_response_topic(self) -> str:
        """Where the gateway answers a poll request: the request topic without its
        trailing /set, as Z-Wave JS UI does. Empty when polling is not configured."""
        topic = self.config.poll_topic.strip()
        if not topic:
            return ""
        return topic[:-4] if topic.endswith("/set") else topic

    # -- paho client passthrough (legacy callers use .client.is_connected()) --

    @property
    def client(self) -> mqtt.Client | None:
        return self._port.client

    # -- lifecycle -----------------------------------------------------------

    def start(self, device_logging: bool = False) -> bool:
        """Start the transport and return at once.

        Returns whether the transport could be LAUNCHED — not whether the broker
        answered. The CONNACK arrives on `connected_signal`, and everything that
        depends on it (subscriptions, sensor list) hangs off that slot, so no
        caller has to wait here. A caller that must report a verdict to the
        operator asks for it explicitly with wait_connected().
        """
        if not self.config.username:
            _logd.error("TilauMQTT start(): missing credentials")
            return False
        try:
            self._port.start(device_logging)
        except Exception as e:
            _logd.error("TilauMQTT start() error: %s", e)
            return False
        return True

    def wait_connected(self, timeout: float | None = None) -> bool:
        """Block until the broker confirms, or the timeout expires.

        Only for the paths whose whole purpose is the verdict — the connection
        test and the one-shot sensor reads. Never on the ON path: a broker that
        is down froze the window for the full timeout before monitoring started
        (a TLS broker needs more than a plain one: the handshake happens in here).
        """
        if self.is_connected:
            return True
        from PyQt6.QtCore import QEventLoop, QTimer
        wait_ms = max(500, int((self.config.connect_timeout if timeout is None
                                else timeout) * 1000))
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.connected_signal.connect(loop.quit)
        timer.start(wait_ms)
        loop.exec()
        try:
            self.connected_signal.disconnect(loop.quit)
        except Exception:
            pass
        return self.is_connected

    def stop(self) -> None:
        """Stop transport."""
        self.is_connected = False
        self.stop_polling()
        self._port.stop()

    # -- subscriptions -------------------------------------------------------

    def update_subscriptions(self, sensor_list: MQTTSensorConfig) -> None:
        """Record the sensor topics and subscribe them now.

        The list is kept on the client so that on_connect_handler can restore the
        subscriptions after an automatic reconnection.
        """
        self.sensor_topics = list(dict.fromkeys(s.topic for s in sensor_list.sensors if s.topic))
        if not self._port.client or not self._port.client.is_connected():
            return
        for topic in self.sensor_topics:
            self._port.client.subscribe(topic, qos=self.config.qos)
        self._schedule_pending_report()
        self.start_polling()

    def _schedule_pending_report(self) -> None:
        """Report, once, the sensor topics still silent after the grace delay.

        A broker publishing without the retain flag delivers nothing on subscribe:
        the cache stays empty until the next spontaneous publication, and every
        channel reads -1 in the meantime without a single trace.
        """
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(_PENDING_REPORT_DELAY_MS, self._report_pending_sensors)

    @pyqtSlot()
    def _report_pending_sensors(self) -> None:
        if not self.sensor_topics:
            return
        pending = [t for t in self.sensor_topics if self.db.get_value(t) is None]
        if pending:
            _logd.warning(
                "TilauMQTT: still no message on %s — check the broker retain flag "
                "and the publication interval of these topics", ", ".join(pending)
            )
        else:
            _logd.info("TilauMQTT: all %d sensor topics received", len(self.sensor_topics))

    # -- polling -------------------------------------------------------------

    def start_polling(self) -> None:
        """Ask the gateway for a reading on every pollable sensor topic, now and
        then at the configured interval.

        Nodes that publish only when they feel like it leave their channel empty
        for minutes; a poll produces a value on demand instead. Runs on the main
        thread — publishing is queued by paho, so nothing here blocks, and the
        sampling loop is never involved.
        """
        self.stop_polling()
        interval = self.config.poll_interval
        if not self.config.poll_topic.strip() or interval <= 0:
            return
        interval = max(interval, _POLL_MIN_INTERVAL_S)
        self._poll_targets = []
        for topic in self.sensor_topics:
            request = derive_poll_request(topic)
            if request is None:
                _logd.info("TilauMQTT: %s cannot be polled, its topic is not a gateway value path", topic)
                continue
            self._poll_targets.append(_PollTarget(topic=topic, request=request))
        if not self._poll_targets:
            return
        from PyQt6.QtCore import QTimer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(interval * 1000)
        self._poll_timer.timeout.connect(self._poll_tick)
        self._poll_timer.start()
        _logd.info("TilauMQTT: polling %d topics every %d s", len(self._poll_targets), interval)
        self._poll_tick()  # prime immediately, the first roast minute matters

    def stop_polling(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        self._poll_targets = []

    @pyqtSlot()
    def _poll_tick(self) -> None:
        if not self.is_connected:
            return
        for target in list(self._poll_targets):
            seen = self.db.get_timestamp(target.topic)
            if target.last_seen is not None and seen == target.last_seen:
                target.misses += 1
                if target.misses >= _POLL_MISS_LIMIT:
                    self._drop_poll_target(target, "no answer after %d polls" % _POLL_MISS_LIMIT)
                    continue
            else:
                target.misses = 0
            target.last_seen = seen
            self.publish(self.config.poll_topic, target.request, qos=0)

    def on_poll_response(self, data: Any) -> None:
        """Handle the gateway's answer to a poll request. A refusal is definitive —
        a wrong property name will not become right on the next cycle — so the
        target leaves the rotation at once, named in the log."""
        if not isinstance(data, dict) or data.get("success", True):
            return
        args = data.get("args") or []
        node = args[0].get("nodeId") if args and isinstance(args[0], dict) else None
        message = data.get("message", "")
        for target in list(self._poll_targets):
            if node is not None and target.request["args"][0]["nodeId"] != node:
                continue
            self._drop_poll_target(target, f"gateway refused the request: {message}")

    def _drop_poll_target(self, target: _PollTarget, reason: str) -> None:
        if target in self._poll_targets:
            self._poll_targets.remove(target)
        _logd.warning("TilauMQTT: stopped polling %s — %s", target.topic, reason)

    # -- publish (alarm commands) -------------------------------------------

    def publish(self, topic: str, value: Any, qos: int = 1, retain: bool = False) -> bool:
        if not self._port.client or not self._port.client.is_connected():
            _logd.warning("TilauMQTT publish: not connected")
            return False
        try:
            # Bool must serialize to lowercase json literals (str(True)=="True" breaks zwave).
            if isinstance(value, bool):
                payload = "true" if value else "false"
            elif isinstance(value, (dict, list)):
                payload = json.dumps(value)
            elif value is None:
                payload = "null"
            else:
                payload = str(value)
            result = self._port.client.publish(topic, payload=payload, qos=qos, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                _logd.error("TilauMQTT publish error: %s", result.rc)
                return False
            return True
        except Exception as e:
            _logd.error("TilauMQTT publish exception: %s", e)
            return False

    def poll(self, topic: str | None = None) -> Any:
        return self.db.get_value(topic) if topic else None


# ---------------------------------------------------------------------------
# Sensor check helpers
# ---------------------------------------------------------------------------

class MQTTSensorCheckError(Enum):
    OK = auto()
    TIMEOUT = auto()
    NO_CLIENT = auto()
    INVALID_COMMAND = auto()
    NO_MESSAGE = auto()
    EXTRACTION_FAILED = auto()
    TYPE_UNSUPPORTED = auto()
    EXCEPTION = auto()


@dataclass
class MQTTSensorCheckResult:
    ok: bool
    value: Any | None = None
    value_type: type | None = None
    error: MQTTSensorCheckError = MQTTSensorCheckError.OK
    message: str | None = None


def _scale_reading(data: Any, sensor: MQTTSensor, mode: str = "") -> float:
    """Extract the sensor's field from a payload, apply multiplier/divider, then
    convert to `mode` when the sensor declares a temperature unit.

    Order matters: multiplier/divider bring the raw payload into the sensor's
    own unit, so the temperature conversion has to come last.
    """
    extractor = sensor.command if sensor.command else "value"
    raw_val = data[extractor] if isinstance(data, dict) else data
    multiplier = sensor.multiplier if sensor.multiplier else 1.0
    divider = sensor.divider if sensor.divider else 1.0
    value = (float(raw_val) * multiplier) / divider
    return convertTemp(value, sensor.unit, mode)


# ---------------------------------------------------------------------------
# Ports — sensor CRUD + sampling
# ---------------------------------------------------------------------------

class TilauMqttPorts:
    def __init__(self, mqtt_client: TilauscopeMQTTClient | None) -> None:
        self.client = mqtt_client

    def load_mqtt_sensors(self) -> MQTTSensorConfig:
        settings = QSettings()
        raw = settings.value(MQTT_SENSORS_KEY, None)
        if not raw:
            return MQTTSensorConfig(sensors=[])
        try:
            return MQTTSensorConfig.from_json(raw)
        except Exception:
            return MQTTSensorConfig(sensors=[])

    def save_mqtt_sensors(self, config: MQTTSensorConfig) -> None:
        settings = QSettings()
        settings.setValue(MQTT_SENSORS_KEY, config.to_json())

    def poll_sensor_by_id(self, sensor_id: str, sensor_config: MQTTSensorConfig,
                          mode: str = "") -> float | None:
        """Non-blocking read for the Artisan sampling thread. Returns None if no data yet.

        `mode` is the unit the application is working in ("C"/"F"). A sensor that
        declares a temperature unit is converted into that unit here, at the
        acquisition boundary; a sensor with no unit is passed through untouched.
        """
        if not self.client or not self.client.is_connected:
            return None
        sensor: MQTTSensor | None = next(
            (s for s in sensor_config.sensors if s.id == sensor_id), None
        )
        if sensor is None:
            return None
        data = self.client.db.get_value(sensor.topic)
        if data is None:
            return None
        try:
            return _scale_reading(data, sensor, mode)
        except Exception:
            return None

    def check_sensor(self, sensor: MQTTSensor, timeout: float = 2.0,
                     mode: str = "") -> MQTTSensorCheckResult:
        """UI-side check with QEventLoop wait. Not for use in sampling thread.

        Reports the value the sampling loop would record, `mode` conversion included.
        """
        if not self.client or not self.client.is_connected:
            return MQTTSensorCheckResult(
                ok=False,
                error=MQTTSensorCheckError.NO_CLIENT,
                message=QApplication.translate("tilauscope_devices", "MQTT client not connected")
            )
        if self.client._port.client:
            self.client._port.client.subscribe(sensor.topic, 1)

        data = self.client.db.get_value(sensor.topic)
        if data is None:
            from PyQt6.QtCore import QEventLoop, QTimer
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            poll_timer = QTimer()
            poll_timer.setInterval(50)

            def _on_new_message() -> None:
                if self.client.db.get_value(sensor.topic) is not None:  # type: ignore[union-attr]
                    loop.quit()

            poll_timer.timeout.connect(_on_new_message)
            poll_timer.start()
            timer.start(int(timeout * 1000))
            loop.exec()
            poll_timer.stop()
            try:
                timer.timeout.disconnect(loop.quit)
            except Exception:
                pass
            data = self.client.db.get_value(sensor.topic)

        if data is None:
            return MQTTSensorCheckResult(
                ok=False,
                error=MQTTSensorCheckError.NO_MESSAGE,
                message=QApplication.translate("tilauscope_devices", "No message received within timeout")
            )

        try:
            return MQTTSensorCheckResult(
                ok=True, value=_scale_reading(data, sensor, mode), value_type=float
            )
        except Exception:
            return MQTTSensorCheckResult(ok=True, value=str(data), value_type=str)