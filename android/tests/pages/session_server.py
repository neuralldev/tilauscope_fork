# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The session behind the page bench: SessionService.run on the real Python core, one JSON line per call.

In: {"method", "args"}; out: {"result", "commands"}, `result` wrapped as the service hands it to the page
(under "reply" for the setup calls, the snapshot of the new samples otherwise, null when the call failed).
The method sets are read from SessionService.kt, so the bench follows the app. Bench calls start with "__":
"__clock" sets the clock to args[0], "__resync" is SessionService.resync.
"""
import json
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "app/src/main/java/org/tilauscope/android/prototype/SessionService.kt"


def method_set(name):
    source = SERVICE.read_text(encoding="utf-8")
    body = re.search(rf"val {name} = setOf\((.*?)\)", source, re.S).group(1)
    return set(re.findall(r'"(\w+)"', body))


REPLY, TEXT_REPLY, QUIET = method_set("REPLY_METHODS"), method_set("TEXT_REPLY_METHODS"), method_set("QUIET_METHODS")


def main(folder):
    sys.path[:0] = [str(ROOT / "python"), str(ROOT.parent / "src")]
    from tilauscope_mobile import config as configuration
    from tilauscope_mobile.demo import Demo
    base = Path(folder)
    overrides = base / "overrides.json" # the test's settings, over the app's defaults
    if overrides.exists():
        configuration.save(str(base / "config.json"), {**configuration.default(), **json.loads(overrides.read_text())})
    demo = Demo(str(base / "session.journal"), str(base / "config.json"), str(base / "beancave"))
    clock = [1000.0]
    demo.clock = demo.real_clock = lambda: clock[0]
    since = 0
    for line in sys.stdin:
        call = json.loads(line)
        method, args = call["method"], call.get("args", [])
        if method == "__clock":
            clock[0] = float(args[0])
            print(json.dumps({"result": None, "commands": []}), flush=True)
            continue
        if method == "__resync": # SessionService.resync: the whole curve, for a newly attached page
            since, method = 0, None
        try:
            answer = getattr(demo, method)(*args) if method else None
            if method in QUIET:
                result = "quiet"
            elif method in TEXT_REPLY:
                result = {"reply": str(answer)}
            elif method in REPLY:
                result = {"reply": json.loads(answer)}
            else:
                result = json.loads(demo.snapshot(since))
                since = result["sample_count"]
        except Exception: # as the service: logged, and null for the page
            traceback.print_exc(file=sys.stderr)
            result = None
        commands = json.loads(demo.take_commands())
        print(json.dumps({"result": result, "commands": commands}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
