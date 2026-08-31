#!/usr/bin/env python3

import argparse
import time
from gpiozero import OutputDevice


# BCM GPIO番号
GPIO_PINS = [17, 18, 27, 22]

# 28BYJ-48 + ULN2003用ハーフステップ駆動
SEQUENCE = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1],
]


def set_outputs(pins, pattern):
    for pin, value in zip(pins, pattern):
        pin.value = value


def release(pins):
    set_outputs(pins, [0, 0, 0, 0])


def main():
    parser = argparse.ArgumentParser(
        description="28BYJ-48ステッピングモーター動作テスト"
    )

    parser.add_argument(
        "steps",
        type=int,
        help="ステップ数。正数は正転、負数は逆転"
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.004,
        help="1ステップ間隔（秒）。初期値は0.004"
    )

    args = parser.parse_args()

    pins = [
        OutputDevice(pin, initial_value=False)
        for pin in GPIO_PINS
    ]

    sequence = SEQUENCE if args.steps > 0 else list(reversed(SEQUENCE))

    print(
        f"開始: steps={args.steps}, "
        f"delay={args.delay}秒"
    )

    try:
        for step in range(abs(args.steps)):
            pattern = sequence[step % len(sequence)]
            set_outputs(pins, pattern)
            time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n中断しました")

    finally:
        release(pins)

        for pin in pins:
            pin.close()

        print("励磁を解除しました")


if __name__ == "__main__":
    main()
