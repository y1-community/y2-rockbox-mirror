#!/usr/bin/env python3
"""Offline structural and policy gate for the Y2 V75 candidate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
LOG_DIR = ROOT / "Progress logs" / "v75-offline-validation"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("v75_builder", ROOT / "00_tools" / "build_y2_v75_route_handoff.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sparse_chunk_counts(data: bytes) -> dict[str, int]:
    magic, _, _, file_hdr, chunk_hdr, _, _, total_chunks, _ = struct.unpack_from("<I4H4I", data)
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


def ramdisk_entries(image: bytes) -> tuple[dict[str, bytes], dict[str, object], str]:
    entries, parts, _, label = builder.ramdisk(image)
    return {entry["name"]: entry["data"] for entry in entries}, parts, label


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
        "y2-v75-route-handoff.json", "y2-v75-route-handoff.md", "V75-TEST.txt"}
    check("zip_crc_members_hash", bad is None and len(names) == len(set(names))
          and set(names) == expected_members and sha256(builder.ZIP) == expected_hash,
          {"bad": bad, "members": len(names), "sha256": sha256(builder.ZIP)})
    changed = [name for name in builder.FILES
               if sha256_bytes(packaged[name]) != sha256_bytes(base[name])]
    check("partition_delta_exact", changed == ["boot.img", "recovery.img", "system.img"], changed)
    check("logo_exact_v74", packaged["logo.bin"] == base["logo.bin"], sha256_bytes(packaged["logo.bin"]))
    check("system_exact_staged", packaged["system.img"] == builder.V75_SYSTEM.read_bytes(),
          sha256_bytes(packaged["system.img"]))
    counts = sparse_chunk_counts(packaged["system.img"])
    check("system_sparse_no_fill", counts.get("0xcac2", 0) == 0, counts)

    script_parse = {}
    for image_name in ("boot.img", "recovery.img"):
        entries, parts, label = ramdisk_entries(packaged[image_name])
        base_entries, base_parts, base_label = ramdisk_entries(base[image_name])
        check(f"{image_name}_kernel_label_exact",
              parts["kernel"] == base_parts["kernel"] and label == base_label,
              {"label": label, "kernel": sha256_bytes(parts["kernel"])})
        route = entries[builder.ROUTE_SCRIPT]
        check(f"{image_name}_effective_route_contract",
              b'setprop y2.firmware.route "$ROUTE"' not in route
              and route.count(b'--es physical_route "$PHYSICAL_ROUTE" --es route "$ROUTE"') == 2
              and b'physical_route_property_immutable=yes' in route
              and b'effective-route-$BOOT_ID.txt' in route,
              {"physical_extra_count": route.count(b'--es physical_route'),
               "forbidden_setprop": route.count(b'setprop y2.firmware.route "$ROUTE"')})
        for script_name in builder.v74.SCRIPT_NAMES:
            if script_name not in entries:
                continue
            with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as handle:
                handle.write(entries[script_name])
                temp = Path(handle.name)
            result = subprocess.run(["wsl", "-d", "Ubuntu", "--", "sh", "-n",
                                     str(temp).replace("C:\\", "/mnt/c/").replace("\\", "/")],
                                    capture_output=True, text=True)
            temp.unlink(missing_ok=True)
            script_parse[f"{image_name}:{script_name}"] = {
                "returncode": result.returncode, "stderr": result.stderr.strip()}
        if image_name == "boot.img":
            init = entries["init.rc"]
            factory = entries["factory_init.rc"]
            check("boot_routes_early_and_immutable",
                  b'on property:sys.boot_completed=1\n    start y2v36stockroute' not in init
                  and b'on post-fs-data\n    start y2v36stockroute' in init
                  and b'setprop y2.firmware.route stock' in init
                  and b'setprop y2.firmware.route settings' in factory,
                  "no-button starts at post-fs-data; stock/settings physical properties retained")
        else:
            check("recovery_physical_route_immutable",
                  b'setprop y2.firmware.route rockbox' in entries["init.rc"],
                  "Volume Down physical route remains rockbox")
    check("embedded_shell_parse", all(v["returncode"] == 0 for v in script_parse.values()), script_parse)

    apk = E_ROOT / "rockbox-android-y2-v75-route-handoff" / "rockbox-y2-v75-route-handoff.apk"
    stable = ROOT / "12_build_outputs" / "rockbox-android-y2-v65" / "rockbox-y2-v65-android-unplug-reassert.apk"
    with zipfile.ZipFile(apk) as archive:
        dex = archive.read("classes.dex")
        manifest = archive.read("AndroidManifest.xml")
        apk_bad = archive.testzip()
        native = {n: sha256_bytes(archive.read(n)) for n in archive.namelist()
                  if n.startswith("lib/armeabi/") and n.endswith(".so") and n != "lib/armeabi/libmisc.so"}
        resources = archive.read("lib/armeabi/libmisc.so")
    with zipfile.ZipFile(stable) as archive:
        stable_native = {n: sha256_bytes(archive.read(n)) for n in archive.namelist()
                         if n.startswith("lib/armeabi/") and n.endswith(".so") and n != "lib/armeabi/libmisc.so"}
    tokens = (b"physical_route", b"ROUTE_SHIELD_ACTIVITY_READY",
              b"ROUTE_SHIELD_SETTINGS_READY", b"route-coordinator-owns-usb-handoff",
              b"Restoring storage", b"y2_rockbox_v75_route_handoff_marker.txt")
    with zipfile.ZipFile(__import__("io").BytesIO(resources)) as archive:
        theme_ok = all(n in archive.namelist() for n in (
            ".rockbox/themes/OneBitMono.cfg", ".rockbox/wps/OneBitMono.wps",
            ".rockbox/wps/OneBitMono.sbs", ".rockbox/fonts/10-Sazanami-Mincho.fnt"))
    check("apk_policy_native_theme", apk_bad is None and all(t in dex for t in tokens)
          and native == stable_native and theme_ok
          and "android.intent.category.HOME".encode("utf-16le") not in manifest,
          {"apk": sha256(apk), "tokens": {t.decode(): dex.count(t) for t in tokens},
           "native_count": len(native), "onebitmono": theme_ok})

    raw_dir = E_ROOT / "y2-rockbox-system-prototype-v75-route-handoff"
    staged_apk = raw_dir / "Rockbox.v75.apk"
    dumped_apk = raw_dir / "Rockbox.dump.apk"
    boot_old = raw_dir / "old-bootanimation.zip"
    boot_new = raw_dir / "new-bootanimation.zip"
    check("system_payload_and_bootanimation",
          staged_apk.read_bytes() == apk.read_bytes() == dumped_apk.read_bytes()
          and boot_old.read_bytes() == boot_new.read_bytes()
          and sha256(boot_new) == "BC7F4ADC94C8E08422F5862C020D6CC630BC6CACB273C4BF9FEE7DD7DFB9D69B",
          {"apk": sha256(apk), "bootanimation": sha256(boot_new)})

    generic_md = E_ROOT / "v75-generic-validation.md"
    generic_json = E_ROOT / "v75-generic-validation.json"
    generic = subprocess.run([
        "python", str(ROOT / "00_tools" / "y2_firmware_validator.py"), str(builder.ZIP),
        "--out-md", str(generic_md), "--out-json", str(generic_json)],
        capture_output=True, text=True)
    check("generic_y2_validator", generic.returncode == 0,
          {"returncode": generic.returncode, "stdout": generic.stdout.strip(),
           "stderr": generic.stderr.strip()})

    passed = sum(1 for value in checks.values() if value["passed"])
    report = {"build": "y2-v75-route-handoff", "passed": passed,
              "total": len(checks), "all_passed": passed == len(checks), "checks": checks}
    (LOG_DIR / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (LOG_DIR / "validation-summary.txt").write_text(
        "\n".join(f"{'PASS' if v['passed'] else 'FAIL'} {k}: {v['detail']}"
                  for k, v in checks.items()) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "total": len(checks),
                      "all_passed": report["all_passed"], "report": str(LOG_DIR / "validation.json")}, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
