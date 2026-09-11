#
# ABOUT
# artisan_message_ticker.py — TilauScope Artisan Message Ticker, standalone widget
# inserted in _SidebarWrapper below alarm_sidebar; fed via ArtisanMessageHook.

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

# ArtisanMessageTicker (widget) + ArtisanMessageHook (monkey-patches sendmessage_internal).
# sendmessage_internal always runs via QTimer.singleShot on the main thread (main.py:12043) — no lock needed.


from __future__ import annotations

import logging
from typing import Final

from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QPushButton, QApplication, QSizePolicy,
)

from tilauscope.theme_qss import mono_family
from tilauscope.tilauscope_types import THEME

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Artisan's own brand blue, sampled from the official icon, and a dimmed
# version of it for older messages. Deliberately NOT theme tokens: this panel
# is badged as upstream Artisan's voice inside TilauScope, so its accent has to
# stay Artisan's whatever the TilauScope palette does. Everything else in this
# file reads from THEME.
_COL_ARTISAN     = "#63B8DD"
_COL_ARTISAN_DIM = "#2E6A8A"

# ── Filtre bruit ──────────────────────────────────────────────────────────────
# Préfixes (lowercased) dont les messages ne présentent pas d'intérêt opérationnel
# pendant la torréfaction.
_NOISE_PREFIXES: Final[frozenset[str]] = frozenset([
    # fichiers / io
    "file not found",
    "saved",
    "loaded",
    "exported",
    "imported",
    "cancelled",
    "canceled",
    "target file",
    "readings exported",
    "readings imported",
    "import failed",
    # config / ui
    "settings",
    "theme",
    "colors set",
    "statistics",
    "excel",
    "csv ranking",
    "csv production",
    "orbiter",
    "rubasse",
    "k202",
    "k204",
    "background profile removed",
    "watermark",
    "set y-coordinate",
    "debug logging",
    "recent roast properties",
    # erreurs hors-contexte
    "scope is not recording",
    # profils format
    "invalid artisan format",
    "artisan json",
    "artisan configured for",
    # divers
    "super on",
    "super off",
    "simulator started",
    "simulator stopped",
    "url open profile",
    "follow on",
    "follow off",
])

_MIN_MSG_LEN: Final[int] = 4    # messages trop courts ignorés (clear résiduel, etc.)
_MAX_HISTORY: Final[int] = 40   # FIFO max messages conservés


def _is_roast_noise(msg: str) -> bool:
    """Return True if the message is not worth displaying in the ticker."""
    if not msg:
        return True
    lo = msg.strip().lower()  # single strip — reused for both length check and prefix match
    if len(lo) < _MIN_MSG_LEN:
        return True
    return any(lo.startswith(prefix) for prefix in _NOISE_PREFIXES)


# ── Widget ligne de message ───────────────────────────────────────────────────

