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

# ABOUT
# TilauScope Alarm Editor — rule-sentence editor with optional phase bucketing.
# AlarmSet (signal-based) bridges to qmc.alarm* via QmcAlarmAdapter, using stable IDs for guard/negguard refs.

import json
import logging
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Final, TYPE_CHECKING

from PyQt6.QtCore import (
    QObject, pyqtSignal, pyqtSlot, Qt, QPoint, QSettings, QMimeData, QTimer,
)
from PyQt6.QtGui import QColor, QCloseEvent, QDrag
from tilauscope.theme_qss import apply_tilau_theme, base_qss
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QFrame, QLabel, QPushButton, QScrollArea,
    QComboBox, QLineEdit, QTimeEdit, QAbstractSpinBox, QSpinBox, QMenu,
    QVBoxLayout, QHBoxLayout, QGraphicsOpacityEffect,
)

from tilauscope.tilauscope_types import THEME, show_styled_message
from tilauscope.ai_service import AITask
from tilauscope.ai_float_panel import AIFloatPanel

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401

_log: Final[logging.Logger] = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────────
# Event model (clean, device-agnostic)
# ───────────────────────────────────────────────────────────────────────────
# `from_event` in the clean record is the MENU INDEX (visual order below),
# not the raw qmc.alarmtime value. The adapter maps menu-index <-> qmc value
# through qmc.menuidx2alarmtime / qmc.alarmtime2menuidx.

class FromEvent(IntEnum):
    ON        = 0
    START     = 1
    CHARGE    = 2
    TP        = 3
    DRY_END   = 4
    FC_START  = 5
    FC_END    = 6
    SC_START  = 7
    SC_END    = 8
    DROP      = 9
    COOL_END  = 10
    IF_ALARM  = 11   # conditional: no time anchor, fires relative to a guard


def from_event_label(ev: int) -> str:
    """Translated label for a from-event menu index."""
    return {
        FromEvent.ON:       QApplication.translate('Label', 'ON'),
        FromEvent.START:    QApplication.translate('Label', 'START'),
        FromEvent.CHARGE:   QApplication.translate('Label', 'CHARGE'),
        FromEvent.TP:       QApplication.translate('Label', 'TP'),
        FromEvent.DRY_END:  QApplication.translate('Label', 'DRY END'),
        FromEvent.FC_START: QApplication.translate('Label', 'FC START'),
        FromEvent.FC_END:   QApplication.translate('Label', 'FC END'),
        FromEvent.SC_START: QApplication.translate('Label', 'SC START'),
        FromEvent.SC_END:   QApplication.translate('Label', 'SC END'),
        FromEvent.DROP:     QApplication.translate('Label', 'DROP'),
        FromEvent.COOL_END: QApplication.translate('ComboBox', 'COOL END'),
        FromEvent.IF_ALARM: QApplication.translate('ComboBox', 'If Alarm'),
    }.get(int(ev), '?')


# ───────────────────────────────────────────────────────────────────────────
# Roast phases (derived from from_event — no stored grouping metadata)
# ───────────────────────────────────────────────────────────────────────────

class Phase(IntEnum):
    SETUP       = 0   # ON, START
    DRYING      = 1   # CHARGE, TP
    MAILLARD    = 2   # DRY END
    DEVELOPMENT = 3   # FC START..SC END
    FINISH      = 4   # DROP, COOL END
    CONDITIONAL = 5   # IF_ALARM with unresolved parent (fallback bucket)


PHASE_ORDER: Final[tuple[Phase, ...]] = (
    Phase.SETUP, Phase.DRYING, Phase.MAILLARD,
    Phase.DEVELOPMENT, Phase.FINISH, Phase.CONDITIONAL,
)

# Accent colour per phase (Catppuccin Mocha; THEME has no per-phase keys).
PHASE_COLOR: Final[dict[Phase, str]] = {
    Phase.SETUP:       '#9399B2',  # overlay2
    Phase.DRYING:      '#FAB387',  # peach
    Phase.MAILLARD:    '#F9E2AF',  # yellow
    Phase.DEVELOPMENT: '#A6E3A1',  # green
    Phase.FINISH:      '#89B4FA',  # blue
    Phase.CONDITIONAL: '#F5C2E7',  # pink
}

_EVENT_PHASE: Final[dict[int, Phase]] = {
    FromEvent.ON: Phase.SETUP, FromEvent.START: Phase.SETUP,
    FromEvent.CHARGE: Phase.DRYING, FromEvent.TP: Phase.DRYING,
    FromEvent.DRY_END: Phase.MAILLARD,
    FromEvent.FC_START: Phase.DEVELOPMENT, FromEvent.FC_END: Phase.DEVELOPMENT,
    FromEvent.SC_START: Phase.DEVELOPMENT, FromEvent.SC_END: Phase.DEVELOPMENT,
    FromEvent.DROP: Phase.FINISH, FromEvent.COOL_END: Phase.FINISH,
}


def phase_label(p: Phase) -> str:
    """Translated phase label."""
    return {
        Phase.SETUP:       QApplication.translate('Tab', 'Setup'),
        Phase.DRYING:      QApplication.translate('Label', 'Drying'),
        Phase.MAILLARD:    QApplication.translate('Label', 'Maillard'),
        Phase.DEVELOPMENT: QApplication.translate('Label', 'Development'),
        Phase.FINISH:      QApplication.translate('Textbox', 'Finish'),
        Phase.CONDITIONAL: QApplication.translate('tilauscope_alarms', 'Conditional'),
    }.get(p, '?')


# ───────────────────────────────────────────────────────────────────────────
# Condition operators
# ───────────────────────────────────────────────────────────────────────────

COND_SYMBOLS: Final[tuple[str, ...]] = ('<', '>', '=', '\u2260')  # qmc.alarmcond order


# ───────────────────────────────────────────────────────────────────────────
# Action model
# ───────────────────────────────────────────────────────────────────────────
# `action` keeps the qmc convention: -1 = none, 0..28 as defined by Artisan +
# TilauScope extensions (26 Airwave, 27 Ambient, 28 kernel).
# `arg` is the single Artisan alarm string: it doubles as the action argument
# (slider value, pop-up message, external command) AND the human description.
# There is no separate description field in the Artisan data model.

class Action(IntEnum):
    NONE              = -1
    POPUP             = 0
    CALL_PROGRAM      = 1
    EVENT_BUTTON      = 2
    SLIDER_0          = 3
    SLIDER_1          = 4
    SLIDER_2          = 5
    SLIDER_3          = 6
    START             = 7
    DRY_END           = 8
    FC_START          = 9
    FC_END            = 10
    SC_START          = 11
    SC_END            = 12
    DROP              = 13
    COOL_END          = 14
    OFF               = 15
    CHARGE            = 16
    RAMPSOAK_ON       = 17
    RAMPSOAK_OFF      = 18
    PID_ON            = 19
    PID_OFF           = 20
    SV                = 21
    PLAYBACK_ON       = 22
    PLAYBACK_OFF      = 23
    SET_CANVAS_COLOR  = 24
    RESET_CANVAS_COLOR = 25
    AIRWAVE           = 26   # TILAU
    AMBIENT           = 27   # TILAU
    KERNEL            = 28   # TILAU

# Actions whose `arg` is a free-form payload worth surfacing in the sentence.
_ARG_BEARING_ACTIONS: Final[frozenset[int]] = frozenset({
    Action.POPUP, Action.CALL_PROGRAM, Action.EVENT_BUTTON,
    Action.SLIDER_0, Action.SLIDER_1, Action.SLIDER_2, Action.SLIDER_3,
    Action.SV, Action.SET_CANVAS_COLOR,
    Action.AIRWAVE, Action.AMBIENT, Action.KERNEL,
})

# Slider actions map to the four configurable event types (etypesf 0..3).
_SLIDER_ACTIONS: Final[frozenset[int]] = frozenset({
    Action.SLIDER_0, Action.SLIDER_1, Action.SLIDER_2, Action.SLIDER_3,
})


def action_takes_arg(action: int) -> bool:
    """True when the action carries a meaningful payload in `arg`."""
    return action in _ARG_BEARING_ACTIONS


# ───────────────────────────────────────────────────────────────────────────
# Clean alarm record
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class Alarm:
    """Device-agnostic alarm record. `aid` is a stable in-set identity used
    for guard/negguard references, independent of list position."""
    aid: int
    enabled: bool = True
    from_event: int = FromEvent.CHARGE   # menu index (FromEvent)
    offset: int = 0                       # seconds after the anchor
    source: int = -3                      # qmc convention: -3.. (-3 = none)
    cond: int = 1                         # index into COND_SYMBOLS (1 = '>')
    value: float = 0.0
    action: int = Action.NONE             # qmc convention
    arg: str = ''                         # single Artisan string (arg + label)
    beep: bool = False
    guard_aid: int | None = None          # "If Alarm" reference (by aid)
    negguard_aid: int | None = None       # "But Not" reference (by aid)
    fired_idx: int = -1                   # qmc.alarmstate convention: -1 = not
                                           # fired, else index into qmc.timex

    @property
    def is_conditional(self) -> bool:
        return int(self.from_event) == FromEvent.IF_ALARM

    @property
    def is_fired(self) -> bool:
        return self.fired_idx != -1


# ───────────────────────────────────────────────────────────────────────────
# AlarmSet — single source of truth
# ───────────────────────────────────────────────────────────────────────────

