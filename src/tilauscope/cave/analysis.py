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
import html
from datetime import datetime

#import matplotlib.pyplot as plt



from artisanlib.atypes import ProfileData, ComputedProfileInformation

from PyQt6.QtCore import pyqtSlot # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QMessageBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import AGTRON_SCALES, THEME, resolve_color_system
from tilauscope.brew_advisor import BrewInput, WaterProfile
from tilauscope.brew_advisor_dialog import BrewAdvisorDlg
from tilauscope import roast_coach as coach
from tilauscope.cave.common import (
    _logd)


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
        """The bean probe's deviation at drop for the machine that ran this roast."""
        return coach.probe_drop_offset_c(self._roast_machine_ctx(data))

    def roast_arrival_uncertainty_c(self, data) -> float:
        """What a level read from this machine's arrival is worth, in °C."""
        return coach.arrival_uncertainty_c(self._roast_machine_ctx(data))

    def roast_level_measured(self, data, computed, mode: str = 'C'):
        """(level, neighbour) for this roast, from its arrival pair."""
        return coach.measured_level(computed, mode, self._roast_machine_ctx(data))

    def roast_level_thresholds(self, level, *,
                               moisture_pct: float = 0.0,
                               dev_time_min: float = 0.0,
                               drop_offset_c: float = 0.0):
        """(level, thresholds) for a measured roast level — see `roast_coach.level_thresholds`."""
        return coach.level_thresholds(level, moisture_pct=moisture_pct,
                                      dev_time_min=dev_time_min, drop_offset_c=drop_offset_c)

    def phase_rules_for_level(self, level):
        """Phase-duration ranges for the roast's level, pooled rules as the fallback."""
        return coach.phase_rules_for_level(level,
                                           getattr(self, 'duration_rules', {}) or {},
                                           getattr(self, 'duration_rules_by_band', {}) or {})



    def _get_uuid_from_bean_description(self, bean_field:str)-> str:
        """The green bean a profile's ``beans`` field points at, or ''."""
        return self.bean_from_profile({'beans': bean_field}) or ""

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
        uuid_match = self.uuid_pattern.search(bean_field)
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
            rise = coach.average_rise(computed, t_from, t_to)
            return "N/A" if rise is None else f"{rise:.2f}"

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

        # Each badge carries its own short key. Cutting a long sentence down with
        # split()[0] or replace(" DTR","") only ever worked on the English text:
        # "Perte de poids normale" became "Perte", and the DTR labels kept the
        # three letters the cut was meant to remove.
        def _range_badge(val, ok_min, ok_max, ok_label):
            if val is None:
                return "N/A", "neutral"
            try:
                v = float(val)
            except (TypeError, ValueError):
                return "N/A", "neutral"
            if ok_min <= v <= ok_max:
                return ok_label, "ok"
            if v < ok_min:
                return QApplication.translate("tilauscope_beancave", "Low"), "warn"
            return QApplication.translate("tilauscope_beancave", "High"), "bad"

        def dtr_badge_text(val, ok_min, ok_max):
            return _range_badge(val, ok_min, ok_max,
                                QApplication.translate("tilauscope_beancave", "Optimal"))

        def wl_badge_text(val, ok_min, ok_max):
            return _range_badge(val, ok_min, ok_max,
                                QApplication.translate("tilauscope_beancave", "Normal"))

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
            # Advice is plain text: a raw "<650 g/l" in a translation would open a
            # tag and swallow the rest of the row.
            text = html.escape(text, quote=False)
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

        # The coach's reading — the same rows Coach's advice shows in the roasting window.
        _bean_uuid = coach.bean_uuid(data.get("beans", ""))
        reading = coach.read_roast(
            data,
            roast_context=self._roast_machine_ctx(data),
            bean=getattr(self, 'uuidmap', {}).get(_bean_uuid) if _bean_uuid else None,
            duration_rules=getattr(self, 'duration_rules', {}) or {},
            duration_rules_by_band=getattr(self, 'duration_rules_by_band', {}) or {},
            evaluate_ror_bt=lambda: self.evaldeltas(data, "temp2"),
            ror_mode=str(self.aw.qmc.mode))
        advice_rows = "".join(advice_row(r.icon, r.text, r.kind) for r in reading.rows)
        # The summary badges judge with the exact windows the advice used.
        lvl_dtr_min, lvl_dtr_max = reading.dtr_window
        wl_lo_eff, wl_hi_eff = reading.wl_window

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