class _MessageRow(QWidget):
    """
    Une ligne dans le ticker : horodatage + texte.
    Bord gauche bleu Artisan vif pour le dernier message,
    bleu sombre + texte blanc pour les anciens.
    Les refs aux widgets internes sont stockées pour que dim() soit fiable.
    """

    def __init__(self, timestamp: str, message: str, is_latest: bool = True, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        border_col = _COL_ARTISAN     if is_latest else _COL_ARTISAN_DIM
        text_col   = _COL_ARTISAN     if is_latest else THEME['TEXT']
        ts_col     = _COL_ARTISAN_DIM if is_latest else THEME['OVERLAY0']

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Frame portant le bord gauche coloré
        self._frame = QFrame(self)
        self._apply_frame_style(border_col)
        outer.addWidget(self._frame)

        inner = QVBoxLayout(self._frame)
        inner.setContentsMargins(8, 4, 6, 4)
        inner.setSpacing(1)

        # Horodatage
        self._ts_lbl = QLabel(timestamp)
        self._apply_ts_style(ts_col)
        self._ts_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        inner.addWidget(self._ts_lbl)

        # Texte du message
        self._msg_lbl = QLabel(message)
        self._apply_msg_style(text_col)
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        inner.addWidget(self._msg_lbl)

    # ── Helpers de style (appelés à la construction et dans dim()) ────────────

    def _apply_frame_style(self, border_col: str) -> None:
        self._frame.setStyleSheet(f"""
            QFrame {{
                background: {THEME['BORDER']};
                border-radius: 4px;
                border-left: 3px solid {border_col};
            }}
        """)

    def _apply_ts_style(self, col: str) -> None:
        self._ts_lbl.setStyleSheet(
            f"color: {col}; font-size: 9px;"
            f" font-family: '{mono_family()}', monospace;"
            "background: transparent; border: none;"
        )

    def _apply_msg_style(self, col: str) -> None:
        self._msg_lbl.setStyleSheet(
            f"color: {col}; font-size: 11px; "
            "background: transparent; border: none;"
        )

    def dim(self) -> None:
        """Passage vers l'état 'ancien' : bordure bleue sombre, texte blanc, ts gris."""
        self._apply_frame_style(_COL_ARTISAN_DIM)
        self._apply_ts_style(THEME['OVERLAY0'])
        self._apply_msg_style(THEME['TEXT'])


# ── Widget principal ─────────────────────────────────────────────────────────

class ArtisanMessageTicker(QWidget):
    """
    Zone d'historique des messages Artisan pendant la torréfaction.
    Hauteur fixe (TICKER_H px), scroll vertical, insertion en tête (LIFO visible).

    Usage dans _SidebarWrapper :
        self.msg_ticker = ArtisanMessageTicker(self)
        layout.addWidget(self.msg_ticker, stretch=0)   # sous alarm_sidebar

    Alimentation :
        self.msg_ticker.push(message)   # depuis ArtisanMessageHook uniquement
    """

    TICKER_H: Final[int] = 155  # hauteur fixe du widget (≈ 3 lignes confortables)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.TICKER_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._rows: list[_MessageRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Séparateur visuel ──────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {THEME['SURFACE1']}; border: none;")
        root.addWidget(sep)

        # ── Barre titre : icône + label + compteur + clear ─────────────────
        title_bar = QWidget()
        title_bar.setFixedHeight(24)
        title_bar.setStyleSheet(f"background: {THEME['BORDER']};")
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(6, 0, 4, 0)
        title_row.setSpacing(4)

        # Icône Artisan — SVG inline du « a » stylisé, coloré en bleu Artisan
        # Même pattern que header_icons.py : pas de fichier disque, portable DMG/EXE
        _SVG_ARTISAN = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<rect width="100" height="100" rx="22" ry="22" fill="#63B8DD"/>'
            '<path d="M67 22 C67 22 67 22 67 22 '
            'C67 22 35 20 32 50 '
            'C29 73 45 80 55 78 '
            'C65 76 72 68 72 58 '
            'C72 45 62 38 50 38 '
            'C41 38 36 44 36 51 '
            'C36 59 41 64 50 64 '
            'C53 64 55 62 55 62 '
            'L55 78" '
            'stroke="white" stroke-width="11" stroke-linecap="round" '
            'fill="none"/>'
            '</svg>'
        )
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(16, 16)
        icon_lbl.setScaledContents(True)
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import QByteArray
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtGui import QPainter as _QPainter, QImage as _QImage
        _renderer = QSvgRenderer(QByteArray(_SVG_ARTISAN.encode()))
        _img = _QImage(16, 16, _QImage.Format.Format_ARGB32)
        _img.fill(0)
        _p = _QPainter(_img)
        _renderer.render(_p)
        _p.end()
        icon_lbl.setPixmap(QPixmap.fromImage(_img))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        title_row.addWidget(icon_lbl)

        hdr = QLabel(QApplication.translate("tilauscope_ticker", "ARTISAN"))
        hdr.setStyleSheet(
            f"color: {_COL_ARTISAN}; font-weight: bold; font-size: 10px;"
            "letter-spacing: 1px;"
            "background: transparent; border: none;"
        )
        title_row.addWidget(hdr, 1)

        self._count_lbl = QLabel("0")
        self._count_lbl.setStyleSheet(
            f"color: {_COL_ARTISAN}; background: {THEME['BG']}; font-size: 9px;"
            "font-weight: 700; border-radius: 8px; padding: 1px 5px;"
            f" font-family: '{mono_family()}', monospace;"
        )
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setFixedHeight(15)
        self._count_lbl.setVisible(False)
        title_row.addWidget(self._count_lbl)

        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(16, 16)
        clear_btn.setToolTip(QApplication.translate("tilauscope_ticker", "Clear Artisan messages"))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']}; color: {THEME['OVERLAY0']};
                border-radius: 3px; border: none;
                font-size: 9px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {THEME['SURFACE1']}; color: {_COL_ARTISAN}; }}
            QPushButton:pressed {{ background: {_COL_ARTISAN}; color: {THEME['BG']}; }}
        """)
        clear_btn.clicked.connect(self.clear)
        title_row.addWidget(clear_btn)

        root.addWidget(title_bar)

        # ── Zone scrollable ────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Kept local rather than left to the base sheet: this scrollbar is 4px,
        # not the base's 12px — a hairline beside a narrow message column. The
        # colours are the base's, by token.
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: {THEME['BG']}; width: 4px; margin: 0; border-radius: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {THEME['SURFACE1']}; min-height: 16px; border-radius: 2px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {THEME['SURFACE2']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._content_layout.setSpacing(3)
        self._content_layout.setContentsMargins(4, 3, 4, 3)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)

    # ── API publique ──────────────────────────────────────────────────────────

    def push(self, message: str) -> None:
        """
        Insère un nouveau message en tête de liste.
        Atténue le précédent message (s'il existe).
        Écrête à _MAX_HISTORY.
        Appelé uniquement depuis le main thread (sécurité garantie par Artisan).
        """
        # Atténuer le premier (dernier inséré = le plus récent)
        if self._rows:
            self._rows[0].dim()

        ts = QDateTime.currentDateTime().toString("hh:mm:ss")
        row = _MessageRow(timestamp=ts, message=message, is_latest=True)
        self._content_layout.insertWidget(0, row)
        self._rows.insert(0, row)

        # Écrêtage FIFO
        while len(self._rows) > _MAX_HISTORY:
            old = self._rows.pop()
            self._content_layout.removeWidget(old)
            old.deleteLater()

        self._update_count()

        # Scroll en haut pour montrer le dernier message
        self._scroll.verticalScrollBar().setValue(0)

    def clear(self) -> None:
        """Vide tout l'historique."""
        for row in self._rows:
            self._content_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._update_count()

    # ── Interne ───────────────────────────────────────────────────────────────

    def _update_count(self) -> None:
        n = len(self._rows)
        self._count_lbl.setText(str(n))
        self._count_lbl.setVisible(n > 0)


# ── Hook monkey-patch ─────────────────────────────────────────────────────────

class ArtisanMessageHook:
    """
    Intercepte sendmessage_internal sur l'instance ApplicationWindow Artisan
    pour router les messages opérationnels vers ArtisanMessageTicker.

    Lifetime : calé sur TilauScope (install à __init__, remove à closeEvent).

    Usage dans TilauScope.__init__ (APRÈS init_ui) :
        self._msg_hook = ArtisanMessageHook(self.aw, self.collapsible_events.sidebar.msg_ticker)
        self._msg_hook.install()

    Usage dans TilauScope.closeEvent :
        if hasattr(self, '_msg_hook'):
            self._msg_hook.remove()
    """

    def __init__(self, aw, ticker: ArtisanMessageTicker):
        self._aw = aw
        self._ticker = ticker
        self._original: object | None = None   # référence à la méthode originale
        self._original_off_recorder: object | None = None

    def install(self) -> None:
        if self._original is not None:
            return  # already installed — idempotent

        self._install_off_recorder_guard()
        self._original = self._aw.sendmessage_internal

        ticker   = self._ticker
        aw       = self._aw
        original = self._original

        def _hooked(message: str, append: bool = True,
                    style: str | None = None, repaint: bool = True) -> None:
            # 1. Original Artisan behaviour (messagelabel, messagehist, etc.)
            original(message, append, style, repaint)  # type: ignore[call-arg]

            # 2. Route to ticker — only during active recording and for meaningful messages
            try:
                if (append
                        and aw.qmc.flagstart
                        and message
                        and not _is_roast_noise(message)):
                    ticker.push(message)
            except Exception as exc:
                _log.debug("ArtisanMessageHook: routing error: %s", exc)

        # Direct instance attribute replacement — no MethodType wrapper needed
        # (instance attribute lookup takes precedence over class method)
        self._aw.sendmessage_internal = _hooked  # type: ignore[method-assign]
        _log.debug("ArtisanMessageHook: installed")

    def _install_off_recorder_guard(self) -> None:
        """Keep Artisan's status line hidden across a STOP.

        `qmc.OffRecorder()` unconditionally does `messagelabel.setVisible(True)`
        (artisanlib/canvas.py), so pressing STOP brought the Artisan status line
        back above the canvas even though TilauScope routes those messages to
        its own ticker. Hiding it once at startup is not enough — it has to be
        re-hidden after every stop, whoever triggered it (TilauScope button,
        Artisan button, alarm).
        """
        if self._original_off_recorder is not None:
            return
        qmc = self._aw.qmc
        self._original_off_recorder = qmc.OffRecorder
        original = self._original_off_recorder
        aw = self._aw

        def _hooked_off_recorder(*args, **kwargs):
            result = original(*args, **kwargs)  # type: ignore[misc,operator]
            try:
                aw.messagelabel.setVisible(False)
            except Exception as exc:
                _log.debug("ArtisanMessageHook: could not re-hide messagelabel: %s", exc)
            return result

        qmc.OffRecorder = _hooked_off_recorder

    def remove(self) -> None:
        if self._original_off_recorder is not None:
            try:
                self._aw.qmc.OffRecorder = self._original_off_recorder
            except Exception as exc:
                _log.warning("ArtisanMessageHook: could not restore OffRecorder: %s", exc)
            finally:
                self._original_off_recorder = None
        if self._original is None:
            return
        try:
            self._aw.sendmessage_internal = self._original  # type: ignore[method-assign]
        except Exception as exc:
            _log.warning("ArtisanMessageHook: could not restore: %s", exc)
        finally:
            self._original = None
        _log.debug("ArtisanMessageHook: removed")