class AlarmSet(QObject):
    """Ordered collection of Alarm records. The UI subscribes to the signals
    below and re-renders only what changed — never reads qmc directly.

    Signals:
        modelReset()          full reload; rebuild everything
        rowInserted(int)      a row was inserted at this index
        rowRemoved(int)       the row at this index was removed
        rowChanged(int)       a field of the row at this index changed
        rowsReordered()       list order changed (DnD); rebuild order only
    """

    modelReset    = pyqtSignal()
    rowInserted   = pyqtSignal(int)
    rowRemoved    = pyqtSignal(int)
    rowChanged    = pyqtSignal(int)
    rowsReordered = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[Alarm] = []
        self._next_aid: int = 1

    # ── identity ──────────────────────────────────────────────────────────

    def _alloc_aid(self) -> int:
        aid = self._next_aid
        self._next_aid += 1
        return aid

    # ── access ────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def rows(self) -> list[Alarm]:
        """Live ordered list (do not mutate order directly — use move())."""
        return self._rows

    def at(self, index: int) -> Alarm | None:
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def by_aid(self, aid: int | None) -> Alarm | None:
        if aid is None:
            return None
        return next((a for a in self._rows if a.aid == aid), None)

    def index_of(self, aid: int) -> int:
        for i, a in enumerate(self._rows):
            if a.aid == aid:
                return i
        return -1

    def display_number(self, aid: int) -> int:
        """1-based position for UI labels (#1, #2 ...)."""
        return self.index_of(aid) + 1

    # ── bulk load (adapter -> set) ────────────────────────────────────────

    def load(self, records: list[Alarm]) -> None:
        """Replace the whole set. aids are taken as-is from the adapter."""
        self._rows = list(records)
        self._next_aid = max((a.aid for a in self._rows), default=0) + 1
        self.modelReset.emit()

    # ── field mutation ────────────────────────────────────────────────────

    def set_field(self, aid: int, name: str, value: object) -> None:
        """Update one field of one alarm and notify. Unknown/equal values
        are no-ops (keeps the real-time path quiet)."""
        a = self.by_aid(aid)
        if a is None or not hasattr(a, name):
            return
        if getattr(a, name) == value:
            return
        setattr(a, name, value)
        self.rowChanged.emit(self.index_of(aid))

    def toggle_enabled(self, aid: int) -> None:
        a = self.by_aid(aid)
        if a is not None:
            self.set_field(aid, 'enabled', not a.enabled)

    def toggle_beep(self, aid: int) -> None:
        a = self.by_aid(aid)
        if a is not None:
            self.set_field(aid, 'beep', not a.beep)

    # ── structural mutation ───────────────────────────────────────────────

    def add(self, template: Alarm | None = None) -> int:
        """Append a new alarm (optionally cloned from `template`). Returns aid."""
        a = self._clone_or_default(template)
        self._rows.append(a)
        self.rowInserted.emit(len(self._rows) - 1)
        return a.aid

    def insert_below(self, ref_aid: int, template: Alarm | None = None) -> int:
        idx = self.index_of(ref_aid)
        if idx < 0:
            return self.add(template)
        a = self._clone_or_default(template)
        self._rows.insert(idx + 1, a)
        self.rowInserted.emit(idx + 1)
        return a.aid

    def remove(self, aid: int) -> None:
        idx = self.index_of(aid)
        if idx < 0:
            return
        self._rows.pop(idx)
        # Detach dangling references to the removed alarm.
        for other in self._rows:
            if other.guard_aid == aid:
                other.guard_aid = None
            if other.negguard_aid == aid:
                other.negguard_aid = None
        self.rowRemoved.emit(idx)

    def move(self, src: int, dst: int) -> None:
        """Reorder by position (DnD in flat mode). References stay valid
        because they are aid-based, not index-based."""
        n = len(self._rows)
        if not (0 <= src < n) or not (0 <= dst < n) or src == dst:
            return
        a = self._rows.pop(src)
        self._rows.insert(dst, a)
        self.rowsReordered.emit()

    def _clone_or_default(self, template: Alarm | None) -> Alarm:
        aid = self._alloc_aid()
        if template is None:
            return Alarm(aid=aid)
        return Alarm(
            aid=aid, enabled=template.enabled, from_event=template.from_event,
            offset=template.offset, source=template.source, cond=template.cond,
            value=template.value, action=template.action, arg=template.arg,
            beep=template.beep,
            guard_aid=template.guard_aid, negguard_aid=template.negguard_aid,
        )

    # ── phase resolution ──────────────────────────────────────────────────

    def phase_of(self, alarm: Alarm) -> Phase:
        """Bucket an alarm by roast phase. Conditional alarms inherit the
        phase of their resolved parent (walking the guard chain)."""
        if not alarm.is_conditional:
            return _EVENT_PHASE.get(int(alarm.from_event), Phase.CONDITIONAL)
        parent = self._resolve_parent(alarm)
        if parent is None or parent is alarm:
            return Phase.CONDITIONAL
        return self.phase_of(parent)

    def _resolve_parent(self, alarm: Alarm) -> Alarm | None:
        """Follow guard/negguard up to the first non-conditional ancestor."""
        seen: set[int] = set()
        cur: Alarm | None = alarm
        while cur is not None and cur.aid not in seen:
            seen.add(cur.aid)
            ref = cur.guard_aid if cur.guard_aid is not None else cur.negguard_aid
            nxt = self.by_aid(ref)
            if nxt is None:
                return None
            if not nxt.is_conditional:
                return nxt
            cur = nxt
        return None

    def grouped_by_phase(self) -> list[tuple[Phase, list[Alarm]]]:
        """Phase buckets in roast order. Within a bucket, original list order
        is preserved (callers may sort by offset if desired)."""
        buckets: dict[Phase, list[Alarm]] = {p: [] for p in PHASE_ORDER}
        for a in self._rows:
            buckets[self.phase_of(a)].append(a)
        return [(p, buckets[p]) for p in PHASE_ORDER if buckets[p]]

    # ── validation ────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return human-readable warnings (dangling refs, cycles, self-refs)."""
        warnings: list[str] = []
        for a in self._rows:
            num = self.display_number(a.aid)
            for ref_name, ref in (('If Alarm', a.guard_aid),
                                  ('But Not', a.negguard_aid)):
                if ref is not None and self.by_aid(ref) is None:
                    warnings.append(
                        QApplication.translate('tilauscope_alarms', 'Alarm #{0}: dangling {1} reference')
                        .format(num, ref_name))
            if a.guard_aid == a.aid or a.negguard_aid == a.aid:
                warnings.append(
                    QApplication.translate('tilauscope_alarms', 'Alarm #{0}: references itself').format(num))
            if a.is_conditional and a.guard_aid is None and a.negguard_aid is None:
                warnings.append(
                    QApplication.translate('tilauscope_alarms', 'Alarm #{0}: conditional without a guard')
                    .format(num))
            # The time criterion is gated by offset > 0; with offset 0 and no
            # sensor condition there is nothing left to fire the alarm.
            if a.offset == 0 and a.source == -3 and a.action != Action.NONE:
                warnings.append(
                    QApplication.translate('tilauscope_alarms', 'Alarm #{0}: never fires (offset 0 with no condition)')
                    .format(num))
        return warnings


# ───────────────────────────────────────────────────────────────────────────
# QmcAlarmAdapter — qmc.alarm* parallel lists <-> AlarmSet
# ───────────────────────────────────────────────────────────────────────────

class QmcAlarmAdapter:
    """The only component that touches qmc.alarm* lists and Artisan-specific
    codecs (alarmtime menu mapping, source list, etypesf). Keeps AlarmSet and
    the UI fully device-agnostic. A future FileAlarmAdapter would implement the
    same load()/save()/source_labels() surface against an .alrm/.alog file."""

    # qmc.alarmtime carries Artisan's internal event codes; the dialog maps
    # them through these two qmc dicts. We round-trip via the menu index.
    def __init__(self, aw: 'ApplicationWindow') -> None:
        self.aw = aw

    @property
    def qmc(self):  # noqa: ANN201 - artisan type
        return self.aw.qmc

    # ── load: qmc -> records ──────────────────────────────────────────────

    def load(self) -> list[Alarm]:
        qmc = self.qmc
        n = len(qmc.alarmtemperature)
        # First pass: build records with positional aids = index + 1.
        records: list[Alarm] = []
        for i in range(n):
            records.append(Alarm(
                aid=i + 1,
                enabled=bool(self._get(qmc.alarmflag, i, 1)),
                from_event=int(qmc.alarmtime2menuidx[self._get(qmc.alarmtime, i, -1)]),
                offset=max(0, int(self._get(qmc.alarmoffset, i, 0))),
                source=int(self._get(qmc.alarmsource, i, 1)),
                cond=int(self._get(qmc.alarmcond, i, 1)),
                value=float(self._get(qmc.alarmtemperature, i, 0.0)),
                action=int(self._get(qmc.alarmaction, i, Action.NONE)),
                arg=str(self._get(qmc.alarmstrings, i, '')),
                beep=bool(self._get(qmc.alarmbeep, i, 0)),
                fired_idx=int(self._get(qmc.alarmstate, i, -1)),
            ))
        # Second pass: convert guard/negguard indices -> aids.
        for i, rec in enumerate(records):
            g = int(self._get(qmc.alarmguard, i, -1))
            ng = int(self._get(qmc.alarmnegguard, i, -1))
            rec.guard_aid = records[g].aid if 0 <= g < n else None
            rec.negguard_aid = records[ng].aid if 0 <= ng < n else None
        return records

    # ── save: set -> qmc ──────────────────────────────────────────────────

    def save(self, alarms: AlarmSet) -> None:
        qmc = self.qmc
        rows = alarms.rows
        aid_to_index = {a.aid: i for i, a in enumerate(rows)}

        qmc.alarmflag        = [1 if a.enabled else 0 for a in rows]
        qmc.alarmguard       = [aid_to_index.get(a.guard_aid, -1) for a in rows]
        qmc.alarmnegguard    = [aid_to_index.get(a.negguard_aid, -1) for a in rows]
        qmc.alarmtime        = [int(qmc.menuidx2alarmtime[int(a.from_event)]) for a in rows]
        qmc.alarmoffset      = [max(0, int(a.offset)) for a in rows]
        qmc.alarmcond        = [int(a.cond) for a in rows]
        qmc.alarmsource      = [int(a.source) for a in rows]
        qmc.alarmtemperature = [float(a.value) for a in rows]
        qmc.alarmaction      = [int(a.action) for a in rows]
        qmc.alarmbeep        = [1 if a.beep else 0 for a in rows]
        qmc.alarmstrings     = [a.arg for a in rows]
        # Fired state travels with the row (by aid), same convention as qmc:
        # -1 = not fired, else index into qmc.timex. A freshly added/duplicated
        # row defaults to -1 (never inherited from a template), so only rows
        # that were actually live when the dialog opened can carry a fired mark.
        qmc.alarmstate       = [int(a.fired_idx) for a in rows]

    @staticmethod
    def _get(lst: list, i: int, default: object) -> object:
        return lst[i] if i < len(lst) else default

    # ── codecs / labels for the UI ────────────────────────────────────────

    def source_labels(self) -> list[str]:
        """Source combo entries; UI index maps to qmc value as index - 3."""
        from artisanlib.util import deltaLabelUTF8  # noqa: PLC0415
        qmc = self.qmc
        extra: list[str] = []
        for j in range(len(qmc.extradevices)):
            extra.append(qmc.device_name_subst(qmc.extraname1[j]))
            extra.append(qmc.device_name_subst(qmc.extraname2[j]))
        return [
            '',
            deltaLabelUTF8 + qmc.device_name_subst(self.aw.ETname),
            deltaLabelUTF8 + qmc.device_name_subst(self.aw.BTname),
            qmc.device_name_subst(self.aw.ETname),
            qmc.device_name_subst(self.aw.BTname),
        ] + extra

    def source_label(self, source_value: int) -> str:
        """Human label for a qmc source value (-3 .. N)."""
        labels = self.source_labels()
        idx = source_value + 3
        return labels[idx] if 0 <= idx < len(labels) else '?'

    def action_labels(self) -> list[str]:
        """Action combo entries (index 0 = none); UI index maps to action - 1."""
        qmc = self.qmc
        return [
            '',
            QApplication.translate('ComboBox', 'Pop Up'),
            QApplication.translate('ComboBox', 'Call Program'),
            QApplication.translate('ComboBox', 'Event Button'),
            QApplication.translate('Label', 'Slider') + ' ' + qmc.etypesf(0),
            QApplication.translate('Label', 'Slider') + ' ' + qmc.etypesf(1),
            QApplication.translate('Label', 'Slider') + ' ' + qmc.etypesf(2),
            QApplication.translate('Label', 'Slider') + ' ' + qmc.etypesf(3),
            QApplication.translate('Label', 'START'),
            QApplication.translate('Label', 'DRY END'),
            QApplication.translate('Label', 'FC START'),
            QApplication.translate('Label', 'FC END'),
            QApplication.translate('Label', 'SC START'),
            QApplication.translate('Label', 'SC END'),
            QApplication.translate('Label', 'DROP'),
            QApplication.translate('ComboBox', 'COOL END'),
            QApplication.translate('Label', 'OFF'),
            QApplication.translate('Label', 'CHARGE'),
            QApplication.translate('ComboBox', 'RampSoak ON'),
            QApplication.translate('ComboBox', 'RampSoak OFF'),
            QApplication.translate('ComboBox', 'PID ON'),
            QApplication.translate('ComboBox', 'PID OFF'),
            QApplication.translate('Label', 'SV'),
            QApplication.translate('ComboBox', 'Playback ON'),
            QApplication.translate('ComboBox', 'Playback OFF'),
            QApplication.translate('ComboBox', 'Set Canvas Color'),
            QApplication.translate('ComboBox', 'Reset Canvas Color'),
            QApplication.translate('Combobox', 'Difluid Airwave command'),
            QApplication.translate('Combobox', 'TilauScope Ambient command'),
            QApplication.translate('Combobox', 'TilauScope command'),
        ]

    def action_label(self, action_value: int) -> str:
        """Short label for an action value (-1 .. 28). For sliders the label
        already embeds the event type via etypesf."""
        labels = self.action_labels()
        idx = action_value + 1
        return labels[idx] if 0 <= idx < len(labels) else '?'

    def event_button_label(self, arg: str) -> str:
        """Resolve an Event Button action argument (1-based button number)
        to the button's rendered content, for display alongside the number."""
        try:
            idx = int(str(arg).strip()) - 1
        except (ValueError, TypeError):
            return ''
        labels = getattr(self.aw, 'extraeventslabels', [])
        if not (0 <= idx < len(labels)):
            return ''
        raw = labels[idx]
        try:
            text = self.aw.substButtonLabel(
                idx, raw, self.aw.extraeventstypes[idx],
                self.aw.extraeventsvalues[idx])
        except Exception:  # noqa: BLE001 - fall back to the raw label
            text = raw
        return str(text or '').replace(chr(10), ' ').strip()


