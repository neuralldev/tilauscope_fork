#### -*- mode: python ; coding: utf-8 -*-
import os
import shutil
import plistlib
import sys
import subprocess
from pathlib import Path
from PyInstaller.utils.hooks import get_package_paths, collect_all

# --- 1. Environment & Global Variables ---
SPECPATH = os.getcwd()
sys.path.insert(1, SPECPATH)
import artisanlib 

VERSION = artisanlib.__version__
BUILD = artisanlib.__build__
LICENSE = 'GPL-3.0-only'
PYTHON_V = os.environ.get("PYTHON_V", '43')
PYTHON_VERSION_STR = f'python{PYTHON_V}'
TARGET_ARCH = 'arm64'

# --- 2. Heavy Library Collection (Ensuring Size/Completeness) ---
# To match py2app's "packages" behavior, we explicitly collect everything 
# for complex libraries like babel, matplotlib, and numpy.
hidden_imports = [
    # already there
    'importlib.metadata',
    'babel.numbers',
    'yoctopuce',
    'pydantic',
    
    # add these based on the macOS log
    'charset_normalizer.md__mypyc',     # requests dependency
    'scipy.special.cython_special',
    'scipy.special._cdflib',
    'scipy._lib.messagestream',
    'scipy.spatial.transform._rotation_groups',
    ## TILAU ## scipy >= 1.18 
    'scipy._external.array_api_compat.numpy.linalg',
    'scipy._external.array_api_compat.numpy.fft',
    'importlib_resources',
    'PyQt6.QtWebChannel',
    'PyQt6.QtWebEngineCore',
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
    ## TILAU ## 'proto' — SPECPATH on pathex must win. Listing the submodules
    ## TILAU ## makes a wrong resolution show up in warn-*.txt.
    'proto.IkawaCmd_pb2',
    'proto.artisan_roast_pb2',
    ]
data_collection = []
binaries_collection = []

for pkg in ['babel', 'matplotlib', 'numpy', 'scipy']:
    tmp_datas, tmp_binaries, tmp_hidden = collect_all(pkg)
    data_collection.extend(tmp_datas)
    binaries_collection.extend(tmp_binaries)
    hidden_imports.extend(tmp_hidden)

# --- 3. Data Files & Binaries ---
DATA_FILES = [
    ('tilauscope.png', '.'),
    ('Assets.car', '.'),
    ('artisanProfile.icns', '.'),
    ('artisanAlarms.icns', '.'),
    ('artisanPalettes.icns', '.'),
    ('artisanSettings.icns', '.'),
    ('artisanTheme.icns', '.'),
    ('artisanWheel.icns', '.'),
    ('includes/*', 'includes/'),
    ('includes/Machines/*', 'includes/Machines/'),
    ('includes/Themes/*', 'includes/Themes/'),
    ('includes/Icons/*', 'includes/Icons/'),
    ('README.txt', '.'),
    ('tilauscope/beancave_beans.json', 'tilauscope'),
    ('tilauscope/roasters.json', 'tilauscope'),
    # Bundled fonts loaded at runtime via QFontDatabase.addApplicationFont
    # (resolved against os.path.dirname(__file__) → the 'tilauscope' folder).
    ('tilauscope/JetBrainsMono-Bold.ttf', 'tilauscope'),
    ('tilauscope/JetBrainsMono-Regular.ttf', 'tilauscope'),
    ('tilauscope/A101HLVB.TTF', 'tilauscope'),
    ('tilauscope/A101HLVN.TTF', 'tilauscope'),
]

# Add Translations [cite: 54]
for root, dirs, files in os.walk('translations'):
    for file in files:
        if file.endswith('.qm'):
            DATA_FILES.append((os.path.join(root, file), 'translations'))

BINARIES = []

# Snap7 [cite: 54]
snap7_path = os.path.join(get_package_paths('snap7')[1], 'lib/libsnap7.dylib')
if os.path.exists(snap7_path):
    BINARIES.append((snap7_path, 'snap7/lib'))

# Yoctopuce (.dylib collection) [cite: 54]
yocto_cdll = os.path.join(get_package_paths('yoctopuce')[1], 'cdll')
if os.path.exists(yocto_cdll):
    BINARIES.extend([(os.path.join(yocto_cdll, f), 'yoctopuce/cdll') 
                    for f in os.listdir(yocto_cdll) if f.endswith('.dylib')])

# Phidget22 [cite: 54]
phidget_path = os.path.join(get_package_paths('Phidget22')[1], '.libs/libphidget22.dylib')
if os.path.exists(phidget_path):
    BINARIES.append((phidget_path, 'Phidget22/.libs'))

def get_brew_libusb_path():
    try:
        # Demande à brew le préfixe d'installation de libusb[cite: 4]
        prefix = subprocess.check_output(['brew', '--prefix', 'libusb'], text=True).strip()
        lib_path = os.path.join(prefix, 'lib', 'libusb-1.0.dylib')
        if os.path.exists(lib_path):
            return lib_path
    except Exception:
        pass
    
    # Chemins par défaut si brew échoue[cite: 6]
    fallback_paths = [
        '/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib',  # Apple Silicon
        '/usr/local/opt/libusb/lib/libusb-1.0.dylib'     # Intel
    ]
    for p in fallback_paths:
        if os.path.exists(p):
            return p
    return None

