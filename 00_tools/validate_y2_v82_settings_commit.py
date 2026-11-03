#!/usr/bin/env python3
"""Offline structural and safety gate for Y2 V82."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v82-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v82_builder",
    ROOT / "00_tools" / "build_y2_v82_settings_commit.py",
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
        wsl_path = f"/mnt/{drive}/{relative}"
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "sh", "-n", wsl_path],
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
        "y2-v82-settings-commit.json",
        "y2-v82-settings-commit.md",
        "V82-TEST.txt",
    }
    with zipfile.ZipFile(builder.ZIP) as archive:
        names = archive.namelist()
        bad = archive.testzip()
        packaged = {
            name: archive.read(name)
            for name in builder.FILES
        }
        manifest = json.loads(
            archive.read("y2-v82-settings-commit.json")
        )
        test_text = archive.read("V82-TEST.txt")
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
        changed == ["boot.img", "recovery.img"],
        changed,
    )
    unchanged = [
        name for name in builder.FILES
        if name not in ("boot.img", "recovery.img")
        and packaged[name] == base[name]
    ]
    check(
        "all_non_ramdisk_partitions_exact_v81",
        len(unchanged) == len(builder.FILES) - 2,
        unchanged,
    )
    check(
        "release_manifest_and_test_contract",
        manifest["build"] == "y2-v82-settings-commit"
        and manifest["base"]["sha256"] == builder.BASE_SHA256
        and b"No button=Y2 Stock" in test_text
        and b"Volume Up=Rockbox" in test_text
        and b"automatic reboot" in test_text
        and b"duplicate assignment" in test_text
        and b"both volume buttons" in test_text,
        manifest["status"],
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
            b'BUILD="y2-v82-settings-commit"',
            b'RUN_AS="/system/bin/run-as"',
            b'APP_PACKAGE="org.rockbox"',
            b'"$RUN_AS" "$APP_PACKAGE" /system/bin/cat',
            b'"$RUN_AS" "$APP_PACKAGE" /system/bin/sh -c',
            b'transport=run-as',
            b'chmod 0600 "$REQUEST_COPY_TMP"',
            b'chmod 0600 "$RESPONSE_PAYLOAD"',
            b'mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"',
            b"settings_broker=verified",
            b"settings_broker=acknowledged",
            b"settings_broker=reboot",
        )
        forbidden = (
            b'chmod 0666',
            b'chmod 0777',
            b"setenforce 0",
            b"permissive",
        )
        check(
            f"{image_name}_run_as_private_transport_contract",
            all(token in guard for token in required)
            and all(token not in guard for token in forbidden),
            sha256_bytes(guard),
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

    # V81's exact system image contains the run-as executable and the exact
    # debuggable APK that produced physical request 37548. These byte checks
    # prevent the transport proof from silently changing either dependency.
    v81_system = base["system.img"]
    check(
        "system_and_apk_dependency_exact_v81",
        packaged["system.img"] == v81_system
        and manifest["files"]["system.img"]["matches_v81"],
        sha256_bytes(packaged["system.img"]),
    )
    raw_system = (
        builder.WORK
        / "y2-rockbox-system-prototype-v81-continuous-handoff"
        / "system.raw.img"
    )
    app_manifest = (
        builder.ROOT
        / "11_rockbox_android"
        / "rockbox-y1"
        / "android"
        / "AndroidManifest.xml"
    )
    run_as = subprocess.run(
        [
            "wsl",
            "-d",
            "Ubuntu",
            "--",
            "debugfs",
            "-R",
            "stat /bin/run-as",
            wsl_path(raw_system),
        ],
        capture_output=True,
        text=True,
    )
    run_as_detail = run_as.stdout + run_as.stderr
    check(
        "run_as_and_debuggable_app_dependencies",
        raw_system.is_file()
        and app_manifest.is_file()
        and run_as.returncode == 0
        and "Mode:  0750" in run_as_detail
        and "runas_exec" in run_as_detail
        and 'android:debuggable="true"' in app_manifest.read_text(
            encoding="utf-8"
        ),
        {
            "returncode": run_as.returncode,
            "run_as_0750": "Mode:  0750" in run_as_detail,
            "run_as_selinux_label": "runas_exec" in run_as_detail,
            "app_debuggable": (
                'android:debuggable="true"'
                in app_manifest.read_text(encoding="utf-8")
            ),
        },
    )

    generic_md = LOG_DIR / "v82-generic-validation.md"
    generic_json = LOG_DIR / "v82-generic-validation.json"
    generic = subprocess.run(
        [
            "python",
            str(ROOT / "00_tools" / "y2_firmware_validator.py"),
            str(builder.ZIP),
            "--out-md",
            str(generic_md),
            "--out-json",
            str(generic_json),
        ],
        capture_output=True,
        text=True,
    )
    check(
        "generic_y2_validator",
        generic.returncode == 0,
        {
            "returncode": generic.returncode,
            "stdout": generic.stdout.strip(),
            "stderr": generic.stderr.strip(),
        },
    )

    passed = sum(
        1 for item in checks.values()
        if item["passed"]
    )
    report = {
        "build": "y2-v82-settings-commit",
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
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "total": len(checks),
                "all_passed": report["all_passed"],
                "report": str(LOG_DIR / "validation.json"),
            },
            indent=2,
        )
    )
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
