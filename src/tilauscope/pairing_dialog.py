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
# Tilau 2025-2026

#
# pairing_dialog.py
#
# ## TILAU ## Desktop pairing screen for remote control (protocol §7 / §9).
#
# Frameless Catppuccin modal: shows the pairing QR (one-time PT in the link),
# a TTL countdown + regenerate, and the list of paired devices with per-device
# revoke. Reuses generate_qr_image() (label_printer) — no new dependency.

import logging
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

_log = logging.getLogger(__name__)

_BG = "#1E1E2E"; _SURFACE = "#313244"; _OVERLAY = "#45475A"
_TEXT = "#CDD6F4"; _SUB = "#A6ADC8"; _ACCENT = "#89B4FA"
_RED = "#F38BA8"; _GREEN = "#A6E3A1"; _YELLOW = "#F9E2AF"


class PairingDialog(QDialog):
    def __init__(self, host, control_port: int, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = control_port
        self._ttl_left = 0
        self._url = ''        # current pairing URL (copied to clipboard on demand)
        self._dev_sig = None  # last-seen (id, name) signature (poll for changes)
        self._editing = None  # device_id currently being renamed inline (or None)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        container = QFrame()
        container.setObjectName("PairContainer")
        container.setStyleSheet(
            f"#PairContainer {{ background-color:{_BG}; border:2px solid {_SURFACE};"
            f" border-radius:15px; }}"
            f"QLabel {{ color:{_TEXT}; background:transparent; border:none; }}")
        root.addWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(22, 16, 22, 18)
        inner.setSpacing(12)

        # header
        header = QHBoxLayout()
        title = QLabel(QApplication.translate("tilauscope_devices", "PAIR A PHONE"))
        title.setStyleSheet(f"color:{_ACCENT};font-size:14px;font-weight:800;letter-spacing:1px;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{_SURFACE}; color:{_RED}; border-radius:15px;"
            f" border:1px solid {_RED}; font-weight:bold; }}"
            f"QPushButton:hover {{ background:{_RED}; color:{_BG}; }}")
        header.addWidget(title); header.addStretch(); header.addWidget(close_btn)
        inner.addLayout(header)

        # QR card
        qr_card = QFrame()
        qr_card.setStyleSheet("background:#ffffff;border-radius:14px;")
        qr_l = QVBoxLayout(qr_card)
        qr_l.setContentsMargins(12, 12, 12, 12)
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(220, 220)
        qr_l.addWidget(self._qr_label, alignment=Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(qr_card, alignment=Qt.AlignmentFlag.AlignCenter)

        hint = QLabel(QApplication.translate("tilauscope_devices",
                      "Scan or open the link on your phone (same wifi)"))
        hint.setStyleSheet(f"color:{_SUB};font-size:12px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(hint)

        self._url_label = QLabel()
        self._url_label.setStyleSheet(f"color:{_SUB};font-family:'JetBrains Mono';font-size:10px;")
        self._url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_label.setWordWrap(True)
        inner.addWidget(self._url_label)

        # secondary .local address (survives IP changes; iOS mDNS can be slow so
        # the numeric IP above is primary)
        self._url_alt = QLabel()
        self._url_alt.setStyleSheet(f"color:{_OVERLAY};font-family:'JetBrains Mono';font-size:9px;")
        self._url_alt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_alt.setWordWrap(True)
        inner.addWidget(self._url_alt)

        ttl_row = QHBoxLayout()
        self._ttl_label = QLabel()
        self._ttl_label.setStyleSheet(f"color:{_YELLOW};font-family:'JetBrains Mono';font-size:11px;")
        _pill = (f"QPushButton {{ background:transparent; color:{_SUB}; border:1px solid {_OVERLAY};"
                 f" border-radius:8px; padding:6px 12px; }}"
                 f"QPushButton:hover {{ color:{_TEXT}; border-color:{_SUB}; }}")
        self._copy_btn = QPushButton(QApplication.translate("tilauscope_devices", "⧉ Copy link"))
        self._copy_btn.clicked.connect(self._copy_url)
        self._copy_btn.setStyleSheet(_pill)
        regen = QPushButton(QApplication.translate("tilauscope_devices", "↻ New code"))
        regen.clicked.connect(self._new_token)
        regen.setStyleSheet(_pill)
        ttl_row.addWidget(self._ttl_label); ttl_row.addStretch()
        ttl_row.addWidget(self._copy_btn); ttl_row.addWidget(regen)
        inner.addLayout(ttl_row)

        # devices
        self._dev_title = QLabel()
        self._dev_title.setStyleSheet(
            f"color:{_SUB};font-size:10px;font-weight:700;letter-spacing:1px;")
        inner.addWidget(self._dev_title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(150)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._dev_host = QWidget()
        self._dev_layout = QVBoxLayout(self._dev_host)
        self._dev_layout.setContentsMargins(0, 0, 0, 0)
        self._dev_layout.setSpacing(8)
        self._dev_layout.addStretch()
        scroll.setWidget(self._dev_host)
        inner.addWidget(scroll)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        self._new_token()
        self._refresh_devices()

    # ---- pairing token / QR -------------------------------------------------

    def _new_token(self) -> None:
        minted = self._host.mint_pairing_token()
        if not minted:
            return
        token, ttl = minted
        self._ttl_left = int(ttl)
        # Prefer the numeric LAN IP: iOS resolves it instantly, whereas
        # tilauscope.local (mDNS) is slow/unreliable on iPhone (protocol §7).
        ip = None
        try:
            if hasattr(self._host, 'lan_ip'):
                ip = self._host.lan_ip()
        except Exception:  # noqa: BLE001
            ip = None
        host = ip or 'tilauscope.local'
        url = f"http://{host}:{self._port}/#pt={token}"
        self._url = url
        self._url_label.setText(url)
        if ip:
            self._url_alt.setText(QApplication.translate("tilauscope_devices",
                                  "or  http://tilauscope.local:{port}").format(port=self._port))
        else:
            self._url_alt.setText('')
        try:
            from tilauscope.label_printer import generate_qr_image
            img = generate_qr_image(url)
            if img is not None:
                pm = QPixmap.fromImage(img).scaled(
                    216, 216, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation)
                self._qr_label.setPixmap(pm)
                self._qr_label.setStyleSheet("")
                self._qr_label.setGraphicsEffect(None)  # undim a previously expired QR
        except Exception as e:  # noqa: BLE001
            _log.warning("pairing QR render failed: %s", e)
        self._update_ttl_label()

    def _copy_url(self) -> None:
        if not self._url:
            return
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self._url)
        self._copy_btn.setText(QApplication.translate("tilauscope_devices", "✓ Copied"))
        QTimer.singleShot(1400, lambda: self._copy_btn.setText(
            QApplication.translate("tilauscope_devices", "⧉ Copy link")))

    def _tick(self) -> None:
        if self._ttl_left > 0:
            self._ttl_left -= 1
            self._update_ttl_label()
            if self._ttl_left == 0:
                # QLabel stylesheets ignore `opacity`; dim via a graphics effect.
                eff = QGraphicsOpacityEffect(self._qr_label)
                eff.setOpacity(0.25)
                self._qr_label.setGraphicsEffect(eff)
        # poll for a device that pairs (or is renamed) while the modal is open —
        # the control thread writes into the shared PairingManager. Rebuild only
        # when the (id, name) signature changes so a Revoke click is never yanked
        # out from under the cursor.
        if self._editing is not None:
            return  # never rebuild while an inline rename field is open
        try:
            sig = self._dev_signature(
                self._host.pairing.list_devices() if self._host.pairing else {})
        except Exception:  # noqa: BLE001
            sig = self._dev_sig
        if sig != self._dev_sig:
            self._refresh_devices()

    def _update_ttl_label(self) -> None:
        if self._ttl_left > 0:
            self._ttl_label.setText(
                QApplication.translate("tilauscope_devices", "Code expires in {n}s").format(n=self._ttl_left))
        else:
            self._ttl_label.setText(
                QApplication.translate("tilauscope_devices", "Code expired — tap New code"))

    # ---- device list --------------------------------------------------------

    def _refresh_devices(self) -> None:
        # clear existing rows (keep the trailing stretch)
        while self._dev_layout.count() > 1:
            item = self._dev_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        devices = self._host.pairing.list_devices() if self._host.pairing else {}
        self._dev_sig = self._dev_signature(devices)
        self._dev_title.setText(
            QApplication.translate("tilauscope_devices", "PAIRED DEVICES ({n})").format(n=len(devices)))
        if not devices:
            empty = QLabel(QApplication.translate("tilauscope_devices", "No paired device yet."))
            empty.setStyleSheet(f"color:{_SUB};font-size:12px;")
            self._dev_layout.insertWidget(0, empty)
            return
        for did, info in devices.items():
            self._dev_layout.insertWidget(self._dev_layout.count() - 1, self._device_row(did, info))

    @staticmethod
    def _dev_signature(devices: dict) -> tuple:
        # id + name so the list also rebuilds on a rename (not just add/remove).
        return tuple(sorted((k, str(v.get('name') or '')) for k, v in devices.items()))

    def _device_row(self, device_id: str, info: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(f"background:{_SURFACE};border-radius:10px;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(11, 9, 11, 9)
        name = str(info.get('name') or device_id)

        if self._editing == device_id:
            edit = QLineEdit(name)
            edit.setMaxLength(40)
            edit.setStyleSheet(
                f"QLineEdit {{ background:{_BG}; color:{_TEXT}; border:1px solid {_ACCENT};"
                f" border-radius:8px; padding:6px 9px; }}")
            edit.returnPressed.connect(lambda d=device_id, e=edit: self._commit_rename(d, e.text()))
            ok = self._icon_btn("✓", _GREEN)
            ok.clicked.connect(lambda _=False, d=device_id, e=edit: self._commit_rename(d, e.text()))
            cancel = self._icon_btn("✕", _SUB)
            cancel.clicked.connect(lambda _=False: self._cancel_rename())
            rl.addWidget(edit, 1); rl.addWidget(ok); rl.addWidget(cancel)
            QTimer.singleShot(0, edit.setFocus)
            QTimer.singleShot(0, edit.selectAll)
            return row

        try:
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(int(info.get('paired_at', 0))))
        except Exception:  # noqa: BLE001
            when = ''
        txt = QLabel(f"<b style='color:{_TEXT}'>{name}</b>"
                     f"<br><span style='color:{_SUB};font-size:10px'>{when}</span>")
        txt.setStyleSheet("background:transparent;border:none;")
        rename = self._icon_btn("✏", _ACCENT)
        rename.setToolTip(QApplication.translate("tilauscope_devices", "Rename"))
        rename.clicked.connect(lambda _=False, d=device_id: self._begin_rename(d))
        revoke = QPushButton(QApplication.translate("tilauscope_devices", "Revoke"))
        revoke.clicked.connect(lambda _=False, d=device_id: self._revoke(d))
        revoke.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_RED}; border:1px solid {_RED}44;"
            f" border-radius:8px; padding:6px 11px; }}"
            f"QPushButton:hover {{ background:{_RED}; color:{_BG}; }}")
        rl.addWidget(txt); rl.addStretch(); rl.addWidget(rename); rl.addWidget(revoke)
        return row

    @staticmethod
    def _icon_btn(glyph: str, color: str) -> QPushButton:
        b = QPushButton(glyph)
        b.setFixedSize(30, 30)
        b.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{color}; border:1px solid {color}44;"
            f" border-radius:8px; font-size:13px; }}"
            f"QPushButton:hover {{ background:{color}; color:{_BG}; }}")
        return b

    # ---- rename -------------------------------------------------------------

    def _begin_rename(self, device_id: str) -> None:
        self._editing = device_id
        self._refresh_devices()

    def _cancel_rename(self) -> None:
        self._editing = None
        self._refresh_devices()

    def _commit_rename(self, device_id: str, name: str) -> None:
        if self._host.pairing is not None:
            self._host.pairing.rename(device_id, name)
        self._editing = None
        self._refresh_devices()

    def _revoke(self, device_id: str) -> None:
        if self._editing == device_id:
            self._editing = None
        if self._host.pairing is not None:
            self._host.pairing.revoke(device_id)
        self._refresh_devices()
