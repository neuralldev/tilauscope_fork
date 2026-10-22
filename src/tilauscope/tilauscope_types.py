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
# TiLau 2025

import re
import uuid
import codecs
import math
import logging
import platform
from dataclasses import dataclass, field
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Final, NamedTuple
from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.mixins.dict import DataClassDictMixin
from PyQt6.QtWidgets import (QApplication, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
                             QFrame, QLabel, QWidget, QPushButton, QSizePolicy, QDoubleSpinBox)
from PyQt6.QtCore import (Qt, QPropertyAnimation, QTimer, QElapsedTimer, QRectF, QSize,
                          QEvent, QObject, pyqtSignal, QLocale, QSettings)
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QIcon

_IS_MACOS   = platform.system() == "Darwin"
_IS_WINDOWS = platform.system() == "Windows"

_log = logging.getLogger(__name__)
_IS_LINUX   = platform.system() == "Linux"

class AUCStartEvent:
    CHARGE = 0
    TP = 1
    DRYEND = 2
    FCSTART = 3

# Roast levels and colour conversion live in the library shared with the tablet.
from tilaucore.roast_colour import (  # noqa: E402  pylint: disable=wrong-import-position
    AGTRON_SCALES, DEFAULT_COLOR_SYSTEM, AgtronRange, AgtronScale, get_agtron_color, resolve_color_system, to_agtron)

# The green coffee records live in the library shared with the tablet; their
# files are read and written with tilaucore.beans.from_json / to_json.
from tilaucore.beans import (  # noqa: E402  pylint: disable=wrong-import-position
    BeanCaveContainer, BrewDialIn, BrewLog, BrewSample, GreenBean, ReferenceProfile, RoastTasting, TastingLog)

# The screen size ranges live in the library shared with the tablet.
from tilaucore.bean_qualifiers import SCREEN_SIZE_RANGES  # noqa: E402,F401  pylint: disable=wrong-import-position

# The currencies offered in Config › BeanCave live in the library shared with the tablet.
from tilaucore.currency import CURRENCIES  # noqa: E402  pylint: disable=wrong-import-position
from tilaucore.bean_edit import NUMBERS as _NUMBERS  # noqa: E402  pylint: disable=wrong-import-position
PRICE_LIMITS = _NUMBERS['price_per_kg']


def currency_code() -> str:
    """The currency set in Config › BeanCave; the system one until the operator picks one."""
    system = QLocale().currencySymbol(QLocale.CurrencySymbolFormat.CurrencyIsoCode) or 'EUR'
    return str(QSettings().value('tilauscope/currency', system, type=str) or system)


def currency_symbol() -> str:
    code = currency_code()
    return CURRENCIES.get(code, code)


def price_per_kg_spin() -> QDoubleSpinBox:
    """The green-coffee price field, in the configured currency per kg."""
    spin = QDoubleSpinBox()
    low, high, decimals = PRICE_LIMITS   # wide enough for JPY and KRW
    spin.setRange(low, high)
    spin.setDecimals(decimals)
    spin.setSuffix(f" {currency_symbol()}/kg")
    spin.setToolTip(QApplication.translate("tilauscope",
        "Purchase price per kg of green beans. Leave 0 if unknown."))
    return spin


def select_listed_or_other(combo, value: object) -> None:
    """Select ``value`` in a closed list; one the list does not carry lands on "Other".

    ``setCurrentText`` silently selects nothing for an unlisted value, and the
    editor then writes the record back blank.
    """
    text = '' if value is None else str(value)
    idx = combo.findText(text)
    if idx < 0 and text:
        idx = combo.findText(QApplication.translate("tilauscope_common", "Other"))
    combo.setCurrentIndex(idx)


def format_money(value: float) -> str:
    """An amount in the configured currency, with the system's own number format."""
    return QLocale().toCurrencyString(float(value), currency_symbol())

GREEN_BEAN_COLUMNS = [
    lambda b: b.name,
    lambda b: b.farm,
    lambda b: b.country,
    lambda b: b.supplier,
    lambda b: b.category,
    lambda b: b.process,
    lambda b: str(b.crop),
    lambda b: f"{b.density:.1f}",
    lambda b: f"{b.last_humidity:.1f}",
    lambda b: f"{b.water_activity:.2f}",
    lambda b: str(b.altitude),
    lambda b: b.species,
    lambda b: b.varieties,
    lambda b: f"{b.weight_left:.1f}",
    lambda b: b.flavour_notes,
    lambda b: f"{b.sca:.1f}",
    lambda b: str(b.count),
    lambda b: f"{b.weight:.1f}",
    lambda b: "Oui" if b.is_blend else "Non",
    lambda b: f"{b.bean1_ratio:.1f}%",
    lambda b: b.bean2_name,
    lambda b: f"{b.bean2_ratio:.1f}%",
    lambda b: b.bean3_name,
    lambda b: f"{b.bean3_ratio:.1f}%",
    lambda b: b.blend_notes,
    lambda b: b.tips,
    lambda b: b.uuid if b.uuid!='' else str(uuid.uuid4()),
]

# The roast-colour ramp of the whole application: roast planning, BeanCave,
# roast viewer and graph annotations all read their colour from here through
# get_agtron_color(), so one Agtron number is always the same colour. The
# tones go light to dark without a step back, and are legible on the dark
# theme background.
# ── .alog text helpers ───────────────────────────────────────────────────────

# Escapes Artisan writes into a profile's text fields: \xNN, \uNNNN and the
# usual whitespace escapes. Several plus signs because repeated Record passes of
# an older build re-escaped what was already escaped.
_ALOG_ESCAPE = re.compile(r'\\+(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|[nrt])')


def decode_alog_text(value: object, default: str = '') -> str:
    """Return a text field of a roast file as the operator typed it.

    Artisan writes every text field of a `.alog` escaped, so an event named
    "Brûleur" is stored as "Br\\xfbleur". Artisan decodes it when it opens the
    profile; anything reading the file directly has to decode it too, or the
    escape reaches the screen.

    Text that is already readable is returned untouched: decoding it a second
    time would turn its accents into mojibake.
    """
    text = str(value) if value is not None else default
    for _ in range(4):   # an over-escaped field needs more than one pass
        if not (text.isascii() and _ALOG_ESCAPE.search(text)):
            break
        try:
            text = codecs.unicode_escape_decode(text)[0]
        except Exception:  # noqa: BLE001 - unreadable escape: keep what we have
            break
    return text


