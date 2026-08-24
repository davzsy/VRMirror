#!/usr/bin/env bash
#
# Build the VRMirror device server into a single .dex.
#
# Requirements:
#   * a JDK (8 or newer)
#   * the Android SDK, with one platform and build-tools installed
#
# Point ANDROID_HOME at the SDK, or let the script guess the usual locations.
# The output lands in build/vrmirror-server.dex and is picked up automatically
# by the desktop app on the next launch.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

sdk="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -z "$sdk" ]; then
    for candidate in "$HOME/Library/Android/sdk" "$HOME/Android/Sdk" "/usr/local/lib/android/sdk"; do
        if [ -d "$candidate" ]; then sdk="$candidate"; break; fi
    done
fi
if [ -z "$sdk" ] || [ ! -d "$sdk" ]; then
    echo "Android SDK not found. Set ANDROID_HOME and try again." >&2
    echo "The desktop app works without this; it just falls back to screenrecord." >&2
    exit 1
fi

# Newest installed platform wins: the hidden APIs are reached by reflection, so
# the compile target only has to be recent enough for the public classes.
android_jar="$(ls -d "$sdk"/platforms/android-*/android.jar 2>/dev/null | sort -V | tail -1 || true)"
if [ -z "$android_jar" ]; then
    echo "No android.jar under $sdk/platforms. Install a platform with sdkmanager." >&2
    exit 1
fi

d8="$(ls -d "$sdk"/build-tools/*/d8 2>/dev/null | sort -V | tail -1 || true)"
if [ -z "$d8" ]; then
    echo "d8 not found under $sdk/build-tools. Install build-tools with sdkmanager." >&2
    exit 1
fi

echo "android.jar : $android_jar"
echo "d8          : $d8"

rm -rf build/classes
mkdir -p build/classes

javac \
    -source 8 -target 8 \
    -nowarn \
    -bootclasspath "$android_jar" \
    -cp "$android_jar" \
    -d build/classes \
    $(find src -name '*.java')

"$d8" \
    --release \
    --min-api 21 \
    --output build/ \
    $(find build/classes -name '*.class')

mv build/classes.dex build/vrmirror-server.dex

mkdir -p ../assets
cp build/vrmirror-server.dex ../assets/vrmirror-server.dex

echo
echo "Built: $(cd .. && pwd)/assets/vrmirror-server.dex"
echo "Restart VRMirror and pick the native engine in Settings."
