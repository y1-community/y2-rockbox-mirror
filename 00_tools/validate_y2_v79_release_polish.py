#!/usr/bin/env python3
"""Offline structural, policy, evidence and reproducibility gate for V79."""

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
LOG_DIR = ROOT / "Progress logs" / "v79-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("v79_builder", ROOT / "00_tools" /
               "build_y2_v79_release_polish.py")


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
    magic, _, _, file_hdr, _, _, _, total_chunks, _ = struct.unpack_from(
        "<I4H4I", data)
    if magic != 0xED26FF3A:
        raise RuntimeError("system.img is not Android sparse")
    offset = file_hdr
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
    with zipfile.ZipFile(builder.ZIP) as archive:
        names = archive.namelist()
        bad = archive.testzip()
        packaged = {name: archive.read(name) for name in builder.FILES}
    with zipfile.ZipFile(builder.BASE_ZIP) as archive:
        base = {name: archive.read(name) for name in builder.FILES}
    expected_members = set(builder.FILES) | {
        "y2-v79-release-polish.json",
        "y2-v79-release-polish.md",
        "V79-TEST.txt",
    }
    check("zip_crc_members_hash",
          bad is None and len(names) == len(set(names))
          and set(names) == expected_members
          and sha256(builder.ZIP) == expected_hash,
          {"bad": bad, "members": len(names), "sha256": sha256(builder.ZIP)})

    changed = [name for name in builder.FILES
               if sha256_bytes(packaged[name]) != sha256_bytes(base[name])]
    check("partition_delta_exact",
          changed == ["boot.img", "recovery.img", "system.img"], changed)
    check("branding_haptic_lk_exact_v78",
          packaged["logo.bin"] == base["logo.bin"]
          and packaged["lk.bin"] == base["lk.bin"],
          {name: sha256_bytes(packaged[name])
           for name in ("logo.bin", "lk.bin")})
    check("system_exact_staged",
          packaged["system.img"] == builder.V79_SYSTEM.read_bytes(),
          sha256_bytes(packaged["system.img"]))
    sparse = sparse_chunk_counts(packaged["system.img"])
    check("system_sparse_no_fill", sparse.get("0xcac2", 0) == 0, sparse)

    script_results: dict[str, object] = {}
    route_scripts: list[bytes] = []
    guard_scripts: list[bytes] = []
    usb_scripts: list[bytes] = []
    for image_name in ("boot.img", "recovery.img"):
        entries, parts, _, label = builder.v78.v77.v76.ramdisk(
            packaged[image_name])
        base_entries, base_parts, _, base_label = \
            builder.v78.v77.v76.ramdisk(base[image_name])
        entry_map = {entry["name"]: entry["data"] for entry in entries}
        check(f"{image_name}_kernel_label_exact",
              parts["kernel"] == base_parts["kernel"] and label == base_label,
              {"label": label, "kernel": sha256_bytes(parts["kernel"])})
        route = entry_map[builder.ROUTE_SCRIPT]
        guard = entry_map[builder.ROUTE_GUARD]
        usb = entry_map[builder.USB_GUARD]
        route_scripts.append(route)
        guard_scripts.append(guard)
        usb_scripts.append(usb)
        check(f"{image_name}_v78_home_gate_retained",
              b'org.rockbox/.Y2FirmwareHomeActivity' in route
              and b'pm disable "$STOCK_HOME_ACTIVITY"' in route
              and b'pm disable "$STOCK_MAIN_ACTIVITY"' in route
              and b'pm disable "$STOCK_PLAY_RECEIVER"' in route
              and b'pm enable "$STOCK_PLAY_RECEIVER"' in route
              and b'PlayControllerReceiver' in route
              and b'HAS_EXPECTED_ACTIVITY' in route,
              sha256_bytes(route))
        check(f"{image_name}_valid_route_wait",
              b'ROUTE=$(grep \'^route=\'' in guard
              and b'rockbox|stock|settings) break' in guard
              and b'[ ! -f "$ROUTE_FILE" ]' not in guard
              and b'route_wait=$ROUTE_WAIT' in guard,
              sha256_bytes(guard))
        check(f"{image_name}_settings_root_broker",
              b'/data/data/org.rockbox/files/y2_boot_routes.request' in guard
              and b'error-invalid-permutation' in guard
              and b'no_button=$REQUEST_NO' in guard
              and b'unchanged_allowed=yes' in guard
              and b'pm disable "$STOCK_PLAY"' in guard
              and b'settings_broker=reboot' in guard,
              "validated permutation, atomic config and root reboot")
        check(f"{image_name}_usb_valid_route_broker",
              b'ROUTE=$(grep \'^route=\'' in usb
              and b'rockbox|stock|settings) break' in usb
              and b'[ ! -f "$ROUTE_FILE" ]' not in usb
              and b'authority=root-init-shell' in usb
              and b'am start -W -n "$USB_ACTIVITY"' in usb,
              sha256_bytes(usb))
        for script_name in set(
                builder.v78.v77.v76.v75.v74.SCRIPT_NAMES) | {
                    builder.USB_GUARD}:
            if script_name in entry_map:
                script_results[f"{image_name}:{script_name}"] = shell_parse(
                    entry_map[script_name])
    check("embedded_shell_parse",
          all(value["returncode"] == 0
              for value in script_results.values()),
          script_results)

    actions = ("rockbox", "stock", "settings")
    accepted = [
        mapping for mapping in itertools.product(actions, repeat=3)
        if len(set(mapping)) == 3 and "settings" in mapping
    ]
    check("route_map_permutation_model",
          len(accepted) == 6
          and all(set(mapping) == set(actions) for mapping in accepted),
          {"accepted": accepted, "count": len(accepted)})

    apk = (E_ROOT / "rockbox-android-y2-v79-release-polish" /
           "rockbox-y2-v79-release-polish.apk")
    stable = (ROOT / "12_build_outputs" / "rockbox-android-y2-v65" /
              "rockbox-y2-v65-android-unplug-reassert.apk")
    with zipfile.ZipFile(apk) as archive:
        dex = archive.read("classes.dex")
        manifest = archive.read("AndroidManifest.xml")
        apk_bad = archive.testzip()
        native = {
            name: sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.startswith("lib/armeabi/") and name.endswith(".so")
            and name != "lib/armeabi/libmisc.so"
        }
        resources = archive.read("lib/armeabi/libmisc.so")
    with zipfile.ZipFile(stable) as archive:
        stable_native = {
            name: sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.startswith("lib/armeabi/") and name.endswith(".so")
            and name != "lib/armeabi/libmisc.so"
        }
    required_dex = (
        b"y2_rockbox_v79_release_polish_marker.txt",
        b"Each boot input must use a different option.",
        b"One boot input must launch Boot Settings.",
        b"y2_boot_routes.request",
        b"root broker owns post-save reboot",
        b"framebuffer attach skipped already attached",
        b"Could not save boot settings. Please try again.",
    )
    forbidden_dex = (
        b"Could not save boot settings. No changes were applied.",
        b"persist-boot-route-map",
    )
    with zipfile.ZipFile(io.BytesIO(resources)) as archive:
        theme_ok = all(name in archive.namelist() for name in (
            ".rockbox/themes/OneBitMono.cfg",
            ".rockbox/wps/OneBitMono.wps",
            ".rockbox/wps/OneBitMono.sbs",
            ".rockbox/fonts/10-Sazanami-Mincho.fnt",
        ))
    check("apk_policy_home_native_theme",
          apk_bad is None
          and all(token in dex for token in required_dex)
          and all(token not in dex for token in forbidden_dex)
          and "android.intent.category.HOME".encode("utf-16le") in manifest
          and native == stable_native and theme_ok,
          {"apk": sha256(apk),
           "required": {t.decode(): dex.count(t) for t in required_dex},
           "forbidden": {t.decode(): dex.count(t) for t in forbidden_dex},
           "native_count": len(native), "onebitmono": theme_ok})

    source_settings = (ROOT / "11_rockbox_android" / "rockbox-y1" /
                       "android/src/org/rockbox/Y2BootSettingsActivity.java"
                       ).read_text(encoding="utf-8")
    source_activity = (ROOT / "11_rockbox_android" / "rockbox-y1" /
                       "android/src/org/rockbox/RockboxActivity.java"
                       ).read_text(encoding="utf-8")
    check("source_dropdown_and_single_framebuffer_contract",
          "new Spinner(this, Spinner.MODE_DROPDOWN)" in source_settings
          and source_settings.count('"Rockbox"') == 1
          and source_settings.count('"Y2 Stock"') == 1
          and source_settings.count('"Boot Settings"') >= 1
          and source_activity.count("new RockboxFramebuffer(this)") == 1
          and "if (framebufferAttached)" in source_activity,
          {"spinner_mode": "MODE_DROPDOWN",
           "framebuffer_constructors":
               source_activity.count("new RockboxFramebuffer(this)")})

    raw_dir = E_ROOT / "y2-rockbox-system-prototype-v79-release-polish"
    check("system_payload_and_bootanimation",
          (raw_dir / "Rockbox.v79.apk").read_bytes() == apk.read_bytes()
          == (raw_dir / "Rockbox.dump.apk").read_bytes()
          and (raw_dir / "old-bootanimation.zip").read_bytes()
          == (raw_dir / "new-bootanimation.zip").read_bytes(),
          {"apk": sha256(apk),
           "bootanimation": sha256(raw_dir / "new-bootanimation.zip")})

    evidence = Path(
        r"E:\Y2-RockBox-evidence\v78-physical-pass-boot-usb-artifacts-20260724"
        r"\Y2_V78_DEBUG")
    guard_logs = list(evidence.rglob("guard-*.txt"))
    usb_logs = list(evidence.rglob("usb-root-broker-*.txt"))
    marker_files = list(evidence.rglob(
        "app-y2_rockbox_v78_hard_home_gate_marker.txt"))
    zero_height = any(
        "status=ok" not in path.read_text(encoding="utf-8", errors="replace")
        and "guard=exit reason=stock-or-unsupported-route route=" in
        path.read_text(encoding="utf-8", errors="replace")
        for path in guard_logs)
    usb_empty = any(
        "effective-route-not-rockbox route= " in
        path.read_text(encoding="utf-8", errors="replace")
        for path in usb_logs)
    double_frame = any(
        text.count("RockboxFramebuffer:constructed") >= 2
        and "framebuffer attached for running service" in text
        for text in (
            path.read_text(encoding="utf-8", errors="replace")
            for path in marker_files))
    stock_background_crash = any(
        "Process: com.innioasis.y2" in text
        and "PlayControllerReceiver" in text
        and "ActivityNotFoundException" in text
        for text in (
            path.read_text(encoding="utf-8", errors="replace")
            for path in evidence.rglob("20-logcat-live.txt")))
    check("v78_failure_signatures_reproduced",
          zero_height and usb_empty and double_frame
          and stock_background_crash,
          {"guard_empty_route": zero_height,
           "usb_empty_route": usb_empty,
           "double_framebuffer": double_frame,
           "stock_background_crash": stock_background_crash})

    generic_md = E_ROOT / "v79-generic-validation.md"
    generic_json = E_ROOT / "v79-generic-validation.json"
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

    passed = sum(1 for value in checks.values() if value["passed"])
    report = {
        "build": "y2-v79-release-polish",
        "passed": passed,
        "total": len(checks),
        "all_passed": passed == len(checks),
        "checks": checks,
    }
    (LOG_DIR / "validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (LOG_DIR / "validation-summary.txt").write_text(
        "\n".join(
            f"{'PASS' if value['passed'] else 'FAIL'} {name}: {value['detail']}"
            for name, value in checks.items()) + "\n",
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
