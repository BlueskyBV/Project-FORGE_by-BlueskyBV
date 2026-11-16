"""How the implicit kernel holds each operation against the exact one (docs/V2-stage3.md, 13.2 and 13.3).

The implicit kernel builds the same construction as ``forge_occ``, but some
operations it builds approximately (an arc as ten chords) and a few it
builds by a different meaning (its blend is a smooth union, not a fillet).
Per operation and its options this module fixes one of:

- **bounded by τ**: the implicit shape is within τ of the exact one near the
  step's faces, τ worked out from the step's resolved parameters and V1's
  own products (or measured, where only the exact side can: a profile's
  outline, a bend's fit), plus :data:`TAU`;
- **not applicable within a zone**: the meanings differ there by design;
  outside the zone the step is held to :data:`TAU` like any other.

Each entry is attached to faces by their names (``forge_occ`` names every
face by the step that made it and the role it has there, 9.2), so it
follows every later move, copy, mirror and bend, and it stays local: a
counterbore's τ applies near the counterbore's faces, not over the part.

| Operation | Entry |
|---|---|
| datums; box; cylinder, cone, sphere, torus, wedge; extrude (straight; ends rounded or chamfered on a convex profile; drafted inward on a convex profile); revolve; booleans (sharp); hole (plain; blind with a counterbore or countersink); patterns, mirror, transform; bend with a prism zone | bounded by 1e-4 mm |
| a profile (any kind) | τ = the distance between V1's outline and the exact one, measured; applies to the faces of every step built from it |
| ``sweep``, ``pipe`` with ``bend_radius`` | τ = (R + rho)(1 - cos(Δ/2)), R each arc's radius as V1 cuts it, rho the section's reach, Δ V1's step (the arc's turn over twelve) |
| ``sweep`` of a profile that isn't a circle about the path | not applicable within 2rho of its faces (the implicit kernel's frame along the path is not the exact one's) |
| ``coil`` | τ = R(1 - cos(π·turns/n)), n V1's point count (36 a turn, eight at least); and within 2rho of each end rho·tan(π·turns/n) more (V1's ends square to a chord) |
| ``hole``, through, with a counterbore or countersink | τ = half V1's step along the axis (the envelope's extent along the axis over 511), on the counterbore's and countersink's faces |
| ``hole``, ``first_wall``, with a counterbore or countersink | τ = V1's step finding the wall's faces (the cut's length over 800) |
| ``bend`` with a mapped zone | τ = the fit's measured error (and the 1e-3 mm slivers dropped either side of a zone) |
| ``extrude``, ends rounded or chamfered on a profile that isn't convex | not applicable within 2r (2c) of the rounded faces |
| ``extrude`` drafted outward, or inward on a profile that isn't convex | not applicable within the draft's offset (distance x tan(draft)) of its side faces |
| booleans with ``blend_radius`` or ``chamfer`` | not applicable where two operands' faces are each within 2r (2c) |
| ``shell``, ``offset`` | bounded by 1e-4 mm where the input is one box, cylinder or sphere; else not applicable within the thickness (the distance) of the faces of the step's part |
| ``loft`` | bounded by 1e-4 mm between two concentric circles; else not applicable within the loft's own size of its faces (both lofts lie in the box of their two sections) |
| ``fillet``, ``chamfer`` (v2's, down-converted to nothing) | not applicable within 2r (2c) of the rounded faces |
| ``text`` (v2's, down-converted to nothing) | not applicable within the letters' depth (and τ) of their faces: every point the letters take or add is within their depth of their floor or top |
| ``thread`` (v2's, down-converted to nothing) | not applicable within the thread's depth (and τ) of its faces: every point its groove takes is within that of its flanks or its root |
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from forge_ir.v2 import DocumentV2, Step
from forge_numeric import scalar as fs
from forge_numeric import vector as fv

from .compiler import compile_products, resolve_feature_parameters

__all__ = [
    "SNAP",
    "TAU",
    "Entry",
    "Faces",
    "coil_tau",
    "entries",
    "first_wall_tau",
    "path_tau",
    "through_hole_tau",
]

#: How closely the two kernels agree where nothing else is said (mm).
TAU = 1e-4
#: The flat slivers a bend drops either side of its zone (mm; forge_occ.ops.bend.SNAP).
SNAP = 1e-3
#: V1's samples: an arc of a path is twelve chords (``round_the_path``); a coil 36 points a turn, eight at least
#: (``helix_points``); a through hole's line 512 samples; a first wall's stretch 801.
PATH_STEPS = 12
COIL_PER_TURN = 36
COIL_LEAST = 8
HOLE_SAMPLES = 512
WALL_SAMPLES = 801


@dataclass(frozen=True)
class Faces:
    """Faces of the built part, by their names: those carrying a name of one of ``steps`` (with one of ``roles``; with any, if None)."""

    steps: frozenset[str]
    roles: frozenset[str] | None = None

    @staticmethod
    def of(step: str, *roles: str) -> Faces:
        return Faces(frozenset({step}), frozenset(roles) if roles else None)


@dataclass(frozen=True)
class Entry:
    """How the implicit kernel holds one step, near some of the part's faces.

    Bounded (``zone`` None): within ``near`` of ``faces`` (τ and a margin,
    when ``near`` is None), the implicit shape is within ``tau`` of the exact
    one. Not applicable (``zone`` set): within ``zone`` of ``faces`` the two
    are not compared, or, when ``apart`` is given, only where faces of at
    least two of ``apart`` are each within ``zone``.
    """

    step: str
    op: str
    why: str
    faces: Faces
    tau: float = TAU
    near: float | None = None
    zone: float | None = None
    apart: tuple[Faces, ...] = ()

    @property
    def applicable(self) -> bool:
        return self.zone is None


# --- the formulas ----------------------------------------------------------------------


def path_tau(
    path: Sequence[Sequence[float]], bend_radius: float, reach: float
) -> float:
    """The most a section of ``reach`` swept along V1's twelve-chord arcs strays from the true arcs: (R + rho)(1 - cos(Δ/2)), the worst corner."""
    pts = [np.asarray(p, dtype=np.float64) for p in path]
    worst = 0.0
    if bend_radius <= 0.0:
        return 0.0
    for i in range(1, len(pts) - 1):
        a, b = pts[i - 1] - pts[i], pts[i + 1] - pts[i]
        la, lb = float(fv.norm(a)), float(fv.norm(b))
        if la < 1e-9 or lb < 1e-9:
            continue
        angle = fs.acos(float(np.clip(fv.matmul(a / la, b / lb), -1.0, 1.0)))
        if angle < 1e-6 or angle > math.pi - 1e-6:
            continue
        cut = min(bend_radius / fs.tan(angle / 2.0), la / 2.0, lb / 2.0)
        r = cut * fs.tan(angle / 2.0)
        step = (math.pi - angle) / PATH_STEPS
        worst = max(worst, (r + reach) * (1.0 - fs.cos(step / 2.0)))
    return worst


