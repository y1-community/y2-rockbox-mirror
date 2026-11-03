#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="${1:-/mnt/e/Y2-RockBox-build-intermediates/v69-packaged-expanded.raw}"
EXPECTED_APK="$ROOT/12_build_outputs/rockbox-android-y2-v69/rockbox-y2-v69-route-owner.apk"
WORK="${2:-/tmp/y2-v69-packaged-system-validation}"

case "$WORK" in
    /tmp/y2-v69-*) ;;
    *)
        echo "Refusing unsafe validation work path: $WORK" >&2
        exit 2
        ;;
esac
rm -rf "$WORK"
mkdir -p "$WORK"
debugfs -R "dump /usr/keylayout/mtk-tpd.kl $WORK/mtk-tpd.kl" "$RAW"
debugfs -R "dump /usr/keylayout/mtk-tpd-kpd.kl $WORK/mtk-tpd-kpd.kl" "$RAW"
debugfs -R "dump /app/Rockbox.apk $WORK/Rockbox.apk" "$RAW"

grep -Eq '^key[[:space:]]+28[[:space:]]+ENTER[[:space:]]+WAKE_DROPPED$' \
    "$WORK/mtk-tpd.kl"
grep -Eq '^key[[:space:]]+28[[:space:]]+ENTER[[:space:]]+WAKE_DROPPED$' \
    "$WORK/mtk-tpd-kpd.kl"
cmp "$EXPECTED_APK" "$WORK/Rockbox.apk"
sha256sum "$WORK/mtk-tpd.kl" "$WORK/mtk-tpd-kpd.kl" "$WORK/Rockbox.apk"
