#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo "Forex Calendar Lab can only be packaged as a .app on macOS." >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 2; }
python3 -c 'import PySide6, openpyxl' || { echo "Install dependencies: python3 -m pip install -r requirements-macos.txt" >&2; exit 2; }
command -v pyside6-deploy >/dev/null || { echo "pyside6-deploy is required (provided by PySide6)." >&2; exit 2; }
HELP="$(pyside6-deploy --help)"
for option in --name --force; do grep -q -- "$option" <<<"$HELP" || { echo "Installed pyside6-deploy does not support $option; upgrade PySide6." >&2; exit 2; }; done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"; rm -rf build/macos-stage "dist/Forex Calendar Lab.app"; mkdir -p build/macos-stage dist
cp -R ff_calendar_toolkit build/macos-stage/; cp requirements-macos.txt build/macos-stage/
# Create a complete native icon set from the repository-owned SVG using QtSvg.
ICONSET="build/macos-stage/ForexCalendarLab.iconset"; mkdir -p "$ICONSET"
QT_QPA_PLATFORM=offscreen python3 scripts/render_macos_icon.py ff_calendar_toolkit/mac_app/assets/icon.svg "$ICONSET"
iconutil -c icns "$ICONSET" -o build/macos-stage/ForexCalendarLab.icns
cat > build/macos-stage/main.py <<'EOF'
from ff_calendar_toolkit.mac_app.app import main
raise SystemExit(main())
EOF
cd build/macos-stage
pyside6-deploy main.py --name "Forex Calendar Lab" --force
APP="$(find . -maxdepth 4 -type d -name '*.app' -print -quit)"; [[ -n "$APP" ]] || { echo "pyside6-deploy did not produce an app bundle" >&2; exit 1; }
cd "$ROOT"; mv "build/macos-stage/$APP" "dist/Forex Calendar Lab.app"
PLIST="dist/Forex Calendar Lab.app/Contents/Info.plist"
[[ -f "$PLIST" ]] || { echo "Generated app is missing Info.plist" >&2; exit 1; }
cp build/macos-stage/ForexCalendarLab.icns "dist/Forex Calendar Lab.app/Contents/Resources/ForexCalendarLab.icns"
/usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName Forex Calendar Lab' "$PLIST"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier com.destin.forexcalendarlab' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleShortVersionString string 1.0.0' "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Set :CFBundleShortVersionString 1.0.0' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :LSApplicationCategoryType string public.app-category.finance' "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Set :LSApplicationCategoryType public.app-category.finance' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string ForexCalendarLab.icns' "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile ForexCalendarLab.icns' "$PLIST"
if command -v codesign >/dev/null; then codesign --force --deep --sign - "dist/Forex Calendar Lab.app"; codesign --verify --deep --strict "dist/Forex Calendar Lab.app"; fi
echo "Built: $ROOT/dist/Forex Calendar Lab.app"; echo "Launch: open '$ROOT/dist/Forex Calendar Lab.app'"
