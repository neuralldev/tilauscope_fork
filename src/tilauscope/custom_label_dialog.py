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

"""Free-entry label: type what is on a bag of coffee, print it on the Niimbot.

For a coffee the operator bought already roasted. Nothing is stored in the bean
catalogue — only the last entry is remembered, so several bags of the same lot
are one click apart. The printer itself belongs to BeanCave, which is created
in the background when it is not open yet.
"""

from __future__ import annotations

import logging
from typing import Final

from PyQt6.QtCore import Qt, QPoint, QDate, QTimer, pyqtSlot, QSettings
from PyQt6.QtGui import QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout,
)

from PIL.ImageQt import ImageQt

from tilauscope.theme_qss import (apply_tilau_theme, calendar_qss,
                                  styled_popup_view, tooltip_qss)
from tilauscope.tilauscope_types import THEME, show_styled_message, print_progress_pill
from tilauscope.label_printer import build_custom_label_image, normalise_process
from tilauscope.header_icons import SVG_CALENDAR, SVG_CALENDAR_OFF, apply_icon

_log: Final[logging.Logger] = logging.getLogger(__name__)

_SETTINGS_PREFIX: Final[str] = "tilauscope/custom_label/"

# Distinct process names the app already prints elsewhere, so a hand-typed
# label and a BeanCave one never spell the same process two ways.
_PROCESS_CHOICES: Final[tuple[str, ...]] = (
    "", "Washed", "Natural", "Honey", "Pulped nat.", "Anaerobic",
    "Coferment", "Wet hulled", "Mixed",
)

# Roast levels named as the Agtron scale names them in tilauscope_types.
_LEVEL_CHOICES: Final[tuple[str, ...]] = (
    "", "Light", "Medium Light", "Medium", "Medium Dark", "Dark", "Very Dark",
)

_PREVIEW_SCALE: Final[float] = 1.5


def _deleted(obj) -> bool:
    """True when Qt has already destroyed the C++ side of `obj`."""
    try:
        try:
            import sip  # noqa: PLC0415
        except ImportError:  # pragma: no cover - PyQt6 packaging variant
            from PyQt6 import sip  # noqa: PLC0415
        return bool(sip.isdeleted(obj))
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return False


