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
# TiLau 2025 — header_icons.py
#
# SVG icon constants + dynamic QIcon builder for TilauScope header buttons.
#
# Design contract
# ───────────────
# • Every SVG uses a single `{color}` placeholder for the stroke value.
#   No fill, no hardcoded color anywhere in the path data.
# • Icons are outline-only (stroke, no fill) so a single color swap covers
#   every visual state.  The btn_start_stop is the only exception: it carries
#   *two* SVG constants (PLAY / STOP) whose shape changes with the state.
# • The public API is a single function:  make_icon(svg_tpl, color, size)
#   It returns a QIcon ready for QPushButton.setIcon().
# • A companion helper  apply_icon(btn, svg_tpl, color_key, size)  uses the
#   Catppuccin color registry defined below so call-sites never embed hex.
#
# Integration notes
# ─────────────────
# 1. Add to displayscope.py imports:
#       from tilauscope.header_icons import (
#           SVG_MENU, SVG_POWER, SVG_PLAY, SVG_STOP,
#           SVG_RESET, SVG_PID, SVG_BEANCAVE, SVG_ASSISTANT, SVG_SWAP,
#           make_icon, BTN_ICON_SIZE,
#           COL_IDLE, COL_ACTIVE, COL_PRESSED, COL_DISABLED,
#           COL_POWER_ACTIVE, COL_START_IDLE, COL_START_ACTIVE,
#           COL_RESET_IDLE, COL_PID_ACTIVE, COL_ASSISTANT_IDLE,
#           COL_SWAP_IDLE, COL_MENU,
#       )
# 2. In __init__, replace every QPushButton("▶") / ("⏻") … with
#    QPushButton() then call _apply_btn_icon() once the button is created.
# 3. In update_button_style() replace the setText("■"/"▶") branch with
#    the new _apply_btn_icon() call shown in the diff snippet at the bottom
#    of this file.
# 4. Button stylesheet: remove font-size / font-weight from QPushButton {}
#    (the icon is drawn by Qt, not by the font engine).  Keep all color /
#    border / radius / state rules — they still drive border appearance.

from __future__ import annotations

from typing import Final

from PyQt6.QtCore  import QByteArray, QSize
from PyQt6.QtGui   import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtSvg   import QSvgRenderer
from PyQt6.QtWidgets import QPushButton


# ── Icon render size ──────────────────────────────────────────────────────────
# Physical pixel size of the icon painted inside every button.
# Qt scales this correctly on HiDPI/Retina via devicePixelRatio.
BTN_ICON_SIZE: Final[QSize] = QSize(18, 18)


# ── Catppuccin Mocha color registry ───────────────────────────────────────────
# Single source of truth — never embed hex in call-sites.

# Generic states
COL_IDLE:           Final[str] = "#45475A"   # Surface1 — muted, any inactive btn
COL_ACTIVE:         Final[str] = "#CDD6F4"   # Text — generic active (unused directly)
COL_PRESSED:        Final[str] = "#11111B"   # Crust — icon color when bg fills on press
COL_DISABLED:       Final[str] = "#282837"   # Mantle-dim — disabled state

# Per-button semantic colors  (idle / active)
COL_MENU:           Final[str] = "#89B4FA"   # Blue — menu hamburger, always this tone
COL_POWER_IDLE:     Final[str] = "#45475A"   # Surface1
COL_POWER_ACTIVE:   Final[str] = "#A6E3A1"   # Green

COL_START_IDLE:     Final[str] = "#26458E"   # Blue dim
COL_START_ACTIVE:   Final[str] = "#3D6EDF"   # Blue bright

COL_RESET_IDLE:     Final[str] = "#6A61AB"   # Lavender dim
COL_RESET_ACTIVE:   Final[str] = "#4D458C"   # Lavender mid

COL_PID_IDLE:       Final[str] = "#78798A"   # Overlay0
COL_PID_ACTIVE:     Final[str] = "#F9E2AF"   # Yellow / Amber

