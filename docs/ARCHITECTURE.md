# How VRMirror works

## The short version

Android has a hardware H.264 encoder and a way to point a display at it. ADB has
a way to carry arbitrary bytes between the device and the computer. Screen
mirroring is those two facts, plus a decoder on this end.

That is all Vysor is doing too. Its license check is a business decision layered
on top, not something the mirroring needs. Once you build the pipeline yourself,
there is nothing left to phone home about.

## The pipeline

```
   device                                    computer
   ------                                    --------
   display 0
      │  SurfaceControl / screenrecord
      ▼
   MediaCodec (hardware H.264)
      │  Annex-B elementary stream
      ▼
   adb socket  ────────────────────────▶  AdbConnection (raw bytes)
                                              │
                                              ├──▶ NalScanner ──▶ Recorder ──▶ .mp4
                                              │
                                              ▼
                                          libavcodec (PyAV)
                                              │  YUV frames
                                              ▼
                                          swscale ──▶ RGB ──▶ QImage
                                              │
                                              ▼
                                          QPainter (crop + scale) ──▶ window
```

Everything from the socket read to the QImage runs on one worker thread. Frames
cross to the UI thread as Qt queued signals.

## Talking to ADB

`vrmirror/adb/protocol.py` speaks the adb server's wire protocol directly over
TCP to `127.0.0.1:5037` instead of shelling out to `adb` per command.

Requests are `"%04x" % len(payload)` followed by the payload; replies start
`OKAY` or `FAIL`. Host services such as `host:devices-l` answer and close.
Device services need `host:transport:<serial>` first, after which the same
socket carries the service, for example `shell:` or `exec:`.

Three of those services carry the whole application:

- **`exec:`** gives a raw binary stdout stream with no pty, which is what the
  screenrecord engine reads video from. Using `shell:` instead would risk
  newline translation mangling the H.264.
- **`host:track-devices-l`** pushes a new device list whenever anything is
  plugged in, unplugged or authorised. The UI never polls.
- **`reverse:forward:`** maps a device-side abstract socket back to a port on
  this machine, which is how the native server reaches us without opening a
  port on the device.

## Capture engine 1: screenrecord

`screenrecord --output-format=h264 ... -` writes an elementary stream to stdout.
Every Android build ships it, so nothing is installed on the device, which makes
it the right default.

Two wrinkles are handled in `engines.py`:

- Many builds cap `--time-limit` at 180 seconds and refuse to start if you ask
  for more. VRMirror asks for the configured value, and if the first attempt
  produces zero bytes it retries at 180 and remembers.
- When a segment ends the stream is restarted transparently. The session yields
  `None` at that boundary so the decoder is reset before new parameter sets
  arrive.

The cost is latency. `screenrecord` is a recording tool: it buffers, and it uses
a 10 second keyframe interval that is wrong for live viewing.

## Capture engine 2: the native server

`server/` compiles to a `.dex` that is pushed to `/data/local/tmp` and run with
`app_process` as the **shell** user. Shell may talk to `SurfaceControl`, so the
server creates a virtual display, points it at a `MediaCodec` input surface and
writes encoded units to a reversed socket.

This is the technique Vysor and scrcpy both use, and it is where the low latency
lives: no intermediate buffering, a sane keyframe interval, no time limit.

Wire format:

```
header  "VRM1" width:uint32 height:uint32
frame   pts:uint64 length:uint32 payload:bytes
```

All the platform APIs involved are `@hide`, so they are reached by reflection.
That keeps the build to a public `android.jar` and lets one binary cover the
several times the platform moved these methods between versions.

## Decoding for latency, not throughput

`decoder.py` sets two things that matter for a live feed:

- `LOW_DELAY`, so the decoder does not hold frames back waiting for reordering
- **slice** threading rather than frame threading; frame threading buys
  parallelism by keeping several frames in flight, which is exactly the delay we
  are trying to avoid

The decoder is fed the raw socket chunks the instant they arrive, not parsed NAL
units, because libavcodec's parser already buffers internally and handing it
whole units first would add a frame of delay for nothing.

## Two paths for the same bytes

The stream is consumed twice, for different reasons:

- **Display** takes raw chunks, for the reason above.
- **Recording** takes the same bytes through `NalScanner`, which splits complete
  Annex-B units. A recording must begin with SPS, PPS and a keyframe or the
  first seconds are garbage. `RecordGate` caches the parameter sets it has
  already seen and splices them in front of the next keyframe, so recording
  starts cleanly without waiting out `screenrecord`'s 10 second keyframe gap.

Recording never re-encodes. Raw H.264 is written to disk, then remuxed into an
MP4 container on a background thread when you stop.

## Why cropping happens at paint time

A headset's display 0 is a wide compositor surface, usually letterboxed and
often stereo. You want a sub-rectangle of it.

Cropping in the decode path (an ffmpeg filter graph) would mean reconfiguring
the graph on every adjustment, with a visible hitch each time. `QPainter` can
draw a sub-rectangle of the source image at no extra cost, so `video_view.py`
crops at paint time instead: adjustments are instant, nothing upstream is
disturbed, and no resolution is lost.

`auto_crop()` finds the bounding box of non-black pixels. It samples a
downscaled copy, so it reads a few thousand pixels rather than several million
and returns instantly even on a 4K source.

## Backpressure

If the UI thread falls behind, the capture thread drops frames rather than
queueing them: at most two frames are allowed in flight. For a live view a
missed frame is always better than a stale one, and an unbounded signal queue
would turn a brief hitch into permanent lag.

## What is not implemented

- **Audio.** Android 11+ can capture playback audio through `AudioRecord` with
  `REMOTE_SUBMIX`, but the device server would have to grow a second stream and
  the client a synchronised audio path.
- **Keyboard and mouse injection.** Taps and swipes go through `input`, which is
  fine for menus but too slow for interaction. Real injection means
  `InputManager.injectInputEvent` in the device server.
- **Android 14+ display API.** `SurfaceControl`'s global transaction methods
  were removed; the `DisplayManagerGlobal` path is not written yet. Only relevant
  once headsets move past Android 12.
