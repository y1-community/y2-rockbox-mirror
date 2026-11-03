#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/00_tools/build_rockbox_y2_v87_vendor_shell_save_wsl.sh"
GENERATED="$ROOT/build-intermediates/.generated-v88-android-wrapper.sh"

test -f "$TEMPLATE" || {
    echo "Missing V87 Android build wrapper: $TEMPLATE" >&2
    exit 2
}

python3 - "$TEMPLATE" "$GENERATED" <<'PY'
import sys

source, output = sys.argv[1:3]
text = open(source, encoding="utf-8").read()
text = text.replace("vendor-shell-save", "route-readback-repair")
text = text.replace("vendor_shell_save", "route_readback_repair")
text = text.replace("v87", "v88").replace("V87", "V88")
text = text.replace(
    "verified V88 minimal UI, vendor-shell save and stable playback/resources",
    "verified V88 route readback repair and stable playback/resources",
)
open(output, "w", encoding="utf-8", newline="\n").write(text)
PY

chmod 0755 "$GENERATED"
exec "$GENERATED"
