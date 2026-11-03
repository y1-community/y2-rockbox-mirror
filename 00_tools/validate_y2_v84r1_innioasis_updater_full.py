#!/usr/bin/env python3
"""Offline gate for the V84R1 full Innioasis Updater package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v84r1-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v84r1_builder",
    ROOT / "00_tools" / "build_y2_v84r1_innioasis_updater_full.py",
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
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    expected_names = {
        *builder.FIRMWARE_FILES,
        "V84R1-READ-ME-FIRST.txt",
        "y2-v84r1-innioasis-updater-full.json",
    }
    with zipfile.ZipFile(builder.OUT) as archive:
        names = archive.namelist()
        bad = archive.testzip()
        data = {name: archive.read(name) for name in names}
    manifest = json.loads(
        data["y2-v84r1-innioasis-updater-full.json"])
    check(
        "zip_crc_unique_exact_members",
        bad is None
        and len(names) == len(set(names))
        and set(names) == expected_names,
        {"bad": bad, "members": len(names)},
    )
    expected_zip_hash = builder.OUT_SHA.read_text(
        encoding="ascii").split()[0]
    check(
        "zip_hash_sidecar",
        sha256(builder.OUT) == expected_zip_hash,
        sha256(builder.OUT),
    )

    stock_scatter = (
        builder.STOCK / "MT6582_Android_scatter.txt").read_bytes()
    selected = builder.parse_selected(
        data["MT6582_Android_scatter.txt"])
    check(
        "exact_official_scatter_and_full_selection",
        data["MT6582_Android_scatter.txt"] == stock_scatter
        and selected == builder.EXPECTED_SELECTED
        and len(selected) == 12,
        selected,
    )
    check(
        "all_selected_images_present",
        all(file_name in data for file_name in selected.values()),
        sorted(selected.values()),
    )

    stock_results = {}
    for name in sorted(builder.STOCK_BOUND_IMAGES):
        exact = data[name] == (builder.STOCK / name).read_bytes()
        stock_results[name] = exact
    check(
        "preloader_tables_and_restore_images_exact_stock",
        all(stock_results.values()),
        stock_results,
    )

    with zipfile.ZipFile(builder.V84_FULL) as archive:
        v84_data = {
            name: archive.read(name)
            for name in builder.FIRMWARE_FILES
        }
    image_results = {
        name: data[name] == v84_data[name]
        for name in builder.FIRMWARE_FILES
    }
    check(
        "all_firmware_images_exact_reproduced_v84_full",
        all(image_results.values()),
        image_results,
    )

    hash_results = {
        name: (
            sha256_bytes(data[name])
            == manifest["image_sha256"][name]
        )
        for name in manifest["image_sha256"]
    }
    check(
        "manifest_binds_every_image_hash",
        all(hash_results.values())
        and set(hash_results)
        == set(builder.FIRMWARE_FILES) - {"MT6582_Android_scatter.txt"},
        hash_results,
    )
    check(
        "manifest_records_format_download_compatibility",
        manifest["mode_required_by_installed_updater"]
        == "format-download"
        and manifest["selected_partition_count"] == 12
        and manifest["preloader_exact_official_stock"] is True
        and "three-partition package" in manifest["reason"],
        manifest["reason"],
    )

    readme = data["V84R1-READ-ME-FIRST.txt"].decode("utf-8")
    check(
        "readme_rejects_targeted_package_and_prioritizes_stock_recovery",
        "three-partition-update.zip is rejected" in readme
        and "erases the full eMMC" in readme
        and "restore official stock first" in readme,
        "explicit recovery warning present",
    )

    updater_log = (
        ROOT / "evidence"
        / "v84-targeted-format-download-failure-20260728"
        / "SP_FT_Dump_07-28-2026-23-17-51"
        / "QT_FLASH_TOOL.log"
    )
    retry_log = (
        ROOT / "evidence"
        / "v84-targeted-format-download-failure-20260728"
        / "SP_FT_Dump_07-28-2026-23-20-17"
        / "QT_FLASH_TOOL.log"
    )
    first_text = updater_log.read_text(encoding="utf-8", errors="ignore")
    retry_text = retry_log.read_text(encoding="utf-8", errors="ignore")
    retry_brom_log = retry_log.with_name("BROM_DLL_V5.log")
    retry_brom_text = retry_brom_log.read_text(
        encoding="utf-8", errors="ignore")
    check(
        "physical_log_proves_unexpected_full_format",
        "DLPlugFmtAll Command::Create" in first_text
        and "Format_ALL(0x0, 0x1d2880000)" in first_text
        and "S_SECURITY_SECURE_USB_DL_DA_RETURN_INVALID_TYPE(6104)"
            in first_text,
        "format 0x0+0x1d2880000 then 6104",
    )
    check(
        "physical_retry_proves_brom_dram_failure",
        "pid_0003" in retry_text.lower()
        and "S_DL_GET_DRAM_SETTING_FAIL(5054)" in retry_text
        and "file_length(0) is NOT valid" in retry_brom_text
        and "EMI setting () is not ready" in retry_brom_text,
        "raw BROM PID 0003; zero-length preloader/EMI source; then 5054",
    )

    scatter_text = data["MT6582_Android_scatter.txt"].decode("ascii")
    preloader_block = re.search(
        r"- partition_index: SYS0.*?(?=\n- partition_index:)",
        scatter_text,
        flags=re.DOTALL,
    )
    check(
        "official_preloader_enabled_for_brom_emi",
        preloader_block is not None
        and "file_name: preloader_eastaeon82_wet_kk.bin"
            in preloader_block.group(0)
        and "is_download: true" in preloader_block.group(0),
        "official preloader selected",
    )

    passed = sum(item["passed"] for item in checks.values())
    report = {
        "package": "y2-v84r1-innioasis-updater-full",
        "passed": passed,
        "total": len(checks),
        "all_passed": passed == len(checks),
        "checks": checks,
    }
    (LOG_DIR / "validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (LOG_DIR / "validation-summary.txt").write_text(
        "\n".join(
            f"{'PASS' if item['passed'] else 'FAIL'} "
            f"{name}: {item['detail']}"
            for name, item in checks.items()
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "passed": passed,
        "total": len(checks),
        "all_passed": report["all_passed"],
        "report": str(LOG_DIR / "validation.json"),
    }, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
