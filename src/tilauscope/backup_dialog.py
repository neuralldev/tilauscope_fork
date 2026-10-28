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

"""Help › Back up TilauScope / Restore TilauScope, the automatic backup on quit, and the notices they leave."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QDateTime, QEventLoop, QLocale, QSettings, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QMessageBox, QProgressBar, QSizePolicy, QVBoxLayout,
                             QWidget)

from tilaucore import backup as core
from tilauscope import backup
from tilauscope.theme_qss import apply_tilau_theme
from tilauscope.tilauscope_types import THEME, show_styled_message
from tilauscope.widgets.card_dialog import CardDialog as _Card
from tilauscope.widgets.card_dialog import card_button as _button
from tilauscope.widgets.card_dialog import card_label as _label
from tilauscope.widgets.card_dialog import card_separator as _separator
from tilauscope.widgets.card_dialog import set_path as _set_path
from tilauscope.widgets.controls import SegmentedControl

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

_log = logging.getLogger(__name__)

_open: dict[str, QDialog] = {}   # one window of each kind, kept alive while shown


def _when(iso: str) -> str:
    stamp = QDateTime.fromString(iso, Qt.DateFormat.ISODate)
    return QLocale().toString(stamp, QLocale.FormatType.ShortFormat) if stamp.isValid() else iso


def _megabytes(size: int) -> str:
    return f"{max(1, round(size / 1_000_000))}"


def _system(name: str) -> str:
    return {"Darwin": "macOS"}.get(name, name)


class _RunPage:
    """Progress row with Cancel, shared by backup and restore."""

    def __init__(self, layout: QVBoxLayout, caption: str) -> None:
        top = QHBoxLayout()
        self.title = _label("")
        top.addWidget(self.title, 1)
        self.count = _label("", variant="mono")
        top.addWidget(self.count)
        layout.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)
        bottom = QHBoxLayout()
        bottom.addWidget(_label(caption, variant="caption"), 1)
        self.cancel = _button(QApplication.translate("Button", "Cancel"))
        bottom.addWidget(self.cancel)
        layout.addLayout(bottom)
        layout.addStretch()

    def show_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        self.count.setText(f"{done} / {total}")


# ── Back up ─────────────────────────────────────────────────────────────────

class BackupDialog(_Card):

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent, QApplication.translate("tilauscope_diagnostics", "Back up TilauScope"))
        self._job: backup.BackupJob | None = None
        self._target: Path | None = None
        self._build_settings_page()
        self._build_run_page()
        self._build_done_page()

    # page 0
    def _build_settings_page(self) -> None:
        lay = self.page()
        counts = core.count(core.plan_roots(backup.roots()))
        lay.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "WHAT IS SAVED"), variant="eyebrow"))
        tiles = QGridLayout()
        tiles.setSpacing(10)
        for column, (value, caption) in enumerate((
                (str(counts.roasts), QApplication.translate("tilauscope_diagnostics", "roasts")),
                (str(counts.coffees), QApplication.translate("tilauscope_diagnostics", "coffees")),
                (str(counts.tastings), QApplication.translate("tilauscope_diagnostics", "tastings")),
                (_megabytes(counts.size) + " MB", QApplication.translate("tilauscope_diagnostics", "in total")))):
            tile = QFrame()
            tile.setObjectName("tile")
            inner = QVBoxLayout(tile)
            inner.setContentsMargins(12, 10, 12, 10)
            inner.setSpacing(2)
            inner.addWidget(_label(value, variant="readout-sm"))
            inner.addWidget(_label(caption, variant="caption"))
            tiles.addWidget(tile, 0, column)
        lay.addLayout(tiles)
        lay.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "Roasts, BeanCave, settings and everything TilauScope has learned are saved together, so they always match."), "body"))
        lay.addWidget(_label("🔒  " + QApplication.translate("tilauscope_diagnostics", "Passwords and API keys stay in the system keychain. They are not in the backup."), "body"))
        lay.addWidget(_separator())

        lay.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "BACKUP FOLDER"), variant="eyebrow"))
        row = QHBoxLayout()
        self._folder = _label("", "path", "mono")
        _set_path(self._folder, backup.folder())
        row.addWidget(self._folder, 1)
        change = _button(QApplication.translate("tilauscope_diagnostics", "Change…"))
        change.clicked.connect(self._choose_folder)
        row.addWidget(change)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addStretch()
        self._backup_now = _button(QApplication.translate("tilauscope_diagnostics", "Back up now"), "primary")
        self._backup_now.clicked.connect(self._start_backup)
        row.addWidget(self._backup_now)
        lay.addLayout(row)
        lay.addWidget(_separator())

        settings = QSettings()
        row = QHBoxLayout()
        row.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "AUTOMATIC BACKUP"), variant="eyebrow"), 1)
        self._auto = SegmentedControl([QApplication.translate("tilauscope_diagnostics", "Off"),
                                       QApplication.translate("tilauscope_diagnostics", "On")], compact=True)
        self._auto.set_current(1 if settings.value(backup.KEY_AUTO, False, type=bool) else 0)
        self._auto.changed.connect(self._auto_changed)
        row.addWidget(self._auto)
        lay.addLayout(row)
        self._auto_box = QWidget()
        box = QVBoxLayout(self._auto_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        box.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "When TilauScope closes after a session with new roasts. Never during a roast."), "body"))
        box.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "Extra copy — network or cloud folder")))
        row = QHBoxLayout()
        self._extra = _label("", "path", "mono")
        row.addWidget(self._extra, 1)
        self._extra_state = _label("", variant="caption")
        self._extra_state.setWordWrap(False)
        row.addWidget(self._extra_state)
        choose = _button(QApplication.translate("tilauscope_diagnostics", "Choose…"))
        choose.clicked.connect(self._choose_extra)
        row.addWidget(choose)
        self._clear_extra = _button("✕")
        self._clear_extra.setToolTip(QApplication.translate("tilauscope_diagnostics", "No extra copy"))
        self._clear_extra.clicked.connect(lambda: self._set_extra(""))
        row.addWidget(self._clear_extra)
        box.addLayout(row)
        box.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "Optional. A local copy is always kept in the backup folder above."), variant="caption"))
        row = QHBoxLayout()
        row.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "Copies to keep")), 1)
        self._keep = SegmentedControl([str(n) for n in backup.KEEP_CHOICES], compact=True)
        self._keep.set_current(backup.KEEP_CHOICES.index(backup.keep_count()))
        self._keep.changed.connect(lambda i: QSettings().setValue(backup.KEY_KEEP, backup.KEEP_CHOICES[i]))
        row.addWidget(self._keep)
        box.addLayout(row)
        status = QFrame()
        status.setObjectName("status")
        inner = QHBoxLayout(status)
        inner.setContentsMargins(12, 9, 12, 9)
        inner.addWidget(_label(self._last_auto_text(), "body"))
        box.addWidget(status)
        lay.addWidget(self._auto_box)
        lay.addStretch()
        self._set_extra(settings.value(backup.KEY_EXTRA, "", type=str))
        self._auto_box.setEnabled(self._auto.current() == 1)

    @staticmethod
    def _last_auto_text() -> str:
        settings = QSettings()
        last = settings.value(backup.KEY_LAST_AUTO, 0.0, type=float)
        if not last:
            return QApplication.translate("tilauscope_diagnostics", "No automatic backup yet.")
        when = QLocale().toString(QDateTime.fromSecsSinceEpoch(int(last)), QLocale.FormatType.ShortFormat)
        if settings.value(backup.KEY_LAST_RESULT, "ok", type=str) == "extra_failed":
            return QApplication.translate("tilauscope_diagnostics", "Last automatic backup: {0} — local copy saved, extra copy failed.").format(when)
        if settings.value(backup.KEY_EXTRA, "", type=str):
            return QApplication.translate("tilauscope_diagnostics", "Last automatic backup: {0} — local and extra copy saved.").format(when)
        return QApplication.translate("tilauscope_diagnostics", "Last automatic backup: {0} — local copy saved.").format(when)

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, QApplication.translate("tilauscope_diagnostics", "Backup folder"), backup.folder())
        if chosen:
            QSettings().setValue(backup.KEY_FOLDER, chosen)
            _set_path(self._folder, chosen)

    def _choose_extra(self) -> None:
        start = QSettings().value(backup.KEY_EXTRA, "", type=str) or backup.folder()
        chosen = QFileDialog.getExistingDirectory(self, QApplication.translate("tilauscope_diagnostics", "Extra copy — network or cloud folder"), start)
        if chosen:
            self._set_extra(chosen)

    def _set_extra(self, path: str) -> None:
        QSettings().setValue(backup.KEY_EXTRA, path)
        self._clear_extra.setVisible(bool(path))
        _set_path(self._extra, path or QApplication.translate("tilauscope_diagnostics", "None"), 250)
        if not path:
            self._extra_state.setText("")
        elif backup.extra_reachable(path):
            self._extra_state.setText("● " + QApplication.translate("tilauscope_diagnostics", "Reachable"))
            self._extra_state.setStyleSheet(f"color:{THEME['SUCCESS']};")
        else:
            self._extra_state.setText("● " + QApplication.translate("tilauscope_diagnostics", "Unreachable"))
            self._extra_state.setStyleSheet(f"color:{THEME['WARNING']};")

    def _auto_changed(self, index: int) -> None:
        QSettings().setValue(backup.KEY_AUTO, index == 1)
        self._auto_box.setEnabled(index == 1)

    # page 1
    def _build_run_page(self) -> None:
        self._run = _RunPage(self.page(), QApplication.translate("tilauscope_diagnostics", "You can keep using TilauScope meanwhile."))
        self._run.title.setText(QApplication.translate("tilauscope_diagnostics", "Copying files"))
        self._run.cancel.clicked.connect(self._cancel)

    # page 2
    def _build_done_page(self) -> None:
        lay = self.page()
        self._done_title = _label("", variant="title")
        lay.addWidget(self._done_title)
        self._done_body = _label("", "body")
        lay.addWidget(self._done_body)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        self._show_folder = _button(QApplication.translate("tilauscope_diagnostics", "Show in folder"))
        self._show_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(backup.folder())))
        row.addWidget(self._show_folder)
        done = _button(QApplication.translate("tilauscope_diagnostics", "Done"), "primary")
        done.clicked.connect(self.close)
        row.addWidget(done)
        lay.addLayout(row)

    def _start_backup(self) -> None:
        self._target = core.backup_name(core.MANUAL_PREFIX, Path(backup.folder()))
        self._job = backup.BackupJob()
        self._job.progress.connect(self._run.show_progress)
        self._job.finished.connect(self._finished)
        self._job.failed.connect(self._failed)
        self.show_page(1)
        self._job.start(backup.backup_work(self._target))

    def _cancel(self) -> None:
        if self._job is not None:
            self._job.cancel.set()

    def _finished(self, target: Path) -> None:
        counts = core.count(core.plan_roots(backup.roots()))
        self._done_title.setText("✓  " + QApplication.translate("tilauscope_diagnostics", "Backup saved"))
        self._done_body.setText(f"{target.name}\n" + QApplication.translate("tilauscope_diagnostics", "{0} roasts · {1} coffees · {2} tastings · {3} MB").format(
            counts.roasts, counts.coffees, counts.tastings, _megabytes(target.stat().st_size)))
        self._show_folder.setVisible(True)
        self.show_page(2)

    def _failed(self, kind: str) -> None:
        if kind == "cancelled":
            self.show_page(0)
            return
        self._done_title.setText(QApplication.translate("tilauscope_diagnostics", "The backup could not be written."))
        self._done_body.setText(QApplication.translate("tilauscope_diagnostics", "Check that the backup folder exists and that there is free space, then try again."))
        self._show_folder.setVisible(False)
        self.show_page(2)

    def closeEvent(self, a0: Any) -> None:  # noqa: N802
        self._cancel()
        _open.pop("backup", None)
        super().closeEvent(a0)


# ── Restore ─────────────────────────────────────────────────────────────────

class RestoreDialog(_Card):

    def __init__(self, parent: QWidget | None, aw: ApplicationWindow, archive: Path, manifest: core.Manifest) -> None:
        super().__init__(parent, QApplication.translate("tilauscope_diagnostics", "Restore TilauScope"))
        self._aw = aw
        self._archive = archive
        self._manifest = manifest
        self._job: backup.BackupJob | None = None
        current = backup.roots()
        # where each operator folder of the backup lands: this machine's folder, else where it was
        self._targets = {key: current.get(key) or info["path"] for key, info in manifest.roots.items()
                         if key in core.OPERATOR_ROOTS and info["inside"] is None}
        self._known = {key: (current.get(key), info["path"]) for key, info in manifest.roots.items()}
        self._build_preview(core.count(core.plan_roots(current)))
        self._run = _RunPage(self.page(), QApplication.translate("tilauscope_diagnostics", "TilauScope restarts when this is done."))
        self._run.title.setText(QApplication.translate("tilauscope_diagnostics", "Checking the backup and saving the current state…"))
        self._run.cancel.clicked.connect(self._cancel)

    def _build_preview(self, here: core.Counts) -> None:
        lay = self.page()
        made = self._manifest
        file_card = QFrame()
        file_card.setObjectName("tile")
        inner = QVBoxLayout(file_card)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.addWidget(_label(self._archive.name, variant="mono"))
        inner.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "Made on {0} · TilauScope {1} build {2} · {3}").format(
            _when(made.created), made.version, made.build, _system(made.system)), variant="caption"))
        lay.addWidget(file_card)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "IN THE BACKUP"), variant="eyebrow"), 0, 1)
        grid.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "ON THIS COMPUTER"), variant="eyebrow"), 0, 2)
        rows = ((QApplication.translate("tilauscope_diagnostics", "Roasts"), made.counts.roasts, here.roasts),
                (QApplication.translate("tilauscope_diagnostics", "Coffees"), made.counts.coffees, here.coffees),
                (QApplication.translate("tilauscope_diagnostics", "Tastings"), made.counts.tastings, here.tastings))
        for line, (name, theirs, ours) in enumerate(rows, start=1):
            grid.addWidget(_label(name), line, 0)
            grid.addWidget(_label(str(theirs), variant="mono"), line, 1)
            more = "" if ours <= theirs else "   · " + QApplication.translate("tilauscope_diagnostics", "{0} more").format(ours - theirs)
            grid.addWidget(_label(f"{ours}{more}", variant="mono"), line, 2)
        lay.addLayout(grid)

        warn = QFrame()
        warn.setObjectName("warn")
        inner = QVBoxLayout(warn)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.addWidget(_label("⚠  " + QApplication.translate("tilauscope_diagnostics", "Everything on this computer is replaced by the backup."), variant="title"))
        inner.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "Roasts made since this backup will no longer appear. They are not lost: a safety copy of the current state is made first, and you can restore it from the same menu."), "body"))
        lay.addWidget(warn)

        self._target_labels: dict[str, QLabel] = {}
        for key in self._targets:
            caption = (QApplication.translate("tilauscope_diagnostics", "Roasts go to") if key == core.ROAST
                       else QApplication.translate("tilauscope_diagnostics", "BeanCave goes to"))
            lay.addWidget(_label(caption))
            row = QHBoxLayout()
            self._target_labels[key] = _label("", "path", "mono")
            _set_path(self._target_labels[key], self._targets[key])
            row.addWidget(self._target_labels[key], 1)
            change = _button(QApplication.translate("tilauscope_diagnostics", "Change…"))
            change.clicked.connect(lambda _c=False, k=key: self._choose_target(k))
            row.addWidget(change)
            lay.addLayout(row)
        if core.CAVE in self._manifest.roots and core.CAVE not in self._targets:
            lay.addWidget(_label(QApplication.translate("tilauscope_diagnostics", "The BeanCave goes to its usual folder."), variant="caption"))
        lay.addWidget(_label("🔒  " + QApplication.translate("tilauscope_diagnostics", "TilauScope restarts. Then enter your passwords and API keys again (AI assistant, MQTT)."), "body"))
        lay.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel = _button(QApplication.translate("Button", "Cancel"))
        cancel.clicked.connect(self.close)
        row.addWidget(cancel)
        go = _button("↺  " + QApplication.translate("tilauscope_diagnostics", "Restore and restart"))
        go.setObjectName("restore")
        go.clicked.connect(self._start)
        row.addWidget(go)
        lay.addLayout(row)
        go.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _choose_target(self, key: str) -> None:
        chosen = QFileDialog.getExistingDirectory(self, self.windowTitle(), self._targets[key])
        if not chosen:
            return
        if not core.safe_target(chosen, self._known.get(key, ())):
            show_styled_message(self, self.windowTitle(), QApplication.translate("tilauscope_diagnostics", "This folder already holds other files, and restoring replaces its content.\n\nChoose an empty folder, or the one TilauScope already uses."), QMessageBox.Icon.Warning)
            return
        self._targets[key] = chosen
        _set_path(self._target_labels[key], chosen)

    def _start(self) -> None:
        if self._aw.qmc.flagstart:
            return
        self._job = backup.BackupJob()
        self._job.progress.connect(self._run.show_progress)
        self._job.finished.connect(self._ready)
        self._job.failed.connect(self._failed)
        self.show_page(1)
        self._job.start(backup.restore_work(self._archive, self._manifest, self._targets))

    def _cancel(self) -> None:
        if self._job is not None:
            self._job.cancel.set()

    def _ready(self, _safety: Path) -> None:
        # The restore itself runs at the next start; quitting starts the relaunch (on_quit).
        self.close()
        self._aw.fileQuit()

    def _failed(self, kind: str) -> None:
        self.show_page(0)
        if kind == "cancelled":
            return
        if kind == core.BackupError.DAMAGED:
            _damaged(self)
        else:
            show_styled_message(self, self.windowTitle(), QApplication.translate("tilauscope_diagnostics", "The current state could not be saved first, so nothing was restored.\n\nCheck that the backup folder exists and that there is free space."), QMessageBox.Icon.Warning)

    def closeEvent(self, a0: Any) -> None:  # noqa: N802
        self._cancel()
        _open.pop("restore", None)
        super().closeEvent(a0)


def _damaged(parent: QWidget | None) -> bool:
    """True when the operator asks to pick another file."""
    title = QApplication.translate("tilauscope_diagnostics", "Restore TilauScope")
    text = QApplication.translate("tilauscope_diagnostics", "This file is damaged or incomplete.\n\nIt cannot be restored. Nothing was changed.")
    buttons = [QApplication.translate("Button", "Close"), QApplication.translate("tilauscope_diagnostics", "Choose another file…")]
    return show_styled_message(parent, title, text, QMessageBox.Icon.Critical, buttons=buttons) == 1


# ── entry points ────────────────────────────────────────────────────────────

def _show(key: str, dialog: QDialog) -> None:
    _open[key] = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def open_backup(aw: ApplicationWindow, parent: QWidget | None = None) -> None:
    if aw.qmc.flagstart:
        return
    if "backup" in _open:
        _open["backup"].raise_()
        return
    _show("backup", BackupDialog(parent or QApplication.activeWindow()))


def open_restore(aw: ApplicationWindow) -> None:
    if aw.qmc.flagstart or "restore" in _open:
        return
    parent = QApplication.activeWindow()
    title = QApplication.translate("tilauscope_diagnostics", "Restore TilauScope")
    version, build = backup.app_version()
    while True:
        chosen, _ = QFileDialog.getOpenFileName(parent, title, backup.folder(),
                                                QApplication.translate("tilauscope_diagnostics", "TilauScope backup") + f" (*{core.EXTENSION})")
        if not chosen:
            return
        try:
            manifest = core.read_manifest(Path(chosen), version=version, build=build)
        except core.BackupError as e:
            if e.kind == core.BackupError.NEWER:
                text = QApplication.translate("tilauscope_diagnostics", "This backup comes from a newer TilauScope ({0}).\n\nUpdate TilauScope, then restore. Nothing was changed.").format(str(e))
                buttons = [QApplication.translate("Button", "Close"), QApplication.translate("tilauscope_diagnostics", "Check for updates")]
                if show_styled_message(parent, title, text, QMessageBox.Icon.Warning, buttons=buttons) == 1:
                    updater = getattr(aw, "_tilau_updater", None)
                    if updater is not None:
                        updater.check_now()
                return
            if _damaged(parent):
                continue
            return
        _show("restore", RestoreDialog(parent, aw, Path(chosen), manifest))
        return


# ── quitting ────────────────────────────────────────────────────────────────

class _ClosingPill(QWidget):
    """Saving your backup before closing… — with the one way out: skip this time."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        apply_tilau_theme(self, ground=False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        pill = QFrame()
        pill.setObjectName("pill")
        pill.setStyleSheet(f"#pill {{ background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']}; border-radius:22px; }}"
                           f"QProgressBar {{ background:{THEME['BORDER']}; border:none; border-radius:3px; max-height:6px; }}"
                           f"QProgressBar::chunk {{ background:{THEME['ACCENT']}; border-radius:3px; }}")
        outer.addWidget(pill)
        row = QHBoxLayout(pill)
        row.setContentsMargins(16, 6, 8, 6)
        row.setSpacing(12)
        row.addWidget(QLabel(QApplication.translate("tilauscope_diagnostics", "Saving your backup before closing…")))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(120)
        row.addWidget(self.bar)
        self.skip = _button(QApplication.translate("tilauscope_diagnostics", "Skip this time"))
        row.addWidget(self.skip)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)

    def show_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)


