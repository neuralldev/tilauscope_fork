#
# ABOUT
# Beancave - ALog Repair (batch completion of incomplete roast profiles)
#
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

"""
AlogRepairDialog - floating roast-profile maintenance window (TilauScope menu). Lists
every .alog, audits missing fields, and lets the user complete one file at a time;
"Complete from bean" fills empty metadata from the matched bean, and "Record"
rewrites the .alog and renames it to the Artisan filename (title + roast date).

IMPORTANT - file encoding: write with ``path.write_text(repr(data), encoding='utf-8')``
only (see write_alog()). Do NOT ``encode('unicode_escape')`` — readers only
literal_eval, so the extra layer compounds on every save.
"""

from __future__ import annotations

from tilauscope.theme_qss import apply_tilau_theme, tint

import re
import ast
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore    import Qt, QPoint, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui     import QColor, QMouseEvent
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QListWidget, QListWidgetItem, QSplitter,
    QWidget, QPlainTextEdit, QApplication, QCheckBox, QMessageBox,
    QFrame, QSizeGrip, QProgressDialog, QButtonGroup, QScrollArea,
)

from tilauscope.tilauscope_types import (
    THEME, AGTRON_SCALES, GreenBean, show_styled_message, TilauProgress,
)
from tilauscope.roasters import RoasterManager, canonical_roaster_name

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow
    from tilauscope.beancave import BeancaveDlg

_log: Final[logging.Logger] = logging.getLogger(__name__)

_UUID_RE: Final = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')
# Artisan removeDisallowedFilenameChars: strips [<>:"/\|?*]
_INVALID_FN: Final = re.compile(r'[<>:"/\\|?*]')


# Default ALog roast-data unit is grams; quantities are stored in weight[2].
_DEFAULT_WEIGHT_UNIT: Final = 'g'

# Typical weight-loss window (%) for guidance (light -> dark).
_LOSS_RANGE: Final = (10.0, 22.0)

# Present-but-implausible guidance ranges. Empty/0 values are handled by the
# completeness audit, not here. (low, high, unit, human-label)
_PLAUSIBLE: Final = {
    'density':          (550.0, 900.0, ' g/l', 'density'),
    'moisture_greens':  (8.0,   14.0,  ' %',   'moisture'),
    'greens_temp':      (5.0,   40.0,  '\u00b0C', 'greens temp'),
    'whole_color':      (40.0,  120.0, '',     'whole color'),
    'ambientTemp':      (5.0,   40.0,  '\u00b0C', 'ambient temp'),
    'ambient_humidity': (20.0,  80.0,  ' %',   'humidity'),
}

_FIELD_LABELS: Final = {
    'beans_uuid':       'bean link',
    'title':            'title',
    'weight_in':        'weight in',
    'weight_out':       'weight out',
    'density':          'density',
    'moisture_greens':  'moisture',
    'greens_temp':      'greens temp',
    'whole_color':      'whole color',
    'ambientTemp':      'ambient temp',
    'ambient_humidity': 'humidity',
}


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (UI-independent, testable)
# ─────────────────────────────────────────────────────────────────────────────

def audit_alog(data: dict) -> list[str]:
    """Return the list of missing/empty field keys for a parsed .alog dict.
    ground_color is intentionally optional and not audited."""
    missing: list[str] = []

    if not _UUID_RE.search(data.get('beans', '') or ''):
        missing.append('beans_uuid')
    if not (data.get('title') or '').strip():
        missing.append('title')

    w = data.get('weight') or []
    if (_safe_float(w[0]) if len(w) > 0 else 0.0) == 0.0:
        missing.append('weight_in')
    if (_safe_float(w[1]) if len(w) > 1 else 0.0) == 0.0:
        missing.append('weight_out')

    dens = data.get('density') or []
    if (_safe_float(dens[0]) if dens else 0.0) == 0.0:
        missing.append('density')
    if _safe_float(data.get('moisture_greens')) == 0.0:
        missing.append('moisture_greens')
    if _safe_float(data.get('greens_temp')) == 0.0:
        missing.append('greens_temp')
    if _safe_float(data.get('whole_color')) == 0.0:
        missing.append('whole_color')
    # ambient feeds the historical analysis quality filter (excluded when 0)
    if _safe_float(data.get('ambientTemp')) == 0.0:
        missing.append('ambientTemp')
    if _safe_float(data.get('ambient_humidity')) == 0.0:
        missing.append('ambient_humidity')

    return missing


def weight_loss_pct(w_in: float, w_out: float) -> float | None:
    """Roast weight loss %, or None when not computable. Negative is impossible
    (out >= in) and is returned as None by the caller's check."""
    if w_in <= 0.0 or w_out <= 0.0:
        return None
    return (w_in - w_out) / w_in * 100.0


def plausibility_checks(values: dict[str, float]) -> list[str]:
    """Human hints for present-but-implausible numeric values (offline guidance)."""
    out: list[str] = []
    for key, (lo, hi, unit, label) in _PLAUSIBLE.items():
        v = _safe_float(values.get(key))
        if v > 0.0 and (v < lo or v > hi):
            out.append(f"{label} {v:g}{unit} (typical {lo:g}\u2013{hi:g})")
    return out


def build_beans_field(bean: GreenBean) -> str:
    """Canonical beans text - mirrors roast_properties._build_beans_field."""
    t = QApplication.translate
    parts: list[str] = []
    if bean.name:
        parts.append(bean.name)
    if bean.country:
        parts.append(bean.country)
    if bean.farm:
        parts.append("{0} {1}".format(t("tilauscope_beancave", "Farm:"), bean.farm))
    if bean.process:
        parts.append("{0} {1}".format(t("tilauscope_beancave", "Process"), bean.process))
    if bean.varieties:
        parts.append("{0} {1}".format(t("tilauscope_beancave", "Variety"), bean.varieties))
    if bean.altitude:
        parts.append("{0} {1}m".format(t("tilauscope_beancave", "Altitude:"), bean.altitude))
    if bean.sca:
        parts.append(t("tilauscope_beancave", "SCA: {0}").format(f"{bean.sca:.1f}"))
    if bean.uuid:
        parts.append(t("tilauscope_beancave", "uuid: {0}").format(bean.uuid))
    return "\n".join(parts)


def build_alog_filename(data: dict) -> str:
    """Reconstruct the Artisan auto-filename: <title>_<yy-MM-dd_hhmm>.alog,
    cleaned of disallowed characters. The roast timestamp is taken from the
    locale-independent roastisodate + roasttime (falls back to roastepoch)."""
    title = (data.get('title') or '').strip()
    suffix = _roast_suffix(data)
    base = f"{title}_{suffix}" if title else suffix
    base = _INVALID_FN.sub('', base).strip()
    return base + '.alog'


def write_alog(data: dict, path: Path) -> None:
    """Write in Artisan's native profile format: ``repr(dict)`` as UTF-8 text,
    read back with ``ast.literal_eval`` — exactly what beancave.get_alog_data
    and artisanlib.util.serialize/deserialize do.

    NEVER ``encode('unicode_escape')`` here: the readers only literal_eval, so
    that extra escape layer is never undone and **compounds on every save** —
    multi-line ``beans`` accumulated runs of backslashes (``\\\\\\\\n`` instead
    of one separator) and accents were mangled to ``\\xNN``. """
    path.write_text(repr(data), encoding='utf-8')


## ── Learning state of a roast: admitted / not reviewed / excluded ──────────
## The admit key is a positive marker, written only when the roast is vouched for.
## Its absence means "not reviewed" (still learned from), distinct from the exclude key.
LEARNING_EXCLUDE_KEY:  Final[str] = 'tilau_exclude_learning'
LEARNING_ADMIT_KEY:    Final[str] = 'tilau_learning_admitted'

LEARNING_ADMITTED:   Final[str] = 'admitted'
LEARNING_UNREVIEWED: Final[str] = 'unreviewed'
LEARNING_EXCLUDED:   Final[str] = 'excluded'


