"""Holes, as V1 drills them (docs/V2-stage3.md, 7.2).

- A through hole is a tool reaching V1's envelope diagonal plus 2r each way
  from its position; a blind one runs ``depth`` from its position.
- ``through: first_wall`` finds its own stretch: walking the axis from the
  position, the first material met, from a margin before it (or, from inside
  material, back to that wall's near face) to a margin past it, never as far
  as the next wall (midway at most), with V1's margin max(0.5, r/4). Where
  V1 sampled the line, this finds the material exactly.
- A counterbore or countersink is cut at V1's surface: for a through hole the
  first material along the whole axis line (the last, for ``entry: end``);
  for ``first_wall`` the wall's own faces; for a blind hole its position.
  Each tool starts V1's margin, max(5 % of the envelope's diagonal, 1 mm),
  outside that surface.

Faces: ``bore``, ``bottom`` (a blind hole's floor), ``counterbore_wall``,
``counterbore_floor``, ``countersink``.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Lin, gp_Pnt
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_IN

from ..errors import DesignError
from ..geom import unit
from ..names import Name, named_by
from ..occt import boundary, box_limits, volume
from ..products import Context, Product, SolidProduct
from .booleans import combine
from .sweeps import _plane_of

__all__ = ["BUILDERS", "material_along"]


@dataclass(frozen=True)
class Envelope:
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]

    @property
    def diagonal(self) -> float:
        return math.dist(self.lo, self.hi)

    def corners(self) -> Any:
        return np.array([[x, y, z] for x in (self.lo[0], self.hi[0]) for y in (self.lo[1], self.hi[1])
                         for z in (self.lo[2], self.hi[2])])  # fmt: skip


def envelope_of(ctx: Context, shape: Any) -> tuple[Envelope, str]:
    """V1's envelope of the step's input (what the document means), or the exact box where V1 can't build it."""
    product = ctx.v1_input(0)
    if product is not None and hasattr(product, "solid"):
        box = product.solid.envelope
        return Envelope(tuple(map(float, box.lo)), tuple(map(float, box.hi))), "v1"  # type: ignore[arg-type]
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bounds, False, False)
    x0, y0, z0, x1, y1, z1 = box_limits(bounds)
    return Envelope(
        (x0, y0, z0), (x1, y1, z1)
    ), "exact box (V1 can't build this step's input)"


def material_along(
    shape: Any, origin: Any, axis: Any, t_lo: float, t_hi: float
) -> list[tuple[float, float]]:
    """The stretches of material on the line ``origin + t·axis`` for t in [t_lo, t_hi], exactly.

    Every crossing of the line with a face is found; between each two, a point
    is classified, so a line through an edge or along a face can't be
    miscounted.
    """
    with boundary("finding material along an axis"):
        hits = IntCurvesFace_ShapeIntersector()
        hits.Load(shape, 1e-9)
        hits.Perform(gp_Lin(gp_Pnt(*origin), gp_Dir(*axis)), t_lo, t_hi)
        ts = sorted({float(hits.WParameter(i)) for i in range(1, hits.NbPnt() + 1)})
    cuts = [t_lo] + [t for t in ts if t_lo < t < t_hi] + [t_hi]
    merged: list[float] = []
    for t in cuts:
        if not merged or t - merged[-1] > 1e-9:
            merged.append(t)
    classifier = BRepClass3d_SolidClassifier(shape)
    stretches: list[tuple[float, float]] = []
    for a, b in itertools.pairwise(merged):
        middle = origin + axis * ((a + b) / 2.0)
        with boundary("classifying a point"):
            classifier.Perform(gp_Pnt(*middle), 1e-9)
            inside = classifier.State() == TopAbs_IN
        if not inside:
            continue
        if stretches and abs(stretches[-1][1] - a) <= 1e-9:
            stretches[-1] = (stretches[-1][0], b)
        else:
            stretches.append((a, b))
    return stretches


def _first_wall(
    shape: Any, position: Any, axis: Any, envelope: Envelope, radius: float
) -> tuple[float, float, float, float]:
    """(enters, ends, near face, far face): V1's ``_depth_through_the_first_wall`` and ``_the_first_wall_s_faces``, exactly."""
    reach = envelope.diagonal * 2.0 + 4.0 * radius
    ahead = material_along(shape, position, axis, 0.0, reach)
    if not ahead:
        raise DesignError("`through: first_wall` meets no material along the hole's axis from its "
                          "position; point `axis` at the wall",
                          position=[round(float(c), 3) for c in position],
                          axis=[round(float(c), 3) for c in axis])  # fmt: skip
    margin = max(0.5, 0.25 * radius)
    near, far = ahead[0]
    enters = max(0.0, near - margin)
    if near <= 1e-9:
        # Started inside the wall: through it is through the whole of it, back to its near face
        # (and never as far as a wall behind, midway at most).
        behind = material_along(shape, position, -axis, 0.0, reach)
        inside = bool(behind) and behind[0][0] <= 1e-9
        back = behind[0][1] if inside else 0.0
        rest = behind[1:] if inside else behind
        reach_back = back + margin
        if rest:
            reach_back = min(reach_back, (back + rest[0][0]) / 2.0)
        enters = -reach_back
        near = -back
    if far >= reach - 1e-9:
        return enters, reach, near, far
    later = ahead[1:]
    end = min(far + margin, (far + later[0][0]) / 2.0) if later else far + margin
    return enters, end, near, far


