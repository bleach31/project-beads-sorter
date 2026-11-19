"""FastAPI operator interface for the bead sorter."""

import asyncio
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from math import sqrt
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Literal

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from beads_sorter.controller import SortController
from beads_sorter.ejector.hardware import (
    DEFAULT_STEPPER_TRAVEL_STEPS,
    HardwareUnavailableError,
    StepperMotor,
    SysfsServo,
)
from beads_sorter.vision.camera import (
    DEFAULT_BACKGROUND_RGB,
    DEFAULT_BACKGROUND_TOLERANCE,
    CameraReading,
    CameraService,
    CameraUnavailableError,
)
from beads_sorter.vision.color import RGB, ColorClassifier, ColorMatch

COLOR_LABELS = {
    "white": "白",
    "pink": "ピンク",
    "magenta": "マゼンタ",
    "purple": "紫",
    "blue": "青",
    "cyan": "水色",
    "green": "緑",
    "green_tea": "緑茶",
    "orange": "オレンジ",
    "red": "赤",
    "background": "ビーズなし",
    "unknown": "判定外",
}

AUTO_RGB_STABILITY_THRESHOLD = 12.0
AUTO_FRAME_STABILITY_THRESHOLD = 5.0
AUTO_STABLE_FRAMES = 2
AUTO_STABILITY_SECONDS = 0.5
AUTO_COLOR_RETRY_INTERVAL_SECONDS = 1.0
AUTO_COLOR_RETRY_TIMEOUT_SECONDS = 60.0


class BusyError(RuntimeError):
    """Raised when another mechanical operation is already active."""


class UnavailableStepper:
    def __init__(self, error: str) -> None:
        self.error = error
        self.current_slot = 0
        self.travel_steps = DEFAULT_STEPPER_TRAVEL_STEPS
        self.step_delay = 0.004
        self.position_offset_steps = 0

    def _raise(self) -> None:
        raise HardwareUnavailableError(self.error)

    def move_to_slot(self, slot: int) -> int:
        self._raise()
        return 0

    def set_home(self) -> None:
        self._raise()

    def configure(self, **_values: Any) -> None:
        self._raise()

    def shift_positions(self, steps: int) -> int:
        self._raise()
        return steps

    def close(self) -> None:
        pass


class SimulatedStepper:
    def __init__(self) -> None:
        self.current_slot = 0
        self.travel_steps = DEFAULT_STEPPER_TRAVEL_STEPS
        self.step_delay = 0.004
        self.position_offset_steps = 0

    def move_to_slot(self, slot: int) -> int:
        old_position = round(self.current_slot * self.travel_steps / 9)
        new_position = round(slot * self.travel_steps / 9)
        steps = new_position - old_position
        self.current_slot = slot
        return steps

    def set_home(self) -> None:
        self.current_slot = 0
        self.position_offset_steps = 0

    def configure(self, *, travel_steps: int, step_delay: float) -> None:
        if travel_steps == 0:
            raise ValueError("Stepper travel must be non-zero")
        self.travel_steps = travel_steps
        self.step_delay = step_delay

    def shift_positions(self, steps: int) -> int:
        self.position_offset_steps += steps
        return steps

    def close(self) -> None:
        pass


class SimulatedPusher:
    def __init__(self) -> None:
        self.push_angle = 175
        self.rest_angle = 90
        self.hold_seconds = 0.35
        self.settle_seconds = 0.35

    def push_and_return(self) -> None:
        pass

    def configure(self, **values: Any) -> None:
        for name, value in values.items():
            setattr(self, name, value)

    def close(self) -> None:
        pass


