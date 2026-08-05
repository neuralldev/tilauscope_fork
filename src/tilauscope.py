
"""Start the application.
"""

import os
import warnings
from typing import Any
import sys
import ctypes
import os
import io
from platform import system

if getattr(sys, 'frozen', False) and sys.stdout is None:
    sys.stdout = io.StringIO()
if getattr(sys, 'frozen', False) and sys.stderr is None:
    sys.stderr = io.StringIO()

if getattr(sys, 'frozen', False):
    # Change CWD to the user's Application Support so relative log paths work
    from PyQt6.QtCore import QStandardPaths
    target = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    os.makedirs(target, exist_ok=True)
    os.chdir(target)

warnings.simplefilter('ignore', DeprecationWarning)

# limit the number of numpy threads to 1 to limit the total number of threads taking into account a potential performance reduction on array operations using blas,
# which should not be significant
os.environ['OMP_NUM_THREADS'] = '1'

# deactivate defusedexml in OPENPYXL as it might not be installed or bundled
os.environ['OPENPYXL_DEFUSEDXML'] = 'False'

# highDPI support must be set before creating the Application instance
from PyQt6.QtWidgets import QApplication  # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtCore import Qt     # @Reimport # @UnusedImport @Reimport  @UnresolvedImport

if system().startswith('Windows'):
    try:
        ## TILAU ##
        mutex_name = "Global\\artisan_Mutex"
        kernel32 = ctypes.windll.kernel32
        artisan_mutex = kernel32.CreateMutexW(None,False,mutex_name)
        ############
        ib = (
            hasattr(sys, 'frozen') or # new py2exe
            hasattr(sys, 'importers') # old py2exe
        )
        from PyQt6.QtWidgets import QApplication  # @UnresolvedImport @Reimport @UnusedImport pylint: disable=import-error
        if ib:
            QApplication.addLibraryPath(os.path.join(os.path.dirname(os.path.realpath(sys.executable)), 'plugins'))
        else:
            import site # @Reimport @UnusedImport
            QApplication.addLibraryPath(site.getsitepackages()[1] + '\\PyQt6\\plugins')

    except Exception: # pylint: disable=broad-except
        pass
else:
    try:
        ib = getattr(sys, 'frozen', False)
        from PyQt6.QtWidgets import QApplication  # @UnresolvedImport @Reimport @UnusedImport pylint: disable=import-error
        if ib:
            QApplication.addLibraryPath(os.path.join(os.path.dirname(__file__), 'Resources/qt_plugins'))
        else:
            import site # @Reimport
            QApplication.addLibraryPath(os.path.dirname(site.getsitepackages()[0]) + '/PyQt6/qt_plugins')
    except Exception: # pylint: disable=broad-except
        pass

from artisanlib import main, command_utility

class NullWriter:
    softspace = 0
    encoding:str = 'UTF-8'

    @staticmethod
    def write(*args:Any) -> None:
        pass

    @staticmethod
    def flush(*args:Any) -> None:
        pass

    # Some packages are checking if stdout/stderr is available (e.g., youtube-dl). For details, see #1883.
    @staticmethod
    def isatty() -> bool:
        return False

if __name__ == '__main__':
     #Manage commands that does not need to start the whole application
    if command_utility.handleCommands():
        main.main()


# EOF
