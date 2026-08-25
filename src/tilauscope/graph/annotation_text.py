#
# ABOUT
# the text inside the two cards that float over the roast curve

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
# TiLau 2025-2026

"""What the roast card and the preheat card say.

Moved out of the canvas, where it had grown into nine hundred lines of rich text
inside Artisan's hottest file. Nothing here draws: each function takes the roast
state and returns a block of HTML.

Everything reads `qmc` and, through it, the application window. No function here
touches the TilauScope window, which may well be closed while a preheat runs —
that property is what let the code move at all, and it has to survive.

The translated labels are built once and cached. Artisan does not support
changing language mid-session, and rebuilding sixty translated strings on a
1-4 Hz path would be the single most expensive thing on it.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from PyQt6.QtWidgets import QApplication

from artisanlib.util import stringfromseconds
from tilauscope.tilauscope_types import get_agtron_color
from tilauscope.graph.common import delta_scale, report_once, within_share
from tilauscope.tilauscope_types import get_roc_color as _omniflux_roc_color

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Constant colour palettes, built once rather than on every refresh.
_PID_COLORS: Final[dict[str, str]] = {
    'manual':      '#FF5555',  # red    — alert
    'scheduling':  '#55FF55',  # green  — scheduling mode
    'ramp/soak':   '#55AAFF',  # blue   — ramp/soak mode
    'highlighted': '#FFFF55',  # yellow — active segment / warning
    'label':       '#AAAAAA',  # grey   — captions
    'value':       '#FFFFFF',  # white  — neutral values
    'close':       '#55FF55',  # green  — input near the SV (<5°)
    'middle':      '#FFFF55',  # yellow — input approaching the SV (<15°)
}
_ANNO_COLORS: Final[dict[str, str]] = {
    'manual':      '#FF5555',  # red    — alert
    'highlighted': '#FFFF55',  # yellow — warning / approach
    'label':       '#AAAAAA',  # grey   — captions
    'value':       '#FFFFFF',  # white  — neutral values
}

_LABELS: dict[str, str] | None = None
_PHASE_MAP: dict[str, tuple[str, str]] | None = None


def _labels() -> dict[str, str]:
    """Translated labels, built on first use and kept."""
    global _LABELS   # noqa: PLW0603 - one cache, filled once
    if _LABELS is None:
        _LABELS = {
            'SV': QApplication.translate('Label', 'SV'),
            'PID': QApplication.translate('Tab', 'PID'),
            'Manual': QApplication.translate('Label', 'Manual'),
            'Delta': QApplication.translate('Label', 'Delta'),
            'Mode': QApplication.translate('Label', 'Mode'),
            'ET': QApplication.translate('Label', 'ET'),
            'BT': QApplication.translate('Label', 'BT'),
            'Color': QApplication.translate('Label', 'Color'),
            'Ramp': QApplication.translate('Table', 'Ramp'),
            'Segments': QApplication.translate('Label', 'Segment'),
            'Soak': QApplication.translate('Table', 'Soak'),
            'Scheduling': QApplication.translate('Label', 'Scheduling'),
            'PV': QApplication.translate('Label', 'PV'),
            'Time': QApplication.translate('Label', 'Time'),
            'Target': QApplication.translate('Label', 'Target'),
            'Temp': QApplication.translate('Label', 'Temp'),
            'FC': QApplication.translate('Label', 'FC'),
            'SCS': QApplication.translate('Label', 'SC START'),
            'SCE': QApplication.translate('Label', 'SC END'),
            'DRY': QApplication.translate('Label', 'DRY'),
            'DROP': QApplication.translate('Label', 'DROP'),
            'Cooling': QApplication.translate('Label', 'Cooling'),
            'DEV': QApplication.translate('Label', 'Development Phase'),
            'MAI': QApplication.translate('Label', 'Maillard Phase'),
            'FCcounter':QApplication.translate('tilauscope_graph', 'FC counter'),
            'from':QApplication.translate('Label', 'from'),
            'Preheat': QApplication.translate('Label', 'Preheat'),
            ## TILAU ## TilauPID preheat annotation (Artisan canvas, no TilauScope window needed)
            'ReadyIn': QApplication.translate('tilauscope_graph', 'READY IN'),
            'ReadyToCharge': QApplication.translate('tilauscope_graph', 'READY TO CHARGE'),
            'Stabilizing': QApplication.translate('tilauscope_graph', 'STABILIZING'),
            'Heating': QApplication.translate('tilauscope_graph', 'HEATING'),
            ## TILAU ## Learning-maturity badge (EXPERIENCE band + capability lines) — cached
            ## once per TilauPreheatPID.start(), never rebuilt on the canvas redraw path.
            'Experience': QApplication.translate('tilauscope_graph', 'EXPERIENCE'),
            'LevelLearning': QApplication.translate('tilauscope_graph', 'Learning'),
            'LevelEstimated': QApplication.translate('tilauscope_graph', 'Estimated'),
            'LevelTuned': QApplication.translate('tilauscope_graph', 'Tuned'),
            'LevelCalibrated': QApplication.translate('tilauscope_graph', 'Calibrated'),
            'FirstPreheatSub': QApplication.translate('tilauscope_graph', 'First preheat at this setpoint'),
            'EstimatedSub': QApplication.translate('tilauscope_graph', 'Adjusted from nearby setpoints'),
            'CounterPreheats': QApplication.translate('tilauscope_graph', '{n} preheats'),
            'CounterRoasts': QApplication.translate('tilauscope_graph', '{n} roasts'),
            'CapHold_check': QApplication.translate('tilauscope_graph', 'Knows the heat that holds this target'),
            'CapHold_approx': QApplication.translate('tilauscope_graph', 'Estimating the heat from past roasts'),
            'CapHold_learning': QApplication.translate('tilauscope_graph', 'Still learning the heat that holds this target'),
            'CapLead_check': QApplication.translate('tilauscope_graph', 'Knows when to back off'),
            'CapLead_approx': QApplication.translate('tilauscope_graph', 'Estimating when to back off'),
            'CapLead_learning': QApplication.translate('tilauscope_graph', 'Still learning when to back off'),
            'SimNotRecorded': QApplication.translate('tilauscope_graph', 'Simulation — not recorded'),
            'DryingPhase': QApplication.translate('tilauscope_graph', 'Drying Phase'),
            'CoolingPhase': QApplication.translate('Button', 'Cooling Phase'),
            # ── Coach (guided simplified view) — cached once, never on the hot path
            'coach_toward_dry':     QApplication.translate('tilauscope_graph', 'to DRY END'),
            'coach_toward_fc':      QApplication.translate('tilauscope_graph', 'to 1C'),
            'coach_toward_drop':    QApplication.translate('tilauscope_graph', 'to DROP'),
            'coach_dry_in':         QApplication.translate('tilauscope_graph', 'DRY END in'),
            'coach_fc_in':          QApplication.translate('tilauscope_graph', '1C in'),
            'coach_on_track':       QApplication.translate('tilauscope_graph', '✓ On track'),
            'coach_approaching_dry':QApplication.translate('tilauscope_graph', '⚠ Approaching DRY END — ease the heat'),
            'coach_fc_imminent':    QApplication.translate('tilauscope_graph', '👂 1C imminent — get ready to cut power'),
            'coach_fc_approaching': QApplication.translate('tilauscope_graph', '⚠ 1C approaching — get ready to reduce'),
            'coach_cracks_heard':   QApplication.translate('tilauscope_graph', '👂 Cracks starting…'),
            'coach_browning_ok':    QApplication.translate('tilauscope_graph', '✓ Steady browning'),
            'coach_dev_ok':         QApplication.translate('tilauscope_graph', '✓ Development on track'),
            'coach_underdeveloped': QApplication.translate('tilauscope_graph', '⚠ Under-developed — let it ride'),
            'coach_ready_drop':     QApplication.translate('tilauscope_graph', '⏏ Ready to DROP'),
            'coach_cool_fast':      QApplication.translate('tilauscope_graph', 'Cool down fast'),
            'coach_dev_short':      QApplication.translate('tilauscope_graph', 'DEV'),
        }
    return _LABELS


def _phase_map() -> dict[str, tuple[str, str]]:
    """Phase title and header colour per roast phase, built from the labels."""
    global _PHASE_MAP   # noqa: PLW0603 - one cache, filled once
    if _PHASE_MAP is None:
        L = _labels()
        _PHASE_MAP = {
            'CHARGE': (L['DryingPhase'], '#42A5F5'),  # Blue   — CHARGE → DRY END
            'DE':     (L['MAI'],         '#FFA726'),  # Orange — DRY END → FCs
            'FC':     (L['DEV'],         '#EF5350'),  # Red    — FCs → DROP
            'SCs':    (L['DEV'],         '#EF5350'),  # Red    — idem (SCs en cours)
            'SCe':    (L['DEV'],         '#EF5350'),  # Red    — idem (SCe en cours)
            'DROP':   (L['CoolingPhase'],'#26C6DA'),  # Cyan   — après DROP
        }
    return _PHASE_MAP


def reset_labels() -> None:
    """Drop the caches. For tests that install a translator after import."""
    global _LABELS, _PHASE_MAP   # noqa: PLW0603 - the caches above
    _LABELS = _PHASE_MAP = None


def _get_tilaupid_text(qmc: Any, pid, et: float, bt: float) -> str:
    """## TILAU ## Preheat monitor drawn on the Artisan canvas while TilauPID ramps
    the roaster to its target SV (recording started, CHARGE not marked yet). Reads
    only qmc + the PID object — never the TilauScope window, which may well be closed.
    All values stay in the current Artisan unit; sv_native() is the single conversion.

    Three fixed zones (header, READY IN hero + climb gauge, EXPERIENCE learning badge).
    The EXPERIENCE band and the two capability lines are pre-built HTML cached on the PID
    object at TilauPreheatPID.start() (pid.learning_badge_html) — this method only reads
    that attribute and pid.ramp_start_temp; no QSettings/corpus/file I/O on this hot path.
    Must never raise: any missing/malformed PID attribute falls back to a minimal render."""
    L = _labels()
    mode = qmc.mode
    try:
        sv = float(pid.sv_native())
        # same input channel the PID cycle is fed with (see sample(): BT for pidSource 0/1)
        on_bt = qmc.aw.pidcontrol.pidSource in (0, 1)
        pid_input = bt if on_bt else et
        delta = sv - pid_input

        # proximity band: identical rule to the TilauScope SV mirror (5 % of SV,
        # or past SV) — judged in °C so °F reads the same physical band
        close = (delta <= 0) or within_share(delta, sv, 0.05, mode)
        # Approach-state colour — drives the top rule, header, gauge fill and (except
        # STABILIZING, always yellow) the hero line: green in the close band, yellow
        # while approaching (<15° away), blue while still far.
        if close:
            state_color = '#A6E3A1'
        elif abs(delta) < 15 * delta_scale(mode):
            state_color = '#F9E2AF'
        else:
            state_color = '#89B4FA'

        # qmc.delta1/qmc.delta2 hold the RoR *display* value, clipped to None by RoRlimitFlag
        # (default -10..45 C/min) whenever it exits that band — a bound sized for a normal roast,
        # routinely exceeded during an aggressive preheat ramp. qmc.rateofchange1/2 is the same
        # smoothed RoR before that clipping (also what the PID itself is fed), so it stays a real
        # number here instead of flipping to None mid-ramp.
        ror = qmc.rateofchange2 if on_bt else qmc.rateofchange1

        # ETA to SV — same convention as the phase predictions: only meaningful while climbing.
        # A tapering burner (lead-based anticipation, see TilauPreheatPID.compute_fuzzy_power)
        # lets the displayed RoR sag to <=0 well before the close band is reached; that is
        # normal deceleration, not a stall, so it gets its own label instead of a frozen --:--.
        # Early in the ramp the RoR is still building thermal momentum, so a linear projection
        # from that low instantaneous value can wildly overshoot (e.g. hours) — cap it and fall
        # back to the same label rather than show an implausible countdown.
        _TILAUPID_ETA_CAP_SEC = 600.  # 10 min
        eta_seconds = (delta / ror * 60.) if (ror is not None and ror > 0 and delta > 0) else None

        # Hero state — identical branching to before; only size/colour changed.
        # The "READY IN" caption only belongs above an actual countdown: over
        # "READY TO CHARGE" it contradicts it. Blanked (not removed) in the other
        # states so the block keeps its geometry through the whole preheat.
        # The "READY IN" caption only belongs above an actual countdown. In the
        # worded states it is dropped entirely rather than blanked: an empty line
        # left a conspicuous hole under the header.
        if close:
            hero_text, hero_size, hero_color = L['ReadyToCharge'], 13, '#A6E3A1'
            hero_caption = ''
        elif eta_seconds is not None and eta_seconds <= _TILAUPID_ETA_CAP_SEC:
            hero_text, hero_size, hero_color = stringfromseconds(eta_seconds), 17, state_color
            hero_caption = L['ReadyIn']
        elif delta > 0 and ror is not None and ror > 0:
            # Still climbing, just too early for the projection to mean anything —
            # calling that "stabilizing" contradicts what the operator sees.
            hero_text, hero_size, hero_color = L['Heating'], 13, state_color
            hero_caption = ''
        elif delta > 0:
            hero_text, hero_size, hero_color = L['Stabilizing'], 13, '#F9E2AF'
            hero_caption = ''
        else:
            hero_text, hero_size, hero_color = '--:--', 17, '#6C7086'
            hero_caption = L['ReadyIn']
        caption_html = (
            f'<div style="margin-top:3px;"><span style="color:#6C7086;font-size:9px;">'
            f'{hero_caption}</span></div>' if hero_caption else ''
        )

        # Climb gauge: progress from the ramp-start temperature (captured by the PID on
        # its first valid cycle — TilauPreheatPID.ramp_start_temp) toward SV, on the same
        # input channel. No baseline yet (attribute missing or still None) → empty gauge.
        #
        # Drawn with block characters, NOT table cells: Qt's rich-text subset ignores
        # px width/height on <td> and collapses such a cell to its glyph, which turned
        # the whole gauge into a dotted line. Glyph runs always render.
        _GAUGE_CELLS = 10
        ramp_start = getattr(pid, 'ramp_start_temp', None)
        if close:
            progress = 1.0
        elif ramp_start is not None and sv > ramp_start:
            progress = max(0.0, min(1.0, (pid_input - ramp_start) / (sv - ramp_start)))
        else:
            progress = None
        fill_cells = int(round(progress * _GAUGE_CELLS)) if progress is not None else 0
        gauge_html = (
            f'<span style="color:{state_color};">{"&#9608;" * fill_cells}</span>'
            f'<span style="color:#45475A;">{"&#9608;" * (_GAUGE_CELLS - fill_cells)}</span>'
        )

        # The EXPERIENCE band that used to close this card is gone. It is
        # rendered in full on the preheat panel a few centimetres to the left,
        # and a card floating over the climb has to earn every line it takes:
        # what is left is the countdown, how far the drum has come, and how far
        # it has to go.
        #
        # No tables anywhere: `width:100%` is not honoured either, so a
        # two-column header silently collapsed into "TilauPID185°C". Everything
        # is left-aligned in a single flow, values carried by their own line.
        return f"""
            <div style="background-color: rgba(24, 24, 37, 0.85); border: 1px solid #45475A; border-radius: 6px; padding: 5px 8px;">
                <div><span style="color: {state_color}; font-weight: bold; font-size: 11px;">{L['Preheat']} &middot; TilauPID</span></div>
                {caption_html}
                <div style="margin-top: {0 if hero_caption else 3}px;"><span style="color: {hero_color}; font-weight: bold; font-size: {hero_size}px;">{hero_text}</span></div>
                <div style="margin-top: 1px;"><span style="font-size: 10px;">{gauge_html}</span>
                <span style="color: #6C7086; font-size: 10px;"> &nbsp;{delta:+.0f}&deg;{mode}</span></div>
            </div>
            """
    except Exception as e: # pylint: disable=broad-except
        # The annotation must never take the canvas redraw down with it.
        _log.exception(e)
        return f"""
            <div style="min-width: 140px; background-color: rgba(24, 24, 37, 0.7); border: 1px solid #45475A; border-radius: 8px; padding: 10px;">
                <span style="color: #89B4FA; font-weight: bold; font-size: 14px;">{L.get('Preheat', 'Preheat')} &middot; TilauPID</span>
            </div>
            """

def _get_pid_text(qmc: Any, pid, tx, et, bt):
    L = _labels() # Use cached translations
    mode = qmc.mode
    time_str = stringfromseconds(tx)

    colors = _PID_COLORS

    mode_display = L['Scheduling'] if pid.pidGainScheduling else (f"{L['Ramp']}/{L['Soak']}" if pid.svMode == 1 and (pid.ramp_soak_engaged or 0) > 0 else L['Manual'])
    _pid_mode_key = 'scheduling' if pid.pidGainScheduling else ('ramp/soak' if pid.svMode == 1 and (pid.ramp_soak_engaged or 0) > 0 else 'manual')
    header_color = colors.get(_pid_mode_key, "#00CCFF")

    html = f"""
            <div style="min-width: 140px; background-color: rgba(24, 24, 37, 0.7); border: 1px solid #45475A; border-radius: 8px; padding: 10px;">
                <div style="border-bottom: 1px solid {header_color}; margin-bottom: 6px; padding-bottom: 2px;">
                    <span style="color: {header_color}; font-weight: bold; font-size: 14px; letter-spacing: 1px;">
                        {L['Mode']} {mode_display}
                    </span>
                </div>   
                <table border="0" cellspacing="0" cellpadding="2" style="width: 100%;">
            """
    t1, t2 = (bt, et) if qmc.swapETBT else (et, bt)
    l1, l2 = (L['BT'], L['ET']) if qmc.swapETBT else (L['ET'], L['BT'])
    if pid.pidGainScheduling:
        to_follow = L['SV'] if pid.pidGainSchedulingSV else L['PV']
        if pid.pidGainSchedulingQuadratic:
            sched_type = "(x2)"
            sv_pv_val = pid.pidSchedule0 if bt <= pid.pidSchedule0 else (pid.pidSchedule1 if bt <= pid.pidSchedule1 else pid.pidSchedule2)
        else:
            sched_type = "(x)"
            sv_pv_val = pid.pidSchedule0 if bt <= pid.pidSchedule0 else pid.pidSchedule1
        html += f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{to_follow} {sched_type}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{sv_pv_val:.0f}°{mode}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{l1}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{t1:.1f}°{mode}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{l2}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{t2:.1f}°{mode}</td>
                </tr>
                </table>
                """
        return html
    elif pid.svMode == 1 and (pid.ramp_soak_engaged or 0) > 0:
        segment = pid.current_ramp_segment or 0
        # number of actually configured segments (svValue != 0 or ramp/soak != 0)
        rslen = sum(1 for i in range(pid.svLen) if pid.svValues[i] != 0.0 or pid.svRamps[i] != 0 or pid.svSoaks[i] != 0)
        is_ramping = (pid.current_soak_segment < segment)
        curr_seg = segment if is_ramping else pid.current_soak_segment
        label =""
        total_passed_segment_time=0.0
        duration = "0:00"
        current_segment_time = 0.0
        total_current_segment_time = 0.0
        pid_input = bt if pid.pidSource == 1 else et
        total_ramp_current_segment = pid.svRamps[curr_seg-1] if curr_seg > 0 else 0.0
        total_soak_current_segment = pid.svSoaks[curr_seg-1] if curr_seg > 0 else 0.0
        if is_ramping:
            ramp_color = colors['highlighted']
            soak_color = "inherit"
        else:
            ramp_color = "inherit"
            soak_color = colors['highlighted']
        # RS time origin: after CHARGE (if RStimeAfterCHARGE and recording) else after PID ON
        try:
            if pid.RStimeAfterCHARGE and qmc.flagstart and qmc.timeindex[0] > -1:
                rs_t0 = qmc.timex[qmc.timeindex[0]]
            else:
                rs_t0 = pid.time_pidON
            rs_elapsed = tx - rs_t0  # time elapsed since RS started
            if is_ramping:
                # time accumulated by all complete ramp+soak pairs before current segment
                segment_start_time = sum(pid.svRamps[:curr_seg-1]) + sum(pid.svSoaks[:curr_seg-1])
                elapsed_in_seg = rs_elapsed - segment_start_time
                total_current_segment_time = float(pid.svRamps[curr_seg-1]) if curr_seg > 0 else 0.0
                label = L['Ramp']
            else:
                # ramps[:curr_seg] all consumed + soaks before current soak segment
                segment_start_time = sum(pid.svRamps[:curr_seg]) + sum(pid.svSoaks[:curr_seg-1])
                elapsed_in_seg = rs_elapsed - segment_start_time
                total_current_segment_time = float(pid.svSoaks[curr_seg-1]) if curr_seg > 0 else 0.0
                label = L['Soak']
            elapsed_in_seg = max(0.0, elapsed_in_seg)
            duration = stringfromseconds(elapsed_in_seg)
            total_passed_segment_time = segment_start_time + elapsed_in_seg
        except (IndexError, TypeError):
            _log.error("Error while accessing PID Ramp/Soak segment data, likely due to missing or incomplete data from PID controller. Falling back to default values.")
        sv = pid.svValues[curr_seg-1]
        # now compute the color for pid_input versus sv
        color_diff = abs(pid_input - sv)
        if color_diff < 5:
            mode_color = colors['close']
        elif color_diff < 15:
            mode_color = colors['middle']
        else:                
            mode_color = colors['value']

        html += f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['PID']}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">Segment {curr_seg} / {rslen} - {stringfromseconds(total_passed_segment_time)} / {stringfromseconds(pid.RS_total_time)}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['Segments']} Ramp/Soak</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;"><span style="{ramp_color}">{stringfromseconds(total_ramp_current_segment)}</span> / <span style="{soak_color}">{stringfromseconds(total_soak_current_segment)}</span></td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{label}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{duration} / {stringfromseconds(total_current_segment_time)}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['Delta']} {L['Temp']}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;"><span style="color: {mode_color}">{pid_input:.1f}</span>/{sv:.0f}°{mode}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{l1}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{t1:.1f}°{mode}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{l2}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{t2:.1f}°{mode}</td>
                </tr>
                </table>
                """

        return html

    # Manual case
    sv = round(getattr(pid, 'svValue', 0.0), 1)
    html += f"""
            <tr>
                <td style="color: {colors['label']}; font-size: 11px;">{l1}</td>
                <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{t1:.1f}°{mode}</td>
            </tr>
            <tr>
                <td style="color: {colors['label']}; font-size: 11px;">{l2}</td>
                <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{t2:.1f}°{mode}</td>
            </tr>
            <tr>
                <td style="color: {colors['label']}; font-size: 11px;">{L['SV']}</td>
                <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{sv:.0f}°{mode}</td>
            </tr>
            <tr>
                <td style="color: {colors['label']}; font-size: 11px;">Delta {L['SV']}-{L['BT']}</td>
                <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{sv-bt:.0f}°{mode}</td>
            </tr>
            </table>
            """
    return html

def _get_omniflux_live(qmc: Any, omniflux)-> tuple[float, float]:
        # read registers from modbus if connected
        
        ci = omniflux.color_device_idx
        ri = omniflux.roc_device_idx
        try:
            color_series = qmc.extratemp1[ci]
            agtron = color_series[-1] if color_series else -1.0
        except (IndexError, TypeError):
            agtron = -1.0
        try:
            roc_series = qmc.extratemp2[ri]
            roc = roc_series[-1] if roc_series else -1.0
        except (IndexError, TypeError):
            roc = -1.0
        return agtron, roc

def _dev_ratio_color_static(dev_pct: float, gap: float, mode: str, colors: dict) -> str:
    """Colorie DEV Ratio en FC : alerte uniquement si ratio bas ET drop proche.
    gap = drop_temp - bt (positif = encore de la marge, négatif = dépassé)
    Seuils en °C, convertis en °F si nécessaire."""
    warn_gap  = 15.0 if mode == 'C' else 27.0   # zone d'approche yellow
    alert_gap = 10.0 if mode == 'C' else 18.0   # zone d'approche red
    if dev_pct < 10.0 and gap < alert_gap:
        return colors['manual']
    if dev_pct < 13.0 and gap < warn_gap:
        return colors['highlighted']
    return colors['value']

def _coach_agtron(qmc: Any):
    """Live Agtron from the Omniflux if present, else None. ## TILAU ##"""
    try:
        dev = qmc.aw.bleAirwaveDevice
        omniflux = dev.omniflux if dev is not None and hasattr(dev, 'omniflux') else None
        if omniflux is not None and omniflux.color_device_idx != -1:
            ag, _ = _get_omniflux_live(qmc, omniflux)
            return ag if ag != -1 else None
    except Exception: # pylint: disable=broad-except
        # The colour device is optional and its reader is third-party: a card
        # must not be lost to it, but a reader that never answers must not be
        # silent either — the card would simply show no colour, forever.
        report_once('annotation_text: live colour reading')
        return None
    return None

