"""
Réglage automatique du menu Axes d'Artisan pour TilauScope.

Applique un jeu de réglages d'axes opinionés (fenêtre temps CHARGE-1min/DROP+1min,
axe température 0-270°C, grille pointillée, légende bas-droite, axe delta 0-18°C, …)
sans modification de artisanlib/main.py ni canvas.py : on écrit directement les
attributs d'instance de qmc (même mécanisme que la boîte de dialogue Config > Axes,
voir artisanlib/axis.py) puis on déclenche qmc.redraw().

Installation (aucune modification de main.py) :
    self._axes_hook = AxesConfigHook(self.aw)
    self._axes_hook.install()      # patch aw.loadFile, ré-applique à chaque profil
    self._axes_hook.apply_now()    # applique une première fois au démarrage de TilauScope

Retrait :
    self._axes_hook.remove()
"""

from __future__ import annotations

import logging

from artisanlib.util import fromCtoFstrict

_log = logging.getLogger(__name__)

# ── Valeurs cibles (exprimées en °C ; converties si qmc.mode == 'F') ──────────
_TIME_MARGIN_S = 60          # 1 min avant CHARGE / après DROP
_TIME_GRID_STEP_S = 60       # pas de grille temps = 1 min
_RECORD_MIN_S = -60          # RECORD Min par défaut = -1 min
_RECORD_MAX_S = 12 * 60      # RECORD Max par défaut = 12 min
_TEMP_MIN_C = 0
_TEMP_MAX_C = 270
_EVENT_STEP100_C = 80
_LEGEND_LOC_BOTTOM_RIGHT = 4
_GRID_DOTTED_INDEX = 3       # qmc.gridstyles = ['-','--','-.',':',' ']
_GRID_WIDTH = 1
_GRID_ALPHA = 0.2
_DELTA_MIN_C = 0
_DELTA_MAX_C = 18
_DELTA_STEP_C = 4


def apply_axes_config(aw: object) -> None:
    """Applique le jeu de réglages Axes TilauScope sur l'instance qmc de aw."""
    qmc = aw.qmc  # type: ignore[attr-defined]
    try:
        is_f = qmc.mode == 'F'

        # 1. Axe temps : -1min avant CHARGE -> +1min après DROP, pas de grille 1min
        qmc.autotimex = False
        if qmc.timeindex[0] > -1 and len(qmc.timex) > qmc.timeindex[0]:
            charge_t = qmc.timex[qmc.timeindex[0]]
        else:
            charge_t = qmc.timex[0] if qmc.timex else 0.0
        if qmc.timeindex[6] > 0 and len(qmc.timex) > qmc.timeindex[6]:
            drop_t = qmc.timex[qmc.timeindex[6]]
        else:
            drop_t = qmc.timex[-1] if qmc.timex else qmc.resetmaxtime
        qmc.startofx = charge_t - _TIME_MARGIN_S
        qmc.endofx = drop_t + _TIME_MARGIN_S
        qmc.xgrid = _TIME_GRID_STEP_S

        # 2. Fenêtre d'enregistrement par défaut : -1min -> 12min, expansion activée
        qmc.chargemintime = _RECORD_MIN_S
        qmc.resetmaxtime = _RECORD_MAX_S
        qmc.fixmaxtime = False  # False = case "Expand" cochée

        # 3. Axe température : 0-270°C (converti en °F si mode Fahrenheit)
        if is_f:
            qmc.ylimit_min = round(fromCtoFstrict(_TEMP_MIN_C))
            qmc.ylimit = round(fromCtoFstrict(_TEMP_MAX_C))
        else:
            qmc.ylimit_min = _TEMP_MIN_C
            qmc.ylimit = _TEMP_MAX_C

        # 4. 100% Event Step = 80°C (converti si °F)
        qmc.step100temp = round(fromCtoFstrict(_EVENT_STEP100_C)) if is_f else _EVENT_STEP100_C

        # 5. Légende bas-droite
        qmc.legendloc = _LEGEND_LOC_BOTTOM_RIGHT
        qmc.legendloc_pos = None
        qmc.legend = None

        # 6. Grille pointillée, largeur 1, opacité 0.2, temps + température cochés
        qmc.gridlinestyle = _GRID_DOTTED_INDEX
        qmc.gridthickness = _GRID_WIDTH
        qmc.gridalpha = _GRID_ALPHA
        qmc.time_grid = True
        qmc.temp_grid = True

        # 7. Axe delta : auto décoché, DeltaET/DeltaBT masqués, 0-18°C pas 4°C
        qmc.autodeltaxET = False
        qmc.autodeltaxBT = False
        if is_f:
            # écarts de température (pas des valeurs absolues) : x9/5 sans offset
            qmc.zlimit_min = round(_DELTA_MIN_C * 9.0 / 5.0)
            qmc.zlimit = round(_DELTA_MAX_C * 9.0 / 5.0)
            qmc.zgrid = round(_DELTA_STEP_C * 9.0 / 5.0)
        else:
            qmc.zlimit_min = _DELTA_MIN_C
            qmc.zlimit = _DELTA_MAX_C
            qmc.zgrid = _DELTA_STEP_C
        qmc.showCurve('DeltaET', False)
        qmc.showCurve('DeltaBT', False)

        # Application
        qmc.redraw(recomputeAllDeltas=False, forceRenewAxis=True)
        if getattr(qmc, 'crossmarker', False):
            qmc.togglecrosslines()
            qmc.togglecrosslines()
        ntb = getattr(aw, 'ntb', None)
        if ntb is not None:
            try:
                ntb.update()
            except Exception:
                pass
    except Exception as exc:
        _log.warning('apply_axes_config: failed to apply: %s', exc)


class AxesConfigHook:
    """
    Intercepte ApplicationWindow.loadFile pour ré-appliquer les réglages Axes
    TilauScope après chaque chargement de profil (.alog).

    Lifetime : calé sur TilauScope (install à __init__, remove à closeEvent),
    même mécanisme que ArtisanMessageHook (artisan_message_ticker.py).
    """

    def __init__(self, aw: object) -> None:
        self._aw = aw
        self._original: object | None = None

    def apply_now(self) -> None:
        """Applique immédiatement les réglages (à appeler une fois au démarrage)."""
        apply_axes_config(self._aw)

    def install(self) -> None:
        if self._original is not None:
            return  # already installed — idempotent

        self._original = self._aw.loadFile  # type: ignore[attr-defined]

        aw = self._aw
        original = self._original

        def _hooked(filename: str, quiet: bool = False) -> None:
            original(filename, quiet)  # type: ignore[misc,operator]
            apply_axes_config(aw)

        self._aw.loadFile = _hooked  # type: ignore[attr-defined]
        _log.debug('AxesConfigHook: installed')

    def remove(self) -> None:
        if self._original is None:
            return
        try:
            self._aw.loadFile = self._original  # type: ignore[attr-defined]
        except Exception as exc:
            _log.warning('AxesConfigHook: could not restore: %s', exc)
        finally:
            self._original = None
        _log.debug('AxesConfigHook: removed')
