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

import logging
from typing import Final
from PyQt6.QtGui import (QPainter, QFont, QPageLayout, QPageSize, QPixmap, QPainterPath,
                          QPen, QBrush, QColor, QFontDatabase, QFontMetrics)
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtCore import QRectF, Qt, QMarginsF, QDate, QPointF, QSizeF
from PyQt6.QtWidgets import QApplication

from pathlib import Path
import qrcode
from PIL.ImageQt import ImageQt
from PIL import Image, ImageDraw, ImageFont
from collections.abc import Sequence
from artisanlib.atypes import ProfileData

from tilauscope.tilauscope_types import GreenBean, _IS_WINDOWS, _IS_MACOS, _IS_LINUX
from tilauscope import text_shaping

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

import sys
import os

def get_downloads_dir() -> Path:
    if _IS_WINDOWS:
        try:
            import winreg
            sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
                val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                return Path(val)
        except Exception:
            pass
        return Path.home() / "Downloads"
    elif _IS_MACOS:
        return Path.home() / "Downloads"
    else:
        os_env = os.environ.get("XDG_DOWNLOAD_DIR")
        if os_env:
            return Path(os_env)
        candidate = Path.home() / "Downloads"
        return candidate if candidate.exists() else Path.home()


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
C_ROAST_BG        = QColor("#1C1007")
C_ROAST_ACCENT    = QColor("#C47C3A")
C_ROAST_ACCENT_LT = QColor("#EFA96A")
C_ROAST_BODY_BG   = QColor("#FAF7F3")
C_ROAST_CARD_BG   = QColor("#EDE8E2")
C_ROAST_HEAD_TXT  = QColor("#FFF8F0")
C_ROAST_HEAD_SUB  = QColor(0xFF, 0xF8, 0xF0, 128)
C_ROAST_PILL_BG   = QColor(196, 124, 58, 46)
C_ROAST_PILL_BD   = QColor(196, 124, 58, 90)
C_ROAST_SPEC_LBL  = QColor("#9E9189")
C_ROAST_SPEC_VAL  = QColor("#1C1007")
C_ROAST_SEP       = QColor("#E0D9D1")
C_ROAST_LOSS      = QColor("#C47C3A")

C_GREEN_BG        = QColor("#0F2918")
C_GREEN_ACCENT    = QColor("#5DBF8A")
C_GREEN_BODY_BG   = QColor("#F5FAF7")
C_GREEN_NOTES_BG  = QColor("#E5F0EA")
C_GREEN_HEAD_TXT  = QColor("#F0FFF6")
C_GREEN_HEAD_SUB  = QColor(0xF0, 0xFF, 0xF6, 128)
C_GREEN_SPEC_LBL  = QColor("#5A8A6D")
C_GREEN_SPEC_VAL  = QColor("#0F2918")
C_GREEN_SEP       = QColor("#CADFD2")
C_GREEN_SCORE_BG  = QColor(93, 191, 138, 38)
C_GREEN_SCORE_BD  = QColor(93, 191, 138, 90)
C_GREEN_TAG_BG    = QColor(93, 191, 138, 31)
C_GREEN_TAG_BD    = QColor(93, 191, 138, 64)
C_BLEND_TAG_BG    = QColor(196, 124, 58, 31)
C_BLEND_TAG_BD    = QColor(196, 124, 58, 64)
C_BLEND_TAG_TXT   = QColor(255, 220, 170, 178)
C_BLEND_RATIO_TXT = QColor(255, 200, 130, 115)

C_TILAU_MARK       = QColor(0xFF, 0xF8, 0xF0, 90)
C_TILAU_MARK_GREEN = QColor(0xF0, 0xFF, 0xF6, 90)

_PROCESS_MAP = {
    "fully washed":      "Washed",
    "washed":            "Washed",
    "wet process":       "Washed",
    "wet":               "Washed",
    "natural":           "Natural",
    "dry process":       "Natural",
    "dry":               "Natural",
    "honey":             "Honey",
    "yellow honey":      "Honey",
    "red honey":         "Honey",
    "black honey":       "Honey",
    "pulped natural":    "Pulped nat.",
    "pulped":            "Pulped nat.",
    "anaerobic natural": "Anaerobic",
    "anaerobic washed":  "Anaerobic",
    "anaerobic":         "Anaerobic",
    "co-fermented":      "Coferment",
    "co fermented":      "Coferment",
    "cofermented":       "Coferment",
    "wet hulled":        "Wet hulled",
    "giling basah":      "Wet hulled",
    "mixed":             "Mixed",
}

def normalise_process(raw: str) -> str:
    if not raw:
        return "-"
    key = raw.strip().lower()
    for k, v in _PROCESS_MAP.items():
        if k in key:
            return v
    return raw.strip().split()[0].title()[:12]

def agtron_to_roast_name(value: int) -> str:
    if value <= 0:
        return "-"
    if value >= 95:
        return "Very light"
    if value >= 75:
        return "Light"
    if value >= 60:
        return "Medium light"
    if value >= 45:
        return "Medium"
    if value >= 35:
        return "Medium dark"
    return "Dark"

def truncate_notes(text: str, max_chars: int = 80) -> str:
    if not text:
        return "-"
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_comma = cut.rfind(",")
    if last_comma > max_chars // 2:
        return cut[:last_comma] + "..."
    return cut.rstrip() + "..."

def qr_base_url() -> str:
    # ## TILAU ## phone-scannable deep-link base (spec wiki/QR-Scan-Spec.md §2.1):
    # the record web server registers tilauscope.local via Bonjour, so printed
    # labels stay valid across machines; the port is read at PRINT time.
    try:
        from PyQt6.QtCore import QSettings
        port = QSettings().value('tilauscope/web_port', 8123, type=int)
    except Exception:
        port = 8123
    return f"http://tilauscope.local:{port}"

def generate_qr_image(payload: str, fill_color: str = "black", back_color: str = "white"):
    # ## TILAU ## shared QR builder for both label types (tilauscope:// deep links);
    # colors must keep strong dark/light contrast to stay scannable
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=5, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color=fill_color, back_color=back_color)
        return ImageQt(img.convert("RGB"))
    except Exception as e:
        _logd.warning(f"QR code generation failed: {e}")
        return None

def short_uuid(uuid: str) -> str:
    clean = uuid.replace("-", "")[:12]
    if len(clean) >= 12:
        return f"{clean[:4]}.{clean[4:8]}.{clean[8:12]}"
    return clean

def blend_ratio_line(bean: GreenBean) -> str:
    main_ratio = 100 - (bean.bean2_ratio or 0) - (bean.bean3_ratio or 0)
    parts = [f"{bean.name} {main_ratio}%"]
    if bean.bean2_ratio and bean.bean2_ratio > 0 and bean.bean2_name:
        parts.append(f"{bean.bean2_name} {bean.bean2_ratio}%")
    if bean.bean3_ratio and bean.bean3_ratio > 0 and bean.bean3_name:
        parts.append(f"{bean.bean3_name} {bean.bean3_ratio}%")
    line = " - ".join(parts)
    return line[:42] + "..." if len(line) > 42 else line


