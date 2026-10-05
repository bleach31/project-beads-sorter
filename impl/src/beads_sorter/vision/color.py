"""Color classification for beads viewed by the camera."""

from dataclasses import dataclass
from math import sqrt
from typing import Mapping

RGB = tuple[int, int, int]

DEFAULT_COLOR_REFERENCES: dict[str, RGB] = {
    "red": (210, 45, 45),
    "orange": (235, 125, 35),
    "yellow": (225, 205, 45),
    "green": (55, 155, 75),
    "cyan": (55, 175, 185),
    "blue": (55, 90, 190),
    "purple": (135, 75, 170),
    "pink": (225, 125, 165),
    "white": (225, 225, 220),
    "black": (35, 35, 35),
}


@dataclass(frozen=True)
class ColorMatch:
    """Nearest configured color and its match quality."""

    name: str
    rgb: RGB
    confidence: float


class ColorClassifier:
    """Classify an RGB sample using nearest-reference distance."""

    def __init__(self, references: Mapping[str, RGB] | None = None) -> None:
        configured = references or DEFAULT_COLOR_REFERENCES
        if not configured:
            raise ValueError("At least one color reference is required")
        self.references = dict(configured)

    def classify(self, rgb: RGB) -> ColorMatch:
        """Return the reference color nearest to the supplied RGB value."""
        if any(channel < 0 or channel > 255 for channel in rgb):
            raise ValueError("RGB channels must be between 0 and 255")

        name, reference = min(
            self.references.items(),
            key=lambda item: self._distance(rgb, item[1]),
        )
        distance = self._distance(rgb, reference)
        max_distance = sqrt(3 * 255**2)
        confidence = max(0.0, 1.0 - distance / max_distance)
        return ColorMatch(name=name, rgb=rgb, confidence=confidence)

    def set_reference(self, name: str, rgb: RGB) -> None:
        """Replace one reference color with a camera calibration sample."""
        if name not in self.references:
            raise ValueError(f"Unknown color: {name}")
        if any(channel < 0 or channel > 255 for channel in rgb):
            raise ValueError("RGB channels must be between 0 and 255")
        self.references[name] = rgb

    @staticmethod
    def _distance(left: RGB, right: RGB) -> float:
        return sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))