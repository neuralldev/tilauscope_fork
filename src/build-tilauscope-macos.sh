#!/bin/bash

echo $PATH

set -e  # reduced logging
python3 -V

PYTHONPATH="$VIRTUAL_ENV/lib/python3.14"
export PYTHON_V='3.14'
export QT_PATH=${PYTHONPATH}/site-packages/PyQt6/Qt6
export QT_SRC_PATH=~/Qt/6.2.3/macos
export PYLUPDATE=pylupdate6pro.py

echo "************* initializing... **************"
# remove useless .c file from Python site-packages from local build setups
rm -f ${PYTHONPATH}/site-packages/fontTools/misc/bezierTools.c # 1.9MB
# distribution
rm -rf build dist
## TILAU ## Marqueur de notarisation d'un build précédent : s'il survit et que le
## build courant n'en produit pas, on lirait un verdict périmé.
rm -f artisan-mac-*.dmg.notarized
sleep .3 # sometimes it takes a little for dist to get really empty

echo "************* updating build number **************"
python3 ../scripts/update-build-files.py

## TILAU ## Opt-in signing + notarization, mirroring .github/workflows/build-macos.yml.
## Set CODESIGN_IDENTITY ("Developer ID Application: Name (TEAMID)") to take the
## signed path: the spec then stops at dist/artisan.app (TILAU_SKIP_DMG=1) and
## sign-notarize-macos.sh signs, builds an APFS DMG, notarizes and staples it.
## Without CODESIGN_IDENTITY the build behaves exactly as before — the spec emits
## an unsigned HFS+ DMG, fine for a local test but not for distribution.
## Notarization needs APPLE_API_KEY_PATH / APPLE_API_KEY_ID / APPLE_API_ISSUER_ID;
## with an identity but no key the DMG is signed only (NOTARIZE=0).
SIGNED_BUILD=0
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    SIGNED_BUILD=1
    export TILAU_SKIP_DMG=1
    if [ -n "${APPLE_API_KEY_PATH:-}" ] && [ -n "${APPLE_API_KEY_ID:-}" ] && [ -n "${APPLE_API_ISSUER_ID:-}" ]; then
        export NOTARIZE="${NOTARIZE:-1}"
        echo "** signed build: sign + notarize (identity: $CODESIGN_IDENTITY)"
    else
        export NOTARIZE=0
        echo "** signed build: sign only — APPLE_API_KEY_PATH/_ID/APPLE_API_ISSUER_ID not all set, skipping notarization"
    fi
else
    echo "** unsigned build: CODESIGN_IDENTITY not set — the DMG will not be signed or notarized"
fi

#echo "************* run p2app **************"
#python3 setup-tilauscope-macos3.py py2app 2>&1 | egrep -v '^(creating|copying file|byte-compiling|locate|ADD INFO|changefunc)'
#if [ "${PIPESTATUS[0]}" -ne 0 ]; then 
#    echo "Failed in py2app"
#    exit 1
#else 
#    echo "** Finished py2app"
#fi

echo "************* run PyInstaller **************"
# Replace py2app with PyInstaller using your .spec file 

pyinstaller --clean setup-tilauscope-mac.spec
if [ $? -ne 0 ]; then 
    echo "Failed in PyInstaller"
    exit 1
else 
    echo "** Finished PyInstaller"
fi

version=$(python3 -c "import artisanlib; print(artisanlib.__version__)")

## TILAU ## Same DMG name in both paths — scripts/main.py uploads a hard-coded
## ./artisan-mac-<version>.dmg, so the signed path must not rename it.
## TILAU ## TILAU_NOTARIZED est lu par scripts/main.py pour décider si la release
## publique doit porter l'avertissement « signé mais non notarisé » (équivalent de
## la variable NOTARIZED du workflow). 0 par défaut : un build non signé déclenche
## forcément Gatekeeper.
TILAU_NOTARIZED=0
if [ "$SIGNED_BUILD" = "1" ]; then
    echo "************* signing / packaging / notarizing **************"
    chmod +x sign-notarize-macos.sh
    ./sign-notarize-macos.sh "dist/artisan.app" "artisan-mac-$version.dmg"

    ## TILAU ## sign-notarize-macos.sh dépose le verdict dans <dmg>.notarized.
    ## On le consomme ici puis on l'efface : c'est un fichier de travail, il n'a
    ## rien à faire dans src/ une fois le résultat récupéré.
    marker="artisan-mac-$version.dmg.notarized"
    TILAU_NOTARIZED=$(cat "$marker" 2>/dev/null || echo 0)
    rm -f "$marker"
fi
export TILAU_NOTARIZED
echo "** notarized=$TILAU_NOTARIZED"

# Check that the packaged files are above an expected size
basename="artisan-mac-$version"
echo "basename: $basename"
suffixes=".dmg" # array of suffixes to check
min_size=295000000  # minimum size in bytes (2.95 GB)
for suffix in $suffixes; do
    filename="$basename$suffix"
    size=$(($(du -k "$filename" | cut -f1) * 1024)) # returns kB so multiply by 1024 (du works on macOS)
    echo "$filename size: $size bytes"
    if [ "$size" -lt "$min_size" ]; then
        echo "$filename is smaller than minimum $min_size bytes"
        exit 1
    else
        echo "**** Success: $filename is larger than minimum $min_size bytes"
        python3 ../scripts/main.py # this is to adapt to your ci/cd env to upload on the cloud the dmg file
    fi
done