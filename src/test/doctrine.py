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

"""Static analysis helpers for the project's own conventions.

The rules checked on top of this module are not general Python hygiene — ruff
already does that, and does it better. They are TilauScope house rules whose
violations are *silent*: the code runs, nothing raises, and the damage only
shows up later, somewhere else. A string that never reaches the translator, a
dialog that ignores the theme, a background thread that touches Qt. Nothing
fails at the point of the mistake, which is exactly why a machine has to look.

Everything here works on the syntax tree rather than on text. A grep for
``QMessageBox`` cannot tell a construction from an enum reference, and the
codebase passes the enum around constantly — a text-based rule would be so
noisy it would be switched off within the week.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple

#: The fork's own package. Upstream ``artisanlib`` is deliberately out of scope:
#: its conventions are not ours and we do not get to change them.
PKG_DIR: Final[Path] = Path(__file__).resolve().parent.parent / 'tilauscope'

#: Names a Qt translation call can be reached through. Anything else called
#: ``translate`` is somebody else's method — ``QPainter.translate`` moves the
#: canvas origin and appears in the label-printing code.
I18N_RECEIVERS: Final[frozenset[str]] = frozenset({
    'QApplication', 'QCoreApplication', 'QtWidgets', 'QtCore',
})

#: Tags for the ways a translation call goes missing.
I18N_CONTEXT: Final[str] = 'i18n-context'
I18N_SOURCE: Final[str] = 'i18n-source'
I18N_UPSTREAM: Final[str] = 'i18n-upstream'

#: Translation contexts that belong to upstream Artisan, not to the fork.
#:
#: Feeding a variable to ``translate()`` in one of these is the *correct* way to
#: render a value Artisan owns — a probe name, an extra-device label, a milestone
#: — because Artisan already declares those literals in its own catalogue. There
#: is nothing here for our extractor to find and nothing to fix.
#:
#: The limit of this rule, stated plainly: it would also excuse a genuinely new
#: TilauScope string filed under an upstream context. That is already against the
#: convention (fork strings go in a ``tilauscope*`` context), and the count of
#: these sites is frozen so a new one still has to be looked at.
ARTISAN_OWNED_CONTEXTS: Final[frozenset[str]] = frozenset({
    'Label', 'ComboBox', 'Combobox', 'Button', 'Tab', 'Textbox', 'CheckBox',
    'Menu', 'Message', 'Tooltip', 'Scope Title',
})


class Site(NamedTuple):
    """One flagged location, reported the way an editor can jump to it.

    ``kind`` is a machine-readable tag; ``detail`` is the sentence a human
    reads. Callers group on the tag — matching against the prose would break
    the moment the wording is improved.
    """

    module: str
    lineno: int
    detail: str
    kind: str = ''

    def __str__(self) -> str:
        return f'tilauscope/{self.module}:{self.lineno}: {self.detail}'


def source_files() -> list[Path]:
    """Every TilauScope module, in a stable order."""
    return sorted(PKG_DIR.rglob('*.py'))


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def _root_name(node: ast.expr) -> str | None:
    """Left-most identifier of a dotted expression: ``a.b.c`` -> ``'a'``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_str_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def i18n_calls(tree: ast.Module) -> list[ast.Call]:
    """Qt translation calls, with the look-alikes filtered out."""
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == 'translate'
        and _root_name(n.func) in I18N_RECEIVERS
    ]


def declared_noop_contexts(tree: ast.Module) -> set[str]:
    """Contexts this module declares strings for via ``QT_TRANSLATE_NOOP``.

    That macro exists precisely for the case a literal cannot sit at the
    ``translate()`` call: it marks the string for the extractor and returns it
    unchanged, so the lookup later succeeds on a value. A module using it is
    obeying the rule, not breaking it, and flagging the downstream call would
    push people away from the one correct answer.
    """
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'QT_TRANSLATE_NOOP'
        and len(node.args) == 2
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def untranslatable_sites(path: Path) -> list[Site]:
    """Translation calls the string extractor cannot see.

    ``pylupdate6`` reads the source; it does not run it. An argument that is not
    a string literal is a name it has no value for, so the call is skipped — and
    skipped *silently*: the run reports how many messages it added, never how
    many it walked past. The string then ships in English forever, and no amount
    of translating the ``.ts`` file will bring it back.

    Both arguments matter. A non-literal source is the obvious case. A non-literal
    context is subtler and just as fatal — hoisting ``_T = "tilauscope"`` to save
    repetition reads as a tidy-up and removes the whole call from the catalogue.

    A non-literal source is *not* flagged when the module declares strings for
    that same context with ``QT_TRANSLATE_NOOP``: the string is then extractable
    where it is written, which is all the rule ever asked for.
    """
    tree = parse(path)
    declared = declared_noop_contexts(tree)
    sites: list[Site] = []
    for call in i18n_calls(tree):
        args = call.args
        if args and not _is_str_literal(args[0]):
            sites.append(Site(
                path.name, call.lineno,
                'translation context is not a string literal — pylupdate6 skips '
                'this call entirely',
                kind=I18N_CONTEXT,
            ))
        if len(args) >= 2 and not _is_str_literal(args[1]):
            context = args[0].value if _is_str_literal(args[0]) else None
            if context in declared:
                continue
            if context in ARTISAN_OWNED_CONTEXTS:
                sites.append(Site(
                    path.name, call.lineno,
                    f'renders an Artisan-owned value through the {context!r} '
                    'context — the literal belongs to the upstream catalogue',
                    kind=I18N_UPSTREAM,
                ))
                continue
            sites.append(Site(
                path.name, call.lineno,
                'translated string is not a string literal, and this module '
                'declares nothing for that context with QT_TRANSLATE_NOOP',
                kind=I18N_SOURCE,
            ))
    return sites


