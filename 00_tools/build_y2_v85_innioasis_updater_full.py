#!/usr/bin/env python3
"""Build V85 as a complete InnioasisUpdater format-download package."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE = WORK / "y2-v84r1-innioasis-updater-full.zip"
BASE_SHA256 = (
    "5E503D03E4615F14AE4EE307DBED14172A2240379CBD1AD89418F35DFE78A263"
)
V85_SYSTEM = (
    WORK / "y2-rockbox-system-prototype-v85-simple-boot-choice"
    / "system.img"
)
STOCK = (
    ROOT / "Y2 - Stock" / "y2_v3.1.7-20260601"
    / "y2_v3.1.7-20260601"
)
OUT = WORK / "y2-v85-simple-boot-choice-innioasis-full.zip"
OUT_SHA = (
    WORK / "y2-v85-simple-boot-choice-innioasis-full.zip.sha256.txt"
)
ZIP_TIMESTAMP = (2026, 7, 28, 23, 55, 0)

FIRMWARE_FILES = (
    "preloader_eastaeon82_wet_kk.bin",
    "MBR",
    "EBR1",
    "lk.bin",
    "boot.img",
    "recovery.img",
    "secro.img",
    "logo.bin",
    "EBR2",
    "system.img",
    "cache.img",
    "userdata.img",
    "MT6582_Android_scatter.txt",
)
EXPECTED_SELECTED = {
    "PRELOADER": "preloader_eastaeon82_wet_kk.bin",
    "MBR": "MBR",
    "EBR1": "EBR1",
    "UBOOT": "lk.bin",
    "BOOTIMG": "boot.img",
    "RECOVERY": "recovery.img",
    "SEC_RO": "secro.img",
    "LOGO": "logo.bin",
    "EBR2": "EBR2",
    "ANDROID": "system.img",
    "CACHE": "cache.img",
    "USRDATA": "userdata.img",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def parse_selected(scatter: bytes) -> dict[str, str]:
    text = scatter.decode("ascii")
    selected: dict[str, str] = {}
    for block in re.split(
            r"(?=^- partition_index:)", text, flags=re.MULTILINE):
        name_match = re.search(
            r"^  partition_name: (.+)$", block, flags=re.MULTILINE)
        file_match = re.search(
            r"^  file_name: (.+)$", block, flags=re.MULTILINE)
        download_match = re.search(
            r"^  is_download: (.+)$", block, flags=re.MULTILINE)
        if not (name_match and file_match and download_match):
            continue
        if download_match.group(1).strip() == "true":
            selected[name_match.group(1).strip()] = (
                file_match.group(1).strip()
            )
    return selected


def deterministic_zip(path: Path, members: dict[str, bytes]) -> None:
    if path.exists():
        path.unlink()
    with zipfile.ZipFile(
            path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, members[name])
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP CRC failed at {bad}")


def main() -> None:
    if not BASE.is_file() or sha256(BASE) != BASE_SHA256:
        raise RuntimeError("Validated V84R1 full base is missing or drifted")
    if not V85_SYSTEM.is_file():
        raise RuntimeError(f"V85 system image is missing: {V85_SYSTEM}")

    with zipfile.ZipFile(BASE) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V84R1 full base failed CRC")
        missing = [
            name for name in FIRMWARE_FILES
            if name not in archive.namelist()
        ]
        if missing:
            raise RuntimeError(f"V84R1 base incomplete: {missing}")
        members = {
            name: archive.read(name)
            for name in FIRMWARE_FILES
        }

    base_system_hash = sha256_bytes(members["system.img"])
    members["system.img"] = V85_SYSTEM.read_bytes()
    if sha256_bytes(members["system.img"]) == base_system_hash:
        raise RuntimeError("V85 system image unexpectedly matches V84R1")

    stock_scatter = (STOCK / "MT6582_Android_scatter.txt").read_bytes()
    if members["MT6582_Android_scatter.txt"] != stock_scatter:
        raise RuntimeError("Full package scatter drifted from official stock")
    selected = parse_selected(stock_scatter)
    if selected != EXPECTED_SELECTED:
        raise RuntimeError(f"Unexpected full-restore selection: {selected}")
    if any(name not in members for name in selected.values()):
        raise RuntimeError("A selected full-restore image is absent")

    manifest = {
        "package": "y2-v85-simple-boot-choice-innioasis-full",
        "firmware_build": "y2-v85-simple-boot-choice",
        "base": {
            "file": BASE.name,
            "sha256": BASE_SHA256,
        },
        "behavior": {
            "normal_boot_choice": ["rockbox", "stock"],
            "volume_up": "opposite of normal boot choice",
            "volume_down": "settings",
            "both_volume_buttons": "fixed fastboot safety route",
        },
        "save_protocol": {
            "version": "3",
            "request_fields": [
                "protocol_version",
                "boot_id",
                "request_id",
                "normal_boot",
                "reboot",
            ],
            "preflight_compatibility_gate": False,
            "unchanged_choice_is_verified": True,
            "root_atomic_write": True,
            "root_reread_before_ack": True,
            "reboot_after_ack": True,
        },
        "mode_required_by_installed_updater": "format-download",
        "full_restore_selected_partitions": selected,
        "selected_partition_count": len(selected),
        "changed_from_v84r1": ["system.img"],
        "image_sha256": {
            name: sha256_bytes(data)
            for name, data in sorted(members.items())
            if name != "MT6582_Android_scatter.txt"
        },
        "physical_status": (
            "offline validation required; not release-approved until the "
            "physical flash and two-choice boot matrix pass"
        ),
    }
    readme = (
        "Y2 V85 - SIMPLE BOOT CHOICE - FULL INNIOASIS UPDATER PACKAGE\n\n"
        "Boot Settings now selects only what starts with no volume button: "
        "Rockbox or Y2 Stock. Volume Up automatically starts the other "
        "player. Volume Down always opens Boot Settings, and both volume "
        "buttons retain the fixed fastboot safety route.\n\n"
        "There is no firmware compatibility preflight screen. Save submits "
        "the single choice to the root helper; success is shown only after "
        "the map is atomically written, reread and acknowledged. Saving an "
        "unchanged choice is supported and performs the same verification.\n\n"
        "This is a complete 12-partition package because InnioasisUpdater "
        "1.1.2 invokes SP Flash Tool in format-download mode. It must not be "
        "repackaged as a selective three-partition archive.\n\n"
        "Physical status: offline validation required; not release-approved "
        "until flash, cold-boot routing, save/reboot and rollback pass.\n"
    ).encode("utf-8")
    members["V85-READ-ME-FIRST.txt"] = readme
    members["y2-v85-simple-boot-choice-innioasis-full.json"] = (
        json.dumps(manifest, indent=2) + "\n"
    ).encode("utf-8")

    deterministic_zip(OUT, members)
    OUT_SHA.write_text(
        f"{sha256(OUT)} *{OUT.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(OUT),
        "bytes": OUT.stat().st_size,
        "sha256": sha256(OUT),
        "selected_partitions": selected,
        "changed_from_v84r1": ["system.img"],
    }, indent=2))


if __name__ == "__main__":
    main()
