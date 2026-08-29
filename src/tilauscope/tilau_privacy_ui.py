#
# ABOUT
# tilau_privacy_ui.py - what the operator is told before something leaves

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

"""Disclosure and consent screens for anything that leaves the machine.

``tilau_privacy`` decides *what* a payload may contain. This module decides
*whether the operator has been told*, which is the other half of the same
obligation and the half that needs Qt.

Three gates:

``ensure_ai_disclosure()``
    Named-recipient disclosure, once per AI provider. Re-armed whenever the
    provider changes, because the recipient is exactly what has to be named.

``show_ai_payload_preview()``
    The exact scrubbed text, on demand, before any of it is sent.

``ensure_geo_consent()``
    Consent for the one call that hands a third party the operator's IP
    address in order to turn it into a town.

Kept apart from ``tilau_privacy`` so the scrubber itself stays free of Qt and
can be imported by a worker thread, a test, or a log formatter.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from tilauscope.ai_support import TilauAIConfig

_log: Final[logging.Logger] = logging.getLogger(__name__)

#: Which provider the operator has been told about. Holds a client_id, not an
#: engine: changing model keeps the same recipient, changing provider does not.
AI_DISCLOSURE_KEY: Final[str] = 'tilauscope/privacy/ai_disclosure_provider'

#: Consent for the IP-to-town lookup behind the online weather button.
GEO_CONSENT_KEY: Final[str] = 'tilauscope/privacy/geo_lookup_consent'


class Gate(StrEnum):
    """Outcome of a disclosure gate."""

    ALLOW         = 'ALLOW'          # told, or told previously — proceed
    DECLINED      = 'DECLINED'       # operator said no — abort without a word
    BLOCKED_ROAST = 'BLOCKED_ROAST'  # a roast is running — refuse and say why


# ─────────────────────────────────────────────────────────────────────────────
# Stored answers
# ─────────────────────────────────────────────────────────────────────────────

def acknowledged_ai_provider() -> str:
    """client_id of the provider the operator has been told about, or ''."""
    try:
        return str(QSettings().value(AI_DISCLOSURE_KEY, '', type=str) or '')
    except Exception:  # noqa: BLE001 - a missing store must not block a roast
        return ''


def forget_ai_disclosure() -> None:
    """Re-arm the disclosure. Called from Settings, and on a provider change."""
    QSettings().remove(AI_DISCLOSURE_KEY)


def geo_consent_granted() -> bool:
    try:
        return bool(QSettings().value(GEO_CONSENT_KEY, False, type=bool))
    except Exception:  # noqa: BLE001
        return False


def forget_geo_consent() -> None:
    QSettings().remove(GEO_CONSENT_KEY)


# ─────────────────────────────────────────────────────────────────────────────
# Gate 1 — named-recipient disclosure before the first request
# ─────────────────────────────────────────────────────────────────────────────

def roast_blocked_message() -> str:
    """Why the request was refused, for the caller to show in its own way."""
    return QApplication.translate(
        'tilauscope_privacy',
        'This is the first request to that AI provider, and reading who '
        'receives it is not something to do with a roast running. Finish '
        'the roast, then ask again.')


def show_roast_blocked(parent: QWidget | None) -> None:
    """Say why the request was refused, for a caller with nowhere to write it.

    A one-click acknowledgement, never a decision: the operator asked for
    something the application will not do until the batch is out.
    """
    from tilauscope.tilauscope_types import show_styled_message  # noqa: PLC0415

    show_styled_message(
        parent,
        QApplication.translate('tilauscope_privacy', 'Not during a roast'),
        roast_blocked_message(),
        QMessageBox.Icon.Warning,
    )


def _roast_in_progress(aw: object | None) -> bool:
    """True once the batch has been charged and is not yet put away."""
    if aw is None:
        return False
    try:
        qmc = aw.qmc                                     # type: ignore[attr-defined]
        return bool(qmc.flagstart) and qmc.timeindex[0] > -1
    except Exception:  # noqa: BLE001 - never let this check stop a request
        return False


def _disclosure_text(cfg: TilauAIConfig) -> str:
    engine = str(getattr(cfg, 'engine', '') or '')
    model  = engine.split('/', 1)[1] if '/' in engine else engine
    who    = cfg.provider_name
    named  = f'{who} ({model})' if model else who

    T = QApplication.translate
    return '\n\n'.join((
        T('tilauscope_privacy', 'This request leaves your computer.'),
        T('tilauscope_privacy',
          'TilauScope has no intelligence of its own. To answer, it sends '
          'your question and the roast data it needs to the AI provider you '
          'configured:') + f'\n\n        {named}',
        T('tilauscope_privacy',
          'Sent: your question, the roast figures and the bean record — and '
          'nothing else.'),
        T('tilauscope_privacy',
          'Removed before sending: e-mail addresses, telephone numbers, bank '
          'details, file paths, network and device identifiers, your operator '
          'and company names.'),
        T('tilauscope_privacy',
          'Stays here: your provider key, your roast files, your bean '
          'library.'),
        T('tilauscope_privacy',
          'The provider may be outside the European Union and keeps the '
          'request for its own retention period. Nothing you send is used to '
          'decide anything on your behalf.'),
        T('tilauscope_privacy',
          'You can read the exact text before every request: use "What is '
          'sent" in the panel.'),
    ))


def ensure_ai_disclosure(parent: QWidget | None,
                         cfg: TilauAIConfig | None,
                         aw: object | None = None) -> Gate:
    """Tell the operator who receives this request, once per provider.

    Returns :class:`Gate`. Anything other than ``ALLOW`` means the caller must
    send nothing at all — including when the dialog could not be raised, which
    is why every failure path here returns ``DECLINED`` rather than ``ALLOW``.
    """
    if cfg is None:
        return Gate.DECLINED

    client_id = str(getattr(cfg, 'client_id', '') or '')
    if client_id and acknowledged_ai_provider() == client_id:
        return Gate.ALLOW

    if _roast_in_progress(aw):
        return Gate.BLOCKED_ROAST

    from tilauscope.tilauscope_types import show_styled_message  # noqa: PLC0415

    accept = QApplication.translate('tilauscope_privacy', 'Send to {0}').format(
        cfg.provider_name)
    try:
        clicked = show_styled_message(
            parent,
            QApplication.translate('tilauscope_privacy',
                                   'Before the first request'),
            _disclosure_text(cfg),
            QMessageBox.Icon.Information,
            buttons=[QApplication.translate('tilauscope_privacy', 'Not now'),
                     accept],
        )
    except Exception as exc:  # noqa: BLE001
        _log.error('AI disclosure could not be shown: %s', exc)
        return Gate.DECLINED

    # Index 1 is the accept button. A closed dialog returns -1, and any other
    # value means the click was not understood — both must not send anything.
    if clicked != 1:
        return Gate.DECLINED

    QSettings().setValue(AI_DISCLOSURE_KEY, client_id)
    _log.info('AI disclosure acknowledged for provider %s', client_id)
    return Gate.ALLOW


# ─────────────────────────────────────────────────────────────────────────────
# Gate 2 — the exact payload, on demand
# ─────────────────────────────────────────────────────────────────────────────

class AiPayloadPreviewDialog(QDialog):
    """The scrubbed request, exactly as it will be sent, and what was taken out."""

    def __init__(self, messages: list[dict[str, str]], report: object,
                 recipient: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from tilauscope.tilauscope_types import THEME as T  # noqa: PLC0415

        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._body_text = self._compose(messages)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName('privacyPreviewCard')
        card.setStyleSheet(f"""
            QFrame#privacyPreviewCard {{
                background-color: {T['BG']};
                border: 2px solid {T['ACCENT']};
                border-radius: 18px;
            }}
            QLabel {{ background: transparent; border: none; color: {T['TEXT']}; }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 24, 28, 24)
        cl.setSpacing(12)
        outer.addWidget(card)

        hdr = QHBoxLayout()
        title = QLabel(QApplication.translate('tilauscope_privacy',
                                              'WHAT IS SENT'))
        title.setStyleSheet(f"color: {T['ACCENT']}; font-size: 15px; "
                            f"font-weight: 900; letter-spacing: 2px;")
        close_btn = QPushButton('✕')
        close_btn.setFixedSize(28, 28)
        close_btn.setProperty('variant', 'icon')
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T['SURFACE']}; color: {T['TEXT']};
                border-radius: 14px; border: 1px solid {T['BORDER']};
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {T['CRITICAL']}; color: {T['BG']}; }}
        """)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(close_btn)
        cl.addLayout(hdr)

        going = QLabel(QApplication.translate(
            'tilauscope_privacy', 'Going to  {0}').format(recipient))
        going.setStyleSheet(f"color: {T['SUBTEXT']}; font-size: 12px;")
        cl.addWidget(going)

        removed = QLabel(self._removed_line(report))
        removed.setWordWrap(True)
        removed.setStyleSheet(
            f"color: {T['SUCCESS'] if self._is_clean(report) else T['WARNING']}; "
            f"font-size: 12px;")
        cl.addWidget(removed)

        shortened = self._shortened_line(report)
        if shortened:
            lbl = QLabel(shortened)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {T['WARNING']}; font-size: 12px;")
            cl.addWidget(lbl)

        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(self._body_text)
        view.setStyleSheet(f"""
            QTextEdit {{
                background: {T['SURFACE']}; color: {T['TEXT']};
                border: 1px solid {T['BORDER']}; border-radius: 10px;
                padding: 10px; font-size: 12px;
                font-family: 'JetBrains Mono', monospace;
            }}
            QScrollBar:vertical {{
                border: none; background: {T['BG']}; width: 6px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {T['ACCENT']}; min-height: 20px; border-radius: 3px;
            }}
        """)
        cl.addWidget(view, 1)

        foot = QLabel(QApplication.translate(
            'tilauscope_privacy',
            'This is the exact text. Nothing else leaves your computer.'))
        foot.setWordWrap(True)
        foot.setStyleSheet(f"color: {T['SUBTEXT']}; font-size: 11px; "
                           f"font-style: italic;")
        cl.addWidget(foot)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()
        copy_btn = QPushButton(QApplication.translate('tilauscope_privacy',
                                                      'Copy'))
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T['SURFACE']}; color: {T['TEXT']};
                border: 1px solid {T['BORDER']}; border-radius: 8px;
                padding: 7px 18px; font-size: 11px;
            }}
            QPushButton:hover {{ border-color: {T['TEXT']}; }}
        """)
        copy_btn.clicked.connect(self._copy)
        close2 = QPushButton(QApplication.translate('tilauscope_privacy',
                                                    'Close'))
        close2.setCursor(Qt.CursorShape.PointingHandCursor)
        close2.setStyleSheet(f"""
            QPushButton {{
                background: {T['ACCENT']}; color: {T['BG']};
                border: none; border-radius: 8px; padding: 7px 18px;
                font-weight: bold; font-size: 11px;
            }}
            QPushButton:hover {{ background: {T['LAVENDER']}; }}
        """)
        close2.clicked.connect(self.accept)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(close2)
        cl.addLayout(btn_row)

        self.resize(680, 560)

    # ── content ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compose(messages: list[dict[str, str]]) -> str:
        heads = {
            'system': QApplication.translate('tilauscope_privacy',
                                             'INSTRUCTIONS'),
            'user':   QApplication.translate('tilauscope_privacy',
                                             'YOUR QUESTION AND DATA'),
        }
        blocks = []
        for msg in messages:
            role = str(msg.get('role', ''))
            blocks.append(f"{heads.get(role, role.upper())}\n"
                          f"{msg.get('content', '')}")
        return '\n\n'.join(blocks)

    @staticmethod
    def _is_clean(report: object) -> bool:
        return bool(getattr(report, 'is_clean', False))

    @staticmethod
    def _removed_line(report: object) -> str:
        if AiPayloadPreviewDialog._is_clean(report):
            return QApplication.translate(
                'tilauscope_privacy',
                'Removed   nothing — this request carried no personal data')
        summary = ''
        try:
            summary = report.summary()          # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        return QApplication.translate('tilauscope_privacy',
                                      'Removed   {0}').format(summary)

    @staticmethod
    def _shortened_line(report: object) -> str:
        n = int(getattr(report, 'truncated_chars', 0) or 0)
        if not n:
            return ''
        return QApplication.translate(
            'tilauscope_privacy',
            'Shortened   {0} characters removed from the end (too long for '
            'the provider)').format(n)

    def _copy(self) -> None:
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(self._body_text)


