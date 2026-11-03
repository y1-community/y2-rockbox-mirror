#!/usr/bin/env bash
set -euo pipefail

# Build the Y2 Rockbox UI simulator without changing the Android APK build
# cache. The SDL packages are unpacked into the user's home directory, so this
# script does not require sudo.

WINDOWS_REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK_ROOT="$HOME/work/y2-rockbox-simulator"
SRC_COPY="$WORK_ROOT/src"
BUILD_DIR="$WORK_ROOT/build"
DEPS_ROOT="$WORK_ROOT/deps"
DEB_CACHE="$WORK_ROOT/debs"
OUT="$WINDOWS_REPO/12_build_outputs/y2-simulator"
SIM_ROOT="$OUT/root"
Y2_RESOURCE_ZIP="$WINDOWS_REPO/12_build_outputs/rockbox-android-y2-v54/rockbox-y2-v54-full.zip"

export ANDROID_SDK_PATH="$HOME/android/android-sdk"
export ANDROID_NDK_PATH="$HOME/android/android-ndk-r10e"

mkdir -p "$WORK_ROOT" "$OUT"
if [ "${Y2_SIM_USE_STAGED:-0}" != "1" ]; then
    rsync -a --delete \
        "$WINDOWS_REPO/11_rockbox_android/rockbox-y1/" "$SRC_COPY/"
elif [ ! -f "$SRC_COPY/tools/configure" ]; then
    echo "The staged source does not exist at $SRC_COPY" >&2
    exit 2
fi
find "$SRC_COPY" -type f \
    \( -name "*.sh" -o -name "configure" -o -name "*.mk" \
       -o -name "*.make" -o -name "*.pl" -o -name "*.pm" \) \
    -print0 | xargs -0 dos2unix -q || true
sed -i 's/--system=windows-x86_64/--system=linux-x86_64/g' \
    "$SRC_COPY/tools/configure"

if [ ! -x "$DEPS_ROOT/usr/bin/sdl2-config" ] ||
   [ ! -x "$DEPS_ROOT/usr/bin/pkg-config" ]; then
    mkdir -p "$DEPS_ROOT" "$DEB_CACHE"
    cd "$DEB_CACHE"
    rm -f ./*.deb
    apt-get download \
        libsdl1.2-dev \
        libsdl1.2debian \
        libsdl2-2.0-0 \
        libsdl2-classic \
        libsdl2-dev \
        libdecor-0-0 \
        libsamplerate0 \
        libxss1 \
        libpkgconf7 \
        pkgconf \
        pkgconf-bin
    for deb in ./*.deb; do
        dpkg-deb -x "$deb" "$DEPS_ROOT"
    done
    sed -i "s|^prefix=/usr$|prefix=$DEPS_ROOT/usr|" \
        "$DEPS_ROOT/usr/bin/sdl-config" \
        "$DEPS_ROOT/usr/bin/sdl2-config"
fi

export PATH="$DEPS_ROOT/usr/bin:$PATH"
export C_INCLUDE_PATH="$DEPS_ROOT/usr/include:$DEPS_ROOT/usr/include/x86_64-linux-gnu${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
export LIBRARY_PATH="$DEPS_ROOT/usr/lib/x86_64-linux-gnu${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$DEPS_ROOT/usr/lib/x86_64-linux-gnu:$DEPS_ROOT/usr/lib/x86_64-linux-gnu/sdl2-classic${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PKG_CONFIG_PATH="$DEPS_ROOT/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
"$SRC_COPY/tools/configure" \
    --target=android \
    --lcdwidth=480 \
    --lcdheight=360 \
    --type=s
make -j"$(nproc)" bin codecs

if [ ! -x "$BUILD_DIR/rockboxui" ]; then
    echo "Simulator build did not create $BUILD_DIR/rockboxui" >&2
    exit 2
fi

mkdir -p "$SIM_ROOT/.rockbox/codecs"
if [ -f "$Y2_RESOURCE_ZIP" ]; then
    unzip -oq "$Y2_RESOURCE_ZIP" \
        '.rockbox/*.cfg' \
        '.rockbox/backdrops/*' \
        '.rockbox/fonts/*' \
        '.rockbox/icons/*' \
        '.rockbox/langs/*' \
        '.rockbox/themes/*' \
        '.rockbox/wps/*' \
        -d "$SIM_ROOT"
fi
find "$BUILD_DIR/lib/rbcodec/codecs" -maxdepth 1 -name "*.codec" \
    -exec cp {} "$SIM_ROOT/.rockbox/codecs/" \;

"$BUILD_DIR/rockboxui" --help > "$OUT/help.txt"
cp "$BUILD_DIR/rockboxui" "$OUT/rockbox-y2-simulator"
cp "$BUILD_DIR/rockbox.map" "$OUT/rockbox-y2-simulator.map"
sha256sum "$OUT/rockbox-y2-simulator" > "$OUT/SHA256SUMS.txt"

echo "Built simulator: $OUT/rockbox-y2-simulator"
