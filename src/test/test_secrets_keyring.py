"""Credentials belong in the OS keychain, not in the settings file.

The settings file is also what Artisan writes into an exported ``.aset`` — the
normal way an operator shares a machine setup. A credential left in there
travels with it, which is the leak these tests exist to keep closed.
"""

from __future__ import annotations

import base64

import pytest
from PyQt6.QtCore import QSettings

from tilauscope import tilau_secrets
from tilauscope.tilau_secrets import (
    ai_account, delete_secret, get_secret, mqtt_account, set_secret,
)

KEY = 'AIzaSyTHIS-IS-NOT-A-REAL-KEY-000000000000'
PWD = 'correct-horse-battery-staple'


class _Keychain:
    """An in-memory stand-in for the OS keychain."""

    def __init__(self, broken: bool = False) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.broken = broken

    def _check(self) -> None:
        if self.broken:
            raise RuntimeError('the user denied access to the keychain')

    def set_password(self, service, account, value):
        self._check()
        self.store[(service, account)] = value

    def get_password(self, service, account):
        self._check()
        return self.store.get((service, account))

    def delete_password(self, service, account):
        self._check()
        self.store.pop((service, account), None)


@pytest.fixture
def keychain(monkeypatch):
    """A keychain that works, wired under the lazy `import keyring`."""
    import keyring

    fake = _Keychain()
    monkeypatch.setattr(keyring, 'set_password', fake.set_password)
    monkeypatch.setattr(keyring, 'get_password', fake.get_password)
    monkeypatch.setattr(keyring, 'delete_password', fake.delete_password)
    tilau_secrets._session.clear()
    yield fake
    tilau_secrets._session.clear()


@pytest.fixture
def broken_keychain(monkeypatch):
    import keyring

    fake = _Keychain(broken=True)
    monkeypatch.setattr(keyring, 'set_password', fake.set_password)
    monkeypatch.setattr(keyring, 'get_password', fake.get_password)
    monkeypatch.setattr(keyring, 'delete_password', fake.delete_password)
    tilau_secrets._session.clear()
    yield fake
    tilau_secrets._session.clear()


# ── the store itself ─────────────────────────────────────────────────────────

@pytest.mark.usefixtures('keychain')
def test_a_credential_round_trips_through_the_keychain() -> None:
    assert set_secret('ai:google', KEY) is True
    assert get_secret('ai:google') == KEY
    delete_secret('ai:google')
    assert get_secret('ai:google') == ''


def test_accounts_are_named_so_a_human_can_recognise_them() -> None:
    assert ai_account('anthropic') == 'ai:anthropic'
    assert mqtt_account('jeedom', '192.168.1.9', 1883) == 'mqtt:jeedom@192.168.1.9:1883'


@pytest.mark.usefixtures('broken_keychain')
def test_a_refused_keychain_keeps_the_session_working() -> None:
    """A denied prompt must not stop a roast — but must not reach the disk."""
    assert set_secret('ai:google', KEY) is False
    assert get_secret('ai:google') == KEY, 'the session lost a key it was given'
    assert tilau_secrets.last_error(), 'the failure was not reported'


@pytest.mark.usefixtures('broken_keychain')
def test_a_refused_keychain_writes_nothing_anywhere_persistent() -> None:
    set_secret('ai:google', KEY)
    leaked = [k for k in QSettings().allKeys() if KEY in str(QSettings().value(k))]
    assert not leaked, f'the fallback persisted a credential: {leaked}'


@pytest.mark.usefixtures('keychain')
def test_storing_an_empty_value_forgets_the_credential() -> None:
    set_secret('ai:google', KEY)
    set_secret('ai:google', '')
    assert get_secret('ai:google') == ''


# ── the AI key ───────────────────────────────────────────────────────────────

@pytest.mark.usefixtures('keychain')
def test_the_ai_config_never_serialises_its_key() -> None:
    from tilauscope.ai_support import TilauAIConfig

    cfg = TilauAIConfig(client_id='google', engine='google/gemini-2.5-flash')
    cfg.apikey = KEY

    body = str(cfg.to_dict())
    assert KEY not in body, 'the key is written to the settings in cleartext'
    assert base64.b64encode(KEY.encode()).decode() not in body, (
        'the key is written to the settings in base64 — an encoding, not a cipher')
    assert 'apikey' not in cfg.to_dict(), 'a key field still reaches the settings'
    assert cfg.to_dict()['engine'] == 'google/gemini-2.5-flash', (
        'the settings lost what they are supposed to keep')


@pytest.mark.usefixtures('keychain')
def test_the_ai_key_survives_a_restart_through_the_keychain() -> None:
    from tilauscope.ai_support import TilauAIConfig

    cfg = TilauAIConfig(client_id='anthropic', engine='anthropic/claude')
    cfg.apikey = KEY

    # What a restart does: rebuild from the settings alone.
    revived = TilauAIConfig.from_dict(cfg.to_dict())
    assert revived.apikey == KEY


