# TilauScope vs Artisan

TilauScope is a guided layer built on top of [Artisan Roaster
Scope](https://github.com/artisan-roaster-scope/artisan), for home and amateur roasters. This
page exists to answer one question in the time it takes to read it: **what does TilauScope
actually add?**

## Why this exists

Artisan is a professional-grade scope. It records and plots everything, exposes every setting it
has, and leaves every decision to the person operating it. That is exactly right for a
professional — and it is a lot to carry for someone roasting 250 g at a time on a Saturday
morning, working out from a handful of previous batches what to do differently this time.

**TilauScope does not change Artisan.** Its core — the curve, the recording, the devices, the
alarms — is untouched underneath. What TilauScope adds sits *on top*: an opinionated layer that
has a view on what should happen next, and says so while the drum is turning. Every chapter in
this documentation follows the same shape, because it is the shape of the whole fork:

> **Artisan does** this already. **TilauScope adds** this on top of it.

## What "guided" means here

The layer runs at two levels — **Guided**, where the assistant takes over the roasting screen and
narrates the roast, and **Expert**, where Artisan's full control panel stays in view and the
extra layer steps back. Nothing about Artisan's own behaviour changes between the two; what
changes is how much TilauScope says.

Three ideas run through everything that follows, and recognising them will make every later
chapter easier to place:

- **A plan, not just a curve.** Before charging, TilauScope computes a roast plan from the
  coffee, the batch size and the machine — targets, phase durations, a staged heat profile — and
  tracks the real roast against it rather than leaving that comparison to memory.
- **Learning from your own history, not a generic reference.** First crack temperature, phase
  timing, heat profile: each is re-derived from your previous roasts of *this coffee*, at a
  *comparable batch size*, and each value states plainly whether it is speaking from your
  experience or from a reference table.
- **A coffee has an identity.** BeanCave gives every green coffee a record that every roast of it
  points back to. That identity is what makes stock tracking, roast history and the learning above
  possible at all — without it, two roasts of the same bag are two unrelated files.

## Everything TilauScope adds

| Area | What it adds | Covered in |
|---|---|---|
| **Getting started** | A five-step first-run wizard, two operator levels, a single menu for the whole fork, self-updating. | [Getting started](getting-started.md) |
| **The roasting window** | Two forms of machine control, colour-graded readouts, phase targets adjustable on the graph, a live column of alarms and Artisan messages. | [The TilauScope window](the-window.md) |
| **Green coffee** | A database per coffee: stock, provenance, AI-assisted entry from a supplier page, a readable catalogue. | [BeanCave](beancave.md) |
| **Configuration** | One dialog for the machine profile, sensors, milestone detection tuning, and outside services. | [Configuration](configuration.md) |
| **Preparing a roast** | A preparation sheet that already knows the coffee, reads the scale, judges the batch before it starts, and preheats on its own. | [Preparing a roast](preparing-a-roast.md) |
| **The roast plan** | Targets and a heat profile computed for this coffee and this batch, with every value stating where it came from and what it has learned. | [The roast plan](the-roast-plan.md) |
| **The guided roast** | Live recommendations, an advance/delay reading against the plan, milestone suggestions, a DROP countdown, crash and flick alerts, an end-of-roast summary. | [The guided roast](the-guided-roast.md) |
| **Sacks, stock and conservation** | A guided way to bring in a new bag, physical labels tracked as a reusable pool, and a water-activity dashboard flagging bags that need attention. | [Sacks, stock and conservation](sacks-and-storage.md) |
| **Labels and QR** | Printed labels for coffee, roasts and sacks; scanning one opens its record from a webcam or a phone. | [Labels and QR](labels-and-qr.md) |
| **After the roast** | Finishing a record later, reading a roast back against your own history, comparing several roasts, and correcting the timeline after the fact. | [After the roast](after-the-roast.md) |
| **Hardware and peripherals** | Roaster link, airflow extractor, colour sensor, ambient probe, scale, label printer, water probe — each with what it adds and its limits. | [Hardware and peripherals](hardware.md) |
| **Piloting from a phone** | Pairing a phone and driving a roast from it, with a deadman safeguard if the connection drops. | [Piloting from a phone](phone-piloting.md) |
| **Brew** | Knowing when a roast is ready to brew, a recipe calculated from it, dialling in by taste, and a printed recipe card. | [Filter coffee and espresso (Brew)](brew.md) |

Chapters marked *Coming next* exist and are used in real roasting, but are not yet written up
here — this documentation is published incrementally, chapter by chapter, rather than held back
until everything is covered. What is published is complete and current for what it covers.

## What TilauScope does not change

Nothing in this documentation describes a change to Artisan's own recording, curve drawing, or
device handling — those remain exactly Artisan's. TilauScope does not take over any control you
have not explicitly handed it: at every level, on every machine, **recommendations are yours to
act on**. Nothing here moves a lever on your behalf.

## Where to start

- Never used TilauScope: [Getting started](getting-started.md).
- Already have coffee to roast: [BeanCave](beancave.md).
- Ready to prepare a batch: [Preparing a roast](preparing-a-roast.md).
- Unfamiliar term along the way: [Glossary](glossary.md).
