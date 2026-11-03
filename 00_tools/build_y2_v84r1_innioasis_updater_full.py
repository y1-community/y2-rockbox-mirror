#!/usr/bin/env python3
"""Build the full-package V84R1 revision required by Innioasis Updater.

The installed Windows updater invokes SP Flash Tool with
``-c format-download``. A selective three-partition package is therefore
unsafe with that frontend: it is formatted as a full restore but does not
contain the preloader, partition tables, or the remaining stock images.

V84R1 changes packaging only. Firmware image bytes come from the reproduced
V84 full package, while the scatter and every non-V84 restore image are bound
to the official Y2 3.1.7 package.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
V84_FULL = WORK / "y2-v84-coherent-boot-settings.zip"
V84_FULL_SHA256 = (
    "DFE8A8E4D1D765C85383C8AC0B381681260FECCC75F92992775571AA39778BDB"
)
STOCK = (
    ROOT / "Y2 - Stock" / "y2_v3.1.7-20260601"
    / "y2_v3.1.7-20260601"
)
OUT = WORK / "y2-v84r1-innioasis-updater-full.zip"
OUT_SHA = WORK / "y2-v84r1-innioasis-updater-full.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 28, 23, 45, 0)

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
V84_CHANGED_IMAGES = {
    "lk.bin",
    "boot.img",
    "recovery.img",
    "logo.bin",
    "system.img",
}
STOCK_BOUND_IMAGES = {
    name for name in FIRMWARE_FILES
    if name not in V84_CHANGED_IMAGES
    and name != "MT6582_Android_scatter.txt"
}
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
    if not V84_FULL.is_file() or sha256(V84_FULL) != V84_FULL_SHA256:
        raise RuntimeError("Reproduced V84 full package is missing or drifted")
    for name in FIRMWARE_FILES:
        if not (STOCK / name).is_file():
            raise RuntimeError(f"Official stock file missing: {name}")

    with zipfile.ZipFile(V84_FULL) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V84 full package failed CRC")
        missing = [name for name in FIRMWARE_FILES
                   if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V84 full package incomplete: {missing}")
        members = {name: archive.read(name) for name in FIRMWARE_FILES}

    stock_scatter = (STOCK / "MT6582_Android_scatter.txt").read_bytes()
    if members["MT6582_Android_scatter.txt"] != stock_scatter:
        raise RuntimeError("V84 scatter drifted from official Y2 3.1.7")
    selected = parse_selected(stock_scatter)
    if selected != EXPECTED_SELECTED:
        raise RuntimeError(f"Unexpected full-restore selection: {selected}")
    missing_selected = [
        file_name for file_name in selected.values()
        if file_name not in members
    ]
    if missing_selected:
        raise RuntimeError(
            f"Selected full-restore images absent: {missing_selected}")

    stock_binding: dict[str, dict[str, object]] = {}
    for name in sorted(STOCK_BOUND_IMAGES):
        stock_data = (STOCK / name).read_bytes()
        exact = members[name] == stock_data
        stock_binding[name] = {
            "exact_official_stock": exact,
            "sha256": sha256_bytes(members[name]),
        }
        if not exact:
            raise RuntimeError(f"Restore image drifted from stock: {name}")

    image_hashes = {
        name: sha256_bytes(data)
        for name, data in sorted(members.items())
        if name != "MT6582_Android_scatter.txt"
    }
    manifest = {
        "package": "y2-v84r1-innioasis-updater-full",
        "firmware_build": "y2-v84-coherent-boot-settings",
        "packaging_revision": "V84R1",
        "reason": (
            "InnioasisUpdater 1.1.2 hardcodes SP Flash Tool "
            "-c format-download; the rejected V84 three-partition package "
            "was incompatible with that frontend"
        ),
        "mode_required_by_installed_updater": "format-download",
        "full_restore_selected_partitions": selected,
        "selected_partition_count": len(selected),
        "preloader_exact_official_stock": (
            stock_binding["preloader_eastaeon82_wet_kk.bin"]
            ["exact_official_stock"]
        ),
        "stock_bound_images": stock_binding,
        "v84_changed_images": sorted(V84_CHANGED_IMAGES),
        "image_sha256": image_hashes,
        "v84_full_base": {
            "file": V84_FULL.name,
            "sha256": V84_FULL_SHA256,
        },
        "physical_status": (
            "offline validated; use first as a recovery candidate only after "
            "explicit approval and the official-stock recovery decision"
        ),
    }
    readme = (
        "Y2 V84R1 - FULL INNIOASIS UPDATER PACKAGE\n\n"
        "The earlier y2-v84-required-three-partition-update.zip is rejected "
        "for InnioasisUpdater 1.1.2. That updater invokes SP Flash Tool with "
        "format-download, which erases the full eMMC before writing selected "
        "images.\n\n"
        "This V84R1 archive contains the complete official Y2 3.1.7 restore "
        "set, with the intended V84 lk, boot, recovery, logo and system "
        "images. Its preloader, partition tables, secro, cache and userdata "
        "images are exact official-stock bytes.\n\n"
        "Physical status: offline validated, not yet physically approved. "
        "Because the failed attempt already formatted the device, restore "
        "official stock first unless the recovery checklist explicitly "
        "authorizes this combined recovery/test package.\n"
    ).encode("utf-8")
    members["V84R1-READ-ME-FIRST.txt"] = readme
    members["y2-v84r1-innioasis-updater-full.json"] = (
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
        "stock_bound_images": sorted(STOCK_BOUND_IMAGES),
        "v84_changed_images": sorted(V84_CHANGED_IMAGES),
    }, indent=2))


if __name__ == "__main__":
    main()
