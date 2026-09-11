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

"""First-run configuration assistant for TilauScope: a 4-step wizard (unit,
roaster model, hardware, hand-off to BeanCave) shown once and replayable from the menu.
Settings apply atomically only when the user validates the last step; skipping never
touches settings."""

import logging
import os
from typing import Final, TYPE_CHECKING

from PyQt6.QtCore import QSettings, Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from artisanlib.util import getResourcePath
from tilauscope.tilauscope_types import _IS_MACOS, THEME

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


# ── Roaster display-name → bundled machine .aset ───────────────────────────
# (subdir, default_file, paired_file): default_file loads when not paired, paired_file
# once paired (e.g. Skywalker switches USB→BLE profile). Matched by substring.
_ROASTER_MACHINE_ASET: Final[list[tuple[str, tuple[str, str, str]]]] = [
    ("Cyberroaster",  ("Skywalker", "skywalkerv2-usb.aset", "skywalkerv2-ble.aset")),
    ("Skywalker V2",  ("Skywalker", "skywalkerv2-usb.aset", "skywalkerv2-ble.aset")),
]

# Curated theme shipped in the repo (generated from the reference profile).
_THEME_REL: Final[tuple[str, ...]] = ("Themes", "TilauScope", "Catppuccin.athm")


from tilauscope.theme_qss import apply_tilau_theme


def _theme_path() -> str:
    return os.path.join(getResourcePath(), *_THEME_REL)


