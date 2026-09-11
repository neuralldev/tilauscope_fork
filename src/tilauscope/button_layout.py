"""Where custom event buttons fall: rows, tray, and welded groups.

Artisan lays its button bar out in ``realignbuttons``, and the rules are not
obvious from the stored data: a button's *visible* flag means two different
things depending on where the button sits. Before the first visible one it is a
button no bar draws, reachable only from an alarm. Among the visible ones it
takes a slot, draws nothing, and splits the welded group in two.

Both TilauScope surfaces that show these buttons — the editor canvas and the
floating panel — read those rules from here, so they cannot drift apart or
drift away from the bar they are meant to reflect.

Callers pass any sequence of objects carrying a ``visible`` attribute.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _HasVisible(Protocol):
    visible: bool


def first_visible(rows: Sequence[_HasVisible]) -> int:
    """Index of the first button a bar draws; 0 when none is drawn.

    Artisan starts its search at 0 and only moves it on finding a visible
    button, so an all-hidden set places every button rather than none.
    """
    for i, row in enumerate(rows):
        if row.visible:
            return i
    return 0


def tray_and_rows(rows: Sequence[_HasVisible],
                  per_row: int) -> tuple[list[int], list[list[int]]]:
    """Split the buttons into the alarm-only tray and the bar's rows.

    Returns ``(tray, rows)`` as index lists. The tray takes no slot. Each row
    holds up to ``per_row`` indices and may include hidden ones — those are the
    gaps, and they occupy their slot exactly as Artisan gives them one.
    """
    first = first_visible(rows)
    tray = list(range(first))
    placed = list(range(first, len(rows)))
    chunks = [placed[i:i + per_row] for i in range(0, len(placed), max(1, per_row))]
    return tray, chunks


def split_groups(chunk: Sequence[int],
                 rows: Sequence[_HasVisible]) -> list[list[int]]:
    """Split one row into its welded groups: runs of consecutive visible buttons.

    A gap ends a group and starts the next. Empty runs are dropped, so a row of
    nothing but gaps yields no group at all.
    """
    groups: list[list[int]] = []
    run: list[int] = []
    for i in chunk:
        if rows[i].visible:
            run.append(i)
        elif run:
            groups.append(run)
            run = []
    if run:
        groups.append(run)
    return groups


def round_codes(rows: Sequence[_HasVisible], per_row: int,
                first: int) -> list[int]:
    """Rounded-corner code per button: 1 left, 2 right, 3 both, 0 square.

    Ported from ``ApplicationWindow.realignbuttons``. Hidden buttons get a code
    of their own that nothing draws.
    """
    codes: list[int] = []
    n = len(rows)
    for i in range(n):
        pos = (i - first) % per_row
        next_hidden = (pos < per_row - 1 and i + 1 < n and not rows[i + 1].visible)
        prev_hidden = (pos > 0 and i > 0 and not rows[i - 1].visible)
        if pos == 0:
            codes.append(3 if (i == n - 1 or next_hidden) else 1)
        elif pos < per_row - 1 and i != n - 1:
            if prev_hidden and next_hidden:
                codes.append(3)
            elif prev_hidden:
                codes.append(1)
            elif next_hidden:
                codes.append(2)
            else:
                codes.append(0)
        elif prev_hidden:
            codes.append(3)
        else:
            codes.append(2)
    return codes


def corner_radii(position: int, size: int, radius: int = 6) -> tuple[int, int]:
    """Left and right corner radius for a button at ``position`` in a group.

    A group of one is rounded on both sides; the ends of a longer group are
    rounded outwards only, and everything between them is square, so the run
    reads as one welded control rather than as separate buttons.
    """
    left = radius if position == 0 else 0
    right = radius if position == size - 1 else 0
    return left, right