LIBUSB_FILE = get_brew_libusb_path()

if LIBUSB_FILE:
    # On l'ajoute aux BINARIES pour qu'il soit copié dans Contents/Frameworks[cite: 6]
    BINARIES.append((LIBUSB_FILE, '.')) 
    print(f"** Succès : libusb trouvé à l'emplacement : {LIBUSB_FILE}")
else:
    print("** Attention : libusb n'a pas été trouvé. Le build risque d'échouer.")

# --- 3. Analysis ---
a = Analysis(
    ['tilauscope.py'],
    pathex=[SPECPATH],
    binaries=BINARIES,
    datas=DATA_FILES,
    hiddenimports=hidden_imports,   
    excludes=['pkg_resources', 'setuptools', 'tkinter', 'mypy', 'curses', 'matplotlib.tests', 'numpy.tests', 'scipy.tests', 'numpy.lib.tests', 'numpy.ma.tests', 'numpy.matrixlib.tests', 'numpy.polynomial.tests', 'numpy.random.tests', 'numpy.testing.tests', 'numpy.typing.tests', 'scipy._lib.tests','scipy.constants.tests','scipy.datasets.tests','scipy.fft.tests','scipy.fftpack.tests','scipy.integrate._ivp.tests','scipy.interpolate.tests','scipy.io._harwell_boeing.tests','scipy.io.arff.tests','scipy.io.matlab.tests','scipy.io.tests','scipy.linalg.tests','scipy.ndimage.tests','scipy.odr.tests','scipy.optimize.tests','scipy.signal.tests','scipy.sparse.linalg._isolve.tests','scipy.sparse.linalg.tests','scipy.sparse.tests','scipy.spatial.tests','scipy.spatial.transform.tests','scipy.special.tests','scipy.stats.tests'], # CRITICAL: Exclude pkg_resources
    hooksconfig={'matplotlib': {'backends': ['QtAgg', 'svg']}},
    runtime_hooks=['./pyinstaller_hooks/rthooks/pyi_rth_mplconfig.py'], # [cite: 55]
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    ## TILAU ## Names Contents/MacOS/<binary> — the process name in Activity
    ## Monitor and Force Quit. MUST stay in sync with CFBundleExecutable in
    ## Info.plist; if the two disagree the bundle will not launch at all.
    name='TilauScope',
    debug=False,
    bootloader_ignore_signals=False,
    ## TILAU ## strip=True corrupts the bootloader's Mach-O such that codesign
    ## --verify still passes but Apple's notary service rejects it with "The
    ## signature of the binary is invalid" on Contents/MacOS/TilauScope. Must stay
    ## False for notarization (COLLECT below is already strip=False).
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False, # Required for 3.14 [cite: 58]
    target_arch=TARGET_ARCH
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='tilauscope_build'
)

# --- 4. Info.plist ---
with open('Info.plist', 'rb') as f:
    plist = plistlib.load(f)

plist.update({
    'CFBundleDisplayName': 'TilauScope',
    'CFBundleShortVersionString': VERSION,
    ## TILAU ## CFBundleVersion is the build version, distinct from the marketing
    ## version above — includes __build__ so two builds of the same VERSION
    ## (e.g. "build 1" then "build 2" of 4.2.4, per ReleaseHistory.md) get
    ## different bundle versions instead of colliding.
    'CFBundleVersion': f'{VERSION}.{BUILD}',
    'NSHumanReadableCopyright': LICENSE,
    'LSMinimumSystemVersion': '14.0',
    'LSArchitecturePriority': ['arm64', 'x86_64'],
    'NSHighResolutionCapable': True,
    ## TILAU ## camera permission prompt for the BeanCave QR label scanner
    'NSCameraUsageDescription': 'TilauScope uses the camera to scan label QR codes and open the matching roast or bean record.',
    ## TILAU ## These two strings are the sentence macOS itself shows in the
    ## Bluetooth permission dialog. They read "artiisan wants to access
    ## bluetooth" upstream — typo included. Rewording them costs nothing: TCC
    ## keys its grants on CFBundleIdentifier, never on the usage description.
    'NSBluetoothAlwaysUsageDescription': 'TilauScope connects to your roaster, scale, smoke extractor and probes over Bluetooth.',
    'NSBluetoothPeripheralUsageDescription': 'TilauScope connects to your roaster, scale, smoke extractor and probes over Bluetooth.',
    ## TILAU ## The identifier macOS anchors every privacy grant to — Bluetooth
    ## for the roaster, scale, extractor and probes, and the camera for the QR
    ## scanner. Declared here rather than left to BUNDLE(bundle_identifier=...),
    ## which loses to this dict and silently did nothing.
    ##
    ## Under tilauscope.org, a domain this project owns. It was org.artisan —
    ## Artisan's own identifier, inherited by the fork, which left two different
    ## applications claiming one identity and let LaunchServices pick either of
    ## them to route notifications and roast links.
    ##
    ## Changing this string again revokes every privacy grant: TCC keys on it,
    ## its database is SIP-protected and tccutil can only reset, so no migration
    ## exists. Settings are unaffected — they key on organizationDomain instead.
    'CFBundleIdentifier': 'org.tilauscope.roasterscope',
})

