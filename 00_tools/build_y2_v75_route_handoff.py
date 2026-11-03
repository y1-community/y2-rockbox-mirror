#!/usr/bin/env python3
"""Build V75: authenticated effective routes and deterministic USB handoff."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v74-release-candidate.zip"
BASE_SHA256 = "F6E6B35E1D85EDFE3205E361BEDDD012575E105AE9F46F621556EE428ED9D3E6"
V75_SYSTEM = E_ROOT / "y2-rockbox-system-prototype-v75-route-handoff" / "system.img"
OUT = E_ROOT / "y2-v75-route-handoff"
ZIP = E_ROOT / "y2-v75-route-handoff.zip"
ZIP_SHA = E_ROOT / "y2-v75-route-handoff.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 22, 1, 0, 0)
CPIO_MTIME = 1784653200
PARTITION_SIZE = 16 * 1024 * 1024


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v74 = load("v74_builder_base", ROOT / "00_tools" / "build_y2_v74_release_candidate.py")
boot_tools = v74.boot_tools
parser = v74.parser
FILES = v74.FILES
ROUTE_SCRIPT = v74.v69.ROUTE_SCRIPT
ROUTE_GUARD = v74.v69.ROUTE_GUARD


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


def ramdisk(image: bytes):
    parts = boot_tools.parse_boot_image(image)
    mtk_header, cpio, label = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = boot_tools.parse_cpio_newc(cpio)
    if boot_tools.build_cpio_newc(entries) != cpio:
        raise RuntimeError("Base CPIO does not round-trip exactly")
    return entries, parts, mtk_header, label


def v75_route_script(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v74-release-candidate", "y2-v75-route-handoff")
    text = text.replace("Y2_V74_DEBUG", "Y2_V75_DEBUG")
    text = text.replace("y2_v74_", "y2_v75_")
    text = text.replace("Y2 V74", "Y2 V75")
    immutable = 'setprop y2.firmware.route "$ROUTE"\n'
    if text.count(immutable) != 1:
        raise RuntimeError("V75 immutable-property anchor drifted")
    text = text.replace(
        immutable,
        'EFFECTIVE_ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"\n'
        '{\n'
        '    echo "physical_route=$PHYSICAL_ROUTE"\n'
        '    echo "route=$ROUTE"\n'
        '    echo "boot_id=$BOOT_ID"\n'
        '    echo "route_map_source=$ROUTE_MAP_SOURCE"\n'
        '} > "$EFFECTIVE_ROUTE_FILE"\n'
        'chmod 0644 "$EFFECTIVE_ROUTE_FILE"\n',
    )
    old = 'am broadcast -a "$ACTION" --es route "$ROUTE"'
    new = ('am broadcast -a "$ACTION" --es physical_route "$PHYSICAL_ROUTE" '
           '--es route "$ROUTE"')
    if text.count(old) != 2:
        raise RuntimeError("V75 broadcast anchors drifted")
    text = text.replace(old, new)
    text = text.replace(
        'echo "command=am broadcast -a $ACTION --es route $ROUTE"',
        'echo "command=am broadcast -a $ACTION --es physical_route '
        '$PHYSICAL_ROUTE --es route $ROUTE"',
    )
    text = text.replace(
        'echo "selection_owner=LK keypad matrix plus selected recovery ramdisk"',
        'echo "selection_owner=immutable physical route plus saved effective mapping"\n'
        '    echo "physical_route_property_immutable=yes"',
    )
    return text.encode("ascii")


def v75_guard_script(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v74-release-candidate", "y2-v75-route-handoff")
    text = text.replace("Y2_V74_DEBUG", "Y2_V75_DEBUG")
    old = '''ROUTE=$(getprop "$ROUTE_PROPERTY")
LOG="$DATA_ROOT/guard-$BOOT_ID-$ROUTE.txt"
SIGNAL="$DATA_ROOT/route-dispatched-$BOOT_ID-$ROUTE.txt"
'''
    new = '''PHYSICAL_ROUTE=$(getprop "$ROUTE_PROPERTY")
ROUTE_FILE="$DATA_ROOT/effective-route-$BOOT_ID.txt"
ROUTE_WAIT=0
while [ "$ROUTE_WAIT" -lt 90 ] && [ ! -f "$ROUTE_FILE" ]; do
    ROUTE_WAIT=$((ROUTE_WAIT + 1))
    sleep 1
done
ROUTE=$(grep '^route=' "$ROUTE_FILE" 2>/dev/null | head -n 1 | cut -d= -f2)
LOG="$DATA_ROOT/guard-$BOOT_ID-$ROUTE.txt"
SIGNAL="$DATA_ROOT/route-dispatched-$BOOT_ID-$ROUTE.txt"
'''
    if text.count(old) != 1:
        raise RuntimeError("V75 guard route anchor drifted")
    text = text.replace(old, new)
    text = text.replace(
        'while [ "$(getprop "$ROUTE_PROPERTY")" = "$ROUTE" ]; do',
        'while [ "$(getprop "$ROUTE_PROPERTY")" = "$PHYSICAL_ROUTE" ]; do',
    )
    text = text.replace(
        'echo "route=$(getprop "$ROUTE_PROPERTY") boot_completed=$(getprop sys.boot_completed)"',
        'echo "physical_route=$(getprop "$ROUTE_PROPERTY") route=$ROUTE boot_completed=$(getprop sys.boot_completed)"',
    )
    return text.encode("ascii")


def v75_other_script(data: bytes) -> bytes:
    text = data.decode("ascii")
    text = text.replace("y2-v74-release-candidate", "y2-v75-route-handoff")
    text = text.replace("Y2_V74_DEBUG", "Y2_V75_DEBUG")
    text = text.replace("y2_v74_", "y2_v75_")
    text = text.replace("Y2 V74", "Y2 V75")
    return text.encode("ascii")


def scripts() -> dict[str, bytes]:
    entries, *_ = ramdisk(base_image("recovery.img"))
    source = {e["name"]: e["data"] for e in entries}
    result = {}
    for name in v74.SCRIPT_NAMES:
        data = source[name]
        if name == ROUTE_SCRIPT:
            result[name] = v75_route_script(data)
        elif name == ROUTE_GUARD:
            result[name] = v75_guard_script(data)
        else:
            result[name] = v75_other_script(data)
    return result


def patch_image(name: str, payloads: dict[str, bytes]) -> dict[str, object]:
    path = OUT / name
    before = path.read_bytes()
    entries, parts, mtk_header, label = ramdisk(before)
    entry_map = {e["name"]: e for e in entries}
    installed = {n: d for n, d in payloads.items() if n in entry_map}
    for script_name, data in installed.items():
        entry_map[script_name]["data"] = data
        entry_map[script_name]["mode"] = 0o100750
        entry_map[script_name]["mtime"] = CPIO_MTIME
    if name == "boot.img":
        init = entry_map["init.rc"]["data"].decode("ascii")
        old = 'on property:sys.boot_completed=1\n    start y2v36stockroute'
        new = '# V75 authenticates and dispatches the no-button route before Stock HOME.\n' \
              'on post-fs-data\n    start y2v36stockroute'
        if init.count(old) != 1:
            raise RuntimeError("V75 boot route trigger anchor drifted")
        entry_map["init.rc"]["data"] = init.replace(old, new).encode("ascii")
        entry_map["init.rc"]["mtime"] = CPIO_MTIME
    built_cpio = boot_tools.build_cpio_newc(entries)
    built_ramdisk = boot_tools.build_mtk_ramdisk(mtk_header, built_cpio)
    after = boot_tools.build_boot_image(parts, built_ramdisk)
    if len(after) > PARTITION_SIZE:
        raise RuntimeError(f"{name} exceeds its partition")
    path.write_bytes(after)
    final_entries, final_parts, _, final_label = ramdisk(after)
    final = {e["name"]: e["data"] for e in final_entries}
    for script_name, data in installed.items():
        if final[script_name] != data:
            raise RuntimeError(f"{name} embedded script mismatch: {script_name}")
    if final_parts["kernel"] != parts["kernel"] or final_label != label:
        raise RuntimeError(f"{name} changed kernel or MediaTek label")
    return {"before": sha256_bytes(before), "after": sha256_bytes(after),
            "kernel_unchanged": True, "scripts": sorted(installed)}


def verify_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Physically tested V74 base is missing or drifted")
    if not V75_SYSTEM.is_file():
        raise FileNotFoundError(V75_SYSTEM)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V74 base ZIP failed CRC")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V74 base ZIP incomplete: {missing}")


def main() -> None:
    verify_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v75-route-handoff":
        raise RuntimeError(f"Unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(BASE_ZIP) as archive:
        base_hashes = {n: sha256_bytes(archive.read(n)) for n in FILES}
        for name in FILES:
            (OUT / name).write_bytes(archive.read(name))
    shutil.copy2(V75_SYSTEM, OUT / "system.img")
    payloads = scripts()
    image_patches = {name: patch_image(name, payloads)
                     for name in ("boot.img", "recovery.img")}
    files = {name: {"size": (OUT / name).stat().st_size,
                    "sha256": sha256(OUT / name),
                    "v74_sha256": base_hashes[name],
                    "matches_v74": sha256(OUT / name) == base_hashes[name]}
             for name in FILES}
    changed = [n for n in FILES if not files[n]["matches_v74"]]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V75 partition delta: {changed}")
    manifest = {
        "build": "y2-v75-route-handoff",
        "status": "focused USB/route stability candidate; physical validation required",
        "base": {"zip": str(BASE_ZIP), "sha256": BASE_SHA256},
        "v74_findings": [
            "USB-off legitimately restarted native Rockbox after storage remounted.",
            "Cable unplug triggered four legacy Rockbox launches and stale cross-process USB-return state, producing flashes and a 10-12 second shield timeout.",
            "The immutable physical boot route was overwritten with the mapped route, causing Volume Down Boot Settings authentication to fail and delaying no-button Rockbox until Stock HOME appeared.",
        ],
        "behavior_delta": [
            "The physical route property remains immutable; the script broadcasts authenticated physical and selected effective routes separately.",
            "No-button dispatch begins at post-fs-data rather than waiting for sys.boot_completed.",
            "Android 4.4 route state reloads across the main and :route processes; either process can close a completed USB return.",
            "The four-shot unplug relaunch is suppressed during route-owned USB handoff and reduced to one bounded non-USB fallback.",
            "A branded Rockbox restoring screen replaces an unexplained black overlay while native storage is remounted.",
            "Boot Settings uses the same authenticated shield/readiness ownership as Rockbox.",
        ],
        "branding_unchanged": True,
        "haptic_unchanged": True,
        "image_patches": image_patches,
        "files": files,
        "flash_safety": "Complete ZIP, Download Only; never Format All.",
    }
    report_json = "y2-v75-route-handoff.json"
    report_md = "y2-v75-route-handoff.md"
    test_txt = "V75-TEST.txt"
    (OUT / report_json).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / report_md).write_text(
        "# Y2 V75 Route Handoff\n\nV75 is V74 plus focused fixes for effective-route authentication, early no-button ownership, and deterministic USB return. Boot branding and haptic behavior are unchanged.\n",
        encoding="utf-8")
    (OUT / test_txt).write_text(
        "Y2 V75 TEST\n"
        "1. Flash the complete package using Download Only. NEVER Format All.\n"
        "2. Cold boot: no button=Rockbox, Volume Up=Y2 Stock, Volume Down=Boot Settings.\n"
        "3. Confirm no HOME chooser and no Stock UI appears on Rockbox or Boot Settings routes.\n"
        "4. In Rockbox test sleep/centre wake five times and three-second power.\n"
        "5. Plug USB, enable storage, safely eject both Windows drives, then Turn off USB storage. Rockbox may show the branded Restoring storage handoff but must not show Stock or a blank black screen.\n"
        "6. Repeat USB storage, safely eject, then unplug the cable. Confirm one clean return with no repeated flashes or 10-second black timeout.\n",
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
            raise RuntimeError("V75 ZIP failed CRC")
    digest = sha256(ZIP)
    ZIP_SHA.write_text(f"{digest} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(ZIP), "size": ZIP.stat().st_size,
                      "sha256": digest, "changed_from_v74": changed}, indent=2))


if __name__ == "__main__":
    main()
