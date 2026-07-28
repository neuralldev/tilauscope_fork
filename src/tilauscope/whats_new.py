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

# courtesy to Difluid team which provided the API structure of packets exchanged through BLE
# and V005 firmware update though the app (this is mandatory for this coupling to work)

# AUTHOR
# TiLau 2026

"""
WhatsNewDlg
===========
Fetches the user-facing ``whatsnew.md``, extracts the latest version section,
and displays it in a styled, scrollable "What's New" dialog. Tried in order:
the public ``tilauscope_fork`` GitHub repository first, then the legacy
Google Drive share as a backup if GitHub is unreachable.

``whatsnew.md`` is a small, hand-written, end-user changelog (one
``## TilauScope <version>`` block per version, newest first) — distinct from the
developer log ``wiki/ReleaseHistory.md``.

The dialog re-appears whenever the displayed content changes: a QSettings flag
``tilauscope/whats_new_shown_hash`` stores a hash of the last section shown, and
the dialog is suppressed while the fetched content hashes to the same value.

Usage (from TilauScope.__init__, after init_ui):

    from tilauscope.whats_new import maybe_show_whats_new
    QTimer.singleShot(800, lambda: maybe_show_whats_new(self, self))
"""

from __future__ import annotations

import logging
import re
from typing import Final

import requests

