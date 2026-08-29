import sys
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow
from PyQt6.QtCore import Qt, QTimer
app = QApplication(sys.argv)
app.lastWindowClosed.connect(lambda: print(">>> lastWindowClosed"))
app.aboutToQuit.connect(lambda: print(">>> aboutToQuit -> APP QUITS"))
aw = QMainWindow(); aw.show(); aw.hide()          # Artisan hidden
d = QDialog(aw); d.setModal(True)
d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
d.show()
QTimer.singleShot(50,  lambda: (print("close() ->", d.close())))
QTimer.singleShot(400, lambda: print("still alive"))
QTimer.singleShot(600, app.quit)
app.exec(); print("done")