def _coach_html(qmc: Any, idx, info, x_intersect, bt, et, mode, L, colors,
                phase_title, header_color) -> str:
    """Guided simplified 'coach' card: header + one hero line + one colour-coded
    verdict + one compact metric line. All strings come from the cached
    _tilau_labels — no translator call here. ## TILAU ##

    Verdicts are derived from the same signals the expert view already
    colour-codes (milestone proximity, FC acoustic burst, DEV ratio, drop
    proximity, cooling temp) — no new unvalidated thresholds.
    """
    GREEN  = '#A6E3A1'
    YELLOW = colors['highlighted']
    RED    = colors['manual']
    LABEL  = colors['label']

    # current BT RoR (°/min), guarded
    try:
        ror = qmc.delta2[-1] if qmc.delta2 and len(qmc.delta2) > 0 and qmc.delta2[-1] is not None else None
    except (AttributeError, IndexError, TypeError):
        ror = None
    ror_str = f" · RoR {ror:+.0f}" if ror is not None else ""

    toward = ""
    hero = ""
    hero_color = colors['value']
    verdict = ""
    verdict_color = GREEN
    compact = ""

    if idx == "CHARGE":
        toward = L['coach_toward_dry']
        inter = info["rel_tx"] - (x_intersect - info["charge"])
        inter_time = stringfromseconds(-inter) if inter < 0 else "--:--"
        if inter < 0 and -inter < 45.0:
            hero_color = RED
        elif inter < 0 and -inter < 90.0:
            hero_color = YELLOW
        hero = f"{L['coach_dry_in']} {inter_time}"
        _dry_approaching = inter < 0 and -inter < 90.0
        if _dry_approaching:
            verdict, verdict_color = L['coach_approaching_dry'], YELLOW
        else:
            verdict, verdict_color = L['coach_on_track'], GREEN
        compact = f"{L['BT']} {bt:.0f}°→{info['target']:.0f}°{mode}{ror_str}"
        ## TILAU ## publish coach proximity so the assistant panel's DRY END
        ## button lights up together with this "approaching" alert (same
        ## predicted-time signal, not a divergent temperature-gap threshold)
        qmc._tilau_coach_pub = {"toward": "DE",
                                 "eta_sec": (-inter if inter < 0 else -1.0),
                                 "approaching": bool(_dry_approaching)}

    elif idx == "DE":
        toward = L['coach_toward_fc']
        pred = info.get("pred_sec", 0.0)
        hero = f"{L['coach_fc_in']} {stringfromseconds(pred) if pred and pred > 0 else '--:--'}"
        # Hero colour tracks predicted time-to-1C, like the drying phase does.
        if pred and pred > 0:
            if pred < 45.0:
                hero_color = RED
            elif pred < 90.0:
                hero_color = YELLOW
        # Verdict priority: acoustic burst (strongest) → cracks heard →
        # time-to-1C proximity (works without a mic) → steady browning.
        fc_signal = False
        if qmc.fc_detector._cached_crack_device_idx != -1:
            cnt = qmc.fc_detector.last_count
            thr = qmc.fc_detector.threshold
            if thr > 0 and cnt >= thr:
                verdict, verdict_color, hero_color = L['coach_fc_imminent'], RED, RED
                fc_signal = True
            elif cnt > 0:
                verdict, verdict_color = L['coach_cracks_heard'], YELLOW
                fc_signal = True
        _fc_approaching = fc_signal
        if not fc_signal:
            if pred and 0 < pred < 90.0:
                verdict, verdict_color = L['coach_fc_approaching'], YELLOW
                _fc_approaching = True
            else:
                verdict, verdict_color = L['coach_browning_ok'], GREEN
        compact = f"{L['BT']} {bt:.0f}°{mode}{ror_str}"
        ## TILAU ## publish coach proximity so the assistant panel's FC
        ## button lights up together with this "1C approaching/imminent"
        ## alert (same predictive signal, incl. acoustic crack burst)
        qmc._tilau_coach_pub = {"toward": "FC",
                                 "eta_sec": (pred if pred and pred > 0 else -1.0),
                                 "approaching": bool(_fc_approaching)}
        ag = _coach_agtron(qmc)
        if ag is not None:
            compact += f" · {ag:.0f}Ag"

    elif idx in ("FC", "SCs", "SCe"):
        toward = L['coach_toward_drop']
        dev_pct = info.get("dev_pct", 0.0)
        DEV_TARGET = 20.0
        hero = f"{L['coach_dev_short']} {dev_pct:.0f}% · {L['Target']} {DEV_TARGET:.0f}%"
        drop_temp = info.get("drop_temp", 0.0)
        gap = drop_temp - bt
        warn_gap = 15.0 if mode == "C" else 27.0
        # Drive the verdict from the DEVELOPMENT RATIO, not temperature: on
        # this roaster BT can sit near the configured drop temp very early,
        # so a temperature-first rule wrongly says "drop" at 5% dev.
        if dev_pct >= DEV_TARGET - 2.0:
            # development target reached → time to drop
            verdict, verdict_color, hero_color = L['coach_ready_drop'], RED, GREEN
        elif dev_pct < 13.0 and drop_temp > 0.0 and gap < warn_gap:
            # hot enough to drop but not developed yet → hold / ease the heat
            verdict, verdict_color, hero_color = L['coach_underdeveloped'], YELLOW, YELLOW
        else:
            verdict, verdict_color = L['coach_dev_ok'], GREEN
        delta_t = bt - info.get('fctemp', bt)
        compact = f"{L['coach_dev_short']} {stringfromseconds(info.get('dev_time', 0.0))} · Δ-T {delta_t:+.0f}°{mode}"

    elif idx == "DROP":
        hero = L['coach_cool_fast']
        hot_limit  = 200.0 if mode == "C" else 392.0
        warm_limit =  50.0 if mode == "C" else 122.0
        hero_color = RED if bt > hot_limit else (YELLOW if bt > warm_limit else GREEN)
        compact = f"{L['BT']} {bt:.0f}°{mode} · {L['ET']} {et:.0f}°{mode}"

    else:
        hero = f"{L['BT']} {bt:.0f}°{mode}"

    toward_html = (f'<span style="color:#6C7086; font-size:10px;"> · {toward}</span>'
                   if toward else "")
    verdict_html = (f'<div style="font-size:12px; color:{verdict_color}; margin-bottom:5px;">{verdict}</div>'
                    if verdict else "")
    compact_html = (f'<div style="font-size:11px; color:{LABEL};">{compact}</div>'
                    if compact else "")
    return f"""
            <div style="min-width: 130px; border: 1px solid #45475A; border-radius: 8px; padding: 9px;">
                <div style="border-bottom: 1px solid {header_color}; margin-bottom: 6px; padding-bottom: 2px;">
                    <span style="color: {header_color}; font-weight: bold; font-size: 13px; letter-spacing: 1px;">{phase_title}</span>{toward_html}
                </div>
                <div style="font-size: 15px; font-weight: bold; color: {hero_color}; margin-bottom: 4px;">{hero}</div>
                {verdict_html}
                {compact_html}
            </div>
            """