# ───────────────────────────────────────────────────────────────────────────
# AlarmPresetStore — named, unlimited alarm programmes
# ───────────────────────────────────────────────────────────────────────────
# Reinvents Artisan's "Alarm Sets" (fixed ALARMSET_COUNT slots, tucked in an
# Expert-only Management tab) as unlimited named presets. A preset is a full,
# qmc-independent snapshot of AlarmSet.rows (same records the QmcAlarmAdapter
# would produce) so it round-trips through guard/negguard aids untouched.
# Persisted as one JSON blob in QSettings, alongside this dialog's other
# settings (geometry, group-by-phase) — no extra file to manage.

class AlarmPresetStore:

    _SETTINGS_KEY: Final[str] = 'TilauAlarmPresets'

    def names(self) -> list[str]:
        return sorted(self._read().keys(), key=str.lower)

    def save(self, name: str, rows: list[Alarm]) -> None:
        data = self._read()
        data[name] = [self._to_dict(a) for a in rows]
        self._write(data)

    def load(self, name: str) -> list[Alarm] | None:
        raw = self._read().get(name)
        if raw is None:
            return None
        try:
            return [Alarm(**d) for d in raw]
        except TypeError:
            _log.warning('AlarmPresetStore: preset %r has an incompatible shape', name)
            return None

    def delete(self, name: str) -> None:
        data = self._read()
        if data.pop(name, None) is not None:
            self._write(data)

    def rename(self, old: str, new: str) -> None:
        data = self._read()
        if old in data and old != new:
            data[new] = data.pop(old)
            self._write(data)

    @staticmethod
    def _to_dict(a: Alarm) -> dict:
        d = asdict(a)
        d['fired_idx'] = -1  # a preset is a programme, never a live roast state
        return d

    @staticmethod
    def _read() -> dict[str, list[dict]]:
        raw = QSettings().value(AlarmPresetStore._SETTINGS_KEY, '', type=str)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            _log.warning('AlarmPresetStore: could not parse stored presets, ignoring')
            return {}

    @staticmethod
    def _write(data: dict[str, list[dict]]) -> None:
        QSettings().setValue(AlarmPresetStore._SETTINGS_KEY, json.dumps(data))


# ═══════════════════════════════════════════════════════════════════════════
# UI LAYER — rule-sentence editor (vue A) with optional phase bucketing (B)
# ═══════════════════════════════════════════════════════════════════════════
# The UI talks to AlarmSet only through its signals/methods. QmcAlarmAdapter is
# used once for load/save and for combo label sources. No widget touches qmc.

# ── Chip palette (Catppuccin Mocha; THEME has no per-category keys) ─────────
_CHIP_COLOR: Final[dict[str, str]] = {
    'time':   '#89B4FA',  # blue   — event + offset
    'cond':   '#CBA6F7',  # mauve  — sensor condition
    'action': '#94E2D5',  # teal   — actuator action
    'ref':    '#F5C2E7',  # pink   — guard reference (conditional)
    'safe':   '#F38BA8',  # red    — pop-up / off
    'ghost':  '#6C7086',  # overlay— "add" affordance
}
_CRUST:   Final[str] = THEME['CRUST']
_SURF1:   Final[str] = THEME['SURFACE1']
_OVERLAY: Final[str] = THEME['OVERLAY0']


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Return an rgba() string for stylesheet backgrounds with alpha."""
    c = QColor(hex_color)
    return f'rgba({c.red()},{c.green()},{c.blue()},{alpha:.2f})'


def _chip_css(color: str, ghost: bool = False) -> str:
    """Stylesheet for a chip button of a given category colour."""
    border = (f'1px dashed {_hex_to_rgba(color, 0.45)}' if ghost
              else f'1px solid {_hex_to_rgba(color, 0.32)}')
    return (
        'QPushButton {'
        f'  background: {_hex_to_rgba(color, 0.14)};'
        f'  color: {color};'
        f'  border: {border};'
        '   border-radius: 6px;'
        "   font-size: 12px;"
        '   padding: 2px 9px; text-align: left;'
        '}'
        f'QPushButton:hover {{ background: {_hex_to_rgba(color, 0.24)}; }}'
    )


def _action_chip_color(action: int) -> str:
    """Category colour for an action chip."""
    if action in (Action.POPUP, Action.OFF):
        return _CHIP_COLOR['safe']
    return _CHIP_COLOR['action']


# ── Drag-and-drop reorder ───────────────────────────────────────────────────
_ALARM_MIME: Final[str] = 'application/x-tilau-alarm-aid'

# Representative anchor used when an alarm is dropped into a phase bucket.
_PHASE_REP: Final[dict[Phase, int]] = {
    Phase.SETUP:       FromEvent.ON,
    Phase.DRYING:      FromEvent.CHARGE,
    Phase.MAILLARD:    FromEvent.DRY_END,
    Phase.DEVELOPMENT: FromEvent.FC_START,
    Phase.FINISH:      FromEvent.DROP,
}


class _GripHandle(QLabel):
    """Drag handle. Starts a row drag once the pointer moves past a small
    threshold; never selects, never reflows."""

    def __init__(self, on_drag_start, parent: QWidget | None = None) -> None:
        super().__init__('\u283F', parent)  # braille 6-dot grip glyph
        self._on_drag_start = on_drag_start
        self._press: QPoint | None = None
        self.setFixedWidth(16)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(QApplication.translate('tilauscope_alarms', 'Drag to reorder'))
        self.setStyleSheet(
            f"color: {_SURF1}; font-size: 14px; border: none; background: transparent;")

    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press = ev.position().toPoint()
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:  # type: ignore[override]
        if (self._press is not None
                and (ev.position().toPoint() - self._press).manhattanLength() > 6):
            self._press = None
            self._on_drag_start()
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        self._press = None
        ev.accept()


class _AlarmListBody(QWidget):
    """Scroll body that accepts alarm drops. Reports drops to the dialog via
    the on_drop callback; draws a thin insertion indicator while dragging."""

    def __init__(self, on_drop, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_drop = on_drop  # callable(src_aid: int, global_y: int)
        self.setAcceptDrops(True)
        self._indicator = QFrame(self)
        self._indicator.setFixedHeight(2)
        self._indicator.setStyleSheet(
            f"background: {THEME['ACCENT']}; border: none;")
        self._indicator.hide()

    def dragEnterEvent(self, ev) -> None:  # type: ignore[override]
        if ev.mimeData().hasFormat(_ALARM_MIME):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:  # type: ignore[override]
        if ev.mimeData().hasFormat(_ALARM_MIME):
            y = ev.position().toPoint().y()
            self._indicator.setGeometry(0, max(0, y - 1), self.width(), 2)
            self._indicator.show()
            self._indicator.raise_()
            ev.acceptProposedAction()

    def dragLeaveEvent(self, ev) -> None:  # type: ignore[override]
        del ev
        self._indicator.hide()

    def dropEvent(self, ev) -> None:  # type: ignore[override]
        self._indicator.hide()
        if ev.mimeData().hasFormat(_ALARM_MIME):
            try:
                src_aid = int(bytes(ev.mimeData().data(_ALARM_MIME)).decode())
            except (ValueError, TypeError):
                return
            gy = self.mapToGlobal(ev.position().toPoint()).y()
            self._on_drop(src_aid, gy)
            ev.acceptProposedAction()


# ───────────────────────────────────────────────────────────────────────────
# _Chip — a clickable sentence token
# ───────────────────────────────────────────────────────────────────────────

class _Chip(QPushButton):
    """A single editable chip. Clicking emits the parent row's edit request
    for the chip's cluster. `cluster` is one of: time, cond, action, ref."""

    def __init__(self, text: str, category: str, cluster: str,
                 ghost: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.cluster = cluster
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_chip_css(_CHIP_COLOR.get(category, category), ghost))


