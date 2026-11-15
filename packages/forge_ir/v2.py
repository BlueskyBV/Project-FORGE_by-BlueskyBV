"""ForgeIR v2: steps that name the spec items they build, references that are queries, instances and mates.

docs/V2-stage3.md, section 6. ForgeIR v2 keeps everything V1 has, in V1's
forms and with V1's meaning, and adds three things:

- **steps** (V1's features under v2's names: ``op`` for ``kind``, ``params``
  for ``parameters``) that list the spec items they build (``for_items``),
  so a failure names a spec item;
- **references by query** (:class:`EdgeQuery`, :class:`FaceQuery`): faces and
  edges named by the step that made them and the role it gave them, told
  apart by a geometric test, held to a match condition; used by two
  operations new in v2, ``fillet`` and ``chamfer``;
- **outlines with true arcs** (``profile_outline``, new in v2): straight
  sides and circular arcs, each arc to its end through its middle;
- **letters and threads** (``text`` and ``thread``, new in v2): a line of
  letters in the pinned font, engraved or embossed; a rod's side cut into
  the ISO metric thread (docs/V2-stage4.md, section 7);
- **instances** (a component placed by a rigid motion) and **mates** (two
  instances' interfaces related), checked on a built assembly.

**How it is read.** A v2 document is decoded by translating it into V1's
form and handing it to V1's decoder, so every rule V1 enforces (units,
expressions, one starting solid, no hole drilled twice, interfaces naming
published geometry, ...) holds unchanged; the pointers in its errors, and on
its features, are translated back, so they point into the v2 document. A
v2-only step stands in V1's form as an identity ``transform`` of its input,
and an outline as V1's ``profile_sketch`` through points no further than
:data:`OUTLINE_CHORD` from its arcs: which is also what the implicit kernel
builds for it (the down-conversion, :meth:`DocumentV2.down_converted`).

>>> doc = DocumentV2.from_json(EXAMPLE)
>>> [s.op for s in doc.steps("plate")]
['box', 'fillet']
>>> doc.step("plate", "round").references["edges"].match.count
(4, 4)
>>> DocumentV2.from_json(doc.to_json()).to_json() == doc.to_json()
True
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .document import SCHEMA_VERSION, Component, Document, decode_document
from .features import (
    FEATURE_SPECS,
    Feature,
    FeatureGraph,
    FeatureSpec,
    _decode_parameters,
    _o,
    _p,
)
from .schema import (
    DanglingReferenceError,
    DuplicateIdentifierError,
    Reader,
    SchemaError,
    SchemaErrorGroup,
    ValueRangeError,
    join_pointer,
)
from .spec import _parameter_schema, document_schema
from .values import (
    IRValue,
    QuantityValue,
    ScalarValue,
    VectorValue,
    decode_points,
    decode_scalar,
    decode_vector,
)

__all__ = [
    "EXAMPLE",
    "MATE_KINDS",
    "OPS",
    "OUTLINE_CHORD",
    "SCHEMA_VERSION_V2",
    "V2_ONLY",
    "DocumentV2",
    "EdgeQueries",
    "EdgeQuery",
    "FaceQuery",
    "Instance",
    "Match",
    "Mate",
    "Placement",
    "Port",
    "Reference",
    "Step",
    "Where",
    "convert_v1",
    "document_schema_v2",
    "write_schema_v2",
]

SCHEMA_VERSION_V2 = "2.0.0"

#: The operations v2 adds to V1's 32 kinds: their parameters, and which of them are references.
V2_ONLY: Mapping[str, FeatureSpec] = {
    "fillet": FeatureSpec(
        kind="fillet",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p(
                "radius",
                "length",
                minimum=0.0,
                description="The radius every edge chosen is rounded to",
            ),
        ),
        emits=(_o("body", "volume"),),
        summary="Round the edges a reference chooses.",
    ),
    "chamfer": FeatureSpec(
        kind="chamfer",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p(
                "distance",
                "length",
                minimum=0.0,
                description="How far back along each face every edge chosen is cut",
            ),
        ),
        emits=(_o("body", "volume"),),
        summary="Bevel the edges a reference chooses, equally on both faces.",
    ),
    "profile_outline": FeatureSpec(
        kind="profile_outline",
        produces="profile",
        inputs=("datum_plane",),
        parameters=(
            _p(
                "points",
                "points",
                description="The outline in the plane's own u, v: where it starts, then where each side "
                "ends, in turn, the last back at the start. A side given as [u, v] is straight; one "
                "given as [u, v, mu, mv] is the circular arc to (u, v) through (mu, mv), its middle",
            ),
        ),
        emits=(_o("region", "volume", "The enclosed 2D region"),),
        summary="An outline of straight sides and true circular arcs.",
    ),
    "text": FeatureSpec(
        kind="text",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("height", "length", minimum=0.0,
               description="How tall a capital is: the pinned font scaled so its letter H is this tall"),
            _p("origin", "displacement",
               description="The middle of the line's box (first letter's start to last advance, baseline to "
               "capital height), on the face"),
            _p("up", "direction", description="The way up the letters, in the face's plane"),
            _p("right", "direction", description="The way the line runs, in the face's plane"),
            _p("depth", "length", minimum=0.0,
               description="How deep the letters go into the face, or how high they stand out of it"),
            _p("mode", "enum", options=("engrave", "emboss"),
               description="Cut into the part, or standing out of it"),
        ),
        emits=(_o("body", "volume"),),
        summary="A line of letters in the pinned font, engraved into a face or embossed on it.",
    ),
    "thread": FeatureSpec(
        kind="thread",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("axis_origin", "displacement", description="A point on the rod's axis"),
            _p("axis", "direction", description="The rod's axis, from its start towards its end"),
            _p("major_diameter", "length", minimum=0.0, description="The thread's major diameter"),
            _p("pitch", "length", minimum=0.0, description="How far the thread advances in one turn"),
            _p("hand", "enum", options=("right", "left"), description="Which way the thread turns"),
            _p("length", "length", minimum=0.0, description="How far it runs from the rod's free end"),
            _p("rod_start", "length", description="Where the rod starts, along the axis from its origin"),
            _p("rod_end", "length", description="Where the rod ends, its free end, along the axis from its origin"),
        ),
        emits=(_o("body", "volume"),),
        summary="A rod's round side cut into the ISO 68-1 basic thread profile over a length from its free end.",
    ),
}  # fmt: skip
_REFERENCES: Mapping[str, tuple[str, ...]] = {
    "fillet": ("edges",),
    "chamfer": ("edges",),
    "profile_outline": (),
    "text": (),
    "thread": (),
}
#: The parameters of a v2-only operation that are words: written as a string, not a value.
_STRINGS: Mapping[str, tuple[str, ...]] = {"text": ("text",)}
#: What a v2-only operation is in V1's form (else an identity ``transform`` of its input).
_V1_FORMS: Mapping[str, str] = {"profile_outline": "profile_sketch"}
#: How far the polygon a ``profile_outline`` is down-converted to strays from its arcs (mm).
OUTLINE_CHORD = 0.005

#: Every operation a v2 step may be.
OPS: tuple[str, ...] = tuple(sorted({*FEATURE_SPECS, *V2_ONLY}))

MATE_KINDS = ("coaxial", "contact", "fixed")
#: The interface types each kind of mate relates.
_MATE_PORTS: Mapping[str, frozenset[str]] = {
    "coaxial": frozenset({"bore", "shaft", "gear_pitch_surface"}),
    "contact": frozenset({"planar_mount"}),
}

_STEP_FIELDS = (
    "id",
    "op",
    "inputs",
    "params",
    "role",
    "tags",
    "description",
    "for_items",
)
_COMPONENT_FIELDS = (
    "id",
    "name",
    "parameters",
    "steps",
    "interfaces",
    "material",
    "description",
)
_DOCUMENT_FIELDS = (
    "schema_version", "document_id", "project_id", "revision", "name", "units",
    "components", "requirements", "assumptions", "provenance", "risk_class",
    "parent_revision_id", "description", "instances", "mates",
)  # fmt: skip

#: The geometric tests a query may make.
_KINDS = ("plane", "cylinder", "cone", "sphere", "torus", "line", "circle")
_SIDES = tuple(f"{e}_{a}" for e in ("min", "max") for a in "xyz")
_COVERS = ("full_circle", "whole")


# --- references ------------------------------------------------------------------------


Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Where:
    """A geometric test that tells pieces apart (lengths in mm, to 1e-6 mm and 1e-9 rad).

    ``centre`` is a circle's or a sphere's centre. ``within`` is the box a
    piece must lie inside: an edge's extent, the segment or arc the spec's
    edge is. Unlike the other tests it never quietly drops a piece: a piece
    that passes every other test and lies partly outside it is an error
    (it runs on past the edge the reference means, onto another item's).
    """

    kind: str | None = None
    axis: Vec3 | None = None
    normal: Vec3 | None = None
    radius_mm: float | None = None
    through: Vec3 | None = None
    side: str | None = None
    centre: Vec3 | None = None
    within: tuple[Vec3, Vec3] | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in ("kind", "radius_mm", "side"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        for name in ("axis", "normal", "through", "centre"):
            if getattr(self, name) is not None:
                out[name] = list(getattr(self, name))
        if self.within is not None:
            out["within"] = [list(self.within[0]), list(self.within[1])]
        return out


@dataclass(frozen=True)
class Match:
    """How many pieces the query must find, and what they must cover together."""

    count: tuple[int, int]
    covers: str | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"count": list(self.count)}
        if self.covers is not None:
            out["covers"] = self.covers
        return out


@dataclass(frozen=True)
class FaceQuery:
    """The faces step ``created_by`` named ``role``, those that pass ``where``."""

    created_by: str
    role: str
    where: Where = field(default_factory=Where)
    match: Match | None = None
    pointer: str = field(default="", compare=False)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"created_by": self.created_by, "role": self.role}
        if self.where.as_json():
            out["where"] = self.where.as_json()
        if self.match is not None:
            out["match"] = self.match.as_json()
        return out


FaceSet = tuple[FaceQuery, ...]


def _face_set_json(faces: FaceSet) -> Any:
    """One face query as itself, several as a list (so a stage-3 reference reads back as it was written)."""
    return faces[0].as_json() if len(faces) == 1 else [f.as_json() for f in faces]


@dataclass(frozen=True)
class EdgeQuery:
    """Edges: of a set of faces, or between two sets; those that pass ``where``; held to ``match``.

    Each set is one face query or several, the faces any of them finds.
    """

    match: Match
    of: FaceSet | None = None
    between: tuple[FaceSet, FaceSet] | None = None
    where: Where = field(default_factory=Where)
    pointer: str = field(default="", compare=False)

    @property
    def faces(self) -> tuple[FaceQuery, ...]:
        """Every face query the query names."""
        if self.of is not None:
            return self.of
        return tuple(f for side in self.between or () for f in side)

    @property
    def steps(self) -> tuple[str, ...]:
        """The steps the query names."""
        return tuple(f.created_by for f in self.faces)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"match": self.match.as_json()}
        if self.of is not None:
            out["of"] = _face_set_json(self.of)
        if self.between is not None:
            out["between"] = [_face_set_json(side) for side in self.between]
        if self.where.as_json():
            out["where"] = self.where.as_json()
        return out


@dataclass(frozen=True)
class EdgeQueries:
    """Several edge queries made at once: the edges every one finds, at least ``at_least`` in all.

    The spec's edge sets name several edges at once (a block's top lies
    between its top face and each of its four sides), and roundings that meet
    must be made in one operation. Each query keeps its own match (whose
    least count may be 0: an edge another item took away); the whole must
    find ``at_least``. docs/V2-stage4.md, 2.4.
    """

    queries: tuple[EdgeQuery, ...]
    at_least: int = 1
    pointer: str = field(default="", compare=False)

    @property
    def steps(self) -> tuple[str, ...]:
        return tuple(step for q in self.queries for step in q.steps)

    def as_json(self) -> dict[str, Any]:
        return {
            "queries": [q.as_json() for q in self.queries],
            "at_least": self.at_least,
        }


Reference = EdgeQuery | EdgeQueries


def _vec3(reader: Reader, what: str, *, unit_length: bool = False) -> Vec3:
    raw = reader.value
    if not (isinstance(raw, list) and len(raw) == 3):
        raise ValueRangeError(
            f"{what} is three numbers", pointer=reader.pointer, got=raw
        )
    values = tuple(
        Reader(v, join_pointer(reader.pointer, i)).as_float() for i, v in enumerate(raw)
    )
    if unit_length and math.sqrt(sum(v * v for v in values)) < 1e-12:
        raise ValueRangeError(f"{what} has no length", pointer=reader.pointer)
    return values[0], values[1], values[2]


def _decode_where(reader: Reader) -> Where:
    reader.reject_unknown(
        ("kind", "axis", "normal", "radius_mm", "through", "side", "centre", "within")
    )
    kind = reader.optional("kind")
    axis = reader.optional("axis")
    normal = reader.optional("normal")
    radius = reader.optional("radius_mm")
    through = reader.optional("through")
    side = reader.optional("side")
    centre = reader.optional("centre")
    within = reader.optional("within")
    box: tuple[Vec3, Vec3] | None = None
    if within is not None:
        raw = within.value
        if not (isinstance(raw, list) and len(raw) == 2):
            raise ValueRangeError("`within` is a box: [least corner, greatest corner]",
                                  pointer=within.pointer, got=raw)  # fmt: skip
        lo = _vec3(Reader(raw[0], join_pointer(within.pointer, 0)), "a corner")
        hi = _vec3(Reader(raw[1], join_pointer(within.pointer, 1)), "a corner")
        if any(a > b for a, b in zip(lo, hi, strict=True)):
            raise ValueRangeError("`within` runs from its least corner to its greatest",
                                  pointer=within.pointer, got=raw)  # fmt: skip
        box = (lo, hi)
    return Where(
        kind=kind.as_str(allowed=_KINDS) if kind else None,
        axis=_vec3(axis, "an axis", unit_length=True) if axis else None,
        normal=_vec3(normal, "a normal", unit_length=True) if normal else None,
        radius_mm=radius.as_float(minimum=0.0) if radius else None,
        through=_vec3(through, "a point") if through else None,
        side=side.as_str(allowed=_SIDES) if side else None,
        centre=_vec3(centre, "a centre") if centre else None,
        within=box,
    )


def _decode_match(reader: Reader, *, least: int = 1) -> Match:
    reader.reject_unknown(("count", "covers"))
    count = reader.require("count")
    raw = count.value
    if not (isinstance(raw, list) and len(raw) == 2):
        raise ValueRangeError(
            "a match's count is a range: [least, most]", pointer=count.pointer, got=raw
        )
    lo = Reader(raw[0], join_pointer(count.pointer, 0)).as_int(minimum=least)
    hi = Reader(raw[1], join_pointer(count.pointer, 1)).as_int(minimum=max(least, 1))
    if hi < lo:
        raise ValueRangeError(
            "a match's count runs from the least to the most",
            pointer=count.pointer,
            got=raw,
        )
    covers = reader.optional("covers")
    return Match((lo, hi), covers.as_str(allowed=_COVERS) if covers else None)


def _decode_faces(reader: Reader, *, with_match: bool) -> FaceQuery:
    reader.reject_unknown(("created_by", "role", "where", "match"))
    where = reader.optional("where")
    match = reader.optional("match")
    if match is not None and not with_match:
        raise ValueRangeError(
            "the faces inside an edge reference take no match of their own: the edges do",
            pointer=match.pointer,
        )
    return FaceQuery(
        created_by=reader.require("created_by").as_identifier(),
        role=reader.require("role").as_identifier(),
        where=_decode_where(where) if where else Where(),
        match=_decode_match(match) if match else None,
        pointer=reader.pointer,
    )


def _decode_face_set(reader: Reader) -> FaceSet:
    """One face query, or a non-empty list of them."""
    raw = reader.value
    if isinstance(raw, list):
        if not raw:
            raise ValueRangeError(
                "a set of faces names at least one", pointer=reader.pointer
            )
        return tuple(_decode_faces(Reader(v, join_pointer(reader.pointer, i)), with_match=False)
                     for i, v in enumerate(raw))  # fmt: skip
    return (_decode_faces(reader, with_match=False),)


def _decode_edges(reader: Reader, *, least: int = 1) -> EdgeQuery:
    reader.reject_unknown(("of", "between", "where", "match"))
    of = reader.optional("of")
    between = reader.optional("between")
    if (of is None) == (between is None):
        raise ValueRangeError(
            "an edge reference is the edges `of` some faces, or `between` two sets of them",
            pointer=reader.pointer,
        )
    pair: tuple[FaceSet, FaceSet] | None = None
    if between is not None:
        listed = between.value
        if not (isinstance(listed, list) and len(listed) == 2):
            raise ValueRangeError(
                "`between` is two face references", pointer=between.pointer, got=listed
            )
        pair = (
            _decode_face_set(Reader(listed[0], join_pointer(between.pointer, 0))),
            _decode_face_set(Reader(listed[1], join_pointer(between.pointer, 1))),
        )
    where = reader.optional("where")
    return EdgeQuery(
        match=_decode_match(reader.require("match"), least=least),
        of=_decode_face_set(of) if of is not None else None,
        between=pair,
        where=_decode_where(where) if where else Where(),
        pointer=reader.pointer,
    )


def _decode_reference(reader: Reader) -> Reference:
    """An edge query, or several made at once (``queries``, ``at_least``)."""
    if not (isinstance(reader.value, dict) and "queries" in reader.value):
        return _decode_edges(reader)
    reader.reject_unknown(("queries", "at_least"))
    listed = reader.require("queries")
    raw = listed.value
    if not (isinstance(raw, list) and raw):
        raise ValueRangeError(
            "`queries` is a non-empty list of edge queries", pointer=listed.pointer
        )
    queries = tuple(_decode_edges(Reader(v, join_pointer(listed.pointer, i)), least=0)
                    for i, v in enumerate(raw))  # fmt: skip
    at_least = reader.optional("at_least")
    return EdgeQueries(
        queries, at_least.as_int(minimum=1) if at_least else 1, pointer=reader.pointer
    )


# --- steps -----------------------------------------------------------------------------


@dataclass(frozen=True)
class StepExtra:
    """What a step has beyond V1's feature: its spec items, and for a v2-only operation its op, parameters and references."""

    for_items: tuple[str, ...] = ()
    op: str | None = None
    params: Mapping[str, IRValue] = field(default_factory=dict)
    references: Mapping[str, Reference] = field(default_factory=dict)
    #: Parameters that are words (a line of letters' text).
    strings: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    """One step of a component, as v2 sees it."""

    id: str
    op: str
    inputs: tuple[str, ...]
    params: Mapping[str, IRValue]
    references: Mapping[str, Reference]
    #: Parameters that are words (a line of letters' text).
    strings: Mapping[str, str]
    role: str
    for_items: tuple[str, ...]
    tags: tuple[str, ...]
    description: str
    pointer: str
    #: V1's feature for this step: the step itself for V1's operations; for a
    #: v2-only one, what it is down-converted to (an identity, or an outline's polygon).
    feature: Feature

    @property
    def v2_only(self) -> bool:
        return self.op in V2_ONLY

    @property
    def spec(self) -> FeatureSpec:
        return V2_ONLY[self.op] if self.v2_only else FEATURE_SPECS[self.op]

    @property
    def publishes_as(self) -> str:
        """The prefix of the names this step publishes (V1's role, or its id)."""
        return self.role or self.id


