package com.vrmirror.server;

import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.IBinder;
import android.view.Surface;

import java.io.OutputStream;
import java.nio.ByteBuffer;

/**
 * VRMirror device server.
 *
 * Runs as the shell user through app_process, which is what makes this possible
 * without installing an APK: the shell user may talk to SurfaceControl and hand
 * the display to a hardware encoder.
 *
 * Flow:
 *   1. create a virtual display and point it at a MediaCodec input surface
 *   2. let the device's hardware H.264 encoder do all the work
 *   3. push the encoded Annex-B units through a reversed socket to the desktop
 *
 * Wire format:
 *   header: "VRM1" + width(uint32 BE) + height(uint32 BE)
 *   frame:  pts(uint64 BE) + length(uint32 BE) + payload
 */
public final class Main {

    private static final String MIME = "video/avc";
    private static final byte[] MAGIC = {'V', 'R', 'M', '1'};

    public static void main(String[] args) {
        // Uncaught exceptions in app_process would otherwise print nothing useful.
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            System.err.println("vrmirror: fatal: " + error);
            error.printStackTrace(System.err);
            System.exit(1);
        });

        Options options = Options.parse(args);
        try {
            run(options);
        } catch (Throwable error) {
            System.err.println("vrmirror: " + error);
            error.printStackTrace(System.err);
            System.exit(1);
        }
        System.exit(0);
    }

    private static void run(Options options) throws Exception {
        Size displaySize = DisplayControl.physicalSize();
        Size videoSize = options.videoSize(displaySize);

        MediaCodec codec = MediaCodec.createEncoderByType(MIME);
        MediaFormat format = MediaFormat.createVideoFormat(MIME, videoSize.width, videoSize.height);
        format.setInteger(MediaFormat.KEY_BIT_RATE, options.bitRate);
        format.setInteger(MediaFormat.KEY_FRAME_RATE, options.frameRate);
        format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2);
        format.setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
        // Without this the encoder emits nothing while the screen is static, and
        // a client that joins during a still moment would wait for the next move.
        format.setLong(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER, 100_000L);

        codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        Surface surface = codec.createInputSurface();

        IBinder display = DisplayControl.createVirtualDisplay(
                "vrmirror", surface, displaySize, videoSize);

        LocalSocket socket = connect(options.socketName);
        OutputStream out = socket.getOutputStream();
        writeHeader(out, videoSize);

        codec.start();
        try {
            encodeLoop(codec, out);
        } finally {
            try {
                codec.stop();
            } catch (Throwable ignored) {
            }
            codec.release();
            surface.release();
            DisplayControl.destroyVirtualDisplay(display);
            try {
                socket.close();
            } catch (Throwable ignored) {
            }
        }
    }

    private static LocalSocket connect(String name) throws Exception {
        // adb reverse maps this abstract socket back to the desktop client, so
        // no listening port is opened on the device itself.
        LocalSocket socket = new LocalSocket();
        socket.connect(new LocalSocketAddress(name, LocalSocketAddress.Namespace.ABSTRACT));
        return socket;
    }

    private static void writeHeader(OutputStream out, Size size) throws Exception {
        byte[] header = new byte[12];
        System.arraycopy(MAGIC, 0, header, 0, 4);
        putInt(header, 4, size.width);
        putInt(header, 8, size.height);
        out.write(header);
        out.flush();
    }

    private static void encodeLoop(MediaCodec codec, OutputStream out) throws Exception {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        byte[] meta = new byte[12];
        byte[] scratch = new byte[256 * 1024];

        while (true) {
            int index = codec.dequeueOutputBuffer(info, 500_000L);
            if (index == MediaCodec.INFO_TRY_AGAIN_LATER) {
                continue;
            }
            if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                continue;
            }
            if (index < 0) {
                continue;
            }

            try {
                if (info.size > 0) {
                    ByteBuffer buffer = codec.getOutputBuffer(index);
                    if (buffer != null) {
                        buffer.position(info.offset);
                        buffer.limit(info.offset + info.size);

                        if (scratch.length < info.size) {
                            scratch = new byte[info.size];
                        }
                        buffer.get(scratch, 0, info.size);

                        putLong(meta, 0, info.presentationTimeUs);
                        putInt(meta, 8, info.size);
                        out.write(meta);
                        out.write(scratch, 0, info.size);
                        out.flush();
                    }
                }
            } finally {
                codec.releaseOutputBuffer(index, false);
            }

            if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                return;
            }
        }
    }

    private static void putInt(byte[] target, int offset, int value) {
        target[offset] = (byte) (value >>> 24);
        target[offset + 1] = (byte) (value >>> 16);
        target[offset + 2] = (byte) (value >>> 8);
        target[offset + 3] = (byte) value;
    }

    private static void putLong(byte[] target, int offset, long value) {
        for (int i = 0; i < 8; i++) {
            target[offset + i] = (byte) (value >>> (56 - 8 * i));
        }
    }
}
