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
SIGN_IDENTITY="${MACOS_SIGN_IDENTITY:--}"

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
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP_DIR"
fi
codesign --verify --deep --strict --verbose=2 "$APP_DIR"

"$APP_DIR/Contents/Resources/AppBackend/meta-sonata-mac" --help >/dev/null

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

echo "$APP_DIR"
echo "$DMG_PATH"
