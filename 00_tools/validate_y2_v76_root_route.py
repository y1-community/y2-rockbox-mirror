#!/usr/bin/env python3
"""Offline structural and policy gate for the Y2 V76 candidate."""

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
LOG_DIR = ROOT / "Progress logs" / "v76-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("v76_builder", ROOT / "00_tools" / "build_y2_v76_root_route.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sparse_chunk_counts(data: bytes) -> dict[str, int]:
    magic, _, _, file_hdr, _, _, _, total_chunks, _ = struct.unpack_from("<I4H4I", data)
    if magic != 0xED26FF3A:
        raise RuntimeError("system.img is not Android sparse")
    offset = file_hdr
    counts: dict[str, int] = {}
    for _ in range(total_chunks):
        chunk_type, _, _, total_size = struct.unpack_from("<2H2I", data, offset)
        key = hex(chunk_type)
        counts[key] = counts.get(key, 0) + 1
        offset += total_size
    return counts


def ramdisk_entries(image: bytes):
    entries, parts, _, label = builder.ramdisk(image)
    return {entry["name"]: entry["data"] for entry in entries}, parts, label


def shell_parse(data: bytes) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as handle:
        handle.write(data)
        temp = Path(handle.name)
    try:
        wsl_path = str(temp).replace("C:\\", "/mnt/c/").replace("\\", "/")
        result = subprocess.run(["wsl", "-d", "Ubuntu", "--", "sh", "-n", wsl_path],
                                capture_output=True, text=True)
        return {"returncode": result.returncode, "stderr": result.stderr.strip()}
    finally:
        temp.unlink(missing_ok=True)


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    expected_hash = builder.ZIP_SHA.read_text(encoding="ascii").split()[0]
    with zipfile.ZipFile(builder.ZIP) as archive:
        names = archive.namelist()
        bad = archive.testzip()
        packaged = {name: archive.read(name) for name in builder.FILES}
    with zipfile.ZipFile(builder.BASE_ZIP) as archive:
        base = {name: archive.read(name) for name in builder.FILES}
    expected_members = set(builder.FILES) | {
        "y2-v76-root-route.json", "y2-v76-root-route.md", "V76-TEST.txt"}
    check("zip_crc_members_hash", bad is None and len(names) == len(set(names))
          and set(names) == expected_members and sha256(builder.ZIP) == expected_hash,
          {"bad": bad, "members": len(names), "sha256": sha256(builder.ZIP)})
    changed = [name for name in builder.FILES
               if sha256_bytes(packaged[name]) != sha256_bytes(base[name])]
    check("partition_delta_exact", changed == ["boot.img", "recovery.img", "system.img"], changed)
    check("branding_and_lk_exact_v75",
          packaged["logo.bin"] == base["logo.bin"] and packaged["lk.bin"] == base["lk.bin"],
          {name: sha256_bytes(packaged[name]) for name in ("logo.bin", "lk.bin")})
    check("system_exact_staged", packaged["system.img"] == builder.V76_SYSTEM.read_bytes(),
          sha256_bytes(packaged["system.img"]))
    counts = sparse_chunk_counts(packaged["system.img"])
    check("system_sparse_no_fill", counts.get("0xcac2", 0) == 0, counts)

    script_results = {}
    for image_name in ("boot.img", "recovery.img"):
        entries, parts, label = ramdisk_entries(packaged[image_name])
        base_entries, base_parts, base_label = ramdisk_entries(base[image_name])
        check(f"{image_name}_kernel_label_exact",
              parts["kernel"] == base_parts["kernel"] and label == base_label,
              {"label": label, "kernel": sha256_bytes(parts["kernel"])})
        route = entries[builder.ROUTE_SCRIPT]
        check(f"{image_name}_root_bootstrap_contract",
              b'org.rockbox/.Y2FirmwareHomeActivity' in route
              and b'am start -W -n "$BOOTSTRAP_COMPONENT"' in route
              and b'am broadcast -a "$ACTION"' not in route
              and b'root_bootstrap_validated=yes' in route
              and b'effective-route-$BOOT_ID.txt' in route
              and b'if [ "$ROUTE" != "stock" ]; then' in route,
              {"activity_starts": route.count(b'am start -W'),
               "broadcast_starts": route.count(b'am broadcast -a')})
        usb = entries.get(builder.USB_GUARD, b"")
        check(f"{image_name}_root_usb_broker",
              b'effective-route-$BOOT_ID.txt' in usb
              and b'ROUTE" != "rockbox"' in usb
              and b'am start -W -n "$USB_ACTIVITY"' in usb
              and b'Permission Denial' in usb
              and b'while true; do' in usb,
              {"present": bool(usb), "sha256": sha256_bytes(usb) if usb else ""})
        for script_name in set(builder.v75.v74.SCRIPT_NAMES) | {builder.USB_GUARD}:
            if script_name in entries:
                script_results[f"{image_name}:{script_name}"] = shell_parse(entries[script_name])
        if image_name == "boot.img":
            init = entries["init.rc"]
            factory = entries["factory_init.rc"]
            check("boot_routes_and_usb_services",
                  b'on post-fs-data\n    start y2v36stockroute' in init
                  and b'setprop y2.firmware.route stock' in init
                  and b'setprop y2.firmware.route settings' in factory
                  and b'service y2v39usbguard ' in init
                  and b'service y2v39usbguard ' in factory
                  and b'on property:sys.boot_completed=1\n    start y2v39usbguard' in init
                  and b'on property:sys.boot_completed=1\n    start y2v39usbguard' in factory,
                  "physical routes immutable; root USB broker in normal and factory init")
        else:
            init = entries["init.rc"]
            check("recovery_route_and_usb_service",
                  b'setprop y2.firmware.route rockbox' in init
                  and b'service y2v39usbguard ' in init
                  and b'start y2v39usbguard' in init,
                  "Volume Down physical path and root USB broker retained")
    check("embedded_shell_parse",
          all(value["returncode"] == 0 for value in script_results.values()), script_results)

    apk = E_ROOT / "rockbox-android-y2-v76-root-route" / "rockbox-y2-v76-root-route.apk"
    stable = ROOT / "12_build_outputs" / "rockbox-android-y2-v65" / "rockbox-y2-v65-android-unplug-reassert.apk"
    with zipfile.ZipFile(apk) as archive:
        dex = archive.read("classes.dex")
        manifest = archive.read("AndroidManifest.xml")
        apk_bad = archive.testzip()
        native = {name: sha256_bytes(archive.read(name)) for name in archive.namelist()
                  if name.startswith("lib/armeabi/") and name.endswith(".so")
                  and name != "lib/armeabi/libmisc.so"}
        resources = archive.read("lib/armeabi/libmisc.so")
    with zipfile.ZipFile(stable) as archive:
        stable_native = {name: sha256_bytes(archive.read(name)) for name in archive.namelist()
                         if name.startswith("lib/armeabi/") and name.endswith(".so")
                         and name != "lib/armeabi/libmisc.so"}
    tokens = (b"FirmwareHome:onCreate root-bootstrap",
              b"FirmwareHome:started root-owned route=",
              b"ROUTE_SHIELD_USB_DISCONNECT_RECOVERY",
              b"recover unexported USB disconnect",
              b"rootBroker=authoritative",
              b"sys.boot_completed",
              b"y2_rockbox_v76_root_route_marker.txt")
    with zipfile.ZipFile(io.BytesIO(resources)) as archive:
        theme_ok = all(name in archive.namelist() for name in (
            ".rockbox/themes/OneBitMono.cfg", ".rockbox/wps/OneBitMono.wps",
            ".rockbox/wps/OneBitMono.sbs", ".rockbox/fonts/10-Sazanami-Mincho.fnt"))
    check("apk_policy_native_theme",
          apk_bad is None and all(token in dex for token in tokens)
          and native == stable_native and theme_ok
          and "android.intent.category.HOME".encode("utf-16le") not in manifest,
          {"apk": sha256(apk), "tokens": {t.decode(): dex.count(t) for t in tokens},
           "native_count": len(native), "onebitmono": theme_ok})

    raw_dir = E_ROOT / "y2-rockbox-system-prototype-v76-root-route"
    staged_apk = raw_dir / "Rockbox.v76.apk"
    dumped_apk = raw_dir / "Rockbox.dump.apk"
    boot_old = raw_dir / "old-bootanimation.zip"
    boot_new = raw_dir / "new-bootanimation.zip"
    check("system_payload_and_bootanimation",
          staged_apk.read_bytes() == apk.read_bytes() == dumped_apk.read_bytes()
          and boot_old.read_bytes() == boot_new.read_bytes()
          and sha256(boot_new) == "BC7F4ADC94C8E08422F5862C020D6CC630BC6CACB273C4BF9FEE7DD7DFB9D69B",
          {"apk": sha256(apk), "bootanimation": sha256(boot_new)})

    generic_md = E_ROOT / "v76-generic-validation.md"
    generic_json = E_ROOT / "v76-generic-validation.json"
    generic = subprocess.run([
        "python", str(ROOT / "00_tools" / "y2_firmware_validator.py"), str(builder.ZIP),
        "--out-md", str(generic_md), "--out-json", str(generic_json)],
        capture_output=True, text=True)
    check("generic_y2_validator", generic.returncode == 0,
          {"returncode": generic.returncode, "stdout": generic.stdout.strip(),
           "stderr": generic.stderr.strip()})

    passed = sum(1 for value in checks.values() if value["passed"])
    report = {"build": "y2-v76-root-route", "passed": passed,
              "total": len(checks), "all_passed": passed == len(checks), "checks": checks}
    (LOG_DIR / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (LOG_DIR / "validation-summary.txt").write_text(
        "\n".join(f"{'PASS' if value['passed'] else 'FAIL'} {name}: {value['detail']}"
                  for name, value in checks.items()) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "total": len(checks),
                      "all_passed": report["all_passed"],
                      "report": str(LOG_DIR / "validation.json")}, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
