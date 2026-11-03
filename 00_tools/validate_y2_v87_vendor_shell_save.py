#!/usr/bin/env python3
"""Offline source, image, package, and broker gate for Y2 V87."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v87-offline-validation"
APP_ROOT = (
    ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
    / "src" / "org" / "rockbox"
)
SYSTEM_DIR = (
    ROOT / "build-intermediates"
    / "y2-rockbox-system-prototype-v87-vendor-shell-save"
)
APK = (
    ROOT / "build-intermediates"
    / "rockbox-android-y2-v87-vendor-shell-save"
    / "rockbox-y2-v87-vendor-shell-save.apk"
)
BROKER = ROOT / "00_tools" / "y2_v87_boot_save_broker.sh"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v87_full_builder",
    ROOT / "00_tools" / "build_y2_v87_innioasis_updater_full.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def embedded_guard(image: bytes) -> tuple[bytes, bytes]:
    patcher = builder.v86.v84.v81.v80.v79.v78.v77.v76
    entries, parts, _, _ = patcher.ramdisk(image)
    entry_map = {entry["name"]: entry["data"] for entry in entries}
    return entry_map[builder.v86.v84.ROUTE_GUARD], parts["kernel"]


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    activity = (APP_ROOT / "Y2BootSettingsActivity.java").read_text()
    marker = (APP_ROOT / "Y2Marker.java").read_text()
    provider = (APP_ROOT / "Y2BootRouteProvider.java").read_text()
    control = (APP_ROOT / "Y2SystemControl.java").read_text()
    broker = BROKER.read_text()
    expected_guard = builder.v87_route_guard()
    guard_text = expected_guard.decode("ascii")

    check(
        "calm_minimal_boot_settings_ui",
        'prompt.setText("Normal boot")' in activity
        and activity.count("new RadioButton") == 2
        and 'saveButton.setText("Save & Restart")' in activity
        and "volumeUpSummary" not in activity
        and "fixedRoutes" not in activity,
        "title, short label, two choices and one save button",
    )
    check(
        "v87_marker",
        'BUILD_VERSION = "87"' in marker
        and "y2_rockbox_v87_vendor_shell_save_marker.txt" in marker,
        "distinct physical marker",
    )
    check(
        "protocol_and_current_boot_binding",
        'EXPECTED_PROTOCOL_VERSION = "3"' in provider
        and 'PROTOCOL_VERSION="3"' in broker
        and "isCurrentBootId" in provider
        and "normal-boot request submitted" in control,
        "protocol 3 and exact boot ID retained",
    )
    unsupported = (
        "printf",
        "mktemp",
        "awk",
        "sed ",
        "cut ",
        "head ",
        "tail ",
        "install ",
    )
    retained = [token for token in unsupported if token in broker]
    check(
        "physical_vendor_shell_allowlist",
        not retained,
        {"forbidden_retained": retained},
    )
    check(
        "echo_atomic_route_map_writer",
        'echo "version=1"' in broker
        and 'echo "no_button=$REQUEST_NORMAL"' in broker
        and 'chmod 0600 "$ROUTE_MAP_TMP"' in broker
        and 'mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"' in broker,
        "no printf; echo block, 0600 temp and atomic rename",
    )
    check(
        "real_provider_health_probe",
        "query_request() {" in broker
        and "save_broker=health-failed" in broker
        and "health=provider-query-ok" in broker,
        "ready uses the real content provider",
    )
    check(
        "root_reread_ack_reboot",
        'VERIFY_NO=$(read_kv "$ROUTE_MAP_FILE" no_button)' in broker
        and "write_response ok" in broker
        and "save_broker=acknowledged" in broker
        and "reboot" in broker,
        "exact reread precedes acknowledgement and reboot",
    )
    check(
        "bootclasspath_repair_retained",
        "export BOOTCLASSPATH BOOTCLASSPATH_EX" in guard_text
        and "BOOTCLASSPATH_MISSING" in guard_text
        and 'BUILD="y2-v87-stable-broker-launcher-v3"' in guard_text,
        "V86 physical classpath/provider repair retained",
    )
    check(
        "broker_only_runs_in_boot_settings",
        'if [ "$ROUTE" = "settings" ]; then' in guard_text
        and guard_text.count("        run_settings_broker") == 1,
        "no polling during Rockbox or stock playback",
    )

    with zipfile.ZipFile(APK) as archive:
        apk_bad = archive.testzip()
        dex = archive.read("classes.dex")
    required_dex = (
        b"y2_rockbox_v87_vendor_shell_save_marker.txt",
        b"Normal boot",
        b"Rockbox",
        b"Y2 Stock",
        b"Save & Restart",
        b"Could not save. Try again.",
        b"normal-boot save confirmed",
    )
    forbidden_dex = (
        b"When the player is powered on normally, start:",
        b"Holding Volume Up at power-on will start ",
        b"Hold Volume Down at power-on",
    )
    check(
        "apk_crc_and_ui_tokens",
        apk_bad is None
        and all(token in dex for token in required_dex)
        and all(token not in dex for token in forbidden_dex),
        {"crc": apk_bad, "required": len(required_dex)},
    )
    check(
        "system_contains_exact_apk_and_broker",
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
        "V87-READ-ME-FIRST.txt",
        "y2-v87-vendor-shell-save-innioasis-full.json",
    }
    with zipfile.ZipFile(builder.OUT) as archive:
        names = archive.namelist()
        package_bad = archive.testzip()
        data = {name: archive.read(name) for name in names}
    manifest = json.loads(
        data["y2-v87-vendor-shell-save-innioasis-full.json"])
    check(
        "full_package_crc_unique_exact_members",
        package_bad is None
        and len(names) == len(set(names))
        and set(names) == expected_names,
        {"crc": package_bad, "members": len(names)},
    )
    selected = builder.v86.v85.parse_selected(
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
        "only_required_partitions_changed_from_v86",
        changed == ["boot.img", "recovery.img", "system.img"],
        changed,
    )
    boot_guard, boot_kernel = embedded_guard(data["boot.img"])
    recovery_guard, recovery_kernel = embedded_guard(data["recovery.img"])
    _, base_boot_kernel = embedded_guard(base_data["boot.img"])
    _, base_recovery_kernel = embedded_guard(base_data["recovery.img"])
    check(
        "boot_and_recovery_embed_exact_v87_guard",
        boot_guard == expected_guard and recovery_guard == expected_guard,
        sha256_bytes(expected_guard),
    )
    check(
        "boot_and_recovery_kernels_unchanged",
        boot_kernel == base_boot_kernel
        and recovery_kernel == base_recovery_kernel,
        sha256_bytes(boot_kernel),
    )
    check(
        "package_system_is_exact_v87_system",
        data["system.img"] == builder.V87_SYSTEM.read_bytes(),
        sha256_bytes(data["system.img"]),
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
    evidence = (
        ROOT / "evidence" / "v86-physical-save-write-failed-20260729"
        / "evidence-summary.md"
    ).read_text()
    check(
        "repair_is_bound_to_physical_v86_evidence",
        "printf: not found" in evidence
        and "error-write-failed" in evidence
        and "SHA-256 mismatches: 0" in evidence,
        "hash-clean physical failure is documented",
    )

    broker_wsl = "/mnt/e/" + BROKER.relative_to(
        Path("E:/")).as_posix()
    syntax = subprocess.run(
        ["wsl", "bash", "-n", broker_wsl],
        cwd=ROOT, text=True, capture_output=True,
    )
    check(
        "broker_shell_syntax",
        syntax.returncode == 0,
        syntax.stderr.strip() or "bash -n passed",
    )
    behavior_path = (
        ROOT / "00_tools" / "test_y2_v87_boot_save_broker.py")
    behavior_wsl = "/mnt/e/" + behavior_path.relative_to(
        Path("E:/")).as_posix()
    behavior = subprocess.run(
        ["wsl", "python3", behavior_wsl],
        cwd=ROOT, text=True, capture_output=True,
    )
    check(
        "broker_behavioral_test",
        behavior.returncode == 0
        and "vendor-shell command allowlist" in behavior.stdout,
        behavior.stdout.strip() or behavior.stderr.strip(),
    )

    passed = sum(item["passed"] for item in checks.values())
    report = {
        "package": "y2-v87-vendor-shell-save-innioasis-full",
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
