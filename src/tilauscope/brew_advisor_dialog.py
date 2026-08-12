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

from __future__ import annotations

from tilauscope.theme_qss import apply_tilau_theme

import copy
import json
import re as _re
import logging
from typing import Final, Optional, Callable

from PyQt6.QtCore import (Qt, QObject, QPoint, QPointF, QRectF, QTimer, QElapsedTimer,
                          pyqtSignal, pyqtSlot, QLocale, QT_TRANSLATE_NOOP)
from PyQt6.QtGui import QPalette, QColor, QMouseEvent, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QPushButton, QWidget, QFrame, QApplication, QMessageBox, QScrollArea,
    QStyle, QStyleOptionSpinBox, QDoubleSpinBox,
)

from artisanlib.util import fromCtoFstrict
from tilauscope.tilauscope_types import THEME, show_styled_message, print_progress_pill
from tilauscope.ai_support import normalize_engine, get_suppress_thinking_params, provider_base_url
from tilauscope.brew_advisor import (
    BrewAdvisor, BrewInput, BrewRecipe, BrewFamily, WaterProfile, Severity,
    EspressoMachine, AgitationCode, GrindCat, NoteCode, PIType,
    ESPRESSO_MACHINE_ORDER, ESPRESSO_STYLE_ORDER, EspressoStyle, METHOD_ORDER, METHOD_ANCHORS, grind_cat,
    BrewCorrection, TasteCode, DiagnosisCode, diagnose, rest_window, RestStatus,
    learn_setup_offset, ratio_floor, planned_pour_rate,
)

_log: Final = logging.getLogger(__name__)

# AITask.BREW_ADVICE if present (add to the enum), else literal string.
try:
    from tilauscope.ai_service import AITask
    _BREW_TASK = getattr(AITask, "BREW_ADVICE", "BREW_ADVICE")
except Exception:  # noqa: BLE001
    _BREW_TASK = "BREW_ADVICE"

# ── Code → translated label maps (resolved at render time) ────────────────
def _method_label(mid: str) -> str:
    return {
        "ESPRESSO": QApplication.translate("tilauscope_brew", "Espresso"), "V60": QApplication.translate("tilauscope_brew", "V60 / Pour-over"),
        "FRENCH_PRESS": QApplication.translate("tilauscope_brew", "French Press"), "AEROPRESS": QApplication.translate("tilauscope_brew", "AeroPress"),
        "PULSAR": QApplication.translate("tilauscope_brew", "Pulsar (no-bypass)"), "WEBER_BIRD": QApplication.translate("tilauscope_brew", "Weber Bird (no-bypass)"),
        "MOKA": QApplication.translate("tilauscope_brew", "Moka pot"),
    }.get(mid, mid)


def _machine_label(mc: EspressoMachine) -> str:
    return {
        EspressoMachine.E61: QApplication.translate("tilauscope_brew", "E61 group (SB/DB)"),
        EspressoMachine.HX: QApplication.translate("tilauscope_brew", "HX (E61)"),
        EspressoMachine.DUAL_BOILER: QApplication.translate("tilauscope_brew", "Dual boiler (programmable PI)"),
        EspressoMachine.LA_MARZOCCO: QApplication.translate("tilauscope_brew", "La Marzocco (paddle / line PI)"),
        EspressoMachine.SLAYER: QApplication.translate("tilauscope_brew", "Slayer (needle-valve pre-brew)"),
        EspressoMachine.LEVER_MANUAL: QApplication.translate("tilauscope_brew", "Manual lever (Flair / Cafelat Robot)"),
        EspressoMachine.FLOW_PROFILER: QApplication.translate("tilauscope_brew", "Flow / pressure profiler"),
        EspressoMachine.BASIC: QApplication.translate("tilauscope_brew", "Basic single boiler (no PI)"),
        EspressoMachine.OTHER: QApplication.translate("tilauscope_brew", "Other / unknown"),
    }[mc]


class _StepSpinBox(QSpinBox):
    """A spin box whose arrows step exactly once per click.

    On macOS this frameless/translucent/Tool dialog can lose the mouse release that
    stops QAbstractSpinBox's auto-repeat, so the arrows are handled directly instead.
    """

    def mousePressEvent(self, e: QMouseEvent) -> None:
        opt = QStyleOptionSpinBox()
        opt.initFrom(self)
        opt.subControls = QStyle.SubControl.SC_All
        sc = self.style().hitTestComplexControl(
            QStyle.ComplexControl.CC_SpinBox, opt, e.position().toPoint(), self)
        if e.button() == Qt.MouseButton.LeftButton and sc in (
                QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown):
            self.stepBy(1 if sc == QStyle.SubControl.SC_SpinBoxUp else -1)
            e.accept()
            return
        super().mousePressEvent(e)


def _style_label(st: EspressoStyle) -> str:
    return {
        EspressoStyle.CLASSIC: QApplication.translate("tilauscope_brew", "Classic long"),
        EspressoStyle.TURBO: QApplication.translate("tilauscope_brew", "Turbo (short, coarse)"),
    }[st]


def _roast_label(key: str) -> str:
    return {
        "EXTREMELY_LIGHT": QApplication.translate("tilauscope_brew", "Extremely Light (Nordic)"), "VERY_LIGHT": QApplication.translate("tilauscope_brew", "Very Light"),
        "LIGHT": QApplication.translate("tilauscope_brew", "Light"), "MEDIUM_LIGHT": QApplication.translate("tilauscope_brew", "Medium Light"), "MEDIUM": QApplication.translate("tilauscope_brew", "Medium"),
        "MEDIUM_DARK": QApplication.translate("tilauscope_brew", "Medium Dark"), "DARK": QApplication.translate("tilauscope_brew", "Dark / Very Dark"),
    }.get(key, key)


def _grind_label(cat: GrindCat) -> str:
    return {
        GrindCat.ULTRA_FINE: QApplication.translate("tilauscope_brew", "Ultra-fine (Turkish)"), GrindCat.FINE: QApplication.translate("tilauscope_brew", "Fine (espresso)"),
        GrindCat.MEDIUM_FINE: QApplication.translate("tilauscope_brew", "Medium-fine (AeroPress / Moka)"), GrindCat.MEDIUM: QApplication.translate("tilauscope_brew", "Medium (pour-over)"),
        GrindCat.MEDIUM_COARSE: QApplication.translate("tilauscope_brew", "Medium-coarse (no-bypass)"), GrindCat.COARSE: QApplication.translate("tilauscope_brew", "Coarse (French Press)"),
        GrindCat.EXTRA_COARSE: QApplication.translate("tilauscope_brew", "Extra-coarse (cold brew)"),
    }[cat]


def _agitation_label(a: AgitationCode) -> str:
    return {
        AgitationCode.NONE_PUCK: QApplication.translate("tilauscope_brew", "None (puck prep / WDT)"),
        AgitationCode.PULSE: QApplication.translate("tilauscope_brew", "Medium (pulse + light swirl)"),
        AgitationCode.CRUST: QApplication.translate("tilauscope_brew", "Low (break crust at 4:00)"),
        AgitationCode.STIR: QApplication.translate("tilauscope_brew", "Medium (stir 10 s)"),
        AgitationCode.SPIN: QApplication.translate("tilauscope_brew", "Spin / WWDT during bloom"),
        AgitationCode.VORTEX: QApplication.translate("tilauscope_brew", "Vortex stir, then pull pod"),
        AgitationCode.NONE_PREHEAT: QApplication.translate("tilauscope_brew", "None (pre-heated water)"),
        AgitationCode.HIGH_DENSE: QApplication.translate("tilauscope_brew", "High (dense high-altitude)"),
        AgitationCode.REDUCED_UNEVEN: QApplication.translate("tilauscope_brew", "Reduced (uneven roast)"),
    }[a]


def _tds_label(key: str) -> str:
    return {"tds_espresso": QApplication.translate("tilauscope_brew", "TDS 8-11%"), "tds_moka": QApplication.translate("tilauscope_brew", "Remove at first gurgle")}.get(key, "")


def _note_text(code: NoteCode, params: dict) -> str:
    tpl = {
        NoteCode.DENSITY_VERY_HIGH: QApplication.translate("tilauscope_brew", "Very high density: coarsen slightly and add agitation to keep flow."),
        NoteCode.DENSITY_HIGH: QApplication.translate("tilauscope_brew", "High density: slightly coarser grind to maintain flow."),
        NoteCode.DENSITY_LOW: QApplication.translate("tilauscope_brew", "Low density: finer grind; watch for fast/thin flow."),
        NoteCode.WL_HIGH: QApplication.translate("tilauscope_brew", "High weight-loss: well-developed/porous bean, extracts easily — watch for over-extraction."),
        NoteCode.WL_LOW: QApplication.translate("tilauscope_brew", "Low weight-loss: under-developed, harder to extract — add agitation."),
        NoteCode.DEV_SHORT: QApplication.translate("tilauscope_brew", "Short development: expect bright acidity, wider ratio to balance."),
        NoteCode.DEV_LONG: QApplication.translate("tilauscope_brew", "Long development: tighter ratio keeps body, lower risk of flatness."),
        NoteCode.ORIGIN_HIGH: QApplication.translate("tilauscope_brew", "Dense high-altitude structure: tolerates high-yield, wider ratio."),
        NoteCode.ORIGIN_LOW: QApplication.translate("tilauscope_brew", "Lower-grown / less dense: tighter ratio to keep body."),
        NoteCode.TURBO: QApplication.translate("tilauscope_brew", "Turbo shot: coarse grind and a short pull. It needs a machine that holds its pressure — if yours dips, the shot will read sour and under-extracted rather than fast."),
        NoteCode.RATIO_OFFSET: QApplication.translate("tilauscope_brew", "Those two ratio signals pull opposite ways and cancel — the ratio above is the balance of both, not a compromise you need to resolve."),
        NoteCode.CAPACITY: QApplication.translate("tilauscope_brew", "This recipe needs {w} g of water — more than a typical brewer of this kind holds (~{cap} g). Brew a smaller dose, or check yours is a large model."),
        NoteCode.BASKET: QApplication.translate("tilauscope_brew", "A {d} g dose will not fit a normal espresso basket (~{cap} g maximum)."),
        NoteCode.WATER_GH_HIGH: QApplication.translate("tilauscope_brew", "High hardness (GH, Ca/Mg): raises extraction — grind a touch coarser to stay in range."),
        NoteCode.WATER_GH_LOW: QApplication.translate("tilauscope_brew", "Low hardness (GH): lowers extraction and body — grind slightly finer."),
        NoteCode.WATER_KH_HIGH: QApplication.translate("tilauscope_brew", "High alkalinity (KH): buffers and mutes acidity — bright/acid-forward coffees taste flatter."),
        NoteCode.WATER_KH_LOW: QApplication.translate("tilauscope_brew", "Low alkalinity (KH): little buffering — acidity reads sharp, watch for sourness."),
        NoteCode.WATER_SCA: QApplication.translate("tilauscope_brew", "Water near SCA target (≈GH 68 / KH 40): balanced extraction window."),
        NoteCode.REST_FRESH: QApplication.translate("tilauscope_brew", "Very fresh ({d}d): heavy degassing → unstable extraction. Longer bloom / pre-infusion."),
        NoteCode.REST_OPTIMAL: QApplication.translate("tilauscope_brew", "Optimal rest ({d}d): stable degassing window."),
        NoteCode.REST_NEARPEAK: QApplication.translate("tilauscope_brew", "Rested ({d}d): nearing peak, slightly finer is fine."),
        NoteCode.REST_STALE: QApplication.translate("tilauscope_brew", "Stale ({d}d): oxidative staling is largely irreversible — flavors will read flat/papery whatever the brew."),
        NoteCode.MOISTURE_AW_DRY: QApplication.translate("tilauscope_brew", "Green aw {aw}: below your storage window — dried-out beans lose aromatics, expect a flatter cup."),
        NoteCode.MOISTURE_AW_WATCH: QApplication.translate("tilauscope_brew", "Green aw {aw}: in your storage watch zone — faster staling, brew within the optimal rest."),
        NoteCode.MOISTURE_AW_RISK: QApplication.translate("tilauscope_brew", "Green aw {aw}: above your storage risk threshold — check the bean in the Storage tab before brewing."),
        NoteCode.MOISTURE_GREEN_HIGH: QApplication.translate("tilauscope_brew", "Green moisture {m}% (high): extraction may run slow."),
        NoteCode.SPREAD_HIGH: QApplication.translate("tilauscope_brew", "High spread: shell over-developed vs core. Lower temp, gentler, longer brew."),
        NoteCode.SPREAD_EXCELLENT: QApplication.translate("tilauscope_brew", "Excellent uniformity: you can push extraction (finer) without fear."),
        NoteCode.AI_ADJUSTED: "{tip}",
    }.get(code, "")
    try:
        return tpl.format(**params) if params else tpl
    except Exception:  # noqa: BLE001
        return tpl


def _step_text(key: str, params: dict) -> str:
    g = params.get("g", 0)
    s = params.get("s", 0)
    tpl = {
        "step_es_flush": QApplication.translate("tilauscope_brew", "Cooling flush to drop brew temperature"),
        "step_es_preheat": QApplication.translate("tilauscope_brew", "Pre-heat group with a hot-water flush (cold group otherwise)"),
        "step_es_prewet": QApplication.translate("tilauscope_brew", "Pre-wet: low-pressure puck saturation"),
        "step_es_prebrew": QApplication.translate("tilauscope_brew", "Low-flow pre-brew ~{s} s"),
        "step_es_pi": QApplication.translate("tilauscope_brew", "Pre-infusion ~{s} s"),
        # Pre-infusion split into the two gestures it really is, so a
        # paddle or lever owner knows where his hand goes and when nothing
        # should be flowing. Line-pressure wording for a paddle machine, lever
        # wording for an E61 or a manual group.
        "step_es_pi_wet_line": QApplication.translate("tilauscope_brew", "Paddle to pre-infusion: water fills the puck, ~{s} s"),
        "step_es_pi_dwell_line": QApplication.translate("tilauscope_brew", "Hold there — nothing flows, the puck settles, ~{s} s"),
        "step_es_pi_wet_lever": QApplication.translate("tilauscope_brew", "Lever half-up: water in at line pressure, ~{s} s"),
        "step_es_pi_dwell_lever": QApplication.translate("tilauscope_brew", "Keep it half-up — nothing flows, the puck settles, ~{s} s"),
        "step_es_full": QApplication.translate("tilauscope_brew", "Full pressure, watch first drops ~6-9 s"),
        "step_es_full_line": QApplication.translate("tilauscope_brew", "Open the paddle fully, watch first drops ~6-9 s"),
        "step_es_full_lever": QApplication.translate("tilauscope_brew", "Lever all the way up, watch first drops ~6-9 s"),
        "step_es_stop": QApplication.translate("tilauscope_brew", "Stop at yield {g} g"),
        "step_moka_fill": QApplication.translate("tilauscope_brew", "Fill base with pre-heated water below the valve"),
        "step_moka_grounds": QApplication.translate("tilauscope_brew", "Add grounds (level, no tamp), assemble"),
        "step_moka_heat": QApplication.translate("tilauscope_brew", "Medium heat, lid open"),
        "step_moka_gurgle": QApplication.translate("tilauscope_brew", "Remove at first gurgle, cool the base"),
        "step_fp_add": QApplication.translate("tilauscope_brew", "Add all water {g} g, stir"),
        "step_fp_steep": QApplication.translate("tilauscope_brew", "Steep (lid on, plunger up)"),
        "step_fp_crust": QApplication.translate("tilauscope_brew", "Break + skim the crust"),
        "step_fp_press": QApplication.translate("tilauscope_brew", "Press slowly & decant"),
        "step_ap_add": QApplication.translate("tilauscope_brew", "Add all water {g} g"),
        "step_ap_stir": QApplication.translate("tilauscope_brew", "Stir 10 s, cap"),
        "step_ap_steep": QApplication.translate("tilauscope_brew", "Steep"),
        "step_ap_press": QApplication.translate("tilauscope_brew", "Press slowly (~30 s)"),
        "step_bird_add": QApplication.translate("tilauscope_brew", "Add grounds + all water {g} g"),
        "step_bird_vortex": QApplication.translate("tilauscope_brew", "Vortex stir with the arm"),
        "step_bird_steep": QApplication.translate("tilauscope_brew", "Steep"),
        "step_bird_pull": QApplication.translate("tilauscope_brew", "Wind wingnut, pull the pod (vacuum)"),
        "step_bloom": QApplication.translate("tilauscope_brew", "Bloom {g} g, swirl / WDT"),
        "step_pulsar_spin": QApplication.translate("tilauscope_brew", "Valve closed, spin to flatten the bed"),
        "step_pulsar_main": QApplication.translate("tilauscope_brew", "Open valve, main pour to {g} g"),
        "step_pulsar_draw": QApplication.translate("tilauscope_brew", "Spin between pours; drawdown"),
        "step_v60_pour1": QApplication.translate("tilauscope_brew", "Pour to {g} g"),
        "step_v60_pour2": QApplication.translate("tilauscope_brew", "Pour to {g} g"),
        "step_v60_draw": QApplication.translate("tilauscope_brew", "Drawdown complete"),
    }.get(key, key)
    try:
        # round, not truncate: the step sentence and its target pill must agree
        return tpl.format(g=round(g), s=round(s))
    except Exception:  # noqa: BLE001
        return tpl


