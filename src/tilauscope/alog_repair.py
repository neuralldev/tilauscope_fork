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
AlogRepairDialog - floating master/detail window opened from the File Management
tab. Lists every .alog in the ALog directory, audits missing fields, and lets the
user complete one file at a time. The bean reference (``uuid: ...`` inside the
``beans`` field) is auto-matched and can be overridden manually; "Complete from
bean" fills only empty metadata fields and rebuilds the ``beans`` field with the
canonical layout used by roast_properties. Pressing "Record" rewrites the .alog
in place and renames it to the Artisan filename derived from title + roast date.

IMPORTANT - file encoding
    Artisan's native profile format is ``repr(dict)`` written as UTF-8 text and
    read back with ``ast.literal_eval`` (artisanlib.util.serialize/deserialize,
    and beancave.get_alog_data). Write with ``path.write_text(repr(data),
    encoding='utf-8')`` — see write_alog(). Do NOT ``encode('unicode_escape')``:
    the readers only literal_eval, so the extra layer is never undone and
    compounds on every save (multi-line ``beans`` gained runs of backslashes).
"""

from __future__ import annotations

import re
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
    QFrame, QSizeGrip, QProgressDialog,
)

from tilauscope.tilauscope_types import (
    THEME, AGTRON_SCALES, GreenBean, show_styled_message,
)

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow
    from tilauscope.beancave import BeancaveDlg

_log: Final[logging.Logger] = logging.getLogger(__name__)

_UUID_RE: Final = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')
# Artisan removeDisallowedFilenameChars: strips [<>:"/\|?*]
_INVALID_FN: Final = re.compile(r'[<>:"/\\|?*]')

_GREEN: Final = '#A6E3A1'

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
    of one separator) and accents were mangled to ``\\xNN``. ## TILAU ##"""
    path.write_text(repr(data), encoding='utf-8')


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
            f"QLabel {{ color: {THEME['TEXT']}; font-family: 'JetBrains Mono';"
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
        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Agtron estimate"))
        title_lbl.setStyleSheet(
            f"font-size:13px; font-weight:bold; color:{THEME['ACCENT']}; background:transparent;")
        btn_x = QPushButton("\u2715")
        btn_x.setFixedSize(24, 24)
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
            "tilauscope_beancave",
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


