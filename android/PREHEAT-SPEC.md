# Preheat on the tablet — TilauPID (draft, 2026-10-15; operator answers same day)

The tablet drives the drum to its charge temperature as the desktop's TilauPID
does. To validate before any code; it extends MACHINE-SPEC step D ("preheat PID on
START") and depends on A0 (the burner driven for real, with its protection).

## 1. What the desktop does today (read in the code)

**When.** Roast Setup's preheat box writes `tilaupid(START,<SV>)` on the START
button (the plan offers its charge temperature as SV). START therefore starts the
recording and the preheat together: the preheat is the part of the roast file before
CHARGE. It stops at CHARGE (`reason="charge"`), when the recording stops, on an
operator abort, or on a fault. `tilaupid(SV,<v>)` changes the target while it runs.

**Input.** One sample per sampling tick (cadence from Artisan's sampling delay): ET
when the machine has one, else BT (`pidSource`). Ambient temperature, humidity and
pressure from the ambient probe when it answers.

**Control law** (`tilaupid.py`, `compute_fuzzy_power`), all in °C:

    t_proj = t + RoR_4s · lead / 60
    burner = clamp(0, 80 %, P_ss · ambient_factor + Kp · (SV − t_proj) + I_hold)

- `Kp` 5 %/°C; `RoR_4s` a 4 s window (not the display RoR); `lead` 2.3–12 s,
  default 5 s.
- `P_ss`: the steady hold power; default `18 + SV/9.5` (the formula wins over
  `p_ss_default`).
- `ambient_factor`: 1 ± 0.3 %/°C away from 20 °C (plus small humidity and pressure
  terms), bounded to 0.85–1.15.
- `I_hold`: slow integral, only after a quiet dwell within 2 °C of SV, ±6 %.
- Hard cut to 0 at SV + 2 °C (backstop, not the set point).
- Output smoothing: changes under 2 % ignored, at most 12 % per cycle up or down; a
  cut to 0 is immediate.
- Burner ceiling 80 % (operator's hardware-preservation limit).

**Safety** (`tilaupid_safety.py`, already pure): temperature −10…350 °C,
|RoR| ≤ 120 °C/min, stale after 3.5 s, frozen probe (15 s flat while heating hard),
3 invalid samples latch a fault → burner 0; recovery needs 3 valid samples. A
watchdog cuts the burner when samples stop arriving (real roaster only). Any
exception in a cycle trips the fault (fail safe).

**Learning** (`tilaupid_adaptative.py`): two knobs per machine, control channel
and SV node — `P_ss` and `lead` — read at START, updated at the end of a preheat
whose hold qualified (EMA 0.3, about 5 preheats to converge; otherwise a slower
droop correction); previous values kept for a rollback. Seeded from past roasts of
the folder, but only those the guided preheat drove (`tilau_preheat_sv_c` in the
file). Stored in QSettings. A simulated preheat never learns.

**Recorded in the roast:** each burner change as an event (`S<n>:<v>%`), a
"TilauPID Preheat started" event (type 4, value = SV), and `tilau_preheat_sv_c`
(°C) — what makes the roast teach the next preheats.

**On screen:** target, projected temperature, time to target, and a learning
badge (how much history is behind P_ss and lead).

**Not part of the preheat:** `pid_autotune`, `pid_calibration*`, `pid_semantics`
(Artisan's own software PID), the thermal model shadow (offline candidate, read
only), the fan-assist brake (off by default).

## 2. Proposed model (shared, `tilaucore`, standard library)

One controller for both apps, as the plan engine:

- `tilaucore.preheat`: the law, the smoothing, the hold integral, the sensor guard
  (moved from `tilaupid_safety.py`), the learning arithmetic, the extraction of a
  past preheat from a roast file. Pure: no Qt, no clock, no storage of its own.
- Inputs per cycle: time, temperature (°C), ambient (optional). Output: the burner
  percentage, or a fault. The caller sends the command and records the event.
- Learned values through a small store interface: QSettings on the desktop, a JSON
  file on the tablet; each app keeps its own (decision 2).
- Desktop switched to it module by module, bench first (same burner command for
  the same sample stream, on recorded preheats), as for the plan engine.

## 3. On the tablet

- Roast Setup: a preheat target (the plan's charge temperature offered, as on the
  desktop); Start recording starts the preheat when a target is set.
- Roast screen: the "Preheat" phase already exists; it shows target, projected
  temperature and time to target, and the burner the PID chose. Touching the burner
  **pauses** the preheat: the operator's value holds, and the preheat can be
  re-armed from the same place (decision 4). Mockup first.
- Learning ported as it is on the desktop, in the first tablet version (decision 3),
  ambient correction included, from TilauAmbient (decision 5).
- The controller runs in the session service (Python), never in the page: it keeps
  running with the screen off.
- Link loss (decision 1, as `tc4ble` does on the desktop): the V2 firmware
  emergency-stops when the link goes; on connecting, the controller asserts a default
  burner (100 % observed), so `OT1,0` is sent first and confirmed by a fresh 0 echo,
  else the link is dropped as unsafe; a silent link (connected but no telemetry) is
  forced to reconnect; reconnection backs off to 2 s at most. The tablet's link
  (`Tc4Link.kt`, A0) does the same before the preheat may drive the burner.
- The roast file carries the same marker, event and burner events, so the desktop
  learns from tablet preheats and the tablet from the computer's roasts (the tablet
  already reads both folders).

## 4. Order

| Step | What |
|---|---|
| P1 | Move the pure parts to `tilaucore`; desktop on it; bench: identical burner commands on recorded and simulated preheats — *done and validated 2026-10-15*: `preheat` (law), `preheat_safety`, `preheat_learning` (learning, scanner, `SettingsStore`), `preheat_thermal` |
| A0 | Burner, air, drum sent to the real V2 and acknowledged; protection tests (MACHINE-SPEC) |
| P2 | Tablet preheat with its learning: mockup, then code; simulated machine first, then the real V2 — *done and validated 2026-10-16 on the real V2, empty drum*: controller in `tilaucore.preheat_controller`, tablet `TabletPreheat` (JSON store, both roast folders), watched from the roast's first reading |

## 5. Decisions (operator, 2026-10-15)

1. Link loss: handled as on the desktop's `tc4ble` (above).
2. Learned values: each app learns on its own, seeded from the roasts it holds (the
   tablet reads its own and the computer's); no shared store — both converge as the
   roast files travel.
3. Learning: ported as it is, in the first tablet version.
4. Operator touching the burner: the preheat pauses and can be re-armed.
5. Ambient correction: kept, as on the desktop.
