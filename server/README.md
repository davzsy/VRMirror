# Device server (optional, low latency)

This is the part that makes VRMirror behave like Vysor rather than like a
screen recorder. It is optional: without it the app falls back to the
`screenrecord` engine, which needs nothing on the device at all.

## What it does

`app_process` runs the compiled `.dex` on the device as the **shell** user. The
shell user is allowed to talk to `SurfaceControl`, so the server can:

1. create a virtual display that mirrors display 0,
2. point that display at the input surface of a hardware H.264 encoder,
3. write the encoded units to an abstract local socket, which `adb reverse` maps
   back to the desktop client.

Nothing is installed on the device. Nothing survives a reboot except a stray
file in `/data/local/tmp`. No account, no license check, no internet.

## Why it is faster than screenrecord

`screenrecord` is a recording tool that happens to be able to write to stdout.
It buffers, it caps each run at a few minutes on many builds, and it gives you
no control over the keyframe interval. Talking to the encoder directly removes
the buffering, removes the time limit, and sets a keyframe interval suited to a
live stream. Expect roughly 60 to 120 ms end to end on USB instead of 200 to
400 ms.

## Building

```sh
./build.sh
```

Requirements: a JDK and the Android SDK (one platform plus build-tools). The
script compiles with `javac` against the public `android.jar` and converts to
Dalvik bytecode with `d8`. All the hidden platform APIs are reached through
reflection, which is why a public `android.jar` is enough and why one build
works across Android versions.

The result is copied to `../assets/vrmirror-server.dex`. Restart VRMirror and it
will be detected; the engine selector in Settings switches from "not built" to
selectable, and "Automatic" starts preferring it.

## Compatibility

| Android | Path used |
| --- | --- |
| 10 and later (API 29+) | `SurfaceControl.Transaction` |
| 5 to 11 (API 21 to 30) | legacy global `SurfaceControl` transaction |
| 14 and later (API 34+) | may need the `DisplayManagerGlobal` path; not implemented yet |

Quest 2, Quest 3, Quest 3S and Quest Pro all run Android 12 based systems, so
the transaction path applies.

If the server fails to start, the app reports the error and you can fall back to
`screenrecord` in Settings without losing anything but latency.
