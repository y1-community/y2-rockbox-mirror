import struct
import sys
from pathlib import Path

SPARSE_MAGIC = 0xED26FF3A
CHUNK_TYPE_RAW = 0xCAC1
CHUNK_TYPE_FILL = 0xCAC2
CHUNK_TYPE_DONT_CARE = 0xCAC3
CHUNK_TYPE_CRC32 = 0xCAC4

def write_repeated(out, pattern, total):
    block = pattern * (1024 * 1024 // len(pattern))
    remaining = total
    while remaining > 0:
        n = min(remaining, len(block))
        out.write(block[:n])
        remaining -= n

def write_zeroes(out, total):
    block = b"\x00" * (1024 * 1024)
    remaining = total
    while remaining > 0:
        n = min(remaining, len(block))
        out.write(block[:n])
        remaining -= n

def convert_sparse_to_raw(src, dst):
    src = Path(src)
    dst = Path(dst)

    with src.open("rb") as f, dst.open("wb") as out:
        header = f.read(28)
        if len(header) != 28:
            raise RuntimeError("File too small for sparse header")

        magic, major, minor, file_hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, checksum = struct.unpack("<IHHHHIIII", header)

        if magic != SPARSE_MAGIC:
            raise RuntimeError(f"Not an Android sparse image. Magic was 0x{magic:08X}")

        if file_hdr_sz > 28:
            f.seek(file_hdr_sz - 28, 1)

        print(f"Input: {src}")
        print(f"Output: {dst}")
        print(f"Sparse version: {major}.{minor}")
        print(f"Block size: {blk_sz}")
        print(f"Total blocks: {total_blks}")
        print(f"Total chunks: {total_chunks}")
        print(f"Expected raw size: {total_blks * blk_sz} bytes")

        for i in range(total_chunks):
            chdr = f.read(12)
            if len(chdr) != 12:
                raise RuntimeError(f"Unexpected end of file reading chunk {i}")

            chunk_type, reserved, chunk_sz, total_sz = struct.unpack("<HHII", chdr)
            data_sz = total_sz - chunk_hdr_sz
            out_sz = chunk_sz * blk_sz

            if chunk_hdr_sz > 12:
                f.seek(chunk_hdr_sz - 12, 1)

            if chunk_type == CHUNK_TYPE_RAW:
                remaining = out_sz
                while remaining > 0:
                    data = f.read(min(1024 * 1024, remaining))
                    if not data:
                        raise RuntimeError(f"Unexpected end of RAW chunk {i}")
                    out.write(data)
                    remaining -= len(data)

            elif chunk_type == CHUNK_TYPE_FILL:
                fill = f.read(4)
                if len(fill) != 4:
                    raise RuntimeError(f"Unexpected end of FILL chunk {i}")
                write_repeated(out, fill, out_sz)

            elif chunk_type == CHUNK_TYPE_DONT_CARE:
                write_zeroes(out, out_sz)

            elif chunk_type == CHUNK_TYPE_CRC32:
                f.seek(data_sz, 1)

            else:
                raise RuntimeError(f"Unknown sparse chunk type 0x{chunk_type:04X} at chunk {i}")

        actual = dst.stat().st_size
        print(f"Actual raw size: {actual} bytes")

        with dst.open("rb") as r:
            r.seek(1024 + 0x38)
            magic2 = r.read(2)

        if magic2 == b"\x53\xEF":
            print("Filesystem check: ext2/ext3/ext4 superblock magic found")
        else:
            print(f"Filesystem check: ext superblock magic NOT found. Bytes were {magic2.hex()}")

if __name__ == "__main__":
    convert_sparse_to_raw(sys.argv[1], sys.argv[2])
