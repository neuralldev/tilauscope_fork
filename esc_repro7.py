import sys
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow
from PyQt6.QtCore import Qt, QTimer
app = QApplication(sys.argv)
class D(QDialog):
    def __init__(s,p):
        super().__init__(p); s.n=0
        s.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    def _close_dialog(s):
        s.n+=1; print("  _close_dialog #",s.n)
        if s.n>4: raise RecursionError
        s.accept()
    def closeEvent(s,e):
        print("  closeEvent -> _close_dialog"); s._close_dialog()
aw=QMainWindow(); aw.show()
d=D(aw); d.show()
def go():
    print("simulate X button click -> _close_dialog()"); d._close_dialog()
    print("  total calls:", d.n, "visible:", d.isVisible())
    print("simulate close() (e.g. window closed later):", d.close(), "calls:", d.n)
QTimer.singleShot(50, go); QTimer.singleShot(300, app.quit)
app.exec(); print("done")
