#!/usr/bin/env python3
"""Assemble the local Y2 Rockbox Beta V2 / v0.2.0 release asset folder."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile


RELEASE_DIR_NAME = "Y2-Rockbox-Beta-v0.2.0"
FIRMWARE_NAME = "Y2-Rockbox-Beta-v0.2.0-InnioasisUpdater.zip"
CE_NAME = "rom_y2.zip"
SOURCE_NAME = "Y2-Rockbox-Beta-v0.2.0-Source.zip"
FLASHER_NAME = "InnioasisUpdater_Setup_1.1.2.exe"
FIRMWARE_SHA256 = "b9f0a4459b3c3de0e9f5a6c99ec2f3246492ea065e43ff5996a5beb0777d026e"
CE_SHA256 = "22195ab5ef775585d73929c05b2fed28bb497c150705a91cc484a02308eb2a46"
FLASHER_SHA256 = "7fa6ff6677b74e7a1d4068fa309dbe5128ab37764c46de930215471d7418c46f"
ARCHIVE_TIME = (2026, 9, 1, 0, 0, 0)


def run(*command: str, cwd: Path) -> bytes:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_locked(source: Path, destination: Path, expected: str) -> None:
    actual = sha256(source)
    if actual != expected:
        raise ValueError(f"Unexpected hash for {source.name}: {actual} != {expected}")
    shutil.copy2(source, destination)


def add_tar(archive: zipfile.ZipFile, data: bytes) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as source:
        for member in source.getmembers():
            if not member.isfile():
                continue
            extracted = source.extractfile(member)
            if extracted is None:
                continue
            info = zipfile.ZipInfo(member.name, ARCHIVE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (member.mode & 0xFFFF) << 16
            archive.writestr(info, extracted.read())


def build_source_archive(output: Path, repository: Path) -> tuple[str, str]:
    parent = run("git", "rev-parse", "HEAD", cwd=repository).decode().strip()
    submodule = repository / "11_rockbox_android" / "rockbox-y1"
    pointer = run(
        "git", "ls-tree", "HEAD", "11_rockbox_android/rockbox-y1", cwd=repository
    ).decode().split()[2]
    run("git", "cat-file", "-e", f"{pointer}^{{commit}}", cwd=submodule)
    prefix = f"{RELEASE_DIR_NAME}-Source"
    parent_tar = run(
        "git", "archive", "--format=tar", f"--prefix={prefix}/", parent,
        cwd=repository,
    )
    rockbox_tar = run(
        "git", "archive", "--format=tar",
        f"--prefix={prefix}/11_rockbox_android/rockbox-y1/", pointer,
        cwd=submodule,
    )
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        add_tar(archive, parent_tar)
        add_tar(archive, rockbox_tar)
        note = (
            "Y2 Rockbox Beta V2 / v0.2.0 source commits\n"
            f"Parent repository: {parent}\n"
            f"Rockbox submodule: {pointer}\n"
        )
        info = zipfile.ZipInfo(f"{prefix}/SOURCE-COMMITS.txt", ARCHIVE_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, note.encode())
    return parent, pointer


def readme(parent: str, rockbox: str) -> str:
    return f"""Y2 ROCKBOX BETA V2 / v0.2.0 - READ THIS FIRST
=====================================================

SUPPORTED DEVICE
----------------
Innioasis Y2 only, based on the official 3.1.7 firmware lineage.
Do not use these files on a Y1 or another MediaTek device.

BACK UP FIRST
-------------
Treat firmware installation as a full-device erase. Back up internal storage,
microSD content, settings, playlists, themes, databases and the complete hidden
.rockbox directory. Keep the official Y2 3.1.7 recovery package available.

INSTALLABLE FIRMWARE
--------------------
Same sparse-image package type as Beta V1:
  {FIRMWARE_NAME}
  SHA-256: {FIRMWARE_SHA256.upper()}

Canonical Innioasis Updater CE Y2 package:
  {CE_NAME}
  SHA-256: {CE_SHA256.upper()}

Both packages contain the same accepted Rockbox build. rom_y2.zip converts the
Android sparse images to raw images and adds the standard Y2 Updater CE support
files. Do not rename a Y1 package or substitute another preloader/scatter.

