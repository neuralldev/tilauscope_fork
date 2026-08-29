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

"""The self-contained widgets BeanCave builds its screens from.

None of them reads the running Artisan session or the BeanCave dialog; they take
what they need through their constructor."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon  # pylint: disable=unused-import

#import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas


from artisanlib.widgets import MyQDoubleSpinBox


from PyQt6.QtCore import (QRect, QStandardPaths, Qt, pyqtSlot, pyqtSignal, QObject,
                          QEasingCurve,QPoint, QTimer, QPropertyAnimation, QEvent, QVariantAnimation, QSize) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QPixmap, QColor, QResizeEvent, QGuiApplication, QCursor, QPainter, QPainterPath, QBrush) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QComboBox, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget, QFrame, QFileDialog, QMessageBox, QDialog, QSizePolicy) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.theme_qss import apply_tilau_theme, tint, tooltip_qss
from tilauscope.tilauscope_types import (show_styled_message,
                                         THEME)

from tilauscope.cave.common import (  # noqa: F401
    _logd, _log, _PLOT_PALETTE, _FS_TITLE, _FS_AXIS, _FS_TICK, _FS_EVENT, _FS_HOVER, _FS_LEGEND, C0_COLOR_KEY, C_BT_COLOR_KEY, C_DTR_COLOR_KEY, C_WL_COLOR_KEY, DEFAULT_C0, DEFAULT_C_BT, DEFAULT_C_DTR, DEFAULT_C_WL, greencave_headers, BEANCAVE_FILE_NAME, _SVG_EXPAND, _SVG_COLLAPSE, _SVG_CONSISTENCY, _SVG_ALIGN, _safe_filename, _svg_bytes_to_icon, _SVG_DENSITY, load_cave_beans, _atomic_write_text, apply_mica_acrylic_effect)

class ZoomToggleButton(QPushButton):
    """
    Bouton zoom/fullscreen checkable avec icônes SVG inline.

    - Icônes chargées une seule fois en variable de classe (lazy).
    - Aucun emoji, aucun texte : rendu identique macOS / Windows.
    - État normal : fond sombre transparent.
    - État actif  : fond bleu teinté.
    - Signal toggled(bool) hérité de QPushButton.
    """

    _icon_normal: "QIcon | None" = None
    _icon_active: "QIcon | None" = None

    _ICON_SIZE = 16
    _BTN_SIZE  = 32

    _SS = f"""
        QPushButton {{
            background-color : {tint('BG', 160)};
            border            : 1px solid rgba(255, 255, 255, 45);
            border-radius     : 8px;
        }}
        QPushButton:hover {{
            background-color : rgba(60,  60,  90,  200);
            border           : 1px solid rgba(255, 255, 255, 90);
        }}
        QPushButton:checked {{
            background-color : rgba(89,  150, 246, 55);
            border           : 1px solid rgba(89,  150, 246, 180);
        }}
        QPushButton:disabled {{
            opacity : 0.35;
        }}
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(self._BTN_SIZE, self._BTN_SIZE)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(
            QApplication.translate("tilauscope_beancave", "Toggle full-screen curve")
        )
        self.setText("")
        self.setStyleSheet(self._SS)

        if ZoomToggleButton._icon_normal is None:
            ZoomToggleButton._icon_normal = _svg_bytes_to_icon(_SVG_EXPAND,   self._ICON_SIZE)
            ZoomToggleButton._icon_active = _svg_bytes_to_icon(_SVG_COLLAPSE, self._ICON_SIZE)

        self.setIcon(ZoomToggleButton._icon_normal)       # type: ignore[arg-type]
        self.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        self.toggled.connect(self._sync_icon)

    @pyqtSlot(bool)
    def _sync_icon(self, checked: bool) -> None:
        icon = ZoomToggleButton._icon_active if checked else ZoomToggleButton._icon_normal
        self.setIcon(icon)  # type: ignore[arg-type]

