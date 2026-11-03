#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/00_tools/build_y2_rockbox_v87_system.sh"
GENERATED="$ROOT/build-intermediates/.generated-v88-system-build.sh"

test -f "$TEMPLATE" || {
    echo "Missing V87 system-image builder: $TEMPLATE" >&2
    exit 2
}

python3 - "$TEMPLATE" "$GENERATED" <<'PY'
import sys

source, output = sys.argv[1:3]
text = open(source, encoding="utf-8").read()
text = text.replace("vendor-shell-save", "route-readback-repair")
text = text.replace("v87", "v88").replace("V87", "V88")

# V87's echo-only broker physically saved and verified the requested map.
# Reuse that exact payload; V88 repairs the separate early-read path.
text = text.replace(
    'BROKER="$ROOT/00_tools/y2_v88_boot_save_broker.sh"',
    'BROKER="$ROOT/00_tools/y2_v87_boot_save_broker.sh"',
)
open(output, "w", encoding="utf-8", newline="\n").write(text)
PY

chmod 0755 "$GENERATED"
exec "$GENERATED"
