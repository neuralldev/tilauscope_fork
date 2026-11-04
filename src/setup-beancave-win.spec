# -*- mode: python ; coding: utf-8 -*-
# BeanCave alone, beside the operator's own Artisan (wiki/BeanCave-Standalone-Spec.md, lot 4).
#
#     set PARENT_DIR=%CD%  &&  cd src  &&  pyinstaller --noconfirm setup-beancave-win.spec
#
# Leaves dist\BeanCave\, packed by setup-beancave.nsi. Layout follows setup-tilauscope-win.spec:
# getResourcePath() is the .exe folder once frozen, translations sit in its translations\ folder.
import os
import shutil
from pathlib import Path

import PyQt6
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(os.environ['PARENT_DIR']).resolve()
SOURCE = ROOT / 'src'
TARGET = SOURCE / 'dist' / 'BeanCave'
QT_TRANSL = Path(PyQt6.__file__).parent / 'Qt6' / 'translations'

hiddenimports = [
    'charset_normalizer.md__mypyc',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_svg',
    'scipy.special.cython_special',
    'scipy.special._cdflib',
    'scipy._lib.messagestream',
    'scipy.spatial.transform._rotation_groups',
    'scipy._external.array_api_compat.numpy.linalg',
    'scipy._external.array_api_compat.numpy.fft',
    'pywintypes',
    'win32cred',
    'win32timezone',
    'babel.numbers',
    'winrt.windows.foundation.collections',
    # QR scan of sack labels (webcam).
    'zxingcpp',
    'PyQt6.QtMultimedia',
    'PyQt6.QtMultimediaWidgets',
    # src/proto shadows the proto-plus package (see setup-tilauscope-mac.spec).
    'proto.IkawaCmd_pb2',
    'proto.artisan_roast_pb2',
]

a = Analysis(
    ['beancave.py'],
    pathex=[str(SOURCE)],
    binaries=collect_dynamic_libs('bleak'),
    datas=collect_data_files('bleak', subdir=r'backends\winrt'),
    hiddenimports=hiddenimports,
    runtime_hooks=[r'pyinstaller_hooks\rthooks\pyi_rth_mplconfig.py'],
    # artisanlib.main renames the application and writes Artisan's settings: BeanCave must never carry it.
    excludes=['artisanlib.main', 'pkg_resources', 'setuptools', 'tkinter'],
    optimize=2,
    noarchive=True,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, exclude_binaries=True, name='BeanCave', debug=False, strip=False, upx=False,
          icon='beancave.ico', version='version_info-beancave-win.txt', console=False)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='BeanCave')


def copy_tree(source: Path, target: Path, pattern: str = '*') -> None:
    target.mkdir(parents=True, exist_ok=True)
    for f in source.glob(pattern):
        if f.is_dir():
            shutil.copytree(f, target / f.name, dirs_exist_ok=True)
        else:
            shutil.copy2(f, target)


shutil.copy2(ROOT / 'vc_redist.x64.exe', TARGET)
shutil.copy2(ROOT / 'LICENSE', TARGET / 'LICENSE.txt')
shutil.copy2(SOURCE / 'beancave.ico', TARGET)
copy_tree(SOURCE / 'translations', TARGET / 'translations', '*.qm')
copy_tree(QT_TRANSL, TARGET / 'translations', 'qtbase_*.qm')
for folder in ('Icons', 'Themes', 'Machines'):
    copy_tree(SOURCE / 'includes' / folder, TARGET / folder)
for data in ('tilaucore/data/beancave_beans.json', 'tilaucore/data/roasters.json',
             'tilauscope/JetBrainsMono-Bold.ttf', 'tilauscope/JetBrainsMono-Regular.ttf'):
    destination = TARGET / '_internal' / Path(data).parent
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / data, destination)
for folder in (r'_internal\PyQt6\Qt6\qml', r'_internal\matplotlib\mpl-data\sample_data'):
    shutil.rmtree(TARGET / folder, ignore_errors=True)
