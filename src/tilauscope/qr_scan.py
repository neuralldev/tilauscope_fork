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

## TILAU ## QR scan module — BeanCave webcam scanner (spec: wiki/QR-Scan-Spec.md).
## Decodes TilauScope label QR codes (roast / bean / sack) from the webcam and
## returns a normalized (kind, id) result. The camera runs ONLY while the dialog
## is open (operator requirement). Decoding is throttled (~5 Hz) so the preview
## stays fluid; everything here is user-action driven — never on the 1 Hz path.

import os
import re
import sys
import logging
import tempfile
from pathlib import Path
from typing import Final, Optional
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSizePolicy,
)

from tilauscope.tilauscope_types import THEME

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Optional heavy imports — the app must keep working (button shows an
# explanatory message) if the packaged build misses one of them.
try:
    import numpy as _np
    import zxingcpp as _zxing
    _HAS_DECODER = True
except Exception as _e:  # pragma: no cover
    _log.warning(f"QR decoder unavailable: {_e}")
    _HAS_DECODER = False

try:
    from PyQt6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_CAMERA_STACK = True
except Exception as _e:  # pragma: no cover
    _log.warning(f"QtMultimedia unavailable: {_e}")
    _HAS_CAMERA_STACK = False

# Qt >= 6.5 permission API: on macOS the camera silently refuses to start (and
# the system prompt never shows) unless the app explicitly requests access.
try:
    from PyQt6.QtCore import QCameraPermission
    _HAS_PERMISSION_API = True
except Exception:  # pragma: no cover
    _HAS_PERMISSION_API = False


def _camera_settings_hint() -> str:
    """Where to re-enable camera access, per platform (shown in error texts)."""
    if sys.platform == 'darwin':
        return QApplication.translate(
            "tilauscope_webclient",
            "System Settings → Privacy & Security → Camera")
    if sys.platform.startswith('win'):
        return QApplication.translate(
            "tilauscope_webclient",
            "Settings → Privacy & security → Camera")
    return QApplication.translate(
        "tilauscope_webclient", "your system's privacy settings")


def _macos_request_camera_access(callback) -> bool:
    """Request macOS camera access directly through AVFoundation (pyobjc).

    Qt's own permission request needs an NSCameraUsageDescription in the main
    bundle's Info.plist — absent when running from an unbundled dev python, so
    the request dies silently and the dialog hangs on "waiting". AVFoundation
    prompts regardless (TCC attributes it to the responsible app: Terminal,
    VSCode, or the packaged bundle). callback(granted: bool) fires on an
    ARBITRARY dispatch-queue thread — marshal back to Qt before touching UI.

    Returns True when the request was issued, False when this path is
    unavailable (not macOS / pyobjc missing) and the caller should fall back
    to the Qt permission API.
    """
    if sys.platform != 'darwin':
        return False
    try:
        import ctypes
        import objc
        ctypes.cdll.LoadLibrary(
            '/System/Library/Frameworks/AVFoundation.framework/AVFoundation')
        objc.registerMetaDataForSelector(
            b'AVCaptureDevice', b'requestAccessForMediaType:completionHandler:',
            {'arguments': {3: {'callable': {'retval': {'type': b'v'},
                                            'arguments': {0: {'type': b'^v'},
                                                          1: {'type': b'Z'}}},
                               'type': b'@?'}}})
        av_capture_device = objc.lookUpClass('AVCaptureDevice')
        av_capture_device.requestAccessForMediaType_completionHandler_(
            'vide', callback)  # 'vide' == AVMediaTypeVideo
        return True
    except Exception as e:  # noqa: BLE001
        _log.warning(f"AVFoundation camera request unavailable: {e}")
        return False


# ---------------------------------------------------------------------------
# Payload parsing — single source of truth for every TilauScope QR format
# ---------------------------------------------------------------------------

_HEX32 = re.compile(r'^[0-9a-fA-F]{32}$')
_UUID36 = re.compile(r'^[0-9a-fA-F-]{36}$')


def parse_tilau_qr(payload: str) -> Optional[tuple[str, str]]:
    """Normalize a scanned QR payload to ("roast"|"bean"|"sack", id).

    Accepted forms (spec §2):
      tilauscope://roast/{hex32}            legacy roast label
      tilauscope://beancave/{uuid36}        legacy green-bean label
      http(s)://tilauscope*[:port]/roast/{hex32}
      http(s)://tilauscope*[:port]/bean/{uuid36}
      http(s)://tilauscope*[:port]/sack/{id}       reserved (storage sacks)

    Returns None for anything else (third-party QR codes are never routed).
    """
    if not payload:
        return None
    payload = payload.strip()
    try:
        parsed = urlparse(payload)
    except Exception:
        return None

    if parsed.scheme == 'tilauscope':
        # urlparse maps tilauscope://roast/xxx -> netloc='roast', path='/xxx'
        kind_raw = (parsed.netloc or '').lower()
        ident = parsed.path.strip('/')
    elif parsed.scheme in ('http', 'https'):
        host = (parsed.hostname or '').lower()
        if not host.startswith('tilauscope'):
            return None
        parts = parsed.path.strip('/').split('/')
        if len(parts) != 2:
            return None
        kind_raw, ident = parts[0].lower(), parts[1]
    else:
        return None

    if kind_raw == 'roast' and _HEX32.match(ident):
        return ('roast', ident.lower())
    if kind_raw in ('bean', 'beancave') and _UUID36.match(ident):
        return ('bean', ident.lower())
    if kind_raw == 'sack' and ident:
        return ('sack', ident)
    return None


def scanner_available() -> tuple[bool, str]:
    """Whether the scan feature can run, with a user-facing reason when not."""
    if not _HAS_DECODER:
        return False, QApplication.translate(
            "tilauscope_webclient",
            "QR decoding library (zxing-cpp) is not available in this build.")
    if not _HAS_CAMERA_STACK:
        return False, QApplication.translate(
            "tilauscope_webclient",
            "Camera support (QtMultimedia) is not available in this build.")
    return True, ""


# ---------------------------------------------------------------------------
# Frame → numpy conversion (grayscale, stride-safe)
# ---------------------------------------------------------------------------

def _qimage_to_gray_array(image: 'QImage'):
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h, bpl = gray.width(), gray.height(), gray.bytesPerLine()
    if w <= 0 or h <= 0:
        return None
    ptr = gray.constBits()
    ptr.setsize(gray.sizeInBytes())
    arr = _np.frombuffer(ptr, _np.uint8).reshape(h, bpl)[:, :w]
    return arr.copy()  # detach from the QImage buffer before it is freed


# ---------------------------------------------------------------------------
# Scan dialog
# ---------------------------------------------------------------------------

class ScanQRDialog(QDialog):
    """Frameless webcam scan dialog (mockup validated 2026-07-16, spec §3.2).

    exec() returns Accepted when a TilauScope QR was decoded; the result is in
    self.result_kind ("roast"|"bean"|"sack") and self.result_id. The camera is
    started on show and unconditionally stopped on any exit path.
    """

    _DECODE_INTERVAL_S = 0.2  # ~5 Hz decode throttle (spec §6)

    # AVFoundation answers on a dispatch-queue thread; a queued signal is the
    # safe way back onto the Qt main thread.
    _native_permission_result = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_kind: str = ""
        self.result_id: str = ""
        self._camera: Optional['QCamera'] = None
        self._session: Optional['QMediaCaptureSession'] = None
        self._camera_permission = None  # kept alive across the async Qt request
        self._permission_requested = False
        self._last_bad_payload: str = ""
        self._drag_pos: Optional[QPoint] = None
        self._native_permission_result.connect(self._on_native_permission)

        # Decode pipeline: the timer pulls the LATEST camera frame (stored by
        # _on_frame, no per-frame conversion cost) and converts it via
        # QVideoFrame.toImage(). If that yields nothing usable (some backends
        # deliver GPU-texture frames whose readback fails silently), it falls
        # back to grabbing the rendered preview widget. Proven data point: the
        # frame path decodes fine with macOS Continuity Camera.
        self._latest_frame = None
        self._diag_logged = False  # one-shot pipeline diagnostics at INFO
        self._decode_timer = QTimer(self)
        self._decode_timer.setInterval(int(self._DECODE_INTERVAL_S * 1000))
        self._decode_timer.timeout.connect(self._decode_tick)

        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setStyleSheet(f"""
            QDialog {{
                background: {THEME['BG']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 10px;
            }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QComboBox {{
                background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 6px; padding: 4px 8px;
            }}
            QPushButton {{
                background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 14px;
                padding: 5px 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {THEME['BORDER']}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # -- custom title bar (frameless drag) --
        title_row = QHBoxLayout()
        title = QLabel("📷  " + QApplication.translate("tilauscope_webclient", "SCAN A QR CODE"))
        title.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 14px; font-weight: 800; "
                            f"font-family: 'JetBrains Mono';")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']}; color: {THEME['CRITICAL']};
                border-radius: 13px; border: 1px solid {THEME['CRITICAL']};
                font-weight: bold; padding: 0;
            }}
            QPushButton:hover {{ background: {THEME['CRITICAL']}; color: {THEME['BG']}; }}
        """)
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        layout.addLayout(title_row)

        # -- live preview --
        if _HAS_CAMERA_STACK:
            self._video = QVideoWidget()
            self._video.setMinimumSize(440, 330)
            self._video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(self._video, 1)
        else:
            self._video = None

        # -- status line --
        self._status = QLabel(QApplication.translate(
            "tilauscope_webclient", "Point the label QR code at the camera…"))
        self._status.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px;")
        layout.addWidget(self._status)

        # -- bottom row: camera selector + close --
        bottom = QHBoxLayout()
        self._camera_combo = QComboBox()
        self._camera_combo.setVisible(False)
        bottom.addWidget(self._camera_combo)
        bottom.addStretch()
        cancel = QPushButton(QApplication.translate("tilauscope_webclient", "Close"))
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        layout.addLayout(bottom)

        self._populate_cameras()

    # ---- camera lifecycle -------------------------------------------------

    def _populate_cameras(self) -> None:
        if not _HAS_CAMERA_STACK:
            self._set_error(QApplication.translate(
                "tilauscope_webclient", "Camera support is not available in this build."))
            return
        if not self._ensure_camera_permission():
            return  # request in flight (callback re-enters here) or denied
        devices = QMediaDevices.videoInputs()
        if not devices:
            self._set_error(QApplication.translate(
                "tilauscope_webclient", "No camera detected on this computer."))
            return
        if len(devices) > 1:
            for dev in devices:
                self._camera_combo.addItem(dev.description())
            self._camera_combo.setVisible(True)
            self._camera_combo.currentIndexChanged.connect(self._restart_camera)
        self._start_camera(devices[0])

    def _ensure_camera_permission(self) -> bool:
        """Qt >= 6.5 macOS camera authorization. True = granted (or API absent:
        older Qt / platforms where access is implicit). False = a system request
        is in flight (the callback re-runs _populate_cameras) or access is denied.
        """
        if not _HAS_PERMISSION_API:
            return True
        if getattr(self, '_native_granted', False):
            return True  # the system just said yes — don't re-enter the Qt check
        try:
            app = QApplication.instance()
            status = app.checkPermission(QCameraPermission())
            if status == Qt.PermissionStatus.Granted:
                return True
            if status == Qt.PermissionStatus.Undetermined and not self._permission_requested:
                self._permission_requested = True  # ask the system exactly once
                self._status.setText(QApplication.translate(
                    "tilauscope_webclient", "Waiting for the system camera authorization…"))
                # Native AVFoundation request first: it prompts even from an
                # unbundled dev python, where Qt's request needs an Info.plist
                # and never calls back.
                if _macos_request_camera_access(
                        lambda granted: self._native_permission_result.emit(bool(granted))):
                    return False
                # Fallback: Qt permission API. The permission object MUST stay
                # referenced until the handler runs (PyQt6 lifetime pitfall).
                self._camera_permission = QCameraPermission()
                app.requestPermission(self._camera_permission, self._on_camera_permission)
                return False
            self._show_denied()
            return False
        except Exception as e:  # noqa: BLE001
            # permission plumbing must never block the feature outright
            _log.warning(f"Camera permission check skipped: {e}")
            return True

    def _show_denied(self) -> None:
        self._set_error(QApplication.translate(
            "tilauscope_webclient",
            "Camera access denied — allow it in {0}, then reopen this window."
        ).format(_camera_settings_hint()))

    @pyqtSlot(bool)
    def _on_native_permission(self, granted: bool) -> None:
        """AVFoundation answer, already marshaled onto the Qt thread."""
        try:
            if not self.isVisible():
                return
            if granted:
                self._native_granted = True
                self._populate_cameras()
            else:
                self._show_denied()
        except RuntimeError:
            pass  # dialog already destroyed

    def _on_camera_permission(self, _permission) -> None:
        """Qt permission API answer — the dialog may have been closed meanwhile."""
        try:
            if self.isVisible():
                self._populate_cameras()
        except RuntimeError:
            pass  # dialog already destroyed

    def _restart_camera(self, index: int) -> None:
        devices = QMediaDevices.videoInputs()
        if 0 <= index < len(devices):
            self._stop_camera()
            self._start_camera(devices[index])

    def _start_camera(self, device) -> None:
        try:
            self._camera = QCamera(device)
            # Highest available resolution: a 14 mm label QR only spans a few
            # pixels per module — every pixel of definition helps the decoder.
            try:
                fmts = device.videoFormats()
                if fmts:
                    best = max(fmts, key=lambda f: f.resolution().width()
                               * f.resolution().height())
                    self._camera.setCameraFormat(best)
                    _log.info("QR scan camera: %s @ %dx%d",
                              device.description(),
                              best.resolution().width(), best.resolution().height())
            except Exception as e:  # noqa: BLE001
                _log.debug(f"camera format selection skipped: {e}")
            self._session = QMediaCaptureSession()
            self._session.setCamera(self._camera)
            self._session.setVideoOutput(self._video)
            # store the latest frame (cheap ref) — converted at timer pace only
            self._video.videoSink().videoFrameChanged.connect(self._on_frame)
            self._camera.errorOccurred.connect(self._on_camera_error)
            self._camera.start()
            self._diag_logged = False
            self._decode_timer.start()
        except Exception as e:
            _log.error(f"Camera start failed: {e}", exc_info=True)
            self._set_error(QApplication.translate(
                "tilauscope_webclient",
                "Could not start the camera (check camera access in {0})."
            ).format(_camera_settings_hint()))

    def _stop_camera(self) -> None:
        self._decode_timer.stop()
        try:
            if self._video is not None:
                try:
                    self._video.videoSink().videoFrameChanged.disconnect(self._on_frame)
                except TypeError:
                    pass  # already disconnected
            if self._camera is not None:
                self._camera.stop()
        except Exception as e:
            _log.debug(f"Camera stop: {e}")
        self._latest_frame = None
        self._camera = None
        self._session = None

    def _on_camera_error(self, _error, error_string: str) -> None:
        _log.warning(f"Camera error: {error_string}")
        self._set_error(QApplication.translate(
            "tilauscope_webclient",
            "Camera error (check camera access in {0})."
        ).format(_camera_settings_hint()))

    def _set_error(self, text: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {THEME['CRITICAL']}; font-size: 12px;")

    # ---- decoding ---------------------------------------------------------

    def _on_frame(self, frame) -> None:
        # camera-fps path: just keep a reference, zero conversion work here
        self._latest_frame = frame

    def _grab_gray(self):
        """Return (gray_array, source_tag) from the best available source:
        the latest camera frame, else the rendered preview widget."""
        # 1. camera frame (the path proven to work with Continuity Camera)
        frame = self._latest_frame
        if frame is not None and frame.isValid():
            try:
                arr = _qimage_to_gray_array(frame.toImage())
                # a readback failure shows up as an empty or uniform image
                if arr is not None and arr.size and int(arr.min()) != int(arr.max()):
                    return arr, 'frame'
            except Exception as e:  # noqa: BLE001
                _log.debug(f"frame conversion failed: {e}")
        # 2. rendered widget (what the eye actually sees)
        if self._video is not None:
            pixmap = self._video.grab()
            if not pixmap.isNull():
                try:
                    arr = _qimage_to_gray_array(pixmap.toImage())
                    if arr is not None and arr.size and int(arr.min()) != int(arr.max()):
                        return arr, 'grab'
                except Exception as e:  # noqa: BLE001
                    _log.debug(f"widget grab conversion failed: {e}")
        return None, 'none'

    def _log_diagnostics(self, arr, source: str) -> None:
        """One-shot pipeline report + optional debug snapshots
        (TILAU_QR_DEBUG=1 dumps what the decoder sees to the temp dir)."""
        if not self._diag_logged:
            self._diag_logged = True
            frame = self._latest_frame
            fmt = frame.pixelFormat() if frame is not None else 'n/a'
            shape = f"{arr.shape[1]}x{arr.shape[0]}" if arr is not None else 'none'
            rng = f"{int(arr.min())}-{int(arr.max())}" if arr is not None else '-'
            _log.info("QR scan pipeline: source=%s frame_format=%s gray=%s range=%s",
                      source, fmt, shape, rng)
        if os.environ.get('TILAU_QR_DEBUG'):
            # surface the pipeline state right in the dialog (no log digging)
            shape = f"{arr.shape[1]}x{arr.shape[0]}" if arr is not None else 'none'
            rng = f"{int(arr.min())}-{int(arr.max())}" if arr is not None else '-'
            self._status.setText(f"debug: source={source} gray={shape} range={rng}")
            if arr is not None:
                try:
                    from PIL import Image
                    p = Path(tempfile.gettempdir()) / 'tilauscope_qr_debug.png'
                    Image.fromarray(arr).save(p)
                except Exception as e:  # noqa: BLE001
                    _log.debug(f"debug snapshot failed: {e}")

    def _decode_tick(self) -> None:
        if not _HAS_DECODER:
            return
        arr, source = self._grab_gray()
        self._log_diagnostics(arr, source)
        if arr is None:
            return
        try:
            results = _zxing.read_barcodes(arr, formats=_zxing.BarcodeFormat.QRCode)
            if not results:
                # mirrored preview/camera (e.g. some front cams): retry flipped
                results = _zxing.read_barcodes(_np.fliplr(arr),
                                               formats=_zxing.BarcodeFormat.QRCode)
        except Exception as e:
            _log.debug(f"QR decode pass failed: {e}")
            return
        if not results:
            return
        payload = results[0].text or ""
        parsed = parse_tilau_qr(payload)
        if parsed is None:
            if payload != self._last_bad_payload:
                self._last_bad_payload = payload
                self._set_error(QApplication.translate(
                    "tilauscope_webclient", "QR code not recognized — not a TilauScope label."))
            return
        # Recognized: stop everything before leaving the dialog.
        self.result_kind, self.result_id = parsed
        QApplication.beep()
        self._stop_camera()
        self.accept()

    # ---- window plumbing --------------------------------------------------

    def reject(self) -> None:
        self._stop_camera()
        super().reject()

    def closeEvent(self, event) -> None:
        self._stop_camera()
        super().closeEvent(event)

    # frameless drag via the whole dialog surface (title row has no dead zone)
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)
