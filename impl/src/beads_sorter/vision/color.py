"""Color classification for beads viewed by the camera."""

from dataclasses import dataclass
from math import sqrt
from typing import Mapping

RGB = tuple[int, int, int]

DEFAULT_COLOR_REFERENCES: dict[str, RGB] = {
    "white": (191, 191, 184),
    "pink": (229, 92, 165),
    "magenta": (215, 12, 118),
    "purple": (124, 39, 167),
    "blue": (2, 46, 214),
    "cyan": (15, 170, 210),
    "green": (37, 183, 88),
    "green_tea": (153, 224, 48),
    "orange": (249, 158, 1),
    "red": (226, 12, 8),
}


@dataclass(frozen=True)
class ColorMatch:
    """Nearest configured color and its match quality."""

    name: str
    rgb: RGB
    confidence: float


@dataclass(frozen=True)
class RGBThreshold:
    """Inclusive RGB channel limits used to accept a color candidate."""

    minimum: RGB
    maximum: RGB

    def contains(self, rgb: RGB) -> bool:
        return all(
            lower <= channel <= upper
            for channel, lower, upper in zip(rgb, self.minimum, self.maximum)
        )


class ColorClassifier:
    """Classify an RGB sample using nearest-reference distance."""

    def __init__(
        self,
        references: Mapping[str, RGB] | None = None,
        *,
        rgb_tolerance: int = 80,
    ) -> None:
        configured = DEFAULT_COLOR_REFERENCES if references is None else references
        if not configured:
            raise ValueError("At least one color reference is required")
        if not 0 <= rgb_tolerance <= 255:
            raise ValueError("RGB tolerance must be between 0 and 255")
        self.references = dict(configured)
        self.rgb_tolerance = rgb_tolerance

    def classify(self, rgb: RGB) -> ColorMatch:
        """Return the nearest reference whose RGB threshold contains the sample."""
        if any(channel < 0 or channel > 255 for channel in rgb):
            raise ValueError("RGB channels must be between 0 and 255")

        candidates = {
            name: reference
            for name, reference in self.references.items()
            if self.threshold_for(name).contains(rgb)
        }
        if not candidates:
            return ColorMatch(name="unknown", rgb=rgb, confidence=0.0)

        name, reference = min(
            candidates.items(),
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

    def set_rgb_tolerance(self, tolerance: int) -> None:
        if not 0 <= tolerance <= 255:
            raise ValueError("RGB tolerance must be between 0 and 255")
        self.rgb_tolerance = tolerance

    def threshold_for(self, name: str) -> RGBThreshold:
        try:
            reference = self.references[name]
        except KeyError as error:
            raise ValueError(f"Unknown color: {name}") from error
        return RGBThreshold(
            minimum=tuple(
                max(0, channel - self.rgb_tolerance) for channel in reference
            ),
            maximum=tuple(
                min(255, channel + self.rgb_tolerance) for channel in reference
            ),
        )

    @staticmethod
    def _distance(left: RGB, right: RGB) -> float:
        return sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))