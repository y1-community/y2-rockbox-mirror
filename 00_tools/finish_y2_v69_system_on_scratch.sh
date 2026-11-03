#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/12_build_outputs/y2-rockbox-system-prototype-v69-route-owner"
SCRATCH="${Y2_BUILD_SCRATCH:-/mnt/e/Y2-RockBox-build-intermediates}"
LIBSPARSE_BIN="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/bin"
LIBSPARSE_LIB="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/lib"

mkdir -p "$SCRATCH"
e2fsck -n -f "$OUT/system.raw.img" > "$OUT/e2fsck.txt"
LD_LIBRARY_PATH="$LIBSPARSE_LIB" \
    "$LIBSPARSE_BIN/img2simg" \
    "$OUT/system.raw.img" "$SCRATCH/v69-system.fill.img"
python3 "$ROOT/00_tools/y2_sparse_compat.py" \
    "$SCRATCH/v69-system.fill.img" \
    --rewrite-no-fill "$SCRATCH/v69-system.img" \
    > "$OUT/sparse_rewrite.txt"
python3 "$ROOT/00_tools/y2_sparse_compat.py" \
    "$SCRATCH/v69-system.img" > "$OUT/sparse_analysis.txt"
sha256sum "$SCRATCH/v69-system.img" \
    > "$SCRATCH/v69-system.img.sha256.txt"
