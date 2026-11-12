# Guided mode and AUTO on the tablet (SPEC §M4) — spec, 2026-11-07

To validate before any code. Operator, 2026-11-07: "the same thing as on the computer". Roast
Replay is already on the tablet (AUTOMATION-SPEC D2). It replays a recorded roast's levers, so it
cannot serve a coffee never roasted. The guided mode and AUTO follow the plan computed for the
coffee, which the tablet already builds (`tilaucore.roast_plan.generate_roast_plan`).

## 1. What the desktop does (read in the code)

All of it lives in `src/tilauscope/roast_asssistant.py` (8 161 lines, Qt) and in the
`guidance_*.py` modules (~1 150 lines, pure Python, no Qt).

**Three ways to follow a plan**, on the coach switch and the operator level:

- **Expert / Manual**: one coach line under the figures. It shows deviation advice
  (`_ror_deviation_advice`) and safety alerts, and stays silent when nothing is useful.
- **Guided**: a gesture card leads the phase page (`_GestureHero`). It shows what to do now,
  the next step, and how long until the next milestone; the figures fold under *Details ›*.
  The steps come from the plan's ramps (`_plan_steps`: `Heater Ramp`, `Air Ramp`, `Dev Ramp`;
  in development, by hand, the levers move by whole 5 % stages). `_gesture_steps` asks for a
  step once, when BT is within `NOW_WINDOW_C` (1 °C) of its threshold. A step stays asked for
  until the lever holds its value, and a burner step up waits while the RoR is above target.
  Per phase:
  - Drying: from charge to the turning point, the card is blank. Then it shows "Now: Burner
    X %", or "Hold the burner · Next: …", or "Dry end · In about m:ss".
  - Maillard: "Now: Burner X %", or "Listen · First crack soon", or the next step "At N°", or
    "First crack · In about …". A button carries out the burner step shown.
  - Development: "Now: Drop at N°" within 1 °C of the drop, otherwise "Now: <step> · Drop at
    N°", otherwise "Drop at N° · In about …".
- **AUTO** (`_ap_*`): it executes the live plan. It never chases a RoR gap.
  - Armed by the AUTO chip. It is refused without a plan; a grid-only plan is the operator's
    call (2026-10-30).
  - At each milestone it sets that phase's plan levers (*feedforward*). After the TP, the
    burner follows `Heater Ramp` and the air follows `Air Ramp` from mid-Maillard. In
    development, `Dev Ramp` brings the burner down and the air up. A step fires only when BT
    crosses its threshold going up, so the pre-TP dip fires nothing.
  - In development the burner only goes down, at most 5 %/min from FC to FC + 75 s.
  - It marks Dry end and First crack itself from the detectors: no confirm prompt, and the
    milestone button is only a fallback. First crack is never marked on the plan's temperature
    alone.
  - Auto-DROP: the plan's drop temperature is held for 3 ticks, then a 10 s countdown runs with
    a beep and a Cancel button. Then it marks DROP, sets the cooling levers and disarms.
  - Crash: before development, AUTO pauses and the message tells the operator what to do. In
    development, the safety net raises the air by 5 % every 30 s, up to 3 stages, until the RoR
    gains 0.5 °C/min. On a coffee never roasted the burner follows the air (`_burner_may_rise`),
    capped by `dev_heater_max_pct`.
  - It pauses on any lever move it did not make. It skips three things: its own echo, the
    AirWave PID's dithering (< 2 % on the extractor), and the first 8 s after charge. It also
    pauses when BT goes stale, and after 3 failed ticks in a row. Resume is by the chip, with
    no move on resume.
  - While armed, the phase page gives way to a cockpit: AUTO · phase · clock, a single status
    line (the next ramp step, or the safety alert), the last action and how long ago, four lever
    tiles that flash 10 s when AUTO moves them (a tap pauses), and a milestone bar with an ETA.
- **Safety is sovereign** (`GuidanceSession`, `GuidanceRiskEngine`, the doctrine in
  `wiki/Guided-Roast-Decision-Architecture.md`). Crash, flick, stall and over-long phases are
  never muted, in any mode. An operator move hands guidance to observation: the advice then
  follows the operator's trajectory, not the plan.

**Already on the tablet**: the plan and its curve, the 3 START faces (by hand, *Follow the
plan*, *Follow a roast*), auto milestones (D1), Roast Replay (D2), alarms held while an
automation runs (decision 9), and its own cooling and machine stop at the end of the roast. No
gesture card, no AUTO, no crash detector, no coach line.

## 2. Proposed model

**One engine, two screens.** We do not rewrite the decisions in the tablet. We move them, as
D1–D3 did, into `tilaucore`, which takes plain data in and gives decisions out:

- `tilaucore.guidance`: the `guidance_*` modules as they are (already pure), plus the crash
  detector (`_RoRCrashDetector`) and the steps (`_plan_steps`, `_gesture_steps`, with no `aw`).
