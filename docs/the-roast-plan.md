# The roast plan

!!! abstract "Artisan does / TilauScope adds"
    **Artisan does** — lets you load a previous roast as a background curve and try to follow
    it by eye. Which reference to use, and whether it was any good, is left entirely to you.

    **TilauScope adds** — a plan computed for this coffee, this batch size and this machine,
    with milestone targets, phase durations, a staged heat profile and a projected
    [DTR](glossary.md#dtr--development-time-ratio). Every value states where it came from, and
    the ones derived from your own previous roasts of the same coffee say how many roasts are
    behind them.

---

## Where the plan lives

The plan is not a screen inside TilauScope. It is produced in **BeanCave → Roasting plan**, a
short step-by-step form: pick the coffee, enter the parameters, adjust probe offsets if needed.
Two actions close it out:

- **⚡ Generate Roast Plan** — becomes available only once every required field is filled, and
  produces **a PDF**. That document is the plan: everything described below is in it.
- **Inject in Artisan** — writes the plan's phases and alarms into Artisan, so the roast is
  set up before it starts. TilauScope confirms with *The base of the roasting plan, phases and
  alarms have been injected into Artisan. Get ready to roast!*

The same engine also feeds the *Predicted targets* and *STRATEGY* blocks on the ROAST SETUP
sheet, which is why those predictions and this PDF agree with each other.

<!-- CAPTURE 6.1 — the BeanCave "Roasting plan" tab, form completed, with the ⚡ Generate Roast
Plan button enabled. CAPTURE 6.2 — the injection confirmation message. CAPTURE 6.3 and 6.4 —
one or two pages of a generated PDF, on a coffee with enough history to show "learned" sources.
-->

---

## What the plan contains

**The coffee and the batch.** *Bean Name*, *Weight to roast*, *Roaster*, *Target Agtron
Profile*, plus the coffee's own properties — *Density*, *Bean Humidity*, *Process Type* — and,
where an ambient probe is fitted, *Ambient Temp* and *Ambient Humidity*. A plan is specific to
a batch on a day, not to a coffee in the abstract.

**Milestone targets.** *Charge Temp*, *End of Dry Temp*, *First Crack Temp*, *First Crack
Time*, *Drop Temp*.

**Phase durations.** *Dry Phase Time*, *Maillard Phase Time*, *Development Phase Time* and
*Total Time* — a target per phase rather than one figure for the whole roast.

**RoR targets.** *Target ROR Maillard*, *Target ROR Dev* and *Target ROR at Drop*: the slope
to hold at each stage.

**Development.** *Target DTR* and *Calculated Final DTR* — where development should end up,
known before charging rather than discovered at the end.

**The curve.** *Planned BT* and *Planned RoR*, a smooth curve the real roast can be laid over.

**The heat profile.** *Heater* and *Heater ramp (anticipated)* — the reductions are **planned
before [first crack](glossary.md#fc--first-crack), not applied after it**, down to
*last step {n} s before FC*. This is the difference between a heat cut that controls first
crack and one that arrives too late and flattens the curve.

**Airflow.** *Airflow*, *AirWave*, *AirWave Mode*, with the reason attached — *to smooth RoR*,
*to prevent crash*, *Action: Increase extraction/airflow to shed thermal energy*.

**Drum speed.** *Drum Speed* and *Control*, computed once for this batch — see
*Preparing a roast* for why drum speed is a setup decision.

**Action notes.** Each requested gesture comes with its reason (*Action: Reduce burner 10% 45s
before*, *Action: Boost heater*). A plan you understand is a plan you can learn from; a list of
orders is not.

**Risk markers.** *CRASH* and *FLICK* points with a *Severity*, plus *RoR variance* — the plan
knows where this coffee is likely to [crash](glossary.md#crash) or
[flick](glossary.md#flick) before it happens.

!!! note
    Every temperature in the plan is a [bean temperature](glossary.md#bt--bean-temperature) and
    every duration is in minutes and seconds. The PDF states this, and it also restates the
    target [Agtron](glossary.md#agtron) profile the plan was computed for, so a printed plan
    cannot be misread later.

---

## Where each value comes from

This is the part that distinguishes the plan from a reference curve: **it never hides whether
it is speaking from your experience or from a reference table.**

Alongside the values, the plan carries *First Crack source*, *Heater source*, *Phase timing
source*, *Drop RoR source* and *Drop Temp Source*. Each reads either `learned (n=N)` — derived
from N of your own roasts — or a reference value, or a blend of the two. Above them sits
*Plan confidence*, in plain words:

| Plan confidence | Meaning |
|---|---|
| **high (consistent history)** | Enough of your own roasts, and they agree with each other. |
| **medium (partial history)** | Some history, not enough to lead on everything. |
| **low (grid)** | Reference values. This coffee is new to the machine, or too few roasts exist. |

A first roast of a new coffee is honestly labelled low confidence. That is not a defect — it is
the plan declining to pretend.

### Which previous roasts count

References are drawn only from roasts of the **same coffee** — matched on its BeanCave identity,
not on a similar-looking name — and at a **comparable batch size**. A 250 g roast is not used
as a reference for a 450 g one, because it never was one. This is what stops a plan from being
steered by a curve that had nothing to do with the batch in the drum.

<!-- CAPTURE 6.5 — the source and Plan confidence lines of a PDF, cropped, on a coffee with
"learned (n=…)" values. CAPTURE 6.6 — the historical profile vs calculated plan comparison. -->

---

## What the plan learns, and when

Learning is not a single switch: each quantity has its own threshold, and until it is met the
plan uses reference values for that quantity alone.

| What is learned | From when |
|---|---|
| **First crack temperature** | From the **3rd roast** of the same coffee. At **2 roasts**, your measured value and the reference are blended. |
| **First crack corrected for batch size** | Needs **3 roasts** with both first crack and charge weight recorded. Removes the bias that comes from comparing different batch sizes. |
| **Phase durations** | From the **2nd roast**; carries full weight from the **3rd**. |
| **Heat profile and development ramp** | From the **2nd roast**. |
| **Drop temperature, from colour feedback** | Progressively, as measured colours accumulate — the colour you record at the end of a roast corrects the next plan's drop target. |
| **RoR at drop** | From your own recorded roast endings. |

So the second roast of a coffee is already better informed than the first, and the third is
where the plan genuinely starts speaking from your machine.

!!! note "What the plan learns without showing it"
    Two things are learned but not printed: the expected [RoR](glossary.md#ror--rate-of-rise)
    peak for your machine (from the 2nd roast, and **discarded if it falls outside a sane
    range**, so one freak roast cannot poison it), and your probe offsets (from four
    measurements onward). They are mentioned here so that nothing in the plan's behaviour is
    unaccounted for.

### Guardrails

Learning is bounded. Values that fall outside professional roasting ranges are rejected rather
than adopted, and where a learned figure is implausible the plan falls back to the reference and
says so through its source labels. A single bad roast does not move the plan; a consistent habit
does.

If the request itself cannot be met — a target that no plan could reach for this coffee and this
batch — the plan says **OUT OF SCOPE** instead of drawing a curve that cannot be followed.

!!! tip
    A roast you know went wrong can be excluded from learning altogether, from the assistant at
    the end of the roast. Use it: the plan is only as good as the roasts it believes.

---

## Next

- What the assistant does with the plan while the drum turns: see [The guided roast](the-guided-roast.md).
- Entering the batch, the coffee and the preheat: see [Preparing a roast](preparing-a-roast.md).
