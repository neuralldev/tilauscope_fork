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

"""The background jobs BeanCave runs off the GUI thread.

Each is a QObject with ``run()`` and result signals, started through the
dialog's worker launcher; none of them touches a widget."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401
    pass  # pylint: disable=unused-import
from pathlib import Path

#import matplotlib.pyplot as plt

from PIL import Image



from PyQt6.QtCore import (pyqtSlot, QThread, pyqtSignal, QObject) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.niimprint import NiimbotBLE, NiimbotPrintOutcome, Niimprint_PaperType
from tilauscope.tilauscope_types import GreenBean
from tilauscope.ai_support import TilauAIConfig
from tilauscope.roasters import RoasterManager
from tilauscope.alogmanager import (AlogMetadata)
from tilauscope.cave.roast_list import BeanFacts, RoastRow, make_row

if TYPE_CHECKING:
    from tilauscope.beancave import BeancaveDlg

from tilauscope.cave.common import (  # noqa: F401
    _logd, _log, _PLOT_PALETTE, _FS_TITLE, _FS_AXIS, _FS_TICK, _FS_EVENT, _FS_HOVER, _FS_LEGEND, C0_COLOR_KEY, C_BT_COLOR_KEY, C_DTR_COLOR_KEY, C_WL_COLOR_KEY, DEFAULT_C0, DEFAULT_C_BT, DEFAULT_C_DTR, DEFAULT_C_WL, greencave_headers, BEANCAVE_FILE_NAME, _SVG_EXPAND, _SVG_COLLAPSE, _SVG_CONSISTENCY, _SVG_ALIGN, _safe_filename, _svg_bytes_to_icon, _SVG_DENSITY, load_cave_beans, _atomic_write_text, apply_mica_acrylic_effect,
    ror_span_samples, recompute_profile_deltas)

class BeanAIWorker(QObject):
    # Signal to return the extracted GreenBean object
    finished = pyqtSignal(GreenBean)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, ai: TilauAIConfig, url: str, coffee_beans_categories:list[str], coffee_processing_methods:dict[str, list[str]], coffee_producing_countries: list[str], coffee_bean_types:dict[str, list[str]], coffee_beans_species: list[str]):
        super().__init__()
        self.ai = ai
        self.url = url
        self.coffee_beans_categories = coffee_beans_categories
        self.coffee_processing_methods = coffee_processing_methods
        self.coffee_producing_countries = coffee_producing_countries
        self.coffee_bean_types = coffee_bean_types
        self.coffee_beans_species = coffee_beans_species

    def run(self):
        try:
            thread = QThread.currentThread()
            if thread.isInterruptionRequested():
                self.cancelled.emit()
                return
            from tilauscope.bean_extractor import CoffeeAIParser
            parser = CoffeeAIParser(
                                    self.ai,
                                    self.coffee_beans_categories,
                                    self.coffee_processing_methods,
                                    self.coffee_producing_countries,
                                    self.coffee_bean_types,
                                    self.coffee_beans_species)
            # This is the time-consuming Gemini call
            result = parser.get_bean_from_url(self.url)
            if thread.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


def stop_worker_thread(thread, worker=None, slots=(), timeout_ms: int = 2000,
                       name: str = "worker") -> None:
    """Detach a worker's result slots, then stop and join its thread.

    The same three steps in the same order, for the jobs that had no teardown at
    all: disconnect first so a result landing during the wait cannot reach a
    half-destroyed dialog, then ask the worker to stop, then join.

    Used only where nothing was joining the thread before. The teardowns that
    already existed keep their own code: each is tuned to what its worker does,
    and replacing them with this one caused hangs.

    `slots` are (signal, slot) pairs to disconnect. Safe to call on a thread
    that is already finished, already deleted, or was never started.
    """
    if thread is None:
        return
    try:
        if not thread.isRunning():
            return
        for sig, slot in slots:
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        cancel = getattr(worker, 'cancel', None)
        if callable(cancel):
            try:
                cancel()
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                pass
        thread.requestInterruption()
        thread.quit()
        if thread.wait(timeout_ms):
            return
        # Deliberately no terminate(). It kills the thread at an arbitrary
        # instruction, which can leave a Qt-internal mutex locked forever: the
        # symptom is the NEXT BeanCave freezing while it builds a widget, with
        # no crash and no log. Measured at 6 hangs in 8 opens when the load
        # cancellation used it. Waiting a second time is the safe move — these
        # workers check isInterruptionRequested and return within a read.
        _log.warning(f"{name} did not stop cooperatively — waiting once more")
        if not thread.wait(timeout_ms):
            _log.error(f"{name} is still running and was left to finish on its own")
    except (RuntimeError, AttributeError):
        pass  # C++ side already gone


class NiimbotWorker(QObject):
    # Signals for the UI to listen to
    print_finished = pyqtSignal()
    print_error = pyqtSignal(str)
    # The label data went out but the printer never reported the label done.
    print_unconfirmed = pyqtSignal()
    copy_progress = pyqtSignal(int, int)  # labels out, labels in the run — for multi-copy runs

    def __init__(self, printer_instance:NiimbotBLE, label_image:Image, label_type:Niimprint_PaperType, copies:int=1):
        super().__init__()
        self.printer = printer_instance
        self.image = label_image
        self.type = label_type
        self.copies = max(1, int(copies))
        self.printed = 0        # copies actually out of the printer
        self._stop = False

    def cancel(self) -> None:
        """Stop after the copy currently being printed — a label already on its
        way through the head cannot be recalled."""
        self._stop = True

    def run(self):
        try:
            # The copies are one job: the printer repeats the label it received once.
            outcome = self.printer.print_image(
                self.image, 3, self.type, copies=self.copies,
                stop_requested=lambda: self._stop, on_label_out=self.copy_progress.emit)
            if outcome is NiimbotPrintOutcome.UNCONFIRMED:
                self.print_unconfirmed.emit()
                return
            if outcome is not NiimbotPrintOutcome.PRINTED:
                self._on_error(self.printer.print_failure)
                return
            self.printed = self.printer.labels_confirmed
            self._on_success()
        except Exception as e:
            self.print_error.emit(str(e))
            return

    def _on_success(self):
        self.print_finished.emit()

    def _on_error(self,message):
        self.print_error.emit(message)

class _RoasterLoadWorker(QObject):
    finished = pyqtSignal(object)   # emits the populated RoasterManager
    error    = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    @pyqtSlot()
    def run(self) -> None:
        try:
            thread = QThread.currentThread()
            if thread.isInterruptionRequested():
                self.cancelled.emit()
                return
            mgr = RoasterManager()
            if self._path.exists():
                mgr.load_json(self._path)
            if thread.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished.emit(mgr)
        except Exception as e:
            self.error.emit(str(e))

class _AlogLoadWorker(QObject):
    finished = pyqtSignal(object, object, object)  # profiledata, deltaet, deltabt
    error = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent:BeancaveDlg, filepath: Path, aw: ApplicationWindow):
        super().__init__()
        self._path = filepath
        self.aw = aw
        self.parent = parent

    @pyqtSlot()
    def run(self) -> None:
        try:
            thread = QThread.currentThread()
            if thread.isInterruptionRequested():
                self.cancelled.emit()
                return
            data = self.parent.get_alog_data(self._path)
            if data is not None:
                if thread.isInterruptionRequested():
                    self.cancelled.emit()
                    return
                # evaldeltas is numpy — safe off-thread
                deltaet = self._eval(data, "temp1")
                if thread.isInterruptionRequested():
                    self.cancelled.emit()
                    return
                deltabt = self._eval(data, "temp2")
                if thread.isInterruptionRequested():
                    self.cancelled.emit()
                    return
                self.finished.emit(data, deltaet, deltabt)
            else:
                # Toujours émettre finished ou error — sinon la queue multi se bloque
                _log.warning(f"_AlogLoadWorker: get_alog_data returned None for {self._path}")
                self.error.emit(f"Could not load data from {self._path.name}")
        except Exception as e:
            _log.error(f"_AlogLoadWorker exception: {e}", exc_info=True)
            self.error.emit(str(e))

    def _eval(self, data: dict, deltaname:str):
        """Same series the GUI path draws: the curve on screen and the coach's
        crash/flick verdict must not be computed two different ways."""
        qmc = self.aw.qmc
        return recompute_profile_deltas(qmc, data, deltaname,
                                        ror_span_samples(qmc, data, deltaname))

class _CallableWorker(QObject):
    """Runs one blocking call off the GUI thread and hands its result back.

    For the short blocking calls the dialog makes on a button press — a web
    request, a GATT read — that used to freeze the window until they timed out.
    The callable must touch no widget and no ``qmc``: only its result crosses
    back, through the signal.
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as e:  # noqa: BLE001
            _log.error(f"_CallableWorker failed: {e}", exc_info=True)
            self.error.emit(str(e))


