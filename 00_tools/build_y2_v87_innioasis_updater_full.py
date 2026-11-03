#!/usr/bin/env python3
"""Build V87 with a vendor-shell-compatible save broker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE = WORK / "y2-v86-boot-save-repair-innioasis-full.zip"
BASE_SHA256 = (
    "6E7E5DA2A39FC86BEA0CEAE32BFE179D0634F7F9304251DA3A28785E6795D7F8"
)
V87_SYSTEM = (
    WORK / "y2-rockbox-system-prototype-v87-vendor-shell-save"
    / "system.img"
)
IMAGE_WORK = WORK / "y2-v87-vendor-shell-save-images"
OUT = WORK / "y2-v87-vendor-shell-save-innioasis-full.zip"
OUT_SHA = WORK / "y2-v87-vendor-shell-save-innioasis-full.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 29, 6, 30, 0)
CPIO_MTIME = 1785342600


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v86 = load(
    "v86_full_builder",
    ROOT / "00_tools" / "build_y2_v86_innioasis_updater_full.py",
)
FIRMWARE_FILES = v86.FIRMWARE_FILES
EXPECTED_SELECTED = v86.EXPECTED_SELECTED


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def v87_route_guard() -> bytes:
    text = v86.v86_route_guard().decode("ascii")
    old = 'BUILD="y2-v86-stable-broker-launcher-v2"'
    new = 'BUILD="y2-v87-stable-broker-launcher-v3"'
    if text.count(old) != 1:
        raise RuntimeError("V87 guard build anchor drifted")
    return text.replace(old, new, 1).encode("ascii")


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


def patch_boot_images(members: dict[str, bytes]) -> dict[str, object]:
    if IMAGE_WORK.resolve().parent != WORK.resolve():
        raise RuntimeError(f"Unsafe V87 image work path: {IMAGE_WORK}")
    if IMAGE_WORK.exists():
        shutil.rmtree(IMAGE_WORK)
    IMAGE_WORK.mkdir(parents=True)
    for name in ("boot.img", "recovery.img"):
        (IMAGE_WORK / name).write_bytes(members[name])

    patcher = v86.v84.v81.v80.v79.v78.v77.v76
    patcher.OUT = IMAGE_WORK
    patcher.CPIO_MTIME = CPIO_MTIME
    payloads = {v86.v84.ROUTE_GUARD: v87_route_guard()}
    patches = {
        name: patcher.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }
    for name in patches:
        members[name] = (IMAGE_WORK / name).read_bytes()
    return patches


def main() -> None:
    if not BASE.is_file() or sha256(BASE) != BASE_SHA256:
        raise RuntimeError("Validated V86 full base is missing or drifted")
    if not V87_SYSTEM.is_file():
        raise RuntimeError(f"V87 system image is missing: {V87_SYSTEM}")

    with zipfile.ZipFile(BASE) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V86 full base failed CRC")
        missing = [
            name for name in FIRMWARE_FILES
            if name not in archive.namelist()
        ]
        if missing:
            raise RuntimeError(f"V86 base incomplete: {missing}")
        members = {
            name: archive.read(name)
            for name in FIRMWARE_FILES
        }
    base_hashes = {
        name: sha256_bytes(data)
        for name, data in members.items()
    }

    image_patches = patch_boot_images(members)
    members["system.img"] = V87_SYSTEM.read_bytes()
    changed = [
        name for name in FIRMWARE_FILES
        if sha256_bytes(members[name]) != base_hashes[name]
    ]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V87 partition delta: {changed}")

    selected = v86.v85.parse_selected(
        members["MT6582_Android_scatter.txt"])
    if selected != EXPECTED_SELECTED:
        raise RuntimeError(f"Unexpected full-restore selection: {selected}")
    if any(name not in members for name in selected.values()):
        raise RuntimeError("A selected full-restore image is absent")

    manifest = {
        "package": "y2-v87-vendor-shell-save-innioasis-full",
        "firmware_build": "y2-v87-vendor-shell-save",
        "base": {"file": BASE.name, "sha256": BASE_SHA256},
        "physical_evidence": {
            "v86_provider_handshake": "passed",
            "v86_request_rejections": 4,
            "v86_status": "error-write-failed",
            "root_cause": "vendor shell reports printf: not found",
        },
        "repair": {
            "printf_removed_from_device_broker": True,
            "route_map_writer": "echo block, 0600 temp, atomic rename",
            "provider_health_probe": True,
            "root_reread_before_ack": True,
            "reboot_after_ack": True,
        },
        "behavior": {
            "normal_boot_default": "rockbox",
            "normal_boot_choice": ["rockbox", "stock"],
            "volume_up": "opposite of normal boot choice",
            "volume_down": "settings",
            "both_volume_buttons": "fixed fastboot safety route",
        },
        "mode_required_by_installed_updater": "format-download",
        "full_restore_selected_partitions": selected,
        "selected_partition_count": len(selected),
        "changed_from_v86": changed,
        "image_patches": image_patches,
        "image_sha256": {
            name: sha256_bytes(data)
            for name, data in sorted(members.items())
            if name != "MT6582_Android_scatter.txt"
        },
        "physical_status": (
            "offline validation required; not release-approved until the "
            "physical save and route matrix passes"
        ),
    }
    readme = (
        "Y2 V87 - VENDOR-SHELL SAVE - FULL INNIOASIS PACKAGE\n\n"
        "V86 proved the provider handshake and exact root failure: the Y2 "
        "Android shell does not provide printf. V87 removes every printf from "
        "the device-side broker and writes the verified route map with echo, "
        "0600 permissions and atomic rename.\n\n"
        "Normal boot defaults to Rockbox. Volume Up starts the other player, "
        "Volume Down opens Boot Settings, and both volume buttons retain "
        "fastboot.\n\n"
        "This is a complete 12-partition package because InnioasisUpdater "
        "1.1.2 invokes SP Flash Tool in format-download mode.\n\n"
        "Physical status: not release-approved until the save/restart and "
        "cold-boot route matrix passes on the Y2.\n"
    ).encode("utf-8")
    members["V87-READ-ME-FIRST.txt"] = readme
    members["y2-v87-vendor-shell-save-innioasis-full.json"] = (
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
        "changed_from_v86": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
