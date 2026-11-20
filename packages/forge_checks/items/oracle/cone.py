"""What the oracle makes for a cone: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from forge_numeric import scalar as fs
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import _mm, _rim_chains, _unit2, round_footprint
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, Face, Hollow, Placed
from forge_checks.shapes import Complement, Frame, Frustum, Halfspace

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Cone(OracleKind):
    key = "cone"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        u = np.asarray(copy.direction, dtype=float)
        frame = Frame.along(copy.point, u)
        base, top = (
            _mm(item.get("base_diameter")) / 2,
            _mm(item.get("top_diameter")) / 2,
        )
        return Frustum(frame, 0.0, _mm(item.get("length")), base, top)

    def hollow(self, item: Item, copy: Copy, placed: Placed) -> Node:
        t0, t1, a, b, _ = _hollow_of(item, placed.hollows[(item.id, copy.index)], 0.0)
        return Frustum(Frame.along(copy.point, np.asarray(copy.direction, dtype=float)), t0, t1, a, b)

    def wall_bands(self, body: Item, copy: Copy, placed: Placed) -> dict[str, Node]:
        """A hollowed cone's bands (shell.md, "cone"): outside the hollow's cone, run on past each end the hollow is open
        at, for its side; past each end's wall, for that end."""
        hollow = placed.hollows[(body.id, copy.index)]
        u = np.asarray(copy.direction, dtype=float)
        frame = Frame.along(copy.point, u)
        t0, t1, a, b, (lo, hi, a_far, b_far) = _hollow_of(body, hollow, 1.0)
        found: dict[str, Node] = {"side": Complement(Frustum(frame, lo, hi, a_far, b_far))}
        point = np.asarray(copy.point, dtype=float)
        if hollow.walls.get("+end", 0.0) > 0.0:
            found["+end"] = Halfspace(_vec(point + t1 * u), _vec(-u))
        if hollow.walls.get("-end", 0.0) > 0.0:
            found["-end"] = Halfspace(_vec(point + t0 * u), _vec(u))
        return found

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return _rim_chains(
            target,
            copy,
            pairs,
            hollow,
            making.placed,
            _mm(target.get("base_diameter")) / 2,
            _mm(target.get("top_diameter")) / 2,
            _mm(target.get("length")),
        ), []

    def footprint_chain(
        self,
        item: Item,
        copy: Copy,
        corners: Mapping[frozenset[str], tuple[str, float]],
    ) -> rounds.Chain:
        r0, r1 = (
            _mm(item.get("base_diameter")) / 2,
            _mm(item.get("top_diameter")) / 2,
        )
        length = _mm(item.get("length"))
        slope = _unit2(length, -(r1 - r0))
        return round_footprint(copy, r0, rounds.Line2((-slope[0], -slope[1])))


def _vec(v: object) -> tuple[float, float, float]:
    x = np.asarray(v, dtype=float)
    return (float(x[0]), float(x[1]), float(x[2]))


def _hollow_of(body: Item, hollow: Hollow, run: float) -> tuple[float, float, float, float, tuple[float, float, float, float]]:
    """A hollowed cone's hollow along its axis from its -end: (start, end, radius there, radius there), and the cone it
    lies in run on ``run`` mm past each open end where its radius stays above nothing (lo, hi, radii there).

    Worked out here from the cone and its walls, apart from the solver's: the side wall ``thickness`` thick square to
    the side, so the hollow's radius is the cone's less the thickness times the side's slant over its length.
    """
    r0, r1 = _mm(body.get("base_diameter")) / 2, _mm(body.get("top_diameter")) / 2
    length = _mm(body.get("length"))
    t = hollow.walls["side"]
    slant = fs.hypot(length, r1 - r0) / length
    taper = (r1 - r0) / length

    def radius(s: float) -> float:
        return r0 + taper * s - t * slant

    start = hollow.walls.get("-end", 0.0)
    end = length - hollow.walls.get("+end", 0.0)
    a, b = radius(start), radius(end)
    lo, hi = start, end
    if "-end" in hollow.open:
        lo = start - (run if taper <= 0.0 else min(run, 0.5 * a / taper))
    if "+end" in hollow.open:
        hi = end + (run if taper >= 0.0 else min(run, 0.5 * b / -taper))
    return start, end, a, b, (lo, hi, radius(lo), radius(hi))


ENTRY = Cone()
