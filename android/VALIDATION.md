# M0 validation — 2026-09-19

## Completed

- Python 3.14.7: **15 tests passed** using
  `PYTHONPATH=android/python python3 -m unittest discover -s android/tests -v`.
  Coverage includes session lifecycle, chronological samples, missing data,
  constant-temperature freshness, irregular-time RoR, stale-gap reset, milestone
  guards, checkpoint atomic-replacement failure, TC4 fragmentation and stale
  callback rejection, TCP EOF/timeout/cancellation/early close, and import isolation.
- The four TCP tests use loopback only. The initial sandbox run blocked socket
  binding; the complete suite passed when run with local socket access permitted.
- CLI simulation: 600 seconds, 601 samples including the initial sample. JSON
  checkpoint decoded successfully and retained `simulated=true`.
- Android manifest/string-resource XML and Python package TOML parse successfully.
- Chaquopy source path resolves to this project's Python package.
- SHA-256 comparison of 1,562 pre-existing tracked files against the initial
  workspace state found no changes, excluding the intentionally updated release
  history. Existing uncommitted desktop work was preserved.

## APK build — 2026-10-11

- The debug APK compiles and the diagnostic screen ran from Android Studio
  (operator test). Android lint and ARM64 physical-device runs are not recorded.

## M1 A+B — session service and journal — 2026-10-11

- Python: **20 tests passed** (5 new journal tests: round trip, process death,
  truncated last line, corrupt journal set aside, milestone index mismatch).
- `./gradlew :app:assembleDebug :app:lintDebug` with JBR 21: build OK, lint
  0 errors, 2 pre-existing manifest warnings (icon, data extraction rules).
  Android Studio's bundled JBR 25 is rejected by Gradle 8.11.1.
- Emulator `Medium_Tablet`, API 35, arm64-v8a:
  - first recording action shows the notification permission request, then the
    service runs in the foreground (`connectedDevice`);
  - rotation and leaving the screen keep the session (60 s, 61 samples);
  - the journal holds the header, 61 samples and CHARGE (63 lines);
  - after `kill -9`, the service is not restarted; relaunch shows the session
    restored read-only as interrupted, with Simulate and End disabled;
  - End session leaves the foreground and writes the stop event; save still works.
- Honor Pad 9 (HEY2-W09, MagicOS, API 34, arm64-v8a), default battery settings,
  operator test: rotation and app switching keep the session, no process kill
  observed, End session and save work. The low-importance notification is posted
  (checked with `dumpsys notification`) but MagicOS shows it only in the collapsed
  silent group, without a status-bar icon; accepted as is. Python cold start after
  a force-stop takes more than 6 s before the first snapshot.
- Not exercised: long screen-off with Doze, notification permission refused.

## M1 roast screen — 2026-10-12

- Python: 24 tests passed (milestone undo replayed from the journal, signal gap
  without fabricated samples, lever settings journaled and echoed, read-only roaster).
- Honor Pad 9, API 34: full simulated roast driven by `adb` taps with screenshots —
  start, charge, burner/air steps with echo, drum and extractor panels, value wheel,
  settings lanes, undo, signal loss, drop, end, save, process kill and read-only
  restore, read-only roaster (extractor only). RoR is shown from its first positive
  value after charge until drop. The screen stays on while recording.
- Lint: 0 errors.
- Not exercised: real devices, long recordings. No echo timeout exists yet (a lever stays "Sending…" until confirmed).

## Start screen — 2026-10-13

- Honor Pad 9: cold start shows the native start screen (bean, inset to the page
  size on Android 12+), then the animated start page within 0.4 s; the roast screen
  replaces it on the first snapshot, about 3 s after launch. Accepted by the operator.

## Setup assistant, settings and Bluetooth detection — 2026-10-13

- Python: 29 tests passed (catalogue matching by name prefix and service UUID,
  configuration validation, levers per machine, setup refused during a roast,
  scan results filtered to recognised devices).
- Honor Pad 9, API 34, real devices nearby: the app opens on the setup assistant
  without a configuration; the Bluetooth permission is asked at the first scan
  (system dialog, French). Recognised live: Acaia LUNAR scale, RoastSee C1 colour
  meter, RoastSee AquaGauge, Niimbot B21S, TilauAmbient (`TLSCAM…`). Finish wrote
  the configuration; the roast screen then showed only the Skywalker V2 levers.
  Settings: step change applied on return (burner − 6 / + 6), devices saved,
  forgotten and switched.
- Skywalker V2 detected as `TD5325A_V3.1.2BLE` and linked from Settings › Devices.
- AirWave: it advertises `AirWave 302291` and service 0x00E3, but with a one-byte
  manufacturer field that makes Android's parser drop the whole advertisement (no
  name, no UUID). The scanner now reads the raw fields itself in that case; the
  AirWave is then found, saved, and the Extractor chip appears on the roast screen.
- Not exercised: Skywalker V1 detection, Bluetooth refused or off, Android 8–11.
- Detection only: no accessory is connected yet.

## Skywalker V2 link check — 2026-10-13

- Honor Pad 9, Skywalker V2 `TD5325A_V3.1.2BLE`, cold machine, started from
  Settings › Devices › Test. The connect permission was asked once.
- Connection, `CHAN;1200`, then `OT1,0` confirmed on a fresh burner echo before
  anything else; temperatures shown live at 1 Hz. Accepted by the operator.
