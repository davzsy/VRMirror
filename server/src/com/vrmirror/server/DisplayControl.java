package com.vrmirror.server;

import android.graphics.Rect;
import android.os.IBinder;
import android.view.Surface;

import java.lang.reflect.Method;

/**
 * Access to the display mirroring APIs.
 *
 * Everything here is @hide in the platform, so it is reached by reflection
 * rather than linked against. That keeps the build to a plain public android.jar
 * and, more importantly, lets one binary work across Android versions that moved
 * these methods around. Two shapes are supported:
 *
 *   API 29 and later: SurfaceControl.Transaction instance methods
 *   API 21 to 30:     the global SurfaceControl.openTransaction static methods
 *
 * The shell user is allowed to do this. That is the whole trick behind Vysor,
 * scrcpy and friends: no APK is installed, the mirroring runs with the same
 * privileges adb already has.
 */
final class DisplayControl {

    private static final String SURFACE_CONTROL = "android.view.SurfaceControl";

    private DisplayControl() {
    }

    // ------------------------------------------------------------------ size

    static Size physicalSize() throws Exception {
        try {
            Class<?> global = Class.forName("android.hardware.display.DisplayManagerGlobal");
            Object instance = global.getMethod("getInstance").invoke(null);
            Object info = global.getMethod("getDisplayInfo", int.class).invoke(instance, 0);
            if (info != null) {
                int width = info.getClass().getField("logicalWidth").getInt(info);
                int height = info.getClass().getField("logicalHeight").getInt(info);
                if (width > 0 && height > 0) {
                    return new Size(width, height);
                }
            }
        } catch (Throwable ignored) {
            // Fall through to the SurfaceControl path.
        }

        Class<?> surfaceControl = Class.forName(SURFACE_CONTROL);
        IBinder token = builtInDisplayToken(surfaceControl);
        if (token != null) {
            try {
                Method getInfo = surfaceControl.getMethod("getDisplayInfo", IBinder.class);
                Object info = getInfo.invoke(null, token);
                if (info != null) {
                    int width = info.getClass().getField("width").getInt(info);
                    int height = info.getClass().getField("height").getInt(info);
                    if (width > 0 && height > 0) {
                        return new Size(width, height);
                    }
                }
            } catch (Throwable ignored) {
            }
        }

        throw new IllegalStateException(
                "could not determine the display size; pass size=WxH explicitly");
    }

    private static IBinder builtInDisplayToken(Class<?> surfaceControl) {
        try {
            // API 29+
            Method ids = surfaceControl.getMethod("getPhysicalDisplayIds");
            long[] displayIds = (long[]) ids.invoke(null);
            if (displayIds != null && displayIds.length > 0) {
                Method token = surfaceControl.getMethod("getPhysicalDisplayToken", long.class);
                return (IBinder) token.invoke(null, displayIds[0]);
            }
        } catch (Throwable ignored) {
        }
        try {
            // API 21 to 28
            Method builtIn = surfaceControl.getMethod("getBuiltInDisplay", int.class);
            return (IBinder) builtIn.invoke(null, 0);
        } catch (Throwable ignored) {
        }
        return null;
    }

    // --------------------------------------------------------------- display

    static IBinder createVirtualDisplay(
            String name, Surface surface, Size source, Size target) throws Exception {

        Class<?> surfaceControl = Class.forName(SURFACE_CONTROL);
        Method create = surfaceControl.getMethod("createDisplay", String.class, boolean.class);
        IBinder display = (IBinder) create.invoke(null, name, false);
        if (display == null) {
            throw new IllegalStateException("SurfaceControl.createDisplay returned null");
        }

        Rect sourceRect = new Rect(0, 0, source.width, source.height);
        Rect targetRect = new Rect(0, 0, target.width, target.height);

        if (!applyWithTransaction(surfaceControl, display, surface, sourceRect, targetRect)
                && !applyWithGlobals(surfaceControl, display, surface, sourceRect, targetRect)) {
            destroyVirtualDisplay(display);
            throw new IllegalStateException(
                    "this Android version does not expose a usable SurfaceControl "
                            + "transaction API; use the screenrecord engine instead");
        }
        return display;
    }

    private static boolean applyWithTransaction(
            Class<?> surfaceControl, IBinder display, Surface surface, Rect source, Rect target) {
        try {
            Class<?> transactionClass = Class.forName(SURFACE_CONTROL + "$Transaction");
            Object transaction = transactionClass.getConstructor().newInstance();
            try {
                transactionClass
                        .getMethod("setDisplaySurface", IBinder.class, Surface.class)
                        .invoke(transaction, display, surface);
                transactionClass
                        .getMethod(
                                "setDisplayProjection",
                                IBinder.class, int.class, Rect.class, Rect.class)
                        .invoke(transaction, display, 0, source, target);
                transactionClass
                        .getMethod("setDisplayLayerStack", IBinder.class, int.class)
                        .invoke(transaction, display, 0);
                transactionClass.getMethod("apply").invoke(transaction);
                return true;
            } finally {
                try {
                    transactionClass.getMethod("close").invoke(transaction);
                } catch (Throwable ignored) {
                }
            }
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static boolean applyWithGlobals(
            Class<?> surfaceControl, IBinder display, Surface surface, Rect source, Rect target) {
        try {
            surfaceControl.getMethod("openTransaction").invoke(null);
            try {
                surfaceControl
                        .getMethod("setDisplaySurface", IBinder.class, Surface.class)
                        .invoke(null, display, surface);
                surfaceControl
                        .getMethod(
                                "setDisplayProjection",
                                IBinder.class, int.class, Rect.class, Rect.class)
                        .invoke(null, display, 0, source, target);
                surfaceControl
                        .getMethod("setDisplayLayerStack", IBinder.class, int.class)
                        .invoke(null, display, 0);
            } finally {
                surfaceControl.getMethod("closeTransaction").invoke(null);
            }
            return true;
        } catch (Throwable ignored) {
            return false;
        }
    }

    static void destroyVirtualDisplay(IBinder display) {
        if (display == null) {
            return;
        }
        try {
            Class.forName(SURFACE_CONTROL)
                    .getMethod("destroyDisplay", IBinder.class)
                    .invoke(null, display);
        } catch (Throwable ignored) {
        }
    }
}
