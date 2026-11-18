"""The preview resolves a cut's end the shape decides (V2-stage4b-0c.md, 3.5; item 2b's second and third steps).

A cut **through the next face** (``{"through_next": true}``, schema 1.8)
goes on until it is out of the part all across its mouth for the first
time, as the shape says. Before the spec is confirmed, the preview finds
how deep that is, on what is made before the cut, built:

1. What is made before it, in the order the part is made (frame.md): the
   spec's items up to it, built through the build loop as the preview
   builds any draft (its roundings made last aren't made yet).
2. Its mouth, carried along its axis past all of that, taken in common with
   it: each solid of what is left lies across a stretch of depths along the
   axis, exactly (its bounds on the axis, from its own surfaces); where no
   stretch is, the mouth is out of the part all across. Where the stretches
   that begin at its face end is where it first comes out.
3. Every copy must come out at the same depth (one depth is recorded); that
   depth is written into the draft as the cut's ``reaches``, which the
   person confirms with the rest, the solver and the planner build to, and
   the judge and the generator each check again on their own shapes.

:func:`resolve_draft` does it for a draft; nothing else here changes it.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from forge_numeric import scalar as fs
from forge_plan.planner import _plan
from forge_spec.draft import Item, PartSpec, read_draft
from forge_spec.ends import ThroughNext, end_of
from forge_spec.geometry import FlatFace
from forge_spec.items.solve import SOLVE
from forge_spec.outline import Arc, Line, Shape
from forge_spec.placement import Instance, Layout, solve, turned_outline
from OCP.Bnd import Bnd_Box
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_Transform,
)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.GC import GC_MakeArcOfCircle
from OCP.gp import gp_Ax2, gp_Ax3, gp_Circ, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from .occt import boundary, box_limits, solids, volume
from .planned import build_plan

__all__ = ["Resolved", "reaches", "resolve_draft"]

#: How close two stretches of material along a cut are taken to meet, and how close to its face one begins (mm).
_MEET = 1e-7
#: How many places a depth the preview finds is kept to (mm): the spec holds no float noise; and how close the
#: copies' depths are to be one.
_PLACES, _SAME = 6, 1e-6
#: How far past what is made before it a cut's mouth is carried to find where it comes out (mm).
_PAST = 10.0
#: The least volume a piece of material along a cut has, to be one (mm³): less is where its mouth only touches.
_SOLID = 1e-9


@dataclass(frozen=True)
class Resolved:
    """What resolving a draft came to: the draft (its cuts through the next face given how deep they go), and what
    couldn't be found, each with the item it is about."""

    draft: dict[str, Any]
    notes: tuple[tuple[str, str], ...] = ()


def resolve_draft(draft: Mapping[str, Any]) -> Resolved:
    """A draft with each cut through the next face given how deep it goes (``reaches``), as the preview finds it.

    A draft with none, or that doesn't read or place, is given back as it
    is. A cut whose depth can't be found (what is made before it doesn't
    build, it doesn't come out, its copies come out at different depths) is
    left without one, and said.
    """
    out = copy.deepcopy(dict(draft))
    spec, problems = read_draft(out)
    if spec is None or problems.faults:
        return Resolved(out)
    through_next = [n for n, item in enumerate(spec.items) if isinstance(end_of(item), ThroughNext)]
    if not through_next:
        return Resolved(out)
    layout = solve(spec)
    notes: list[tuple[str, str]] = []
    raw_items = out.get("items", [])
    for n in through_next:
        item = spec.items[n]
        if item.id in layout.unplaced or not layout.instances.get(item.id):
            continue
        try:
            found = reaches(spec, layout, item)
        except _UnresolvedError as why:
            notes.append((item.id, str(why)))
            continue
        depth = raw_items[n].get("depth") if n < len(raw_items) and isinstance(raw_items[n], dict) else None
        if isinstance(depth, dict):
            depth["reaches"] = found
    return Resolved(out, tuple(notes))


class _UnresolvedError(Exception):
    """A cut through the next face whose depth the preview can't find, and why."""


def reaches(spec: PartSpec, layout: Layout, item: Item) -> float:
    """How deep a cut through the next face goes, as the preview finds it on what is made before it (see the module):
    the same for every copy, to :data:`_PLACES` places."""
    made = _made_before(spec, layout, item)
    found: list[float] = []
    for instance in layout.instances[item.id]:
        found.append(_comes_out(made, item, instance, layout))
    if max(found) - min(found) > _SAME:
        raise _UnresolvedError(f"its copies come out at different depths: {min(found):g} to {max(found):g} mm")
    return round(found[0], _PLACES) + 0.0


def _made_before(spec: PartSpec, layout: Layout, item: Item) -> Any:
    """What is made before a cut, built: the spec's items made before it, in the order the part is made, through the
    build loop."""
    before = layout.order[: layout.order.index(item.id)]
    wanted = set(before)
    prefix = replace(spec, items=tuple(i for i in spec.items if i.id in wanted))
    if not prefix.items:
        raise _UnresolvedError("nothing is made before it")
    solved = solve(prefix)
    if solved.issues:
        raise _UnresolvedError(f"what is made before it doesn't place: {solved.issues[0].message}")
    built = build_plan(_plan(prefix, solved, digest=None))
    if built.result is None or built.gap is not None:
        raise _UnresolvedError("what is made before it doesn't build")
    return built.result.shape


