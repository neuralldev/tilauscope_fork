### -*- mode: python ; coding: utf-8 -*-
# ABOUT
# artisan-mac.spec script for Artisan macOS builds using pyinstaller
#
# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later versison. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.
#
# AUTHOR
# Dave Baxter, Marko Luther 2025

# Tilauscope pyinstaller specification file
# updated 2026/03/01

import logging
import sys
import os
import shutil
from pathlib import Path
import site
import PyQt6
import yoctopuce
import snap7
import Phidget22

from PyInstaller.utils.hooks import copy_metadata, collect_data_files, collect_dynamic_libs

# Set up the logger
logging.basicConfig(level=logging.INFO)

# function to copy single file
def copy_file(source_file, destination_file, fatal=True):
    try:
        shutil.copy2(source_file, destination_file)
    except Exception as exc:
        msg = f'Copy operation failed: {source_file} -> {destination_file}'
        logging.exception(msg)
        if fatal:
            sys.exit(msg)

# Function to perform xcopy
def xcopy_files(source_dir: str | Path, destination_dir: str | Path, wildchar : str = "*.*", fatal: bool = True):
    try:
        # copytree crée le dossier de destination lui-même
        # dirs_exist_ok=True permet de fusionner si le dossier existe déjà (Python 3.8+)
        shutil.copytree(source_dir, destination_dir, dirs_exist_ok=True, copy_function=shutil.copy2)        
    except Exception:
        msg = f'xcopy directory failed to {destination_dir}'
        logging.exception(msg)
        if fatal:
            sys.exit(msg)

# Function to make dir
def make_dir(path, fatal=True):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except Exception:
        msg = f'Create directory failed: {path}'
        logging.exception(msg)
        if fatal:
            sys.exit(msg)

def remove_dir(path, fatal=True):
    try:
        target = Path(path).resolve()
        # Garde-fou minimal
        if len(target.parts) <= 1:
            raise ValueError(f"Refusing to remove top-level directory: {target}")
        if target.exists():
            shutil.rmtree(target)
        else:
            logging.warning("Directory does not exist: %s", target)
    except Exception:
        msg = f'Remove directory failed: {path}'
        logging.exception(msg)
        if fatal:
            sys.exit(msg)

# Function to check if a file exists
def check_file_exists(file_path, fatal=True):
    if not os.path.isfile(file_path):
        msg = f'File does not exist: {file_path} '
        logging.error(msg)
        if fatal:
            sys.exit('Fatal Error')

# function to delete a
def del_file(path, fatal=True):
    try:
        target = Path(path)
        if target.exists():
            target.unlink()
        else:
            logging.warning("File does not exist: %s", target)
    except Exception:
        msg = f'Delete file failed: {path}'
        logging.exception(msg)
        if fatal:
            sys.exit(msg)

###################################
# Setup the environment
###################################
ROOTLOCAL = os.getenv('PARENT_DIR')
NAME = os.getenv('APP_NAME', 'artisan')

ROOT = Path(ROOTLOCAL).resolve()
SOURCE = ROOT / 'src'
PYTHON = ROOT / '.venv'
PYTHON_PACKAGES = Path(os.path.dirname(os.path.dirname(PyQt6.__file__)))
#PYTHON_PACKAGES = PYTHON / 'Lib' / 'site-packages'

TILAUSCOPE_SRC = str(SOURCE)
TARGETSTR = str(SOURCE / 'dist' / NAME) + '\\'
INCLUDES = TARGETSTR + 'includes\\'


PYQT_QT = PYTHON_PACKAGES / 'PyQt6' / 'Qt6'
PYQT_QT_BIN = str(PYQT_QT / 'bin')
#QT_TRANSL = PYQT_QT / 'translations'

YOCTO_BIN = Path(os.path.join(PYTHON_PACKAGES, 'yoctopuce', 'cdll'))
SNAP7_BIN = Path(os.path.join(PYTHON_PACKAGES, 'snap7', 'lib'))
PHIDGET22_BIN = Path(os.path.join(PYTHON_PACKAGES, 'Phidget22', '.libs'))
QT_TRANSL = Path(os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "translations"))


#YOCTO_BIN = PYTHON_PACKAGES / 'yoctopuce' / 'cdll'
#SNAP7_BIN = PYTHON_PACKAGES / 'snap7' / 'lib'
#PHIDGET22_BIN = PYTHON_PACKAGES / 'Phidget22' / '.libs'

logging.info(f"**Root: {ROOT}")
logging.info(f"**PYTHON_PACKAGES: {PYTHON_PACKAGES}")
logging.info("** QT_TRANSL: %s",QT_TRANSL)

from PyInstaller.utils.hooks import is_module_satisfies

