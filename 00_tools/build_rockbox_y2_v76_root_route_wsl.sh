#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_rockbox_y2_v75_route_handoff_wsl.sh"
TEMP="$ROOT/00_tools/.build-rockbox-v76-root-route-wrapper.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V75 builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v75-route-handoff/v76-root-route/g' \
    -e 's/v75_route_handoff/v76_root_route/g' \
    -e 's/V75/V76/g' \
    -e 's/v75-/v76-/g' \
    "$SOURCE" > "$TEMP"
chmod 0755 "$TEMP"
bash "$TEMP"

APK="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v76-root-route/rockbox-y2-v76-root-route.apk"
python3 - "$APK" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    dex = archive.read('classes.dex')
for token in (
    b'FirmwareHome:onCreate root-bootstrap',
    b'FirmwareHome:started root-owned route=',
    b'ROUTE_SHIELD_USB_DISCONNECT_RECOVERY',
    b'recover unexported USB disconnect',
    b'rootBroker=authoritative',
    b'y2_rockbox_v76_root_route_marker.txt'):
    if token not in dex:
        raise SystemExit(f'V76 classes.dex token absent: {token!r}')
print('verified V76 root bootstrap, USB recovery and marker tokens')
PY
