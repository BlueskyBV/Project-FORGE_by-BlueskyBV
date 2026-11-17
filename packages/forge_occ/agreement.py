"""Second-kernel agreement: the exact part and the implicit kernel's, held to each other point by point (docs/V2-stage3.md, 13.4).

For a component both kernels build:

1. **Points.** (a) the exact part's coverage, each point moved along its
   exact normal both ways by its τ and a margin δ; (b) the same from the
   implicit part's surface (V1's own samples, its field's gradient for a
   normal); (c) a grid through the box round both.
2. **Kept**: the points at least τ + δ/2 from the exact part's surface, in
   no not-applicable zone (:mod:`forge_kernel.agreement`, its zones found by
   the faces' names).
3. **Every kept point is on the same side in both kernels.** One that isn't
   is a disagreement, reported with the point, both sides, the steps whose
   faces are near, and their entries.
4. **Volume**: the exact volume inside the implicit interval widened by each
   entry's faces' area times its τ (and each zone's faces' area times twice
   its reach).
5. **Names**: every face V1 publishes and finds on its part is found by
   ``forge_occ`` too; cylinders' radii and axes agree to their τ.
6. **Topology**: solids, voids and genus equal, unless a not-applicable zone
   is on the part, or the exact part has a wall or a gap the implicit mesh's
   grid can step over (reported, not counted).

δ is 0.01 mm, or five times the implicit mesh's deflection, whichever is
larger. The test is two-sided: (a) catches material the implicit kernel lost,
(b) material it added, (c) anything far from both surfaces.

Distances from faces are read from a fine mesh of the exact part, measured
from its surface; where a mesh distance can't decide a point (within the
mesh's measured deviation of the threshold) the exact distance decides it.
Every uncertainty is resolved by keeping fewer points, never more.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from forge_checks.mesh import Mesh, MeshView
from forge_checks.view import Side
from forge_ir.v2 import DocumentV2
from forge_kernel import Compiler, compile_products
from forge_kernel.agreement import TAU, Entry, Faces, entries
from forge_kernel.implicit_view import ImplicitView
from forge_numeric import vector as fv
from numpy.typing import NDArray
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS

from .aftercheck import distances_to
from .backend import BuildResult, OccBackend
from .errors import OperationError
from .export import _triangulate, deviation, refined
from .geom import Frame
from .make import compound
from .names import Names
from .occt import edges, faces, solids, surface_area
from .products import ProfileProduct, SolidProduct
from .view import BrepView, face_facts

__all__ = [
    "DELTA",
    "FINER",
    "AgreementReport",
    "Disagreement",
    "agree",
    "profile_distance",
]

Array = NDArray[np.float64]

#: The margin past τ at which the two kernels must agree (mm), at least.
DELTA = 0.01
#: About how many points of each surface are moved off it to be compared.
_SURFACE_POINTS = 15_000
#: How many cells across the implicit mesh is made again at, in turn, where it is sound but its topology differs
#: from the exact part's (a hole a cell or two across closes at 96).
FINER = (192, 256)
#: Points a side of the grid through the box.
_GRID = 24
#: A wall or a gap of the exact part narrower than this many of the implicit mesh's cells may be lost or closed
#: in the mesh whatever the field holds (grid points a cell apart can step over anything under sqrt(3) cells
#: across): where one is, the mesh's topology is not the implicit kernel's, and isn't counted.
_RESOLVED = 2.0
#: At most how many of the exact part's surface points the thinnest wall and gap are sought at.
_THIN_POINTS = 300_000
#: How nearly the face found across a wall or a gap faces back (cosine) for the two to be its sides, not a
#: wedge's (a wedge sharper than this is as thin, near its edge, as a wall).
_ACROSS = 0.9
#: The points are moved, each a little in a direction of its own, by about this share of δ: a test point
#: never sits exactly on a plane both kernels share (V1's field is exactly 0 on a face a tool shares with
#: its body, a set of no volume the side of which neither kernel can be asked).
_JITTER = 1e-2
#: Disagreements reported in full (all are counted).
_REPORTED = 40


@dataclass(frozen=True)
class Disagreement:
    point: tuple[float, float, float]
    exact: str
    implicit: str
    near: tuple[str, ...]
    entries: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class AgreementReport:
    """What holding the two kernels' parts to each other found."""

    component: str
    delta: float
    compared: int
    not_applicable: int
    too_near: int
    disagreements: int
    shown: tuple[Disagreement, ...]
    volume: Mapping[str, Any]
    names: Mapping[str, Any]
    topology: Mapping[str, Any]
    entries: tuple[Entry, ...]
    notes: tuple[str, ...] = field(default=())

    @property
    def holds(self) -> bool:
        return (self.disagreements == 0 and bool(self.volume["holds"]) and bool(self.names["holds"])
                and bool(self.topology["holds"]))  # fmt: skip

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component, "holds": self.holds, "delta": self.delta, "compared": self.compared,
            "not_applicable": self.not_applicable, "too_near": self.too_near, "disagreements": self.disagreements,
            "shown": [d.__dict__ for d in self.shown], "volume": dict(self.volume), "names": dict(self.names),
            "topology": dict(self.topology), "notes": list(self.notes),
            "entries": [{"step": e.step, "op": e.op, "why": e.why, "tau": e.tau, "zone": e.zone} for e in self.entries],
        }  # fmt: skip


