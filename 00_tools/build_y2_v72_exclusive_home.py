#!/usr/bin/env python3
"""Build V72: make the LK-selected UI the sole HOME after Android boot completes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v71-wake-owner.zip"
BASE_SHA256 = "7666B9285EEB680AFACB78A559D0FCEF54A67F3A39FB19A523914873D630863B"
SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v72-exclusive-home" / "system.img"
OUT = E_ROOT / "y2-v72-exclusive-home"
ZIP = E_ROOT / "y2-v72-exclusive-home.zip"
ZIP_SHA = E_ROOT / "y2-v72-exclusive-home.zip.sha256.txt"
REPORT_JSON = "y2-v72-exclusive-home.json"
REPORT_MD = "y2-v72-exclusive-home.md"
ROUTE_SCRIPT = "sbin/y2v36route.sh"
ZIP_TIMESTAMP = (2026, 7, 21, 23, 30, 0)
PARTITION_SIZE = 16 * 1024 * 1024


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v69 = load_module("v69_home_base", ROOT / "00_tools" / "build_y2_v69_route_ownership.py")
boot_tools = v69.boot_tools
parser = v69.v68.v67.recovery_parser()
FILES = v69.FILES


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
        raise RuntimeError(f"V72 {label} anchor count is {text.count(before)}, expected 1")
    return text.replace(before, after, 1)


def patch_route_script(text: str) -> str:
    text = text.replace('BUILD="y2-v69-route-ownership"', 'BUILD="y2-v72-exclusive-home"', 1)
    text = replace_once(
        text,
        'STOCK_PACKAGE="com.innioasis.y2"\n',
        'STOCK_PACKAGE="com.innioasis.y2"\n'
        'STOCK_HOME="com.innioasis.y2/com.innioasis.y1.activity.SplashActivity"\n'
        'ROCKBOX_HOME="org.rockbox/.RockboxActivity"\n'
        'SETTINGS_HOME="org.rockbox/.Y2BootSettingsActivity"\n',
        "HOME component declarations",
    )

    start = text.index('    if [ "$PACKAGE_SERVICE" -eq 1 ] &&\n')
    end = text.index('    if service check activity', start)
    old_policy = text[start:end]
    if 'COMPONENT_POLICY_APPLIED' not in old_policy or 'STOCK_SD_RECEIVER' not in old_policy:
        raise RuntimeError("V72 component-policy block drifted")
    new_policy = r'''    if [ "$PACKAGE_SERVICE" -eq 1 ] &&
       [ "$COMPONENT_POLICY_APPLIED" -eq 0 ] &&
       dumpsys package "$STOCK_PACKAGE" 2>/dev/null |
           grep -F "com.innioasis.y1.activity.SplashActivity" >/dev/null 2>&1 &&
       dumpsys package org.rockbox 2>/dev/null |
           grep -F "org.rockbox.RockboxActivity" >/dev/null 2>&1 &&
       dumpsys package org.rockbox 2>/dev/null |
           grep -F "org.rockbox.Y2BootSettingsActivity" >/dev/null 2>&1; then
        {
            echo "build=$BUILD"
            echo "route=$ROUTE"
            echo "policy=restore-stock-fail-safe-then-prepare-one-selected-home"
            echo "readiness_attempt=$READINESS_ATTEMPT"
            echo "date=$(date 2>/dev/null)"
            echo "uptime=$(cat /proc/uptime 2>/dev/null)"
            echo "--- fail-safe package and vendor boot restore ---"
            pm enable "$STOCK_PACKAGE" 2>&1
            pm enable "$STOCK_HOME" 2>&1
            pm enable "$STOCK_BOOT_RECEIVER" 2>&1
            pm enable "$STOCK_SD_RECEIVER" 2>&1
            echo "--- pre-boot route HOME preparation ---"
            case "$ROUTE" in
                rockbox)
                    pm enable "$ROCKBOX_HOME" 2>&1
                    pm disable "$SETTINGS_HOME" 2>&1
                    pm disable "$STOCK_BOOT_RECEIVER" 2>&1
                    pm disable "$STOCK_SD_RECEIVER" 2>&1
                    ;;
                settings)
                    pm disable "$ROCKBOX_HOME" 2>&1
                    pm enable "$SETTINGS_HOME" 2>&1
                    pm disable "$STOCK_BOOT_RECEIVER" 2>&1
                    pm disable "$STOCK_SD_RECEIVER" 2>&1
                    ;;
                *)
                    pm disable "$ROCKBOX_HOME" 2>&1
                    pm disable "$SETTINGS_HOME" 2>&1
                    ;;
            esac
            echo "--- prepared package state ---"
            dumpsys package "$STOCK_PACKAGE" 2>&1 | grep -E \
                "SplashActivity|BootCompletedReceiver|SDReceiver|enabledComponents|disabledComponents"
            dumpsys package org.rockbox 2>&1 | grep -E \
                "RockboxActivity|Y2BootSettingsActivity|enabledComponents|disabledComponents"
        } > "$COMPONENT_POLICY_LOG"
        chmod 0644 "$COMPONENT_POLICY_LOG"
        COMPONENT_POLICY_APPLIED=1
    fi
'''
    text = text[:start] + new_policy + text[end:]

    function_anchor = '''TARGET_FOREGROUND=0
FIRST_TARGET_FOREGROUND_ELAPSED=-1
ELAPSED=0
'''
    function_replacement = r'''commit_exclusive_home() {
    {
        echo "===== exclusive HOME commit ====="
        echo "build=$BUILD route=$ROUTE date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null)"
        echo "boot_completed=$(getprop sys.boot_completed 2>/dev/null)"
        RESULT=0
        case "$ROUTE" in
            rockbox)
                pm enable "$ROCKBOX_HOME" 2>&1 || RESULT=1
                pm disable "$SETTINGS_HOME" 2>&1 || RESULT=1
                pm disable "$STOCK_PACKAGE" 2>&1 || RESULT=1
                am start -a android.intent.action.MAIN \
                    -c android.intent.category.HOME \
                    -n "$ROCKBOX_HOME" 2>&1 || RESULT=1
                ;;
            settings)
                pm disable "$ROCKBOX_HOME" 2>&1 || RESULT=1
                pm enable "$SETTINGS_HOME" 2>&1 || RESULT=1
                pm disable "$STOCK_PACKAGE" 2>&1 || RESULT=1
                am start -a android.intent.action.MAIN \
                    -c android.intent.category.HOME \
                    -n "$SETTINGS_HOME" 2>&1 || RESULT=1
                ;;
            *)
                pm enable "$STOCK_PACKAGE" 2>&1 || RESULT=1
                pm enable "$STOCK_HOME" 2>&1 || RESULT=1
                pm disable "$ROCKBOX_HOME" 2>&1 || RESULT=1
                pm disable "$SETTINGS_HOME" 2>&1 || RESULT=1
                ;;
        esac
        echo "result=$RESULT"
        echo "--- disabled packages ---"
        pm list packages -d 2>&1
        echo "--- stock HOME/package state ---"
        dumpsys package "$STOCK_PACKAGE" 2>&1 | grep -E \
            "SplashActivity|enabledComponents|disabledComponents|User 0"
        echo "--- Rockbox HOME component state ---"
        dumpsys package org.rockbox 2>&1 | grep -E \
            "RockboxActivity|Y2BootSettingsActivity|enabledComponents|disabledComponents|User 0"
    } >> "$COMPONENT_POLICY_LOG"
    chmod 0644 "$COMPONENT_POLICY_LOG"
    if [ "$RESULT" -eq 0 ]; then
        HOME_COMMIT_APPLIED=1
        log_inline "inline=exclusive-home-commit route=$ROUTE result=success"
    else
        log_inline "inline=exclusive-home-commit route=$ROUTE result=retry"
    fi
}

TARGET_FOREGROUND=0
FIRST_TARGET_FOREGROUND_ELAPSED=-1
HOME_COMMIT_APPLIED=0
ELAPSED=0
'''
    text = replace_once(text, function_anchor, function_replacement, "exclusive HOME function")

    loop_anchor = '''while [ "$ELAPSED" -le "$CAPTURE_SECONDS" ]; do
    CURRENT_FOCUS=$(foreground_snapshot)
'''
    loop_replacement = '''while [ "$ELAPSED" -le "$CAPTURE_SECONDS" ]; do
    if [ "$HOME_COMMIT_APPLIED" -eq 0 ] &&
       [ "$(getprop sys.boot_completed 2>/dev/null)" = "1" ]; then
        commit_exclusive_home
    fi
    CURRENT_FOCUS=$(foreground_snapshot)
'''
    text = replace_once(text, loop_anchor, loop_replacement, "boot-complete HOME commit")
    return text


def route_script_from_image(path: Path) -> bytes:
    parts = boot_tools.parse_boot_image(path.read_bytes())
    _, cpio, _ = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = {item["name"]: item for item in boot_tools.parse_cpio_newc(cpio)}
    return entries[ROUTE_SCRIPT]["data"]


def patch_boot_image(path: Path, new_script: bytes) -> dict[str, object]:
    before = path.read_bytes()
    parts = boot_tools.parse_boot_image(before)
    mtk_header, cpio, label = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = boot_tools.parse_cpio_newc(cpio)
    entry = next(item for item in entries if item["name"] == ROUTE_SCRIPT)
    old_script = entry["data"]
    entry["data"] = new_script
    entry["mode"] = 0o100750
    patched_cpio = boot_tools.build_cpio_newc(entries)
    ramdisk = boot_tools.build_mtk_ramdisk(mtk_header, patched_cpio)
    after = boot_tools.build_boot_image(parts, ramdisk)
    if len(after) > PARTITION_SIZE:
        raise RuntimeError(f"{path.name} exceeds its 16 MiB partition")
    path.write_bytes(after)

    check_parts = boot_tools.parse_boot_image(after)
    _, check_cpio, check_label = parser.parse_mtk_ramdisk(check_parts["ramdisk"])
    check_entries = {item["name"]: item for item in boot_tools.parse_cpio_newc(check_cpio)}
    if check_entries[ROUTE_SCRIPT]["data"] != new_script:
        raise RuntimeError(f"{path.name} route script failed round-trip")
    if check_parts["kernel"] != parts["kernel"] or check_label != label:
        raise RuntimeError(f"{path.name} unexpectedly changed kernel or MTK label")
    return {
        "before_sha256": sha256_bytes(before),
        "after_sha256": sha256_bytes(after),
        "kernel_unchanged": True,
        "route_script_before_sha256": sha256_bytes(old_script),
        "route_script_after_sha256": sha256_bytes(new_script),
        "size": len(after),
    }


def main() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("V71 base ZIP missing or drifted")
    if not SYSTEM.is_file():
        raise FileNotFoundError(SYSTEM)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V71 base ZIP failed CRC")
        base = {name: archive.read(name) for name in FILES}
        for name, data in base.items():
            (OUT / name).write_bytes(data)
    shutil.copy2(SYSTEM, OUT / "system.img")
    canonical = route_script_from_image(OUT / "recovery.img")
    patched_script = patch_route_script(canonical.decode("ascii")).encode("ascii")
    if not patched_script.endswith(b"\n"):
        patched_script += b"\n"
    boot_patch = patch_boot_image(OUT / "boot.img", patched_script)
    recovery_patch = patch_boot_image(OUT / "recovery.img", patched_script)

    files = {}
    for name in FILES:
        output_hash = sha256(OUT / name)
        base_hash = sha256_bytes(base[name])
        files[name] = {"size": (OUT / name).stat().st_size, "sha256": output_hash,
                       "v71_sha256": base_hash, "matches_v71": output_hash == base_hash}
    changed = [name for name in FILES if not files[name]["matches_v71"]]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V72 partition delta: {changed}")

    report = {
        "build": "y2-v72-exclusive-home",
        "status": "fixed-map exclusive-HOME architecture candidate; physical validation required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "fixed_route_map": {
            "no_button": "stock HOME",
            "volume_down": "Rockbox HOME",
            "volume_up": "Boot Settings HOME",
            "both_volumes": "fastboot safety route",
        },
        "policy": [
            "Restore the stock package and vendor boot components at the start of every Android boot.",
            "Prepare only the selected Rockbox-package HOME activity before route dispatch.",
            "Do not disable the stock package until sys.boot_completed=1.",
            "After boot completion, make the selected UI the sole eligible HOME and explicitly foreground it.",
            "A following stock boot always re-enables stock before attempting normal stock operation.",
        ],
        "next_stage": (
            "Keep LK's three proven physical slots, persist a validated permutation of "
            "Rockbox/stock/settings, and let each selected ramdisk resolve its slot from that mapping."
        ),
        "boot_patch": boot_patch,
        "recovery_patch": recovery_patch,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    (OUT / REPORT_JSON).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUT / REPORT_MD).write_text(
        "# Y2 V72 Exclusive HOME\n\n"
        "Fixed test map: no key selects stock HOME, Volume Down selects Rockbox HOME, "
        "Volume Up selects Boot Settings HOME, and both volumes retain fastboot. "
        "Stock is restored first on every boot and is disabled on non-stock routes only "
        "after Android reports boot complete. Physical validation is required.\n",
        encoding="utf-8",
    )
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted((*FILES, REPORT_JSON, REPORT_MD)):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())
    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V72 output ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(f"{digest} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(ZIP), "size": ZIP.stat().st_size,
                      "sha256": digest, "changed_from_v71": changed}, indent=2))


if __name__ == "__main__":
    main()
