# Simulation on the tablet — spec, 2026-10-20

To validate before any code. Goal: work on the tablet (alarms, plan, preheat, screens)
without the roaster or the accessories, as the desktop's simulator allows.

## 1. What exists

**Desktop** (`artisanlib/simulator.py`, `main.simulate`). The operator opens a recorded
`.alog`; the sampling loop reads BT, ET and the extra channels from it instead of the
devices, interpolated at the clock's time, from the file's first valid BT (its START).
Past the file's end the last reading holds. Milestones are marked by hand. The speed is
1×, 2× or 8× (TilauScope's segments on the curve, `tilau_set_simulator_speed`). The
machine setup stays the operator's; the band names the replayed roast
(`simulation_source`: its title, else the file name).

**Tablet** (`demo.py`). A simulated machine runs only when no roaster is declared:
a synthetic BT curve (`PROFILE`, "a software test, not a suggested roast"), levers
confirmed at the next tick, the **Simulation** badge in the header, roasts saved with
`tilau_simulated` (never in any learning). Testing alarms today means setting the
roaster to None in the config, then restoring it.

## 2. Decisions (operator, 2026-10-20)

1. **The curve is a recorded roast**: an `.alog` from the tablet's roasts or the
   computer's, replayed as the desktop replays it (BT, ET, extra channels). The
   synthetic curve is left only to a tablet with no declared roaster.
2. **Started from a roast** (mockup v2, 2026-10-20, artifact KaZYH7qXwA8hmKLCKy1H7g): a
   replay picto on a roast of BeanCave › Roasts opens the roast screen in simulation with
   that roast; no Settings page. The machine, its `.aset`, levers, event buttons and alarm
   lists stay the real ones; nothing is sent over Bluetooth, no device is connected.
   Commands are logged as sent and the echo is simulated, as the simulated machine does.
3. **Every device is simulated**: roaster and accessories. Extra channels the tablet knows
   (`tilau_name_map`: AirWave, TilauAmbient) come from the file.
4. **Milestones by hand**, as on the desktop; only the curve is replayed. Speeds 1×,
   2×, 8×.
5. **Exit takes the place of Stop**: back to the real roaster; a simulated roast in
   progress is dropped, never saved, and the levers return to their levels before the
   replay. To test the end of a roast, the replay runs to Drop and the roast ends as usual.

## 3. Behaviour

- **Roast screen**: the link pill reads Simulation (mauve); a replay bar shows the
  position in the file over its whole length (preheat included) with 1× 2× 8×; Exit.
- **Pause** (operator, 2026-10-20): the first segment of the speeds, ⏸ 1× 2× 8× (speed 0).
  Paused, nothing is sampled, no alarm fires, the preheat and the roast clock stand still;
  levers and milestones stay usable, recorded at the paused instant. A speed resumes; ⏸
  touched again while paused resumes at the speed chosen before.
- **Clock**: the replay starts at Start, from the file's first valid BT. One sample per
  simulated second at every speed, so alarms, RoR and the preheat see a 1 Hz stream.
  Before Start the screen shows the file's first reading; past the file's end the last
  reading holds (desktop).
- **Refused** while a roast is on screen (recording, or over and not yet left).
- **No stock move**: there are no beans in a replay.
- **Preheat**: watched on the replayed curve; burner commands logged, never learns.
- **End roast**: as with the simulated machine; the cool-first sequence belongs to the
  real link and does not run. Roast file: `tilau_simulated`.
- Without a declared roaster, the synthetic simulated machine stays as before.

## 3b. S3 — a roaster that reacts (operator, 2026-10-21)

Goal: check that the automations (auto milestones, crack sequence, Follow) react, without the
machine. Realism is enough when the curve answers the levers in the right direction and order of
size; it is not a model to learn or steer from.

- The replayed roast stays the reference curve. From the simulated CHARGE to its DROP, the BT
  moves away from it by how far each lever is from the recorded roast's at the same moment (a
  lever the recorded roast never moved: by its moves since CHARGE). *Amended 2026-10-21*: a gap
  counted from the levers held at CHARGE read a burner at 0 then set to the recorded 75 as +75
  points (RoR near 40 °C/min).
- RoR offset = Σ gain × that gap, the gap felt through the probe's dead time then a first-order
  lag; the BT offset is its integral. ET is replayed unchanged. The gain of the phase is in what
  is lagged, so entering Maillard brings the air in as a move would, never as a step.
- A Follow test means something when the roast simulated is the roast followed: another one
  keeps its own curve, moved only by the levers' gap to it.
- Values (`tilaucore.lever_response`), measured on the corpus (Skywalker V2), 2026-10-21:

  | Lever | Phase | Gain on the BT's RoR | Lag |
  |---|---|---|---|
  | Burner | all | +0.4 °C/min per point (10 latest roasts: 10/10 positive, per roast 0.04–1.9, pooled out of sample 0.39) | dead 5.5 s, τ 30 s (half at ≈ 26 s on isolated moves) |
  | Air | Maillard (DE→FC) | +0.33 °C/min per % (23 isolated steps: +1.7 per 5 % step at +45 s, 19/23 positive, placebo drift −0.5) | dead 5.5 s, τ 15 s |
  | Air | drying, development | 0 (not measured; in development the air chases the smoke, operator) | — |
  | Drum, extractor | all | 0 | — |

  The corpus is a closed loop (the operator moves a lever because the curve drifts): the burner's
  size is known within a factor of two, the air's sign only shows on its own steps in Maillard.

## 4. Open questions

- None.

## 5. Order

| Step | What |
|---|---|
| S1 | Replay engine in `tilaucore` (reads an `.alog`, gives BT, ET and the extra channels at a time, desktop's interpolation and hold); test against `Simulator.read` on corpus files — *done and validated 2026-10-20*: `tilaucore.roast_replay.Replay`, identical to `Simulator.read` bit for bit on 107 roasts × C/F (numpy's search where times step back, its fused multiply-add) |
| S2 | Mockup (v2: from a BeanCave roast, replay bar, Exit in place of Stop), then code: `simulate`, `set_speed`, `exit_simulation`, devices not connected, the 1×/2×/8× clock — *done and validated 2026-10-20* on the Honor Pad 9: pause (⏸, touched again resumes), the preheat on the replay in simulated seconds, Exit gives the levers back; with it the preheat is built between roasts (Start immediate) and its axis starts at 0 °C |
| S3 | A roaster that reacts to burner and air (§3b): `tilaucore.lever_response`, wired into the simulated reading |
