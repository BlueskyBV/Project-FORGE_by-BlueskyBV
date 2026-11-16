"""Solids swept from outlines: extrude, revolve, sweep, pipe, coil, loft (docs/V2-stage3.md, 7.2).

Each is V1's builder read as a definition:

- **extrude**: the profile's face swept along its plane's normal over V1's
  span (``normal`` from the plane, ``symmetric`` centred on it, ``reverse``
  behind it); the end faces ``ends`` chooses rounded or chamfered (V1's
  ``start`` is the face on the sketch plane whatever the mode); a draft
  tapers from V1's low end, inward for a positive angle;
- **revolve**: as V1 reads it, the profile's u the radius from the axis and v
  the height along it from the axis's origin (whatever plane it was sketched
  on), only its part at u ≥ 0, turned from ``Frame.from_axis``'s x by the
  right hand;
- **sweep**: each straight run the profile extruded in a twist-free frame
  (V1's first frame, carried round each corner by the corner's turn),
  lengthened at a turn by the section's reach times tan(turn/2) as V1 lengthens
  it; each corner V1 rounds to ``bend_radius`` a true arc, the profile turned
  about it; all fused;
- **pipe**: a cylinder per straight run, a ball at each sharp joint, a torus
  segment per ``bend_radius`` arc; the bore the same, lengthened past the
  open ends by the outer radius as V1; fused, the bore cut;
- **coil**: a circle swept along a true helix starting where V1's starts,
  right-handed, its ends square to the wire;
- **loft**: V1's ordering of the two outlines, joined by a ruled loft.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepLib import BRepLib
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakeRevol,
    BRepPrimAPI_MakeSphere,
)
from OCP.GC import GC_MakeSegment2d
from OCP.Geom import Geom_CylindricalSurface
from OCP.gp import gp_Ax2, gp_Ax3, gp_Circ, gp_Dir, gp_Pnt, gp_Pnt2d
from OCP.LocOpe import LocOpe_DPrism
from OCP.TopoDS import TopoDS

from ..aftercheck import blend_bounds, check_volume
from ..errors import DesignError, OperationError
from ..geom import Frame, ax1, rotation_about, unit
from ..make import boolean, one_solid, prism, round_edges, unify
from ..names import Name, Names, carry, named_by
from ..occt import (
    area_centroid,
    boundary,
    edges,
    faces,
    perimeter,
    plane_of,
    surface_area,
    volume,
)
from ..products import Context, Product, SolidProduct
from ..profiles import Profile, half_plane, v_extremes

__all__ = ["BUILDERS", "extrusion", "fuse_named"]

Array = Any


# --- shared pieces -------------------------------------------------------------------------


def _plane_of(face: Any) -> tuple[Array, Array] | None:
    """(a point, the outward normal) of a planar face, or None."""
    found = plane_of(face)
    if found is None:
        return None
    return np.array(found[0]), np.array(found[1])


def _on_plane(face: Any, point: Array, normal: Array) -> bool:
    """Whether ``face`` is planar and lies in the plane through ``point`` square to ``normal`` (either way)."""
    found = _plane_of(face)
    if found is None:
        return False
    origin, n = found
    return bool(
        abs(abs(float(fv.matmul(n, normal))) - 1.0) < 1e-9
        and abs(float(fv.matmul(origin - point, normal))) < 1e-6
    )


def fuse_named(step: str, pieces: Sequence[SolidProduct]) -> SolidProduct:
    """The pieces fused into one, their names carried, faces on one surface merged."""
    if len(pieces) == 1:
        return pieces[0]
    fused = boolean("union", [pieces[0].shape], [p.shape for p in pieces[1:]])
    carried = carry([p.names for p in pieces], fused.shape, fused.history,
                    fallback=(Name(step, "other"),))  # fmt: skip
    merged = unify(fused.shape)
    again = carry(
        [carried.names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    return SolidProduct(
        one_solid(merged.shape), again.names.on(one_solid(merged.shape))
    )


def _named(shape: Any, step: str, role: Callable[[Any], str]) -> SolidProduct:
    return SolidProduct(shape, named_by(shape, lambda f: (Name(step, role(f)),)))


# --- extrusion --------------------------------------------------------------------------------


def extrusion(
    step: str,
    profile: Profile,
    frame: Frame,
    *,
    offset: float,
    distance: float,
    start_round: float = 0.0,
    end_round: float = 0.0,
    start_chamfer: float = 0.0,
    end_chamfer: float = 0.0,
    taper: float = 0.0,
) -> SolidProduct:
    """V1's ``ExtrusionSDF``: the profile swept from ``offset`` to ``offset + distance`` along the frame's z.

    The start is the low end (w = offset), whatever the mode the caller is
    building. Faces: ``start_face``, ``end_face``, ``side``; ``round`` and
    ``bevel`` where the ends' edges are rounded or chamfered. ``taper`` is
    the draft's tangent, inward positive.

    What it expects of its volume V (section 8.2), for a profile of area A
    and perimeter P, length h: A·h, plain; drafted inward, at most A·h;
    drafted outward (OpenCascade rounds the corners as V1's field does),
    from A·h to Steiner's A·h + P·t·h²/2 + π·t²·h³/3 (equal for a convex
    profile); the ends rounded or chamfered, the solid before them less at
    most what the blends move (:func:`~forge_occ.aftercheck.blend_bounds`).
    The solid before the ends is held to its own expectation here.
    """
    if distance <= 0.0:
        raise DesignError("an extrusion's distance must be positive", distance=distance)
    for name, value in (("start_round", start_round), ("end_round", end_round)):
        if value < 0.0 or value > distance / 2.0 + 1e-9:
            raise DesignError("an end edge's radius is at most half the extrusion's length",
                              **{name: value, "distance": distance})  # fmt: skip
    for name, value in (("start_chamfer", start_chamfer), ("end_chamfer", end_chamfer)):
        if value < 0.0 or value > distance + 1e-9:
            raise DesignError("an end edge's chamfer is at most the extrusion's length",
                              **{name: value, "distance": distance})  # fmt: skip
    if abs(taper) >= 10.0:
        raise DesignError("a draft is an angle well under 90 degrees", taper=taper)
    z = np.asarray(frame.z, dtype=np.float64)
    low = frame.moved(z * offset)
    face = profile.face(low)
    if taper:
        angle = fs.atan(taper)
        with boundary("a drafted extrusion"):
            drafted = LocOpe_DPrism(face, distance / fs.cos(angle), angle)
            shape = drafted.Shape()
        if shape.IsNull():
            raise OperationError("OpenCascade could not draft the extrusion")
    else:
        shape = prism(face, z * distance).shape
    shape = one_solid(shape)
    start_point = np.asarray(low.origin)
    end_point = start_point + z * distance

    def role(f: Any) -> str:
        if _on_plane(f, start_point, z):
            return "start_face"
        if _on_plane(f, end_point, z):
            return "end_face"
        return "side"

    held = _prism_expect(face, distance, taper)
    plain = replace(_named(shape, step, role), expect=held)
    if not (start_round or end_round or start_chamfer or end_chamfer):
        return plain
    check_volume(plain.shape, (held[0], held[1]), held[2])
    before = volume(plain.shape)
    pieces: list[tuple[SolidProduct, float]] = []
    if start_round or end_round:
        pieces.append(_round_ends(step, plain, start_round, end_round, bevel=False))
    if start_chamfer or end_chamfer:
        pieces.append(_round_ends(step, plain, start_chamfer, end_chamfer, bevel=True))
    removed = sum(most for _, most in pieces)
    expect = (
        before - removed,
        before,
        "rounding or chamfering an extrusion's ends removes no more than its blends move",
    )
    if len(pieces) == 1:
        return replace(pieces[0][0], expect=expect)
    (rounded, _), (bevelled, _) = pieces
    # Both rounded and chamfered: V1 takes the larger field, the solids' common part.
    common = boolean("intersect", [rounded.shape], [bevelled.shape])
    carried = carry([rounded.names, bevelled.names], common.shape, common.history,
                    fallback=(Name(step, "other"),))  # fmt: skip
    merged = unify(common.shape)
    names = carry(
        [carried.names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    solid = one_solid(merged.shape)
    return SolidProduct(solid, names.names.on(solid), expect=expect)


def _prism_expect(face: Any, distance: float, taper: float) -> tuple[float, float, str]:
    """What an extrusion of ``face`` by ``distance``, drafted by ``taper`` (inward positive), holds."""
    prism = surface_area(face) * distance
    if taper > 0.0:
        return 0.0, prism, "an extrusion drafted inward is no larger than its prism"
    if taper < 0.0:
        t, h = -taper, distance
        steiner = (
            prism
            + perimeter(face) * t * h * h / 2.0
            + math.pi * t * t * (h * h * h) / 3.0
        )
        return (
            prism,
            steiner,
            "an extrusion drafted outward is between its prism and Steiner's bound",
        )
    return prism, prism, "an extrusion's volume is its profile's area times its length"


def _round_ends(
    step: str, plain: SolidProduct, start: float, end: float, *, bevel: bool
) -> tuple[SolidProduct, float]:
    """The plain extrusion with the edges of its start face (by ``start``) and end face (by ``end``) rounded or chamfered; and the most volume that can remove."""
    chosen: list[tuple[float, Any]] = []
    for face, held in plain.names.items():
        roles = {n.role for n in held}
        size = start if "start_face" in roles else end if "end_face" in roles else 0.0
        if size > 0.0:
            chosen.extend((size, e) for e in edges(face))
    sizes = sorted({s for s, _ in chosen})
    shape = plain.shape
    names = plain.names
    role = "bevel" if bevel else "round"
    removed = 0.0
    for size in sizes:
        these = [e for s, e in chosen if s == size]
        # Edges of the shape as it is now (an earlier size may have changed them).
        current = [e for e in edges(shape) if any(e.IsSame(t) for t in these)]
        made = round_edges(shape, current, size, bevel=bevel)
        most, _ = blend_bounds(shape, made.rounded, made.sizes, bevel=bevel)
        removed += most
        carried = carry(
            [names], made.shape, made.history, lambda _f: (Name(step, role),)
        )
        shape, names = made.shape, carried.names
    return SolidProduct(shape, names), removed


def _extrude(ctx: Context) -> Product:
    source = ctx.profile(0)
    distance = ctx.length("distance")
    mode = ctx.option("mode", "normal")
    offset = {"symmetric": -distance / 2.0, "reverse": -distance}.get(mode, 0.0)
    ends = ctx.option("ends", "both")
    radius = ctx.length("end_radius", 0.0)
    chamfer = ctx.length("end_chamfer", 0.0)
    near, far = ends in ("both", "start"), ends in ("both", "end")
    if mode == "reverse":
        near, far = far, near  # the sketch-plane face is the high end
    return extrusion(
        ctx.step, source.profile, source.frame, offset=offset, distance=distance,
        start_round=radius if near else 0.0, end_round=radius if far else 0.0,
        start_chamfer=chamfer if near else 0.0, end_chamfer=chamfer if far else 0.0,
        taper=fs.tan(ctx.angle("draft_angle", 0.0)),
    )  # fmt: skip


# --- revolve ----------------------------------------------------------------------------------


def _revolve(ctx: Context) -> Product:
    source = ctx.profile(0)
    axis = ctx.axis(1)
    angle = ctx.angle("angle")
    if angle <= 0.0:
        raise ctx.fail(
            DesignError("a revolve turns through more than nothing", angle=angle)
        )
    reference = Frame.from_axis(axis.origin, axis.direction)
    # V1 reads the outline with u the radius and v the height along the axis.
    half = Frame.through(
        axis.origin, reference.x, axis.direction, np.cross(reference.x, axis.direction)
    )
    _, u_hi, v_lo, v_hi = source.profile.bounds()
    if u_hi <= 0.0:
        raise ctx.fail(
            DesignError(
                "the outline lies wholly on the far side of the axis: nothing to turn"
            )
        )
    keep = half_plane(v_lo - 1.0, v_hi + 1.0, u_hi + 1.0)
    face = source.profile.face(half, within=keep)
    full = angle >= 2.0 * math.pi - 1e-9
    with boundary("a revolve"):
        maker = (BRepPrimAPI_MakeRevol(face, ax1(axis.origin, axis.direction)) if full
                 else BRepPrimAPI_MakeRevol(face, ax1(axis.origin, axis.direction), angle))  # fmt: skip
        maker.Build()
        if not maker.IsDone():
            raise ctx.fail(OperationError("OpenCascade could not revolve the outline"))
        shape = one_solid(maker.Shape())
        first, last = maker.FirstShape(), maker.LastShape()

    def role(f: Any) -> str:
        if not full and f.IsSame(first):
            return "start_face"
        if not full and f.IsSame(last):
            return "end_face"
        return "side"

    d = unit(axis.direction)
    v_lo, v_hi = v_extremes(source.profile)
    origin = np.asarray(axis.origin, dtype=np.float64)

    def names(f: Any) -> tuple[Name, ...]:
        """Its role; and a full turn's flat ends, square to the axis at the outline's greatest and least heights, are its ``top`` and ``base`` too."""
        found = [Name(ctx.step, role(f))]
        plane = _plane_of(f) if full else None
        if plane is not None:
            at, normal = plane
            height = float(fv.matmul(at - origin, d))
            if float(fv.matmul(normal, d)) > 1.0 - 1e-9 and abs(height - v_hi) <= 1e-7:
                found.append(Name(ctx.step, "top"))
            elif (
                float(fv.matmul(normal, d)) < -1.0 + 1e-9 and abs(height - v_lo) <= 1e-7
            ):
                found.append(Name(ctx.step, "base"))
        return tuple(found)

    # Pappus: the section's area times the path of its centroid.
    area = surface_area(face)
    centre = np.asarray(area_centroid(face)) - origin
    reach = float(fv.norm(centre - (fv.matmul(centre, d)) * d))
    swept = area * reach * (2.0 * math.pi if full else angle)
    return SolidProduct(
        shape,
        named_by(shape, names),
        expect=(swept, swept, "a revolve's volume as Pappus says"),
    )


# --- sweep and pipe -------------------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    start: Array
    end: Array
    tangent: Array


@dataclass(frozen=True)
class _Bend:
    """An arc of the path: from ``start`` (tangent ``before``) to ``end`` (tangent ``after``), round ``centre``."""

    start: Array
    end: Array
    centre: Array
    axis: Array
    angle: float
    radius: float


def _path(points: Sequence[Sequence[float]], radius: float) -> list[_Run | _Bend]:
    """V1's path, its corners rounded to ``radius`` as ``round_the_path`` does (cut back at most half of either run), as true arcs."""
    pts = [np.asarray(p, dtype=np.float64) for p in points]
    if len(pts) < 2:
        raise DesignError("a path is two or more points")
    # Points written twice in a row are one.
    kept = [pts[0]]
    for p in pts[1:]:
        if float(fv.norm(p - kept[-1])) > 1e-9:
            kept.append(p)
    if len(kept) < 2:
        raise DesignError("a path needs two different points")
    pieces: list[_Run | _Bend] = []
    cursor = kept[0]
    for i in range(1, len(kept) - 1):
        here, before, after = kept[i], kept[i - 1], kept[i + 1]
        a, b = before - here, after - here
        la, lb = float(fv.norm(a)), float(fv.norm(b))
        a, b = a / la, b / lb
        angle = fs.acos(float(np.clip(fv.matmul(a, b), -1.0, 1.0)))
        if radius <= 0.0 or angle < 1e-6 or angle > math.pi - 1e-6:
            pieces.append(_Run(cursor, here, unit(here - cursor)))
            cursor = here
            continue
        cut = min(radius / fs.tan(angle / 2.0), la / 2.0, lb / 2.0)
        r = cut * fs.tan(angle / 2.0)
        start, end = here + a * cut, here + b * cut
        bisector = (a + b) / float(fv.norm(a + b))
        centre = here + bisector * (r / fs.sin(angle / 2.0))
        if float(fv.norm(start - cursor)) > 1e-9:
            pieces.append(_Run(cursor, start, unit(start - cursor)))
        turn_axis = unit(np.cross(-a, b))
        pieces.append(_Bend(start, end, centre, turn_axis, math.pi - angle, r))
        cursor = end
    pieces.append(_Run(cursor, kept[-1], unit(kept[-1] - cursor)))
    return pieces


