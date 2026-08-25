# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# TiLau 2026

"""Tripwires on the conventions that fail silently.

Three rules, each guarding a mistake that produces no error at the point it is
made:

* a translation call the string extractor cannot see — ships untranslated;
* a raw ``QMessageBox`` — ships with the system look in a themed application;
* the WebSocket thread touching ``qmc`` — crashes the process, somewhere else,
  later, with a native traceback and no Python frames.

Two of them are green today and stay at zero. The translation rule is not: the
existing offences are frozen as a baseline so the debt cannot grow while it
waits to be paid down.
"""

from __future__ import annotations

import ast
import collections
import shutil
import subprocess
import sys
from pathlib import Path
from string import Formatter
from typing import Final

import doctrine
import pytest

# ── baselines ────────────────────────────────────────────────────────────────
#
# Both categories of genuinely-invisible string are at zero. They were not: 203
# sites were found when this file was written, and paid off in the same batch —
# 177 hoisted contexts inlined, the rest either declared with QT_TRANSLATE_NOOP
# or rewritten so the literal sits at the call.
#
# Counts rather than line numbers, so an unrelated edit above a site does not
# churn the baseline. The trade-off is that a one-for-one swap in the same module
# nets out; at zero that does not apply.

#: A variable used as the translation *context*. Zero, and it stays there: the
#: hoisted-constant pattern (``_T = "tilauscope_beancave"``) reads as tidy
#: factoring and silently removes every call under it from the catalogue.
UNTRANSLATABLE_CONTEXT_DEBT: Final[dict[str, int]] = {}

#: A value translated in a TilauScope context with nothing declaring the literal.
#: The fix is always one of two things: put the literal at the call, or declare
#: it with ``QT_TRANSLATE_NOOP`` where it is written.
UNTRANSLATABLE_SOURCE_DEBT: Final[dict[str, int]] = {}

#: Values Artisan owns, rendered through Artisan's own contexts — probe names,
#: extra-device labels, milestones. Correct as written: the literals live in the
#: upstream catalogue. Frozen anyway, because this is also the shape a genuinely
#: new fork string would take if it were filed under the wrong context.
UPSTREAM_VALUE_SITES: Final[dict[str, int]] = {
    'beancave.py': 10,
    'displayscope.py': 2,
}

#: The one place allowed to touch ``QMessageBox`` as a dialog: it *is* the
#: styled replacement every other module is required to call.
STYLED_DIALOG_MODULE: Final[str] = 'tilauscope_types.py'


def _debt_by_module(kind: str) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    for path in doctrine.source_files():
        for site in doctrine.untranslatable_sites(path):
            if site.kind == kind:
                counts[path.name] += 1
    return dict(counts)


def _compare_to_baseline(found: dict[str, int], frozen: dict[str, int],
                         what: str) -> None:
    """Fail on any divergence, in either direction, with the reason for each."""
    problems: list[str] = []
    for module in sorted(set(found) | set(frozen)):
        now, before = found.get(module, 0), frozen.get(module, 0)
        if now > before:
            problems.append(
                f'  {module}: {before} -> {now} (+{now - before} new)')
        elif now < before:
            problems.append(
                f'  {module}: {before} -> {now} (fixed — update the baseline)')
    assert not problems, (
        f'{what} changed:\n' + '\n'.join(problems) + '\n\n'
        'A string that is not a literal at the call is never extracted, so it '
        'ships in English whatever the chosen language. Either put the literal '
        'at the call, or declare it with QT_TRANSLATE_NOOP where it is written.'
    )


def test_no_new_untranslatable_context() -> None:
    """The translation context must be a literal, or the call is never extracted.

    ``QApplication.translate(_T, "…")`` looks like ordinary factoring. It is not:
    ``pylupdate6`` has no value for ``_T``, drops the call, and says nothing.
    """
    _compare_to_baseline(
        _debt_by_module(doctrine.I18N_CONTEXT), UNTRANSLATABLE_CONTEXT_DEBT,
        'the set of translation calls with a non-literal context',
    )


def test_no_new_untranslatable_source() -> None:
    """Same rule for the string itself — f-strings and variables are invisible.

    ``QT_TRANSLATE_NOOP`` is the escape hatch and it is a real one: it declares
    the literal for the extractor and returns it unchanged, so a value can still
    be translated at run time. A module using it for a context is not flagged for
    that context.
    """
    _compare_to_baseline(
        _debt_by_module(doctrine.I18N_SOURCE), UNTRANSLATABLE_SOURCE_DEBT,
        'the set of translation calls with a non-literal source string',
    )


