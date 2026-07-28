# Thermal Model Extraction Tool

## Overview

`extract_thermal_model.py` analyzes Skywalker preheat cycles from TilauScope/Artisan `.alog` files to build a thermal response model for fast FIR roasters.

The tool processes 20-40 recent roasts and extracts:
- **Thermal mass** (°C per % burner power per minute) — responsiveness of the roaster
- **Response lag** (seconds) — delay from burner change to temperature response
- **Ramp phase metrics** — sustained heating (0 to fuzzy zone start)
- **Approach phase metrics** — overshoot braking zone effectiveness

## What It Extracts Per Preheat

### From Metadata
- Roast date/time
- Ambient temperature, humidity, pressure
- Charge mark index (`timeindex[0]`)

### Ramp Phase (0 → Fuzzy Zone Start)
The initial heating phase with burner at high power. Computed metrics:
- **Duration** (seconds)
- **Mean RoR** (°C/min) — rapid temperature rise
- **Mean burner %** — sustained power level
- **Thermal mass** — ΔT per % power per minute (key parameter for model)
- **Response lag** — delay to detect burner changes

### Fuzzy/Approach Phase (Fuzzy Zone → CHARGE)
The final ~60s before charge when the burner is cut/modulated to brake overshoot:
- **Duration** (seconds)
- **Mean RoR** (°C/min) — usually much lower, even negative (coast-down)
- **Mean burner %** — typically near zero (braking)
- **Final undershoot** (°C) — how much temp drops from peak to charge

### Burner Modulation Detection
Fuzzy zone is detected by looking backwards from CHARGE to find the last time burner was above 70%, then assuming fuzzy starts after that. Fallback: assume 30s before CHARGE if no high burner power found.

## Output

### CSV File
`thermal_model_metrics.csv` — one row per valid preheat with all metrics

Columns:
```
roast_name, ambient_temp, ambient_humidity, ambient_pressure,
ramp_duration_s, ramp_mean_ror_c_per_min, ramp_mean_burner_pct,
thermal_mass_c_per_pct_per_min, response_lag_s,
approach_duration_s, approach_mean_ror_c_per_min, approach_mean_burner_pct,
final_undershoot_c, timestamp
```

### Aggregated Statistics (printed to stderr)
- **Thermal mass** mean ± stdev
- **Response lag** mean ± stdev
- **Ramp RoR** mean ± stdev
- **Approach RoR** mean ± stdev
- **Ambient conditions** mean (temp, humidity, pressure)
- **Recommendation** — expected temperature rise for 6-minute target preheat

## Usage

```bash
cd /Users/thierrygluzman/Documents/Dev/artisan4
python3 src/tilauscope/tools/extract_thermal_model.py
```

The tool will:
1. Scan `/Users/thierrygluzman/Documents/roasters/` for `.alog` files
2. Process up to 40 most recent roasts
3. Write `thermal_model_metrics.csv` to `/private/tmp/`
4. Print aggregated statistics to stderr
5. Print CSV path and completion status

## Integration with TilauPID

The extracted thermal model can feed into `tilaupid.py`:
- **Thermal mass** calibrates the expected temperature response
- **Response lag** helps tune PID lag compensation
- **Ambient sensitivity** informs adjustments for seasonal changes

## Current Model (34 valid samples)

From the initial run across 40 roasts:

| Metric | Value | Notes |
|--------|-------|-------|
| **Thermal Mass** | 0.608 ± 0.173 °C/(%·min) | Skywalker FIR responsiveness |
| **Response Lag** | 2.3 ± 0.4 s | Limited samples; detect more burner transitions |
| **Ramp RoR** | 13.73 ± 3.84 °C/min | Full power sustained heating |
| **Approach RoR** | 5.35 ± 4.75 °C/min | Highly variable (braking strategy dependent) |
| **Ambient Avg** | 21.2°C, 52.4%, 1119 hPa | Typical lab conditions |
| **6-min Target** | +75.4°C rise | Starting from ~65°C → ~140°C |

## Future Improvements

1. **Burner transition detection**: Current lag measurement only catches cases where SV changes >20%. Finer transitions (±5%) would give more samples.

2. **Fuzzy zone boundary**: Currently hardcoded 30s lookback. Could be improved by detecting when RoR drops below a threshold (e.g., <8°C/min).

3. **Ambient sensitivity**: Analyze correlation between ambient temp and thermal mass (FIR efficiency should degrade in cold).

4. **Seasonal/roaster aging**: Track model drift across batches to detect equipment wear.

5. **Charge mass calibration**: Thermal mass may vary with charge weight. Tag by bean load.

6. **Cross-roast memory**: Feed learned thermal mass back to next roast's TilauPID for warm-start calibration.

## Technical Notes

- **Encoding**: `.alog` files are latin-1 encoded Python dictionaries
- **Parsing**: Uses `ast.literal_eval()` (safe for Artisan's format)
- **Sampling**: ~1 Hz (timex increments ~1 second)
- **BT channel**: `temp1` (Skywalker bean temperature via TC4)
- **Burner power**: `extratemp1[1]` (labeled "SV" = servo valve %)
- **Skywalker specifics**:
  - Zero coast/inertia (temp stops rising immediately when burner cuts)
  - FIR radiant heating (fast response, ~2s lag observed)
  - No acoustic signature (unlike drum roasters) — harder to detect FC

## Running Locally vs. CI

- **Local**: Run manually to refresh model when new roasts available
- **CI/Daily**: Could be scheduled via `schedule` skill to update model on cron
- **Output path**: Currently hardcoded to `/private/tmp/` (use scratchpad); CSV copied to project `/tools/`

## Debugging

If extraction fails on a specific roast:
1. Check `.alog` file is valid (can load with `ast.literal_eval()`)
2. Verify `timeindex[0]` is marked (>0)
3. Ensure `extratemp1[1]` has burner data (not all extradevices may be logged)
4. Review stderr output for specific rejection reason

Example single-file debug:
```python
from extract_thermal_model import load_alog, compute_thermal_metrics
data = load_alog('/path/to/file.alog')
print(data['preheatDuration'], data['timeindex'])
metrics = compute_thermal_metrics('/path/to/file.alog')
print(metrics)
```
