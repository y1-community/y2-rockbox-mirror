#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$ROOT/12_build_outputs/y2-rockbox-system-prototype-v68-clean-return"
OUT="$ROOT/12_build_outputs/y2-rockbox-system-prototype-v69-route-owner"
V65_APK="$ROOT/12_build_outputs/rockbox-android-y2-v65/rockbox-y2-v65-android-unplug-reassert.apk"
V69_APK="$ROOT/12_build_outputs/rockbox-android-y2-v69/rockbox-y2-v69-route-owner.apk"
LIBSPARSE_BIN="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/bin"
LIBSPARSE_LIB="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/lib"
export E2FSPROGS_FAKE_TIME=1784394000

for required in "$BASE/system.raw.img" "$V65_APK" "$V69_APK"; do
    if [ ! -f "$required" ]; then
        echo "Missing required input: $required" >&2
        exit 2
    fi
done

rm -rf "$OUT"
mkdir -p "$OUT/apk_libs"
cp "$BASE/system.raw.img" "$OUT/system.raw.img"
cp "$V69_APK" "$OUT/Rockbox.v69.apk"

python3 - "$V65_APK" "$V69_APK" "$OUT/apk_libs" "$OUT/native-library-diff.txt" <<'PY'
import hashlib
import sys
import zipfile
from pathlib import Path

def native_payload(path):
    with zipfile.ZipFile(path) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith("lib/armeabi/") and name.endswith(".so")
        }

old = native_payload(sys.argv[1])
new = native_payload(sys.argv[2])
if set(old) != set(new):
    raise SystemExit("V69 native library inventory differs from V65")

out = Path(sys.argv[3])
changed = []
for name, data in sorted(new.items()):
    (out / Path(name).name).write_bytes(data)
    if hashlib.sha256(data).digest() != hashlib.sha256(old[name]).digest():
        changed.append(name)
Path(sys.argv[4]).write_text(
    f"library_count={len(new)}\nchanged_count={len(changed)}\n"
    + "\n".join(changed) + "\n",
    encoding="utf-8",
)
if changed:
    raise SystemExit("V69 unexpectedly changed native libraries")
PY

pushd "$OUT" >/dev/null
debugfs -w -R "rm /app/Rockbox.apk" system.raw.img
debugfs -w -R "write Rockbox.v69.apk /app/Rockbox.apk" system.raw.img
debugfs -w -R "sif /app/Rockbox.apk mode 0100644" system.raw.img

debugfs -R "dump /usr/keylayout/Generic.kl mtk-tpd.kl" system.raw.img
sed -i -E 's/^key[[:space:]]+28[[:space:]]+ENTER([[:space:]].*)?$/key 28    ENTER             WAKE_DROPPED/' mtk-tpd.kl
cp mtk-tpd.kl mtk-tpd-kpd.kl
grep -Eq '^key[[:space:]]+28[[:space:]]+ENTER[[:space:]]+WAKE_DROPPED$' mtk-tpd.kl
debugfs -w -R "write mtk-tpd.kl /usr/keylayout/mtk-tpd.kl" system.raw.img
debugfs -w -R "sif /usr/keylayout/mtk-tpd.kl mode 0100644" system.raw.img
debugfs -w -R "write mtk-tpd-kpd.kl /usr/keylayout/mtk-tpd-kpd.kl" system.raw.img
debugfs -w -R "sif /usr/keylayout/mtk-tpd-kpd.kl mode 0100644" system.raw.img

debugfs -R "stat /app/Rockbox.apk" system.raw.img > Rockbox.debugfs.stat.txt
debugfs -R "dump /app/Rockbox.apk Rockbox.dump.apk" system.raw.img
cmp Rockbox.v69.apk Rockbox.dump.apk
for layout in mtk-tpd.kl mtk-tpd-kpd.kl; do
    debugfs -R "dump /usr/keylayout/$layout $layout.dump" system.raw.img
    cmp "$layout" "$layout.dump"
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