def _kw(text: str) -> QLabel:
    """A non-interactive keyword label (when / if / → ...)."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {_OVERLAY};"
        f'font-size: 12px; border: none; background: transparent;')
    return lbl


# ───────────────────────────────────────────────────────────────────────────
# _AlarmRow — renders one alarm as a sentence of chips
# ───────────────────────────────────────────────────────────────────────────

class _AlarmRow(QFrame):
    """One alarm row. Re-renders on demand from the live Alarm record; emits
    edit/toggle/delete requests upward. Holds no state beyond the aid."""

    editRequested   = pyqtSignal(int, str, QPoint)  # aid, cluster, global anchor
    toggleEnable    = pyqtSignal(int)
    toggleBeep      = pyqtSignal(int)
    deleteRequested = pyqtSignal(int)
    rowClicked      = pyqtSignal(int)

    def __init__(self, aid: int, alarms: AlarmSet, adapter: 'QmcAlarmAdapter',
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.aid = aid
        self._alarms = alarms
        self._adapter = adapter
        self._selected = False
        self.setObjectName('alarmRow')
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(8, 6, 8, 6)
        self._lay.setSpacing(7)
        self.refresh()

    # ── selection visuals ─────────────────────────────────────────────────

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self._apply_frame_style()

    def _apply_frame_style(self) -> None:
        border = THEME['ACCENT'] if self._selected else THEME['BORDER']
        bg = THEME['BG'] if self._selected else THEME['SURFACE']
        self.setStyleSheet(
            f'#alarmRow {{ background: {bg}; border: 1px solid {border}; '
            f'border-radius: 8px; }}')

    # ── rendering ──────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Rebuild the chip sentence from the current record."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        a = self._alarms.by_aid(self.aid)
        if a is None:
            return

        self._lay.addWidget(_GripHandle(self._start_drag))
        self._lay.addWidget(self._enable_dot(a))
        num = QLabel(f'#{self._alarms.display_number(self.aid)}')
        num.setStyleSheet(
            f"color: {_OVERLAY};"
            f'font-size: 11px; border: none; background: transparent;')
        self._lay.addWidget(num)

        if a.is_conditional:
            self._render_conditional(a)
        else:
            self._render_standard(a)

        self._lay.addStretch(1)
        self._lay.addWidget(self._beep_btn(a))
        self._lay.addWidget(self._delete_btn())
        self._apply_frame_style()

    def _render_standard(self, a: Alarm) -> None:
        self._lay.addWidget(_kw(QApplication.translate('tilauscope_alarms', 'when')))
        self._lay.addWidget(self._chip(from_event_label(a.from_event), 'time', 'time'))
        self._lay.addWidget(self._chip(self._offset_text(a.offset), 'time', 'time'))
        # Optional sensor condition
        if a.source != -3:
            self._lay.addWidget(_kw(QApplication.translate('tilauscope_alarms', 'if')))
            self._lay.addWidget(self._chip(self._cond_text(a), 'cond', 'cond'))
        else:
            self._lay.addWidget(self._chip(
                '+ ' + QApplication.translate('tilauscope_alarms', 'condition'),
                'ghost', 'cond', ghost=True))
        self._render_action(a)

    def _render_conditional(self, a: Alarm) -> None:
        self._lay.addWidget(_kw(QApplication.translate('tilauscope_alarms', 'if')))
        self._lay.addWidget(self._chip(self._ref_text(a), 'ref', 'ref'))
        self._lay.addWidget(self._chip(self._offset_text(a.offset), 'time', 'ref'))
        if a.source != -3:
            self._lay.addWidget(_kw(QApplication.translate('tilauscope_alarms', 'and')))
            self._lay.addWidget(self._chip(self._cond_text(a), 'cond', 'cond'))
        self._render_action(a)

    def _render_action(self, a: Alarm) -> None:
        self._lay.addWidget(_kw('\u2192'))  # arrow
        if a.action == Action.NONE:
            self._lay.addWidget(self._chip(
                '+ ' + QApplication.translate('tilauscope_alarms', 'action'),
                'ghost', 'action', ghost=True))
            return
        label = self._adapter.action_label(a.action)
        if a.action == Action.EVENT_BUTTON:
            content = self._adapter.event_button_label(a.arg)
            if a.arg:
                label = f'{label} : {a.arg}'
            if content:
                label = f'{label} ({content})'
        elif action_takes_arg(a.action) and a.arg:
            sep = ' = ' if a.action in _SLIDER_ACTIONS else ' : '
            label = f'{label}{sep}{a.arg}'
        chip = _Chip(label, 'action', 'action')
        chip.setStyleSheet(_chip_css(_action_chip_color(a.action)))
        chip.clicked.connect(lambda: self._emit_edit('action', chip))
        self._lay.addWidget(chip)
        if a.enabled and a.is_fired:
            badge = self._fired_badge(a)
            if badge is not None:
                self._lay.addWidget(badge)

    # ── chip/button factories ─────────────────────────────────────────────

    def _chip(self, text: str, category: str, cluster: str,
              ghost: bool = False) -> _Chip:
        chip = _Chip(text, category, cluster, ghost=ghost)
        chip.clicked.connect(lambda: self._emit_edit(cluster, chip))
        return chip

    def _enable_dot(self, a: Alarm) -> QPushButton:
        # Tri-state: dim = disabled, plain dot = armed, dot + check = fired.
        fired = a.enabled and a.is_fired
        dot = QPushButton('✓' if fired else '')
        dot.setFixedSize(13, 13)
        dot.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dot.setCursor(Qt.CursorShape.PointingHandCursor)
        color = THEME['SUCCESS'] if a.enabled else _SURF1
        tip = QApplication.translate('tilauscope_alarms', 'Enable / disable')
        if fired:
            fired_text = self._fired_text(a)
            if fired_text:
                tip += '\n' + QApplication.translate(
                    'tilauscope_alarms', 'Fired at {0}').format(fired_text)
        dot.setToolTip(tip)
        dot.setStyleSheet(
            f'QPushButton {{ background: {color}; border: none; '
            f'border-radius: 6px; color: {_CRUST}; font-size: 8px; '
            f'font-weight: bold; padding: 0; }}')
        dot.clicked.connect(lambda: self.toggleEnable.emit(self.aid))
        return dot

    def _beep_btn(self, a: Alarm) -> QPushButton:
        # Emoji glyphs ignore CSS colour, so on/off is conveyed by the glyph
        # itself: bell vs bell-with-cancellation-stroke (muted).
        glyph = '\U0001F514' if a.beep else '\U0001F515'
        btn = QPushButton(glyph)
        btn.setFixedSize(24, 24)
        btn.setProperty('variant', 'icon')   # fixed size: no base padding
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(QApplication.translate('tilauscope_alarms', 'Beep on alarm')
                       if a.beep else
                       QApplication.translate('tilauscope_alarms', 'Beep off'))
        opacity = '1.0' if a.beep else '0.45'
        btn.setStyleSheet(
            f'QPushButton {{ background: transparent; border: none; '
            f'font-size: 13px; }}'
            f'QPushButton:hover {{ background: {_hex_to_rgba(THEME["ACCENT"], 0.12)}; '
            f'border-radius: 6px; }}')
        eff = QGraphicsOpacityEffect(btn)
        eff.setOpacity(float(opacity))
        btn.setGraphicsEffect(eff)
        btn.clicked.connect(lambda: self.toggleBeep.emit(self.aid))
        return btn

    def _delete_btn(self) -> QPushButton:
        btn = QPushButton('\u2715')
        btn.setFixedSize(22, 22)
        btn.setProperty('variant', 'icon')   # fixed size: no base padding
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f'QPushButton {{ background: transparent; color: {_SURF1}; '
            f'border: none; font-size: 13px; }}'
            f'QPushButton:hover {{ color: {THEME["CRITICAL"]}; }}')
        btn.clicked.connect(lambda: self.deleteRequested.emit(self.aid))
        return btn

    # ── text builders ─────────────────────────────────────────────────────

    @staticmethod
    def _offset_text(seconds: int) -> str:
        m, s = divmod(max(0, int(seconds)), 60)
        return f'+{m}:{s:02d}'

    def _fired_text(self, a: Alarm) -> str:
        """Elapsed roast time (mm:ss) at which this alarm fired, or ''."""
        timex = getattr(self._adapter.qmc, 'timex', [])
        if not (0 <= a.fired_idx < len(timex)):
            return ''
        m, s = divmod(max(0, int(timex[a.fired_idx])), 60)
        return f'{m}:{s:02d}'

    def _fired_badge(self, a: Alarm) -> QLabel | None:
        text = self._fired_text(a)
        if not text:
            return None
        lbl = QLabel('✓ ' + text)
        lbl.setToolTip(
            QApplication.translate('tilauscope_alarms', 'Fired at {0}').format(text))
        lbl.setStyleSheet(
            f"color: {THEME['SUCCESS']};"
            f'font-size: 11px; border: none; background: transparent;')
        return lbl

    def _cond_text(self, a: Alarm) -> str:
        src = self._adapter.source_label(a.source)
        op = COND_SYMBOLS[a.cond] if 0 <= a.cond < len(COND_SYMBOLS) else '?'
        val = f'{a.value:g}'
        return f'{src} {op} {val}'

    def _ref_text(self, a: Alarm) -> str:
        target = a.guard_aid if a.guard_aid is not None else a.negguard_aid
        not_fired = a.negguard_aid is not None
        if target is None:
            return QApplication.translate('tilauscope_alarms', '(no guard)')
        num = self._alarms.display_number(target)
        # Both branches spell the literal out: pylupdate6 reads the source, so a
        # key chosen first and translated afterwards is a string it never sees.
        verb = (QApplication.translate('tilauscope_alarms', 'not fired')
                if not_fired
                else QApplication.translate('tilauscope_alarms', 'fired'))
        return f'#{num} {verb}'

    # ── events ────────────────────────────────────────────────────────────

    def _emit_edit(self, cluster: str, chip: QWidget) -> None:
        anchor = chip.mapToGlobal(QPoint(0, chip.height()))
        self.editRequested.emit(self.aid, cluster, anchor)

    def _start_drag(self) -> None:
        """Begin a reorder drag carrying this row's stable aid."""
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_ALARM_MIME, str(self.aid).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.rowClicked.emit(self.aid)
        super().mousePressEvent(event)


# ───────────────────────────────────────────────────────────────────────────
# _ChipEditOverlay — floating editor, no layout reflow
# ───────────────────────────────────────────────────────────────────────────

