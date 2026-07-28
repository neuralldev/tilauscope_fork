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

## TILAU ## Sack identification & label recycling (BeanCave — Lot 1).
## Spec: wiki/design-nouveau-sac-etiquette-v4.md
##
## Sack labelling is a fully OPTIONAL convenience for users with a label
## printer: a bean with no sacks is a normal, permanent state and every
## feature here degrades to invisible when unused.
##
## Persistence is machine-local (QSettings, per user decision):
##   tilauscope/next_sack_id          int   — next sequential label number
##   tilauscope/free_sack_ids         json  — [[id, iso-date], ...] released labels
##   tilauscope/sack_release_confirm  bool  — show the release confirmation

import json
import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame,
                             QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from tilauscope.tilauscope_types import THEME, show_styled_message

_logd = logging.getLogger(__name__)

_KEY_NEXT    = "tilauscope/next_sack_id"
_KEY_FREE    = "tilauscope/free_sack_ids"
_KEY_PRINTED = "tilauscope/printed_sack_ids"
_KEY_CONFIRM = "tilauscope/sack_release_confirm"


class SackPool:
    """Machine-local registry of the label counter and released (free) sack ids."""

    # ── sequential counter (Nouveau lot tool, Lot 2) ────────────────────────
    @staticmethod
    def next_number() -> int:
        try:
            return int(QSettings().value(_KEY_NEXT, 1))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def set_next_number(n: int) -> None:
        QSettings().setValue(_KEY_NEXT, max(1, int(n)))

    # ── free (recyclable) labels ─────────────────────────────────────────────
    @staticmethod
    def free_entries() -> list[tuple[str, str]]:
        """Released labels as (sack_id, iso-date) pairs, oldest first."""
        raw = QSettings().value(_KEY_FREE, "")
        try:
            entries = json.loads(raw) if raw else []
            pairs = [(str(e[0]), str(e[1])) for e in entries if e and e[0]]
        except (json.JSONDecodeError, TypeError, IndexError) as e:
            _logd.warning(f"Corrupt free_sack_ids setting, resetting: {e}")
            pairs = []
        return sorted(pairs, key=lambda p: p[1])

    @staticmethod
    def free_ids() -> list[str]:
        return [sid for sid, _d in SackPool.free_entries()]

    @staticmethod
    def _save(entries: list[tuple[str, str]]) -> None:
        QSettings().setValue(_KEY_FREE, json.dumps([list(e) for e in entries]))

    @staticmethod
    def release(sack_id: str) -> None:
        """Add a label back to the free pool (bag emptied, label reusable)."""
        sack_id = sack_id.strip()
        if not sack_id:
            return
        entries = [e for e in SackPool.free_entries() if e[0] != sack_id]
        entries.append((sack_id, datetime.now().astimezone().date().isoformat()))
        SackPool._save(entries)

    @staticmethod
    def consume(sack_id: str) -> None:
        """Remove a label from the free pool (re-assigned to a new bag)."""
        SackPool._save([e for e in SackPool.free_entries() if e[0] != sack_id])

    # alias for the "Retirer" action of the Sacs libres tool (label destroyed)
    discard = consume

    # ── printed, never-assigned labels ───────────────────────────────────────
    # A batch printed with the ID-labels tool is a physical stock of blank
    # sacks waiting to be used: those ids must be offered at the wizard's
    # identification step even though no bag was ever released.
    @staticmethod
    def printed_ids() -> list[str]:
        raw = QSettings().value(_KEY_PRINTED, "")
        try:
            ids = [str(i) for i in (json.loads(raw) if raw else []) if i]
        except (json.JSONDecodeError, TypeError) as e:
            _logd.warning(f"Corrupt printed_sack_ids setting, resetting: {e}")
            ids = []
        return ids

    @staticmethod
    def register_printed(ids: list[str]) -> None:
        """Record freshly batch-printed labels as available for assignment."""
        known = SackPool.printed_ids()
        for raw_id in ids:
            sid = raw_id.strip()
            if sid and sid not in known:
                known.append(sid)
        QSettings().setValue(_KEY_PRINTED, json.dumps(known))

    @staticmethod
    def mark_assigned(sack_id: str) -> None:
        """A label was attached to a bean: drop it from both available stores."""
        SackPool.consume(sack_id)
        remaining = [i for i in SackPool.printed_ids() if i != sack_id]
        QSettings().setValue(_KEY_PRINTED, json.dumps(remaining))

    # a destroyed label leaves both stores too — same effect as assigning it
    forget = mark_assigned

    @staticmethod
    def available_ids(green_beans: list) -> list[str]:
        """Labels offerable at the identification step: released (recycled)
        ones first, then printed-but-never-assigned ones, excluding any id
        currently attached to a catalogue bean."""
        assigned = {sid for bean in (green_beans or [])
                    for sid in (getattr(bean, "sacks", None) or [])}
        out = [sid for sid in SackPool.free_ids() if sid not in assigned]
        out += [sid for sid in SackPool.printed_ids()
                if sid not in assigned and sid not in out]
        return out

    # ── duplicate lookup (warning at entry time, Lot 3) ──────────────────────
    @staticmethod
    def find_owner(sack_id: str, green_beans: list) -> str | None:
        """Return the name of the bean already holding sack_id, else None."""
        for bean in green_beans or []:
            if sack_id in (getattr(bean, "sacks", None) or []):
                return bean.name
        return None


