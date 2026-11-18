"""What the oracle makes for a revolution: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from forge_numeric import scalar as fs
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Inter, Node
from forge_checks.items.oracle._shapes import (
    OracleError,
    _across_at,
    _circle,
    _off_axis,
    _outline_boundary,
    _round_bulge,
    _together,
    convex_pieces_of,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.outlines import Segment as OutlineSegment
from forge_checks.place import (
    Copy,
    Face,
    Hollow,
    Placed,
    section_of,
)
from forge_checks.shapes import Frame, Polygon, Revolved, Torus

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Revolution(OracleKind):
    key = "revolution"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        return _revolution_node(item, copy)

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return _turned_rims(target, copy, pairs), []


def _revolution_node(item: Item, copy: Copy) -> Node:
    """A revolution: its half outline's convex pieces turned about its axis (docs/V2-stage4.md, 6.6).

    Each polygon a :class:`Revolved`; each bulge the ring its arc's circle
    sweeps (a :class:`Torus`, a ball for a centre on the axis) meeting the
    :class:`Revolved` of a polygon round the bulge on its side of the chord.
    An arc about a centre across the axis sweeps something else, and is not
    made yet.
    """
    pieces = convex_pieces_of(item)
    u = np.asarray(copy.direction, dtype=float)
    origin = np.asarray(copy.point, dtype=float)
    frame = Frame.along(origin, u)
    added: list[Node] = [
        Revolved(frame, Polygon(tuple(_off_axis(p) for p in c)))
        for c in pieces.polygons
    ]
    taken: list[Node] = []
    for bulge in pieces.bulges:
        (c_rho, c_h), r = bulge.arc.centre, bulge.arc.radius
        if c_rho < -1e-9:
            raise OracleError(f"{item.id}: an arc of its outline turns about a centre across the axis, "
                              f"at ({c_rho:g}, {c_h:g}); the oracle doesn't make that yet")  # fmt: skip
        ring = Torus(Frame.along(origin + c_h * u, u), max(c_rho, 0.0), r)
        around = Polygon(_round_bulge(bulge.arc.centre, r, bulge.a, bulge.outward))
        node = Inter((ring, Revolved(frame, around)))
        (added if bulge.adds else taken).append(node)
    return _together(added, taken)


def _turned_rims(
    target: Item, copy: Copy, pairs: Sequence[tuple[str, str]]
) -> list[rounds.Chain]:
    """A revolution's ends' rims (revolution.md): each circle where a flat end meets the side next to it at an angle, off the axis."""
    section = section_of(target)
    frame = Frame.along(copy.point, np.asarray(copy.direction, dtype=float))
    found = []
    for end, _ in pairs:
        top = end == "+end"
        height = section.centre[1] + (section.half[1] if top else -section.half[1])
        flat = [q for q in section.pieces() if isinstance(q, OutlineSegment) and abs(q.a[1] - height) <= 1e-9
                and abs(q.b[1] - height) <= 1e-9]  # fmt: skip
        if len(flat) != 1:
            raise OracleError(
                f"{target.id}: it has no flat {end}: its edges there are none"
            )
        for rim in (flat[0].a, flat[0].b):
            if rim[0] <= 1e-9:
                continue  # on the axis: the end is a disc, with no edge there
            beside = [
                q
                for q in section.pieces()
                if q is not flat[0] and any(fs.dist(p, rim) <= 1e-9 for p in q.ends())
            ]
            if len(beside) != 1:
                raise OracleError(
                    f"{target.id}: its outline at ({rim[0]:g}, {rim[1]:g}) isn't one side meeting its end"
                )
            if abs(_across_at(beside[0], rim)[0]) > 1.0 - 1e-9:
                continue  # the side runs on smoothly into the end: no edge there
            wall = _outline_boundary(section, beside[0], rim, (0.0, 0.0), material=True)
            found.append(
                _circle(
                    frame,
                    rim[0],
                    rim[1],
                    rounds.Line2((0.0, 1.0 if top else -1.0)),
                    wall,
                )
            )
    if not found:
        raise OracleError(
            f"{target.id}: its side runs on smoothly into its ends: its edges there are none"
        )
    return found


ENTRY = Revolution()
