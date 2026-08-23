"""Base stylesheet for TilauScope screens: one token-driven Qt stylesheet applied
to the root of each TilauScope top-level window (never QApplication or
Artisan's appWindow — TilauScope lives inside Artisan's process). Spec: ``wiki/Theme-QSS-Spec.md``.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

from tilauscope.tilauscope_types import THEME

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

__all__ = ['apply_tilau_theme', 'base_qss', 'mono_family', 'restyle', 'tint', 'tooltip_qss',
           'with_tooltip']

_log = logging.getLogger(__name__)

_MONO_FAMILY: str | None = None


def mono_family() -> str:
    """Return the family name of the bundled JetBrains Mono, registering it first.

    Registration is lazy (needs a QApplication, imported before one exists);
    the real family name is read back from Qt rather than assumed.
    """
    global _MONO_FAMILY   # noqa: PLW0603
    if _MONO_FAMILY:
        return _MONO_FAMILY
    fallback = 'Menlo' if sys.platform == 'darwin' else 'Consolas'
    try:
        from PyQt6.QtGui import QFontDatabase  # noqa: PLC0415
        from PyQt6.QtWidgets import QApplication  # noqa: PLC0415
        # Touching QFontDatabase before a QApplication exists does not
        # raise — it segfaults, so the except below would never see it. Return
        # the fallback without caching, so the real registration still happens
        # on the first call made once the application is up.
        if QApplication.instance() is None:
            return fallback
        here = os.path.dirname(__file__)
        families: list[str] = []
        # Both faces: a sheet asking for font-weight bold needs the bold file
        # registered too, or Qt synthesises a smeared fake bold.
        for name in ('JetBrainsMono-Regular.ttf', 'JetBrainsMono-Bold.ttf'):
            fid = QFontDatabase.addApplicationFont(os.path.join(here, name))
            if fid != -1:
                families += QFontDatabase.applicationFontFamilies(fid)
            else:
                _log.warning('theme: could not register %s', name)
        _MONO_FAMILY = families[0] if families else fallback
        if not families:
            _log.warning('theme: no bundled mono registered, falling back to %s',
                         fallback)
    except Exception:  # noqa: BLE001
        _log.exception('theme: font registration failed, falling back to %s', fallback)
        _MONO_FAMILY = fallback
    return _MONO_FAMILY


def tooltip_qss() -> str:
    """Return the QToolTip rule alone.

    Qt does not cascade tooltip styling: it styles the tip with the sheet of
    the *first* ancestor of the hovered widget that has a non-empty stylesheet.
    A container styled with something as small as ``background: transparent``
    therefore hides the window's QToolTip rule and the tip falls back to the
    system white. Append this to any such intermediate sheet.
    """
    t = THEME
    return f"""
QToolTip {{
    background-color: {t['SURFACE']};
    color: {t['TEXT']};
    border: 1px solid {t['BORDER']};
    border-radius: 4px;
    padding: 5px 7px;
    font-size: 12px;
}}
"""


def with_tooltip(qss: str) -> str:
    """Return *qss* carrying the theme's tooltip rule.

    Any widget given its own stylesheet becomes the sheet Qt styles its tooltip
    from, and a sheet that says nothing about QToolTip leaves the tip system
    white on a dark screen. A styled widget that also carries a tooltip must go
    through here — the alternative is remembering it at every call site, which
    is how the white tips got there in the first place.
    """
    return qss if 'QToolTip' in qss else qss + tooltip_qss()


def base_qss(ground: bool = True) -> str:
    """Return the base stylesheet, built from THEME.

    `ground=False` drops the `QWidget { color }` and window `background-color`
    rules, keeping only typography/controls — needed for panels composing with
    transparency and any window with `WA_TranslucentBackground` (mutually
    exclusive with `ground=True`, or the ground paints over the rounded card).
    On macOS a QComboBox popup is a separate top-level window, so
    ``QComboBox QAbstractItemView`` styles it on Windows only — see
    ``devices._styled_combo_view`` for the macOS path.
    """
    t = THEME
    mono = mono_family()
    # The ground paints the window only, not every widget in it: containers
    # inherit the dialog's background by showing through. See wiki/Theme-QSS-Spec.md.
    ground_qss = f"""
QWidget {{ color: {t['TEXT']}; }}
QDialog, QMainWindow {{ background-color: {t['BG']}; }}
""" if ground else ""
    # The ground sets a size, never a family: a monospaced face app-wide is
    # wider than the system proportional one and overflows control labels.
    # Prose reads in the system face; figures use `variant="mono"` or a
    # readout variant instead.
    return f"""
/* ---- ground ---- */
QWidget {{ font-size: 12px; }}
{ground_qss}
/* Counters, temperatures, timers, the measurement cards — anything whose
   glyphs must not move as the value changes. */