- Field order: on this V2 the `READ` line is ambient, **bean**, drum. The first
  build followed the desktop indices, which read them the other way round (the
  desktop swaps them back with Artisan's ET/BT setting), and the operator saw Beans
  and Drum swapped; corrected and confirmed.
- Air raised to 60 % for 10 s: heard by the operator. Connecting starts the air
  (20 %) and the drum (80 %); `OFF` at the end of the test stops the whole machine
  and the link is closed. Confirmed.
- Not exercised: the same check inside the first setup assistant, connect
  permission refused, burner not confirmed off, link lost during the test.

## AirWave extractor — 2026-10-13

- Python: 30 tests passed (a value reported by the device is confirmed at once and
  recorded as a setting only when it changes; off is recorded as 0).
- Honor Pad 9, AirWave `AirWave 302291`: the roast screen connects by itself when
  the extractor is in the setup; MTU 512, host name `TilauScope` sent before any
  command, temperatures read every second with an answer each time. The Extractor
  chip shows the device state; the panel (power, speed 30–100 %, mode, inlet and
  catalyst temperatures) and the Settings › Devices › Test check (speed changed
  for 10 s, mode untouched, power and speed put back) were accepted by the operator.
- Not exercised (extractor): changes recorded during a real roast, the
  "switched on for the check" path, reconnection after the extractor is switched
  off, connect permission refused.

## TilauAmbient probe — 2026-10-13

- Python: 31 tests passed (the reading at Charge is kept only when fresher than
  3 s, journaled and replayed, and dropped when Charge is undone).
- Honor Pad 9, `TLSCAM…`: the roast screen connects by itself when the probe is in
  the setup; the header pill shows room temperature and humidity once a second.
  A simulated roast recorded the reading at Charge (journal and summary line
  **Room at charge**). Accepted by the operator.
- First readings swung regularly (18–22 °C, 74–80 %, 988–995 hPa over 30 s) with
  valid frames and checksums: the probe's wires were swapped. Once rewired, the
  values held steady (19.1–19.2 °C, 63–64 %).
- Not exercised: probe switched off during a roast and reconnection, a real roast.

## Scale — 2026-10-13

- Python: 32 tests passed (green weight before the roast, roasted after it, whole
  grams only, both journaled — the roasted one after the stop line — and replayed).
- Honor Pad 9, Acaia Lunar: the roast screen connects by itself when the scale is
  in the setup. Weighing the green coffee from the Green chip and the roasted
  coffee from the summary, and entering a weight on the wheel without the scale,
  both accepted by the operator. Weights are shown and kept in whole grams.
- Not exercised: Pearl, Pyxis and older Acaia models, a scale set to kg or oz, the
  scale switched off while weighing.

## Colour meter — 2026-10-13

- Python: 33 tests passed (whole and ground colours kept apart, set once the roast
  is over, journaled after the stop line and replayed).
- Honor Pad 9, RoastSee C1: the roast screen connects by itself when the meter is
  in the setup; a measurement started on the meter reaches the summary, is sorted
  as whole beans or ground and shown with its roast level name and tint; entry by
  hand on the wheel (20–130). Accepted by the operator.

## Roasts on the tablet — 2026-10-14

- Mockup SN2Nop4JKeUmwm9iDDnzKo v3. `roasts.py`: the tablet's roasts (`files/roasts`)
  and the computer's (`files/roasts-computer`), indexed with `tilaucore.alog_index`
  (cache per folder), detail with `tilaucore.roast_summary` tiles, curve, marks and
  settings lanes; import never copies a roast already held (same roastUUID).
  BeanCave: Roasts tab (`roasts.js`), roast memory zone from `tilaucore.roast_memory`;
  Settings › BeanCave: Import from the computer (a folder picked with
  `ACTION_OPEN_DOCUMENT_TREE`, staged, previewed, Import in the app's words — the
  system file picker only says Select) and Send the tablet's roasts
  (`ACTION_SEND_MULTIPLE`). Tasting words moved to `tilaucore.tasting_log`
  (desktop labels identical, 86 desktop tests passed).
- Tablet tests 65 passed. Honor Pad 9: 105 of the operator's 106 roasts imported (one
  is a second file of the same roast), list, sorts, filter from All N roasts,
  detail, full view, share and send to Google Drive (3 files). Accepted.

## Roast Setup, stock and theme colours on the tablet — 2026-10-14

- Roast Setup (`roast-setup.html`, `Demo.set_roast_setup`): values filled from the
  coffee (`cave.roast_setup`), limits from `tilaucore.bean_edit.NUMBERS`, Roast Setup
  keys written to the `.alog`. Tablet owner: the green weight leaves the stock at
  START, once, floored at 0 (`Cave.decrease`), with a toast; computer owner: not
  applied, said so. The green weight is kept for the next roast. Colours from
  `tilaucore.display_colours` (desktop TilauScope theme).
- Honor Pad 9: two roasts of 250 g in a row lowered the stock by 500 g; colours of
  curves, sliders and RoR accepted. Accepted.

## Energy, temperature unit, milestones in Roasts (MQTT-SPEC E2, UNIT-SPEC) — 2026-10-24

- Python 157 tests passed (new: the energy session, the end card and its sheet, a saved roast's
  sheet equal to the live one, the Roasts tile, the unit setting, °F roasts read in °C, alarm
  thresholds through import, editor and share, milestone points); desktop 47 energy and
  packaging tests and 6 quit tests passed.
- Bench: `energy_model` moved to `tilaucore`, the 7 corpus roasts with `tilau_energy` give the
  desktop's bill; the desktop's readings and burner replayed through the tablet on 4 roasts give
  the same roast bill (total within 0.1 Wh).
- Real roast, empty drum, plug on the roaster's socket (24-10 17:29): 79 readings, 6.1 Wh in all
  (preheat 1.6, roast 4.4, cooling 0.1), measured; the operator opened the file on the desktop:
  same figures. The desktop then closed at quit: macOS 27's native "Save profile?" alert crashed
  drawing its icon once BeanCave was closed; the styled dialog is now used in every case (red
  test proven).
- Honor Pad 9 in °F (tested by Claude through adb, the unit set back to °C afterwards): Settings,
  roast screen at rest and in a replay (BT 70 → 447 °F, RoR 34.2 °F/min on its axis), end
  summary (FC 368 °F, Drop 440 °F), a desktop roast in Roasts (Drop 375 °F, FC 360 °F), Roast
  Setup round trip (400 °F and 68 °F typed, kept, then cleared), an alarm threshold of 3 °C shown
  "ET > 37.4". Roasts: the milestone chips with their values (Caturra 11-10: TP 109 °C 1:07, Dry
  end 146 °C 3:58…), the Energy tile and its sheet (0.157 kWh, preheat 0.093, roast 0.062), the
  double tap to full screen and back, the share icon.

## End roast ends the cooling — 2026-10-24

- Real SW V2, empty drum, bean probe under 50 °C: the cooling started at Drop (the setup's
  EVT,8) kept running after End roast, whose OFF alone did not stop it. End roast now sends the
  setup's COOL END (EVT,9) after the 50 °C wait and before OFF, as the desktop's Cool end button.
  Python 149 tests passed. Accepted by the operator without a new roast; the link now logs each
  end-script command (TilauScopeTc4) should it need checking.

## Network saved at once, back from another app — 2026-10-23

