#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_rockbox_y2_v78_hard_home_gate_wsl.sh"
TEMP="$ROOT/00_tools/.build-rockbox-v79-release-polish-wrapper.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V78 Android builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v78-hard-home-gate/v79-release-polish/g' \
    -e 's/v78_hard_home_gate/v79_release_polish/g' \
    -e 's/V78/V79/g' \
    -e 's/v78-/v79-/g' \
    "$SOURCE" > "$TEMP"

python3 - "$TEMP" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
anchor = "text = path.read_text()\n"
replacement = (
    anchor
    + "text = text.replace(\"b'persist-boot-route-map'\", "
      "\"b'y2_boot_routes.request'\")\n"
)
if text.count(anchor) != 1:
    raise SystemExit("V79 inherited direct-builder patch anchor drifted")
path.write_text(text.replace(anchor, replacement))
PY

chmod 0755 "$TEMP"
bash "$TEMP"

APK="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v79-release-polish/rockbox-y2-v79-release-polish.apk"
python3 - "$APK" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    dex = archive.read("classes.dex")
for token in (
    b"y2_rockbox_v79_release_polish_marker.txt",
    b"Each boot input must use a different option.",
    b"One boot input must launch Boot Settings.",
    b"y2_boot_routes.request",
    b"root broker owns post-save reboot",
    b"framebuffer attach skipped already attached",
):
    if token not in dex:
        raise SystemExit(f"V79 classes.dex token absent: {token!r}")
if b"Could not save boot settings. No changes were applied." in dex:
    raise SystemExit("V79 retained the misleading unchanged-settings error")
print("verified V79 dropdown, route broker, validation and single-framebuffer tokens")
PY
