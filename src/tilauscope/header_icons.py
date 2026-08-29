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
# Icons are outline-only (single `{color}` stroke placeholder, no fill) so one
# color swap covers every visual state; apply_icon() uses the Catppuccin
# registry below so call-sites never embed hex.

from __future__ import annotations

from typing import Final

from PyQt6.QtCore  import QByteArray, QSize
from PyQt6.QtGui   import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtSvg   import QSvgRenderer
from PyQt6.QtWidgets import QPushButton

from tilauscope.theme_qss import with_tooltip


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
COL_DISABLED:       Final[str] = "#6C7086"   # Overlay0 — visible disabled icon

# Per-button semantic colors  (idle / active)
# Convention: ACTIVE is always the BRIGHTER tone. update_button_style() passes
# active=enabled, and make_btn_style() paints the [active="true"] border with it,
# so a darker "active" hides both the glyph and the border on the dark ground.
COL_MENU:           Final[str] = "#89B4FA"   # Blue — menu hamburger, always this tone
COL_POWER_IDLE:     Final[str] = "#45475A"   # Surface1
COL_POWER_ACTIVE:   Final[str] = "#A6E3A1"   # Green

COL_START_IDLE:     Final[str] = "#26458E"   # Blue dim
COL_START_ACTIVE:   Final[str] = "#3D6EDF"   # Blue bright
# Ink for a button whose own fill is light (compact START). Light-on-light was
# unreadable — label and glyph both take this instead.
COL_ON_LIGHT_FILL:  Final[str] = "#11111B"   # Crust

COL_RESET_IDLE:     Final[str] = "#4D458C"   # Lavender dim
COL_RESET_ACTIVE:   Final[str] = "#B4BEFE"   # Lavender bright

COL_PID_IDLE:       Final[str] = "#78798A"   # Overlay0
COL_PID_ACTIVE:     Final[str] = "#F9E2AF"   # Yellow / Amber

COL_BEANCAVE_IDLE:  Final[str] = "#2A4C99"   # Blue dim
COL_BEANCAVE_ACTIVE: Final[str] = "#89B4FA"  # Blue bright

COL_ASSISTANT_IDLE: Final[str] = "#A68B00"   # Gold dim  (provisional feature)
COL_ASSISTANT_ACTIVE: Final[str] = "#F9E2AF" # Amber bright

COL_SWAP_IDLE:      Final[str] = "#4A614A"   # Sage green dim
COL_SWAP_ACTIVE:    Final[str] = "#A6E3A1"   # Green bright

# btn_estop — emergency heat cut. The only critical tone of the header.
COL_ESTOP:          Final[str] = "#F38BA8"   # Red

# btn_dock — assistant float (idle) ↔ anchor (active)
COL_DOCK_IDLE:      Final[str] = "#78798A"   # Overlay0 — floating
COL_DOCK_ACTIVE:    Final[str] = "#94E2D5"   # Teal — anchored

# Hover tones (used only in QSS, kept here for reference / consistency)
COL_POWER_HOVER:    Final[str] = "rgba(166,227,161,0.5)"
COL_PID_HOVER:      Final[str] = "rgba(250,179,135,0.5)"
COL_SWAP_HOVER:     Final[str] = "rgba(166,227,161,0.5)"
COL_DOCK_HOVER:     Final[str] = "rgba(148,226,213,0.5)"   # teal translucent


# ── SVG templates — ONE {color} placeholder, viewBox 0 0 24 24 ───────────────
# stroke="{color}" injected at render time; fill="none" always explicit; no
# style="" attributes, only presentation attributes for reliability.

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
# Triangle pointant à droite.
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
# Courbe oscillante amortie : évoque la réponse indicielle d'un régulateur.
SVG_PID: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M3 17 Q6 7 9 12 Q12 17 15 9 Q18 3 21 9"/>'
    '<line x1="3" y1="20" x2="21" y2="20"/>'
    '</svg>'
)

# ── btn_beancave — grain de café (ellipse inclinée + ligne de crête) ─────────
# Ligne pleine (pas de pointillés) — plus lisible à 18 px sous Windows ClearType.
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

# ── btn_estop — flamme barrée : le brûleur est coupé ─────────────────────────
# Names the lever it cuts (BURNER) rather than an abstract "stop", so it cannot
# be read as stopping the recording. Outline-only like every header glyph.
SVG_HEATCUT: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M12 3c3.5 3.2 5.5 5.9 5.5 9a5.5 5.5 0 0 1-11 0c0-1.6.6-3 1.7-4.4'
    ' .7 1.2 1.5 1.9 2.3 2.1-.3-2.5.2-4.7 1.5-6.7z"/>'
    '<line x1="4" y1="20" x2="20" y2="4"/>'
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

# ── Process glyphs — shown inside a TilauProgress ring ────────────────────────
# One per family of long operation. Monochrome strokes, never emoji — colour
# emoji differ across macOS/Windows and cannot take a theme colour.

SVG_PROG_SEARCH: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<circle cx="11" cy="11" r="7"/>'
    '<line x1="16" y1="16" x2="21" y2="21"/>'
    '</svg>'
)

SVG_PROG_DOWNLOAD: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M12 3v12"/>'
    '<path d="M7 10l5 5 5-5"/>'
    '<path d="M4 21h16"/>'
    '</svg>'
)

SVG_PROG_UPLOAD: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M12 21V9"/>'
    '<path d="M7 14l5-5 5 5"/>'
    '<path d="M4 3h16"/>'
    '</svg>'
)

SVG_PROG_AI: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M12 3l2 6.5L20.5 12 14 14.5 12 21l-2-6.5L3.5 12 10 9.5z"/>'
    '</svg>'
)