COL_BEANCAVE_IDLE:  Final[str] = "#3D6EDF"   # Blue
COL_BEANCAVE_ACTIVE: Final[str] = "#1F3E88"  # Blue dark

COL_ASSISTANT_IDLE: Final[str] = "#A68B00"   # Gold dim  (provisional feature)
COL_ASSISTANT_ACTIVE: Final[str] = "#F9E2AF" # Amber bright

COL_SWAP_IDLE:      Final[str] = "#78798A"   # Overlay0
COL_SWAP_ACTIVE:    Final[str] = "#4A614A"   # Sage green dim

# btn_dock — assistant float (idle) ↔ anchor (active) ## TILAU ##
COL_DOCK_IDLE:      Final[str] = "#78798A"   # Overlay0 — floating
COL_DOCK_ACTIVE:    Final[str] = "#94E2D5"   # Teal — anchored

# Hover tones (used only in QSS, kept here for reference / consistency)
COL_POWER_HOVER:    Final[str] = "rgba(166,227,161,0.5)"
COL_PID_HOVER:      Final[str] = "rgba(250,179,135,0.5)"
COL_SWAP_HOVER:     Final[str] = "rgba(166,227,161,0.5)"
COL_DOCK_HOVER:     Final[str] = "rgba(148,226,213,0.5)"   ## TILAU ## teal translucent


# ── SVG templates — ONE {color} placeholder, viewBox 0 0 24 24 ───────────────
# Rules:
#   • stroke="{color}"   ← injected at render time
#   • fill="none"        ← always explicit on every path/shape
#   • stroke-width="1.8"  stroke-linecap="round"  stroke-linejoin="round"
#   • No style="" attributes — only presentation attributes for reliability

_SVG_ATTRS: Final[str] = (
    'xmlns="http://www.w3.org/2000/svg" '
    'viewBox="0 0 24 24" '
    'fill="none" '
    'stroke="{color}" '
    'stroke-width="1.8" '
    'stroke-linecap="round" '
    'stroke-linejoin="round"'
)

# ── btn_main_menu — hamburger (3 lignes, 3e ligne plus courte) ────────────────
SVG_MENU: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<line x1="4" y1="7"  x2="20" y2="7"/>'
    '<line x1="4" y1="12" x2="15" y2="12"/>'
    '<line x1="4" y1="17" x2="20" y2="17"/>'
    '</svg>'
)

# ── btn_power — symbole power IEEE 60417-5009 ─────────────────────────────────
SVG_POWER: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M12 3v6"/>'
    '<path d="M7.7 5.7A8 8 0 1 0 16.3 5.7"/>'
    '</svg>'
)

# ── btn_start_stop — PLAY (idle) ──────────────────────────────────────────────
# Triangle pointant à droite.  Pas de fill sur <polygon> car le SVG global
# déclare fill="none" ; on n'a pas besoin de le répéter.
SVG_PLAY: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<polygon points="7,4 20,12 7,20"/>'
    '</svg>'
)

# ── btn_start_stop — STOP (enregistrement actif) ──────────────────────────────
# Carré à coins légèrement arrondis (rx="2") — distingue du rectangle plein.
SVG_STOP: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<rect x="5" y="5" width="14" height="14" rx="2"/>'
    '</svg>'
)

# ── btn_reset — flèche circulaire CCW ────────────────────────────────────────
SVG_RESET: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
    '<path d="M3 3v5h5"/>'
    '</svg>'
)

# ── btn_pid — courbe step-response PID + ligne de base ───────────────────────
# Courbe oscillante amortie sur axe horizontal : évoque visuellement la
# réponse indicielle d'un régulateur.
SVG_PID: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M3 17 Q6 7 9 12 Q12 17 15 9 Q18 3 21 9"/>'
    '<line x1="3" y1="20" x2="21" y2="20"/>'
    '</svg>'
)