## TILAU ##
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
        self._bc = beancave
        self._aw = aw
        self._current_path: Path | None = None
        self._current_data: dict | None = None
        self._loading = False          # True while populating (suppresses dirty)
        self._dirty = False            # unsaved edits on the current file
        self._suppress_select = False  # guards programmatic selection changes
        self._drag_pos: QPoint | None = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(880, 600)

        self._build_ui()
        self._reload_file_list()

    # ── styling ────────────────────────────────────────────────────────────
    def _style(self) -> str:
        crit = THEME.get('CRITICAL', '#F38BA8')
        return f"""
            QDialog, QWidget {{ background-color:{THEME['BG']}; color:{THEME['TEXT']};
                font-family:'JetBrains Mono'; }}
            QLineEdit, QComboBox, QPlainTextEdit {{ background-color:{THEME['SURFACE']};
                color:{THEME['TEXT']}; border:1px solid {THEME['BORDER']};
                border-radius:6px; padding:5px 8px; font-size:12px; }}
            QLineEdit:focus, QComboBox:focus {{ border:1px solid {THEME['ACCENT']}; }}
            QListWidget {{ background-color:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};
                border-radius:6px; font-size:12px; }}
            QListWidget::item:selected {{ background-color:{THEME['ACCENT']}; color:{THEME['BG']}; }}
            QCheckBox {{ color:{THEME['SUBTEXT']}; font-size:11px; }}
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
        lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:10px; letter-spacing:1px;")
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
            QApplication.translate("tilauscope_beancave", "\U0001f527  Repair ALogs"))
        title_lbl.setStyleSheet(
            f"font-size:15px; font-weight:bold; color:{THEME['ACCENT']}; background:transparent;")
        btn_x = QPushButton("\u2715")
        btn_x.setFixedSize(26, 26)
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
        self._summary_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px;")
        left_lay.addWidget(self._summary_lbl)
        self._incomplete_only = QCheckBox(
            QApplication.translate("tilauscope_beancave", "Show incomplete only"))
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

        # status summary (missing / plausibility)
        self._missing_lbl = QLabel("")
        self._missing_lbl.setWordWrap(True)
        self._missing_lbl.setStyleSheet(f"color:{THEME.get('WARNING', '#F9E2AF')}; font-size:11px;")
        form.addWidget(self._missing_lbl)
        self._check_lbl = QLabel("")
        self._check_lbl.setWordWrap(True)
        self._check_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px; font-style:italic;")
        form.addWidget(self._check_lbl)

        # bean link row
        bean_row = QHBoxLayout()
        self._bean_combo = QComboBox()
        self._bean_combo.currentIndexChanged.connect(self._on_field_changed)
        bean_row.addWidget(QLabel(QApplication.translate("tilauscope_beancave", "Green bean:")))
        bean_row.addWidget(self._bean_combo, 1)
        form.addLayout(bean_row)

        self._complete_btn = QPushButton(
            QApplication.translate("tilauscope_beancave", "Complete from bean (empty fields only)"))
        self._complete_btn.clicked.connect(self._complete_from_bean)
        form.addWidget(self._complete_btn)

        # title
        form.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "TITLE")))
        self._title_edit = QLineEdit()
        form.addWidget(self._title_edit)

        # beans
        form.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "BEANS")))
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
        self._loss_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:12px;")

        self._density_edit.setPlaceholderText("550\u2013900")
        self._moisture_edit.setPlaceholderText("8\u201314")
        self._greens_edit.setPlaceholderText("\u00b0C")
        self._ambient_edit.setPlaceholderText("\u00b0C")
        self._humidity_edit.setPlaceholderText("20\u201380")
        self._density_edit.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Green bean density, typical 550\u2013900 g/l"))
        self._moisture_edit.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Green moisture, typical 8\u201314 %"))
        self._ambient_edit.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Ambient temperature at roast (feeds historical analysis)"))
        self._humidity_edit.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Ambient humidity at roast (feeds historical analysis)"))

        grid = QGridLayout()
        grid.addWidget(self._w_in_lbl,  0, 0)
        grid.addWidget(self._w_out_lbl, 0, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "WEIGHT LOSS")), 0, 2)
        grid.addWidget(self._w_in_edit,  1, 0)
        grid.addWidget(self._w_out_edit, 1, 1)
        grid.addWidget(self._loss_lbl,   1, 2)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "DENSITY")),    2, 0)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "MOISTURE %")), 2, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "GREENS TEMP")),2, 2)
        grid.addWidget(self._density_edit,  3, 0)
        grid.addWidget(self._moisture_edit, 3, 1)
        grid.addWidget(self._greens_edit,   3, 2)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "AMBIENT \u00b0C")), 4, 0)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "HUMIDITY %")),     4, 1)
        grid.addWidget(self._ambient_edit,  5, 0)
        grid.addWidget(self._humidity_edit, 5, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "COLOR WHOLE")),   6, 0)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "COLOR GROUND")),  6, 1)
        grid.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "COLOR SYSTEM")),  6, 2)
        grid.addWidget(self._whole_edit,      7, 0)
        grid.addWidget(self._ground_edit,     7, 1)
        grid.addWidget(self._color_sys_combo, 7, 2)
        agtron_btn = QPushButton(QApplication.translate("tilauscope_beancave", "Agtron\u2026"))
        agtron_btn.clicked.connect(self._open_agtron)
        grid.addWidget(agtron_btn, 8, 2)
        form.addLayout(grid)

        # filename preview
        form.addWidget(self._field_label(QApplication.translate("tilauscope_beancave", "\u2192 NEW FILENAME")))
        self._fname_lbl = QLabel("")
        self._fname_lbl.setWordWrap(True)
        self._fname_lbl.setStyleSheet(
            f"color:{THEME['ACCENT']}; background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};"
            f"border-radius:6px; padding:6px 8px; font-size:11px;")
        form.addWidget(self._fname_lbl)

        form.addStretch(1)

        # buttons
        btn_row = QHBoxLayout()
        self._record_btn = QPushButton(QApplication.translate("tilauscope_beancave", "Record"))
        self._record_btn.setObjectName("btnPrimary")
        self._record_btn.clicked.connect(self._record)
        self._next_btn = QPushButton(QApplication.translate("tilauscope_beancave", "Next incomplete \u25b8"))
        self._next_btn.clicked.connect(lambda: self._select_next_incomplete(self._list.currentRow()))
        ## TILAU ## — batch stamp tilau_name_map on legacy alogs
        self._stamp_btn = QPushButton(
            QApplication.translate("tilauscope_beancave", "Stamp device map"))
        self._stamp_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave",
            "Rebuild tilau_name_map in all ALogs that pre-date automatic device-index stamping."))
        self._stamp_btn.clicked.connect(self._stamp_device_map_batch)
        # Toggle « exclure de l'apprentissage » sur l'alog sélectionné : pose /
        # retire tilau_exclude_learning directement dans le fichier (écriture
        # immédiate, pas de Record) — l'analyse historique du plan saute les
        # fichiers flaggés (FC, timings, drop couleur, courbe maître).
        self._exclude_btn = QPushButton(
            QApplication.translate("tilauscope_beancave", "\U0001f6ab Exclude from learning"))
        self._exclude_btn.setCheckable(True)
        self._exclude_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave",
            "Flag the selected ALog so plan learning skips it (written to the file immediately; click again to re-admit it)."))
        self._exclude_btn.setStyleSheet(
            f"QPushButton:checked {{ border:1.5px solid {THEME.get('CRITICAL', '#F38BA8')};"
            f" color:{THEME.get('CRITICAL', '#F38BA8')};"
            f" background-color: rgba(243,139,168,0.10); }}")
        self._exclude_btn.clicked.connect(self._toggle_exclude_learning)
        close_btn = QPushButton(QApplication.translate("tilauscope_beancave", "Close"))
        close_btn.setObjectName("btnGhost")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._record_btn)
        btn_row.addWidget(self._next_btn)
        btn_row.addWidget(self._stamp_btn)
        btn_row.addWidget(self._exclude_btn)
        btn_row.addWidget(close_btn)
        btn_row.addStretch(1)
        form.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setSizes([320, 560])

        # QSizeGrip anchored to bottom-right of the container
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        grip = QSizeGrip(self.container)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip)
        root.addLayout(grip_row)

        # live status + dirty tracking
        for w in (self._title_edit, self._w_in_edit, self._w_out_edit, self._density_edit,
                  self._moisture_edit, self._greens_edit, self._ambient_edit,
                  self._humidity_edit, self._whole_edit, self._ground_edit):
            w.textChanged.connect(self._on_field_changed)
        self._beans_edit.textChanged.connect(self._on_field_changed)
        self._color_sys_combo.currentIndexChanged.connect(self._on_field_changed)

        self._set_editor_enabled(False)

    # ── list population ────────────────────────────────────────────────────
    def _reload_file_list(self) -> None:
        self._suppress_select = True
        self._list.clear()
        self._suppress_select = False
        directory = Path(self._bc.alog_directory) if self._bc.alog_directory else None
        if not directory or not directory.is_dir():
            self._summary_lbl.setText(QApplication.translate(
                "tilauscope_beancave", "ALog directory not set."))
            return
        files = sorted(directory.glob("*.alog"), key=lambda p: p.name.lower())
        incomplete = 0
        shown = 0
        only_incomplete = self._incomplete_only.isChecked()
        for fp in files:
            data = self._bc.get_alog_data(fp)
            if data is None:
                continue
            missing = audit_alog(data)
            is_incomplete = bool(missing)
            if is_incomplete:
                incomplete += 1
            if only_incomplete and not is_incomplete:
                continue
            item = QListWidgetItem(fp.name)
            item.setData(self._ROLE_PATH, str(fp))
            item.setData(self._ROLE_INCOMPLETE, is_incomplete)
            if 'beans_uuid' in missing:
                item.setForeground(QColor(THEME.get('CRITICAL', '#F38BA8')))
                item.setText(f"\u2716  {fp.name}")
            elif missing:
                item.setForeground(QColor(THEME.get('WARNING', '#F9E2AF')))
                item.setText(f"\u26A0  {fp.name}  ({len(missing)})")
            else:
                item.setForeground(QColor(_GREEN))
                item.setText(f"\u2713  {fp.name}")
            if data.get('tilau_exclude_learning', False):
                item.setText(item.text() + "  \U0001f6ab")
            self._list.addItem(item)
            shown += 1
        self._summary_lbl.setText(QApplication.translate(
            "tilauscope_beancave", "{0} files \u00b7 {1} incomplete \u00b7 {2} shown").format(
                len(files), incomplete, shown))

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
                    QApplication.translate("tilauscope_beancave", "Unsaved changes"),
                    QApplication.translate("tilauscope_beancave",
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
        # état du toggle « exclure de l'apprentissage » du fichier sélectionné
        self._exclude_btn.setChecked(bool(data.get('tilau_exclude_learning', False)))

    def _populate_editor(self, data: dict) -> None:
        self._loading = True
        unit = self._weight_unit(data)
        self._w_in_lbl.setText(QApplication.translate(
            "tilauscope_beancave", "WEIGHT IN ({0})").format(unit))
        self._w_out_lbl.setText(QApplication.translate(
            "tilauscope_beancave", "WEIGHT OUT ({0})").format(unit))

        self._title_edit.setText(data.get('title', '') or '')
        self._beans_edit.setPlainText(data.get('beans', '') or '')

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
        self._bean_combo.addItem(QApplication.translate("tilauscope_beancave", "\u2014 none \u2014"), userData=None)
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
                QApplication.translate("tilauscope_beancave", "No bean"),
                QApplication.translate("tilauscope_beancave", "Select a green bean first."),
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

    ## TILAU ##
    @pyqtSlot()
    def _stamp_device_map_batch(self) -> None:
        """Iterate every alog in the directory; write tilau_name_map for files
        that contain TilauScope devices (identified by extraname1 label) but
        lack the map key.  Skips files that already have the key."""
        directory = Path(self._bc.alog_directory) if self._bc.alog_directory else None
        if not directory or not directory.is_dir():
            show_styled_message(
                self,
                QApplication.translate("tilauscope_beancave", "No directory"),
                QApplication.translate("tilauscope_beancave", "ALog directory not set."),
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
            QApplication.translate("tilauscope_beancave", "Stamping device map…"),
            QApplication.translate("tilauscope_beancave", "Cancel"),
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
                    "tilauscope_beancave", "Processing {0}…").format(fp.name))
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
            "tilauscope_beancave",
            "{0} file(s) stamped · {1} already up-to-date · {2} error(s)").format(
                stamped, skipped, errors)
        show_styled_message(
            self,
            QApplication.translate("tilauscope_beancave", "Stamp device map"),
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
                QApplication.translate("tilauscope_beancave", "Invalid weights"),
                QApplication.translate("tilauscope_beancave",
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

        new_name = build_alog_filename(data)
        new_path = self._current_path.with_name(new_name)

        # collision guard: never silently clobber a different existing file
        if new_path.exists() and new_path.resolve() != self._current_path.resolve():
            if not self._confirm(
                    QApplication.translate("tilauscope_beancave", "File exists"),
                    QApplication.translate("tilauscope_beancave",
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
                QApplication.translate("tilauscope_beancave", "Save Error"),
                QApplication.translate("tilauscope_beancave",
                    "Could not write the ALog file:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True)
            return

        _log.info("ALog repaired: %s -> %s", self._current_path.name, new_path.name)
        self._dirty = False
        self.repaired.emit(str(new_path))
        prev_row = self._list.currentRow()
        self._current_path = new_path
        self._reload_file_list()
        self._select_next_incomplete(prev_row, fallback=str(new_path))

    def _toggle_exclude_learning(self, checked: bool) -> None:
        """Pose / retire tilau_exclude_learning sur le fichier sélectionné,
        écrit IMMÉDIATEMENT (pas de Record) : le fichier est relu depuis le
        disque pour ne pas embarquer d'éditions non enregistrées, et seule la
        clé du flag est touchée. La copie d'édition courante est synchronisée
        pour qu'un Record ultérieur n'écrase pas le choix."""
        if self._current_path is None:
            return
        data = self._bc.get_alog_data(self._current_path)
        if data is None:
            self._exclude_btn.setChecked(not checked)
            return
        data = dict(data)   # never mutate the beancave cache entry
        if checked:
            data['tilau_exclude_learning'] = True
        else:
            data.pop('tilau_exclude_learning', None)
        try:
            write_alog(data, self._current_path)
        except Exception as exc:  # noqa: BLE001
            _log.error("ALog exclude-learning write failed: %s", exc)
            self._exclude_btn.setChecked(not checked)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_beancave", "Save Error"),
                QApplication.translate("tilauscope_beancave",
                    "Could not write the ALog file:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True)
            return
        if self._current_data is not None:
            if checked:
                self._current_data['tilau_exclude_learning'] = True
            else:
                self._current_data.pop('tilau_exclude_learning', None)
        item = self._list.currentItem()
        if item is not None:
            base = item.text().replace("  \U0001f6ab", "")
            item.setText(base + ("  \U0001f6ab" if checked else ""))
        _log.info("ALog %s: tilau_exclude_learning=%s", self._current_path.name, checked)

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

    def _reselect(self, path: Path) -> None:
        self._suppress_select = True
        for r in range(self._list.count()):
            it = self._list.item(r)
            if it.data(self._ROLE_PATH) == str(path):
                self._list.setCurrentRow(r)
                break
        self._suppress_select = False

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
        warn = THEME.get('WARNING', '#F9E2AF')
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
                QApplication.translate("tilauscope_beancave", "Missing: {0}").format(labels))
        else:
            self._missing_lbl.setText(
                QApplication.translate("tilauscope_beancave", "\u2713 All required fields filled"))

        # weight loss badge
        loss = weight_loss_pct(
            _safe_float(self._w_in_edit.text()), _safe_float(self._w_out_edit.text()))
        wi = _safe_float(self._w_in_edit.text())
        wo = _safe_float(self._w_out_edit.text())
        if wi > 0.0 and wo > 0.0 and wo >= wi:
            self._loss_lbl.setText(QApplication.translate("tilauscope_beancave", "out \u2265 in!"))
            self._loss_lbl.setStyleSheet(f"color:{THEME.get('CRITICAL', '#F38BA8')}; font-size:12px;")
        elif loss is None:
            self._loss_lbl.setText("\u2014")
            self._loss_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:12px;")
        else:
            in_range = _LOSS_RANGE[0] <= loss <= _LOSS_RANGE[1]
            self._loss_lbl.setText(f"{loss:.1f}%")
            self._loss_lbl.setStyleSheet(
                f"color:{_GREEN if in_range else warn}; font-size:12px;")

        # plausibility (present-but-unusual): separate "Check:" line, no border
        checks = plausibility_checks(self._current_values())
        if checks:
            self._check_lbl.setText(
                QApplication.translate("tilauscope_beancave", "Check: {0}").format('; '.join(checks)))
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
        for w in (self._bean_combo, self._complete_btn, self._title_edit, self._beans_edit,
                  self._w_in_edit, self._w_out_edit, self._density_edit, self._moisture_edit,
                  self._greens_edit, self._ambient_edit, self._humidity_edit, self._whole_edit,
                  self._ground_edit, self._color_sys_combo, self._record_btn,
                  self._exclude_btn):
            w.setEnabled(on)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(150, self._recenter)

    def _recenter(self) -> None:
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
                QApplication.translate("tilauscope_beancave", "Unsaved changes"),
                QApplication.translate("tilauscope_beancave",
                    "Discard unsaved changes and close?")):
            event.ignore()
            return
        event.accept()

    @staticmethod
    def _fmt(v: object) -> str:
        f = _safe_float(v)
        if f == 0.0:
            return ''
        return f"{f:g}"