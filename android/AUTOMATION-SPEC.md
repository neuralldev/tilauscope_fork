# Roast automation on the tablet (MACHINE-SPEC step D) — spec, 2026-10-20

To validate before any code. Step D was "auto marks, preheat PID on START, replay". The
preheat at START is done (PREHEAT-SPEC P2). What is left: the automatic milestones and
Roast Replay. The word *replay* already names the simulation (SIM-SPEC); here it is
**Roast Replay**, the desktop's name: following a recorded roast's moves during a real roast.

## 1. What the desktop does (read in the code)

**Switches** (Roast Setup › *Roast automation*): Auto Charge, Auto Drop, Auto Dry End,
Auto First Crack; tuning in Configuration › DETECTION.

**Auto Charge / Auto Drop** (Artisan, `canvas.sample`, `main.BTbreak`/`checkTop`): a break
in BT over the last 5 samples (or the last 10, every other one), with Artisan's thresholds
(`btbreak_params`, Standard mode). CHARGE only before CHARGE with BT > 77 °C; DROP only after
CHARGE, more than 7 min in, BT > 160 °C. Each fires once per roast.

**Auto Dry End** (TilauScope `DryEndDetector`, called from `canvas.sample`): after CHARGE
and before DRY END; scores BT's progress toward the Dry End target (Artisan Phases
`phases[1]`), the convergence of the BT/ET RoR ratio, the slope of the BT–ET gap, colour as
a bonus when a colour device reads live. Fires on a confidence threshold.

**Auto First Crack** (TilauScope `FirstCrackDetector`): only once Dry End is marked and only
with a crack counter among the devices (TilauAmbient). Listens from the FC target (`phases[2]`)
minus a tolerance; a burst of cracks (count in a window) calls FC early, the target plus the
tolerance calls it anyway; the mark is placed back at the first crack heard.

**Guided / Expert** (`_tilau_milestone_automark`): a detection is a *suggestion* the
assistant offers for a one-tap confirm; it marks silently only when the operator opted in.