class _ChipEditOverlay(QFrame):
    """Floating panel rendered as a child of the dialog and raised above the
    list (no reflow). Edits a single cluster of one alarm with live commit.
    Closes on Done / Esc / when another chip is clicked."""

    closed = pyqtSignal()

    def __init__(self, aid: int, cluster: str, alarms: AlarmSet,
                 adapter: 'QmcAlarmAdapter', parent: QWidget) -> None:
        super().__init__(parent)
        self.aid = aid
        self.cluster = cluster
        self._alarms = alarms
        self._adapter = adapter
        self._ref_aids: list[int] = []  # combo index -> aid (ref cluster)
        self.setObjectName('chipOverlay')
        self.setStyleSheet(
            f'#chipOverlay {{ background: {_CRUST}; '
            f'border: 1px solid {THEME["ACCENT"]}; border-radius: 9px; }}')
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 10, 12, 12)
        self._lay.setSpacing(7)
        self._build()

    # ── construction ──────────────────────────────────────────────────────

    def _build(self) -> None:
        a = self._alarms.by_aid(self.aid)
        if a is None:
            return
        title = {
            'time':   QApplication.translate('tilauscope_alarms', 'edit timing'),
            'cond':   QApplication.translate('tilauscope_alarms', 'edit condition'),
            'action': QApplication.translate('tilauscope_alarms', 'edit action'),
            'ref':    QApplication.translate('tilauscope_alarms', 'edit guard'),
        }.get(self.cluster, '')
        cap = QLabel(title.upper())
        cap.setProperty('variant', 'eyebrow')
        self._lay.addWidget(cap)

        if self.cluster == 'time':
            self._build_time(a)
        elif self.cluster == 'cond':
            self._build_cond(a)
        elif self.cluster == 'action':
            self._build_action(a)
        elif self.cluster == 'ref':
            self._build_ref(a)

        done = QPushButton(QApplication.translate('tilauscope_alarms', 'Done'))
        done.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        done.setProperty('variant', 'primary')
        done.clicked.connect(self._close)
        self._lay.addWidget(done)
        self.adjustSize()

    # ── cluster builders ──────────────────────────────────────────────────

    def _build_time(self, a: Alarm) -> None:
        events = [from_event_label(e) for e in range(len(FromEvent))]
        cb = self._combo(events, int(a.from_event))
        cb.currentIndexChanged.connect(
            lambda i: self._alarms.set_field(self.aid, 'from_event', int(i)))
        self._field(QApplication.translate('Label', 'from'), cb)
        self._field(QApplication.translate('tilauscope_alarms', 'offset'),
                    self._offset_edit(a))

    def _build_cond(self, a: Alarm) -> None:
        labels = self._adapter.source_labels()
        labels = [QApplication.translate('tilauscope_alarms', '(none)')
                  if not s else s for s in labels]
        src = self._combo(labels, a.source + 3)
        src.currentIndexChanged.connect(
            lambda i: self._alarms.set_field(self.aid, 'source', int(i) - 3))
        self._field(QApplication.translate('tilauscope_alarms', 'source'), src)

        op = self._combo(list(COND_SYMBOLS), a.cond)
        op.currentIndexChanged.connect(
            lambda i: self._alarms.set_field(self.aid, 'cond', int(i)))
        self._field(QApplication.translate('tilauscope_alarms', 'operator'), op)

        val = QLineEdit(f'{a.value:g}')
        val.setValidator(
            self._adapter.aw.createCLocaleDoubleValidator(-999.9, 999.9, 1, val))
        val.setStyleSheet(self._edit_css())
        val.textChanged.connect(self._commit_value)
        self._field(QApplication.translate('tilauscope_alarms', 'value'), val)

    def _build_action(self, a: Alarm) -> None:
        labels = self._adapter.action_labels()
        labels = [QApplication.translate('tilauscope_alarms', '(none)')
                  if not s else s for s in labels]
        cb = self._combo(labels, a.action + 1)
        cb.currentIndexChanged.connect(
            lambda i: self._alarms.set_field(self.aid, 'action', int(i) - 1))
        self._field(QApplication.translate('tilauscope_alarms', 'action'), cb)

        arg = QLineEdit(a.arg)
        arg.setStyleSheet(self._edit_css())
        arg.setPlaceholderText(
            QApplication.translate('tilauscope_alarms', 'value / message / command'))
        arg.textChanged.connect(
            lambda t: self._alarms.set_field(self.aid, 'arg', t))
        self._field(QApplication.translate('tilauscope_alarms', 'argument'), arg)

    def _build_ref(self, a: Alarm) -> None:
        modes = [QApplication.translate('tilauscope_alarms', 'fired'),
                 QApplication.translate('tilauscope_alarms', 'not fired')]
        mode = self._combo(modes, 1 if a.negguard_aid is not None else 0)
        self._field(QApplication.translate('tilauscope_alarms', 'when target'), mode)

        # Candidate guards = every other alarm.
        self._ref_aids = [o.aid for o in self._alarms.rows if o.aid != self.aid]
        items: list[str] = []
        for ref in self._ref_aids:
            num = self._alarms.display_number(ref)
            items.append(f'#{num}')
        cur = a.guard_aid if a.guard_aid is not None else a.negguard_aid
        cur_idx = self._ref_aids.index(cur) if cur in self._ref_aids else 0
        tgt = self._combo(items if items else ['—'], cur_idx)
        self._field(QApplication.translate('Label', 'target'), tgt)

        def _apply() -> None:
            if not self._ref_aids:
                return
            ref_aid = self._ref_aids[max(0, tgt.currentIndex())]
            if mode.currentIndex() == 1:  # not fired
                self._alarms.set_field(self.aid, 'guard_aid', None)
                self._alarms.set_field(self.aid, 'negguard_aid', ref_aid)
            else:
                self._alarms.set_field(self.aid, 'negguard_aid', None)
                self._alarms.set_field(self.aid, 'guard_aid', ref_aid)

        mode.currentIndexChanged.connect(lambda _i: _apply())
        tgt.currentIndexChanged.connect(lambda _i: _apply())

        self._field(QApplication.translate('tilauscope_alarms', 'offset'),
                    self._offset_edit(a))

    # ── small widget helpers ──────────────────────────────────────────────

    def _combo(self, items: list[str], current: int) -> QComboBox:
        cb = QComboBox()
        cb.addItems(items)
        cb.setCurrentIndex(current if 0 <= current < len(items) else 0)
        cb.setStyleSheet(self._edit_css())
        cb.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return cb

    def _offset_edit(self, a: Alarm) -> QTimeEdit:
        te = QTimeEdit()
        te.setDisplayFormat('mm:ss')
        te.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        te.setAlignment(Qt.AlignmentFlag.AlignRight)
        te.setTime(self._adapter.aw.time2QTime(max(0, a.offset)))
        te.setStyleSheet(self._edit_css())
        te.timeChanged.connect(
            lambda t: self._alarms.set_field(
                self.aid, 'offset',
                max(0, int(round(self._adapter.aw.QTime2time(t))))))
        return te

    def _commit_value(self, text: str) -> None:
        try:
            from artisanlib.util import comma2dot  # noqa: PLC0415
            self._alarms.set_field(self.aid, 'value', float(comma2dot(text)))
        except (ValueError, ImportError):
            pass

    def _field(self, label: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)
        lbl = QLabel(label)
        lbl.setMinimumWidth(64)
        lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']};"
            f'font-size: 11px; border: none; background: transparent;')
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        self._lay.addLayout(row)

    def _edit_css(self) -> str:
        return (
            f'QComboBox, QLineEdit, QTimeEdit {{ background: {THEME["BG"]}; '
            f'color: {THEME["TEXT"]}; border: 1px solid {_SURF1}; '
            f"border-radius: 6px; padding: 3px 8px;"
            f"font-size: 12px; }}"
            f'QComboBox QAbstractItemView {{ background: {THEME["BG"]}; '
            f'color: {THEME["TEXT"]}; selection-background-color: {THEME["ACCENT"]}; }}')

    # ── lifecycle ─────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self._close()
            return
        super().keyPressEvent(event)

    def _close(self) -> None:
        self.closed.emit()
        self.close()
        self.deleteLater()


# ───────────────────────────────────────────────────────────────────────────
# _NamePromptOverlay — floating text prompt (save-as / rename), same visual
# language as _ChipEditOverlay so preset management does not feel bolted on.
# ───────────────────────────────────────────────────────────────────────────

