# Temperature unit on the tablet (°C / °F) — spec, 2026-10-24

## 1. What exists (read in the code)

- Everything is °C: the session, the journal, the plan, TilauPID, the alarm engine, the `.alog`
  written with `"mode": "C"` (`alog.py`). The screens print "°C" literally (about 30 places in
  `roast.html`, `roast-setup.html`, `settings.html`, `check.js`, `extractor-check.js`, `roasts.js`).
- **Defect, whatever the setting**: a roast recorded in °F on the desktop and imported is read as
  °C — the roast's detail in Roasts (`roasts.py`), the roast followed behind a roast (`follow.py`)
  and Roast Replay (`demo.py`) take `temp1` / `temp2` as they are. The shared modules already know
  a file's unit (`tilaucore.roast_replay`, `roast_summary`, `alog_index.mode`).
- The desktop converts a file recorded in the other unit when it loads it (Artisan
  `main.py`, `loadFile`): a tablet `.alog` in °C opens right on a desktop set to °F.
- An `.alrm` file does not say its unit (checked on `minimal.alrm`): Artisan reads its
  temperatures in its current unit.

## 2. Decisions (operator, 2026-10-24)

1. **Inside, °C everywhere**; only what is shown and typed follows the chosen unit.
2. **The `.alog` stays in °C** (`mode C`): the desktop converts it on load.
3. **Alarms**: an imported `.alrm` is read in the chosen unit, kept in °C, written back in the
   chosen unit; changing the unit does not change what the alarms already on the tablet mean.
4. **The setting**: Settings › General, **°C | °F**, default °C, changed between roasts only.

## 3. Behaviour

- A temperature shown: `°F = °C × 1.8 + 32`; a rate (RoR, °/min): `× 1.8`; a temperature
  difference shown as such: `× 1.8`. Same decimals as today.
- A temperature typed (preheat target, bean temperature, alarm threshold): read in the chosen
  unit, kept in °C.
- Texts built in Python that hold a temperature (plan notes, tasting changes, preheat chips)
  get the unit; the shared functions already take one (`tasting_change_text(…, unit)`,
  `change_text(…, mode)`).
- Imported roasts are read through their own `mode`, converted to °C when they are in °F.
- MQTT room sensors keep their own °C/°F choice (it says what the sensor sends).

## 4. Order

| Step | What |
|---|---|
| U1 | Imported roasts read through their unit (the defect), with tests on an °F file |
| U2 | Mockup of the setting and of a screen in °F, then the setting and the display |
| U3 | Alarms: import, editor and export in the chosen unit |

**U1–U3 done and validated 2026-10-24** (checked on the tablet in °F). U1: `alog.curves_c` reads a roast's curves
through its `mode` (Roasts detail, followed roast; Roast Replay already converted), red test proven.
U2: `unit` in the configuration, sent with every snapshot; `common.js` `shownT` / `shownD` /
`typedT` / `deg()`; roast screen, Roast Setup, Roasts detail (tiles and ticks), device checks and
MQTT room values; chart ticks at round values of the unit shown; plan and tasting texts worded in
it. U3: an alarm threshold is converted by what its source reads — BT/ET and a probe channel in
°C as temperatures, a RoR as a rate (× 1.8), anything else and Artisan's 500 untouched (Artisan
converts every threshold as a temperature; the round trip is exact either way); shared through a
copy in `alarms-shared`. Python 154 tests (6 new).