class AppRuntime:
    """Own application services and observable operation state."""

    def __init__(
        self,
        camera: Any | None = None,
        stepper: Any | None = None,
        pusher: Any | None = None,
        *,
        simulation: bool | None = None,
        automatic_stability_seconds: float = AUTO_STABILITY_SECONDS,
    ) -> None:
        if automatic_stability_seconds <= 0:
            raise ValueError("Automatic stability time must be positive")
        self.camera = camera or CameraService()
        self.automatic_stability_seconds = automatic_stability_seconds
        requested_simulation = simulation
        if requested_simulation is None:
            requested_simulation = os.getenv("BEADS_SORTER_SIMULATION") == "1"

        self.hardware_error: str | None = None
        if stepper is not None:
            self.stepper = stepper
            self.hardware_mode = "injected"
        elif requested_simulation:
            self.stepper = SimulatedStepper()
            self.hardware_mode = "simulation"
        else:
            try:
                self.stepper = StepperMotor()
                self.hardware_mode = "gpio"
            except Exception as error:  # noqa: BLE001 - hardware fallback
                self.hardware_error = str(error)
                self.stepper = UnavailableStepper(str(error))
                self.hardware_mode = "unavailable"

        if pusher is not None:
            self.pusher = pusher
        elif requested_simulation:
            self.pusher = SimulatedPusher()
        else:
            self.pusher = SysfsServo()

        classifier = ColorClassifier()
        slots = {name: slot for slot, name in enumerate(classifier.references)}
        self.controller = SortController(
            classifier,
            self.stepper,
            self.pusher,
            slots,
        )
        self._operation_lock = Lock()
        self._state_lock = Lock()
        self.busy = False
        self.action = "idle"
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.last_detection: ColorMatch | None = None
        self.background_rgb: RGB = DEFAULT_BACKGROUND_RGB
        self.background_tolerance = DEFAULT_BACKGROUND_TOLERANCE
        self._recognition_paused = False
        self._auto_stop_event = Event()
        self._auto_thread: Thread | None = None
        self._auto_running = False
        self._auto_waiting = False
        self._auto_count = 0
        self._auto_retry_since: float | None = None
        self._auto_retry_count = 0

    def start(self) -> None:
        self.camera.start()

    def close(self) -> None:
        self.stop_automatic()
        auto_thread = self._auto_thread
        if auto_thread is not None:
            auto_thread.join(timeout=30)
            if auto_thread.is_alive():
                raise RuntimeError("Automatic sorting did not stop during shutdown")
        self.camera.stop()
        self.stepper.close()
        self.pusher.close()

    def execute(
        self,
        action: str,
        operation: Callable[[], Any],
        *,
        allow_during_automatic: bool = False,
    ) -> Any:
        with self._state_lock:
            if self._auto_running and not allow_during_automatic:
                raise BusyError("Automatic sorting is running")
        if not self._operation_lock.acquire(blocking=False):
            raise BusyError("Another mechanical operation is running")
        with self._state_lock:
            self.busy = True
            self.action = action
            self.last_error = None
        try:
            result = operation()
            if hasattr(result, "__dataclass_fields__"):
                self.last_result = asdict(result)
            return result
        except Exception as error:
            with self._state_lock:
                self.last_error = str(error)
            raise
        finally:
            with self._state_lock:
                self.busy = False
                self.action = "idle"
            self._operation_lock.release()

    @staticmethod
    def _rgb_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
        return sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))

    @staticmethod
    def _frame_distance(left: bytes | None, right: bytes) -> float:
        if not left:
            return 0.0
        left_frame = cv2.imdecode(np.frombuffer(left, np.uint8), cv2.IMREAD_GRAYSCALE)
        right_frame = cv2.imdecode(
            np.frombuffer(right, np.uint8),
            cv2.IMREAD_GRAYSCALE,
        )
        if left_frame is None or right_frame is None:
            return 0.0
        size = (32, 24)
        left_small = cv2.resize(left_frame, size, interpolation=cv2.INTER_AREA)
        right_small = cv2.resize(right_frame, size, interpolation=cv2.INTER_AREA)
        return float(np.mean(cv2.absdiff(left_small, right_small)))

    def _wait_for_stable_reading(self) -> bool:
        last_sequence = -1
        candidate_rgb: tuple[int, int, int] | None = None
        candidate_jpeg: bytes | None = None
        stable_frames = 0
        stable_since: float | None = None

        while not self._auto_stop_event.is_set():
            reading = self.camera.latest()
            if reading is None:
                if self.camera.error is not None:
                    raise CameraUnavailableError(self.camera.error)
                self._auto_stop_event.wait(0.05)
                continue
            if reading.sequence == last_sequence:
                self._auto_stop_event.wait(0.05)
                continue

            last_sequence = reading.sequence
            if (
                candidate_rgb is not None
                and candidate_jpeg is not None
                and self._rgb_distance(reading.rgb, candidate_rgb)
                <= AUTO_RGB_STABILITY_THRESHOLD
                and self._frame_distance(reading.jpeg, candidate_jpeg)
                <= AUTO_FRAME_STABILITY_THRESHOLD
            ):
                stable_frames += 1
                candidate_rgb = reading.rgb
                candidate_jpeg = reading.jpeg
            else:
                candidate_rgb = reading.rgb
                candidate_jpeg = reading.jpeg
                stable_frames = 1
                stable_since = monotonic()

            if (
                stable_frames >= AUTO_STABLE_FRAMES
                and stable_since is not None
                and monotonic() - stable_since >= self.automatic_stability_seconds
            ):
                return True

        return False

    def _retry_color(
        self, reading: CameraReading, match: ColorMatch
    ) -> ColorMatch | None:
        """Retry uncertain colors using fresh frames, without moving hardware."""
        if match.name == "background" or (
            match.name != "unknown"
            and match.confidence >= self.controller.minimum_confidence
        ):
            return match

        started = monotonic()
        deadline = started + AUTO_COLOR_RETRY_TIMEOUT_SECONDS
        last_sequence = reading.sequence
        with self._state_lock:
            self._auto_retry_since = started
            self._auto_retry_count = 0
        try:
            while not self._auto_stop_event.is_set():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                if self._auto_stop_event.wait(
                    min(AUTO_COLOR_RETRY_INTERVAL_SECONDS, remaining)
                ):
                    return None
                reading = self.camera.latest()
                if self.camera.error is not None:
                    raise CameraUnavailableError(self.camera.error)
                if reading is not None and reading.sequence != last_sequence:
                    last_sequence = reading.sequence
                    match = self._classify_reading(reading)
                    with self._state_lock:
                        self.last_detection = match
                        self._auto_retry_count += 1
                    if match.name == "background" or (
                        match.name != "unknown"
                        and match.confidence >= self.controller.minimum_confidence
                    ):
                        return match
            if self._auto_stop_event.is_set():
                return None
            raise ValueError(
                f"Color recognition timed out after "
                f"{AUTO_COLOR_RETRY_TIMEOUT_SECONDS:g}s: "
                f"{match.name}, confidence {match.confidence:.2f}"
            )
        finally:
            with self._state_lock:
                self._auto_retry_since = None
                self._auto_retry_count = 0

    def _automatic_loop(self) -> None:
        has_sorted = False
        try:
            while not self._auto_stop_event.is_set():
                if has_sorted:
                    with self._state_lock:
                        self._auto_waiting = True
                    if not self._wait_for_stable_reading():
                        break

                reading = self.camera.latest()
                if reading is None:
                    reading = self.camera.get_reading()
                match = self._classify_reading(reading)
                with self._state_lock:
                    self.last_detection = match
                    self._auto_waiting = False
                match = self._retry_color(reading, match)
                if match is None or self._auto_stop_event.is_set():
                    break
                if match.name == "background":
                    with self._state_lock:
                        self._auto_waiting = True
                    if not self._wait_for_stable_reading():
                        break
                    has_sorted = True
                    continue

                self.execute(
                    "automatic sorting",
                    lambda match=match: self.controller.sort_match(
                        match, push_action=self._push_with_recognition_paused
                    ),
                    allow_during_automatic=True,
                )
                with self._state_lock:
                    self._auto_count += 1
                has_sorted = True
        except Exception as error:  # noqa: BLE001 - stop automatic on any failure
            with self._state_lock:
                self.last_error = f"Automatic sorting stopped: {error}"
        finally:
            with self._state_lock:
                self._auto_running = False
                self._auto_waiting = False
                self._auto_thread = None

    def start_automatic(self) -> dict[str, Any]:
        with self._state_lock:
            if self._auto_running:
                raise BusyError("Automatic sorting is already running")
            if self.busy:
                raise BusyError("Another mechanical operation is running")
            self._auto_stop_event.clear()
            self._auto_running = True
            self._auto_waiting = False
            self._auto_count = 0
            self.last_error = None
            self._auto_thread = Thread(
                target=self._automatic_loop,
                daemon=True,
                name="automatic-sorter",
            )
            auto_thread = self._auto_thread
        auto_thread.start()
        return self.automatic_status()

    def stop_automatic(self) -> dict[str, Any]:
        self._auto_stop_event.set()
        return self.automatic_status()

    def automatic_status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "running": self._auto_running,
                "waiting_for_bead": self._auto_waiting,
                "stop_requested": (
                    self._auto_running and self._auto_stop_event.is_set()
                ),
                "sorted_count": self._auto_count,
                "retrying": self._auto_retry_since is not None,
                "retry_elapsed_seconds": (
                    min(
                        monotonic() - self._auto_retry_since,
                        AUTO_COLOR_RETRY_TIMEOUT_SECONDS,
                    )
                    if self._auto_retry_since is not None
                    else 0.0
                ),
                "retry_timeout_seconds": AUTO_COLOR_RETRY_TIMEOUT_SECONDS,
                "retry_count": self._auto_retry_count,
            }

    def recognize_current(
        self,
        *,
        after_sequence: int | None = None,
    ) -> ColorMatch:
        reading = self.camera.get_reading(after_sequence=after_sequence)
        match = self._classify_reading(reading)
        with self._state_lock:
            self.last_detection = match
        return match

    def _classify_reading(self, reading: CameraReading) -> ColorMatch:
        # Real camera measurements explicitly report foreground area.
        # Legacy/injected RGB-only readings retain their original fallback.
        if reading.sample_count == 0 or (
            reading.sample_count is None
            and all(
                abs(channel - bg) <= self.background_tolerance
                for channel, bg in zip(reading.rgb, self.background_rgb)
            )
        ):
            return ColorMatch(name="background", rgb=reading.rgb, confidence=1.0)
        return self.controller.recognize(reading.rgb)

    def configure_background(self, rgb: RGB, tolerance: int) -> None:
        with self._state_lock:
            self.camera.configure_background(rgb, tolerance)
            self.background_rgb = rgb
            self.background_tolerance = tolerance
            self.last_detection = None

    def _refresh_live_detection(self) -> ColorMatch | None:
        reading = self.camera.latest()
        if reading is None:
            return None
        with self._state_lock:
            if self._recognition_paused:
                return self.last_detection
            self.last_detection = self._classify_reading(reading)
            return self.last_detection

    def _push_with_recognition_paused(self) -> ColorMatch:
        with self._state_lock:
            self._recognition_paused = True
        try:
            self.pusher.push_and_return()
            latest = self.camera.latest()
            after_sequence = latest.sequence if latest is not None else None
            reading = self.camera.get_reading(after_sequence=after_sequence)
            match = self._classify_reading(reading)
            with self._state_lock:
                self.last_detection = match
            return match
        finally:
            with self._state_lock:
                self._recognition_paused = False

    def sort_current(self):
        reading = self.camera.latest()
        if reading is None:
            reading = self.camera.get_reading()
        match = self._classify_reading(reading)
        with self._state_lock:
            self.last_detection = match
        if match.name == "background":
            raise ValueError("No bead detected: the measurement matches the background")

        return self.controller.sort_match(
            match,
            push_action=self._push_with_recognition_paused,
        )

    def push_and_recognize(self) -> ColorMatch:
        return self._push_with_recognition_paused()

    def status(self) -> dict[str, Any]:
        self._refresh_live_detection()
        reading = self.camera.latest()
        with self._state_lock:
            detection = (
                asdict(self.last_detection)
                if self.last_detection is not None
                else None
            )
            if detection is not None and self.last_detection is not None:
                detection["slot"] = self.controller.slots.get(
                    self.last_detection.name
                )
            recognition_paused = self._recognition_paused
        return {
            "busy": self.busy,
            "action": self.action,
            "recognition_paused": recognition_paused,
            "camera": {
                "ready": reading is not None,
                "error": self.camera.error,
                "sample_count": (reading.sample_count or 0) if reading else 0,
            },
            "hardware": {
                "mode": self.hardware_mode,
                "error": self.hardware_error,
            },
            "current_slot": self.stepper.current_slot,
            "detection": detection,
            "last_result": self.last_result,
            "last_error": self.last_error,
            "automatic": self.automatic_status(),
            "config": self.config(),
        }

    def config(self) -> dict[str, Any]:
        slot_direction = 1 if self.stepper.travel_steps > 0 else -1
        return {
            "travel_steps": self.stepper.travel_steps,
            "position_offset_steps": (
                self.stepper.position_offset_steps * slot_direction
            ),
            "step_delay": self.stepper.step_delay,
            "push_angle": self.pusher.push_angle,
            "rest_angle": self.pusher.rest_angle,
            "hold_seconds": self.pusher.hold_seconds,
            "settle_seconds": self.pusher.settle_seconds,
            "minimum_confidence": self.controller.minimum_confidence,
            "rgb_tolerance": self.controller.classifier.rgb_tolerance,
            "background_rgb": self.background_rgb,
            "background_tolerance": self.background_tolerance,
        }


