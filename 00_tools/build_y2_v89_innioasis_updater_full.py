#!/usr/bin/env python3
"""Build V89 with cached framebuffer restore after USB surface recreation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE = WORK / "y2-v88-route-readback-repair-innioasis-full.zip"
BASE_SHA256 = (
    "40636D86943F6F0A1461B6D8C9285A1A50252253447B3DC7D11743533A88E4DE"
)
V89_SYSTEM = (
    WORK / "y2-rockbox-system-prototype-v89-usb-display-restore"
    / "system.img"
)
OUT = WORK / "y2-v89-usb-display-restore-innioasis-full.zip"
OUT_SHA = WORK / "y2-v89-usb-display-restore-innioasis-full.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 29, 18, 30, 0)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v88 = load(
    "v88_full_builder",
    ROOT / "00_tools" / "build_y2_v88_innioasis_updater_full.py",
)
FIRMWARE_FILES = v88.FIRMWARE_FILES
EXPECTED_SELECTED = v88.EXPECTED_SELECTED


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    if not BASE.is_file() or sha256(BASE) != BASE_SHA256:
        raise RuntimeError("Validated V88 full base is missing or drifted")
    if not V89_SYSTEM.is_file():
        raise RuntimeError(f"V89 system image is missing: {V89_SYSTEM}")

    with zipfile.ZipFile(BASE) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V88 full base failed CRC")
        members = {
            name: archive.read(name)
            for name in FIRMWARE_FILES
        }

    base_hashes = {
        name: sha256_bytes(data)
        for name, data in members.items()
    }
    members["system.img"] = V89_SYSTEM.read_bytes()
    changed = [
        name for name in FIRMWARE_FILES
        if sha256_bytes(members[name]) != base_hashes[name]
    ]
    if changed != ["system.img"]:
        raise RuntimeError(f"Unexpected V89 partition delta: {changed}")

    selected = v88.v87.v86.v85.parse_selected(
        members["MT6582_Android_scatter.txt"])
    if selected != EXPECTED_SELECTED:
        raise RuntimeError(f"Unexpected full-restore selection: {selected}")
    if any(name not in members for name in selected.values()):
        raise RuntimeError("A selected full-restore image is absent")

    manifest = {
        "package": "y2-v89-usb-display-restore-innioasis-full",
        "firmware_build": "y2-v89-usb-display-restore",
        "base": {"file": BASE.name, "sha256": BASE_SHA256},
        "physical_evidence": {
            "v88_routes": "passed",
            "v88_playback_controls_sleep_theme_storage_power": "passed",
            "usb_storage_transfer": "passed",
            "usb_return_display": "failed",
            "observed_order": [
                "Rockbox framebuffer update",
                "Android surfaceChanged",
                "surface clear and bitmap replacement",
                "no later framebuffer update captured",
            ],
        },
        "repair": {
            "retain_last_native_frame_across_surface_recreation": True,
            "restore_cached_frame_after_surfaceChanged": True,
            "initial_surface_without_cache": "clear to black",
            "native_framebuffer": "480x360 RGB565",
            "destination": "full 480x360 Y2 surface",
        },
        "behavior": {
            "normal_boot_default": "rockbox",
            "normal_boot_choice": ["rockbox", "stock"],
            "volume_up": "opposite of normal boot choice",
            "volume_down": "settings",
            "both_volume_buttons": (
                "configured fixed fastboot route; physical chord remains "
                "a known V88-era limitation"
            ),
        },
        "mode_required_by_installed_updater": "format-download",
        "full_restore_selected_partitions": selected,
        "selected_partition_count": len(selected),
        "changed_from_v88": changed,
        "image_sha256": {
            name: sha256_bytes(data)
            for name, data in sorted(members.items())
            if name != "MT6582_Android_scatter.txt"
        },
        "physical_status": (
            "offline validation required; not release-approved until the "
            "USB display-return physical retest passes"
        ),
    }
    readme = (
        "Y2 V89 - USB DISPLAY RESTORE - FULL INNIOASIS PACKAGE\n\n"
        "V88 passed boot routing, playback, controls, sleep/wake, theme "
        "persistence, storage playback and power-off. USB storage transfer "
        "worked, but Rockbox returned with an incorrect display presentation. "
        "Diagnostics recorded a framebuffer update before Android recreated "
        "and cleared the SurfaceView, with no later update captured.\n\n"
        "V89 retains the last complete 480x360 RGB565 frame and redraws it "
        "after surfaceChanged instead of replacing it with an empty bitmap. "
        "The first surface still clears to black until Rockbox supplies its "
        "first real frame.\n\n"
        "This is a complete 12-partition package because InnioasisUpdater "
        "1.1.2 invokes SP Flash Tool in format-download mode. Back up both "
        "storage volumes before flashing.\n\n"
        "Physical status: not release-approved until USB enable, transfer, "
        "safe eject, disable, unplug and full-screen Rockbox return pass on "
        "the Y2.\n"
    ).encode("utf-8")
    members["V89-READ-ME-FIRST.txt"] = readme
    members["y2-v89-usb-display-restore-innioasis-full.json"] = (
        json.dumps(manifest, indent=2) + "\n"
    ).encode("utf-8")

    v88.deterministic_zip(OUT, members)
    OUT_SHA.write_text(
        f"{sha256(OUT)} *{OUT.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(OUT),
        "bytes": OUT.stat().st_size,
        "sha256": sha256(OUT),
        "selected_partitions": selected,
        "changed_from_v88": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