# ---------------------------------------------------------------------------
## TILAU ## Stock-exhausted reclaim (design v4 §9.3) — a bean whose stock hits
## zero still holds its labels, and the Storage tab filters those beans out of
## its own list: without this, the ids leave the pool and never come back.
##
## "Empty" is strictly 0 g — same criterion as the Storage tab filter and the
## catalogue out-of-stock pill, so the three never disagree.
# ---------------------------------------------------------------------------

def is_out_of_stock(bean) -> bool:
    """True when a bean holds no green coffee left (strictly 0 g)."""
    try:
        return float(getattr(bean, "weight_left", 0.0) or 0.0) <= 0.0
    except (TypeError, ValueError):
        return False


def orphaned_sacks(green_beans: list) -> list[tuple[object, list[str]]]:
    """Beans with no stock left that still hold labels, as (bean, ids) pairs.

    Callers must pass the FULL bean list: the Storage tab's own list is
    filtered on ``weight_left > 0`` and excludes exactly what we look for.
    """
    out: list[tuple[object, list[str]]] = []
    for bean in green_beans or []:
        ids = [s for s in (getattr(bean, "sacks", None) or []) if s]
        if ids and is_out_of_stock(bean):
            out.append((bean, ids))
    return out


def release_sacks(bean, sack_ids: list[str]) -> int:
    """Detach labels from a bean and return them to the reusable pool.

    Persistence is left to the caller (each host owns its own save path).
    Returns the number of labels actually released.
    """
    ids = [s for s in (sack_ids or []) if s]
    if not ids:
        return 0
    bean.sacks = [s for s in (getattr(bean, "sacks", None) or []) if s not in ids]
    for sack_id in ids:
        SackPool.release(sack_id)
    _logd.debug(f"Released {len(ids)} label(s) from '{getattr(bean, 'name', '?')}'")
    return len(ids)


def prompt_release_if_emptied(parent: QWidget | None, bean, previous_weight: float,
                              save_cb=None) -> bool:
    """Offer to reclaim a bean's labels when its stock just reached zero.

    ## TILAU ## Single entry point for every path that writes ``weight_left``
    ## (bean form, zone editors, wizard restock). Duplicating this check would
    ## leave one path silently uncovered — no error, the prompt simply absent.
    ## The passive banner in the Storage tab is the safety net for anything
    ## that still slips through.

    Fires only on the 0 g *transition*: ``previous_weight`` above zero and the
    bean now empty while still holding labels. Returns True when labels were
    released (the caller's ``save_cb`` has then already run).
    """
    try:
        if bean is None or not is_out_of_stock(bean):
            return False
        if float(previous_weight or 0.0) <= 0.0:
            return False            # already empty before the write — not a transition
        ids = [s for s in (getattr(bean, "sacks", None) or []) if s]
        if not ids:
            return False

        name = getattr(bean, "name", "") or QApplication.translate("tilauscope_beancave", "(unnamed)")
        choice = show_styled_message(
            parent,
            QApplication.translate("tilauscope_beancave", "Stock exhausted"),
            QApplication.translate("tilauscope_beancave", "« {0} » is down to 0 g.").format(name) + "\n\n" +
            QApplication.translate(
                "tilauscope_beancave",
                "Its {0} label(s) can go back to the pool and be reused:").format(len(ids)) +
            "\n" + "   ".join(ids),
            buttons=[QApplication.translate("tilauscope_beancave", "Keep them attached"),
                     QApplication.translate("tilauscope_beancave", "Release the labels")],
        )
        if choice != 1:
            return False            # kept — this time only, the banner will insist

        release_sacks(bean, ids)
        if callable(save_cb):
            save_cb()
        return True
    except Exception:  # noqa: BLE001
        _logd.exception("prompt_release_if_emptied failed")
        return False


def confirm_release(parent: QWidget | None, sack_id: str) -> bool:
    """Ask 'is this sack empty?' before releasing a label back to the pool.

    Honors the 'don't ask me again' preference (tilauscope/sack_release_confirm).
    Returns True when the release should proceed.
    """
    settings = QSettings()
    if not settings.value(_KEY_CONFIRM, True, type=bool):
        return True

    dlg = QDialog(parent)
    dlg.setWindowTitle(QApplication.translate("tilauscope_beancave", "Release sack") + f" {sack_id}")
    dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    card = QFrame()
    card.setObjectName("SackReleaseCard")
    card.setStyleSheet(
        f"#SackReleaseCard {{ background-color: {THEME['BG']};"
        f" border: 2px solid {THEME['ACCENT']}; border-radius: 14px; }}"
        f"QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}"
        f"QCheckBox {{ color: {THEME['SUBTEXT']}; background: transparent; }}"
    )
    outer.addWidget(card)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 16, 20, 14)
    lay.setSpacing(10)

    title = QLabel(QApplication.translate("tilauscope_beancave", "RELEASE SACK") + f" {sack_id}")
    title.setStyleSheet(
        f"color: {THEME['ACCENT']}; font-family: 'JetBrains Mono', monospace;"
        f" font-size: 13px; font-weight: 800; letter-spacing: 1px;")
    lay.addWidget(title)

    msg = QLabel(
        QApplication.translate("tilauscope_beancave", "Is this sack empty?") + "\n" +
        QApplication.translate("tilauscope_beancave",
                               "The label {0} will become reusable for a future sack.").format(sack_id))
    msg.setWordWrap(True)
    lay.addWidget(msg)

    dont_ask = QCheckBox(QApplication.translate("tilauscope_beancave", "Don't ask me again"))
    lay.addWidget(dont_ask)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = _sack_button(QApplication.translate("tilauscope_beancave", "Cancel"))
    ok_btn = _sack_button(QApplication.translate("tilauscope_beancave", "Release"), primary=True)
    cancel_btn.clicked.connect(dlg.reject)
    ok_btn.clicked.connect(dlg.accept)
    ok_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(ok_btn)
    lay.addLayout(btn_row)

    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    if accepted and dont_ask.isChecked():
        settings.setValue(_KEY_CONFIRM, False)
    return accepted


