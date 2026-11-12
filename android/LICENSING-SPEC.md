# Shared core free of Artisan code — study, 2026-11-08 (revised)

**Done: every lot validated by Tilau on 2026-11-10 and shipped in 4.3 build 57; no Artisan line is left in `tilaucore` nor in the tablet (§7).** The rest of this document is the study as it was written, kept for the reasoning.

To validate before any code. Goal: the desktop and the tablet keep **one shared core**
(`src/tilaucore`), and that core becomes Tilau's own code only. Each piece that came from
Artisan is **redesigned with Tilau, at a calm pace**, one lot at a time. It is not a rewrite of
Artisan's method: Artisan's processing, with the variants it gathered over the years, is not the
reference. The reference is **the right moment**. A curve or a detection may land at a different
sample than Artisan's; what counts is that it lands where it should on the roast.

The desktop fork stays AGPL with its `## TILAU ##` grafts. Not a legal opinion: the licensing
point (§6) is to be checked by a lawyer before an APK ships under other terms.

## 1. What reaches the APK today

Chaquopy packages `android/python` (`tilauscope_mobile`), `src/tilaucore` and the
`machine_setups` built from two `.aset` files (`app/build.gradle.kts`). No `artisanlib`, `plus` or
Qt: `android/tests/test_isolation.py` checks the imports. The Kotlin links and the WebView
pages are the app's own sources.

So the question is not imports but **code carried over**: functions written by reading Artisan.

## 2. Inventory of what is derived

As found on 2026-11-08. Every entry below has since been redesigned or reworded (§7).

### 2.1 Declared (header "Portions derived from Artisan Roaster Scope")

| File | Derived piece | Artisan source | Nature |
|---|---|---|---|
| `tilaucore/artisan_compat.py` | `convertWeight`, `decodeLocalStrict`, `events_internal_to_external_value`, `from*strict`, `RoR*strict`, `convertTemp` | `util.py` | formulas of the file format |
| | `fill_gaps`, `medfilt`, `_smooth_slice`, `smooth_list`, `compute_deltas`, `recompute_deltas`, `recompute_bt_deltas`, `delta_samples`, `profile_sampling_interval`, `RoRSettings` defaults | `util.py`, `canvas.py` | standard maths (finite differences, median filter, linearly weighted moving average, interpolation), written as Artisan writes them |
| `tilaucore/milestones.py` | `BTBREAK` table, `check_top`, `bt_break`, `charge_index`, `drop_index`, `CHARGE_MIN_BT`, `DROP_MIN_BT`, `DROP_MIN_S` | `main.BTbreak`, `checkTop`, `canvas.sample` | Artisan's own detector design |
| | the rest (`resolve_*_window`, `FirstCrack`, `DryEnd`) | — | Tilau's own (tilau_intelligence) |
| `tilaucore/playback.py` | whole file: `Playback`, `Foreground`, `_line`, replay types | `canvas.playbackevent`, `timealign`, `updateReplayedBackgroundEvents` | faithful transcription, Artisan's quirks included ("operator precedence included") |
| `tilaucore/roast_replay.py` | `Replay` (prefix removal, time shift, swap of extra channels) | `simulator.py` | trivial; most of the file is numpy's `interp`/`binary_search_with_guess` (numpy: BSD) |
| `tilaucore/alarms.py` | `AlarmRun` (firing rule), `TurningPoint` (`findTPint`, `TP_max_roasttime`), `slider_value`, `event_buttons` | `canvas.sample` alarm loop, `util.findTPint` | Artisan's firing rule |
| | `Alarm`, `_KEYS`, `read_alrm`, `read_profile_alarms`, `write_alrm`, codes, `remove_row`/`move_row`/`append_row` | — | the `.alrm` format and Tilau's editor |
| `tilauscope_mobile/alog.py` | `find_tp` (= `findTPint`, duplicate of `TurningPoint._lowest`), `float2float`, `weight_loss`, `event_value`, `_computed` fields | `util.py`, `main.computedProfileInformation` | small rules of the format |
| | `profile()`, `_events`, `_extra_devices`, `file_name`, `write` | — | Tilau's own writer |
| `app/.../Scales.kt` | `SettledWeight` (350 ms rule) | `scale.py` | tiny rule |