def _hole(ctx: Context) -> Product:
    base = ctx.solid(0)
    radius = ctx.length("diameter") / 2.0
    if radius <= 0.0:
        raise ctx.fail(DesignError("a hole needs a diameter"))
    position = np.asarray(ctx.vector("position"), dtype=np.float64)
    try:
        axis = unit(ctx.vector("axis", (0.0, 0.0, 1.0)), "a hole's axis")
    except DesignError as error:
        raise ctx.fail(error) from error
    envelope, source = envelope_of(ctx, base.shape)
    span = envelope.diagonal
    depth = ctx.params.get("depth")
    notes = [] if source == "v1" else [f"margins from the {source}"]
    wall: tuple[float, float] | None = None
    try:
        if ctx.option("through", "all") == "first_wall":
            if depth is not None:
                raise DesignError(
                    "`through: first_wall` finds its own depth; give no `depth` with it"
                )
            start, end, near, far = _first_wall(
                base.shape, position, axis, envelope, radius
            )
            wall = (near, far)
            origin = position + axis * start
            depth = end - start
            wall_points = (position + axis * near, position + axis * far)
            position = origin
        if depth is not None and float(depth) <= 0.0:
            raise DesignError("hole depth must be positive", depth=float(depth))
    except DesignError as error:
        raise ctx.fail(error) from error

    if depth is None:
        length = span * 2.0 + 4.0 * radius
        tool_base = position - axis * (length / 2.0)
    else:
        length = float(depth)
        tool_base = position
    with boundary("a hole's tool"):
        bore = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(*tool_base), gp_Dir(*axis)), radius, length
        ).Shape()
    tools = [
        SolidProduct(
            bore,
            named_by(
                bore,
                lambda f: (
                    Name(ctx.step, "bore" if _plane_of(f) is None else "bottom"),
                ),
            ),
        )
    ]

    # Where the hole meets the material.
    if wall is not None:
        start_at, end_at = wall_points
    elif depth is None:
        corners = envelope.corners() @ axis
        offset = float(position @ axis)
        t_lo, t_hi = float(corners.min()) - offset, float(corners.max()) - offset
        stretches = material_along(base.shape, position, axis, t_lo, t_hi)
        if stretches:
            first, last = stretches[0][0], stretches[-1][1]
        else:
            first, last = -(t_hi - t_lo) / 2.0, (t_hi - t_lo) / 2.0
        start_at, end_at = position + axis * first, position + axis * last
    else:
        start_at, end_at = position, position + axis * float(depth)
    if ctx.option("entry", "start") == "end":
        surface, inward = end_at, -axis
    else:
        surface, inward = start_at, axis
    margin = max(span * 0.05, 1.0)

    try:
        cb_diameter = ctx.params.get("counterbore_diameter")
        cb_depth = ctx.params.get("counterbore_depth")
        if cb_diameter is not None:
            if cb_depth is None:
                raise DesignError(
                    "a counterbore needs its depth as well as its diameter"
                )
            cb_radius = float(cb_diameter) / 2.0
            if cb_radius <= radius:
                raise DesignError("counterbore diameter must exceed the hole diameter",
                                  counterbore_diameter=2 * cb_radius, diameter=2 * radius)  # fmt: skip
            with boundary("a counterbore's tool"):
                cut = BRepPrimAPI_MakeCylinder(
                    gp_Ax2(gp_Pnt(*(surface - inward * margin)), gp_Dir(*inward)), cb_radius,
                    margin + float(cb_depth)).Shape()  # fmt: skip
            tools.append(SolidProduct(cut, named_by(cut, lambda f: (Name(
                ctx.step, "counterbore_wall" if _plane_of(f) is None else "counterbore_floor"),))))  # fmt: skip
        cs_diameter = ctx.params.get("countersink_diameter")
        if cs_diameter is not None:
            cs_radius = float(cs_diameter) / 2.0
            if cs_radius <= radius:
                raise DesignError("countersink diameter must exceed the hole diameter",
                                  countersink_diameter=2 * cs_radius, diameter=2 * radius)  # fmt: skip
            half_angle = ctx.angle("countersink_angle", math.radians(90.0)) / 2.0
            if not 0.05 < half_angle < 1.5:
                raise DesignError(
                    "a countersink's angle is between a few and 170 degrees"
                )
            slope = math.tan(half_angle)
            outer = cs_radius + margin * slope
            sink = (cs_radius - radius) / slope
            with boundary("a countersink's tool"):
                cone = BRepPrimAPI_MakeCone(
                    gp_Ax2(gp_Pnt(*(surface - inward * margin)), gp_Dir(*inward)), outer, radius,
                    margin + sink).Shape()  # fmt: skip
            tools.append(SolidProduct(cone, named_by(cone, lambda f: (Name(
                ctx.step, "countersink" if _plane_of(f) is None else "countersink_end"),))))  # fmt: skip
    except DesignError as error:
        raise ctx.fail(error) from error

    made = combine(ctx, "subtract", [base, *tools])
    before = volume(base.shape)
    expect = (
        before - sum(volume(t.shape) for t in tools),
        before,
        "a hole removes no more than its tools",
    )
    return SolidProduct(
        made.shape,
        made.names,
        notes=(*made.notes, *notes),
        lost=made.lost,
        expect=expect,
    )


BUILDERS: Mapping[str, Callable[[Context], Product]] = {"hole": _hole}
