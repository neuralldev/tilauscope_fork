<img align="right" src="src/tilauscope.png" width="90">

TilauScope
==========
A guided roasting assistant for home and amateur coffee roasters.

[![Latest release](https://img.shields.io/github/v/release/neuralldev/tilauscope_fork?label=release)](https://github.com/neuralldev/tilauscope_fork/releases/latest)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

> **TilauScope is a modified version of [Artisan Roaster Scope](https://github.com/artisan-roaster-scope/artisan).**
> It is not affiliated with, nor endorsed by, the Artisan project. Modifications by
> Tilau began in 2025 and are ongoing. Please report TilauScope issues here, never
> on the Artisan tracker. See [NOTICE](NOTICE) for full attribution and licensing.

---

## What it is

Artisan is a professional-grade scope: it records and plots everything, and leaves
every decision to you. That is exactly right for a professional, and overwhelming
for someone roasting 250 g batches at home on a Saturday morning.

TilauScope keeps Artisan's core untouched and adds an opinionated layer on top of
it — one that has an opinion about *what you should do next*, and says so while
the drum is turning.

## What it adds

**A guided roast assistant.** Before charging, it builds a roast plan from the
bean, the batch size and your machine. During the roast it tells you which lever
to move and when — staged heat reductions announced before they happen, a live
read on whether you are ahead of or behind plan, a DROP countdown that accounts
for the curve flattening out, and a projected final DTR.

**A plan that learns from you.** First-crack temperature, phase durations and heat
profiles are re-derived from your own previous roasts of the *same* bean at a
*comparable* batch size — not from a generic reference curve.

**BeanCave**, a green-bean database with stock tracking, storage advice based on
water activity, sack management, QR-coded labels, and a roast viewer. Scan a label
with your phone and the record opens in the browser.

**Remote piloting.** A phone-shaped web interface served on your local network:
draggable controls for the four levers, contextual milestone marking, and a
non-destructive recorder. Installable as a PWA.

**Hardware integration** beyond Artisan's: Skywalker V2, DiFluid AirWave and
Omniflux, Acaia scales, Niimbot label printers, and a custom ESP32 ambient probe.

**Preheat PID** with cross-roast memory, so the machine is at the right
temperature when you are ready to charge.

## Screenshots

| | |
|---|---|
| ![Guided roasting](wiki/tilauscope/general%20roasting.png) | ![Bean management](wiki/tilauscope/bean%20cave%20green%20beans%20management.png) |
| ![First crack prediction](wiki/tilauscope/roasting%20FC%20prediction%20annotation.png) | ![Device integration](wiki/tilauscope/BLE%20devices%20support.png) |

## Install

Download the latest macOS or Windows build from the
[releases page](https://github.com/neuralldev/tilauscope_fork/releases/latest).

macOS builds are signed and, when Apple's service cooperates, notarized. If a
build could not be notarized the release notes say so and tell you how to open it.

To run from source, see [wiki/HowToRunFromSource.md](wiki/HowToRunFromSource.md).
TilauScope targets **Python 3.14** and **PyQt6**; dependencies are pinned in
[src/requirements.txt](src/requirements.txt).

## Documentation

- [What's new](wiki/whatsnew.md) — user-facing changes, by version
- [Release history](wiki/ReleaseHistory.md) — full changelog
- [Installation](wiki/Installation.md)
- [Improving translations](wiki/HowToImproveTranslations.md)

## Contributing

Bug reports and ideas are welcome — please open an
[issue](https://github.com/neuralldev/tilauscope_fork/issues) or a
[discussion](https://github.com/neuralldev/tilauscope_fork/discussions).

TilauScope is developed by a single person against one main roasting machine, so
reports that include a profile (`*.alog`) and a settings file (`*.aset`) are far
more actionable than reports that do not. The bug report form will ask for them.

## Licence

TilauScope is distributed under the **GNU Affero General Public License v3 or
later** ([LICENSE](LICENSE)).

Code inherited from Artisan Roaster Scope keeps its original GPL terms and
headers ([LICENSE-GPL-3.0](LICENSE-GPL-3.0)); code original to this fork, under
`src/tilauscope/`, is AGPL-3.0-or-later. GPLv3 §13 expressly permits this
combination. [NOTICE](NOTICE) explains the arrangement in full.

One practical consequence: if you run a modified TilauScope and let other people
use it remotely over a network — its remote-piloting interface, for instance —
you owe those users the source of your modified version.

## Credits

TilauScope exists because Artisan exists. All credit for the roasting engine,
the device layer and a decade of careful work goes to **Marko Luther** and the
Artisan contributors. The original project README is preserved here as
[README-Artisan.md](README-Artisan.md).
