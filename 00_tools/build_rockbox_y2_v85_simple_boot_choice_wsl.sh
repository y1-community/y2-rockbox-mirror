#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/00_tools/build_rockbox_y2_v84_coherent_boot_settings_wsl.sh"
GENERATED="$ROOT/build-intermediates/.generated-v85-android-build.sh"

test -f "$TEMPLATE" || {
    echo "Missing V84 Android build template: $TEMPLATE" >&2
    exit 2
}

python3 - "$TEMPLATE" "$GENERATED" <<'PY'
import sys

source, output = sys.argv[1:3]
text = open(source, encoding="utf-8").read()
text = text.replace("coherent-boot-settings", "simple-boot-choice")
text = text.replace("v84", "v85").replace("V84", "V85")

old = '''for token in (
    b"y2_rockbox_v85_coherent_boot_settings_marker.txt",
    b"y2-v85-simple-boot-choice",
    b"content://org.rockbox.y2.bootroutes/status",
    b"protocol_version",
    b"broker_build",
    b"current_boot_id",
    b"Firmware update incomplete",
    b"Retry Firmware Check",
    b"boot-route IPC request submitted",
    b"boot-route IPC broker confirmed",
    b"Saved - restarting...",
):'''
new = '''for token in (
    b"y2_rockbox_v85_simple_boot_choice_marker.txt",
    b"content://org.rockbox.y2.bootroutes/request",
    b"protocol_version",
    b"normal_boot",
    b"When the player is powered on normally, start:",
    b"Holding Volume Up at power-on will start ",
    b"Save & Restart",
    b"normal-boot request submitted",
    b"normal-boot save confirmed",
    b"Saved - restarting...",
):'''
if text.count(old) != 1:
    raise SystemExit("V85 token-check template anchor drifted")
text = text.replace(old, new)
text = text.replace(
    "verified V85 boot-ID handshake, coherence gate and stable playback/resources",
    "verified V85 simple boot choice, acknowledged save and stable playback/resources",
)
open(output, "w", encoding="utf-8", newline="\n").write(text)
PY

chmod 0755 "$GENERATED"
exec "$GENERATED"
