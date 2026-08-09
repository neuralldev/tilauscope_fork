# Glossary

Terms used throughout this documentation. Definitions are given as they apply inside
TilauScope, which is not always the widest possible sense of the word.

!!! note
    This glossary grows with the documentation. Every chapter that introduces a term
    defines it here and links to it on first use.

---

## Roast phases and milestones

#### CHARGE

The moment the green coffee is dropped into the drum. It is the origin of the roast clock:
every phase duration and every milestone time is counted from it.

#### TP — turning point

The lowest bean temperature of the roast, reached shortly after charge, when the beans stop
absorbing heat faster than the machine supplies it and start climbing again. A rising
[RoR](#ror--rate-of-rise) after TP is normal recovery, not a fault.

#### Drying — DRY

The first phase, from [CHARGE](#charge) to [dry end](#de--dry-end). Free moisture leaves the
bean. Little colour develops.

#### DE — dry end

The end of the drying phase. In TilauScope it is a marked milestone, detected and proposed
for confirmation, and one of the anchors the roast plan is built around.

#### Maillard

The middle phase, from [dry end](#de--dry-end) to [first crack](#fc--first-crack). Sugars
and amino acids react and produce most of the roast's aromatic complexity. The phase where
heat reductions are staged.

These reactions **absorb** heat rather than release it, so the burner is feeding them, not
merely warming the bean. Cutting the heat here does not slow the reaction gently — it starves
it, and the bean temperature keeps climbing on the drum's own heat while the chemistry
stalls. This is why the plan holds the heat through Maillard instead of stepping it down
early, and why it is a phase to judge by the settings held rather than by the curve. See
[baked](#baked).

#### FC — first crack

The audible cracking as bean structure fails under internal pressure. It marks the start of
[development](#development) and is the single most important milestone for reproducibility —
which is why TilauScope learns its temperature from your own roasts.

#### Development

The final phase, from [first crack](#fc--first-crack) to [DROP](#drop). Determines much of
the cup's balance and body. Measured relative to the whole roast as [DTR](#dtr--development-time-ratio).

#### DROP

The moment the beans leave the drum for the cooling tray. The end of the roast.

#### Back-to-back

Roasting a second batch immediately after the first, while the machine is still hot. It
needs different handling from a cold start, which is why TilauScope has a dedicated mode for
it.

---

## Measurements

#### BT — bean temperature

The probe reading closest to the beans themselves. **Every temperature in this
documentation is a bean temperature unless stated otherwise.**

#### ET — environmental temperature

The probe reading of the air or the drum environment. On some machines — radiant ones in
particular — ET can sit *below* BT, which is normal for that machine type and not a fault.

#### RoR — rate of rise

How fast bean temperature is climbing, in degrees per minute. The slope of the curve rather
than its height. A roast is steered largely by keeping RoR inside a sensible band and
falling smoothly.

#### DTR — development time ratio

The share of total roast time spent in [development](#development), as a percentage. A
common target sits somewhere between the high teens and low twenties, depending on the
coffee and the intended cup.

#### Charge weight — green weight

The weight of green coffee going into the drum. It sets the whole scale of the roast: phase
durations, how much heat the batch can absorb, and what counts as a comparable previous roast
when TilauScope looks at your history.

#### Weight loss

The weight the batch lost during roasting, as a percentage of its
[charge weight](#charge-weight--green-weight). Mostly water early on, then organic matter as
the roast develops, so it tracks how far the roast went.

#### Moisture content

The water still held in green coffee, as a percentage of its weight. Higher moisture means a
longer drying phase and a coffee that resists heat for longer at the start.

#### Density

How much the beans weigh for a given volume. Dense beans conduct heat inward more slowly and
need sustained heat; light, low-density beans take heat faster and are easier to scorch.

#### Agtron

A numeric scale for roast colour: the lower the number, the darker the roast. TilauScope
uses it as the target you aim for, and — where a colour reader is fitted — as the
measurement you compare against.

#### SCA score

A cupping score out of 100 following the Specialty Coffee Association protocol, used as the
standard reference for a coffee's quality independent of any particular roast.

#### aw — water activity

How much of the water in green coffee is chemically available, on a 0 to 1 scale. It
predicts how well a bag will keep far better than moisture content alone.

#### Retained reading

A network sensor's last published value, kept by the message broker and handed to
TilauScope the moment it starts listening. Without it a channel stays empty until the
sensor next speaks of its own accord, which on a home automation network can take minutes.

#### TLS

The encryption a message broker can require on the link, so that readings and the password
used to obtain them do not travel in clear text. The broker proves its identity with a
certificate, which must come from a recognised authority: a certificate the broker issued
to itself is refused, and the connection simply fails.

#### Keepalive

The idle time after which a quiet connection to the broker is checked. Short values notice
a broker that has gone away sooner, at the cost of talking to it more often.

#### Polling

Asking a network sensor for a reading instead of waiting for one. Some sensors report only
on their own schedule, far too slowly to follow a roast; polling requests a fresh value at
a chosen interval. Only sensors on mains power can be polled — a battery sensor sleeps
between its own reports and cannot be reached in between.

---

## Machine behaviour

#### Thermal mass

How much heat the machine's own metal stores. A high-thermal-mass drum keeps delivering heat
after the power is reduced, so reductions must be made *earlier* to land on time.

#### Radiant heat — FIR/NIR

Heating by infrared radiation rather than by hot air. Radiant machines transfer heat to the
beans very directly, which changes both how fast they respond and how their two probes
relate to each other.

#### PID

A control loop that holds a temperature at a target by continuously adjusting power.
TilauScope uses one to bring the machine to its preheat target.

#### Shadow validation

Running a candidate model beside the active controller using the same measurements, while
giving it no authority over the heater. Its predictions can therefore be checked on the real
machine before it is allowed to contribute even a bounded fallback setting.

#### SV — setpoint value

The temperature a [PID](#pid) is aiming for.

#### Overshoot

Sailing past the target temperature because the machine's stored heat keeps arriving after the
power has been cut. The higher the [thermal mass](#thermal-mass), the more of it there is, and
the earlier the power has to come off to avoid it.

---

## Storage

#### Conditioning

How a bag of green coffee is sealed: vacuum, valve bag, sealed jar, open cloth bag, and so
on. It decides whether the coffee drifts toward the room's humidity or holds its own
[water activity](#aw--water-activity) — sealed methods hold it, an open bag drifts.

#### Equilibrium moisture content — EMC

The moisture a bean would settle at if left in the current room conditions indefinitely. A
rough guide for what an open bag is drifting toward, not a measurement of the bean itself.

---

## Brewing

#### Degassing

The release of CO₂ trapped in a bean by roasting. A coffee brewed too soon, before it has
degassed enough, pushes back against water unevenly and extracts unpredictably — which is
why a coffee needs a few days' rest before it brews at its best.

#### Extraction yield — EY

The share of the ground coffee's mass that ends up dissolved in the cup, as a percentage.
Too little tastes thin and sour; too much tastes bitter and harsh — dialling in means
steering toward the range in between by adjusting grind, ratio or time.

#### Channeling

Water carving a fast path through the coffee bed instead of passing through it evenly —
part of the bed is over-extracted, part under-extracted, at the same time. A grind change
alone does not fix it; it is a distribution or preparation problem.

---

## Faults and risks

#### Crash

An abrupt collapse of [RoR](#ror--rate-of-rise), usually just after [first crack](#fc--first-crack),
when the roast loses momentum. Left alone it leads to a [baked](#baked) cup.

#### Flick

The opposite of a crash: [RoR](#ror--rate-of-rise) turning back upward late in the roast,
usually producing harsh, ashy notes.

#### Baked

A flat, hollow, bread-like cup, caused by spending too long in a phase with too little
thermal momentum — most often a drying or [Maillard](#maillard) phase that ran long, or one
run on too little heat.

The second case is the harder one to see: because the drum keeps radiating, bean temperature
and [RoR](#ror--rate-of-rise) can both look impeccable while the reaction underneath has
already stalled. A smooth curve is not proof that the roast is being fed.

#### Flash drying

Drying driven so hard that the bean surface dries far ahead of its core, leaving the roast
unevenly developed.
