#
# ABOUT
#
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

import re
from collections import deque
from typing import Final, NamedTuple
from typing import TYPE_CHECKING
import logging
from artisanlib.main import ApplicationWindow # pylint: disable=unused-import
from tilaucore.milestones import DryEnd, FirstCrack
from tilauscope.tilauscope_types import (MILESTONE_HALF_C,
                                         classify_extra_channel,
                                         resolve_crack_channel)

_logd: Final[logging.Logger] = logging.getLogger("tilau")
_log: Final[logging.Logger] = logging.getLogger(__name__)

# Extra-device channel classification lives in tilauscope_types: the drawing
# pass needs it too, and this module imports artisanlib.main — which the
# curve must never pull in. Re-exported here for existing callers.

class FirstCrackDetector:
    """First Crack on the desktop: the crack channels read from qmc, the decision taken by
    tilaucore.milestones.FirstCrack, the engine the Android prototype shares."""

    def __init__(self):
        self._core = FirstCrack()
        self.last_count: int = 0
        self.aw_qmc = None
        # FC + SC crack counters. Attribution inverts between builds
        # (a roast may route ALL pops to FCcounter on one build, to SCcounter on
        # another). Pre-fire we fuse both; at fire we snapshot the SC offset so a
        # downstream SC count is corrected for pops already attributed to FC.
        self._cached_crack_device_idx: int = -1      # FC counter channel
        self._cached_crack_device_channel: int = -1
        self._cached_sc_device_idx: int = -1         # SC counter channel
        self._cached_sc_device_channel: int = -1
        self._sc_raw_at_fc: int | None = None        # SC raw snapshot at FC fire (offset)
        self._fc_tally: int = 0                      # our own FC pop tally beside raw counters

    # The detection window (s), the cracks in it that call FC, and the BT half-band (°C)
    # around the target: the shared detector's, set from Artisan's settings.
    @property
    def window_seconds(self) -> float:
        return self._core.window_s

    @property
    def threshold(self) -> int:
        return self._core.threshold

    @property
    def half_band_c(self) -> float:
        return self._core.half_band_c

    @property
    def crack_timestamps(self) -> "deque[float]":
        return self._core.crack_times

    @property
    def is_fired(self) -> bool:
        return self._core.fired

    def reset(self):
        self._core = FirstCrack(self._core.window_s, self._core.threshold, self._core.half_band_c)
        self.last_count = 0
        self._cached_crack_device_idx = -1
        self._cached_crack_device_channel = -1
        self._cached_sc_device_idx = -1
        self._cached_sc_device_channel = -1
        self._sc_raw_at_fc = None
        self._fc_tally = 0

    def detect_extradevice(self, aw: ApplicationWindow) -> int | None:
        self.aw_qmc = aw.qmc
        # Load configuration from Artisan AppWindow
        self._core.window_s    = float(getattr(aw, "TilauScopeFCWindow", 35.0))
        self._core.threshold   = int(getattr(aw, "TilauScopeFCTreshold", 4))
        self._core.half_band_c = float(getattr(aw, "TilauScopeFCHalfBand", MILESTONE_HALF_C))

        qmc = aw.qmc
        found_crack_idx: int | None = None

        for i in range(len(qmc.extradevices)):
            for ch, names in ((1, qmc.extraname1), (2, qmc.extraname2)):
                name = names[i].lower() if i < len(names) else ""
                cat = classify_extra_channel(name)
                if cat is None:
                    continue
                if cat == "fc":
                    pass   # the FC slot is resolved once, below
                elif cat == "sc" and self._cached_sc_device_idx == -1:
                    # SC counter is fused with FC pre-fire (attribution
                    # inverts between builds), and offset-corrected post-fire.
                    self._cached_sc_device_idx     = i
                    self._cached_sc_device_channel = ch
                    _log.info(f"FC_Detector: SC counter @ extra {i} ch{ch} ({name})")
                # 'color'/'roc' deliberately ignored here: no reliable colour
                # threshold exists at FC, and RoC is a DryEnd signal (negative
                # slope by FC). Colour stays a DryEnd-only signal.

        crack = resolve_crack_channel(qmc.extraname1, qmc.extraname2,
                                      qmc.extratemp1, qmc.extratemp2)
        if crack is not None:
            self._cached_crack_device_idx, self._cached_crack_device_channel = crack
            found_crack_idx = crack[0]
            _log.info(f"FC_Detector: FC counter @ extra {crack[0]} ch{crack[1]}")

        # The FC and SC slots are FUSED by the reader, and fusing only makes
        # sense within one device: attribution inverts between firmware builds,
        # so one channel of a device carries everything and its twin reads ~0.
        # Across two devices it is not the same signal counted twice — it is two
        # instruments added together. A machine can carry both an acoustic probe
        # and the Omniflux pair, so drop an SC slot that belongs to another one.
        if (self._cached_sc_device_idx != -1
                and self._cached_sc_device_idx != self._cached_crack_device_idx):
            _log.info(f"FC_Detector: SC counter @ extra {self._cached_sc_device_idx} "
                      f"dropped — not the device the crack counter is on")
            self._cached_sc_device_idx     = -1
            self._cached_sc_device_channel = -1

        return found_crack_idx

    def check_detection(self, current_bt: float, target_fcs: float,
                      current_time: float, mode: str = 'C') -> float | bool:
        """The FC timestamp when it fires at this sample, else False. The fused FC+SC pop count
        is read here; the window (plan target_fcs in native units, else the profession band),
        the arming from below and the burst rule are tilaucore's."""
        if self._core.fired:
            return False
        raw = self._get_crack_counter_value()
        if raw is not None:
            self.last_count = raw                      # keep the UI badge current
        fired_at = self._core.check(current_bt, target_fcs, current_time, raw, mode)
        if fired_at is None:
            return False
        self._snapshot_at_fire()
        _log.info(f"FC_Detector: FIRED @ t={current_time:.0f}s (BT={current_bt:.1f}), first crack at {fired_at:.0f}s")
        return fired_at

    def _get_value_by_cache(self, idx: int, channel: int) -> float | None:
        """Récupère la dernière valeur d'un périphérique extra mis en cache."""
        if not hasattr(self, 'aw_qmc') or self.aw_qmc is None:
            return None
        if idx == -1:
            return None
        try:
            if self.aw_qmc.flagstart:
                series = self.aw_qmc.extratemp1[idx] if channel == 1 else self.aw_qmc.extratemp2[idx]
                return float(series[-1]) if series else None
            else:
                series = self.aw_qmc.RTextratemp1[idx] if channel == 1 else self.aw_qmc.RTextratemp2[idx]
            return float(series) if series else None
        except (IndexError, TypeError, ValueError):
            return None

    def _read_counter(self, idx: int, channel: int) -> int | None:
        """Single counter channel as int, filtering the -1 'no data' sentinel."""
        val = self._get_value_by_cache(idx, channel)
        if val is None:
            return None
        count = int(val)
        return count if count >= 0 else None

    def _read_fc_raw(self) -> int | None:
        return self._read_counter(self._cached_crack_device_idx,
                                  self._cached_crack_device_channel)

    def _read_sc_raw(self) -> int | None:
        return self._read_counter(self._cached_sc_device_idx,
                                  self._cached_sc_device_channel)

    def _get_crack_counter_value(self) -> int | None:
        """
        Fused FC+SC crack count used pre-fire. Channel attribution inverts between
        builds (one routes all pops to FCcounter, another to SCcounter), so the
        total is the sum of both: one carries everything, the other is ~0 — never
        double-counted (pops land on a single channel). None only when BOTH die.
        """
        fc = self._read_fc_raw()
        sc = self._read_sc_raw()
        if fc is None and sc is None:
            return None
        return (fc or 0) + (sc or 0)

    def _snapshot_at_fire(self) -> None:
        """Freeze the SC offset and our own FC tally at the instant FC fires."""
        self._sc_raw_at_fc = self._read_sc_raw() or 0   # SC pops pre-FC were fused into FC
        self._fc_tally     = self.last_count            # fused total attributed to FC

    def get_sc_count(self) -> int:
        """
        Real SC count for downstream consumers (display / future SC detector):
        the SC channel minus the offset captured at FC fire. Returns 0 until FC
        has fired. Note: on a build that routes ALL pops to FCcounter, post-FC SC
        stays 0 — harmless here since dark roasts (real SC) are never run.
        """
        if self._sc_raw_at_fc is None:
            return 0
        sc = self._read_sc_raw()
        if sc is None:
            return 0
        return max(0, sc - self._sc_raw_at_fc)

    def get_window_count(self) -> int:
        return len(self.crack_timestamps)

    #: How far back a reader may look for the last answer. The acoustic probe
    #: writes -1 on any tick it does not answer, which on real roasts is most of
    #: them; a counter is cumulative, so the last answer still stands. Past this
    #: many samples the probe is genuinely silent and the reading is gone.
    _READ_LOOKBACK: int = 15

    def read_total(self) -> int | None:
        """Cumulative pops on the fused FC+SC channels, or None when nothing is
        counting — no channel configured, or the probe silent for a while.

        Public because the display needs the raw counter and cannot use the
        sliding window: that window is only fed while FC is still unmarked, and
        a readout has to keep reading through development. Unlike the marking
        path this one tolerates gaps: a missed BLE read is not a reset, and a
        bar that blinked out on every one of them would be unreadable.
        """
        fc = self._read_recent(self._cached_crack_device_idx,
                               self._cached_crack_device_channel)
        sc = self._read_recent(self._cached_sc_device_idx,
                               self._cached_sc_device_channel)
        if fc is None and sc is None:
            return None
        return (fc or 0) + (sc or 0)

    def crack_channel(self) -> "tuple[int, int] | None":
        """(extra-device index, channel) the acoustic counter is bound to, or
        None. What a drawing pass needs to walk the recorded series itself."""
        if self._cached_crack_device_idx == -1:
            return None
        return self._cached_crack_device_idx, self._cached_crack_device_channel

    def _read_recent(self, idx: int, channel: int) -> int | None:
        """Last answered value on a counter channel, within the lookback.

        Saved profiles carry the series interpolated to floats, so the integer
        part is the count — 0.0, 0.33, 0.67, 1.0 is one pop, not three.
        """
        if idx == -1 or getattr(self, 'aw_qmc', None) is None:
            return None
        qmc = self.aw_qmc
        try:
            if qmc.flagstart:
                series = qmc.extratemp1[idx] if channel == 1 else qmc.extratemp2[idx]
                for value in reversed(series[-self._READ_LOOKBACK:]):
                    if value is not None and value >= 0:
                        return int(value)
                return None
            rt = qmc.RTextratemp1 if channel == 1 else qmc.RTextratemp2
            value = rt[idx]
            return int(value) if value is not None and value >= 0 else None
        except (AttributeError, IndexError, TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# DryEndDetector — résultat de détection
# ---------------------------------------------------------------------------

class DryEndResult(NamedTuple):
    """
    Résultat émis à chaque tick par DryEndDetector.check_detection().

    confidence  : score composite [0.0 – 1.0] pour affichage progressif dans l'UI.
    is_fired    : True uniquement au tick de déclenchement de l'événement
                  (confirmation soutenue atteinte). False tous les autres ticks.
    score_a     : contribution du signal ratio RoR_BT/RoR_ET [0.0 – 1.0]
    score_b     : contribution du signal Δgap_slope [0.0 – 1.0]
    score_c     : contribution du signal BT_progress [0.0 – 1.0]
    score_d     : contribution du signal Agtron pente [0.0 – 1.0] (0 si absent)
    reason      : chaîne lisible décrivant ce qui a déclenché, vide si pas encore fired
    """
    confidence: float
    is_fired: bool
    score_a: float
    score_b: float
    score_c: float
    score_d: float
    reason: str


class DryEndDetector:
    """Dry End on the desktop: Artisan's turning point, its smoothed BT RoR (delta2) and the
    colour channel read from qmc, the decision taken by tilaucore.milestones.DryEnd, the engine
    the Android prototype shares.

    Roaster-agnostic: DE is bounded to the window around the plan target (else the profession
    band + the roaster's dry offset); inside it, the colour turn, the knee of the post-TP RoR
    bell and BT's position decide where to fire, with a force-fire at the window's top.
    """

    def __init__(self) -> None:
        self._core = DryEnd()
        self._tp_time: float = 0.0
        self.aw_qmc = None
        self._cached_color_device_idx: int = -1
        self._cached_color_channel:    int = -1
        self._last_diag_t: float = -1.0

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Remet le détecteur à zéro. À appeler au CHARGE."""
        self._core = DryEnd()
        self._tp_time = 0.0
        self._cached_color_device_idx = -1
        self._cached_color_channel    = -1
        self._last_diag_t = -1.0
        _log.info("DryEnd_Detector: reset.")

    def configure(self, aw: ApplicationWindow) -> None:
        self.aw_qmc = aw.qmc
        qmc = aw.qmc
        for i in range(len(qmc.extradevices)):
            if self._cached_color_device_idx != -1:
                break
            for ch, names in ((1, qmc.extraname1), (2, qmc.extraname2)):
                name = names[i].lower() if i < len(names) else ""
                if classify_extra_channel(name) == "color":
                    self._cached_color_device_idx = i
                    self._cached_color_channel    = ch
                    _log.info(f"DryEnd_Detector: Agtron found @ extra {i} ch{ch} ({name})")
                    break
        if self._cached_color_device_idx == -1:
            _log.info("DryEnd_Detector: no Agtron device — colour marker disabled.")
        self._core.colour_meter = self._cached_color_device_idx != -1

    def set_bean_context(self, bt_de_target: float, bt_tp: float = 0.0,
                         bt_dry_offset: float = 0.0, mode: str = 'C') -> None:
        """Resolve the physical DE window in the roaster's displayed BT frame.

        bt_de_target  : plan target (authoritative, offset already applied,
                        NATIVE unit — Artisan phases[1]). <=0 -> fall back to
                        the profession band shifted by bt_dry_offset.
        bt_dry_offset : roaster bean_temperature_offset_c[dry] (index 1). Only used
                        on the fallback path (°C frame, converted with the band).
        mode          : Artisan temperature unit ('C'/'F').
        """
        self._core.set_context(bt_de_target, bt_dry_offset, mode)
        if bt_tp > 0.0:
            self._core.set_tp(bt_tp)

    def check_detection(self, bt: float, et: float, current_time: float) -> DryEndResult:
        """Called every tick. `et` kept for signature compatibility (unused)."""
        if not self._core.fired:
            self._sync_tp_from_artisan()
        colour = self._get_agtron_value() if not self._core.fired and self._cached_color_device_idx != -1 else None
        r = self._core.check(bt, current_time, self._delta2(), colour)
        if r.fired:
            _log.info(f"DryEnd_Detector: FIRED @ t={current_time:.0f}s "
                      f"confidence={r.confidence:.3f} — {r.reason}")
        elif r.score_pos > 0.0 and current_time % 10 < 2 and current_time != self._last_diag_t:
            self._last_diag_t = current_time
            _log.info(f"DryEnd_Detector: t={current_time:.0f}s conf={r.confidence:.2f} BT={bt:.1f} "
                      f"pos={r.score_pos:.2f} morph={r.score_morph:.2f} color={r.score_color:.2f}")
        return DryEndResult(r.confidence, r.fired, r.score_pos, r.score_color, r.score_morph, 0.0, r.reason)

    # ------------------------------------------------------------------
    # What the shared detector is given from Artisan
    # ------------------------------------------------------------------

    def _sync_tp_from_artisan(self) -> None:
        """Consume Artisan's Turning Point (qmc.TPalarmtimeindex). temp2=BT,
        timex=absolute time, timeindex[0]=CHARGE. Read-only, once."""
        if self._core.tp_confirmed or self.aw_qmc is None:
            return
        qmc = self.aw_qmc
        tp_idx = getattr(qmc, "TPalarmtimeindex", None)
        if tp_idx is None:
            return
        try:
            charge_idx = qmc.timeindex[0]
            if charge_idx < 0:
                return
            bt_tp = float(qmc.temp2[tp_idx])
            self._tp_time = float(qmc.timex[tp_idx] - qmc.timex[charge_idx])
            self._core.set_tp(bt_tp)
            _log.info(f"DryEnd_Detector: TP from Artisan — BT_TP={bt_tp:.1f} @ t={self._tp_time:.0f}s")
        except (IndexError, TypeError, ValueError):
            return

    def _delta2(self) -> float | None:
        """Artisan's smoothed BT RoR at this sample; None lets the shared detector compute it."""
        d2 = getattr(self.aw_qmc, "delta2", None) if self.aw_qmc is not None else None
        if d2 and d2[-1] is not None:
            try:
                return float(d2[-1])
            except (TypeError, ValueError):
                pass
        return None

    def _get_agtron_value(self, offset: int = 0) -> float | None:
        if self.aw_qmc is None or self._cached_color_device_idx == -1:
            return None
        idx = self._cached_color_device_idx
        ch  = self._cached_color_channel
        try:
            if self.aw_qmc.flagstart:
                series = self.aw_qmc.extratemp1[idx] if ch == 1 else self.aw_qmc.extratemp2[idx]
            else:
                series = self.aw_qmc.RTextratemp1[idx] if ch == 1 else self.aw_qmc.RTextratemp2[idx]
            if not series:
                return None
            pos = -(offset + 1)
            if abs(pos) > len(series):
                return None
            return float(series[pos])
        except (IndexError, TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_fired(self) -> bool:
        return self._core.fired

    @property
    def bt_tp(self) -> float:
        return self._core.bt_tp

    @property
    def tp_confirmed(self) -> bool:
        return self._core.tp_confirmed

    @property
    def ratio_initial(self) -> float:
        """Deprecated (ratio signal removed). Kept for any external reader."""
        return 0.0