# --- instances and mates -----------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """A rigid motion with V1's ``transform`` parameters: rotate about ``rotate_origin``, then translate."""

    translate: VectorValue | None = None
    rotate_axis: VectorValue | None = None
    rotate_angle: ScalarValue | None = None
    rotate_origin: VectorValue | None = None

    def resolve(self) -> tuple[tuple[tuple[float, float, float], ...], Vec3]:
        """(rotation rows, translation in mm)."""
        from forge_units import parse_unit

        angle = 0.0
        if self.rotate_angle is not None:
            angle = (
                self.rotate_angle.resolve(None).to(parse_unit("rad")).magnitude.midpoint
            )
        axis = (0.0, 0.0, 1.0)
        if self.rotate_axis is not None:
            axis = self.rotate_axis.resolve_direction(None)
        pivot = (
            self.rotate_origin.resolve_displacement(None)
            if self.rotate_origin
            else (0.0, 0.0, 0.0)
        )
        shift = (
            self.translate.resolve_displacement(None)
            if self.translate
            else (0.0, 0.0, 0.0)
        )
        x, y, z = axis
        c, s, t = math.cos(angle), math.sin(angle), 1.0 - math.cos(angle)
        rows = (
            (c + x * x * t, x * y * t - z * s, x * z * t + y * s),
            (y * x * t + z * s, c + y * y * t, y * z * t - x * s),
            (z * x * t - y * s, z * y * t + x * s, c + z * z * t),
        )
        turned = tuple(sum(rows[i][j] * pivot[j] for j in range(3)) for i in range(3))
        translation = tuple(pivot[i] - turned[i] + shift[i] for i in range(3))
        return rows, (translation[0], translation[1], translation[2])

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in ("translate", "rotate_axis", "rotate_angle", "rotate_origin"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value.as_json()
        return out

    def free_names(self) -> frozenset[str]:
        names: set[str] = set()
        for name in ("translate", "rotate_axis", "rotate_angle", "rotate_origin"):
            value = getattr(self, name)
            if value is not None:
                names |= value.free_names()
        return frozenset(names)


@dataclass(frozen=True)
class Instance:
    """One placed copy of a component."""

    id: str
    component: str
    at: Placement = field(default_factory=Placement)
    pointer: str = field(default="", compare=False)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "component": self.component}
        if self.at.as_json():
            out["at"] = self.at.as_json()
        return out


