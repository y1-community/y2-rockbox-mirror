#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_RAW="$ROOT/build-intermediates/y2-rockbox-system-prototype-v81-continuous-handoff/system.raw.img"
OUT="$ROOT/build-intermediates/y2-rockbox-system-prototype-v87-vendor-shell-save"
V87_APK="$ROOT/build-intermediates/rockbox-android-y2-v87-vendor-shell-save/rockbox-y2-v87-vendor-shell-save.apk"
BROKER="$ROOT/00_tools/y2_v87_boot_save_broker.sh"
LIBSPARSE_BIN="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/bin"
LIBSPARSE_LIB="$ROOT/13_external_tools/android-sdk-libsparse-utils/local/lib"
export E2FSPROGS_FAKE_TIME=1785342600

for required in "$BASE_RAW" "$V87_APK" "$BROKER" \
        "$LIBSPARSE_BIN/img2simg" "$LIBSPARSE_LIB"; do
    test -e "$required" || {
        echo "Missing required input: $required" >&2
        exit 2
    }
done
case "$OUT" in
    "$ROOT/build-intermediates/y2-rockbox-system-prototype-v87-vendor-shell-save") ;;
    *)
        echo "Refusing unsafe V87 system output path: $OUT" >&2
        exit 2
        ;;
esac

rm -rf "$OUT"
mkdir -p "$OUT"
cp "$BASE_RAW" "$OUT/system.raw.img"
cp "$V87_APK" "$OUT/Rockbox.v87.apk"
cp "$BROKER" "$OUT/y2_boot_route_broker.sh"
printf 'u:object_r:system_file:s0\0' > "$OUT/system-file.selinux"

python3 - "$V87_APK" "$OUT/libmisc.so" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    if archive.testzip() is not None:
        raise SystemExit("V87 APK failed CRC")
    payload = archive.read("lib/armeabi/libmisc.so")
with open(sys.argv[2], "wb") as output:
    output.write(payload)
PY

pushd "$OUT" >/dev/null
debugfs -w -R "rm /app/Rockbox.apk" system.raw.img
debugfs -w -R "write Rockbox.v87.apk /app/Rockbox.apk" system.raw.img
debugfs -w -R "sif /app/Rockbox.apk mode 0100644" system.raw.img
debugfs -w -R "rm /lib/libmisc.so" system.raw.img
debugfs -w -R "write libmisc.so /lib/libmisc.so" system.raw.img
debugfs -w -R "sif /lib/libmisc.so mode 0100644" system.raw.img
debugfs -w -R "rm /etc/y2_boot_route_broker.sh" system.raw.img || true
debugfs -w -R "write y2_boot_route_broker.sh /etc/y2_boot_route_broker.sh" system.raw.img
debugfs -w -R "sif /etc/y2_boot_route_broker.sh mode 0100644" system.raw.img
debugfs -w -R "ea_set -f system-file.selinux /etc/y2_boot_route_broker.sh security.selinux" system.raw.img
debugfs -R "dump /app/Rockbox.apk Rockbox.dump.apk" system.raw.img
debugfs -R "dump /lib/libmisc.so libmisc.dump.so" system.raw.img
debugfs -R "dump /etc/y2_boot_route_broker.sh broker.dump.sh" system.raw.img
cmp Rockbox.v87.apk Rockbox.dump.apk
cmp libmisc.so libmisc.dump.so
cmp y2_boot_route_broker.sh broker.dump.sh
debugfs -R "stat /etc/y2_boot_route_broker.sh" system.raw.img \
    > broker-stat.txt
grep -q "Mode:  0644" broker-stat.txt
debugfs -R "ea_list /etc/y2_boot_route_broker.sh" system.raw.img \
    > broker-xattr.txt
grep -q "u:object_r:system_file:s0" broker-xattr.txt
popd >/dev/null

e2fsck -n -f "$OUT/system.raw.img" > "$OUT/e2fsck.txt"
LD_LIBRARY_PATH="$LIBSPARSE_LIB" "$LIBSPARSE_BIN/img2simg" \
    "$OUT/system.raw.img" "$OUT/system.fill.img"
python3 "$ROOT/00_tools/y2_sparse_compat.py" "$OUT/system.fill.img" \
    --rewrite-no-fill "$OUT/system.img" > "$OUT/sparse_rewrite.txt"
python3 "$ROOT/00_tools/y2_sparse_compat.py" "$OUT/system.img" \
    > "$OUT/sparse_analysis.txt"
sha256sum "$OUT/system.img" > "$OUT/system.img.sha256.txt"