- Python 149 tests passed (new: Network saved at each change, refused during a roast).
- Honor Pad 9: a Network change kept after the app was force-stopped from Android and opened
  again; Settings open, another app, back: Settings again, not the roast screen. The cause was
  not seen in the logs (the tablet was unplugged): both were handled — the page survives a
  configuration change, and a page Android closed in the background is restored.

## MQTT sensors, room conditions (MQTT-SPEC E1) — 2026-10-23

- Python 144 tests (6 new: a message's value, the room behind TilauAmbient, a partial room in
  the `.alog`, the Settings check) and Kotlin 18 tests (6 new: the MQTT 3.1.1 packets, a 275 kB
  retained message read past) passed.
- Honor Pad 9 against a test broker on the computer (`adb reverse`): connected, subscribed,
  live values in Settings › Network and in a sensor's sheet (°F converted), the Room pill from
  MQTT with TilauAmbient off and from TilauAmbient when it reads.
- Operator's broker (Jeedom, 192.168.121.34): the link dropped every 2 s on a 275 kB retained
  message until fixed; then connected, five sensors saved (roaster and extractor power,
  temperature, humidity, pressure), the Room pill at 20.4 °C from zigbee2mqtt with TilauAmbient
  switched off. SwiftKey capitalised the sensor's name although the field asked no capitals:
  a first letter typed into an empty field is lowered.
- After the code review (same day): ping once nothing was sent for half the keep-alive, TLS
  host name checked, Settings subscribed to the sensors' topics and the one typed, not to
  every topic. Python 144 and Kotlin 18 tests passed. Operator's broker: Settings shows
  Connected (a page asking for the same link is now told its state), values live, a topic
  changed in a sheet heard at its next message, the Room pill steady over 2 min on the roast
  screen.

## Bluetooth off, malformed frames, permissions (ACQUISITION-SPEC T3, T4, T5) — 2026-10-23