class SaveMarkerButton(QPushButton):
    """
    Ephemeral overlay button shown when timeindex has been edited but not saved.
    Positioned bottom-right of CanvasContainer, hidden by default.
    """
    _SS = f"""
        QPushButton {{
            background-color : rgba(166, 227, 161, 220);
            color            : {THEME['BG']};
            border           : 1px solid rgba(166, 227, 161, 255);
            border-radius    : 6px;
            padding          : 4px 14px;
            font-size        : 11px;
            font-weight      : bold;
        }}
        QPushButton:hover {{
            background-color : rgba(166, 227, 161, 255);
        }}
        QPushButton:pressed {{
            background-color : rgba(100, 180, 100, 255);
        }}
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(QApplication.translate("tilauscope_beancave", "💾 Save markers"))
        self.setStyleSheet(self._SS)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.adjustSize()
        self.hide()

class CanvasContainer(QWidget):
    """
    Conteneur Qt stable qui wrappe le FigureCanvas matplotlib.

    - Fournit un parent QWidget dans le layout (curve_layout).
    - Porte le ZoomToggleButton en overlay haut-gauche via son propre resizeEvent.
    - Porte le SaveMarkerButton en overlay bas-droite (caché par défaut).
    - En mode zoom plein-écran, on transfère CE widget dans le QDialog :
      les boutons suivent naturellement (ils sont enfants du conteneur).
    """

    _MARGIN = 8

    def __init__(
        self,
        canvas: FigureCanvas,
        zoom_btn: ZoomToggleButton,
        parent: QWidget | None = None,
        mode_btns: "list[QPushButton] | None" = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(canvas)

        zoom_btn.setParent(self)
        zoom_btn.raise_()
        self._zoom_btn = zoom_btn

        # Toggles optionnels (vues Consistance / Aligné) en overlay, à droite du zoom.
        self._mode_btns = list(mode_btns or [])
        for b in self._mode_btns:
            b.setParent(self)
            b.raise_()

        self._save_btn = SaveMarkerButton(self)
        self._save_btn.raise_()

        self._reposition_buttons()

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition_buttons()

    def _reposition_buttons(self) -> None:
        self._zoom_btn.move(self._MARGIN, self._MARGIN)
        x = self._MARGIN + self._zoom_btn.width() + 6
        for b in self._mode_btns:
            b.move(x, self._MARGIN)
            x += b.width() + 6
        bw = self._save_btn.sizeHint().width()
        bh = self._save_btn.sizeHint().height()
        x = self.width()  - bw - self._MARGIN
        y = self.height() - bh - self._MARGIN * 5
        self._save_btn.move(max(0, x), max(0, y))

    # Alias for callers of _reposition_button
    def _reposition_button(self) -> None:
        self._reposition_buttons()

class HoverTooltip(QLabel):
    def __init__(self):               ## ← no parent arg
        super().__init__(
            None,                     ## ← parent=None, top-level window
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool      ## ← Tool, not ToolTip
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                padding: 6px;
                border-radius: 4px;
                font-size: 11px;
            }}
        """)
        self.setWordWrap(False)
        self.hide()

    def show_at(self, global_pos: QPoint, html: str) -> None:
        self.setText(html)
        self.adjustSize()
        # Décalage pour ne pas être pile sous le curseur
        offset = QPoint(15, 15)
        self.move(global_pos + offset) # move utilise des coordonnées ECRAN
        self.show()

