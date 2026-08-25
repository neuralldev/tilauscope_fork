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

"""RoastDataBridge — couche de signaux Qt normalisés entre qmc et
RoastAssistantPanel ; centralise les accès qmc et élimine le polling multi-appels."""

import logging
from typing import Final, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from artisanlib.util import fromFtoCstrict

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

_logd: Final[logging.Logger] = logging.getLogger("tilau")

# ── Seuils de déclenchement ambient_updated ─────────────────────────────────
_AMBIENT_TEMP_DELTA: float = 3.0   # °C — changement significatif (l'ambiant est normalisé en °C)
_AMBIENT_HUM_DELTA:  float = 5.0   # % RH


class RoastDataBridge(QObject):
    """
    Passerelle de signaux normalisés entre qmc et RoastAssistantPanel.
    Instancier une seule fois dans TilauScope.__init_ui__().
    """

    # ── Signaux publics ──────────────────────────────────────────────────────
    bt_updated             = pyqtSignal(float)          # BT courante
    et_updated             = pyqtSignal(float)          # ET courante
    ror_updated            = pyqtSignal(float)          # RoR courant
    ambient_updated        = pyqtSignal(float, float)   # (temp °C, hum) — si Δ significatif
    phase_changed          = pyqtSignal(str)            # clé de phase
    roast_state_changed    = pyqtSignal(bool)           # True = roast ON

    def __init__(self, aw: "ApplicationWindow", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.aw = aw

        # Dernières valeurs connues — pour filtrage et détection de changement
        self._last_bt:  float = 0.0
        self._last_et:  float = 0.0
        self._last_ror: float = 0.0
        self._last_ambient_temp: float = 0.0
        self._last_ambient_hum:  float = 0.0

        # Phase courante — pour limiter la régénération du plan aux phases utiles
        self._current_phase: str = "IDLE"

    # ── API publique appelée par displayscope ────────────────────────────────

    @pyqtSlot(object)
    def tick(self, _data: int | str = 10) -> None:
        """Cycle complet 1 Hz, appelé UNIQUEMENT depuis la branche TIMER (data == 10)
        de update_ui_from_artisan() ; relit qmc et agrège BT+ET+RoR+ambient en une
        seule passe (pas de dispatch par canal). `_data` est ignoré."""
        self._emit_bt()
        self._emit_et()
        self._emit_ror()
        self._check_ambient()

    @pyqtSlot(str)
    def notify_phase(self, phase_key: str) -> None:
        """Appelé depuis _handle_milestone_events() à chaque changement de phase."""
        self._current_phase = phase_key
        self.phase_changed.emit(phase_key)

    @pyqtSlot(bool)
    def notify_preheat(self, active: bool) -> None:
        """Appelé depuis handle_preheat() ; mappe sur notify_phase."""
        self.notify_phase("PREHEAT" if active else "IDLE")

    @pyqtSlot(bool)
    def notify_roast_state(self, active: bool) -> None:
        """Appelé depuis toggle_start_stop()."""
        if not active:
            self._current_phase = "IDLE"
        self.roast_state_changed.emit(active)

    # ── Émissions partielles ─────────────────────────────────────────────────

    def _emit_bt(self) -> None:
        try:
            bt = float(self.aw.qmc.temp2[-1])
            if bt > 0 and bt != self._last_bt:   # -1 = Artisan sentinel, skip
                self._last_bt = bt
                self.bt_updated.emit(bt)
        except (IndexError, TypeError, AttributeError):
            pass

    def _emit_et(self) -> None:
        try:
            et = float(self.aw.qmc.temp1[-1])
            if et > 0 and et != self._last_et:
                self._last_et = et
                self.et_updated.emit(et)
        except (IndexError, TypeError, AttributeError):
            pass

    def _emit_ror(self) -> None:
        try:
            delta2 = self.aw.qmc.delta2
            ror = float(delta2[-1]) if delta2 else 0.0
            if ror != self._last_ror:
                self._last_ror = ror
                self.ror_updated.emit(ror)
        except (IndexError, TypeError, AttributeError):
            pass

    # ── Lecture ambiant live ─────────────────────────────────────────────────

    def _check_ambient(self) -> None:
        """Lit la dernière valeur des extradevices configurés comme source ambiante ;
        n'émet ambient_updated que si le changement dépasse les seuils, en PREHEAT/DRY."""
        if self._current_phase not in ("PREHEAT", "DRY", "IDLE"):
            return

        temp = self._read_ambient_temp()
        hum  = self._read_ambient_hum()

        if temp is None and hum is None:
            return

        temp = temp if temp is not None else self._last_ambient_temp
        hum  = hum  if hum  is not None else self._last_ambient_hum

        # Émet seulement si changement significatif sur l'une ou l'autre valeur
        temp_changed = abs(temp - self._last_ambient_temp) >= _AMBIENT_TEMP_DELTA
        hum_changed  = abs(hum  - self._last_ambient_hum)  >= _AMBIENT_HUM_DELTA

        if temp_changed or hum_changed:
            _logd.info(
                f"RoastDataBridge: ambient change detected "
                f"T {self._last_ambient_temp:.1f}→{temp:.1f} "
                f"H {self._last_ambient_hum:.1f}→{hum:.1f}"
            )
            self._last_ambient_temp = temp
            self._last_ambient_hum  = hum
            self.ambient_updated.emit(temp, hum)

    def _read_ambient_temp(self) -> float | None:
        """
        Lit la température ambiante depuis la source configurée dans Artisan.
        Stratégie : dernière valeur live de l'extradevice (pas la moyenne figée).
        Retourne None si aucune source n'est configurée ou si les données manquent.

        Le plan travaille en °C : les séries qmc portent l'unité d'AFFICHAGE,
        la conversion se fait donc ici, à la frontière d'entrée.
        """
        try:
            qmc = self.aw.qmc
            _to_c = fromFtoCstrict if qmc.mode == 'F' else float
            source = int(qmc.ambientTempSource or 0)
            if source == 0:
                # Pas de source configurée — fallback sur qmc.ambientTemp one-shot
                v = float(qmc.ambientTemp or 0.0)
                return _to_c(v) if v != 0.0 else None
            if source == 1:  # ET
                return _to_c(float(qmc.temp1[-1])) if qmc.temp1 else None
            if source == 2:  # BT
                return _to_c(float(qmc.temp2[-1])) if qmc.temp2 else None
            # Extra device : source ≥ 3
            # Artisan encode : source=3 → extratemp1[0], 4 → extratemp2[0],
            #                  source=5 → extratemp1[1], 6 → extratemp2[1], …
            dev_idx = (source - 3) // 2
            use_t2  = (source % 2 == 0)
            if qmc.flagstart:
                series  = qmc.extratemp2[dev_idx] if use_t2 else qmc.extratemp1[dev_idx]
            else:
                series  = qmc.RTextratemp2[dev_idx] if use_t2 else qmc.RTextratemp1[dev_idx]
            if series is not None and (not qmc.flagstart or len(series)):
                v = float(series[-1]) if qmc.flagstart else float(series) # RT array is a list of float not a list of (list of float)
                return _to_c(v) if v != -1 else None
        except (IndexError, TypeError, AttributeError, ValueError):
            pass
        return None

    def _read_ambient_hum(self) -> float | None:
        """
        Lit l'humidité ambiante depuis la source configurée dans Artisan.
        Même logique d'encodage que _read_ambient_temp.
        """
        try:
            qmc = self.aw.qmc
            source = int(qmc.ambientHumiditySource or 0)
            if source == 0:
                v = float(qmc.ambient_humidity or 0.0)
                return v if v != 0.0 else None
            if source == 1:
                return float(qmc.temp1[-1]) if qmc.temp1 else None
            if source == 2:
                return float(qmc.temp2[-1]) if qmc.temp2 else None
            dev_idx = (source - 3) // 2
            use_t2  = (source % 2 == 0)
            if qmc.flagstart:
                series  = qmc.extratemp2[dev_idx] if use_t2 else qmc.extratemp1[dev_idx]
            else:
                series  = qmc.RTextratemp2[dev_idx] if use_t2 else qmc.RTextratemp1[dev_idx]
            if series is not None and (not qmc.flagstart or len(series)):
                v = float(series[-1]) if qmc.flagstart else float(series) # RT array is a list of float not a list of (list of float)
                return v if v != -1 else None
        except (IndexError, TypeError, AttributeError, ValueError):
            pass
        return None