#!/usr/bin/env python3
"""Build V84 with a stable boot launcher and system-coherent save broker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE_ZIP = WORK / "y2-v83-boot-settings-ipc.zip"
BASE_SHA256 = "C704816312BDC4D156B493D3ED4E319DC225D7CED2934408D28880EF8CEEB63F"
V84_SYSTEM = (
    WORK
    / "y2-rockbox-system-prototype-v84-coherent-boot-settings"
    / "system.img"
)
V84_APK = (
    WORK
    / "rockbox-android-y2-v84-coherent-boot-settings"
    / "rockbox-y2-v84-coherent-boot-settings.apk"
)
SYSTEM_BROKER = ROOT / "00_tools" / "y2_v84_boot_route_broker.sh"
OUT = WORK / "y2-v84-coherent-boot-settings"
ZIP = WORK / "y2-v84-coherent-boot-settings.zip"
ZIP_SHA = WORK / "y2-v84-coherent-boot-settings.zip.sha256.txt"
UPDATE_ZIP = WORK / "y2-v84-required-three-partition-update.zip"
UPDATE_SHA = WORK / "y2-v84-required-three-partition-update.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 28, 23, 15, 0)
CPIO_MTIME = 1785251700

UPDATE_SCATTER = "MT6582_Android_scatter_V84_REQUIRED.txt"
UPDATE_IMAGES = {
    "BOOTIMG": ("boot.img", "V84_BOOTIMG_REQUIRED.img"),
    "RECOVERY": ("recovery.img", "V84_RECOVERY_REQUIRED.img"),
    "ANDROID": ("system.img", "V84_SYSTEM_REQUIRED.img"),
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v83 = load(
    "v83_builder_base",
    ROOT / "00_tools" / "build_y2_v83_boot_settings_ipc.py",
)
v81 = v83.v81
FILES = v83.FILES
ROUTE_GUARD = v83.ROUTE_GUARD


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def v84_route_guard() -> bytes:
    """Replace the versioned broker with a stable system-helper launcher."""

    text = v83.v83_route_guard().decode("ascii")
    text = text.replace(
        'BUILD="y2-v83-boot-settings-ipc"',
        'BUILD="y2-v84-stable-broker-launcher-v1"',
        1,
    )
    text = text.replace(
        'DATA_ROOT="/data/local/tmp/Y2_V83_DEBUG"',
        'DATA_ROOT="/data/local/tmp/Y2_V84_DEBUG"',
        1,
    )
    old_constants = (
        'CONTENT="/system/bin/content"\n'
        'REQUEST_URI="content://org.rockbox.y2.bootroutes/request"\n'
        'RESPONSE_URI="content://org.rockbox.y2.bootroutes/response"\n'
        'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"\n'
        'LAST_QUERY_ERROR=""\n'
    )
    new_constants = (
        'BROKER_HELPER="/system/etc/y2_boot_route_broker.sh"\n'
        'SYSTEM_SHELL="/system/bin/sh"\n'
        'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"\n'
        'BROKER_READY=0\n'
        'BROKER_ERROR=""\n'
        'BROKER_POLL_ERROR=""\n'
    )
    if text.count(old_constants) != 1:
        raise RuntimeError("V84 guard constants anchor drifted")
    text = text.replace(old_constants, new_constants, 1)

    broker_start = text.index("query_value() {")
    broker_end = text.index('\nlog_event "guard=start', broker_start)
    launcher = r'''run_settings_broker() {
    if [ ! -r "$BROKER_HELPER" ]; then
        CURRENT_BROKER_ERROR="helper-missing path=$BROKER_HELPER"
        if [ "$CURRENT_BROKER_ERROR" != "$BROKER_ERROR" ]; then
            log_event "settings_broker=unavailable $CURRENT_BROKER_ERROR"
            BROKER_ERROR="$CURRENT_BROKER_ERROR"
        fi
        BROKER_READY=0
        return
    fi

    if [ "$BROKER_READY" -ne 1 ]; then
        BROKER_OUTPUT=$("$SYSTEM_SHELL" "$BROKER_HELPER" ready \
            "$ROUTE" "$BOOT_ID" "$LOG" 2>&1)
        BROKER_EXIT=$?
        if [ "$BROKER_EXIT" -eq 0 ]; then
            BROKER_READY=1
            BROKER_ERROR=""
            log_event "settings_broker=launcher-ready helper=$BROKER_HELPER boot_id=$BOOT_ID"
        else
            CURRENT_BROKER_ERROR="helper-ready-failed exit=$BROKER_EXIT output=$BROKER_OUTPUT"
            if [ "$CURRENT_BROKER_ERROR" != "$BROKER_ERROR" ]; then
                log_event "settings_broker=unavailable $CURRENT_BROKER_ERROR"
                BROKER_ERROR="$CURRENT_BROKER_ERROR"
            fi
            return
        fi
    fi

    BROKER_OUTPUT=$("$SYSTEM_SHELL" "$BROKER_HELPER" poll \
        "$ROUTE" "$BOOT_ID" "$LOG" 2>&1)
    BROKER_EXIT=$?
    if [ "$BROKER_EXIT" -eq 0 ]; then
        BROKER_POLL_ERROR=""
        return
    fi
    CURRENT_POLL_ERROR="helper-poll-failed exit=$BROKER_EXIT output=$BROKER_OUTPUT"
    if [ "$CURRENT_POLL_ERROR" != "$BROKER_POLL_ERROR" ]; then
        log_event "settings_broker=helper-error $CURRENT_POLL_ERROR"
        BROKER_POLL_ERROR="$CURRENT_POLL_ERROR"
    fi
}
'''
    text = text[:broker_start] + launcher + text[broker_end + 1 :]
    if text.count("    process_settings_request\n") != 1:
        raise RuntimeError("V84 guard loop anchor drifted")
    text = text.replace(
        "    process_settings_request\n",
        "    run_settings_broker\n",
        1,
    )
    return text.encode("ascii")


def targeted_scatter(data: bytes) -> bytes:
    text = data.decode("ascii")
    blocks = re.split(r"(?=^- partition_index:)", text, flags=re.MULTILINE)
    seen: set[str] = set()
    output: list[str] = []
    for block in blocks:
        match = re.search(r"^  partition_name: (.+)$", block, re.MULTILINE)
        if match is None:
            output.append(block)
            continue
        partition = match.group(1).strip()
        if partition in UPDATE_IMAGES:
            seen.add(partition)
            file_name = UPDATE_IMAGES[partition][1]
            block = re.sub(
                r"^  file_name: .+$",
                f"  file_name: {file_name}",
                block,
                count=1,
                flags=re.MULTILINE,
            )
            block = re.sub(
                r"^  is_download: .+$",
                "  is_download: true",
                block,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            block = re.sub(
                r"^  file_name: .+$",
                "  file_name: NONE",
                block,
                count=1,
                flags=re.MULTILINE,
            )
            block = re.sub(
                r"^  is_download: .+$",
                "  is_download: false",
                block,
                count=1,
                flags=re.MULTILINE,
            )
        output.append(block)
    if seen != set(UPDATE_IMAGES):
        raise RuntimeError(f"Targeted scatter missing partitions: {seen}")
    result = "".join(output)
    if result.count("  is_download: true") != 3:
        raise RuntimeError("Targeted scatter does not select exactly 3 partitions")
    return result.encode("ascii")


def deterministic_zip(path: Path, members: dict[str, bytes]) -> None:
    if path.exists():
        path.unlink()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, members[name])
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"ZIP failed CRC: {path}")


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("V83 comparison base is missing or drifted")
    for required in (V84_SYSTEM, V84_APK, SYSTEM_BROKER):
        if not required.is_file():
            raise RuntimeError(f"Missing V84 input: {required}")
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V83 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V83 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != WORK.resolve() or OUT.name != (
            "y2-v84-coherent-boot-settings"):
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
    shutil.copyfile(V84_SYSTEM, OUT / "system.img")

    v81.v80.v79.v78.v77.v76.OUT = OUT
    v81.v80.v79.v78.v77.v76.CPIO_MTIME = CPIO_MTIME
    payloads = {ROUTE_GUARD: v84_route_guard()}
    image_patches = {
        name: v81.v80.v79.v78.v77.v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }

    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v83_sha256": base_hashes[name],
            "matches_v83": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [
        name for name in FILES
        if not files[name]["matches_v83"]
    ]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V84 partition delta: {changed}")

    manifest = {
        "build": "y2-v84-coherent-boot-settings",
        "status": "offline validation required; physical release gate required",
        "base": {"zip": BASE_ZIP.name, "sha256": BASE_SHA256},
        "physical_root_cause": (
            "V83 app/system was present while the live boot guard still "
            "identified as y2-v81-continuous-handoff"
        ),
        "architecture": {
            "boot_recovery": "stable system-helper launcher v1",
            "system_helper": "/system/etc/y2_boot_route_broker.sh",
            "protocol": "2",
            "coherence": (
                "app and changing broker are shipped together in system.img"
            ),
            "handshake": (
                "exact protocol, broker build and current Linux boot ID"
            ),
        },
        "safety": {
            "world_writable_files": False,
            "shared_storage_mailbox": False,
            "selinux_permissive_change": False,
            "route_map_mode": "0600",
            "targeted_update_partitions": [
                "BOOTIMG", "RECOVERY", "ANDROID"
            ],
        },
        "image_patches": image_patches,
        "files": files,
    }
    report_json = "y2-v84-coherent-boot-settings.json"
    report_md = "y2-v84-coherent-boot-settings.md"
    test_txt = "V84-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / report_md).write_text(
        "# Y2 V84 Coherent Boot Settings\n\n"
        "V84 detects incomplete cross-partition installs before Save, uses "
        "an exact current-boot handshake, and moves the changing root broker "
        "into system.img beside the Rockbox app. Boot and recovery contain "
        "only a stable launcher for that system helper.\n",
        encoding="utf-8",
    )
    (OUT / test_txt).write_text(
        "Y2 V84 COHERENT BOOT SETTINGS - PHYSICAL GATE\n"
        "Use the required three-partition update ZIP and Download Only.\n"
        "Never use Format All or Firmware Upgrade.\n"
        "Confirm all three selected rows are V84_BOOTIMG_REQUIRED.img, "
        "V84_RECOVERY_REQUIRED.img and V84_SYSTEM_REQUIRED.img.\n"
        "Boot Volume Down and require Firmware ready before Save is enabled.\n"
        "Save the changed map and the unchanged map; each must show "
        "Saved - restarting... and automatically reboot.\n"
        "Any firmware-incomplete message, timeout or missing reboot fails "
        "the gate.\n",
        encoding="utf-8",
    )

    full_members = {
        name: (OUT / name).read_bytes()
        for name in (*FILES, report_json, report_md, test_txt)
    }
    deterministic_zip(ZIP, full_members)
    ZIP_SHA.write_text(
        f"{sha256(ZIP)} *{ZIP.name}\n",
        encoding="ascii",
    )

    scatter = targeted_scatter(
        (OUT / "MT6582_Android_scatter.txt").read_bytes()
    )
    update_files = {
        target_name: (OUT / source_name).read_bytes()
        for source_name, target_name in UPDATE_IMAGES.values()
    }
    update_hashes = {
        name: sha256_bytes(data)
        for name, data in update_files.items()
    }
    update_manifest = {
        "build": manifest["build"],
        "mode": "SP Flash Tool Download Only",
        "required_partitions": UPDATE_IMAGES,
        "image_sha256": update_hashes,
        "all_three_required": True,
        "format_all_forbidden": True,
    }
    readme = (
        "V84 REQUIRED THREE-PARTITION UPDATE\n\n"
        "This package intentionally selects only BOOTIMG, RECOVERY and "
        "ANDROID. All three are required because the current device evidence "
        "shows a V83 system with a stale V81 boot guard.\n\n"
        "Use Download Only. Never use Format All or Firmware Upgrade. Load "
        f"{UPDATE_SCATTER} from this directory. Confirm exactly three rows "
        "are selected and their paths remain inside this extracted V84 "
        "directory. Stop if any row is unchecked or any path differs.\n"
    ).encode("utf-8")
    hash_text = "".join(
        f"{digest} *{name}\n"
        for name, digest in sorted(update_hashes.items())
    ).encode("ascii")
    update_members = {
        UPDATE_SCATTER: scatter,
        **update_files,
        "V84-READ-ME-FIRST.txt": readme,
        "V84-REQUIRED-SHA256.txt": hash_text,
        "y2-v84-targeted-update.json": (
            json.dumps(update_manifest, indent=2) + "\n"
        ).encode("utf-8"),
    }
    deterministic_zip(UPDATE_ZIP, update_members)
    UPDATE_SHA.write_text(
        f"{sha256(UPDATE_ZIP)} *{UPDATE_ZIP.name}\n",
        encoding="ascii",
    )
    print(json.dumps({
        "full_zip": str(ZIP),
        "full_size": ZIP.stat().st_size,
        "full_sha256": sha256(ZIP),
        "update_zip": str(UPDATE_ZIP),
        "update_size": UPDATE_ZIP.stat().st_size,
        "update_sha256": sha256(UPDATE_ZIP),
        "changed_partitions": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
