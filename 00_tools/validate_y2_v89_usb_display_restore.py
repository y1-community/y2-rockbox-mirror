#!/usr/bin/env python3
"""Offline source, evidence, image and package gate for Y2 V89."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "Progress logs" / "v89-offline-validation"
APP_ROOT = (
    ROOT / "11_rockbox_android" / "rockbox-y1" / "android"
    / "src" / "org" / "rockbox"
)
SYSTEM_DIR = (
    ROOT / "build-intermediates"
    / "y2-rockbox-system-prototype-v89-usb-display-restore"
)
APK = (
    ROOT / "build-intermediates"
    / "rockbox-android-y2-v89-usb-display-restore"
    / "rockbox-y2-v89-usb-display-restore.apk"
)
EVIDENCE = (
    ROOT / "Progress logs" / "v88-persistent-display-scaling-20260729"
)
USB_MARKER = (
    EVIDENCE
    / "20220101-010831-rockbox-route-5a311348-7daa-44d2-a2ce-1edd6d80ff5e-116"
    / "app-y2_rockbox_v81_continuous_handoff_marker.txt"
)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(
    "v89_full_builder",
    ROOT / "00_tools" / "build_y2_v89_innioasis_updater_full.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, object]] = {}

    def check(name: str, passed: bool, detail: object) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    framebuffer = (APP_ROOT / "RockboxFramebuffer.java").read_text()
    marker_source = (APP_ROOT / "Y2Marker.java").read_text()
    surface_start = framebuffer.index("public void surfaceChanged")
    surface_end = framebuffer.index(
        "private void restoreCachedFrame", surface_start)
    surface_changed = framebuffer[surface_start:surface_end]

    check(
        "v89_distinct_physical_marker",
        'BUILD_VERSION = "89"' in marker_source
        and "y2_rockbox_v89_usb_display_restore_marker.txt" in marker_source
        and "y2_rockbox_v89_usb_display_restore_snapshot.txt" in marker_source,
        "build 89 marker and snapshot names",
    )
    check(
        "cached_frame_visibility_is_cross_thread_safe",
        "private volatile boolean hasCachedFrame;" in framebuffer
        and "synchronized (btm)" in framebuffer,
        "volatile state plus bitmap synchronization",
    )
    check(
        "surface_recreation_reuses_fixed_native_bitmap",
        "if (btm == null" in surface_changed
        and "btm.getWidth() != Y2_LCD_WIDTH" in surface_changed
        and "btm.getHeight() != Y2_LCD_HEIGHT" in surface_changed,
        "480x360 bitmap is replaced only when absent or dimensionally invalid",
    )
    check(
        "surface_changed_restores_cache_or_clears_initial_surface",
        "if (hasCachedFrame)" in surface_changed
        and 'restoreCachedFrame(holder, "surfaceChanged")' in surface_changed
        and 'clearSurface(holder, "surfaceChanged-no-cache")' in surface_changed
        and 'clearSurface(holder, "surfaceChanged");' not in surface_changed,
        "cached USB-return frame is not destroyed by unconditional clear",
    )
    check(
        "cached_restore_draws_full_mapped_frame",
        "private void restoreCachedFrame" in framebuffer
        and "canvas.drawColor(Color.BLACK);" in framebuffer
        and "canvas.drawBitmap(btm, srcRect, dstRect, null);" in framebuffer
        and "RockboxFramebuffer:cached frame restored reason=" in framebuffer,
        "cached bitmap redraw uses the current full destination rectangle",
    )
    check(
        "native_updates_populate_cache",
        "btm.copyPixelsFromBuffer(framebuffer);" in framebuffer
        and "hasCachedFrame = true;" in framebuffer,
        "every complete copied native frame becomes restorable",
    )

    with (EVIDENCE / "sha256-manifest.csv").open(
            newline="", encoding="utf-8-sig") as handle:
        evidence_rows = list(csv.DictReader(handle))
    check(
        "persistent_scaling_evidence_inventory_present",
        len(evidence_rows) == 1531
        and sum(int(row["Bytes"]) for row in evidence_rows) == 169230606,
        {"files": len(evidence_rows),
         "bytes": sum(int(row["Bytes"]) for row in evidence_rows)},
    )
    usb_text = USB_MARKER.read_text(errors="replace")
    frame_token = (
        "wallMs=1641050634832 elapsedMs=51327600"
        " buildVersion=81 pid=1227 externalState=mounted"
        " RockboxFramebuffer:firstUpdate mode=rect 0,48-480,316"
    )
    clear_token = (
        "wallMs=1641050634890 elapsedMs=51327658"
        " buildVersion=81 pid=1227 externalState=mounted"
        " RockboxFramebuffer:surface cleared reason=surfaceChanged"
    )
    changed_token = (
        "wallMs=1641050634910 elapsedMs=51327678"
        " buildVersion=81 pid=1227 externalState=mounted"
        " RockboxFramebuffer:surfaceChanged format=4 surface=480x360"
    )
    positions = [
        usb_text.find(frame_token),
        usb_text.find(clear_token),
        usb_text.find(changed_token),
    ]
    check(
        "usb_failure_order_bound_to_physical_evidence",
        all(position >= 0 for position in positions)
        and positions == sorted(positions),
        {"frame_clear_changed_positions": positions},
    )
    check(
        "physical_geometry_was_full_480x360",
        (
            "native=480x360 surface=480x360 bitmap=480x360 "
            "dst=0,0-480,360"
        ) in usb_text,
        "failure is lifecycle ordering, not a smaller Android destination",
    )

    with zipfile.ZipFile(APK) as archive:
        apk_bad = archive.testzip()
        dex = archive.read("classes.dex")
        resources = archive.read("lib/armeabi/libmisc.so")
    required_dex = (
        b"y2_rockbox_v89_usb_display_restore_marker.txt",
        b"RockboxFramebuffer:cached frame restored reason=",
        b"RockboxFramebuffer:cached frame restore skipped without canvas",
        b"surfaceChanged-no-cache",
        b"Normal boot",
        b"Save & Restart",
    )
    check(
        "apk_crc_and_v89_display_tokens",
        apk_bad is None and all(token in dex for token in required_dex),
        {"crc": apk_bad, "required_tokens": len(required_dex)},
    )
    with zipfile.ZipFile(
            __import__("io").BytesIO(resources)) as archive:
        sbs = archive.read(".rockbox/wps/OneBitMono.sbs")
    check(
        "onebitmono_remains_full_width",
        b"%Vi(menu,0,48,480,268,-)" in sbs
        and b"%Vi(menu,30,75,420,247,-)" not in sbs,
        {"sbs_bytes": len(sbs)},
    )

    check(
        "system_contains_exact_apk",
        (SYSTEM_DIR / "Rockbox.dump.apk").read_bytes() == APK.read_bytes(),
        sha256_bytes(APK.read_bytes()),
    )
    check(
        "system_contains_exact_resource_payload",
        (SYSTEM_DIR / "libmisc.dump.so").read_bytes() == resources,
        sha256_bytes(resources),
    )
    broker = (
        ROOT / "00_tools" / "y2_v87_boot_save_broker.sh"
    ).read_bytes()
    check(
        "physically_proven_route_broker_unchanged",
        (SYSTEM_DIR / "broker.dump.sh").read_bytes() == broker,
        sha256_bytes(broker),
    )
    e2fsck = (SYSTEM_DIR / "e2fsck.txt").read_text(errors="replace")
    check(
        "system_filesystem_clean",
        all(f"Pass {number}:" in e2fsck for number in range(1, 6))
        and "UNEXPECTED INCONSISTENCY" not in e2fsck,
        e2fsck.strip().splitlines()[-1],
    )

    expected_names = {
        *builder.FIRMWARE_FILES,
        "V89-READ-ME-FIRST.txt",
        "y2-v89-usb-display-restore-innioasis-full.json",
    }
    with zipfile.ZipFile(builder.OUT) as archive:
        names = archive.namelist()
        package_bad = archive.testzip()
        data = {name: archive.read(name) for name in names}
    check(
        "full_package_crc_unique_exact_members",
        package_bad is None
        and len(names) == len(set(names))
        and set(names) == expected_names,
        {"crc": package_bad, "members": len(names)},
    )
    selected = builder.v88.v87.v86.v85.parse_selected(
        data["MT6582_Android_scatter.txt"])
    check(
        "full_stock_scatter_selects_all_12_images",
        selected == builder.EXPECTED_SELECTED
        and all(name in data for name in selected.values()),
        sorted(selected),
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
        "only_system_changed_from_physically_accepted_v88",
        changed == ["system.img"],
        changed,
    )
    check(
        "v88_boot_and_recovery_retained_exactly",
        data["boot.img"] == base_data["boot.img"]
        and data["recovery.img"] == base_data["recovery.img"],
        {
            "boot": sha256_bytes(data["boot.img"]),
            "recovery": sha256_bytes(data["recovery.img"]),
        },
    )
    check(
        "package_system_is_exact_v89_system",
        data["system.img"] == builder.V89_SYSTEM.read_bytes(),
        sha256_bytes(data["system.img"]),
    )
    package_manifest = json.loads(
        data["y2-v89-usb-display-restore-innioasis-full.json"])
    check(
        "package_manifest_binds_repair_and_partition_delta",
        package_manifest["changed_from_v88"] == ["system.img"]
        and package_manifest["repair"][
            "retain_last_native_frame_across_surface_recreation"
        ]
        and package_manifest["repair"][
            "restore_cached_frame_after_surfaceChanged"
        ],
        package_manifest["repair"],
    )

    passed = sum(result["passed"] for result in checks.values())
    result = {
        "candidate": str(builder.OUT),
        "bytes": builder.OUT.stat().st_size,
        "sha256": builder.sha256(builder.OUT),
        "checks_passed": passed,
        "checks_total": len(checks),
        "checks": checks,
    }
    (LOG_DIR / "validation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if passed != len(checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
