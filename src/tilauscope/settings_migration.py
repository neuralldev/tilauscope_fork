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
# Tilau 2025-2026

# One-shot move of settings onto the fork's own identity (tilauscope / TilauScope)
# on first launch. Only ever copies — the Artisan-named store is left intact, so the change stays reversible.

from __future__ import annotations

import logging
import os
import shutil

from PyQt6.QtCore import QCoreApplication, QSettings, QStandardPaths

_log = logging.getLogger(__name__)

# Where TilauScope used to live — stock Artisan's identity.
LEGACY_ORG_NAME = 'artisan-scope'
LEGACY_ORG_DOMAIN = 'artisan-scope.org'
LEGACY_APP_NAME = 'Artisan'
LEGACY_VIEWER_NAME = 'ArtisanViewer'

# Marker written into the NEW store once the copy has run. Kept out of the
# Artisan-named store so a Factory Reset of the old one cannot re-trigger it.
_DONE_KEY = '_tilauIdentityMigrated'

# Runtime lock/sidecar files: copying them would hand the new tree a lock held
# by nothing, or a WAL that no longer matches its database.
_SKIP_SUFFIXES = ('_lock', '-shm', '-wal')


def _store(app, org_name: str, org_domain: str, app_name: str) -> QSettings:
    """A QSettings bound to an arbitrary identity.

    Qt derives the backing file from the application-level identity, so the only
    reliable way to reach another one is to swap it, build the object, and put
    it back — the approach Artisan itself uses for its own legacy migration
    (main.py, the YourQuest/p.code.google.com block).
    """
    keep = (app.organizationName(), app.organizationDomain(), app.applicationName())
    app.setOrganizationName(org_name)
    app.setOrganizationDomain(org_domain)
    app.setApplicationName(app_name)
    settings = QSettings()
    app.setOrganizationName(keep[0])
    app.setOrganizationDomain(keep[1])
    app.setApplicationName(keep[2])
    return settings


def _own_keys(settings: QSettings) -> QSettings:
    """A view restricted to the store's own file — no inherited fallbacks.

    ⚠️ A plain QSettings() aggregates the fallback chain, which on macOS ends at
    NSGlobalDomain: allKeys() then returns ~63 system keys (AppleLanguages,
    AppleLocale, AppleInterfaceStyleSwitchesAutomatically…) alongside the app's
    own. Copying those into the new store would pin them, and the application
    would stop following the system language and appearance. Addressing the file
    directly is what keeps the copy to the keys that really live in it.
    """
    return QSettings(settings.fileName(), QSettings.Format.NativeFormat)


def _copy_settings(app, app_name: str, legacy_app_name: str,
                   org_name: str, org_domain: str) -> int:
    """Copy every key of one store into another. Returns the number copied."""
    new = _store(app, org_name, org_domain, app_name)
    if new.value(_DONE_KEY) is not None or _own_keys(new).contains('Mode'):
        return 0  # already migrated, or the user already has settings here
    old = _own_keys(_store(app, LEGACY_ORG_NAME, LEGACY_ORG_DOMAIN, legacy_app_name))
    keys = old.allKeys()
    if not keys:
        return 0
    for key in keys:
        new.setValue(key, old.value(key))
    new.setValue(_DONE_KEY, 1)
    new.sync()
    return len(keys)


# Stores the fork used to open by hand, outside the application identity, each
# landing in its own file. Their keys are namespaced, so they fold into the main
# store without collision. (organization, application) as passed to QSettings().
_ADHOC_STORES = (
    ('Artisan', 'TilauScope'),      # displayscope — interface/swap_events_control
    ('TilauScope', 'TilauLogger'),  # tilaulogger  — tilaulogger/*
)


def _absorb_adhoc_stores(app, org_name: str, org_domain: str, app_name: str) -> int:
    """Fold the hand-rolled stores into the main one. Returns keys carried.

    Without this the two settings they hold silently reset to their defaults:
    the swapped-control layout, and the logger's serial port, baud rate and
    panel state. Copy-only, like everything else here.
    """
    main = _store(app, org_name, org_domain, app_name)
    carried = 0
    for org, application in _ADHOC_STORES:
        try:
            old = _own_keys(QSettings(org, application))
            for key in old.allKeys():
                if not main.contains(key):   # never overwrite a newer value
                    main.setValue(key, old.value(key))
                    carried += 1
        except Exception:  # pylint: disable=broad-except
            _log.exception('could not absorb the %s/%s store', org, application)
    if carried:
        main.sync()
    return carried


def _data_dir(app, org_name: str, app_name: str) -> str:
    keep = (app.organizationName(), app.applicationName())
    app.setOrganizationName(org_name)
    app.setApplicationName(app_name)
    path = QStandardPaths.standardLocations(
        QStandardPaths.StandardLocation.AppLocalDataLocation)[0]
    app.setOrganizationName(keep[0])
    app.setApplicationName(keep[1])
    return path


