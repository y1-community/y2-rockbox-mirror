#!/usr/bin/env python3
"""Package the chooser-free V71 payload as the V73 recovery build."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
E_ROOT = Path(r"E:\Y2-RockBox-build-intermediates")
BASE_ZIP = E_ROOT / "y2-v71-wake-owner.zip"
BASE_SHA256 = "7666B9285EEB680AFACB78A559D0FCEF54A67F3A39FB19A523914873D630863B"
BASE_APK = E_ROOT / "rockbox-android-y2-v71-wake-owner" / "rockbox-y2-v71-wake-owner.apk"
AAPT = ROOT / "00_tools" / "android-sdk" / "build-tools" / "19.1.0" / "aapt.exe"
SOURCE_MANIFEST = ROOT / "11_rockbox_android" / "rockbox-y1" / "android" / "AndroidManifest.xml"
OUT = E_ROOT / "y2-v73-home-resolver-recovery"
ZIP = E_ROOT / "y2-v73-home-resolver-recovery.zip"
ZIP_SHA = E_ROOT / "y2-v73-home-resolver-recovery.zip.sha256.txt"
REPORT_JSON = "y2-v73-home-resolver-recovery.json"
REPORT_MD = "y2-v73-home-resolver-recovery.md"
RECOVERY_TXT = "V73-RECOVERY-TEST.txt"
ZIP_TIMESTAMP = (2026, 7, 21, 23, 55, 0)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v69 = load_module("v69_builder_base", ROOT / "00_tools" / "build_y2_v69_route_ownership.py")
FILES = v69.FILES


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def verify_chooser_free_inputs() -> None:
    if not BASE_ZIP.is_file() or sha256(BASE_ZIP) != BASE_SHA256:
        raise RuntimeError("Validated V71 base ZIP is missing or drifted")
    if not BASE_APK.is_file() or not AAPT.is_file():
        raise FileNotFoundError("V71 APK or aapt is missing")
    source_text = SOURCE_MANIFEST.read_text(encoding="utf-8")
    if "android.intent.category.HOME" in source_text:
        raise RuntimeError("Rockbox source still declares an Android HOME candidate")
    dump = subprocess.run(
        [str(AAPT), "dump", "xmltree", str(BASE_APK), "AndroidManifest.xml"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout
    if "android.intent.category.HOME" in dump:
        raise RuntimeError("Validated V71 APK unexpectedly declares Android HOME")
    with zipfile.ZipFile(BASE_ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V71 base ZIP failed CRC verification")
        missing = [name for name in FILES if name not in archive.namelist()]
        if missing:
            raise RuntimeError(f"V71 base ZIP is incomplete: {missing}")


def compose() -> dict[str, dict[str, object]]:
    verify_chooser_free_inputs()
    if OUT.resolve().parent != E_ROOT.resolve() or OUT.name != "y2-v73-home-resolver-recovery":
        raise RuntimeError(f"Refusing unsafe output path: {OUT}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    details: dict[str, dict[str, object]] = {}
    with zipfile.ZipFile(BASE_ZIP) as archive:
        for name in FILES:
            data = archive.read(name)
            (OUT / name).write_bytes(data)
            output_hash = sha256(OUT / name)
            base_hash = sha256_bytes(data)
            details[name] = {
                "size": len(data),
                "sha256": output_hash,
                "v71_sha256": base_hash,
                "matches_v71": output_hash == base_hash,
            }
    return details


def write_reports(files: dict[str, dict[str, object]]) -> None:
    manifest = {
        "build": "y2-v73-home-resolver-recovery",
        "status": "chooser-free recovery from unsafe V72; physical validation required",
        "created_local": "2026-07-21T23:55:00+10:00",
        "base": {
            "zip": str(BASE_ZIP),
            "sha256": BASE_SHA256,
            "partition_payloads": "all packaged firmware partitions byte-identical to V71",
        },
        "v72_failure": {
            "evidence": r"E:\Y2-RockBox-evidence\v72-physical-home-resolver-loop-20260721",
            "root_causes": [
                "V72 exposed Rockbox, Boot Settings and stock as simultaneous Android HOME candidates before route policy could run.",
                "The component verification grep expected org.rockbox.RockboxActivity while dumpsys spells the component org.rockbox/.RockboxActivity, so policy failed safe on every captured boot.",
                "After Always Rockbox was selected on a stock route, Android repeatedly launched Rockbox as HOME while Rockbox's stock-route launch guard exited.",
            ],
        },
        "recovery_behavior": [
            "RockboxActivity and Y2BootSettingsActivity do not declare android.intent.category.HOME.",
            "The vendor Y1 launcher is again the sole HOME candidate, so Android cannot resolve a HOME intent to Rockbox and the saved V72 preference is ineligible.",
            "V71 explicit button routing, centre-wake release suppression and Rockbox SCREEN_ON foreground ownership are restored.",
            "No userdata clear is performed; Rockbox settings and themes are preserved.",
        ],
        "architecture_decision": (
            "Held-button routing cannot safely be implemented by exposing multiple persistent HOME candidates and selecting one later in boot. "
            "A future chooser-proof design needs one permanent HOME router (and no competing vendor HOME filter) or a selection committed before reboot."
        ),
        "next_test": [
            "Flash the complete V73 ZIP with Download Only; never Format All.",
            "Cold boot with no key and confirm stock opens with no HOME chooser.",
            "Power off, cold boot with Volume Down and confirm Rockbox opens.",
            "Sleep/wake Rockbox with Centre five times and confirm no highlighted item is selected.",
            "Confirm three-second power works, then perform the deferred USB storage connect/eject/unplug test.",
        ],
        "files": files,
    }
    (OUT / REPORT_JSON).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / REPORT_MD).write_text(
        "# Y2 V73 HOME Resolver Recovery\n\n"
        "V73 removes V72's unsafe Android HOME candidates by restoring every firmware "
        "partition to the validated V71 payload. The stock Y1 launcher is the sole HOME; "
        "Rockbox and Boot Settings remain explicit route targets. No userdata is cleared.\n\n"
        "Flash the complete ZIP with **Download Only**. Never use Format All.\n",
        encoding="utf-8",
    )
    (OUT / RECOVERY_TXT).write_text(
        "Y2 V73 RECOVERY TEST\n"
        "1. Flash the complete package using Download Only. NEVER Format All.\n"
        "2. Boot with no key: stock must open with no HOME chooser.\n"
        "3. Power off; boot with Volume Down: Rockbox must open.\n"
        "4. Sleep/wake Rockbox with Centre five times; no menu selection may leak.\n"
        "5. Confirm three-second power.\n"
        "6. Test USB storage, safely eject/disable, unplug, and confirm Rockbox returns.\n",
        encoding="utf-8",
    )


def write_zip() -> None:
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted((*FILES, REPORT_JSON, REPORT_MD, RECOVERY_TXT)):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (OUT / name).read_bytes())


def main() -> None:
    files = compose()
    mismatches = [name for name, detail in files.items() if not detail["matches_v71"]]
    if mismatches:
        raise RuntimeError(f"Unexpected partition drift from V71: {mismatches}")
    write_reports(files)
    write_zip()
    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V73 ZIP failed CRC verification")
    zip_hash = sha256(ZIP)
    ZIP_SHA.write_text(f"{zip_hash} *{ZIP.name}\n", encoding="ascii")
    print(json.dumps({
        "zip": str(ZIP),
        "size": ZIP.stat().st_size,
        "sha256": zip_hash,
        "partition_drift_from_v71": mismatches,
        "rockbox_home_candidates": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
