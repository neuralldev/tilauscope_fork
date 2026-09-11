#
# ABOUT
# ai_support.py - Support for AI-generated annotations on the graph (e.g. BT tips, roast phase detection)

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

from __future__ import annotations

import base64
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Final

from mashumaro import DataClassDictMixin, field_options

from PyQt6.QtCore    import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QComboBox, QApplication, QWidget, QMenu,
)
from PyQt6.QtGui import QAction

_log: Final[logging.Logger] = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Known providers + their default engine strings
# instructor's from_provider() accepts these model strings directly.
# ─────────────────────────────────────────────────────────────────────────────

PROVIDERS: dict[str, dict] = {
    "Gemini": {
        "client_id": "gemini",
        "engines": [
            "google/gemini-2.5-flash",
            "google/gemini-2.5-pro-preview-06-05",
            "google/gemini-2.0-flash",
            "google/gemini-1.5-pro",
        ],
        "key_hint":       "AIza…",
        "key_url":        "https://aistudio.google.com/app/apikey",
        "browse_url":     "https://ai.google.dev/gemini-api/docs/models",
        "models_endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "thinking_engines": set(),
    },
    "OpenAI": {
        "client_id": "openai",
        "engines": [
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "openai/gpt-4-turbo",
        ],
        "key_hint":       "sk-…",
        "key_url":        "https://platform.openai.com/api-keys",
        "browse_url":     "https://platform.openai.com/docs/models",
        "models_endpoint": "https://api.openai.com/v1/models",
    },
    "Anthropic": {
        "client_id": "anthropic",
        "engines": [
            "anthropic/claude-3-5-haiku-latest",
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-opus-4-5",
        ],
        "key_hint":       "sk-ant-…",
        "key_url":        "https://console.anthropic.com/settings/keys",
        "browse_url":     "https://docs.anthropic.com/en/docs/about-claude/models/overview",
        "models_endpoint": "https://api.anthropic.com/v1/models",
    },
    "Mistral": {
        "client_id": "mistral",
        "engines": [
            "mistral/mistral-small-latest",
            "mistral/mistral-medium-latest",
            "mistral/mistral-large-latest",
        ],
        "key_hint":       "…",
        "key_url":        "https://console.mistral.ai/api-keys",
        "browse_url":     "https://docs.mistral.ai/getting-started/models/models_overview/",
        "models_endpoint": "https://api.mistral.ai/v1/models",
    },
    "Deepseek": {
        "client_id": "deepseek",
        "engines": [
            "deepseek/deepseek-chat",
            "deepseek/deepseek-reasoner",
        ],
        "key_hint":       "sk-…",
        "key_url":        "https://platform.deepseek.com/api_keys",
        "browse_url":     "https://api-docs.deepseek.com/quick_start/pricing",
        "models_endpoint": "https://api.deepseek.com/v1/models",
        # deepseek-reasoner streams thinking in delta.reasoning_content (already
        # filtered in ai_float_panel._work); no suppress_thinking_params needed.
        "thinking_engines": {"deepseek/deepseek-reasoner"},
    },
}


# Bare model names saved by older configs → canonical "provider/model" string.
# Only models that were actually shipped are listed; new models discovered via
# Browse are already stored with their full prefix and need no entry here.
_LEGACY_ENGINE_MAP: dict[str, str] = {
    "gemini-2.5-flash":             "google/gemini-2.5-flash",
    "gemini-2.5-pro-preview-06-05": "google/gemini-2.5-pro-preview-06-05",
    "gemini-2.0-flash":             "google/gemini-2.0-flash",
    "gemini-1.5-pro":               "google/gemini-1.5-pro",
    "gpt-4o-mini":                  "openai/gpt-4o-mini",
    "gpt-4o":                       "openai/gpt-4o",
    "gpt-4-turbo":                  "openai/gpt-4-turbo",
    "claude-3-5-haiku-latest":      "anthropic/claude-3-5-haiku-latest",
    "claude-sonnet-4-5":            "anthropic/claude-sonnet-4-5",
    "claude-opus-4-5":              "anthropic/claude-opus-4-5",
    "mistral-small-latest":         "mistral/mistral-small-latest",
    "mistral-medium-latest":        "mistral/mistral-medium-latest",
    "mistral-large-latest":         "mistral/mistral-large-latest",
    "deepseek-chat":                "deepseek/deepseek-chat",
    "deepseek-reasoner":            "deepseek/deepseek-reasoner",
}


