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
# TiLau 2025

import sys
import zipfile
import traceback
import platform
import logging
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                             QLabel, QTextEdit, QPushButton, QStyle, QFileDialog)
from PyQt6.QtCore import QStandardPaths, QUrl
from PyQt6.QtGui import QFont, QDesktopServices

class TilauCrashDialog(QDialog):

    mod_name_map = {
        "ai_support.py": "crash during AI request",
        "annotations.py": "crash of annotation manager",
        "artisanworker.py": "crash of beancave",
        "bean_extraction.py" : "crash during AI request",
        "beancave.py" : "crash of bean cave",
        "difluid.py" : "crash of difluid integration",
        "displayscope.py" : "crash of TilauScope",
        "label_printer.py" : "crash during label generation",
        "lebrewroastsee.py" : "crash of Lebrew device support", 
        "mqttbridge.py" : "crash of mqtt manager",
        "niimprint.py" : "crash of niimprint manager",
        "roast_assistant.py" : "crash of roast assistant",
        "roast_plan_model.py" : "crash of roast plan generator",
        "roast_timeline.py" : "crash in roast timeline", 
        "tilau_wheel.py": "crash in flavor wheel manager",
        "tilauambient.py": "crash in tilau probe manager", 
        "tilaulogger.py" : "crash in tilau logger manager",
        "tilaupid.py" : "crash of tilau PID",
        "visualalarm.py" : "crash of graphic alarm viewer",
        "other" : "crash of TilauScope"
    }

    def __init__(self, mod_name, line_no, error_val, tb_text, no_display:bool=False):
        super().__init__()
        module_name = self.mod_name_map.get(mod_name,self.mod_name_map["other"])
        self.setWindowTitle(QApplication.translate("tilauscope_beancave","TilauScope: {0}").format(module_name))
        self.setMinimumWidth(500)
        if no_display:
            export_logs_to_zip()
        else:
            self.setup_ui(mod_name, line_no, error_val, tb_text)

    def setup_ui(self, mod_name, line_no, error_val, tb_text):
        layout = QVBoxLayout(self)

        # Header with Icon
        header_layout = QHBoxLayout()
        icon_label = QLabel()
        critical_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
        icon_label.setPixmap(critical_icon.pixmap(48, 48))
        
        title_text = QApplication.translate("tilauscope_beancave", "<b><font size='5' color='#d32f2f'>TilauScope Interrupted</font></b><br>Something went wrong in <i>{0}</i>.").format(mod_name)
        header_label = QLabel(title_text)
        header_layout.addWidget(icon_label)
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Summary
        summary = QLabel(QApplication.translate("tilauscope_beancave","<b>Error:</b> {0}\n<b>Location:</b> Line {1}").format(error_val, line_no))
        layout.addWidget(summary)

        # Collapsible Traceback (Expert Mode)
        self.details_box = QTextEdit()
        self.details_box.setReadOnly(True)
        self.details_box.setPlainText(tb_text)
        self.details_box.setFont(QFont("Courier New", 10))
        self.details_box.hide()
        
        self.toggle_btn = QPushButton(QApplication.translate("tilauscope_beancave","Show Technical Details"))
        self.toggle_btn.clicked.connect(self.toggle_details)
        layout.addWidget(self.toggle_btn)
        layout.addWidget(self.details_box)

        # Instructions
        instr = QLabel(QApplication.translate("tilauscope_beancave","<br>Would you like to export a Debug Bundle (Logs + Environment) to help fix this?"))
        instr.setWordWrap(True)
        layout.addWidget(instr)

        # Buttons
        btn_layout = QHBoxLayout()
        self.export_btn = QPushButton(QApplication.translate("tilauscope_beancave","Export Logs & Close"))
        self.export_btn.setDefault(True)
        self.close_btn = QPushButton(QApplication.translate("tilauscope_beancave","Just Close"))
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addWidget(self.export_btn)
        layout.addLayout(btn_layout)

        # Connections
        self.export_btn.clicked.connect(self.accept)
        self.close_btn.clicked.connect(self.reject)

    def toggle_details(self):
        if self.details_box.isHidden():
            self.details_box.show()
            self.toggle_btn.setText(QApplication.translate("tilauscope_beancave","Hide Technical Details"))
            self.adjustSize()
        else:
            self.details_box.hide()
            self.toggle_btn.setText(QApplication.translate("tilauscope_beancave","Show Technical Details"))
            self.adjustSize()

def export_logs_to_zip():
    for handler in logging.root.handlers:
        artisan_filepath = Path(handler.baseFilename)
        break # use first only
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"Tilau_Debug_{platform.system()}_{timestamp}.zip"
    other_logs_directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "tilauscope"
    save_path, _ = QFileDialog.getSaveFileName(None, QApplication.translate("tilauscope_beancave","Save Debug Logs"), zip_filename, "Zip Files (*.zip)")
    
    if save_path:
        try:
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for path in other_logs_directory, artisan_filepath.parent:
                    if path.exists():
                        # Grab artisan and tilau logs
                        for log in list(path.glob("*.log*")) + list(path.glob("tilau_*.log")):
                            zipf.write(log, arcname=f"logs/{log.name}")
                
                # Add a system info file
                sys_info = f"OS: {platform.system()} {platform.release()}\nPython: {sys.version}\nQt: 6.11"
                zipf.writestr("system_info.txt", sys_info)
            return True
        except Exception as e:
            print(f"Failed to zip: {e}")
    return False

## TILAU ## Public issue tracker of the AGPL fork — where bug reports land.
TILAUSCOPE_ISSUES_URL = "https://github.com/neuralldev/tilauscope_fork/issues"

def report_a_bug(parent=None) -> bool:
    """Single entry point for "report a bug": export the diagnostics archive,
    then offer to open the public issue tracker.

    Called from the About dialog and from BeanCave's Export Logs button, so the
    two never drift apart. Cancelling the save dialog is silent (returns False).
    """
    from tilauscope.tilauscope_types import show_styled_message
    if not export_logs_to_zip():
        return False
    choice = show_styled_message(
        parent,
        QApplication.translate("tilauscope", "Diagnostics saved"),
        QApplication.translate("tilauscope",
            "Attach the archive to your report so the problem can be reproduced."),
        buttons=[QApplication.translate("tilauscope", "Open GitHub"),
                 QApplication.translate("tilauscope", "Done")])
    if choice == 0:
        QDesktopServices.openUrl(QUrl(TILAUSCOPE_ISSUES_URL))
    return True

def my_exception_hook(exctype, value, tb):
    tb_text = "".join(traceback.format_exception(exctype, value, tb))
    last_frame = traceback.extract_tb(tb)[-1]
    
    app = QApplication.instance() or QApplication(sys.argv)
    
    dialog = TilauCrashDialog(
        mod_name=Path(last_frame.filename).name,
        line_no=last_frame.lineno,
        error_val=value,
        tb_text=tb_text
    )

    if dialog.exec() == QDialog.DialogCode.Accepted:
        if export_logs_to_zip():
            from tilauscope.tilauscope_types import show_styled_message
            show_styled_message(None, QApplication.translate("tilauscope_beancave","Success"), QApplication.translate("tilauscope_beancave","Logs bundled. Please send this to the TilauScope team."))
    sys.exit(1)