class _NamePromptOverlay(QFrame):

    accepted = pyqtSignal(str)
    closed = pyqtSignal()

    def __init__(self, title: str, initial: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName('namePromptOverlay')
        self.setStyleSheet(
            f'#namePromptOverlay {{ background: {_CRUST}; '
            f'border: 1px solid {THEME["ACCENT"]}; border-radius: 9px; }}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(7)

        cap = QLabel(title.upper())
        cap.setProperty('variant', 'eyebrow')
        lay.addWidget(cap)

        self._edit = QLineEdit(initial)
        self._edit.setStyleSheet(
            f'QLineEdit {{ background: {THEME["BG"]}; color: {THEME["TEXT"]}; '
            f'border: 1px solid {_SURF1}; border-radius: 6px; padding: 4px 8px; '
            f"font-size: 12px; }}")
        self._edit.selectAll()
        self._edit.returnPressed.connect(self._commit)
        lay.addWidget(self._edit)

        save = QPushButton(QApplication.translate('Button', 'Save'))
        save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        save.setProperty('variant', 'primary')
        save.clicked.connect(self._commit)
        lay.addWidget(save)
        self.adjustSize()

    def show_at(self, global_anchor: QPoint) -> None:
        parent = self.parentWidget()
        self.adjustSize()
        local = parent.mapFromGlobal(global_anchor)
        x = min(max(8, local.x()), parent.width() - self.width() - 8)
        y = min(local.y() + 4, parent.height() - self.height() - 8)
        self.move(x, y)
        self.show()
        self.raise_()
        self._edit.setFocus()

    def _commit(self) -> None:
        name = self._edit.text().strip()
        if name:
            self.accepted.emit(name)
        self._close()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self._close()
            return
        super().keyPressEvent(event)

    def _close(self) -> None:
        self.closed.emit()
        self.close()
        self.deleteLater()


# ───────────────────────────────────────────────────────────────────────────
# _PresetManagerDlg — rename / delete saved presets
# ───────────────────────────────────────────────────────────────────────────

class _PresetManagerDlg(QDialog):

    def __init__(self, store: AlarmPresetStore, parent: QWidget) -> None:
        super().__init__(parent)
        self._store = store
        self._rename_overlay: _NamePromptOverlay | None = None
        self.setWindowTitle(QApplication.translate('tilauscope_alarms', 'Manage presets'))
        self.setModal(True)
        self.setStyleSheet(base_qss() + f"QDialog {{ background: {THEME['BG']}; }}")
        self.resize(360, 320)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 14, 14, 14)
        self._lay.setSpacing(6)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(6)
        self.body_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        self._lay.addWidget(self.scroll, 1)

        close = QPushButton(QApplication.translate('Button', 'Close'))
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.accept)
        close.setStyleSheet(
            f"QPushButton {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 7px; padding: 6px 14px;"
            f"font-size: 11px; }}")
        self._lay.addWidget(close)

        self._rebuild()

    def _rebuild(self) -> None:
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        names = self._store.names()
        if not names:
            empty = QLabel(QApplication.translate('tilauscope_alarms', 'No presets saved yet'))
            empty.setStyleSheet(
                f"color: {THEME['SUBTEXT']};"
                f'font-size: 12px; border: none;')
            self.body_lay.addWidget(empty)
        for name in names:
            self.body_lay.addWidget(self._preset_row(name))
        self.body_lay.addStretch(1)

    def _preset_row(self, name: str) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f'QFrame {{ background: {THEME["SURFACE"]}; '
            f'border: 1px solid {THEME["BORDER"]}; border-radius: 8px; }}')
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        lbl = QLabel(name)
        lbl.setStyleSheet(
            f"color: {THEME['TEXT']};"
            f'font-size: 12px; border: none; background: transparent;')
        lay.addWidget(lbl, 1)

        rename = QPushButton('✎')
        rename.setFixedSize(22, 22)
        rename.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rename.setCursor(Qt.CursorShape.PointingHandCursor)
        rename.setToolTip(QApplication.translate('Button', 'Rename'))
        rename.setStyleSheet(
            f'QPushButton {{ background: transparent; color: {THEME["SUBTEXT"]}; '
            f'border: none; font-size: 13px; }}'
            f'QPushButton:hover {{ color: {THEME["ACCENT"]}; }}')
        rename.clicked.connect(lambda: self._start_rename(name, rename))
        lay.addWidget(rename)

        delete = QPushButton('✕')
        delete.setFixedSize(22, 22)
        delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setToolTip(QApplication.translate('Button', 'Delete'))
        delete.setStyleSheet(
            f'QPushButton {{ background: transparent; color: {THEME["SUBTEXT"]}; '
            f'border: none; font-size: 13px; }}'
            f'QPushButton:hover {{ color: {THEME["CRITICAL"]}; }}')
        delete.clicked.connect(lambda: self._delete(name))
        lay.addWidget(delete)
        return row

    def _start_rename(self, name: str, anchor: QPushButton) -> None:
        if self._rename_overlay is not None:
            self._rename_overlay.close()
            self._rename_overlay.deleteLater()
        ov = _NamePromptOverlay(
            QApplication.translate('tilauscope_alarms', 'rename preset'), name, self)
        ov.accepted.connect(lambda new_name: self._rename(name, new_name))
        ov.closed.connect(self._clear_rename_overlay)
        self._rename_overlay = ov
        ov.show_at(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _clear_rename_overlay(self) -> None:
        self._rename_overlay = None

    def _rename(self, old: str, new: str) -> None:
        if new in self._store.names() and new != old:
            show_styled_message(
                self,
                QApplication.translate('tilauscope_alarms', 'Rename preset'),
                QApplication.translate(
                    'tilauscope_alarms', 'A preset named "{0}" already exists.').format(new))
            return
        self._store.rename(old, new)
        self._rebuild()

    def _delete(self, name: str) -> None:
        self._store.delete(name)
        self._rebuild()


# ───────────────────────────────────────────────────────────────────────────
# TilauAlarmDlg — the editor dialog (drop-in for aw.alarmconfig)
# ───────────────────────────────────────────────────────────────────────────

class TilauAlarmDlg(QDialog):
    """Rule-sentence alarm editor. Same constructor signature as the legacy
    dialog so external wiring (aw.alarmconfig monkey-patch) keeps working.
    Loads qmc on open, saves qmc on close; the UI itself only knows AlarmSet."""

    def __init__(self, parent: QWidget, aw: 'ApplicationWindow') -> None:
        super().__init__(parent)
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.aw = aw
        self.adapter = QmcAlarmAdapter(aw)
        self.alarms = AlarmSet(self)
        self._rows_by_aid: dict[int, _AlarmRow] = {}
        self._selected_aid: int | None = None
        self._phase_headers: list[tuple[Phase, QWidget]] = []
        self._overlay: _ChipEditOverlay | None = None
        self._ai_panel: AIFloatPanel | None = None
        self._preset_store = AlarmPresetStore()
        self._save_preset_overlay: _NamePromptOverlay | None = None
        # Original qmc row index of each alarm still tied to the live roast
        # (aid -> index). Rows created/loaded in this session (Add, preset
        # load) are absent, so the live poll below leaves them alone.
        self._aid_to_qmc_index: dict[int, int] = {}
        self.oldPos: QPoint | None = None

        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        settings = QSettings()
        self._group_by_phase = settings.value(
            'TilauAlarmsGroupByPhase', True, type=bool)

        self._build_ui()
        self._connect_model()
        loaded = self.adapter.load()
        self.alarms.load(loaded)
        self._aid_to_qmc_index = {a.aid: i for i, a in enumerate(loaded)}
        self._init_ai_panel()

        if settings.contains('TilauAlarmsGeometry'):
            self.restoreGeometry(settings.value('TilauAlarmsGeometry'))
        else:
            self.resize(720, 620)

        # Alarms can fire while this (modal) editor is open mid-roast; poll
        # qmc.alarmstate directly here rather than hooking the 1 Hz hot path.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(2000)
        self._live_timer.timeout.connect(self._poll_fired_state)
        self._live_timer.start()

    # ── construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setStyleSheet(
            f"QFrame {{ background: {THEME['BG']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 16px; }}")
        outer.addWidget(self.container)

        root = QVBoxLayout(self.container)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        root.addLayout(self._build_header())
        root.addLayout(self._build_toolbar())

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        self.banner.setStyleSheet(
            f"color: {THEME['WARNING']}; background: {_hex_to_rgba(THEME['WARNING'], 0.10)};"
            f"border: 1px solid {_hex_to_rgba(THEME['WARNING'], 0.35)}; border-radius: 8px;"
            f"padding: 6px 10px; font-size: 11px;")
        root.addWidget(self.banner)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        self.body = _AlarmListBody(self._handle_drop)
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 4, 0)
        self.body_lay.setSpacing(6)
        self.body_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)

        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        title = QLabel(QApplication.translate('tilauscope_alarms', 'Alarm editor').upper())
        title.setStyleSheet(
            f"color: {THEME['ACCENT']};"
            f'font-size: 16px; font-weight: 900; letter-spacing: 2px; border: none;')
        close = QPushButton('\u2715')
        close.setFixedSize(28, 28)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self._close_dialog)
        close.setStyleSheet(
            f"QPushButton {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 14px; }}"
            f"QPushButton:hover {{ background: {THEME['CRITICAL']}; color: {THEME['BG']}; }}")
        h.addWidget(title)
        h.addStretch()
        h.addWidget(close)
        return h

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._btn_add = self._tool_btn(
            QApplication.translate('Button', 'Add'), self._on_add,
            accent=THEME['SUCCESS'])
        self._btn_insert = self._tool_btn(
            QApplication.translate('tilauscope_alarms', 'Insert below'), self._on_insert)
        self._btn_dup = self._tool_btn(
            QApplication.translate('tilauscope_alarms', 'Duplicate'), self._on_duplicate)
        self._btn_del = self._tool_btn(
            QApplication.translate('Button', 'Delete'), self._on_delete)
        bar.addWidget(self._btn_add)
        bar.addWidget(self._btn_insert)
        bar.addWidget(self._btn_dup)
        bar.addWidget(self._btn_del)

        self._btn_presets = self._tool_btn(
            QApplication.translate('tilauscope_alarms', 'Presets') + '  ▾',
            self._show_presets_menu)
        bar.addWidget(self._btn_presets)

        self._btn_ai = self._tool_btn(
            '\u2726  ' + QApplication.translate('tilauscope_alarms', 'Check consistency (AI)'),
            self._toggle_ai_panel, accent=THEME['ACCENT'])
        cfg = getattr(self.aw, 'tilau_aiConfig', None)
        self._btn_ai.setVisible(bool(cfg is not None and cfg.is_configured))
        bar.addWidget(self._btn_ai)
        bar.addStretch()

        self._phase_toggle = QPushButton(
            QApplication.translate('tilauscope_alarms', 'Group by phase'))
        self._phase_toggle.setCheckable(True)
        self._phase_toggle.setChecked(self._group_by_phase)
        self._phase_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._phase_toggle.toggled.connect(self._on_toggle_phase)
        self._style_toggle()
        bar.addWidget(self._phase_toggle)
        bar.addStretch()

        bar.addWidget(self._caption(
            QApplication.translate('tilauscope_alarms', 'Pop-up timeout')))
        self._popup_timeout = QSpinBox()
        self._popup_timeout.setSuffix('s')
        self._popup_timeout.setRange(0, 120)
        self._popup_timeout.setValue(int(self.aw.qmc.alarm_popup_timout))
        self._popup_timeout.setStyleSheet(
            f"QSpinBox {{ background: {THEME['BG']}; color: {THEME['TEXT']};"
            f"border: 1px solid {_SURF1}; border-radius: 6px; padding: 2px 6px;"
            f"font-size: 11px; }}")
        bar.addWidget(self._popup_timeout)
        return bar

    def _build_footer(self) -> QHBoxLayout:
        f = QHBoxLayout()
        f.addStretch()
        ok = QPushButton(QApplication.translate('Button', 'Close'))
        ok.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ok.setMinimumWidth(110)
        ok.clicked.connect(self._close_dialog)
        ok.setStyleSheet(
            f"QPushButton {{ background: {THEME['ACCENT']}; color: {THEME['BG']};"
            f"border: none; border-radius: 8px; padding: 7px 16px;"
            f"font-size: 12px; font-weight: bold; }}")
        f.addWidget(ok)
        return f

    def _tool_btn(self, text: str, slot, accent: str | None = None) -> QPushButton:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(slot)
        col = accent or THEME['TEXT']
        btn.setStyleSheet(
            f"QPushButton {{ background: {THEME['SURFACE']}; color: {col};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 7px;"
            f"padding: 5px 11px; font-size: 11px; }}"
            f"QPushButton:hover {{ border-color: {col}; }}")
        return btn

    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']};"
            f'font-size: 11px; border: none;')
        return lbl

    def _style_toggle(self) -> None:
        on = self._phase_toggle.isChecked()
        col = THEME['ACCENT'] if on else THEME['SUBTEXT']
        bg = _hex_to_rgba(THEME['ACCENT'], 0.16) if on else 'transparent'
        self._phase_toggle.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {col};"
            f"border: 1px solid {col}; border-radius: 7px; padding: 5px 11px;"
            f"font-size: 11px; }}")

    # ── model wiring ──────────────────────────────────────────────────────

    def _connect_model(self) -> None:
        self.alarms.modelReset.connect(self._rebuild_body)
        self.alarms.rowInserted.connect(lambda _i: self._rebuild_body())
        self.alarms.rowRemoved.connect(lambda _i: self._rebuild_body())
        self.alarms.rowsReordered.connect(self._rebuild_body)
        self.alarms.rowChanged.connect(self._on_row_changed)

    @pyqtSlot(int)
    def _on_row_changed(self, index: int) -> None:
        a = self.alarms.at(index)
        if a is None:
            return
        row = self._rows_by_aid.get(a.aid)
        if row is None:
            self._rebuild_body()
        else:
            # Refresh in place so an open edit overlay is never torn down.
            # Phase re-bucketing (if the anchor changed) is deferred to close.
            row.refresh()
        self._update_banner()

    # ── body rendering ────────────────────────────────────────────────────

    def _rebuild_body(self) -> None:
        self._close_overlay()
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows_by_aid.clear()
        self._phase_headers.clear()

        if self._group_by_phase:
            for phase, group in self.alarms.grouped_by_phase():
                header = self._phase_header(phase, len(group))
                self._phase_headers.append((phase, header))
                self.body_lay.addWidget(header)
                for a in group:
                    self.body_lay.addWidget(self._make_row(a.aid, indent=a.is_conditional))
        else:
            for a in self.alarms.rows:
                self.body_lay.addWidget(self._make_row(a.aid, indent=a.is_conditional))

        self.body_lay.addStretch(1)
        self._update_banner()

    def _phase_header(self, phase: Phase, count: int) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 8, 2, 2)
        lay.setSpacing(8)
        tick = QFrame()
        tick.setFixedSize(3, 13)
        tick.setStyleSheet(
            f'background: {PHASE_COLOR[phase]}; border-radius: 1px;')
        lbl = QLabel(phase_label(phase).lower())
        lbl.setProperty('variant', 'eyebrow')
        cnt = QLabel(str(count))
        cnt.setStyleSheet(
            f"color: {_OVERLAY};"
            f'font-size: 11px; border: none;')
        lay.addWidget(tick)
        lay.addWidget(lbl)
        lay.addStretch()
        lay.addWidget(cnt)
        return w

    def _make_row(self, aid: int, indent: bool = False) -> QWidget:
        row = _AlarmRow(aid, self.alarms, self.adapter)
        row.editRequested.connect(self._open_overlay)
        row.toggleEnable.connect(self.alarms.toggle_enabled)
        row.toggleBeep.connect(self.alarms.toggle_beep)
        row.deleteRequested.connect(self._on_row_delete)
        row.rowClicked.connect(self._on_select)
        row.set_selected(aid == self._selected_aid)
        self._rows_by_aid[aid] = row
        if not indent:
            return row
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(20, 0, 0, 0)
        wl.addWidget(row)
        return wrap

    # ── selection ─────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_select(self, aid: int) -> None:
        # Apply across all materialised rows so a preceding rebuild (e.g. from
        # an insert) cannot leave a stale row highlighted.
        self._selected_aid = aid
        for rid, row in self._rows_by_aid.items():
            row.set_selected(rid == aid)

    def _clear_selection(self) -> None:
        self._selected_aid = None
        for row in self._rows_by_aid.values():
            row.set_selected(False)

    # ── CRUD slots ────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_add(self) -> None:
        # Blank alarm, but inheriting the selected row's anchor so it does not
        # jump to another phase. Duplicate is the operation that clones fully.
        self._on_select(self.alarms.add(self._seed_from_selection()))

    @pyqtSlot()
    def _on_insert(self) -> None:
        if self._selected_aid is None:
            self._on_add()
            return
        self._on_select(self.alarms.insert_below(
            self._selected_aid, self._seed_from_selection()))

    def _seed_from_selection(self) -> Alarm | None:
        """Blank alarm seeded with the selected row's anchor (event + offset),
        so a new row lands in the same phase next to it. None when nothing is
        selected (a default alarm is created instead)."""
        ref = self.alarms.by_aid(self._selected_aid)
        if ref is None:
            return None
        return Alarm(aid=0, from_event=ref.from_event, offset=ref.offset)

    @pyqtSlot()
    def _on_duplicate(self) -> None:
        sel = self.alarms.by_aid(self._selected_aid)
        if sel is None:
            return
        self._on_select(self.alarms.insert_below(self._selected_aid, sel))

    @pyqtSlot()
    def _on_delete(self) -> None:
        if self._selected_aid is not None:
            self.alarms.remove(self._selected_aid)
            self._clear_selection()

    @pyqtSlot(int)
    def _on_row_delete(self, aid: int) -> None:
        was_selected = self._selected_aid == aid
        self.alarms.remove(aid)
        if was_selected:
            self._clear_selection()

    # ── phase toggle ──────────────────────────────────────────────────────

    @pyqtSlot(bool)
    def _on_toggle_phase(self, on: bool) -> None:
        self._group_by_phase = on
        self._style_toggle()
        self._rebuild_body()

    # ── fired-state live poll ───────────────────────────────────────────────

    @pyqtSlot()
    def _poll_fired_state(self) -> None:
        states = getattr(self.aw.qmc, 'alarmstate', None)
        if not states:
            return
        for aid, qidx in self._aid_to_qmc_index.items():
            if 0 <= qidx < len(states):
                self.alarms.set_field(aid, 'fired_idx', int(states[qidx]))

    # ── presets ────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _show_presets_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 8px; padding: 4px; }}"
            f"QMenu::item {{ padding: 5px 14px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background: {THEME['ACCENT']}; color: {THEME['BG']}; }}"
            f"QMenu::item:disabled {{ color: {THEME['SUBTEXT']}; }}"
            f"QMenu::separator {{ height: 1px; background: {THEME['BORDER']}; margin: 4px 6px; }}")
        names = self._preset_store.names()
        if names:
            for name in names:
                act = menu.addAction(name)
                act.triggered.connect(lambda _checked=False, n=name: self._load_preset(n))
            menu.addSeparator()
        else:
            empty = menu.addAction(
                QApplication.translate('tilauscope_alarms', '(no presets saved)'))
            empty.setEnabled(False)
            menu.addSeparator()

        save_act = menu.addAction(
            QApplication.translate('tilauscope_alarms', 'Save current as…'))
        save_act.triggered.connect(self._open_save_preset_popup)
        if names:
            manage_act = menu.addAction(
                QApplication.translate('tilauscope_alarms', 'Manage presets…'))
            manage_act.triggered.connect(self._open_manage_presets)
        menu.exec(self._btn_presets.mapToGlobal(QPoint(0, self._btn_presets.height())))

    def _open_save_preset_popup(self) -> None:
        if self._save_preset_overlay is not None:
            self._save_preset_overlay.close()
            self._save_preset_overlay.deleteLater()
        ov = _NamePromptOverlay(
            QApplication.translate('tilauscope_alarms', 'save preset as'), '', self)
        ov.accepted.connect(self._do_save_preset)
        ov.closed.connect(self._clear_save_preset_overlay)
        self._save_preset_overlay = ov
        ov.show_at(self._btn_presets.mapToGlobal(QPoint(0, self._btn_presets.height())))

    def _clear_save_preset_overlay(self) -> None:
        self._save_preset_overlay = None

    def _do_save_preset(self, name: str) -> None:
        if name in self._preset_store.names():
            answer = show_styled_message(
                self,
                QApplication.translate('tilauscope_alarms', 'Save preset'),
                QApplication.translate(
                    'tilauscope_alarms', 'A preset named "{0}" already exists. Overwrite it?')
                .format(name),
                buttons=[QApplication.translate('Button', 'Cancel'),
                         QApplication.translate('Button', 'Overwrite')])
            if answer != 1:
                return
        self._preset_store.save(name, self.alarms.rows)

    def _load_preset(self, name: str) -> None:
        rows = self._preset_store.load(name)
        if rows is None:
            return
        # A preset is a programme, not a live roast state: it no longer
        # corresponds to any position in the currently loaded qmc arrays.
        self._aid_to_qmc_index = {}
        self.alarms.load(rows)
        self._clear_selection()

    def _open_manage_presets(self) -> None:
        dlg = _PresetManagerDlg(self._preset_store, self)
        dlg.exec()

    # ── edit overlay ──────────────────────────────────────────────────────

    @pyqtSlot(int, str, QPoint)
    def _open_overlay(self, aid: int, cluster: str, global_anchor: QPoint) -> None:
        self._close_overlay()
        self._on_select(aid)
        ov = _ChipEditOverlay(aid, cluster, self.alarms, self.adapter, self)
        ov.closed.connect(self._on_overlay_closed)
        self._overlay = ov
        ov.adjustSize()
        local = self.mapFromGlobal(global_anchor)
        x = min(max(8, local.x()), self.width() - ov.width() - 8)
        y = local.y() + 4
        if y + ov.height() > self.height() - 8:
            y = max(8, local.y() - ov.height() - 24)
        ov.move(x, y)
        ov.show()
        ov.raise_()
        ov.setFocus()

    def _close_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay.deleteLater()
            self._overlay = None

    @pyqtSlot()
    def _on_overlay_closed(self) -> None:
        self._overlay = None
        # Re-bucket once the user is done editing (anchor may have changed phase).
        if self._group_by_phase:
            self._rebuild_body()

    # ── drag-and-drop ─────────────────────────────────────────────────────

    def _handle_drop(self, src_aid: int, global_y: int) -> None:
        """Reorder in both modes. In phase mode, a drop into a *different*
        phase also re-anchors the alarm to that phase (intra-phase drops keep
        the original anchor, so CHARGE vs TP is preserved)."""
        src = self.alarms.index_of(src_aid)
        a = self.alarms.by_aid(src_aid)
        if src < 0 or a is None:
            return

        ref = self._drop_reference(global_y, src_aid)
        changed = False
        if self._group_by_phase:
            target_phase = self._phase_at(global_y)
            if (target_phase is not None and target_phase != Phase.CONDITIONAL
                    and self.alarms.phase_of(a) != target_phase):
                rep = _PHASE_REP.get(target_phase)
                if rep is not None:
                    self.alarms.set_field(src_aid, 'from_event', int(rep))
                    changed = True

        if ref is None:
            dst = len(self.alarms) - 1
        else:
            ref_idx = self.alarms.index_of(ref.aid)
            dst = ref_idx - 1 if src < ref_idx else ref_idx
        dst = max(0, min(dst, len(self.alarms) - 1))

        if dst != src:
            self.alarms.move(src, dst)   # emits rowsReordered -> rebuild
        elif changed:
            self._rebuild_body()         # anchor changed but position did not
        self._on_select(src_aid)

    def _drop_reference(self, global_y: int, src_aid: int):
        """First visible row (in visual order) whose vertical midpoint sits
        below the drop point; the dragged row inserts before it. None = end."""
        for a in self._visual_rows():
            if a.aid == src_aid:
                continue
            row = self._rows_by_aid.get(a.aid)
            if row is None:
                continue
            mid = row.mapToGlobal(QPoint(0, row.height() // 2)).y()
            if mid > global_y:
                return a
        return None

    def _visual_rows(self) -> list[Alarm]:
        """Alarms in on-screen order (phase-grouped or flat)."""
        if self._group_by_phase:
            out: list[Alarm] = []
            for _phase, group in self.alarms.grouped_by_phase():
                out.extend(group)
            return out
        return list(self.alarms.rows)

    def _phase_at(self, global_y: int) -> Phase | None:
        """Phase whose header sits at or above the drop point."""
        chosen: Phase | None = None
        for phase, header in self._phase_headers:
            if header.mapToGlobal(QPoint(0, 0)).y() <= global_y:
                chosen = phase
            else:
                break
        return chosen

    # ── AI consistency audit ──────────────────────────────────────────────

    def _init_ai_panel(self) -> None:
        """Create the floating AI panel if AI is configured (same panel used
        previously by the visual timeline)."""
        cfg = getattr(self.aw, 'tilau_aiConfig', None)
        if cfg is None or not cfg.is_configured:
            return
        self._ai_panel = AIFloatPanel(
            task_type=AITask.ALARM_NARRATIVE,
            ai_service=self.aw.tilau_ai_service,
            title=QApplication.translate('tilauscope_alarms', 'Alarm consistency check'),
            owner=self,
            aw=self.aw,
        )
        self._ai_panel.set_payload_fn(self._build_audit_payload)

    @pyqtSlot()
    def _toggle_ai_panel(self) -> None:
        if self._ai_panel is not None:
            self._ai_panel.toggle()

    def _reposition_ai_panel(self) -> None:
        if getattr(self, '_ai_panel', None) is not None:
            self._ai_panel.reposition()

    def _build_audit_payload(self) -> tuple[str, str]:
        """System + user messages: audit the set for inconsistencies and
        propose corrections (not a description of what the alarms do)."""
        rows = self.alarms.rows
        if not rows:
            return ('', '')

        lines: list[str] = []
        for i, a in enumerate(rows):
            num = i + 1
            if a.is_conditional:
                if a.guard_aid is not None:
                    timing = (f'if alarm #{self.alarms.display_number(a.guard_aid)} '
                              f'fired, at +{a.offset}s')
                elif a.negguard_aid is not None:
                    timing = (f'if alarm #{self.alarms.display_number(a.negguard_aid)} '
                              f'did NOT fire, at +{a.offset}s')
                else:
                    timing = f'conditional with no guard, at +{a.offset}s'
            else:
                timing = f'at {from_event_label(a.from_event)} +{a.offset}s'

            cond = ''
            if a.source != -3:
                sym = COND_SYMBOLS[a.cond] if 0 <= a.cond < len(COND_SYMBOLS) else '?'
                cond = f' [when {self.adapter.source_label(a.source)} {sym} {a.value:g}]'

            act = self.adapter.action_label(a.action)
            if a.action == Action.EVENT_BUTTON:
                content = self.adapter.event_button_label(a.arg)
                arg = f' #{a.arg}' + (f' ({content})' if content else '')
            elif action_takes_arg(a.action) and a.arg:
                arg = f' = {a.arg}' if a.action in _SLIDER_ACTIONS else f' : {a.arg}'
            else:
                arg = ''

            state = '' if a.enabled else ' (DISABLED)'
            phase = phase_label(self.alarms.phase_of(a))
            lines.append(f'- #{num} [{phase}]{state}: {timing}{cond} -> {act}{arg}')

        roaster = getattr(self.aw, 'tilau_roaster', None)
        roaster_text = f' on a {roaster}' if roaster else ''
        interval = max(0.1, self.aw.qmc.delay / 1000.0)  # sample tick, seconds
        _locale_map = {'fr': 'French', 'en': 'English', 'de': 'German',
                       'es': 'Spanish', 'it': 'Italian', 'ja': 'Japanese',
                       'zh': 'Chinese', 'pt': 'Portuguese', 'nl': 'Dutch',
                       'ko': 'Korean', 'ru': 'Russian', 'pl': 'Polish'}
        lang = _locale_map.get(self.aw.qmc.locale_str, self.aw.qmc.locale_str)

        system = (
            'You are an expert auditor of coffee-roasting automation. You review the '
            f'alarm set programmed into a roaster{roaster_text} (independent air, drum, '
            'speed and burner controls) and judge whether it is internally CONSISTENT. '
            'Do NOT describe or summarise what the alarms do.\n\n'
            'How the roaster fires these (reason strictly with this model):\n'
            f'- The loop scans every alarm once per sample tick (~{interval:g}s here); '
            'timing resolution is one tick, so an offset fires at the first tick at or '
            'after it.\n'
            '- Each alarm fires at most once per roast. A disabled alarm never fires and '
            "never satisfies another alarm's guard.\n"
            '- An alarm becomes eligible only once its FROM event has actually happened: '
            'ON = monitoring on, START = recording start, CHARGE / DRY END / FC / SC / '
            'DROP / COOL = that marked event, TP = after CHARGE once the turning point is '
            'detected. If that event never occurs, the alarm never fires.\n'
            '- Offset = seconds AFTER the anchor before the time criterion is met. The '
            'time criterion only exists when offset > 0; offset 0 means there is NO time '
            'criterion (it does NOT mean "fire at the anchor"), so "essentially at the '
            'anchor" is written as the smallest non-zero offset, commonly +0:01. For an '
            'IF-alarm the offset counts from the instant its guard fired, not from a roast '
            'event.\n'
            '- Guards: an IF-alarm fires only after its guard alarm has fired; an IF-NOT '
            'only while the referenced alarm has not fired; an IF-alarm with no guard '
            'never fires.\n'
            '- An alarm fires on (offset > 0 AND elapsed-since-anchor >= offset) OR (a '
            'sensor condition that holds) - logical OR. Hence: offset > 0 + no condition = '
            'timed; offset 0 + condition = pure condition; offset > 0 + condition = '
            'whichever comes first; and offset 0 + NO condition = NEVER fires (a dead '
            'alarm).\n'
            '- A sensor condition is a LATCH, not an instant test: the alarm arms at its '
            'anchor, then the condition is re-checked every tick and fires the first tick '
            'it holds. The condition is EXPECTED to become true some time AFTER the anchor, '
            'not at it - e.g. "from DROP +0s, BT < 100" is the correct idiom for "once the '
            'bean cools below 100 deg C after drop", and fires during cooling. Only treat a '
            'condition as impossible if it can NEVER hold during a real roast (an '
            'out-of-range threshold), never merely because it is not yet true at the '
            'anchor.\n'
            '- Same-tick chaining depends on list order: a guard sets its state within the '
            'tick, so an IF-alarm listed AFTER its guard can fire on the same tick, while '
            'one listed BEFORE its guard waits one extra tick.\n\n'
            'Check specifically for:\n'
            '- conflicting actions: two alarms driving the same actuator to different '
            'values at the same moment;\n'
            '- contradictory or impossible trigger conditions: a threshold outside any '
            'plausible roast range that can never be reached. Do NOT flag a condition just '
            'because it is not satisfied at its anchor - arming at the anchor and firing '
            'later is the intended behaviour;\n'
            '- broken guard logic: an IF-alarm referencing a missing, disabled, self or '
            'cyclic alarm;\n'
            '- dead alarms: offset 0 with no sensor condition (and an action set) can '
            'never fire;\n'
            '- ordering problems, including offset-0 conditional chains whose list order '
            'forces an unintended extra-tick delay;\n'
            '- wrong anchor/phase: an action attached to an event where it makes no sense;\n'
            '- duplicates: identical trigger and action;\n'
            '- safety gaps: e.g. burner not cut or no cooling started at DROP.\n\n'
            'Respond in this exact structure, referencing the alarm numbers given:\n'
            '1. **Verdict** - exactly one line: `CONSISTENT` or `ISSUES FOUND`.\n'
            '2. **Issues** - only if any; one bullet per issue stating the alarm number(s) '
            'involved, what is wrong, a severity (critical / warning / minor), and a '
            'concrete proposed correction with specific values or anchors. Omit this '
            'section entirely when there are none.\n'
            '3. **Optional refinements** - at most three genuinely useful, non-blocking '
            'suggestions; omit if none.\n\n'
            'Be terse and specific. No preamble, no restatement of the alarms. Use Markdown. '
            f'Write the entire response in {lang}.'
        )
        user = 'Alarm set (in firing order):\n\n' + '\n'.join(lines)
        return (system, user)

    # ── validation banner ─────────────────────────────────────────────────

    def _update_banner(self) -> None:
        warnings = self.alarms.validate()
        if warnings:
            self.banner.setText('\u26A0  ' + '   •   '.join(warnings))
            self.banner.setVisible(True)
        else:
            self.banner.setVisible(False)

    # ── window drag (frameless) ───────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.childAt(event.position().toPoint())
            if isinstance(w, (QPushButton, QComboBox, QLineEdit, QTimeEdit,
                              QScrollArea, _AlarmRow, _Chip, _AlarmListBody,
                              _GripHandle)):
                event.ignore()
                return
            self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.oldPos is not None:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self.oldPos = None

    def moveEvent(self, a0) -> None:  # type: ignore[override]
        super().moveEvent(a0)
        self._reposition_ai_panel()

    def resizeEvent(self, a0) -> None:  # type: ignore[override]
        super().resizeEvent(a0)
        self._reposition_ai_panel()

    def showEvent(self, a0) -> None:  # type: ignore[override]
        super().showEvent(a0)
        QTimer.singleShot(50, self._reposition_ai_panel)

    # ── close / persist ───────────────────────────────────────────────────

    def _teardown_ai_panel(self) -> None:
        if self._ai_panel is None:
            return
        try:
            self._ai_panel._ai_service.cancel(AITask.ALARM_NARRATIVE)
        except Exception:  # noqa: BLE001 - best-effort cancellation
            pass
        self._ai_panel.hide()
        self._ai_panel.close()
        self._ai_panel = None

    @pyqtSlot()
    def _close_dialog(self) -> None:
        self._live_timer.stop()
        self._close_overlay()
        self._teardown_ai_panel()
        self.adapter.save(self.alarms)
        self.aw.qmc.alarm_popup_timout = int(self._popup_timeout.value())
        settings = QSettings()
        settings.setValue('TilauAlarmsGeometry', self.saveGeometry())
        settings.setValue('TilauAlarmsGroupByPhase', self._group_by_phase)
        if getattr(self.aw, 'tilauscope_main', None) is not None:
            self.aw.tilauscope_main.update_status_text()
        self.accept()

    def closeEvent(self, a0: QCloseEvent | None) -> None:  # type: ignore[override]
        del a0
        self._close_dialog()


# ───────────────────────────────────────────────────────────────────────────
# Integration hook
# ───────────────────────────────────────────────────────────────────────────

def open_alarm_editor(aw: 'ApplicationWindow', parent: QWidget | None = None) -> None:
    """Open the TilauScope alarm editor. Drop-in target for aw.alarmconfig."""
    dlg = TilauAlarmDlg(parent or aw, aw)
    dlg.exec()


def install(aw: 'ApplicationWindow') -> None:
    """Monkey-patch aw.alarmconfig to use the TilauScope editor."""
    aw.alarmconfig = lambda _checked=False: open_alarm_editor(aw)  # type: ignore[assignment]