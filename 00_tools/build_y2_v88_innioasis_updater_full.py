#!/usr/bin/env python3
"""Build V88 with vendor-shell-compatible boot-route readback."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE = WORK / "y2-v87-vendor-shell-save-innioasis-full.zip"
BASE_SHA256 = (
    "AE14E5091F0B39C9E10ACF5469D0B9F39C4A98E12E9E1C42ABF0AE463A06363C"
)
V88_SYSTEM = (
    WORK / "y2-rockbox-system-prototype-v88-route-readback-repair"
    / "system.img"
)
IMAGE_WORK = WORK / "y2-v88-route-readback-repair-images"
OUT = WORK / "y2-v88-route-readback-repair-innioasis-full.zip"
OUT_SHA = WORK / "y2-v88-route-readback-repair-innioasis-full.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 29, 10, 30, 0)
CPIO_MTIME = 1785357000


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v87 = load(
    "v87_full_builder",
    ROOT / "00_tools" / "build_y2_v87_innioasis_updater_full.py",
)
FIRMWARE_FILES = v87.FIRMWARE_FILES
EXPECTED_SELECTED = v87.EXPECTED_SELECTED
ROUTE_SCRIPT = v87.v86.v84.v81.ROUTE_SCRIPT
ROUTE_GUARD = v87.v86.v84.ROUTE_GUARD
USB_GUARD = v87.v86.v84.v81.USB_GUARD
SCRIPT_NAMES = (ROUTE_SCRIPT, ROUTE_GUARD, USB_GUARD)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def base_members() -> dict[str, bytes]:
    with zipfile.ZipFile(BASE) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V87 full base failed CRC")
        return {
            name: archive.read(name)
            for name in FIRMWARE_FILES
        }


def embedded_scripts(image: bytes) -> dict[str, bytes]:
    patcher = v87.v86.v84.v81.v80.v79.v78.v77.v76
    entries, *_ = patcher.ramdisk(image)
    entry_map = {entry["name"]: entry["data"] for entry in entries}
    return {name: entry_map[name] for name in SCRIPT_NAMES}


def repair_read_kv(
        data: bytes, old_build: str, new_build: str) -> bytes:
    text = data.decode("ascii")
    old_reader = """                printf '%s\\n' "${READ_KV_LINE#*=}"\n"""
    new_reader = """                echo "${READ_KV_LINE#*=}"\n"""
    if text.count(old_reader) != 1:
        raise RuntimeError(f"read_kv printf anchor drifted for {old_build}")
    if text.count(old_build) != 1:
        raise RuntimeError(f"build anchor drifted for {old_build}")
    text = text.replace(old_reader, new_reader, 1)
    text = text.replace(old_build, new_build, 1)
    if "printf" in text:
        raise RuntimeError(f"unsupported printf remains in {new_build}")
    return text.encode("ascii")


def v88_scripts(image: bytes) -> dict[str, bytes]:
    current = embedded_scripts(image)
    return {
        ROUTE_SCRIPT: repair_read_kv(
            current[ROUTE_SCRIPT],
            'BUILD="y2-v81-continuous-handoff"',
            'BUILD="y2-v88-route-readback-repair"',
        ),
        ROUTE_GUARD: repair_read_kv(
            current[ROUTE_GUARD],
            'BUILD="y2-v87-stable-broker-launcher-v3"',
            'BUILD="y2-v88-stable-broker-launcher-v4"',
        ),
        USB_GUARD: repair_read_kv(
            current[USB_GUARD],
            'BUILD="y2-v81-continuous-handoff"',
            'BUILD="y2-v88-usb-readback-repair"',
        ),
    }


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
        raise RuntimeError(f"Unsafe V88 image work path: {IMAGE_WORK}")
    if IMAGE_WORK.exists():
        shutil.rmtree(IMAGE_WORK)
    IMAGE_WORK.mkdir(parents=True)
    for name in ("boot.img", "recovery.img"):
        (IMAGE_WORK / name).write_bytes(members[name])

    patcher = v87.v86.v84.v81.v80.v79.v78.v77.v76
    patcher.OUT = IMAGE_WORK
    patcher.CPIO_MTIME = CPIO_MTIME
    payloads = v88_scripts(members["boot.img"])
    patches = {
        name: patcher.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }
    for name in patches:
        members[name] = (IMAGE_WORK / name).read_bytes()
    return patches


def main() -> None:
    if not BASE.is_file() or sha256(BASE) != BASE_SHA256:
        raise RuntimeError("Validated V87 full base is missing or drifted")
    if not V88_SYSTEM.is_file():
        raise RuntimeError(f"V88 system image is missing: {V88_SYSTEM}")

    members = base_members()
    base_hashes = {
        name: sha256_bytes(data)
        for name, data in members.items()
    }
    image_patches = patch_boot_images(members)
    members["system.img"] = V88_SYSTEM.read_bytes()
    changed = [
        name for name in FIRMWARE_FILES
        if sha256_bytes(members[name]) != base_hashes[name]
    ]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V88 partition delta: {changed}")

    selected = v87.v86.v85.parse_selected(
        members["MT6582_Android_scatter.txt"])
    if selected != EXPECTED_SELECTED:
        raise RuntimeError(f"Unexpected full-restore selection: {selected}")
    if any(name not in members for name in selected.values()):
        raise RuntimeError("A selected full-restore image is absent")

    manifest = {
        "package": "y2-v88-route-readback-repair-innioasis-full",
        "firmware_build": "y2-v88-route-readback-repair",
        "base": {"file": BASE.name, "sha256": BASE_SHA256},
        "physical_evidence": {
            "v87_save_service": "passed",
            "v87_requested_normal_boot": "stock",
            "v87_saved_map_verified": True,
            "v87_next_boot": "rockbox",
            "v87_next_boot_map_source": "built-in-defaults",
            "root_cause": (
                "early route, route-guard and USB read_kv retained the same "
                "vendor-shell-incompatible printf already proven by V86"
            ),
        },
        "repair": {
            "route_read_kv": "echo",
            "route_guard_read_kv": "echo",
            "usb_guard_read_kv": "echo",
            "unsupported_printf_in_patched_scripts": False,
            "physically_proven_v87_echo_save_broker_reused": True,
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
        "changed_from_v87": changed,
        "image_patches": image_patches,
        "image_sha256": {
            name: sha256_bytes(data)
            for name, data in sorted(members.items())
            if name != "MT6582_Android_scatter.txt"
        },
        "physical_status": (
            "offline validation required; not release-approved until the "
            "physical save, restart and cold-boot route matrix passes"
        ),
    }
    readme = (
        "Y2 V88 - ROUTE READBACK REPAIR - FULL INNIOASIS PACKAGE\n\n"
        "V87 physically proved that Boot Settings saved, verified and "
        "acknowledged Stock. Its next boot still selected Rockbox because the "
        "early route reader retained printf, a command this Y2 vendor shell "
        "does not provide. V88 replaces printf with echo in the route, route "
        "guard and USB readers and reuses V87's physically proven echo-only "
        "save broker.\n\n"
        "Normal boot defaults to Rockbox. Volume Up starts the other player, "
        "Volume Down opens Boot Settings, and both volume buttons retain "
        "fastboot.\n\n"
        "This is a complete 12-partition package because InnioasisUpdater "
        "1.1.2 invokes SP Flash Tool in format-download mode.\n\n"
        "Physical status: not release-approved until save/restart and the "
        "cold-boot route matrix pass on the Y2.\n"
    ).encode("utf-8")
    members["V88-READ-ME-FIRST.txt"] = readme
    members["y2-v88-route-readback-repair-innioasis-full.json"] = (
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
        "changed_from_v87": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