def ensure_color_system(qmc: object, default: str = DEFAULT_COLOR_SYSTEM) -> str:
    """Apply :func:`resolve_color_system` to a live Artisan canvas.

    Called right after a colour reading is written to `qmc`, so the scale
    reaches the saved profile with the value it describes. Returns the
    resolved scale name.
    """
    def _num(name: str) -> float:
        try:
            return float(getattr(qmc, name, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    systems = list(getattr(qmc, "color_systems", None) or [])
    try:
        idx = int(getattr(qmc, "color_system_idx", 0) or 0)
    except (TypeError, ValueError):
        idx = 0
    current = systems[idx] if 0 <= idx < len(systems) else ""

    resolved = resolve_color_system(current, _num("ground_color"), _num("whole_color"), default)
    if resolved and resolved != current and resolved in systems:
        qmc.color_system_idx = systems.index(resolved)  # type: ignore[attr-defined]
    return resolved


def get_roc_color(roc: float) -> str:
    """Return a colour for the Omniflux Rate-of-Color value (Agtron/min).

    The RoC is negative during normal roasting (bean darkens → Agtron drops).
    We work on the magnitude so the palette is direction-independent:

        blue  → slow / stalled   (abs < 1.0)
        green → steady brunissement (1.0 – 3.0)
        gold  → active / fast    (3.0 – 6.0)
        red   → aggressive       (> 6.0)
    """
    abs_roc = abs(roc)
    if abs_roc > 6.0:  return "#FF4500"  # OrangeRed  — aggressive
    if abs_roc > 3.0:  return "#FFD700"  # Gold       — active
    if abs_roc >= 1.0: return "#32CD32"  # LimeGreen  — steady
    return "#00BFFF"                     # DeepSkyBlue — slow / stalled


# Reading a recorded roast lives in the library shared with the tablet.
from tilaucore.roast_analysis import (  # noqa: E402,F401  pylint: disable=wrong-import-position
    DEV_EVENT_PROMINENCE_C, DRY_MATTER_DEV_REF_MIN, DRY_MATTER_LOSS_PCT_BY_CATEGORY, DRY_MATTER_PCT_PER_DEV_MIN,
    GREEN_MOISTURE_NEUTRAL_PCT, UNMARKED, WEIGHT_LOSS_TOLERANCE_PCT, ProbeDeviation, ProbeDeviationInterval,
    RoastingPhase, WeightLossTarget, clean_delta_bt, dominant_dev_ror_event, estimate_ror_dt,
    find_flicks_crashes, find_turning_point_index, get_ror_color_by_phase, get_ror_ideal_band, is_reading,
    marked, normalize_timeindex, weight_loss_target, weight_loss_target_from_plan, which_roast_phase)


# dictionnaire de standardisation pour nettoyer les noms de processus courants
standardization_map = {
    # Cible les termes sans les séparateurs pour les rendre plus flexibles
    "Washed Wet": "Washed",
    "Natural - Dry": "Natural",
    "Natural - Wet": "Natural",
    "Washed Process": "Washed",
    "Natural Process": "Natural",
}

@dataclass
class MQTTSensor(DataClassDictMixin):
    id: str = ""
    topic: str =""
    command: str = ""
    multiplier: float | None = 1.0
    divider: float | None = 1.0
    # unit of the reading once multiplier/divider are applied: "C", "F", "W"
    # for a power reading, or "" otherwise. Read at acquisition to convert into the
    # unit the application is currently working in. Defaults to "" so sensors
    # stored before this field existed keep their raw value.
    unit: str = ""

@dataclass
class MQTTSensorConfig(DataClassJSONMixin):
    sensors: list[MQTTSensor]

MQTT_SENSORS_KEY = "mqtt/sensors"

# The level table and the arrival-pair reading live in the library shared with the tablet.
from tilaucore.roast_levels import (  # noqa: E402,F401  pylint: disable=wrong-import-position
    ARRIVAL_SECONDS_PER_DEGREE, ARRIVAL_UNCERTAINTY_DEFAULT_C, ROASTING_BASIC_BASE, RoasterBasicPlan,
    RoasterBasicPlanPerPhase, arrival_index, roast_level_from_arrival, roast_level_from_arrival_detail)

#
# category = Traditional Wet
# process = Washed / Wet Process
# species = Arabica
# varieties = Bourbon

# Catppuccin Mocha. Single source of colour for every TilauScope
# screen — read a token, never paste a hex literal into a new stylesheet.
# The base stylesheet built on top of these tokens lives in theme_qss.py;
# spec and migration plan in wiki/Theme-QSS-Spec.md.
THEME = {
    # --- surfaces, darkest to lightest ---
    "CRUST": "#11111B",   # deepest inset, behind a surface
    "SURFACE": "#181825", # Mantle — cards, headers, inset panels
    "BG": "#1E1E2E",      # Base — window / dialog background
    "BORDER": "#313244",  # Surface0 — separators, idle borders, button fill
    "SURFACE1": "#45475A",# raised surface, hover fill
    "SURFACE2": "#585B70",# disabled fill, strong border

    # --- text, faintest to brightest ---
    "OVERLAY0": "#6C7086", # disabled text, faint separator
    "OVERLAY1": "#7F849C", # muted glyphs
    "OVERLAY2": "#9399B2", # secondary caption
    "SUBTEXT": "#A6ADC8",  # Subtext0 — captions, units, secondary lines
    "SUBTEXT1": "#BAC2DE", # near-primary text
    "TEXT": "#CDD6F4",     # primary text

    # --- semantic accents ---
    "ACCENT": "#89B4FA",   # Blue — primary action, focus, selection
    "SUCCESS": "#A6E3A1",  # Green — on-target, connected, done
    "WARNING": "#FAB387",  # Peach — drifting, needs attention
    "CRITICAL": "#F38BA8", # Red — out of band, failed, destructive
    "TODAY": "#FAB387",    # Peach — "now" marker on a timeline

    # --- accent variants ---
    "LAVENDER": "#B4BEFE", # selection, focus ring
    "SAPPHIRE": "#74C7EC", # link
    "SKY": "#89DCEB",      # informational
    "TEAL": "#94E2D5",     # measured / sensor values
    "YELLOW": "#F9E2AF",   # attention, pending
    "MAUVE": "#CBA6F7",    # category / accent variant
    "PINK": "#F5C2E7",     # rare accent

    # --- roast-level swatches: the only place these belong ---
    "VERY_LIGHT_ROAST": "#BBE3A1",
    "LIGHT_ROAST": "#A6E3A1",
    "MED_ROAST": "#825E50",
    "DARK_ROAST": "#583121",
    "VERY_DARK_ROAST": "#35190E",
}

# ── the probe hues, one source for every screen that draws a roast ──────────
#
# One hue per PROBE, not per quantity: the bean and its rate are one family,
# the air and its rate another. Within a family the temperature is the full
# hue and the rate wears it a step back, so a rate is never mistaken for the
# line the roast is read from. The roast window, BeanCave's viewer, the roast
# cards and the phone all read these, because a roast reviewed afterwards must
# be the same picture as the roast that was driven.
from tilaucore.display_colours import COLOR_AIR, COLOR_GRAIN  # noqa: E402,F401  pylint: disable=wrong-import-position


def dimmed(colour: str, fallback: str) -> str:
    """The same hue, one step back.

    A rate belongs to the probe it is measured on, so it wears that probe's
    colour rather than one of its own — but it must never be mistaken for the
    temperature itself, which is the line the roast is read from. Darker and a
    little less saturated does both: same family at a glance, clearly the
    quieter member of it.
    """
    c = QColor(colour)
    if not c.isValid():
        c = QColor(fallback)
    h, sat, light, alpha = c.getHsl()
    return QColor.fromHsl(h, int(sat * 0.72), int(light * 0.74), alpha).name()


#: The three roast phases, in the order they happen: drying, Maillard,
#: development. Blue then yellow then red — peach and red sit one step apart on
#: the wheel, and with peach in the middle the Maillard and development
#: stretches read as one block. Every surface that shows a phase reads this
#: triple: the grounds behind the curve, the ribbon of a roast review, the
#: phase bar of a roast card, the chip on the phone. What varies is only the
#: strength each surface needs — faint behind a curve, `dimmed` where the phase
#: must not compete with the roast hues around it, full on a band of its own.
PHASE_COLORS: Final[tuple[str, str, str]] = (THEME['SKY'], THEME['YELLOW'], THEME['CRITICAL'])


# The batch label lives in the library shared with the tablet.
from tilaucore.roast_memory import format_batch_label, roast_batch_tag  # noqa: E402,F401  pylint: disable=wrong-import-position

import unicodedata
def replace_accents(texte):
    if not texte:
        return ""

    # Normalisation NFKD pour séparer les caractères de leurs accents
    charg_normalise = unicodedata.normalize('NFKD', texte)

    # On ne garde que les caractères qui ne sont pas des "combinaisons" (accents)
    # et on réencode en ASCII en ignorant les erreurs pour plus de sécurité
    return "".join([c for c in charg_normalise if not unicodedata.combining(c)])

# Single place where an exported file (label PDF, roast card, plan) is handed
# over to the OS's own viewer, ensuring it comes up in front: a WindowStaysOnTopHint
# window would otherwise keep the viewer underneath, and re-raising ourselves would push it behind again.

class _EnterGuard(QObject):
    """Swallows a Return that reached the dialog because nothing else wanted it.

    A key pressed in a field is delivered to that field. It only travels up to
    the dialog when the field leaves it unhandled — which is exactly the journey
    that ends in the default button being fired. Stopping it here stops that and
    nothing else: a focused button still takes its own Return, and a field that
    handles Return (committing an edit on `returnPressed`) has already done so
    by the time we see it.
    """

    def eventFilter(self, obj: object, event: object) -> bool:  # noqa: N802 (Qt)
        try:
            if (event.type() == QEvent.Type.KeyPress
                    and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
                return True
        except (AttributeError, RuntimeError):
            pass
        return False


def literal_ampersand(text: str) -> str:
    """Keep an ``&`` in a widget label from being eaten as a keyboard shortcut.

    Qt reads a single ampersand in a button, check box or group-box title as a
    mnemonic and takes it out of what is shown, so "detection & marking" was
    drawn as "detection marking". Doubling it after translation leaves the
    source string — and every translation already made from it — untouched.
    """
    return text.replace('&', '&&')


def no_enter_default(dialog) -> None:
    """Stop the Return key from throwing `dialog` away.

    Qt gives each QPushButton in a QDialog `autoDefault`, so a Return nobody
    else claimed activates the first button Qt finds — and in every TilauScope
    dialog that button is the frameless chrome's ✕, wired to reject, close or
    cancel. Typing a name and pressing Return therefore committed the edit AND
    discarded the window in one keystroke, which reads as the edit having failed.

    Two things, because the trap has two halves. The buttons standing right now
    lose `autoDefault` — all of them, not just the destructive one: leave one
    standing and Return simply finds that instead, which is how a Revoke or a
    Delete sitting in a row ends up one keystroke away from an edit. And a guard
    is installed on the dialog for the rest, since a list of rows builds buttons
    long after this call and no sweep can reach forward in time.

    Consequence worth knowing before calling it: Return no longer confirms
    anything in this dialog. That is a gain wherever the key could only close or
    cancel, and a loss in a plain form where Enter is meant to mean OK — those
    should keep their default button and not call this.
    """
    try:
        for button in dialog.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        if getattr(dialog, '_tilau_enter_guard', None) is None:
            guard = _EnterGuard(dialog)      # parented: lives as long as the dialog
            dialog._tilau_enter_guard = guard
            dialog.installEventFilter(guard)
    except Exception as exc:  # noqa: BLE001  a keyboard nicety, never a crash
        _log.warning("no_enter_default failed: %s", exc)


def call_later(owner, ms: int, callback) -> None:
    """Run `callback` after `ms`, unless `owner` has been destroyed by then.

    The plain QTimer.singleShot(ms, lambda: ...) has no Qt receiver, so nothing
    cancels it when the widget the lambda writes into is destroyed — a window
    closed inside the delay leaves the call to land on a deleted object, which
    raises, and an exception from a timer callback reaches the excepthook and
    ends the application. A timer parented to `owner` is destroyed with it and
    simply never fires.

    A destroyed owner is only one of the ways such a call can raise, and the
    others end the application just the same, so the callback runs contained:
    the delayed touch-up this is meant for is never worth a session.

    For anything that has to happen whether the widget survives or not, this is
    the wrong tool: it is meant for the label a widget restores on itself.
    """
    def _run() -> None:
        try:
            callback()
        except Exception as exc:  # noqa: BLE001  a delayed touch-up, never a crash
            _log.warning("call_later callback failed: %s", exc)

    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.timeout.connect(_run)
    timer.timeout.connect(timer.deleteLater)
    timer.start(ms)


def drop_stay_on_top(window) -> None:
    """Let another application come in front of `window`.

    No-op when the window does not float. setWindowFlag() hides a visible
    window, hence the show(). The hint is not restored: once the export is on
    screen the window has no reason to fight it for the front.
    """
    try:
        if window is None or not (window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
            return
        was_visible = window.isVisible()
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        if was_visible:
            window.show()
    except Exception as exc:  # noqa: BLE001
        _log.warning("drop_stay_on_top failed: %s", exc)


def open_in_os_viewer(file_path: str, window=None, helpers=()) -> None:
    """Open `file_path` with the OS viewer, in front of `window`.

    `helpers` are floating companion windows (scale readout, colour card …)
    that would otherwise stay above the viewer on their own.
    """
    import os
    import subprocess
    import sys
    drop_stay_on_top(window)
    for helper in helpers:
        drop_stay_on_top(helper)
    try:
        if sys.platform.startswith("win"):
            os.startfile(file_path)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", file_path])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", file_path])  # noqa: S603,S607
    except Exception as exc:  # noqa: BLE001
        _log.error("Failed to open file %s: %s", file_path, exc)


#: How long a styled dialog takes to fade out after a button is pressed. A
#: caller that puts the focus somewhere on the way out has to outlast it, or
#: Qt hands the focus back to whatever had it before the dialog opened.
STYLED_MESSAGE_FADE_MS: int = 400


def show_styled_message(parent, title, text, icon=QMessageBox.Icon.Information, rich=False, width:int= 0, buttons:list[str]=None):
    m = TilauMessageBox(parent, title, text, icon, rich, width, buttons)
    return m.exec() # call message box

def ask_save_profile(parent, allow_discard: bool = True) -> str:
    """'save', 'discard' or 'cancel': Artisan's "Profile unsaved" question, styled.

    Artisan's native alert crashes AppKit when the monitor redraws the screen while
    it lays itself out; this one is a Qt window. Closing it cancels.
    """
    choices = [('cancel', QApplication.translate('Button', 'Cancel'))]
    if allow_discard:
        choices.append(('discard', QApplication.translate('QPlatformTheme', 'Discard')))  # Qt's own, in every language
    choices.append(('save', QApplication.translate('Button', 'Save')))
    index = show_styled_message(parent, QApplication.translate('Message', 'Profile unsaved'),
                                QApplication.translate('Message', 'Save profile?'), QMessageBox.Icon.Warning,
                                buttons=[label for _, label in choices])
    return choices[index][0] if 0 <= index < len(choices) else 'cancel'


class TilauMessageBox(QMessageBox):
    def __init__(self, parent, title, text, icon, rich, width,buttons:list[str]=None):
        # Parent to the caller's window when it is a real visible window: ties
        # activation/modality to that window so TilauScope._safe_raise recognises it (avoids stealing focus).
        _p = parent if (parent is not None and parent.isVisible()) else None
        super().__init__(parent = _p)
        self.setModal(True)
        # No Qt.Tool flag: a Tool window never becomes key/active on macOS, requiring
        # two clicks. A plain frameless dialog takes activation on the first click.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)

        self.setWindowTitle(title)
        self.setText(text)

        if rich:
            self.setTextFormat(Qt.TextFormat.RichText)

        self.setIcon(QMessageBox.Icon.Information if icon is None else icon)


        if buttons is None:
            btn = self.addButton(QMessageBox.StandardButton.Ok)
            self._tilau_ok_button = btn
            btn.setDefault(True)
            btn.setAutoDefault(True)
        else:
            self._clicked_button_index = -1 # Valeur par défaut si fermé autrement
            for index, btn_text in enumerate(buttons):
                pb = self.addButton(btn_text, QMessageBox.ButtonRole.ActionRole)

                # On passe l'index actuel à la fonction qui gère le clic
                pb.clicked.connect(lambda checked, idx=index: self.on_button_clicked(idx))
        QTimer.singleShot(0, self._tilau_grab_focus)

        # 3. Use the stylesheet to force a solid background on the widget
        # We add a margin so the border-radius has "room" to exist inside the window
        self.setStyleSheet(f"""
            QMessageBox {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};

            }}
            QLabel {{
                color: {THEME['TEXT']};
                font-size: 14px;
                padding: 20px;
                background: transparent;
            }}
            QPushButton {{
                background-color: {THEME['ACCENT']};
                color: {THEME['BG']};
                border-radius: 5px;
                font-weight: bold;
                padding: 8px 20px;
                margin: 10px;
            }}
            QPushButton:hover {{
                background-color: {THEME['LAVENDER']};
            }}
        """)

        # Ensure it has a physical size
        self.setMinimumWidth(800 if width == 0 else width)
        self.setMinimumHeight(400)

    def on_button_clicked(self, index):
        # 1. On mémorise l'index du bouton qui a été cliqué
        self._clicked_button_index = index
        # 2. On lance votre animation de fade out
        self.start_fade_out()

    def _tilau_grab_focus(self):
        # Bring the message box to the front and give it activation +
        # button focus so the very first click on OK registers (see __init__).
        self.raise_()
        self.activateWindow()
        try:
            self._tilau_ok_button.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        except (RuntimeError, AttributeError):
            pass

    def start_fade_out(self):
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(STYLED_MESSAGE_FADE_MS)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self.close)
        self.fade_anim.start()
        self.conclude_dialog()

    def conclude_dialog(self):
        # done() ferme la boîte de dialogue et fait sauter le verrou du exec()
        # en renvoyant la valeur passée en argument.
        if hasattr(self, '_clicked_button_index'):
            self.done(self._clicked_button_index)
        else:
            self.done(0) # Pour le bouton OK standard par exemple

# ══ TilauProgress — the one progress indicator ══════════════════════════════
# ONE component for every long operation, "the app is working" — painted with
# QPainter (not a styled QProgressBar) so it is identical on macOS and Windows.
# Never means "the roast is progressing" — that keeps its own domain widgets.

_reduce_motion_cache: "bool | None" = None


def _probe_reduce_motion() -> bool:
    """Ask the OS whether the operator has asked for less animation."""
    try:
        if _IS_MACOS:
            from AppKit import NSWorkspace  # noqa: PLC0415  # pylint: disable=import-error
            return bool(NSWorkspace.sharedWorkspace()
                        .accessibilityDisplayShouldReduceMotion())
        if _IS_WINDOWS:
            import ctypes  # noqa: PLC0415
            SPI_GETCLIENTAREAANIMATION = 0x1042
            enabled = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
            return not bool(enabled.value)
    except Exception:                                    # noqa: BLE001
        _log.debug("reduce-motion probe unavailable", exc_info=True)
    return False


def reduce_motion() -> bool:
    """True when the OS accessibility settings ask for reduced animation.

    Probed once and cached: it is a preference that needs a logout to change,
    and it must never be read from inside a paint or a sampling tick.
    """
    global _reduce_motion_cache                          # noqa: PLW0603
    if _reduce_motion_cache is None:
        _reduce_motion_cache = _probe_reduce_motion()
    return _reduce_motion_cache


class TilauProgress(QWidget):
    """Ring or bar progress indicator, in one of five states.

    Deliberately mirrors the part of the ``QProgressBar`` API the app already
    uses (``setRange`` / ``setValue`` / ``setMaximum`` / ``value``), so an
    existing bar is replaced by swapping the constructor.  As with
    ``QProgressBar``, ``setRange(0, 0)`` means indeterminate.
    """

    # shapes
    RING = "ring"
    BAR  = "bar"

    # states
    WAITING = "waiting"   # accepted, not started
    WORKING = "working"   # alive, duration unknown
    FILLING = "filling"   # alive, and it will end
    DONE    = "done"      # finished
    FAILED  = "failed"    # stopped — never auto-dismisses

    dismissed = pyqtSignal()   # DONE has been readable long enough to hide

    _TICK_MS    = 33     # 30 fps
    _SWEEP_MS   = 1400   # one ring revolution
    _SHUTTLE_MS = 1100   # one bar sweep
    _EASE_MS    = 180    # value changes never teleport
    _HOLD_MS    = 1200   # how long DONE stays before `dismissed` fires
    _PULSE_MS   = 1600   # reduced-motion breathing
    _ARC_SPAN   = 90.0   # degrees of the indeterminate arc — flat, no tail

    _GLYPH_MIN_PX = 40   # below this a glyph is a smudge: ring alone
    _MARK_MIN_PX  = 20   # below this the check/bang is a smudge: solid ring

    def __init__(self, shape: str = "ring", size: int = 24,
                 glyph: "str | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._shape = shape
        self._size  = int(size)
        self._glyph = glyph
        self._glyph_pm = None
        self._state = self.WORKING

        self._min = 0
        self._max = 0
        self._raw = 0            # last setValue(), for value()

        self._shown = 0.0        # eased 0..1 actually painted
        self._from  = 0.0
        self._to    = 0.0
        self._ease_at = -1       # ms on _clock when the ease started
        self._hold_token = 0

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self.update)

        if shape == self.BAR:
            self.setFixedHeight(6)
            self.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
            self.setMinimumWidth(80)
        else:
            self.setFixedSize(self._size, self._size)

    # ── Qt-compatible surface (drop-in for the bars being replaced) ─────────
    def setRange(self, lo: int, hi: int) -> None:
        self._min, self._max = int(lo), int(hi)
        if self._max <= self._min:
            self.set_state(self.WORKING)          # QProgressBar convention
        elif self._state in (self.WAITING, self.WORKING):
            self.set_state(self.FILLING)

    def setMaximum(self, hi: int) -> None:
        self.setRange(self._min, hi)

    def setMinimum(self, lo: int) -> None:
        self.setRange(lo, self._max)

    def setValue(self, v: int) -> None:
        """QProgressBar-compatible surface — jumps straight to the value, no
        ease.  This is what a blocking scan loop drives through manual
        ``QApplication.processEvents()`` calls: a step can arrive faster than
        the ease's own duration, so easing here only ever restarts the
        animation before it catches up, and the ring visibly stalls a
        quarter of the way round no matter how far the scan has actually
        gone. A caller fed by a real, separately-paced signal (a worker
        thread reporting one printed line at a time) wants the smoothing and
        should call ``set_value`` directly instead."""
        self._raw = int(v)
        span = self._max - self._min
        if span <= 0:
            return                                 # indeterminate: nothing to fill
        if self._state in (self.WAITING, self.WORKING):
            self._state = self.FILLING
        self.set_value((self._raw - self._min) / float(span), animate=False)

    def value(self) -> int:
        return self._raw

    def maximum(self) -> int:
        return self._max

    # ── native surface ──────────────────────────────────────────────────────
    def set_value(self, frac: float, animate: bool = True) -> None:
        """Set the filled fraction 0..1, eased by default so it never
        teleports when fed at a natural real-time pace. ``animate=False``
        jumps straight there — used by ``setValue()`` for blocking loops."""
        frac = max(0.0, min(1.0, float(frac)))
        if not animate:
            self._from = self._to = self._shown = frac
            self._ease_at = -1
            self._sync_timer()
            self.update()
            return
        if abs(frac - self._to) < 1e-4:
            return
        self._from = self._shown
        self._to   = frac
        self._ease_at = self._clock.elapsed()
        self._sync_timer()
        self.update()

    def set_count(self, done: int, total: int) -> None:
        self.setRange(0, int(total))
        self.setValue(int(done))

    def set_indeterminate(self) -> None:
        self.setRange(0, 0)

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self._hold_token += 1
        if state == self.DONE:
            self.set_value(1.0)
            token = self._hold_token
            QTimer.singleShot(
                self._HOLD_MS,
                lambda: self.dismissed.emit() if token == self._hold_token else None)
        elif state == self.WAITING:
            self._from = self._to = self._shown = 0.0
        self._sync_timer()
        self.update()

    def state(self) -> str:
        return self._state

    def succeed(self) -> None:
        self.set_state(self.DONE)

    def fail(self) -> None:
        """Freeze at the last value. Never auto-dismisses — by design."""
        self.set_state(self.FAILED)

    # ── animation bookkeeping ───────────────────────────────────────────────
    def _easing(self) -> bool:
        return (self._ease_at >= 0
                and (self._clock.elapsed() - self._ease_at) < self._EASE_MS)

    def _needs_timer(self) -> bool:
        return self._state == self.WORKING or self._easing()

    def _sync_timer(self) -> None:
        want = self.isVisible() and self._needs_timer()
        if want and not self._timer.isActive():
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event) -> None:                  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:                  # noqa: N802
        # A spinner nobody can see must not repaint at 30 fps.
        self._timer.stop()
        super().hideEvent(event)

    # ── painting ────────────────────────────────────────────────────────────
    def _colour(self) -> QColor:
        if self._state == self.DONE:
            return QColor(THEME['SUCCESS'])
        if self._state == self.FAILED:
            return QColor(THEME['CRITICAL'])
        return QColor(THEME['ACCENT'])

    def _current_fraction(self) -> float:
        if self._ease_at < 0:
            self._shown = self._to
            return self._shown
        t = (self._clock.elapsed() - self._ease_at) / float(self._EASE_MS)
        if t >= 1.0:
            self._ease_at = -1
            self._shown = self._to
        else:
            e = 1.0 - pow(1.0 - t, 3)               # ease-out cubic
            self._shown = self._from + (self._to - self._from) * e
        return self._shown

    def paintEvent(self, event) -> None:                 # noqa: N802
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self._shape == self.BAR:
                self._paint_bar(painter)
            else:
                self._paint_ring(painter)
            painter.end()
        except Exception:                                # noqa: BLE001
            _log.debug("TilauProgress paint failed", exc_info=True)

    def _paint_ring(self, painter: QPainter) -> None:
        side = min(self.width(), self.height())
        pen_w = max(2.0, side / 8.0)
        inset = pen_w / 2.0 + 1.0
        rect = QRectF(inset, inset, side - 2 * inset, side - 2 * inset)
        frac = self._current_fraction()

        # track
        track = QPen(QColor(THEME['BORDER']), pen_w)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        if self._state == self.WAITING:
            track.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)

        if self._state == self.WAITING:
            return

        pen = QPen(self._colour(), pen_w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        if self._state == self.WORKING:
            if reduce_motion():
                # No rotation: the ring breathes instead.
                phase = (self._clock.elapsed() % self._PULSE_MS) / float(self._PULSE_MS)
                wave = 0.28 + 0.72 * (0.5 - 0.5 * math.cos(2.0 * math.pi * phase))
                col = self._colour()
                col.setAlphaF(wave)
                pen.setColor(col)
                painter.setPen(pen)
                painter.drawArc(rect, 0, 360 * 16)
            else:
                phase = (self._clock.elapsed() % self._SWEEP_MS) / float(self._SWEEP_MS)
                start = 90.0 - 360.0 * phase
                painter.setPen(pen)
                painter.drawArc(rect, int(start * 16), int(-self._ARC_SPAN * 16))
        else:
            painter.setPen(pen)
            span = 360.0 if self._state == self.DONE else 360.0 * frac
            if span > 0.0:
                painter.drawArc(rect, int(90 * 16), int(-span * 16))

        if self._state == self.DONE and side >= self._MARK_MIN_PX:
            self._paint_mark(painter, side, check=True)
        elif self._state == self.FAILED and side >= self._MARK_MIN_PX:
            self._paint_mark(painter, side, check=False)
        elif self._glyph and side >= self._GLYPH_MIN_PX:
            self._paint_glyph(painter, side)

    def _paint_mark(self, painter: QPainter, side: float, check: bool) -> None:
        pen = QPen(self._colour(), max(2.0, side / 9.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        if check:
            path.moveTo(side * 0.30, side * 0.51)
            path.lineTo(side * 0.44, side * 0.65)
            path.lineTo(side * 0.71, side * 0.36)
            painter.drawPath(path)
        else:
            path.moveTo(side * 0.50, side * 0.30)
            path.lineTo(side * 0.50, side * 0.56)
            painter.drawPath(path)
            painter.drawPoint(int(side * 0.50), int(side * 0.69))

    def _paint_glyph(self, painter: QPainter, side: float) -> None:
        px = int(side * 0.42)
        if px < 8:
            return
        if self._glyph_pm is None or self._glyph_pm.width() != px * self._dpr():
            self._glyph_pm = self._render_glyph(px)
        if self._glyph_pm is None:
            return
        x = (side - px) / 2.0
        painter.drawPixmap(QRectF(x, x, px, px), self._glyph_pm,
                           QRectF(self._glyph_pm.rect()))

    def _dpr(self) -> int:
        return max(1, int(round(self.devicePixelRatioF())))

    def _render_glyph(self, px: int):
        try:
            from tilauscope.header_icons import make_icon  # noqa: PLC0415
            hi = px * self._dpr()
            icon = make_icon(self._glyph, THEME['SUBTEXT'], QSize(hi, hi))
            return icon.pixmap(QSize(hi, hi))
        except Exception:                                # noqa: BLE001
            _log.debug("progress glyph unavailable", exc_info=True)
            return None

    def _paint_bar(self, painter: QPainter) -> None:
        w, h = float(self.width()), float(self.height())
        r = h / 2.0
        frac = self._current_fraction()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME['BORDER']))
        painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        if self._state == self.WAITING:
            return

        painter.setBrush(self._colour())
        if self._state == self.WORKING and not reduce_motion():
            shuttle = w * 0.30
            phase = (self._clock.elapsed() % self._SHUTTLE_MS) / float(self._SHUTTLE_MS)
            x = -shuttle + (w + shuttle) * phase
            painter.setClipPath(self._rounded(w, h, r))
            painter.drawRoundedRect(QRectF(x, 0, shuttle, h), r, r)
        elif self._state == self.WORKING:
            col = self._colour()
            pulse_phase = (self._clock.elapsed() % self._PULSE_MS) / float(self._PULSE_MS)
            col.setAlphaF(0.28 + 0.72 * (0.5 - 0.5 * math.cos(2.0 * math.pi * pulse_phase)))
            painter.setBrush(col)
            painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        else:
            fill = w if self._state == self.DONE else w * frac
            if fill > 0.0:
                painter.drawRoundedRect(QRectF(0, 0, max(fill, h), h), r, r)

    @staticmethod
    def _rounded(w: float, h: float, r: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        return path


class TilauProgressRow(QWidget):
    """Host C — a bar with its count, for a queue the operator can watch.

    Exposes the same ``setRange`` / ``setMaximum`` / ``setValue`` / ``hide`` /
    ``show`` surface as the QProgressBar it replaces, so existing call sites
    keep working, and writes the count as '3 of 5' rather than a bare
    percentage.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)

        self.progress = TilauProgress(TilauProgress.BAR, parent=self)
        lay.addWidget(self.progress, 1)

        self.count = QLabel("", self)
        self.count.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:10px; font-family:'JetBrains Mono';"
            f" background:transparent; border:none;")
        lay.addWidget(self.count)

    def _refresh(self) -> None:
        total = self.progress.maximum()
        if total > 0:
            self.count.setText(
                QApplication.translate("tilauscope", "{0} of {1}").format(
                    self.progress.value(), total))
        else:
            self.count.setText("")

    def setRange(self, lo: int, hi: int) -> None:         # noqa: N802
        self.progress.setRange(lo, hi)
        self._refresh()

    def setMaximum(self, hi: int) -> None:                # noqa: N802
        self.progress.setMaximum(hi)
        self._refresh()

    def setValue(self, v: int) -> None:                   # noqa: N802
        self.progress.setValue(v)
        self._refresh()

    def value(self) -> int:
        return self.progress.value()

    def maximum(self) -> int:
        return self.progress.maximum()

    def set_state(self, state: str) -> None:
        self.progress.set_state(state)


class TilauProgressPill(QWidget):
    """Host A — non-modal status pill, anchored bottom-right of its parent.

    For work the operator starts and then ignores.  The window stays usable,
    which makes this the ONLY progress form allowed while a roast is running:
    nothing may steal focus with 250 g and ten minutes on the line.
    """

    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget, text: str = "",
                 glyph: "str | None" = None, cancellable: bool = True) -> None:
        super().__init__(parent)
        self._margin_r = 16
        self._margin_b = 16
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};"
            f" border-radius:14px;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(8)

        # 20 px, not 16: below _MARK_MIN_PX the ✓ and ✕ are not painted. `glyph` is under
        # TilauProgress._GLYPH_MIN_PX (40) here, so it is never painted — only TilauProgressDialog (ring 64) is above threshold.
        self.progress = TilauProgress(TilauProgress.RING, 20, glyph, self)
        self.progress.dismissed.connect(self._fade_out)
        lay.addWidget(self.progress)

        self.label = QLabel(text, self)
        self.label.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:11px; "
            f" background:transparent; border:none;")
        lay.addWidget(self.label)

        self.count = QLabel("", self)
        self.count.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px; font-family:'JetBrains Mono';"
            f" background:transparent; border:none;")
        lay.addWidget(self.count)

        self.btn_cancel = QPushButton("✕", self)
        self.btn_cancel.setFixedSize(18, 18)
        self.btn_cancel.setProperty('variant', 'icon')   # fixed size: no base padding
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setToolTip(QApplication.translate("Button", "Cancel"))
        self.btn_cancel.setStyleSheet(
            f"QPushButton {{ color:{THEME['SUBTEXT']}; background:transparent;"
            f" border:none; font-size:11px; }}"
            f"QPushButton:hover {{ color:{THEME['CRITICAL']}; }}")
        self.btn_cancel.clicked.connect(self.cancelled.emit)
        self.btn_cancel.setVisible(cancellable)
        lay.addWidget(self.btn_cancel)

        parent.installEventFilter(self)
        self.place()

    # ── placement ───────────────────────────────────────────────────────────
    def set_margin(self, right: int, bottom: int) -> None:
        """Lift the pill clear of the local furniture (a size grip, a button row)."""
        self._margin_r, self._margin_b = int(right), int(bottom)
        self.place()

    def place(self) -> None:
        self.adjustSize()
        p = self.parentWidget()
        if p is None:
            return
        self.move(max(0, p.width() - self.width() - self._margin_r),
                  max(0, p.height() - self.height() - self._margin_b))
        self.raise_()

    def eventFilter(self, obj, event) -> bool:           # noqa: N802
        if obj is self.parentWidget() and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show):
            self.place()
        return super().eventFilter(obj, event)

    # ── state, forwarded to the shared painter ──────────────────────────────
    def set_text(self, text: str) -> None:
        self.label.setText(text)
        self.place()

    def set_step(self, done: int, total: int) -> None:
        """Update the counter text only — for runs whose ring is driven finer
        than one step at a time (a printer reports line by line)."""
        self.count.setText(
            QApplication.translate("tilauscope", "{0} of {1}").format(done, total))
        self.place()

    def set_count(self, done: int, total: int) -> None:
        self.set_step(done, total)
        self.progress.set_count(done, total)

    def succeed(self, text: "str | None" = None) -> None:
        if text:
            self.label.setText(text)
        self.count.setText("")
        self.btn_cancel.setVisible(False)
        self.progress.succeed()
        self.place()

    def fail(self, text: str) -> None:
        """Never auto-dismisses: the operator has to read the gesture."""
        self.label.setText(text)
        self.label.setStyleSheet(
            f"color:{THEME['CRITICAL']}; font-size:11px; "
            f" background:transparent; border:none;")
        self.count.setText("")
        # The work is over: ✕ now means "I have read this", never "cancel".
        # Leaving it wired to `cancelled` would call back into a dead worker.
        try:
            self.btn_cancel.clicked.disconnect()
        except TypeError:
            pass
        self.btn_cancel.clicked.connect(self._fade_out)
        self.btn_cancel.setToolTip(QApplication.translate("tilauscope", "Dismiss"))
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setText("✕")
        self.progress.fail()
        self.place()

    def _fade_out(self) -> None:
        self.hide()
        self.deleteLater()


def print_progress_pill(parent: QWidget, total: int,
                        on_cancel=None) -> TilauProgressPill:
    """Host A wired for one Niimbot run — the single entry point for printing.

    ``total`` is the number of labels the run will put out.  A single label has
    nothing to count and nothing to interrupt: the ring just sweeps.  A batch
    counts, and offers ✕ when the caller can honour it — which on a printer
    means "stop after the label currently coming out", never "undo".
    """
    pill = TilauProgressPill(
        parent,
        "🖨  " + QApplication.translate("tilauscope_common", "Printing…"),
        cancellable=(total > 1 and on_cancel is not None))
    if total > 1:
        pill.progress.set_count(0, total)
        pill.set_step(0, total)
        if on_cancel is not None:
            pill.cancelled.connect(on_cancel)
            pill.btn_cancel.setToolTip(QApplication.translate(
                "tilauscope", "Stop after the label being printed"))
    else:
        # Nothing to count: sweep rather than show a ring frozen at zero.
        # A caller that does have finer progress may switch it to determinate.
        pill.progress.set_indeterminate()
    pill.show()
    return pill


def set_button_busy(button: QPushButton, busy: bool,
                    text: "str | None" = None,
                    glyph: "str | None" = None) -> None:
    """Host D — turn a button's own icon slot into a ring while it works.

    For actions between roughly 0.4 s and 2 s: Generate, Print, Connect.
    The button keeps its exact width, so nothing on the screen moves.

    `glyph` is accepted for signature symmetry with the other hosts and is
    never painted: the ring is 16 px, well under
    TilauProgress._GLYPH_MIN_PX (40). Do not pass one expecting it to show.
    """
    spinner = getattr(button, "_tilau_busy", None)
    if busy:
        if spinner is None:
            spinner = TilauProgress(TilauProgress.RING, 16, glyph, button)
            button._tilau_busy = spinner                 # noqa: SLF001
            button._tilau_text = button.text()           # noqa: SLF001
            button._tilau_icon = button.icon()           # noqa: SLF001
        button.setIcon(QIcon())
        if text:
            button.setText(text)
        spinner.set_indeterminate()
        spinner.move(max(6, (button.height() - 16) // 2),
                     max(0, (button.height() - 16) // 2))
        spinner.show()
        button.setEnabled(False)
    elif spinner is not None:
        spinner.hide()
        spinner.deleteLater()
        button._tilau_busy = None                        # noqa: SLF001
        button.setText(getattr(button, "_tilau_text", button.text()))
        button.setIcon(getattr(button, "_tilau_icon", QIcon()))
        button.setEnabled(True)


class TilauProgressDialog(QDialog):
    """Host B — modal progress, for work that must not be interrupted.

    ApplicationModal on purpose, NOT WindowModal: on macOS a WindowModal
    QDialog is rendered as a sheet, and closing one programmatically just
    before opening another dialog can leave the parent window unclickable —
    the failure already seen after Niimbot printing.
    """

    def __init__(self, message: str, parent=None, maxvalue: "int | None" = None,
                 glyph: "str | None" = None, hint: str = "") -> None:
        super().__init__(parent)
        # imported here, not at module level: theme_qss reads THEME
        # from this module, so a top-level import is a cycle that only happens
        # to work when tilauscope_types is imported first.
        from tilauscope.theme_qss import apply_tilau_theme  # noqa: PLC0415
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setup_ui(message, maxvalue, glyph, hint)
        self.resize(400, 210)

    def setup_ui(self, message, maxvalue, glyph=None, hint="") -> None:
        self.main_layout = QVBoxLayout(self)
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 20px;
            }}
        """)
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(30, 26, 30, 26)
        self.content_layout.setSpacing(14)
        self.main_layout.addWidget(self.container)

        # the ring carries the motion, so the message doesn't have to shout
        self.pbar = TilauProgress(TilauProgress.RING, 64, glyph, self)
        # maxvalue None -> indeterminate.
        self.pbar.setRange(0, 0 if maxvalue is None else int(maxvalue))

        self.msg_label = QLabel(message.upper())
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setStyleSheet(
            f"color:{THEME['TEXT']}; font-weight:bold; font-size:12px;"
            f" border:none; background:transparent;")

        self.hint_label = QLabel(hint)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setVisible(bool(hint))
        self.hint_label.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px;"
            f" border:none; background:transparent;")

        ring_row = QHBoxLayout()
        ring_row.addStretch(1)
        ring_row.addWidget(self.pbar)
        ring_row.addStretch(1)

        self.content_layout.addLayout(ring_row)
        self.content_layout.addWidget(self.msg_label)
        self.content_layout.addWidget(self.hint_label)

    def set_count(self, done: int, total: int) -> None:
        """Show '47 of 312' under the message — never a bare percentage."""
        self.hint_label.setText(
            QApplication.translate("tilauscope", "{0} of {1}").format(done, total))
        self.hint_label.setVisible(True)
        self.pbar.set_count(done, total)

    # ── QProgressDialog-compatible surface ──────────────────────────────────
    # Lets the raw QProgressDialog call sites migrate by swapping the
    # constructor alone, without rewriting the loops around them.
    def setValue(self, v: int) -> None:                  # noqa: N802
        self.pbar.setValue(v)
        total = self.pbar.maximum()
        if total > 0:
            self.hint_label.setText(
                QApplication.translate("tilauscope", "{0} of {1}").format(v, total))
            self.hint_label.setVisible(True)

    def wasCanceled(self) -> bool:                       # noqa: N802
        """Always False — as with the dialogs this replaces, which were built
        with no cancel button. Work that must not be interrupted has no
        cancel affordance; cancellable work belongs in a pill instead."""
        return False

