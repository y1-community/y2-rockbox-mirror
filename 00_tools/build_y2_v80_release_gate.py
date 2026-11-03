#!/usr/bin/env python3
"""Build V80: verified route persistence, true boot readiness and SPYCE branding."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v79-release-polish.zip"
BASE_SHA256 = "B49EB6181183241162E973BC2EDC36B3D21AE78529D87D8A5DB4B6BE2147406C"
V80_SYSTEM = (
    E_ROOT / "y2-rockbox-system-prototype-v80-release-gate" / "system.img"
)
V80_BRANDING = E_ROOT / "y2-v80-release-gate-branding"
V80_LOGO = V80_BRANDING / "logo.bin"
OUT = E_ROOT / "y2-v80-release-gate"
ZIP = E_ROOT / "y2-v80-release-gate.zip"
ZIP_SHA = E_ROOT / "y2-v80-release-gate.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 25, 1, 0, 0)
CPIO_MTIME = 1784908800


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v79 = load("v79_builder_base", ROOT / "00_tools" /
           "build_y2_v79_release_polish.py")
FILES = v79.FILES
ROUTE_SCRIPT = v79.ROUTE_SCRIPT
ROUTE_GUARD = v79.ROUTE_GUARD
USB_GUARD = v79.USB_GUARD


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


def rename_v80(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v79-release-polish", "y2-v80-release-gate")
    text = text.replace("Y2_V79_DEBUG", "Y2_V80_DEBUG")
    text = text.replace("y2_v79_", "y2_v80_")
    text = text.replace("Y2 V79", "Y2 V80")
    return text.encode("ascii")


READ_KV_FUNCTION = r'''read_kv() {
    READ_KV_FILE="$1"
    READ_KV_KEY="$2"
    [ -r "$READ_KV_FILE" ] || return 1
    while IFS= read READ_KV_LINE || [ -n "$READ_KV_LINE" ]; do
        case "$READ_KV_LINE" in
            "$READ_KV_KEY="*)
                printf '%s\n' "${READ_KV_LINE#*=}"
                return 0
                ;;
        esac
    done < "$READ_KV_FILE"
    return 1
}
'''


def v80_route_script(data: bytes) -> bytes:
    text = rename_v80(data).decode("ascii")
    text = text.replace("MAX_READINESS_ATTEMPTS=90",
                        "MAX_READINESS_ATTEMPTS=240")

    old_map = r'''if [ -r "$ROUTE_MAP_FILE" ] &&
   grep -F "version=1" "$ROUTE_MAP_FILE" >/dev/null 2>&1; then
    CANDIDATE=$(grep "^$ROUTE_MAP_KEY=" "$ROUTE_MAP_FILE" 2>/dev/null |
        head -n 1 | cut -d= -f2)
    case "$CANDIDATE" in
        rockbox|stock|settings)
            MAPPED_ROUTE="$CANDIDATE"
            ROUTE_MAP_SOURCE="saved-settings"
            ;;
    esac
fi
'''
    new_map = READ_KV_FUNCTION + r'''
ROUTE_MAP_VERSION=$(read_kv "$ROUTE_MAP_FILE" version)
if [ "$ROUTE_MAP_VERSION" = "1" ]; then
    CANDIDATE=$(read_kv "$ROUTE_MAP_FILE" "$ROUTE_MAP_KEY")
    case "$CANDIDATE" in
        rockbox|stock|settings)
            MAPPED_ROUTE="$CANDIDATE"
            ROUTE_MAP_SOURCE="saved-settings"
            ;;
    esac
fi
'''
    if text.count(old_map) != 1:
        raise RuntimeError("V80 route-map parser anchor drifted")
    text = text.replace(old_map, new_map)

    old_effective = r'''EFFECTIVE_ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
{
    echo "physical_route=$PHYSICAL_ROUTE"
    echo "route=$ROUTE"
    echo "boot_id=$BOOT_ID"
    echo "route_map_source=$ROUTE_MAP_SOURCE"
} > "$EFFECTIVE_ROUTE_FILE"
chmod 0644 "$EFFECTIVE_ROUTE_FILE"
'''
    new_effective = r'''EFFECTIVE_ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
EFFECTIVE_ROUTE_TMP="$EFFECTIVE_ROUTE_FILE.tmp.$$"
if {
    echo "physical_route=$PHYSICAL_ROUTE"
    echo "route=$ROUTE"
    echo "boot_id=$BOOT_ID"
    echo "route_map_source=$ROUTE_MAP_SOURCE"
} > "$EFFECTIVE_ROUTE_TMP" &&
   chmod 0644 "$EFFECTIVE_ROUTE_TMP" &&
   mv "$EFFECTIVE_ROUTE_TMP" "$EFFECTIVE_ROUTE_FILE"; then
    :
else
    rm -f "$EFFECTIVE_ROUTE_TMP"
    exit 1
fi
'''
    if text.count(old_effective) != 1:
        raise RuntimeError("V80 effective-route write anchor drifted")
    text = text.replace(old_effective, new_effective)

    text = text.replace(
        "readiness=native Binder receiver registration; storage is observed but not a dispatch blocker",
        "readiness=package/activity/router plus sys.boot_completed; Rockbox also requires writable primary storage",
    )
    text = text.replace(
        "fallback=one bounded boot-complete dispatch after two bounded early failures",
        "dispatch=single root HOME launch only after the real boot-complete gate",
    )

    old_vars = r'''    PRIMARY_STORAGE=0
    SECONDARY_STORAGE=0
'''
    new_vars = r'''    PRIMARY_STORAGE=0
    PRIMARY_WRITABLE=0
    SECONDARY_STORAGE=0
    BOOT_COMPLETE=0
    ROUTE_STORAGE_READY=1
'''
    if text.count(old_vars) != 1:
        raise RuntimeError("V80 readiness variable anchor drifted")
    text = text.replace(old_vars, new_vars)

    old_storage = r'''    if is_mounted /storage/sdcard0; then
        PRIMARY_STORAGE=1
    fi
    if is_mounted /storage/sdcard1; then
        SECONDARY_STORAGE=1
    fi

    echo "attempt=$READINESS_ATTEMPT date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) package_service=$PACKAGE_SERVICE activity_service=$ACTIVITY_SERVICE route_receiver=$ROUTE_RECEIVER primary_storage=$PRIMARY_STORAGE secondary_storage=$SECONDARY_STORAGE boot_completed=$(getprop sys.boot_completed 2>/dev/null) bootanim_exit=$(getprop service.bootanim.exit 2>/dev/null)" >> "$OUT/07-native-readiness.txt"

    if [ "$PACKAGE_SERVICE" -eq 1 ] && \
       [ "$ACTIVITY_SERVICE" -eq 1 ] && \
       [ "$ROUTE_RECEIVER" -eq 1 ]; then
        SERVICES_READY=1
        break
    fi
'''
    new_storage = r'''    if is_mounted /storage/sdcard0; then
        PRIMARY_STORAGE=1
        PRIMARY_PROBE="/storage/sdcard0/.y2-v80-ready-$BOOT_ID-$$"
        if : > "$PRIMARY_PROBE" 2>/dev/null; then
            PRIMARY_WRITABLE=1
            rm -f "$PRIMARY_PROBE"
        fi
    fi
    if is_mounted /storage/sdcard1; then
        SECONDARY_STORAGE=1
    fi
    if [ "$(getprop sys.boot_completed 2>/dev/null)" = "1" ]; then
        BOOT_COMPLETE=1
    fi
    if [ "$ROUTE" = "rockbox" ] &&
       { [ "$PRIMARY_STORAGE" -ne 1 ] || [ "$PRIMARY_WRITABLE" -ne 1 ]; }; then
        ROUTE_STORAGE_READY=0
    fi

    echo "attempt=$READINESS_ATTEMPT date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) package_service=$PACKAGE_SERVICE activity_service=$ACTIVITY_SERVICE route_receiver=$ROUTE_RECEIVER primary_storage=$PRIMARY_STORAGE primary_writable=$PRIMARY_WRITABLE secondary_storage=$SECONDARY_STORAGE boot_complete=$BOOT_COMPLETE route_storage_ready=$ROUTE_STORAGE_READY bootanim_exit=$(getprop service.bootanim.exit 2>/dev/null)" >> "$OUT/07-native-readiness.txt"

    if [ "$PACKAGE_SERVICE" -eq 1 ] && \
       [ "$ACTIVITY_SERVICE" -eq 1 ] && \
       [ "$ROUTE_RECEIVER" -eq 1 ] && \
       [ "$BOOT_COMPLETE" -eq 1 ] && \
       [ "$ROUTE_STORAGE_READY" -eq 1 ]; then
        SERVICES_READY=1
        break
    fi
'''
    if text.count(old_storage) != 1:
        raise RuntimeError("V80 true-readiness anchor drifted")
    text = text.replace(old_storage, new_storage)
    text = text.replace("reason=native-receiver-readiness-timeout",
                        "reason=boot-complete-or-route-storage-readiness-timeout")
    text = text.replace("native-receiver-readiness-timeout",
                        "boot-complete-or-route-storage-readiness-timeout")
    return text.encode("ascii")


def v80_route_guard() -> bytes:
    return (r'''#!/system/bin/sh

BUILD="y2-v80-release-gate"
DATA_ROOT="/data/local/tmp/Y2_V80_DEBUG"
ROUTE_PROPERTY="y2.firmware.route"
STOCK_PACKAGE="com.innioasis.y2"
STOCK_HOME="com.innioasis.y2/com.innioasis.y1.activity.SplashActivity"
STOCK_MAIN="com.innioasis.y2/com.innioasis.y1.activity.MainActivity"
STOCK_PLAY="com.innioasis.y2/com.innioasis.y1.ui.receiver.PlayControllerReceiver"
ROUTER_HOME="org.rockbox/.Y2FirmwareHomeActivity"
SETTINGS_REQUEST="/data/data/org.rockbox/files/y2_boot_routes.request"
ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"

''' + READ_KV_FUNCTION + r'''
mkdir -p "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
[ -n "$BOOT_ID" ] || BOOT_ID="noid"
PHYSICAL_ROUTE=$(getprop "$ROUTE_PROPERTY")
ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
ROUTE=""
ROUTE_WAIT=0
while [ "$ROUTE_WAIT" -lt 240 ]; do
    ROUTE=$(read_kv "$ROUTE_FILE" route)
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
while [ "$WAIT" -lt 240 ] && [ ! -f "$SIGNAL" ]; do
    WAIT=$((WAIT + 1))
    sleep 1
done
if [ ! -f "$SIGNAL" ]; then
    log_event "guard=exit reason=current-boot-dispatch-signal-absent action=none"
    exit 0
fi

write_response() {
    RESPONSE_STATUS="$1"
    RESPONSE_TMP="$SETTINGS_REQUEST.response.$$"
    if printf '%s\n' "request_id=$REQUEST_ID" \
            "status=$RESPONSE_STATUS" > "$RESPONSE_TMP" &&
       chmod 0644 "$RESPONSE_TMP" &&
       mv "$RESPONSE_TMP" "$SETTINGS_REQUEST"; then
        return 0
    fi
    rm -f "$RESPONSE_TMP"
    return 1
}

process_settings_request() {
    if [ "$ROUTE" != "settings" ] || [ ! -f "$SETTINGS_REQUEST" ]; then
        return
    fi
    REQUEST_STATUS=$(read_kv "$SETTINGS_REQUEST" status)
    [ -z "$REQUEST_STATUS" ] || return

    REQUEST_VERSION=$(read_kv "$SETTINGS_REQUEST" request_version)
    REQUEST_ID=$(read_kv "$SETTINGS_REQUEST" request_id)
    REQUEST_NO=$(read_kv "$SETTINGS_REQUEST" no_button)
    REQUEST_UP=$(read_kv "$SETTINGS_REQUEST" volume_up)
    REQUEST_DOWN=$(read_kv "$SETTINGS_REQUEST" volume_down)
    REQUEST_REBOOT=$(read_kv "$SETTINGS_REQUEST" reboot)
    REQUEST_VALID=1
    [ "$REQUEST_VERSION" = "1" ] || REQUEST_VALID=0
    case "$REQUEST_ID" in
        ""|*[!0-9]*) REQUEST_VALID=0 ;;
    esac
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
        write_response error-invalid-permutation
        log_event "settings_broker=rejected request_id=$REQUEST_ID reason=invalid-permutation"
        return
    fi

    ROUTE_MAP_TMP="$ROUTE_MAP_FILE.tmp.$$"
    if umask 077 &&
       printf '%s\n' 'version=1' "no_button=$REQUEST_NO" \
           "volume_up=$REQUEST_UP" "volume_down=$REQUEST_DOWN" > "$ROUTE_MAP_TMP" &&
       chmod 0600 "$ROUTE_MAP_TMP" &&
       mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"; then
        VERIFY_VERSION=$(read_kv "$ROUTE_MAP_FILE" version)
        VERIFY_NO=$(read_kv "$ROUTE_MAP_FILE" no_button)
        VERIFY_UP=$(read_kv "$ROUTE_MAP_FILE" volume_up)
        VERIFY_DOWN=$(read_kv "$ROUTE_MAP_FILE" volume_down)
        if [ "$VERIFY_VERSION" = "1" ] &&
           [ "$VERIFY_NO" = "$REQUEST_NO" ] &&
           [ "$VERIFY_UP" = "$REQUEST_UP" ] &&
           [ "$VERIFY_DOWN" = "$REQUEST_DOWN" ]; then
            log_event "settings_broker=verified request_id=$REQUEST_ID no_button=$VERIFY_NO volume_up=$VERIFY_UP volume_down=$VERIFY_DOWN"
            sync
            if write_response ok; then
                log_event "settings_broker=acknowledged request_id=$REQUEST_ID status=ok"
                sync
                if [ "$REQUEST_REBOOT" = "1" ]; then
                    sleep 2
                    log_event "settings_broker=reboot request_id=$REQUEST_ID"
                    sync
                    reboot
                fi
            else
                log_event "settings_broker=rejected request_id=$REQUEST_ID reason=response-write-failed"
            fi
            return
        fi
        write_response error-verify-failed
        log_event "settings_broker=rejected request_id=$REQUEST_ID reason=verify-failed verify_no=$VERIFY_NO verify_up=$VERIFY_UP verify_down=$VERIFY_DOWN"
    else
        rm -f "$ROUTE_MAP_TMP"
        write_response error-write-failed
        log_event "settings_broker=rejected request_id=$REQUEST_ID reason=write-failed"
    fi
}

log_event "guard=start policy=active-exclusive-home-repair route=$ROUTE physical_route=$PHYSICAL_ROUTE route_wait=$ROUTE_WAIT parser=shell-builtins settings_broker=$([ "$ROUTE" = "settings" ] && echo active || echo inactive)"
CYCLE=0
REPAIRS=0
while [ "$(getprop "$ROUTE_PROPERTY")" = "$PHYSICAL_ROUTE" ]; do
    process_settings_request
    FOCUS=$(dumpsys activity activities 2>/dev/null | grep -E "mResumedActivity|mFocusedActivity")
    case "$FOCUS" in
        *"$STOCK_PACKAGE/"*)
            REPAIRS=$((REPAIRS + 1))
            log_event "event=stock-foreground-violation repair=$REPAIRS action=disable-force-stop-router-reassert"
            echo "$FOCUS" >> "$LOG"
            pm disable "$STOCK_HOME" >> "$LOG" 2>&1
            pm disable "$STOCK_MAIN" >> "$LOG" 2>&1
            pm disable "$STOCK_PLAY" >> "$LOG" 2>&1
            am force-stop "$STOCK_PACKAGE" >> "$LOG" 2>&1
            am start -W -n "$ROUTER_HOME" --es physical_route "$PHYSICAL_ROUTE" --es route "$ROUTE" >> "$LOG" 2>&1
            chmod 0644 "$LOG"
            ;;
    esac
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
''').encode("ascii")


def v80_usb_guard() -> bytes:
    return (r'''#!/system/bin/sh

BUILD="y2-v80-release-gate"
DATA_ROOT="/data/local/tmp/Y2_V80_DEBUG"
STATE_FILE="/sys/class/android_usb/android0/state"
USB_ACTIVITY="com.android.systemui/.usb.UsbStorageActivity"

''' + READ_KV_FUNCTION + r'''
mkdir -p "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
[ -n "$BOOT_ID" ] || BOOT_ID="noid"
ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
LOG="$DATA_ROOT/usb-root-broker-$BOOT_ID.txt"

log_event() {
    echo "build=$BUILD date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) $*" >> "$LOG"
    chmod 0644 "$LOG"
}

ROUTE=""
WAIT=0
while [ "$WAIT" -lt 240 ]; do
    ROUTE=$(read_kv "$ROUTE_FILE" route)
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
log_event "broker=start route=$ROUTE route_wait=$WAIT parser=shell-builtins authority=root-init-shell activity=$USB_ACTIVITY"
while true; do
    STATE=$(cat "$STATE_FILE" 2>/dev/null)
    [ -n "$STATE" ] || STATE="unknown"
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
''').encode("ascii")


def scripts() -> dict[str, bytes]:
    entries, *_ = v79.v78.v77.v76.ramdisk(base_image("recovery.img"))
    source = {entry["name"]: entry["data"] for entry in entries}
    result: dict[str, bytes] = {}
    for name in v79.v78.v77.v76.v75.v74.SCRIPT_NAMES:
        if name == ROUTE_SCRIPT:
            result[name] = v80_route_script(source[name])
        elif name == ROUTE_GUARD:
            result[name] = v80_route_guard()
        elif name == USB_GUARD:
            result[name] = v80_usb_guard()
        else:
            result[name] = rename_v80(source[name])
    result[USB_GUARD] = v80_usb_guard()
    return result


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V79 base is missing or drifted")
    for required in (V80_SYSTEM, V80_LOGO):
        if not required.is_file():
            raise FileNotFoundError(required)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V79 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V79 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v80-release-gate":
        raise RuntimeError(f"Unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V80_SYSTEM, OUT / "system.img")
    shutil.copy2(V80_LOGO, OUT / "logo.bin")

    payloads = scripts()
    v79.v78.v77.v76.OUT = OUT
    v79.v78.v77.v76.CPIO_MTIME = CPIO_MTIME
    image_patches = {
        name: v79.v78.v77.v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }
    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v79_sha256": base_hashes[name],
            "matches_v79": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [name for name in FILES if not files[name]["matches_v79"]]
    if changed != ["boot.img", "recovery.img", "logo.bin", "system.img"]:
        raise RuntimeError(f"Unexpected V80 partition delta: {changed}")
    if files["lk.bin"]["matches_v79"] is not True:
        raise RuntimeError("V80 changed LK and could alter key latch/haptic behavior")

    manifest = {
        "build": "y2-v80-release-gate",
        "status": "offline validation required; physical release gate required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v79_physical_findings": [
            "First post-flash Rockbox dispatch started before sys.boot_completed and writable primary storage, producing a Rockbox Starting loop.",
            "Boot Settings submitted a valid save request, but the root guard parsed an empty route through a grep/head pipeline and exited after 90 seconds.",
            "The second Rockbox boot, all three dropdowns, sleep/wake and USB operation otherwise worked.",
        ],
        "behavior_delta": [
            "Critical route/config parsers now use shell built-ins without grep/head SIGPIPE exposure.",
            "The effective route handoff is written atomically.",
            "Stock components are gated early, while HOME dispatch waits for sys.boot_completed; Rockbox additionally waits for writable primary storage.",
            "Boot Settings displays Saving, verified Saved/restarting, and recoverable timeout states.",
            "The root broker writes, rereads and verifies the exact route permutation before acknowledging and rebooting.",
            "OneBitMono uses a full-width 480-pixel menu viewport.",
            "The user-supplied SPYCE GIF replaces the Android animation and the two full-screen Innioasis logo slots.",
            "Charging/error logo assets, LK, key latch timing and stock haptic behavior are preserved.",
        ],
        "branding": {
            "gif_sha256": (
                "640FD82729D11FC0695AEABC5037B45B0D4811AD902D8C045751F78990A32E5C"
            ),
            "logo_sha256": sha256(V80_LOGO),
            "bootanimation_sha256": sha256(
                V80_BRANDING / "bootanimation.zip"),
            "native_geometry": "480x360",
        },
        "haptic_unchanged": True,
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    report_json = "y2-v80-release-gate.json"
    report_md = "y2-v80-release-gate.md"
    test_txt = "V80-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / report_md).write_text(
        "# Y2 V80 Release Gate\n\n"
        "V80 closes the two V79 physical blockers: premature first-boot dispatch "
        "and the root settings broker's unreliable pipeline parser. It also "
        "adds the supplied SPYCE boot branding and corrects OneBitMono's inset "
        "menu viewport while preserving LK and its haptic/key timing.\n",
        encoding="utf-8")
    (OUT / test_txt).write_text(
        "Y2 V80 RELEASE GATE TEST\n"
        "1. Flash the complete package with Download Only. NEVER use Format All.\n"
        "2. First post-flash no-button boot: SPYCE must appear, haptic remains the button-release cue, then Rockbox opens once with no Starting loop or Stock UI.\n"
        "3. Reboot no-button twice more; Rockbox must open cleanly with no top-row artifacts.\n"
        "4. Volume Up must open Y2 Stock cleanly.\n"
        "5. Volume Down must open Boot Settings; each dropdown must show Rockbox, Y2 Stock and Boot Settings.\n"
        "6. Save the unchanged map: button shows Saving, then Saved/restarting, and the Y2 reboots automatically.\n"
        "7. Save a different valid permutation and cold-boot all three inputs to prove the persisted map.\n"
        "8. Restore No button=Rockbox, Volume Up=Y2 Stock, Volume Down=Boot Settings and save.\n"
        "9. In Rockbox select OneBitMono and confirm the root menu uses the full display width.\n"
        "10. Test sleep/centre wake five times, three-second power, theme persistence, USB on/off, and cable unplug return.\n"
        "11. Power off before returning the SD card for V80 diagnostics.\n",
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
            raise RuntimeError("V80 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(f"{digest} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(ZIP),
        "size": ZIP.stat().st_size,
        "sha256": digest,
        "changed_from_v79": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
