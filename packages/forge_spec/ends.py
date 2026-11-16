"""A cut's end condition: how far it goes into the material (4b.0c item 2a; V2-stage4b-0c.md, 3.5).

Today's two: **blind** to a depth, and **through all** the material under
its mouth, as each program's own model of the material defines it. Every
program reads a cut's end through :func:`end_of`, so item 2b's conditions
(through the next face that covers it, up to a face, a vertex or a body,
an offset from a face, from one to another, symmetric about its face; in
two directions, from a stated start) are each one more kind here, read the
same way. The spec still writes them as ``depth`` (a length, or
``{"through": true}``) until the schema's 2.0 migration.
"""

from __future__ import annotations

from dataclasses import dataclass

from .draft import Item, Through
from .values import Value

__all__ = ["Blind", "End", "ThroughAll", "end_of"]


@dataclass(frozen=True)
class Blind:
    """To a depth, measured from the face it is cut into."""

    depth: Value


@dataclass(frozen=True)
class ThroughAll:
    """Through all the material under its mouth."""

    through: Through


End = Blind | ThroughAll


def end_of(item: Item) -> End | None:
    """A cut's end condition; None for an item with no depth (what stands, or a cut whose depth isn't given)."""
    depth = item.get("depth")
    if isinstance(depth, Through):
        return ThroughAll(depth)
    if isinstance(depth, Value):
        return Blind(depth)
    return None
