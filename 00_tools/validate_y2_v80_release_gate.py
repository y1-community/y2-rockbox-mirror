#!/usr/bin/env python3
"""Offline structural, boot-policy, branding and reproducibility gate for V80."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import itertools
import json
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
LOG_DIR = ROOT / "Progress logs" / "v80-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("v80_builder", ROOT / "00_tools" /
               "build_y2_v80_release_gate.py")
branding = load("v80_branding", ROOT / "00_tools" /
                "build_y2_v80_branding.py")


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
        wsl_path = str(temp).replace("C:\\", "/mnt/c/").replace("\\", "/")
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "sh", "-n", wsl_path],
            capture_output=True, text=True)
        return {"returncode": result.returncode,
                "stderr": result.stderr.strip()}
    finally:
        temp.unlink(missing_ok=True)


def sparse_chunk_counts(data: bytes) -> dict[str, int]:
    magic, _, _, file_header, _, _, _, total_chunks, _ = struct.unpack_from(
        "<I4H4I", data)
    if magic != 0xED26FF3A:
        raise RuntimeError("system.img is not Android sparse")
    offset = file_header
    counts: dict[str, int] = {}
    for _ in range(total_chunks):
        chunk_type, _, _, total_size = struct.unpack_from(
            "<2H2I", data, offset)
        key = hex(chunk_type)
        counts[key] = counts.get(key, 0) + 1
        offset += total_size
    return counts


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    expected_hash = builder.ZIP_SHA.read_text(
        encoding="ascii").split()[0]
    expected_members = set(builder.FILES) | {
        "y2-v80-release-gate.json",
        "y2-v80-release-gate.md",
        "V80-TEST.txt",
    }
    with zipfile.ZipFile(builder.ZIP) as archive:
        names = archive.namelist()
        bad = archive.testzip()
        packaged = {name: archive.read(name) for name in builder.FILES}
    with zipfile.ZipFile(builder.BASE_ZIP) as archive:
        base = {name: archive.read(name) for name in builder.FILES}
    check("zip_crc_members_hash",
          bad is None and len(names) == len(set(names))
          and set(names) == expected_members
          and sha256(builder.ZIP) == expected_hash,
          {"bad": bad, "members": len(names), "sha256": sha256(builder.ZIP)})

    changed = [name for name in builder.FILES
               if packaged[name] != base[name]]
    check("partition_delta_exact",
          changed == ["boot.img", "recovery.img", "logo.bin", "system.img"],
          changed)
    check("lk_haptic_key_timing_exact_v79",
          packaged["lk.bin"] == base["lk.bin"],
          sha256_bytes(packaged["lk.bin"]))
    check("system_and_logo_exact_staged",
          packaged["system.img"] == builder.V80_SYSTEM.read_bytes()
          and packaged["logo.bin"] == builder.V80_LOGO.read_bytes(),
          {"system": sha256_bytes(packaged["system.img"]),
           "logo": sha256_bytes(packaged["logo.bin"])})
    sparse = sparse_chunk_counts(packaged["system.img"])
    check("system_sparse_no_fill", sparse.get("0xcac2", 0) == 0, sparse)

    script_results: dict[str, object] = {}
    route_hashes: list[str] = []
    for image_name in ("boot.img", "recovery.img"):
        entries, parts, _, label = builder.v79.v78.v77.v76.ramdisk(
            packaged[image_name])
        base_entries, base_parts, _, base_label = \
            builder.v79.v78.v77.v76.ramdisk(base[image_name])
        entry_map = {entry["name"]: entry["data"] for entry in entries}
        check(f"{image_name}_kernel_label_exact",
              parts["kernel"] == base_parts["kernel"] and label == base_label,
              {"label": label, "kernel": sha256_bytes(parts["kernel"])})
        route = entry_map[builder.ROUTE_SCRIPT]
        guard = entry_map[builder.ROUTE_GUARD]
        usb = entry_map[builder.USB_GUARD]
        route_hashes.append(sha256_bytes(route))
        check(f"{image_name}_true_readiness_and_atomic_route",
              b"MAX_READINESS_ATTEMPTS=240" in route
              and b'BOOT_COMPLETE=1' in route
              and b'PRIMARY_WRITABLE=1' in route
              and b'ROUTE_STORAGE_READY=0' in route
              and b'mv "$EFFECTIVE_ROUTE_TMP" "$EFFECTIVE_ROUTE_FILE"' in route
              and b'pm disable "$STOCK_HOME_ACTIVITY"' in route
              and b'pm disable "$STOCK_MAIN_ACTIVITY"' in route,
              sha256_bytes(route))
        check(f"{image_name}_pipeline_free_critical_parsers",
              b"read_kv()" in route and b"read_kv()" in guard
              and b"read_kv()" in usb
              and b"grep '^route='" not in route
              and b"grep '^route='" not in guard
              and b"grep '^route='" not in usb
              and b"head -n 1 | cut" not in route
              and b"head -n 1 | cut" not in guard
              and b"head -n 1 | cut" not in usb,
              "critical route/config reads use shell built-ins")
        verified = guard.find(b"settings_broker=verified")
        acknowledged = guard.find(b"settings_broker=acknowledged")
        rebooted = guard.find(b"settings_broker=reboot")
        check(f"{image_name}_verified_save_ack_reboot_order",
              verified >= 0 and verified < acknowledged < rebooted
              and b"error-verify-failed" in guard
              and b'chmod 0600 "$ROUTE_MAP_TMP"' in guard
              and b'chmod 0644 "$RESPONSE_TMP"' in guard
              and b"sleep 2" in guard,
              {"verified": verified, "acknowledged": acknowledged,
               "reboot": rebooted})
        for script_name in set(
                builder.v79.v78.v77.v76.v75.v74.SCRIPT_NAMES) | {
                    builder.USB_GUARD}:
            if script_name in entry_map:
                script_results[f"{image_name}:{script_name}"] = shell_parse(
                    entry_map[script_name])
    check("boot_recovery_route_script_identical",
          len(set(route_hashes)) == 1, route_hashes)
    check("embedded_shell_parse",
          all(item["returncode"] == 0 for item in script_results.values()),
          script_results)

    _, base_logo_images = branding.unpack_logo(base["logo.bin"])
    _, new_logo_images = branding.unpack_logo(packaged["logo.bin"])
    preserved = all(new_logo_images[index] == base_logo_images[index]
                    for index in range(1, 38))
    check("logo_slots_and_charging_assets",
          new_logo_images[0] == new_logo_images[38]
          and new_logo_images[0] != base_logo_images[0] and preserved,
          {"slot0": sha256_bytes(new_logo_images[0]),
           "slot38": sha256_bytes(new_logo_images[38]),
           "preserved_slots_1_to_37": preserved})

    apk = (E_ROOT / "rockbox-android-y2-v80-release-gate" /
           "rockbox-y2-v80-release-gate.apk")
    stable = (ROOT / "12_build_outputs" / "rockbox-android-y2-v65" /
              "rockbox-y2-v65-android-unplug-reassert.apk")
    with zipfile.ZipFile(apk) as archive:
        apk_bad = archive.testzip()
        dex = archive.read("classes.dex")
        manifest = archive.read("AndroidManifest.xml")
        resources = archive.read("lib/armeabi/libmisc.so")
        native = {
            name: sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.startswith("lib/armeabi/") and name.endswith(".so")
            and name != "lib/armeabi/libmisc.so"
        }
    with zipfile.ZipFile(stable) as archive:
        stable_native = {
            name: sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.startswith("lib/armeabi/") and name.endswith(".so")
            and name != "lib/armeabi/libmisc.so"
        }
    required_dex = (
        b"y2_rockbox_v80_release_gate_marker.txt",
        b"Saving...",
        b"Saved - restarting...",
        b"Save timed out. Nothing was changed; please try again.",
        b"root verified save; waiting for root reboot",
        b"Each boot input must use a different option.",
        b"One boot input must launch Boot Settings.",
        b"framebuffer attach skipped already attached",
    )
    with zipfile.ZipFile(io.BytesIO(resources)) as archive:
        sbs = archive.read(".rockbox/wps/OneBitMono.sbs")
        theme_ok = (
            b"%Vi(menu,0,48,480,268,-)" in sbs
            and b"%Vi(menu,30,75,420,247,-)" not in sbs
        )
    check("apk_home_save_theme_native_contract",
          apk_bad is None
          and all(token in dex for token in required_dex)
          and "android.intent.category.HOME".encode("utf-16le") in manifest
          and native == stable_native and theme_ok,
          {"apk": sha256(apk), "theme": theme_ok,
           "native_count": len(native),
           "required": {token.decode(): dex.count(token)
                        for token in required_dex}})

    raw_dir = E_ROOT / "y2-rockbox-system-prototype-v80-release-gate"
    bootanimation = raw_dir / "bootanimation.dump.zip"
    expected_animation = builder.V80_BRANDING / "bootanimation.zip"
    with zipfile.ZipFile(bootanimation) as archive:
        animation_bad = archive.testzip()
        desc = archive.read("desc.txt")
        part0 = [name for name in archive.namelist()
                 if name.startswith("part0/") and name.endswith(".jpg")]
        part1 = [name for name in archive.namelist()
                 if name.startswith("part1/") and name.endswith(".jpg")]
        stored = all(info.compress_type == zipfile.ZIP_STORED
                     for info in archive.infolist())
    check("system_apk_and_spyce_animation_exact",
          (raw_dir / "Rockbox.v80.apk").read_bytes() == apk.read_bytes()
          == (raw_dir / "Rockbox.dump.apk").read_bytes()
          and bootanimation.read_bytes() == expected_animation.read_bytes()
          and animation_bad is None and desc.startswith(b"480 360 20")
          and len(part0) == 39 and len(part1) == 1 and stored,
          {"apk": sha256(apk), "bootanimation": sha256(bootanimation),
           "desc": desc.decode().strip().splitlines(),
           "part0": len(part0), "part1": len(part1), "stored": stored})

    actions = ("rockbox", "stock", "settings")
    accepted = [
        mapping for mapping in itertools.product(actions, repeat=3)
        if len(set(mapping)) == 3 and "settings" in mapping
    ]
    check("route_map_permutation_model",
          len(accepted) == 6
          and all(set(mapping) == set(actions) for mapping in accepted),
          {"accepted": accepted, "count": len(accepted)})

    generic_md = E_ROOT / "v80-generic-validation.md"
    generic_json = E_ROOT / "v80-generic-validation.json"
    generic = subprocess.run([
        "python", str(ROOT / "00_tools" / "y2_firmware_validator.py"),
        str(builder.ZIP),
        "--out-md", str(generic_md),
        "--out-json", str(generic_json),
    ], capture_output=True, text=True)
    check("generic_y2_validator", generic.returncode == 0,
          {"returncode": generic.returncode,
           "stdout": generic.stdout.strip(),
           "stderr": generic.stderr.strip()})

    passed = sum(1 for item in checks.values() if item["passed"])
    report = {
        "build": "y2-v80-release-gate",
        "passed": passed,
        "total": len(checks),
        "all_passed": passed == len(checks),
        "checks": checks,
    }
    (LOG_DIR / "validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (LOG_DIR / "validation-summary.txt").write_text(
        "\n".join(
            f"{'PASS' if item['passed'] else 'FAIL'} {name}: {item['detail']}"
            for name, item in checks.items()) + "\n",
        encoding="utf-8")
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
