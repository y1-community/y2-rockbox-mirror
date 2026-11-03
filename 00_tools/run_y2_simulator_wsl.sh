#!/usr/bin/env bash
set -euo pipefail

WINDOWS_REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEPS_ROOT="$HOME/work/y2-rockbox-simulator/deps"
SIMULATOR="$WINDOWS_REPO/12_build_outputs/y2-simulator/rockbox-y2-simulator"

if [ ! -x "$SIMULATOR" ]; then
    echo "Simulator is not built. Run 00_tools/build_y2_simulator_wsl.sh first." >&2
    exit 2
fi

export LD_LIBRARY_PATH="$DEPS_ROOT/usr/lib/x86_64-linux-gnu:$DEPS_ROOT/usr/lib/x86_64-linux-gnu/sdl2-classic${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

cd "$WINDOWS_REPO/12_build_outputs/y2-simulator"
exec "$SIMULATOR" \
    --nobackground \
    --root "$WINDOWS_REPO/12_build_outputs/y2-simulator/root" \
    "$@"
