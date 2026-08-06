## TILAU ##
# Frameless / Catppuccin styling for the main Artisan window.
#
# First-iteration scope (deliberately cautious): only the native title bar is
# replaced by a custom draggable one with min/max/close buttons. Native
# resize borders are left untouched (Qt.WindowType.FramelessWindowHint is NOT
# used) so OS-level resize/snap/tiling behaviour is preserved while this is
# being validated on both macOS and Windows.

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from tilauscope.tilauscope_types import THEME

_TITLE_BAR_HEIGHT = 34


class _TilauTitleBar(QWidget):
    def __init__(self, aw: QMainWindow) -> None:
        super().__init__(aw)
        self._aw = aw
        self._drag_offset: QPoint | None = None
        self.setObjectName('TilauTitleBar')
        self.setFixedHeight(_TITLE_BAR_HEIGHT)
        self.setStyleSheet(f"""
            #TilauTitleBar {{ background-color: {THEME['SURFACE']}; }}
            #TilauTitleBar QLabel {{ color: {THEME['TEXT']}; font-weight: 600; background: transparent; }}
            #TilauTitleBar QPushButton {{
                background: transparent; color: {THEME['TEXT']}; border: none;
                font-size: 13px; min-width: 40px; min-height: {_TITLE_BAR_HEIGHT}px;
            }}
            #TilauTitleBar QPushButton:hover {{ background-color: {THEME['BORDER']}; }}
            #TilauTitleBar QPushButton#closeButton:hover {{ background-color: {THEME['CRITICAL']}; }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)

        self._title_label = QLabel(aw.windowTitle())
        layout.addWidget(self._title_label)
        layout.addStretch()

        btn_min = QPushButton('–')
        btn_min.setToolTip('Minimize')
        btn_min.clicked.connect(aw.showMinimized)

        btn_max = QPushButton('□')
        btn_max.setToolTip('Maximize / Restore')
        btn_max.clicked.connect(self._toggle_maximized)

        btn_close = QPushButton('✕')
        btn_close.setObjectName('closeButton')
        btn_close.setToolTip('Close')
        btn_close.clicked.connect(aw.close)

        for button in (btn_min, btn_max, btn_close):
            layout.addWidget(button)

    def _toggle_maximized(self) -> None:
        if self._aw.isMaximized():
            self._aw.showNormal()
        else:
            self._aw.showMaximized()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._aw.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and bool(event.buttons() & Qt.MouseButton.LeftButton):
            self._aw.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._toggle_maximized()


# Global "chrome" QSS: deliberately scoped to widget classes that do not already
# carry their own inline stylesheet in main.py (event buttons, LCDs, sliders, ...
# are left untouched to avoid clobbering styles tuned over years).
#
# Split in two and applied to two different widgets, NOT to `aw` itself:
# main.py (~line 6598) already calls aw.setStyleSheet(...) dynamically for the
# canvas background color on every roast/theme change, which would otherwise
# wipe out anything we set at the aw level (setStyleSheet replaces, it doesn't merge).
_MENU_QSS = f"""
    QMenuBar {{ background-color: {THEME['SURFACE']}; color: {THEME['TEXT']}; }}
    QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
    QMenuBar::item:selected {{ background-color: {THEME['BORDER']}; }}
    QMenu {{ background-color: {THEME['SURFACE']}; color: {THEME['TEXT']}; border: 1px solid {THEME['BORDER']}; }}
    QMenu::item {{ padding: 4px 20px; }}
    QMenu::item:selected {{ background-color: {THEME['BORDER']}; }}
    QMenu::separator {{ height: 1px; background-color: {THEME['BORDER']}; margin: 4px 0; }}
"""

_CENTRAL_QSS = f"""
    QToolTip {{ background-color: {THEME['SURFACE']}; color: {THEME['TEXT']}; border: 1px solid {THEME['BORDER']}; }}
    QScrollBar:vertical {{ background-color: {THEME['BG']}; width: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background-color: {THEME['BORDER']}; border-radius: 4px; min-height: 20px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background-color: {THEME['BG']}; height: 12px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background-color: {THEME['BORDER']}; border-radius: 4px; min-width: 20px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def take_body(aw: QMainWindow) -> QWidget:
    """Detach and return the wrapped central content (below the custom title bar),
    leaving the title bar itself in place. Used when TilauScope embeds the Artisan
    graph in its own window — without this, TilauScope would grab centralWidget()
    (the title bar + graph wrapper) instead of just the graph.
    """
    wrapper = aw.centralWidget()
    body = aw.main_widget
    if wrapper is not None and wrapper.layout() is not None:
        wrapper.layout().removeWidget(body)
    return body


def give_body(aw: QMainWindow, body: QWidget) -> None:
    """Re-attach content previously detached via take_body(), restoring it below
    the custom title bar.
    """
    wrapper = aw.centralWidget()
    if wrapper is not None and wrapper.layout() is not None:
        wrapper.layout().addWidget(body)
    else:
        aw.setCentralWidget(body)
    body.show()


def apply_frameless_style(aw: QMainWindow) -> None:
    """Replace the native title bar of the main Artisan window with a Catppuccin-themed custom one,
    and extend the Catppuccin theme to the window chrome (menu bar, menus, tooltips, scrollbars).

    Native resize borders are intentionally kept (no FramelessWindowHint) for this first,
    cautious test iteration on both macOS and Windows. Widgets that already carry their own
    inline stylesheet (event buttons, LCDs, sliders, ...) are deliberately left untouched.
    """
    was_visible = aw.isVisible()

    aw.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.CustomizeWindowHint)

    menu_bar = aw.menuBar()
    if menu_bar is not None:
        menu_bar.setStyleSheet(_MENU_QSS)

    old_central = aw.centralWidget()
    wrapper = QWidget()
    wrapper.setStyleSheet(_CENTRAL_QSS)
    outer_layout = QVBoxLayout(wrapper)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)
    outer_layout.addWidget(_TilauTitleBar(aw))
    if old_central is not None:
        outer_layout.addWidget(old_central)
    aw.setCentralWidget(wrapper)

    if was_visible:
        aw.show()