def _machine_aset_for(roaster: str, paired: bool = False) -> str | None:
    """Resolve the bundled machine .aset for *roaster*.

    When *paired* is True and a paired-variant is defined, that one wins
    (e.g. BLE once the Skywalker was manually paired), else the default.
    """
    for needle, rel in _ROASTER_MACHINE_ASET:
        if needle.lower() in roaster.lower():
            subdir, default_file, paired_file = rel
            fname = paired_file if (paired and paired_file) else default_file
            p = os.path.join(getResourcePath(), "Machines", subdir, fname)
            return p if os.path.exists(p) else None
    return None


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
    """The 4-step first-run configuration dialog."""

    STEPS: Final[tuple[str, ...]] = (
        "Unité", "Torréfacteur", "Matériel", "Dossiers", "Premier grain")

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
        self._roaster: str = ""
        self._skywalker_ready: bool = False  # set by detection → drives USB/BLE profile
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
            lab = QLabel(name)
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
        self._stack.addWidget(self._page_hardware())
        self._stack.addWidget(self._page_dirs())
        self._stack.addWidget(self._page_finish())
        self._stack.setMinimumHeight(330)
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
        self._back_btn.clicked.connect(lambda: self._show_step(self._index - 1))

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

    # ── page 1: unit ──────────────────────────────────────────────────────
    def _page_unit(self) -> QWidget:
        page = self._page_base(
            QApplication.translate("tilauscope_onboarding","Which unit do you want to work in?"),
            QApplication.translate("tilauscope_onboarding","All temperatures — curves, milestones, setpoints — will be shown in "
                "this unit. You can change it later in the settings."),
        )
        seg = QHBoxLayout()
        seg.setSpacing(10)
        seg.addStretch()
        self._unit_group = QButtonGroup(self)
        for code, big, small in (("C", "°C", "Celsius"), ("F", "°F", "Fahrenheit")):
            b = QPushButton(f"{big}\n{small}")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(150, 74)
            b.setStyleSheet(self._toggle_style())
            b.setChecked(code == "C")
            b.clicked.connect(lambda _=False, c=code: setattr(self, "_unit", c))
            self._unit_group.addButton(b)
            seg.addWidget(b)
        seg.addStretch()
        page.layout().addLayout(seg)
        page.layout().addStretch()
        return page

    # ── page 2: roaster ───────────────────────────────────────────────────
    def _page_roaster(self) -> QWidget:
        page = self._page_base(
            QApplication.translate("tilauscope_onboarding","Which roaster do you use?"),
            QApplication.translate("tilauscope_onboarding","The machine sets the roast plan, slider labels and recommendations. "
                "If a device profile is bundled, it is loaded when you finish."),
        )
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
        col.setSpacing(8)

        self._roaster_group = QButtonGroup(self)
        names = self._roaster_names()
        current = QSettings().value("RoastPlan/RoasterModel", "", str) or ""
        default_i = next(
            (i for i, n in enumerate(names) if n == current),
            next((i for i, n in enumerate(names)
                  if "cyberroaster" in n.lower() or "skywalker v2" in n.lower()), 0),
        )
        for i, name in enumerate(names):
            rb = QRadioButton("  " + name)
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            rb.setStyleSheet(self._radio_style())
            rb.setChecked(i == default_i)
            rb.toggled.connect(lambda on, n=name: self._set_roaster(n) if on else None)
            self._roaster_group.addButton(rb)
            col.addWidget(rb)
        col.addStretch()
        if names:
            self._roaster = names[default_i]
        scroll.setWidget(holder)
        page.layout().addWidget(scroll, 1)
        return page

    # ── page 3: hardware ──────────────────────────────────────────────────
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
            from tilauscope.tc4ble import SKYWALKER_PREFIX
        except Exception:  # pylint: disable=broad-except
            SKYWALKER_PREFIX = "TD5325A"
        try:
            from tilauscope.lebrewroastsee import C1_PREFIX, AG_PREFIX
        except Exception:  # pylint: disable=broad-except
            C1_PREFIX, AG_PREFIX = "RoastSee C1", "RoastSee AquaGauge"

        # Each device: persisted attributes (checked on aw + BeanCave, so a
        # previously configured device shows "detected" on redo) AND a live BLE
        # name prefix (matched against the central scanner's stream, so a
        # present-but-unconfigured device is detected on first run too). The
        # Skywalker also drives the USB→BLE profile switch: detected ⇒ BLE.
        self._periph: list[tuple[tuple[str, ...], QLabel, bool, str]] = []
        for icon, name, desc, attrs, is_roaster, prefix in (
            ("🔥", "Skywalker V2", QApplication.translate("tilauscope_onboarding","roaster · USB by default, BLE if detected"),
             ("bleSkywalkerDeviceName", "bleSkywalkerDeviceslist"), True, SKYWALKER_PREFIX),
            ("🌫️", "DiFluid AirWave", QApplication.translate("tilauscope_onboarding","smoke extractor · PID"),
             ("bleAirwaveDeviceName", "bleAirwaveDeviceslist"), False, AIRWAVE_PREFIX),
            ("⚖️", "Acaia scale", QApplication.translate("tilauscope_onboarding","charge & output weighing"),
             ("scale1_name", "scale1_id", "scale2_name", "scale2_id"), False, ""),
            ("🌡️", "TilauAmbient", QApplication.translate("tilauscope_onboarding","ESP32 probe · BME280 / I²S mic"),
             ("bleTilauAmbientDeviceslist", "bleTilauAmbientDevice"), False, TILAUAMBIENT_PREFIX),
            ("💧", "Lebrew AquaGauge", QApplication.translate("tilauscope_onboarding","water activity (Aw)"),
             ("bleRoastSeeAGDeviceName", "bleRoastSeeAGDeviceslist", "bleRoastSeeAGDevice"),
             False, AG_PREFIX),
            ("🎨", "Lebrew RoastSee C1", QApplication.translate("tilauscope_onboarding","bean colour reader"),
             ("bleRoastSeeDeviceName", "bleRoastSeeDeviceslist"), False, C1_PREFIX),
        ):
            row, status = self._device_row(icon, name, desc, action=False)
            self._periph.append((attrs, status, is_roaster, prefix))
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

    # ── page 4: directories ───────────────────────────────────────────────
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

    # ── page 5: finish ────────────────────────────────────────────────────
    def _page_finish(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(34, 20, 34, 10)
        lay.setSpacing(4)

        seal = QLabel("🌱")
        seal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seal.setStyleSheet("font-size:44px; ")
        h = QLabel(QApplication.translate("tilauscope_onboarding","Ready to apply."))
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.setStyleSheet(f"color:{_T['TEXT']}; font-size:22px; font-weight:700; background:transparent;")
        sub = QLabel(QApplication.translate("tilauscope_onboarding","On finish, TilauScope applies these settings then takes you to "
                         "create your first green bean. If you leave now, nothing changes."))
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color:{_T['SUBTEXT']}; font-size:13px; background:transparent;")

        lay.addWidget(seal)
        lay.addWidget(h)
        lay.addWidget(sub)
        lay.addSpacing(10)

        self._recap = QVBoxLayout()
        self._recap.setSpacing(7)
        recap_host = QWidget()
        recap_host.setMaximumWidth(430)
        recap_host.setLayout(self._recap)
        lay.addWidget(recap_host, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch()
        return page

    def _fill_recap(self) -> None:
        while self._recap.count():
            item = self._recap.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        rows = [
            (QApplication.translate("tilauscope_onboarding","Unit"), "°C" if self._unit == "C" else "°F"),
            (QApplication.translate("tilauscope_onboarding","Roaster"), self._roaster or "—"),
        ]
        # show which device profile will load, when one is bundled
        if _machine_aset_for(self._roaster, paired=self._skywalker_ready):
            rows.append((QApplication.translate("tilauscope_onboarding","Device profile"),
                         "BLE" if self._skywalker_ready else "USB"))
        rows += [
            (QApplication.translate("tilauscope_onboarding","Theme & curves"), "Catppuccin"),
            (QApplication.translate("tilauscope_onboarding","Axes & smoothing"), QApplication.translate("tilauscope_onboarding","reference profile")),
        ]
        if self._beancave_dir:
            rows.append((QApplication.translate("tilauscope_onboarding","BeanCave folder"), os.path.basename(self._beancave_dir.rstrip("/\\")) or self._beancave_dir))
        if self._alog_dir:
            rows.append((QApplication.translate("tilauscope_onboarding","Roast logs folder"), os.path.basename(self._alog_dir.rstrip("/\\")) or self._alog_dir))
        for k, v in rows:
            row = QFrame()
            row.setStyleSheet(
                f"background:{_T['SURFACE']}; border:1px solid {_T['OVERLAY']};"
                f" border-radius:9px;"
            )
            hl = QHBoxLayout(row)
            hl.setContentsMargins(14, 10, 14, 10)
            arrow = QLabel("→")
            arrow.setStyleSheet(f"color:{_T['GREEN']}; ")
            kl = QLabel(k)
            kl.setStyleSheet(f"color:{_T['SUBTEXT']}; font-size:13px; background:transparent;")
            vl = QLabel(v)
            vl.setStyleSheet(
                f"color:{_T['TEXT']}; font-size:13px; font-weight:600;"
                f" background:transparent;"
            )
            hl.addWidget(arrow)
            hl.addWidget(kl)
            hl.addStretch()
            hl.addWidget(vl)
            self._recap.addWidget(row)

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

        for i, (b, lab) in enumerate(zip(self._bullets, self._steplabels)):
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

        if index == 2:
            self._hook_scanner()      # live first-run detection
            self._refresh_detection()  # persisted (redo) detection
            self._detect_timer.start(1500)
        else:
            self._detect_timer.stop()
        if index == 3:
            self._refresh_dir_labels()
        if last:
            self._fill_recap()

    @pyqtSlot()
    def _on_next(self) -> None:
        if self._index == len(self.STEPS) - 1:
            self._apply_and_finish()
        else:
            self._show_step(self._index + 1)

    # ── hardware detection (best-effort, non-blocking) ────────────────────
    def _mark_detected(self, status: QLabel, is_roaster: bool) -> None:
        status.setText(QApplication.translate("tilauscope_onboarding","detected ✓"))
        status.setStyleSheet(
            f"color:{_T['GREEN']}; font-size:12px;"
            f" background:transparent;"
        )
        if is_roaster:
            self._skywalker_ready = True

    def _refresh_detection(self) -> None:
        """Detect devices already configured (persisted names/ids) — redo path."""
        for attrs, status, is_roaster, _prefix in self._periph:
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
                self._mark_detected(status, is_roaster)

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
            own_prefixes = tuple(p.casefold() for *_, p in self._periph if p)
            for bd, ad in devices:
                name = getattr(bd, "name", None)
                # 1. our own peripherals → flip their dedicated row to "detected"
                matched_own = False
                if name:
                    for _attrs, status, is_roaster, prefix in self._periph:
                        if prefix and name.startswith(prefix):
                            self._mark_detected(status, is_roaster)
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
        # 1. unit (before theme so the °C custom axes survive)
        try:
            if self._unit == "C":
                aw.qmc.celsiusMode()
            else:
                aw.qmc.fahrenheitMode()
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("unit apply failed: %s", e)

        # 2. machine device config (only the machine subset — never the theme).
        #    Paired → BLE profile, otherwise the default USB profile.
        QSettings().setValue("RoastPlan/RoasterModel", self._roaster)
        aset = _machine_aset_for(self._roaster, paired=self._skywalker_ready)
        if aset:
            try:
                aw.loadSettings(fn=aset, remember=False, machine=True, reload=False)
            except Exception as e:  # pylint: disable=broad-except
                _log.exception("machine aset load failed: %s", e)

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

    def _toggle_style(self) -> str:
        return (
            f"QPushButton {{ background:{_T['SURFACE']}; color:{_T['SUBTEXT']};"
            f" border:1px solid {_T['OVERLAY']}; border-radius:12px; font-size:15px;"
            f" font-weight:600; }}"
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
