"""Coordinate color recognition and bead-sorting hardware."""

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from beads_sorter.vision.color import ColorClassifier, ColorMatch, RGB


class SlotMover(Protocol):
    @property
    def current_slot(self) -> int: ...

    def move_to_slot(self, slot: int) -> int: ...


class Pusher(Protocol):
    def push_and_return(self) -> None: ...


@dataclass(frozen=True)
class SortResult:
    color: str
    rgb: RGB
    confidence: float
    slot: int
    steps: int


class SortController:
    """Run one complete recognize, position, and eject operation at a time."""

    def __init__(
        self,
        classifier: ColorClassifier,
        stepper: SlotMover,
        pusher: Pusher,
        slots: dict[str, int],
        *,
        minimum_confidence: float = 0.55,
    ) -> None:
        self.classifier = classifier
        self.stepper = stepper
        self.pusher = pusher
        self.slots = slots
        self.minimum_confidence = minimum_confidence
        self._lock = Lock()

    def recognize(self, rgb: RGB):
        return self.classifier.classify(rgb)

    def sort(self, rgb: RGB) -> SortResult:
        return self.sort_match(self.recognize(rgb))

    def sort_match(self, match: ColorMatch) -> SortResult:
        """Sort a bead using a color recognized while the pusher was at rest."""
        with self._lock:
            if match.confidence < self.minimum_confidence:
                raise ValueError(
                    f"Color confidence {match.confidence:.2f} is below "
                    f"{self.minimum_confidence:.2f}"
                )
            try:
                slot = self.slots[match.name]
            except KeyError as error:
                raise ValueError(f"No sorting slot configured for {match.name}") from error

            steps = self.stepper.move_to_slot(slot)
            self.pusher.push_and_return()
            return SortResult(
                color=match.name,
                rgb=match.rgb,
                confidence=match.confidence,
                slot=slot,
                steps=steps,
            )