class SlotRequest(BaseModel):
    slot: int = Field(ge=0, le=9)


class CalibrationRequest(SlotRequest):
    color: str


class ColorRequest(BaseModel):
    color: str


class SlotAssignmentRequest(SlotRequest):
    color: str


class StepperConfig(BaseModel):
    travel_steps: int = Field(ge=-100_000, le=100_000)
    step_delay: float = Field(ge=0, le=0.1)


class PositionShiftRequest(BaseModel):
    direction: Literal["left", "right"]
    steps: int = Field(ge=1, le=100_000)


class ServoConfig(BaseModel):
    push_angle: int = Field(ge=0, le=180)
    rest_angle: int = Field(ge=0, le=180)
    hold_seconds: float = Field(ge=0, le=10)
    settle_seconds: float = Field(ge=0, le=10)


class RecognitionConfig(BaseModel):
    minimum_confidence: float = Field(ge=0, le=1)
    rgb_tolerance: int = Field(ge=0, le=255)


class BackgroundConfig(BaseModel):
    background_tolerance: int = Field(ge=0, le=255)


class MotionConfig(BaseModel):
    travel_steps: int = Field(ge=-100_000, le=100_000)
    step_delay: float = Field(ge=0, le=0.1)
    push_angle: int = Field(ge=0, le=180)
    rest_angle: int = Field(ge=0, le=180)
    hold_seconds: float = Field(ge=0, le=10)
    settle_seconds: float = Field(ge=0, le=10)
    minimum_confidence: float = Field(ge=0, le=1)
    rgb_tolerance: int | None = Field(default=None, ge=0, le=255)


