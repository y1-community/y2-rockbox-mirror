#!/usr/bin/env python3
"""Build V76: root-owned route bootstrap and root-owned USB prompt."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v75-route-handoff.zip"
BASE_SHA256 = "C5386532B8E7A0FC20E5CB1EC347985D5FF5193643511E3A27C262D46FEA26BD"
V76_SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v76-root-route" / "system.img"
OUT = E_ROOT / "y2-v76-root-route"
ZIP = E_ROOT / "y2-v76-root-route.zip"
ZIP_SHA = E_ROOT / "y2-v76-root-route.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 22, 2, 0, 0)
CPIO_MTIME = 1784656800
PARTITION_SIZE = 16 * 1024 * 1024
USB_GUARD = "sbin/y2v39usbguard.sh"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v75 = load("v75_builder_base", ROOT / "00_tools" / "build_y2_v75_route_handoff.py")
boot_tools = v75.boot_tools
parser = v75.parser
FILES = v75.FILES
ROUTE_SCRIPT = v75.ROUTE_SCRIPT
ROUTE_GUARD = v75.ROUTE_GUARD


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def base_image(name: str) -> bytes:
    with zipfile.ZipFile(BASE_ZIP) as archive:
        return archive.read(name)


def ramdisk(image: bytes):
    parts = boot_tools.parse_boot_image(image)
    mtk_header, cpio, label = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = boot_tools.parse_cpio_newc(cpio)
    if boot_tools.build_cpio_newc(entries) != cpio:
        raise RuntimeError("Base CPIO does not round-trip exactly")
    return entries, parts, mtk_header, label


def rename_v76(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v75-route-handoff", "y2-v76-root-route")
    text = text.replace("Y2_V75_DEBUG", "Y2_V76_DEBUG")
    text = text.replace("y2_v75_", "y2_v76_")
    text = text.replace("Y2 V75", "Y2 V76")
    return text.encode("ascii")


def v76_route_script(data: bytes) -> bytes:
    text = rename_v76(data).decode("ascii")
    isolation = '            if [ "$ROUTE" = "rockbox" ]; then\n'
    if text.count(isolation) != 1:
        raise RuntimeError("V76 component-isolation anchor drifted")
    text = text.replace(isolation, '            if [ "$ROUTE" != "stock" ]; then\n')

    start = text.index('{\n    echo "build=$BUILD"\n    echo "route=$ROUTE"\n    echo "readiness=proven"')
    end_anchor = 'echo "dispatch_signal=$DISPATCH_SIGNAL" >> "$OUT/08-route-dispatch.txt"\n'
    end = text.index(end_anchor, start) + len(end_anchor)
    replacement = r'''BOOTSTRAP_COMPONENT="org.rockbox/.Y2FirmwareHomeActivity"
{
    echo "build=$BUILD"
    echo "route=$ROUTE"
    echo "readiness=proven"
    echo "readiness_attempts=$READINESS_ATTEMPT"
    echo "environment_repaired=$ENVIRONMENT_REPAIRED"
    echo "effective_BOOTCLASSPATH=$BOOTCLASSPATH"
    echo "route_owner=root init_shell bootstrap plus Y2RouteShieldService"
    echo "command=am start -W -n $BOOTSTRAP_COMPONENT --es physical_route $PHYSICAL_ROUTE --es route $ROUTE"
    echo "ready_date=$(date 2>/dev/null)"
    echo "ready_uptime=$(cat /proc/uptime 2>/dev/null)"
} > "$OUT/08-route-dispatch.txt"
copy_all_storage small

DISPATCH_OK=0
DISPATCH_PHASE="root-bootstrap"
TOTAL_DISPATCH_ATTEMPT=0
if [ "$ROUTE" = "stock" ]; then
    DISPATCH_OK=1
    DISPATCH_PHASE="stock-no-bootstrap"
    echo "dispatch=not-required reason=effective-stock-owned-by-vendor-home" >> "$OUT/08-route-dispatch.txt"
else
    while [ "$TOTAL_DISPATCH_ATTEMPT" -lt 90 ]; do
        TEMP_RESULT="$OUT/.activity-result-$TOTAL_DISPATCH_ATTEMPT.txt"
        am start -W -n "$BOOTSTRAP_COMPONENT" --es physical_route "$PHYSICAL_ROUTE" --es route "$ROUTE" > "$TEMP_RESULT" 2>&1
        WRAPPER_RESULT=$?
        HAS_STARTING=0
        HAS_ERROR=0
        if grep -F "Starting:" "$TEMP_RESULT" >/dev/null 2>&1 || \
           grep -F "Status: ok" "$TEMP_RESULT" >/dev/null 2>&1; then
            HAS_STARTING=1
        fi
        if grep -E "Error:|Exception|Permission Denial|does not exist" "$TEMP_RESULT" >/dev/null 2>&1; then
            HAS_ERROR=1
        fi
        {
            echo "dispatch_phase=$DISPATCH_PHASE total_attempt=$TOTAL_DISPATCH_ATTEMPT wrapper_result=$WRAPPER_RESULT has_starting=$HAS_STARTING has_error=$HAS_ERROR date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null)"
            cat "$TEMP_RESULT"
        } >> "$OUT/08-route-dispatch.txt"
        if [ "$WRAPPER_RESULT" -eq 0 ] && [ "$HAS_STARTING" -eq 1 ] && [ "$HAS_ERROR" -eq 0 ]; then
            DISPATCH_OK=1
            rm -f "$TEMP_RESULT"
            break
        fi
        rm -f "$TEMP_RESULT"
        copy_all_storage small
        TOTAL_DISPATCH_ATTEMPT=$((TOTAL_DISPATCH_ATTEMPT + 1))
        sleep 1
    done
fi

if [ "$DISPATCH_OK" -ne 1 ]; then
    {
        echo "dispatch=failed"
        echo "total_dispatch_attempt=$TOTAL_DISPATCH_ATTEMPT"
        echo "action=exit-without-stock-cleanup"
    } >> "$OUT/08-route-dispatch.txt"
    finish_capture fail-safe root-bootstrap-failed
fi

{
    echo "dispatch=success"
    echo "successful_phase=$DISPATCH_PHASE"
    echo "successful_total_attempt=$TOTAL_DISPATCH_ATTEMPT"
    echo "success_date=$(date 2>/dev/null)"
    echo "success_uptime=$(cat /proc/uptime 2>/dev/null)"
} >> "$OUT/08-route-dispatch.txt"
DISPATCH_SIGNAL="$DATA_ROOT/route-dispatched-$BOOT_ID-$ROUTE.txt"
{
    echo "build=$BUILD"
    echo "route=$ROUTE"
    echo "session=$SESSION"
    echo "boot_id=$BOOT_ID"
    echo "dispatch_phase=$DISPATCH_PHASE"
    echo "broadcast_output_validated=no"
    echo "root_bootstrap_validated=yes"
    echo "created_date=$(date 2>/dev/null)"
    echo "created_uptime=$(cat /proc/uptime 2>/dev/null)"
} > "$DISPATCH_SIGNAL"
chmod 0644 "$DISPATCH_SIGNAL"
echo "dispatch_signal=$DISPATCH_SIGNAL" >> "$OUT/08-route-dispatch.txt"
'''
    text = text[:start] + replacement + text[end:]
    if 'am broadcast -a "$ACTION"' in text:
        raise RuntimeError("V76 retained pre-boot broadcast dispatch")
    return text.encode("ascii")


def v76_usb_guard() -> bytes:
    return r'''#!/system/bin/sh

BUILD="y2-v76-root-route"
DATA_ROOT="/data/local/tmp/Y2_V76_DEBUG"
STATE_FILE="/sys/class/android_usb/android0/state"
USB_ACTIVITY="com.android.systemui/.usb.UsbStorageActivity"

mkdir -p "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if [ -z "$BOOT_ID" ]; then
    BOOT_ID="noid"
fi
ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
LOG="$DATA_ROOT/usb-root-broker-$BOOT_ID.txt"

log_event() {
    echo "build=$BUILD date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) $*" >> "$LOG"
    chmod 0644 "$LOG"
}

WAIT=0
while [ "$WAIT" -lt 180 ] && [ ! -f "$ROUTE_FILE" ]; do
    WAIT=$((WAIT + 1))
    sleep 1
done
ROUTE=$(grep '^route=' "$ROUTE_FILE" 2>/dev/null | head -n 1 | cut -d= -f2)
if [ "$ROUTE" != "rockbox" ]; then
    log_event "broker=exit reason=effective-route-not-rockbox route=$ROUTE route_file=$ROUTE_FILE"
    exit 0
fi

LAST_STATE="unknown"
PROMPTED=0
log_event "broker=start route=$ROUTE authority=root-init-shell activity=$USB_ACTIVITY"
while true; do
    STATE=$(cat "$STATE_FILE" 2>/dev/null)
    if [ -z "$STATE" ]; then
        STATE="unknown"
    fi
    if [ "$STATE" != "$LAST_STATE" ]; then
        log_event "usb_state_change previous=$LAST_STATE current=$STATE config=$(getprop sys.usb.config) framework_state=$(getprop sys.usb.state)"
    fi
    if [ "$STATE" = "CONFIGURED" ] || [ "$STATE" = "CONNECTED" ]; then
        if [ "$PROMPTED" -eq 0 ]; then
            RESULT_FILE="$DATA_ROOT/.usb-activity-$BOOT_ID.txt"
            am start -W -n "$USB_ACTIVITY" > "$RESULT_FILE" 2>&1
            RESULT=$?
            HAS_ERROR=0
            if grep -E "Error:|Exception|Permission Denial|does not exist" "$RESULT_FILE" >/dev/null 2>&1; then
                HAS_ERROR=1
            fi
            log_event "usb=$STATE action=root-start result=$RESULT has_error=$HAS_ERROR"
            cat "$RESULT_FILE" >> "$LOG"
            rm -f "$RESULT_FILE"
            if [ "$RESULT" -eq 0 ] && [ "$HAS_ERROR" -eq 0 ]; then
                PROMPTED=1
            fi
        fi
    else
        if [ "$LAST_STATE" = "CONFIGURED" ] || [ "$LAST_STATE" = "CONNECTED" ]; then
            log_event "usb=$STATE action=connection-ended"
        fi
        PROMPTED=0
    fi
    LAST_STATE="$STATE"
    sleep 1
done
'''.encode("ascii")


def scripts() -> dict[str, bytes]:
    entries, *_ = ramdisk(base_image("recovery.img"))
    source = {entry["name"]: entry["data"] for entry in entries}
    result = {}
    for name in v75.v74.SCRIPT_NAMES:
        if name == ROUTE_SCRIPT:
            result[name] = v76_route_script(source[name])
        elif name == USB_GUARD:
            result[name] = v76_usb_guard()
        else:
            result[name] = rename_v76(source[name])
    result[USB_GUARD] = v76_usb_guard()
    return result


USB_SERVICE = '''# Y2 V76: root-owned SystemUI USB prompt broker for effective Rockbox routes.
service y2v39usbguard /system/bin/sh /sbin/y2v39usbguard.sh
    class late_start
    user root
    group root shell log system sdcard_r sdcard_rw media_rw
    disabled
    oneshot
    seclabel u:r:init_shell:s0

on property:sys.boot_completed=1
    start y2v39usbguard
'''


def ensure_usb_service(text: str) -> str:
    if "service y2v39usbguard " in text:
        return text
    return text.rstrip() + "\n\n" + USB_SERVICE


def patch_image(name: str, payloads: dict[str, bytes]) -> dict[str, object]:
    path = OUT / name
    before = path.read_bytes()
    entries, parts, mtk_header, label = ramdisk(before)
    entry_map = {entry["name"]: entry for entry in entries}
    if USB_GUARD not in entry_map:
        template = dict(entry_map[ROUTE_SCRIPT])
        template.update(name=USB_GUARD, ino=max(e["ino"] for e in entries) + 1,
                        data=payloads[USB_GUARD], mode=0o100750,
                        mtime=CPIO_MTIME)
        entries.insert(-1, template)
        entry_map[USB_GUARD] = template
    installed = {n: d for n, d in payloads.items() if n in entry_map}
    for script_name, data in installed.items():
        entry_map[script_name]["data"] = data
        entry_map[script_name]["mode"] = 0o100750
        entry_map[script_name]["mtime"] = CPIO_MTIME
    for rc_name in ("init.rc", "factory_init.rc"):
        if rc_name not in entry_map:
            continue
        text = entry_map[rc_name]["data"].decode("ascii")
        text = text.replace("V75 authenticates", "V76 root bootstrap authenticates")
        text = ensure_usb_service(text)
        entry_map[rc_name]["data"] = text.encode("ascii")
        entry_map[rc_name]["mtime"] = CPIO_MTIME
    built_cpio = boot_tools.build_cpio_newc(entries)
    built_ramdisk = boot_tools.build_mtk_ramdisk(mtk_header, built_cpio)
    after = boot_tools.build_boot_image(parts, built_ramdisk)
    if len(after) > PARTITION_SIZE:
        raise RuntimeError(f"{name} exceeds its partition")
    path.write_bytes(after)
    final_entries, final_parts, _, final_label = ramdisk(after)
    final = {entry["name"]: entry["data"] for entry in final_entries}
    for script_name, data in installed.items():
        if final[script_name] != data:
            raise RuntimeError(f"{name} embedded script mismatch: {script_name}")
    if final_parts["kernel"] != parts["kernel"] or final_label != label:
        raise RuntimeError(f"{name} changed kernel or MediaTek label")
    return {"before": sha256_bytes(before), "after": sha256_bytes(after),
            "kernel_unchanged": True, "scripts": sorted(installed)}


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V75 base is missing or drifted")
    if not V76_SYSTEM.is_file():
        raise FileNotFoundError(V76_SYSTEM)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V75 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V75 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v76-root-route":
        raise RuntimeError(f"Unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V76_SYSTEM, OUT / "system.img")
    payloads = scripts()
    image_patches = {name: patch_image(name, payloads)
                     for name in ("boot.img", "recovery.img")}
    files = {name: {"size": (OUT / name).stat().st_size,
                    "sha256": sha256(OUT / name),
                    "v75_sha256": base_hashes[name],
                    "matches_v75": sha256(OUT / name) == base_hashes[name]}
             for name in FILES}
    changed = [name for name in FILES if not files[name]["matches_v75"]]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V76 partition delta: {changed}")
    manifest = {
        "build": "y2-v76-root-route",
        "status": "root-owned boot and USB candidate; physical validation required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v75_findings": [
            "Pre-boot app broadcasts were rejected until Stock HOME had already started.",
            "Stock reclaimed Boot Settings after Android boot completion.",
            "The app UID could not open SystemUI's non-exported USB storage activity.",
        ],
        "behavior_delta": [
            "Init starts an explicit Rockbox bootstrap Activity instead of a pre-boot broadcast.",
            "The black route shield remains through boot completion before Rockbox or Boot Settings launches.",
            "A root init_shell broker opens the SystemUI USB activity on every effective Rockbox route.",
            "Cross-boot Boot Settings and USB grace state is cleared at route-session start.",
        ],
        "branding_unchanged": True,
        "haptic_unchanged": True,
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    report_json = "y2-v76-root-route.json"
    report_md = "y2-v76-root-route.md"
    test_txt = "V76-TEST.txt"
    (OUT / report_json).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / report_md).write_text(
        "# Y2 V76 Root Route\n\nV76 replaces V75's racing app broadcast with root-owned boot and USB handoffs. Boot branding and haptic behavior are byte-identical to V75.\n",
        encoding="utf-8")
    (OUT / test_txt).write_text(
        "Y2 V76 TEST\n"
        "1. Flash the complete package using Download Only. NEVER Format All.\n"
        "2. Cold boot: no button=Rockbox, Volume Up=Y2 Stock, Volume Down=Boot Settings.\n"
        "3. Confirm no HOME chooser, Stock foreground, or unexplained black pause on Rockbox and Boot Settings routes.\n"
        "4. In Rockbox test sleep/centre wake five times and three-second power.\n"
        "5. Plug USB and confirm the storage screen opens. Enable storage, safely eject both Windows drives, then turn storage off; confirm one clean Rockbox return.\n"
        "6. Repeat USB storage, safely eject, then unplug the cable; confirm one clean Rockbox return.\n",
        encoding="utf-8")
    if ZIP.exists():
        ZIP.unlink()
    members = (*FILES, report_json, report_md, test_txt)
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())
    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V76 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(f"{digest} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(ZIP), "size": ZIP.stat().st_size,
                      "sha256": digest, "changed_from_v75": changed}, indent=2))


if __name__ == "__main__":
    main()
