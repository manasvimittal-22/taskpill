#!/bin/sh
# Build TaskPill for macOS: icon -> PyInstaller TaskPill.app -> ad-hoc signature -> .dmg
#   sh packaging/build_macos.sh
# Output: dist/TaskPill.app and dist/TaskPill-<version>-Mac-AppleSilicon.dmg
# (names: src/taskpill/release_files.py)
#
# No Apple Developer account, so the app is signed "ad hoc" (Apple Silicon refuses to
# run unsigned code at all) and not notarized: the first open needs "Open Anyway" in
# System Settings -> Privacy & Security. See README -> macOS.
set -eu
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PYTHON=.venv/bin/python

VERSION=$("$PYTHON" -c "import sys; sys.path.insert(0, 'src'); import taskpill; print(taskpill.__version__)")
echo "Building TaskPill $VERSION for macOS"

mkdir -p build
rm -rf build/taskpill.iconset
"$PYTHON" packaging/make_icon.py build/taskpill.iconset
iconutil -c icns build/taskpill.iconset -o build/taskpill.icns

"$PYTHON" -m PyInstaller --noconfirm --clean --log-level WARN packaging/taskpill_mac.spec \
    --distpath dist --workpath build/pyinstaller

APP=dist/TaskPill.app
test -x "$APP/Contents/MacOS/TaskPill" || { echo "TaskPill missing from the bundle"; exit 1; }
test -x "$APP/Contents/MacOS/taskpill-hook" || { echo "taskpill-hook missing from the bundle"; exit 1; }
test -f "$APP/Contents/Resources/taskpill/sounds/done.wav" \
    || find "$APP" -name done.wav | grep -q . || { echo "sounds missing"; exit 1; }

# One ad-hoc signature over the whole bundle, after PyInstaller's per-file ones.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# The hook helper must answer at once and print nothing (it runs on every hook event).
OUT=$(echo '{"hook_event_name":"Notification","session_id":"build-check"}' \
    | TASKPILL_CONFIG_DIR="$(mktemp -d)" "$APP/Contents/MacOS/taskpill-hook")
[ -z "$OUT" ] || { echo "the hook printed something: $OUT"; exit 1; }

# The .dmg: the app next to a shortcut to Applications, so people can drag it across.
STAGE=build/dmg
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/TaskPill-$VERSION-Mac-AppleSilicon.dmg"
rm -f "$DMG"
hdiutil create -volname "TaskPill" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "Done: $DMG"
