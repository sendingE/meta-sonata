#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/.build/macos-release"
APP_DIR="$PROJECT_DIR/dist/Meta Sonata.app"
VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$PROJECT_DIR/pyproject.toml" | head -n 1)"
if [[ -z "$VERSION" ]]; then
  echo "could not determine project version" >&2
  exit 1
fi
DMG_PATH="$PROJECT_DIR/dist/Meta-Sonata-$VERSION-macOS-arm64.dmg"
DMG_STAGING_DIR="$BUILD_DIR/dmg-root"
PACKAGE_DIR="$PROJECT_DIR/macos/MetaSonataMac"
VENV_DIR="$BUILD_DIR/python"
BACKEND_DIST="$BUILD_DIR/backend-dist"
SWIFT_BUILD="$BUILD_DIR/swift"
ICON_SOURCE="$PROJECT_DIR/src/meta_sonata/assets/MetaSonata.svg"
LOCALIZATION_SOURCE="$PROJECT_DIR/src/meta_sonata/assets/locales"
ICONSET="$BUILD_DIR/MetaSonata.iconset"
PINNED_SIGN_IDENTITY="Developer ID Application: MING YANG (P62F9L4PYC)"
PINNED_CERT_SHA256="CB6E93211E8D0615E156483A08D48F2551950245E1EC6121F60738E3CB43D052"
NOTARIZE="${MACOS_NOTARIZE:-0}"
NOTARY_PROFILE="${MACOS_NOTARY_PROFILE:-meta-sonata-notary}"

if [[ "$NOTARIZE" != "0" && "$NOTARIZE" != "1" ]]; then
  echo "MACOS_NOTARIZE must be 0 or 1" >&2
  exit 1
fi
if [[ "$NOTARIZE" == "1" ]]; then
  SIGN_IDENTITY="${MACOS_SIGN_IDENTITY:-$PINNED_SIGN_IDENTITY}"
else
  SIGN_IDENTITY="${MACOS_SIGN_IDENTITY:--}"
fi

verify_signing_certificate() {
  if [[ "$SIGN_IDENTITY" != "$PINNED_SIGN_IDENTITY" ]]; then
    echo "refusing to sign with an unpinned identity: $SIGN_IDENTITY" >&2
    exit 1
  fi

  local certificate_hash
  certificate_hash="$({
    security find-certificate -Z -c "$SIGN_IDENTITY" 2>/dev/null || true
  } | awk '/SHA-256 hash:/{print $3; exit}')"
  if [[ "$certificate_hash" != "$PINNED_CERT_SHA256" ]]; then
    echo "Developer ID certificate fingerprint mismatch" >&2
    echo "expected: $PINNED_CERT_SHA256" >&2
    echo "actual:   ${certificate_hash:-not found}" >&2
    exit 1
  fi

  if ! security find-identity -v -p codesigning | grep -Fq "\"$SIGN_IDENTITY\""; then
    echo "Developer ID certificate has no accessible private key" >&2
    exit 1
  fi
}

sign_macho_files() {
  local target="$1"
  local candidate
  while IFS= read -r -d '' candidate; do
    if file -b "$candidate" | grep -q '^Mach-O'; then
      codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$candidate"
    fi
  done < <(find "$target" -type f -print0)
}

sign_nested_bundles() {
  local target="$1"
  local bundle
  while IFS= read -r -d '' bundle; do
    codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$bundle"
  done < <(
    find "$target" -depth -type d \
      \( -name '*.framework' -o -name '*.bundle' -o -name '*.xpc' \) \
      -print0
  )
}

notarize_and_staple() {
  local submission="$1"
  local staple_target="$2"
  xcrun notarytool submit "$submission" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait
  xcrun stapler staple "$staple_target"
  xcrun stapler validate "$staple_target"
}

if [[ "$SIGN_IDENTITY" != "-" ]]; then
  verify_signing_certificate
fi
if [[ "$NOTARIZE" == "1" ]]; then
  xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null
fi

mkdir -p "$BUILD_DIR" "$PROJECT_DIR/dist"

if [[ ! -x "$VENV_DIR/bin/pyinstaller" ]]; then
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
  "$VENV_DIR/bin/python" -m pip install --quiet "pyinstaller>=6.11,<7" "$PROJECT_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --quiet --no-deps --force-reinstall "$PROJECT_DIR"

