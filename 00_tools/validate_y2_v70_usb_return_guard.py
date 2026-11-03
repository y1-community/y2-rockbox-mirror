#!/usr/bin/env python3
"""Offline structural and packaging validation for Y2 V70."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v70-offline-validation"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_module(
    "v70_builder",
    ROOT / "00_tools" / "build_y2_v70_usb_return_guard.py",
)
generic = load_module(
    "generic_validator",
    ROOT / "00_tools" / "y2_firmware_validator.py",
)
v47 = load_module(
    "v47_validator",
    ROOT / "00_tools" / "validate_y2_v47_full_stock_v42_system_isolation.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict] = {}

    def check(name: str, passed: bool, detail) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    expected_members = set(builder.FILES) | {
        builder.REPORT_JSON,
        builder.REPORT_MD,
    }
    with zipfile.ZipFile(builder.ZIP) as archive:
        names = archive.namelist()
        bad_member = archive.testzip()
        packaged = {name: archive.read(name) for name in builder.FILES}
        manifest = json.loads(archive.read(builder.REPORT_JSON).decode("utf-8"))
    check("zip_crc_clean", bad_member is None, bad_member)
    check(
        "zip_members_unique_and_exact",
        len(names) == len(set(names)) and set(names) == expected_members,
        {"entries": len(names), "expected": len(expected_members)},
    )
    sidecar_hash = builder.ZIP_SHA.read_text(encoding="ascii").split()[0].upper()
    check(
        "published_zip_hash_exact",
        sha256(builder.ZIP) == sidecar_hash,
        {"actual": sha256(builder.ZIP), "sidecar": sidecar_hash},
    )
    check(
        "v69_base_zip_exact",
        sha256(builder.V69_ZIP) == builder.V69_ZIP_SHA256,
        sha256(builder.V69_ZIP),
    )

    with zipfile.ZipFile(builder.V69_ZIP) as archive:
        base = {name: archive.read(name) for name in builder.FILES}
    changed = [
        name for name in builder.FILES
        if sha256_bytes(packaged[name]) != sha256_bytes(base[name])
    ]
    check("firmware_delta_system_only", changed == ["system.img"], changed)
    check(
        "system_image_exact_staged_v70",
        packaged["system.img"] == builder.V70_SYSTEM.read_bytes(),
        sha256_bytes(packaged["system.img"]),
    )

    apk = (
        ROOT / "12_build_outputs" / "rockbox-android-y2-v70"
        / "rockbox-y2-v70-usb-return-guard.apk"
    )
    stable_apk = (
        ROOT / "12_build_outputs" / "rockbox-android-y2-v65"
        / "rockbox-y2-v65-android-unplug-reassert.apk"
    )
    with zipfile.ZipFile(apk) as archive:
        dex = archive.read("classes.dex")
        apk_bad = archive.testzip()
        native = {
            name: sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.startswith("lib/armeabi/") and name.endswith(".so")
        }
    with zipfile.ZipFile(stable_apk) as archive:
        stable_native = {
            name: sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.startswith("lib/armeabi/") and name.endswith(".so")
        }
    dex_tokens = (
        b"Y2StorageReceiver:ignore unarmed USB return action=",
        b"Y2RouteShieldService:ignore unarmed USB return begin",
        b"Y2RouteShieldService:ignore storage change without USB return",
        b"Y2RouteShieldService:frame retry exhausted, fail-open hide",
        b"RockboxFramebuffer:first frame signalled to route shield",
    )
    check(
        "guarded_apk_crc_tokens_and_native_boundary",
        apk_bad is None
        and all(token in dex for token in dex_tokens)
        and native == stable_native,
        {
            "apk_sha256": sha256(apk),
            "native_count": len(native),
            "tokens": {token.decode("ascii"): dex.count(token) for token in dex_tokens},
        },
    )

    receiver_source = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android" / "src"
        / "org" / "rockbox" / "Y2StorageReceiver.java"
    ).read_text(encoding="utf-8")
    service_source = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android" / "src"
        / "org" / "rockbox" / "Y2RouteShieldService.java"
    ).read_text(encoding="utf-8")
    framebuffer_source = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android" / "src"
        / "org" / "rockbox" / "RockboxFramebuffer.java"
    ).read_text(encoding="utf-8")
    disconnect_block = receiver_source[
        receiver_source.index('if ("com.innioasis.y1.PRE_MOUNT_SDCARD"'):
        receiver_source.index("if (Intent.ACTION_MEDIA_MOUNTED")
    ]
    check(
        "unarmed_disconnect_rejected_before_service_start",
        disconnect_block.index("!Y2BootState.isUsbReturnPending(context)")
        < disconnect_block.index("context.startService(coordinator)"),
        disconnect_block,
    )
    check(
        "service_rechecks_latch_and_fails_open",
        service_source.count("!Y2BootState.isUsbReturnPending(this)") >= 2
        and "private boolean frameRetryIssued;" in service_source
        and "frame retry exhausted, fail-open hide" in service_source
        and "hideShield(\"frame-timeout-fail-open\")" in service_source,
        "receiver trust boundary is rechecked and the overlay retry is bounded",
    )
    check(
        "recreated_surface_can_acknowledge_new_owner",
        "notifiedRouteShield = false;" in framebuffer_source
        and framebuffer_source.index("notifiedRouteShield = false;")
        > framebuffer_source.index("public void surfaceChanged"),
        "surfaceChanged resets the per-surface frame acknowledgement",
    )

    aapt = sorted(
        (ROOT / "00_tools" / "android-sdk" / "build-tools").rglob("aapt.exe")
    )[-1]
    manifest_result = subprocess.run(
        [str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml"],
        capture_output=True,
        text=True,
    )
    check(
        "route_process_manifest_preserved",
        manifest_result.returncode == 0
        and ".Y2RouteShieldService" in manifest_result.stdout
        and ".Y2StorageReceiver" in manifest_result.stdout
        and manifest_result.stdout.count('=\":route\"') >= 3,
        {
            "returncode": manifest_result.returncode,
            "route_process_count": manifest_result.stdout.count('=\":route\"'),
        },
    )

    packaged_system_result = subprocess.run(
        [
            "wsl", "-d", "Ubuntu", "--cd", str(ROOT),
            "bash", "00_tools/validate_y2_v70_packaged_system.sh",
        ],
        capture_output=True,
        text=True,
    )
    check(
        "staged_system_apk_and_keylayouts_exact",
        packaged_system_result.returncode == 0,
        {
            "returncode": packaged_system_result.returncode,
            "stdout": packaged_system_result.stdout.strip(),
            "stderr": packaged_system_result.stderr.strip(),
        },
    )

    sparse = v47.sparse_layout(builder.OUT / "system.img")
    check(
        "system_sparse_has_no_fill_chunks",
        sparse["chunk_counts"].get("0xcac2", 0) == 0,
        sparse,
    )
    scatter = generic.parse_scatter(builder.OUT / "MT6582_Android_scatter.txt")
    fit = {
        "lk": ((builder.OUT / "lk.bin").stat().st_size,
               int(scatter["UBOOT"]["partition_size"])),
        "boot": ((builder.OUT / "boot.img").stat().st_size,
                 int(scatter["BOOTIMG"]["partition_size"])),
        "recovery": ((builder.OUT / "recovery.img").stat().st_size,
                     int(scatter["RECOVERY"]["partition_size"])),
        "system": (sparse["expanded_size"],
                   int(scatter["ANDROID"]["partition_size"])),
    }
    check(
        "all_images_fit_partitions",
        all(size <= limit for size, limit in fit.values()),
        fit,
    )
    generic_result = generic.validate_y2(builder.OUT, builder.OFFICIAL)
    check(
        "generic_firmware_reference_and_flash_config_pass",
        generic_result.get("is_y2_package") is True
        and generic_result.get("official_reference_complete") is True
        and generic_result.get("sp_flash_config_ok") is True,
        {
            "is_y2_package": generic_result.get("is_y2_package"),
            "official_reference_complete": generic_result.get("official_reference_complete"),
            "sp_flash_config_ok": generic_result.get("sp_flash_config_ok"),
        },
    )
    check(
        "manifest_scope_and_flash_safety",
        manifest["status"].startswith("targeted V69 physical-failure correction")
        and "physical validation required" in manifest["status"]
        and "Only system.img differs from V69" in manifest["firmware_delta"]
        and "never Format All" in manifest["flash_safety"],
        {
            "status": manifest["status"],
            "firmware_delta": manifest["firmware_delta"],
            "flash_safety": manifest["flash_safety"],
        },
    )

    (LOG_DIR / "v70-generic-firmware-validation.json").write_text(
        json.dumps(generic_result, indent=2) + "\n", encoding="utf-8"
    )
    (LOG_DIR / "v70-generic-firmware-validation.md").write_text(
        generic.render_markdown(generic_result), encoding="utf-8"
    )
    report = {
        "build": "y2-v70-usb-return-guard",
        "passed": all(item["passed"] for item in checks.values()),
        "checks_passed": sum(item["passed"] for item in checks.values()),
        "checks_total": len(checks),
        "checks": checks,
    }
    (LOG_DIR / "v70-structural-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Y2 V70 Structural Validation",
        "",
        f"Overall: {'PASS' if report['passed'] else 'FAIL'}",
        "",
        f"Checks: {report['checks_passed']}/{report['checks_total']}",
        "",
    ]
    lines.extend(
        f"- {'PASS' if item['passed'] else 'FAIL'} `{name}`"
        for name, item in checks.items()
    )
    lines.append("")
    (LOG_DIR / "v70-structural-validation.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
