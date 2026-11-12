# Green coffee cave and roast plan on the tablet — draft spec

Status: **decisions taken 2026-10-13** (§4, §5); phases coded and validated 2026-10-13 to 2026-10-15 (§6).
Sections 1–3 state what the desktop already does (facts, with sources); section 4
records the operator's decisions; section 5 settles the points left open; section
6 the phasing.

Goal (from [SPEC.md](SPEC.md)): a roast prepared and made on the tablet moves to the
desktop without loss, and the reverse. For the cave this means the **same files,
the same fields and the same links** as the desktop — no tablet-only format.

## 1. What the desktop holds

### 1.1 Green coffee (`tilauscope_types.py:161-225`)

`beancave.json` = `BeanCaveContainer{green_beans: [GreenBean], reference_profiles: []}`.
`GreenBean` fields, in file order (the order is the JSON key order):

| Group | Fields |
|---|---|
| Identity, origin | name, farm, country, supplier |
| Process | category, process |
| Physical | crop (year), density (g/l), last_humidity (%), water_activity (aw), altitude (m), screen_size (`''`/large/medium/small/peaberry) |
| Species | species, varieties |
| Stock | weight_left (g, one global stock), sacks (list of sack IDs) |
| Sensory | flavour_notes, sca |
| Counters | count, weight (never recomputed by any code found) |
| Blend | is_blend, bean1_ratio, bean2_name, bean2_ratio, bean3_name, bean3_ratio, blend_notes |
| Other | tips, conditioning (`''`/vacuum/grainpro/ecotact/bocal/toile), dial_ins (brew dial-ins), price_per_kg (currency from desktop settings) |
| Links | uuid (uuid4, 36 chars), reference_roast_uuid (an Artisan roastUUID) |

Sidecars in the same folder: `tastings.json` (`TastingLog`: per roastUUID, bean_uuid,
date, verdict yes/almost/no, defects, notes) and `brewlog.json` (`BrewLog`).

Predefined lists ship in `beancave_beans.json`: 46 countries, 7 process categories
with their processes, 3 species with their varieties. They are **wanted fixed**
(never editable).

Form bounds: crop 2000–2100 (wizard), density 0–800 g/l, humidity 0–15 % (1 dec.),
aw 0–1.0, altitude 0–3000 m, stock 0–100 000 g, SCA 0–100, blend ratios 0–100 %.

### 1.2 Files and writing

- Folder: desktop setting `beancaveDirectory` (falls back to the roasts folder).
- Format: `json.dumps` defaults (`ensure_ascii=True`, `", "` / `": "`, no indent),
  keys in field order; UTF-8 (with BOM on Windows). **No schema version.**
- `beancave.json` is written atomically (temp file, fsync, replace); never written
  after a failed load. On load: a missing uuid gets one, density 500.0 becomes 0.
- Missing keys take their defaults (`ignore_missing_keys`); a key the desktop does
  not know is not kept, so it **disappears on the next desktop save**.

### 1.3 Links between a roast and its coffee

- The `.alog` `beans` text carries a line `uuid: <36-char uuid>`; everything else
  in that text is translated labels (name, country, Farm, Process, Variety,
  Altitude, SCA). Only the `uuid:` line is a key.
- Tastings and the reference roast use Artisan's `roastUUID` (32 hex).
- Stock: decreased **at Roast Setup OK** (checkbox), `weight_left − green weight`,
  floored at 0; emptied stock offers to recycle its sack IDs.

### 1.4 Roast Setup and the plan

Roast Setup reads the bean (name … reference_roast_uuid), pre-fills the green weight
from the last real roast of that coffee, and asks: green weight (scale or typed),
density, moisture, bean temperature, title, target level (`AGTRON_SCALES`),
destination (filter/omni/espresso), room conditions, auto marks, plan alarms,
stock decrease.