def _first_frame(tangent: Array) -> tuple[Array, Array]:
    """V1's first frame: normal = helper cross t, binormal = t cross normal."""
    helper = (
        np.array([0.0, 0.0, 1.0])
        if abs(tangent[2]) < 0.9
        else np.array([1.0, 0.0, 0.0])
    )
    normal = np.cross(helper, tangent)
    normal = normal / fv.norm(normal)
    return normal, np.cross(tangent, normal)


def _tangent_in(piece: _Run | _Bend) -> Array:
    if isinstance(piece, _Run):
        return piece.tangent
    return unit(np.cross(piece.axis, piece.start - piece.centre))


def _tangent_out(piece: _Run | _Bend) -> Array:
    if isinstance(piece, _Run):
        return piece.tangent
    return unit(np.cross(piece.axis, piece.end - piece.centre))


def _turn(before: Array, after: Array) -> Array:
    """The rotation that takes tangent ``before`` to ``after`` about their common normal (identity if they agree)."""
    axis = np.cross(before, after)
    s = float(fv.norm(axis))
    c = float(np.clip(fv.matmul(before, after), -1.0, 1.0))
    if s < 1e-12:
        return np.eye(3)
    return rotation_about(axis / s, fs.atan2(s, c))


def _section_frames(pieces: Sequence[_Run | _Bend]) -> list[tuple[Array, Array]]:
    """The (normal, binormal) the section has at the start of each piece, carried twist-free."""
    normal, binormal = _first_frame(_tangent_in(pieces[0]))
    frames = []
    previous = _tangent_in(pieces[0])
    for piece in pieces:
        r = _turn(previous, _tangent_in(piece))
        normal, binormal = fv.matmul(r, normal), fv.matmul(r, binormal)
        frames.append((normal, binormal))
        if isinstance(piece, _Bend):
            r = rotation_about(piece.axis, piece.angle)
            normal, binormal = fv.matmul(r, normal), fv.matmul(r, binormal)
        previous = _tangent_out(piece)
    return frames


