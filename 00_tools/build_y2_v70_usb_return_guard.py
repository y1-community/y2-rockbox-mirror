#!/usr/bin/env python3
"""Build V70 from V69 with only the guarded Rockbox system image changed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v69 = load_module(
    "v69_builder_base",
    ROOT / "00_tools" / "build_y2_v69_route_ownership.py",
)

FILES = v69.FILES
OFFICIAL = v69.OFFICIAL
V69_ZIP = ROOT / "12_build_outputs" / "y2-v69-route-ownership.zip"
V69_ZIP_SHA256 = "2A74CE99B413270BEAA033C3F043A6E1361A24731E831FC156EAB15078574134"
V70_SYSTEM = (
    Path(r"E:\Y2-RockBox-build-intermediates")
    / "y2-rockbox-system-prototype-v70-usb-return-guard"
    / "system.img"
)

OUT = ROOT / "12_build_outputs" / "y2-v70-usb-return-guard"
ZIP = ROOT / "12_build_outputs" / "y2-v70-usb-return-guard.zip"
ZIP_SHA = ROOT / "12_build_outputs" / "y2-v70-usb-return-guard.zip.sha256.txt"
REPORT_JSON = "y2-v70-usb-return-guard.json"
REPORT_MD = "y2-v70-usb-return-guard.md"
BUILD_TIMESTAMP_UTC = "2026-07-21T02:00:00+00:00"
ZIP_TIMESTAMP = (2026, 7, 21, 12, 0, 0)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_inputs() -> None:
    if not V69_ZIP.is_file() or sha256(V69_ZIP) != V69_ZIP_SHA256:
        raise RuntimeError("V69 base ZIP missing or drifted")
    if not V70_SYSTEM.is_file():
        raise FileNotFoundError(V70_SYSTEM)
    with zipfile.ZipFile(V69_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V69 base ZIP failed CRC verification")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V69 base ZIP is incomplete: {missing}")


def compose() -> None:
    verify_inputs()
    expected_parent = (ROOT / "12_build_outputs").resolve()
    resolved_out = OUT.resolve()
    if resolved_out.parent != expected_parent or resolved_out.name != OUT.name:
        raise RuntimeError(f"Refusing unsafe output path: {resolved_out}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(V69_ZIP) as archive:
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V70_SYSTEM, OUT / "system.img")


def write_reports() -> dict[str, object]:
    with zipfile.ZipFile(V69_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
    files = {}
    for name in FILES:
        output_hash = sha256(OUT / name)
        files[name] = {
            "size": (OUT / name).stat().st_size,
            "sha256": output_hash,
            "v69_sha256": base_hashes[name],
            "matches_v69": output_hash == base_hashes[name],
        }

    manifest: dict[str, object] = {
        "build": "y2-v70-usb-return-guard",
        "status": "targeted V69 physical-failure correction; physical validation required",
        "created_utc": BUILD_TIMESTAMP_UTC,
        "base": {
            "zip": str(V69_ZIP.relative_to(ROOT)),
            "sha256": V69_ZIP_SHA256,
            "physical_result": (
                "Two cold Rockbox boots displayed cleanly, then ordinary "
                "UMS_DISCONNECTED broadcasts were mistaken for armed USB returns. "
                "The opaque route shield covered the sleeping Rockbox surface while "
                "the long-power GlobalActions window remained available."
            ),
        },
        "root_cause": (
            "Y2StorageReceiver started ACTION_USB_RETURN_BEGIN without requiring the "
            "USB-return latch set by MEDIA_UNMOUNTED/EJECT/SHARED. The coordinator "
            "also retried indefinitely, and a recreated framebuffer could acknowledge "
            "the shield only once per Java object lifetime."
        ),
        "behavior_delta": [
            "Ignore PRE_MOUNT_SDCARD and UMS_DISCONNECTED unless a real Rockbox USB export armed the persisted return latch.",
            "Recheck the latch inside the route service before showing or retaining its system overlay.",
            "Permit each recreated Rockbox surface to acknowledge a newly owned return frame.",
            "Allow one frame-timeout retry, then remove the shield fail-open instead of covering the UI indefinitely.",
        ],
        "unchanged": [
            "LK, boot.img, recovery.img, userdata, stock APK and vendor services",
            "V69 center-wake keylayouts",
            "V65 native Rockbox playback libraries",
            "themes, settings, databases and storage content",
        ],
        "next_test": [
            "Cold Volume Down Rockbox boot and wait beyond the screen timeout; ordinary disconnect broadcasts must not raise the route shield.",
            "Wake and exercise Rockbox controls, playback, volume, sleep/wake and the three-second power menu.",
            "Run one real USB export, safe eject, disable and unplug cycle; Rockbox must return once with no stock window or persistent shield.",
            "Boot stock with no key and confirm normal stock behavior.",
        ],
        "firmware_delta": (
            "Only system.img differs from V69. All other packaged partitions are "
            "byte-identical to the V69 candidate."
        ),
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    (OUT / REPORT_JSON).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / REPORT_MD).write_text(
        "# Y2 V70 Armed USB Return Guard\n\n"
        "V70 keeps V69's clean route-ownership architecture and fixes the reproduced "
        "false-disconnect shield lockout. Only `system.img` differs from V69.\n\n"
        "This is a physical-test candidate. Use the complete ZIP with Download Only. "
        "Never use Format All.\n",
        encoding="utf-8",
    )
    return manifest


def write_zip() -> None:
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted((*FILES, REPORT_JSON, REPORT_MD)):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())


def main() -> None:
    compose()
    manifest = write_reports()
    write_zip()
    zip_hash = sha256(ZIP)
    ZIP_SHA.write_text(f"{zip_hash} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(ZIP.relative_to(ROOT)),
        "size": ZIP.stat().st_size,
        "sha256": zip_hash,
        "changed_from_v69": [
            name for name, detail in manifest["files"].items()
            if not detail["matches_v69"]
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
