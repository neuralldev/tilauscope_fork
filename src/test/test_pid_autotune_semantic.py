from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QSemaphore, Qt
from PyQt6.QtWidgets import QSizeGrip, QScrollArea, QWidget

from tilauscope.pid_autotune import CalibrationReadinessDialog, PIDAutotune


class _Action:
    checked = False

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt-compatible fake
        self.checked = checked


class _Signal:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []
        self.events: list[tuple[Any, ...]] = []

    def connect(self, callback: Any) -> None:
        self.callbacks.append(callback)

    def disconnect(self, callback: Any) -> None:
        self.callbacks.remove(callback)

    def emit(self, *args: Any) -> None:
        self.events.append(args)
        for callback in tuple(self.callbacks):
            callback(*args)


class _Engine:
    def __init__(self) -> None:
        self.pidSemaphore = QSemaphore(1)
        self.lastInput = 190.0
        self.target = 200.0
        self.Pterm = 30.0
        self.Iterm = 2.0
        self.Dterm = -4.0
        self.lastOutput = 62.0
        self.active = True
        self.outMin = 0
        self.outMax = 100

    @staticmethod
    def getKp(_: float) -> float:  # noqa: N802 - mirrors Artisan API
        return 10.0

    @staticmethod
    def getKi(_: float) -> float:  # noqa: N802 - mirrors Artisan API
        return 0.1

    @staticmethod
    def getKd(_: float) -> float:  # noqa: N802 - mirrors Artisan API
        return 20.0


class _Control:
    def __init__(self) -> None:
        self.pidKp = 10.0
        self.pidKi = 0.1
        self.pidKd = 20.0
        self.pidKp1 = 8.0
        self.pidKi1 = 0.08
        self.pidKd1 = 30.0
        self.pidKp2 = 6.0
        self.pidKi2 = 0.06
        self.pidKd2 = 40.0
        self.svValue = 200.0
        self.pidGainScheduling = False
        self.pidGainSchedulingSV = True
        self.pidGainSchedulingQuadratic = False
        self.pidSchedule0 = 95.0
        self.pidSchedule1 = 150.0
        self.pidSchedule2 = 185.0
        self.pidPsetpointWeight = 1.0
        self.pidDsetpointWeight = 1.0
        self.pidCycle = 1000
        self.pidNegativeTarget = 0
        self.dutySteps = 1
        self.duty_filter = 0
        self.derivative_filter = 0
        self.pidDlimit = 500.0
        self.pidIlimitFactor = 1.0
        self.pidIWP = True
        self.pidIRoC = False
        self.pidIRoCthreshold = 30.0
        self.sv_filter = 0
        self.dutyMin = 0
        self.dutyMax = 80
        self.positiveTargetRangeLimit = False
        self.positiveTargetMin = 0
        self.positiveTargetMax = 100
        self.negativeTargetRangeLimit = False
        self.negativeTargetMin = 0
        self.negativeTargetMax = 100
        self.pidSource = 1
        self.pidActive = True
        self.pidPositiveTarget = 4
        self.invertControl = False
        self.conf_calls = 0

    @staticmethod
    def externalPIDControl() -> int:  # noqa: N802 - mirrors Artisan API
        return 0

    def confSoftwarePID(self, reset: bool = False) -> None:  # noqa: N802
        assert reset is False
        self.conf_calls += 1


class _ProbeSeries:
    """Sampled-series view over the engine value.

    The readiness path reads the series that feeds the PID, not the engine
    snapshot, so a test that moves ``lastInput`` must move both.
    """

    def __init__(self, engine: _Engine) -> None:
        self._engine = engine

    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> float:  # noqa: ARG002
        return self._engine.lastInput


