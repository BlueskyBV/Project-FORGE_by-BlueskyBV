"""A shell's hollow, as a tool taken from the part (docs/V2-stage4.md 4.8; docs/definitions/shell.md).

The hollow is every point of the body at least its wall's thickness from
each of its closed faces: each wall ``thickness`` thick, the floor (the wall
opposite an open face) ``floor`` thick, an open face no wall at all. The
body is made whole first, its own roundings and chamfers that border no
open face included, and the hollow follows them: where an edge is rounded by
``r`` between two walls both ``t`` thick, the points at least ``t`` from
both walls and from the rounding are those within ``r - t`` of its axis, so
the hollow's edge there is rounded by ``r - t`` (sharp where that is 0 or
less); a chamfer of ``c`` moved in by ``t`` meets the inner walls
``c - (2 - √2) t`` back from their corner. The hollow's own edges are
rounded in the order the body's were, so where its roundings meet they meet
as the body's do. Where the two walls of a rounded edge differ (a floor of
its own beside a rounded floor edge) the hollow is what the two distances
leave, not an offset of either: no construction is written for it
(:class:`HollowGapError`, a gap of the plan).
"""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.placement import Instance

from .items.plan import PLAN
from .items.plan._shells import HollowGapError
from .write import (
    Chain,
    Vec,
)

__all__ = ["HollowGapError", "hollow_tool"]


def hollow_tool(chain: Chain, shell: Item, body: Item, copy: Instance,
                cavity: tuple[Vec, Vec] | None) -> str:  # fmt: skip
    """One copy's hollow: a tool to take from the part, its inside faces named on the body."""
    return PLAN[body.kind].hollow_tool(chain, shell, body, copy, cavity)
