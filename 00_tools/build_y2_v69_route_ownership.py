#!/usr/bin/env python3
"""Build V69: one visible route owner, exact stock receiver isolation, fast USB."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v68 = load_module(
    "v68_builder_base",
    ROOT / "00_tools" / "build_y2_v68_clean_scan_display_return.py",
)
boot_tools = v68.boot_tools
FILES = v68.FILES
OFFICIAL = v68.OFFICIAL
ROUTE_SCRIPT = "sbin/y2v36route.sh"
ROUTE_GUARD = "sbin/y2v40routeguard.sh"
EARLY_DIAG = "sbin/y2v54earlydiag.sh"
USB_GUARD = "sbin/y2v39usbguard.sh"

V68_ZIP = ROOT / "12_build_outputs" / "y2-v68-clean-scan-display-return.zip"
V68_ZIP_SHA256 = "7F924592301EFF67681C4441F0D56E509DDACA0C736C87402238FD43E7FFA747"
V69_SYSTEM = (
    ROOT
    / "12_build_outputs"
    / "y2-rockbox-system-prototype-v69-route-owner"
    / "system.img"
)

OUT = ROOT / "12_build_outputs" / "y2-v69-route-ownership"
ZIP = ROOT / "12_build_outputs" / "y2-v69-route-ownership.zip"
ZIP_SHA = ROOT / "12_build_outputs" / "y2-v69-route-ownership.zip.sha256.txt"
REPORT_JSON = "y2-v69-route-ownership.json"
REPORT_MD = "y2-v69-route-ownership.md"
BUILD_TIMESTAMP_UTC = "2026-07-19T12:00:00+00:00"
ZIP_TIMESTAMP = (2026, 7, 19, 22, 0, 0)
CPIO_MTIME = 1784397600
PARTITION_SIZE = 16 * 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def replace_once(text: str, before: str, after: str, label: str) -> str:
    if text.count(before) != 1:
        raise RuntimeError(f"V68 {label} anchor drifted")
    return text.replace(before, after, 1)


def replace_identity(text: str) -> str:
    text = text.replace(
        "y2-v68-clean-scan-display-return",
        "y2-v69-route-ownership",
    )
    text = text.replace("Y2_V68_DEBUG", "Y2_V69_DEBUG")
    text = text.replace("Y2 V68", "Y2 V69")
    text = text.replace('y2_v68_"$ROUTE', 'y2_v69_"$ROUTE')
    text = text.replace("y2_v68_", "y2_v69_")
    text = text.replace("y2-v54-prehome-route", "y2-v69-route-ownership")
    text = text.replace("Y2_V54_DEBUG", "Y2_V69_DEBUG")
    return text.replace("Y2 V54", "Y2 V69")


def recovery_script_data() -> dict[str, bytes]:
    with zipfile.ZipFile(V68_ZIP) as archive:
        parts = boot_tools.parse_boot_image(archive.read("recovery.img"))
    parser = v68.v67.recovery_parser()
    _, cpio, _ = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = {
        entry["name"]: entry
        for entry in boot_tools.parse_cpio_newc(cpio)
    }
    return {
        name: entries[name]["data"]
        for name in (ROUTE_SCRIPT, ROUTE_GUARD, EARLY_DIAG, USB_GUARD)
    }


def patch_route_script(text: str) -> str:
    readiness_anchor = """READINESS_ATTEMPT=0
SERVICES_READY=0
while [ "$READINESS_ATTEMPT" -lt "$MAX_READINESS_ATTEMPTS" ]; do
"""
    readiness_replacement = r'''READINESS_ATTEMPT=0
SERVICES_READY=0
COMPONENT_POLICY_APPLIED=0
COMPONENT_POLICY_LOG="$OUT/11-stock-component-policy.txt"
STOCK_BOOT_RECEIVER="com.innioasis.y2/com.innioasis.y1.receiver.BootCompletedReceiver"
STOCK_SD_RECEIVER="com.innioasis.y2/com.innioasis.y1.receiver.SDReceiver"
while [ "$READINESS_ATTEMPT" -lt "$MAX_READINESS_ATTEMPTS" ]; do
'''
    text = replace_once(
        text,
        readiness_anchor,
        readiness_replacement,
        "early component policy state",
    )

    package_anchor = """    if service check package 2>&1 | grep -F "found" >/dev/null 2>&1; then
        PACKAGE_SERVICE=1
    fi
    if service check activity 2>&1 | grep -F "found" >/dev/null 2>&1; then