def test_upstream_value_rendering_stays_where_it_is() -> None:
    """Translating an Artisan-owned value through an Artisan context is correct.

    Frozen rather than ignored. The same shape would appear if a new TilauScope
    string were filed under ``Label`` or ``Combobox`` instead of a ``tilauscope``
    context — which the extractor would happily accept and which would put our
    string in somebody else's catalogue.
    """
    _compare_to_baseline(
        _debt_by_module(doctrine.I18N_UPSTREAM), UPSTREAM_VALUE_SITES,
        'the set of Artisan-owned values rendered through an upstream context',
    )


def test_every_module_uses_the_styled_dialog() -> None:
    """No raw ``QMessageBox`` outside the module that implements the styled one.

    Zero today, and the point is to keep it there. A system message box in a
    Catppuccin window is not a subtle regression, but it is an easy one: the
    Qt documentation and every code sample reach for the static call.
    """
    offenders = [
        site
        for path in doctrine.source_files()
        if path.name != STYLED_DIALOG_MODULE
        for site in doctrine.raw_message_box_sites(path)
    ]
    assert not offenders, (
        'raw QMessageBox used instead of show_styled_message():\n'
        + '\n'.join(f'  {s}' for s in offenders)
    )


def test_the_styled_dialog_helper_still_exists() -> None:
    """Guard the guard: the rule above is only meaningful with a way to obey it."""
    source = (doctrine.PKG_DIR / STYLED_DIALOG_MODULE).read_text(encoding='utf-8')
    assert 'def show_styled_message(' in source, (
        f'show_styled_message() is gone from {STYLED_DIALOG_MODULE} — the '
        'no-raw-QMessageBox rule now forbids something with no replacement.'
    )


# ── thread discipline ────────────────────────────────────────────────────────

#: Modules whose code runs on the aiohttp event loop thread, not on Qt's.
#: Protocol §8, invariant 8: every ``qmc`` access goes through the bridge's
#: queued connection.
#:
#: ``telemetry_tap`` is deliberately absent. It reads ``qmc`` constantly and is
#: right to: it is driven by ``tilauUpdateSignal``, so it already executes on
#: the Qt main thread and only hands plain dictionaries across to the server
#: side. Listing it would have frozen a large permanent exception into the rule
#: and taught the reader that the rule has exceptions — which is how a rule
#: stops being obeyed.
WS_THREAD_MODULES: Final[tuple[str, ...]] = ('webcontrol.py', 'webhost.py')

#: Attribute roots that mean "you are on the Qt side now".
QT_OWNED_ROOTS: Final[frozenset[str]] = frozenset({'qmc', 'aw'})


