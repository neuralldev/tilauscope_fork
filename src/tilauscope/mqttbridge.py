#
# ABOUT
# MQTT bridge for TilauScope sensors
# Transport delegated to artisanlib.mqttport (Artisan native paho stack).
# Maintains a separate broker connection; feeds MQTTDatabase instead of readings[].

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
from mashumaro import DataClassDictMixin

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage

from artisanlib.mqttport import mqttport as _mqttport_base
from artisanlib.util import convertTemp
from tilauscope.tilauscope_types import MQTTSensor, MQTT_SENSORS_KEY, MQTTSensorConfig

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # pylint: disable=unused-import

_logd: Final[logging.Logger] = logging.getLogger("tilau")


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


@dataclass
class MQTTConfig(DataClassDictMixin):
    broker_url: str = "localhost"
    port: int = 1883
    topic: str = "/#"
    client_id: str = "Tilauscope"
    username_encoded: str = ""
    password_encoded: str = ""
    _username: str = field(default="mqtt", repr=False)
    _password: str = field(default="mqtt", repr=False)
    keepalive: int = 60
    qos: int = 1

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

    @property
    def password(self) -> str:
        if self.password_encoded:
            try:
                return base64.b64decode(self.password_encoded).decode('utf-8')
            except Exception:
                return self._password
        return self._password

    @password.setter
    def password(self, value: str) -> None:
        if value is not None:
            self._password = value
            self.password_encoded = base64.b64encode(value.encode('utf-8')).decode('utf-8')


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
            self.owner.db.update(message.topic, data)
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

        self._port = _TilauMqttTransport(aw)
        self._port.owner = self  # back-reference for callbacks
        self._port.host = config.broker_url
        self._port.port = config.port
        self._port.keepalive = config.keepalive
        self._port.user = config.username
        self._port.password = config.password
        self._port.topic = config.topic if config.topic else "/#"

    # -- paho client passthrough (legacy callers use .client.is_connected()) --

    @property
    def client(self) -> mqtt.Client | None:
        return self._port.client

    # -- lifecycle -----------------------------------------------------------

    def start(self, device_logging: bool = False) -> bool:
        """Start transport. Returns True when connected (2 s timeout)."""
        if not self.config.username:
            _logd.error("TilauMQTT start(): missing credentials")
            return False
        try:
            self._port.start(device_logging)
        except Exception as e:
            _logd.error("TilauMQTT start() error: %s", e)
            return False
        from PyQt6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.connected_signal.connect(loop.quit)
        timer.start(2000)
        loop.exec()
        try:
            self.connected_signal.disconnect(loop.quit)
        except Exception:
            pass
        return self.is_connected

    def stop(self) -> None:
        """Stop transport."""
        self.is_connected = False
        self._port.stop()

    # -- subscriptions -------------------------------------------------------

    def update_subscriptions(self, sensor_list: MQTTSensorConfig) -> None:
        if not self._port.client or not self._port.client.is_connected():
            return
        for s in sensor_list.sensors:
            self._port.client.subscribe(s.topic, qos=self.config.qos)

    # -- publish (alarm commands) -------------------------------------------

    def publish(self, topic: str, value: Any, qos: int = 1, retain: bool = False) -> bool:
        if not self._port.client or not self._port.client.is_connected():
            _logd.warning("TilauMQTT publish: not connected")
            return False
        try:
            # Bool must serialize to lowercase json literals (str(True)=="True" breaks zwave). ## TILAU ##
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