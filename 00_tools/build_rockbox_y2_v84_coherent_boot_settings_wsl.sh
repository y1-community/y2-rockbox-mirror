#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK_ROOT="$HOME/work/y2-rockbox"
SRC_COPY="$WORK_ROOT/11_rockbox_android/rockbox-y1"
BUILD_DIR="$WORK_ROOT/12_build_outputs/rockbox-android-y2-build-v29"
OUT="$ROOT/build-intermediates/rockbox-android-y2-v84-coherent-boot-settings"
APK_NAME="rockbox-y2-v84-coherent-boot-settings.apk"
FULL_NAME="rockbox-y2-v84-full.zip"
STABLE_APK="$ROOT/12_build_outputs/rockbox-android-y2-v65/rockbox-y2-v65-android-unplug-reassert.apk"
BASE_FULL="$ROOT/build-intermediates/rockbox-android-y2-v81-continuous-handoff/rockbox-y2-v81-full.zip"

export ANDROID_SDK_PATH="$HOME/android/android-sdk"
export ANDROID_NDK_PATH="$HOME/android/android-ndk-r10e"
export JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
export PATH="$JAVA_HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$ANDROID_SDK_PATH/platform-tools:$ANDROID_SDK_PATH/build-tools/19.1.0"
export VERSION="-260728"

for required in "$BUILD_DIR/Makefile" "$STABLE_APK" "$BASE_FULL"; do
    test -f "$required" || {
        echo "Missing required input: $required" >&2
        exit 2
    }
done
case "$OUT" in
    "$ROOT/build-intermediates/rockbox-android-y2-v84-coherent-boot-settings") ;;
    *)
        echo "Refusing unsafe V84 Android output path: $OUT" >&2
        exit 2
        ;;
esac

rm -rf "$OUT"
mkdir -p "$WORK_ROOT/11_rockbox_android" "$OUT" "$BUILD_DIR/bin"
rsync -a --delete --exclude ".git/" \
    "$ROOT/11_rockbox_android/rockbox-y1/" "$SRC_COPY/"
find "$SRC_COPY" -type f \
        \( -name "*.sh" -o -name "configure" -o -name "*.mk" \
           -o -name "*.make" -o -name "*.pl" -o -name "*.pm" \) \
        -print0 | xargs -0 dos2unix -q || true
sed -i 's/--system=windows-x86_64/--system=linux-x86_64/g' \
    "$SRC_COPY/tools/configure"

cd "$BUILD_DIR"
cp "$BASE_FULL" rockbox-full.zip
rm -f bin/AndroidManifest.xml bin/classes.jar bin/classes.dex \
    bin/_rockbox.apk bin/__rockbox.apk rockbox.apk
rm -rf bin/classes/org/rockbox
make BUILDDATE='-DYEAR=2026 -DMONTH=07 -DDAY=28' apk

python3 - rockbox.apk "$STABLE_APK" bin/v84-unsigned.apk <<'PY'
import sys
import zipfile

current_path, stable_path, output_path = sys.argv[1:4]
with zipfile.ZipFile(stable_path) as stable:
    stable_native = {
        name: stable.read(name)
        for name in stable.namelist()
        if name.startswith("lib/armeabi/")
        and name.endswith(".so")
        and name != "lib/armeabi/libmisc.so"
    }
with zipfile.ZipFile(current_path) as source, zipfile.ZipFile(
        output_path, "w"
    ) as output:
    for source_info in source.infolist():
        name = source_info.filename
        if name.startswith("META-INF/"):
            continue
        data = stable_native.get(name, source.read(name))
        info = zipfile.ZipInfo(name, (2026, 7, 28, 22, 45, 0))
        info.compress_type = source_info.compress_type
        info.external_attr = source_info.external_attr
        info.internal_attr = source_info.internal_attr
        info.create_system = source_info.create_system
        info.flag_bits = source_info.flag_bits & ~0x08
        output.writestr(info, data)
PY

jarsigner -keystore "$HOME/.android/debug.keystore" \
    -storepass android -keypass android \
    -signedjar bin/v84-signed.apk bin/v84-unsigned.apk androiddebugkey \
    -sigalg SHA1withRSA -digestalg SHA1

python3 - bin/v84-signed.apk bin/v84-signed-normalized.apk <<'PY'
import sys
import zipfile

source_path, output_path = sys.argv[1:3]
with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(
        output_path, "w"
    ) as output:
    for source_info in source.infolist():
        info = zipfile.ZipInfo(
            source_info.filename, (2026, 7, 28, 22, 50, 0)
        )
        info.compress_type = source_info.compress_type
        info.external_attr = source_info.external_attr
        info.internal_attr = source_info.internal_attr
        info.create_system = source_info.create_system
        info.flag_bits = source_info.flag_bits & ~0x08
        output.writestr(info, source.read(source_info.filename))
PY

"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 \
    bin/v84-signed-normalized.apk rockbox.apk

APK="$OUT/$APK_NAME"
cp rockbox.apk "$APK"
cp rockbox-full.zip "$OUT/$FULL_NAME"
jarsigner -verify "$APK" >/dev/null

python3 - "$STABLE_APK" "$APK" "$BASE_FULL" "$OUT/$FULL_NAME" <<'PY'
import hashlib
import io
import sys
import zipfile

old_apk, new_apk, base_full, new_full = sys.argv[1:5]

def native_payload(path):
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith("lib/armeabi/")
            and name.endswith(".so")
            and name != "lib/armeabi/libmisc.so"
        }

with zipfile.ZipFile(new_apk) as archive:
    if archive.testzip() is not None:
        raise SystemExit("V84 APK failed CRC")
    dex = archive.read("classes.dex")
    manifest = archive.read("AndroidManifest.xml")
    resources = archive.read("lib/armeabi/libmisc.so")
for token in (
    b"y2_rockbox_v84_coherent_boot_settings_marker.txt",
    b"y2-v84-coherent-boot-settings",
    b"content://org.rockbox.y2.bootroutes/status",
    b"protocol_version",
    b"broker_build",
    b"current_boot_id",
    b"Firmware update incomplete",
    b"Retry Firmware Check",
    b"boot-route IPC request submitted",
    b"boot-route IPC broker confirmed",
    b"Saved - restarting...",
):
    if token not in dex:
        raise SystemExit(f"V84 classes.dex token absent: {token!r}")
for token in (
    "android.intent.category.HOME",
    "org.rockbox.y2.bootroutes",
    "Y2BootRouteProvider",
):
    if token.encode("utf-16le") not in manifest:
        raise SystemExit(f"V84 binary manifest token absent: {token}")
if native_payload(old_apk) != native_payload(new_apk):
    raise SystemExit("V84 unexpectedly changed stable playback libraries")
if open(base_full, "rb").read() != open(new_full, "rb").read():
    raise SystemExit("V84 full Rockbox resource ZIP drifted from V81")
with zipfile.ZipFile(io.BytesIO(resources)) as resource_zip:
    if b"%Vi(menu,0,48,480,268,-)" not in resource_zip.read(
            ".rockbox/wps/OneBitMono.sbs"):
        raise SystemExit("V84 lost the full-width OneBitMono viewport")
print("verified V84 boot-ID handshake, coherence gate and stable playback/resources")
PY

(cd "$OUT" && sha256sum "$APK_NAME" "$FULL_NAME" > SHA256SUMS.txt)
