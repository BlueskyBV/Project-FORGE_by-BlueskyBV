"""Assemblies: a document's parts built, its instances placed, and its mates held (docs/V2-stage3.md, 6.1 and 16).

An interface names a semantic output its component's features publish
(``pivot.bore``); on the built part that is the faces the name carries
(``BuildResult.published``). A placed interface is those faces' surface in
the assembly: one cylinder (its axis and radius) or one plane (its outward
normal and place), or the document is refused.

| Mate | Holds when |
|---|---|
| ``coaxial`` | the two cylinders' axes are one line: parallel within 1e-9 rad, and within 1e-6 mm of each other |
| ``contact`` | the two planes face each other (outward normals opposite, within 1e-9 rad), the second ``gap`` from the first along its normal (0 by default) to 1e-6 mm, and the faces overlap there |
| ``fixed`` | both interfaces are found: the placements are the mate |

The same check runs on an assembly read back from STEP, where faces carry no
names: each interface's faces are found again by their geometry (kind,
surface, area and box, to 1e-6).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from forge_checks.view import FaceFacts
from forge_ir.v2 import DocumentV2, Mate
from forge_units import parse_unit
from numpy.typing import NDArray
from OCP.TopoDS import TopoDS

from .backend import BuildResult, OccBackend
from .cache import StepCache
from .errors import DesignError
from .export import StepFile, StepInstance, StepPart
from .geom import Motion
from .make import boolean, compound
from .occt import faces, surface_area
from .view import face_facts

__all__ = [
    "ANGLE", "DISTANCE", "BuiltAssembly", "MateCheck", "PlacedInstance", "Surface", "build_assembly", "check_mate",
    "check_mates", "check_mates_read_back", "found_again", "surface_of",
]  # fmt: skip

Array = NDArray[np.float64]

#: How closely a mate must hold: directions within this angle (rad), lines and planes within this distance (mm).
ANGLE = 1e-9
DISTANCE = 1e-6
#: How closely a face found again in a file must match the face written (relative to the part's size, and to its area).
FOUND_AGAIN = 1e-6


@dataclass(frozen=True)
class Surface:
    """A placed interface's surface: a cylinder (``point`` on its axis, ``direction`` the axis) or a plane (``point`` on it, ``direction`` its outward normal)."""

    kind: str
    point: Array
    direction: Array
    radius: float | None
    faces: tuple[Any, ...]


@dataclass(frozen=True)
class MateCheck:
    mate: str
    kind: str
    holds: bool
    found: Mapping[str, float]
    why: str


@dataclass(frozen=True)
class PlacedInstance:
    id: str
    component: str
    motion: Motion


@dataclass(frozen=True)
class BuiltAssembly:
    """A document's parts, built once each; its instances, placed; its mates, checked."""

    name: str
    parts: Mapping[str, BuildResult]
    instances: tuple[PlacedInstance, ...]
    mates: tuple[MateCheck, ...]

    @property
    def holds(self) -> bool:
        return all(m.holds for m in self.mates)

    def step_parts(self) -> list[StepPart]:
        return [
            StepPart(component, result.shape)
            for component, result in self.parts.items()
        ]

    def step_instances(self) -> list[StepInstance]:
        return [StepInstance(i.id, i.component, i.motion) for i in self.instances]


def _motion(placement: Any) -> Motion:
    rows, translation = placement.resolve()
    return Motion.of(np.asarray(rows, dtype=np.float64), translation)


def build_assembly(document: DocumentV2, *, backend: OccBackend | None = None,
                   cache: StepCache | None = None) -> BuiltAssembly:  # fmt: skip
    """Every component the document's instances use, built; each instance placed; each mate checked."""
    if not document.instances:
        raise DesignError("the document places no instances: it is no assembly")
    builder = backend or OccBackend()
    parts: dict[str, BuildResult] = {}
    for instance in document.instances:
        if instance.component not in parts:
            parts[instance.component] = builder.build(
                document, instance.component, cache=cache
            )
    placed = tuple(
        PlacedInstance(i.id, i.component, _motion(i.at)) for i in document.instances
    )
    surfaces = _named_surfaces(document, parts)
    checks = check_mates(document.mates, {i.id: i for i in placed}, surfaces)
    return BuiltAssembly(
        document.base.name or document.base.document_id, parts, placed, checks
    )


def _named_surfaces(
    document: DocumentV2, parts: Mapping[str, BuildResult]
) -> dict[tuple[str, str], list[Any]]:
    """Each (component, interface)'s faces on its built part, in the part's own coordinates."""
    out: dict[tuple[str, str], list[Any]] = {}
    for component, result in parts.items():
        definition = document.component(component)
        published = result.published(definition)
        for interface in definition.interfaces:
            found = published.get(interface.geometry)
            if not found:
                raise DesignError("an interface's geometry names no face of the built part", component=component,
                                  interface=interface.identifier, geometry=interface.geometry)  # fmt: skip
            out[(component, interface.identifier)] = found
    return out