from PyQt6.QtCore import (
    QObject,
    QSettings,
    QThread,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from tilauscope.tilauscope_types import _IS_MACOS, _IS_WINDOWS

_log: Final[logging.Logger] = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Raw GitHub URL for the user-facing whatsnew.md, published on every CI build
# to the public tilauscope_fork repo. "HEAD" always resolves to that repo's
# default branch, so this keeps working even if the branch is renamed.
_RELEASE_NOTES_URL_GITHUB: Final[str] = (
    "https://raw.githubusercontent.com/neuralldev/tilauscope_fork/HEAD/whatsnew.md"
)

_RELEASE_NOTES_URLS: Final[tuple[str, ...]] = (
    _RELEASE_NOTES_URL_GITHUB,
)

# QSettings key that stores the highest whatsnew VERSION already shown to the
# user (e.g. "4.0.4"). Version-based so that jumping several releases at once
# shows the accumulated notes of every skipped version, once — the old
# content-hash key only ever compared the single latest block.
_SETTINGS_KEY: Final[str] = "tilauscope/whats_new_last_version"
# Legacy content-hash key (pre-4.1) — read once for migration only.
_LEGACY_HASH_KEY: Final[str] = "tilauscope/whats_new_shown_hash"

_THEME: Final[dict] = {
    "BG":      "#1E1E2E",
    "SURFACE": "#181825",
    "TEXT":    "#CDD6F4",
    "SUBTEXT": "#94A3B8",
    "ACCENT":  "#89B4FA",
    "BORDER":  "#313244",
    "SUCCESS": "#A6E3A1",
    "WARN":    "#FAB387",
    "HEAD1":   "#CBA6F7",   # h1 / version title colour
    "HEAD2":   "#89DCEB",   # h2 / section colour
    "BULLET":  "#A6E3A1",   # bullet accent
}


# ── Build / version helpers ───────────────────────────────────────────────────

def _get_local_build() -> int:
    """Return the current build integer (0 if not determinable)."""
    try:
        from artisanlib.__init__ import __build__  # type: ignore[import]
        return int(str(__build__).strip("\"'"))
    except Exception:
        return 0


def _get_local_version() -> str:
    try:
        from artisanlib.__init__ import __version__  # type: ignore[import]
        return str(__version__)
    except Exception:
        return "0.0.0"


# ── Background fetch worker ───────────────────────────────────────────────────

class _FetchWorker(QObject):
    """Fetches ReleaseHistory.md in a QThread and emits the raw markdown."""

    fetched = pyqtSignal(str)   # markdown text
    failed  = pyqtSignal(str)   # error message

    @pyqtSlot()
    def run(self) -> None:
        headers = {"User-Agent": "Mozilla/5.0 (TilauScope whats-new)"}
        last_exc: Exception | None = None
        for url in _RELEASE_NOTES_URLS:
            try:
                resp = requests.get(url, headers=headers, timeout=8)
                resp.raise_for_status()
                self.fetched.emit(resp.text)
                return
            except Exception as exc:
                _log.debug(f"[WhatsNew] Fetch failed for {url}: {exc}")
                last_exc = exc
        if isinstance(last_exc, requests.exceptions.ConnectionError):
            self.failed.emit("offline")
        else:
            self.failed.emit(str(last_exc))


# ── Markdown → Qt widget renderer ────────────────────────────────────────────

def _parse_version(text: str) -> "tuple[int, ...] | None":
    """Extract a dotted numeric version ("4.0.4" → (4, 0, 4)) from a string.
    None when no version-looking token is present."""
    m = re.search(r"(\d+(?:\.\d+)+)", text or "")
    if not m:
        return None
    try:
        return tuple(int(p) for p in m.group(1).split("."))
    except ValueError:
        return None


def _vkey(v: "tuple[int, ...]") -> tuple:
    """Comparable, length-normalised key (so (4,1) == (4,1,0))."""
    return v + (0,) * (4 - len(v)) if len(v) < 4 else v


# A whatsnew VERSION block starts at a top-level "# TilauScope <version>"
# heading (H1). The "## " headings inside are per-version RUBRICS
# (☕ Roasting Assistant, 📊 BeanCave, …), NOT version separators — the old
# code split on "## " and returned a single rubric instead of a version.
_VERSION_HEADING_RE: Final = re.compile(r"(?m)^#\s+\S.*?(\d+(?:\.\d+)+).*$")


def _iter_version_sections(markdown: str) -> "list[tuple[tuple[int, ...], str]]":
    """Split whatsnew.md into (version_tuple, block_text) per H1 version
    heading, newest first (file order). Preamble before the first heading is
    ignored. Empty list when no version heading is found."""
    heads = list(_VERSION_HEADING_RE.finditer(markdown))
    out: list[tuple[tuple[int, ...], str]] = []
    for i, m in enumerate(heads):
        v = _parse_version(m.group(1))
        if v is None:
            continue
        start = m.start()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(markdown)
        out.append((v, markdown[start:end].strip()))
    return out


def _sections_to_show(markdown: str, last_seen: "tuple[int, ...] | None",
                      installed: "tuple[int, ...] | None"
                      ) -> "tuple[str, tuple[int, ...] | None]":
    """Concatenate every version block newer than `last_seen` and not newer
    than the `installed` build — so skipping several releases shows all their
    notes at once. Returns (markdown_to_show, highest_version_shown).

    First run (last_seen is None): only the newest applicable block, to avoid
    dumping the whole history. Falls back to the raw document when the file has
    no parseable version heading."""
    sections = _iter_version_sections(markdown)
    if not sections:
        return (markdown.strip(), installed)
    applicable = [(v, txt) for (v, txt) in sections
                  if installed is None or _vkey(v) <= _vkey(installed)]
    if not applicable:
        return ("", None)
    if last_seen is None:
        applicable = applicable[:1]   # newest only on first run
    else:
        applicable = [(v, txt) for (v, txt) in applicable if _vkey(v) > _vkey(last_seen)]
    if not applicable:
        return ("", None)
    highest = max((v for v, _ in applicable), key=_vkey)
    return ("\n\n".join(txt for _, txt in applicable), highest)


def _md_to_widgets(markdown: str, parent: QWidget) -> list[QWidget]:
    """
    Minimal Markdown → QLabel list.
    Handles: # h1, ## h2, ### h3, - bullet, blank lines, plain text.
    No external dependency needed.
    """
    widgets: list[QWidget] = []

    def _make_label(text: str, style: str, wrap: bool = True) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(wrap)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setStyleSheet(style)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return lbl

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()

        if not line:
            spacer = QLabel("")
            spacer.setFixedHeight(6)
            widgets.append(spacer)
            continue

        # Headings
        if line.startswith("### "):
            text = line[4:].strip()
            widgets.append(_make_label(
                text,
                f"color:{_THEME['HEAD2']}; font-size:13px; font-weight:700;"
                f"font-family:'JetBrains Mono',monospace; margin-top:6px;",
            ))
        elif line.startswith("## "):
            text = line[3:].strip()
            widgets.append(_make_label(
                text,
                f"color:{_THEME['HEAD1']}; font-size:16px; font-weight:800;"
                f"font-family:'JetBrains Mono',monospace; margin-top:10px;",
            ))
        elif line.startswith("# "):
            text = line[2:].strip()
            widgets.append(_make_label(
                text,
                f"color:{_THEME['ACCENT']}; font-size:20px; font-weight:900;"
                f"font-family:'JetBrains Mono',monospace; letter-spacing:1px;",
            ))

        # Bullet items  –  *, -, +
        elif re.match(r"^[\*\-\+]\s+", line):
            text = re.sub(r"^[\*\-\+]\s+", "", line)
            # Inline bold **text**
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            # Inline code `text`
            text = re.sub(
                r"`([^`]+)`",
                rf"<span style='background:{_THEME['SURFACE']};color:{_THEME['WARN']};"
                r"font-family:monospace;border-radius:3px;padding:1px 4px;'>\1</span>",
                text,
            )
            row = QHBoxLayout()
            row.setContentsMargins(10, 0, 0, 0)
            row.setSpacing(6)

            dot = QLabel("▸")
            dot.setFixedWidth(14)
            dot.setStyleSheet(
                f"color:{_THEME['BULLET']}; font-size:12px; font-weight:bold;"
            )
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)

            content = _make_label(
                text,
                f"color:{_THEME['TEXT']}; font-size:12px;"
                f"font-family:'JetBrains Mono',monospace; line-height:1.5;",
            )

            row.addWidget(dot)
            row.addWidget(content, 1)

            wrapper = QWidget()
            wrapper.setLayout(row)
            wrapper.setStyleSheet("background:transparent;")
            widgets.append(wrapper)

        # Horizontal rule
        elif re.match(r"^-{3,}$", line) or re.match(r"^={3,}$", line):
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color:{_THEME['BORDER']}; margin:4px 0;")
            widgets.append(sep)

        # Normal paragraph
        else:
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            text = re.sub(
                r"`([^`]+)`",
                rf"<span style='background:{_THEME['SURFACE']};color:{_THEME['WARN']};"
                r"font-family:monospace;border-radius:3px;padding:1px 4px;'>\1</span>",
                text,
            )
            widgets.append(_make_label(
                text,
                f"color:{_THEME['SUBTEXT']}; font-size:12px;"
                f"font-family:'JetBrains Mono',monospace; line-height:1.5;",
            ))

    return widgets


