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

from __future__ import annotations

import json
import time
import os
from typing import Any, override, TYPE_CHECKING

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401
    pass  # pylint: disable=unused-import
import re # For sorting alog files
from pathlib import Path

#import matplotlib.pyplot as plt



from artisanlib.atypes import ProfileData

from PyQt6.QtCore import (QMutex, QMutexLocker,QStandardPaths, Qt, pyqtSlot, QSettings, QThread, QPoint, QTimer, QEvent) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QCloseEvent, QGuiApplication, QCursor, QKeyEvent) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QComboBox, QSizeGrip, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QTabWidget, # @UnusedImport @Reimport  @UnresolvedImport
                                QGroupBox, QTableWidget, QHeaderView, QStyledItemDelegate, QListView, QFrame, QFileDialog, QMessageBox, QDialog, QListWidget, QDoubleSpinBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.niimprint import NiimbotBLE
from tilauscope.tilau_ble_scanner import TilauBLEScanner
from tilauscope.theme_qss import base_qss
from tilauscope.tilauscope_types import (BeanCaveContainer, show_styled_message,
                                         THEME, _IS_MACOS, _IS_WINDOWS,
                                         open_in_os_viewer, call_later)
from tilauscope.lebrewroastsee import LebrewWaterActivityChecker
from tilauscope.roasters import RoasterManager
from tilauscope.alogmanager import (AlogCacheCollection, AlogIndex, _AlogCacheIndexingWorker, directory_changed)
from tilauscope.cave.common import (PKG_DIR,
    _log, _logd, C0_COLOR_KEY, C_BT_COLOR_KEY, C_DTR_COLOR_KEY, C_WL_COLOR_KEY,
    DEFAULT_C0, DEFAULT_C_BT, DEFAULT_C_DTR, DEFAULT_C_WL,
    greencave_headers, apply_mica_acrylic_effect)
from tilauscope.cave.widgets import (
    _DensityFloatWindow)
from tilauscope.cave.workers import (
    stop_worker_thread,
    _RoasterLoadWorker)


