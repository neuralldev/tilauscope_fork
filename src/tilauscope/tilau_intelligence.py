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
from tilauscope.tilauscope_types import (resolve_de_window, resolve_fc_window,
                                         classify_extra_channel,
                                         resolve_crack_channel)

_logd: Final[logging.Logger] = logging.getLogger("tilau")
_log: Final[logging.Logger] = logging.getLogger(__name__)

# Extra-device channel classification lives in tilauscope_types: the drawing
# pass needs it too, and this module imports artisanlib.main — which the
# curve must never pull in. Re-exported here for existing callers.

class FirstCrackDetector:
    """
    Advanced First Crack detection using a sliding time window and
    thermodynamic gating.
    """

    def __init__(self):
        # Configuration (could be moved to QSettings later)
        self.window_seconds: float = 35.0  # Detection window — widened to handle sparse FC onset
                                            # (natural/light FC cracks can be 10-30s apart initially;
                                            #  7s was too tight and kept purging isolated early cracks)
        self.threshold: int = 4           # Min cracks in window to trigger

        # State
        self.crack_timestamps = deque()
        self.last_count: int = 0
        self.is_fired: bool = False
        # position-anchored FC state
        self._armed: bool = False              # BT approached the FC window from below
        self._pos_since: float | None = None   # position-base confirmation timer
        self._CONFIRM_S: float = 4.0
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

        self.params: dict = {
            "FC": [4, 90.0, 2.0, 25.0],
            "SC": [4, 50.0, 1.0, 45.0]
        }

    def reset(self):
        self.crack_timestamps.clear()
        self.last_count = 0
        self.is_fired = False
        self._armed = False
        self._pos_since = None
        self._banked_count = None
        self._cached_crack_device_idx = -1
        self._cached_crack_device_channel = -1
        self._cached_sc_device_idx = -1
        self._cached_sc_device_channel = -1
        self._sc_raw_at_fc = None
        self._fc_tally = 0

    def detect_extradevice(self, aw: ApplicationWindow) -> int | None:
        self.aw_qmc = aw.qmc
        # Load configuration from Artisan AppWindow
        self.window_seconds = float(getattr(aw, "TilauScopeFCWindow", 35.0))
        self.threshold      = int(getattr(aw, "TilauScopeFCTreshold", 4))
        self.params         = getattr(aw, "TilauScopeCrackParams", self.params)

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
        """Position-anchored First Crack (same proven architecture as
        DryEnd). The crack counter over-counts pre-FC noise on real setups, so pops
        are NOT the primary trigger: the physical window is the base, and a pop
        BURST only corroborates AT/ABOVE the target (never below -> cannot fire on
        pre-FC noise). The pop counter is the fused FC+SC channel. Colour and RoC
        play no role at FC (no reliable colour threshold; RoR is a DryEnd signal,
        negative-sloped by FC) — both stay DryEnd-only.

        Window: plan target_fcs (native units) -> point +/- half; else profession
        FC band (resolve_fc_window). Returns the FC timestamp when fired, else False.
        """
        if self.is_fired:
            return False

        # --- resolve the FC window in the roast's own unit frame ---
        half = 9.0 if mode == 'F' else 5.0
        if target_fcs and target_fcs > 0.0:
            band_lo = band_hi = float(target_fcs)
            fc_lo, fc_hi = band_lo - half, band_hi + half
        else:
            fc_lo, fc_hi, band_lo, band_hi = resolve_fc_window(0.0, 0.0)   # profession (C)
            if mode == 'F':
                fc_lo, fc_hi, band_lo, band_hi = (v * 9.0 / 5.0 + 32.0
                                                  for v in (fc_lo, fc_hi, band_lo, band_hi))

        raw = self._get_crack_counter_value()
        if raw is not None:
            self.last_count = raw                      # keep the UI badge current

        # --- below the window: arm from below, bank no pops (reject pre-FC noise) ---
        if current_bt < fc_lo:
            self._armed = True
            return False
        if not self._armed:                            # entered window without approaching from below
            return False

        # --- fail-safe: FC cannot be later than band_hi + half ---
        if current_bt >= fc_hi:
            self.is_fired = True
            self._snapshot_at_fire()
            _log.info(f"FC_Detector: FIRED force@FC_hi (BT={current_bt:.1f}>={fc_hi:.1f})")
            return current_time

        # --- in-window: bank NEW pops (delta vs a private banked tracker), purge ---
        prev = getattr(self, "_banked_count", None)
        if raw is not None:
            if prev is None:
                self._banked_count = raw          # baseline: pops before entering window ignored
            elif raw > prev:
                for _ in range(raw - prev):
                    self.crack_timestamps.append(current_time)
                self._banked_count = raw
        while self.crack_timestamps and (current_time - self.crack_timestamps[0] > self.window_seconds):
            self.crack_timestamps.popleft()
        audio = len(self.crack_timestamps)

        # --- pop BURST advancer: only AT/ABOVE the band (>= target / band_lo) ---
        if audio >= self.threshold and current_bt >= band_lo:
            self.is_fired = True
            self._snapshot_at_fire()
            _log.info(f"FC_Detector: FIRED burst ({audio} pops, BT={current_bt:.1f})")
            return self.crack_timestamps[0]

        # --- position base: BT reached the band (target) with a short confirm ---
        if current_bt >= band_hi:
            if self._pos_since is None:
                self._pos_since = current_time
            if (current_time - self._pos_since) >= self._CONFIRM_S:
                self.is_fired = True
                self._snapshot_at_fire()
                _log.info(f"FC_Detector: FIRED position (BT={current_bt:.1f}>={band_hi:.1f})")
                return current_time
        else:
            self._pos_since = None

        return False

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
    """Dry-End detector — physical window + sensor-priority cascade.

    Roaster-agnostic. No RoR_BT/RoR_ET ratio, no ET-BT gap assumption (both are
    roaster-type dependent). DE is physically bounded to [band-5, band+5] in the
    roaster's displayed BT frame; the markers only decide WHERE inside that window
    to fire, with a hard force-fire at band_hi+5.

    Target window (set via set_bean_context, resolved by tilauscope_types,
    in the roast's own unit frame — half is +/-5 °C or +/-9 °F, and the
    profession fallback band is converted when Artisan runs in °F):
        plan target (authoritative, offset already applied)  -> point +/- half
        else profession band + roaster dry sensor offset      -> band +/- half

    Markers (priority by available sensors), evaluated only inside the window:
        S_color : Agtron Rate-of-Colour turned sustained-negative (browning onset)
                  = DE at the onset of the negative slope. Primary when colour live.
        S_morph : post-TP RoR bell knee (RoR dropped from its peak AND flattening
                  or dipping). Uses Artisan's smoothed delta2. Primary without colour.
        S_pos   : BT position inside the window. Weak prior + (with the force-fire)
                  the fail-safe; never fires on its own.
    """

    _BUFFER_SIZE: Final[int] = 240          # ~8 min @ 0.5 Hz, covers all windows
    _ROR_WINDOW_S: Final[float] = 30.0      # fallback RoR window (when no delta2)

    _FIRE_THRESHOLD:     Final[float] = 0.75
    _CONFIRM_DURATION_S: Final[float] = 4.0  # light debounce; onset persistence is in S_color

    # Colour (Agtron/min) — onset of sustained browning
    _COLOR_SLOPE_WINDOW_S: Final[float] = 30.0
    _COLOR_SLOPE_NEG:      Final[float] = -0.8   # Agtron/min below which it darkens
    _COLOR_ONSET_S:        Final[float] = 6.0    # sustained-negative duration -> full
    _COLOR_MIN_SAMPLES:    Final[int]   = 5
    _COLOR_VALID_MIN:      Final[float] = 0.0    # Omniflux -1 -> invalid, skip
    _AG_PEAK_DROP_MIN:     Final[float] = 1.0    # Agtron units below in-window peak
                                                 # to confirm a real (non-noise) peak

    # Morphology of the post-TP RoR bell (Artisan smoothed delta2)
    _MORPH_SLOPE_WINDOW_S: Final[float] = 30.0
    _MORPH_DROP_FULL:      Final[float] = 0.45   # calibrated: median drop ~0.43 at DE
    _MORPH_FLAT_SCALE:     Final[float] = 4.0    # |dRoR/dt| (C/min^2) scale for flat/creux
    _ROR_PEAK_MIN:         Final[float] = 3.0    # ignore tiny (noise) peaks

    # Confidence blend. Position (plan target) is the reliable backbone across all
    # validated roasts; morphology advances it; colour can only ADVANCE the fire
    # (max-blend) and never starves the base — robust when colour is absent,
    # stuck at -1, or behaving unexpectedly (e.g. Agtron rising through DE).
    _POS_W:       Final[float] = 0.75
    _MORPH_W:     Final[float] = 0.25
    _COLOR_W:     Final[float] = 0.90
    _COLOR_POS_W: Final[float] = 0.10

    def __init__(self) -> None:
        self._bt_buf: deque[float] = deque([0.0] * self._BUFFER_SIZE, maxlen=self._BUFFER_SIZE)
        self._t_buf:  deque[float] = deque([0.0] * self._BUFFER_SIZE, maxlen=self._BUFFER_SIZE)
        self._ror_buf:   deque[float] = deque(maxlen=self._BUFFER_SIZE)
        self._ror_t_buf: deque[float] = deque(maxlen=self._BUFFER_SIZE)
        self._ag_buf:    deque[float] = deque(maxlen=self._BUFFER_SIZE)
        self._ag_t_buf:  deque[float] = deque(maxlen=self._BUFFER_SIZE)

        # turning point (from Artisan)
        self._bt_tp:        float = 0.0
        self._tp_confirmed: bool  = False
        self._tp_time:      float = 0.0

        # resolved DE window (displayed BT frame)
        self._de_lo:   float = 0.0
        self._de_hi:   float = 0.0
        self._band_lo: float = 0.0
        self._band_hi: float = 0.0
        self._unit_scale: float = 1.0   # 1.8 in °F — scales °C-doctrine RoR thresholds

        # marker state
        self._ror_peak:        float = 0.0
        self._ag_peak:         float = -1.0   # in-window Agtron peak (DE candidate)
        self._color_neg_since: float | None = None

        # devices
        self.aw_qmc = None
        self._cached_color_device_idx: int = -1
        self._cached_color_channel:    int = -1

        # firing state
        self.is_fired:       bool = False
        self._armed:         bool = False   # True once BT approached the window from below
        self._confirm_since: float | None = None

        # diagnostics
        self._diag_logged: bool = False
        self._last_diag_t: float = -1.0

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Remet le détecteur à zéro. À appeler au CHARGE."""
        self._bt_buf = deque([0.0] * self._BUFFER_SIZE, maxlen=self._BUFFER_SIZE)
        self._t_buf  = deque([0.0] * self._BUFFER_SIZE, maxlen=self._BUFFER_SIZE)
        self._ror_buf.clear(); self._ror_t_buf.clear()
        self._ag_buf.clear();  self._ag_t_buf.clear()

        self._bt_tp = 0.0
        self._tp_confirmed = False
        self._tp_time = 0.0

        self._de_lo = self._de_hi = self._band_lo = self._band_hi = 0.0
        self._unit_scale = 1.0

        self._ror_peak = 0.0
        self._ag_peak = -1.0
        self._color_neg_since = None

        self._cached_color_device_idx = -1
        self._cached_color_channel    = -1

        self.is_fired = False
        self._armed = False
        self._confirm_since = None

        self._diag_logged = False
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

    def set_bean_context(self, bt_de_target: float, bt_tp: float = 0.0,
                         bt_dry_offset: float = 0.0, mode: str = 'C') -> None:
        """Resolve the physical DE window in the roaster's displayed BT frame.

        bt_de_target  : plan target (authoritative, offset already applied,
                        NATIVE unit — Artisan phases[1]). <=0 -> fall back to
                        the profession band shifted by bt_dry_offset.
        bt_dry_offset : roaster bean_temperature_offset_c[dry] (index 1). Only used
                        on the fallback path (°C frame, converted with the band).
        mode          : Artisan temperature unit ('C'/'F') — same contract as the
                        FC detector: half-window and the profession fallback band
                        are resolved in the roast's own unit frame.
        """
        self._unit_scale = 1.8 if mode == 'F' else 1.0
        half = 9.0 if mode == 'F' else 5.0
        if bt_de_target and bt_de_target > 0.0:
            # plan target is native; only the half-window scales with the unit
            de_lo, de_hi, band_lo, band_hi = resolve_de_window(
                bt_de_target, bt_dry_offset, half_c=half)
        else:
            # profession band + offset are °C-frame -> resolve in °C, then convert
            de_lo, de_hi, band_lo, band_hi = resolve_de_window(0.0, bt_dry_offset)
            if mode == 'F':
                de_lo, de_hi, band_lo, band_hi = (
                    v * 9.0 / 5.0 + 32.0 for v in (de_lo, de_hi, band_lo, band_hi))
        self._de_lo, self._de_hi = de_lo, de_hi
        self._band_lo, self._band_hi = band_lo, band_hi
        if bt_tp > 0.0:
            self._bt_tp = bt_tp
            self._tp_confirmed = True
        _log.debug(
            f"DryEnd_Detector: window set — band=[{band_lo:.1f},{band_hi:.1f}] "
            f"gate=[{de_lo:.1f},{de_hi:.1f}] "
            f"(plan_target={bt_de_target:.1f} dry_offset={bt_dry_offset:+.1f})"
        )

    def check_detection(self, bt: float, et: float, current_time: float) -> DryEndResult:
        """Called every tick. `et` kept for signature compatibility (unused)."""
        self._bt_buf.append(bt)
        self._t_buf.append(current_time)

        if not self.is_fired:
            self._sync_tp_from_artisan()
            self._accumulate_ror()
            self._accumulate_agtron()

        # need a confirmed TP and a resolved window
        if not self._tp_confirmed or self._de_hi <= 0.0:
            return DryEndResult(0.0, False, 0.0, 0.0, 0.0, 0.0, "")

        if self.is_fired:
            return DryEndResult(1.0, False, 0.0, 0.0, 0.0, 0.0, "")

        # below the window: physically impossible -> idle. Arm: we are approaching
        # the window from below (the rising post-TP limb where DE actually occurs).
        if bt < self._de_lo:
            self._armed = True
            return DryEndResult(0.0, False, 0.0, 0.0, 0.0, 0.0, "")

        # never fire if TP was confirmed while BT was already above the window
        # (initial post-charge plunge / edge cases): wait to be armed from below.
        if not self._armed:
            return DryEndResult(0.0, False, 0.0, 0.0, 0.0, 0.0, "")

        # fail-safe: at/over band_hi+5 -> force fire (can't be later)
        if bt >= self._de_hi:
            self.is_fired = True
            reason = f"force@DE_hi (BT={bt:.1f}>={self._de_hi:.1f})"
            _log.info(f"DryEnd_Detector: FIRED @ t={current_time:.0f}s force — {reason}")
            return DryEndResult(1.0, True, 1.0, 0.0, 0.0, 0.0, reason)

        # in-window markers
        s_pos   = self._score_pos(bt)
        s_morph = self._score_morph()
        base    = self._POS_W * s_pos + self._MORPH_W * s_morph

        color_live, s_color = self._score_color(current_time)
        if color_live and s_color > 0.0:
            color_conf = self._COLOR_W * s_color + self._COLOR_POS_W * s_pos
            confidence = max(base, color_conf)
        else:
            confidence = base
        confidence = max(0.0, min(1.0, confidence))

        if current_time % 10 < 2 and current_time != self._last_diag_t:
            self._last_diag_t = current_time
            _log.info(
                f"DryEnd_Detector: t={current_time:.0f}s conf={confidence:.2f} BT={bt:.1f} "
                f"pos={s_pos:.2f} morph={s_morph:.2f} "
                f"color={s_color:.2f}{'' if color_live else '(off)'} rorpeak={self._ror_peak:.1f}"
            )

        if confidence >= self._FIRE_THRESHOLD:
            if self._confirm_since is None:
                self._confirm_since = current_time
        else:
            self._confirm_since = None

        if (self._confirm_since is not None
                and (current_time - self._confirm_since) >= self._CONFIRM_DURATION_S):
            self.is_fired = True
            reason = self._build_reason(s_pos, s_color, s_morph, color_live)
            _log.info(f"DryEnd_Detector: FIRED @ t={current_time:.0f}s "
                      f"confidence={confidence:.3f} — {reason}")
            return DryEndResult(confidence, True, s_pos, s_color, s_morph, 0.0, reason)

        return DryEndResult(confidence, False, s_pos, s_color, s_morph, 0.0, "")

    # ------------------------------------------------------------------
    # Turning Point (Artisan)
    # ------------------------------------------------------------------

    def _sync_tp_from_artisan(self) -> None:
        """Consume Artisan's Turning Point (qmc.TPalarmtimeindex). temp2=BT,
        timex=absolute time, timeindex[0]=CHARGE. Read-only, once."""
        if self._tp_confirmed or self.aw_qmc is None:
            return
        qmc = self.aw_qmc
        tp_idx = getattr(qmc, "TPalarmtimeindex", None)
        if tp_idx is None:
            return
        try:
            charge_idx = qmc.timeindex[0]
            if charge_idx < 0:
                return
            self._bt_tp        = float(qmc.temp2[tp_idx])
            self._tp_time      = float(qmc.timex[tp_idx] - qmc.timex[charge_idx])
            self._tp_confirmed = True
            _log.info(f"DryEnd_Detector: TP from Artisan — BT_TP={self._bt_tp:.1f} @ t={self._tp_time:.0f}s")
        except (IndexError, TypeError, ValueError):
            return

    # ------------------------------------------------------------------
    # Accumulators (run every tick, post-TP)
    # ------------------------------------------------------------------

    def _accumulate_ror(self) -> None:
        """Feed the RoR history (from Artisan delta2, else computed) and track the
        post-TP peak. The peak anchors the morphology knee."""
        if not self._tp_confirmed:
            return
        r = self._ror_bt()
        if r is None:
            return
        self._ror_buf.append(r)
        self._ror_t_buf.append(self._t_buf[-1])
        if r > self._ror_peak:
            self._ror_peak = r

    def _accumulate_agtron(self) -> None:
        if self._cached_color_device_idx == -1:
            return
        v = self._get_agtron_value()
        if v is None or v < self._COLOR_VALID_MIN:   # Omniflux -1 -> skip (not live)
            return
        self._ag_buf.append(v)
        self._ag_t_buf.append(self._t_buf[-1])

    # ------------------------------------------------------------------
    # Markers
    # ------------------------------------------------------------------

    def _score_pos(self, bt: float) -> float:
        """BT position in the window: 0 at de_lo, ramps to 1 at band_lo, 1 in band."""
        if bt <= self._de_lo:
            return 0.0
        if bt >= self._band_hi:
            return 1.0
        # ramp across the whole gate up to band_hi: peaks at the late edge so it
        # cannot fire alone early inside a wide (roaster-fallback) band.
        return (bt - self._de_lo) / (self._band_hi - self._de_lo)

    def _score_color(self, current_time: float) -> tuple[bool, float]:
        """(live, score). DE = the Agtron PEAK followed by a permanent descent
        (RoC turns and stays negative). Peak tracking is window-gated (caller only
        calls this in-window), so the pre-TP / pre-DE fluctuation is excluded.
        Returns live=False when the colour channel has no usable live data.

        NB on current Omniflux output the Agtron peak lags the thermal DE by a few
        degrees and the RoC is noisy; the max-blend keeps this purely an *advancer*,
        so a late peak never delays the position-anchored fire."""
        if self._cached_color_device_idx == -1 or not self._ag_buf:
            return (False, 0.0)
        ag_now = self._ag_buf[-1]
        if ag_now > self._ag_peak:
            self._ag_peak = ag_now            # in-window running peak (DE candidate)
        slope = self._regress_slope(self._ag_buf, self._ag_t_buf,
                                    self._COLOR_SLOPE_WINDOW_S, self._COLOR_MIN_SAMPLES)
        if slope is None:
            return (False, 0.0)               # not enough live colour data
        roc = slope * 60.0                    # Agtron / minute (computed RoC)
        descended = (self._ag_peak - ag_now) >= self._AG_PEAK_DROP_MIN
        if descended and roc <= self._COLOR_SLOPE_NEG:
            if self._color_neg_since is None:
                self._color_neg_since = current_time
            dur = current_time - self._color_neg_since
            return (True, max(0.0, min(1.0, dur / self._COLOR_ONSET_S)))
        self._color_neg_since = None
        return (True, 0.0)

    def _score_morph(self) -> float:
        """Post-TP RoR bell knee: RoR dropped from its peak (drop) AND flattening or
        dipping (flat/creux). min() of both so a steep descent does not score."""
        # RoR series is in the native unit — °C-doctrine thresholds scale ×1.8 in °F
        if self._ror_peak < self._ROR_PEAK_MIN * self._unit_scale:
            return 0.0
        r_now = self._ror_bt()
        if r_now is None:
            return 0.0
        drop = (self._ror_peak - r_now) / self._ror_peak
        drop_score = max(0.0, min(1.0, drop / self._MORPH_DROP_FULL))
        slope = self._regress_slope(self._ror_buf, self._ror_t_buf,
                                    self._MORPH_SLOPE_WINDOW_S, 5)
        if slope is None:
            return 0.0
        slope_min2 = slope * 60.0   # °/min per minute (native unit)
        if slope_min2 >= 0.0:
            flat_score = 1.0                                   # creux (turning up)
        else:
            flat_score = max(0.0, 1.0 - (-slope_min2) / (self._MORPH_FLAT_SCALE * self._unit_scale))
        return max(0.0, min(1.0, min(drop_score, flat_score)))

    # ------------------------------------------------------------------
    # Numeric helpers
    # ------------------------------------------------------------------

    def _ror_bt(self) -> float | None:
        """BT RoR (C/min). Prefer Artisan's smoothed delta2, else compute."""
        qmc = self.aw_qmc
        if qmc is not None:
            d2 = getattr(qmc, "delta2", None)
            if d2:
                v = d2[-1]
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        pass
        return self._ror(self._bt_buf)

    def _idx_back_by_time(self, seconds: float) -> int | None:
        n = len(self._t_buf)
        if n < 2:
            return None
        target = self._t_buf[-1] - seconds
        for back in range(1, n):
            if self._t_buf[-1 - back] <= target:
                return n - 1 - back
        return None

    def _ror(self, buf: deque[float], window_s: float = _ROR_WINDOW_S) -> float:
        idx = self._idx_back_by_time(window_s)
        if idx is None:
            return 0.0
        dt = self._t_buf[-1] - self._t_buf[idx]
        if dt <= 0:
            return 0.0
        return (buf[-1] - buf[idx]) / dt * 60.0

    @staticmethod
    def _regress_slope(vals: deque[float], ts: deque[float],
                       window_s: float, min_n: int) -> float | None:
        """Least-squares slope (unit/second) over the most recent `window_s`.
        None if fewer than `min_n` points in the window."""
        n = len(ts)
        if n < min_n:
            return None
        cutoff = ts[-1] - window_s
        xs: list[float] = []
        ys: list[float] = []
        for i in range(n - 1, -1, -1):
            if ts[i] < cutoff:
                break
            xs.append(ts[i]); ys.append(vals[i])
        m = len(xs)
        if m < min_n:
            return None
        sx = sum(xs); sy = sum(ys)
        sxx = sum(x * x for x in xs); sxy = sum(x * y for x, y in zip(xs, ys))
        den = m * sxx - sx * sx
        if den == 0:
            return None
        return (m * sxy - sx * sy) / den

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

    @staticmethod
    def _build_reason(pos: float, color: float, morph: float, color_live: bool) -> str:
        parts = []
        if color_live and color >= 0.5:
            parts.append(f"Agtron_peak_descent({color:.2f})")
        if morph >= 0.5:
            parts.append(f"RoR_knee({morph:.2f})")
        if pos >= 0.5:
            parts.append(f"BT_in_band({pos:.2f})")
        return " + ".join(parts) if parts else "composite"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def bt_tp(self) -> float:
        return self._bt_tp

    @property
    def tp_confirmed(self) -> bool:
        return self._tp_confirmed

    @property
    def ratio_initial(self) -> float:
        """Deprecated (ratio signal removed). Kept for any external reader."""
        return 0.0