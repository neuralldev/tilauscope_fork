"""The QR diagnostic keeps camera frames out of a shared, guessable path.

Scanned frames normally stay in memory. ``TILAU_QR_DEBUG`` is the one path that
writes one to disk, and a frame holds whatever the lens was pointed at — a
kitchen, a face, a document held up to it — not merely the label. So the file
gets an unguessable name in a private directory, owner-only permissions, and a
life no longer than the scan window unless the operator asks otherwise.
"""

from __future__ import annotations

import stat
import tempfile
from pathlib import Path

import pytest

from tilauscope.qr_scan import ScanQRDialog, qr_debug_mode


class _Scanner:
    """The snapshot plumbing on its own — no Qt dialog, no camera."""

    _debug_dir: Path | None = None

    _debug_dir_path = ScanQRDialog._debug_dir_path
    _discard_debug_dir = ScanQRDialog._discard_debug_dir
    _write_debug_snapshot = ScanQRDialog._write_debug_snapshot


@pytest.fixture
def scanner(monkeypatch):
    monkeypatch.delenv('TILAU_QR_DEBUG', raising=False)
    obj = _Scanner()
    yield obj
    directory = obj._debug_dir
    if directory is not None and directory.exists():
        import shutil
        shutil.rmtree(directory, ignore_errors=True)


# ── reading the flag ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw', ['', '0', 'false', 'no', 'off', '  OFF  '])
def test_the_diagnostic_is_off_by_default(monkeypatch, raw) -> None:
    monkeypatch.setenv('TILAU_QR_DEBUG', raw)
    assert qr_debug_mode() == ''


def test_an_unset_variable_is_off(monkeypatch) -> None:
    monkeypatch.delenv('TILAU_QR_DEBUG', raising=False)
    assert qr_debug_mode() == ''


@pytest.mark.parametrize('raw', ['1', 'true', 'yes', 'on', 'anything'])
def test_any_truthy_value_gives_the_transient_mode(monkeypatch, raw) -> None:
    """The documented ``=1`` must be the safe one, not the persistent one."""
    monkeypatch.setenv('TILAU_QR_DEBUG', raw)
    assert qr_debug_mode() == 'session'


@pytest.mark.parametrize('raw', ['keep', 'KEEP', ' Keep '])
def test_keeping_the_frame_is_spelled_out(monkeypatch, raw) -> None:
    monkeypatch.setenv('TILAU_QR_DEBUG', raw)
    assert qr_debug_mode() == 'keep'


# ── where the frame lands ────────────────────────────────────────────────────

def test_the_directory_is_private_and_unguessable(scanner) -> None:
    directory = scanner._debug_dir_path()
    assert directory is not None and directory.is_dir()
    mode = stat.S_IMODE(directory.stat().st_mode)
    assert mode == 0o700, f'{directory} is {oct(mode)}, not owner-only'
    assert 'tilauscope_qr_debug.png' not in str(directory)


def test_two_sessions_do_not_share_a_path(scanner) -> None:
    first = scanner._debug_dir_path()
    other = _Scanner()
    try:
        assert other._debug_dir_path() != first
    finally:
        other._discard_debug_dir()


def test_the_directory_is_made_once_per_session(scanner) -> None:
    assert scanner._debug_dir_path() == scanner._debug_dir_path()


def test_the_written_frame_is_readable_by_nobody_else(scanner) -> None:
    numpy = pytest.importorskip('numpy')
    pytest.importorskip('PIL')
    scanner._write_debug_snapshot(numpy.zeros((8, 8), dtype=numpy.uint8))
    snapshot = scanner._debug_dir / 'decoder-view.png'
    assert snapshot.exists()
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600


# ── how long it lives ────────────────────────────────────────────────────────

def test_the_frame_does_not_outlive_the_scan_window(scanner) -> None:
    directory = scanner._debug_dir_path()
    (directory / 'decoder-view.png').write_bytes(b'not really a png')
    scanner._discard_debug_dir()
    assert not directory.exists()
    assert scanner._debug_dir is None


def test_keeping_the_frame_takes_an_explicit_request(monkeypatch, scanner) -> None:
    monkeypatch.setenv('TILAU_QR_DEBUG', 'keep')
    directory = scanner._debug_dir_path()
    (directory / 'decoder-view.png').write_bytes(b'not really a png')
    scanner._discard_debug_dir()
    assert directory.exists(), 'TILAU_QR_DEBUG=keep asked for it to stay'
    assert scanner._debug_dir == directory, 'a restart must not strew directories'


def test_discarding_twice_is_harmless(scanner) -> None:
    scanner._debug_dir_path()
    scanner._discard_debug_dir()
    scanner._discard_debug_dir()


def test_discarding_before_anything_was_written_is_harmless(scanner) -> None:
    scanner._discard_debug_dir()
    assert scanner._debug_dir is None


def test_a_kept_frame_is_announced_in_the_log(monkeypatch, scanner, caplog) -> None:
    """Left on disk without a word is how it gets forgotten."""
    monkeypatch.setenv('TILAU_QR_DEBUG', 'keep')
    directory = scanner._debug_dir_path()
    with caplog.at_level('WARNING', logger='tilauscope.qr_scan'):
        scanner._discard_debug_dir()
    assert str(directory) in caplog.text


def test_the_frame_never_sits_directly_in_the_shared_temp_directory(scanner) -> None:
    """The old bug in one line: a fixed name under gettempdir()."""
    numpy = pytest.importorskip('numpy')
    pytest.importorskip('PIL')
    scanner._write_debug_snapshot(numpy.zeros((8, 8), dtype=numpy.uint8))
    shared = Path(tempfile.gettempdir())
    snapshot = scanner._debug_dir / 'decoder-view.png'
    assert snapshot.parent != shared, 'back to a path anyone can guess'
    assert not (shared / 'tilauscope_qr_debug.png').exists()
