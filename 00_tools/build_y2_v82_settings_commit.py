"""Build V82: minimal run-as bridge for the Boot Settings save broker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE_ZIP = WORK / "y2-v81-continuous-handoff.zip"
BASE_SHA256 = "3569C71678F772272FFB7E6036F298C80C53DAA447673A7A300322C292473C8E"
OUT = WORK / "y2-v82-settings-commit"
ZIP = WORK / "y2-v82-settings-commit.zip"
ZIP_SHA = WORK / "y2-v82-settings-commit.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 26, 12, 0, 0)
CPIO_MTIME = 1785031200


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v81 = load(
    "v81_builder_base",
    ROOT / "00_tools" / "build_y2_v81_continuous_handoff.py",
)
FILES = v81.FILES
ROUTE_GUARD = v81.ROUTE_GUARD


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


def v82_route_guard() -> bytes:
    """Patch only the V81 guard's app-private request transport.

    The V81 physical evidence proved that the init_shell broker runs and sees
    the request inode, but it cannot read or replace the app-owned 0600 file.
    Android's run-as command is present in the unchanged V81 system image, and
    org.rockbox is debuggable, so run-as supplies the intended package-UID
    boundary without weakening file modes or SELinux.
    """

    text = v81.v81_route_guard().decode("ascii")
    text = text.replace(
        'BUILD="y2-v81-continuous-handoff"',
        'BUILD="y2-v82-settings-commit"',
        1,
    )
    anchor = (
        'SETTINGS_REQUEST="/data/data/org.rockbox/files/'
        'y2_boot_routes.request"\n'
        'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"\n'
    )
    replacement = anchor + (
        'APP_PACKAGE="org.rockbox"\n'
        'APP_REQUEST_RELATIVE="files/y2_boot_routes.request"\n'
        'RUN_AS="/system/bin/run-as"\n'
    )
    if text.count(anchor) != 1:
        raise RuntimeError("V82 request constant anchor drifted")
    text = text.replace(anchor, replacement, 1)

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
    new = r'''stage_settings_request() {
    REQUEST_COPY_TMP="$DATA_ROOT/.settings-request-$BOOT_ID.$$"
    REQUEST_COPY="$DATA_ROOT/settings-request-$BOOT_ID.txt"
    if "$RUN_AS" "$APP_PACKAGE" /system/bin/cat \
            "$APP_REQUEST_RELATIVE" > "$REQUEST_COPY_TMP" 2>/dev/null &&
       chmod 0600 "$REQUEST_COPY_TMP" &&
       mv "$REQUEST_COPY_TMP" "$REQUEST_COPY"; then
        return 0
    fi
    rm -f "$REQUEST_COPY_TMP"

    # Direct access is retained only as a compatibility fallback. V81
    # physical evidence showed that this path cannot read the app's 0600
    # request on the production SELinux/DAC configuration.
    if cp "$SETTINGS_REQUEST" "$REQUEST_COPY_TMP" 2>/dev/null &&
       chmod 0600 "$REQUEST_COPY_TMP" &&
       mv "$REQUEST_COPY_TMP" "$REQUEST_COPY"; then
        return 0
    fi
    rm -f "$REQUEST_COPY_TMP"
    return 1
}

write_response() {
    RESPONSE_STATUS="$1"
    RESPONSE_PAYLOAD="$DATA_ROOT/.settings-response-$BOOT_ID.$$"
    if ! printf '%s\n' "request_id=$REQUEST_ID" \
            "status=$RESPONSE_STATUS" > "$RESPONSE_PAYLOAD"; then
        rm -f "$RESPONSE_PAYLOAD"
        return 1
    fi
    chmod 0600 "$RESPONSE_PAYLOAD"

    if "$RUN_AS" "$APP_PACKAGE" /system/bin/sh -c \
            'umask 077; response_tmp=files/y2_boot_routes.request.response; cat > "$response_tmp" && mv "$response_tmp" files/y2_boot_routes.request' \
            < "$RESPONSE_PAYLOAD" 2>/dev/null; then
        rm -f "$RESPONSE_PAYLOAD"
        return 0
    fi

    # If a vendor build grants direct package-data writes, preserve the
    # existing request inode so its app ownership and private mode remain.
    if /system/bin/cat "$RESPONSE_PAYLOAD" > "$SETTINGS_REQUEST" 2>/dev/null; then
        rm -f "$RESPONSE_PAYLOAD"
        return 0
    fi
    rm -f "$RESPONSE_PAYLOAD"
    return 1
}

process_settings_request() {
    [ -f "$SETTINGS_REQUEST" ] || return
    if ! stage_settings_request; then
        log_event "settings_broker=request-access-failed transport=run-as"
        return
    fi
    REQUEST_STATUS=$(read_kv "$REQUEST_COPY" status)
    if [ -n "$REQUEST_STATUS" ]; then
        rm -f "$REQUEST_COPY"
        return
    fi

    REQUEST_VERSION=$(read_kv "$REQUEST_COPY" request_version)
    REQUEST_ID=$(read_kv "$REQUEST_COPY" request_id)
    REQUEST_NO=$(read_kv "$REQUEST_COPY" no_button)
    REQUEST_UP=$(read_kv "$REQUEST_COPY" volume_up)
    REQUEST_DOWN=$(read_kv "$REQUEST_COPY" volume_down)
    REQUEST_REBOOT=$(read_kv "$REQUEST_COPY" reboot)
    rm -f "$REQUEST_COPY"
    log_event "settings_broker=received request_id=$REQUEST_ID route=$ROUTE transport=run-as"
'''
    if text.count(old) != 1:
        raise RuntimeError("V82 request broker anchor drifted")
    return text.replace(old, new, 1).encode("ascii")


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V81 base is missing or drifted")
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V81 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V81 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if (
        OUT.resolve().parent != WORK.resolve()
        or OUT.name != "y2-v82-settings-commit"
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

    v81.v80.v79.v78.v77.v76.OUT = OUT
    v81.v80.v79.v78.v77.v76.CPIO_MTIME = CPIO_MTIME
    payloads = {ROUTE_GUARD: v82_route_guard()}
    image_patches = {
        name: v81.v80.v79.v78.v77.v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }

    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v81_sha256": base_hashes[name],
            "matches_v81": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [
        name for name in FILES
        if not files[name]["matches_v81"]
    ]
    if changed != ["boot.img", "recovery.img"]:
        raise RuntimeError(f"Unexpected V82 partition delta: {changed}")

    manifest = {
        "build": "y2-v82-settings-commit",
        "status": "offline validated candidate; physical save/reboot gate required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v81_physical_finding": {
            "request_id": "37548",
            "requested_map": {
                "no_button": "stock",
                "volume_up": "rockbox",
                "volume_down": "settings",
            },
            "observed": (
                "The session-long root broker ran, saw the private request "
                "inode, parsed empty fields, rejected it repeatedly and could "
                "not replace it with a response; the app timed out."
            ),
            "root_cause": (
                "The app-private 0600 request was accessed directly across "
                "the package UID boundary."
            ),
        },
        "behavior_delta": [
            "The root broker reads and atomically replaces the private request through Android run-as under the org.rockbox package UID.",
            "The request, staged copy, response and persisted route map retain private 0600 modes.",
            "Direct access remains only as a compatibility fallback.",
            "All V81 system/APK, LK, logo, animation, routing, haptic, theme and playback bytes are unchanged.",
        ],
        "image_patches": image_patches,
        "files": files,
        "diagnostics_note": (
            "The unchanged V81 app and collector retain V81 marker/file names; "
            "the guard log identifies build=y2-v82-settings-commit."
        ),
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }

    report_json = "y2-v82-settings-commit.json"
    report_md = "y2-v82-settings-commit.md"
    test_txt = "V82-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / report_md).write_text(
        "# Y2 V82 Settings Commit\n\n"
        "V82 is the physically tested V81 package with only the boot and "
        "recovery route-guard payload changed. The broker now crosses into "
        "the debuggable Rockbox package UID with Android run-as to read and "
        "atomically acknowledge the private Boot Settings request. Every "
        "other partition and the V81 system/APK remain byte-identical.\n",
        encoding="utf-8",
    )
    (OUT / test_txt).write_text(
        "Y2 V82 SETTINGS COMMIT - PHYSICAL RELEASE GATE\n"
        "1. Flash the complete package with Download Only. NEVER use Format All.\n"
        "2. Boot with Volume Down and confirm Boot Settings appears without a black/static delay.\n"
        "3. Set No button=Y2 Stock, Volume Up=Rockbox, Volume Down=Boot Settings.\n"
        "4. Select Save. Require Saving, then Saved - restarting, and an automatic reboot within 20 seconds.\n"
        "5. Cold boot with no button: require Y2 Stock.\n"
        "6. Cold boot with Volume Up: require Rockbox.\n"
        "7. Cold boot with Volume Down: require Boot Settings.\n"
        "8. Save the same map again to prove idempotence and automatic restart.\n"
        "9. Try a duplicate assignment: Save must be blocked locally and the current map must remain unchanged.\n"
        "10. Hold both volume buttons during cold boot: require the fixed fastboot safety route.\n"
        "11. Recheck Rockbox playback, OneBitMono width, sleep/centre wake, three-second power and USB return.\n"
        "12. After power-off, capture the V81-named debug folder; guard lines must identify y2-v82-settings-commit and show received, verified, acknowledged and reboot for one request ID.\n",
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
            raise RuntimeError("V82 ZIP failed CRC")
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
                "changed_from_v81": changed,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
