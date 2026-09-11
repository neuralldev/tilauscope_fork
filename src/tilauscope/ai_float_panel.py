#
# ABOUT
# AIFloatPanel – floating AI streaming panel for TilauScope.

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
#
# ARCHITECTURE
# Top-level QWidget (no Qt parent, no special window flags); the calling dialog is
# passed as `owner` for positioning/closing. No WA_DeleteOnClose so it can be reused.


from __future__ import annotations

import logging
from typing import Final, Callable

from PyQt6.QtCore    import Qt, QPropertyAnimation, QPoint, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame, QApplication, QSizePolicy,
)
from PyQt6.QtGui import QTextCursor

from tilauscope.tilauscope_types import THEME
from tilauscope.ai_service import TilauAIService

_log: Final[logging.Logger] = logging.getLogger(__name__)

_COLLAPSED_H = 52
_EXPANDED_H  = 400
_PANEL_W     = 370
_GAP         = 14   # pixels between owner right edge and panel left edge


class AIFloatPanel(QWidget):
    """
    Floating AI streaming panel.

    Pass the calling QDialog as *owner*. The panel positions itself to the
    right of the owner on show(), and follows it on reposition() calls.

    The panel is a plain top-level QWidget — no FramelessWindowHint, no Tool,
    no WindowStaysOnTopHint. This is the only approach that gives reliable
    mouse interaction on both macOS and Windows.

    Usage
    -----
        # In __init__ of the calling dialog:
        self._ai_panel = AIFloatPanel(
            task_type  = AITask.ROAST_SUMMARY,
            ai_service = aw.tilau_ai_service,
            title      = "Roast Summary",
            owner      = self,
        )
        self._ai_panel.set_payload_fn(self._build_payload)

        # Toggle from a button:
        self._ai_panel.toggle()

        # On owner move:
        self._ai_panel.reposition()

        # On owner close:
        self._ai_panel.close()
    """

    def __init__(
        self,
        task_type:  str,
        ai_service: TilauAIService,
        title:      str = "AI",
        owner:      QWidget | None = None,
        aw:         object | None = None,   # ApplicationWindow — for live tilau_aiConfig access
    ) -> None:
        # owner.window() as Qt parent keeps this panel above the owner (and its
        # children) on both macOS/Windows without native chrome or global stay-on-top;
        # drag is implemented manually since the frameless hint disables the OS one.
        qt_parent = owner.window() if owner is not None else None
        super().__init__(
            qt_parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        # WA_TranslucentBackground with a real parent (qt_parent) works correctly
        # on both macOS and Windows — the OS composites the window alpha channel,
        # so border-radius corners on the card QFrame are transparent rather than
        # filled with the system window background color.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._task_type  = task_type
        self._ai_service = ai_service
        self._title_text = title
        self._owner      = owner
        self._aw         = aw   # ApplicationWindow; used to read live tilau_aiConfig
        self._payload_fn: Callable[[], str] | None = None
        self._is_expanded = True
        self._accumulated = ""
        self._drag_pos: QPoint | None = None

        self.setWindowTitle(title)
        self._build_ui()
        self._wire_signals()
        self.resize(_PANEL_W, _EXPANDED_H)
        # Don't auto-delete on close — owner controls lifetime explicitly
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_payload_fn(self, fn: Callable[[], str | tuple[str, str]]) -> None:
        """
        Register the payload function.

        The function must return either:
          - a str  → used as the user message; a generic system prompt is used
          - a tuple (system: str, user: str) → used as distinct system/user messages
        """
        self._payload_fn = fn

    def toggle(self) -> None:
        """Show (and reposition) or hide the panel."""
        if self.isVisible():
            self.hide()
        else:
            self.reposition()
            self.show()
            self.raise_()

    def reposition(self) -> None:
        """
        Position the panel to the right of the owner.
        Uses mapToGlobal — pure Qt API, identical on macOS and Windows.
        The Qt parent is owner.window() (for z-order), but geometry is
        computed relative to owner (the dialog, not the main window).
        """
        if self._owner is None or not self._owner.isVisible():
            return
        owner_global = self._owner.mapToGlobal(QPoint(0, 0))
        x = owner_global.x() + self._owner.width() + _GAP
        y = owner_global.y()
        self.move(x, y)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        T = THEME

        # Root is transparent — WA_TranslucentBackground lets the card's
        # border-radius show cleanly on both platforms.
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)

        self._card = QFrame()
        self._card.setObjectName("aiFloatCard")
        self._card.setStyleSheet(f"""
            QFrame#aiFloatCard {{
                background-color: {T['BG']};
                border: 1px solid {T['BORDER']};
                border-radius: 20px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                color: {T['TEXT']};
                }}
        """)
        card_l = QVBoxLayout(self._card)
        card_l.setContentsMargins(20, 14, 20, 14)
        card_l.setSpacing(10)
        root.addWidget(self._card)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        self._grip_btn = QPushButton("▾")
        self._grip_btn.setFixedSize(22, 22)
        self._grip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._grip_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['ACCENT']};
                border: none; font-size: 14px; font-weight: bold; padding: 0;
            }}
            QPushButton:hover {{ color: {T['TEXT']}; }}
        """)
        self._grip_btn.clicked.connect(self._toggle_collapse)
        hdr.addWidget(self._grip_btn)

        title_lbl = QLabel(self._title_text.upper())
        title_lbl.setStyleSheet(
            f"color: {T['ACCENT']}; font-size: 11px; font-weight: 900; letter-spacing: 2px;"
        )
        hdr.addWidget(title_lbl)
        hdr.addStretch()

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color: {T['BORDER']}; font-size: 10px;")
        hdr.addWidget(self._status_dot)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T['SURFACE']}; color: {T['SUBTEXT']};
                border: 1px solid {T['BORDER']}; border-radius: 12px;
                font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{
                background: {T['CRITICAL']}; color: {T['BG']};
                border-color: {T['CRITICAL']};
            }}
        """)
        self._close_btn.clicked.connect(self.hide)
        hdr.addWidget(self._close_btn)
        card_l.addLayout(hdr)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {T['BORDER']}; border: none; border-radius: 0;")
        card_l.addWidget(sep)

        # ── Body (collapsible) ────────────────────────────────────────────────
        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        body_l = QVBoxLayout(self._body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(8)

        self._text_area = QTextEdit()
        self._text_area.setReadOnly(True)
        self._text_area.setPlaceholderText(
            QApplication.translate("tilauscope_ai", "Press ▶ Generate to start…")
        )
        self._text_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._text_area.setStyleSheet(f"""
            QTextEdit {{
                background: {T['SURFACE']};
                color: {T['TEXT']};
                border: 1px solid {T['BORDER']};
                border-radius: 10px;
                padding: 10px;
                font-size: 12px;
            }}
            QScrollBar:vertical {{
                border: none; background: {T['BG']}; width: 6px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {T['ACCENT']}; min-height: 20px; border-radius: 3px;
            }}
        """)
        body_l.addWidget(self._text_area)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._generate_btn = QPushButton(
            "▶  " + QApplication.translate("tilauscope_ai", "Generate")
        )
        self._generate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._generate_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T['ACCENT']}; color: {T['BG']};
                border: none; border-radius: 8px; padding: 7px 18px;
                font-weight: bold; font-size: 11px;
            }}
            QPushButton:hover {{ background: {T['LAVENDER']}; }}
            QPushButton:disabled {{ background: {T['BORDER']}; color: {T['SUBTEXT']}; }}
        """)
        self._generate_btn.clicked.connect(self._on_generate)

        self._cancel_btn = QPushButton(
            "■  " + QApplication.translate("tilauscope_ai", "Stop")
        )
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['CRITICAL']};
                border: 1px solid {T['CRITICAL']}; border-radius: 8px;
                padding: 7px 14px;
                font-weight: bold; font-size: 11px;
            }}
            QPushButton:hover {{ background: {T['CRITICAL']}; color: {T['BG']}; }}
        """)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._preview_btn = QPushButton(
            QApplication.translate("tilauscope_ai", "What is sent")
        )
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_btn.setToolTip(QApplication.translate(
            "tilauscope_ai",
            "Read the exact text that would be sent to your AI provider."))
        self._preview_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['SUBTEXT']};
                border: 1px solid {T['BORDER']}; border-radius: 8px;
                padding: 7px 14px;
                font-size: 11px;
            }}
            QPushButton:hover {{ color: {T['TEXT']}; border-color: {T['TEXT']}; }}
            QPushButton:disabled {{ color: {T['BORDER']}; }}
        """)
        self._preview_btn.clicked.connect(self._on_preview)

        self._clear_btn = QPushButton(
            QApplication.translate("tilauscope_ai", "Clear")
        )
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['SUBTEXT']};
                border: 1px solid {T['BORDER']}; border-radius: 8px;
                padding: 7px 14px;
                font-size: 11px;
            }}
            QPushButton:hover {{ color: {T['TEXT']}; border-color: {T['TEXT']}; }}
        """)
        self._clear_btn.clicked.connect(self._on_clear)

        btn_row.addWidget(self._generate_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._preview_btn)
        btn_row.addWidget(self._clear_btn)
        body_l.addLayout(btn_row)

        card_l.addWidget(self._body)

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _wire_signals(self) -> None:
        svc = self._ai_service
        svc.task_started.connect(self._on_task_started)
        svc.task_busy.connect(self._on_task_busy)
        svc.token_received.connect(self._on_token)
        svc.task_finished.connect(self._on_finished)
        svc.task_error.connect(self._on_error)
        svc.task_cancelled.connect(self._on_cancelled)

    def _unwire_signals(self) -> None:
        svc = self._ai_service
        for sig, slot in [
            (svc.task_started,   self._on_task_started),
            (svc.task_busy,      self._on_task_busy),
            (svc.token_received, self._on_token),
            (svc.task_finished,  self._on_finished),
            (svc.task_error,     self._on_error),
            (svc.task_cancelled, self._on_cancelled),
        ]:
            try:
                sig.disconnect(slot)
            except Exception:
                pass

    # ── TilauAIService slots ───────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_task_started(self, tt: str) -> None:
        if tt != self._task_type:
            return
        self._accumulated = ""
        self._text_area.setPlainText(
            QApplication.translate("tilauscope_ai", "⏳  Thinking…")
        )
        self._set_status("running", THEME["ACCENT"])
        self._generate_btn.setVisible(False)
        self._cancel_btn.setVisible(True)

    @pyqtSlot(str)
    def _on_task_busy(self, tt: str) -> None:
        if tt != self._task_type:
            return
        self._set_status("busy", THEME["WARNING"])

    @pyqtSlot(str, str)
    def _on_token(self, tt: str, chunk: str) -> None:
        if tt != self._task_type:
            return
        self._accumulated += chunk
        self._text_area.setPlainText(self._accumulated)
        cur = self._text_area.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self._text_area.setTextCursor(cur)

    @pyqtSlot(str, object)
    def _on_finished(self, tt: str, result: object) -> None:
        if tt != self._task_type:
            return
        final = str(result) if not isinstance(result, str) else result
        self._text_area.setMarkdown(final)
        self._set_status("done", THEME["SUCCESS"])
        self._generate_btn.setVisible(True)
        self._cancel_btn.setVisible(False)

    @pyqtSlot(str, str)
    def _on_error(self, tt: str, msg: str) -> None:
        if tt != self._task_type:
            return
        self._text_area.setPlainText(f"⚠  Error: {msg}")
        self._set_status("error", THEME["CRITICAL"])
        self._generate_btn.setVisible(True)
        self._cancel_btn.setVisible(False)

    @pyqtSlot(str)
    def _on_cancelled(self, tt: str) -> None:
        if tt != self._task_type:
            return
        self._set_status("cancelled", THEME["WARNING"])
        self._generate_btn.setVisible(True)
        self._cancel_btn.setVisible(False)

    # ── Button handlers ───────────────────────────────────────────────────────

    def _resolve_payload(self) -> tuple[str, str] | None:
        """The two halves of the request, before any scrubbing. None when
        there is nothing to send."""
        if self._payload_fn is None:
            _log.warning("AIFloatPanel: no payload_fn for %s", self._task_type)
            return None

        result = self._payload_fn()

        # Support both (system, user) tuple and plain string payloads.
        if isinstance(result, tuple):
            system_prompt, user_content = result
        else:
            system_prompt = (
                "You are an expert coffee roasting consultant. "
                "Answer clearly and professionally using Markdown."
            )
            user_content = result

        if not user_content.strip():
            return None
        return system_prompt, user_content

    def _live_ai_config(self):
        """Read from live aw.tilau_aiConfig so a change in Settings applies
        without restarting the panel."""
        ai = None
        if self._aw is not None:
            ai = getattr(self._aw, "tilau_aiConfig", None)
        if ai is None:
            ai = self._ai_service.ai_config
        return ai

    def _on_preview(self) -> None:
        """Show the exact text this panel would send, scrubbed, without
        sending it."""
        from tilauscope.tilau_privacy_ui import show_ai_payload_preview  # noqa: PLC0415

        ai = self._live_ai_config()
        if ai is None or not getattr(ai, "engine", None) or not getattr(ai, "apikey", None):
            self._text_area.setPlainText(
                "⚠  AI provider not configured.\n"
                "Open Settings → TilauScope → Configure AI Provider.")
            self._set_status("error", THEME["CRITICAL"])
            return
        payload = self._resolve_payload()
        if payload is None:
            self._text_area.setPlainText(QApplication.translate(
                "tilauscope_ai",
                "There is nothing to send yet — this panel has no roast to "
                "describe."))
            return
        system_prompt, user_content = payload
        recipient = getattr(ai, "provider_name", "") or ""
        show_ai_payload_preview(self, system_prompt, user_content,
                                recipient, task=str(self._task_type))

    def _on_generate(self) -> None:
        payload = self._resolve_payload()
        if payload is None:
            return
        system_prompt, user_content = payload

        from tilauscope.ai_service import _CancelToken                   # noqa: PLC0415
        from tilauscope.ai_support import get_suppress_thinking_params, normalize_engine  # noqa: PLC0415
        import re as _re                                                  # noqa: PLC0415

        ai = self._live_ai_config()

        if ai is None or not getattr(ai, "engine", None) or not getattr(ai, "apikey", None):
            msg = "⚠  AI provider not configured.\nOpen Settings → TilauScope → Configure AI Provider."
            self._text_area.setPlainText(msg)
            self._set_status("error", THEME["CRITICAL"])
            return

        # Who receives this must be named once per provider, before the first
        # request reaches it.
        from tilauscope.tilau_privacy_ui import (  # noqa: PLC0415
            Gate, ensure_ai_disclosure, roast_blocked_message,
        )
        gate = ensure_ai_disclosure(self, ai, self._aw)
        if gate is Gate.BLOCKED_ROAST:
            self._text_area.setPlainText("⚠  " + roast_blocked_message())
            self._set_status("error", THEME["WARNING"])
            return
        if gate is not Gate.ALLOW:
            return

        task_type = self._task_type
        # Single choke point: no payload leaves TilauScope unscrubbed.
        from tilauscope.tilau_privacy import prepare_ai_messages  # noqa: PLC0415
        messages, _report = prepare_ai_messages(
            system_prompt, user_content, task=str(task_type)
        )

        from tilauscope.ai_support import provider_base_url   # add to imports
        _engine     = normalize_engine(ai.engine)
        _model_name = _engine.split("/", 1)[1] if "/" in _engine else _engine
        _base_url   = provider_base_url(_engine)
        # Gemini 2.5 thinking suppression: budget_tokens=0 disables CoT via the
        # OpenAI-compat endpoint extra_body parameter.
        _thinking_params: dict = get_suppress_thinking_params(_engine)

        def _strip_thinking(text: str) -> str:
            """Last-resort filter for <think>/<thinking> tags emitted by some
            local/compat models (Deepseek R1, QwQ). Gemini CoT is suppressed
            upstream via extra_body so this is a safety net only."""
            return _re.sub(
                r"<think(?:ing)?>\s*.*?\s*</think(?:ing)?>",
                "",
                text,
                flags=_re.DOTALL | _re.IGNORECASE,
            ).lstrip()

        def _work(cancel: _CancelToken, on_token: Callable[[str], None]) -> str:
            import json as _json    # noqa: PLC0415
            import httpx as _httpx  # noqa: PLC0415

            # Direct httpx streaming — bypasses openai SDK env-var resolution
            # entirely. Every provider exposes an OpenAI-compat endpoint; we
            # POST to it with a Bearer token and parse SSE chunks ourselves.
            url = _base_url.rstrip("/") + "/chat/completions"
            headers = {
                "Authorization": f"Bearer {ai.apikey}",
                "Content-Type":  "application/json",
            }
            body: dict = {
                "model":    _model_name,
                "messages": messages,
                "stream":   True,
            }
            if _thinking_params:
                body.update(_thinking_params)

            _log.info("AIFloatPanel streaming: POST %s model=%s", url, _model_name)

            response_text = ""
            visible_text  = ""

            with _httpx.Client(timeout=_httpx.Timeout(120.0)) as http:
                with http.stream("POST", url, headers=headers,
                                 content=_json.dumps(body)) as resp:
                    if resp.status_code != 200:
                        body_text = resp.read().decode("utf-8", errors="replace")
                        raise RuntimeError(
                            f"Error code: {resp.status_code} - {body_text}"
                        )
                    for raw_line in resp.iter_lines():
                        if cancel.is_cancelled:
                            break
                        line = raw_line.strip()
                        if not line or line == "data: [DONE]":
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        try:
                            chunk = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                        try:
                            delta = chunk["choices"][0]["delta"]
                        except (KeyError, IndexError):
                            continue
                        # Deepseek-reasoner: skip reasoning tokens
                        if delta.get("reasoning_content"):
                            continue
                        content = delta.get("content") or ""
                        if not content:
                            continue
                        response_text += content
                        clean = _strip_thinking(response_text)
                        if len(clean) > len(visible_text):
                            on_token(clean[len(visible_text):])
                            visible_text = clean

            return _strip_thinking(response_text)

        self._ai_service.submit(task_type, _work)

    def _on_cancel(self) -> None:
        self._ai_service.cancel(self._task_type)

    def _on_clear(self) -> None:
        self._accumulated = ""
        self._text_area.clear()
        self._set_status("idle", THEME["BORDER"])

    # ── Collapse ──────────────────────────────────────────────────────────────

    def _toggle_collapse(self) -> None:
        self._is_expanded = not self._is_expanded
        self._body.setVisible(self._is_expanded)
        self._grip_btn.setText("▾" if self._is_expanded else "▸")
        target_h = _EXPANDED_H if self._is_expanded else _COLLAPSED_H
        self._anim = QPropertyAnimation(self, b"minimumHeight")
        self._anim.setDuration(180)
        self._anim.setEndValue(target_h)
        self._anim.start()
        self.setMaximumHeight(target_h if not self._is_expanded else 16_777_215)

    # ── Status dot ────────────────────────────────────────────────────────────

    def _set_status(self, state: str, color: str) -> None:
        T = THEME
        labels: dict[str, tuple[str, str]] = {
            "idle":      ("●", T["BORDER"]),
            "running":   ("◉", color),
            "done":      ("✓", color),
            "error":     ("✗", color),
            "busy":      ("⏸", color),
            "cancelled": ("○", color),
        }
        symbol, c = labels.get(state, ("●", color))
        self._status_dot.setText(symbol)
        self._status_dot.setStyleSheet(f"color: {c}; font-size: 10px;")

    # ── Drag ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self.childAt(event.position().toPoint())
            if not isinstance(hit, (QPushButton, QTextEdit)):
                self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._unwire_signals()
        super().closeEvent(event)