def _diagnosis_text(code: DiagnosisCode) -> tuple[str, str]:
    """(verdict, what to do) for a taste diagnosis. The engine returns codes;
    the wording lives here, like NoteCode."""
    return {
        DiagnosisCode.UNDER_FAST: (
            QApplication.translate("tilauscope_brew", "Under-extracted — it ran fast"),
            QApplication.translate("tilauscope_brew",
                "Water passed too quickly to dissolve enough. The grind is the lever.")),
        DiagnosisCode.UNDER_ON_TIME: (
            QApplication.translate("tilauscope_brew", "Under-extracted — but on time"),
            QApplication.translate("tilauscope_brew",
                "The grind is about right, so push extraction another way: hotter water, "
                "or more agitation during the brew.")),
        DiagnosisCode.OVER_SLOW: (
            QApplication.translate("tilauscope_brew", "Over-extracted — it ran slow"),
            QApplication.translate("tilauscope_brew",
                "Water stayed in contact too long and pulled out the harsh compounds.")),
        DiagnosisCode.UNDER_NO_TIME: (
            QApplication.translate("tilauscope_brew", "Sour — most likely under-extracted"),
            QApplication.translate("tilauscope_brew",
                "A finer grind is the usual fix. Without a measured brew time this cannot be "
                "told apart from channelling though — so if the brew also felt slow, leave the "
                "grind alone and fix the distribution instead.")),
        DiagnosisCode.OVER_NO_TIME: (
            QApplication.translate("tilauscope_brew", "Bitter — most likely over-extracted"),
            QApplication.translate("tilauscope_brew",
                "A coarser grind is the usual fix. Without a measured brew time this cannot be "
                "told apart from channelling though — so if the brew also felt fast, leave the "
                "grind alone and fix the distribution instead.")),
        DiagnosisCode.OVER_ON_TIME: (
            QApplication.translate("tilauscope_brew", "Over-extracted"),
            QApplication.translate("tilauscope_brew",
                "Too much was dissolved. Coarsen a step to slow the extraction down.")),
        DiagnosisCode.CHANNELING: (
            QApplication.translate("tilauscope_brew", "Channelling — slow AND sour"),
            QApplication.translate("tilauscope_brew",
                "Slow and sour together means the water found a path through the bed "
                "instead of extracting it evenly. Grinding finer would make this worse. "
                "Fix the distribution: WDT, level the bed, gentler first pour.")),
        DiagnosisCode.CHANNELING_FINES: (
            QApplication.translate("tilauscope_brew", "Channelling — fast AND bitter"),
            QApplication.translate("tilauscope_brew",
                "Fast but bitter means part of the bed over-extracted while the rest was "
                "bypassed — usually fines migrating. Improve distribution before touching "
                "the grind size.")),
        DiagnosisCode.UNEVEN: (
            QApplication.translate("tilauscope_brew", "Uneven extraction"),
            QApplication.translate("tilauscope_brew",
                "Sour and bitter at once means part of the bed under-extracted while part "
                "over-extracted. No single grind size fixes that — only better distribution "
                "does (WDT, level bed, even pouring).")),
        DiagnosisCode.ASTRINGENT: (
            QApplication.translate("tilauscope_brew", "Astringent / drying"),
            QApplication.translate("tilauscope_brew",
                "That drying, mouth-puckering edge is over-extraction. Coarsen a step and "
                "drop the temperature slightly.")),
        DiagnosisCode.WEAK_BODY: (
            QApplication.translate("tilauscope_brew", "Thin body"),
            QApplication.translate("tilauscope_brew",
                "Body is the ratio's job, not the grind's. Use less water for the same dose.")),
        DiagnosisCode.STALE: (
            QApplication.translate("tilauscope_brew", "The bean is past its window"),
            QApplication.translate("tilauscope_brew",
                "This roast is stale, and oxidative staling cannot be brewed back. Nothing "
                "is adjusted — the cup is explained by the bean, not by the recipe.")),
        DiagnosisCode.BALANCED: (
            QApplication.translate("tilauscope_brew", "Balanced — nothing to change"),
            QApplication.translate("tilauscope_brew",
                "Save it and the next brew of this bean will open on this setting.")),
        DiagnosisCode.NO_SIGNAL: ("", ""),
    }.get(code, ("", ""))


_SEV_COLOR = {
    Severity.GOOD: THEME["SUCCESS"], Severity.WARN: THEME["WARNING"],
    Severity.CRIT: THEME["CRITICAL"], Severity.INFO: THEME["SUBTEXT"],
}
_WATER_ITEMS = (
    (WaterProfile.AUTO, QT_TRANSLATE_NOOP("tilauscope_brew", "Auto / measured")),
    (WaterProfile.SCA,  QT_TRANSLATE_NOOP("tilauscope_brew", "SCA target")),
    (WaterProfile.SOFT, QT_TRANSLATE_NOOP("tilauscope_brew", "Soft")),
    (WaterProfile.HARD, QT_TRANSLATE_NOOP("tilauscope_brew", "Hard")),
)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _clear_layout(lay) -> None:
    """Drop every child widget of a layout (recipe panels are rebuilt on each
    recompute rather than diffed — the row count is tiny)."""
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


