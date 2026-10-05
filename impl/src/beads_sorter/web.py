"""FastAPI operator interface for the bead sorter."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from threading import Lock
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from beads_sorter.controller import SortController
from beads_sorter.ejector.hardware import (
    HardwareUnavailableError,
    StepperMotor,
    SysfsServo,
)
from beads_sorter.vision.camera import CameraService, CameraUnavailableError
from beads_sorter.vision.color import ColorClassifier, ColorMatch

COLOR_LABELS = {
    "red": "赤",
    "orange": "オレンジ",
    "yellow": "黄",
    "green": "緑",
    "cyan": "水色",
    "blue": "青",
    "purple": "紫",
    "pink": "ピンク",
    "white": "白",
    "black": "黒",
    "unknown": "判定外",
}


class BusyError(RuntimeError):
    """Raised when another mechanical operation is already active."""


class UnavailableStepper:
    def __init__(self, error: str) -> None:
        self.error = error
        self.current_slot = 0
        self.travel_steps = 1536
        self.step_delay = 0.004

    def _raise(self) -> None:
        raise HardwareUnavailableError(self.error)

    def move_to_slot(self, slot: int) -> int:
        self._raise()
        return 0

    def set_home(self) -> None:
        self._raise()

    def configure(self, **_values: Any) -> None:
        self._raise()

    def close(self) -> None:
        pass


class SimulatedStepper:
    def __init__(self) -> None:
        self.current_slot = 0
        self.travel_steps = 1536
        self.step_delay = 0.004

    def move_to_slot(self, slot: int) -> int:
        old_position = round(self.current_slot * self.travel_steps / 9)
        new_position = round(slot * self.travel_steps / 9)
        steps = new_position - old_position
        self.current_slot = slot
        return steps

    def set_home(self) -> None:
        self.current_slot = 0

    def configure(self, *, travel_steps: int, step_delay: float) -> None:
        if travel_steps == 0:
            raise ValueError("Stepper travel must be non-zero")
        self.travel_steps = travel_steps
        self.step_delay = step_delay

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
    ) -> None:
        self.camera = camera or CameraService()
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
            except Exception as error:
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
        self.controller = SortController(classifier, self.stepper, self.pusher, slots)
        self._operation_lock = Lock()
        self._state_lock = Lock()
        self.busy = False
        self.action = "idle"
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.last_detection: ColorMatch | None = None
        self._recognition_paused = False

    def start(self) -> None:
        self.camera.start()

    def close(self) -> None:
        self.camera.stop()
        self.stepper.close()
        self.pusher.close()

    def execute(self, action: str, operation: Callable[[], Any]) -> Any:
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

    def recognize_current(
        self,
        *,
        after_sequence: int | None = None,
    ) -> ColorMatch:
        reading = self.camera.get_reading(after_sequence=after_sequence)
        match = self.controller.recognize(reading.rgb)
        with self._state_lock:
            self.last_detection = match
        return match

    def _refresh_live_detection(self) -> ColorMatch | None:
        reading = self.camera.latest()
        if reading is None:
            return None
        with self._state_lock:
            if self._recognition_paused:
                return self.last_detection
            self.last_detection = self.controller.recognize(reading.rgb)
            return self.last_detection

    def _push_with_recognition_paused(self) -> ColorMatch:
        with self._state_lock:
            self._recognition_paused = True
        try:
            self.pusher.push_and_return()
            latest = self.camera.latest()
            after_sequence = latest.sequence if latest is not None else None
            reading = self.camera.get_reading(after_sequence=after_sequence)
            match = self.controller.recognize(reading.rgb)
            with self._state_lock:
                self.last_detection = match
            return match
        finally:
            with self._state_lock:
                self._recognition_paused = False

    def sort_current(self):
        match = self._refresh_live_detection()
        if match is None:
            match = self.recognize_current()

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
            recognition_paused = self._recognition_paused
        return {
            "busy": self.busy,
            "action": self.action,
            "recognition_paused": recognition_paused,
            "camera": {
                "ready": reading is not None,
                "error": self.camera.error,
                "sample_count": reading.sample_count if reading is not None else 0,
            },
            "hardware": {
                "mode": self.hardware_mode,
                "error": self.hardware_error,
            },
            "current_slot": self.stepper.current_slot,
            "detection": detection,
            "last_result": self.last_result,
            "last_error": self.last_error,
            "config": self.config(),
        }

    def config(self) -> dict[str, Any]:
        return {
            "travel_steps": self.stepper.travel_steps,
            "step_delay": self.stepper.step_delay,
            "push_angle": self.pusher.push_angle,
            "rest_angle": self.pusher.rest_angle,
            "hold_seconds": self.pusher.hold_seconds,
            "settle_seconds": self.pusher.settle_seconds,
            "minimum_confidence": self.controller.minimum_confidence,
            "rgb_tolerance": self.controller.classifier.rgb_tolerance,
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


class ServoConfig(BaseModel):
    push_angle: int = Field(ge=0, le=180)
    rest_angle: int = Field(ge=0, le=180)
    hold_seconds: float = Field(ge=0, le=10)
    settle_seconds: float = Field(ge=0, le=10)


class RecognitionConfig(BaseModel):
    minimum_confidence: float = Field(ge=0, le=1)
    rgb_tolerance: int = Field(ge=0, le=255)


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

    @app.post("/api/calibrate")
    async def calibrate(request: CalibrationRequest) -> Any:
        def apply_calibration() -> dict[str, Any]:
            reading = runtime.camera.get_reading()
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
            with runtime._state_lock:
                runtime.controller.classifier.set_reference(
                    request.color,
                    reading.rgb,
                )
                runtime.last_detection = runtime.controller.recognize(reading.rgb)
            return {"color": request.color, "rgb": reading.rgb}

        return await run_action("calibrating", apply_color_calibration)

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
    .color-name { font: 700 28px/1 "Arial Narrow", "Noto Sans JP", sans-serif; }
    .rgb, .confidence { color: var(--muted); font: 12px/1.5 monospace; }
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
          <div><div id="color-name" class="color-name">待機中</div><div id="rgb" class="rgb">RGB -- / -- / --</div><div id="confidence" class="confidence">CONFIDENCE --</div></div>
        </div>
        <div><h2 class="section-title">自動運転</h2></div>
        <div class="primary-actions">
          <button class="primary action" data-action="sort">認識して仕分け</button>
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
                    </div>
                    <div class="group-actions"><button id="save-stepper" class="action">ステッパー設定を適用</button></div>
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
    const labels = {red:'赤',orange:'オレンジ',yellow:'黄',green:'緑',cyan:'水色',blue:'青',purple:'紫',pink:'ピンク',white:'白',black:'黒',unknown:'判定外'};
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
      document.querySelector('#rgb').textContent=`RGB ${r} / ${g} / ${b}`;
        document.querySelector('#confidence').textContent=`CONFIDENCE ${Math.round(item.confidence*100)}% / ${sampleCount} PIXELS`;
    }
    async function refresh() {
      try {
        const state=await request('/api/status','GET');
        showDetection(state.detection,state.camera.sample_count);
        document.querySelector('#slot').textContent=`SLOT ${state.current_slot}`;
        document.querySelector('#status-dot').classList.toggle('ready',state.camera.ready && state.hardware.mode!=='unavailable');
        document.querySelector('#status-text').textContent=state.recognition_paused ? 'PUSHING / COLOR HOLD' : state.busy ? state.action.toUpperCase() : `${state.camera.ready?'CAMERA OK':'CAMERA WAIT'} / ${state.hardware.mode.toUpperCase()}`;
        document.querySelectorAll('.action').forEach(button => button.disabled=state.busy);
        if (!configLoaded) { for (const [name,id] of Object.entries(fields)) document.querySelector(`#${id}`).value=state.config[name]; configLoaded=true; }
        if (state.last_error) message(state.last_error,true);
        else if (state.camera.error) message(state.camera.error,true);
        else if (state.hardware.error) message(state.hardware.error,true);
        else if (!state.busy) message('常時認識中');
      } catch (error) { message(error.message,true); }
    }
    async function act(name) {
      try {
        message('実行中');
        let data;
        if (name==='move') data=await request('/api/move','POST',{slot:Number(manualSlot.value)});
        else data=await request(`/api/${name}`);
        if (data.color) message(`${labels[data.color] || data.color} → スロット ${data.slot ?? '-'}`);
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
        document.querySelector('#save-servo').addEventListener('click',()=>saveSettings('/api/config/servo',servoFields,'サーボ設定を適用しました'));
        document.querySelector('#save-recognition').addEventListener('click',async()=>{
            await saveSettings('/api/config/recognition',recognitionFields,'判定設定を適用しました');
            await loadColors();
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