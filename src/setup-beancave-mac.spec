# -*- mode: python ; coding: utf-8 -*-
# BeanCave alone, beside the operator's own Artisan (wiki/BeanCave-Standalone-Spec.md, lot 4).
#
#     pyinstaller --clean setup-beancave-mac.spec      (from src/)
#
# Leaves dist/BeanCave.app; with TILAU_SKIP_DMG unset it also builds beancave-mac-<version>.dmg.
# Signing and notarisation reuse sign-notarize-macos.sh on dist/BeanCave.app.
import os
import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

SPECPATH = os.getcwd()
sys.path.insert(1, SPECPATH)
import artisanlib

VERSION = artisanlib.__version__
BUILD = artisanlib.__build__

hidden_imports = [
    'importlib.metadata',
    'babel.numbers',
    # QR scan of sack labels (webcam).
    'zxingcpp',
    'PyQt6.QtMultimedia',
    'PyQt6.QtMultimediaWidgets',
    # src/proto shadows the proto-plus package (see setup-tilauscope-mac.spec).
    'proto.IkawaCmd_pb2',
    'proto.artisan_roast_pb2',
]
data_collection = []
binaries_collection = []
for pkg in ['babel', 'matplotlib', 'numpy', 'scipy']:
    datas, binaries, hidden = collect_all(pkg)
    data_collection.extend(datas)
    binaries_collection.extend(binaries)
    hidden_imports.extend(hidden)

DATA_FILES = [
    ('includes/*', 'includes/'),
    ('includes/Machines/*', 'includes/Machines/'),
    ('includes/Themes/*', 'includes/Themes/'),
    ('includes/Icons/*', 'includes/Icons/'),
    ('tilaucore/data/beancave_beans.json', 'tilaucore/data'),
    ('tilaucore/data/roasters.json', 'tilaucore/data'),
    ('tilauscope/JetBrainsMono-Bold.ttf', 'tilauscope'),
    ('tilauscope/JetBrainsMono-Regular.ttf', 'tilauscope'),
]
DATA_FILES += [(str(qm), 'translations') for qm in Path('translations').glob('*.qm')]

a = Analysis(
    ['beancave.py'],
    pathex=[SPECPATH],
    binaries=binaries_collection,
    datas=DATA_FILES + data_collection,
    hiddenimports=hidden_imports,
    # artisanlib.main renames the application and writes Artisan's settings: BeanCave must never carry it.
    excludes=['artisanlib.main', 'pkg_resources', 'setuptools', 'tkinter', 'mypy', 'curses',
              'matplotlib.tests', 'numpy.tests', 'scipy.tests'],
    hooksconfig={'matplotlib': {'backends': ['QtAgg', 'svg']}},
    runtime_hooks=['./pyinstaller_hooks/rthooks/pyi_rth_mplconfig.py'],
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BeanCave',  # must match CFBundleExecutable
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # strip breaks notarisation (see setup-tilauscope-mac.spec)
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch='arm64',
)

coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='beancave_build')

APPLE_LOCALE = {'zh_CN': 'zh-Hans', 'zh_TW': 'zh-Hant', 'pt_BR': 'pt-BR', 'no': 'nb'}
BUNDLE_LOCALIZATIONS = sorted({
    APPLE_LOCALE.get(code, code)
    for code in (f.stem.split('artisan_', 1)[1]
                 for f in Path('translations').glob('artisan_*.qm')
                 if f.stat().st_size > 1024)
} | {'en'})

# No CFBundleDocumentTypes: .alog files stay Artisan's.
app = BUNDLE(
    coll,
    name='BeanCave.app',
    icon='beancave.icns',
    info_plist={
        'CFBundleName': 'BeanCave',
        'CFBundleDisplayName': 'BeanCave',
        'CFBundleExecutable': 'BeanCave',
        'CFBundleIdentifier': 'org.tilauscope.beancave',
        'CFBundleDevelopmentRegion': 'en',
        'CFBundleLocalizations': BUNDLE_LOCALIZATIONS,
        'CFBundleAllowMixedLocalizations': True,
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': f'{VERSION}.{BUILD}',
        'NSHumanReadableCopyright': 'AGPL-3.0-or-later',
        'LSMinimumSystemVersion': '14.0',
        'NSHighResolutionCapable': True,
        'NSCameraUsageDescription': 'BeanCave uses the camera to scan sack label QR codes.',
        'NSBluetoothAlwaysUsageDescription': 'BeanCave connects to your scale and water activity probe over Bluetooth.',
        'NSBluetoothPeripheralUsageDescription': 'BeanCave connects to your scale and water activity probe over Bluetooth.',
    },
)

DIST_DIR = Path(DISTPATH).resolve()  # --distpath, dist/ by default
APP_PATH = DIST_DIR / 'BeanCave.app'

# Qt frameworks BeanCave never loads.
QT_KEEP = ['QtCore', 'QtGui', 'QtWidgets', 'QtSvg', 'QtNetwork', 'QtMultimedia', 'QtOpenGL',
           'QtPrintSupport', 'Python.framework']
for fw in (APP_PATH / 'Contents/Frameworks').glob('*.framework'):
    if not any(k in fw.name for k in QT_KEEP):
        shutil.rmtree(fw, ignore_errors=True)

build_folder = DIST_DIR / 'beancave_build'
if build_folder.exists():
    shutil.rmtree(build_folder)

if os.environ.get('TILAU_SKIP_DMG') != '1':
    os.chdir(SPECPATH)
    dmg = f'beancave-mac-{VERSION}.dmg'
    staging = DIST_DIR.parent / 'beancave-dmg'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(APP_PATH, staging / 'BeanCave.app', symlinks=True)
    os.symlink('/Applications', staging / 'Applications')
    if os.path.exists(dmg):
        os.remove(dmg)
    os.system(f'hdiutil create "{dmg}" -volname "BeanCave" -fs APFS -srcfolder "{staging}"')
