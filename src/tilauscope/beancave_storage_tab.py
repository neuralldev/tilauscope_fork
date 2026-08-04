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

## TILAU ##
"""Stockage tab — green-coffee conservation dashboard for BeanCave.

Multi-bean water-activity (aw) risk overview + per-bean conservation fiche.
Reads each bean's measured aw (AquaGauge) and the real storage-room ambient
humidity (passive MQTT read, NOT a roast channel) and runs storage_advisor to
classify a risk zone and a moisture-drift trend. All logic is display-only over
the shared green_beans list; storage_advisor holds the (offline-tested) engine.

Kept in a separate module so beancave.py does not grow (sacks-spec convention).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QComboBox, QSplitter, QSizePolicy, QDialog, QLineEdit, QGridLayout,
)
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QApplication

from tilauscope.tilauscope_types import THEME
from tilauscope.sack_manager import (   ## TILAU ## sack labels (design v4 §9)
    SackAssignDialog, SackChipsRow, SackPool, ReclaimSacksDialog,
    confirm_release, orphaned_sacks, release_sacks,
)
from tilauscope import storage_advisor as SA
from tilauscope.storage_advisor import (
    AwZone, MoistureTrend, StorageThresholds,
    STORAGE_HUMIDITY_TOPIC_KEY, STORAGE_HUMIDITY_FIELD_KEY,
    STORAGE_TEMP_TOPIC_KEY, STORAGE_TEMP_FIELD_KEY,
    STORAGE_AW_DRY_KEY, STORAGE_AW_WARN_KEY, STORAGE_AW_RISK_KEY,
    DEFAULT_HUMIDITY_FIELD, DEFAULT_TEMP_FIELD,
)

if TYPE_CHECKING:
    from tilauscope.beancave import BeancaveDlg
    from tilauscope.tilauscope_types import GreenBean
    from tilauscope.mqttbridge import TilauscopeMQTTClient

_logd = logging.getLogger("tilau")

# --- semantic colours (aligned with the validated mockup) ------------------- #
Z_OPTIMAL = THEME["SUCCESS"]     # #A6E3A1 green
Z_WATCH = THEME["TODAY"]         # #FAB387 peach
Z_TOO_DRY = "#F9E2AF"            # Catppuccin yellow (not in THEME)
Z_RISK = THEME["CRITICAL"]       # #F38BA8 red
Z_UNKNOWN = THEME["SUBTEXT"]     # grey

_ZONE_COLOR: dict[AwZone, str] = {
    AwZone.OPTIMAL: Z_OPTIMAL,
    AwZone.WATCH: Z_WATCH,
    AwZone.TOO_DRY: Z_TOO_DRY,
    AwZone.MOLD_RISK: Z_RISK,
    AwZone.UNKNOWN: Z_UNKNOWN,
}

# Sort order: most-at-risk beans float to the top of the table.
_ZONE_RANK: dict[AwZone, int] = {
    AwZone.MOLD_RISK: 0,
    AwZone.WATCH: 1,
    AwZone.TOO_DRY: 2,
    AwZone.OPTIMAL: 3,
    AwZone.UNKNOWN: 4,
}


def zone_label(zone: AwZone) -> str:
    return {
        AwZone.OPTIMAL: QApplication.translate("tilauscope_storage", "Optimal"),
        AwZone.WATCH: QApplication.translate("tilauscope_storage", "To watch"),
        AwZone.TOO_DRY: QApplication.translate("tilauscope_storage", "Too dry"),
        AwZone.MOLD_RISK: QApplication.translate("tilauscope_storage", "Mould risk"),
        AwZone.UNKNOWN: QApplication.translate("tilauscope_storage", "aw not measured"),
    }[zone]


def trend_label(trend: MoistureTrend) -> str:
    return {
        MoistureTrend.SEALED: QApplication.translate("tilauscope_storage", "🔒 sealed"),
        MoistureTrend.GAINING: QApplication.translate("tilauscope_storage", "↑ gaining moisture"),
        MoistureTrend.DRYING: QApplication.translate("tilauscope_storage", "↓ slow drying"),
        MoistureTrend.STABLE: QApplication.translate("tilauscope_storage", "= stable"),
        MoistureTrend.UNKNOWN: "—",
    }[trend]


# --- conditioning options (key stored on GreenBean, label shown) ------------ #
def conditioning_options() -> list[tuple[str, str]]:
    return [
        ("", QApplication.translate("tilauscope_storage", "Not set")),
        ("vacuum", QApplication.translate("tilauscope_storage", "Vacuum-sealed")),
        ("grainpro", QApplication.translate("tilauscope_storage", "GrainPro (valve)")),
        ("ecotact", QApplication.translate("tilauscope_storage", "Ecotact bag")),
        ("bocal", QApplication.translate("tilauscope_storage", "Sealed jar")),
        ("toile", QApplication.translate("tilauscope_storage", "Open cloth bag")),
    ]


def conditioning_label(key: str) -> str:
    for k, lbl in conditioning_options():
        if k == (key or ""):
            return lbl
    return QApplication.translate("tilauscope_storage", "Not set")


# --- settings helpers ------------------------------------------------------- #
def load_thresholds() -> StorageThresholds:
    s = QSettings()
    d = SA.DEFAULT_THRESHOLDS
    try:
        return StorageThresholds(
            dry=float(s.value(STORAGE_AW_DRY_KEY, d.dry, type=float)),
            warn=float(s.value(STORAGE_AW_WARN_KEY, d.warn, type=float)),
            risk=float(s.value(STORAGE_AW_RISK_KEY, d.risk, type=float)),
        )
    except Exception:
        return d


# --------------------------------------------------------------------------- #
# Widget
# --------------------------------------------------------------------------- #

class StorageTab(QWidget):
    """The Stockage tab body. Owns nothing but reads host.green_beans live."""

    def __init__(self, host: "BeancaveDlg") -> None:
        super().__init__()
        self.host = host
        self._rows: list["GreenBean"] = []          # bean per visible table row
        self._orphans: list[tuple[object, list[str]]] = []   # out-of-stock beans still holding labels
        self._selected_uuid: str = ""
        self._ambient_rh: float | None = None
        self._ambient_temp: float | None = None
        # Dedicated MQTT connection for the storage sensor, used when no roast is
        # running (the shared roast client only lives during monitoring).
        self._mqtt: "TilauscopeMQTTClient | None" = None
        self._sub_client: object | None = None      # client we last subscribed on
        self._subscribed: set[str] = set()
        self._build_ui()

        # Refresh the ambient banner periodically while this tab is on screen.
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._refresh_ambient_only)

    # -- lifecycle ----------------------------------------------------------- #

    def on_shown(self) -> None:
        """Called when this tab becomes current."""
        self.refresh()
        self._timer.start()

    def on_hidden(self) -> None:
        self._timer.stop()
        self._stop_dedicated()

    # -- UI ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # toolbar
        bar = QHBoxLayout()
        title = QLabel(QApplication.translate("tilauscope_storage", "Stock conservation"))
        title.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:16px; font-weight:700;"
        )
        bar.addWidget(title)
        bar.addStretch()
        self.sack_tool_btn = QPushButton("🏷️  " + QApplication.translate("tilauscope_storage", "Manage sack labels"))
        self.sack_tool_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sack_tool_btn.setStyleSheet(self._btn_css())
        self.sack_tool_btn.clicked.connect(self._open_sack_labels)
        bar.addWidget(self.sack_tool_btn)
        root.addLayout(bar)

        # ## TILAU ## orphan-label banner (design v4 §9.3) — passive safety net.
        # Shown whenever out-of-stock beans still hold labels: this is a data
        # anomaly, not a notification, so it stays until the user resolves it.
        self.orphan_banner = QFrame()
        self.orphan_banner.setObjectName("StorageOrphanBanner")
        self.orphan_banner.setStyleSheet(
            f"""
            #StorageOrphanBanner {{
                background: {THEME['SURFACE']};
                border: 1px solid {THEME['BORDER']};
                border-left: 3px solid {Z_WATCH};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; border: none; }}
            """
        )
        ol = QHBoxLayout(self.orphan_banner)
        ol.setContentsMargins(14, 9, 14, 9)
        ol.setSpacing(10)
        icon = QLabel("⚠️")
        icon.setStyleSheet("font-size:15px;")
        self.orphan_lbl = QLabel()
        self.orphan_lbl.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:13px; font-weight:600;"
        )
        self.orphan_btn = QPushButton(QApplication.translate("tilauscope_storage", "Review…"))
        self.orphan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.orphan_btn.setStyleSheet(self._btn_css())
        self.orphan_btn.clicked.connect(self._open_reclaim)
        ol.addWidget(icon)
        ol.addWidget(self.orphan_lbl)
        ol.addStretch()
        ol.addWidget(self.orphan_btn)
        self.orphan_banner.setVisible(False)
        root.addWidget(self.orphan_banner)

        # ambient banner
        self.banner = QFrame()
        self.banner.setObjectName("StorageAmbientBanner")
        self.banner.setStyleSheet(
            f"""
            #StorageAmbientBanner {{
                background: {THEME['SURFACE']};
                border: 1px solid {THEME['BORDER']};
                border-left: 3px solid {THEME['ACCENT']};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; border: none; }}
            """
        )
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(10)
        self.banner_icon = QLabel("🌡️")
        self.banner_icon.setStyleSheet("font-size:18px;")
        self.banner_value = QLabel()
        self.banner_value.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:15px; font-weight:600;"
        )
        self.banner_source = QLabel()
        self.banner_source.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:12px;")
        self.banner_cfg_btn = QPushButton("⚙  " + QApplication.translate("tilauscope_storage", "configure"))
        self.banner_cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.banner_cfg_btn.setStyleSheet(self._btn_css())
        self.banner_cfg_btn.clicked.connect(self._open_mqtt_config)
        bl.addWidget(self.banner_icon)
        bl.addWidget(self.banner_value)
        bl.addStretch()
        bl.addWidget(self.banner_source)
        bl.addWidget(self.banner_cfg_btn)
        root.addWidget(self.banner)

        # split: table | fiche
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_table())
        split.addWidget(self._build_fiche())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([620, 400])
        root.addWidget(split, 1)

        # legend
        root.addWidget(self._build_legend())

    def _btn_css(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ border-color: {THEME['ACCENT']}; }}
            QPushButton:pressed {{ background-color: {THEME['BORDER']}; }}
        """

    def _build_table(self) -> QWidget:
        headers = [
            QApplication.translate("tilauscope_storage", "Bean"), QApplication.translate("tilauscope_storage", "Stock"), QApplication.translate("tilauscope_storage", "Sacks"),
            QApplication.translate("tilauscope_storage", "aw"), QApplication.translate("tilauscope_storage", "Conditioning"), QApplication.translate("tilauscope_storage", "Trend"),
        ]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(headers)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {THEME['SURFACE']};
                alternate-background-color: {THEME['BG']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 10px;
                gridline-color: {THEME['BORDER']};
                selection-background-color: rgba(137,180,250,40);
                selection-color: {THEME['TEXT']};
            }}
            QHeaderView::section {{
                background-color: {THEME['BG']};
                color: {THEME['SUBTEXT']};
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid {THEME['BORDER']};
                font-weight: 700;
            }}
            QTableWidget::item {{ padding: 6px 8px; }}
            """
        )
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        return self.table

    def _build_fiche(self) -> QWidget:
        self.fiche = QFrame()
        self.fiche.setObjectName("StorageFiche")
        self.fiche.setStyleSheet(
            f"""
            #StorageFiche {{
                background: {THEME['SURFACE']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; border: none; color: {THEME['TEXT']}; }}
            QComboBox {{
                background: {THEME['BG']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
                padding: 6px 10px;
            }}
            QComboBox:hover {{ border-color: {THEME['ACCENT']}; }}
            """
        )
        v = QVBoxLayout(self.fiche)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(14)

        # header
        self.f_name = QLabel()
        self.f_name.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:16px; font-weight:700;"
        )
        self.f_meta = QLabel()
        self.f_meta.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:12px;")
        self.f_stock = QLabel()
        self.f_stock.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:12px; font-weight:600;"
        )
        hrow = QHBoxLayout()
        namecol = QVBoxLayout()
        namecol.setSpacing(2)
        namecol.addWidget(self.f_name)
        namecol.addWidget(self.f_meta)
        hrow.addLayout(namecol)
        hrow.addStretch()
        hrow.addWidget(self.f_stock, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(hrow)

        # aw big + zone
        awrow = QHBoxLayout()
        self.f_aw = QLabel()
        self.f_aw.setStyleSheet("font-size:30px; font-weight:700;")
        self.f_zone = QLabel()
        self.f_zone.setStyleSheet("font-size:13px; font-weight:700;")
        awrow.addWidget(self.f_aw)
        awrow.addSpacing(12)
        awrow.addWidget(self.f_zone)
        awrow.addStretch()
        self.f_measure_btn = QPushButton("💧  " + QApplication.translate("tilauscope_storage", "Measure aw"))
        self.f_measure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.f_measure_btn.setStyleSheet(self._btn_css())
        self.f_measure_btn.clicked.connect(self._open_aw_editor)
        awrow.addWidget(self.f_measure_btn)
        v.addLayout(awrow)

        # conditioning selector
        cond_lbl = QLabel(QApplication.translate("tilauscope_storage", "CONDITIONING"))
        cond_lbl.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:10px; font-weight:700;"
            " letter-spacing:1px;"
        )
        v.addWidget(cond_lbl)
        self.f_conditioning = QComboBox()
        for key, lbl in conditioning_options():
            self.f_conditioning.addItem(lbl, key)
        self.f_conditioning.currentIndexChanged.connect(self._on_conditioning_changed)
        v.addWidget(self.f_conditioning)

        # ## TILAU ## sack labels (design v4 §9.1, slot A) — placed here because
        # this is where the fiche turns from readings into actions. The whole
        # block hides when the bean has no sack AND no label is available, so a
        # user without a label printer never sees it.
        self.f_sacks_box = QWidget()
        sv = QVBoxLayout(self.f_sacks_box)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(7)
        srow = QHBoxLayout()
        sacks_lbl = QLabel(QApplication.translate("tilauscope_storage", "SACK LABELS"))
        sacks_lbl.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:10px; font-weight:700;"
            " letter-spacing:1px;"
        )
        srow.addWidget(sacks_lbl)
        srow.addStretch()
        self.f_assign_btn = QPushButton("+ " + QApplication.translate("tilauscope_storage", "Assign"))
        self.f_assign_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.f_assign_btn.setStyleSheet(self._btn_css())
        self.f_assign_btn.clicked.connect(self._assign_sack)
        srow.addWidget(self.f_assign_btn)
        sv.addLayout(srow)
        self.f_sack_chips = SackChipsRow()
        self.f_sack_chips.sackReleased.connect(self._release_sack)
        sv.addWidget(self.f_sack_chips)
        v.addWidget(self.f_sacks_box)

        # verdict block
        self.f_verdict = QLabel()
        self.f_verdict.setWordWrap(True)
        self.f_verdict.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:12.5px; "
            f"background:{THEME['BG']}; border:1px solid {THEME['BORDER']}; "
            "border-radius:10px; padding:12px;"
        )
        v.addWidget(self.f_verdict)
        v.addStretch()

        self.fiche.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return self.fiche

    def _build_legend(self) -> QWidget:
        w = QLabel(
            f"<span style='color:{Z_TOO_DRY}'>■</span> {QApplication.translate("tilauscope_storage", '&lt; 0.45 · too dry')}"
            f"&nbsp;&nbsp;<span style='color:{Z_OPTIMAL}'>■</span> {QApplication.translate("tilauscope_storage", '0.45–0.60 · optimal')}"
            f"&nbsp;&nbsp;<span style='color:{Z_WATCH}'>■</span> {QApplication.translate("tilauscope_storage", '0.60–0.65 · to watch')}"
            f"&nbsp;&nbsp;<span style='color:{Z_RISK}'>■</span> {QApplication.translate("tilauscope_storage", '&gt; 0.65 · mould risk')}"
        )
        w.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px;")
        return w

    # -- data / refresh ------------------------------------------------------ #

    # -- MQTT connection (independent of the roast monitoring lifecycle) ------ #

    def _stop_dedicated(self) -> None:
        if self._mqtt is not None:
            try:
                self._mqtt.stop()
            except Exception:
                _logd.exception("StorageTab: stopping dedicated MQTT failed")
            self._mqtt = None
        self._sub_client = None
        self._subscribed = set()

    def _ensure_dedicated(self, topics: list[str]):
        """Open our own broker connection when no roast client is running."""
        if self._mqtt is not None and getattr(self._mqtt, "is_connected", False):
            self._subscribe_storage(self._mqtt, topics)
            return self._mqtt
        cfg = getattr(self.host.aw, "mqttConfig", None)
        if cfg is None or not getattr(cfg, "username", "") or not getattr(cfg, "password", ""):
            _logd.info("StorageTab: no MQTT broker credentials configured — "
                       "cannot read the storage sensor")
            return None
        try:
            from tilauscope.mqttbridge import TilauscopeMQTTClient
            _logd.info("StorageTab: starting dedicated MQTT client (broker=%s:%s)",
                       getattr(cfg, "broker_url", "?"), getattr(cfg, "port", "?"))
            self._mqtt = TilauscopeMQTTClient(cfg, self.host.aw)
            connected = self._mqtt.start()
            _logd.info("StorageTab: dedicated MQTT connected=%s", connected)
            if connected:
                self._subscribe_storage(self._mqtt, topics)
                return self._mqtt
            self._mqtt = None
            return None
        except Exception:
            _logd.exception("StorageTab: dedicated MQTT start failed")
            self._mqtt = None
            return None

    def _subscribe_storage(self, client, topics: list[str]) -> None:
        """Explicitly subscribe to the storage topics on whichever client we use
        (retained messages then arrive immediately)."""
        try:
            if self._sub_client is not client:
                self._sub_client = client
                self._subscribed = set()
            port_client = getattr(getattr(client, "_port", None), "client", None)
            if port_client is None:
                return
            qos = getattr(getattr(client, "config", None), "qos", 0)
            for t in topics:
                if t and t not in self._subscribed:
                    port_client.subscribe(t, qos=qos)
                    self._subscribed.add(t)
                    _logd.info("StorageTab: subscribed to storage topic '%s'", t)
        except Exception:
            _logd.exception("StorageTab: subscribe to storage topics failed")

    def _active_client(self, topics: list[str]):
        """Prefer the live roast client (avoids a 2nd broker connection during a
        roast); otherwise use our own dedicated connection."""
        try:
            ports = getattr(self.host.aw.qmc, "tilau_mqtt_ports", None)
            roast_client = getattr(ports, "client", None) if ports else None
            if roast_client is not None and getattr(roast_client, "is_connected", False):
                self._subscribe_storage(roast_client, topics)
                return roast_client
        except Exception:
            _logd.exception("StorageTab: inspecting roast MQTT client failed")
        return self._ensure_dedicated(topics)

    def _poll_topic(self, topic: str):
        """Latest cached payload for one MQTT topic (None if unavailable)."""
        if not topic:
            return None
        client = self._active_client([topic])
        if client is None:
            return None
        try:
            return client.poll(topic)
        except Exception:
            _logd.exception("StorageTab: poll('%s') failed", topic)
            return None

    def _read_ambient(self) -> tuple[float | None, float | None, bool]:
        """Read humidity and temperature independently — they may live on
        different topics (and different fields within each payload)."""
        s = QSettings()
        h_topic = s.value(STORAGE_HUMIDITY_TOPIC_KEY, "", type=str) or ""
        t_topic = s.value(STORAGE_TEMP_TOPIC_KEY, "", type=str) or ""
        h_field = s.value(STORAGE_HUMIDITY_FIELD_KEY, DEFAULT_HUMIDITY_FIELD, type=str)
        t_field = s.value(STORAGE_TEMP_FIELD_KEY, DEFAULT_TEMP_FIELD, type=str)
        topics = [x for x in (h_topic, t_topic) if x]
        rh = temp = None
        if topics:
            client = self._active_client(topics)
            if client is None:
                _logd.info("StorageTab: no live MQTT client — storage sensor not read")
            else:
                h_payload = client.poll(h_topic) if h_topic else None
                t_payload = client.poll(t_topic) if t_topic else None
                rh = SA.extract_value(h_payload, h_field) if h_topic else None
                temp = SA.extract_value(t_payload, t_field) if t_topic else None
                _logd.info(
                    "StorageTab read: hum topic='%s' payload=%r -> rh=%s | "
                    "temp topic='%s' payload=%r -> temp=%s",
                    h_topic, h_payload, rh, t_topic, t_payload, temp,
                )
        return rh, temp, bool(h_topic)

    def _refresh_ambient_only(self) -> None:
        try:
            self._ambient_rh, self._ambient_temp, configured = self._read_ambient()
            self._render_banner(configured)
            # a fresher ambient changes trends — recompute the fiche & trend column
            self._populate_table()
            self._render_fiche()
        except Exception:
            pass

    def _render_banner(self, configured: bool) -> None:
        if not configured:
            self.banner_value.setText(QApplication.translate("tilauscope_storage", "Storage ambient not configured"))
            self.banner_source.setText(QApplication.translate("tilauscope_storage", "Set the humidity sensor topic"))
            return
        if self._ambient_rh is None:
            self.banner_value.setText(QApplication.translate("tilauscope_storage", "Waiting for the sensor…"))
            self.banner_source.setText(QApplication.translate("tilauscope_storage", "storage sensor · MQTT"))
            return
        parts = [f"{self._ambient_rh:.0f} % RH"]
        if self._ambient_temp is not None:
            parts.append(f"{self._ambient_temp:.0f} °C")
        self.banner_value.setText("  ·  ".join(parts))
        self.banner_source.setText(QApplication.translate("tilauscope_storage", "storage sensor · MQTT"))

    def refresh(self) -> None:
        try:
            self._ambient_rh, self._ambient_temp, configured = self._read_ambient()
            self._render_banner(configured)
            self._render_orphan_banner()
            self._populate_table()
            self._render_fiche()
        except Exception:
            # Never let the Stockage tab raise into the BeanCave dialog.
            pass

    def _in_stock_beans(self) -> list["GreenBean"]:
        beans = list(getattr(self.host, "green_beans", []) or [])
        thr = load_thresholds()
        stock = [b for b in beans if getattr(b, "weight_left", 0.0) > 0.0]
        stock.sort(
            key=lambda b: (
                _ZONE_RANK[SA.classify_aw(getattr(b, "water_activity", 0.0), thr)],
                getattr(b, "name", ""),
            )
        )
        return stock

    def _populate_table(self) -> None:
        thr = load_thresholds()
        self._rows = self._in_stock_beans()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._rows))
        for r, b in enumerate(self._rows):
            aw = getattr(b, "water_activity", 0.0)
            zone = SA.classify_aw(aw, thr)
            trend = SA.compute_trend(aw, self._ambient_rh, getattr(b, "conditioning", ""))
            color = _ZONE_COLOR[zone]

            name = getattr(b, "name", "") or QApplication.translate("tilauscope_storage", "(unnamed)")
            crop = getattr(b, "crop", 0)
            sub = f" '{str(crop)[-2:]}" if crop else ""
            self._set_cell(r, 0, f"{name}{sub}")
            self._set_cell(r, 1, f"{getattr(b, 'weight_left', 0.0) / 1000:.1f} kg", align_right=True)
            sacks = getattr(b, "sacks", []) or []
            self._set_cell(r, 2, "  ".join(sacks) if sacks else "—")
            aw_txt = f"{aw:.2f}" if aw > 0 else "—"
            self._set_cell(r, 3, aw_txt, color=color, bold=True, tooltip=zone_label(zone))
            self._set_cell(r, 4, conditioning_label(getattr(b, "conditioning", "")))
            self._set_cell(r, 5, trend_label(trend),
                           color=self._trend_color(trend))
        self.table.blockSignals(False)

        # keep / restore selection
        if self._rows:
            target = 0
            for i, b in enumerate(self._rows):
                if getattr(b, "uuid", "") == self._selected_uuid:
                    target = i
                    break
            self.table.selectRow(target)

    def _trend_color(self, trend: MoistureTrend) -> str:
        if trend is MoistureTrend.GAINING:
            return Z_WATCH
        if trend is MoistureTrend.DRYING:
            return Z_TOO_DRY
        return THEME["SUBTEXT"]

    def _set_cell(self, r: int, c: int, text: str, *, align_right: bool = False,
                  color: str | None = None, bold: bool = False,
                  tooltip: str | None = None) -> None:
        it = QTableWidgetItem(text)
        flags = Qt.AlignmentFlag.AlignVCenter | (
            Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignLeft
        )
        it.setTextAlignment(flags)
        if color:
            it.setForeground(QBrush(QColor(color)))
        if bold:
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        if tooltip:
            it.setToolTip(tooltip)
        self.table.setItem(r, c, it)

    def _selected_bean(self) -> "GreenBean | None":
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def _on_row_selected(self) -> None:
        b = self._selected_bean()
        self._selected_uuid = getattr(b, "uuid", "") if b else ""
        self._render_fiche()

    def _render_fiche(self) -> None:
        b = self._selected_bean()
        if b is None:
            self.f_name.setText(QApplication.translate("tilauscope_storage", "No bean in stock"))
            self.f_meta.setText("")
            self.f_stock.setText("")
            self.f_aw.setText("—")
            self.f_aw.setStyleSheet(f"font-size:30px; font-weight:700; color:{THEME['SUBTEXT']};")
            self.f_zone.setText("")
            self.f_conditioning.setEnabled(False)
            self.f_measure_btn.setEnabled(False)
            self.f_verdict.setText("")
            self._render_sacks(None)
            return

        thr = load_thresholds()
        aw = getattr(b, "water_activity", 0.0)
        cond = getattr(b, "conditioning", "")
        a = SA.assess(aw, self._ambient_rh, cond, thr)
        color = _ZONE_COLOR[a.zone]

        self.f_name.setText(getattr(b, "name", "") or QApplication.translate("tilauscope_storage", "(unnamed)"))
        meta_bits = [x for x in (getattr(b, "process", ""), getattr(b, "species", "")) if x]
        crop = getattr(b, "crop", 0)
        if crop:
            meta_bits.append(f"{QApplication.translate("tilauscope_storage", 'crop')} '{str(crop)[-2:]}")
        self.f_meta.setText(" · ".join(meta_bits))
        nsacks = len(getattr(b, "sacks", []) or [])
        sack_txt = f"{nsacks} {QApplication.translate("tilauscope_storage", 'lot(s)')} · " if nsacks else ""
        self.f_stock.setText(f"{sack_txt}{getattr(b, 'weight_left', 0.0) / 1000:.1f} kg")

        self.f_aw.setText(f"{aw:.2f}" if aw > 0 else "—")
        self.f_aw.setStyleSheet(f"font-size:30px; font-weight:700; color:{color};")
        self.f_zone.setText(zone_label(a.zone))
        self.f_zone.setStyleSheet(f"font-size:13px; font-weight:700; color:{color};")

        self.f_measure_btn.setEnabled(True)
        self.f_conditioning.setEnabled(True)
        self.f_conditioning.blockSignals(True)
        target = self.f_conditioning.findData(cond or "")
        self.f_conditioning.setCurrentIndex(target if target >= 0 else 0)
        self.f_conditioning.blockSignals(False)

        self._render_sacks(b)
        self.f_verdict.setText(self._verdict_html(a))

    def _verdict_html(self, a: SA.StorageAssessment) -> str:
        lines: list[str] = []
        if a.aw <= 0:
            lines.append(QApplication.translate("tilauscope_storage", "Measure aw with the AquaGauge to assess conservation."))
            return "<br>".join(lines)

        if a.trend is MoistureTrend.SEALED:
            lines.append(QApplication.translate("tilauscope_storage", "🔒 Sealed conditioning: negligible exchange, aw is protected."))
        elif a.trend is MoistureTrend.GAINING:
            lines.append(
                QApplication.translate("tilauscope_storage", "↑ <b>Gaining moisture</b>: your storage is more humid than the bean, "
                   "aw is drifting up.")
            )
        elif a.trend is MoistureTrend.DRYING:
            lines.append(QApplication.translate("tilauscope_storage", "↓ Slow drying: your storage is drier than the bean."))
        elif a.trend is MoistureTrend.STABLE:
            lines.append(QApplication.translate("tilauscope_storage", "= Stable equilibrium with your current ambient."))
        else:
            lines.append(QApplication.translate("tilauscope_storage", "Connect a storage MQTT sensor to estimate the trend."))

        if a.equilibrium_moisture is not None and a.trend not in (
            MoistureTrend.SEALED, MoistureTrend.UNKNOWN
        ):
            lines.append(
                f"{QApplication.translate("tilauscope_storage", 'Target equilibrium moisture')}: ~{a.equilibrium_moisture:.1f} %"
            )

        if a.zone is AwZone.MOLD_RISK:
            lines.append(
                QApplication.translate("tilauscope_storage", "⚠ <b>Mould zone</b>: recondition or roast in priority; "
                   "aim for storage &lt; 60 % RH.")
            )
        elif a.zone is AwZone.WATCH:
            lines.append(QApplication.translate("tilauscope_storage", "To watch: keep the ambient below 65 % RH."))
        elif a.zone is AwZone.TOO_DRY:
            lines.append(QApplication.translate("tilauscope_storage", "Dry bean: more fragile aromatics, faster staling."))

        return "<br>".join(lines)

    # -- actions ------------------------------------------------------------- #

    def _on_conditioning_changed(self, _idx: int) -> None:
        b = self._selected_bean()
        if b is None:
            return
        key = self.f_conditioning.currentData() or ""
        if getattr(b, "conditioning", "") == key:
            return
        b.conditioning = key
        try:
            self.host.save_green_beans()
        except Exception:
            pass
        # refresh the affected row + fiche verdict
        self._populate_table()
        self._render_fiche()

    def _open_mqtt_config(self) -> None:
        dlg = StorageMqttConfigDialog(self)
        geo = self.host.geometry()
        dlg.adjustSize()
        dlg.move(geo.center().x() - dlg.width() // 2,
                 geo.center().y() - dlg.height() // 2)
        if dlg.exec():
            self.refresh()

    def _open_aw_editor(self) -> None:
        """Reuse the validated Characteristics editor (hosts the 💧 Aw window)."""
        b = self._selected_bean()
        if b is None:
            return
        try:
            from tilauscope.beancave_zone_editors import ZoneEditorDialog
            dlg = ZoneEditorDialog(self.host, b, "characteristics")
            dlg.adjustSize()
            geo = self.host.geometry()
            dlg.move(geo.center().x() - dlg.width() // 2,
                     geo.center().y() - dlg.height() // 2)
            dlg.exec()
        except Exception:
            pass
        self.refresh()

    # ## TILAU ## ── sack labels: assign / release / reclaim (design v4 §9) ──

    def _all_beans(self) -> list["GreenBean"]:
        """The FULL catalogue — never the table's list, which filters on stock."""
        return list(getattr(self.host, "green_beans", []) or [])

    def _save_beans(self) -> None:
        try:
            self.host.save_green_beans()
        except Exception:
            _logd.exception("StorageTab: saving green beans failed")

    def _render_sacks(self, bean: "GreenBean | None") -> None:
        """Fill the slot-A block, hiding it entirely when it serves no purpose."""
        if bean is None:
            self.f_sacks_box.setVisible(False)
            return
        sacks = list(getattr(bean, "sacks", None) or [])
        try:
            available = SackPool.available_ids(self._all_beans())
        except Exception:
            _logd.exception("StorageTab: reading the sack pool failed")
            available = []
        # no sack on this bean and nothing to assign -> the feature is not in use
        self.f_sacks_box.setVisible(bool(sacks or available))
        self.f_sack_chips.set_sacks(sacks)
        self.f_assign_btn.setEnabled(True)

    def _assign_sack(self) -> None:
        bean = self._selected_bean()
        if bean is None:
            return
        try:
            dlg = SackAssignDialog(self, bean, self._all_beans(), host=self.host)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            sack_id = dlg.selected_id()
            if not sack_id:
                return
            bean.sacks = list(getattr(bean, "sacks", None) or []) + [sack_id]
            SackPool.mark_assigned(sack_id)
            self._save_beans()
            self.refresh()
            _logd.debug(f"Sack {sack_id} assigned to '{getattr(bean, 'name', '?')}'")
        except Exception:
            _logd.exception("StorageTab: sack assignment failed")

    def _release_sack(self, sack_id: str) -> None:
        """✕ on a chip — the physical bag is empty, the label goes back to the pool."""
        bean = self._selected_bean()
        if bean is None:
            return
        try:
            if not confirm_release(self, sack_id):
                return
            release_sacks(bean, [sack_id])
            self._save_beans()
            self.refresh()
        except Exception:
            _logd.exception(f"StorageTab: releasing sack {sack_id} failed")

    def _render_orphan_banner(self) -> None:
        try:
            self._orphans = orphaned_sacks(self._all_beans())
        except Exception:
            _logd.exception("StorageTab: orphan scan failed")
            self._orphans = []
        n = sum(len(ids) for _b, ids in self._orphans)
        if n:
            self.orphan_lbl.setText(QApplication.translate(
                "tilauscope_storage",
                "{0} label(s) are held by beans with no stock left.").format(n))
        self.orphan_banner.setVisible(bool(n))

    def _open_reclaim(self) -> None:
        if not getattr(self, "_orphans", None):
            return
        try:
            dlg = ReclaimSacksDialog(self, self._orphans)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            if dlg.apply():
                self._save_beans()
                self.refresh()
        except Exception:
            _logd.exception("StorageTab: reclaiming labels failed")

    def _open_sack_labels(self) -> None:
        try:
            from tilauscope.sack_manager import SackLabelsDialog
            dlg = SackLabelsDialog(self.host)
            dlg.exec()
        except Exception:
            pass
        self.refresh()


# --------------------------------------------------------------------------- #
# Storage-sensor MQTT config dialog
# --------------------------------------------------------------------------- #

class StorageMqttConfigDialog(QDialog):
    """Configure the storage-room ambient sensor.

    Humidity and temperature are set INDEPENDENTLY — each has its own topic and
    its own field/path, because they are not necessarily on the same sub-topic.
    A live 'Tester' preview shows the raw payload so the right field is obvious.
    """

    def __init__(self, tab: "StorageTab") -> None:
        super().__init__(tab)
        self._tab = tab
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(540)

        s = QSettings()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("StorageCfgCard")
        card.setStyleSheet(
            f"""
            #StorageCfgCard {{
                background: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 14px;
            }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QLineEdit {{
                background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 7px; padding: 6px 9px;
            }}
            QLineEdit:focus {{ border: 1px solid {THEME['ACCENT']}; }}
            """
        )
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        title = QLabel("🌡️  " + QApplication.translate("tilauscope_storage", "Storage sensor (MQTT)"))
        title.setStyleSheet(f"color:{THEME['TEXT']}; font-size:15px; font-weight:700;")
        v.addWidget(title)
        hint = QLabel(QApplication.translate("tilauscope_storage", 
            "Humidity and temperature can be on different topics. "
            "Leave the field empty if the topic already publishes a bare value; "
            "otherwise give the key (e.g. humidity) or a path (e.g. data.rh)."
        ))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px;")
        v.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(self._lbl(QApplication.translate("tilauscope_storage", "Humidity — topic")), 0, 0)
        self.h_topic = QLineEdit(s.value(STORAGE_HUMIDITY_TOPIC_KEY, "", type=str) or "")
        self.h_topic.setPlaceholderText("tilauscope/storage/humidity")
        grid.addWidget(self.h_topic, 0, 1)
        grid.addWidget(self._lbl(QApplication.translate("tilauscope_storage", "Humidity — field")), 1, 0)
        self.h_field = QLineEdit(s.value(STORAGE_HUMIDITY_FIELD_KEY, DEFAULT_HUMIDITY_FIELD, type=str))
        self.h_field.setPlaceholderText(DEFAULT_HUMIDITY_FIELD)
        grid.addWidget(self.h_field, 1, 1)
        self.h_preview = self._preview_lbl()
        grid.addWidget(self.h_preview, 2, 1)

        grid.addWidget(self._lbl(QApplication.translate("tilauscope_storage", "Temperature — topic")), 3, 0)
        self.t_topic = QLineEdit(s.value(STORAGE_TEMP_TOPIC_KEY, "", type=str) or "")
        self.t_topic.setPlaceholderText("tilauscope/storage/temperature")
        grid.addWidget(self.t_topic, 3, 1)
        grid.addWidget(self._lbl(QApplication.translate("tilauscope_storage", "Temperature — field")), 4, 0)
        self.t_field = QLineEdit(s.value(STORAGE_TEMP_FIELD_KEY, DEFAULT_TEMP_FIELD, type=str))
        self.t_field.setPlaceholderText(DEFAULT_TEMP_FIELD)
        grid.addWidget(self.t_field, 4, 1)
        self.t_preview = self._preview_lbl()
        grid.addWidget(self.t_preview, 5, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        btns = QHBoxLayout()
        test_btn = QPushButton("🔍  " + QApplication.translate("tilauscope_storage", "Test"))
        test_btn.setStyleSheet(self._tab._btn_css())
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.clicked.connect(self._test)
        cancel_btn = QPushButton(QApplication.translate("tilauscope_storage", "Cancel"))
        cancel_btn.setStyleSheet(self._tab._btn_css())
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(QApplication.translate("tilauscope_storage", "Save"))
        save_btn.setStyleSheet(self._accent_css())
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        btns.addWidget(test_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        v.addLayout(btns)

        self._test()

    def _lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:12px;")
        return lbl

    def _preview_lbl(self) -> QLabel:
        lbl = QLabel("")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:10px; font-family: monospace;")
        return lbl

    def _accent_css(self) -> str:
        return f"""
            QPushButton {{
                background-color: rgba(137,180,250,40);
                color: {THEME['ACCENT']};
                border: 1px solid rgba(137,180,250,120);
                border-radius: 8px; padding: 6px 14px; font-weight: 700;
            }}
            QPushButton:hover {{ background-color: rgba(137,180,250,70); }}
        """

    def _test(self) -> None:
        for topic_edit, field_edit, prev in (
            (self.h_topic, self.h_field, self.h_preview),
            (self.t_topic, self.t_field, self.t_preview),
        ):
            topic = topic_edit.text().strip()
            if not topic:
                prev.setText("")
                continue
            payload = self._tab._poll_topic(topic)
            mono = "font-size:10px; font-family: monospace;"
            if payload is None:
                prev.setText("⚠ " + QApplication.translate("tilauscope_storage", "no data received on this topic"))
                prev.setStyleSheet(f"color:{THEME['WARNING']}; {mono}")
                continue
            val = SA.extract_value(payload, field_edit.text().strip())
            raw = str(payload)
            if len(raw) > 90:
                raw = raw[:90] + "…"
            if val is None:
                prev.setText("⚠ " + QApplication.translate("tilauscope_storage", "field not found") + f"  ·  {raw}")
                prev.setStyleSheet(f"color:{THEME['WARNING']}; {mono}")
            else:
                prev.setText(f"✓ {val:.1f}  ·  {raw}")
                prev.setStyleSheet(f"color:{THEME['SUCCESS']}; {mono}")

    def _save(self) -> None:
        s = QSettings()
        s.setValue(STORAGE_HUMIDITY_TOPIC_KEY, self.h_topic.text().strip())
        s.setValue(STORAGE_HUMIDITY_FIELD_KEY, self.h_field.text().strip())
        s.setValue(STORAGE_TEMP_TOPIC_KEY, self.t_topic.text().strip())
        s.setValue(STORAGE_TEMP_FIELD_KEY, self.t_field.text().strip())
        self.accept()
