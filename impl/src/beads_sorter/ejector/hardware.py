"""Hardware drivers for the sorting table and bead pusher."""

import time
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Protocol


class HardwareUnavailableError(RuntimeError):
    """Raised when the configured Raspberry Pi hardware cannot be used."""


class DigitalOutput(Protocol):
    value: int

    def close(self) -> None: ...


FULL_STEP_SEQUENCE = (
    (1, 1, 0, 0),
    (0, 1, 1, 0),
    (0, 0, 1, 1),
    (1, 0, 0, 1),
)


def _gpio_output(pin_number: int) -> DigitalOutput:
    try:
        from gpiozero import OutputDevice
    except ImportError as error:
        raise HardwareUnavailableError(
            "gpiozero is required to control the stepper motor"
        ) from error
    return OutputDevice(pin_number, initial_value=False)


class StepperMotor:
    """Drive a 28BYJ-48 in full-step mode and track the table position."""

    def __init__(
        self,
        pins: tuple[int, int, int, int] = (17, 18, 27, 22),
        *,
        travel_steps: int = 1536,
        slot_count: int = 10,
        step_delay: float = 0.004,
        pin_factory: Callable[[int], DigitalOutput] = _gpio_output,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if travel_steps == 0 or slot_count < 2 or step_delay < 0:
            raise ValueError("Stepper travel must be non-zero and slots at least two")
        self.travel_steps = travel_steps
        self.slot_count = slot_count
        self.step_delay = step_delay
        self._sleep = sleep
        self._pins = tuple(pin_factory(pin) for pin in pins)
        self._position_steps = 0
        self._lock = Lock()

    @property
    def current_slot(self) -> int:
        slot = round(
            self._position_steps * (self.slot_count - 1) / self.travel_steps
        )
        return min(max(slot, 0), self.slot_count - 1)

    def set_home(self) -> None:
        """Mark the current physical table position as slot zero."""
        with self._lock:
            self._position_steps = 0

    def configure(self, *, travel_steps: int, step_delay: float) -> None:
        """Apply motion tuning while preserving the current logical slot."""
        if travel_steps == 0 or step_delay < 0:
            raise ValueError("Stepper travel must be non-zero")
        with self._lock:
            slot = self.current_slot
            self.travel_steps = travel_steps
            self.step_delay = step_delay
            self._position_steps = round(
                slot * self.travel_steps / (self.slot_count - 1)
            )

    def move_to_slot(self, slot: int) -> int:
        """Move within the configured bounded travel and return signed steps."""
        if not 0 <= slot < self.slot_count:
            raise ValueError(f"slot must be between 0 and {self.slot_count - 1}")

        with self._lock:
            target = round(slot * self.travel_steps / (self.slot_count - 1))
            steps = target - self._position_steps
            self._move_steps(steps)
            self._position_steps = target
            return steps

    def _move_steps(self, steps: int) -> None:
        sequence = FULL_STEP_SEQUENCE if steps >= 0 else tuple(
            reversed(FULL_STEP_SEQUENCE)
        )
        try:
            for step in range(abs(steps)):
                self._set_outputs(sequence[step % len(sequence)])
                self._sleep(self.step_delay)
        finally:
            self.release()

    def _set_outputs(self, pattern: tuple[int, int, int, int]) -> None:
        for pin, value in zip(self._pins, pattern):
            pin.value = value

    def release(self) -> None:
        self._set_outputs((0, 0, 0, 0))

    def close(self) -> None:
        with self._lock:
            self.release()
            for pin in self._pins:
                pin.close()


class SysfsServo:
    """Control an SG90 through the Raspberry Pi hardware PWM sysfs API."""

    def __init__(
        self,
        *,
        channel: int = 1,
        push_angle: int = 175,
        rest_angle: int = 90,
        hold_seconds: float = 0.35,
        settle_seconds: float = 0.35,
        pwm_root: Path = Path("/sys/class/pwm"),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 <= push_angle <= 180 or not 0 <= rest_angle <= 180:
            raise ValueError("Servo angles must be between 0 and 180")
        self.channel = channel
        self.push_angle = push_angle
        self.rest_angle = rest_angle
        self.hold_seconds = hold_seconds
        self.settle_seconds = settle_seconds
        self.pwm_root = pwm_root
        self._sleep = sleep
        self._pwm_path: Path | None = None
        self._lock = Lock()

    @staticmethod
    def _angle_to_duty_cycle(angle: int) -> int:
        return 500_000 + angle * 10_000

    def _find_pwm_chip(self) -> Path:
        for chip in sorted(self.pwm_root.glob("pwmchip*")):
            try:
                if int((chip / "npwm").read_text().strip()) > self.channel:
                    return chip
            except (OSError, ValueError):
                continue
        raise HardwareUnavailableError(
            f"No PWM chip with channel {self.channel} found under {self.pwm_root}"
        )

    def _ensure_pwm(self) -> Path:
        if self._pwm_path is not None:
            return self._pwm_path

        chip = self._find_pwm_chip()
        pwm_path = chip / f"pwm{self.channel}"
        if not pwm_path.exists():
            (chip / "export").write_text(str(self.channel))
            for _ in range(100):
                if pwm_path.exists():
                    break
                self._sleep(0.01)
        if not pwm_path.exists():
            raise HardwareUnavailableError(f"PWM channel did not appear at {pwm_path}")

        enable_path = pwm_path / "enable"
        if enable_path.read_text().strip() == "1":
            enable_path.write_text("0")
        (pwm_path / "period").write_text("20000000")
        self._pwm_path = pwm_path
        return pwm_path

    def _set_angle(self, angle: int) -> None:
        pwm_path = self._ensure_pwm()
        (pwm_path / "duty_cycle").write_text(
            str(self._angle_to_duty_cycle(angle))
        )
        if (pwm_path / "enable").read_text().strip() != "1":
            (pwm_path / "enable").write_text("1")

    def push_and_return(self) -> None:
        """Push one bead, return to rest, and release the servo."""
        with self._lock:
            self._set_angle(self.push_angle)
            try:
                self._sleep(self.hold_seconds)
            finally:
                self._set_angle(self.rest_angle)
                self._sleep(self.settle_seconds)
                if self._pwm_path is not None:
                    (self._pwm_path / "enable").write_text("0")

    def configure(
        self,
        *,
        push_angle: int,
        rest_angle: int,
        hold_seconds: float,
        settle_seconds: float,
    ) -> None:
        """Apply pusher tuning values for subsequent operations."""
        if not 0 <= push_angle <= 180 or not 0 <= rest_angle <= 180:
            raise ValueError("Servo angles must be between 0 and 180")
        if hold_seconds < 0 or settle_seconds < 0:
            raise ValueError("Servo timing must not be negative")
        with self._lock:
            self.push_angle = push_angle
            self.rest_angle = rest_angle
            self.hold_seconds = hold_seconds
            self.settle_seconds = settle_seconds

    def close(self) -> None:
        with self._lock:
            if self._pwm_path is not None:
                (self._pwm_path / "enable").write_text("0")