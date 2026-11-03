#!/usr/bin/env bash
set -euo pipefail

WINDOWS_REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK_ROOT="$HOME/work/y2-rockbox"
SRC_COPY="$WORK_ROOT/11_rockbox_android/rockbox-y1"
BUILD_DIR="$WORK_ROOT/12_build_outputs/rockbox-android-y2-build-v29"
OUT="$WINDOWS_REPO/12_build_outputs/rockbox-android-y2-v69"
STABLE_APK="$WINDOWS_REPO/12_build_outputs/rockbox-android-y2-v65/rockbox-y2-v65-android-unplug-reassert.apk"

export ANDROID_SDK_PATH="$HOME/android/android-sdk"
export ANDROID_NDK_PATH="$HOME/android/android-ndk-r10e"
export JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
export PATH="$JAVA_HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$ANDROID_SDK_PATH/platform-tools:$ANDROID_SDK_PATH/build-tools/19.1.0"
export VERSION="-260719"

for required in "$BUILD_DIR/Makefile" "$BUILD_DIR/rockbox-full.zip" "$STABLE_APK"; do
    if [ ! -f "$required" ]; then
        echo "Missing required input: $required" >&2
        exit 2
    fi
done

mkdir -p "$WORK_ROOT/11_rockbox_android" "$OUT"
rsync -a --delete "$WINDOWS_REPO/11_rockbox_android/rockbox-y1/" "$SRC_COPY/"
find "$SRC_COPY" -type f \( -name "*.sh" -o -name "configure" -o -name "*.mk" -o -name "*.make" -o -name "*.pl" -o -name "*.pm" \) -print0 |
    xargs -0 dos2unix -q || true
sed -i 's/--system=windows-x86_64/--system=linux-x86_64/g' "$SRC_COPY/tools/configure"

cd "$BUILD_DIR"
rm -f bin/AndroidManifest.xml bin/classes.jar bin/classes.dex bin/_rockbox.apk bin/__rockbox.apk rockbox.apk
rm -rf bin/classes/org/rockbox
make BUILDDATE='-DYEAR=2026 -DMONTH=07 -DDAY=19' apk

python3 - rockbox.apk "$STABLE_APK" bin/v69-unsigned.apk <<'PY'
import sys
import zipfile

current_path, stable_path, output_path = sys.argv[1:4]
with zipfile.ZipFile(stable_path) as stable:
    stable_native = {
        name: stable.read(name)
        for name in stable.namelist()
        if name.startswith("lib/armeabi/") and name.endswith(".so")
    }

with zipfile.ZipFile(current_path) as source, zipfile.ZipFile(
    output_path, "w"
) as output:
    for source_info in source.infolist():
        name = source_info.filename
        if name.startswith("META-INF/"):
            continue
        data = stable_native.get(name, source.read(name))
        info = zipfile.ZipInfo(name, (2026, 7, 19, 22, 0, 0))
        info.compress_type = source_info.compress_type
        info.external_attr = source_info.external_attr
        info.internal_attr = source_info.internal_attr
        info.create_system = source_info.create_system
        info.flag_bits = source_info.flag_bits & ~0x08
        output.writestr(info, data)
PY

jarsigner \
    -keystore "$HOME/.android/debug.keystore" \
    -storepass android -keypass android \
    -signedjar bin/v69-signed.apk bin/v69-unsigned.apk androiddebugkey \
    -sigalg SHA1withRSA -digestalg SHA1
"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 bin/v69-signed.apk rockbox.apk

python3 - rockbox.apk <<'PY'
import struct
import sys
import zipfile
from pathlib import Path

path = Path(sys.argv[1])
data = bytearray(path.read_bytes())
eocd = data.rfind(b"PK\x05\x06")
if eocd < 0:
    raise SystemExit("APK EOCD not found")
entry_count = struct.unpack_from("<H", data, eocd + 10)[0]
central = struct.unpack_from("<I", data, eocd + 16)[0]
dos_time = 22 << 11
dos_date = ((2026 - 1980) << 9) | (7 << 5) | 19
offset = central
for _ in range(entry_count):
    if data[offset:offset + 4] != b"PK\x01\x02":
        raise SystemExit(f"Bad central-directory entry at {offset}")
    name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, offset + 28)
    local = struct.unpack_from("<I", data, offset + 42)[0]
    if data[local:local + 4] != b"PK\x03\x04":
        raise SystemExit(f"Bad local-file entry at {local}")
    struct.pack_into("<HH", data, offset + 12, dos_time, dos_date)
    struct.pack_into("<HH", data, local + 10, dos_time, dos_date)
    offset += 46 + name_len + extra_len + comment_len
path.write_bytes(data)
with zipfile.ZipFile(path) as archive:
    bad = archive.testzip()
if bad is not None:
    raise SystemExit(f"Normalized APK failed CRC at {bad}")
PY

APK="$OUT/rockbox-y2-v69-route-owner.apk"
cp rockbox.apk "$APK"
cp rockbox-full.zip "$OUT/rockbox-y2-v69-full.zip"

python3 - "$STABLE_APK" "$APK" <<'PY'
import hashlib
import sys
import zipfile

old_apk, new_apk = sys.argv[1:3]

def payload(path, prefix):
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith(prefix)
        }

with zipfile.ZipFile(new_apk) as archive:
    names = set(archive.namelist())
    dex = archive.read("classes.dex")
    manifest = archive.read("AndroidManifest.xml")
    bad = archive.testzip()
if bad is not None:
    raise SystemExit(f"V69 APK failed CRC at {bad}")
for required in (
    "AndroidManifest.xml",
    "classes.dex",
    "lib/armeabi/librockbox.so",
    "lib/armeabi/libmisc.so",
):
    if required not in names:
        raise SystemExit(f"Missing V69 APK entry: {required}")
for token in (
    b"Y2RouteShieldService:single-owner launch",
    b"Y2StorageReceiver:UsbStorageActivity requested directly",
    b"RockboxFramebuffer:first frame signalled to route shield",
):
    if token not in dex:
        raise SystemExit(f"V69 classes.dex token absent: {token!r}")
if payload(old_apk, "lib/armeabi/") != payload(new_apk, "lib/armeabi/"):
    raise SystemExit("V69 unexpectedly changed native APK libraries")
print("verified V69 route-owner classes and unchanged native libraries")
PY

(cd "$OUT" && sha256sum rockbox-y2-v69-route-owner.apk rockbox-y2-v69-full.zip > SHA256SUMS.txt)
