#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_RAW="$ROOT/build-intermediates/y2-rockbox-system-prototype-v81-continuous-handoff/system.raw.img"
OUT="$ROOT/build-intermediates/y2-rockbox-system-prototype-v83-boot-settings-ipc"
V83_APK="$ROOT/build-intermediates/rockbox-android-y2-v83-boot-settings-ipc/rockbox-y2-v83-boot-settings-ipc.apk"
LIBSPARSE_BIN="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/bin"
LIBSPARSE_LIB="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/lib"
export E2FSPROGS_FAKE_TIME=1785240000

for required in "$BASE_RAW" "$V83_APK" \
        "$LIBSPARSE_BIN/img2simg" "$LIBSPARSE_LIB"; do
    test -e "$required" || {
        echo "Missing required input: $required" >&2
        exit 2
    }
done
case "$OUT" in
    "$ROOT/build-intermediates/y2-rockbox-system-prototype-v83-boot-settings-ipc") ;;
    *)
        echo "Refusing unsafe V83 system output path: $OUT" >&2
        exit 2
        ;;
esac

rm -rf "$OUT"
mkdir -p "$OUT"
cp "$BASE_RAW" "$OUT/system.raw.img"
cp "$V83_APK" "$OUT/Rockbox.v83.apk"

python3 - "$V83_APK" "$OUT/libmisc.so" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    if archive.testzip() is not None:
        raise SystemExit("V83 APK failed CRC")
    payload = archive.read("lib/armeabi/libmisc.so")
with open(sys.argv[2], "wb") as output:
    output.write(payload)
PY

pushd "$OUT" >/dev/null
debugfs -w -R "rm /app/Rockbox.apk" system.raw.img
debugfs -w -R "write Rockbox.v83.apk /app/Rockbox.apk" system.raw.img
debugfs -w -R "sif /app/Rockbox.apk mode 0100644" system.raw.img
debugfs -w -R "rm /lib/libmisc.so" system.raw.img
debugfs -w -R "write libmisc.so /lib/libmisc.so" system.raw.img
debugfs -w -R "sif /lib/libmisc.so mode 0100644" system.raw.img
debugfs -R "dump /app/Rockbox.apk Rockbox.dump.apk" system.raw.img
debugfs -R "dump /lib/libmisc.so libmisc.dump.so" system.raw.img
cmp Rockbox.v83.apk Rockbox.dump.apk
cmp libmisc.so libmisc.dump.so
debugfs -R "stat /bin/content" system.raw.img > content-command-stat.txt
grep -q "Mode:  0755" content-command-stat.txt
debugfs -R "stat /priv-app/SettingsProvider.apk" system.raw.img \
    > settings-provider-stat.txt
grep -q "Mode:  0644" settings-provider-stat.txt
popd >/dev/null

e2fsck -n -f "$OUT/system.raw.img" > "$OUT/e2fsck.txt"
LD_LIBRARY_PATH="$LIBSPARSE_LIB" "$LIBSPARSE_BIN/img2simg" \
    "$OUT/system.raw.img" "$OUT/system.fill.img"
python3 "$ROOT/00_tools/y2_sparse_compat.py" "$OUT/system.fill.img" \
    --rewrite-no-fill "$OUT/system.img" > "$OUT/sparse_rewrite.txt"
python3 "$ROOT/00_tools/y2_sparse_compat.py" "$OUT/system.img" \
    > "$OUT/sparse_analysis.txt"
sha256sum "$OUT/system.img" > "$OUT/system.img.sha256.txt"
