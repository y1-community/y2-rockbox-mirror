#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_rockbox_y2_v76_root_route_wsl.sh"
TEMP="$ROOT/00_tools/.build-rockbox-v77-release-day-gate-outer.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V76 builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v76-root-route/v77-release-day-gate/g' \
    -e 's/v76_root_route/v77_release_day_gate/g' \
    -e 's/V76/V77/g' \
    -e 's/v76-/v77-/g' \
    "$SOURCE" > "$TEMP"
chmod 0755 "$TEMP"
bash "$TEMP"

APK="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v77-release-day-gate/rockbox-y2-v77-release-day-gate.apk"
python3 - "$APK" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    dex = archive.read('classes.dex')
for token in (
    b'FirmwareHome:onCreate root-bootstrap',
    b'FirmwareHome:started root-owned route=',
    b'ROUTE_SHIELD_USB_DISCONNECT_RECOVERY',
    b'rootBroker=authoritative',
    b'y2_rockbox_v77_release_day_gate_marker.txt'):
    if token not in dex:
        raise SystemExit(f'V77 classes.dex token absent: {token!r}')
print('verified V77 root route, USB recovery and unambiguous marker tokens')
PY
