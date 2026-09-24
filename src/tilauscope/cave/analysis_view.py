"""BeanCave's lazy, read-only analysis page with one in-flight calculation."""
from __future__ import annotations

from collections import OrderedDict
import html
import logging

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox,
                            QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu,
                            QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
                            QTableWidget, QTableWidgetItem, QVBoxLayout,
                            QWidget, QWidgetAction)

from tilauscope.cave.profile_analysis import (MODELS, NOTABLE_DELTA, AnalysisInput, AnalysisResult,
                                              AnalysisUnavailable, Observation, analyze_all,
                                              observations)
from tilauscope.cave.viewer_detail import menu_qss
from tilauscope.widgets.controls import SegmentedControl
from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import THEME, TilauProgress, marked, normalize_timeindex

_log = logging.getLogger(__name__)


class _Signals(QObject):
    finished = pyqtSignal(int, object, object, str)


class _AnalysisTask(QRunnable):
    def __init__(self, generation: int, source: AnalysisInput):
        super().__init__()
        self.generation = generation
        self.source = source
        self.signals = _Signals()

    def run(self) -> None:
        results, error = None, ''
        try:
            results = analyze_all(self.source)
        except AnalysisUnavailable as exc:
            error = str(exc)
        except Exception:  # A worker failure must always release the single-flight gate.
            _log.exception('BeanCave profile analysis failed')
            error = 'fit'
        self.signals.finished.emit(self.generation, self.source, results, error)


class _ReferenceTask(QRunnable):
    """Reads the reference roast's file; its RoR is computed back on the GUI thread."""

    def __init__(self, fname: str, parse):  # noqa: ANN001
        super().__init__()
        self.fname = fname
        self.parse = parse
        self.signals = _Signals()

    def run(self) -> None:
        data = None
        try:
            data = self.parse(self.fname)
        except Exception:  # noqa: BLE001  the gate is released whatever happens
            _log.exception('BeanCave reference roast could not be read')
        self.signals.finished.emit(0, self.fname, data, '')


def _clock(seconds: float) -> str:
    sign = '-' if seconds < 0 else ''
    seconds = abs(int(round(seconds)))
    return f'{sign}{seconds // 60:02d}:{seconds % 60:02d}'


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty('variant', 'caption')
    label.setWordWrap(True)
    return label