# ── Milestone temperature windows (DE / FC) ─────────────────────────────────
# Profession-standard bands in the *true* bean frame, resolved to the displayed
# frame (plan target, else band + roaster offset): shared with the Android prototype.
from tilaucore.milestones import (  # noqa: E402,F401  pylint: disable=wrong-import-position
    MILESTONE_HALF_C, PROFESSION_DE_TRUE_C, PROFESSION_FC_TRUE_C, resolve_de_window, resolve_fc_window,
    resolve_milestone_window)


# --- Extra-device channel classification --------------------------------------
# Shared by FirstCrackDetector and DryEndDetector. Substring phrases match
# explicit multi-word names; exact tokens match short codes WITHOUT the
# substring footgun ("roc" in "process", "fc" in "fcs target").
# Priority resolves overlaps: RoC before Color ("rate of color" contains
# "color"); SC before FC ("second crack" contains "crack").
_EXTRA_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")

_EXTRA_MATCH: Final[dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    #  category : (substring phrases,                              exact tokens)
    "roc":   (("rate of color", "rate of colour", "rateofcolor"), ("roc",)),
    "color": (("agtron", "ground color", "ground colour",
               "whole color", "whole colour"),                    ("color", "colour")),
    "sc":    (("second crack", "sc counter", "sccounter"),        ("sc", "tlsc")),
    "fc":    (("first crack", "fc counter", "fccounter",
               "crack counter"),                                  ("fc", "tlfc",
                                                                   "crack", "cracks")),
}
#: Names the ACOUSTIC probe gives its counter. Several channels can classify as
#: "fc" on the same machine — the Omniflux pair (FCcounter/SCCounter) is declared
#: whether or not anything ever writes to it, and on this hardware it never does:
#: it has no Bluetooth acquisition at all. The acoustic channel is the one that
#: counts, so it wins the binding whatever order the devices are declared in.
_ACOUSTIC_TOKENS: Final[frozenset[str]] = frozenset(("crack", "cracks"))
_EXTRA_PRIORITY: Final[tuple[str, ...]] = ("roc", "color", "sc", "fc")


