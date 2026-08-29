"""Custom event button label substitution, shared by every TilauScope surface.

Artisan renders a button label through ``ApplicationWindow.substButtonLabel``,
which reads the pressed state out of the live ``aw.buttonStates`` list.  The
button editor needs the same rendering for a button that is not on screen yet,
and the TilauScope button bar needs it without the live state at all.  Both go
through :func:`subst_button_label`, which takes the state as an argument.

Also holds the plain-word catalogue of the escape sequences, so the editor can
offer them by name instead of by code.
"""

from __future__ import annotations

from typing import Final, NamedTuple

from PyQt6.QtCore import QT_TRANSLATE_NOOP
from PyQt6.QtWidgets import QApplication

from artisanlib.util import (
    events_internal_to_external_value,
    fromCtoFstrict,
    fromFtoCstrict,
)

# Event type stored when the button records nothing at all.
NO_EVENT: Final[int] = 4

# Offsets applied to the event type index (0..3) to encode how the value is
# applied.  Kept identical to Artisan's storage, which the roasting engine and
# the .aset format both depend on.
MODE_SET: Final[int] = 0        # types 0..3   — set the event to the value
MODE_OFFSET: Final[int] = 5     # types 5..8   — add the value to the event
MODE_PERCENT: Final[int] = 9    # types 9..12  — add a percentage of the event


def split_event_type(event_type: int) -> tuple[int, int]:
    """Split a stored event type into ``(etype_index, mode)``.

    ``etype_index`` is -1 when the button records no event.
    """
    t = int(event_type)
    if t == NO_EVENT:
        return -1, MODE_SET
    if 0 <= t <= 3:
        return t, MODE_SET
    if 5 <= t <= 8:
        return t - MODE_OFFSET, MODE_OFFSET
    if 9 <= t <= 12:
        return t - MODE_PERCENT, MODE_PERCENT
    return -1, MODE_SET


def join_event_type(etype_index: int, mode: int) -> int:
    """Inverse of :func:`split_event_type`."""
    if not 0 <= etype_index <= 3:
        return NO_EVENT
    return etype_index + mode


def subst_button_label(label: str, event_type: int, etypes: list[str],
                       event_value: float, mode: str, state: int = 0) -> str:
    """Apply Artisan's label substitutions to ``label``.

    ``etypes`` is ``qmc.etypes`` (the four event names).  ``mode`` is the
    temperature unit, 'C' or 'F'.  ``state`` is 0 for a released button and 1
    for a pressed one; the ``\\2 \\3 \\A \\C \\M \\O \\P \\S`` sequences render
    differently for each.

    Mirrors ``ApplicationWindow.substButtonLabel``; keep the two in step when
    integrating an upstream Artisan update.
    """
    et = int(event_type)
    res = label
    value = events_internal_to_external_value(event_value)
    tempvalue_f = value if mode == 'F' else int(round(fromFtoCstrict(value)))
    tempvalue_c = value if mode == 'C' else int(round(fromCtoFstrict(value)))
    sign = ''
    percent = ''
    if et != 9 and 4 < et < 14 and value > 0:
        sign = '+'
    if 9 < et < 14:
        percent = '%'
    if et > 8:
        et -= 10
    if et > 4:
        et -= 5
    if et < 4 and event_type != 9 and 0 <= et < len(etypes):
        res = res.replace('\\t', etypes[et])

    def _name(i: int) -> str:
        return etypes[i] if 0 <= i < len(etypes) else ''

    on, off = QApplication.translate('Label', 'ON'), QApplication.translate('Label', 'OFF')
    auto, manual = QApplication.translate('Label', 'AUTO'), QApplication.translate('Label', 'MANUAL')
    close, opened = QApplication.translate('Label', 'CLOSE'), QApplication.translate('Label', 'OPEN')
    start, stop = QApplication.translate('Label', 'START'), QApplication.translate('Label', 'STOP')
    for var, subst in (
            ('\\0', off),
            ('\\1', on),
            ('\\2', on if state else off),
            ('\\3', off if state else on),
            ('\\a', auto),
            ('\\A', manual if state else auto),
            ('\\b', QApplication.translate('Label', 'FLAP')),
            ('\\c', close),
            ('\\C', opened if state else close),
            ('\\d', QApplication.translate('Label', 'CONTROL')),
            ('\\D', QApplication.translate('Label', 'DISCHARGE')),
            ('\\e', _name(2)),
            ('\\h', QApplication.translate('Label', 'HEATING')),
            ('\\i', QApplication.translate('Label', 'STIRRER')),
            ('\\f', QApplication.translate('Label', 'FILL')),
            ('\\F', f'{tempvalue_f}{mode}'),
            ('\\l', QApplication.translate('Label', 'COOLING')),
            ('\\m', manual),
            ('\\M', auto if state else manual),
            ('\\o', opened),
            ('\\O', close if state else opened),
            ('\\p', stop),
            ('\\P', start if state else stop),
            ('\\q', _name(0)),
            ('\\r', _name(3)),
            ('\\R', QApplication.translate('Label', 'RELEASE')),
            ('\\s', start),
            ('\\S', stop if state else start),
            ('\\T', f'{sign}{tempvalue_c}{mode}'),
            ('\\V', f'{sign}{value}{percent}'),
            ('\\w', _name(1)),
    ):
        res = res.replace(var, str(subst))
    return res


