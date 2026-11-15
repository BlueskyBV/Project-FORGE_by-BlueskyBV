"""V1's bend, built exactly (docs/V2-stage3.md, 7.3).

V1's bend (``forge_geom.Bend``) is a map of space. In the bend's frame
(``e1`` along, ``e3`` toward with its part along ``e1`` removed, ``e2 = e3
cross e1``), with the inside face ``f`` and thickness ``t`` taken from V1's
envelope of the flat part, the middle radius ``m = r + t/2``, the zone from
``x0 = -mθ/2`` to ``x0 + mθ`` and the bend axis through ``(x0, f + r)``
along ``e2``:

- the part before the zone stays;
- the zone is wrapped round the axis: (x, z) ↦ angle (x - x0)/m, radius
  (f + r) - z;
- the part past it turns rigidly through θ about the axis;
- ``hold: middle`` then turns the whole bent part back by θ/2 about the axis
  so the middle of the zone's middle surface stays where it was flat.

Bends stated one after another on one flat part are one chain, applied far
end first (each fold meeting flat material), ``hold`` off; a bend whose
``along`` crosses an earlier one's acts on the solid as it is.

This builds the map exactly: the flat part split at the zone's planes, the
part before kept, the part past moved, and the zone revolved from its first
section when it is a prism along ``e1``; otherwise each face of the zone
mapped by the wrap (:mod:`forge_occ.ops.warp`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_SurfaceOfExtrusion
from OCP.TopoDS import TopoDS

from ..aftercheck import check_volume
from ..errors import DesignError
from ..geom import Motion, ax1, unit
from ..make import boolean, one_solid
from ..names import Name, Names, carry
from ..occt import (
    boundary,
    box_limits,
    centroid,
    edges,
    faces,
    surface_area,
    volume,
)
from ..products import Context, Product, SolidProduct
from .arrays import moved
from .holes import envelope_of
from .sweeps import _plane_of

__all__ = ["BUILDERS", "BendSpec"]


@dataclass(frozen=True)
class BendSpec:
    """One bend of a chain, as V1's ``Bend`` holds it."""

    position: tuple[float, float, float]
    along: tuple[float, float, float]
    toward: tuple[float, float, float]
    angle: float
    radius: float
    face: float
    thickness: float
    hold: float = 0.0

    @property
    def frame(self) -> tuple[Any, Any, Any]:
        e1 = unit(self.along, "a bend's `along`")
        e3 = np.asarray(self.toward, dtype=np.float64)
        e3 = e3 - e1 * float(e3 @ e1)
        if float(np.linalg.norm(e3)) < 1e-9:
            raise DesignError("a bend's `toward` runs along `along`: it must point off the solid's "
                              "face, across the way the solid runs")  # fmt: skip
        e3 = e3 / np.linalg.norm(e3)
        return e1, np.cross(e3, e1), e3

    @property
    def layout(self) -> tuple[float, float, float, float]:
        """(inside face, thickness, zone start, middle radius), local."""
        middle = self.radius + self.thickness / 2.0
        return self.face, self.thickness, -middle * self.angle / 2.0, middle

    def local(self, p: Any) -> Any:
        e1, e2, e3 = self.frame
        rel = np.asarray(p, dtype=np.float64) - np.asarray(self.position)
        return np.array([rel @ e1, rel @ e2, rel @ e3])

    def world(self, x: float, y: float, z: float) -> Any:
        e1, e2, e3 = self.frame
        return np.asarray(self.position) + x * e1 + y * e2 + z * e3

    def rotation_by(self, turn: float) -> Any:
        """V1's rotation through ``turn`` about the bend axis (as V1's ``rotation_by``)."""
        e1, e2, e3 = self.frame
        c, s = math.cos(turn), math.sin(turn)
        frame = np.column_stack([e1, e2, e3])
        local = np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])
        return frame @ local @ frame.T

    def axis_point(self) -> Any:
        inside, _, start, _ = self.layout
        return self.world(start, 0.0, inside + self.radius)

    def past_motion(self) -> Motion:
        """The rigid motion V1 gives the part past the zone."""
        inside, _, start, middle = self.layout
        rotation = self.rotation_by(self.angle)
        # A point at the zone's end on the axis's level maps to the axis's foot, turned.
        end = self.world(start + middle * self.angle, 0.0, inside + self.radius)
        target = self.axis_point()
        return Motion.of(rotation, target - rotation @ end)

    def forward(self, p: Any) -> Any:
        """V1's unheld map of one point of the flat part."""
        x, y, z = self.local(p)
        inside, _, start, middle = self.layout
        cx, cz = start, inside + self.radius
        theta = self.angle
        if start < x < start + middle * theta:
            phi = (x - start) / middle
            r = cz - z
            return self.world(cx + r * math.sin(phi), y, cz - r * math.cos(phi))
        if x >= start + middle * theta:
            a, b = x - start - middle * theta, z - cz
            return self.world(cx + a * math.cos(theta) - b * math.sin(theta), y,
                              cz + a * math.sin(theta) + b * math.cos(theta))  # fmt: skip
        return np.asarray(p, dtype=np.float64)

    def hold_motion(self) -> Motion | None:
        """V1's turn back by ``hold``: the zone's middle on its middle surface kept where it was flat."""
        if not self.hold:
            return None
        inside, thickness, start, middle = self.layout
        flat = self.world(
            start + middle * self.angle / 2.0, 0.0, inside - thickness / 2.0
        )
        bent = self.forward(flat)
        rotation = self.rotation_by(-self.hold)
        return Motion.of(rotation, flat - rotation @ bent)