def _reach(profile: Profile) -> float:
    u_lo, u_hi, v_lo, v_hi = profile.bounds()
    return max(abs(u_lo), abs(u_hi), abs(v_lo), abs(v_hi))


def _sweep(ctx: Context) -> Product:
    source = ctx.profile(0)
    pieces = _path(ctx.params.get("path") or (), ctx.length("bend_radius", 0.0))
    frames = _section_frames(pieces)
    reach = _reach(source.profile)
    built: list[SolidProduct] = []
    for index, (piece, (normal, binormal)) in enumerate(
        zip(pieces, frames, strict=True)
    ):
        if isinstance(piece, _Bend):
            t = _tangent_in(piece)
            frame = Frame.through(piece.start, normal, binormal, t)
            face = source.profile.face(frame)
            with boundary("turning a sweep's section round a bend"):
                maker = BRepPrimAPI_MakeRevol(
                    face, ax1(piece.centre, piece.axis), piece.angle
                )
                maker.Build()
                shape = one_solid(maker.Shape())
            built.append(_named(shape, ctx.step, lambda _f: "side"))
            continue
        # A straight run, lengthened at a sharp turn as V1 lengthens it.
        pad_lo = pad_hi = 0.0
        if index > 0 and isinstance(pieces[index - 1], _Run):
            turn = fs.acos(
                float(
                    np.clip(
                        fv.matmul(piece.tangent, _tangent_out(pieces[index - 1])), -1, 1
                    )
                )
            )
            pad_lo = reach * fs.tan(min(turn, 1.4) / 2.0)
        if index + 1 < len(pieces) and isinstance(pieces[index + 1], _Run):
            turn = fs.acos(
                float(
                    np.clip(
                        fv.matmul(piece.tangent, _tangent_in(pieces[index + 1])), -1, 1
                    )
                )
            )
            pad_hi = reach * fs.tan(min(turn, 1.4) / 2.0)
        length = float(fv.norm(piece.end - piece.start))
        origin = piece.start - piece.tangent * pad_lo
        frame = Frame.through(origin, normal, binormal, piece.tangent)
        run = extrusion(
            ctx.step,
            source.profile,
            frame,
            offset=0.0,
            distance=length + pad_lo + pad_hi,
        )
        built.append(run)
    fused = fuse_named(ctx.step, built)
    first, last = pieces[0], pieces[-1]
    start_point, start_t = np.asarray(first.start), _tangent_in(first)
    end_point, end_t = np.asarray(last.end), _tangent_out(last)

    def role(f: Any) -> str:
        if _on_plane(f, start_point, start_t):
            return "start_face"
        if _on_plane(f, end_point, end_t):
            return "end_face"
        return "side"

    return _named(fused.shape, ctx.step, role)


