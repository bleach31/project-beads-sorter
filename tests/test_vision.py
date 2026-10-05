"""Tests for bead color classification."""

import pytest

from beads_sorter.vision.color import ColorClassifier


def test_classifier_matches_nearest_reference() -> None:
    classifier = ColorClassifier(
        {
            "red": (220, 30, 30),
            "blue": (30, 30, 220),
        }
    )

    match = classifier.classify((205, 40, 35))

    assert match.name == "red"
    assert match.rgb == (205, 40, 35)
    assert 0.9 < match.confidence <= 1.0


def test_classifier_rejects_invalid_rgb() -> None:
    classifier = ColorClassifier()

    with pytest.raises(ValueError, match="between 0 and 255"):
        classifier.classify((256, 0, 0))


def test_classifier_uses_displayable_rgb_thresholds() -> None:
    classifier = ColorClassifier(
        {"red": (220, 30, 30)},
        rgb_tolerance=20,
    )

    threshold = classifier.threshold_for("red")

    assert threshold.minimum == (200, 10, 10)
    assert threshold.maximum == (240, 50, 50)
    assert classifier.classify((230, 40, 35)).name == "red"
    assert classifier.classify((230, 40, 80)).name == "unknown"