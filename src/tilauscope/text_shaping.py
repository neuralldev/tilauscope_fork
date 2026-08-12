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
# TiLau 2026
# -*- coding: utf-8 -*-

"""Fonts and text preparation shared by everything TilauScope prints.

Single source of font choice and bidirectional shaping for the three
operator-facing renderers (fpdf roast plan, QPainter label sheets, Pillow
Niimbot bitmaps) — none of which shape text or fall back fonts on their own.
Qt does both itself, so it only needs the font resolution part.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

_logd: Final[logging.Logger] = logging.getLogger("tilau")

# ── Font files ───────────────────────────────────────────────────────────────
# DejaVu Sans is the body face everywhere: proportional, carries the three
# styles the documents use, covers latin/greek/cyrillic/arabic/hebrew, and is
# freely redistributable (licenses/DejaVu-Fonts.txt). It has no CJK, which is
# what WenQuanYi Zen Hei is for — already shipped for the graphs, and it carries
# latin and cyrillic too, so a mixed Chinese/latin string stays in one face.
_SANS: Final[dict] = {
    (False, False): 'DejaVuSans.ttf',
    (True,  False): 'DejaVuSans-Bold.ttf',
    (False, True):  'DejaVuSans-Oblique.ttf',
    (True,  True):  'DejaVuSans-BoldOblique.ttf',
}
_CJK_FILE: Final[str] = 'WenQuanYiZenHei-01.ttf'


@lru_cache(maxsize=1)
def font_dir() -> "Path | None":
    """Directory holding the bundled fonts, or None if it cannot be located."""
    try:
        from artisanlib.util import getResourcePath
        base = Path(getResourcePath())
        return base if base.is_dir() else None
    except Exception as e:                      # never let typography raise
        _logd.warning("text_shaping: resource path unavailable (%s)", e)
        return None


@lru_cache(maxsize=8)
def sans_path(bold: bool = False, italic: bool = False) -> "Path | None":
    """Path to the Unicode body face, or None on a checkout without the fonts.

    Falls back to the regular cut when a style is not bundled rather than
    returning nothing: a document in the wrong weight beats no document.
    """
    base = font_dir()
    if base is None:
        return None
    for key in ((bold, italic), (bold, False), (False, False)):
        path = base / _SANS[key]
        if path.is_file():
            return path
    _logd.warning("text_shaping: %s missing from %s", _SANS[(False, False)], base)
    return None


@lru_cache(maxsize=1)
def cjk_path() -> "Path | None":
    """Path to the CJK face, or None if it is not bundled."""
    base = font_dir()
    if base is None:
        return None
    path = base / _CJK_FILE
    return path if path.is_file() else None


# ── Script detection ─────────────────────────────────────────────────────────
# Checked on the text itself rather than on the active locale: a bean name, a
# farm or a roaster model can be Arabic or Chinese in an English session, and a
# locale test would miss it. Pure and testable as a result.
RTL_RANGES: Final[tuple] = ((0x0590, 0x05FF), (0x0600, 0x06FF), (0x0700, 0x074F),
                            (0x0750, 0x077F), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF))
ARABIC_RANGES: Final[tuple] = ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF))
CJK_RANGES: Final[tuple] = ((0x1100, 0x11FF), (0x2E80, 0x2EFF), (0x3000, 0x303F),
                            (0x3040, 0x30FF), (0x3130, 0x318F), (0x3400, 0x4DBF),
                            (0x4E00, 0x9FFF), (0xA960, 0xA97F), (0xAC00, 0xD7AF),
                            (0xF900, 0xFAFF), (0xFF00, 0xFFEF))


def in_ranges(ch: str, ranges: tuple) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ranges)


def has_script(text: Any, ranges: tuple) -> bool:
    """True when any character of `text` falls in `ranges`."""
    if not text:
        return False
    return any(in_ranges(ch, ranges) for ch in str(text))


# ── Bidirectional scripts ────────────────────────────────────────────────────
def shape_bidi(text: Any) -> Any:
    """Render Arabic, Persian and Hebrew readably in a document or a bitmap.

    fpdf and Pillow both draw glyphs in the order they are given them, with no
    shaping and no bidirectional reordering. Left alone, Arabic comes out as a
    row of disconnected letters and any number inside a right-to-left sentence
    lands on the wrong side of it.

    Two steps, the same pair Artisan already uses for its own graph labels
    (``arabicReshape`` in artisanlib/main.py), so every surface agrees:

    1. ``arabic_reshaper`` replaces each letter with its contextual form
       (initial / medial / final), which is what joins the script. Skipped for
       Hebrew, which does not join.
    2. ``get_display`` applies the Unicode bidirectional algorithm, putting the
       run in visual order — this is what moves "200" back where it belongs.

    Order matters and is not interchangeable: reshaping AFTER reordering would
    compute the joining forms on a reversed string and unjoin it again.
    Left-to-right text is returned untouched, so the common path costs one range
    scan and nothing else.
    """
    if not text:
        return text
    s = str(text)
    if not has_script(s, RTL_RANGES):
        return text
    try:
        if has_script(s, ARABIC_RANGES):
            import arabic_reshaper
            s = arabic_reshaper.reshape(s)
        from bidi import get_display
        return str(get_display(s))
    except Exception as e:                      # never let typography stop a print
        _logd.warning("text_shaping: bidi rendering unavailable (%s)", e)
        return text


# ── Pillow ───────────────────────────────────────────────────────────────────
@lru_cache(maxsize=64)
def pil_font(size: int, bold: bool = False, cjk: bool = False) -> Any:
    """A Pillow font at `size`, or Pillow's own default if nothing is bundled.

    Cached: the Niimbot builders reload the same handful of sizes for every
    label, and FreeType parsing is not free.
    """
    from PIL import ImageFont
    path = cjk_path() if cjk else sans_path(bold=bold)
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError as e:
            _logd.warning("text_shaping: %s unusable (%s)", path.name, e)
    return ImageFont.load_default()


def shaping_draw(img: Any) -> Any:
    """An ImageDraw that shapes right-to-left text and swaps in the CJK face.

    Pillow is built here without Raqm, so ``draw.text`` performs no joining, no
    bidirectional reordering and no font fallback — a Chinese bean name on a
    latin-only face prints as a row of empty boxes. Both are handled once, on
    the drawing object, rather than at the ~57 call sites the label builders
    have between them: one missed site is a single blank line on one label,
    which is exactly the defect nobody catches in review.

    ``textlength`` and ``textbbox`` get the same treatment so that the measuring
    the builders do to fit text into a 50 mm roll matches what is drawn.
    """
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    for name in ('text', 'textlength', 'textbbox'):
        setattr(draw, name, _shaping_wrapper(getattr(draw, name)))
    return draw


def _shaping_wrapper(fn: Any) -> Any:
    """Wrap one ImageDraw text method with the bidi pass and the CJK swap."""
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        args, kwargs = _shape_call(args, kwargs)
        return fn(*args, **kwargs)
    return wrapped


def _shape_call(args: tuple, kwargs: dict) -> "tuple[tuple, dict]":
    """Shape the string argument and pick the face that can draw it.

    text/textlength/textbbox all take the string second at the latest (after the
    anchor point, which ``textlength`` does not have), and it can also arrive as
    ``text=``. The argument is located rather than assumed — an override with a
    fixed signature is how the roast plan lost its graph labels once already.
    """
    if 'text' in kwargs:
        text = kwargs['text']
        kwargs['text'] = shape_bidi(text)
    elif args:
        index = 1 if len(args) > 1 and not isinstance(args[0], str) else 0
        text = args[index]
        mutable = list(args)
        mutable[index] = shape_bidi(text)
        args = tuple(mutable)
    else:
        return args, kwargs
    font = kwargs.get('font')
    if font is not None and has_script(text, CJK_RANGES):
        kwargs['font'] = _cjk_twin(font)
    return args, kwargs


def _cjk_twin(font: Any) -> Any:
    """The CJK face at the same size, or `font` unchanged if unavailable."""
    size = getattr(font, 'size', None)
    if size is None or cjk_path() is None:
        return font
    return pil_font(int(size), cjk=True)
