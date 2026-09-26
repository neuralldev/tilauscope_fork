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

"""First-run configuration assistant for TilauScope: a 6-step wizard (you, roaster,
connection, hardware, folders, hand-off to BeanCave) shown once and replayable from the
menu. The roaster's machine setup comes from roasters.json (see machine_setup). Settings
apply atomically only when the user validates the last step; skipping never touches
settings."""

import logging
import os
from typing import Final, TYPE_CHECKING

from PyQt6.QtCore import QT_TRANSLATE_NOOP, QSettings, Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from artisanlib.util import getResourcePath
from tilauscope.tilauscope_types import _IS_MACOS, THEME, show_styled_message

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

_log: Final[logging.Logger] = logging.getLogger(__name__)

# ── Persistence ────────────────────────────────────────────────────────────
_DONE_KEY: Final[str] = "tilauscope/onboarding_done"

# ── Catppuccin Mocha palette (matches whats_new / displayscope) ────────────
# Derived from the shared THEME table; local names kept so the ~60 references need no churn.
_T: Final[dict] = {
    "BG":      THEME["BG"],
    "SURFACE": THEME["SURFACE"],
    "OVERLAY": THEME["BORDER"],
    "OVER1":   THEME["SURFACE1"],
    "OVER2":   THEME["SURFACE2"],
    "TEXT":    THEME["TEXT"],
    "SUBTEXT": THEME["SUBTEXT"],
    "MUTED":   THEME["OVERLAY0"],
    "ACCENT":  THEME["ACCENT"],
    "SKY":     THEME["SAPPHIRE"],   # historic name: this is Sapphire
    "GREEN":   THEME["SUCCESS"],
    "PEACH":   THEME["WARNING"],
    "YELLOW":  THEME["YELLOW"],
    "MAUVE":   THEME["MAUVE"],
    "RED":     THEME["CRITICAL"],
}


# Link kinds of roasters.json artisan_setups, as the wizard names them.
_LINK_LABELS: Final[dict[str, str]] = {
    "usb":       QT_TRANSLATE_NOOP("tilauscope_onboarding", "USB cable"),
    "bluetooth": QT_TRANSLATE_NOOP("tilauscope_onboarding", "Bluetooth"),
    "network":   QT_TRANSLATE_NOOP("tilauscope_onboarding", "Network"),
    "probes":    QT_TRANSLATE_NOOP("tilauscope_onboarding", "Probe kit"),
}
_HEATING_LABELS: Final[dict[str, str]] = {
    "gas":       QT_TRANSLATE_NOOP("tilauscope_onboarding", "Gas"),
    "electric":  QT_TRANSLATE_NOOP("tilauscope_onboarding", "Electric"),
    "infrared":  QT_TRANSLATE_NOOP("tilauscope_onboarding", "Infrared"),
    "induction": QT_TRANSLATE_NOOP("tilauscope_onboarding", "Induction"),
    "hybrid":    QT_TRANSLATE_NOOP("tilauscope_onboarding", "Hybrid"),
    "wood":      QT_TRANSLATE_NOOP("tilauscope_onboarding", "Wood"),
    "coal":      QT_TRANSLATE_NOOP("tilauscope_onboarding", "Coal"),
}
# Artisan's order of the milestone buttons (qmc.buttonactions), as the recap abbreviates them.
_MILESTONES: Final[tuple[str, ...]] = (
    "CHARGE", "DRY", "FC", "FC END", "SC", "SC END", "DROP", "COOL")

# Curated theme shipped in the repo (generated from the reference profile).
_THEME_REL: Final[tuple[str, ...]] = ("Themes", "TilauScope", "Catppuccin.athm")


from tilauscope import machine_setup
from tilauscope.theme_qss import apply_tilau_theme, tint


def _theme_path() -> str:
    return os.path.join(getResourcePath(), *_THEME_REL)


# ── Known Artisan BLE device signatures (identification only) ──────────────
# Sourced from each device port's add_device_description() call in artisanlib.
# Tuple is (label, name_prefix, service_uuid|None); matched via ble_port.name_match
# (prefix hit or service UUID). USB/serial roasters never appear here; our own
# peripherals have dedicated rows above and are filtered out of this section.
_KNOWN_BLE_SIGNATURES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("Santoker (Cube)",        "SANTOKER",              "6e400001-b5a3-f393-e0a9-e50e24dcca9e"),
    ("Santoker R",             "Santoker",              "0000fff0-0000-1000-8000-00805f9b34fb"),
    ("IKAWA",                  "IKAWA",                 "c92a6046-6c8d-4116-9d1d-d20a8f6a245f"),
    ("ColorTrack",             "ColorTrack",            "713d0000-503e-4c75-ba94-3148f18d941e"),
    ("BlueDOT",                "BlueDOT",               None),
    ("Skywalker (Skycommand)", "ESP32_Skycommand_BLE",  "6e400001-b5a3-f393-e0a9-e50e24dcca9e"),
    ("Lebrew RoastSeeNEXT",    "RoastSeeNEXT",          "000000bb-0000-1000-8000-00805f9b34fb"),
)


def _ble_signature_match(bd, ad, prefix: str, service_uuid: str | None) -> bool:
    """True if (bd, ad) matches a known signature — name prefix OR service UUID."""
    try:
        name = getattr(bd, "name", None) or ""
        local = getattr(ad, "local_name", None) or ""
        if prefix:
            pl = prefix.casefold()
            if name.casefold().startswith(pl) or local.casefold().startswith(pl):
                return True
        if service_uuid:
            uuids = [u.casefold() for u in (getattr(ad, "service_uuids", None) or [])]
            if service_uuid.casefold() in uuids:
                return True
    except Exception:  # pylint: disable=broad-except
        return False
    return False


