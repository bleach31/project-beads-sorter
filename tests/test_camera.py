"""Tests for camera bead-area measurement."""

import cv2
import numpy as np

from beads_sorter.vision.camera import measure_bead_rgb


def test_measurement_averages_the_whole_bead_without_background() -> None:
    frame = np.full((100, 120, 3), (170, 165, 160), dtype=np.uint8)
    cv2.ellipse(frame, (70, 50), (35, 40), 0, 0, 360, (35, 55, 210), -1)
    cv2.rectangle(frame, (36, 35), (104, 65), (45, 65, 200), -1)
    cv2.circle(frame, (82, 34), 5, (245, 245, 245), -1)

    rgb, bead_mask = measure_bead_rgb(
        frame,
        region=(25, 5, 110, 95),
        seed=(60, 50),
        color_tolerance=55,
    )

    assert 195 <= rgb[0] <= 215
    assert 50 <= rgb[1] <= 70
    assert 35 <= rgb[2] <= 50
    assert cv2.countNonZero(bead_mask) > 3_500
    assert bead_mask[0, 0] == 0