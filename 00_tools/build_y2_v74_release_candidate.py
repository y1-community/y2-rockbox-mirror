#!/usr/bin/env python3
"""Build V74: configurable early boot routes, USB exit recovery and OneBitMono."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v73-home-resolver-recovery.zip"
BASE_SHA256 = "034C69C9BE414BECF2B15EE543F9320426C41AC5851D4837ADCDE059E6A7F1D9"
V74_SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v74-release-candidate" / "system.img"
OUT = E_ROOT / "y2-v74-release-candidate"
ZIP = E_ROOT / "y2-v74-release-candidate.zip"
ZIP_SHA = E_ROOT / "y2-v74-release-candidate.zip.sha256.txt"
REPORT_JSON = "y2-v74-release-candidate.json"
REPORT_MD = "y2-v74-release-candidate.md"
TEST_TXT = "V74-TEST.txt"
ZIP_TIMESTAMP = (2026, 7, 22, 0, 30, 0)
CPIO_MTIME = 1784651400
PARTITION_SIZE = 16 * 1024 * 1024


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v69 = load_module("v69_builder_base", ROOT / "00_tools" / "build_y2_v69_route_ownership.py")
boot_tools = v69.boot_tools
parser = v69.v68.v67.recovery_parser()
FILES = v69.FILES
SCRIPT_NAMES = (v69.ROUTE_SCRIPT, v69.ROUTE_GUARD, v69.EARLY_DIAG, v69.USB_GUARD)


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


def ramdisk_entries(image: bytes) -> tuple[dict[str, bytes], dict[str, object], bytes, str]:
    parts = boot_tools.parse_boot_image(image)
    mtk_header, cpio, label = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = boot_tools.parse_cpio_newc(cpio)
    if boot_tools.build_cpio_newc(entries) != cpio:
        raise RuntimeError("Base CPIO does not round-trip exactly")
    return ({entry["name"]: entry["data"] for entry in entries}, parts, mtk_header, label)


def canonical_scripts() -> dict[str, bytes]:
    entries, _, _, _ = ramdisk_entries(base_image("recovery.img"))
    return {name: entries[name] for name in SCRIPT_NAMES}


ROUTE_MAP_BLOCK = r'''PHYSICAL_ROUTE="$ROUTE"
ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"
ROUTE_MAP_SOURCE="built-in-defaults"
case "$PHYSICAL_ROUTE" in
    stock)
        ROUTE_MAP_KEY="no_button"
        MAPPED_ROUTE="rockbox"
        ;;
    settings)
        ROUTE_MAP_KEY="volume_up"
        MAPPED_ROUTE="stock"
        ;;
    rockbox)
        ROUTE_MAP_KEY="volume_down"
        MAPPED_ROUTE="settings"
        ;;
    *)
        ROUTE_MAP_KEY="unsupported"
        MAPPED_ROUTE="stock"
        ;;
esac
if [ -r "$ROUTE_MAP_FILE" ] &&
   grep -F "version=1" "$ROUTE_MAP_FILE" >/dev/null 2>&1; then
    CANDIDATE=$(grep "^$ROUTE_MAP_KEY=" "$ROUTE_MAP_FILE" 2>/dev/null |
        head -n 1 | cut -d= -f2)
    case "$CANDIDATE" in
        rockbox|stock|settings)
            MAPPED_ROUTE="$CANDIDATE"
            ROUTE_MAP_SOURCE="saved-settings"
            ;;
    esac
fi
ROUTE="$MAPPED_ROUTE"

STOCK_PACKAGE="com.innioasis.y2"
'''


def v74_script(name: str, data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v69-route-ownership", "y2-v74-release-candidate")
    text = text.replace("Y2_V69_DEBUG", "Y2_V74_DEBUG")
    text = text.replace("y2_v69_", "y2_v74_")
    text = text.replace("Y2 V69", "Y2 V74")
    if name == v69.ROUTE_SCRIPT:
        anchor = 'STOCK_PACKAGE="com.innioasis.y2"\n'
        if text.count(anchor) != 1:
            raise RuntimeError("V74 route-map anchor drifted")
        text = text.replace(anchor, ROUTE_MAP_BLOCK, 1)
        text = text.replace(
            '    echo "route=$ROUTE"\n    echo "session=$SESSION"',
            '    echo "physical_route=$PHYSICAL_ROUTE"\n'
            '    echo "route=$ROUTE"\n'
            '    echo "route_map_key=$ROUTE_MAP_KEY"\n'
            '    echo "route_map_source=$ROUTE_MAP_SOURCE"\n'
            '    echo "route_map_file=$ROUTE_MAP_FILE"\n'
            '    echo "session=$SESSION"',
            1,
        )
    encoded = text.encode("ascii")
    return encoded if encoded.endswith(b"\n") else encoded + b"\n"


def patch_image(name: str, scripts: dict[str, bytes]) -> dict[str, object]:
    path = OUT / name
    before = path.read_bytes()
    parts = boot_tools.parse_boot_image(before)
    mtk_header, cpio, label = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = boot_tools.parse_cpio_newc(cpio)
    if boot_tools.build_cpio_newc(entries) != cpio:
        raise RuntimeError(f"{name} CPIO does not round-trip exactly")
    entry_map = {entry["name"]: entry for entry in entries}
    required_scripts = (v69.ROUTE_SCRIPT, v69.ROUTE_GUARD, v69.EARLY_DIAG)
    missing = [script for script in required_scripts if script not in entry_map]
    if missing:
        raise RuntimeError(f"{name} lacks route scripts: {missing}")
    installed_scripts = {
        script: payload for script, payload in scripts.items() if script in entry_map
    }
    for script, payload in installed_scripts.items():
        entry_map[script]["data"] = payload
        entry_map[script]["mode"] = 0o100750
        entry_map[script]["mtime"] = CPIO_MTIME
    patched_cpio = boot_tools.build_cpio_newc(entries)
    patched_ramdisk = boot_tools.build_mtk_ramdisk(mtk_header, patched_cpio)
    after = boot_tools.build_boot_image(parts, patched_ramdisk)
    if len(after) > PARTITION_SIZE:
        raise RuntimeError(f"{name} exceeds its 16 MiB partition")
    path.write_bytes(after)
    final_entries, final_parts, _, final_label = ramdisk_entries(after)
    for script, payload in installed_scripts.items():
        if final_entries[script] != payload:
            raise RuntimeError(f"{name} failed embedded verification: {script}")
    if final_parts["kernel"] != parts["kernel"] or final_label != label:
        raise RuntimeError(f"{name} kernel or MediaTek label changed")
    return {
        "before_sha256": sha256_bytes(before),
        "after_sha256": sha256_bytes(after),
        "size": len(after),
        "kernel_unchanged": True,
        "scripts": list(installed_scripts),
    }


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V73 base ZIP is missing or drifted")
    if not V74_SYSTEM.is_file():
        raise FileNotFoundError(V74_SYSTEM)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V73 base ZIP failed CRC verification")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V73 base ZIP is incomplete: {missing}")


def compose() -> dict[str, object]:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v74-release-candidate":
        raise RuntimeError(f"Refusing unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V74_SYSTEM, OUT / "system.img")
    scripts = {name: v74_script(name, data) for name, data in canonical_scripts().items()}
    return {
        "boot.img": patch_image("boot.img", scripts),
        "recovery.img": patch_image("recovery.img", scripts),
    }


def write_reports(image_patches: dict[str, object]) -> dict[str, object]:
    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {name: sha256_bytes(archive.read(name)) for name in FILES}
    files = {
        name: {
            "size": (OUT / name).stat().st_size,
            "sha256": sha256(OUT / name),
            "v73_sha256": base_hashes[name],
            "matches_v73": sha256(OUT / name) == base_hashes[name],
        }
        for name in FILES
    }
    manifest = {
        "build": "y2-v74-release-candidate",
        "status": "focused release candidate; physical validation required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v73_physical_result": {
            "passed": ["clean Rockbox boot", "no HOME chooser", "theme changes", "centre wake without Select", "three-second power"],
            "failed": "Disabling USB storage caused native Rockbox main to return normally; Stock became foreground after the Rockbox activity finished.",
        },
        "behavior_delta": [
            "The independent route process takes a black shield before Rockbox's native-exit activity finish, waits for both storage volumes to be writable, then performs one owned relaunch.",
            "Native-exit recovery is bounded to three attempts per minute to prevent a boot loop.",
            "Boot Settings now contains only No button, Volume Up and Volume Down mappings, each offering Rockbox, Y2 Stock or Boot Settings, plus Save & Exit.",
            "Saved mappings are written atomically to /data/system/y2_boot_routes.conf and resolved by the early boot route script.",
            "Built-in defaults are No button=Rockbox, Volume Up=Y2 Stock, Volume Down=Boot Settings.",
            "The OneBitMono 480x360 theme and its assets are bundled in the Rockbox resource archive.",
        ],
        "onebitmono": {
            "conversion": "OneBit_Mono_360p / OneBitMono for a 480x360 Rockbox screen",
            "theme_credit": "chronicallyoffline / Cicumpunct; credits also name Chuck Lardo and D0-0K",
            "license": "CC-BY-SA as declared in OneBitMono.cfg",
            "source_post": "https://www.reddit.com/r/innioasis/comments/1naevbo/testing_360p_theme_conversion_python_script/",
            "source_archive": "https://drive.google.com/file/d/1QlVo1r4m_Y5nueDG78HYMd9Hb2E6T9Q4/view",
            "source_archive_sha256": "C1CE64161AA5A36D829CD964E64CED876DBFBA65EDFF7FCE3AE9732D540F8A7E",
        },
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    (OUT / REPORT_JSON).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / REPORT_MD).write_text(
        "# Y2 V74 Release Candidate\n\n"
        "V74 closes the reproduced USB native-exit ownership gap, makes the three boot "
        "routes genuinely configurable before Android dispatch, and bundles OneBitMono.\n\n"
        "Flash the complete ZIP with **Download Only**. Never use Format All.\n",
        encoding="utf-8",
    )
    (OUT / TEST_TXT).write_text(
        "Y2 V74 TEST\n"
        "1. Flash the complete package using Download Only. NEVER Format All.\n"
        "2. No button must open Rockbox; Volume Up must open Y2 Stock; Volume Down must open Boot Settings.\n"
        "3. In Boot Settings confirm exactly three rows and Save & Exit; change a mapping, save, and verify the next cold boot.\n"
        "4. In Rockbox select OneBitMono and confirm it renders.\n"
        "5. Test sleep/centre wake five times and three-second power.\n"
        "6. Enable USB storage, safely eject, disable USB storage, unplug, and confirm Rockbox returns with no Stock window.\n",
        encoding="utf-8",
    )
    return manifest


def write_zip() -> None:
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted((*FILES, REPORT_JSON, REPORT_MD, TEST_TXT)):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())


def main() -> None:
    patches = compose()
    manifest = write_reports(patches)
    changed = [name for name, detail in manifest["files"].items() if not detail["matches_v73"]]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V74 partition delta: {changed}")
    write_zip()
    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V74 output ZIP failed CRC verification")
    zip_hash = sha256(ZIP)
    ZIP_SHA.write_text(f"{zip_hash} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(ZIP), "size": ZIP.stat().st_size,
                      "sha256": zip_hash, "changed_from_v73": changed}, indent=2))


if __name__ == "__main__":
    main()