class SackChipsRow(QWidget):
    """Horizontal row of sack chips ``[ TS-0043 ✕ ]`` shown in the bean form.

    Emits ``sackReleased(sack_id)`` when the user clicks a chip's ✕. The whole
    widget hides itself when the bean has no sacks — a user who never labels
    bags never sees it.
    """

    sackReleased = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self.setVisible(False)

    def set_sacks(self, sacks: list[str]) -> None:
        # clear previous chips (keep the trailing stretch)
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for sack_id in sacks:
            self._layout.insertWidget(self._layout.count() - 1, self._make_chip(sack_id))
        self.setVisible(bool(sacks))

    def _make_chip(self, sack_id: str) -> QWidget:
        chip = QFrame()
        chip.setStyleSheet(
            "QFrame { background: rgba(137,180,250,20); border: 1px solid rgba(137,180,250,70);"
            " border-radius: 9px; }")
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(8, 1, 4, 1)
        lay.setSpacing(4)
        lbl = QLabel(sack_id)
        lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; background: transparent; border: none;"
            f" font-size: 11px; padding: 0;")
        lay.addWidget(lbl)
        x_btn = QPushButton("✕")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.setFixedSize(16, 16)
        x_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Sack empty — release this label for reuse"))
        x_btn.setStyleSheet(
            f"QPushButton {{ color: {THEME['SUBTEXT']}; background: transparent;"
            f" border: none; font-size: 10px; padding: 0; }}"
            f"QPushButton:hover {{ color: {THEME['CRITICAL']}; }}")
        x_btn.clicked.connect(lambda _=False, s=sack_id: self.sackReleased.emit(s))
        lay.addWidget(x_btn)
        return chip


# ## TILAU ## Button charter for every sack dialog — mirrors the Storage tab's
# ``_btn_css`` / ``_accent_css``, since that tab is where these dialogs open
# from. Kept as module constants so the ``SackLabelsDialog`` card stylesheet
# and ``_sack_button`` cannot drift apart.
_SACK_BTN_QSS = (
    f"QPushButton {{ background-color: {THEME['SURFACE']}; color: {THEME['TEXT']};"
    f" border: 1px solid {THEME['BORDER']}; border-radius: 8px;"
    f" padding: 6px 12px; font-weight: 600; }}"
    f"QPushButton:hover {{ border-color: {THEME['ACCENT']}; }}"
    f"QPushButton:disabled {{ color: {THEME['SUBTEXT']}; border-color: {THEME['BORDER']}; }}"
)

_SACK_BTN_PRIMARY_QSS = (
    f"QPushButton {{ background-color: rgba(137,180,250,40); color: {THEME['ACCENT']};"
    f" border: 1px solid rgba(137,180,250,120); border-radius: 8px;"
    f" padding: 6px 14px; font-weight: 700; }}"
    f"QPushButton:hover {{ background-color: rgba(137,180,250,70); }}"
    f"QPushButton:disabled {{ background-color: {THEME['SURFACE']};"
    f" color: {THEME['SUBTEXT']}; border-color: {THEME['BORDER']}; }}"
)


def _sack_button(text: str, *, primary: bool = False) -> QPushButton:
    """Button following the Storage-tab charter (``_btn_css`` / ``_accent_css``).

    ## TILAU ## These dialogs are opened from the Storage tab, so they follow
    ## its button style — surface + 1px border for secondary, accent tint for
    ## primary — and not the flat filled variant used by the older sack dialogs.
    """
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(_SACK_BTN_PRIMARY_QSS if primary else _SACK_BTN_QSS)
    return btn


