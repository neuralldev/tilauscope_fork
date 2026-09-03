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

import numpy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401
    pass  # pylint: disable=unused-import
from pathlib import Path

#import matplotlib.pyplot as plt

from PIL import Image

from artisanlib.util import fill_gaps, convertTemp, smooth_list  # smooth_list moved from tgraphcanvas to util


from PyQt6.QtCore import (pyqtSlot, QThread, pyqtSignal, QObject) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.niimprint import NiimbotBLE, Niimprint_PaperType
from tilauscope.tilauscope_types import (GreenBean, RoastingPhase, marked, normalize_timeindex)
from tilauscope.ai_support import TilauAIConfig
from tilauscope.roasters import RoasterManager
from tilauscope.alogmanager import (AlogMetadata)

if TYPE_CHECKING:
    from tilauscope.beancave import BeancaveDlg

from tilauscope.cave.common import (  # noqa: F401
    _logd, _log, _PLOT_PALETTE, _FS_TITLE, _FS_AXIS, _FS_TICK, _FS_EVENT, _FS_HOVER, _FS_LEGEND, C0_COLOR_KEY, C_BT_COLOR_KEY, C_DTR_COLOR_KEY, C_WL_COLOR_KEY, DEFAULT_C0, DEFAULT_C_BT, DEFAULT_C_DTR, DEFAULT_C_WL, greencave_headers, BEANCAVE_FILE_NAME, _SVG_EXPAND, _SVG_COLLAPSE, _SVG_CONSISTENCY, _SVG_ALIGN, _safe_filename, _svg_bytes_to_icon, _SVG_DENSITY, load_cave_beans, _atomic_write_text, apply_mica_acrylic_effect)

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

class _NiimbotPollWorker(QObject):
    """Worker off-thread : appelle np.poll_status() sans bloquer l'UI."""
    finished = pyqtSignal()

    def __init__(self, np: "NiimbotBLE"):
        super().__init__()
        self._np = np

    @pyqtSlot()
    def run(self) -> None:
        try:
            self._np.poll_status()
        except Exception as e:
            _logd.warning(f"_NiimbotPollWorker: {e}")
        finally:
            self.finished.emit()

class NiimbotWorker(QObject):
    # Signals for the UI to listen to
    print_finished = pyqtSignal()
    print_error = pyqtSignal(str)
    copy_progress = pyqtSignal(int, int)  # done, total — for multi-copy runs

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
            for i in range(self.copies):
                if self._stop:
                    break
                self.copy_progress.emit(i + 1, self.copies)
                if not self.printer.print_image(self.image, 3, self.type):
                    self._on_error("error printing")
                    return
                self.printed = i + 1
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
            tx = numpy.array(data.get("timex", []))
            timeindex = normalize_timeindex(data.get("timeindex", []))
            rd = timeindex[RoastingPhase.CHARGE] if marked(timeindex, RoastingPhase.CHARGE) else 0
            drop = timeindex[RoastingPhase.DROP]
            unit = data.get("temp_unit", "C")
            temp = [convertTemp(t,unit,self.aw.qmc.mode) for t in data.get(deltaname, [])]

            cf = self.aw.qmc.curvefilter #*2 # we smooth twice as heavy for PID/RoR calculation as for normal curve smoothing
            t1 = smooth_list(data.get("timex", []),(fill_gaps(temp) if self.aw.qmc.interpolateDropsflag else temp),window_len=cf,decay_smoothing=not self.aw.qmc.optimalSmoothing)
            if len(t1)>10 and len(tx) > 10:
                # we start RoR computation 10 readings after CHARGE to avoid this initial peak
                RoR_start = min(rd+10,len(tx)-1)
                _, deltas = self.aw.qmc.recomputeDeltas(tx,RoR_start,drop,None,t1,optimalSmoothing=self.aw.qmc.optimalSmoothing)
                return deltas
            return None

class _AlogListWorker(QObject):
    """Scans the alog directory and formats display names off the main thread using cached metadata."""
    finished = pyqtSignal(list)   # list of (raw_filename, display_name)
    error    = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, directory: Path, cache_records: dict[str, AlogMetadata]):
        super().__init__()
        self._directory = directory
        self._cache_records = cache_records

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

            # Build intermediate tuples: (fname, sort_epoch, display_name, base_name)
            triples: list[tuple[str, int, str, str]] = []
            for f in fnames:
                if thread.isInterruptionRequested():
                    self.cancelled.emit()
                    return
                f_path_str = str(self._directory / f)
                meta = self._cache_records.get(f_path_str)
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
                triples.append((f, sort_epoch, display, base_name))

            # Sort: bean name ASC, then roast date DESC within a bean. sort_epoch
            # resolves a date from the filename when roastepoch is missing, so the
            # date tiebreak always has real values instead of falling back to 0.
            triples.sort(key=lambda t: (t[3].lower(), -(t[1])))

            # Deduplicate display names: two roasts of one bean sharing the same
            # displayed date get the original filename stem appended, in parens —
            # the brackets are taken by the date. An explicit "already suffixed"
            # set tracks disambiguation, since every line ends with "[date]".
            seen: dict[str, int] = {}        # display_name → first occurrence index
            disambiguated: set[int] = set()  # indices already given a suffix
            # The roast date travels with each row: the list is ordered by bean
            # name, so nothing downstream could work out which roast is the most
            # recent, and the metadata index is not necessarily built yet.
            rows: list[tuple[str, str, int]] = []
            for fname, epoch, display, _base in triples:
                if thread.isInterruptionRequested():
                    self.cancelled.emit()
                    return
                if display in seen:
                    first_idx = seen[display]
                    if first_idx not in disambiguated:
                        first_fname, first_display, first_epoch = rows[first_idx]
                        rows[first_idx] = (first_fname,
                                           f"{first_display} ({first_fname[:-5]})",
                                           first_epoch)
                        disambiguated.add(first_idx)
                    new_display = f"{display} ({fname[:-5]})"
                else:
                    seen[display] = len(rows)
                    new_display = display
                rows.append((fname, new_display, epoch))

            self.finished.emit(rows)
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