def _comes_out(made: Any, item: Item, instance: Instance, layout: Layout) -> float:
    """How deep one copy first comes out of ``made`` all across its mouth (see the module)."""
    host = instance.host
    face = layout.faces.get(host[:2], {}).get(host[2]) if host is not None else None
    if not isinstance(face, FlatFace) or instance.direction is not None:
        raise _UnresolvedError("the preview finds how deep a cut goes square to a flat face only")
    n = tuple(float(x) for x in instance.normal)
    e1, e2 = (_unit(a) for a in face.axes)
    outline = _mouth(item, layout, face.axes)
    with boundary("finding where a cut through the next face comes out"):
        lo, hi = _limits(made)
        corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        level = sum(instance.origin[k] * n[k] for k in range(3))
        far = max(level - sum(c[k] * n[k] for k in range(3)) for c in corners) + _PAST
        prism = _prism(outline, instance.origin, e1, e2, n, far)
        common = BRepAlgoAPI_Common(made, prism)
        common.Build()
        if not common.IsDone():
            raise _UnresolvedError("the preview couldn't take its mouth in common with what is made before it")
        stretches = sorted(_along(piece, instance.origin, n) for piece in solids(common.Shape())
                           if volume(piece) > _SOLID)  # fmt: skip
    if not stretches or stretches[0][0] > _MEET:
        raise _UnresolvedError("there is no material under its mouth")
    end = stretches[0][1]
    for start, stop in stretches[1:]:
        if start > end + _MEET:
            break
        end = max(end, stop)
    if end >= far - _PAST / 2:
        raise _UnresolvedError("it doesn't come out of what is made before it")
    return end


def _mouth(item: Item, layout: Layout, axes: tuple[str, str]) -> Shape:
    """A cut's mouth on its face, about its point, along the face's axes: its turned outline, or its own."""
    turned = turned_outline(item, layout, axes)
    if turned is not None:
        return turned
    sizes = SOLVE[item.kind].turnable(item, layout, axes)
    if sizes is not None:
        h1, h2, r = sizes
        return Shape.rect((0.0, 0.0), (h1, h2), (r, r, r, r))
    (part, *rest) = SOLVE[item.kind].outline(item, layout, axes)
    if rest or not part.disc:
        raise _UnresolvedError("the preview finds how deep a hole, a pocket or a slot goes")
    return Shape((Arc(part.centre, part.half[0], 0.0, 2 * math.pi),))


def _unit(axis: str) -> tuple[float, float, float]:
    return tuple(1.0 if a == axis else 0.0 for a in "xyz")  # type: ignore[return-value]


def _prism(outline: Shape, origin: Sequence[float], e1: Sequence[float], e2: Sequence[float], n: Sequence[float],
           far: float) -> Any:  # fmt: skip
    """The mouth's outline on its face, carried in along the cut's axis ``far``."""

    def point(p: tuple[float, float]) -> gp_Pnt:
        return gp_Pnt(*(origin[k] + p[0] * e1[k] + p[1] * e2[k] for k in range(3)))

    wire = BRepBuilderAPI_MakeWire()
    for piece in outline.pieces:
        if isinstance(piece, Line):
            if fs.dist(piece.a, piece.b) > _MEET:
                wire.Add(BRepBuilderAPI_MakeEdge(point(piece.a), point(piece.b)).Edge())
        elif piece.radius <= _MEET:
            continue  # a sharp corner
        elif abs(abs(piece.sweep) - 2 * math.pi) < 1e-12:
            normal = gp_Dir(*(e1[(k + 1) % 3] * e2[(k + 2) % 3] - e1[(k + 2) % 3] * e2[(k + 1) % 3] for k in range(3)))
            circle = gp_Circ(gp_Ax2(point(piece.centre), normal, gp_Dir(*e1)), piece.radius)
            wire.Add(BRepBuilderAPI_MakeEdge(circle).Edge())
        else:
            arc = GC_MakeArcOfCircle(point(piece.at(0.0)), point(piece.at(0.5)), point(piece.at(1.0))).Value()
            wire.Add(BRepBuilderAPI_MakeEdge(arc).Edge())
    face = BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(*(-far * n[k] for k in range(3)))).Shape()


def _limits(shape: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    x0, y0, z0, x1, y1, z1 = box_limits(box)
    return (x0, y0, z0), (x1, y1, z1)


def _along(piece: Any, origin: Sequence[float], n: Sequence[float]) -> tuple[float, float]:
    """The stretch of depths, in from the cut's face along its axis, a piece of material lies across: exactly, from its
    bounds with the axis turned to be the third."""
    trsf = gp_Trsf()
    # Into the frame whose third axis is the cut's way in (against its face's normal), from its point.
    inward = gp_Dir(*(-x for x in n))
    trsf.SetTransformation(gp_Ax3(gp_Pnt(*origin), inward))
    moved = BRepBuilderAPI_Transform(piece, trsf, True).Shape()
    _, (_, _, top) = _limits(moved)
    (_, _, bottom), _ = _limits(moved)
    return bottom, top