class LifecycleMixin:
    """Construction, teardown, settings and the folders BeanCave reads.

    Everything with a lifetime: the attributes the dialog declares, the
    background jobs it starts and must stop, the theme, the stored geometry and
    the two directory choices the rest of the dialog depends on.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """

    def __init__(self, aw:'ApplicationWindow', uuid:str="") -> None:
        super().__init__(parent=aw)
        # before setting up information for ui, let's work on security
        self.shutdown_lock = QMutex() # Le verrou
        self.is_shutting_down = False  # Le drapeau
        self._niimbot_connected = False  # True uniquement quand imprimante prête (heartbeat OK)
        self._niimbot_ble_up    = False  # True dès que la connexion BLE est établie (indép. du papier)
        self._niimbot_poll_timer: QTimer | None = None   # timer heartbeat 5 s
        self._niimbot_poll_thread: QThread | None = None # thread du dernier poll
        self._niimbot_prev_closingstate: int | None = None  # pour détecter réouverture capot
        if _IS_WINDOWS:
            # Tool + Window: stays above aw without system-wide StaysOnTopHint (avoids crash on open)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Window
                | Qt.WindowType.Tool
            )
        else:
            # macOS: Dialog keeps the window in aw's z-order stack
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Window
                | Qt.WindowType.Dialog
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if _IS_WINDOWS:
            apply_mica_acrylic_effect(self)

        self._drag_pos = None

        self.aw = aw
        self.ai = aw.tilau_aiConfig

        # scale-piloted density measurement window
        self._density_window: '_DensityFloatWindow | None' = None
        self._density_scale_was_connected: bool = False

        self._roaster_thread: QThread | None = None
        self._ble_thread:     QThread | None = None   # obsolète — conservé pour _cancel_threads
        self._ble_scanner:    TilauBLEScanner | None = None
        self._alog_thread:    QThread | None = None

        self.coffee_beans_species:list[str] = []
        self.coffee_beans_categories:list[str] = []
        self.coffee_processing_methods:dict[str,list[str]] = {}
        self.coffee_producing_countries:list[str] = []
        self.coffee_bean_types:dict[str,list[str]] = {}

        self.initialized = False
        self.hasfinished = False # used my file load
        self.app = self.aw.app
        self.alog_directory = Path("") # Pour stocker le chemin du répertoire ALog
        self.beancave_directory = Path("") # Nouvelle variable pour le répertoire de beancave.json
        self.is_directory_defined = False

        self.C0_COLOR: float = DEFAULT_C0
        self.C_BT_COLOR: float = DEFAULT_C_BT
        self.C_DTR_COLOR: float = DEFAULT_C_DTR
        self.C_WL_COLOR: float = DEFAULT_C_WL

        self.roaster_manager:RoasterManager | None = None
        # Charger le fichier JSON (ajustez le chemin selon votre structure)

        self.current_roaster_model = "" # Sera peuplé par load_settings
        self.probe_override:bool = False

        # process uuid and actual filename loaded in artisan to preposition cursors
        self.uuid_pattern = re.compile(r'uuid: \s*([a-fA-F0-9-]{36})')

        self.load_parameters()
        self.load_settings()

        self.cave: BeanCaveContainer | None = None
        self.load_green_beans()

        # start the background task to collect alog information and avoid to read from multiple threads the same thing
        # Seeded from the persisted index: the list paints from the previous
        # session's entries while the background pass reconciles with disk.
        self._metadata_cache = AlogCacheCollection(
            records=dict(AlogIndex.instance().records(Path(self.alog_directory)))
            if self.alog_directory else {})
        self._cache_thread = None
        self._cache_worker = None

        # Create the 5-minute background refresh timer
        self.cache_refresh_timer = QTimer(self)
        self.cache_refresh_timer.setInterval(5 * 60 * 1000) # 5 minutes in milliseconds
        self.cache_refresh_timer.timeout.connect(self.trigger_cache_refresh)

        # Trigger once on initial startup/entry
        self.trigger_cache_refresh()
        self.cache_refresh_timer.start()

        self.last_sorted_column = -1
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.last_plot_data: dict|None = None
        self._displayed_fname: str = ""   # roast the curve is currently showing
        self._loading_fname: str = ""     # roast the in-flight load is for

        self.np: NiimbotBLE|None = None
        self._print_pill = None   # host A — pastille de progression d'impression
        self.bleRoastSeeAGDevice: LebrewWaterActivityChecker|None = None
        self.bleTilauAmbientDevice = None  # BeanCave-managed ambient probe (BME280), same pattern as Lebrew

        self.deviceID: str = ""
        self.current_bean_name = ""
        self.roast_plan_inputs: dict[str, QDoubleSpinBox] = {}
        self.status_label: QLabel|None = None
        self.input_group: QGroupBox|None = None
        self.generate_plan_btn: QPushButton|None = None
        self.injectinartisan_btn: QPushButton|None = None
        self.lastprofiledata:ProfileData
        self._alog_cache: dict[str, tuple[float, ProfileData]] = {}  # LRU cap = 5
        # Recomputed RoR series, kept beside the profile they came from. The
        # entry holds the profile object itself, so identity stays valid for as
        # long as the result is cached. Never stored inside the profile dict:
        # a milestone edit writes that dict back to the .alog.
        self._deltas_cache: list[tuple[object, tuple, list|None]] = []  # cap = 5
        self._event_vlines: dict[str, object] = {}   # label → axvline artist
        self._event_annots: dict[str, object] = {}   # label → annotation artist
        self._event_dots:   dict[str, object] = {}   # label → bt dot artist
        self._event_et_dots:   dict[str, object] = {}  # label → et dot artist
        self._event_et_annots: dict[str, object] = {}  # label → et annotation artist
        self._pending_timeindex: list | None = None  # unsaved timeindex edits; None = no pending
        # ── Multi-curve comparison state ──────────────────────────────────────
        self._multi_mode: bool = False           # True dès que ≥2 courbes sélectionnées
        self._multi_curves: list[dict] = []      # [{filepath, data, deltabt, deltaet, color, title}]
        self._multi_load_queue: list[str] = []   # filepaths en attente de chargement
        self._multi_load_idx: int = 0            # index courant dans la queue
        self._multi_alog_thread: QThread | None = None   # thread courant multi
        self._multi_alog_worker: object | None  = None   # worker courant multi
        self._alog_uuid_index:      dict[str, list[str]] = {}  # uuid  → [filename, ...]
        self._alog_file_uuid:       dict[str, str]        = {}  # filename → uuid  (reverse)
        self.datatable = QTableWidget()
        self.datatable.setAlternatingRowColors(True)
        # Optional: Hide the vertical header (row numbers) for a cleaner look
        self.datatable.verticalHeader().setVisible(False)

        self.createdatatable()
        self.apply_modern_theme()
        self.setup_ui()

        self.load_settings() #reload settings for deviations
        self._validate_startup_directories()

        #if a bean was given in parameter, search for uuid, then go to the green bean record and the roast itself as well in 3rd tab
        b = self._get_uuid_from_bean_description(uuid) # get uuid and validate that it is in the list

        self.is_directory_defined:bool = str(self.beancave_directory) != "" and str(self.alog_directory) != ""

        # Positioning on the green bean if a bean match was found for the provided uuid parameter
        self.populate_table()
        if b != "":
            # set current record of the datatable pointing to the matched bean's uuid
            for row in range(self.datatable.rowCount()):
                # Use the uuid field (last column) to find the match
                uuid_item = self.datatable.item(row, len(greencave_headers) - 1)
                if uuid_item and uuid_item.text() == b.uuid:
                    self.datatable.selectRow(row)
                    self.datatable.scrollToItem(uuid_item)
                    QTimer.singleShot(600, self._update_roast_plan_ui_state)
                    break

        # by default disable all buttons
        self.add_button.setEnabled(True)
        self.clear_button.setEnabled(False)
        self.generate_label_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.inject_from_ai_button.setEnabled(False)
        self.update_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.generate_qr_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.generate_card_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.roast.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.remove_button.setEnabled(False)
        self.new_crop_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.update_ui_visibility()
        if self.is_directory_defined:
            self.main_tab.setFocus()
        else:
            self.main_tab.setFocus()
        self.aw.beanCaveMenuAction.setChecked(True)

        self.oldPos = QPoint()   # null until first mouse press
        self.global_pos = QPoint(0, 0) # For tooltip positioning
        # macOS: explicit raise needed after Tool-window z-order shuffle
        if _IS_MACOS:
            self.raise_()
            self.activateWindow()
        self.initialized = True

        if self.aw:
            self.aw.installEventFilter(self)

        # Replace Artisan AlarmDlg with TilauScope editor
        def _tilau_alarmconfig(_: bool = False) -> None:
            from tilauscope.alarms import TilauAlarmDlg
            dlg = TilauAlarmDlg(self.aw, self.aw)
            dlg.show()
        self.aw.alarmconfig = _tilau_alarmconfig   # type: ignore[method-assign]

        QTimer.singleShot(0, self._start_ble_scanner)

        # the read-only Records web server is now owned app-level by
        # TilauWebHost (started with Artisan/TilauScope). BeanCave only supplies
        # the roast/bean resolvers once its catalogue is loaded.
        self._web_records = None  # deprecated: kept for compatibility, unused
        QTimer.singleShot(0, self._register_web_resolvers)

        # first-run configuration assistant (once, before what's-new)
        QTimer.singleShot(500, self._maybe_show_onboarding)

    def _maybe_show_onboarding(self) -> None:
        try:
            from tilauscope.onboarding import maybe_show_onboarding
            self._onboarding_dlg = maybe_show_onboarding(self, self.aw)
        except Exception:  # pylint: disable=broad-except
            _logd.exception("onboarding assistant failed to start")

    def _find_item_by_metadata(self, list_widget: QListWidget, key: str, value: Any) :
        """
        Scans the QListWidget for an item containing a specific metadata key-value pair.
        """
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            metadata = item.data(Qt.ItemDataRole.UserRole)

            # Check if metadata exists, is a dictionary, and matches our criteria
            if isinstance(metadata, dict) and metadata.get(key) == value:
                return row

        return None


    @override
    def eventFilter(self, obj, event):
        if _IS_MACOS and obj == self.aw and event.type() == QEvent.Type.WindowActivate:
            active = QApplication.activeWindow()
            if active is None or active is self.aw:
                QTimer.singleShot(200, self._safe_raise)
        # Canvas right-click / two-finger tap: intercept before Qt default context menu
        if (obj is getattr(self, 'canvas', None)
                and event.type() == QEvent.Type.ContextMenu):
            if not self._multi_mode:
                self._build_marker_menu(event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos(),
                                        event.pos()       if hasattr(event, 'pos')       else None)
            return True  # always consume — prevent Qt's default empty menu
        return super().eventFilter(obj, event)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        """Re-raise BeancaveDlg when macOS moves focus to aw after a Tool window closes."""
        super().changeEvent(event)
        if _IS_MACOS and event.type() == QEvent.Type.WindowDeactivate:
            QTimer.singleShot(150, self._safe_raise)

    @staticmethod
    def _has_visible_child_dialog(roots, exclude=()) -> bool:
        """Return True if any visible QDialog (excluding self) is a descendant of any root."""
        root_set = set(roots)
        exclude_set = set(exclude)
        for widget in QApplication.topLevelWidgets():
            if widget in exclude_set:
                continue
            if not (isinstance(widget, QDialog) and widget.isVisible()):
                continue
            p = widget.parent()
            while p is not None:
                if p in root_set:
                    return True
                p = p.parent()
        return False

    def _safe_raise(self):
        """Bring BeancaveDlg to front only when no descendant dialog is open."""
        if not self.isVisible():
            return
        active = QApplication.activeWindow()
        # Exclude self: BeancaveDlg is itself a QDialog child of aw
        has_child = self._has_visible_child_dialog((self, self.aw), exclude=(self,))
        if active is not None and active is not self.aw and active is not self:
            return
        if has_child:
            QTimer.singleShot(150, self._safe_raise)
            return
        self.raise_()
        self.activateWindow()


    def _start_ble_scanner(self) -> None:
        """
        Démarre le scanner BLE centralisé TilauBLEScanner.
        Remplace _BleInitWorker + _scan_and_connect_worker individuels.
        Un seul scan toutes les 8s distribué à tous les workers.
        """
        from artisanlib.ble_port import bluetooth_enabled
        if not bluetooth_enabled():
            _log.warning("Bluetooth non disponible — TilauBLEScanner non démarré")
            self.niimbot_overlay.update_status(
                QApplication.translate("tilauscope_beancave", "Printer: Bluetooth N/A"),
                THEME["SUBTEXT"]
            )
            self.print_label_button.setEnabled(False)
            return

        # Créer NiimbotBLE et brancher ses signaux.
        # Si un UUID est mémorisé dans les settings, on le passe directement
        # → TilauBLEScanner connectera par adresse sans scan par préfixe.
        self.np = NiimbotBLE(
            known_uuid=getattr(self.aw, "bleNiimbotDeviceName", None) or None
        )
        self.np.aw = self.aw  # référence pour auto-save UUID après connexion
        self.np.at_connected.connect(self.niimbot_connected)
        self.np.at_disconnected.connect(self.niimbot_disconnected)

        # Créer Lebrew si adresse connue
        if self.aw.bleRoastSeeAGDeviceName is not None and self.bleRoastSeeAGDevice is None:
            self.bleRoastSeeAGDevice = LebrewWaterActivityChecker(self.aw.bleRoastSeeAGDeviceName)
            self.bleRoastSeeAGDevice.connected_signal.connect(self.slotStartLebrewAG)
            self.bleRoastSeeAGDevice.disconnected_signal.connect(self.slotStopLebrewAG)
            self.bleRoastSeeAGDevice.wa_changed_signal.connect(self.on_read_water_activity)

        # Ambient probe (TilauAmbient / BME280) — same managed pattern
        # as Lebrew above. It connects by BLE address on construction, so it does
        # not need the centralised scanner (no on_devices_found).
        if self.aw.bleTilauScopeDeviceName not in (None, "", "none") and self.bleTilauAmbientDevice is None:
            try:
                from tilauscope.tilauambient import TilauAmbient
                self.bleTilauAmbientDevice = TilauAmbient(uuid=self.aw.bleTilauScopeDeviceName, aw=self.aw)
                self.bleTilauAmbientDevice.connected_signal.connect(self.slotStartTilauAmbient)
                self.bleTilauAmbientDevice.disconnected_signal.connect(self.slotStopTilauAmbient)
                _log.info("TilauAmbient probe registered (managed by BeanCave)")
            except Exception as exc:  # noqa: BLE001
                _log.warning("TilauAmbient probe init failed: %s", exc)

        # Démarrer le scanner centralisé
        self._ble_scanner = TilauBLEScanner(self)
        self._ble_scanner.devices_found.connect(self.np.on_devices_found)
        if self.bleRoastSeeAGDevice is not None and hasattr(self.bleRoastSeeAGDevice, "on_devices_found"):
            # LebrewWaterActivityChecker doit implémenter on_devices_found(list) pour
            # bénéficier du scanner centralisé. Si la méthode n'existe pas encore,
            # Lebrew continue à scanner de son côté (comportement legacy).
            self._ble_scanner.devices_found.connect(self.bleRoastSeeAGDevice.on_devices_found)
            _log.info("Lebrew branché sur TilauBLEScanner")
        elif self.bleRoastSeeAGDevice is not None:
            _log.info("Lebrew: on_devices_found absent — scan legacy actif")
        self._ble_scanner.start()
        _log.info("TilauBLEScanner started — Niimbot + Lebrew enregistrés")

    # ------- record web resolvers (server owned by TilauWebHost) -------

    def _resolve_roast(self, roast_uuid: str):
        """roast_uuid -> .alog filepath (or None). Runs on the web server thread;
        reads only plain-python structures (metadata cache dataclasses)."""
        try:
            records = self._metadata_cache.records
            return next((m.filepath_str for m in records.values()
                         if m.roast_uuid.lower() == roast_uuid.lower()), None)
        except Exception:  # noqa: BLE001
            return None

    def _resolve_bean(self, uuid_str: str):
        """bean uuid -> plain dict of GreenBean fields (or None)."""
        try:
            uuidmap = getattr(self, 'uuidmap', None)
            bean = uuidmap.get(uuid_str) if uuidmap else None
            return bean.to_dict() if bean is not None else None
        except Exception:  # noqa: BLE001
            return None

    def _resolve_sack(self, sack_id: str):
        """sack id -> uuid of the bean currently holding it (or None)."""
        try:
            return next((bean.uuid for bean in self.green_beans
                         if sack_id in (getattr(bean, "sacks", None) or [])), None)
        except Exception:  # noqa: BLE001
            return None

    def _register_web_resolvers(self) -> None:
        """Hand BeanCave's roast/bean/sack resolvers to the app-level web host so the
        read-only Records server can answer /roast, /bean and /sack. The server itself
        is started by TilauWebHost with Artisan/TilauScope, not here, and only when
        the operator enabled it — registering resolvers is then a harmless no-op."""
        try:
            host = getattr(self.aw, 'tilau_web_host', None)
            if host is not None:
                host.set_records_resolvers(self._resolve_roast, self._resolve_bean, self._resolve_sack)
                _log.info("record web resolvers registered with TilauWebHost")
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _log.warning(f"record web resolvers not registered: {e}")

    def _snapshot_list_selection(self) -> None:
        """Record the roast currently highlighted + scroll position so a later
        list rebuild can restore the user's place. Guarded: an empty selection
        never clobbers a previously captured one (e.g. a transient state during
        the startup refresh, when the list is momentarily empty)."""
        try:
            cur_item = self.roast_list_widget.currentItem()
            cur_fname = (
                (cur_item.data(Qt.ItemDataRole.UserRole) or {}).get("raw_fname", "")
                if cur_item else "")
            if cur_fname:
                self._pending_restore_fname = cur_fname
                self._pending_restore_scroll = self.roast_list_widget.verticalScrollBar().value()
        except (RuntimeError, AttributeError):
            pass

    def trigger_cache_refresh(self):
        """Dispatches a background thread execution to re-index the log files."""
        # Snapshot the user's selection NOW — at the moment the background
        # refresh is triggered — not later inside list_alog_files (which, at startup,
        # can read a transient empty selection and lose the loaded profile).
        self._snapshot_list_selection()

        # Skip if a previous indexing pass is still running (large/network alog dir):
        # avoids orphaned threads and concurrent writes to _metadata_cache.records.
        try:
            if getattr(self, '_indexer_thread', None) is not None and self._indexer_thread.isRunning():
                _logd.debug("cache refresh: previous indexer still running, skip.")
                return
        except RuntimeError:
            # C++ QThread object already deleted (deleteLater pending) — safe to recreate
            self._indexer_thread = None
            self._indexer_worker = None

        self._indexer_thread = QThread()
        self._indexer_worker = _AlogCacheIndexingWorker(Path(self.alog_directory), self._metadata_cache.records)
        self._indexer_worker.moveToThread(self._indexer_thread)

        self._indexer_thread.started.connect(self._indexer_worker.run)
        self._indexer_worker.finished.connect(self._on_cache_indexing_complete)
        self._indexer_worker.finished.connect(self._indexer_thread.quit)
        self._indexer_worker.finished.connect(self._indexer_worker.deleteLater)
        self._indexer_thread.finished.connect(self._indexer_thread.deleteLater)
        self._indexer_thread.start()

    def _on_cache_indexing_complete(self, updated_records: dict):
        """Callback when background index updates are fully synced."""
        self._metadata_cache.records = updated_records

        # Instantly rebuild lookups from memory without firing off another background thread
        self.update_alog_uuid_indexes()

        # Refresh GUI views smoothly
        if self.initialized:
            self.list_alog_files()

    def _cancel_threads(self) -> None:
        """Request stop + wait (briefly) for all background threads."""

        # Stop timers that trigger threads. The attribute outlives the C++ timer
        # it points at, so its presence says nothing about whether it can still
        # be stopped — and a raise here would abandon every thread below.
        for timer_name in ('cache_refresh_timer', '_selection_debounce'):
            timer = getattr(self, timer_name, None)
            if timer is None:
                continue
            try:
                timer.stop()
            except RuntimeError:
                pass  # already collected by Qt

        # --- Curve load (mono + multi) ---
        # These threads are parented to the dialog, so Qt destroys them with it.
        # A load still in flight at that point is destroyed while running, which
        # Qt reports as fatal and aborts the process on the way out.
        self._cancel_alog_thread()

        # --- Indexer (Cache load) ---
        if hasattr(self, '_indexer_thread') and self._indexer_thread is not None:
            # Disconnect result slot so signal doesn't fire into a half-dead widget.
            try:
                if self._indexer_thread.isRunning():
                    self._indexer_worker.finished.disconnect(self._on_cache_indexing_complete)
                    self._indexer_thread.requestInterruption()  # signal worker de s'arrêter
                    self._indexer_thread.quit()
                    if not self._indexer_thread.wait(2000):     # 2s — scan disque peut être lent
                        # No terminate(): it kills the thread at an arbitrary
                        # instruction and can leave a Qt-internal mutex locked
                        # for good — the next Bean Cave then freezes while it
                        # builds a widget, with no crash and no log. These
                        # workers check isInterruptionRequested and return
                        # within a read, so waiting once more is the safe move.
                        _log.warning("indexer thread did not stop cooperatively — waiting once more")
                        if not self._indexer_thread.wait(2000):
                            _log.error("indexer thread is still running and was left to finish on its own")
            except (TypeError, RuntimeError):
                pass
            self._indexer_thread = None
            self._indexer_worker = None

        # --- Roaster load ---
        if hasattr(self, '_roaster_thread') and self._roaster_thread is not None:
            # Disconnect result slot so signal doesn't fire into a half-dead widget.
            try:
                if self._roaster_thread.isRunning():
                    self._roaster_worker.finished.disconnect(self._on_roaster_loaded)
                    self._roaster_thread.requestInterruption()
                    self._roaster_thread.quit()
                    if not self._roaster_thread.wait(2000):
                        # See the indexer above: no terminate() — it can leave a
                        # Qt-internal mutex locked and freeze the next Bean Cave.
                        _log.warning("roaster worker did not stop cooperatively — waiting once more")
                        if not self._roaster_thread.wait(2000):
                            _log.error("roaster worker is still running and was left to finish on its own")
            except (TypeError, RuntimeError):
                pass
            self._roaster_thread = None
            self._roaster_worker = None

        # --- Alog list thread ---
        if hasattr(self, '_list_thread') and self._list_thread is not None:
            try:
                if self._list_thread.isRunning():
                    # Same guard as every other worker: a queued result must not
                    # land in roast_list_widget while the dialog is tearing down.
                    try:
                        self._list_worker.finished.disconnect(self._on_alog_list_ready)
                    except (TypeError, RuntimeError, AttributeError):
                        pass
                    self._list_thread.requestInterruption()
                    self._list_thread.quit()
                    if not self._list_thread.wait(2000):
                        # See the indexer above: no terminate() — it can leave a
                        # Qt-internal mutex locked and freeze the next Bean Cave.
                        _log.warning("alog list worker did not stop cooperatively — waiting once more")
                        if not self._list_thread.wait(2000):
                            _log.error("alog list worker is still running and was left to finish on its own")
            except RuntimeError:
                pass  # Qt object already deleted by deleteLater
            self._list_thread = None
            self._list_worker = None

        # --- Plan roast files thread ---
        if hasattr(self, '_plan_roast_files_thread') and self._plan_roast_files_thread is not None:
            try:
                if self._plan_roast_files_thread.isRunning():
                    self._plan_roast_files_worker.finished.disconnect(self._on_plan_combo_alog_load)
                    self._plan_roast_files_thread.requestInterruption()
                    self._plan_roast_files_thread.quit()
                    if not self._plan_roast_files_thread.wait(2000):
                        # See the indexer above: no terminate() — it can leave a
                        # Qt-internal mutex locked and freeze the next Bean Cave.
                        _log.warning("plan worker did not stop cooperatively — waiting once more")
                        if not self._plan_roast_files_thread.wait(2000):
                            _log.error("plan worker is still running and was left to finish on its own")
            except (RuntimeError, TypeError):
                pass
            self._plan_roast_files_thread = None
            self._plan_roast_files_worker = None

        # --- TilauBLEScanner centralisé ---
        if hasattr(self, '_ble_scanner') and self._ble_scanner is not None:
            try:
                self._ble_scanner.stop()
            except Exception:
                pass
            self._ble_scanner = None

        # --- AI thread — attendre la fin propre avant destruction ──────────
        if hasattr(self, 'ai_thread') and self.ai_thread is not None:
            try:
                if self.ai_thread.isRunning():
                    for _sig, _slot in ((self.ai_worker.finished, self._on_bean_ai_finished),
                                        (self.ai_worker.error, self._on_bean_ai_error)):
                        try:
                            _sig.disconnect(_slot)
                        except (TypeError, RuntimeError):
                            pass
                    self.ai_thread.requestInterruption()
                    self.ai_thread.quit()
                    if not self.ai_thread.wait(2000):   # 2s timeout
                        # See the indexer above: no terminate().
                        _log.warning("bean AI worker did not stop cooperatively — waiting once more")
                        if not self.ai_thread.wait(2000):
                            _log.error("bean AI worker is still running and was left to finish on its own")
            except (TypeError, RuntimeError):
                pass
            self.ai_thread = None
            self.ai_worker = None

        # --- Niimbot print thread ---
        if hasattr(self, 'niimbot_thread') and self.niimbot_thread is not None:
            try:
                if self.niimbot_thread.isRunning():
                    # Drop the result slots first: a label finishing during the
                    # 5 s wait used to land in a dialog already tearing down.
                    for _sig, _slot in ((self.niimbot_worker.print_finished, self._on_print_success),
                                        (self.niimbot_worker.print_error, self._on_print_error)):
                        try:
                            _sig.disconnect(_slot)
                        except (TypeError, RuntimeError):
                            pass
                    self.niimbot_worker.cancel()
                    self.niimbot_thread.requestInterruption()
                    self.niimbot_thread.quit()
                    if not self.niimbot_thread.wait(5000):
                        _log.warning("print worker is finishing the current label")
                        self.niimbot_thread.wait()
            except (RuntimeError, TypeError):
                pass
            self.niimbot_thread = None
            self.niimbot_worker = None

        # --- Niimbot satellite print (sack sheets, brew labels) ---
        # Its own thread, started outside the main print path and until now
        # never joined: closing BeanCave mid-print destroyed it while running.
        if getattr(self, '_sat_niimbot_thread', None) is not None:
            stop_worker_thread(self._sat_niimbot_thread,
                               getattr(self, '_sat_niimbot_worker', None),
                               name="satellite print worker")
            self._sat_niimbot_thread = None
            self._sat_niimbot_worker = None

        # --- Niimbot heartbeat poll (timer + thread éphémère) ---
        # Stoppe le timer + déconnecte status_updated, puis joint un poll en vol
        # AVANT np.stop() (poll() fait du I/O BLE sous _ble_lock).
        self._stop_niimbot_poll()
        if hasattr(self, '_niimbot_poll_thread') and self._niimbot_poll_thread is not None:
            try:
                if self._niimbot_poll_thread.isRunning():
                    self._niimbot_poll_thread.requestInterruption()
                    self._niimbot_poll_thread.quit()
                    if not self._niimbot_poll_thread.wait(1000):
                        _log.warning("printer poll is finishing its current request")
                        self._niimbot_poll_thread.wait()
            except (RuntimeError, TypeError):
                pass
            self._niimbot_poll_thread = None


    def update_alog_uuid_indexes(self) -> None:
        """Assembles forward/reverse UUID lookups from the active metadata cache."""
        self._alog_uuid_index = {}  # uuid -> [filename, ...]
        self._alog_file_uuid = {}   # filename -> uuid

        for path_str, meta in self._metadata_cache.records.items():
            fname = meta.filename
            uuid_val = meta.uuid

            if uuid_val:
                self._alog_uuid_index.setdefault(uuid_val, []).append(fname)
                self._alog_file_uuid[fname] = uuid_val

    def _validate_startup_directories(self) -> None:
        """
        Called once at startup after settings are loaded.
        Checks both directories for existence and write access using existing helpers.
        If invalid, clears the bad path, saves settings, and redirects to the File tab.
        """
        problems = []

        # --- Check beancave directory ---
        if self.beancave_directory:
            bc_path = Path(self.beancave_directory)
            if not self._is_readable_directory(bc_path) or not os.access(str(bc_path), os.W_OK):
                problems.append(
                    QApplication.translate("tilauscope_beancave",
                        "Beancave directory is missing or not writable") +
                    f":\n{self.beancave_directory}"
                )
                self.beancave_directory = ""

        # --- Check alog directory ---
        if self.alog_directory:
            al_path = Path(self.alog_directory)
            if not self._is_readable_directory(al_path) or not os.access(str(al_path), os.W_OK):
                problems.append(
                    QApplication.translate("tilauscope_beancave",
                        "ALog directory is missing or not writable") +
                    f":\n{self.alog_directory}"
                )
                self.alog_directory = ""

        if not problems:
            return

        # Persist the cleared paths so stale values don't survive a restart
        self.save_settings()
        self.is_directory_defined = False

        msg = (
            QApplication.translate("tilauscope_beancave",
                "One or more directories configured at startup are no longer valid. "
                "Please select them again in TilausCope Configuration > BeanCave.") +
            "\n\n" +
            "\n".join(problems)
        )
        # Defer the message so the window is fully visible before the dialog appears
        # Tied to this window: closed inside the delay, the warning would open
        # on a catalogue that no longer exists.
        call_later(self, 200, lambda: (
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Directory Error"),
                msg,
                QMessageBox.Icon.Warning
            ),
            self.tab_widget.setCurrentWidget(self.main_tab)
        ))

    def apply_modern_theme(self):
        # Ensure the central widget has a solid background
        if hasattr(self, 'centralwidget'):
            self.centralwidget.setAutoFillBackground(True)
            self.centralwidget.setObjectName("centralwidget")

        # Draws the shared base from theme_qss.base_qss(); what follows is only
        # what this window needs differently, each rule with its reason.
        # See wiki/Theme-QSS-Spec.md.
        self.setStyleSheet(base_qss(ground=False) + f"""
            QWidget#centralwidget {{ background-color: {THEME['BG']}; }}

            /* A catalogue is read row by row: banding is what makes a long
               table scannable, and the base has no opinion on it. */
            QTableWidget, QTableView {{
                background-color: {THEME['BG']};
                alternate-background-color: {THEME['SURFACE']};
            }}

            /* Native combo popup, and the item height a bean name needs. */
            QComboBox {{ combobox-popup: 0; }}
            QComboBox QAbstractItemView {{
                /* margin/padding 0 removes the white frame macOS draws around
                   a styled popup. */
                margin: 0px;
                padding: 0px;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 30px;
                padding-left: 10px;
            }}
            /* The popup is its own window and does not inherit the base
               scrollbar; without these it comes back in the OS style. */
            QComboBox QScrollBar:vertical {{
                background: {THEME['BG']}; width: 12px; margin: 0px;
            }}
            QComboBox QScrollBar::handle:vertical {{
                background: {THEME['BORDER']}; min-height: 20px;
                border-radius: 6px; margin: 2px;
            }}
            QComboBox QScrollBar::add-line:vertical,
            QComboBox QScrollBar::sub-line:vertical,
            QComboBox QScrollBar::add-page:vertical,
            QComboBox QScrollBar::sub-page:vertical {{
                border: none; background: none; height: 0px; width: 0px;
            }}

            /* Editing a catalogue field must not nudge the row: the focus
               border grows by 1px and the padding gives that pixel back. */
            QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
            QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 2px solid {THEME['ACCENT']};
                padding: 4px 7px;
                background-color: {THEME['BG']};
                font-weight: bold;
            }}

            /* Rows are pointed at before they are clicked. */
            QListWidget::item:hover {{
                background-color: {THEME['SURFACE1']};
                color: {THEME['TEXT']};
            }}

            /* The window has a toolbar; no other TilauScope screen does. */
            QToolBar {{
                background: {THEME['SURFACE']};
                border-bottom: 1px solid {THEME['BORDER']};
                spacing: 10px;
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.oldPos = event.globalPosition().toPoint()
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        if event.button() == Qt.MouseButton.LeftButton:
            self.oldPos = QPoint()   # reset — null QPoint signals "not dragging"


        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            new_pos = self.pos() + delta
            self.move(new_pos)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def load_parameters(self) -> None :
        parameters_file = PKG_DIR / "beancave_beans.json"
        if not parameters_file.exists():
            _log.error(f"parameter file {parameters_file} not found")
            return
        try:
            data = json.loads(parameters_file.read_text(encoding='utf-8-sig' if _IS_WINDOWS else 'utf-8'))
            self.coffee_producing_countries  = data["country"]

            #cycle through varieties
            self.coffee_beans_species = data["varieties"]
            for specy in data["varieties"]:
                self.coffee_bean_types[specy] = data[specy]

            self.coffee_beans_categories = data["category"]
            for processing in data["category"]:
                self.coffee_processing_methods[processing] = data[processing]
        except Exception as e:
            _log.error(f"error loading parameter file : {e}")

         # --- roasters: kick off background load ---
        self.roaster_manager = RoasterManager()          # empty stub, safe to use immediately
        roaster_path = PKG_DIR / "roasters.json"
        self._start_roaster_load(roaster_path)

    def _launch_worker(self, worker, on_ok, on_err=None, *,
                        on_done=None, auto_delete=True) -> tuple:
        """Spin up a worker on a fresh QThread.

        Parameters
        ----------
        worker      : QObject with run(), finished, and optionally error signals.
        on_ok       : slot connected to worker.finished.
        on_err      : slot connected to worker.error (optional).
        on_done     : slot connected to thread.finished (optional).
        auto_delete : if True, call deleteLater on worker and thread when done.
                      Set False when _cancel_threads owns the lifetime.

        Returns (thread, worker) so callers can store refs if needed.
        """
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_ok)
        if on_err is not None:
            worker.error.connect(on_err)
        worker.finished.connect(thread.quit)
        if on_err is not None:
            worker.error.connect(thread.quit)
        cancelled = getattr(worker, 'cancelled', None)
        if cancelled is not None:
            cancelled.connect(thread.quit)
        if auto_delete:
            worker.finished.connect(worker.deleteLater)
            if on_err is not None:
                worker.error.connect(worker.deleteLater)
            if cancelled is not None:
                cancelled.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
        if on_done is not None:
            thread.finished.connect(on_done)
        thread.start()
        return thread, worker

    def _start_roaster_load(self, roaster_path: Path) -> None:
        self._roaster_thread, self._roaster_worker = self._launch_worker(
            _RoasterLoadWorker(roaster_path),
            on_ok=self._on_roaster_loaded,
            on_err=lambda e: _log.error(f"Roaster load failed: {e}"),
            on_done=self._on_roaster_thread_done,
            auto_delete=False,  # _cancel_threads owns lifetime
        )

    @pyqtSlot(object)
    def _on_roaster_loaded(self, mgr: RoasterManager) -> None:
        self.roaster_manager = mgr
        # UI is already built at this point — just refresh the combo
        if hasattr(self, 'roaster_combo'):
            self._populate_roaster_list()
            _log.info(f"Roasters loaded: {len(mgr.roasters)} entries")

    @pyqtSlot()
    def _on_roaster_thread_done(self) -> None:
        """Clear refs after roaster thread stops normally so _cancel_threads
        won't try to touch an already-idle object."""
        self._roaster_thread = None
        self._roaster_worker = None

    # when_finished() removed: dead code (never connected); secured teardown
    # is now performed authoritatively in closeEvent.

    def setup_ui(self) -> None:
        self.main_window_layout = QVBoxLayout(self)
        self.main_window_layout.setContentsMargins(10, 10, 10, 10) # Margin for the border/shadow

        # This is the actual visible window body
        self.container = QFrame()
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet(f"""
            #MainContainer {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 15px;
            }}
        """)

        # All your existing UI content goes inside this layout
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(20, 10, 20, 20)
        self.main_window_layout.addWidget(self.container)

        size_grip = QSizeGrip(self.container)
        size_grip.setStyleSheet("width: 16px; height: 16px;")
        self.layout.addWidget(size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        # --- MODERN HEADER ---
        header = QHBoxLayout()
        header.setContentsMargins(5, 5, 5, 10)

        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "BEANCAVE"))
        title_lbl.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 18px; font-weight: 800; border: none; background: transparent;")

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setStyleSheet(f"""
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

        header.addWidget(title_lbl)
        header.addStretch()
        # QR scan entry point (spec wiki/QR-Scan-Spec.md §3.1) — the camera
        # only runs while the scan dialog is open, hence a button, never always-on.
        self.scan_qr_btn = QPushButton(QApplication.translate("tilauscope_beancave", "📷  SCAN"))
        self.scan_qr_btn.setFixedHeight(30)
        self.scan_qr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_qr_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Scan a label QR code (roast or green bean)"))
        self.scan_qr_btn.clicked.connect(self.on_click_scan_qr)
        self.scan_qr_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']};
                color: {THEME['TEXT']};
                border-radius: 15px;
                border: 1px solid {THEME['BORDER']};
                padding: 0 14px;
                font-weight: 800;
                }}
            QPushButton:hover {{ background: {THEME['ACCENT']}; color: {THEME['BG']}; }}
        """)
        header.addWidget(self.scan_qr_btn)
        # headless home: BeanCave has no menu bar (the Artisan window that
        # owns it is hidden), so give the home a direct way to open the roast view.
        # tilauscopeCall() opens TilauScope and hides BeanCave (view-switch).
        if getattr(self.aw, '_tilau_headless', False):
            self.open_tilauscope_btn = QPushButton(QApplication.translate("tilauscope_beancave", "▶  TilauScope"))
            self.open_tilauscope_btn.setFixedHeight(30)
            self.open_tilauscope_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.open_tilauscope_btn.setToolTip(QApplication.translate(
                "tilauscope_beancave", "Open the roasting view"))
            self.open_tilauscope_btn.clicked.connect(lambda: self.aw.tilauscopeCall())
            self.open_tilauscope_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['ACCENT']};
                    color: {THEME['BG']};
                    border-radius: 15px;
                    border: none;
                    padding: 0 14px;
                    font-weight: 800;
                    }}
                QPushButton:hover {{ background: {THEME['LAVENDER']}; }}
                QPushButton:pressed {{ background: {THEME['SAPPHIRE']}; }}
            """)
            header.addWidget(self.open_tilauscope_btn)
        header.addWidget(self.close_btn)
        self.layout.addLayout(header)

        self.tab_widget = QTabWidget()
        self.main_tab = QWidget()
        self.roast_viewer_tab = QWidget()
        self.roast_plan_tab = QWidget()
        self.storage_tab = QWidget()  # conservation / water-activity dashboard
        self.status_label = QLabel()
        self.input_group = QGroupBox()

        self.tab_widget.addTab(self.main_tab, QApplication.translate("tilauscope_beancave","Green Beans"))
        self.tab_widget.addTab(self.roast_viewer_tab, QApplication.translate("tilauscope_beancave","Roast Viewer"))
        self.tab_widget.addTab(self.roast_plan_tab, QApplication.translate("tilauscope_beancave","Roasting plan"))
        self.tab_widget.addTab(self.storage_tab, QApplication.translate("tilauscope_beancave","Stockage"))
        # refresh the TilauAmbient probe button state on entering the plan tab
        self.tab_widget.currentChanged.connect(self._on_beancave_tab_changed)
        self.setup_main_tab_ui()
        self.setup_roast_viewer_tab_ui()
        self.setup_roast_plan_tab_ui()
        self.setup_storage_tab_ui()
        self.layout.addWidget(self.tab_widget)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        footer_layout.addWidget(QSizeGrip(self.container))
        self.layout.addLayout(footer_layout)

        settings = QSettings()
        geometry = settings.value('BeanCaveGeometry')
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setGeometry(100, 100, 1200, 800)

        self.setMinimumSize(800, 500)

        # A geometry saved on a larger/other monitor may not fit the
        # current screen (smaller resolution, changed DPI, unplugged display).
        # Without this, Qt clamps the window itself and spams the log with
        # "QWindowsWindow::setGeometry: Unable to set geometry …" warnings.
        # We pre-clamp so the dialog is always fully on-screen and no warning fires.
        self._clamp_geometry_to_screen()

        for combo in self.findChildren(QComboBox):
                combo.setView(QListView())
                combo.setItemDelegate(QStyledItemDelegate())

        for _cb in (
            self.country_combo,
            self.category_process_combo,
            self.process_combo,
            self.species_combo,
            self.varieties_combo,
            self.type_combo,
        ):
            self._install_hover_filter(_cb)

        self.restore_table_state()

    def _clamp_geometry_to_screen(self) -> None:
        """
        Shrink and reposition the window so it fits entirely within the current
        screen's available area. Prevents Qt "Unable to set geometry" warnings
        when a geometry saved on a bigger/other monitor is restored.
        """
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            frame = self.frameGeometry()

            # Clamp size to the available area (never below the minimum size).
            min_sz = self.minimumSize()
            new_w = max(min_sz.width(), min(frame.width(), avail.width()))
            new_h = max(min_sz.height(), min(frame.height(), avail.height()))
            if (new_w, new_h) != (frame.width(), frame.height()):
                self.resize(new_w, new_h)
                frame = self.frameGeometry()

            # Reposition so the whole frame stays inside the available area.
            new_x = min(max(frame.x(), avail.left()), avail.right() - frame.width())
            new_y = min(max(frame.y(), avail.top()), avail.bottom() - frame.height())
            if (new_x, new_y) != (frame.x(), frame.y()):
                self.move(new_x, new_y)
        except Exception:  # pylint: disable=broad-except
            _log.exception("clamp geometry to screen failed")

    #: Identity of the roast left highlighted last time. The roast's own UUID and
    #: not its filename, so renaming a log — which the operator does — does not
    #: lose the place.
    _LAST_ROAST_KEY: str = 'Beancave/LastRoastUUID'

    def load_settings(self) -> None:
        settings = QSettings()
        self.alog_directory = settings.value('alogDirectory', "", str)
        self.beancave_directory = settings.value('beancaveDirectory', self.alog_directory, str)
        self._last_roast_uuid = settings.value(self._LAST_ROAST_KEY, "", str)
        try:
            self.C0_COLOR = float(settings.value(C0_COLOR_KEY, self.C0_COLOR))
            self.C_BT_COLOR = float(settings.value(C_BT_COLOR_KEY, self.C_BT_COLOR))
            self.C_DTR_COLOR = float(settings.value(C_DTR_COLOR_KEY, self.C_DTR_COLOR))
            self.C_WL_COLOR = float(settings.value(C_WL_COLOR_KEY, self.C_WL_COLOR))
            self.duration_rules = settings.value("duration_rules", {
                "drying": (4.0, 8.0),
                "maillard": (3.0, 5.0),
                "development": (1.5, 4.0),
                })
            self.current_roaster_model = settings.value("RoastPlan/RoasterModel", "", str)
        except Exception as e:
            _logd.warning(f"color prediction coefficients loading failed, falling back to defaults: {e}")

        settings.beginGroup("ProbeDeviation")
        self.probe_override = settings.value("ManualProbeSettings", False, bool)
        if not hasattr(self, 'dev_inputs'):
            return
        for key, widgets in self.dev_inputs.items():
            try:
                start_widget, end_widget = widgets
                # Read values, defaulting to 0.0 if not found
                val_start = settings.value(f"{key}_start", 0.0, type=float)
                val_end = settings.value(f"{key}_end", 0.0, type=float)

                start_widget.setValue(val_start)
                end_widget.setValue(val_end)
            except Exception as e:
                _logd.error(f"Error loading settings for {key}: {e}")
        settings.endGroup()

    @pyqtSlot()
    def save_settings(self) -> None:
        settings = QSettings()
        settings.setValue('alogDirectory', self.alog_directory)
        settings.setValue('beancaveDirectory', self.beancave_directory)
        settings.setValue(C0_COLOR_KEY, self.C0_COLOR)
        settings.setValue(C_BT_COLOR_KEY, self.C_BT_COLOR)
        settings.setValue(C_DTR_COLOR_KEY, self.C_DTR_COLOR)
        settings.setValue(C_WL_COLOR_KEY, self.C_WL_COLOR)
        settings.setValue("duration_rules",self.duration_rules)
        settings.setValue(self._LAST_ROAST_KEY, getattr(self, '_last_roast_uuid', ""))
        settings.beginGroup("ProbeDeviation")
        for key, widgets in self.dev_inputs.items():
            try:
                start_widget, end_widget = widgets
                # Ensure we are saving raw floats
                settings.setValue(f"{key}_start", float(start_widget.value()))
                settings.setValue(f"{key}_end", float(end_widget.value()))
            except (AttributeError, ValueError) as e:
                _logd.warning(f"Could not save ProbeDeviation for {key}: {e}")
                continue
            settings.setValue("ManualProbeSettings", self.probe_override)
        settings.endGroup()

        settings.sync() # Forces immediate write to disk
        _logd.debug("Settings saved successfully.")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_B and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.close()
        elif event.key() == Qt.Key.Key_Escape:
            # ESC sur un QDialog NonModal appelle reject() → hide() sans closeEvent.
            # On force close() pour déclencher closeEvent et le cleanup complet
            # (notamment _hover_tooltip top-level qui resterait sinon visible).
            self.close()
        else:
            super().keyPressEvent(event)

    def _close_step_flag_shutdown(self) -> None:
        # Fermeture en cours : neutralise les slots BLE queued (gardes is_shutting_down).
        with QMutexLocker(self.shutdown_lock):
            self.is_shutting_down = True
        # Stopper le timer de sélection immédiatement pour éviter
        # qu'un chargement ne démarre pendant ou après le cleanup
        if hasattr(self, '_selection_debounce'):
            self._selection_debounce.stop()
            # Déconnecter uniquement le signal connu pour éviter le warning Qt
            # "wildcard call disconnects from destroyed signal"
            try:
                self._selection_debounce.timeout.disconnect()
            except (TypeError, RuntimeError):
                pass

    def _close_step_density_window(self) -> None:
        # tear down the density window (disconnect scale signals first)
        if self._density_window is not None:
            self._disconnect_density_scale()
            try:
                self._density_window.close()
                self._density_window.deleteLater()
            except (RuntimeError, AttributeError):
                pass
            self._density_window = None

    def _close_step_table_signals(self) -> None:
        try:
            self.datatable.selectionModel().selectionChanged.disconnect()
        except TypeError:
            pass # Déjà déconnecté

    def _close_step_geometry(self) -> None:
        settings = QSettings()
        settings.setValue('BeanCaveGeometry', self.saveGeometry())
        header:QHeaderView = self.datatable.horizontalHeader() #type:ignore
        logical_indices = [header.logicalIndex(visual_index) for visual_index in range(header.count())]
        order_str = ','.join(map(str, logical_indices))
        settings.setValue('BeanCaveColumnOrder', order_str)
        for i in range(header.count()):
            settings.setValue(f'BeanCaveColumnWidth/{i}', header.sectionSize(i))
        if self.aw.beanCaveMenuAction is not None:
            self.aw.beanCaveMenuAction.setChecked(False)

    def _close_step_persist(self) -> None:
        self.save_green_beans()
        self.save_settings()

    def _close_step_tooltip(self) -> None:
        if hasattr(self, '_hover_tooltip'):
            self._hover_tooltip.hide()
            self._hover_tooltip.close()   # force fermeture fenêtre top-level (parent=None)
            self._hover_tooltip.deleteLater()

    def _close_step_ble_signals(self) -> None:
        # Teardown is unconditional: gating it on the adapter still being on left
        # the scanner running and the signals live when Bluetooth was switched off
        # during the session — exactly the state that aborts at shutdown.
        # Couper les signaux BLE : aucun évènement queued ne doit tomber dans un widget détruit.
        if self.np is not None:
            for _sig in (self.np.at_connected, self.np.at_disconnected, self.np.error, self.np.status_updated):
                try:
                    _sig.disconnect()
                except (TypeError, RuntimeError):
                    pass

    def _close_step_niimbot(self) -> None:
        if self.np is not None:
            try:
                self.np.stop()
                _log.info("Niimbot printer connection and background scan stopped successfully.")
            except Exception as e:
                _log.error(f"Error during Niimbot printer cleanup: {e}")
        else:
            _log.error("NiimbotPrinter object (self.np) is None.")

    @pyqtSlot('QCloseEvent')
    def closeEvent(self, event: QCloseEvent| None = None) -> None: # type: ignore
        """Close BeanCave, running every teardown step even if one of them raises.

        This is a Qt virtual: an exception escaping it reaches the application's
        excepthook, which exits — so closing the catalogue would take the whole
        app down, and the steps below the raise (the geometry and settings
        writes, the printer teardown) would never run at all.
        """
        _log.info("beancave closing")
        for step in (self._close_step_flag_shutdown,
                     self._cancel_threads,
                     self._close_step_density_window,
                     self._close_step_table_signals,
                     self._close_step_geometry,
                     self._close_step_persist,
                     self._close_step_tooltip,
                     self._close_step_ble_signals,
                     self.stopLebrewAGmanager,
                     self.stopTilauAmbientManager,
                     self._close_step_niimbot):
            try:
                step()
            except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
                _log.error(f"beancave close step {step.__name__} failed: {e}")
        # event may be None when close() is triggered programmatically without an event.
        if event is not None:
            event.accept()
            super().closeEvent(event)



    @override
    def showEvent(self, event):
        super().showEvent(event)
        # niimbot_overlay est un widget inline dans action_bar_layout — pas besoin de show()/move().

    def directory_validity_check(self, directory: str) -> bool:
        path_obj = Path(directory)
        if not path_obj.is_dir():
            self._show_message(self,
                    QApplication.translate("tilauscope_beancave", "Invalid Directory"),
                    QApplication.translate("tilauscope_beancave", "The selected path is not a valid directory."),
                    QMessageBox.Icon.Critical)
            self.raise_()
            _log.error(f"selected directory is not a directory: {directory}")
            return False
        if not os.access(directory, os.W_OK):
            # Custom message based on platform for better UX
            platform_msg = ""
            if  _IS_MACOS: # macOS
                platform_msg = "\n\n" + QApplication.translate("tilauscope_beancave", "On macOS, please ensure TilauScope has 'Full Disk Access' in System Settings if this is a protected folder.")
            elif _IS_WINDOWS:
                platform_msg = "\n\n" + QApplication.translate("tilauscope_beancave", "On Windows, ensure the folder is not marked 'Read-only' and your user has modify permissions.")
            self._show_message(self,
                    QApplication.translate("tilauscope_beancave", "Permission Denied"),
                    QApplication.translate("tilauscope_beancave", "You do not have write permissions for this directory. TilauScope needs to save logs and metadata here.") + platform_msg,
                    QMessageBox.Icon.Warning)
            self.raise_()
            _log.error(f"selected directory has not enough rights to be used: {directory}")
            return False

        return True

    @pyqtSlot()
    def select_beancave_directory(self) -> None:
        """
        Opens a dialog to select the Beancave directory.
        Checks for directory validity and write permissions for macOS/Windows compatibility.
        """
        start_dir = str(self.beancave_directory) if self.beancave_directory and Path(self.beancave_directory).exists() else (QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
        if _IS_WINDOWS:
            start_dir = start_dir.rstrip('\\')

        directory = QFileDialog.getExistingDirectory(self, QApplication.translate("tilauscope_beancave","Select Beancave directory"), start_dir)
        if not directory:
            QTimer.singleShot(50, self._restore_focus)
            self._show_message(self,
                QApplication.translate("tilauscope_beancave","Selection Cancelled"),
                QApplication.translate("tilauscope_beancave","Beancave directory selection was cancelled."),
                QMessageBox.Icon.Information)
            return
        if self.directory_validity_check(directory) and directory != self.beancave_directory:
            self.beancave_directory = directory.rstrip('\\') if _IS_WINDOWS else directory
            self.save_settings()
            self.load_green_beans()
            self.populate_table()
            self.update_directory_labels()
            self.is_directory_defined = str(self.beancave_directory) != "" and str(self.alog_directory) != ""
            self.update_ui_visibility()
            _logd.debug(f"Beancave directory selected: {self.beancave_directory}")
            self._show_message(self,
            QApplication.translate("tilauscope_beancave","Beancave Directory Selected"),
            QApplication.translate("tilauscope_beancave","The directory") + f" '{self.beancave_directory}' " +
            QApplication.translate("tilauscope_beancave","has been selected.\nThe beancave.json file is now loaded from this location."))
        if _IS_WINDOWS :
            self.raise_()

    @pyqtSlot()
    def select_alog_directory(self) -> None:
        """
        Opens a dialog to select the ALog directory.
        Checks for directory validity and write permissions for macOS/Windows compatibility.
        """
        start_dir = str(self.alog_directory) if self.alog_directory and Path(self.alog_directory).exists() else (QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
        if _IS_WINDOWS:
            start_dir = start_dir.rstrip('\\')

        directory = QFileDialog.getExistingDirectory(self, QApplication.translate("tilauscope_beancave", "Select ALog Directory"),start_dir)
        if not directory:
            QTimer.singleShot(50, self._restore_focus)
            self._show_message(self,
                QApplication.translate("tilauscope_beancave","Selection Cancelled"),
                QApplication.translate("tilauscope_beancave","ALog directory selection was cancelled."),
                QMessageBox.Icon.Information)
            return
        if self.directory_validity_check(directory) and directory != self.alog_directory:
            self.alog_directory = directory.rstrip('\\') if _IS_WINDOWS else directory
            self.save_settings()
            # New folder → the index built for the old one is void. Drop it and
            # rebuild off-thread before any consumer asks.
            directory_changed(self.alog_directory)
            self._metadata_cache.records = {}
            self.update_directory_labels()
            self.list_alog_files()
            _logd.debug(QApplication.translate("tilauscope_beancave","ALog directory selected")+f": {self.alog_directory}")
            self.is_directory_defined = str(self.beancave_directory) != "" and str(self.alog_directory) != ""
            self.update_ui_visibility()
            self._show_message(self,
                QApplication.translate("tilauscope_beancave","ALog Directory Selected"),
                QApplication.translate("tilauscope_beancave","The directory") +  f" '{self.alog_directory}' " + QApplication.translate("tilauscope_beancave","has been selected."),
                QMessageBox.Icon.Warning)
        else:
            if _IS_WINDOWS :
                self.raise_()

    @pyqtSlot()
    def on_click_roast_properties(self) -> None:
        selected_row_index = self.datatable.currentRow()
        if selected_row_index == -1:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Error"), QApplication.translate("tilauscope_beancave","Select a line to start a Roast!"), QMessageBox.Icon.Warning)
            return
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return
        from tilauscope.roast_properties import RoastSetupDialog
        self.roast_properties_dialog = RoastSetupDialog(self.cave.green_beans[selected_row_index], self)
        self.roast_properties_dialog.exec()

    def try_to_open_file(self, file_path: str):
        # The export must keep the front — see open_in_os_viewer. The "Saved to …"
        # message shown just before this call has already queued its own focus
        # restore, which would land on top of the viewer: hold restores off for a
        # moment so the export really stays in front.
        self._focus_restore_blocked_until = time.monotonic() + 2.0
        open_in_os_viewer(file_path, self)

    def _restore_focus(self):
        if self.is_shutting_down:
            return
        # a file was just handed to an external viewer — leave it in front
        if time.monotonic() < getattr(self, "_focus_restore_blocked_until", 0.0):
            return
        if self.isVisible() and not self.isMinimized():
            self.raise_()
            self.activateWindow()

    def _show_message(self, parent, title: str, message: str, icon=QMessageBox.Icon.Information, **kwargs):
        show_styled_message(parent, title, message, icon, **kwargs)
        QTimer.singleShot(100, self._restore_focus)

    def _open_file_dialog_save(self, title: str, default: str, filter_str: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, default, filter_str)
        QTimer.singleShot(50, self._restore_focus)
        return path