### 2.2 Not declared, found by reading

| File | Finding | To do |
|---|---|---|
| `app/.../AcaiaLink.kt` | "same protocol as the desktop driver": the desktop driver is `artisanlib/acaia.py` (Artisan's, AGPL). `decodeWeight` follows `acaia.decode_weight` line for line (byte order, unit divisor, sign bit `0x02`, stable bit `0x01`) | on the lock list; redesigned in L3 from the protocol |
| `tilaucore/backup.py`, `coffee_share.py`, `archive.py` | header says "a fork of Artisan Roaster Scope": wording only, the code is Tilau's | reword the header (§6) — done 2026-11-12 |

### 2.3 Checked and own

- `.aset` files `skywalkerv2-ble.aset`, `skywalkerv1-skycommand.aset`: **not in upstream Artisan**
  (`upstream/master` has no `Machines/Skywalker`); written by Tilau, in Artisan's format. They stay.
- `tilaucore/artisan_setup.py`: reads the `.aset` format, Tilau's code.
- `Tc4Link.kt` and the desktop `tilauscope/tc4ble.py`: Tilau's private BLE loop.
- Decent and Bookoo (`Scales.kt`, `tilauscope/scales/decent.py`, `bookoo.py`): Tilau's drivers;
  the desktop ones sit on Artisan's `ClientBLE` base class, but the protocol code is Tilau's.
- The ~45 other `tilaucore` modules: they *mention* Artisan (keys, sentinels, units, conventions
  of the format) but carry no code from it.
- Git authorship of `src/tilaucore` and `android/`: Tilau only.

### 2.4 Who calls the derived pieces

| Derived piece | Desktop callers | Tablet callers |
|---|---|---|
| conversions, event values | `roast_plan`, `alog_index`, `preheat_learning`, `cave/common`, `cave/standalone`, `roast_plan_model` | `alarms`, `alog`, `demo`, `follow`, `plan`, `roasts` |
| RoR pipeline | `tilauscope/ror.py`, `roast_plan_model`, `roast_plan`, cave, graph, `roast_review_panel` | `follow`, `demo`, `plan` |
| `bt_break`, `check_top`, thresholds | **`artisanlib/main.py:167`, `canvas.py:132`** (grafts) | `automation`, `demo` |
| `AlarmRun`, `read_profile_alarms`, `PROFILE_KEYS` | **`artisanlib/canvas.py:130`** (graft) | `alarms`, `automation`, `demo` |
| `Playback`, `Foreground` | **`artisanlib/canvas.py:131`** (graft) | `follow` |
| `Replay` | — | `demo` (simulator) |

The `artisanlib` grafts import **public names of tilaucore**. Those names are the contract:
they never change, only what is behind them. So **no line of `artisanlib` changes**, neither
in C nor in A.

### 2.5 The tests that compare with Artisan

`src/test/test_artisan_compat.py`, `test_playback_shared.py`, `test_tilaucore_roast_replay.py`,
`test_milestone_detectors_shared.py` (and `roast_harness.py`, `test_roast_plan_p2.py`) import
`artisanlib` and check that tilaucore gives Artisan's answers. Equality with Artisan is no longer
the goal: each lot retires the equality checks of its piece and replaces them with tests of the
right moment (§3).

Other tests on these modules: `test_tilaucore_alarms`, `test_tilaucore_playback`,
`test_tilaucore_milestones`, `test_ror_module`, `android/tests/test_alog.py`, `test_unit.py`.

## 3. How each lot is done, together

1. **What "the right moment" is**, decided with Tilau first. Plain words, roasting terms, the
   curve signature that shows it (the roaster skills are loaded for this; no roasting fact is
   invented). Written in this file under the lot, committed alone.
2. **Design** of the rule from that definition, by Claude, presented before code: what it reads,
   when it decides, what it does when the probe is noisy or missing.
3. **Bench on the corpus** (`~/Documents/artisan/roasters`) and on the virtual Skywalker of
   `make android`. Its result is a **visual page**: one line per roast, where the new rule lands
   against the recorded mark, the disagreements drawn on their curves. Recorded marks are not the
   truth: many were placed by Artisan's own detector, or by hand late. Tilau judges the
   disagreements on the page.
4. **Code**, once Tilau has validated the bench: the public name stays (`bt_break`,
   `AlarmRun`, `Playback`, `recompute_deltas`…), so the `artisanlib` grafts and the tablet see
   nothing but the new behaviour. The Artisan-derived lines and their header go.
5. **Tests of the right moment**: the bench's validated cases become the tests (a few named
   roasts, the virtual roaster); the "same as Artisan" checks of the piece are removed.
