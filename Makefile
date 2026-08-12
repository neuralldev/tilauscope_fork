# TilauScope — developer checks
#
# Everything runs locally: the private repo's GitHub Actions are billed and the
# build workflows are inert there, so CI is not a safety net for this project.
#
#   make test      fast suite (< 10 s target) — run this constantly
#   make check     lint of the test perimeter + fatal-rule lint of the app + fast suite
#   make portico   headless import of every tilauscope module (subprocess-isolated)
#   make test-all  everything, including the portico
#   make tripwires house rules + frozen contracts only — after a rename or a new dep
#   make codecs    printer / probe / Airwave protocols, no hardware needed
#   make lint-app  ruff over tilauscope/ — pre-existing debt, informational
#   make golden    rewrite the frozen corpus snapshot, then review the diff
#   make sanitize-fixtures   strip local paths from the committed roasts
#
# The suite installs a hermetic Qt settings sandbox (src/test/_guard.py); it can
# never write to the real Artisan preferences.

PY      ?= python3
SRC     := src
PYTEST  := $(PY) -m pytest
RUFF    := $(PY) -m ruff
MYPY    := $(PY) -m mypy

.PHONY: test check portico test-all tripwires codecs lint lint-app lint-fatal types clean-test help

help:
	@grep -E '^#   make' Makefile | sed 's/^#   //'

test:
	cd $(SRC) && $(PYTEST) -m "not slow"

portico:
	cd $(SRC) && $(PYTEST) -m slow -k "not golden"

golden-test:
	cd $(SRC) && $(PYTEST) test/test_golden_corpus.py

# The rules that fail silently in production: untranslatable strings, raw
# dialogs, Qt touched off-thread, the frozen remote-control protocol, and the
# packaging manifests. Part of `make test` already — this target is for running
# them alone after a rename, a new dependency, or a protocol change.
tripwires:
	cd $(SRC) && $(PYTEST) test/test_doctrine.py test/test_contracts.py \
	                       test/test_packaging.py

# Wire formats and exchange order for the Niimbot printer, the ESP32 ambient
# probe and the DiFluid Airwave — no device in the room. The difluid/tilauambient
# checks run in a child process (they import artisanlib.main); `python
# test/codecs_child.py` runs them alone with a readable summary.
codecs:
	cd $(SRC) && $(PYTEST) test/test_hardware_codecs.py test/test_codecs_isolated.py

# Rewrites the frozen snapshot. Read `git diff -- src/test/golden/` afterwards:
# accepting a diff you have not read is how a characterisation corpus dies.
golden:
	cd $(SRC) && PYTHONPATH=.:test $(PY) test/regen_golden.py

# Strips local filesystem paths from the committed roast fixtures — they ship
# in the public fork. `make test` fails if a fixture still carries one.
sanitize-fixtures:
	cd $(SRC) && $(PY) test/sanitize_fixtures.py

sanitize-fixtures-check:
	cd $(SRC) && $(PY) test/sanitize_fixtures.py --dry-run

test-all:
	cd $(SRC) && $(PYTEST)

# Gate on the test perimeter only. `ruff check tilauscope` currently reports
# ~900 pre-existing findings; wiring that into the gate would mean a permanently
# red `make check`, which trains us to ignore it. Use `make lint-app` to look at
# the application debt deliberately.
lint:
	cd $(SRC) && $(RUFF) check test

lint-app:
	cd $(SRC) && $(RUFF) check tilauscope

# The style debt above is informational, but a handful of ruff rules do not
# report style at all — they report code that cannot run: a name that is not
# defined (F821), a definition shadowed before use (F811), an __all__ entry that
# does not exist (F822), a local read before assignment (F823). These are zero
# over tilauscope/ and must stay zero, so they gate. (A syntax error needs no
# rule: ruff reports it natively and fails the run.)
# Added 2026-08-06 after a NameError shipped to the plan generator: the orphan
# name sat in the unevaluated branch of a conditional, so no test reached it and
# only a linter could have seen it.
lint-fatal:
	cd $(SRC) && $(RUFF) check --select F821,F811,F822,F823 tilauscope

# Dead locals (F841). Deliberately out of `check`: a variable that is never
# read cannot crash anything, and 28 of these are pre-existing. It earns its
# place because of
# what it finds: during the stylesheet migration a 23-line QSS constant
# (_SS_PRIMARY, beancave.py) turned out to have no caller at all, having drifted
# out of use unnoticed while still reading as authoritative. F841 had been able
# to see it the whole time; nothing was asking. Run it after any pass that
# deletes or rewires styling.
lint-dead:
	cd $(SRC) && $(RUFF) check --select F841 tilauscope

# Currently blocked, and NOT by the test suite: [tool.mypy] files lists both
# "*.py" and "artisanlib/*.py", so mypy reports artisanlib/__init__.py "found
# twice under different module names" and stops before checking anything. This
# pre-dates the test suite — any mypy invocation in this repo hits it. Left
# out of `make check` until the inherited config is untangled.
types:
	cd $(SRC) && $(MYPY) tilauscope/roast_plan_model.py test

check: lint lint-fatal test

clean-test:
	rm -rf $(SRC)/.pytest_cache $(SRC)/.htmlcov
	rm -rf $${TMPDIR:-/tmp}/tilau-test-settings-*
	rm -rf $${HOME}/.qttest
