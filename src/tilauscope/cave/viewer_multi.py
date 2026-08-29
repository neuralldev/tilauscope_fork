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

import numpy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # pylint: disable=unused-import

#import matplotlib.pyplot as plt




from PyQt6.QtCore import (pyqtSlot, QPoint) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtWidgets import (QApplication) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import (THEME, RoastingPhase, estimate_ror_dt, find_turning_point_index, find_flicks_crashes)
from tilauscope.cave.common import (
    _logd, _PLOT_PALETTE, _FS_AXIS, _FS_TICK, _FS_EVENT, _FS_LEGEND)


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

    # Jalons HiBean affichés en multi-comparaison (ordre d'affichage)
    _MULTI_MILESTONES: tuple = ('CHARGE', 'TP', 'DRY END', 'FC start', 'DROP')

    def _multi_milestones(self, data: dict) -> dict:
        """Renvoie {label: (x_min, bt_temp, t_sec)} pour CHARGE/TP/DRY END/FC start/DROP.

        x_min/t_sec sont relatifs au CHARGE. TP est recalculé (min BT entre CHARGE
        et DRY END) car Artisan ne le stocke pas dans timeindex.
        """
        if not data:
            return {}
        timex = data.get('timex', [])
        temp2 = data.get('temp2', [])
        ti = (list(data.get('timeindex', [])) + [-1] * 8)[:8]
        charge = ti[RoastingPhase.CHARGE]
        if charge < 0 or charge >= len(timex):
            return {}
        charge_t = timex[charge]
        out: dict = {}

        def _put(label: str, idx: int) -> None:
            if idx is None or idx <= 0 or idx >= len(timex) or idx >= len(temp2):
                return
            if temp2[idx] is None:
                return
            t = timex[idx] - charge_t
            out[label] = (t / 60.0, temp2[idx], t)

        # CHARGE — l'index peut légitimement valoir 0
        if charge < len(temp2) and temp2[charge] is not None:
            out['CHARGE'] = (0.0, temp2[charge], 0.0)
        # TP : minimum de BT entre CHARGE et DRY END (fenêtre 2 min par défaut)
        dryend = ti[RoastingPhase.DRYEND]
        tp_hi = dryend if dryend > charge else min(len(temp2), charge + 120)
        seg = [(k, temp2[k]) for k in range(charge, tp_hi)
               if k < len(temp2) and temp2[k] is not None]
        if seg:
            tp_idx = min(seg, key=lambda kv: kv[1])[0]
            t = timex[tp_idx] - charge_t
            out['TP'] = (t / 60.0, temp2[tp_idx], t)
        _put('DRY END', dryend)
        _put('FC start', ti[RoastingPhase.FCSTART])
        _put('DROP', ti[RoastingPhase.DROP])
        return out

    def _draw_multi_event_markers(self, ax1, palette: list, mode: str) -> None:
        """Bandeau de jalons : lignes-guides + boîtes en haut sur la roast de
        référence (curve[0]). À 3+ roasts : LABEL / temp / temps uniquement (épuré).
        À exactement 2 roasts : on ajoute les Δt/ΔT vs la courbe comparée, là où
        c'est lisible — l'info delta reste ainsi près de la courbe."""
        ref_data = self._multi_curves[0].get('data')
        ref_ms = self._multi_milestones(ref_data)
        if not ref_ms:
            return
        n = len(self._multi_curves)
        # À 2 roasts : jalons de la courbe comparée pour calculer les écarts.
        other_ms = self._multi_milestones(self._multi_curves[1].get('data')) if n == 2 else {}
        ref_col = palette[0][0]
        bbox_style = dict(boxstyle="round,pad=0.3", fc="black", alpha=0.82,
                          ec=ref_col, lw=0.8)
        drop_x = ref_ms.get('DROP', (0.0,))[0] or 1.0
        # Boîtes ancrées juste au-dessus de leur point sur la courbe (offset en
        # points) : elles suivent la courbe quel que soit le zoom, reliées par la
        # ligne-guide. Quinconce vertical pour éviter le chevauchement des jalons
        # proches (FC start / DROP) ; décalage horizontal selon le côté.
        dy_rows = (62, 24)
        for k, label in enumerate(self._MULTI_MILESTONES):
            if label not in ref_ms:
                continue
            x_min, bt, t_sec = ref_ms[label]
            ax1.axvline(x=x_min, color='gray', linestyle=':', linewidth=0.7, alpha=0.45, zorder=2)
            ax1.plot(x_min, bt, marker='o', color=ref_col, markersize=4, zorder=8)
            lines = [label, f"{bt:.1f}°{mode}", self.format_seconds(t_sec)]
            if n == 2 and label in other_ms:
                _, obt, ot_sec = other_ms[label]
                lines.append(f"Δt {t_sec - ot_sec:+.0f}s")   # réf − comparée
                lines.append(f"ΔT {bt - obt:+.1f}°")
            right = x_min >= 0.78 * drop_x
            ha = 'right' if right else 'left'
            dx = -6 if right else 6
            ax1.annotate("\n".join(lines), (x_min, bt),
                         textcoords="offset points", xytext=(dx, dy_rows[k % 2]),
                         ha=ha, va='bottom', fontsize=_FS_EVENT, color='white',
                         bbox=bbox_style, zorder=9)

    # Couleurs de phase désaturées (frais → chaud), indépendantes des teintes roast
    _PHASE_COLORS: tuple = ("#6E94C2", "#C79356", "#B06E7E")  # Drying / Maillard / Dev

    def _draw_phase_ribbon(self, ax, palette: list) -> None:
        """Ruban d'équilibre des phases : une barre horizontale empilée par roast
        (Séchage / Maillard / Développement en %), nom du roast coloré + durée à
        gauche. Le % de développement EST le DTR."""
        bg_color = _PLOT_PALETTE["background"]
        ax.set_facecolor(bg_color)
        rows = [(i, c, self._extract_roast_metrics(c['data']))
                for i, c in enumerate(self._multi_curves) if c.get('data')]
        if not rows:
            ax.axis('off')
            return
        nrows = len(rows)
        labels, label_colors = [], []
        dry_c, mai_c, dev_c = self._PHASE_COLORS
        _bar_h = 0.72
        # Place utile du ruban en points, sur les deux axes : l'axe x couvre
        # 0-100 %, une largeur de texte se convertit donc en % de ruban. La
        # hauteur d'une barre borne la taille de police posable dessus.
        try:
            _fig = ax.figure
            _pos = ax.get_position()
            # 0.90 : la mise en page contrainte peut encore rétrécir l'axe pour
            # loger les noms de roast à gauche — on sous-estime volontairement.
            _ax_pts = _pos.width * _fig.get_figwidth() * 72.0 * 0.90
            _bar_pts = (_pos.height * _fig.get_figheight() * 72.0
                        / (nrows + 0.2) * _bar_h)
        except Exception:
            _ax_pts, _bar_pts = 430.0, 10.0
        # Plus grande taille tenant dans la hauteur de barre ; None si aucune.
        _fs = next((f for f in range(_FS_TICK - 1, 5, -1) if f * 1.15 <= _bar_pts), None)
        def _fits(text: str, width_pct: float, fontsize: int) -> bool:
            # 0.60 em par caractère : approximation large pour une police
            # proportionnelle, plus 8 % de marge pour ne pas coller aux bords.
            need_pts = len(text) * 0.60 * fontsize * 1.08
            return _ax_pts > 0 and (need_pts / _ax_pts * 100.0) <= width_pct
        for row_idx, (i, curve, m) in enumerate(rows):
            y = nrows - 1 - row_idx  # première courbe (référence) en haut
            dry = m.get('drying_pct') or 0.0
            mai = m.get('maillard_pct') or 0.0
            dev = m.get('dtr') or 0.0
            s = dry + mai + dev
            if s > 0:
                dry, mai, dev = dry * 100 / s, mai * 100 / s, dev * 100 / s
            for val, left, lab, col in (
                (dry, 0.0, QApplication.translate("tilauscope_beancave", "Drying"), dry_c),
                (mai, dry, QApplication.translate("tilauscope_beancave", "Maillard"), mai_c),
                (dev, dry + mai, QApplication.translate("tilauscope_beancave", "Dev"), dev_c),
            ):
                ax.barh(y, val, left=left, height=_bar_h, color=col,
                        edgecolor=bg_color, linewidth=1.2, alpha=0.92)
                # Une décimale : deux roasts proches (49,5 % vs 50,2 %) ne doivent
                # pas s'afficher avec le même chiffre. Repli sur le seul
                # pourcentage, puis rien du tout, si le segment est trop étroit.
                if _fs is None:
                    continue
                for _txt, _size in ((f"{lab} {val:.1f}%", _fs),
                                    (f"{val:.1f}%", _fs),
                                    (f"{val:.1f}%", _fs - 1)):
                    if _size >= 6 and _fits(_txt, val, _size):
                        ax.text(left + val / 2, y, _txt, ha='center', va='center',
                                fontsize=_size, color=THEME['BG'])
                        break
            short = (curve['title'][:16] + '…') if len(curve['title']) > 16 else curve['title']
            labels.append(f"{short} · {m.get('total_fmt', '')}")
            label_colors.append(palette[i][0])
        ax.set_xlim(0, 100)
        ax.set_ylim(-0.6, nrows - 0.4)
        ax.set_yticks(range(nrows))
        # y-ticks dans l'ordre d'affichage (haut → bas) : on inverse les labels
        ax.set_yticklabels(list(reversed(labels)), fontsize=_FS_TICK)
        for tick, col in zip(ax.get_yticklabels(), reversed(label_colors)):
            tick.set_color(col)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.tick_params(axis='x', colors=_PLOT_PALETTE['xlabel'], labelsize=_FS_TICK - 1)
        ax.tick_params(axis='y', length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)

    def _draw_residual_strip(self, ax, mode: str) -> None:
        """Bandeau résiduel : écart de BT de chaque roast à la référence (ΔBT),
        centré sur 0. Interpolé sur la grille x de la référence (temps brut, ou
        temps warpé en vue Aligné → écart de forme pur). Partage l'axe x du graphe."""
        bg_color = _PLOT_PALETTE["background"]
        ax.set_facecolor(bg_color)
        if len(self._multi_series) < 2:
            ax.axis('off')
            return
        ref = self._multi_series[0]
        ref_x = numpy.asarray(ref['x'], dtype=float)
        ref_bt = numpy.asarray([v if v is not None else numpy.nan for v in ref['bt']], dtype=float)
        if ref_x.size < 2:
            ax.axis('off')
            return
        ax.axhline(0, color=ref['bt_col'], linewidth=1.3, alpha=0.9, zorder=3)  # référence
        max_abs = 5.0
        for s in self._multi_series[1:]:
            ox = numpy.asarray(s['x'], dtype=float)
            oy = numpy.asarray([v if v is not None else numpy.nan for v in s['bt']], dtype=float)
            valid = ~numpy.isnan(oy)
            if valid.sum() < 2:
                continue
            yi = numpy.interp(ref_x, ox[valid], oy[valid], left=numpy.nan, right=numpy.nan)
            resid = yi - ref_bt
            ax.plot(ref_x, resid, color=s['bt_col'], linewidth=1.0, alpha=0.85, zorder=4)
            finite = resid[~numpy.isnan(resid)]
            if finite.size:
                max_abs = max(max_abs, float(numpy.nanmax(numpy.abs(finite))))
        lim = numpy.ceil(max_abs / 5.0) * 5.0
        ax.set_ylim(-lim, lim)
        from matplotlib.colors import to_hex, to_rgba
        ylab = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 1.0), keep_alpha=True)
        ax.set_ylabel("Δ" + QApplication.translate("Label", "BT") + f" (°{mode})",
                      fontsize=_FS_TICK, color=ylab)
        ax.tick_params(axis='both', colors=ylab, labelsize=_FS_TICK - 1)
        ax.grid(True, alpha=0.2, color=_PLOT_PALETTE['grid'])
        for sp in ax.spines.values():
            sp.set_color(_PLOT_PALETTE['grid'])
        ax.set_xlabel(QApplication.translate("tilauscope_beancave", "Time (min)"),
                      fontsize=_FS_AXIS, color=_PLOT_PALETTE['xlabel'])

    @pyqtSlot(bool)
    def _on_consistency_toggled(self, checked: bool) -> None:
        """Active la vue Consistance (exclusive avec Aligné) et redessine."""
        if checked:
            self.align_button.blockSignals(True)
            self.align_button.setChecked(False)
            self.align_button.blockSignals(False)
            self._multi_view_mode = 'consistency'
        else:
            self._multi_view_mode = 'align' if self.align_button.isChecked() else 'overlay'
        if self._multi_curves:
            self._plot_multi_curves()

    @pyqtSlot(bool)
    def _on_align_toggled(self, checked: bool) -> None:
        """Active la vue Aligné / time-warp (exclusive avec Consistance) et redessine."""
        if checked:
            self.consistency_button.blockSignals(True)
            self.consistency_button.setChecked(False)
            self.consistency_button.blockSignals(False)
            self._multi_view_mode = 'align'
        else:
            self._multi_view_mode = 'consistency' if self.consistency_button.isChecked() else 'overlay'
        if self._multi_curves:
            self._plot_multi_curves()

    def _plot_multi_curves(self) -> None:
        """Trace la superposition de BT, ET et DeltaBT pour toutes les courbes multi."""
        if not self._multi_curves:
            return

        n = len(self._multi_curves)
        palette = self._make_multi_palette(n)

        bg_color = _PLOT_PALETTE["background"]
        mode = self._multi_curves[0]['data'].get('mode', 'C') if self._multi_curves[0]['data'] else 'C'

        from matplotlib.colors import to_hex, to_rgba
        ylabel_alpha_color = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 1.0), keep_alpha=True)

        self.fig.clear()
        # Deux lignes empilées : graphe principal (BT/ET/RoR) + ruban de phases.
        # Hauteur du ruban proportionnelle au nombre de roasts (sinon les barres
        # s'écrasent et mordent la légende dès 4-5 courbes) : chaque ligne doit
        # rester plus haute que l'étiquette posée dessus.
        n_data = sum(1 for c in self._multi_curves if c.get('data')) or 1
        ribbon_h = 0.75 + 0.62 * n_data
        # 4 lignes : graphe / résiduel ΔBT / ruban / bande-légende. Le résiduel
        # partage l'axe x du graphe (l'axe temps vit donc sur le résiduel). La
        # légende a sa propre cellule réservée → pas de chevauchement.
        gs = self.fig.add_gridspec(4, 1, height_ratios=[7.0, 1.5, ribbon_h, 0.5], hspace=0.14)
        ax1 = self.fig.add_subplot(gs[0])
        ax_resid = self.fig.add_subplot(gs[1], sharex=ax1)
        ax_ribbon = self.fig.add_subplot(gs[2])
        ax_legend = self.fig.add_subplot(gs[3])
        ax_legend.axis('off')
        ax_ror = ax1.twinx()
        self.ax1 = ax1
        self.ax2 = None        # pas de slider panel en mode multi
        self.ax_hoovers = ax_ror

        self.fig.set_facecolor(bg_color)
        ax1.set_facecolor(bg_color)
        ax_ror.set_facecolor(bg_color)
        for spine in ax1.spines.values():
            spine.set_color(_PLOT_PALETTE['grid'])
        ax1.tick_params(axis='both', colors=ylabel_alpha_color, labelsize=_FS_TICK)
        ax_ror.tick_params(axis='y',  colors=ylabel_alpha_color, labelsize=_FS_TICK)

        # Modes de vue (n >= 2). consistency : réf + bande min–max. align : time-warp
        # (jalons alignés sur ceux de la référence, BT seul).
        view = getattr(self, '_multi_view_mode', 'overlay')
        consistency = (view == 'consistency' and n >= 2)
        align = (view == 'align' and n >= 2)
        # Jalons de la référence (1ʳᵉ courbe avec données) pour le time-warp.
        ref_warp_ms = {}
        if align:
            for c in self._multi_curves:
                if c.get('data'):
                    ref_warp_ms = self._multi_milestones(c['data'])
                    break

        # Stocker les séries pour hover
        self._multi_series: list[dict] = []

        for i, curve in enumerate(self._multi_curves):
            data = curve['data']
            if not data:
                continue
            bt_col, et_col, dbt_col, ror_col = palette[i]
            timex     = data.get('timex', [])
            temp2     = data.get('temp2', [])
            temp1     = data.get('temp1', [])
            timeindex = data.get('timeindex', [])
            deltabt   = curve['deltabt'] or []

            if not timex or not temp2 or len(timeindex) < 7:
                continue

            charge = timeindex[0]
            drop   = timeindex[6]
            if charge < 0:
                continue
            charge_start = max(0, charge - 10)
            drop_end     = min(len(timex), drop + 10) if drop > 0 else len(timex)

            x_vals = [(t - timex[charge]) / 60.0 for t in timex[charge_start:drop_end]]
            y_bt   = temp2[charge_start:drop_end]
            y_et   = temp1[charge_start:drop_end] if temp1 else []
            y_ror  = [v if v is not None else 0.0 for v in deltabt[charge_start:drop_end]] if deltabt else []

            # Time-warp : remappe le temps de ce roast pour aligner ses jalons sur
            # ceux de la référence (interp linéaire par morceaux). Identité pour la réf.
            plot_x = x_vals
            if align and ref_warp_ms:
                this_ms = self._multi_milestones(data)
                shared = [l for l in self._MULTI_MILESTONES if l in this_ms and l in ref_warp_ms]
                if len(shared) >= 2:
                    xp = [this_ms[l][2] for l in shared]       # temps jalons de ce roast (s)
                    fp = [ref_warp_ms[l][2] for l in shared]   # temps jalons de la référence (s)
                    t_sec = [(t - timex[charge]) for t in timex[charge_start:drop_end]]
                    plot_x = list(numpy.interp(t_sec, xp, fp) / 60.0)

            is_ref = (i == 0)
            if align:
                # Vue alignée : BT seul (le warp fausse l'échelle du RoR).
                ax1.plot(plot_x, y_bt, color=bt_col, zorder=6 if is_ref else 4,
                         linewidth=1.5 if is_ref else 1.0, alpha=1.0 if is_ref else 0.5)
            elif not consistency or is_ref:
                # Type encodé par le style : BT plein, RoR tireté, ET pointillé fin.
                # Réf pleine et un peu plus épaisse ; autres atténués.
                bt_lw     = 1.5 if is_ref else 1.0
                bt_alpha  = 1.0 if is_ref else 0.45
                ror_alpha = 0.85 if is_ref else 0.40
                et_alpha  = 0.45 if is_ref else 0.22
                ax1.plot(x_vals, y_bt, color=bt_col, linewidth=bt_lw, alpha=bt_alpha,
                         zorder=6 if is_ref else 4)
                if y_et:
                    ax1.plot(x_vals, y_et, color=et_col, linewidth=0.8, linestyle=':', alpha=et_alpha)
                if y_ror:
                    ax_ror.plot(x_vals, y_ror, color=ror_col, linewidth=1.0, linestyle='--', alpha=ror_alpha)

            self._multi_series.append({
                'title':    curve['title'],
                'x':        plot_x,
                'bt':       y_bt,
                'et':       y_et,
                'ror':      y_ror,
                'bt_col':   bt_col,
                'et_col':   et_col,
                'dbt_col':  dbt_col,
                'ror_col':  ror_col,
                'timex':    timex,
                'timeindex': timeindex,
                'mode':     mode,
            })

        # ── Bande de consistance : enveloppe min–max sur TOUS les roasts ──────
        # (référence incluse) interpolés sur la grille temps de la référence —
        # sinon, à 2 roasts, min==max et la bande serait invisible. Tracée pour
        # BT (ax1) et RoR (ax_ror), en teinte réf, faible alpha.
        if consistency and len(self._multi_series) >= 2:
            ref_s = self._multi_series[0]
            ref_x = numpy.asarray(ref_s['x'], dtype=float)
            band_col = ref_s['bt_col']

            def _draw_band(key: str, axis) -> None:
                stack = []
                for s in self._multi_series:  # inclut la référence → enveloppe complète
                    ox = numpy.asarray(s['x'], dtype=float)
                    oy = numpy.asarray([v if v is not None else numpy.nan
                                        for v in (s.get(key) or [])], dtype=float)
                    valid = ~numpy.isnan(oy)
                    if valid.sum() < 2:
                        continue
                    stack.append(numpy.interp(ref_x, ox[valid], oy[valid],
                                              left=numpy.nan, right=numpy.nan))
                if not stack:
                    return
                arr = numpy.vstack(stack)
                lo, hi = numpy.nanmin(arr, axis=0), numpy.nanmax(arr, axis=0)
                m = ~(numpy.isnan(lo) | numpy.isnan(hi))
                axis.fill_between(ref_x[m], lo[m], hi[m], color=band_col,
                                  alpha=0.16, linewidth=0, zorder=2)

            if ref_x.size:
                _draw_band('bt', ax1)
                _draw_band('ror', ax_ror)

        ax1.set_facecolor(bg_color)
        # Échelle Y adaptative sur l'ensemble des courbes (BT + ET), ~10–20° d'air
        # au-dessus du pic le plus chaud. Fallback 0–300 si aucune donnée.
        all_temps = [
            v for s in self._multi_series
            for v in ((s['bt'] or []) + (s['et'] or []))
            if v is not None
        ]
        if all_temps:
            t_min = min(all_temps)
            t_max = max(all_temps)
            y_lo = max(0, int(numpy.floor((t_min - 10) / 10.0) * 10))
            # Headroom plus large qu'en mono : laisse la place aux boîtes
            # d'événement ancrées en haut de l'axe (lignes-guides HiBean).
            # À 2 roasts les boîtes portent les Δt/ΔT (5 lignes) → un peu plus d'air.
            head = 30 if len(self._multi_curves) == 2 else 18
            y_hi = int(numpy.ceil((t_max + head) / 10.0) * 10)
            ax1.set_ylim(y_lo, y_hi)
        else:
            ax1.set_ylim(0, 300)
        ax1.set_ylabel(QApplication.translate("Label", "Temp") + f" (°{mode})",
                       fontsize=_FS_AXIS, color=_PLOT_PALETTE['ylabel'])
        # L'axe temps vit sur le résiduel (sous le graphe) → on masque celui d'ax1.
        ax1.tick_params(axis='x', labelbottom=False)
        ax1.grid(True, alpha=0.25, color=_PLOT_PALETTE['grid'])
        # Échelle RoR : axe strictement positif — plancher fixe à 0.
        # Les valeurs négatives restent dans les données (hover tooltip) mais
        # ne font jamais descendre l'axe en dessous de 0.
        if align:
            # Vue alignée : pas de RoR tracé → on masque l'axe de droite (vide).
            ax_ror.set_yticks([])
            ax_ror.set_ylabel('')
        else:
            all_ror = [v for s in self._multi_series for v in (s['ror'] or []) if v is not None]
            if all_ror:
                ror_max = max(max(all_ror), 30)
                ax_ror.set_ylim(0, ror_max + 2)
            else:
                ax_ror.set_ylim(0, 30)
            ax_ror.set_ylabel(QApplication.translate("Label", "RoR") + f" (°{mode}/min)",
                              fontsize=_FS_AXIS, color=ylabel_alpha_color)

        # ── Marqueurs d'événement façon HiBean (lignes-guides + boîtes + Δ) ──
        try:
            self._draw_multi_event_markers(ax1, palette, mode)
        except Exception as e:
            _logd.error(f"_draw_multi_event_markers error: {e}")

        # ── Bandeau résiduel ΔBT vs référence (sous le graphe) ───────────────
        try:
            self._draw_residual_strip(ax_resid, mode)
        except Exception as e:
            _logd.error(f"_draw_residual_strip error: {e}")
            ax_resid.axis('off')

        # ── Ruban d'équilibre des phases (sous le graphe) ────────────────────
        # L'identité des roasts (nom + couleur) est portée par le ruban : la
        # légende ne garde donc que le rappel de style de trait.
        from matplotlib.lines import Line2D as _L2D
        try:
            self._draw_phase_ribbon(ax_ribbon, palette)
        except Exception as e:
            _logd.error(f"_draw_phase_ribbon error: {e}")
            ax_ribbon.axis('off')

        # Rappel de style de trait, ancré sous le ruban. En vue alignée, seul BT
        # est tracé → on n'affiche que BT.
        style_handles = [_L2D([0], [0], color=THEME['TEXT'], linewidth=2,
                               label=QApplication.translate("Label", "BT"))]
        if not align:
            style_handles += [
                _L2D([0], [0], color=THEME['TEXT'], linewidth=1.4, linestyle='--',
                     label=QApplication.translate("Label", "RoR")),
                _L2D([0], [0], color=THEME['TEXT'], linewidth=0.9, linestyle=':',
                     label=QApplication.translate("Label", "ET")),
            ]
        ax_legend.legend(
            handles=style_handles,
            loc='center',
            ncol=len(style_handles),
            fontsize=_FS_LEGEND,
            facecolor=THEME['BG'],
            edgecolor=THEME['SURFACE1'],
            labelcolor='white',
            framealpha=0.85,
        )

        # Marqueurs hover — BT + ET sur ax1, RoR sur ax_ror
        # Tous taille 7. Courbe la plus proche : markerfacecolor rempli.
        from matplotlib.lines import Line2D as _Line2D
        self._multi_markers_bt  = []
        self._multi_markers_et  = []
        self._multi_markers_ror = []
        for series in self._multi_series:
            def _mk(col, ax):
                m = _Line2D([0],[0], marker='o', color=col, markersize=7,
                            markerfacecolor='none', markeredgewidth=1.8,
                            linestyle='none', visible=False, zorder=7)
                ax.add_line(m)
                return m
            self._multi_markers_bt.append( _mk(series['bt_col'],  ax1))
            self._multi_markers_et.append( _mk(series['et_col'],  ax1))
            self._multi_markers_ror.append(_mk(series['ror_col'], ax_ror))
        # alias pour compatibilité on_plot_leave
        self._multi_markers = self._multi_markers_bt + self._multi_markers_et + self._multi_markers_ror

        self._reconnect_hover()
        self.canvas.mpl_connect('figure_leave_event', self.on_plot_leave)
        self.last_plot_data = self._multi_curves[0]['data'] if self._multi_curves else None
        self.canvas.draw_idle()
        # Onglet Advanced Stats : dot plot comparatif + mini-résumé (pas le tableau).
        try:
            self._set_stats_view(True)
            self._render_multi_dotplot()
            _mode_label = {
                'overlay':     QApplication.translate("tilauscope_beancave", "Overlay"),
                'consistency': QApplication.translate("tilauscope_beancave", "Consistency"),
                'align':       QApplication.translate("tilauscope_beancave", "Aligned"),
            }.get(view, QApplication.translate("tilauscope_beancave", "Overlay"))
            self.roast_plot_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "Comparing {n} roasts · {mode} view — select one to return to single view."
                ).format(n=len(self._multi_curves), mode=_mode_label))
        except Exception as e:
            _logd.error(f"_multi_stats_html error: {e}")

    def _on_multi_hover(self, event) -> None:
        """Hover en mode multi : identifie la courbe BT la plus proche du curseur."""
        if not hasattr(self, '_multi_series') or not self._multi_series:
            return
        if event.inaxes not in (self.ax1, self.ax_hoovers):
            self._hover_tooltip.hide()
            return

        x_data = event.xdata
        if x_data is None:
            self._hover_tooltip.hide()
            return

        # Mode actif : restreint le survol aux courbes réellement tracées.
        view = getattr(self, '_multi_view_mode', 'overlay')
        consistency = (view == 'consistency')
        aligned = (view == 'align')
        # En Consistance seule la référence est tracée → on ne survole qu'elle.
        cand_idx = [0] if (consistency and self._multi_series) else list(range(len(self._multi_series)))

        # Trouver la série dont le BT est le plus proche du y curseur
        y_data = event.ydata
        best_series = None
        best_dist   = float('inf')
        best_t_idx  = 0

        for i in cand_idx:
            series = self._multi_series[i]
            if not series['x'] or not series['bt']:
                continue
            t_idx = min(range(len(series['x'])),
                        key=lambda k, x=x_data: abs(series['x'][k] - x))
            if t_idx < len(series['bt']):
                dist = abs(series['bt'][t_idx] - (y_data or 0))
                if dist < best_dist:
                    best_dist   = dist
                    best_series = series
                    best_t_idx  = t_idx

        if best_series is None:
            self._hover_tooltip.hide()
            # Cacher tous les marqueurs
            if hasattr(self, '_multi_markers'):
                for m in self._multi_markers:
                    m.set_visible(False)
            self.canvas.draw_idle()
            return

        # Marqueurs adaptés au mode : réf seule en Consistance, BT seul en Aligné.
        has_markers = (hasattr(self, '_multi_markers_bt') and
                       len(self._multi_markers_bt) == len(self._multi_series))
        if has_markers:
            for idx, (series, m_bt, m_et, m_ror) in enumerate(zip(
                    self._multi_series,
                    self._multi_markers_bt,
                    self._multi_markers_et,
                    self._multi_markers_ror)):
                if (idx not in cand_idx) or not series['x']:
                    m_bt.set_visible(False)
                    m_et.set_visible(False)
                    m_ror.set_visible(False)
                    continue
                t_idx_m = min(range(len(series['x'])),
                              key=lambda k, x=x_data: abs(series['x'][k] - x))
                is_best = (series is best_series)
                ew = 2.2 if is_best else 1.5
                # BT (toujours tracé dans tous les modes)
                if t_idx_m < len(series['bt']) and series['bt'][t_idx_m] is not None:
                    m_bt.set_data([series['x'][t_idx_m]], [series['bt'][t_idx_m]])
                    m_bt.set_markerfacecolor(series['bt_col'] if is_best else 'none')
                    m_bt.set_markeredgewidth(ew)
                    m_bt.set_visible(True)
                else:
                    m_bt.set_visible(False)
                # ET / RoR : masqués en Aligné (non tracés)
                if (not aligned) and t_idx_m < len(series['et']) and series['et'][t_idx_m] is not None:
                    m_et.set_data([series['x'][t_idx_m]], [series['et'][t_idx_m]])
                    m_et.set_markerfacecolor(series['et_col'] if is_best else 'none')
                    m_et.set_markeredgewidth(ew)
                    m_et.set_visible(True)
                else:
                    m_et.set_visible(False)
                if (not aligned) and t_idx_m < len(series['ror']) and series['ror'][t_idx_m] is not None:
                    m_ror.set_data([series['x'][t_idx_m]], [series['ror'][t_idx_m]])
                    m_ror.set_markerfacecolor(series['ror_col'] if is_best else 'none')
                    m_ror.set_markeredgewidth(ew)
                    m_ror.set_visible(True)
                else:
                    m_ror.set_visible(False)
            self.canvas.draw_idle()

        mode    = best_series['mode']
        x_vals  = best_series['x']
        time_s  = x_vals[best_t_idx] * 60.0
        time_str = self.format_seconds(time_s)

        bt_val  = best_series['bt'][best_t_idx]  if best_t_idx < len(best_series['bt'])  else None
        et_val  = best_series['et'][best_t_idx]  if best_t_idx < len(best_series['et'])  else None
        dbt_val = best_series['ror'][best_t_idx] if best_t_idx < len(best_series['ror']) else None

        def dot(c): return f'<span style="color:{c}; font-size:14px;">&#9632;</span> '

        _time_lbl = QApplication.translate("Label", "Time")
        if aligned:
            _time_lbl = QApplication.translate("tilauscope_beancave", "Aligned time")
        lines = [
            f'<b style="color:{THEME["TEXT"]};">{best_series["title"]}</b>',
            f'<b style="color:{THEME["TEXT"]};">{_time_lbl} : {time_str}</b>',
        ]
        if bt_val is not None: lines.append(f'{dot(best_series["bt_col"])}BT : {bt_val:.1f}°{mode}')
        # ET / RoR seulement si réellement tracés (pas en Aligné).
        if not aligned:
            if et_val  is not None: lines.append(f'{dot(best_series["et_col"])}ET : {et_val:.1f}°{mode}')
            if dbt_val is not None: lines.append(f'{dot(best_series["ror_col"])}RoR : {dbt_val:.1f}°{mode}/min')
        # En Consistance : étendue BT (min–max) de tous les roasts à cet instant.
        if consistency and len(self._multi_series) >= 2:
            bt_at = []
            for s in self._multi_series:
                if not s['x'] or not s['bt']:
                    continue
                k = min(range(len(s['x'])), key=lambda j, x=x_data: abs(s['x'][j] - x))
                if k < len(s['bt']) and s['bt'][k] is not None:
                    bt_at.append(s['bt'][k])
            if len(bt_at) >= 2:
                _spread_lbl = QApplication.translate("tilauscope_beancave", "BT spread")
                lines.append(f'<span style="color:{THEME["OVERLAY2"]};">{_spread_lbl} : '
                             f'{min(bt_at):.1f}–{max(bt_at):.1f}°{mode}</span>')

        html = '<br>'.join(lines)
        if event.guiEvent is not None:
            global_point = event.guiEvent.globalPosition().toPoint()
        else:
            device_ratio = self.canvas.devicePixelRatioF()
            x_canvas = int(event.x / device_ratio)
            y_canvas = int((self.canvas.height() * device_ratio - event.y) / device_ratio)
            global_point = self.canvas.mapToGlobal(QPoint(x_canvas, y_canvas))
        self._hover_tooltip.show_at(global_point, html)

    def _extract_roast_metrics(self, data: dict) -> dict:
        c = data.get('computed', {})
        mode = data.get('mode', 'C')
        ground = data.get('ground_color', 0) or 0
        whole = data.get('whole_color', 0) or 0
        level, lvl_th = self.roast_level_thresholds(ground if ground else whole)
        dtr_target = sum(lvl_th['dtr']) / 2.0
        wl_target = sum(lvl_th['wl']) / 2.0
        t_charge = 0
        t_dry    = c.get('DRY_time', 0) or 0
        t_fcs    = c.get('FCs_time', 0) or 0
        t_drop   = c.get('DROP_time', 0) or 0
        drying      = t_dry - t_charge
        maillard    = t_fcs - t_dry
        development = t_drop - t_fcs
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
        torréfaction et le coach mono-roast — 'crash', 'flick', les deux, ou
        None si le développement reste propre."""
        if not data or not deltabt:
            return None
        ti = (list(data.get('timeindex', [])) + [-1] * 8)[:8]
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
            # Seuil de proéminence en °/min → mis à l'échelle pour le Fahrenheit.
            tscale = 1.8 if data.get('mode', 'C') == 'F' else 1.0
            flicks, crashes = find_flicks_crashes(
                deltabt[seg_slice], timex_shifted[seg_slice], phase_times, tp_idx_local,
                prominence=1.0 * tscale,
            )
        except (TypeError, ValueError, IndexError):
            return None
        dev_crash = any(e.get("phase") == 3 for e in crashes)
        dev_flick = any(e.get("phase") == 3 for e in flicks)
        if dev_crash and dev_flick:
            return 'crash+flick'
        if dev_crash:
            return 'crash'
        if dev_flick:
            return 'flick'
        return None

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

    def _multi_stats_html(self) -> str:
        if not self._multi_curves:
            return ""
        metrics = [self._extract_roast_metrics(c['data']) for c in self._multi_curves if c.get('data')]
        if not metrics:
            return ""
        n = len(metrics)
        mode = metrics[0]['mode']
        palette = self._make_multi_palette(n)
        TD=THEME['SURFACE']; TH=THEME['BG']; HDR=THEME['BORDER']
        BEST_BG='rgba(166,227,161,0.18)'; WARN_BG=tint('CRITICAL', 0.15)
        BEST=THEME['SUCCESS']; WARN=THEME['CRITICAL']; NEUT=THEME['TEXT']; MUTED=THEME['OVERLAY2']
        F="font-family:'SF Pro Display','Segoe UI',sans-serif;"
        def th(t, w=''):
            ws=f'width:{w};' if w else ''
            return f'<th style="background:{HDR};color:{NEUT};padding:7px 10px;text-align:left;font-size:11px;font-weight:600;border-bottom:1px solid {THEME["SURFACE1"]};{ws}{F}">{t}</th>'
        def lc(t):
            return f'<td style="background:{TH};color:{MUTED};padding:6px 10px;font-size:11px;white-space:nowrap;border-bottom:1px solid #2a2a3a;{F}">{t}</td>'
        def vc(t, bg=None, color=None, bold=False):
            bg=bg or TD; color=color or NEUT; fw='font-weight:700;' if bold else ''
            return f'<td style="background:{bg};color:{color};padding:6px 10px;font-size:12px;text-align:right;border-bottom:1px solid #2a2a3a;{fw}{F}">{t}</td>'
        def sec(t):
            return f'<tr><td colspan="{n+1}" style="background:#252536;color:{THEME["ACCENT"]};padding:5px 10px;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;border-top:1px solid {THEME["SURFACE1"]};{F}">{t}</td></tr>'
        def hrow(label, vals, ideal=None, lower_better=False, fmt=str, warn_fn=None, unit=''):
            nums=[v for v in vals if v is not None]
            cells=[]
            for v in vals:
                if v is None: cells.append(vc('\u2014', color=MUTED)); continue
                bg2=TD; col2=NEUT; bold=False
                if ideal is not None and nums:
                    bv=min(nums, key=lambda x:abs(x-ideal))
                    if v==bv: bg2,col2,bold=BEST_BG,BEST,True
                elif lower_better and nums:
                    if v==min(nums): bg2,col2,bold=BEST_BG,BEST,True
                if warn_fn and warn_fn(v): bg2,col2=WARN_BG,WARN
                cells.append(vc(f'{fmt(v)}{unit}',bg=bg2,color=col2,bold=bold))
            return '<tr>'+lc(label)+''.join(cells)+'</tr>'
        # header
        hdr='<tr>'+th('Metric','150px')
        for i,m in enumerate(metrics):
            bt_col=palette[i][0]
            short=m['title'][:26]+'\u2026' if len(m['title'])>26 else m['title']
            hdr+=f'<th style="background:{HDR};color:{bt_col};padding:7px 10px;font-size:11px;font-weight:700;border-bottom:1px solid {THEME["SURFACE1"]};text-align:right;{F}" title="{m["title"]}">{short}</th>'
        hdr+='</tr>'
        rows=hdr
        rows+=sec('\u23f1 TIME')
        rows+=hrow('Total',    [m['total_s']    for m in metrics], ideal=sum(m['total_s']    for m in metrics)/n, fmt=lambda x: next(m['total_fmt']    for m in metrics if m['total_s']   ==x))
        rows+=hrow('Drying',   [m['drying_s']   for m in metrics], ideal=sum(m['drying_s']   for m in metrics)/n, fmt=lambda x: next(m['drying_fmt']   for m in metrics if m['drying_s']  ==x))
        rows+=hrow('Maillard', [m['maillard_s'] for m in metrics], ideal=sum(m['maillard_s'] for m in metrics)/n, fmt=lambda x: next(m['maillard_fmt'] for m in metrics if m['maillard_s']==x))
        rows+=hrow('Development',[m['dev_s']    for m in metrics], ideal=sum(m['dev_s']      for m in metrics)/n, fmt=lambda x: next(m['dev_fmt']      for m in metrics if m['dev_s']     ==x))
        rows+=sec('\U0001f4ca KEY RATIOS')
        rows+=hrow('DTR %',       [m['dtr'] for m in metrics], ideal=20.0, warn_fn=lambda v:v<15 or v>25, fmt=lambda x:f'{x:.1f}', unit=' %')
        rows+=hrow('Weight loss', [m['wl']  for m in metrics], ideal=15.0, warn_fn=lambda v:v is not None and (v<12 or v>18), fmt=lambda x:f'{x:.1f}', unit=' %')
        rows+=sec(f'\U0001f321 TEMPERATURES (\u00b0{mode})')
        cb_avg = sum(m['charge_bt'] for m in metrics if m['charge_bt'])/max(1,sum(1 for m in metrics if m['charge_bt']))
        db_avg = sum(m['drop_bt']   for m in metrics if m['drop_bt']  )/max(1,sum(1 for m in metrics if m['drop_bt']))
        rows+=hrow('Charge BT',  [m['charge_bt'] for m in metrics], ideal=cb_avg, fmt=lambda x:f'{x:.1f}')
        rows+=hrow('Turn Point', [m['tp_bt']     for m in metrics], lower_better=True, fmt=lambda x:f'{x:.1f}')
        rows+=hrow('Drop BT',    [m['drop_bt']   for m in metrics], ideal=db_avg, fmt=lambda x:f'{x:.1f}')
        rows+=sec('\U0001f525 ROR (\u00b0/min)')
        rows+=hrow('RoR Dry',      [m['ror_dry']   for m in metrics], ideal=12.0, fmt=lambda x:f'{x:.2f}')
        rows+=hrow('RoR Maillard', [m['ror_mid']   for m in metrics], ideal=9.0,  fmt=lambda x:f'{x:.2f}')
        rows+=hrow('RoR Finish',   [m['ror_fin']   for m in metrics], ideal=5.0,  fmt=lambda x:f'{x:.2f}')
        rows+=hrow('RoR Total',    [m['ror_total'] for m in metrics], ideal=9.0,  fmt=lambda x:f'{x:.2f}')
        rows+=sec('\u2696 WEIGHT')
        wcells=[]
        for m in metrics:
            if m['w_in'] and m['w_out']: wcells.append(vc(f"{m['w_in']:.0f}\u2192{m['w_out']:.0f} {m['w_unit']}"))
            else: wcells.append(vc('\u2014', color=MUTED))
        rows+='<tr>'+lc('Green \u2192 Roasted')+''.join(wcells)+'</tr>'
        table=f'<table style="width:100%;border-collapse:collapse;">{rows}</table>'
        # coach advice
        advices=self._generate_multi_coach_advice(metrics)
        coach_html=''
        if advices:
            items=''.join(f'<li style="padding:4px 0;color:{NEUT};font-size:12px;border-bottom:1px solid #2a2a3a;{F}">{a}</li>' for a in advices)
            coach_html=(f'<div style="margin-top:16px;">'
                f'<div style="color:{THEME["ACCENT"]};font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:6px 10px;background:#252536;border-radius:6px 6px 0 0;">'
                f'\U0001f9d1\u200d\U0001f3eb COACH\'S COMPARATIVE ADVICE</div>'
                f'<ul style="list-style:none;margin:0;padding:8px 12px;background:{TD};border-radius:0 0 6px 6px;">{items}</ul></div>')
        return f'<div style="padding:8px;">{table}{coach_html}</div>'