# ── Recipe presentation widgets ───────────────────────────────────────────
class _KpiTile(QFrame):
    """One headline recipe number: small-caps caption, large mono value and an
    optional low-contrast qualifier underneath (e.g. the grind category)."""

    def __init__(self, caption: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("kpiTile")
        self.setStyleSheet(
            f"QFrame#kpiTile {{ background:{THEME['SURFACE']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:10px; }}"
            f" QLabel {{ border:none; background:transparent; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        self._cap = QLabel(caption.upper())
        self._cap.setProperty('variant', 'eyebrow')
        self._val = QLabel("—")
        self._val.setProperty('variant', 'readout-sm')
        self._val.setStyleSheet(f"color: {THEME['TEXT']};")
        self._sub = QLabel("")
        self._sub.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:10px;")
        self._sub.setVisible(False)
        lay.addWidget(self._cap)
        lay.addWidget(self._val)
        lay.addWidget(self._sub)

    def set_caption(self, text: str) -> None:
        self._cap.setText(text.upper())

    def set_value(self, value: str, sub: str = "") -> None:
        self._val.setText(value)
        self._sub.setText(sub)
        self._sub.setVisible(bool(sub))


def _make_chip(text: str, color: Optional[str] = None) -> QLabel:
    """Low-contrast pill for secondary recipe context (roast level, agitation…)."""
    c = color or THEME["SUBTEXT"]
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{c}; background:{THEME['SURFACE']};"
        f" border:1px solid {THEME['BORDER']}; border-radius:9px;"
        f" padding:2px 9px; font-size:11px;")
    return lbl


class _StepRow(QFrame):
    """One protocol step: coloured left rail, time badge, instruction and an
    optional target-weight pill.

    ``set_state`` already carries the DONE / CURRENT / PENDING styling so the
    live checklist in phase 2 only has to drive it.
    """

    PENDING, CURRENT, DONE = 0, 1, 2

    def __init__(self, time_str: str, text: str, target_str: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("stepRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._rail = QFrame()
        self._rail.setFixedWidth(3)
        lay.addWidget(self._rail)

        inner = QHBoxLayout()
        inner.setContentsMargins(10, 6, 10, 6)
        inner.setSpacing(10)
        self._time = QLabel(time_str)
        self._time.setFixedWidth(42)
        self._text = QLabel(text)
        self._text.setWordWrap(True)
        self._target = QLabel(target_str)
        self._target.setVisible(bool(target_str))
        inner.addWidget(self._time)
        inner.addWidget(self._text, 1)
        inner.addWidget(self._target)
        lay.addLayout(inner, 1)

        self.set_state(self.PENDING)

    def set_state(self, state: int) -> None:
        self._state = state
        if state == self.DONE:
            rail, time_c, text_c = THEME["SUCCESS"], THEME["SUBTEXT"], THEME["SUBTEXT"]
            bg = "transparent"
        elif state == self.CURRENT:
            rail, time_c, text_c = THEME["ACCENT"], THEME["ACCENT"], THEME["TEXT"]
            bg = "rgba(137,180,250,22)"
        else:
            rail, time_c, text_c = THEME["BORDER"], THEME["ACCENT"], THEME["TEXT"]
            bg = "transparent"
        self._rail.setStyleSheet(f"background:{rail}; border:none; border-radius:1px;")
        self.setStyleSheet(f"QFrame#stepRow {{ background:{bg}; border-radius:6px; }}")
        self._time.setStyleSheet(
            f"color:{time_c};font-size:12px;"
            f"font-weight:bold;background:transparent;border:none;")
        self._text.setStyleSheet(
            f"color:{text_c};font-size:12px;"
            f"background:transparent;border:none;")
        self._target.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:11px;"
            f"font-weight:bold;background:{THEME['SURFACE']};"
            f"border:1px solid {THEME['BORDER']};border-radius:8px;padding:1px 7px;")


class _DiagnosticsBox(QWidget):
    """Collapsed-by-default notes list. The header shows the count plus one
    severity dot per note so the panel stays scannable when folded."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._btn = QPushButton("")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{THEME['SUBTEXT']};"
            f" border:none; padding:4px 0; text-align:left;"
            f" font-size:12px; font-weight:bold; }}"
            f" QPushButton:hover {{ color:{THEME['ACCENT']}; }}")
        self._btn.clicked.connect(self._toggle)
        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:12px;"
            f"background:{THEME['SURFACE']};border:1px solid {THEME['BORDER']};"
            f"border-radius:8px;padding:8px 10px;")
        self._body.setVisible(False)
        lay.addWidget(self._btn)
        lay.addWidget(self._body)
        self._expanded = False
        self._count = 0
        self._dots = ""

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded and self._count > 0)
        self._sync_header()

    def _sync_header(self) -> None:
        arrow = "▾" if self._expanded else "▸"
        label = (QApplication.translate("tilauscope_brew", "1 diagnostic") if self._count == 1
                 else QApplication.translate("tilauscope_brew", "{n} diagnostics").format(n=self._count))
        self._btn.setText(f"{arrow}  {label}   {self._dots}")

    def set_notes(self, notes) -> None:
        self._count = len(notes)
        # QPushButton renders plain text only: the folded header carries one
        # neutral dot per note, colours live in the expanded body.
        self._dots = "●" * min(self._count, 8)
        self._btn.setVisible(self._count > 0)
        if self._count == 0:
            self._body.setVisible(False)
            return
        self._body.setText("".join(
            f"<div style='color:{_SEV_COLOR.get(sev, THEME['SUBTEXT'])};margin:2px 0;'>"
            + ("✦ " if code == NoteCode.AI_ADJUSTED else "• ")
            + f"{_note_text(code, params)}</div>" for sev, code, params in notes))
        self._body.setVisible(self._expanded)
        self._sync_header()


# ── Protocol → target corridor ────────────────────────────────────────────
def _poly_at(pts: list[tuple[float, float]], t: float) -> float:
    """Value of a piecewise-linear polyline at t. Envelopes contain vertical
    segments (instant jumps), so the LAST segment covering t wins — i.e. the
    value after the jump."""
    if not pts:
        return 0.0
    if t < pts[0][0]:
        return pts[0][1]
    # NB: strict `<` — at t == pts[0][0] the loop must run, so an envelope that
    # jumps vertically at t=0 (bloom target already due) resolves post-jump.
    val = pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:], strict=False):
        if t0 <= t <= t1:
            val = v1 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    if t >= pts[-1][0]:
        val = pts[-1][1]
    return val


def _build_corridor(rec) -> tuple[list, list, list]:
    """Turn the recipe protocol into a reach-by corridor (lower, upper, marks).

    A step target is a deadline, not a trajectory: pouring 150 g "at 0:45" is
    on-plan whether you finish in 10 s or coast until the next step opens. So
    the upper edge assumes the target is hit the instant the step opens and the
    lower edge assumes it is only hit as the NEXT step opens. Staying inside the
    band is what "on plan" means.

    Two shapes exist in practice, told apart by whether the first step already
    carries a target: percolation/immersion place water on a schedule
    (staircase), while pressure extractions accumulate beverage continuously
    from first drop (ramp with a grams tolerance).
    """
    steps = list(getattr(rec, "steps", []) or [])
    total = float(max(getattr(rec, "total_time_s", 0), 1))
    marks = [float(s.at_s) for s in steps]
    tgts = [(float(s.at_s), float(s.target_g)) for s in steps if s.target_g > 0]
    if not tgts:
        return [], [], marks

    if not (steps and steps[0].target_g > 0):
        # Pressure: beverage only starts accumulating once the puck/pot flows.
        t_end, g_end = tgts[-1]
        t_end = max(t_end, 1.0)
        prev = [float(s.at_s) for s in steps if s.at_s < t_end]
        t0 = max(prev[-1], 0.0) if prev else t_end * 0.3
        tol = max(1.5, g_end * 0.08)
        lo = [(0.0, 0.0), (min(t0 + 2.0, t_end), 0.0), (t_end, max(g_end - tol, 0.0))]
        hi = [(0.0, 0.0), (max(t0 - 1.0, 0.0), 0.0), (t_end, g_end + tol)]
        return lo, hi, marks

    # Staircase: one plateau per pour, upper jumps at the step, lower at the next.
    hi_pts: list[tuple[float, float]] = [(0.0, 0.0)]
    lo_pts: list[tuple[float, float]] = [(0.0, 0.0)]
    for i, (t, g) in enumerate(tgts):
        if g <= hi_pts[-1][1]:
            continue  # same plateau held across several steps
        nxt = tgts[i + 1][0] if i + 1 < len(tgts) else total
        hi_pts.append((t, hi_pts[-1][1]))
        hi_pts.append((t, g))
        lo_pts.append((nxt, lo_pts[-1][1]))
        lo_pts.append((nxt, g))
    hi_pts.append((total, hi_pts[-1][1]))
    lo_pts.append((max(total, lo_pts[-1][0]), lo_pts[-1][1]))
    return lo_pts, hi_pts, marks


# ── Live extraction chart (weight vs. plan corridor, flow underneath) ──────
class _ExtractionChart(QWidget):
    """weight(t) read against the protocol corridor, with flow as a filled
    band along the bottom.

    Flow uses a FIXED per-family scale rather than auto-ranging: a rescaling
    axis makes the trace jump while pouring, which reads as a flow change that
    never happened.
    """

    _ML, _MR, _MT, _MB = 40, 10, 10, 20   # plot margins (axis labels)
    _FLOW_BAND = 0.30                     # share of plot height given to flow

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pts: list[tuple[float, float]] = []
        self._flow: list[tuple[float, float]] = []
        self._marker: Optional[tuple[float, float]] = None
        self._lo: list[tuple[float, float]] = []
        self._hi: list[tuple[float, float]] = []
        self._marks: list[float] = []
        self._target_g: float = 0.0
        self._target_t: float = 0.0
        self._flow_max: float = 10.0
        # Kept low on purpose: the debrief card shares this column once the brew
        # stops, and a tall minimum here pushed it into an overlap.
        self.setMinimumHeight(120)

    # ── plan / data ──
    def set_plan(self, target_g: float, target_t: float, lo, hi, marks,
                 flow_max: float) -> None:
        self._target_g, self._target_t = target_g, target_t
        self._lo, self._hi, self._marks = lo, hi, marks
        self._flow_max = max(flow_max, 0.5)
        self.update()

    def band_at(self, t: float) -> Optional[tuple[float, float]]:
        if not self._lo or not self._hi:
            return None
        return _poly_at(self._lo, t), _poly_at(self._hi, t)

    def set_points(self, pts) -> None:
        self._pts = pts
        self.update()

    def set_flow(self, pts) -> None:
        self._flow = pts
        self.update()

    def set_marker(self, marker) -> None:
        self._marker = marker
        self.update()

    def clear(self) -> None:
        self._pts, self._flow, self._marker = [], [], None
        self.update()

    # ── painting ──
    @staticmethod
    def _tick_step(span: float) -> int:
        for limit, step in ((60, 15), (180, 30), (360, 60), (900, 120)):
            if span <= limit:
                return step
        return 300

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        x0, x1 = self._ML, w - self._MR
        y0, y1 = self._MT, h - self._MB
        if x1 <= x0 or y1 <= y0:
            p.end()
            return

        last_t = self._pts[-1][0] if self._pts else 0.0
        last_g = max((g for _, g in self._pts), default=0.0)
        max_t = max(self._target_t, last_t, 1.0) * 1.02
        max_g = max(self._target_g * 1.12, last_g * 1.05, 1.0)

        def X(t: float) -> float:
            return x0 + (x1 - x0) * (t / max_t)

        def Yg(g: float) -> float:
            return y1 - (y1 - y0) * _clamp(g / max_g, 0.0, 1.0)

        def Yf(f: float) -> float:
            return y1 - (y1 - y0) * self._FLOW_BAND * _clamp(f / self._flow_max, 0.0, 1.0)

        sub, border = QColor(THEME["SUBTEXT"]), QColor(THEME["BORDER"])
        font = p.font()
        font.setFamily("JetBrains Mono")
        font.setPointSize(8)
        p.setFont(font)

        # ── grid + axes ──
        p.setPen(QPen(border, 1))
        p.drawLine(QPointF(x0, y1), QPointF(x1, y1))
        step = self._tick_step(max_t)
        t = 0.0
        while t <= max_t:
            gx = X(t)
            p.setPen(QPen(border, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(gx, y0), QPointF(gx, y1))
            p.setPen(sub)
            p.drawText(QRectF(gx - 24, y1 + 2, 48, 14),
                       int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                       f"{int(t) // 60}:{int(t) % 60:02d}")
            t += step
        for gval in (self._target_g, self._target_g / 2.0):
            if gval <= 0:
                continue
            gy = Yg(gval)
            p.setPen(QPen(border, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x0, gy), QPointF(x1, gy))
            p.setPen(sub)
            p.drawText(QRectF(0, gy - 7, self._ML - 5, 14),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       f"{gval:.0f}")

        # ── step markers (ticks only: the protocol list carries the labels) ──
        for mt in self._marks:
            if mt <= 0 or mt > max_t:
                continue
            mx = X(mt)
            p.setPen(QPen(border, 1))
            p.drawLine(QPointF(mx, y1 - 4), QPointF(mx, y1 + 3))

        # ── plan corridor ──
        if len(self._lo) >= 2 and len(self._hi) >= 2:
            band = QPolygonF([QPointF(X(t), Yg(g)) for t, g in self._hi]
                             + [QPointF(X(t), Yg(g)) for t, g in reversed(self._lo)])
            p.setPen(Qt.PenStyle.NoPen)
            fill = QColor(THEME["ACCENT"])
            fill.setAlpha(34)
            p.setBrush(fill)
            p.drawPolygon(band)
            edge = QColor(THEME["ACCENT"])
            edge.setAlpha(90)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(edge, 1, Qt.PenStyle.DashLine))
            p.drawPolyline(QPolygonF([QPointF(X(t), Yg(g)) for t, g in self._hi]))
            p.drawPolyline(QPolygonF([QPointF(X(t), Yg(g)) for t, g in self._lo]))

        # ── flow area (fixed scale, bottom band) ──
        if len(self._flow) >= 2:
            poly = QPolygonF([QPointF(X(self._flow[0][0]), y1)]
                             + [QPointF(X(ft), Yf(f)) for ft, f in self._flow]
                             + [QPointF(X(self._flow[-1][0]), y1)])
            fill = QColor(THEME["WARNING"])
            fill.setAlpha(46)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPolygon(poly)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(THEME["WARNING"]), 1))
            p.drawPolyline(QPolygonF([QPointF(X(ft), Yf(f)) for ft, f in self._flow]))

        # ── live weight curve + head dot ──
        if len(self._pts) >= 2:
            p.setPen(QPen(QColor(THEME["ACCENT"]), 2))
            p.drawPolyline(QPolygonF([QPointF(X(t), Yg(g)) for t, g in self._pts]))
        if self._pts and self._marker is None:
            ht, hg = self._pts[-1]
            p.setBrush(QColor(THEME["ACCENT"]))
            p.setPen(QPen(QColor(THEME["BG"]), 1))
            p.drawEllipse(QPointF(X(ht), Yg(hg)), 3.5, 3.5)

        # ── stop marker ──
        if self._marker is not None:
            mx, my = X(self._marker[0]), Yg(self._marker[1])
            p.setPen(QPen(QColor(THEME["SUCCESS"]), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(mx, y0), QPointF(mx, y1))
            p.setBrush(QColor(THEME["SUCCESS"]))
            p.setPen(QPen(QColor(THEME["SUCCESS"]), 1))
            p.drawEllipse(QPointF(mx, my), 4.0, 4.0)

        # ── legend ──
        p.setPen(QColor(THEME["ACCENT"]))
        p.drawText(QRectF(x0 + 2, y0 - 2, 70, 14), int(Qt.AlignmentFlag.AlignLeft), "g")
        p.setPen(QColor(THEME["WARNING"]))
        p.drawText(QRectF(x1 - 70, y0 - 2, 70, 14), int(Qt.AlignmentFlag.AlignRight),
                   f"g/s · max {self._flow_max:.0f}")
        p.end()


# ── Slim progress-to-target bar ───────────────────────────────────────────
class _TargetBar(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._frac = 0.0
        self.setFixedHeight(6)

    def set_fraction(self, frac: float) -> None:
        self._frac = _clamp(frac, 0.0, 1.0)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(THEME["BORDER"]))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 3, 3)
        if self._frac > 0:
            p.setBrush(QColor(THEME["ACCENT"]))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self._frac, self.height()), 3, 3)
        p.end()


# ── Service (signal-based, owns AI merge) ─────────────────────────────────
class BrewAdvisorService(QObject):
    recipe_ready = pyqtSignal(object)  # BrewRecipe

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._engine = BrewAdvisor()
        self._input = BrewInput()
        self._method = METHOD_ORDER[0]
        self._dose: Optional[float] = None
        self._last: Optional[BrewRecipe] = None
        # Accepted taste corrections, per method. Re-applied on every recompute
        # so a dial-in survives a dose change instead of being recomputed away.
        self._dialin: dict[str, BrewCorrection] = {}
        # Dialled-in dose, per method, for PRESSURE brewing only. On a
        # pressure brewer the dose is not a preference: the basket sets it, and
        # reopening on the method default silently changes the puck the whole
        # dial-in was built on. Filter doses stay on the method default — there
        # the dose is a free choice (cup size), and pinning last time's would
        # fight the operator every time they brew a different volume.
        self._dialin_dose: dict[str, float] = {}
        # When each dial-in was accepted (ISO date, '' if unknown). A
        # dial-in never expires on its own — it was made on ONE roast of this
        # green bean, and reopening it a season later is plausible but not
        # guaranteed. Showing its age lets the operator judge instead of
        # trusting a setting whose origin is invisible.
        self._dialin_date: dict[str, str] = {}
        # Methods whose dose the operator has set BY HAND this session.
        # Restoring the dialled-in dose is right when you arrive on a method; doing
        # it again after you have deliberately typed another one is the app arguing
        # with you — the change simply vanished on a round-trip through another
        # method. Their gesture wins until they accept a new dial-in at that dose.
        self._dose_touched: dict[str, float] = {}
        # Learned cross-bean offset, per family key ("pressure"/"other"). Applied
        # ONLY when this bean has no dial-in of its own — a bean dial-in already
        # contains the systematic bias, so stacking both would count it twice.
        self._setup_offset: dict[str, float] = {}
        self._setup_samples: dict[str, int] = {}

    def set_input(self, inp: BrewInput, emit: bool = True) -> None:
        self._input = inp
        if emit:
            self.recompute()

    def set_method(self, method_id: str) -> None:
        self._method = method_id
        self._dose = self.dose_for_method(method_id)
        self.recompute()

    def dose_for_method(self, method_id: str) -> Optional[float]:
        """The dose to open this method on: the operator's own gesture first, then
        the dialled-in dose, then None (the method's default)."""
        touched = self._dose_touched.get(method_id)
        return touched if touched else self._dialin_dose.get(method_id)

    def set_dialin_dose(self, method_id: str, dose_g: Optional[float]) -> None:
        """Remember the dose a PRESSURE dial-in was built on (see _dialin_dose)."""
        if not dose_g or dose_g <= 0 or self.family_key(method_id) != "pressure":
            self._dialin_dose.pop(method_id, None)
        else:
            self._dialin_dose[method_id] = float(dose_g)

    def dialin_dose_for(self, method_id: str) -> Optional[float]:
        return self._dialin_dose.get(method_id)

    def set_dialin_date(self, method_id: str, iso_date: str) -> None:
        if iso_date:
            self._dialin_date[method_id] = str(iso_date)
        else:
            self._dialin_date.pop(method_id, None)

    def dialin_date_for(self, method_id: str) -> str:
        return self._dialin_date.get(method_id, "")

    def set_dose(self, dose_g: float) -> None:
        self._dose = float(dose_g)
        self._dose_touched[self._method] = self._dose
        self.recompute()

    def set_water(self, profile: WaterProfile) -> None:
        self._input.water_profile = profile
        self.recompute()

    def set_espresso_machine(self, mc: EspressoMachine) -> None:
        self._input.espresso_machine = mc
        self.recompute()

    def set_espresso_style(self, st: EspressoStyle) -> None:
        self._input.espresso_style = st
        self.recompute()

    @property
    def method(self) -> str:
        return self._method

    @property
    def input(self) -> BrewInput:
        return self._input

    @property
    def last(self) -> Optional[BrewRecipe]:
        return self._last

    # ── dial-in (accepted taste corrections) ──
    def dialin_for(self, method_id: str) -> Optional[BrewCorrection]:
        return self._dialin.get(method_id)

    def set_dialin(self, method_id: str, corr: Optional[BrewCorrection],
                   emit: bool = True) -> None:
        if corr is None:
            self._dialin.pop(method_id, None)
        else:
            self._dialin[method_id] = corr
        if emit:
            self.recompute()

    def add_correction(self, corr: BrewCorrection) -> None:
        """Compose a new correction onto the current dial-in for this method.

        Dial-in converges by iterating, so corrections compose rather than
        replace — but the cumulative result is clamped so a run of bad cups can
        never walk the recipe somewhere absurd.
        """
        cur = self._dialin.get(self._method)
        if cur is None:
            composed = corr
        else:
            composed = BrewCorrection(
                grind_mult=cur.grind_mult * corr.grind_mult,
                ratio_delta=cur.ratio_delta + corr.ratio_delta,
                temp_delta=cur.temp_delta + corr.temp_delta)
        composed = BrewCorrection(
            grind_mult=_clamp(composed.grind_mult, 0.60, 1.60),
            ratio_delta=_clamp(composed.ratio_delta, -4.0, 4.0),
            temp_delta=_clamp(composed.temp_delta, -5.0, 5.0))
        self.set_dialin(self._method, composed)

    @staticmethod
    def _apply_correction(rec: BrewRecipe, corr: BrewCorrection) -> None:
        """Fold a dial-in into a freshly computed recipe, in place."""
        if abs(corr.grind_mult - 1.0) > 1e-6:
            rec.grind_um = int(_clamp(round(rec.grind_um * corr.grind_mult), 150, 1300))
            rec.grind_cat = grind_cat(rec.grind_um)
        if abs(corr.temp_delta) > 1e-6:
            rec.temp_c = float(round(_clamp(rec.temp_c + corr.temp_delta, 80.0, 99.0)))
        if abs(corr.ratio_delta) > 1e-6:
            m = _re.search(r"1:([\d.]+)", rec.ratio_str)
            if m:
                base = max(ratio_floor(rec.family), float(m.group(1)) + corr.ratio_delta)
                rec.ratio_str = f"1:{base:.0f}" if abs(base - round(base)) < 0.05 else f"1:{base:.1f}"
                old_w = rec.water_g
                rec.water_g = round(rec.dose_g * base, 0)
                # The steps carry the pour plan the operator actually brews to;
                # scale them with the total so the correction reaches the cup, not just the on-screen KPI.
                if old_w > 0 and rec.steps:
                    k = rec.water_g / old_w
                    for st in rec.steps:
                        if st.target_g > 0:
                            st.target_g = round(st.target_g * k, 1)

    def base_recipe(self) -> Optional[BrewRecipe]:
        """The engine's recommendation with no dial-in folded in."""
        try:
            return self._engine.advise(self._input, self._method, self._dose)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def family_key(method_id: str) -> str:
        """Espresso and filter are different physical regimes; a correction
        learned on one says little about the other."""
        fam = METHOD_ANCHORS[method_id].family
        return "pressure" if fam == BrewFamily.PRESSURE else "other"

    def set_setup_offset(self, key: str, mult: Optional[float], samples: int = 0) -> None:
        if mult is None:
            self._setup_offset.pop(key, None)
            self._setup_samples.pop(key, None)
        else:
            self._setup_offset[key] = mult
            self._setup_samples[key] = samples

    def setup_offset_for(self, method_id: str) -> tuple[Optional[float], int]:
        k = self.family_key(method_id)
        return self._setup_offset.get(k), self._setup_samples.get(k, 0)

    def recompute(self) -> None:
        rec = self._engine.advise(self._input, self._method, self._dose)
        corr = self._dialin.get(self._method)
        if corr is not None and not corr.is_empty:
            self._apply_correction(rec, corr)
            rec.dialed_in = True
        else:
            mult, _n = self.setup_offset_for(self._method)
            if mult is not None:
                self._apply_correction(rec, BrewCorrection(grind_mult=mult))
                rec.setup_adjusted = True
        self._last = rec
        self.recipe_ready.emit(rec)

    def apply_ai(self, data: dict) -> bool:
        """Merge bounded AI adjustments into the current recipe. Returns True if
        anything changed. Silently ignores empty/invalid payloads."""
        if not self._last or not isinstance(data, dict):
            return False
        rec = copy.deepcopy(self._last)
        changed = False
        # Routed through _apply_correction rather than reimplemented, so the water,
        # pour steps, checklist, auto-stop target and espresso path — and the ratio
        # floor — all move together instead of drifting apart. One implementation
        # of "fold an adjustment into a recipe" is the fix for all three.
        td = _clamp(float(data.get("temp_delta_c", 0) or 0), -2.0, 2.0)
        gp = _clamp(float(data.get("grind_pct", 0) or 0), -10.0, 10.0)
        rd = _clamp(float(data.get("ratio_delta", 0) or 0), -1.0, 1.0)
        corr = BrewCorrection(
            grind_mult=(1 + gp / 100.0) if abs(gp) >= 0.5 else 1.0,
            ratio_delta=rd if abs(rd) >= 0.1 else 0.0,
            # Whole degrees, consistent with the engine ([S1] coarse anchor).
            temp_delta=td if abs(td) >= 0.1 else 0.0)
        if not corr.is_empty:
            self._apply_correction(rec, corr)
            changed = True
        for tip in (data.get("tips") or [])[:2]:
            if isinstance(tip, str) and tip.strip():
                rec.notes.append((Severity.INFO, NoteCode.AI_ADJUSTED, {"tip": tip.strip()[:180]}))
                changed = True
        if changed:
            rec.ai_adjusted = True
            self._last = rec
            self.recipe_ready.emit(rec)
        return changed


# ── Dialog ────────────────────────────────────────────────────────────────
class BrewAdvisorDlg(QDialog):
    def __init__(self, inp: BrewInput, title: str = "", aw=None, beancave=None, bean=None):
        super().__init__(None)  # parent=None: avoid Qt embedding on macOS
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.aw = aw
        # GreenBean this roast belongs to; carries the saved taste dial-ins.
        # None when the advisor is opened outside the BeanCave workflow.
        self._bean = bean
        self._pending_fix = None
        self._applying_fix = False
        # BeanCave host (owns the Niimbot printer `np`); used to print the
        # 50×30 dial-in label. None when opened outside the BeanCave workflow.
        self._beancave = beancave
        self._mode = getattr(getattr(aw, "qmc", None), "mode", "C") or "C"
        self._title = title or QApplication.translate("tilauscope_brew", "Roast")
        self.service = BrewAdvisorService(self)
        self._building = True
        self._drag_pos: Optional[QPoint] = None
        self._ai_busy = False
        # live-brew state
        self._brew_running = False
        # True only when THIS dialog brought the scale online, so closing releases
        # it without stealing a scale the rest of the app was already using.
        self._we_connected_scale = False
        self._search_started = False
        self._brew_rec = None       # plan frozen at Start; None outside a brew
        self._step_idx = -1
        self._step_actuals: dict[int, tuple[float, float]] = {}
        self._samples: list[tuple[float, float]] = []
        self._flow_samples: list[tuple[float, float]] = []
        # Drawdown of the brew that just finished; derived at Stop, consumed by the
        # journal. 0 / False means "not measured", never "drained instantly".
        self._drawdown_s: int = 0
        self._drawdown_valid: bool = False
        # Provenance of the numbers in _samples, carried into the journal.
        # Reset with the curve: a manual entry must not leave its label on the next
        # brew the scale measures.
        self._measured_source: str = "scale"
        self._stop_marker: Optional[tuple[float, float]] = None
        self._last_w: Optional[float] = None
        # One "scale connected but silent" report per brew — see
        # _tick_update_inner.
        self._silent_scale_warned: bool = False
        self._elapsed = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._tick_update)
        # Delays the scale's stopwatch command past the tare burst — see
        # _start_brew. Owned by the dialog so it dies with it and can never fire
        # into a deleted widget.
        self._scale_timer_delay = QTimer(self)
        self._scale_timer_delay.setSingleShot(True)
        self._scale_timer_delay.timeout.connect(self._start_scale_timer_deferred)

        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._apply_palette()
        # Apply persisted prefs onto the live input BEFORE set_input so they survive.
        pref_method, pref_machine, pref_style = self._read_settings()
        if pref_method:
            self.service._method = pref_method
        if pref_machine is not None:
            inp.espresso_machine = pref_machine
        if pref_style is not None:
            inp.espresso_style = pref_style
        self._build_ui(inp)

        # Seed the input first: a dial-in is stored as an absolute grind/temp and
        # is resolved back into a correction against THIS bean's base recipe, so
        # the engine must already know the bean when _load_dialins runs.
        self.service.set_input(inp, emit=False)
        self._learn_setup_offsets()   # cross-bean, before per-bean
        self._load_dialins()          # before the first recompute
        self._reload_brewlog()        # file I/O once, at open — never in the render path
        # _load_dialins may have restored a dialled-in dose for the
        # method being opened; the spinbox was built on the method default.
        restored_dose = self.service.dialin_dose_for(self.service.method)
        if restored_dose:
            self.service.set_dose(restored_dose)
            self.spn_dose.blockSignals(True)
            self.spn_dose.setValue(int(round(restored_dose)))
            self.spn_dose.blockSignals(False)
        self.service.recipe_ready.connect(self._render)
        self._connect_ai()
        self._connect_scale_state()
        # Opening the advisor is intent to brew: start looking for the scale now
        # rather than waiting for the operator to ask for it.
        self._start_scale_search()
        self._sync_scale_ui()
        self.service.set_input(inp)
        self._building = False

    # ── AI availability ──
    def _ai_service(self):
        return getattr(self.aw, "tilau_ai_service", None)

    def _ai_cfg(self):
        # Read the live config so Settings changes are reflected without reopening.
        ai = getattr(self.aw, "tilau_aiConfig", None)
        if ai is None:
            svc = self._ai_service()
            ai = getattr(svc, "ai_config", None) if svc else None
        return ai

    def _ai_ready(self) -> bool:
        svc = self._ai_service()
        ai = self._ai_cfg()
        try:
            return (bool(svc) and ai is not None
                    and bool(getattr(ai, "engine", None))
                    and bool(getattr(ai, "apikey", None)))
        except Exception:  # noqa: BLE001
            return False

    def _connect_ai(self) -> None:
        svc = self._ai_service()
        if not svc:
            return
        svc.task_finished.connect(self._on_ai_finished)
        svc.task_error.connect(self._on_ai_error)
        svc.task_busy.connect(self._on_ai_busy)

    def _disconnect_ai(self) -> None:
        svc = self._ai_service()
        if not svc:
            return
        for sig, slot in ((svc.task_finished, self._on_ai_finished),
                          (svc.task_error, self._on_ai_error),
                          (svc.task_busy, self._on_ai_busy)):
            try:
                sig.disconnect(slot)
            except Exception:  # noqa: BLE001
                pass

    # ── styling ──
    def _apply_palette(self) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.WindowText, QColor(THEME["TEXT"]))
        pal.setColor(QPalette.ColorRole.Base, QColor(THEME["SURFACE"]))
        pal.setColor(QPalette.ColorRole.Text, QColor(THEME["TEXT"]))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(THEME["TEXT"]))
        self.setPalette(pal)

    def _qss(self) -> str:
        return f"""
            QLabel {{ color: {THEME['TEXT']}; background: transparent; }}
            QComboBox, QSpinBox {{
                background-color: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 6px;
                padding: 4px 8px; min-height: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {THEME['SURFACE']}; color: {THEME['TEXT']};
                selection-background-color: {THEME['ACCENT']}; selection-color: {THEME['BG']};
            }}
            QPushButton {{
                background-color: {THEME['ACCENT']}; color: {THEME['BG']};
                border: none; border-radius: 6px; padding: 6px 16px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {THEME['LAVENDER']}; }}
            QPushButton:disabled {{ background-color: {THEME['SURFACE']}; color: {THEME['SUBTEXT']}; }}
            /* Tooltips are top-level windows painted by the platform
               style, so without an explicit rule they came out as a native
               yellow box in the middle of a Catppuccin panel — most visibly on
               "Searching for the scale…", whose tooltip carries the only
               instruction the operator gets. */
            QToolTip {{
                background-color: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 6px;
                padding: 6px 8px; font-size: 12px;
            }}
        """

    # ── layout ──
    def _build_ui(self, inp: BrewInput) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("brewRoot")
        self.container.setStyleSheet(
            f"#brewRoot {{ background-color: {THEME['BG']}; border: 2px solid {THEME['ACCENT']};"
            f" border-radius: 16px; }}" + self._qss())
        outer.addWidget(self.container)

        root = QVBoxLayout(self.container)
        root.setContentsMargins(18, 12, 18, 16)
        root.setSpacing(12)

        # custom title bar (drag handle + close)
        bar = QHBoxLayout()
        self.lbl_title = QLabel(f"☕ {QApplication.translate("tilauscope_brew", 'Barista Expert — Brew Advisor')}")
        self.lbl_title.setStyleSheet(f"font-size:15px;font-weight:bold;color:{THEME['ACCENT']};")
        btn_x = QPushButton("✕")
        btn_x.setFixedSize(26, 26)
        btn_x.setProperty('variant', 'icon')   # fixed size: no base padding
        btn_x.setStyleSheet(
            f"QPushButton {{ background:{THEME['BORDER']}; color:{THEME['TEXT']};"
            f" border-radius:13px; font-size:14px; font-weight:bold; }}"
            f" QPushButton:hover {{ background:{THEME['CRITICAL']}; color:{THEME['BG']}; }}")
        btn_x.clicked.connect(self.accept)
        bar.addWidget(self.lbl_title)
        bar.addStretch(1)
        bar.addWidget(btn_x)
        root.addLayout(bar)

        agt = inp.ground_color if inp.ground_color > 0 else inp.whole_color
        rest = inp.days_off_roast if inp.days_off_roast >= 0 else "N/A"
        self.lbl_head = QLabel(
            f"<span style='color:{THEME['SUBTEXT']};font-size:12px;'>{self._title} · "
            f"{QApplication.translate("tilauscope_brew", 'Color')}: {agt} {inp.color_system} · {QApplication.translate("tilauscope_brew", 'WL')}: {inp.weight_loss:.1f}% · "
            f"{QApplication.translate("tilauscope_brew", 'Rest')}: {rest} d</span>")
        self.lbl_head.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.lbl_head)

        # ── controls (full width: they drive both columns) ──
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.cmb_method = QComboBox()
        for mid in METHOD_ORDER:
            self.cmb_method.addItem(_method_label(mid), mid)
        i = self.cmb_method.findData(self.service.method)
        if i >= 0:
            self.cmb_method.setCurrentIndex(i)
        self.cmb_method.currentIndexChanged.connect(self._on_method)

        self.spn_dose = _StepSpinBox()
        self.spn_dose.setRange(8, 60)
        self.spn_dose.setSuffix(" g")
        self.spn_dose.setValue(BrewAdvisor.default_dose(self.service.method))
        self.spn_dose.valueChanged.connect(self._on_dose)

        self.cmb_water = QComboBox()
        for wp, lbl in _WATER_ITEMS:
            self.cmb_water.addItem(QApplication.translate("tilauscope_brew", lbl), wp)
        self.cmb_water.currentIndexChanged.connect(self._on_water)

        self.lbl_machine = QLabel(QApplication.translate("tilauscope_brew", "Machine"))
        self.cmb_machine = QComboBox()
        for mc in ESPRESSO_MACHINE_ORDER:
            self.cmb_machine.addItem(_machine_label(mc), mc)
        j = self.cmb_machine.findData(inp.espresso_machine)
        if j >= 0:
            self.cmb_machine.setCurrentIndex(j)
        self.cmb_machine.currentIndexChanged.connect(self._on_machine)

        self.lbl_style = QLabel(QApplication.translate("tilauscope_brew", "Style"))
        self.cmb_style = QComboBox()
        for stl in ESPRESSO_STYLE_ORDER:
            self.cmb_style.addItem(_style_label(stl), stl)
        k = self.cmb_style.findData(inp.espresso_style)
        if k >= 0:
            self.cmb_style.setCurrentIndex(k)
        self.cmb_style.setToolTip(QApplication.translate(
            "tilauscope_brew",
            "Classic long: keeps the grind the roast asks for and lets the shot run as "
            "long as the ratio needs.\nTurbo: fixes the shot around 25 s and opens the "
            "grind to get the flow — the roast is then expressed by the ratio alone."))
        self.cmb_style.currentIndexChanged.connect(self._on_style)

        ctrl.addWidget(QLabel(QApplication.translate("tilauscope_brew", "Method")))
        ctrl.addWidget(self.cmb_method, 3)
        ctrl.addWidget(QLabel(QApplication.translate("tilauscope_brew", "Dose")))
        ctrl.addWidget(self.spn_dose, 1)
        ctrl.addWidget(QLabel(QApplication.translate("tilauscope_brew", "Water")))
        ctrl.addWidget(self.cmb_water, 2)
        ctrl.addWidget(self.lbl_machine)
        ctrl.addWidget(self.cmb_machine, 3)
        ctrl.addWidget(self.lbl_style)
        ctrl.addWidget(self.cmb_style, 2)
        root.addLayout(ctrl)
        # Kept so the minimum width can be measured from the row
        # itself rather than hardcoded — see setMinimumSize below.
        self._ctrl_row = ctrl

        # ── KPI strip: the numbers the barista actually acts on ──
        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(8)
        self.kpis: dict[str, _KpiTile] = {}
        for key, cap in (
            ("dose",  QApplication.translate("tilauscope_brew", "Dose")),
            ("water", QApplication.translate("tilauscope_brew", "Water")),
            ("ratio", QApplication.translate("tilauscope_brew", "Ratio")),
            ("temp",  QApplication.translate("tilauscope_brew", "Temp")),
            ("grind", QApplication.translate("tilauscope_brew", "Grind")),
            ("time",  QApplication.translate("tilauscope_brew", "Time")),
        ):
            tile = _KpiTile(cap)
            self.kpis[key] = tile
            self.kpi_row.addWidget(tile, 1)
        root.addLayout(self.kpi_row)

        # ── secondary context chips ──
        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        root.addLayout(self.chip_row)

        # body: two columns
        body = QHBoxLayout()
        body.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(8)

        lbl_proto = QLabel(QApplication.translate("tilauscope_brew", "PROTOCOL"))
        lbl_proto.setProperty('variant', 'eyebrow')
        left.addWidget(lbl_proto)

        self.steps_host = QWidget()
        self.steps_lay = QVBoxLayout(self.steps_host)
        self.steps_lay.setContentsMargins(0, 0, 0, 0)
        self.steps_lay.setSpacing(2)
        self.steps_lay.addStretch(1)
        steps_scroll = QScrollArea()
        steps_scroll.setWidgetResizable(True)
        steps_scroll.setWidget(self.steps_host)
        steps_scroll.setFrameShape(QFrame.Shape.NoFrame)
        steps_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                                   " QWidget { background: transparent; }")
        steps_scroll.setMinimumWidth(400)
        left.addWidget(steps_scroll, 1)

        # ── taste feedback ──
        # Always available, not gated behind a live brew: you do not need a
        # scale to have an opinion on a recipe. It simply diagnoses more
        # precisely when a brew time was measured.
        _taste_hdr = QLabel(QApplication.translate("tilauscope_brew", "HOW DOES IT TASTE?"))
        _taste_hdr.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:11px;letter-spacing:1.5px;"
            f"font-weight:bold;padding-top:6px;")
        left.addWidget(_taste_hdr)
        self.lbl_taste_prompt = QLabel(
            QApplication.translate("tilauscope_brew", "Tell the advisor and it will adjust the recipe."))
        self.lbl_taste_prompt.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:12px;"
            f"font-weight:bold;padding-top:4px;")
        left.addWidget(self.lbl_taste_prompt)

        taste_row = QHBoxLayout()
        taste_row.setSpacing(4)
        self.taste_btns: dict[TasteCode, QPushButton] = {}
        for code, label in (
            (TasteCode.SOUR,     QApplication.translate("tilauscope_brew", "Sour")),
            (TasteCode.BITTER,   QApplication.translate("tilauscope_brew", "Bitter")),
            (TasteCode.HARSH,    QApplication.translate("tilauscope_brew", "Harsh")),
            (TasteCode.THIN,     QApplication.translate("tilauscope_brew", "Thin")),
            (TasteCode.BALANCED, QApplication.translate("tilauscope_brew", "✓ Balanced")),
        ):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            on = THEME["SUCCESS"] if code == TasteCode.BALANCED else THEME["ACCENT"]
            b.setStyleSheet(
                f"QPushButton {{ background:{THEME['SURFACE']}; color:{THEME['SUBTEXT']};"
                f" border:1px solid {THEME['BORDER']}; border-radius:9px;"
                f" padding:3px 9px; font-size:12px; }}"
                f" QPushButton:hover {{ color:{THEME['TEXT']}; }}"
                f" QPushButton:checked {{ background:{on}; color:{THEME['BG']};"
                f" border:1px solid {on}; font-weight:bold; }}")
            b.clicked.connect(lambda _c, tc=code: self._on_taste_clicked(tc))
            self.taste_btns[code] = b
            taste_row.addWidget(b)
        taste_row.addStretch(1)
        left.addLayout(taste_row)

        # verdict + bounded correction, shown once a taste is reported
        self.lbl_verdict = QLabel("")
        self.lbl_verdict.setWordWrap(True)
        self.lbl_verdict.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_verdict.setStyleSheet(
            "font-size:12px;padding-top:4px;")
        self.lbl_verdict.setVisible(False)
        left.addWidget(self.lbl_verdict)

        apply_row = QHBoxLayout()
        apply_row.setSpacing(6)
        self.btn_apply_fix = QPushButton(
            QApplication.translate("tilauscope_brew", "Apply to next brew"))
        # The panel's primary action; hover/pressed states come from the base
        # sheet's primary variant.
        self.btn_apply_fix.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_fix.setProperty('variant', 'primary')
        self.btn_apply_fix.clicked.connect(self._apply_taste_correction)
        self.btn_apply_fix.setVisible(False)
        apply_row.addWidget(self.btn_apply_fix)
        apply_row.addStretch(1)
        left.addLayout(apply_row)
        # Full width and on its own row, not beside the button: the
        # confirmation now names the bean and restates both numbers, which does
        # not fit next to a button and must not be read as a caption of it.
        self.lbl_fix_done = QLabel("")
        self.lbl_fix_done.setWordWrap(True)
        self.lbl_fix_done.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_fix_done.setStyleSheet(
            "font-size:12px;padding-top:2px;")
        self.lbl_fix_done.setVisible(False)
        left.addWidget(self.lbl_fix_done)
        self.diagnostics = _DiagnosticsBox()
        left.addWidget(self.diagnostics)

        body.addLayout(left, 3)

        # right column: live extraction (Acaia)
        # The readouts scroll, the brew controls do not. This column's height is
        # content-driven (the debrief grows with the diagnosis text), so a fixed
        # pixel budget cannot hold — Qt overlaps rather than clips when a column
        # is short. Scrolling degrades gracefully; the Start/Stop button stays
        # pinned below so it can never scroll out of reach mid-brew.
        self.right = QFrame()
        self.right.setMinimumWidth(300)
        self.right.setStyleSheet(
            f"QFrame {{ background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};"
            f" border-radius:10px; }} QLabel {{ border:none; }}")
        right_outer = QVBoxLayout(self.right)
        right_outer.setContentsMargins(14, 14, 14, 14)
        right_outer.setSpacing(8)

        self._right_scroll = QScrollArea()
        self._right_scroll.setWidgetResizable(True)
        self._right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._right_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        _right_content = QWidget()
        self._right_scroll.setWidget(_right_content)
        right_outer.addWidget(self._right_scroll, 1)
        rl = QVBoxLayout(_right_content)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        head = QHBoxLayout()
        rtitle = QLabel(QApplication.translate("tilauscope_brew", "Live extraction"))
        rtitle.setStyleSheet(f"font-weight:bold;color:{THEME['ACCENT']};border:none;")
        # on-plan / ahead / behind, read off the corridor
        self.lbl_pace = QLabel("")
        self.lbl_pace.setVisible(False)
        head.addWidget(rtitle)
        head.addStretch(1)
        head.addWidget(self.lbl_pace)
        rl.addLayout(head)

        self.lbl_brew_target = QLabel("—")
        self.lbl_brew_target.setProperty('variant', 'secondary')
        rl.addWidget(self.lbl_brew_target)

        stat = QHBoxLayout()
        self.lbl_brew_time = QLabel("0:00")
        self.lbl_brew_time.setProperty('variant', 'readout')
        self.lbl_brew_time.setStyleSheet(f"color: {THEME['TEXT']};")
        self.lbl_brew_weight = QLabel("–– g")
        self.lbl_brew_weight.setProperty('variant', 'readout')
        self.lbl_brew_weight.setStyleSheet(f"color: {THEME['ACCENT']};")
        stat.addWidget(self.lbl_brew_time)
        stat.addStretch(1)
        stat.addWidget(self.lbl_brew_weight)
        rl.addLayout(stat)

        self.bar_target = _TargetBar()
        rl.addWidget(self.bar_target)

        sub_row = QHBoxLayout()
        self.lbl_brew_flow = QLabel(QApplication.translate("tilauscope_brew", "Flow: –– g/s"))
        self.lbl_brew_flow.setProperty('variant', 'secondary')
        self.lbl_brew_pct = QLabel("")
        self.lbl_brew_pct.setStyleSheet(f"color:{THEME['SUBTEXT']};border:none;")
        sub_row.addWidget(self.lbl_brew_flow)
        sub_row.addStretch(1)
        sub_row.addWidget(self.lbl_brew_pct)
        rl.addLayout(sub_row)

        self.spark = _ExtractionChart()
        rl.addWidget(self.spark, 1)

        # Manual result entry, for espresso machines whose scale is built
        # into the drip tray: no cup fits over an Acaia on a Linea Mini, so the
        # whole feedback loop (debrief, time-aware diagnosis, journal, previous
        # attempt) was unreachable there. This writes the same two numbers the
        # scale produces into _samples and lets every downstream path run
        # unchanged — a second measurement path would drift from the first.
        # Espresso only: elsewhere the total time is the operator's pour schedule,
        # not the coffee bed, and a typed number there would mean nothing.
        self.manual_card = QFrame()
        self.manual_card.setVisible(False)
        self.manual_card.setStyleSheet(
            f"QFrame {{ background:{THEME['BG']}; border:1px solid {THEME['ACCENT']};"
            f" border-radius:8px; }} QLabel {{ border:none; }}")
        ml = QVBoxLayout(self.manual_card)
        ml.setContentsMargins(12, 9, 12, 9)
        ml.setSpacing(6)
        lbl_manual_title = QLabel(QApplication.translate("tilauscope_brew", "SHOT RESULT"))
        lbl_manual_title.setProperty('variant', 'eyebrow')
        lbl_manual_title.setStyleSheet(f"color: {THEME['ACCENT']};")
        ml.addWidget(lbl_manual_title)

        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        lbl_mt = QLabel(QApplication.translate("tilauscope_brew", "Shot time"))
        lbl_mt.setProperty('variant', 'caption')
        self.spn_manual_time = QSpinBox()
        self.spn_manual_time.setRange(1, 120)
        self.spn_manual_time.setSuffix(" s")
        lbl_my = QLabel(QApplication.translate("tilauscope_brew", "In the cup"))
        lbl_my.setProperty('variant', 'caption')
        self.spn_manual_yield = QDoubleSpinBox()
        self.spn_manual_yield.setRange(1.0, 200.0)
        self.spn_manual_yield.setDecimals(1)
        self.spn_manual_yield.setSingleStep(0.5)
        self.spn_manual_yield.setSuffix(" g")
        for w in (self.spn_manual_time, self.spn_manual_yield):
            w.setStyleSheet(
                f"QAbstractSpinBox {{ background:{THEME['SURFACE']}; color:{THEME['TEXT']};"
                f" border:1px solid {THEME['BORDER']}; border-radius:6px; padding:4px 6px;"
                f" }}")
        mrow.addWidget(lbl_mt)
        mrow.addWidget(self.spn_manual_time, 1)
        mrow.addSpacing(6)
        mrow.addWidget(lbl_my)
        mrow.addWidget(self.spn_manual_yield, 1)
        ml.addLayout(mrow)

        self.lbl_manual_target = QLabel("")
        self.lbl_manual_target.setProperty('variant', 'caption')
        ml.addWidget(self.lbl_manual_target)

        mbtn = QHBoxLayout()
        mbtn.setSpacing(8)
        self.btn_manual_cancel = QPushButton(QApplication.translate("tilauscope_brew", "Cancel"))
        self.btn_manual_cancel.clicked.connect(self._close_manual_entry)
        self.btn_manual_cancel.setStyleSheet(
            f"QPushButton {{ background:{THEME['SURFACE']}; color:{THEME['SUBTEXT']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:6px; padding:5px 12px; }}")
        self.btn_manual_save = QPushButton(QApplication.translate("tilauscope_brew", "Record"))
        self.btn_manual_save.clicked.connect(self._record_manual_result)
        self.btn_manual_save.setProperty('variant', 'primary')
        mbtn.addStretch(1)
        mbtn.addWidget(self.btn_manual_cancel)
        mbtn.addWidget(self.btn_manual_save)
        ml.addLayout(mbtn)
        rl.addWidget(self.manual_card)

        # post-brew debrief, shown in place of the chart once the brew stops
        self.debrief = QFrame()
        self.debrief.setVisible(False)
        self.debrief.setStyleSheet(
            f"QFrame {{ background:{THEME['BG']}; border:1px solid {THEME['BORDER']};"
            f" border-radius:8px; }} QLabel {{ border:none; }}")
        dl = QVBoxLayout(self.debrief)
        dl.setContentsMargins(12, 7, 12, 7)
        dl.setSpacing(2)
        self.lbl_debrief_title = QLabel(QApplication.translate("tilauscope_brew", "BREW COMPLETE"))
        self.lbl_debrief_title.setProperty('variant', 'eyebrow')
        self.lbl_debrief_title.setStyleSheet(f"color: {THEME['SUCCESS']};")
        self.lbl_debrief_spec = QLabel("")
        self.lbl_debrief_spec.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:13px;font-weight:bold;")
        self.lbl_debrief_delta = QLabel("")
        self.lbl_debrief_delta.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_debrief_delta.setStyleSheet("font-size:11px;")
        self.lbl_debrief_coach = QLabel("")
        self.lbl_debrief_coach.setWordWrap(True)
        self.lbl_debrief_coach.setProperty('variant', 'caption')
        dl.addWidget(self.lbl_debrief_title)
        dl.addWidget(self.lbl_debrief_spec)
        dl.addWidget(self.lbl_debrief_delta)
        dl.addWidget(self.lbl_debrief_coach)

        rl.addWidget(self.debrief)

        # "Did my last change actually do anything?" — read from the brew
        # journal, never from the live brew. A sibling of the debrief rather than a
        # part of it: the debrief describes the cup you just poured, this describes
        # the SETTING you changed before it, and it is worth seeing when you open
        # the advisor to brew again, not only after serving.
        self.prev_try = QFrame()
        self.prev_try.setVisible(False)
        self.prev_try.setStyleSheet(
            f"QFrame {{ background:{THEME['BG']}; border:1px solid {THEME['BORDER']};"
            f" border-radius:8px; }} QLabel {{ border:none; }}")
        pl = QVBoxLayout(self.prev_try)
        pl.setContentsMargins(12, 7, 12, 7)
        pl.setSpacing(2)
        self.lbl_prev_title = QLabel("")
        self.lbl_prev_title.setProperty('variant', 'eyebrow')
        self.lbl_prev_change = QLabel("")
        self.lbl_prev_change.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:13px;font-weight:bold;")
        self.lbl_prev_signal = QLabel("")
        self.lbl_prev_signal.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_prev_signal.setStyleSheet("font-size:11px;")
        self.lbl_prev_verdict = QLabel("")
        self.lbl_prev_verdict.setWordWrap(True)
        self.lbl_prev_verdict.setProperty('variant', 'caption')
        self.lbl_prev_causes = QLabel("")
        self.lbl_prev_causes.setWordWrap(True)
        self.lbl_prev_causes.setVisible(False)
        self.lbl_prev_causes.setProperty('variant', 'caption')
        for w in (self.lbl_prev_title, self.lbl_prev_change, self.lbl_prev_signal,
                  self.lbl_prev_verdict, self.lbl_prev_causes):
            pl.addWidget(w)
        rl.addWidget(self.prev_try)

        brew_row = QHBoxLayout()
        self.btn_brew = QPushButton(QApplication.translate("tilauscope_brew", "▶ Start brew"))
        self.btn_brew.clicked.connect(self._toggle_brew)
        self.btn_autostop = QPushButton(QApplication.translate("tilauscope_brew", "Auto-stop"))
        self.btn_autostop.setCheckable(True)
        # On by default: a shot ends at its yield, and no hand is as
        # quick as the scale. Espresso is the only method where it is offered.
        self.btn_autostop.setChecked(True)
        self.btn_autostop.setToolTip(QApplication.translate("tilauscope_brew", "Stop the shot on its own when the cup reaches the target yield."))
        self.btn_autostop.setStyleSheet(
            f"QPushButton {{ background:{THEME['SURFACE']}; color:{THEME['SUBTEXT']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:6px; padding:6px 10px; }}"
            f" QPushButton:checked {{ background:{THEME['ACCENT']}; color:{THEME['BG']};"
            f" border:1px solid {THEME['ACCENT']}; font-weight:bold; }}")
        # Shown in place of the controls while no scale is on the line.
        self.lbl_scale_status = QLabel("")
        self.lbl_scale_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_scale_status.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:11px;"
            f"background:transparent;border:1px dashed {THEME['BORDER']};"
            f"border-radius:6px;padding:6px 10px;")
        # The way in when no scale can be put under the cup. Sits beside
        # the status rather than replacing it: the scale may still turn up, and
        # the operator should keep seeing that it is being looked for.
        self.btn_manual = QPushButton(QApplication.translate("tilauscope_brew", "✎ Enter manually"))
        self.btn_manual.setVisible(False)
        self.btn_manual.clicked.connect(self._open_manual_entry)
        self.btn_manual.setToolTip(QApplication.translate(
            "tilauscope_brew",
            "Type the shot time and the weight in the cup, for machines whose "
            "scale is built in and leaves no room for an Acaia."))
        self.btn_manual.setStyleSheet(
            f"QPushButton {{ background:{THEME['SURFACE']}; color:{THEME['TEXT']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:6px; padding:6px 10px; }}"
            f" QPushButton:hover {{ border:1px solid {THEME['ACCENT']}; }}")
        brew_row.addWidget(self.btn_brew, 2)
        brew_row.addWidget(self.btn_autostop, 1)
        brew_row.addWidget(self.lbl_scale_status, 3)
        brew_row.addWidget(self.btn_manual, 2)
        right_outer.addLayout(brew_row)   # pinned: never scrolls away
        self._sync_scale_ui()

        body.addWidget(self.right, 2)

        root.addLayout(body, 1)

        # bottom action row: AI refine (opt-in) + Close
        btn_row = QHBoxLayout()
        self.btn_ai = QPushButton(QApplication.translate("tilauscope_brew", "✦ Refine (AI)"))
        self.btn_ai.clicked.connect(self._run_ai)
        if not self._ai_ready():
            self.btn_ai.setEnabled(False)
            self.btn_ai.setToolTip(QApplication.translate("tilauscope_brew", "Configure an AI engine in the settings to enable refinement."))
        # 50×30 Niimbot label (dial-in recipe) — direct print, in-window status.
        self.btn_print = QPushButton("🖨  " + QApplication.translate("tilauscope_brew", "50×30 label"))
        self.btn_print.clicked.connect(self._print_label)
        self._print_pill = None   # host A — pastille de progression d'impression
        if not self._can_print_label():
            self.btn_print.setEnabled(False)
            self.btn_print.setToolTip(QApplication.translate(
                "tilauscope_brew",
                "Connect the Niimbot B21S in BeanCave to print a 50×30 recipe label."))

        btn_close = QPushButton(QApplication.translate("tilauscope_brew", "Close"))
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_ai)
        btn_row.addWidget(self.btn_print)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        # Height budgeted so the debrief AND an expanded taste verdict fit under
        # the chart without scrolling in the common case; the right column
        # scrolls as a safety net when a diagnosis runs long.
        # The minimum width is measured, not guessed. The control row
        # needs ~1090 px once the espresso machine and style selectors are in,
        # against a hardcoded 980 — and Qt OVERLAPS widgets rather than clipping
        # them when a row cannot meet its minimum, so the fields silently piled
        # up on top of each other. Asking the layout means macOS's wider system
        # fonts are accounted for on the real machine, and adding a control
        # later cannot quietly break it again.
        # Measured HERE, before _update_machine_visibility() hides the espresso
        # selectors: a hidden widget contributes nothing to a layout's size hint,
        # so measuring after would give a width too small for espresso.
        need_w = self._ctrl_row.sizeHint().width() + 18 + 18 + 8   # + root margins
        self.setMinimumSize(max(980, need_w), 760)
        self._update_machine_visibility()

    # ── control slots ──
    def _update_machine_visibility(self) -> None:
        is_es = self.service.method == "ESPRESSO"
        self.lbl_machine.setVisible(is_es)
        self.cmb_machine.setVisible(is_es)
        self.lbl_style.setVisible(is_es)
        self.cmb_style.setVisible(is_es)

    @pyqtSlot(int)
    def _on_method(self, _i: int) -> None:
        if self._building:
            return
        mid = self.cmb_method.currentData()
        self.service.set_method(mid)
        self.spn_dose.blockSignals(True)
        self.spn_dose.setValue(int(round(
            self.service.dose_for_method(mid) or BrewAdvisor.default_dose(mid))))
        self.spn_dose.blockSignals(False)
        self._update_machine_visibility()
        # Auto-stop is espresso-only, so its visibility follows the method.
        self._sync_scale_ui()
        self._save_settings()

    @pyqtSlot(int)
    def _on_dose(self, v: int) -> None:
        if not self._building:
            self.service.set_dose(float(v))

    @pyqtSlot(int)
    def _on_water(self, _i: int) -> None:
        if not self._building:
            self.service.set_water(self.cmb_water.currentData())

    @pyqtSlot(int)
    def _on_machine(self, _i: int) -> None:
        if self._building:
            return
        self.service.set_espresso_machine(self.cmb_machine.currentData())
        self._save_settings()

    @pyqtSlot(int)
    def _on_style(self, _i: int) -> None:
        if self._building:
            return
        self.service.set_espresso_style(self.cmb_style.currentData())
        self._save_settings()

    # ── persistence (method + espresso machine + espresso style) ──
    def _read_settings(self) -> tuple[Optional[str], Optional[EspressoMachine],
                                      Optional[EspressoStyle]]:
        method: Optional[str] = None
        machine: Optional[EspressoMachine] = None
        style: Optional[EspressoStyle] = None
        try:
            from PyQt6.QtCore import QSettings
            s = QSettings()
            m = s.value("tilauscope/brew/method", "", str)
            if m in METHOD_ORDER:
                method = m
            mc = s.value("tilauscope/brew/espresso_machine", "", str)
            for em in EspressoMachine:
                if em.value == mc:
                    machine = em
                    break
            sv = s.value("tilauscope/brew/espresso_style", "", str)
            for es in EspressoStyle:
                if es.value == sv:
                    style = es
                    break
        except Exception:  # noqa: BLE001
            pass
        return method, machine, style

    def _save_settings(self) -> None:
        try:
            from PyQt6.QtCore import QSettings
            s = QSettings()
            s.setValue("tilauscope/brew/method", self.service.method)
            s.setValue("tilauscope/brew/espresso_machine", self.service.input.espresso_machine.value)
            s.setValue("tilauscope/brew/espresso_style", self.service.input.espresso_style.value)
        except Exception:  # noqa: BLE001
            pass

    # ── temperature / time formatting ──
    def _fmt_temp(self, t_c: float) -> str:
        # Whole degrees only: per [S1] brew temperature is a coarse lever, sub-
        # degree precision would be misleading.
        return f"{t_c:.0f} °C" if self._mode == "C" else f"{fromCtoFstrict(t_c):.0f} °F"

    @staticmethod
    def _fmt_time(s: int) -> str:
        return f"{s // 60}:{s % 60:02d}"

    # ── AI pass ──
    def _run_ai(self) -> None:
        if self._ai_busy or not self._ai_ready() or not self.service.last:
            return
        svc = self._ai_service()
        cfg = self._ai_cfg()
        rec = self.service.last
        inp = self.service.input
        lang = QLocale.system().name().split("_")[0]

        agtron_str = f"{rec.agtron}" if rec.agtron > 0 else "N/A"
        ctx = (
            f"method={rec.method_id} roast={rec.roast_key} agtron={agtron_str} "
            f"ratio={rec.ratio_str} temp_c={rec.temp_c} grind_um={rec.grind_um} dose_g={rec.dose_g} "
            # Style and total time are part of what the recipe now IS:
            # the same roast pulled classic or turbo is a different drink, and
            # without the time the model cannot see the flow it implies.
            f"total_time_s={rec.total_time_s} "
            f"machine={inp.espresso_machine.value} style={inp.espresso_style.value} "
            f"bean: origin={inp.country} process={inp.process} variety={inp.variety} "
            f"density={inp.density} weight_loss={inp.weight_loss} days_off_roast={inp.days_off_roast}"
        )
        system_prompt = (
            "You are an extraction-focused coffee specialist grounded in peer-reviewed "
            "brewing science, NOT in barista folklore. You receive an already-computed brew "
            "recipe and may propose SMALL refinements only. Reason from the levers that "
            "actually control the cup: grind, contact time and ratio set total dissolved "
            "solids (TDS) and extraction yield (EY); at a fixed TDS/EY, brew temperature has "
            "little sensory impact, so prefer grind/ratio over temperature changes. For water, "
            "reason on GH (Ca/Mg, raises extraction) and KH (bicarbonate, buffers/mutes acidity) "
            "separately. Do NOT make claims unsupported by evidence: process (washed/natural) "
            "and variety do not have generalizable grind/temperature rules, and oxidative "
            "staling cannot be 'recovered' by brewing tweaks. Respond with a COMPACT JSON object "
            "and nothing else (no markdown, no prose). Schema: {\"temp_delta_c\": number (-2..2), "
            "\"grind_pct\": number (-10..10), \"ratio_delta\": number (-1..1), "
            "\"tips\": array of at most 2 short strings}. Use 0 / empty when no change is warranted. "
            f"Write tips in language code '{lang}'."
        )
        user_content = f"Recipe context:\n{ctx}\nReturn the JSON adjustments now."

        _engine = normalize_engine(cfg.engine)
        model = _engine.split("/", 1)[1] if "/" in _engine else _engine
        base = provider_base_url(_engine)
        thinking = get_suppress_thinking_params(_engine)
        api_key = cfg.apikey
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}]

        def _work(cancel, on_token: Callable[[str], None]) -> str:
            import time as _time  # noqa: PLC0415
            import httpx as _httpx  # noqa: PLC0415
            url = base.rstrip("/") + "/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body: dict = {"model": model, "messages": messages, "stream": True}
            if thinking:
                body.update(thinking)
            transient = {429, 500, 502, 503, 504}
            last_err = "AI request failed"
            for attempt in range(3):
                if cancel.is_cancelled:
                    break
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0)) as http:
                        with http.stream("POST", url, headers=headers, content=json.dumps(body)) as resp:
                            if resp.status_code in transient:
                                last_err = f"HTTP {resp.status_code}"
                                _time.sleep(1.5 * (attempt + 1))  # backoff, model overloaded
                                continue
                            if resp.status_code != 200:
                                raise RuntimeError(f"HTTP {resp.status_code}")
                            out = ""
                            for raw in resp.iter_lines():
                                if cancel.is_cancelled:
                                    break
                                line = raw.strip()
                                if not line or line == "data: [DONE]":
                                    continue
                                if line.startswith("data: "):
                                    line = line[6:]
                                try:
                                    chunk = json.loads(line)
                                    delta = chunk["choices"][0]["delta"]
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                                if delta.get("reasoning_content"):
                                    continue
                                out += delta.get("content") or ""
                            return out
                except _httpx.RequestError as exc:
                    last_err = str(exc)
                    _time.sleep(1.0 * (attempt + 1))
            raise RuntimeError(last_err)

        if svc.submit(_BREW_TASK, _work):
            self._ai_busy = True
            if self.btn_ai:
                self.btn_ai.setEnabled(False)
                self.btn_ai.setText(QApplication.translate("tilauscope_brew", "✦ Refining…"))

    @staticmethod
    def _parse_ai_json(text: str) -> Optional[dict]:
        if not text:
            return None
        t = _re.sub(r"```(?:json)?|```", "", text).strip()
        m = _re.search(r"\{.*\}", t, _re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    @pyqtSlot(str, object)
    def _on_ai_finished(self, task_type: str, result: object) -> None:
        if task_type != _BREW_TASK:
            return
        self._reset_ai_button()
        data = self._parse_ai_json(result if isinstance(result, str) else "")
        if data is None:
            return  # AI returned nothing usable → ignore, keep base recipe
        if self._brew_running:
            # Landed after Start (request was in flight): re-planning a pour that
            # is already running is meaningless, and the panel is frozen anyway.
            _log.info("Brew: AI refinement discarded, a brew is in progress")
            return
        self.service.apply_ai(data)

    @pyqtSlot(str, str)
    def _on_ai_error(self, task_type: str, _msg: str) -> None:
        if task_type == _BREW_TASK:
            self._reset_ai_button()  # silently ignore the error

    @pyqtSlot(str)
    def _on_ai_busy(self, task_type: str) -> None:
        if task_type == _BREW_TASK:
            self._reset_ai_button()

    def _reset_ai_button(self) -> None:
        self._ai_busy = False
        if self.btn_ai:
            self.btn_ai.setEnabled(True)
            self.btn_ai.setText(QApplication.translate("tilauscope_brew", "✦ Refine (AI)"))

    # ── Niimbot 50×30 label (delegated to the BeanCave host printer) ──
    def _niimbot(self):
        return getattr(self._beancave, "np", None) if self._beancave is not None else None

    def _can_print_label(self) -> bool:
        try:
            return bool(self._beancave is not None
                        and getattr(self._beancave, "_niimbot_connected", False)
                        and self._niimbot() is not None)
        except Exception:  # noqa: BLE001
            return False

    def _grain_line(self, rec) -> str:
        """« Process · Agtron NN · Roast level » — segments omitted when absent."""
        from tilauscope.label_printer import normalise_process  # noqa: PLC0415
        inp = self.service.input
        parts: list[str] = []
        proc = normalise_process(inp.process) if getattr(inp, "process", "") else ""
        if proc and proc != "-":
            parts.append(proc)
        if getattr(rec, "agtron", 0) and rec.agtron > 0:
            csys = (getattr(inp, "color_system", "") or "Agtron").strip()
            parts.append(f"{csys} {rec.agtron:.0f}")
        lvl = _roast_label(rec.roast_key)
        if lvl:
            parts.append(lvl)
        return " · ".join(parts)

    def _print_label(self) -> None:
        rec = self.service.last
        np_ = self._niimbot()
        if rec is None or not self._can_print_label() or np_ is None:
            return
        if getattr(np_, "paper_height", 0) != 30:
            show_styled_message(
                self, QApplication.translate("tilauscope_brew", "Print"),
                QApplication.translate("tilauscope_brew",
                    "Brew labels need the 50×30 mm roll (detected: {0}×{1} mm).")
                    .format(getattr(np_, "paper_width", 0), getattr(np_, "paper_height", 0)),
                QMessageBox.Icon.Warning)
            return
        try:
            from tilauscope.label_printer import build_brew_recipe_label_image  # noqa: PLC0415
            method_label = _method_label(rec.method_id)
            grain = self._grain_line(rec)
            if rec.method_id == "ESPRESSO":
                water_lbl = (QApplication.translate("tilauscope_brew", "Yield")
                             if rec.water_is_yield else QApplication.translate("tilauscope_brew", "Water"))
                cells = [
                    (QApplication.translate("tilauscope_brew", "Dose"),  f"{rec.dose_g:.0f} g"),
                    (water_lbl,                                          f"{rec.water_g:.0f} g"),
                    (QApplication.translate("tilauscope_brew", "Ratio"), rec.ratio_str),
                    (QApplication.translate("tilauscope_brew", "Temp"),  self._fmt_temp(rec.temp_c)),
                    (QApplication.translate("tilauscope_brew", "Grind"), f"{rec.grind_um} µm"),
                    (QApplication.translate("tilauscope_brew", "Time"),  self._fmt_time(rec.total_time_s)),
                ]
                img = build_brew_recipe_label_image(
                    self._title, rec.method_id, method_label, grain, grid_cells=cells)
            else:
                spec = " · ".join([
                    f"{rec.dose_g:.0f} g", f"{rec.water_g:.0f} g", rec.ratio_str,
                    self._fmt_temp(rec.temp_c), f"{rec.grind_um} µm",
                ])
                steps = []
                for s in rec.steps:
                    tgt = f"{s.target_g:.0f} g" if getattr(s, "target_g", 0) and s.target_g > 0 else ""
                    steps.append((self._fmt_time(s.at_s), _step_text(s.label_key, s.params), tgt))
                img = build_brew_recipe_label_image(
                    self._title, rec.method_id, method_label, grain, spec_line=spec, steps=steps)
        except Exception as exc:  # noqa: BLE001
            _log.error("Brew label build failed: %s", exc)
            show_styled_message(
                self, QApplication.translate("tilauscope_brew", "Print"),
                QApplication.translate("tilauscope_brew",
                    "The label could not be built, so nothing was sent to the printer."),
                QMessageBox.Icon.Warning)
            return
        self.btn_print.setEnabled(False)
        # Progression dans la pastille flottante (host A), relevée au-dessus de
        # la rangée de boutons pour ne pas couvrir Close.
        self._print_pill = print_progress_pill(self.container, 1)
        self._print_pill.set_margin(20, 56)
        try:
            self._beancave.print_niimbot_image_async(img, self._on_print_ok, self._on_print_err)
        except Exception as exc:  # noqa: BLE001
            _log.error("Brew label print dispatch failed: %s", exc)
            self._on_print_err(str(exc))

    @pyqtSlot()
    def _on_print_ok(self) -> None:
        pill = self._print_pill
        self._print_pill = None
        if pill is not None:
            pill.succeed("🖨  " + QApplication.translate("tilauscope_brew", "Label printed"))
        if getattr(self, "btn_print", None) is not None:
            self.btn_print.setEnabled(self._can_print_label())

    @pyqtSlot(str)
    def _on_print_err(self, msg: str) -> None:
        pill = self._print_pill
        self._print_pill = None
        if pill is not None:
            pill.fail("🖨  " + (msg or QApplication.translate(
                "tilauscope_brew", "Printing failed — check the printer")))
        if getattr(self, "btn_print", None) is not None:
            self.btn_print.setEnabled(self._can_print_label())

    # ── live brew (Acaia via aw.scale_manager) ──
    def _scale_mgr(self):
        return getattr(self.aw, "scale_manager", None)

    def _scale_configured(self) -> bool:
        """A scale exists in the settings — it may well be off or out of range."""
        sm = self._scale_mgr()
        try:
            return bool(sm) and sm.is_scale1_configured()
        except Exception:  # noqa: BLE001
            return False

    def _scale_connected(self) -> bool:
        """A scale is actually on the line and can deliver weights."""
        sm = self._scale_mgr()
        try:
            return bool(sm) and sm.is_scale1_connected()
        except Exception:  # noqa: BLE001
            return False

    def _sync_scale_ui(self) -> None:
        """Brew controls appear only once a scale is really on the line.

        Artisan's BLE layer keeps scanning/reconnecting on its own, so a configured-but-offline scale shows a searching status, never a dead Start button.
        """
        auto = self._autostop_applies()
        if self._brew_running:
            self.btn_brew.setVisible(True)
            self.btn_brew.setEnabled(True)
            self.btn_brew.setText(QApplication.translate("tilauscope_brew", "■ Stop brew"))
            self.btn_autostop.setVisible(auto)
            self.btn_autostop.setEnabled(auto)
            self.lbl_scale_status.setVisible(False)
            self.btn_manual.setVisible(False)
            return
        configured, connected = self._scale_configured(), self._scale_connected()
        # Offered only where it means something: espresso (the scale
        # weighs what comes out) and only while no scale is on the line — with a
        # working Acaia, typing a number the scale already measured better is a
        # way to corrupt the journal, not to fill it.
        self.btn_manual.setVisible(auto and not connected)
        self.btn_brew.setText(QApplication.translate("tilauscope_brew", "▶ Start brew"))
        self.btn_brew.setEnabled(connected)
        self.btn_brew.setVisible(connected)
        self.btn_autostop.setVisible(connected and auto)
        self.btn_autostop.setEnabled(connected and auto)
        self.lbl_scale_status.setVisible(not connected)
        if connected:
            return
        if configured:
            self.lbl_scale_status.setText(
                QApplication.translate("tilauscope_brew", "⟳  Searching for the scale…"))
            self.lbl_scale_status.setToolTip(QApplication.translate(
                "tilauscope_brew",
                "Switch the scale on and it will connect by itself."))
        else:
            self.lbl_scale_status.setText(
                QApplication.translate("tilauscope_brew", "No scale configured"))
            self.lbl_scale_status.setToolTip(QApplication.translate(
                "tilauscope_brew",
                "Configure an Acaia scale in the settings to enable live brewing."))

    def _connect_scale_state(self) -> None:
        """Track the scale for the whole dialog lifetime, not just during a brew,
        so the controls never show a stale state."""
        sm = self._scale_mgr()
        if sm is None:
            return
        for name in ("scale1_connected_signal", "scale1_disconnected_signal"):
            sig = getattr(sm, name, None)
            try:
                if sig is not None:
                    sig.connect(self._on_scale_state)
            except Exception:  # noqa: BLE001
                pass

    def _disconnect_scale_state(self) -> None:
        sm = self._scale_mgr()
        if sm is None:
            return
        for name in ("scale1_connected_signal", "scale1_disconnected_signal"):
            sig = getattr(sm, name, None)
            try:
                if sig is not None:
                    sig.disconnect(self._on_scale_state)
            except Exception:  # noqa: BLE001
                pass

    @pyqtSlot()
    def _on_scale_state(self) -> None:
        self._sync_scale_ui()
        if self._brew_running and not self._scale_connected():
            # Losing the scale mid-brew must be said out loud: the timer would
            # otherwise keep running against a curve that stopped growing.
            self.lbl_pace.setText(QApplication.translate("tilauscope_brew", "● scale lost"))
            self.lbl_pace.setStyleSheet(
                f"color:{THEME['CRITICAL']};"
                f"font-size:11px;font-weight:bold;border:none;")
            self.lbl_pace.setVisible(True)

    def _start_scale_search(self) -> None:
        """Kick off Artisan's scan/reconnect loop once, then let it run.

        BLEPort.start() sets `_running` and loops on scan-and-connect until
        stopped, so this is fire-once: re-emitting would only make the BLE layer
        log 'client already running'.
        """
        sm = self._scale_mgr()
        if sm is None or self._search_started or not self._scale_configured():
            return
        if self._scale_connected():
            return  # already online — someone else owns it, leave it alone
        self._search_started = True
        self._we_connected_scale = True
        try:
            sm.connect_scale1_signal.emit(False)
        except Exception as exc:  # noqa: BLE001
            _log.warning("Brew: starting the scale search failed: %s", exc)
            self._search_started = False
            self._we_connected_scale = False

    def _brew_target(self) -> tuple[float, float]:
        rec = self._plan_rec()
        if not rec:
            return 0.0, 0.0
        return rec.water_g, float(rec.total_time_s)

    def _reset_live_view(self) -> None:
        """Wipe everything that describes a past brew.

        Changing the recipe invalidates a recorded curve as much as starting a new brew does.
        """
        self._samples.clear()
        self._flow_samples.clear()
        # The drawdown belongs to the curve being wiped; keeping it would attach the
        # previous brew's drain time to the next one.
        self._drawdown_s = 0
        self._drawdown_valid = False
        # Back to the default provenance with the curve: a manual entry
        # must not leave "manual" stamped on the next brew a scale measures.
        self._measured_source = "scale"
        ## A manual entry hides the chart (there is no shape to draw) and leaves
        ## its card open; both belong to the result being wiped.
        self.spark.setVisible(True)
        if hasattr(self, "manual_card"):
            self.manual_card.setVisible(False)
        self._stop_marker = None
        self._last_w = None
        self._step_idx = -1
        self._step_actuals = {}
        self.spark.clear()
        self.lbl_brew_time.setText("0:00")
        self.lbl_brew_weight.setText("–– g")
        self.lbl_brew_flow.setText(QApplication.translate("tilauscope_brew", "Flow: –– g/s"))
        self.lbl_brew_pct.setText("")
        self.bar_target.set_fraction(0.0)
        self.lbl_pace.setVisible(False)
        if not getattr(self, "_applying_fix", False):
            self._reset_taste_ui()
        for row in getattr(self, "step_rows", []):
            row.set_state(_StepRow.PENDING)

    def _set_recipe_locked(self, locked: bool) -> None:
        """Freeze the recipe inputs while pouring.

        Re-planning a brew that is already running is not a real gesture, and
        letting it through moved the auto-stop target and desynchronised the
        chart from the KPI strip.
        """
        for wdg in (self.cmb_method, self.spn_dose, self.cmb_water, self.cmb_machine,
                    self.cmb_style):
            wdg.setEnabled(not locked)
        if locked:
            self.btn_ai.setEnabled(False)
        else:
            self.btn_ai.setEnabled(self._ai_ready() and not self._ai_busy)

    def _toggle_brew(self) -> None:
        # The button is only reachable when a scale is connected, so there is no
        # connect branch to take here.
        self._stop_brew() if self._brew_running else self._start_brew()

    # The scale's stopwatch follows the app's brew timer, both ways and
    # from one place: start, manual stop, auto-stop at target and closing the
    # dialog mid-brew all end up here, so the scale can never be left counting
    # after a brew that is over.
    # Deliberately outside the wiring try/except of _start_brew: a scale with no
    # stopwatch (or an older scale.py with no timer signal) must degrade to "no
    # timer", never to "no brew". The gesture is fire-and-forget — the scale
    # sends no acknowledgement, so there is nothing to wait for or report.
    def _set_scale_timer(self, on: bool) -> None:
        sm = self._scale_mgr()
        sig = getattr(sm, "timer_scale1_signal", None) if sm is not None else None
        if sig is None:
            return
        try:
            sig.emit(bool(on))
        except Exception as exc:  # noqa: BLE001
            _log.warning("Brew: scale timer %s failed: %s", "start" if on else "stop", exc)

    # Fired ~300 ms after Start rather than with it. Starting a brew
    # already sends the Acaia a tare AND an LED effect (ScaleManager pairs every
    # tare with signal_user(TARE) -> send_leds_breathe), and adding a timer reset
    # plus a timer start put four BLE writes back to back on a link that answers
    # none of them. A burst like that is a plausible cause of the reported
    # "scale stays connected but sends no weight", so the stopwatch waits for the
    # tare to settle. The cost is ~0.3 s of offset on a three-minute brew, which
    # is below the scale's own display resolution; the benefit is not risking the
    # measurement itself for a convenience.
    @pyqtSlot()
    def _start_scale_timer_deferred(self) -> None:
        if self._brew_running:      # a brew that ended in the meantime wants nothing started
            self._set_scale_timer(True)

    def _start_brew(self) -> None:
        sm = self._scale_mgr()
        if sm is None or not self._scale_connected():
            return
        # Idempotent: an earlier start that raised part-way could otherwise leave
        # a stale connection behind and deliver every weight sample twice.
        self._unwire_scale_data()
        try:
            sm.scale1_weight_changed_signal.connect(self._on_scale_weight)
            sm.scale1_stable_weight_changed_signal.connect(self._on_scale_weight)
            sm.scale1_disconnected_signal.connect(self._on_scale_disconnected)
            sm.tare_scale1_signal.emit()  # zero before pulling the shot
        except Exception as exc:  # noqa: BLE001
            _log.warning("Brew: scale wiring failed: %s", exc)
            self._unwire_scale_data()
            return
        self._brew_rec = self.service.last   # freeze the plan for this brew
        # Per brew, not per dialog: each start gets its own chance to
        # report a silent scale.
        self._silent_scale_warned = False
        self._reset_live_view()
        self._set_recipe_locked(True)
        self.debrief.setVisible(False)
        self.spark.setVisible(True)
        self.lbl_pace.setVisible(True)
        self._apply_plan_to_chart()
        self._elapsed.restart()
        self._brew_running = True
        self._tick.start()
        # Deferred, not immediate — see _start_scale_timer_deferred: the
        # tare fired a few lines above is already two BLE writes, and the scale
        # must not be handed four in one burst at the exact moment it is supposed
        # to start streaming weights.
        self._scale_timer_delay.start(300)
        self._sync_scale_ui()

    def _stop_brew(self) -> None:
        if not self._brew_running:
            return
        self._brew_running = False
        self._tick.stop()
        # Stopped with the on-screen timer, whatever ended the brew —
        # the button, the auto-stop at target, or closing the dialog mid-pour.
        # The pending start is cancelled first: a brew stopped inside its first
        # 300 ms would otherwise leave the scale counting on its own.
        self._scale_timer_delay.stop()
        self._set_scale_timer(False)
        if self._samples:
            self._stop_marker = self._samples[-1]
            self.spark.set_marker(self._stop_marker)
        # Derived once, here — never in the tick path. The curve is already in
        # memory and the brew is over, so this costs nothing and cannot be
        # recomputed later: _samples is cleared by the next brew.
        self._drawdown_s, self._drawdown_valid = self._derive_drawdown()
        self.lbl_pace.setVisible(False)
        self._set_recipe_locked(False)
        for row in getattr(self, "step_rows", []):
            row.set_state(_StepRow.DONE)
        self._show_debrief()
        self._unwire_scale_data()
        # A scale we connected is released when the DIALOG closes, not here:
        # stopping one brew usually means another is about to start.
        self._sync_scale_ui()

    # ── manual result entry (espresso on a machine with a built-in scale) ──
    def _open_manual_entry(self) -> None:
        """Show the card, pre-filled with the plan so the common case is one click."""
        rec = self.service.last
        if rec is None:
            return
        self.spn_manual_time.setValue(int(_clamp(rec.total_time_s, 1, 120)))
        self.spn_manual_yield.setValue(float(_clamp(rec.water_g, 1.0, 200.0)))
        self.lbl_manual_target.setText(
            QApplication.translate("tilauscope_brew", "Target: {g} g in {t}")
            .format(g=f"{rec.water_g:.0f}", t=self._fmt_time(rec.total_time_s)))
        self.debrief.setVisible(False)
        self.manual_card.setVisible(True)
        QTimer.singleShot(0, lambda: self._right_scroll.ensureWidgetVisible(self.manual_card))

    def _close_manual_entry(self) -> None:
        self.manual_card.setVisible(False)

    def _record_manual_result(self) -> None:
        """Turn the two typed numbers into the curve the rest of the dialog reads.

        Two points only — start and end. The shape between them is not invented: the chart stays hidden and the drawdown is left invalid.
        """
        rec = self.service.last
        if rec is None:
            return
        t = float(self.spn_manual_time.value())
        w = float(self.spn_manual_yield.value())
        if t <= 0 or w <= 0:
            return
        self._brew_rec = rec          # freeze the plan this shot ran against
        self._reset_live_view()       # clears _measured_source, so label after
        self._measured_source = "manual"
        self._samples = [(0.0, 0.0), (t, w)]
        # Deliberately left empty: no flow was sampled, so no drawdown exists.
        # Espresso does not use one anyway — the shot time IS the bed signal.
        self._drawdown_s, self._drawdown_valid = 0, False
        self.manual_card.setVisible(False)
        self.spark.setVisible(False)
        self.lbl_brew_time.setText(self._fmt_time(int(t)))
        self.lbl_brew_weight.setText(f"{w:.1f} g")
        tg, _ = self._brew_target()
        if tg > 0:
            self.bar_target.set_fraction(w / tg)
            self.lbl_brew_pct.setText(
                QApplication.translate("tilauscope_brew", "{p}% of {t} g")
                .format(p=int(_clamp(w / tg * 100, 0, 999)), t=f"{tg:.0f}"))
        self.lbl_brew_flow.setText(
            QApplication.translate("tilauscope_brew", "Flow: {f} g/s").format(f=f"{w / t:.1f}"))
        self._show_debrief()

    def _unwire_scale_data(self) -> None:
        """Drop the per-brew weight subscriptions. Safe to call when not wired."""
        sm = self._scale_mgr()
        if sm is None:
            return
        for name, slot in (("scale1_weight_changed_signal", self._on_scale_weight),
                           ("scale1_stable_weight_changed_signal", self._on_scale_weight),
                           ("scale1_disconnected_signal", self._on_scale_disconnected)):
            sig = getattr(sm, name, None)
            try:
                if sig is not None:
                    sig.disconnect(slot)
            except Exception:  # noqa: BLE001
                pass

    @pyqtSlot(int)
    def _on_scale_weight(self, weight: int) -> None:
        self._last_w = float(weight)

    @pyqtSlot()
    def _on_scale_disconnected(self) -> None:
        self._last_w = None

    # ── plan wiring ──
    def _plan_rec(self):
        """The recipe the live brew is executed against.

        Frozen at Start: a recompute landing mid-pour (a late AI refinement, or
        anything that re-emits recipe_ready) must not move the target, the
        corridor or the step list out from under a brew already in progress.
        """
        return self._brew_rec if self._brew_rec is not None else self.service.last

    def _flow_scale(self) -> float:
        """Flow axis sized from the plan the operator is actually pouring.

        Scaled from the plan's steepest segment plus headroom for pour bursts, so the trace stays legible at any method and dose.
        """
        rec = self._plan_rec()
        if rec is None:
            return 10.0
        # Headroom, because a real pour is bursty around its average rate.
        return _clamp(round(planned_pour_rate(rec) * 1.6), 2.0, 14.0)

    def _apply_plan_to_chart(self) -> None:
        rec = self._plan_rec()
        if rec is None:
            return
        lo, hi, marks = _build_corridor(rec)
        self.spark.set_plan(rec.water_g, float(rec.total_time_s), lo, hi, marks,
                            self._flow_scale())

    def _update_pace(self, t: float, w: float) -> None:
        """Position against the corridor: inside the band is on plan."""
        band = self.spark.band_at(t)
        if band is None:
            self.lbl_pace.setVisible(False)
            return
        lo, hi = band
        if w > hi + 0.5:
            text = QApplication.translate("tilauscope_brew", "● {g} g ahead").format(g=f"{w - hi:.0f}")
            color = THEME["WARNING"]
        elif w < lo - 0.5:
            text = QApplication.translate("tilauscope_brew", "● {g} g behind").format(g=f"{lo - w:.0f}")
            color = THEME["WARNING"]
        else:
            text = QApplication.translate("tilauscope_brew", "● on plan")
            color = THEME["SUCCESS"]
        self.lbl_pace.setText(text)
        self.lbl_pace.setStyleSheet(
            f"color:{color};font-size:11px;font-weight:bold;border:none;")
        self.lbl_pace.setVisible(True)

    @staticmethod
    def _rows_match_states(rows, idx: int) -> bool:
        """Guard against rows that were rebuilt underneath us: the index alone is
        not proof the displayed states are still correct."""
        want = [_StepRow.DONE if i < idx else (_StepRow.CURRENT if i == idx else _StepRow.PENDING)
                for i in range(len(rows))]
        return all(r._state == s for r, s in zip(rows, want, strict=False))

    def _update_checklist(self, t: float, w: float) -> None:
        """Auto-advance the protocol rows on elapsed time and record the weight
        actually reached as each step closes."""
        rec = self._plan_rec()
        rows = getattr(self, "step_rows", [])
        if rec is None or not rows:
            return
        idx = -1
        for i, s in enumerate(rec.steps):
            if t >= s.at_s:
                idx = i
        if idx == self._step_idx and self._rows_match_states(rows, idx):
            return
        for i in range(self._step_idx, idx):
            if 0 <= i < len(rows):
                self._step_actuals[i] = (t, w)
        self._step_idx = idx
        for i, row in enumerate(rows):
            row.set_state(_StepRow.DONE if i < idx
                          else (_StepRow.CURRENT if i == idx else _StepRow.PENDING))

    def _tick_update(self) -> None:
        # Guarded: an exception here would otherwise repeat at 5 Hz and leave the
        # brew running against a display that stopped updating.
        try:
            self._tick_update_inner()
        except Exception as exc:  # noqa: BLE001
            _log.exception("Brew: live update failed, stopping the brew: %s", exc)
            try:
                self._stop_brew()
            except Exception:  # noqa: BLE001
                self._tick.stop()
                self._brew_running = False

    # How long a started brew may go without a single weight before the
    # panel says so. An Acaia that is streaming delivers within a second or two;
    # five seconds of nothing is a scale that is connected but silent, not a slow
    # one. Long enough that a pause between placing the cup and pouring never
    # triggers it — the reading arrives regardless of whether the weight moves.
    _SILENT_SCALE_S: float = 5.0

    def _tick_update_inner(self) -> None:
        t = self._elapsed.elapsed() / 1000.0
        self.lbl_brew_time.setText(self._fmt_time(int(t)))
        if self._last_w is None:
            # A brew where the scale never reports a weight otherwise looks like a
            # brew going fine (timer running, everything else empty). Named on
            # screen AND logged at WARNING so an intermittent occurrence leaves a
            # trace even with debug logging off.
            # Not an error path: the brew keeps running and heals itself the
            # moment a weight arrives, because _update_pace repaints this label.
            if t >= self._SILENT_SCALE_S and not self._silent_scale_warned:
                self._silent_scale_warned = True
                _log.warning(
                    "Brew: no weight received %.0fs after start "
                    "(scale1 connected=%s, configured=%s) — scale connected but silent",
                    t, self._scale_connected(), self._scale_configured())
                self.lbl_pace.setText(QApplication.translate(
                    "tilauscope_brew", "● scale silent"))
                self.lbl_pace.setToolTip(QApplication.translate(
                    "tilauscope_brew",
                    "The scale is connected but has not sent a single weight since "
                    "the brew started. Take the cup off and put it back, or switch "
                    "the scale off and on again — the app reconnects by itself."))
                self.lbl_pace.setStyleSheet(
                    f"color:{THEME['CRITICAL']};"
                    f"font-size:12px;font-weight:bold;border:none;")
                self.lbl_pace.setVisible(True)
            return
        w = self._last_w
        self.lbl_brew_weight.setText(f"{w:.1f} g")
        self._samples.append((t, w))
        # flow = smoothed slope over the last ~1.5 s window
        flow = 0.0
        if len(self._samples) >= 2:
            t0, w0 = next((p for p in reversed(self._samples) if t - p[0] >= 1.5), self._samples[0])
            dt = t - t0
            if dt > 0:
                flow = max(0.0, (w - w0) / dt)
        self.lbl_brew_flow.setText(QApplication.translate("tilauscope_brew", "Flow: {f} g/s").format(f=f"{flow:.1f}"))
        self._flow_samples.append((t, flow))
        self.spark.set_points(self._samples)
        self.spark.set_flow(self._flow_samples)
        tg, _ = self._brew_target()
        if tg > 0:
            self.bar_target.set_fraction(w / tg)
            self.lbl_brew_pct.setText(
                QApplication.translate("tilauscope_brew", "{p}% of {t} g")
                .format(p=int(_clamp(w / tg * 100, 0, 999)), t=f"{tg:.0f}"))
        self._update_pace(t, w)
        self._update_checklist(t, w)
        # optional auto-stop at target
        if self._autostop_applies() and self.btn_autostop.isChecked() and tg > 0 and w >= tg:
            self._stop_brew()

    # ── per-bean dial-in persistence (BeanCave GreenBean.dial_ins) ──
    @staticmethod
    def _ratio_of(rec) -> float:
        """The N in 1:N, or 0.0 if it cannot be read."""
        m = _re.search(r"1:([\d.]+)", getattr(rec, "ratio_str", "") or "")
        return float(m.group(1)) if m else 0.0

    # Stopping on weight only makes sense when the scale weighs what
    # COMES OUT — that is exactly water_is_yield, and only espresso has it.
    # Everywhere else the scale weighs the whole assembly, so it reaches the
    # target at the end of the last pour, before the bed has finished draining:
    # an auto-stop there cuts the brew short and, worse, records a drawdown of
    # zero. Soft methods end when the operator judges it has stopped dripping.
    # Below this smoothed flow the operator has stopped pouring and the
    # bed is draining on its own. Provisional and assumed as such: no data exists
    # yet to set it (wiki/Brew-DialIn-Feedback-Spec.md §6) — it is one of the first
    # things the journal itself will let us measure.
    _POUR_FLOW_THRESHOLD: float = 0.4      # g/s

    def _derive_drawdown(self) -> tuple[int, bool]:
        """Seconds of drain after the last pour, and whether that number means anything.

        In a pour-over or an immersion the scale weighs the whole assembly, so the
        weight climbs while pouring and PLATEAUS while the bed drains — the drawdown
        is the flat tail of the curve. That tail is the only part of the total time
        the grind actually controls; the rest is the operator's pour schedule.

        Espresso is excluded on purpose: the pump is fixed and the shot time IS the
        bed, so `measured_time_s` is already the clean signal and a "drawdown" there
        would mean nothing.

        The flow used is the same 1.5 s smoothed slope shown live, so the detected
        pour end trails the real one by up to ~1.5 s. Left uncorrected: the bias is
        systematic, so it cancels in the drawdown DIFFERENCE between two brews, which
        is the only quantity the journal is built to compare. Chasing the exact
        instant would buy false precision on a scale that samples every 200 ms.
        """
        rec = self._plan_rec()
        if rec is None or getattr(rec, "water_is_yield", False):
            return 0, False
        if not self._samples or not self._flow_samples:
            return 0, False        # no scale was on the line
        t_end = self._samples[-1][0]
        last_pour = None
        for t, flow in self._flow_samples:
            if flow >= self._POUR_FLOW_THRESHOLD:
                last_pour = t
        if last_pour is None:
            return 0, False        # weight never moved: nothing was measured
        return max(0, int(round(t_end - last_pour))), True

    def _autostop_applies(self) -> bool:
        rec = self._plan_rec() or self.service.last
        return bool(getattr(rec, "water_is_yield", False)) if rec is not None else False

    def _can_store_dialin(self) -> bool:
        return self._bean is not None

    # A dial-in carries no expiry. It was accepted on ONE roast of this
    # green bean, at one point in its degassing; a later roast is a legitimate
    # place to reuse it (the correction is relative), a bean sitting a season in
    # storage much less so. Rather than invent an expiry rule, show the age and
    # let the operator judge — the data was already being recorded.
    _DIALIN_STALE_DAYS: int = 90

    def _dialin_age_days(self, method_id: str) -> Optional[int]:
        iso = self.service.dialin_date_for(method_id)
        if not iso:
            return None
        try:
            from datetime import datetime  # noqa: PLC0415
            d = datetime.fromisoformat(str(iso)[:10]).date()
        except (TypeError, ValueError):
            return None
        from datetime import date  # noqa: PLC0415
        return max(0, (date.today() - d).days)

    def _dialin_age_text(self, method_id: str) -> str:
        """Short age for the badge. '' when the date is unknown (legacy entry)."""
        n = self._dialin_age_days(method_id)
        if n is None:
            return ""
        if n == 0:
            return QApplication.translate("tilauscope_brew", "today")
        if n < 14:
            return QApplication.translate("tilauscope_brew", "{n} d").format(n=n)
        if n < 60:
            return QApplication.translate("tilauscope_brew", "{n} wk").format(n=n // 7)
        return QApplication.translate("tilauscope_brew", "{n} mo").format(n=n // 30)

    def _dialin_age_tooltip(self, method_id: str) -> str:
        base = QApplication.translate(
            "tilauscope_brew",
            "This recipe carries the correction you saved for this bean on this "
            "brew method, applied on top of today's recommendation.")
        iso = self.service.dialin_date_for(method_id)
        n = self._dialin_age_days(method_id)
        if n is None:
            return base + "\n\n" + QApplication.translate(
                "tilauscope_brew",
                "It was saved before TilauScope kept the date, so its age is unknown.")
        when = QApplication.translate(
            "tilauscope_brew", "Saved on {d}.").format(d=str(iso)[:10])
        if n < self._DIALIN_STALE_DAYS:
            return f"{base}\n\n{when}"
        return f"{base}\n\n{when} " + QApplication.translate(
            "tilauscope_brew",
            "That is a while ago: it was dialled on a different roast of this bean, "
            "and the green itself has aged since. Treat it as a starting point and "
            "taste before trusting it.")

    def _load_dialins(self) -> None:
        """Restore accepted corrections for this bean so a known bean reopens on
        the setting that actually tasted right, not the generic recommendation."""
        if self._bean is None:
            return
        for d in (getattr(self._bean, "dial_ins", None) or []):
            try:
                if d.method_id not in METHOD_ORDER:
                    continue
                # Prefer the base recorded with the dial-in: a correction is
                # relative, so re-applying it stays valid on a different roast. No stored base falls back to the current one.
                ref_grind = d.base_grind_um
                ref_temp = d.base_temp_c
                ref_ratio = getattr(d, "base_ratio", 0.0)
                if not ref_grind:
                    legacy = self.service._engine.advise(self.service.input, d.method_id,
                                                         d.dose_g or None)
                    ref_grind, ref_temp = legacy.grind_um, legacy.temp_c
                    # No ratio fallback: comparing a stored roast-independent
                    # ratio against today's roast-dependent base would read as a correction the operator never made.
                    ref_ratio = 0.0
                    _log.info("Brew: dial-in for %s predates base tracking; "
                              "restoring against the current recipe", d.method_id)
                corr = BrewCorrection(
                    grind_mult=(d.grind_um / ref_grind) if (d.grind_um and ref_grind) else 1.0,
                    # A "thin body" dial-in moves the RATIO and nothing else;
                    # restoring only grind/temp would drop it and leave the bean
                    # looking un-dialled to the cross-bean setup offset.
                    ratio_delta=(d.ratio - ref_ratio) if (d.ratio and ref_ratio) else 0.0,
                    temp_delta=(d.temp_c - ref_temp) if (d.temp_c and ref_temp) else 0.0)
                # Restored on its own, not as part of the correction: a dial-in that
                # only moved the dose is still worth reopening on, and a PRESSURE
                # recipe at the wrong dose is a different puck whatever the grind says.
                self.service.set_dialin_dose(d.method_id, d.dose_g)
                self.service.set_dialin_date(d.method_id, getattr(d, "iso_date", ""))
                if not corr.is_empty:
                    self.service.set_dialin(d.method_id, corr, emit=False)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Brew: could not restore dial-in for %s: %s",
                             getattr(d, "method_id", "?"), exc)

    def _learn_setup_offsets(self) -> None:
        """Aggregate every bean's accepted corrections into a per-family offset.

        Recomputed from the library on each open rather than cached: the source
        of truth is the dial-ins themselves, so there is no stale value to
        invalidate when one is added or a bean is deleted.
        """
        cave = getattr(self._beancave, "cave", None)
        beans = getattr(cave, "green_beans", None) if cave is not None else None
        if not beans:
            return
        ratios: dict[str, list[float]] = {}
        for b in beans:
            # Per bean, reduced to one sample: this offset models a fixed setup
            # bias, so evidence must come from different beans, not one bean dialled on several methods.
            per_bean: dict[str, list[float]] = {}
            for d in (getattr(b, "dial_ins", None) or []):
                try:
                    if d.method_id not in METHOD_ORDER or not (d.grind_um and d.base_grind_um):
                        continue  # legacy entry: no base recorded, no usable ratio
                    r = d.grind_um / d.base_grind_um
                    # A dial-in that moved only ratio or temp says nothing about
                    # grind, so a 1.0 sample is excluded rather than skewing the direction test.
                    if abs(r - 1.0) < 1e-3:
                        continue
                    per_bean.setdefault(BrewAdvisorService.family_key(d.method_id), []).append(r)
                except Exception:  # noqa: BLE001
                    continue
            for key, vals in per_bean.items():
                vals.sort()
                n = len(vals)
                med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
                ratios.setdefault(key, []).append(med)
        for key, vals in ratios.items():
            mult = learn_setup_offset(vals)
            if mult is not None:
                self.service.set_setup_offset(key, mult, len(vals))
                _log.info("Brew: setup offset for %s = %.3f from %d dial-ins",
                          key, mult, len(vals))

    def _store_dialin(self, rec, dg, tastes: list[str],
                      measured: tuple[float, float]) -> bool:
        """True only if the dial-in actually reached the disk."""
        if self._bean is None or rec is None:
            return False
        try:
            from datetime import datetime  # noqa: PLC0415
            from tilauscope.tilauscope_types import BrewDialIn  # noqa: PLC0415
            corrected = self.service.last or rec
            base = self.service.base_recipe()
            m = _re.search(r"1:([\d.]+)", corrected.ratio_str)
            entry = BrewDialIn(
                method_id=corrected.method_id,
                grind_um=int(corrected.grind_um),
                ratio=float(m.group(1)) if m else 0.0,
                temp_c=float(corrected.temp_c),
                base_grind_um=int(base.grind_um) if base else 0,
                base_temp_c=float(base.temp_c) if base else 0.0,
                base_ratio=self._ratio_of(base) if base else 0.0,
                dose_g=float(corrected.dose_g),
                taste=list(tastes),
                diagnosis=dg.code.value,
                measured_time_s=int(measured[0]),
                measured_yield_g=float(measured[1]),
                iso_date=datetime.now().astimezone().date().isoformat(),
            )
            existing = list(getattr(self._bean, "dial_ins", None) or [])
            # One entry per method: the latest accepted dial-in wins.
            existing = [d for d in existing if d.method_id != entry.method_id]
            existing.append(entry)
            self._bean.dial_ins = existing
            # Keep the badge honest straight away: this dial-in is from today.
            self.service.set_dialin_dose(entry.method_id, entry.dose_g)
            self.service.set_dialin_date(entry.method_id, entry.iso_date)
            return self._persist_bean()
        except Exception as exc:  # noqa: BLE001
            _log.error("Brew: storing the dial-in failed: %s", exc)
            return False

    # The journal records the extraction that was just tasted (setting, result,
    # verdict) — not the dial-in, which records the corrected setting to reopen on.
    # Written only when a brew was really measured (spec §4.1): a measurement
    # without a verdict is not data, and neither is a verdict without a measurement.
    # Reading thresholds below are all provisional (spec §6), conventions rather than data-derived.
    _GRIND_CHANGED_PCT: float = 2.0     # below this the grinder does not render it
    _SIGNAL_MOVED_PCT: float = 10.0     # of the previous value
    _SIGNAL_MOVED_S: int = 5            # and at least this many seconds
    _DOSE_COMPARABLE_PCT: float = 10.0  # beyond this it is a different brew

    def _reload_brewlog(self) -> None:
        """Re-read the journal from disk. At open, and after a line is written —
        never anywhere the render path can reach."""
        try:
            from tilauscope import brew_log as _brew_log  # noqa: PLC0415
            self._brewlog = _brew_log.load(
                getattr(self._beancave, "beancave_directory", None))
        except Exception as exc:  # noqa: BLE001
            _log.warning("Brew: journal unavailable (%s)", exc)
            self._brewlog = None

    def _refresh_previous_try(self) -> None:
        """Show whether the last setting change moved the extraction, or hide.

        Pure: reads `self._brewlog`, held in memory since the dialog opened and
        refreshed only after a write. Called from the render path, so it must never
        touch the disk (see feedback_realtime_architecture / populate_bean_list).
        """
        try:
            self._render_previous_try()
        except Exception as exc:  # noqa: BLE001
            _log.warning("Brew: previous-attempt panel failed: %s", exc)
            self.prev_try.setVisible(False)

    def _render_previous_try(self) -> None:
        from tilauscope import brew_log as _brew_log  # noqa: PLC0415

        self.lbl_prev_causes.setVisible(False)
        bean_uuid = getattr(self._bean, "uuid", "") if self._bean is not None else ""
        log = getattr(self, "_brewlog", None)
        rec = self.service.last
        if not bean_uuid or log is None or rec is None:
            self.prev_try.setVisible(False)
            return
        rows = _brew_log.samples_for(log, bean_uuid, rec.method_id)
        if len(rows) < 2:
            # One row is a record, not a comparison: nothing to say yet.
            self.prev_try.setVisible(False)
            return
        prev, last = rows[-2], rows[-1]

        # ── is this pair comparable at all? ──
        if prev.dose_g > 0 and last.dose_g > 0:
            dose_gap = abs(last.dose_g - prev.dose_g) / prev.dose_g * 100.0
            if dose_gap > self._DOSE_COMPARABLE_PCT:
                self.prev_try.setVisible(False)
                return
        is_shot = bool(getattr(rec, "water_is_yield", False))

        self.lbl_prev_title.setText(QApplication.translate(
            "tilauscope_brew", "PREVIOUS ATTEMPT — {d}").format(d=last.iso_date or "?"))

        # ── what changed (the cause) ──
        if prev.grind_um > 0 and last.grind_um > 0:
            pct = (last.grind_um - prev.grind_um) / prev.grind_um * 100.0
        else:
            pct = 0.0
        grind_moved = abs(pct) >= self._GRIND_CHANGED_PCT
        if grind_moved:
            self.lbl_prev_change.setText(QApplication.translate(
                "tilauscope_brew", "Grind {a} → {b} µm  ({p:+.0f} %)").format(
                    a=prev.grind_um, b=last.grind_um, p=pct))
        else:
            self.lbl_prev_change.setText(QApplication.translate(
                "tilauscope_brew", "Grind unchanged — {a} µm").format(a=last.grind_um))

        # ── what came out (the consequence) ──
        if is_shot:
            a, b = prev.measured_time_s, last.measured_time_s
            label = QApplication.translate("tilauscope_brew", "Shot time")
            measured = a > 0 and b > 0
        else:
            a, b = prev.drawdown_s, last.drawdown_s
            label = QApplication.translate("tilauscope_brew", "Drawdown")
            measured = prev.drawdown_valid and last.drawdown_valid
        if not measured:
            # Say plainly that nothing was measured. Showing the total time
            # instead would put a number on screen that mostly reflects how the
            # operator poured — the very confusion this whole feature exists to avoid.
            self.lbl_prev_signal.setText("")
            self.lbl_prev_verdict.setText(QApplication.translate(
                "tilauscope_brew",
                "Flow was not measured: no scale was connected. The total time depends "
                "mostly on how you poured, so it says nothing about the grind."))
            self.prev_try.setVisible(True)
            return

        delta = b - a
        color = THEME["SUBTEXT"] if delta == 0 else (
            THEME["WARNING"] if delta > 0 else THEME["ACCENT"])
        self.lbl_prev_signal.setText(
            f"<span style='color:{THEME['SUBTEXT']};'>{label}</span>&nbsp;&nbsp;"
            f"<span style='color:{THEME['TEXT']};'>{a} s → {b} s</span>&nbsp;&nbsp;"
            f"<span style='color:{color};'>{delta:+d} s</span>")

        # ── did the change bite? ──
        moved = abs(delta) >= self._SIGNAL_MOVED_S and (
            a <= 0 or abs(delta) / a * 100.0 >= self._SIGNAL_MOVED_PCT)
        if not grind_moved:
            self.lbl_prev_verdict.setText(QApplication.translate(
                "tilauscope_brew",
                "Same grind as the attempt before: this is the spread between two "
                "brews at the same setting.") if not moved else QApplication.translate(
                "tilauscope_brew",
                "Same grind, yet the flow moved: something other than the grind "
                "changed between these two brews."))
            self.lbl_prev_verdict.setProperty('variant', 'caption')
        elif moved:
            finer = pct < 0
            slower = delta > 0
            self.lbl_prev_verdict.setText(
                QApplication.translate("tilauscope_brew",
                                       "The bed resists more: that step bit.")
                if (finer and slower) or (not finer and not slower) else
                QApplication.translate("tilauscope_brew",
                                       "The flow moved the other way to the grind — "
                                       "worth a second look before trusting it."))
            self.lbl_prev_verdict.setStyleSheet(
                f"color:{THEME['SUCCESS']};font-size:11px;")
        else:
            self.lbl_prev_verdict.setText(QApplication.translate(
                "tilauscope_brew", "That step changed nothing in the flow."))
            self.lbl_prev_verdict.setStyleSheet(
                f"color:{THEME['WARNING']};font-size:11px;")
            # Causes, never a proposal. The doctrine is explicit: the
            # measured flow diagnoses, it does not decide the next setting.
            self.lbl_prev_causes.setText(QApplication.translate(
                "tilauscope_brew",
                "Can come from: play on that step of your grinder · a different dose "
                "or pour · a bean still very fresh."))
            self.lbl_prev_causes.setVisible(True)
        self.prev_try.setVisible(True)

    def _journal_brew(self, rec, dg, tastes: list[str],
                      measured: tuple[float, float],
                      drawdown: tuple[int, bool], source: str = "scale") -> bool:
        bean_uuid = getattr(self._bean, "uuid", "") if self._bean is not None else ""
        if not bean_uuid or rec is None:
            return False
        if not measured or measured[0] <= 0:
            return False        # nothing was brewed in the app: no consequence to record
        try:
            from datetime import datetime  # noqa: PLC0415
            from tilauscope import brew_log as _brew_log  # noqa: PLC0415
            from tilauscope.tilauscope_types import BrewSample  # noqa: PLC0415
            base = self.service.base_recipe()
            inp = self.service.input
            sample = BrewSample(
                method_id=rec.method_id,
                iso_date=datetime.now().astimezone().date().isoformat(),
                # the cause: the setting this brew actually ran on
                grind_um=int(rec.grind_um),
                ratio=self._ratio_of(rec),
                temp_c=float(rec.temp_c),
                dose_g=float(rec.dose_g),
                base_grind_um=int(base.grind_um) if base else 0,
                base_ratio=self._ratio_of(base) if base else 0.0,
                base_temp_c=float(base.temp_c) if base else 0.0,
                # the target, so the gap stays computable when the engine moves on
                planned_time_s=int(rec.total_time_s),
                planned_water_g=float(rec.water_g),
                # the consequence
                measured_time_s=int(measured[0]),
                measured_yield_g=float(measured[1]),
                drawdown_s=int(drawdown[0]),
                drawdown_valid=bool(drawdown[1]),
                measured_source=str(source or "scale"),
                # the context, without which two rows cannot be compared
                agtron=float(getattr(rec, "agtron", 0.0)),
                days_off_roast=int(getattr(inp, "days_off_roast", -1)),
                espresso_style=getattr(getattr(inp, "espresso_style", None), "value", ""),
                # the verdict that justifies keeping the row at all
                taste=list(tastes),
                diagnosis=dg.code.value,
            )
            directory = getattr(self._beancave, "beancave_directory", None)
            return _brew_log.record(directory, bean_uuid, sample)
        except Exception as exc:  # noqa: BLE001
            _log.error("Brew: journalling the extraction failed: %s", exc)
            return False

    def _persist_bean(self) -> bool:
        """Write the BeanCave library back to disk (BeancaveDlg.save_green_beans
        serialises the whole container, so the new field goes with it)."""
        fn = getattr(self._beancave, "save_green_beans", None)
        if not callable(fn):
            _log.warning("Brew: no BeanCave save entry point; dial-in kept in memory only")
            return False
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _log.error("Brew: BeanCave save failed: %s", exc)
            return False
        return True

    # ── taste feedback ──
    def _reset_taste_ui(self) -> None:
        for b in self.taste_btns.values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self.lbl_verdict.setVisible(False)
        self.btn_apply_fix.setVisible(False)
        self.lbl_fix_done.setVisible(False)
        self._pending_fix = None

    def _selected_tastes(self) -> set:
        return {c for c, b in self.taste_btns.items() if b.isChecked()}

    def _on_taste_clicked(self, code) -> None:
        # "Balanced" is exclusive: it cannot coexist with a fault.
        if code == TasteCode.BALANCED and self.taste_btns[code].isChecked():
            for c, b in self.taste_btns.items():
                if c != TasteCode.BALANCED:
                    b.setChecked(False)
        elif code != TasteCode.BALANCED and self.taste_btns[code].isChecked():
            self.taste_btns[TasteCode.BALANCED].setChecked(False)
        self._update_verdict()

    def _rest_status(self) -> Optional[RestStatus]:
        rec = self._plan_rec()
        inp = self.service.input
        if rec is None or inp.days_off_roast < 0:
            return None
        return rest_window(rec.agtron, inp.days_off_roast, rec.family).status

    def _update_verdict(self) -> None:
        rec = self._plan_rec()
        tastes = self._selected_tastes()
        self.lbl_fix_done.setVisible(False)
        if rec is None or not tastes:
            self.lbl_verdict.setVisible(False)
            self.btn_apply_fix.setVisible(False)
            self._pending_fix = None
            self.lbl_debrief_coach.setVisible(bool(self.lbl_debrief_coach.text()))
            return
        measured = int(self._samples[-1][0]) if self._samples else 0
        dg = diagnose(tastes, rec.total_time_s, measured, self._rest_status(),
                      family=rec.family, current_ratio=self._ratio_of(rec))
        title, what = _diagnosis_text(dg.code)
        if not title:
            self.lbl_verdict.setVisible(False)
            self.btn_apply_fix.setVisible(False)
            self._pending_fix = None
            return
        color = (THEME["SUCCESS"] if dg.code == DiagnosisCode.BALANCED
                 else THEME["WARNING"] if dg.actionable else THEME["CRITICAL"])
        html = (f"<span style='color:{color};font-weight:bold;'>{title}</span><br/>"
                f"<span style='color:{THEME['SUBTEXT']};'>{what}</span>")
        if dg.actionable and not dg.correction.is_empty:
            html += "<br/>" + self._correction_preview(rec, dg.correction)
        if not dg.used_time and dg.code not in (DiagnosisCode.UNDER_NO_TIME,
                                                DiagnosisCode.OVER_NO_TIME):
            html += ("<br/><span style='color:" + THEME["SUBTEXT"] + ";'>"
                     + QApplication.translate(
                         "tilauscope_brew",
                         "No brew time was measured, so this reads the taste alone.")
                     + "</span>")
        self.lbl_verdict.setText(html)
        self.lbl_verdict.setVisible(True)
        # The time-only coach is a fallback for when no taste was reported. Once
        # it is, the taste diagnosis knows strictly more and must not sit next to
        # a contradictory "grind coarser" line (slow+sour is channelling, not
        # over-extraction).
        self.lbl_debrief_coach.setVisible(False)
        # Reveal the answer: on a short window the verdict lands below the fold,
        # and an answer the operator has to go looking for is a wasted answer.
        QTimer.singleShot(0, lambda: self._right_scroll.ensureWidgetVisible(self.debrief)
                          if self.debrief.isVisible() else None)
        # BALANCED is worth saving even though it changes nothing.
        offer = dg.code == DiagnosisCode.BALANCED or (dg.actionable and not dg.correction.is_empty)
        self.btn_apply_fix.setVisible(offer and self._can_store_dialin())
        self.btn_apply_fix.setText(
            QApplication.translate("tilauscope_brew", "Save this dial-in")
            if dg.code == DiagnosisCode.BALANCED
            else QApplication.translate("tilauscope_brew", "Apply to next brew"))
        self._pending_fix = dg if offer else None

    def _correction_preview(self, rec, corr) -> str:
        """Show the change as before → after, so nothing moves invisibly."""
        bits: list[str] = []
        if abs(corr.grind_mult - 1.0) > 1e-6:
            new = int(_clamp(round(rec.grind_um * corr.grind_mult), 150, 1300))
            word = (QApplication.translate("tilauscope_brew", "finer")
                    if new < rec.grind_um else QApplication.translate("tilauscope_brew", "coarser"))
            bits.append(f"{QApplication.translate('tilauscope_brew', 'Grind')} "
                        f"{rec.grind_um} → <b>{new} µm</b> ({word})")
        if abs(corr.temp_delta) > 1e-6:
            new_t = _clamp(rec.temp_c + corr.temp_delta, 80.0, 99.0)
            bits.append(f"{QApplication.translate('tilauscope_brew', 'Temp')} "
                        f"{self._fmt_temp(rec.temp_c)} → <b>{self._fmt_temp(new_t)}</b>")
        if abs(corr.ratio_delta) > 1e-6:
            m = _re.search(r"1:([\d.]+)", rec.ratio_str)
            if m:
                base = max(ratio_floor(rec.family), float(m.group(1)) + corr.ratio_delta)
                bits.append(f"{QApplication.translate('tilauscope_brew', 'Ratio')} "
                            f"{rec.ratio_str} → <b>1:{base:.1f}</b> "
                            f"({rec.water_g:.0f} → {rec.dose_g * base:.0f} g)")
        return f"<span style='color:{THEME['TEXT']};'>" + " · ".join(bits) + "</span>"

    # The acknowledgement of an accepted correction. It has one job the
    # previous "Saved ✓" could not do: prove the click landed. Accepting a fix
    # clears the chips and hides the verdict that justified it (both deliberate),
    # so unless the confirmation itself restates WHAT moved and WHERE it went,
    # the whole gesture reads as "nothing happened" — which is exactly how it was
    # reported. Same before → after rendering as the preview above, so the line
    # the operator agreed to and the line they get back are one implementation.
    def _fix_done_text(self, rec, dg, stored: bool) -> str:
        bean = str(getattr(self._bean, "name", "") or "").strip() or self._title
        if stored:
            head = QApplication.translate(
                "tilauscope_brew", "✓ Applied and saved to {bean}").format(bean=bean)
            colour = THEME["SUCCESS"]
        else:
            ## Applied on screen but never reached the library: it dies with the
            ## dialog, and the operator has to be told now, not next time.
            head = QApplication.translate(
                "tilauscope_brew", "Applied — but could not be saved to this bean")
            colour = THEME["WARNING"]
        html = f"<span style='color:{colour};font-weight:bold;'>{head}</span>"
        # BALANCED carries no correction: there is nothing to show as before → after.
        if rec is not None and dg.correction is not None and not dg.correction.is_empty:
            html += "<br/>" + self._correction_preview(rec, dg.correction)
        return html

    def _apply_taste_correction(self) -> None:
        dg = getattr(self, "_pending_fix", None)
        if dg is None:
            return
        rec = self._plan_rec()
        # Snapshot the report BEFORE anything recomputes: applying re-renders,
        # and the render path clears the taste chips.
        tastes = sorted(t.value for t in self._selected_tastes())
        measured = self._samples[-1] if self._samples else (0.0, 0.0)
        # The drawdown belongs to the same snapshot: applying re-renders,
        # and the render path wipes the curve AND the drawdown derived from it. Read
        # after the recompute, the journal would record every drain as zero.
        drawdown = (self._drawdown_s, self._drawdown_valid)
        ## Same snapshot, same reason: the recompute resets the provenance.
        source = self._measured_source
        # Keep the debrief on screen through the re-render — it is the
        # justification for the change that just happened, and would otherwise
        # vanish with it.
        # Bound before the try, not inside it: the acknowledgement below
        # runs whatever happens, and the honest default for "did this reach the
        # library" is no.
        stored = False
        self._applying_fix = True
        try:
            # Applying releases the frozen plan so the corrected recipe renders.
            self._brew_rec = None
            if not dg.correction.is_empty:
                self.service.add_correction(dg.correction)
            # Journalled BEFORE the dial-in is stored, and independently:
            # the two writes target different files and neither may take the other
            # down. `rec` here is the plan the brew ran against, captured above
            # before the correction moved anything.
            if self._journal_brew(rec, dg, tastes, measured, drawdown, source):
                self._reload_brewlog()   # a new line makes a new comparison possible
            stored = self._store_dialin(rec, dg, tastes, measured)
            # The badge was painted by the recompute above, before the dial-in
            # existed, so it came out undated; repaint now, still under _applying_fix so the debrief survives.
            if self.service.last is not None:
                self._render(self.service.last)
        finally:
            self._applying_fix = False
        # An accepted correction consumes the report that produced it, so the
        # next cup's tasting starts from a clean slate rather than folding in an already-applied adjustment.
        self._reset_taste_ui()
        # The correction always applies to the recipe on screen but only
        # survives closing the dialog if it reached the library — never say "Saved" when the write failed.
        self.lbl_fix_done.setText(self._fix_done_text(rec, dg, stored))
        self.lbl_fix_done.setVisible(True)

    # ── post-brew debrief ──
    def _show_debrief(self) -> None:
        rec = self._plan_rec()   # judge the brew against the plan it actually ran
        if rec is None or not self._samples:
            return
        t_end, w_end = self._samples[-1]
        tg, tt = self._brew_target()
        avg_flow = w_end / t_end if t_end > 0 else 0.0
        ratio = f"1:{w_end / rec.dose_g:.1f}" if rec.dose_g > 0 else "—"
        self.lbl_debrief_spec.setText(
            f"{rec.dose_g:.0f} g → {w_end:.0f} g   {ratio}   "
            f"{self._fmt_time(int(t_end))}   {avg_flow:.1f} g/s")

        dg, dt = w_end - tg, t_end - tt
        parts: list[str] = []
        if tg > 0:
            c = THEME["SUCCESS"] if abs(dg) <= max(2.0, tg * 0.03) else THEME["WARNING"]
            word = (QApplication.translate("tilauscope_brew", "over")
                    if dg >= 0 else QApplication.translate("tilauscope_brew", "under"))
            parts.append(f"<span style='color:{c};'>● {abs(dg):.0f} g {word}</span>")
        if tt > 0:
            c = THEME["SUCCESS"] if abs(dt) <= max(5.0, tt * 0.06) else THEME["WARNING"]
            word = (QApplication.translate("tilauscope_brew", "slow")
                    if dt >= 0 else QApplication.translate("tilauscope_brew", "fast"))
            parts.append(f"<span style='color:{c};'>● {abs(dt):.0f} s {word}</span>")
        self.lbl_debrief_delta.setText("&nbsp;&nbsp;".join(parts))

        # Coaching points back at the lever, not at the outcome: time drift on a
        # fixed grind is a grind problem.
        tip = ""
        if tt > 0 and dt < -max(5.0, tt * 0.10):
            tip = QApplication.translate(
                "tilauscope_brew", "Ran fast: grind one step finer next time.")
        elif tt > 0 and dt > max(5.0, tt * 0.10):
            tip = QApplication.translate(
                "tilauscope_brew", "Ran slow: grind one step coarser next time.")
        elif tg > 0 and dg > max(2.0, tg * 0.05):
            tip = QApplication.translate(
                "tilauscope_brew", "Overshot the target weight: stop earlier or enable auto-stop.")
        self.lbl_debrief_coach.setText(tip)
        self.lbl_debrief_coach.setVisible(bool(tip))
        self.debrief.setVisible(True)

    # ── render slot ──
    @pyqtSlot(object)
    def _render(self, rec: BrewRecipe) -> None:
        # A brew in progress owns the whole panel: the KPI strip, the chips, the
        # step list and the corridor must all keep describing the plan frozen at
        # Start. Repainting only part of it would show a recipe the pour is not
        # following.
        if self._brew_running:
            return
        if hasattr(self, "lbl_brew_target"):
            lbl = QApplication.translate("tilauscope_brew", "Yield") if rec.water_is_yield else QApplication.translate("tilauscope_brew", "Water")
            self.lbl_brew_target.setText(
                f"{QApplication.translate("tilauscope_brew", 'Target')}: {rec.water_g:.0f} g {lbl} · {self._fmt_time(rec.total_time_s)}")
            # Show the plan corridor before the brew starts, so the operator can
            # read the intended shape ahead of pouring. A new recipe also
            # releases the frozen plan, wipes the previous brew's trace and
            # retires its debrief.
            self._brew_rec = None
            self._reset_live_view()
            self._apply_plan_to_chart()
            if not getattr(self, "_applying_fix", False):
                self.debrief.setVisible(False)
            # The brew controls depend on the RECIPE (only espresso is
            # offered an auto-stop or a manual entry), not just on the scale, so
            # they have to be resynced whenever the recipe moves. Without this
            # the first sync ran before the first recipe existed and, with no
            # scale on the line to fire _on_scale_state, nothing ever corrected
            # it — the manual-entry button stayed hidden for exactly the
            # operators it was built for. Pure widget state, no I/O.
            self._sync_scale_ui()
        water_label = QApplication.translate("tilauscope_brew", "Yield") if rec.water_is_yield else QApplication.translate("tilauscope_brew", "Water")

        # ── KPI strip ──
        self.kpis["dose"].set_value(f"{rec.dose_g:.0f} g")
        self.kpis["water"].set_caption(water_label)
        self.kpis["water"].set_value(f"{rec.water_g:.0f} g")
        self.kpis["ratio"].set_value(rec.ratio_str)
        self.kpis["temp"].set_value(self._fmt_temp(rec.temp_c))
        self.kpis["grind"].set_value(f"{rec.grind_um} µm", _grind_label(rec.grind_cat))
        self.kpis["time"].set_value(self._fmt_time(rec.total_time_s))

        # ── secondary chips ──
        _clear_layout(self.chip_row)
        chips: list[tuple[str, Optional[str]]] = [(_roast_label(rec.roast_key), None)]
        if rec.bloom_g > 0:
            chips.append((QApplication.translate("tilauscope_brew", "Bloom {g} g / {s} s")
                          .format(g=f"{rec.bloom_g:.0f}", s=rec.bloom_s), None))
        chips.append((_agitation_label(rec.agitation), None))
        tds = _tds_label(rec.tds_hint_key)
        chips.append((QApplication.translate("tilauscope_brew", "EY {ey}").format(ey=rec.target_ey)
                      + (f" · {tds}" if tds else ""), None))
        if getattr(rec, "dialed_in", False):
            age = self._dialin_age_text(rec.method_id)
            label = QApplication.translate("tilauscope_brew", "✓ your dial-in")
            chip = _make_chip(f"{label} · {age}" if age else label, THEME["SUCCESS"])
            chip.setToolTip(self._dialin_age_tooltip(rec.method_id))
            self.chip_row.addWidget(chip)
        elif getattr(rec, "setup_adjusted", False):
            mult, n = self.service.setup_offset_for(rec.method_id)
            if mult is not None:
                pct = abs(mult - 1.0) * 100.0
                word = (QApplication.translate("tilauscope_brew", "coarse")
                        if mult < 1.0 else QApplication.translate("tilauscope_brew", "fine"))
                chip = _make_chip(QApplication.translate(
                    "tilauscope_brew", "⌁ setup runs ~{p}% {w} — adjusted").format(
                        p=f"{pct:.0f}", w=word), THEME["ACCENT"])
                chip.setToolTip(QApplication.translate(
                    "tilauscope_brew",
                    "Learned from {n} dial-ins across your beans: they all needed a "
                    "correction in the same direction, so it is applied up front to a bean "
                    "you have not dialled in yet. This covers your whole setup — grinder, "
                    "water, palate and technique — not the grinder alone.").format(n=n))
                self.chip_row.addWidget(chip)
        if rec.ai_adjusted:
            chips.append((QApplication.translate("tilauscope_brew", "✦ AI-refined"), THEME["SUCCESS"]))
        for text, color in chips:
            self.chip_row.addWidget(_make_chip(text, color))
        self.chip_row.addStretch(1)

        # ── protocol step rows ──
        _clear_layout(self.steps_lay)
        self.step_rows: list[_StepRow] = []
        for s in rec.steps:
            tgt = f"{s.target_g:.0f} g" if s.target_g > 0 else ""
            row = _StepRow(self._fmt_time(s.at_s), _step_text(s.label_key, s.params), tgt)
            self.step_rows.append(row)
            self.steps_lay.addWidget(row)
        self.steps_lay.addStretch(1)

        # ── did the last setting change do anything? (from the journal, in memory) ──
        self._refresh_previous_try()

        # ── diagnostics (folded) ──
        self.diagnostics.set_notes(rec.notes)


    # ── frameless: drag + center + cleanup ──
    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(150, self._recenter)  # async center (frameless on macOS)

    def _recenter(self) -> None:
        # Centre on the host window: BeanCave when visible, Artisan otherwise.
        ref = None
        try:
            if self._beancave is not None and self._beancave.window().isVisible():
                ref = self._beancave.window().geometry()
        except (AttributeError, RuntimeError):
            ref = None
        if ref is None:
            ref = self.aw.window().geometry() if (self.aw and self.aw.window()) else self.screen().availableGeometry()
        self.move(ref.center() - self.rect().center())

    # These three chain to QDialog when the gesture is not a title-bar drag,
    # so the window-drag handler does not swallow events meant for child widgets.
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 50:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(e)

    def closeEvent(self, e) -> None:
        self._stop_brew()
        self._disconnect_scale_state()
        sm = self._scale_mgr()
        if sm is not None and self._we_connected_scale:
            try:
                sm.disconnect_scale1_signal.emit()
            except Exception:  # noqa: BLE001
                pass
        self._disconnect_ai()
        super().closeEvent(e)