def learning_state(data: dict) -> str:
    """Read the learning state of a profile dict.

    Exclusion wins over admission: a file carrying both keys (hand-edited, or a
    save that crossed a toggle) is the conservative case — the operator's veto
    is the one that must survive.
    """
    if data.get(LEARNING_EXCLUDE_KEY) is True:
        return LEARNING_EXCLUDED
    if data.get(LEARNING_ADMIT_KEY) is True:
        return LEARNING_ADMITTED
    return LEARNING_UNREVIEWED


def apply_learning_state(data: dict, state: str) -> dict:
    """Return a copy of `data` carrying exactly one (or no) learning marker.

    Both keys are dropped first, so a state change never leaves the previous
    marker behind — that is how a file would end up meaning two things at once.
    """
    out = dict(data)
    out.pop(LEARNING_EXCLUDE_KEY, None)
    out.pop(LEARNING_ADMIT_KEY, None)
    if state == LEARNING_EXCLUDED:
        out[LEARNING_EXCLUDE_KEY] = True
    elif state == LEARNING_ADMITTED:
        out[LEARNING_ADMIT_KEY] = True
    return out


# ── fast metadata read (list audit only) ─────────────────────────────────────
# A .alog is a repr(dict) dominated by curve data; auditing needs only a dozen
# scalar fields, so the targeted read below is ~100x cheaper than a full parse
# (~35ms/file). Full parse still happens when a file is SELECTED.

_META_KEYS: Final[tuple[str, ...]] = (
    'title', 'beans', 'weight', 'density', 'moisture_greens', 'greens_temp',
    'whole_color', 'ambientTemp', 'ambient_humidity',
    LEARNING_EXCLUDE_KEY, LEARNING_ADMIT_KEY,
)


