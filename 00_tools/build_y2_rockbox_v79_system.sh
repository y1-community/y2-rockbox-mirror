#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_y2_rockbox_v74_system.sh"
TEMP="$ROOT/00_tools/.build-system-v79-release-polish-direct.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V74 direct system builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v74-release-candidate/v79-release-polish/g' \
    -e 's/V74/V79/g' \
    -e 's/v74/v79/g' \
    -e 's#BASE_RAW="$BASE/y2-rockbox-system-prototype-v69-route-owner-system.raw.img"#BASE_RAW="$BASE/y2-rockbox-system-prototype-v78-hard-home-gate/system.raw.img"#' \
    "$SOURCE" > "$TEMP"
chmod 0755 "$TEMP"
bash "$TEMP"

BASE="/mnt/e/Y2-RockBox-build-intermediates"
V78_RAW="$BASE/y2-rockbox-system-prototype-v78-hard-home-gate/system.raw.img"
V79_RAW="$BASE/y2-rockbox-system-prototype-v79-release-polish/system.raw.img"
for asset in /media/bootanimation.zip; do
    old="$BASE/y2-rockbox-system-prototype-v79-release-polish/old-$(basename "$asset")"
    new="$BASE/y2-rockbox-system-prototype-v79-release-polish/new-$(basename "$asset")"
    debugfs -R "dump $asset $old" "$V78_RAW"
    debugfs -R "dump $asset $new" "$V79_RAW"
    cmp "$old" "$new"
done
echo "verified V79 retains V78 boot animation byte-for-byte"
