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

"""BeanCave is actually opened here, in a child, and reported back as JSON.

Nothing else in the suite constructs the dialog. That is how a split which moved
``load_parameters`` one package deeper shipped: the parameter file was looked
for in the wrong folder, the read logged and returned, and the failure surfaced
hundreds of lines away as a KeyError on an empty dictionary.

It runs in a child for the same reason the codec checks do, and one more:
opening BeanCave imports ``artisanlib.main``, and in a process where another
TilauScope is running that import *registers this process as the ArtisanViewer*.
Done in the pytest process, every later subprocess that imports Artisan then
sees an app **and** a viewer already running and calls ``sys.exit(0)`` — so a
developer with the application open would watch two dozen unrelated tests fail.

Run directly for a quick look: ``python test/beancave_child.py``.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest.mock import MagicMock

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))          # _guard and friends
sys.path.insert(0, str(_HERE.parent))   # the `tilauscope` package itself

import _guard  # noqa: E402  # before anything can touch Qt settings

CHECKS: dict[str, object] = {}


def check(fn):  # noqa: ANN001, ANN201
    CHECKS[fn.__name__] = fn
    return fn


_CORPUS = _HERE / 'fixtures' / 'corpus'

#: Alphabetically first (March) and most recent (August), so "row 0" and "the
#: latest roast" are never the same row.
OLDEST_BY_NAME = '74110 GR2 - Natural  Dry Process - 2025_26-03-07_0847.alog'
MIDDLE = 'Barazilie - Anaerobic Fermentation - 2025_26-06-28_1037.alog'
NEWEST = 'Ethiopia Hambela Benti Nenka_26-08-03_1902.alog'
THREE = (OLDEST_BY_NAME, MIDDLE, NEWEST)

#: Modules that can raise a styled dialog while BeanCave is being built. One
#: opening here would block the offscreen run forever, so each is redirected to
#: a recorder and the dialogs become an assertion instead of a hang.
_DIALOG_SITES = ('lifecycle', 'bean_tab', 'ambient', 'printing', 'viewer_plot', 'widgets')

_dialogs_raised: list[str] = []
_built: list[tuple] = []
_tmp = Path()


def _no_dialog(_parent, title='', message='', *_a, **_k):  # noqa: ANN001, ANN002, ANN003, ANN202
    _dialogs_raised.append(f'{title}: {message}')
    return 0


def roast_uuid(filename: str) -> str:
    """The roastUUID Artisan wrote into a corpus fixture."""
    return ast.literal_eval((_CORPUS / filename).read_text(encoding='utf-8'))['roastUUID']


def selected(dlg) -> str:  # noqa: ANN001
    from PyQt6.QtCore import Qt

    item = dlg.roast_list_widget.currentItem()
    return (item.data(Qt.ItemDataRole.UserRole) or {}).get('raw_fname', '') if item else ''


def open_beancave(*, roasts: tuple[str, ...] = (), last_roast_uuid: str = '',
                  cur_file: str = ''):  # noqa: ANN202
    """Build BeanCave on a folder of real roasts and let its deferred work land."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QWidget

    from tilauscope.beancave import BeancaveDlg
    from tilauscope.tilauscope_types import BeanCaveContainer, GreenBean

    app = QApplication.instance() or QApplication([])

    home = _tmp / f'beancave{len(_built)}'
    home.mkdir()
    cave = BeanCaveContainer(
        green_beans=[GreenBean(name='Ethiopia Guji Uraga',
                               uuid='3f8a1c2e-7b4d-4e9a-9c1f-2d6b8e0a5c73')],
        reference_profiles=[],
    )
    (home / 'beancave.json').write_text(cave.to_json(), encoding='utf-8')

    roast_dir = _tmp / f'roasts{len(_built)}'
    roast_dir.mkdir()
    for name in roasts:
        shutil.copy(_CORPUS / name, roast_dir / name)

    settings = QSettings()
    settings.setValue('beancaveDirectory', str(home))
    settings.setValue('alogDirectory', str(roast_dir))
    settings.setValue('Beancave/LastRoastUUID', last_roast_uuid)
    settings.sync()

    class FakeApplicationWindow(QWidget):
        """Stands in for the running application.

        A real QWidget, because the dialog parents itself to it; everything else
        BeanCave reaches for is answered on demand, so a new dependency on the
        application shows up as a recorded attribute rather than a crash.
        """

        def __getattr__(self, name: str):  # noqa: ANN204
            stub = MagicMock(name=f'aw.{name}')
            object.__setattr__(self, name, stub)
            return stub

    aw = FakeApplicationWindow()
    # Explicit, not a stub: the list asks whether a roast is open, and a
    # MagicMock is truthy, so an unset value would read as "one is".
    aw.curFile = cur_file
    dlg = BeancaveDlg(aw)
    _built.append((dlg, aw))

    # Construction defers work to the event loop — the first folder scan, the
    # metadata index and the refresh it triggers. Let all of it land, or the
    # checks would describe a dialog no operator ever sees.
    _settle(dlg, app)
    return dlg