QLabel[variant="mono"],
QLabel[variant="readout"],
QLabel[variant="readout-sm"] {{ font-family: '{mono}', monospace; }}
QLabel {{ background: transparent; color: {t['TEXT']}; }}
QLabel[variant="caption"]   {{ color: {t['SUBTEXT']}; font-size: 11px; }}
QLabel[variant="secondary"] {{ color: {t['SUBTEXT']}; }}
QLabel[variant="title"]   {{ color: {t['TEXT']}; font-size: 14px; font-weight: 600; }}
QLabel[variant="muted"]   {{ color: {t['OVERLAY0']}; }}
/* The small spaced caps that name the value underneath them. Uniformly
   SUBTEXT across the app, so the role carries the colour. */
QLabel[variant="eyebrow"] {{
    color: {t['SUBTEXT']};
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1.5px;
}}
/* The two glanceable-number sizes: `readout` for a floating card read at
   arm's length while both hands are busy, `readout-sm` for the same job
   inside the in-roast panel where the number shares the width.
   Neither sets a colour — a readout's colour is the measurement talking
   (accent, hue, on-target, out-of-band), so it stays at the call site. */
QLabel[variant="readout"]    {{ font-size: 34px; font-weight: bold; }}
QLabel[variant="readout-sm"] {{ font-size: 19px; font-weight: bold; }}
QFrame[variant="card"] {{
    background-color: {t['SURFACE']};
    border: 1px solid {t['BORDER']};
    border-radius: 8px;
}}
QFrame[variant="sep"] {{ background-color: {t['BORDER']}; border: none; }}

/* ---- buttons ----
   SURFACE fill is what the app already draws for an ordinary button (41 of
   the pre-existing sheets against 13 for a BORDER fill); transparent, the
   other common form, is the ghost variant below. */
QPushButton {{
    background-color: {t['SURFACE']};
    color: {t['TEXT']};
    border: 1px solid {t['BORDER']};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover    {{ background-color: {t['BORDER']}; border-color: {t['SURFACE1']}; }}
QPushButton:pressed  {{ background-color: {t['SURFACE1']}; }}
QPushButton:disabled {{
    background-color: {t['SURFACE']};
    color: {t['OVERLAY0']};
    border-color: {t['BORDER']};
}}
QPushButton:focus {{ border-color: {t['ACCENT']}; }}

QPushButton[variant="primary"] {{
    background-color: {t['ACCENT']}; color: {t['BG']};
    border: none; font-weight: 600;
}}
QPushButton[variant="primary"]:hover   {{ background-color: {t['LAVENDER']}; }}
QPushButton[variant="primary"]:pressed {{ background-color: {t['SAPPHIRE']}; }}
QPushButton[variant="primary"]:disabled {{
    background-color: {t['SURFACE1']}; color: {t['OVERLAY0']};
}}

QPushButton[variant="danger"] {{
    background-color: {t['CRITICAL']}; color: {t['BG']};
    border: none; font-weight: 600;
}}
QPushButton[variant="danger"]:hover {{ background-color: {t['PINK']}; }}

/* Destructive, but standing in a row of equals — a Delete beside Update and
   Add. The filled `danger` would make removal the loudest thing on the row.
   Hover lifts the ground one step and keeps the red text, so a red icon baked
   into the button stays visible; filling with red would swallow it. */
QPushButton[variant="danger-outline"] {{
    background: transparent; color: {t['CRITICAL']};
    border: 1px solid {t['CRITICAL']};
}}
QPushButton[variant="danger-outline"]:hover {{
    background-color: {t['BORDER']};
}}
QPushButton[variant="danger-outline"]:pressed {{
    background-color: {t['SURFACE1']};
}}
QPushButton[variant="danger-outline"]:disabled {{
    background: transparent;
    color: {t['OVERLAY0']}; border-color: {t['BORDER']};
}}

QPushButton[variant="outline"] {{
    background: transparent; color: {t['SUBTEXT']};
    border: 1px solid {t['BORDER']};
}}
QPushButton[variant="outline"]:hover {{
    color: {t['ACCENT']}; border-color: {t['ACCENT']};
}}
QPushButton[variant="outline"]:disabled {{
    color: {t['OVERLAY0']}; border-color: {t['BORDER']};
}}

/* A square button sized in code — a header glyph, a +/- stepper. The base
   padding is 6px 12px, which on a 24–28px fixed square leaves no room at all
   and clips the glyph away entirely. Say `icon` and the padding goes. */
QPushButton[variant="icon"] {{ padding: 0; }}

QPushButton[variant="ghost"] {{
    background: transparent; border: none; color: {t['SUBTEXT']};
}}
QPushButton[variant="ghost"]:hover    {{ color: {t['TEXT']}; }}
QPushButton[variant="ghost"]:disabled {{ color: {t['OVERLAY0']}; }}

/* ---- text inputs ----
   QSS switches a widget off its native palette, so every state has to be
   written out or the widget goes unreadable in a state nobody tested. */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {t['SURFACE']};
    color: {t['TEXT']};
    border: 1px solid {t['BORDER']};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {t['ACCENT']};
    selection-color: {t['BG']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['ACCENT']}; }}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {t['BG']}; color: {t['OVERLAY0']};
}}
QLineEdit[readOnly="true"] {{
    background-color: {t['BG']}; color: {t['SUBTEXT']};
}}

