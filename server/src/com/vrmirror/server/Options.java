package com.vrmirror.server;

/** key=value arguments passed on the app_process command line. */
final class Options {

    int bitRate = 12_000_000;
    int frameRate = 60;
    int maxSize = 0;
    Size explicitSize = null;
    String socketName = "vrmirror";

    static Options parse(String[] args) {
        Options options = new Options();
        for (String arg : args) {
            int separator = arg.indexOf('=');
            if (separator <= 0) {
                continue;
            }
            String key = arg.substring(0, separator);
            String value = arg.substring(separator + 1);
            try {
                switch (key) {
                    case "bitrate":
                        options.bitRate = Integer.parseInt(value);
                        break;
                    case "fps":
                        options.frameRate = Integer.parseInt(value);
                        break;
                    case "max_size":
                        options.maxSize = Integer.parseInt(value);
                        break;
                    case "socket":
                        options.socketName = value;
                        break;
                    case "size":
                        int x = value.indexOf('x');
                        if (x > 0) {
                            options.explicitSize = new Size(
                                    Integer.parseInt(value.substring(0, x)),
                                    Integer.parseInt(value.substring(x + 1)));
                        }
                        break;
                    default:
                        break;
                }
            } catch (NumberFormatException ignored) {
                // Keep the default rather than refusing to start.
            }
        }
        return options;
    }

    /** Encoder dimensions: explicit, capped by maxSize, or the display size. */
    Size videoSize(Size display) {
        if (explicitSize != null) {
            return explicitSize.evened();
        }
        if (maxSize > 0) {
            return display.fitInside(maxSize).evened();
        }
        return display.evened();
    }
}
