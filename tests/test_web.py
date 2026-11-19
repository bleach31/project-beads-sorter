"""Tests for the web-controlled sorting flow."""

from collections.abc import Callable
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

import beads_sorter.web as web

from beads_sorter.vision.camera import CameraReading
from beads_sorter.web import AppRuntime, create_app


class FakeCamera:
    error = None

    def __init__(self, operations: list[str] | None = None) -> None:
        self.operations = operations
        self.reading = CameraReading((210, 45, 45), b"jpeg", 1)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def latest(self) -> CameraReading:
        return self.reading

    def get_reading(
        self,
        timeout: float = 2.0,
        *,
        after_sequence: int | None = None,
    ) -> CameraReading:
        del timeout
        if self.operations is not None:
            label = (
                f"read-after:{after_sequence}"
                if after_sequence is not None
                else "read:current"
            )
            self.operations.append(label)
        if after_sequence is not None:
            self.reading = CameraReading(
                (55, 90, 190),
                b"next-jpeg",
                after_sequence + 1,
            )
        return self.reading

    def frames(self):
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\njpeg\r\n"


class FakeStepper:
    current_slot = 0
    travel_steps = 90
    step_delay = 0
    position_offset_steps = 0

    def __init__(self, operations: list[str]) -> None:
        self.operations = operations

    def move_to_slot(self, slot: int) -> int:
        self.operations.append(f"move:{slot}")
        self.current_slot = slot
        return 10

    def set_home(self) -> None:
        self.current_slot = 0
        self.position_offset_steps = 0

    def configure(self, *, travel_steps: int, step_delay: float) -> None:
        self.travel_steps = travel_steps
        self.step_delay = step_delay

    def shift_positions(self, steps: int) -> int:
        self.operations.append(f"shift:{steps}")
        self.position_offset_steps += steps
        return steps

    def close(self) -> None:
        pass


class FakePusher:
    push_angle = 175
    rest_angle = 90
    hold_seconds = 0
    settle_seconds = 0

    def __init__(self, operations: list[str]) -> None:
        self.operations = operations
        self.on_push: Callable[[], None] | None = None

    def push_and_return(self) -> None:
        self.operations.append("push-and-return")
        if self.on_push is not None:
            self.on_push()

    def configure(self, **values) -> None:
        for name, value in values.items():
            setattr(self, name, value)

    def close(self) -> None:
        pass


def test_sort_endpoint_runs_complete_flow() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(operations),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/sort")
        status = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["color"] == "red"
    assert response.json()["slot"] == 9
    assert status.json()["detection"]["name"] == "blue"
    assert operations == [
        "move:9",
        "push-and-return",
        "read-after:1",
    ]


