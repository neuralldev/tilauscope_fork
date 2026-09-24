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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # pylint: disable=unused-import
from pathlib import Path

from artisanlib.atypes import ProfileData
from tilauscope.probe_visibility import et_available_in_profile

from PyQt6.QtCore import QPoint # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtWidgets import (QApplication, QMessageBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import (show_styled_message, RoastingPhase,
                                         normalize_timeindex)
from tilauscope.cave.common import (_log, _atomic_write_text)


class ViewerPlotMixin:
    """Drawing one roast: the curve, its milestone markers and the hover readout.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """



    def show_roast_on_engine(self, data: ProfileData, deltaet: list, deltabt: list) -> None:
        """Draw one saved roast with TilauScope's own curve engine.

        The same drawing as the window the roast was driven on: one frame, one
        phase ground, milestones parked above the curves, the levers in the
        strips underneath. A milestone dragged here is proposed by the engine
        and written back by this dialog, which is the one that owns the file.
        """
        from tilauscope.graph import comparison as compare

        self._plot_cache = (data, deltaet, deltabt)
        shown = dict(data)
        saved = None
        if self._pending_timeindex is not None:
            # A correction made and not yet saved is what the operator is
            # looking at, and what any further correction is measured from.
            shown['timeindex'] = list(self._pending_timeindex)
            saved = normalize_timeindex(list(data.get('timeindex') or []))
        qmc = getattr(self.aw, 'qmc', None)
        try:
            pcts = [qmc.eventsInternal2ExternalValue(v)
                    for v in (data.get('specialeventsvalue') or [])]
        except Exception:
            pcts = []
        roast = compare.from_profile(
            shown, colour=None, title=str(data.get('title') or ''),
            deltabt=deltabt,
            deltaet=deltaet if et_available_in_profile(data) else [],
            ev_pcts=pcts)
        if roast is None:
            self.roast_info_text.setText(QApplication.translate(
                "tilauscope_beancave", "The file holds no readings to draw."))
            # The roast left on screen is not the one on file any more: nothing may be corrected on it.
            self.roast_curve.release_editor()
            return
        self.roast_curve.set_comparison([roast], editor=self._engine_milestone_moved, saved=saved)
        self._apply_engine_view()
        self.canvas_stack.setCurrentWidget(self.roast_curve)
        self.roast_plot_label.setText("")
        self.display_roast_info(shown)  # type: ignore[arg-type]
        analysis_view = getattr(self, 'roast_analysis_view', None)
        if analysis_view is not None and self.selected_roast_fnames() == [self._displayed_fname]:
            analysis_view.set_profile(shown, deltabt, self.aw.qmc.mode,
                                      self.previous_roast(self._displayed_fname))

    def _engine_milestone_moved(self, milestone: int, index: int) -> None:
        """A milestone dragged on the engine, held until the operator saves it.

        Nothing is written to the file here: the correction joins the pending
        timeline, which the pill above the curve saves or undoes.
        """
        data = self.displayed_profile()
        if not data:
            return
        on_file = normalize_timeindex(list(data.get('timeindex', [])))
        if self._pending_timeindex is None:
            self._pending_timeindex = list(on_file)
        self._pending_timeindex[milestone] = index
        if self._pending_timeindex == on_file:
            # Put back where the file has it: nothing is left to save.
            self._pending_timeindex = None
        self._replot_single()

    def _undo_pending_markers(self) -> None:
        """Drop the staged correction: the roast is drawn again as its file holds it."""
        self._pending_timeindex = None
        self._replot_single()

    def plot_bt_curve_preview(self, data: ProfileData, deltaet: list, deltabt: list) -> None:
        """One roast on screen. Drawn by the curve engine, like every other roast."""
        self.show_roast_on_engine(data, deltaet, deltabt)

    def _apply_curve_view(self) -> None:
        """Temperatures, rate of rise or both, on the roast already drawn."""
        view = getattr(self, '_curve_view', 'both')
        self._apply_engine_view(temps=view in ('temps', 'both'),
                                rate=view in ('ror', 'both'))

    def _apply_engine_view(self, *, temps: bool | None = None,
                           rate: bool | None = None) -> None:
        """Hand the card's switches to the curve engine, all four at once."""
        view = getattr(self, '_curve_view', 'both')
        mode = getattr(self, '_curve_range', 'auto')
        if mode == 'fixed':
            window: tuple[float, float] | None = (0.0, 720.0)
        elif mode == 'custom':
            window = tuple(getattr(self, '_curve_custom_range', (0.0, 720.0)))  # type: ignore[assignment]
        else:
            window = None       # the engine frames the roast itself
        self.roast_curve.set_static_view(
            temps=view in ('temps', 'both') if temps is None else temps,
            rate=view in ('ror', 'both') if rate is None else rate,
            lanes=bool(getattr(self, '_curve_show_settings', True)),
            window=window)

    def _apply_time_range(self) -> None:
        """Auto, 0–12 min or a custom range, on the roast already drawn."""
        self._apply_engine_view()

    def _replot_single(self) -> None:
        """Draw the roast on screen again from what is loaded, for a change of layout or of milestones."""
        cache = getattr(self, '_plot_cache', None)
        if getattr(self, '_multi_mode', False) or cache is None:
            return
        try:
            self.show_roast_on_engine(*cache)
            self._apply_engine_view()
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            # Called from slots: an escape would reach the excepthook and close the app.
            _log.error(f"_replot_single: {e}", exc_info=True)

    _TIMEINDEX_LABELS: dict[int, str] = {
        RoastingPhase.CHARGE:  'CHARGE',
        RoastingPhase.DRYEND:  'DRY END',
        RoastingPhase.FCSTART: 'FC start',
        RoastingPhase.FCEND:   'FC end',
        RoastingPhase.SCSTART: 'SC start',
        RoastingPhase.SCEND:   'SC end',
        RoastingPhase.DROP:    'DROP',
        RoastingPhase.COOLEND: 'COOL end',
    }

    def _save_timeindex_to_alog(self) -> None:
        """Write updated timeindex back to the .alog file (Artisan native repr format) and invalidate cache."""
        if self._pending_timeindex is None:
            return
        # Both the file and its contents come from the roast on the canvas. The
        # list cursor answers a different roast than the selection after a
        # ctrl-click or a background rebuild, and `lastprofiledata` is shared
        # with the Roast Plan tab: taking one from each wrote roast B into the
        # file of roast A and lost A.
        filepath = self.displayed_profile_path()
        source = self.displayed_profile()
        if filepath is None or not source:
            return
        try:
            # Artisan native format: repr(dict) written as UTF-8
            # (cf. artisanlib.util.serialize). Read back with ast.literal_eval.
            data_to_write = dict(source)
            data_to_write['timeindex'] = self._pending_timeindex
            # Through the temporary file, never over the profile itself: this
            # rewrites a whole roast to change one number, and a write cut
            # short — a full disk, an unplugged drive, a crash — would leave a
            # truncated file where the roast used to be, with no copy of it.
            _atomic_write_text(filepath, repr(data_to_write), 'utf-8')
            # Invalidate LRU cache so next load reads the updated file
            cache_key = str(filepath)
            with self._alog_cache_lock:
                self._alog_cache.pop(cache_key, None)
            # Carry the saved milestones into the dict still held in memory:
            # without it a second correction rebuilt its pending list from the
            # pre-save values and silently reverted the first one.
            source['timeindex'] = list(self._pending_timeindex)
            self._pending_timeindex = None
            _log.info(f"Saved updated timeindex to {filepath.name}")
        except Exception as e:
            _log.error(f"_save_timeindex_to_alog: {e}", exc_info=True)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_beancave", "Save Error"),
                str(e),
                QMessageBox.Icon.Critical,
            )
            return
        cache = getattr(self, '_plot_cache', None)
        if cache is not None:
            # Drawn again from the roast as now saved, so the pill has nothing left to name.
            self._plot_cache = (source, *cache[1:])
            self._replot_single()

    def take_snapshot(self, filename: str | None = None) -> None:
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        """Opens a file dialog to save the Matplotlib figure as a PNG snapshot."""
        # Selected, not current: the current item is the keyboard cursor and is
        # None right after the list is rebuilt — reading it raised inside a
        # clicked slot, which the excepthook turns into closing the application.
        selected = self.selected_roast_fnames()
        if not selected:
            return
        f = selected[0]

        from PyQt6.QtCore import QStandardPaths

        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )

        default_path = str(Path(downloads_dir) / f)

        file_path = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave","Save Curve Snapshot as PNG"),
            default_path,
            QApplication.translate("tilauscope_beancave", "PN Files (*.png);;All Files (*)")
        )

        if file_path:
            try:
                # A picture of what is on screen: the roast is drawn by the
                # curve engine, and the engine is a widget, not a figure.
                self.roast_curve.snapshot().save(file_path)
                self._show_message(self, QApplication.translate("tilauscope_beancave","Snapshot Successful"),
                                        QApplication.translate("tilauscope_beancave","The curve has been successfully saved to:")+f"\n{file_path}")
                # show the snapshot straight away, like the roast card does
                self.try_to_open_file(file_path)
            except Exception as e:
                self._show_message(self, QApplication.translate("tilauscope_beancave","Save Error"),
                                     QApplication.translate("tilauscope_beancave","An error occurred while saving the figure:")+f"\n{e}", QMessageBox.Icon.Critical)
