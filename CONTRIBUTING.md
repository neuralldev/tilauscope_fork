# Contributing to TilauScope

Thank you for considering it. TilauScope is a guided roasting assistant for home
roasters, free software under the GNU AGPL v3 or later, and it is meant to grow
beyond one roaster and one machine. Roasters, developers and translators are all
welcome.

TilauScope is a modified version of Artisan Roaster Scope, but it is not Artisan:
please report TilauScope issues here, never on the Artisan tracker.

## Ways to help

- **Roast with it and tell us.** An [issue](https://github.com/neuralldev/tilauscope_fork/issues)
  with the roast file (`*.alog`) and your settings file (`*.aset`) is the most useful
  report there is. Roasts from machines other than the Skywalker are especially
  welcome: detection thresholds are declared per machine and need real roasts to
  be set.
- **Discuss an idea** in [discussions](https://github.com/neuralldev/tilauscope_fork/discussions)
  before writing code for it: the roasting rule behind a feature is agreed first.
- **Translate.** The interface is written in English and translated into many
  languages; see [wiki/HowToImproveTranslations.md](wiki/HowToImproveTranslations.md).
- **Write code**, on one of the three parts below.

## The three parts

| Part | Where | What it is |
|---|---|---|
| Desktop layer | `src/tilauscope/` | The assistant, the plan, BeanCave, the windows (Python, PyQt6), running inside Artisan |
| Shared roasting library | `src/tilaucore/` | Milestone detection, rate of rise, alarms, roast replay, the plan's rules: standard library only, shared by the desktop and Android |
| Android application | `android/` | An autonomous tablet edition (Kotlin and Python through Chaquopy); start with [android/README.md](android/README.md) |

Artisan's own code lives in `src/artisanlib/`. It is left as Artisan writes it, so
that its updates can still be merged: a change there is kept to a few lines, each
marked with a `## TILAU ##` comment.

## Working on the code

- Python 3.14. Desktop tests: `make test-fast` (or `make test-all`); tests of the code the
  Android and iPad apps share, without mobile tooling:
  `PYTHONPATH=mobile/python:src python3 -m unittest discover -s mobile/tests`.
- Lint with `ruff`, as configured in `src/pyproject.toml`.
- A roasting value or rule (a threshold, a duration, how a lever moves) comes from
  roasting practice and is checked on recorded roasts; say where it comes from in
  the pull request. A rule specific to one machine goes in
  `src/tilaucore/data/roasters.json`, never in the code.
- Interface text is English and goes through
  `QApplication.translate("context", "literal")`.
- A pull request says what changes for the roaster, and comes with tests of the
  cases it fixes or adds.

AI-assisted contributions are welcome, as part of TilauScope itself is built with an AI
coding assistant: you remain responsible for what you submit, and it is reviewed
like any other change.

## Licence of contributions

By opening a pull request, you agree that your contribution is distributed under
the GNU Affero General Public License v3 or later, like the rest of TilauScope
(see [LICENSE](LICENSE) and [NOTICE](NOTICE)).

The tablet apps (`android/`, `ios/`, `mobile/` and `src/tilaucore/`) are also published
through application stores, under an additional permission of the licence's section 7
(see `android/NOTICE` and `ios/NOTICE`). A contribution to that code is covered by the
same permission, and you grant Tilau, the maintainer, a perpetual, worldwide,
royalty-free, non-exclusive licence to distribute it under the GNU AGPL v3 or later
together with additional permissions of that section. You keep the copyright of your
contribution.

Sign off each commit (`git commit -s`): the `Signed-off-by:` line certifies, as the
[Developer Certificate of Origin](https://developercertificate.org/) says, that you wrote
the change or have the right to submit it under these terms.
