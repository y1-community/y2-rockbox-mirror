#!/usr/bin/env python3
"""Build an Innioasis Updater/MTKClient Y2 package from a verified Y2 ZIP."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile


EXPECTED_SOURCE_SHA256 = (
    "40636d86943f6f0a1461b6d8c9285a1a50252253447b3dc7d11743533a88e4de"
)
SPARSE_MAGIC = 0xED26FF3A
IMAGES_TO_DESPARSE = ("system.img", "cache.img", "userdata.img")
REQUIRED_FIRMWARE_MEMBERS = {
    "EBR1",
    "EBR2",
    "MBR",
    "MT6582_Android_scatter.txt",
    "boot.img",
    "cache.img",
    "lk.bin",
    "logo.bin",
    "preloader_eastaeon82_wet_kk.bin",
    "recovery.img",
    "secro.img",
    "system.img",
    "userdata.img",
}
DA_NAME = "MTK_AllInOne_DA.bin"
HISTORY_NAME = "history.ini"
HISTORY_CONTENT = (
    "[LastDAFilePath]\n"
    "lastDir=MTK_AllInOne_DA.bin\n"
    "\n"
    "[RecentOpenFile]\n"
    "lastDir=\n"
    "scatterHistory=MT6582_Android_scatter.txt\n"
    "authHistory=\n"
).encode("ascii")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sparse_declared_raw_size(path: Path) -> int | None:
    with path.open("rb") as handle:
        header = handle.read(28)
    if len(header) != 28:
        return None
    magic, _major, _minor, _fh, _ch, block_size, blocks, _chunks, _crc = (
        struct.unpack("<I4H4I", header)
    )
    if magic != SPARSE_MAGIC:
        return None
    return block_size * blocks


def validate_source_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("The source ZIP contains duplicate member names")

    for name in names:
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise ValueError(f"Unsafe or nested source member: {name}")
        if name in {DA_NAME, HISTORY_NAME}:
            raise ValueError(f"Source unexpectedly contains generated support file: {name}")

    missing = sorted(REQUIRED_FIRMWARE_MEMBERS - set(names))
    if missing:
        raise ValueError(f"Source ZIP is missing required firmware: {', '.join(missing)}")
    return infos


def extract_source(archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo], root: Path) -> None:
    for info in infos:
        target = root / info.filename
        with archive.open(info) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        timestamp = dt.datetime(*info.date_time, tzinfo=dt.timezone.utc).timestamp()
        os.utime(target, (timestamp, timestamp))


def parse_scatter_partition_sizes(path: Path) -> dict[str, int]:
    entries: dict[str, int] = {}
    current_name: str | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("partition_name:"):
            current_name = line.split(":", 1)[1].strip().upper()
        elif current_name and line.startswith("partition_size:"):
            value = line.split(":", 1)[1].strip()
            entries[current_name] = int(value, 0)
            current_name = None
    return entries


def desparse_images(root: Path, simg2img: str) -> list[dict[str, object]]:
    transformations: list[dict[str, object]] = []
    for name in IMAGES_TO_DESPARSE:
        source = root / name
        source_timestamp = source.stat().st_mtime
        declared_size = sparse_declared_raw_size(source)
        before_hash = sha256_file(source)
        before_size = source.stat().st_size
        if declared_size is None:
            raise ValueError(f"{name} in the released ZIP is not Android sparse")

        raw_path = root / f"{name}.raw"
        subprocess.run(
            [simg2img, str(source), str(raw_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        if raw_path.stat().st_size != declared_size:
            raise ValueError(
                f"{name} raw size mismatch: {raw_path.stat().st_size} != {declared_size}"
            )
        os.replace(raw_path, source)
        os.utime(source, (source_timestamp, source_timestamp))
        transformations.append(
            {
                "member": name,
                "operation": "Android sparse to raw via simg2img",
                "source_size": before_size,
                "source_sha256": before_hash,
                "raw_size": source.stat().st_size,
                "raw_sha256": sha256_file(source),
            }
        )
    return transformations


def verify_partition_fit(root: Path) -> list[dict[str, object]]:
    partition_sizes = parse_scatter_partition_sizes(
        root / "MT6582_Android_scatter.txt"
    )
    mapping = {
        "system.img": "ANDROID",
        "cache.img": "CACHE",
        "userdata.img": "USRDATA",
    }
    results: list[dict[str, object]] = []
    for image_name, partition_name in mapping.items():
        if partition_name not in partition_sizes:
            raise ValueError(f"Scatter is missing partition {partition_name}")
        image_size = (root / image_name).stat().st_size
        partition_size = partition_sizes[partition_name]
        if image_size > partition_size:
            raise ValueError(
                f"{image_name} is larger than {partition_name}: "
                f"{image_size} > {partition_size}"
            )
        results.append(
            {
                "image": image_name,
                "partition": partition_name,
                "image_size": image_size,
                "partition_size": partition_size,
                "fits": True,
            }
        )
    return results


def add_support_files(root: Path, updater_dir: Path, timestamp: float) -> dict[str, object]:
    da_source = updater_dir / DA_NAME
    if not da_source.is_file():
        raise FileNotFoundError(f"Updater Download Agent not found: {da_source}")
    shutil.copy2(da_source, root / DA_NAME)
    (root / HISTORY_NAME).write_bytes(HISTORY_CONTENT)
    os.utime(root / DA_NAME, (timestamp, timestamp))
    os.utime(root / HISTORY_NAME, (timestamp, timestamp))
    return {
        "download_agent": {
            "source": str(da_source.resolve()),
            "size": da_source.stat().st_size,
            "sha256": sha256_file(da_source),
        },
        "history_ini": {
            "generated": True,
            "size": len(HISTORY_CONTENT),
            "sha256": hashlib.sha256(HISTORY_CONTENT).hexdigest(),
        },
    }


def git_revision(path: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def write_package(
    output: Path,
    root: Path,
    source_infos: list[zipfile.ZipInfo],
) -> list[str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    temp_output.unlink(missing_ok=True)
    member_names = [info.filename for info in source_infos] + [DA_NAME, HISTORY_NAME]
    try:
        with zipfile.ZipFile(
            temp_output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for name in member_names:
                archive.write(root / name, arcname=name)
        os.replace(temp_output, output)
    finally:
        temp_output.unlink(missing_ok=True)
    return member_names


def validate_package(
    output: Path,
    expected_names: list[str],
    unchanged_hashes: dict[str, str],
) -> list[dict[str, object]]:
    members: list[dict[str, object]] = []
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if names != expected_names:
            raise ValueError("Output ZIP member names/order differ from the build plan")
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"Output ZIP CRC failure: {bad_member}")

        for info in archive.infolist():
            digest = hashlib.sha256()
            with archive.open(info) as handle:
                first = handle.read(28)
                digest.update(first)
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            member_hash = digest.hexdigest()
            if info.filename in unchanged_hashes:
                if member_hash != unchanged_hashes[info.filename]:
                    raise ValueError(f"Released member changed unexpectedly: {info.filename}")
            if info.filename in IMAGES_TO_DESPARSE and len(first) >= 4:
                if struct.unpack("<I", first[:4])[0] == SPARSE_MAGIC:
                    raise ValueError(f"Output image is still sparse: {info.filename}")
            members.append(
                {
                    "name": info.filename,
                    "size": info.file_size,
                    "compressed_size": info.compress_size,
                    "sha256": member_hash,
                }
            )
    return members


def build(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    updater_dir = args.updater_dir.resolve()
    output = args.output.resolve()
    manifest_path = args.manifest.resolve()
    simg2img = args.simg2img or shutil.which("simg2img")
    if not simg2img:
        raise FileNotFoundError("simg2img is required and was not found on PATH")

    source_hash = sha256_file(source)
    expected_source_hash = args.expected_source_sha256.lower()
    if source_hash != expected_source_hash:
        raise ValueError(
            "Source ZIP hash does not match --expected-source-sha256: "
            f"{source_hash} != {expected_source_hash}"
        )

    with tempfile.TemporaryDirectory(prefix="y2-mac-rom-") as temp:
        root = Path(temp)
        with zipfile.ZipFile(source) as source_archive:
            source_infos = validate_source_members(source_archive)
            if source_archive.testzip() is not None:
                raise ValueError("Source ZIP failed CRC validation")
            unchanged_hashes = {}
            for info in source_infos:
                if info.filename not in IMAGES_TO_DESPARSE:
                    with source_archive.open(info) as handle:
                        digest = hashlib.sha256()
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                        unchanged_hashes[info.filename] = digest.hexdigest()
            extract_source(source_archive, source_infos, root)

        transformations = desparse_images(root, simg2img)
        partition_checks = verify_partition_fit(root)
        timestamp = max((root / info.filename).stat().st_mtime for info in source_infos)
        support = add_support_files(root, updater_dir, timestamp)
        expected_names = write_package(output, root, source_infos)
        members = validate_package(output, expected_names, unchanged_hashes)

    manifest = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "output": {
            "path": str(output),
            "size": output.stat().st_size,
            "sha256": sha256_file(output),
            "member_count": len(members),
        },
        "firmware_source": {
            "path": str(source),
            "sha256": source_hash,
            "expected_sha256": expected_source_hash,
            "label": args.source_label,
            "physical_status": args.source_physical_status,
            "statement": (
                "All Y2 firmware payloads originate exclusively from the verified "
                "SPYCEMAGIC source ZIP recorded above."
            ),
        },
        "updater_support_source": {
            "path": str(updater_dir),
            "git_revision": git_revision(updater_dir),
            "repository": "https://github.com/y1-community/Innioasis-Updater",
            **support,
        },
        "transformations": transformations,
        "partition_checks": partition_checks,
        "members": members,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Built: {output}")
    print(f"SHA-256: {manifest['output']['sha256']}")
    print(f"Members: {manifest['output']['member_count']}")
    print(f"Manifest: {manifest_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Canonical Y2 ZIP")
    parser.add_argument(
        "--expected-source-sha256",
        default=EXPECTED_SOURCE_SHA256,
        help="Required SHA-256 for the canonical input (defaults to released V88)",
    )
    parser.add_argument(
        "--source-label",
        default="SPYCEMAGIC Y2 Rockbox V88 beta",
        help="Human-readable source build label for the manifest",
    )
    parser.add_argument(
        "--source-physical-status",
        default="physically accepted V88 beta",
        help="Physical-test status recorded in the manifest",
    )
    parser.add_argument(
        "--updater-dir",
        type=Path,
        required=True,
        help="Checked-out/installed Innioasis Updater directory containing the DA",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output rom_y2.zip")
    parser.add_argument("--manifest", type=Path, required=True, help="Output JSON manifest")
    parser.add_argument("--simg2img", help="Optional explicit simg2img executable")
    return parser.parse_args()


if __name__ == "__main__":
    build(parse_args())