def raw_message_box_sites(path: Path) -> list[Site]:
    """Direct uses of ``QMessageBox`` as a dialog rather than as an enum.

    Flags construction (``QMessageBox(...)``), the static convenience calls, and
    subclassing. Bare attribute access is left alone on purpose: the sanctioned
    helper takes a ``QMessageBox.Icon`` argument, so the name legitimately
    appears at hundreds of call sites that are doing exactly the right thing.
    """
    static_calls = {'warning', 'information', 'critical', 'question', 'about'}
    sites: list[Site] = []
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == 'QMessageBox':
                sites.append(Site(path.name, node.lineno,
                                  'constructs a raw QMessageBox'))
            elif (isinstance(func, ast.Attribute)
                  and func.attr in static_calls
                  and isinstance(func.value, ast.Name)
                  and func.value.id == 'QMessageBox'):
                sites.append(Site(path.name, node.lineno,
                                  f'calls QMessageBox.{func.attr}()'))
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == 'QMessageBox':
                    sites.append(Site(path.name, node.lineno,
                                      f'class {node.name} subclasses QMessageBox'))
    return sites


#: The only module allowed to assemble a model message. Everything else asks
#: it for one, which is what makes the scrubbing unconditional.
AI_MESSAGE_GATE: Final[str] = 'tilau_privacy.py'

#: Tag for a prompt built outside the gate.
AI_PAYLOAD: Final[str] = 'ai-payload'