def test_unknown_color_is_not_sorted() -> None:
    operations: list[str] = []
    camera = FakeCamera(operations)
    camera.reading = CameraReading((0, 255, 0), b"unknown", 1)
    runtime = AppRuntime(
        camera,
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/sort")
        status = client.get("/api/status")

    assert response.status_code == 422
    assert status.json()["detection"]["name"] == "unknown"
    assert status.json()["detection"]["slot"] is None
    assert operations == []


def test_calibrated_background_is_not_sorted() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(operations),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        calibration = client.post("/api/calibrate/background")
        response = client.post("/api/sort")
        status = client.get("/api/status")

    assert calibration.status_code == 200
    assert calibration.json()["background_rgb"] == [210, 45, 45]
    assert response.status_code == 422
    assert status.json()["detection"]["name"] == "background"
    assert status.json()["detection"]["slot"] is None
    assert operations == ["read:current"]


def test_background_tolerance_can_be_adjusted_separately() -> None:
    runtime = AppRuntime(FakeCamera(), FakeStepper([]), FakePusher([]))

    with TestClient(create_app(runtime)) as client:
        response = client.put(
            "/api/config/background",
            json={"background_tolerance": 12},
        )

    assert response.status_code == 200
    assert response.json()["background_tolerance"] == 12
    assert runtime.controller.classifier.rgb_tolerance == 80


def test_automatic_mode_waits_when_background_is_detected() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(operations),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        client.post("/api/calibrate/background")
        start = client.post("/api/automatic/start")
        deadline = monotonic() + 2
        state = client.get("/api/status").json()
        while (
            not state["automatic"]["waiting_for_bead"]
            and monotonic() < deadline
        ):
            sleep(0.01)
            state = client.get("/api/status").json()
        stop = client.post("/api/automatic/stop")

    assert start.status_code == 200
    assert stop.status_code == 200
    assert state["automatic"]["running"] is True
    assert state["automatic"]["waiting_for_bead"] is True
    assert state["automatic"]["sorted_count"] == 0
    assert state["last_error"] is None
    assert operations == ["read:current"]


def test_automatic_mode_sorts_then_waits_for_a_changed_bead() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(operations),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        start = client.post("/api/automatic/start")
        deadline = monotonic() + 2
        state = client.get("/api/status").json()
        while (
            state["automatic"]["sorted_count"] < 1
            or not state["automatic"]["waiting_for_bead"]
        ) and monotonic() < deadline:
            sleep(0.01)
            state = client.get("/api/status").json()

        manual = client.post("/api/move", json={"slot": 3})
        stop = client.post("/api/automatic/stop")
        deadline = monotonic() + 2
        while state["automatic"]["running"] and monotonic() < deadline:
            sleep(0.01)
            state = client.get("/api/status").json()

    assert start.status_code == 200
    assert state["automatic"]["sorted_count"] == 1
    assert state["automatic"]["running"] is False
    assert manual.status_code == 409
    assert stop.status_code == 200
    assert operations[:3] == ["move:9", "push-and-return", "read-after:1"]


def wait_for_automatic(runtime: AppRuntime, predicate) -> dict:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        status = runtime.automatic_status()
        if predicate(status):
            return status
        sleep(0.005)
    raise AssertionError(f"Automatic state did not change: {status}")


@pytest.mark.parametrize("low_confidence", [False, True])
def test_automatic_retries_then_sorts(
    monkeypatch: pytest.MonkeyPatch, low_confidence: bool
) -> None:
    monkeypatch.setattr(web, "AUTO_COLOR_RETRY_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(web, "AUTO_COLOR_RETRY_TIMEOUT_SECONDS", 0.5)
    operations: list[str] = []
    camera = FakeCamera(operations)
    camera.reading = CameraReading(
        (210, 45, 45) if low_confidence else (0, 255, 0), b"jpeg", 1
    )
    runtime = AppRuntime(camera, FakeStepper(operations), FakePusher(operations))
    if low_confidence:
        runtime.controller.minimum_confidence = 0.99

    with TestClient(create_app(runtime)) as client:
        client.post("/api/automatic/start")
        wait_for_automatic(runtime, lambda s: s["retrying"])
        status = client.get("/api/status").json()
        assert status["automatic"]["retrying"]
        assert status["automatic"]["retry_timeout_seconds"] == 0.5
        assert operations == []
        camera.reading = CameraReading((226, 12, 8), b"jpeg", 2)
        wait_for_automatic(runtime, lambda s: s["sorted_count"] == 1)
        assert not runtime.automatic_status()["retrying"]

    assert operations[:3] == ["move:9", "push-and-return", "read-after:2"]


def test_automatic_retry_times_out_without_reusing_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "AUTO_COLOR_RETRY_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(web, "AUTO_COLOR_RETRY_TIMEOUT_SECONDS", 0.15)
    operations: list[str] = []
    camera = FakeCamera(operations)
    camera.reading = CameraReading((0, 255, 0), b"jpeg", 1)
    runtime = AppRuntime(camera, FakeStepper(operations), FakePusher(operations))

    with TestClient(create_app(runtime)) as client:
        client.post("/api/automatic/start")
        wait_for_automatic(runtime, lambda s: s["retrying"])
        sleep(0.04)
        assert runtime.automatic_status()["retry_count"] == 0
        camera.reading = CameraReading((0, 255, 0), b"jpeg", 2)
        wait_for_automatic(runtime, lambda s: s["retry_count"] == 1)
        wait_for_automatic(runtime, lambda s: not s["running"])
        status = client.get("/api/status").json()

    assert "Color recognition timed out" in status["last_error"]
    assert not status["automatic"]["retrying"]
    assert status["automatic"]["sorted_count"] == 0
    assert operations == []


def test_automatic_retry_can_be_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "AUTO_COLOR_RETRY_INTERVAL_SECONDS", 10.0)
    operations: list[str] = []
    camera = FakeCamera(operations)
    camera.reading = CameraReading((0, 255, 0), b"jpeg", 1)
    runtime = AppRuntime(camera, FakeStepper(operations), FakePusher(operations))

    with TestClient(create_app(runtime)) as client:
        client.post("/api/automatic/start")
        wait_for_automatic(runtime, lambda s: s["retrying"])
        client.post("/api/automatic/stop")
        wait_for_automatic(runtime, lambda s: not s["running"])
        assert runtime.last_error is None
        assert not runtime.automatic_status()["retrying"]

    assert operations == []


def test_automatic_retry_returns_to_background_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "AUTO_COLOR_RETRY_INTERVAL_SECONDS", 0.02)
    operations: list[str] = []
    camera = FakeCamera(operations)
    camera.reading = CameraReading((0, 255, 0), b"jpeg", 1)
    runtime = AppRuntime(camera, FakeStepper(operations), FakePusher(operations))
    runtime.background_rgb = (0, 0, 0)

    with TestClient(create_app(runtime)) as client:
        client.post("/api/automatic/start")
        wait_for_automatic(runtime, lambda s: s["retrying"])
        camera.reading = CameraReading((0, 0, 0), b"jpeg", 2)
        status = wait_for_automatic(runtime, lambda s: s["waiting_for_bead"])
        assert not status["retrying"]
        assert status["running"]
        assert runtime.last_error is None

    assert operations == []


