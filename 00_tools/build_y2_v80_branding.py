#!/usr/bin/env python3
"""Build the native 480x360 SPYCE boot animation and MTK logo partition."""

from __future__ import annotations

import argparse
import hashlib
import io
import struct
import zlib
import zipfile
from pathlib import Path

from PIL import Image

WIDTH = 480
HEIGHT = 360
EXPECTED_GIF_SHA256 = (
    "640FD82729D11FC0695AEABC5037B45B0D4811AD902D8C045751F78990A32E5C"
)
MTK_LOGO_MAGIC = 0x58881688
MTK_HEADER_SIZE = 0x200


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def fit_square_frame(frame: Image.Image) -> Image.Image:
    """Preserve the supplied square composition on a native landscape canvas."""
    source = frame.convert("RGB")
    source.thumbnail((HEIGHT, HEIGHT), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "black")
    canvas.paste(source, ((WIDTH - source.width) // 2,
                          (HEIGHT - source.height) // 2))
    return canvas


def gif_frames(path: Path) -> list[Image.Image]:
    if sha256(path) != EXPECTED_GIF_SHA256:
        raise RuntimeError("The supplied SPYCE GIF is missing or has changed")
    result: list[Image.Image] = []
    with Image.open(path) as source:
        frame_count = getattr(source, "n_frames", 1)
        if source.size != (540, 540) or frame_count != 39:
            raise RuntimeError(
                f"Unexpected GIF geometry/frame count: {source.size}/{frame_count}")
        for index in range(frame_count):
            source.seek(index)
            result.append(fit_square_frame(source.copy()))
    return result


def jpeg_bytes(frame: Image.Image) -> bytes:
    output = io.BytesIO()
    frame.save(output, "JPEG", quality=95, subsampling=0, optimize=True)
    return output.getvalue()


def build_bootanimation(frames: list[Image.Image], output: Path) -> None:
    timestamp = (2026, 7, 25, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        def write(name: str, data: bytes, mode: int = 0o644) -> None:
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = mode << 16
            archive.writestr(info, data)

        write("desc.txt",
              b"480 360 20\r\np 1 0 part0\r\np 0 0 part1\r\n")
        write("part0/", b"", 0o755)
        for index, frame in enumerate(frames):
            write(f"part0/SPYCE_{index:05d}.jpg", jpeg_bytes(frame))
        write("part1/", b"", 0o755)
        write("part1/SPYCE_00038.jpg", jpeg_bytes(frames[-1]))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Generated bootanimation ZIP failed CRC")
        if len([name for name in archive.namelist()
                if name.startswith("part0/") and name.endswith(".jpg")]) != 39:
            raise RuntimeError("Generated bootanimation frame count is wrong")


def rgb565_bytes(frame: Image.Image) -> bytes:
    pixels = frame.convert("RGB").tobytes()
    output = bytearray(WIDTH * HEIGHT * 2)
    write = 0
    for read in range(0, len(pixels), 3):
        red, green, blue = pixels[read:read + 3]
        value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
        output[write] = value & 0xFF
        output[write + 1] = value >> 8
        write += 2
    return bytes(output)


def unpack_logo(data: bytes) -> tuple[bytes, list[bytes]]:
    if len(data) < MTK_HEADER_SIZE + 12:
        raise RuntimeError("logo.bin is too small")
    magic, outer_size = struct.unpack_from("<II", data, 0)
    if magic != MTK_LOGO_MAGIC or outer_size != len(data) - MTK_HEADER_SIZE:
        raise RuntimeError("Unexpected MTK logo outer header")
    count, pack_size = struct.unpack_from("<II", data, MTK_HEADER_SIZE)
    if count != 39 or pack_size != outer_size:
        raise RuntimeError("Unexpected MTK logo pack header")
    offsets = list(struct.unpack_from(
        f"<{count}I", data, MTK_HEADER_SIZE + 8))
    if offsets[0] != 8 + count * 4 or offsets != sorted(offsets):
        raise RuntimeError("Invalid MTK logo offsets")
    pack = data[MTK_HEADER_SIZE:MTK_HEADER_SIZE + pack_size]
    limits = offsets[1:] + [pack_size]
    images = [zlib.decompress(pack[start:end])
              for start, end in zip(offsets, limits)]
    if (len(images[0]) != WIDTH * HEIGHT * 2
            or len(images[38]) != WIDTH * HEIGHT * 2):
        raise RuntimeError("Unexpected MTK full-screen logo geometry")
    return data[:MTK_HEADER_SIZE], images


def build_logo(base: Path, static_frame: Image.Image, output: Path) -> None:
    prefix, images = unpack_logo(base.read_bytes())
    replacement = rgb565_bytes(static_frame)
    images[0] = replacement
    images[38] = replacement
    compressed = [zlib.compress(image, 9) for image in images]
    header_size = 8 + len(compressed) * 4
    offsets: list[int] = []
    cursor = header_size
    for blob in compressed:
        offsets.append(cursor)
        cursor += len(blob)
    pack = (struct.pack("<II", len(compressed), cursor)
            + struct.pack(f"<{len(offsets)}I", *offsets)
            + b"".join(compressed))
    prefix = bytearray(prefix)
    struct.pack_into("<II", prefix, 0, MTK_LOGO_MAGIC, len(pack))
    output.write_bytes(bytes(prefix) + pack)

    final_prefix, final_images = unpack_logo(output.read_bytes())
    if final_prefix[8:MTK_HEADER_SIZE] != base.read_bytes()[8:MTK_HEADER_SIZE]:
        raise RuntimeError("MTK logo metadata outside the size field changed")
    if final_images[0] != replacement or final_images[38] != replacement:
        raise RuntimeError("MTK static SPYCE frames did not round-trip")
    _, original = unpack_logo(base.read_bytes())
    if any(final_images[index] != original[index]
           for index in range(1, 38)):
        raise RuntimeError("Charging/error MTK logo assets changed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gif", type=Path, required=True)
    parser.add_argument("--base-logo", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frames = gif_frames(args.gif)
    bootanimation = args.out_dir / "bootanimation.zip"
    logo = args.out_dir / "logo.bin"
    preview = args.out_dir / "spyce-480x360-preview.png"
    build_bootanimation(frames, bootanimation)
    build_logo(args.base_logo, frames[0], logo)
    frames[0].save(preview)
    print(f"bootanimation={bootanimation} sha256={sha256(bootanimation)}")
    print(f"logo={logo} sha256={sha256(logo)}")
    print(f"preview={preview} sha256={sha256(preview)}")


if __name__ == "__main__":
    main()
