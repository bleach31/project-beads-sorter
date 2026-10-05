"""Shared Pi Camera capture service for preview and color sampling."""

from dataclasses import dataclass
from threading import Condition, Event, Thread
from time import monotonic
from typing import Iterator

import cv2
import numpy as np

from beads_sorter.vision.color import RGB


class CameraUnavailableError(RuntimeError):
    """Raised when a frame cannot be obtained from the camera."""


@dataclass(frozen=True)
class CameraReading:
    rgb: RGB
    jpeg: bytes
    sequence: int
    sample_count: int = 0


def measure_bead_rgb(
    frame: np.ndarray,
    *,
    region: tuple[int, int, int, int],
    seed: tuple[int, int],
    color_tolerance: float = 55.0,
    minimum_pixels: int = 200,
) -> tuple[RGB, np.ndarray]:
    """Segment the bead around a seed point and average its visible surface."""
    if color_tolerance <= 0 or minimum_pixels <= 0:
        raise ValueError("Invalid bead measurement configuration")

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = region
    seed_x, seed_y = seed
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("Measurement region is outside the frame")
    if not (x1 <= seed_x < x2 and y1 <= seed_y < y2):
        raise ValueError("Seed point must be inside the measurement region")

    roi = frame[y1:y2, x1:x2]
    local_seed_x = seed_x - x1
    local_seed_y = seed_y - y1
    seed_radius = max(2, min(roi.shape[:2]) // 50)
    seed_patch = roi[
        max(0, local_seed_y - seed_radius) : local_seed_y + seed_radius + 1,
        max(0, local_seed_x - seed_radius) : local_seed_x + seed_radius + 1,
    ]
    seed_bgr = np.median(seed_patch, axis=(0, 1)).astype(np.uint8)

    roi_lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    seed_lab = cv2.cvtColor(seed_bgr.reshape(1, 1, 3), cv2.COLOR_BGR2LAB)[
        0, 0
    ].astype(np.float32)
    distances = np.linalg.norm(roi_lab - seed_lab, axis=2)
    candidate_mask = np.where(distances <= color_tolerance, 255, 0).astype(
        np.uint8
    )
    candidate_mask = cv2.morphologyEx(
        candidate_mask,
        cv2.MORPH_OPEN,
        np.ones((3, 3), np.uint8),
    )
    candidate_mask = cv2.morphologyEx(
        candidate_mask,
        cv2.MORPH_CLOSE,
        np.ones((11, 11), np.uint8),
    )

    component_count, labels, statistics, _centroids = cv2.connectedComponentsWithStats(
        candidate_mask
    )
    seed_label = int(labels[local_seed_y, local_seed_x])
    if seed_label == 0 and component_count > 1:
        seed_label = 1 + int(np.argmax(statistics[1:, cv2.CC_STAT_AREA]))
    if seed_label == 0:
        raise CameraUnavailableError("No bead area found in the measurement region")

    component_mask = np.where(labels == seed_label, 255, 0).astype(np.uint8)
    contours, _hierarchy = cv2.findContours(
        component_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        raise CameraUnavailableError("No bead contour found in the measurement region")

    bead_mask = np.zeros(component_mask.shape, dtype=np.uint8)
    cv2.drawContours(
        bead_mask,
        [max(contours, key=cv2.contourArea)],
        -1,
        255,
        cv2.FILLED,
    )
    pixel_count = cv2.countNonZero(bead_mask)
    if pixel_count < minimum_pixels:
        raise CameraUnavailableError(
            f"Detected bead area is too small ({pixel_count} pixels)"
        )

    average_bgr = np.mean(roi[bead_mask > 0], axis=0).astype(int)
    rgb: RGB = (
        int(average_bgr[2]),
        int(average_bgr[1]),
        int(average_bgr[0]),
    )
    return rgb, bead_mask


class CameraService:
    """Continuously capture one camera for all connected web clients."""

    def __init__(
        self,
        *,
        frame_size: tuple[int, int] = (640, 480),
        measurement_region: tuple[float, float, float, float] = (
            0.36,
            0.16,
            0.92,
            0.90,
        ),
        seed_position: tuple[float, float] = (0.50, 0.50),
        color_tolerance: float = 55.0,
    ) -> None:
        self.frame_size = frame_size
        self.measurement_region = measurement_region
        self.seed_position = seed_position
        self.color_tolerance = color_tolerance
        self._condition = Condition()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._reading: CameraReading | None = None
        self._error: str | None = None

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
                    lambda: self._stop_event.is_set()
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
                seed_x = round(width * self.seed_position[0])
                seed_y = round(height * self.seed_position[1])
                rgb, bead_mask = measure_bead_rgb(
                    frame,
                    region=(x1, y1, x2, y2),
                    seed=(seed_x, seed_y),
                    color_tolerance=self.color_tolerance,
                )

                cv2.rectangle(frame, (x1, y1), (x2, y2), (44, 220, 166), 2)
                contours, _hierarchy = cv2.findContours(
                    bead_mask,
                    cv2.RETR_EXTERNAL,
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
                cv2.circle(frame, (seed_x, seed_y), 4, (44, 220, 166), -1)
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
                )
                with self._condition:
                    self._reading = reading
                    self._error = None
                    self._condition.notify_all()
        except Exception as error:
            with self._condition:
                self._error = str(error)
                self._condition.notify_all()
        finally:
            if camera is not None:
                camera.stop()
                camera.close()