#!/usr/bin/env python3
"""Compose V71 on E: from physically tested V70 plus the V71 system image."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
OUT = E_ROOT / "y2-v71-wake-owner"
ZIP = E_ROOT / "y2-v71-wake-owner.zip"
ZIP_SHA = E_ROOT / "y2-v71-wake-owner.zip.sha256.txt"
V70_ZIP = ROOT / "12_build_outputs" / "y2-v70-usb-return-guard.zip"
V70_SHA256 = "6F2DD09D6EF2AE516BF0EEF13B1ADECC77DCD5BE50FE4947FA4A2F9C84C38437"
V71_SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v71-wake-owner" / "system.img"
REPORT_JSON = "y2-v71-wake-owner.json"
REPORT_MD = "y2-v71-wake-owner.md"
ZIP_TIMESTAMP = (2026, 7, 21, 22, 30, 0)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v69 = load_module("v69_builder_base", ROOT / "00_tools" / "build_y2_v69_route_ownership.py")
FILES = v69.FILES


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_inputs() -> None:
    if not V70_ZIP.is_file() or sha256(V70_ZIP) != V70_SHA256:
        raise RuntimeError("Physically tested V70 base ZIP is missing or drifted")
    if not V71_SYSTEM.is_file():
        raise FileNotFoundError(V71_SYSTEM)
    with zipfile.ZipFile(V70_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V70 base ZIP failed CRC verification")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V70 base ZIP is incomplete: {missing}")


def compose() -> None:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v71-wake-owner":
        raise RuntimeError(f"Refusing unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(V70_ZIP) as archive:
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V71_SYSTEM, OUT / "system.img")


def write_reports() -> dict[str, object]:
    with zipfile.ZipFile(V70_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
    files = {}
    for name in FILES:
        output_hash = sha256(OUT / name)
        files[name] = {
            "size": (OUT / name).stat().st_size,
            "sha256": output_hash,
            "v70_sha256": base_hashes[name],
            "matches_v70": output_hash == base_hashes[name],
        }

    manifest: dict[str, object] = {
        "build": "y2-v71-wake-owner",
        "status": "targeted V70 physical-test correction; physical validation required",
        "created_local": "2026-07-21T22:30:00+10:00",
        "base": {
            "zip": str(V70_ZIP.relative_to(ROOT)),
            "sha256": V70_SHA256,
            "physical_result": (
                "Stock and Rockbox booted; Rockbox sleep/wake, three-second power, "
                "and theme persistence passed. Centre wake leaked a Select, and stock "
                "was later seen in front after Rockbox had slept. USB was not tested."
            ),
        },
        "evidence": {
            "preserved_at": r"E:\Y2-RockBox-evidence\v70-physical-centre-wake-late-stock-20260721",
            "finding": (
                "The Y2 WAKE_DROPPED mapping suppresses centre key-down while asleep "
                "but delivers key-up after wake. Stock remains the Android HOME task "
                "under Rockbox, so wake needs an explicit Rockbox route owner."
            ),
        },
        "behavior_delta": [
            "Consume a centre-key release unless Rockbox observed its matching key-down.",
            "On SCREEN_ON, only after sys.boot_completed=1 and only on the Rockbox firmware route, bring the existing singleTask Rockbox activity to the foreground.",
            "Retain V70's guarded USB return and bounded route shield unchanged.",
        ],
        "unchanged": [
            "LK, boot.img, recovery.img, userdata, stock APK and vendor services",
            "V70 root route scripts and exact stock receiver policy",
            "V70 USB storage-return behavior",
            "V65 native Rockbox playback libraries",
        ],
        "next_test": [
            "Cold boot stock with no key and confirm stock remains normal.",
            "Cold boot Rockbox with Volume Down; change theme and start playback.",
            "Sleep and wake with Centre at least five times: wake must not select the highlighted item.",
            "Leave Rockbox asleep for at least 30 minutes, then wake with Centre; Rockbox must be foreground.",
            "Confirm three-second power still works.",
            "Then test one real USB storage connect, safe eject/disable and unplug return cycle.",
        ],
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    (OUT / REPORT_JSON).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / REPORT_MD).write_text(
        "# Y2 V71 Wake Owner\n\n"
        "V71 fixes the two reproduced V70 failures: centre-wake Select-through and "
        "Rockbox losing the foreground after sleep. Only `system.img` differs from "
        "V70; all other packaged partitions are byte-identical.\n\n"
        "Physical validation is still required, including the USB test deferred on V70. "
        "Use the complete ZIP with Download Only. Never use Format All.\n",
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
    changed = [name for name, detail in manifest["files"].items() if not detail["matches_v70"]]
    if changed != ["system.img"]:
        raise RuntimeError(f"Unexpected V71 partition delta: {changed}")
    write_zip()
    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V71 output ZIP failed CRC verification")
    zip_hash = sha256(ZIP)
    ZIP_SHA.write_text(f"{zip_hash} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(ZIP), "size": ZIP.stat().st_size,
                      "sha256": zip_hash, "changed_from_v70": changed}, indent=2))


if __name__ == "__main__":
    main()
