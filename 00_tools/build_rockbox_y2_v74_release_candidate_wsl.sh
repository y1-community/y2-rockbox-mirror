#!/usr/bin/env bash
set -euo pipefail

WINDOWS_REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK_ROOT="$HOME/work/y2-rockbox"
SRC_COPY="$WORK_ROOT/11_rockbox_android/rockbox-y1"
BUILD_DIR="$WORK_ROOT/12_build_outputs/rockbox-android-y2-build-v29"
OUT="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v74-release-candidate"
APK_NAME="rockbox-y2-v74-release-candidate.apk"
FULL_NAME="rockbox-y2-v74-full.zip"
STABLE_APK="$WINDOWS_REPO/12_build_outputs/rockbox-android-y2-v65/rockbox-y2-v65-android-unplug-reassert.apk"
BASE_FULL="/mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v71-wake-owner/rockbox-y2-v71-full.zip"
THEME_ROOT="/mnt/e/Y2-RockBox-build-intermediates/third-party-themes/Experimental-360p-Themes-Testing-03/OneBit_Mono_360p/.rockbox"

export ANDROID_SDK_PATH="$HOME/android/android-sdk"
export ANDROID_NDK_PATH="$HOME/android/android-ndk-r10e"
export JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
export PATH="$JAVA_HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$ANDROID_SDK_PATH/platform-tools:$ANDROID_SDK_PATH/build-tools/19.1.0"
export VERSION="-260722"

for required in "$BUILD_DIR/Makefile" "$STABLE_APK" "$BASE_FULL" \
        "$THEME_ROOT/themes/OneBitMono.cfg" "$THEME_ROOT/wps/OneBitMono.wps"; do
    test -f "$required" || { echo "Missing required input: $required" >&2; exit 2; }
done
case "$OUT" in
    /mnt/e/Y2-RockBox-build-intermediates/rockbox-android-y2-v74-release-candidate) ;;
    *) echo "Refusing unsafe V74 output path: $OUT" >&2; exit 2 ;;
esac
rm -rf "$OUT"
mkdir -p "$WORK_ROOT/11_rockbox_android" "$OUT" "$BUILD_DIR/bin"
rsync -a --delete "$WINDOWS_REPO/11_rockbox_android/rockbox-y1/" "$SRC_COPY/"
find "$SRC_COPY" -type f \( -name "*.sh" -o -name "configure" -o -name "*.mk" -o -name "*.make" -o -name "*.pl" -o -name "*.pm" \) -print0 |
    xargs -0 dos2unix -q || true
sed -i 's/--system=windows-x86_64/--system=linux-x86_64/g' "$SRC_COPY/tools/configure"