def test_automatic_mode_accepts_stable_same_color() -> None:
    class ChangingCamera(FakeCamera):
        def __init__(self) -> None:
            super().__init__()
            self.readings = iter(
                [
                    CameraReading((226, 12, 8), b"same", 1),
                    CameraReading((226, 12, 8), b"same", 2),
                    CameraReading((226, 12, 8), b"same", 3),
                ]
            )
            self.reading = CameraReading((226, 12, 8), b"same", 0)

        def latest(self) -> CameraReading:
            self.reading = next(
                self.readings,
                CameraReading(
                    self.reading.rgb,
                    self.reading.jpeg,
                    self.reading.sequence + 1,
                ),
            )
            return self.reading

    runtime = AppRuntime(
        ChangingCamera(),
        FakeStepper([]),
        FakePusher([]),
        automatic_stability_seconds=0.01,
    )

    assert runtime._wait_for_stable_reading() is True


def test_manual_push_recognizes_only_after_return() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(operations),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/push")

    assert response.status_code == 200
    assert response.json()["name"] == "blue"
    assert operations == ["push-and-return", "read-after:1"]


def test_stepper_positions_can_shift_left_and_right() -> None:
    operations: list[str] = []
    stepper = FakeStepper(operations)
    runtime = AppRuntime(FakeCamera(), stepper, FakePusher(operations))

    with TestClient(create_app(runtime)) as client:
        right = client.post(
            "/api/stepper/shift",
            json={"direction": "right", "steps": 12},
        )
        left = client.post(
            "/api/stepper/shift",
            json={"direction": "left", "steps": 5},
        )

    assert right.status_code == 200
    assert right.json()["position_offset_steps"] == 12
    assert left.status_code == 200
    assert left.json()["position_offset_steps"] == 7
    assert operations == ["shift:12", "shift:-5"]


def test_stepper_shift_uses_slot_direction_for_negative_travel() -> None:
    operations: list[str] = []
    stepper = FakeStepper(operations)
    stepper.travel_steps = -90
    runtime = AppRuntime(FakeCamera(), stepper, FakePusher(operations))

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/stepper/shift",
            json={"direction": "right", "steps": 8},
        )

    assert response.status_code == 200
    assert response.json()["moved_steps"] == -8
    assert response.json()["position_offset_steps"] == 8
    assert operations == ["shift:-8"]