class SackAssignDialog(QDialog):
    """Attach an existing label to a bean (design v4 §9.2).

    Offers ``SackPool.available_ids()`` and nothing else — recycled labels
    first, then printed but never assigned ones. Picking from that list is the
    only way in: a free-text field could only produce a number the app has no
    record of. A label printed elsewhere goes through the labels tool
    ("Free sacks" tab), which registers it into this very list.
    """

    def __init__(self, parent: QWidget | None, bean, green_beans: list, host=None) -> None:
        super().__init__(parent)
        self._green_beans = green_beans or []
        self._host = host if host is not None else parent
        self._chosen: str | None = None

        from PyQt6.QtWidgets import QListWidget, QListWidgetItem  # noqa: PLC0415
        self._QListWidgetItem = QListWidgetItem

        bean_name = getattr(bean, "name", "") or QApplication.translate("tilauscope_beancave", "(unnamed)")
        dlg_title = QApplication.translate("tilauscope_beancave", "Assign a label") + f" — {bean_name}"
        self.setWindowTitle(dlg_title)
        self.setMinimumWidth(420)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("SackAssignCard")
        card.setStyleSheet(f"""
            #SackAssignCard {{ background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']}; border-radius: 14px; }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QListWidget {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 8px; outline: none; }}
            QListWidget::item {{ padding: 5px 9px; }}
            QListWidget::item:selected {{ background: rgba(137,180,250,40); color: {THEME['TEXT']}; }}
        """)
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(10)

        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "ASSIGN A LABEL")
                           + f" — {bean_name.upper()}")
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-family: 'JetBrains Mono', monospace;"
            f" font-size: 12.5px; font-weight: 800; letter-spacing: 1px;")
        lay.addWidget(title_lbl)

        self.list = QListWidget()
        self.list.setMaximumHeight(184)
        self.list.itemSelectionChanged.connect(self._on_row_picked)
        lay.addWidget(self.list)

        # ## TILAU ## No hand-typed field here: it could only ever produce a
        # number the app does not know about. A label printed elsewhere is
        # registered through the labels tool ("Free sacks" tab, "Add an
        # existing label"), which puts it in this list like any other.
        self.empty_lbl = QLabel(QApplication.translate(
            "tilauscope_beancave",
            "No label available. Print a batch, or register a label you "
            "already have, from the sack labels tool."))
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
        lay.addWidget(self.empty_lbl)

        actions = QHBoxLayout()
        self.print_btn = _sack_button("🏷️ " + QApplication.translate("tilauscope_beancave", "Sack labels…"))
        self.print_btn.clicked.connect(self._open_labels_tool)
        actions.addWidget(self.print_btn)
        actions.addStretch(1)
        cancel_btn = _sack_button(QApplication.translate("tilauscope_beancave", "Cancel"))
        cancel_btn.clicked.connect(self.reject)
        self.ok_btn = _sack_button(QApplication.translate("tilauscope_beancave", "Assign"), primary=True)
        self.ok_btn.clicked.connect(self._accept)
        self.ok_btn.setDefault(True)
        actions.addWidget(cancel_btn)
        actions.addWidget(self.ok_btn)
        lay.addLayout(actions)

        self._reload()

    # ── population ──────────────────────────────────────────────────────────
    def _reload(self) -> None:
        free = set(SackPool.free_ids())
        dates = dict(SackPool.free_entries())
        available = SackPool.available_ids(self._green_beans)
        recycled = [i for i in available if i in free]
        printed = [i for i in available if i not in free]

        self.list.blockSignals(True)
        self.list.clear()
        if recycled:
            self._add_header(QApplication.translate("tilauscope_beancave", "RECYCLED"))
            for sack_id in recycled:
                freed = dates.get(sack_id, "")
                hint = (QApplication.translate("tilauscope_beancave", "freed on {0}").format(freed)
                        if freed else QApplication.translate("tilauscope_beancave", "recycled"))
                self._add_option(sack_id, hint)
        if printed:
            self._add_header(QApplication.translate("tilauscope_beancave", "PRINTED, NEVER USED"))
            for sack_id in printed:
                self._add_option(sack_id, QApplication.translate("tilauscope_beancave", "not assigned yet"))
        self.list.blockSignals(False)

        has_any = bool(available)
        self.list.setVisible(has_any)
        self.empty_lbl.setVisible(not has_any)
        self._validate()

    def _add_header(self, text: str) -> None:
        item = self._QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor(THEME['SUBTEXT']))
        font = item.font()
        font.setPointSizeF(max(8.0, font.pointSizeF() - 2.0))
        font.setBold(True)
        item.setFont(font)
        self.list.addItem(item)

    def _add_option(self, sack_id: str, hint: str) -> None:
        item = self._QListWidgetItem(f"{sack_id}    ·  {hint}")
        item.setData(Qt.ItemDataRole.UserRole, sack_id)
        self.list.addItem(item)

    # ── interaction ─────────────────────────────────────────────────────────
    def _picked_id(self) -> str | None:
        """The selected label, or None on a group header / empty selection."""
        items = self.list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole) or None

    def _on_row_picked(self) -> None:
        self._validate()

    def _validate(self) -> None:
        # ``available_ids`` already excludes every label held by a bean, so a
        # selectable row can never be a duplicate — nothing left to warn about.
        self.ok_btn.setEnabled(self._picked_id() is not None)

    def _open_labels_tool(self) -> None:
        try:
            SackLabelsDialog(self._host).exec()
        except Exception:  # noqa: BLE001
            _logd.exception("SackAssignDialog: labels tool failed")
        self._reload()

    def _accept(self) -> None:
        self._chosen = self._picked_id()
        if self._chosen is None:
            return
        self.accept()

    def selected_id(self) -> str | None:
        """The label the user picked, or None when the dialog was cancelled."""
        return self._chosen