**Roast Replay** (`window/lifecycle._engage_replay`, Artisan's playback engine
`canvas.playbackevent`): a background roast (often the coffee's reference roast) loaded in
Roast Setup; armed, it engages **at CHARGE only**, then moves the burner, air and drum as the
background did, matched on BT once BT is usable (on time before), leading by the machine's
burner lag (10 s without a measured one). Forces Expert for its duration; Auto Dry End and
Auto First Crack stand down (the milestones come from the curve followed). A read-only
machine only announces the moves.

## 2. Proposed model

- **Shared engine first** (as C1/C4, "pas 2 systèmes"): BTbreak, the Dry End and First Crack
  detectors and the playback rule move to `tilaucore` (standard library), benched against the
  desktop code on the corpus before the tablet uses them; the desktop switches later.
- **On the tablet**: a milestone found automatically is marked as a touch would mark it
  (machine command, alarms anchored on it, journal); the existing Undo takes it back.
- Roast Replay on the tablet: its moves are gestures (as alarms, decision 7 of ALARM-SPEC):
  recorded, confirmed by echo, a burner move pauses nothing (the preheat is over at CHARGE).

## 3. Decisions (operator, 2026-10-20)

1. **Order**: auto milestones first (D1), Roast Replay after (D2), the desktop on the shared
   engine last (D3).
2. **Mark directly, Undo takes it back**: a milestone found automatically is marked as a
   touch would mark it; no suggestion to confirm.
3. **Dry End and FC targets of the detectors from the coffee's plan** ("End of Dry Temp",
   "First Crack Temp" of the tablet's plan); without a plan (no coffee chosen, plan not
   ready), the detectors' own fallback as on the desktop with no target: the trade bands
   (158–163 °C, 195–200 °C). *Amended 2026-10-20*: the shipped `.aset` carries no Artisan
   Phases (the desktop keeps them in its own settings), so they cannot be the fallback. The desktop reads the Phases
   and does not write its plan into them: on this point the tablet differs on purpose. The
   engine takes the target as a value, so both apps keep their own source.
   *Amended 2026-10-20*: the automation applies only to a roast that follows a plan; without
   one the roast is manual (no auto milestone, its alarm list runs), so the trade bands only
   stand in for a target the plan lacks.
   *Amended 2026-10-20*: without the plan's, the target is a point, as Artisan's Phases on the
   desktop: the trade's value (158 °C Dry end, 195 °C First crack) plus the roaster's bean probe
   offset (`bean_temperature_offset_c` of roasters.json, index 1 and 2), ± 5 °C. Skywalker V2:
   150 °C and 185 °C (the desktop's Phases there: 150 and 186).
4. **Roast Replay follows either** the coffee's reference roast (★), proposed in Roast Setup,
   or a curve chosen by hand with a picto in BeanCave › Roasts. With neither, Roast Replay is
   not offered.
5. **Switches in Roast Setup**, per roast as on the desktop, kept from one roast to the next.
6. **Auto Dry End and Auto First Crack follow the background curve** when there is one (a
   Roast Replay): the milestone is marked when the live roast reaches the background's Dry End
   or First Crack, matched on BT as the replay's moves. Without a background, the desktop's
   detectors (Dry End, First Crack) trigger them, when the option is on.

7. **Armed per milestone** in Roast Setup › Plan (AUTO on the row of each milestone, beside
   its target), kept from one roast to the next. *Default* (2026-10-20): Charge, Dry End and
   First Crack armed, Drop not: the operator usually drops the beans themself.
8. **The automation drops at the first hand**: undoing a milestone or touching a lever puts
   the whole roast back in manual (every milestone), for the rest of the roast; it is armed
   again in Roast Setup, for the next roast. TilauPID's commands are part of the automation
   and do not drop it.
   *Amended 2026-10-21*: before Charge a lever touched pauses the preheat only (its PID); the
   automation stays armed and takes over at Charge. From Charge on, the first hand drops it.
   *Amended 2026-11-08* (GUIDED-SPEC decision 7): following the plan (guided or AUTO) a lever no
   longer drops the milestones, only an undo does; following a roast is unchanged.
9. **Alarms are a manual Expert tool**: while an automation is armed (auto milestones, Roast
   Replay, a guided mode), the alarm list does not run; once the automation has dropped, the
   roast stays manual without alarms.
10. **Nothing shown during the roast** but a toast: when a milestone marks itself, and when
   the automation drops. No AUTO under the steps.

11. **Crack detection** (operator, 2026-10-20): a setting in Settings › General. When it is on
   and TilauAmbient is switched on, the tablet runs the probe's sequence every roast:
   - **CAL1** (empty drum) 20 s after the start of the preheat (the Start of the roast);
   - **CAL2** (beans in, Maillard) 1:30 after Dry end, marked by hand or found;
   - **START** (counting) 40 s after CAL2 (its 30 s acquisition, plus a margin; FC comes
     3–4 min after Dry end);
   - **STOP** at Drop.
   During each 30 s acquisition a chip on the roast screen says it is under way. Counting
   runs from START to STOP; Auto First Crack listens to it, and is offered only with crack
   detection on. The sequence is not an alarm: it goes on when the automation drops; while it
   is on, an alarm row sending a TilauAmbient command is not run (one master for the probe).

12. **Three ways to roast** (operator, 2026-10-20), which supersede decisions 7–9 where they differ:

    | Way | Auto milestones | Alarms |
    |---|---|---|
    | By hand | none | run |
    | By hand with detection | Dry end and/or First crack, from Settings › General (Dry end detection, Crack detection) | run |
    | Following the plan (coffee → Roast Setup → Plan tab) | the AUTO chips of the Plan; the detection settings are ignored | off |

    By hand, a lever touched is the roast itself: only an undo drops the detections. Following
    the plan, the probe's sequence runs for an armed AUTO First crack, with TilauAmbient on.
    *Amended 2026-10-21*: the way is chosen on the roast screen, before Start, and nowhere
    else: three choices over the empty curve (*By hand*, *The plan*, *A roast*), the curve
    showing the plan or the roast chosen, and the Start button naming the choice and what it
    runs. Every roast starts by hand: no choice is kept from one roast to the next. Showing
    the Plan tab no longer decides anything (it used to switch the alarms off and AUTO on).
    *The plan* is offered once the plan is ready; *A roast* once there is one to follow.
    *Amended 2026-10-21*: Settings › General › *Charge detection*, on by default as the
    desktop's Auto CHARGE, marks Charge by hand and following a roast; following the plan,
    its AUTO Charge chip decides instead.

13. **Roast Replay on the tablet** (operator, 2026-10-20; mockup D2 v2): one of the two ways to
    follow a plan (the other, the guided mode, follows the whole plan as the desktop
    assistant). Chosen in Roast Setup › Plan, *Follow: Plan | Replay*; Replay plays back the
    coffee's ★ reference roast, or a roast picked with the replay picto in BeanCave › Roasts
    (any coffee). It moves burner, air, drum **and the extractor** as that roast's `.alog` did,
    with Artisan's playback (`tilaucore.playback`, benched on the corpus): by BT after the
    turning point, by time before, ramps 10 s ahead (the burner lag). The first touch on a
    lever disengages it for the rest of the roast: the operator has taken the roast back by hand.
    *Amended 2026-10-20*: AUTO belongs to following the plan only. Following a roast, no milestone
    marks itself (decision 6 does not apply): Charge is touched by hand and engages the playback.
    *Amended 2026-10-21*: Roast Setup › Plan has no *Follow* choice any more; it shows the plan
    and its AUTO chips only. The roast followed is the ★ reference, or the one picked with the
    follow picto in BeanCave › Roasts (which opens the roast screen); it is chosen at Start
    (decision 12).
    *Amended 2026-10-21*: following a roast, Charge marks itself when Charge detection is on
    (decision 12), and engages the playback as Artisan does after an Auto CHARGE.

14. **The desktop on the shared engine** (operator, 2026-10-21): the three modules, in this
    order: D3b Dry End and First Crack (`tilau_intelligence` detectors become adapters that read
    `aw`/`qmc` and hand the decision to `tilaucore.milestones`), D3a Auto Charge / Auto Drop
    (`aw.BTbreak` keeps its signature and calls `tilaucore.milestones`), D3c Roast Replay
    (`canvas.playbackevent` takes its moves and ramps from `tilaucore.playback`; sending to the
    sliders, the beep and the Fuji PID stay in canvas). Artisan code changed under `## TILAU ##`;
    an upstream merge touching these functions redoes the joint. Each module: the bench against
    the desktop code as it is, a red test, the desktop suite, then an operator run in the desktop
    simulator. The desktop keeps Artisan's Phases as its targets (decision 3 differs on purpose).

## 4. Order

| Step | What |
|---|---|
| D1 | Auto milestones: engine in `tilaucore` + bench, then tablet (mockup of the switches and of how a found milestone shows) — **done, validated 2026-10-21** |
| D2 | Roast Replay: engine in `tilaucore` + bench, then tablet (mockup first) — **done, validated 2026-10-21** |
| D3 | Desktop on the shared engine, module by module — **done, validated 2026-10-21** (D3b, D3a, D3c) |

## 5. To carry over from the desktop (2026-11-01, Android paused)

Decided on the desktop. What the tablet already has comes first; the rest waits for the
guided mode and AUTO.

**Already on the tablet** through `tilaucore` (`generate_roast_plan`, `data/roasters.json`):
the burner before first crack learned from each roast of a coffee, the 60 % development
ceiling. The tablet learns from the roasts it holds.

**Auto milestones, carried over 2026-11-01:**
- Auto First Crack no longer needs the crack counter: without cracks it marks at target +
  `MILESTONE_HALF_C`. Its AUTO chip is always available in Roast Setup.
- In simulation, armed milestones and Drop mark at the replayed roast's own milestone. Cracks
  may call FC sooner; a roast with no cracks takes its milestone; a milestone the original
  never marked falls back on the live rule. Marks stay by hand when not armed (SIM-SPEC).

**When the guided mode or AUTO arrives** (none on the tablet today, SPEC §M4):
- AUTO moves phase on real marks only, never on the plan's temperature, and marks them itself:
  no confirm prompt, the milestone button stays quiet and is only a fallback.
- AUTO's own lever moves must never read as the operator's hand.
- A lever move reported, a phase name, a milestone name: always translated.
- Crash, by phase. Drying and Maillard: air first, burner if the air is not enough. Development
  without a crash: air by 5 % stages. Development with a crash: air and burner by 5 % stages
  until the RoR picks up, capped by `dev_heater_max_pct`, resorbed after.
- Guided: one voice, a single card gives the burner and air value; the "near dry end" hint and
  button open 5 °C before the target.