@dataclass(frozen=True)
class Port:
    """An instance's interface."""

    instance: str
    interface: str

    def as_json(self) -> dict[str, str]:
        return {"instance": self.instance, "interface": self.interface}


@dataclass(frozen=True)
class Mate:
    """Two instances' interfaces related: ``coaxial``, ``contact`` (with a ``gap``), or ``fixed``."""

    id: str
    kind: Literal["coaxial", "contact", "fixed"]
    a: Port
    b: Port
    gap: ScalarValue | None = None
    pointer: str = field(default="", compare=False)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "kind": self.kind, "a": self.a.as_json(),
                               "b": self.b.as_json()}  # fmt: skip
        if self.gap is not None:
            out["gap"] = self.gap.as_json()
        return out


def _decode_placement(reader: Reader) -> Placement:
    reader.reject_unknown(("translate", "rotate_axis", "rotate_angle", "rotate_origin"))
    found: dict[str, Any] = {}
    for name in ("translate", "rotate_axis", "rotate_origin"):
        child = reader.optional(name)
        if child is not None:
            found[name] = decode_vector(child)
    angle = reader.optional("rotate_angle")
    if angle is not None:
        found["rotate_angle"] = decode_scalar(angle)
    placement = Placement(**found)
    if placement.free_names():
        raise ValueRangeError(
            "an instance is placed by numbers with units, not by names",
            pointer=reader.pointer,
            names=sorted(placement.free_names()),
        )
    try:
        placement.resolve()
    except Exception as error:  # any unresolvable value is the document's
        raise ValueRangeError(
            f"an instance's placement can't be worked out: {error}",
            pointer=reader.pointer,
        ) from error
    return placement


