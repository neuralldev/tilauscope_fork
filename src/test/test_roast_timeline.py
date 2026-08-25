from __future__ import annotations


def test_planning_card_closes_after_leaving_bar_but_stays_clickable(
        qapp, monkeypatch) -> None:
    """Leaving a bar must not leave its card stuck over the planning.

    The brief grace period lets the pointer cross the gap to the card CTA; entering
    the card cancels dismissal, while leaving the card restarts it.
    """
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtTest import QTest

    from tilauscope.roast_timeline import RoastReadyDialog

    qapp.processEvents()
    monkeypatch.setattr(RoastReadyDialog, "_start_scan", lambda _self: None)
    monkeypatch.setattr(RoastReadyDialog, "_center_on_screen", lambda _self: None)

    dialog = RoastReadyDialog("", {})
    dialog._build_scene()
    assert dialog._tooltip_proxy is not None

    dialog._tooltip_proxy.show()
    dialog._tooltip_proxy.setPos(10_000, 10_000)
    dialog._hover_key = "roast.alog"

    # A mouse move onto empty planning space is what follows leaving a bar.
    empty_scene_pos = QPointF(22, 80)  # between the 44 px day-grid lines
    assert dialog._scene.itemAt(empty_scene_pos, dialog._view.transform()) is None
    viewport_pos = dialog._view.mapFromScene(empty_scene_pos)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(viewport_pos),
        QPointF(dialog._view.viewport().mapToGlobal(viewport_pos)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    dialog.eventFilter(dialog._view.viewport(), event)
    assert dialog._tooltip_hide_timer.isActive()

    dialog._tooltip_widget.pointer_entered.emit()
    assert not dialog._tooltip_hide_timer.isActive()
    assert dialog._tooltip_proxy.isVisible()

    dialog._tooltip_widget.pointer_left.emit()
    assert dialog._tooltip_hide_timer.isActive()
    QTest.qWait(dialog._tooltip_hide_timer.interval() + 50)

    assert not dialog._tooltip_proxy.isVisible()
    assert dialog._hover_key is None
    dialog.close()
