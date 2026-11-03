#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/00_tools/build_y2_rockbox_v87_system.sh"
GENERATED="$ROOT/build-intermediates/.generated-v89-system-build.sh"

test -f "$TEMPLATE" || {
    echo "Missing V87 system-image builder: $TEMPLATE" >&2
    exit 2
}

python3 - "$TEMPLATE" "$GENERATED" <<'PY'
import sys

source, output = sys.argv[1:3]
text = open(source, encoding="utf-8").read()
text = text.replace("vendor-shell-save", "usb-display-restore")
text = text.replace("v87", "v89").replace("V87", "V89")

# V89 changes only the Android display lifecycle. Reuse the exact V87 broker
# already present in and physically proven through V88.
text = text.replace(
    'BROKER="$ROOT/00_tools/y2_v89_boot_save_broker.sh"',
    'BROKER="$ROOT/00_tools/y2_v87_boot_save_broker.sh"',
)
open(output, "w", encoding="utf-8", newline="\n").write(text)
PY

chmod 0755 "$GENERATED"
sync "$GENERATED"
exec bash "$GENERATED"
