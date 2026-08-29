# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Semantic assistant for Artisan's software PID.

The historic window exposed and modified Kp/Ki/Kd heuristically. This version
keeps engineering values behind an expert disclosure and lets the operator act
on observable behaviours: react, catch up, brake and stabilise.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Final, TYPE_CHECKING, TypedDict

from PyQt6.QtCore import QPoint, QPropertyAnimation, QStandardPaths, Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from tilauscope.pid_calibration import (
    CalibrationLimits,
    CalibrationProtocol,
    CalibrationReadinessInputs,
    CalibrationReadinessReport,
    CalibrationRuntimeInterlocks,
    LiveCalibrationCoordinator,
    PIDCandidate,
    ZeroOutputQualification,
    evaluate_calibration_readiness,
    runtime_interlock_reason,
    run_reference_simulation,
)
from tilauscope.pid_calibration_store import (
    CalibrationMachineIdentity,
    build_machine_identity,
    write_hardware_pilot_manifest,
    write_calibration_journal,
    write_zero_qualification_evidence,
)
from tilauscope.pid_calibration_runner import (
    LiveCalibrationSampleObserver,
    PIDCalibrationRunner,
    temperature_to_c,
)
from tilauscope.pid_semantics import (
    Behaviour,
    PIDNarrative,
    PIDObservation,
    adjust_pid_behaviour,
    narrate_pid,
)
from tilauscope.roasters import RoasterManager
from tilauscope.tilauscope_types import THEME, show_styled_message
from tilauscope.theme_qss import apply_tilau_theme

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow


_log: Final[logging.Logger] = logging.getLogger(__name__)


class _EngineSnapshot(TypedDict):
    active: bool
    pv: float | None
    target: float
    p: float
    i: float
    d: float
    output: float | None
    output_min: float
    output_max: float
    kp: float | None
    ki: float | None
    kd: float | None


