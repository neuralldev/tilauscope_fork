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

"""Temperature-unit boundaries of the post-roast review panel."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


def test_peak_ror_is_normalized_from_the_live_fahrenheit_mode(qapp: Any) -> None:  # noqa: ARG001
    from tilauscope.roast_review_panel import RoastReviewPanel

    qmc = SimpleNamespace(
        mode='F',
        timex=[0.0, 1.0, 2.0],
        temp2=[350.0, 351.0, 352.0],
        stemp2=[],
        timeindex=[0, 0, 0, 0, 0, 0, 2, 0],
        TPalarmtimeindex=0,
        optimalSmoothing=True,
        recomputeDeltas=lambda *_args, **_kwargs: ([], [None, 18.0, 36.0]),
    )
    panel = SimpleNamespace(aw=SimpleNamespace(qmc=qmc))

    peak_c = RoastReviewPanel._peak_ror(panel)

    assert peak_c == pytest.approx(20.0)


def test_the_reviewed_snapshot_is_handed_out_as_a_copy(qapp: Any) -> None:  # noqa: ARG001
    """The page's record of what it drew must not be editable from outside.

    The caller that opens the weight form edits a roast; if it held the panel's
    own dict, that edit would silently rewrite what the review claims to show.
    """
    from tilauscope.roast_review_panel import RoastReviewPanel

    panel = SimpleNamespace(_profile=None)
    assert RoastReviewPanel.reviewed_profile(panel) is None

    panel._profile = {'beans': 'Ethiopia Guji'}
    handed = RoastReviewPanel.reviewed_profile(panel)
    assert handed == {'beans': 'Ethiopia Guji'}
    handed['beans'] = 'something else'
    assert panel._profile == {'beans': 'Ethiopia Guji'}


def test_a_refresh_that_fails_leaves_no_previous_roast_behind(
        qapp: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ARG001
    """A page that could not be read describes no roast — not the last one.

    The snapshot decides which coffee an edit from the review belongs to. Left
    standing after a failed rebuild, it would point the next edit at the roast
    the operator is no longer looking at.
    """
    from tilauscope import roast_review_panel as mod

    aw = SimpleNamespace(qmc=SimpleNamespace(mode='C', tilau_roast_plan_snapshot=None))
    panel = mod.RoastReviewPanel(aw)

    monkeypatch.setattr(mod, 'profile_from_qmc', lambda _aw: {'beans': 'first roast'})
    monkeypatch.setattr(mod, 'build_debrief', lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(mod.RoastReviewPanel, '_build', lambda *_a, **_k: None)
    panel.refresh()
    assert panel.reviewed_profile() == {'beans': 'first roast'}

    def _unreadable(_aw: Any) -> dict[str, Any]:
        raise ValueError('malformed profile')

    monkeypatch.setattr(mod, 'profile_from_qmc', _unreadable)
    panel.refresh()
    assert panel.reviewed_profile() is None