def coil_tau(radius: float, wire: float, turns: float) -> tuple[float, float]:
    """V1's polyline coil against the true helix: (along the coil, more within 2rho of each end)."""
    count = max(COIL_LEAST, math.ceil(turns * COIL_PER_TURN))
    half = math.pi * turns / count
    return radius * (1.0 - fs.cos(half)), wire * fs.tan(half)


def through_hole_tau(
    envelope_lo: Sequence[float], envelope_hi: Sequence[float], axis: Sequence[float]
) -> float:
    """Half V1's step along a through hole's axis: where it finds the material's first and last points."""
    corners = np.array([[x, y, z] for x in (envelope_lo[0], envelope_hi[0]) for y in (envelope_lo[1], envelope_hi[1])
                        for z in (envelope_lo[2], envelope_hi[2])])  # fmt: skip
    d = np.asarray(axis, dtype=np.float64)
    d = d / fv.norm(d)
    along = fv.matmul(corners, d)
    return float(along.max() - along.min()) / (HOLE_SAMPLES - 1) / 2.0


def first_wall_tau(cut_length: float) -> float:
    """V1's step finding a first wall's faces: the cut's length over 800."""
    return abs(cut_length) / (WALL_SAMPLES - 1)


# --- the entries for a component -------------------------------------------------------