SVG_PROG_PRINT: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M7 9V4h10v5"/>'
    '<path d="M7 18H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/>'
    '<rect x="7" y="14" width="10" height="7" rx="1"/>'
    '</svg>'
)

SVG_PROG_HEAT: Final[str] = (
    f'<svg {_SVG_ATTRS}>'
    '<path d="M14 14.76V4a2 2 0 0 0-4 0v10.76a4 4 0 1 0 4 0z"/>'
    '</svg>'
)


# ── Public API ────────────────────────────────────────────────────────────────

def make_icon(
    svg_template: str,
    color: str,
    size: QSize = BTN_ICON_SIZE,
) -> QIcon:
    """Render an SVG template (one of the SVG_* constants) to a HiDPI-aware QIcon."""
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
    """Build the icon and assign it to *button*, and set its icon size."""
    button.setIcon(make_icon(svg_template, color, size))
    button.setIconSize(size)


# ── Button stylesheet factory ─────────────────────────────────────────────────
# Returns the QSS string for a header button, parameterised by its semantic
# color family. Border + radius rules only — the icon replaces the label.

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
    fg:            str = "#CDD6F4",
    fg_hover:      str = "#FFFFFF",
) -> str:
    """Generate a QSS stylesheet for a TilauScope header button (idle/active/hover/
    pressed/disabled). Caller must unpolish()+polish() after changing dynamic
    properties so Qt re-evaluates the sheet.
    """
    return with_tooltip(f"""
        QPushButton {{
            background-color: {bg};
            border: {border_idle} solid {color_idle};
            border-radius: 8px;
            color: {fg};
        }}
        QPushButton[active="true"] {{
            border: {border_active} solid {color_active};
        }}
        QPushButton:hover {{
            background-color: {bg_hover};
            border: 2px solid {color_hover};
            color: {fg_hover};
        }}
        QPushButton:pressed {{
            background-color: {color_pressed};
            color: #11111B;
        }}
        QPushButton:disabled {{
            background-color: #252538;
            border: 1px solid #6C7086;
            color: #A6ADC8;
        }}
    """)


# ── Pre-built stylesheets for each header button ──────────────────────────────

QSS_MENU: Final[str] = with_tooltip("""
    QPushButton {
        background: transparent;
        border: none;
        border-radius: 0px;
    }
    QPushButton:hover  { background: transparent; }
    QPushButton:pressed { background: transparent; }
""")

QSS_POWER: Final[str] = make_btn_style(
    color_idle=    "#313244",
    color_active=  COL_POWER_ACTIVE,
    color_hover=   COL_POWER_ACTIVE,
    color_pressed= COL_POWER_ACTIVE,
    border_idle=   "2px",
    border_active= "2px",
)

QSS_START_STOP: Final[str] = make_btn_style(
    color_idle=    "#3D6EDF",
    color_active=  COL_START_ACTIVE,
    color_hover=   COL_START_ACTIVE,
    color_pressed= COL_START_ACTIVE,
)

QSS_RESET: Final[str] = make_btn_style(
    color_idle=    "#78798A",
    color_active=  COL_RESET_ACTIVE,
    color_hover=   COL_RESET_ACTIVE,
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

# btn_dock — assistant anchor toggle
QSS_DOCK: Final[str] = make_btn_style(
    color_idle=    COL_DOCK_IDLE,
    color_active=  COL_DOCK_ACTIVE,
    color_hover=   COL_DOCK_HOVER,
    color_pressed= COL_DOCK_ACTIVE,
)

# Compact two-row header styles. These preserve the legacy styles above while
# giving the approved layout the filled surfaces shown in its mockup.
QSS_COMPACT_POWER: Final[str] = make_btn_style(
    color_idle="#64856E", color_active=COL_POWER_ACTIVE,
    color_hover="#CDD6F4", color_pressed=COL_POWER_ACTIVE,
    bg="#26382D", bg_hover="#45475A",
)
QSS_COMPACT_START: Final[str] = make_btn_style(
    color_idle="#638BD1", color_active=COL_START_ACTIVE,
    color_hover="#CDD6F4", color_pressed=COL_START_ACTIVE,
    bg="#89B4FA", bg_hover="#B4BEFE",
    fg=COL_ON_LIGHT_FILL, fg_hover=COL_ON_LIGHT_FILL,
)
QSS_COMPACT_RESET: Final[str] = make_btn_style(
    color_idle="#98765F", color_active=COL_RESET_ACTIVE,
    color_hover="#CDD6F4", color_pressed=COL_RESET_ACTIVE,
    bg="#29293D", bg_hover="#45475A",
)
QSS_COMPACT_BEANCAVE: Final[str] = make_btn_style(
    color_idle="#5477AD", color_active=COL_BEANCAVE_ACTIVE,
    color_hover="#CDD6F4", color_pressed=COL_BEANCAVE_ACTIVE,
    bg="#29293D", bg_hover="#45475A",
)
# Emergency heat cut. Red on a dark red fill: the only critical-coloured
# control of the header, so it cannot be confused with START or RESET.
# padding:0 — the style's default button padding would push the glyph off centre
# in a button this narrow.
QSS_COMPACT_ESTOP: Final[str] = make_btn_style(
    color_idle="#F38BA8", color_active="#F38BA8",
    color_hover="#FFFFFF", color_pressed="#FFFFFF",
    bg="#3A1E28", bg_hover="#5A2434",
    border_idle="2px", border_active="2px",
) + """
        QPushButton { padding: 0px; }
"""
QSS_COMPACT_SWAP: Final[str] = make_btn_style(
    color_idle="#5F9D93", color_active=COL_SWAP_ACTIVE,
    color_hover="#CDD6F4", color_pressed=COL_SWAP_ACTIVE,
    bg="#29293D", bg_hover="#45475A",
)