class _AlogListWorker(QObject):
    """Scans the alog directory and builds the roast list rows off the main thread using cached metadata."""
    finished = pyqtSignal(int, list)   # scan generation, list of RoastRow
    error    = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, directory: Path, cache_records: dict[str, AlogMetadata],
                 beans: dict[str, BeanFacts] | None = None, generation: int = 0):
        super().__init__()
        self._directory = directory
        self._cache_records = cache_records
        # Plain values copied on the GUI thread, never the bean records it edits.
        self._beans = dict(beans or {})
        # Travels with the rows: this worker is deleted as soon as it emits, so
        # the receiver cannot tell which scan they belong to from sender().
        self._generation = generation

    @pyqtSlot()
    def run(self) -> None:
        import re as _re
        from datetime import datetime as _dt

        # Generic Artisan default titles that carry no bean information
        _GENERIC_TITLES = {'roaster scope', 'artisan', 'tilausope',''}

        try:
            thread = QThread.currentThread()
            if thread.isInterruptionRequested():
                self.cancelled.emit()
                return
            fnames = [f.name for f in self._directory.glob('*.alog')
                      if f.suffix.lower() == '.alog']

            # sort_epoch resolves a date from the filename when the index has none,
            # so ordering and grouping by day work before the index is built.
            rows: list[RoastRow] = []
            for f in fnames:
                if thread.isInterruptionRequested():
                    self.cancelled.emit()
                    return
                meta = self._cache_records.get(str(self._directory / f))
                display, base_name, sort_epoch = _AlogListWorker._build_display(
                    fname_stem=f[:-5],
                    meta_title=meta.title if meta else "",
                    batch_prefix=meta.batch_prefix if meta else "",
                    batch_nr=meta.batch_nr if meta else 0,
                    roastepoch=meta.roastepoch if meta else 0,
                    re=_re,
                    dt=_dt,
                    generic_titles=_GENERIC_TITLES,
                )
                rows.append(make_row(f, sort_epoch, display, base_name, meta, self._beans))

            # The list orders and groups the rows itself.
            self.finished.emit(self._generation, rows)
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _build_display(
        fname_stem: str,
        meta_title: str,
        batch_prefix: str,
        batch_nr: int,
        roastepoch: int,
        re,
        dt,
        generic_titles: set,
    ) -> tuple[str, str, int]:
        """
        Build a human-readable display name for a roast file.

        Returns (display_name, base_name, sort_epoch) where sort_epoch is the
        roast date used to order the list (0 when no date could be resolved).

        Priority:
          date_str  : roastepoch → multi-pattern filename extraction → ""
          base_name : meta.title (if not generic) → cleaned filename stem → ""
          batch_tag : "#N · " prefix when batch_nr > 0  (leading '#' stripped from prefix)
        Result: "{batch_tag}{base_name} ({date_str})"
        """
        # 1. Date from roastepoch (most reliable — immune to filename conventions)
        date_str = ""
        if roastepoch > 0:
            try:
                date_str = dt.fromtimestamp(roastepoch).strftime('%Y/%m/%d %H:%M')
            except (OSError, OverflowError, ValueError):
                pass

        # 2. Fallback: extract date from filename stem
        if not date_str:
            date_str = _AlogListWorker._extract_date_from_stem(fname_stem, re, dt)

        # 2b. Sort epoch — the cache has no roastepoch for older /
        # not-yet-scanned files, so recover one from the date read off the
        # filename; without it every such file ties at 0 and the list falls back
        # to raw directory order (which looks random to the user).
        sort_epoch = roastepoch if roastepoch > 0 else 0
        if sort_epoch <= 0 and date_str:
            for _fmt in ('%Y/%m/%d %H:%M', '%Y/%m/%d'):
                try:
                    sort_epoch = int(dt.strptime(date_str, _fmt).timestamp())
                    break
                except (ValueError, OSError, OverflowError):
                    continue

        # 3. Base name: prefer meta.title when it carries real information
        clean_title = meta_title.strip()
        if clean_title.lower() in generic_titles or not clean_title:
            base_name = _AlogListWorker._clean_stem(fname_stem, re)
        else:
            base_name = clean_title

        # 4. Batch tag — strip any leading '#' from prefix to avoid "##N"
        bp_clean = batch_prefix.lstrip('#') if batch_prefix else ""
        batch_tag = f"#{bp_clean}{batch_nr} · " if batch_nr > 0 else ""

        # 5. Assemble: "<bean name incl. crop year> [<date>]" — the name (the
        #    primary sort key) leads the line, the date sits in brackets.
        if date_str:
            if base_name:
                display = f"{batch_tag}{base_name} [{date_str}]"
            elif batch_tag:
                display = f"{batch_tag.removesuffix(' · ')} [{date_str}]"
            else:
                display = date_str
        else:
            display = f"{batch_tag}{base_name}" if (batch_tag or base_name) else fname_stem

        return display, (base_name if base_name else fname_stem), sort_epoch

    @staticmethod
    def _extract_date_from_stem(stem: str, re, dt) -> str:
        """
        Try multiple filename date patterns. Returns 'YYYY/MM/DD HH:MM' or 'YYYY/MM/DD' or "".

        Patterns (non-anchored — date may appear anywhere in the stem):
          A: YY-MM-DD_HHMM  (optionally preceded by #N_)  e.g. #1_26-02-24_1858
          B: YYYYMMDD_HHMM                                 e.g. Colombia_20260224_1858
          C: YYYY_MM_DD_HHMM                               e.g. Colombia_2026_02_24_1858
          D: YY-MM-DD  (date only, no time)                e.g. Colombia_26-02-24
        """
        s = stem.replace('\xa0', ' ').strip()

        # A: optional leading #N_, then YY-MM-DD_HHMM (tolerant of trailing suffix like 'b')
        m = re.search(r'(?:^#\d*[_\s])?(\d{2})[-_](\d{2})[-_](\d{2})[_\s-](\d{4})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}", '%y%m%d%H%M'
                ).strftime('%Y/%m/%d %H:%M')
            except ValueError:
                pass

        # B: YYYYMMDD_HHMM
        m = re.search(r'(\d{4})(\d{2})(\d{2})[_\s-](\d{4})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}", '%Y%m%d%H%M'
                ).strftime('%Y/%m/%d %H:%M')
            except ValueError:
                pass

        # C: YYYY_MM_DD_HHMM
        m = re.search(r'(\d{4})[_\-](\d{2})[_\-](\d{2})[_\s-](\d{4})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}", '%Y%m%d%H%M'
                ).strftime('%Y/%m/%d %H:%M')
            except ValueError:
                pass

        # D: YY-MM-DD anywhere (no time)
        m = re.search(r'(\d{2})[-_](\d{2})[-_](\d{2})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}", '%y%m%d'
                ).strftime('%Y/%m/%d')
            except ValueError:
                pass

        return ""

    @staticmethod
    def _clean_stem(stem: str, re) -> str:
        """Strip date/time noise and batch prefix from a filename stem."""
        s = stem.replace('\xa0', ' ').strip()
        # Remove leading batch marker: #N_ or #_ (N can be empty)
        s = re.sub(r'^#\d*[_\-\s]+', '', s)

        # Strip Artisan's trailing date stamp as ONE anchored unit — a loose
        # "date-like block" match can otherwise catch a crop year instead (e.g.
        # "2024_26-05-13_1847"), leaving an orphan day number welded to the name
        # and making every file of the same bean look unique.
        date_suffix = (
            r'[\s_\-]+'
            r'(?:\d{2}[-_]\d{2}[-_]\d{2}'      # YY-MM-DD
            r'|\d{4}[-_]\d{2}[-_]\d{2}'        # YYYY-MM-DD
            r'|\d{8})'                          # YYYYMMDD
            r'(?:[\s_\-]+\d{4}\w*)?$'          # optional HHMM (+ suffix like 'b')
        )
        cleaned = re.sub(date_suffix, '', s)
        if cleaned != s:
            s = cleaned
        else:
            # Unknown convention: fall back to the loose rules (date may sit
            # anywhere in the stem). YY-MM-DD first — it is the narrowest match.
            s = re.sub(r'\d{2}[\-_]\d{2}[\-_]\d{2}', '', s)      # YY-MM-DD
            s = re.sub(r'\d{4}[\s_\-]\d{2}[\s_\-]\d{2}', '', s)  # YYYY-MM-DD
            s = re.sub(r'\d{8}', '', s)                            # YYYYMMDD
            # Trailing HHMM block (4 digits, optional non-digit suffix like 'b')
            s = re.sub(r'[\s_\-]\d{4}\w*$', '', s)
        # Normalise separators and trim
        s = re.sub(r'[\s\-_\/]+', ' ', s).strip()
        s = re.sub(r'[.\-\s_]+$', '', s).strip()
        return s  # may be "" — caller handles fallback