@pytest.fixture
def semantic_window(qapp: Any) -> tuple[PIDAutotune, _Control, _Action]:  # noqa: ARG001
    engine = _Engine()
    control = _Control()
    action = _Action()
    command_signal = _Signal()
    applied_signal = _Signal()
    manual_signal = _Signal()
    aw = SimpleNamespace(
        qmc=SimpleNamespace(
            mode="C",
            pid=engine,
            flagon=True,
            flagstart=False,
            on_timex=[1.0],
            on_temp1=_ProbeSeries(engine),
            on_temp2=_ProbeSeries(engine),
            timex=[],
            temp1=_ProbeSeries(engine),
            temp2=_ProbeSeries(engine),
        ),
        pidcontrol=control,
        PIDAutotuneMenuAction=action,
        tilau_roaster="ITOP Cyberroaster",
        # slider 0 = airflow, needed so the test can cool the machine at the end
        eventslideractions=[7, 0, 0, 5],
        eventslidercommands=["FAN:{}", "", "", "HEAT:{}"],
        eventsliderfactors=[1.0, 1.0, 1.0, 1.0],
        eventslideroffsets=[0.0, 0.0, 0.0, 0.0],
        eventslidervalues=[0, 0, 0, 30],
        eventslidermin=[0, 0, 0, 0],
        eventslidermax=[100, 100, 100, 100],
        simulator=None,
        tilauPreheatingPid=None,
        tilaupidSliderCommandSignal=command_signal,
        tilaupidSliderAppliedSignal=applied_signal,
        tilauManualSliderMovedSignal=manual_signal,
    )
    command_signal.connect(
        lambda slider, power, fire: (
            aw.eventslidervalues.__setitem__(slider, power),
            applied_signal.emit(slider, power, fire),
        )
    )
    window = PIDAutotune(None, aw)  # type: ignore[arg-type]
    window.present()
    qapp.processEvents()
    yield window, control, action
    window.close()


