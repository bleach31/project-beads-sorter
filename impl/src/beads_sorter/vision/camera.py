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
    sample_count: int = 9


def sample_roi_rgb(
    frame: np.ndarray,
    *,
    center: tuple[int, int],
    roi_size: int,
    grid_size: int = 3,
    patch_radius: int = 2,
) -> tuple[RGB, tuple[tuple[int, int], ...]]:
    """Sample a grid of small patches and return their median RGB color."""
    if grid_size < 2 or roi_size <= 0 or patch_radius < 0:
        raise ValueError("Invalid ROI sampling configuration")

    height, width = frame.shape[:2]
    center_x, center_y = center
    half = roi_size // 2
    x1, x2 = max(0, center_x - half), min(width, center_x + half)
    y1, y2 = max(0, center_y - half), min(height, center_y + half)
    if x2 - x1 < grid_size or y2 - y1 < grid_size:
        raise ValueError("ROI is too small for the sampling grid")

    x_margin = max(patch_radius, (x2 - x1) // (grid_size + 1))
    y_margin = max(patch_radius, (y2 - y1) // (grid_size + 1))
    xs = np.linspace(x1 + x_margin, x2 - x_margin - 1, grid_size).astype(int)
    ys = np.linspace(y1 + y_margin, y2 - y_margin - 1, grid_size).astype(int)

    points: list[tuple[int, int]] = []
    samples: list[np.ndarray] = []
    for sample_y in ys:
        for sample_x in xs:
            patch = frame[
                max(0, sample_y - patch_radius) : min(
                    height, sample_y + patch_radius + 1
                ),
                max(0, sample_x - patch_radius) : min(
                    width, sample_x + patch_radius + 1
                ),
            ]
            points.append((int(sample_x), int(sample_y)))
            samples.append(np.median(patch, axis=(0, 1)))

    median_bgr = np.median(np.stack(samples), axis=0).astype(int)
    rgb: RGB = (
        int(median_bgr[2]),
        int(median_bgr[1]),
        int(median_bgr[0]),
    )
    return rgb, tuple(points)


class CameraService:
    """Continuously capture one camera for all connected web clients."""

    def __init__(
        self,
        *,
        frame_size: tuple[int, int] = (640, 480),
        roi_size: int = 40,
    ) -> None:
        self.frame_size = frame_size
        self.roi_size = roi_size
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
                half = self.roi_size // 2
                center_x, center_y = width // 2, height // 2
                x1, x2 = center_x - half, center_x + half
                y1, y2 = center_y - half, center_y + half
                rgb, sample_points = sample_roi_rgb(
                    frame,
                    center=(center_x, center_y),
                    roi_size=self.roi_size,
                )

                cv2.rectangle(frame, (x1, y1), (x2, y2), (44, 220, 166), 2)
                for sample_point in sample_points:
                    cv2.circle(frame, sample_point, 2, (44, 220, 166), -1)
                cv2.putText(
                    frame,
                    f"R:{rgb[0]} G:{rgb[1]} B:{rgb[2]} / {len(sample_points)} points",
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
                    len(sample_points),
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