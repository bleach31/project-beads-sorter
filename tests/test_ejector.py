"""Tests for table movement and the complete sorting operation."""

from beads_sorter.controller import SortController
from beads_sorter.ejector.hardware import StepperMotor, SysfsServo
from beads_sorter.vision.color import ColorClassifier


class FakePin:
    def __init__(self, number: int) -> None:
        self.number = number
        self._value = 0
        self.history: list[int] = []
        self.closed = False

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = value
        self.history.append(value)

    def close(self) -> None:
        self.closed = True


def test_stepper_uses_dual_coil_full_step_sequence() -> None:
    pins: list[FakePin] = []

    def make_pin(number: int) -> FakePin:
        pin = FakePin(number)
        pins.append(pin)
        return pin

    stepper = StepperMotor(
        travel_steps=4,
        slot_count=2,
        step_delay=0,
        pin_factory=make_pin,
        sleep=lambda _seconds: None,
    )

    stepper.move_to_slot(1)

    patterns = list(zip(*(pin.history for pin in pins)))
    assert patterns == [
        (1, 1, 0, 0),
        (0, 1, 1, 0),
        (0, 0, 1, 1),
        (1, 0, 0, 1),
        (0, 0, 0, 0),
    ]


def test_stepper_stays_within_adjustable_bounded_travel() -> None:
    pins: list[FakePin] = []

    def make_pin(number: int) -> FakePin:
        pin = FakePin(number)
        pins.append(pin)
        return pin

    stepper = StepperMotor(
        travel_steps=90,
        slot_count=10,
        step_delay=0,
        pin_factory=make_pin,
        sleep=lambda _seconds: None,
    )

    assert stepper.move_to_slot(9) == 90
    assert stepper.current_slot == 9
    assert stepper.move_to_slot(1) == -80
    assert stepper.current_slot == 1
    assert all(pin.value == 0 for pin in pins)

    stepper.configure(travel_steps=-180, step_delay=0)

    assert stepper.current_slot == 1
    assert stepper.move_to_slot(9) == -160


def test_servo_defaults_match_pusher_mechanism() -> None:
    servo = SysfsServo()

    assert servo.rest_angle == 90
    assert servo.push_angle == 175


def test_sort_moves_before_pushing_and_returning() -> None:
    operations: list[str] = []

    class FakeStepper:
        current_slot = 0

        def move_to_slot(self, slot: int) -> int:
            operations.append(f"move:{slot}")
            self.current_slot = slot
            return 20

    class FakePusher:
        def push_and_return(self) -> None:
            operations.append("push-and-return")

    controller = SortController(
        ColorClassifier({"red": (220, 30, 30)}),
        FakeStepper(),
        FakePusher(),
        {"red": 3},
    )

    result = controller.sort((215, 35, 30))

    assert operations == ["move:3", "push-and-return"]
    assert result.color == "red"
    assert result.slot == 3
    assert result.steps == 20