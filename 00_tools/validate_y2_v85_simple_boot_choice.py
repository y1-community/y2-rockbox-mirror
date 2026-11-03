#!/usr/bin/env python3
"""Offline source, image, and full-package gate for Y2 V85."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v85-offline-validation"
APP_ROOT = (
    ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
    / "src" / "org" / "rockbox"
)
SYSTEM_DIR = (
    ROOT / "build-intermediates"
    / "y2-rockbox-system-prototype-v85-simple-boot-choice"
)
APK = (
    ROOT / "build-intermediates"
    / "rockbox-android-y2-v85-simple-boot-choice"
    / "rockbox-y2-v85-simple-boot-choice.apk"
)
BROKER = ROOT / "00_tools" / "y2_v85_boot_choice_broker.sh"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v85_full_builder",
    ROOT / "00_tools" / "build_y2_v85_innioasis_updater_full.py",
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

    activity = (APP_ROOT / "Y2BootSettingsActivity.java").read_text()
    control = (APP_ROOT / "Y2SystemControl.java").read_text()
    provider = (APP_ROOT / "Y2BootRouteProvider.java").read_text()
    broker = BROKER.read_text()
    marker = (APP_ROOT / "Y2Marker.java").read_text()

    check(
        "single_user_choice_ui",
        "RadioGroup normalBootChoices" in activity
        and '"Rockbox"' in activity
        and '"Y2 Stock"' in activity
        and "Spinner" not in activity
        and "firmware compatibility" not in activity.lower(),
        "one two-option radio group; compatibility gate absent",
    )
    check(
        "derived_and_fixed_routes",
        "oppositePlayer(normalBoot)" in activity
        and "volumeDown = Y2BootState.BOOT_SETTINGS" in activity
        and 'REQUEST_UP="stock"' in broker
        and 'REQUEST_UP="rockbox"' in broker
        and 'REQUEST_DOWN="settings"' in broker,
        "Volume Up derived; Volume Down fixed in UI and root helper",
    )
    check(
        "unchanged_choice_can_be_saved",
        "if (!hasUnsavedChanges())" in activity
        and "saveAndExit();" in activity
        and "nothing was changed" not in activity.lower(),
        "save button always submits; back alone uses dirty-state check",
    )
    check(
        "stable_minimal_protocol",
        'EXPECTED_PROTOCOL_VERSION = "3"' in provider
        and 'PROTOCOL_VERSION="3"' in broker
        and "NORMAL_BOOT" in provider
        and "BROKER_BUILD" not in provider
        and "STATUS_URI" not in provider
        and "bootRouteBrokerStatus" not in control,
        "protocol 3 carries only current-boot request/ack fields",
    )
    check(
        "caller_and_current_boot_guards",
        "requireAppCaller()" in provider
        and "requireBrokerCaller()" in provider
        and "Binder.getCallingUid()" in provider
        and "isCurrentBootId" in provider
        and 'CURRENT_BOOT_ID=$(cat /proc/sys/kernel/random/boot_id'
            in broker,
        "app/root caller separation and boot-ID binding retained",
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
    check(
        "v85_marker",
        'BUILD_VERSION = "85"' in marker
        and "y2_rockbox_v85_simple_boot_choice_marker.txt" in marker,
        "V85 debug marker is distinct",
    )

    with zipfile.ZipFile(APK) as archive:
        apk_bad = archive.testzip()
        dex = archive.read("classes.dex")
    dex_tokens = [
        b"y2_rockbox_v85_simple_boot_choice_marker.txt",
        b"normal_boot",
        b"Save & Restart",
        b"normal-boot request submitted",
        b"normal-boot save confirmed",
    ]
    check(
        "apk_crc_and_v85_tokens",
        apk_bad is None and all(token in dex for token in dex_tokens),
        {"crc": apk_bad, "tokens": len(dex_tokens)},
    )

    dumped_helper = SYSTEM_DIR / "broker.dump.sh"
    check(
        "system_contains_exact_apk_and_helper",
        (SYSTEM_DIR / "Rockbox.dump.apk").read_bytes()
            == APK.read_bytes()
        and dumped_helper.read_bytes() == BROKER.read_bytes(),
        "dumped system payloads match inputs",
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
        "V85-READ-ME-FIRST.txt",
        "y2-v85-simple-boot-choice-innioasis-full.json",
    }
    with zipfile.ZipFile(builder.OUT) as archive:
        names = archive.namelist()
        package_bad = archive.testzip()
        data = {name: archive.read(name) for name in names}
    manifest = json.loads(
        data["y2-v85-simple-boot-choice-innioasis-full.json"])
    check(
        "full_package_crc_unique_exact_members",
        package_bad is None
        and len(names) == len(set(names))
        and set(names) == expected_names,
        {"crc": package_bad, "members": len(names)},
    )
    check(
        "full_stock_scatter_selects_12_images",
        data["MT6582_Android_scatter.txt"]
            == (builder.STOCK / "MT6582_Android_scatter.txt").read_bytes()
        and builder.parse_selected(
            data["MT6582_Android_scatter.txt"])
            == builder.EXPECTED_SELECTED
        and all(name in data for name in builder.EXPECTED_SELECTED.values()),
        sorted(builder.EXPECTED_SELECTED),
    )
    with zipfile.ZipFile(builder.BASE) as archive:
        base_data = {
            name: archive.read(name)
            for name in builder.FIRMWARE_FILES
        }
    unchanged = {
        name: data[name] == base_data[name]
        for name in builder.FIRMWARE_FILES
        if name not in {"system.img"}
    }
    check(
        "only_system_changed_from_validated_v84r1",
        all(unchanged.values())
        and data["system.img"] == builder.V85_SYSTEM.read_bytes()
        and data["system.img"] != base_data["system.img"],
        unchanged,
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
        "package": "y2-v85-simple-boot-choice-innioasis-full",
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