rm -rf "$BACKEND_DIST" "$BUILD_DIR/backend-work" "$BUILD_DIR/backend-spec"
mkdir -p "$BUILD_DIR/backend-spec"
MACOSX_DEPLOYMENT_TARGET=13.0 "$VENV_DIR/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --onedir \
  --name meta-sonata-mac \
  --collect-all opencc \
  --add-data "$PROJECT_DIR/src/meta_sonata/assets:meta_sonata/assets" \
  --paths "$PROJECT_DIR/src" \
  --distpath "$BACKEND_DIST" \
  --workpath "$BUILD_DIR/backend-work" \
  --specpath "$BUILD_DIR/backend-spec" \
  "$PACKAGE_DIR/backend_entry.py"

swift build \
  -c release \
  --package-path "$PACKAGE_DIR" \
  --scratch-path "$SWIFT_BUILD"
SWIFT_BIN_DIR="$(swift build -c release --package-path "$PACKAGE_DIR" --scratch-path "$SWIFT_BUILD" --show-bin-path)"

rm -rf "$ICONSET"
mkdir -p "$ICONSET"
rsvg-convert -w 1024 -h 1024 "$ICON_SOURCE" -o "$BUILD_DIR/icon-1024.png"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$BUILD_DIR/icon-1024.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$BUILD_DIR/icon-1024.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD_DIR/MetaSonata.icns"

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources/AppBackend"
cp "$SWIFT_BIN_DIR/MetaSonataMac" "$APP_DIR/Contents/MacOS/MetaSonataMac"
strip -S "$APP_DIR/Contents/MacOS/MetaSonataMac"
# Swift may embed a build-machine Xcode RPATH. System Swift and loader-relative
# paths are sufficient for the packaged app, so remove developer-only entries.
DEVELOPER_DIR="$(xcode-select -p)"
while IFS= read -r rpath; do
  case "$rpath" in
    "$DEVELOPER_DIR"/*)
      install_name_tool -delete_rpath "$rpath" "$APP_DIR/Contents/MacOS/MetaSonataMac"
      ;;
  esac
done < <(
  otool -l "$APP_DIR/Contents/MacOS/MetaSonataMac" |
    awk '/cmd LC_RPATH/{getline; getline; print $2}'
)
cp "$PACKAGE_DIR/Resources/Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$BUILD_DIR/MetaSonata.icns" "$APP_DIR/Contents/Resources/MetaSonata.icns"
cp -R "$LOCALIZATION_SOURCE" "$APP_DIR/Contents/Resources/Localizations"
cp -R "$BACKEND_DIST/meta-sonata-mac/." "$APP_DIR/Contents/Resources/AppBackend/"
# Wheel RECORD files are unnecessary at runtime and may retain local build paths.
find "$APP_DIR/Contents/Resources/AppBackend" -type f -path '*/*.dist-info/RECORD' -delete

if [[ "$SIGN_IDENTITY" == "-" ]]; then
  codesign --force --deep --sign - --timestamp=none "$APP_DIR"
else
  sign_macho_files "$APP_DIR"
  sign_nested_bundles "$APP_DIR"
  codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP_DIR"
fi
codesign --verify --deep --strict --verbose=2 "$APP_DIR"

"$APP_DIR/Contents/Resources/AppBackend/meta-sonata-mac" --help >/dev/null

if [[ "$NOTARIZE" == "1" ]]; then
  NOTARY_ZIP="$BUILD_DIR/Meta-Sonata-$VERSION-macOS-arm64.zip"
  rm -f "$NOTARY_ZIP"
  ditto -c -k --keepParent "$APP_DIR" "$NOTARY_ZIP"
  notarize_and_staple "$NOTARY_ZIP" "$APP_DIR"
  spctl --assess --type execute --verbose=4 "$APP_DIR"
fi

rm -rf "$DMG_STAGING_DIR"
mkdir -p "$DMG_STAGING_DIR"
cp -R "$APP_DIR" "$DMG_STAGING_DIR/"
ln -s /Applications "$DMG_STAGING_DIR/Applications"

rm -f "$DMG_PATH"
hdiutil create \
  -volname "Meta Sonata" \
  -srcfolder "$DMG_STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH" >/dev/null

if [[ "$SIGN_IDENTITY" != "-" ]]; then
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_PATH"
  codesign --verify --verbose=2 "$DMG_PATH"
fi

if [[ "$NOTARIZE" == "1" ]]; then
  notarize_and_staple "$DMG_PATH" "$DMG_PATH"
  spctl --assess --type open --context context:primary-signature --verbose=4 "$DMG_PATH"
fi

echo "$APP_DIR"
echo "$DMG_PATH"