def _decode_instance(reader: Reader) -> Instance:
    reader.reject_unknown(("id", "component", "at"))
    at = reader.optional("at")
    return Instance(
        id=reader.require("id").as_identifier(),
        component=reader.require("component").as_identifier(),
        at=_decode_placement(at) if at is not None else Placement(),
        pointer=reader.pointer,
    )


def _decode_port(reader: Reader) -> Port:
    reader.reject_unknown(("instance", "interface"))
    return Port(
        reader.require("instance").as_identifier(),
        reader.require("interface").as_identifier(),
    )


def _decode_mate(reader: Reader) -> Mate:
    reader.reject_unknown(("id", "kind", "a", "b", "gap"))
    kind = reader.require("kind").as_str(allowed=MATE_KINDS)
    gap = reader.optional("gap")
    if gap is not None and kind != "contact":
        raise ValueRangeError(
            "only a contact mate has a gap", pointer=gap.pointer, kind=kind
        )
    return Mate(
        id=reader.require("id").as_identifier(),
        kind=kind,  # type: ignore[arg-type]
        a=_decode_port(reader.require("a")),
        b=_decode_port(reader.require("b")),
        gap=decode_scalar(gap) if gap is not None else None,
        pointer=reader.pointer,
    )


# --- pointers between the two forms ------------------------------------------------------

