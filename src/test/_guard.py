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

"""Hermetic Qt sandbox for the TilauScope test suite.

WHY THIS FILE EXISTS
--------------------
``artisanlib/main.py`` runs, at *module scope*, an organisation/application
name binding plus a legacy-settings migration block that calls
``QSettings.setValue()``.  Merely importing that module therefore **writes to
the developer's real preferences** (cfprefsd on macOS).  Eight TilauScope
modules import it without a ``TYPE_CHECKING`` guard, so any harness that
reaches them would clobber the live Artisan configuration.

WHAT ACTUALLY PROTECTS US
-------------------------
Not the organisation name: ``artisanlib.main`` overwrites it the moment it is
imported, and we cannot stop that.  The protection is the pair::

    QSettings.setDefaultFormat(IniFormat)
    QSettings.setPath(IniFormat, scope, <sandbox>)

Both are *process-global statics*.  Once applied, every default-constructed
``QSettings()`` resolves to a file underneath the sandbox directory, whatever
organisation name the code later sets.  Order is the whole game: they must be
in place before the first ``QSettings`` instance is built, which is why every
module import under test happens in a fresh subprocess that calls
:func:`install` as its very first statement.

The organisation name we set is a *tripwire*, not a lock: if a test observes
one of :data:`FORBIDDEN_ORGS`, it means real-preference code ran, and the
sandbox assertion in :func:`verify` is what decides whether damage was
possible.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

#: Identity the sandbox binds, so settings files are obviously test artefacts.
TEST_ORG: Final[str] = 'TilauScopeTest'
TEST_DOMAIN: Final[str] = 'tilauscope.test.invalid'
TEST_APP: Final[str] = 'tilauscope-pytest'

#: Passed to subprocesses so every child writes into the same sandbox.
SANDBOX_ENV: Final[str] = 'TILAU_TEST_SETTINGS_DIR'

#: Real identities. Seeing one of these means artisanlib.main was imported.
FORBIDDEN_ORGS: Final[frozenset[str]] = frozenset({'artisan-scope', 'YourQuest'})

#: Key written by :func:`verify` to prove the settings file lands in the sandbox.
_PROBE_KEY: Final[str] = '_tilau_sandbox_probe'

#: Path component Qt inserts when QStandardPaths test mode is on ('.qttest' on
#: Unix, 'qttest' on Windows) — the substring covers both.
_TEST_MODE_MARKER: Final[str] = 'qttest'


class SandboxEscape(RuntimeError):
    """Qt settings resolved outside the sandbox — real preferences are at risk."""


def sandbox_dir() -> Path:
    """Sandbox directory for this process, creating one if none is inherited.

    The path is exported through :data:`SANDBOX_ENV` so subprocesses spawned by
    the import portico share it instead of scattering temporary directories.
    """
    inherited = os.environ.get(SANDBOX_ENV)
    if inherited:
        d = Path(inherited)
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = Path(tempfile.mkdtemp(prefix='tilau-test-settings-'))
    os.environ[SANDBOX_ENV] = str(d)
    return d


def install(target: str | os.PathLike[str] | None = None) -> Path:
    """Install the hermetic sandbox. Must run before any ``QSettings`` exists.

    Returns the sandbox directory. Raises :class:`SandboxEscape` if the
    redirection did not take, which means the caller imported Qt settings code
    too early.
    """
    # Offscreen first: a headless run must never try to open a display, and on
    # macOS it also keeps Qt from registering the process with the window server.
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    # Artisan reads these; keep any hardware/telemetry side path inert by default.
    os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.*=false')

    d = Path(target) if target is not None else sandbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.environ[SANDBOX_ENV] = str(d)

    from PyQt6.QtCore import QCoreApplication, QSettings, QStandardPaths

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(d))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.SystemScope, str(d))

    # Settings are not the only thing that escapes. `artisanlib.util.
    # getDataDirectory()` resolves QStandardPaths.AppLocalDataLocation and
    # *creates* the directory — under the live organisation name, which
    # artisanlib.main rebinds to the real one. Test mode reroutes every
    # standard location into Qt's own test area, so that call can never land
    # on the user's real Artisan data directory.
    QStandardPaths.setTestModeEnabled(True)

    QCoreApplication.setOrganizationName(TEST_ORG)
    QCoreApplication.setOrganizationDomain(TEST_DOMAIN)
    QCoreApplication.setApplicationName(TEST_APP)

    verify(d)
    return d


def settings_file() -> Path:
    """Absolute path a default ``QSettings()`` currently resolves to."""
    from PyQt6.QtCore import QSettings

    return Path(QSettings().fileName()).resolve()


def verify(target: str | os.PathLike[str] | None = None) -> Path:
    """Prove a default ``QSettings()`` reads *and writes* inside the sandbox.

    Resolution alone is not proof — the value is written and flushed, then the
    on-disk file is checked, so a silently ineffective redirection cannot pass.
    """
    d = Path(target) if target is not None else sandbox_dir()
    d = d.resolve()

    from PyQt6.QtCore import QSettings

    settings = QSettings()
    resolved = Path(settings.fileName()).resolve()
    if not resolved.is_relative_to(d):
        raise SandboxEscape(
            f'QSettings resolves to {resolved}, outside the sandbox {d}. '
            'Qt settings were touched before the sandbox was installed.',
        )

    settings.setValue(_PROBE_KEY, 1)
    settings.sync()
    if not resolved.is_file():
        raise SandboxEscape(
            f'QSettings claims {resolved} but writing produced no file there; '
            'the write went somewhere else (native backend still active?).',
        )

    # PyQt6 exposes setTestModeEnabled() but no getter, so check the effect
    # rather than the flag. Note the organisation name is NOT a usable signal:
    # once artisanlib.main rebinds it, the redirected path legitimately reads
    # `~/.qttest/Library/Application Support/artisan-scope/Artisan` — the real
    # org name inside the test area. What matters is the test-area marker Qt
    # documents ('.qttest' on Unix, 'qttest' on Windows).
    from PyQt6.QtCore import QStandardPaths

    data_root = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation,
    )
    if _TEST_MODE_MARKER not in data_root:
        raise SandboxEscape(
            f'application data directory resolves to {data_root}, which is not '
            'inside Qt\'s test area; QStandardPaths test mode did not take effect '
            'and code touching the data directory could reach the real Artisan one.',
        )
    return d


def contaminated_org() -> str | None:
    """Real organisation name currently bound, or ``None`` when clean.

    A non-``None`` result means ``artisanlib.main`` (or equivalent) executed.
    That is informative, not fatal on its own: :func:`verify` decides whether
    the writes could have escaped.
    """
    from PyQt6.QtCore import QCoreApplication

    org = QCoreApplication.organizationName()
    return org if org in FORBIDDEN_ORGS else None