"""
    package_replacement = r'''    if service check package 2>&1 | grep -F "found" >/dev/null 2>&1; then
        PACKAGE_SERVICE=1
    fi
    if [ "$PACKAGE_SERVICE" -eq 1 ] &&
       [ "$COMPONENT_POLICY_APPLIED" -eq 0 ] &&
       dumpsys package "$STOCK_PACKAGE" 2>/dev/null |
           grep -F "com.innioasis.y1.receiver.BootCompletedReceiver" >/dev/null 2>&1 &&
       dumpsys package "$STOCK_PACKAGE" 2>/dev/null |
           grep -F "com.innioasis.y1.receiver.SDReceiver" >/dev/null 2>&1; then
        {
            echo "build=$BUILD"
            echo "route=$ROUTE"
            echo "policy=restore-on-every-boot-then-isolate-only-popup-producing-receivers-on-rockbox"
            echo "readiness_attempt=$READINESS_ATTEMPT"
            echo "date=$(date 2>/dev/null)"
            echo "uptime=$(cat /proc/uptime 2>/dev/null)"
            echo "--- fail-safe restore ---"
            pm enable "$STOCK_BOOT_RECEIVER" 2>&1
            pm enable "$STOCK_SD_RECEIVER" 2>&1
            if [ "$ROUTE" = "rockbox" ]; then
                echo "--- Rockbox-route isolation before mount/boot broadcasts ---"
                pm disable "$STOCK_BOOT_RECEIVER" 2>&1
                pm disable "$STOCK_SD_RECEIVER" 2>&1
            fi
            echo "--- exact package state ---"
            dumpsys package "$STOCK_PACKAGE" 2>&1 | grep -E \
                "BootCompletedReceiver|SDReceiver|enabledComponents|disabledComponents"
        } > "$COMPONENT_POLICY_LOG"
        chmod 0644 "$COMPONENT_POLICY_LOG"
        COMPONENT_POLICY_APPLIED=1
    fi
    if service check activity 2>&1 | grep -F "found" >/dev/null 2>&1; then
'''
    text = replace_once(
        text,
        package_anchor,
        package_replacement,
        "first stock-package readiness isolation",
    )

    ready_anchor = """if [ "$SERVICES_READY" -ne 1 ]; then
"""
    ready_replacement = """if [ "$COMPONENT_POLICY_APPLIED" -ne 1 ]; then
    {
        echo "build=$BUILD"
        echo "route=$ROUTE"
        echo "component_policy=not-applied"
        echo "reason=stock-receiver-components-never-became-verifiable"
        echo "action=exit-without-route-dispatch"
    } > "$COMPONENT_POLICY_LOG"
    finish_capture fail-safe stock-component-policy-not-applied
fi

