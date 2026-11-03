#!/usr/bin/env python3
"""Assemble the local Y2 Rockbox Beta v0.1.0 release asset folder."""

from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile


RELEASE_DIR_NAME = "Y2-Rockbox-Beta-v0.1.0"
FIRMWARE_RELEASE_NAME = "Y2-Rockbox-Beta-v0.1.0-V88-InnioasisUpdater.zip"
SOURCE_RELEASE_NAME = "Y2-Rockbox-Beta-v0.1.0-Source.zip"
GUIDE_RELEASE_NAME = "Y2-Rockbox-Beta-v0.1.0-Guide.pdf"
FLASHER_RELEASE_NAME = "InnioasisUpdater_Setup_1.1.2.exe"

V88_SOURCE_COMMIT = "dfd4483bb8e93f8bb77c6131ddd945b8085790c4"
FIRMWARE_SHA256 = (
    "40636D86943F6F0A1461B6D8C9285A1A50252253447B3DC7D11743533A88E4DE"
)
FLASHER_SHA256 = (
    "7FA6FF6677B74E7A1D4068FA309DBE5128AB37764C46DE930215471D7418C46F"
)


def run(*command: str, cwd: Path | None = None) -> bytes:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def add_tar_to_zip(
    archive: zipfile.ZipFile,
    tar_bytes: bytes,
) -> None:
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as source:
        for member in source.getmembers():
            if not member.isfile():
                continue
            extracted = source.extractfile(member)
            if extracted is None:
                continue
            info = zipfile.ZipInfo(member.name)
            info.date_time = (2026, 7, 29, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (member.mode & 0xFFFF) << 16
            archive.writestr(info, extracted.read())


def build_source_archive(
    output: Path,
    repository: Path,
    submodule: Path,
) -> tuple[str, str]:
    parent_commit = run("git", "rev-parse", "HEAD", cwd=repository).decode().strip()
    run("git", "cat-file", "-e", f"{V88_SOURCE_COMMIT}^{{commit}}", cwd=submodule)

    prefix = f"{RELEASE_DIR_NAME}-Source"
    parent_tar = run(
        "git",
        "archive",
        "--format=tar",
        f"--prefix={prefix}/",
        parent_commit,
        cwd=repository,
    )
    submodule_tar = run(
        "git",
        "archive",
        "--format=tar",
        f"--prefix={prefix}/11_rockbox_android/rockbox-y1/",
        V88_SOURCE_COMMIT,
        cwd=submodule,
    )

    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        add_tar_to_zip(archive, parent_tar)
        add_tar_to_zip(archive, submodule_tar)
        commit_note = (
            "Y2 Rockbox Beta v0.1.0 source commits\n"
            f"Parent repository: {parent_commit}\n"
            f"Rockbox V88 source: {V88_SOURCE_COMMIT}\n"
            "\n"
            "The Rockbox tree is embedded under:\n"
            "11_rockbox_android/rockbox-y1/\n"
        )
        info = zipfile.ZipInfo(f"{prefix}/SOURCE-COMMITS.txt")
        info.date_time = (2026, 7, 29, 0, 0, 0)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, commit_note.encode("utf-8"))

    return parent_commit, V88_SOURCE_COMMIT