def _literal_end(text: str, start: int) -> int:
    """Index just past the Python literal beginning at `start`.

    Walks quotes (with escapes) and bracket depth, and stops on the comma that
    closes the value at depth 0 — the same rule repr() wrote it with."""
    i, depth, quote = start, 0, ''
    while i < len(text):
        c = text[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                quote = ''
        elif c in "'\"":
            quote = c
        elif c in '([{':
            depth += 1
        elif c in ')]}':
            if depth == 0:
                return i
            depth -= 1
        elif c == ',' and depth == 0:
            return i
        i += 1
    return len(text)


def read_alog_meta(path: Path) -> dict | None:
    """Read just the fields the list audit needs, without parsing the curves.

    Returns a dict usable by audit_alog/learning_state, or None if the file
    cannot be read — the caller then falls back to a full parse."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    meta: dict = {}
    for key in _META_KEYS:
        needle = f"'{key}': "
        pos = text.find(needle)
        # Only accept the key where a dict entry can actually start, so the same
        # text appearing inside a value (a bean note, a comment) is not read as
        # a field. Artisan writes the profile as one flat dict.
        while pos > 0 and not (text[pos - 1] == '{'
                               or text[pos - 2:pos] == ', '):
            pos = text.find(needle, pos + 1)
        if pos < 0:
            continue
        start = pos + len(needle)
        try:
            meta[key] = ast.literal_eval(text[start:_literal_end(text, start)])
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return None
    return meta


def match_bean(data: dict, beans: list[GreenBean]) -> GreenBean | None:
    """Auto-match a green bean: UUID first, then bean name as a title substring."""
    field = data.get('beans', '') or ''
    m = _UUID_RE.search(field)
    if m:
        u = m.group(1)
        for b in beans:
            if b.uuid and b.uuid == u:
                return b
    title = (data.get('title') or '').strip().lower()
    if title:
        for b in beans:
            if b.name and b.name.lower() in title:
                return b
    return None


def selectable_roaster_name(
    stored: object, available: list[str], fallback: object = '',
) -> str:
    """Resolve full name, legacy alias or unique model; otherwise stay empty."""
    by_fold = {name.casefold(): name for name in available}
    for raw in (stored, fallback):
        candidate = canonical_roaster_name(str(raw or ''))
        if not candidate:
            continue
        exact = by_fold.get(candidate.casefold())
        if exact is not None:
            return exact
        suffix = f' {candidate}'.casefold()
        model_matches = [name for name in available if name.casefold().endswith(suffix)]
        if len(model_matches) == 1:
            return model_matches[0]
    return ''


def _safe_float(v: object) -> float:
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return 0.0


def _roast_suffix(data: dict) -> str:
    iso = (data.get('roastisodate') or '').strip()
    rt  = (data.get('roasttime') or '00:00:00').strip()
    if iso:
        try:
            return datetime.fromisoformat(f"{iso}T{rt}").strftime('%y-%m-%d_%H%M')
        except ValueError:
            pass
    ep = data.get('roastepoch')
    if ep:
        try:
            return datetime.fromtimestamp(int(ep)).strftime('%y-%m-%d_%H%M')
        except (TypeError, ValueError, OSError):
            pass
    return datetime.now().strftime('%y-%m-%d_%H%M')


# ─────────────────────────────────────────────────────────────────────────────
# Agtron quick-picker popup
# ─────────────────────────────────────────────────────────────────────────────

class _AgtronPicker(QDialog):
    """Tiny popup listing the SCA roast levels; returns the median Agtron value
    of the chosen range when an exact reading is not available."""

    picked = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(None)  # parent=None: avoid Qt embedding on macOS
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self._drag_pos: QPoint | None = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("agtronRoot")
        container.setStyleSheet(
            f"#agtronRoot {{ background-color: {THEME['BG']}; border: 2px solid {THEME['ACCENT']};"
            f" border-radius: 14px; }}"
            f"QLabel {{ color: {THEME['TEXT']};"
            f" background: transparent; }}"
            f"QPushButton {{ text-align:left; padding:6px 10px;"
            f" border:1px solid {THEME['BORDER']}; border-radius:6px;"
            f" background:{THEME['SURFACE']}; color:{THEME['TEXT']}; }}"
            f"QPushButton:hover {{ background:{THEME['ACCENT']}; color:{THEME['BG']}; }}"
        )
        outer.addWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(14, 10, 14, 14)
        lay.setSpacing(6)

        # title bar
        bar = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate("tilauscope_repair", "Agtron estimate"))
        title_lbl.setStyleSheet(
            f"font-size:13px; font-weight:bold; color:{THEME['ACCENT']}; background:transparent;")
        btn_x = QPushButton("\u2715")
        btn_x.setFixedSize(24, 24)
        btn_x.setProperty('variant', 'icon')   # fixed size: no base padding
        btn_x.setStyleSheet(
            f"QPushButton {{ background:{THEME['BORDER']}; color:{THEME['TEXT']};"
            f" border-radius:12px; font-size:13px; font-weight:bold; text-align:center; }}"
            f"QPushButton:hover {{ background:{THEME['CRITICAL']}; color:{THEME['BG']}; }}")
        btn_x.clicked.connect(self.reject)
        bar.addWidget(title_lbl)
        bar.addStretch(1)
        bar.addWidget(btn_x)
        lay.addLayout(bar)

        hint = QLabel(QApplication.translate(
            "tilauscope_repair",
            "Pick a roast level to prefill the median Agtron of its range."))
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; background: transparent;")
        lay.addWidget(hint)

        for scale in reversed(AGTRON_SCALES):  # light -> dark
            rng = scale.agtron_range
            median = round((rng.min_value + rng.max_value) / 2.0, 1)
            btn = QPushButton(f"{scale.name}  \u00b7  {scale.description}   ({median} Agtron)")
            btn.clicked.connect(lambda _=False, v=median: self._choose(v))
            lay.addWidget(btn)

    def _choose(self, value: float) -> None:
        self.picked.emit(value)
        self.accept()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_pos = None


def stamp_device_map(data: dict, tilau_devices: dict) -> bool:
    """Reconstruct tilau_name_map from extraname1 labels for legacy alogs that
    pre-date the automatic stamping (saved before Approche-B was deployed).
    Returns True when at least one slot was mapped, False when nothing changed."""
    extradevices: list = data.get('extradevices') or []
    extraname1:   list = data.get('extraname1')   or []
    label_to_key: dict[str, str] = {d['label']: k for k, d in tilau_devices.items()}
    name_map: dict[int, str] = {}
    for slot_i in range(min(len(extradevices), len(extraname1))):
        label = extraname1[slot_i]
        if label in label_to_key:
            name_map[slot_i] = label_to_key[label]
    if not name_map:
        return False
    data['tilau_name_map'] = name_map
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Main dialog
# ─────────────────────────────────────────────────────────────────────────────

class AlogRepairDialog(QDialog):
    """Master/detail window to complete incomplete .alog files."""

    # emitted after a successful record with the new file path (str)
    repaired = pyqtSignal(str)

    _ROLE_PATH       = Qt.ItemDataRole.UserRole
    _ROLE_INCOMPLETE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, beancave: 'BeancaveDlg', aw: 'ApplicationWindow') -> None:
        super().__init__(None)  # parent=None: avoid Qt embedding on macOS
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self._bc = beancave
        self._aw = aw
        self._current_path: Path | None = None
        self._current_data: dict | None = None
        self._loading = False          # True while populating (suppresses dirty)
        self._dirty = False            # unsaved edits on the current file
        self._suppress_select = False  # guards programmatic selection changes
        self._drag_pos: QPoint | None = None
        # List-row metadata cache: path -> (mtime, size, missing, learning state).
        # BeanCave's own alog cache is capped at 5 entries, so without this every
        # Record re-read and literal_eval'd the WHOLE directory just to redraw the
        # list. Keyed on mtime+size, so an externally edited file still refreshes.
        self._meta_cache: dict[str, tuple[float, int, list[str], str]] = {}
        # Incremental directory scan state — see _reload_file_list / _scan_step.
        self._scan_files: list[Path] = []
        self._scan_idx = 0
        self._scan_incomplete = 0
        self._scan_shown = 0
        self._scan_seen: set[str] = set()
        self._scan_dir: Path | None = None
        self._scan_active = False
        self._pending_select: Path | None = None
        self._pending_prev_row = -1

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(880, 600)

        self._build_ui()
        # The scan starts from showEvent, once the window is actually on
        # screen — opening it by mistake must not cost a wait.
        self._first_show = True

    # ── styling ────────────────────────────────────────────────────────────
    def _style(self) -> str:
        crit = THEME['CRITICAL']
        return f"""
            QDialog, QWidget {{ background-color:{THEME['BG']}; color:{THEME['TEXT']};
                }}
            QLineEdit, QComboBox, QPlainTextEdit {{ background-color:{THEME['SURFACE']};
                color:{THEME['TEXT']}; border:1px solid {THEME['BORDER']};
                border-radius:6px; padding:5px 8px; font-size:12px; }}
            QLineEdit:focus, QComboBox:focus {{ border:1px solid {THEME['ACCENT']}; }}
            QListWidget {{ background-color:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};
                border-radius:6px; font-size:12px; }}
            QListWidget::item:selected {{ background-color:{THEME['ACCENT']}; color:{THEME['BG']}; }}
            QCheckBox {{ color:{THEME['SUBTEXT']}; font-size:11px; }}
            QScrollArea {{ background:transparent; border:none; }}
            QProgressBar {{ background-color:{THEME['SURFACE']}; color:{THEME['TEXT']};
                border:1px solid {THEME['BORDER']}; border-radius:7px;
                font-size:9px; text-align:center; }}
            QProgressBar::chunk {{ background-color:{THEME['ACCENT']}; border-radius:6px; }}
            QScrollBar:vertical {{ background:transparent; width:10px; margin:0px; }}
            QScrollBar::handle:vertical {{ background:{THEME['BORDER']};
                border-radius:5px; min-height:28px; }}
            QScrollBar::handle:vertical:hover {{ background:{THEME['ACCENT']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
            QLabel {{ background:transparent; }}
            QPushButton {{
                background:{THEME['SURFACE']}; color:{THEME['TEXT']};
                border:1px solid {THEME['BORDER']}; border-radius:7px;
                padding:9px 18px; font-size:12px; }}
            QPushButton:hover {{
                background:{THEME['ACCENT']}; color:{THEME['BG']};
                border-color:{THEME['ACCENT']}; }}
            QPushButton:pressed {{
                background:{THEME['BORDER']}; }}
            QPushButton:disabled {{
                color:{THEME['SUBTEXT']}; border-color:{THEME['BORDER']}; }}
            QPushButton#btnPrimary {{
                background:{THEME['ACCENT']}; color:{THEME['BG']};
                border:none; font-weight:bold; padding:9px 24px; }}
            QPushButton#btnPrimary:hover {{
                background:{THEME['TEXT']}; color:{THEME['BG']}; }}
            QPushButton#btnPrimary:pressed {{
                background:{THEME['BORDER']}; }}
            QPushButton#btnGhost {{
                color:{THEME['SUBTEXT']}; background:transparent; border-color:transparent; }}
            QPushButton#btnGhost:hover {{
                color:{THEME['TEXT']}; background:{THEME['SURFACE']};
                border-color:{THEME['BORDER']}; }}
            QPushButton#btnClose {{
                background:{THEME['BORDER']}; color:{THEME['TEXT']};
                border-radius:13px; font-size:14px; font-weight:bold;
                border:none; padding:0px; }}
            QPushButton#btnClose:hover {{
                background:{crit}; color:{THEME['BG']}; }}
        """

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty('variant', 'eyebrow')
        return lbl

    @staticmethod
    def _line_style(border: str) -> str:
        return (f"QLineEdit {{ background-color:{THEME['SURFACE']}; color:{THEME['TEXT']};"
                f"border:1px solid {border}; border-radius:6px; padding:5px 8px; font-size:12px; }}"
                f"QLineEdit:focus {{ border:1px solid {THEME['ACCENT']}; }}")

    @staticmethod
    def _text_style(border: str) -> str:
        return (f"QPlainTextEdit {{ background-color:{THEME['SURFACE']}; color:{THEME['TEXT']};"
                f"border:1px solid {border}; border-radius:6px; padding:5px 8px; font-size:12px; }}")

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("alogRoot")
        self.container.setStyleSheet(
            f"#alogRoot {{ background-color: {THEME['BG']}; border: 2px solid {THEME['ACCENT']};"
            f" border-radius: 16px; }}" + self._style())
        outer.addWidget(self.container)

        root = QVBoxLayout(self.container)
        root.setContentsMargins(16, 10, 16, 14)
        root.setSpacing(10)

        # custom title bar (drag handle + close)
        bar = QHBoxLayout()
        title_lbl = QLabel(
            QApplication.translate(
                "tilauscope_repair", "\U0001f527  Roast Profile Maintenance"))
        title_lbl.setStyleSheet(
            f"font-size:15px; font-weight:bold; color:{THEME['ACCENT']}; background:transparent;")
        btn_x = QPushButton("\u2715")
        btn_x.setFixedSize(26, 26)
        btn_x.setProperty('variant', 'icon')   # fixed size: no base padding
        btn_x.setObjectName("btnClose")
        btn_x.clicked.connect(self.close)
        bar.addWidget(title_lbl)
        bar.addStretch(1)
        bar.addWidget(btn_x)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # left: file list + filter
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self._summary_lbl = QLabel("")
        self._summary_lbl.setProperty('variant', 'caption')
        left_lay.addWidget(self._summary_lbl)

        # Scan progress + cancel. Hidden when idle; the button turns into
        # "scan again" after a cancelled pass so a partial list is never a
        # dead end.
        self._scan_row = QWidget()
        scan_lay = QHBoxLayout(self._scan_row)
        scan_lay.setContentsMargins(0, 0, 0, 0)
        scan_lay.setSpacing(6)
        # Bar only: the count lives in _summary_lbl just below, as
        # "Reading roast files… 47 / 312".
        self._scan_bar = TilauProgress(TilauProgress.BAR)
        self._scan_bar.setRange(0, 100)
        self._scan_btn = QPushButton(QApplication.translate("tilauscope_repair", "Cancel"))
        self._scan_btn.setObjectName("btnGhost")
        self._scan_btn.setToolTip(QApplication.translate(
            "tilauscope_repair", "Stop reading the roast files. Those already read stay listed."))
        self._scan_btn.clicked.connect(self._on_scan_button)
        scan_lay.addWidget(self._scan_bar, 1)
        scan_lay.addWidget(self._scan_btn)
        self._scan_row.setVisible(False)
        left_lay.addWidget(self._scan_row)
        self._incomplete_only = QCheckBox(
            QApplication.translate("tilauscope_repair", "Show incomplete only"))
        self._incomplete_only.toggled.connect(lambda _on: self._reload_file_list())
        left_lay.addWidget(self._incomplete_only)
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)
        left_lay.addWidget(self._list, 1)
        splitter.addWidget(left)

        # right: editor
        right = QWidget()
        form = QVBoxLayout(right)
        form.setSpacing(7)

        # ── Learning state of the selected roast ─────────────────────────────
        # Segmented control so the state reads directly off the row; written to
        # the file immediately (no Record). Sits at the top as a verdict on the
        # whole roast, not one more field.
        learn_row = QHBoxLayout()
        learn_row.setSpacing(6)
        learn_lbl = self._field_label(QApplication.translate(
            "tilauscope_repair", "PLAN LEARNING"))
        learn_row.addWidget(learn_lbl)
        self._learn_group = QButtonGroup(self)
        self._learn_group.setExclusive(True)
        self._learn_btns: dict[str, QPushButton] = {}
        for state, label, colour, tip in (
            (LEARNING_ADMITTED,
             QApplication.translate("tilauscope_repair", "✓ Admitted"),
             THEME['SUCCESS'],
             QApplication.translate(
                 "tilauscope_repair",
                 "You have checked this roast and it is sound: the plan learns from it, and you can see at a glance that it was reviewed.")),
            (LEARNING_UNREVIEWED,
             QApplication.translate("tilauscope_repair", "– Not reviewed"),
             THEME['SUBTEXT'],
             QApplication.translate(
                 "tilauscope_repair",
                 "No decision recorded. The plan still learns from this roast — an imperfect roast teaches something too. This is the state of every file you have never opened.")),
            (LEARNING_EXCLUDED,
             QApplication.translate("tilauscope_repair", "\U0001f6ab Excluded"),
             THEME['CRITICAL'],
             QApplication.translate(
                 "tilauscope_repair",
                 "Plan learning skips this roast entirely: first crack, phase timings, colour response, heater profile and the master curve all ignore it.")),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                # tighter than the default button padding: the three states plus
                # their label share a single line
                "QPushButton { padding:6px 10px; font-size:11px; }"
                f"QPushButton:checked {{ border:1.5px solid {colour};"
                f" color:{colour}; background-color: {tint('TEXT', 0.06)}; }}")
            btn.clicked.connect(
                lambda _checked=False, s=state: self._set_learning_state(s))
            self._learn_group.addButton(btn)
            self._learn_btns[state] = btn
            learn_row.addWidget(btn)
        learn_row.addStretch(1)
        form.addLayout(learn_row)

        # status summary (missing / plausibility)
        self._missing_lbl = QLabel("")
        self._missing_lbl.setWordWrap(True)
        self._missing_lbl.setStyleSheet(f"color:{THEME['WARNING']}; font-size:11px;")
        form.addWidget(self._missing_lbl)
        self._check_lbl = QLabel("")
        self._check_lbl.setWordWrap(True)
        self._check_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px; font-style:italic;")
        form.addWidget(self._check_lbl)

        # bean link row
        bean_row = QHBoxLayout()
        self._bean_combo = QComboBox()
        self._bean_combo.currentIndexChanged.connect(self._on_field_changed)
        bean_row.addWidget(QLabel(QApplication.translate("tilauscope_repair", "Green bean:")))
        bean_row.addWidget(self._bean_combo, 1)
        form.addLayout(bean_row)

        self._complete_btn = QPushButton(
            QApplication.translate("tilauscope_repair", "Complete from bean (empty fields only)"))
        self._complete_btn.clicked.connect(self._complete_from_bean)
        form.addWidget(self._complete_btn)

        # title
        form.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "TITLE")))
        self._title_edit = QLineEdit()
        form.addWidget(self._title_edit)

        # roaster identity persisted by Artisan (optional when unlisted)
        form.addWidget(self._field_label(QApplication.translate(
            "tilauscope_repair", "ROASTER")))
        self._roaster_combo = QComboBox()
        self._roaster_combo.addItem(QApplication.translate(
            "tilauscope_repair", "— not listed / leave empty —"), userData='')
        for roaster_name in RoasterManager().get_roaster_list():
            self._roaster_combo.addItem(roaster_name, userData=roaster_name)
        form.addWidget(self._roaster_combo)

        # beans
        form.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "BEANS")))
        self._beans_edit = QPlainTextEdit()
        self._beans_edit.setFixedHeight(82)
        form.addWidget(self._beans_edit)

        # numeric grid
        self._w_in_edit     = QLineEdit()
        self._w_out_edit    = QLineEdit()
        self._density_edit  = QLineEdit()
        self._moisture_edit = QLineEdit()
        self._greens_edit   = QLineEdit()
        self._ambient_edit  = QLineEdit()
        self._humidity_edit = QLineEdit()
        self._whole_edit    = QLineEdit()
        self._ground_edit   = QLineEdit()
        self._color_sys_combo = QComboBox()
        for sys_name in self._color_systems():
            self._color_sys_combo.addItem(sys_name)

        self._w_in_lbl  = self._field_label("WEIGHT IN (g)")
        self._w_out_lbl = self._field_label("WEIGHT OUT (g)")
        self._loss_lbl  = QLabel("\u2014")
        self._loss_lbl.setProperty('variant', 'secondary')

        self._density_edit.setPlaceholderText("550\u2013900")
        self._moisture_edit.setPlaceholderText("8\u201314")
        self._greens_edit.setPlaceholderText("\u00b0C")
        self._ambient_edit.setPlaceholderText("\u00b0C")
        self._humidity_edit.setPlaceholderText("20\u201380")
        self._density_edit.setToolTip(QApplication.translate(
            "tilauscope_repair", "Green bean density, typical 550\u2013900 g/l"))
        self._moisture_edit.setToolTip(QApplication.translate(
            "tilauscope_repair", "Green moisture, typical 8\u201314 %"))
        self._ambient_edit.setToolTip(QApplication.translate(
            "tilauscope_repair", "Ambient temperature at roast (feeds historical analysis)"))
        self._humidity_edit.setToolTip(QApplication.translate(
            "tilauscope_repair", "Ambient humidity at roast (feeds historical analysis)"))

        grid = QGridLayout()
        grid.addWidget(self._w_in_lbl,  0, 0)
        grid.addWidget(self._w_out_lbl, 0, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "WEIGHT LOSS")), 0, 2)
        grid.addWidget(self._w_in_edit,  1, 0)
        grid.addWidget(self._w_out_edit, 1, 1)
        grid.addWidget(self._loss_lbl,   1, 2)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "DENSITY")),    2, 0)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "MOISTURE %")), 2, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "GREENS TEMP")),2, 2)
        grid.addWidget(self._density_edit,  3, 0)
        grid.addWidget(self._moisture_edit, 3, 1)
        grid.addWidget(self._greens_edit,   3, 2)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "AMBIENT \u00b0C")), 4, 0)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "HUMIDITY %")),     4, 1)
        grid.addWidget(self._ambient_edit,  5, 0)
        grid.addWidget(self._humidity_edit, 5, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "COLOR WHOLE")),   6, 0)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "COLOR GROUND")),  6, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "COLOR SYSTEM")),  6, 2)
        grid.addWidget(self._whole_edit,      7, 0)
        grid.addWidget(self._ground_edit,     7, 1)
        grid.addWidget(self._color_sys_combo, 7, 2)
        agtron_btn = QPushButton(QApplication.translate("tilauscope_repair", "Agtron\u2026"))
        agtron_btn.clicked.connect(self._open_agtron)
        grid.addWidget(agtron_btn, 8, 2)
        form.addLayout(grid)

        # filename preview
        form.addWidget(self._field_label(QApplication.translate("tilauscope_repair", "\u2192 NEW FILENAME")))
        self._fname_lbl = QLabel("")
        self._fname_lbl.setWordWrap(True)
        self._fname_lbl.setStyleSheet(
            f"color:{THEME['ACCENT']}; background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};"
            f"border-radius:6px; padding:6px 8px; font-size:11px;")
        form.addWidget(self._fname_lbl)

        form.addStretch(1)

        # buttons
        btn_row = QHBoxLayout()
        self._record_btn = QPushButton(QApplication.translate("tilauscope_repair", "Record"))
        self._record_btn.setObjectName("btnPrimary")
        self._record_btn.clicked.connect(self._record)
        self._next_btn = QPushButton(QApplication.translate("tilauscope_repair", "Next incomplete \u25b8"))
        self._next_btn.clicked.connect(lambda: self._select_next_incomplete(self._list.currentRow()))
        # — batch stamp tilau_name_map on legacy alogs
        self._stamp_btn = QPushButton(
            QApplication.translate("tilauscope_repair", "Stamp device map"))
        self._stamp_btn.setToolTip(QApplication.translate(
            "tilauscope_repair",
            "Rebuild tilau_name_map in all ALogs that pre-date automatic device-index stamping."))
        self._stamp_btn.clicked.connect(self._stamp_device_map_batch)
        close_btn = QPushButton(QApplication.translate("tilauscope_repair", "Close"))
        close_btn.setObjectName("btnGhost")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._record_btn)
        btn_row.addWidget(self._next_btn)
        btn_row.addWidget(self._stamp_btn)
        btn_row.addWidget(close_btn)
        btn_row.addStretch(1)

        # The fields grow with the content (learning row, plausibility warnings,
        # filename preview): give them a vertical scroller rather than letting
        # them be squeezed out of the window. The action buttons stay OUTSIDE
        # the scroller — Record must never be something you have to scroll to.
        right_scroll = QScrollArea()
        right_scroll.setWidget(right)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right.setMinimumWidth(420)

        right_pane = QWidget()
        right_lay = QVBoxLayout(right_pane)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)
        right_lay.addWidget(right_scroll, 1)
        right_lay.addLayout(btn_row)
        splitter.addWidget(right_pane)
        splitter.setSizes([320, 560])

        # QSizeGrip anchored to bottom-right of the container
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        grip = QSizeGrip(self.container)
        grip_row.addWidget(grip)
        root.addLayout(grip_row)

        # live status + dirty tracking
        for w in (self._title_edit, self._w_in_edit, self._w_out_edit, self._density_edit,
                  self._moisture_edit, self._greens_edit, self._ambient_edit,
                  self._humidity_edit, self._whole_edit, self._ground_edit):
            w.textChanged.connect(self._on_field_changed)
        self._beans_edit.textChanged.connect(self._on_field_changed)
        self._roaster_combo.currentIndexChanged.connect(self._on_field_changed)
        self._color_sys_combo.currentIndexChanged.connect(self._on_field_changed)

        self._set_editor_enabled(False)

    # ── list population (incremental, cancellable) ──────────────────────────
    def _reload_file_list(self, select_after: Path | None = None,
                          prev_row: int = -1) -> None:
        """Start a fresh scan of the ALog directory.

        Auditing a profile means parsing the whole file, so a large archive
        cannot be read in one go without freezing the window for seconds. The
        scan therefore runs in slices on the event loop: rows appear as they are
        read, progress is reported, and the user can stop it at any point.
        `select_after` is applied once the scan ends (or is cancelled)."""
        self._scan_active = False          # halt any in-flight scan
        self._pending_select = select_after
        self._pending_prev_row = prev_row
        self._suppress_select = True
        self._list.clear()
        self._suppress_select = False
        directory = Path(self._bc.alog_directory) if self._bc.alog_directory else None
        if not directory or not directory.is_dir():
            self._scan_row.setVisible(False)
            self._summary_lbl.setText(QApplication.translate(
                "tilauscope_repair", "ALog directory not set."))
            return
        self._scan_dir = directory
        self._scan_files = sorted(directory.glob("*.alog"), key=lambda p: p.name.lower())
        self._scan_idx = 0
        self._scan_incomplete = 0
        self._scan_shown = 0
        self._scan_seen = set()
        self._scan_active = True
        self._scan_bar.setValue(0)
        self._scan_btn.setText(QApplication.translate("tilauscope_repair", "Cancel"))
        self._scan_btn.setToolTip(QApplication.translate(
            "tilauscope_repair", "Stop reading the roast files. Those already read stay listed."))
        # The progress row is a safety net, not the normal experience: a folder
        # is read in a few tens of milliseconds, and a bar that flashes for that
        # long is worse than no bar. It only appears if the reading is still
        # going after a moment — a huge folder, or a slow network volume.
        self._scan_row.setVisible(False)
        QTimer.singleShot(400, self._show_progress_if_still_scanning)
        self._scan_step()

    def _show_progress_if_still_scanning(self) -> None:
        if self._scan_active and self._scan_files:
            self._scan_row.setVisible(True)

    def _scan_step(self) -> None:
        """Read one time-boxed slice of the directory, then yield back to Qt."""
        if not self._scan_active:
            return
        total = len(self._scan_files)
        deadline = time.monotonic() + 0.04   # ~40 ms of work, then repaint
        while self._scan_idx < total:
            self._scan_file(self._scan_files[self._scan_idx])
            self._scan_idx += 1
            if time.monotonic() >= deadline:
                break
        self._scan_bar.setValue(int(self._scan_idx * 100 / total) if total else 100)
        if self._scan_row.isVisible():
            self._summary_lbl.setText(QApplication.translate(
                "tilauscope_repair", "Reading roast files… {0} / {1}").format(
                    self._scan_idx, total))
        if self._scan_idx >= total:
            self._finish_scan(cancelled=False)
        else:
            # 1 ms rather than 0: a chain of zero timers can outrun the platform
            # run loop and starve the very repaints this slicing exists for.
            QTimer.singleShot(1, self._scan_step)

    def _scan_file(self, fp: Path) -> None:
        """Audit one file and append its row, unless the filter hides it."""
        key = str(fp)
        self._scan_seen.add(key)
        try:
            st = fp.stat()
            stamp = (st.st_mtime, st.st_size)
        except OSError:
            return
        cached = self._meta_cache.get(key)
        if cached is not None and (cached[0], cached[1]) == stamp:
            missing, _state = list(cached[2]), cached[3]
        else:
            # Targeted read: the audit needs a dozen fields, not the curves.
            # Falls back to the full parse if the file will not give them up.
            data = read_alog_meta(fp) or self._bc.get_alog_data(fp)
            if data is None:
                return
            missing = audit_alog(data)
            _state = learning_state(data)
            self._meta_cache[key] = (stamp[0], stamp[1], list(missing), _state)
        is_incomplete = bool(missing)
        if is_incomplete:
            self._scan_incomplete += 1
        if self._incomplete_only.isChecked() and not is_incomplete:
            return
        item = QListWidgetItem(fp.name)
        item.setData(self._ROLE_PATH, str(fp))
        item.setData(self._ROLE_INCOMPLETE, is_incomplete)
        if 'beans_uuid' in missing:
            item.setForeground(QColor(THEME['CRITICAL']))
            item.setText(f"\u2716  {fp.name}")
        elif missing:
            item.setForeground(QColor(THEME['WARNING']))
            item.setText(f"\u26A0  {fp.name}  ({len(missing)})")
        else:
            item.setForeground(QColor(THEME['SUCCESS']))
            item.setText(f"\u2713  {fp.name}")
        # Learning state as a suffix badge: 🚫 excluded, ✅ reviewed and
        # admitted, nothing for a file no one has ruled on yet. The prefix
        # (✓ ⚠ ✖) already says whether the METADATA is complete — a
        # different question entirely, and the two must stay readable apart.
        if _state == LEARNING_EXCLUDED:
            item.setText(item.text() + "  \U0001f6ab")
        elif _state == LEARNING_ADMITTED:
            item.setText(item.text() + "  ✅")
        self._list.addItem(item)
        self._scan_shown += 1

    def _finish_scan(self, cancelled: bool) -> None:
        self._scan_active = False
        if cancelled:
            self._scan_btn.setText(QApplication.translate("tilauscope_repair", "Scan again"))
            self._scan_btn.setToolTip(QApplication.translate(
                "tilauscope_repair", "Read the roast files that were left out."))
            self._summary_lbl.setText(QApplication.translate(
                "tilauscope_repair",
                "Stopped \u00b7 {0} of {1} files read \u00b7 {2} incomplete").format(
                    self._scan_idx, len(self._scan_files), self._scan_incomplete))
        else:
            self._scan_row.setVisible(False)
            # Only a full pass knows which files are really gone, and only for the
            # folder it just walked: pruning after a partial pass, or across
            # folders, would drop metadata that is still valid.
            scanned = self._scan_dir
            for stale in [k for k in self._meta_cache
                          if k not in self._scan_seen
                          and scanned is not None and Path(k).parent == scanned]:
                del self._meta_cache[stale]
            self._summary_lbl.setText(QApplication.translate(
                "tilauscope_repair", "{0} files \u00b7 {1} incomplete \u00b7 {2} shown").format(
                    len(self._scan_files), self._scan_incomplete, self._scan_shown))
        if self._pending_select is not None:
            target, prev_row = self._pending_select, self._pending_prev_row
            self._pending_select = None
            self._pending_prev_row = -1
            if not self._reselect(target) and prev_row >= 0:
                self._select_next_incomplete(prev_row)

    def _on_scan_button(self) -> None:
        """Cancel an in-flight scan, or restart one after a cancelled pass."""
        if self._scan_active:
            self._finish_scan(cancelled=True)
        else:
            self._reload_file_list()

    # ── selection (with unsaved-changes guard) ──────────────────────────────
    @pyqtSlot()
    def _on_select(self) -> None:
        if self._suppress_select:
            return
        item = self._list.currentItem()
        if item is None:
            self._set_editor_enabled(False)
            return
        path = Path(item.data(self._ROLE_PATH))

        # guard unsaved edits before switching away
        if self._dirty and self._current_path is not None and path != self._current_path:
            if not self._confirm(
                    QApplication.translate("tilauscope_repair", "Unsaved changes"),
                    QApplication.translate("tilauscope_repair",
                        "Discard unsaved changes to this profile?")):
                self._reselect(self._current_path)
                return

        data = self._bc.get_alog_data(path)
        if data is None:
            self._set_editor_enabled(False)
            return
        self._current_path = path
        self._current_data = dict(data)  # copy; not committed until Record
        self._populate_editor(self._current_data)
        self._set_editor_enabled(True)
        # état d'apprentissage du fichier sélectionné — setChecked n'émet pas
        # clicked(), donc parcourir la liste ne réécrit jamais un fichier.
        # C'est exactement ce qui manquait à l'ancien bouton unique : son état
        # se lisait comme une commande, et un clic sur un fichier non marqué le
        # faisait basculer dans l'état inverse de celui qu'on croyait poser.
        self._learn_btns[learning_state(data)].setChecked(True)

    def _populate_editor(self, data: dict) -> None:
        self._loading = True
        unit = self._weight_unit(data)
        self._w_in_lbl.setText(QApplication.translate(
            "tilauscope_repair", "WEIGHT IN ({0})").format(unit))
        self._w_out_lbl.setText(QApplication.translate(
            "tilauscope_repair", "WEIGHT OUT ({0})").format(unit))

        self._title_edit.setText(data.get('title', '') or '')
        self._beans_edit.setPlainText(data.get('beans', '') or '')
        available_roasters = [str(self._roaster_combo.itemData(i) or '')
                              for i in range(1, self._roaster_combo.count())]
        selected_roaster = selectable_roaster_name(
            data.get('roastertype'), available_roasters, data.get('machinesetup'))
        roaster_idx = self._roaster_combo.findData(selected_roaster)
        self._roaster_combo.setCurrentIndex(max(0, roaster_idx))

        w = data.get('weight') or []
        self._w_in_edit.setText(self._fmt(w[0]) if len(w) > 0 else '')
        self._w_out_edit.setText(self._fmt(w[1]) if len(w) > 1 else '')
        dens = data.get('density') or []
        self._density_edit.setText(self._fmt(dens[0]) if dens else '')
        self._moisture_edit.setText(self._fmt(data.get('moisture_greens')))
        self._greens_edit.setText(self._fmt(data.get('greens_temp')))
        self._ambient_edit.setText(self._fmt(data.get('ambientTemp')))
        self._humidity_edit.setText(self._fmt(data.get('ambient_humidity')))
        self._whole_edit.setText(self._fmt(data.get('whole_color')))
        self._ground_edit.setText(self._fmt(data.get('ground_color')))

        # color system
        cs = (data.get('color_system') or '').strip()
        idx = self._color_sys_combo.findText(cs) if cs else -1
        self._color_sys_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # bean combo + auto-match
        beans = self._green_beans()
        self._bean_combo.blockSignals(True)
        self._bean_combo.clear()
        self._bean_combo.addItem(QApplication.translate("tilauscope_repair", "\u2014 none \u2014"), userData=None)
        matched = match_bean(data, beans)
        sel_idx = 0
        for i, b in enumerate(beans, start=1):
            self._bean_combo.addItem(b.name or b.uuid or f"bean {i}", userData=b)
            if matched is not None and b is matched:
                sel_idx = i
        self._bean_combo.setCurrentIndex(sel_idx)
        self._bean_combo.blockSignals(False)

        self._loading = False
        self._dirty = False
        self._refresh_status()
        self._update_filename_preview()

    # ── complete from bean (empty fields only; rebuild beans for the link) ──
    @pyqtSlot()
    def _complete_from_bean(self) -> None:
        bean = self._bean_combo.currentData()
        if bean is None:
            show_styled_message(
                self,
                QApplication.translate("tilauscope_repair", "No bean"),
                QApplication.translate("tilauscope_repair", "Select a green bean first."),
                QMessageBox.Icon.Information)
            return

        # beans: rebuild only when the link (uuid) is missing - this is the purpose
        if not _UUID_RE.search(self._beans_edit.toPlainText() or ''):
            self._beans_edit.setPlainText(build_beans_field(bean))
        # title: fill only if empty
        if not self._title_edit.text().strip():
            crop = str(bean.crop) if bean.crop else 'N/A'
            self._title_edit.setText(f"{bean.name} - {bean.process} - {crop}".strip(' -'))
        # metadata: fill only if empty
        if _safe_float(self._density_edit.text()) == 0.0 and bean.density:
            self._density_edit.setText(f"{bean.density:.1f}")
        if _safe_float(self._moisture_edit.text()) == 0.0 and bean.last_humidity:
            self._moisture_edit.setText(f"{bean.last_humidity:.1f}")

    # ── agtron popup ────────────────────────────────────────────────────────
    @pyqtSlot()
    def _open_agtron(self) -> None:
        picker = _AgtronPicker(self)
        picker.picked.connect(self._apply_agtron)
        picker.exec()

    def _apply_agtron(self, value: float) -> None:
        if _safe_float(self._whole_edit.text()) == 0.0:
            self._whole_edit.setText(f"{value:.1f}")
        elif _safe_float(self._ground_edit.text()) == 0.0:
            self._ground_edit.setText(f"{value:.1f}")

    @pyqtSlot()
    def _stamp_device_map_batch(self) -> None:
        """Iterate every alog in the directory; write tilau_name_map for files
        that contain TilauScope devices (identified by extraname1 label) but
        lack the map key.  Skips files that already have the key."""
        directory = Path(self._bc.alog_directory) if self._bc.alog_directory else None
        if not directory or not directory.is_dir():
            show_styled_message(
                self,
                QApplication.translate("tilauscope_repair", "No directory"),
                QApplication.translate("tilauscope_repair", "ALog directory not set."),
                QMessageBox.Icon.Warning)
            return

        tilau_devices = getattr(getattr(self._aw, 'qmc', None), 'tilau_devices', {})
        if not tilau_devices:
            _log.warning("stamp_device_map_batch: tilau_devices not available")
            return

        files = sorted(directory.glob("*.alog"))
        total = len(files)
        if total == 0:
            return

        progress = QProgressDialog(
            QApplication.translate("tilauscope_repair", "Stamping device map…"),
            QApplication.translate("tilauscope_repair", "Cancel"),
            0, total, self,
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        stamped = 0
        skipped = 0
        errors  = 0

        for idx, fp in enumerate(files):
            if progress.wasCanceled():
                break
            progress.setLabelText(
                QApplication.translate(
                    "tilauscope_repair", "Processing {0}…").format(fp.name))
            progress.setValue(idx)
            QApplication.processEvents()

            data = self._bc.get_alog_data(fp)
            if data is None:
                errors += 1
                continue
            # compute the expected map regardless of whether one is already stored
            expected: dict[int, str] = {}
            extradevices: list = data.get('extradevices') or []
            extraname1:   list = data.get('extraname1')   or []
            label_to_key: dict[str, str] = {d['label']: k for k, d in tilau_devices.items()}
            for slot_i in range(min(len(extradevices), len(extraname1))):
                lbl = extraname1[slot_i]
                if lbl in label_to_key:
                    expected[slot_i] = label_to_key[lbl]
            if not expected:
                # no TilauScope devices in this file
                continue
            # normalise stored map keys to int for comparison
            stored = {int(k): v for k, v in (data.get('tilau_name_map') or {}).items()}
            if stored == expected:
                skipped += 1
                continue
            data['tilau_name_map'] = expected
            try:
                write_alog(data, fp)
                stamped += 1
                _log.info("tilau_name_map stamped: %s", fp.name)
            except Exception as exc:  # pylint: disable=broad-except
                _log.error("stamp_device_map_batch write error %s: %s", fp.name, exc)
                errors += 1

        progress.setValue(total)

        msg = QApplication.translate(
            "tilauscope_repair",
            "{0} file(s) stamped · {1} already up-to-date · {2} error(s)").format(
                stamped, skipped, errors)
        show_styled_message(
            self,
            QApplication.translate("tilauscope_repair", "Stamp device map"),
            msg,
            QMessageBox.Icon.Information)
        if stamped:
            self._reload_file_list()
    @pyqtSlot()
    def _record(self) -> None:
        if self._current_data is None or self._current_path is None:
            return

        # hard validation: roasted weight cannot meet/exceed green weight
        wi = _safe_float(self._w_in_edit.text())
        wo = _safe_float(self._w_out_edit.text())
        if wi > 0.0 and wo > 0.0 and wo >= wi:
            show_styled_message(
                self,
                QApplication.translate("tilauscope_repair", "Invalid weights"),
                QApplication.translate("tilauscope_repair",
                    "Weight out ({0}) must be lower than weight in ({1}).").format(
                        self._fmt(wo), self._fmt(wi)),
                QMessageBox.Icon.Warning)
            return

        data = self._current_data
        data['title'] = self._title_edit.text().strip()
        data['beans'] = self._beans_edit.toPlainText().strip()

        unit = self._weight_unit(data)
        data['weight'] = [wi, wo, unit]
        dens = list(data.get('density') or [])
        dens_val = _safe_float(self._density_edit.text())
        if len(dens) >= 4:
            dens[0] = dens_val
        else:
            dens = [dens_val, 'g', 1, 'l']  # Artisan density tuple shape
        data['density'] = dens
        data['moisture_greens'] = _safe_float(self._moisture_edit.text())
        data['greens_temp']     = _safe_float(self._greens_edit.text())
        data['ambientTemp']      = _safe_float(self._ambient_edit.text())
        data['ambient_humidity'] = _safe_float(self._humidity_edit.text())
        data['whole_color']     = _safe_float(self._whole_edit.text())
        data['ground_color']    = _safe_float(self._ground_edit.text())
        data['color_system']    = self._color_sys_combo.currentText()
        # TilauScope mirrors this identity into both Artisan machine fields.
        # Empty is intentional when the machine is not explicitly registered.
        roaster_name = str(self._roaster_combo.currentData() or '')
        data['roastertype'] = roaster_name
        data['machinesetup'] = roaster_name

        new_name = build_alog_filename(data)
        new_path = self._current_path.with_name(new_name)

        # collision guard: never silently clobber a different existing file
        if new_path.exists() and new_path.resolve() != self._current_path.resolve():
            if not self._confirm(
                    QApplication.translate("tilauscope_repair", "File exists"),
                    QApplication.translate("tilauscope_repair",
                        "{0} already exists. Overwrite it?").format(new_name)):
                return

        try:
            write_alog(data, new_path)
            if new_path.resolve() != self._current_path.resolve() and self._current_path.exists():
                self._current_path.unlink()
        except Exception as exc:  # noqa: BLE001
            _log.error("ALog repair write failed: %s", exc)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_repair", "Save Error"),
                QApplication.translate("tilauscope_repair",
                    "Could not write the ALog file:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True)
            return

        _log.info("ALog repaired: %s -> %s", self._current_path.name, new_path.name)
        self._dirty = False
        self.repaired.emit(str(new_path))
        prev_row = self._list.currentRow()
        self._current_path = new_path
        # Stay on the file that was just recorded (its row may have moved if the
        # rename changed the sort order). Advancing is the job of "Next
        # incomplete", not of Record. Only when the file left the list — the
        # "incomplete only" filter and it is now complete — do we move on. The
        # selection is applied when the rescan ends, since it runs in slices.
        self._reload_file_list(select_after=new_path, prev_row=prev_row)

    def _set_learning_state(self, state: str) -> None:
        """Pose l'état d'apprentissage sur le fichier sélectionné et écrit
        IMMÉDIATEMENT (pas de Record) : le fichier est relu depuis le disque
        pour ne pas embarquer d'éditions non enregistrées, et seules les clés
        d'état sont touchées. La copie d'édition courante est synchronisée pour
        qu'un Record ultérieur n'écrase pas le choix."""
        if self._current_path is None:
            return
        data = self._bc.get_alog_data(self._current_path)
        if data is None:
            return
        previous = learning_state(data)
        if state == previous:
            return
        try:
            write_alog(apply_learning_state(data, state), self._current_path)
        except Exception as exc:  # noqa: BLE001
            _log.error("ALog learning-state write failed: %s", exc)
            self._learn_btns[previous].setChecked(True)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_repair", "Save Error"),
                QApplication.translate("tilauscope_repair",
                    "Could not write the ALog file:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True)
            return
        if self._current_data is not None:
            self._current_data = apply_learning_state(self._current_data, state)
        item = self._list.currentItem()
        if item is not None:
            base = item.text().replace("  \U0001f6ab", "").replace("  ✅", "")
            item.setText(base + {LEARNING_EXCLUDED: "  \U0001f6ab",
                                 LEARNING_ADMITTED: "  ✅"}.get(state, ""))
        _log.info("ALog %s: plan learning %s -> %s",
                  self._current_path.name, previous, state)

    # ── navigation ───────────────────────────────────────────────────────────
    def _select_next_incomplete(self, from_row: int, fallback: str | None = None) -> None:
        """Select the next incomplete file after from_row (wraps once). Falls back
        to the given path, else leaves the current selection untouched."""
        count = self._list.count()
        order = list(range(from_row + 1, count)) + list(range(0, max(from_row + 1, 0)))
        for r in order:
            it = self._list.item(r)
            if it is not None and it.data(self._ROLE_INCOMPLETE):
                self._list.setCurrentRow(r)
                return
        if fallback is not None:
            self._reselect(Path(fallback))

    def _reselect(self, path: Path) -> bool:
        """Select the row holding `path` without re-entering _on_select.
        Returns False when the file is not in the current (possibly filtered) list."""
        found = False
        self._suppress_select = True
        for r in range(self._list.count()):
            it = self._list.item(r)
            if it.data(self._ROLE_PATH) == str(path):
                self._list.setCurrentRow(r)
                found = True
                break
        self._suppress_select = False
        return found

    # ── live status (highlight + missing + plausibility + weight loss) ───────
    def _on_field_changed(self, *_args) -> None:
        if not self._loading:
            self._dirty = True
        self._refresh_status()
        self._update_filename_preview()

    def _current_values(self) -> dict[str, float]:
        return {
            'density':          _safe_float(self._density_edit.text()),
            'moisture_greens':  _safe_float(self._moisture_edit.text()),
            'greens_temp':      _safe_float(self._greens_edit.text()),
            'whole_color':      _safe_float(self._whole_edit.text()),
            'ambientTemp':      _safe_float(self._ambient_edit.text()),
            'ambient_humidity': _safe_float(self._humidity_edit.text()),
        }

    def _refresh_status(self) -> None:
        warn = THEME['WARNING']
        ok   = THEME['BORDER']

        # field -> is-empty (borders + missing list)
        empties = [
            ('title',            self._title_edit,    not self._title_edit.text().strip()),
            ('weight_in',        self._w_in_edit,     _safe_float(self._w_in_edit.text())    == 0.0),
            ('weight_out',       self._w_out_edit,    _safe_float(self._w_out_edit.text())   == 0.0),
            ('density',          self._density_edit,  _safe_float(self._density_edit.text()) == 0.0),
            ('moisture_greens',  self._moisture_edit, _safe_float(self._moisture_edit.text())== 0.0),
            ('greens_temp',      self._greens_edit,   _safe_float(self._greens_edit.text())  == 0.0),
            ('ambientTemp',      self._ambient_edit,  _safe_float(self._ambient_edit.text()) == 0.0),
            ('ambient_humidity', self._humidity_edit, _safe_float(self._humidity_edit.text())== 0.0),
            ('whole_color',      self._whole_edit,    _safe_float(self._whole_edit.text())   == 0.0),
        ]
        missing_keys: list[str] = []
        for key, widget, is_empty in empties:
            widget.setStyleSheet(self._line_style(warn if is_empty else ok))
            if is_empty:
                missing_keys.append(key)

        no_uuid = not _UUID_RE.search(self._beans_edit.toPlainText() or '')
        self._beans_edit.setStyleSheet(self._text_style(warn if no_uuid else ok))
        if no_uuid:
            missing_keys.insert(0, 'beans_uuid')

        if missing_keys:
            labels = ', '.join(_FIELD_LABELS.get(k, k) for k in missing_keys)
            self._missing_lbl.setText(
                QApplication.translate("tilauscope_repair", "Missing: {0}").format(labels))
        else:
            self._missing_lbl.setText(
                QApplication.translate("tilauscope_repair", "\u2713 All required fields filled"))

        # weight loss badge
        loss = weight_loss_pct(
            _safe_float(self._w_in_edit.text()), _safe_float(self._w_out_edit.text()))
        wi = _safe_float(self._w_in_edit.text())
        wo = _safe_float(self._w_out_edit.text())
        if wi > 0.0 and wo > 0.0 and wo >= wi:
            self._loss_lbl.setText(QApplication.translate("tilauscope_repair", "out \u2265 in!"))
            self._loss_lbl.setStyleSheet(f"color:{THEME['CRITICAL']}; font-size:12px;")
        elif loss is None:
            self._loss_lbl.setText("\u2014")
            self._loss_lbl.setProperty('variant', 'secondary')
        else:
            in_range = _LOSS_RANGE[0] <= loss <= _LOSS_RANGE[1]
            self._loss_lbl.setText(f"{loss:.1f}%")
            self._loss_lbl.setStyleSheet(
                f"color:{THEME['SUCCESS'] if in_range else warn}; font-size:12px;")

        # plausibility (present-but-unusual): separate "Check:" line, no border
        checks = plausibility_checks(self._current_values())
        if checks:
            self._check_lbl.setText(
                QApplication.translate("tilauscope_repair", "Check: {0}").format('; '.join(checks)))
            self._check_lbl.setVisible(True)
        else:
            self._check_lbl.setText("")
            self._check_lbl.setVisible(False)

    # ── helpers ────────────────────────────────────────────────────────────
    def _green_beans(self) -> list[GreenBean]:
        cave = getattr(self._bc, 'cave', None)
        return list(cave.green_beans) if (cave and cave.green_beans) else []

    def _color_systems(self) -> list[str]:
        qmc = getattr(self._aw, 'qmc', None)
        systems = list(getattr(qmc, 'color_systems', []) or [])
        return systems or ['Agtron', 'Tonino', 'ColorTest', 'ColorTrack', 'Roast Vision', 'Colorette']

    @staticmethod
    def _weight_unit(data: dict) -> str:
        w = data.get('weight') or []
        return w[2] if len(w) > 2 and isinstance(w[2], str) and w[2] else _DEFAULT_WEIGHT_UNIT

    def _update_filename_preview(self) -> None:
        if self._current_data is None:
            self._fname_lbl.setText("")
            return
        preview = dict(self._current_data)
        preview['title'] = self._title_edit.text().strip()
        self._fname_lbl.setText(build_alog_filename(preview))

    def _confirm(self, title: str, text: str) -> bool:
        return show_styled_message(
            self, title, text,
            QMessageBox.Icon.Question) == QMessageBox.StandardButton.Ok

    def _set_editor_enabled(self, on: bool) -> None:
        for w in (self._bean_combo, self._complete_btn, self._title_edit,
                  self._roaster_combo, self._beans_edit,
                  self._w_in_edit, self._w_out_edit, self._density_edit, self._moisture_edit,
                  self._greens_edit, self._ambient_edit, self._humidity_edit, self._whole_edit,
                  self._ground_edit, self._color_sys_combo, self._record_btn,
                  *self._learn_btns.values()):
            w.setEnabled(on)
        if not on:
            # No file selected: show no state at all rather than the previous
            # file's, which would read as a decision about nothing.
            self._learn_group.setExclusive(False)
            for btn in self._learn_btns.values():
                btn.setChecked(False)
            self._learn_group.setExclusive(True)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(150, self._recenter)
        if self._first_show:
            self._first_show = False
            QTimer.singleShot(0, self._reload_file_list)

    def _recenter(self) -> None:
        # Centre on the host window: BeanCave when visible, Artisan otherwise.
        ref = None
        try:
            if self._bc is not None and self._bc.window().isVisible():
                ref = self._bc.window().geometry()
        except (AttributeError, RuntimeError):
            ref = None
        if ref is None:
            ref = (self._aw.window().geometry()
                   if (self._aw and self._aw.window()) else self.screen().availableGeometry())
        self.move(ref.center() - self.rect().center())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 50:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_pos = None

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._dirty and not self._confirm(
                QApplication.translate("tilauscope_repair", "Unsaved changes"),
                QApplication.translate("tilauscope_repair",
                    "Discard unsaved changes and close?")):
            event.ignore()
            return
        # Closing the window must also stop the scan: the chained timer would
        # otherwise keep parsing files for a window that is no longer there.
        self._scan_active = False
        event.accept()

    @staticmethod
    def _fmt(v: object) -> str:
        f = _safe_float(v)
        if f == 0.0:
            return ''
        return f"{f:g}"
