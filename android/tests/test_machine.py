# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""What the roaster is told: the commands of the machine's Artisan setup, at each milestone and at End roast."""
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo


class MachineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = str(Path(directory.name) / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2"})
        self.demo = Demo(str(Path(directory.name) / "session.journal"), config)

    def test_milestones_and_end_roast_send_the_setups_commands(self):
        self.demo.start()
        self.demo.mark("charge")
        self.assertEqual(self.demo.machine_log, ["EVT,1"])
        for milestone in ("dry_end", "first_crack"): # nothing in the V2 setup for these
            self.demo.advance(120)
            self.demo.mark(milestone)
        self.assertEqual(self.demo.machine_log, ["EVT,1"])
        self.demo.advance(60)
        self.demo.mark("drop")
        self.demo.stop()
        # End roast: burner off, cooled first (until the beans are under 50 °C), then stopped.
        self.assertEqual(self.demo.machine_log, ["EVT,1", "EVT,8", "OT1,0", "CLDN,ON", "OT2,75", "OT3,80",
                                                 "UNTIL_BT_BELOW,50", "EVT,9", "OFF"])

    def test_without_a_machine_nothing_is_sent(self):
        demo = Demo(None)
        demo.start()
        demo.mark("charge")
        demo.stop()
        self.assertEqual(demo.machine_log, [])


if __name__ == "__main__":
    unittest.main()
