# Machine actions — milestones, commands, alarms (bench, 2026-10-14)

What the roaster is told, and when. To validate before any code; placed in the
order of the work that remains (CAVE-SPEC phases, shared library §7).

## 1. What the desktop does today (read in the code)

**Milestone commands.** Artisan keeps one action per button, by position, in the
machine setup (`.aset`, copied into the settings at first setup):
`buttonactions` / `buttonactionstrings`, index 0 CHARGE, 1 DRY END, 2 FC START,
3 FC END, 4 SC START, 5 SC END, 6 DROP, 7 COOL END (`canvas.py:1380`); ON, OFF,
SAMPLE in `extrabuttonactions`; RESET, START in `xextrabuttonactions`.
Skywalker V2 BLE (`includes/Machines/Skywalker/skywalkerv2-ble.aset`):

| Moment | Command sent to the roaster |
|---|---|
| CHARGE | `EVT,1` |
| DROP | `EVT,8` |
| COOL END | `EVT,9` |
| START (Roast Setup, PID box) | `tilaupid(START,<SV>)` — TilauScope's preheat PID |

The firmware reads the `EVT` codes (among others, to show the state on the
roaster's touch screen); their meaning is not written anywhere in our code.

**Sliders.** `slidercommands`: air `OT2,{}`, drum `OT3,{}`, AirWave `OT4,{}`,
burner `OT1,{}` (the AirWave slider goes through the roaster's bridge, a point to
check against the tablet, where the AirWave is its own BLE device).

**Extra event buttons** (same file): burner and air −5/+5, **cooling on
`CLDN,ON` / off `CLDN,OF`**, drum 100…80 %, burner 0 %. Each is a row of six
parallel lists (`extraeventsactions`, `…strings`, `…types`, `…values`,
`…labels`, `…descriptions`).

**Alarms.** Artisan's alarm table (one row per alarm, parallel lists: guard,
time or temperature condition, source, action type, action string). TilauScope's
alarm editor (`alarms.py`) writes those rows from rule sentences; the roast plan
can load its own alarms at START (Expert). The operator sets the cooling air and
extractor with alarms.

**Also on the desktop:** auto CHARGE / DRY END / FC / DROP marks, preheat PID,
roast replay.

## 2. What is wrong in Artisan's design (not to copy)

1. Actions are positions in parallel lists: an index shift silently sends the
   wrong command (already met with device ids, `reference_skywalker_ble_preset_stale_ids`).
2. Commands are strings of a mini-language (`skywalker(OT1,{})`) evaluated at
   run time, mixed with labels, colours and slider scaling in one blob.
3. The same intent (burner to 0, cooling on) is written three times: button,
   slider, alarm, each with its own encoding.
4. Machine knowledge lives in the operator's settings, not with the machine: a
   second operator, or the tablet, cannot read it.
5. Alarms are rows, not rules: no name, no reason, no link to a plan or a coffee.

## 3. Proposed model (shared, `tilaucore`, standard library)

**The machine's Artisan setup is the source** (decision 1): the `.aset` that
`roasters.json` names for the machine and its link (`artisan_setups[].preset`,
`Skywalker/skywalkerv2-ble.aset` for the tablet) gives the defaults, as on the
desktop; a default set ships with the app. `tilaucore` reads it (standard
library) into named entries — `on_milestone` (charge, dry_end, first_crack, …,
drop, cool_end), `on_button` (on, off, start, reset), `levers`, `actions` — so
nothing downstream depends on list positions. Only IO commands of the form
`skywalker(<command>)` are sent by the tablet; any other kind (for example
`tilaupid(START,…)`) is reported as not supported there, never guessed.

**One way to say what to do**: an *action* is `{lever, value}` or `{machine action}`
or `{message}`. Buttons, milestone commands and alarms all use it.

**Alarms as rules** (an engine of our own, no Artisan code): *when* (a milestone
plus a delay, a temperature crossed, a time) → *do* (actions above), with a name
and a reason; stored as JSON; attached to the machine, to a coffee or to a plan.
The desktop and the tablet run the same engine on their sample stream.

## 4. Order of the work