def create_app(runtime: AppRuntime | None = None) -> FastAPI:
    runtime = runtime or AppRuntime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(title="Beads Sorter", lifespan=lifespan)
    app.state.runtime = runtime

    async def run_action(name: str, operation: Callable[[], Any]) -> Any:
        try:
            result = await asyncio.to_thread(runtime.execute, name, operation)
            return asdict(result) if hasattr(result, "__dataclass_fields__") else result
        except BusyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CameraUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except HardwareUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return OPERATOR_HTML

    @app.get("/video_feed")
    def video_feed() -> StreamingResponse:
        return StreamingResponse(
            runtime.camera.frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return runtime.status()

    @app.get("/api/colors")
    def colors() -> list[dict[str, Any]]:
        result = []
        for name, rgb in runtime.controller.classifier.references.items():
            threshold = runtime.controller.classifier.threshold_for(name)
            result.append(
                {
                    "name": name,
                    "label": COLOR_LABELS.get(name, name),
                    "rgb": rgb,
                    "rgb_min": threshold.minimum,
                    "rgb_max": threshold.maximum,
                    "slot": runtime.controller.slots[name],
                }
            )
        return result

    @app.post("/api/recognize")
    async def recognize() -> Any:
        return await run_action("recognizing", runtime.recognize_current)

    @app.post("/api/sort")
    async def sort() -> Any:
        return await run_action("sorting", runtime.sort_current)

    @app.post("/api/automatic/start")
    async def start_automatic() -> Any:
        try:
            return runtime.start_automatic()
        except BusyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/automatic/stop")
    async def stop_automatic() -> Any:
        return runtime.stop_automatic()

    @app.post("/api/move")
    async def move(request: SlotRequest) -> Any:
        return await run_action(
            "moving",
            lambda: {
                "slot": request.slot,
                "steps": runtime.stepper.move_to_slot(request.slot),
            },
        )

    @app.post("/api/push")
    async def push() -> Any:
        return await run_action("pushing", runtime.push_and_recognize)

    @app.post("/api/home")
    async def home() -> Any:
        return await run_action(
            "homing",
            lambda: (runtime.stepper.set_home() or {"slot": 0}),
        )

    @app.post("/api/stepper/shift")
    async def shift_stepper(request: PositionShiftRequest) -> Any:
        def apply_shift() -> dict[str, Any]:
            slot_direction = 1 if runtime.stepper.travel_steps > 0 else -1
            direction = 1 if request.direction == "right" else -1
            moved_steps = runtime.stepper.shift_positions(
                request.steps * slot_direction * direction
            )
            return {
                "direction": request.direction,
                "steps": request.steps,
                "moved_steps": moved_steps,
                "position_offset_steps": runtime.config()["position_offset_steps"],
            }

        return await run_action("shifting", apply_shift)

    @app.post("/api/calibrate")
    async def calibrate(request: CalibrationRequest) -> Any:
        def apply_calibration() -> dict[str, Any]:
            reading = runtime.camera.get_reading()
            if runtime._classify_reading(reading).name == "background":
                raise ValueError("No bead detected for color calibration")
            runtime.controller.classifier.set_reference(request.color, reading.rgb)
            runtime.controller.slots[request.color] = request.slot
            return {
                "color": request.color,
                "rgb": reading.rgb,
                "slot": request.slot,
            }

        return await run_action("calibrating", apply_calibration)

    @app.post("/api/calibrate/color")
    async def calibrate_color(request: ColorRequest) -> Any:
        def apply_color_calibration() -> dict[str, Any]:
            reading = runtime.camera.get_reading()
            if runtime._classify_reading(reading).name == "background":
                raise ValueError("No bead detected for color calibration")
            with runtime._state_lock:
                runtime.controller.classifier.set_reference(
                    request.color,
                    reading.rgb,
                )
                runtime.last_detection = runtime.controller.recognize(reading.rgb)
            return {"color": request.color, "rgb": reading.rgb}

        return await run_action("calibrating", apply_color_calibration)

    @app.post("/api/calibrate/background")
    async def calibrate_background() -> Any:
        def apply_background_calibration() -> dict[str, Any]:
            reading = runtime.camera.get_reading()
            rgb = reading.background_sample or reading.rgb
            runtime.configure_background(rgb, runtime.background_tolerance)
            return {
                "background_rgb": rgb,
                "background_tolerance": runtime.background_tolerance,
            }

        return await run_action("calibrating", apply_background_calibration)

    @app.put("/api/slots")
    async def assign_slot(request: SlotAssignmentRequest) -> Any:
        def apply_slot() -> dict[str, Any]:
            if request.color not in runtime.controller.classifier.references:
                raise ValueError(f"Unknown color: {request.color}")
            runtime.controller.slots[request.color] = request.slot
            return {"color": request.color, "slot": request.slot}

        return await run_action("configuring", apply_slot)

    def apply_stepper_config(request: StepperConfig) -> dict[str, Any]:
        runtime.stepper.configure(
            travel_steps=request.travel_steps,
            step_delay=request.step_delay,
        )
        return runtime.config()

    def apply_servo_config(request: ServoConfig) -> dict[str, Any]:
        runtime.pusher.configure(
            push_angle=request.push_angle,
            rest_angle=request.rest_angle,
            hold_seconds=request.hold_seconds,
            settle_seconds=request.settle_seconds,
        )
        return runtime.config()

    def apply_recognition_config(request: RecognitionConfig) -> dict[str, Any]:
        with runtime._state_lock:
            runtime.controller.minimum_confidence = request.minimum_confidence
            runtime.controller.classifier.set_rgb_tolerance(request.rgb_tolerance)
        return runtime.config()

    @app.put("/api/config/stepper")
    async def configure_stepper(request: StepperConfig) -> Any:
        return await run_action(
            "configuring",
            lambda: apply_stepper_config(request),
        )

    @app.put("/api/config/servo")
    async def configure_servo(request: ServoConfig) -> Any:
        return await run_action(
            "configuring",
            lambda: apply_servo_config(request),
        )

    @app.put("/api/config/recognition")
    async def configure_recognition(request: RecognitionConfig) -> Any:
        return await run_action(
            "configuring",
            lambda: apply_recognition_config(request),
        )

    @app.put("/api/config/background")
    async def configure_background(request: BackgroundConfig) -> Any:
        def apply_background_config() -> dict[str, Any]:
            runtime.configure_background(
                runtime.background_rgb, request.background_tolerance
            )
            return runtime.config()

        return await run_action("configuring", apply_background_config)

    @app.put("/api/config")
    async def configure(request: MotionConfig) -> Any:
        def apply_config() -> dict[str, Any]:
            apply_stepper_config(StepperConfig(
                travel_steps=request.travel_steps,
                step_delay=request.step_delay,
            ))
            apply_servo_config(ServoConfig(
                push_angle=request.push_angle,
                rest_angle=request.rest_angle,
                hold_seconds=request.hold_seconds,
                settle_seconds=request.settle_seconds,
            ))
            if request.rgb_tolerance is None:
                runtime.controller.minimum_confidence = request.minimum_confidence
            else:
                apply_recognition_config(RecognitionConfig(
                    minimum_confidence=request.minimum_confidence,
                    rgb_tolerance=request.rgb_tolerance,
                ))
            return runtime.config()

        return await run_action("configuring", apply_config)

    return app


app = create_app()


OPERATOR_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Beads Sorter Console</title>
  <style>
    :root {
      --ink: #172027; --muted: #647079; --paper: #f4f7f5; --panel: #ffffff;
      --line: #ccd5d1; --accent: #e44f37; --accent-dark: #b83221;
      --mint: #22a879; --warning: #e0a526; --shadow: rgba(23, 32, 39, .1);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; color: var(--ink); background-color: var(--paper);
      background-image: linear-gradient(rgba(23,32,39,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(23,32,39,.035) 1px, transparent 1px);
      background-size: 24px 24px;
      font-family: "Aptos", "Noto Sans JP", "Yu Gothic", sans-serif;
    }
    header {
      min-height: 72px; padding: 14px clamp(16px, 4vw, 48px); color: white;
      background: #172027; display: flex; align-items: center;
      justify-content: space-between; gap: 16px; border-bottom: 4px solid var(--accent);
    }
    h1 { margin: 0; font: 700 24px/1.1 "Arial Narrow", "Noto Sans JP", sans-serif; }
    .eyebrow { color: #aebbb6; font-size: 11px; text-transform: uppercase; }
    .status-pill { display: flex; align-items: center; gap: 8px; font-size: 13px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--warning); }
    .dot.ready { background: #35d59d; box-shadow: 0 0 0 4px rgba(53,213,157,.15); }
    main { width: min(1220px, 100%); margin: 0 auto; padding: 24px; }
    .workspace { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(300px, .75fr); gap: 20px; }
    .camera-panel, .control-panel, details {
      background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
      box-shadow: 0 12px 30px var(--shadow);
    }
    .camera-panel { overflow: hidden; }
    .panel-head { padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; }
    .panel-head h2, .section-title { margin: 0; font-size: 14px; letter-spacing: 0; }
    .slot-readout { font-family: monospace; font-size: 13px; color: var(--muted); }
    .feed { position: relative; background: #111; aspect-ratio: 4 / 3; }
    .feed img { width: 100%; height: 100%; display: block; object-fit: contain; }
    .control-panel { padding: 18px; display: flex; flex-direction: column; gap: 18px; }
    .detection { display: grid; grid-template-columns: 64px 1fr; gap: 14px; align-items: center; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
    .swatch { width: 64px; height: 64px; border: 1px solid var(--line); border-radius: 6px; background: #d5dbd8; }
    .detection-title { display: flex; align-items: baseline; gap: 10px; }
    .color-name { font: 700 28px/1 "Arial Narrow", "Noto Sans JP", sans-serif; }
    .detection-slot { color: var(--muted); font: 700 13px/1 monospace; }
    .rgb, .confidence { color: var(--muted); font: 12px/1.5 monospace; }
    .primary-actions { display: grid; gap: 8px; }
    .primary-actions button { width: 100%; }
    button, select, input { min-height: 42px; border: 1px solid var(--line); border-radius: 5px; font: inherit; }
    button { padding: 0 14px; color: var(--ink); background: white; cursor: pointer; font-weight: 700; }
    button:hover { border-color: var(--ink); }
    button:disabled { cursor: wait; opacity: .48; }
    button.primary { color: white; background: var(--accent); border-color: var(--accent); }
    button.primary:hover { background: var(--accent-dark); }
    .manual-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .manual-grid select { padding: 0 10px; background: white; }
    .message { min-height: 42px; padding: 10px 12px; border-left: 3px solid var(--mint); background: #edf8f4; font-size: 13px; }
    .message.error { border-color: var(--accent); background: #fff0ed; }
    details { margin-top: 20px; box-shadow: none; }
    summary { cursor: pointer; padding: 15px 18px; font-weight: 700; }
        .calibration-layout { border-top: 1px solid var(--line); padding: 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .settings-group { min-width: 0; margin: 0; padding: 16px; border: 1px solid var(--line); border-radius: 5px; }
        .settings-group legend { padding: 0 8px; color: var(--ink); font-size: 14px; font-weight: 700; }
        .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .group-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
        .subsection-title { margin: 18px 0 10px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--ink); font-size: 12px; font-weight: 700; }
        .color-settings { grid-column: 1 / -1; }
        .recognition-body { display: grid; grid-template-columns: minmax(220px, .65fr) minmax(0, 1.35fr); gap: 18px; }
        .table-wrap { min-width: 0; overflow-x: auto; }
        .color-table { width: 100%; border-collapse: collapse; font-size: 12px; }
        .color-table th, .color-table td { padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; white-space: nowrap; }
        .color-table th { color: var(--muted); background: #f2f5f3; font-weight: 700; }
        .color-chip { display: inline-block; width: 18px; height: 18px; margin-right: 8px; border: 1px solid var(--line); border-radius: 3px; vertical-align: middle; }
        .threshold { color: var(--muted); font-family: monospace; line-height: 1.45; }
    label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; }
    input, select { width: 100%; padding: 0 10px; color: var(--ink); background: white; }
    @media (max-width: 820px) {
      header { min-height: 64px; } main { padding: 14px; }
      .workspace { grid-template-columns: 1fr; }
            .calibration-layout, .recognition-body { grid-template-columns: 1fr; }
            .color-settings { grid-column: auto; }
    }
    @media (max-width: 460px) {
            .manual-grid, .field-grid { grid-template-columns: 1fr; }
            .group-actions { display: grid; }
            .status-pill span:last-child { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <div><div class="eyebrow">Operator console</div><h1>BEADS SORTER</h1></div>
    <div class="status-pill"><i id="status-dot" class="dot"></i><span id="status-text">接続中</span></div>
  </header>
  <main>
    <div class="workspace">
      <section class="camera-panel">
                <div class="panel-head"><h2>CAMERA / BEAD AREA</h2><span id="slot" class="slot-readout">SLOT 0</span></div>
                <div class="feed"><img src="/video_feed" alt="Pi Camera live feed"></div>
      </section>
      <aside class="control-panel">
        <div class="detection">
          <div id="swatch" class="swatch"></div>
          <div><div class="detection-title"><div id="color-name" class="color-name">待機中</div><div id="detection-slot" class="detection-slot">SLOT --</div></div><div id="rgb" class="rgb">RGB -- / -- / --</div><div id="confidence" class="confidence">CONFIDENCE --</div></div>
        </div>
        <div><h2 class="section-title">自動運転</h2></div>
        <div class="primary-actions">
          <button class="primary action" data-action="sort">認識して仕分け</button>
          <button id="automatic-start" class="primary action" data-action="automatic-start">完全自動仕分けを開始</button>
          <button id="automatic-stop" class="action" data-action="automatic-stop" disabled>完全自動仕分けを停止</button>
        </div>
        <div><h2 class="section-title">手動操作</h2></div>
        <div class="manual-grid">
          <select id="manual-slot" aria-label="移動先スロット"></select>
          <button class="action" data-action="move">スロットへ移動</button>
          <button class="action" data-action="push">押す・戻す</button>
          <button class="action" data-action="home">現在位置を原点に</button>
        </div>
        <div id="message" class="message">カメラを準備しています</div>
      </aside>
    </div>
    <details>
      <summary>校正・機構設定</summary>
            <div class="calibration-layout">
                <fieldset class="settings-group">
                    <legend>スロット / ステッパー</legend>
                    <div class="field-grid">
                        <label>SLOT 0→9 可動量（フルステップ）<input id="travel" type="number" min="-100000" max="100000"></label>
                        <label>1フルステップ待ち時間（秒）<input id="delay" type="number" min="0" max="0.1" step="0.001"></label>
                        <label>全体位置調整（ステップ）<input id="position-shift" type="number" min="1" max="100000" value="1"></label>
                        <label>現在の位置オフセット<span id="position-offset" class="threshold">0 steps</span></label>
                    </div>
                    <div class="group-actions"><button id="save-stepper" class="action">ステッパー設定を適用</button></div>
                    <div class="group-actions"><button id="shift-left" class="action">左へずらす</button><button id="shift-right" class="action">右へずらす</button></div>
                    <div class="subsection-title">色別の排出先</div>
                    <div class="field-grid">
                        <label>認識色<select id="slot-color"></select></label>
                        <label>排出スロット<input id="calibration-slot" type="number" min="0" max="9" value="0"></label>
                    </div>
                    <div class="group-actions"><button id="save-slot" class="action">スロット割当を保存</button></div>
                </fieldset>
                <fieldset class="settings-group">
                    <legend>押し出しサーボ</legend>
                    <div class="field-grid">
                        <label>押し出し角度<input id="push-angle" type="number" min="0" max="180"></label>
                        <label>戻り角度<input id="rest-angle" type="number" min="0" max="180"></label>
                        <label>押し保持（秒）<input id="hold" type="number" min="0" max="10" step="0.05"></label>
                        <label>戻り待ち（秒）<input id="settle" type="number" min="0" max="10" step="0.05"></label>
                    </div>
                    <div class="group-actions"><button id="save-servo" class="action">サーボ設定を適用</button></div>
                </fieldset>
                <fieldset class="settings-group color-settings">
                    <legend>色認識</legend>
                    <div class="recognition-body">
                        <div>
                            <div class="field-grid">
                                <label>RGB許容幅（±）<input id="rgb-tolerance" type="number" min="0" max="255"></label>
                                <label>最低信頼度<input id="confidence-min" type="number" min="0" max="1" step="0.01"></label>
                            </div>
                            <div class="group-actions"><button id="save-recognition" class="action">判定設定を適用</button></div>
                            <div class="subsection-title">背景の校正</div>
                            <div class="field-grid">
                                <label>背景RGB<span id="background-rgb" class="threshold">未登録</span></label>
                                <label>背景RGB許容幅（±）<input id="background-tolerance" type="number" min="0" max="255" value="25"></label>
                            </div>
                            <div class="group-actions"><button id="save-background" class="action">背景設定を適用</button><button id="calibrate-background" class="action">ビーズなしの背景RGBを登録</button></div>
                            <div class="subsection-title">基準色の校正</div>
                            <label>校正する色<select id="calibration-color"></select></label>
                            <div class="group-actions"><button id="calibrate" class="action">現在のRGBを基準色に登録</button></div>
                        </div>
                        <div class="table-wrap">
                            <table class="color-table">
                                <thead><tr><th>認識色</th><th>基準RGB</th><th>RGB閾値</th><th>SLOT</th></tr></thead>
                                <tbody id="color-table-body"></tbody>
                            </table>
                        </div>
                    </div>
                </fieldset>
      </div>
    </details>
  </main>
  <script>
    const labels = {white:'白',pink:'ピンク',magenta:'マゼンタ',purple:'紫',blue:'青',cyan:'水色',green:'緑',green_tea:'緑茶',orange:'オレンジ',red:'赤',background:'ビーズなし',unknown:'判定外'};
    const stepperFields = {travel_steps:'travel',step_delay:'delay'};
    const servoFields = {push_angle:'push-angle',rest_angle:'rest-angle',hold_seconds:'hold',settle_seconds:'settle'};
    const recognitionFields = {minimum_confidence:'confidence-min',rgb_tolerance:'rgb-tolerance'};
    const fields = {...stepperFields,...servoFields,...recognitionFields};
    let configLoaded = false;
    let colors = [];
    const manualSlot = document.querySelector('#manual-slot');
    for (let slot = 0; slot < 10; slot++) manualSlot.add(new Option(`スロット ${slot}`, slot));
    function message(text, error=false) { const box=document.querySelector('#message'); box.textContent=text; box.classList.toggle('error',error); }
    async function request(path, method='POST', body=null) {
      const response = await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '操作に失敗しました');
      return data;
    }
        function showDetection(item, sampleCount=0) {
      if (!item) return;
      const [r,g,b]=item.rgb;
      document.querySelector('#swatch').style.background=`rgb(${r},${g},${b})`;
      document.querySelector('#color-name').textContent=labels[item.name] || item.name;
      document.querySelector('#detection-slot').textContent=`SLOT ${item.slot ?? '--'}`;
      document.querySelector('#rgb').textContent=`RGB ${r} / ${g} / ${b}`;
        document.querySelector('#confidence').textContent=`CONFIDENCE ${Math.round(item.confidence*100)}% / ${sampleCount} PIXELS`;
    }
    async function refresh() {
      try {
        const state=await request('/api/status','GET');
        showDetection(state.detection,state.camera.sample_count);
        document.querySelector('#slot').textContent=`SLOT ${state.current_slot}`;
        document.querySelector('#status-dot').classList.toggle('ready',state.camera.ready && state.hardware.mode!=='unavailable');
        const automatic=state.automatic;
        document.querySelector('#status-text').textContent=state.recognition_paused ? 'PUSHING / COLOR HOLD' : automatic.running ? (automatic.retrying ? 'AUTO / RETRYING' : automatic.waiting_for_bead ? 'AUTO / WAITING FOR BEAD' : 'AUTO / SORTING') : state.busy ? state.action.toUpperCase() : `${state.camera.ready?'CAMERA OK':'CAMERA WAIT'} / ${state.hardware.mode.toUpperCase()}`;
        document.querySelectorAll('.action').forEach(button => button.disabled=state.busy || automatic.running);
        document.querySelector('#automatic-start').disabled=state.busy || automatic.running;
        document.querySelector('#automatic-stop').disabled=!automatic.running || automatic.stop_requested;
        document.querySelector('#position-offset').textContent=`${state.config.position_offset_steps} steps`;
        document.querySelector('#background-rgb').textContent=state.config.background_rgb ? state.config.background_rgb.join(' / ') : '未登録';
        if (!configLoaded) document.querySelector('#background-tolerance').value=state.config.background_tolerance;
        if (!configLoaded) { for (const [name,id] of Object.entries(fields)) document.querySelector(`#${id}`).value=state.config[name]; configLoaded=true; }
        if (state.last_error) message(state.last_error,true);
        else if (state.camera.error) message(state.camera.error,true);
        else if (state.hardware.error) message(state.hardware.error,true);
        else if (automatic.stop_requested) message(`停止待ちです（仕分け済み ${automatic.sorted_count}個）`);
        else if (automatic.retrying) message(`色判定リトライ中（${Math.floor(automatic.retry_elapsed_seconds)} / ${automatic.retry_timeout_seconds}秒、再判定 ${automatic.retry_count}回、仕分け済み ${automatic.sorted_count}個）`);
        else if (automatic.running) message(`完全自動仕分け中（仕分け済み ${automatic.sorted_count}個）`);
        else if (!state.busy) message('常時認識中');
      } catch (error) { message(error.message,true); }
    }
    async function act(name) {
      try {
        message('実行中');
        let data;
        if (name==='move') data=await request('/api/move','POST',{slot:Number(manualSlot.value)});
        else if (name==='automatic-start') data=await request('/api/automatic/start');
        else if (name==='automatic-stop') data=await request('/api/automatic/stop');
        else data=await request(`/api/${name}`);
        if (name==='automatic-start') message('完全自動仕分けを開始しました');
        else if (name==='automatic-stop') message('完全自動仕分けの停止を要求しました');
        else if (data.color) message(`${labels[data.color] || data.color} → スロット ${data.slot ?? '-'}`);
        else if (data.name) message(`復帰後に${labels[data.name] || data.name}を認識`);
        else message('完了');
      } catch (error) { message(error.message,true); }
      await refresh();
    }
    document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click',()=>act(button.dataset.action)));
        async function saveSettings(path, fieldMap, successMessage) {
            const body={}; for (const [name,id] of Object.entries(fieldMap)) body[name]=Number(document.querySelector(`#${id}`).value);
            try { await request(path,'PUT',body); message(successMessage); } catch(error) { message(error.message,true); }
      await refresh();
        }
        document.querySelector('#save-stepper').addEventListener('click',()=>saveSettings('/api/config/stepper',stepperFields,'ステッパー設定を適用しました'));
        async function shiftPositions(direction) {
            const steps=Number(document.querySelector('#position-shift').value);
            try {
                const data=await request('/api/stepper/shift','POST',{direction,steps});
                message(`${direction==='right'?'右':'左'}へ${steps}ステップ調整しました（オフセット ${data.position_offset_steps}）`);
            } catch(error) { message(error.message,true); }
            await refresh();
        }
        document.querySelector('#shift-left').addEventListener('click',()=>shiftPositions('left'));
        document.querySelector('#shift-right').addEventListener('click',()=>shiftPositions('right'));
        document.querySelector('#save-servo').addEventListener('click',()=>saveSettings('/api/config/servo',servoFields,'サーボ設定を適用しました'));
        document.querySelector('#save-recognition').addEventListener('click',async()=>{
            await saveSettings('/api/config/recognition',recognitionFields,'判定設定を適用しました');
            await loadColors();
        });
        document.querySelector('#save-background').addEventListener('click',async()=>{
            const background_tolerance=Number(document.querySelector('#background-tolerance').value);
            try { await request('/api/config/background','PUT',{background_tolerance}); message('背景判定設定を適用しました'); } catch(error) { message(error.message,true); }
            await refresh();
        });
        document.querySelector('#calibrate-background').addEventListener('click',async()=>{
            try { await request('/api/calibrate/background'); message('背景RGBを登録しました'); } catch(error) { message(error.message,true); }
            await refresh();
        });
    document.querySelector('#calibrate').addEventListener('click',async()=>{
      const color=document.querySelector('#calibration-color').value;
            try { await request('/api/calibrate/color','POST',{color}); message(`${labels[color]}の基準RGBを校正しました`); await loadColors(); } catch(error) { message(error.message,true); }
      await refresh();
    });
        document.querySelector('#save-slot').addEventListener('click',async()=>{
            const color=document.querySelector('#slot-color').value;
            const slot=Number(document.querySelector('#calibration-slot').value);
            try { await request('/api/slots','PUT',{color,slot}); message(`${labels[color]}をスロット${slot}へ割り当てました`); await loadColors(); } catch(error) { message(error.message,true); }
            await refresh();
        });
        document.querySelector('#slot-color').addEventListener('change',event=>{
            const item=colors.find(color=>color.name===event.target.value);
            if (item) document.querySelector('#calibration-slot').value=item.slot;
        });
    async function loadColors() {
            colors=await request('/api/colors','GET');
            const calibrationSelect=document.querySelector('#calibration-color');
            const slotSelect=document.querySelector('#slot-color');
            const previousCalibration=calibrationSelect.value;
            const previousSlot=slotSelect.value;
            calibrationSelect.replaceChildren(); slotSelect.replaceChildren();
            const table=document.querySelector('#color-table-body'); table.replaceChildren();
            colors.forEach(item=>{
                calibrationSelect.add(new Option(item.label,item.name));
                slotSelect.add(new Option(item.label,item.name));
                const row=document.createElement('tr');
                row.innerHTML=`<td><span class="color-chip" style="background:rgb(${item.rgb.join(',')})"></span>${item.label}</td><td class="threshold">${item.rgb.join(' / ')}</td><td class="threshold">R ${item.rgb_min[0]}–${item.rgb_max[0]}<br>G ${item.rgb_min[1]}–${item.rgb_max[1]}<br>B ${item.rgb_min[2]}–${item.rgb_max[2]}</td><td>${item.slot}</td>`;
                table.append(row);
            });
            if (colors.some(item=>item.name===previousCalibration)) calibrationSelect.value=previousCalibration;
            if (colors.some(item=>item.name===previousSlot)) slotSelect.value=previousSlot;
            const selected=colors.find(item=>item.name===slotSelect.value);
            if (selected) document.querySelector('#calibration-slot').value=selected.slot;
    }
        loadColors().catch(error=>message(error.message,true)); refresh(); setInterval(refresh,300);
  </script>
</body>
</html>
"""