def show_ai_payload_preview(parent: QWidget | None,
                            system_prompt: str,
                            user_content: str,
                            recipient: str,
                            task: str = '') -> None:
    """Build the payload exactly as a request would, and show it."""
    from tilauscope.tilau_privacy import prepare_ai_messages  # noqa: PLC0415

    messages, report = prepare_ai_messages(system_prompt, user_content,
                                           task=task)
    dlg = AiPayloadPreviewDialog(messages, report, recipient, parent)
    dlg.exec()


# ─────────────────────────────────────────────────────────────────────────────
# Gate 3 — turning an IP address into a town
# ─────────────────────────────────────────────────────────────────────────────

def hand_over_to_manual_entry(field: QWidget | None) -> None:
    """Put the operator in the field they just chose to fill themselves.

    Declining a lookup is not a failure, it is the other way of filling the
    same values — so the cursor lands in the field, selected, ready to be
    typed over. Deferred past the dialog's fade-out, which would otherwise
    hand the focus back to the button that opened it.
    """
    if field is None:
        return

    def _land() -> None:
        try:
            field.setFocus(Qt.FocusReason.OtherFocusReason)
            selector = getattr(field, 'selectAll', None)
            if callable(selector):
                selector()
        except RuntimeError:      # the window closed while the dialog faded
            pass

    from tilauscope.tilauscope_types import STYLED_MESSAGE_FADE_MS  # noqa: PLC0415
    QTimer.singleShot(STYLED_MESSAGE_FADE_MS + 50, _land)


