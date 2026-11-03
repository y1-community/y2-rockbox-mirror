#!/usr/bin/env python3
"""Build the V81 continuous SPYCE boot animation from the verified V80 frames."""

from __future__ import annotations

import argparse
import importlib.util
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_v80():
    path = ROOT / "00_tools" / "build_y2_v80_branding.py"
    spec = importlib.util.spec_from_file_location("v80_branding_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v80 = load_v80()


def build_bootanimation(frames, output: Path) -> None:
    """Group three complete GIF cycles into each interruptible animation part."""
    timestamp = (2026, 7, 25, 2, 0, 0)
    encoded = [v80.jpeg_bytes(frame) for frame in frames]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        def write(name: str, data: bytes, mode: int = 0o644) -> None:
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = mode << 16
            archive.writestr(info, data)

        write("desc.txt", b"480 360 20\r\np 0 0 part0\r\n")
        write("part0/", b"", 0o755)
        for cycle in range(3):
            for frame_index, data in enumerate(encoded):
                output_index = cycle * len(encoded) + frame_index
                write(
                    f"part0/SPYCE_{output_index:05d}.jpg",
                    data,
                )

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        frame_names = [
            name for name in names
            if name.startswith("part0/") and name.endswith(".jpg")
        ]
        if archive.testzip() is not None:
            raise RuntimeError("V81 boot animation ZIP failed CRC")
        if archive.read("desc.txt") != b"480 360 20\r\np 0 0 part0\r\n":
            raise RuntimeError("V81 continuous descriptor is wrong")
        if len(frame_names) != 117:
            raise RuntimeError("V81 must contain three complete 39-frame cycles")
        for cycle in range(3):
            for frame_index, expected in enumerate(encoded):
                output_index = cycle * len(encoded) + frame_index
                actual = archive.read(
                    f"part0/SPYCE_{output_index:05d}.jpg"
                )
                if actual != expected:
                    raise RuntimeError(
                        f"V81 frame cycle mismatch at {cycle}/{frame_index}"
                    )
        if any(name.startswith("part1/") for name in names):
            raise RuntimeError("V81 retained the V80 static hold section")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gif", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frames = v80.gif_frames(args.gif)
    output = args.out_dir / "bootanimation.zip"
    preview = args.out_dir / "spyce-first-frame-480x360.png"
    build_bootanimation(frames, output)
    frames[0].save(preview)
    print(f"bootanimation={output} sha256={v80.sha256(output)}")
    print(f"preview={preview} sha256={v80.sha256(preview)}")


if __name__ == "__main__":
    main()
