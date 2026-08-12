"""Responsive-width contracts for the anchored guided assistant."""

_APP = None


def _app():
    global _APP  # noqa: PLW0603 - Qt requires one process-wide strong reference
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    if not hasattr(_APP, 'artisanviewerMode'):
        _APP.artisanviewerMode = False
    return _APP


def test_setup_fields_contract_inside_guided_column() -> None:
    app = _app()
    from tilauscope.roast_asssistant import _BeanHeader, _QuickAdjustRow, _SetupBar

    setup = _SetupBar()
    setup.combo_bean.addItem(
        'Santa Lucila Rojo · Washed / Wet Process 2024 (empty stock)')
    setup.resize(370, setup.sizeHint().height())
    setup.layout().activate()

    assert setup.minimumSizeHint().width() <= 370
    assert setup.combo_bean.minimumWidth() == 0
    assert setup.combo_agtron.minimumWidth() == 0

    header = _BeanHeader()
    header.set_start_stop_visible(False)
    header._lbl_name.setText(  # pylint: disable=protected-access
        'Santa Lucila Rojo Washed Wet Process 2024 exceptionally long name')
    header.resize(370, header.sizeHint().height())
    header.layout().activate()

    assert header.minimumSizeHint().width() <= 370
    assert header._lbl_name.minimumWidth() == 0  # pylint: disable=protected-access

    quick = _QuickAdjustRow(object(), [
        ('Burner', 3, '#fff'), ('Air', 0, '#fff'),
        ('Drum', 1, '#fff'), ('Extraction', 2, '#fff'),
    ])
    quick.resize(350, quick.sizeHint().height())
    quick.layout().activate()
    assert quick.minimumSizeHint().width() <= 350
    app.processEvents()