# ── Dialog ────────────────────────────────────────────────────────────────────

class WhatsNewDlg(QDialog):
    """
    Fancy "What's New in TilauScope" splash dialog.

    Shows the whatsnew.md section for the current build,
    fetched asynchronously from GitHub (tilauscope_fork).
    """

    def __init__(self, version: str, build: int, parent: QWidget | None = None) -> None:
        # Keep parent for macOS WA_TranslucentBackground compatibility.
        # We use parent.destroyed signal (below) to trigger our closeEvent
        # before Qt's implicit child destruction can bypass it.
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)   # non-blocking — user can dismiss at any time
        self._version  = version
        self._build    = build
        self._drag_pos = None
        self._destroyed = False   # guard: prevents cross-thread slot access after close
        self._parent_ref = parent     # kept for centring once content has loaded
        self._pending_version: "tuple[int, ...] | None" = None  # highest version shown → persisted on dismiss
        self._silent = False          # True when dismissed without ever being shown

        self._build_skeleton()
        self._start_fetch()

        # macOS: FramelessWindowHint + WA_TranslucentBackground requires this
        if _IS_MACOS:
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        # When the app main window closes, close ourselves cleanly so closeEvent runs.
        if parent is not None:
            parent.destroyed.connect(self._on_parent_destroyed)

    # ── UI skeleton (shown immediately, content filled after fetch) ───────────

    def _build_skeleton(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        self._card = QFrame()
        self._card.setObjectName("WhatsNewCard")
        self._card.setStyleSheet(f"""
            #WhatsNewCard {{
                background-color: {_THEME['BG']};
                border: 2px solid {_THEME['ACCENT']};
                border-radius: 16px;
            }}
        """)
        outer.addWidget(self._card)

        root = QVBoxLayout(self._card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────────
        header_bar = QFrame()
        header_bar.setObjectName("HeaderBar")
        header_bar.setFixedHeight(52)
        header_bar.setStyleSheet(f"""
            #HeaderBar {{
                background: {_THEME['SURFACE']};
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
                border-bottom: 1px solid {_THEME['BORDER']};
            }}
        """)
        h_row = QHBoxLayout(header_bar)
        h_row.setContentsMargins(20, 0, 14, 0)
        h_row.setSpacing(10)

        icon_lbl = QLabel("🫘")
        icon_lbl.setStyleSheet("font-size:22px; background:transparent;")

        title_lbl = QLabel(
            QApplication.translate("WhatsNew", "What's New in TilauScope")
        )
        title_lbl.setStyleSheet(
            f"color:{_THEME['ACCENT']}; font-family:'JetBrains Mono',monospace;"
            f"font-size:15px; font-weight:800; letter-spacing:1px; background:transparent;"
        )

        build_lbl = QLabel(f"v{self._version}  ·  build {self._build}")
        build_lbl.setStyleSheet(
            f"color:{_THEME['SUBTEXT']}; font-family:'JetBrains Mono',monospace;"
            f"font-size:11px; background:transparent;"
        )

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_THEME['SUBTEXT']};
                border: none;
                font-size: 14px;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {_THEME['BORDER']};
                color: {_THEME['TEXT']};
            }}
        """)
        close_btn.clicked.connect(self._on_close)

        h_row.addWidget(icon_lbl)
        h_row.addWidget(title_lbl)
        h_row.addStretch()
        h_row.addWidget(build_lbl)
        h_row.addSpacing(8)
        h_row.addWidget(close_btn)
        root.addWidget(header_bar)

        # ── Scroll area (content goes here) ──────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: {_THEME['SURFACE']};
                width: 6px;
                border-radius: 3px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {_THEME['BORDER']};
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {_THEME['ACCENT']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        # Loading placeholder
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background:transparent;")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(24, 20, 24, 20)
        self._content_layout.setSpacing(4)

        self._loading_lbl = QLabel(
            QApplication.translate("WhatsNew", "⏳  Fetching release notes…")
        )
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet(
            f"color:{_THEME['SUBTEXT']}; font-size:13px;"
            f"font-family:'JetBrains Mono',monospace;"
        )
        self._content_layout.addStretch()
        self._content_layout.addWidget(self._loading_lbl)
        self._content_layout.addStretch()

        self._scroll.setWidget(self._content_widget)
        root.addWidget(self._scroll, 1)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = QFrame()
        footer.setFixedHeight(54)
        footer.setObjectName("FooterBar")
        footer.setStyleSheet(f"""
            #FooterBar {{
                background: {_THEME['SURFACE']};
                border-top: 1px solid {_THEME['BORDER']};
                border-bottom-left-radius: 14px;
                border-bottom-right-radius: 14px;
            }}
        """)
        f_row = QHBoxLayout(footer)
        f_row.setContentsMargins(20, 0, 20, 0)

        self._dont_show_cb = QCheckBox(
            QApplication.translate("WhatsNew", "Don't show again")
        )
        self._dont_show_cb.setChecked(True)
        self._dont_show_cb.setStyleSheet(f"""
            QCheckBox {{
                color: {_THEME['SUBTEXT']};
                font-size: 12px;
                font-family: 'JetBrains Mono', monospace;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid {_THEME['BORDER']};
                background: {_THEME['SURFACE']};
            }}
            QCheckBox::indicator:unchecked:hover {{
                border-color: {_THEME['ACCENT']};
            }}
            QCheckBox::indicator:checked {{
                background: {_THEME['ACCENT']};
                border-color: {_THEME['ACCENT']};
                image: url(check_mark_path); /* Optionnel : ou utilisez un caractère ✓ */
            }}
            /* Style simple pour le check interne si vous n'avez pas d'image */
            QCheckBox::indicator:checked {{
                background-color: {_THEME['ACCENT']};
            }}
            """)

        ok_btn = QPushButton(QApplication.translate("WhatsNew", "Close  ✕"))
        ok_btn.setFixedSize(110, 32)
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_THEME['ACCENT']};
                color: {_THEME['BG']};
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
                font-family: 'JetBrains Mono', monospace;
            }}
            QPushButton:hover {{
                background: #B9C4F8;
            }}
            QPushButton:pressed {{
                background: {_THEME['SURFACE']};
                color: {_THEME['ACCENT']};
                border: 1px solid {_THEME['ACCENT']};
            }}
        """)
        ok_btn.clicked.connect(self._on_close)

        f_row.addWidget(  self._dont_show_cb )
        f_row.addStretch(1)
        f_row.addWidget(ok_btn)
        root.addWidget(footer)

        # Size — wide enough for comfortable reading, shorter on smaller screens
        self.setMinimumSize(600, 480)
        self.resize(680, 560)

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def _start_fetch(self) -> None:
        self._worker = _FetchWorker()
        self._thread = QThread(self)    # self as parent keeps the thread alive as long as dialog exists
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.fetched.connect(self._on_fetched)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.fetched.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        # NOTE: do NOT connect finished→thread.deleteLater when thread has a parent;
        # the parent (self) owns the lifetime — deleteLater would double-free.

        self._thread.start()

    @pyqtSlot(str)
    def _on_fetched(self, markdown: str) -> None:
        if self._destroyed:
            return
        last_seen = self._read_last_seen_version()
        installed = _parse_version(self._version)
        section, highest = _sections_to_show(markdown, last_seen, installed)

        # Nothing newer than what the user already saw (up to their build).
        if not section:
            _log.debug("[WhatsNew] No unseen version notes — skipping.")
            self._dismiss_silently()
            return

        self._pending_version = highest
        self._populate_content(section)
        self._center_and_show()

    @staticmethod
    def _read_last_seen_version() -> "tuple[int, ...] | None":
        """Highest whatsnew version already shown. Migrates silently from the
        legacy content-hash key: if only the old key is set, treat the current
        installed build's notes as unseen (return None) so the user gets the
        accumulated notes once under the new scheme."""
        settings = QSettings()
        raw = settings.value(_SETTINGS_KEY, "")
        v = _parse_version(str(raw)) if raw else None
        return v

    @pyqtSlot(str)
    def _on_fetch_failed(self, reason: str) -> None:
        # Nothing has been shown yet — stay silent rather than popping an error
        # dialog on every offline launch.
        if self._destroyed:
            return
        _log.debug(f"[WhatsNew] Fetch failed ({reason}) — staying silent.")
        self._dismiss_silently()

    # ── Content population ────────────────────────────────────────────────────

    def _populate_content(self, markdown: str) -> None:
        """Replace the loading placeholder with rendered markdown widgets."""
        # Clear the layout
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        widgets = _md_to_widgets(markdown, self._content_widget)
        for w in widgets:
            self._content_layout.addWidget(w)
        self._content_layout.addStretch(1)

    # ── Show / silent dismiss ─────────────────────────────────────────────────

    def _center_and_show(self) -> None:
        """Centre over the parent window and show the dialog."""
        parent = self._parent_ref
        if parent is not None and parent.isVisible():
            geo = parent.geometry()
            self.move(
                geo.x() + (geo.width()  - self.width())  // 2,
                geo.y() + (geo.height() - self.height()) // 2,
            )
        self.show()

    def _dismiss_silently(self) -> None:
        """Tear down without ever showing the dialog (content unchanged or fetch failed)."""
        self._destroyed = True
        self._silent = True
        self._teardown_thread()
        self.deleteLater()

    # ── Parent destruction handler ────────────────────────────────────────────

    @pyqtSlot()
    def _on_parent_destroyed(self) -> None:
        """Called when the main window is destroyed — close ourselves cleanly."""
        self.close()

    # ── Close handling ────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        # _save_shown_flag() sera aussi appelé via closeEvent —
        # c'est sans danger car settings.setValue est idempotent.
        self.close()

    # ── Close event override ──────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """Intercept ALL close paths (✕ btn, Alt+F4, Esc) to honour the checkbox."""
        self._destroyed = True   # block pending cross-thread signals
        self._save_shown_flag()
        self._teardown_thread()
        super().closeEvent(event)

    def _teardown_thread(self) -> None:
        """Disconnect worker signals and stop the fetch thread cleanly."""
        # Disconnect worker→dialog signals BEFORE quit/wait so no slot fires
        # on partially-destroyed widgets while we're waiting for the thread.
        worker = getattr(self, "_worker", None)
        if worker is not None:
            try:
                worker.fetched.disconnect(self._on_fetched)
                worker.failed.disconnect(self._on_fetch_failed)
            except (RuntimeError, TypeError):
                pass  # already disconnected or worker C++ object gone
        thread = getattr(self, "_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(2000)

    def _save_shown_flag(self) -> None:
        """Persist the highest version shown (so it — and every version below —
        won't pop up again) when the 'don't show again' box is checked."""
        if self._silent or self._pending_version is None:
            return  # nothing was shown — don't record a flag
        cb = getattr(self, "_dont_show_cb", None)
        if cb is not None and cb.isChecked():
            ver_str = ".".join(str(p) for p in self._pending_version)
            settings = QSettings()
            settings.setValue(_SETTINGS_KEY, ver_str)
            settings.remove(_LEGACY_HASH_KEY)   # retire l'ancienne clé de hash
            settings.sync()  # force flush to disk immediately
            _log.debug(f"[WhatsNew] Saved last-seen version {ver_str}.")

    # ── Dragging (frameless window) ───────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_pos is not None
        ):
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)


# ── Public entry point ────────────────────────────────────────────────────────

def maybe_show_whats_new(parent: QWidget, store_parent: QWidget | None = None) -> WhatsNewDlg | None:
    """
    Create the WhatsNewDlg and fetch the latest notes.

    Whether the dialog actually appears is decided once the content is in hand:
    it shows only if the latest section differs from what was last shown (see
    ``WhatsNewDlg._on_fetched``); otherwise — or if the fetch fails — it dismisses
    itself silently. The returned dialog is kept alive by its parent.

    Call this from TilauScope.__init__ (inside a QTimer.singleShot):

        from tilauscope.whats_new import maybe_show_whats_new
        QTimer.singleShot(800, lambda: maybe_show_whats_new(self, self))

    Parameters
    ----------
    parent        : dialog parent (for positioning / ownership)
    store_parent  : unused, kept for signature compatibility
    """
    _log.info("whats new enter")
    build   = _get_local_build()
    version = _get_local_version()

    # The dialog stays hidden until the fetch confirms the content is new.
    dlg = WhatsNewDlg(version, build, parent)
    return dlg