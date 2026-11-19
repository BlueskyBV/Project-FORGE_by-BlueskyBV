"""The document as it is written: steps appended to a chain, and what each spec face is called.

A **chain** is the construction so far: the steps written, the step that
holds the part made so far (its head), what each item copy's faces are
called in the built part (docs/V2-stage4.md 4.6), and the boxes of every
tool added to the part and taken from it (the proofs of section 5 read
them).

Every number is written as a literal with its unit, rounded to
:data:`DIGITS` decimal places, so one spec is one document on every
platform whatever its floating point rounds a sine to. Step ids are
``<item>.<copy>.<part>`` and the chain's own ``<item>.join``,
``<item>.cut``; a face's name in the built part is ``(step, role)``, the
roles stage 3's operations give (docs/V2-stage3.md 7.2).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from forge_ir.v2 import DocumentV2

from .errors import PlanError

__all__ = [
    "DATUMS",
    "DIGITS",
    "PLANE_AXES",
    "Box",
    "Chain",
    "Done",
    "Early",
    "Hollow",
    "Ref",
    "Vec",
    "add",
    "along",
    "axis_of",
    "direction",
    "dot",
    "length",
    "neg",
    "num",
    "ordered",
    "point",
    "role_of",
    "scale",
    "unit",
]

Vec = tuple[float, float, float]

#: Decimal places every literal is rounded to (1e-9 mm, 1e-9 degrees).
DIGITS = 9

_AXES: Mapping[str, Vec] = {
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
}

#: The standard datum plane square to each frame axis, and the way its normal runs along it
#: (stage 3: XY's normal +z, YZ's +x, XZ's -y; a profile's u and v are the face's first and
#: second axes, the frame table of docs/definitions/frame.md).
DATUMS: Mapping[str, tuple[str, float]] = {
    "z": ("XY", 1.0),
    "x": ("YZ", 1.0),
    "y": ("XZ", -1.0),
}
#: Each standard plane's u and v axes.
PLANE_AXES: Mapping[str, tuple[str, str]] = {
    "XY": ("x", "y"),
    "YZ": ("y", "z"),
    "XZ": ("x", "z"),
}


def num(x: float) -> float:
    """A literal as written: rounded, and never minus zero."""
    value = round(float(x), DIGITS)
    if not math.isfinite(value):
        raise PlanError(f"a number to write isn't finite: {x!r}")
    return value + 0.0


def length(x: float) -> dict[str, Any]:
    return {"magnitude": num(x), "unit": "mm"}


def point(p: Sequence[float]) -> dict[str, Any]:
    return {"vector": [num(c) for c in p], "unit": "mm"}


def direction(u: Sequence[float]) -> dict[str, Any]:
    return {"vector": [num(c) for c in u]}


def unit(name: str) -> Vec:
    """A frame direction by name: ``+x``, ``-z``; or a frame axis: ``x``."""
    base = _AXES[name[-1]]
    sign = -1.0 if name.startswith("-") else 1.0
    return (sign * base[0] + 0.0, sign * base[1] + 0.0, sign * base[2] + 0.0)


def axis_of(u: Sequence[float]) -> str:
    """The frame axis a frame direction runs along."""
    k = max(range(3), key=lambda i: abs(u[i]))
    if abs(abs(u[k]) - 1.0) > 1e-12 or any(
        abs(u[i]) > 1e-12 for i in range(3) if i != k
    ):
        raise PlanError(f"{tuple(u)} is not a frame direction")
    return "xyz"[k]


def role_of(direction_name: str) -> str:
    """A box's face facing that way: ``+x`` is its ``x_max``."""
    return f"{direction_name[1]}_{'max' if direction_name[0] == '+' else 'min'}"


def add(a: Sequence[float], b: Sequence[float], k: float = 1.0) -> Vec:
    return (a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2])


