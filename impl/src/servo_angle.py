import argparse
import time

import RPi.GPIO as GPIO


SERVO_PIN = 21
FREQUENCY = 50
MOVE_SECONDS = 1.0
MIN_ANGLE = 0.0
MAX_ANGLE = 180.0
MIN_DUTY = 2.5
MAX_DUTY = 11.5


def angle_to_duty_cycle(angle: float) -> float:
    if not MIN_ANGLE <= angle <= MAX_ANGLE:
        raise ValueError(f"angle must be between {MIN_ANGLE:g} and {MAX_ANGLE:g}")

    return MIN_DUTY + (MAX_DUTY - MIN_DUTY) * (angle / MAX_ANGLE)


def move_to_angle(angle: float) -> None:
    duty_cycle = angle_to_duty_cycle(angle)
    pwm = None

    GPIO.setmode(GPIO.BCM)
    try:
        GPIO.setup(SERVO_PIN, GPIO.OUT)
        pwm = GPIO.PWM(SERVO_PIN, FREQUENCY)
        pwm.start(duty_cycle)
        time.sleep(MOVE_SECONDS)
        print(f"Angle: {angle:g} degrees ({duty_cycle:.1f}% duty cycle)")
    finally:
        if pwm is not None:
            pwm.stop()
            # rpi-lgpio's PWM destructor calls stop, so run it before cleanup.
            del pwm
        GPIO.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Move the servo to an angle.")
    parser.add_argument("angle", type=float, help="angle from 0 to 180 degrees")
    args = parser.parse_args()

    try:
        move_to_angle(args.angle)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()