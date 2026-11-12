# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

import argparse
import json

from .demo import Demo


def main() -> None:
    parser = argparse.ArgumentParser(description="TilauScope Android core: simulation only")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--output", help="Optional .json checkpoint (not an Artisan .alog)")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("--seconds must be between 1 and 3600")
    demo = Demo()
    demo.start()
    demo.mark("charge")
    snapshot = json.loads(demo.advance(args.seconds))
    if args.output:
        demo.save(args.output)
    del snapshot["samples"]
    print(json.dumps(snapshot))


if __name__ == "__main__":
    main()