WHAT IS NEW
-----------
- Bluetooth Settings, pairing, A2DP, controls and reconnect in Rockbox/Stock.
- Hold Previous/Next to seek; optional held-Volume track skipping.
- Persistent time/date and adjustable wheel vibration, including true-off.
- Clean first-connect and complete USB storage lifecycle on both routes.
- Clean approximately 28-second SPYCE/title/Rockbox launch.
- Centre wake and a standard held-Centre Now Playing context menu.
- Improved Now Playing navigation, PictureFlow and route stability.
- Physically proven official Stock rollback and protected-state recovery.

KNOWN LIMITATIONS / BETA V3
---------------------------
The final power-down animation can look imperfect. FM remains deferred pending
a demonstrably working Y2 vendor baseline. PictureFlow missing-art branding and
faster adjacent-cover loading are deferred polish. Beta V3 also targets lyrics,
480x360 theme diagnostics, high-resolution FLAC, DAC/wired-audio qualification,
settings cleanup and database/playlist presentation controls.

VERIFY FIRST
------------
Check every downloaded file against SHA256SUMS.txt before use. The included
legacy Windows updater is unsigned; use it only when its exact hash matches.
Updater CE is maintained separately at:
https://github.com/y1-community/Innioasis-Updater/releases/latest

SOURCE
------
Parent repository: {parent}
Rockbox submodule:  {rockbox}
See LICENSE.txt and NOTICE.txt. Firmware and updater components are third-party
materials and are not covered by the parent project's GPL notice.

RELEASE NOTES
-------------
https://github.com/SPYCEMAGIC/Y2-Rockbox/releases/tag/v0.2.0-beta
"""


def public_ce_manifest(source_manifest: Path, parent: str, rockbox: str) -> dict:
    source = json.loads(source_manifest.read_text())
    return {
        "schema_version": 1,
        "release": "Y2 Rockbox Beta V2 / v0.2.0",
        "parent_commit": parent,
        "rockbox_commit": rockbox,
        "output": {
            "name": CE_NAME,
            "size": source["output"]["size"],
            "sha256": source["output"]["sha256"],
            "member_count": source["output"]["member_count"],
        },
        "canonical_source": {
            "name": FIRMWARE_NAME,
            "sha256": FIRMWARE_SHA256,
        },
        "transformations": source["transformations"],
        "partition_checks": source["partition_checks"],
        "statement": (
            "All firmware payloads originate from the exact physically accepted "
            "canonical source. Non-transformed firmware members are byte-identical."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--rom-y2", type=Path, required=True)
    parser.add_argument("--rom-y2-manifest", type=Path, required=True)
    parser.add_argument("--flasher", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("dist"))
    parser.add_argument("--repository", type=Path, default=Path("."))
    args = parser.parse_args()

    repository = args.repository.resolve()
    release = args.output_root.resolve() / RELEASE_DIR_NAME
    release.mkdir(parents=True, exist_ok=True)
    copy_locked(args.firmware, release / FIRMWARE_NAME, FIRMWARE_SHA256)
    copy_locked(args.rom_y2, release / CE_NAME, CE_SHA256)
    copy_locked(args.flasher, release / FLASHER_NAME, FLASHER_SHA256)
    shutil.copy2(repository / "LICENSE", release / "LICENSE.txt")
    shutil.copy2(repository / "NOTICE.md", release / "NOTICE.txt")
    shutil.copy2(
        repository / "00_project_docs" / "Y2_ROCKBOX_BETA_V2_RELEASE.md",
        release / "RELEASE-NOTES.md",
    )
    shutil.copy2(
        repository / "00_project_docs" / "Y2_BETA_V2_UPDATER_FORMATS.md",
        release / "UPDATER-FORMATS.md",
    )
    shutil.copy2(
        repository / "00_project_docs" / "Y2_ROCKBOX_BETA_V2_INSTALL_GUIDE.md",
        release / "INSTALL-GUIDE.md",
    )
    parent, rockbox = build_source_archive(release / SOURCE_NAME, repository)
    (release / "README-FIRST.txt").write_text(readme(parent, rockbox), newline="\n")
    manifest = public_ce_manifest(args.rom_y2_manifest, parent, rockbox)
    (release / "rom_y2.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    assets = sorted(
        item for item in release.iterdir()
        if item.is_file() and item.name != "SHA256SUMS.txt"
    )
    (release / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(item).upper()}  {item.name}\n" for item in assets),
        encoding="ascii",
    )
    for item in sorted(release.iterdir()):
        if item.is_file():
            print(f"{item.name}\t{item.stat().st_size}\t{sha256(item)}")


if __name__ == "__main__":
    main()
