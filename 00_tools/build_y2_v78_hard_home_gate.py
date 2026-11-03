#!/usr/bin/env python3
"""Build V78: exclusive system HOME router and active Stock reclaim gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v77-release-day-gate.zip"
BASE_SHA256 = "891985DFBF52F9018B14FB98C1DBD7EF6BD3C298FC6892336713850F014067F2"
V78_SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v78-hard-home-gate" / "system.img"
OUT = E_ROOT / "y2-v78-hard-home-gate"
ZIP = E_ROOT / "y2-v78-hard-home-gate.zip"
ZIP_SHA = E_ROOT / "y2-v78-hard-home-gate.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 24, 8, 0, 0)
CPIO_MTIME = 1784872800
PARTITION_SIZE = 16 * 1024 * 1024


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v77 = load("v77_builder_base", ROOT / "00_tools" /
           "build_y2_v77_release_day_gate.py")
FILES = v77.FILES
ROUTE_SCRIPT = v77.ROUTE_SCRIPT
ROUTE_GUARD = v77.v76.ROUTE_GUARD
USB_GUARD = v77.USB_GUARD


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


def rename_v78(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v77-release-day-gate", "y2-v78-hard-home-gate")
    text = text.replace("Y2_V77_DEBUG", "Y2_V78_DEBUG")
    text = text.replace("y2_v77_", "y2_v78_")
    text = text.replace("Y2 V77", "Y2 V78")
    return text.encode("ascii")


def v78_route_script(data: bytes) -> bytes:
    text = rename_v78(data).decode("ascii")

    declaration = (
        'COMPONENT_POLICY_LOG="$OUT/11-stock-component-policy.txt"\n'
        'STOCK_BOOT_RECEIVER="com.innioasis.y2/'
        'com.innioasis.y1.receiver.BootCompletedReceiver"\n'
        'STOCK_SD_RECEIVER="com.innioasis.y2/'
        'com.innioasis.y1.receiver.SDReceiver"\n'
    )
    replacement = declaration + (
        'STOCK_HOME_ACTIVITY="com.innioasis.y2/'
        'com.innioasis.y1.activity.SplashActivity"\n'
        'STOCK_MAIN_ACTIVITY="com.innioasis.y2/'
        'com.innioasis.y1.activity.MainActivity"\n'
        'ROUTER_HOME_ACTIVITY="org.rockbox/.Y2FirmwareHomeActivity"\n'
    )
    if text.count(declaration) != 1:
        raise RuntimeError("V78 component declaration anchor drifted")
    text = text.replace(declaration, replacement)

    old_policy = r'''        {
            echo "build=$BUILD"
            echo "route=$ROUTE"
            echo "policy=restore-on-every-boot-then-isolate-only-popup-producing-receivers-on-rockbox"
            echo "readiness_attempt=$READINESS_ATTEMPT"
            echo "date=$(date 2>/dev/null)"
            echo "uptime=$(cat /proc/uptime 2>/dev/null)"
            echo "--- fail-safe restore ---"
            pm enable "$STOCK_BOOT_RECEIVER" 2>&1
            pm enable "$STOCK_SD_RECEIVER" 2>&1
            if [ "$ROUTE" != "stock" ]; then
                echo "--- Rockbox-route isolation before mount/boot broadcasts ---"
                pm disable "$STOCK_BOOT_RECEIVER" 2>&1
                pm disable "$STOCK_SD_RECEIVER" 2>&1
            fi
            echo "--- exact package state ---"
            dumpsys package "$STOCK_PACKAGE" 2>&1 | grep -E \
                "BootCompletedReceiver|SDReceiver|enabledComponents|disabledComponents"
        } > "$COMPONENT_POLICY_LOG"
'''
    new_policy = r'''        {
            echo "build=$BUILD"
            echo "route=$ROUTE"
            echo "policy=exclusive-router-home-plus-route-controlled-stock-activity-gate"
            echo "readiness_attempt=$READINESS_ATTEMPT"
            echo "date=$(date 2>/dev/null)"
            echo "uptime=$(cat /proc/uptime 2>/dev/null)"
            echo "--- apply only the components required by the selected route ---"
            pm enable "$ROUTER_HOME_ACTIVITY" 2>&1
            if [ "$ROUTE" = "stock" ]; then
                echo "--- selected Stock route: restore complete Stock HOME ---"
                pm enable "$STOCK_BOOT_RECEIVER" 2>&1
                pm enable "$STOCK_SD_RECEIVER" 2>&1
                pm enable "$STOCK_HOME_ACTIVITY" 2>&1
                pm enable "$STOCK_MAIN_ACTIVITY" 2>&1
            else
                echo "--- exclusive non-stock HOME gate before Android HOME settles ---"
                pm disable "$STOCK_BOOT_RECEIVER" 2>&1
                pm disable "$STOCK_SD_RECEIVER" 2>&1
                pm disable "$STOCK_HOME_ACTIVITY" 2>&1
                pm disable "$STOCK_MAIN_ACTIVITY" 2>&1
                am force-stop "$STOCK_PACKAGE" 2>&1
            fi
            echo "--- exact router and Stock component state ---"
            dumpsys package org.rockbox 2>&1 | grep -E \
                "Y2FirmwareHomeActivity|enabledComponents|disabledComponents"
            dumpsys package "$STOCK_PACKAGE" 2>&1 | grep -E \
                "BootCompletedReceiver|SDReceiver|SplashActivity|MainActivity|enabledComponents|disabledComponents"
        } > "$COMPONENT_POLICY_LOG"
'''
    if text.count(old_policy) != 1:
        raise RuntimeError("V78 component policy anchor drifted")
    text = text.replace(old_policy, new_policy)

    stock_case = '''    *)
        TARGET_PACKAGE=""
        TARGET_CLASS=""
        TARGET_COMPONENT=""
        ;;
'''
    stock_replacement = '''    stock)
        TARGET_PACKAGE="com.innioasis.y2"
        TARGET_CLASS="MainActivity"
        TARGET_COMPONENT="com.innioasis.y2/com.innioasis.y1.activity.MainActivity"
        ;;
    *)
        TARGET_PACKAGE=""
        TARGET_CLASS=""
        TARGET_COMPONENT=""
        ;;
'''
    if text.count(stock_case) != 1:
        raise RuntimeError("V78 target case anchor drifted")
    text = text.replace(stock_case, stock_replacement)

    old_dispatch = r'''DISPATCH_OK=0
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
'''
    new_dispatch = r'''DISPATCH_OK=0
DISPATCH_PHASE="root-exclusive-home-gate"
TOTAL_DISPATCH_ATTEMPT=0
while [ "$TOTAL_DISPATCH_ATTEMPT" -lt 90 ]; do
    TEMP_RESULT="$OUT/.activity-result-$TOTAL_DISPATCH_ATTEMPT.txt"
    am start -W -n "$BOOTSTRAP_COMPONENT" --es physical_route "$PHYSICAL_ROUTE" --es route "$ROUTE" > "$TEMP_RESULT" 2>&1
    WRAPPER_RESULT=$?
    HAS_EXPECTED_ACTIVITY=0
    HAS_ERROR=0
    if grep -F "Activity: $BOOTSTRAP_COMPONENT" "$TEMP_RESULT" >/dev/null 2>&1 || \
       { [ -n "$TARGET_COMPONENT" ] && grep -F "Activity: $TARGET_COMPONENT" "$TEMP_RESULT" >/dev/null 2>&1; } || \
       { [ "$ROUTE" = "stock" ] && grep -F "Activity: com.innioasis.y2/com.innioasis.y1.activity.SplashActivity" "$TEMP_RESULT" >/dev/null 2>&1; }; then
        HAS_EXPECTED_ACTIVITY=1
    fi
    if grep -E "Error:|Exception|Permission Denial|does not exist" "$TEMP_RESULT" >/dev/null 2>&1; then
        HAS_ERROR=1
    fi
    {
        echo "dispatch_phase=$DISPATCH_PHASE total_attempt=$TOTAL_DISPATCH_ATTEMPT wrapper_result=$WRAPPER_RESULT has_expected_activity=$HAS_EXPECTED_ACTIVITY has_error=$HAS_ERROR date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null)"
        cat "$TEMP_RESULT"
    } >> "$OUT/08-route-dispatch.txt"
    if [ "$WRAPPER_RESULT" -eq 0 ] && [ "$HAS_EXPECTED_ACTIVITY" -eq 1 ] && [ "$HAS_ERROR" -eq 0 ]; then
        DISPATCH_OK=1
        rm -f "$TEMP_RESULT"
        break
    fi
    if [ "$ROUTE" != "stock" ]; then
        pm disable "$STOCK_HOME_ACTIVITY" >> "$OUT/08-route-dispatch.txt" 2>&1
        pm disable "$STOCK_MAIN_ACTIVITY" >> "$OUT/08-route-dispatch.txt" 2>&1
        am force-stop "$STOCK_PACKAGE" >> "$OUT/08-route-dispatch.txt" 2>&1
        echo "repair=stock-foreground-rejected action=disable-force-stop-and-retry" >> "$OUT/08-route-dispatch.txt"
    fi
    rm -f "$TEMP_RESULT"
    copy_all_storage small
    TOTAL_DISPATCH_ATTEMPT=$((TOTAL_DISPATCH_ATTEMPT + 1))
    sleep 1
done
'''
    if text.count(old_dispatch) != 1:
        raise RuntimeError("V78 dispatch anchor drifted")
    text = text.replace(old_dispatch, new_dispatch)
    return text.encode("ascii")


def v78_route_guard(_: bytes) -> bytes:
    return r'''#!/system/bin/sh

BUILD="y2-v78-hard-home-gate"
DATA_ROOT="/data/local/tmp/Y2_V78_DEBUG"
ROUTE_PROPERTY="y2.firmware.route"
STOCK_PACKAGE="com.innioasis.y2"
STOCK_HOME="com.innioasis.y2/com.innioasis.y1.activity.SplashActivity"
STOCK_MAIN="com.innioasis.y2/com.innioasis.y1.activity.MainActivity"
ROUTER_HOME="org.rockbox/.Y2FirmwareHomeActivity"

mkdir -p "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if [ -z "$BOOT_ID" ]; then
    BOOT_ID="noid"
fi
PHYSICAL_ROUTE=$(getprop "$ROUTE_PROPERTY")
ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
ROUTE_WAIT=0
while [ "$ROUTE_WAIT" -lt 90 ] && [ ! -f "$ROUTE_FILE" ]; do
    ROUTE_WAIT=$((ROUTE_WAIT + 1))
    sleep 1
done
ROUTE=$(grep '^route=' "$ROUTE_FILE" 2>/dev/null | head -n 1 | cut -d= -f2)
LOG="$DATA_ROOT/guard-$BOOT_ID-$ROUTE.txt"
SIGNAL="$DATA_ROOT/route-dispatched-$BOOT_ID-$ROUTE.txt"

log_event() {
    echo "build=$BUILD date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) $*" >> "$LOG"
    chmod 0644 "$LOG"
}

case "$ROUTE" in
    rockbox|settings) ;;
    *)
        log_event "guard=exit reason=stock-or-unsupported-route route=$ROUTE action=none"
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

log_event "guard=start policy=active-exclusive-home-repair route=$ROUTE physical_route=$PHYSICAL_ROUTE"
CYCLE=0
REPAIRS=0
while [ "$(getprop "$ROUTE_PROPERTY")" = "$PHYSICAL_ROUTE" ]; do
    FOCUS=$(dumpsys activity activities 2>/dev/null | grep -E "mResumedActivity|mFocusedActivity" | head -n 4)
    if echo "$FOCUS" | grep -F "$STOCK_PACKAGE/" >/dev/null 2>&1; then
        REPAIRS=$((REPAIRS + 1))
        log_event "event=stock-foreground-violation repair=$REPAIRS action=disable-force-stop-router-reassert"
        echo "$FOCUS" >> "$LOG"
        pm disable "$STOCK_HOME" >> "$LOG" 2>&1
        pm disable "$STOCK_MAIN" >> "$LOG" 2>&1
        am force-stop "$STOCK_PACKAGE" >> "$LOG" 2>&1
        am start -W -n "$ROUTER_HOME" --es physical_route "$PHYSICAL_ROUTE" --es route "$ROUTE" >> "$LOG" 2>&1
        chmod 0644 "$LOG"
    fi
    REMAINDER=$((CYCLE % 15))
    if [ "$CYCLE" -lt 30 ] || [ "$REMAINDER" -eq 0 ]; then
        {
            echo "===== cycle=$CYCLE repairs=$REPAIRS date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) ====="
            echo "physical_route=$(getprop "$ROUTE_PROPERTY") route=$ROUTE boot_completed=$(getprop sys.boot_completed)"
            echo "$FOCUS"
        } >> "$LOG"
        chmod 0644 "$LOG"
    fi
    CYCLE=$((CYCLE + 1))
    sleep 1
done
log_event "guard=exit reason=route-changed cycles=$CYCLE repairs=$REPAIRS"
exit 0
'''.encode("ascii")


def scripts() -> dict[str, bytes]:
    entries, *_ = v77.v76.ramdisk(base_image("recovery.img"))
    source = {entry["name"]: entry["data"] for entry in entries}
    result: dict[str, bytes] = {}
    for name in v77.v76.v75.v74.SCRIPT_NAMES:
        if name == ROUTE_SCRIPT:
            result[name] = v78_route_script(source[name])
        elif name == ROUTE_GUARD:
            result[name] = v78_route_guard(source[name])
        else:
            result[name] = rename_v78(source[name])
    result[USB_GUARD] = rename_v78(source[USB_GUARD])
    return result


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V77 base is missing or drifted")
    if not V78_SYSTEM.is_file():
        raise FileNotFoundError(V78_SYSTEM)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V77 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V77 base ZIP incomplete: {missing}")


NORMAL_GUARD_SERVICE = '''# Y2 V78: the no-button physical path can map to
# Rockbox or Boot Settings, so it requires the same active HOME repair guard.
service y2v40routeguard /system/bin/sh /sbin/y2v40routeguard.sh
    class late_start
    user root
    group root shell log system sdcard_r sdcard_rw media_rw
    disabled
    oneshot
    seclabel u:r:init_shell:s0
'''


def ensure_normal_route_guard(patch_report: dict[str, object]) -> dict[str, object]:
    path = OUT / "boot.img"
    before = path.read_bytes()
    entries, parts, mtk_header, label = v77.v76.ramdisk(before)
    entry_map = {entry["name"]: entry for entry in entries}
    init = entry_map["init.rc"]["data"].decode("ascii")
    trigger = 'on post-fs-data\n    start y2v36stockroute\n'
    replacement = trigger + '    start y2v40routeguard\n'
    if init.count(trigger) != 1:
        raise RuntimeError("V78 normal route-guard trigger anchor drifted")
    if "service y2v40routeguard " in init:
        raise RuntimeError("V78 normal route-guard service unexpectedly pre-exists")
    init = init.replace(trigger, replacement)
    init = init.rstrip() + "\n\n" + NORMAL_GUARD_SERVICE
    entry_map["init.rc"]["data"] = init.encode("ascii")
    entry_map["init.rc"]["mtime"] = CPIO_MTIME
    built_cpio = v77.v76.boot_tools.build_cpio_newc(entries)
    built_ramdisk = v77.v76.boot_tools.build_mtk_ramdisk(
        mtk_header, built_cpio)
    after = v77.v76.boot_tools.build_boot_image(parts, built_ramdisk)
    if len(after) > PARTITION_SIZE:
        raise RuntimeError("boot.img exceeds partition after normal guard install")
    path.write_bytes(after)

    final_entries, final_parts, _, final_label = v77.v76.ramdisk(after)
    final = {entry["name"]: entry["data"] for entry in final_entries}
    final_init = final["init.rc"]
    if (b'on post-fs-data\n    start y2v36stockroute\n'
            b'    start y2v40routeguard\n' not in final_init
            or b'service y2v40routeguard ' not in final_init):
        raise RuntimeError("V78 normal route guard failed round-trip validation")
    if final_parts["kernel"] != parts["kernel"] or final_label != label:
        raise RuntimeError("V78 normal route guard changed kernel or MTK label")
    patch_report["after"] = sha256_bytes(after)
    patch_report["normal_route_guard_registered"] = True
    return patch_report


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v78-hard-home-gate":
        raise RuntimeError(f"Unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V78_SYSTEM, OUT / "system.img")

    payloads = scripts()
    v77.v76.OUT = OUT
    v77.v76.CPIO_MTIME = CPIO_MTIME
    image_patches = {
        name: v77.v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }
    image_patches["boot.img"] = ensure_normal_route_guard(
        image_patches["boot.img"])
    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v77_sha256": base_hashes[name],
            "matches_v77": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [name for name in FILES if not files[name]["matches_v77"]]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V78 partition delta: {changed}")

    manifest = {
        "build": "y2-v78-hard-home-gate",
        "status": "offline validated; physical route gate required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v77_evidence": {
            "capture": r"E:\Y2-RockBox-evidence\v77-physical-home-gate-failure-20260724",
            "finding": (
                "Root am start returned Status: ok while the actual Activity was "
                "Stock MainActivity; V77 had no Android HOME intent filter."
            ),
        },
        "behavior_delta": [
            "Y2FirmwareHomeActivity is a real persistent Android HOME router.",
            "The system app pins that router as preferred HOME without a chooser.",
            "Stock SplashActivity and MainActivity are disabled and force-stopped on non-stock routes.",
            "Root dispatch rejects Status: ok unless the returned Activity is the selected route.",
            "An active root watchdog repairs any later Stock foreground violation.",
            "Stock route restores Stock components and is launched through the same router.",
        ],
        "branding_unchanged": True,
        "haptic_unchanged": True,
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    report_json = "y2-v78-hard-home-gate.json"
    report_md = "y2-v78-hard-home-gate.md"
    test_txt = "V78-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / report_md).write_text(
        "# Y2 V78 Hard HOME Gate\n\n"
        "V78 replaces V77's foreground handoff with a real, preferred Android "
        "HOME router plus root component isolation and active reclaim repair.\n",
        encoding="utf-8")
    (OUT / test_txt).write_text(
        "Y2 V78 HARD HOME GATE TEST\n"
        "1. Flash the complete package using Download Only. NEVER Format All.\n"
        "2. No button: Rockbox must appear with no chooser and no Stock UI.\n"
        "3. Sleep five minutes; power and centre wake must return to Rockbox, never Stock.\n"
        "4. Volume Up: Y2 Stock must open cleanly and remain foreground.\n"
        "5. Volume Down: Boot Settings must open cleanly and remain foreground.\n"
        "6. Repeat no-button, Volume Up, and Volume Down once each.\n"
        "7. Only after all six boots pass, test USB export and both return paths.\n"
        "8. Power off before returning the SD card for V78 diagnostics.\n",
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
            raise RuntimeError("V78 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(f"{digest} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(ZIP),
        "size": ZIP.stat().st_size,
        "sha256": digest,
        "changed_from_v77": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
