#!/usr/bin/env python3
"""Build V77: V76 root behavior plus unambiguous, exportable diagnostics."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v76-root-route.zip"
BASE_SHA256 = "0709F663BB6911D88D894EEA9B432B393DEAB1791CE559EDE39B1C4222C08AD1"
V77_SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v77-release-day-gate" / "system.img"
OUT = E_ROOT / "y2-v77-release-day-gate"
ZIP = E_ROOT / "y2-v77-release-day-gate.zip"
ZIP_SHA = E_ROOT / "y2-v77-release-day-gate.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 24, 1, 0, 0)
CPIO_MTIME = 1784851200


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v76 = load("v76_builder_base", ROOT / "00_tools" / "build_y2_v76_root_route.py")
FILES = v76.FILES
ROUTE_SCRIPT = v76.ROUTE_SCRIPT
USB_GUARD = v76.USB_GUARD
ramdisk = v76.ramdisk
v75 = v76.v75


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


def rename_v77(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v76-root-route", "y2-v77-release-day-gate")
    text = text.replace("Y2_V76_DEBUG", "Y2_V77_DEBUG")
    text = text.replace("y2_v76_", "y2_v77_")
    text = text.replace("Y2 V76", "Y2 V77")
    return text.encode("ascii")


def v77_route_script(data: bytes) -> bytes:
    text = rename_v77(data).decode("ascii")
    anchor = '        "$DATA_ROOT"/early-latest.txt \\\n'
    replacement = (
        '        "$DATA_ROOT"/early-latest.txt \\\n'
        '        "$DATA_ROOT"/usb-root-broker-*.txt \\\n'
    )
    if text.count(anchor) != 1:
        raise RuntimeError("V77 route USB diagnostic-copy anchor drifted")
    text = text.replace(anchor, replacement)
    return text.encode("ascii")


def v77_early_diag(data: bytes) -> bytes:
    text = rename_v77(data).decode("ascii")
    anchor = (
        '    for SUPPORT in "$DATA_ROOT"/guard-*.txt '
        '"$DATA_ROOT"/route-dispatched-*.txt '
        '"$DATA_ROOT"/inline-takeover-*.txt '
        '"$DATA_ROOT"/boot-completion-bridge-*.txt; do'
    )
    replacement = (
        '    for SUPPORT in "$DATA_ROOT"/guard-*.txt '
        '"$DATA_ROOT"/route-dispatched-*.txt '
        '"$DATA_ROOT"/inline-takeover-*.txt '
        '"$DATA_ROOT"/boot-completion-bridge-*.txt '
        '"$DATA_ROOT"/usb-root-broker-*.txt; do'
    )
    if text.count(anchor) != 1:
        raise RuntimeError("V77 early USB diagnostic-copy anchor drifted")
    return text.replace(anchor, replacement).encode("ascii")


def scripts() -> dict[str, bytes]:
    entries, *_ = v76.ramdisk(base_image("recovery.img"))
    source = {entry["name"]: entry["data"] for entry in entries}
    result: dict[str, bytes] = {}
    for name in v76.v75.v74.SCRIPT_NAMES:
        if name == ROUTE_SCRIPT:
            result[name] = v77_route_script(source[name])
        elif name.endswith("y2v54earlydiag.sh"):
            result[name] = v77_early_diag(source[name])
        else:
            result[name] = rename_v77(source[name])
    result[USB_GUARD] = rename_v77(source[USB_GUARD])
    return result


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Validated V76 base is missing or drifted")
    if not V77_SYSTEM.is_file():
        raise FileNotFoundError(V77_SYSTEM)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V76 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V76 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v77-release-day-gate":
        raise RuntimeError(f"Unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V77_SYSTEM, OUT / "system.img")

    payloads = scripts()
    v76.OUT = OUT
    v76.CPIO_MTIME = CPIO_MTIME
    image_patches = {
        name: v76.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }
    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v76_sha256": base_hashes[name],
            "matches_v76": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    changed = [name for name in FILES if not files[name]["matches_v76"]]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V77 partition delta: {changed}")

    manifest = {
        "build": "y2-v77-release-day-gate",
        "status": "release-day physical gate; V76 root behavior untested on hardware",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "sd_evidence": {
            "capture": r"E:\Y2-RockBox-evidence\v75-late-partial-test-20260724",
            "finding": "No V76 files were present; the partial test was V75.",
        },
        "behavior_delta": [
            "Root-owned V76 boot and USB behavior is frozen unchanged.",
            "Build identity advances to V77 so the next test cannot be confused with V75.",
            "The route and early diagnostic collectors now copy the root USB broker log to SD.",
        ],
        "branding_unchanged": True,
        "haptic_unchanged": True,
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    report_json = "y2-v77-release-day-gate.json"
    report_md = "y2-v77-release-day-gate.md"
    test_txt = "V77-TEST.txt"
    (OUT / report_json).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / report_md).write_text(
        "# Y2 V77 Release-Day Gate\n\n"
        "V77 is the first physical test of the V76 root-owned boot and USB design. "
        "Its only V76 delta is unambiguous V77 identity and SD export of the root "
        "USB-broker log. Boot branding and haptics are unchanged.\n",
        encoding="utf-8")
    (OUT / test_txt).write_text(
        "Y2 V77 RELEASE-DAY TEST\n"
        "1. Flash the complete package using Download Only. NEVER Format All.\n"
        "2. No button: Rockbox must appear without a HOME chooser or visible Stock UI.\n"
        "3. Volume Up: Y2 Stock must open cleanly and remain foreground.\n"
        "4. Volume Down: Boot Settings must open cleanly and remain foreground.\n"
        "5. Confirm OneBitMono, five sleep/centre-wake cycles, no wake Select, and three-second power.\n"
        "6. Plug USB: the storage screen must open. Export, safely eject both Windows drives, then Turn off USB storage; expect one clean Rockbox return.\n"
        "7. Repeat USB export, safely eject both Windows drives, then unplug; expect one clean Rockbox return.\n"
        "8. Power off before returning the SD card for V77 diagnostics.\n",
        encoding="utf-8")

    if ZIP.exists():
        ZIP.unlink()
    members = (*FILES, report_json, report_md, test_txt)
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())
    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V77 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(f"{digest} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(ZIP),
        "size": ZIP.stat().st_size,
        "sha256": digest,
        "changed_from_v76": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
