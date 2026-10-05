"""Tests for camera ROI sampling."""

import numpy as np

from beads_sorter.vision.camera import sample_roi_rgb


def test_roi_sampling_uses_multiple_points_and_rejects_one_outlier() -> None:
    target_bgr = (35, 45, 210)
    frame = np.full((60, 60, 3), target_bgr, dtype=np.uint8)

    rgb, points = sample_roi_rgb(
        frame,
        center=(30, 30),
        roi_size=40,
    )

    assert rgb == (210, 45, 35)
    assert len(points) == 9

    outlier_x, outlier_y = points[0]
    frame[outlier_y - 2 : outlier_y + 3, outlier_x - 2 : outlier_x + 3] = (
        255,
        255,
        255,
    )

    robust_rgb, _ = sample_roi_rgb(
        frame,
        center=(30, 30),
        roi_size=40,
    )

    assert robust_rgb == (210, 45, 35)