class Sequence(NamedTuple):
    """One escape sequence, named in words the operator can act on."""
    code: str
    name: str          # source English, translated at display time
    group: str


_SEQ_LAYOUT: Final[str] = QT_TRANSLATE_NOOP('tilauscope_buttons', 'Layout')
_SEQ_EVENT: Final[str] = QT_TRANSLATE_NOOP('tilauscope_buttons', 'Event')
_SEQ_STATE: Final[str] = QT_TRANSLATE_NOOP('tilauscope_buttons', 'State pairs')
_SEQ_WORDS: Final[str] = QT_TRANSLATE_NOOP('tilauscope_buttons', 'Words')

# Ordered as the Insert menu presents them: what a beginner reaches for first.
SEQUENCES: Final[tuple[Sequence, ...]] = (
    Sequence('\\n', QT_TRANSLATE_NOOP('tilauscope_buttons', 'New line'), _SEQ_LAYOUT),

    Sequence('\\t', QT_TRANSLATE_NOOP('tilauscope_buttons', 'Event name'), _SEQ_EVENT),
    Sequence('\\V', QT_TRANSLATE_NOOP('tilauscope_buttons', 'Value'), _SEQ_EVENT),
    Sequence('\\T', QT_TRANSLATE_NOOP('tilauscope_buttons', 'Temperature'), _SEQ_EVENT),
    Sequence('\\q', QT_TRANSLATE_NOOP('tilauscope_buttons', 'Event type 1'), _SEQ_EVENT),
    Sequence('\\w', QT_TRANSLATE_NOOP('tilauscope_buttons', 'Event type 2'), _SEQ_EVENT),
    Sequence('\\e', QT_TRANSLATE_NOOP('tilauscope_buttons', 'Event type 3'), _SEQ_EVENT),
    Sequence('\\r', QT_TRANSLATE_NOOP('tilauscope_buttons', 'Event type 4'), _SEQ_EVENT),

    Sequence('\\1', QT_TRANSLATE_NOOP('tilauscope_buttons', 'ON'), _SEQ_STATE),
    Sequence('\\0', QT_TRANSLATE_NOOP('tilauscope_buttons', 'OFF'), _SEQ_STATE),
    Sequence('\\3', QT_TRANSLATE_NOOP('tilauscope_buttons', 'ON / OFF — follows button state'), _SEQ_STATE),
    Sequence('\\s', QT_TRANSLATE_NOOP('tilauscope_buttons', 'START'), _SEQ_STATE),
    Sequence('\\p', QT_TRANSLATE_NOOP('tilauscope_buttons', 'STOP'), _SEQ_STATE),
    Sequence('\\S', QT_TRANSLATE_NOOP('tilauscope_buttons', 'START / STOP — follows button state'), _SEQ_STATE),
    Sequence('\\o', QT_TRANSLATE_NOOP('tilauscope_buttons', 'OPEN'), _SEQ_STATE),
    Sequence('\\c', QT_TRANSLATE_NOOP('tilauscope_buttons', 'CLOSE'), _SEQ_STATE),
    Sequence('\\O', QT_TRANSLATE_NOOP('tilauscope_buttons', 'OPEN / CLOSE — follows button state'), _SEQ_STATE),
    Sequence('\\a', QT_TRANSLATE_NOOP('tilauscope_buttons', 'AUTO'), _SEQ_STATE),
    Sequence('\\m', QT_TRANSLATE_NOOP('tilauscope_buttons', 'MANUAL'), _SEQ_STATE),
    Sequence('\\A', QT_TRANSLATE_NOOP('tilauscope_buttons', 'AUTO / MANUAL — follows button state'), _SEQ_STATE),

    Sequence('\\h', QT_TRANSLATE_NOOP('tilauscope_buttons', 'HEATING'), _SEQ_WORDS),
    Sequence('\\l', QT_TRANSLATE_NOOP('tilauscope_buttons', 'COOLING'), _SEQ_WORDS),
    Sequence('\\d', QT_TRANSLATE_NOOP('tilauscope_buttons', 'CONTROL'), _SEQ_WORDS),
    Sequence('\\i', QT_TRANSLATE_NOOP('tilauscope_buttons', 'STIRRER'), _SEQ_WORDS),
    Sequence('\\f', QT_TRANSLATE_NOOP('tilauscope_buttons', 'FILL'), _SEQ_WORDS),
    Sequence('\\b', QT_TRANSLATE_NOOP('tilauscope_buttons', 'FLAP'), _SEQ_WORDS),
    Sequence('\\D', QT_TRANSLATE_NOOP('tilauscope_buttons', 'DISCHARGE'), _SEQ_WORDS),
    Sequence('\\R', QT_TRANSLATE_NOOP('tilauscope_buttons', 'RELEASE'), _SEQ_WORDS),
)