def test_present_creates_a_visible_dialog_window(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, _, _ = semantic_window
    assert window.isWindow()
    assert window.isVisible()
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.height() <= 620
    assert window.maximumHeight() <= 620
    scroll = window.findChild(QScrollArea, "PIDAssistantScroll")
    assert scroll is not None
    assert scroll.widgetResizable()
    assert window.findChild(QSizeGrip) is not None


def test_present_with_a_visible_main_window_parent(
    qapp: Any,
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    first_window, _, _ = semantic_window
    parent = QWidget()
    parent.resize(1200, 800)
    parent.show()
    dialog = PIDAutotune(parent, first_window.aw)

    dialog.present()
    qapp.processEvents()

    assert dialog.parentWidget() is parent
    assert dialog.windowType() == Qt.WindowType.Dialog
    assert dialog.isVisible()
    dialog.close()
    parent.close()


def test_start_is_read_only_until_a_behaviour_button_is_used(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    before = control.pidKp, control.pidKi, control.pidKd

    window.start_monitoring()
    window.update_logic()

    assert (control.pidKp, control.pidKi, control.pidKd) == before
    assert control.conf_calls == 0
    assert "accelerating" in window.lbl_headline.text().lower()


def test_calibration_rehearsal_runs_600_virtual_seconds_without_config_write(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    before = control.pidKp, control.pidKi, control.pidKd

    window._run_calibration_self_test()

    assert (control.pidKp, control.pidKi, control.pidKd) == before
    assert control.conf_calls == 0
    assert "600" in window.lbl_calibration.text()
    assert "passed" in window._calibration_engineering
    assert window.btn_calibration_live.isEnabled()


def test_live_readiness_reads_real_application_gates_without_commands(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )

    report = window._live_calibration_readiness(
        machine_empty=True,
        airflow_safe=True,
        supervised=True,
    )

    assert report.ready
    assert control.conf_calls == 0


def test_runtime_interlock_reads_current_application_state(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    assert window._runtime_calibration_stop_reason(
        manual_override=False, communication_ok=True
    ) is None

    window.aw.qmc.flagstart = True
    assert window._runtime_calibration_stop_reason(
        manual_override=False, communication_ok=True
    ) == "roast_started"
    window.aw.qmc.flagstart = False

    window.aw.simulator = object()
    assert window._runtime_calibration_stop_reason(
        manual_override=False, communication_ok=True
    ) == "simulator_started"
    window.aw.simulator = None

    assert window._runtime_calibration_stop_reason(
        manual_override=True, communication_ok=True
    ) == "manual_override"
    assert window._runtime_calibration_stop_reason(
        manual_override=False, communication_ok=False
    ) == "communication_lost"


def test_live_runner_is_built_without_command_and_only_starts_explicitly(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    window.aw.qmc.pid.lastInput = 200.0
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )
    readiness = window._live_calibration_readiness(
        machine_empty=True,
        airflow_safe=True,
        supervised=True,
    )
    identity = window._calibration_machine_identity()
    assert readiness.ready
    assert identity is not None
    window._zero_output_qualified = True
    window._qualified_machine_fingerprint = identity.fingerprint

    runner = window._build_live_calibration_runner(
        readiness=readiness,
        identity=identity,
    )
    journals: list[str] = []
    runner.persist_journal = lambda coordinator: journals.append(coordinator.phase)
    assert window.aw.tilaupidSliderCommandSignal.events == []

    runner.start()
    assert window.aw.tilaupidSliderCommandSignal.events == [(3, 30, True)]
    runner.close()

    # The stop cuts the heat and then opens the airflow to cool the machine.
    events = window.aw.tilaupidSliderCommandSignal.events
    assert (3, 0, True) in events
    assert events[-1] == (0, 80, True)
    assert journals == ["safe_stop"]


def test_live_authorization_is_bound_to_roaster_and_exact_actuator(
    monkeypatch: pytest.MonkeyPatch,
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, _control, _ = semantic_window
    identity = window._calibration_machine_identity()
    assert identity is not None
    monkeypatch.setattr(
        PIDAutotune,
        "_LIVE_CALIBRATION_ACTUATORS",
        frozenset({(identity.roaster_id, identity.actuator_signature)}),
    )
    assert window._live_calibration_profile_authorized(identity)

    window.aw.eventslidercommands[3] = "DIFFERENT:{}"
    changed = window._calibration_machine_identity()
    assert changed is not None
    assert not window._live_calibration_profile_authorized(changed)
    assert not window._supervised_pilot_profile_authorized(changed)


def test_exact_itop_path_can_only_offer_a_review_only_pilot(
    monkeypatch: pytest.MonkeyPatch,
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )
    identity = window._calibration_machine_identity()
    assert identity is not None
    monkeypatch.setattr(
        PIDAutotune,
        "_SUPERVISED_PILOT_ACTUATORS",
        frozenset({(identity.roaster_id, identity.actuator_signature)}),
    )
    dialog = CalibrationReadinessDialog(window)
    dialog.machine_empty.setChecked(True)
    dialog.airflow_safe.setChecked(True)
    dialog.supervised.setChecked(True)
    dialog.qualification.phase = "qualified"
    dialog._qualification_identity = identity
    # The hand-over already happened in this scenario: hold the sequence at
    # "ready" so the tick does not restart an approach.
    dialog.start_preparation()
    dialog._preparation.phase = "ready"
    window._zero_output_qualified = True
    window._qualified_machine_fingerprint = identity.fingerprint

    dialog.refresh()

    assert dialog.start_live.isEnabled()
    assert "REVIEW-ONLY" in dialog.start_live.text()
    assert window._supervised_pilot_profile_authorized(identity)
    assert not window._live_calibration_profile_authorized(identity)
    dialog.close()


def test_preparation_dialog_reveals_one_guided_action_at_a_time(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    window.aw.eventslidervalues[3] = 0
    window.aw.qmc.pid.lastInput = -1.0

    dialog = CalibrationReadinessDialog(window)

    scroll = dialog.findChild(QScrollArea, "CalibrationPreparationScroll")
    assert scroll is not None
    assert scroll.widgetResizable()
    assert dialog.height() <= 520
    assert dialog.maximumHeight() <= 520
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert dialog.findChild(QWidget, "CalibrationPreparationCard") is not None
    assert dialog.findChild(QSizeGrip) is not None
    assert "valid bean-temperature" in dialog.next_steps.text()
    assert not dialog.checks.isVisible()
    assert dialog.machine_empty.isHidden()

    window.aw.qmc.pid.lastInput = 200.0
    window.update_logic()
    dialog.refresh()
    assert "between 13% and 67%" in dialog.next_steps.text()
    assert "holding at 0%" in dialog.next_steps.text()
    assert dialog.machine_empty.isHidden()

    # Nobody sets the heater any more: once the machine has room, the guidance
    # is about TilauScope bringing it up, never about a gesture to make.
    window.aw.eventslidervalues[3] = 30
    window.update_logic()
    dialog.refresh()
    assert "nothing to set" in dialog.next_steps.text().lower()

    window._readiness_history.clear()
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )
    dialog.refresh()
    assert not dialog.machine_empty.isHidden()
    assert dialog.airflow_safe.isHidden()
    dialog.machine_empty.setChecked(True)
    assert dialog.machine_empty.isHidden()
    assert not dialog.airflow_safe.isHidden()
    assert window.aw.tilaupidSliderCommandSignal.events == []
    dialog.close()


def test_preparation_secures_controllers_before_requesting_manual_heat(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = True
    window.aw.qmc.pid.lastInput = 200.0
    window.aw.eventslidervalues[3] = 30
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )

    dialog = CalibrationReadinessDialog(window)

    assert "Stop Artisan's PID" in dialog.next_steps.text()
    assert "heater slightly" not in dialog.next_steps.text()
    dialog.close()


def test_exporting_pilot_sheet_never_sends_an_actuator_command(
    monkeypatch: pytest.MonkeyPatch,
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, _control, _ = semantic_window
    exported = Path("/tmp/pilot-test.json")
    monkeypatch.setattr(
        window,
        "_export_hardware_pilot_manifest",
        lambda _identity: exported,
    )
    dialog = CalibrationReadinessDialog(window)

    dialog._export_pilot_sheet()

    assert str(exported) in dialog.status.text()
    assert window.aw.tilaupidSliderCommandSignal.events == []
    dialog.close()


def test_zero_shutdown_bench_only_sends_zero_and_never_restores_power(
    monkeypatch: pytest.MonkeyPatch,
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )
    dialog = CalibrationReadinessDialog(window)
    dialog.machine_empty.setChecked(True)
    dialog.airflow_safe.setChecked(True)
    dialog.supervised.setChecked(True)
    monkeypatch.setattr(
        "tilauscope.pid_autotune.show_styled_message",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(window, "_record_zero_output_evidence", lambda _identity: True)

    dialog._request_zero()

    assert window.aw.tilaupidSliderCommandSignal.events == [(3, 0, True)]
    assert window.aw.eventslidervalues[3] == 0
    assert dialog.qualification.phase == "software_zero_confirmed"
    dialog.physical_off.setChecked(True)
    dialog._confirm_physical_shutdown()
    assert dialog.qualification.phase == "qualified"
    assert window._zero_output_qualified
    assert not dialog.start_live.isEnabled()
    assert not window._live_calibration_profile_authorized(
        window._calibration_machine_identity()
    )
    assert window.aw.eventslidervalues[3] == 0
    assert window.aw.tilaupidSliderCommandSignal.events == [(3, 0, True)]
    dialog.close()


def test_zero_shutdown_proof_is_invalidated_when_actuator_path_changes(
    monkeypatch: pytest.MonkeyPatch,
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )
    dialog = CalibrationReadinessDialog(window)
    dialog.machine_empty.setChecked(True)
    dialog.airflow_safe.setChecked(True)
    dialog.supervised.setChecked(True)
    monkeypatch.setattr(
        "tilauscope.pid_autotune.show_styled_message",
        lambda *_args, **_kwargs: 1,
    )

    # Hold the acknowledgement so the control path can change in flight.
    window.aw.tilaupidSliderCommandSignal.callbacks.clear()
    dialog._request_zero()
    window.aw.eventslidercommands[3] = "OTHER_HEATER:{}"
    window.aw.tilaupidSliderAppliedSignal.emit(3, 0, True)

    assert dialog.qualification.phase == "failed"
    assert dialog.qualification.reason == "machine_identity_changed"
    assert not window._zero_output_qualified
    dialog.close()


def test_zero_dispatch_failure_never_claims_physical_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    control.pidActive = False
    window._measured_holding_point_c = 200.0
    window._readiness_history.extend(
        (float(second), 200.0, 0.1, 0.1) for second in range(30)
    )
    dialog = CalibrationReadinessDialog(window)
    dialog.machine_empty.setChecked(True)
    dialog.airflow_safe.setChecked(True)
    dialog.supervised.setChecked(True)
    monkeypatch.setattr(
        "tilauscope.pid_autotune.show_styled_message",
        lambda *_args, **_kwargs: 1,
    )
    window.aw.tilaupidSliderCommandSignal.callbacks.clear()
    window.aw.tilaupidSliderCommandSignal.connect(
        lambda slider, power, _fire: window.aw.tilaupidSliderAppliedSignal.emit(
            slider, power, False
        )
    )

    dialog._request_zero()

    assert dialog.qualification.phase == "failed"
    assert dialog.qualification.reason == "heater_action_not_fired"
    assert "physical shutdown is not confirmed" in dialog.next_steps.text()
    assert "remains at 0%" not in dialog.next_steps.text()
    dialog.close()


def test_terminal_result_disconnects_runner_and_requires_physical_confirmation(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, _control, _ = semantic_window
    dialog = CalibrationReadinessDialog(window)
    closed: list[bool] = []
    runner = SimpleNamespace(
        coordinator=SimpleNamespace(shutdown_command_dispatched=True),
        close=lambda: closed.append(True),
    )
    dialog._runner = runner
    window._calibration_runner = runner

    dialog._live_finished("safe_stop", "operator_cancelled")

    assert closed == [True]
    assert dialog._runner is None
    assert window._calibration_runner is None
    assert dialog._awaiting_final_shutdown_confirmation
    assert "VERIFY THE PHYSICAL HEATER" in dialog.guide_title.text()
    assert "machine is safe" not in dialog.next_steps.text().lower()
    assert not dialog.final_physical_off.isHidden()
    assert not dialog.confirm_final_shutdown.isEnabled()

    dialog.final_physical_off.setChecked(True)
    assert dialog.confirm_final_shutdown.isEnabled()
    dialog._confirm_final_physical_shutdown()

    assert not dialog._awaiting_final_shutdown_confirmation
    assert "Physical heater shutdown confirmed" in dialog.guide_title.text()
    dialog.close()


def test_terminal_dialog_cannot_close_before_physical_confirmation(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, _control, _ = semantic_window
    dialog = CalibrationReadinessDialog(window)
    dialog._awaiting_final_shutdown_confirmation = True

    dialog._request_close()

    assert dialog._awaiting_final_shutdown_confirmation
    assert "before closing" in dialog.guide_title.text()
    dialog.final_physical_off.setChecked(True)
    dialog._confirm_final_physical_shutdown()
    dialog.close()


def test_behaviour_notch_applies_live_and_undo_restores_it(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    window.start_monitoring()

    window._apply_behaviour("braking", -1, -1)
    assert control.pidKd == pytest.approx(20.0 / 1.15)
    assert control.conf_calls == 1
    assert window._offsets["braking"] == -1

    window.undo_last_change()
    assert control.pidKd == pytest.approx(20.0)
    assert control.conf_calls == 2
    assert window._offsets["braking"] == 0


def test_complete_pid_snapshot_round_trips_every_safety_relevant_field(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, control, _ = semantic_window
    snapshot = window._capture_config()

    for name, value in snapshot.items():
        if isinstance(value, bool):
            setattr(control, name, not value)
        elif isinstance(value, int):
            setattr(control, name, value + 1)
        else:
            setattr(control, name, value + 0.5)
    assert window._capture_config() != snapshot

    window._apply_config(snapshot)

    assert window._capture_config() == snapshot
    assert control.conf_calls == 1


def test_close_unchecks_menu_action(
    semantic_window: tuple[PIDAutotune, _Control, _Action],
) -> None:
    window, _, action = semantic_window
    assert action.checked is True
    window.close()
    assert action.checked is False