The plan: `TilauScopeRoastPlan.generate_roast_plan(bean, agtron_target, ambient
temp, humidity, charge weight, altitude, …)` in `roast_plan_model.py` — **7 987
lines**, needs numpy (56 uses), scipy (PCHIP curve), fpdf (PDF), PyQt6
(165 translations, 5 settings reads), `artisanlib.util`, and the roasts folder.
Everything it learns (FC, phase times, drop from colour, burner per phase, descent
before DRY END, confidence, heat soak) comes from **the desktop's `.alog` files of
that coffee**; without them it falls back on the grid. Roasts flagged
`tilau_simulated` or `tilau_exclude_learning` are skipped. The plan is also
re-fitted during the roast (`replan_from_milestone`) and drives the assistant.

### 1.5 What the cave does besides storing beans

Zone editors (essentials, provenance, characteristics, sensory), sack wizard
(new / restock / new crop), sack ID pool (**in desktop settings, per machine**,
`TS-` + 4 digits, recycled at 0 g), storage tab (`storage_advisor`, room RH over
MQTT), roasts tab and viewer, tasting, labels (Niimbot/PDF), QR (`/roast`, `/bean`,
`/sack`), AI import from a URL, density by scale, aw by AquaGauge, brew advisor.

## 2. Already on the tablet

`.alog` export with the desktop keys (validated), weights and colours, room
conditions at charge, AquaGauge and B21S links (checks only), scale, C1.
Missing for the cave: any bean record, the `uuid:` line in the exported `beans`
text, a plan.

## 3. Constraints that are not open

1. Files written by the tablet are the desktop's files, byte-compatible
   (`beancave.json`, `tastings.json`, `.alog`); the tablet core imports nothing
   from the desktop and stays standard-library Python.
2. Predefined lists and form bounds are the desktop's, copied, not re-invented.
3. A roast made on the tablet links to its coffee by the `uuid:` line, and is
   flagged `tilau_simulated` while the roaster is simulated.
5. The tablet works **alone** (a tablet-only operator) as well as **beside a
   computer** running TilauScope.
4. The plan's numbers never differ between desktop and tablet for the same inputs
   and history (one engine's result, not two engines that drift).

## 4. Decisions (operator, 2026-10-13)

**D1 — How the cave travels.** First step: the operator picks a `beancave.json` on
the tablet (Android file picker) to import it, and the tablet can export it the
same way. Second step: when a computer runs TilauScope, the tablet exchanges with
it through TilauScope's web server on the local network. A tablet-only operator
needs neither.

**D2 — Who owns the stock.** A setting on the tablet:
- **This tablet** — the tablet-only operator: the tablet keeps the cave, decreases
  the stock at each roast and saves `beancave.json` itself.
- **A computer** — the tablet keeps a read-only copy and records movements (green
  weight used, aw, density, moisture measured) that the computer applies when it
  receives them.

**D3 — Where the plan is computed.** In **one Python file free of Qt**, computed
there and used by the desktop as well as by the tablet. Checked 2026-10-13:
neither numpy nor scipy exists for Chaquopy on Python 3.14 (Chaquopy's index stops
at numpy 1.26.2 for Python 3.13 and scipy 1.8.1 for Python 3.10; PyPI ships no
Android wheel of numpy 2.5.4 or scipy 1.18.1). The shared plan code is therefore
**standard-library Python**: its 56 numpy uses and the scipy PCHIP curve are
rewritten in plain Python, and the desktop is checked to give the same plan as
before on its reference cases.

**D4 — Learning history.** The plan learns from the coffee's roasts that the
device holds: the tablet's own roasts, plus the computer's when they are exchanged.

**D5 — The plan on the tablet.** Step 1: the plan is shown before the roast.
Step 1 also prepares a **reference curve in the background of the roast screen**.
Step 2: a past roast can be **replayed** as that reference. The assistant stays on
the desktop for now (too computer-oriented).

**D6 — Sacks.** No sack management on the tablet.

**D7 — Features.** Accepted as proposed:

| Feature | Phase |
|---|---|
| Browse coffees, pick one for the roast | 1 |
| Roast Setup inputs (weight, density, moisture, level, room) and stock | 1 |
| aw (AquaGauge), density (scale) on the coffee | 1 |
| `uuid:` line in the exported roast | 1 |
| Plan before the roast, reference curve | 2 |
| Tasting after the roast; roast label (B21S, 30 mm) | 2 |
| Replay a past roast as reference | 3 |
| Storage zones per coffee | 3 |
| Sacks, AI import, brew advisor, PDF | desktop only |

**D8 — Past roasts and storage.** The tablet lists the roasts it holds and opens
one read-only (curve, settings, summary). It cannot keep files forever: roasts are
managed (share, delete, keep only recent ones).

## 5. Decisions on the open points (operator, 2026-10-13)

**O1 — Coffees on a tablet-only device.** With the owner setting on *This
tablet*, the tablet creates and edits coffees: the desktop's fields, predefined
lists and bounds, **redesigned for the tablet** (mockup first). With *A computer*,
coffees stay read-only on the tablet.

**O2 — One domain library for both apps (extended 2026-10-13).** Not only the plan:
every calculation and every data file the two apps need lives **once**, in a
standalone package beside both apps (working name `src/tilaucore/`), standard
library only, no Qt, no Artisan import. The desktop imports it; the tablet build
adds it as a second source folder. There are never two implementations of the same
rule. See §7.

**O3 — Keeping roasts.**
- *Exchange with the computer's web server enabled*: a roast sent to the computer
  may be deleted; the tablet offers to remove those older than a chosen age
  (setting, default 3 months); the space used is shown.
- *Tablet only*: roasts are archived elsewhere before any removal — copied to
  Google Drive or an equivalent folder the operator chooses. To check on the
  tablet before design: whether Android's folder picker grants a lasting Google
  Drive folder (otherwise the share sheet, one export at a time).
- In both cases a roast never sent or archived is never removed without an
  explicit confirmation.

**O4 — Movements file.** Each movement carries an id so a second import changes
nothing; the desktop is adjusted to read the tablet's movements (and, more
generally, to stay compatible with the mobile client).