class PIDAutotune(QDialog):
    """Explain and adjust Artisan's software PID without exposing raw gains."""

    # Filled one exact (roaster_id, actuator_signature) pair at a time only
    # after its physical pilot passes. The shipped empty set cannot heat.
    _LIVE_CALIBRATION_ACTUATORS: Final[
        frozenset[tuple[str, str]]
    ] = frozenset()
    # First reduced-risk pilot: current ITOP Cyberroaster + exact slider-4
    # actuator from the operator's 2026-08-28 configuration. A successful run
    # is always cut to 0% and rolled back for review; it cannot retain gains.
    _SUPERVISED_PILOT_ACTUATORS: Final[frozenset[tuple[str, str]]] = frozenset({
        (
            "itop-cyberroaster",
            "559c368d9f76411191563ecb16bb67f2012eecc30ca8a8d1be7a5506c11af947",
        ),
    })
    _CONFIG_FIELDS: Final[tuple[str, ...]] = (
        "pidKp", "pidKi", "pidKd",
        "pidKp1", "pidKi1", "pidKd1",
        "pidKp2", "pidKi2", "pidKd2",
        "pidGainScheduling", "pidGainSchedulingSV",
        "pidGainSchedulingQuadratic",
        "pidSchedule0", "pidSchedule1", "pidSchedule2",
        "pidPsetpointWeight", "pidDsetpointWeight",
        "pidSource", "pidCycle",
        "pidPositiveTarget", "pidNegativeTarget", "invertControl",
        "dutyMin", "dutyMax", "dutySteps", "duty_filter",
        "derivative_filter", "pidDlimit",
        "pidIlimitFactor", "pidIWP", "pidIRoC", "pidIRoCthreshold",
        "sv_filter",
        "positiveTargetRangeLimit", "positiveTargetMin", "positiveTargetMax",
        "negativeTargetRangeLimit", "negativeTargetMin", "negativeTargetMax",
    )
    _OFFSET_MIN: Final[int] = -2
    _OFFSET_MAX: Final[int] = 2
    _SETTLE_WAIT_MS: Final[int] = 15_000

    def __init__(self, parent: QWidget | None, aw: ApplicationWindow) -> None:
        # A frameless modeless child can be constructed but never presented as
        # a native window on macOS. Keep ownership only for a visible parent
        # and explicitly retain the Dialog window type below.
        visible_parent = parent if parent is not None and parent.isVisible() else None
        super().__init__(visible_parent)
        apply_tilau_theme(self, ground=False)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(False)

        self.aw = aw
        self.pid = aw.pidcontrol
        self.is_monitoring = False
        self._cooling_down = False
        self._pv_history: deque[tuple[float, float]] = deque(maxlen=8)
        self._readiness_history: deque[
            tuple[float, float, float, float]
        ] = deque(maxlen=45)
        self._error_history: deque[float] = deque(maxlen=90)
        self._candidate_state: str | None = None
        self._candidate_count = 0
        self._calibration_engineering = ""
        self._zero_output_qualified = False
        self._qualified_machine_fingerprint: str | None = None
        self._calibration_runner: PIDCalibrationRunner | None = None
        self._last_calibration_journal_path: Path | None = None
        self._current_narrative = PIDNarrative("stopped", "high")
        self._latest_schedule_value = 0.0
        self._baseline_config: dict[str, float | int | bool] | None = None
        self._undo_stack: list[
            tuple[dict[str, float | int | bool], dict[Behaviour, int]]
        ] = []
        self._offsets: dict[Behaviour, int] = {
            "reaction": 0,
            "recovery": 0,
            "braking": 0,
            "stability": 0,
        }
        self._behaviour_widgets: dict[
            Behaviour, tuple[QPushButton, QLabel, QPushButton]
        ] = {}
        self.anim: QPropertyAnimation | None = None
        self.oldPos = QPoint()

        # setup_ui() replaces these placeholders immediately.  Initialising
        # them here makes their lifetime explicit to static type checkers too.
        self.lbl_headline = QLabel()
        self.lbl_reason = QLabel()
        self.lbl_suggestion = QLabel()
        self.lbl_pv = QLabel()
        self.lbl_sp = QLabel()
        self.lbl_output = QLabel()
        self.scope_combo = QComboBox()
        self.lbl_change = QLabel()
        self.lbl_calibration = QLabel()
        self.btn_calibration_check = QPushButton()
        self.btn_calibration_live = QPushButton()
        self.btn_undo = QPushButton()
        self.btn_restore = QPushButton()
        self.btn_keep = QPushButton()
        self.lbl_engineering = QLabel()
        self.btn_start = QPushButton()
        self.btn_stop = QPushButton()

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_logic)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._settle_wait_finished)

        self.setup_ui()
        self.aw.PIDAutotuneMenuAction.setChecked(True)
        self._render_narrative(self._current_narrative, None, None)
        self._update_behaviour_controls()

    def setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        container = QFrame()
        container.setObjectName("PIDAssistantContainer")
        container.setStyleSheet(
            f"QFrame#PIDAssistantContainer {{ background-color: {THEME['BG']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 20px; }}"
        )
        shell = QVBoxLayout(container)
        shell.setContentsMargins(22, 18, 22, 20)
        shell.setSpacing(12)
        content_scroll = QScrollArea()
        content_scroll.setObjectName("PIDAssistantScroll")
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        content_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        content_body = QWidget()
        content_body.setStyleSheet("background: transparent;")
        content = QVBoxLayout(content_body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        content_scroll.setWidget(content_body)
        main_layout.addWidget(container)

        header = QHBoxLayout()
        title = QLabel(QApplication.translate("tilauscope_pid", "UNDERSTAND AND ADJUST THE PID"))
        title.setStyleSheet("color:white; font-size:18px; font-weight:900; border:none;")
        help_btn = QPushButton("?")
        help_btn.setFixedSize(26, 26)
        help_btn.setProperty("variant", "icon")
        help_btn.clicked.connect(self.show_help)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setProperty("variant", "icon")
        close_btn.clicked.connect(self.fade_out_and_close)
        close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {THEME['SURFACE']}; color: white;"
            f" border-radius: 15px; border: 1px solid {THEME['BORDER']}; }}"
            f"QPushButton:hover {{ background-color: {THEME['CRITICAL']}; }}"
        )
        header.addWidget(title)
        header.addWidget(help_btn)
        header.addStretch()
        header.addWidget(close_btn)
        shell.addLayout(header)
        shell.addWidget(content_scroll, 1)

        intro = QLabel(QApplication.translate("tilauscope_pid", 
            "TilauScope translates Artisan's calculations into machine behaviour. "
            "Technical PID values stay hidden."
        ))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{THEME['SUBTEXT']}; border:none;")
        content.addWidget(intro)

        calibration_group = QGroupBox(QApplication.translate("tilauscope_pid", "AUTOMATIC TEST — ABOUT 10 MINUTES"))
        calibration_group.setStyleSheet(self._group_style())
        calibration_layout = QVBoxLayout(calibration_group)
        calibration_intro = QLabel(QApplication.translate("tilauscope_pid", 
            "The future guided test will observe a small heat increase and decrease, "
            "try a cautious setting, then keep it only if the response improves."
        ))
        calibration_intro.setWordWrap(True)
        calibration_intro.setStyleSheet(f"color:{THEME['TEXT']}; border:none;")
        self.lbl_calibration = QLabel(QApplication.translate("tilauscope_pid", 
            "First validate the complete procedure in software. No heat command is sent."
        ))
        self.lbl_calibration.setWordWrap(True)
        self.lbl_calibration.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:12px; border:none;"
        )
        calibration_buttons = QHBoxLayout()
        self.btn_calibration_check = self._secondary_button(
            QApplication.translate("tilauscope_pid", "CHECK WITHOUT HEATING")
        )
        self.btn_calibration_live = self._primary_button(
            QApplication.translate("tilauscope_pid", "PREPARE THE MACHINE TEST")
        )
        self.btn_calibration_live.setToolTip(QApplication.translate("tilauscope_pid", 
            "Review every automatic check and the three confirmations."
        ))
        self.btn_calibration_check.clicked.connect(self._run_calibration_self_test)
        self.btn_calibration_live.clicked.connect(self.show_calibration_readiness)
        calibration_buttons.addWidget(self.btn_calibration_check)
        calibration_buttons.addWidget(self.btn_calibration_live)
        calibration_layout.addWidget(calibration_intro)
        calibration_layout.addWidget(self.lbl_calibration)
        calibration_layout.addLayout(calibration_buttons)
        content.addWidget(calibration_group)

        state_card = QFrame()
        state_card.setStyleSheet(
            f"QFrame {{ background-color: {THEME['SURFACE']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 12px; }}"
        )
        state_layout = QVBoxLayout(state_card)
        state_layout.setContentsMargins(16, 14, 16, 14)
        self.lbl_headline = QLabel()
        self.lbl_headline.setWordWrap(True)
        self.lbl_headline.setStyleSheet(
            f"color:{THEME['ACCENT']}; font-size:17px; font-weight:800;"
        )
        self.lbl_reason = QLabel()
        self.lbl_reason.setWordWrap(True)
        self.lbl_reason.setStyleSheet(f"color:{THEME['TEXT']}; font-size:13px;")
        self.lbl_suggestion = QLabel()
        self.lbl_suggestion.setWordWrap(True)
        self.lbl_suggestion.setStyleSheet(
            f"color:{THEME['WARNING']}; font-size:12px; font-weight:600;"
        )
        state_layout.addWidget(self.lbl_headline)
        state_layout.addWidget(self.lbl_reason)
        state_layout.addWidget(self.lbl_suggestion)

        facts = QHBoxLayout()
        self.lbl_pv = self._fact(facts, QApplication.translate("tilauscope_pid", "TEMPERATURE"))
        self.lbl_sp = self._fact(facts, QApplication.translate("tilauscope_pid", "TARGET"))
        self.lbl_output = self._fact(facts, QApplication.translate("tilauscope_pid", "HEAT REQUEST"))
        state_layout.addLayout(facts)
        content.addWidget(state_card)

        behaviour_group = QGroupBox(QApplication.translate("tilauscope_pid", "CHANGE THE BEHAVIOUR"))
        behaviour_group.setStyleSheet(self._group_style())
        behaviour_grid = QGridLayout(behaviour_group)
        behaviour_grid.setHorizontalSpacing(10)
        behaviour_grid.setVerticalSpacing(8)

        rows: tuple[tuple[Behaviour, str, str, str, int, int], ...] = (
            ("reaction", QApplication.translate("tilauscope_pid", "CURRENT GAP"), QApplication.translate("tilauscope_pid", "React less"),
             QApplication.translate("tilauscope_pid", "React more"), -1, 1),
            ("recovery", QApplication.translate("tilauscope_pid", "LASTING DELAY"), QApplication.translate("tilauscope_pid", "Catch up less"),
             QApplication.translate("tilauscope_pid", "Catch up more"), -1, 1),
            ("braking", QApplication.translate("tilauscope_pid", "INERTIA"), QApplication.translate("tilauscope_pid", "Brake less"),
             QApplication.translate("tilauscope_pid", "Brake more"), -1, 1),
            # Visual axis is stable -> active, while the semantic core receives
            # +1 for calmer and -1 for more active.
            ("stability", QApplication.translate("tilauscope_pid", "COMMAND"), QApplication.translate("tilauscope_pid", "More stable"),
             QApplication.translate("tilauscope_pid", "More responsive"), 1, -1),
        )
        for row, (behaviour, label, left_text, right_text, left_dir, right_dir) in enumerate(rows):
            name = QLabel(label)
            name.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-weight:700; border:none;")
            left = self._semantic_button(left_text)
            right = self._semantic_button(right_text)
            indicator = QLabel("○  ○  ●  ○  ○")
            indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
            indicator.setMinimumWidth(120)
            indicator.setStyleSheet(
                f"color:{THEME['ACCENT']}; font-size:15px; font-weight:800; border:none;"
            )
            left.clicked.connect(partial(self._apply_behaviour, behaviour, left_dir, -1))
            right.clicked.connect(partial(self._apply_behaviour, behaviour, right_dir, 1))
            behaviour_grid.addWidget(name, row, 0)
            behaviour_grid.addWidget(left, row, 1)
            behaviour_grid.addWidget(indicator, row, 2)
            behaviour_grid.addWidget(right, row, 3)
            self._behaviour_widgets[behaviour] = (left, indicator, right)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel(QApplication.translate("tilauscope_pid", "Apply the change:")))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems([
            QApplication.translate("tilauscope_pid", "in this temperature zone"),
            QApplication.translate("tilauscope_pid", "throughout the whole range"),
        ])
        scope_row.addWidget(self.scope_combo)
        scope_row.addStretch()
        behaviour_grid.addLayout(scope_row, len(rows), 0, 1, 4)
        content.addWidget(behaviour_group)

        self.lbl_change = QLabel()
        self.lbl_change.setWordWrap(True)
        self.lbl_change.setStyleSheet(
            f"color:{THEME['LAVENDER']}; font-size:12px; border:none;"
        )
        content.addWidget(self.lbl_change)

        history_row = QHBoxLayout()
        self.btn_undo = self._secondary_button(QApplication.translate("tilauscope_pid", "UNDO LAST CHANGE"))
        self.btn_restore = self._secondary_button(QApplication.translate("tilauscope_pid", "RESTORE SESSION START"))
        self.btn_keep = self._secondary_button(QApplication.translate("tilauscope_pid", "KEEP AS REFERENCE"))
        self.btn_undo.clicked.connect(self.undo_last_change)
        self.btn_restore.clicked.connect(self.restore_session_start)
        self.btn_keep.clicked.connect(self.keep_as_reference)
        history_row.addWidget(self.btn_undo)
        history_row.addWidget(self.btn_restore)
        history_row.addWidget(self.btn_keep)
        content.addLayout(history_row)

        expert_group = QGroupBox(QApplication.translate("tilauscope_pid", "ENGINEER DETAILS"))
        expert_group.setCheckable(True)
        expert_group.setChecked(False)
        expert_group.setStyleSheet(self._group_style())
        expert_layout = QVBoxLayout(expert_group)
        self.lbl_engineering = QLabel("—")
        self.lbl_engineering.setWordWrap(True)
        self.lbl_engineering.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_engineering.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-family:monospace; border:none;"
        )
        expert_layout.addWidget(self.lbl_engineering)
        self.lbl_engineering.setVisible(False)
        expert_group.toggled.connect(self.lbl_engineering.setVisible)
        content.addWidget(expert_group)

        controls = QHBoxLayout()
        self.btn_start = self._primary_button(QApplication.translate("tilauscope_pid", "START EXPLANATION"))
        self.btn_stop = self._secondary_button(QApplication.translate("tilauscope_pid", "STOP"))
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self.start_monitoring)
        self.btn_stop.clicked.connect(self.stop_monitoring)
        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_stop)
        shell.addLayout(controls)

        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            window_width, window_height = 760, 620
        else:
            available = screen.availableGeometry()
            window_width = min(760, max(520, int(available.width() * 0.82)))
            window_height = min(620, max(420, int(available.height() * 0.72)))
        self.resize(window_width, window_height)
        self.setMaximumHeight(window_height)

    def present(self) -> None:
        """Show, centre and activate the assistant as a top-level dialog."""
        self.setWindowOpacity(1.0)
        self.show()

        parent = self.parentWidget()
        frame = self.frameGeometry()
        if parent is not None and parent.isVisible():
            frame.moveCenter(parent.frameGeometry().center())
        else:
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

        # Activation before show() is ignored by the macOS window server.
        QTimer.singleShot(0, self._bring_to_front)

    def _bring_to_front(self) -> None:
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _group_style() -> str:
        return (
            f"QGroupBox {{ color:{THEME['ACCENT']}; font-weight:bold;"
            f" border:1px solid {THEME['BORDER']}; border-radius:10px;"
            " margin-top:14px; padding-top:10px; }}"
            "QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top left;"
            " padding:0 6px; }"
        )

    @staticmethod
    def _fact(layout: QHBoxLayout, title: str) -> QLabel:
        column = QVBoxLayout()
        name = QLabel(title)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:10px; border:none;")
        value = QLabel("—")
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:16px; font-weight:700; border:none;"
        )
        column.addWidget(name)
        column.addWidget(value)
        layout.addLayout(column)
        layout.addStretch()
        return value

    @staticmethod
    def _semantic_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(34)
        button.setStyleSheet(
            f"QPushButton {{ background-color: {THEME['SURFACE']}; color:{THEME['TEXT']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:7px; padding:5px 10px; }}"
            f"QPushButton:hover {{ border-color:{THEME['ACCENT']}; }}"
            f"QPushButton:disabled {{ color:{THEME['BORDER']}; }}"
        )
        return button

    @staticmethod
    def _primary_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(40)
        button.setStyleSheet(
            f"QPushButton {{ background-color: {THEME['ACCENT']}; color:{THEME['BG']};"
            " border:none; border-radius:8px; font-weight:bold; }}"
            "QPushButton:disabled { background-color:#45475A; }"
        )
        return button

    @staticmethod
    def _secondary_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(36)
        button.setStyleSheet(
            f"QPushButton {{ background-color: {THEME['SURFACE']}; color:{THEME['TEXT']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:8px; padding:5px 10px; }}"
            f"QPushButton:hover {{ border-color:{THEME['LAVENDER']}; }}"
            f"QPushButton:disabled {{ color:{THEME['BORDER']}; }}"
        )
        return button

    def _run_calibration_self_test(self) -> None:
        """Run the 600-second state machine without any actuator connection."""
        self.btn_calibration_check.setEnabled(False)
        self.lbl_calibration.setText(QApplication.translate("tilauscope_pid", 
            "Checking the 600-second sequence in the virtual machine…"
        ))
        QApplication.processEvents()
        try:
            protocol = run_reference_simulation(
                current_kp=float(self.pid.pidKp),
                current_ki=float(self.pid.pidKi),
            )
            if (
                protocol.phase != "complete"
                or protocol.plant is None
                or protocol.candidate is None
                or protocol.validation_result is None
                or not protocol.validation_result.accepted
            ):
                reason = protocol.reason or QApplication.translate("tilauscope_pid", "unknown software failure")
                self.lbl_calibration.setText(QApplication.translate("tilauscope_pid", 
                    "The safety rehearsal refused the candidate. No setting was changed. "
                ) + str(reason))
                return
            plant = protocol.plant
            candidate = protocol.candidate
            self.lbl_calibration.setText(QApplication.translate("tilauscope_pid", 
                "Safety rehearsal passed: all 600 seconds, identification, cautious "
                "trial and rollback decision were exercised without sending heat. "
                "The real-machine test remains locked until its hardware safety checks pass."
            ))
            self._calibration_engineering = (
                "\ncalibration-self-test=passed"
                f"  K={plant.gain_c_per_pct:.4g} °C/%"
                f"  tau={plant.tau_sec:.0f}s  delay={plant.delay_sec:.0f}s"
                f"  candidate={candidate.kp:.4g}/{candidate.ki:.4g}/{candidate.kd:.4g}"
            )
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _log.exception("PID calibration software self-test failed")
            self.lbl_calibration.setText(QApplication.translate("tilauscope_pid", 
                "The software safety rehearsal failed. No setting was changed."
            ))
        finally:
            self.btn_calibration_check.setEnabled(True)

    def _live_calibration_readiness(
        self,
        *,
        machine_empty: bool,
        airflow_safe: bool,
        supervised: bool,
    ) -> CalibrationReadinessReport:
        """Read current application facts without issuing any command."""
        qmc = self.aw.qmc
        slider_target = int(getattr(self.pid, "pidPositiveTarget", 0))
        heater_slider = slider_target - 1 if 1 <= slider_target <= 4 else None

        identity = self._calibration_machine_identity()
        actions = getattr(self.aw, "eventslideractions", ())
        action_configured = (
            heater_slider is not None
            and heater_slider < len(actions)
            and int(actions[heater_slider]) != 0
        )
        slider_values = getattr(self.aw, "eventslidervalues", ())
        current_power: float | None = None
        if heater_slider is not None and heater_slider < len(slider_values):
            value = slider_values[heater_slider]
            if value is not None and math.isfinite(float(value)):
                current_power = float(value)

        slider_mins = getattr(self.aw, "eventslidermin", ())
        slider_maxs = getattr(self.aw, "eventslidermax", ())
        slider_min = (
            float(slider_mins[heater_slider])
            if heater_slider is not None and heater_slider < len(slider_mins)
            else 0.0
        )
        slider_max = (
            float(slider_maxs[heater_slider])
            if heater_slider is not None and heater_slider < len(slider_maxs)
            else 100.0
        )
        power_min = max(slider_min, float(self.pid.dutyMin))
        power_max = min(slider_max, float(self.pid.dutyMax))

        values = tuple(self._readiness_history)
        temperatures = [point[1] for point in values]
        errors = [abs(point[2]) for point in values]
        rors = [abs(point[3]) for point in values]
        sensor_valid = bool(
            values
            and all(math.isfinite(value) for value in temperatures)
        )
        preheat_pid = getattr(self.aw, "tilauPreheatingPid", None)
        try:
            self._capture_config()
            rollback_available = True
        except (AttributeError, TypeError, ValueError):
            rollback_available = False

        return evaluate_calibration_readiness(CalibrationReadinessInputs(
            monitoring_active=bool(getattr(qmc, "flagon", False)),
            machine_identity_known=identity is not None,
            roast_started=bool(getattr(qmc, "flagstart", False)),
            software_pid_selected=self.pid.externalPIDControl() == 0,
            gain_scheduling_active=bool(self.pid.pidGainScheduling),
            artisan_pid_active=bool(self.pid.pidActive),
            sensor_valid=sensor_valid,
            stable_sample_count=len(values),
            max_abs_error_c=max(errors, default=math.inf),
            temperature_span_c=(
                max(temperatures) - min(temperatures)
                if temperatures else math.inf
            ),
            max_abs_ror_c_per_min=max(rors, default=math.inf),
            heater_slider=heater_slider,
            heater_action_configured=bool(action_configured),
            actuator_direction_normal=not bool(self.pid.invertControl),
            current_power_pct=current_power,
            power_min_pct=power_min,
            power_max_pct=power_max,
            required_power_room_pct=13.0,
            simulator_active=getattr(self.aw, "simulator", None) is not None,
            preheat_pid_active=bool(
                preheat_pid is not None and getattr(preheat_pid, "active", False)
            ),
            rollback_snapshot_available=rollback_available,
            machine_empty_confirmed=machine_empty,
            airflow_safe_confirmed=airflow_safe,
            supervision_confirmed=supervised,
        ))

    def _calibration_machine_identity(
        self,
    ) -> CalibrationMachineIdentity | None:
        """Resolve the selected roaster and exact actuator path, or fail closed."""
        display_name = str(getattr(self.aw, "tilau_roaster", "") or "")
        slider_target = int(getattr(self.pid, "pidPositiveTarget", 0))
        heater_slider = slider_target - 1
        try:
            roaster = RoasterManager().get_by_display_name(display_name)
            if roaster is None:
                return None
            actions = self.aw.eventslideractions
            commands = self.aw.eventslidercommands
            minimums = self.aw.eventslidermin
            maximums = self.aw.eventslidermax
            factors = self.aw.eventsliderfactors
            offsets = self.aw.eventslideroffsets
            return build_machine_identity(
                roaster_id=roaster.roaster_id,
                display_name=display_name,
                temperature_unit=str(self.aw.qmc.mode),
                pid_source=int(self.pid.pidSource),
                heater_slider=heater_slider,
                action_id=int(actions[heater_slider]),
                action_command=str(commands[heater_slider]),
                slider_min=int(minimums[heater_slider]),
                slider_max=int(maximums[heater_slider]),
                slider_factor=float(factors[heater_slider]),
                slider_offset=float(offsets[heater_slider]),
                inverted=bool(self.pid.invertControl),
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    def _zero_output_is_qualified_for_current_machine(self) -> bool:
        identity = self._calibration_machine_identity()
        return bool(
            self._zero_output_qualified
            and identity is not None
            and self._qualified_machine_fingerprint == identity.fingerprint
        )

    @classmethod
    def _live_calibration_profile_authorized(
        cls, identity: CalibrationMachineIdentity | None
    ) -> bool:
        return bool(
            identity is not None
            and (identity.roaster_id, identity.actuator_signature)
            in cls._LIVE_CALIBRATION_ACTUATORS
        )

    @classmethod
    def _supervised_pilot_profile_authorized(
        cls, identity: CalibrationMachineIdentity | None
    ) -> bool:
        return bool(
            identity is not None
            and (identity.roaster_id, identity.actuator_signature)
            in cls._SUPERVISED_PILOT_ACTUATORS
        )

    @staticmethod
    def _export_hardware_pilot_manifest(
        identity: CalibrationMachineIdentity,
    ) -> Path:
        root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        if not root:
            raise OSError("application data directory is unavailable")
        return write_hardware_pilot_manifest(
            Path(root) / "tilauscope" / "pid-calibration", identity
        )

    @staticmethod
    def _record_zero_output_evidence(
        identity: CalibrationMachineIdentity,
    ) -> bool:
        try:
            root = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            if not root:
                return False
            write_zero_qualification_evidence(
                Path(root) / "tilauscope" / "pid-calibration", identity
            )
            return True
        except OSError:
            _log.exception("PID zero-output evidence could not be persisted")
            return False

    def _build_live_calibration_runner(
        self,
        *,
        readiness: CalibrationReadinessReport,
        identity: CalibrationMachineIdentity,
        review_only: bool = False,
    ) -> PIDCalibrationRunner:
        """Build the real adapter, without starting it or exposing it in the UI."""
        current_identity = self._calibration_machine_identity()
        if (
            not readiness.ready
            or current_identity is None
            or current_identity.fingerprint != identity.fingerprint
            or not self._zero_output_is_qualified_for_current_machine()
        ):
            raise RuntimeError("live calibration safety gate is not satisfied")

        slider = identity.heater_slider
        values = self.aw.eventslidervalues
        minimums = self.aw.eventslidermin
        maximums = self.aw.eventslidermax
        baseline_power = float(values[slider])
        power_min = max(float(minimums[slider]), float(self.pid.dutyMin))
        power_max = min(float(maximums[slider]), float(self.pid.dutyMax))
        engine = self._read_engine()
        target_c = temperature_to_c(float(engine["target"]), identity.temperature_unit)
        baseline_config = self._capture_config()
        protocol = CalibrationProtocol(
            CalibrationLimits(
                target_c=target_c,
                baseline_power_pct=baseline_power,
                power_min_pct=power_min,
                power_max_pct=power_max,
            ),
            current_kp=float(self.pid.pidKp),
            current_ki=float(self.pid.pidKi),
            current_kd=float(self.pid.pidKd),
        )

        def read_temperature() -> float | None:
            return self._read_engine()["pv"]

        def read_source_token() -> object | None:
            qmc = self.aw.qmc
            series = qmc.timex if qmc.flagstart else qmc.on_timex
            return series[-1] if series else None

        observer = LiveCalibrationSampleObserver(
            read_temperature=read_temperature,
            read_source_token=read_source_token,
            temperature_unit=identity.temperature_unit,
            stale_after_sec=protocol.limits.stale_after_sec,
        )

        def apply_candidate(candidate: PIDCandidate) -> None:
            candidate_config = dict(baseline_config)
            candidate_config.update({
                "pidKp": candidate.kp,
                "pidKi": candidate.ki,
                "pidKd": candidate.kd,
            })
            self._apply_config(candidate_config)

        def persist_journal(coordinator: LiveCalibrationCoordinator) -> None:
            if coordinator.phase == "complete":
                outcome = "complete"
            elif coordinator.phase == "refused":
                outcome = "refused"
            elif coordinator.phase == "safe_stop":
                outcome = "safe_stop"
            else:
                raise ValueError("cannot persist a non-terminal calibration")
            root = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            if not root:
                raise OSError("application data directory is unavailable")
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
            journal_path = (
                Path(root)
                / "tilauscope"
                / "pid-calibration"
                / f"run-{timestamp}-{identity.fingerprint[:12]}.json"
            )
            write_calibration_journal(
                journal_path,
                identity=identity,
                events=coordinator.audit_events,
                outcome=outcome,
                reason=coordinator.reason,
            )
            self._last_calibration_journal_path = journal_path

        if self._calibration_runner is not None:
            self._calibration_runner.close()
        runner = PIDCalibrationRunner(
            LiveCalibrationCoordinator(
                protocol,
                heater_slider=slider,
                zero_output_qualified=True,
                request_power=self.aw.tilaupidSliderCommandSignal.emit,
                apply_candidate=apply_candidate,
                restore_config=lambda: self._apply_config(baseline_config),
            ),
            readiness_provider=lambda: self._live_calibration_readiness(
                machine_empty=True,
                airflow_safe=True,
                supervised=True,
            ),
            sample_provider=observer.sample,
            runtime_stop_provider=lambda manual, communication: (
                self._runtime_calibration_stop_reason(
                    manual_override=manual,
                    communication_ok=communication,
                    expected_machine_fingerprint=identity.fingerprint,
                )
            ),
            applied_signal=self.aw.tilaupidSliderAppliedSignal,
            manual_signal=self.aw.tilauManualSliderMovedSignal,
            persist_journal=persist_journal,
            review_only=review_only,
            parent=self,
        )
        self._calibration_runner = runner
        return runner

    def _runtime_calibration_stop_reason(
        self,
        *,
        manual_override: bool,
        communication_ok: bool,
        expected_machine_fingerprint: str | None = None,
    ) -> str | None:
        """Map current ApplicationWindow state to the coordinator interlock."""
        qmc = self.aw.qmc
        preheat_pid = getattr(self.aw, "tilauPreheatingPid", None)
        current_identity = self._calibration_machine_identity()
        identity_unchanged = bool(
            expected_machine_fingerprint is None
            or (
                current_identity is not None
                and current_identity.fingerprint == expected_machine_fingerprint
            )
        )
        return runtime_interlock_reason(CalibrationRuntimeInterlocks(
            monitoring_active=bool(getattr(qmc, "flagon", False)),
            roast_started=bool(getattr(qmc, "flagstart", False)),
            software_pid_selected=self.pid.externalPIDControl() == 0,
            machine_identity_unchanged=identity_unchanged,
            artisan_pid_active=bool(self.pid.pidActive),
            simulator_active=getattr(self.aw, "simulator", None) is not None,
            preheat_pid_active=bool(
                preheat_pid is not None and getattr(preheat_pid, "active", False)
            ),
            manual_override=manual_override,
            communication_ok=communication_ok,
        ))

    def show_calibration_readiness(self) -> None:
        CalibrationReadinessDialog(self).exec()

    def _capture_config(self) -> dict[str, float | int | bool]:
        return {name: getattr(self.pid, name) for name in self._CONFIG_FIELDS}

    def _apply_config(self, config: dict[str, float | int | bool]) -> None:
        for name in self._CONFIG_FIELDS:
            if name in config:
                setattr(self.pid, name, config[name])
        if self.pid.externalPIDControl() == 0:
            self.pid.confSoftwarePID(reset=False)

    def _apply_behaviour(
        self, behaviour: Behaviour, engine_direction: int, visual_delta: int
    ) -> None:
        if not self.is_monitoring or self._cooling_down:
            return
        if not self.pid.pidActive or self.pid.externalPIDControl() != 0:
            self.lbl_change.setText(QApplication.translate("tilauscope_pid", 
                "Behaviour controls require Artisan's active software PID."
            ))
            return
        old_offset = self._offsets[behaviour]
        new_offset = max(self._OFFSET_MIN, min(self._OFFSET_MAX, old_offset + visual_delta))
        if new_offset == old_offset:
            return

        current = self._capture_config()
        changed = adjust_pid_behaviour(
            current,
            behaviour,
            engine_direction,
            all_zones=(self.scope_combo.currentIndex() == 1),
            schedule_value=self._latest_schedule_value,
            mode=self.aw.qmc.mode,
        )
        if changed == current:
            self.lbl_change.setText(QApplication.translate("tilauscope_pid", 
                "This behaviour is already at its safe adjustment limit."
            ))
            return
        self._undo_stack.append((current, dict(self._offsets)))
        self._apply_config(changed)
        self._offsets[behaviour] = new_offset
        self._begin_settle_wait(behaviour, engine_direction)
        self._update_behaviour_controls()

    def _begin_settle_wait(self, behaviour: Behaviour, direction: int) -> None:
        descriptions = {
            ("reaction", -1): QApplication.translate("tilauscope_pid", "Reaction made gentler."),
            ("reaction", 1): QApplication.translate("tilauscope_pid", "Reaction made stronger."),
            ("recovery", -1): QApplication.translate("tilauscope_pid", "Lasting-delay catch-up reduced."),
            ("recovery", 1): QApplication.translate("tilauscope_pid", "Lasting-delay catch-up increased."),
            ("braking", -1): QApplication.translate("tilauscope_pid", "Inertia braking reduced."),
            ("braking", 1): QApplication.translate("tilauscope_pid", "Inertia braking increased."),
            ("stability", 1): QApplication.translate("tilauscope_pid", "Command made more stable."),
            ("stability", -1): QApplication.translate("tilauscope_pid", "Command made more responsive."),
        }
        self.lbl_change.setText(
            descriptions[(behaviour, direction)] + " " +
            QApplication.translate("tilauscope_pid", "Waiting for the machine to respond before another change.")
        )
        self._cooling_down = True
        self._settle_timer.start(self._SETTLE_WAIT_MS)

    def _settle_wait_finished(self) -> None:
        self._cooling_down = False
        self.lbl_change.setText(QApplication.translate("tilauscope_pid", 
            "The response can now be assessed. Change one behaviour at a time."
        ))
        self._update_behaviour_controls()

    def _update_behaviour_controls(self) -> None:
        allowed = (
            self.is_monitoring
            and self.pid.pidActive
            and self.pid.externalPIDControl() == 0
            and not self._cooling_down
        )
        for behaviour, (left, indicator, right) in self._behaviour_widgets.items():
            index = self._offsets[behaviour] - self._OFFSET_MIN
            rendered = ["○", "○", "○", "○", "○"]
            rendered[index] = "●"
            indicator.setText("  ".join(rendered))
            left.setEnabled(allowed and self._offsets[behaviour] > self._OFFSET_MIN)
            right.setEnabled(allowed and self._offsets[behaviour] < self._OFFSET_MAX)
        scheduling = bool(self.pid.pidGainScheduling)
        self.scope_combo.setEnabled(allowed and scheduling)
        if not scheduling:
            self.scope_combo.setCurrentIndex(1)
        self.btn_undo.setEnabled(bool(self._undo_stack))
        self.btn_restore.setEnabled(self._baseline_config is not None)
        self.btn_keep.setEnabled(self._baseline_config is not None)

    def _read_engine(self) -> _EngineSnapshot:
        engine = self.aw.qmc.pid
        engine.pidSemaphore.acquire(1)
        try:
            pv = None if engine.lastInput is None else float(engine.lastInput)
            target = float(engine.target)
            if pv is None:
                kp = ki = kd = None
            else:
                kp = float(engine.getKp(pv))
                ki = float(engine.getKi(pv))
                kd = float(engine.getKd(pv))
            output_min = max(float(engine.outMin), float(self.pid.dutyMin))
            output_max = min(float(engine.outMax), float(self.pid.dutyMax))
            output = None if engine.lastOutput is None else float(engine.lastOutput)
            if output is not None:
                output = min(output_max, max(output_min, float(output)))
            return {
                "active": bool(engine.active and self.pid.pidActive),
                "pv": pv,
                "target": target,
                "p": float(engine.Pterm),
                "i": float(engine.Iterm),
                "d": float(engine.Dterm),
                "output": output,
                "output_min": output_min,
                "output_max": output_max,
                "kp": kp,
                "ki": ki,
                "kd": kd,
            }
        finally:
            engine.pidSemaphore.release(1)

    def _ror(self, pv: float, now: float) -> float:
        self._pv_history.append((now, pv))
        if len(self._pv_history) < 2:
            return 0.0
        first_time, first_pv = self._pv_history[0]
        dt = now - first_time
        if dt <= 0.1:
            return 0.0
        native_ror = (pv - first_pv) / dt * 60.0
        return native_ror / 1.8 if self.aw.qmc.mode == "F" else native_ror

    def update_logic(self) -> None:
        if not self.isVisible():
            self.stop_monitoring()
            return
        if self.pid.externalPIDControl() != 0:
            self._render_external_pid()
            return
        try:
            data = self._read_engine()
            pv_raw = data["pv"]
            valid = pv_raw is not None and pv_raw != -1.0
            pv = pv_raw if pv_raw is not None and pv_raw != -1.0 else 0.0
            target = data["target"] if valid else 0.0
            scale = 1.8 if self.aw.qmc.mode == "F" else 1.0
            error_c = (target - pv) / scale if valid else 0.0
            now = time.monotonic()
            ror_c = self._ror(pv, now) if valid else 0.0
            if valid:
                self._error_history.append(error_c)
                self._readiness_history.append((
                    now,
                    temperature_to_c(pv, self.aw.qmc.mode),
                    error_c,
                    ror_c,
                ))

            observation = PIDObservation(
                active=bool(data["active"]),
                valid=valid,
                error_c=error_c,
                ror_c_per_min=ror_c,
                output_pct=(float(data["output"]) if data["output"] is not None else None),
                output_min_pct=float(data["output_min"] or 0.0),
                output_max_pct=float(data["output_max"] or 0.0),
                p_term=float(data["p"] or 0.0),
                i_term=float(data["i"] or 0.0),
                d_term=float(data["d"] or 0.0),
                recent_errors_c=tuple(self._error_history),
            )
            narrative = self._stabilise_narrative(narrate_pid(observation))
            self._latest_schedule_value = target if self.pid.pidGainSchedulingSV else pv
            self._render_narrative(narrative, observation, data)
            self._render_engineering(data, observation)
            self._update_behaviour_controls()
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _log.exception("PID semantic observation failed")
            self._render_narrative(PIDNarrative("unavailable", "high"), None, None)

    def _stabilise_narrative(self, narrative: PIDNarrative) -> PIDNarrative:
        immediate = {"stopped", "unavailable", "power_limited", "coasting"}
        if narrative.state in immediate or narrative.state == self._current_narrative.state:
            self._current_narrative = narrative
            self._candidate_state = None
            self._candidate_count = 0
            return narrative
        if self._candidate_state == narrative.state:
            self._candidate_count += 1
        else:
            self._candidate_state = narrative.state
            self._candidate_count = 1
        if self._candidate_count >= 2:
            self._current_narrative = narrative
            self._candidate_state = None
            self._candidate_count = 0
        return self._current_narrative

    def _render_narrative(
        self,
        narrative: PIDNarrative,
        observation: PIDObservation | None,
        data: _EngineSnapshot | None,
    ) -> None:
        messages = {
            "stopped": (QApplication.translate("tilauscope_pid", "Artisan's PID is stopped."),
                QApplication.translate("tilauscope_pid", "Start the software PID to explain and adjust its behaviour."), ""),
            "unavailable": (QApplication.translate("tilauscope_pid", "The temperature signal is not available."),
                QApplication.translate("tilauscope_pid", "TilauScope will not interpret or adjust an invalid measurement."),
                QApplication.translate("tilauscope_pid", "Check the selected input and sensor connection.")),
            "power_limited": (QApplication.translate("tilauscope_pid", "Artisan is already requesting all allowed heat."),
                QApplication.translate("tilauscope_pid", "The temperature remains below target, but the command cannot go higher."),
                QApplication.translate("tilauscope_pid", "Changing PID behaviour cannot add power. Check the limit, target or machine capacity.")),
            "coasting": (QApplication.translate("tilauscope_pid", "Artisan has cut the heat and is letting inertia act."),
                QApplication.translate("tilauscope_pid", "The temperature is still rising while the heat request is at its minimum."),
                QApplication.translate("tilauscope_pid", "Wait for the machine response before changing the behaviour.")),
            "oscillating": (QApplication.translate("tilauscope_pid", "The corrections are too fast for this machine."),
                QApplication.translate("tilauscope_pid", "The temperature has crossed the target repeatedly."),
                QApplication.translate("tilauscope_pid", "Try React less or Catch up less, one notch at a time.")),
            "braking": (QApplication.translate("tilauscope_pid", "Artisan is starting to brake before the target."),
                QApplication.translate("tilauscope_pid", "The temperature is still below target, but it is already rising quickly."),
                QApplication.translate("tilauscope_pid", "Use Brake less/more only if the final approach is consistently wrong.")),
            "catching_up": (QApplication.translate("tilauscope_pid", "Artisan is catching up a lasting delay."),
                QApplication.translate("tilauscope_pid", "The temperature has remained below target long enough to build a progressive correction."),
                QApplication.translate("tilauscope_pid", "Reduce catch-up if this later causes overshoot.")),
            "accelerating": (QApplication.translate("tilauscope_pid", "Artisan is accelerating toward the target."),
                QApplication.translate("tilauscope_pid", "The current temperature gap is asking for more heat."),
                QApplication.translate("tilauscope_pid", "React more/less changes the strength of this immediate response.")),
            "above_target": (QApplication.translate("tilauscope_pid", "The temperature is above the target."),
                QApplication.translate("tilauscope_pid", "Artisan is reducing its heat request to return toward the target."),
                QApplication.translate("tilauscope_pid", "If this repeats, try Brake more or Catch up less.")),
            "holding": (QApplication.translate("tilauscope_pid", "The target is being held."),
                QApplication.translate("tilauscope_pid", "No large correction is currently required."),
                QApplication.translate("tilauscope_pid", "Keep this setting if the command also remains calm.")),
        }
        headline, reason, suggestion = messages[narrative.state]
        self.lbl_headline.setText(headline)
        self.lbl_reason.setText(reason)
        self.lbl_suggestion.setText(suggestion)

        if observation is None or not observation.valid or data is None:
            self.lbl_pv.setText("—")
            self.lbl_sp.setText("—")
            self.lbl_output.setText("—")
            return
        suffix = f" °{self.aw.qmc.mode}"
        pv = data["pv"]
        self.lbl_pv.setText("—" if pv is None else f"{pv:.1f}{suffix}")
        self.lbl_sp.setText(f"{data['target']:.1f}{suffix}")
        output = data["output"]
        self.lbl_output.setText("—" if output is None else f"{output:.0f} %")

    def _render_engineering(
        self, data: _EngineSnapshot, observation: PIDObservation
    ) -> None:
        kp, ki, kd = data["kp"], data["ki"], data["kd"]
        if kp is None or ki is None or kd is None:
            gain_text = "—/—/—"
        else:
            gain_text = f"{kp:.4g}/{ki:.4g}/{kd:.4g}"
        self.lbl_engineering.setText(
            f"source={self.pid.pidSource}  gains={gain_text}\n"
            f"error={observation.error_c:+.2f} °C  RoR={observation.ror_c_per_min:+.2f} °C/min\n"
            f"terms={observation.p_term:+.2f} / {observation.i_term:+.2f} / {observation.d_term:+.2f}\n"
            f"output={observation.output_pct}  limits=[{observation.output_min_pct:.0f}, "
            f"{observation.output_max_pct:.0f}]  schedule={'on' if self.pid.pidGainScheduling else 'off'}"
            f"{self._calibration_engineering}"
        )

    def _render_external_pid(self) -> None:
        self.lbl_headline.setText(QApplication.translate("tilauscope_pid", "An external hardware PID is selected."))
        self.lbl_reason.setText(QApplication.translate("tilauscope_pid", 
            "This assistant currently explains and adjusts Artisan's internal software PID only."
        ))
        self.lbl_suggestion.setText(QApplication.translate("tilauscope_pid", 
            "Use the hardware controller's own certified tuning procedure."
        ))
        self.lbl_pv.setText("—")
        self.lbl_sp.setText("—")
        self.lbl_output.setText("—")
        self._update_behaviour_controls()

    def start_monitoring(self) -> None:
        self.is_monitoring = True
        self._pv_history.clear()
        self._readiness_history.clear()
        self._error_history.clear()
        self._candidate_state = None
        self._candidate_count = 0
        self._baseline_config = self._capture_config()
        self._undo_stack.clear()
        self._offsets = dict.fromkeys(self._offsets, 0)
        self.lbl_change.setText(QApplication.translate("tilauscope_pid", 
            "Explanation started. No setting changes until you press a behaviour button."
        ))
        self.timer.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.update_logic()
        self._update_behaviour_controls()

    def stop_monitoring(self) -> None:
        self.is_monitoring = False
        self.timer.stop()
        self._settle_timer.stop()
        self._cooling_down = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_change.setText(QApplication.translate("tilauscope_pid", "Explanation stopped."))
        self._update_behaviour_controls()

    def undo_last_change(self) -> None:
        if not self._undo_stack:
            return
        config, offsets = self._undo_stack.pop()
        self._apply_config(config)
        self._offsets = offsets
        self._settle_timer.stop()
        self._cooling_down = False
        self.lbl_change.setText(QApplication.translate("tilauscope_pid", "Last behaviour change undone."))
        self._update_behaviour_controls()

    def restore_session_start(self) -> None:
        if self._baseline_config is None:
            return
        self._apply_config(self._baseline_config)
        self._undo_stack.clear()
        self._offsets = dict.fromkeys(self._offsets, 0)
        self._settle_timer.stop()
        self._cooling_down = False
        self.lbl_change.setText(QApplication.translate("tilauscope_pid", "The session-start setting has been restored."))
        self._update_behaviour_controls()

    def keep_as_reference(self) -> None:
        self._baseline_config = self._capture_config()
        self._undo_stack.clear()
        self._offsets = dict.fromkeys(self._offsets, 0)
        self.lbl_change.setText(QApplication.translate("tilauscope_pid", "The current behaviour is now the session reference."))
        self._update_behaviour_controls()

    def show_help(self) -> None:
        HelpDialog(self).exec()

    def fade_out_and_close(self) -> None:
        animation = QPropertyAnimation(self, b"windowOpacity")
        self.anim = animation
        animation.setDuration(250)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.finished.connect(self.close)
        animation.start()

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        self.oldPos = a0.globalPosition().toPoint()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        delta = a0.globalPosition().toPoint() - self.oldPos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = a0.globalPosition().toPoint()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.stop_monitoring()
        if self._calibration_runner is not None:
            self._calibration_runner.close()
            self._calibration_runner = None
        self.aw.PIDAutotuneMenuAction.setChecked(False)
        if a0 is not None:
            a0.accept()


# This tightly coupled child dialog deliberately calls its owning assistant's
# non-public read-only helpers; they are not part of the application API.
# pylint: disable=protected-access
class CalibrationReadinessDialog(QDialog):
    """Prerequisite review plus the zero-output-only qualification bench."""

    def __init__(self, assistant: PIDAutotune) -> None:
        super().__init__(assistant)
        self.assistant = assistant
        self.oldPos = QPoint()
        self.qualification = ZeroOutputQualification(timeout_sec=60.0)
        self._qualification_identity: CalibrationMachineIdentity | None = None
        self._runner: PIDCalibrationRunner | None = None
        self._report: CalibrationReadinessReport | None = None
        self._applied_signal = getattr(
            assistant.aw, "tilaupidSliderAppliedSignal", None
        )
        if self._applied_signal is not None:
            self._applied_signal.connect(self._zero_applied)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setInterval(500)
        self._timeout_timer.timeout.connect(self._poll_qualification)
        self._guide_timer = QTimer(self)
        self._guide_timer.setInterval(1000)
        self._guide_timer.timeout.connect(self.refresh)
        self._details_visible = False
        apply_tilau_theme(self, ground=False)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            "QDialog { background: transparent; }"
            f"QFrame#CalibrationPreparationCard {{ background-color:{THEME['BG']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:20px; }}"
            f"QLabel, QCheckBox {{ color:{THEME['TEXT']}; }}"
        )
        self.setWindowTitle(QApplication.translate("tilauscope_pid", "PREPARE THE 10-MINUTE TEST"))
        self.setModal(True)
        screen = assistant.screen() or QApplication.primaryScreen()
        if screen is None:
            dialog_width, dialog_height = 680, 520
        else:
            available = screen.availableGeometry()
            dialog_width = min(680, max(440, int(available.width() * 0.86)))
            dialog_height = min(520, max(360, int(available.height() * 0.68)))
        self.resize(dialog_width, dialog_height)
        # The centre scrolls; never let Qt's content size push the buttons off-screen.
        self.setMaximumHeight(dialog_height)
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(10, 10, 10, 10)
        card = QFrame()
        card.setObjectName("CalibrationPreparationCard")
        window_layout.addWidget(card)
        outer_layout = QVBoxLayout(card)
        outer_layout.setContentsMargins(18, 16, 18, 16)
        outer_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setObjectName("CalibrationPreparationScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer_layout.addWidget(scroll, 1)
        title = QLabel(QApplication.translate("tilauscope_pid", "BEFORE ANY HEAT COMMAND"))
        title.setStyleSheet(
            f"color:{THEME['ACCENT']}; font-size:17px; font-weight:800;"
        )
        explanation = QLabel(QApplication.translate("tilauscope_pid", 
            "TilauScope shows one action at a time. Nothing advances until the "
            "current step is safely completed."
        ))
        explanation.setWordWrap(True)
        self.guide_progress = QLabel()
        self.guide_progress.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px; font-weight:700;"
        )
        self.guide_title = QLabel()
        self.guide_title.setWordWrap(True)
        self.guide_title.setStyleSheet(
            f"color:{THEME['ACCENT']}; font-size:20px; font-weight:800;"
        )
        self.machine_empty = QCheckBox(QApplication.translate("tilauscope_pid", "The machine is empty"))
        self.airflow_safe = QCheckBox(QApplication.translate("tilauscope_pid", 
            "The drum and airflow are in their safe test position"
        ))
        self.supervised = QCheckBox(QApplication.translate("tilauscope_pid", 
            "I will remain beside the machine for the whole test"
        ))
        self.checks = QTextBrowser()
        self.checks.setOpenExternalLinks(False)
        self.checks.setStyleSheet(
            f"QTextBrowser {{ background-color:{THEME['SURFACE']};"
            f" color:{THEME['TEXT']}; border:1px solid {THEME['BORDER']};"
            " border-radius:8px; padding:10px; }}"
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color:{THEME['WARNING']}; font-weight:700;"
        )
        self.next_steps = QLabel()
        self.next_steps.setObjectName("CalibrationNextSteps")
        self.next_steps.setWordWrap(True)
        self.next_steps.setStyleSheet(
            f"color:{THEME['TEXT']}; background-color:{THEME['SURFACE']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:8px;"
            " padding:16px; font-size:15px;"
        )
        self.zero_warning = QLabel(QApplication.translate("tilauscope_pid", 
            "The shutdown qualification can only command 0% heat. It never "
            "restores the previous power; the heater remains stopped."
        ))
        self.zero_warning.setWordWrap(True)
        self.zero_warning.setStyleSheet(
            f"color:{THEME['WARNING']}; font-weight:700;"
        )
        self.zero_button = assistant._secondary_button(
            QApplication.translate("tilauscope_pid", "TEST THE PHYSICAL 0% SHUTDOWN")
        )
        self.zero_button.clicked.connect(self._request_zero)
        self.physical_off = QCheckBox(QApplication.translate("tilauscope_pid", 
            "I can see that the physical heater is off"
        ))
        self.physical_off.setEnabled(False)
        self.confirm_zero = assistant._primary_button(
            QApplication.translate("tilauscope_pid", "CONFIRM PHYSICAL SHUTDOWN")
        )
        self.confirm_zero.setEnabled(False)
        self.confirm_zero.clicked.connect(self._confirm_physical_shutdown)
        live_buttons = QHBoxLayout()
        self.start_live = assistant._primary_button(
            QApplication.translate("tilauscope_pid", "START THE SUPERVISED 10-MINUTE TEST")
        )
        self.start_live.setEnabled(False)
        self.start_live.clicked.connect(self._start_live_test)
        self.stop_live = assistant._secondary_button(
            QApplication.translate("tilauscope_pid", "STOP TEST AND CUT HEAT")
        )
        self.stop_live.setEnabled(False)
        self.stop_live.clicked.connect(self._stop_live_test)
        live_buttons.addWidget(self.start_live)
        live_buttons.addWidget(self.stop_live)
        buttons = QHBoxLayout()
        self.details_button = assistant._secondary_button(
            QApplication.translate("tilauscope_pid", "SHOW TECHNICAL DETAILS")
        )
        self.export_pilot = assistant._secondary_button(
            QApplication.translate("tilauscope_pid", "EXPORT HARDWARE PILOT SHEET")
        )
        close = assistant._primary_button(QApplication.translate("tilauscope_pid", "CLOSE"))
        self.details_button.clicked.connect(self._toggle_details)
        self.export_pilot.clicked.connect(self._export_pilot_sheet)
        close.clicked.connect(self.accept)
        buttons.addWidget(self.details_button)
        buttons.addWidget(self.export_pilot)
        buttons.addStretch()
        buttons.addWidget(close)

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.guide_progress)
        layout.addWidget(self.guide_title)
        layout.addWidget(self.next_steps)
        layout.addWidget(self.machine_empty)
        layout.addWidget(self.airflow_safe)
        layout.addWidget(self.supervised)
        layout.addWidget(self.checks, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.zero_warning)
        layout.addWidget(self.zero_button)
        layout.addWidget(self.physical_off)
        layout.addWidget(self.confirm_zero)
        layout.addLayout(live_buttons)
        outer_layout.addLayout(buttons)
        for checkbox in (
            self.machine_empty,
            self.airflow_safe,
            self.supervised,
        ):
            checkbox.toggled.connect(self.refresh)
        self.checks.hide()
        self.export_pilot.hide()
        if (
            not self.assistant.is_monitoring
            and not self.assistant._readiness_history
        ):
            # Read-only observation: this never starts either PID or sends heat.
            self.assistant.start_monitoring()
        self.refresh()
        self._guide_timer.start()

    def _toggle_details(self) -> None:
        self._details_visible = not self._details_visible
        self.checks.setVisible(self._details_visible)
        self.export_pilot.setVisible(self._details_visible)
        self.details_button.setText(
            QApplication.translate("tilauscope_pid", "HIDE TECHNICAL DETAILS")
            if self._details_visible else
            QApplication.translate("tilauscope_pid", "SHOW TECHNICAL DETAILS")
        )

    def _show_blocking_message(self, text: str) -> None:
        """Keep an exceptional stop visible instead of returning to the wizard."""
        self._guide_timer.stop()
        self.guide_progress.setText(QApplication.translate("tilauscope_pid", "ACTION REQUIRED"))
        self.guide_title.setText(QApplication.translate("tilauscope_pid", "The test remains locked"))
        self.next_steps.setText(text)

    def _displayed_test_point(self) -> tuple[float | None, float | None, str]:
        """Return current BT and PID target in the unit shown by Artisan."""
        try:
            engine = self.assistant._read_engine()
            pv = engine["pv"]
            target = float(engine["target"])
            if pv is None or not math.isfinite(float(pv)):
                pv = None
            if not math.isfinite(target):
                target = None
            return (
                None if pv is None else float(pv),
                target,
                str(self.assistant.aw.qmc.mode),
            )
        except (AttributeError, TypeError, ValueError):
            return None, None, str(getattr(self.assistant.aw.qmc, "mode", "C"))

    def _current_heater_power(self) -> float | None:
        slider = int(getattr(self.assistant.pid, "pidPositiveTarget", 0)) - 1
        values = getattr(self.assistant.aw, "eventslidervalues", ())
        try:
            if not 0 <= slider < len(values):
                return None
            value = float(values[slider])
            return value if math.isfinite(value) else None
        except (IndexError, TypeError, ValueError):
            return None

    def _next_steps_text(
        self, report: CalibrationReadinessReport
    ) -> str:
        """Return only the single action the operator should perform now."""
        blocked = set(report.blocking_codes)
        if "sensor_valid" in blocked:
            return QApplication.translate("tilauscope_pid", 
                "TilauScope is waiting for a valid bean-temperature reading. "
                "Check that the BT value is displayed and changing normally."
            )

        if "power_headroom" in blocked:
            slider_target = int(getattr(
                self.assistant.pid, "pidPositiveTarget", 0
            ))
            heater_slider = slider_target - 1
            minimums = getattr(self.assistant.aw, "eventslidermin", ())
            maximums = getattr(self.assistant.aw, "eventslidermax", ())
            current = self._current_heater_power()
            slider_min = (
                float(minimums[heater_slider])
                if 0 <= heater_slider < len(minimums) else 0.0
            )
            slider_max = (
                float(maximums[heater_slider])
                if 0 <= heater_slider < len(maximums) else 100.0
            )
            safe_min = max(slider_min, float(self.assistant.pid.dutyMin)) + 13.0
            safe_max = min(slider_max, float(self.assistant.pid.dutyMax)) - 13.0
            if safe_min <= safe_max:
                pv, target, unit = self._displayed_test_point()
                current_text = (
                    QApplication.translate("tilauscope_pid", "unknown")
                    if current is None or not math.isfinite(current)
                    else f"{current:g}%"
                )
                pv_text = "—" if pv is None else f"{pv:g} °{unit}"
                target_text = "—" if target is None else f"{target:g} °{unit}"
                return QApplication.translate("tilauscope_pid", 
                    "TilauScope is observing only; you control the heater.\n\n"
                    "Temperature to reach: {target}   •   Current BT: {temperature}\n"
                    "Set the heater between {minimum:g}% and {maximum:g}% "
                    "(currently {current})."
                ).format(
                    target=target_text,
                    temperature=pv_text,
                    minimum=safe_min,
                    maximum=safe_max,
                    current=current_text,
                )
            return QApplication.translate("tilauscope_pid", 
                "The configured heater range is too narrow for a safe test. "
                "The automatic test remains locked."
            )

        if "sensor_stable" in blocked:
            collected = min(len(self.assistant._readiness_history), 30)
            pv, target, unit = self._displayed_test_point()
            power = self._current_heater_power()
            if pv is not None and target is not None:
                tolerance = 0.7 * (1.8 if unit == "F" else 1.0)
                direction = "hold"
                if pv < target - tolerance:
                    direction = "increase"
                elif pv > target + tolerance:
                    direction = "decrease"
                power_text = "—" if power is None else f"{power:g}%"
                if direction == "increase":
                    return QApplication.translate("tilauscope_pid", 
                        "Increase the heater slightly.\n\n"
                        "Current BT: {temperature:g} °{unit}   •   Target: "
                        "{target:g} °{unit}   •   Heater: {power}"
                    ).format(
                        temperature=pv, target=target, unit=unit, power=power_text
                    )
                if direction == "decrease":
                    return QApplication.translate("tilauscope_pid", 
                        "Decrease the heater slightly.\n\n"
                        "Current BT: {temperature:g} °{unit}   •   Target: "
                        "{target:g} °{unit}   •   Heater: {power}"
                    ).format(
                        temperature=pv, target=target, unit=unit, power=power_text
                    )
            return QApplication.translate("tilauscope_pid", 
                "Do not change anything. TilauScope is checking stability: "
                "{collected}/30 seconds. It will advance automatically."
            ).format(collected=collected)

        human_codes = {
            "machine_empty_confirmed",
            "airflow_safe_confirmed",
            "supervision_confirmed",
        }
        if "machine_empty_confirmed" in blocked:
            return QApplication.translate("tilauscope_pid", 
                "Look inside the machine. If there is no coffee or other material, "
                "confirm the first statement below."
            )
        if "airflow_safe_confirmed" in blocked:
            return QApplication.translate("tilauscope_pid", 
                "Put the drum and airflow in the safe positions used for an empty "
                "machine test, then confirm the statement below."
            )
        if "supervision_confirmed" in blocked:
            return QApplication.translate("tilauscope_pid", 
                "Only continue if you can remain beside the machine and reach its "
                "physical heat cut-off for the whole test."
            )
        if blocked - human_codes:
            return QApplication.translate("tilauscope_pid", 
                "A machine setting still prevents the test. Open the technical "
                "details below to see the single crossed setting."
            )
        return QApplication.translate("tilauscope_pid", 
            "Preparation is complete. The next button sends only 0% heat so you "
            "can verify that the physical heater really stops."
        )

    def _guide_heading(
        self, report: CalibrationReadinessReport
    ) -> tuple[str, str]:
        blocked = set(report.blocking_codes)
        human_codes = {
            "machine_empty_confirmed",
            "airflow_safe_confirmed",
            "supervision_confirmed",
        }
        if self.qualification.phase == "failed":
            return QApplication.translate("tilauscope_pid", "ACTION REQUIRED"), QApplication.translate("tilauscope_pid", 
                "Shutdown not confirmed"
            )
        if self.qualification.phase == "software_zero_confirmed":
            return QApplication.translate("tilauscope_pid", "STEP 4 OF 6"), QApplication.translate("tilauscope_pid", 
                "Check that the heater is really off"
            )
        if self.qualification.phase == "qualified" and not report.ready:
            return QApplication.translate("tilauscope_pid", "STEP 5 OF 6"), QApplication.translate("tilauscope_pid", 
                "Return to the stable holding point"
            )
        if self.qualification.phase == "qualified":
            return QApplication.translate("tilauscope_pid", "STEP 6 OF 6"), QApplication.translate("tilauscope_pid", 
                "The supervised test is ready"
            )
        if blocked & human_codes and blocked <= human_codes:
            return QApplication.translate("tilauscope_pid", "STEP 3 OF 6"), QApplication.translate("tilauscope_pid", 
                "Confirm one physical condition"
            )
        if "sensor_valid" in blocked:
            return QApplication.translate("tilauscope_pid", "STEP 1 OF 6"), QApplication.translate("tilauscope_pid", 
                "Read the temperature"
            )
        return QApplication.translate("tilauscope_pid", "STEP 2 OF 6"), QApplication.translate("tilauscope_pid", 
            "Reach and hold the test temperature"
        )

    def refresh(self) -> None:
        report = self.assistant._live_calibration_readiness(
            machine_empty=self.machine_empty.isChecked(),
            airflow_safe=self.airflow_safe.isChecked(),
            supervised=self.supervised.isChecked(),
        )
        self._report = report
        descriptions = {
            "monitoring_active": QApplication.translate("tilauscope_pid", "Monitoring is active"),
            "machine_identity_known": QApplication.translate("tilauscope_pid", 
                "The selected machine and its heater control path are identified"
            ),
            "no_roast_running": QApplication.translate("tilauscope_pid", "No roast is running"),
            "software_pid_selected": QApplication.translate("tilauscope_pid", 
                "Artisan's internal software PID is selected"
            ),
            "gain_scheduling_disabled": QApplication.translate("tilauscope_pid", 
                "Gain scheduling is off for this single-temperature test"
            ),
            "artisan_pid_stopped": QApplication.translate("tilauscope_pid", 
                "Artisan's PID is stopped before takeover"
            ),
            "sensor_valid": QApplication.translate("tilauscope_pid", "The temperature signal is valid"),
            "sensor_stable": QApplication.translate("tilauscope_pid", 
                "Temperature has been stable for at least 30 seconds"
            ),
            "heater_slider_configured": QApplication.translate("tilauscope_pid", 
                "A heater slider is assigned to the PID"
            ),
            "heater_action_configured": QApplication.translate("tilauscope_pid", 
                "The heater slider has a hardware action"
            ),
            "normal_actuator_direction": QApplication.translate("tilauscope_pid", 
                "Increasing the command means increasing heat"
            ),
            "power_headroom": QApplication.translate("tilauscope_pid", 
                "There is enough heat range above and below the holding power"
            ),
            "no_simulator": QApplication.translate("tilauscope_pid", "The Artisan simulator is stopped"),
            "preheat_pid_stopped": QApplication.translate("tilauscope_pid", 
                "TilauPID preheat is no longer commanding the heater"
            ),
            "rollback_snapshot_available": QApplication.translate("tilauscope_pid", 
                "The complete PID configuration can be restored"
            ),
            "machine_empty_confirmed": QApplication.translate("tilauscope_pid", 
                "Machine empty — confirmed"
            ),
            "airflow_safe_confirmed": QApplication.translate("tilauscope_pid", 
                "Safe drum and airflow position — confirmed"
            ),
            "supervision_confirmed": QApplication.translate("tilauscope_pid", 
                "Continuous human supervision — confirmed"
            ),
        }
        rows: list[str] = []
        for check in report.checks:
            colour = THEME["SUCCESS"] if check.passed else THEME["WARNING"]
            mark = "✓" if check.passed else "✕"
            rows.append(
                f'<div style="color:{colour}; margin:3px">'
                f"{mark}&nbsp;&nbsp;{descriptions[check.code]}</div>"
            )
        self.checks.setHtml("".join(rows))
        progress, heading = self._guide_heading(report)
        self.guide_progress.setText(progress)
        self.guide_title.setText(heading)
        if self.qualification.phase == "failed":
            self.next_steps.setText(QApplication.translate("tilauscope_pid", 
                "Heat remains commanded at 0%. Close this window, correct the "
                "problem, then restart the guided preparation from the beginning."
            ))
        elif self.qualification.phase == "software_zero_confirmed":
            self.next_steps.setText(QApplication.translate("tilauscope_pid", 
                "Look at the machine, not only the screen. If the physical heater "
                "is off, tick the confirmation below and validate it."
            ))
        elif self.qualification.phase == "qualified" and report.ready:
            self.next_steps.setText(QApplication.translate("tilauscope_pid", 
                "All conditions are now stable again. You may start the supervised "
                "10-minute test. Stay beside the machine."
            ))
        else:
            self.next_steps.setText(self._next_steps_text(report))

        blocked = set(report.blocking_codes)
        human_codes = {
            "machine_empty_confirmed",
            "airflow_safe_confirmed",
            "supervision_confirmed",
        }
        confirmations_active = (
            self.qualification.phase == "idle"
            and blocked <= human_codes
        )
        self.machine_empty.setVisible(
            confirmations_active and not self.machine_empty.isChecked()
        )
        self.airflow_safe.setVisible(
            confirmations_active
            and self.machine_empty.isChecked()
            and not self.airflow_safe.isChecked()
        )
        self.supervised.setVisible(
            confirmations_active
            and self.machine_empty.isChecked()
            and self.airflow_safe.isChecked()
            and not self.supervised.isChecked()
        )
        self.zero_button.setEnabled(
            report.ready and self.qualification.phase == "idle"
        )
        self.zero_button.setVisible(
            report.ready and self.qualification.phase == "idle"
        )
        self.zero_warning.setVisible(self.zero_button.isVisible())
        awaiting_physical = self.qualification.phase == "software_zero_confirmed"
        self.physical_off.setVisible(awaiting_physical)
        self.confirm_zero.setVisible(awaiting_physical)
        identity = self.assistant._calibration_machine_identity()
        identity_matches = bool(
            identity is not None
            and self._qualification_identity is not None
            and identity.fingerprint == self._qualification_identity.fingerprint
        )
        profile_authorized = self.assistant._live_calibration_profile_authorized(
            identity
        )
        pilot_authorized = self.assistant._supervised_pilot_profile_authorized(
            identity
        )
        self.start_live.setText(
            QApplication.translate("tilauscope_pid", "START THE SUPERVISED 10-MINUTE TEST")
            if profile_authorized
            else QApplication.translate("tilauscope_pid", "START THE REVIEW-ONLY HARDWARE PILOT")
        )
        self.export_pilot.setEnabled(identity is not None and self._runner is None)
        self.start_live.setEnabled(
            self._runner is None
            and report.ready
            and self.qualification.phase == "qualified"
            and identity_matches
            and (profile_authorized or pilot_authorized)
        )
        self.start_live.setVisible(
            self.qualification.phase == "qualified" and report.ready
        )
        self.stop_live.setVisible(self._runner is not None)
        self.status.hide()
        if self.qualification.phase == "qualified":
            if not profile_authorized and not pilot_authorized:
                self.status.setText(QApplication.translate("tilauscope_pid", 
                    "The 0% shutdown is qualified, but this machine profile has not "
                    "yet passed its supervised hardware pilot. Starting remains locked."
                ))
                self.status.show()
        elif self.qualification.phase == "failed":
            self.status.setText(QApplication.translate("tilauscope_pid", 
                "The shutdown qualification is no longer valid. Heat remains at 0%."
            ))
            self.status.show()

    def _request_zero(self) -> None:
        self.refresh()
        if self._report is None or not self._report.ready:
            return
        # Index of the clicked button, -1 when the dialog is dismissed: anything
        # other than the confirm button leaves the heater exactly as it is.
        answer = show_styled_message(
            self,
            QApplication.translate("tilauscope_pid", "COMMAND 0% HEAT"),
            QApplication.translate("tilauscope_pid",
                "This sends only a 0% heater command through the configured hardware "
                "action. The previous power will not be restored. Continue?"
            ),
            icon=QMessageBox.Icon.Question,
            buttons=[QApplication.translate("tilauscope_pid", "Cancel"),
                     QApplication.translate("tilauscope_pid", "Continue")],
        )
        if answer != 1:
            return
        if self._applied_signal is None:
            self._show_blocking_message(QApplication.translate("tilauscope_pid", 
                "The central transaction acknowledgement is unavailable. Nothing was sent."
            ))
            return
        identity = self.assistant._calibration_machine_identity()
        if identity is None:
            self._show_blocking_message(QApplication.translate("tilauscope_pid", 
                "The exact machine and heater control path cannot be identified. Nothing was sent."
            ))
            return
        slider = int(self.assistant.pid.pidPositiveTarget) - 1
        self.qualification = ZeroOutputQualification(timeout_sec=60.0)
        if not self.qualification.start(
            self._report,
            heater_slider=slider,
            now_sec=time.monotonic(),
        ):
            self.refresh()
            return
        self._qualification_identity = identity
        self.zero_button.setEnabled(False)
        self._timeout_timer.start()
        self.assistant.aw.tilaupidSliderCommandSignal.emit(slider, 0, True)

    def _zero_applied(
        self, heater_slider: int, applied_power: int, action_fired: bool
    ) -> None:
        current_identity = self.assistant._calibration_machine_identity()
        if (
            self._qualification_identity is None
            or current_identity is None
            or current_identity.fingerprint
            != self._qualification_identity.fingerprint
        ):
            self.qualification.invalidate("machine_identity_changed")
            self.assistant._zero_output_qualified = False
            self.refresh()
            return
        accepted = self.qualification.acknowledge(
            heater_slider=heater_slider,
            applied_power_pct=applied_power,
            action_fired=action_fired,
            now_sec=time.monotonic(),
        )
        if accepted:
            self.physical_off.setEnabled(True)
            self.confirm_zero.setEnabled(True)
        self.refresh()

    def _confirm_physical_shutdown(self) -> None:
        if not self.physical_off.isChecked():
            return
        current_identity = self.assistant._calibration_machine_identity()
        if (
            self._qualification_identity is None
            or current_identity is None
            or current_identity.fingerprint
            != self._qualification_identity.fingerprint
        ):
            self.qualification.invalidate("machine_identity_changed")
            self.assistant._zero_output_qualified = False
            self.refresh()
            return
        if self.qualification.confirm_physical_shutdown(
            heater_is_off=True,
            now_sec=time.monotonic(),
        ):
            self._timeout_timer.stop()
            self.physical_off.setEnabled(False)
            self.confirm_zero.setEnabled(False)
            if not self.assistant._record_zero_output_evidence(current_identity):
                self.qualification.invalidate("evidence_persistence_failed")
                self.assistant._zero_output_qualified = False
                self.assistant._qualified_machine_fingerprint = None
                self.assistant.lbl_calibration.setText(QApplication.translate("tilauscope_pid", 
                    "The 0% shutdown was observed, but its proof could not be saved. "
                    "The machine test remains locked."
                ))
                self.refresh()
                return
            self.assistant._zero_output_qualified = True
            self.assistant._qualified_machine_fingerprint = current_identity.fingerprint
            self.assistant.lbl_calibration.setText(QApplication.translate("tilauscope_pid", 
                "Physical 0% shutdown qualified for this session. "
                "The heater remains stopped and the 10-minute heat test is still locked."
            ))
        self.refresh()

    def _poll_qualification(self) -> None:
        if self.qualification.poll(time.monotonic()) == "failed":
            self._timeout_timer.stop()
            self.physical_off.setEnabled(False)
            self.confirm_zero.setEnabled(False)
            self._show_blocking_message(QApplication.translate("tilauscope_pid", 
                "Shutdown qualification timed out. Heat remains commanded at 0%."
            ))

    def _start_live_test(self) -> None:
        self.refresh()
        identity = self.assistant._calibration_machine_identity()
        if (
            self._report is None
            or not self._report.ready
            or not self.start_live.isEnabled()
            or identity is None
        ):
            return
        answer = show_styled_message(
            self,
            QApplication.translate("tilauscope_pid", "START SUPERVISED HEAT TEST"),
            QApplication.translate("tilauscope_pid",
                "The machine is empty and supervised. TilauScope will vary heat for "
                "about 10 minutes and cut it to 0% on any anomaly. Start now?"
            ),
            icon=QMessageBox.Icon.Question,
            buttons=[QApplication.translate("tilauscope_pid", "Cancel"),
                     QApplication.translate("tilauscope_pid", "Start")],
        )
        if answer != 1:
            return
        try:
            runner = self.assistant._build_live_calibration_runner(
                readiness=self._report,
                identity=identity,
                review_only=(
                    not self.assistant._live_calibration_profile_authorized(identity)
                ),
            )
            runner.progress.connect(self._live_progress)
            runner.finished.connect(self._live_finished)
            self._runner = runner
            self.start_live.setEnabled(False)
            self.stop_live.setEnabled(True)
            self._guide_timer.stop()
            runner.start()
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _log.exception("PID supervised calibration could not start")
            self.stop_live.setEnabled(False)
            self._show_blocking_message(QApplication.translate("tilauscope_pid", 
                "The test could not start. Heat remains at 0%."
            ))

    def _export_pilot_sheet(self) -> None:
        identity = self.assistant._calibration_machine_identity()
        if identity is None:
            self.status.setText(QApplication.translate("tilauscope_pid", 
                "Select a known machine and configure its heater action first."
            ))
            return
        try:
            path = self.assistant._export_hardware_pilot_manifest(identity)
            self.status.setText(
                QApplication.translate("tilauscope_pid", 
                    "Pilot sheet saved without sending heat: "
                ) + str(path)
            )
        except OSError:
            _log.exception("PID hardware pilot sheet could not be exported")
            self.status.setText(QApplication.translate("tilauscope_pid", 
                "The pilot sheet could not be saved. No heat was sent."
            ))

    def _stop_live_test(self) -> None:
        if self._runner is not None:
            self._runner.abort("operator_cancelled")

    def _live_progress(self, phase: str, elapsed_sec: int) -> None:
        phases = {
            "baseline": QApplication.translate("tilauscope_pid", "Observing the stable level"),
            "step_up": QApplication.translate("tilauscope_pid", "Observing a little more heat"),
            "recover_up": QApplication.translate("tilauscope_pid", "Waiting for recovery"),
            "step_down": QApplication.translate("tilauscope_pid", "Observing a little less heat"),
            "recover_down": QApplication.translate("tilauscope_pid", "Waiting for recovery"),
            "identifying": QApplication.translate("tilauscope_pid", "Understanding the machine response"),
            "validating": QApplication.translate("tilauscope_pid", "Trying the cautious setting"),
            "deciding": QApplication.translate("tilauscope_pid", "Checking the final result"),
        }
        label = phases.get(phase, QApplication.translate("tilauscope_pid", "Securing the test"))
        self.guide_progress.setText(QApplication.translate("tilauscope_pid", "TEST IN PROGRESS"))
        self.guide_title.setText(label)
        self.next_steps.setText(QApplication.translate("tilauscope_pid", 
            "Elapsed time: {elapsed}/600 seconds. Stay beside the machine."
        ).format(elapsed=elapsed_sec))
        self.stop_live.show()

    def _live_finished(self, phase: str, reason: str) -> None:
        self.stop_live.setEnabled(False)
        if "journal_persistence_failed" in reason:
            self.guide_progress.setText(QApplication.translate("tilauscope_pid", "TEST FINISHED"))
            self.guide_title.setText(QApplication.translate("tilauscope_pid", "Report unavailable"))
            self.next_steps.setText(QApplication.translate("tilauscope_pid", 
                "Heat is at 0% and the previous settings were restored, but the "
                "report could not be saved. Do not authorize this machine."
            ))
            return
        if reason == "pilot_completed_pending_review":
            self.status.setText(QApplication.translate("tilauscope_pid", 
                "The pilot sequence completed. Heat is at 0%, the previous settings "
                "were restored and the report is ready for review."
            ))
        elif phase == "complete":
            self.status.setText(QApplication.translate("tilauscope_pid", 
                "The response improved safely. The cautious setting was kept and "
                "the complete report was saved."
            ))
        else:
            self.status.setText(QApplication.translate("tilauscope_pid", 
                "The test stopped safely: heat was cut to 0%, the previous settings "
                "were restored and the report was saved."
            ))
        if self.assistant._last_calibration_journal_path is not None:
            self.status.setText(
                self.status.text()
                + "\n"
                + QApplication.translate("tilauscope_pid", "Report: ")
                + str(self.assistant._last_calibration_journal_path)
            )
        self.guide_progress.setText(QApplication.translate("tilauscope_pid", "TEST FINISHED"))
        self.guide_title.setText(QApplication.translate("tilauscope_pid", "The machine is safe"))
        self.next_steps.setText(self.status.text())
        self.status.hide()

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.oldPos = a0.globalPosition().toPoint()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None or not a0.buttons() & Qt.MouseButton.LeftButton:
            return
        delta = a0.globalPosition().toPoint() - self.oldPos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = a0.globalPosition().toPoint()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self._timeout_timer.stop()
        if self._runner is not None and self._runner.coordinator.phase == "running":
            self._runner.abort("preparation_window_closed")
        if self._applied_signal is not None:
            try:
                self._applied_signal.disconnect(self._zero_applied)
            except (TypeError, RuntimeError):
                pass
        if a0 is not None:
            a0.accept()
