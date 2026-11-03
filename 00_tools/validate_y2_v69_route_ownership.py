#!/usr/bin/env python3
"""Structural, policy, and packaging validation for Y2 V69."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v69-offline-validation"
EXPECTED_ZIP_SHA256 = "2A74CE99B413270BEAA033C3F043A6E1361A24731E831FC156EAB15078574134"
PACKAGED_RAW = Path(
    r"E:\Y2-RockBox-build-intermediates\v69-packaged-expanded.raw"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_module(
    "v69_builder",
    ROOT / "00_tools" / "build_y2_v69_route_ownership.py",
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


def recovery_details(blob: bytes):
    parts = builder.boot_tools.parse_boot_image(blob)
    parser = builder.v68.v67.recovery_parser()
    _, cpio, label = parser.parse_mtk_ramdisk(parts["ramdisk"])
    entries = {
        item["name"]: item
        for item in builder.boot_tools.parse_cpio_newc(cpio)
    }
    return parts, label, entries


def entry_signature(entry: dict):
    return (
        entry["data"],
        entry["mode"],
        entry["uid"],
        entry["gid"],
        entry["nlink"],
        entry["mtime"],
    )


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
        manifest = json.loads(
            archive.read(builder.REPORT_JSON).decode("utf-8")
        )
    check("zip_crc_clean", bad_member is None, bad_member)
    check(
        "zip_members_unique_and_exact",
        len(names) == len(set(names)) and set(names) == expected_members,
        {"entries": len(names), "expected": len(expected_members)},
    )
    check(
        "published_zip_hash_exact",
        sha256(builder.ZIP) == EXPECTED_ZIP_SHA256,
        sha256(builder.ZIP),
    )
    check(
        "v68_base_zip_exact",
        sha256(builder.V68_ZIP) == builder.V68_ZIP_SHA256,
        sha256(builder.V68_ZIP),
    )

    with zipfile.ZipFile(builder.V68_ZIP) as archive:
        base = {name: archive.read(name) for name in builder.FILES}
    changed = [
        name for name in builder.FILES
        if sha256_bytes(packaged[name]) != sha256_bytes(base[name])
    ]
    check(
        "firmware_delta_system_and_recovery_only",
        changed == ["recovery.img", "system.img"],
        changed,
    )
    check(
        "system_image_exact_staged_v69",
        packaged["system.img"] == builder.V69_SYSTEM.read_bytes(),
        sha256_bytes(packaged["system.img"]),
    )

    base_parts, base_label, base_entries = recovery_details(base["recovery.img"])
    out_parts, out_label, out_entries = recovery_details(packaged["recovery.img"])
    payloads = builder.script_payloads()
    changed_entries = sorted(
        name for name in set(base_entries) | set(out_entries)
        if name not in base_entries
        or name not in out_entries
        or entry_signature(base_entries[name]) != entry_signature(out_entries[name])
    )
    check(
        "recovery_delta_four_generated_scripts_only",
        changed_entries == sorted(payloads),
        changed_entries,
    )
    static_headers_exact = (
        set(base_parts) == set(out_parts)
        and all(
            base_parts[name] == out_parts[name]
            for name in base_parts
            if name not in {"ramdisk", "ramdisk_size", "image_id"}
        )
    )
    check(
        "recovery_kernel_headers_label_exact_v68",
        static_headers_exact
        and out_parts["kernel"] == base_parts["kernel"]
        and out_label == base_label,
        {"static_headers": static_headers_exact, "label": out_label},
    )
    check(
        "recovery_init_environment_exact_v68",
        all(
            entry_signature(out_entries[name]) == entry_signature(base_entries[name])
            for name in ("init.rc", "init.environ.rc")
        ),
        "critical recovery init and environment entries",
    )

    route = out_entries[builder.ROUTE_SCRIPT]["data"]
    exact_boot = (
        b"com.innioasis.y2/com.innioasis.y1.receiver.BootCompletedReceiver"
    )
    exact_sd = b"com.innioasis.y2/com.innioasis.y1.receiver.SDReceiver"
    required_route_tokens = (
        b"COMPONENT_POLICY_APPLIED=0",
        b"restore-on-every-boot-then-isolate-only-popup-producing-receivers-on-rockbox",
        b"Rockbox-route isolation before mount/boot broadcasts",
        b"stock-component-policy-not-applied",
        b"action=observe-only-single-owner-coordinator",
    )
    check(
        "early_exact_stock_receiver_policy_present",
        all(token in route for token in required_route_tokens)
        and route.count(b'pm enable "$STOCK_BOOT_RECEIVER"') == 1
        and route.count(b'pm enable "$STOCK_SD_RECEIVER"') == 1
        and route.count(b'pm disable "$STOCK_BOOT_RECEIVER"') == 1
        and route.count(b'pm disable "$STOCK_SD_RECEIVER"') == 1
        and exact_boot in route and exact_sd in route,
        {token.decode("ascii"): route.count(token) for token in required_route_tokens},
    )
    check(
        "receiver_policy_precedes_route_receiver_readiness",
        route.index(b"COMPONENT_POLICY_APPLIED=0")
        < route.index(b'grep -F "org.rockbox/.Y2FirmwareRouteReceiver"')
        < route.index(b'command=am broadcast -a $ACTION'),
        "stock components are handled before route dispatch and mount delivery window",
    )
    forbidden_route = (
        b"am force-stop",
        b"kill -9",
        b"pm clear",
        b'pm disable "$STOCK_PACKAGE"',
        b"setprop sys.boot_completed",
    )
    check(
        "no_broad_stock_or_platform_mutation",
        not any(token in route for token in forbidden_route),
        {token.decode("ascii"): route.count(token) for token in forbidden_route},
    )

    guard = out_entries[builder.ROUTE_GUARD]["data"]
    forbidden_guard = (
        b"am start",
        b"am broadcast",
        b"pm disable",
        b"input keyevent",
        b"CANCEL_SCAN",
    )
    check(
        "route_guard_is_passive_evidence_only",
        b"policy=passive-evidence-only" in guard
        and not any(token in guard for token in forbidden_guard),
        {token.decode("ascii"): guard.count(token) for token in forbidden_guard},
    )
    usb_guard = out_entries[builder.USB_GUARD]["data"]
    check(
        "shell_usb_guard_explicit_fallback_only",
        b"one-second-fallback-primary-is-direct-manifest-receiver" in usb_guard,
        "direct manifest receiver is primary; shell remains bounded fallback",
    )

    extracted_dir = LOG_DIR / "embedded-scripts"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    shell_results = {}
    for name in sorted(payloads):
        extracted = extracted_dir / Path(name).name
        extracted.write_bytes(out_entries[name]["data"])
        result = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--cd", str(ROOT),
                "sh", "-n",
                str(extracted.relative_to(ROOT)).replace("\\", "/"),
            ],
            capture_output=True,
            text=True,
        )
        shell_results[name] = {
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
        }
    check(
        "all_embedded_shell_scripts_parse",
        all(item["returncode"] == 0 for item in shell_results.values()),
        shell_results,
    )

    apk = (
        ROOT / "12_build_outputs" / "rockbox-android-y2-v69"
        / "rockbox-y2-v69-route-owner.apk"
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
        b"Y2RouteShieldService:shield shown reason=",
        b"Y2RouteShieldService:single-owner launch reason=",
        b"Y2StorageReceiver:UsbStorageActivity requested directly",
        b"RockboxFramebuffer:first frame signalled to route shield",
        b"scanner-finished is not a launch trigger",
    )
    check(
        "route_owner_apk_crc_tokens_and_native_boundary",
        apk_bad is None
        and all(token in dex for token in dex_tokens)
        and native == stable_native,
        {
            "apk_sha256": sha256(apk),
            "native_count": len(native),
            "tokens": {token.decode("ascii"): dex.count(token) for token in dex_tokens},
        },
    )

    aapt = sorted(
        (ROOT / "00_tools" / "android-sdk" / "build-tools").rglob("aapt.exe")
    )[-1]
    permission_result = subprocess.run(
        [str(aapt), "dump", "permissions", str(apk)],
        capture_output=True,
        text=True,
    )
    manifest_result = subprocess.run(
        [str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml"],
        capture_output=True,
        text=True,
    )
    manifest_text = manifest_result.stdout
    check(
        "overlay_permission_and_route_process_manifest",
        permission_result.returncode == 0
        and "android.permission.SYSTEM_ALERT_WINDOW" in permission_result.stdout
        and manifest_result.returncode == 0
        and ".Y2RouteShieldService" in manifest_text
        and ".Y2StorageReceiver" in manifest_text
        and manifest_text.count('=":route"') >= 3,
        {
            "permission_returncode": permission_result.returncode,
            "manifest_returncode": manifest_result.returncode,
            "route_process_count": manifest_text.count('=":route"'),
        },
    )

    sparse = v47.sparse_layout(builder.OUT / "system.img")
    check(
        "system_sparse_has_no_fill_chunks",
        sparse["chunk_counts"].get("0xcac2", 0) == 0,
        sparse,
    )
    packaged_system_result = subprocess.run(
        [
            "wsl", "-d", "Ubuntu", "--cd", str(ROOT),
            "bash", "00_tools/validate_y2_v69_packaged_system.sh",
        ],
        capture_output=True,
        text=True,
    )
    check(
        "packaged_system_apk_and_device_keylayouts_exact",
        PACKAGED_RAW.is_file() and packaged_system_result.returncode == 0,
        {
            "expanded_raw": str(PACKAGED_RAW),
            "returncode": packaged_system_result.returncode,
            "stdout": packaged_system_result.stdout.strip(),
            "stderr": packaged_system_result.stderr.strip(),
        },
    )

    service_source = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android" / "src"
        / "org" / "rockbox" / "RockboxService.java"
    ).read_text(encoding="utf-8")
    check(
        "theme_and_settings_retention_preserved",
        "boolean shouldWrite = generated && !current;" in service_source
        and "boolean shouldWrite = !current;" not in service_source,
        "valid user-selected Rockbox config is not overwritten",
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
            "official_reference_complete": generic_result.get(
                "official_reference_complete"
            ),
            "sp_flash_config_ok": generic_result.get("sp_flash_config_ok"),
        },
    )
    check(
        "manifest_scope_status_and_flash_safety",
        manifest["status"].startswith("root-cause ownership candidate")
        and "physical validation required" in manifest["status"]
        and "never Format All" in manifest["flash_safety"]
        and len(manifest["next_test"]) == 3,
        {
            "status": manifest["status"],
            "flash_safety": manifest["flash_safety"],
        },
    )

    (LOG_DIR / "v69-generic-firmware-validation.json").write_text(
        json.dumps(generic_result, indent=2) + "\n", encoding="utf-8"
    )
    (LOG_DIR / "v69-generic-firmware-validation.md").write_text(
        generic.render_markdown(generic_result), encoding="utf-8"
    )
    report = {
        "build": "y2-v69-route-ownership",
        "passed": all(item["passed"] for item in checks.values()),
        "checks_passed": sum(item["passed"] for item in checks.values()),
        "checks_total": len(checks),
        "checks": checks,
    }
    (LOG_DIR / "v69-structural-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Y2 V69 Structural Validation",
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
    (LOG_DIR / "v69-structural-validation.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