def on_quit() -> None:
    """Called by closeApp once the quit is confirmed and the settings written.

    A restore waiting for the next start: launch the helper that reopens
    TilauScope. Otherwise run the automatic backup when one is due.
    """
    if backup.restore_pending():
        backup.relaunch_after_exit()
        return
    if not backup.auto_backup_due():
        return
    pill = _ClosingPill()
    job = backup.BackupJob()
    loop = QEventLoop()
    outcome: dict[str, str] = {}
    job.progress.connect(pill.show_progress)
    job.finished.connect(lambda result: (outcome.update(result=result), loop.quit()))
    job.failed.connect(lambda kind: (outcome.update(failed=kind), loop.quit()))
    pill.skip.clicked.connect(job.cancel.set)
    pill.show()
    job.start(backup.auto_backup_work())
    loop.exec()
    pill.close()
    if "result" in outcome:
        backup.record_auto_result(outcome["result"])
    elif outcome.get("failed") != "cancelled":
        settings = QSettings()
        settings.setValue(backup.KEY_LAST_RESULT, "failed")
        settings.sync()


# ── what the last session left to say ───────────────────────────────────────

def show_backup_notices(parent: QWidget, aw: ApplicationWindow) -> None:
    """After a restore, or after an extra copy that could not be made. Runs from a timer: never raises."""
    try:
        _notices(parent, aw)
    except Exception:  # pylint: disable=broad-except
        _log.exception("backup notices failed")


