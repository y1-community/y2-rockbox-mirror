#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_rockbox_y2_v78_hard_home_gate_wsl.sh"
TEMP="$ROOT/00_tools/.build-rockbox-v80-release-gate-wrapper.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V78 Android builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v78-hard-home-gate/v80-release-gate/g' \
    -e 's/v78_hard_home_gate/v80_release_gate/g' \
    -e 's/V78/V80/g' \
    -e 's/v78-/v80-/g' \
    "$SOURCE" > "$TEMP"

# This edits the Python transform inside the inherited V78 wrapper. That
# transform then applies these V80 resource changes to the generated V74
# direct builder before any Android compilation begins.
python3 - "$TEMP" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
anchor = "text = path.read_text()\n"
injected = r'''text = text.replace(
    "b'persist-boot-route-map'", "b'y2_boot_routes.request'")
theme_anchor = "        target.writestr(info, path.read_bytes())\n"
theme_replacement = """        data = path.read_bytes()
        if name == '.rockbox/wps/OneBitMono.sbs':
            old = b'%Vi(menu,30,75,420,247,-)'
            new = b'%Vi(menu,0,48,480,268,-)'
            if data.count(old) != 1:
                raise SystemExit('OneBitMono menu viewport anchor drifted')
            data = data.replace(old, new)
        target.writestr(info, data)
"""
if text.count(theme_anchor) != 1:
    raise SystemExit("V80 OneBitMono direct-builder anchor drifted")
text = text.replace(theme_anchor, theme_replacement)
'''
replacement = anchor + injected
if text.count(anchor) != 1:
    raise SystemExit("V80 inherited direct-builder transform anchor drifted")
path.write_text(text.replace(anchor, replacement))
PY

chmod 0755 "$TEMP"
bash "$TEMP"

APK="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v80-release-gate/rockbox-y2-v80-release-gate.apk"
python3 - "$APK" <<'PY'
import io
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    if archive.testzip() is not None:
        raise SystemExit("V80 APK failed CRC")
    dex = archive.read("classes.dex")
    manifest = archive.read("AndroidManifest.xml")
    resources = archive.read("lib/armeabi/libmisc.so")
for token in (
    b"y2_rockbox_v80_release_gate_marker.txt",
    b"Each boot input must use a different option.",
    b"One boot input must launch Boot Settings.",
    b"y2_boot_routes.request",
    b"framebuffer attach skipped already attached",
    b"Saving...",
    b"Saved - restarting...",
    b"Save timed out. Nothing was changed; please try again.",
    b"root verified save; waiting for root reboot",
):
    if token not in dex:
        raise SystemExit(f"V80 classes.dex token absent: {token!r}")
for token in (
    "android.intent.category.HOME",
    "android.permission.SET_PREFERRED_APPLICATIONS",
):
    if token.encode("utf-16le") not in manifest:
        raise SystemExit(f"V80 binary manifest token absent: {token}")
with zipfile.ZipFile(io.BytesIO(resources)) as archive:
    sbs = archive.read(".rockbox/wps/OneBitMono.sbs")
if b"%Vi(menu,0,48,480,268,-)" not in sbs:
    raise SystemExit("V80 full-width OneBitMono menu viewport absent")
if b"%Vi(menu,30,75,420,247,-)" in sbs:
    raise SystemExit("V80 retained the inset OneBitMono menu viewport")
print("verified V80 HOME policy, save states and full-width OneBitMono viewport")
PY