- Python 138 tests and Kotlin 12 tests passed (new: 5 on the roaster's frames).
- Honor Pad 9, TilauAmbient and Acaia scale on, outside a roast: Bluetooth off 30 s then on.
  Before: the app closed (Android 13's GATT write throws once the stack dies, uncaught on the
  scale's thread); then, fixed that, no accessory came back. After: no crash, Ambient and scale
  back within 20 s.
- Frames: "NaN"/"Infinity" no longer read as temperatures; a line with no end is dropped past
  256 characters.
- Permissions revoked (nearby devices, notifications): the Bluetooth question shows at launch,
  then at Start the roast link's Bluetooth question and the notification question one after the
  other (the second was dropped before). Bluetooth refused: red pill "Bluetooth not allowed" and
  the card with Android settings, which opens the app's page; allowed there and back, the pill is
  normal again and the Ambient and the scale reconnect (checked outside a roast).

## Roast clock and no sleep (ACQUISITION-SPEC 1b) — 2026-10-23

- Python: 138 tests passed (new: real clock, a late tick leaves a gap, the pill's 30 s, the
  `.alog` field). APK built; lint's errors are the six pre-existing `writeCharacteristic` ones.
- Honor Pad 9 with the Skywalker V2, operator test, 9:47 recorded with the screen off twice:
  the roast timer matched a stopwatch. The file: 552 samples, a tick every 1.057 s on average
  (the tick count read 9:16 for 9:47), one late tick of 17.2 s at 4:37 recorded in
  `tilau_late_sampling`, at the moment the roaster link dropped and came back. The app was
  already exempt from Doze and the wake lock held: the whole process was paused by the
  system's own app management; set to manual by the operator, made a prerequisite in the
  guide.

## Desktop Roast Replay on the shared engine (AUTOMATION-SPEC D3c) — 2026-10-21

- `canvas.playbackevent` takes the events that fire, the slider jumps and the ramps from
  `tilaucore.playback`; the sliders, the Fuji PID commands, the playback aid and its beep stay in canvas.
  `tilaucore.playback` gains `moves` (the aid alone), `fired` and `announced`; the tablet is unchanged.
- Bench: HEAD against the new code, 105 corpus roasts replayed live with the previous one as background,
  8 settings (the 5 replay types, the aid alone, event types and ramps switched off, a Fuji PID):
  681 696 samples, 1 632 593 side effects identical and in the same order; 2 planted mutations (moves always
  on, aid without Reproduce) caught. The D2 bench only covered BY_BT and BY_TIME.
- `test_tilaucore_playback.py` (+2), `test_playback_shared.py` (2, red on both mutations); tablet suite and
  desktop suite pass but `test_curve_snapshot_save` (PNG reload, unrelated).
- Operator run in the desktop simulator: Roast Replay as before. Accepted by the operator. D3 done.

## Desktop Auto Charge and Auto Drop on the shared engine (AUTOMATION-SPEC D3a) — 2026-10-21

- `ApplicationWindow.BTbreak` / `checkTop` keep their signatures and call `tilaucore.milestones`.
- Bench: HEAD against the new code on 106 corpus roasts, every sample, CHARGE and DROP, °C and °F,
  Standard and Sensitive modes crossed for CHARGE and DROP, 1 s / 0.5 s / 0.25 s delays: 8 935 056
  calls, 248 688 breaks, identical; 2 planted mutations (unit dropped, CHARGE mode read as the DROP
  one) caught.
- `test_milestone_detectors_shared.py`: the wiring test, red on both mutations. Desktop suite: all
  passed but `test_curve_snapshot_save` (PNG reload, unrelated).
- With it, Configuration › DETECTION holds the defaults of the four automatic milestones (Auto
  Charge and Auto Drop added) and Roast Setup chooses for one roast, back to the defaults at OFF
  (`auto_marks`, `test_auto_marks_defaults.py`); the setting lanes no longer stop the curve drawing
  with no step in the window (red test first).
- Operator run in the desktop simulator: Charge and Drop marked automatically, defaults and the
  per-roast choice as specified. Accepted by the operator.

## Desktop Dry End and First Crack on the shared engine (AUTOMATION-SPEC D3b) — 2026-10-21

- `tilau_intelligence.DryEndDetector` / `FirstCrackDetector` become adapters: they read Artisan's
  TP, delta2, the colour channel and the fused FC+SC counters, `tilaucore.milestones` decides;
  `tilauscope_types` takes the milestone windows from it.
- Bench: the detectors as they were (HEAD) against the adapters, fed the same qmc sample by
  sample, on 106 corpus roasts and 172 012 samples (Phases targets and the trade band, RoR given
  and computed): every result and every field the app reads identical; 2 planted mutations
  (delta2 not passed, crack badge not updated) caught. `tilaucore` against the desktop of before:
  still identical on the 106 roasts.
- `test_milestone_detectors_shared.py` (3 corpus roasts), red on both mutations. Desktop suite:
  2 772 passed, 1 failed unrelated (`test_curve_snapshot_save`, PNG reload).
- Operator run in the desktop simulator (Guji 74110, 2026-10-17): milestones and preheat as before.
  Accepted by the operator.

## Auto milestones and following a roast (AUTOMATION-SPEC D1, D2) — 2026-10-21

- `tilaucore.playback` (Artisan's background event playback, without NumPy): bench against
  `canvas.playbackevent` on 105 corpus roasts, identical moves and ramps; 5 planted mutations all
  caught. `tilaucore.lever_response` (the simulated roaster answering burner and air): gains from
  the corpus, burner 0.4 °C/min per point (10/10 roasts positive), air 0.33 in Maillard only.
- Tablet: `test_automation.py`, `test_follow.py`, `test_reacting_roaster.py`, `test_simulation.py`
  (slowdown before Charge); suite 137 tests.
- Simulator run, headless, on the 6 latest Skywalker V2 roasts of the corpus, 6 scenarios: Charge
  detection by hand on the file's Charge to the second, alarms on (6/6); Dry end detection at
  150.4–151.5 °C (6/6) and First crack with the counter at ~186 °C (5/5, the sixth has no counter);
  the plan's AUTO Dry end at its target after TP, alarms off, a touch on the air drops AUTO (6/6);
  following a roast, Charge found, the recorded moves played with their values (later when the
  simulated bean is behind, by BT as Artisan), lanes matching, a touch gives the levers back, alarms
  off (6/6); TP within 0–8 s of the file's, +15 % burner → +5.8 °C/min RoR (6/6); 8× back to 1× 29 s
  before Charge (6/6). Screen and the followed extractor (real AirWave only) not covered. Accepted
  by the operator on these results.

## Desktop alarms on the shared engine (ALARM-SPEC C4) — 2026-10-20

- Bench: canvas.py's new alarm block run against the loop it replaces (taken from HEAD) on 106
  corpus roasts × 4 tables (recorded + 3 random), with 20 samples of ON phase before START:
  identical firings sample by sample. A first draft was caught by it (wrong key names).
- `test_tilaucore_alarms.py`: 16 tests, with the firing placed at the first recorded sample
  before START (red without the fix). Desktop suite: 2 749 passed, 1 failed unrelated
  (`test_curve_snapshot_save`, PNG reload).
- Operator run in the desktop simulator with minimal.alrm: alarms as before; artisan.log of the
  run holds no error.

## Simulation by replay (SIM-SPEC S1, S2) — 2026-10-20

- `tilaucore.roast_replay`: 4 tests against `artisanlib.simulator.Simulator`; bench on 107 corpus
  roasts, °C and °F, 442 348 instants: identical readings bit for bit (BT, ET, every extra probe).
- Tablet: `test_simulation.py` (replay at 8×, extra channel from the file, pause and resume,
  Exit drops the roast and gives the levers back, preheat on the replay in simulated seconds and
  built before Start); suite 113 tests.
- Honor Pad 9: replay picto in BeanCave › Roasts, roast screen in simulation with no device
  connected, 1:37 after 12 s at 8×, alarms and TilauPID on the replayed curve, stock untouched,
  pause and resume, Exit back to the Skywalker V2. Start measured: ~8 s before, immediate after
  (preheat history loaded beforehand; 2.3 s → 7 ms on the Mac with the tablet's files). Accepted
  by the operator.

## Alarms on the tablet (ALARM-SPEC C1, C2) — 2026-10-20

- C1 `tilaucore.alarms`: `.alrm` read and written back byte for byte (the operator's lists),
  the desktop's firing rule; bench over 105 corpus roasts × 4 tables (recorded + 3 random),
  2 729 firings identical, sample by sample, to a verbatim copy of `canvas.py` 5251–5405.
  Live TP as `canvas.sample` (findTPint, 2-minute fallback). Setup reader: extra event buttons
  (270 presets, 1 339 buttons read). 19 desktop tests.
- C2 tablet: `AlarmLists` (Settings › Alarms, active list in the config), `TabletAlarms` run on
  the session's samples; levers through the operator's path (recorded, echoed, preheat paused);
  event buttons; AirWave and TilauAmbient commands through the service; extra probes by the
  computer's `tilau_name_map`. Roast screen: chip, yellow dots, toast, message banner, list with
  past greyed, a "now" line and the next alarm. 107 tablet tests.
- Emulator (simulation) and Honor Pad 9 + Skywalker V2, empty drum: all C2 checks run by the
  operator. Accepted.
- C3 editor: `remove_row`/`move_row`/`append_row` tested on the operator's list (a reference
  follows its alarm, is released when it goes; moved back = the same file byte for byte); tablet
  editor API tested (each change written to the .alrm, wrong fields refused, Undo, new and deleted
  lists). Honor Pad 9: lists, editor rows, zone sheets, swipe to delete, number as on/off, actions
  changed by the operator. 21 desktop tests, 110 tablet tests. Accepted.

## Tablet preheat and cool first (PREHEAT-SPEC P2) — 2026-10-16

- Controller moved to `tilaucore.preheat_controller` (start, stop, control step, safety
  stops, watchdog), desktop on hooks; the P1 benches stay identical (burner commands,
  learning, scanner). Tablet `TabletPreheat`: JSON store, past preheats of both roast
  folders, learning at Charge, pause on a burner touch and Resume, watched from the roast's
  first reading (the V2 answers 2–3 s after connecting).
- Cool first: End roast, a preheat safety stop and letting the link go hot run `OT1,0`,
  `CLDN,ON`, air 100 %, drum 80 %, a wait for BT under 50 °C, then the setup's OFF and
  `OFF`; BT and ET live while cooling. Start while cooling keeps the link: `CLDN,OF`,
  burner verified at 0, the new roast's air and drum.
- New roast guard (mockup UY7RFknqM7zEhJC85fbeN9): an unsaved roast asks for the save;
  a 5 s hold skips it. BT and ET with one decimal.
- Field order fixed (`READ` = ambient, ET, BT); the tablet's three test roasts and its
  learned preheat file were deleted.
- Tests: tablet 101. Honor Pad 9 + Skywalker V2, empty drum: preheat climbing at 80 %,
  pause and resume, cooling with BT and ET matching the roaster's display, OFF under 50 °C,
  Start while cooling stopping the cooling, the New roast guard. Accepted by the operator.

## The roast link on the real roaster (MACHINE-SPEC A0) — 2026-10-16

- Mockup FvxVRBaMS4XW1dJMzK5gJW; decisions: recovery guard armed from Start recording to
  End roast, burner free in a roast (0–100 %, 80 % only for the preheat), empty drum only,
  never beans; in-app drop test by a long press on the roaster pill (Android no longer lets
  an app switch Bluetooth off).
- `Tc4Link.kt` roast mode at parity with `tc4ble`: commands as whole numbers, burner echo
  above the command corrected at once (alert at two), silent link (3 s) dropped, reconnection
  by address (0.5/1/2 s), OT1,0 verified on a fresh echo at every connection, air and drum
  sent again on recovery, burner held at 0 and reported `recovered`. Core: readings as
  samples, file not simulated, burner held at 0 on connection, levers from the `.aset`
  sliders (clamped), `EVT,1`/`EVT,8`/`OFF` sent; commands leave through `take_commands()`.
- Tests: tablet 95 (6 new on the real roaster), desktop `.aset` reader. Honor Pad 9 +
  Skywalker V2, empty drum: connection and burner at 0, air/drum/burner echoes, low burner
  heating, several drop tests with recovery and the banner, Charge/Drop/End roast commands,
  the run opened on the desktop as a real roast. Accepted by the operator.

## Preheat controller shared (PREHEAT-SPEC P1) — 2026-10-15

- Moved to `tilaucore`: `preheat` (PIDConfig, SlowHoldIntegrator, ambient correction, the
  law's methods as `PreheatLaw`), `preheat_safety`, `preheat_thermal` (unchanged),
  `preheat_learning` (learning arithmetic, `AlogScanner` with an injected roast index,
  `PreheatLearning` with hooks `_settings`, `_simulated`, `_make_scanner`). Desktop
  `TilauPreheatPID` and `AdaptivePIDMixin` keep their signatures and give the hooks.
- Benches, identical before/after: 13 814 burner commands (14 scenarios: SV 160–200, °C/°F,
  SV change, probe spike/frozen/gap, three plants); 7 consecutive real (non-simulated)
  preheats learning in an isolated QSettings over a copy of the corpus (start P_ss/lead,
  commands, all 30 stored values); the scanner over the 106 real roasts (23 guided
  preheats) and its windows per machine and channel. 352 desktop tests passed, 0 contexts
  changed. Simulated preheat checked in the dev app by the operator. Accepted.

## Machine setup read (MACHINE-SPEC step A, reading) — 2026-10-15

- `tilaucore.artisan_setup.read_setup`: Qt INI read with the standard library, entries by
  name (RoR settings; commands at each milestone and at ON/OFF/SAMPLE/RESET/START; only
  `skywalker(...)` IO commands kept, any other action listed as unsupported). Against
  QSettings on the 270 bundled .aset: 376 values compared, 0 differences.
- Skywalker V2 BLE: Charge `EVT,1`, Drop `EVT,8`, Cool end `EVT,9`; DeltaSpan 15, delta
  filter 7, curve filter 3, drop-out filter on; no RoR limits in the preset (Artisan's
  defaults kept, the preset does not say their unit). End roast = the setup's OFF (empty)
  then `OFF`; the V1 Skycommand's stop is unknown and nothing is sent.
- Tablet: plan on the setup's RoR (span 20 → 15 s); commands logged by the simulated
  machine; the .aset packaged as `machine_setups` at build time and read from the APK on the
  emulator (Charge marked, no error). Tests: desktop 6, tablet 81 passed. Accepted.

## Reference roast line — 2026-10-15

- Mockup 5VerP9g3bxS44yEqcnS7nA (the tablet page itself rendered on real plans: Caturra,
  Medium, Omni, the 11 Oct roast starred on a copy of the BeanCave). Desktop sentences
  moved to `tilaucore.roast_plan_view.reference_line` and `roast_name` to
  `tilaucore.roast_summary`: 94 lines identical before/after, English and French.
- Desktop fix found while mocking: a plan learned from the reference alone (one roast,
  `operator_reference`) said "No earlier roast of this coffee could be used"; now "Based on
  your reference roast of this coffee". Test red then green; 53 desktop tests passed.
- Tested on the Android Studio emulator (Medium_Tablet, 2560 × 1600, seeded with the
  operator's BeanCave and 106 roasts, Caturra given stock in the copy): ★ at 180 g, ☆ with
  the weight reason at 250 g. Tablet tests 79 passed. Accepted.

## Roast label — 2026-10-14

- Mockup 6rarsgD9dgg4G2GQvyexNH; decisions: the desktop's 30 mm label unchanged, no QR,
  a line without a value left out on both (desktop fix), printed from the roast screen
  and the Roasts tab, no sheet.
- `tilaucore.roast_label` (label data moved from the desktop, the 30 mm lines): desktop
  212 real labels (30 and 80 mm) byte-identical before/after the move; empty-lines test
  red then green; 0 contexts changed. Pillow absent from Chaquopy for Python 3.14 (wheels
  stop at 3.13): drawn in `label.js` with DejaVu (copied at build) and Pillow's 1-bit
  advances/ink from `label-metrics.js` — Chromium vs Pillow on 7 real roasts: same breaks,
  truncations and positions, glyph pixels differ (antialias vs monochrome hinting).
- Honor Pad 9, B21S: label from the roast screen and from the Roasts tab, icon grey until
  the printer is found, then violet, pulse, tick. Tablet tests 79 passed. Accepted.

## Tasting on the tablet — 2026-10-14

- Mockup YYzEoT81DtcZSm1LsD14Vj; decisions: no invitation (Taste on an untasted roast),
  both owners, reference star in both modes, no shortcut from the roast screen.
  `save_tasting` writes `tastings.json` through `tilaucore.tasting_log.record`; the
  star sets `reference_roast_uuid` (one per coffee, replacing asks). "Next time" words
  shared (`NEXT_SAME`, `NEXT_TICK`); desktop 62 tasting tests, 0 contexts changed.
- Touch rule (Tilau): a zone opens when tapped — tasting banner, coffee sheet zones,
  flavour notes; Edit buttons removed.
- Tablet tests 75 passed. Honor Pad 9: banner, Taste, zones. Accepted.

## The plan behind the roast — 2026-10-14

- Mockup C8L6oPLyGWEi98EbQhDWny: planned BT and RoR dashed from Charge, planned
  milestones dotted at the foot of the chart, "Plan · level · use" chip, planned
  burner/air/drum steps dashed in the lanes (`plan.view` "steps" from
  `control_trajectories`); the time axis stretches to the planned drop. Anchored at
  Charge; re-anchoring at milestones comes with the assistant. No level, no plan.
- Honor Pad 9: Barazilie Medium Light 244 g Filter, before Start and while
  recording. Accepted.

## The plan on the tablet — 2026-10-14

- Mockup 1AcgqnV7pGYniVyVykgHaW, layout A with the use under the level, levels as
  buttons; no alarms, no PDF. `plan.py`: `TabletPlan` (the shared engine over the
  tablet's and the computer's roasts, both indexes), Artisan's default RoR settings
  with the span counted per roast (`RoRSettings.delta_span_s`, `delta_samples` checked
  against Artisan's `updateDeltaSamples`); room from the probe else 20 °C / 50 %,
  altitude from the probe else sea level; level and use kept in the configuration.
  Roadmap levers, cooled weight, tasting line and confidence moved to
  `tilaucore/roast_plan_view.py` and `tasting_log.CHANGE_WORDS` — desktop outputs
  byte-identical on 99 plans, 36 tasting lines, 6 confidence cases; 0 translation
  contexts changed.
- Tablet tests 72 passed (`test_plan`: states, roadmap, both folders read as the
  desktop engine). Honor Pad 9: Barazilie Medium Light 244 g Filter — roadmap, last
  tasting, "Based on 2 roasts", curve over the band. Accepted.

## BeanCave files and tastings on the tablet — 2026-10-14

- Mockup 4DSo2v91juQZAvYVi4xqo9. The cave moves as one set: `beancave.json`
  (required), `tastings.json` and `brewlog.json` (absent until first used on the
  desktop). Import: the BeanCave folder picked with `ACTION_OPEN_DOCUMENT_TREE`,
  staged; every file read as the desktop reads it (`GreenBean`, `TastingLog`,
  `BrewLog`) before anything is replaced; one unreadable file refuses the whole
  folder; a companion the folder lacks is removed from the tablet. Send:
  `ACTION_SEND_MULTIPLE` of the files held (provider path `cave/`). The folder copy
  is shared with the roasts import. Roast detail and full view show "Tasted: …" in
  the desktop banner's words (read only; entering a tasting is phase 2).
- Tablet tests 69 passed. Honor Pad 9: the operator's folder imported (33 coffees,
  6 tastings), the three files byte-for-byte identical to the desktop's; tastings in
  the roast memory and the Roasts tab; Send the BeanCave exported the three files.
  Accepted.
- Not yet: tastings on the tablet (`tastings.json` is not imported), so the memory
  shows no "Tasted"; the RoR drawn on a replayed roast is the tablet's 30 s slope,
  not Artisan's smoothing.

## Shared library, module 9: roast summary — 2026-10-14

- `tilaucore/roast_summary.py`: `RoastFacts`, `roast_facts`, `colour_category`,
  the four tiles as texts with their context and arguments; the desktop
  `viewer_detail` translates them and adds the roast cost; Energy and comparison
  tiles stay on the desktop.
- Operator decision: a whole-bean colour names its roast level when no ground
  colour was measured, on the desktop too. Before/after on the 106 roasts: the only
  differences are the Colour sub line of the 90 whole-bean roasts ("Whole bean" →
  "Whole bean · Light"); the test of the old rule rewritten. Desktop targeted tests
  385 passed (`test_curve_snapshot_save` failing before). `docs/after-the-roast.md`
  updated. Operator: desktop checked. Accepted.

## Shared library, module 8: roast memory — 2026-10-14

- `tilaucore/roast_levels.py` (level table, arrival pair, `measured_level`),
  `tilaucore/tasting_log.py` (whole module), `tilaucore/roast_memory.py` (last
  roast, batch label); desktop relays. Reference state and readiness to taste stay
  on the desktop until the plan moves (they need the plan model and the brew
  advisor).
- Before/after snapshot on the operator's data identical byte for byte: levels of
  106 roasts (no offset and Skywalker offsets), memories of 28 coffees with 6
  tastings. Desktop targeted tests 703 passed; tablet suite passed. Operator:
  desktop unchanged. Accepted.

## Shared library, module 7: roast index — 2026-10-14

- `tilaucore/alog_index.py`: partial reader, `AlogMetadata`, burner per phase,
  folder scan and index file (plain JSON instead of mashumaro);
  `tilaucore/artisan_compat.py`: the four Artisan helpers it needs, checked against
  `artisanlib.util` by `test_artisan_compat`. The desktop `alogmanager` keeps the
  index location and its Qt background refresh, and re-exports the rest.
- The operator's 106 roasts give identical records before and after (0.5 s each);
  a file written by the new code reads back identically with the old reader. The
  stored index (schema 4) is rebuilt by both, as before. Desktop targeted tests 703
  passed; tablet suite passed. Operator: desktop unchanged. Accepted.

## Editing coffees — 2026-10-14

- Mockups LkunhWBsZCkemtvWuBJKAw v3 and LPHL8JGB3VmhMZiLkfxGn9 (dial, variant C,
  off-centre geometry of the first build) approved. ✎ Edit per zone and
  + New coffee, tablet owner only; `cave-edit.js` and `flavour-dial.js`.
- Shared with the desktop: `tilaucore/flavour_wheel.py` (data identical to a
  snapshot taken before the move; `notes_text`) and `tilaucore/bean_edit.py`
  (zones, limits, required fields, `apply`). The desktop zone editor saves
  through `apply`: identical records on the operator's 33 coffees × 9 edits.
  Its spin-box limits stay literal (guarded by `test_bean_form_holds_every_record_value`);
  a new test checks the shared table against them, proven red.
- Devices as on the desktop: scale beside Stock (Use when stable), ⚖ Measure
  for density (50–500 ml, tare, net ÷ volume), AquaGauge beside Water activity
  (Use once the measurement ends); a device the editor woke is let go on close.
- Saving rewrites `beancave.json` with the desktop's serializer. Tablet tests 55
  passed; desktop targeted tests 68 passed. Checked on the Honor Pad 9 by
  screenshots (editors, lists, density and aw cards, new coffee, keyboard,
  dial); `windowSoftInputMode=adjustResize`. Accepted by the operator.

## BeanCave screen and the coffee of the roast — 2026-10-13

- Mockup Coj6EimzAjUMJ9gZfqnPL7 v3 approved. Bean button beside Settings (hidden
  while recording) opens `beancave.html`: In stock / All, search ignoring accents,
  the desktop sheet zones (Essentials, Roast memory, Characteristics, Provenance;
  no Edit until editing comes). Roast this coffee: header pill with stock left,
  peach when the green weight asks more; kept from roast to roast, refused while
  recording, dropped when an imported file no longer holds it.
- Shared with the desktop (`tilaucore/bean_text.py`, `family_pace`,
  `tilaucore/currency.py`): title "name - process - crop" and the beans text with
  its `uuid:` line, identical to the desktop on the 33 coffees of the operator's
  BeanCave; Roast Setup, the repair tool and the bean sheet now use them.
- The title and beans text go to the journal header and the `.alog`; an
  interrupted roast keeps them. Tablet tests 51 passed; desktop targeted tests
  200 passed.
- Currency (mockup 8UMginTXmh9Ti1gXqY5eG9 approved): Settings › BeanCave row, the
  desktop's 22 currencies, the system one (from Android) until one is chosen;
  price in the system number format with the shared symbol.
- Operator on the Honor Pad 9: list, sheet, pill, currency and list spacing
  accepted.

## Shared library, module 6: bean qualifiers — 2026-10-13

- The rule of `physical_qualifier`, the density thresholds and the screen sizes
  moved to `tilaucore/bean_qualifiers.py`: English text with its translation
  context, declared with a local no-op `QT_TRANSLATE_NOOP`, and a level instead of
  a theme colour. The desktop module keeps its interface and translates with
  `QApplication.translate(*text)`.
- Translation tools: `tilaucore/*.py` added to `artisan.pro` SOURCES and to
  `context_map.json`; retarget dry run: 0 call sites change context; PyQt's
  extractor finds the 15 texts in their original contexts. Doctrine: the form
  `translate(*text)` accepted for shared texts; two new checks (literal
  declarations, tilaucore in `artisan.pro`), each proven red.
- Same words and colours as a baseline taken before the change (value grid with
  limits, screen sizes). Desktop suite 2713 passed (`test_curve_snapshot_save`
  failing before the bench). Operator: bean sheet and form unchanged. Accepted.
- Tablet, same day: once a ground colour is entered, the whole-bean cell drops its
  level name (ground prevails); without ground, the whole bean keeps it.

## Shared library, module 5: roast colour — 2026-10-13

- `AgtronRange`, `AgtronScale`, `AGTRON_SCALES`, `to_agtron`,
  `DEFAULT_COLOR_SYSTEM`, `resolve_color_system`, `get_agtron_color` moved
  unchanged to `tilaucore/roast_colour.py`; `ensure_color_system` (writes the
  Artisan canvas) and `get_roc_color` (Omniflux display) stay on the desktop. The
  tablet's copy (`colour.py`) removed; its levels now built from the shared scale
  (identical, checked before removal).
- 435 related desktop tests passed; desktop suite 2711 passed
  (`test_curve_snapshot_save` failing before the bench); tablet tests OK.
- Operator: desktop target levels and roast colours unchanged; tablet colour row
  unchanged. A whole-bean reading shows a hollow tint without a level name on the
  desktop (deliberate since build 27); the tablet keeps the level name, also for a
  whole-bean or hand-entered colour (operator's decision). Accepted.

## Shared library, module 4: bean energy — 2026-10-13

- `bean_energy.py` moved unchanged to `tilaucore`; the old path re-exports it.
  366 related tests passed (bean energy, roast plan model and construction);
  desktop suite 2710 passed (`test_curve_snapshot_save` failing before the bench;
  `test_widget_leaks` failed once in parallel, passes alone, unrelated).
- Operator, development version: bean family on the bean sheet and the roast plan
  unchanged. Accepted.

## Shared library, module 3: green coffee records — 2026-10-13

- `GreenBean`, `BeanCaveContainer`, `ReferenceProfile`, `BrewDialIn`,
  `RoastTasting`, `TastingLog`, `BrewSample`, `BrewLog` moved field for field to
  `tilaucore/beans.py`, with a standard-library reader/writer replacing mashumaro
  for them (same conversions: 1200 → 1200.0, "2025" → 2025, null → "None" or
  False, unknown keys ignored, missing keys default, ValueError otherwise).
  `tilauscope_types` re-exports them; 8 desktop call sites switched; the tablet's
  cave reads with the same reader.
- Bench: the operator's beancave.json, tastings.json and brewlog.json give
  byte-identical output with old and new code; 21 edge cases identical. Desktop
  suite 2710 passed (3 test fixtures that mocked `cave.to_json()` moved to real
  containers; `test_curve_snapshot_save` failing before the bench). Tablet 46.
- Operator, development version: bean name edited and saved, a tasting recorded
  (file re-read identical by both readers); tablet import 33 / 5 / 6.7 kg.
  Accepted.

## Shared library, module 2: data files — 2026-10-13

- `roasters.json` and `beancave_beans.json` moved unchanged to `src/tilaucore/data/`,
  named once in `tilaucore/data_files.py`; desktop readers (`roasters.py`,
  `cave/lifecycle.py`, `test_machine_setup.py`) and both build files (mac `datas`,
  Windows copy to `_internal\tilaucore\data`) switched; the doctrine test now also
  checks `tilaucore` (red proven with the file removed).
- Desktop suite 2711 passed (`test_curve_snapshot_save` failing before the bench).
  macOS PyInstaller build into a scratch folder: `tilaucore` modules in the archive,
  both files in `Contents/Resources/tilaucore/data/`. Windows: build file and NSIS
  (`File /r`) reviewed, not built.
- A first check ran the old installed app (`/Applications`, 4.2.17 build 5, August)
  and showed its old behaviour; the development version shows the current lists.
  Accepted by the operator on the development version.

## Shared library, module 1: storage advisor — 2026-10-13

- `storage_advisor.py` moved unchanged to `src/tilaucore/` (standard library only);
  `tilauscope/storage_advisor.py` re-exports it; the tablet's copy of the aw zones
  (`water-check.js`) replaced by the shared thresholds; the Android build takes
  `tilaucore` from `src/` and nothing else (APK content checked).
- Desktop: self-check OK, old and new paths give the same objects, full suite
  2710 passed; `test_packaging` taught that `tilaucore` is first-party;
  `test_curve_snapshot_save` fails with and without the move (not related).
  Tablet: 46 tests passed.
- Operator: desktop BeanCave Storage tab unchanged; tablet AquaGauge check
  unchanged. Accepted.

## BeanCave import / export — 2026-10-13

- Python: 46 tests passed (a Windows file with BOM and CRLF stored and given back
  byte for byte; non-BeanCave files refused without change; empty cave written as
  the desktop's empty container; stock owner setting).
- Honor Pad 9: the operator's desktop `beancave.json` (33 coffees, 5 in stock,
  6 728 g) copied to Download, imported through Android's file picker, exported,
  replaced over an existing cave with the comparison sheet, and a wrong file
  refused. Accepted by the operator.

## Label printer — 2026-10-13

- Honor Pad 9, Niimbot B21S, 30 mm roll, check from Settings › Devices: desktop
  protocol and D110M V4 print flow ported to Kotlin (initial packet, heartbeat,
  roll tag, density 3, printStart, page size, 0x84/0x83/0x85 rows with repeats,
  pageEnd, status poll until the label is out, printEnd); label drawn on a canvas,
  black and white, 384 × 240. First label: bottom line outside the label, roll
  badly loaded; after reloading, the second label printed perfectly. Accepted by
  the operator.

## Water activity meter — 2026-10-13

- Honor Pad 9, RoastSee AquaGauge, check from Settings › Devices. Captured frames:
  a 15-byte signature on connect, then ASCII `aw=0.705,dew=60.078` lines. A
  measurement opens with a few `aw=0.000` values, then streams about one value per
  1.1 s for about 2 minutes (one capture also showed ~8 values per second).
  The last value is final after 2 s without a new one, as on the desktop.
- `dew` is not shown on the meter (which shows temperature, time and aw) and its
  unit is unknown (~62 at about 23 °C, aw 0.64): not used.
- Curve with aw axis, elapsed time and zone limits; storage zone and Check done.
  Accepted by the operator.
- Meter switched off during a measurement: Android reported the loss late and the
  last intermediate value was taken as final. Fixed: the silence is confirmed by
  reading the characteristic (no answer in 3 s = lost, measurement discarded), and
  an idle link is read every 5 s. Loss detection reviewed for every link: V2 3 s,
  AirWave 5 s, Acaia 15 s unchanged; room probe now lost after 5 s without a read
  answer; C1 read every 5 s, lost after 8 s. Test buttons in Settings › Devices are
  grey while the device is not heard. Accepted by the operator.

## Roast file (.alog) — 2026-10-13

- Python: 41 tests passed, including a full roast exported and read back with
  `ast.literal_eval` (as the desktop deserializes), and a guard reading the desktop
  sources (`ProfileData`, `ComputedProfileInformation`, device registry) without
  importing them: every key written must exist there.
- Honor Pad 9: Save roast wrote `TilauScope roast_26-10-13_1306.alog` (copied to the
  Mac by hand). The share sheet did not open: the file path was read back as JSON
  and refused, so the screen also said the save had failed; fixed (the path is now
  passed as text). Since then: the share sheet opens, and Saved stays after the app
  is closed and reopened; New roast followed by a restart returns to Ready. The
  weight and colour wheels in the summary no longer close by themselves. Accepted
  by the operator. Opened in desktop TilauScope: curve, CHARGE and the four settings
  lanes shown. A complete simulated roast (all milestones, weights, colours,
  extractor and probe curves) produced by the same code opened with its summary.
  Accepted by the operator.
- Simulated roasts carry `tilau_simulated` (added after the first two files, which
  were patched by hand) so they stay out of the desktop's learning.
- Not written: AUC, RoR by phase, energy and preheat keys; the desktop computes
  them when it saves the roast again.

## Not yet validated

- BLE hardware, real network devices, permissions, foreground service,
  screen-off operation, process-death recovery and actuator behavior.
- `.alog` interchange and numerical parity with desktop RoR or guidance.
- Desktop runtime regression suite: not rerun because desktop sources,
  dependencies and build configuration were unchanged.

The next validation gate is M1: the Android runtime (service, permissions,
journal, activity recreation) and simulation checks on an ARM64 device. Hardware
support remains gated by the milestones in the specification.

## Energy tile period, review fixes — 2026-10-24

- Energy tile reads **Charge → Drop** under its kWh (option B of the mockup), desktop and tablet; validated by the operator on both. The desktop line was cut by the tile's width (seen on the doc captures): kWh/kg left the tile for the energy sheet, operator's choice. Tests: `test_roast_detail` (desktop, 7), `test_energy` (tablet).
- Review fixes, tablet: RoR change in the unit shown; energy sheet above the full-screen curve (checked on the tablet); milestone clock never `x:60`; Settings shows the unit being chosen before saving (checked: room 68.7 °F); an alarm keeps its shown value when only its source changes; a typed 500 °F is a threshold; the preheat range is said in °F; a deleted alarm list leaves no shared copy. Four red tests proven, 161 Python tests OK.

## Deleting a roast, reference star — 2026-10-24

- Tablet, BeanCave › Roasts: swipe right shows the bin, the confirmation matches the mockup, Delete removed the dry test of 24 Oct 17:29; the next roast took its place, the coffee's roast memory went from 5 to 4 roasts (last roast 23 Oct). The coffee's "Roasts" count is the stock-decrease count and stays, as the stock does (operator's choice). Refused during a roast or a simulation. Test: `test_roasts` (red proven), 162 Python tests OK.
- Reference ★: deleting its roast on the tablet clears it (test, red proven; not seen on screen). Desktop: removed at the next index pass when the file is gone, kept when the folder is unreachable — `test_reference_roast` (red proven) and a simulation of the index pass on corpus files (present → kept, deleted → removed and saved, folder missing → kept); not run in the app. Desktop fast suite: 2785 passed; `test_curve_snapshot_save` fails alone on untouched code, `test_qr_debug_snapshot` passes alone.
