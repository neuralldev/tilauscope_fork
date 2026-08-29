"""The other half of the privacy gate: who is told, and when.

``test_ai_privacy`` covers what a payload may contain. These cover whether the
operator was told who receives it — once per provider, never during a roast,
and re-armed the moment the recipient changes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tilauscope.tilau_privacy_ui import (
    AiPayloadPreviewDialog, Gate, acknowledged_ai_provider, ensure_ai_disclosure,
    ensure_geo_consent, forget_ai_disclosure, forget_geo_consent,
    geo_consent_granted,
)

DECLINE = 0
ACCEPT  = 1


@pytest.fixture(autouse=True)
def _fresh_install():
    """Every test starts on a machine that has never been asked."""
    forget_ai_disclosure()
    forget_geo_consent()
    yield
    forget_ai_disclosure()
    forget_geo_consent()


def _cfg(client_id: str = 'anthropic', engine: str = 'anthropic/claude-opus-5'):
    return SimpleNamespace(client_id=client_id, engine=engine,
                           provider_name=client_id.capitalize())


def _aw(charged: bool):
    """An Artisan stand-in. CHARGE is index 0, whose unmarked value is -1."""
    return SimpleNamespace(qmc=SimpleNamespace(
        flagstart=charged,
        timeindex=[12 if charged else -1, 0, 0, 0, 0, 0, 0, 0]))


class _Asked:
    """Records that the dialog was raised, and answers it."""

    def __init__(self, answer: int) -> None:
        self.answer = answer
        self.calls  = 0

    def __call__(self, *_args, **_kwargs) -> int:
        self.calls += 1
        return self.answer


def _patch_dialog(monkeypatch, answer: int) -> _Asked:
    asked = _Asked(answer)
    monkeypatch.setattr('tilauscope.tilauscope_types.show_styled_message', asked)
    return asked


# ── the AI disclosure ────────────────────────────────────────────────────────

def test_a_fresh_install_has_been_told_nothing() -> None:
    assert acknowledged_ai_provider() == ''
    assert geo_consent_granted() is False


def test_the_operator_is_told_once_and_then_left_alone(monkeypatch) -> None:
    asked = _patch_dialog(monkeypatch, ACCEPT)
    cfg = _cfg()

    assert ensure_ai_disclosure(None, cfg) is Gate.ALLOW
    assert ensure_ai_disclosure(None, cfg) is Gate.ALLOW
    assert asked.calls == 1, 'the disclosure was raised twice for one provider'
    assert acknowledged_ai_provider() == 'anthropic'


def test_declining_sends_nothing_and_is_not_taken_as_an_answer(monkeypatch) -> None:
    asked = _patch_dialog(monkeypatch, DECLINE)
    cfg = _cfg()

    assert ensure_ai_disclosure(None, cfg) is Gate.DECLINED
    assert acknowledged_ai_provider() == '', 'a refusal was stored as consent'
    assert ensure_ai_disclosure(None, cfg) is Gate.DECLINED
    assert asked.calls == 2, 'the question stopped being asked after a no'


@pytest.mark.parametrize('answer', [-1, 2, 99])
def test_an_answer_that_is_not_the_accept_button_sends_nothing(monkeypatch, answer) -> None:
    """A dialog closed by the window manager returns -1. Nothing may leave on it."""
    _patch_dialog(monkeypatch, answer)
    assert ensure_ai_disclosure(None, _cfg()) is Gate.DECLINED
    assert acknowledged_ai_provider() == ''


def test_a_new_provider_is_disclosed_again(monkeypatch) -> None:
    asked = _patch_dialog(monkeypatch, ACCEPT)

    assert ensure_ai_disclosure(None, _cfg('anthropic')) is Gate.ALLOW
    assert ensure_ai_disclosure(None, _cfg('openai', 'openai/gpt-4o')) is Gate.ALLOW
    assert asked.calls == 2, 'a second recipient inherited the first one\'s answer'
    assert acknowledged_ai_provider() == 'openai'


def test_a_different_model_at_the_same_provider_does_not_ask_again(monkeypatch) -> None:
    """The recipient is the provider. Changing model changes nothing about who."""
    asked = _patch_dialog(monkeypatch, ACCEPT)

    assert ensure_ai_disclosure(None, _cfg('anthropic', 'anthropic/a')) is Gate.ALLOW
    assert ensure_ai_disclosure(None, _cfg('anthropic', 'anthropic/b')) is Gate.ALLOW
    assert asked.calls == 1


def test_a_running_roast_is_refused_rather_than_interrupted(monkeypatch) -> None:
    asked = _patch_dialog(monkeypatch, ACCEPT)

    assert ensure_ai_disclosure(None, _cfg(), _aw(charged=True)) is Gate.BLOCKED_ROAST
    assert asked.calls == 0, 'a dialog was raised with a batch in the drum'
    assert acknowledged_ai_provider() == ''


def test_a_roast_already_disclosed_still_goes_through(monkeypatch) -> None:
    """The block guards the reading, not the request: once told, a roast may ask."""
    _patch_dialog(monkeypatch, ACCEPT)
    assert ensure_ai_disclosure(None, _cfg()) is Gate.ALLOW
    assert ensure_ai_disclosure(None, _cfg(), _aw(charged=True)) is Gate.ALLOW


def test_monitoring_without_a_charge_is_not_a_roast(monkeypatch) -> None:
    asked = _patch_dialog(monkeypatch, ACCEPT)
    idle = SimpleNamespace(qmc=SimpleNamespace(
        flagstart=True, timeindex=[-1, 0, 0, 0, 0, 0, 0, 0]))

    assert ensure_ai_disclosure(None, _cfg(), idle) is Gate.ALLOW
    assert asked.calls == 1


def test_no_provider_configured_sends_nothing(monkeypatch) -> None:
    asked = _patch_dialog(monkeypatch, ACCEPT)
    assert ensure_ai_disclosure(None, None) is Gate.DECLINED
    assert asked.calls == 0


def test_a_dialog_that_cannot_be_raised_sends_nothing(monkeypatch) -> None:
    """Fail closed: an unusable screen must not become silent consent."""
    def _boom(*_args, **_kwargs):
        raise RuntimeError('no display')
    monkeypatch.setattr('tilauscope.tilauscope_types.show_styled_message', _boom)

    assert ensure_ai_disclosure(None, _cfg()) is Gate.DECLINED
    assert acknowledged_ai_provider() == ''


# ── the location lookup ──────────────────────────────────────────────────────

def test_the_location_lookup_asks_once_and_remembers_a_yes(monkeypatch) -> None:
    asked = _patch_dialog(monkeypatch, ACCEPT)

    assert ensure_geo_consent(None) is True
    assert ensure_geo_consent(None) is True
    assert asked.calls == 1
    assert geo_consent_granted() is True


def test_the_location_lookup_keeps_explaining_itself_after_a_no(monkeypatch) -> None:
    """A no is not stored: the button must not go quietly dead."""
    asked = _patch_dialog(monkeypatch, DECLINE)

    assert ensure_geo_consent(None) is False
    assert ensure_geo_consent(None) is False
    assert asked.calls == 2
    assert geo_consent_granted() is False


def test_a_location_dialog_that_cannot_be_raised_looks_nothing_up(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError('no display')
    monkeypatch.setattr('tilauscope.tilauscope_types.show_styled_message', _boom)

    assert ensure_geo_consent(None) is False


# ── what the preview says ────────────────────────────────────────────────────

def test_a_clean_payload_is_reported_as_carrying_nothing_personal() -> None:
    from tilauscope.tilau_privacy import RedactionReport

    line = AiPayloadPreviewDialog._removed_line(RedactionReport())
    assert 'nothing' in line


def test_a_scrubbed_payload_names_what_was_taken_out() -> None:
    from tilauscope.tilau_privacy import RedactionReport

    report = RedactionReport()
    report.note('email', 2)
    report.urls_cleaned = 1

    line = AiPayloadPreviewDialog._removed_line(report)
    assert 'email' in line and 'urls-cleaned' in line
    assert 'nothing' not in line


def test_truncation_is_stated_only_when_it_happened() -> None:
    from tilauscope.tilau_privacy import RedactionReport

    assert AiPayloadPreviewDialog._shortened_line(RedactionReport()) == ''

    report = RedactionReport()
    report.truncated_chars = 4210
    assert '4210' in AiPayloadPreviewDialog._shortened_line(report)


def test_the_preview_shows_both_halves_of_the_request() -> None:
    body = AiPayloadPreviewDialog._compose([
        {'role': 'system', 'content': 'you are a roasting consultant'},
        {'role': 'user',   'content': 'charge 250 g'},
    ])
    assert 'you are a roasting consultant' in body
    assert 'charge 250 g' in body
    assert body.index('you are a roasting consultant') < body.index('charge 250 g')


# ── the contract the whole gate rests on ─────────────────────────────────────

@pytest.mark.usefixtures('qapp')
@pytest.mark.parametrize('clicked', [DECLINE, ACCEPT])
def test_a_two_button_styled_dialog_reports_which_button_was_pressed(clicked) -> None:
    """``show_styled_message(buttons=[…])`` returns the index of the button.

    Every gate above reads that index, and no other call site in the
    application passes ``buttons=`` — so nothing else would notice if Qt
    stopped reporting it and both answers started reading as "Not now".
    """
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QMessageBox
    from tilauscope.tilauscope_types import TilauMessageBox

    box = TilauMessageBox(None, 'title', 'body', QMessageBox.Icon.Information,
                          False, 0, ['Not now', 'Send to X'])
    buttons = list(box.buttons())
    QTimer.singleShot(0, buttons[clicked].click)
    assert box.exec() == clicked


# ── declining the lookup is a path, not a dead end ───────────────────────────
#
# These import tilau_privacy_ui only. Anything under tilauscope/cave/ drags in
# artisanlib.main through cave/__init__.py, which configures logging at import
# and breaks caplog for every test that runs afterwards.

@pytest.mark.usefixtures('qapp')
def test_declining_a_lookup_hands_the_field_over(monkeypatch) -> None:
    """"I'll type it" has to leave the operator able to type.

    The dialog offers two ways to fill the same values. If the manual one only
    closes the dialog, the button reads as having done nothing.
    """
    from PyQt6.QtWidgets import QDoubleSpinBox, QVBoxLayout, QWidget
    from tilauscope.tilau_privacy_ui import hand_over_to_manual_entry

    landed: list[int] = []
    monkeypatch.setattr(
        'PyQt6.QtCore.QTimer.singleShot',
        staticmethod(lambda ms, fn: (landed.append(ms), fn())))

    # A widget only takes focus inside a window, so the field is given one —
    # as it has in BeanCave.
    host = QWidget()
    field = QDoubleSpinBox()
    QVBoxLayout(host).addWidget(field)
    host.show()
    field.setValue(21.0)

    hand_over_to_manual_entry(field)

    # focusWidget(), not hasFocus(): the offscreen platform never makes a
    # window active, and hasFocus() answers for the active window.
    assert host.focusWidget() is field, (
        'nothing was focused — the manual path is a dead end')
    assert field.lineEdit().selectedText(), 'the value is not selected to type over'
    assert landed and landed[0] > 400, (
        'the focus was requested before the dialog finished fading out, so Qt '
        'gives it straight back to the button that opened it')


@pytest.mark.usefixtures('qapp')
def test_the_handover_survives_a_window_closed_while_it_waited(monkeypatch) -> None:
    """The handover is deferred, so the widget may be gone when it lands."""
    from tilauscope.tilau_privacy_ui import hand_over_to_manual_entry

    class _Dead:
        def setFocus(self, _reason):
            raise RuntimeError('wrapped C/C++ object has been deleted')

    monkeypatch.setattr('PyQt6.QtCore.QTimer.singleShot',
                        staticmethod(lambda _ms, fn: fn()))
    hand_over_to_manual_entry(_Dead())   # must not raise


def test_no_field_to_hand_over_asks_for_nothing(monkeypatch) -> None:
    from tilauscope.tilau_privacy_ui import hand_over_to_manual_entry

    fired: list[int] = []
    monkeypatch.setattr('PyQt6.QtCore.QTimer.singleShot',
                        staticmethod(lambda ms, _fn: fired.append(ms)))
    hand_over_to_manual_entry(None)
    assert not fired