_CONVEX_KINDS = frozenset(
    {"profile_rectangle", "profile_circle", "profile_slot", "profile_polygon"}
)
_PRIMITIVES = frozenset({"box", "cylinder", "sphere"})


def _sketch_convex(points: Sequence[Sequence[float]]) -> bool:
    corners = [(float(p[0]), float(p[1])) for p in points]
    if len(corners) > 3 and fs.dist(corners[0], corners[-1]) < 1e-9:
        corners = corners[:-1]
    n = len(corners)
    turns = []
    for i in range(n):
        (ax, ay), (bx, by), (cx, cy) = corners[i - 1], corners[i], corners[(i + 1) % n]
        turns.append((bx - ax) * (cy - by) - (by - ay) * (cx - bx))
    return all(t >= 0.0 for t in turns) or all(t <= 0.0 for t in turns)


def _upstream(steps: Sequence[Step]) -> dict[str, frozenset[str]]:
    """Each step and every step before it in the graph that it is built from."""
    found: dict[str, frozenset[str]] = {}
    for step in steps:
        mine = {step.id}
        for i in step.inputs:
            mine |= found.get(i, frozenset({i}))
        found[step.id] = frozenset(mine)
    return found


def entries(document: DocumentV2, component: str, *, overrides: Mapping[str, Any] | None = None,
            measured: Mapping[str, float] | None = None, v1: Mapping[str, Any] | None = None) -> tuple[Entry, ...]:  # fmt: skip
    """The entries for every step of the component whose holding is anything but :data:`TAU` everywhere.

    ``measured`` is what only the exact side can know, by step: a profile's
    outline against V1's, a bend's fit. ``v1`` is V1's products for the
    component (built here if not given), for V1's envelopes.
    """
    part = document.component(component)
    resolution = part.parameters.resolve(overrides)
    steps = document.steps(component)
    by_id = {s.id: s for s in steps}
    upstream = _upstream(steps)
    measured = measured or {}
    if v1 is None:
        try:
            v1 = compile_products(
                document.down_converted().component(component), overrides=overrides
            )
        except Exception:  # V1 can't build it: its envelopes are unknown, the entries that need them say so
            v1 = {}
    consumers: dict[str, list[str]] = {}
    for s in steps:
        for i in s.inputs:
            consumers.setdefault(i, []).append(s.id)
    resolved = {step.id: _params(step, resolution, part.identifier) for step in steps}
    out: list[Entry] = []
    for step in steps:
        params = resolved[step.id]
        op = step.op
        if op.startswith("profile_"):
            tau = measured.get(step.id, TAU)
            users = frozenset(consumers.get(step.id, ()))
            if users and tau > TAU:
                out.append(Entry(step.id, op, "a profile: V1's outline against the exact one, measured",
                                 Faces(users), tau=TAU + tau))  # fmt: skip
        elif op == "extrude":
            out.extend(_extrude(step, params, by_id, resolved))
        elif op in ("sweep", "pipe"):
            out.extend(_swept(step, params, measured))
        elif op == "coil":
            radius, wire = (
                float(params["diameter"]) / 2.0,
                float(params["wire_diameter"]) / 2.0,
            )
            along, ends = coil_tau(radius, wire, float(params.get("turns") or 0.0))
            out.append(Entry(step.id, op, "a coil: V1's polyline against the true helix", Faces.of(step.id),
                             tau=TAU + along))  # fmt: skip
            out.append(Entry(step.id, op, "a coil's ends: V1's square to a chord", Faces.of(step.id, "start_face", "end_face"),
                             tau=TAU + along + ends, near=2.0 * wire))  # fmt: skip
        elif op == "hole":
            out.extend(_hole(step, params, v1))
        elif op == "bend":
            tau = measured.get(step.id, 0.0)
            if tau > 0.0:
                out.append(Entry(step.id, op, "a bend's mapped zone: the fit's error (and slivers dropped)",
                                 Faces.of(step.id), tau=TAU + tau))  # fmt: skip
        elif op in ("union", "subtract", "intersect"):
            size = max(
                float(params.get("blend_radius") or 0.0),
                float(params.get("chamfer") or 0.0),
            )
            if size > 0.0:
                operands = tuple(
                    Faces(upstream.get(i, frozenset({i}))) for i in step.inputs
                )
                out.append(Entry(step.id, op, "a blended or chamfered boolean: V1's smooth union is no fillet",
                                 Faces(upstream[step.id]), zone=2.0 * size, apart=operands))  # fmt: skip
        elif op in ("shell", "offset"):
            source = by_id.get(step.inputs[0]) if step.inputs else None
            size = abs(float(params.get("thickness") or params.get("distance") or 0.0))
            if source is None or source.op not in _PRIMITIVES:
                out.append(Entry(step.id, op, f"a {op} of anything but one box, cylinder or sphere: V1's field is no distance",
                                 Faces(upstream[step.id]), zone=size + TAU))  # fmt: skip
        elif op == "loft":
            out.extend(_loft(step, measured, v1))
        elif op in ("fillet", "chamfer"):
            size = float(params.get("radius") or params.get("distance") or 0.0)
            out.append(Entry(step.id, op, f"a {op}: down-converted to nothing for the implicit kernel",
                             Faces.of(step.id, "round", "bevel"), zone=2.0 * size))  # fmt: skip
        elif op == "text":
            out.append(Entry(step.id, op, "letters: down-converted to nothing for the implicit kernel",
                             Faces.of(step.id, "letter_wall", "letter_floor", "letter_top", "letter_mouth"),
                             zone=float(params["depth"]) + TAU))  # fmt: skip
        elif op == "thread":
            depth = 5.0 / 8.0 * math.sqrt(3.0) / 2.0 * float(params["pitch"])
            out.append(Entry(step.id, op, "a thread: down-converted to nothing for the implicit kernel",
                             Faces.of(step.id, "flank", "root", "runout"), zone=depth + TAU))  # fmt: skip
    return tuple(out)


