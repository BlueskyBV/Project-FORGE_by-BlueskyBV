"""What the compiler refuses."""

from __future__ import annotations

__all__ = ["GapError", "PlanError"]


class PlanError(ValueError):
    """A spec the compiler must not plan, with the item and field it rests on.

    A spec with an issue its layout hasn't settled, a spec not locked when a
    verdict is wanted, or a construction asked of an item it can't make.
    """

    def __init__(self, message: str, *, item: str | None = None, at: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.item = item
        self.at = at

    def __str__(self) -> str:
        where = f"{self.item}: " if self.item else ""
        return f"{where}{self.message}" + (f" ({self.at})" if self.at else "")


class GapError(PlanError):
    """A determinate item no construction is written for, and why: the plan's gap (docs/V2-stage4.md 4.9)."""