/* ---- combo ---- */
QComboBox {{
    background-color: {t['SURFACE']};
    color: {t['TEXT']};
    border: 1px solid {t['BORDER']};
    border-radius: 6px;
    padding: 5px 8px;
}}
QComboBox:hover {{ border-color: {t['SURFACE2']}; }}
QComboBox:focus, QComboBox:on {{ border-color: {t['ACCENT']}; }}
QComboBox:disabled {{ background-color: {t['BG']}; color: {t['OVERLAY0']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {t['SURFACE']};
    color: {t['TEXT']};
    border: 1px solid {t['BORDER']};
    selection-background-color: {t['ACCENT']};
    selection-color: {t['BG']};
    outline: none;
}}

/* ---- checkable ---- */
QCheckBox, QRadioButton {{
    background: transparent; color: {t['TEXT']}; spacing: 6px;
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t['OVERLAY0']}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    background-color: {t['SURFACE']};
    border: 1px solid {t['SURFACE2']};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {t['ACCENT']}; border-color: {t['ACCENT']};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background-color: {t['BG']}; border-color: {t['BORDER']};
}}

/* ---- group / tabs ---- */
QGroupBox {{
    background: transparent;
    border: 1px solid {t['BORDER']};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: {t['SUBTEXT']};
}}
QTabWidget::pane {{
    border: 1px solid {t['BORDER']};
    border-radius: 8px;
    background-color: {t['BG']};
}}
QTabBar::tab {{
    background: transparent;
    color: {t['SUBTEXT']};
    padding: 6px 14px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {t['TEXT']}; border-bottom-color: {t['ACCENT']}; }}
QTabBar::tab:hover:!selected {{ color: {t['TEXT']}; }}

/* ---- tables / lists ---- */
QTableWidget, QTableView, QListWidget, QListView, QTreeView {{
    background-color: {t['SURFACE']};
    color: {t['TEXT']};
    border: 1px solid {t['BORDER']};
    border-radius: 8px;
    gridline-color: {t['BORDER']};
    selection-background-color: {t['ACCENT']};
    selection-color: {t['BG']};
    outline: none;
}}
QTableWidget::item, QListWidget::item {{ padding: 4px 6px; }}
QTableWidget::item:selected, QListWidget::item:selected {{
    background-color: {t['ACCENT']}; color: {t['BG']};
}}
QHeaderView::section {{
    background-color: {t['BORDER']};
    color: {t['SUBTEXT']};
    border: none;
    border-right: 1px solid {t['BG']};
    padding: 5px 6px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background-color: {t['BORDER']}; border: none; }}

/* ---- scroll / progress / tooltip ---- */
/* A QScrollArea's viewport is a plain child QWidget. The ground rule used to
   paint it by accident; now that the ground paints the window instead, the
   viewport has to be named explicitly or Qt falls back to the system white.
   The `> QWidget > QWidget` form is the documented idiom and reaches the
   viewport without touching QListWidget / QTableWidget, which are also scroll
   areas but are deliberately opaque. */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical   {{ background-color: {t['BG']}; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background-color: {t['BG']}; height: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background-color: {t['BORDER']}; border-radius: 4px; min-height: 20px;
}}
QScrollBar::handle:horizontal {{
    background-color: {t['BORDER']}; border-radius: 4px; min-width: 20px;
}}
QScrollBar::handle:hover {{ background-color: {t['SURFACE2']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{
    background-color: {t['SURFACE']};
    color: {t['TEXT']};
    border: 1px solid {t['BORDER']};
    border-radius: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {t['ACCENT']}; border-radius: 5px; }}

{tooltip_qss()}
"""


def apply_tilau_theme(root: QWidget, ground: bool = True) -> None:
    """Apply the base stylesheet to a TilauScope window or panel.

    Call once, at construction. `root` must be TilauScope's own — never
    Artisan's main window, never the QApplication.

    **Check what lives under `root` before calling this.** A stylesheet
    cascades to every descendant, so a window that hosts a widget drawing its
    own colours must not receive it at the root: ``TilauScope`` in
    displayscope.py puts the roast curve, which paints its whole surface
    itself, beside its control panel. Such a window applies the base to its own
    sub-containers instead — see ``TilauScope.init_ui``.

    Pass ``ground=False`` for a panel that composes with transparency **and for
    every window that sets ``WA_TranslucentBackground``** — the ground paints
    the whole rectangle, squaring off the rounded card such a window draws
    inside itself. See ``base_qss``.
    """
    root.setStyleSheet(base_qss(ground))


def tint(token: str, alpha: float) -> str:
    """Return ``rgba(r, g, b, alpha)`` for a THEME token.

    A translucent wash of a palette colour — the usual shape is a chip or a
    pill whose border and text are the token and whose ground is the same
    colour at 5–20 %. Written by hand that ground is a decimal triple
    (``rgba(166, 227, 161, 0.08)``), which no search for the token or for its
    hex will ever find: retune the token and the border moves while the fill
    stays where it was. Derive it here instead and the three follow together.
    """
    h = THEME[token].lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet to `widget` after a dynamic property changed.

    Qt does not restyle on a property change; without this an updated
    ``variant`` has no visible effect.
    """
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