def _params(step: Step, resolution: Any, component: str) -> Mapping[str, Any]:
    from forge_ir import Feature

    feature = step.feature if not step.v2_only else Feature(
        identifier=step.id, kind=step.op, inputs=step.inputs, parameters=step.params, role=step.role,
        pointer=step.pointer)  # fmt: skip
    return resolve_feature_parameters(feature, resolution, component, spec=step.spec)


def _profile_convex(profile: Step | None, params: Mapping[str, Any]) -> bool:
    """Whether a profile is convex: a rectangle, circle, slot or polygon always; a sketch of straight sides when its corners turn one way."""
    if profile is None:
        return False
    if profile.op in _CONVEX_KINDS:
        return True
    if profile.op == "profile_sketch" and not params.get("smooth"):
        points = params.get("points") or ()
        return len(points) >= 3 and _sketch_convex(points)
    return False


def _extrude(step: Step, params: Mapping[str, Any], by_id: Mapping[str, Step],
             resolved: Mapping[str, Mapping[str, Any]]) -> list[Entry]:  # fmt: skip
    profile = by_id.get(step.inputs[0]) if step.inputs else None
    convex = _profile_convex(
        profile, resolved.get(profile.id, {}) if profile is not None else {}
    )
    out = []
    size = max(
        float(params.get("end_radius") or 0.0), float(params.get("end_chamfer") or 0.0)
    )
    if size > 0.0 and not convex:
        out.append(Entry(step.id, "extrude", "ends rounded or chamfered on a profile that isn't convex",
                         Faces.of(step.id, "round", "bevel"), zone=2.0 * size))  # fmt: skip
    draft = float(params.get("draft_angle") or 0.0)
    if draft < 0.0 or (draft > 0.0 and not convex):
        offset = abs(float(params["distance"]) * fs.tan(draft))
        out.append(Entry(step.id, "extrude", "drafted outward, or inward on a profile that isn't convex",
                         Faces.of(step.id, "side"), zone=offset + TAU))  # fmt: skip
    return out


