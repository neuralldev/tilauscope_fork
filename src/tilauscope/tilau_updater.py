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

"""
TilauScope Auto-Updater
=======================
Non-blocking background update checker. Looks for a newer installer among the
assets attached to the public tilauscope_fork GitHub Releases.

Usage (from Artisan startup, e.g. in ApplicationWindow.__init__ or post-init hook):

    from tilauscope.tilau_updater import TilauUpdater
    self._tilau_updater = TilauUpdater(self)
    self._tilau_updater.start()

The check runs in a QThread so it never blocks the UI.
If a newer build is found, a styled dialog appears offering to download & install.
On confirmation the installer/dmg is saved to the OS Downloads folder,
launched, and the main application is asked to close.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Final

import requests
from tilauscope.tilauscope_types import _IS_MACOS, _IS_WINDOWS

from PyQt6.QtCore import (
    QObject,
    QStandardPaths,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
    Qt,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from packaging import version as pkg_version
    _HAS_PACKAGING = True
except ImportError:
    _HAS_PACKAGING = False

_log: Final[logging.Logger] = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_GITHUB_RELEASES_API: Final[str] = (
    "https://api.github.com/repos/neuralldev/tilauscope_fork/releases?per_page=100"
)
_GITHUB_RELEASES_URL: Final[str] = (
    "https://github.com/neuralldev/tilauscope_fork/releases"
)

_THEME: Final[dict] = {
    "BG":       "#1E1E2E",
    "SURFACE":  "#181825",
    "TEXT":     "#CDD6F4",
    "SUBTEXT":  "#94A3B8",
    "ACCENT":   "#89B4FA",
    "BORDER":   "#313244",
    "SUCCESS":  "#A6E3A1",
    "CRITICAL": "#F38BA8",
    "WARNING":  "#E0903B",
    "HOVER":    "#B9C098",
}

# ──────────────────────────────────────────────────────────────────────────────
# Version helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_version(v: str):
    """Return a comparable version object. Falls back to tuple comparison."""
    if _HAS_PACKAGING:
        try:
            return pkg_version.parse(v)
        except Exception:
            pass
    # Manual fallback: compare tuples of ints
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts)


def _is_newer(remote_v: str, remote_b: int, local_v: str, local_b: int) -> bool:
    rv = _parse_version(remote_v)
    lv = _parse_version(local_v)
    if rv > lv:
        return True
    if rv == lv and remote_b > local_b:
        return True
    return False


def _get_local_version() -> tuple[str, int]:
    """Import version/build from artisanlib and return (version_str, build_int)."""
    try:
        from artisanlib.__init__ import __build__, __version__  # type: ignore[import]
        build_str = str(__build__).strip('"\'')
        return str(__version__), int(build_str)
    except Exception as exc:
        _log.warning(f"[TilauUpdater] Could not read local version: {exc}")
        return "0.0.0", 0


# ──────────────────────────────────────────────────────────────────────────────
# Background worker
# ──────────────────────────────────────────────────────────────────────────────

class _UpdateCheckWorker(QObject):
    """Runs in a QThread. Emits update_found or no_update when done."""

    update_found = pyqtSignal(str, int, str, str)   # (remote_version, remote_build, download_url, filename)
    no_update    = pyqtSignal()
    check_error  = pyqtSignal(str)

    def __init__(self, local_v: str, local_b: int) -> None:
        super().__init__()
        self._local_v = local_v
        self._local_b = local_b

    # ── GitHub releases (tilauscope_fork) ───────────────────────────────────────

    # Installers are attached to the release as assets. The tag itself carries
    # only the version (one release per public version, two assets); the build
    # number stays in the asset name so support can trace an exact binary.
    #   macOS   : tilauscope-4.1.0-build41.dmg
    #   Windows : tilauscope-4.1.0-build41-setup.exe
    _ASSET_RE: Final = re.compile(
        r"^tilauscope-(\d+\.\d+\.\d+)-build(\d+)-setup\.exe$" if _IS_WINDOWS
        else r"^tilauscope-(\d+\.\d+\.\d+)-build(\d+)\.dmg$"
    )

    def _check_github(self) -> dict | None:
        """Scan tilauscope_fork's releases for the newest installer asset
        matching this platform. Returns a result dict, or None if nothing could
        be found (network error, rate-limited, no matching asset)."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (TilauScope updater)",
                "Accept": "application/vnd.github+json",
            }
            resp = requests.get(_GITHUB_RELEASES_API, headers=headers, timeout=10)
            resp.raise_for_status()
            releases = resp.json()
        except Exception as exc:
            _log.debug(f"[TilauUpdater] GitHub releases fetch failed: {exc}")
            return None

        best: dict | None = None
        for release in releases:
            if release.get("draft") or release.get("prerelease"):
                continue
            for asset in release.get("assets") or ():
                name = asset.get("name") or ""
                url = asset.get("browser_download_url")
                m = self._ASSET_RE.match(name)
                if not m or not url:
                    continue
                v_str, b = m.group(1), int(m.group(2))
                if best is None or _is_newer(v_str, b, best["version"], best["build"]):
                    best = {"version": v_str, "build": b, "dl_url": url, "filename": name}

        if best is None:
            _log.debug("[TilauUpdater] No matching installer asset on GitHub.")
        return best

    # ── main run ─────────────────────────────────────────────────────────────

    @pyqtSlot()
    def run(self) -> None:
        try:
            best = self._check_github()
            if best is None:
                _log.info("[TilauUpdater] No update found on GitHub.")
                self.no_update.emit()
                return

            if not _is_newer(best["version"], best["build"], self._local_v, self._local_b):
                _log.info("[TilauUpdater] Already on latest build.")
                self.no_update.emit()
                return

            _log.info(
                f"[TilauUpdater] Update found: {best['version']} build {best['build']}  →  {best['dl_url']}"
            )
            self.update_found.emit(best["version"], best["build"], best["dl_url"], best["filename"])

        except Exception as exc:
            _log.warning(f"[TilauUpdater] Check failed: {exc}")
            self.check_error.emit(str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Download worker
# ──────────────────────────────────────────────────────────────────────────────

# Below this size a 200 response is almost certainly an error/quota page, not an
# installer, even when it is not recognisable HTML.
_MIN_INSTALLER_BYTES: Final[int] = 200_000


class _DownloadError(Exception):
    """User-presentable download failure carrying an already-localized message."""


class _DownloadWorker(QObject):
    """Downloads the installer file in the background, reporting progress."""

    progress   = pyqtSignal(int)          # 0-100
    finished   = pyqtSignal(str)          # local file path
    dl_error   = pyqtSignal(str)

    def __init__(self, url: str, dest_path: str) -> None:
        super().__init__()
        self._url  = url
        self._dest = dest_path

    @pyqtSlot()
    def run(self) -> None:
        thread = QThread.currentThread()
        try:
            session = requests.Session()
            headers = {"User-Agent": "Mozilla/5.0 (TilauScope updater)"}

            # GitHub redirects asset URLs to its object storage; requests
            # follows that transparently.
            # timeout=(connect, read): fail fast on connect, tolerate slow body.
            resp = session.get(self._url, headers=headers, stream=True, timeout=(10, 60))
            resp.raise_for_status()

            # A release asset is always binary. Getting HTML back means the
            # asset is gone or an error page was served — streaming it would
            # just save that page under the installer's name.
            if "text/html" in resp.headers.get("content-type", "").lower():
                raise _DownloadError(QApplication.translate(
                    "tilauscope_beancave",
                    "The server returned a web page instead of the installer "
                    "(the release asset may have been removed)."))

            # Stream the actual file to disk
            total = int(resp.headers.get("content-length", 0) or 0)
            downloaded = 0
            interrupted = False
            try:
                with open(self._dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if thread is not None and thread.isInterruptionRequested():
                            interrupted = True
                            break
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(min(100, int(downloaded * 100 / total)))
            except OSError as exc:
                raise _DownloadError(QApplication.translate(
                    "tilauscope_beancave",
                    "Could not write the update to disk (disk full or permission "
                    "denied):\n{0}").format(exc)) from exc

            if interrupted:
                self._safe_unlink()
                _log.info("[TilauUpdater] Download interrupted by user.")
                return  # controller owns the cancel UI; emit nothing

            # Presence + integrity gate before declaring success.
            self._verify_download(downloaded, total)

            self.finished.emit(self._dest)

        except _DownloadError as exc:
            self._safe_unlink()
            _log.error(f"[TilauUpdater] Download rejected: {exc}")
            self.dl_error.emit(str(exc))
        except requests.exceptions.Timeout:
            self._safe_unlink()
            self.dl_error.emit(QApplication.translate(
                "tilauscope_beancave",
                "The connection timed out while downloading the update."))
        except requests.exceptions.ConnectionError:
            self._safe_unlink()
            self.dl_error.emit(QApplication.translate(
                "tilauscope_beancave",
                "Network connection lost during the download."))
        except requests.exceptions.HTTPError as exc:
            self._safe_unlink()
            code = exc.response.status_code if exc.response is not None else "?"
            self.dl_error.emit(QApplication.translate(
                "tilauscope_beancave",
                "The server refused the download (HTTP {0}).").format(code))
        except Exception as exc:
            self._safe_unlink()
            _log.error(f"[TilauUpdater] Download error: {exc}")
            self.dl_error.emit(str(exc))

    # ── integrity helpers ─────────────────────────────────────────────────────

    def _safe_unlink(self) -> None:
        """Remove the (possibly partial) destination file, ignoring errors."""
        try:
            p = Path(self._dest)
            if p.exists():
                p.unlink()
        except OSError:
            pass

    def _verify_download(self, downloaded: int, total: int) -> None:
        """Raise _DownloadError if the file is absent, empty, truncated, an HTML
        error page, implausibly small, or not a valid Windows installer."""
        p = Path(self._dest)
        if not p.exists():
            raise _DownloadError(QApplication.translate(
                "tilauscope_beancave",
                "The downloaded file is missing after the transfer."))
        size = p.stat().st_size
        if size == 0:
            raise _DownloadError(QApplication.translate(
                "tilauscope_beancave", "The downloaded file is empty."))
        if total and downloaded != total:
            raise _DownloadError(QApplication.translate(
                "tilauscope_beancave",
                "The download is incomplete ({0} of {1} bytes).").format(downloaded, total))

        try:
            with open(p, "rb") as f:
                head = f.read(512)
        except OSError as exc:
            raise _DownloadError(QApplication.translate(
                "tilauscope_beancave",
                "The downloaded file could not be read back:\n{0}").format(exc)) from exc

        low = head.lower()
        if b"<html" in low or b"<!doctype" in low:
            raise _DownloadError(QApplication.translate(
                "tilauscope_beancave",
                "Received a web page instead of the installer. The download link "
                "could not be resolved."))
        if size < _MIN_INSTALLER_BYTES:
            raise _DownloadError(QApplication.translate(
                "tilauscope_beancave",
                "The downloaded file is too small to be a valid installer "
                "({0} bytes).").format(size))
        # Windows PE installers start with "MZ"; DMG headers are not stable so
        # macOS relies on the size + non-HTML checks above.
        if _IS_WINDOWS and not head.startswith(b"MZ"):
            raise _DownloadError(QApplication.translate(
                "tilauscope_beancave",
                "The downloaded file is not a valid Windows installer."))


# ──────────────────────────────────────────────────────────────────────────────
# Styled dialogs
# ──────────────────────────────────────────────────────────────────────────────

_BASE_STYLE = f"""
    QDialog, QWidget {{
        background-color: {_THEME['BG']};
        color: {_THEME['TEXT']};
        font-family: 'JetBrains Mono', monospace;
    }}
    QLabel {{
        color: {_THEME['TEXT']};
        background: transparent;
        font-family: 'JetBrains Mono', monospace;
    }}
    QPushButton {{
        background-color: #3b4252;
        border: 1px solid {_THEME['BORDER']};
        border-radius: 6px;
        padding: 8px 20px;
        color: {_THEME['TEXT']};
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {_THEME['HOVER']};
        border: 1px solid {_THEME['ACCENT']};
        color: {_THEME['BG']};
    }}
    QPushButton:disabled {{
        background-color: {_THEME['BG']};
        color: #6272a4;
        border: 1px solid {_THEME['SURFACE']};
    }}
    QProgressBar {{
        background: {_THEME['SURFACE']};
        border-radius: 4px;
        border: none;
        height: 8px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: {_THEME['ACCENT']};
        border-radius: 4px;
    }}
"""


class _UpdateAvailableDialog(QDialog):
    """Frameless, themed dialog that announces a new build."""

    def __init__(
        self,
        remote_version: str,
        remote_build:   int,
        local_version:  str,
        local_build:    int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(_BASE_STYLE)
        self._build_ui(remote_version, remote_build, local_version, local_build)

    def _build_ui(
        self,
        remote_version: str,
        remote_build:   int,
        local_version:  str,
        local_build:    int,
    ) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        container = QFrame()
        container.setObjectName("UpdContainer")
        container.setStyleSheet(f"""
            #UpdContainer {{
                background-color: {_THEME['BG']};
                border: 2px solid {_THEME['ACCENT']};
                border-radius: 14px;
            }}
        """)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(28, 22, 28, 22)
        inner.setSpacing(14)
        outer.addWidget(container)

        # ── Title ──────────────────────────────────────────────────────────
        title = QLabel("🚀  UPDATE AVAILABLE")
        title.setStyleSheet(
            f"color: {_THEME['ACCENT']}; font-size: 18px; font-weight: 800; letter-spacing: 1px;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)

        # ── Version info ───────────────────────────────────────────────────
        info_frame = QFrame()
        info_frame.setStyleSheet(
            f"background: {_THEME['SURFACE']}; border-radius: 8px; border: 1px solid {_THEME['BORDER']};"
        )
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(16, 12, 16, 12)
        info_layout.setSpacing(6)

        def _row(label: str, value: str, color: str = _THEME["TEXT"]) -> QLabel:
            lbl = QLabel(f"<b style='color:{_THEME['SUBTEXT']};'>{label}</b>  "
                         f"<span style='color:{color};'>{value}</span>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            return lbl

        info_layout.addWidget(_row("Current :", f"v{local_version}  build {local_build}"))
        info_layout.addWidget(
            _row("New     :", f"v{remote_version}  build {remote_build}", _THEME["SUCCESS"])
        )
        inner.addWidget(info_frame)

        # ── Body text ──────────────────────────────────────────────────────
        body = QLabel(QApplication.translate("tilauscope_beancave",
            "A new version of <b>TilauScope</b> is available.\n"
            "Download now to get the latest features and fixes."
        ))
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet(f"color: {_THEME['SUBTEXT']}; font-size: 13px;")
        inner.addWidget(body)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_download = QPushButton(QApplication.translate("tilauscope_beancave","⬇  Download & Install"))
        self.btn_download.setStyleSheet(
            f"background-color: {_THEME['ACCENT']}; color: {_THEME['BG']}; "
            f"font-weight: bold; border: none; border-radius: 6px; padding: 10px 22px;"
        )
        self.btn_download.clicked.connect(self.accept)

        btn_later = QPushButton(QApplication.translate("tilauscope_beancave","Later"))
        btn_later.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_later)
        btn_layout.addWidget(self.btn_download)
        inner.addLayout(btn_layout)

        self.setMinimumWidth(460)

    # Allow dragging the frameless dialog
    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)


class _DownloadProgressDialog(QDialog):
    """Frameless, themed progress dialog shown while downloading."""

    cancelled = pyqtSignal()

    def __init__(self, filename: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(_BASE_STYLE)
        self._build_ui(filename)

    def _build_ui(self, filename: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        container = QFrame()
        container.setObjectName("DlContainer")
        container.setStyleSheet(f"""
            #DlContainer {{
                background-color: {_THEME['BG']};
                border: 2px solid {_THEME['ACCENT']};
                border-radius: 14px;
            }}
        """)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(28, 24, 28, 20)
        inner.setSpacing(16)
        outer.addWidget(container)

        title = QLabel(QApplication.translate("tilauscope_beancave","⬇  DOWNLOADING UPDATE"))
        title.setStyleSheet(
            f"color: {_THEME['ACCENT']}; font-size: 16px; font-weight: 800; letter-spacing: 1px;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)

        self._file_label = QLabel(filename)
        self._file_label.setStyleSheet(f"color: {_THEME['SUBTEXT']}; font-size: 11px;")
        self._file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_label.setWordWrap(True)
        inner.addWidget(self._file_label)

        self.pbar = QProgressBar()
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setFixedHeight(10)
        self.pbar.setTextVisible(False)
        inner.addWidget(self.pbar)

        self._pct_label = QLabel("0 %")
        self._pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pct_label.setStyleSheet(f"color: {_THEME['TEXT']}; font-size: 13px;")
        inner.addWidget(self._pct_label)

        btn_cancel = QPushButton(QApplication.translate("tilauscope_beancave","Cancel"))
        btn_cancel.setFixedWidth(120)
        btn_cancel.clicked.connect(self._on_cancel)
        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        cancel_row.addWidget(btn_cancel)
        cancel_row.addStretch()
        inner.addLayout(cancel_row)

        self.setMinimumWidth(420)
        self._cancelled = False

    @pyqtSlot(int)
    def set_progress(self, pct: int) -> None:
        self.pbar.setValue(pct)
        self._pct_label.setText(f"{pct} %")

    def _on_cancel(self) -> None:
        self._cancelled = True
        self.cancelled.emit()
        self.reject()

    @property
    def was_cancelled(self) -> bool:
        return self._cancelled


class _InstallReadyDialog(QDialog):
    """Shown after a successful download – asks to launch and quit."""

    def __init__(self, file_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(_BASE_STYLE)
        self._build_ui(Path(file_path).name)

    def _build_ui(self, filename: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        container = QFrame()
        container.setObjectName("InstContainer")
        container.setStyleSheet(f"""
            #InstContainer {{
                background-color: {_THEME['BG']};
                border: 2px solid {_THEME['SUCCESS']};
                border-radius: 14px;
            }}
        """)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(28, 24, 28, 22)
        inner.setSpacing(14)
        outer.addWidget(container)

        title = QLabel(QApplication.translate("tilauscope_beancave","✅  DOWNLOAD COMPLETE"))
        title.setStyleSheet(
            f"color: {_THEME['SUCCESS']}; font-size: 17px; font-weight: 800; letter-spacing: 1px;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)

        body = QLabel(QApplication.translate("tilauscope_beancave",
            "<b>{0}</b><br/><br/>"
            "Click <b>Install Now</b> to launch the installer and close TilauScope.<br/>"
            "Or <b>Later</b> to install manually from your Downloads folder."
        ).format(filename))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet(f"color: {_THEME['SUBTEXT']}; font-size: 13px; line-height: 1.5;")
        inner.addWidget(body)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_install = QPushButton(QApplication.translate("tilauscope_beancave","🛠  Install Now & Quit"))
        self.btn_install.setStyleSheet(
            f"background-color: {_THEME['SUCCESS']}; color: {_THEME['BG']}; "
            f"font-weight: bold; border: none; border-radius: 6px; padding: 10px 22px;"
        )
        self.btn_install.clicked.connect(self.accept)

        btn_later = QPushButton(QApplication.translate("tilauscope_beancave","Later"))
        btn_later.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_later)
        btn_layout.addWidget(self.btn_install)
        inner.addLayout(btn_layout)

        self.setMinimumWidth(460)


# ──────────────────────────────────────────────────────────────────────────────
# Public class
# ──────────────────────────────────────────────────────────────────────────────

class TilauUpdater(QObject):
    """
    Non-blocking startup update checker for TilauScope.

    Parameters
    ----------
    parent_window
        The main ApplicationWindow (or any QWidget).  Used as dialog parent
        and to call ``close()`` after a successful install launch.
    delay_ms : int
        Milliseconds to wait after construction before starting the check.
        Default 5 000 ms so the main window can finish drawing first.
    """

    def __init__(self, parent_window: QWidget, delay_ms: int = 5000) -> None:
        super().__init__(parent_window)
        self._parent = parent_window
        self._delay_ms = delay_ms

        # Threads / workers kept alive as instance variables
        self._check_thread: QThread | None = None
        self._check_worker: _UpdateCheckWorker | None = None
        self._dl_thread:    QThread | None = None
        self._dl_worker:    _DownloadWorker | None = None

        self._dl_dialog:    _DownloadProgressDialog | None = None
        self._dest_path:    str = ""
        self._cancelled:    bool = False

    # ── public API ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Schedule the update check after *delay_ms*."""
        QTimer.singleShot(self._delay_ms, self._run_check)
        _log.debug("[TilauUpdater] Scheduled update check.")

    # ── step 1 : background version check ────────────────────────────────────

    @pyqtSlot()
    def _run_check(self) -> None:
        local_v, local_b = _get_local_version()
        _log.info(f"[TilauUpdater] Local version: {local_v}  build: {local_b}")

        self._check_worker = _UpdateCheckWorker(local_v, local_b)
        self._check_thread = QThread(self)
        self._check_worker.moveToThread(self._check_thread)

        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.update_found.connect(self._on_update_found)
        self._check_worker.no_update.connect(self._cleanup_check_thread)
        self._check_worker.check_error.connect(self._on_check_error)

        # Clean-up wiring — use lambda to discard args for thread.quit()
        self._check_worker.update_found.connect(lambda *_: self._check_thread.quit())
        self._check_worker.no_update.connect(self._check_thread.quit)
        self._check_worker.check_error.connect(lambda *_: self._check_thread.quit())
        self._check_thread.finished.connect(self._check_worker.deleteLater)

        self._check_thread.start()

    @pyqtSlot()
    def _cleanup_check_thread(self) -> None:
        _log.debug("[TilauUpdater] No update found or error – done.")

    @pyqtSlot(str)
    def _on_check_error(self, msg: str) -> None:
        _log.warning(f"[TilauUpdater] Check error: {msg}")

    # ── step 2 : offer the update ─────────────────────────────────────────────

    @pyqtSlot(str, int, str, str)
    def _on_update_found(self, remote_v: str, remote_b: int, dl_url: str, filename: str) -> None:
        local_v, local_b = _get_local_version()

        dlg = _UpdateAvailableDialog(remote_v, remote_b, local_v, local_b, self._parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            _log.info("[TilauUpdater] User deferred update.")
            return

        self._start_download(remote_v, remote_b, dl_url, filename)

    # ── step 3 : download ─────────────────────────────────────────────────────

    def _start_download(self, remote_v: str, remote_b: int, dl_url: str, filename: str) -> None:
        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        self._dest_path = str(Path(downloads_dir) / filename)

        self._dl_dialog = _DownloadProgressDialog(self._dest_path, self._parent)
        self._dl_dialog.cancelled.connect(self._on_download_cancelled)
        self._dl_dialog.show()

        self._dl_worker = _DownloadWorker(dl_url, self._dest_path)
        self._dl_thread = QThread(self)
        self._dl_worker.moveToThread(self._dl_thread)

        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_worker.progress.connect(self._dl_dialog.set_progress)
        self._dl_worker.finished.connect(self._on_download_finished)
        self._dl_worker.dl_error.connect(self._on_download_error)

        self._dl_worker.finished.connect(self._dl_thread.quit)
        self._dl_worker.dl_error.connect(self._dl_thread.quit)
        self._dl_thread.finished.connect(self._dl_worker.deleteLater)

        self._dl_thread.start()

    @pyqtSlot()
    def _on_download_cancelled(self) -> None:
        self._cancelled = True
        if self._dl_dialog:
            self._dl_dialog.hide()
            self._dl_dialog.deleteLater()
            self._dl_dialog = None
        if self._dl_thread and self._dl_thread.isRunning():
            self._dl_thread.requestInterruption()
            self._dl_thread.quit()
        _log.info("[TilauUpdater] Download cancelled by user.")
        # The worker removes its own partial file once it observes the
        # interruption, so we avoid unlinking it here mid-write (race).

    @pyqtSlot(str)
    def _on_download_finished(self, file_path: str) -> None:
        if self._dl_dialog:
            self._dl_dialog.hide()
            self._dl_dialog.deleteLater()
            self._dl_dialog = None

        if self._cancelled:
            return

        # Final presence guard: the file could have been moved or removed
        # between the worker's verification and this slot running.
        p = Path(file_path)
        try:
            ok = p.exists() and p.stat().st_size > 0
        except OSError:
            ok = False
        if not ok:
            self._on_download_error(QApplication.translate(
                "tilauscope_beancave",
                "The downloaded file is no longer available."))
            return

        _log.info(f"[TilauUpdater] Download complete: {file_path} ({p.stat().st_size} bytes)")
        self._offer_install(file_path)

    @pyqtSlot(str)
    def _on_download_error(self, msg: str) -> None:
        if self._dl_dialog:
            self._dl_dialog.hide()
            self._dl_dialog.deleteLater()
            self._dl_dialog = None

        if self._cancelled:
            return  # user already cancelled – don't show a spurious error

        _log.error(f"[TilauUpdater] Download failed: {msg}")

        from PyQt6.QtWidgets import QMessageBox
        err_box = QMessageBox(self._parent)
        err_box.setWindowTitle(QApplication.translate("tilauscope_beancave","Download Failed"))
        err_box.setIcon(QMessageBox.Icon.Critical)
        err_box.setText(
            QApplication.translate("tilauscope_beancave",
                "The update could not be downloaded.\n\n{0}\n\n"
                "Please download manually from:\n{1}"
            ).format(msg, _GITHUB_RELEASES_URL)
        )
        err_box.exec()

    # ── step 4 : install ──────────────────────────────────────────────────────

    def _offer_install(self, file_path: str) -> None:
        dlg = _InstallReadyDialog(file_path, self._parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            _log.info("[TilauUpdater] User chose to install later.")
            return

        self._launch_installer(file_path)

    def _launch_installer(self, file_path: str) -> None:
        """Launch the downloaded installer/dmg and request app shutdown."""

        # Presence guard: the file may have been removed between download and
        # the user confirming the install dialog.
        p = Path(file_path)
        try:
            present = p.exists() and p.stat().st_size > 0
        except OSError:
            present = False
        if not present:
            _log.error("[TilauUpdater] Installer file missing at launch time.")
            from PyQt6.QtWidgets import QMessageBox
            from tilauscope.tilauscope_types import show_styled_message
            show_styled_message(
                self._parent,
                QApplication.translate("tilauscope_beancave", "Installer Not Found"),
                QApplication.translate("tilauscope_beancave",
                    "The downloaded installer could not be found:\n{0}\n\n"
                    "Please download it again.").format(file_path),
                QMessageBox.Icon.Warning,
            )
            return

        try:
            if _IS_WINDOWS:
                # Run the NSIS/Inno installer; it is a detached process
                os.startfile(file_path)  # type: ignore[attr-defined]
            elif _IS_MACOS:
                # Mount the dmg; user drags the app to /Applications themselves
                subprocess.Popen(["open", file_path])
            else:
                # Linux: try xdg-open as generic fallback
                subprocess.Popen(["xdg-open", file_path])

            _log.info(f"[TilauUpdater] Launched installer: {file_path}")
        except Exception as exc:
            _log.error(f"[TilauUpdater] Failed to launch installer: {exc}")
            from PyQt6.QtWidgets import QMessageBox
            from tilauscope.tilauscope_types import show_styled_message
            show_styled_message(
                self._parent,
                QApplication.translate("tilauscope_beancave","Launch Failed"),
                QApplication.translate("tilauscope_beancave","Could not open the installer automatically.\n\nPlease open it manually:\n{0}").format(file_path),
                QMessageBox.Icon.Warning,
                )
            return  # Don't quit if we couldn't even open the file

        # Ask the main application window to close
        QTimer.singleShot(800, self._request_app_close)

    @pyqtSlot()
    def _request_app_close(self) -> None:
        _log.info("[TilauUpdater] Requesting application shutdown for update install.")
        try:
            # Prefer calling the parent window's close() – Artisan will handle
            # saving profiles / settings in its own closeEvent.
            self._parent.close()
        except Exception:
            pass
        # Hard fallback: quit the Qt event loop
        QTimer.singleShot(2_000, QApplication.instance().quit)