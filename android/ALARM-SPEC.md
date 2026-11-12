# Alarms on the tablet (MACHINE-SPEC step C) — spec, 2026-10-16

To validate before any code. Step B was dropped (MACHINE-SPEC §4); the tablet's
cool-first end stays fixed and is not an alarm (decision 4 below).

## 1. What the desktop does today (read in the code)

**Storage.** Artisan keeps the alarm table as parallel lists (`alarmflag`,
`alarmguard`, `alarmnegguard`, `alarmtime`, `alarmoffset`, `alarmsource`,
`alarmcond`, `alarmtemperature`, `alarmaction`, `alarmbeep`, `alarmstrings`) in its
settings; **Save/Load** writes them as a JSON `.alrm` file with the same keys.
TilauScope's editor (`tilauscope/alarms.py`) shows them as rule sentences; the roast
plan builds its own table at START (`roast_plan_model.generate`).

**Firing** (`canvas.py` 5251–5410, TILAU-modified Artisan loop, each sample). An alarm
fires **once per roast**, when it is on, not fired yet, its guard (*If Alarm*) has fired,
its negative guard (*But Not*) has not, and its anchor is reached:

| `alarmtime` | Anchor |
|---|---|
| 9 | ON |
| −1 | START |
| 0 | CHARGE |
| 8 | TP (detected) |
| 1–7 | DRY END, FC START, FC END, SC START, SC END, DROP, COOL END |
| 10 | If Alarm: the guard's firing |

Then it is *ready* when its delay since the anchor is reached (`alarmoffset` > 0;
0 skips the delay, so +1 s is the convention for "at the anchor") **or** its
temperature condition holds: `alarmsource` −3 none, −2 ΔET, −1 ΔBT, 0 ET, 1 BT,
2+ extra device channels (by index); `alarmcond` 0 below, 1 above, 2 equal, 3 not
equal; for an If Alarm the reading is taken relative to the reading at the guard's
firing. A missing reading (None, −1) never fires.