class SmoothHoverFilter(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_border = QColor(THEME['BORDER'])
        self.accent_border = QColor(THEME['ACCENT'])

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.HoverEnter:
            self.animate(obj, self.base_border, self.accent_border)
            return True   # ← keep returning True so Qt doesn't double-fire
        elif event.type() == QEvent.Type.HoverLeave:
            self.animate(obj, self.accent_border, self.base_border)
            return True
        return super().eventFilter(obj, event)

    def animate(self, widget, start_brd, end_brd):
        anim = QVariantAnimation(widget)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Determine the Qt widget class name for scoped CSS
        # This prevents the rule leaking into child widgets or tooltip scope
        class_name = widget.__class__.__name__

        def update_style(value):
            brd_r = int(start_brd.red()   + (end_brd.red()   - start_brd.red())   * value)
            brd_g = int(start_brd.green() + (end_brd.green() - start_brd.green()) * value)
            brd_b = int(start_brd.blue()  + (end_brd.blue()  - start_brd.blue())  * value)
            color_brd = f"rgb({brd_r}, {brd_g}, {brd_b})"

            widget.setStyleSheet(f"""
                {class_name} {{
                    border: 2px solid {color_brd};
                    border-radius: 5px;
                    padding: 3px;
                    background-color: {THEME['SURFACE']};
                    color: {THEME['TEXT']};
                    }}
                {tooltip_qss()}
            """)

        anim.valueChanged.connect(update_style)
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

class TilauSpinBox(MyQDoubleSpinBox):
    """
    MyQDoubleSpinBox that draws its own inset up/down arrows via paintEvent.
    Fixes macOS Qt6/Fusion ignoring ::up-arrow CSS, and prevents hover-
    triggered window resize.
    """

    _BTN_W  : int = 20   # button column width  (px)
    _ARROW_W: int = 7    # arrow glyph width    (px)
    _ARROW_H: int = 4    # arrow glyph height   (px)
    _H      : int = 28   # fixed widget height  (px)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self._H)
        # ── Only style THIS class — do NOT use QDoubleSpinBox here
        # so the parent stylesheet's QDoubleSpinBox rule can't override us
        self.setStyleSheet(f"""
            TilauSpinBox {{
                padding-right : {self._BTN_W + 2}px;
                border        : 1px solid {THEME['BORDER']};
                border-radius : 5px;
                background    : {THEME['SURFACE']};
                color         : {THEME['TEXT']};
                font-size     : 12px;
            }}
            TilauSpinBox:focus {{
                border : 1px solid {THEME['ACCENT']};
            }}
            /* Completely suppress the native button subcontrols */
            TilauSpinBox::up-button   {{ width: 0px; border: none; }}
            TilauSpinBox::down-button {{ width: 0px; border: none; }}
            TilauSpinBox::up-arrow    {{ width: 0px; height: 0px; }}
            TilauSpinBox::down-arrow  {{ width: 0px; height: 0px; }}
        """)
        self._up_hovered   = False
        self._down_hovered = False
        self.setMouseTracking(True)

    # ── geometry — use contentsRect() so layout is already resolved ───────

    def _btn_x(self) -> int:
        """Left edge of the button column, inside the border."""
        return self.contentsRect().right() - self._BTN_W + 1

    def _up_rect(self) -> QRect:
        r   = self.contentsRect()
        mid = r.top() + r.height() // 2
        return QRect(self._btn_x(), r.top(), self._BTN_W, mid - r.top())

    def _down_rect(self) -> QRect:
        r   = self.contentsRect()
        mid = r.top() + r.height() // 2
        return QRect(self._btn_x(), mid, self._BTN_W, r.bottom() - mid + 1)

    # ── mouse ─────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event) -> None:
        pos      = event.pos()
        up_hot   = self._up_rect().contains(pos)
        down_hot = self._down_rect().contains(pos)
        if up_hot != self._up_hovered or down_hot != self._down_hovered:
            self._up_hovered   = up_hot
            self._down_hovered = down_hot
            self.update()          # repaint only — no geometry change
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._up_hovered or self._down_hovered:
            self._up_hovered   = False
            self._down_hovered = False
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        pos = event.pos()
        if self._up_rect().contains(pos):
            self.stepUp()
            return
        if self._down_rect().contains(pos):
            self.stepDown()
            return
        super().mousePressEvent(event)

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        super().paintEvent(event)          # frame + text drawn by Qt

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        accent  = QColor(THEME['ACCENT'])
        border  = QColor(THEME['BORDER'])
        surface = QColor(THEME['SURFACE'])
        fg      = QColor(THEME['TEXT'])

        up_r   = self._up_rect()
        down_r = self._down_rect()

        # ── button backgrounds ────────────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        for rect, hovered in ((up_r, self._up_hovered),
                               (down_r, self._down_hovered)):
            fill = QPainterPath()
            fill.addRoundedRect(
                float(rect.x()), float(rect.y()),
                float(rect.width()), float(rect.height()), 2, 2)
            p.fillPath(fill, QBrush(accent if hovered else surface))

        # ── separator lines ───────────────────────────────────────────────
        p.setPen(border)
        bx  = self._btn_x()
        cr  = self.contentsRect()
        mid = cr.top() + cr.height() // 2
        p.drawLine(bx, cr.top(),  bx, cr.bottom())   # vertical divider
        p.drawLine(bx, mid, cr.right(), mid)           # horizontal mid

        # ── arrow triangles ───────────────────────────────────────────────
        def draw_triangle(cx: float, cy: float, up: bool) -> None:
            aw = self._ARROW_W / 2.0
            ah = self._ARROW_H / 2.0
            tri = QPainterPath()
            if up:
                tri.moveTo(cx,      cy - ah)
                tri.lineTo(cx + aw, cy + ah)
                tri.lineTo(cx - aw, cy + ah)
            else:
                tri.moveTo(cx - aw, cy - ah)
                tri.lineTo(cx + aw, cy - ah)
                tri.lineTo(cx,      cy + ah)
            tri.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            # Arrow is dark on accent background, light otherwise
            any_hovered = self._up_hovered or self._down_hovered
            arrow_col   = QColor(THEME['BG']) if any_hovered else fg
            p.fillPath(tri, QBrush(arrow_col))

        draw_triangle(
            up_r.x()   + up_r.width()   / 2.0,
            up_r.y()   + up_r.height()  / 2.0,
            up=True)
        draw_triangle(
            down_r.x() + down_r.width()  / 2.0,
            down_r.y() + down_r.height() / 2.0,
            up=False)

        p.end()