class ReclaimSacksDialog(QDialog):
    """Bulk-release labels still held by out-of-stock beans (design v4 §9.3)."""

    def __init__(self, parent: QWidget | None, orphans: list[tuple[object, list[str]]]) -> None:
        super().__init__(parent)
        self._orphans = orphans
        self._checks: list[tuple[QCheckBox, object, list[str]]] = []

        self.setWindowTitle(QApplication.translate("tilauscope_beancave", "Reclaim labels"))
        self.setMinimumWidth(430)
        dlg_lay = QVBoxLayout(self)
        dlg_lay.setContentsMargins(0, 0, 0, 0)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        card = QFrame()
        card.setObjectName("SackReclaimCard")
        card.setStyleSheet(
            f"#SackReclaimCard {{ background-color: {THEME['BG']};"
            f" border: 2px solid {THEME['ACCENT']}; border-radius: 14px; }}"
            f"QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}"
            f"QCheckBox {{ color: {THEME['TEXT']}; background: transparent; }}")
        dlg_lay.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(10)

        title = QLabel(QApplication.translate("tilauscope_beancave", "RECLAIM LABELS"))
        title.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-family: 'JetBrains Mono', monospace;"
            f" font-size: 12.5px; font-weight: 800; letter-spacing: 1px;")
        lay.addWidget(title)

        intro = QLabel(QApplication.translate(
            "tilauscope_beancave",
            "These beans have no stock left but still hold labels. "
            "Releasing makes them reusable for a future sack."))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px;")
        lay.addWidget(intro)

        for bean, ids in orphans:
            row = QHBoxLayout()
            row.setSpacing(10)
            box = QCheckBox(getattr(bean, "name", "") or
                            QApplication.translate("tilauscope_beancave", "(unnamed)"))
            box.setChecked(True)
            box.stateChanged.connect(self._refresh_count)
            row.addWidget(box, 1)
            ids_lbl = QLabel("   ".join(ids))
            ids_lbl.setStyleSheet(
                f"color: {THEME['ACCENT']}; font-family: 'JetBrains Mono', monospace; font-size: 11.5px;")
            row.addWidget(ids_lbl)
            lay.addLayout(row)
            self._checks.append((box, bean, ids))

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = _sack_button(QApplication.translate("tilauscope_beancave", "Cancel"))
        cancel_btn.clicked.connect(self.reject)
        self.ok_btn = _sack_button("", primary=True)
        self.ok_btn.clicked.connect(self.accept)
        self.ok_btn.setDefault(True)
        actions.addWidget(cancel_btn)
        actions.addWidget(self.ok_btn)
        lay.addLayout(actions)
        self._refresh_count()

    def _refresh_count(self) -> None:
        n = sum(len(ids) for box, _b, ids in self._checks if box.isChecked())
        self.ok_btn.setText(
            QApplication.translate("tilauscope_beancave", "Release {0} label(s)").format(n))
        self.ok_btn.setEnabled(n > 0)

    def apply(self) -> int:
        """Release every checked bean's labels. Returns the count released."""
        total = 0
        for box, bean, ids in self._checks:
            if box.isChecked():
                total += release_sacks(bean, ids)
        return total


# ---------------------------------------------------------------------------
## TILAU ## "Sack ID labels" tool (design v4 §4) — three modes:
## New batch (sequential), Reprint (manual number), Free sacks (recycling).
## Hosted in the BeanCave File Management tab; also opened from the
## New-sack assistant shortcuts (Lot 3).
# ---------------------------------------------------------------------------

class _SackBatchPrintWorker(QObject):
    """Prints a list of label images sequentially on the Niimbot."""

    progress = pyqtSignal(int)        # 1-based index of the label being printed
    finished = pyqtSignal(int)        # number of labels actually printed
    error    = pyqtSignal(str, int)   # message, number printed before failure

    def __init__(self, printer, images: list, label_type) -> None:
        super().__init__()
        self._printer = printer
        self._images  = images
        self._type    = label_type

    def run(self) -> None:
        printed = 0
        try:
            for i, img in enumerate(self._images, 1):
                self.progress.emit(i)
                if not self._printer.print_image(img, 3, self._type):
                    self.error.emit(
                        QApplication.translate("tilauscope_beancave", "Printer error"),
                        printed)
                    return
                printed += 1
            self.finished.emit(printed)
        except Exception as e:  # noqa: BLE001 — surface any BLE failure to the UI
            self.error.emit(str(e), printed)