### Format of the tablet's own data (operator's question)

`beancave.json` stays JSON: it is the desktop's file, the exchange needs it
byte-compatible, and its size is small (about 1–2 KB a coffee, so a few hundred
coffees fit under 1 MB, rewritten atomically in milliseconds). What the tablet
adds of its own is better kept beside it rather than inside it:
- movements and roast session: append-only JSON lines (already used for the roast
  journal) — a line written per event survives a crash;
- the list of past roasts (D8): rebuilt from the `.alog` files themselves, as the
  desktop's roast index does; if that list grows to many hundred roasts, an
  SQLite index (in Python's standard library, available on Android) becomes worth
  it, as a cache only — never as the record.

## 6. Phasing

1. **Cave on the tablet**: import/export `beancave.json` (file picker); owner
   setting (D2) — *done and validated 2026-10-13*; create and edit coffees in tablet-only mode (O1) — *done and validated 2026-10-14*; pick a coffee
   at Ready, with the `uuid:` line in the exported `.alog` — *done and validated 2026-10-13*; Roast Setup inputs; stock (tablet owner) — *done and validated 2026-10-14*
   or movements (computer owner); aw and density on the coffee; past roasts list, import and sending
   (D8, O3; no archive, nothing deleted — §8.5) — *done and validated 2026-10-14*; the cave travels as one set
   with `tastings.json` and `brewlog.json` (BeanCave folder in, share sheet out; all files checked before an
   import), tastings shown read only — *done and validated 2026-10-14*.
2. **Plan**: shared standard-library plan file (D3, O2), desktop switched to it and
   checked against its reference plans — *done and validated 2026-10-14 (§8.6)*; plan before the roast
   (Plan tab of Roast Setup, desktop roadmap and notes, planned curve over the band of past roasts; Artisan's
   RoR settings from the machine's .aset since step A, 2026-10-15; the ★ reference-roast line, the desktop's sentences from
   `tilaucore.roast_plan_view.reference_line`, validated 2026-10-15) — *done and validated 2026-10-14*;
   reference curve on the roast screen (the plan's BT and RoR dashed from Charge, its
   milestones, its burner/air/drum steps dashed in the lanes; anchored at Charge — re-anchoring at
   dry end and first crack as the desktop's replan comes with the assistant, decision 2026-10-14) —
   *done and validated 2026-10-14*; tasting (the desktop's form from the Roasts tab, both owners, reference
   star, never an invitation — decisions 2026-10-14) — *done and validated 2026-10-14*; roast label (the desktop's
   30 mm label: its texts from `tilaucore.roast_label`, drawn on a canvas with Pillow's measures from
   `tools/gen_label_metrics.py` since Chaquopy has no Pillow for Python 3.14; printer icon beside Roast complete
   and in the Roasts tab, grey until the printer is found, no sheet — decisions 2026-10-14) —
   *done and validated 2026-10-14*.
3. **Replay** a past roast as reference; storage zones; exchange with the
   computer's web server (D1 step 2).

Each phase: mockup approved before UI code; desktop round-trip test (file written
on the tablet, read by the desktop) before validation.

## 7. The shared domain library

### What goes in

| Today on the desktop | Qt / Artisan ties | In the shared library |
|---|---|---|
| `beancave_beans.json` (countries, processes, species, varieties) | none (file) | the file itself |
| `roasters.json` (machines, contexts, offsets, limits) | none (file) | the file itself |
| `GreenBean`, `BeanCaveContainer`, tastings, brew log formats (`tilauscope_types.py`) | module imports PyQt6; mashumaro | plain dataclasses with an explicit reader/writer giving the same JSON (field order, `json.dumps` defaults) |
| `AGTRON_SCALES`, `RoasterBasicPlan`, `ProbeDeviation` (`tilauscope_types.py`) | module imports PyQt6 | as they are |
| `storage_advisor.py` (aw zones, trend, EMC) | none | as it is |
| `bean_energy.py` (Maillard floor, bean family, humidity / aw bounds) | none | as it is |
| `bean_qualifiers.py` (dense, moist, typical…) | `QApplication.translate`, theme colours | words as English source text, a level instead of a colour |
| `roasters.py` (roaster context) | small `tilauscope_types` import | as it is |
| `tasting_log.py`, `brew_log.py` | `tilauscope_types` import | as they are |
| `roast_memory.py`, `roast_plan_snapshot.py` | `tilauscope_types`, coach, brew advisor | the computing part |
| `.alog` reading for history (head/tail parse of `alogmanager.py`) | QtCore, `artisanlib.util` | the parsing part |
| `roast_plan_model.py` (plan, replan, learning) | numpy, scipy, Qt, fpdf, `artisanlib.util` | the computing part, numpy and scipy rewritten in plain Python; PDF and alarms stay on the desktop |

### Rules

- **No Qt, no Artisan, standard library only** in the shared library; checked by a
  test that parses its imports (as the tablet's isolation test does today).
- **Text**: the shared library returns English source text marked with a local
  no-op `QT_TRANSLATE_NOOP(context, text)`, so the desktop's translation tools
  still find every literal; the desktop translates at display, the tablet shows
  English.
- **Desktop modules become thin**: what stays in `src/tilauscope` is display,
  Qt, PDF and Artisan wiring; their calculations call the shared library.
- **Same results**: before a desktop module switches, its existing tests and the
  plan's reference cases run unchanged against the shared code.
- **Artisan's own rules** (the `computed` section of an `.alog`, `artisanlib`)
  cannot move — Artisan is upstream code. The tablet keeps its port (`alog.py`),
  guarded by the test that reads the desktop sources.

### What the tablet already copied (to move into the library)

| Tablet copy | Source |
|---|---|
| `colour.py` `LEVELS` | `AGTRON_SCALES` — moved 2026-10-13, copy removed |
| storage zones in `water-check.js` | `storage_advisor.DEFAULT_THRESHOLDS` — moved 2026-10-13, copy removed |
| roaster entries of `catalogue.py` | to compare with `roasters.json` |

### Order

1. Phase 1 needs (storage advisor, the two JSON files, the `GreenBean` reader/writer, bean energy, roast colour and qualifiers — lot 1 complete, validated 2026-10-13): `GreenBean` reader/writer, qualifiers,
   storage zones, `AGTRON_SCALES`, bean family — moved first, desktop switched,
   tablet copies removed.
2. Phase 2: roaster context, roast memory, `.alog` history reading, the plan.

## 8. Roasts on the tablet, and the list the plan learns from (bench, 2026-10-14)

### 8.1 What the desktop does (read in the code)

- **One index of the roast folder** (`alogmanager.py`, `AlogIndex`): each `.alog`
  is read partially (head and tail windows, never a whole `literal_eval`) into an
  `AlogMetadata`: file, date, roastUUID, title, bean `uuid:` line, mode, roaster,
  green and roasted weights in grams, whole and ground colours, the whole
  `computed` block, ambient readings, burner held per phase (`heater_dry` …
  `heater_de`), `exclude_learning`, `simulated`, the plan's reference roast. The
  index is saved beside the folder and refreshed in the background.
- **Its readers**: the roast plan (37 reads: learning, reference roast, burner per
  phase, charge temperature; simulated and excluded roasts skipped), BeanCave's
  Roasts tab and viewer, the bean sheet's **Roast memory** (`roast_memory.py`:
  last roast, count, development, loss, colour and its basis, tasting from
  `tastings.json`, the "Next time" change, reference state).
- Dependencies: Qt only for the background refresh and paths; four Artisan helpers
  (`weight_units`/`convertWeight`, `decodeLocalStrict`,
  `events_internal_to_external_value`); mashumaro for the index file.
  `roast_memory` needs `tasting_log` (already on `tilaucore.beans`) and
  `roast_coach.measured_level` (pure function in a Qt module).

### 8.2 What the tablet needs (phase 1)

1. **Its own roasts** (`files/roasts`, written by Save roast) and **the
   computer's** (D4) in one index, with the desktop's fields, so the plan of
   phase 2 reads the same records on both.
2. **Roast memory** in the bean sheet as on the desktop, and **All N roasts** →
   the coffee's roasts; a **Roasts** list for all coffees; a roast opened
   read-only (curve, settings lanes, summary) — D8.
3. **Keeping roasts** (O3): share, delete, archive; space used; never delete a
   roast not sent or archived without confirmation.

### 8.3 Shared library (lot 2 begins)

| Module | Bench |
|---|---|
| 7 · *done and validated 2026-10-14* · `tilaucore/alog_index.py` — partial reader, `AlogMetadata`, burner per phase, folder scan, index file (`beans`-style JSON instead of mashumaro, as module 3) | desktop `alogmanager` keeps its Qt refresh and re-exports the rest; same records as before on the operator's roast folder |
| 9 · *done and validated 2026-10-14* · `tilaucore/roast_summary.py` — facts and tiles of one roast | desktop translates; whole bean names its level (decision 5) |
| 8 · *done and validated 2026-10-14* · `tilaucore/roast_memory.py` + `roast_levels.py` + `tasting_log.py` | desktop keeps its words; same memory for every coffee before/after |

### 8.6 Plan bench (phase 2)

The plan engine moves to tilaucore one step at a time; the gate of every step is
the golden corpus (`src/test/golden/corpus.json`) unchanged. numpy and SciPy are
replaced by the standard library (no wheel for Chaquopy 3.14), proved identical on
the operator's roasts before the switch. The desktop keeps settings, translation,
the plan PDF and the alarm factory.

| Step | Bench |
|---|---|
| P1 · *done and validated 2026-10-14* · `tilaucore/roast_analysis.py` — RoR bands, sampling interval, turning point, crashes and flicks (moving average and peak search rewritten after SciPy's steps), timeindex sentinels, probe offsets, weight-loss target | `tilauscope_types` re-exports; snapshot of 139 roasts (1 039 events) byte-identical; 483 desktop tests incl. golden |
| P2 · *done and validated 2026-10-14* · `tilaucore/roasters.py` — the machines of `roasters.json`, legacy names, `RoasterContext`, `RoasterManager`; read with the `tilaucore.beans` reader (enums and optional fields added) | desktop `roasters.py` keeps the Artisan sync and re-exports; 16 machines and their contexts byte-identical; 614 desktop tests |
| P3 · *done and validated 2026-10-14* · `tilaucore/roast_plan_snapshot.py` — pre-roast prediction snapshot and its errors | moved unchanged but for the `to_agtron` import; desktop re-exports; 493 desktop tests |
| P4 · *done and validated 2026-10-14* · `tilaucore/numeric.py` — NumPy order of sums, median, clip, rounding (signed zero), arange, interp (fused multiply-add, as NumPy on the Mac), column stats, line fit, SciPy PCHIP; the plan engine no longer calls NumPy/SciPy for its maths | 99 full plans of the operator's coffees byte-identical at full precision; fuzz bit-exact except the moving average (BLAS order, last bit); 99 plans 32.5 s → 33.2 s; 580 desktop tests; plan PDF curve and band checked |
| P5a · *done and validated 2026-10-14* · `artisan_compat` — Artisan's standard RoR method only (decision 2026-10-14: TilauScope uses one method set; optimal smoothing, polyfit and Savitzky-Golay not ported), gap filling, median filter, °C/°F conversions; `RoRSettings`; `numeric.interp` follows NumPy's guessed search (a roast whose time runs back) | 30 144 roast × settings combinations identical to Artisan; 99 plans byte-identical; Barazilie Light 244 g identical to pre-phase-2 code; `test_artisan_compat`, `test_numeric` |
| P5b · *done and validated 2026-10-14* · `tilaucore/roast_plan.py` — `RoastPlanEngine` (history, plan, replan) with explicit inputs (machine, roasts and BeanCave folders, unit, destination, `RoRSettings`) and overridable reads; 49 texts as `QT_TRANSLATE_NOOP`, `translate` set by the desktop | desktop `TilauScopeRoastPlan(parent, roaster_ctx)` subclass reads qmc, settings, `AlogIndex`, BeanCave live; keeps alarms and PDF; 99 plans byte-identical on the desktop AND with NumPy, SciPy, Qt, Artisan blocked; 953 desktop tests; 0 translation contexts changed |

### 8.4 To decide

1. **The computer's roasts on the tablet in phase 1**: imported as files (Android
   picker, several `.alog` at once, kept in their own folder, marked "from the
   computer", never counted as tablet roasts nor exported again) until the web
   exchange (D1 step 2)?
2. **The four Artisan helpers** in `tilaucore`: Artisan's `artisanlib` cannot be
   imported there, so `tilaucore` holds its own versions, checked by a test
   against `artisanlib.util` on the same inputs (one rule, guarded): agreed?
3. **Roasts that do not count**: simulated tablet roasts appear in the lists but
   never in the plan's learning (as on the desktop); the two test roasts already on
   the tablet are simulated.
4. **Retention (O3), tablet only**: archive folder chosen with Android's folder
   picker (to try on the tablet whether a Google Drive folder is kept), then
   "remove roasts older than N months that are archived" (default 3) — or the
   share sheet one roast at a time if the folder grant does not last.

### 8.5 Decisions (operator, 2026-10-14)

1. The computer's `.alog` are imported as files into their own folder, marked
   "from the computer", until the web exchange.
2. `tilaucore` holds its own versions of the four Artisan helpers, checked against
   `artisanlib.util` by a test.
3. Simulated roasts show in the lists and are **never** used by a plan.
4. Nothing is deleted by the app: the operator only chooses an archive folder
   (whether the picker reaches Google Drive is tried on the tablet).
5. (2026-10-14) A whole-bean colour names the roast level when no ground colour
   was measured, on the desktop too (its colour tile left the name out: a mistake,
   aligned on the tablet).
6. (2026-10-14) Roasts imported from the computer feed the tablet's plan, with the
   desktop's rules: simulated and excluded roasts never.
7. (2026-10-14) Roasts mockup SN2Nop4JKeUmwm9iDDnzKo v3: the Roasts tab as the
   desktop's (two-line rows, day or coffee headings, Most recent / Oldest first /
   Coffee A–Z with a marker, the selected roast beside it), the desktop's summary
   tiles shared by both apps, import and sending only in Settings, no archive.