- `tilaucore.autopilot`: AUTO's state machine taken out of the panel. On each tick it gets BT,
  RoR, the phase, the milestones, the plan, the levers read back and the clock. It returns the
  moves to make, the milestone to mark, the state (off / armed / paused) and the cockpit's text
  as keys. It never touches a slider: each screen executes the moves through its own path (the
  desktop's `_apply_slider_value`, the machine command on the tablet).
- The desktop then calls this engine, module by module, under the D3 rule: the outputs are
  identical, proved by a bench on the corpus before and after.

**On the tablet:**

- *The plan* becomes the guided mode: its indications in the notification bubble over the curve,
  from the same engine and the same words as the desktop (decision 3).
- *AUTO*, a fourth START face (decision 2): the levers it drives carry an AUTO tag, a move it
  makes shows as a toast, a lever touch pauses it and the AUTO chip by the clock resumes it.
- The safety layer (crash, flick, stall) runs in every mode, *by hand* included, as on the
  desktop. No deviation advice (decision 4).
- AUTO's moves are gestures (ALARM-SPEC decision 7). They are recorded in the `.alog` as AUTO's
  (§5 of AUTOMATION-SPEC: never as the operator's), and confirmed by the machine's echo.
- Simulation (SIM-SPEC): AUTO and the guided mode run on a replayed roast. That is how the
  operator validates.

## 3. Decisions (operator, 2026-11-07)

1. **Order**: the engine in `tilaucore` with the desktop on it first, proved identical on the
   corpus, then the tablet.
2. **Where AUTO lives on the tablet**: a fourth START face, *AUTO*, beside *By hand*, *The plan*
   and *A roast* (mockup, 2026-11-07: the tablet's way, one choice before START).
3. **Guided on the tablet**: inside *The plan*. Its indications (the step due, first crack soon,
   the drop) go in the notification bubble over the curve, the one alarms use; nothing on the
   levers, the step lanes or the milestone buttons. Nothing to do: no bubble; a tap on the bubble
   does nothing, it goes once the lever holds the value. One exception kept: in development the
   Drop button fills with the bean's way from first crack to the plan's drop temperature.
   - AUTO is chosen before START only; the AUTO chip by the clock only resumes it after a pause. Mockup
   https://claude.ai/artifact/DBsybMHY1fxDoXYX3ksdLd.
   - Crash under AUTO: a toast of what AUTO did is enough, no bubble.
   - *Wait* during the drop countdown cancels the auto-drop for the rest of the roast, as on the
     desktop: the drop is then by hand.
4. **No deviation advice**: no coach line of RoR gaps, in any mode. Only the safety alerts.
5. **Nothing hard-coded for one machine**: the cooling at drop is the roaster's, in
   `roasters.json` (`cooling`: burner, air, drum, extractor and its mode, the BT under which it
   ends). Skywalker V2: burner 0, air 75 %, drum 80 %, AirWave 80 % in FAN mode, ends under
   50 °C, where COOL END is marked unless an alarm marked it. The desktop's AUTO and the tablet's
   end roast both read it (done 2026-11-07, to validate).
6. **English only** in the first version: no translation work.
7. **A lever no longer drops the plan's auto milestones** (2026-11-08): following the plan, guided
   or AUTO, a lever is the gesture the bubble asks for. Only an undo drops them. Following a
   roast keeps AUTOMATION-SPEC decision 8 (the first hand takes the roast back).

**Choices made in G4** (to validate):
- The crash rule and AUTO read BT RoR as Artisan computes it with the machine's setup
  (`recompute_deltas` over the last minute), the rate the desktop's thresholds were set on. The
  curve keeps the tablet's own RoR. The plain 20 s slope called crashes on sound roasts.
- The tablet's auto milestones (`AutoMarks`, cracks or the replayed roast) are AUTO's detectors;
  AUTO marks on BT past the window only when they have not.
- AUTO's cooling at DROP is the roaster's (decision 5). COOL END under 50 °C is not marked by the
  tablet: its End roast is the desktop's Cool end, still the operator's.
- Not carried over: holding a burner step up while the RoR is above target (the plan's phase RoR
  targets are not read yet); the bubble asks for the step as soon as the bean is on it.

## 4. Order

| Step | What |
|---|---|
| G1 | The guidance engine in `tilaucore`: the eight `guidance_*` modules moved as they were, the crash rule (`guidance_crash`) and the plan's steps (`guidance_steps`) taken out of the panel, the desktop on them with its own words and beep — **done 2026-11-07, to validate** |
| G2 | `tilaucore.autopilot`: AUTO's state and decisions taken out of the panel (`AutoPilot`), the screen as its host (`AutoHost`: levers, marks, beep, words). Desktop on it; same ticks given to the old and the new panel on 108 corpus roasts × 3 operator scenarios: identical moves, marks and states — **done 2026-11-08, to validate** |
| G3 | Tablet mockup (https://claude.ai/artifact/DBsybMHY1fxDoXYX3ksdLd) — **validated 2026-11-07** |
| G4 | Tablet: `tilauscope_mobile/guided.py` (the host of AUTO, the bubble, the crash), START face AUTO, chip, tags, toast, bubble, Drop gauge, Wait; tests on corpus replays (`tests/test_guided.py`), the virtual Skywalker (`AutoOnTheVirtualRoasterTests`) and the page bench — **done 2026-11-08** |

Risk: G2 touches the most-tuned part of the desktop. Each extraction lands separately, with the
tests and the bench, and nothing is changed on the way.
