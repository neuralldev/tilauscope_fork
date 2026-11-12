# MQTT accessories on the tablet — spec, 2026-10-23

To validate before any code. Goal: the network accessories the desktop reads over MQTT, read by
the tablet the same way (operator, 2026-10-23: "comme sur desktop"; Matter later, its own spec).

## 1. What the desktop does (read in the code)

- **One broker** (`MQTTConfig`, `tilauscope/mqttbridge.py`): host, port (1883), client id,
  user and password (password in the system keychain), keepalive 60 s, QoS 1, TLS on/off (system
  CA bundle, self-signed refused), protocol 3.1 / 3.1.1 / 5, connect timeout 3 s. Transport:
  paho, through `artisanlib/mqttport.py`.
- **Sensors** (`MQTTSensor`, QSettings `mqtt/sensors`): id (a name), topic, multiplier, divider,
  unit (`C`, `F`, `W` or none). A temperature is converted on arrival into the unit the session
  works in. Edited in Configuration › INTEGRATIONS under their broker, each with a check that
  waits 2 s for a message.
- **Cache**: topic → last value and its arrival time; each topic independent, the newest wins.
  Topics with no message after 30 s are named in the log.
- **Polling** (optional): a gateway topic (Z-Wave JS UI `pollValue`) asked every N s (floor 10 s)
  for sensors that report rarely (a plug once a minute); a sensor that answers nothing 3 polls
  in a row leaves the rotation (a sleeping battery node).
- **Three uses**:
  1. *Curves*: up to 8 sensors, in pairs, as extra devices `TILAUMQTTBRIDGE12…78` — recorded
     in the `.alog` like any extra channel, named by the sensor.
  2. *Energy of a roast* (`energy_tap.py`): sensors named `roaster` and `extractor`, unit `W`,
     stamped with their arrival time (a silent plug never looks alive); preheat, roast, cooling,
     kWh per kg of green.
  3. *Storage room humidity* (BeanCave › Storage): one sensor read outside a roast.

## 2. What the tablet has

No network device. Accessories are BLE links in Kotlin that hand their values to the session
(`extra_readings`, fixed channels: inlet, catalyst, room °C/RH, pressure, altitude). No external
library at all (Python standard library only, Kotlin without dependencies), no energy, no
storage tab.

## 3. Decisions (operator, 2026-10-23)

1. **Uses**: room conditions and energy (roaster, extractor). Not the curves.
2. **Transport**: an `MqttLink` in Kotlin, as every device link of the tablet, without a
   library: connect, subscribe, QoS 0/1, ping, publish, reconnect every 2 s while wanted, TLS by
   the system's trust store. Values go to the session with their arrival time; the session
   never reads the network.
3. **Configuration typed on the tablet**: the broker (host, port, client id, user, password,
   TLS) and its sensors (name, topic, multiplier, divider, unit), in Settings, with a check per
   sensor as on the desktop (waits 2 s for a message).
4. **Protocol**: MQTT 3.1.1 only, the most widely supported.

5. **Room source**: TilauAmbient always wins over MQTT; an MQTT room reading is used only when
   no TilauAmbient reading is fresh.
6. **Energy**: stored in the `.alog` (`tilau_energy`), read on the desktop for now; shown on
   the tablet in a later evolution.
7. **Polling (Z-Wave)**: later, its own batch.

## 4. Behaviour

- **Room conditions**: a sensor is tied to one of the room readings the tablet records —
  temperature, humidity, pressure — and feeds it as TilauAmbient does (header pill, reading at
  Charge, `.alog`), unless TilauAmbient gives that reading (decision 5). Its unit is declared as
  on the desktop; a °F temperature is converted to °C on arrival.
- **What a sensor feeds** is chosen in its sheet (room temperature, room humidity, pressure,
  roaster power, extractor power); its name stays free. The desktop's reserved names `roaster` and
  `extractor` become the two power choices.
- **Energy**: the roaster and extractor power sensors, unit W, as on the desktop.
  `energy_model.py` (standard library only) moves to `tilaucore`, benched against the desktop on
  its roasts; the tablet records the session from monitoring on (preheat included), each reading
  stamped with its arrival time, and writes `tilau_energy` in the `.alog`.
- **Link**: connects when the roast screen opens (as the accessories do) and keeps reconnecting
  every 2 s while wanted; a sensor silent for 30 s after connecting is named in the log; its
  state shows in Settings (connected, refused, unreachable).

## 5. Order

| Step | What |
|---|---|
| E1 | Mockup of Settings › Network (artifact Ag492cbh4DqzUt8aGGwfhg: broker card, sensor list, a sensor's sheet with what it feeds), then `MqttLink`, configuration, room conditions |
| E2 | `energy_model` in `tilaucore` + bench against the desktop, then the tablet's energy session and `tilau_energy` in the `.alog` |
| — | Later: energy shown on the tablet; Z-Wave polling; Matter (its own spec) |

**E1 done and validated 2026-10-23** with the operator's broker (Jeedom, Z-Wave and zigbee2mqtt): a retained gateway message of 275 kB dropped the link until such messages were read past; a keyboard (SwiftKey) capitalised a first letter whatever the field asked, so the page lowers a first letter typed into an empty field (names, topics and fields are case-sensitive). Before that, coded and `MqttLink.kt` (MQTT 3.1.1 codec + link,
5 Kotlin tests), `mqtt.py` (configuration, a message's value), the room behind TilauAmbient
(6 Python tests), Settings › Network. Checked on the Honor Pad 9 against a test broker on the
computer (`adb reverse`): connected, subscribed to the sensors' topics on the roast screen and
to every topic in Settings, live values per sensor and in the sheet (°F converted), the Room
pill from MQTT when TilauAmbient is off and from TilauAmbient when it reads. Added to the
mockup: a sensor's **field** (the JSON key, `value` by default), the desktop's `command`.
Choices made in coding: an MQTT room reading stays valid 10 min; each room reading is taken on
its own (a room without pressure leaves the preheat without ambient and the `.alog` without
`ambient_pressure`); the password is kept in the app's private configuration file (no system
keychain without a library); the client id is `TilauScope-tablet`, not the desktop's, so both
can be connected to the same broker.

After the code review of 2026-10-23: Settings subscribes to the sensors' topics and to the topic
being typed, no longer to every topic (a busy broker flooded the worker that samples the roast);
the link pings once nothing was sent for half the keep-alive, even while messages arrive; with TLS
the certificate must name the broker. Validated on the tablet the same day.

**E2 done and validated 2026-10-24** (real roast with the plug, same figures on the desktop; shown at the end of the roast and in BeanCave › Roasts). Coded 2026-10-23: `energy_model` moved to `tilaucore` (the desktop
imports it through a shim; the 7 corpus roasts with `tilau_energy` give the same bill). The tablet's
`energy.py` feeds it as the desktop's EnergyTap: START to STOP, readings stamped at arrival, 60 s
freshness widened to the sensor's cadence after 20 readings, the burner estimate between CHARGE and
DROP from the V2's curve in `roasters.json` (operator's choice), context rows, no session for a
simulated roast; an extractor on the roaster's plug is not offered, and a roast restored from the
journal loses its energy (operator's choices). Bench: the desktop's readings and burner replayed
through the tablet on 4 roasts give the same roast bill (total within 0.1 Wh). 3 new Python tests.