_V1_STEP = re.compile(r"^(/components/\d+)/features(?=/|$)(/\d+)?(/kind|/parameters)?")


def _to_v2_pointer(pointer: str) -> str:
    """A pointer into the V1 form of a document, as the same place in its v2 form."""

    def swap(match: re.Match[str]) -> str:
        tail = {"/kind": "/op", "/parameters": "/params", None: ""}[match.group(3)]
        return f"{match.group(1)}/steps{match.group(2) or ''}{tail}"

    return _V1_STEP.sub(swap, pointer)


def _repoint(error: SchemaError) -> SchemaError:
    """``error`` (and every error in a group) pointing into the v2 document."""
    if isinstance(error, SchemaErrorGroup):
        return SchemaErrorGroup([_repoint(e) for e in error.errors])
    error.pointer = _to_v2_pointer(error.pointer)
    if isinstance(error.detail.get("pointer"), str):
        error.detail["pointer"] = _to_v2_pointer(error.detail["pointer"])
    return error


def _repointed(component: Component) -> Component:
    features = [
        replace(f, pointer=_to_v2_pointer(f.pointer)) for f in component.features
    ]
    graph = FeatureGraph(features, pointer=join_pointer(component.pointer, "steps"))
    return replace(component, features=graph)


# --- the document ----------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentV2:
    """A ForgeIR v2 document: V1's document (``base``, its v2-only steps as identities) and what v2 adds."""

    base: Document
    extras: Mapping[tuple[str, str], StepExtra] = field(default_factory=dict)
    instances: tuple[Instance, ...] = ()
    mates: tuple[Mate, ...] = ()

    # -- access ---------------------------------------------------------------------
    @property
    def components(self) -> tuple[Component, ...]:
        return self.base.components

    def component(self, identifier: str) -> Component:
        return self.base.component(identifier)

    def steps(self, component: str) -> tuple[Step, ...]:
        """Every step of ``component``, in the order written."""
        return tuple(
            self._step(component, f) for f in self.component(component).features
        )

    def step(self, component: str, step: str) -> Step:
        return self._step(component, self.component(component).features[step])

    def _step(self, component: str, feature: Feature) -> Step:
        extra = self.extras.get((component, feature.identifier), StepExtra())
        return Step(
            id=feature.identifier,
            op=extra.op or feature.kind,
            inputs=feature.inputs,
            params=extra.params if extra.op else feature.parameters,
            references=extra.references,
            strings=extra.strings,
            role=feature.role,
            for_items=extra.for_items,
            tags=feature.tags,
            description=feature.description,
            pointer=feature.pointer,
            feature=feature,
        )

    def v2_only(self, component: str) -> tuple[str, ...]:
        """The steps of ``component`` the implicit kernel builds as identities (down-converted)."""
        return tuple(s.id for s in self.steps(component) if s.v2_only)

    def placed(self) -> tuple[Instance, ...]:
        """The instances: as written, or one of each component where it was built if none are."""
        if self.instances:
            return self.instances
        return tuple(Instance(c.identifier, c.identifier) for c in self.components)

    # -- the two forms ------------------------------------------------------------------
    def to_v1(self) -> Document:
        """The same document in V1's form; only for a document that uses V1's operations alone."""
        if any(extra.op for extra in self.extras.values()):
            names = sorted(f"{c}/{s}" for (c, s), e in self.extras.items() if e.op)
            raise ValueError(f"steps V1 can't express: {', '.join(names)}")
        if self.instances or self.mates:
            raise ValueError("V1 has no instances or mates")
        return self.base

    def down_converted(self) -> Document:
        """V1's form for the implicit kernel: every v2-only step an identity of its input, an outline a polygon within :data:`OUTLINE_CHORD` of it."""
        return self.base

    def as_json(self) -> dict[str, Any]:
        payload = copy.deepcopy(self.base.as_json())
        payload["schema_version"] = SCHEMA_VERSION_V2
        for component in payload["components"]:
            steps = []
            for feature in component.pop("features"):
                extra = self.extras.get((component["id"], feature["id"]), StepExtra())
                step: dict[str, Any] = {"id": feature["id"]}
                if extra.op:
                    step["op"] = extra.op
                    step["params"] = {
                        k: v.as_json() for k, v in sorted(extra.params.items())
                    }
                    for name, query in sorted(extra.references.items()):
                        step["params"][name] = query.as_json()
                    for name, words in sorted(extra.strings.items()):
                        step["params"][name] = words
                else:
                    step["op"] = feature["kind"]
                    if "parameters" in feature:
                        step["params"] = feature["parameters"]
                for name in ("inputs", "role", "tags", "description"):
                    if name in feature:
                        step[name] = feature[name]
                if extra.for_items:
                    step["for_items"] = list(extra.for_items)
                steps.append(step)
            component["steps"] = steps
        if self.instances:
            payload["instances"] = [i.as_json() for i in self.instances]
        if self.mates:
            payload["mates"] = [m.as_json() for m in self.mates]
        return payload

    def to_json(self, *, indent: int = 2) -> str:
        """Canonical: sorted keys and fixed separators, as V1's."""
        return json.dumps(
            self.as_json(), indent=indent, sort_keys=True, separators=(",", ": ")
        )

    @classmethod
    def from_json(cls, text: str | bytes) -> DocumentV2:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise SchemaError(
                f"document is not valid JSON: {error.msg}",
                pointer="",
                line=error.lineno,
                column=error.colno,
            ) from error
        except RecursionError as error:
            raise SchemaError("document is nested too deeply", pointer="") from error
        return decode_document_v2(Reader(payload, ""))

    @classmethod
    def from_any(cls, text: str | bytes) -> DocumentV2:
        """A v2 document, or a V1 one converted."""
        payload = json.loads(text)
        version = (
            str(payload.get("schema_version", "")) if isinstance(payload, dict) else ""
        )
        if version.split(".")[0] == SCHEMA_VERSION.split(".")[0]:
            return convert_v1(Document.from_json(text))
        return cls.from_json(text)


