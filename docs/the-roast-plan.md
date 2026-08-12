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
The **batch weight** and **roast level** come back as you last left them, since a bag is usually
worked through at one batch size and one roast level over several sessions. The ambient fields
do not: they describe the room as it is now, and are filled from the online weather or the
ambient probe. Two actions close it out:

- **⚡ Generate Roast Plan** — becomes available only once every required field is filled, and
  produces **a PDF**. That document is the plan: everything described below is in it.
- **Inject in Artisan** — writes the plan's phases and alarms into Artisan, so the roast is
  set up before it starts. TilauScope confirms with *The base of the roasting plan, phases and
  alarms have been injected into Artisan. Get ready to roast!*

!!! note
    All three control ramps are armed, not just the burner: the heat ladder through Maillard,
    the airflow opening that follows the browning, and the development ramp where the fire eases
    while the air supports the reaction. Each step fires on its own bean-temperature threshold.
    The rows posted at dry end and at first crack are the value the ramp **holds** as the
    milestone is crossed — the same figures as the phase-entry table — so a milestone never
    jumps a lever to where the ramp is only due to arrive later.

The same engine also feeds the *Predicted targets* and *STRATEGY* blocks on the ROAST SETUP
sheet, which is why those predictions and this PDF agree with each other.

The plan prints in the language TilauScope is set to, whichever alphabet that language uses:
Greek, Cyrillic, Chinese, Japanese, Korean, and Arabic, Persian or Hebrew read right to left.
Coffee and farm names print in their own script too. Thai is the one exception — it has no
letterforms available and prints blank.

<!-- CAPTURE 6.1 — the BeanCave "Roasting plan" tab, form completed, with the ⚡ Generate Roast
Plan button enabled. CAPTURE 6.2 — the injection confirmation message. CAPTURE 6.3 and 6.4 —
one or two pages of a generated PDF, on a coffee with enough history to show "learned" sources.
CAPTURE 6.7 — the "Control Ramps (Heater & Airflow)" page of a generated PDF, on a coffee whose
plan carries a full heater ramp and a development ramp.
-->

---

## What the plan contains

**The coffee and the batch.** *Bean Name*, *Weight to roast*, *Roaster*, *Target Agtron
Profile*, plus the coffee's own properties — *Density*, *Bean Humidity*, *Water Activity*,
*Process Type* — and, where an ambient probe is fitted, *Ambient Temp*. A plan is specific to
a batch on a day, not to a coffee in the abstract.

Two of those properties are measured twice, and the plan uses only one of each. **Water
activity beats bean humidity**: humidity counts all the water in the coffee, including the part
that is chemically bound and never leaves during drying, while water activity counts only the
free water — the water that actually evaporates, protects the surface from scorching, and
becomes the steam that swells the bean. **Density beats altitude**: altitude only tells you a
coffee is *probably* hard, density tells you it is. When the better measurement is on the
record, the other is ignored rather than added on top; when neither is, nothing is applied and
the plan simply uses its grid.

*Ambient Humidity* is still recorded on every roast, but it no longer changes a plan. Its
influence is on the coffee **between** roasts — a humid room pulls the water activity of stored
green upward over weeks — which is where you will find it, in
[Sacks, stock and conservation](sacks-and-storage.md).

**Milestone targets.** *Charge Temp*, *End of Dry Temp*, *First Crack Temp*, *First Crack
Time*, *Drop Temp*.

**Phase durations.** *Dry Phase Time*, *Maillard Phase Time*, *Development Phase Time* and
*Total Time* — a target per phase rather than one figure for the whole roast. A valid historical
Maillard duration is not lengthened merely because it is under 3:00; only a 2:00 technical
plausibility guard rejects likely bad milestone data. Style ranges remain guidance.

The Skywalker V2's post-turning-point [rate of rise](glossary.md#ror--rate-of-rise) is centred
near 16°C/min in the available history. The plan treats this as a typical reference, not a
physical maximum. Values above 16 are common, and the initial placeholder turning point is not
used to declare a plan impossible.

*Estimated TP* is the turning point the plan draws on its own curve — one figure, not two. It is
placed from the batch size rather than from the charge temperature alone, because that is what
the machine actually does: load half a drum and the temperature dives far less far. Expect a
small batch to turn some 25°C higher than a full one charged identically, and expect the drying
rate of rise to be correspondingly gentler — there is less climb left to make.

**RoR targets.** *Target ROR Maillard*, *Target ROR at FC*, *Target ROR Dev* and *Target ROR at
Drop*: the slope to hold at each stage. The Maillard figure is an average, and an average says
nothing about where the roast lands — *Target ROR at FC* is the arrival value, worked out from
how quickly this machine's rate of rise decays, and it is the one that decides first crack.

**Development.** *Resulting DTR (%)* — development itself is planned as a duration at the
right temperature and rate of rise for the batch, and the ratio is the figure that comes out
of it, known before charging rather than discovered at the end. When it falls outside the
usual range for the roast level, the plan notes it as a sign to look at the front of the
roast, not at development.

**The curve.** *Planned BT* and *Planned RoR*, a smooth curve the real roast can be laid over.