class _ObservationCard(QFrame):
    """One passage to examine: what the RoR did, and on demand what it may mean."""

    picked = pyqtSignal(int)

    def __init__(self, number: int, title: str, facts: str, indicates: str, check: str) -> None:
        super().__init__()
        self._number = number
        self.setObjectName('analysisObservation')
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(f"""
            QFrame#analysisObservation {{ background-color: {tint('YELLOW', 10)};
                border: 1px solid {tint('YELLOW', 60)}; border-radius: 9px; }}
            QFrame#analysisObservation QLabel {{ background: transparent; }}""")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        row = QHBoxLayout()
        badge = QLabel(str(number))
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"background-color: {tint('YELLOW', 45)}; color: {THEME['YELLOW']};"
                            f" border-radius: 6px; font-weight: 600;")
        text = QVBoxLayout()
        heading = QLabel(title)
        heading.setStyleSheet('font-weight: 600;')
        heading.setWordWrap(True)
        text.addWidget(heading)
        text.addWidget(_caption(facts))
        self.more = QPushButton(QApplication.translate('tilauscope_beancave', 'Understand ▾'))
        self.more.setCheckable(True)
        self.more.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        row.addWidget(self.more, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(row)
        self.explanation = QLabel(
            f"<b>{QApplication.translate('tilauscope_beancave', 'What it indicates')}</b><br>{html.escape(indicates)}"
            f"<br><b>{QApplication.translate('tilauscope_beancave', 'What to check')}</b><br>{html.escape(check)}")
        self.explanation.setWordWrap(True)
        self.explanation.setStyleSheet(f"color: {THEME['SUBTEXT']}; border-left: 2px solid {THEME['YELLOW']};"
                                       f" padding-left: 10px;")
        self.explanation.hide()
        outer.addWidget(self.explanation)
        self.more.toggled.connect(self._toggled)

    @pyqtSlot(bool)
    def _toggled(self, opened: bool) -> None:
        self.explanation.setVisible(opened)
        self.more.setText(QApplication.translate('tilauscope_beancave', 'Collapse ▴') if opened else QApplication.translate('tilauscope_beancave', 'Understand ▾'))

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        # A virtual: an escape here would close the application.
        try:
            self.picked.emit(self._number - 1)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception('observation selection failed')
        super().mousePressEvent(event)


class RoastAnalysisView(QWidget):
    """Only showEvent / a visible input change can schedule work.

    Workers own immutable series, never this widget or qmc. A global pool keeps
    a running task alive if BeanCave is destroyed; Qt drops its receiver safely.
    New selections replace the pending input, never enqueue another worker.
    Every reference is computed in one pass, so switching between them is free.
    """

    curve_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, parse=None, ror_of=None):  # noqa: ANN001
        super().__init__(parent)
        # parse(fname) -> profile runs off the GUI thread; ror_of(profile) on it.
        self._parse = parse
        self._ror_of = ror_of
        self._profile = None
        self._reference: tuple[str, str] | None = None
        self._references: OrderedDict[str, tuple | None] = OrderedDict()
        self._generation = 0
        self._task = None
        self._pending = False
        self._cache: OrderedDict[AnalysisInput, dict] = OrderedDict()
        self._results: dict | None = None
        self._result: AnalysisResult | None = None
        self._observations: tuple[Observation, ...] = ()
        self._canvas = None
        self._axis = None
        self._highlight = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._start)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        # One row of controls: every pixel of height goes to the chart.
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.result_switch = SegmentedControl(
            [QApplication.translate('tilauscope_beancave', 'Summary'),
             QApplication.translate('tilauscope_beancave', 'Expert')], compact=True)
        self.result_switch.set_current(0)
        controls.addWidget(self.result_switch)
        controls.addSpacing(8)
        self.markers = QLabel()
        controls.addWidget(self.markers)
        controls.addStretch()
        self.model = QComboBox()
        self.model.addItem(QApplication.translate('tilauscope_beancave', 'Quadratic trend · x²'), 'quadratic')
        self.model.addItem(QApplication.translate('tilauscope_beancave', 'Cubic trend · x³'), 'cubic')
        self.model.addItem(QApplication.translate('tilauscope_beancave', 'Logarithmic trend · ln()'), 'logarithmic')
        self.model.setToolTip(QApplication.translate('tilauscope_beancave', 'Reference the measured RoR is compared with'))
        self.period = QComboBox()
        self.period.addItem(QApplication.translate('tilauscope_beancave', 'Dry end → Drop'), 'dry')
        self.period.addItem(QApplication.translate('tilauscope_beancave', '2 min before first crack → Drop'), 'crack')
        self.period.setToolTip(QApplication.translate('tilauscope_beancave', 'Analysed period'))
        for caption, combo in ((QApplication.translate('tilauscope_beancave', 'Reference'), self.model), (QApplication.translate('tilauscope_beancave', 'Period'), self.period)):
            controls.addWidget(_caption(caption))
            combo.setMinimumWidth(170)
            controls.addWidget(combo)
        self.settings = QPushButton(QApplication.translate('tilauscope_beancave', '⚙ Settings'))
        self.settings.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.settings.setMenu(self._settings_menu())
        controls.addWidget(self.settings)
        layout.addLayout(controls)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._message_page())
        self.pages.addWidget(self._loading_page())
        self.result_page = self._result_page()
        self.pages.addWidget(self.result_page)
        layout.addWidget(self.pages, 1)
        self._show_message(QApplication.translate('tilauscope_beancave', 'Select one roast to analyze.'))

        self.model.currentIndexChanged.connect(self._changed)
        self.period.currentIndexChanged.connect(self._changed)
        self.fit_period.currentIndexChanged.connect(self._changed)
        self.minimum_seconds.valueChanged.connect(self._changed)
        self.minimum_delta.valueChanged.connect(self._changed)

    # ── construction ───────────────────────────────────────────────────────

    def _settings_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss())
        panel = QWidget()
        panel.setMinimumWidth(340)
        column = QVBoxLayout(panel)
        column.setContentsMargins(12, 10, 12, 10)
        heading = QLabel(QApplication.translate('tilauscope_beancave', 'Analysis settings'))
        heading.setStyleSheet('font-weight: 600;')
        column.addWidget(heading)
        column.addWidget(_caption(QApplication.translate('tilauscope_beancave', 'The reference can be built over a different period from the one measured.')))
        form = QFormLayout()
        self.fit_period = QComboBox()
        self.fit_period.addItem(QApplication.translate('tilauscope_beancave', 'Same as the analysed period'), '')
        self.fit_period.addItem(QApplication.translate('tilauscope_beancave', 'Dry end'), 'dry')
        self.fit_period.addItem(QApplication.translate('tilauscope_beancave', '2 min before first crack'), 'crack')
        self.minimum_seconds = QDoubleSpinBox()
        self.minimum_seconds.setRange(0, 60)
        self.minimum_seconds.setValue(5)
        self.minimum_seconds.setSuffix(' s')
        self.minimum_delta = QDoubleSpinBox()
        self.minimum_delta.setRange(0, 10)
        self.minimum_delta.setValue(.5)
        self.minimum_delta.setSuffix(' °C/min')
        form.addRow(QApplication.translate('tilauscope_beancave', 'Start of the fit'), self.fit_period)
        form.addRow(QApplication.translate('tilauscope_beancave', 'Merge passages lasting at most'), self.minimum_seconds)
        form.addRow(QApplication.translate('tilauscope_beancave', 'Or deviating at most'), self.minimum_delta)
        column.addLayout(form)
        column.addWidget(_caption(QApplication.translate('tilauscope_beancave', 'RoR smoothing follows the curve settings. These thresholds '
                                      'group small oscillations; they are not quality limits.')))
        holder = QWidgetAction(menu)
        holder.setDefaultWidget(panel)
        menu.addAction(holder)
        return menu

    def _message_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.addStretch()
        self.message_glyph = QLabel('◷')
        self.message_glyph.setStyleSheet(f"font-size: 32px; color: {THEME['YELLOW']};")
        self.message_title = QLabel()
        self.message_title.setProperty('variant', 'section-title')
        self.message_text = _caption('')
        self.message_text.setFixedWidth(460)
        self.message_button = QPushButton(QApplication.translate('tilauscope_beancave', 'See the curve →'))
        self.message_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.message_button.clicked.connect(self.curve_requested)
        self.message_foot = _caption(QApplication.translate('tilauscope_beancave', 'The statistics remain available.'))
        for widget in (self.message_glyph, self.message_title, self.message_text,
                       self.message_button, self.message_foot):
            if isinstance(widget, QLabel):
                widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch()
        return page

    def _loading_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.addStretch()
        self.progress = TilauProgress(size=36)
        column.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel(QApplication.translate('tilauscope_beancave', 'Analysis in progress…'))
        title.setProperty('variant', 'section-title')
        column.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = _caption(QApplication.translate('tilauscope_beancave', 'You can keep browsing your roasts. Only the latest selection will be shown.'))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFixedWidth(420)
        column.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch()
        return page

    @staticmethod
    def _scrolled(body: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(body)
        return area

    def _result_page(self) -> QWidget:
        """Summary, Segments and Expert as sub-pages; the summary puts the chart beside its reading."""
        self.result_pages = QStackedWidget()
        self.result_switch.changed.connect(self.result_pages.setCurrentIndex)

        summary = QWidget()
        columns = QHBoxLayout(summary)
        columns.setContentsMargins(0, 4, 0, 0)
        columns.setSpacing(10)
        # The matplotlib canvas is created only when the first result is shown.
        self.plot_host = QVBoxLayout()
        columns.addLayout(self.plot_host, 1)

        side = QWidget()
        side.setFixedWidth(330)
        self.body_layout = QVBoxLayout(side)
        self.body_layout.setContentsMargins(0, 0, 6, 0)
        self.body_layout.setSpacing(6)
        metrics = QFrame()
        metrics.setProperty('variant', 'card')
        grid = QFormLayout(metrics)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setVerticalSpacing(4)
        self.metrics: list[tuple[QLabel, QLabel]] = []
        for _ in range(3):
            caption, value = _caption(''), QLabel('—')
            caption.setWordWrap(False)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setStyleSheet('font-weight: 600;')
            grid.addRow(caption, value)
            self.metrics.append((caption, value))
        self.body_layout.addWidget(metrics)

        segment = QFrame()
        segment.setProperty('variant', 'card')
        segment.setToolTip(QApplication.translate('tilauscope_beancave', 'Segments describe deviations from the reference, not roast defects. '
            'Small oscillations are merged. Swing is the change of peak deviation from the previous segment.'))
        segment_layout = QVBoxLayout(segment)
        segment_layout.setContentsMargins(10, 8, 10, 8)
        segment_layout.setSpacing(4)
        self.segment_title = QLabel()
        self.segment_title.setStyleSheet('font-weight: 600;')
        segment_layout.addWidget(self.segment_title)
        segment_grid = QFormLayout()
        segment_grid.setVerticalSpacing(2)
        self.segment_rows: list[QLabel] = []
        for name in (QApplication.translate('tilauscope_beancave', 'Position'), QApplication.translate('tilauscope_beancave', 'Peak deviation'),
                     QApplication.translate('tilauscope_beancave', 'Mean absolute deviation'), QApplication.translate('tilauscope_beancave', 'Swing')):
            value = QLabel('—')
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            caption = _caption(name)
            caption.setWordWrap(False)
            segment_grid.addRow(caption, value)
            self.segment_rows.append(value)
        segment_layout.addLayout(segment_grid)
        segment_layout.addWidget(_caption(QApplication.translate('tilauscope_beancave', 'Click the chart to inspect another segment.')))
        self.body_layout.addWidget(segment)

        self.examine_title = QLabel()
        self.examine_title.setStyleSheet('font-weight: 600;')
        self.examine_title.setToolTip(QApplication.translate('tilauscope_beancave', 'Observations, not a quality score'))
        self.body_layout.addWidget(self.examine_title)
        cards = QWidget()
        self.cards = QVBoxLayout(cards)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(6)
        cards_column = QVBoxLayout()
        cards_column.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setLayout(cards_column)
        cards_column.addWidget(cards)
        cards_column.addStretch()
        self.body_layout.addWidget(self._scrolled(holder), 1)
        columns.addWidget(side)
        self.result_pages.addWidget(summary)

        expert_body = QWidget()
        expert_layout = QVBoxLayout(expert_body)
        expert_layout.setContentsMargins(0, 4, 8, 0)
        self.models_table = QTableWidget(0, 5)
        self.models_table.setHorizontalHeaderLabels([
            QApplication.translate('tilauscope_beancave', 'Reference'), QApplication.translate('tilauscope_beancave', 'RMSE BT'), QApplication.translate('tilauscope_beancave', 'MSE BT'), QApplication.translate('tilauscope_beancave', 'Δ RoR at first crack'),
            QApplication.translate('tilauscope_beancave', 'Max / min Δ RoR')])
        self.models_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.models_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.models_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.models_table.verticalHeader().hide()
        self.models_table.setFixedHeight(150)
        expert_layout.addWidget(self.models_table)
        self.details = QLabel('')
        self.details.setWordWrap(True)
        self.details.setStyleSheet(f"font-size: 13px; color: {THEME['SUBTEXT1']};")
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        expert_layout.addWidget(self.details)
        note = QLabel(QApplication.translate('tilauscope_beancave', 
            'Closeness to a reference describes the shape of the profile. On its own it does not '
            'predict cup quality. All analysis results use Celsius.'))
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size: 13px; color: {THEME['SUBTEXT']};")
        expert_layout.addWidget(note)
        expert_layout.addStretch()
        self.result_pages.addWidget(self._scrolled(expert_body))
        return self.result_pages

    # ── inputs ─────────────────────────────────────────────────────────────

    def set_profile(self, data: dict, ror, ror_unit: str,
                    reference: tuple[str, str] | None = None) -> None:
        """reference is (file name, label) of the roast offered for comparison."""
        # No arrays copied and no maths on the ordinary navigation path.
        self._profile = (data, ror, ror_unit)
        ti = normalize_timeindex(data.get('timeindex', ()))
        complete = marked(ti, 0) and marked(ti, 6)
        self.markers.setText(QApplication.translate('tilauscope_beancave', '● CHARGE and DROP present') if complete else QApplication.translate('tilauscope_beancave', '● Markers incomplete'))
        self.markers.setStyleSheet(f"color: {THEME['SUCCESS' if complete else 'YELLOW']}; font-size: 12px;")
        self.markers.show()
        self._set_reference(reference)
        self._changed()

    def _set_reference(self, reference: tuple[str, str] | None) -> None:
        if reference is not None and self._parse is None:
            reference = None
        self._reference = reference
        at = self.model.findData('roast')
        self.model.blockSignals(True)
        try:
            if reference is None:
                if at >= 0:
                    if self.model.currentIndex() == at:
                        self.model.setCurrentIndex(0)
                    self.model.removeItem(at)
            else:
                label = QApplication.translate('tilauscope_beancave', 'Previous roast')
                if at < 0:
                    self.model.addItem(label, 'roast')
                    at = self.model.count() - 1
                self.model.setItemData(at, reference[1], Qt.ItemDataRole.ToolTipRole)
        finally:
            self.model.blockSignals(False)

    def clear_profile(self, message: str = '') -> None:
        self._profile = None
        self._generation += 1
        self._pending = False
        self._timer.stop()
        self.markers.hide()
        self._show_message(message or QApplication.translate('tilauscope_beancave', 'Select one roast to analyze.'))

    def _changed(self, *_args) -> None:
        self._generation += 1
        self._pending = self._profile is not None
        self._timer.stop()
        if self._pending:
            self._show_loading()
        if self.isVisible() and self._pending:
            self._timer.start(250)

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        if self._profile is not None:
            self._pending = True
            self._timer.start(0)

    def hideEvent(self, event) -> None:  # noqa: N802, ANN001
        self._timer.stop()
        super().hideEvent(event)

    # ── work ───────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _start(self) -> None:
        if not self.isVisible() or self._profile is None or self._task is not None:
            return
        data, ror, unit = self._profile
        reference: dict = {}
        if self.model.currentData() == 'roast' and self._reference is not None:
            fname = self._reference[0]
            if fname not in self._references:
                self._show_loading()
                self._task = _ReferenceTask(fname, self._parse)
                self._task.signals.finished.connect(self._reference_loaded)
                QThreadPool.globalInstance().start(self._task)
                return
            loaded = self._references[fname]
            if loaded is None:
                self._pending = False
                self._show_error('reference')
                return
            ref_data, ref_ror = loaded
            reference = {'reference_times': tuple(ref_data.get('timex', ())),
                         'reference_temperatures': tuple(ref_data.get('temp2', ())),
                         'reference_ror': tuple(ref_ror),
                         'reference_milestones': tuple(ref_data.get('timeindex', ())),
                         'reference_unit': str(ref_data.get('mode') or unit)}
        try:
            source = AnalysisInput(tuple(data.get('timex', ())), tuple(data.get('temp2', ())),
                                   tuple(ror) if ror is not None else (),
                                   tuple(data.get('timeindex', ())), str(data.get('mode') or unit), unit,
                                   '', self.period.currentData(),
                                   self.minimum_seconds.value(), self.minimum_delta.value(),
                                   self.fit_period.currentData(), **reference)
            cached = self._cache.get(source)
        except (TypeError, ValueError):
            self._pending = False
            self._show_error('readings')
            return
        self._pending = False
        if cached is not None:
            self._cache.move_to_end(source)
            self._render(cached)
            return
        self._show_loading()
        self._task = _AnalysisTask(self._generation, source)
        self._task.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(self._task)

    @pyqtSlot(int, object, object, str)
    def _reference_loaded(self, _generation: int, fname: str, data, _error: str) -> None:
        self._task = None
        ror = None
        if data is not None and self._ror_of is not None:
            try:
                ror = self._ror_of(data)
            except Exception:  # noqa: BLE001  a slot: an escape would close the application
                _log.exception('reference roast RoR could not be computed')
        self._references[fname] = (data, ror) if ror is not None else None
        while len(self._references) > 4:
            self._references.popitem(last=False)
        if self.isVisible() and self._profile is not None:
            self._timer.start(0)

    @pyqtSlot(int, object, object, str)
    def _finished(self, generation: int, source: AnalysisInput, results, error: str) -> None:
        self._task = None
        if results is not None:
            self._cache[source] = results
            self._cache.move_to_end(source)
            while len(self._cache) > 12:
                self._cache.popitem(last=False)
        if generation == self._generation and self.isVisible():
            if error:
                self._show_error(error)
            else:
                self._render(results)
        if self._pending and self.isVisible():
            self._timer.start(250)

    # ── states ─────────────────────────────────────────────────────────────

    def _show_loading(self) -> None:
        self.result_switch.hide()
        self.pages.setCurrentIndex(1)

    def _show_message(self, text: str, title: str = '', curve: bool = False) -> None:
        self.message_glyph.setVisible(bool(title))
        self.message_title.setText(title)
        self.message_title.setVisible(bool(title))
        self.message_text.setText(text)
        self.message_button.setVisible(curve)
        self.message_foot.setVisible(bool(title))
        self.result_switch.hide()
        self.pages.setCurrentIndex(0)

    def _show_error(self, code: str) -> None:
        titles = {
            'charge_drop': QApplication.translate('tilauscope_beancave', 'The CHARGE or DROP marker is missing'),
            'dry': QApplication.translate('tilauscope_beancave', 'The dry-end marker is missing'),
            'crack': QApplication.translate('tilauscope_beancave', 'The first-crack marker is missing'),
            'reference': QApplication.translate('tilauscope_beancave', 'The reference roast cannot be compared'),
            'units': QApplication.translate('tilauscope_beancave', 'The temperature unit is not recognized'),
            'readings': QApplication.translate('tilauscope_beancave', 'Readings are incomplete'),
        }
        self._result = None
        self._show_message(self._error_text(code), titles.get(code, QApplication.translate('tilauscope_beancave', 'This reference could not be fitted')),
                           code in ('charge_drop', 'dry', 'crack'))

    @staticmethod
    def _error_text(code: str) -> str:
        if code == 'charge_drop':
            return QApplication.translate('tilauscope_beancave', 'The analysis needs CHARGE and DROP to delimit the roast. Check the markers in Curve.')
        if code == 'dry':
            return QApplication.translate('tilauscope_beancave', 'Dry end is missing or outside the roast. Check the marker or choose the first-crack period.')
        if code == 'crack':
            return QApplication.translate('tilauscope_beancave', 'A first-crack marker is required for this period.')
        if code == 'reference':
            return QApplication.translate('tilauscope_beancave', 'The previous roast needs CHARGE, DROP and readings covering the analysed period. '
                       'Choose a trend as reference instead.')
        if code == 'units':
            return QApplication.translate('tilauscope_beancave', 'The temperature unit is not recognized.')
        if code == 'readings':
            return QApplication.translate('tilauscope_beancave', 'Analysis needs at least six valid BT and RoR samples, with strictly increasing times, over the selected period.')
        return QApplication.translate('tilauscope_beancave', 'This model could not be fitted. Try another reference or period.')

    # ── result ─────────────────────────────────────────────────────────────

    def _model_name(self, model: str, short: bool = False) -> str:
        if short:
            return {'quadratic': 'x²', 'cubic': 'x³', 'logarithmic': 'ln()'}.get(model, QApplication.translate('tilauscope_beancave', 'Previous roast'))
        return self.model.itemText(max(0, self.model.findData(model)))

    def _render(self, results: dict) -> None:
        self._results = results
        model = self.model.currentData()
        result = results.get(model)
        if not isinstance(result, AnalysisResult):
            self._show_error(result if isinstance(result, str) else 'fit')
            return
        self._result = result
        self._observations = observations(result)
        self._fill_tiles(result)
        self._fill_observations()
        self._fill_expert(results, result, model)
        self._plot(result)
        self.result_switch.show()
        self.pages.setCurrentIndex(2)
        passages = [i for i, o in enumerate(self._observations) if o.segment is not None]
        if passages:
            self._pick_observation(passages[0])
        elif result.segments:
            self._select_segment(max(range(len(result.segments)),
                                     key=lambda i: result.segments[i].mean_absolute))
        self._canvas.draw_idle()

    def _fill_tiles(self, result: AnalysisResult) -> None:
        rows = [(QApplication.translate('tilauscope_beancave', 'BT deviation (RMSE)'), f'{result.rmse_bt:.2f} °C',
                 QApplication.translate('tilauscope_beancave', 'Overall temperature deviation · closeness to the reference'), ''),
                (QApplication.translate('tilauscope_beancave', 'Mean RoR deviation'), f'{result.mean_absolute:.2f} °C/min',
                 QApplication.translate('tilauscope_beancave', 'Mean absolute RoR deviation · area between curves / duration'), '')]
        if result.fc_delta is None:
            rows.append((QApplication.translate('tilauscope_beancave', 'RoR deviation at first crack'), '—',
                         QApplication.translate('tilauscope_beancave', 'First crack unmarked or outside the period'), ''))
        else:
            rows.append((QApplication.translate('tilauscope_beancave', 'RoR deviation at first crack'), f'{result.fc_delta:+.2f} °C/min',
                         QApplication.translate('tilauscope_beancave', 'Measured RoR below the reference') if result.fc_delta < 0
                         else QApplication.translate('tilauscope_beancave', 'Measured RoR above the reference'),
                         THEME['YELLOW'] if abs(result.fc_delta) >= NOTABLE_DELTA else ''))
        for (caption, value), (name, figure, tip, colour) in zip(self.metrics, rows, strict=True):
            caption.setText(name)
            value.setText(figure)
            value.setStyleSheet(f"font-weight: 600; color: {colour or THEME['TEXT']};")
            for label in (caption, value):
                label.setToolTip(tip)

    def _observation_text(self, observation: Observation, reference: str) -> tuple[str, str, str, str]:
        """Title, facts, what it indicates, what to check — worded as observations, never verdicts."""
        start, end = _clock(observation.start), _clock(observation.end)
        deviation = QApplication.translate('tilauscope_beancave', 'Largest deviation: {peak} °C/min · Mean deviation: {mean} °C/min.').format(
            peak=f'{observation.peak:+.2f}', mean=f'{observation.mean_absolute:.2f}')
        cupping = QApplication.translate('tilauscope_beancave', 'Confirm any effect on taste by cupping.')
        if observation.kind == 'crash':
            return (QApplication.translate('tilauscope_beancave', 'Sharp RoR drop (crash)'),
                    QApplication.translate('tilauscope_beancave', '{start}–{end} · The measured RoR dips by {size} °C/min before recovering.').format(
                        start=start, end=end, size=f'{observation.prominence:.1f}') + '\n' + deviation,
                    QApplication.translate('tilauscope_beancave', 'The RoR falls faster than a steady decline and forms a real dip. Around first crack, '
                        'moisture release cools the beans, and a late or strong heat cut adds to it. '
                        'A marked crash is often linked to flat, less sweet cups.'),
                    QApplication.translate('tilauscope_beancave', 'Heat and airflow changes in the minute before the dip, and the position of the '
                        'first-crack marker.') + ' ' + cupping)
        if observation.kind == 'flick':
            return (QApplication.translate('tilauscope_beancave', 'RoR rising again (flick)'),
                    QApplication.translate('tilauscope_beancave', '{start}–{end} · The measured RoR rises by {size} °C/min after slowing.').format(
                        start=start, end=end, size=f'{observation.prominence:.1f}') + '\n' + deviation,
                    QApplication.translate('tilauscope_beancave', 'After slowing, the RoR climbs again late in the roast, often because heat was added '
                        'to catch a crash. A late rise speeds up development and is often linked to roasty '
                        'or harsh notes.'),
                    QApplication.translate('tilauscope_beancave', 'Heat changes before the rise; an earlier, gentler adjustment usually avoids the '
                        'crash-and-flick pair.') + ' ' + cupping)
        if observation.kind == 'flat':
            return (QApplication.translate('tilauscope_beancave', 'The RoR does not decline over the period'),
                    QApplication.translate('tilauscope_beancave', 'Overall trend of the measured RoR: {slope} °C/min per minute. '
                        'The reference trend: {reference} °C/min per minute.').format(
                        slope=f'{observation.peak:+.2f}', reference=f'{self._result.reference_slope:+.2f}'),
                    QApplication.translate('tilauscope_beancave', 'A RoR that declines steadily from its peak to the drop is a widely used guideline '
                        'for even development. A flat or rising trend means the roast kept accelerating.'),
                    QApplication.translate('tilauscope_beancave', 'When and how the heat was reduced after the RoR peak.') + ' ' + cupping)
        below = observation.kind == 'below'
        facts = (QApplication.translate('tilauscope_beancave', '{start}–{end} · For {seconds} s the RoR stays below {reference}.') if below
                 else QApplication.translate('tilauscope_beancave', '{start}–{end} · For {seconds} s the RoR stays above {reference}.')).format(
            start=start, end=end, seconds=int(observation.end - observation.start), reference=reference)
        if below:
            return (QApplication.translate('tilauscope_beancave', 'Slower than the reference'), facts + '\n' + deviation,
                    QApplication.translate('tilauscope_beancave', 'The roast progresses more slowly than the reference on this passage. A sudden '
                        'fall at its start, around first crack, is the usual crash pattern; a gradual one means '
                        'the heat was eased earlier than the trend. After first crack a slowdown lengthens '
                        'development; a long one can give flat or baked notes.'),
                    QApplication.translate('tilauscope_beancave', 'Where the fall starts on the chart, and the heat and airflow changes just before '
                        'it.') + ' ' + cupping)
        return (QApplication.translate('tilauscope_beancave', 'Faster than the reference'), facts + '\n' + deviation,
                QApplication.translate('tilauscope_beancave', 'The roast progresses faster than the reference on this passage. Before first crack it '
                    'shortens Maillard; after it, it shortens development and can bring roasty notes.'),
                QApplication.translate('tilauscope_beancave', 'Heat and airflow changes before this passage.') + ' ' + cupping)

    def _fill_observations(self) -> None:
        while self.cards.count():
            widget = self.cards.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        count = len(self._observations)
        self.examine_title.setText(
            QApplication.translate('tilauscope_beancave', 'To examine · 1 passage') if count == 1 else QApplication.translate('tilauscope_beancave', 'To examine · {n} passages').format(n=count))
        reference = (QApplication.translate('tilauscope_beancave', 'the previous roast') if self.model.currentData() == 'roast'
                     else QApplication.translate('tilauscope_beancave', 'the reference trend'))
        for number, observation in enumerate(self._observations, 1):
            title, facts, indicates, check = self._observation_text(observation, reference)
            phase = {1: QApplication.translate('tilauscope_beancave', 'Drying'), 2: QApplication.translate('tilauscope_beancave', 'Maillard'), 3: QApplication.translate('tilauscope_beancave', 'Development')}.get(observation.phase)
            if phase:
                title += ' · ' + phase
            card = _ObservationCard(number, title, facts, indicates, check)
            card.picked.connect(self._pick_observation)
            self.cards.addWidget(card)
        if not count:
            self.cards.addWidget(_caption(QApplication.translate('tilauscope_beancave', 
                'Nothing to examine: the RoR stays within {delta} °C/min of the reference and shows no '
                'marked dip or rise.').format(delta=f'{NOTABLE_DELTA:.0f}')))

    def _fill_expert(self, results: dict, result: AnalysisResult, model: str) -> None:
        rows = [m for m in MODELS + ('roast',) if m in results]
        self.models_table.setRowCount(len(rows))
        for row, name in enumerate(rows):
            other = results[name]
            if isinstance(other, AnalysisResult):
                cells = (self._model_name(name, True), f'{other.rmse_bt:.2f} °C', f'{other.mse_bt:.2f} °C²',
                         f'{other.fc_delta:+.2f} °C/min' if other.fc_delta is not None else '—',
                         f'{other.maximum:+.2f} / {other.minimum:+.2f}')
            else:
                cells = (self._model_name(name, True), QApplication.translate('tilauscope_beancave', 'Unavailable'), '', '', '')
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if name == model:
                    item.setForeground(QColor(THEME['ACCENT']))
                self.models_table.setItem(row, col, item)

        def number(value: float | None, digits: int = 4) -> str:
            return f'{value:.{digits}f}' if value is not None else '—'

        if model == 'roast':
            method = QApplication.translate('tilauscope_beancave', 'Reference compared: the previous roast, aligned on CHARGE and cut at the earlier DROP.')
        else:
            method = QApplication.translate('tilauscope_beancave', 'BT(t) = {equation}, with t in seconds from CHARGE, fitted from {start}.').format(
                equation=result.equation, start=_clock(result.fit_start))
        self.details.setText(QApplication.translate('tilauscope_beancave', 
            '{method}\nR² BT: {r2bt} · R² RoR: {r2ror} · RMSE RoR: {rmse} °C/min\n'
            'Measured RoR at first crack: {fcror} °C/min\n'
            'RoR trend over the period: measured {slope} · reference {refslope} °C/min per minute\n'
            'BT fitting and error use raw readings; the reference RoR is the derivative of the fitted BT. '
            'The measured RoR is the BeanCave curve with its current smoothing, so results can differ '
            'slightly from Artisan Analyzer. Crashes and flicks are dips and rises of the measured RoR '
            'of at least {delta} °C/min, whatever the reference.').format(
                method=method, r2bt=number(result.r2_bt), r2ror=number(result.r2_ror),
                rmse=f'{result.rmse_ror:.2f}',
                fcror=f'{result.fc_ror:.2f}' if result.fc_ror is not None else '—',
                slope=f'{result.ror_slope:+.2f}', refslope=f'{result.reference_slope:+.2f}',
                delta=f'{NOTABLE_DELTA:.0f}'))

    def _plot(self, result: AnalysisResult) -> None:
        from matplotlib.ticker import FuncFormatter
        if self._canvas is None:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
            self._canvas = FigureCanvasQTAgg(Figure(figsize=(7, 2.8), layout='constrained'))
            self._canvas.setMinimumHeight(180)
            self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._canvas.mpl_connect('button_press_event', self._chart_clicked)
            self.plot_host.addWidget(self._canvas)
        figure = self._canvas.figure
        figure.clear()
        figure.set_facecolor(THEME['SURFACE'])
        axis = figure.add_subplot(111)
        self._axis = axis
        axis.set_facecolor(THEME['SURFACE'])
        axis.plot(result.times, result.actual_ror, color=THEME['ACCENT'], linewidth=2,
                  label=QApplication.translate('tilauscope_beancave', 'Measured RoR'))
        axis.plot(result.times, result.reference_ror, color=THEME['YELLOW'], linestyle='--',
                  linewidth=1.5, label=self._model_name(self.model.currentData()))
        axis.set_ylabel('°C/min', color=THEME['SUBTEXT'], fontsize=8)
        axis.xaxis.set_major_formatter(FuncFormatter(lambda x, _pos: _clock(x)))
        axis.tick_params(colors=THEME['SUBTEXT'], labelsize=8)
        axis.grid(axis='y', color=THEME['BORDER'], linewidth=.8)
        for spine in axis.spines.values():
            spine.set_visible(False)
        axis.set_xlim(result.times[0], result.times[-1])
        end = (QApplication.translate('tilauscope_beancave', 'Drop') if result.times[-1] >= result.drop_time
               else QApplication.translate('tilauscope_beancave', 'End'))
        marks = [(result.times[0], QApplication.translate('tilauscope_beancave', 'Start')), (result.times[-1], end)]
        if result.dry_time is not None and result.times[0] <= result.dry_time <= result.times[-1]:
            marks[0] = (result.dry_time, QApplication.translate('tilauscope_beancave', 'Dry end'))
        if result.fc_time is not None:
            marks.append((result.fc_time, QApplication.translate('tilauscope_beancave', 'First crack')))
        transform = axis.get_xaxis_transform()
        span = float(result.times[-1] - result.times[0])
        previous = None
        for when, name in sorted(marks):
            axis.axvline(when, color=THEME['OVERLAY0'], linestyle=(0, (3, 5)), linewidth=1)
            align = 'left' if when == result.times[0] else 'right' if when == result.times[-1] else 'center'
            # Two markers close together would print over each other: the later one goes a line up.
            lifted = previous is not None and when - previous < .2 * span
            axis.text(when, 1.10 if lifted else 1.02, f'{name} · {_clock(when)}', transform=transform,
                      ha=align, va='bottom', fontsize=8, color=THEME['SUBTEXT'])
            previous = None if lifted else when
        for number, observation in enumerate(self._observations, 1):
            if observation.segment is None:
                continue
            at = self._peak_index(result, observation)
            axis.plot(result.times[at], result.actual_ror[at], 'o', color=THEME['YELLOW'], markersize=6)
            axis.annotate(str(number), (result.times[at], result.actual_ror[at]), xytext=(0, -14),
                          textcoords='offset points', ha='center', fontsize=8, color=THEME['YELLOW'])
        axis.legend(loc='upper right', frameon=False, labelcolor=THEME['SUBTEXT'], fontsize=8)
        self._highlight = None

    @staticmethod
    def _peak_index(result: AnalysisResult, observation: Observation) -> int:
        lo, hi = (int(v) for v in result.times.searchsorted((observation.start, observation.end)))
        hi = max(hi, lo + 1)
        if observation.kind in ('crash', 'flick'):
            values = result.actual_ror[lo:hi]
            return lo + int(values.argmin() if observation.kind == 'crash' else values.argmax())
        residual = result.actual_ror[lo:hi] - result.reference_ror[lo:hi]
        return lo + int(abs(residual).argmax())

    @pyqtSlot(int)
    def _pick_observation(self, index: int) -> None:
        if not 0 <= index < len(self._observations):
            return
        segment = self._observations[index].segment
        if segment is not None:
            self._select_segment(segment)

    def _chart_clicked(self, event) -> None:  # noqa: ANN001
        # Called from the canvas's mouse event: an escape here would close the application.
        try:
            if self._result is None or event.inaxes is not self._axis or event.xdata is None:
                return
            for index, segment in enumerate(self._result.segments):
                if segment.start <= event.xdata <= segment.end:
                    self._select_segment(index)
                    return
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception('segment selection from the chart failed')

    def _select_segment(self, index: int) -> None:
        if self._result is None or self._axis is None or not 0 <= index < len(self._result.segments):
            return
        segment = self._result.segments[index]
        below = segment.peak < 0
        self.segment_title.setText(QApplication.translate('tilauscope_beancave', 'Segment {start} → {end} · {duration}').format(
            start=_clock(segment.start), end=_clock(segment.end), duration=_clock(segment.end - segment.start)))
        values = (QApplication.translate('tilauscope_beancave', 'Below the reference') if below else QApplication.translate('tilauscope_beancave', 'Above the reference'),
                  f'{segment.peak:+.2f} °C/min', f'{segment.mean_absolute:.2f} °C/min',
                  f'{segment.swing:+.2f} °C/min' if segment.swing is not None else '—')
        for number, (label, text) in enumerate(zip(self.segment_rows, values, strict=True)):
            label.setText(text)
            label.setStyleSheet(f"color: {THEME['YELLOW'] if below and number < 2 else THEME['TEXT']};")
        if self._highlight is not None:
            self._highlight.remove()
        self._highlight = self._axis.axvspan(segment.start, segment.end, color=THEME['YELLOW'], alpha=.10)
        self._canvas.draw_idle()