def name_key(name: str) -> str:
    """A sensor or channel name as compared for uniqueness: case and surrounding spaces ignored."""
    return name.strip().casefold()


def duplicate_names(names: Iterable[str]) -> set[str]:
    """The name keys (see name_key) more than one non-empty name carries."""
    counts = Counter(name_key(name) for name in names)
    return {key for key, count in counts.items() if key and count > 1}


def classify_extra_channel(name: str) -> str | None:
    """Map an extra-device channel name to 'roc'|'color'|'sc'|'fc' or None.
    Deterministic and collision-safe: at most one category per channel."""
    if not name:
        return None
    low = name.lower()
    tokens = set(_EXTRA_TOKEN_RE.findall(low))
    for cat in _EXTRA_PRIORITY:
        subs, exact = _EXTRA_MATCH[cat]
        if any(s in low for s in subs) or (tokens & set(exact)):
            return cat
    return None

#: Where the operator level is persisted between sessions.
OPERATOR_LEVEL_KEY: Final = "tilauscope/operator_level"


def operator_level(aw: object) -> str:
    """The operator level in force right now — "guided" or "expert".

    The window holds it; the setting only persists it. Roast Replay borrows
    Expert for the length of one replay and deliberately never writes that
    down, so whoever reads the setting alone sees Guided while the window is
    running Expert. Ask here instead, and the answer follows the screen.

    Falls back to the stored value while no window is open, and to Guided
    when nothing is stored.
    """
    try:
        tilauscope = aw.tilauscope_main  # type: ignore[attr-defined]
        if tilauscope is not None:
            level = getattr(tilauscope, "_operator_level", None)
            if level in ("guided", "expert"):
                return level
    except AttributeError:
        pass
    from PyQt6.QtCore import QSettings
    stored = QSettings().value(OPERATOR_LEVEL_KEY, "guided", type=str)
    return stored if stored in ("guided", "expert") else "guided"


