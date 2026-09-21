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

#import matplotlib.pyplot as plt




from PyQt6.QtCore import QPoint # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtWidgets import (QApplication) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import (THEME, RoastingPhase, normalize_timeindex, estimate_ror_dt, find_turning_point_index, dominant_dev_ror_event)
from tilauscope.cave.common import (_logd, _PLOT_PALETTE, _FS_AXIS, _FS_TICK)
from tilauscope.graph import comparison as compare


class ViewerMultiMixin:
    """Comparing several roasts on one set of axes, and the statistics that go with it.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """


    # Teintes catégorielles distinctes — une par roast en comparaison (Catppuccin).
    # Le roast est identifié par la couleur ; le type de donnée par le style de
    # trait (BT plein, RoR tireté, ET pointillé fin).
    _MULTI_HUES: tuple = (
        "#89B4FA",  # Blue
        "#FAB387",  # Peach
        "#A6E3A1",  # Green
        "#CBA6F7",  # Mauve
        "#F9E2AF",  # Yellow
        "#94E2D5",  # Teal
        "#F38BA8",  # Red
        "#F5C2E7",  # Pink
    )

    def _make_multi_palette(self, n: int) -> list[tuple[str, str, str, str]]:
        """Génère n quadruplets (bt, et, dbt, ror) — une teinte distincte par roast.

        Les quatre composantes partagent la même teinte : la distinction BT / ET /
        RoR se fait par le style de trait au tracé, pas par la couleur. Au-delà de
        8 roasts, les teintes sont recyclées.
        """
        result = []
        for i in range(n):
            hue = self._MULTI_HUES[i % len(self._MULTI_HUES)]
            result.append((hue, hue, hue, hue))
        return result

    def _plot_multi_curves(self) -> None:
        """Compare the loaded roasts on TilauScope's own curve engine.

        The comparison is the same drawing as the roast being watched — same
        frame, same phase grounds, same milestone chips — with the first roast
        holding it and the others measured against it. Everything the mode asks
        of the data happens inside the engine, once, not at paint time.
        """
        if not self._multi_curves:
            return
        roasts: list[compare.ComparedRoast] = []
        for curve in self._multi_curves:
            data = curve.get('data')
            if not data:
                continue
            # The first roast with data holds the frame, and keeps the bean
            # colour it is drawn in everywhere else.
            hue = (None if not roasts
                   else compare.COMPARISON_HUES[(len(roasts) - 1)
                                                % len(compare.COMPARISON_HUES)])
            roast = compare.from_profile(
                data, colour=hue, title=str(curve.get('title') or ''),
                deltabt=curve.get('deltabt'), deltaet=curve.get('deltaet'))
            if roast is not None:
                roasts.append(roast)
        if not roasts:
            return
        # The card hides the view and time range switches while comparing, even
        # when one roast is all that loaded: nothing they said may apply here.
        self.roast_curve.set_static_view(lanes=bool(getattr(self, '_curve_show_settings', True)))
        self.roast_curve.set_comparison(
            roasts, getattr(self, '_multi_view_mode', 'overlay'))
        self.canvas_stack.setCurrentWidget(self.roast_curve)
        self.last_plot_data = self._multi_curves[0]['data']
        # Onglet Advanced Stats : dot plot comparatif + mini-résumé (pas le tableau).
        try:
            self._set_stats_view(True)
            self._render_multi_dotplot()
            # The detail head says how many roasts are compared, the View switch how.
            self.roast_plot_label.setText("")
        except Exception as e:
            _logd.error(f"multi curve plot error: {e}")

    def _extract_roast_metrics(self, data: dict) -> dict:
        c = data.get('computed', {})
        mode = data.get('mode', 'C')
        t_charge = 0
        t_dry    = c.get('DRY_time', 0) or 0
        t_fcs    = c.get('FCs_time', 0) or 0
        t_drop   = c.get('DROP_time', 0) or 0
        drying      = t_dry - t_charge
        maillard    = t_fcs - t_dry
        development = t_drop - t_fcs
        # Resolved after the phases: the weight-loss target needs this roast's
        # own water and development, not the colour alone.
        try:
            _moist = float(data.get('moisture_greens') or 0.0)
        except (TypeError, ValueError):
            _moist = 0.0
        # The level the roast ran, from its arrival pair — the colour is the
        # result, never the reference the roast is judged against.
        level, lvl_th = self.roast_level_thresholds(
            self.roast_level_measured(data, c, mode)[0],
            moisture_pct=_moist, dev_time_min=development / 60.0,
            drop_offset_c=self.roast_drop_offset_c(data))
        dtr_target = sum(lvl_th['dtr']) / 2.0
        wl_target = lvl_th['wl_target']
        total       = t_drop - t_charge
        dtr  = round(100 * development / total, 1) if total > 0 else 0.0
        wl   = c.get('weight_loss', None)
        try: wl = round(float(wl), 1) if wl not in (None, 0.0, 'N/A') else None
        except (TypeError, ValueError): wl = None
        def _ror(key):
            v = c.get(key, None)
            try: return round(float(v), 2) if v not in (None, 'N/A') else None
            except (TypeError, ValueError): return None
        def _fmt_s(s):
            s = int(s or 0)
            return f"{s//60}:{s%60:02d}"
        charge_w = data.get('weight', [None, None, ''])
        try: w_in  = float(charge_w[0]) if charge_w[0] else None
        except (TypeError, ValueError): w_in = None
        try: w_out = float(charge_w[1]) if charge_w[1] else None
        except (TypeError, ValueError): w_out = None
        w_unit = charge_w[2] if len(charge_w) > 2 else 'g'
        def _bt(key):
            v = c.get(key, None)
            try: return round(float(v), 1) if v not in (None, 'N/A', 0) else None
            except (TypeError, ValueError): return None
        def _auc(key):
            # AUC (area under BT curve above the configured base) — absolute value
            # depends on the user's AUCbase setting, but is consistent across the
            # user's own roasts, so it is surfaced as a consistency metric only.
            v = c.get(key, None)
            try: return int(round(float(v))) if v not in (None, 'N/A', 0) else None
            except (TypeError, ValueError): return None
        return {
            'title': data.get('title', '?'), 'date': data.get('roastdate', ''),
            'mode': mode, 'total_s': total, 'total_fmt': _fmt_s(total),
            'drying_s': drying, 'drying_fmt': _fmt_s(drying),
            'drying_pct': round(100*drying/total,1) if total>0 else 0,
            'maillard_s': maillard, 'maillard_fmt': _fmt_s(maillard),
            'maillard_pct': round(100*maillard/total,1) if total>0 else 0,
            'dev_s': development, 'dev_fmt': _fmt_s(development), 'dtr': dtr,
            'wl': wl, 'charge_bt': _bt('CHARGE_BT'), 'drop_bt': _bt('DROP_BT'),
            'tp_bt': _bt('TP_BT'), 'tp_fmt': _fmt_s(c.get('TP_time', 0) or 0),
            'ror_dry': _ror('dry_phase_ror'), 'ror_mid': _ror('mid_phase_ror'),
            'ror_fin': _ror('finish_phase_ror'), 'ror_total': _ror('total_ror'),
            'auc_total': _auc('AUC'), 'auc_dry': _auc('dry_phase_AUC'),
            'auc_mid': _auc('mid_phase_AUC'), 'auc_fin': _auc('finish_phase_AUC'),
            'w_in': w_in, 'w_out': w_out, 'w_unit': w_unit,
            'level': level, 'dtr_target': dtr_target, 'wl_target': wl_target,
        }

    def _generate_multi_coach_advice(self, metrics: list) -> list:
        advices = []
        OK, WARN, INFO = THEME['SUCCESS'], THEME['CRITICAL'], THEME['SKY']
        def _c(col, txt): return f'<span style="color:{col};font-weight:600;">{txt}</span>'
        mode = metrics[0].get('mode', 'C') if metrics else 'C'
        tscale = 1.8 if mode == 'F' else 1.0   # cibles/écarts en ° pour le Fahrenheit
        # DTR and weight loss are compared against each roast's OWN roast-level
        # target (ROASTING_BASIC_BASE / WEIGHT_LOSS_PCT_BY_CATEGORY, the same
        # shared tables as the roast plan and the single-roast coach) — a light
        # and a dark roast in the same comparison are no longer judged against
        # one another's target.
        dtrs = [(m['title'][:22], m['dtr'], m['dtr_target']) for m in metrics if m['dtr']]
        if dtrs:
            best  = min(dtrs, key=lambda x: abs(x[1] - x[2]))
            worst = max(dtrs, key=lambda x: abs(x[1] - x[2]))
            advices.append(QApplication.translate("tilauscope_beancave",
                "DTR closest to its roast-level target: {best} ({bv:.1f}% vs {bt:.0f}%) — "
                "furthest: {worst} ({wv:.1f}% vs {wt:.0f}%)").format(
                    best=_c(OK, best[0]), bv=best[1], bt=best[2],
                    worst=_c(WARN, worst[0]), wv=worst[1], wt=worst[2]))
        wls = [(m['title'][:22], m['wl'], m['wl_target']) for m in metrics if m['wl']]
        if wls:
            best = min(wls, key=lambda x: abs(x[1] - x[2]))
            advices.append(QApplication.translate("tilauscope_beancave",
                "Weight loss closest to its roast-level target: {best} ({bv:.1f}% vs {bt:.0f}%)").format(
                    best=_c(OK, best[0]), bv=best[1], bt=best[2]))
        # RoR Total has no validated per-level reference anywhere else in the app
        # (unlike DTR/weight loss) — it stays a relative consistency check against
        # the group's own average, the same pattern as the drop BT and development
        # spreads below, rather than an arbitrary absolute figure.
        rors = [(m['title'][:22], m['ror_total']) for m in metrics if m['ror_total']]
        if len(rors) >= 2:
            avg = sum(r[1] for r in rors) / len(rors)
            best  = min(rors, key=lambda x: abs(x[1] - avg))
            worst = max(rors, key=lambda x: abs(x[1] - avg))
            if best[0] != worst[0]:
                advices.append(QApplication.translate("tilauscope_beancave",
                    "RoR Total closest to the group average ({avg:.2f}°/min): {best} ({bv:.2f}) — "
                    "furthest: {worst} ({wv:.2f})").format(
                        avg=avg, best=_c(OK, best[0]), bv=best[1], worst=_c(WARN, worst[0]), wv=worst[1]))
        drops = [(m['title'][:22], m['drop_bt']) for m in metrics if m['drop_bt']]
        if len(drops) >= 2:
            spread = max(d[1] for d in drops) - min(d[1] for d in drops)
            ok = spread < 5 * tscale
            note = (QApplication.translate("tilauscope_beancave", "consistent ✓") if ok
                    else QApplication.translate("tilauscope_beancave", "variable — check profile consistency"))
            advices.append(QApplication.translate("tilauscope_beancave", "Drop BT spread: {v} — {note}").format(
                v=_c(OK if ok else WARN, f"{spread:.1f}°{mode}"), note=note))
        devs = [(m['title'][:22], m['dev_s']) for m in metrics if m['dev_s']]
        if devs:
            spread_s = max(d[1] for d in devs) - min(d[1] for d in devs)
            mm, ss = int(spread_s)//60, int(spread_s)%60
            ok = spread_s < 30
            note = (QApplication.translate("tilauscope_beancave", "tight ✓") if ok
                    else QApplication.translate("tilauscope_beancave", "consider aligning development phases"))
            advices.append(QApplication.translate("tilauscope_beancave", "Development spread: {v} — {note}").format(
                v=_c(OK if ok else INFO, f"{mm}:{ss:02d}"), note=note))
        return advices

    def _detect_crash_flick(self, data: dict, deltabt: list) -> "str | None":
        """Détecte un accident de RoR en développement (FCs→DROP) via le même
        détecteur à extrema locaux pondérés par proéminence que le plan de
        torréfaction et le coach mono-roast — 'crash', 'flick', ou None si le
        développement reste propre. Un seul verdict : le plus proéminent."""
        if not data or not deltabt:
            return None
        ti = normalize_timeindex(data.get('timeindex', []))
        charge_idx, drop_idx = ti[RoastingPhase.CHARGE], ti[RoastingPhase.DROP]
        timex = data.get('timex', [])
        if (charge_idx < 0 or drop_idx <= charge_idx or not timex
                or len(timex) != len(deltabt) or drop_idx >= len(timex)):
            return None
        try:
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
            # Série de RoR déjà convertie dans l'unité d'affichage par evaldeltas :
            # le seuil se met à l'échelle sur celle-ci, pas sur l'unité du profil.
            event = dominant_dev_ror_event(
                deltabt[seg_slice], timex_shifted[seg_slice], phase_times,
                tp_idx_local, str(self.aw.qmc.mode))
        except (TypeError, ValueError, IndexError):
            return None
        return None if event is None else str(event["kind"])

    def _generate_multi_analysis(self, metrics: list) -> str:
        """Analyse en clair (1 paragraphe) de la comparaison : verdict de régularité,
        principal écart, note sur le ratio de développement, accidents de RoR.
        Déterministe."""
        n = len(metrics)
        if n < 2:
            return ""
        OK, WARN, ACC = THEME['SUCCESS'], THEME['CRITICAL'], THEME['ACCENT']
        mode = metrics[0].get('mode', 'C')
        tscale = 1.8 if mode == 'F' else 1.0   # seuils en ° pour le Fahrenheit
        drop_tol = 5 * tscale
        def _c(col, t): return f'<span style="color:{col};font-weight:600;">{t}</span>'
        def _spread(key):
            vals = [m[key] for m in metrics if m.get(key) is not None]
            return (max(vals) - min(vals)) if len(vals) >= 2 else None
        drop_sp, dev_sp = _spread('drop_bt'), _spread('dev_s')
        dtr_sp, tot_sp = _spread('dtr'), _spread('total_s')

        # Verdict de régularité : combien de dimensions sont serrées.
        checks = []
        for sp, tol in ((drop_sp, drop_tol), (dev_sp, 30), (dtr_sp, 3), (tot_sp, 45)):
            if sp is not None:
                checks.append(sp < tol)
        tight = sum(checks)
        if checks and tight == len(checks):
            verdict = QApplication.translate("tilauscope_beancave", "very consistent")
            vcol = OK
        elif checks and tight >= len(checks) * 0.6:
            verdict = QApplication.translate("tilauscope_beancave", "fairly consistent")
            vcol = OK
        else:
            verdict = QApplication.translate("tilauscope_beancave", "uneven")
            vcol = WARN
        parts = [QApplication.translate("tilauscope_beancave",
                 "These {n} roasts are {verdict}.").format(n=n, verdict=_c(vcol, verdict))]

        # Principal écart (rapporté à sa tolérance).
        issues = []
        if drop_sp is not None and drop_sp >= drop_tol:
            issues.append((QApplication.translate("tilauscope_beancave", "drop temperature"),
                           f"{drop_sp:.0f}°{mode}", drop_sp / drop_tol))
        if dev_sp is not None and dev_sp >= 30:
            issues.append((QApplication.translate("tilauscope_beancave", "development time"),
                           f"{int(dev_sp)//60}:{int(dev_sp)%60:02d}", dev_sp / 30))
        if dtr_sp is not None and dtr_sp >= 3:
            issues.append((QApplication.translate("tilauscope_beancave", "development ratio"),
                           f"{dtr_sp:.0f} pts", dtr_sp / 3))
        if tot_sp is not None and tot_sp >= 45:
            issues.append((QApplication.translate("tilauscope_beancave", "total time"),
                           f"{int(tot_sp)//60}:{int(tot_sp)%60:02d}", tot_sp / 45))
        if issues:
            issues.sort(key=lambda x: -x[2])
            name, val, _ = issues[0]
            parts.append(QApplication.translate("tilauscope_beancave",
                         "The biggest difference is in {name} ({val} spread).").format(
                             name=name, val=_c(WARN, val)))
        else:
            parts.append(QApplication.translate("tilauscope_beancave",
                         "All the key milestones line up closely."))

        # Note sur le ratio de développement (cible ~18–22%).
        dtrs = [m['dtr'] for m in metrics if m.get('dtr')]
        if dtrs:
            avg = sum(dtrs) / len(dtrs)
            if avg < 17:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Development ratios average {v} — a touch low; a longer development "
                    "could add sweetness.").format(v=_c(ACC, f"{avg:.0f}%")))
            elif avg > 23:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Development ratios average {v} — on the high side; a shorter "
                    "development would brighten the cup.").format(v=_c(ACC, f"{avg:.0f}%")))
            else:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Development ratios sit around {v}, in the usual window.").format(
                        v=_c(ACC, f"{avg:.0f}%")))

        # Accidents de RoR (crash / flick) en développement.
        cf = []
        for c in (c for c in self._multi_curves if c.get('data')):
            lab = self._detect_crash_flick(c['data'], c.get('deltabt') or [])
            if lab:
                cf.append((c['title'], lab))
        if not cf:
            parts.append(_c(OK, QApplication.translate("tilauscope_beancave",
                "All roasts keep a clean, declining RoR through development.")))
        else:
            kinds = set()
            for _, lab in cf:
                if 'crash' in lab:
                    kinds.add(QApplication.translate("tilauscope_beancave", "crash"))
                if 'flick' in lab:
                    kinds.add(QApplication.translate("tilauscope_beancave", "flick"))
            kind = " / ".join(sorted(kinds))
            if len(cf) == 1:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Roast {name} shows a RoR {kind} after first crack — watch for "
                    "stalled, uneven development.").format(
                        name=cf[0][0][:22], kind=_c(WARN, kind)))
            else:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "{k} of {n} roasts show a RoR {kind} after first crack — watch for "
                    "stalled, uneven development.").format(
                        k=len(cf), n=n, kind=_c(WARN, kind)))
        return " ".join(parts)

    def _set_stats_view(self, multi: bool) -> None:
        """Bascule l'onglet Advanced Stats : vue HTML (mono) ↔ dot plot (multi)."""
        if hasattr(self, 'stats_scroll'):
            self.stats_scroll.setVisible(not multi)
        if hasattr(self, 'stats_multi_widget'):
            self.stats_multi_widget.setVisible(multi)

    # Métriques du dot plot multi : (label, clé, formateur de valeur)
    def _render_multi_dotplot(self) -> None:
        """Dot plot comparatif (Advanced Stats multi) : une ligne par métrique,
        un point par roast (sa teinte), référence en anneau. Échelle propre par
        ligne. Remplace l'ancien tableau, trop chargé pour un amateur."""
        metrics = [self._extract_roast_metrics(c['data'])
                   for c in self._multi_curves if c.get('data')]
        fig = self.stats_dot_fig
        fig.clear()
        fig.set_facecolor(_PLOT_PALETTE['background'])
        if not metrics:
            self.stats_dot_canvas.draw_idle()
            self.stats_summary.setText("")
            return
        palette = self._make_multi_palette(len(metrics))
        ax = fig.add_subplot(111)
        ax.set_facecolor(_PLOT_PALETTE['background'])

        def _t(s):
            return self.format_seconds(s or 0)
        # Réutilise les sources de traduction existantes (artisan_fr.ts) :
        # Total/Drying/Maillard/DTR/Weight loss → [tilauscope_beancave],
        # Development → [Label].
        rows = [
            (QApplication.translate("tilauscope_beancave", "Total"),       'total_s',    _t),
            (QApplication.translate("tilauscope_beancave", "Drying"),      'drying_s',   _t),
            (QApplication.translate("tilauscope_beancave", "Maillard"),    'maillard_s', _t),
            (QApplication.translate("Label", "Development"),               'dev_s',      _t),
            (QApplication.translate("tilauscope_beancave", "DTR") + " %",  'dtr',     lambda v: f"{v:.0f}%"),
            (QApplication.translate("tilauscope_beancave", "Drop BT"),     'drop_bt', lambda v: f"{v:.0f}°"),
            (QApplication.translate("tilauscope_beancave", "Weight loss") + " %", 'wl', lambda v: f"{v:.0f}%"),
        ]
        # Roast area (AUC) — added only when the roasts carry the data. The dot
        # plot normalises each row by its own min/max, so AUC is shown purely as
        # a consistency spread (the absolute value depends on the AUCbase setting
        # and is not roaster-comparable). Kept to two rows to stay uncluttered.
        _auc_fmt = lambda v: f"{v:.0f}"
        for label, key in ((QApplication.translate("tilauscope_beancave", "Area total"),       'auc_total'),
                           (QApplication.translate("tilauscope_beancave", "Area development"), 'auc_fin')):
            if any(m.get(key) is not None for m in metrics):
                rows.append((label, key, _auc_fmt))
        nrows = len(rows)
        from matplotlib.colors import to_hex, to_rgba
        muted = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 0.6), keep_alpha=True)
        ylabels = []
        for r_idx, (label, key, fmt) in enumerate(rows):
            y = nrows - 1 - r_idx
            ylabels.append(label)
            vals = [(j, m.get(key)) for j, m in enumerate(metrics)]
            nums = [v for _, v in vals if v is not None]
            if not nums:
                continue
            lo, hi = min(nums), max(nums)
            span = hi - lo
            ax.plot([0.12, 0.88], [y, y], color=_PLOT_PALETTE['grid'], lw=1, alpha=0.5, zorder=1)
            ax.text(0.10, y, fmt(lo), ha='right', va='center', fontsize=_FS_TICK - 1, color=muted)
            ax.text(0.90, y, fmt(hi), ha='left',  va='center', fontsize=_FS_TICK - 1, color=muted)
            for j, v in vals:
                if v is None:
                    continue
                norm = (v - lo) / span if span > 0 else 0.5
                x = 0.12 + norm * 0.76
                is_ref = (j == 0)
                ax.scatter([x], [y], s=95 if is_ref else 55, zorder=5,
                           facecolors=palette[j][0],
                           edgecolors=THEME['TEXT'] if is_ref else palette[j][0],
                           linewidths=1.7 if is_ref else 0)
        ax.set_xlim(0, 1)
        ax.set_ylim(-0.6, nrows - 0.4)
        ax.set_xticks([])
        ax.set_yticks(range(nrows))
        ax.set_yticklabels(list(reversed(ylabels)), fontsize=_FS_TICK,
                           color=_PLOT_PALETTE['ylabel'])
        ax.tick_params(axis='y', length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(QApplication.translate("tilauscope_beancave",
                     "Comparison — ◉ = reference roast"),
                     fontsize=_FS_AXIS, color=_PLOT_PALETTE['title'])
        self.stats_dot_canvas.draw_idle()

        # Mini-résumé : analyse en clair + écarts notables vs référence.
        analysis = self._generate_multi_analysis(metrics)
        advices = self._generate_multi_coach_advice(metrics)
        html = f'<div style="color:{THEME["TEXT"]};font-size:12px;font-family:sans-serif;">'
        if analysis:
            html += (f'<b style="color:{THEME["ACCENT"]};">' +
                     QApplication.translate("tilauscope_beancave", "Analysis") +
                     f'</b><p style="margin:3px 0 8px 0;line-height:1.4;">{analysis}</p>')
        if advices:
            items = ''.join(f'<li style="margin-bottom:3px;">{a}</li>' for a in advices)
            html += (f'<b style="color:{THEME["ACCENT"]};">' +
                     QApplication.translate("tilauscope_beancave", "Notable differences") +
                     f'</b><ul style="margin:4px 0 0 0;padding-left:18px;">{items}</ul>')
        html += '</div>'
        self.stats_summary.setText(html if (analysis or advices) else "")
