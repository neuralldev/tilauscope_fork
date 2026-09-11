# Offline thermal identification and shadow validation

`extract_thermal_model.py` identifies a small first-order thermal model from saved,
real preheats. It is deliberately offline: scanning and fitting never happen when START
is pressed.

The model is:

```text
dT/dt = heating_gain × (burner / 100)² − cooling_coefficient × (T − ambient)
```

The squared heater input reflects the measured non-linear Skywalker V2 heater. The tool
uses Artisan's actual channel convention (`temp2` for BT, `temp1` for ET), locates the
named continuous Burner extra-device channel and aligns it on its own time base. It
rejects simulated profiles, pre-calibration burner values, malformed samples and profiles
from a different machine or input. The cooking-learning exclusion flag is intentionally
ignored because it does not describe the independent preheat response of the machine.

## Run the offline fit

From the `src` directory:

```bash
python tilauscope/tools/extract_thermal_model.py \
  /path/to/your/alog/directory \
  --machine "ITOP Cyberroaster" \
  --channel BT
```

`--machine` may be omitted to use the most common eligible machine in the selected
channel. At most the newest 200 files are inspected by default; `--limit` changes this
offline budget. `--output` can publish the candidate elsewhere for inspection.

The tool requires at least three eligible preheats and applies two independent checks:

- fit residuals on temperature rate;
- free-running temperature error, including leave-one-profile-out validation.

It also rejects coefficients outside physical bounds or a model that implies an
implausible holding power. A failed fit exits without replacing the existing candidate.
A successful fit atomically writes `tilaupid_thermal_candidate.json` beside the `.alog`
files. It does not edit any Artisan profile.

## What happens in the application

The JSON file starts as a **candidate**, never as an active controller setting. On each
subsequent real preheat TilauPID runs the candidate in **shadow mode**:

- measured burner commands are replayed into the model;
- its free-running predicted temperature is compared with the real probe;
- the existing PID remains the sole source of heater commands;
- simulation, interrupted sessions, sampling gaps, short runs and runs without enough
  heater/temperature excitation do not count.

A qualified shadow run passes only when RMSE is at most 8 °C, absolute bias at most
4 °C and the 95th-percentile absolute error at most 12 °C. Three consecutive passes are
required before promotion. A qualified failure resets the sequence and withdraws a
previously promoted model.

After promotion, the model is used only as a bounded cold-start prior for holding power
and response lead. Direct stable-hold evidence and learned setpoint nodes retain priority,
and the normal burner ceiling, sensor safety and controller clamps still apply. Promotion
state is kept in contextual settings keyed by machine, BT/ET input and candidate
fingerprint; replacing the JSON therefore starts a fresh shadow qualification.

## Diagnosing eligibility

`tilau_exclude_learning=True` concerns cooking and does not exclude a preheat trace.
If the command reports no eligible trace, first check that recent real profiles:

- were recorded after the November 2025 burner calibration;
- contain a continuous extra-device channel named Burner (the historical `Buner` typo is
  also recognised);
- have a CHARGE marker and at least three minutes of valid preheat samples;
- are not marked simulated.

The application log reports the candidate fingerprint, shadow/active state, pass count
and the latest RMSE, bias and 95th-percentile error.