def _copy_data_directory(app, org_name: str, app_name: str) -> str | None:
    """Copy the application-support tree across. Returns the target, or None.

    This holds uuids.db, the sync database and the paired-phone records — losing
    it would look to the user like the roast history and every pairing vanished.
    """
    src = _data_dir(app, LEGACY_ORG_NAME, LEGACY_APP_NAME)
    dst = _data_dir(app, org_name, app_name)
    if src == dst or not os.path.isdir(src) or os.path.isdir(dst):
        return None
    os.makedirs(dst, exist_ok=True)
    for entry in os.scandir(src):
        if entry.name.endswith(_SKIP_SUFFIXES):
            continue
        target = os.path.join(dst, entry.name)
        try:
            if entry.is_dir():
                shutil.copytree(entry.path, target, dirs_exist_ok=True)
            else:
                shutil.copy2(entry.path, target)
        except Exception:  # pylint: disable=broad-except
            _log.exception('could not copy %s', entry.path)
    return dst


def migrate_identity(app: QCoreApplication | None = None) -> bool:
    """Carry settings and data onto the TilauScope identity. Idempotent.

    Must run before anything reads QSettings() or calls getDataDirectory() —
    the latter memoises its result, so a late call would pin the old path for
    the whole session. Never raises: a failed migration must not stop the app
    from starting, it only means this launch still looks empty.
    """
    from artisanlib.util import (application_name, application_organization_name,
                                 application_viewer_name)
    from artisanlib.util import application_organization_domain as org_domain

    if app is None:
        app = QCoreApplication.instance()
    if app is None:
        return False
    if application_organization_name == LEGACY_ORG_NAME and application_name == LEGACY_APP_NAME:
        return False  # identity not renamed — nothing to carry

    migrated = False
    try:
        copied = _copy_settings(app, application_name, LEGACY_APP_NAME,
                                application_organization_name, org_domain)
        if copied:
            _log.info('migrated %d settings keys onto the TilauScope identity', copied)
            migrated = True
        # The viewer keeps its own store; carry it with the same rules.
        _copy_settings(app, application_viewer_name, LEGACY_VIEWER_NAME,
                       application_organization_name, org_domain)
        carried = _absorb_adhoc_stores(app, application_organization_name,
                                       org_domain, application_name)
        if carried:
            _log.info('absorbed %d keys from the hand-rolled stores', carried)
            migrated = True
    except Exception:  # pylint: disable=broad-except
        _log.exception('settings migration failed')

    try:
        dst = _copy_data_directory(app, application_organization_name, application_name)
        if dst:
            _log.info('copied the application data directory to %s', dst)
            migrated = True
    except Exception:  # pylint: disable=broad-except
        _log.exception('data directory migration failed')

    return migrated


# ─────────────────────────────────────────────────────────────────────────────
# Credentials out of the settings file and into the OS keychain
# ─────────────────────────────────────────────────────────────────────────────

# Where the AI key and the broker password used to sit. Both groups exist
# because the settings are written once at the top level and once under
# Device — so a secret left behind in either is a secret still on disk.
_AI_KEYS: tuple[str, ...] = ('tilauai', 'Device/tilauai')
_MQTT_KEYS: tuple[str, ...] = ('tilaumqttbridge', 'Device/tilaumqttbridge')


def _plain(entry: dict, encoded_field: str, clear_field: str) -> str:
    """The credential in one settings dict, whichever form it was left in."""
    import base64

    encoded = entry.get(encoded_field) or ''
    if encoded:
        try:
            return base64.b64decode(encoded).decode('utf-8')
        except Exception:  # noqa: BLE001
            pass
    return entry.get(clear_field) or ''


def migrate_secrets_to_keyring(settings: QSettings | None = None) -> None:
    """Move stored credentials into the keychain and strip them from settings.

    Before this release the AI key and the broker password were kept in the
    settings — base64 for one copy, cleartext for the other. That file is also
    what Artisan writes into an exported ``.aset``, so a shared machine setup
    carried the operator's credentials with it.

    Runs on every launch and is a no-op once there is nothing left to move.
    Never removes a credential it did not manage to store somewhere first.
    """
    from tilauscope.tilau_secrets import ai_account, mqtt_account, set_secret

    # The argument exists so this can be pointed at a copy of a real settings
    # file and its effect read before it is let loose on the original.
    if settings is None:
        settings = QSettings()
    moved = 0

    for key in _AI_KEYS:
        entry = settings.value(key, None)
        if not isinstance(entry, dict):
            continue
        secret = _plain(entry, 'apikey_encoded', '_apikey')
        client_id = entry.get('client_id') or 'google'
        if secret and not set_secret(ai_account(str(client_id)), secret):
            _log.warning('keychain refused the AI key; leaving %s alone', key)
            continue
        if _strip(settings, key, entry, ('apikey_encoded', '_apikey')):
            moved += 1

    for key in _MQTT_KEYS:
        entry = settings.value(key, None)
        if not isinstance(entry, dict):
            continue
        secret = _plain(entry, 'password_encoded', '_password')
        user = _plain(entry, 'username_encoded', '_username')
        host = entry.get('broker_url') or ''
        port = entry.get('port') or 1883
        if secret and not set_secret(mqtt_account(user, str(host), port), secret):
            _log.warning('keychain refused the broker password; leaving %s alone', key)
            continue
        if _strip(settings, key, entry, ('password_encoded', '_password')):
            moved += 1

    if moved:
        settings.sync()
        _log.info('moved credentials out of the settings file in %d group(s)', moved)


def _strip(settings: QSettings, key: str, entry: dict, fields: tuple[str, ...]) -> bool:
    """Rewrite one settings group without its credential fields."""
    if not any(entry.get(f) for f in fields):
        return False
    cleaned = {k: v for k, v in entry.items() if k not in fields}
    settings.setValue(key, cleaned)
    return True