def _tube(
    step: str, pieces: Sequence[_Run | _Bend], radius: float, role: str
) -> SolidProduct:
    """V1's ``TubeSDF`` chain: a capped cylinder per run, a ball at each joint between runs, a torus segment per arc."""
    built: list[SolidProduct] = []
    for index, piece in enumerate(pieces):
        with boundary("a tube's piece"):
            if isinstance(piece, _Run):
                length = float(fv.norm(piece.end - piece.start))
                shape = BRepPrimAPI_MakeCylinder(
                    gp_Ax2(gp_Pnt(*piece.start), gp_Dir(*piece.tangent)), radius, length
                ).Shape()
            else:
                ring_frame = Frame.through(
                    piece.start,
                    unit(piece.start - piece.centre),
                    piece.axis,
                    _tangent_in(piece),
                )
                from ..profiles import circle as circle_profile

                disc = circle_profile((0.0, 0.0), 2.0 * radius).face(ring_frame)
                maker = BRepPrimAPI_MakeRevol(
                    disc, ax1(piece.centre, piece.axis), piece.angle
                )
                maker.Build()
                shape = one_solid(maker.Shape())
        built.append(_named(shape, step, lambda _f: role))
        if (
            index > 0
            and isinstance(piece, _Run)
            and isinstance(pieces[index - 1], _Run)
        ):
            with boundary("a tube's joint"):
                ball = BRepPrimAPI_MakeSphere(gp_Pnt(*piece.start), radius).Shape()
            built.append(_named(ball, step, lambda _f: role))
    return fuse_named(step, built)


