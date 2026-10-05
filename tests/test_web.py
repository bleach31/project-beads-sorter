"""Tests for the web-controlled sorting flow."""

from collections.abc import Callable

from fastapi.testclient import TestClient

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

    def __init__(self, operations: list[str]) -> None:
        self.operations = operations

    def move_to_slot(self, slot: int) -> int:
        self.operations.append(f"move:{slot}")
        self.current_slot = slot
        return 10

    def set_home(self) -> None:
        self.current_slot = 0

    def configure(self, *, travel_steps: int, step_delay: float) -> None:
        self.travel_steps = travel_steps
        self.step_delay = step_delay

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
    assert response.json()["slot"] == 0
    assert status.json()["detection"]["name"] == "blue"
    assert operations == [
        "move:0",
        "push-and-return",
        "read-after:1",
    ]


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
    assert red["rgb_min"] == [185, 20, 20]
    assert red["rgb_max"] == [235, 70, 70]


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