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
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass  # pylint: disable=unused-import
import ast  # Import de la bibliothèque ast
import qrcode # Import de la bibliothèque qrcode
import re # For sorting alog files
import requests
from pathlib import Path

#import matplotlib.pyplot as plt

from PIL.ImageQt import ImageQt # Import pour convertir l'image PIL en QImage

# getAppPath lives in artisanlib.util; artisanlib.main only re-exports it, and
# importing it from there booted the whole application through cave/__init__.
from artisanlib.util import cast, getAppPath  # smooth_list moved from tgraphcanvas to util


from PyQt6.QtCore import (QMutexLocker,QStandardPaths, Qt, pyqtSlot, QThread, QTimer) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QPixmap) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QMessageBox, QDialog, QSpinBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.niimprint import Niimprint_PaperType
from tilauscope.tilauscope_types import (show_styled_message,
                                         THEME, print_progress_pill)
from tilauscope.niimprint import NiimbotHeartbeat, NiimbotRFIDinfo
from tilauscope.cave.common import (
    _log, _logd, _safe_filename)
from tilauscope.cave.widgets import (
    QRCodeDialog)
from tilauscope.cave.workers import (
    _NiimbotPollWorker, NiimbotWorker)


class PrintingMixin:
    """Everything that leaves BeanCave: QR codes, printed labels, PDFs and cards.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """


    @pyqtSlot()
    def generate_qr_code(self) -> None:
        """Génère et affiche le QR Code du bean sélectionné dans QRCodeDialog."""
        selected_row_index = self.datatable.currentRow()
        if selected_row_index == -1:
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "Select a line to generate a QRCODE!"),
                QMessageBox.Icon.Warning
            )
            return
        if self.cave is None or not hasattr(self.cave, "green_beans"):
            return

        bean = self.cave.green_beans[selected_row_index]
        if not bean.uuid:
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave",
                    "Save this bean before generating its QR code — the code points at the record."),
                QMessageBox.Icon.Warning,
            )
            return

        try:
            # The scanner and the printed label both route on this URL, and only on
            # this URL (spec §2.1). The record itself is far past what a QR can hold.
            from tilauscope.label_printer import bean_qr_payload
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,  # type: ignore
                box_size=5,
                border=4,
            )
            qr.add_data(bean_qr_payload(bean))
            qr.make(fit=True)
            img    = qr.make_image(fill_color="black", back_color="white")
            qimg   = ImageQt(img.convert("RGB"))                      # type: ignore
            pixmap = QPixmap.fromImage(qimg)

            # ── Affichage dans QRCodeDialog (style FlavorSelectorDialog) ──────
            dlg = QRCodeDialog(
                bean_name=bean.name,
                pixmap=pixmap,
                pil_img=img,
                parent=self,
            )
            dlg.exec()

        except Exception as e:
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "An error happened while generating the QRCode:") + f" {e}",
                QMessageBox.Icon.Critical,
            )
            _logd.error(f"QRCode generation error: {e}")


    @pyqtSlot()
    def load_roast_in_artisan(self) -> None:
        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Load in TilauScope"),
                                QApplication.translate("tilauscope_beancave","Plese, select a roast session first."), QMessageBox.Icon.Warning)
            return

        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        alog_filename = meta['raw_fname']
        full_path = Path(self.alog_directory) / alog_filename

        if not full_path.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave","File error"),
                                QApplication.translate("tilauscope_beancave", "File not found")+f": {full_path}", QMessageBox.Icon.Critical)
            _logd.error(f"aLog file not found for loading: {full_path}")
            return

        try:
            self.aw.loadFile(str(full_path))
            self._show_message(self,
                                    QApplication.translate("tilauscope_beancave","Load in TilauScope"),
                                    f"'{alog_filename}' "+QApplication.translate("tilauscope_beancave","has been loaded in TilauScope."))
        except AttributeError:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Configuration error"),
                                 QApplication.translate("tilauscope_beancave","Error accessing to main TilauScope routine."), QMessageBox.Icon.Critical)
        except Exception as e:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Loading error"),
                                 QApplication.translate("tilauscope_beancave","An error occurred while loading file")+f": {e}", QMessageBox.Icon.Critical)
            _logd.error(f"Error loading aLog into TilauScope: {e}")

    @pyqtSlot()
    def load_roast_in_artisan_background(self) -> None:

        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","TilauScope load"),
                                QApplication.translate("tilauscope_beancave","Please, select a roast fist from the list."), QMessageBox.Icon.Warning)
            return

        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        alog_filename = meta['raw_fname']
        full_path = Path(self.alog_directory) / alog_filename

        if not full_path.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave","File Error"),
                                 QApplication.translate("tilauscope_beancave","File not found")+f": {full_path}", QMessageBox.Icon.Critical)
            _logd.error(f"aLog file not found for loading: {full_path}")
            return

        try:
            self.aw.loadAndRedrawBackgroundUUID(str(full_path))
            self._show_message(self, QApplication.translate("tilauscope_beancave","TilauScope Load"),
                                    f"'{alog_filename}'"+QApplication.translate("tilauscope_beancave"," has been loaded in main TilauScope window."))
        except AttributeError:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Configuration error"),
                                 QApplication.translate("tilauscope_beancave","Error accessing to background TilauScope routine"), QMessageBox.Icon.Critical)
        except Exception as e:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Load error"),
                                QApplication.translate("tilauscope_beancave", "An error occurred while loading")+f": {e}", QMessageBox.Icon.Critical)
            _logd.error(f"Error loading ALog into Artisan: {e}")

    def get_cloud_template_info(self, one_code: str) -> dict[str, Any]|None:
    # 1. URL de l'API Niimbot Cloud
        API_URL = "https://print.niimbot.com/api/template/getCloudTemplateByOneCode"
        payload = {
            "oneCode": one_code
        }
        headers = {
            "Content-Type": "application/json",
            "niimbot-user-agent": "AppVersionName/999.0.0"
        }
        try:
            response = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=10)
            response.raise_for_status() # Lève une exception pour les codes d'erreur 4xx/5xx
            data = response.json()
            if data.get("code") == 1:
                return data.get("data")
            return None
        except requests.exceptions.RequestException as e:
            _logd.debug(f"Error sending request to Niimbot Cloud {e}")
            return None
        except json.JSONDecodeError:
            _logd.debug("could not find any json answer from cloud api")
            return None

    @pyqtSlot()
    def niimbot_connected(self) -> None:
        # Afficher l'overlay dès la connexion (il était masqué au démarrage)
        if hasattr(self, "niimbot_overlay") and self.niimbot_overlay:
            self.niimbot_overlay.update_status(
                QApplication.translate("tilauscope_beancave", "Printer: Connecting…"),
                THEME["SUBTEXT"]
            )
        if self.np is not None:
            # BLE établi — le polling peut démarrer immédiatement,
            # même si le papier n'est pas encore détecté.
            self._niimbot_ble_up = True
            self._start_niimbot_poll()
            # Ne pas appeler stop/start_notifications ici : _connect() de ClientBLE
            # appelle déjà start_notifications() juste après on_connect().
            # Un double appel lève "Characteristic notifications already started".
            self.np.initialize()
            time.sleep(0.1)  # Laisser l'imprimante traiter le paquet initial
            hb = self.np.get_heartbeat()  # Pour s'assurer que la connexion est active
            deviceID = self.np.get_serial_number()
            firmwareVersion = self.np.get_software_version()
            rfid = self.np.get_rfid()
            self.np.paperstyle = self.np.get_paper_type()
            if rfid is not None and rfid.valid:
                _logd.debug(f"rfid detected, confirmed paper type={rfid.type} remaining labels={rfid.used_len}/{rfid.total_len}")
                self.np.used_labels = rfid.used_len if rfid.used_len is not None else 0
                self.np.total_labels = rfid.total_len if rfid.total_len is not None else 0
                t = self.get_cloud_template_info(str(rfid.barcode))
                if t is not None:  #swap as we print vertical on B21
                    self.np.paper_height = int(t["width"])
                    self.np.paper_width = int(t["height"])
            _logd.debug(f"Niimbot Device ID: {deviceID}")
            _logd.debug(f"Niimbot Firmware Version: {firmwareVersion}")
            _logd.debug(f"paper type h={self.np.paper_height}xw={self.np.paper_width}")
            # powerlevel = 0-5 (ink)
            # paperstate = 0-2 (paper) 0=ok, 1=no paper, 2 = printer loader opened
            # closingstate = 0-2 (cover) 0=ok, 1=cover opened, 2=unstable state cannot print
            # rfidreadstate = 0-3 (rfid) 0=ok, 1=no rfid, 2=reading error, 3=no rfid support
            _logd.debug(f"hb received {hb.closingstate} {hb.powerlevel} {hb.paperstate} {hb.rfidreadstate}")
            if hb.powerlevel is not None and hb.powerlevel <= 1 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Power low"), THEME['WARNING'])
                _logd.warning(f"niimbot printer power is low {hb.powerlevel}/5")
            if hb.rfidreadstate is not None and hb.rfidreadstate != 1 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: RFID Error"), THEME['CRITICAL'])
                _logd.warning("niimbot rfid cannot be read")
                return
            if hb.paperstate is not None and hb.paperstate == 1 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Cover opened"), THEME['WARNING'])
                _logd.warning("niimbot printer has cover opened, must be closed before printing (1)")
                return
            if hb.paperstate is not None and hb.paperstate == 2 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Status error"), THEME['WARNING'])
                _logd.warning("niimbot printer status is unstable (2)")
                return

            if self.np.paper_height > 0 and self.np.paper_width > 0:
                text, color = self._niimbot_ready_status()
                self.niimbot_overlay.update_status(text, color)
                self._niimbot_connected = True
                self.print_label_button.setEnabled(True)
                _logd.debug("everything is ok")
                return
            self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Invalid paper"), THEME['CRITICAL'])
            _logd.debug("paper cannot be used no size detected")

    @pyqtSlot()
    def niimbot_disconnected(self) -> None:
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down:
                _logd.debug("the app is closing, ignoring calls.")
                return
        _log.warning("niimbot printer disconnected unexpectedly")
        self._niimbot_connected = False
        self._niimbot_ble_up    = False
        self._stop_niimbot_poll()
        self.niimbot_overlay.update_status(
            QApplication.translate("tilauscope_beancave", "Printer: Disconnected"),
            THEME["CRITICAL"]
        )
        self.print_label_button.setEnabled(False)
        self.print_label_button.repaint()

    # À ajouter dans la classe BeancaveDlg
    # À ajouter dans la classe BeancaveDlg
    # ── Polling heartbeat Niimbot (5 s) ──────────────────────────────────────

    def _start_niimbot_poll(self) -> None:
        """Démarre le timer de polling heartbeat/RFID (5 s)."""
        if self._niimbot_poll_timer is not None:
            return  # déjà démarré
        self._niimbot_poll_timer = QTimer(self)
        self._niimbot_poll_timer.setInterval(5000)
        self._niimbot_poll_timer.timeout.connect(self._on_niimbot_poll_tick)
        if self.np is not None:
            self.np.status_updated.connect(self._on_niimbot_status)
            self.np.print_progress.connect(self._on_print_progress)
        self._niimbot_poll_timer.start()
        _logd.debug("Niimbot poll timer started (5 s)")

    def _stop_niimbot_poll(self) -> None:
        """Arrête le timer et déconnecte le signal."""
        if self._niimbot_poll_timer is not None:
            self._niimbot_poll_timer.stop()
            self._niimbot_poll_timer.deleteLater()
            self._niimbot_poll_timer = None
        if self.np is not None:
            try:
                self.np.status_updated.disconnect(self._on_niimbot_status)
            except (TypeError, RuntimeError):
                pass
            try:
                self.np.print_progress.disconnect(self._on_print_progress)
            except (TypeError, RuntimeError):
                pass
        _logd.debug("Niimbot poll timer stopped")

    @pyqtSlot()
    def _on_niimbot_poll_tick(self) -> None:
        """Tick du timer : lance poll_status() dans un QThread dédié.

        Si un thread précédent est encore actif, on skip ce tick pour ne pas
        empiler des requêtes BLE.
        """
        if self.np is None or not self._niimbot_ble_up:
            return
        if self._niimbot_poll_thread is not None and self._niimbot_poll_thread.isRunning():
            _logd.debug("Niimbot poll: thread précédent encore actif, skip.")
            return
        # NOTE — this worker is never actually reached: it has no parent and no
        # stored reference, so it is collected as soon as this method returns and
        # the thread's started signal fires into nothing. poll_status() has
        # therefore never run. Giving it a reference is NOT the fix: the worker
        # calls a method on `np`, a QObject that lives on the GUI thread, from a
        # background thread — enabling it deadlocks Qt against widget creation
        # (measured: 1 hang in 10 opens of BeanCave). The path needs a design
        # that does the BLE read without touching a GUI-thread object.
        self._niimbot_poll_thread = QThread()
        worker = _NiimbotPollWorker(self.np)
        worker.moveToThread(self._niimbot_poll_thread)
        self._niimbot_poll_thread.started.connect(worker.run)
        worker.finished.connect(self._niimbot_poll_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._niimbot_poll_thread.finished.connect(self._niimbot_poll_thread.deleteLater)
        self._niimbot_poll_thread.finished.connect(
            lambda: setattr(self, "_niimbot_poll_thread", None)
        )
        self._niimbot_poll_thread.start()

    def _niimbot_ready_status(self) -> tuple[str, str]:
        """Texte + couleur du bandeau quand l'imprimante est prête à imprimer.

        Source unique partagée par le connect et le poll 5 s : garantit que le
        compteur d'étiquettes (« B21S 50×30mm · N labels left ») s'affiche dès
        la connexion et ne soit plus écrasé par un format court « B21S: 50x30 »."""
        remaining = self.np.used_labels  if self.np else 0
        total     = self.np.total_labels if self.np else 0
        w = self.np.paper_width  if self.np else 0
        h = self.np.paper_height if self.np else 0
        labels_word = QApplication.translate("tilauscope_beancave", "labels left")
        count_txt   = f"{remaining}/{total}" if total > 0 else f"{remaining}"
        text  = f"B21S {w}×{h}mm · {count_txt} {labels_word}"
        color = THEME["WARNING"] if total > 0 and remaining / total < 0.1 else THEME["SUCCESS"]
        return text, color

    @pyqtSlot(object, object)
    def _on_niimbot_status(self, hb:NiimbotHeartbeat, rfid:NiimbotRFIDinfo) -> None:
        """Slot main-thread : met à jour l'overlay et paper_height si rouleau changé."""

        if not hb.valid:
            return

        # ── Détection ouverture/fermeture capot ──────────────────────────────
        cs = hb.closingstate
        ps = hb.paperstate
        self._niimbot_prev_closingstate = cs

        cover_open = (
            (cs is not None and cs != 0) or
            (ps is not None and ps != 0)
        )
        if cover_open:
            if ps == 1:
                status_txt = QApplication.translate("tilauscope_beancave", "Printer: No paper")
            elif ps == 2:
                status_txt = QApplication.translate("tilauscope_beancave", "Printer: Cover open")
            else:
                status_txt = QApplication.translate("tilauscope_beancave", "Printer: Cover open")
            self.niimbot_overlay.update_status(status_txt, THEME["WARNING"])
            self.print_label_button.setEnabled(False)
            return

        # ── Mise à jour RFID si rouleau changé ───────────────────────────────
        if rfid is not None and rfid.valid:
            prev_h = self.np.paper_height if self.np else 0
            self.np.used_labels  = rfid.used_len  if rfid.used_len  is not None else 0
            self.np.total_labels = rfid.total_len if rfid.total_len is not None else 0
            t = self.get_cloud_template_info(str(rfid.barcode))
            if t is not None:
                new_h = int(t["width"])
                new_w = int(t["height"])
                if new_h != prev_h:
                    _logd.debug(f"Niimbot poll: nouveau rouleau détecté {new_w}x{new_h}mm")
                self.np.paper_height = new_h
                self.np.paper_width  = new_w
                self.np.paperstyle   = self.np.get_paper_type()

        # ── Mise à jour overlay ───────────────────────────────────────────────
        if self.np is not None and self.np.paper_height > 0:
            text, color = self._niimbot_ready_status()
            self.niimbot_overlay.update_status(text, color)
            self.print_label_button.setEnabled(True)
        else:
            self.niimbot_overlay.update_status(
                QApplication.translate("tilauscope_beancave", "Printer: Invalid paper"),
                THEME["CRITICAL"]
            )

    @pyqtSlot()
    def generate_and_print_label(self) -> None:
        from tilauscope.tilauscope_types import replace_accents  # noqa: F401
        if self.cave is None or not hasattr(self.cave, "green_beans"):
            return

        # ── Résoudre le GreenBean ────────────────────────────────────────────
        bean_field = self.last_plot_data.get("beans", "") if self.last_plot_data is not None else ""
        bean = None
        uuid_match = re.search(r"uuid: \s*([a-fA-F0-9-]{36})", bean_field)
        if uuid_match and self.cave and self.cave.green_beans:
            bean = self.uuidmap.get(uuid_match.group(1))

        if bean is None:
            selected_items = self.roast_list_widget.selectedItems()
            if not selected_items:
                self.roast_plot_label.setText(
                    replace_accents(QApplication.translate("tilauscope_beancave",
                        "Select a roast file to see the curve preview."))
                )
                self.roast_info_text.setText(
                    replace_accents(QApplication.translate("tilauscope_beancave",
                        "Roast Information will appear here."))
                )
                return
            selected_rows = self.datatable.selectionModel().selectedRows()  # type: ignore
            if not selected_rows:
                self._show_message(self,
                    QApplication.translate("tilauscope_beancave", "Print"),
                    QApplication.translate("tilauscope_beancave",
                        "Please, select a green bean first in the first tab, then the roast."),
                    QMessageBox.Icon.Warning)
                return
            bean = self.cave.green_beans[selected_rows[0].row()]

        # ── Vérifications imprimante ─────────────────────────────────────────
        if self.np is not None and (
            self.np.used_labels == 0 or
            (self.np.total_labels > 0 and self.np.used_labels >= self.np.total_labels)
        ):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Print"),
                QApplication.translate("tilauscope_beancave",
                    "There is no more labels on the roll, please load a new roll"),
                QMessageBox.Icon.Warning)
            return

        paper_height = 0 if self.np is None else self.np.paper_height
        paper_width  = 0 if self.np is None else self.np.paper_width

        if self.np is not None and (
            self.np.paperstyle == Niimprint_PaperType.UNKNOWN
            or paper_width == 0 or paper_height == 0
        ):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Print"),
                QApplication.translate("tilauscope_beancave",
                    "Label size or type of paper was not correctly detected, "
                    "please close and retry to open bean cave"),
                QMessageBox.Icon.Warning)
            return

        if paper_height not in (30, 80):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Print"),
                QApplication.translate("tilauscope_beancave", "unsupported paper size")
                + f" {paper_width}x{paper_height}",
                QMessageBox.Icon.Warning)
            return

        labeltype = self.np.paperstyle  # type: ignore[union-attr]

        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        filepath = Path(self.alog_directory) / meta["raw_fname"]

        try:
            data = self.get_alog_data(filepath)
            if data is None:
                raise ValueError("Failed to load alog data")

            # ── Construction de l'image déléguée à NiimbotLabelBuilder ──────
            from tilauscope.label_printer import NiimbotLabelBuilder
            builder = NiimbotLabelBuilder()
            img = builder.build(bean, data, paper_height)

            # ── Prévisualisation — style TilauScope ──────────────────────────
            WIDTH_PX, HEIGHT_PX = img.size
            from PIL.ImageQt import ImageQt
            qimage = ImageQt(img)
            pixmap = QPixmap.fromImage(qimage)
            pixmap = pixmap.scaled(
                int(WIDTH_PX * 1.0), int(HEIGHT_PX * 1.0),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

            # ── Dialog frameless + card THEME ────────────────────────────────
            preview_dialog = QDialog(self)
            preview_dialog.setWindowTitle(
                QApplication.translate("tilauscope_beancave", "Preview for Niimbot B21S")
            )
            preview_dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            preview_dialog.setWindowFlags(
                Qt.WindowType.Dialog |
                Qt.WindowType.FramelessWindowHint
            )

            outer_layout = QVBoxLayout(preview_dialog)
            outer_layout.setContentsMargins(0, 0, 0, 0)

            card = QFrame()
            card.setObjectName("NiimbotPreviewCard")
            card.setStyleSheet(f"""
                #NiimbotPreviewCard {{
                    background-color : {THEME['BG']};
                    border           : 2px solid {THEME['ACCENT']};
                    border-radius    : 14px;
                }}
            """)
            outer_layout.addWidget(card)

            root = QVBoxLayout(card)
            root.setContentsMargins(20, 18, 20, 18)
            root.setSpacing(14)

            # Titre
            title_lbl = QLabel(
                QApplication.translate("tilauscope_beancave", "Preview for Niimbot B21S")
            )
            title_lbl.setStyleSheet(f"""
                color        : {THEME['ACCENT']};
                font-size    : 13px;
                font-weight  : 800;
                letter-spacing: 1px;
            """)
            root.addWidget(title_lbl)

            # Séparateur
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {THEME['BORDER']};")
            root.addWidget(sep)

            # Image de prévisualisation
            img_lbl = QLabel()
            img_lbl.setPixmap(pixmap)
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet(f"""
                background-color : {THEME['SURFACE']};
                border           : 1px solid {THEME['BORDER']};
                border-radius    : 6px;
                padding          : 8px;
            """)
            root.addWidget(img_lbl)

            # Boutons
            btn_print  = QPushButton("🖨  " + QApplication.translate("tilauscope_beancave", "Print now"))
            btn_cancel = QPushButton(QApplication.translate("Button", "Cancel"))

            btn_print.setMinimumHeight(36)
            btn_cancel.setMinimumHeight(36)

            btn_print.setStyleSheet(f"""
                QPushButton {{
                    background-color : {THEME['ACCENT']};
                    color            : {THEME['BG']};
                    border           : none;
                    border-radius    : 6px;
                    padding          : 8px 18px;
                    font-size        : 11px;
                    font-weight      : 700;
                }}
                QPushButton:hover {{
                    background-color : {THEME['LAVENDER']};
                }}
                QPushButton:pressed {{
                    background-color : {THEME['SURFACE']};
                    color            : {THEME['ACCENT']};
                    border           : 1px solid {THEME['ACCENT']};
                }}
            """)
            btn_cancel.setStyleSheet(f"""
                QPushButton {{
                    background-color : transparent;
                    color            : {THEME['OVERLAY1']};
                    border           : none;
                    padding          : 6px 12px;
                    font-size        : 10px;
                }}
                QPushButton:hover {{
                    color : {THEME['TEXT']};
                }}
            """)

            # Copies counter (default 1) — prints the same label N times.
            copies_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Copies"))
            copies_lbl.setStyleSheet(
                f"color:{THEME['SUBTEXT']};font-size:11px;border:none;")
            copies_spin = QSpinBox()
            copies_spin.setRange(1, 50)
            copies_spin.setValue(1)
            copies_spin.setFixedWidth(70)
            copies_spin.setStyleSheet(f"""
                QSpinBox {{
                    background:{THEME['SURFACE']}; color:{THEME['TEXT']};
                    border:1px solid {THEME['BORDER']}; border-radius:6px;
                    padding:4px 6px; font-size:12px;
                }}
            """)

            btn_row = QHBoxLayout()
            btn_row.addWidget(copies_lbl)
            btn_row.addWidget(copies_spin)
            btn_row.addStretch()
            btn_row.addWidget(btn_print)
            btn_row.addWidget(btn_cancel)
            root.addLayout(btn_row)

            btn_print.clicked.connect(preview_dialog.accept)
            btn_cancel.clicked.connect(preview_dialog.reject)

            if preview_dialog.exec() == QDialog.DialogCode.Accepted:
                # Progression dans la pastille flottante (host A) : la barre
                # d'état garde l'état imprimante au lieu d'être détournée.
                copies = int(copies_spin.value())
                self._roast_print_copies = copies
                self.niimbot_thread = QThread()
                self._roast_print_copy_i = 1
                self.niimbot_worker = NiimbotWorker(self.np, img, labeltype, copies=copies)
                self._print_pill = print_progress_pill(
                    self.container, copies, self.niimbot_worker.cancel)
                self._print_pill.set_margin(28, 28)   # clear of the size grip
                self.niimbot_worker.copy_progress.connect(self._on_roast_copy_progress)
                self.niimbot_worker.moveToThread(self.niimbot_thread)

                self.niimbot_worker.print_finished.connect(self._on_print_success)
                self.niimbot_worker.print_error.connect(self._on_print_error)
                self.niimbot_thread.started.connect(self.niimbot_worker.run)
                self.niimbot_worker.print_finished.connect(self.niimbot_thread.quit)
                self.niimbot_worker.print_finished.connect(self.niimbot_worker.deleteLater)
                self.niimbot_worker.print_error.connect(self.niimbot_thread.quit)
                self.niimbot_worker.print_error.connect(self.niimbot_worker.deleteLater)
                self.niimbot_thread.finished.connect(self.niimbot_thread.deleteLater)
                self.niimbot_thread.start()

        except ValueError as e:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Niimbot B21S Print"),
                str(e),
                QMessageBox.Icon.Warning)
        except Exception as e:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Niimbot B21S Print"),
                QApplication.translate("tilauscope_beancave", "Error") + f" : {e}",
                QMessageBox.Icon.Critical)
            _logd.error(f"Label printing error: {e}")

    @pyqtSlot(int, int)
    def _on_print_progress(self, done: int, total: int) -> None:
        """Progression ligne par ligne à l'intérieur d'une étiquette (np → GUI).

        Combinée à l'index de copie, elle donne la fraction de tout le tirage :
        l'anneau de la pastille se remplit une seule fois du début à la fin au
        lieu de repartir de zéro à chaque exemplaire.
        """
        pill = getattr(self, "_print_pill", None)
        if pill is None or total <= 0:
            return
        copies = max(1, int(getattr(self, "_roast_print_copies", 1)))
        if copies == 1:
            pill.progress.set_count(done, total)      # une seule étiquette
            return
        i = min(copies, max(1, int(getattr(self, "_roast_print_copy_i", 1))))
        pill.progress.set_value(((i - 1) + done / float(total)) / copies)

    @pyqtSlot(int, int)
    def _on_roast_copy_progress(self, i: int, n: int) -> None:
        """Worker signal between copies of a multi-copy roast label run."""
        self._roast_print_copy_i = i
        self._roast_print_copies = n
        pill = getattr(self, "_print_pill", None)
        if pill is not None and n > 1:
            pill.set_step(i, n)   # l'anneau est piloté ligne par ligne

    def _on_print_success(self):
        # Décrémenter used_labels localement du nombre d'exemplaires réellement
        # sortis (le prochain poll RFID confirmera le compteur du rouleau).
        copies  = int(getattr(self, "_roast_print_copies", 1))
        worker  = getattr(self, "niimbot_worker", None)
        printed = int(getattr(worker, "printed", copies) or 0)
        if self.np is not None and self.np.used_labels > 0:
            self.np.used_labels = max(0, self.np.used_labels - printed)
        self._roast_print_copies = 1
        self._roast_print_copy_i = 1
        # Remettre TOUT DE SUITE le statut imprimante (avec le compteur mis à
        # jour), sans attendre le poll.
        if (hasattr(self, "niimbot_overlay") and self.niimbot_overlay
                and self.np is not None and self.np.paper_height > 0):
            text, color = self._niimbot_ready_status()
            self.niimbot_overlay.update_status(text, color)
        # Poll RFID différé pour confirmer le compteur réel du rouleau.
        QTimer.singleShot(500, self._on_niimbot_poll_tick)

        # Le résultat est porté par la pastille : plus de popup modale pour un
        # succès ordinaire. Seul le rouleau bientôt vide justifie de couper
        # l'opérateur, parce que c'est un geste à faire avant le prochain lot.
        if printed < copies:
            done = QApplication.translate("tilauscope_beancave",
                "Stopped after {0} of {1} labels").format(printed, copies)
        elif printed > 1:
            done = QApplication.translate("tilauscope_beancave",
                "{0} labels printed").format(printed)
        else:
            done = QApplication.translate("tilauscope_beancave", "Label printed")
        pill = getattr(self, "_print_pill", None)
        self._print_pill = None
        if pill is not None:
            pill.succeed("🖨  " + done)

        if (self.np is not None and self.np.total_labels > 0
                and float(self.np.used_labels) <= float(self.np.total_labels) * 0.1):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Niimbot B21S Print"),
                f"{self.np.used_labels} " + QApplication.translate("tilauscope_beancave",
                    "label(s) remaining on the roll, consider changing the roll."))

    def _on_print_error(self, message):
        # Forcer un poll pour remettre l'overlay à jour après l'erreur
        self._roast_print_copies = 1
        self._roast_print_copy_i = 1
        QTimer.singleShot(500, self._on_niimbot_poll_tick)
        # La pastille rouge reste jusqu'à ce que l'opérateur la ferme ; la boîte
        # porte le détail imprimante, qui ne tient pas sur une ligne.
        pill = getattr(self, "_print_pill", None)
        self._print_pill = None
        if pill is not None:
            pill.fail("🖨  " + QApplication.translate(
                "tilauscope_beancave", "Printing stopped — see the message"))
        show_styled_message(self,
                            QApplication.translate("tilauscope_beancave","Niimbot B21S Print"), message,
                            QMessageBox.Icon.Warning)

    def print_niimbot_image_async(self, img, on_finished, on_error) -> None:
        """Print one 1-bit image on the connected Niimbot, no UI popup here.

        For satellite dialogs (Brew Advisor dial-in) that render their own
        in-window status. ``on_finished()`` / ``on_error(str)`` run on the GUI
        thread. BLE access is serialised by NiimbotBLE's internal lock, so this
        coexists safely with the 5 s heartbeat poll. The BeanCave printer
        overlay + remaining-labels counter are refreshed on success."""
        if self.np is None or not self._niimbot_connected:
            on_error(QApplication.translate("tilauscope_beancave", "Printer not ready"))
            return
        if getattr(self, "_sat_niimbot_thread", None) is not None and self._sat_niimbot_thread.isRunning():
            on_error(QApplication.translate("tilauscope_beancave", "A print is already in progress"))
            return
        self._sat_niimbot_thread = QThread()
        self._sat_niimbot_worker = NiimbotWorker(self.np, img, self.np.paperstyle)
        self._sat_niimbot_worker.moveToThread(self._sat_niimbot_thread)
        self._sat_niimbot_thread.started.connect(self._sat_niimbot_worker.run)

        def _post_ok():
            if self.np is not None and self.np.used_labels > 0:
                self.np.used_labels -= 1
            if (hasattr(self, "niimbot_overlay") and self.niimbot_overlay
                    and self.np is not None and self.np.paper_height > 0):
                text, color = self._niimbot_ready_status()
                self.niimbot_overlay.update_status(text, color)
            QTimer.singleShot(500, self._on_niimbot_poll_tick)

        self._sat_niimbot_worker.print_finished.connect(_post_ok)
        self._sat_niimbot_worker.print_finished.connect(on_finished)
        self._sat_niimbot_worker.print_error.connect(on_error)
        for sig in (self._sat_niimbot_worker.print_finished, self._sat_niimbot_worker.print_error):
            sig.connect(self._sat_niimbot_thread.quit)
            sig.connect(self._sat_niimbot_worker.deleteLater)
        self._sat_niimbot_thread.finished.connect(self._sat_niimbot_thread.deleteLater)
        self._sat_niimbot_thread.finished.connect(lambda: setattr(self, "_sat_niimbot_thread", None))
        self._sat_niimbot_thread.start()

    def generate_and_print_pdf_label(self):
        # get roast selected file
        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","TilauScope load"),
                                QApplication.translate("tilauscope_beancave","Please, select a roast fist from the list."),
                                QMessageBox.Icon.Warning)
            return

        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        alog_filename = meta['raw_fname']
        alog_full_path = Path(self.alog_directory) / alog_filename

        if not alog_full_path.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave","File Error"),
                                 QApplication.translate("tilauscope_beancave","File not found")+f": {alog_full_path}",
                                 QMessageBox.Icon.Critical)
            _logd.error(f"aLog file not found for loading: {alog_full_path}")
            return
        if alog_filename and self.last_plot_data is not None: # Fixe 2026/03/06 last plot data can be empty if alog file is malformed or corrupted
            # 'bean' field usually contains something like "Bean Name (uuid: xxxxxxxx-xxxx-...)"
            bean_field = self.last_plot_data.get("beans", "")
            target_bean = None
            # 2. Search for 'uuid: <uuid value>' in the bean field
            uuid_match = re.search(r'uuid: \s*([a-fA-F0-9-]{36})', bean_field)
            if uuid_match:
                target_uuid = uuid_match.group(1)
                # 3. Load the bean from GreenBean objects
                if self.cave and self.cave.green_beans:
                    target_bean = self.uuidmap.get(target_uuid)
                    if target_bean is None:
                        self._show_message(self,
                            QApplication.translate("tilauscope_beancave", "Missing Bean"),
                            QApplication.translate("tilauscope_beancave", "This roast is linked to a bean that no longer exists in your cave."),
                            QMessageBox.Icon.Warning)
                        return
            downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            if not downloads_dir:
                downloads_dir = str(Path.home() / "Downloads")
            default_name = str(Path(downloads_dir) / f"roast_label_{alog_filename}.pdf")
            file_path = self._open_file_dialog_save( QApplication.translate("tilauscope_beancave", "Save Label PDF"), default_name, QApplication.translate("tilauscope_beancave", "PDF Files (*.pdf)"))
            if file_path:
                from tilauscope.label_printer import RoastedBeanLabelPrinter
                printer = RoastedBeanLabelPrinter()
                try:
                    # Format natif Artisan : repr(dict) en UTF-8 — pas de unicode_escape
                    # (sinon mojibake sur les accents). literal_eval gère les échappements.
                    decoded_content = alog_full_path.read_text(encoding='utf-8')
                    roast_properties = cast('ProfileData', ast.literal_eval(decoded_content))
                    success = printer.print_to_label(roast_properties, target_bean, file_path)
                    if success:
                        self._show_message(self,
                                        QApplication.translate("tilauscope_beancave","Success"),
                                        QApplication.translate("tilauscope_beancave","Label saved to")+f" {file_path}")
                        self.try_to_open_file(file_path)
                    else:
                        self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Error"),
                                QApplication.translate("tilauscope_beancave","PDF file was not generated."),
                                QMessageBox.Icon.Warning)
                except Exception as e:
                    _logd.error(f"error printing to pdf: {e}")


    @pyqtSlot()
    def on_print_label_clicked(self):
        # 1. Get selected bean data
        selected_rows = self.datatable.selectionModel().selectedRows()
        if not selected_rows:
            self._show_message(self,
                                QApplication.translate("Button","Select"),
                                QApplication.translate("tilauscope_beancave","Please select a bean from the table first."),
                                QMessageBox.Icon.Warning)
            return

        row = selected_rows[0].row()
        bean = self.cave.green_beans[row]