**Actions** (`alarmaction`, argument in `alarmstrings`): 0 pop-up message, 1 call a
program, 2 extra event button (its number), 3–6 sliders (air, drum, damper, burner
on the Skywalker presets), 7–16 START, the milestones, OFF, CHARGE, 17–18 ramp/soak,
19–20 PID on/off, 21 SV, 22–23 playback, 24–25 canvas colour, 26 AirWave command,
27 TilauAmbient command, 28 kernel (the last three TilauScope's own).

**The operator's lists** (`~/Documents/artisan/*.alrm`, 2026-10-16). `minimal.alrm`:
air 20 / burner 0 / drum 80 at ON; PID on and air 25 at START; PID off, air 30, drum 85,
burner 75 at CHARGE; drum 80 at TP; air 35 at DRY END; air 45 at FC START; at DROP air 0,
burner 0, event button 5 (`CLDN,ON` in the V2 preset), drum 80 — chained by If Alarm.
`La Fabrica.alrm` adds AirWave (`MODE …`, `FAN …`) and TilauAmbient (`CAL`, `START`,
`STOP`) commands. `liste alarmes.alrm` uses temperature conditions (a "DE!" pop-up,
levers on extra-device thresholds).

## 2. Decisions (operator, 2026-10-16)

1. The tablet runs: the operator's lever sequence, temperature alerts, and accessory
   commands (AirWave, TilauAmbient). The plan's levers are not sent by alarms.
2. The rules come from Artisan `.alrm` files, read as they are (the same file on both
   apps, as the `.aset` for the machine).
3. Rules can also be edited on the tablet (mockup first); the tablet writes `.alrm`.
4. Cooling stays with End roast (the fixed cool-first sequence); a list's DROP cooling
   rows are not what ends the roast.
5. PID on/off rows are not run on the tablet: the preheat is set in Roast Setup.
6. Extra-device conditions are resolved, not dropped: the source index points into the
   machine setup's extra devices (`.aset`), named through Artisan's device table, which
   ships with the app as static data; a channel the tablet has (TilauAmbient, AirWave)
   is read from its link, any other is reported as not run.
7. **An alarm is a gesture**: it replaces the operator's hand and has exactly the same
   effect — recorded as a setting, confirmed by echo, and a burner value pauses the
   preheat as a touch does.
8. Alarm lists live in Settings and stay across coffees, as on the desktop.
9. The tablet editor mirrors the desktop's: every rule field, on/off, beep, reorder,
   insert, delete, guards, saved lists. Touch conventions: swipe a row to delete (with
   undo) or to turn it on/off, long press then drag to move, tap a zone of the sentence to
   edit it (no Edit button).

## 3. Proposed model

**Shared engine, `tilaucore.alarms` (standard library).**
- `read_alrm(text) -> AlarmList` and `write_alrm(list) -> text`: the JSON `.alrm`,
  lossless (a row the tablet cannot run is kept and written back unchanged).
- Named records: anchor (`on`, `start`, `charge`, `tp`, milestones, `if_alarm`), delay,
  condition (probe, operator, value), action (kind + argument), beep, guard and negative
  guard **by row identity**, not position (positions only in the file).
- `AlarmRun.step(t, samples, marks) -> fired`: the firing rule of §1, on the session's
  sample stream; returns the rows fired at this sample, in table order. Pure: no I/O,
  no clock of its own.
- Bench before the desktop uses it: the corpus `.alog` files carry their alarm table
  (not which rows fired); replay each roast's samples and marks through the engine and
  through a copy of the desktop's loop in the bench script (never the app itself), and compare the fired rows
  and times. The lever settings an alarm recorded in the roast are a cross-check only. The desktop switches later,
  module by module (MACHINE-SPEC §4 last row).

**On the tablet.**
- Actions run: sliders → the lever commands of the `.aset` (the same path as the
  operator's buttons, so they are recorded as settings and confirmed by echo); event
  button *n* → the `.aset`'s extra event button *n* (its `skywalker(…)` commands);
  pop-up → a message on the roast screen (no modal); AirWave and TilauAmbient → their
  links. Any other action (program, PID, SV, playback, canvas, kernel, ramp/soak,
  milestone marks) is **listed as not run on the tablet**, never guessed.
- PID on/off rows: not run (decision 5). Extra-device conditions: resolved by name
  (decision 6). A burner value pauses the preheat (decision 7).
- Settings › Alarms: the lists (imported from a `.alrm`, created or edited on the
  tablet, several kept) and the active one, kept across coffees (decision 8).
- Roast screen: each fired row is visible (what was sent and why), the beep sounds.

## 4. Open questions

- None; decisions 5–9 answered the first list (operator, 2026-10-16).

## 5. Order

| Step | What |
|---|---|
| C1 | `tilaucore.alarms`: read/write `.alrm` losslessly, firing rule; tests from the operator's three files; bench on the corpus — *done and validated 2026-10-16*: `read_alrm`/`write_alrm` (byte-identical on the operator's lists), `read_profile_alarms`, `AlarmRun.step`, `slider_value`, `event_buttons`; 10 tests; bench: 105 roasts × 4 tables (recorded + 3 random), 2 729 firings, identical to a verbatim copy of the desktop loop sample by sample |
| C2 | Tablet: run a chosen list (levers, event buttons, messages, accessories); mockup of the roast-screen display first; empty drum only — *done and validated 2026-10-20* (mockups ATEBfScpqLcvqrbdpPingG, AsPdXmS2CJpJygzi3wDrs9): Settings › Alarms (import, active list, None); acts on the gesture path; event buttons (`[ExtraEventButtons]`, IO command 6); AirWave FAN/MODE/POWER; TilauAmbient audio commands (the desktop's words); extra probes resolved by the computer's `tilau_name_map` (registry ids shift with upstream merges); live TP; alarm-made settings `A{n} (S{t})` in the .alog, not kept by the journal (operator: lost on an app kill) |
| C3 | Tablet editor: mockup first, then code — *done and validated 2026-10-20* (mockup JRTerG1VrE6PTHgU1qVCtM v2, toggle option D 3s69VNV3TBiFLhbnpGcHWH): `tilaucore.alarms` `remove_row`, `move_row`, `append_row` (references follow by identity, as the desktop's AlarmSet); tablet `get_alarm_list`, `edit_alarm` (checked fields), add, delete + Undo, move, new and delete list, share; `alarm-editor.js` (pictos, number = on/off, handle, swipe left with `touch-action: pan-y`, zone sheets) |
| C4 | Desktop on the shared engine, once C1's bench is identical — *done and validated 2026-10-20*: canvas.py's alarm loop calls `AlarmRun.step` (TILAU-marked, 17 lines for 189); `Readings.recorded` keeps Artisan's firing index before START (len(timex), not the ON buffer), a gap the C1 bench could not see; bench: the new block against the old loop from HEAD, 106 roasts × 4 tables with an ON phase, identical; operator run in the desktop simulator, minimal.alrm, no error in artisan.log |