scipy_dir = 'extra-dll' if not is_module_satisfies('scipy >= 1.3.2') else '.libs'
SCIPY_BIN = str(PYTHON_PACKAGES / 'scipy' / scipy_dir)


###################################
# Pyinstaller core
###################################
hiddenimports_list=['charset_normalizer.md__mypyc', 
                    'matplotlib.backends.backend_pdf',
                    'matplotlib.backends.backend_svg',
                    'matplotlib.backends.backend_qtagg',
                    'scipy.spatial.transform._rotation_groups',
                    'scipy.special.cython_special',
                    'scipy._lib.messagestream',
                    'scipy.special._cdflib',
                    'pywintypes',
                    'win32cred',
                    'win32timezone',
                    'babel.numbers',
                    'PyQt6.QtWebChannel',
                    'PyQt6.QtWebEngineCore',
                    'importlib_resources',
                    'winrt.windows.foundation.collections',
                    ## TILAU ## scipy >= 1.18 vendors array_api_compat under scipy._external (a namespace
                    ## TILAU ## package, so collect_submodules refuses it) and loads linalg/fft via
                    ## TILAU ## __import__(__package__ + ...), which PyInstaller cannot trace statically
                    'scipy._external.array_api_compat.numpy.linalg',
                    'scipy._external.array_api_compat.numpy.fft',
                    ## TILAU ## QR scan (webcam) — C extension + camera stack
                    'zxingcpp',
                    'PyQt6.QtMultimedia',
                    'PyQt6.QtMultimediaWidgets',
                    ## TILAU ## record web server — Bonjour registration (cython submodules)
                    'zeroconf',
                    'ifaddr',
                    ## TILAU ## src/proto (upstream generated protobuf stubs, imported by
                    ## TILAU ## artisanlib.ikawa and artisanlib.util). The name collides with the
                    ## TILAU ## installed proto-plus package, which also exposes a top-level
                    ## TILAU ## 'proto' — TILAUSCOPE_SRC on pathex must win. Listing the
                    ## TILAU ## submodules makes a wrong resolution show up in warn-*.txt.
                    'proto.IkawaCmd_pb2',
                    'proto.artisan_roast_pb2'
                    ]

datas = collect_data_files('bleak', subdir=r'backends\winrt')

binaries = collect_dynamic_libs('bleak')
block_cipher = None

logging.info(">>>>> Starting PyInstaller build")
a = Analysis(['artisan.py'],
             pathex=[PYQT_QT_BIN, TILAUSCOPE_SRC, SCIPY_BIN, PHIDGET22_BIN],
             binaries=binaries,
             datas=datas, # + copy_metadata('tzdata')
             hookspath=[],
             runtime_hooks=[r'pyinstaller_hooks\rthooks\pyi_rth_mplconfig.py'], # overwrites default MPL runtime hook which keeps loading font cache from (new) temp directory
             excludes=['pkg_resources', 'setuptools'], ## TILAU ## parity with macOS spec: keep pkg_resources/setuptools out of the frozen bundle (babel imports them optionally); avoids DeprecationWarning + startup scan
             hiddenimports=hiddenimports_list,
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             optimize=2,
             noarchive=True,
             cipher=block_cipher)
logging.info(">>>>> Analysis complete, building executable")
pyz = PYZ(a.pure, a.zipped_data,cipher=block_cipher)
logging.info(">>>>> PYZ complete, building EXE")
exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name=NAME,
          debug=False,
          strip=False, # =True fails
          upx=False, # not installed
          icon='artisan.ico',
          version='version_info-win.txt',
          console=False) # was True
logging.info(">>>>> EXE complete, collecting files")
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False, # =True fails
               upx=False, # not installed
               name=NAME)

###################################
# copy additional needed files
###################################
logging.info(">>>>> Copying additional needed files")

# requires the Microsoft Visual C++ 2015 Redistributable Package (x64), vc_redist.x64.exe, to be located above the source directory
copy_file(str(ROOT / 'vc_redist.x64.exe'), TARGETSTR)

copy_file(str(ROOT / 'README.MD'),TARGETSTR)
copy_file(str(ROOT / 'LICENSE'), TARGETSTR + r'\LICENSE.txt')

WHEELS = TARGETSTR + '\\Wheels'
make_dir(WHEELS)
xcopy_files(SOURCE / 'Wheels' / 'Cupping', TARGETSTR + 'Wheels\\Cupping')
xcopy_files(SOURCE / 'Wheels' / 'Other', TARGETSTR + 'Wheels\\Other')
xcopy_files(SOURCE / 'Wheels' / 'Roasting', TARGETSTR + 'Wheels\\Roasting')