# --- what only the exact side can measure ----------------------------------------------


def _outline_points(product: ProfileProduct, spacing: float) -> Array:
    """Points along the exact profile's boundary, in its own (u, v), at most ``spacing`` apart."""
    face = product.profile.face(Frame((0.0, 0.0, 0.0)))
    out = []
    for edge in edges(face):
        curve = BRepAdaptor_Curve(TopoDS.Edge(edge))
        first, last = curve.FirstParameter(), curve.LastParameter()
        length = GCPnts_AbscissaPoint.Length_s(curve, first, last, 1e-9)
        count = max(8, math.ceil(length / spacing) + 1)
        for t in np.linspace(first, last, count):
            p = curve.Value(float(t))
            out.append((p.X(), p.Y()))
    return np.asarray(out, dtype=np.float64)


def _v1_polygon(v1_profile: Any) -> Array | None:
    """V1's outline as the polygon it is, where it is one (a sketch's, a gear's); None for an analytic outline."""
    vertices = getattr(v1_profile, "vertices", None)
    if vertices is not None:
        return np.asarray(vertices, dtype=np.float64)
    if hasattr(v1_profile, "teeth"):
        from forge_geom.sdf import gear_outline

        return np.asarray(gear_outline(v1_profile.module, v1_profile.teeth, v1_profile.pressure_angle,
                                       centre=v1_profile.centre, rotation=v1_profile.rotation), dtype=np.float64)  # fmt: skip
    return None


def profile_distance(exact: ProfileProduct, v1_profile: Any) -> float:
    """How far apart the exact outline and V1's are, both ways, measured (mm).

    From the exact outline to V1's: V1's own distance (an exact distance to
    its outline) at points of the exact outline a twenty-thousandth of the
    profile's size apart. From V1's outline to the exact one, where V1's is a
    polygon (a sketch's, a gear's): the exact distance from each of its
    corners and from three points along each of its sides (where a chord is
    furthest from the arc it stands for) to the exact outline. An analytic
    outline of V1's is the exact one's own curve: the first way is the
    measure.
    """
    lo_u, hi_u, lo_v, hi_v = (float(x) for x in v1_profile.bounds())
    size = max(hi_u - lo_u, hi_v - lo_v, 1e-6)
    points = _outline_points(exact, size / 20000.0)
    found = float(
        np.abs(
            np.asarray(
                v1_profile.distance(points[:, 0], points[:, 1]), dtype=np.float64
            )
        ).max()
    )
    polygon = _v1_polygon(v1_profile)
    if polygon is None:
        return found
    after = np.roll(polygon, -1, axis=0)
    samples = np.concatenate(
        [polygon + (after - polygon) * t for t in (0.0, 0.25, 0.5, 0.75)]
    )
    meter = BRepExtrema_DistShapeShape()
    meter.LoadS2(compound(edges(exact.profile.face(Frame((0.0, 0.0, 0.0))))))
    other = 0.0
    for u, v in samples:
        meter.LoadS1(
            BRepBuilderAPI_MakeVertex(gp_Pnt(float(u), float(v), 0.0)).Vertex()
        )
        meter.Perform()
        if not meter.IsDone():
            raise RuntimeError(
                "OpenCascade could not measure a distance to a profile's outline"
            )
        other = max(other, float(meter.Value()))
    return max(found, other)


