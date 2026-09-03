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

from matplotlib.axes import Axes
import numpy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # pylint: disable=unused-import
from pathlib import Path

#import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator



from artisanlib.atypes import ProfileData

from PyQt6.QtCore import (Qt, QPoint) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QResizeEvent, QAction) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QMessageBox, QMenu) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import (show_styled_message,
                                         THEME, RoastingPhase, marked, normalize_timeindex)
from tilauscope.cave.common import (
    _log, _PLOT_PALETTE, _FS_TITLE, _FS_AXIS, _FS_TICK, _FS_EVENT, _FS_HOVER, _FS_LEGEND)


class ViewerPlotMixin:
    """Drawing one roast: the curve, its milestone markers and the hover readout.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """



    def plot_bt_curve_preview(self, data: ProfileData, deltaet: list, deltabt: list) -> None:
        try:
            # Create lists to hold the curve references
            self.temp_lines = []
            self.setting_lines = []
            self.deltabt = deltabt
            self.deltaet = deltaet
            mode = data.get('mode', 'C')
            timex = data.get('timex', [])
            temp2 = data.get('temp2', [])
            temp1 = data.get('temp1', [])

            if not timex or not temp2:
                self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Roast data (BT) is missing in the file."))
                self.fig.clear()
                self.canvas.draw()
                return

            timeindex: list[int] = normalize_timeindex(data.get('timeindex', []))

            # Infer CHARGE / DROP from timex boundaries when not set
            if not marked(timeindex, RoastingPhase.CHARGE) or timeindex[RoastingPhase.CHARGE] >= len(timex):
                timeindex[RoastingPhase.CHARGE] = 0
            if not marked(timeindex, RoastingPhase.DROP) or timeindex[RoastingPhase.DROP] >= len(timex):
                timeindex[RoastingPhase.DROP] = len(timex) - 1

            charge = timeindex[RoastingPhase.CHARGE]
            charge_start = charge - 10 if charge >= 10 else charge
            drop = timeindex[RoastingPhase.DROP]
            drop_end = drop + 10 if len(timex) >= drop + 10 else drop
            x_vals = [(t-timex[charge]) / 60.0 for t in timex[charge_start:drop_end]]

            y_bt = temp2[charge_start:drop_end]
            y_et = temp1[charge_start:drop_end]

            y_det = deltaet[charge_start:drop_end] if deltaet else []
            y_dbt = deltabt[charge_start:drop_end] if deltabt else []

            y_det = [v if v is not None else 0.0 for v in y_det]
            self.y_dbt = [v if v is not None else 0.0 for v in y_dbt]

            if not x_vals or not y_bt:
                self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Roast data (sliced) is empty. Check charge/drop points."))
                self.fig.clear()
                self.fig.set_facecolor(_PLOT_PALETTE["background"])
                self.canvas.draw_idle()
                return

            self.fig.clear()
            # Create two subplots: ax1 for temperatures, ax2 for machine settings
            # hspace=0 ensures they are close to each other
            ax1:Axes
            ax2:Axes
            ax_hoovers:Axes
            ax1, ax2 = self.fig.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})

            #ax = self.fig.add_subplot(111)
            self.ax1 = ax1
            self.ax2 = ax2

            bg_color = _PLOT_PALETTE["background"]
            self.fig.set_facecolor(bg_color)
            from matplotlib.colors import to_hex, to_rgba # type:ignore[untyped-import,unused-ignore] # ty:ignore[ignore]

            xlabel_alpha_color = to_hex(to_rgba(_PLOT_PALETTE['xlabel'], 1.0), keep_alpha=True)
            ylabel_alpha_color = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 1.0), keep_alpha=True)

            ax1.set_facecolor(bg_color)
            ax1.tick_params(axis='x', colors=xlabel_alpha_color, labelsize=_FS_TICK)
            ax1.tick_params(axis='y', colors=ylabel_alpha_color, labelsize=_FS_TICK)
            ax1.spines['bottom'].set_color(_PLOT_PALETTE['grid'])
            ax1.spines['top'].set_color(_PLOT_PALETTE['grid'])
            ax1.spines['left'].set_color(_PLOT_PALETTE['grid'])
            ax1.spines['right'].set_color(_PLOT_PALETTE['grid'])
            # Adjust font size for the top plot (Temperatures)
            ax1.tick_params(axis='both', which='major', labelsize=_FS_TICK)

            ax1.plot(x_vals, y_bt, label=QApplication.translate("Label","BT")+f" (°{mode})", color=_PLOT_PALETTE["bt"], linewidth=1.3)
            ax1.plot(x_vals, y_et, label=QApplication.translate("Label","ET")+f" (°{mode})", color=_PLOT_PALETTE["et"], linewidth=1.3)

            ax_hoovers = ax1.twinx() # second axe
            self.ax_hoovers = ax_hoovers # used for plotted hoovers

            ax_hoovers.set_facecolor("none")  # transparent – shares bg with ax1
            ax_hoovers.tick_params(axis='y', colors=ylabel_alpha_color, labelsize=_FS_TICK)
            ax_hoovers.spines['right'].set_color(_PLOT_PALETTE['grid'])
            ax_hoovers.spines['left'].set_color(_PLOT_PALETTE['grid'])

            #Time
            self.annot_time = ax1.annotate("", xy=(0,0), xytext=(10, 20),
                textcoords="offset points", fontweight='bold', fontsize=_FS_HOVER, color='black',
                bbox=dict(boxstyle="square", fc="w", alpha=0.9))

            # Second line (e.g., BT Temperature)
            self.annot_bt = ax1.annotate("", xy=(0,0), xytext=(10, 10),
                textcoords="offset points", fontweight='bold', fontsize=_FS_HOVER,color=_PLOT_PALETTE['bt'],
                bbox=dict(boxstyle="square", fc="w", alpha=0.9))

            # Third line (e.g., ET Temperature)
            self.annot_et = ax1.annotate("", xy=(0,0), xytext=(10, 0),
                textcoords="offset points", fontweight='bold', fontsize=_FS_HOVER,color=_PLOT_PALETTE['et'],
                bbox=dict(boxstyle="square", fc="w",  alpha=0.9))

            #calc Y_MAX_ROR (multiple of 10)
            if self.y_dbt:
                max_ror = numpy.max(self.y_dbt)
                Y_MAX_ROR = numpy.ceil(max_ror / 10.0) * 10.0
                if (Y_MAX_ROR == 0 and max_ror > 0) or (Y_MAX_ROR < 10 and max_ror > 0):
                    Y_MAX_ROR = 10
            else:
                Y_MAX_ROR = 30

            ax_hoovers.set_ylim(0, Y_MAX_ROR)
            ax_hoovers.set_ylabel(QApplication.translate("Label","RoR")+" (°/min)", fontsize=_FS_AXIS, color=ylabel_alpha_color)

            ax_hoovers.plot(x_vals, self.y_dbt, label=QApplication.translate("Label","RoR")+" "+QApplication.translate("Label","BT"), color=_PLOT_PALETTE["deltabt"], linestyle='--', linewidth=1.3, alpha=0.85)
            ax_hoovers.plot(x_vals, y_det, label=QApplication.translate("Label","RoR")+" "+QApplication.translate("Label","ET"), color=_PLOT_PALETTE["deltaet"], linestyle='--', linewidth=1.3, alpha=0.85)

            x_min_val = min(x_vals)
            x_max_val = max(x_vals)
            x_start_tick = int(x_min_val) if x_min_val >= 0 or x_min_val.is_integer() else int(x_min_val) - 1
            x_end_tick = int(x_max_val) + 1
            x_ticks = list(range(x_start_tick, x_end_tick))
            x_labels = [str(i) for i in x_ticks]
            ax1.set_xticks(x_ticks)
            ax1.set_xticklabels(x_labels)

            # Échelle Y adaptative : la courbe BT occupe la pleine hauteur au lieu
            # du tiers inférieur d'un 0–300 figé. On garde ~10–20° d'air au-dessus
            # du pic BT (headroom +18° arrondi au 10 supérieur).
            temp_vals = [v for v in (list(y_bt) + list(y_et)) if v is not None]
            if temp_vals:
                t_min = min(temp_vals)
                t_max = max(temp_vals)
                Y_MIN = max(0, int(numpy.floor((t_min - 10) / 10.0) * 10))
                Y_MAX = int(numpy.ceil((t_max + 18) / 10.0) * 10)
                span = Y_MAX - Y_MIN
                Y_STEP = 50 if span > 200 else (25 if span > 100 else 10)
            else:
                Y_MIN, Y_MAX, Y_STEP = 0, 300, 50
            ax1.set_ylim(Y_MIN, Y_MAX)
            y_ticks = list(range(Y_MIN, Y_MAX + Y_STEP, Y_STEP))
            y_labels = [f"{i}" for i in y_ticks]
            ax1.set_yticks(y_ticks)
            ax1.set_yticklabels(y_labels)

            bbox_style_dark = dict(
                boxstyle="round,pad=0.3",
                fc="black",
                alpha=0.8,
                ec="lightgray",
                lw=1
            )

            # Reset tracking dicts then draw all non-(-1) events via shared helper
            self._event_vlines    = {}
            self._event_annots    = {}
            self._event_dots      = {}
            self._event_et_dots   = {}
            self._event_et_annots = {}
            self._pending_timeindex = None  # discard any unsaved edits from previous file
            self._draw_event_markers(ax1, timex, timeindex, temp2, temp1, mode, charge, bbox_style_dark,
                                     idx_min=charge_start, idx_max=drop_end)
            # titles and labels
            ax1.set_title(QApplication.translate("tilauscope_beancave","Curve Preview")+f": {data.get('title', 'Roast')}", fontsize=_FS_TITLE, color=_PLOT_PALETTE["title"])
            ax1.set_xlabel(QApplication.translate("tilauscope_beancave","Time (min)"), fontsize=_FS_AXIS, color=_PLOT_PALETTE['xlabel'])
            ax1.set_ylabel(QApplication.translate("tilauscope_beancave","Time")+f" (°{mode})", fontsize=_FS_AXIS, color=_PLOT_PALETTE['ylabel'])
            ax1.grid(True, alpha=0.3, color=_PLOT_PALETTE['grid'])
            #self.fig.tight_layout()
            self.annotation = ax1.annotate(
                '', xy=(0, 0), xytext=(20, 20), textcoords='offset points',
                bbox=dict(boxstyle="round", fc="w", alpha=0.9, ec="lightgray"),
                arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0.5",
                                color="w", linewidth=0.8),
                visible=False, fontsize=_FS_HOVER
            )

            if hasattr(self, 'annot_squares') and self.annot_squares:
                for sq in self.annot_squares:
                    try:
                        if sq in self.ax1.texts:
                            sq.remove()
                    except Exception:
                        pass
                self.annot_squares.clear()
            else:
                self.annot_squares = []
            self.curve_colors = [_PLOT_PALETTE["bt"], _PLOT_PALETTE["et"], _PLOT_PALETTE["deltabt"], _PLOT_PALETTE["deltaet"],
                                 '#FAB387', '#F38BA8', '#A6E3A1', '#89DCEB']
                                 #self.aw.qmc.EvalueColor[0], self.aw.qmc.EvalueColor[1], self.aw.qmc.EvalueColor[2], self.aw.qmc.EvalueColor[3]]
            for i in range(8):
                # Création d'une annotation par ligne de texte
                self.annot_squares.append(self.ax1.annotate(
                    "■",
                    xy=(0,0),
                    xytext=(20, 20), # Même base que self.annot
                    textcoords="offset points",
                    color=self.curve_colors[7-i],
                    va="top",         # "top" facilite l'alignement depuis le haut du bloc
                    ha="left",
                    visible=False,
                    zorder=10         # S'assure qu'ils sont au-dessus de la box
                ))

            # Plotting on the bottom axis

            # extra information
            names = data.get('etypes',[])
            event_types = data.get('specialeventstype', [])
            event_values = data.get('specialeventsvalue', [])
            event_times = data.get('specialevents', [])
            default_names = self.aw.qmc.etypesdefault


            # 1. Initialize Markers with high zorder and add them to ax1
            self.bt_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['bt'], markersize=5, visible=False, zorder=5)
            self.et_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['et'], markersize=5, visible=False, zorder=5)
            self.deltabt_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['deltabt'], markersize=5, visible=False, zorder=5)
            self.deltaet_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['deltaet'], markersize=5, visible=False, zorder=5)
            self.slider_marker=[]
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider0"], markersize=5, visible=False, zorder=5))
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider1"], markersize=5, visible=False, zorder=5))
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider2"], markersize=5, visible=False, zorder=5))
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider3"], markersize=5, visible=False, zorder=5))

            self.ax1.add_line(self.bt_marker)
            self.ax1.add_line(self.et_marker)
            self.ax_hoovers.add_line(self.deltabt_marker) # RoR marker goes on ax2            # Create the BT marker (dot)
            self.ax_hoovers.add_line(self.deltaet_marker) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[0]) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[1]) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[2]) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[3]) # RoR marker goes on ax2            # Create the ET marker (dot)

            self.bt_marker.set_visible(False)
            self.et_marker.set_visible(False)
            self.deltabt_marker.set_visible(False)
            self.deltaet_marker.set_visible(False)
            self.slider_marker[0].set_visible(False)
            self.slider_marker[1].set_visible(False)
            self.slider_marker[2].set_visible(False)
            self.slider_marker[3].set_visible(False)

            # Mapping table for labels/colors (using etypes)
            # Type IDs: 1=Burner, 2=Airflow, 3=Drum, 4=Airwave
            self.machine_config = {
                0: {'label': QApplication.translate("Combobox",names[0]) if names else QApplication.translate("Combobox",default_names[0]), 'color': _PLOT_PALETTE["slider0"], 'marker':None},
                1: {'label': QApplication.translate("Combobox",names[1] if names else QApplication.translate("Combobox",default_names[1])), 'color': _PLOT_PALETTE["slider1"],'marker':None},
                2: {'label': QApplication.translate("Combobox",names[2] if names else QApplication.translate("Combobox",default_names[2])), 'color': _PLOT_PALETTE["slider2"],'marker':None},
                3: {'label': QApplication.translate("Combobox",names[3] if names else QApplication.translate("Combobox",default_names[3])), 'color': _PLOT_PALETTE["slider3"],'marker':None}
            }

            # draw steps for each machine setting
            charge_time_abs = timex[charge_start]

            for etype, cfg in self.machine_config.items():
                y_stepped = []

                # Filter events for this specific type first
                type_times = [t for i, t in enumerate(event_times) if event_types[i] == etype]
                type_vals = [v for i, v in enumerate(event_values) if event_types[i] == etype]
                timex_events = [t for i, t in enumerate(timex) if i in type_times]

                if not type_times:
                    continue

                for x_min in x_vals:
                    # Convert the current plot-minute back to absolute log time
                    current_time_abs = charge_time_abs + (x_min * 60.0)

                    # Find the latest event value that happened BEFORE or AT this time
                    # We look for the max index where event_time <= current_time
                    val = 0.0
                    try:
                        for i in range(len(type_times)):
                            if i<len(timex_events) and timex_events[i] <= current_time_abs: # fix 2026/02/24 check for consistency between event time and timex time to avoid index error
                                val = self.aw.qmc.eventsInternal2ExternalValue(type_vals[i]) # fix 2026/02/20 convert internal to external value for display
                            else:
                                break # Events are sorted by time, so we can stop
                        y_stepped.append(val)
                    except Exception as e:
                        _log.debug(f"Error processing events for type {etype}: {e}")
                        y_stepped.append(0.0) # Default to 0 if there's an error
                # Only plot if there is actual non-zero data
                if any(v != 0 for v in y_stepped):
                    ax2.step(x_vals, y_stepped, where='post', color=cfg['color'],
                            label=cfg['label'], linewidth=1.2, alpha=0.9)

            # Final Styling
            ax2.set_facecolor(bg_color)
            ax2.set_ylabel(QApplication.translate("tilauscope_beancave",'Settings %'), color=_PLOT_PALETTE['ylabel'], fontsize=_FS_AXIS)
            ax2.tick_params(axis='y', labelcolor=ylabel_alpha_color)
            ax2.yaxis.set_major_locator(MultipleLocator(10))
            ax2.set_ylim(-5, 110)
            ax2.set_yticks(list(range(0, 101, 50)))
            ax2.grid(True, linestyle=':', alpha=0.3, color=_PLOT_PALETTE['grid'])
            # Only show legend if at least one labelled artist was plotted
            if ax2.get_legend_handles_labels()[0]:
                ax2.legend(
                    loc='upper center',
                    bbox_to_anchor=(0.5, -0.4),
                    fontsize=_FS_LEGEND,
                    ncol=4,
                    facecolor='#1e1e1e',
                    edgecolor='gray',
                    labelcolor='white'
                )
            ax2.tick_params(axis='both', which='major', labelsize=_FS_TICK)
            # Marges gérées par layout="constrained" (cf. création de la figure) —
            # plus de subplots_adjust codé en dur, la légende sous ax2 est prise en compte.
            if hasattr(self, 'hover_cid'):
                self.canvas.mpl_disconnect(self.hover_cid)
            self.curve_colors = [
                _PLOT_PALETTE["bt"],      # BT
                _PLOT_PALETTE["et"],      # ET
                _PLOT_PALETTE["deltabt"], # RoR BT
                _PLOT_PALETTE["deltaet"], # RoR ET
                _PLOT_PALETTE["slider0"],
                _PLOT_PALETTE["slider1"],
                _PLOT_PALETTE["slider2"],
                _PLOT_PALETTE["slider3"],
            ]
            self._reconnect_hover()  # connects hover AND leave, dropping the old pair
            # Hide save button — data just loaded, no pending edits
            self.canvas_container._save_btn.hide()
            self.canvas.draw_idle()
            self.last_plot_data = data # type: ignore

        except Exception as e:
            _log.error(f"Error generating plot: {e}", exc_info=True)
            self.fig.clear()
            self.fig.set_facecolor(_PLOT_PALETTE["background"])
            self.canvas.draw()

            self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Error generating plot: ")+f"{e}")

    def resizeEvent(self, event: QResizeEvent) -> None: # type: ignore
        redraw = False
        if event is not None: # type: ignore
            super().resizeEvent(event) # type: ignore
            redraw = True
        if redraw:
            try:
                self.canvas.draw()
            except Exception:
                pass

    # Value of channel `e` still in force at sample `sample_index`: a setting holds
    # until the next one replaces it.
    def findLastValidEvent(self, e:int, sample_index:int)->float:
        if self.last_plot_data is None:
            return 0.0
        eventtypes = self.last_plot_data.get('specialeventstype', []) # slider channel: 0,1,2,3
        # Artisan-INTERNAL values (8.0 = 70%). The caller decodes them with
        # eventsInternal2ExternalValue; they are not percentages here.
        eventvalues = self.last_plot_data.get('specialeventsvalue', [])
        # INDICES into timex, not seconds — in a .alog exactly as in the live qmc,
        # since Artisan saves and reloads this list verbatim. Which is why they are
        # compared against a sample index and never converted to a time.
        timestamp = self.last_plot_data.get('specialevents', [])
        last_value = -1.0

        for d in range(len(eventvalues)):
            if eventtypes[d] == e: #check only event of type e
                v = eventvalues[d] if eventvalues[d] is not None else 0.0
                ts = timestamp[d] if timestamp[d] is not None else 0
                if ts <= sample_index:
                    last_value = v
                else:
                    return last_value
        return last_value

    def on_plot_leave(self, event):
        """Fired when the mouse leaves the entire canvas area."""
        if hasattr(self, '_hover_tooltip'):
            self._hover_tooltip.hide()
        # Cacher les markers multi si actifs
        if hasattr(self, '_multi_markers'):
            for m in self._multi_markers:
                m.set_visible(False)
            self.canvas.draw_idle()

    # ── Timeindex remark via right-click ──────────────────────────────────────

    # Artisan timeindex slot names (index → display label)
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

    def _build_marker_menu(self, global_pos, widget_pos) -> None:
        """
        Build and exec the contextual marker-remark menu.
        global_pos : QPoint — screen position for menu.exec()
        widget_pos : QPoint | None — canvas-widget position for data conversion
        """
        if not hasattr(self, 'ax1') or self.ax1 is None:
            return
        if not hasattr(self, 'lastprofiledata') or not self.lastprofiledata:
            return

        data  = self.lastprofiledata
        timex = data.get('timex', [])
        if not timex:
            return

        timeindex: list[int] = normalize_timeindex(data.get('timeindex', []))

        charge_idx = timeindex[RoastingPhase.CHARGE]
        # If CHARGE is unset, use timex[0] as time origin so click position is still meaningful
        if charge_idx < 0 or charge_idx >= len(timex):
            charge_t = timex[0]
        else:
            charge_t = timex[charge_idx]

        # ── Convert Qt widget pos → matplotlib data x (minutes from CHARGE) ──
        x_min: float | None = None
        if widget_pos is not None:
            canvas_h = self.canvas.height()
            try:
                dpr = self.canvas.devicePixelRatioF()
            except AttributeError:
                dpr = 1.0
            disp_x = widget_pos.x() * dpr
            disp_y = (canvas_h - widget_pos.y()) * dpr
            try:
                inv = self.ax1.transData.inverted()
                x_data, _y_data = inv.transform((disp_x, disp_y))
                x_min = float(x_data)
            except Exception:
                x_min = None

        if x_min is None:
            return

        click_t = charge_t + x_min * 60.0

        # Artisan convention: val==0 means "unset" for all slots except CHARGE
        # val==-1 also means unset; only val>0 is a real placed marker
        set_events: list[tuple[int, float]] = sorted(
            [(slot, timex[val]) for slot, val in enumerate(timeindex)
             if slot < 8 and val > 0 and val < len(timex)],
            key=lambda x: x[1]
        )

        # No events set at all → offer the 4 main slots regardless of click position
        _MAIN_SLOTS = {RoastingPhase.CHARGE, RoastingPhase.DRYEND,
                       RoastingPhase.FCSTART, RoastingPhase.DROP}
        if not set_events:
            ordered = sorted(s for s in _MAIN_SLOTS if timeindex[s] <= 0)
        else:
            left_slot: int | None  = None
            right_slot: int | None = None
            for slot, t in set_events:
                if t <= click_t:
                    left_slot = slot
                elif right_slot is None:
                    right_slot = slot

            in_range = False
            candidates: set[int] = set()
            for slot, _t in set_events:
                if slot == left_slot:
                    in_range = True
                if in_range:
                    candidates.add(slot)
                if slot == right_slot:
                    break

            for slot in range(8):
                if slot in candidates or timeindex[slot] > 0:
                    continue
                if left_slot is not None and right_slot is not None and left_slot < slot < right_slot:
                    candidates.add(slot)
                elif left_slot is not None and right_slot is None and slot > left_slot:
                    candidates.add(slot)
                elif left_slot is None and right_slot is not None and slot < right_slot:
                    candidates.add(slot)

            ordered = sorted(candidates)

        if not ordered:
            return

        # Nearest timex index to click position
        nearest_idx = min(range(len(timex)), key=lambda i: abs(timex[i] - click_t))

        mode  = data.get('mode', 'C')
        temp2 = data.get('temp2', [])
        click_bt  = temp2[nearest_idx] if nearest_idx < len(temp2) else 0.0
        click_mm  = self.format_seconds(click_t - charge_t)

        # ── Hide hover tooltip + annotation before showing menu ────────────
        if hasattr(self, '_hover_tooltip'):
            self._hover_tooltip.hide()
        if hasattr(self, 'annotation') and self.annotation is not None:
            self.annotation.set_visible(False)
        if hasattr(self, 'annot_squares'):
            for sq in self.annot_squares:
                sq.set_visible(False)
        for m in [getattr(self, 'bt_marker', None), getattr(self, 'et_marker', None),
                  getattr(self, 'deltabt_marker', None), getattr(self, 'deltaet_marker', None)]:
            if m is not None:
                m.set_visible(False)
        self.canvas.draw_idle()

        # ── Build menu ─────────────────────────────────────────────────────
        menu = QMenu(self.canvas)
        menu.setStyleSheet(
            f"QMenu {{ background-color:{THEME['SURFACE']}; color:{THEME['TEXT']};"
            f"border:1px solid {THEME['BORDER']}; border-radius:6px; font-size:12px; padding:4px; }}"
            f"QMenu::item {{ padding:4px 18px; }}"
            f"QMenu::item:selected {{ background-color:{THEME['BORDER']}; }}"
            f"QMenu::item:disabled {{ color:{THEME['SUBTEXT']}; }}"
        )
        # Only "BT" is translatable here; the rest is an arrow and numbers, kept
        # out of the translated string so the lookup key stays stable per click.
        _bt = QApplication.translate("tilauscope_beancave", "BT")
        hdr = menu.addAction(f"→ {click_mm}  {_bt} {click_bt:.1f}°{mode}")
        hdr.setEnabled(False)
        menu.addSeparator()

        for slot in ordered:
            label   = self._TIMEINDEX_LABELS.get(slot, f'Event {slot}')
            old_idx = timeindex[slot]
            if marked(timeindex, slot) and old_idx < len(timex):
                old_mm = self.format_seconds(timex[old_idx] - charge_t)
                old_bt = temp2[old_idx] if old_idx < len(temp2) else 0.0
                entry  = f"{label}   {old_mm} → {click_mm}   ({old_bt:.1f}→{click_bt:.1f}°{mode})"
            else:
                entry  = f"{label}   [—] → {click_mm}   ({click_bt:.1f}°{mode})"
            act = QAction(entry, menu)
            act.setData(slot)
            menu.addAction(act)

        chosen = menu.exec(global_pos)
        if chosen is None or not chosen.isEnabled() or chosen.data() is None:
            return

        target_slot: int = chosen.data()
        # Work on pending copy — never mutate the cached lastprofiledata dict
        if self._pending_timeindex is None:
            raw = list(self.lastprofiledata.get('timeindex', []))  # type: ignore[arg-type]
            self._pending_timeindex = normalize_timeindex(raw)
        self._pending_timeindex[target_slot] = nearest_idx
        self._redraw_event_markers()
        # Build a view of lastprofiledata with pending timeindex for stats display
        _display_data = dict(self.lastprofiledata)
        _display_data['timeindex'] = self._pending_timeindex
        self.display_roast_info(_display_data)  # type: ignore[arg-type]
        self.canvas_container._save_btn.show()
        self.canvas_container._reposition_buttons()

    def _draw_event_markers(self, ax1, timex, timeindex, temp2, temp1, mode, charge_idx, bbox_style,
                            idx_min: int = 0, idx_max: int | None = None) -> None:
        """
        Draw all non-(-1) timeindex events onto ax1 and populate tracking dicts.
        idx_min/idx_max: only draw events whose timex index falls within [idx_min, idx_max).
        Must be called with cleared _event_vlines/annots/dots.
        """
        charge_t       = timex[charge_idx]
        if idx_max is None:
            idx_max = len(timex)
        vertical_offsets = [5, 10, 15, 20]
        offset_idx     = 0

        for slot, label in self._TIMEINDEX_LABELS.items():
            if slot >= len(timeindex):
                continue
            index = timeindex[slot]
            # val==0 means unset (Artisan convention), val==-1 also means unset
            if index <= 0 or index >= len(timex):
                continue
            # Skip events outside the visible plot range
            if index < idx_min or index >= idx_max:
                continue

            x_time     = timex[index] - charge_t
            x_min      = x_time / 60.0
            bt_val     = temp2[index] if index < len(temp2) else 0.0
            et_val     = temp1[index] if temp1 and index < len(temp1) else None

            vl = ax1.axvline(x=x_min, color='gray', linestyle=':', linewidth=0.8)
            self._event_vlines[label] = vl

            dot = ax1.plot(x_min, bt_val, marker='o',
                           color=_PLOT_PALETTE['bt'], markersize=3)[0]
            self._event_dots[label] = dot

            ann_text = f"{label}\n{bt_val:.1f}°{mode} ({self.format_seconds(x_time)})"
            y_off    = vertical_offsets[offset_idx % len(vertical_offsets)]
            offset_idx += 1
            ann = ax1.annotate(
                ann_text, (x_min, bt_val),
                textcoords="offset points", xytext=(5, y_off),
                ha='left', fontsize=_FS_EVENT, color='white', bbox=bbox_style,
            )
            self._event_annots[label] = ann

            if et_val is not None:
                et_dot = ax1.plot(x_min, et_val, marker='x',
                                  color=_PLOT_PALETTE['et'], markersize=3)[0]
                self._event_et_dots[label] = et_dot
                et_ann = ax1.annotate(
                    f"ET: {et_val:.1f}°{mode}", (x_min, et_val),
                    textcoords="offset points", xytext=(5, -15),
                    ha='left', fontsize=_FS_EVENT, color='white', bbox=bbox_style,
                )
                self._event_et_annots[label] = et_ann

    def _redraw_event_markers(self) -> None:
        """Remove old event artists from ax1, redraw using pending edits or lastprofiledata timeindex."""
        if not hasattr(self, 'ax1') or self.ax1 is None:
            return
        data      = self.lastprofiledata
        timex     = data.get('timex', [])
        # Use pending edits if present, otherwise fall back to the original profile (padded to 8)
        if self._pending_timeindex is not None:
            timeindex: list[int] = self._pending_timeindex
        else:
            timeindex = normalize_timeindex(data.get('timeindex', []))
        temp2     = data.get('temp2', [])
        temp1     = data.get('temp1', [])
        mode      = data.get('mode', 'C')

        # Remove all tracked artists
        for art_dict in (self._event_vlines, self._event_annots, self._event_dots,
                         self._event_et_dots, self._event_et_annots):
            for art in art_dict.values():
                try:
                    art.remove()  # type: ignore[union-attr]
                except Exception:
                    pass
        self._event_vlines.clear()
        self._event_annots.clear()
        self._event_dots.clear()
        self._event_et_dots.clear()
        self._event_et_annots.clear()

        if len(timeindex) < 8 or not timex:
            self.canvas.draw_idle()
            return

        charge_idx = timeindex[RoastingPhase.CHARGE]
        if charge_idx < 0 or charge_idx >= len(timex):
            self.canvas.draw_idle()
            return

        drop_idx   = timeindex[RoastingPhase.DROP]
        idx_min    = charge_idx - 10 if charge_idx >= 10 else charge_idx
        if not marked(timeindex, RoastingPhase.DROP):
            drop_idx = len(timex) - 1
        idx_max    = (drop_idx + 10) if drop_idx + 10 <= len(timex) else drop_idx

        bbox_style = dict(boxstyle="round,pad=0.3", fc="black", alpha=0.8, ec="lightgray", lw=1)
        self._draw_event_markers(self.ax1, timex, timeindex, temp2, temp1, mode, charge_idx, bbox_style,
                                 idx_min=idx_min, idx_max=idx_max)
        self.canvas.draw_idle()

    def _save_timeindex_to_alog(self) -> None:
        """Write updated timeindex back to the .alog file (Artisan native repr format) and invalidate cache."""
        if not hasattr(self, 'lastprofiledata') or not self.lastprofiledata:
            return
        if self._pending_timeindex is None:
            return
        item = self.roast_list_widget.currentItem()
        if item is None:
            return
        metadata = item.data(Qt.ItemDataRole.UserRole)
        if not metadata:
            return
        filepath = Path(self.alog_directory) / metadata["raw_fname"]
        try:
            # Artisan native format: repr(dict) written as UTF-8
            # (cf. artisanlib.util.serialize). Read back with ast.literal_eval.
            data_to_write = dict(self.lastprofiledata)
            data_to_write['timeindex'] = self._pending_timeindex
            filepath.write_text(repr(data_to_write), encoding='utf-8')
            # Invalidate LRU cache so next load reads the updated file
            cache_key = str(filepath)
            if cache_key in self._alog_cache:
                del self._alog_cache[cache_key]
            self._pending_timeindex = None
            self.canvas_container._save_btn.hide()
            _log.info(f"Saved updated timeindex to {filepath.name}")
        except Exception as e:
            _log.error(f"_save_timeindex_to_alog: {e}", exc_info=True)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_beancave", "Save Error"),
                str(e),
                QMessageBox.Icon.Critical,
            )

    def on_plot_hover(self, event) -> None:
        if self.ax1 is None or self.last_plot_data is None:
            return

        if event.inaxes not in (self.ax1, self.ax_hoovers):
            self._hover_tooltip.hide()
            # Cacher les marqueurs
            for m in [self.bt_marker, self.et_marker,
                    self.deltabt_marker, self.deltaet_marker]:
                m.set_visible(False)
            for m in self.slider_marker:
                m.set_visible(False)
            self.canvas.draw_idle()
            return

        x_data = event.xdata
        y_data = event.ydata
        if x_data is None or y_data is None:
            self._hover_tooltip.hide()
            return

        timex    = self.last_plot_data.get('timex', [])
        temp1    = self.last_plot_data.get('temp1', [])
        temp2    = self.last_plot_data.get('temp2', [])
        timeindex = normalize_timeindex(self.last_plot_data.get('timeindex', []))
        mode     = self.last_plot_data.get('mode', 'C')

        if not timex:
            return

        charge_idx      = timeindex[RoastingPhase.CHARGE] if marked(timeindex, RoastingPhase.CHARGE) else 0
        if charge_idx >= len(timex):
            return
        charge_time_s   = float(timex[charge_idx])
        current_time_s  = charge_time_s + (float(x_data) * 60.0)
        time_str        = self.format_seconds(current_time_s - charge_time_s)

        # Trouver l'index le plus proche
        t_idx = 0
        min_diff = float('inf')
        for i, t in enumerate(timex):
            diff = abs(t - current_time_s)
            if diff < min_diff:
                min_diff = diff
                t_idx = i
            if min_diff <= 1:
                break
        # Valeurs à afficher
        try:
            bt_val      = float(temp2[t_idx]) if t_idx < len(temp2) else None
            et_val      = float(temp1[t_idx]) if t_idx < len(temp1) else None
            dbt_val     = float(self.deltabt[t_idx]) if self.deltabt[t_idx] is not None and t_idx < len(self.deltabt) else None
            det_val     = float(self.deltaet[t_idx]) if self.deltaet[t_idx] is not None and t_idx < len(self.deltaet) else None
        except (TypeError, ValueError, IndexError):
            bt_val = et_val = dbt_val = det_val = None

        if bt_val is None or numpy.isnan(bt_val):
            self._hover_tooltip.hide()
            return

        # ── Mise à jour des marqueurs Matplotlib (points sur les courbes) ────────
        self.bt_marker.set_data([x_data], [bt_val])
        self.bt_marker.set_visible(True)
        if et_val is not None:
            self.et_marker.set_data([x_data], [et_val])
            self.et_marker.set_visible(True)
        if dbt_val is not None:
            self.deltabt_marker.set_data([x_data], [dbt_val])
            self.deltabt_marker.set_visible(True)
        if det_val is not None:
            self.deltaet_marker.set_data([x_data], [det_val])
            self.deltaet_marker.set_visible(True)

        # Sliders
        slider_vals = []
        for e in range(4):
            v = self.findLastValidEvent(e, t_idx)
            v1 = self.aw.qmc.eventsInternal2ExternalValue(v) if v >= 0 else -1
            if v1 >= 0:
                self.slider_marker[e].set_data([x_data], [v1])
                self.slider_marker[e].set_visible(True)
                slider_vals.append((e, v1))

        self.canvas.draw_idle()

        # ── Contenu du tooltip Qt ────────────────────────────────────────────────
        names  = self.last_plot_data.get('etypes', self.aw.qmc.etypesdefault)

        bt_col = '#04690E'
        et_col = '#E0124C'
        dbt_col = '#1E0AD9'
        det_col = '#E6871B'
        # Couleurs hex pour les pastilles HTML
