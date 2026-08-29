from __future__ import annotations

import io
import zipfile
from pathlib import Path

from tilauscope.tilau_exceptions import (
    _sanitized_archive_filename,
    _write_sanitized_log,
    sanitize_log_text,
)


def test_sanitize_log_text_removes_personal_data_and_secrets() -> None:
    raw = (
        'operator="Jane Roaster" organization=Private Coffee Ltd\n'
        'email=jane@example.com api_key=sk-private-key password="coffee-secret"\n'
        'File "/Users/jane/Clients/Private Coffee/profile.alog", line 42\n'
        r'Windows C:\Users\jane\Clients\Private Coffee\profile.alog' '\n'
        'request https://supplier.example/bean?customer=Jane from 192.168.1.24\n'
        'listener=[fe80::aede:48ff:fe00:1122] directory=/Volumes/Private/client\n'
        'device=00:11:22:33:44:55 id=550e8400-e29b-41d4-a716-446655440000\n'
        'host Jane-MacBook user jane\n'
    )

    cleaned = sanitize_log_text(raw, ('Jane Roaster', 'Private Coffee Ltd',
                                      'Jane-MacBook', 'jane'))

    for private_value in (
            'Jane Roaster', 'Private Coffee Ltd', 'jane@example.com',
            'sk-private-key', 'coffee-secret', '/Users/jane', r'C:\Users\jane',
            'supplier.example', '192.168.1.24', '00:11:22:33:44:55',
            'fe80::aede:48ff:fe00:1122', '/Volumes/Private/client',
            '550e8400-e29b-41d4-a716-446655440000', 'Jane-MacBook'):
        assert private_value.lower() not in cleaned.lower()

    assert '[REDACTED_PERSONAL]' in cleaned
    assert '[REDACTED_SECRET]' in cleaned
    assert '[REDACTED_PATH]' in cleaned
    assert '[REDACTED_URL]' in cleaned
    assert '[REDACTED_IP]' in cleaned


def test_archive_filename_is_sanitized() -> None:
    assert 'jane' not in _sanitized_archive_filename(
        'diagnostic-jane.log', ('jane',)
    ).lower()


def test_log_is_sanitized_before_it_is_written_to_zip(tmp_path: Path) -> None:
    log = tmp_path / 'artisan.log'
    log.write_text(
        'operator=Jane Roaster path=/Users/jane/private.alog '
        'token=super-secret-token\n',
        encoding='utf-8',
    )
    archive = io.BytesIO()

    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipf:
        _write_sanitized_log(zipf, log, 'logs/artisan.log', ('Jane Roaster',))

    with zipfile.ZipFile(archive, 'r') as zipf:
        exported = zipf.read('logs/artisan.log').decode('utf-8')

    assert 'Jane Roaster' not in exported
    assert '/Users/jane' not in exported
    assert 'super-secret-token' not in exported
    assert '[REDACTED_PERSONAL]' in exported
    assert '[REDACTED_PATH]' in exported
    assert '[REDACTED_SECRET]' in exported
