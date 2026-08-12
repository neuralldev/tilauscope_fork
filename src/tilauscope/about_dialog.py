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
# about_dialog.py
#
# "About TilauScope" window, opened from the TilauScope menu.
# Frameless Catppuccin modal: logo, version/build, Artisan attribution, source link, bug report entry.

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

_log = logging.getLogger(__name__)

_ARTISAN_URL = "https://artisan-scope.org"
_SOURCE_URL = "https://github.com/neuralldev/tilauscope_fork"
# AGPL attribution — Artisan core developers, kept in sync with
# ApplicationWindow.helpAbout() in artisanlib/main.py.
_ARTISAN_DEVS = "Rafael Cobo, Marko Luther &amp; Dave Baxter"


from tilauscope.theme_qss import apply_tilau_theme
from tilauscope.tilauscope_types import THEME


class TilauAboutDlg(QDialog):
    """About TilauScope — fixed-size frameless modal, dragged by its header."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self._drag_from: QPoint | None = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        container = QFrame()
        container.setObjectName("AboutContainer")
        container.setStyleSheet(
            f"#AboutContainer {{ background-color:{THEME['BG']};"
            f" border:2px solid {THEME['BORDER']};"
            f" border-radius:15px; }}")
        root.addWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(26, 16, 26, 22)
        inner.setSpacing(0)

        inner.addLayout(self._build_header())
        inner.addSpacing(18)
        self._add_identity(inner)
        inner.addSpacing(22)
        inner.addWidget(self._rule())
        inner.addSpacing(20)
        self._add_credits(inner)
        inner.addSpacing(20)
        self._add_actions(inner)

        self.setFixedWidth(420)
        self.adjustSize()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel(QApplication.translate("tilauscope_updates", "ABOUT TILAUSCOPE"))
        title.setStyleSheet(
            f"QLabel {{ color:{THEME['ACCENT']}; font-size:14px;"
            f" font-weight:800; letter-spacing:1px; }}")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{THEME['BORDER']}; color:{THEME['CRITICAL']}; border-radius:15px;"
            f" border:1px solid {THEME['CRITICAL']}; font-weight:bold; }}"
            f"QPushButton:hover {{ background:{THEME['CRITICAL']}; color:{THEME['BG']}; }}")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        return header

    def _add_identity(self, inner: QVBoxLayout) -> None:
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = self._load_logo()
        if pix is not None:
            logo.setPixmap(pix)
            inner.addWidget(logo)
            inner.addSpacing(16)

        # Version comes from artisanlib/__init__.py, the single source of truth
        # (tilauscope/__init__.py's __version__ is stale; never read it here).
        from artisanlib import __version__ as version_str, __build__ as build_str

        name = QLabel("Tilau<span style='color:%s'>Scope</span>" % THEME['ACCENT'])
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("font-size:22px;font-weight:700;")
        inner.addWidget(name)

        version = QLabel(QApplication.translate(
            "tilauscope_updates", "Version {0} · build {1}").format(version_str, build_str))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet(f"QLabel {{ color:{THEME['OVERLAY0']}; font-size:12px; }}")
        inner.addWidget(version)

        inner.addSpacing(14)
        tagline = QLabel(QApplication.translate(
            "tilauscope_updates", "Guided roasting assistant for home and enthusiast roasters."))
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setWordWrap(True)
        tagline.setStyleSheet(f"QLabel {{ color:{THEME['SUBTEXT']}; font-size:13px; }}")
        inner.addWidget(tagline)

    def _add_credits(self, inner: QVBoxLayout) -> None:
        # No version number repeated here — the fork tracks Artisan's release lockstep.
        self._add_block(
            inner,
            QApplication.translate("tilauscope_updates", "Built on"),
            "Artisan Roaster Scope<br>"
            f"<a href='{_ARTISAN_URL}' style='color:{THEME['ACCENT']};'>artisan-scope.org</a>")
        inner.addSpacing(14)
        self._add_block(
            inner,
            QApplication.translate("tilauscope_updates", "Artisan core developers"),
            _ARTISAN_DEVS)
        inner.addSpacing(14)
        self._add_block(
            inner,
            QApplication.translate("tilauscope_updates", "Source code"),
            f"<a href='{_SOURCE_URL}' style='color:{THEME['ACCENT']};'>"
            "github.com/neuralldev/tilauscope_fork</a>")

        inner.addSpacing(20)
        legal = QLabel(QApplication.translate(
            "tilauscope_updates", "© Tilau — released under the GNU AGPL v3."))
        legal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        legal.setStyleSheet(f"QLabel {{ color:{THEME['OVERLAY0']}; font-size:11px; }}")
        inner.addWidget(legal)

    def _add_block(self, inner: QVBoxLayout, label: str, body_html: str) -> None:
        key = QLabel(label.upper())
        key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        key.setProperty('variant', 'eyebrow')
        inner.addWidget(key)
        body = QLabel(body_html)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setStyleSheet(f"QLabel {{ color:{THEME['SUBTEXT']}; font-size:12px; }}")
        inner.addWidget(body)

    def _add_actions(self, inner: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        report = QPushButton(QApplication.translate("tilauscope_updates", "Report a bug"))
        report.setMinimumWidth(118)
        report.clicked.connect(self._report_a_bug)
        report.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{THEME['ACCENT']}; border:1px solid {THEME['ACCENT']};"
            f" border-radius:8px; padding:9px 18px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{THEME['ACCENT']}; color:{THEME['BG']}; }}")
        close = QPushButton(QApplication.translate("tilauscope_updates", "Close"))
        close.setMinimumWidth(118)
        close.clicked.connect(self.accept)
        close.setStyleSheet(
            f"QPushButton {{ background:{THEME['BORDER']}; color:{THEME['TEXT']}; border:1px solid {THEME['SURFACE1']};"
            f" border-radius:8px; padding:9px 18px; font-weight:600; }}"
            f"QPushButton:hover {{ border-color:{THEME['SUBTEXT']}; }}")
        row.addStretch()
        row.addWidget(report)
        row.addWidget(close)
        row.addStretch()
        inner.addLayout(row)

    def _rule(self) -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        line.setProperty('variant', 'sep')
        return line

    @staticmethod
    def _load_logo() -> QPixmap | None:
        try:
            # Transparent glyph on the dialog's own ground. getResourcePath()
            # (not getAppPath) resolves includes/ both in dev and frozen bundles.
            from artisanlib.util import getResourcePath
            path = Path(getResourcePath()) / "Icons" / "tilauscope-large.png"
            if not path.exists():
                return None
            pix = QPixmap(str(path))
            if pix.isNull():
                return None
            return pix.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        except Exception:  # pylint: disable=broad-except
            _log.exception("about logo load failed")
            return None

    # ------------------------------------------------------------------
    # Behaviour
    # ------------------------------------------------------------------

    def _report_a_bug(self) -> None:
        try:
            from tilauscope.tilau_exceptions import report_a_bug
            report_a_bug(self)
        except Exception:  # pylint: disable=broad-except
            _log.exception("bug report failed")

    # Frameless windows have no title bar to grab — drag from anywhere.
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        super().mouseReleaseEvent(event)
