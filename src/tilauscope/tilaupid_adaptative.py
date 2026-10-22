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
# TiLau 2025 — Adaptive Learning Extension

"""
tilaupid_adaptive.py
====================
Module d'apprentissage adaptatif pour TilauPreheatPID.

Fonctionnement :
  1. AlogScanner   — Scanne le répertoire des alogs Artisan et extrait les
                     métriques de torréfaction pertinentes (montée RoR,
                     dépassement, temps de stabilisation, conditions ambiantes).
  2. AdaptiveMemory — Stocke et agrège les métriques sur une fenêtre glissante
                      de N torréfactions (défaut 10).
  3. AmbientCorrector — Applique une correction multiplicative de puissance
                        basée sur T°/humidité/pression ambiantes.
  4. StabilisationDetector — Détecte en temps réel si le hold est stable
                             (variance glissante < seuil).
  5. AdaptivePIDMixin — Mixin à intégrer dans TilauPreheatPID ; expose
                        apply_adaptive_corrections() à appeler depuis
                        _precompute_targets() et cycle().

Intégration minimale dans tilaupid.py :
  • Importer AdaptivePIDMixin
  • Ajouter AdaptivePIDMixin comme base de TilauPreheatPID
  • Appeler self._adaptive_init() dans __init__
  • Appeler self._on_cycle_end(t_c, burner) depuis cycle()
  • Appeler self._on_preheat_complete() quand stabilisation détectée
"""

# Lazy annotations so this module can be imported by an offline corpus
# analysis tool WITHOUT importing artisanlib.main (which would bind a QApplication
# and clobber the user's real Artisan prefs). ApplicationWindow / ProfileData are
# used only in type hints + a string cast, so they live under TYPE_CHECKING.
from __future__ import annotations

import logging
import time  # noqa: F401  (the tests set the clock through this module)
from typing import Optional, Callable, TYPE_CHECKING
from typing import Final

from tilaucore.preheat import AmbientConditions, AmbientCorrector  # noqa: F401
from tilaucore.preheat_learning import (  # noqa: F401  (shared with the tablet; still imported from here)
    AdaptiveMemory, LearnedParams, RoastPreheatMetrics, StabilisationDetector, ThermalModel,
    _robust_centre, _robust_peak, quadratic_thermal_gain_c_per_pct, read_law_nodes,
    thermal_gain_c_per_pct, weight_gaussian, weight_triangular)
from tilaucore.preheat_learning import (  # noqa: F401
    _BUMPLESS_STOP_REASONS, IDENTITY_KEYS_VERSION, LAW_VERSION, AlogScanner as _CoreAlogScanner, PreheatLearning,
    _normalise_identity, migrate_renamed_machine_keys)

if TYPE_CHECKING:
    from typing import Protocol

    from artisanlib.main import ApplicationWindow

    class _PIDConfigLike(Protocol):
        target_sv: float
        p_ss_default: float
        lead_sec_default: float
        lead_sec_min: float
        lead_sec_max: float
        max_burner: float

from PyQt6.QtCore import QSettings

_logd: Final[logging.Logger] = logging.getLogger("tilau")



def law_context_prefix(aw: object, *, version: int = LAW_VERSION) -> str:
    """Settings prefix isolating one machine/control-channel pair."""
    qmc = getattr(aw, "qmc", None)
    machine = _normalise_identity(
        getattr(qmc, "roastertype_setup", "")
        or getattr(qmc, "roastertype", "")
        or getattr(qmc, "machinesetup", "")
    )
    source = getattr(getattr(aw, "pidcontrol", None), "pidSource", 1)
    channel = AlogScanner._control_channel(source)  # noqa: SLF001
    return f"tilaupid/v{version}/{machine or 'unknown'}/{channel}"


class AlogScanner(_CoreAlogScanner):
    """The shared scanner, given this machine and channel from Artisan, over the desktop's roast index."""

    def __init__(self, alog_dir: str, window: int = 10, aw:ApplicationWindow | None = None,
                 scan_budget: int | None = None):
        qmc = getattr(aw, "qmc", None)
        machine = (
            getattr(qmc, "roastertype_setup", "")
            or getattr(qmc, "roastertype", "")
            or getattr(qmc, "machinesetup", "")
        )
        source = getattr(getattr(aw, "pidcontrol", None), "pidSource", None)
        super().__init__(alog_dir, window, machine=machine, pid_source=source, scan_budget=scan_budget)
        self.aw = aw

    def _index_records(self) -> dict:
        from tilauscope.alogmanager import AlogIndex
        return AlogIndex.instance().records(self.alog_dir)


class AdaptivePIDMixin(PreheatLearning):
    """The shared preheat learning, given Artisan's settings, simulator flag, machine and roast index."""

    def _settings(self) -> QSettings:
        return QSettings()

    def _simulated(self) -> bool:
        return getattr(getattr(self, "aw", None), "simulator", None) is not None

    def _make_scanner(self, alog_dir: str, window: int, scan_budget: int | None) -> AlogScanner:
        return AlogScanner(alog_dir, window, aw=self.aw, scan_budget=scan_budget)

    def _adaptive_init(
        self,
        alog_dir: Optional[str] = None,
        window: int = 10,
        ambient: Optional[AmbientConditions] = None,
        aw: ApplicationWindow | None = None ,
        scan_budget: int | None = None,
    ) -> None:
        self.aw=aw
        super()._adaptive_init(alog_dir, window, ambient, scan_budget)

    @staticmethod
    def _configured_alog_dir() -> str:
        """Répertoire alog canonique tel que fixé par l'application.

        Lit la clé QSettings 'alogDirectory' — la même source utilisée par
        routine_check, roast_plan_model, beancave et l'onboarding. On ne devine
        pas le dossier ; s'il n'est pas configuré, on retourne "" (le scanner
        traite un répertoire inexistant comme un corpus vide, sans planter).
        """
        alog_dir = QSettings().value("alogDirectory", "", str) or ""
        if not alog_dir:
            _logd.warning("QSettings 'alogDirectory' non configuré — corpus vide.")
        return alog_dir

    def _law_context(self) -> tuple[str, str]:
        """Return the stable machine/source identity used to isolate learned state."""
        scanner = getattr(self, "_alog_scanner", None)
        machine = getattr(scanner, "machine_fingerprint", "")
        channel = getattr(scanner, "control_channel", None)
        if not machine:
            qmc = getattr(getattr(self, "aw", None), "qmc", None)
            machine = _normalise_identity(
                getattr(qmc, "roastertype_setup", "")
                or getattr(qmc, "roastertype", "")
                or getattr(qmc, "machinesetup", "")
            )
        if channel is None:
            source = getattr(getattr(getattr(self, "aw", None), "pidcontrol", None),
                             "pidSource", 1)
            channel = AlogScanner._control_channel(source)
        return machine or "unknown", channel