# ---------------------------------------------------------------------------
# Shared Base Mixin
# ---------------------------------------------------------------------------
class _FontMixin:
    # ## TILAU ## the whole layout below (margins, header height, font mm sizes)
    # was authored against this reference canvas — LABEL_WIDTH_MM/HEIGHT_MM is the
    # physical output size, read from the user's config (default = the reference,
    # so nothing scales for the size the layout was actually drawn for)
    REF_WIDTH_MM  = 100.0
    REF_HEIGHT_MM = 150.0
    LABEL_WIDTH_MM  = REF_WIDTH_MM
    LABEL_HEIGHT_MM = REF_HEIGHT_MM
    _FONT_SCALE = 1.2   # global font boost on top of native mm→pt conversion

    def _load_label_size(self):
        from PyQt6.QtCore import QSettings
        raw = QSettings().value("tilauscope/label_size_mm", "100x150", type=str)
        try:
            w_str, h_str = raw.lower().split("x")
            self.LABEL_WIDTH_MM  = float(w_str)
            self.LABEL_HEIGHT_MM = float(h_str)
        except (ValueError, AttributeError):
            self.LABEL_WIDTH_MM  = self.REF_WIDTH_MM
            self.LABEL_HEIGHT_MM = self.REF_HEIGHT_MM

    def _init_fonts(self):
        """Load the shared Unicode body face.

        These two sheets used to be drawn in a display face carrying 223 glyphs
        — latin only. A Cyrillic, Greek, Arabic, Hebrew or CJK bean name fell
        through to whatever Qt found on the machine, so the label came out in a
        second typeface, or blank on a system without a matching font. DejaVu
        covers all of those but CJK, which Qt substitutes on its own.
        """
        self._load_label_size()
        try:
            self.bold_family = self._load_font(text_shaping.sans_path(bold=True))
            self.reg_family  = self._load_font(text_shaping.sans_path())
        except Exception:
            _logd.error("Failed to load the label fonts, falling back to the system sans.")
            self.bold_family = self.reg_family = self._system_sans()

    def _load_font(self, path: "Path | None") -> str:
        if path is not None:
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid != -1:
                return QFontDatabase.applicationFontFamilies(fid)[0]
        return self._system_sans()

    @staticmethod
    def _system_sans() -> str:
        """A sans the running system actually has. 'Arial' does not exist on
        most Linux desktops, where Qt would silently pick something at random."""
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()

    def _dims(self, painter: QPainter):
        # ## TILAU ## page IS the label (native LABEL_WIDTH_MM x LABEL_HEIGHT_MM,
        # set on the QPrinter by _make_printer) — print at 100%, no fit-to-page
        # scaling. The layout below is authored against REF_WIDTH/HEIGHT_MM; fit
        # that reference canvas into the chosen physical size, aspect-preserving.
        dev = painter.device()
        scale = min(dev.width() / self.REF_WIDTH_MM, dev.height() / self.REF_HEIGHT_MM)
        # Geometric ratio physical-mm → reference-mm, used by pt() for font scaling
        self._scale_mm = min(
            self.LABEL_WIDTH_MM  / self.REF_WIDTH_MM,
            self.LABEL_HEIGHT_MM / self.REF_HEIGHT_MM,
        )
        W = self.p(scale, self.REF_WIDTH_MM)
        H = self.p(scale, self.REF_HEIGHT_MM)
        return W, H, scale

    def p(self, scale: float, mm: float) -> int:
        return int(mm * scale)

    def pt(self, mm: float) -> int:
        # ## TILAU ## fonts scale with the chosen physical label size × legibility boost
        scale_mm = getattr(self, "_scale_mm", 1.0)
        return max(1, round(mm * scale_mm * self._FONT_SCALE * 72.0 / 25.4))

    def _micro_label(self, painter, text, x, y, color, scale):
        painter.setFont(QFont(self.reg_family, self.pt(2.2)))
        painter.setPen(color)
        painter.drawText(int(x), int(y), text.upper())

    def _spec_value(self, painter, text, rect, color, scale, bold=True):
        w = QFont.Weight.DemiBold if bold else QFont.Weight.Normal
        painter.setFont(QFont(self.reg_family, self.pt(2.8), w))
        painter.setPen(color)
        painter.drawText(rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, text)

    def _rounded_rect(self, painter, rect, radius, fill, border=None, bw=1.0):
        painter.setPen(Qt.PenStyle.NoPen if border is None else QPen(border, bw))
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(rect, radius, radius)

    def _pill(self, painter, text, x, y, fill, border, text_color, scale) -> float:
        """Draws a pill that dynamically grows to fit text perfectly without clipping."""
        fs = self.pt(2.2)
        font = QFont(self.reg_family, fs, QFont.Weight.DemiBold)
        
        # CRUCIAL FIX: Force the painter to bind the font state BEFORE measuring,
        # and pass the painter directly to QFontMetrics so high-DPI scaling is respected.
        painter.save()
        painter.setFont(font)
        
        fm = QFontMetrics(font, painter.device()) # Pass device context explicitly
        
        # Clean text string measurements
        clean_text = text
        tw = fm.horizontalAdvance(clean_text)
        th = fm.height()
        
        # Scale dynamic breathing room paddings
        ph = self.p(scale, 3.0)  # Expanded horizontal buffer padding
        pv = self.p(scale, 1.4)  # Vertical buffer padding
        
        pill_w = tw + (2 * ph)
        pill_h = th + (2 * pv)
        
        # Define layout bounding box
        rect = QRectF(x, y, pill_w, pill_h)
        self._rounded_rect(painter, rect, self.p(scale, 1.8), fill, border, 0.8)
        
        painter.setPen(text_color)
        # Clear clip constraints to prevent edge cutting bugs
        painter.setClipping(False) 
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, clean_text)
        painter.restore()
        
        return pill_w
 
    def _hline(self, painter, x1, x2, y, color, width=0.8):
        painter.setPen(QPen(color, width))
        painter.drawLine(QPointF(x1, y), QPointF(x2, y))

    def _draw_tilau_logo(self, painter, cx: float, cy: float,
                          mark_color: QColor, scale: float,
                          size_mm: float = 12.0):
        """
        Roast-dial logo for Tilau Roaster — speedometer open at bottom.

        Geometry (Qt angle convention: 0°=right, positive=CCW, screen y-flipped
                  so negative spanAngle = clockwise visual sweep):
          - Ghost arc:  225° → 315° CW through top (270° CW sweep, gap at bottom)
          - Amber arc:  225° → ~63° CW (162° CW, ≈60% of arc, bottom-left through top)
          - Needle:     centre → tip at Qt 63° (upper-right quadrant visually)
          - Centre dot: small filled circle at cx,cy
          - Wordmark:   "TILAU" micro-caps, centred below

        cx, cy  — centre of the dial in painter coordinates
        size_mm — overall diameter in mm
        Returns dial diameter in px so callers can reserve space.
        """
        import math

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        R      = self.p(scale, size_mm / 2.0)
        # Stroke is proportionally thick — matches the bold mock style
        stroke = max(2.0, self.p(scale, 1.1))

        arc_rect = QRectF(cx - R, cy - R, 2 * R, 2 * R)

        # ── Qt arc angle constants ────────────────────────────────────────
        # start_qt = 225° → bottom-left visually (SW)
        # span_ghost = -270 → CW sweep through top, ending at 315° (SE, bottom-right)
        # span_amber = -162 → CW ~60% of arc, ending at 63° (NE, upper-right)
        start_qt   = 225
        span_ghost = -270
        span_amber = -162
        needle_qt  = (start_qt + span_amber) % 360   # = 63°

        # 1. Ghost ring (full horseshoe, mark_color @22%)
        ghost = QColor(mark_color.red(), mark_color.green(),
                       mark_color.blue(), int(mark_color.alpha() * 0.22))
        painter.setPen(QPen(ghost, stroke, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(arc_rect, start_qt * 16, span_ghost * 16)

        # 2. Amber arc (roast level, C_ROAST_ACCENT @92%)
        amber = QColor(C_ROAST_ACCENT)
        amber.setAlpha(235)
        painter.setPen(QPen(amber, stroke, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawArc(arc_rect, start_qt * 16, span_amber * 16)

        # 3. Needle — from centre to 62% radius at needle_qt angle
        # Qt angle → screen coords: x = cx + R*cos(-angle_rad), y = cy + R*sin(-angle_rad)
        nx = cx + (R * 0.62) * math.cos(math.radians(-needle_qt))
        ny = cy + (R * 0.62) * math.sin(math.radians(-needle_qt))
        needle_c = QColor(mark_color.red(), mark_color.green(),
                          mark_color.blue(), int(mark_color.alpha() * 0.92))
        painter.setPen(QPen(needle_c, max(1.0, stroke * 0.55),
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx, cy), QPointF(nx, ny))

        # 4. Centre dot (mark_color @92%)
        dot_r = max(2.0, self.p(scale, 0.9))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(needle_c))
        painter.drawEllipse(QPointF(cx, cy), dot_r, dot_r)

        # 5. "TILAU" wordmark — centred below the dial (mark_color @50%)
        fs = self.pt(1.9)
        word_c = QColor(mark_color.red(), mark_color.green(),
                        mark_color.blue(), int(mark_color.alpha() * 0.50))
        f_word = QFont(self.bold_family, fs, QFont.Weight.DemiBold)
        painter.setFont(f_word)
        painter.setPen(word_c)
        # Use device-aware QFontMetrics so measurement matches 300 DPI painter output
        fm = QFontMetrics(f_word, painter.device())
        word_w = fm.horizontalAdvance("TILAU")
        word_y = cy + R + self.p(scale, 2.2)
        # Draw into a centred rect so Qt's own alignment handles sub-pixel centering
        word_rect = QRectF(cx - word_w / 2 - self.p(scale, 2),
                           word_y - fm.ascent(),
                           word_w + self.p(scale, 4),
                           fm.height())
        painter.drawText(word_rect, Qt.AlignmentFlag.AlignHCenter, "TILAU")

        painter.restore()
        return 2 * R

    def _make_printer(self, output_path: str) -> QPrinter:
        # ## TILAU ## PDF page = native label size (100x150mm) so it prints at 100%
        # straight into the pochette, no manual scale-down and no cut-to-size step
        page_size = QPageSize(QSizeF(self.LABEL_WIDTH_MM, self.LABEL_HEIGHT_MM),
                               QPageSize.Unit.Millimeter)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(300)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(output_path)
        printer.setPageSize(page_size)
        printer.setPageLayout(QPageLayout(
            page_size,
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0)
        ))
        return printer


# ---------------------------------------------------------------------------
# Roasted Bean Label
# ---------------------------------------------------------------------------
class RoastedBeanLabelPrinter(_FontMixin):

    def __init__(self):
        self._init_fonts()

    def render(self, painter: QPainter, profile: ProfileData, bean: GreenBean):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ## TILAU ## _dims returns native label geometry (page = label, no upscale)
        lbl_w, lbl_h, scale = self._dims(painter)
        dev = painter.device()
        offset_x = (dev.width()  - lbl_w) / 2.0
        offset_y = (dev.height() - lbl_h) / 2.0

        painter.save()
        painter.translate(offset_x, offset_y)

        mg = self.p(scale, 5.5)   
        r  = self.p(scale, 4.0)   

        self._rounded_rect(painter, QRectF(0, 0, lbl_w, lbl_h), r, C_ROAST_BG)
        self._rounded_rect(painter, QRectF(0, 0, lbl_w, lbl_h), r, C_ROAST_BODY_BG)

        header_h = self._header_height(bean, scale)
        self._draw_header(painter, bean, profile, lbl_w, header_h, mg, scale)
        self._draw_body(painter, profile, bean, lbl_w, lbl_h, header_h, mg, scale)

        painter.restore()

    def _header_height(self, bean, scale) -> int:
        h = self.p(scale, 48) 
        if bean and bean.is_blend:
            h += self.p(scale, 7)
        return h

    def _draw_header(self, painter, bean, profile, W, header_h, mg, scale):
        r = self.p(scale, 4.0)
        
        # Base header background card
        self._rounded_rect(painter, QRectF(0, 0, W, header_h + r), r, C_ROAST_BG)

        # Clip decorative background rings safely
        painter.save()
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(0, 0, W, header_h + r), r, r)
        painter.setClipPath(clip_path)

        cx, cy = float(W), 0.0
        for size_mm, alpha in [(32, 10), (20, 10)]:
            painter.setPen(QPen(QColor(0xFF, 0xF8, 0xF0, alpha), self.p(scale, 5.5)))
            painter.drawEllipse(QPointF(cx, cy), self.p(scale, size_mm), self.p(scale, size_mm))
        painter.restore()

        # Branding & Typography Setup
        y = float(self.p(scale, 4.5))
        # Logo: dial centred 14mm from right edge, vertically at y + half dial size
        logo_size_mm = 9.0
        logo_cx = float(W - mg - self.p(scale, logo_size_mm / 2))
        logo_cy = float(y + self.p(scale, logo_size_mm / 2 + 1.5))
        self._draw_tilau_logo(painter, logo_cx, logo_cy, C_TILAU_MARK, scale, logo_size_mm)

        painter.setFont(QFont(self.reg_family, self.pt(2.2)))
        painter.setPen(C_ROAST_ACCENT)
        painter.drawText(mg, int(y + self.p(scale, 4)), QApplication.translate("tilauscope_label", "Roasted bean").upper())
        y += self.p(scale, 8.0)

        # Title
        name = bean.name if bean else "-"
        fs_pt = self.pt(8.5) if len(name) <= 10 else self.pt(6.5)
        painter.setFont(QFont(self.bold_family, fs_pt, QFont.Weight.Bold))
        painter.setPen(C_ROAST_HEAD_TXT)
        name_w = W - 2 * mg - self.p(scale, 10)
        
        name_rect = QRectF(mg, y, name_w, self.p(scale, 18))
        painter.drawText(name_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, name)
        y += self.p(scale, 18.0) 

        # Origin
        parts = []
        if bean and bean.country:
            parts.append(bean.country)
        if bean and bean.farm:
            parts.append(bean.farm)
        origin = " - ".join(parts)
        
        fm_orig = QFontMetrics(QFont(self.reg_family, self.pt(2.5)))
        max_orig_w = W - 2 * mg
        if fm_orig.horizontalAdvance(origin) > max_orig_w:
            while fm_orig.horizontalAdvance(origin + "...") > max_orig_w and len(origin) > 0:
                origin = origin[:-1]
            origin = origin.rstrip() + "..."
            
        painter.setFont(QFont(self.reg_family, self.pt(2.6)))
        painter.setPen(C_ROAST_HEAD_SUB)
        painter.drawText(QRectF(mg, y, W - 2 * mg, self.p(scale, 6)), Qt.AlignmentFlag.AlignLeft, origin)
        y += self.p(scale, 8.5)

        if bean and bean.is_blend:
            tag_rect = QRectF(mg, y, W - 2 * mg, self.p(scale, 5.5))
            self._rounded_rect(painter, tag_rect, self.p(scale, 1.5), C_BLEND_TAG_BG, C_BLEND_TAG_BD, 0.8)
            # ... rest of blend logic ...
            y += self.p(scale, 7)

        # ---- FLAVOR NOTES WRAPPING LOGIC ----
        # Pills show tasting descriptors: bean flavour notes first, then the
        # profile cupping notes — never the operator roasting notes.
        flavor_src = ""
        if bean:
            flavor_src = bean.flavour_notes or ""
        if not flavor_src and profile:
            flavor_src = profile.get("cuppingnotes", "") or ""

        tokens = [t.strip().rstrip(".").title() for t in flavor_src.split(",") if t.strip()]
        
        # Define an explicit, isolated tracking context
        px = float(mg)
        
        # Hard buffer line: give the right side a wider padding safety margin 
        # to force the break earlier if high-DPI calculations mismatch
        right_boundary = float(W - mg - self.p(scale, 2.0))
        
        current_y = float(y)
        
        # Instantiate font context matching the internal _pill configuration precisely
        pill_font = QFont(self.reg_family, self.pt(2.2), QFont.Weight.DemiBold)
        fm_pill = QFontMetrics(pill_font)
        
        # Row layout heights
        capsule_h = fm_pill.height() + 2 * self.p(scale, 1.4)
        row_gap = self.p(scale, 1.8)
        max_allowed_y = float(header_h) - self.p(scale, 1.0)

        for tok in tokens[:12]:
            # Predictive wrap-check using string measurement rules
            estimated_tw = fm_pill.horizontalAdvance(tok)
            estimated_pw = estimated_tw + (2 * self.p(scale, 2.5))
            
            # If the current tracking cursor + element width breaches the right wall, wrap downwards
            if (px + estimated_pw) > right_boundary:
                px = float(mg)  # Carriage return back to the margin side
                current_y += capsule_h + row_gap
                
            # Truncation fallback: prevent bleeding into the white body block area
            if (current_y + capsule_h) > max_allowed_y:
                break

            # Execute the rendering operation onto our distinct tracking layout cursor
            actual_w = self._pill(painter, tok, px, float(current_y), C_ROAST_PILL_BG, C_ROAST_PILL_BD, C_ROAST_ACCENT_LT, scale)
            
            # Use the actual pixel footprint returned by the method to increment layout cursor
            px += actual_w + self.p(scale, 2.0)

    def _draw_body(self, painter, profile, bean, W, H, header_h, mg, scale):
        r = self.p(scale, 4.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(C_ROAST_BODY_BG))
        painter.drawRect(QRectF(0, header_h, W, H - header_h))
        self._rounded_rect(painter, QRectF(0, H - 2 * r, W, 2 * r + 2), r, C_ROAST_BODY_BG)

        y = float(header_h + self.p(scale, 4))

        roast_date = str(profile["roastdate"]) if profile and profile.get("roastdate") else "-"
        self._micro_label(painter, QApplication.translate("tilauscope_label", "Roast date"), mg, y + self.p(scale, 3.5), C_ROAST_SPEC_LBL, scale)
        painter.setFont(QFont(self.reg_family, self.pt(2.8), QFont.Weight.DemiBold))
        painter.setPen(C_ROAST_SPEC_VAL)
        painter.drawText(QRectF(mg, y + self.p(scale, 5), W * 0.6, self.p(scale, 7)), Qt.AlignmentFlag.AlignLeft, roast_date)

        sca_val = bean.sca if bean and bean.sca and bean.sca > 0 else 0
        sca_str = f"{sca_val:.1f}" if sca_val > 0 else "-"
        sca_w   = self.p(scale, 14)
        sca_h   = self.p(scale, 11)
        sca_x   = W - mg - sca_w          
        sca_rect = QRectF(sca_x, y, sca_w, sca_h)
        self._rounded_rect(painter, sca_rect, self.p(scale, 2), C_ROAST_BG)
        painter.setFont(QFont(self.bold_family, self.pt(3.8), QFont.Weight.DemiBold))
        painter.setPen(C_ROAST_ACCENT_LT)
        painter.drawText(QRectF(sca_x, y, sca_w, sca_h * 0.7), Qt.AlignmentFlag.AlignCenter, sca_str)
        painter.setFont(QFont(self.reg_family, self.pt(1.8)))
        painter.setPen(QColor(C_ROAST_ACCENT_LT.red(), C_ROAST_ACCENT_LT.green(), C_ROAST_ACCENT_LT.blue(), 140))
        painter.drawText(QRectF(sca_x, y + sca_h * 0.62, sca_w, sca_h * 0.38), Qt.AlignmentFlag.AlignCenter, "SCA")

        y += self.p(scale, 13)
        self._hline(painter, mg, W - mg, y, C_ROAST_SEP)
        y += self.p(scale, 4)

        col_w  = (W - 2 * mg) / 2
        col2_x = mg + col_w
        row_h  = self.p(scale, 11)

        process = normalise_process(bean.process if bean else "")
        variety = bean.varieties if bean and bean.varieties else "-"
        fm_v = QFontMetrics(QFont(self.reg_family, self.pt(2.8), QFont.Weight.DemiBold))
        max_v_w = int(col_w - self.p(scale, 1))
        while fm_v.horizontalAdvance(variety) > max_v_w and len(variety) > 3:
            variety = variety[:-1]
        if variety != (bean.varieties if bean and bean.varieties else "-"):
            variety = variety.rstrip() + "..."

        altitude = f"{bean.altitude} m" if bean and bean.altitude and bean.altitude > 0 else "-"

        bean_color_raw = 0
        if profile:
            bean_color_raw = int(profile.get("ground_color") or profile.get("whole_color") or 0)
        roast_color = agtron_to_roast_name(bean_color_raw)

        if profile and profile.get("density") and len(profile["density"]) >= 4 and profile["density"][2] > 0:
            density = f"{int(profile['density'][0] / profile['density'][2])} {profile['density'][1]}/{profile['density'][3]}"
        else:
            density = f"{bean.density:.0f} g/L" if bean and bean.density else "-"

        crop = str(bean.crop) if bean and bean.crop and bean.crop > 0 else "-"

        specs = [
            (QApplication.translate("tilauscope_label", "Process"),    process,     mg,     col_w),
            (QApplication.translate("tilauscope_label", "Variety"),    variety,     col2_x, col_w),
            (QApplication.translate("tilauscope_label", "Altitude"),   altitude,    mg,     col_w),
            (QApplication.translate("tilauscope_label", "Roast color"),roast_color, col2_x, col_w),
            (QApplication.translate("tilauscope_label", "Density"),    density,     mg,     col_w),
            (QApplication.translate("tilauscope_label", "Crop"),       crop,        col2_x, col_w),
        ]

        for i, (lbl, val, x, w) in enumerate(specs):
            ry = y + (i // 2) * row_h
            self._micro_label(painter, lbl, x, ry + self.p(scale, 3), C_ROAST_SPEC_LBL, scale)
            self._spec_value(painter, val, QRectF(x, ry + self.p(scale, 4), w - self.p(scale, 1), self.p(scale, 7)), C_ROAST_SPEC_VAL, scale)

        y += (len(specs) // 2) * row_h + self.p(scale, 3)

        bar_h    = self.p(scale, 17)
        bar_rect = QRectF(mg, y, W - 2 * mg, bar_h)
        self._rounded_rect(painter, bar_rect, self.p(scale, 2), C_ROAST_CARD_BG)

        col_bar_w = (W - 2 * mg) / 3
        green_w = roasted_w = unit = ""
        if profile and profile.get("weight") and len(profile["weight"]) >= 3:
            green_w   = str(profile["weight"][0])
            roasted_w = str(profile["weight"][1])
            unit      = str(profile["weight"][2])
        loss = ""
        if profile and profile.get("computed") and profile["computed"].get("total_loss") is not None:
            loss = f"{profile['computed']['total_loss']} %"

        weight_rows = [
            (QApplication.translate("tilauscope_label", "Green"), f"{green_w} {unit}".strip() or "-", C_ROAST_SPEC_VAL),
            (QApplication.translate("tilauscope_label", "Roasted"), f"{roasted_w} {unit}".strip() or "-", C_ROAST_SPEC_VAL),
            (QApplication.translate("tilauscope_label", "Loss"), loss or "-", C_ROAST_LOSS),
        ]
        for i, (lbl, val, vc) in enumerate(weight_rows):
            bx = mg + i * col_bar_w + self.p(scale, 2)
            self._micro_label(painter, lbl, bx, y + self.p(scale, 5), C_ROAST_SPEC_LBL, scale)
            painter.setFont(QFont(self.bold_family, self.pt(3.5), QFont.Weight.DemiBold))
            painter.setPen(vc)
            painter.drawText(QRectF(bx, y + self.p(scale, 6.5), col_bar_w - self.p(scale, 2), self.p(scale, 9)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, val)

        # ## TILAU ## traceability footer — QR encodes the Artisan roastUUID of this profile
        roast_uuid = str(profile.get("roastUUID") or "") if profile else ""
        if roast_uuid:
            qr_size = self.p(scale, 14)
            qr_x = W - mg - qr_size
            qr_y = H - mg - qr_size
            # http URL payload: the phone's native camera opens the record page
            # served by TilauScope (spec §2.1); the desktop scanner reads it too
            qimg = generate_qr_image(f"{qr_base_url()}/roast/{roast_uuid}",
                                     fill_color=C_ROAST_BG.name(), back_color=C_ROAST_BODY_BG.name())
            if qimg is not None:
                painter.drawPixmap(int(qr_x), int(qr_y), qr_size, qr_size, QPixmap.fromImage(qimg))
            painter.setFont(QFont(self.reg_family, self.pt(1.8)))
            painter.setPen(C_ROAST_SPEC_LBL)
            txt_rect = QRectF(mg, qr_y, qr_x - mg - self.p(scale, 2), qr_size)
            painter.drawText(txt_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             "ROAST ID " + short_uuid(roast_uuid))

    def print_to_label(self, profile_data: ProfileData, bean: GreenBean, output_path: str | None = None) -> bool:
        if output_path is None:
            safe_name = (bean.name if bean and bean.name else "roast").replace(" ", "_")
            date_str  = (str(profile_data["roastdate"]).replace(" ", "_") if profile_data and profile_data.get("roastdate") else "")
            fname     = f"roast_label_{safe_name}_{date_str}.pdf".strip("_")
            output_path = str(get_downloads_dir() / fname)
        try:
            printer = self._make_printer(output_path)
            painter = QPainter(printer)
            self.render(painter, profile_data, bean)
            painter.end()
            _logd.debug(f"Roasted bean label saved to {output_path}")
            return True
        except Exception as e:
            _logd.error(f"Error generating roasted bean PDF label: {e}")
            return False


# ---------------------------------------------------------------------------
# Green Bean Label
# ---------------------------------------------------------------------------
class GreenBeanLabelPrinter(_FontMixin):

    def __init__(self, logo_path: Path | None = None):
        ## TILAU ## logo_path is accepted for call-site compatibility but no longer
        ## loaded: the label's mark is drawn from vectors by _draw_tilau_logo(), and
        ## the pixmap was decoded on every export without ever being painted.
        self._init_fonts()

    def render(self, painter: QPainter, bean: GreenBean):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ## TILAU ## _dims returns native label geometry (page = label, no upscale)
        lbl_w, lbl_h, scale = self._dims(painter)
        dev = painter.device()
        offset_x = (dev.width()  - lbl_w) / 2.0
        offset_y = (dev.height() - lbl_h) / 2.0

        painter.save()
        painter.translate(offset_x, offset_y)

        mg = self.p(scale, 5.5)
        r  = self.p(scale, 4.0)

        self._rounded_rect(painter, QRectF(0, 0, lbl_w, lbl_h), r, C_GREEN_BODY_BG)

        header_h = self._header_height(bean, scale)
        self._draw_header(painter, bean, lbl_w, header_h, mg, scale)
        self._draw_body(painter, bean, lbl_w, lbl_h, header_h, mg, scale)

        painter.restore()

    def _header_height(self, bean, scale) -> int:
        h = self.p(scale, 54)
        if bean and bean.is_blend:
            h += self.p(scale, 7)
        return h

    def _draw_header(self, painter, bean, W, header_h, mg, scale):
        r = self.p(scale, 4.0)
        self._rounded_rect(painter, QRectF(0, 0, W, header_h + r), r, C_GREEN_BG)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx = float(W / 2)
        cy = float(header_h + self.p(scale, 4))
        for rx_mm, ry_mm, alpha in [(28, 12, 20), (38, 18, 16), (48, 24, 13), (58, 30, 9), (68, 36, 6)]:
            painter.setPen(QPen(QColor(255, 255, 255, alpha), 0.9))
            painter.drawEllipse(QPointF(cx, cy), self.p(scale, rx_mm), self.p(scale, ry_mm))

        y = float(self.p(scale, 4.5))
        # Logo: dial centred 14mm from right edge
        logo_size_mm = 9.0
        logo_cx = float(W - mg - self.p(scale, logo_size_mm / 2))
        logo_cy = float(y + self.p(scale, logo_size_mm / 2 + 1.5))
        self._draw_tilau_logo(painter, logo_cx, logo_cy, C_TILAU_MARK_GREEN, scale, logo_size_mm)

        painter.setFont(QFont(self.reg_family, self.pt(2.2)))
        painter.setPen(C_GREEN_ACCENT)
        painter.drawText(mg, int(y + self.p(scale, 4)), QApplication.translate("tilauscope_label", "Green bean").upper())
        y += self.p(scale, 8)

        # ## TILAU ## title sized to match the roasted label's masthead (was 4.0/3.4/2.9mm,
        # unreadable once printed) — shrink-to-fit still guards long names
        name = bean.name if bean else "-"
        name_w = W - 2 * mg - self.p(scale, 16)
        for fs_mm in (7.5, 6.0, 4.8):
            fs = self.pt(fs_mm)
            fm_n = QFontMetrics(QFont(self.bold_family, fs, QFont.Weight.DemiBold))
            if fm_n.horizontalAdvance(name) <= name_w or fs_mm <= 4.8:
                break
        painter.setFont(QFont(self.bold_family, fs, QFont.Weight.DemiBold))
        painter.setPen(C_GREEN_HEAD_TXT)
        painter.drawText(QRectF(mg, y, name_w, self.p(scale, 20)), Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, name)
        y += self.p(scale, 18)

        parts = []
        if bean and bean.country:
            parts.append(bean.country)
        if bean and bean.farm:
            parts.append(bean.farm)
        origin = " - ".join(parts)
        fm_orig = QFontMetrics(QFont(self.reg_family, self.pt(2.5)))
        max_orig_w = W - 2 * mg
        while fm_orig.horizontalAdvance(origin) > max_orig_w and len(origin) > 4:
            origin = origin[:-1]
        if not origin.endswith(" - ".join(parts)):
            origin = origin.rstrip() + "..."
        painter.setFont(QFont(self.reg_family, self.pt(2.5)))
        painter.setPen(C_GREEN_HEAD_SUB)
        painter.drawText(QRectF(mg, y, W - 2 * mg, self.p(scale, 6)), Qt.AlignmentFlag.AlignLeft, origin)
        y += self.p(scale, 8)

        # ---- DYNAMIC ENTRY POINT FOR PILL SYSTEM ----
        if bean and bean.is_blend:
            tag_bg, tag_bd  = C_BLEND_TAG_BG, C_BLEND_TAG_BD
            tag_txt         = QApplication.translate("tilauscope_label", "Blend").upper()
            tag_color       = C_BLEND_TAG_TXT
        else:
            tag_bg, tag_bd  = C_GREEN_TAG_BG, C_GREEN_TAG_BD
            tag_txt         = QApplication.translate("tilauscope_label", "Single origin").upper()
            tag_color       = QColor(C_GREEN_ACCENT.red(), C_GREEN_ACCENT.green(), C_GREEN_ACCENT.blue(), 165)

        # Drop the broken hardcoded QRect drawing code completely!
        # Instead, utilize our self-adjusting _pill subsystem to draw without clipping boundaries:
        actual_tag_w = self._pill(painter, tag_txt, float(mg), float(y), tag_bg, tag_bd, tag_color, scale)

        if bean and bean.is_blend:
            ratio_avail = W - mg - actual_tag_w - self.p(scale, 2) - self.p(scale, 18)
            if ratio_avail > 0:
                painter.setFont(QFont(self.reg_family, self.pt(1.8)))
                painter.setPen(C_BLEND_RATIO_TXT)
                # Compute starting coordinates natively relative to the real pixel output width
                painter.drawText(QRectF(mg + actual_tag_w + self.p(scale, 2), y, ratio_avail, self.p(scale, 6)), 
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, blend_ratio_line(bean))

        # ---- SCA BADGE COMPONENT WITH SEPARATED METRIC BLOCKS ----
        if bean.sca and bean.sca > 0:
            badge_w = self.p(scale, 14.0)
            badge_h = self.p(scale, 11.0)
            badge_x = W - mg - badge_w
            badge_y = y # Sync straight into the tag base line row coordinates

            sca_rect = QRectF(badge_x, badge_y, badge_w, badge_h)
            self._rounded_rect(painter, sca_rect, self.p(scale, 2.0), C_GREEN_TAG_BG, C_GREEN_TAG_BD, 0.9)

            painter.save()
            # 1. Main Score Numeric String Entry Line
            score_str = f"{bean.sca:.1f}"
            score_font = QFont(self.bold_family, self.pt(3.8), QFont.Weight.Bold)
            painter.setFont(score_font)
            painter.setPen(C_GREEN_ACCENT)
            painter.drawText(QRectF(badge_x, badge_y, badge_w, badge_h * 0.7), Qt.AlignmentFlag.AlignCenter, score_str)

            # 2. Subtitle SCA Text Label Block (Matching roasted layout spec values)
            lbl_font = QFont(self.reg_family, self.pt(1.8), QFont.Weight.Normal)
            painter.setFont(lbl_font)
            painter.setPen(QColor(C_GREEN_ACCENT.red(), C_GREEN_ACCENT.green(), C_GREEN_ACCENT.blue(), 140))
            painter.drawText(QRectF(badge_x, badge_y + badge_h * 0.62, badge_w, badge_h * 0.38), Qt.AlignmentFlag.AlignCenter, "SCA")
            painter.restore()
            
    def _draw_body(self, painter, bean, W, H, header_h, mg, scale):
        r = self.p(scale, 4.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(C_GREEN_BODY_BG))
        painter.drawRect(QRectF(0, header_h, W, H - header_h))
        self._rounded_rect(painter, QRectF(0, H - 2 * r, W, 2 * r + 2), r, C_GREEN_BODY_BG)

        y = float(header_h + self.p(scale, 4))

        supplier = bean.supplier if bean and bean.supplier else "-"
        fm_sup = QFontMetrics(QFont(self.reg_family, self.pt(2.8), QFont.Weight.DemiBold))
        max_sup_w = int(W * 0.6 - mg)
        while fm_sup.horizontalAdvance(supplier) > max_sup_w and len(supplier) > 3:
            supplier = supplier[:-1]
        if supplier != (bean.supplier if bean and bean.supplier else "-"):
            supplier = supplier.rstrip() + "..."

        crop = str(bean.crop) if bean and bean.crop and bean.crop > 0 else "-"

        self._micro_label(painter, QApplication.translate("tilauscope_label", "Supplier"), mg, y + self.p(scale, 3.5), C_GREEN_SPEC_LBL, scale)
        painter.setFont(QFont(self.reg_family, self.pt(2.8), QFont.Weight.DemiBold))
        painter.setPen(C_GREEN_SPEC_VAL)
        painter.drawText(QRectF(mg, y + self.p(scale, 5), W * 0.6 - mg, self.p(scale, 7)), Qt.AlignmentFlag.AlignLeft, supplier)

        crop_col_w = self.p(scale, 18)   
        crop_x     = W - mg - crop_col_w
        self._micro_label(painter, QApplication.translate("tilauscope_label", "Crop"), crop_x, y + self.p(scale, 3.5), C_GREEN_SPEC_LBL, scale)
        painter.setFont(QFont(self.reg_family, self.pt(2.8), QFont.Weight.DemiBold))
        painter.setPen(C_GREEN_SPEC_VAL)
        painter.drawText(QRectF(crop_x, y + self.p(scale, 5), crop_col_w, self.p(scale, 7)), Qt.AlignmentFlag.AlignLeft, crop)

        y += self.p(scale, 14)
        self._hline(painter, mg, W - mg, y, C_GREEN_SEP)
        y += self.p(scale, 4)

        col_w  = (W - 2 * mg) / 2
        col2_x = mg + col_w
        row_h  = self.p(scale, 11)

        process = normalise_process(bean.process if bean else "")
        variety = bean.varieties if bean and bean.varieties else "-"
        fm_v    = QFontMetrics(QFont(self.reg_family, self.pt(2.8), QFont.Weight.DemiBold))
        max_v_w = int(col_w - self.p(scale, 1))
        orig_variety = variety
        while fm_v.horizontalAdvance(variety) > max_v_w and len(variety) > 3:
            variety = variety[:-1]
        if variety != orig_variety:
            variety = variety.rstrip() + "..."

        altitude  = f"{bean.altitude} masl" if bean and bean.altitude and bean.altitude > 0 else "-"
        density   = f"{bean.density:.0f} g/L" if bean and bean.density and bean.density > 0 else "-"
        moisture  = f"{bean.last_humidity:.1f} %" if bean and bean.last_humidity and bean.last_humidity > 0 else "-"
        water_act = f"{bean.water_activity:.2f} aw" if bean and bean.water_activity and bean.water_activity > 0 else "-"

        specs = [
            (QApplication.translate("tilauscope_label", "Process"),    process,   mg,     col_w),
            (QApplication.translate("tilauscope_label", "Variety"),    variety,   col2_x, col_w),
            (QApplication.translate("tilauscope_label", "Altitude"),   altitude,  mg,     col_w),
            (QApplication.translate("tilauscope_label", "Density"),    density,   col2_x, col_w),
            (QApplication.translate("tilauscope_label", "Moisture"),   moisture,  mg,     col_w),
            (QApplication.translate("tilauscope_label", "Water act."), water_act, col2_x, col_w),
        ]

        for i, (lbl, val, x, w) in enumerate(specs):
            ry = y + (i // 2) * row_h
            self._micro_label(painter, lbl, x, ry + self.p(scale, 3), C_GREEN_SPEC_LBL, scale)
            self._spec_value(painter, val, QRectF(x, ry + self.p(scale, 4), w - self.p(scale, 1), self.p(scale, 7)), C_GREEN_SPEC_VAL, scale)

        y += (len(specs) // 2) * row_h + self.p(scale, 2)

        raw_notes = truncate_notes(bean.flavour_notes if bean else "", max_chars=90)
        notes_h = self.p(scale, 18)
        self._rounded_rect(painter, QRectF(mg, y, W - 2 * mg, notes_h), self.p(scale, 2), C_GREEN_NOTES_BG)
        self._micro_label(painter, QApplication.translate("tilauscope_label", "Cupping notes"), mg + self.p(scale, 2.5), y + self.p(scale, 4), C_GREEN_SPEC_LBL, scale)
        painter.setFont(QFont(self.reg_family, self.pt(2.5), QFont.Weight.DemiBold))
        painter.setPen(C_GREEN_SPEC_VAL)
        painter.drawText(QRectF(mg + self.p(scale, 2.5), y + self.p(scale, 5.5), W - 2 * mg - self.p(scale, 5), self.p(scale, 12)), Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, raw_notes)

        y += notes_h + self.p(scale, 3)

        self._hline(painter, mg, W - mg, y, C_GREEN_SEP)
        y += self.p(scale, 3)

        qr_size = self.p(scale, 15)
        qr_x    = W - mg - qr_size
        qimg    = self._generate_qr(bean)
        if qimg is not None:
            pixmap = QPixmap.fromImage(qimg)
            painter.drawPixmap(int(qr_x), int(y), qr_size, qr_size, pixmap)

        painter.setFont(QFont(self.bold_family, self.pt(1.8), QFont.Weight.DemiBold))
        painter.setPen(C_GREEN_SPEC_LBL)
        painter.drawText(int(mg), int(y + self.p(scale, 3.5)), "TILAUSCOPE RECORD")

        uuid_str = short_uuid(bean.uuid) if bean and bean.uuid else "-"
        painter.setFont(QFont(self.reg_family, self.pt(2.5)))
        painter.setPen(C_GREEN_SPEC_VAL)
        painter.drawText(int(mg), int(y + self.p(scale, 7.5)), uuid_str)

        today = QDate.currentDate().toString("d MMM yyyy")
        painter.setFont(QFont(self.reg_family, self.pt(1.8)))
        painter.setPen(C_GREEN_SPEC_LBL)
        painter.drawText(int(mg), int(y + self.p(scale, 11)), QApplication.translate("tilauscope_label", "Stored") + f" {today}")

    def _generate_qr(self, bean: GreenBean):
        # http URL payload (spec §2.1) — phone camera opens the bean page directly
        return generate_qr_image(f"{qr_base_url()}/bean/{bean.uuid}",
                                 fill_color=C_GREEN_BG.name(), back_color=C_GREEN_BODY_BG.name())

    def generate_qr_code(self, bean: GreenBean):
        return self._generate_qr(bean)

    def print_to_label(self, bean: GreenBean, output_path: str | None = None) -> bool:
        if output_path is None:
            safe_name  = (bean.name if bean and bean.name else "bean").replace(" ", "_")
            fname      = f"Label_{safe_name}.pdf"
            output_path = str(get_downloads_dir() / fname)
        try:
            printer = self._make_printer(output_path)
            painter = QPainter(printer)
            self.render(painter, bean)
            painter.end()
            _logd.debug(f"Green bean label saved to {output_path}")
            return True
        except Exception as e:
            _logd.error(f"Error generating green bean PDF label: {e}")
            return False

# ---------------------------------------------------------------------------
# Niimbot Label Builder  (PIL/1-bit bitmap — Niimbot B21S thermal printer)
# ---------------------------------------------------------------------------
# ── Dimensions canoniques par format ────────────────────────────────────────
# Dimensions pixel natives de la Niimbot B21S à 203.2 DPI
# 80mm → 640px  |  50mm largeur → 384px (fixe, tête thermique)
# 30mm → 240px
# CRITIQUE : HEIGHT_PX doit correspondre exactement au papier physique.
# Toute différence entraîne une éjection d'étiquette vierge.
# B21S native resolution: 203.2 DPI → 80mm=640px, 30mm=240px
# IMPORTANT : 80mm est à 600px ici — le padding est géré dans niimprint._print_image_locked
_LAYOUT: dict[int, tuple[int, int, int, bool]] = {
    80: (384, 640, 10, False),   # WIDTH_PX, HEIGHT_PX, PADDING, ROTATE_90
    30: (384, 240, 10, False),
}

# ── Polices ──────────────────────────────────────────────────────────────────
# Résolues par tilauscope.text_shaping : même face que le plan PDF et que les
# planches A4, avec bascule CJK et passe bidi assurées par shaping_draw().

# ---------------------------------------------------------------------------
class NiimbotLabelBuilder:
    """Construit un PIL.Image 1-bit pour l'imprimante Niimbot B21S.

    Instance réutilisable : les polices sont chargées une seule fois dans
    ``__init__``.  Thread-safe en lecture (``build`` ne modifie pas l'état).
    """

    def __init__(self) -> None:
        self._font_label    = text_shaping.pil_font(20)
        self._font_header   = text_shaping.pil_font(24, bold=True)
        self._font_subtitle = text_shaping.pil_font(16, bold=True)
        self._font_value    = text_shaping.pil_font(24)
        self._font_notes    = text_shaping.pil_font(20)
        self._font_graph    = text_shaping.pil_font(12)
        self._font_sizes_value: list[ImageFont.FreeTypeFont] = [
            text_shaping.pil_font(sz) for sz in (20, 18, 16, 14, 12, 10)
        ]

    # ── API publique ─────────────────────────────────────────────────────────

    def build(
        self,
        bean: GreenBean,
        alog_data: dict,
        paper_height: int,
    ) -> Image.Image:
        """Retourne un PIL.Image mode '1' prêt à imprimer.

        Parameters
        ----------
        bean:         GreenBean associé à la torréfaction.
        alog_data:    dict retourné par ``BeancaveDlg.get_alog_data()``.
        paper_height: hauteur en mm du papier Niimbot (30 ou 80).

        Raises
        ------
        ValueError si ``paper_height`` n'est pas supporté.
        """
        if paper_height not in _LAYOUT:
            raise ValueError(
                f"NiimbotLabelBuilder: format papier {paper_height} mm non supporté "
                f"(supportés : {sorted(_LAYOUT)})"
            )

        W, H, PAD, ROTATE_90 = _LAYOUT[paper_height]
        roast_data, qr_data, phases = self._extract_data(bean, alog_data)

        img  = Image.new("1", (W, H), 1)
        draw = text_shaping.shaping_draw(img)

        if paper_height == 80:
            self._build_80mm(draw, img, W, H, PAD, roast_data, qr_data, phases)
        else:
            self._build_30mm(draw, img, W, H, PAD, roast_data, qr_data)

        # Garantir que l'image ne dépasse jamais HEIGHT_PX —
        # un pixel de trop suffit à faire éjecter une étiquette vierge.
        if img.height != H or img.width != W:
            _logd.warning(f"[LABEL] Crop de sécurité: ({img.width}×{img.height}) → ({W}×{H})")
            img = img.crop((0, 0, W, H))
        
        # if ROTATE_90, rotate the image 90 degrees clockwise to match printer orientation
        if ROTATE_90:
            img = img.rotate(-90, expand=True)
            _logd.debug(f"[LABEL] Image tournée de 90° pour orientation papier (ROTATE_90=True)")

        # Diagnostic : compter les pixels noirs et la zone de contenu
        black_px = sum(1 for y in range(img.height) for x in range(img.width) if img.getpixel((x, y)) == 0)
        last_black_y = max((y for y in range(img.height) for x in range(img.width) if img.getpixel((x, y)) == 0), default=-1)
        _logd.debug(
            f"[LABEL] Image générée: {img.width}×{img.height}px, mode={img.mode}, "
            f"pixels noirs={black_px}, dernier contenu y={last_black_y}px, "
            f"blanc bas={img.height - last_black_y - 1}px"
        )
        return img

    # ── Extraction / normalisation des données ───────────────────────────────

    def _extract_data(
        self,
        bean: GreenBean,
        data: dict,
    ) -> tuple[dict[str, str], str, dict[str, float]]:
        """Retourne (roast_data, qr_url, phases).

        ``phases`` contient les durées brutes (s) et les pourcentages.
        Lève ``ValueError`` si les points clés sont manquants/invalides.
        """
        computed = data.get("computed", {})
        mode     = data.get("mode", "C")

        t_dry  = computed.get("DRY_time")
        t_fcs  = computed.get("FCs_time")
        t_drop = computed.get("DROP_time")

        if None in (t_dry, t_fcs, t_drop) or t_drop <= 0:
            raise ValueError(
                "Données de torréfaction incomplètes (DRY/FCs/DROP) — "
                "impossible de calculer les phases."
            )

        t_charge   = 0.0
        drying     = float(t_dry)
        maillard   = float(t_fcs)  - float(t_dry)
        development= float(t_drop) - float(t_fcs)
        total      = float(t_drop)

        phases: dict[str, float] = {
            "drying":          drying,
            "maillard":        maillard,
            "development":     development,
            "total":           total,
            "drying_pct":      round(100 * drying     / total, 1),
            "maillard_pct":    round(100 * maillard   / total, 1),
            "development_pct": round(100 * development/ total, 1),
        }

        roast_iso  = data.get("roastisodate", "N/A")
        roast_date = (
            f"{roast_iso[8:10]}-{roast_iso[5:7]}-{roast_iso[:4]}"
            if roast_iso != "N/A" else "N/A"
        )

        weightin  = computed.get("weightin",  "N/A")
        weightout = computed.get("weightout", "N/A")
        wloss     = computed.get("weight_loss","N/A")

        roast_data: dict[str, str] = {
            "Bean":        (bean.name[:27] + "…") if len(bean.name) > 30 else bean.name,
            "Origin":      bean.country,
            "Process":     bean.process,
            "Variety":     bean.varieties,
            "Roaster":     bean.supplier,
            "Farm":        bean.farm,
            "Density":     f"{bean.density} g/l" if bean.density > 0 else str(data.get("density", ["-"])[0]),
            "Altitude":    f"{bean.altitude} m" if bean.altitude > 0 else "-",
            "Date":        roast_date,
            "Time":        data.get("roasttime", "N/A"),
            "SCA Score":   str(bean.sca),
            "Weight In":   f"{weightin} g",
            "Weight Out":  f"{weightout} g",
            "Weight Loss": f"{wloss} %",
            "Agtron Color":f"{data.get('whole_color','N/A')} {data.get('color_system','')}".strip(),
            "Total Time":  self._fmt_seconds(int(computed.get("totaltime", 0))),
            "DTR":         f"{round(computed.get('finishphasetime',0) / computed.get('totaltime',1) * 100, 1)}%",
            "Drop BT":     f"{computed.get('DROP_BT','N/A')}°{mode}",
            "RoR DEV":     f"{computed.get('finish_phase_ror','N/A')}°{mode}/min",
            "Notes (Aro.)":data.get("Aroma_Notes",   "N/A"),
            "Notes (Fls.)":bean.flavour_notes,
            "Notes (M.F.)":data.get("Mouthfeel_Notes","N/A"),
        }

        # Tasting notes consolidées
        notes_parts = []
        for key in ("Notes (Aro.)", "Notes (Fls.)", "Notes (M.F.)"):
            val = roast_data[key]
            if val and val != "N/A":
                initial = key.replace("Notes (", "").replace(".)", "")[:1]
                notes_parts.append(f"{initial}: {val}")
        roast_data["Tasting Notes"] = "; ".join(notes_parts)

        # ## TILAU ## QR encodes the same http record URL as the PDF label and the
        # bean/sack labels, so any label can be scanned (webcam or phone) to open
        # the roast record — previously encoded a raw text blob here, unscannable
        # by parse_tilau_qr().
        roast_uuid = str(data.get("roastUUID") or "")
        qr_url = f"{qr_base_url()}/roast/{roast_uuid}" if roast_uuid else ""

        return roast_data, qr_url, phases

    # ── Layout 80 mm ─────────────────────────────────────────────────────────
    #
    # Zones (hauteur 600px, largeur 384px, PAD=10) :
    #   [current_y=10]  Titre bean  (grande police)
    #   [sep]
    #   Infos grain : Origin / Farm / Process / Roaster / Variety
    #   [sep]
    #   Métriques   : Color / SCA score / Density / Altitude
    #                 Total time / DTR / Drop BT / Roast date
    #   [sep]
    #   Tasting Notes (wrapping, police graph)
    #   [QR 90px — bas droite, juste au-dessus du graphe]
    #   ─────────────────────────────────────────────
    #   Graphe phases (20px) + labels (12px) → 44px au total
    #   PAD bas

    def _build_80mm(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        W: int, H: int, PAD: int,
        roast_data: dict[str, str],
        qr_url:     str,
        phases:     dict[str, float],
    ) -> None:
        TEXT_W = W - 2 * PAD          # 364px — pleine largeur disponible

        # ── Réserver la zone basse : graphe + labels + QR ─────────────────
        GRAPH_H      = 20
        LABEL_GRAPH_H = draw.textbbox((0, 0), "0:00 (00.0%)", font=self._font_graph)[3] + 2
        QR_SIZE      = 90
        BOTTOM_ZONE  = PAD + GRAPH_H + LABEL_GRAPH_H + PAD  # espace graphe+labels
        QR_Y         = H - BOTTOM_ZONE - PAD - QR_SIZE       # Y du QR
        QR_X         = W - PAD - QR_SIZE                     # X du QR (droite)
        MAX_TEXT_Y   = QR_Y - PAD                            # limite basse du texte

        # ── Titre bean ────────────────────────────────────────────────────
        current_y = PAD
        # Police adaptive : on descend de taille si le nom est long
        title_fonts = [self._font_header, self._font_value, self._font_label]
        title_font  = self._font_header
        for f in title_fonts:
            if draw.textbbox((0, 0), roast_data["Bean"], font=f)[2] <= TEXT_W:
                title_font = f
                break
        draw.text((PAD, current_y), roast_data["Bean"],
                  font=title_font, fill=0)
        current_y += draw.textbbox((0, 0), roast_data["Bean"], font=title_font)[3] + 3

        # ── Séparateur ────────────────────────────────────────────────────
        def _hline(y: int) -> int:
            draw.line((PAD, y, W - PAD, y), fill=0, width=1)
            return y + 5

        current_y = _hline(current_y)

        # ── Infos grain ───────────────────────────────────────────────────
        grain_fields = [
            ("Origin",  roast_data["Origin"]),
            ("Farm",    roast_data["Farm"]),
            ("Process", roast_data["Process"]),
            ("Roaster", roast_data["Roaster"]),
            ("Variety", roast_data["Variety"]),
        ]
        for lbl, val in grain_fields:
            if current_y + 16 > MAX_TEXT_Y:
                break
            current_y += self._draw_adapting_text_line(
                draw, lbl, val,
                PAD, current_y, TEXT_W,
                self._font_label, self._font_sizes_value,
            )

        current_y = _hline(current_y)

        # ── Métriques torréfaction ────────────────────────────────────────
        metrics_fields = [
            ("Color",       roast_data["Agtron Color"]),
            ("SCA score",   roast_data["SCA Score"]),
            ("Density",     roast_data["Density"]),
            ("Altitude",    roast_data["Altitude"]),
            ("Total time",  roast_data["Total Time"]),
            ("DTR",         roast_data["DTR"]),
            ("Drop BT",     roast_data["Drop BT"]),
            ("Roast date",  roast_data["Date"]),
        ]
        for lbl, val in metrics_fields:
            if current_y + 16 > MAX_TEXT_Y:
                break
            current_y += self._draw_adapting_text_line(
                draw, lbl, val,
                PAD, current_y, TEXT_W,
                self._font_label, self._font_sizes_value,
            )

        current_y = _hline(current_y)

        # ── Tasting Notes ─────────────────────────────────────────────────
        if current_y + 20 < MAX_TEXT_Y:
            notes_lbl = QApplication.translate("tilauscope_label", "Tasting Notes:")
            draw.text((PAD, current_y), notes_lbl,
                      font=self._font_label, fill=0)
            current_y += draw.textbbox((0, 0), notes_lbl, font=self._font_label)[3] + 2

            # Zone notes : largeur réduite si le QR empiète horizontalement
            notes_w   = TEXT_W
            notes_max_y = MAX_TEXT_Y
            self._draw_wrapped_text(
                draw, roast_data["Tasting Notes"],
                PAD, current_y, notes_w, notes_max_y,
                self._font_graph,
            )

        # ── QR code — bas droite, au-dessus du graphe ─────────────────────
        if qr_url:
            self._paste_qr(img, draw, qr_url, QR_X, QR_Y, QR_SIZE)

        # ── Séparateur avant graphe ───────────────────────────────────────
        GRAPH_Y = H - PAD - LABEL_GRAPH_H - GRAPH_H
        draw.line((PAD, GRAPH_Y - PAD, W - PAD, GRAPH_Y - PAD), fill=0, width=1)

        # ── Graphe de phases ──────────────────────────────────────────────
        GRAPH_X = PAD
        GRAPH_W = W - 2 * PAD

        draw.rectangle(
            (GRAPH_X, GRAPH_Y, GRAPH_X + GRAPH_W, GRAPH_Y + GRAPH_H),
            outline=0, fill=1,
        )

        x_maillard    = GRAPH_X + int(GRAPH_W * phases["drying_pct"]     / 100)
        x_development = x_maillard + int(GRAPH_W * phases["maillard_pct"] / 100)

        # Drying — hachures verticales
        for i in range(0, int(GRAPH_W * phases["drying_pct"] / 100), 4):
            draw.line([GRAPH_X + i, GRAPH_Y, GRAPH_X + i, GRAPH_Y + GRAPH_H],
                      fill=0, width=1)

        # Maillard — pointillés
        for gx in range(x_maillard, x_development, 4):
            for gy in range(GRAPH_Y + 1, GRAPH_Y + GRAPH_H, 4):
                draw.point((gx, gy), fill=0)

        # Development — plein
        draw.rectangle(
            (x_development, GRAPH_Y, GRAPH_X + GRAPH_W, GRAPH_Y + GRAPH_H),
            fill=0,
        )

        # ── Labels phases ─────────────────────────────────────────────────
        label_y = GRAPH_Y + GRAPH_H + 2
        for label_txt, center_x in (
            (
                f"{self._fmt_seconds(int(phases['drying']))} ({phases['drying_pct']}%)",
                GRAPH_X + int(GRAPH_W * phases["drying_pct"] / 100 / 2),
            ),
            (
                f"{self._fmt_seconds(int(phases['maillard']))} ({phases['maillard_pct']}%)",
                x_maillard + int(GRAPH_W * phases["maillard_pct"] / 100 / 2),
            ),
            (
                f"{self._fmt_seconds(int(phases['development']))} ({phases['development_pct']}%)",
                x_development + int(GRAPH_W * phases["development_pct"] / 100 / 2),
            ),
        ):
            w_txt = draw.textbbox((0, 0), label_txt, font=self._font_graph)[2]
            x_pos = int(center_x - w_txt / 2)
            # Garder dans les bornes
            x_pos = max(PAD, min(x_pos, W - PAD - w_txt))
            draw.text((x_pos, label_y), label_txt,
                      font=self._font_graph, fill=0)

    # ── Layout 30 mm ─────────────────────────────────────────────────────────

    def _build_30mm(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        W: int, H: int, PAD: int,
        roast_data: dict[str, str],
        qr_url:     str,
    ) -> None:
        # QR supprimé sur ce format — trop petit pour être utile.
        # Texte pleine largeur (W - 2*PAD).
        TEXT_W = W - 2 * PAD
        current_y = PAD

        # Ligne 1 : Origin + Farm  — police valeur, pleine largeur
        origin_farm = f"{roast_data['Origin']} {roast_data['Farm']}"
        # Troncature pixel-exacte
        while draw.textbbox((0, 0), origin_farm, font=self._font_value)[2] > TEXT_W and len(origin_farm) > 3:
            origin_farm = origin_farm[:-1]
        if origin_farm != f"{roast_data['Origin']} {roast_data['Farm']}":
            origin_farm = origin_farm.rstrip() + "…"
        draw.text((PAD, current_y), origin_farm, font=self._font_value, fill=0)
        current_y += draw.textbbox((0, 0), origin_farm, font=self._font_value)[3] + 1

        # Ligne 2 : Bean — police subtitle
        bean_txt = QApplication.translate("tilauscope_label", "Beans") + f": {roast_data['Bean']}"
        while draw.textbbox((0, 0), bean_txt, font=self._font_subtitle)[2] > TEXT_W and len(bean_txt) > 6:
            bean_txt = bean_txt[:-1]
        draw.text((PAD, current_y), bean_txt, font=self._font_subtitle, fill=0)
        current_y += draw.textbbox((0, 0), bean_txt, font=self._font_subtitle)[3] + 2

        # Lignes détails — police subtitle, pleine largeur, troncature adaptative
        detail_rows = [
            (QApplication.translate("tilauscope_label", "Process"),   roast_data["Process"]),
            (QApplication.translate("tilauscope_label", "Altitude"),  roast_data["Altitude"]),
            (QApplication.translate("tilauscope_label", "Density"),   roast_data["Density"]),
            (QApplication.translate("tilauscope_label", "SCA score"), roast_data["SCA Score"]),
        ]
        for lbl, val in detail_rows:
            if current_y + draw.textbbox((0, 0), "Ag", font=self._font_subtitle)[3] > H - PAD * 4:
                break
            current_y += self._draw_adapting_text_line(
                draw, lbl, val,
                PAD, current_y, TEXT_W,
                self._font_subtitle, self._font_sizes_value,
            )

        current_y += 2
        # Ligne date
        date_txt = QApplication.translate("tilauscope_label", "Roasted on") + f": {roast_data['Date']}"
        draw.text((PAD, current_y), date_txt, font=self._font_subtitle, fill=0)
        current_y += draw.textbbox((0, 0), date_txt, font=self._font_subtitle)[3] + 2

        # Tasting notes — police graph, wrapping pixel-exact
        notes_hdr = QApplication.translate("tilauscope_label", "Tasting notes") + ": "
        draw.text((PAD, current_y), notes_hdr, font=self._font_graph, fill=0)
        current_y += draw.textbbox((0, 0), notes_hdr, font=self._font_graph)[3] + 1

        self._draw_wrapped_text(
            draw, roast_data["Tasting Notes"],
            PAD, current_y, TEXT_W, H - PAD,
            self._font_graph,
        )

    # ── Helpers privés ────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_seconds(s: int) -> str:
        """Formate une durée en secondes → 'm:ss'."""
        return f"{s // 60}:{s % 60:02d}"

    def _draw_adapting_text_line(
        self,
        draw: ImageDraw.ImageDraw,
        label: str,
        value: str,
        x: int, y: int,
        max_width: int,
        font_label: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        font_sizes_value: Sequence[ImageFont.FreeTypeFont | ImageFont.ImageFont],
        fill: int = 0,
    ) -> int:
        """Dessine `label: value` sur une ligne avec police adaptative pour la valeur.

        Retourne la hauteur de ligne consommée (px) pour incrémenter current_y.
        """
        label_str = (label + ": ") if label else ""

        if not font_sizes_value:
            draw.text((x, y), f"{label_str}{value}", font=font_label, fill=fill)
            return draw.textbbox((0, 0), "Ag", font=font_label)[3] + 1  # type: ignore[union-attr]

        label_w = draw.textbbox((0, 0), label_str, font=font_label)[2]
        max_val_w = max_width - label_w

        best = font_sizes_value[-1]
        for f in font_sizes_value:
            if draw.textbbox((0, 0), value, font=f)[2] <= max_val_w:
                best = f
                break

        # Troncature si même la plus petite police déborde
        if draw.textbbox((0, 0), value, font=best)[2] > max_val_w:
            while value and draw.textbbox((0, 0), value + "…", font=best)[2] > max_val_w:
                value = value[:-1]
            value = value + "…"

        draw.text((x,             y), label_str, font=font_label, fill=fill)
        draw.text((x + label_w,   y), value,     font=best,       fill=fill)
        return draw.textbbox((0, 0), "Ag", font=font_label)[3] + 2  # type: ignore[union-attr]

    def _draw_wrapped_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        x: int, y: int,
        max_width: int,
        max_y: int,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> int:
        """Wrapping pixel-exact. Retourne la position Y après le dernier trait."""
        words = text.split(" ")
        current_line = ""
        line_h = draw.textbbox((0, 0), "Ag", font=font)[3] + 1  # type: ignore[union-attr]

        for word in words:
            test = (current_line + " " + word).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_width:  # type: ignore[union-attr]
                current_line = test
            else:
                if current_line:
                    if y + line_h > max_y:
                        break
                    draw.text((x, y), current_line, font=font, fill=0)
                    y += line_h
                current_line = word

        if current_line and y + line_h <= max_y:
            draw.text((x, y), current_line, font=font, fill=0)
            y += line_h

        return y

    def _paste_qr(
        self,
        img:     Image.Image,
        draw:    ImageDraw.ImageDraw,
        payload: str,
        qr_x:    int,
        qr_y:    int,
        size:    int,
    ) -> None:
        """Génère et colle le QR code à la position (qr_x, qr_y)."""
        draw.rectangle((qr_x, qr_y, qr_x + size, qr_y + size), fill=0, outline=0)
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=4,
                border=0,
            )
            qr.add_data(payload)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("L")
            qr_img = qr_img.resize((size, size), Image.Resampling.NEAREST)
            img.paste(qr_img, (qr_x, qr_y))
        except Exception as exc:
            _logd.warning(f"NiimbotLabelBuilder: échec génération QR code: {exc}")

# ---------------------------------------------------------------------------
## TILAU ## Sack ID label (design v4 §3-§4) — 50×30 mm Niimbot bitmap.
# QR encodes tilauscope://sack/{id} (URL scheme, same family as the bean
# label's tilauscope://beancave/{uuid}); the id is repeated human-readable.
# ---------------------------------------------------------------------------

def build_sack_label_image(sack_id: str) -> Image.Image:
    """Return a 384×240 1-bit PIL image for a sack ID label (30 mm roll)."""
    W, H, PAD, _rot = _LAYOUT[30]
    img  = Image.new("1", (W, H), 1)
    draw = text_shaping.shaping_draw(img)

    # ── QR left ──────────────────────────────────────────────────────────────
    qr_size = H - 2 * PAD                      # 220 px
    try:
        qr = qrcode.QRCode(version=None,
                           error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=4, border=1)
        qr.add_data(f"tilauscope://sack/{sack_id}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("1")
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)
        img.paste(qr_img, (PAD, PAD))
    except Exception as exc:
        _logd.warning(f"build_sack_label_image: QR generation failed: {exc}")

    # ── Human-readable id right ─────────────────────────────────────────────
    text_x = PAD + qr_size + PAD
    text_w = W - text_x - PAD                  # ~144 px
    def _fit(text: str, sizes: tuple[int, ...]) -> "ImageFont.FreeTypeFont":
        f = text_shaping.pil_font(sizes[-1], bold=True)
        for sz in sizes:
            f = text_shaping.pil_font(sz, bold=True)
            if draw.textlength(text, font=f) <= text_w:
                break
        return f

    caption_font = text_shaping.pil_font(14)
    font = _fit(sack_id, (44, 38, 32, 28, 24, 20, 16))
    if draw.textlength(sack_id, font=font) <= text_w:
        lines = [sack_id]
    else:
        # too long for one readable line: split near the middle,
        # preferring a separator, and fit each half independently
        mid = len(sack_id) // 2
        seps = [i for i, ch in enumerate(sack_id) if ch in "-_ ."]
        cut = min(seps, key=lambda i: abs(i - mid)) + 1 if seps else mid
        lines = [sack_id[:cut], sack_id[cut:]]
        font = min((_fit(ln, (32, 28, 24, 20, 16, 12)) for ln in lines),
                   key=lambda f: f.size)

    line_hs = []
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        line_hs.append((bbox[3] - bbox[1], bbox[1]))
    gap = 6 if len(lines) > 1 else 0
    block_h = sum(h for h, _o in line_hs) + gap * (len(lines) - 1)
    ty = (H - block_h) // 2
    for ln, (h, off) in zip(lines, line_hs, strict=True):
        draw.text((text_x, ty - off), ln, font=font, fill=0)
        ty += h + gap
    draw.text((text_x, H - PAD - 16), "TILAUSCOPE", font=caption_font, fill=0)
    return img


# ---------------------------------------------------------------------------
## TILAU ## Dial-in brew recipe label — 50×30 mm Niimbot bitmap.
# Two templates driven by the brew method:
#   • Espresso  → a 3×2 grid of large "grammage" numbers (dose/yield/ratio…).
#   • Soft methods (V60, French press, AeroPress, Pulsar, Weber Bird, Moka)
#     → the timed pour protocol (each step: time · gesture · target grams).
# Both share a header: bean name (title) + method + a grain line (process +
# colour level) + a monochrome method pictogram (the "target").
# ---------------------------------------------------------------------------


def _brew_clean(text: str) -> str:
    """Normalise a label string without losing any of it.

    This used to strip accents, because the display face the labels were drawn
    in carried 223 glyphs and no `é`. That worked for French and destroyed
    everything else: decomposing Korean splits a syllable into separate jamo,
    and dropping the combining marks of Devanagari, Arabic or Vietnamese changes
    the words outright. The bundled face covers those scripts, so the text is
    now printed as written. NFC is applied so a decomposed `e`+`́` from an
    external source occupies one glyph rather than two overlapping ones.
    """
    import unicodedata
    if not text:
        return ""
    return unicodedata.normalize("NFC", str(text))


# ── Method pictograms (drawn 1-bit, black on white, in a size×size box) ─────
def _ic_espresso(d, x, y, s):
    lw = 3
    ct, cb = y + int(s * 0.34), y + int(s * 0.74)
    l, r = x + int(s * 0.14), x + int(s * 0.64)
    li, ri = x + int(s * 0.22), x + int(s * 0.56)
    d.line([(l, ct), (li, cb)], fill=0, width=lw); d.line([(r, ct), (ri, cb)], fill=0, width=lw)
    d.line([(l, ct), (r, ct)], fill=0, width=lw); d.line([(li, cb), (ri, cb)], fill=0, width=lw)
    d.arc([r - 4, ct + 2, r + int(s * 0.22), ct + int(s * 0.26)], -70, 70, fill=0, width=lw)
    d.line([(x + int(s * 0.06), cb + 5), (x + int(s * 0.72), cb + 5)], fill=0, width=lw)
    for sx in (x + int(s * 0.28), x + int(s * 0.44)):
        d.line([(sx, y + int(s * 0.10)), (sx, y + int(s * 0.26))], fill=0, width=2)


def _ic_v60(d, x, y, s):
    lw = 3
    top, bot = y + int(s * 0.20), y + int(s * 0.62)
    l, r = x + int(s * 0.10), x + int(s * 0.72)
    bl, br = x + int(s * 0.36), x + int(s * 0.46)
    d.line([(l, top), (bl, bot)], fill=0, width=lw); d.line([(r, top), (br, bot)], fill=0, width=lw)
    d.line([(l, top), (r, top)], fill=0, width=lw)
    d.line([(x + int(s * 0.30), top + 3), (x + int(s * 0.40), bot - 2)], fill=0, width=1)
    d.line([(x + int(s * 0.52), top + 3), (x + int(s * 0.42), bot - 2)], fill=0, width=1)
    d.line([(x + int(s * 0.41), bot), (x + int(s * 0.41), bot + int(s * 0.10))], fill=0, width=2)
    sy = bot + int(s * 0.14)
    d.line([(x + int(s * 0.20), sy), (x + int(s * 0.62), sy)], fill=0, width=lw)
    d.line([(x + int(s * 0.20), sy), (x + int(s * 0.24), sy + int(s * 0.16))], fill=0, width=lw)
    d.line([(x + int(s * 0.62), sy), (x + int(s * 0.58), sy + int(s * 0.16))], fill=0, width=lw)
    d.line([(x + int(s * 0.24), sy + int(s * 0.16)), (x + int(s * 0.58), sy + int(s * 0.16))], fill=0, width=lw)


def _ic_press(d, x, y, s):  # French press: carafe + plunger rod + knob
    lw = 3
    l, r = x + int(s * 0.20), x + int(s * 0.66)
    top, bot = y + int(s * 0.30), y + int(s * 0.82)
    d.rectangle([l, top, r, bot], outline=0, width=lw)
    midx = (l + r) // 2
    d.line([(midx, y + int(s * 0.10)), (midx, top)], fill=0, width=lw)
    d.line([(midx - int(s * 0.10), y + int(s * 0.10)), (midx + int(s * 0.10), y + int(s * 0.10))], fill=0, width=lw)
    d.line([(l, y + int(s * 0.42)), (r, y + int(s * 0.42))], fill=0, width=lw)
    d.line([(r, top + 2), (r + int(s * 0.08), top + int(s * 0.12))], fill=0, width=lw)


def _ic_aeropress(d, x, y, s):  # chamber + plunger rod + filter cap
    lw = 3
    l, r = x + int(s * 0.26), x + int(s * 0.62)
    top, bot = y + int(s * 0.28), y + int(s * 0.76)
    d.rectangle([l, top, r, bot], outline=0, width=lw)
    midx = (l + r) // 2
    d.line([(midx, y + int(s * 0.08)), (midx, top)], fill=0, width=lw)
    d.line([(l, y + int(s * 0.40)), (r, y + int(s * 0.40))], fill=0, width=lw)
    d.line([(l - 3, bot), (r + 3, bot)], fill=0, width=lw)
    d.line([(l + 2, bot + int(s * 0.07)), (r - 2, bot + int(s * 0.07))], fill=0, width=2)


def _ic_moka(d, x, y, s):  # stovetop moka pot: hourglass body + knob + handle
    lw = 3
    cx = x + int(s * 0.42)
    mid, base, topy = y + int(s * 0.52), y + int(s * 0.82), y + int(s * 0.20)
    bl, br = x + int(s * 0.16), x + int(s * 0.58)
    wl, wr = x + int(s * 0.26), x + int(s * 0.50)
    tl, tr = x + int(s * 0.20), x + int(s * 0.54)
    d.line([(bl, base), (br, base)], fill=0, width=lw)
    d.line([(bl, base), (wl, mid)], fill=0, width=lw); d.line([(br, base), (wr, mid)], fill=0, width=lw)
    d.line([(wl, mid), (tl, topy)], fill=0, width=lw); d.line([(wr, mid), (tr, topy)], fill=0, width=lw)
    d.line([(tl, topy), (tr, topy)], fill=0, width=lw)
    d.line([(cx - int(s * 0.06), y + int(s * 0.10)), (cx + int(s * 0.06), y + int(s * 0.10))], fill=0, width=lw)
    d.line([(cx, y + int(s * 0.10)), (cx, topy)], fill=0, width=2)
    d.line([(br, base - int(s * 0.04)), (x + int(s * 0.80), base - int(s * 0.14))], fill=0, width=lw)
    d.line([(wr, mid + int(s * 0.02)), (x + int(s * 0.80), base - int(s * 0.14))], fill=0, width=lw)


def _ic_flatbottom(d, x, y, s):  # no-bypass flat-bottom brewer (Pulsar / Bird)
    lw = 3
    top, bot = y + int(s * 0.24), y + int(s * 0.66)
    l, r = x + int(s * 0.12), x + int(s * 0.74)
    bl, br = x + int(s * 0.28), x + int(s * 0.58)
    d.line([(l, top), (bl, bot)], fill=0, width=lw); d.line([(r, top), (br, bot)], fill=0, width=lw)
    d.line([(l, top), (r, top)], fill=0, width=lw); d.line([(bl, bot), (br, bot)], fill=0, width=lw)
    d.line([(x + int(s * 0.30), top + 3), (x + int(s * 0.36), bot - 2)], fill=0, width=1)
    d.line([(x + int(s * 0.50), top + 3), (x + int(s * 0.48), bot - 2)], fill=0, width=1)
    for dx in (bl + 5, br - 5):
        d.line([(dx, bot), (dx, bot + int(s * 0.10))], fill=0, width=2)


def _ic_cup(d, x, y, s):  # generic fallback mug
    lw = 3
    l, r = x + int(s * 0.16), x + int(s * 0.58)
    top, bot = y + int(s * 0.28), y + int(s * 0.74)
    d.rectangle([l, top, r, bot], outline=0, width=lw)
    d.arc([r - 2, top + 4, r + int(s * 0.24), bot - 4], -80, 80, fill=0, width=lw)
    for sx in (x + int(s * 0.26), x + int(s * 0.42)):
        d.line([(sx, y + int(s * 0.08)), (sx, y + int(s * 0.22))], fill=0, width=2)


_BREW_ICONS = {
    "ESPRESSO": _ic_espresso, "V60": _ic_v60, "FRENCH_PRESS": _ic_press,
    "AEROPRESS": _ic_aeropress, "MOKA": _ic_moka,
    "PULSAR": _ic_flatbottom, "WEBER_BIRD": _ic_flatbottom,
}


def _brew_fonts(draw, text, bold, sizes, max_w):
    """Largest of `sizes` whose `text` fits `max_w`; else smallest + ellipsis."""
    def _load(sz):
        return text_shaping.pil_font(sz, bold=bold)

    f = _load(sizes[-1])
    for sz in sizes:
        f = _load(sz)
        if draw.textlength(text, font=f) <= max_w:
            return text, f
    out = text
    while out and draw.textlength(out + "…", font=f) > max_w:
        out = out[:-1]
    return (out + "…") if out else text, f


def build_brew_recipe_label_image(
    title: str,
    method_id: str,
    method_label: str,
    grain_line: str = "",
    *,
    grid_cells: list[tuple[str, str]] | None = None,
    spec_line: str = "",
    steps: list[tuple[str, str, str]] | None = None,
) -> Image.Image:
    """Return a 384×240 1-bit dial-in brew label (50×30 mm roll).

    Pass ``grid_cells`` (six (label, value) pairs) for the espresso grammage
    grid, or ``spec_line`` + ``steps`` ((time, gesture, target) tuples) for the
    timed protocol used by every other method. All strings are already
    localised and formatted by the caller."""
    W, H, PAD, _rot = _LAYOUT[30]
    img = Image.new("1", (W, H), 1)
    d = text_shaping.shaping_draw(img)
    text_w = W - 2 * PAD

    # ── Header: pictogram (top-right) + name + method + grain line ───────────
    icon_s, icon_x = 50, W - PAD - 50
    _BREW_ICONS.get(method_id, _ic_cup)(d, icon_x, PAD, icon_s)
    name_w = icon_x - PAD - 8

    nt, nf = _brew_fonts(d, _brew_clean(title), True, (30, 26, 22, 19, 16), name_w)
    d.text((PAD, PAD), nt, font=nf, fill=0)
    y = PAD + d.textbbox((0, 0), nt, font=nf)[3] + 2

    mt, mf = _brew_fonts(d, _brew_clean(method_label), False, (18, 16, 14), name_w)
    d.text((PAD, y), mt, font=mf, fill=0)
    y += d.textbbox((0, 0), mt, font=mf)[3] + 3

    if grain_line:
        gt, gf = _brew_fonts(d, _brew_clean(grain_line), False, (16, 15, 14, 13), text_w)
        d.text((PAD, y), gt, font=gf, fill=0)
        y += d.textbbox((0, 0), gt, font=gf)[3] + 4

    y = max(y + 1, PAD + icon_s + 3)
    d.line((PAD, y, W - PAD, y), fill=0, width=1)
    y += 6

    if grid_cells is not None:
        # ── Espresso grammage grid: 3 columns × 2 rows of big numbers ───────
        col_w = text_w // 3
        grid_top, row_gap = y, (H - PAD - y) // 2
        lbl_font = _brew_fonts(d, "Ag", False, (15,), col_w)[1]
        lbl_h = d.textbbox((0, 0), "Ag", font=lbl_font)[3]
        for idx, (lbl, val) in enumerate(grid_cells[:6]):
            col, row = idx % 3, idx // 3
            cx = PAD + col * col_w
            ry = grid_top + row * row_gap
            d.text((cx, ry), _brew_clean(str(lbl)).upper(), font=lbl_font, fill=0)
            vt, vf = _brew_fonts(d, _brew_clean(str(val)), True, (30, 26, 22, 18, 15), col_w - 6)
            d.text((cx, ry + lbl_h + 3), vt, font=vf, fill=0)
    else:
        # ── Soft-method protocol: compact spec line + timed steps ───────────
        if spec_line:
            st, sf = _brew_fonts(d, _brew_clean(spec_line), False, (16, 15, 14, 13), text_w)
            d.text((PAD, y), st, font=sf, fill=0)
            y += d.textbbox((0, 0), st, font=sf)[3] + 4
            d.line((PAD, y, W - PAD, y), fill=0, width=1)
            y += 5
        tfont = _brew_fonts(d, "0:00", True, (17,), 60)[1]
        gfont = tfont
        time_w, line_h = 52, 22
        for tstr, desc, tgt in (steps or []):
            if y + line_h > H - PAD + 2:
                break
            d.text((PAD, y), _brew_clean(tstr), font=tfont, fill=0)
            gx = W - PAD
            if tgt:
                gc = _brew_clean(tgt)
                gx = W - PAD - int(d.textlength(gc, font=gfont))
                d.text((gx, y), gc, font=gfont, fill=0)
            avail = gx - (PAD + time_w) - 6
            dt, df = _brew_fonts(d, _brew_clean(desc), False, (17, 16, 15, 14), max(avail, 20))
            d.text((PAD + time_w, y), dt, font=df, fill=0)
            y += line_h

    return img