@pytest.mark.parametrize('module', WS_THREAD_MODULES)
def test_ws_thread_never_touches_qt_state(module: str) -> None:
    """The server thread reads plain data only; ``qmc`` belongs to the bridge.

    Touching Qt or ``qmc`` from the WebSocket thread does not raise. It corrupts
    state and the process dies later inside a native frame, with no Python
    traceback to point back here — the signature is a ``SIGTRAP`` in a Qt paint
    call after an unrelated user action. That distance between cause and symptom
    is the whole reason for checking statically.
    """
    path = doctrine.PKG_DIR / module
    tree = doctrine.parse(path)

    offenders: list[doctrine.Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        chain = doctrine.attribute_chain(node)
        parts = chain.split('.')
        # `self.aw.qmc.timex` -> look past `self`, `_x`, etc. for a Qt root that
        # is being dereferenced, i.e. not the last element of the chain.
        for i, part in enumerate(parts[:-1]):
            if part in QT_OWNED_ROOTS:
                offenders.append(doctrine.Site(module, node.lineno, chain))
                break
            del i

    # Report deepest chains only: `a.qmc.b.c` also walks `a.qmc.b`, and three
    # lines for one access buries the signal.
    unique = {(s.lineno, s.detail) for s in offenders}
    deepest = {
        (line, detail) for line, detail in unique
        if not any(other.startswith(detail + '.')
                   for oline, other in unique if oline == line)
    }
    assert not deepest, (
        f'{module} dereferences Qt-owned state from the server thread:\n'
        + '\n'.join(f'  tilauscope/{module}:{line}: {detail}'
                    for line, detail in sorted(deepest))
        + '\n\nRoute it through TilauCommandBridge.submit() (queued connection) '
          'so the access happens on the Qt main thread.'
    )


#: Artisan's device functions run on the sampling thread. Reading ``qmc`` there
#: is what they are for; *changing the application* from there is not.
ARTISAN_DIR: Final[Path] = Path(__file__).resolve().parent.parent / 'artisanlib'

#: Work the TRP handshake must not do inline — each redraws the canvas or
#: rebuilds widgets, and the sampling thread may do neither.
GUI_ONLY_IN_HANDSHAKE: Final[tuple[str, ...]] = (
    'sync_roaster_to_qmc', 'refresh_replay_capability')


def test_roaster_auto_identification_is_handed_to_the_gui_thread() -> None:
    """The TRP handshake may name the roaster; it may not adopt it.

    ``_trp_handshake`` runs inside a device function, i.e. on the sampling
    thread. Adopting a roaster redraws the canvas and realigns the TilauScope
    controls that reason on the machine — Qt work, with the same delayed
    ``SIGTRAP`` signature as the rule above. The adoption therefore leaves by
    signal and lands on ApplicationWindow's GUI thread.
    """
    comm = doctrine.parse(ARTISAN_DIR / 'comm.py')
    handshake = next(
        node for node in ast.walk(comm)
        if isinstance(node, ast.FunctionDef) and node.name == '_trp_handshake'
    )

    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(handshake)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    forbidden = sorted(set(GUI_ONLY_IN_HANDSHAKE) & called)
    assert not forbidden, (
        'artisanlib/comm.py _trp_handshake() does GUI work on the sampling '
        f'thread: {", ".join(forbidden)}.\n'
        'Emit tilauRoasterIdentifiedSignal instead — it lands on the GUI '
        'thread through applyTilauRoasterIdentification().'
    )

    assigned = {
        doctrine.attribute_chain(target)
        for node in ast.walk(handshake)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    assert 'self.aw.tilau_roaster' not in assigned, (
        'the handshake sets aw.tilau_roaster itself — the readers that cache a '
        'machine context are never told, so the assistant keeps advising on '
        'the previous roaster.'
    )
    assert 'tilauRoasterIdentifiedSignal' in ast.unparse(handshake), (
        'the handshake no longer hands the identified roaster to the GUI thread.'
    )

    # The other end has to exist, or the emit is a silent no-op.
    main = doctrine.parse(ARTISAN_DIR / 'main.py')
    app = next(
        node for node in ast.walk(main)
        if isinstance(node, ast.ClassDef) and node.name == 'ApplicationWindow'
    )
    declared = {
        target.id
        for node in app.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    assert 'tilauRoasterIdentifiedSignal' in declared, (
        'ApplicationWindow does not declare tilauRoasterIdentifiedSignal.')
    slots = {
        node.name for node in ast.walk(app)
        if isinstance(node, ast.FunctionDef)
    }
    assert 'applyTilauRoasterIdentification' in slots, (
        'the signal has no slot on the GUI side.')
    source = (ARTISAN_DIR / 'main.py').read_text(encoding='utf-8')
    assert ('self.tilauRoasterIdentifiedSignal.connect('
            'self.applyTilauRoasterIdentification)') in source, (
        'the signal is declared but never connected — emitting it does nothing.'
    )


# ── stylesheet templates ─────────────────────────────────────────────────────

#: Button stylesheets are ``str.format`` templates held in one module and filled
#: in from many call sites. A placeholder added to a template is invisible to
#: every caller that does not supply it — see the docstring below.
STYLE_TEMPLATE_MODULE: Final[str] = 'button_style.py'
STYLE_TEMPLATE_CALLERS: Final[tuple[str, ...]] = ('main.py', 'canvas.py')


def _style_templates() -> dict[str, dict[str, str]]:
    """{dict name: {key: template}} for every button-style dict."""
    tree = doctrine.parse(ARTISAN_DIR / STYLE_TEMPLATE_MODULE)
    found: dict[str, dict[str, str]] = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            target = node.targets[0].id
        if target and target.endswith('_dict') and isinstance(node.value, ast.Dict):
            found[target] = ast.literal_eval(node.value)
    return found


def test_every_button_style_call_fills_its_template() -> None:
    """A stylesheet template and its callers must agree on the placeholders.

    ``str.format`` fails only at the moment of the call, with a ``KeyError``
    naming the placeholder and nothing naming the template. These calls sit
    inside broad ``except`` blocks that log and swallow, so the visible symptom
    is not a wrong-looking button — it is every statement *after* the call in
    that try block silently not running. Adding a placeholder to a template is
    therefore a change every call site has to be checked against, which is what
    this does.
    """
    templates = _style_templates()
    assert templates, 'no button-style dicts found — did the module move?'

    required = {
        name: {key: {field for _, field, _, _ in Formatter().parse(tpl) if field}
               for key, tpl in entries.items()}
        for name, entries in templates.items()
    }

    offenders: list[str] = []
    for module in STYLE_TEMPLATE_CALLERS:
        tree = doctrine.parse(ARTISAN_DIR / module)
        for node in ast.walk(tree):
            # <dict>['KEY'].format(...)
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'format'
                    and isinstance(node.func.value, ast.Subscript)):
                continue
            sub = node.func.value
            if not (isinstance(sub.value, ast.Name) and sub.value.id in required):
                continue
            if not (isinstance(sub.slice, ast.Constant)
                    and isinstance(sub.slice.value, str)):
                continue
            needed = required[sub.value.id].get(sub.slice.value)
            if needed is None:
                offenders.append(
                    f'  artisanlib/{module}:{node.lineno}: '
                    f'{sub.value.id}[{sub.slice.value!r}] is not a key of that dict')
                continue
            supplied = {kw.arg for kw in node.keywords if kw.arg is not None}
            if any(kw.arg is None for kw in node.keywords):
                continue        # **kwargs — cannot be judged statically
            missing = sorted(needed - supplied)
            if missing:
                offenders.append(
                    f'  artisanlib/{module}:{node.lineno}: '
                    f'{sub.value.id}[{sub.slice.value!r}] does not supply '
                    f'{", ".join(missing)}')

    assert not offenders, (
        'button stylesheet calls do not fill their template:\n'
        + '\n'.join(sorted(offenders))
        + f'\n\nEvery placeholder declared in artisanlib/{STYLE_TEMPLATE_MODULE} '
          'has to be passed by every caller, or the call raises KeyError at '
          'runtime and takes the rest of its try block down with it.'
    )


# ── premise ──────────────────────────────────────────────────────────────────

_PYLUPDATE: Final[str | None] = shutil.which(
    'pylupdate6', path=str(Path(sys.executable).parent),
) or shutil.which('pylupdate6')

_PROBE: Final[str] = '''\
from PyQt6.QtWidgets import QApplication
_CTX = "ctx_from_variable"
QApplication.translate(_CTX, "VIA_VARIABLE_CONTEXT")
QApplication.translate("ctx_literal", "VIA_LITERALS")
_name = "x"
QApplication.translate("ctx_literal", f"VIA_FSTRING_{_name}")
QApplication.translate("ctx_literal", _name)
'''


@pytest.mark.slow
@pytest.mark.skipif(_PYLUPDATE is None, reason='pylupdate6 not on PATH')
def test_pylupdate_really_drops_non_literals(tmp_path: Path) -> None:
    """Prove the premise the two baselines above rest on.

    Everything in this file assumes the extractor skips non-literal arguments.
    That is an assumption about a tool, not about our code, and it could change
    under a PyQt upgrade. So it is measured rather than believed: if a future
    ``pylupdate6`` learns to resolve a module-level constant, this test fails and
    177 sites stop being debt.
    """
    probe = tmp_path / 'probe.py'
    probe.write_text(_PROBE, encoding='utf-8')
    out = tmp_path / 'probe.ts'

    subprocess.run(  # noqa: S603
        [_PYLUPDATE, str(probe), '-ts', str(out)],
        check=True, capture_output=True, timeout=120,
    )
    catalogue = out.read_text(encoding='utf-8')

    assert 'VIA_LITERALS' in catalogue, (
        'the fully-literal call was not extracted either — the probe is wrong, '
        'not the extractor'
    )
    for skipped in ('VIA_VARIABLE_CONTEXT', 'VIA_FSTRING', 'ctx_from_variable'):
        assert skipped not in catalogue, (
            f'pylupdate6 now extracts {skipped!r}. The frozen debt in this file '
            'is no longer debt — re-measure and lower the baselines.'
        )