def surface_of(face_list: Sequence[Any], motion: Motion, where: str) -> Surface:
    """The one cylinder or plane the faces lie on, placed by ``motion``."""
    facts = [face_facts(TopoDS.Face(f)) for f in face_list]
    kinds = {f.kind for f in facts}
    if kinds == {"cylinder"}:
        first = np.asarray(facts[0].surface)
        for other in facts[1:]:
            o = np.asarray(other.surface)
            if not (_parallel(first[3:6], o[3:6]) and _line_gap(first[:3], first[3:6], o[:3]) <= DISTANCE
                    and abs(o[6] - first[6]) <= DISTANCE):  # fmt: skip
                raise DesignError(f"{where}'s faces don't lie on one cylinder")
        point, axis = motion.point(first[:3]), motion.direction(first[3:6])
        return Surface(
            "cylinder",
            point,
            axis / np.linalg.norm(axis),
            float(first[6]),
            _placed(face_list, motion),
        )
    if kinds == {"plane"}:
        first = np.asarray(facts[0].surface)
        for other in facts[1:]:
            o = np.asarray(other.surface)
            if not (
                _parallel(first[:3], o[:3], same_way=True)
                and abs(o[3] - first[3]) <= DISTANCE
            ):
                raise DesignError(f"{where}'s faces don't lie on one plane")
        normal = first[:3]
        point = normal * first[3]
        n = motion.direction(normal)
        return Surface(
            "plane",
            motion.point(point),
            n / np.linalg.norm(n),
            None,
            _placed(face_list, motion),
        )
    raise DesignError(
        f"{where} is neither one cylinder nor one plane", kinds=sorted(kinds)
    )


def _placed(face_list: Sequence[Any], motion: Motion) -> tuple[Any, ...]:
    return tuple(faces(motion.apply(compound(face_list))))


def _parallel(a: Array, b: Array, *, same_way: bool = False) -> bool:
    a, b = np.asarray(a) / np.linalg.norm(a), np.asarray(b) / np.linalg.norm(b)
    angle = math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a @ b))
    return angle <= ANGLE if same_way else min(angle, math.pi - angle) <= ANGLE


def _line_gap(point: Array, direction: Array, other: Array) -> float:
    """How far ``other`` is from the line through ``point`` along ``direction``."""
    d = np.asarray(direction) / np.linalg.norm(direction)
    rel = np.asarray(other) - np.asarray(point)
    return float(np.linalg.norm(rel - (rel @ d) * d))


def _angle(a: Array, b: Array) -> float:
    return math.atan2(
        float(np.linalg.norm(np.cross(a, b))), float(np.asarray(a) @ np.asarray(b))
    )


def check_mate(mate: Mate, a: Surface, b: Surface) -> MateCheck:
    """Whether ``mate`` holds between the placed surfaces ``a`` and ``b``."""
    if mate.kind == "fixed":
        return MateCheck(
            mate.id,
            mate.kind,
            True,
            {},
            "both interfaces found; the placements are the mate",
        )
    if mate.kind == "coaxial":
        if a.kind != "cylinder" or b.kind != "cylinder":
            return MateCheck(
                mate.id, mate.kind, False, {}, "a coaxial mate relates two cylinders"
            )
        tilt = _angle(a.direction, b.direction)
        tilt = min(tilt, math.pi - tilt)
        apart = max(
            _line_gap(a.point, a.direction, b.point),
            _line_gap(b.point, b.direction, a.point),
        )
        holds = tilt <= ANGLE and apart <= DISTANCE
        return MateCheck(mate.id, mate.kind, holds, {"tilt": tilt, "apart": apart},
                         "the axes are one line" if holds else "the axes are not one line")  # fmt: skip
    if a.kind != "plane" or b.kind != "plane":
        return MateCheck(
            mate.id, mate.kind, False, {}, "a contact mate relates two planes"
        )
    gap = (
        float(mate.gap.resolve(None).to(parse_unit("mm")).magnitude.midpoint)
        if mate.gap is not None
        else 0.0
    )
    facing = math.pi - _angle(a.direction, b.direction)
    found_gap = float((b.point - a.point) @ a.direction)
    overlap = _overlap(a, b, found_gap)
    holds = facing <= ANGLE and abs(found_gap - gap) <= DISTANCE and overlap > 0.0
    found = {"facing": facing, "gap": found_gap, "overlap": overlap}
    if holds:
        why = (
            "the faces meet, facing each other"
            if not gap
            else f"the faces face each other {gap:g} mm apart"
        )
    elif facing > ANGLE:
        why = "the faces don't face each other"
    elif abs(found_gap - gap) > DISTANCE:
        why = f"the faces are {found_gap:g} mm apart, not {gap:g}"
    else:
        why = "the faces don't overlap"
    return MateCheck(mate.id, mate.kind, holds, found, why)


