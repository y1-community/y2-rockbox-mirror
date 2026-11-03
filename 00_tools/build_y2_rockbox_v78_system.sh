#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_y2_rockbox_v74_system.sh"
TEMP="$ROOT/00_tools/.build-system-v78-hard-home-gate-direct.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V74 direct system builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v74-release-candidate/v78-hard-home-gate/g' \
    -e 's/V74/V78/g' \
    -e 's/v74/v78/g' \
    -e 's#BASE_RAW="$BASE/y2-rockbox-system-prototype-v69-route-owner-system.raw.img"#BASE_RAW="$BASE/y2-rockbox-system-prototype-v77-release-day-gate/system.raw.img"#' \
    "$SOURCE" > "$TEMP"
chmod 0755 "$TEMP"
bash "$TEMP"

BASE="/mnt/e/Y2-RockBox-build-intermediates"
V77_RAW="$BASE/y2-rockbox-system-prototype-v77-release-day-gate/system.raw.img"
V78_RAW="$BASE/y2-rockbox-system-prototype-v78-hard-home-gate/system.raw.img"
for asset in /media/bootanimation.zip; do
    old="$BASE/y2-rockbox-system-prototype-v78-hard-home-gate/old-$(basename "$asset")"
    new="$BASE/y2-rockbox-system-prototype-v78-hard-home-gate/new-$(basename "$asset")"
    debugfs -R "dump $asset $old" "$V77_RAW"
    debugfs -R "dump $asset $new" "$V78_RAW"
    cmp "$old" "$new"
done
echo "verified V78 retains the V77 boot animation byte-for-byte"