@pytest.mark.usefixtures('keychain')
def test_each_provider_keeps_its_own_key() -> None:
    """Switching provider and back must not throw the first key away."""
    from tilauscope.ai_support import TilauAIConfig

    google = TilauAIConfig(client_id='google')
    google.apikey = KEY
    anthropic = TilauAIConfig(client_id='anthropic')
    anthropic.apikey = 'sk-ant-other'

    assert TilauAIConfig(client_id='google').apikey == KEY
    assert TilauAIConfig(client_id='anthropic').apikey == 'sk-ant-other'


def test_a_key_left_in_old_settings_is_adopted_and_dropped(keychain) -> None:
    """The upgrade path: read the legacy field once, then never write it."""
    from tilauscope.ai_support import TilauAIConfig

    legacy = {'client_id': 'google', 'engine': 'google/gemini-2.0-flash',
              'apikey_encoded': base64.b64encode(KEY.encode()).decode()}
    cfg = TilauAIConfig.from_dict(legacy)

    assert cfg.apikey == KEY, 'the upgrade lost the operator key'
    assert keychain.store[('TilauScope', 'ai:google')] == KEY
    assert KEY not in str(cfg.to_dict())
    assert base64.b64encode(KEY.encode()).decode() not in str(cfg.to_dict())


@pytest.mark.usefixtures('keychain')
def test_no_key_anywhere_reads_as_no_key() -> None:
    from tilauscope.ai_support import TilauAIConfig

    assert TilauAIConfig(client_id='google').apikey == ''


# ── the broker password ──────────────────────────────────────────────────────

@pytest.mark.usefixtures('keychain')
def test_the_mqtt_config_never_serialises_its_password() -> None:
    from tilauscope.mqttbridge import MQTTConfig

    cfg = MQTTConfig(broker_url='192.168.1.9', port=1883)
    cfg.username = 'jeedom'
    cfg.password = PWD

    body = str(cfg.to_dict())
    assert PWD not in body
    assert base64.b64encode(PWD.encode()).decode() not in body
    assert 'password' not in cfg.to_dict()
    assert cfg.to_dict()['broker_url'] == '192.168.1.9'


@pytest.mark.usefixtures('keychain')
def test_the_broker_password_survives_a_restart() -> None:
    from tilauscope.mqttbridge import MQTTConfig

    cfg = MQTTConfig(broker_url='192.168.1.9', port=1883)
    cfg.username = 'jeedom'
    cfg.password = PWD

    revived = MQTTConfig.from_dict(cfg.to_dict())
    assert revived.password == PWD


def test_a_password_left_in_old_settings_is_adopted_and_dropped(keychain) -> None:
    from tilauscope.mqttbridge import MQTTConfig

    legacy = {'broker_url': '192.168.1.9', 'port': 1883,
              'username_encoded': base64.b64encode(b'jeedom').decode(),
              'password_encoded': base64.b64encode(PWD.encode()).decode()}
    cfg = MQTTConfig.from_dict(legacy)

    assert cfg.password == PWD
    assert keychain.store[('TilauScope', 'mqtt:jeedom@192.168.1.9:1883')] == PWD
    assert PWD not in str(cfg.to_dict())


# ── the one-shot migration of an existing installation ───────────────────────

def _seed_legacy_settings() -> QSettings:
    s = QSettings()
    for key in ('tilauai', 'Device/tilauai'):
        s.setValue(key, {'client_id': 'google', 'engine': 'google/gemini-2.0-flash',
                         'apikey_encoded': base64.b64encode(KEY.encode()).decode(),
                         '_apikey': KEY})
    for key in ('tilaumqttbridge', 'Device/tilaumqttbridge'):
        s.setValue(key, {'broker_url': '192.168.1.9', 'port': 1883,
                         'username_encoded': base64.b64encode(b'jeedom').decode(),
                         '_username': 'jeedom',
                         'password_encoded': base64.b64encode(PWD.encode()).decode(),
                         '_password': PWD})
    s.sync()
    return s


@pytest.mark.usefixtures('keychain')
def test_the_migration_empties_the_settings_file_of_credentials() -> None:
    from tilauscope.settings_migration import migrate_secrets_to_keyring

    _seed_legacy_settings()
    migrate_secrets_to_keyring()

    s = QSettings()
    for key in ('tilauai', 'Device/tilauai', 'tilaumqttbridge', 'Device/tilaumqttbridge'):
        body = str(s.value(key))
        assert KEY not in body, f'{key} still holds the AI key'
        assert PWD not in body, f'{key} still holds the broker password'
        assert base64.b64encode(KEY.encode()).decode() not in body
        assert base64.b64encode(PWD.encode()).decode() not in body


def test_the_migration_keeps_the_credentials_it_moved(keychain) -> None:
    from tilauscope.settings_migration import migrate_secrets_to_keyring

    _seed_legacy_settings()
    migrate_secrets_to_keyring()

    assert keychain.store[('TilauScope', 'ai:google')] == KEY
    assert keychain.store[('TilauScope', 'mqtt:jeedom@192.168.1.9:1883')] == PWD