from tilauscope.theme_qss import apply_tilau_theme


def normalize_engine(engine: str) -> str:
    """Return canonical 'provider/model' string, migrating legacy bare names."""
    if "/" in engine:
        prov, _, model = engine.partition("/")
        return f"google/{model}" if prov == "gemini" else engine  # gemini/ → google/ alias
    return _LEGACY_ENGINE_MAP.get(engine, engine)


def get_suppress_thinking_params(engine: str) -> dict:
    """Return params to merge into the JSON body to suppress CoT, or {}.

    Gemini 2.5 via the OpenAI-compat endpoint sends thinking in
    delta.reasoning_content — filtered client-side, no body param needed.
    """
    engine = normalize_engine(engine)
    for info in PROVIDERS.values():
        thinking_engines: set = info.get("thinking_engines", set())
        if engine in thinking_engines:
            return info.get("suppress_thinking_params", {})
    return {}

PROVIDER_BASE_URLS: dict[str, str] = {
    "google":    "https://generativelanguage.googleapis.com/v1beta/openai/",
    "gemini":    "https://generativelanguage.googleapis.com/v1beta/openai/",  # legacy alias
    "openai":    "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "mistral":   "https://api.mistral.ai/v1",
    "deepseek":  "https://api.deepseek.com/v1",
}

def provider_base_url(engine: str) -> str:
    """Single source of truth for the OpenAI-compat base URL of an engine."""
    eng = normalize_engine(engine)
    prefix = eng.split("/", 1)[0] if "/" in eng else "openai"
    return PROVIDER_BASE_URLS.get(prefix, PROVIDER_BASE_URLS["openai"])


# Reverse lookup: client_id → provider display name
_CLIENT_ID_TO_PROVIDER: dict[str, str] = {
    v["client_id"]: k for k, v in PROVIDERS.items()
}


