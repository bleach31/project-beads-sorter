"""Tests for table movement and the complete sorting operation."""

import pytest

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


def test_stepper_preserves_phase_when_reversing_direction() -> None:
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
    history_start = len(pins[0].history)
    stepper.shift_positions(-2)

    reverse_patterns = list(
        zip(*(pin.history[history_start:] for pin in pins))
    )
    assert reverse_patterns == [
        (0, 0, 1, 1),
        (0, 1, 1, 0),
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

    assert stepper.shift_positions(-12) == -12
    assert stepper.position_offset_steps == -12
    assert stepper.current_slot == 9
    assert stepper.move_to_slot(0) == 180
    assert stepper.current_slot == 0


def test_stepper_defaults_to_current_travel() -> None:
    stepper = StepperMotor(
        pin_factory=FakePin,
        sleep=lambda _seconds: None,
    )

    assert stepper.travel_steps == 350


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


def test_unknown_color_is_not_ejected() -> None:
    operations: list[str] = []

    class FakeStepper:
        current_slot = 0

        def move_to_slot(self, slot: int) -> int:
            operations.append(f"move:{slot}")
            self.current_slot = slot
            return 60

    class FakePusher:
        def push_and_return(self) -> None:
            operations.append("push-and-return")

    controller = SortController(
        ColorClassifier({"blue": (2, 46, 214)}, rgb_tolerance=10),
        FakeStepper(),
        FakePusher(),
        {"blue": 6},
    )

    with pytest.raises(ValueError, match="confidence"):
        controller.sort((255, 255, 255))

    assert operations == []