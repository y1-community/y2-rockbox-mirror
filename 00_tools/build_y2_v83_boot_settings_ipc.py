#!/usr/bin/env python3
"""Build V83: narrow Binder IPC for the Boot Settings save broker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE_ZIP = WORK / "y2-v82-settings-commit.zip"
BASE_SHA256 = "BDA35D7C730F6228717626848ACA79E01CA5DDAB8F03F22F29544B77756C0073"
V83_SYSTEM = (
    WORK
    / "y2-rockbox-system-prototype-v83-boot-settings-ipc"
    / "system.img"
)
V83_APK = (
    WORK
    / "rockbox-android-y2-v83-boot-settings-ipc"
    / "rockbox-y2-v83-boot-settings-ipc.apk"
)
OUT = WORK / "y2-v83-boot-settings-ipc"
ZIP = WORK / "y2-v83-boot-settings-ipc.zip"
ZIP_SHA = WORK / "y2-v83-boot-settings-ipc.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 28, 20, 30, 0)
CPIO_MTIME = 1785241800


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v82 = load(
    "v82_builder_base",
    ROOT / "00_tools" / "build_y2_v82_settings_commit.py",
)
v81 = v82.v81
FILES = v82.FILES
ROUTE_GUARD = v82.ROUTE_GUARD


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def v83_route_guard() -> bytes:
    """Replace the rejected private-file bridge with a narrow provider."""

    text = v81.v81_route_guard().decode("ascii")
    text = text.replace(
        'BUILD="y2-v81-continuous-handoff"',
        'BUILD="y2-v83-boot-settings-ipc"',
        1,
    )
    text = text.replace(
        'DATA_ROOT="/data/local/tmp/Y2_V81_DEBUG"',
        'DATA_ROOT="/data/local/tmp/Y2_V83_DEBUG"',
        1,
    )
    constants = (
        'SETTINGS_REQUEST="/data/data/org.rockbox/files/'
        'y2_boot_routes.request"\n'
        'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"\n'
    )
    replacement = (
        'CONTENT="/system/bin/content"\n'
        'REQUEST_URI="content://org.rockbox.y2.bootroutes/request"\n'
        'RESPONSE_URI="content://org.rockbox.y2.bootroutes/response"\n'
        'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"\n'
        'LAST_QUERY_ERROR=""\n'
    )
    if text.count(constants) != 1:
        raise RuntimeError("V83 guard constants anchor drifted")
    text = text.replace(constants, replacement, 1)

    old = r'''write_response() {
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
'''
    new = r'''query_value() {
    QUERY_KEY="$1"
    QUERY_REMAINDER=${QUERY_OUTPUT#*"$QUERY_KEY="}
    if [ "$QUERY_REMAINDER" = "$QUERY_OUTPUT" ]; then
        QUERY_VALUE=""
        return
    fi
    QUERY_VALUE=${QUERY_REMAINDER%%,*}
}

quarantine_request() {
    QUARANTINE_OUTPUT=$("$CONTENT" delete --uri "$REQUEST_URI" 2>&1)
    QUARANTINE_EXIT=$?
}

write_response() {
    RESPONSE_STATUS="$1"
    RESPONSE_OUTPUT=$("$CONTENT" insert --uri "$RESPONSE_URI" \
        --bind "request_id:s:$REQUEST_ID" \
        --bind "status:s:$RESPONSE_STATUS" 2>&1)
    RESPONSE_EXIT=$?
    [ "$RESPONSE_EXIT" -eq 0 ]
}

process_settings_request() {
    QUERY_OUTPUT=$("$CONTENT" query --uri "$REQUEST_URI" 2>&1)
    QUERY_EXIT=$?
    if [ "$QUERY_EXIT" -ne 0 ]; then
        QUERY_ERROR="$QUERY_EXIT:$QUERY_OUTPUT"
        if [ "$QUERY_ERROR" != "$LAST_QUERY_ERROR" ]; then
            log_event "settings_broker=query-failed transport=content-provider exit=$QUERY_EXIT output=$QUERY_OUTPUT"
            LAST_QUERY_ERROR="$QUERY_ERROR"
        fi
        return
    fi
    LAST_QUERY_ERROR=""
    case "$QUERY_OUTPUT" in
        ""|*"No result found."*)
            return
            ;;
        *"request_version="*"request_id="*"no_button="*"volume_up="*"volume_down="*"reboot="*)
            ;;
        *)
            quarantine_request
            log_event "settings_broker=rejected reason=malformed-provider-output query_exit=$QUERY_EXIT quarantine_exit=$QUARANTINE_EXIT"
            return
            ;;
    esac

    query_value request_version
    REQUEST_VERSION="$QUERY_VALUE"
    query_value request_id
    REQUEST_ID="$QUERY_VALUE"
    query_value no_button
    REQUEST_NO="$QUERY_VALUE"
    query_value volume_up
    REQUEST_UP="$QUERY_VALUE"
    query_value volume_down
    REQUEST_DOWN="$QUERY_VALUE"
    query_value reboot
    REQUEST_REBOOT="$QUERY_VALUE"
'''
    if text.count(old) != 1:
        raise RuntimeError("V83 request broker anchor drifted")
    text = text.replace(old, new, 1)

    invalid = r'''    if [ "$REQUEST_VALID" -ne 1 ]; then
        write_response error-invalid-permutation
        log_event "settings_broker=rejected request_id=$REQUEST_ID reason=invalid-permutation"
        return
    fi
'''
    invalid_replacement = r'''    if [ "$REQUEST_VALID" -ne 1 ]; then
        if write_response error-invalid-permutation; then
            INVALID_CONSUMED="response"
        else
            quarantine_request
            INVALID_CONSUMED="quarantine-exit-$QUARANTINE_EXIT"
        fi
        log_event "settings_broker=rejected request_id=$REQUEST_ID reason=invalid-permutation consumed=$INVALID_CONSUMED"
        return
    fi
    log_event "settings_broker=received request_id=$REQUEST_ID route=$ROUTE transport=content-provider query_exit=$QUERY_EXIT fields=valid"
'''
    if text.count(invalid) != 1:
        raise RuntimeError("V83 invalid-request anchor drifted")
    text = text.replace(invalid, invalid_replacement, 1)
    return text.encode("ascii")


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Rejected V82 comparison base is missing or drifted")
    if not V83_SYSTEM.is_file():
        raise RuntimeError("V83 system image is missing")
    if not V83_APK.is_file():
        raise RuntimeError("V83 APK is missing")
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V82 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V82 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != WORK.resolve() or OUT.name != (
            "y2-v83-boot-settings-ipc"):
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
    shutil.copyfile(V83_SYSTEM, OUT / "system.img")

    v81.v80.v79.v78.v77.v76.OUT = OUT
    v81.v80.v79.v78.v77.v76.CPIO_MTIME = CPIO_MTIME
    payloads = {ROUTE_GUARD: v83_route_guard()}
    image_patches = {
        name: v81.v80.v79.v78.v77.v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }

    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v82_sha256": base_hashes[name],
            "matches_v82": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [
        name for name in FILES
        if not files[name]["matches_v82"]
    ]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V83 partition delta: {changed}")

    manifest = {
        "build": "y2-v83-boot-settings-ipc",
        "status": "offline validation required; physical release gate required",
        "base": {
            "zip": BASE_ZIP.name,
            "sha256": BASE_SHA256,
            "note": "V82 is comparison-only and remains rejected.",
        },
        "v82_physical_finding": (
            "run-as returned success while staging an empty private request; "
            "409 receives produced zero acknowledgements and no reboot"
        ),
        "behavior_delta": [
            "The Rockbox app exposes a single-purpose boot-route ContentProvider in an isolated process.",
            "Provider code accepts requests only from the Rockbox UID and broker operations only from root, system or shell UIDs.",
            "Both the app and root guard validate the complete six-permutation route contract.",
            "The root guard uses Android's packaged content command and Binder instead of reading or replacing app-private files.",
            "A successful response atomically consumes the request; malformed provider output is quarantined before any receipt log.",
            "The root-owned 0600 route map, exact reread, acknowledgement delay and reboot contract are preserved.",
            "All playback libraries, Rockbox resources, branding, LK, logo, key timing, haptic and unrelated firmware partitions are unchanged.",
        ],
        "ipc": {
            "authority": "org.rockbox.y2.bootroutes",
            "request_uri": "content://org.rockbox.y2.bootroutes/request",
            "response_uri": "content://org.rockbox.y2.bootroutes/response",
            "command": "/system/bin/content",
            "storage": "provider-private SharedPreferences",
            "world_writable_files": False,
            "shared_storage_mailbox": False,
            "selinux_permissive_change": False,
        },
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }

    report_json = "y2-v83-boot-settings-ipc.json"
    report_md = "y2-v83-boot-settings-ipc.md"
    test_txt = "V83-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / report_md).write_text(
        "# Y2 V83 Boot Settings IPC\n\n"
        "V83 replaces V82's rejected run-as private-file bridge with a "
        "single-purpose, caller-UID-gated Android ContentProvider. The app "
        "and root broker independently validate the route permutation; the "
        "root-owned route map and verified acknowledgement/reboot contract "
        "remain unchanged.\n",
        encoding="utf-8",
    )
    (OUT / test_txt).write_text(
        "Y2 V83 BOOT SETTINGS IPC - PHYSICAL RELEASE GATE\n"
        "1. Flash the complete package with Download Only. NEVER use Format All.\n"
        "2. Boot with Volume Down; require the Boot Settings screen without a black/static delay.\n"
        "3. Save No button=Y2 Stock, Volume Up=Rockbox, Volume Down=Boot Settings.\n"
        "4. Require Saving..., Saved - restarting..., and automatic restart within 20 seconds.\n"
        "5. Cold boot all three inputs and require the saved destinations.\n"
        "6. Save the same map again; require the same acknowledgement and restart.\n"
        "7. Attempt a duplicate assignment; require local rejection with the saved map intact.\n"
        "8. Restore the default map and confirm it across all three cold boots.\n"
        "9. Hold both volume buttons at cold boot; require the fixed fastboot safety route.\n"
        "10. Recheck playback, controls, five sleep/wake cycles, three-second power, USB round-trip and theme persistence.\n"
        "11. Power off and preserve the complete Y2_V83_DEBUG folder and V83 root markers.\n"
        "12. Require one non-empty ID across received, verified, acknowledged and reboot events, with no timeout or repeated malformed-request loop.\n",
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
            raise RuntimeError("V83 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(
        f"{digest} *{ZIP.name}\n",
        encoding="ascii",
    )
    print(json.dumps({
        "zip": str(ZIP),
        "size": ZIP.stat().st_size,
        "sha256": digest,
        "changed_from_v82": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