def scale(a: Sequence[float], k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def neg(a: Sequence[float]) -> Vec:
    return (-a[0] + 0.0, -a[1] + 0.0, -a[2] + 0.0)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def along(a: Sequence[float], name: str) -> float:
    """A point's coordinate along a frame axis."""
    return float(a["xyz".index(name)])


@dataclass(frozen=True, order=True)
class Ref:
    """A face of the built part, by the step that made it and the role it gave it.

    ``normal``, where given, holds the role's faces to the plane ones facing
    that way: an extrusion calls every face round its outline ``side``, and
    a box-like tool made by one (a block whose vertical edges are rounded
    early, 5.5) has its four sides told apart so.
    """

    step: str
    role: str
    normal: Vec | tuple[()] = ()

    def as_json(self) -> dict[str, Any]:
        found: dict[str, Any] = {"created_by": self.step, "role": self.role}
        if self.normal:
            found["where"] = {"normal": [num(c) for c in self.normal]}
        return found


@dataclass(frozen=True)
class Box:
    """The box round a tool, and the item copy it is for."""

    lo: Vec
    hi: Vec
    item: str
    copy: int

    def meets(self, other: Box, *, by: float = 0.0) -> bool:
        """Whether the two boxes' interiors overlap (touching on a plane is not meeting), ``other`` grown by ``by``."""
        return all(
            self.lo[k] < other.hi[k] + by and other.lo[k] - by < self.hi[k]
            for k in range(3)
        )


def box_round(points: Iterable[Sequence[float]]) -> tuple[Vec, Vec]:
    """The box round some points."""
    found = list(points)
    lo = tuple(min(p[k] for p in found) for k in range(3))
    hi = tuple(max(p[k] for p in found) for k in range(3))
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


class RoundingOp(StrEnum):
    """ForgeIR's two rounding operations, which share their names with the items that ask for them."""

    FILLET = "fillet"
    CHAMFER = "chamfer"


@dataclass(frozen=True)
class Done:
    """A rounding or chamfer already made on one copy of an item: its step, kind, size and edges (by their two faces).

    ``faces`` are its round or bevel faces where it made them otherwise than
    as a fillet or chamfer step's (early, on the item's own tool: 5.5).
    """

    step: str
    bevel: bool
    size: float
    pairs: frozenset[frozenset[str]]
    faces: tuple[Ref, ...] = ()
    #: The rounding or chamfer item that made it.
    rounding: str = ""

    @property
    def refs(self) -> tuple[Ref, ...]:
        """Its round or bevel faces in the part."""
        return self.faces or (Ref(self.step, "bevel" if self.bevel else "round"),)


def ordered(pairs: Iterable[frozenset[str]]) -> list[tuple[str, ...]]:
    """Edges by their faces, in one fixed order: a set's own order changes from run to run, a document's never may."""
    return sorted(tuple(sorted(pair)) for pair in pairs)


@dataclass(frozen=True)
class Early:
    """A rounding made early, on its item's own tool before it is joined (5.5): which edges, how, how big."""

    rounding: str
    which: str
    bevel: bool
    size: float


@dataclass(frozen=True)
class Hollow:
    """The hollow a shell made in one copy of a body: its box, and its radius for a round one."""

    lo: Vec
    hi: Vec
    radius: float = 0.0
    #: Its own edges' roundings, following the body's (each by the faces of the body over it).
    rounded: tuple[Done, ...] = ()


@dataclass
class Chain:
    """The construction so far."""

    #: The step holding the part made so far; None before the first body.
    head: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    #: Each item copy's faces, by the schema's names (and a cut's own: its ``wall``, ``floor``, ...).
    faces: dict[tuple[str, int], dict[str, tuple[Ref, ...]]] = field(
        default_factory=dict
    )
    added: list[Box] = field(default_factory=list)
    cut: list[Box] = field(default_factory=list)
    #: The planned item each step was written for.
    owners: dict[str, str] = field(default_factory=dict)
    #: The steps that join to or cut the part made so far: after each the part is one solid (V2-stage4.md, 8).
    parts: list[str] = field(default_factory=list)
    #: Each item copy's roundings and chamfers made so far, in order.
    rounded: dict[tuple[str, int], list[Done]] = field(default_factory=dict)
    #: Each hollowed body copy's hollow.
    hollows: dict[tuple[str, int], Hollow] = field(default_factory=dict)
    #: The planned item being written.
    planning: str = ""
    #: The boxes each planned item's tools (or a rounding's edges) take up: the build loop's search reads them.
    boxes: dict[str, list[Box]] = field(default_factory=dict)
    #: The roundings to make early, on each item's own tool (5.5), by the item they round.
    early: dict[str, list[Early]] = field(default_factory=dict)
    #: Each rounding made early, on each copy (by its index).
    made_early: set[tuple[str, int]] = field(default_factory=set)
    #: A copy made upright and unturned, then moved onto the part (a turned box; what is on a turned item's face): the
    #: box round it as it stands so (None for a cut), and the motion (a ``forge_spec.frames.Rigid``) that moves it.
    #: Its edges are found so, then moved (edges.md, "A turned item's edges").
    motions: dict[tuple[str, int], tuple[Vec | None, Vec | None, Any]] = field(default_factory=dict)
    #: A ball (or a dome) made turned about its centre, or a cone about its axis, so its seam (and a ball's poles)
    #: are clear of what is on it (:mod:`forge_plan.seams`): the turn (a ``forge_spec.frames.Rigid``), by its copy.
    #: What is on it is cut by its ball or cone turned alike, and a ball's hollow's inner ball.
    seams: dict[tuple[str, int], Any] = field(default_factory=dict)
    #: While a hole's construction that turns its round tools is written (V2-stage4.md, 5.7): each cylinder or cone it
    #: makes is turned a quarter turn about its own axis, the same points with its seam elsewhere.
    turning: bool = False
    #: Each round tool so turned, by its step: what takes it as an input takes the turned one (its names its own).
    turned: dict[str, str] = field(default_factory=dict)

    def turned_round(self, solid: str, base: Sequence[float], axis: Sequence[float], *, item: str) -> str:
        """A cylinder's or a cone's step, turned a quarter turn about its own axis while :attr:`turning` (5.7); its
        own id, which names its faces, either way."""
        if not self.turning:
            return solid
        from forge_numeric import scalar as fs
        from forge_spec.frames import Rigid

        from .moved import transform_params

        size = fs.hypot(axis[0], axis[1], axis[2])
        way = (axis[0] / size, axis[1] / size, axis[2] / size)
        motion = Rigid.turn_about((base[0], base[1], base[2]), way, 0.0, 1.0)
        self.turned[solid] = self.step(f"{solid}.turned", "transform", transform_params(motion), item=item,
                                       inputs=(solid,))  # fmt: skip
        return solid

    def seamed(self, solid: str, key: tuple[str, int], *, item: str) -> str:
        """A ball's or a cone's step, turned as the one ``key`` is made (:attr:`seams`), or as it is."""
        turn = self.seams.get(key)
        if turn is None:
            return solid
        from .moved import transform_params

        return self.step(f"{solid}.seam", "transform", transform_params(turn), item=item, inputs=(solid,))

    # -- steps -----------------------------------------------------------------------------
    def step(self, step_id: str, op: str, params: Mapping[str, Any], *, item: str,
             inputs: Sequence[str] = ()) -> str:  # fmt: skip
        if step_id in self.owners:
            raise PlanError(f"two steps would be called {step_id!r}", item=item)
        written: dict[str, Any] = {"id": step_id, "op": op, "params": dict(params),
                                   "for_items": [item]}  # fmt: skip
        if inputs:
            written["inputs"] = [self.turned.get(i, i) for i in inputs]
        self.steps.append(written)
        self.owners[step_id] = self.planning or item
        return step_id

    def box(
        self, step_id: str, lo: Sequence[float], hi: Sequence[float], *, item: str
    ) -> str:
        size = [hi[k] - lo[k] for k in range(3)]
        if min(size) <= 0.0:
            raise PlanError(
                f"a box from {tuple(lo)} to {tuple(hi)} has no inside", item=item
            )
        return self.step(
            step_id, "box", {"size": point(size), "origin": point(lo)}, item=item
        )

    def cylinder(self, step_id: str, base: Sequence[float], axis: Sequence[float],
                 diameter: float, height: float, *, item: str) -> str:  # fmt: skip
        if diameter <= 0.0 or height <= 0.0:
            raise PlanError(
                f"a cylinder {diameter:g} mm across and {height:g} mm long", item=item
            )
        made = self.step(step_id, "cylinder", {
            "diameter": length(diameter), "height": length(height), "origin": point(base),
            "axis": direction(axis)}, item=item)  # fmt: skip
        return self.turned_round(made, base, axis, item=item)

    def cone(self, step_id: str, base: Sequence[float], axis: Sequence[float], bottom: float,
             top: float, height: float, *, item: str) -> str:  # fmt: skip
        made = self.step(step_id, "cone", {
            "bottom_diameter": length(bottom), "top_diameter": length(top), "height": length(height),
            "origin": point(base), "axis": direction(axis)}, item=item)  # fmt: skip
        return self.turned_round(made, base, axis, item=item)

    def sphere(
        self, step_id: str, centre: Sequence[float], diameter: float, *, item: str
    ) -> str:
        return self.step(step_id, "sphere", {"diameter": length(diameter), "origin": point(centre)},
                         item=item)  # fmt: skip

    def boolean(
        self, step_id: str, op: str, operands: Sequence[str], *, item: str
    ) -> str:
        if len(operands) < 2:
            raise PlanError(f"a {op} needs two solids or more", item=item)
        return self.step(step_id, op, {}, item=item, inputs=operands)

    def datum(self, step_id: str, axis: str, offset: float, *, item: str) -> str:
        """The standard plane square to a frame axis, at that coordinate along it."""
        base, _ = DATUMS[axis]
        return self.step(step_id, "datum_plane", {"base": base, "offset": length(offset)},
                         item=item)  # fmt: skip

    def profile(self, step_id: str, op: str, plane: str, params: Mapping[str, Any], *,
                item: str) -> str:  # fmt: skip
        return self.step(step_id, op, params, item=item, inputs=(plane,))

    def axis(
        self,
        step_id: str,
        origin: Sequence[float],
        direction: Sequence[float],
        *,
        item: str,
    ) -> str:
        """A datum axis through ``origin`` along ``direction``."""
        return self.step(step_id, "datum_axis", {"origin": point(origin), "direction": {"vector": [num(c) for c in direction], "unit": ""}},
                         item=item)  # fmt: skip

    def revolve(self, step_id: str, profile: str, axis: str, *, item: str) -> str:
        """A profile turned a full turn about an axis."""
        return self.step(step_id, "revolve", {"angle": {"magnitude": 360.0, "unit": "deg"}}, item=item,
                         inputs=(profile, axis))  # fmt: skip

    def extrude(
        self, step_id: str, profile: str, distance: float, mode: str, *, item: str
    ) -> str:
        if distance <= 0.0:
            raise PlanError(f"an extrusion {distance:g} mm long", item=item)
        return self.step(step_id, "extrude", {"distance": length(distance), "mode": mode},
                         item=item, inputs=(profile,))  # fmt: skip

    # -- the part made so far -----------------------------------------------------------------
    def join(
        self, key: str, tools: Sequence[str], *, item: str, copy: int | None = None
    ) -> None:
        """The part, and every tool joined to it (the first body: the part); ``copy``, one copy's alone (5.1)."""
        if not tools:
            return
        step = f"{key}.join" if copy is None else f"{key}.join.{copy}"
        if self.head is None:
            self.head = (
                tools[0]
                if len(tools) == 1
                else self.boolean(step, "union", tools, item=item)
            )
            return
        self.head = self.boolean(step, "union", [self.head, *tools], item=item)
        self.parts.append(self.head)

    def take(
        self, key: str, tools: Sequence[str], *, item: str, copy: int | None = None
    ) -> None:
        """The part less every tool; ``copy``, one copy's alone (5.1)."""
        if not tools:
            return
        if self.head is None:
            raise PlanError("a cut before any body", item=item)
        step = f"{key}.cut" if copy is None else f"{key}.cut.{copy}"
        self.head = self.boolean(step, "subtract", [self.head, *tools], item=item)
        self.parts.append(self.head)

    def add_box(self, box: Box) -> None:
        """A tool added to the part: its box."""
        self.added.append(box)
        self.note(box)

    def cut_box(self, box: Box) -> None:
        """A tool taken from the part: its box."""
        self.cut.append(box)
        self.note(box)

    def note(self, box: Box) -> None:
        """A box the planned item being written takes up."""
        self.boxes.setdefault(self.planning, []).append(box)

    def name(self, item: str, copy: int, face: str, *refs: Ref) -> None:
        self.faces.setdefault((item, copy), {})[face] = tuple(sorted(set(refs)))

    def names_of(self, item: str, copy: int) -> Mapping[str, tuple[Ref, ...]]:
        return self.faces.get((item, copy), {})

    # -- the document -------------------------------------------------------------------------
    def payload(
        self, *, document_id: str, name: str, material: str | None = None
    ) -> dict[str, Any]:
        if self.head is None:
            raise PlanError("the spec makes nothing")
        if self.steps[-1]["id"] != self.head:
            raise PlanError("the part made so far is not the last step")
        component: dict[str, Any] = {"id": "part", "name": name, "steps": self.steps}
        if material:
            component["material"] = material
        return {"schema_version": "2.0.0", "document_id": document_id, "project_id": "forge",
                "revision": 1, "name": name, "components": [component]}  # fmt: skip

    def document(
        self, *, document_id: str, name: str, material: str | None = None
    ) -> DocumentV2:
        payload = self.payload(document_id=document_id, name=name, material=material)
        return DocumentV2.from_json(json.dumps(payload, sort_keys=True))
