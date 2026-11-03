#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_rockbox_y2_v74_release_candidate_wsl.sh"
TEMP="$ROOT/00_tools/.build-rockbox-v78-hard-home-gate-direct.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V74 direct builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v74-release-candidate/v78-hard-home-gate/g' \
    -e 's/V74/V78/g' \
    -e 's/v74-/v78-/g' \
    "$SOURCE" > "$TEMP"

python3 - "$TEMP" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
negative = """if 'android.intent.category.HOME'.encode('utf-16le') in manifest:
    raise SystemExit('V78 must not declare an Android HOME candidate')
"""
positive = """if 'android.intent.category.HOME'.encode('utf-16le') not in manifest:
    raise SystemExit('V78 must declare the persistent Android HOME router')
if 'android.permission.SET_PREFERRED_APPLICATIONS'.encode('utf-16le') not in manifest:
    raise SystemExit('V78 preferred HOME permission is absent')
"""
if text.count(negative) != 1:
    raise SystemExit("V78 HOME assertion anchor drifted")
text = text.replace(negative, positive)
text = text.replace(
    "verified V78 Java policy, no HOME filter, bundled OneBitMono",
    "verified V78 Java policy, persistent HOME router, bundled OneBitMono",
)

zipalign = '"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 bin/v78-signed.apk rockbox.apk'
normalized = r'''python3 - bin/v78-signed.apk bin/v78-signed-normalized.apk <<'PY_NORMALIZE'
import sys, zipfile
source_path, output_path = sys.argv[1:3]
with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(output_path, 'w') as output:
    for source_info in source.infolist():
        info = zipfile.ZipInfo(source_info.filename, (2026, 7, 24, 7, 50, 0))
        info.compress_type = source_info.compress_type
        info.external_attr = source_info.external_attr
        info.internal_attr = source_info.internal_attr
        info.create_system = source_info.create_system
        info.flag_bits = source_info.flag_bits & ~0x08
        output.writestr(info, source.read(source_info.filename))
PY_NORMALIZE
"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 bin/v78-signed-normalized.apk rockbox.apk'''
if text.count(zipalign) != 1:
    raise SystemExit("V78 zip normalization anchor drifted")
path.write_text(text.replace(zipalign, normalized))
PY

chmod 0755 "$TEMP"
bash "$TEMP"

APK="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v78-hard-home-gate/rockbox-y2-v78-hard-home-gate.apk"
python3 - "$APK" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    dex = archive.read("classes.dex")
    manifest = archive.read("AndroidManifest.xml")
for token in (
    b"FirmwareHome:preferred HOME pinned",
    b"FirmwareHome:hold unauthenticated HOME invocation",
    b"FirmwareHome:restored current-boot route",
    b"root component gate remains",
    b"y2_rockbox_v78_hard_home_gate_marker.txt",
):
    if token not in dex:
        raise SystemExit(f"V78 classes.dex token absent: {token!r}")
for token in (
    "android.intent.category.HOME",
    "android.permission.SET_PREFERRED_APPLICATIONS",
):
    if token.encode("utf-16le") not in manifest:
        raise SystemExit(f"V78 binary manifest token absent: {token}")
print("verified V78 persistent preferred HOME router and recovery tokens")
PY