def _measured(
    document: DocumentV2, component: str, exact: BuildResult, v1: Mapping[str, Any]
) -> dict[str, float]:
    out: dict[str, float] = {}
    steps = document.steps(component)
    by_id = {s.id: s for s in steps}
    for step in steps:
        product = exact.products.get(step.id)
        if isinstance(product, ProfileProduct):
            theirs = v1.get(step.id)
            if theirs is not None and hasattr(theirs, "profile"):
                out[step.id] = profile_distance(product, theirs.profile)
        elif step.op == "bend":
            trace = next((t for t in exact.traces if t.step == step.id), None)
            if trace is not None and trace.tolerance:
                out[step.id] = trace.tolerance
        elif step.op == "sweep" and step.inputs:
            source = exact.products.get(step.inputs[0])
            if isinstance(source, ProfileProduct):
                pts = _outline_points(source, 1e-2)
                out[f"{step.id}#reach"] = float(fv.norm(pts, axis=1).max())
                circle = by_id[step.inputs[0]].op == "profile_circle"
                radii = fv.norm(pts, axis=1)
                out[f"{step.id}#off_centre"] = (
                    0.0 if circle and float(np.ptp(radii)) <= 1e-9 else 1.0
                )
        elif step.op == "loft" and len(step.inputs) == 2:
            sources = [exact.products.get(i) for i in step.inputs]
            concentric = all(isinstance(s, ProfileProduct) and by_id[i].op == "profile_circle"
                             for s, i in zip(sources, step.inputs, strict=True))  # fmt: skip
            if concentric:
                outlines = [
                    _outline_points(s, 1e-2)
                    for s in sources
                    if isinstance(s, ProfileProduct)
                ]
                concentric = all(
                    float(np.ptp(fv.norm(p, axis=1))) <= 1e-9 for p in outlines
                )
            out[f"{step.id}#concentric_circles"] = 1.0 if concentric else 0.0
    return out


# --- faces by their names, and distances from them --------------------------------------


def _faces_named(names: Names, which: Faces) -> list[int]:
    out = []
    for k, held in enumerate(names.table):
        if any(
            n.step in which.steps and (which.roles is None or n.role in which.roles)
            for n in held
        ):
            out.append(k)
    return out


class _Meshed:
    """The exact part meshed once, and distances from any set of its faces, each within the mesh's measured deviation.

    The mesh is made at ``deflection``, its triangles measured further than
    that from the surface split (``export.refined``), and then measured
    (``export.deviation``): the deviation found is the uncertainty every
    distance read from it carries, and a point the uncertainty leaves
    undecided is decided by the exact distance.
    """

    def __init__(self, shape: Any, deflection: float) -> None:
        made = _triangulate(shape, deflection, 0.1)
        try:
            self.mesh, self.owner, uv, near, self.whole = refined(
                shape, *made, deflection
            )
        except (
            OperationError
        ):  # not sound as made: measured from all the same, sides read exactly
            (self.mesh, self.owner, uv), near = made, None
            self.whole = MeshView(self.mesh, source="mesh-file", deflection=0.0)
        found, _ = deviation(shape, self.mesh.vertices[self.mesh.faces], self.owner, uv, enough=deflection,
                             mesh_view=self.whole, mesh_to_surface=near)  # fmt: skip
        self.error = found + 1e-6
        self._views: dict[tuple[int, ...], MeshView | None] = {}

    def distance(
        self, points: Array, face_indices: Sequence[int] | None = None
    ) -> Array:
        if face_indices is None:
            return self.whole.distance(points)
        key = tuple(sorted(face_indices))
        if key not in self._views:
            keep = np.isin(self.owner, key)
            if not keep.any():
                self._views[key] = None
            else:
                used = self.mesh.faces[keep]
                corners, inverse = np.unique(used.ravel(), return_inverse=True)
                piece = Mesh(
                    self.mesh.vertices[corners], inverse.reshape(-1, 3).astype(np.int64)
                )
                self._views[key] = MeshView(piece, source="mesh-file", deflection=0.0)
        view = self._views[key]
        if view is None:
            return np.full(len(points), np.inf)
        return view.distance(points)


# --- the test -------------------------------------------------------------------------


