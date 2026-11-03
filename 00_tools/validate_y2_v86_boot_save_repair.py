#!/usr/bin/env python3
"""Offline source, image, and full-package gate for Y2 V86."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v86-offline-validation"
APP_ROOT = (
    ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
    / "src" / "org" / "rockbox"
)
SYSTEM_DIR = (
    ROOT / "build-intermediates"
    / "y2-rockbox-system-prototype-v86-boot-save-repair"
)
APK = (
    ROOT / "build-intermediates"
    / "rockbox-android-y2-v86-boot-save-repair"
    / "rockbox-y2-v86-boot-save-repair.apk"
)
BROKER = ROOT / "00_tools" / "y2_v86_boot_save_broker.sh"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v86_full_builder",
    ROOT / "00_tools" / "build_y2_v86_innioasis_updater_full.py",
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
    patcher = builder.v84.v81.v80.v79.v78.v77.v76
    entries, parts, _, _ = patcher.ramdisk(image)
    entry_map = {entry["name"]: entry["data"] for entry in entries}
    return entry_map[builder.v84.ROUTE_GUARD], parts["kernel"]


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
    expected_guard = builder.v86_route_guard()

    check(
        "calm_minimal_boot_settings_ui",
        'prompt.setText("Normal boot")' in activity
        and activity.count("new RadioButton") == 2
        and 'saveButton.setText("Save & Restart")' in activity
        and "volumeUpSummary" not in activity
        and "fixedRoutes" not in activity
        and "When the player is powered on normally" not in activity
        and "Holding Volume Up at power-on" not in activity,
        "title, short label, two choices and one save button",
    )
    check(
        "simple_save_failure_copy",
        '"Could not save. Try again."' in activity
        and "Could not reach the boot save service" not in activity,
        "one concise recoverable error",
    )
    check(
        "single_choice_route_policy",
        "oppositePlayer(normalBoot)" in activity
        and "volumeDown = Y2BootState.BOOT_SETTINGS" in activity
        and 'REQUEST_UP="stock"' in broker
        and 'REQUEST_UP="rockbox"' in broker
        and 'REQUEST_DOWN="settings"' in broker,
        "normal boot selectable; Volume Up opposite; Volume Down settings",
    )
    check(
        "v86_marker",
        'BUILD_VERSION = "86"' in marker
        and "y2_rockbox_v86_boot_save_repair_marker.txt" in marker,
        "distinct V86 physical marker",
    )
    check(
        "protocol_and_current_boot_binding",
        'EXPECTED_PROTOCOL_VERSION = "3"' in provider
        and 'PROTOCOL_VERSION="3"' in broker
        and "isCurrentBootId" in provider
        and 'CURRENT_BOOT_ID=$(cat /proc/sys/kernel/random/boot_id'
            in broker
        and "normal-boot request submitted" in control,
        "protocol 3 and exact current Linux boot ID",
    )
    check(
        "real_provider_health_probe",
        "query_request() {" in broker
        and 'case "$ACTION" in' in broker
        and "save_broker=health-failed" in broker
        and "health=provider-query-ok" in broker,
        "ready invokes the real content query and validates its output",
    )
    check(
        "provider_errors_cannot_look_successful",
        '*"Error while accessing provider:"*|*"Exception"*)'
            in broker
        and "unexpected-content-output" in broker
        and "delete --uri" not in broker,
        "exit-zero Java errors rejected; malformed output not deleted",
    )
    check(
        "atomic_verified_root_write",
        'ROUTE_MAP_TMP="$ROUTE_MAP_FILE.tmp.$$"' in broker
        and 'chmod 0600 "$ROUTE_MAP_TMP"' in broker
        and 'mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"' in broker
        and 'VERIFY_NO=$(read_kv "$ROUTE_MAP_FILE" no_button)'
            in broker
        and "write_response ok" in broker
        and "reboot" in broker,
        "0600 temp+rename, exact reread, ack, reboot",
    )
    guard_text = expected_guard.decode("ascii")
    check(
        "guard_repairs_bootclasspath_before_java_tools",
        f'CANONICAL_BOOTCLASSPATH="{builder.CANONICAL_BOOTCLASSPATH}"'
            in guard_text
        and "export BOOTCLASSPATH BOOTCLASSPATH_EX" in guard_text
        and guard_text.index("export BOOTCLASSPATH BOOTCLASSPATH_EX")
            < guard_text.index("run_settings_broker()")
        and "BOOTCLASSPATH_MISSING" in guard_text,
        "canonical device classpath exported and every JAR checked",
    )
    check(
        "broker_only_runs_in_boot_settings",
        'if [ "$ROUTE" = "settings" ]; then' in guard_text
        and guard_text.count("        run_settings_broker") == 1,
        "no provider polling during Rockbox or stock playback",
    )
    check(
        "guard_logs_into_existing_sd_collector_path",
        'DATA_ROOT="/data/local/tmp/Y2_V81_DEBUG"' in guard_text
        and 'BUILD="y2-v86-stable-broker-launcher-v2"' in guard_text
        and "inherited_BOOTCLASSPATH=" in guard_text
        and "missing_boot_jars=" in guard_text,
        "existing early diagnostic copier will collect exact V86 guard log",
    )

    with zipfile.ZipFile(APK) as archive:
        apk_bad = archive.testzip()
        dex = archive.read("classes.dex")
    required_dex = (
        b"y2_rockbox_v86_boot_save_repair_marker.txt",
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
        {
            "crc": apk_bad,
            "required": len(required_dex),
            "forbidden": len(forbidden_dex),
        },
    )
    check(
        "system_contains_exact_apk_and_broker",
        (SYSTEM_DIR / "Rockbox.dump.apk").read_bytes()
            == APK.read_bytes()
        and (SYSTEM_DIR / "broker.dump.sh").read_bytes()
            == BROKER.read_bytes(),
        "dumped system payloads match V86 source inputs",
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
        "V86-READ-ME-FIRST.txt",
        "y2-v86-boot-save-repair-innioasis-full.json",
    }
    with zipfile.ZipFile(builder.OUT) as archive:
        names = archive.namelist()
        package_bad = archive.testzip()
        data = {name: archive.read(name) for name in names}
    manifest = json.loads(
        data["y2-v86-boot-save-repair-innioasis-full.json"])
    check(
        "full_package_crc_unique_exact_members",
        package_bad is None
        and len(names) == len(set(names))
        and set(names) == expected_names,
        {"crc": package_bad, "members": len(names)},
    )
    check(
        "full_stock_scatter_selects_all_12_images",
        builder.v85.parse_selected(
            data["MT6582_Android_scatter.txt"])
            == builder.EXPECTED_SELECTED
        and all(
            name in data for name in builder.EXPECTED_SELECTED.values()),
        sorted(builder.EXPECTED_SELECTED),
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
        "only_required_partitions_changed_from_v85",
        changed == ["boot.img", "recovery.img", "system.img"],
        changed,
    )
    boot_guard, boot_kernel = embedded_guard(data["boot.img"])
    recovery_guard, recovery_kernel = embedded_guard(data["recovery.img"])
    _, base_boot_kernel = embedded_guard(base_data["boot.img"])
    _, base_recovery_kernel = embedded_guard(base_data["recovery.img"])
    check(
        "boot_and_recovery_embed_exact_v86_guard",
        boot_guard == expected_guard and recovery_guard == expected_guard,
        {
            "guard_sha256": sha256_bytes(expected_guard),
            "boot_match": boot_guard == expected_guard,
            "recovery_match": recovery_guard == expected_guard,
        },
    )
    check(
        "boot_and_recovery_kernels_unchanged",
        boot_kernel == base_boot_kernel
        and recovery_kernel == base_recovery_kernel,
        {
            "boot_kernel_sha256": sha256_bytes(boot_kernel),
            "recovery_kernel_sha256": sha256_bytes(recovery_kernel),
        },
    )
    check(
        "package_system_is_exact_v86_system",
        data["system.img"] == builder.V86_SYSTEM.read_bytes(),
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

    broker_wsl = "/mnt/e/" + BROKER.relative_to(
        Path("E:/")).as_posix()
    shell_result = subprocess.run(
        ["wsl", "bash", "-n", broker_wsl],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    check(
        "broker_shell_syntax",
        shell_result.returncode == 0,
        shell_result.stderr.strip() or "bash -n passed",
    )

    passed = sum(item["passed"] for item in checks.values())
    report = {
        "package": "y2-v86-boot-save-repair-innioasis-full",
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
