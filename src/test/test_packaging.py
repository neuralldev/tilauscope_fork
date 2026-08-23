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

"""What the source imports must survive being frozen into an installer.

This is the failure that costs the most to find late. Everything works from
source, because the developer's virtualenv has the package — pulled in as
somebody else's dependency, never asked for by name. The CI runner resolves
differently, or the upstream drops it, and the ``.dmg`` builds clean and dies on
launch with an ``ImportError`` that nothing in the repository predicted.

Two rules, both cheap:

* a module imported by name is a module we depend on, so it belongs in
  ``requirements.txt`` with a pin, not in the transitive closure of something
  else;
* a ``## TILAU ##`` hidden import added for a fork feature belongs in *both*
  PyInstaller specs — a dependency that only PyInstaller cannot trace is exactly
  the kind that gets added to the platform being tested that day.

Import names are resolved to distribution names through the installed
environment rather than guessed. ``PIL`` comes from ``pillow`` and ``serial``
from ``pyserial``; a substring match would call both of those fine and would
also call ``pil`` present because ``pillow`` contains it.
"""

from __future__ import annotations

import ast
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Final

import doctrine
import pytest

SRC_DIR: Final[Path] = doctrine.PKG_DIR.parent
REQUIREMENTS: Final[Path] = SRC_DIR / 'requirements.txt'
SPECS: Final[tuple[Path, ...]] = (
    SRC_DIR / 'setup-tilauscope-mac.spec',
    SRC_DIR / 'setup-tilauscope-win.spec',
)

#: Imported from inside the repository, so not a distribution.
FIRST_PARTY: Final[frozenset[str]] = frozenset({
    'tilauscope', 'artisanlib', 'artisan', 'plus', 'proto', 'uic', 'const',
})

#: Third-party modules imported by name but absent from ``requirements.txt``.
#:
#: Both arrive today as dependencies of ``instructor``, which is pinned. That is
#: what makes the arrangement fragile: importing them directly means the day
#: ``instructor`` bumps and drops one, the build still succeeds and the
#: application fails at run time, on a user's machine, in the AI path.
#:
#: Frozen rather than fixed, because pinning a version is a packaging decision
#: with a release attached to it, not something a test suite gets to make.
UNPINNED_DIRECT_IMPORTS: Final[frozenset[str]] = frozenset({
    'httpx',
    'openai',
})