6. Desktop and tablet change together, since they share the code. The desktop is checked with
   `tools/autopilot/offscreen_roast.py`; the tablet with `make android`. No step asks for a real roast.

**Lock** (added with the first lot): `android/tests/test_licence_boundary.py` lists the files still
derived from Artisan (§2.1, plus `AcaiaLink.kt`). The list can only shrink; an Artisan copyright
line anywhere else fails. When the list is empty, the rule becomes "no Artisan line in
`tilaucore` and `android/`".

## 4. The lots

| Lot | What | What "the right moment" asks | Size |
|---|---|---|---|
| **L1** | Units: °F/°C, RoR units, weights, event-value codec, text decoding, rounding, weight loss | nothing to decide: formulas of the file format (an `.alog` must read the same) | short |
| **L2** | Simulator: a recorded roast replayed as readings | read the curve faithfully at any time | short |
| **L3** | Scale: when a weight is settled; Acaia frames | settled when the operator's hand is off the scale; frames from the protocol | short |
| **L4** | Turning point: one rule instead of two copies | the TP is where the bean temperature stops falling and turns, on a noisy probe too | short |
| **L5** | Auto CHARGE and DROP | CHARGE when the beans go in (the BT probe plunges), DROP when they leave; not fooled by a probe glitch, a lid opened, a preheat oscillation | medium |
| **L6** | RoR: how fast BT rises, and how it is smoothed | the true trend, early enough to act, without the noise; see §5 | medium + recalibration |
| **L7** | Alarms: when a row of an `.alrm` fires | the meaning of each field (anchor, delay, condition, source, guard, relative alarm) as an operator reads it; a list fires the same on desktop and tablet | medium |
| **L8** | Roast Replay: following a background roast's moves | the move comes when the roast reaches the same point (time or temperature), ramps without jumps | long |

Suggested order: L1 → L2 → L3 → L4 → L5 → L7 → L8 → L6. The short lots empty the list quickly
without a decision to take. L5 is the first true "right moment" lot. L6 goes last, because it
moves the plan (§5).

## 5. The RoR and the plan

The plan's doctrine was measured with the current RoR: the RoR ceiling (SW 16, default 21), the
Skywalker envelope 16→12→8→5, the planned rebound, the timing rules, the Dry End and First Crack
detectors, AUTO. A different RoR (another smoothing, less lag) shifts those numbers. So L6 is
three steps:
1. design the new RoR with Tilau (§3);
2. **re-measure on the corpus** every doctrine value that reads a RoR, with the old and the new
   side by side, and let Tilau validate each new value;
3. switch the plan, the detectors and the display together.

Until L6, the current RoR stays, rewritten if needed but numerically unchanged, so that nothing
moves before the recalibration is done.

## 6. Licensing, once the list is empty

- Desktop: `tilaucore` is published with the fork (`tools/publish/include.txt` has `src/**`) and runs
  inside an AGPL Artisan, so it stays `AGPL-3.0-or-later`. No header changes.