def _pipe(ctx: Context) -> Product:
    pieces = _path(ctx.params.get("path") or (), ctx.length("bend_radius", 0.0))
    outer = ctx.length("diameter") / 2.0
    inner = ctx.length("inner_diameter", 0.0) / 2.0
    if outer <= 0.0:
        raise ctx.fail(DesignError("a pipe needs a positive diameter"))
    if not 0.0 <= inner < outer:
        raise ctx.fail(
            DesignError(
                "a pipe's bore is smaller than the pipe", inner=inner, outer=outer
            )
        )
    body = _tube(ctx.step, pieces, outer, "surface")
    start, end = np.asarray(pieces[0].start), np.asarray(pieces[-1].end)
    t0, t1 = _tangent_in(pieces[0]), _tangent_out(pieces[-1])
    if inner > 0.0:
        # The bore, lengthened past both open ends by the outer radius, as V1.
        bore_pieces = list(pieces)
        if isinstance(bore_pieces[0], _Run):
            bore_pieces[0] = _Run(
                bore_pieces[0].start - t0 * outer, bore_pieces[0].end, t0
            )
        else:
            bore_pieces.insert(0, _Run(start - t0 * outer, start, t0))
        if isinstance(bore_pieces[-1], _Run):
            last = bore_pieces[-1]
            bore_pieces[-1] = _Run(last.start, last.end + t1 * outer, t1)
        else:
            bore_pieces.append(_Run(end, end + t1 * outer, t1))
        bore = _tube(ctx.step, bore_pieces, inner, "bore")
        cut = boolean("subtract", [body.shape], [bore.shape])
        carried = carry([body.names, bore.names], cut.shape, cut.history,
                        fallback=(Name(ctx.step, "other"),))  # fmt: skip
        merged = unify(cut.shape)
        again = carry([carried.names], merged.shape, merged.history,
                      fallback=(Name(ctx.step, "other"),))  # fmt: skip
        body = SolidProduct(
            one_solid(merged.shape), again.names.on(one_solid(merged.shape))
        )

    def role(f: Any, held: frozenset[Name]) -> str:
        if _on_plane(f, start, t0):
            return "start_face"
        if _on_plane(f, end, t1):
            return "end_face"
        return "bore" if any(n.role == "bore" for n in held) else "surface"

    table = tuple(
        frozenset({Name(ctx.step, role(f, held))}) for f, held in body.names.items()
    )
    return SolidProduct(body.shape, Names(body.shape, table))


