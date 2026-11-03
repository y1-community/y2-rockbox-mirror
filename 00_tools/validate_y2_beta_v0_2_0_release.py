#!/usr/bin/env python3
"""Validate the assembled Y2 Rockbox Beta V2 release directory offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile


FIRMWARE = "Y2-Rockbox-Beta-v0.2.0-InnioasisUpdater.zip"
SOURCE = "Y2-Rockbox-Beta-v0.2.0-Source.zip"
EXPECTED = {
    FIRMWARE: "b9f0a4459b3c3de0e9f5a6c99ec2f3246492ea065e43ff5996a5beb0777d026e",
    "rom_y2.zip": "22195ab5ef775585d73929c05b2fed28bb497c150705a91cc484a02308eb2a46",
    "InnioasisUpdater_Setup_1.1.2.exe": "7fa6ff6677b74e7a1d4068fa309dbe5128ab37764c46de930215471d7418c46f",
}
REQUIRED = set(EXPECTED) | {
    SOURCE,
    "README-FIRST.txt",
    "RELEASE-NOTES.md",
    "INSTALL-GUIDE.md",
    "UPDATER-FORMATS.md",
    "rom_y2.manifest.json",
    "SHA256SUMS.txt",
    "LICENSE.txt",
    "NOTICE.txt",
}
SPARSE_MAGIC = 0xED26FF3A


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_magic(archive: zipfile.ZipFile, name: str) -> int:
    with archive.open(name) as handle:
        return struct.unpack("<I", handle.read(4))[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    root = args.release.resolve()
    checks: list[tuple[str, bool, str]] = []
    names = {item.name for item in root.iterdir() if item.is_file()}
    checks.append(("asset_set", names == REQUIRED, f"{len(names)} files"))
    for name, expected in EXPECTED.items():
        actual = sha256(root / name)
        checks.append((f"hash_{name}", actual == expected, actual))
    with zipfile.ZipFile(root / FIRMWARE) as archive:
        checks.append(("firmware_crc", archive.testzip() is None, "CRC"))
        sparse = all(
            image_magic(archive, name) == SPARSE_MAGIC
            for name in ("system.img", "cache.img", "userdata.img")
        )
        checks.append(("legacy_sparse_images", sparse, "three sparse images"))
    with zipfile.ZipFile(root / "rom_y2.zip") as archive:
        checks.append(("rom_y2_crc", archive.testzip() is None, "CRC"))
        raw = all(
            image_magic(archive, name) != SPARSE_MAGIC
            for name in ("system.img", "cache.img", "userdata.img")
        )
        support = {"MTK_AllInOne_DA.bin", "history.ini"} <= set(archive.namelist())
        checks.append(("rom_y2_raw_images", raw, "three raw images"))
        checks.append(("rom_y2_support", support, "DA and history"))
    checksum_lines = (root / "SHA256SUMS.txt").read_text().splitlines()
    parsed = {line.split("  ", 1)[1]: line.split("  ", 1)[0].lower() for line in checksum_lines}
    checksum_ok = set(parsed) == REQUIRED - {"SHA256SUMS.txt"} and all(
        sha256(root / name) == value for name, value in parsed.items()
    )
    checks.append(("checksum_manifest", checksum_ok, f"{len(parsed)} entries"))
    public_text = "\n".join(
        (root / name).read_text(errors="replace")
        for name in (
            "README-FIRST.txt", "RELEASE-NOTES.md", "INSTALL-GUIDE.md",
            "UPDATER-FORMATS.md", "rom_y2.manifest.json",
        )
    )
    checks.append(("no_local_paths", "/Users/" not in public_text, "public text"))
    manifest = json.loads((root / "rom_y2.manifest.json").read_text())
    checks.append((
        "public_manifest",
        manifest["output"]["sha256"] == EXPECTED["rom_y2.zip"]
        and manifest["canonical_source"]["sha256"] == EXPECTED[FIRMWARE],
        "locked identities",
    ))
    passed = sum(ok for _, ok, _ in checks)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    print(f"RESULT: {passed}/{len(checks)}")
    print("device_accessed: false")
    if passed != len(checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