python3 - "$BASE_FULL" "$THEME_ROOT" "$BUILD_DIR/rockbox-full.zip" <<'PY'
import sys, zipfile
from pathlib import Path
base, theme, output = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
theme_files = sorted(p for p in theme.rglob('*') if p.is_file())
with zipfile.ZipFile(base) as source, zipfile.ZipFile(output, 'w') as target:
    names = set()
    for entry in source.infolist():
        if entry.filename.startswith('.rockbox/themes/OneBitMono') or entry.filename.startswith('.rockbox/wps/OneBitMono'):
            continue
        target.writestr(entry, source.read(entry.filename))
        names.add(entry.filename)
    for path in theme_files:
        name = '.rockbox/' + path.relative_to(theme).as_posix()
        if name in names:
            raise SystemExit(f'duplicate theme path: {name}')
        info = zipfile.ZipInfo(name, (2026, 7, 22, 0, 10, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        target.writestr(info, path.read_bytes())
with zipfile.ZipFile(output) as result:
    if result.testzip() is not None:
        raise SystemExit('merged Rockbox resource ZIP failed CRC')
    required = {
        '.rockbox/themes/OneBitMono.cfg',
        '.rockbox/wps/OneBitMono.wps',
        '.rockbox/wps/OneBitMono.sbs',
        '.rockbox/wps/OneBitMono/progressbar.bmp',
        '.rockbox/fonts/10-Sazanami-Mincho.fnt',
    }
    missing = sorted(required - set(result.namelist()))
    if missing:
        raise SystemExit(f'merged resource ZIP is incomplete: {missing}')
PY

cd "$BUILD_DIR"
rm -f bin/AndroidManifest.xml bin/classes.jar bin/classes.dex bin/_rockbox.apk bin/__rockbox.apk rockbox.apk
rm -rf bin/classes/org/rockbox
make BUILDDATE='-DYEAR=2026 -DMONTH=07 -DDAY=22' apk

python3 - rockbox.apk "$STABLE_APK" bin/v74-unsigned.apk <<'PY'
import sys, zipfile
current_path, stable_path, output_path = sys.argv[1:4]
with zipfile.ZipFile(stable_path) as stable:
    stable_native = {n: stable.read(n) for n in stable.namelist()
                     if n.startswith('lib/armeabi/') and n.endswith('.so')
                     and n != 'lib/armeabi/libmisc.so'}
with zipfile.ZipFile(current_path) as source, zipfile.ZipFile(output_path, 'w') as output:
    for source_info in source.infolist():
        name = source_info.filename
        if name.startswith('META-INF/'):
            continue
        data = stable_native.get(name, source.read(name))
        info = zipfile.ZipInfo(name, (2026, 7, 22, 0, 15, 0))
        info.compress_type = source_info.compress_type
        info.external_attr = source_info.external_attr
        info.internal_attr = source_info.internal_attr
        info.create_system = source_info.create_system
        info.flag_bits = source_info.flag_bits & ~0x08
        output.writestr(info, data)
PY

jarsigner -keystore "$HOME/.android/debug.keystore" -storepass android -keypass android \
    -signedjar bin/v74-signed.apk bin/v74-unsigned.apk androiddebugkey \
    -sigalg SHA1withRSA -digestalg SHA1
"$ANDROID_SDK_PATH/build-tools/19.1.0/zipalign" -f 4 bin/v74-signed.apk rockbox.apk

APK="$OUT/$APK_NAME"
cp rockbox.apk "$APK"
cp rockbox-full.zip "$OUT/$FULL_NAME"

python3 - "$STABLE_APK" "$APK" <<'PY'
import hashlib, sys, zipfile
old_apk, new_apk = sys.argv[1:3]
def native_payload(path):
    with zipfile.ZipFile(path) as z:
        return {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()
                if n.startswith('lib/armeabi/') and n.endswith('.so')
                and n != 'lib/armeabi/libmisc.so'}
with zipfile.ZipFile(new_apk) as z:
    names = set(z.namelist()); dex = z.read('classes.dex'); manifest = z.read('AndroidManifest.xml')
    resources = z.read('lib/armeabi/libmisc.so')
    bad = z.testzip()
if bad is not None:
    raise SystemExit(f'V74 APK failed CRC at {bad}')
for token in (b'ROUTE_SHIELD_NATIVE_EXIT_RECOVERY', b'native-exit-storage-ready',
              b'persist-boot-route-map', b'No button', b'Volume Up',
              b'Volume Down', b'Y2 Stock', b'OneBitMono'):
    if token not in dex:
        raise SystemExit(f'V74 classes.dex token absent: {token!r}')
if 'android.intent.category.HOME'.encode('utf-16le') in manifest:
    raise SystemExit('V74 must not declare an Android HOME candidate')
with zipfile.ZipFile(new_apk) as z, z.open('lib/armeabi/libmisc.so') as embedded:
    pass
with zipfile.ZipFile(new_apk) as z:
    resource_blob = z.read('lib/armeabi/libmisc.so')
import io
with zipfile.ZipFile(io.BytesIO(resource_blob)) as resource_zip:
    required = ('.rockbox/themes/OneBitMono.cfg', '.rockbox/wps/OneBitMono.wps',
                '.rockbox/wps/OneBitMono.sbs', '.rockbox/fonts/10-Sazanami-Mincho.fnt')
    for name in required:
        if name not in resource_zip.namelist():
            raise SystemExit(f'V74 embedded resources missing: {name}')
if native_payload(old_apk) != native_payload(new_apk):
    raise SystemExit('V74 unexpectedly changed playback native APK libraries')
print('verified V74 Java policy, no HOME filter, bundled OneBitMono and unchanged playback native libraries')
PY

(cd "$OUT" && sha256sum "$APK_NAME" "$FULL_NAME" > SHA256SUMS.txt)