# ─────────────────────────────────────────────────────────────────────────────
# TilauAIConfig  –  serialisable, attached to aw.tilau_aiConfig
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TilauAIConfig(DataClassDictMixin):
    """Which provider and model to use. The key itself lives in the keychain.

    ``apikey_encoded`` is read on the way in and never written on the way out:
    it is where installations before this release kept the key, and reading it
    once is what migrates them. Both it and ``_apikey`` are omitted from
    ``to_dict()``, so nothing secret reaches the settings file — nor the
    ``.aset`` an operator exports to share a machine setup.
    """

    client_id:       str = "google"
    engine:          str = "google/gemini-2.0-flash"

    # Legacy, read-only: migrated to the keychain on first access, then dropped.
    apikey_encoded:  str = field(default="",
                                 metadata=field_options(serialize="omit"))

    # Session cache for the keychain value. Never serialised.
    _apikey: str = field(default="", repr=False,
                         metadata=field_options(serialize="omit"))

    def _stored_apikey(self) -> str:
        """The key as the keychain holds it, cached. No migration, no writes.

        Kept apart from the property so the setter can ask what is already
        stored without re-entering the legacy adoption below — which calls the
        setter, and would not come back.
        """
        if self._apikey:
            return self._apikey
        from tilauscope.tilau_secrets import ai_account, get_secret  # noqa: PLC0415
        stored = get_secret(ai_account(self.client_id))
        if stored:
            self._apikey = stored
        return stored

    @property
    def apikey(self) -> str:
        stored = self._stored_apikey()
        if stored:
            return stored

        # Nothing in the keychain: this is an installation that still keeps its
        # key in the settings. Move it, once, then answer from the keychain.
        if self.apikey_encoded:
            try:
                legacy = base64.b64decode(self.apikey_encoded).decode("utf-8")
            except Exception:  # noqa: BLE001
                return ""
            if legacy:
                self.apikey = legacy
                return legacy
        return ""

    @apikey.setter
    def apikey(self, value: str) -> None:
        if value is None:
            return
        # Settings dialogs write every field back on OK, changed or not. Going
        # to the keychain for a value it already holds costs an access the
        # operating system may well ask the operator to approve.
        if value == self._stored_apikey():
            return
        from tilauscope.tilau_secrets import (  # noqa: PLC0415
            ai_account, delete_secret, set_secret,
        )
        self._apikey = value
        account = ai_account(self.client_id)
        if value:
            set_secret(account, value)
        else:
            delete_secret(account)
        # The settings copy is superseded the moment the keychain holds it.
        self.apikey_encoded = ""

    @property
    def is_configured(self) -> bool:
        """True when a key and an engine are present."""
        return bool(self.apikey) and bool(self.engine)

    @property
    def provider_name(self) -> str:
        """Human-readable provider name from client_id."""
        return _CLIENT_ID_TO_PROVIDER.get(self.client_id, self.client_id.capitalize())


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic model fetching
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_models(provider_name: str, key: str) -> list[str]:
    """Fetch available models from the provider API.

    Returns canonical 'prefix/model' strings sorted alphabetically.
    Raises on network or auth errors — callers should catch broadly.
    """
    info     = PROVIDERS.get(provider_name, {})
    endpoint = info.get("models_endpoint")
    if not endpoint:
        return []

    client_id = info.get("client_id", "")

    if client_id == "google":
        # Header, not ?key=: a query string is written to every proxy and
        # server log along the way, and an API key is a credential.
        req = urllib.request.Request(endpoint, headers={
            "x-goog-api-key": key,
        })
    elif client_id == "anthropic":
        req = urllib.request.Request(endpoint, headers={
            "x-api-key":        key,
            "anthropic-version": "2023-06-01",
        })
    else:
        req = urllib.request.Request(endpoint, headers={
            "Authorization": f"Bearer {key}",
        })

    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    prefix = "google" if client_id == "google" else client_id

    if client_id == "google":
        raw = [
            m["name"].removeprefix("models/")
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    else:
        raw = [m["id"] for m in data.get("data", [])]

    if client_id == "openai":
        raw = [m for m in raw if m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))]
    elif client_id == "mistral":
        raw = [m for m in raw if "embed" not in m.lower()]

    return [f"{prefix}/{m}" for m in sorted(raw)]


class _ModelFetcher(QObject):
    """Worker: runs _fetch_models on a background QThread."""

    models_ready = pyqtSignal(list)
    failed       = pyqtSignal(str)

    def __init__(self, provider_name: str, key: str) -> None:
        super().__init__()
        self._provider = provider_name
        self._key      = key

    def run(self) -> None:
        try:
            self.models_ready.emit(_fetch_models(self._provider, self._key))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# A model fetch outlives the dialog that asked for it. The call has a ten
# second socket timeout, so joining it on close would freeze the window for as
# long; and a QThread parented to the dialog is destroyed with it mid-call,
# which Qt reports as fatal. Both threads and workers are held here instead,
# until they announce they are done and delete themselves.
_INFLIGHT_MODEL_FETCHES: set = set()


# ─────────────────────────────────────────────────────────────────────────────
# Provider picker dialog
# ─────────────────────────────────────────────────────────────────────────────

def _theme() -> dict:
    """Late import to avoid circular dependency with tilauscope_types."""
    from tilauscope.tilauscope_types import THEME  # noqa: PLC0415
    return THEME


