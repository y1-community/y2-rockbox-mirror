#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_y2_rockbox_v75_system.sh"
TEMP="$ROOT/00_tools/.build-system-v76-root-route-wrapper.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V75 system builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v75-route-handoff/v76-root-route/g' \
    -e 's/V75/V76/g' \
    -e 's/v75/v76/g' \
    "$SOURCE" > "$TEMP"
chmod 0755 "$TEMP"
bash "$TEMP"
