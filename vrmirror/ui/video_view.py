"""The video surface.

Cropping happens here rather than in the decoder on purpose: QPainter can draw
a sub-rectangle of the source image at no extra cost, so the crop can be
adjusted live, with instant feedback and without disturbing the pipeline or
losing resolution. That matters for headsets, where finding the right crop is
trial and error.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

PLACEHOLDER = (
    "No stream.\n\n"
    "Connect a device on the left, then press Start mirroring."
)


class VideoView(QWidget):
    tapped = Signal(int, int)  # device pixel coordinates
    swiped = Signal(int, int, int, int)
    doubleClicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._crop = QRect()  # empty means "use the whole frame"
        self._fit_mode = "fit"
        self._smooth = True
        self._press_point: QPointF | None = None
        self._show_crop_guide = False

        self.setMinimumSize(360, 240)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(False)

    # ------------------------------------------------------------------ state

    @property
    def has_frame(self) -> bool:
        return self._image is not None

    @property
    def frame(self) -> QImage | None:
        return self._image

    @property
    def frame_size(self) -> tuple[int, int]:
        if self._image is None:
            return (0, 0)
        return (self._image.width(), self._image.height())

    def set_frame(self, image: QImage) -> None:
        self._image = image
        self.update()

    def clear(self) -> None:
        self._image = None
        self.update()

    def set_fit_mode(self, mode: str) -> None:
        self._fit_mode = mode if mode in ("fit", "fill", "actual") else "fit"
        self.update()

    def set_smooth(self, smooth: bool) -> None:
        self._smooth = bool(smooth)
        self.update()

    def set_crop_guide(self, visible: bool) -> None:
        self._show_crop_guide = bool(visible)
        self.update()

    # ------------------------------------------------------------------- crop

    @property
    def crop(self) -> QRect:
        return QRect(self._crop)

    def set_crop(self, rect: QRect | list[int] | None) -> None:
        if rect is None:
            self._crop = QRect()
        elif isinstance(rect, QRect):
            self._crop = QRect(rect)
        else:
            x, y, w, h = rect
            self._crop = QRect(int(x), int(y), int(w), int(h))
        self.update()

    def source_rect(self) -> QRect:
        if self._image is None:
            return QRect()
        full = QRect(0, 0, self._image.width(), self._image.height())
        if self._crop.isEmpty():
            return full
        clipped = self._crop.intersected(full)
        return clipped if not clipped.isEmpty() else full

    def auto_crop(self, threshold: int = 22) -> QRect | None:
        """Find the bounding box of non-black pixels in the current frame.

        Sampling a downscaled copy keeps this to a few thousand pixel reads, so
        it runs instantly even on a 4K source. The result is snapped outwards to
        even coordinates with a small margin, since headset compositors often
        leave a faint gradient at the edge of the rendered area.
        """
        if self._image is None:
            return None

        probe_size = 160
        small = self._image.scaled(
            probe_size, probe_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        ).convertToFormat(QImage.Format_RGB32)
        if small.isNull() or small.width() < 4 or small.height() < 4:
            return None

        left, top = small.width(), small.height()
        right, bottom = -1, -1
        for y in range(small.height()):
            for x in range(small.width()):
                pixel = small.pixel(x, y)
                luma = (
                    ((pixel >> 16) & 0xFF) * 299
                    + ((pixel >> 8) & 0xFF) * 587
                    + (pixel & 0xFF) * 114
                ) // 1000
                if luma >= threshold:
                    if x < left:
                        left = x
                    if x > right:
                        right = x
                    if y < top:
                        top = y
                    if y > bottom:
                        bottom = y

        if right < 0 or bottom < 0:
            return None

        scale_x = self._image.width() / small.width()
        scale_y = self._image.height() / small.height()
        margin = 1

        x0 = max(0, int((left - margin) * scale_x))
        y0 = max(0, int((top - margin) * scale_y))
        x1 = min(self._image.width(), int((right + 1 + margin) * scale_x))
        y1 = min(self._image.height(), int((bottom + 1 + margin) * scale_y))

        width = max(2, (x1 - x0) & ~1)
        height = max(2, (y1 - y0) & ~1)
        rect = QRect(x0 & ~1, y0 & ~1, width, height)

        full = QRect(0, 0, self._image.width(), self._image.height())
        if rect == full or rect.width() < 16 or rect.height() < 16:
            return None
        return rect

    def crop_to_left_eye(self) -> QRect | None:
        """Halve the current view horizontally: the usual stereo split."""
        source = self.source_rect()
        if source.isEmpty() or source.width() < 32:
            return None
        return QRect(source.x(), source.y(), (source.width() // 2) & ~1, source.height())

    # ---------------------------------------------------------------- drawing

    def target_rect(self) -> QRectF:
        source = self.source_rect()
        if source.isEmpty():
            return QRectF()

        widget_w = float(self.width())
        widget_h = float(self.height())
        src_w = float(source.width())
        src_h = float(source.height())

        if self._fit_mode == "actual":
            width, height = src_w, src_h
        else:
            scale_w = widget_w / src_w
            scale_h = widget_h / src_h
            scale = max(scale_w, scale_h) if self._fit_mode == "fill" else min(scale_w, scale_h)
            width = src_w * scale
            height = src_h * scale

        return QRectF((widget_w - width) / 2.0, (widget_h - height) / 2.0, width, height)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

        if self._image is None:
            painter.setPen(QPen(QColor("#6b7382")))
            font = QFont(painter.font())
            font.setPointSize(12)
            painter.setFont(font)
            painter.drawText(self.rect().adjusted(24, 24, -24, -24), Qt.AlignCenter, PLACEHOLDER)
            painter.end()
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._smooth)
        target = self.target_rect()
        source = self.source_rect()
        painter.drawImage(target, self._image, QRectF(source))

        if self._show_crop_guide and not self._crop.isEmpty():
            painter.setPen(QPen(QColor("#4c8dff"), 1, Qt.DashLine))
            painter.drawRect(target.adjusted(0.5, 0.5, -0.5, -0.5))

        painter.end()

    # ----------------------------------------------------------------- input

    def _to_device(self, position: QPointF) -> tuple[int, int] | None:
        target = self.target_rect()
        if target.isEmpty() or not target.contains(QPointF(position)):
            return None
        source = self.source_rect()
        fx = (position.x() - target.x()) / target.width()
        fy = (position.y() - target.y()) / target.height()
        return (
            int(source.x() + fx * source.width()),
            int(source.y() + fy * source.height()),
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_point = QPointF(event.position())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or self._press_point is None:
            return
        start = self._press_point
        self._press_point = None
        end = QPointF(event.position())

        start_device = self._to_device(start)
        end_device = self._to_device(end)
        if start_device is None or end_device is None:
            return

        distance = (start - end).manhattanLength()
        if distance < 12:
            self.tapped.emit(*start_device)
        else:
            self.swiped.emit(*start_device, *end_device)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