app = BUNDLE(
    coll,
    name='TilauScope.app',
    ## TILAU ## Fork identity, not Artisan's. The GPL licenses the code, not the
    ## upstream name or logo (GPLv3 §7e reserves trademark rights), so a modified
    ## build must not present itself as Artisan in the Dock.
    ## Regenerate with tools/shell/gen_app_icons.py.
    icon='tilauscope.icns',
    ## TILAU ## No bundle_identifier= here on purpose: info_plist is merged after
    ## it and wins, so the argument was dead and advertised an identifier the
    ## build never used. CFBundleIdentifier lives in the plist dict above.
    info_plist=plist
)

# --- 5. Post-Build Cleanup & Pathing FIX ---
DIST_DIR = Path('dist').resolve()
APP_PATH = DIST_DIR / 'TilauScope.app'

print("************* Cleaning and Fixing Pathing **************")

# 1. EMULATE PY2APP RESOURCE STRUCTURE for Yoctopuce 
# Moves collected libs to Contents/Resources/lib/python3.14/...
res_lib_target = APP_PATH / f"Contents/Resources/lib/{PYTHON_VERSION_STR}/yoctopuce/cdll"
res_lib_target.mkdir(parents=True, exist_ok=True)

# PyInstaller places them in MacOS/_internal/yoctopuce/cdll initially
internal_yocto = DIST_DIR / 'tilauscope_build/_internal/yoctopuce/cdll'
if internal_yocto.exists():
    for lib in internal_yocto.glob('*.dylib'):
        shutil.copy2(lib, res_lib_target)
        print(f"Copied Yocto lib to Resources: {lib.name}")

# 2. FRAMEWORK CLEANUP (STRICT PROTECTION) 
# We must include 'Python.framework' or the app won't launch!
QT_KEEP = ['QtCore', 'QtGui', 'QtWidgets', 'QtSvg', 'QtNetwork', 
           'QtWebEngineCore', 'QtOpenGL', 'Python.framework', 'libusb'] 

fw_dir = APP_PATH / "Contents/Frameworks"
if fw_dir.exists():
    for fw in fw_dir.glob('*.framework'):
        if not any(k in fw.name for k in QT_KEEP):
            shutil.rmtree(fw, ignore_errors=True)
            print(f"Removed unused framework: {fw.name}")

# --- 6. DMG Creation (In Parent Directory)  ---
os.chdir(SPECPATH)
DMG_NAME = f'tilauscope-mac-{VERSION}.dmg'

# 1. REMOVE the intermediate build folder so it doesn't show up in the DMG
build_folder = DIST_DIR / 'tilauscope_build'
if build_folder.exists():
    print(f"*** Removing intermediate build folder: {build_folder} ***")
    shutil.rmtree(build_folder)

## TILAU ## The signed release pipeline must codesign TilauScope.app *before* the
## DMG is built — a DMG whose inner app is unsigned cannot be notarized. When
## TILAU_SKIP_DMG=1 the spec stops at dist/TilauScope.app and the caller
## (.github/workflows/build-macos.yml) signs, packages, notarizes and staples.
if os.environ.get('TILAU_SKIP_DMG') == '1':
    print("*** TILAU_SKIP_DMG=1 — leaving DMG creation to the caller ***")
else:
    # 2. Clean up existing DMG if it exists
    if os.path.exists(DMG_NAME):
        os.remove(DMG_NAME)

    # 3. Create /Applications symlink inside dist for DMG view
    # At this point, 'dist' only contains 'TilauScope.app'
    if os.path.exists('dist/Applications'):
        os.remove('dist/Applications')
    os.symlink('/Applications', 'dist/Applications')

    # 4. Generate DMG
    print(f"*** Generating DMG: {DMG_NAME} ***")
    # Now that tilauscope_build is gone, the DMG will only contain TilauScope.app and the shortcut
    os.system(f'hdiutil create "{DMG_NAME}" -volname "TilauScope" -fs HFS+ -srcfolder "dist"')

# Logging final size
def get_size(p):
    ## TILAU ## Skip symlinks: Qt frameworks alias every binary two or three
    ## times (Versions/Current, top-level shims), and following those symlinks
    ## counted each target repeatedly — the old figure was ~2.4x the truth
    ## (reported 1751 MB for a 720 MB app). Count each real file once, like du.
    total = 0
    for f in Path(p).rglob('*'):
        if f.is_symlink() or not f.is_file():
            continue
        total += f.stat().st_size
    return total

print(f">>>>> Final App Size (on disk): {get_size(APP_PATH) / (1024 * 1024):.2f} MB")

DMG_FILE = Path(SPECPATH) / DMG_NAME
if DMG_FILE.exists():
    print(f">>>>> DMG (compressed download): {DMG_FILE.stat().st_size / (1024 * 1024):.2f} MB")