def _normalise(name: str) -> str:
    """PEP 503 distribution name comparison: case- and separator-insensitive."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _pinned_distributions() -> set[str]:
    """Distribution names declared in ``requirements.txt``, markers ignored."""
    found: set[str] = set()
    for raw in REQUIREMENTS.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        # `name==1.2.3; sys_platform=='darwin'` / `name>=1,<2`
        match = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)', line.split(';', 1)[0])
        if match:
            found.add(_normalise(match.group(1)))
    return found


def _optional_fallback_imports(tree: ast.Module) -> set[str]:
    """Top-level names imported inside a ``try``/``except ImportError`` branch.

    An optional import guarded by a fallback is a deliberate "use it if it is
    there" — the code already handles its absence, so requiring a pin would be
    wrong. ``PyQt5`` is the live case: a compatibility path that never runs on a
    supported platform.
    """
    optional: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        guards_import = any(
            isinstance(h.type, ast.Name) and h.type.id in ('ImportError', 'Exception')
            or (isinstance(h.type, ast.Tuple)
                and any(isinstance(e, ast.Name) and e.id == 'ImportError'
                        for e in h.type.elts))
            or h.type is None
            for h in node.handlers
        )
        if not guards_import:
            continue
        for branch in (*node.body, *(s for h in node.handlers for s in h.body)):
            for sub in ast.walk(branch):
                if isinstance(sub, ast.Import):
                    optional.update(a.name.split('.')[0] for a in sub.names)
                elif isinstance(sub, ast.ImportFrom) and sub.level == 0 and sub.module:
                    optional.add(sub.module.split('.')[0])
    return optional


def _imported_top_levels() -> set[str]:
    """Third-party top-level modules ``tilauscope`` imports unconditionally."""
    required: set[str] = set()
    optional: set[str] = set()
    for path in doctrine.source_files():
        tree = doctrine.parse(path)
        optional |= _optional_fallback_imports(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                required.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                required.add(node.module.split('.')[0])
    return {
        name for name in required - optional
        if name not in sys.stdlib_module_names and name not in FIRST_PARTY
    }


def _distributions_for(top_level: str) -> set[str]:
    """Distributions providing an import name, per the installed environment."""
    return {_normalise(d) for d in metadata.packages_distributions().get(top_level, ())}


def test_requirements_file_is_readable() -> None:
    """Guard the guard: an unparsed requirements file would pass everything."""
    pinned = _pinned_distributions()
    assert len(pinned) > 40, (
        f'only {len(pinned)} distributions parsed out of {REQUIREMENTS} — the '
        'format changed and the check below is now vacuous'
    )


def test_every_imported_package_is_pinned() -> None:
    """A direct import is a direct dependency, whoever happens to install it.

    Resolution goes through the live environment, so this test says something
    about *this* machine's virtualenv. That is the right place for it: it is the
    machine the release is built from, and a module that cannot be resolved here
    could not have been imported here either.
    """
    pinned = _pinned_distributions()
    unpinned: dict[str, set[str]] = {}

    for name in sorted(_imported_top_levels()):
        dists = _distributions_for(name)
        if not dists:
            # Not installed under a distribution the metadata knows about —
            # a C extension installed by hand, or a name that is simply absent.
            # Fall back to the import name itself.
            dists = {_normalise(name)}
        if not (dists & pinned):
            unpinned[name] = dists

    unexpected = {k: v for k, v in unpinned.items() if k not in UNPINNED_DIRECT_IMPORTS}
    assert not unexpected, (
        'imported directly but not pinned in requirements.txt:\n'
        + '\n'.join(f'  import {name}  (distribution: {", ".join(sorted(d))})'
                    for name, d in unexpected.items())
        + '\n\nThe frozen build resolves dependencies independently of this '
          'virtualenv — an unpinned import is an ImportError waiting for the '
          'first machine that resolves differently.'
    )

    resolved = UNPINNED_DIRECT_IMPORTS - set(unpinned)
    assert not resolved, (
        f'{sorted(resolved)} are now pinned — remove them from '
        'UNPINNED_DIRECT_IMPORTS so they cannot silently slip back out.'
    )


# ── PyInstaller specs ────────────────────────────────────────────────────────

def _hidden_import_block(spec: Path) -> str:
    text = spec.read_text(encoding='utf-8')
    block = re.search(r'hidden_?imports_?(?:list)?\s*=\s*\[(.*?)\n\s*\]', text, re.S)
    assert block, f'{spec.name}: no hidden imports list found'
    return block.group(1)


def _all_hidden_imports(spec: Path) -> set[str]:
    """Every name in the spec's hidden-imports list, marked or not."""
    return {
        name
        for line in _hidden_import_block(spec).splitlines()
        if not line.strip().startswith('#')
        for name in re.findall(r"'([^']+)'", line)
    }


def _tilau_hidden_imports(spec: Path) -> set[str]:
    """Names introduced by a ``## TILAU ##`` comment, up to the next comment.

    Only the fork's own additions are singled out. The rest of each list is
    genuinely platform-specific — ``pywintypes`` has no business in a ``.dmg`` —
    and demanding parity there would be wrong.

    Marker placement is a comment convention, not data: the same name sits
    inside a marked block in one spec and above it in the other. So this is used
    only to decide *which* names the fork cares about; whether they are present
    is then checked against the whole list on both sides.
    """
    names: set[str] = set()
    in_tilau_block = False
    for line in _hidden_import_block(spec).splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            in_tilau_block = '## TILAU ##' in stripped
            continue
        if in_tilau_block:
            names.update(re.findall(r"'([^']+)'", stripped))
    return names