class QRCodeDialog(QDialog):
    """
    Dialog d'affichage du QR Code — style uniforme FlavorSelectorDialog.

    Frameless + fond translucide + container arrondi thème Catppuccin Mocha.
    Actions : Copy to Clipboard | Save as PNG | Print | ✕ Close.
    """

    def __init__(
        self,
        bean_name: str,
        pixmap: QPixmap,
        pil_img,                       # PIL.Image pour save/print
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pixmap  = pixmap
        self._pil_img = pil_img

        # ── Root layout avec marge pour l'ombre / border ────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Conteneur principal ──────────────────────────────────────────────
        container = QFrame()
        container.setObjectName("QRContainer")
        container.setStyleSheet(f"""
            #QRContainer {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 15px;
            }}
        """)
        root.addWidget(container)

        inner = QVBoxLayout(container)
        inner.setContentsMargins(20, 10, 20, 16)
        inner.setSpacing(10)

        # ── Header ───────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 4, 0, 6)

        title = QLabel(f"QR CODE — {bean_name.upper()}")
        title.setStyleSheet(
            f"color:{THEME['ACCENT']};font-size:14px;font-weight:800;"
            f"border:none;background:transparent;"
        )

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']};
                color: {THEME['CRITICAL']};
                border-radius: 15px;
                border: 1px solid {THEME['CRITICAL']};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {THEME['CRITICAL']};
                color: {THEME['BG']};
            }}
        """)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        inner.addLayout(header)

        # ── QR image ─────────────────────────────────────────────────────────
        qr_label = QLabel()
        # Fond blanc pour le QR (lisibilité des modules noirs)
        scaled = pixmap.scaled(
            280, 280,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        qr_label.setPixmap(scaled)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setStyleSheet(
            "background: white; border-radius: 8px; padding: 8px; border: none;"
        )
        inner.addWidget(qr_label)

        # ── Footer — boutons d'action ─────────────────────────────────────────
        # Copy and Save are neutral buttons and take the base sheet as it is.
        # Print is the one action the window exists for, so it says `primary`.
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self._btn_copy = QPushButton(
            QApplication.translate("tilauscope_beancave", "Copy to Clipboard")
        )
        self._btn_copy.clicked.connect(self._copy_to_clipboard)

        btn_save = QPushButton(
            QApplication.translate("tilauscope_beancave", "Save as PNG")
        )
        btn_save.clicked.connect(self._save_as_png)

        btn_print = QPushButton(
            QApplication.translate("tilauscope_beancave", "Print")
        )
        btn_print.setProperty('variant', 'primary')
        btn_print.clicked.connect(self._print)

        footer.addWidget(self._btn_copy)
        footer.addWidget(btn_save)
        footer.addStretch()
        footer.addWidget(btn_print)
        inner.addLayout(footer)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setPixmap(self._pixmap)
        self._btn_copy.setText(
            QApplication.translate("tilauscope_beancave", "Copied! ✓")
        )
        QTimer.singleShot(1500, lambda: self._btn_copy.setText(
            QApplication.translate("tilauscope_beancave", "Copy to Clipboard")
        ))

    def _save_as_png(self) -> None:
        from pathlib import Path
        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        # Extraire le nom du bean depuis le titre
        title_text = self.findChild(QLabel).text() if self.findChild(QLabel) else "QR"
        bean_name = title_text.replace("QR CODE — ", "").replace(" ", "_").lower()
        default_path = str(Path(downloads_dir) / f"QR_{bean_name}.png")

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            QApplication.translate("tilauscope_beancave", "Save QR Code"),
            default_path,
            QApplication.translate("tilauscope_beancave", "PNG Files (*.png);;All Files (*)")
        )
        if file_path:
            # PIL infers the format from the extension: a name typed
            # without one raised out of the click handler, leaving neither a file
            # nor any message on screen.
            if not Path(file_path).suffix:
                file_path += ".png"
            try:
                self._pil_img.save(file_path)
            except Exception as exc:  # noqa: BLE001
                _logd.error(f"QR code save failed: {exc}")
                show_styled_message(
                    self,
                    QApplication.translate("tilauscope_beancave", "Save Error"),
                    QApplication.translate("tilauscope_beancave",
                        "The QR code could not be saved:") + f"\n{exc}",
                    QMessageBox.Icon.Warning)

    def _print(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        print_dialog = QPrintDialog(printer, self)
        if print_dialog.exec() == QPrintDialog.DialogCode.Accepted:
            from PIL.ImageQt import ImageQt as _IQt
            painter = QPainter(printer)
            q_img   = _IQt(self._pil_img)
            rect    = painter.viewport()
            size    = q_img.size()
            size.scale(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.setViewport(rect.x(), rect.y(), size.width(), size.height())
            painter.setWindow(q_img.rect())
            painter.drawImage(0, 0, q_img)
            painter.end()

class _DensityFloatWindow(QDialog):
    """Always-on-top card showing live computed density from scale1.

    Click the density value -> density_picked(float) is emitted.
    Net weight and TARE button are secondary controls.
    """

    density_picked = pyqtSignal(float)
    tare_requested = pyqtSignal()

    _VOLUMES_ML: tuple[int, ...] = (50, 100, 200, 250, 500)
    _DEFAULT_VOLUME_ML: int = 100

    def __init__(self, parent: QWidget) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._net_g: float | None = None
        self._volume_ml: int = self._DEFAULT_VOLUME_ML
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("densityCard")
        card.setStyleSheet(f"""
            QFrame#densityCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 16px;
            }}
            {tooltip_qss()}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)
        cl.setSpacing(4)

        header = QLabel(QApplication.translate("tilauscope_beancave", "🧪  DENSITY"))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setProperty('variant', 'eyebrow')

        self._density_lbl = QLabel("––– g/l")
        self._density_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._density_lbl.setProperty('variant', 'readout')
        self._density_lbl.setStyleSheet(f"color: {THEME['ACCENT']};")
        self._density_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._density_lbl.setToolTip(
            f"<span style='font-size:10px;'>"
            f"{QApplication.translate('tilauscope_beancave', 'Click to transfer density')}</span>"
        )
        self._density_lbl.mousePressEvent = self._on_density_clicked  # type: ignore[method-assign]

        hint = QLabel(QApplication.translate("tilauscope_beancave", "tap to use"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:10px;"
            f"background:transparent;"
        )

        # volume selector (fixed list)
        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        vol_lbl = QLabel(QApplication.translate("tilauscope_beancave", "volume"))
        vol_lbl.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:11px;"
            f"background:transparent;"
        )
        self._vol_combo = QComboBox()
        for v in self._VOLUMES_ML:
            self._vol_combo.addItem(f"{v} ml", v)
        self._vol_combo.setCurrentIndex(self._VOLUMES_ML.index(self._DEFAULT_VOLUME_ML))
        self._vol_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._vol_combo.setMinimumWidth(96)
        self._vol_combo.view().setMinimumWidth(96)  # popup must fit "500 ml"
        self._vol_combo.currentIndexChanged.connect(self._on_volume_changed)
        vol_row.addStretch(1)
        vol_row.addWidget(vol_lbl)
        vol_row.addWidget(self._vol_combo)
        vol_row.addStretch(1)

        # secondary row: net weight + TARE
        sec_row = QHBoxLayout()
        sec_row.setSpacing(8)
        self._net_lbl = QLabel(QApplication.translate("tilauscope_beancave", "net –– g"))
        self._net_lbl.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:12px;"
            f"background:transparent;"
        )
        self._tare_btn = QPushButton(QApplication.translate("tilauscope_beancave", "TARE"))
        self._tare_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tare_btn.setStyleSheet(f"""
            QPushButton {{
                background-color:{THEME['BG']};
                color:{THEME['SUBTEXT']};
                border:1px solid {THEME['BORDER']};
                border-radius:8px;
                padding:3px 12px;
                font-size:11px;letter-spacing:1px;
                }}
            QPushButton:hover {{ border-color:{THEME['ACCENT']}; }}
        """)
        self._tare_btn.clicked.connect(self.tare_requested.emit)
        sec_row.addWidget(self._net_lbl)
        sec_row.addStretch(1)
        sec_row.addWidget(self._tare_btn)

        cl.addWidget(header)
        cl.addWidget(self._density_lbl)
        cl.addWidget(hint)
        cl.addLayout(vol_row)
        cl.addLayout(sec_row)
        outer.addWidget(card)
        self.adjustSize()

    # ── Public slots ─────────────────────────────────────────────────────────
    @pyqtSlot(int)
    def update_weight(self, weight: int) -> None:
        self._net_g = float(weight)
        self._net_lbl.setText(
            QApplication.translate("tilauscope_beancave", "net {0} g").format(weight)
        )
        self._recompute()

    @pyqtSlot()
    def scale_disconnected(self) -> None:
        self._net_g = None
        self._net_lbl.setText(QApplication.translate("tilauscope_beancave", "net –– g"))
        self._density_lbl.setText("––– g/l")

    # ── Interaction ────────────────────────────────────────────────────────
    def _on_volume_changed(self, _idx: int) -> None:
        self._volume_ml = int(self._vol_combo.currentData())
        self._recompute()

    def _recompute(self) -> None:
        if self._net_g is None or self._net_g <= 0.0 or self._volume_ml <= 0:
            self._density_lbl.setText("––– g/l")
            return
        density = round(self._net_g * 1000.0 / self._volume_ml)
        self._density_lbl.setText(f"{density} g/l")

    def _on_density_clicked(self, _event) -> None:  # noqa: ANN001
        if self._net_g is None or self._net_g <= 0.0 or self._volume_ml <= 0:
            return
        self.density_picked.emit(self._net_g * 1000.0 / self._volume_ml)