**The heat profile.** *Heater* and *Heater ramp (anticipated)* — the reductions are **planned
before [first crack](glossary.md#fc--first-crack), not applied after it**, down to
*last step {n} s before FC*. This is the difference between a heat cut that controls first
crack and one that arrives too late and flattens the curve.

Before dry end the ladder normally does nothing: a charge temperature and an initial heat
that suit the coffee carry it through drying untouched. When they do not — when this coffee has
shown a rate of rise that flattens too early — you bring the burner down during drying to put
the curve back on a slope. **The plan learns that from your own roasts** rather than inventing
it: when it starts, how large your steps are, and the value you land on at dry end. A coffee
you have never had to correct gets no reduction scheduled at all.

After dry end the ladder follows its grid or learned settings. Coffee properties do not impose
a heater floor. Where a roaster has been measured for it, a pre-first-crack setting below its
support threshold is reported as a low-authority zone, and the band just above it as a
low-margin zone; the note names the machine and its own figures — on the Skywalker V2 (the
*ITOP Cyberroaster* profile), below about 45% and 45–50%. The plan does not raise either
setting.
These are machine observations, not electrical cut-offs or bean-chemistry laws. They do not
apply as warnings during development, where losing momentum can be intentional.

**Machine settings at phase entry.** A table of what each lever must read as a phase begins:
at charge, when bean temperature reaches dry end, and at first crack. Not an average for the
phase — an average is not a setting anyone dials, and treating one as an instruction puts the
middle of the descent at the start of the phase. Expect the burner to show the **same value at
charge and at dry end**: the drying fire is held through dry end, and the descent starts just
after it.

**The control ramps, on their own page.** The heat ladder used to be a run of
*value @ temperature* pairs — exact, unreadable while roasting. It is now a chart plus a
checklist. The chart draws the whole roast with **burner in red and airflow in blue**, the
drying, Maillard and development bands behind them, the dry-end and first-crack marks, and the
value each lever finishes on in the right margin. Each level is a step held until the next
change, because that is what the plan asks for — one move, then time to read its effect, never a
continuous slide. Below it, every gesture in order: its time, the bean temperature that triggers
it, which lever, and from what to what. Then *At a glance* — charge and drop temperatures, first
crack, total time, and the duration of each phase with its share of the roast.

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

**Geometry notes.** An unusual Maillard reference shape is reported as information to compare
with live measurements. The fallback decay exponent is a drawing aid, not proof that a flick,
a sensory defect, or an unrecoverable roast will follow.

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
source*, *Drop RoR source* and *Drop Temp Source*. They identify the shared historical profile:
`medoid (n=N)` for the representative real roast, `grid/profile blend (n=2)`, or `grid`.
With one complete roast, *History profile* says `reference only (n=1)` while the individual
targets remain on the grid.

A fourth label, `skeleton (n=N)`, appears when the only matching roasts recorded no slider
movements — driven on the PID, or with event logging switched off. Those roasts still show
where the coffee cracks and where it was finished, so first crack, the phase timings and the
drop are taken from them; the heater and airflow stay on the grid, because a roast that logged
no hand cannot describe one. It is a last resort: with two fully recorded roasts available, it
never applies.

Above these sits *History support*, in plain words. It describes the amount and consistency of
available history; it is not a probability that the plan will be accurate:

| History support | Meaning |
|---|---|
| **consistent history** | Enough of your own roasts, and their measurements agree. |
| **partial history** | Some history, not enough to support every value. |
| **grid only** | Reference values; too few matching roasts exist. |

A first roast of a new coffee is labelled grid only.

### Which previous roasts count

References are drawn only from roasts of the **same coffee** — matched on its BeanCave identity,
not on a similar-looking name — and at a **comparable batch size**. A 250 g roast is not used
as a reference for a 450 g one, because it never was one. This is what stops a plan from being
steered by a curve that had nothing to do with the batch in the drum.

<!-- CAPTURE 6.5 — the source and History support lines of a PDF, cropped, on a coffee with
"learned (n=…)" values. CAPTURE 6.6 — the historical profile vs calculated plan comparison. -->

---

## How history becomes a plan

The plan no longer combines separate medians for phase times, heater, airflow, first crack and
drop. That could describe a synthetic roast that was never performed. Instead it selects one
complete historical roast and keeps its timings, milestone settings and development trajectory
together.

- With no complete matching observation, the reference grid is used.
- With one observation, the grid remains authoritative and the roast is shown as a reference.
- With two observations, the roast closest in batch mass and target colour is blended cautiously
  with the grid.
- With three or more, the plan selects the most representative real roast: the one with the
  smallest robust overall distance to the others across phase durations, heater, airflow,
  first crack, drop and finishing rate of rise.

Whole-bean and ground-colour histories remain separate. A ground-colour cohort is preferred
once it contains two complete roasts; otherwise whole-bean history is used. The PDF's *History
profile* line states whether the source is grid, reference only, a grid/profile blend or a
representative historical roast.

### Predictive validation

When a plan is used by the guided assistant, TilauScope freezes its initial prediction before
charge and stores it with the roast profile. The record includes the plan and model identifiers,
its grid/history sources, predicted dry end, first crack and drop, the target colour, and the
heater and airflow expected at those milestones. Replanning during the roast does not rewrite
this starting prediction.

When the profile is saved, the observed milestone times and bean temperatures are added. Whole
and ground colour readings are converted to Agtron and retained separately. TilauScope can then
calculate absolute timing, temperature and colour errors using only predictions that existed
before their roasts. Entering a colour later and saving the profile again updates the observation
without changing the original prediction.

These records do not yet produce a `low`, `medium` or `high` confidence label. Such a label will
only be introduced when enough pre-roast predictions exist to validate meaningful error bands;
the current *History support* label continues to describe available history, not forecast
accuracy.

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
