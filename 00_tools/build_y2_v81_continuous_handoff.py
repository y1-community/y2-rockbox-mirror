#!/usr/bin/env python3
"""Build V81: continuous branding, early Settings UI and durable save broker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v80-release-gate.zip"
BASE_SHA256 = "C16F8D89FFDB915E5DEAE1B00CC66F653B3E81029EE3303AEDAF2F67378D1C72"
V81_SYSTEM = (
    E_ROOT
    / "y2-rockbox-system-prototype-v81-continuous-handoff"
    / "system.img"
)
V81_BRANDING = E_ROOT / "y2-v81-continuous-handoff-branding"
OUT = E_ROOT / "y2-v81-continuous-handoff"
ZIP = E_ROOT / "y2-v81-continuous-handoff.zip"
ZIP_SHA = E_ROOT / "y2-v81-continuous-handoff.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 25, 2, 30, 0)
CPIO_MTIME = 1784910600


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v80 = load(
    "v80_builder_base",
    ROOT / "00_tools" / "build_y2_v80_release_gate.py",
)
FILES = v80.FILES
ROUTE_SCRIPT = v80.ROUTE_SCRIPT
ROUTE_GUARD = v80.ROUTE_GUARD
USB_GUARD = v80.USB_GUARD
READ_KV_FUNCTION = v80.READ_KV_FUNCTION


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


def rename_v81(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace(
        "y2-v80-release-gate",
        "y2-v81-continuous-handoff",
    )
    text = text.replace("Y2_V80_DEBUG", "Y2_V81_DEBUG")
    text = text.replace("y2_v80_", "y2_v81_")
    text = text.replace("Y2 V80", "Y2 V81")
    return text.encode("ascii")


def v81_route_script(data: bytes) -> bytes:
    text = rename_v81(data).decode("ascii")

    effective_anchor = r'''else
    rm -f "$EFFECTIVE_ROUTE_TMP"
    exit 1
fi

INHERITED_BOOTCLASSPATH="$BOOTCLASSPATH"
'''
    effective_replacement = r'''else
    rm -f "$EFFECTIVE_ROUTE_TMP"
    exit 1
fi
setprop y2.firmware.effective_route "$ROUTE"
if [ "$(getprop y2.firmware.effective_route 2>/dev/null)" != "$ROUTE" ]; then
    exit 1
fi

INHERITED_BOOTCLASSPATH="$BOOTCLASSPATH"
'''
    if text.count(effective_anchor) != 1:
        raise RuntimeError("V81 effective-route property anchor drifted")
    text = text.replace(effective_anchor, effective_replacement)

    text = text.replace(
        "readiness=package/activity/router plus sys.boot_completed; "
        "Rockbox also requires writable primary storage",
        "readiness=Settings uses package/activity/router readiness; Stock uses "
        "boot completion; Rockbox also requires writable primary storage",
    )
    text = text.replace(
        "dispatch=single root HOME launch only after the real boot-complete gate",
        "dispatch=Settings launches at UI readiness; Stock and Rockbox retain "
        "their stronger readiness gates",
    )

    old_vars = r'''    BOOT_COMPLETE=0
    ROUTE_STORAGE_READY=1
'''
    new_vars = r'''    BOOT_COMPLETE=0
    ROUTE_STORAGE_READY=1
    ROUTE_READINESS=0
'''
    if text.count(old_vars) != 1:
        raise RuntimeError("V81 route-readiness variable anchor drifted")
    text = text.replace(old_vars, new_vars)

    old_gate = r'''    echo "attempt=$READINESS_ATTEMPT date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) package_service=$PACKAGE_SERVICE activity_service=$ACTIVITY_SERVICE route_receiver=$ROUTE_RECEIVER primary_storage=$PRIMARY_STORAGE primary_writable=$PRIMARY_WRITABLE secondary_storage=$SECONDARY_STORAGE boot_complete=$BOOT_COMPLETE route_storage_ready=$ROUTE_STORAGE_READY bootanim_exit=$(getprop service.bootanim.exit 2>/dev/null)" >> "$OUT/07-native-readiness.txt"

    if [ "$PACKAGE_SERVICE" -eq 1 ] && \
       [ "$ACTIVITY_SERVICE" -eq 1 ] && \
       [ "$ROUTE_RECEIVER" -eq 1 ] && \
       [ "$BOOT_COMPLETE" -eq 1 ] && \
       [ "$ROUTE_STORAGE_READY" -eq 1 ]; then
        SERVICES_READY=1
        break
    fi
'''
    new_gate = r'''    if [ "$PACKAGE_SERVICE" -eq 1 ] && \
       [ "$ACTIVITY_SERVICE" -eq 1 ] && \
       [ "$ROUTE_RECEIVER" -eq 1 ]; then
        case "$ROUTE" in
            settings)
                ROUTE_READINESS=1
                ;;
            stock)
                [ "$BOOT_COMPLETE" -eq 1 ] && ROUTE_READINESS=1
                ;;
            rockbox)
                if [ "$BOOT_COMPLETE" -eq 1 ] && \
                   [ "$ROUTE_STORAGE_READY" -eq 1 ]; then
                    ROUTE_READINESS=1
                fi
                ;;
        esac
    fi

    echo "attempt=$READINESS_ATTEMPT date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) package_service=$PACKAGE_SERVICE activity_service=$ACTIVITY_SERVICE route_receiver=$ROUTE_RECEIVER primary_storage=$PRIMARY_STORAGE primary_writable=$PRIMARY_WRITABLE secondary_storage=$SECONDARY_STORAGE boot_complete=$BOOT_COMPLETE route_storage_ready=$ROUTE_STORAGE_READY route_readiness=$ROUTE_READINESS bootanim_exit=$(getprop service.bootanim.exit 2>/dev/null)" >> "$OUT/07-native-readiness.txt"

    if [ "$ROUTE_READINESS" -eq 1 ]; then
        SERVICES_READY=1
        break
    fi
'''
    if text.count(old_gate) != 1:
        raise RuntimeError("V81 route-specific readiness anchor drifted")
    text = text.replace(old_gate, new_gate)
    text = text.replace(
        "reason=boot-complete-or-route-storage-readiness-timeout",
        "reason=route-specific-readiness-timeout",
    )
    text = text.replace(
        "fail-safe boot-complete-or-route-storage-readiness-timeout",
        "fail-safe route-specific-readiness-timeout",
    )
    return text.encode("ascii")


def v81_route_guard() -> bytes:
    return (
        r'''#!/system/bin/sh

BUILD="y2-v81-continuous-handoff"
DATA_ROOT="/data/local/tmp/Y2_V81_DEBUG"
ROUTE_PROPERTY="y2.firmware.route"
EFFECTIVE_ROUTE_PROPERTY="y2.firmware.effective_route"
STOCK_PACKAGE="com.innioasis.y2"
STOCK_HOME="com.innioasis.y2/com.innioasis.y1.activity.SplashActivity"
STOCK_MAIN="com.innioasis.y2/com.innioasis.y1.activity.MainActivity"
STOCK_PLAY="com.innioasis.y2/com.innioasis.y1.ui.receiver.PlayControllerReceiver"
ROUTER_HOME="org.rockbox/.Y2FirmwareHomeActivity"
SETTINGS_REQUEST="/data/data/org.rockbox/files/y2_boot_routes.request"
ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"

'''
        + READ_KV_FUNCTION
        + r'''
mkdir -p "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
[ -n "$BOOT_ID" ] || BOOT_ID="noid"
PHYSICAL_ROUTE=$(getprop "$ROUTE_PROPERTY")
ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
LOG="$DATA_ROOT/guard-$BOOT_ID.txt"
ROUTE=""
SIGNAL=""

log_event() {
    echo "build=$BUILD date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) $*" >> "$LOG"
    chmod 0644 "$LOG"
}

resolve_route() {
    CANDIDATE=$(getprop "$EFFECTIVE_ROUTE_PROPERTY" 2>/dev/null)
    case "$CANDIDATE" in
        rockbox|stock|settings) ;;
        *)
            CANDIDATE=$(read_kv "$ROUTE_FILE" route)
            ;;
    esac
    case "$CANDIDATE" in
        rockbox|stock|settings)
            if [ "$ROUTE" != "$CANDIDATE" ]; then
                ROUTE="$CANDIDATE"
                SIGNAL="$DATA_ROOT/route-dispatched-$BOOT_ID-$ROUTE.txt"
                log_event "guard=route-resolved route=$ROUTE source=authenticated-property-with-file-fallback"
            fi
            ;;
    esac
}

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
    [ -f "$SETTINGS_REQUEST" ] || return
    REQUEST_STATUS=$(read_kv "$SETTINGS_REQUEST" status)
    [ -z "$REQUEST_STATUS" ] || return

    REQUEST_VERSION=$(read_kv "$SETTINGS_REQUEST" request_version)
    REQUEST_ID=$(read_kv "$SETTINGS_REQUEST" request_id)
    REQUEST_NO=$(read_kv "$SETTINGS_REQUEST" no_button)
    REQUEST_UP=$(read_kv "$SETTINGS_REQUEST" volume_up)
    REQUEST_DOWN=$(read_kv "$SETTINGS_REQUEST" volume_down)
    REQUEST_REBOOT=$(read_kv "$SETTINGS_REQUEST" reboot)
    log_event "settings_broker=received request_id=$REQUEST_ID route=$ROUTE"

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

log_event "guard=start policy=route-independent-session-long-settings-broker physical_route=$PHYSICAL_ROUTE"
CYCLE=0
REPAIRS=0
while [ "$(getprop "$ROUTE_PROPERTY")" = "$PHYSICAL_ROUTE" ]; do
    resolve_route
    process_settings_request

    FOCUS=""
    if { [ "$ROUTE" = "rockbox" ] || [ "$ROUTE" = "settings" ]; } &&
       [ -n "$SIGNAL" ] && [ -f "$SIGNAL" ]; then
        FOCUS=$(dumpsys activity activities 2>/dev/null | grep -E "mResumedActivity|mFocusedActivity")
        case "$FOCUS" in
            *"$STOCK_PACKAGE/"*)
                REPAIRS=$((REPAIRS + 1))
                log_event "event=stock-foreground-violation route=$ROUTE repair=$REPAIRS action=disable-force-stop-router-reassert"
                echo "$FOCUS" >> "$LOG"
                pm disable "$STOCK_HOME" >> "$LOG" 2>&1
                pm disable "$STOCK_MAIN" >> "$LOG" 2>&1
                pm disable "$STOCK_PLAY" >> "$LOG" 2>&1
                am force-stop "$STOCK_PACKAGE" >> "$LOG" 2>&1
                am start -W -n "$ROUTER_HOME" --es physical_route "$PHYSICAL_ROUTE" --es route "$ROUTE" >> "$LOG" 2>&1
                chmod 0644 "$LOG"
                ;;
        esac
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
log_event "guard=exit reason=physical-route-changed cycles=$CYCLE repairs=$REPAIRS"
exit 0
'''
    ).encode("ascii")


def v81_usb_guard(data: bytes) -> bytes:
    text = rename_v81(data).decode("ascii")
    text = text.replace(
        'STATE_FILE="/sys/class/android_usb/android0/state"\n',
        'STATE_FILE="/sys/class/android_usb/android0/state"\n'
        'EFFECTIVE_ROUTE_PROPERTY="y2.firmware.effective_route"\n',
    )
    old_loop = r'''while [ "$WAIT" -lt 240 ]; do
    ROUTE=$(read_kv "$ROUTE_FILE" route)
    case "$ROUTE" in
        rockbox|stock|settings) break ;;
    esac
    ROUTE=""
    WAIT=$((WAIT + 1))
    sleep 1
done
'''
    new_loop = r'''while [ "$WAIT" -lt 240 ]; do
    ROUTE=$(getprop "$EFFECTIVE_ROUTE_PROPERTY" 2>/dev/null)
    case "$ROUTE" in
        rockbox|stock|settings) break ;;
        *) ROUTE=$(read_kv "$ROUTE_FILE" route) ;;
    esac
    case "$ROUTE" in
        rockbox|stock|settings) break ;;
    esac
    ROUTE=""
    WAIT=$((WAIT + 1))
    sleep 1
done
'''
    if text.count(old_loop) != 1:
        raise RuntimeError("V81 USB authenticated property anchor drifted")
    return text.replace(old_loop, new_loop).encode("ascii")


def scripts() -> dict[str, bytes]:
    entries, *_ = v80.v79.v78.v77.v76.ramdisk(base_image("recovery.img"))
    source = {entry["name"]: entry["data"] for entry in entries}
    result: dict[str, bytes] = {}
    for name in v80.v79.v78.v77.v76.v75.v74.SCRIPT_NAMES:
        if name == ROUTE_SCRIPT:
            result[name] = v81_route_script(source[name])
        elif name == ROUTE_GUARD:
            result[name] = v81_route_guard()
        elif name == USB_GUARD:
            result[name] = v81_usb_guard(source[name])
        else:
            result[name] = rename_v81(source[name])
    result[USB_GUARD] = v81_usb_guard(source[USB_GUARD])
    return result


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V80 base is missing or drifted")
    for required in (V81_SYSTEM, V81_BRANDING / "bootanimation.zip"):
        if not required.is_file():
            raise FileNotFoundError(required)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V80 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V80 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if (
        OUT.resolve().parent != E_ROOT.resolve()
        or OUT.name != "y2-v81-continuous-handoff"
    ):
        raise RuntimeError(f"Unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {
            name: sha256_bytes(archive.read(name))
            for name in FILES
        }
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V81_SYSTEM, OUT / "system.img")

    payloads = scripts()
    v80.v79.v78.v77.v76.OUT = OUT
    v80.v79.v78.v77.v76.CPIO_MTIME = CPIO_MTIME
    image_patches = {
        name: v80.v79.v78.v77.v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }

    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v80_sha256": base_hashes[name],
            "matches_v80": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [
        name for name in FILES
        if not files[name]["matches_v80"]
    ]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V81 partition delta: {changed}")
    for name in ("lk.bin", "logo.bin"):
        if not files[name]["matches_v80"]:
            raise RuntimeError(f"V81 unexpectedly changed {name}")

    manifest = {
        "build": "y2-v81-continuous-handoff",
        "status": "offline validation required; physical gate required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v80_physical_findings": [
            "No-button Rockbox boot passed.",
            "The one-loop-plus-static boot animation visibly paused and was followed by a large black interval before Boot Settings.",
            "Boot Settings rendered in 359 ms once launched; the delay was in the upstream boot-complete dispatch gate.",
            "Save request 124428 timed out because the root route guard waited 240 seconds with an empty effective route and never entered its request loop.",
        ],
        "behavior_delta": [
            "The Android SPYCE animation continuously repeats three complete 39-frame GIF cycles per interruptible part and has no static hold section.",
            "The first GIF frame remains the unchanged LK/static fallback image.",
            "Boot Settings uses package/activity/router readiness and no longer waits for global boot completion.",
            "Rockbox retains V80's true boot-complete and writable-primary-storage gate.",
            "The effective route is published as a root-owned Android property with the atomic file retained as fallback.",
            "The settings broker starts immediately, is route-independent and remains alive for the Android session.",
            "The broker logs receipt, validates the unique permutation, atomically writes and rereads it, acknowledges the app, waits two seconds and reboots.",
        ],
        "branding": {
            "gif_sha256": (
                "640FD82729D11FC0695AEABC5037B45B0D4811AD902D8C045751F78990A32E5C"
            ),
            "bootanimation_sha256": sha256(
                V81_BRANDING / "bootanimation.zip"
            ),
            "descriptor": "480 360 20; p 0 0 part0",
            "frames_per_part": 117,
            "source_frames": 39,
            "source_cycles_per_part": 3,
            "static_fallback": "GIF frame 1 through unchanged V80 logo.bin",
        },
        "haptic_unchanged": True,
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }

    report_json = "y2-v81-continuous-handoff.json"
    report_md = "y2-v81-continuous-handoff.md"
    test_txt = "V81-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / report_md).write_text(
        "# Y2 V81 Continuous Handoff\n\n"
        "V81 is the exact physically tested V80 base with three constrained "
        "changes: continuous full-GIF animation, early Boot Settings UI "
        "readiness, and a route-independent session-long settings save "
        "broker. LK, logo.bin, the key latch, haptic timing, playback "
        "libraries and the Rockbox storage gate are preserved.\n",
        encoding="utf-8",
    )
    (OUT / test_txt).write_text(
        "Y2 V81 CONTINUOUS HANDOFF TEST\n"
        "1. Flash the complete package with Download Only. NEVER use Format All.\n"
        "2. No-button boot: SPYCE must animate continuously with no dim/static pause, complete at least three loops, continue through the haptic release cue, and hand directly to Rockbox without black.\n"
        "3. Volume Down: SPYCE must animate continuously and hand directly to Boot Settings without a black interval.\n"
        "4. Save the unchanged map: require Saving, then Saved - restarting, followed by automatic reboot.\n"
        "5. Save a different valid permutation and cold-boot all three inputs to prove the persisted mapping.\n"
        "6. Restore No button=Rockbox, Volume Up=Y2 Stock and Volume Down=Boot Settings, then save and confirm automatic reboot.\n"
        "7. Recheck no-button Rockbox first-post-flash startup, OneBitMono width, sleep/centre wake, three-second power and USB return.\n"
        "8. Power off before returning the SD card for V81 diagnostics.\n",
        encoding="utf-8",
    )

    if ZIP.exists():
        ZIP.unlink()
    members = (*FILES, report_json, report_md, test_txt)
    with zipfile.ZipFile(
        ZIP,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())
    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V81 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(
        f"{digest} *{ZIP.name}\n",
        encoding="ascii",
    )
    print(
        json.dumps(
            {
                "zip": str(ZIP),
                "size": ZIP.stat().st_size,
                "sha256": digest,
                "changed_from_v80": changed,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