#        bean_data = self.helper.get_bean_data_by_index(row) # Using your existing helper

        if bean:
            # 2. Ask where to save
            downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            if not downloads_dir:
                downloads_dir = str(Path.home() / "Downloads")
            default_name = str(Path(downloads_dir) / f"Label_{bean.name}.pdf")
            file_path = self._open_file_dialog_save("Save Label PDF", default_name, "PDF Files (*.pdf)")

            if file_path:
                from tilauscope.label_printer import GreenBeanLabelPrinter
                logo_path = Path(getAppPath()) / "tilauscope.png"
                printer = GreenBeanLabelPrinter(logo_path) # set a logo if any
                success = printer.print_to_label(bean, file_path)

                if success:
                    self._show_message(self,
                                            QApplication.translate("tilauscope_beancave","Success"),
                                            QApplication.translate("tilauscope_beancave","Label saved to")+f" {file_path}")
                self.try_to_open_file(file_path)

    # Export the selected bean sheet as a shareable landscape JPEG
    def on_export_social_card(self):
        selected_rows = self.datatable.selectionModel().selectedRows()
        if not selected_rows:
            self._show_message(self,
                                QApplication.translate("Button","Select"),
                                QApplication.translate("tilauscope_beancave","Please select a bean from the table first."),
                                QMessageBox.Icon.Warning)
            return

        row = selected_rows[0].row()
        bean = self.cave.green_beans[row]
        if not bean:
            return

        downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if not downloads_dir:
            downloads_dir = str(Path.home() / "Downloads")
        safe_name = _safe_filename(bean.name, "bean")
        default_name = str(Path(downloads_dir) / f"{safe_name}.jpg")
        file_path = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave","Save Bean Card"),
            default_name, "JPEG Images (*.jpg)")
        if not file_path:
            return

        try:
            from tilauscope.beancave_social_card import GreenBeanSocialCard
            ok = GreenBeanSocialCard().save_jpeg(bean, file_path)
        except Exception as e:
            _logd.error(f"Bean card export failed: {e}", exc_info=True)
            ok = False

        if ok:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Success"),
                                QApplication.translate("tilauscope_beancave","Bean card saved to")+f" {file_path}")
            self.try_to_open_file(file_path)
        else:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Error"),
                                QApplication.translate("tilauscope_beancave","The bean card could not be generated."),
                                QMessageBox.Icon.Warning)
