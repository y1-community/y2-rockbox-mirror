#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_y2_rockbox_v74_system.sh"
TEMP="$ROOT/00_tools/.build-system-v75-route-handoff.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V74 system builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v74-release-candidate/v75-route-handoff/g' \
    -e 's/V74/V75/g' \
    -e 's/v74/v75/g' \
    -e 's#BASE_RAW="$BASE/y2-rockbox-system-prototype-v69-route-owner-system.raw.img"#BASE_RAW="$BASE/y2-rockbox-system-prototype-v74-release-candidate/system.raw.img"#' \
    "$SOURCE" > "$TEMP"
chmod 0755 "$TEMP"
bash "$TEMP"

BASE="/mnt/e/Y2-RockBox-build-intermediates"
V74_RAW="$BASE/y2-rockbox-system-prototype-v74-release-candidate/system.raw.img"
V75_RAW="$BASE/y2-rockbox-system-prototype-v75-route-handoff/system.raw.img"
for asset in /media/bootanimation.zip; do
    old="$BASE/y2-rockbox-system-prototype-v75-route-handoff/old-$(basename "$asset")"
    new="$BASE/y2-rockbox-system-prototype-v75-route-handoff/new-$(basename "$asset")"
    debugfs -R "dump $asset $old" "$V74_RAW"
    debugfs -R "dump $asset $new" "$V75_RAW"
    cmp "$old" "$new"
done
echo "verified V75 retains the V74 boot animation byte-for-byte"