class NiimbotStatusOverlay(QWidget):
    """
    Statut imprimante Niimbot — widget inline dans l'action_bar_layout du viewer.
    Pas de fenêtre flottante, pas de z-order, pas d'overlay : juste un QWidget
    avec icône + label, inséré directement dans le layout de la barre de boutons.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(5)

        self.icon_label = QLabel("🖨️")
        self.icon_label.setStyleSheet("font-size: 13px; background: transparent; border: none;")

        self.status_label = QLabel(QApplication.translate("tilauscope_beancave", "Printer: Disconnected"))
        self._apply_style(THEME['CRITICAL'])

        lay.addWidget(self.icon_label)
        lay.addWidget(self.status_label)

        self.setStyleSheet(f"""
            NiimbotStatusOverlay {{
                background-color: {THEME['SURFACE']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
            }}
        """)

    def _apply_style(self, color_hex: str):
        self.status_label.setStyleSheet(f"""
            color: {color_hex};
            font-size: 11px;
            font-weight: bold;
            background: transparent;
            border: none;
        """)

    def update_status(self, text: str, color_hex: str):
        self.status_label.setText(text)
        self._apply_style(color_hex)

class AwReadingOverlay(QFrame):
    def __init__(self, parent=None):
        # Using WindowStaysOnTopHint and FramelessWindowHint to match Beancave's custom dialog style
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint |
                                 Qt.WindowType.FramelessWindowHint |
                                 Qt.WindowType.Tool)

        # Match Beancave's transparency and focus behavior
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Import THEME from your types (assuming it's available in scope)
        from tilauscope.tilauscope_types import THEME

        # Main Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 10, 15, 10)

        # Inner container for styling (Matches #MainContainer in beancave.py)
        self.container = QFrame()
        self.container.setObjectName("OverlayContainer")
        self.container.setStyleSheet(f"""
            #OverlayContainer {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 12px;
            }}
        """)

        inner_layout = QVBoxLayout(self.container)

        # Header text (Accent color, JetBrains Mono)
        self.title_label = QLabel(QApplication.translate("tilauscope_beancave", "WATER ACTIVITY"))
        self.title_label.setProperty('variant', 'eyebrow')
        self.title_label.setStyleSheet(f"color: {THEME['ACCENT']};")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Value display
        self.value_label = QLabel("0.000")
        self.value_label.setProperty('variant', 'readout')
        self.value_label.setStyleSheet(f"color: {THEME['TEXT']};")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        inner_layout.addWidget(self.title_label)
        inner_layout.addWidget(self.value_label)
        self.layout.addWidget(self.container)

        # Animation setup
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(300)

    def update_value(self, value):
        """Updates label and triggers a small 'pulse' animation."""
        self.value_label.setText(str(value))
        self.adjustSize()

    def show_fancy(self):
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(0.95) # Slightly transparent
            self.fade_anim.start()

    def hide_fancy(self):
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self.hide)
        self.fade_anim.start()

class URLInputDialog(QDialog):
    """Frameless, THEME-styled prompt for the supplier URL to AI-parse.

    Styled to match TilauScope's dark THEME (frameless + translucent), same
    pattern as AddBeanChoiceDialog / QRCodeDialog.
    """

    def __init__(self, parent=None):
        super().__init__(parent,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(400)

        # ── Outer shell (gives the translucent rounded frame) ──────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("URLInputCard")
        card.setStyleSheet(f"""
            #URLInputCard {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
        """)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ── Icon + title ─────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        icon_lbl = QLabel("✨")
        icon_lbl.setStyleSheet("font-size: 26px;")
        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Search for bean data using AI"))
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-size   : 14px;
            font-weight : 800;
            letter-spacing: 1px;
        """)
        title_row.addWidget(icon_lbl)
        title_row.addWidget(title_lbl, 1)
        root.addLayout(title_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {THEME['BORDER']};")
        root.addWidget(sep)

        _input_style = f"""
            QLineEdit {{
                background      : {THEME['SURFACE']};
                color            : {THEME['TEXT']};
                border           : 1px solid {THEME['BORDER']};
                border-radius    : 7px;
                padding          : 7px 10px;
                    font-size        : 11px;
            }}
            QLineEdit:focus {{
                border: 1px solid {THEME['ACCENT']};
            }}
        """
        self.url_input = QLineEdit()
        self.url_input.setStyleSheet(_input_style)
        self.url_input.setPlaceholderText(QApplication.translate("tilauscope_beancave","Enter URL of supplier here..."))
        self.url_input.setMinimumHeight(30)

        # Button: Paste URL
        self.btn_paste = QPushButton(QApplication.translate("tilauscope_beancave","Paste URL"))
        self.btn_paste.setProperty('variant', 'outline')
        self.btn_paste.clicked.connect(self.paste_url)

        # Connection for dynamic update when clipboard changes
        QGuiApplication.clipboard().dataChanged.connect(self.update_paste_button_state)

        # Set initial state
        self.update_paste_button_state()

        # Boutons Validation
        self.btn_ok = QPushButton(QApplication.translate("tilauscope_beancave","Extract data"))
        self.btn_ok.setProperty('variant', 'primary')
        self.btn_ok.setMinimumHeight(34)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton(QApplication.translate("Button","Cancel"))
        self.btn_cancel.setProperty('variant', 'ghost')
        self.btn_cancel.clicked.connect(self.reject)

        root.addWidget(self.url_input)
        root.addWidget(self.btn_paste)

        btns_layout = QHBoxLayout()
        btns_layout.addWidget(self.btn_ok)
        btns_layout.addStretch(1)
        btns_layout.addWidget(self.btn_cancel)
        root.addLayout(btns_layout)

    def update_paste_button_state(self):
        """Checks clipboard content and enables/disables the paste button accordingly."""
        clipboard_text = QGuiApplication.clipboard().text()
        # Enable only if the clipboard contains a URL starting with http
        self.btn_paste.setEnabled(clipboard_text.startswith("http"))

    def paste_url(self):
        self.url_input.setText(QGuiApplication.clipboard().text()) # type: ignore

    def get_url(self):
        return self.url_input.text()
