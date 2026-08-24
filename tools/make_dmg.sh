#!/bin/bash
# Wrap dist/VRMirror.app in a compressed disk image with the usual
# drag-to-Applications layout. macOS only; uses hdiutil, which ships with the
# system, so there is nothing to install.
#
#     ./tools/make_dmg.sh [output.dmg]

set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
app="$root/dist/VRMirror.app"
output="${1:-$root/dist/VRMirror.dmg}"

if [ ! -d "$app" ]; then
    echo "no $app; run 'python tools/build.py' first" >&2
    exit 1
fi

version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/vrmirror/__init__.py")"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

# ditto rather than cp: it preserves the bundle's symlinks and signature.
ditto "$app" "$staging/VRMirror.app"
ln -s /Applications "$staging/Applications"

rm -f "$output"
hdiutil create \
    -volname "VRMirror ${version}" \
    -srcfolder "$staging" \
    -fs HFS+ \
    -format UDZO \
    -quiet \
    "$output"

echo "wrote $output"
