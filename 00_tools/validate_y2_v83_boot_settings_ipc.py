#!/usr/bin/env python3
"""Offline structural, IPC, behavior and safety gate for Y2 V83."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v83-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v83_builder",
    ROOT / "00_tools" / "build_y2_v83_boot_settings_ipc.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def shell_parse(data: bytes) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as handle:
        handle.write(data)
        temp = Path(handle.name)
    try:
        drive = temp.drive.rstrip(":").lower()
        relative = temp.as_posix()[3:]
        wsl_temp = f"/mnt/{drive}/{relative}"
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "sh", "-n", wsl_temp],
            capture_output=True,
            text=True,
        )
        return {
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
        }
    finally:
        temp.unlink(missing_ok=True)


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    relative = resolved.as_posix()[3:]
    return f"/mnt/{drive}/{relative}"


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    expected_hash = builder.ZIP_SHA.read_text(
        encoding="ascii"
    ).split()[0]
    expected_members = set(builder.FILES) | {
        "y2-v83-boot-settings-ipc.json",
        "y2-v83-boot-settings-ipc.md",
        "V83-TEST.txt",
    }
    with zipfile.ZipFile(builder.ZIP) as archive:
        names = archive.namelist()
        bad = archive.testzip()
        packaged = {
            name: archive.read(name)
            for name in builder.FILES
        }
        manifest = json.loads(
            archive.read("y2-v83-boot-settings-ipc.json")
        )
        test_text = archive.read("V83-TEST.txt")
    with zipfile.ZipFile(builder.BASE_ZIP) as archive:
        base = {
            name: archive.read(name)
            for name in builder.FILES
        }

    check(
        "zip_crc_members_hash",
        bad is None
        and len(names) == len(set(names))
        and set(names) == expected_members
        and sha256(builder.ZIP) == expected_hash,
        {
            "bad": bad,
            "members": len(names),
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
        "all_unrelated_partitions_exact_v82",
        len(unchanged) == len(builder.FILES) - 3,
        unchanged,
    )
    check(
        "system_exact_staged",
        packaged["system.img"] == builder.V83_SYSTEM.read_bytes(),
        sha256_bytes(packaged["system.img"]),
    )
    check(
        "release_manifest_and_test_contract",
        manifest["build"] == "y2-v83-boot-settings-ipc"
        and manifest["base"]["sha256"] == builder.BASE_SHA256
        and manifest["base"]["zip"] == builder.BASE_ZIP.name
        and manifest["ipc"]["world_writable_files"] is False
        and manifest["ipc"]["shared_storage_mailbox"] is False
        and b"No button=Y2 Stock" in test_text
        and b"Volume Up=Rockbox" in test_text
        and b"automatic restart" in test_text
        and b"duplicate assignment" in test_text
        and b"both volume buttons" in test_text
        and b"official" not in test_text,
        manifest["status"],
    )
    package_manifest_text = json.dumps(manifest)
    check(
        "portable_package_manifest",
        "E:\\Y2 RockBox" not in package_manifest_text
        and "C:\\Users" not in package_manifest_text
        and "/mnt/e/" not in package_manifest_text,
        manifest["base"]["zip"],
    )

    guards: list[str] = []
    parses: dict[str, object] = {}
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
        guards.append(sha256_bytes(guard))
        parses[image_name] = shell_parse(guard)

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
            b'BUILD="y2-v83-boot-settings-ipc"',
            b'CONTENT="/system/bin/content"',
            b"content://org.rockbox.y2.bootroutes/request",
            b"content://org.rockbox.y2.bootroutes/response",
            b'"$CONTENT" query --uri "$REQUEST_URI"',
            b'"$CONTENT" insert --uri "$RESPONSE_URI"',
            b'"$CONTENT" delete --uri "$REQUEST_URI"',
            b"transport=content-provider",
            b"fields=valid",
            b"reason=malformed-provider-output",
            b'chmod 0600 "$ROUTE_MAP_TMP"',
            b'mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"',
            b"settings_broker=verified",
            b"settings_broker=acknowledged",
            b"settings_broker=reboot",
        )
        forbidden = (
            b"/data/data/org.rockbox",
            b"y2_boot_routes.request",
            b"/system/bin/run-as",
            b"transport=run-as",
            b"chmod 0666",
            b"chmod 0777",
            b"setenforce 0",
            b"permissive",
        )
        received = guard.find(b"settings_broker=received")
        invalid = guard.find(b'if [ "$REQUEST_VALID" -ne 1 ]')
        verified = guard.find(b"settings_broker=verified")
        acknowledged = guard.find(b"settings_broker=acknowledged")
        rebooted = guard.find(b"settings_broker=reboot")
        check(
            f"{image_name}_narrow_provider_transport_contract",
            all(token in guard for token in required)
            and all(token not in guard for token in forbidden)
            and 0 <= invalid < received < verified < acknowledged < rebooted,
            {
                "sha256": sha256_bytes(guard),
                "invalid": invalid,
                "received": received,
                "verified": verified,
                "acknowledged": acknowledged,
                "reboot": rebooted,
            },
        )

    check(
        "boot_recovery_guard_identical",
        len(set(guards)) == 1,
        guards,
    )
    check(
        "embedded_guard_shell_parse",
        all(item["returncode"] == 0 for item in parses.values()),
        parses,
    )

    provider_source = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
        / "src" / "org" / "rockbox" / "Y2BootRouteProvider.java"
    ).read_text(encoding="utf-8")
    system_control = (
        ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
        / "src" / "org" / "rockbox" / "Y2SystemControl.java"
    ).read_text(encoding="utf-8")
    app_manifest = (
        ROOT / "11_rockbox_android" / "rockbox-y1"
        / "android" / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    check(
        "provider_caller_uid_and_validation_contract",
        "Binder.getCallingUid()" in provider_source
        and "Process.myUid()" in provider_source
        and "uid != 0" in provider_source
        and "uid != Process.SYSTEM_UID" in provider_source
        and "uid != SHELL_UID" in provider_source
        and "isValidPermutation" in provider_source
        and "response does not match active request" in provider_source
        and ".edit().clear()" in provider_source
        and 'android:authorities="org.rockbox.y2.bootroutes"'
            in app_manifest
        and 'android:process=":bootroutes"' in app_manifest,
        "app-only request; matching root/system/shell response",
    )
    check(
        "app_ipc_client_no_private_mailbox",
        "Y2BootRouteProvider.REQUEST_URI" in system_control
        and "Y2BootRouteProvider.RESPONSE_URI" in system_control
        and "getContentResolver().insert" in system_control
        and "getContentResolver().query" in system_control
        and "getContentResolver().delete" in system_control
        and "y2_boot_routes.request" not in system_control
        and "FileOutputStream" not in system_control,
        "ContentResolver request/response with timeout cleanup",
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

    apk = builder.V83_APK
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
        "apk_provider_and_client_packaged",
        apk_bad is None
        and aapt_dump.returncode == 0
        and 'android:name(0x01010003)=".Y2BootRouteProvider"' in aapt_detail
        and "org.rockbox.y2.bootroutes" in aapt_detail
        and ":bootroutes" in aapt_detail
        and b"root/system/shell broker required" in dex
        and b"boot-route IPC request submitted" in dex,
        {"apk_sha256": sha256(apk), "aapt_exit": aapt_dump.returncode},
    )

    raw_system = (
        builder.WORK
        / "y2-rockbox-system-prototype-v83-boot-settings-ipc"
        / "system.raw.img"
    )
    dependency_stats: dict[str, object] = {}
    dependencies_ok = raw_system.is_file()
    for path, mode, label_token in (
        ("/bin/content", "Mode:  0755", "content_exec"),
        ("/priv-app/SettingsProvider.apk", "Mode:  0644", "system_file"),
    ):
        result = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--", "debugfs",
                "-R", f"stat {path}", wsl_path(raw_system),
            ],
            capture_output=True,
            text=True,
        )
        detail = result.stdout + result.stderr
        dependency_stats[path] = {
            "returncode": result.returncode,
            "mode": mode in detail,
            "label": label_token in detail,
        }
        dependencies_ok = (
            dependencies_ok
            and result.returncode == 0
            and mode in detail
            and label_token in detail
        )
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        content_jar = temp_root / "content.jar"
        content_dex = temp_root / "classes.dex"
        dump = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--", "debugfs",
                "-R",
                (
                    "dump /framework/content.jar "
                    f"{wsl_path(content_jar)}"
                ),
                wsl_path(raw_system),
            ],
            capture_output=True,
            text=True,
        )
        dexdump_detail = ""
        if dump.returncode == 0 and content_jar.is_file():
            with zipfile.ZipFile(content_jar) as archive:
                content_dex.write_bytes(archive.read("classes.dex"))
            dexdump = subprocess.run(
                [
                    str(
                        ROOT / "00_tools" / "android-sdk"
                        / "build-tools" / "19.1.0" / "dexdump.exe"
                    ),
                    "-d",
                    str(content_dex),
                ],
                capture_output=True,
                text=True,
            )
            dexdump_detail = dexdump.stdout + dexdump.stderr
        command_tokens = (
            '"--uri"',
            '"--bind"',
            '"insert"',
            '"delete"',
            '"query"',
            '"No result found."',
        )
        command_ops = (
            dump.returncode == 0
            and all(token in dexdump_detail for token in command_tokens)
        )
        dependency_stats["/framework/content.jar"] = {
            "returncode": dump.returncode,
            "query_insert_delete_bind": command_ops,
        }
        dependencies_ok = dependencies_ok and command_ops
    check(
        "packaged_android_ipc_dependencies",
        dependencies_ok,
        dependency_stats,
    )

    generic_md = LOG_DIR / "v83-generic-validation.md"
    generic_json = LOG_DIR / "v83-generic-validation.json"
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
        "build": "y2-v83-boot-settings-ipc",
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