def agree(document: DocumentV2, component: str, *, exact: BuildResult | None = None,
          delta: float = DELTA, resolution: int = 96) -> AgreementReport:  # fmt: skip
    """Hold the implicit kernel's part to the exact one."""
    exact = exact if exact is not None else OccBackend().build(document, component)
    v1_component = document.down_converted().component(component)
    v1_products = compile_products(v1_component)
    implicit_part = Compiler().compile_component(v1_component)
    implicit = ImplicitView(implicit_part.solid, resolution=resolution)
    measured = _measured(document, component, exact, v1_products)
    found_entries = entries(document, component, measured=measured, v1=v1_products)
    view = BrepView(exact.shape)
    names = exact.names
    notes: list[str] = []

    # δ: at least five times how far the implicit kernel's own surface points stray from its field's zero.
    surface_points, surface_normals = implicit.surface()
    straying = (
        float(np.abs(implicit.field(surface_points)).max())
        if len(surface_points)
        else 0.0
    )
    delta = max(delta, 5.0 * straying)

    meshed = _Meshed(exact.shape, delta / 4.0)
    try:
        view.accelerate(meshed.whole, meshed.error)
    except ValueError:
        notes.append(
            "the exact part's fine mesh isn't sound: every side is read by the exact methods alone"
        )
    groups = {e: _faces_named(names, e.faces) for e in found_entries}
    bounded = [e for e in found_entries if e.applicable]
    zones = [e for e in found_entries if not e.applicable]

    box = view.bounds()
    size = float(max(box.size))

    def tau_at(points: Array) -> Array:
        """Each point's τ: the largest of the bounded entries whose faces are within reach of it."""
        tau: Array = np.full(len(points), TAU)
        for e in bounded:
            if not groups[e]:
                continue
            reach = e.near if e.near is not None else e.tau + delta
            near = meshed.distance(points, groups[e]) - meshed.error <= reach
            tau = np.where(near, np.maximum(tau, e.tau), tau)
        return tau

    def in_zone(points: Array) -> NDArray[np.bool_]:
        out = np.zeros(len(points), dtype=bool)
        for e in zones:
            assert e.zone is not None
            if e.apart:
                within = []
                for operand in e.apart:
                    idx = _faces_named(names, operand)
                    if idx:
                        within.append(
                            meshed.distance(points, idx) - meshed.error <= e.zone
                        )
                if len(within) >= 2:
                    out |= np.sum(within, axis=0) >= 2
                continue
            if groups[e]:
                out |= meshed.distance(points, groups[e]) - meshed.error <= e.zone
        return out

    # 1. The points.
    area = sum(surface_area(f) for f in faces(exact.shape))
    radius = max(math.sqrt(area / _SURFACE_POINTS) / 0.6, size / 400.0)
    cover = view.coverage(radius)
    rng = fv.Draws(0)
    cover_points, cover_normals = cover.points, cover.normals
    if (
        len(cover_points) > _SURFACE_POINTS
    ):  # B-spline faces' speed bounds are loose: many more than asked
        chosen = np.sort(rng.choice(len(cover_points), _SURFACE_POINTS, replace=False))
        cover_points, cover_normals = cover_points[chosen], cover_normals[chosen]
    if len(surface_points) > _SURFACE_POINTS:
        chosen = rng.choice(len(surface_points), _SURFACE_POINTS, replace=False)
        surface_points, surface_normals = (
            surface_points[np.sort(chosen)],
            surface_normals[np.sort(chosen)],
        )
    tau_a = tau_at(cover_points)
    step_a = (tau_a + delta)[:, None] * cover_normals
    tau_b = tau_at(surface_points) if len(surface_points) else np.zeros(0)
    step_b = (
        (tau_b + delta)[:, None] * surface_normals
        if len(surface_points)
        else np.zeros((0, 3))
    )
    lo = np.minimum(np.asarray(box.lo), implicit.bounds().lo) - 0.05 * size
    hi = np.maximum(np.asarray(box.hi), implicit.bounds().hi) + 0.05 * size
    axes = [np.linspace(lo[i], hi[i], _GRID) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    points = np.concatenate([cover_points + step_a, cover_points - step_a, surface_points + step_b,
                             surface_points - step_b, grid])  # fmt: skip
    points = points + fv.normal(rng, scale=_JITTER * delta, size=points.shape)
    source = np.array(["exact surface"] * (2 * len(cover_points)) + ["implicit surface"] * (2 * len(surface_points))
                      + ["grid"] * len(grid))  # fmt: skip
    tau = np.concatenate([tau_a, tau_a, tau_b, tau_b, tau_at(grid)])

    # 2. Kept: far enough from the exact surface, and in no zone.
    zoned = in_zone(points)
    gap = meshed.distance(points)
    need = tau + delta / 2.0
    far = gap - meshed.error >= need
    unsure = ~far & (gap + meshed.error >= need) & ~zoned
    if unsure.any():
        exact_gap = view.distance(points[unsure])
        far[np.flatnonzero(unsure)] = exact_gap >= need[unsure]
    kept = far & ~zoned
    compared = int(kept.sum())

    # 3. The same side in both.
    where = points[kept]
    theirs = implicit.classify(where)
    ours = view.classify(where)
    wrong = np.flatnonzero(
        (ours != theirs) | (ours == Side.UNKNOWN) | (ours == Side.ON)
    )
    shown = []
    for k in wrong[:_REPORTED]:
        p = where[k]
        near_steps, why = _near(p, found_entries, groups, meshed, names, size)
        shown.append(Disagreement((float(p[0]), float(p[1]), float(p[2])), Side(int(ours[k])).name, Side(int(theirs[k])).name,
                                  near_steps, why, str(source[kept][k])))  # fmt: skip

    # 4. Volume.
    exact_volume = view.volume()
    implicit_volume = implicit.volume()
    face_areas = [surface_area(f) for f in faces(exact.shape)]
    widen = TAU * sum(face_areas)
    for e in found_entries:
        area = sum(face_areas[k] for k in groups[e])
        widen += area * (e.tau if e.applicable else 2.0 * float(e.zone or 0.0))
    volume_holds = (
        implicit_volume.lo - widen <= exact_volume.lo
        and exact_volume.hi <= implicit_volume.hi + widen
    )
    volume = {"exact": [exact_volume.lo, exact_volume.hi], "implicit": [implicit_volume.lo, implicit_volume.hi],
              "widened_by": widen, "holds": bool(volume_holds)}  # fmt: skip

    # 5. Names.
    published = exact.published(document.component(component))
    missing: list[str] = []
    mismatched: list[str] = []
    excused: list[str] = []
    for entity in implicit_part.geometry_map:
        if not entity.entity_type.endswith("_face") or entity.status.value != "live":
            continue
        found = published.get(entity.name)
        if not found:
            excuse = (_lost_fairly(entity, document, component, exact, implicit_part.solid, view)
                      or _gone_inside(entity, document, component, exact, implicit_part.solid, view)
                      or _blended_away(entity, exact, zones, implicit_part.solid, meshed))  # fmt: skip
            if excuse is None:
                missing.append(entity.name)
            else:
                excused.append(f"{entity.name}: {excuse}")
            continue
        # A bent cylinder is no cylinder (V1 carries the entity through its warps): its name is all there is to hold.
        if (
            entity.entity_type == "cylindrical_face"
            and "radius" in entity.dimensions
            and not entity.warps
        ):
            facts = face_facts(TopoDS.Face(found[0]))
            if facts.kind != "cylinder":
                mismatched.append(f"{entity.name}: a {facts.kind}, not a cylinder")
                continue
            reach = max(
                [
                    e.tau
                    for e in bounded
                    if any(k in groups[e] for k in _indices(names, found))
                ],
                default=TAU,
            )
            radius = facts.surface[6]
            axis = np.asarray(facts.surface[3:6])
            theirs_axis = np.asarray(entity.frame.z_axis, dtype=np.float64)
            tilt = float(fv.norm(np.cross(axis, theirs_axis / fv.norm(theirs_axis))))
            foot = np.asarray(facts.surface[:3])
            rel = np.asarray(entity.frame.origin, dtype=np.float64) - foot
            apart = float(fv.norm(rel - (fv.matmul(rel, axis)) * axis))
            if (
                abs(radius - float(entity.dimensions["radius"])) > reach + 1e-9
                or apart > reach + 1e-9
                or tilt > 1e-9
            ):
                mismatched.append(f"{entity.name}: radius {radius:.6g} against {entity.dimensions['radius']:.6g}, "
                                  f"axes {apart:.2e} mm apart, {tilt:.1e} rad")  # fmt: skip
    names_report = {"missing": missing, "mismatched": mismatched, "excused": excused,
                    "holds": not missing and not mismatched}  # fmt: skip

    # 6. Topology.
    ours_topology = view.topology()
    try:
        theirs_topology = implicit.topology()
    except Exception as error:
        # The implicit mesh can't be had: topology isn't compared.
        theirs_topology = None
        notes.append(f"the implicit kernel's mesh could not be made: {error!r}")
    # A mesh as coarse as a feature closes a hole: where it is sound but the counts differ, it is made again
    # finer, and the finest made is the one compared. One that isn't sound is not made again: finer, it stays
    # so (a cone's apex), and the extraction's memory grows past bounds (more than 4 GB at 192 cells for a cone
    # on a plate, against 0.25 GB for generated part 190's block).
    finest = implicit
    for finer in FINER:
        if (
            theirs_topology is None
            or not theirs_topology.sound
            or (ours_topology.solids, ours_topology.voids, ours_topology.genus)
            == (theirs_topology.solids, theirs_topology.voids, theirs_topology.genus)
        ):
            break
        try:
            made = ImplicitView(implicit_part.solid, resolution=finer)
            theirs_topology = made.topology()
            finest = made
        except (MemoryError, ValueError, RuntimeError) as error:
            notes.append(
                f"the implicit kernel's mesh could not be made at {finer} cells: {error!r}"
            )
            break
        notes.append(f"the implicit kernel's mesh made again at {finer} cells across")
    # Solids of the exact part that only touch (along edges or at points: rods standing on a pole's surface
    # at a tangent) are as many solids to it and one to the implicit kernel, whose mesh can't tell a contact of
    # no width from a join; the build's trace says how they meet.
    touching = (
        ours_topology.solids is None
        and len(solids(exact.shape)) > 1
        and ours_topology.bad_edges + ours_topology.bad_vertices > 0
        and ours_topology.open_edges == 0
        and ours_topology.self_intersections == 0
    )
    counted = (
        not zones
        and not touching
        and theirs_topology is not None
        and theirs_topology.sound
    )
    same = theirs_topology is not None and (ours_topology.solids, ours_topology.voids, ours_topology.genus) == (
        theirs_topology.solids, theirs_topology.voids, theirs_topology.genus)  # fmt: skip
    # Counts that differ at the finest mesh made may be the mesh's: where the exact part has a wall or a gap
    # narrower than about two of its cells (generated part 9530: four holes 0.118 mm from a pocket's side, in
    # cells of 0.42 mm, and each wall lost: genus 8 for 4), the grid steps over it.
    thin: tuple[float, float] | None = None
    if counted and not same:
        thin = (_thinnest(view, _cell(finest)), _cell(finest))
        if thin[0] < _RESOLVED * thin[1]:
            counted = False
    topology = {
        "exact": {"solids": ours_topology.solids, "voids": ours_topology.voids, "genus": list(ours_topology.genus)},
        "implicit": None if theirs_topology is None else {
            "solids": theirs_topology.solids, "voids": theirs_topology.voids, "genus": list(theirs_topology.genus),
            "sound": theirs_topology.sound},
        "counted": counted, "holds": bool(same or not counted),
        "thinnest": None if thin is None else {"across": thin[0], "cell": thin[1]},
    }  # fmt: skip
    if not counted:
        reason = ("a not-applicable zone is on the part" if zones
                  else "the exact part's solids only touch, along edges or at points" if touching
                  else "the implicit kernel's mesh isn't sound" if theirs_topology is None or not theirs_topology.sound
                  else f"the exact part has a wall or a gap {thin[0]:.3g} mm across, under {_RESOLVED:g} of the "
                       f"implicit mesh's cells ({thin[1]:.3g} mm)" if thin is not None
                  else "")  # fmt: skip
        notes.append(f"topology reported, not counted: {reason}")
    return AgreementReport(
        component, delta, compared, int(zoned.sum()), int((~far & ~zoned).sum()), len(wrong), tuple(shown),
        volume, names_report, topology, found_entries, tuple(notes),
    )  # fmt: skip


def _cell(made: ImplicitView) -> float:
    """About how far apart the implicit mesh's grid points are: the median length of its triangles' edges (each joins two cells' vertices)."""
    mesh = made.mesh_view.mesh
    corners = mesh.vertices[mesh.faces]
    edges = fv.norm(corners - np.roll(corners, 1, axis=1), axis=2)
    return float(np.median(edges)) if edges.size else 0.0


def _thinnest(view: BrepView, cell: float) -> float:
    """The exact part's thinnest wall or narrowest gap: along the normal at each point of its surface (``cell`` apart), inward to where the material ends and outward to where it begins again, where the face found there faces back (:data:`_ACROSS`).

    A point is moved a nanometre off its face first, the side it measures, so
    its own face is never what it finds.
    """
    cover = view.coverage(max(cell, 1e-3))
    points, normals = cover.points, cover.normals
    if len(points) > _THIN_POINTS:
        chosen = fv.Draws(0).choice(len(points), _THIN_POINTS, replace=False)
        points, normals = points[np.sort(chosen)], normals[np.sort(chosen)]
    off = 1e-6
    found = math.inf
    for way in (-1.0, 1.0):  # inward: a wall; outward: a gap
        far, there = view.first_hits(points + way * off * normals, way * normals)
        back = fv.dot(np.nan_to_num(there), normals) < -_ACROSS
        if back.any():
            found = min(found, float(far[back].min()) + off)
    return found


#: The operations after which a step's own product is no longer where its faces are on the part.
_MOVES = frozenset({"transform", "bend", "mirror"})


def _moved_after(steps: Sequence[Any], owner: str) -> bool:
    """Whether a step after ``owner`` moves what ``owner`` made: a move whose input is made from its product.

    A move of another solid only (a turned tab's stadium, turned on its own
    before it is kept and joined: V2-stage4b-0c.md 3.3, 1b's first move)
    leaves the faces ``owner`` made where it made them.
    """
    inputs = {step.id: tuple(step.inputs) for step in steps}
    made_from: dict[str, bool] = {}

    def from_owner(step: str) -> bool:
        if step == owner:
            return True
        if step not in made_from:
            made_from[step] = False  # no step is made from itself: a guard on the walk alone
            made_from[step] = any(from_owner(i) for i in inputs.get(step, ()))
        return made_from[step]

    after = False
    for step in steps:
        if step.id == owner:
            after = True
        elif after and step.op in _MOVES and from_owner(step.id):
            return True
    return False


def _lost_fairly(entity: Any, document: DocumentV2, component: str, exact: BuildResult, solid: Any,
                 view: BrepView) -> str | None:  # fmt: skip
    """Why a face V1 finds on its part has no face of the exact part named for it, when that is right; None when it isn't.

    V1 finds a face by samples on its analytic patch (a planar face is the
    box round it), so where the patch reaches past the face onto another
    face of the part, V1 finds it though the face itself is gone: a hub's
    base on its flange, the patch's corners on the flange's top. It is right
    when none of V1's samples on its boundary lies on the face the exact
    kernel's step made (as that step made it) and on the exact part too.
    Undecided (None) when what the step made was moved after it.
    """
    steps = document.steps(component)
    owner = entity.owning_feature
    if _moved_after(steps, owner):
        return None
    product = exact.products.get(owner)
    suffix = entity.name.split(".")[-1]
    if not isinstance(product, SolidProduct):
        return None
    made = product.names.faces_named(owner, suffix)
    if not made:
        return None
    candidates, reach = _on_v1(entity, solid)
    if not len(candidates):
        return None
    from_face = distances_to(candidates, compound(made))
    on_face = candidates[from_face <= reach]
    if len(on_face) and (view.distance(on_face) <= reach).any():
        return None
    return ("V1 finds it only where its patch reaches other faces of the part; the face itself is inside the "
            "part or gone")  # fmt: skip


#: Points a side of the grid a face's inside is first sampled on (in its parameters).
_INSIDE_GRID = 9
#: The most points a side that grid is refined to, where it finds no point well clear of the face's rim.
_INSIDE_GRID_MOST = 129


def _gone_inside(entity: Any, document: DocumentV2, component: str, exact: BuildResult, solid: Any,
                 view: BrepView) -> str | None:  # fmt: skip
    """Why a face V1 finds has no face of the exact part named for it, when the step that lost it was right to; None when it wasn't, or it can't be told.

    A cut's tool's face at its mouth (a hole's end in the plane of the face
    it is cut into) is all air once cut: only its rim, an edge of the hole,
    is on the part; a tab's or a post's foot, joined, is inside the part.
    V1 finds such a face by its patch, which meets the faces round it, or
    lies on a face a later step made in its place (a lid over a pocket's
    mouth: the pocket's ceiling is the lid's foot; a pin's bore through a
    buried foot): the exact kernel rightly names nothing for it. The step
    whose trace says it lost the name was right when the face, as the last
    step that had it left it, taken well clear of its rim, is nowhere on
    that step's part: whatever lies there later is a later step's face.
    Without a trace of the loss, the face must be off the finished part.
    """
    steps = document.steps(component)
    owner = entity.owning_feature
    if _moved_after(steps, owner):
        return None
    # The face as the last step that still has it left it (a tool's face cut down to the tool by the next step),
    # and the first step after that whose trace says it lost the name.
    suffix = entity.name.split(".")[-1]
    made: list[Any] = []
    last = -1
    for k, step in enumerate(steps):
        product = exact.products.get(step.id)
        if isinstance(product, SolidProduct):
            here = product.names.faces_named(owner, suffix)
            if here:
                made, last = here, k
    if not made:
        return None
    losing = {t.step: t for t in exact.traces if entity.name in t.lost}
    lost_at = next((s.id for s in steps[last + 1 :] if s.id in losing), None)
    reach = max(float(solid.envelope.diagonal) * 1e-3, 1e-6)
    clear = _clear_inside(made, 2 * reach)
    if not len(clear):
        return None
    if lost_at is None:
        if (view.distance(clear) <= reach).any():
            return None
        return "its inside is off the exact part everywhere (a tool's face in the air, its rim an edge of the part)"
    there = exact.products.get(lost_at)
    if (
        not isinstance(there, SolidProduct)
        or (distances_to(clear, there.shape) <= reach).any()
    ):
        return None
    return (f"step {lost_at} lost it rightly: its inside is nowhere on that step's part (in the air or inside it, "
            "its rim an edge); any face there now is a later step's")  # fmt: skip


def _clear_inside(made: Sequence[Any], margin: float) -> Array:
    """Points of the faces' insides farther than ``margin`` from their rims, on a grid in each face's parameters.

    The grid starts at :data:`_INSIDE_GRID` points a side and is refined
    (17, 33, ... up to :data:`_INSIDE_GRID_MOST`) while it finds none: a
    face that is a thin strip has no grid point well clear of its rim on a
    coarse grid (generated part 6820: an extrusion's L-shaped foot, its legs
    0.49 mm wide, sampled 0.35 mm apart across them). None found at the
    finest grid is an empty array.
    """
    from .uvclass import on_grid

    rims = compound([e for f in made for e in edges(f)])
    count = _INSIDE_GRID
    while True:
        inside: list[Array] = []
        for face in made:
            face = TopoDS.Face(face)
            surface = BRepAdaptor_Surface(face, False)
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
            us, vs = np.linspace(u0, u1, count), np.linspace(v0, v1, count)
            p = gp_Pnt()
            for i, j in np.argwhere(on_grid(face, us, vs)):
                surface.D0(float(us[i]), float(vs[j]), p)
                inside.append(np.array([p.X(), p.Y(), p.Z()]))
        if inside:
            points = np.array(inside)
            clear = points[_edge_distances(points, rims) > margin]
            if len(clear):
                return clear
        if count >= _INSIDE_GRID_MOST:
            return np.zeros((0, 3))
        count = 2 * count - 1


def _edge_distances(points: Array, shape: Any) -> Array:
    """Each point's distance to the edges of ``shape``."""
    found = np.empty(len(points))
    meter = BRepExtrema_DistShapeShape()
    meter.LoadS2(shape)
    for k, point in enumerate(points):
        meter.LoadS1(BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex())
        meter.Perform()
        found[k] = meter.Value() if meter.IsDone() else 0.0
    return found


def _on_v1(entity: Any, solid: Any) -> tuple[Array, float]:
    """V1's samples of an entity that lie on V1's surface (its field changes sign beside them), and how near "beside" is."""
    samples = np.asarray(entity.sample_points(), dtype=np.float64).reshape(-1, 3)
    reach = max(float(solid.envelope.diagonal) * 1e-3, 1e-6)
    if not len(samples):
        return samples, reach
    probes = np.vstack([np.eye(3), -np.eye(3)]) * reach
    field_near = np.asarray(
        solid((samples[:, None, :] + probes[None, :, :]).reshape(-1, 3))
    ).reshape(len(samples), 6)
    on_v1 = (field_near < 0.0).any(axis=1) & (field_near > 0.0).any(axis=1)
    return samples[on_v1], reach


def _blended_away(
    entity: Any, exact: BuildResult, zones: Sequence[Entry], solid: Any, meshed: _Meshed
) -> str | None:
    """Why a face V1 finds has no face of the exact part named for it, when a blend rounded it away; None otherwise.

    Right when a step whose blend is a not-applicable zone (13.3) buried the
    name (its trace says so), and every one of V1's samples on its surface
    lies within that zone of the blend's faces: the face was wholly inside
    where the two kernels' blends differ by design, so neither is held to
    the other there (a boss standing as far above a plate as its root blend
    is wide: the blend covers its side).
    """
    candidates, _ = _on_v1(entity, solid)
    if not len(candidates):
        return None
    names = exact.names
    for trace in exact.traces:
        if entity.name not in trace.lost:
            continue
        for entry in zones:
            if entry.step != trace.step or entry.zone is None:
                continue
            blends = [k for k, held in enumerate(names.table)
                      if any(n.step == trace.step and n.role in ("round", "bevel") for n in held)]  # fmt: skip
            if blends and bool(
                (meshed.distance(candidates, blends) - meshed.error <= entry.zone).all()
            ):
                return (f"step {trace.step}'s blend rounded it away, wholly inside the zone where the kernels' "
                        "blends aren't compared")  # fmt: skip
    return None


def _indices(names: Names, found: Sequence[Any]) -> list[int]:
    all_faces = faces(names.shape)
    return [k for k, f in enumerate(all_faces) if any(f.IsSame(g) for g in found)]


def _near(point: Array, found_entries: Sequence[Entry], groups: Mapping[Entry, list[int]], meshed: _Meshed,
          names: Names, size: float) -> tuple[tuple[str, ...], tuple[str, ...]]:  # fmt: skip
    """The steps whose faces are near a point (within a hundredth of the part's size), and their entries."""
    p = point[None, :]
    steps: set[str] = set()
    reach = max(size / 100.0, 1.0)
    for k, held in enumerate(names.table):
        if meshed.distance(p, [k])[0] <= reach:
            steps.update(n.step for n in held)
    why = tuple(e.why for e in found_entries if e.step in steps)
    return tuple(sorted(steps)), why