# pylint: enable=protected-access


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_tilau_theme(self, ground=False)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(600, 580)
        self.oldPos = QPoint()
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        container = QFrame()
        container.setObjectName("MainContainer")
        container.setStyleSheet(
            f"QFrame#MainContainer {{ background-color: {THEME['BG']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 20px; }}"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 24)
        outer.addWidget(container)

        header = QHBoxLayout()
        title = QLabel(QApplication.translate("tilauscope_pid", "UNDERSTANDING THE PID"))
        title.setStyleSheet("color:white; font-size:16px; font-weight:900; border:none;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setProperty("variant", "icon")
        close_btn.clicked.connect(self.close)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        layout.addLayout(header)

        text = QTextBrowser()
        text.setStyleSheet(
            f"QTextBrowser {{ background-color: {THEME['SURFACE']}; color:{THEME['TEXT']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:10px; padding:14px; }}"
        )
        text.setHtml(QApplication.translate("tilauscope_pid", """
        <h3>The four behaviours</h3>
        <p><b>React:</b> how strongly Artisan answers the temperature gap visible now.</p>
        <p><b>Catch up:</b> how quickly Artisan builds an extra correction when the
        machine remains behind the target.</p>
        <p><b>Brake:</b> how much heat Artisan removes when temperature is already
        moving quickly toward the target.</p>
        <p><b>Stabilise:</b> how much Artisan ignores tiny command changes that the
        machine cannot usefully reproduce.</p>
        <hr>
        <h3>Safe method</h3>
        <p>Change one behaviour by one notch. Wait for the machine to respond.
        Keep the change only if the full response improves. If Artisan already
        requests maximum heat, stronger PID settings cannot add more power.</p>
        <p>The normal screen intentionally hides engineering gains. They remain
        available under Engineer details for diagnosis and export.</p>
        """))
        layout.addWidget(text)

        close = QPushButton(QApplication.translate("tilauscope_pid", "CLOSE"))
        close.setMinimumHeight(40)
        close.clicked.connect(self.close)
        layout.addWidget(close)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        self.oldPos = a0.globalPosition().toPoint()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        delta = a0.globalPosition().toPoint() - self.oldPos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = a0.globalPosition().toPoint()