def _swept(
    step: Step, params: Mapping[str, Any], measured: Mapping[str, float]
) -> list[Entry]:
    path = params.get("path") or ()
    bend = float(params.get("bend_radius") or 0.0)
    if step.op == "pipe":
        reach = float(params["diameter"]) / 2.0
    else:
        reach = measured.get(f"{step.id}#reach", 0.0)
    out = []
    tau = path_tau(path, bend, reach)
    if tau > 0.0:
        out.append(
            Entry(
                step.id,
                step.op,
                "a path's arcs: V1's twelve chords",
                Faces.of(step.id),
                tau=TAU + tau,
            )
        )
    # The exact side says whether a sweep's profile is a circle centred on the path (0) or not (1).
    if step.op == "sweep" and measured.get(f"{step.id}#off_centre", 1.0) != 0.0:
        out.append(Entry(step.id, "sweep", "a sweep of anything but a circle about its path: the frames differ",
                             Faces.of(step.id), zone=2.0 * max(reach, TAU)))  # fmt: skip
    return out


def _hole(step: Step, params: Mapping[str, Any], v1: Mapping[str, Any]) -> list[Entry]:
    if (
        params.get("counterbore_diameter") is None
        and params.get("countersink_diameter") is None
    ):
        return []
    faces = Faces.of(step.id, "counterbore_wall", "counterbore_floor", "countersink")
    axis = params.get("axis") or (0.0, 0.0, 1.0)
    if params.get("depth") is not None:
        return []
    source = v1.get(step.inputs[0]) if step.inputs else None
    solid = getattr(source, "solid", None)
    if solid is None:
        return [Entry(step.id, "hole", "a counterbore V1 can't place (V1 can't build the hole's input)", faces,
                      zone=float(params.get("counterbore_depth") or 0.0) + float(params.get("diameter") or 0.0))]  # fmt: skip
    envelope = solid.envelope
    if str(params.get("through") or "all") == "first_wall":
        from .implicit_backend import _depth_through_the_first_wall

        direction = np.asarray(axis, dtype=np.float64)
        direction = direction / fv.norm(direction)
        start, end = _depth_through_the_first_wall(solid, np.asarray(params["position"], dtype=np.float64), direction,
                                                   envelope, float(params["diameter"]) / 2.0, step.id)  # fmt: skip
        return [Entry(step.id, "hole", "a first-wall hole's counterbore: V1's step finding the wall's faces", faces,
                      tau=TAU + first_wall_tau(end - start))]  # fmt: skip
    return [Entry(step.id, "hole", "a through hole's counterbore: half V1's step along the axis", faces,
                  tau=TAU + through_hole_tau(envelope.lo, envelope.hi, axis))]  # fmt: skip


def _loft(
    step: Step, measured: Mapping[str, float], v1: Mapping[str, Any]
) -> list[Entry]:
    # The exact side says whether the loft runs between two concentric circles (1) or not (0).
    if measured.get(f"{step.id}#concentric_circles", 0.0) == 1.0:
        return []
    product = v1.get(step.id)
    solid = getattr(product, "solid", None)
    size = float(solid.envelope.diagonal) if solid is not None else math.inf
    return [Entry(step.id, "loft", "a loft of anything but two concentric circles: V1's blend is no ruled surface",
                  Faces.of(step.id), zone=size)]  # fmt: skip
