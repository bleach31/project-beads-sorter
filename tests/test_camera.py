"""Tests for camera bead-area measurement."""

import cv2
import numpy as np
from beads_sorter.vision.camera import CameraService, measure_bead_rgb


def test_camera_defaults_cover_physical_bead_area() -> None:
    camera = CameraService()
    assert camera.measurement_region == (0.16, 0.20, 0.98, 0.91)
    assert camera.background_rgb == (30, 30, 30)
    assert camera.background_tolerance == 25


def test_measurement_averages_the_whole_bead_without_background() -> None:
    frame = np.full((100, 120, 3), (170, 165, 160), dtype=np.uint8)
    cv2.ellipse(frame, (70, 50), (35, 40), 0, 0, 360, (35, 55, 210), -1)
    cv2.rectangle(frame, (36, 35), (104, 65), (45, 65, 200), -1)
    cv2.circle(frame, (82, 34), 5, (245, 245, 245), -1)
    rgb, mask = measure_bead_rgb(
        frame, region=(25, 5, 110, 95), background_rgb=(160, 165, 170)
    )
    assert 195 <= rgb[0] <= 215
    assert 50 <= rgb[1] <= 70
    assert 35 <= rgb[2] <= 50
    assert cv2.countNonZero(mask) > 3500
    assert mask[0, 0] == 0


def test_offset_side_view_and_noise() -> None:
    frame = np.full((100, 120, 3), 30, dtype=np.uint8)
    frame[15:45, 8:48] = (214, 46, 2)
    frame[80:85, 100:105] = (30, 200, 30)
    rgb, mask = measure_bead_rgb(frame, region=(0, 0, 120, 100))
    assert rgb == (2, 46, 214)
    assert cv2.countNonZero(mask) == 1200
    assert mask[82, 102] == 0


def test_visible_hole_is_not_included() -> None:
    frame = np.full((100, 120, 3), 30, dtype=np.uint8)
    cv2.circle(frame, (75, 50), 25, (167, 39, 124), -1)
    cv2.circle(frame, (75, 50), 10, (30, 30, 30), -1)
    rgb, mask = measure_bead_rgb(frame, region=(0, 0, 120, 100))
    assert rgb == (124, 39, 167)
    assert mask[50, 75] == 0
    assert mask[50, 90] == 255


def test_empty_background_and_small_noise_return_no_bead() -> None:
    frame = np.full((100, 120, 3), 30, dtype=np.uint8)
    frame[10:20, 10:20] = (100, 100, 100)
    rgb, mask = measure_bead_rgb(frame, region=(0, 0, 120, 100))
    assert rgb == (30, 30, 30)
    assert cv2.countNonZero(mask) == 0


def test_calibrated_background_and_tolerance() -> None:
    camera = CameraService()
    camera.configure_background((45, 40, 35), 12)
    frame = np.full((100, 120, 3), (40, 45, 50), dtype=np.uint8)
    rgb, mask = measure_bead_rgb(
        frame,
        region=(0, 0, 120, 100),
        background_rgb=camera.background_rgb,
        background_tolerance=camera.background_tolerance,
    )
    assert rgb == (45, 40, 35)
    assert cv2.countNonZero(mask) == 0