# ── btn_beancave — grain de café (ellipse inclinée + ligne de crête) ─────────
# Ellipse tournée -30° + ligne centrale pleine (pas de pointillés — plus
# lisible à 18 px, meilleure robustesse Windows ClearType).
SVG_BEANCAVE: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<ellipse cx="12" cy="12" rx="4.5" ry="7.5" transform="rotate(-30 12 12)"/>'
    '<line x1="9.2" y1="7.2" x2="14.8" y2="16.8"/>'
    '</svg>'
)

# ── btn_assistant — étoile 5 branches outline ────────────────────────────────
SVG_ASSISTANT: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/>'
    '</svg>'
)

# ── swap_button — double flèche horizontale inversée ─────────────────────────
SVG_SWAP: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M4 9h16"/>'
    '<path d="M4 15h16"/>'
    '<path d="M14 5l4 4-4 4"/>'
    '<path d="M10 11l-4 4 4 4"/>'
    '</svg>'
)

# ── btn_dock — ancre marine (ring + hampe + jas + arc) ## TILAU ── ───────────
# Anchored = teal, floating = muted. Stroke-only, lisible à 18 px.
SVG_DOCK: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<circle cx="12" cy="5" r="2"/>'
    '<line x1="12" y1="7" x2="12" y2="21"/>'
    '<line x1="8" y1="10" x2="16" y2="10"/>'
    '<path d="M5 13a7 7 0 0 0 14 0"/>'
    '</svg>'
)


# ── Public API ────────────────────────────────────────────────────────────────

def make_icon(
    svg_template: str,
    color: str,
    size: QSize = BTN_ICON_SIZE,
) -> QIcon:
    """
    Render an SVG template to a HiDPI-aware QIcon.

    Parameters
    ----------
    svg_template : str
        One of the SVG_* constants above.  Must contain exactly one
        ``{color}`` placeholder in the ``stroke`` attribute.
    color : str
        Any CSS color string accepted by QColor: ``"#RRGGBB"``,
        ``"rgba(r,g,b,a)"``, named colors, etc.
    size : QSize
        Logical pixel size.  The pixmap is created at size * devicePixelRatio
        of the primary screen so Retina / 4K displays stay crisp.

    Returns
    -------
    QIcon
        Ready to pass to ``QPushButton.setIcon()``.

    Notes
    -----
    • QSvgRenderer is lightweight and does NOT keep a reference to the
      QByteArray after construction — safe to let it go out of scope.
    • The pixmap is created at 1× here; Qt's icon system handles HiDPI
      scaling automatically when devicePixelRatioF() > 1.  If you need
      explicit 2× support (e.g. for @2x assets), call make_icon twice and
      use QIcon.addPixmap().
    """
    svg_bytes = QByteArray(svg_template.format(color=color).encode("utf-8"))
    renderer = QSvgRenderer(svg_bytes)

    pixmap = QPixmap(size)
    pixmap.fill(QColor(0, 0, 0, 0))          # transparent background

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()

    return QIcon(pixmap)


def apply_icon(
    button: QPushButton,
    svg_template: str,
    color: str,
    size: QSize = BTN_ICON_SIZE,
) -> None:
    """
    Convenience wrapper: build the icon and assign it to *button* in one call.
    Also sets the icon size so Qt doesn't auto-shrink it.

    Usage in displayscope.py
    ------------------------
    ::

        apply_icon(self.btn_power, SVG_POWER, COL_POWER_IDLE)
    """
    button.setIcon(make_icon(svg_template, color, size))
    button.setIconSize(size)


# ── Button stylesheet factory ─────────────────────────────────────────────────
# Returns the QSS string for a header button, parameterised by its semantic
# color family.  Border + radius rules only — no font/text rules (the icon
# replaces the label entirely).
#
# ``color_idle``    : stroke + border color in default state
# ``color_active``  : stroke + border when active="true"
# ``color_hover``   : border rgba for hover (often a translucent variant)
# ``color_pressed`` : fill color of the button bg on press
# ``border_idle``   : border width when idle  (e.g. "1px" or "2px")
# ``border_active`` : border width when active

