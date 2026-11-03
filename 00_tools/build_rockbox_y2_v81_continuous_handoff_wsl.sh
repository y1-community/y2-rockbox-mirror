#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_rockbox_y2_v80_release_gate_wsl.sh"
TEMP="$ROOT/00_tools/.build-rockbox-v81-stage1.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || {
    echo "Missing V80 Android builder: $SOURCE" >&2
    exit 2
}
sed \
    -e 's/v80-release-gate/v81-continuous-handoff/g' \
    -e 's/v80_release_gate/v81_continuous_handoff/g' \
    -e 's/V80/V81/g' \
    -e 's/v80-/v81-/g' \
    "$SOURCE" > "$TEMP"

chmod 0755 "$TEMP"
bash "$TEMP"

APK="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v81-continuous-handoff/rockbox-y2-v81-continuous-handoff.apk"
python3 - "$APK" <<'PY'
import io
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    if archive.testzip() is not None:
        raise SystemExit("V81 APK failed CRC")
    dex = archive.read("classes.dex")
    manifest = archive.read("AndroidManifest.xml")
    resources = archive.read("lib/armeabi/libmisc.so")
for token in (
    b"buildVersion=",
    b"y2_rockbox_v81_continuous_handoff_marker.txt",
    b"Each boot input must use a different option.",
    b"One boot input must launch Boot Settings.",
    b"y2_boot_routes.request",
    b"Saving...",
    b"Saved - restarting...",
    b"Save timed out. Nothing was changed; please try again.",
    b"root verified save; waiting for root reboot",
):
    if token not in dex:
        raise SystemExit(f"V81 classes.dex token absent: {token!r}")
for token in (
    "android.intent.category.HOME",
    "android.permission.SET_PREFERRED_APPLICATIONS",
):
    if token.encode("utf-16le") not in manifest:
        raise SystemExit(f"V81 binary manifest token absent: {token}")
with zipfile.ZipFile(io.BytesIO(resources)) as archive:
    sbs = archive.read(".rockbox/wps/OneBitMono.sbs")
if b"%Vi(menu,0,48,480,268,-)" not in sbs:
    raise SystemExit("V81 full-width OneBitMono viewport absent")
if b"%Vi(menu,30,75,420,247,-)" in sbs:
    raise SystemExit("V81 retained the inset OneBitMono viewport")
print("verified V81 marker, save UI, HOME policy and OneBitMono resources")
PY