if [ "$SERVICES_READY" -ne 1 ]; then
"""
    text = replace_once(
        text,
        ready_anchor,
        ready_replacement,
        "component policy required before route dispatch",
    )

    pattern = re.compile(
        r'            INLINE_AM_RESULT="\$OUT/\.inline-am-\$ROUTE\.txt"\n'
        r'.*?'
        r'            chmod 0644 "\$INLINE_LOG"\n',
        re.DOTALL,
    )
    text, count = pattern.subn(
        '            echo "build=$BUILD date=$(date 2>/dev/null) '
        'uptime=$(cat /proc/uptime 2>/dev/null) '
        'inline=target-foreground-proved action=observe-only-single-owner-coordinator" '
        '>> "$INLINE_LOG"\n',
        text,
    )
    if count != 1:
        raise RuntimeError("V68 inline target reassert anchor drifted")
    return text.replace(
        "storage_is_not_dispatch_blocker=RockboxActivity has a bounded 20-second storage gate",
        "route_owner=Y2RouteShieldService waits for boot completion or both storage volumes",
    )


def passive_guard() -> str:
    return r'''#!/system/bin/sh

BUILD="y2-v69-route-ownership"
DATA_ROOT="/data/local/tmp/Y2_V69_DEBUG"
ROUTE_PROPERTY="y2.firmware.route"
mkdir -p "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"

BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if [ -z "$BOOT_ID" ]; then
    BOOT_ID="noid"
fi
ROUTE=$(getprop "$ROUTE_PROPERTY")
LOG="$DATA_ROOT/guard-$BOOT_ID-$ROUTE.txt"
SIGNAL="$DATA_ROOT/route-dispatched-$BOOT_ID-$ROUTE.txt"

log_event() {
    echo "build=$BUILD date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) $*" >> "$LOG"
    chmod 0644 "$LOG"
}

case "$ROUTE" in
    rockbox|settings) ;;
    *)
        log_event "guard=exit reason=unsupported-route route=$ROUTE action=none"
        exit 0
        ;;
esac

WAIT=0
while [ "$WAIT" -lt 90 ] && [ ! -f "$SIGNAL" ]; do
    WAIT=$((WAIT + 1))
    sleep 1
done
if [ ! -f "$SIGNAL" ]; then
    log_event "guard=exit reason=current-boot-dispatch-signal-absent action=none"
    exit 0
fi

log_event "guard=start policy=passive-evidence-only route=$ROUTE"
CYCLE=0
while [ "$(getprop "$ROUTE_PROPERTY")" = "$ROUTE" ]; do
    REMAINDER=$((CYCLE % 5))
    if [ "$CYCLE" -lt 30 ] || [ "$REMAINDER" -eq 0 ]; then
        {
            echo "===== cycle=$CYCLE date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) ====="
            echo "route=$(getprop "$ROUTE_PROPERTY") boot_completed=$(getprop sys.boot_completed)"
            echo "--- focus ---"
            dumpsys window windows 2>/dev/null | grep -E "mCurrentFocus|mFocusedApp"
            dumpsys activity activities 2>/dev/null | grep -E "mResumedActivity|mFocusedActivity"
            echo "--- route processes ---"
            ps 2>/dev/null | grep -E "org.rockbox|com.innioasis.y2|systemui" | grep -v grep
        } >> "$LOG"
        chmod 0644 "$LOG"
    fi
    CYCLE=$((CYCLE + 1))
    sleep 1
done
log_event "guard=exit reason=route-changed action=none cycles=$CYCLE"
exit 0
'''


def script_payloads() -> dict[str, bytes]:
    base = recovery_script_data()
    payloads: dict[str, bytes] = {}
    for name, data in base.items():
        text = replace_identity(data.decode("ascii"))
        if name == ROUTE_SCRIPT:
            text = patch_route_script(text)
        elif name == ROUTE_GUARD:
            text = passive_guard()
        elif name == USB_GUARD:
            text = text.replace(
                'log_event "guard=start route=$(getprop $ROUTE_PROPERTY)"',
                'log_event "guard=start role=one-second-fallback-primary-is-direct-manifest-receiver route=$(getprop $ROUTE_PROPERTY)"',
            )
        encoded = text.encode("ascii")
        payloads[name] = encoded if encoded.endswith(b"\n") else encoded + b"\n"
    return payloads


def verify_sources() -> None:
    if not V68_ZIP.is_file() or sha256(V68_ZIP) != V68_ZIP_SHA256:
        raise RuntimeError("V68 base ZIP missing or drifted")
    if not V69_SYSTEM.is_file():
        raise FileNotFoundError(V69_SYSTEM)
    with zipfile.ZipFile(V68_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V68 base ZIP failed CRC verification")
        if any(name not in archive.namelist() for name in FILES):
            raise RuntimeError("V68 base ZIP is incomplete")
    script_payloads()


def compose() -> None:
    verify_sources()
    expected_parent = (ROOT / "12_build_outputs").resolve()
    if OUT.resolve().parent != expected_parent:
        raise RuntimeError(f"Refusing unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(V68_ZIP) as archive:
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V69_SYSTEM, OUT / "system.img")


def patch_recovery() -> dict[str, object]:
    path = OUT / "recovery.img"
    before = path.read_bytes()
    parts = boot_tools.parse_boot_image(before)
    parser = v68.v67.recovery_parser()
    mtk_header, cpio, label = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = boot_tools.parse_cpio_newc(cpio)
    if boot_tools.build_cpio_newc(entries) != cpio:
        raise RuntimeError("V68 recovery CPIO does not round-trip exactly")

    entry_map = {entry["name"]: entry for entry in entries}
    base_payloads = recovery_script_data()
    payloads = script_payloads()
    changes: dict[str, object] = {}
    for name, after_script in payloads.items():
        if name not in entry_map or entry_map[name]["data"] != base_payloads[name]:
            raise RuntimeError(f"Embedded V68 script drifted: {name}")
        entry_map[name]["data"] = after_script
        entry_map[name]["mode"] = 0o100750
        entry_map[name]["mtime"] = CPIO_MTIME
        changes[name] = {
            "before_sha256": sha256_bytes(base_payloads[name]),
            "after_sha256": sha256_bytes(after_script),
            "size": len(after_script),
        }

    patched_cpio = boot_tools.build_cpio_newc(entries)
    patched_ramdisk = boot_tools.build_mtk_ramdisk(mtk_header, patched_cpio)
    after = boot_tools.build_boot_image(parts, patched_ramdisk)
    if len(after) > PARTITION_SIZE:
        raise RuntimeError("V69 recovery exceeds its 16 MiB partition")
    path.write_bytes(after)

    final_parts = boot_tools.parse_boot_image(after)
    _, final_cpio, final_label = parser.parse_mtk_ramdisk(final_parts["ramdisk"])
    final_entries = {
        entry["name"]: entry
        for entry in boot_tools.parse_cpio_newc(final_cpio)
    }
    if any(final_entries[name]["data"] != data for name, data in payloads.items()):
        raise RuntimeError("V69 embedded scripts failed post-repack verification")
    if final_parts["kernel"] != parts["kernel"] or final_label != label:
        raise RuntimeError("V69 recovery kernel or MediaTek label changed")
    return {
        "before_sha256": sha256_bytes(before),
        "after_sha256": sha256_bytes(after),
        "size": len(after),
        "partition_limit": PARTITION_SIZE,
        "kernel_unchanged": True,
        "changed_cpio_entries": sorted(payloads),
        "scripts": changes,
    }


def write_reports(recovery_patch: dict[str, object]) -> dict[str, object]:
    with zipfile.ZipFile(V68_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
    files = {}
    for name in FILES:
        output_hash = sha256(OUT / name)
        files[name] = {
            "size": (OUT / name).stat().st_size,
            "sha256": output_hash,
            "v68_sha256": base_hashes[name],
            "matches_v68": output_hash == base_hashes[name],
        }

    manifest = {
        "build": "y2-v69-route-ownership",
        "status": "root-cause ownership candidate; physical validation required",
        "created_utc": BUILD_TIMESTAMP_UTC,
        "base": {
            "zip": str(V68_ZIP.relative_to(ROOT)),
            "sha256": V68_ZIP_SHA256,
            "physical_result": (
                "Stock baseline and stable Rockbox operation passed, but boot and USB "
                "return exposed vendor HOME/scan windows, surface gaps, and a delayed "
                "SystemUI USB activity."
            ),
        },
        "root_causes": {
            "boot": (
                "The stock HOME and BootCompletedReceiver gained focus after the early "
                "Rockbox launch; the old guard reacted only after their windows existed."
            ),
            "usb_return": (
                "The vendor SDReceiver started DatabaseRefreshService for each remounted "
                "volume while the activity, service, and shell guard independently "
                "restarted Rockbox."
            ),
            "artifacts": (
                "Stale display rows occurred during SurfaceFlinger ownership gaps, before "
                "or after Rockbox owned a surface; Rockbox redraw changes could not cover "
                "a window it did not own."
            ),
            "usb_prompt": (
                "A one-second shell polling loop launched SystemUI only after the cable "
                "broadcast and shell startup delay."
            ),
            "centre_wake": (
                "The built-in mtk-tpd raw key 28 mapped to ENTER without WAKE_DROPPED, "
                "so PhoneWindowManager recorded isWakeKey=false while asleep."
            ),
        },
        "behavior_delta": [
            "A separate-process system overlay owns boot and USB-return visibility until a real Rockbox framebuffer frame is posted.",
            "The vendor BootCompletedReceiver and SDReceiver are restored on every boot, then disabled only on the Rockbox route; the stock launcher and database service remain installed.",
            "One Java coordinator waits for Android boot completion or both mounted volumes and launches Rockbox once; the shell guard is passive evidence only.",
            "The manifest USB receiver starts SystemUI UsbStorageActivity directly; the one-second shell loop remains fallback only.",
            "Device-specific mtk-tpd keylayouts map center ENTER as WAKE_DROPPED for device-wide wake-policy handling.",
        ],
        "database_contract": (
            "The suppressed Innioasis scan is only the stock launcher's catalog. Rockbox "
            "Files and Rockbox tagcache remain independent. On a stock-route boot, both "
            "vendor receivers are restored before normal stock operation."
        ),
        "update_architecture": {
            "name": "Rockbox port with a firmware-integration patch; packaged together as custom firmware",
            "layers": [
                "verified official stock/vendor base",
                "versioned Y2 boot, keylayout, route-owner, and recovery integration",
                "independently replaceable Rockbox APK/native/runtime payload",
                "persistent user themes, settings, and databases on data/storage",
            ],
        },
        "boot_customization_contract": (
            "Changing the default route or artwork on V68 would preserve its failures. "
            "After V69 ownership is physically proven, no-button Rockbox selection and "
            "custom boot art attach to the route shield and do not change stock or "
            "Rockbox update boundaries."
        ),
        "next_test": [
            "Cold Rockbox boot: no stock root, scan popup, black ownership gap, or top-row artifact.",
            "USB plug: storage screen target under one second; export/eject/disable returns directly to the persisted theme with no stock window.",
            "Device-wide center wake: from stock, USB UI, and Rockbox, center wakes the display in under one second; recheck sleep/wake, power menu, playback, volume, theme persistence, and a following stock boot.",
        ],
        "firmware_delta": (
            "Only recovery.img and system.img differ from V68. LK, boot.img, userdata, "
            "stock APK, recovery kernel/init/environment, and V65 native playback "
            "libraries remain unchanged."
        ),
        "recovery_image": recovery_patch,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    (OUT / REPORT_JSON).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / REPORT_MD).write_text(
        "# Y2 V69 Route Ownership Candidate\n\n"
        "V69 replaces reactive foreground recovery with one shielded boot/USB "
        "coordinator and exact Rockbox-route isolation of the two vendor popup "
        "producers. It also adds direct USB UI launch and device-specific center "
        "wake policy.\n\n"
        "This is a physical-test candidate, not a release claim. Use only the "
        "complete ZIP with Download Only. Never use Format All.\n",
        encoding="utf-8",
    )
    return manifest


def write_zip() -> None:
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted((*FILES, REPORT_JSON, REPORT_MD)):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())


def main() -> None:
    compose()
    recovery_patch = patch_recovery()
    manifest = write_reports(recovery_patch)
    write_zip()
    zip_hash = sha256(ZIP)
    ZIP_SHA.write_text(f"{zip_hash} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(ZIP.relative_to(ROOT)),
        "size": ZIP.stat().st_size,
        "sha256": zip_hash,
        "changed_firmware_members": [
            name for name, item in manifest["files"].items()
            if not item["matches_v68"]
        ],
        "recovery": recovery_patch,
    }, indent=2))


if __name__ == "__main__":
    main()