# --- coil ------------------------------------------------------------------------------------


def _coil(ctx: Context) -> Product:
    radius = ctx.length("diameter") / 2.0
    pitch = ctx.length("pitch")
    turns = float(ctx.params.get("turns") or 0.0)
    wire = ctx.length("wire_diameter") / 2.0
    if radius <= 0.0 or turns <= 0.0:
        raise ctx.fail(
            DesignError(
                "a helix needs a radius and some turns", radius=radius, turns=turns
            )
        )
    if wire <= 0.0:
        raise ctx.fail(DesignError("a coil needs a wire diameter"))
    if pitch < 2.0 * wire - 1e-9 and turns > 1.0:
        raise ctx.fail(DesignError(
            "a coil's pitch must be at least its wire's diameter, or its turns run into each other",
            pitch=pitch, wire_diameter=2.0 * wire))  # fmt: skip
    z = unit(ctx.vector("axis", (0.0, 0.0, 1.0)), "a coil's axis")
    helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = unit(np.cross(z, helper))
    origin = np.asarray(ctx.vector("origin", (0.0, 0.0, 0.0)), dtype=np.float64)
    with boundary("a coil"):
        surface = Geom_CylindricalSurface(
            gp_Ax3(gp_Pnt(*origin), gp_Dir(*z), gp_Dir(*x)), radius
        )
        line = GC_MakeSegment2d(
            gp_Pnt2d(0.0, 0.0), gp_Pnt2d(2.0 * math.pi * turns, pitch * turns)
        ).Value()
        edge = BRepBuilderAPI_MakeEdge(line, surface).Edge()
        BRepLib.BuildCurves3d_s(edge, 1e-7)
        spine = BRepBuilderAPI_MakeWire(edge).Wire()
        y = np.cross(z, x)
        start = origin + radius * x
        tangent = unit(radius * y + z * pitch / (2.0 * math.pi))
        section = BRepBuilderAPI_MakeWire(
            BRepBuilderAPI_MakeEdge(
                gp_Circ(gp_Ax2(gp_Pnt(*start), gp_Dir(*tangent)), wire)
            ).Edge()
        ).Wire()
        sweep = BRepOffsetAPI_MakePipeShell(spine)
        sweep.SetMode(gp_Dir(*z))
        sweep.Add(section, False, False)
        sweep.Build()
        if not sweep.IsDone():
            raise ctx.fail(OperationError("OpenCascade could not sweep the coil"))
        sweep.MakeSolid()
        shape = one_solid(sweep.Shape())
        first, last = sweep.FirstShape(), sweep.LastShape()

    def role(f: Any) -> str:
        for end, name in ((first, "start_face"), (last, "end_face")):
            if any(f.IsSame(g) for g in faces(end)) or (
                    any(e.IsSame(g) for e in edges(f) for g in edges(end)) and _plane_of(f) is not None):  # fmt: skip
                return name
        return "surface"

    # Pappus for a section swept square to its path: the section's area times the helix's length.
    length = turns * math.hypot(2.0 * math.pi * radius, pitch)
    wound = math.pi * wire * wire * length
    return replace(
        _named(shape, ctx.step, role),
        expect=(wound, wound, "a coil's volume is its wire's section times its length"),
    )


