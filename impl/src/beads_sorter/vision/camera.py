"""Shared Pi Camera capture service for preview and color sampling."""

from collections.abc import Iterator
from dataclasses import dataclass
from threading import Condition, Event, Thread
from time import monotonic

import cv2
import numpy as np

from beads_sorter.vision.color import RGB

DEFAULT_BACKGROUND_RGB: RGB = (30, 30, 30)
DEFAULT_BACKGROUND_TOLERANCE = 25


class CameraUnavailableError(RuntimeError):
    """Raised when a frame cannot be obtained from the camera."""


@dataclass(frozen=True)
class CameraReading:
    rgb: RGB
    jpeg: bytes
    sequence: int
    sample_count: int | None = None
    background_sample: RGB | None = None


def measure_bead_rgb(
    frame: np.ndarray,
    *,
    region: tuple[int, int, int, int],
    background_rgb: RGB = DEFAULT_BACKGROUND_RGB,
    background_tolerance: int = DEFAULT_BACKGROUND_TOLERANCE,
    minimum_pixels: int = 200,
) -> tuple[RGB, np.ndarray]:
    """Average the largest foreground region, preserving any holes."""
    if not 0 <= background_tolerance <= 255 or minimum_pixels <= 0:
        raise ValueError("Invalid bead measurement configuration")
    if any(value < 0 or value > 255 for value in background_rgb):
        raise ValueError("Background RGB channels must be between 0 and 255")

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = region
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("Measurement region is outside the frame")

    roi = frame[y1:y2, x1:x2]
    background_bgr = np.array(background_rgb[::-1], dtype=np.int16)
    difference = np.abs(roi.astype(np.int16) - background_bgr)
    foreground = np.any(difference > background_tolerance, axis=2)
    candidate_mask = np.where(foreground, 255, 0).astype(np.uint8)
    candidate_mask = cv2.morphologyEx(
        candidate_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
    )
    component_count, labels, statistics, _ = cv2.connectedComponentsWithStats(
        candidate_mask
    )
    if component_count <= 1:
        return background_rgb, np.zeros(candidate_mask.shape, dtype=np.uint8)

    component = 1 + int(np.argmax(statistics[1:, cv2.CC_STAT_AREA]))
    bead_mask = np.where((labels == component) & foreground, 255, 0).astype(
        np.uint8
    )
    if cv2.countNonZero(bead_mask) < minimum_pixels:
        return background_rgb, np.zeros(candidate_mask.shape, dtype=np.uint8)

    average_bgr = np.mean(roi[bead_mask > 0], axis=0).astype(int)
    rgb: RGB = (int(average_bgr[2]), int(average_bgr[1]), int(average_bgr[0]))
    return rgb, bead_mask