def raw_ai_message_sites(path: Path) -> list[Site]:
    """Model messages assembled by hand instead of through the privacy gate.

    A chat message is a dict with ``role`` and ``content``, or a literal list
    handed to a ``messages=`` argument. Both mean a payload was built where
    ``prepare_ai_messages()`` could not see it, and a payload the scrubber does
    not see is a payload that leaves with whatever the user typed in it.

    The rule is structural rather than textual on purpose: the strings ``role``
    and ``content`` are far too common to grep for.
    """
    if path.name == AI_MESSAGE_GATE:
        return []
    sites: list[Site] = []
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Dict):
            keys = {
                key.value for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if {'role', 'content'} <= keys:
                sites.append(Site(
                    path.name, node.lineno,
                    'builds a model message by hand — go through '
                    'tilau_privacy.prepare_ai_messages()', AI_PAYLOAD))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == 'messages' and isinstance(kw.value, (ast.List, ast.Tuple)):
                    sites.append(Site(
                        path.name, node.lineno,
                        'passes a literal messages= list to a model call — go '
                        'through tilau_privacy.prepare_ai_messages()',
                        AI_PAYLOAD))
    return sites


#: The module holding the disclosure gate.
AI_DISCLOSURE_GATE: Final[str] = 'tilau_privacy_ui.py'

#: Tag for an AI request started without naming its recipient.
AI_DISCLOSURE: Final[str] = 'ai-disclosure'

#: Modules that reach the model but never from the UI thread, so they cannot
#: raise a dialog and must not try: their callers hold the gate instead.
_OFF_THREAD_AI: Final[frozenset[str]] = frozenset({
    'bean_extractor.py',
})

#: Constructing one of these starts an AI request against a supplier page.
_AI_WORKERS: Final[frozenset[str]] = frozenset({
    'BeanAIWorker', '_WizardAIWorker',
})


def ungated_ai_launch_sites(path: Path) -> list[Site]:
    """AI requests started without the operator being told who receives them.

    Art. 13 is satisfied once per provider, not once per installation, and the
    place it has to happen is where the request is *launched* — the only place
    that runs on the UI thread and can still stop. A module that starts a
    request and never names ``ensure_ai_disclosure()`` has no such place.

    Textual on the gate name and structural on the launch: naming the gate is
    the whole obligation, so the presence of the name is the whole check.
    """
    if path.name in (AI_MESSAGE_GATE, AI_DISCLOSURE_GATE) or path.name in _OFF_THREAD_AI:
        return []
    tree = parse(path)
    launches: list[Site] = []
    gated = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id == 'ensure_ai_disclosure':
                gated = True
            elif node.id == 'prepare_ai_messages':
                launches.append(Site(
                    path.name, node.lineno,
                    'sends a prompt without naming the recipient — call '
                    'tilau_privacy_ui.ensure_ai_disclosure() first',
                    AI_DISCLOSURE))
            elif node.id in _AI_WORKERS:
                launches.append(Site(
                    path.name, node.lineno,
                    f'starts {node.id} without naming the recipient — call '
                    'tilau_privacy_ui.ensure_ai_disclosure() first',
                    AI_DISCLOSURE))
        elif isinstance(node, ast.Attribute) and node.attr == 'ensure_ai_disclosure':
            gated = True
    return [] if gated else launches


#: Tag for a credential that would reach the settings file.
SERIALISED_SECRET: Final[str] = 'serialised-secret'

#: Field names that hold a credential. Matched as substrings on the field name,
#: so ``password_encoded`` and ``_apikey`` are both caught.
_SECRET_FIELDS: Final[tuple[str, ...]] = (
    'apikey', 'api_key', 'passwd', 'password', 'secret', 'token', 'credential',
)

#: Field names that merely *look* like one. ``username`` contains no secret,
#: and the keychain needs it in the settings to name the account.
_NOT_SECRET_FIELDS: Final[frozenset[str]] = frozenset({
    'token_limit', 'max_tokens', 'secret_hint',
})


def serialised_secret_sites(path: Path) -> list[Site]:
    """Credential fields a dataclass would write into the settings file.

    Artisan writes *every* setting into an exported ``.aset``, which is how a
    machine setup is shared — so a credential a dataclass serialises does not
    just sit on the operator's disk, it travels. The keychain holds them
    instead, and the field says so with ``field_options(serialize='omit')``.

    Base64 does not exempt a field: it is an encoding, not a cipher.
    """
    sites: list[Site] = []
    for node in ast.walk(parse(path)):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any('dataclass' in ast.unparse(d) for d in node.decorator_list):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            name = stmt.target.id
            lowered = name.lower().lstrip('_')
            if lowered in _NOT_SECRET_FIELDS:
                continue
            if not any(tag in lowered for tag in _SECRET_FIELDS):
                continue
            declared = ast.unparse(stmt.value) if stmt.value is not None else ''
            if "serialize='omit'" in declared or 'serialize="omit"' in declared:
                continue
            sites.append(Site(
                path.name, stmt.lineno,
                f'dataclass field {node.name}.{name} is written to the settings '
                "— keep it in the keychain and declare "
                "field(metadata=field_options(serialize='omit'))",
                SERIALISED_SECRET))
    return sites


#: Tag for a file written to a guessable name in the shared temp directory.
PREDICTABLE_TEMP: Final[str] = 'predictable-temp-path'


def predictable_temp_path_sites(path: Path) -> list[Site]:
    """Paths built under the shared temp directory rather than a private one.

    ``tempfile.gettempdir()`` is per-user on macOS and Windows, but it falls
    back to a world-readable ``/tmp`` whenever TMPDIR is unset — and that
    fallback is invisible, because the call reads identically either way. Given
    a fixed file name it yields a path any local account can read, or
    pre-create as a symlink aimed somewhere the roaster can write.

    What prompted the rule was a diagnostic writing camera frames there. The
    safe idioms name themselves: ``mkdtemp``, ``TemporaryDirectory``,
    ``NamedTemporaryFile`` — each an unguessable name inside a directory the
    operating system creates private.
    """
    sites: list[Site] = []
    for node in ast.walk(parse(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        named = (func.attr if isinstance(func, ast.Attribute)
                 else func.id if isinstance(func, ast.Name) else '')
        if named != 'gettempdir':
            continue
        sites.append(Site(
            path.name, node.lineno,
            'builds a path under the shared temp directory — use '
            'tempfile.mkdtemp() or TemporaryDirectory() so the name is '
            'unguessable and the directory private',
            PREDICTABLE_TEMP))
    return sites


def attribute_chain(node: ast.expr) -> str:
    """Render a dotted expression back to text: ``self.aw.qmc.timex``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return '.'.join(reversed(parts))
