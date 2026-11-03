#!/usr/bin/env python3
"""Build V86 with a repaired boot guard as a complete updater package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-intermediates"
BASE = WORK / "y2-v85-simple-boot-choice-innioasis-full.zip"
BASE_SHA256 = (
    "7BFF85B0085D270BF6A03E25E2756D50082FF2AFAA018FA5717E2D3572DF13E5"
)
V86_SYSTEM = (
    WORK / "y2-rockbox-system-prototype-v86-boot-save-repair"
    / "system.img"
)
IMAGE_WORK = WORK / "y2-v86-boot-save-repair-images"
OUT = WORK / "y2-v86-boot-save-repair-innioasis-full.zip"
OUT_SHA = WORK / "y2-v86-boot-save-repair-innioasis-full.zip.sha256.txt"
ZIP_TIMESTAMP = (2026, 7, 29, 5, 0, 0)
CPIO_MTIME = 1785337200

CANONICAL_BOOTCLASSPATH = (
    "/system/framework/core.jar:/system/framework/conscrypt.jar:"
    "/system/framework/okhttp.jar:/system/framework/core-junit.jar:"
    "/system/framework/bouncycastle.jar:/system/framework/ext.jar:"
    "/system/framework/framework.jar:/system/framework/framework2.jar:"
    "/system/framework/telephony-common.jar:/system/framework/voip-common.jar:"
    "/system/framework/mms-common.jar:/system/framework/android.policy.jar:"
    "/system/framework/services.jar:/system/framework/apache-xml.jar:"
    "/system/framework/webviewchromium.jar:"
    "/system/framework/mediatek-common.jar:"
    "/system/framework/mediatek-framework.jar:"
    "/system/framework/CustomProperties.jar:"
    "/system/framework/mediatek-telephony-common.jar:"
    "/system/framework/mediatek-tablet.jar"
)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v84 = load(
    "v84_guard_builder",
    ROOT / "00_tools" / "build_y2_v84_coherent_boot_settings.py",
)
v85 = load(
    "v85_full_builder",
    ROOT / "00_tools" / "build_y2_v85_innioasis_updater_full.py",
)
FIRMWARE_FILES = v85.FIRMWARE_FILES
EXPECTED_SELECTED = v85.EXPECTED_SELECTED


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def v86_route_guard() -> bytes:
    text = v84.v84_route_guard().decode("ascii")
    text = text.replace(
        'BUILD="y2-v84-stable-broker-launcher-v1"',
        'BUILD="y2-v86-stable-broker-launcher-v2"',
        1,
    )
    text = text.replace(
        'DATA_ROOT="/data/local/tmp/Y2_V84_DEBUG"',
        'DATA_ROOT="/data/local/tmp/Y2_V81_DEBUG"',
        1,
    )
    constants = 'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"\n'
    replacement = (
        constants
        + f'CANONICAL_BOOTCLASSPATH="{CANONICAL_BOOTCLASSPATH}"\n'
        + 'CANONICAL_BOOTCLASSPATH_EX="/system/framework/mediatek-op.jar"\n'
        + 'INHERITED_BOOTCLASSPATH="$BOOTCLASSPATH"\n'
        + 'INHERITED_BOOTCLASSPATH_EX="$BOOTCLASSPATH_EX"\n'
        + 'BOOTCLASSPATH="$CANONICAL_BOOTCLASSPATH"\n'
        + 'BOOTCLASSPATH_EX="$CANONICAL_BOOTCLASSPATH_EX"\n'
        + 'export BOOTCLASSPATH BOOTCLASSPATH_EX\n'
    )
    if text.count(constants) != 1:
        raise RuntimeError("V86 classpath constant anchor drifted")
    text = text.replace(constants, replacement, 1)

    mkdir_anchor = (
        'mkdir -p "$DATA_ROOT"\n'
        'chmod 0755 "$DATA_ROOT"\n'
    )
    classpath_check = mkdir_anchor + r'''BOOTCLASSPATH_MISSING=""
OLD_IFS="$IFS"
IFS=:
for BOOT_JAR in $BOOTCLASSPATH; do
    if [ ! -r "$BOOT_JAR" ]; then
        BOOTCLASSPATH_MISSING="$BOOTCLASSPATH_MISSING $BOOT_JAR"
    fi
done
IFS="$OLD_IFS"
if [ ! -r "$BOOTCLASSPATH_EX" ]; then
    BOOTCLASSPATH_MISSING="$BOOTCLASSPATH_MISSING $BOOTCLASSPATH_EX"
fi
'''
    if text.count(mkdir_anchor) != 1:
        raise RuntimeError("V86 classpath check anchor drifted")
    text = text.replace(mkdir_anchor, classpath_check, 1)

    start_log = (
        'log_event "guard=start '
        'policy=route-independent-session-long-settings-broker '
        'physical_route=$PHYSICAL_ROUTE"'
    )
    new_start_log = (
        'log_event "guard=start policy=settings-route-only-save-broker '
        'physical_route=$PHYSICAL_ROUTE '
        'inherited_BOOTCLASSPATH=$INHERITED_BOOTCLASSPATH '
        'inherited_BOOTCLASSPATH_EX=$INHERITED_BOOTCLASSPATH_EX '
        'effective_BOOTCLASSPATH=$BOOTCLASSPATH '
        'effective_BOOTCLASSPATH_EX=$BOOTCLASSPATH_EX '
        'missing_boot_jars=$BOOTCLASSPATH_MISSING"'
    )
    if text.count(start_log) != 1:
        raise RuntimeError("V86 start log anchor drifted")
    text = text.replace(start_log, new_start_log, 1)

    loop = '    resolve_route\n    run_settings_broker\n'
    route_scoped = (
        '    resolve_route\n'
        '    if [ "$ROUTE" = "settings" ]; then\n'
        '        run_settings_broker\n'
        '    fi\n'
    )
    if text.count(loop) != 1:
        raise RuntimeError("V86 broker loop anchor drifted")
    text = text.replace(loop, route_scoped, 1)
    return text.encode("ascii")


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
        raise RuntimeError(f"Unsafe V86 image work path: {IMAGE_WORK}")
    if IMAGE_WORK.exists():
        shutil.rmtree(IMAGE_WORK)
    IMAGE_WORK.mkdir(parents=True)
    for name in ("boot.img", "recovery.img"):
        (IMAGE_WORK / name).write_bytes(members[name])

    patcher = v84.v81.v80.v79.v78.v77.v76
    patcher.OUT = IMAGE_WORK
    patcher.CPIO_MTIME = CPIO_MTIME
    payloads = {v84.ROUTE_GUARD: v86_route_guard()}
    patches = {
        name: patcher.patch_image(name, payloads)
        for name in ("boot.img", "recovery.img")
    }
    for name in patches:
        members[name] = (IMAGE_WORK / name).read_bytes()
    return patches


def main() -> None:
    if not BASE.is_file() or sha256(BASE) != BASE_SHA256:
        raise RuntimeError("Validated V85 full base is missing or drifted")
    if not V86_SYSTEM.is_file():
        raise RuntimeError(f"V86 system image is missing: {V86_SYSTEM}")

    with zipfile.ZipFile(BASE) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V85 full base failed CRC")
        missing = [
            name for name in FIRMWARE_FILES
            if name not in archive.namelist()
        ]
        if missing:
            raise RuntimeError(f"V85 base incomplete: {missing}")
        members = {
            name: archive.read(name)
            for name in FIRMWARE_FILES
        }
    base_hashes = {
        name: sha256_bytes(data)
        for name, data in members.items()
    }

    image_patches = patch_boot_images(members)
    members["system.img"] = V86_SYSTEM.read_bytes()
    changed = [
        name for name in FIRMWARE_FILES
        if sha256_bytes(members[name]) != base_hashes[name]
    ]
    if changed != ["boot.img", "recovery.img", "system.img"]:
        raise RuntimeError(f"Unexpected V86 partition delta: {changed}")

    selected = v85.parse_selected(
        members["MT6582_Android_scatter.txt"])
    if selected != EXPECTED_SELECTED:
        raise RuntimeError(f"Unexpected full-restore selection: {selected}")
    if any(name not in members for name in selected.values()):
        raise RuntimeError("A selected full-restore image is absent")

    manifest = {
        "package": "y2-v86-boot-save-repair-innioasis-full",
        "firmware_build": "y2-v86-boot-save-repair",
        "base": {"file": BASE.name, "sha256": BASE_SHA256},
        "physical_evidence": {
            "v85_flash": "SP Flash Tool S_DONE with all 12 images",
            "save_requests": 2,
            "save_result": "both timed out without root acknowledgement",
            "java_vm_failures": 482,
            "failure": "must specify non-'.' bootclasspath",
        },
        "repair": {
            "canonical_bootclasspath_exported_by_guard": True,
            "all_boot_jars_checked_readable": True,
            "save_broker_scope": "settings route only",
            "ready_probe": "real ContentProvider query",
            "diagnostic_root": "/data/local/tmp/Y2_V81_DEBUG",
            "atomic_verified_route_map_write": True,
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
        "changed_from_v85": changed,
        "image_patches": image_patches,
        "image_sha256": {
            name: sha256_bytes(data)
            for name, data in sorted(members.items())
            if name != "MT6582_Android_scatter.txt"
        },
        "physical_status": (
            "offline validation required; not release-approved until the "
            "physical flash, both save directions and rollback pass"
        ),
    }
    readme = (
        "Y2 V86 - BOOT SAVE REPAIR - FULL INNIOASIS UPDATER PACKAGE\n\n"
        "Boot Settings contains one choice: what starts on a normal boot. "
        "The default is Rockbox. Volume Up starts the other player, Volume "
        "Down opens Boot Settings, and both volume buttons retain fastboot.\n\n"
        "V86 repairs the root guard's Android boot classpath before it invokes "
        "the save broker or activity manager. The broker now performs a real "
        "provider health query and runs only on the Boot Settings route.\n\n"
        "This is a complete 12-partition package because InnioasisUpdater "
        "1.1.2 invokes SP Flash Tool in format-download mode. Do not convert "
        "it to a selective partition archive.\n\n"
        "Physical status: not release-approved until the V86 flash and route/"
        "save test matrix pass on the Y2.\n"
    ).encode("utf-8")
    members["V86-READ-ME-FIRST.txt"] = readme
    members["y2-v86-boot-save-repair-innioasis-full.json"] = (
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
        "changed_from_v85": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
