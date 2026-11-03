#!/usr/bin/env python3
"""Offline structural, coherence, transport and flash-safety gate for V84."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v84-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v84_builder",
    ROOT / "00_tools" / "build_y2_v84_coherent_boot_settings.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    relative = resolved.as_posix()[3:]
    return f"/mnt/{drive}/{relative}"


def shell_parse(data: bytes) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as handle:
        handle.write(data)
        temp = Path(handle.name)
    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "sh", "-n", wsl_path(temp)],
            capture_output=True,
            text=True,
        )
        return {
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
        }
    finally:
        temp.unlink(missing_ok=True)


def simulate_system_broker(
        helper: bytes,
        permutations: list[tuple[str, str, str]]) -> dict[str, object]:
    """Exercise the packaged shell broker with a narrow fake content CLI."""

    boot_id = "11111111-2222-3333-4444-555555555555"
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        fake_content = root / "content"
        request = root / "request.txt"
        response = root / "response.txt"
        route_map = root / "route-map.txt"
        reboot_marker = root / "reboot.txt"
        log = root / "broker.log"
        test_helper = root / "broker-under-test.sh"
        fake_content.write_text(
            "#!/bin/sh\n"
            "case \"$1:$3\" in\n"
            "  insert:*'/status') exit 0 ;;\n"
            "  query:*'/request') cat \"$FAKE_REQUEST\"; exit 0 ;;\n"
            "  insert:*'/response') printf '%s\\n' \"$@\" > "
            "\"$FAKE_RESPONSE\"; exit 0 ;;\n"
            "  delete:*'/request') : > \"$FAKE_REQUEST\"; exit 0 ;;\n"
            "esac\n"
            "exit 12\n",
            encoding="ascii",
            newline="\n",
        )
        fake_content.chmod(0o755)
        helper_text = helper.decode("ascii")
        helper_text = helper_text.replace(
            'CONTENT="/system/bin/content"',
            f'CONTENT="{wsl_path(fake_content)}"',
            1,
        )
        helper_text = helper_text.replace(
            'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"',
            f'ROUTE_MAP_FILE="{wsl_path(route_map)}"',
            1,
        )
        helper_text = helper_text.replace(
            "CURRENT_BOOT_ID=$(cat /proc/sys/kernel/random/boot_id "
            "2>/dev/null)",
            'CURRENT_BOOT_ID="$EXPECTED_BOOT_ID"',
            1,
        )
        helper_text = helper_text.replace("                sleep 2", "                sleep 0", 1)
        helper_text = helper_text.replace(
            "                reboot",
            f"                printf 'reboot\\n' > "
            f'"{wsl_path(reboot_marker)}"',
            1,
        )
        test_helper.write_text(helper_text, encoding="ascii", newline="\n")

        common_env = [
            "env",
            f"FAKE_REQUEST={wsl_path(request)}",
            f"FAKE_RESPONSE={wsl_path(response)}",
        ]
        ready = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--", *common_env,
                "sh", wsl_path(test_helper), "ready", "settings",
                boot_id, wsl_path(log),
            ],
            capture_output=True,
            text=True,
        )
        if ready.returncode != 0:
            return {
                "ready_returncode": ready.returncode,
                "ready_output": ready.stdout + ready.stderr,
                "permutations": [],
            }

        for index, values in enumerate(permutations, start=1):
            no_button, volume_up, volume_down = values
            request_id = str(80000 + index)
            request.write_text(
                "Row: 0 protocol_version=2, "
                "broker_build=y2-v84-coherent-boot-settings, "
                f"boot_id={boot_id}, request_id={request_id}, "
                f"no_button={no_button}, volume_up={volume_up}, "
                f"volume_down={volume_down}, reboot=1\n",
                encoding="ascii",
                newline="\n",
            )
            for path in (response, route_map, reboot_marker):
                path.unlink(missing_ok=True)
            run = subprocess.run(
                [
                    "wsl", "-d", "Ubuntu", "--", *common_env,
                    "sh", wsl_path(test_helper), "poll", "settings",
                    boot_id, wsl_path(log),
                ],
                capture_output=True,
                text=True,
            )
            expected_map = (
                "version=1\n"
                f"no_button={no_button}\n"
                f"volume_up={volume_up}\n"
                f"volume_down={volume_down}\n"
            )
            response_text = (
                response.read_text(encoding="ascii")
                if response.is_file() else ""
            )
            assertions = {
                "returncode": run.returncode == 0,
                "route_map": (
                    route_map.is_file()
                    and route_map.read_text(encoding="ascii") == expected_map
                ),
                "protocol": "protocol_version:s:2" in response_text,
                "build": (
                    "broker_build:s:y2-v84-coherent-boot-settings"
                    in response_text
                ),
                "boot_id": f"boot_id:s:{boot_id}" in response_text,
                "request_id": f"request_id:s:{request_id}" in response_text,
                "status": "status:s:ok" in response_text,
                "reboot": reboot_marker.is_file(),
            }
            passed = all(assertions.values())
            results.append({
                "map": "/".join(values),
                "returncode": run.returncode,
                "passed": passed,
                "assertions": assertions,
            })

        request.write_text(
            "Row: 0 protocol_version=2, broker_build=wrong-build, "
            f"boot_id={boot_id}, request_id=89999, "
            "no_button=rockbox, volume_up=stock, "
            "volume_down=settings, reboot=1\n",
            encoding="ascii",
            newline="\n",
        )
        for path in (response, route_map, reboot_marker):
            path.unlink(missing_ok=True)
        invalid = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--", *common_env,
                "sh", wsl_path(test_helper), "poll", "settings",
                boot_id, wsl_path(log),
            ],
            capture_output=True,
            text=True,
        )
        invalid_response = (
            response.read_text(encoding="ascii")
            if response.is_file() else ""
        )
        invalid_passed = (
            invalid.returncode == 6
            and "status:s:error-invalid-request" in invalid_response
            and not route_map.exists()
            and not reboot_marker.exists()
        )
    return {
        "ready_returncode": ready.returncode,
        "permutations": results,
        "invalid_request_returncode": invalid.returncode,
        "invalid_request_passed": invalid_passed,
    }


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    expected_hash = builder.ZIP_SHA.read_text(
        encoding="ascii"
    ).split()[0]
    expected_members = set(builder.FILES) | {
        "y2-v84-coherent-boot-settings.json",
        "y2-v84-coherent-boot-settings.md",
        "V84-TEST.txt",
    }
    with zipfile.ZipFile(builder.ZIP) as archive:
        full_names = archive.namelist()
        full_bad = archive.testzip()
        packaged = {
            name: archive.read(name)
            for name in builder.FILES
        }
        manifest = json.loads(
            archive.read("y2-v84-coherent-boot-settings.json")
        )
        test_text = archive.read("V84-TEST.txt")
    with zipfile.ZipFile(builder.BASE_ZIP) as archive:
        base = {
            name: archive.read(name)
            for name in builder.FILES
        }

    check(
        "full_zip_crc_members_hash",
        full_bad is None
        and len(full_names) == len(set(full_names))
        and set(full_names) == expected_members
        and sha256(builder.ZIP) == expected_hash,
        {
            "bad": full_bad,
            "members": len(full_names),
            "sha256": sha256(builder.ZIP),
        },
    )
    changed = [
        name for name in builder.FILES
        if packaged[name] != base[name]
    ]
    check(
        "partition_delta_exact",
        changed == ["boot.img", "recovery.img", "system.img"],
        changed,
    )
    unchanged = [
        name for name in builder.FILES
        if name not in ("boot.img", "recovery.img", "system.img")
        and packaged[name] == base[name]
    ]
    check(
        "all_unrelated_partitions_exact_v83",
        len(unchanged) == len(builder.FILES) - 3,
        unchanged,
    )
    check(
        "system_exact_staged",
        packaged["system.img"] == builder.V84_SYSTEM.read_bytes(),
        sha256_bytes(packaged["system.img"]),
    )
    manifest_text = json.dumps(manifest)
    check(
        "release_manifest_and_test_contract",
        manifest["build"] == "y2-v84-coherent-boot-settings"
        and manifest["base"]["sha256"] == builder.BASE_SHA256
        and manifest["architecture"]["protocol"] == "2"
        and manifest["safety"]["world_writable_files"] is False
        and manifest["safety"]["shared_storage_mailbox"] is False
        and manifest["safety"]["targeted_update_partitions"]
            == ["BOOTIMG", "RECOVERY", "ANDROID"]
        and b"Firmware ready" in test_text
        and b"all three selected rows" in test_text
        and b"Download Only" in test_text,
        manifest["status"],
    )
    check(
        "portable_package_manifest",
        "E:\\Y2 RockBox" not in manifest_text
        and "C:\\Users" not in manifest_text
        and "/mnt/e/" not in manifest_text,
        manifest["base"]["zip"],
    )

    guard_hashes: list[str] = []
    guard_parses: dict[str, object] = {}
    for image_name in ("boot.img", "recovery.img"):
        entries, parts, _, label = (
            builder.v81.v80.v79.v78.v77.v76.ramdisk(
                packaged[image_name]
            )
        )
        base_entries, base_parts, _, base_label = (
            builder.v81.v80.v79.v78.v77.v76.ramdisk(
                base[image_name]
            )
        )
        entry_map = {
            entry["name"]: entry["data"]
            for entry in entries
        }
        base_map = {
            entry["name"]: entry["data"]
            for entry in base_entries
        }
        guard = entry_map[builder.ROUTE_GUARD]
        guard_hashes.append(sha256_bytes(guard))
        guard_parses[image_name] = shell_parse(guard)
        changed_entries = sorted(
            name for name in entry_map
            if entry_map[name] != base_map.get(name)
        )
        check(
            f"{image_name}_guard_only_ramdisk_payload_delta",
            changed_entries == [builder.ROUTE_GUARD]
            and parts["kernel"] == base_parts["kernel"]
            and label == base_label,
            {
                "changed_entries": changed_entries,
                "kernel": sha256_bytes(parts["kernel"]),
                "label": label,
            },
        )
        required = (
            b'BUILD="y2-v84-stable-broker-launcher-v1"',
            b'BROKER_HELPER="/system/etc/y2_boot_route_broker.sh"',
            b'SYSTEM_SHELL="/system/bin/sh"',
            b'"$SYSTEM_SHELL" "$BROKER_HELPER" ready',
            b'"$SYSTEM_SHELL" "$BROKER_HELPER" poll',
            b"settings_broker=launcher-ready",
            b"helper-missing",
            b'BOOT_ID=$(cat /proc/sys/kernel/random/boot_id',
        )
        forbidden = (
            b"content://org.rockbox.y2.bootroutes",
            b"protocol_version",
            b"broker_build",
            b"y2_boot_routes.request",
            b"/system/bin/run-as",
            b"chmod 0666",
            b"setenforce 0",
        )
        check(
            f"{image_name}_stable_launcher_contract",
            all(token in guard for token in required)
            and all(token not in guard for token in forbidden),
            {"sha256": sha256_bytes(guard), "size": len(guard)},
        )
    check(
        "boot_recovery_launcher_identical",
        len(set(guard_hashes)) == 1,
        guard_hashes,
    )
    check(
        "embedded_launcher_shell_parse",
        all(
            item["returncode"] == 0
            for item in guard_parses.values()
        ),
        guard_parses,
    )

    helper = builder.SYSTEM_BROKER.read_bytes()
    helper_parse = shell_parse(helper)
    helper_required = (
        b'BUILD="y2-v84-coherent-boot-settings"',
        b'PROTOCOL_VERSION="2"',
        b"/proc/sys/kernel/random/boot_id",
        b"content://org.rockbox.y2.bootroutes/status",
        b"content://org.rockbox.y2.bootroutes/request",
        b"content://org.rockbox.y2.bootroutes/response",
        b"--bind \"protocol_version:s:$PROTOCOL_VERSION\"",
        b"--bind \"broker_build:s:$BUILD\"",
        b"--bind \"boot_id:s:$EXPECTED_BOOT_ID\"",
        b'chmod 0600 "$ROUTE_MAP_TMP"',
        b'mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"',
        b"settings_broker=received",
        b"settings_broker=verified",
        b"settings_broker=acknowledged",
        b"settings_broker=reboot",
    )
    received = helper.find(b"settings_broker=received")
    verified = helper.find(b"settings_broker=verified")
    acknowledged = helper.find(b"settings_broker=acknowledged")
    rebooted = helper.find(b"settings_broker=reboot")
    check(
        "system_broker_transport_write_verify_contract",
        helper_parse["returncode"] == 0
        and all(token in helper for token in helper_required)
        and 0 <= received < verified < acknowledged < rebooted
        and b"chmod 0666" not in helper
        and b"setenforce 0" not in helper
        and b"/data/data/org.rockbox" not in helper,
        {
            "sha256": sha256_bytes(helper),
            "parse": helper_parse,
            "ordering": [received, verified, acknowledged, rebooted],
        },
    )

    provider_source = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
        / "src" / "org" / "rockbox" / "Y2BootRouteProvider.java"
    ).read_text(encoding="utf-8")
    system_control = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
        / "src" / "org" / "rockbox" / "Y2SystemControl.java"
    ).read_text(encoding="utf-8")
    settings_activity = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
        / "src" / "org" / "rockbox" / "Y2BootSettingsActivity.java"
    ).read_text(encoding="utf-8")
    app_manifest = (
        ROOT / "11_rockbox_android" / "rockbox-y1"
        / "android" / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    check(
        "provider_current_boot_coherence_contract",
        'EXPECTED_PROTOCOL_VERSION = "2"' in provider_source
        and '"y2-v84-coherent-boot-settings"' in provider_source
        and 'addURI(AUTHORITY, "status"' in provider_source
        and "isCurrentBootId" in provider_source
        and "Y2BootState.currentBootId()" in provider_source
        and "Binder.getCallingUid()" in provider_source
        and "response does not match active request" in provider_source
        and 'android:process=":bootroutes"' in app_manifest,
        "protocol + build + current Linux boot ID",
    )
    check(
        "app_pre_save_coherence_gate",
        "bootRouteBrokerStatus" in system_control
        and "Y2BootRouteProvider.STATUS_URI" in system_control
        and "current_boot_id=" in system_control
        and "compatibility rejected" in system_control
        and "checkFirmwareCompatibility" in settings_activity
        and "Firmware update incomplete" in settings_activity
        and "Retry Firmware Check" in settings_activity
        and settings_activity.index("bootRouteBrokerStatus")
            < settings_activity.index("persistBootRouteMap")
        and "Save timed out. Nothing was changed" not in settings_activity,
        "Save disabled until exact current-boot broker handshake",
    )

    actions = ("rockbox", "stock", "settings")
    valid = [
        values for values in itertools.product(actions, repeat=3)
        if len(set(values)) == 3 and "settings" in values
    ]
    check(
        "six_permutation_contract",
        len(valid) == 6,
        ["/".join(values) for values in valid],
    )
    broker_behavior = simulate_system_broker(helper, valid)
    check(
        "system_broker_six_permutation_behavior",
        broker_behavior["ready_returncode"] == 0
        and len(broker_behavior["permutations"]) == 6
        and all(
            item["passed"]
            for item in broker_behavior["permutations"]
        )
        and broker_behavior["invalid_request_passed"] is True,
        broker_behavior,
    )

    apk = builder.V84_APK
    aapt = (
        ROOT / "00_tools" / "android-sdk"
        / "build-tools" / "19.1.0" / "aapt.exe"
    )
    aapt_dump = subprocess.run(
        [str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml"],
        capture_output=True,
        text=True,
    )
    aapt_detail = aapt_dump.stdout + aapt_dump.stderr
    with zipfile.ZipFile(apk) as archive:
        apk_bad = archive.testzip()
        dex = archive.read("classes.dex")
    check(
        "apk_handshake_and_provider_packaged",
        apk_bad is None
        and aapt_dump.returncode == 0
        and 'android:name(0x01010003)=".Y2BootRouteProvider"'
            in aapt_detail
        and "org.rockbox.y2.bootroutes" in aapt_detail
        and ":bootroutes" in aapt_detail
        and b"y2-v84-coherent-boot-settings" in dex
        and b"current_boot_id" in dex
        and b"Firmware update incomplete" in dex,
        {"apk_sha256": sha256(apk), "aapt_exit": aapt_dump.returncode},
    )

    raw_system = (
        builder.WORK
        / "y2-rockbox-system-prototype-v84-coherent-boot-settings"
        / "system.raw.img"
    )
    system_stats: dict[str, object] = {}
    system_ok = raw_system.is_file()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        dumped_helper = temp_root / "broker.sh"
        dumped_apk = temp_root / "Rockbox.apk"
        for internal, output in (
            ("/etc/y2_boot_route_broker.sh", dumped_helper),
            ("/app/Rockbox.apk", dumped_apk),
        ):
            dump = subprocess.run(
                [
                    "wsl", "-d", "Ubuntu", "--", "debugfs",
                    "-R", f"dump {internal} {wsl_path(output)}",
                    wsl_path(raw_system),
                ],
                capture_output=True,
                text=True,
            )
            system_stats[internal] = {"dump_exit": dump.returncode}
            system_ok = system_ok and dump.returncode == 0
        helper_stat = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--", "debugfs",
                "-R", "stat /etc/y2_boot_route_broker.sh",
                wsl_path(raw_system),
            ],
            capture_output=True,
            text=True,
        )
        helper_xattr = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--", "debugfs",
                "-R", "ea_list /etc/y2_boot_route_broker.sh",
                wsl_path(raw_system),
            ],
            capture_output=True,
            text=True,
        )
        helper_detail = helper_stat.stdout + helper_stat.stderr
        xattr_detail = helper_xattr.stdout + helper_xattr.stderr
        exact_helper = (
            dumped_helper.is_file()
            and dumped_helper.read_bytes() == helper
        )
        exact_apk = (
            dumped_apk.is_file()
            and dumped_apk.read_bytes() == apk.read_bytes()
        )
        system_ok = (
            system_ok
            and exact_helper
            and exact_apk
            and "Mode:  0644" in helper_detail
            and "u:object_r:system_file:s0" in xattr_detail
        )
        system_stats["coherence"] = {
            "exact_helper": exact_helper,
            "exact_apk": exact_apk,
            "helper_mode_0644": "Mode:  0644" in helper_detail,
            "helper_selinux_system_file":
                "u:object_r:system_file:s0" in xattr_detail,
        }
    check(
        "app_and_broker_exact_in_same_system_image",
        system_ok,
        system_stats,
    )

    update_expected_hash = builder.UPDATE_SHA.read_text(
        encoding="ascii"
    ).split()[0]
    expected_update_names = {
        builder.UPDATE_SCATTER,
        "V84_BOOTIMG_REQUIRED.img",
        "V84_RECOVERY_REQUIRED.img",
        "V84_SYSTEM_REQUIRED.img",
        "V84-READ-ME-FIRST.txt",
        "V84-REQUIRED-SHA256.txt",
        "y2-v84-targeted-update.json",
    }
    with zipfile.ZipFile(builder.UPDATE_ZIP) as archive:
        update_names = archive.namelist()
        update_bad = archive.testzip()
        update_data = {
            name: archive.read(name)
            for name in update_names
        }
        update_manifest = json.loads(
            update_data["y2-v84-targeted-update.json"]
        )
    check(
        "targeted_update_zip_crc_members_hash",
        update_bad is None
        and len(update_names) == len(set(update_names))
        and set(update_names) == expected_update_names
        and sha256(builder.UPDATE_ZIP) == update_expected_hash,
        {
            "bad": update_bad,
            "members": len(update_names),
            "sha256": sha256(builder.UPDATE_ZIP),
        },
    )

    scatter = update_data[builder.UPDATE_SCATTER].decode("ascii")
    selected: dict[str, str] = {}
    disabled_ok = True
    for block in re.split(
            r"(?=^- partition_index:)", scatter, flags=re.MULTILINE):
        partition_match = re.search(
            r"^  partition_name: (.+)$", block, re.MULTILINE)
        if partition_match is None:
            continue
        partition = partition_match.group(1).strip()
        file_match = re.search(
            r"^  file_name: (.+)$", block, re.MULTILINE)
        download_match = re.search(
            r"^  is_download: (.+)$", block, re.MULTILINE)
        file_name = file_match.group(1).strip() if file_match else ""
        is_download = (
            download_match.group(1).strip() if download_match else ""
        )
        if is_download == "true":
            selected[partition] = file_name
        elif file_name != "NONE" or is_download != "false":
            disabled_ok = False
    expected_selected = {
        partition: target_name
        for partition, (_, target_name)
        in builder.UPDATE_IMAGES.items()
    }
    check(
        "targeted_scatter_exact_three_required_partitions",
        selected == expected_selected
        and disabled_ok
        and scatter.count("  is_download: true") == 3,
        selected,
    )
    image_matches = {}
    for partition, (source_name, target_name) in (
            builder.UPDATE_IMAGES.items()):
        exact = update_data[target_name] == packaged[source_name]
        hash_matches_manifest = (
            sha256_bytes(update_data[target_name])
            == update_manifest["image_sha256"][target_name]
        )
        image_matches[partition] = {
            "exact_full_package_image": exact,
            "hash_matches_manifest": hash_matches_manifest,
        }
    check(
        "targeted_images_exact_and_hash_bound",
        all(
            item["exact_full_package_image"]
            and item["hash_matches_manifest"]
            for item in image_matches.values()
        )
        and update_manifest["all_three_required"] is True
        and update_manifest["format_all_forbidden"] is True,
        image_matches,
    )

    generic_md = LOG_DIR / "v84-generic-validation.md"
    generic_json = LOG_DIR / "v84-generic-validation.json"
    generic = subprocess.run(
        [
            "python",
            str(ROOT / "00_tools" / "y2_firmware_validator.py"),
            str(builder.ZIP),
            "--out-md", str(generic_md),
            "--out-json", str(generic_json),
        ],
        capture_output=True,
        text=True,
    )
    check(
        "generic_y2_validator",
        generic.returncode == 0,
        {
            "returncode": generic.returncode,
            "valid_package_shape": generic.returncode == 0,
        },
    )

    passed = sum(1 for item in checks.values() if item["passed"])
    report = {
        "build": "y2-v84-coherent-boot-settings",
        "passed": passed,
        "total": len(checks),
        "all_passed": passed == len(checks),
        "checks": checks,
    }
    (LOG_DIR / "validation.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
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
