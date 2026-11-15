"""Boxes, cylinders, cones, spheres, tori and wedges, as V1 makes them (docs/V2-stage3.md, 7.2).

A box with rounded or chamfered edges is built by V1's own construction for
each ``edges`` option, so its corners are V1's:

- ``all`` rounded (no chamfer): the box shrunk by r each way, grown back by r
  (an offset: flat faces, quarter cylinders, ball corners);
- ``along_x``/``along_y`` (and ``bottom_``/``top_`` of them): the box's
  section across that axis, its corners rounded or chamfered, extruded along
  it; one end only joins the other half of the box, square;
- ``vertical_*``: the end's footprint, its corners rounded, extruded up the
  box, cut to the box, joined to the square part behind it;
- every other case (``all`` with a chamfer, ``vertical``, ``top``,
  ``bottom``, ``top_and_bottom``): the footprint (its corners rounded or
  chamfered for the upright edges) extruded up the box, the edges round its
  top and bottom faces rounded or chamfered as the option says.

Faces are named by where they are: ``x_min`` … ``z_max`` the flat faces on
the box's sides, ``round`` and ``bevel`` the rest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
from OCP.BRepOffset import BRepOffset_Skin
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakeSphere,
    BRepPrimAPI_MakeTorus,
)
from OCP.GeomAbs import GeomAbs_Arc
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from ..errors import DesignError, OperationError
from ..geom import Frame, unit
from ..make import boolean, one_solid, unify
from ..names import Name, Names, carry, named_by
from ..occt import boundary, box_limits
from ..products import Context, Product, SolidProduct
from ..profiles import rectangle, sketch
from .sweeps import _plane_of, extrusion

__all__ = ["BUILDERS"]

_AXES = np.eye(3)
_SIDE_NAMES = (("x_min", "x_max"), ("y_min", "y_max"), ("z_min", "z_max"))


def _box_role(lo: Any, hi: Any) -> Callable[[Any], str]:
    """Name a face by where it is on the box from ``lo`` to ``hi``."""

    def role(face: Any) -> str:
        found = _plane_of(face)
        if found is not None:
            origin, normal = found
            for axis in range(3):
                for side, bound in enumerate((lo, hi)):
                    sign = 1.0 if side else -1.0
                    if (
                        float(normal[axis]) * sign > 1.0 - 1e-9
                        and abs(float(origin[axis]) - float(bound[axis])) < 1e-6
                    ):
                        return _SIDE_NAMES[axis][side]
            return "bevel"
        return "round"

    return role


def _box_solid(lo: Any, hi: Any) -> Any:
    with boundary("a box"):
        return BRepPrimAPI_MakeBox(gp_Pnt(*lo), gp_Pnt(*hi)).Shape()


def _combine(kind: str, step: str, a: SolidProduct, b: SolidProduct) -> SolidProduct:
    done = boolean(kind, [a.shape], [b.shape])
    carried = carry(
        [a.names, b.names], done.shape, done.history, fallback=(Name(step, "other"),)
    )
    merged = unify(done.shape)
    again = carry(
        [carried.names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    solid = one_solid(merged.shape)
    return SolidProduct(solid, again.names.on(solid))


def _box(ctx: Context) -> Product:
    size = np.asarray(ctx.vector("size"), dtype=np.float64)
    if np.any(size <= 0.0):
        raise ctx.fail(
            DesignError("a box needs every side longer than zero", size=size.tolist())
        )
    origin = np.asarray(ctx.vector("origin", (0.0, 0.0, 0.0)), dtype=np.float64)
    half = size / 2.0
    centre = origin if ctx.flag("centered", False) else origin + half
    lo, hi = centre - half, centre + half
    radius = ctx.length("edge_radius", 0.0)
    chamfer = ctx.length("edge_chamfer", 0.0)
    edges = ctx.option("edges", "all")
    role = _box_role(lo, hi)
    step = ctx.step
    try:
        if radius <= 0.0 and chamfer <= 0.0:
            built = _box_solid(lo, hi)
        elif radius > 0.0 and chamfer <= 0.0 and edges == "all":
            if radius * 2.0 >= float(size.min()):
                raise DesignError("an edge radius must be under half the box's smallest side",
                                  edge_radius=radius, smallest_side=float(size.min()))  # fmt: skip
            core = _box_solid(lo + radius, hi - radius)
            with boundary("rounding a box's edges"):
                grown = BRepOffsetAPI_MakeOffsetShape()
                grown.PerformByJoin(
                    core, radius, 1e-7, BRepOffset_Skin, False, False, GeomAbs_Arc
                )
                if not grown.IsDone():
                    raise OperationError("OpenCascade could not round the box's edges")
                built = one_solid(grown.Shape())
        elif edges.endswith(("along_x", "along_y")):
            built = _along(step, edges, centre, half, size, radius, chamfer).shape
        elif edges.startswith("vertical_"):
            built = _vertical(step, edges, centre, half, size, radius, chamfer).shape
        else:
            vertical = edges in ("all", "vertical")
            top = edges in ("all", "top", "top_and_bottom")
            bottom = edges in ("all", "bottom", "top_and_bottom")
            footprint = rectangle((float(centre[0]), float(centre[1])), float(size[0]), float(size[1]),
                                  radius if vertical else 0.0, chamfer if vertical else 0.0)  # fmt: skip
            built = extrusion(
                step, footprint, Frame((0.0, 0.0, float(lo[2]))), offset=0.0, distance=float(size[2]),
                start_round=radius if bottom else 0.0, end_round=radius if top else 0.0,
                start_chamfer=chamfer if bottom else 0.0, end_chamfer=chamfer if top else 0.0,
            ).shape  # fmt: skip
    except DesignError as error:
        raise ctx.fail(error) from error
    return SolidProduct(built, _sides_rounded_away(step, built, named_by(built, lambda f: (Name(step, role(f)),)),
                                                   lo, hi))  # fmt: skip


def _sides_rounded_away(step: str, shape: Any, names: Names, lo: Any, hi: Any) -> Names:
    """A side the box's rounding left no face of (a rail rounded to half its width has no flat end) named on what's there.

    The rounded or bevelled faces reaching that side's plane take its name
    besides their own, so ``x_max`` still means the box's +x end, as it does
    in V1 (whose box publishes the side for any rounding).
    """
    present = {n.role for n in names.every()}
    gone = [
        (axis, end)
        for axis in range(3)
        for end in (0, 1)
        if _SIDE_NAMES[axis][end] not in present
    ]
    if not gone:
        return names
    table = []
    for face, held in names.items():
        extra = set()
        if any(n.role in ("round", "bevel") for n in held):
            low, high = _face_box(face)
            for axis, end in gone:
                reach = high[axis] if end else low[axis]
                bound = float(hi[axis] if end else lo[axis])
                if abs(reach - bound) <= 1e-6:
                    extra.add(Name(step, _SIDE_NAMES[axis][end]))
        table.append(held | extra)
    return Names(shape, tuple(table))


def _face_box(face: Any) -> tuple[Any, Any]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(face, box, False, False)
    x0, y0, z0, x1, y1, z1 = box_limits(box)
    return np.array([x0, y0, z0]), np.array([x1, y1, z1])


def _along(
    step: str,
    edges: str,
    centre: Any,
    half: Any,
    size: Any,
    radius: float,
    chamfer: float,
) -> SolidProduct:
    """The four edges along one axis: the section across it, its corners rounded, extruded along it."""
    w = 0 if edges.endswith("along_x") else 1
    u, v = (1, 2) if w == 0 else (2, 0)
    section = rectangle(
        (float(centre[u]), float(centre[v])),
        float(size[u]),
        float(size[v]),
        radius,
        chamfer,
    )
    start = np.zeros(3)
    start[w] = float(centre[w] - half[w])
    frame = Frame.through(start, _AXES[u], _AXES[v], _AXES[w])
    solid = extrusion(step, section, frame, offset=0.0, distance=float(size[w]))
    if not edges.startswith(("bottom_", "top_")):
        return solid
    # One end only: the other half of the box kept square.
    lo, hi = (centre - half).copy(), (centre + half).copy()
    if edges.startswith("bottom_"):
        lo[2] = float(centre[2])
    else:
        hi[2] = float(centre[2])
    square = _box_solid(lo, hi)
    return _combine(
        "union",
        step,
        solid,
        SolidProduct(square, named_by(square, lambda _f: (Name(step, "side"),))),
    )


def _vertical(
    step: str,
    edges: str,
    centre: Any,
    half: Any,
    size: Any,
    radius: float,
    chamfer: float,
) -> SolidProduct:
    """The two upright edges of one face only: its end rounded in plan, the rest square."""
    normal = 0 if edges.startswith("vertical_x") else 1
    across = 1 - normal
    sign = 1.0 if edges.endswith("_max") else -1.0
    depth = radius if radius > 0.0 else chamfer
    if depth > float(half[across]) + 1e-9:
        raise DesignError("an end's edge radius must be at most half the width of the face it rounds",
                          edge_radius=depth, face_width=float(size[across]))  # fmt: skip
    if depth > float(size[normal]) + 1e-9:
        raise DesignError("an end's edge radius must be at most the box's length behind that face",
                          edge_radius=depth, length=float(size[normal]))  # fmt: skip
    end = float(centre[normal] + sign * half[normal])
    middle = [float(centre[0]), float(centre[1])]
    extent = [float(half[0]), float(half[1])]
    middle[normal] = end - sign * depth
    extent[normal] = depth
    footprint = rectangle(
        (middle[0], middle[1]), 2 * extent[0], 2 * extent[1], radius, chamfer
    )
    rounded = extrusion(step, footprint, Frame((0.0, 0.0, float(centre[2] - half[2]))), offset=0.0,
                        distance=float(size[2]))  # fmt: skip
    whole = _box_solid(centre - half, centre + half)
    solid = _combine("intersect", step, rounded,
                     SolidProduct(whole, named_by(whole, lambda _f: (Name(step, "side"),))))  # fmt: skip
    if float(size[normal]) - depth <= 1e-9:
        return solid
    lo, hi = (centre - half).copy(), (centre + half).copy()
    if sign > 0:
        hi[normal] = end - depth
    else:
        lo[normal] = end + depth
    square = _box_solid(lo, hi)
    return _combine("union", step, square_named(step, square), solid)


def square_named(step: str, shape: Any) -> SolidProduct:
    return SolidProduct(shape, named_by(shape, lambda _f: (Name(step, "side"),)))


def _axis_of(ctx: Context, what: str) -> Any:
    try:
        return unit(ctx.vector("axis", (0.0, 0.0, 1.0)), f"a {what}'s axis")
    except DesignError as error:
        raise ctx.fail(error) from error


def _ends_role(base: Any, axis: Any, height: float) -> Callable[[Any], str]:
    top = base + axis * height

    def role(face: Any) -> str:
        found = _plane_of(face)
        if found is None:
            return "lateral"
        origin, _ = found
        return (
            "base"
            if abs(float((origin - base) @ axis)) < 1e-6
            else "top"
            if abs(float((origin - top) @ axis)) < 1e-6
            else "lateral"
        )

    return role


def _cylinder(ctx: Context) -> Product:
    radius = ctx.length("diameter") / 2.0
    height = ctx.length("height")
    if radius <= 0.0 or height <= 0.0:
        raise ctx.fail(
            DesignError(
                "a cylinder needs a diameter and a height",
                diameter=2 * radius,
                height=height,
            )
        )
    origin = np.asarray(ctx.vector("origin", (0.0, 0.0, 0.0)), dtype=np.float64)
    axis = _axis_of(ctx, "cylinder")
    with boundary("a cylinder"):
        shape = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(*origin), gp_Dir(*axis)), radius, height
        ).Shape()
    role = _ends_role(origin, axis, height)
    return SolidProduct(shape, named_by(shape, lambda f: (Name(ctx.step, role(f)),)))


def _cone(ctx: Context) -> Product:
    bottom = ctx.length("bottom_diameter") / 2.0
    top = ctx.length("top_diameter") / 2.0
    height = ctx.length("height")
    if height <= 0.0 or bottom < 0.0 or top < 0.0 or max(bottom, top) <= 0.0:
        raise ctx.fail(DesignError("a cone needs a height and a radius at one end at least",
                                   bottom_diameter=2 * bottom, top_diameter=2 * top, height=height))  # fmt: skip
    origin = np.asarray(ctx.vector("origin", (0.0, 0.0, 0.0)), dtype=np.float64)
    axis = _axis_of(ctx, "cone")
    with boundary("a cone"):
        frame = gp_Ax2(gp_Pnt(*origin), gp_Dir(*axis))
        if abs(bottom - top) <= 1e-12:
            shape = BRepPrimAPI_MakeCylinder(frame, bottom, height).Shape()
        else:
            shape = BRepPrimAPI_MakeCone(frame, bottom, top, height).Shape()
    role = _ends_role(origin, axis, height)
    return SolidProduct(shape, named_by(shape, lambda f: (Name(ctx.step, role(f)),)))


def _sphere(ctx: Context) -> Product:
    radius = ctx.length("diameter") / 2.0
    if radius <= 0.0:
        raise ctx.fail(DesignError("a sphere needs a diameter", diameter=2 * radius))
    origin = ctx.vector("origin", (0.0, 0.0, 0.0))
    with boundary("a sphere"):
        shape = BRepPrimAPI_MakeSphere(gp_Pnt(*origin), radius).Shape()
    return SolidProduct(shape, named_by(shape, lambda _f: (Name(ctx.step, "surface"),)))


def _torus(ctx: Context) -> Product:
    radius = ctx.length("diameter") / 2.0
    tube = ctx.length("tube_diameter") / 2.0
    if tube <= 0.0 or radius <= 0.0:
        raise ctx.fail(DesignError("a ring needs a diameter and a tube diameter"))
    if tube >= radius:
        raise ctx.fail(DesignError(
            "a ring's tube is thicker than the ring is across: its `tube_diameter` must be less "
            "than its `diameter`", diameter=2 * radius, tube_diameter=2 * tube))  # fmt: skip
    origin = np.asarray(ctx.vector("origin", (0.0, 0.0, 0.0)), dtype=np.float64)
    axis = _axis_of(ctx, "ring")
    with boundary("a ring"):
        shape = BRepPrimAPI_MakeTorus(
            gp_Ax2(gp_Pnt(*origin), gp_Dir(*axis)), radius, tube
        ).Shape()
    return SolidProduct(shape, named_by(shape, lambda _f: (Name(ctx.step, "surface"),)))


def _wedge(ctx: Context) -> Product:
    size = np.asarray(ctx.vector("size"), dtype=np.float64)
    if np.any(size <= 0.0):
        raise ctx.fail(
            DesignError(
                "a wedge needs every extent greater than zero", size=size.tolist()
            )
        )
    origin = np.asarray(ctx.vector("origin", (0.0, 0.0, 0.0)), dtype=np.float64)
    lo = origin - size / 2.0 if ctx.flag("centered") else origin
    hi = lo + size
    slope = ctx.option("slope", "+x")
    if slope not in ("+x", "-x", "+y", "-y"):
        raise ctx.fail(
            DesignError("a wedge slopes towards +x, -x, +y or -y", slope=slope)
        )
    along = 0 if slope.endswith("x") else 1
    other = 1 - along
    sign = 1.0 if slope.startswith("+") else -1.0
    tall = float(lo[along] if sign > 0 else hi[along])
    short = float(hi[along] if sign > 0 else lo[along])
    # The triangle in the (along, z) plane: the tall end's foot and head, the low end's foot.
    triangle = [(tall, float(lo[2])), (tall, float(hi[2])), (short, float(lo[2]))]
    section = sketch(triangle)
    frame_x = _AXES[along]
    frame_y = _AXES[2]
    frame_z = np.cross(frame_x, frame_y)
    start = np.zeros(3)
    start[other] = float(lo[other]) if frame_z[other] > 0 else float(hi[other])
    frame = Frame.through(start, frame_x, frame_y, frame_z)
    built = extrusion(ctx.step, section, frame, offset=0.0, distance=float(size[other]))
    sides = _SIDE_NAMES[other]

    def role(face: Any) -> str:
        found = _plane_of(face)
        if found is None:
            return "slope"
        _, normal = found
        if normal[2] < -1.0 + 1e-9:
            return "base"
        if abs(abs(float(normal[along])) - 1.0) < 1e-9:
            return "back"
        if abs(abs(float(normal[other])) - 1.0) < 1e-9:
            return sides[0] if normal[other] < 0 else sides[1]
        return "slope"

    shape = built.shape
    return SolidProduct(shape, named_by(shape, lambda f: (Name(ctx.step, role(f)),)))


BUILDERS: Mapping[str, Callable[[Context], Product]] = {
    "box": _box,
    "cylinder": _cylinder,
    "cone": _cone,
    "sphere": _sphere,
    "torus": _torus,
    "wedge": _wedge,
}