def convert_v1(document: Document) -> DocumentV2:
    """A V1 document as v2, with nothing lost: :meth:`DocumentV2.to_v1` gives it back."""
    return DocumentV2(base=document)


def decode_document_v2(reader: Reader) -> DocumentV2:
    reader.reject_unknown(_DOCUMENT_FIELDS)
    version = reader.require("schema_version").as_str()
    if version.split(".")[0] != SCHEMA_VERSION_V2.split(".")[0]:
        raise ValueRangeError(
            "this is not a ForgeIR v2 document",
            pointer=join_pointer(reader.pointer, "schema_version"),
            got=version,
            supported=SCHEMA_VERSION_V2,
        )
    payload = dict(reader.as_object())
    instances_reader = reader.optional("instances")
    mates_reader = reader.optional("mates")
    payload.pop("instances", None)
    payload.pop("mates", None)
    payload["schema_version"] = SCHEMA_VERSION

    errors: list[SchemaError] = []
    extras: dict[tuple[str, str], StepExtra] = {}
    components = reader.optional("components")
    translated: list[Any] = []
    for index, raw in enumerate(components.value if components else ()):
        component = Reader(
            raw, join_pointer(join_pointer(reader.pointer, "components"), index)
        )
        try:
            translated.append(_translate_component(component, extras))
        except SchemaError as error:
            errors.append(error)
            translated.append(raw)
    if components is not None:
        payload["components"] = (
            translated if isinstance(components.value, list) else components.value
        )
    if errors:
        raise SchemaErrorGroup(errors) if len(errors) > 1 else errors[0]

    try:
        base = decode_document(Reader(payload, reader.pointer))
    except SchemaError as error:
        raise _repoint(error) from None
    base = replace(base, components=tuple(_repointed(c) for c in base.components))

    instances = (
        tuple(instances_reader.decode_list(_decode_instance))
        if instances_reader
        else ()
    )
    mates = tuple(mates_reader.decode_list(_decode_mate)) if mates_reader else ()
    document = DocumentV2(base=base, extras=extras, instances=instances, mates=mates)
    _validate_v2(document, reader)
    return document


def _translate_component(
    reader: Reader, extras: dict[tuple[str, str], StepExtra]
) -> dict[str, Any]:
    """A v2 component in V1's form; what V1 can't hold goes into ``extras``."""
    reader.reject_unknown(_COMPONENT_FIELDS)
    raw = dict(reader.as_object())
    identifier = reader.require("id").as_identifier()
    steps = reader.require("steps")
    features = []
    errors: list[SchemaError] = []
    for index, value in enumerate(steps.value if isinstance(steps.value, list) else ()):
        step = Reader(value, join_pointer(steps.pointer, index))
        try:
            features.append(_translate_step(step, identifier, extras))
        except SchemaError as error:
            errors.append(error)
    if not isinstance(steps.value, list):
        raise ValueRangeError("a component's steps are a list", pointer=steps.pointer)
    if errors:
        raise SchemaErrorGroup(errors) if len(errors) > 1 else errors[0]
    raw.pop("steps")
    raw["features"] = features
    return raw


def _translate_step(
    reader: Reader, component: str, extras: dict[tuple[str, str], StepExtra]
) -> dict[str, Any]:
    reader.reject_unknown(_STEP_FIELDS)
    identifier = reader.require("id").as_identifier()
    op = reader.require("op").as_str(allowed=OPS)
    for_items_reader = reader.optional("for_items")
    for_items = tuple(for_items_reader.as_str_list()) if for_items_reader else ()
    for position, item in enumerate(for_items):
        Reader(item, join_pointer(for_items_reader.pointer, position)).as_identifier()  # type: ignore[union-attr]
    feature: dict[str, Any] = {"id": identifier}
    for name in ("inputs", "role", "tags", "description"):
        if reader.has(name):
            feature[name] = reader.as_object()[name]
    if op not in V2_ONLY:
        feature["kind"] = op
        if reader.has("params"):
            feature["parameters"] = reader.as_object()["params"]
        if for_items:
            extras[(component, identifier)] = StepExtra(for_items=for_items)
        return feature
    # A v2-only step: V1 holds it as an identity of its input (an outline, as
    # the polygon within OUTLINE_CHORD of it); its own parameters and
    # references are read here.
    feature["kind"] = _V1_FORMS.get(op, "transform")
    spec = V2_ONLY[op]
    params = reader.require("params")
    raw = params.as_object()
    if op == "profile_outline":
        feature["parameters"] = {"points": _chords(params.child("points"))}
    names = _REFERENCES[op]
    strings = {name: _words(params, name) for name in _STRINGS.get(op, ())}
    plain = {k: v for k, v in raw.items() if k not in names and k not in strings}
    try:
        decoded = _decode_parameters(
            Reader({"parameters": plain}, reader.pointer), spec
        )
    except SchemaError as error:
        raise _swap_params(error) from None
    references: dict[str, Reference] = {}
    for name in names:
        if name not in raw:
            raise DanglingReferenceError(
                f"a {op} needs its `{name}` reference",
                pointer=join_pointer(params.pointer, name),
            )
        references[name] = _decode_reference(params.child(name))
    extras[(component, identifier)] = StepExtra(
        for_items=for_items,
        op=op,
        params=decoded,
        references=references,
        strings=strings,
    )
    return feature


def _words(params: Reader, name: str) -> str:
    """A parameter that is words: a string of one line, not empty."""
    found = params.require(name).as_str()
    at = join_pointer(params.pointer, name)
    if not found:
        raise ValueRangeError(f"`{name}` has at least one letter", pointer=at)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in found):
        raise ValueRangeError(
            f"`{name}` is one line: no line breaks, tabs or control characters",
            pointer=at,
        )
    return found