def resolve_crack_channel(extraname1: "list[str]",
                          extraname2: "list[str]",
                          extratemp1: "list | None" = None,
                          extratemp2: "list | None" = None) -> "tuple[int, int] | None":
    """Which extra-device channel carries the crack counter: (index, channel).

    A machine can declare several. The acoustic probe writes to a channel named
    for the crack; the Omniflux pair (FCcounter/SCCounter) is declared whether or
    not anything ever writes to it. Either can be the dead one on any given
    roast, so the name alone cannot decide — what COUNTED does.

    Liveness is judged per DEVICE, not per channel: attribution inverts between
    firmware builds, so a device can route every pop to its SC channel and leave
    its FC channel flat. Reading only the FC channel would call that device dead
    while it was the one doing the counting.

    Preference: a device that counted something, then the acoustic one among
    them. With no readings to go on — discovery runs before the first sample —
    an unread device outranks one seen to be flat and yields to one seen to
    count. Callers pair the result with the SC channel of the SAME device.

    Shared by the detector's own discovery and by the drawing pass, which has to
    resolve the channel on a roast merely opened from a file: discovery runs on
    monitor-on and at CHARGE, neither of which a reopened profile goes through.
    """
    def series_of(idx: int, ch: int):
        try:
            if ch == 1 and extratemp1 is not None:
                return extratemp1[idx]
            if ch == 2 and extratemp2 is not None:
                return extratemp2[idx]
        except (IndexError, TypeError):
            return None
        return None

    def counted(idx: int) -> "bool | None":
        """Whether either crack channel of this device ever rose above zero."""
        seen = False
        for ch, names in ((1, extraname1), (2, extraname2)):
            name = names[idx].lower() if idx < len(names) else ""
            if classify_extra_channel(name) not in ("fc", "sc"):
                continue
            series = series_of(idx, ch)
            if series is None or len(series) == 0:
                continue
            seen = True
            if any(v is not None and v > 0 for v in series):
                return True
        return False if seen else None

    best: "tuple[int, int, int, int] | None" = None
    liveness: "dict[int, bool | None]" = {}
    for i in range(max(len(extraname1), len(extraname2))):
        for ch, names in ((1, extraname1), (2, extraname2)):
            name = names[i].lower() if i < len(names) else ""
            if classify_extra_channel(name) != "fc":
                continue
            if i not in liveness:
                liveness[i] = counted(i)
            live = liveness[i]
            rank = 2 if live else (0 if live is False else 1)
            acoustic = bool(set(_EXTRA_TOKEN_RE.findall(name)) & _ACOUSTIC_TOKENS)
            candidate = (rank, int(acoustic), i, ch)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    return None if best is None else (best[2], best[3])