xcopy_files(SOURCE / 'translations', TARGETSTR + 'translations', '*.qm')
xcopy_files(QT_TRANSL, TARGETSTR + 'translations', 'qtbase_*.qm')

make_dir(TARGETSTR + '_internal\\yoctopuce\\cdll')
copy_file(YOCTO_BIN / 'yapi64.dll', TARGETSTR + '_internal\\yoctopuce\\cdll')
copy_file(SNAP7_BIN / 'snap7.dll', TARGETSTR + '_internal')

make_dir(TARGETSTR + '_internal\\tilauscope')
copy_file(SOURCE / 'tilauscope' / 'beancave_beans.json', TARGETSTR + '_internal\\tilauscope')
copy_file(SOURCE / 'tilauscope' / 'roasters.json', TARGETSTR + '_internal\\tilauscope')
# Fonts loaded at runtime via QFontDatabase.addApplicationFont, resolved
# against os.path.dirname(__file__) → the 'tilauscope' package folder.
copy_file(SOURCE / 'tilauscope' / 'JetBrainsMono-Bold.ttf', TARGETSTR + '_internal\\tilauscope')
copy_file(SOURCE / 'tilauscope' / 'JetBrainsMono-Regular.ttf', TARGETSTR + '_internal\\tilauscope')
copy_file(SOURCE / 'tilauscope' / 'A101HLVB.TTF', TARGETSTR + '_internal\\tilauscope')
copy_file(SOURCE / 'tilauscope' / 'A101HLVN.TTF', TARGETSTR + '_internal\\tilauscope')

for fn in [
    'tilauscope.png',
    'artisan.png',
    'artisan.ico',
    'artisanAlarms.ico',
    'artisanProfile.ico',
    'artisanPalettes.ico',
    'artisanTheme.ico',
    'artisanSettings.ico',
    'artisanWheel.ico',
    r'includes\Humor-Sans.ttf',
    r'includes\dijkstra.ttf',
    r'includes\ComicNeue-Regular.ttf',
    r'includes\xkcd-script.ttf',
    r'includes\WenQuanYiZenHei-01.ttf',
    r'includes\WenQuanYiZenHeiMonoMedium.ttf',
    r'includes\SourceHanSansCN-Regular.otf',
    r'includes\SourceHanSansHK-Regular.otf',
    r'includes\SourceHanSansJP-Regular.otf',
    r'includes\SourceHanSansKR-Regular.otf',
    r'includes\SourceHanSansTW-Regular.otf',
    r'includes\alarmclock.eot',
    r'includes\alarmclock.svg',
    r'includes\alarmclock.ttf',
    r'includes\alarmclock.woff',
    r'includes\roboto-300.woff2',
    r'includes\roboto-600.woff2',
    r'includes\roboto-regular.woff2',
    r'includes\JetBrainsMono-Bold.ttf',
    r'includes\JetBrainsMono-OFL.txt',
    r'includes\JetBrainsMono-Regular.ttf',
    r'includes\artisan.tpl',
    r'includes\scale_widget.tpl',
    r'includes\fitty_patched.js',
    r'includes\bigtext.js',
    r'includes\sorttable.js',
    r'includes\report-template.htm',
    r'includes\roast-template.htm',
    r'includes\ranking-template.htm',
    r'includes\jquery-1.11.1.min.js',
    r'includes\android-chrome-192x192.png',
    r'includes\android-chrome-512x512.png',
    r'includes\apple-touch-icon.png',
    r'includes\browserconfig.xml',
    r'includes\favicon-16x16.png',
    r'includes\favicon-32x32.png',
    r'includes\favicon.ico',
    r'includes\mstile-150x150.png',
    r'includes\safari-pinned-tab.svg',
    r'includes\site.webmanifest',
    r'includes\A101HLVB.TTF',
    r'includes\A101HLVN.TTF',
    r'includes\logging.yaml',
    r'includes\artisan_public_key.pem',
    ]:
    copy_file(SOURCE / fn, TARGETSTR)

xcopy_files(SOURCE / 'includes' / 'Machines', INCLUDES + 'Machines')
xcopy_files(SOURCE / 'includes' / 'Themes', INCLUDES + 'Themes')
xcopy_files(SOURCE / 'includes' / 'Icons', INCLUDES + 'Icons')
xcopy_files(SOURCE / 'includes' / 'Icons',    TARGETSTR + 'Icons')
xcopy_files(SOURCE / 'includes' / 'Themes',   TARGETSTR + 'Themes')
###################################
# Remove unneeded files and folders
###################################
# remove unused translations of unused Qt modules
SUPPORTED_LANGUAGES = ['ar', 'bg', 'cs', 'da', 'de','el','en','es','fa','fi','fr','gd', 'he','hu','id','it','ja','ko','lv', 'nl','no','pl','pt_BR','pt','sk', 'sv','th','tr','uk','vi','zh_CN','zh_TW']