def _faces_of(
    spec_frame: tuple[Any, Any, Any], position: Any, envelope: Any
) -> tuple[float, float]:
    """V1's ``faces_of``: the inside face and thickness from the envelope's corners."""
    _, _, e3 = spec_frame
    local = (envelope.corners() - np.asarray(position)) @ e3
    inside, outside = float(local.max()), float(local.min())
    return inside, max(inside - outside, 0.0)


def _slab(spec: BendSpec, x_lo: float, x_hi: float, reach: float) -> Any:
    """A box in the bend's frame from x_lo to x_hi along e1, ``reach`` each way across."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    e1, _, e3 = spec.frame
    corner = spec.world(x_lo, -reach, -reach)
    with boundary("cutting at a bend's zone"):
        return BRepPrimAPI_MakeBox(gp_Ax2(gp_Pnt(*corner), gp_Dir(*e3), gp_Dir(*e1)),
                                   x_hi - x_lo, 2 * reach, 2 * reach).Shape()  # fmt: skip


def _piece(step: str, part: SolidProduct, slab: Any) -> SolidProduct | None:
    done = boolean("intersect", [part.shape], [slab])
    carried = carry(
        [part.names], done.shape, done.history, lambda _f: (Name(step, "cut"),)
    )
    if not faces(done.shape) or volume(done.shape) <= 1e-12:
        return None
    return SolidProduct(done.shape, carried.names)


def _is_prism(
    zone: SolidProduct, e1: Any, cuts: Sequence[float], spec: BendSpec
) -> bool:
    """Every face but the two cuts unchanged by a shift along e1."""
    for face in faces(zone.shape):
        surface = BRepAdaptor_Surface(TopoDS.Face(face))
        kind = surface.GetType()
        if kind == GeomAbs_Plane:
            normal = surface.Plane().Axis().Direction()
            n = np.array([normal.X(), normal.Y(), normal.Z()])
            if abs(float(n @ e1)) < 1e-9:
                continue
            if abs(abs(float(n @ e1)) - 1.0) < 1e-9:
                origin = surface.Plane().Location()
                x = spec.local((origin.X(), origin.Y(), origin.Z()))[0]
                if any(abs(x - c) < 1e-6 for c in cuts):
                    continue
            return False
        if kind == GeomAbs_Cylinder:
            d = surface.Cylinder().Axis().Direction()
            if abs(abs(float(np.array([d.X(), d.Y(), d.Z()]) @ e1)) - 1.0) < 1e-9:
                continue
            return False
        if kind == GeomAbs_SurfaceOfExtrusion:
            d = surface.Direction()
            if abs(abs(float(np.array([d.X(), d.Y(), d.Z()]) @ e1)) - 1.0) < 1e-9:
                continue
            return False
        return False
    return True


def _revolved(
    step: str, zone: SolidProduct, spec: BendSpec, start: float
) -> SolidProduct:
    """The prism zone wrapped: its first cut face turned about the bend axis through the angle."""
    e2 = spec.frame[1]
    sections = [f for f in faces(zone.shape) if _on_cut(f, spec, start)]
    if not sections:
        raise DesignError("the bend's zone has no section to turn")
    end = start + spec.layout[3] * spec.angle
    # The names on the zone's far cut (the part's own end face, where the zone reaches it).
    far = frozenset().union(
        *(n for f, n in zone.names.items() if _on_cut(f, spec, end))
    )
    pieces = []
    for section in sections:
        with boundary("turning a bend's zone"):
            maker = BRepPrimAPI_MakeRevol(
                section, ax1(spec.axis_point(), -e2), spec.angle
            )
            maker.Build()
            shape = one_solid(maker.Shape())
            first, last = maker.FirstShape(), maker.LastShape()
        # Each face the section's edge sweeps takes the names of the zone's face that edge was on;
        # the section's own face and its turned image take the names of the zone's cuts.
        table = []
        zone_faces = [(f, n) for f, n in zone.names.items() if not f.IsSame(section)]
        made: dict[int, frozenset[Name]] = {}
        result_faces = faces(shape)
        for edge in edges(section):
            owners = [n for f, n in zone_faces if any(edge.IsSame(e) for e in edges(f))]
            for generated in maker.Generated(edge):
                for k, f in enumerate(result_faces):
                    if f.IsSame(generated):
                        made[k] = (
                            frozenset().union(*owners)
                            if owners
                            else frozenset({Name(step, "zone")})
                        )
        cut = frozenset({Name(step, "cut")})
        own = next((n for g, n in zone.names.items() if g.IsSame(section)), cut)
        for k, f in enumerate(result_faces):
            if k in made:
                table.append(made[k])
            elif any(f.IsSame(g) for g in faces(first)):
                table.append(own | cut)
            elif any(f.IsSame(g) for g in faces(last)):
                table.append(far | cut)
            else:
                table.append(cut)
        pieces.append(SolidProduct(shape, Names(shape, tuple(table))))
    if len(pieces) == 1:
        return pieces[0]
    from .sweeps import fuse_named

    return fuse_named(step, pieces)


def _on_cut(face: Any, spec: BendSpec, x: float) -> bool:
    found = _plane_of(face)
    if found is None:
        return False
    origin, normal = found
    e1 = spec.frame[0]
    return (
        abs(abs(float(normal @ e1)) - 1.0) < 1e-9
        and abs(float(spec.local(origin)[0]) - x) < 1e-6
    )


def _bend_once(
    step: str, part: SolidProduct, spec: BendSpec, reach: float
) -> tuple[SolidProduct, float]:
    """One bend of the flat part (or of a part already bent farther along): (the result, its fit's tolerance)."""
    _, _, start, middle = spec.layout
    end = start + middle * spec.angle
    before = _piece(step, part, _slab(spec, -reach, start, reach))
    zone = _piece(step, part, _slab(spec, start, end, reach))
    past = _piece(step, part, _slab(spec, end, reach, reach))
    pieces = []
    tolerance = 0.0
    # Flat material thinner than SNAP either side of the zone (a zone sized to the whole part,
    # missing it by rounding) is dropped: it would only leave slivers the join can't make. The
    # part's own end faces it held are then the zone's cut faces there, and take their names.
    if before is not None and _extent(before, spec) < SNAP:
        if zone is not None:
            zone = _named_at(zone, spec, start, _end_names(step, before, spec))
        before, tolerance = None, SNAP
    if past is not None and _extent(past, spec) < SNAP:
        if zone is not None:
            zone = _named_at(zone, spec, end, _end_names(step, past, spec))
        past, tolerance = None, SNAP
    if before is not None:
        pieces.append(before)
    wrapped_volume = slack = 0.0
    if zone is not None:
        e1 = spec.frame[0]
        if _is_prism(zone, e1, (start, end), spec):
            image, fit = _revolved(step, zone, spec, start), 0.0
        else:
            from .warp import wrapped

            image, fit = wrapped(step, zone, spec)
            tolerance = max(tolerance, fit)
        slack = fit_slack(image, fit)
        wrapped_volume = _check_zone(zone, image, spec, slack)
        pieces.append(image)
    if past is not None:
        pieces.append(moved(past, spec.past_motion()))
    from .sweeps import fuse_named

    result = fuse_named(step, pieces)
    # The parts before and past the zone kept whole (one stays, one turns rigidly), the zone as wrapped.
    kept = sum(volume(p.shape) for p in (before, past) if p is not None)
    check_volume(result.shape, (kept + wrapped_volume - slack, kept + wrapped_volume + slack),
                 "a bend keeps the flat material either side of its zone, and wraps the zone")  # fmt: skip
    return result, tolerance


def _check_zone(
    zone: SolidProduct, image: SolidProduct, spec: BendSpec, slack: float
) -> float:
    """The wrapped zone's volume as the wrap makes it; that volume.

    The wrap takes (x, z) in the bend's frame to the angle (x - x0)/m and the
    radius (f + r) - z, so a volume element grows by ((f + r) - z)/m: the
    zone's volume becomes V·((f + r) - z̄)/m, z̄ its centroid's height (Pappus,
    for any zone). A prism zone is turned exactly; a mapped one's faces lie
    within the fit's tolerance of the wrap, so its volume within that times
    its area.
    """
    inside, _, _, middle = spec.layout
    v = volume(zone.shape)
    height = float(spec.local(centroid(zone.shape))[2])
    expected = v * (inside + spec.radius - height) / middle
    check_volume(
        image.shape,
        (expected - slack, expected + slack),
        "the zone's volume as the wrap (Pappus) says",
    )
    return expected


def fit_slack(image: SolidProduct, fit: float) -> float:
    """How far a mapped zone's volume may be from the wrap's: the fit's tolerance over the zone's area."""
    return 0.0 if fit <= 0.0 else fit * surface_area(image.shape)


#: How thin a piece of flat material either side of a bend zone may be and still be dropped (mm).
SNAP = 1e-3


def _end_names(step: str, sliver: SolidProduct, spec: BendSpec) -> frozenset[Name]:
    """The names of a sliver's faces square to the bend's ``along`` other than its own cut: the part's end faces it holds."""
    e1 = spec.frame[0]
    found: set[Name] = set()
    for face, names in sliver.names.items():
        plane = _plane_of(face)
        if plane is not None and abs(abs(float(plane[1] @ e1)) - 1.0) < 1e-9:
            found |= {n for n in names if n != Name(step, "cut")}
    return frozenset(found)


def _named_at(
    zone: SolidProduct, spec: BendSpec, x: float, extra: frozenset[Name]
) -> SolidProduct:
    """The zone with ``extra`` names added to its cut faces at ``x``."""
    if not extra:
        return zone
    table = tuple(
        names | extra if _on_cut(face, spec, x) else names
        for face, names in zone.names.items()
    )
    return replace(zone, names=Names(zone.shape, table))


def _extent(piece: SolidProduct, spec: BendSpec) -> float:
    """How far the piece reaches along the bend's ``along``."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(piece.shape, box, False, False)
    x0, y0, z0, x1, y1, z1 = box_limits(box)
    corners = np.array(
        [[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    )
    along = corners @ spec.frame[0]
    return float(along.max() - along.min())


def _bend(ctx: Context) -> Product:
    source = ctx.solid(0)
    angle = ctx.angle("angle")
    radius = ctx.params.get("radius")
    spread = ctx.params.get("bend_length")
    if radius is not None and spread is not None:
        raise ctx.fail(
            DesignError("a bend is sized by `radius` or by `bend_length`, not by both")
        )
    position = ctx.vector("position")
    along = ctx.vector("along")
    toward = ctx.vector("toward")
    earlier: tuple[BendSpec, ...] = source.chain
    flat: SolidProduct = source.flat if source.flat is not None else source
    probe = BendSpec(
        position,
        along,
        toward,
        angle if 0.0 < angle < math.pi else math.pi / 2,
        1.0,
        0.0,
        0.0,
    )
    try:
        e1 = probe.frame[0]
    except DesignError as error:
        raise ctx.fail(error) from error
    if any(abs(abs(float(b.frame[0] @ e1)) - 1.0) > 1e-9 for b in earlier):
        earlier, flat = (), source
    envelope, how = envelope_of(_flat_context(ctx, flat, source), flat.shape)
    face, thickness = _faces_of(probe.frame, position, envelope)
    if radius is None and spread is not None:
        if angle <= 0.0:
            radius = 1.0
        else:
            radius = float(spread) / angle - thickness / 2.0
            if radius <= 0.0:
                raise ctx.fail(DesignError(
                    f"the bend is tighter than the solid is thick: spread over {float(spread):g} mm, "
                    f"{math.degrees(angle):g} degrees needs a solid thinner than {2.0 * float(spread) / angle:g} mm",
                    thickness=thickness))  # fmt: skip
    if radius is None:
        radius = thickness
    if not 0.0 < angle < math.pi:
        raise ctx.fail(DesignError("a bend angle must be more than 0 and less than 180 degrees",
                                   angle_deg=math.degrees(angle)))  # fmt: skip
    if float(radius) <= 0.0:
        raise ctx.fail(
            DesignError(
                "a bend needs an inside radius greater than zero", radius=float(radius)
            )
        )
    held = ctx.option("hold", "start") == "middle"
    this = BendSpec(position, along, toward, angle, float(radius), face, thickness,
                    angle / 2.0 if held else 0.0)  # fmt: skip
    specs = [this, *earlier]
    if len(specs) > 1:
        specs = [replace(s, hold=0.0) for s in specs]
    specs.sort(key=lambda s: -float(np.asarray(s.position) @ e1))
    reach = (
        4.0 * envelope.diagonal
        + 4.0 * max(s.radius + s.thickness for s in specs)
        + 10.0
    )
    result = flat
    tolerance = 0.0
    for spec in specs:
        result, fit = _bend_once(ctx.step, result, spec, reach)
        tolerance = max(tolerance, fit)
    hold = specs[0].hold_motion() if len(specs) == 1 else None
    if hold is not None:
        result = moved(result, hold)
    notes = () if how == "v1" else (f"the face and thickness from the {how}",)
    return SolidProduct(result.shape, result.names, notes=notes, tolerance=tolerance,
                        chain=tuple(specs), flat=flat)  # fmt: skip


def _flat_context(ctx: Context, flat: SolidProduct, source: SolidProduct) -> Context:
    """The context whose input is the flat part, for V1's envelope of it."""
    if flat is source:
        return ctx
    # V1 peels bends off the solid: its envelope of the flat part is its first bend's input's.
    v1 = ctx.v1_input(0)
    while v1 is not None and type(getattr(v1, "solid", None)).__name__ == "Bend":
        v1 = type(v1)(solid=v1.solid.solid, entities=v1.entities)
    return replace(
        ctx, v1={"flat": v1} if v1 is not None else None, input_ids=("flat",)
    )


BUILDERS: Mapping[str, Callable[[Context], Product]] = {"bend": _bend}
