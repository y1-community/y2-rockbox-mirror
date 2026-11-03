#!/usr/bin/env python3
"""Run the V76 gate as V77 and verify root USB logs are exported to SD."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "00_tools" / "validate_y2_v76_root_route.py"
BUILDER = ROOT / "00_tools" / "build_y2_v77_release_day_gate.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace("build_y2_v76_root_route.py",
                        "build_y2_v77_release_day_gate.py")
    text = text.replace("y2-v76-root-route", "y2-v77-release-day-gate")
    text = text.replace("v76-root-route", "v77-release-day-gate")
    text = text.replace("y2_rockbox_v76_root_route",
                        "y2_rockbox_v77_release_day_gate")
    text = text.replace("Y2 V76", "Y2 V77")
    text = text.replace("V76_SYSTEM", "V77_SYSTEM")
    text = text.replace("V76-TEST.txt", "V77-TEST.txt")
    text = text.replace("Rockbox.v76.apk", "Rockbox.v77.apk")
    text = text.replace("v76-offline-validation", "v77-offline-validation")
    text = text.replace("v76-generic-validation", "v77-generic-validation")

    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", encoding="utf-8", delete=False,
            dir=ROOT / "00_tools") as handle:
        handle.write(text)
        generated = Path(handle.name)
    try:
        result = subprocess.run([sys.executable, str(generated)])
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    finally:
        generated.unlink(missing_ok=True)

    builder = load("v77_builder_validation", BUILDER)
    with zipfile.ZipFile(builder.ZIP) as archive:
        for image_name in ("boot.img", "recovery.img"):
            entries, *_ = builder.v76.ramdisk(archive.read(image_name))
            payloads = {entry["name"]: entry["data"] for entry in entries}
            route = payloads[builder.ROUTE_SCRIPT]
            early = payloads["sbin/y2v54earlydiag.sh"]
            if b'"$DATA_ROOT"/usb-root-broker-*.txt' not in route:
                raise SystemExit(f"{image_name}: route collector omits root USB log")
            if b'"$DATA_ROOT"/usb-root-broker-*.txt' not in early:
                raise SystemExit(f"{image_name}: early collector omits root USB log")
    print("PASS V77 root USB broker logs are exported by route and early collectors")


if __name__ == "__main__":
    main()