class SackLabelsDialog(QDialog):
    """Sack ID label tool — batch print, manual reprint, free-label pool."""

    def __init__(self, host, initial_tab: int = 0) -> None:
        # host: BeancaveDlg — provides .np (NiimbotBLE) and _niimbot_connected
        # initial_tab: 0 = New batch, 1 = Reprint, 2 = Free sacks
        super().__init__(host)
        self._host = host
        self._thread = None
        self._worker = None
        self._printing = False      # impression en cours (progression dans le pill)
        self._run_total = 0         # nb d'étiquettes du lot en cours
        self._batch_start = 0
        self._batch_mode = False
        self._drag_pos = None
        self.setWindowTitle(QApplication.translate("tilauscope_beancave", "Sack ID labels"))
        self.setMinimumWidth(680)

        # ── BeanCave visual code: frameless translucent window + themed card ─
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        from PyQt6.QtWidgets import QTabWidget, QSpinBox, QLineEdit, QListWidget, QFormLayout

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("SackLabelsCard")
        card.setStyleSheet(f"""
            #SackLabelsCard {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QLineEdit, QSpinBox {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 5px; padding: 3px 6px; }}
            QListWidget {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 5px; }}
            QTabWidget::pane {{ border: 1px solid {THEME['BORDER']}; border-radius: 6px; }}
            QTabBar::tab {{ background: {THEME['SURFACE']}; color: {THEME['SUBTEXT']};
                padding: 5px 16px; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
            QTabBar::tab:selected {{ background: {THEME['BORDER']}; color: {THEME['TEXT']}; }}
            {_SACK_BTN_QSS}
        """)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # ── Title row (custom title bar, close button) ───────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "SACK ID LABELS"))
        title_lbl.setStyleSheet(f"""
            color         : {THEME['ACCENT']};
            font-family   : 'JetBrains Mono', monospace;
            font-size     : 13px;
            font-weight   : 800;
            letter-spacing: 1px;
        """)
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['SUBTEXT']};"
            f" border: none; font-size: 14px; padding: 0; }}"
            f"QPushButton:hover {{ color: {THEME['CRITICAL']}; }}")
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn)
        lay.addLayout(title_row)

        subtitle = QLabel(QApplication.translate(
            "tilauscope_beancave",
            "Give each green coffee bag a printed number so you always know "
            "which physical sack a bean comes from."))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
        lay.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {THEME['BORDER']};")
        lay.addWidget(sep)

        # ── Printer status pill — always visible, updated live ──────────────
        self.printer_hint = QLabel("")
        self.printer_hint.setWordWrap(True)
        lay.addWidget(self.printer_hint)
        lay.addSpacing(10)

        tabs = QTabWidget()
        lay.addWidget(tabs)

        def _intro(text: str) -> QLabel:
            w = QLabel(text)
            w.setWordWrap(True)
            w.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px; padding: 2px 0 6px 0;")
            return w

        # ── Tab 1 : New batch ────────────────────────────────────────────────
        batch = QWidget()
        bl = QVBoxLayout(batch)
        bl.addWidget(_intro(QApplication.translate(
            "tilauscope_beancave",
            "Print a small stock of numbered labels ahead of time. Stick one on "
            "each new bag when it arrives, then type its number in the bean form. "
            "The next number follows on from your last batch — you can still edit "
            "it if your sequence ever drifts.")))
        bf = QFormLayout()
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(10)
        self.prefix_edit = QLineEdit("TS-")
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, 99999)
        self.start_spin.setValue(SackPool.next_number())
        self.start_spin.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Prefilled from the counter but editable — fix a drift here."))
        self.batch_preview = QLabel("")
        self.batch_preview.setStyleSheet(f"color: {THEME['SUBTEXT']};")
        bf.addRow(QApplication.translate("tilauscope_beancave", "Number of labels"), self.count_spin)
        bf.addRow(QApplication.translate("tilauscope_beancave", "Prefix"), self.prefix_edit)
        bf.addRow(QApplication.translate("tilauscope_beancave", "Next number"), self.start_spin)
        bf.addRow(QApplication.translate("tilauscope_beancave", "Will print"), self.batch_preview)
        bl.addLayout(bf)
        self.batch_print_btn = _sack_button("🖨  " + QApplication.translate("tilauscope_beancave", "Print batch"), primary=True)
        self.batch_print_btn.clicked.connect(self._print_batch)
        bl.addWidget(self.batch_print_btn)
        bl.addStretch(1)
        tabs.addTab(batch, QApplication.translate("tilauscope_beancave", "New batch"))

        # ── Tab 2 : Reprint ──────────────────────────────────────────────────
        reprint = QWidget()
        rl = QVBoxLayout(reprint)
        rl.addWidget(_intro(QApplication.translate(
            "tilauscope_beancave",
            "A label came out damaged, unreadable, or got lost? Reprint just that "
            "one here: type its exact number — any text works, including a "
            "supplier's own bag number. This prints a single label and never "
            "advances the batch counter.")))
        rf = QFormLayout()
        self.reprint_edit = QLineEdit()
        self.reprint_edit.setPlaceholderText("TS-0043")
        rf.addRow(QApplication.translate("tilauscope_beancave", "Number to print"), self.reprint_edit)
        rl.addLayout(rf)
        self.reprint_btn = _sack_button("🖨  " + QApplication.translate("tilauscope_beancave", "Print one label"), primary=True)
        self.reprint_btn.clicked.connect(self._print_reprint)
        rl.addWidget(self.reprint_btn)
        rl.addStretch(1)
        tabs.addTab(reprint, QApplication.translate("tilauscope_beancave", "Reprint"))

        # ── Tab 3 : Free sacks ───────────────────────────────────────────────
        free = QWidget()
        fl = QVBoxLayout(free)
        fl.addWidget(_intro(QApplication.translate(
            "tilauscope_beancave",
            "Every label you can stick on a future bag lives here: numbers "
            "released by clicking ✕ on an emptied sack, and printed labels not "
            "assigned to a bean yet. They are offered first when you identify a "
            "new sack. Use Remove only when the physical label itself was "
            "destroyed.")))
        self.free_list = QListWidget()
        fl.addWidget(self.free_list)
        self.free_empty_lbl = QLabel(QApplication.translate(
            "tilauscope_beancave", "No label available yet — everything is in use."))
        self.free_empty_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
        fl.addWidget(self.free_empty_lbl)
        ## TILAU ## recover labels printed before tracking existed (or elsewhere):
        ## typing them here puts them back in the available pool without reprinting
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.add_label_edit = QLineEdit()
        self.add_label_edit.setPlaceholderText(QApplication.translate(
            "tilauscope_beancave", "e.g. GV-0001"))
        self.add_label_edit.setMaximumWidth(160)
        self.add_label_btn = QPushButton(QApplication.translate(
            "tilauscope_beancave", "Add label"))
        self.add_label_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave",
            "Register a label you already printed so it is offered again when "
            "identifying a sack — nothing is printed."))
        self.add_label_btn.clicked.connect(self._add_existing_label)
        self.add_label_edit.returnPressed.connect(self._add_existing_label)
        add_row.addWidget(QLabel(QApplication.translate(
            "tilauscope_beancave", "I already have this label:")))
        add_row.addWidget(self.add_label_edit)
        add_row.addWidget(self.add_label_btn)
        add_row.addStretch(1)
        self.remove_free_btn = QPushButton(QApplication.translate("tilauscope_beancave", "Remove"))
        self.remove_free_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Take this label out of the pool (physically destroyed)."))
        self.remove_free_btn.clicked.connect(self._remove_free)
        add_row.addWidget(self.remove_free_btn)
        fl.addLayout(add_row)
        tabs.addTab(free, QApplication.translate("tilauscope_beancave", "Free sacks"))

        tabs.setCurrentIndex(initial_tab)

        self.count_spin.valueChanged.connect(self._refresh_batch_preview)
        self.prefix_edit.textChanged.connect(self._refresh_batch_preview)
        self.start_spin.valueChanged.connect(self._refresh_batch_preview)
        self._refresh_batch_preview()
        self._refresh_free_list()
        self._refresh_printer_state()

        # Live printer state — the Niimbot can be switched on/off while the
        # dialog is open; keep buttons and the status pill in sync.
        from PyQt6.QtCore import QTimer
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(1500)
        self._state_timer.timeout.connect(self._refresh_printer_state)
        self._state_timer.start()

    # ── frameless drag ───────────────────────────────────────────────────────
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _batch_ids(self) -> list[str]:
        prefix = self.prefix_edit.text()
        start  = self.start_spin.value()
        return [f"{prefix}{n:04d}" for n in range(start, start + self.count_spin.value())]

    def _refresh_batch_preview(self) -> None:
        ids = self._batch_ids()
        shown = ", ".join(ids[:3]) + (" …" if len(ids) > 3 else "")
        self.batch_preview.setText(shown)

    def _refresh_free_list(self) -> None:
        self.free_list.clear()
        released = SackPool.free_entries()
        for sid, d in released:
            self.free_list.addItem(f"{sid}   —   " + QApplication.translate(
                "tilauscope_beancave", "released on") + f" {d}")
        released_ids = {sid for sid, _d in released}
        for sid in SackPool.printed_ids():
            if sid not in released_ids:
                self.free_list.addItem(f"{sid}   —   " + QApplication.translate(
                    "tilauscope_beancave", "printed, not assigned yet"))
        has_free = self.free_list.count() > 0
        self.remove_free_btn.setEnabled(has_free)
        self.free_list.setVisible(has_free)
        self.free_empty_lbl.setVisible(not has_free)

    def _add_existing_label(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        sack_id = self.add_label_edit.text().strip()
        if not sack_id:
            return
        beans = getattr(getattr(self._host, 'cave', None), 'green_beans', None) or []
        owner = SackPool.find_owner(sack_id, beans)
        if owner is not None:
            show_styled_message(self,
                QApplication.translate("tilauscope_beancave", "Sack ID labels"),
                QApplication.translate("tilauscope_beancave",
                    "This label is already assigned to") + f" « {owner} ».",
                QMessageBox.Icon.Warning)
            return
        SackPool.register_printed([sack_id])
        self.add_label_edit.clear()
        self._refresh_free_list()

    def _refresh_printer_state(self) -> None:
        # Pendant une impression, le pill affiche la progression et les boutons
        # restent désactivés : ne pas laisser le timer 1,5 s les réécraser.
        if self._printing:
            return
        np_ = getattr(self._host, "np", None)
        connected = bool(getattr(self._host, "_niimbot_connected", False))
        ready = np_ is not None and connected
        self.batch_print_btn.setEnabled(ready)
        self.reprint_btn.setEnabled(ready)
        if ready:
            self.printer_hint.setText("🖨  " + QApplication.translate(
                "tilauscope_beancave", "Niimbot ready"))
            self.printer_hint.setStyleSheet(
                f"color: {THEME['SUCCESS']}; background: rgba(166,227,161,18);"
                f" border: 1px solid rgba(166,227,161,60); border-radius: 5px;"
                f" padding: 4px 10px; font-size: 11px;")
        else:
            self.printer_hint.setText("🖨  " + QApplication.translate(
                "tilauscope_beancave",
                "Niimbot printer not connected — you can prepare everything, printing will unlock when it is."))
            self.printer_hint.setStyleSheet(
                f"color: {THEME['WARNING']}; background: rgba(224,144,59,15);"
                f" border: 1px solid rgba(224,144,59,60); border-radius: 5px;"
                f" padding: 4px 10px; font-size: 11px;")

    def _remove_free(self) -> None:
        item = self.free_list.currentItem()
        if item is not None:
            SackPool.forget(item.text().split()[0])
            self._refresh_free_list()

    # ── printing ─────────────────────────────────────────────────────────────
    def _print_batch(self) -> None:
        ids = self._batch_ids()
        self._batch_start = self.start_spin.value()
        self._batch_mode = True
        self._print_ids(ids)

    def _print_reprint(self) -> None:
        sack_id = self.reprint_edit.text().strip()
        if not sack_id:
            return
        self._batch_mode = False
        self._print_ids([sack_id])

    def _print_ids(self, ids: list[str]) -> None:
        from PyQt6.QtWidgets import QMessageBox
        np_ = getattr(self._host, "np", None)
        if np_ is None or not getattr(self._host, "_niimbot_connected", False):
            self._refresh_printer_state()
            return
        if np_.paper_height != 30:
            show_styled_message(self,
                QApplication.translate("tilauscope_beancave", "Sack ID labels"),
                QApplication.translate("tilauscope_beancave",
                    "Sack labels need the 50×30 mm roll (detected: {0}×{1} mm).")
                    .format(np_.paper_width, np_.paper_height),
                QMessageBox.Icon.Warning)
            return
        from tilauscope.label_printer import build_sack_label_image
        try:
            images = [build_sack_label_image(sid) for sid in ids]
        except Exception as e:
            show_styled_message(self,
                QApplication.translate("tilauscope_beancave", "Sack ID labels"),
                QApplication.translate("tilauscope_beancave", "Label rendering failed") + f": {e}",
                QMessageBox.Icon.Warning)
            return

        self._run_ids = list(ids)
        self._run_total = len(images)
        self.batch_print_btn.setEnabled(False)
        self.reprint_btn.setEnabled(False)
        # Progression affichée dans le pill non-modal (plus de fenêtre modale
        # grisant le fond et bloquant les clics / le premier-plan sur macOS).
        self._printing = True
        self._set_progress_pill(0, self._run_total)

        from PyQt6.QtCore import QThread
        self._thread = QThread()
        self._worker = _SackBatchPrintWorker(np_, images, np_.paperstyle)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_print_progress)
        self._worker.finished.connect(self._on_print_finished)
        self._worker.error.connect(self._on_print_error)
        for sig in (self._worker.finished, ):
            sig.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _set_progress_pill(self, done: int, total: int) -> None:
        """Affiche la progression d'impression dans le pill non-modal."""
        self.printer_hint.setText(
            "🖨  " + QApplication.translate("tilauscope_beancave", "Printing...")
            + f" {done}/{total}")
        self.printer_hint.setStyleSheet(
            f"color: {THEME['TEXT']}; background: rgba(137,180,250,18);"
            f" border: 1px solid rgba(137,180,250,60); border-radius: 5px;"
            f" padding: 4px 10px; font-size: 11px;")

    def _on_print_progress(self, i: int) -> None:
        # i = index 1-based de l'étiquette en cours d'impression.
        self._set_progress_pill(i, self._run_total)

    def _finish_run(self, printed: int) -> None:
        # Fin d'impression : le timer 1,5 s reprend la main sur le pill/boutons.
        self._printing = False
        self.raise_()
        self.activateWindow()
        # the counter only advances by what was actually printed (design v4 §4.1)
        if self._batch_mode and printed > 0:
            SackPool.set_next_number(self._batch_start + printed)
            self.start_spin.setValue(SackPool.next_number())
            # printed labels become an available physical stock — the wizard's
            # identification step offers them until they are assigned to a bean
            SackPool.register_printed(getattr(self, '_run_ids', [])[:printed])
        self._refresh_printer_state()

    def _on_print_finished(self, printed: int) -> None:
        self._finish_run(printed)
        show_styled_message(self,
            QApplication.translate("tilauscope_beancave", "Sack ID labels"),
            QApplication.translate("tilauscope_beancave", "{0} label(s) printed.").format(printed))

    def _on_print_error(self, message: str, printed: int) -> None:
        from PyQt6.QtWidgets import QMessageBox
        self._finish_run(printed)
        show_styled_message(self,
            QApplication.translate("tilauscope_beancave", "Sack ID labels"),
            QApplication.translate("tilauscope_beancave",
                "Printing stopped after {0} label(s): {1}").format(printed, message),
            QMessageBox.Icon.Warning)