def _overlap(a: Surface, b: Surface, gap: float) -> float:
    """The area where ``b``'s faces, brought ``gap`` back along ``a``'s normal, cover ``a``'s."""
    back = Motion.of(np.eye(3), -gap * a.direction)
    common = boolean("intersect", [compound(a.faces)], [back.apply(compound(b.faces))])
    return surface_area(common.shape) if faces(common.shape) else 0.0


def check_mates(mates: Sequence[Mate], instances: Mapping[str, PlacedInstance],
                surfaces: Mapping[tuple[str, str], Sequence[Any]]) -> tuple[MateCheck, ...]:  # fmt: skip
    """Each mate checked on the interfaces' faces (in their parts' coordinates), placed by their instances."""
    out = []
    for mate in mates:
        placed = []
        for port in (mate.a, mate.b):
            instance = instances[port.instance]
            found = surfaces.get((instance.component, port.interface))
            if found is None:
                raise DesignError("a mate's interface isn't its instance's component's", mate=mate.id,
                                  instance=port.instance, interface=port.interface)  # fmt: skip
            placed.append(
                surface_of(found, instance.motion, f"{port.instance}.{port.interface}")
            )
        out.append(check_mate(mate, placed[0], placed[1]))
    return tuple(out)


def found_again(
    written: Mapping[tuple[str, str], Sequence[Any]], read: StepFile
) -> dict[tuple[str, str], list[Any]]:
    """Each interface's faces on the parts read back from STEP, found by their geometry.

    A face is found again as the faces read back on its surface and inside
    its box that together have its area and its box: one face, or the two a
    face round a seam was written as (:func:`~forge_occ.export.exchanged`).
    """
    out: dict[tuple[str, str], list[Any]] = {}
    for (component, interface), face_list in written.items():
        shape = read.parts.get(component)
        if shape is None:
            raise DesignError(
                "a part is missing from the file read back", component=component
            )
        candidates = [(f, face_facts(TopoDS.Face(f))) for f in faces(shape)]
        size = (
            max(
                float(np.linalg.norm(np.subtract(c.bounds.hi, c.bounds.lo)))
                for _, c in candidates
            )
            or 1.0
        )
        matched: list[Any] = []
        for face in face_list:
            want = face_facts(TopoDS.Face(face))
            hits = [(f, c) for f, c in candidates if _on_it(want, c, size)]
            if not hits or not _whole(want, [c for _, c in hits], size):
                raise DesignError("an interface's face can't be found again in the file read back", component=component,
                                  interface=interface, matches=len(hits))  # fmt: skip
            matched.extend(f for f, _ in hits)
        out[(component, interface)] = matched
    return out


def _on_it(a: FaceFacts, b: FaceFacts, size: float) -> bool:
    """Whether ``b`` lies on ``a``'s surface, inside ``a``'s box."""
    reach = FOUND_AGAIN * max(size, 1.0)
    if a.kind != b.kind or len(a.surface) != len(b.surface):
        return False
    if np.max(np.abs(np.subtract(a.surface, b.surface)), initial=0.0) > reach:
        return False
    return bool(
        np.all(np.asarray(b.bounds.lo) >= np.asarray(a.bounds.lo) - reach)
        and np.all(np.asarray(b.bounds.hi) <= np.asarray(a.bounds.hi) + reach)
    )


def _whole(a: FaceFacts, pieces: Sequence[FaceFacts], size: float) -> bool:
    """Whether the pieces together have ``a``'s area and its box."""
    reach = FOUND_AGAIN * max(size, 1.0)
    if abs(sum(p.area for p in pieces) - a.area) > FOUND_AGAIN * max(a.area, 1e-12):
        return False
    lo = np.min([p.bounds.lo for p in pieces], axis=0)
    hi = np.max([p.bounds.hi for p in pieces], axis=0)
    corners = np.abs(np.subtract([*lo, *hi], [*a.bounds.lo, *a.bounds.hi]))
    return bool(corners.max() <= reach)


def check_mates_read_back(
    document: DocumentV2, assembly: BuiltAssembly, read: StepFile
) -> tuple[MateCheck, ...]:
    """The document's mates checked on an assembly read back from STEP: its own placements, its faces found again."""
    written = _named_surfaces(document, assembly.parts)
    surfaces = found_again(written, read)
    instances = {
        i.name: PlacedInstance(i.name, i.part, i.motion) for i in read.instances
    }
    return check_mates(document.mates, instances, surfaces)
