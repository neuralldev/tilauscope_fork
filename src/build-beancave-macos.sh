#!/usr/bin/env bash
## Build BeanCave alone (wiki/BeanCave-Standalone-Spec.md, lot 4): BeanCave.app and its DMG.
#
# From src/, with the virtual environment active:
#   ./build-beancave-macos.sh
# With CODESIGN_IDENTITY set (and the APPLE_API_* key for notarisation, see buildmac.sh)
# the DMG is signed, notarised and stapled by sign-notarize-macos.sh.
# Output: beancave-mac-<version>.dmg. Uses build/beancave-* so TilauScope's dist/ is left alone.

set -euo pipefail
cd "$(dirname "$0")"

DIST=build/beancave-dist
WORK=build/beancave-work
rm -rf "$DIST" "$WORK"

version=$(python3 -c "import artisanlib; print(artisanlib.__version__)")
DMG="beancave-mac-$version.dmg"

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    export TILAU_SKIP_DMG=1
    if [ -z "${APPLE_API_KEY_PATH:-}" ]; then
        export NOTARIZE=0
    fi
fi

pyinstaller --clean --noconfirm --distpath "$DIST" --workpath "$WORK" setup-beancave-mac.spec

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    VOLNAME=BeanCave ./sign-notarize-macos.sh "$DIST/BeanCave.app" "$DMG"
    rm -f "$DMG.notarized"
else
    echo "** unsigned build: CODESIGN_IDENTITY not set"
fi
echo "** $DMG"