qt_trans_prefix_keep = {
    'qtbase',
    'qt'
}
qt_trans_file_keep = {
    'en-US.pak'
}
qt_trans_prefix_delete = {
    'qt_help'
}

logging.info(">>>>> Removing unneeded Qt translation files")
for root, _, files in os.walk(TARGETSTR +'_internal' + r'\PyQt6\Qt6\translations'):
    for file in files:
        if (any(file.startswith(f'{x}_') for x in qt_trans_prefix_delete) or
                not ( (any(file.startswith(f'{x}_') for x in qt_trans_prefix_keep) and any(file.endswith(f'_{x}.qm') for x in SUPPORTED_LANGUAGES)) or
                        any(file == f'{x}' for x in qt_trans_file_keep))):
            file_path = os.path.join(root, file)
            del_file(file_path, True)

logging.info(">>>>> Removing unneeded language support from babel")
for root, _, files in os.walk(TARGETSTR +'_internal' + r'\babel\locale-data'):
    for file in files:
        if (file.endswith('.dat') and
                file != 'root.dat' and not (file.startswith('zh') and file.endswith('.dat')) and
                (('_' not in file and file.split('.')[0] not in SUPPORTED_LANGUAGES) or
                    ('_' in file and file.split('.')[0] not in SUPPORTED_LANGUAGES))):
            file_path = os.path.join(root, file)
            del_file(file_path, True)
            #logging.info(file_path)

# remove unneeded files and folders from Windows (not implemented for legacy)
logging.info(">>>>> Removing unneeded files")
for fn in [
    ## TILAU ## Qt6Multimedia.dll is REQUIRED since the QR webcam scanner —
    ## do not re-add it to this deletion list (Qt6MultimediaQuick is QML-only,
    ## still safe to drop)
    r'_internal\PyQt6\Qt6\bin\Qt6MultimediaQuick.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6PdfQuick.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6PositioningQuick.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3D.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DAssetImport.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DAssetUtils.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DEffects.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DHelpers.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DHelpersImpl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DParticles.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DPhysics.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DPhysicsHelpers.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DRuntimeRender.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DSpatialAudio.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Quick3DUtils.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2Basic.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2BasicStyleImpl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2Fusion.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2FusionStyleImpl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2Imagine.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2ImagineStyleImpl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2Impl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2Material.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2MaterialStyleImpl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2Universal.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickControls2UniversalStyleImpl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickDialogs2.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickDialogs2QuickImpl.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickDialogs2Utils.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickLayouts.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickParticles.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickShapes.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickTemplates2.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickTest.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickTimeline.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6QuickTimelineBlendTrees.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6RemoteObjects.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6RemoteObjectsQml.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Sensors.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6SensorsQuick.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6SerialPort.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6ShaderTools.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6SpatialAudio.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6Test.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6TextToSpeech.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6WebChannelQuick.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6WebEngineQuick.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6WebEngineQuickDelegatesQml.dll',
    r'_internal\PyQt6\Qt6\bin\Qt6WebSockets.dll',
    r'_internal\PyQt6\Qt6\plugins\platforms\qminimal.dll',
    r'_internal\PyQt6\Qt6\plugins\platforms\qoffscreen.dll',
    r'_internal\PyQt6\Qt6\plugins\imageformats\qicns.dll',
    r'_internal\PyQt6\Qt6\plugins\imageformats\qtga.dll',
    r'_internal\PyQt6\Qt6\plugins\imageformats\qtiff.dll',
    r'_internal\PyQt6\Qt6\plugins\imageformats\qwebp.dll',
    ]:
    del_file(TARGETSTR + fn, True)

    # The api-ms-win*.dll files are generated on Appveyer CI and are not required
    for root, _, files in os.walk(TARGETSTR):
        for file in files:
            if (file.startswith('api-ms-win')):
                file_path = os.path.join(root, file)
                del_file(file_path, True)

logging.info(">>>>> Removing unneeded folders")
for dp in [
    r'_internal\PyQt6\Qt6\plugins\generic',
    r'_internal\PyQt6\Qt6\plugins\networkinformation',
    r'_internal\PyQt6\Qt6\plugins\position',
    r'_internal\PyQt6\Qt6\plugins\tls',
    r'_internal\PyQt6\Qt6\qml',
    r'_internal\matplotlib\mpl-data\sample_data',
    ]:
    remove_dir(TARGETSTR + dp, True)
logging.info(">>>>> END")

###################################