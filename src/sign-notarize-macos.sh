#!/usr/bin/env bash
## TILAU ## Sign, package, notarize and staple the macOS build.
#
# Usage:
#   CODESIGN_IDENTITY="Developer ID Application: Name (TEAMID)" \
#   APPLE_API_KEY_PATH=/path/to/AuthKey_XXXX.p8 \
#   APPLE_API_KEY_ID=XXXXXXXXXX \
#   APPLE_API_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
#   ./sign-notarize-macos.sh dist/TilauScope.app tilauscope-4.1.0-build27.dmg
#
# Set NOTARIZE=0 to sign and package only (useful for a quick local check).
# Set NOTARIZE_REQUIRED=0 to keep going (exit 0) if notarization fails, so the
# signed-but-unstapled DMG still ships; default 1 makes a failure fatal.

set -euo pipefail

APP_PATH="${1:?usage: sign-notarize-macos.sh <app-path> <dmg-path>}"
DMG_PATH="${2:?usage: sign-notarize-macos.sh <app-path> <dmg-path>}"
NOTARIZE="${NOTARIZE:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTITLEMENTS="$SCRIPT_DIR/artisan.entitlements"
CHILD_ENTITLEMENTS="$SCRIPT_DIR/Child.entitlements"

: "${CODESIGN_IDENTITY:?CODESIGN_IDENTITY is not set}"

sign() { codesign --force --timestamp --options runtime --sign "$CODESIGN_IDENTITY" "$@"; }

echo "=== Signing $APP_PATH with: $CODESIGN_IDENTITY"

# Codesign seals a bundle's contents into its own signature, so anything nested
# must be signed before its container: loose Mach-O objects, then helper .app
# bundles (QtWebEngineProcess), then frameworks, then the app itself. Deepest
# paths first within each pass — `sort -r` puts a/b/c before a/b.
echo "--- 1/4 dylibs and Python extension modules"
find "$APP_PATH" -type f \( -name '*.dylib' -o -name '*.so' \) | sort -r | while read -r f; do
  sign "$f"
done

# QtWebEngineProcess inherits the parent's entitlements rather than declaring
# its own — that is what Child.entitlements is for.
echo "--- 2/4 nested helper apps"
find "$APP_PATH" -mindepth 1 -name '*.app' -type d | sort -r | while read -r helper; do
  echo "    $helper"
  sign --entitlements "$CHILD_ENTITLEMENTS" "$helper"
done

echo "--- 3/4 frameworks"
find "$APP_PATH" -name '*.framework' -type d | sort -r | while read -r fw; do
  echo "    $fw"
  sign "$fw"
done

echo "--- 4/4 app bundle"
sign --entitlements "$ENTITLEMENTS" "$APP_PATH"

echo "=== Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "=== Building DMG: $DMG_PATH"
DIST_DIR="$(dirname "$APP_PATH")"
rm -f "$DMG_PATH"
rm -f "$DIST_DIR/Applications"
ln -s /Applications "$DIST_DIR/Applications"
# APFS, not HFS+: HFS+ renormalizes filenames to Unicode NFD, which rewrites
# the "Bühler" machine-profile folder (ü → u + combining diaeresis). That
# breaks the app's sealed-resource signature inside the image, and the notary
# service reports it — confusingly — as "the signature of the binary is
# invalid" on Contents/MacOS/TilauScope. APFS preserves the bytes as signed.
## TILAU ## VOLNAME lets a second product (the Translator) reuse this script
## without mounting a volume that claims to be TilauScope. Default unchanged.
hdiutil create "$DMG_PATH" -volname "${VOLNAME:-TilauScope}" -fs APFS -srcfolder "$DIST_DIR" -ov

echo "=== Signing DMG"
codesign --force --timestamp --sign "$CODESIGN_IDENTITY" "$DMG_PATH"

if [ "$NOTARIZE" != "1" ]; then
  echo "=== NOTARIZE=0 — stopping after signing"
  exit 0
fi

: "${APPLE_API_KEY_PATH:?APPLE_API_KEY_PATH is not set}"
## TILAU ## The variable being set says nothing about the file existing; a
## mistyped path used to surface only as a notarytool failure further down.
[ -f "$APPLE_API_KEY_PATH" ] || {
  echo "error: no App Store Connect key at $APPLE_API_KEY_PATH" >&2
  exit 1
}
: "${APPLE_API_KEY_ID:?APPLE_API_KEY_ID is not set}"
: "${APPLE_API_ISSUER_ID:?APPLE_API_ISSUER_ID is not set}"

# The DMG is signed and shippable at this point. NOTARIZE_REQUIRED controls
# what happens if Apple's notary service rejects it, times out, or is down:
#   1 (default) — fatal: exit non-zero, nothing ships. Right for local runs.
#   0           — best-effort: warn and exit 0 so the signed-but-unstapled DMG
#                 still ships. Users then clear quarantine by hand (see below).
# A marker file "<dmg>.notarized" (1/0) is written for the caller to read.
NOTARIZE_REQUIRED="${NOTARIZE_REQUIRED:-1}"
MARKER="${DMG_PATH}.notarized"

ship_unnotarized() {
  echo "0" > "$MARKER"
  echo "!!! Shipping a signed but NOT notarized DMG (NOTARIZE_REQUIRED=0)."
  echo "!!! On first launch macOS will block it. To authorize after install:"
  echo "!!!     xattr -dr com.apple.quarantine /Applications/TilauScope.app"
  echo "!!! (or right-click the app → Open, then confirm in the dialog)."
}

echo "=== Submitting to Apple notary service (this takes a few minutes)"
SUBMIT_JSON="$(mktemp)"
# --wait can hit its own timeout while Apple is still processing; don't let that
# abort the script under `set -e` — inspect the JSON verdict instead.
xcrun notarytool submit "$DMG_PATH" \
  --key "$APPLE_API_KEY_PATH" \
  --key-id "$APPLE_API_KEY_ID" \
  --issuer "$APPLE_API_ISSUER_ID" \
  --wait --timeout 45m \
  --output-format json | tee "$SUBMIT_JSON" || true

# `notarytool submit --wait` exits 0 as long as Apple returned a verdict, even
# when that verdict is Invalid — the status has to be inspected explicitly. On a
# client-side timeout the JSON carries no "status" key, so default to Unknown.
STATUS=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('status','Unknown'))" "$SUBMIT_JSON" 2>/dev/null || echo Unknown)
SUBMISSION_ID=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('id',''))" "$SUBMIT_JSON" 2>/dev/null || echo "")

if [ "$STATUS" != "Accepted" ]; then
  echo "!!! Notarization did not succeed (status: $STATUS)."
  if [ -n "$SUBMISSION_ID" ]; then
    echo "--- Apple notary log for submission $SUBMISSION_ID:"
    xcrun notarytool log "$SUBMISSION_ID" \
      --key "$APPLE_API_KEY_PATH" \
      --key-id "$APPLE_API_KEY_ID" \
      --issuer "$APPLE_API_ISSUER_ID" || true
  fi
  if [ "$NOTARIZE_REQUIRED" = "1" ]; then
    echo "!!! NOTARIZE_REQUIRED=1 — treating this as fatal."
    exit 1
  fi
  ship_unnotarized
  exit 0
fi

echo "=== Stapling the notarization ticket"
xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"

echo "=== Gatekeeper assessment"
spctl --assess --type open --context context:primary-signature -vv "$DMG_PATH"

echo "1" > "$MARKER"
echo "=== Done: $DMG_PATH is signed, notarized and stapled"