def _settle(dlg, app, seconds: float = 20.0) -> None:  # noqa: ANN001
    from PyQt6.QtCore import QThread

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if not [t for t in dlg.findChildren(QThread) if t.isRunning()]:
            break
        time.sleep(0.01)
    app.processEvents()


# ── the dialog really finished opening ───────────────────────────────────────

@check
def the_parameter_files_are_read() -> None:
    """``load_parameters`` logs and returns when the file is not where it looks,
    so an empty list here is the whole symptom: the variety and process pickers
    come up blank and the first read of them raises a KeyError."""
    dlg = open_beancave()
    assert dlg.coffee_beans_species, 'no bean species loaded (see cave.common.PKG_DIR)'
    assert dlg.coffee_bean_types.get('Arabica'), 'the Arabica variety list is empty'
    assert dlg.coffee_processing_methods, 'no processing methods loaded'
    assert dlg.roaster_manager is not None, 'the roaster list was never created'


@check
def opening_beancave_raises_no_dialog() -> None:
    """A message here means construction hit a path it treats as an operator
    error — an unreadable folder, a corrupt library — on a folder that is neither."""
    open_beancave(roasts=THREE)
    assert not _dialogs_raised, 'dialogs on screen: ' + ' | '.join(_dialogs_raised)


@check
def the_library_on_disk_reaches_the_table() -> None:
    dlg = open_beancave()
    assert dlg.cave is not None, 'the bean library was not loaded'
    assert [b.name for b in dlg.cave.green_beans] == ['Ethiopia Guji Uraga']
    assert dlg.datatable.rowCount() == 1


@check
def every_slice_reaches_qt() -> None:
    """Slots declared in the slices are slots on the assembled dialog.

    A mixin dropped from the bases, or a slot renamed in one of them, shows up
    here rather than as a connection that silently never fires.
    """
    dlg = open_beancave()
    meta = dlg.metaObject()
    registered = {bytes(meta.method(i).name()).decode() for i in range(meta.methodCount())}
    for slot in ('save_settings', 'generate_qr_code'):   # first and last mixin
        assert slot in registered, f'{slot!r} never reached Qt'


# ── one scan at a time ───────────────────────────────────────────────────────

@check
def a_second_folder_scan_replaces_the_first() -> None:
    """Both happen on the way in — the viewer defers one, the metadata index
    triggers another when it lands — and the second used to overwrite the handle
    to the first. The first went on scanning, still wired to the list it was
    about to repaint, and a thread destroyed while running takes the process."""
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    dlg = open_beancave(roasts=THREE)
    dlg.list_alog_files()
    first = dlg._list_thread          # noqa: SLF001
    dlg.list_alog_files()
    assert first is not dlg._list_thread, 'the second scan reused the first handle'  # noqa: SLF001
    assert not first.isRunning(), 'the first scan is still running after being replaced'

    _settle(dlg, QApplication.instance(), 15.0)
    assert not [t for t in dlg.findChildren(QThread) if t.isRunning()], \
        'a scan thread outlived the dialog it belongs to'


@check
def a_roast_appears_once_in_the_list() -> None:
    """Disconnecting an abandoned scan cannot unqueue a result it already
    emitted, so a stale delivery used to append on top of the fresh one."""
    dlg = open_beancave(roasts=THREE)
    rows = dlg.roast_list_widget.count()
    assert rows == len(THREE), f'{len(THREE)} roasts in the folder, {rows} rows listed'


