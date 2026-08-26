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

"""Frameless-window behaviour: dragging, resizing, focus and teardown.

A slice of the roasting window. It is a mixin rather than a collaborator: the
window is one object with one set of attributes, and these methods read and
write it exactly as they did when they sat in the same file. What the split
buys is a boundary to read within, not a decoupling.
"""

from __future__ import annotations

import logging
from typing import Final

from PyQt6.QtCore import QEvent, QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QHideEvent, QKeyEvent, QShowEvent
from PyQt6.QtWidgets import QApplication, QDialog
from tilauscope.beancave import BeancaveDlg
from tilauscope.tilauscope_types import _IS_WINDOWS
from typing import override


_log: Final[logging.Logger] = logging.getLogger(__name__)


class ChromeMixin:
    """Frameless-window behaviour: dragging, resizing, focus and teardown.

    A plain mixin, deliberately not a QWidget subclass. Qt registers the slots
    a class declares in that class's own metaobject, and a window built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice became unconnectable, with Qt reporting
    a slot that takes no arguments at all. Inheriting nothing keeps every slot
    on the window itself.
    """

    @pyqtSlot()
    def focusOn(self):
        self.setFocus()

    @override
    def showEvent(self, a0: 'QShowEvent|None') -> None:
        """The roast is drawn by our own curve while this window is up.

        Artisan's figure is still built and still holds every sample — it is
        simply not rendered, which is most of what a sampling tick costs. The
        LCD updates that carry those samples to us are untouched; see the gate
        in updategraphics().

        Tied to visibility rather than to construction because the headless
        flow hides this window without closing it, and a hidden TilauScope must
        not leave Artisan's graph frozen behind it.
        """
        super().showEvent(a0)
        self.aw.tilau_suspend_render = True
        # A roast read back from disk sends no samples, so nothing else would
        # ever ask the curve to catch up with it.
        if self.curve is not None:
            self.curve.tick()
        self._queue_live_artisan_state_adoption()

    @override
    def hideEvent(self, a0: 'QHideEvent|None') -> None:
        super().hideEvent(a0)
        self.aw.tilau_suspend_render = False

    @override
    def closeEvent(self, a0: 'QCloseEvent|None') -> None:
        aw = self.aw
        qmc = aw.qmc

        # block exit while sampling is active
        if qmc.flagon and a0 is not None:
            a0.ignore()
            return

        # Monitoring is off, so this window no longer owns a wake lock. Also
        # detach the application-level fallback to avoid retaining a closed
        # DisplayScope instance.
        self.tilau_ssbserver.finish()
        app = QApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self.tilau_ssbserver.finish)
            except (TypeError, RuntimeError):
                pass

        # don't lose a slider change still inside its coalescing window
        self.flush_pending_slider_commits()

        # 1. Stopper les timers avant toute manipulation de widgets
        if hasattr(self, 'p_timer') and self.p_timer.isActive():
            self.p_timer.stop()

        # 2. Rendre la figure à Artisan : elle a cessé d'être rendue pendant
        #    que notre courbe tenait l'écran, donc elle est en retard de toute la
        #    session. Le redraw complet du point 6 la remet d'aplomb.
        aw.tilau_suspend_render = False

        # 3. Restaurer l'opacité
        aw.setWindowOpacity(1.0)

        # 6. Kick Qt layout engine — deferred redraw ensures canvas has its final
        #    geometry before matplotlib tight_layout recalculates
        aw.main_widget.updateGeometry()
        aw.resize(aw.size())

        def _deferred_restore() -> None:
            try:
                canvas = aw.qmc.canvas
                sz = canvas.size()
                from PyQt6.QtGui import QResizeEvent
                canvas.resizeEvent(QResizeEvent(sz, sz))
                qmc.redraw(recomputeAllDeltas=True)
                canvas.draw_idle()
                aw.update()
            except Exception as e:
                _log.error('deferred restore after TilauScope close: %s', e)

        QTimer.singleShot(150, _deferred_restore)

        # 9. Restaurer la visibilité des éléments UI Artisan
        idx = 2 if qmc.flagstart else (1 if qmc.flagon else 0)
        try:
            if self.show_controls[idx] == 1:     aw.showControls()
            if self.show_lcds[idx] == 1:         aw.showLCDs()
            if self.show_minieventline[idx] == 1: aw.show_minieventline()
            if self.show_extrabuttons[idx] == 1: aw.showExtraButtons()
            if self.show_sliders[idx] == 1:      aw.showSliders()
        except (IndexError, AttributeError) as e:
            _log.error('restore UI elements: %s', e)

        # 10. Fermer le panel flottant
        if hasattr(self, 'event_panel'):
            self.event_panel.close()
        # 10bis. Fermer le panel flottant extradevices
        if hasattr(self, 'extra_panel'):
            self.extra_panel.close()

        # Close roast assistant panel if open (floating or anchored)
        if hasattr(self, 'roast_assistant') and (
                self.roast_assistant.isVisible() or getattr(self, '_assistant_anchored', False)):
            if getattr(self, '_body_in_host', False):
                # Return the body to the shell before closing to avoid orphaning it.
                self._anchor_host.takeWidget()
                self.roast_assistant.give_body()
                self._body_in_host = False
            self.roast_assistant.close()

        # 11. Remove event filter from main window
        if self.aw:
            self.aw.removeEventFilter(self)

        # 12. Restore focus to main window
        aw.activateWindow()
        aw.raise_()

        self.aw.tilauscopeMain.setChecked(False)

        if hasattr(self,'_brew_notif'):
            if self._brew_notif:
                try:
                    self._brew_notif.request_stop()
                except RuntimeError:
                    # underlying C++ widget already deleted (auto-closed) — nothing to stop
                    pass
                self._brew_notif = None

        if _IS_WINDOWS:
            self.clearFocus()

        # Détacher le flux de données live qmc -> TilauScope
        try:
            self.aw.qmc.tilauUpdateSignal.disconnect(self.update_ui_from_artisan)
        except (TypeError, RuntimeError):
            pass
        try:
            self.aw.loadBackgroundSignal.disconnect(self._on_background_changed)
        except (TypeError, RuntimeError):
            pass
        try:
            self.aw.clearBackgroundSignal.disconnect(self._on_background_changed)
        except (TypeError, RuntimeError):
            pass

        # 13. Retirer le hook messages Artisan et restaurer messagelabel
        if hasattr(self, '_msg_hook'):
            self._msg_hook.remove()
        if hasattr(self, '_axes_hook'):
            self._axes_hook.remove()
        if hasattr(self, '_canvas_style_hook'):
            self._canvas_style_hook.remove()
        self.aw.messagelabel.setVisible(True)
        super().closeEvent(a0)

    @override
    def eventFilter(self, obj, event):
        # ── Wheel sur PhaseWidget → ajuster la consigne de phase ─────────
        if (event.type() == QEvent.Type.Wheel
                and hasattr(obj, '_phase_key')):
            self._phase_wheel(obj, event)
            return True   # événement consommé — ne remonte pas
        if obj == self.aw and event.type() == QEvent.Type.WindowActivate:
            # Vérifie qu'aucune fenêtre modale/dialogue fils n'est active
            # (QFileDialog, QMessageBox, etc. ferment et rendent focus à aw)
            active = QApplication.activeWindow()
            if active is None or active is self.aw:
                # Ne pas interférer si Beancave est visible — il a la priorité
                beancave_visible = any(
                    isinstance(w, BeancaveDlg) and w.isVisible()
                    for w in QApplication.topLevelWidgets()
                )
                if not beancave_visible:
                    QTimer.singleShot(0, self._safe_raise)
        return super().eventFilter(obj, event)

    def _safe_raise(self):
        """Ramène TilauScope au premier plan seulement si aucun dialogue fils n'est ouvert
        et si Beancave n'est pas visible (il a la priorité de premier plan)."""
        # Ne pas interférer pendant un drag — évite boucle WindowActivate ↔ raise_()
        if getattr(self, "_dragging", False):
            return
        active = QApplication.activeWindow()
        if (active is not None and active is not self.aw) or active is self:
            return
        # Vérifie qu'aucun QDialog fils n'est visible — remonte toute la chaîne de parenté
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                p = widget.parent()
                while p is not None:
                    if p in (self, self.aw):
                        return
                    p = p.parent()
        # Cède la priorité à Beancave s'il est ouvert et visible
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, BeancaveDlg) and widget.isVisible():
                return
        self.raise_()
        self.activateWindow()
        # A child dialog just closed (e.g. Artisan's own Profile Background
        # window) — its "Load" button sets qmc.backgroundprofile directly,
        # without going through loadBackgroundSignal, so this is the only
        # reliable point to catch it back.
        self._refresh_replay_button()

    @override
    def keyPressEvent(self, a0: 'QKeyEvent|None') -> None:
        if a0 is None:
            return
        key = a0.key()
        modifiers = a0.modifiers()
        shift_modifier = modifiers == Qt.KeyboardModifier.ShiftModifier # SHIFT
        no_modifier = modifiers == Qt.KeyboardModifier.NoModifier

        # PID L/R shortcuts removed — PID piloting is delegated to
        # Artisan's own key cascade (handled by self.aw.keyPressEvent below).
        if key == Qt.Key.Key_B and shift_modifier:
            # call Beancave
            self.btn_beancave.setChecked(not self.btn_beancave.isChecked()) # fix 2026/04/25
            self.toggle_beancave()
        elif key == Qt.Key.Key_X and no_modifier:
            # Call the extra counters logic
            if len(self.extra_panel.active_counters) > 0:
                self.extra_panel.toggle_visibility()
            return
        elif key == Qt.Key.Key_B and no_modifier:
            # Call the extra counters logic
            self.event_panel.toggle_visibility()
            return
        elif key == Qt.Key.Key_A and shift_modifier:
            self.toggle_roast_assistant()   # placement handled inside
            return
        # F1-F8 milestone shortcuts gated on current_event (last marked
        # event code: None=nothing, 0=CHARGE, 1=DRY END, 2=FC START, 3=FC END,
        # 4=SC START, 5=SC END, 6=DROP, 7=COOL END). That chain carries the
        # ordering; _milestone_key_allowed() checks it against Artisan's own
        # timeindex, which the two can drift apart from (a mark made while this
        # window was closed never reaches current_event).
        elif key==Qt.Key.Key_F1 and no_modifier and (self.current_event is None or self.current_event == 0): # charge can be marked at any time before dry end is marked, but not after
            if self.is_roasting:
                self.aw.qmc.markChargeSignal.emit(False)
                return
        elif key==Qt.Key.Key_F2 and no_modifier and self.current_event in [0,1]: # dry end can be marked any time after charge is marked, but not after 1C start is marked
            if self._milestone_key_allowed(1, 0):
                self.aw.qmc.markDRYSignal.emit(False)
                return
        elif key==Qt.Key.Key_F3 and no_modifier and self.current_event in [1,2]: # 1C start can be marked any time after dry end is marked, but not after 1C end is marked
            if self._milestone_key_allowed(2, 1):
                self.aw.qmc.markFCsSignal.emit(False)
                return
        elif key==Qt.Key.Key_F4 and no_modifier and self.current_event in [2,3]: # 1C end can be marked any time after 1C start is marked, but not after 2C start is marked
            if self._milestone_key_allowed(3, 2):
                self.aw.qmc.markFCeSignal.emit(False)
                return
        elif key==Qt.Key.Key_F5 and no_modifier and self.current_event in [3,4]: # 2C start can be marked any time after 1C end is marked, but not after 2C end is marked
            if self._milestone_key_allowed(4, 3):
                self.aw.qmc.markSCsSignal.emit(False)
                return
        elif key==Qt.Key.Key_F6 and no_modifier and self.current_event in [4,5]: # 2C end can be marked any time after 2C start is marked, but not after drop is marked
            if self._milestone_key_allowed(5, 4):
                self.aw.qmc.markSCeSignal.emit(False)
                return
        elif key==Qt.Key.Key_F7 and no_modifier and self.current_event in [5,6]: # drop can be marked any time after CHARGE is marked, but not after cool end is marked (except if it's a mispress before charge)
            if self._milestone_key_allowed(6, 0):   # CHARGE, not the crack before it
                self.handle_drop()
                return
        elif key==Qt.Key.Key_F8 and no_modifier and self.current_event in [6,7]: # cool end can be marked any time after drop is marked, but not after another event is marked (except if it's a mispress before charge)
            if self._milestone_key_allowed(7, 6):
                self.handle_cool()
                return
        # Pass other keys to the standard handler (important for ESC, etc.)
        self.aw.keyPressEvent(a0)
        super().keyPressEvent(a0)

    def _handle_drag_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_self_origin = self.pos()
            self._dragging = True          # inhibe eventFilter/_safe_raise
        event.accept()

    def _handle_drag_move(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not hasattr(self, "_drag_origin") or self._drag_origin is None:
            return
        delta = event.globalPosition().toPoint() - self._drag_origin
        dist = abs(delta.x()) + abs(delta.y())
        if dist < 2 or dist > 1200:
            return
        new_pos = self._drag_self_origin + delta
        self.move(new_pos)
        if self.aw:
            self.aw.move(new_pos)
        event.accept()

    def _handle_drag_release(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._dragging = False
        event.accept()

    # mousePressEvent principal : déléguer uniquement le fond nu (container)
    # La drag handle a ses propres handlers — pas besoin de la logique childAt ici
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child is None or child == self.container:
                # Clic sur fond nu — activer drag de secours (même logique que handle)
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_self_origin = self.pos()
            else:
                event.ignore()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not hasattr(self, "_drag_origin") or self._drag_origin is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._drag_origin = None
            return
        delta = event.globalPosition().toPoint() - self._drag_origin
        dist = abs(delta.x()) + abs(delta.y())
        if dist < 2 or dist > 1200:
            return
        new_pos = self._drag_self_origin + delta
        self.move(new_pos)
        if self.aw:
            self.aw.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
        super().mouseReleaseEvent(event)

    def moveEvent(self, event):
        # This keeps the Button Panel (event_panel) attached
        # whenever the TilauScope moves (triggered by the parent moving)
        if hasattr(self, 'event_panel'):
            self.align_panels()
        super().moveEvent(event)

    def resizeEvent(self, event):
        """Allow the window to keep its new size."""
        # Only perform layout updates here, do NOT call self.resize()
        # or it will create an infinite loop/snap-back effect.
        super().resizeEvent(event)
        if hasattr(self, 'aw') and self.aw:
            # Sync the parent window's geometry to match this window
            self.aw.setGeometry(self.geometry())
            # If the event panel exists, we need to update its width and reposition it
            if hasattr(self, 'event_panel') and self.event_panel:
                self.event_panel.setFixedWidth(self.width())
                self.event_panel.update_panel_height()
                self.event_panel.move(self.x(), self.y() + self.height())
