#
# ABOUT
# Artisan settings TilauScope imposes: one-second sampling without Keep ON or
# viewer hand-off, and the BT / BT projection / ΔBT curve selection.

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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from PyQt6.QtCore import QTimer

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

_log = logging.getLogger(__name__)

SAMPLING_INTERVAL_MS: Final[int] = 1000

#: Imposed main-curve selection, as qmc attribute -> value.
CURVE_FLAGS: Final[dict[str, bool]] = {
    'BTcurve': True,
    'BTprojectFlag': True,
    'DeltaBTflag': True,
    'ETcurve': False,
    'ETprojectFlag': False,
    'DeltaETflag': False,
    'projectDeltaFlag': False,
}

#: Readout label, palette key and flag that dims it — the pairs Artisan's toggles use.
_READOUT_LABELS: Final[tuple[tuple[str, str, str], ...]] = (
    ('label2', 'et', 'ETcurve'),
    ('label3', 'bt', 'BTcurve'),
    ('label4', 'deltaet', 'DeltaETflag'),
    ('label5', 'deltabt', 'DeltaBTflag'),
)

#: Position of forceRenewAxis in tgraphcanvas.redraw()'s signature.
_FORCE_RENEW_AXIS_ARG: Final[int] = 3


def enforce_sampling(aw: ApplicationWindow) -> bool:
    """Impose the Sampling dialog values. True when something changed."""
    qmc = aw.qmc
    changed = False
    if qmc.delay != SAMPLING_INTERVAL_MS:
        aw.setSamplingRate(SAMPLING_INTERVAL_MS)  # also refreshes the ticks derived from it
        changed = True
        if qmc.delay != SAMPLING_INTERVAL_MS:
            _log.warning('sampling interval %s ms refused: Artisan keeps %s ms (min_delay %s ms)',
                         SAMPLING_INTERVAL_MS, qmc.delay, qmc.min_delay)
    if qmc.flagKeepON:
        qmc.flagKeepON = False
        changed = True
    if qmc.flagOpenCompleted:
        qmc.flagOpenCompleted = False
        changed = True
    return changed


def enforce_curves(aw: ApplicationWindow) -> bool:
    """Impose the main-curve selection. True when something changed.

    State only — rendering is left to the redraw the caller already performs.
    """
    qmc = aw.qmc
    wrong = [name for name, value in CURVE_FLAGS.items() if getattr(qmc, name) != value]
    if not wrong:
        return False
    for name in wrong:
        setattr(qmc, name, CURVE_FLAGS[name])
    if 'BTcurve' in wrong or 'ETcurve' in wrong:
        # event annotations sit on BT or ET; their cached positions belong to the old curve
        qmc.l_annotations_dict = {}
        qmc.l_event_flags_dict = {}
    for label_attr, colour_key, flag in _READOUT_LABELS:
        label = getattr(aw, label_attr, None)
        colour = qmc.palette.get(colour_key)
        if label is not None and colour:
            aw.setLabelColor(label, colour, CURVE_FLAGS[flag])
    return True


def enforce(aw: ApplicationWindow) -> bool:
    """Impose every value. True when something changed."""
    sampling = enforce_sampling(aw)
    curves = enforce_curves(aw)
    return sampling or curves


def _with_axis_renewal(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if len(args) > _FORCE_RENEW_AXIS_ARG:
        return (*args[:_FORCE_RENEW_AXIS_ARG], True, *args[_FORCE_RENEW_AXIS_ARG + 1:]), kwargs
    return args, {**kwargs, 'forceRenewAxis': True}


class ArtisanDisplayPolicy:
    """Keeps the imposed values in force on every path that can change them.

    - after each settingsLoad(): boot, imported or machine settings, themes. Artisan
      reads the sampling and curve values after the menu rebuild settingsLoad() runs,
      so the menu hook alone would be overwritten;
    - before each qmc.redraw(), which every curve toggle ends with: readout clicks,
      showCurve() commands, the Devices dialog;
    - after a legend click, which hides a line without touching its flag.

    The sampling interval has no other writer than settingsLoad() and the hidden
    Sampling dialog, so monitoring always starts at the imposed period.
    """

    def __init__(self, aw: ApplicationWindow) -> None:
        self._aw = aw
        self._installed = False

    def install(self) -> None:
        """Wrap once, at window construction. It must precede CanvasStyleHook, which
        restores the redraw it found when the roasting window closes."""
        if self._installed:
            return
        try:
            aw = self._aw
            qmc = aw.qmc
            original_settings_load = aw.settingsLoad
            original_redraw = qmc.redraw

            def _settings_load(*args: Any, **kwargs: Any) -> Any:
                result = original_settings_load(*args, **kwargs)
                self.enforce()
                return result

            def _redraw(*args: Any, **kwargs: Any) -> Any:
                try:
                    two_axis = qmc.twoAxisMode()
                    if enforce_curves(aw) and qmc.twoAxisMode() != two_axis:
                        args, kwargs = _with_axis_renewal(args, kwargs)
                except Exception:  # pylint: disable=broad-except
                    _log.exception('imposing the Artisan curve selection failed')
                return original_redraw(*args, **kwargs)

            aw.settingsLoad = _settings_load  # type: ignore[method-assign]
            qmc.redraw = _redraw  # type: ignore[method-assign]
            qmc.fig.canvas.mpl_connect('pick_event', self._on_pick)
            self._installed = True
        except Exception:  # pylint: disable=broad-except
            _log.exception('installing the Artisan display policy failed')

    def enforce(self) -> None:
        try:
            enforce(self._aw)
        except Exception:  # pylint: disable=broad-except
            _log.exception('imposing Artisan sampling and curve settings failed')

    def _on_pick(self, event: Any) -> None:
        try:
            aw = self._aw
            qmc = aw.qmc
            legend = qmc.legend
            if legend is None or getattr(aw, 'comparator', None):
                return
            artist = getattr(event, 'artist', None)
            if artist not in legend.get_texts() and artist not in getattr(qmc, 'legend_lines', []):
                return
            if any(line is not None and not line.get_visible() for line in (qmc.l_temp2, qmc.l_delta2)):
                # deferred past Artisan's own pick handler and its draw
                QTimer.singleShot(0, lambda: qmc.redraw_keep_view(recomputeAllDeltas=False))
        except Exception:  # pylint: disable=broad-except
            _log.exception('restoring the imposed curves after a legend click failed')
