# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Coffee packages for the page bench: `make_coffee.py <folder>` writes a shared coffee, a damaged file and a newer one,
and prints their paths with the library card of the coffee, as JSON."""
import json
from pathlib import Path
import sys

TESTS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TESTS), str(TESTS.parents[0] / "python"), str(TESTS.parents[1] / "src")]
from test_coffee_share import THEIRS, UUID, card, roast, write  # noqa: E402
from tilaucore.beans import RoastTasting  # noqa: E402


def main(folder: str) -> None:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    good = write(out / "catuai.tilaucoffee", roasts=[roast(THEIRS)], tastings={THEIRS: RoastTasting(bean_uuid=UUID, verdict="yes")})
    (out / "bad.tilaucoffee").write_bytes(b"PK not a zip")
    newer = write(out / "newer.tilaucoffee", version="9.0", build=1, roasts=[roast(THEIRS)])
    print(json.dumps({"good": str(good), "bad": str(out / "bad.tilaucoffee"), "newer": str(newer), "uuid": UUID,
                      "card": card(), "other": card("Barazilie", roaster="Aillio Bullet", id="0" * 31 + "2")}))


if __name__ == "__main__":
    main(sys.argv[1])