class CameraService:
    """Continuously capture one camera for all connected web clients."""

    def __init__(
        self,
        *,
        frame_size: tuple[int, int] = (640, 480),
        measurement_region: tuple[float, float, float, float] = (
            0.16,
            0.20,
            0.98,
            0.91,
        ),
        background_rgb: RGB = DEFAULT_BACKGROUND_RGB,
        background_tolerance: int = DEFAULT_BACKGROUND_TOLERANCE,
    ) -> None:
        self.frame_size = frame_size
        self.measurement_region = measurement_region
        self.background_rgb = background_rgb
        self.background_tolerance = background_tolerance
        self._background_generation = 0
        self._condition = Condition()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._reading: CameraReading | None = None
        self._error: str | None = None

    def configure_background(self, rgb: RGB, tolerance: int) -> None:
        """Apply background settings and invalidate measurements made with old settings."""
        if not 0 <= tolerance <= 255 or any(v < 0 or v > 255 for v in rgb):
            raise ValueError("Invalid background configuration")
        with self._condition:
            self.background_rgb = rgb
            self.background_tolerance = tolerance
            self._background_generation += 1
            self._reading = None
            self._condition.notify_all()

    @property
    def error(self) -> str | None:
        with self._condition:
            return self._error

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._capture, daemon=True, name="camera")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def latest(self) -> CameraReading | None:
        with self._condition:
            return self._reading

    def get_reading(
        self,
        timeout: float = 2.0,
        *,
        after_sequence: int | None = None,
    ) -> CameraReading:
        """Return a reading, optionally waiting for a newer frame."""
        deadline = monotonic() + timeout
        with self._condition:
            while self._error is None and (
                self._reading is None
                or (
                    after_sequence is not None
                    and self._reading.sequence <= after_sequence
                )
            ):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            if self._reading is not None and (
                after_sequence is None
                or self._reading.sequence > after_sequence
            ):
                return self._reading
            message = self._error or "Timed out waiting for a new camera frame"
            raise CameraUnavailableError(message)

    def frames(self) -> Iterator[bytes]:
        last_sequence = -1
        while not self._stop_event.is_set():
            with self._condition:
                self._condition.wait_for(
                    lambda last_sequence=last_sequence: self._stop_event.is_set()
                    or self._error is not None
                    or (
                        self._reading is not None
                        and self._reading.sequence != last_sequence
                    ),
                    timeout=2,
                )
                if self._stop_event.is_set():
                    return
                if self._reading is None:
                    if self._error is not None:
                        return
                    continue
                reading = self._reading
            last_sequence = reading.sequence
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + reading.jpeg
                + b"\r\n"
            )

    def _capture(self) -> None:
        camera = None
        try:
            from picamera2 import Picamera2

            camera = Picamera2()
            config = camera.create_video_configuration(
                main={"size": self.frame_size, "format": "BGR888"}
            )
            camera.configure(config)
            camera.start()
            sequence = 0

            while not self._stop_event.is_set():
                frame = camera.capture_array()
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                height, width = frame.shape[:2]
                x1 = round(width * self.measurement_region[0])
                y1 = round(height * self.measurement_region[1])
                x2 = round(width * self.measurement_region[2])
                y2 = round(height * self.measurement_region[3])
                with self._condition:
                    generation = self._background_generation
                    background_rgb = self.background_rgb
                    background_tolerance = self.background_tolerance
                # Sample the raw ROI for empty-background calibration, independently
                # of the current foreground threshold.
                median_bgr = np.median(frame[y1:y2, x1:x2], axis=(0, 1))
                background_sample: RGB = (
                    int(median_bgr[2]), int(median_bgr[1]), int(median_bgr[0])
                )
                rgb, bead_mask = measure_bead_rgb(
                    frame,
                    region=(x1, y1, x2, y2),
                    background_rgb=background_rgb,
                    background_tolerance=background_tolerance,
                )

                cv2.rectangle(frame, (x1, y1), (x2, y2), (44, 220, 166), 2)
                contours, _hierarchy = cv2.findContours(
                    bead_mask,
                    cv2.RETR_LIST,
                    cv2.CHAIN_APPROX_SIMPLE,
                )
                offset = np.array([[[x1, y1]]], dtype=np.int32)
                cv2.drawContours(
                    frame,
                    [contour + offset for contour in contours],
                    -1,
                    (0, 220, 255),
                    2,
                )
                pixel_count = cv2.countNonZero(bead_mask)
                cv2.putText(
                    frame,
                    f"R:{rgb[0]} G:{rgb[1]} B:{rgb[2]} / {pixel_count} px",
                    (20, height - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (44, 220, 166),
                    2,
                )
                encoded, buffer = cv2.imencode(".jpg", frame)
                if not encoded:
                    continue

                sequence += 1
                reading = CameraReading(
                    rgb,
                    buffer.tobytes(),
                    sequence,
                    pixel_count,
                    background_sample,
                )
                with self._condition:
                    if generation != self._background_generation:
                        continue
                    self._reading = reading
                    self._error = None
                    self._condition.notify_all()
        except Exception as error:  # noqa: BLE001 - camera thread reports failures
            with self._condition:
                self._error = str(error)
                self._condition.notify_all()
        finally:
            if camera is not None:
                camera.stop()
                camera.close()