#: How dark one pop of the crack band is drawn — light enough that overlapping
#: ticks build the density on their own. Every drawing of the band shares it.
CRACK_TICK_ALPHA: Final[int] = 90
#: A counter that overflows (65535 is on record) must not flood the band.
_CRACK_POPS_PER_SAMPLE: Final[int] = 16


def crack_pop_times(series: list | None, timex: list) -> list[float]:
    """When each pop was heard: one `timex` value per unit the counter rose.

    Read off the recorded counter rather than accumulated live, so a roast
    reopened from a file draws exactly what the roast that ran drew. The probe
    writes -1 on any tick it does not answer — most of them — and a saved
    profile carries the series interpolated to floats, so only the integer
    part is the count: 0.0, 0.33, 0.67, 1.0 is one pop, not three.
    """
    times: list[float] = []
    previous: int | None = None
    for i, value in enumerate(series or ()):
        if (i >= len(timex) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            continue
        count = int(value)
        if previous is not None and count > previous:
            times.extend([float(timex[i])] * min(count - previous, _CRACK_POPS_PER_SAMPLE))
        previous = count
    return times


def profile_crack_times(profile: Mapping[str, Any]) -> list[float]:
    """Pop times of a saved roast, on its own `timex` — for the drawings that
    read a profile rather than the live canvas (BeanCave viewer, roast card)."""
    extratemp1 = profile.get("extratemp1")
    extratemp2 = profile.get("extratemp2")
    try:
        channel = resolve_crack_channel(profile.get("extraname1") or [],
                                        profile.get("extraname2") or [],
                                        extratemp1, extratemp2)
        if channel is None:
            return []
        idx, ch = channel
        series = (extratemp1 if ch == 1 else extratemp2)[idx]
    except (AttributeError, IndexError, TypeError):
        return []   # a malformed profile has no band, but keeps its curve
    return crack_pop_times(series, profile.get("timex") or [])


# Threads that outlived their owner's wait, held until they finish on their own:
# a QThread destroyed while running aborts the application.
_PARKED: set = set()


def park_until_finished(thread, worker=None) -> None:
    """Keep `thread` (and its worker) alive until it has finished.

    Detached from its parent first: a dying parent deletes its children on the
    C++ side, whatever Python still holds.
    """
    try:
        if thread.parent() is not None:
            thread.setParent(None)
    except (RuntimeError, AttributeError):
        return   # already gone
    entry = (thread, worker)
    _PARKED.add(entry)

    def _release() -> None:
        thread.wait(1000)   # finished fires just before the thread really exits
        _PARKED.discard(entry)

    thread.finished.connect(_release)
