#!/usr/bin/env python3
"""Build V79: editable boot map, valid-route brokers and one framebuffer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v78-hard-home-gate.zip"
BASE_SHA256 = "55E87D33369FD19C8CDA356B2274D9354D1CA317035BC97F554445BADA81DD98"
V79_SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v79-release-polish" / "system.img"
OUT = E_ROOT / "y2-v79-release-polish"
ZIP = E_ROOT / "y2-v79-release-polish.zip"
ZIP_SHA = E_ROOT / "y2-v79-release-polish.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 24, 13, 0, 0)
CPIO_MTIME = 1784890800


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v78 = load("v78_builder_base", ROOT / "00_tools" /
           "build_y2_v78_hard_home_gate.py")
FILES = v78.FILES
ROUTE_SCRIPT = v78.ROUTE_SCRIPT
ROUTE_GUARD = v78.ROUTE_GUARD
USB_GUARD = v78.USB_GUARD


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


def rename_v79(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v78-hard-home-gate", "y2-v79-release-polish")
    text = text.replace("Y2_V78_DEBUG", "Y2_V79_DEBUG")
    text = text.replace("y2_v78_", "y2_v79_")
    text = text.replace("Y2 V78", "Y2 V79")
    return text.encode("ascii")


def v79_route_script(data: bytes) -> bytes:
    text = rename_v79(data).decode("ascii")
    declaration = (
        'STOCK_SD_RECEIVER="com.innioasis.y2/'
        'com.innioasis.y1.receiver.SDReceiver"\n'
    )
    replacement = declaration + (
        'STOCK_PLAY_RECEIVER="com.innioasis.y2/'
        'com.innioasis.y1.ui.receiver.PlayControllerReceiver"\n'
    )
    if text.count(declaration) != 1:
        raise RuntimeError("V79 Stock play receiver declaration anchor drifted")
    text = text.replace(declaration, replacement)
    stock_enable = '                pm enable "$STOCK_SD_RECEIVER" 2>&1\n'
    nonstock_disable = '                pm disable "$STOCK_SD_RECEIVER" 2>&1\n'
    if text.count(stock_enable) != 1 or text.count(nonstock_disable) != 1:
        raise RuntimeError("V79 Stock receiver policy anchors drifted")
    text = text.replace(
        stock_enable,
        stock_enable + '                pm enable "$STOCK_PLAY_RECEIVER" 2>&1\n')
    text = text.replace(
        nonstock_disable,
        nonstock_disable
        + '                pm disable "$STOCK_PLAY_RECEIVER" 2>&1\n')
    text = text.replace(
        '"BootCompletedReceiver|SDReceiver|SplashActivity|MainActivity|enabledComponents|disabledComponents"',
        '"BootCompletedReceiver|SDReceiver|PlayControllerReceiver|SplashActivity|MainActivity|enabledComponents|disabledComponents"',
    )
    return text.encode("ascii")


def v79_route_guard() -> bytes:
    return r'''#!/system/bin/sh

BUILD="y2-v79-release-polish"
DATA_ROOT="/data/local/tmp/Y2_V79_DEBUG"
ROUTE_PROPERTY="y2.firmware.route"
STOCK_PACKAGE="com.innioasis.y2"
STOCK_HOME="com.innioasis.y2/com.innioasis.y1.activity.SplashActivity"
STOCK_MAIN="com.innioasis.y2/com.innioasis.y1.activity.MainActivity"
STOCK_PLAY="com.innioasis.y2/com.innioasis.y1.ui.receiver.PlayControllerReceiver"
ROUTER_HOME="org.rockbox/.Y2FirmwareHomeActivity"
SETTINGS_REQUEST="/data/data/org.rockbox/files/y2_boot_routes.request"
ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"

mkdir -p "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if [ -z "$BOOT_ID" ]; then
    BOOT_ID="noid"
fi
PHYSICAL_ROUTE=$(getprop "$ROUTE_PROPERTY")
ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
ROUTE=""
ROUTE_WAIT=0
while [ "$ROUTE_WAIT" -lt 90 ]; do
    ROUTE=$(grep '^route=' "$ROUTE_FILE" 2>/dev/null | head -n 1 | cut -d= -f2)
    case "$ROUTE" in
        rockbox|stock|settings) break ;;
    esac
    ROUTE=""
    ROUTE_WAIT=$((ROUTE_WAIT + 1))
    sleep 1
done
LOG="$DATA_ROOT/guard-$BOOT_ID-$ROUTE.txt"
SIGNAL="$DATA_ROOT/route-dispatched-$BOOT_ID-$ROUTE.txt"

log_event() {
    echo "build=$BUILD date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) $*" >> "$LOG"
    chmod 0644 "$LOG"
}

case "$ROUTE" in
    rockbox|settings) ;;
    *)
        log_event "guard=exit reason=stock-or-unsupported-route route=$ROUTE route_wait=$ROUTE_WAIT action=none"
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

process_settings_request() {
    if [ "$ROUTE" != "settings" ] || [ ! -f "$SETTINGS_REQUEST" ]; then
        return
    fi
    if grep '^status=' "$SETTINGS_REQUEST" >/dev/null 2>&1; then
        return
    fi
    REQUEST_VERSION=$(grep '^request_version=' "$SETTINGS_REQUEST" 2>/dev/null | head -n 1 | cut -d= -f2)
    REQUEST_ID=$(grep '^request_id=' "$SETTINGS_REQUEST" 2>/dev/null | head -n 1 | cut -d= -f2)
    REQUEST_NO=$(grep '^no_button=' "$SETTINGS_REQUEST" 2>/dev/null | head -n 1 | cut -d= -f2)
    REQUEST_UP=$(grep '^volume_up=' "$SETTINGS_REQUEST" 2>/dev/null | head -n 1 | cut -d= -f2)
    REQUEST_DOWN=$(grep '^volume_down=' "$SETTINGS_REQUEST" 2>/dev/null | head -n 1 | cut -d= -f2)
    REQUEST_REBOOT=$(grep '^reboot=' "$SETTINGS_REQUEST" 2>/dev/null | head -n 1 | cut -d= -f2)
    REQUEST_VALID=1
    [ "$REQUEST_VERSION" = "1" ] || REQUEST_VALID=0
    echo "$REQUEST_ID" | grep -E '^[0-9]+$' >/dev/null 2>&1 || REQUEST_VALID=0
    for REQUEST_VALUE in "$REQUEST_NO" "$REQUEST_UP" "$REQUEST_DOWN"; do
        case "$REQUEST_VALUE" in
            rockbox|stock|settings) ;;
            *) REQUEST_VALID=0 ;;
        esac
    done
    if [ "$REQUEST_NO" = "$REQUEST_UP" ] ||
       [ "$REQUEST_NO" = "$REQUEST_DOWN" ] ||
       [ "$REQUEST_UP" = "$REQUEST_DOWN" ]; then
        REQUEST_VALID=0
    fi
    if [ "$REQUEST_NO" != "settings" ] &&
       [ "$REQUEST_UP" != "settings" ] &&
       [ "$REQUEST_DOWN" != "settings" ]; then
        REQUEST_VALID=0
    fi
    if [ "$REQUEST_VALID" -ne 1 ]; then
        printf '%s\n' "request_id=$REQUEST_ID" "status=error-invalid-permutation" > "$SETTINGS_REQUEST"
        log_event "settings_broker=rejected request_id=$REQUEST_ID reason=invalid-permutation"
        return
    fi
    ROUTE_MAP_TMP="$ROUTE_MAP_FILE.tmp"
    if umask 077 &&
       printf '%s\n' 'version=1' "no_button=$REQUEST_NO" \
           "volume_up=$REQUEST_UP" "volume_down=$REQUEST_DOWN" > "$ROUTE_MAP_TMP" &&
       chmod 0600 "$ROUTE_MAP_TMP" &&
       mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"; then
        printf '%s\n' "request_id=$REQUEST_ID" "status=ok" > "$SETTINGS_REQUEST"
        sync
        log_event "settings_broker=saved request_id=$REQUEST_ID no_button=$REQUEST_NO volume_up=$REQUEST_UP volume_down=$REQUEST_DOWN unchanged_allowed=yes"
        if [ "$REQUEST_REBOOT" = "1" ]; then
            sleep 1
            log_event "settings_broker=reboot request_id=$REQUEST_ID"
            reboot
        fi
    else
        rm -f "$ROUTE_MAP_TMP"
        printf '%s\n' "request_id=$REQUEST_ID" "status=error-write-failed" > "$SETTINGS_REQUEST"
        log_event "settings_broker=rejected request_id=$REQUEST_ID reason=write-failed"
    fi
}

log_event "guard=start policy=active-exclusive-home-repair route=$ROUTE physical_route=$PHYSICAL_ROUTE route_wait=$ROUTE_WAIT settings_broker=$([ "$ROUTE" = "settings" ] && echo active || echo inactive)"
CYCLE=0
REPAIRS=0
while [ "$(getprop "$ROUTE_PROPERTY")" = "$PHYSICAL_ROUTE" ]; do
    process_settings_request
    FOCUS=$(dumpsys activity activities 2>/dev/null | grep -E "mResumedActivity|mFocusedActivity" | head -n 4)
    if echo "$FOCUS" | grep -F "$STOCK_PACKAGE/" >/dev/null 2>&1; then
        REPAIRS=$((REPAIRS + 1))
        log_event "event=stock-foreground-violation repair=$REPAIRS action=disable-force-stop-router-reassert"
        echo "$FOCUS" >> "$LOG"
        pm disable "$STOCK_HOME" >> "$LOG" 2>&1
        pm disable "$STOCK_MAIN" >> "$LOG" 2>&1
        pm disable "$STOCK_PLAY" >> "$LOG" 2>&1
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


def v79_usb_guard() -> bytes:
    return r'''#!/system/bin/sh

BUILD="y2-v79-release-polish"
DATA_ROOT="/data/local/tmp/Y2_V79_DEBUG"
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

ROUTE=""
WAIT=0
while [ "$WAIT" -lt 180 ]; do
    ROUTE=$(grep '^route=' "$ROUTE_FILE" 2>/dev/null | head -n 1 | cut -d= -f2)
    case "$ROUTE" in
        rockbox|stock|settings) break ;;
    esac
    ROUTE=""
    WAIT=$((WAIT + 1))
    sleep 1
done
if [ "$ROUTE" != "rockbox" ]; then
    log_event "broker=exit reason=effective-route-not-rockbox route=$ROUTE route_wait=$WAIT route_file=$ROUTE_FILE"
    exit 0
fi

LAST_STATE="unknown"
PROMPTED=0
log_event "broker=start route=$ROUTE route_wait=$WAIT authority=root-init-shell activity=$USB_ACTIVITY"
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
    entries, *_ = v78.v77.v76.ramdisk(base_image("recovery.img"))
    source = {entry["name"]: entry["data"] for entry in entries}
    result: dict[str, bytes] = {}
    for name in v78.v77.v76.v75.v74.SCRIPT_NAMES:
        if name == ROUTE_SCRIPT:
            result[name] = v79_route_script(source[name])
        elif name == ROUTE_GUARD:
            result[name] = v79_route_guard()
        elif name == USB_GUARD:
            result[name] = v79_usb_guard()
        else:
            result[name] = rename_v79(source[name])
    result[USB_GUARD] = v79_usb_guard()
    return result


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V78 base is missing or drifted")
    if not V79_SYSTEM.is_file():
        raise FileNotFoundError(V79_SYSTEM)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V78 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V78 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v79-release-polish":
        raise RuntimeError(f"Unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V79_SYSTEM, OUT / "system.img")

    payloads = scripts()
    v78.v77.v76.OUT = OUT
    v78.v77.v76.CPIO_MTIME = CPIO_MTIME
    image_patches = {
        name: v78.v77.v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }
    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v78_sha256": base_hashes[name],
            "matches_v78": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [name for name in FILES if not files[name]["matches_v78"]]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V79 partition delta: {changed}")

    manifest = {
        "build": "y2-v79-release-polish",
        "status": "offline validation required; physical release gate required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v78_physical_result": {
            "passed": [
                "all six mapped cold-boot route checks",
                "Rockbox sleep and wake",
                "theme persistence",
                "USB export and clean Rockbox return without Stock UI",
            ],
            "remaining": [
                "platform Spinner choice list measured at zero height",
                "application su execution denied during route-map save",
                "root route/USB guards read a present but not-yet-populated route file",
                "Rockbox attached two framebuffer surfaces after initial extraction",
            ],
        },
        "behavior_delta": [
            "Boot Settings explicitly uses anchored dropdowns containing Rockbox, Y2 Stock and Boot Settings.",
            "Save rejects duplicate assignments and requires Boot Settings, while unchanged valid maps remain saveable.",
            "A root settings broker atomically persists the validated permutation and owns the reboot.",
            "The route guard and USB broker wait for a valid effective-route value rather than file existence alone.",
            "Rockbox attaches only one framebuffer per Activity, removing the second-surface top-row artifact path.",
            "The Stock playback receiver is route-gated so wake/media broadcasts cannot start a hidden Stock process on Rockbox or Boot Settings routes.",
            "V78's physically proven HOME and Stock component gates are otherwise unchanged.",
        ],
        "branding_unchanged": True,
        "haptic_unchanged": True,
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    report_json = "y2-v79-release-polish.json"
    report_md = "y2-v79-release-polish.md"
    test_txt = "V79-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / report_md).write_text(
        "# Y2 V79 Release Polish\n\n"
        "V79 preserves V78's physically successful HOME gates and closes the "
        "Boot Settings, route-file timing and duplicate framebuffer gaps.\n",
        encoding="utf-8")
    (OUT / test_txt).write_text(
        "Y2 V79 RELEASE POLISH TEST\n"
        "1. Flash the complete package using Download Only. NEVER Format All.\n"
        "2. No button, Volume Up and Volume Down must still open their configured routes cleanly.\n"
        "3. In Boot Settings open EACH dropdown and confirm all three choices: Rockbox, Y2 Stock, Boot Settings.\n"
        "4. Confirm duplicate assignments cannot save and one assignment must remain Boot Settings.\n"
        "5. Save the unchanged valid map; it must save and reboot without an error.\n"
        "6. Change to another valid permutation, save, then cold-boot all three inputs and confirm the new mapping.\n"
        "7. Restore the preferred mapping and save: No button=Rockbox, Volume Up=Y2 Stock, Volume Down=Boot Settings.\n"
        "8. Cold-boot Rockbox three times; no upper-row artifact may appear on boot 2 or 3.\n"
        "9. Test sleep/centre wake, theme persistence and USB storage on/off/unplug once.\n"
        "10. Power off before returning the SD card for V79 diagnostics.\n",
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
            raise RuntimeError("V79 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(f"{digest} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(ZIP),
        "size": ZIP.stat().st_size,
        "sha256": digest,
        "changed_from_v78": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