def ensure_geo_consent(parent: QWidget | None) -> bool:
    """Ask before handing the operator's IP address to the lookup service.

    A yes is remembered; a no is not, so the button keeps explaining itself
    rather than going quietly dead.
    """
    if geo_consent_granted():
        return True

    from tilauscope.tilauscope_types import show_styled_message  # noqa: PLC0415

    T = QApplication.translate
    text = '\n\n'.join((
        T('tilauscope_beancave', 'Where should the weather be read?'),
        T('tilauscope_beancave',
          'TilauScope does not know where you are. To read the weather it '
          'first asks ip-api.com, a service outside the European Union, '
          'which turns your internet address into a town — then asks '
          'Open-Meteo for that town\'s temperature, humidity and pressure.'),
        T('tilauscope_beancave',
          'Your internet address is what identifies your connection. Neither '
          'service is told anything about you or your coffee.'),
        T('tilauscope_beancave',
          'You can always type the three values by hand instead.'),
    ))
    try:
        clicked = show_styled_message(
            parent,
            T('tilauscope_beancave', 'Online weather'),
            text,
            QMessageBox.Icon.Information,
            buttons=[T('tilauscope_beancave', "I'll type it"),
                     T('tilauscope_beancave', 'Find my town and fill them in')],
        )
    except Exception as exc:  # noqa: BLE001
        _log.error('Location consent could not be shown: %s', exc)
        return False

    if clicked != 1:
        return False

    QSettings().setValue(GEO_CONSENT_KEY, True)
    _log.info('Location lookup consent granted')
    return True