# ═══════════════════════════════════════════════════════════════════════════
class OnboardingWizard(QDialog):
    """The 6-step first-run configuration dialog."""

    # Translated where the stepper is built; declared here for the extractor.
    STEPS: Final[tuple[str, ...]] = (
        QT_TRANSLATE_NOOP("tilauscope_onboarding", "You"),
        QT_TRANSLATE_NOOP("tilauscope_onboarding", "Roaster"),
        QT_TRANSLATE_NOOP("tilauscope_onboarding", "Connection"),
        QT_TRANSLATE_NOOP("tilauscope_onboarding", "Hardware"),
        QT_TRANSLATE_NOOP("tilauscope_onboarding", "Folders"),
        QT_TRANSLATE_NOOP("tilauscope_onboarding", "First bean"))

    def __init__(self, beancave: QWidget, aw: "ApplicationWindow") -> None:
        super().__init__(
            beancave,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        # ground=False: the grounded base would paint the rectangle opaque and
        # square off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        if _IS_MACOS:
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        self._beancave = beancave
        self._aw = aw
        self._drag_pos = None
        self._index = 0

        # collected choices
        self._unit: str = "C"
        self._operator: str = getattr(getattr(aw, "qmc", None), "operator_setup", "") or ""
        self._roaster: str = ""
        self._setups: list = []              # roasters.json artisan_setups of self._roaster
        self._setup_index: int = 0
        self._setup_chosen: bool = False     # the operator picked the link: detection stops choosing
        self._port: str | None = None
        self._host: str = ""
        self._ble_seen: set[str] = set()     # BLE name prefixes heard nearby
        _s = QSettings()
        self._alog_dir: str = _s.value("alogDirectory", "", str) or ""
        self._beancave_dir: str = _s.value("beancaveDirectory", self._alog_dir, str) or ""

        self._scanner_hooked = False
        self._detect_timer = QTimer(self)
        self._detect_timer.timeout.connect(self._refresh_detection)

        self._build_ui()
        self._show_step(0)

    # ── UI construction ───────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        card = QFrame()
        card.setObjectName("Card")
        card.setStyleSheet(
            f"#Card {{ background:{_T['BG']}; border:1px solid {_T['OVERLAY']};"
            f" border-radius:16px; }}"
        )
        card.setFixedWidth(720)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_titlebar())
        root.addWidget(self._build_stepper())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_footer())

    def _build_titlebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Bar")
        bar.setFixedHeight(48)
        bar.setStyleSheet(
            f"#Bar {{ background:{_T['SURFACE']}; border-top-left-radius:15px;"
            f" border-top-right-radius:15px; border-bottom:1px solid {_T['OVERLAY']}; }}"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 0, 14, 0)

        icon = QLabel("🌱")
        icon.setStyleSheet("font-size:20px; ")
        title = QLabel(QApplication.translate("tilauscope_onboarding","Welcome — first-time setup"))
        title.setStyleSheet(
            f"color:{_T['TEXT']};"
            f" font-size:14px; font-weight:700; background:transparent;"
        )
        close = QPushButton("✕")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_T['MUTED']}; border:none;"
            f" font-size:14px; border-radius:6px; }}"
            f"QPushButton:hover {{ background:{_T['OVERLAY']}; color:{_T['TEXT']}; }}"
        )
        close.clicked.connect(self._skip)

        row.addWidget(icon)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(close)
        return bar

    def _build_stepper(self) -> QWidget:
        wrap = QFrame()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(26, 18, 26, 4)
        row.setSpacing(0)

        self._bullets: list[QLabel] = []
        self._steplabels: list[QLabel] = []
        for i, name in enumerate(self.STEPS):
            col = QVBoxLayout()
            col.setSpacing(6)
            b = QLabel(str(i + 1))
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b.setFixedSize(32, 32)
            lab = QLabel(QApplication.translate("tilauscope_onboarding", name))
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(lab, 0, Qt.AlignmentFlag.AlignHCenter)
            self._bullets.append(b)
            self._steplabels.append(lab)
            row.addLayout(col)
            if i < len(self.STEPS) - 1:
                bar = QFrame()
                bar.setFixedHeight(2)
                bar.setStyleSheet(f"background:{_T['OVERLAY']};")
                row.addWidget(bar, 1)
        return wrap

    def _build_body(self) -> QWidget:
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_unit())
        self._stack.addWidget(self._page_roaster())
        self._stack.addWidget(self._page_connection())
        self._stack.addWidget(self._page_hardware())
        self._stack.addWidget(self._page_dirs())
        self._stack.addWidget(self._page_finish())
        self._stack.setMinimumHeight(420)
        return self._stack

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setObjectName("Foot")
        foot.setStyleSheet(
            f"#Foot {{ background:{_T['SURFACE']}; border-top:1px solid {_T['OVERLAY']};"
            f" border-bottom-left-radius:15px; border-bottom-right-radius:15px; }}"
        )
        row = QHBoxLayout(foot)
        row.setContentsMargins(26, 16, 26, 20)

        self._skip_btn = QPushButton(QApplication.translate("tilauscope_onboarding","Skip for now"))
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_T['MUTED']}; border:none;"
            f" font-size:13px; }} QPushButton:hover {{ color:{_T['SUBTEXT']}; }}"
        )
        self._skip_btn.clicked.connect(self._skip)

        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet(
            f"color:{_T['MUTED']}; font-size:11px;"
        )
        self._back_btn = QPushButton(QApplication.translate("tilauscope_onboarding","Back"))
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setStyleSheet(self._ghost_style())
        self._back_btn.clicked.connect(lambda: self._go(-1))

        self._next_btn = QPushButton(QApplication.translate("tilauscope_onboarding","Next"))
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setStyleSheet(self._primary_style())
        self._next_btn.clicked.connect(self._on_next)

        row.addWidget(self._skip_btn)
        row.addStretch()
        row.addWidget(self._count_lbl)
        row.addSpacing(10)
        row.addWidget(self._back_btn)
        row.addWidget(self._next_btn)
        return foot

    # ── page 1: you (name + unit) ─────────────────────────────────────────
    def _page_unit(self) -> QWidget:
        page = self._page_base(
            QApplication.translate("tilauscope_onboarding","Who is roasting?"), "")
        lay = page.layout()

        # signature line: borderless field underlined, accent under focus
        sig = QHBoxLayout()
        sig.setSpacing(10)
        pen = QLabel("✎")
        pen.setStyleSheet(f"color:{_T['MUTED']}; font-size:20px; background:transparent;")
        self._operator_edit = QLineEdit(self._operator)
        self._operator_edit.setPlaceholderText(
            QApplication.translate("tilauscope_onboarding","Your name"))
        self._operator_edit.setMaxLength(64)
        self._operator_edit.setStyleSheet(
            f"QLineEdit {{ background:transparent; color:{_T['TEXT']}; border:none;"
            f" border-bottom:2px solid {_T['OVERLAY']}; padding:6px 2px; font-size:22px;"
            f" font-weight:600; }}"
            f"QLineEdit:focus {{ border-bottom-color:{_T['ACCENT']}; }}"
        )
        self._operator_edit.textChanged.connect(self._on_operator_changed)
        sig.addWidget(pen)
        sig.addWidget(self._operator_edit, 1)
        lay.addLayout(sig)
        lay.addSpacing(10)

        # live preview of where the name appears
        self._operator_preview = QLabel()
        self._operator_preview.setStyleSheet(
            f"color:{_T['SUBTEXT']}; font-size:13px; background:{_T['SURFACE']};"
            f" border:1px solid {_T['OVERLAY']}; border-radius:14px; padding:8px 16px;"
        )
        lay.addWidget(self._operator_preview, 0, Qt.AlignmentFlag.AlignLeft)
        self._on_operator_changed(self._operator)
        lay.addSpacing(26)

        # unit: compact pills on one line
        seg = QHBoxLayout()
        seg.setSpacing(8)
        unit_lbl = QLabel(QApplication.translate("tilauscope_onboarding","Temperatures in"))
        unit_lbl.setStyleSheet(f"color:{_T['SUBTEXT']}; font-size:14px; background:transparent;")
        seg.addWidget(unit_lbl)
        seg.addSpacing(8)
        self._unit_group = QButtonGroup(self)
        for code, big, small in (("C", "°C", "Celsius"), ("F", "°F", "Fahrenheit")):
            b = QPushButton(f"{big}  {small}")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(self._pill_style())
            b.setChecked(code == "C")
            b.clicked.connect(lambda _=False, c=code: setattr(self, "_unit", c))
            self._unit_group.addButton(b)
            seg.addWidget(b)
        seg.addStretch()
        lay.addLayout(seg)
        lay.addStretch()
        return page

    def _on_operator_changed(self, text: str) -> None:
        self._operator = text.strip()
        sample = QApplication.translate("tilauscope_onboarding","Ethiopia Guji · #142")
        if self._operator:
            sample += " · " + QApplication.translate(
                "tilauscope_onboarding","roasted by {0}").format(self._operator)
        self._operator_preview.setText("📄  " + sample)

    # ── page 2: roaster ───────────────────────────────────────────────────
    def _page_roaster(self) -> QWidget:
        page = self._page_base(
            QApplication.translate("tilauscope_onboarding","Which roaster do you use?"),
            QApplication.translate("tilauscope_onboarding","It sets the roast plan, and how TilauScope reads and drives the machine."),
        )
        lay = page.layout()
        search = QLineEdit()
        search.setPlaceholderText("⌕  " + QApplication.translate("tilauscope_onboarding","Search roasters"))
        search.setClearButtonEnabled(True)
        search.setStyleSheet(
            f"QLineEdit {{ background:{_T['SURFACE']}; color:{_T['TEXT']}; border:1px solid {_T['OVERLAY']};"
            f" border-radius:9px; padding:7px 10px; font-size:13px; }}"
            f"QLineEdit:focus {{ border-color:{_T['ACCENT']}; }}"
        )
        lay.addWidget(search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border:none; background:transparent; }}"
            f"QScrollBar:vertical {{ background:transparent; width:8px; }}"
            f"QScrollBar::handle:vertical {{ background:{_T['OVER1']}; border-radius:4px; }}"
        )
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(6)

        from tilauscope.roasters import RoasterManager
        manager = RoasterManager()
        self._roaster_group = QButtonGroup(self)
        self._roaster_cards: list[tuple[str, QPushButton]] = []
        names = self._roaster_names()
        current = (getattr(self._aw, "tilau_roaster", "")
                   or QSettings().value("RoastPlan/RoasterModel", "", str) or "")
        default_i = next(
            (i for i, n in enumerate(names) if n == current),
            next((i for i, n in enumerate(names)
                  if "cyberroaster" in n.lower() or "skywalker v2" in n.lower()), 0),
        )
        for i, name in enumerate(names):
            card = self._roaster_card(name, manager.get_by_display_name(name))
            card.setChecked(i == default_i)
            card.toggled.connect(lambda on, n=name: self._set_roaster(n) if on else None)
            self._roaster_group.addButton(card)
            self._roaster_cards.append((name, card))
            col.addWidget(card)
        col.addStretch()
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)
        search.textChanged.connect(self._filter_roasters)

        g = QLabel(QApplication.translate("tilauscope_onboarding","From this roaster").upper())
        g.setStyleSheet(self._group_style())
        lay.addWidget(g)
        facts = QHBoxLayout()
        facts.setSpacing(8)
        self._fact_labels: list[tuple[QLabel, QLabel]] = []
        for caption in (QApplication.translate("tilauscope_onboarding","Capacity"),
                        QApplication.translate("tilauscope_onboarding","Heating"),
                        QApplication.translate("tilauscope_onboarding","First batch")):
            tile = QFrame()
            tile.setObjectName("Fact")
            tile.setStyleSheet(
                f"#Fact {{ background:{_T['SURFACE']}; border:1px solid {_T['OVERLAY']}; border-radius:9px; }}")
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(12, 7, 12, 7)
            tl.setSpacing(0)
            cap = QLabel(caption.upper())
            cap.setStyleSheet(f"color:{_T['MUTED']}; font-size:10px; letter-spacing:1px; background:transparent;")
            val = QLabel("—")
            val.setStyleSheet(f"color:{_T['TEXT']}; font-size:14px; font-weight:600; background:transparent;")
            hint = QLabel("")
            hint.setStyleSheet(f"color:{_T['MUTED']}; font-size:11px; background:transparent;")
            tl.addWidget(cap)
            tl.addWidget(val)
            tl.addWidget(hint)
            self._fact_labels.append((val, hint))
            facts.addWidget(tile, 1)
        lay.addLayout(facts)
        if names:
            self._set_roaster(names[default_i])
        return page

    def _roaster_card(self, name: str, roaster) -> QPushButton:
        card = QPushButton()
        card.setCheckable(True)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedHeight(54)
        card.setStyleSheet(
            f"QPushButton {{ background:{_T['SURFACE']}; border:1px solid {_T['OVERLAY']};"
            f" border-radius:10px; text-align:left; }}"
            f"QPushButton:hover {{ border-color:{_T['OVER2']}; }}"
            f"QPushButton:checked {{ border-color:{_T['ACCENT']}; background:{tint('ACCENT', 0.08)}; }}"
        )
        hl = QHBoxLayout(card)
        hl.setContentsMargins(14, 6, 12, 6)
        hl.setSpacing(8)
        box = QVBoxLayout()
        box.setSpacing(1)
        maker = roaster.manufacturer if roaster is not None else ""
        model = roaster.model if roaster is not None else name
        title = QLabel(f"<span style='color:{_T['MUTED']}; font-weight:400;'>{maker}</span>&nbsp; {model}")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(f"color:{_T['TEXT']}; font-size:14px; font-weight:600; background:transparent;")
        meta = QLabel(self._roaster_meta(roaster))
        meta.setStyleSheet(f"color:{_T['MUTED']}; font-size:11px; background:transparent;")
        box.addWidget(title)
        box.addWidget(meta)
        hl.addLayout(box, 1)
        setups = list(roaster.artisan_setups) if roaster is not None else []
        if setups:
            for setup in setups:
                hl.addWidget(self._pill(QApplication.translate("tilauscope_onboarding", _LINK_LABELS.get(setup.link, setup.link)),
                                        "ACCENT" if setup.link == "probes" else "SUCCESS"), 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            hl.addWidget(self._pill(QApplication.translate("tilauscope_onboarding","Manual setup"), None),
                         0, Qt.AlignmentFlag.AlignVCenter)
        for w in card.findChildren(QLabel):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return card

    def _roaster_meta(self, roaster) -> str:
        if roaster is None:
            return ""
        heating = QApplication.translate("tilauscope_onboarding",
                                         _HEATING_LABELS.get(str(roaster.heating_type), str(roaster.heating_type)))
        lo, hi = roaster.batch_capacity_min_g, roaster.batch_capacity_max_g
        size = (QApplication.translate("tilauscope_onboarding","{0}–{1} g").format(lo, hi) if lo
                else QApplication.translate("tilauscope_onboarding","up to {0} g").format(hi))
        return f"{heating} · {size}"

    def _pill(self, text: str, token: str | None) -> QLabel:
        pill = QLabel(text)
        pill.setFixedHeight(22)
        color = THEME[token] if token else _T["SUBTEXT"]
        ground = tint(token, 0.14) if token else _T["OVERLAY"]
        pill.setStyleSheet(
            f"color:{color}; background:{ground}; border-radius:9px; padding:2px 9px;"
            f" font-size:11px; font-weight:600;")
        return pill

    def _filter_roasters(self, text: str) -> None:
        needle = text.strip().casefold()
        for name, card in self._roaster_cards:
            card.setVisible(not needle or needle in name.casefold())

    def _refresh_facts(self) -> None:
        from tilauscope.roasters import RoasterManager
        roaster = RoasterManager().get_by_display_name(self._roaster)
        if roaster is None or not getattr(self, "_fact_labels", None):
            return
        spec = roaster.electrical_specification
        kw = getattr(spec, "max_power_draw_kw", None) if spec is not None else None
        first = roaster.optimal_batch_capacity_g or roaster.batch_capacity_max_g
        values = (
            (f"{roaster.batch_capacity_max_g / 1000:g} kg", QApplication.translate("tilauscope_onboarding","nominal")),
            (QApplication.translate("tilauscope_onboarding",
                                    _HEATING_LABELS.get(str(roaster.heating_type), str(roaster.heating_type))),
             f"{kw:g} kW" if kw else ""),
            (f"{first} g", QApplication.translate("tilauscope_onboarding","sweet spot")),
        )
        for (val, hint), (v, h) in zip(self._fact_labels, values, strict=True):
            val.setText(v)
            hint.setText(h)

    # ── page 3: connection ────────────────────────────────────────────────
    def _page_connection(self) -> QWidget:
        page = self._page_base("", QApplication.translate("tilauscope_onboarding",
            "Plug the roaster in and switch it on. Nothing changes until you finish."))
        lay = page.layout()
        self._conn_title = lay.itemAt(0).widget()
        self._link_bar = QHBoxLayout()
        self._link_bar.setSpacing(6)
        lay.addLayout(self._link_bar)
        lay.addSpacing(6)
        self._conn_body = QVBoxLayout()
        self._conn_body.setSpacing(8)
        lay.addLayout(self._conn_body)
        lay.addStretch()
        return page

    def _current_setup(self):
        if 0 <= self._setup_index < len(self._setups):
            return self._setups[self._setup_index]
        return None

    def _connection_needed(self) -> bool:
        """Whether the Connection step has a question: a link to pick, or a port to choose."""
        if len(self._setups) > 1 or any(s.link == "network" for s in self._setups):
            return True
        setup = self._current_setup()
        if setup is None or setup.link != "usb":
            return False
        path = machine_setup.preset_path(setup)
        if path is None or machine_setup.port_target(path) is None:
            return False
        # only the saved port still plugged in goes unasked: an unknown lone port may be a probe
        return machine_setup.saved_port(self._aw, path) not in {d for d, _ in machine_setup.usb_serial_ports()}

    def _default_setup_index(self) -> int:
        """The link in use now, else a detected Bluetooth one, else the first."""
        for i, setup in enumerate(self._setups):
            path = machine_setup.preset_path(setup)
            if path is not None and machine_setup.link_in_use(self._aw, path):
                return i
        for i, setup in enumerate(self._setups):
            if setup.ble_prefix and setup.ble_prefix in self._ble_seen:
                return i
        return 0

    def _choose_setup(self, index: int) -> None:
        if index != self._setup_index:
            self._port = None
            self._host = ""
        self._setup_index = index
        self._setup_chosen = True
        self._fill_connection()

    def _fill_connection(self) -> None:
        self._clear_layout(self._link_bar)
        self._clear_layout(self._conn_body)
        from tilauscope.roasters import RoasterManager
        roaster = RoasterManager().get_by_display_name(self._roaster)
        model = roaster.model if roaster is not None else self._roaster
        self._conn_title.setText(
            QApplication.translate("tilauscope_onboarding","How is your {0} connected?").format(model))
        if len(self._setups) > 1:
            group = self._fresh_group("_link_group")
            for i, setup in enumerate(self._setups):
                b = QPushButton(QApplication.translate("tilauscope_onboarding", _LINK_LABELS.get(setup.link, setup.link)))
                b.setCheckable(True)
                b.setChecked(i == self._setup_index)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(self._pill_style())
                b.clicked.connect(lambda _=False, k=i: self._choose_setup(k))
                group.addButton(b)
                self._link_bar.addWidget(b)
            self._link_bar.addStretch()
        setup = self._current_setup()
        if setup is None:
            return
        if setup.link == "bluetooth":
            self._fill_bluetooth(setup, model)
        elif setup.link == "network":
            self._fill_network(setup)
        elif setup.link == "probes":
            self._fill_probes(setup)
        else:
            self._fill_usb(setup)

    def _fill_usb(self, setup) -> None:
        path = machine_setup.preset_path(setup)
        if path is None or machine_setup.port_target(path) is None:
            self._conn_body.addWidget(self._hint("ACCENT", "ⓘ", QApplication.translate("tilauscope_onboarding",
                "Plug the cable in. TilauScope finds the roaster by itself.")))
            return
        ports = machine_setup.usb_serial_ports()
        if self._port not in {d for d, _ in ports}:
            self._port = None   # unplugged since it was ticked: Finish must not apply it
        saved = machine_setup.saved_port(self._aw, path)
        auto = machine_setup.auto_port(saved, ports)
        if self._port in {d for d, _ in ports} and self._port != auto:
            auto = None   # the operator ticked another port: keep the list and their choice
        if auto is not None:
            self._port = auto
            why = (QApplication.translate("tilauscope_onboarding","The port used last time. TilauScope keeps it.")
                   if auto == saved else
                   QApplication.translate("tilauscope_onboarding","The only USB serial port on this computer. TilauScope will use it."))
            self._conn_body.addWidget(self._hint("SUCCESS", "✓", "<b>{}</b> · {}<br>{}".format(
                QApplication.translate("tilauscope_onboarding","USB port found"), auto, why)))
            return
        if ports:
            g = QLabel(QApplication.translate("tilauscope_onboarding","USB port").upper())
            g.setStyleSheet(self._group_style())
            self._conn_body.addWidget(g)
            group = self._fresh_group("_port_group")
            for device, desc in ports:
                rb = QRadioButton(f"  {device}   {desc}")
                rb.setCursor(Qt.CursorShape.PointingHandCursor)
                rb.setStyleSheet(self._radio_style())
                rb.setChecked(device == self._port)
                rb.toggled.connect(lambda on, d=device: setattr(self, "_port", d) if on else None)
                group.addButton(rb)
                self._conn_body.addWidget(rb)
            self._conn_body.addWidget(self._hint("ACCENT", "ⓘ", QApplication.translate("tilauscope_onboarding",
                "Not listed? Unplug the cable, plug it back in, then scan again.")))
        else:
            self._conn_body.addWidget(self._hint("WARNING", "!", QApplication.translate("tilauscope_onboarding",
                "No USB port found. Plug the cable in, switch the roaster on, then scan again.")))
        rescan = QPushButton("↻  " + QApplication.translate("tilauscope_onboarding","Scan again"))
        rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan.setStyleSheet(self._pair_style())
        rescan.clicked.connect(self._fill_connection)
        self._conn_body.addWidget(rescan, 0, Qt.AlignmentFlag.AlignLeft)

    def _fill_network(self, setup) -> None:
        path = machine_setup.preset_path(setup)
        if not self._host:
            self._host = machine_setup.suggested_host(self._aw, path) if path is not None else ""
        cap = QLabel(QApplication.translate("tilauscope_onboarding","Roaster address (name or IP)"))
        cap.setStyleSheet(f"color:{_T['SUBTEXT']}; font-size:12px; background:transparent;")
        field = QLineEdit(self._host)
        field.setStyleSheet(
            f"QLineEdit {{ background:{_T['SURFACE']}; color:{_T['TEXT']}; border:1px solid {_T['OVERLAY']};"
            f" border-radius:9px; padding:8px 10px; font-size:13px; }}"
            f"QLineEdit:focus {{ border-color:{_T['ACCENT']}; }}"
        )
        field.textChanged.connect(lambda text: setattr(self, "_host", text.strip()))
        self._conn_body.addWidget(cap)
        self._conn_body.addWidget(field)
        self._conn_body.addWidget(self._hint("ACCENT", "ⓘ", QApplication.translate("tilauscope_onboarding",
            "Your roaster and this computer must be on the same network. The address is shown in the roaster's network settings.")))

    def _fill_bluetooth(self, setup, model: str) -> None:
        if not setup.ble_prefix:
            self._conn_body.addWidget(self._hint("ACCENT", "ⓘ", QApplication.translate("tilauscope_onboarding",
                "Switch the roaster on. TilauScope connects to it when monitoring starts.")))
        elif setup.ble_prefix in self._ble_seen:
            self._conn_body.addWidget(self._hint("SUCCESS", "✓", "<b>{}</b><br>{}".format(
                QApplication.translate("tilauscope_onboarding","{0} found nearby").format(model),
                QApplication.translate("tilauscope_onboarding","TilauScope will read and drive it over Bluetooth. No cable needed."))))
        else:
            self._conn_body.addWidget(self._hint("ACCENT", "⌕", QApplication.translate("tilauscope_onboarding",
                "Searching nearby… Switch the roaster on.")))
        if any(s.link == "usb" for s in self._setups):
            near = QApplication.translate("tilauscope_onboarding",
                "Keep the roaster within a few metres of this computer. If the link drops mid-roast, switch to the USB cable.")
        else:
            near = QApplication.translate("tilauscope_onboarding",
                "Keep the roaster within a few metres of this computer.")
        self._conn_body.addWidget(self._hint("WARNING", "!", near))

    def _fill_probes(self, setup) -> None:
        self._conn_body.addWidget(self._hint("ACCENT", "ⓘ", QApplication.translate("tilauscope_onboarding",
            "Temperatures come from the probes fitted to the roaster. Probe settings and formulas come with the kit.")))
        if setup.read_only:
            self._conn_body.addWidget(self._hint("ACCENT", "ⓘ", QApplication.translate("tilauscope_onboarding",
                "This roaster takes no command from TilauScope. It records, and the assistant shows the settings to make by hand.")))

    def _hint(self, token: str, glyph: str, html: str) -> QFrame:
        box = QFrame()
        box.setObjectName("Hint")
        box.setStyleSheet(
            f"#Hint {{ background:{tint(token, 0.08)}; border:1px solid {tint(token, 0.35)}; border-radius:9px; }}")
        hl = QHBoxLayout(box)
        hl.setContentsMargins(12, 9, 12, 9)
        hl.setSpacing(10)
        g = QLabel(glyph)
        g.setStyleSheet(f"color:{THEME[token]}; font-size:14px; background:transparent;")
        t = QLabel(html)
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setWordWrap(True)
        t.setStyleSheet(f"color:{_T['TEXT']}; font-size:12px; background:transparent;")
        hl.addWidget(g, 0, Qt.AlignmentFlag.AlignTop)
        hl.addWidget(t, 1)
        return box

    def _fresh_group(self, attr: str) -> QButtonGroup:
        old = getattr(self, attr, None)
        if old is not None:
            old.deleteLater()
        group = QButtonGroup(self)
        setattr(self, attr, group)
        return group

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()  # deleteLater waits for the event loop; the old row must not show meanwhile
                w.deleteLater()

    # ── page 4: hardware ──────────────────────────────────────────────────
    # Managed-instance attributes that count as "configured" when not None
    # (they are lazily created only once the device is set up).
    _OBJECT_OK: Final[tuple[str, ...]] = ("bleTilauAmbientDevice", "bleRoastSeeAGDevice")

    def _page_hardware(self) -> QWidget:
        page = self._page_base(
            QApplication.translate("tilauscope_onboarding","Connect your hardware"),
            QApplication.translate("tilauscope_onboarding","TilauScope scans for your gear and registers what it finds. "
                "Anything already set up shows as detected. Everything is optional."),
        )
        g = QLabel(QApplication.translate("tilauscope_onboarding","Search & auto-register").upper())
        g.setStyleSheet(self._group_style())
        page.layout().addWidget(g)

        # BLE name prefixes for live scan detection (fall back to literals if a
        # device module can't be imported).
        try:
            from tilauscope.difluid import AIRWAVE_PREFIX
        except Exception:  # pylint: disable=broad-except
            AIRWAVE_PREFIX = "AirWave "
        try:
            from tilauscope.tilauambient import TILAUAMBIENT_PREFIX
        except Exception:  # pylint: disable=broad-except
            TILAUAMBIENT_PREFIX = "TLSCAM"
        try:
            from tilauscope.lebrewroastsee import C1_PREFIX, AG_PREFIX
        except Exception:  # pylint: disable=broad-except
            C1_PREFIX, AG_PREFIX = "RoastSee C1", "RoastSee AquaGauge"

        # Each device: persisted attributes (checked on aw + BeanCave, so a
        # previously configured device shows "detected" on redo) AND a live BLE
        # name prefix (matched against the central scanner's stream, so a
        # present-but-unconfigured device is detected on first run too).
        self._periph: list[tuple[tuple[str, ...], QLabel, str]] = []
        for icon, name, desc, attrs, prefix in (
            ("🌫️", "DiFluid AirWave", QApplication.translate("tilauscope_onboarding","smoke extractor · PID"),
             ("bleAirwaveDeviceName", "bleAirwaveDeviceslist"), AIRWAVE_PREFIX),
            ("⚖️", "Acaia scale", QApplication.translate("tilauscope_onboarding","charge & output weighing"),
             ("scale1_name", "scale1_id", "scale2_name", "scale2_id"), ""),
            ("🌡️", "TilauAmbient", QApplication.translate("tilauscope_onboarding","ESP32 probe · BME280 / I²S mic"),
             ("bleTilauAmbientDeviceslist", "bleTilauAmbientDevice"), TILAUAMBIENT_PREFIX),
            ("💧", "Lebrew AquaGauge", QApplication.translate("tilauscope_onboarding","water activity (Aw)"),
             ("bleRoastSeeAGDeviceName", "bleRoastSeeAGDeviceslist", "bleRoastSeeAGDevice"),
             AG_PREFIX),
            ("🎨", "Lebrew RoastSee C1", QApplication.translate("tilauscope_onboarding","bean colour reader"),
             ("bleRoastSeeDeviceName", "bleRoastSeeDeviceslist"), C1_PREFIX),
        ):
            row, status = self._device_row(icon, name, desc, action=False)
            self._periph.append((attrs, status, prefix))
            page.layout().addWidget(row)

        # ── other known Artisan BLE devices (identification only) ──────────
        # Live-only: whatever advertises nearby and matches an Artisan signature
        # is surfaced by name — no pairing, no linking, no persistence.
        page.layout().addSpacing(8)
        g2 = QLabel(QApplication.translate("tilauscope_onboarding","Other Artisan BLE devices detected").upper())
        g2.setStyleSheet(self._group_style())
        page.layout().addWidget(g2)

        self._known_ble_seen: dict[str, str] = {}
        self._known_ble_host = QFrame()
        self._known_ble_layout = QVBoxLayout(self._known_ble_host)
        self._known_ble_layout.setContentsMargins(0, 0, 0, 0)
        self._known_ble_layout.setSpacing(6)
        self._known_ble_empty: QLabel | None = QLabel(
            QApplication.translate("tilauscope_onboarding","nothing recognised nearby — these are identified, not configured"))
        self._known_ble_empty.setStyleSheet(
            f"color:{_T['MUTED']}; font-size:11px;"
            f" background:transparent; padding:2px 0;"
        )
        self._known_ble_layout.addWidget(self._known_ble_empty)
        page.layout().addWidget(self._known_ble_host)

        page.layout().addStretch()
        return page

    # ── page 5: directories ───────────────────────────────────────────────
    def _page_dirs(self) -> QWidget:
        page = self._page_base(
            QApplication.translate("tilauscope_onboarding","Where should your files live?"),
            QApplication.translate("tilauscope_onboarding","Choose the folders for your BeanCave green-bean database and your "
                "roast logs (.alog). Existing folders are pre-filled."),
        )
        self._dir_path_lbls: dict[str, QLabel] = {}
        for kind, icon, title in (
            ("beancave", "🫘", QApplication.translate("tilauscope_onboarding","BeanCave folder")),
            ("alog", "📈", QApplication.translate("tilauscope_onboarding","Roast logs folder")),
        ):
            page.layout().addWidget(self._dir_row(kind, icon, title))
        page.layout().addStretch()
        self._refresh_dir_labels()
        return page

    def _dir_row(self, kind: str, icon: str, title: str) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"background:{_T['SURFACE']}; border:1px solid {_T['OVERLAY']}; border-radius:11px;"
        )
        hl = QHBoxLayout(row)
        hl.setContentsMargins(14, 11, 14, 11)
        ic = QLabel(icon)
        ic.setStyleSheet("font-size:18px; ")
        box = QVBoxLayout()
        box.setSpacing(2)
        nl = QLabel(title)
        nl.setStyleSheet(f"color:{_T['TEXT']}; font-size:14px; font-weight:600; background:transparent;")
        pl = QLabel("—")
        pl.setStyleSheet(
            f"color:{_T['MUTED']}; font-size:11px;"
            f" background:transparent;"
        )
        self._dir_path_lbls[kind] = pl
        box.addWidget(nl)
        box.addWidget(pl)
        btn = QPushButton(QApplication.translate("tilauscope_onboarding","Choose…"))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(self._pair_style())
        btn.clicked.connect(lambda _=False, k=kind: self._pick_dir(k))
        hl.addWidget(ic)
        hl.addLayout(box, 1)
        hl.addStretch()
        hl.addWidget(btn)
        return row

    def _pick_dir(self, kind: str) -> None:
        bc = self._beancave
        method = "select_beancave_directory" if kind == "beancave" else "select_alog_directory"
        if hasattr(bc, method):
            # reuse BeanCave's tested picker (validity check + save + reload)
            try:
                getattr(bc, method)()
            except Exception as e:  # pylint: disable=broad-except
                _log.exception("directory pick failed: %s", e)
        else:
            key = "beancaveDirectory" if kind == "beancave" else "alogDirectory"
            start = QSettings().value(key, os.path.expanduser("~"), str) or os.path.expanduser("~")
            d = QFileDialog.getExistingDirectory(self, QApplication.translate("tilauscope_onboarding","Select folder"), start)
            if d:
                QSettings().setValue(key, d)
                if kind != "beancave":
                    from tilauscope.alogmanager import directory_changed
                    directory_changed(d)
        self._refresh_dir_labels()

    def _refresh_dir_labels(self) -> None:
        bc = self._beancave
        s = QSettings()
        self._beancave_dir = str(getattr(bc, "beancave_directory", "")
                                 or s.value("beancaveDirectory", "", str) or "")
        self._alog_dir = str(getattr(bc, "alog_directory", "")
                             or s.value("alogDirectory", "", str) or "")
        for kind, val in (("beancave", self._beancave_dir), ("alog", self._alog_dir)):
            lbl = getattr(self, "_dir_path_lbls", {}).get(kind)
            if lbl is not None:
                lbl.setText(val if val else QApplication.translate("tilauscope_onboarding","not set — click Choose…"))
                lbl.setStyleSheet(
                    f"color:{_T['GREEN'] if val else _T['MUTED']}; font-size:11px;"
                    f" background:transparent;"
                )

    # ── page 6: finish ────────────────────────────────────────────────────
    def _page_finish(self) -> QWidget:
        page = self._page_base(
            QApplication.translate("tilauscope_onboarding","Ready to set up"),
            QApplication.translate("tilauscope_onboarding","Here is what Finish changes. Anything under “Kept as it is” stays yours."),
        )
        lay = page.layout()
        cols = QHBoxLayout()
        cols.setSpacing(10)
        self._recap_set = self._recap_card(QApplication.translate("tilauscope_onboarding","Will be set"))
        self._recap_kept = self._recap_card(QApplication.translate("tilauscope_onboarding","Kept as it is"))
        cols.addWidget(self._recap_set[0], 3)
        cols.addWidget(self._recap_kept[0], 2)
        lay.addLayout(cols)
        lay.addSpacing(4)
        lay.addWidget(self._hint("ACCENT", "→", QApplication.translate("tilauscope_onboarding",
            "Next: add your first green coffee, then start a roast.")))
        lay.addStretch()
        return page

    def _recap_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Recap")
        card.setStyleSheet(
            f"#Recap {{ background:{_T['SURFACE']}; border:1px solid {_T['OVERLAY']}; border-radius:10px; }}")
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 10, 14, 12)
        col.setSpacing(5)
        g = QLabel(title.upper())
        g.setStyleSheet(self._group_style())
        col.addWidget(g)
        rows = QVBoxLayout()
        rows.setSpacing(5)
        col.addLayout(rows)
        col.addStretch()
        return card, rows

    def _recap_row(self, rows: QVBoxLayout, key: str, value: str, muted: bool = False) -> None:
        hl = QHBoxLayout()
        hl.setSpacing(10)
        kl = QLabel(key)
        kl.setStyleSheet(f"color:{_T['MUTED']}; font-size:12px; background:transparent;")
        vl = QLabel(value)
        vl.setWordWrap(True)
        vl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vl.setStyleSheet(
            f"color:{_T['MUTED'] if muted else _T['TEXT']}; font-size:12px;"
            f" font-weight:{400 if muted else 600}; background:transparent;")
        hl.addWidget(kl)
        hl.addWidget(vl, 1)
        holder = QWidget()
        holder.setLayout(hl)
        hl.setContentsMargins(0, 0, 0, 0)
        rows.addWidget(holder)

    def _fill_recap(self) -> None:
        rows = self._recap_set[1]
        self._clear_layout(rows)
        if self._operator:
            self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Roasted by"), self._operator)
        self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Units"), "°C" if self._unit == "C" else "°F")
        setup = self._current_setup()
        link = (QApplication.translate("tilauscope_onboarding", _LINK_LABELS.get(setup.link, setup.link))
                if setup is not None else QApplication.translate("tilauscope_onboarding","set up later in Devices…"))
        self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Roaster"), f"{self._roaster or '—'} · {link}")
        if self._port:
            self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Port"), os.path.basename(self._port))
        if setup is not None and setup.link == "network" and self._host:
            self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Address"), self._host)
        path = machine_setup.preset_path(setup) if setup is not None else None
        if path is not None:
            sliders, milestones, buttons = machine_setup.preset_controls(path, list(self._aw.qmc.etypesdefault))
            if setup.read_only:
                self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Sliders"), QApplication.translate("tilauscope_onboarding","none · read-only roaster"))
            elif sliders:
                self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Sliders"), " · ".join(sliders))
            if milestones:
                self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Milestone buttons"),
                                QApplication.translate("tilauscope_onboarding","{0} send commands").format(" · ".join(_MILESTONES[i] for i in milestones if i < len(_MILESTONES))))
            if buttons:
                self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Command buttons"), str(buttons))
        from tilauscope.roasters import RoasterManager
        roaster = RoasterManager().get_by_display_name(self._roaster)
        if roaster is not None:
            heating = QApplication.translate("tilauscope_onboarding", _HEATING_LABELS.get(str(roaster.heating_type), str(roaster.heating_type))).lower()
            self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Capacity"), f"{roaster.batch_capacity_max_g / 1000:g} kg · {heating}")
            self._recap_row(rows, QApplication.translate("tilauscope_onboarding","First batch"), f"{roaster.optimal_batch_capacity_g or roaster.batch_capacity_max_g} g")
        self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Theme and curves"), "Catppuccin")
        if self._beancave_dir:
            self._recap_row(rows, QApplication.translate("tilauscope_onboarding","BeanCave folder"), os.path.basename(self._beancave_dir.rstrip("/\\")) or self._beancave_dir)
        if self._alog_dir:
            self._recap_row(rows, QApplication.translate("tilauscope_onboarding","Roast logs folder"), os.path.basename(self._alog_dir.rstrip("/\\")) or self._alog_dir)

        kept = self._recap_kept[1]
        self._clear_layout(kept)
        for key in (QApplication.translate("tilauscope_onboarding","Your alarms"), QApplication.translate("tilauscope_onboarding","Sounds"), QApplication.translate("tilauscope_onboarding","Batch counter"), QApplication.translate("tilauscope_onboarding","Paired devices")):
            self._recap_row(kept, key, QApplication.translate("tilauscope_onboarding","unchanged"), muted=True)

    # ── small builders ────────────────────────────────────────────────────
    def _page_base(self, title: str, subtitle: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(34, 14, 34, 8)
        lay.setSpacing(6)
        h = QLabel(title)
        h.setWordWrap(True)
        h.setStyleSheet(f"color:{_T['TEXT']}; font-size:22px; font-weight:650; background:transparent;")
        s = QLabel(subtitle)
        s.setWordWrap(True)
        s.setStyleSheet(f"color:{_T['SUBTEXT']}; font-size:13px; background:transparent;")
        lay.addWidget(h)
        lay.addWidget(s)
        lay.addSpacing(14)
        return page

    def _device_row(self, icon: str, name: str, desc: str, action: bool):
        row = QFrame()
        row.setStyleSheet(
            f"background:{_T['SURFACE']}; border:1px solid {_T['OVERLAY']}; border-radius:11px;"
        )
        hl = QHBoxLayout(row)
        hl.setContentsMargins(14, 10, 14, 10)
        ic = QLabel(icon)
        ic.setStyleSheet("font-size:18px; ")
        box = QVBoxLayout()
        box.setSpacing(1)
        nl = QLabel(name)
        nl.setStyleSheet(f"color:{_T['TEXT']}; font-size:14px; font-weight:600; background:transparent;")
        dl = QLabel(desc)
        dl.setStyleSheet(
            f"color:{_T['MUTED']}; font-size:11px;"
            f" background:transparent;"
        )
        box.addWidget(nl)
        box.addWidget(dl)
        hl.addWidget(ic)
        hl.addLayout(box)
        hl.addStretch()
        if action:
            btn = QPushButton(QApplication.translate("tilauscope_onboarding","Pair"))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._pair_style())
            hl.addWidget(btn)
            return row, btn
        status = QLabel(QApplication.translate("tilauscope_onboarding","searching…"))
        status.setStyleSheet(
            f"color:{_T['MUTED']}; font-size:12px;"
            f" background:transparent;"
        )
        hl.addWidget(status)
        return row, status

    # ── navigation ────────────────────────────────────────────────────────
    def _show_step(self, index: int) -> None:
        index = max(0, min(index, len(self.STEPS) - 1))
        self._index = index
        self._stack.setCurrentIndex(index)

        skipped = index != 2 and not self._connection_needed()
        for i, (b, lab) in enumerate(zip(self._bullets, self._steplabels)):
            b.setText("–" if (i == 2 and skipped) else str(i + 1))
            if i == index:
                b.setStyleSheet(
                    f"background:{_T['ACCENT']}; color:{_T['SURFACE']}; border-radius:16px;"
                    f" font-weight:700;"
                )
                lab.setStyleSheet(f"color:{_T['TEXT']}; font-size:11px; background:transparent;")
            elif i < index:
                b.setStyleSheet(
                    f"background:{_T['OVERLAY']}; color:{_T['GREEN']}; border-radius:16px;"
                    f" font-weight:700;"
                )
                lab.setStyleSheet(f"color:{_T['SUBTEXT']}; font-size:11px; background:transparent;")
            else:
                b.setStyleSheet(
                    f"background:{_T['OVERLAY']}; color:{_T['MUTED']}; border-radius:16px;"
                    f" font-weight:700;"
                )
                lab.setStyleSheet(f"color:{_T['MUTED']}; font-size:11px; background:transparent;")

        self._back_btn.setEnabled(index > 0)
        last = index == len(self.STEPS) - 1
        self._next_btn.setText(QApplication.translate("tilauscope_onboarding","Finish") if last else QApplication.translate("tilauscope_onboarding","Next"))
        self._count_lbl.setText(f"{index + 1} / {len(self.STEPS)}")

        if index >= 1:
            self._hook_scanner()      # live first-run detection, roaster link included
        if index == 2:
            self._fill_connection()
        if index == 3:
            self._refresh_detection()  # persisted (redo) detection
            self._detect_timer.start(1500)
        else:
            self._detect_timer.stop()
        if index == 4:
            self._refresh_dir_labels()
        if last:
            self._fill_recap()

    def _go(self, step: int) -> None:
        """Move by *step*, passing over the Connection step when it has nothing to ask."""
        target = self._index + step
        if target == 2 and not self._connection_needed():
            target += step
        self._show_step(target)

    @pyqtSlot()
    def _on_next(self) -> None:
        if self._index == len(self.STEPS) - 1:
            qmc = self._aw.qmc
            if qmc.flagon or qmc.flagstart:
                show_styled_message(
                    self,
                    QApplication.translate("tilauscope_onboarding","Monitoring is on"),
                    QApplication.translate("tilauscope_onboarding",
                        "Turn monitoring off, then press Finish again. The roaster setup cannot change while it is being read."))
                return
            self._apply_and_finish()
        else:
            self._go(1)

    # ── hardware detection (best-effort, non-blocking) ────────────────────
    def _mark_detected(self, status: QLabel) -> None:
        status.setText(QApplication.translate("tilauscope_onboarding","detected ✓"))
        status.setStyleSheet(
            f"color:{_T['GREEN']}; font-size:12px;"
            f" background:transparent;"
        )

    def _roaster_heard(self, prefix: str) -> None:
        """A roaster link advertised nearby: select it unless the operator chose, then redraw."""
        if prefix in self._ble_seen:
            return
        self._ble_seen.add(prefix)
        if not self._setup_chosen:
            self._setup_index = self._default_setup_index()
        if self._index == 2:
            self._fill_connection()

    def _refresh_detection(self) -> None:
        """Detect devices already configured (persisted names/ids) — redo path."""
        for attrs, status, _prefix in self._periph:
            found = False
            for attr in attrs:
                val = getattr(self._aw, attr, None)
                if val is None:
                    val = getattr(self._beancave, attr, None)
                try:
                    if isinstance(val, (list, tuple, str)) and len(val) > 0:
                        found = True
                        break
                    if attr in self._OBJECT_OK and val is not None:
                        found = True
                        break
                except Exception:  # pylint: disable=broad-except
                    continue
            if found:
                self._mark_detected(status)

    # ── live scan detection (first-run path) ──────────────────────────────
    def _hook_scanner(self) -> None:
        """Subscribe to the central BLE scanner's stream (once)."""
        if self._scanner_hooked:
            return
        scanner = getattr(self._beancave, "_ble_scanner", None)
        if scanner is None or not hasattr(scanner, "devices_found"):
            return
        try:
            scanner.devices_found.connect(self._on_devices_found)
            self._scanner_hooked = True
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("scanner hook failed: %s", e)

    def _unhook_scanner(self) -> None:
        if not self._scanner_hooked:
            return
        scanner = getattr(self._beancave, "_ble_scanner", None)
        try:
            if scanner is not None:
                scanner.devices_found.disconnect(self._on_devices_found)
        except Exception:  # pylint: disable=broad-except
            pass
        self._scanner_hooked = False

    def _on_devices_found(self, devices: list) -> None:
        """Slot on TilauBLEScanner.devices_found — match advertised names to rows."""
        try:
            roaster_prefixes = tuple(s.ble_prefix for s in self._setups if s.ble_prefix)
            own_prefixes = tuple(p.casefold() for *_, p in self._periph if p) + tuple(
                p.casefold() for p in roaster_prefixes)
            for bd, ad in devices:
                name = getattr(bd, "name", None)
                # 1. our own peripherals → flip their dedicated row to "detected"
                matched_own = False
                if name:
                    for prefix in roaster_prefixes:
                        if name.startswith(prefix):
                            self._roaster_heard(prefix)
                            matched_own = True
                    for _attrs, status, prefix in self._periph:
                        if prefix and name.startswith(prefix):
                            self._mark_detected(status)
                            matched_own = True
                if matched_own:
                    continue
                # 2. other known Artisan BLE devices → identify only, no linking
                self._match_known_ble(bd, ad, own_prefixes)
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("on_devices_found failed: %s", e)

    def _match_known_ble(self, bd, ad, own_prefixes: tuple[str, ...]) -> None:
        """Identify a nearby device against the Artisan BLE signature catalog."""
        addr = getattr(bd, "address", None) or getattr(bd, "name", None)
        if not addr or addr in self._known_ble_seen:
            return
        name = getattr(bd, "name", None) or ""
        if any(name.casefold().startswith(p) for p in own_prefixes):
            return  # already covered by a dedicated peripheral row
        for label, prefix, service_uuid in _KNOWN_BLE_SIGNATURES:
            if _ble_signature_match(bd, ad, prefix, service_uuid):
                self._known_ble_seen[addr] = label
                self._add_known_ble_row(label, name or str(addr))
                return

    def _add_known_ble_row(self, label: str, signature: str) -> None:
        if getattr(self, "_known_ble_empty", None) is not None:
            self._known_ble_empty.hide()
            self._known_ble_empty.deleteLater()
            self._known_ble_empty = None
        row = QFrame()
        row.setStyleSheet(
            f"background:{_T['SURFACE']}; border:1px solid {_T['OVERLAY']}; border-radius:9px;"
        )
        hl = QHBoxLayout(row)
        hl.setContentsMargins(12, 8, 12, 8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{_T['MAUVE']}; font-size:11px; background:transparent;")
        nl = QLabel(label)
        nl.setStyleSheet(f"color:{_T['TEXT']}; font-size:13px; font-weight:600; background:transparent;")
        sig = QLabel(signature)
        sig.setStyleSheet(
            f"color:{_T['MUTED']}; font-size:11px;"
            f" background:transparent;"
        )
        tag = QLabel(QApplication.translate("tilauscope_onboarding","recognised · not configured"))
        tag.setStyleSheet(
            f"color:{_T['MAUVE']}; font-size:11px;"
            f" background:transparent;"
        )
        hl.addWidget(dot)
        hl.addWidget(nl)
        hl.addSpacing(8)
        hl.addWidget(sig)
        hl.addStretch()
        hl.addWidget(tag)
        self._known_ble_layout.addWidget(row)

    # ── apply ─────────────────────────────────────────────────────────────
    def _apply_and_finish(self) -> None:
        self._detect_timer.stop()
        self._unhook_scanner()
        QSettings().setValue(_DONE_KEY, True)
        try:
            self._apply_settings()
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("onboarding apply failed: %s", e)
        self.accept()
        # hand-off: open the new green bean editor in BeanCave
        QTimer.singleShot(0, self._open_first_bean)

    def _apply_settings(self) -> None:
        aw = self._aw
        from tilauscope.roasters import sync_operator_to_qmc
        sync_operator_to_qmc(aw, self._operator)

        # 1. unit (before theme so the °C custom axes survive)
        try:
            if self._unit == "C":
                aw.qmc.celsiusMode()
            else:
                aw.qmc.fahrenheitMode()
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("unit apply failed: %s", e)

        # 2. machine setup: the functional part of the chosen link's preset, then
        #    the roaster's own figures (never the theme, alarms or paired devices).
        QSettings().setValue("RoastPlan/RoasterModel", self._roaster)
        setup = self._current_setup()
        try:
            if setup is not None:
                machine_setup.apply(aw, self._roaster, setup, self._port, self._host)
            elif self._roaster:
                from tilauscope.roasters import sync_roaster_to_qmc
                aw.tilau_roaster = self._roaster
                sync_roaster_to_qmc(aw, self._roaster)
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("machine setup failed: %s", e)

        # 3. theme (visual sections only → safe with theme=True)
        theme = _theme_path()
        if os.path.exists(theme):
            try:
                aw.settingsLoad(theme, theme=True)
            except Exception as e:  # pylint: disable=broad-except
                _log.exception("theme load failed: %s", e)
        else:
            _log.warning("theme file not found: %s", theme)

        # 4. fix axes for °F (theme carries the °C reference ranges)
        if self._unit == "F":
            try:
                aw.qmc.fahrenheitMode(setdefaultaxes=True)
            except Exception:  # pylint: disable=broad-except
                pass
        try:
            aw.qmc.redraw()
        except Exception:  # pylint: disable=broad-except
            pass

    def _open_first_bean(self) -> None:
        try:
            bc = self._beancave
            if hasattr(bc, "clear_form"):
                bc.clear_form()
            if hasattr(bc, "_enter_edit_mode"):
                bc._enter_edit_mode()
            if hasattr(bc, "_open_full_bean_editor"):
                bc._open_full_bean_editor()
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("first-bean hand-off failed: %s", e)

    # ── skip / close ──────────────────────────────────────────────────────
    def _skip(self) -> None:
        self._detect_timer.stop()
        self._unhook_scanner()
        QSettings().setValue(_DONE_KEY, True)  # do not auto-reappear
        self.reject()

    # ── helpers ───────────────────────────────────────────────────────────
    def _roaster_names(self) -> list[str]:
        # Fresh manager → always the full bundled list, regardless of BeanCave state.
        try:
            from tilauscope.roasters import RoasterManager
            names = RoasterManager().get_roaster_list()
            if names:
                return list(names)
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            rm = getattr(self._beancave, "roaster_manager", None)
            if rm is not None:
                names = rm.get_display_names()
                if names:
                    return list(names)
        except Exception:  # pylint: disable=broad-except
            pass
        return ["ITOP Cyberroaster"]

    def _set_roaster(self, name: str) -> None:
        self._roaster = name
        self._setups = machine_setup.setups_for(name)
        self._setup_chosen = False
        self._port = None
        self._host = ""
        self._setup_index = self._default_setup_index()
        self._refresh_facts()

    # ── frameless drag ────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── styles ────────────────────────────────────────────────────────────
    def _ghost_style(self) -> str:
        return (
            f"QPushButton {{ background:transparent; color:{_T['SUBTEXT']};"
            f" border:1px solid {_T['OVER1']}; border-radius:10px; padding:10px 22px;"
            f" font-size:14px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{_T['OVERLAY']}; }}"
            f"QPushButton:disabled {{ color:{_T['MUTED']}; border-color:{_T['OVERLAY']}; }}"
        )

    def _primary_style(self) -> str:
        return (
            f"QPushButton {{ background:{_T['ACCENT']}; color:{_T['SURFACE']};"
            f" border:none; border-radius:10px; padding:10px 22px; font-size:14px;"
            f" font-weight:700; }}"
            f"QPushButton:hover {{ background:{_T['SKY']}; }}"
        )

    def _pill_style(self) -> str:
        return (
            f"QPushButton {{ background:{_T['SURFACE']}; color:{_T['SUBTEXT']};"
            f" border:1px solid {_T['OVERLAY']}; border-radius:15px; padding:6px 16px;"
            f" font-size:13px; font-weight:600; }}"
            f"QPushButton:hover {{ border-color:{_T['OVER2']}; }}"
            f"QPushButton:checked {{ background:{_T['ACCENT']}; color:{_T['SURFACE']};"
            f" border-color:{_T['ACCENT']}; }}"
        )

    def _radio_style(self) -> str:
        return (
            f"QRadioButton {{ background:{_T['SURFACE']}; color:{_T['TEXT']};"
            f" border:1px solid {_T['OVERLAY']}; border-radius:11px; padding:12px 14px;"
            f" font-size:14px; font-weight:600; }}"
            f"QRadioButton:hover {{ border-color:{_T['OVER2']}; }}"
            f"QRadioButton::indicator {{ width:0px; height:0px; }}"
            f"QRadioButton:checked {{ border-color:{_T['ACCENT']}; color:{_T['TEXT']}; }}"
        )

    def _pair_style(self, linked: bool = False) -> str:
        if linked:
            return (
                f"QPushButton {{ background:rgba(166,227,161,0.15); color:{_T['GREEN']};"
                f" border:none; border-radius:8px; padding:8px 15px; font-size:12px;"
                f" font-weight:600; }}"
            )
        return (
            f"QPushButton {{ background:{_T['OVERLAY']}; color:{_T['ACCENT']};"
            f" border:1px solid {_T['OVER1']}; border-radius:8px; padding:8px 15px;"
            f" font-size:12px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{_T['OVER1']}; }}"
        )

    def _group_style(self) -> str:
        return (
            f"color:{_T['MUTED']}; font-size:11px; "
            f" letter-spacing:1px; background:transparent;"
        )


# ═══════════════════════════════════════════════════════════════════════════
def maybe_show_onboarding(beancave: QWidget, aw: "ApplicationWindow") -> "OnboardingWizard | None":
    """Show the wizard once, on first run. No-op afterwards.

    Call from BeanCave startup (inside a QTimer.singleShot), *before* what's-new::

        from tilauscope.onboarding import maybe_show_onboarding
        QTimer.singleShot(400, lambda: maybe_show_onboarding(self, self.aw))
    """
    try:
        if QSettings().value(_DONE_KEY, False, type=bool):
            return None
        return run_onboarding(beancave, aw)
    except Exception as e:  # pylint: disable=broad-except
        _log.exception("maybe_show_onboarding failed: %s", e)
        return None


def run_onboarding(beancave: QWidget, aw: "ApplicationWindow") -> "OnboardingWizard | None":
    """Force-show the wizard (menu replay), ignoring the done flag."""
    try:
        dlg = OnboardingWizard(beancave, aw)
        dlg.show()
        dlg.raise_()
        return dlg
    except Exception as e:  # pylint: disable=broad-except
        _log.exception("run_onboarding failed: %s", e)
        return None
