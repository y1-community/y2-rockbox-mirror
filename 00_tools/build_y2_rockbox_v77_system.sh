#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/00_tools/build_y2_rockbox_v76_system.sh"
TEMP="$ROOT/00_tools/.build-system-v77-release-day-gate-outer.generated.sh"
trap 'rm -f "$TEMP"' EXIT

test -f "$SOURCE" || { echo "Missing V76 system builder: $SOURCE" >&2; exit 2; }
sed \
    -e 's/v76-root-route/v77-release-day-gate/g' \
    -e 's/V76/V77/g' \
    -e 's/v76/v77/g' \
    "$SOURCE" > "$TEMP"
chmod 0755 "$TEMP"
bash "$TEMP"