def test_status_continuously_reclassifies_live_frames() -> None:
    operations: list[str] = []
    camera = FakeCamera(operations)
    runtime = AppRuntime(
        camera,
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        assert client.post("/api/recognize").json()["name"] == "red"
        camera.reading = CameraReading((55, 90, 190), b"later", 2)
        status = client.get("/api/status")

    assert status.json()["detection"]["name"] == "blue"
    assert status.json()["detection"]["slot"] == 4
    assert operations == ["read:current"]


def test_detection_is_frozen_only_while_pusher_is_moving() -> None:
    operations: list[str] = []
    camera = FakeCamera(operations)
    pusher = FakePusher(operations)
    runtime = AppRuntime(camera, FakeStepper(operations), pusher)
    detection_during_push: list[str] = []

    runtime.recognize_current()
    camera.reading = CameraReading((55, 90, 190), b"pusher", 2)
    pusher.on_push = lambda: detection_during_push.append(
        runtime.status()["detection"]["name"]
    )

    match = runtime.push_and_recognize()

    assert detection_during_push == ["red"]
    assert match.name == "blue"
    assert runtime.status()["detection"]["name"] == "blue"
    assert operations == ["read:current", "push-and-return", "read-after:2"]


def test_calibration_uses_current_camera_sample_and_slot() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/calibrate",
            json={"color": "pink", "slot": 7},
        )
        colors = client.get("/api/colors").json()

    assert response.status_code == 200
    pink = next(item for item in colors if item["name"] == "pink")
    assert pink["rgb"] == [210, 45, 45]
    assert pink["rgb_min"] == [130, 0, 0]
    assert pink["rgb_max"] == [255, 125, 125]
    assert pink["slot"] == 7


def test_color_and_slot_can_be_calibrated_separately() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        color_response = client.post(
            "/api/calibrate/color",
            json={"color": "green"},
        )
        slot_response = client.put(
            "/api/slots",
            json={"color": "green", "slot": 8},
        )
        colors = client.get("/api/colors").json()

    green = next(item for item in colors if item["name"] == "green")
    assert color_response.status_code == 200
    assert slot_response.status_code == 200
    assert green["rgb"] == [210, 45, 45]
    assert green["slot"] == 8


def test_recognition_threshold_can_be_adjusted_separately() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.put(
            "/api/config/recognition",
            json={"minimum_confidence": 0.65, "rgb_tolerance": 25},
        )
        red = next(
            item for item in client.get("/api/colors").json()
            if item["name"] == "red"
        )

    assert response.status_code == 200
    assert response.json()["rgb_tolerance"] == 25
    assert red["rgb_min"] == [201, 0, 0]
    assert red["rgb_max"] == [251, 37, 33]


def test_calibration_page_separates_controls_and_lists_thresholds() -> None:
    operations: list[str] = []
    runtime = AppRuntime(
        FakeCamera(),
        FakeStepper(operations),
        FakePusher(operations),
    )

    with TestClient(create_app(runtime)) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert "スロット / ステッパー" in page.text
    assert "押し出しサーボ" in page.text
    assert "RGB閾値" in page.text
    assert 'id="color-table-body"' in page.text
    assert 'id="detection-slot"' in page.text
    assert 'id="automatic-start"' in page.text
    assert 'id="automatic-stop"' in page.text
    assert 'id="position-shift"' in page.text
    assert 'id="shift-left"' in page.text
    assert 'id="shift-right"' in page.text
    assert 'id="background-rgb"' in page.text
    assert 'id="background-tolerance"' in page.text
    assert 'id="calibrate-background"' in page.text


def test_motion_range_can_be_adjusted_from_api() -> None:
    operations: list[str] = []
    stepper = FakeStepper(operations)
    runtime = AppRuntime(FakeCamera(), stepper, FakePusher(operations))

    with TestClient(create_app(runtime)) as client:
        response = client.put(
            "/api/config",
            json={
                "travel_steps": -1800,
                "step_delay": 0.005,
                "push_angle": 175,
                "rest_angle": 90,
                "hold_seconds": 0.4,
                "settle_seconds": 0.4,
                "minimum_confidence": 0.6,
            },
        )

    assert response.status_code == 200
    assert response.json()["travel_steps"] == -1800
    assert stepper.travel_steps == -1800