def readme_text(parent_commit: str) -> str:
    return f"""Y2 ROCKBOX BETA v0.1.0 - READ THIS FIRST
================================================

SUPPORTED DEVICE
----------------
Innioasis Y2 only, based on official firmware 3.1.7.
Do not use this on the Y1 or any other MediaTek player.

IMPORTANT
---------
This is beta software. Flashing erases the complete player. Back up internal
storage, microSD content, settings and the entire hidden .rockbox directory.

Bluetooth is untested. The both-volume fastboot shortcut did not work during
physical testing. Keep the official Y2 stock-recovery package available and
use the InnioasisUpdater/pinhole recovery workflow.

FILES TO USE
------------
Firmware:
  {FIRMWARE_RELEASE_NAME}

Windows flasher:
  {FLASHER_RELEASE_NAME}

Visual flashing, operating and theme guide:
  {GUIDE_RELEASE_NAME}

Complete corresponding source:
  {SOURCE_RELEASE_NAME}

VERIFY FIRST
------------
Check every downloaded file against SHA256SUMS.txt.

Firmware SHA-256:
  {FIRMWARE_SHA256}

Flasher SHA-256:
  {FLASHER_SHA256}

The InnioasisUpdater setup is not digitally signed. Windows may warn about an
unknown publisher. Continue only when the filename and SHA-256 match.

QUICK FLASH OUTLINE
-------------------
1. Read the PDF guide completely.
2. Back up all user data and keep official stock recovery ready.
3. Install InnioasisUpdater 1.1.2 and its bundled USB driver.
4. Open the updater and choose the beta firmware ZIP itself. Do not extract it.
5. Start flashing.
6. Fully power off the Y2 and connect it by USB. If detection does not start,
   leave it connected and gently press the bottom reset/pinhole once.
7. Do not disconnect until the updater reaches 100% and says Flash Complete.
8. Disconnect and allow the first boot to finish.

DEFAULT COLD-BOOT ROUTES
------------------------
No volume button: Rockbox
Volume Up:        Stock Y2 interface
Volume Down:      Boot Settings
Both volume:      Not available in this beta

THEMES
------
Use 480x360 Rockbox themes or known-compatible Y1/Y2 360p themes. Merge the
theme's complete .rockbox directory into the existing .rockbox directory.
Never delete or replace the complete existing tree. Full visual instructions
are in the PDF guide.

KNOWN BETA LIMITATIONS
----------------------
- Bluetooth playback is untested.
- The both-volume fastboot chord did not open fastboot.
- Date/time changes did not persist during testing; the stock relationship is
  not yet isolated.
- SNAZZ3 intentionally uses visible 30-pixel margins. It is not display scaling.
- InnioasisUpdater performs a destructive full format-download.

TESTED
------
Flashing, stock rollback, Rockbox/Stock boot selection, saved boot routes,
15-minute playback, controls, sleep/wake, theme persistence, internal and
microSD playback, USB storage/return and power off passed on physical Y2
hardware.

SOURCE AND LICENSES
-------------------
The source archive contains parent commit:
  {parent_commit}

and the exact Rockbox V88 source commit:
  {V88_SOURCE_COMMIT}

See LICENSE.txt and NOTICE.txt. Innioasis firmware and updater components are
third-party materials and are not covered by the project GPL notice.

OFFICIAL Y2 RESET/RECOVERY INFORMATION
--------------------------------------
https://www.innioasis.com/a/docs/y2/reset-your-device
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--firmware",
        type=Path,
        default=Path(
            "build-intermediates/y2-v88-route-readback-repair-innioasis-full.zip"
        ),
    )
    parser.add_argument(
        "--flasher",
        type=Path,
        default=Path("Y2 - Stock/InnioasisUpdater_Setup_1.1.2.exe"),
    )
    parser.add_argument(
        "--guide",
        type=Path,
        default=Path("output/pdf") / GUIDE_RELEASE_NAME,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output/releases"),
    )
    parser.add_argument("--repository", type=Path, default=Path("."))
    args = parser.parse_args()

    repository = args.repository.resolve()
    submodule = repository / "11_rockbox_android" / "rockbox-y1"
    inputs = [args.firmware, args.flasher, args.guide]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise SystemExit("Missing required input(s): " + ", ".join(missing))

    if sha256(args.firmware) != FIRMWARE_SHA256:
        raise SystemExit("The firmware is not the physically tested V88 ZIP")
    if sha256(args.flasher) != FLASHER_SHA256:
        raise SystemExit("The flasher does not match the approved local copy")

    release = args.output_root / RELEASE_DIR_NAME
    release.mkdir(parents=True, exist_ok=True)

    destinations = {
        FIRMWARE_RELEASE_NAME: args.firmware,
        FLASHER_RELEASE_NAME: args.flasher,
        GUIDE_RELEASE_NAME: args.guide,
        "LICENSE.txt": repository / "LICENSE",
        "NOTICE.txt": repository / "NOTICE.md",
    }
    for destination_name, source in destinations.items():
        shutil.copy2(source, release / destination_name)

    parent_commit, _ = build_source_archive(
        release / SOURCE_RELEASE_NAME,
        repository,
        submodule,
    )
    (release / "README-FIRST.txt").write_text(
        readme_text(parent_commit),
        encoding="utf-8",
        newline="\n",
    )

    checksum_files = sorted(
        path for path in release.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    checksum_lines = [
        f"{sha256(path)}  {path.name}" for path in checksum_files
    ]
    (release / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="ascii",
        newline="\n",
    )

    print(release)
    for path in sorted(release.iterdir()):
        if path.is_file():
            print(f"{path.name}\t{path.stat().st_size}\t{sha256(path)}")


if __name__ == "__main__":
    main()
