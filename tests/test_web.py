"""Tests for the web-controlled sorting flow."""

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

    def push_and_return(self) -> None:
        self.operations.append("push-and-return")

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
        "read:current",
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


def test_status_does_not_reclassify_live_frames() -> None:
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

    assert status.json()["detection"]["name"] == "red"
    assert operations == ["read:current"]


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
    assert pink["slot"] == 7


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