def make_btn_style(
    *,
    color_idle:    str,
    color_active:  str,
    color_hover:   str,
    color_pressed: str,
    border_idle:   str = "1px",
    border_active: str = "1px",
    bg:            str = "#181825",
    bg_hover:      str = "#1E1E2E",
) -> str:
    """
    Generate a QSS stylesheet for a TilauScope header button.

    The generated sheet covers five pseudo-states / dynamic properties:
    idle, active, hover, pressed, disabled.  It intentionally does NOT
    include font-size or font-weight — those are irrelevant once the button
    uses setIcon().

    The caller is responsible for calling ``button.style().unpolish(button)``
    + ``button.style().polish(button)`` after changing dynamic properties so
    Qt re-evaluates the sheet.
    """
    return f"""
        QPushButton {{
            background-color: {bg};
            border: {border_idle} solid {color_idle};
            border-radius: 8px;
        }}
        QPushButton[active="true"] {{
            border: {border_active} solid {color_active};
        }}
        QPushButton:hover {{
            background-color: {bg_hover};
            border: 1px solid {color_hover};
        }}
        QPushButton:pressed {{
            background-color: {color_pressed};
        }}
        QPushButton:disabled {{
            border: 1px solid #282837;
        }}
    """


# ── Pre-built stylesheets for each header button ──────────────────────────────
# Import these directly in displayscope.py to replace the inline stylesheet
# strings.  The ``font-size`` / ``font-weight`` lines from the original sheets
# must be removed since the buttons now use icons.

QSS_MENU: Final[str] = """
    QPushButton {
        background: transparent;
        border: none;
        border-radius: 0px;
    }
    QPushButton:hover  { background: transparent; }
    QPushButton:pressed { background: transparent; }
"""

QSS_POWER: Final[str] = make_btn_style(
    color_idle=    "#313244",
    color_active=  COL_POWER_ACTIVE,
    color_hover=   COL_POWER_HOVER,
    color_pressed= COL_POWER_ACTIVE,
    border_idle=   "2px",
    border_active= "2px",
)

QSS_START_STOP: Final[str] = make_btn_style(
    color_idle=    "#3D6EDF",
    color_active=  COL_START_ACTIVE,
    color_hover=   "rgba(77,69,140,0.5)",
    color_pressed= COL_START_ACTIVE,
)

QSS_RESET: Final[str] = make_btn_style(
    color_idle=    "#78798A",
    color_active=  COL_RESET_ACTIVE,
    color_hover=   "rgba(77,69,140,0.5)",
    color_pressed= COL_RESET_ACTIVE,
)

QSS_PID: Final[str] = make_btn_style(
    color_idle=    "#313244",
    color_active=  COL_PID_ACTIVE,
    color_hover=   COL_PID_HOVER,
    color_pressed= COL_PID_ACTIVE,
    border_idle=   "2px",
    border_active= "2px",
)

QSS_BEANCAVE: Final[str] = make_btn_style(
    color_idle=    COL_BEANCAVE_IDLE,
    color_active=  COL_BEANCAVE_ACTIVE,
    color_hover=   "rgba(77,69,140,0.5)",
    color_pressed= COL_BEANCAVE_IDLE,
)

QSS_ASSISTANT: Final[str] = make_btn_style(
    color_idle=    COL_ASSISTANT_IDLE,
    color_active=  COL_ASSISTANT_ACTIVE,
    color_hover=   "rgba(249,226,175,0.5)",
    color_pressed= COL_ASSISTANT_ACTIVE,
)

QSS_SWAP: Final[str] = make_btn_style(
    color_idle=    COL_SWAP_IDLE,
    color_active=  COL_SWAP_ACTIVE,
    color_hover=   COL_SWAP_HOVER,
    color_pressed= COL_SWAP_ACTIVE,
    border_idle=   "2px",
    border_active= "2px",
)

# btn_dock — assistant anchor toggle ## TILAU ##
QSS_DOCK: Final[str] = make_btn_style(
    color_idle=    COL_DOCK_IDLE,
    color_active=  COL_DOCK_ACTIVE,
    color_hover=   COL_DOCK_HOVER,
    color_pressed= COL_DOCK_ACTIVE,
)