def _chords(reader: Reader) -> list[list[float]]:
    """A ``profile_outline``'s points as V1's ``profile_sketch`` takes them: each arc followed by chords no further than :data:`OUTLINE_CHORD` from it.

    V1's form is worked out from the points, so each is a length written out
    (in any length unit), not an expression.
    """
    found: list[list[float]] = []
    for n, row in enumerate(decode_points(reader).points):
        at = join_pointer(reader.pointer, n)
        numbers = []
        for value in row:
            if (
                not isinstance(value, QuantityValue)
                or not value.quantity.magnitude.is_exact
            ):
                raise ValueRangeError(
                    "an outline's points are lengths written out, not expressions",
                    pointer=at,
                )
            numbers.append(value.quantity.magnitude_in("mm").lo)
        if len(numbers) not in (2, 4) or (not found and len(numbers) != 2):
            raise ValueRangeError("an outline starts at [u, v]; each side ends at [u, v], or an arc's at "
                                  "[u, v, mu, mv] through (mu, mv)", pointer=at)  # fmt: skip
        if len(numbers) == 4:
            found += _arc_chords(found[-1], numbers, at)
        found.append(numbers[:2])
    if len(found) < 4 or math.dist(found[0], found[-1]) > 1e-9:
        raise ValueRangeError("an outline has three sides or more and ends where it starts",
                              pointer=reader.pointer)  # fmt: skip
    return found


def _arc_chords(
    start: list[float], row: list[float], pointer: str
) -> list[list[float]]:
    """The points an arc from ``start`` to (row[0], row[1]) through (row[2], row[3]) is followed by, before its end."""
    (ax, ay), (bx, by), (mx, my) = start, row[:2], row[2:]
    d = 2.0 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) <= 1e-12 * max(1.0, math.dist(start, row[:2])) ** 2:
        raise ValueRangeError("an arc's three points lie on a line", pointer=pointer)
    ux = (
        (ax * ax + ay * ay) * (my - by)
        + (mx * mx + my * my) * (by - ay)
        + (bx * bx + by * by) * (ay - my)
    ) / d
    uy = (
        (ax * ax + ay * ay) * (bx - mx)
        + (mx * mx + my * my) * (ax - bx)
        + (bx * bx + by * by) * (mx - ax)
    ) / d
    r = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux)
    am = math.atan2(my - uy, mx - ux)
    a1 = math.atan2(by - uy, bx - ux)
    sweep = (a1 - a0) % (2 * math.pi)
    if (am - a0) % (2 * math.pi) > sweep:  # it goes the other way round
        sweep -= 2 * math.pi
    step = (
        2 * math.acos(max(-1.0, 1.0 - OUTLINE_CHORD / r))
        if r > OUTLINE_CHORD
        else math.pi
    )
    n = max(1, math.ceil(abs(sweep) / step))
    return [
        [ux + r * math.cos(a0 + sweep * k / n), uy + r * math.sin(a0 + sweep * k / n)]
        for k in range(1, n)
    ]


def _swap_params(error: SchemaError) -> SchemaError:
    if isinstance(error, SchemaErrorGroup):
        return SchemaErrorGroup([_swap_params(e) for e in error.errors])
    error.pointer = re.sub(r"/parameters(?=/|$)", "/params", error.pointer)
    return error


def _validate_v2(document: DocumentV2, reader: Reader) -> None:
    """What v2 adds to V1's rules: references among a step's ancestors, single-input v2 steps, instances and mates."""
    errors: list[SchemaError] = []
    for component in document.components:
        graph = component.features
        for step in document.steps(component.identifier):
            if not step.v2_only:
                continue
            if len(step.inputs) != 1:
                takes = step.spec.inputs[0].replace("_", " ")
                errors.append(ValueRangeError(
                    f"a {step.op} takes one {takes}", pointer=join_pointer(step.pointer, "inputs"),
                    got=len(step.inputs)))  # fmt: skip
                continue
            reachable = set(graph.ancestors_of(step.inputs[0])) | {step.inputs[0]}
            for name, query in step.references.items():
                for named in query.steps:
                    if named not in reachable:
                        errors.append(DanglingReferenceError(
                            "a reference names a step this one doesn't build on",
                            pointer=join_pointer(join_pointer(step.pointer, "params"), name),
                            step=named, reachable=sorted(reachable)))  # fmt: skip
    ids = [i.id for i in document.instances]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        errors.append(DuplicateIdentifierError(
            "two instances share an id", pointer=join_pointer(reader.pointer, "instances"),
            duplicates=duplicates))  # fmt: skip
    known = {c.identifier: c for c in document.components}
    placed: dict[str, Component] = {}
    for instance in document.instances:
        if instance.component not in known:
            errors.append(DanglingReferenceError(
                "an instance of a component the document hasn't", pointer=instance.pointer,
                component=instance.component, available=sorted(known)))  # fmt: skip
        else:
            placed[instance.id] = known[instance.component]
    if document.mates and not document.instances:
        errors.append(ValueRangeError(
            "mates relate instances; the document places none",
            pointer=join_pointer(reader.pointer, "mates")))  # fmt: skip
    mate_ids = [m.id for m in document.mates]
    if len(set(mate_ids)) != len(mate_ids):
        errors.append(DuplicateIdentifierError(
            "two mates share an id", pointer=join_pointer(reader.pointer, "mates")))  # fmt: skip
    for mate in document.mates:
        if mate.a.instance == mate.b.instance:
            errors.append(ValueRangeError("a mate relates two instances, not one to itself",
                                          pointer=mate.pointer))  # fmt: skip
        for side, port in (("a", mate.a), ("b", mate.b)):
            where = join_pointer(mate.pointer, side)
            if port.instance not in placed:
                if document.instances:
                    errors.append(DanglingReferenceError(
                        "a mate names an instance the document hasn't", pointer=where,
                        instance=port.instance, available=sorted(placed)))  # fmt: skip
                continue
            component = placed[port.instance]
            found = [i for i in component.interfaces if i.identifier == port.interface]
            if not found:
                errors.append(DanglingReferenceError(
                    "a mate names an interface the instance's component hasn't", pointer=where,
                    interface=port.interface,
                    available=sorted(i.identifier for i in component.interfaces)))  # fmt: skip
                continue
            suits = _MATE_PORTS.get(mate.kind)
            if suits is not None and found[0].interface_type not in suits:
                errors.append(ValueRangeError(
                    f"a {mate.kind} mate relates {', '.join(sorted(suits))} interfaces",
                    pointer=where, got=found[0].interface_type))  # fmt: skip
    if errors:
        raise SchemaErrorGroup(errors) if len(errors) > 1 else errors[0]


# --- the JSON Schema -----------------------------------------------------------------------


