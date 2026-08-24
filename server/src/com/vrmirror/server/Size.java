package com.vrmirror.server;

final class Size {
    final int width;
    final int height;

    Size(int width, int height) {
        this.width = width;
        this.height = height;
    }

    /** H.264 encoders require even dimensions. */
    Size evened() {
        return new Size(Math.max(2, width & ~1), Math.max(2, height & ~1));
    }

    Size fitInside(int maxDimension) {
        int longest = Math.max(width, height);
        if (longest <= maxDimension) {
            return this;
        }
        double scale = (double) maxDimension / longest;
        return new Size((int) (width * scale), (int) (height * scale));
    }

    @Override
    public String toString() {
        return width + "x" + height;
    }
}
