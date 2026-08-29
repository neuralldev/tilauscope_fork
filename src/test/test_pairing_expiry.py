"""A device token is kept alive by being used, not by having once existed.

Before this, a phone paired once stayed authorised for ever — sold, lost or
simply forgotten. Revocation was the only way out, and the desktop showed only
the pairing date, so nothing distinguished the phone in daily use from the one
retired eight months ago.
"""

from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import QSettings

from tilauscope.pairing import _DT_IDLE_TTL, _LAST_SEEN_RESOLUTION, PairingManager

DAY = 86400


@pytest.fixture
def manager():
    QSettings().remove('tilauscope/remote_devices')
    yield PairingManager()
    QSettings().remove('tilauscope/remote_devices')


def _pair(mgr: PairingManager, device_id: str = 'phone-a') -> str:
    token, _ttl = mgr.mint_pairing_token()
    dt = mgr.pair(token, device_id, 'Tilau iPhone')
    assert dt, 'pairing failed to issue a token'
    return dt


def _age(mgr: PairingManager, device_id: str, seconds: int) -> None:
    """Backdate a device's last connection."""
    with mgr._lock:                       # noqa: SLF001 - the test owns the manager
        mgr._devices[device_id]['last_seen'] = int(time.time()) - seconds
        mgr._save(mgr._devices)


# ── the token still works while the phone is in use ──────────────────────────

def test_a_device_in_use_keeps_working(manager) -> None:
    dt = _pair(manager)
    assert manager.verify_token('phone-a', dt) is True

    _age(manager, 'phone-a', _DT_IDLE_TTL - DAY)
    assert manager.verify_token('phone-a', dt) is True, (
        'a device used within the limit was refused')


def test_connecting_restarts_the_clock(manager) -> None:
    """Using the phone is what keeps it paired."""
    dt = _pair(manager)
    _age(manager, 'phone-a', _DT_IDLE_TTL - DAY)
    assert manager.verify_token('phone-a', dt) is True

    _age(manager, 'phone-a', _DT_IDLE_TTL - DAY)
    assert manager.verify_token('phone-a', dt) is True
    assert manager.list_devices()['phone-a']['last_seen'] > 0


# ── and stops when it goes quiet ─────────────────────────────────────────────

def test_a_device_silent_for_a_month_is_refused(manager) -> None:
    dt = _pair(manager)
    _age(manager, 'phone-a', _DT_IDLE_TTL + DAY)

    assert manager.verify_token('phone-a', dt) is False, (
        'a token that has not been used for a month still opened the roaster')


def test_an_expired_device_is_forgotten_not_merely_refused(manager) -> None:
    """Refusing but keeping it would leave a dead row nobody can interpret."""
    dt = _pair(manager)
    _age(manager, 'phone-a', _DT_IDLE_TTL + DAY)
    manager.verify_token('phone-a', dt)

    assert 'phone-a' not in manager.list_devices()


def test_expiry_survives_a_restart(manager) -> None:
    dt = _pair(manager)
    _age(manager, 'phone-a', _DT_IDLE_TTL + DAY)

    restarted = PairingManager()          # what the next launch builds
    assert restarted.verify_token('phone-a', dt) is False
    assert 'phone-a' not in restarted.list_devices()


def test_the_sweep_forgets_only_the_idle_ones(manager) -> None:
    live = _pair(manager, 'phone-live')
    _pair(manager, 'phone-old')
    _age(manager, 'phone-old', _DT_IDLE_TTL + DAY)

    assert manager.sweep_expired() == 1
    assert sorted(manager.list_devices()) == ['phone-live']
    assert manager.verify_token('phone-live', live) is True


# ── the upgrade must not punish a phone in daily use ─────────────────────────

def test_an_installation_upgrading_starts_the_clock_now(manager) -> None:
    """A device paired long ago but used yesterday must not vanish on upgrade.

    Before this release nothing recorded when a device last connected, so the
    pairing date is all an upgrade has — and reading it as a last sign of life
    would expire exactly the phone the operator uses every day.
    """
    dt = _pair(manager)
    with manager._lock:                   # noqa: SLF001 - simulate the old shape
        dev = manager._devices['phone-a']
        dev.pop('last_seen', None)
        dev['paired_at'] = int(time.time()) - (_DT_IDLE_TTL + 60 * DAY)
        manager._save(manager._devices)

    upgraded = PairingManager()
    assert upgraded.verify_token('phone-a', dt) is True, (
        'the upgrade expired a device whose real activity it cannot know')


# ── the settings file is not rewritten on every handshake ────────────────────

def test_a_reconnect_burst_does_not_rewrite_the_settings(manager, monkeypatch) -> None:
    """A flaky link reconnects constantly; each one must not cost a disk write."""
    dt = _pair(manager)
    saves = []
    monkeypatch.setattr(PairingManager, '_save',
                        staticmethod(lambda _devices: saves.append(1)))

    for _ in range(20):
        assert manager.verify_token('phone-a', dt) is True
    assert not saves, f'{len(saves)} settings writes for 20 reconnects'


def test_a_connection_after_a_long_gap_is_recorded(manager) -> None:
    dt = _pair(manager)
    _age(manager, 'phone-a', _LAST_SEEN_RESOLUTION + 60)
    before = manager.list_devices()['phone-a']['last_seen']

    assert manager.verify_token('phone-a', dt) is True
    assert manager.list_devices()['phone-a']['last_seen'] > before


# ── none of this weakens what already worked ─────────────────────────────────

def test_a_wrong_token_is_still_refused(manager) -> None:
    _pair(manager)
    assert manager.verify_token('phone-a', 'dt_not-the-one') is False


def test_a_revoked_device_is_still_refused(manager) -> None:
    dt = _pair(manager)
    manager.revoke('phone-a')
    assert manager.verify_token('phone-a', dt) is False


def test_an_unknown_device_is_still_refused(manager) -> None:
    assert manager.verify_token('nobody', 'dt_whatever') is False


def test_the_pairing_token_is_still_one_time(manager) -> None:
    token, _ttl = manager.mint_pairing_token()
    assert manager.pair(token, 'phone-a', 'A')
    assert manager.pair(token, 'phone-b', 'B') is None