def _notices(parent: QWidget, aw: ApplicationWindow) -> None:
    settings = QSettings()
    title = QApplication.translate("tilauscope_diagnostics", "Restore TilauScope")
    failed_safety = settings.value(backup.KEY_RESTORE_FAILED, None)
    restored = settings.value(backup.KEY_RESTORED, "", type=str)
    if failed_safety is not None:
        settings.remove(backup.KEY_RESTORE_FAILED)
        text = QApplication.translate("tilauscope_diagnostics", "The restore could not be completed.\n\nThe state from before the restore is saved in {0}. You can restore it from Help › Restore TilauScope.").format(Path(str(failed_safety)).name)
        show_styled_message(parent, title, text, QMessageBox.Icon.Critical)
    elif restored:
        settings.remove(backup.KEY_RESTORED)
        text = QApplication.translate("tilauscope_diagnostics", "Backup of {0} restored.\n\nEnter your passwords and API keys again: AI assistant, MQTT.").format(_when(restored))
        buttons = [QApplication.translate("tilauscope_diagnostics", "Later"), QApplication.translate("tilauscope_diagnostics", "Open settings")]
        if show_styled_message(parent, title, text, buttons=buttons) == 1:
            aw.tilauscope_config()
    elif settings.value(backup.KEY_EXTRA_FAILED, False, type=bool):
        settings.setValue(backup.KEY_EXTRA_FAILED, False)
        text = QApplication.translate("tilauscope_diagnostics", "Network folder unreachable — the local backup was saved.")
        buttons = [QApplication.translate("tilauscope_diagnostics", "Later"), QApplication.translate("tilauscope_diagnostics", "Check folder")]
        if show_styled_message(parent, QApplication.translate("tilauscope_diagnostics", "Back up TilauScope"), text, QMessageBox.Icon.Warning, buttons=buttons) == 1:
            open_backup(aw, parent)
