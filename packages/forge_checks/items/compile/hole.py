"""What the check compiler holds for a hole: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs
from forge_spec.draft import Counterbore, Countersink, Fit, Item
from forge_spec.ends import ThroughAll, end_of
from forge_spec.values import Value

from forge_checks.classes import general, tolerance_of
from forge_checks.items.compile._common import _PLAIN, _deg, _mm, _t, _v
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Centre, ConeRim, Ref, RoundEdge
from forge_checks.kinds.surfaces import Cone, Plane, Round
from forge_checks.place import Copy

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


def leaning_wall(item: Item, copy: Copy, radius: float, recess: float) -> Round | None:
    """A leaning hole's side where it is all round (1b's second move): from where its whole circle is past the face
    (or its counterbore's floor), ``recess + r tan(tilt)`` along its axis, to its floor (square to its axis), or right
    through, to where its circle starts to come out of the far side (its span ends where all of it is past that, its
    circle's ``r tan(tilt)`` each way later); None where that is shorter than :data:`_PLAIN`."""
    assert copy.lean is not None and copy.span is not None
    c = float(sum(copy.lean[k] * copy.direction[k] for k in range(3)))
    tan = math.sqrt(max(1.0 - c * c, 0.0)) / c
    start = recess + radius * tan
    end = copy.span[1] - (2 * radius * tan if isinstance(end_of(item), ThroughAll) else 0.0)
    if end - start < _PLAIN:
        return None
    return Round(copy.point, _t(-_v(copy.lean)), radius, start, end, True)


class Hole(CompileKind):
    key = "hole"

    def checks(self, c: CompileContext, item: Item) -> None:
        radius = c.placed.diameters[item.id] / 2
        c.size(item, radius)
        diameter = item.get("diameter")
        tolerance = (
            c.tol(diameter) if isinstance(diameter, Value) else general(2 * radius)
        )
        bore, sink = item.get("counterbore"), item.get("countersink")
        recess = 0.0
        if isinstance(bore, Counterbore):
            recess = _mm(bore.depth)
        elif isinstance(sink, Countersink):
            recess = (_mm(sink.diameter) / 2 - radius) / fs.tan(
                math.radians(_deg(sink.angle) / 2)
            )
        for copy in c.copies(item):
            assert copy.span is not None
            if copy.lean is not None:  # leaning (1b's second move): its sides fitted where each is all round
                axis = _t(-_v(copy.lean))
                lean_c = float(sum(copy.lean[k] * copy.direction[k] for k in range(3)))
                tan = math.sqrt(max(1.0 - lean_c * lean_c, 0.0)) / lean_c
                wall = leaning_wall(item, copy, radius, recess)
                if wall is not None:
                    c.check(item, "diameter", "diameter", 2 * radius, tolerance, wall, copy.index)
                else:
                    c.skip(item, "diameter", "it leans so far its side isn't all round anywhere", "face accounting")
                if isinstance(bore, Counterbore):
                    r = _mm(bore.diameter) / 2
                    if recess - r * tan >= _PLAIN:
                        c.check(item, "counterbore.diameter", "diameter", 2 * r, c.tol(bore.diameter),
                                Round(copy.point, axis, r, r * tan, recess, True), copy.index)  # fmt: skip
                    else:
                        c.skip(item, "counterbore.diameter", "it leans so far its counterbore's side isn't all round "
                               "anywhere", "face accounting")  # fmt: skip
                c._leaning_rest(item, ("depth", "counterbore.depth") if isinstance(bore, Counterbore) else ("depth",))
                continue
            axis = _t(-_v(copy.direction))
            start, end = max(copy.span[0], recess), copy.span[1]
            wall = Round(copy.point, axis, radius, start, end, True)
            c.check(
                item, "diameter", "diameter", 2 * radius, tolerance, wall, copy.index
            )
            c._cut_depth(item, copy, radius, radius, end)
            if isinstance(bore, Counterbore):
                r = _mm(bore.diameter) / 2
                c.check(item, "counterbore.diameter", "diameter", 2 * r, c.tol(bore.diameter),
                           Round(copy.point, axis, r, 0.0, recess, True), copy.index)  # fmt: skip
                floor = Plane(
                    _t(_v(copy.point) - recess * _v(copy.direction)), copy.direction, r
                )
                c._floor(
                    item,
                    "counterbore.depth",
                    copy,
                    floor,
                    recess,
                    c.tol(bore.depth),
                    r,
                )
            if isinstance(sink, Countersink):
                r = _mm(sink.diameter) / 2
                cone = Cone(copy.point, axis, (r, radius), (0.0, recess), True)
                c.check(
                    item,
                    "countersink.diameter",
                    "diameter",
                    2 * r,
                    c.tol(sink.diameter),
                    cone,
                    copy.index,
                )
                slant = fs.hypot(r - radius, recess)
                angle = sink.angle
                assert isinstance(angle, Value)
                tolerance_angle = tolerance_of(angle, shorter_side=slant)
                c.check(
                    item,
                    "countersink.angle",
                    "angle",
                    _deg(angle),
                    tolerance_angle,
                    cone,
                    copy.index,
                )
        if isinstance(diameter, Fit):
            pass  # the fit's size is the diameter checked; its kind, size and grade are where that size came from
        c._cut_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        assert copy.span is not None
        r = c.placed.diameters[item.id] / 2
        if copy.lean is not None:  # leaning: its axis, where its side is all round
            wall = leaning_wall(item, copy, r, c._recess(item, r))
            return Centre(wall) if wall is not None else None
        return Centre(Round(copy.point, _t(-_v(copy.direction)), r, max(copy.span[0], c._recess(item, r)),
                            copy.span[1], True))  # fmt: skip

    def edge_ref(
        self, c: CompileContext, item: Item, copy: Copy, axis: str, sign: float
    ) -> Ref | None:
        """A hole's is its widest circle's (place.md): its counterbore's, or its countersink's rim at the mouth, where it has one."""
        if copy.span is not None:
            n = _v(copy.direction)
            radius = c.placed.diameters[item.id] / 2
            bore, sink = item.get("counterbore"), item.get("countersink")
            if isinstance(bore, Counterbore) and _mm(bore.diameter) / 2 > radius:
                wide = Round(
                    copy.point,
                    _t(-n),
                    _mm(bore.diameter) / 2,
                    0.0,
                    _mm(bore.depth),
                    True,
                )
                return RoundEdge(wide, -1.0)
            if isinstance(sink, Countersink) and _mm(sink.diameter) / 2 > radius:
                recess = c._recess(item, radius)
                cone = Cone(
                    copy.point,
                    _t(-n),
                    (_mm(sink.diameter) / 2, radius),
                    (0.0, recess),
                    True,
                )
                return ConeRim(cone, 0.0, -1.0)
        return super().edge_ref(c, item, copy, axis, sign)


ENTRY = Hole()