@pytest.mark.usefixtures('keychain')
def test_the_migration_keeps_everything_that_is_not_a_credential() -> None:
    from tilauscope.settings_migration import migrate_secrets_to_keyring

    _seed_legacy_settings()
    migrate_secrets_to_keyring()

    s = QSettings()
    assert s.value('tilauai')['engine'] == 'google/gemini-2.0-flash'
    assert s.value('tilaumqttbridge')['broker_url'] == '192.168.1.9'
    assert s.value('tilaumqttbridge')['username_encoded'], 'the login was dropped too'


@pytest.mark.usefixtures('broken_keychain')
def test_the_migration_leaves_the_settings_alone_when_the_keychain_refuses() -> None:
    """Never remove a credential that could not be stored somewhere first."""
    from tilauscope.settings_migration import migrate_secrets_to_keyring

    _seed_legacy_settings()
    migrate_secrets_to_keyring()

    assert KEY in str(QSettings().value('tilauai')), (
        'the key was deleted from the settings without ever reaching a keychain')


@pytest.mark.usefixtures('keychain')
def test_running_the_migration_twice_changes_nothing() -> None:
    from tilauscope.settings_migration import migrate_secrets_to_keyring

    _seed_legacy_settings()
    migrate_secrets_to_keyring()
    after_once = {k: QSettings().value(k) for k in ('tilauai', 'tilaumqttbridge')}
    migrate_secrets_to_keyring()

    assert {k: QSettings().value(k) for k in ('tilauai', 'tilaumqttbridge')} == after_once


# ── the keychain is not touched for nothing ──────────────────────────────────
#
# Every keychain access can put an approval dialog in front of the operator —
# macOS ties permission to the binary asking, so a rebuild, or running from
# source, starts asking again. An access that changes nothing is therefore not
# merely wasted work, it is a prompt the operator has to answer.

class _Counting(_Keychain):
    def __init__(self) -> None:
        super().__init__()
        self.ops: list[str] = []

    def set_password(self, service, account, value):
        self.ops.append(f'write {account}')
        super().set_password(service, account, value)

    def get_password(self, service, account):
        self.ops.append(f'read {account}')
        return super().get_password(service, account)

    def delete_password(self, service, account):
        self.ops.append(f'delete {account}')
        super().delete_password(service, account)


@pytest.fixture
def counting(monkeypatch):
    import keyring

    fake = _Counting()
    monkeypatch.setattr(keyring, 'set_password', fake.set_password)
    monkeypatch.setattr(keyring, 'get_password', fake.get_password)
    monkeypatch.setattr(keyring, 'delete_password', fake.delete_password)
    tilau_secrets._session.clear()
    yield fake
    tilau_secrets._session.clear()


def test_reading_a_credential_twice_asks_the_keychain_once(counting) -> None:
    from tilauscope.ai_support import TilauAIConfig

    cfg = TilauAIConfig(client_id='google')
    cfg.apikey = KEY
    counting.ops.clear()

    for _ in range(5):
        assert cfg.apikey == KEY
    assert counting.ops == [], 'a cached key still went to the keychain'


def test_saving_an_unchanged_password_touches_nothing(counting) -> None:
    """The settings dialog writes every field back on OK, changed or not."""
    from tilauscope.mqttbridge import MQTTConfig

    cfg = MQTTConfig(broker_url='192.168.1.9', port=1883)
    cfg.username = 'jeedom'
    cfg.password = PWD
    counting.ops.clear()

    for _ in range(3):          # open the dialog, press OK, three times over
        assert cfg.password == PWD
        cfg.password = PWD
    assert counting.ops == [], (
        f'pressing OK cost {len(counting.ops)} keychain accesses: {counting.ops}')


def test_saving_an_unchanged_ai_key_touches_nothing(counting) -> None:
    from tilauscope.ai_support import TilauAIConfig

    cfg = TilauAIConfig(client_id='google')
    cfg.apikey = KEY
    counting.ops.clear()

    cfg.apikey = KEY
    assert counting.ops == []


def test_a_real_change_is_still_written(counting) -> None:
    from tilauscope.mqttbridge import MQTTConfig

    cfg = MQTTConfig(broker_url='192.168.1.9', port=1883)
    cfg.username = 'jeedom'
    cfg.password = PWD
    counting.ops.clear()

    cfg.password = 'a-new-one'
    assert any(op.startswith('write') for op in counting.ops)
    assert cfg.password == 'a-new-one'


def test_clearing_a_credential_is_still_a_change(counting) -> None:
    from tilauscope.ai_support import TilauAIConfig

    cfg = TilauAIConfig(client_id='google')
    cfg.apikey = KEY
    counting.ops.clear()

    cfg.apikey = ''
    assert any(op.startswith('delete') for op in counting.ops)
    assert cfg.apikey == ''
