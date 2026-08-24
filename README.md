# VRMirror

Mirror an Android device or a standalone VR headset to your computer. Free, and
fully offline: no account, no license server, no internet.

Built as a replacement for Vysor, whose only online requirement is checking a
license. The mirroring itself has never needed a network connection.

```
  headset ──USB or Wi-Fi──▶ adb ──H.264──▶ VRMirror ──▶ your screen
```

## What it does

- Live mirroring over USB or Wi-Fi, with the device's hardware H.264 encoder
- **Crop tools built for headsets**: auto-trim the black borders around the
  compositor output, or halve the view to a single eye, in one click
- Recording straight to MP4 with no re-encode, and PNG screenshots
- One-click untethering: switch a cabled device to Wi-Fi and unplug
- Click and drag on the video to tap and swipe on the device
- Fullscreen, always-on-top, per-device crop memory
- Packages into a single self-contained application

## Quick start (from source)

```sh
python -m pip install -r requirements.txt
python run.py
```

You also need `adb`. Either install Android platform-tools yourself, or let
VRMirror bundle its own copy:

```sh
python tools/fetch_adb.py
```

## Setting up a Quest

1. In the Meta Horizon phone app: **Devices → your headset → Headset settings →
   Developer mode → on**. This needs a (free) developer account once.
2. Plug the headset into the computer with a USB-C cable.
3. Put the headset on. Accept **Allow USB debugging** when it appears. Tick
   "always allow" so you are not asked again.
4. Launch VRMirror, pick the headset in the list, press **Start mirroring**.
5. Press **Auto-crop** once the picture appears. Headsets render a wide
   letterboxed surface; this trims it. **Left eye** halves a stereo view.

The crop is remembered per headset model, so step 5 is a one-time thing.

### Going wireless

With the headset still on USB, press **Untether selected device**. VRMirror
reads the headset's Wi-Fi address, restarts its adb in TCP mode and reconnects
over the network. Unplug the cable and carry on.

After a headset reboot, adb goes back to USB-only. Reconnect with **Connect IP**
using the same address, or plug in and untether again.

## Building a standalone app

```sh
python tools/build.py            # a folder in dist/, fastest to start
python tools/build.py --onefile  # a single file, a few seconds slower to launch
```

On Windows this produces `dist/VRMirror/VRMirror.exe` (or `dist/VRMirror.exe`
with `--onefile`). On macOS it produces `dist/VRMirror.app`.

**PyInstaller does not cross compile.** A Windows `.exe` has to be built on
Windows. If you develop on a Mac, push the repo to GitHub and let
`.github/workflows/build.yml` build both; the `.exe` shows up as a workflow
artifact, and tagging `v0.1.0` attaches it to a release.

## The two capture engines

| | screenrecord | native server |
| --- | --- | --- |
| Installs anything on the device | no | pushes a 30 KB file to `/data/local/tmp` |
| Latency | roughly 200 to 400 ms | roughly 60 to 120 ms |
| Session length | restarts every few minutes on some builds | unlimited |
| Needs to be built | no | yes, `server/build.sh` with an Android SDK |

`screenrecord` is the default and works out of the box on a stock headset. The
native server is the same technique Vysor and scrcpy use: see
[`server/README.md`](server/README.md) to build it, after which "Automatic"
prefers it. Everything works without it; you only pay in latency.

## Keyboard

| | |
| --- | --- |
| `Ctrl+R` | start or stop mirroring |
| `Ctrl+Shift+R` | start or stop recording |
| `Ctrl+S` | screenshot |
| `F11`, double click | fullscreen |
| `Esc` | leave fullscreen |

## Troubleshooting

**Device shows as `unauthorized`.** The debugging prompt is waiting inside the
headset. Put it on and accept.

**"screenrecord produced no video".** Something else already holds the encoder:
close the headset's own recording or casting session and try again. On a device
in use by another mirroring tool, close that first.

**Black picture, or a small image in a large black frame.** That is normal for a
headset. Press **Auto-crop**.

**Stuttering over Wi-Fi.** Lower **Max dimension** in Settings before lowering
the bitrate; resolution costs far more than bitrate on a congested network.

**Nothing in the device list.** Check `adb devices` in a terminal. If adb sees
nothing, the problem is the cable, the driver or developer mode, not VRMirror.
Logs are written to the config directory (`%APPDATA%\VRMirror` on Windows,
`~/Library/Application Support/VRMirror` on macOS).

## Tests

```sh
python -m unittest discover -s tests -v
```

These cover the protocol parsing and stream handling, and need neither Qt nor
ffmpeg installed.

## Layout

```
vrmirror/adb/       ADB server protocol, device operations, adb discovery
vrmirror/capture/   capture engines, H.264 handling, decoding, recording
vrmirror/ui/        Qt interface
server/             optional device-side server (Java, compiled to .dex)
tools/              build scripts
docs/               how it works, in more detail
```

## Licensing note

VRMirror's own code is yours to use. If you redistribute a build that bundles
`adb`, note that adb is covered by the Android SDK licence; for personal use
this is a non-issue, and you can always ship without `assets/platform-tools/`
and let users supply their own.
