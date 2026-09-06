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
import re # For sorting alog files
from datetime import datetime

#import matplotlib.pyplot as plt



from artisanlib.atypes import ProfileData, ComputedProfileInformation

from PyQt6.QtCore import (pyqtSlot, QT_TRANSLATE_NOOP) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtWidgets import (QApplication, QMessageBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import (AGTRON_SCALES, THEME, RoastingPhase, normalize_timeindex, ROASTING_BASIC_BASE, weight_loss_target,
                                         get_ror_ideal_band, estimate_ror_dt, find_turning_point_index, dominant_dev_ror_event,
                                         roast_level_from_arrival_detail, ARRIVAL_UNCERTAINTY_DEFAULT_C,
                                         resolve_color_system)
from tilauscope.brew_advisor import BrewInput, WaterProfile
from tilauscope.brew_advisor_dialog import BrewAdvisorDlg
from tilauscope.cave.common import (
    _logd)


# What the coach's inputs are actually worth. Nothing in a home roast is
# measured finely enough to judge a batch on a tenth of a point, so every
# band comparison below is widened by the uncertainty of its own measurement
# rather than compared to a bare edge.
_MILESTONE_MARK_TOLERANCE_S: float = 5.0   # when first crack was called, by ear
_WEIGHT_READING_TOLERANCE_G: float = 1.0   # what a batch weight on file is worth


def _safe_moisture(value) -> float:
    """Green moisture as a float; 0.0 when absent or unreadable (= not measured)."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


class AnalysisMixin:
    """Reading a single roast: colour level, phase rules, and the written report.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """





    # ── Roast-level awareness (single source of truth for the coach) ──────────
    # Coffee science, not roaster-specific: a lighter target drops cooler, loses
    # less weight and runs a shorter absolute development than a darker target,
    # whatever the machine. Every quantitative coach check routes through here so
    # a deliberately light roast is never judged against a different level's
    # assumptions. The category and its dtr/drop/dev_time fundamentals come from
    # tilauscope_types.ROASTING_BASIC_BASE — the same table the roast plan
    # generator (roast_plan_model.py) builds its plan from — so the coach never
    # disagrees with the plan on what a given roast level requires.
    #
    # The level is read from what the roast DID — its arrival pair, development
    # duration and drop temperature — never from the bean's colour. The colour is
    # the result: it is expected to agree with the roast, and when it does not it
    # is the roast that went wrong, so it cannot be the reference the roast is
    # then judged against.
    def _roast_machine_ctx(self, data):
        """The roaster record of the machine that ran this roast, or None."""
        try:
            mgr = getattr(self, 'roaster_manager', None)
            if mgr is None:
                return None
            return mgr.get_roast_context(str(data.get('roastertype', '') or ''))
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.debug(f"coach: roaster context unavailable: {e}")
            return None

    def roast_drop_offset_c(self, data) -> float:
        """The bean probe's deviation at drop for the machine that ran this roast.

        Same value and same sign the plan generator applies to the reference drop
        window, so a level read here and a level prescribed there mean the same
        temperature on the operator's own display.
        """
        ctx = self._roast_machine_ctx(data)
        offsets = getattr(ctx, 'bt_offsets', None) if ctx is not None else None
        if offsets and len(offsets) >= 4:
            try:
                return float(offsets[3])
            except (TypeError, ValueError):
                pass
        return 0.0

    def roast_arrival_uncertainty_c(self, data) -> float:
        """What a level read from this machine's arrival is worth, in °C."""
        ctx = self._roast_machine_ctx(data)
        try:
            return float(getattr(ctx, 'arrival_uncertainty_c', None)
                         or ARRIVAL_UNCERTAINTY_DEFAULT_C)
        except (TypeError, ValueError):
            return ARRIVAL_UNCERTAINTY_DEFAULT_C

    def roast_level_measured(self, data, computed, mode: str = 'C'):
        """(level, neighbour) for this roast, from its arrival pair.

        `neighbour` is the level the arrival could just as well be read as when
        it lands on a band edge — None when the reading is clear-cut.
        """
        try:
            drop_bt = float(computed.get('DROP_BT') or 0.0)
            fcs_t   = float(computed.get('FCs_time') or 0.0)
            drop_t  = float(computed.get('DROP_time') or 0.0)
        except (TypeError, ValueError):
            return None, None
        if drop_bt <= 0 or fcs_t <= 0 or drop_t <= fcs_t:
            return None, None
        # The reference table is in °C — convert at the boundary, once.
        drop_c = (drop_bt - 32.0) * 5.0 / 9.0 if mode == 'F' else drop_bt
        return roast_level_from_arrival_detail(drop_c, (drop_t - fcs_t) / 60.0,
                                               self.roast_drop_offset_c(data),
                                               self.roast_arrival_uncertainty_c(data))

    def roast_level_thresholds(self, level, *,
                               moisture_pct: float = 0.0,
                               dev_time_min: float = 0.0,
                               drop_offset_c: float = 0.0):
        """Return (level, thresholds) for a measured roast level.

        thresholds carries: dtr (min,max %), wl (min,max %), wl_target (%),
        drop_c (low,high bean-temp window in °C) and dev_time (low,high absolute
        minutes FCs→DROP). dtr/drop_c/dev_time come from ROASTING_BASIC_BASE
        (shared with the plan generator); wl comes from `weight_loss_target()`,
        which needs the lot's water and the development on top of the level —
        pass both when the roast has them, or the target falls back to a neutral
        moisture and drops the development term. When the level cannot be read we
        fall back to the Medium profile but keep level None so callers stay
        cautious.
        """
        plan = next((p for p in ROASTING_BASIC_BASE.plans if p.name == level), None)
        if plan is None:
            plan = next(p for p in ROASTING_BASIC_BASE.plans if p.name == "Medium")
        wl = weight_loss_target(plan.name, moisture_pct=moisture_pct,
                                dev_time_min=dev_time_min)
        thresholds = {
            'dtr': (plan.dtr_pct[0] * 100.0, plan.dtr_pct[1] * 100.0),
            'wl': (wl.low, wl.high),
            'wl_target': wl.target,
            # Shifted onto the machine's own display, like the plan generator
            # does, so the window can be compared with the recorded drop.
            'drop_c': (float(plan.drop_temp[0]) + drop_offset_c,
                       float(plan.drop_temp[1]) + drop_offset_c),
            'dev_time': plan.development_time,
        }
        return level, thresholds

    def phase_rules_for_level(self, level):
        """Phase-duration ranges for the roast's level, falling back per-phase to
        the pooled rules when the level has too few samples to be reliable."""
        pooled = getattr(self, 'duration_rules', {}) or {}
        by_band = getattr(self, 'duration_rules_by_band', {}) or {}
        band = by_band.get(level, {}) if level else {}
        out = {}
        for k in ('drying', 'maillard', 'development'):
            if k in band:
                out[k] = band[k]
            elif k in pooled:
                out[k] = pooled[k]
        return out



    def _get_uuid_from_bean_description(self, bean_field:str)-> str:
        uuid_match = self.uuid_pattern.search(bean_field)
        if uuid_match:
            target_uuid = uuid_match.group(1)
            # Look up the bean in the cave using the existing helper method
            return self.uuidmap.get(target_uuid,"") if uuid_match else ""
        else:
            return "" # no uuid

    @pyqtSlot()
    def show_barista_expert_view(self, profiledata=None):
        # Works on the passed profile (timeline hand-off) or the currently loaded
        # roast (the toolbar button). Both carry the same enriched shape (incl.
        # the "computed" block) so the advice is identical either way.
        data = profiledata if profiledata is not None else getattr(self, 'lastprofiledata', None)
        if not data:
            self._show_message(self, QApplication.translate("tilauscope_beancave", "No Data"),
                               QApplication.translate("tilauscope_beancave", "Please select a roast file first."),
                               QMessageBox.Icon.Warning)
            return

        # ProfileData is a TypedDict the runtime does not enforce; an .alog from an
        # older version, a repair, or another tool can carry a number as text and
        # abort the engine with a TypeError. Coerce once here rather than downstream.
        def _num(v, default: float = 0.0) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        def _storage_thresholds():
            """The operator's own aw window, or the shipped defaults."""
            try:
                from tilauscope.beancave_storage_tab import load_thresholds  # noqa: PLC0415
                return load_thresholds()
            except Exception as exc:  # noqa: BLE001
                _logd.warning("Brew: storage thresholds unavailable (%s); using defaults", exc)
                from tilauscope.storage_advisor import DEFAULT_THRESHOLDS  # noqa: PLC0415
                return DEFAULT_THRESHOLDS

        ground = _num(data.get("ground_color", 0.0))
        whole = _num(data.get("whole_color", 0.0))
        # A profile saved before the scale was filed with the reading carries an
        # empty color_system; a reading without a scale is Agtron, not a missing
        # measurement. Only the absence of a reading blocks the advice.
        color_system: str = resolve_color_system(
            str(data.get("color_system", "") or ""), ground, whole)

        if ground == 0.0 and whole == 0.0:
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Missing color data"),
                               QApplication.translate("tilauscope_beancave", "Please enter color information in the roast property first."),
                               QMessageBox.Icon.Warning)
            return

        # Resolve the linked green bean (expert advice requires bean context)
        bean_field = str(data.get('beans', "") or "")
        uuid_match = re.compile(r'uuid: \s*([a-fA-F0-9-]{36})').search(bean_field)
        matched_bean = self.uuidmap.get(uuid_match.group(1)) if uuid_match else None
        if not matched_bean:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Association Error"),
                QApplication.translate("tilauscope_beancave",
                    "This roast is not associated with a green bean in your Beancave. "
                    "Please link it using the 'Set UUID' tool to see expert recommendations."),
                QMessageBox.Icon.Critical)
            return

        # Phase context — development ratio drives extraction guidance
        computed = data.get("computed", {})
        dry = _num(computed.get("dryphasetime", 0))
        mid = _num(computed.get("midphasetime", 0))
        dev = _num(computed.get("finishphasetime", 0))
        total_phase = dry + mid + dev
        dev_ratio = (dev / total_phase) if total_phase > 0 else 0.0

        # Days off roast (degassing) from the ISO roast date
        days_off = -1
        iso = str(data.get("roastisodate", "") or "")
        if iso:
            try:
                rd = datetime.fromisoformat(iso[:10]).date()
                days_off = max(0, (datetime.now().date() - rd).days)
            except Exception:
                days_off = -1

        inp = BrewInput(
            ground_color=ground, whole_color=whole, color_system=color_system,
            weight_loss=_num(computed.get("weight_loss", 0.0)),
            density=_num(getattr(matched_bean, "density", 0.0)),
            water_activity=_num(getattr(matched_bean, "water_activity", 0.0)),
            green_moisture=_num(getattr(matched_bean, "last_humidity", 0.0)),
            dev_ratio=dev_ratio, dev_time_s=int(dev),
            process=str(getattr(matched_bean, "process", "") or ""),
            country=str(getattr(matched_bean, "country", "") or ""),
            altitude=int(_num(getattr(matched_bean, "altitude", 0))),
            variety=str(getattr(matched_bean, "varieties", "") or ""),
            species=str(getattr(matched_bean, "species", "") or ""),
            days_off_roast=days_off,
            water_profile=WaterProfile.AUTO,
            # The Storage tab owns the aw doctrine, thresholds
            # included: the brew advice follows the operator's own window
            # instead of a second hardcoded opinion.
            aw_thresholds=_storage_thresholds(),
        )
        title = str(data.get("title", "") or "") or getattr(matched_bean, "name", "")
        dlg = BrewAdvisorDlg(inp, title=title, aw=self.aw, beancave=self,
                             bean=matched_bean)
        dlg.exec()

    def display_roast_info(self, data: ProfileData) -> None:
        # Vue mono : on affiche la fiche HTML (et non le dot plot multi).
        self._set_stats_view(False)

        computed: ComputedProfileInformation = data.get("computed", {})

        # The four phase figures are averages — degrees gained over the phase,
        # divided by its length — not the rate of rise drawn on the curve, which
        # moves within every one of them. They are recomputed here from the
        # milestones rather than read from the file: the stored block anchors
        # each phase differently (the drying one starts from the green bean's own
        # temperature, not the turning point) and comes out as a plain 0 on
        # profiles whose milestones were edited after the roast. Same anchors for
        # all four, turning point to drop, so the four can be read together.
        def phase_rise(t_from: str, t_to: str) -> str:
            try:
                bt0 = float(computed.get(f'{t_from}_BT') or 0.0)
                bt1 = float(computed.get(f'{t_to}_BT') or 0.0)
                s0  = float(computed.get(f'{t_from}_time') or 0.0)
                s1  = float(computed.get(f'{t_to}_time') or 0.0)
            except (TypeError, ValueError):
                return "N/A"
            if bt0 <= 0 or bt1 <= 0 or s1 <= s0:
                return "N/A"
            return f"{(bt1 - bt0) / (s1 - s0) * 60.0:.2f}"

        # ── Extraction ────────────────────────────────────────────────────
        roasttime      = data.get("roasttime", "N/A")
        date           = data.get("roastdate", "N/A")
        roastertype    = data.get("roastertype", "N/A")
        batch_prefix   = str(data.get("roastbatchprefix", "") or "")
        batch_nr       = int(data.get("roastbatchnr", 0) or 0)
        # Colour reference: GROUND describes real development; whole-bean is only
        # the fallback for roasts measured whole. Same rule as the roast card,
        # label printer, and brew advisor.
        def _colour_num(v) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        whole_colour   = _colour_num(data.get("whole_color", 0))
        ground_colour  = _colour_num(data.get("ground_color", 0))
        roast_colour   = ground_colour or whole_colour        # ground wins, whole falls back
        roastcolor     = roast_colour if roast_colour > 0 else "N/A"
        colorsystem    = resolve_color_system(
            str(data.get("color_system", "") or ""), ground_colour, whole_colour) or "N/A"
        charge_unit    = data.get("weight", ["N/A", None, ""])[2]
        mode           = data.get("mode", "C")

        t_charge = 0
        t_dry    = computed.get("DRY_time", 0)
        t_fcs    = computed.get("FCs_time", 0)
        t_drop   = computed.get("DROP_time", 0)

        drying_auc  = computed.get("dry_phase_AUC", "N/A")
        middle_auc  = computed.get("mid_phase_AUC", "N/A")
        fcs_drop    = computed.get("finish_phase_AUC", "N/A")
        total_auc   = computed.get("AUC", "N/A")
        auc_start   = computed.get("AUCbegin")
        auc_start_str = QApplication.translate("Label", auc_start) if auc_start else ""

        drying      = t_dry - t_charge
        maillard    = t_fcs - t_dry
        development = t_drop - t_fcs
        total       = t_drop - t_charge

        if total > 0:
            drying_pct      = 100 * drying / total
            maillard_pct    = 100 * maillard / total
            development_pct = 100 * development / total
        else:
            drying_pct = maillard_pct = development_pct = 0

        weight_loss = computed.get("weight_loss", 0.0)
        defect_weight = computed.get("roast_defects_loss", 0.0)
        dtr_pct_val = development_pct

        try:
            wl_val = float(weight_loss) if weight_loss not in {0.0, "N/A"} else None
        except (ValueError, TypeError):
            wl_val = None

        _measured_level, _level_neighbour = self.roast_level_measured(data, computed, mode)
        rules = self.phase_rules_for_level(_measured_level)

        # ── Agtron label ──────────────────────────────────────────────────
        # A category name is only put on a GROUND reading: the scale behind those
        # names is a ground-bean scale, and a whole-bean number read on it lands a
        # category too dark. A whole-bean reading is shown as the number it is.
        agtron_label = ""
        if ground_colour > 0:
            for a in AGTRON_SCALES:
                try:
                    if a.agtron_range.min_value <= ground_colour <= a.agtron_range.max_value:
                        agtron_label = f"{a.name} · {a.description}"
                        break
                except (TypeError, ValueError):
                    pass
        elif whole_colour > 0:
            agtron_label = QApplication.translate(
                "tilauscope_beancave", "whole bean — not on the ground scale")
        else:
            agtron_label = QApplication.translate("tilauscope_beancave", "not present")

        # ── Colour badge + provenance line ────────────────────────────────
        # The badge carries the reference reading; the line below names which
        # measurement it came from and shows the whole/ground delta when both
        # exist (a wide delta = surface and core developed unevenly).
        _cs = str(colorsystem or "").strip()
        colour_badge_txt = f"{roast_colour:g} {_cs}".strip() if roast_colour > 0 else str(roastcolor)
        colour_detail = ""
        if ground_colour > 0 and whole_colour > 0:
            colour_detail = QApplication.translate(
                "tilauscope_beancave", "ground {0} · whole {1} · Δ {2}").format(
                    f"{ground_colour:g}", f"{whole_colour:g}",
                    f"{abs(ground_colour - whole_colour):g}")
        elif ground_colour > 0:
            colour_detail = QApplication.translate("tilauscope_beancave", "ground")
        elif whole_colour > 0:
            colour_detail = QApplication.translate("tilauscope_beancave", "whole bean")

        # ── CARD_BG : légèrement plus claire que BG pour faire ressortir ──
        # On éclaircit manuellement la couleur de surface
        CARD_BG = "#2a2a3e"   # plus clair que THEME['BG'] (#1E1E2E)

        # ── Helper: badge ─────────────────────────────────────────────────
        def badge(text, kind="neutral"):
            colors = {
                "ok":      f"background-color:#1a3a1a; color:{THEME['SUCCESS']};",
                "warn":    f"background-color:#3a2e00; color:{THEME['WARNING']};",
                "bad":     f"background-color:#3a1a1a; color:{THEME['CRITICAL']};",
                "neutral": f"background-color:{THEME['SURFACE']}; color:{THEME['SUBTEXT']};",
                "accent":  f"background-color:{THEME['ACCENT']}; color:{THEME['BG']};",
            }
            s = colors.get(kind, colors["neutral"])
            return (f'<span style="font-size:10px; font-weight:bold; padding:1px 6px; '
                    f'border-radius:4px; {s}">{text}</span>')

        def status_badge_text(val, ok_min, ok_max):
            """Retourne (texte_label, kind) selon position dans la plage."""
            if val is None:
                return "N/A", "neutral"
            try:
                v = float(val)
                if ok_min <= v <= ok_max:
                    return QApplication.translate("tilauscope_beancave", "Normal weight loss").split()[0], "ok"
                elif v < ok_min:
                    return QApplication.translate("tilauscope_beancave", "Too short"), "warn"
                else:
                    return QApplication.translate("tilauscope_beancave", "Too long"), "bad"
            except (TypeError, ValueError):
                return "N/A", "neutral"

        def dtr_badge_text(val, ok_min, ok_max):
            if val is None:
                return "N/A", "neutral"
            try:
                v = float(val)
                if ok_min <= v <= ok_max:
                    # réutilise la clé existante, on prend juste "Optimal"
                    return QApplication.translate("tilauscope_beancave", "Optimal DTR").replace(" DTR",""), "ok"
                elif v < ok_min:
                    return QApplication.translate("tilauscope_beancave", "Low DTR").replace(" DTR",""), "warn"
                else:
                    return QApplication.translate("tilauscope_beancave", "High DTR").replace(" DTR",""), "bad"
            except (TypeError, ValueError):
                return "N/A", "neutral"

        def wl_badge_text(val, ok_min, ok_max):
            if val is None:
                return "N/A", "neutral"
            try:
                v = float(val)
                if ok_min <= v <= ok_max:
                    return QApplication.translate("tilauscope_beancave", "Normal weight loss").split()[0], "ok"
                elif v < ok_min:
                    return QApplication.translate("tilauscope_beancave", "Low weight loss").split()[0], "warn"
                else:
                    return QApplication.translate("tilauscope_beancave", "High  weight loss").split()[0], "bad"
            except (TypeError, ValueError):
                return "N/A", "neutral"

        # ── Helper: section title ─────────────────────────────────────────
        def section_title(text):
            return (f'<tr><td colspan="4" style="padding:10px 0 3px 0;">'
                    f'<span style="font-size:10px; font-weight:bold; letter-spacing:1px; '
                    f'color:{THEME["SUBTEXT"]};">{text.upper()}</span>'
                    f'<hr style="border:none; border-top:1px solid {THEME["BORDER"]}; margin:2px 0 0 0;"/>'
                    f'</td></tr>')

        # ── Helper: metric card — hauteur fixe via 2 lignes explicites ────
        def metric_card(label, value, badge_label="", badge_kind="neutral"):
            b_html = badge(badge_label, badge_kind) if badge_label else "&nbsp;"
            return (
                f'<td style="padding:3px; vertical-align:top; width:25%;">'
                f'<table width="100%" cellpadding="0" cellspacing="0" style="'
                f'background-color:{CARD_BG}; border-radius:6px; '
                f'border:1px solid {THEME["BORDER"]}; border-collapse: collapse;">'
                f'<tr>'
                f'<td style="padding:7px 8px 7px 8px; border:none; vertical-align:top;">'
                # --- FIX DE HAUTEUR ICI ---
                f'<div style="min-height:68px; height:68px;">'
                f'<div style="font-size:10px; color:{THEME["SUBTEXT"]}; margin-bottom:2px;">{label}</div>'
                f'<div style="font-size:13px; font-weight:bold; line-height:1.1; margin-bottom:5px;">{value}</div>'
                f'<div>{b_html}</div>'
                f'</div>'
                # --------------------------
                f'</td>'
                f'</tr>'
                f'</table>'
                f'</td>'
            )
        # ── Helper: key-value row ─────────────────────────────────────────
        def kv_row(label, value):
            return (
                f'<tr>'
                f'<td style="font-size:11px; color:{THEME["SUBTEXT"]}; '
                f'padding:3px 8px 3px 0; white-space:nowrap;">{label}</td>'
                f'<td style="font-size:11px; font-weight:bold; '
                f'padding:3px 0; text-align:right; white-space:nowrap;">{value}</td>'
                f'</tr>'
            )

        # ── Helper: advice row ────────────────────────────────────────────
        def advice_row(icon, text, kind="ok"):
            colors = {
                "ok":   f"background-color:#1a3a1a; color:{THEME['SUCCESS']};",
                "warn": f"background-color:#3a2e00; color:{THEME['WARNING']};",
                "bad":  f"background-color:#3a1a1a; color:{THEME['CRITICAL']};",
                "info": f"background-color:#0d2a3a; color:{THEME['ACCENT']};",
            }
            c = colors.get(kind, colors["info"])
            return (
                f'<tr><td colspan="4" style="padding:2px 0;">'
                f'<table width="100%" cellpadding="7" cellspacing="0" '
                f'style="{c} border-radius:5px;">'
                f'<tr>'
                f'<td width="18" style="font-size:13px; vertical-align:top; '
                f'padding-right:6px;">{icon}</td>'
                f'<td style="font-size:11px; line-height:1.5;">{text}</td>'
                f'</tr></table></td></tr>'
            )

        # ── Phase bar ─────────────────────────────────────────────────────
        _dry_label  = QApplication.translate("tilauscope_beancave", "Drying (Charge -> Dry)").split("(")[0].strip()
        _mail_label = QApplication.translate("tilauscope_beancave", "Maillard (Dry -> FCs)").split("(")[0].strip()
        _dev_label  = QApplication.translate("tilauscope_beancave", "Development (FCs -> Drop)").split("(")[0].strip()

        if total > 0:
            dry_w  = max(2, int(drying_pct))
            mail_w = max(2, int(maillard_pct))
            dev_w  = max(2, int(development_pct))

            phase_bar_html = (
                f'<tr><td colspan="4" style="padding:4px 0 2px 0;">'
                # barre colorée
                f'<table width="100%" cellpadding="0" cellspacing="0" style="'
                f'border-radius:4px; border:1px solid {THEME["BORDER"]}; '
                f'border-collapse:collapse;">'
                f'<tr>'
                f'<td width="{dry_w}%" align="center" style="background-color:#1a3050; '
                f'color:{THEME["ACCENT"]}; font-size:10px; font-weight:bold; padding:4px 1px;">'
                f'{drying_pct:.0f}%</td>'
                f'<td width="{mail_w}%" align="center" style="background-color:#3a2800; '
                f'color:{THEME["WARNING"]}; font-size:10px; font-weight:bold; padding:4px 1px;">'
                f'{maillard_pct:.0f}%</td>'
                f'<td width="{dev_w}%" align="center" style="background-color:#1a3a1a; '
                f'color:{THEME["SUCCESS"]}; font-size:10px; font-weight:bold; padding:4px 1px;">'
                f'{development_pct:.0f}%</td>'
                f'</tr></table>'
                # légende : 3 cellules alignées à gauche, pas étalées
                f'<table cellpadding="0" cellspacing="0" style="margin-top:5px;">'
                f'<tr>'
                f'<td style="font-size:10px; color:{THEME["SUBTEXT"]}; '
                f'padding-right:20px; white-space:nowrap;">'
                f'<span style="color:{THEME["ACCENT"]};">&#9632;</span>&nbsp;'
                f'{_dry_label} {self.format_seconds(int(drying))}</td>'
                f'<td style="font-size:10px; color:{THEME["SUBTEXT"]}; '
                f'padding-right:20px; white-space:nowrap;">'
                f'<span style="color:{THEME["WARNING"]};">&#9632;</span>&nbsp;'
                f'{_mail_label} {self.format_seconds(int(maillard))}</td>'
                f'<td style="font-size:10px; color:{THEME["SUBTEXT"]}; '
                f'white-space:nowrap;">'
                f'<span style="color:{THEME["SUCCESS"]};">&#9632;</span>&nbsp;'
                f'{_dev_label} {self.format_seconds(int(development))}</td>'
                f'</tr></table>'
                f'</td></tr>'
            )
        else:
            phase_bar_html = (
                f'<tr><td colspan="4" style="font-size:11px; color:{THEME["SUBTEXT"]};">'
                + QApplication.translate("tilauscope_beancave",
                                        "Roast data (events) is incomplete in the file.")
                + '</td></tr>'
            )

        # Replace the advice_rows generation block with this:

        advice_rows = ""

        # Single resolution of the roast-level thresholds, reused by every check.
        # The level is the one the roast ran, read from its arrival pair.
        roast_level, lvl_th = self.roast_level_thresholds(
            _measured_level,
            moisture_pct=_safe_moisture(data.get("moisture_greens")),
            dev_time_min=development / 60.0,
            drop_offset_c=self.roast_drop_offset_c(data))
        lvl_dtr_min, lvl_dtr_max = lvl_th['dtr']
        lvl_wl_min,  lvl_wl_max  = lvl_th['wl']

        # Widen both bands by what their own measurement is worth, once, so the
        # advice and the badges inherit the same tolerant edges. A ratio built on
        # a first crack called by ear is worth about the seconds of that call; a
        # weight loss is worth what the two weights on file are worth.
        if total > 0:
            _dtr_tol = 100.0 * _MILESTONE_MARK_TOLERANCE_S / total
            lvl_dtr_min -= _dtr_tol
            lvl_dtr_max += _dtr_tol
        try:
            _w_in  = float(computed.get('weightin') or 0.0)
            _w_out = float(computed.get('weightout') or 0.0)
        except (TypeError, ValueError):
            _w_in = _w_out = 0.0
        if _w_in > 0 and _w_out > 0:
            _wl_tol = 100.0 * _WEIGHT_READING_TOLERANCE_G * (1.0 / _w_in + _w_out / (_w_in ** 2))
            lvl_wl_min -= _wl_tol
            lvl_wl_max += _wl_tol
        lvl_label = (
            QApplication.translate("tilauscope_beancave", "({0} roast)").format(roast_level)
            if roast_level else ""
        )

        # The level everything below is measured against, said out loud with the
        # pair it was read from — a verdict the operator cannot see the basis of
        # is a verdict they cannot argue with.
        if roast_level:
            try:
                _drop_num = float(computed.get('DROP_BT') or 0.0)
            except (TypeError, ValueError):
                _drop_num = 0.0
            _dev_txt = f"{int(development) // 60}:{int(development) % 60:02d}"
            _drop_txt = f"{_drop_num:.0f}°{mode}"
            if _level_neighbour:
                advice_rows += advice_row("\U0001F3AF",
                    QApplication.translate("tilauscope_beancave",
                        "Read as a {0} roast — {1} development, dropped at {2} — but that is too "
                        "close to {3} for this machine to tell the two apart, so it could be read "
                        "either way. What follows is measured against {0}.").format(
                            roast_level, _dev_txt, _drop_txt, _level_neighbour),
                    "info")
            else:
                advice_rows += advice_row("\U0001F3AF",
                    QApplication.translate("tilauscope_beancave",
                        "Read as a {0} roast — {1} development, dropped at {2}. What follows is "
                        "measured against that level.").format(roast_level, _dev_txt, _drop_txt),
                    "info")

        # Effective weight-loss window, resolved once and shared by the coach
        # advice and the summary badge so they can never disagree. The floor
        # follows the roast level (lighter roasts lose less); a known process
        # only *widens the top* — it must not raise the floor above the level,
        # which would wrongly flag a light natural that the badge calls Normal.
        wl_lo_eff, wl_hi_eff = lvl_wl_min, lvl_wl_max
        wl_proc_hint = ""
        _bean_field = data.get("beans", "")
        _linked = None
        _um = re.search(r'uuid:\s*([a-fA-F0-9-]{36})', _bean_field)
        if _um and hasattr(self, 'uuidmap'):
            _linked = self.uuidmap.get(_um.group(1))
            if _linked:
                _proc = getattr(_linked, 'process', '').lower()
                if any(p in _proc for p in ['natural', 'honey', 'anaerobic']):
                    # Surface sugars and looser chaff cost a little extra, but the
                    # water and the development are now in the target itself: the
                    # old absolute 20 % ceiling double-counted them and made the
                    # "high" branch unreachable.
                    wl_hi_eff += 1.0
                    wl_proc_hint = QApplication.translate("tilauscope_beancave", "(natural/honey)")
                elif 'washed' in _proc:
                    wl_proc_hint = QApplication.translate("tilauscope_beancave", "(washed)")

        # ── 1. DTR% — with roast-level context ────────────────────────────────────
        if dtr_pct_val > 0:
            # Thresholds adapt to the target roast level (lighter roasts run a lower DTR).
            dtr_min_ctx, dtr_max_ctx = lvl_dtr_min, lvl_dtr_max
            dtr_label = (
                QApplication.translate("tilauscope_beancave", "({0} roast range)").format(roast_level)
                if roast_level else ""
            )

            # The ratio is only an under-development signal when the *absolute*
            # development time is also short. When the time is adequate, a low
            # ratio just means the front (drying/Maillard) is long — pointing at
            # "extend development" would be wrong, so we reframe it as info.
            dev_min_conv = lvl_th['dev_time'][0]
            dev_time_adequate = (development / 60.0) >= dev_min_conv

            if dtr_pct_val < dtr_min_ctx:
                if dev_time_adequate:
                    advice_rows += advice_row("ℹ",
                        QApplication.translate("tilauscope_beancave", "DTR low but development time is adequate")
                        + f" ({dtr_pct_val:.1f}% &lt; {dtr_min_ctx:.1f}%, {development/60.0:.1f} min) {dtr_label} — "
                        + QApplication.translate("tilauscope_beancave",
                            "the ratio is low because the front (drying/Maillard) is long; shorten the front if you want a higher ratio, no need to extend development."),
                        "info")
                else:
                    advice_rows += advice_row("⚡",
                        QApplication.translate("tilauscope_beancave", "Short development")
                        + f" ({dtr_pct_val:.1f}% &lt; {dtr_min_ctx:.1f}%) {dtr_label} — "
                        + QApplication.translate("tilauscope_beancave",
                            "Underdeveloped risk: baked/grassy notes. Extend dev phase or raise drop temp."),
                        "warn")
            elif dtr_pct_val > dtr_max_ctx:
                advice_rows += advice_row("⚡",
                    QApplication.translate("tilauscope_beancave", "Long development")
                    + f" ({dtr_pct_val:.1f}% &gt; {dtr_max_ctx:.1f}%) {dtr_label} — "
                    + QApplication.translate("tilauscope_beancave",
                        "Over-development risk: flat, roasty notes dominate. Consider an earlier drop."),
                    "warn")
            else:
                advice_rows += advice_row("✓",
                    QApplication.translate("tilauscope_beancave", "DTR in range")
                    + f" ({dtr_pct_val:.1f}%) {dtr_label}", "ok")

        # ── 2. Weight loss — roast-level window, widened for high-retention process ─
        if wl_val is not None:
            process_hint = wl_proc_hint
            wl_min_ctx, wl_max_ctx = wl_lo_eff, wl_hi_eff
            if wl_val < wl_min_ctx:
                advice_rows += advice_row("⚠",
                    QApplication.translate("tilauscope_beancave", "Low weight loss")
                    + f" ({wl_val:.1f}% &lt; {wl_min_ctx:.1f}%) {process_hint} — "
                    + QApplication.translate("tilauscope_beancave",
                        "Bean may be under-roasted or the batch was unusually dense. Verify scale calibration."),
                    "warn")
            elif wl_val > wl_max_ctx:
                advice_rows += advice_row("⚠",
                    QApplication.translate("tilauscope_beancave", "High weight loss")
                    + f" ({wl_val:.1f}% &gt; {wl_max_ctx:.1f}%) {process_hint} — "
                    + QApplication.translate("tilauscope_beancave",
                        "Roast may be over-developed or airflow too high. Watch for flat cup."),
                    "bad")
            else:
                advice_rows += advice_row("✓",
                    QApplication.translate("tilauscope_beancave", "Weight loss in range")
                    + f" ({wl_val:.1f}%) {process_hint}", "ok")

        # ── 3. Phase durations ────────────────────────────────────────────────────
        # Development time is judged on the professional-convention window for the
        # target level (absolute minutes), so a sound light development of 1:00–1:30
        # reads on-target regardless of the learned average. Drying and Maillard
        # keep the learned, per-level ranges (with pooled fallback).
        rules = dict(rules)
        rules['development'] = lvl_th['dev_time']
        # QT_TRANSLATE_NOOP declares the label for the extractor and returns it
        # unchanged; the translate() below then finds it in the catalogue.
        for phase_name_key, phase_key, duration_s in [
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Dry Phase"),         "drying",      drying),
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Maillard Phase"),    "maillard",    maillard),
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Development Phase"), "development", development),
        ]:
            if phase_key in rules and duration_s > 0:
                mn, mx = rules[phase_key]
                actual_min = duration_s / 60.0
                phase_tr = QApplication.translate("tilauscope_beancave", phase_name_key)
                # Development cites the professional standard; the other phases
                # cite the user's own learned range.
                range_lbl = (QApplication.translate('tilauscope_beancave', 'standard for this level')
                             if phase_key == 'development'
                             else QApplication.translate('tilauscope_beancave', 'your usual range'))
                # Drying/Maillard are learned, soft references: a minor drift past
                # the band (< 30 s) is noise, not a fault — stay silent (on-target).
                # Development keeps the professional floor, but still cannot be
                # judged finer than the seconds its milestones were called with.
                grace = (0.5 if phase_key in ('drying', 'maillard')
                         else _MILESTONE_MARK_TOLERANCE_S / 60.0)
                if actual_min < mn - grace:
                    # Observational, not a verdict: the range is learned from the
                    # user's own roasts at this level, so a short phase may simply
                    # be the intended style. Development gets the gentlest framing.
                    context = {
                        "drying": QApplication.translate("tilauscope_beancave",
                            "If the cup tastes grassy or green, give the beans a little longer to dry before browning."),
                        "maillard": QApplication.translate("tilauscope_beancave",
                            "Less time for caramelization — body may be lighter and acidity sharper."),
                        "development": QApplication.translate("tilauscope_beancave",
                            "Below the professional minimum for this level — real under-development risk (grassy/baked). Carry more momentum into first crack or drop a little later."),
                    }.get(phase_key, "")
                    advice_rows += advice_row("⏱",
                        f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'shorter than usual')}"
                        + f" ({actual_min:.1f} min, {range_lbl} {mn:.1f}–{mx:.1f} min) {lvl_label} — {context}",
                        "warn")
                elif actual_min > mx + grace:
                    context = {
                        "drying": QApplication.translate("tilauscope_beancave",
                            "Long drying can reduce caramelization potential and flatten sweetness."),
                        "maillard": QApplication.translate("tilauscope_beancave",
                            "Excessive Maillard may push toward flat, bready notes."),
                        "development": QApplication.translate("tilauscope_beancave",
                            "Over-development: roasty, dark tones may dominate origin character."),
                    }.get(phase_key, "")
                    advice_rows += advice_row("⏱",
                        f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'longer than usual')}"
                        + f" ({actual_min:.1f} min, {range_lbl} {mn:.1f}–{mx:.1f} min) {lvl_label} — {context}",
                        "warn")
                else:
                    advice_rows += advice_row("✓",
                        f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'on target')}"
                        + f" ({actual_min:.1f} min)", "ok")

        # ── 4. Cross-check: Drop BT vs DTR consistency ────────────────────────────
        # A low drop temperature is the *goal* on a light roast, so it is only a
        # concern when it lands below the window expected for the target level AND
        # the development ratio is also short — two independent signals agreeing.
        # That concordance is what earns the red flag; either one alone does not.
        drop_bt_val = computed.get('DROP_BT', None)
        if drop_bt_val and dtr_pct_val > 0:
            try:
                drop_bt_f = float(drop_bt_val)
                drop_low_c, drop_high_c = lvl_th['drop_c']
                if mode == 'F':
                    drop_low  = drop_low_c * 9.0 / 5.0 + 32.0
                    drop_high = drop_high_c * 9.0 / 5.0 + 32.0
                else:
                    drop_low, drop_high = drop_low_c, drop_high_c
                if drop_bt_f < drop_low and dtr_pct_val < lvl_dtr_min:
                    advice_rows += advice_row("🔴",
                        QApplication.translate("tilauscope_beancave",
                            "Both the drop temperature and the development ratio land below the "
                            "window expected for this roast level — two signals agreeing on "
                            "under-development. Watch for grassy or baked notes; consider a hotter "
                            "charge or a slower Maillard.") + f" {lvl_label}",
                        "bad")
                elif drop_bt_f > drop_high and dtr_pct_val < lvl_dtr_min:
                    advice_rows += advice_row("🔶",
                        QApplication.translate("tilauscope_beancave",
                            "Drop temperature is higher than expected for this level yet the "
                            "development ratio is short — the bean colour may be darker than "
                            "intended. Watch for scorching; reduce end-heat or drop earlier.") + f" {lvl_label}",
                        "warn")
            except (TypeError, ValueError):
                pass

        # ── 5. RoR at drop — check for crash/flick ────────────────────────────────
        # 5a. RoR at the onset of first crack — momentum entering development.
        #     Roaster-agnostic: a flat/negative RoR at FCs means the bean enters
        #     development with no thermal momentum (stall/crash risk), regardless
        #     of roaster type. No absolute "high" threshold is used here on purpose.
        # Ideal RoR band for the development phase (FC → DROP), the same shared
        # source used in-roast by the assistant (roast_asssistant.py) and by the
        # plan generator's drying-band lookup (roast_plan_model.py).
        dev_ror_lo, dev_ror_hi = get_ror_ideal_band("FC_DROP", mode)

        fcs_ror = computed.get('fcs_ror', None)
        if fcs_ror is not None:
            try:
                fcs_ror_v = float(fcs_ror)
                if fcs_ror_v <= 0:
                    advice_rows += advice_row("🧊",
                        QApplication.translate("tilauscope_beancave",
                            "Flat or negative RoR entering first crack: the roast lost momentum "
                            "right at FC, a strong stall/crash signal. Add a touch of heat just "
                            "before FC next time to carry momentum into development."),
                        "bad")
                elif fcs_ror_v < dev_ror_lo:
                    advice_rows += advice_row("🐌",
                        QApplication.translate("tilauscope_beancave",
                            "Low RoR entering first crack: little momentum into "
                            "development — watch for a stall and baked, flat character."),
                        "warn")
            except (TypeError, ValueError):
                pass

        # 5b. Crash/flick in development, via the same prominence-based local-extrema
        #     detector the plan generator uses on historical logs — one algorithm,
        #     not a separate ratio heuristic in the coach.
        try:
            ti = normalize_timeindex(data.get('timeindex', []))
            charge_idx, drop_idx = ti[RoastingPhase.CHARGE], ti[RoastingPhase.DROP]
            timex = data.get("timex", [])
            raw_delta_bt = self.evaldeltas(data, "temp2") if charge_idx >= 0 < drop_idx else None
            if (raw_delta_bt and timex and charge_idx >= 0 and drop_idx > charge_idx
                    and len(timex) == len(raw_delta_bt) and drop_idx < len(timex)):
                charge_ts = timex[charge_idx]
                timex_shifted = [(t - charge_ts) for t in timex]
                dry_idx, fc_idx = ti[RoastingPhase.DRYEND], ti[RoastingPhase.FCSTART]
                phase_times = {
                    "dry_end":  timex_shifted[dry_idx] if dry_idx > 0 else None,
                    "fc_start": timex_shifted[fc_idx]  if fc_idx  > 0 else None,
                    "drop":     timex_shifted[drop_idx],
                }
                bt_raw = data.get("temp2", [])
                seg_slice = slice(charge_idx, drop_idx + 1)
                seg_dt = estimate_ror_dt(timex_shifted[seg_slice])
                tp_idx_local = find_turning_point_index(bt_raw[seg_slice], seg_dt)
                # The RoR series is in the DISPLAY unit (evaldeltas converts it),
                # so the °C-based threshold scales on that, not on the unit the
                # profile was recorded in.
                event = dominant_dev_ror_event(
                    raw_delta_bt[seg_slice], timex_shifted[seg_slice], phase_times,
                    tp_idx_local, str(self.aw.qmc.mode))
                if event is not None:
                    # The time is spelled out so the operator can go and look at
                    # the spot on the curve instead of taking the claim on trust.
                    at_t = f"{int(event['time']) // 60}:{int(event['time']) % 60:02d}"
                    if event["kind"] == "crash":
                        advice_rows += advice_row("📉",
                            QApplication.translate("tilauscope_beancave",
                                "RoR crash at {0} in development: the rate dropped sharply before "
                                "drop. This can cause baked character. Maintain at least {1:.0f}°/min "
                                "through drop.").format(at_t, dev_ror_lo),
                            "bad")
                    else:
                        advice_rows += advice_row("📈",
                            QApplication.translate("tilauscope_beancave",
                                "RoR flick at {0} in development: the rate bumped up significantly. "
                                "This may indicate a heat spike. Reduce burner earlier to avoid "
                                "scorching.").format(at_t),
                            "warn")
        except (TypeError, ValueError, IndexError):
            pass

        # ── 6. Density context ────────────────────────────────────────────────────
        # The bean this roast is linked to, never the catalogue selection: the
        # Green Beans tab keeps its own highlight, so the advice used to describe
        # a coffee that is not in the log at all. No link, no density advice.
        chk_bean = _linked
        if chk_bean is not None:
            if chk_bean.density > 780:
                advice_rows += advice_row("💎",
                    QApplication.translate("tilauscope_beancave",
                        "Very high density bean (>780 g/l): needs strong initial charge energy. "
                        "If DTR or weight loss is low, consider raising charge temp by 5–8°C next roast."),
                    "info")
            elif 0 < chk_bean.density < 650:
                advice_rows += advice_row("🪶",
                    QApplication.translate("tilauscope_beancave",
                        "Low density bean (<650 g/l): absorbs heat quickly — watch for early FC. "
                        "Reduce heat in Maillard to avoid rushing development."),
                    "info")

        if not advice_rows:
            advice_rows = advice_row("✓",
                QApplication.translate("tilauscope_beancave",
                    "All measured parameters are within the recommended ranges."), "ok")

        # ── Translated labels ─────────────────────────────────────────────
        _total_time   = QApplication.translate("tilauscope_beancave", "Total Time")
        _weight_loss_l= QApplication.translate("tilauscope_beancave", "Weight loss")
        _bean_weight  = QApplication.translate("tilauscope_beancave", "Green beans weight")
        _roast_weight = QApplication.translate("tilauscope_beancave", "Roasted weight")
        _charge_bt    = QApplication.translate("tilauscope_beancave", "Charge BT")
        _tp           = QApplication.translate("tilauscope_beancave", "Turn Point BT")
        _de           = QApplication.translate("tilauscope_beancave", "Dry End BT")
        _fc           = QApplication.translate("tilauscope_beancave", "FCs BT")
        _drop         = QApplication.translate("tilauscope_beancave", "Drop BT")
        _ror_dry      = QApplication.translate("tilauscope_beancave", "Average rise · Drying")
        _ror_mai      = QApplication.translate("tilauscope_beancave", "Average rise · Maillard")
        _ror_dev      = QApplication.translate("tilauscope_beancave", "Average rise · Development")
        _ror_total    = QApplication.translate("tilauscope_beancave", "Average rise · TP to drop")
        _auc_dry      = QApplication.translate("tilauscope_beancave", "AUC Dry Phase")
        _auc_middle   = QApplication.translate("tilauscope_beancave", "AUC Maillard Phase")
        _auc_fc       = QApplication.translate("tilauscope_beancave", "AUC Finish phase")
        _auc_total    = QApplication.translate("tilauscope_beancave", "AUC Total")
        _auc_begin    = QApplication.translate("tilauscope_beancave", " - AUC begins from ") if auc_start_str else ""
        _coach_lbl    = QApplication.translate("tilauscope_beancave", "Coach's Advice 🎯") \
                            .replace("<h3>","").replace("</h3>","")
        _weight_inout = f"{_bean_weight} → {_roast_weight}"

        # badges pour les metric cards
        # Badges use the exact same effective windows as the advice above.
        wl_text, wl_kind   = wl_badge_text(wl_val, wl_lo_eff, wl_hi_eff)
        dtr_text, dtr_kind = dtr_badge_text(dtr_pct_val, lvl_dtr_min, lvl_dtr_max)

        auc_suffix = f"{_auc_begin}{auc_start_str}" if auc_start_str else ""

        # ── RoR par phase : 3 metric cards côte à côte ────────────────────
        ror_cards = (
            '<tr>'
            + metric_card(_ror_dry,
                        f"{phase_rise('TP', 'DRY')} °/min")
            + metric_card(_ror_mai,
                        f"{phase_rise('DRY', 'FCs')} °/min")
            + metric_card(_ror_dev,
                        f"{phase_rise('FCs', 'DROP')} °/min")
            + metric_card(_ror_total,
                        f"{phase_rise('TP', 'DROP')} °/min")
            + '</tr>'
        )

        # ── Assembly ──────────────────────────────────────────────────────
        summary = f"""<html><body style="
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: {THEME['TEXT']};
            background-color: {THEME['BG']};
            margin: 0; padding: 8px;">

    <table width="100%" cellpadding="0" cellspacing="0">

    <!-- HEADER -->
    <tr>
    <td colspan="3" style="padding-bottom:4px;">
        <span style="font-size:14px; font-weight:bold;">{data.get('title','—')}</span>
        {f' &nbsp;<span style="font-size:11px; font-weight:bold; padding:2px 7px; border-radius:4px; background-color:{THEME["ACCENT"]}; color:{THEME["BG"]}">{batch_prefix}{batch_nr}</span>' if batch_nr > 0 else ''}<br/>
        <span style="font-size:11px; color:{THEME['SUBTEXT']};">{date} {roasttime} · {roastertype}</span>
    </td>
    <td align="right" style="vertical-align:top; padding-bottom:4px; white-space:nowrap;">
        {badge(colour_badge_txt, "accent")}
        {f'<br/><span style="font-size:10px; color:{THEME["SUBTEXT"]};">{colour_detail}</span>' if colour_detail else ''}
        <br/><span style="font-size:10px; color:{THEME['SUBTEXT']};">{agtron_label}</span>
    </td>
    </tr>
    <tr><td colspan="4">
    <hr style="border:none; border-top:1px solid {THEME['BORDER']}; margin:4px 0 8px 0;"/>
    </td></tr>

    <!-- RÉSUMÉ : 4 metric cards -->
    {section_title(QApplication.translate("tilauscope_beancave","Summary"))}
    <tr>
    {metric_card(_total_time,
                f"{self.format_seconds(total)}",f"({round(total/60,1)} min)")}
    {metric_card(_weight_loss_l,
                f"{wl_val:.1f} %" if wl_val else "N/A",
                wl_text, wl_kind)}
    {metric_card("DTR",
                f"{dtr_pct_val:.1f} %" if dtr_pct_val else "N/A",
                dtr_text, dtr_kind)}
    {metric_card(_weight_inout,
                f"{computed.get('weightin','?')}{charge_unit} → {computed.get('weightout','?')}{charge_unit}",f"({QApplication.translate("Label","Defects")} {defect_weight}{charge_unit})")}
    </tr>

    <!-- PHASES -->
    {section_title(QApplication.translate("tilauscope_beancave","Phases"))}
    {phase_bar_html}

    <!-- TEMPÉRATURES -->
    {section_title(QApplication.translate("tilauscope_beancave","Charge BT").replace(" BT","") + " & Drop")}
    <tr>
    <td colspan="2" style="vertical-align:top; padding-right:1px;">
        <table cellpadding="0" cellspacing="0">
        {kv_row(_charge_bt,  f"{computed.get('CHARGE_BT','N/A')} °{mode}")}
        {kv_row(_tp,         f"{computed.get('TP_BT','N/A')} °{mode} · {self.format_seconds(computed.get('TP_time',0))}")}
        {kv_row(_de,         f"{computed.get('DRY_BT','N/A')} °{mode}")}
        {kv_row(_fc,         f"{computed.get('FCs_BT','N/A')} °{mode}")}
        {kv_row(_drop,       f"{computed.get('DROP_BT','N/A')} °{mode}")}
        </table>
    </td>
    <td colspan="2" style="vertical-align:top;">
        <table cellpadding="0" cellspacing="0" width="100%">
        {kv_row(_auc_dry,    f"{drying_auc} °{mode}")}
        {kv_row(_auc_middle, f"{middle_auc} °{mode}")}
        {kv_row(_auc_fc,     f"{fcs_drop} °{mode}")}
        {kv_row(_auc_total,  f"{total_auc} °{mode}{auc_suffix}")}
        </table>
    </td>
    </tr>

    <!-- RoR PAR PHASE : 4 metric cards -->
    {section_title(QApplication.translate("tilauscope_beancave","Average rise per phase"))}
    {ror_cards}

    <!-- CONSEILS -->
    {section_title(_coach_lbl)}
    {advice_rows}

    </table>
    </body></html>"""

        self.roast_info_text.setText(summary)

    @staticmethod
    def format_seconds(seconds: float) -> str:
        return f"{int(seconds // 60)}:{int(round(seconds % 60)):02d}"