@check
def a_rebuilt_list_never_leaves_the_viewer_on_its_placeholder() -> None:
    """The rebuild reselects in silence, so it must repaint what it reselected.

    Rebuilding the list clears it, and clearing arms a pending selection change.
    On a cold roast index the scan outlasts that delay, so the pending change
    fired on an empty list and painted "select a roast" — then the rows arrived,
    the selection was restored with signals blocked, and nothing repainted. A
    blank curve, a placeholder where the roast should be, and not one line in the
    log, until the operator clicked another row.
    """
    from PyQt6.QtWidgets import QApplication

    dlg = open_beancave(roasts=THREE)
    placeholder = 'Select a roast file to see the curve preview.'

    # Force the shape the cold index produces: a rebuild whose pending selection
    # change would otherwise fire while the list is empty.
    dlg.list_alog_files()
    assert not dlg._selection_debounce.isActive(), (  # noqa: SLF001
        'the rebuild left a selection change pending — on a cold index it fires '
        'before the rows arrive, against an empty list'
    )
    dlg._selection_debounce.timeout.emit()      # noqa: SLF001  the delay, elapsed
    _settle(dlg, QApplication.instance(), 15.0)

    assert selected(dlg), 'the rebuild left the list with nothing selected'
    assert dlg.roast_plot_label.text() != placeholder, (
        'the viewer is showing its "no roast selected" placeholder while a roast '
        'is selected — the rebuild reselected in silence and never repainted'
    )


# ── where the list lands ─────────────────────────────────────────────────────

@check
def the_list_lands_on_the_roast_open_in_tilauscope() -> None:
    """A roast already on screen is what the operator came back to."""
    assert selected(open_beancave(roasts=THREE, cur_file=MIDDLE)) == MIDDLE


@check
def with_nothing_open_the_list_lands_on_the_latest_roast() -> None:
    """Not the first row: that is alphabetical and says nothing about recency."""
    from PyQt6.QtCore import Qt

    dlg = open_beancave(roasts=THREE)
    assert selected(dlg) == NEWEST
    row0 = dlg.roast_list_widget.item(0).data(Qt.ItemDataRole.UserRole)['raw_fname']
    assert row0 == OLDEST_BY_NAME, 'the fixtures no longer distinguish row 0 from the latest'


@check
def the_roast_left_selected_is_where_the_next_session_opens() -> None:
    """Carried by the roast's own UUID, so renaming the log keeps the place."""
    dlg = open_beancave(roasts=THREE, last_roast_uuid=roast_uuid(OLDEST_BY_NAME))
    assert selected(dlg) == OLDEST_BY_NAME


@check
def a_remembered_roast_that_is_gone_falls_back_to_the_latest() -> None:
    """The folder is the operator's to reorganise; a stale memory must not stick."""
    assert selected(open_beancave(roasts=THREE, last_roast_uuid='0' * 32)) == NEWEST


@check
def what_was_selected_is_written_out_as_a_uuid() -> None:
    """The saved value is the roast UUID, not the filename that may change."""
    from PyQt6.QtCore import QSettings

    dlg = open_beancave(roasts=THREE)
    row = dlg._find_item_by_metadata(dlg.roast_list_widget, 'raw_fname', MIDDLE)  # noqa: SLF001
    dlg.roast_list_widget.setCurrentRow(row)
    dlg.save_settings()
    assert QSettings().value('Beancave/LastRoastUUID', '', str) == roast_uuid(MIDDLE)


# ── runner ───────────────────────────────────────────────────────────────────

def main() -> None:
    global _tmp  # noqa: PLW0603  one scratch folder for the whole run
    sandbox = sys.argv[1] if len(sys.argv) > 1 else None
    _guard.install(sandbox)

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    _tmp = Path(tempfile.mkdtemp(prefix='beancave-child-'))

    # Bluetooth is deferred work with hardware behind it and a test of its own
    # (test_ble_shutdown); and no styled dialog may block an offscreen run.
    for name in _DIALOG_SITES:
        mod = importlib.import_module(f'tilauscope.cave.{name}')
        if hasattr(mod, 'show_styled_message'):
            mod.show_styled_message = _no_dialog
    from tilauscope.cave import lifecycle as _lifecycle
    _lifecycle.LifecycleMixin._start_ble_scanner = lambda _self: None

    results: dict[str, str | None] = {}
    for name, fn in CHECKS.items():
        _dialogs_raised.clear()
        try:
            fn()
            results[name] = None
        except BaseException:  # noqa: BLE001  # a check must never abort the run
            results[name] = traceback.format_exc(limit=6)

    for dlg, aw in _built:
        try:
            dlg._cancel_threads()  # noqa: SLF001
            dlg.close()
            aw.deleteLater()
        except BaseException:  # noqa: BLE001, S110
            pass
    shutil.rmtree(_tmp, ignore_errors=True)

    if sandbox:
        _guard.verify(sandbox)

    if sys.stdout.isatty():
        for name, failure in results.items():
            print(f'{"ok  " if failure is None else "FAIL"}  {name}')
            if failure:
                print(failure)
    print('---JSON---')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