#        bt_col  = self.aw.qmc.palette.get('bt',       '#04690E')
#        et_col  = self.aw.qmc.palette.get('et',       '#E0124C')
#        dbt_col = self.aw.qmc.palette.get('deltabt',  '#1E0AD9')
#        det_col = self.aw.qmc.palette.get('deltaet',  '#E6871B')

        def dot(color: str) -> str:
            return (f'<span style="color:{color}; '
                    f'font-size:14px; line-height:1;">&#9632;</span> ')

        lines = [
            f'<b style="color:{THEME["TEXT"]};">{QApplication.translate("Label","Time")} : {time_str}</b>',
            f'{dot(bt_col)}{QApplication.translate("Label","BT")} : {bt_val:.1f}°{mode}',
        ]
        if et_val is not None:
            lines.append(f'{dot(et_col)}{QApplication.translate("Label","ET")} : {et_val:.1f}°{mode}')
        if dbt_val is not None:
            lines.append(f'{dot(dbt_col)}{QApplication.translate("Label","RoR BT")} : {dbt_val:.1f}°{mode}/min')
        if det_val is not None:
            lines.append(f'{dot(det_col)}{QApplication.translate("Label","RoR ET")} : {det_val:.1f}°{mode}/min')

        slider_colors = [_PLOT_PALETTE[f"slider{i}"] for i in range(4)]
        for e, v1 in slider_vals:
            name = QApplication.translate("Combobox",
                        names[e] if e < len(names)
                        else self.aw.qmc.etypesdefault[e])
            lines.append(f'{dot(slider_colors[e])}{name} : {v1:.0f}%')

        html = '<br>'.join(lines)
        if event.xdata is None or event.ydata is None:
            self._hover_tooltip.hide()
            return

        if event.guiEvent is not None:
            global_point = event.guiEvent.globalPosition().toPoint()
        else:
            ## fallback for non-interactive backends
            device_ratio = self.canvas.devicePixelRatioF()
            x_canvas = int(event.x / device_ratio)
            y_canvas = int((self.canvas.height() * device_ratio - event.y) / device_ratio)
            local_point = QPoint(x_canvas, y_canvas)
            global_point = self.canvas.mapToGlobal(local_point)
        if event.inaxes:
            self._hover_tooltip.show_at(global_point, html)
        else:
            # Hide if we are on the canvas but not on the axes
            if hasattr(self, 'annotation'):
                self.annotation.hide()

    def take_snapshot(self, figure, filename: str|None = None) -> None:
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        """Opens a file dialog to save the Matplotlib figure as a PNG snapshot."""
        # Selected, not current: the current item is the keyboard cursor and is
        # None right after the list is rebuilt — reading it raised inside a
        # clicked slot, which the excepthook turns into closing the application.
        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            return
        metadata = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if not isinstance(metadata, dict) or not metadata.get("raw_fname"):
            return
        f = metadata["raw_fname"]

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
                # Save the Matplotlib figure to the specified file
                # The entire Figure (including axes, labels, etc.) is saved.
                figure.savefig(file_path)
                self._show_message(self, QApplication.translate("tilauscope_beancave","Snapshot Successful"),
                                        QApplication.translate("tilauscope_beancave","The curve has been successfully saved to:")+f"\n{file_path}")
                # show the snapshot straight away, like the roast card does
                self.try_to_open_file(file_path)
            except Exception as e:
                self._show_message(self, QApplication.translate("tilauscope_beancave","Save Error"),
                                     QApplication.translate("tilauscope_beancave","An error occurred while saving the figure:")+f"\n{e}", QMessageBox.Icon.Critical)
