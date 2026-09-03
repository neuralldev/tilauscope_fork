from PyQt6.QtCore import QEvent

def test_zz_hover_preserves_widget_sheet(qapp):
    from tilauscope.cave.widgets import SmoothHoverFilter, TilauSpinBox

    sb = TilauSpinBox()
    base = sb.styleSheet()
    assert 'padding-right' in base and 'up-arrow' in base, 'fixture wrong'

    f = SmoothHoverFilter()
    f.install(sb)

    # drive one full hover-in animation to completion
    f.animate(sb, f.base_border, f.accent_border)
    import time
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.45:   # animation lasts 250 ms
        qapp.processEvents()

    after = sb.styleSheet()
    print("\n[CHECK] padding-right kept :", 'padding-right' in after)
    print("[CHECK] ::up-arrow kept    :", 'up-arrow' in after)
    print("[CHECK] :focus rule kept   :", ':focus' in after)
    print("[CHECK] font-size kept     :", 'font-size' in after)
    print("[CHECK] animated border    :", 'border: 2px solid rgb' in after)

    assert 'padding-right' in after
    assert 'up-arrow' in after
    assert ':focus' in after
    assert 'border: 2px solid rgb' in after

    # eventFilter must not swallow the event any more
    ev = QEvent(QEvent.Type.HoverEnter)
    swallowed = f.eventFilter(sb, ev)
    print("[CHECK] event swallowed    :", swallowed)
    assert swallowed is False