def _reference_schema() -> dict[str, Any]:
    number3 = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
    }
    where = {
        "type": "object",
        "properties": {
            "kind": {"enum": list(_KINDS)},
            "axis": number3,
            "normal": number3,
            "radius_mm": {"type": "number", "minimum": 0},
            "through": number3,
            "side": {"enum": list(_SIDES)},
            "centre": number3,
            "within": {"type": "array", "items": number3, "minItems": 2, "maxItems": 2},
        },
        "additionalProperties": False,
    }

    def match(least: int) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "count": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": least},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "covers": {"enum": list(_COVERS)},
            },
            "required": ["count"],
            "additionalProperties": False,
        }

    faces = {
        "type": "object",
        "properties": {
            "created_by": {"type": "string"},
            "role": {"type": "string"},
            "where": where,
        },
        "required": ["created_by", "role"],
        "additionalProperties": False,
    }
    face_set = {"oneOf": [faces, {"type": "array", "items": faces, "minItems": 1}]}

    def query(least: int) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "of": face_set,
                "between": {
                    "type": "array",
                    "items": face_set,
                    "minItems": 2,
                    "maxItems": 2,
                },
                "where": where,
                "match": match(least),
            },
            "required": ["match"],
            "additionalProperties": False,
        }

    several = {
        "type": "object",
        "properties": {
            "queries": {"type": "array", "items": query(0), "minItems": 1},
            "at_least": {"type": "integer", "minimum": 1},
        },
        "required": ["queries"],
        "additionalProperties": False,
    }
    return {"oneOf": [query(1), several]}


def document_schema_v2() -> dict[str, Any]:
    """JSON Schema for a ForgeIR v2 document, made from V1's and the v2 catalogue."""
    schema = copy.deepcopy(document_schema())
    schema["title"] = "ForgeIR v2 document"
    properties = schema["properties"]
    properties["schema_version"] = {"const": SCHEMA_VERSION_V2}
    component = properties["components"]["items"]
    branches = component["properties"].pop("features")["items"]["oneOf"]
    steps = []
    for branch in branches:
        props = branch["properties"]
        props["op"] = props.pop("kind")
        if "parameters" in props:
            props["params"] = props.pop("parameters")
        props["for_items"] = {"type": "array", "items": {"type": "string"}}
        branch["required"] = [
            {"kind": "op", "parameters": "params"}.get(r, r) for r in branch["required"]
        ]
        steps.append(branch)
    for op, spec in sorted(V2_ONLY.items()):
        params: dict[str, Any] = {
            p.name: dict(_parameter_schema(p)) if p.sort not in ("length", "angle", "dimensionless") else {"oneOf": [
                {"type": "object", "properties": {"magnitude": {"type": "number"},
                                                  "unit": {"type": "string"}},
                 "required": ["magnitude", "unit"], "additionalProperties": False},
                {"type": "object", "properties": {"expression": {"type": "string"},
                                                  "unit": {"type": "string"}},
                 "required": ["expression"], "additionalProperties": False},
            ]}
            for p in spec.parameters
        }  # fmt: skip
        for name in _REFERENCES[op]:
            params[name] = _reference_schema()
        for name in _STRINGS.get(op, ()):
            params[name] = {"type": "string", "minLength": 1}
        steps.append({
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "op": {"const": op}, "role": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "inputs": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                           "maxItems": 1},
                "for_items": {"type": "array", "items": {"type": "string"}},
                "params": {"type": "object", "properties": params,
                           "required": sorted(params), "additionalProperties": False},
            },
            "required": ["id", "op", "inputs", "params"],
            "additionalProperties": False,
        })  # fmt: skip
    component["properties"]["steps"] = {
        "type": "array",
        "minItems": 1,
        "items": {"oneOf": steps},
    }
    component["required"] = ["id", "steps"]
    # An instance is placed by numbers with units, never by names (the decoder refuses names).
    numbers = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
    }
    length = {
        "type": "object",
        "properties": {"vector": numbers, "unit": {"type": "string"}},
        "required": ["vector", "unit"],
        "additionalProperties": False,
    }
    direction = {
        "oneOf": [
            numbers,
            {
                "type": "object",
                "properties": {"vector": numbers, "unit": {"type": "string"}},
                "required": ["vector"],
                "additionalProperties": False,
            },
        ]
    }
    quantity = {
        "type": "object",
        "properties": {"magnitude": {"type": "number"}, "unit": {"type": "string"}},
        "required": ["magnitude", "unit"],
        "additionalProperties": False,
    }
    properties["instances"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "component": {"type": "string"},
                "at": {"type": "object", "properties": {
                    "translate": length, "rotate_axis": direction, "rotate_origin": length,
                    "rotate_angle": quantity}, "additionalProperties": False},
            },
            "required": ["id", "component"],
            "additionalProperties": False,
        },
    }  # fmt: skip
    port = {"type": "object", "properties": {"instance": {"type": "string"},
                                             "interface": {"type": "string"}},
            "required": ["instance", "interface"], "additionalProperties": False}  # fmt: skip
    properties["mates"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "kind": {"enum": list(MATE_KINDS)},
                           "a": port, "b": port, "gap": dict(quantity)},
            "required": ["id", "kind", "a", "b"],
            "additionalProperties": False,
        },
    }  # fmt: skip
    return schema


def write_schema_v2(path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document_schema_v2(), handle, indent=2, sort_keys=True)
        handle.write("\n")


#: A small v2 document: a plate with its top edges rounded.
EXAMPLE = json.dumps(
    {
        "schema_version": SCHEMA_VERSION_V2,
        "document_id": "example",
        "project_id": "example",
        "revision": 1,
        "name": "a rounded plate",
        "components": [
            {
                "id": "plate",
                "steps": [
                    {"id": "body", "op": "box", "role": "plate", "for_items": ["plate"],
                     "params": {"size": {"vector": [40, 30, 6], "unit": "mm"}}},
                    {"id": "round", "op": "fillet", "inputs": ["body"], "for_items": ["top_edges"],
                     "params": {"radius": {"magnitude": 2, "unit": "mm"},
                                "edges": {"of": {"created_by": "body", "role": "z_max"},
                                          "match": {"count": [4, 4]}}}},
                ],
            }
        ],
    }
)  # fmt: skip
