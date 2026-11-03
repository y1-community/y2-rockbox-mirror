#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/00_tools/build_rockbox_y2_v84_coherent_boot_settings_wsl.sh"
GENERATED="$ROOT/build-intermediates/.generated-v86-android-build.sh"

test -f "$TEMPLATE" || {
    echo "Missing V84 Android build template: $TEMPLATE" >&2
    exit 2
}

python3 - "$TEMPLATE" "$GENERATED" <<'PY'
import sys

source, output = sys.argv[1:3]
text = open(source, encoding="utf-8").read()
text = text.replace("coherent-boot-settings", "boot-save-repair")
text = text.replace("v84", "v86").replace("V84", "V86")

old = '''for token in (
    b"y2_rockbox_v86_coherent_boot_settings_marker.txt",
    b"y2-v86-boot-save-repair",
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
    b"y2_rockbox_v86_boot_save_repair_marker.txt",
    b"content://org.rockbox.y2.bootroutes/request",
    b"protocol_version",
    b"normal_boot",
    b"Normal boot",
    b"Rockbox",
    b"Y2 Stock",
    b"Save & Restart",
    b"Could not save. Try again.",
    b"normal-boot request submitted",
    b"normal-boot save confirmed",
    b"Saved - restarting...",
):'''
if text.count(old) != 1:
    raise SystemExit("V86 token-check template anchor drifted")
text = text.replace(old, new)

anchor = '''    if token not in dex:
        raise SystemExit(f"V86 classes.dex token absent: {token!r}")
for token in (
    "android.intent.category.HOME",'''
replacement = '''    if token not in dex:
        raise SystemExit(f"V86 classes.dex token absent: {token!r}")
for forbidden in (
    b"When the player is powered on normally, start:",
    b"Holding Volume Up at power-on will start ",
    b"Hold Volume Down at power-on",
    b"firmware compatibility",
):
    if forbidden in dex:
        raise SystemExit(f"V86 verbose UI token retained: {forbidden!r}")
for token in (
    "android.intent.category.HOME",'''
if text.count(anchor) != 1:
    raise SystemExit("V86 forbidden-token anchor drifted")
text = text.replace(anchor, replacement)
text = text.replace(
    "verified V86 boot-ID handshake, coherence gate and stable playback/resources",
    "verified V86 minimal UI, boot-save repair and stable playback/resources",
)
open(output, "w", encoding="utf-8", newline="\n").write(text)
PY

chmod 0755 "$GENERATED"
exec "$GENERATED"
