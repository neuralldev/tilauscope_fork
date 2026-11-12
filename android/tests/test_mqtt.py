# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""MQTT sensors (MQTT-SPEC): the value a message carries, and the room they feed behind TilauAmbient."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration, mqtt
from tilauscope_mobile.demo import Demo

TEMPERATURE = {"name": "Lab", "topic": "zigbee2mqtt/lab", "field": "temperature", "feeds": "room_c"}
HUMIDITY = {"name": "Lab RH", "topic": "zigbee2mqtt/lab", "field": "humidity", "feeds": "room_rh"}


class ReadingTests(unittest.TestCase):
    def test_a_field_of_a_json_message_or_the_message_itself_scaled_as_on_the_desktop(self):
        self.assertEqual(mqtt.reading(mqtt.sensor(TEMPERATURE), '{"temperature": 21.5, "humidity": 58}'), 21.5)
        plug = mqtt.sensor({"name": "Plug", "topic": "zwave/135/49/0/Power", "feeds": "roaster_w", "divider": 10})
        self.assertEqual(mqtt.reading(plug, "12400"), 1240.0)
        self.assertEqual(mqtt.reading(plug, '{"value": 12400, "time": 1}'), 1240.0) # the desktop's default field
        fahrenheit = mqtt.sensor({**TEMPERATURE, "unit": "F"})
        self.assertAlmostEqual(mqtt.reading(fahrenheit, '{"temperature": 68}'), 20.0)

    def test_a_message_without_a_number_reads_nothing(self):
        sensor = mqtt.sensor(TEMPERATURE)
        for payload in ('{"humidity": 58}', '{"temperature": "warm"}', "offline", '{"temperature": null}', "NaN"):
            self.assertIsNone(mqtt.reading(sensor, payload), payload)

    def test_a_sensor_reads_one_topic_and_a_broker_its_port(self):
        with self.assertRaises(ValueError):
            mqtt.sensor({**TEMPERATURE, "topic": "zigbee2mqtt/#"})
        with self.assertRaises(ValueError):
            mqtt.sensor({**TEMPERATURE, "divider": 0})
        with self.assertRaises(ValueError):
            mqtt.validate({"host": "192.168.1.20", "port": 70000})
        self.assertEqual(mqtt.sensor({**HUMIDITY, "unit": "F"})["unit"], "") # °F only for a temperature


class RoomTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        config = str(self.dir / "config.json")
        configuration.save(config, {**configuration.default(), "mqtt": {"host": "192.168.1.20", "sensors": [TEMPERATURE, HUMIDITY]}})
        self.demo = Demo(str(self.dir / "session.journal"), config)
        self.clock = [100.0]
        self.demo.clock = lambda: self.clock[0]

    def message(self, payload):
        self.demo.mqtt_message(json.dumps({"topic": "zigbee2mqtt/lab", "payload": payload}))

    def test_tilauambient_wins_and_mqtt_gives_what_it_has_while_it_is_recent(self):
        self.message('{"temperature": 22.0, "humidity": 61}')
        self.demo.ambient_reading(json.dumps({"temperature_c": 19.5, "humidity_pct": 55.0, "pressure_hpa": 1012.0}))
        self.assertEqual(self.demo.room()["temperature_c"], 19.5)
        self.clock[0] += 4 # the probe is silent: its readings are stale
        self.assertEqual(self.demo.room(), {"temperature_c": 22.0, "humidity_pct": 61.0})
        self.assertEqual(json.loads(self.demo.snapshot())["room_source"], "mqtt")
        self.clock[0] += 600
        self.assertIsNone(self.demo.room())

    def test_a_partial_room_is_kept_at_charge_and_written_as_it_is(self):
        self.demo.start()
        self.message('{"temperature": 22.0, "humidity": 61}')
        self.clock[0] += 1
        self.demo.advance(1)
        self.demo.mark("charge")
        self.assertIsNone(self.demo._preheat_room()) # the preheat needs the pressure too
        self.demo.advance(1)
        self.demo.stop()
        data = ast.literal_eval(Path(self.demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        self.assertEqual((data["ambientTemp"], data["ambient_humidity"]), (22.0, 61.0))
        self.assertNotIn("ambient_pressure", data)

    def test_settings_check_reads_the_last_message_with_the_sensor_as_typed(self):
        self.assertEqual(json.loads(self.demo.mqtt_check(json.dumps(TEMPERATURE))), {"key": None, "heard": False})
        self.message('{"temperature": 68, "humidity": 61}')
        self.clock[0] += 3
        self.assertEqual(json.loads(self.demo.mqtt_check(json.dumps({**TEMPERATURE, "unit": "F", "key": 0}))),
                         {"key": 0, "heard": True, "age_s": 3, "value": 20.0})

    def test_network_is_saved_at_each_change_but_not_during_a_roast(self):
        broker = {"host": "192.168.1.30", "port": 1883, "sensors": [TEMPERATURE]}
        self.assertEqual(json.loads(self.demo.save_mqtt(json.dumps(broker)))["mqtt"]["host"], "192.168.1.30")
        self.assertEqual(configuration.load(str(self.dir / "config.json"))["mqtt"]["host"], "192.168.1.30")
        self.demo.start()
        with self.assertRaises(ValueError):
            self.demo.save_mqtt("null")


if __name__ == "__main__":
    unittest.main()
