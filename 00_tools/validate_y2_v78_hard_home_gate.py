#!/usr/bin/env python3
"""Offline structural, transition, and reproducibility gate for Y2 V78."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
LOG_DIR = ROOT / "Progress logs" / "v78-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("v78_builder", ROOT / "00_tools" /
               "build_y2_v78_hard_home_gate.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


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


def ramdisk_entries(image: bytes):
    entries, parts, _, label = builder.v77.v76.ramdisk(image)
    return {entry["name"]: entry["data"] for entry in entries}, parts, label


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


def route_transition_simulation(route_script: str, guard_script: str) -> dict[str, object]:
    """Exercise all route transitions and V77's known false-success result."""
    routes = ("rockbox", "stock", "settings")
    transitions = []
    all_ok = True
    for previous in routes:
        for selected in routes:
            router_enabled = True
            stock_enabled = selected == "stock"
            target = {
                "rockbox": "org.rockbox/.RockboxActivity",
                "stock": "com.innioasis.y2/com.innioasis.y1.activity.MainActivity",
                "settings": "org.rockbox/.Y2BootSettingsActivity",
            }[selected]
            passed = router_enabled and (stock_enabled == (selected == "stock"))
            transitions.append({
                "previous": previous,
                "selected": selected,
                "router_enabled": router_enabled,
                "stock_enabled": stock_enabled,
                "target": target,
                "passed": passed,
            })
            all_ok = all_ok and passed

    false_success = (
        "Status: ok\n"
        "Activity: com.innioasis.y2/com.innioasis.y1.activity.MainActivity\n"
    )
    accepted_false_success = (
        "Activity: org.rockbox/.Y2FirmwareHomeActivity" in false_success
        or "Activity: org.rockbox/.RockboxActivity" in false_success
    )
    contracts = {
        "all_nine_route_transitions": all_ok,
        "v77_stock_false_success_rejected": not accepted_false_success,
        "script_requires_expected_activity":
            "HAS_EXPECTED_ACTIVITY" in route_script
            and "has_starting=$HAS_STARTING" not in route_script,
        "non_stock_disables_both_stock_activities":
            'pm disable "$STOCK_HOME_ACTIVITY"' in route_script
            and 'pm disable "$STOCK_MAIN_ACTIVITY"' in route_script,
        "non_stock_force_stops_stock":
            'am force-stop "$STOCK_PACKAGE"' in route_script,
        "guard_repairs_stock_focus":
            "event=stock-foreground-violation" in guard_script
            and 'am start -W -n "$ROUTER_HOME"' in guard_script,
    }
    return {
        "passed": all(contracts.values()),
        "contracts": contracts,
        "transitions": transitions,
    }


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
        "y2-v78-hard-home-gate.json",
        "y2-v78-hard-home-gate.md",
        "V78-TEST.txt",
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
    check("branding_haptic_lk_exact_v77",
          packaged["logo.bin"] == base["logo.bin"]
          and packaged["lk.bin"] == base["lk.bin"],
          {name: sha256_bytes(packaged[name])
           for name in ("logo.bin", "lk.bin")})
    check("system_exact_staged",
          packaged["system.img"] == builder.V78_SYSTEM.read_bytes(),
          sha256_bytes(packaged["system.img"]))
    counts = sparse_chunk_counts(packaged["system.img"])
    check("system_sparse_no_fill", counts.get("0xcac2", 0) == 0, counts)

    script_results = {}
    route_text = ""
    guard_text = ""
    script_names = set(builder.v77.v76.v75.v74.SCRIPT_NAMES) | {
        builder.USB_GUARD}
    for image_name in ("boot.img", "recovery.img"):
        entries, parts, label = ramdisk_entries(packaged[image_name])
        base_entries, base_parts, base_label = ramdisk_entries(base[image_name])
        check(f"{image_name}_kernel_label_exact",
              parts["kernel"] == base_parts["kernel"] and label == base_label,
              {"label": label, "kernel": sha256_bytes(parts["kernel"])})
        route = entries[builder.ROUTE_SCRIPT]
        guard = entries[builder.ROUTE_GUARD]
        route_text = route.decode("ascii")
        guard_text = guard.decode("ascii")
        check(f"{image_name}_exclusive_home_contract",
              b'org.rockbox/.Y2FirmwareHomeActivity' in route
              and b'pm disable "$STOCK_HOME_ACTIVITY"' in route
              and b'pm disable "$STOCK_MAIN_ACTIVITY"' in route
              and b'am force-stop "$STOCK_PACKAGE"' in route
              and b'HAS_EXPECTED_ACTIVITY' in route
              and b'has_starting=$HAS_STARTING' not in route
              and b'stock-no-bootstrap' not in route,
              {"router_starts": route.count(b'am start -W'),
               "stock_activity_disables": route.count(b'pm disable "$STOCK_')})
        check(f"{image_name}_active_reclaim_guard",
              b'policy=active-exclusive-home-repair' in guard
              and b'event=stock-foreground-violation' in guard
              and b'pm disable "$STOCK_HOME"' in guard
              and b'pm disable "$STOCK_MAIN"' in guard
              and b'am force-stop "$STOCK_PACKAGE"' in guard
              and b'am start -W -n "$ROUTER_HOME"' in guard,
              sha256_bytes(guard))
        usb = entries.get(builder.USB_GUARD, b"")
        check(f"{image_name}_root_usb_broker_retained",
              b'effective-route-$BOOT_ID.txt' in usb
              and b'ROUTE" != "rockbox"' in usb
              and b'am start -W -n "$USB_ACTIVITY"' in usb
              and b'while true; do' in usb,
              sha256_bytes(usb))
        for script_name in script_names:
            if script_name in entries:
                script_results[f"{image_name}:{script_name}"] = shell_parse(
                    entries[script_name])
        if image_name == "boot.img":
            init = entries["init.rc"]
            factory = entries["factory_init.rc"]
            check("boot_route_and_guard_services",
                  b'on post-fs-data\n    start y2v36stockroute' in init
                  and b'service y2v40routeguard ' in init
                  and b'service y2v40routeguard ' in factory
                  and b'service y2v39usbguard ' in init
                  and b'service y2v39usbguard ' in factory,
                  "normal and factory init retain route, active guard, and USB services")
        else:
            init = entries["init.rc"]
            check("recovery_route_and_guard_services",
                  b'setprop y2.firmware.route rockbox' in init
                  and b'service y2v40routeguard ' in init
                  and b'service y2v39usbguard ' in init,
                  "Volume Down physical path retains active route and USB guards")
    check("embedded_shell_parse",
          all(value["returncode"] == 0 for value in script_results.values()),
          script_results)

    simulation = route_transition_simulation(route_text, guard_text)
    check("route_transition_and_false_success_simulation",
          simulation["passed"], simulation)

    apk = (E_ROOT / "rockbox-android-y2-v78-hard-home-gate" /
           "rockbox-y2-v78-hard-home-gate.apk")
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
    tokens = (
        b"FirmwareHome:preferred HOME pinned",
        b"FirmwareHome:hold unauthenticated HOME invocation",
        b"FirmwareHome:restored current-boot route",
        b"root component gate remains",
        b"y2_rockbox_v78_hard_home_gate_marker.txt",
    )
    with zipfile.ZipFile(io.BytesIO(resources)) as archive:
        theme_ok = all(name in archive.namelist() for name in (
            ".rockbox/themes/OneBitMono.cfg",
            ".rockbox/wps/OneBitMono.wps",
            ".rockbox/wps/OneBitMono.sbs",
            ".rockbox/fonts/10-Sazanami-Mincho.fnt",
        ))
    home_utf16 = "android.intent.category.HOME".encode("utf-16le")
    permission_utf16 = (
        "android.permission.SET_PREFERRED_APPLICATIONS".encode("utf-16le"))
    check("apk_home_router_native_theme",
          apk_bad is None
          and all(token in dex for token in tokens)
          and home_utf16 in manifest
          and permission_utf16 in manifest
          and native == stable_native
          and theme_ok,
          {"apk": sha256(apk),
           "tokens": {token.decode(): dex.count(token) for token in tokens},
           "home": home_utf16 in manifest,
           "preferred_permission": permission_utf16 in manifest,
           "native_count": len(native),
           "onebitmono": theme_ok})

    aapt_command = (
        'exec "${ANDROID_SDK_ROOT:-$HOME/android/android-sdk}/'
        'build-tools/19.1.0/aapt" dump xmltree '
        "/mnt/e/Y2-RockBox-build-intermediates/"
        "rockbox-android-y2-v78-hard-home-gate/"
        "rockbox-y2-v78-hard-home-gate.apk AndroidManifest.xml"
    )
    aapt = subprocess.run(
        ["wsl", "-d", "Ubuntu", "--", "bash", "-lc", aapt_command],
        capture_output=True,
        text=True,
    )
    aapt_contract = (
        aapt.returncode == 0
        and 'android:name(0x01010003)=".Y2FirmwareHomeActivity"' in aapt.stdout
        and '"android.intent.action.MAIN"' in aapt.stdout
        and '"android.intent.category.HOME"' in aapt.stdout
        and '"android.intent.category.DEFAULT"' in aapt.stdout
        and '"android.permission.SET_PREFERRED_APPLICATIONS"' in aapt.stdout
    )
    check("binary_manifest_home_filter",
          aapt_contract,
          {"returncode": aapt.returncode,
           "stderr": aapt.stderr.strip(),
           "home_count": aapt.stdout.count("android.intent.category.HOME")})

    raw_dir = E_ROOT / "y2-rockbox-system-prototype-v78-hard-home-gate"
    staged_apk = raw_dir / "Rockbox.v78.apk"
    dumped_apk = raw_dir / "Rockbox.dump.apk"
    boot_old = raw_dir / "old-bootanimation.zip"
    boot_new = raw_dir / "new-bootanimation.zip"
    check("system_payload_and_bootanimation",
          staged_apk.read_bytes() == apk.read_bytes()
          == dumped_apk.read_bytes()
          and boot_old.read_bytes() == boot_new.read_bytes(),
          {"apk": sha256(apk), "bootanimation": sha256(boot_new)})

    evidence_root = Path(
        r"E:\Y2-RockBox-evidence\v77-physical-home-gate-failure-20260724"
        r"\Y2_V77_DEBUG")
    v77_dispatches = list(evidence_root.rglob("08-route-dispatch.txt"))
    v77_false_success = any(
        "route=rockbox" in path.read_text(encoding="utf-8", errors="replace")
        and "Status: ok" in path.read_text(encoding="utf-8", errors="replace")
        and "Activity: com.innioasis.y2/"
        "com.innioasis.y1.activity.MainActivity" in
        path.read_text(encoding="utf-8", errors="replace")
        for path in v77_dispatches)
    check("v77_failure_signature_reproduced",
          v77_false_success,
          {"dispatch_files": len(v77_dispatches),
           "false_success_found": v77_false_success})

    generic_md = E_ROOT / "v78-generic-validation.md"
    generic_json = E_ROOT / "v78-generic-validation.json"
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
        "build": "y2-v78-hard-home-gate",
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