class AIProviderPickerDialog(QDialog):
    """
    Modal dialog to configure the AI provider, model, and API key.
    On accept(), the caller must read .result_config and persist it.

    Usage
    -----
        dlg = AIProviderPickerDialog(current_config, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            aw.tilau_aiConfig = dlg.result_config
            # persist via your settings mechanism
    """

    def __init__(self, current: TilauAIConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.result_config: TilauAIConfig = TilauAIConfig(
            client_id=current.client_id,
            apikey_encoded=current.apikey_encoded,
            engine=current.engine,
        )

        self._current = current
        self._build_ui()
        self._populate(current)
        self.resize(520, 0)

        # Return must not reach the ✕ this dialog builds first. Imported here:
        # tilauscope_types is a circular dependency for this module (see _theme).
        from tilauscope.tilauscope_types import no_enter_default  # noqa: PLC0415
        no_enter_default(self)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        T = _theme()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("aiPickerCard")
        card.setStyleSheet(f"""
            QFrame#aiPickerCard {{
                background-color: {T['BG']};
                border: 2px solid {T['ACCENT']};
                border-radius: 18px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                color: {T['TEXT']};
                }}
            QComboBox, QLineEdit {{
                background: {T['SURFACE']};
                color: {T['TEXT']};
                border: 1px solid {T['BORDER']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                combobox-popup: 0;
            }}
            QComboBox:focus, QLineEdit:focus {{
                border-color: {T['ACCENT']};
            }}
            QComboBox QAbstractItemView {{
                background: {T['SURFACE']};
                color: {T['TEXT']};
                selection-background-color: {T['ACCENT']};
                selection-color: {T['BG']};
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 24, 28, 24)
        cl.setSpacing(14)
        outer.addWidget(card)

        # Header
        hdr = QHBoxLayout()
        title = QLabel(
            QApplication.translate("tilauscope_ai", "AI PROVIDER").upper()
        )
        title.setStyleSheet(
            f"color: {T['ACCENT']}; font-size: 15px; font-weight: 900; letter-spacing: 2px;"
        )
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
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

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {T['BORDER']}; border: none;")
        cl.addWidget(sep)

        # Provider selector
        cl.addWidget(self._row_label(
            QApplication.translate("tilauscope_ai", "Provider")
        ))
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(list(PROVIDERS.keys()))
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        cl.addWidget(self._provider_combo)

        # Model/engine field  (free-text + Browse button)
        model_hdr = QHBoxLayout()
        model_hdr.addWidget(self._row_label(
            QApplication.translate("tilauscope_ai", "Model")
        ))
        model_hdr.addStretch()
        self._browse_btn = QPushButton(
            QApplication.translate("tilauscope_ai", "↗ Browse")
        )
        self._browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['ACCENT']};
                border: none; font-size: 11px;
                padding: 0;
            }}
            QPushButton:hover  {{ color: {T['LAVENDER']}; }}
            QPushButton:disabled {{ color: {T['SUBTEXT']}; }}
        """)
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        model_hdr.addWidget(self._browse_btn)
        cl.addLayout(model_hdr)

        self._engine_edit = QLineEdit()
        self._engine_edit.setPlaceholderText("provider/model-name")
        cl.addWidget(self._engine_edit)

        # API key field
        key_lbl_row = QHBoxLayout()
        key_lbl_row.addWidget(self._row_label(
            QApplication.translate("tilauscope_ai", "API Key")
        ))
        key_lbl_row.addStretch()
        self._key_link_btn = QPushButton(
            QApplication.translate("tilauscope_ai", "↗ Get a key")
        )
        self._key_link_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T['ACCENT']};
                border: none;
                font-size: 11px;
                padding: 0;
            }}
            QPushButton:hover {{ color: {T['LAVENDER']}; }}
        """)
        self._key_link_btn.clicked.connect(self._open_key_url)
        key_lbl_row.addWidget(self._key_link_btn)
        cl.addLayout(key_lbl_row)

        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("…")
        cl.addWidget(self._key_edit)

        # Show/hide key toggle
        show_row = QHBoxLayout()
        show_row.addStretch()
        self._show_key_btn = QPushButton(
            QApplication.translate("tilauscope_ai", "Show key")
        )
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['SUBTEXT']};
                border: none; font-size: 11px; }}
            QPushButton:checked {{ color: {T['ACCENT']}; }}
        """)
        self._show_key_btn.toggled.connect(self._toggle_key_visibility)
        show_row.addWidget(self._show_key_btn)
        cl.addLayout(show_row)

        # Status hint
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color: {T['SUBTEXT']}; font-size: 11px; font-style: italic;"
        )
        cl.addWidget(self._status_lbl)

        # Buttons
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {T['BORDER']}; border: none;")
        cl.addWidget(sep2)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        cancel_btn = QPushButton(QApplication.translate("tilauscope_ai", "Cancel"))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T['SURFACE']}; color: {T['TEXT']};
                border: 1px solid {T['BORDER']}; border-radius: 8px;
                padding: 8px 20px; font-weight: bold;
            }}
            QPushButton:hover {{ border-color: {T['ACCENT']}; color: {T['ACCENT']}; }}
        """)
        cancel_btn.clicked.connect(self.reject)

        self._save_btn = QPushButton(
            QApplication.translate("tilauscope_ai", "⬥  Save")
        )
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T['ACCENT']}; color: {T['BG']};
                border: none; border-radius: 8px;
                padding: 8px 24px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {T['LAVENDER']}; }}
            QPushButton:disabled {{ background: {T['BORDER']}; color: {T['SUBTEXT']}; }}
        """)
        self._save_btn.clicked.connect(self._on_save)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self._save_btn)
        cl.addLayout(btn_row)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty('variant', 'eyebrow')
        return lbl

    def _populate(self, cfg: TilauAIConfig) -> None:
        """Fill widgets from an existing TilauAIConfig (prefix-tolerant)."""
        eng = normalize_engine(cfg.engine)
        provider = _CLIENT_ID_TO_PROVIDER.get(cfg.client_id)
        if provider is None:  # fall back: which provider owns this engine?
            for name, info in PROVIDERS.items():
                if any(normalize_engine(e) == eng for e in info.get("engines", [])):
                    provider = name
                    break
        if provider is None:
            provider = list(PROVIDERS.keys())[0]
        idx = self._provider_combo.findText(provider)
        self._provider_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._on_provider_changed(self._provider_combo.currentText())  # sets default engine
        if eng:
            self._engine_edit.setText(eng)  # override default with saved value
        if cfg.apikey:
            self._key_edit.setText(cfg.apikey)
        self._refresh_status()

    def _on_provider_changed(self, provider_name: str) -> None:
        info    = PROVIDERS.get(provider_name, {})
        engines = info.get("engines", [])
        default = engines[0] if engines else ""
        if hasattr(self, "_engine_edit"):
            self._engine_edit.setPlaceholderText(default or "provider/model-name")
            self._engine_edit.setText(default)
        if hasattr(self, "_key_edit"):
            self._key_edit.setPlaceholderText(info.get("key_hint", "…"))
            # Keys are held per provider, so show the one belonging to the
            # provider now selected — not the one still in the box, which
            # would otherwise be saved under someone else's name.
            from tilauscope.tilau_secrets import ai_account, get_secret  # noqa: PLC0415
            client_id = info.get("client_id", provider_name.lower())
            self._key_edit.setText(get_secret(ai_account(client_id)))
        self._refresh_status()

    def _open_key_url(self) -> None:
        from PyQt6.QtGui import QDesktopServices  # noqa: PLC0415
        from PyQt6.QtCore import QUrl              # noqa: PLC0415
        provider = self._provider_combo.currentText()
        url = PROVIDERS.get(provider, {}).get("key_url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _toggle_key_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._key_edit.setEchoMode(mode)

    def _refresh_status(self) -> None:
        T = _theme()
        key = self._key_edit.text().strip() if hasattr(self, "_key_edit") else ""
        if key:
            self._status_lbl.setText(
                QApplication.translate("tilauscope_ai", "✓ Key entered")
            )
            self._status_lbl.setStyleSheet(
                f"color: {T['SUCCESS']}; font-size: 11px; font-style: italic;"
            )
        else:
            self._status_lbl.setText(
                QApplication.translate("tilauscope_ai", "No API key – AI features disabled")
            )
            self._status_lbl.setStyleSheet(
                f"color: {T['WARNING']}; font-size: 11px; font-style: italic;"
            )

    # ── Save ─────────────────────────────────────────────────────────────────

    # ── Browse / dynamic model fetch ─────────────────────────────────────────

    def _on_browse_clicked(self) -> None:
        provider = self._provider_combo.currentText()
        key      = self._key_edit.text().strip()
        info     = PROVIDERS.get(provider, {})

        if not key or not info.get("models_endpoint"):
            self._show_model_menu(info.get("engines", []))
            return

        self._browse_btn.setText("…")
        self._browse_btn.setEnabled(False)

        thread  = QThread()          # no parent: it must survive this dialog
        fetcher = _ModelFetcher(provider, key)
        fetcher.moveToThread(thread)
        self._fetch_thread = thread
        self._fetcher      = fetcher
        entry = (thread, fetcher)
        _INFLIGHT_MODEL_FETCHES.add(entry)

        thread.started.connect(fetcher.run)
        fetcher.models_ready.connect(self._on_models_ready)
        fetcher.failed.connect(self._on_models_error)
        fetcher.models_ready.connect(thread.quit)
        fetcher.failed.connect(thread.quit)
        thread.finished.connect(lambda e=entry: _INFLIGHT_MODEL_FETCHES.discard(e))
        thread.finished.connect(fetcher.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def done(self, result: int) -> None:  # noqa: N802 (Qt override)
        """Let a fetch still in flight finish on its own, talking to nobody.

        Only the result slots are cut: the thread keeps its own references and
        deletes itself when the call returns.
        """
        fetcher = getattr(self, '_fetcher', None)
        if fetcher is not None:
            for sig, slot in ((fetcher.models_ready, self._on_models_ready),
                              (fetcher.failed, self._on_models_error)):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self._fetcher = None
        self._fetch_thread = None
        super().done(result)

    def _on_models_ready(self, models: list) -> None:
        self._browse_btn.setText(QApplication.translate("tilauscope_ai", "↗ Browse"))
        self._browse_btn.setEnabled(True)
        provider = self._provider_combo.currentText()
        self._show_model_menu(
            models or PROVIDERS.get(provider, {}).get("engines", [])
        )

    def _on_models_error(self, error: str) -> None:
        self._browse_btn.setText(QApplication.translate("tilauscope_ai", "↗ Browse"))
        self._browse_btn.setEnabled(True)
        _log.warning("Model fetch failed: %s – showing defaults", error)
        provider = self._provider_combo.currentText()
        self._show_model_menu(PROVIDERS.get(provider, {}).get("engines", []))

    def _show_model_menu(self, models: list[str]) -> None:
        if not models:
            return
        T    = _theme()
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {T['SURFACE']}; color: {T['TEXT']};
                border: 1px solid {T['BORDER']}; border-radius: 6px;
                font-size: 12px;
                padding: 4px;
            }}
            QMenu::item {{ padding: 6px 16px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {T['ACCENT']}; color: {T['BG']}; }}
        """)
        for model in models:
            action = QAction(model, menu)
            action.triggered.connect(
                lambda _checked, m=model: self._engine_edit.setText(m)
            )
            menu.addAction(action)
        menu.exec(self._browse_btn.mapToGlobal(
            self._browse_btn.rect().bottomLeft()
        ))

    # ── Save ─────────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        provider = self._provider_combo.currentText()
        info     = PROVIDERS.get(provider, {})
        engine   = normalize_engine(self._engine_edit.text().strip())
        key      = self._key_edit.text().strip()

        cfg = TilauAIConfig(
            client_id=info.get("client_id", provider.lower()),
            engine=engine,
        )
        cfg.apikey = key  # encodes to apikey_encoded

        self.result_config = cfg
        self.accept()