# --- loft ------------------------------------------------------------------------------------


def _loft(ctx: Context) -> Product:
    first, second = ctx.profile(0), ctx.profile(1)
    a, b = first.frame, second.frame
    na, nb = np.asarray(a.z), np.asarray(b.z)
    if abs(abs(float(fv.matmul(na, nb))) - 1.0) > 1e-6:
        raise ctx.fail(DesignError("a loft's two profiles must lie on parallel planes"))
    if (
        float(fv.matmul(np.asarray(b.x), np.asarray(a.x))) < 0
        or float(fv.matmul(np.asarray(b.y), np.asarray(a.y))) < 0
    ):
        raise ctx.fail(DesignError(
            "a loft's two profiles must be sketched on planes facing the same way"))  # fmt: skip
    height = float(fv.matmul(np.asarray(b.origin) - np.asarray(a.origin), na))
    if abs(height) < 1e-9:
        raise ctx.fail(
            DesignError("the two profiles of a loft must be on different planes")
        )
    if height < 0:
        first, second = second, first
    lower = first.profile.face(first.frame)
    upper = second.profile.face(second.frame)
    with boundary("a loft"):
        loft = BRepOffsetAPI_ThruSections(True, True, 1e-6)
        from OCP.BRepTools import BRepTools

        loft.AddWire(BRepTools.OuterWire_s(TopoDS.Face(lower)))
        loft.AddWire(BRepTools.OuterWire_s(TopoDS.Face(upper)))
        loft.CheckCompatibility(True)
        loft.Build()
        if not loft.IsDone():
            raise ctx.fail(
                OperationError("OpenCascade could not loft between the two outlines")
            )
        shape = one_solid(loft.Shape())
        bottom, top = loft.FirstShape(), loft.LastShape()

    def role(f: Any) -> str:
        if f.IsSame(bottom):
            return "start_face"
        if f.IsSame(top):
            return "end_face"
        return "side"

    return _named(shape, ctx.step, role)


BUILDERS: Mapping[str, Callable[[Context], Product]] = {
    "extrude": _extrude,
    "revolve": _revolve,
    "sweep": _sweep,
    "pipe": _pipe,
    "coil": _coil,
    "loft": _loft,
}