- Tablet: **decided 2026-11-12, the APK stays AGPL-3.0-or-later**, no commercial intent: the aim is to
  bring others to work on it. `android/` is now published with the fork (`tools/publish/include.txt`),
  which also gives the test builds already handed out their source. `android/NOTICE` and the root
  `NOTICE` say so; `CONTRIBUTING.md` (TilauScope's own, replacing Artisan's) states that contributions
  come in under the AGPL.
- The three "a fork of Artisan Roaster Scope" headers (`backup.py`, `coffee_share.py`,
  `archive.py`) are reworded: done 2026-11-12 (the short header of the other core files).
- A contributor agreement if anyone else ever contributes to `tilaucore`: set aside for now (Tilau
  2026-11-12).
- AI-assisted code: stated as co-construction in the README (text to validate, 2026-11-12).
- Reading Artisan's sources is not cited: every definition of §3 comes from roasting and was set by
  Tilau, lot by lot (Tilau 2026-11-12).
- Earlier versions stay in the fork's history under AGPL. That does not bind the new versions.

## 7. Progress

Night sessions (2026-11-08): lots with nothing to decide are coded; lots that need Tilau's
"right moment" get a proposed definition and a bench page, no code, until he validates.
All lots validated by Tilau on 2026-11-10, shipped in 4.3 build 57 (release notes, docs, captures 4.7 and 7.17,
translations). Auto DROP per roaster (2026-11-12): 22 roasts of 8 other roasters peak 0–6 s after the beans leave, so the
default probe lag is 2 s (was 6, the Skywalker V2's, which it keeps declared); the Cormorant CR600e declares
0 s (9 roasts marked by hand, BT peaks as the beans leave). The 3 °C fall holds everywhere (reached 2–14 s
after the drop). Aillio Bullet R2: 3 usable roasts, on the default until about ten. Still open: the drop
door contact on the tablet (in design).

| Lot | State | Notes |
|---|---|---|
| L1 | validated 2026-11-10, build 57 | `tilaucore/units.py` (own); `artisan_compat` and `alog.py` re-export it under the old names. Weights use the exact pound (453.59237 g), not Artisan's constant (gap ~1e-10 g). The event-value check against the desktop stays: it is the format. Lock `android/tests/test_licence_boundary.py` added; `AcaiaLink.kt` now carries its Artisan header. `test_tilaucore_roast_replay` compares approximately (°F last bits) until L2. Pre-existing failure, unrelated: `android/tests/test_cave.py` (stock keys in the empty cave). |
| L2 | validated 2026-11-10, build 57 | `tilaucore/roast_replay.py` rewritten (own): each probe read straight between its real readings, a dropout (-1) skipped instead of drawn as a plunge (Artisan interpolated towards -1), a sample stepping back left out, -1 before a probe's first reading, last reading held. The numpy emulation is gone. `src/test/test_tilaucore_roast_replay.py` (equality with Artisan's simulator) replaced by `android/tests/test_replay_curves.py`. |
| L3 | validated 2026-11-10, build 57 | `SettledWeight` (Scales.kt) redesigned: stable when the scale flags it, or when the reading stays within 0.5 g of where it settled for **500 ms** (was: the rounded gram unchanged for 350 ms; a reading flickering across a gram boundary never settled). Acaia weight decoding rewritten from the protocol (little-endian count, decimals, flags; exact ounce). Kotlin tests: 29 pass, one new (flicker). |
| L3b | validated 2026-11-10, build 57 | Tilau 2026-11-09: one rate, re-ask after 2 s without a weight, no fast/slow. `AcaiaLink.kt` asks weights once the ID is sent, again only after `WEIGHT_REQUEST_MS` (2 s) without one; Artisan header removed. New test `weightsAreAskedOnceThenAgainOnlyAfterTwoSecondsWithoutOne`. |
| L4 | validated 2026-11-10, build 57 | Tilau 2026-11-09: the TP is the low turning point after CHARGE, before Dry End; none after (a crash would pass for one). `tilaucore.milestones.turning_point`: smoothed BT (median of 5) lowest between CHARGE+15 s and the first of the next milestone marked and CHARGE+4:00, middle of a flat bottom (0.2 °C), known once BT is 1 °C above it; no TP placed by the clock (Artisan's 2:00 fallback gone). `alarms.TurningPoint` and `alog.find_tp` use it. Corpus: 110/110 found, 73 s (IQR 69-78), known 16 s after it. `roast_analysis.find_turning_point_index` (plan, coach, cave) untouched: the plan's doctrine is calibrated on it. Bench: https://claude.ai/artifact/BDGQnzoBSiDS2ixc3gVhYY. |
| L5 | validated 2026-11-10, build 57 | Tilau 2026-11-09: CHARGE is one sample before the clear plunge; a gentle slope before it is the PID easing off. `charge_index`: BT lost ≥ 4 °C within 8 s from above 77 °C, the last two readings low; placed by walking back while BT falls ≥ 0.4 °C/s. Corpus: 104 compared with Artisan, 96 within 2 s, 1 earlier, 7 later (gentle PID slope), 1 missed. **DROP** (Tilau: automatic as an option, marked even late; a replay reproduces the recorded DROP): a crash slows BT, it never makes it fall (FC to DROP, 0.1 °C at most on 110 roasts, Guji crashes included); BT still rises ~6 s after the beans leave, peaks, then falls. `drop_index`: BT ≥ 3 °C under its peak of the last 2 min, the last two readings low; placed 6 s before the peak; tablet looks after FC, desktop behind Artisan's gate (7 min, 160 °C). Corpus: 102/110 found (7 of the 8 misses end their recording at DROP), 0 before DROP, median 0 s from the recorded mark, 80 within 5 s, 19 later than 5 s (long plateau), known ~16 s after (Artisan: 92 found, +10 s, 6 within 4 s, known +14 s). The desktop's CHARGE/DROP modes (Standard/Sensitive) are no longer read. Next: a dry contact on the drop door, wired to TilauProbe (to design with Tilau). Per machine: roasters.json `drop_fall_c`, `drop_probe_lag_s` (declared for Skywalker V2: 3 °C, 6 s; others take the shared defaults); the desktop's roaster resolver passes them with `set_drop_roaster`, the tablet with `machine.drop_detection`. Devices › Charge and Drop text rewritten (validated), it shows the roaster's fall. Bench: https://claude.ai/artifact/VmKV1RtwPyZajYkmv2eZTH. |
| L7 | validated 2026-11-10, build 57 | Tilau 2026-11-09: a delay counts from the anchor's place (a milestone marked late fires what is already due at once); a delay and a temperature on one row must both hold, checked at each sample; a limit already past when the anchor comes fires at once; a lost probe (-1) holds the rows that read it. `AlarmRun` rewritten (own), same `Readings`/`step` contract, desktop and tablet. Also own: a row with no delay and no source fires on its anchor (Artisan never fired it); "above"/"below" are strict for an If Alarm too (Artisan fired on equality); an extra device channel is read as named (Artisan read the second when the first was empty). Corpus, 110 roasts, 1 623 active rows: 1 608 fire at the same sample; 13 "milestone + 0 s" rows (2025-07/08 lists) now fire; 2 "DROP + 1 s and BT under 100" rows wait for BT (3 min later). |
| L8 | validated 2026-11-10, build 57 | Tilau 2026-11-09: engaged at CHARGE; a move by time until the live TP, then when the live BT reaches the move's recorded BT; no ramp, each move a jump as the hand made it; nothing after the DROP (cooling as usual); by time throughout without a recorded BT. `playback.py` rewritten (own), same contract: at CHARGE each lever takes the recorded roast's setup (its last preheat move); a lever not replayed is not followed; the live DROP stops it (`Foreground.dropped`, the tablet passes it); `held()` gives each lever's value so a replay resumed after a dropped link sends it again (the ramps used to). Artisan's ET and mixed modes read as BT (open question). Bench, 70 pairs of roasts of one coffee: lever values agree 98.2 % of the seconds (old jumps only), the rest Artisan's moves 2 s behind the recorded time. Desktop: canvas passes the live DROP (`## TILAU ##`, validated by Tilau). Tablet: the ramp-step bookkeeping (`_ramp_settings`, `follow.live(skip=)`) removed. |
| L6 | validated 2026-11-10, build 57 | Tilau 2026-11-10: the slope as the RoR, 20 s for Standard, 15 s / 30 s for Responsive / Smooth. `tilaucore/ror.py` (own): at each reading, the least-squares slope of the real readings of the last `window_s` seconds; a missed reading is left out; no value under 3 readings or half a window. `RoRSettings` is `window_s` + the limits; `window_for(span, filter)` maps the three smoothing levels as Artisan's settings store them ((10,5), (15,7), (25,9)) to 15 / 20 / 30 s, anything else to 20 s. Switched: the plan (`evaldeltas`), `tilauscope.ror` (reference curve, cave, review), the tablet (followed roast, crash rule and AUTO via `rate_now`). `artisan_compat.py` keeps only the old names of `units`; the smoothing and the differences are gone (the followed roast's BT is the readings as recorded). `DERIVED` is empty. Re-measured: reference hand, 62 roasts, previous → slope 20 s (medians): peak 15.87 → 15.91, at Dry End 10.99 → 11.02, plateau 9.12 → 9.13, at FC 9.25 → 9.18, FC+1:20 5.77 → 5.74, at DROP 5.70 → 5.68. Goldens regenerated (their harness read the RoR over 6 readings, about 9 s): one generated plan value moves (`drop_ror_c` 5.77 → 5.82), learned peak RoR −0.4…+0.1; the post-roast analysis lists fewer small dips and bumps (crashes 192 → 117, flicks 180 → 111 on 51 roasts), and the 3 short stalls of the guidance replay (BT jitter on two other-brand roasts) are no longer read. **Not switched**: the desktop's live rate (`qmc.delta2`, `rateofchange2`, computed by Artisan while sampling) that the live curve, the detectors and AUTO read; Tilau 2026-11-10: it stays Artisan's (the gap is under 0.1 °C/min, a graft in the sampling loop is not worth it); to switch the day the desktop no longer samples through Artisan. The level menu shows the window (15 / 20 / 30 s). Bench: https://claude.ai/artifact/BDk77Tig2nrWFjPvGMqFgd. |
| bug hunt | fixed 2026-11-09 | Alarms: before START an If Alarm counts since ON (the ON buffer is a short rolling one: it never fired); a rate of −1 °C/min is a reading. Replay: `held()` keeps the CHARGE setup and works without a recorded CHARGE; the tablet engages with the CHARGE's own time (a CHARGE found is marked a few seconds back: the setup and the first moves were skipped). CHARGE: the steep fall judged over ≥ 1 s (a fast sampling cut it short). Tablet: Dry End still looked for when no TP comes (4 min after CHARGE); the unused ramp lookahead removed. Acaia: weights asked again 2 s after a silence even when the scale sends nothing (was up to 5 s). `guidance_replay`: a slider sent to 0 (stored 0 or 1.0) matches its alarm. **Open, needs artisanlib**: `canvas.updateReplayedBackgroundEvents` treats "short after CHARGE" as 3 samples; our auto CHARGE is known ~4 s after its place, so on the desktop the recorded moves of the first seconds after CHARGE are skipped when a replay is switched on by an auto CHARGE. |
| replay after auto CHARGE | fixed 2026-11-10 | `canvas.updateReplayedBackgroundEvents` (`## TILAU ##`): with auto CHARGE on, "just after CHARGE" lasts `CHARGE_WINDOW_S` more (our auto CHARGE is known a few seconds after its place), so the moves recorded in those seconds are played instead of skipped. |