| Step | What | Where it sits |
|---|---|---|
| A0 | **Prerequisite** — record a roast with the real Skywalker V2: temperatures from the link into the session, lever commands sent and acknowledged by their echo, reconnection during a roast, burner protection (SPEC §4 gate "Recording, reconnection during a roast", "Device protection and acknowledgement tests"). Today only the AirWave is driven for real; the session's burner, air and drum reach the simulated machine. *Done and validated 2026-10-16 on an empty drum (§7)*. | before A |
| A | `.aset` reader in `tilaucore` + milestone commands: CHARGE, DRY END, FC, DROP send what the setup gives (`EVT,1`, `EVT,8` on the V2); **End roast = STOP + OFF** (decision 2): the setup's OFF action, then `OFF` to the roaster. *Reading done and validated 2026-10-15* (`tilaucore.artisan_setup`, tablet plan on the setup's RoR, commands to the simulated machine); sending to the real roaster after A0 | after A0 |
| B | ~~Named machine actions on the tablet (cooling on/off as the desktop's buttons)~~ — *dropped 2026-10-16*: the tablet's levers cover burner, air and drum, and End roast cools by itself | — |
| C | Alarm engine: spec, rule format, editor mockup, then code; cooling air/extractor values come from it, nothing hard-coded — spec `ALARM-SPEC.md`; *C1 engine, C2 tablet run, C3 tablet editor and C4 desktop on the shared engine done and validated 2026-10-20* | own phase, before the plan |
| D | Auto marks, preheat PID on START, replay | after C; replay already phase 3 |
| — | Desktop switched to the reader and the engine | once tablet and tests prove them, module by module (bench) |

## 5. Decisions (operator, 2026-10-14)

1. The Artisan `.aset` is the source of the default settings, as on the desktop;
   a default set ships with the app.
2. End roast = STOP + OFF on the roaster.
3. Steps placed as above. Cooling values: set by alarms (step C), never in code.
   *Amended 2026-10-16*: the tablet's cool-first sequence (air 100 %, drum 80 %, under
   50 °C BT) is the machine's fixed safety end, kept in the catalogue; it differs from the
   desktop on purpose. Alarms (step C) set the cooling the operator chooses.

## 6. Open

- A0 before A: the real-roaster recording is a production gate with its own
  protection tests; to schedule now or after the rest of phase 1 (Roast Setup is
  done; past roasts list remains).

## 7. A0 — the roast link (plan, 2026-10-16)

What the tablet link adds to the link check, at parity with the desktop's `tc4ble`
(read in `src/tilauscope/tc4ble.py`). Safety first: none of it may be skipped.

**Levers.** Burner, air and drum are sent as the setup's slider commands (`.aset`
`slidercommands`, positions = Artisan's event types: air, drum, extractor, burner;
V2: `OT2` 0–100, `OT3` 60–100, `OT1` 0–100), clamped to the setup's min/max, as whole
numbers. The `.aset` reader gains these `levers`. The extractor stays the AirWave's
own link on the tablet. The burner has no 80 % cap in a roast (operator's decision:
the cap is for the preheat and the plan).

**Acknowledgement.** The roaster echoes the burner (field 4) and the air (field 5)
in every reading; a command is confirmed when its echo matches; the drum is not
echoed and is shown as commanded. The core records the commanded value, as today.

**Burner monitor.** An echo above the commanded burner is corrected at once (the
command is sent again); two in a row raise an alert.

**Readings into the roast.** BT, ET and the ambient probe of each reading become the
session's samples (no simulation once the real machine is linked); the roast file is
not marked simulated.

**Link loss during a roast.** The firmware emergency-stops (burner 0, fans on). The
tablet reconnects by address, waiting 0.5, 1, then 2 s at most between attempts;
each reconnection verifies the burner at 0 on a fresh echo, else drops the link
again. A silent link (no reading for 3 s) is closed and reconnected. While the
roast is live the recovery guard is armed: on reconnection the air and drum are
sent again, the burner is **not**: it is held at its echo (0), the burner lever
shows 0 and the screen says the link is back and the burner must be raised again.
The session keeps recording; samples missing during the drop are a gap.

**Commands of the setup.** Charge, Drop and End roast send what step A gives
(`EVT,1`, `EVT,8`; End roast = OFF action of the setup, then `OFF`) to the real link.

**Validation on the machine:** empty drum only, no beans (operator, 2026-10-16), burner
at a low value; check the echoes, the monitor, a forced drop (tablet Bluetooth off then
on) and the recovery; the recorded run is opened on the desktop.

**Cool first, then stop (operator, 2026-10-16, replaces "End roast = STOP + OFF").**
End roast, a safety stop of the preheat and any letting go of the roast link while hot
(the app closing) first set the burner to 0, then the roaster's cooling (`CLDN,ON`),
air 100 % and drum 80 %, and wait until the bean probe is under 50 °C before the setup's
OFF and `OFF`. The link runs the wait on its readings; without a valid bean reading it
keeps cooling and never stops on a guess. A dropped link is the firmware's own
emergency stop (burner 0, fans on). V1 Skycommand: cooling commands unknown, not sent.
*Validated 2026-10-16 on the real V2, empty drum.*

**Back to back (operator, 2026-10-16).** A new roast started while the roaster cools is
the operator's choice and is never blocked: the link is kept, the cooling stops
(`CLDN,OF`), the burner is verified at 0 and the new roast's air and drum are sent; its
preheat starts from the current temperature. New roast asks for the save of an unsaved
roast; holding it 5 s skips the save.

**Field order (corrected 2026-10-16).** After `CHAN;1200`, `READ` is ambient, ET, BT, as
the desktop's `tc4ble` reads it. The tablet first read BT before ET; its test roasts and
learned preheat values were deleted.

**Desktop unchanged (operator, 2026-10-16).** End roast on the desktop keeps Artisan's
buttons and `tc4ble`; it does not get the cool-first sequence.

**Decisions (operator, 2026-10-16).** The recovery guard arms itself from Start
recording to End roast. The burner is free in a roast (0–100 %); only the preheat is
capped at 80 %. Validation on an empty drum, never with beans.
