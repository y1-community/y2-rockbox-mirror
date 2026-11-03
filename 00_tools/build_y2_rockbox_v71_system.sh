#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="/mnt/e/Y2-RockBox-build-intermediates"
BASE_RAW="$BASE/y2-rockbox-system-prototype-v69-route-owner-system.raw.img"
OUT="${Y2_SYSTEM_OUT:-$BASE/y2-rockbox-system-prototype-v71-wake-owner}"
V65_APK="$ROOT/12_build_outputs/rockbox-android-y2-v65/rockbox-y2-v65-android-unplug-reassert.apk"
V71_APK="${Y2_SYSTEM_APK:-$BASE/rockbox-android-y2-v71-wake-owner/rockbox-y2-v71-wake-owner.apk}"
LIBSPARSE_BIN="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/bin"
LIBSPARSE_LIB="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/lib"
export E2FSPROGS_FAKE_TIME=1784394000

for required in "$BASE_RAW" "$V65_APK" "$V71_APK"; do
    test -f "$required" || { echo "Missing required input: $required" >&2; exit 2; }
done
case "$OUT" in
    /mnt/e/Y2-RockBox-build-intermediates/y2-rockbox-system-prototype-v71-wake-owner|\
    /mnt/e/Y2-RockBox-build-intermediates/y2-rockbox-system-prototype-v72-exclusive-home) ;;
    *) echo "Refusing unsafe V71 output path: $OUT" >&2; exit 2 ;;
esac
rm -rf "$OUT"
mkdir -p "$OUT/apk_libs"
cp "$BASE_RAW" "$OUT/system.raw.img"
cp "$V71_APK" "$OUT/Rockbox.v71.apk"

python3 - "$V65_APK" "$V71_APK" "$OUT/apk_libs" <<'PY'
import hashlib, sys, zipfile
from pathlib import Path
def libs(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist() if n.startswith("lib/armeabi/") and n.endswith(".so")}
old, new = libs(sys.argv[1]), libs(sys.argv[2])
if old.keys() != new.keys() or any(hashlib.sha256(old[n]).digest() != hashlib.sha256(new[n]).digest() for n in old):
    raise SystemExit("V71 native libraries differ from stable V65")
out = Path(sys.argv[3])
for name, data in new.items(): (out / Path(name).name).write_bytes(data)
PY

pushd "$OUT" >/dev/null
debugfs -w -R "rm /app/Rockbox.apk" system.raw.img
debugfs -w -R "write Rockbox.v71.apk /app/Rockbox.apk" system.raw.img
debugfs -w -R "sif /app/Rockbox.apk mode 0100644" system.raw.img
debugfs -R "dump /app/Rockbox.apk Rockbox.dump.apk" system.raw.img
cmp Rockbox.v71.apk Rockbox.dump.apk
for layout in mtk-tpd.kl mtk-tpd-kpd.kl; do
    debugfs -R "dump /usr/keylayout/$layout $layout.dump" system.raw.img
    grep -Eq '^key[[:space:]]+28[[:space:]]+ENTER[[:space:]]+WAKE_DROPPED$' "$layout.dump"
done
for library in apk_libs/*.so; do
    name="$(basename "$library")"
    debugfs -R "dump /lib/$name $name.dump" system.raw.img
    cmp "$library" "$name.dump"
done
popd >/dev/null

e2fsck -n -f "$OUT/system.raw.img" > "$OUT/e2fsck.txt"
LD_LIBRARY_PATH="$LIBSPARSE_LIB" "$LIBSPARSE_BIN/img2simg" "$OUT/system.raw.img" "$OUT/system.fill.img"
python3 "$ROOT/00_tools/y2_sparse_compat.py" "$OUT/system.fill.img" --rewrite-no-fill "$OUT/system.img" > "$OUT/sparse_rewrite.txt"
python3 "$ROOT/00_tools/y2_sparse_compat.py" "$OUT/system.img" > "$OUT/sparse_analysis.txt"
sha256sum "$OUT/system.img" > "$OUT/system.img.sha256.txt"