def test_both_specs_carry_every_fork_hidden_import() -> None:
    """A fork dependency shipped on one platform and missing on the other.

    PyInstaller finds imports by following them statically. The ones listed here
    are precisely the ones it cannot find — C extensions, plugin backends,
    modules loaded through ``__import__``. They are invisible to the tooling by
    definition, so nothing but this comparison will notice one being added to a
    single spec: macOS is where the work happens, and the Windows installer is
    built later, by CI, from the spec nobody reopened.
    """
    mac_spec, win_spec = SPECS
    required = _tilau_hidden_imports(mac_spec) | _tilau_hidden_imports(win_spec)
    mac, win = _all_hidden_imports(mac_spec), _all_hidden_imports(win_spec)

    missing = {
        mac_spec.name: sorted(required - mac),
        win_spec.name: sorted(required - win),
    }
    assert not any(missing.values()), (
        'a fork hidden import is declared in one PyInstaller spec but absent '
        'from the other:\n'
        + '\n'.join(f'  missing from {spec}: {names}'
                    for spec, names in missing.items() if names)
        + '\nThat installer raises ImportError on first use of the feature the '
          'name belongs to.'
    )


@pytest.mark.parametrize('spec', SPECS, ids=lambda p: p.stem)
def test_spec_hidden_imports_are_not_empty(spec: Path) -> None:
    """Guard the guard: a regex that stops matching makes the parity test vacuous."""
    assert _tilau_hidden_imports(spec), (
        f'{spec.name}: no `## TILAU ##` hidden imports extracted. Either the list '
        'was restructured or the markers were dropped — the parity check above is '
        'comparing two empty sets.'
    )


# ── the excluded package must stay unreachable from shipped code ────────────

def test_the_render_gate_sits_below_the_lcd_updates() -> None:
    """TilauScope suspends Artisan's figure while it draws the roast itself.

    The obvious place for that gate is the top of ``updategraphics`` — and it is
    the wrong one. ``updateLCDs()`` is called from inside that method, and
    ``updateLCDs`` is what emits ``tilauUpdateSignal``: an early return would cut
    TilauScope's own supply of samples while claiming to save its rendering. The
    screen would go still, the figure would be "saved", and nothing would say so.

    So the gate belongs strictly after the LCD call. This asserts the order in
    the source, because there is no cheap way to assert it at runtime and the
    mistake looks correct on the page.
    """
    src = (SRC_DIR / 'artisanlib' / 'canvas.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    method = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == 'updategraphics'), None)
    assert method is not None, 'updategraphics has gone missing'

    lcd_lines = [n.lineno for n in ast.walk(method)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in {'updateLCDs', 'updatePhasesLCDs'}]
    assert lcd_lines, 'updategraphics no longer updates the LCDs — check the gate'

    gate_lines = [n.lineno for n in ast.walk(method)
                  if isinstance(n, ast.Attribute) and n.attr == 'tilau_suspend_render']
    assert gate_lines, 'the render gate is gone from updategraphics'
    assert min(gate_lines) > min(lcd_lines), (
        'the render gate moved above the LCD update: suspending the figure now '
        'also suspends the samples TilauScope is drawn from')


def test_every_header_button_styles_its_own_tooltip() -> None:
    """Qt styles a tooltip from the sheet of the hovered widget itself when it
    has one. Each header button carries its own sheet, so each has to carry the
    tooltip rule too — otherwise the tip falls back to the system white on a
    dark screen."""
    from tilauscope import header_icons

    sheets = {name: getattr(header_icons, name)
              for name in dir(header_icons) if name.startswith('QSS_')}
    assert sheets, 'no header button stylesheets found'
    naked = [name for name, qss in sheets.items() if 'QToolTip' not in qss]
    assert not naked, f'these sheets leave their tooltip unstyled: {naked}'