def _format_annotation_text(qmc: Any, x_intersect, info, coach: bool = False)->str:
    # Pre-fetch common variables to avoid repeated dict hashing
    L = _labels() # Use cached translations

    colors = _ANNO_COLORS

    # charge = charge time in second since start of preheat
    # rel_tx = elapsed time since charge in seconds
    # bt = current bean temperature 
    # et = environmental extract temperature
    # target = target temperature from phase (target - bt is DeltaT)
    # pred_sec = predictive First Crack in seconds
    # fctemp = bean temperature recorded at FIRST CRACK
    # fc_time = elapsed time since charge in seconds at FIRST CRACK
    # dev_time = elapsted time in second since FIRST CRACK has been marked
    # dev_pct = % of development x 100
    # de_time = elapsed seconds since charger at DRY END
    # dry pct = % of dry end x 100
    # mai_pct = % of maillard x 100
    # sc_dur = elapsed seconds between SECOND CRACK START AND END
    # scs_temp = bean temperature at SECOND CRACK START
    # sce_temp = bean temperature at SECOND CRACK END

    # get_agtron_color / get_roc_color imported from tilauscope_types at module level

    idx = info["index"]
    mode = qmc.mode
    bt = float(info["bt"])
    et = float(info["et"])

    # Phase title and header colour — map built once in _init_Tilau_translations
    phase_title, header_color = _phase_map().get(idx, (L['BT'], '#9E9E9E'))

    # The simplified guided view. Which view is chosen is the caller's business
    # — it owns the toggle and the operator level that gates it — so it arrives
    # as an argument rather than being fished off the host. Default is the full
    # table: unknown must never render a half-decided screen.
    if coach:
        return _coach_html(qmc, idx, info, x_intersect, bt, et, mode,
                                L, colors, phase_title, header_color)

    # Cache the formatted relative time
    rel_time = stringfromseconds(info["rel_tx"])

    html = f"""
            <div style="min-width: 140px; border: 1px solid #45475A; border-radius: 8px; padding: 10px;">
                <div style="border-bottom: 1px solid {header_color}; margin-bottom: 6px; padding-bottom: 2px;">
                    <span style="color: {header_color}; font-weight: bold; font-size: 14px; letter-spacing: 1px;">
                        {phase_title}
                    </span>
                </div>   
                <table border="0" cellspacing="0" cellpadding="2" style="width: 100%;">
            """

    if idx == "CHARGE" or idx == "DE":
        label = L['DRY'] if idx == "CHARGE" else L['FC']
        # difference between current prediction and real time mark in seconds
        inter = info["rel_tx"] - (x_intersect - info["charge"])
        # create a time stamp out of time difference if we're not yet reached the target (x_intersect)
        inter_time = stringfromseconds(-inter) if inter < 0 else "--:--" 
        # if close at 5% use a red color, if at 10% use yellow, else white or so
        if inter < 0 and -inter < 45.0: # assume that at 45s from milestone we are in red
            inter_color = colors['manual']
        elif inter < 0 and -inter < 90: # assume that at 1:30 from milestone we might have to take care of settings
            inter_color = colors['highlighted']
        else:
            inter_color = colors['value']
        # if close at 5% use a red color, if at 10% use yellow, else white or so
        inter_bt = bt-info['target']
        if inter_bt < 0 and within_share(inter_bt, info["target"], 0.05, mode):
            inter_bt_color = colors['manual']
        elif inter_bt < 0 and within_share(inter_bt, info["target"], 0.10, mode):
            inter_bt_color = colors['highlighted']
        else:
            inter_bt_color = colors['value']
        
        bt_row = "" if idx == "CHARGE" else f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['BT']}</td>
                    <td align="right" style="color: {inter_bt_color}; font-weight: bold; font-size: 12px;">{bt:.1f}°{mode}</td>
                </tr>
                """
        html += f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['Time']}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{rel_time}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">Expected {L['DRY'] if idx=="CHARGE" else L['FC']} in</td>
                    <td align="right" style="color: {inter_color}; font-weight: bold; font-size: 12px;">{inter_time}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['Target']} {L['DRY'] if idx=="CHARGE" else L['FC']}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{info['target']:.1f}°{mode}</td>
                </tr>
                {bt_row}
                """
        omniflux = qmc.aw.bleAirwaveDevice.omniflux if qmc.aw.bleAirwaveDevice is not None and hasattr(qmc.aw.bleAirwaveDevice, 'omniflux') else None
        if omniflux is not None and omniflux.color_device_idx != -1:
            agtron, roc = _get_omniflux_live(qmc, omniflux)
            if agtron != -1:
                ag_color  = get_agtron_color(agtron)
                roc_color = _omniflux_roc_color(roc)
                html += f"""
                        <tr>
                            <td style="color: {colors['label']}; font-size: 11px;">{L['Color']}</td>
                            <td align="right" style="color: {ag_color}; font-weight: bold; font-size: 12px;">{agtron:.1f}Ag</td>
                        </tr>
                        <tr>
                            <td style="color: {colors['label']}; font-size: 11px;">RoC</td>
                            <td align="right" style="color: {roc_color}; font-weight: bold; font-size: 12px;">{roc:.1f}</td>
                        </tr>
                        """
        if qmc.fc_detector._cached_crack_device_idx != -1 and idx=="DE": # only after dry end
                fc_cnt = qmc.fc_detector.last_count
                fc_burst = qmc.fc_detector.threshold
                if fc_cnt <= 0:
                    fc_color = colors['value']
                elif fc_cnt < fc_burst:
                    fc_color = colors['highlighted']  # cracks entendus, pas encore le seuil de déclenchement
                else:
                    fc_color = colors['manual']        # seuil burst atteint → auto-FC imminent

                html += f"""
                        <tr>
                            <td style="color: {colors['label']}; font-size: 11px;">{L['FCcounter']}</td>
                            <td align="right" style="color: {fc_color}; font-weight: bold; font-size: 12px;">{fc_cnt if fc_cnt != -1 else ''}</td>
                        </tr>
                        """

        html += "</table>"
        return html
    
    if idx == "FC" or idx == "SCs" or idx == "SCe":
        # BT turns red when within bt_delta_limit of the drop target (approaching, not overshoot)
        # A DIFFERENCE from the drop target: it scales (×1.8). 32 is the
        # freezing offset and has no business in a gap.
        bt_delta_limit:float = 5.0 * delta_scale(qmc.mode)
        delta_color:str = colors['manual'] if info["drop_temp"] > 0.0 and (info["drop_temp"] - bt) < bt_delta_limit else colors['value']
        html += f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">DEV Time</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{stringfromseconds(info['dev_time'])}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['Delta']}-T °{mode}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;"> {bt - info['fctemp']:.1f}°{mode}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['BT']}</td>
                    <td align="right" style="color: {delta_color}; font-weight: bold; font-size: 12px;">{bt:.1f}°{mode}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">DEV Ratio</td>
                    <td align="right" style="color: {_dev_ratio_color_static(info['dev_pct'], info['drop_temp'] - bt, qmc.mode, colors)}; font-weight: bold; font-size: 12px;">{info["dev_pct"]:.1f}%</td>
                </tr>
                """
        if idx == "SCs":
            html +=  f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['SCS']}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{info["scs_temp"]:.1f}°{mode}</td>
                </tr>
            """
        if idx == "SCe":
            html +=  f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['SCE']}</td>
                    <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{info["sce_temp"]:.1f}°{mode}</td>
                </tr>
            """
        omniflux = qmc.aw.bleAirwaveDevice.omniflux if qmc.aw.bleAirwaveDevice is not None and hasattr(qmc.aw.bleAirwaveDevice, 'omniflux') else None
        if omniflux is not None and omniflux.color_device_idx != -1:
            agtron, roc = _get_omniflux_live(qmc, omniflux)
            if agtron != -1:
                ag_color  = get_agtron_color(agtron)
                roc_color = _omniflux_roc_color(roc)
                html += f"""
                        <tr>
                            <td style="color: {colors['label']}; font-size: 11px;">{L['Color']}</td>
                            <td align="right" style="color: {ag_color}; font-weight: bold; font-size: 12px;">{agtron:.1f}Ag</td>
                        </tr>
                        <tr>
                            <td style="color: {colors['label']}; font-size: 11px;">RoC</td>
                            <td align="right" style="color: {roc_color}; font-weight: bold; font-size: 12px;">{roc:.1f}</td>
                        </tr>
                        """
        html +="</table>"
        return html
    
    if idx == "DROP":
        hot_limit  = 200.0 if mode == "C" else 392.0  # encore très chaud — rouge
        warm_limit =  50.0 if mode == "C" else 122.0  # refroidissement insuffisant — jaune
        def _cool_color(t: float) -> str:
            return colors['manual'] if t > hot_limit else (colors['highlighted'] if t > warm_limit else colors['value'])
        bt_color = _cool_color(bt)
        et_color = _cool_color(et)

        html += f"""
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['BT']}</td>
                    <td align="right" style="color: {bt_color}; font-weight: bold; font-size: 12px;">{bt:.1f}°{mode}</td>
                </tr>
                <tr>
                    <td style="color: {colors['label']}; font-size: 11px;">{L['ET']}</td>
                    <td align="right" style="color: {et_color}; font-weight: bold; font-size: 12px;">{et:.1f}°{mode}</td>
                </tr>
                </table>
                """
        return html
    else:
        html += f"""
                    <tr>
                        <td style="color: {colors['label']}; font-size: 11px;">{L['BT']}</td>
                        <td align="right" style="color: {colors['value']}; font-weight: bold; font-size: 12px;">{bt:.1f}°{mode}</td>
                    </tr>
                    </table>
                    """
    return html

def _get_phase_and_target(qmc: Any):
    """Calcule la phase et la cible avec initialisation sécurisée des clés."""
    if not qmc.timeindex or not qmc.timex:
        return 0.0, {"index": "init", "target": 0.0, "charge": 0.0, "rel_tx": 0.0, "bt": 0.0}

    t_idx = qmc.timeindex
    t_x = qmc.timex
    temp2 = qmc.temp2
    temp1 = qmc.temp1
    charge = t_x[t_idx[0]]
    rel_tx = t_x[-1] - charge
    # temp1/temp2 can hold None for curve gaps — keep them numeric downstream.
    bt_last = temp2[-1] if len(temp2) > 0 and temp2[-1] is not None else 0.0
    et_last = temp1[-1] if len(temp1) > 0 and temp1[-1] is not None else 0.0
    
    # charge = charge time in second since start of preheat
    # rel_tx = elapsed time since charge in seconds
    # bt = current bean temperature 
    # et = environmental extract tempperature
    # target = target temperature from phase (target - bt is DeltaT)
    # pred_sec = predictive First Crack in seconds
    # fctemp = bean temperature recorded at FIRST CRACK
    # fc_time = elapsed time since charge in seconds at FIRST CRACK
    # dev_time = elapsted time in second since FIRST CRACK has been marked
    # dev_pct = % of development x 100
    # de_time = elapsed seconds since charger at DRY END
    # dry pct = % of dry end x 100
    # mai_pct = % of maillard x 100
    # sc_dur = elapsed seconds between SECOND CRACK START AND END
    # scs_temp = bean temperature at SECOND CRACK START
    # sce_temp = bean temperature at SECOND CRACK END
    # drop_temp = drop temperature set in phases
    res = {
        "index": "unknown", "charge": charge, "rel_tx": rel_tx, "bt": bt_last, "et": et_last,
        "target": 0.0, "pred_sec": 0.0, "fctemp": 0.0, "fc_time": 0.0,
        "dev_time": 0.0, "dev_pct": 0.0, "de_time": 0.0, "dry_pct": 0.0, 
        "mai_pct": 0.0, "sc_dur": 0.0, "scs_temp": 0.0, "sce_temp": 0.0, 
        "drop_temp": 0.0
    }

    if t_idx[6] > 0: # DROP
        res.update({"index": "DROP", "drop": t_x[t_idx[6]], "drop_temp": temp2[t_idx[6]]})
        target = res["drop_temp"]
    
    elif t_idx[2] > 0: # Après FCs
        fctemp:float = temp2[t_idx[2]]
        de_time:float = t_x[t_idx[1]] - charge 
        fc_time:float = t_x[t_idx[2]] - charge
        dev_time:float = rel_tx - fc_time
        #_log.error(f"phase vals fc_time={fc_time} de_time={de_time} dev_time={dev_time}")
        
        res.update({
            "fctemp": fctemp,
            "fc_time": fc_time,
            "de_time": de_time,
            "dev_time": dev_time,
            "dev_pct": (dev_time * 100. / rel_tx) if rel_tx > 0 else 0,
            "dry_pct": (de_time * 100. / rel_tx) if rel_tx > 0 else 0,
            "mai_pct": ((fc_time - de_time) * 100. / rel_tx) if rel_tx > 0 else 0,
            "drop_temp" : qmc.phases[3] # drop temperature aimed
        })
        target = bt_last
        
        if t_idx[5] > 0: res.update({"index": "SCe", "sc_dur": t_x[t_idx[5]] - t_x[t_idx[4]], "sce_temp": temp2[t_idx[5]]})
        elif t_idx[4] > 0: res.update({"index": "SCs", "scs_temp": temp2[t_idx[4]]})
        else: res["index"] = "FC"

    elif t_idx[1] > 0: # de DE à FCs
        res["index"] = "DE"
        p = qmc.EvalPredictiveValues()
        res["pred_sec"] = p.get("pFCs", 0.0)
        target = qmc.phases[2] if qmc.phases[2] > 0 else (qmc.phases_celsius_defaults[2] if qmc.mode == "C" else qmc.phases_fahrenheit_defaults[2]) # Fix 2026/03/07
        #_logd.info(f"estimating predictive temp of FCs = {target} versus {qmc.phases[2]}")
    else: # de CHARGE à DE
        res["index"] = "CHARGE"
        p = qmc.EvalPredictiveValues()
        res["pred_sec"] = p.get("pDRY", 0.0)
        target = qmc.phases[1] if qmc.phases[1] > 0 else (qmc.phases_celsius_defaults[1] if qmc.mode == "C" else qmc.phases_fahrenheit_defaults[1]) # Fix 2026/03/07
        #_logd.info(f"estimating predictive temp of DE = {target} versus {qmc.phases[1]}")

    res["target"] = target
    return target, res


# ── the names the rest of the code uses ─────────────────────────────────────
# The private names above are the ported originals, kept identical so the move
# stays reviewable against the source. These are the public surface.

phase_and_target = _get_phase_and_target
roast_card = _format_annotation_text
preheat_card = _get_tilaupid_text
pid_card = _get_pid_text
