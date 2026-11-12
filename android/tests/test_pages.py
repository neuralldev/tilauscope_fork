# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The WebView pages hold the TilauBridge: what they insert as HTML must never become script.

No JavaScript engine runs here: these read the page sources.
"""
from pathlib import Path
import re
import unittest

ASSETS = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "assets"


def sources():
    return {path.name: path.read_text(encoding="utf-8") for path in ASSETS.iterdir() if path.suffix in (".html", ".js")}


class EscapeTests(unittest.TestCase):
    def test_one_escape_helper_in_common_js_that_escapes_quotes(self):
        """A quote in an imported file name or coffee id closed a data-* attribute and ran script."""
        defining = [name for name, text in sources().items() if re.search(r"function esc\s*\(", text)]
        self.assertEqual(defining, ["common.js"])
        helper = re.search(r"function esc\s*\(.*?\n\}", sources()["common.js"], re.S).group(0)
        for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            self.assertIn(entity, helper)

    def test_coffee_name_in_the_editor_head_is_escaped(self):
        """The coffee name went raw into the editor head's innerHTML."""
        for line in sources()["cave-edit.js"].splitlines():
            if "innerHTML" in line and "coffee.name" in line:
                self.assertIn("esc(", line[:line.index("coffee.name")], line.strip())


class RecordingLockTests(unittest.TestCase):
    def test_the_roast_screen_greys_its_way_out_while_recording(self):
        """The coffee pill stayed live while recording and opened the BeanCave, cutting the devices."""
        roast = sources()["roast.html"]
        for button in ("gear", "cavebtn", "coffee"):
            self.assertIn(f'$("{button}").disabled = recording;', roast)

    def test_the_activity_refuses_any_page_change_while_recording(self):
        """Every page change disconnects the devices: the roaster link would get OFF mid-roast."""
        self.assertRegex(activity(), r"override fun shouldOverrideUrlLoading\([^)]*\)\s*=\s*recording")


def activity() -> str:
    return (ASSETS.parent / "java" / "org" / "tilauscope" / "android" / "prototype" / "MainActivity.kt").read_text(encoding="utf-8")


class BridgeTests(unittest.TestCase):
    def test_a_malformed_page_argument_is_ignored_not_thrown(self):
        """A bad number or a missing separator from the page threw on the main thread: the app closed, mid-roast too."""
        source = activity()
        for unsafe in (r"\.to(Int|Double)\(\)", r"val \([^)]*\) = argument\.split"):
            found = re.search(unsafe, source)
            self.assertIsNone(found, found and found.group(0))
        self.assertRegex(source, r"runCatching \{ Base64\.decode\(argument")

    def test_picked_folders_are_copied_off_the_main_thread(self):
        """A large Drive folder copied on the main thread froze the screen (ANR)."""
        source = activity()
        for function in ("importCave", "importRoasts"):
            body = source[source.index(f"private fun {function}("):]
            body = body[:body.index("\n    }\n")]
            self.assertLess(body.index("Thread {"), body.index("copyFolder("), function)


if __name__ == "__main__":
    unittest.main()
