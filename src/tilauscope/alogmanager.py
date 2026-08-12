#
# ABOUT
# alog manager

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
# TiLau 2025

from dataclasses import dataclass, field
from mashumaro.mixins.json import DataClassJSONMixin
import ast as _ast
import re as _re
from pathlib import Path
from typing import Final
import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

_log: Final[logging.Logger] = logging.getLogger(__name__)

@dataclass
class AlogMetadata(DataClassJSONMixin):
    filename: str
    filepath_str: str
    mtime: float
    batch_prefix: str = ""
    batch_nr: int = 0
    title: str = ""
    bean_field: str = ""
    uuid: str = ""
    roastepoch: int = 0  # seconds since epoch from roastepoch field in .alog; 0 = unknown
    roast_uuid: str = ""  # Artisan roastUUID (hex-32) — QR scan lookup key

@dataclass
class AlogCacheCollection(DataClassJSONMixin):
    records: dict[str, AlogMetadata] = field(default_factory=dict)


class _AlogCacheIndexingWorker(QObject):
    """
    Background worker that updates a shared memory cache collection.
    Reads file bytes ONLY if the file is new or its mtime has changed.
    """
    finished = pyqtSignal(dict)

    def __init__(self, directory: Path, existing_records: dict[str, AlogMetadata]):
        super().__init__()
        self.directory = directory
        self.records = dict(existing_records)

    @pyqtSlot()
    def run(self) -> None:
        if not self.directory.exists() or not self.directory.is_dir():
            self.finished.emit(self.records)
            return

        thread = QThread.currentThread()  # pour isInterruptionRequested()

        try:
            uuid_pattern = _re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')
            current_paths = set()

            for f in self.directory.glob('*.alog'):
                # Point d'interruption : vérifié à chaque fichier
                # requestInterruption() est appelé par _cancel_threads avant quit()
                if thread.isInterruptionRequested():
                    _log.debug("AlogCacheIndexingWorker: interruption demandée, arrêt anticipé")
                    self.finished.emit(self.records)
                    return

                if f.suffix.lower() != '.alog':
                    continue

                f_str = str(f)
                current_paths.add(f_str)
                try:
                    current_mtime = f.stat().st_mtime
                except OSError:
                    continue

                # Cache verification layer — skip si mtime inchangé
                if f_str in self.records and self.records[f_str].mtime == current_mtime:
                    continue

                # Point d'interruption avant l'opération la plus longue (I/O + parse)
                if thread.isInterruptionRequested():
                    _log.debug("AlogCacheIndexingWorker: interruption avant lecture fichier")
                    self.finished.emit(self.records)
                    return

                # Parse file only on cache-miss.
                # Format natif Artisan : repr(dict) en UTF-8 (cf. artisanlib.util) —
                # pas de unicode_escape, sinon mojibake sur les accents.
                try:
                    data = _ast.literal_eval(f.read_text(encoding='utf-8'))
                    if not isinstance(data, dict):
                        continue
                except Exception:
                    continue

                bean_field = str(data.get("beans", "") or "")
                uuid_match = uuid_pattern.search(bean_field)
                uuid_val = uuid_match.group(1) if uuid_match else ""

                # roastepoch: prefer explicit field, fall back to mtime
                try:
                    epoch_val = int(data.get('roastepoch', 0) or 0)
                except (ValueError, TypeError):
                    epoch_val = 0
                if epoch_val <= 0:
                    epoch_val = int(current_mtime)

                self.records[f_str] = AlogMetadata(
                    filename=f.name,
                    filepath_str=f_str,
                    mtime=current_mtime,
                    batch_prefix=str(data.get('roastbatchprefix', '') or ''),
                    batch_nr=int(data.get('roastbatchnr', 0) or 0),
                    title=str(data.get('title', '') or ''),
                    bean_field=bean_field,
                    uuid=uuid_val,
                    roastepoch=epoch_val,
                    roast_uuid=str(data.get('roastUUID', '') or ''),
                )

            # Prune deleted files — seulement si pas interrompu (cache partiel cohérent)
            if not thread.isInterruptionRequested():
                for old_path in list(self.records.keys()):
                    if old_path not in current_paths:
                        del self.records[old_path]

        except Exception as e:
            _log.error(f"Error updating Alog metadata cache: {e}", exc_info=True)

        self.finished.emit(self.records)