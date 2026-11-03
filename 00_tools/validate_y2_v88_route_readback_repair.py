#!/usr/bin/env python3
"""Offline source, ramdisk, package and behavior gate for Y2 V88."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v88-offline-validation"
APP_ROOT = (
    ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
    / "src" / "org" / "rockbox"
)
SYSTEM_DIR = (
    ROOT / "build-intermediates"
    / "y2-rockbox-system-prototype-v88-route-readback-repair"
)
APK = (
    ROOT / "build-intermediates"
    / "rockbox-android-y2-v88-route-readback-repair"
    / "rockbox-y2-v88-route-readback-repair.apk"
)
BROKER = ROOT / "00_tools" / "y2_v87_boot_save_broker.sh"
EVIDENCE = (
    ROOT / "evidence"
    / "v87-physical-save-persisted-next-boot-rockbox-20260729"
    / "evidence-summary.md"
)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v88_full_builder",
    ROOT / "00_tools" / "build_y2_v88_innioasis_updater_full.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def embedded(image: bytes) -> tuple[dict[str, bytes], bytes]:
    patcher = builder.v87.v86.v84.v81.v80.v79.v78.v77.v76
    entries, parts, _, _ = patcher.ramdisk(image)
    entry_map = {entry["name"]: entry["data"] for entry in entries}
    scripts = {
        name: entry_map[name]
        for name in builder.SCRIPT_NAMES
    }
    return scripts, parts["kernel"]


def read_kv_function(script: str) -> str:
    start = script.index("read_kv() {")
    end = script.index("\n}\n", start) + 3
    return script[start:end]


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    marker = (APP_ROOT / "Y2Marker.java").read_text()
    activity = (APP_ROOT / "Y2BootSettingsActivity.java").read_text()
    evidence = EVIDENCE.read_text()
    broker = BROKER.read_text()

    check(
        "v88_distinct_physical_marker",
        'BUILD_VERSION = "88"' in marker
        and "y2_rockbox_v88_route_readback_repair_marker.txt" in marker,
        "build 88 marker and snapshot names",
    )
    check(
        "calm_minimal_boot_settings_ui_retained",
        'prompt.setText("Normal boot")' in activity
        and activity.count("new RadioButton") == 2
        and 'saveButton.setText("Save & Restart")' in activity
        and "volumeUpSummary" not in activity
        and "fixedRoutes" not in activity,
        "short title, two choices and one save button",
    )
    check(
        "v87_echo_save_broker_reused_exactly",
        'BUILD="y2-v87-vendor-shell-save"' in broker
        and "printf" not in broker
        and 'echo "version=1"' in broker
        and 'VERIFY_NO=$(read_kv "$ROUTE_MAP_FILE" no_button)' in broker,
        "physically successful V87 save payload is unchanged",
    )
    check(
        "repair_bound_to_hash_clean_physical_evidence",
        "SHA-256 copy mismatches: 0" in evidence
        and "request `33249`" in evidence
        and "route_map_source=built-in-defaults" in evidence
        and "printf: not found" in evidence,
        "V87 save pass and immediate readback failure documented",
    )

    with zipfile.ZipFile(APK) as archive:
        apk_bad = archive.testzip()
        dex = archive.read("classes.dex")
    required_dex = (
        b"y2_rockbox_v88_route_readback_repair_marker.txt",
        b"Normal boot",
        b"Rockbox",
        b"Y2 Stock",
        b"Save & Restart",
        b"normal-boot save confirmed",
    )
    check(
        "apk_crc_and_v88_tokens",
        apk_bad is None and all(token in dex for token in required_dex),
        {"crc": apk_bad, "required": len(required_dex)},
    )
    check(
        "system_contains_exact_apk_and_proven_broker",
        (SYSTEM_DIR / "Rockbox.dump.apk").read_bytes()
            == APK.read_bytes()
        and (SYSTEM_DIR / "broker.dump.sh").read_bytes()
            == BROKER.read_bytes(),
        "dumped payloads match inputs byte-for-byte",
    )
    e2fsck_text = (SYSTEM_DIR / "e2fsck.txt").read_text(
        errors="replace")
    check(
        "system_filesystem_clean",
        all(f"Pass {number}:" in e2fsck_text for number in range(1, 6))
        and "UNEXPECTED INCONSISTENCY" not in e2fsck_text,
        e2fsck_text.strip().splitlines()[-1],
    )

    expected_names = {
        *builder.FIRMWARE_FILES,
        "V88-READ-ME-FIRST.txt",
        "y2-v88-route-readback-repair-innioasis-full.json",
    }
    with zipfile.ZipFile(builder.OUT) as archive:
        names = archive.namelist()
        package_bad = archive.testzip()
        data = {name: archive.read(name) for name in names}
    manifest = json.loads(
        data["y2-v88-route-readback-repair-innioasis-full.json"])
    check(
        "full_package_crc_unique_exact_members",
        package_bad is None
        and len(names) == len(set(names))
        and set(names) == expected_names,
        {"crc": package_bad, "members": len(names)},
    )
    selected = builder.v87.v86.v85.parse_selected(
        data["MT6582_Android_scatter.txt"])
    check(
        "full_stock_scatter_selects_all_12_images",
        selected == builder.EXPECTED_SELECTED
        and all(name in data for name in selected.values()),
        sorted(selected),
    )

    with zipfile.ZipFile(builder.BASE) as archive:
        base_data = {
            name: archive.read(name)
            for name in builder.FIRMWARE_FILES
        }
    changed = [
        name for name in builder.FIRMWARE_FILES
        if data[name] != base_data[name]
    ]
    check(
        "only_required_partitions_changed_from_v87",
        changed == ["boot.img", "recovery.img", "system.img"],
        changed,
    )

    expected_scripts = builder.v88_scripts(base_data["boot.img"])
    boot_scripts, boot_kernel = embedded(data["boot.img"])
    recovery_scripts, recovery_kernel = embedded(data["recovery.img"])
    _, base_boot_kernel = embedded(base_data["boot.img"])
    _, base_recovery_kernel = embedded(base_data["recovery.img"])
    check(
        "boot_embeds_exact_v88_scripts",
        boot_scripts == expected_scripts,
        {
            name: sha256_bytes(payload)
            for name, payload in boot_scripts.items()
        },
    )
    check(
        "recovery_embeds_exact_v88_scripts",
        recovery_scripts == expected_scripts,
        {
            name: sha256_bytes(payload)
            for name, payload in recovery_scripts.items()
        },
    )
    check(
        "boot_and_recovery_kernels_unchanged",
        boot_kernel == base_boot_kernel
        and recovery_kernel == base_recovery_kernel,
        sha256_bytes(boot_kernel),
    )
    check(
        "package_system_is_exact_v88_system",
        data["system.img"] == builder.V88_SYSTEM.read_bytes(),
        sha256_bytes(data["system.img"]),
    )

    decoded = {
        name: payload.decode("ascii")
        for name, payload in expected_scripts.items()
    }
    check(
        "no_printf_in_any_boot_handoff_reader",
        all("printf" not in script for script in decoded.values()),
        sorted(decoded),
    )
    check(
        "all_boot_handoff_readers_use_echo",
        all(
            'echo "${READ_KV_LINE#*=}"' in script
            for script in decoded.values()
        ),
        sorted(decoded),
    )
    check(
        "saved_route_map_path_and_defaults_unchanged",
        'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"'
            in decoded[builder.ROUTE_SCRIPT]
        and 'MAPPED_ROUTE="rockbox"' in decoded[builder.ROUTE_SCRIPT]
        and 'MAPPED_ROUTE="stock"' in decoded[builder.ROUTE_SCRIPT]
        and 'MAPPED_ROUTE="settings"' in decoded[builder.ROUTE_SCRIPT],
        "repair changes parser command, not routing semantics",
    )
    check(
        "v88_script_build_labels",
        'BUILD="y2-v88-route-readback-repair"'
            in decoded[builder.ROUTE_SCRIPT]
        and 'BUILD="y2-v88-stable-broker-launcher-v4"'
            in decoded[builder.ROUTE_GUARD]
        and 'BUILD="y2-v88-usb-readback-repair"'
            in decoded[builder.USB_GUARD],
        "distinct route, guard and USB labels",
    )

    syntax_results = {}
    for name, script in decoded.items():
        result = subprocess.run(
            ["wsl", "bash", "-n", "-"],
            input=script.encode("ascii"), capture_output=True,
        )
        syntax_results[name] = {
            "exit": result.returncode,
            "stderr": result.stderr.decode(
                "utf-8", errors="replace").strip(),
        }
    check(
        "embedded_shell_syntax",
        all(item["exit"] == 0 for item in syntax_results.values()),
        syntax_results,
    )

    route_function = read_kv_function(decoded[builder.ROUTE_SCRIPT])
    behavior_script = (
        "#!/usr/bin/env bash\nset -eu\n"
        + route_function
        + 'map="/tmp/y2-v88-route-map-$$"\n'
        + 'trap \'rm -f "$map"\' EXIT\n'
        + '{ echo "version=1"; echo "no_button=stock"; '
          'echo "volume_up=rockbox"; echo "volume_down=settings"; } > "$map"\n'
        + '[ "$(read_kv "$map" version)" = "1" ]\n'
        + '[ "$(read_kv "$map" no_button)" = "stock" ]\n'
        + '[ "$(read_kv "$map" volume_up)" = "rockbox" ]\n'
        + '[ "$(read_kv "$map" volume_down)" = "settings" ]\n'
    )
    behavior = subprocess.run(
        ["wsl", "bash", "-s"],
        input=behavior_script.encode("ascii"), capture_output=True,
    )
    check(
        "exact_route_read_kv_behavior",
        behavior.returncode == 0,
        behavior.stderr.decode("utf-8", errors="replace").strip()
            or "saved Stock map read exactly",
    )

    broker_test = ROOT / "00_tools" / "test_y2_v87_boot_save_broker.py"
    broker_wsl = "/mnt/e/" + broker_test.relative_to(
        Path("E:/")).as_posix()
    broker_behavior = subprocess.run(
        ["wsl", "python3", broker_wsl],
        cwd=ROOT, text=True, capture_output=True,
    )
    check(
        "physically_proven_broker_behavior_regression",
        broker_behavior.returncode == 0
        and "vendor-shell command allowlist" in broker_behavior.stdout,
        broker_behavior.stdout.strip() or broker_behavior.stderr.strip(),
    )
    check(
        "manifest_records_exact_physical_root_cause",
        manifest["physical_evidence"]["v87_save_service"] == "passed"
        and manifest["physical_evidence"]["v87_next_boot"] == "rockbox"
        and "printf" in manifest["physical_evidence"]["root_cause"]
        and manifest["repair"]["unsupported_printf_in_patched_scripts"]
            is False,
        manifest["physical_evidence"],
    )
    image_hashes = manifest["image_sha256"]
    check(
        "manifest_binds_all_image_hashes",
        set(image_hashes)
            == set(builder.FIRMWARE_FILES)
                - {"MT6582_Android_scatter.txt"}
        and all(
            sha256_bytes(data[name]) == digest
            for name, digest in image_hashes.items()
        ),
        len(image_hashes),
    )
    check(
        "package_hash_sidecar",
        builder.OUT_SHA.read_text(encoding="ascii").split()[0]
            == sha256(builder.OUT),
        sha256(builder.OUT),
    )

    passed = sum(item["passed"] for item in checks.values())
    report = {
        "package": "y2-v88-route-readback-repair-innioasis-full",
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
