#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_rockbox_y2_v74_release_candidate_wsl.sh"
TEMP="$ROOT/00_tools/.build-rockbox-v75-route-handoff.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V74 builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v74-release-candidate/v75-route-handoff/g' \
    -e 's/V74/V75/g' \
    -e 's/v74-/v75-/g' \
    "$SOURCE" > "$TEMP"
python3 - "$TEMP" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
anchor = '"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 bin/v75-signed.apk rockbox.apk'
replacement = r'''python3 - bin/v75-signed.apk bin/v75-signed-normalized.apk <<'PY_NORMALIZE'
import sys, zipfile
source_path, output_path = sys.argv[1:3]
with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(output_path, 'w') as output:
    for source_info in source.infolist():
        info = zipfile.ZipInfo(source_info.filename, (2026, 7, 22, 0, 20, 0))
        info.compress_type = source_info.compress_type
        info.external_attr = source_info.external_attr
        info.internal_attr = source_info.internal_attr
        info.create_system = source_info.create_system
        info.flag_bits = source_info.flag_bits & ~0x08
        output.writestr(info, source.read(source_info.filename))
PY_NORMALIZE
"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 bin/v75-signed-normalized.apk rockbox.apk'''
if text.count(anchor) != 1:
    raise SystemExit('V75 zipalign normalization anchor drifted')
path.write_text(text.replace(anchor, replacement))
PY
chmod 0755 "$TEMP"
bash "$TEMP"

APK="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v75-route-handoff/rockbox-y2-v75-route-handoff.apk"
python3 - "$APK" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    dex = archive.read('classes.dex')
for token in (
    b'physical_route', b'ROUTE_SHIELD_ACTIVITY_READY',
    b'ROUTE_SHIELD_SETTINGS_READY', b'route-coordinator-owns-usb-handoff',
    b'Restoring storage', b'y2_rockbox_v75_route_handoff_marker.txt'):
    if token not in dex:
        raise SystemExit(f'V75 classes.dex token absent: {token!r}')
print('verified V75 effective-route and USB handoff policy tokens')
PY