class CustomLabelDlg(QDialog):
    """Type a label for a bought coffee and print it, one bag after another.

    Non-modal and never closed by printing: the fields stay filled so the next
    bag of the same lot is a single click."""

    def __init__(self, aw) -> None:
        super().__init__(None)  # parent=None: avoid Qt embedding on macOS
        apply_tilau_theme(self, ground=False)
        self.aw = aw
        self._drag_pos: QPoint | None = None
        self._print_pill = None
        self._printing = False
        self._host_ref = None
        self._signals_bound = False
        # One creation attempt only: a BeanCave that fails to build must not be
        # retried every second by the poll.
        self._host_attempted = False
        # True only when THIS dialog brought BeanCave up, so closing releases the
        # printer instead of tearing down a window the operator was using.
        self._host_owned = False
        self._scale_window = None
        self._scale_was_connected = False
        # BeanCave builds its printer object one event loop later and learns the
        # roll size later still, on the first heartbeat: state is polled rather
        # than read once. 1 s in a form is free — nothing here is a hot path.
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._attach_host)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(QApplication.translate("tilauscope_label", "Print a label"))

        self._build_ui()
        self._restore_last()
        # Bring the printer online while the operator types, not at the click.
        QTimer.singleShot(0, self._attach_host)
        self._poll.start()
        self._refresh_preview()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("labelRoot")
        self.container.setStyleSheet(
            f"#labelRoot {{ background-color: {THEME['BG']}; border: 2px solid {THEME['ACCENT']};"
            f" border-radius: 16px; }}"
            f" QLabel {{ color: {THEME['TEXT']}; font-size: 12px; }}" + tooltip_qss())
        outer.addWidget(self.container)

        root = QVBoxLayout(self.container)
        root.setContentsMargins(18, 12, 18, 16)
        root.setSpacing(10)

        # custom title bar (drag handle + close)
        bar = QHBoxLayout()
        title = QLabel("🏷  " + QApplication.translate("tilauscope_label", "Print a label"))
        title.setStyleSheet(f"font-size:15px;font-weight:bold;color:{THEME['ACCENT']};")
        btn_x = QPushButton("✕")
        btn_x.setFixedSize(26, 26)
        btn_x.setProperty("variant", "icon")
        btn_x.setStyleSheet(
            f"QPushButton {{ background:{THEME['BORDER']}; color:{THEME['TEXT']};"
            f" border-radius:13px; font-size:14px; font-weight:bold; }}"
            f" QPushButton:hover {{ background:{THEME['CRITICAL']}; color:{THEME['BG']}; }}")
        btn_x.clicked.connect(self.close)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(btn_x)
        root.addLayout(bar)

        hint = QLabel(QApplication.translate(
            "tilauscope_label",
            "For a coffee you bought already roasted. Only the name is required — "
            "anything you leave empty is simply left off the label."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;")
        root.addWidget(hint)

        # ── form ──
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        def _lbl(text: str) -> QLabel:
            w = QLabel(text)
            w.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;")
            return w

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText(QApplication.translate(
            "tilauscope_label", "Ethiopia Guji Hambela"))
        self.ed_roaster = QLineEdit()
        self.ed_origin = QLineEdit()

        # setView / calendar_qss: on macOS these popups are separate top-level
        # windows and inherit none of the dialog's stylesheet.
        self.cmb_process = QComboBox()
        self.cmb_process.setEditable(True)
        self.cmb_process.setView(styled_popup_view())
        self.cmb_process.addItems(_PROCESS_CHOICES)
        self.cmb_level = QComboBox()
        self.cmb_level.setEditable(True)
        self.cmb_level.setView(styled_popup_view())
        self.cmb_level.addItems(_LEVEL_CHOICES)

        self.dt_roasted = QDateEdit()
        self.dt_roasted.setCalendarPopup(True)
        self.dt_roasted.setDisplayFormat("dd/MM/yyyy")
        self.dt_roasted.setDate(QDate.currentDate())
        _cal = self.dt_roasted.calendarWidget()
        if _cal is not None:
            _cal.setStyleSheet(calendar_qss())

        # A struck-through calendar rather than a word: the button shows what
        # the label will carry, and the preview beside it confirms straight away.
        self.chk_no_date = QPushButton()
        self.chk_no_date.setCheckable(True)
        self.chk_no_date.setProperty("variant", "icon")
        self.chk_no_date.setFixedSize(30, 28)
        self.chk_no_date.toggled.connect(self._on_no_date)
        self._sync_date_button(False)

        self.spn_weight = QSpinBox()
        self.spn_weight.setRange(0, 5000)
        self.spn_weight.setSingleStep(50)
        self.spn_weight.setSuffix(" g")
        self.spn_weight.setSpecialValueText(QApplication.translate("tilauscope_label", "—"))
        self.spn_weight.setValue(250)

        self.btn_scale = QPushButton("⚖")
        self.btn_scale.setFixedWidth(34)
        self.btn_scale.setToolTip(QApplication.translate(
            "tilauscope_label", "Read the weight from the scale"))
        self.btn_scale.clicked.connect(self._show_scale_window)

        self.ed_notes = QLineEdit()
        self.ed_notes.setPlaceholderText(QApplication.translate(
            "tilauscope_label", "jasmine, peach, black tea"))

        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Coffee name")), 0, 0)
        form.addWidget(self.ed_name, 0, 1, 1, 4)
        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Roasted by")), 1, 0)
        form.addWidget(self.ed_roaster, 1, 1, 1, 4)
        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Origin")), 2, 0)
        form.addWidget(self.ed_origin, 2, 1)
        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Process")), 2, 2)
        form.addWidget(self.cmb_process, 2, 3, 1, 2)
        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Roast level")), 3, 0)
        form.addWidget(self.cmb_level, 3, 1)
        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Roasted on")), 3, 2)
        form.addWidget(self.dt_roasted, 3, 3)
        form.addWidget(self.chk_no_date, 3, 4)
        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Weight")), 4, 0)
        form.addWidget(self.spn_weight, 4, 1)
        form.addWidget(self.btn_scale, 4, 2)
        form.addWidget(_lbl(QApplication.translate("tilauscope_label", "Tasting notes")), 5, 0)
        form.addWidget(self.ed_notes, 5, 1, 1, 4)
        root.addLayout(form)

        # ── preview: the real 1-bit bitmap, magnified ──
        prev_cap = QLabel(QApplication.translate(
            "tilauscope_label", "Preview — 50 × 30 mm, exactly what prints"))
        prev_cap.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;")
        root.addWidget(prev_cap)

        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet(
            f"background:#FFFFFF; border:1px solid {THEME['BORDER']}; border-radius:6px;")
        self.lbl_preview.setFixedSize(int(384 * _PREVIEW_SCALE) + 8,
                                      int(240 * _PREVIEW_SCALE) + 8)
        root.addWidget(self.lbl_preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;")
        root.addWidget(self.lbl_status)

        # ── actions ──
        actions = QHBoxLayout()
        self.btn_recall = QPushButton(QApplication.translate("tilauscope_label", "Recall last"))
        self.btn_recall.setToolTip(QApplication.translate(
            "tilauscope_label", "Bring back the last label you printed"))
        self.btn_recall.clicked.connect(self._restore_last)
        self.btn_clear = QPushButton(QApplication.translate("tilauscope_label", "Clear"))
        self.btn_clear.clicked.connect(self._clear_fields)
        btn_close = QPushButton(QApplication.translate("tilauscope_label", "Close"))
        btn_close.clicked.connect(self.close)
        self.btn_print = QPushButton("🖨  " + QApplication.translate("tilauscope_label", "Print"))
        self.btn_print.setProperty("variant", "primary")
        self.btn_print.setDefault(True)
        self.btn_print.clicked.connect(self._print_label)
        actions.addWidget(self.btn_recall)
        actions.addWidget(self.btn_clear)
        actions.addStretch(1)
        actions.addWidget(btn_close)
        actions.addWidget(self.btn_print)
        root.addLayout(actions)

        for widget in (self.ed_name, self.ed_roaster, self.ed_origin, self.ed_notes):
            widget.textChanged.connect(self._refresh_preview)
        for combo in (self.cmb_process, self.cmb_level):
            combo.currentTextChanged.connect(self._refresh_preview)
        self.spn_weight.valueChanged.connect(self._refresh_preview)
        self.dt_roasted.dateChanged.connect(self._refresh_preview)

    # ── frameless drag ───────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── printer host (BeanCave owns the Niimbot) ─────────────────────────────

    def _attach_host(self) -> None:
        """Resolve the BeanCave that owns the printer, then track its state.

        Idempotent: it is both the first call and the 1 s poll tick. BeanCave
        builds its printer object one event loop after construction, so a single
        read at open would find nothing and never connect the signals — which is
        why the printer went online while Print stayed grey.
        """
        try:
            host = self._host()
            if host is None:
                # A host that went away takes its signal bindings with it.
                self._signals_bound = False
                host = self._resolve_host()
                self._host_ref = host
            if host is not None and not self._signals_bound:
                np_ = getattr(host, "np", None)
                if np_ is not None:
                    np_.at_connected.connect(self._on_printer_state)
                    np_.at_disconnected.connect(self._on_printer_state)
                    self._signals_bound = True
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("custom label: printer host unavailable")
            self._host_ref = None
        self._on_printer_state()

    def _resolve_host(self):
        """Return the BeanCave window, creating it off-screen when none is open.

        A BeanCave created here is owned by this dialog and closed with it, so
        the printer connection and its BLE scan do not outlive the window that
        asked for them."""
        host = getattr(self.aw, "beancaveWindow", None)
        if host is not None and not _deleted(host):
            return host
        if self._host_attempted:
            return None
        self._host_attempted = True
        from tilauscope.beancave import BeancaveDlg  # noqa: PLC0415
        host = BeancaveDlg(self.aw, self.aw.qmc.beans if self.aw.qmc.beans else "")
        host.setWindowModality(Qt.WindowModality.NonModal)
        self.aw.beancaveWindow = host
        self._host_owned = True
        return host

    def _host(self):
        host = self._host_ref
        return None if host is None or _deleted(host) else host

    def _printer(self):
        host = self._host()
        return getattr(host, "np", None) if host is not None else None

    @pyqtSlot()
    def _on_printer_state(self) -> None:
        """Say in one line what stands between the operator and a printed label."""
        if self._printing:
            return
        host, np_ = self._host(), self._printer()
        name_ok = bool(self.ed_name.text().strip())
        reason = ""
        if host is None or np_ is None or not getattr(host, "_niimbot_connected", False):
            reason = QApplication.translate(
                "tilauscope_label",
                "Looking for the printer — switch it on and pair it in Settings if "
                "this stays here.")
        elif getattr(np_, "paper_height", 0) != 30:
            reason = QApplication.translate(
                "tilauscope_label",
                "This label needs the 50 × 30 mm roll (loaded: {0} × {1} mm).").format(
                    getattr(np_, "paper_width", 0), getattr(np_, "paper_height", 0))
        elif not name_ok:
            reason = QApplication.translate(
                "tilauscope_label", "Type the coffee name to print.")
        else:
            left = getattr(np_, "total_labels", 0) - getattr(np_, "used_labels", 0)
            reason = QApplication.translate(
                "tilauscope_label", "Roll: 50 × 30 mm · {0} labels left").format(max(left, 0))
        if self.lbl_status.text() != reason:
            self.lbl_status.setText(reason)
        self.btn_print.setEnabled(
            host is not None and np_ is not None
            and getattr(host, "_niimbot_connected", False)
            and getattr(np_, "paper_height", 0) == 30 and name_ok)

    # ── fields ───────────────────────────────────────────────────────────────

    def _sync_date_button(self, omitted: bool) -> None:
        """Paint the button with the state it produces, and say both halves of
        the toggle in the tooltip so it cannot be read backwards."""
        apply_icon(self.chk_no_date,
                   SVG_CALENDAR_OFF if omitted else SVG_CALENDAR,
                   THEME["SUBTEXT"] if omitted else THEME["ACCENT"])
        self.chk_no_date.setToolTip(
            QApplication.translate(
                "tilauscope_label", "No roast date on the label — click to print it")
            if omitted else
            QApplication.translate(
                "tilauscope_label", "Roast date printed — click to leave it off"))

    def _on_no_date(self, checked: bool) -> None:
        self.dt_roasted.setEnabled(not checked)
        self._sync_date_button(checked)
        self._refresh_preview()

    def _fields(self) -> dict:
        weight = self.spn_weight.value()
        date_str = ("" if self.chk_no_date.isChecked()
                    else self.dt_roasted.date().toString("dd MMM yyyy"))
        process = self.cmb_process.currentText().strip()
        return {
            "name": self.ed_name.text().strip(),
            "roaster": self.ed_roaster.text().strip(),
            "origin": self.ed_origin.text().strip(),
            "process": normalise_process(process) if process else "",
            "roast_level": self.cmb_level.currentText().strip(),
            "roast_date": date_str,
            "weight": f"{weight} g" if weight > 0 else "",
            "notes": self.ed_notes.text().strip(),
        }

    def _clear_fields(self) -> None:
        for widget in (self.ed_name, self.ed_roaster, self.ed_origin, self.ed_notes):
            widget.clear()
        self.cmb_process.setCurrentIndex(0)
        self.cmb_level.setCurrentIndex(0)
        self.spn_weight.setValue(250)
        self.chk_no_date.setChecked(False)
        self.dt_roasted.setDate(QDate.currentDate())
        self._refresh_preview()

    def _store_last(self) -> None:
        s = QSettings()
        s.setValue(_SETTINGS_PREFIX + "name", self.ed_name.text())
        s.setValue(_SETTINGS_PREFIX + "roaster", self.ed_roaster.text())
        s.setValue(_SETTINGS_PREFIX + "origin", self.ed_origin.text())
        s.setValue(_SETTINGS_PREFIX + "process", self.cmb_process.currentText())
        s.setValue(_SETTINGS_PREFIX + "level", self.cmb_level.currentText())
        s.setValue(_SETTINGS_PREFIX + "weight", self.spn_weight.value())
        s.setValue(_SETTINGS_PREFIX + "notes", self.ed_notes.text())
        s.setValue(_SETTINGS_PREFIX + "date", self.dt_roasted.date().toString(Qt.DateFormat.ISODate))
        s.setValue(_SETTINGS_PREFIX + "no_date", self.chk_no_date.isChecked())

    def _restore_last(self) -> None:
        try:
            s = QSettings()
            self.ed_name.setText(str(s.value(_SETTINGS_PREFIX + "name", "")))
            self.ed_roaster.setText(str(s.value(_SETTINGS_PREFIX + "roaster", "")))
            self.ed_origin.setText(str(s.value(_SETTINGS_PREFIX + "origin", "")))
            self.cmb_process.setCurrentText(str(s.value(_SETTINGS_PREFIX + "process", "")))
            self.cmb_level.setCurrentText(str(s.value(_SETTINGS_PREFIX + "level", "")))
            self.spn_weight.setValue(int(s.value(_SETTINGS_PREFIX + "weight", 250, type=int)))
            self.ed_notes.setText(str(s.value(_SETTINGS_PREFIX + "notes", "")))
            iso = str(s.value(_SETTINGS_PREFIX + "date", ""))
            date = QDate.fromString(iso, Qt.DateFormat.ISODate)
            self.dt_roasted.setDate(date if date.isValid() else QDate.currentDate())
            self.chk_no_date.setChecked(s.value(_SETTINGS_PREFIX + "no_date", False, type=bool))
            self._sync_date_button(self.chk_no_date.isChecked())
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("custom label: recalling the last entry failed")
        self._refresh_preview()

    # ── preview ──────────────────────────────────────────────────────────────

    def _refresh_preview(self) -> None:
        fields = self._fields()
        if not fields["name"]:
            self.lbl_preview.clear()
            self.lbl_preview.setText(QApplication.translate(
                "tilauscope_label", "The label appears here as you type."))
            self.lbl_preview.setStyleSheet(
                f"background:#FFFFFF; color:#8A8A9A; font-size:12px;"
                f" border:1px solid {THEME['BORDER']}; border-radius:6px;")
        else:
            try:
                img = build_custom_label_image(**fields).convert("L")
                pix = QPixmap.fromImage(ImageQt(img)).scaled(
                    int(384 * _PREVIEW_SCALE), int(240 * _PREVIEW_SCALE),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self.lbl_preview.setPixmap(pix)
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _log.exception("custom label: preview build failed")
        self._on_printer_state()

    # ── scale capture ────────────────────────────────────────────────────────

    def _show_scale_window(self) -> None:
        try:
            sm = getattr(self.aw, "scale_manager", None)
            if sm is None or not sm.is_scale1_configured():
                show_styled_message(
                    self, QApplication.translate("tilauscope_label", "Scale"),
                    QApplication.translate(
                        "tilauscope_label",
                        "No scale is set up yet — pair one in Settings, or type the "
                        "weight in by hand."),
                    QMessageBox.Icon.Information)
                return
            if self._scale_window is None:
                from tilauscope.roast_properties import _ScaleFloatWindow  # noqa: PLC0415
                self._scale_window = _ScaleFloatWindow(self)  # type: ignore[arg-type]
                self._scale_was_connected = sm.is_scale1_connected()
                sm.scale1_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_stable_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_disconnected_signal.connect(self._scale_window.scale_disconnected)
                if not self._scale_was_connected:
                    sm.connect_scale1_signal.emit(False)
                else:
                    last = sm.get_scale1_last_weight()
                    if last is not None:
                        self._scale_window.update_weight(last)
            geo = self.geometry()
            self._scale_window.move(geo.right() + 12, geo.top() + 40)
            self._scale_window.show()
            self._scale_window.raise_()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("custom label: scale window unavailable")

    def receive_scale_weight(self, weight: float) -> None:
        # _ScaleFloatWindow contract: a click on the live reading lands here.
        self.spn_weight.setValue(int(round(float(weight))))

    def _teardown_scale(self) -> None:
        if self._scale_window is None:
            return
        sm = getattr(self.aw, "scale_manager", None)
        if sm is not None:
            for _sig, _slot in (
                (sm.scale1_weight_changed_signal, self._scale_window.update_weight),
                (sm.scale1_stable_weight_changed_signal, self._scale_window.update_weight),
                (sm.scale1_disconnected_signal, self._scale_window.scale_disconnected),
            ):
                try:
                    _sig.disconnect(_slot)
                except (TypeError, RuntimeError):
                    pass
        try:
            self._scale_window.close()
        except RuntimeError:
            pass
        self._scale_window = None

    # ── printing ─────────────────────────────────────────────────────────────

    def _print_label(self) -> None:
        host, np_ = self._host(), self._printer()
        if host is None or np_ is None or self._printing:
            return
        fields = self._fields()
        if not fields["name"]:
            return
        try:
            img = build_custom_label_image(**fields)
        except Exception as exc:  # noqa: BLE001
            _log.error("custom label build failed: %s", exc)
            show_styled_message(
                self, QApplication.translate("tilauscope_label", "Print"),
                QApplication.translate(
                    "tilauscope_label",
                    "The label could not be built, so nothing was sent to the printer."),
                QMessageBox.Icon.Warning)
            return
        self._store_last()
        self._printing = True
        self.btn_print.setEnabled(False)
        self.lbl_status.setText(QApplication.translate(
            "tilauscope_label", "Printing…"))
        self._print_pill = print_progress_pill(self.container, 1)
        self._print_pill.set_margin(20, 56)
        try:
            host.print_niimbot_image_async(img, self._on_print_ok, self._on_print_err)
        except Exception as exc:  # noqa: BLE001
            _log.error("custom label print dispatch failed: %s", exc)
            self._on_print_err(str(exc))

    @pyqtSlot()
    def _on_print_ok(self) -> None:
        pill, self._print_pill = self._print_pill, None
        if pill is not None:
            pill.succeed("🖨  " + QApplication.translate("tilauscope_label", "Label printed"))
        # The dialog stays open with its fields filled: the next bag of the same
        # lot is one click away.
        self._printing = False
        self._on_printer_state()

    @pyqtSlot(str)
    def _on_print_err(self, msg: str) -> None:
        pill, self._print_pill = self._print_pill, None
        if pill is not None:
            pill.fail("🖨  " + QApplication.translate("tilauscope_label", "Not printed"))
        self._printing = False
        self._on_printer_state()
        show_styled_message(
            self, QApplication.translate("tilauscope_label", "Print"),
            QApplication.translate(
                "tilauscope_label",
                "The label did not print: {0}\n\nCheck the printer is on and the roll "
                "is loaded, then try again.").format(msg),
            QMessageBox.Icon.Warning)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802
        """Give the printer back. A BeanCave this dialog opened is closed with
        it: left running, its printer connection and BLE scan survive the window
        and the next open collides with the thread still holding them."""
        self._poll.stop()
        self._teardown_scale()
        host = self._host()
        np_ = getattr(host, "np", None) if host is not None else None
        if np_ is not None and self._signals_bound:
            for _sig in (np_.at_connected, np_.at_disconnected):
                try:
                    _sig.disconnect(self._on_printer_state)
                except (TypeError, RuntimeError):
                    pass
        self._signals_bound = False
        # Only a BeanCave we created and that the operator never brought up:
        # once it is on screen it is theirs, whoever opened it.
        if host is not None and self._host_owned and not host.isVisible():
            try:
                host.close()
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _log.exception("custom label: releasing the printer failed")
            else:
                if getattr(self.aw, "beancaveWindow", None) is host:
                    self.aw.beancaveWindow = None
                host.deleteLater()
        self._host_owned = False
        self._host_ref = None
        if getattr(self.aw, "tilau_custom_label_dlg", None) is self:
            self.aw.tilau_custom_label_dlg = None
        super().closeEvent(event)
        self.deleteLater()


def open_custom_label_dialog(aw) -> CustomLabelDlg:
    """Open the free-entry label window, raising the one already on screen."""
    dlg = getattr(aw, "tilau_custom_label_dlg", None)
    if dlg is not None and not _deleted(dlg) and dlg.isVisible():
        dlg.raise_()
        dlg.activateWindow()
        return dlg
    dlg = CustomLabelDlg(aw)
    aw.tilau_custom_label_dlg = dlg
    dlg.show()
    # macOS gives no hover until the window is key.
    dlg.raise_()
    dlg.activateWindow()
    return dlg
