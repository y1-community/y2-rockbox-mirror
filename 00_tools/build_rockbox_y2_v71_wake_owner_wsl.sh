#!/usr/bin/env bash
set -euo pipefail

WINDOWS_REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK_ROOT="$HOME/work/y2-rockbox"
SRC_COPY="$WORK_ROOT/11_rockbox_android/rockbox-y1"
BUILD_DIR="$WORK_ROOT/12_build_outputs/rockbox-android-y2-build-v29"
OUT="${Y2_APK_OUT:-/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v71-wake-owner}"
APK_NAME="${Y2_APK_NAME:-rockbox-y2-v71-wake-owner.apk}"
FULL_NAME="${Y2_FULL_NAME:-rockbox-y2-v71-full.zip}"
STABLE_APK="$WINDOWS_REPO/12_build_outputs/rockbox-android-y2-v65/rockbox-y2-v65-android-unplug-reassert.apk"

export ANDROID_SDK_PATH="$HOME/android/android-sdk"
export ANDROID_NDK_PATH="$HOME/android/android-ndk-r10e"
export JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
export PATH="$JAVA_HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$ANDROID_SDK_PATH/platform-tools:$ANDROID_SDK_PATH/build-tools/19.1.0"
export VERSION="-260721"

for required in "$BUILD_DIR/Makefile" "$BUILD_DIR/rockbox-full.zip" "$STABLE_APK"; do
    test -f "$required" || { echo "Missing required input: $required" >&2; exit 2; }
done

case "$OUT" in
    /mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v71-wake-owner|\
    /mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v72-exclusive-home) ;;
    *) echo "Refusing unsafe V71 output path: $OUT" >&2; exit 2 ;;
esac
rm -rf "$OUT"
mkdir -p "$WORK_ROOT/11_rockbox_android" "$OUT"
rsync -a --delete "$WINDOWS_REPO/11_rockbox_android/rockbox-y1/" "$SRC_COPY/"
find "$SRC_COPY" -type f \( -name "*.sh" -o -name "configure" -o -name "*.mk" -o -name "*.make" -o -name "*.pl" -o -name "*.pm" \) -print0 |
    xargs -0 dos2unix -q || true
sed -i 's/--system=windows-x86_64/--system=linux-x86_64/g' "$SRC_COPY/tools/configure"

cd "$BUILD_DIR"
rm -f bin/AndroidManifest.xml bin/classes.jar bin/classes.dex bin/_rockbox.apk bin/__rockbox.apk rockbox.apk
rm -rf bin/classes/org/rockbox
make BUILDDATE='-DYEAR=2026 -DMONTH=07 -DDAY=21' apk

python3 - rockbox.apk "$STABLE_APK" bin/v71-unsigned.apk <<'PY'
import sys, zipfile
current_path, stable_path, output_path = sys.argv[1:4]
with zipfile.ZipFile(stable_path) as stable:
    stable_native = {n: stable.read(n) for n in stable.namelist()
                     if n.startswith("lib/armeabi/") and n.endswith(".so")}
with zipfile.ZipFile(current_path) as source, zipfile.ZipFile(output_path, "w") as output:
    for source_info in source.infolist():
        name = source_info.filename
        if name.startswith("META-INF/"):
            continue
        data = stable_native.get(name, source.read(name))
        info = zipfile.ZipInfo(name, (2026, 7, 21, 18, 0, 0))
        info.compress_type = source_info.compress_type
        info.external_attr = source_info.external_attr
        info.internal_attr = source_info.internal_attr
        info.create_system = source_info.create_system
        info.flag_bits = source_info.flag_bits & ~0x08
        output.writestr(info, data)
PY

jarsigner -keystore "$HOME/.android/debug.keystore" -storepass android -keypass android \
    -signedjar bin/v71-signed.apk bin/v71-unsigned.apk androiddebugkey \
    -sigalg SHA1withRSA -digestalg SHA1
"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 bin/v71-signed.apk rockbox.apk

APK="$OUT/$APK_NAME"
cp rockbox.apk "$APK"
cp rockbox-full.zip "$OUT/$FULL_NAME"

python3 - "$STABLE_APK" "$APK" <<'PY'
import hashlib, sys, zipfile
old_apk, new_apk = sys.argv[1:3]
def native_payload(path):
    with zipfile.ZipFile(path) as z:
        return {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()
                if n.startswith("lib/armeabi/") and n.endswith(".so")}
with zipfile.ZipFile(new_apk) as z:
    names = set(z.namelist()); dex = z.read("classes.dex"); manifest = z.read("AndroidManifest.xml")
    bad = z.testzip()
if bad is not None:
    raise SystemExit(f"V71 APK failed CRC at {bad}")
for required in ("AndroidManifest.xml", "classes.dex", "lib/armeabi/librockbox.so", "lib/armeabi/libmisc.so"):
    if required not in names: raise SystemExit(f"Missing V71 APK entry: {required}")
for token in (b"FirmwareRoute:screen-on reasserted Rockbox task ownership",
              b"RockboxFramebuffer:consumed orphan center key-up after WAKE_DROPPED wake",
              b"Y2RouteShieldService:ignore unarmed USB return begin"):
    if token not in dex: raise SystemExit(f"V71 classes.dex token absent: {token!r}")
if "android.intent.action.SCREEN_ON".encode("utf-16le") not in manifest:
    raise SystemExit("V71 manifest lacks SCREEN_ON receiver action")
if native_payload(old_apk) != native_payload(new_apk):
    raise SystemExit("V71 unexpectedly changed native APK libraries")
print("verified V71 wake ownership, orphan-key suppression, V70 USB guard, and unchanged native libraries")
PY

(cd "$OUT" && sha256sum "$APK_NAME" "$FULL_NAME" > SHA256SUMS.txt)
