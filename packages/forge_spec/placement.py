"""The placement solver: stated relations to positions in the frame.

It solves only what the spec states. V1's solver also turned boxes over,
guessed which way was up from parameter names, and read V1's own requirement
record; this one does none of that (plan, section 2, cause N). Where the spec
leaves a position open (no position along an axis, no start angle for a bolt
circle), the solver centres it or starts it at 0 degrees and records an
**assumption**, which the person sees first when confirming.

Every body is axis-aligned in this version: the first sits on the origin, and
every other body or feature stands on, or cuts into, a face of something
placed before it. Faces have exactly the names the schema declares for the
kind (:data:`forge_spec.schema.KINDS`). A declared face the solver can't
offer (the face a standing item is joined by, a face a shell leaves open) is
*closed* with the reason, so the writer is told why.

Every field the spec gives is used, or it is a fault: an angle on a flat
face, a pattern value along an axis the face doesn't have, a position along
an axis a pattern already fixes. A value the solver silently dropped would
reach the person as if it had been applied.

Problems are routed by what they rest on (:func:`route`): an impossibility
that follows from the brief's own numbers is the person's (a question, or a
CAN'T); one that rests on a value the spec writer assumed is the writer's to
fix (a fault), so a draft can't end a run as CAN'T on an assumption of its
own. Only the values that bind are blamed: a hole too wide for a plate rests
on the hole's size and the plate's width, not its thickness; one too deep
rests on its depth and the plate's thickness, not its width.

Positions are in millimetres in the frame; directions are unit vectors. The
geometry (faces, outlines, exact fits, overlaps, material) is in
:mod:`forge_spec.geometry`.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from .draft import (
    PATTERN_ANGLES,
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    EdgeSet,
    Faces,
    Fit,
    Item,
    On,
    PartSpec,
    Pattern,
    Place,
    Profile,
    Text,
    Through,
)
from .font import missing_letters, text_width
from .geometry import (
    EPS,
    Dome,
    FlatFace,
    Footprint,
    Less,
    Over,
    Part,
    SideFace,
    Source,
    Taper,
    Turned,
    Vec,
    _parts_overlap,
    add_material,
    bbox,
    copies_overlap,
    disc,
    face_footprint,
    first_close_pair,
    fits_somewhere,
    footprint_on_face,
    inside_hole,
    least_material_under,
    material_at,
    outline_meets_face,
    outline_on_face,
    outline_within,
    reach,
    rect,
    rounded_rect,
    shape_meets_face,
    side_material,
    slot_outline,
    touches_edge,
    uniform,
)
from .letters import ink_box
from .outline import Shape, turned_depth, turned_extremes
from .problems import pointer
from .schema import DIRECTIONS, FACE_AXES, KINDS, Category
from .tables import lookup_fit
from .values import Count, Value
from .values import Source as ValueSource

__all__ = [
    "MAX_COPIES",
    "Assumption",
    "FlatFace",
    "Instance",
    "Issue",
    "Layout",
    "SideFace",
    "edges_of",
    "footing_values",
    "height_of",
    "mm",
    "route",
    "solve",
]

_INDEX = {"x": 0, "y": 1, "z": 2}
#: The most copies of one item Forge places (a perforated sheet is a later stage).
MAX_COPIES = 10_000
#: The kinds a shell can hollow in this version.
_HOLLOWABLE = ("block", "cylinder", "sphere")

Face = FlatFace | SideFace


def _dir(direction: str) -> Vec:
    sign = 1.0 if direction[0] == "+" else -1.0
    v = [0.0, 0.0, 0.0]
    v[_INDEX[direction[1]]] = sign
    return (v[0], v[1], v[2])


def _add(a: Vec, b: Vec, scale: float = 1.0) -> Vec:
    return (a[0] + b[0] * scale, a[1] + b[1] * scale, a[2] + b[2] * scale)


def _opposite(direction: str) -> str:
    return ("-" if direction[0] == "+" else "+") + direction[1]


def _direction_of(vector: Vec) -> str | None:
    for direction in DIRECTIONS:
        if all(abs(a - b) < 1e-9 for a, b in zip(vector, _dir(direction), strict=True)):
            return direction
    return None


def mm(value: Value) -> float:
    """A size as it is made, in mm: the middle of its tolerance (:attr:`~forge_spec.values.Value.made`)."""
    return value.made_in("mm")


def degrees(value: Value) -> float:
    """An angle as it is made, in degrees: the middle of its tolerance."""
    return value.made_in("deg")


@dataclass(frozen=True)
class Issue:
    """Something the solver couldn't settle.

    ``kind`` routes it: ``fault`` back to the spec writer (the draft is
    inconsistent), ``question`` to the person (the brief leaves it open or
    asks for something odd), ``cant`` to a CAN'T ending (it can't be made),
    ``unable`` to an UNABLE ending (Forge can't do it yet).
    """

    kind: str
    at: str
    message: str


@dataclass(frozen=True)
class Assumption:
    at: str
    message: str


@dataclass(frozen=True)
class Instance:
    """One copy of one item, placed."""

    item: str
    index: int
    origin: Vec  # bodies: centre of the base; features: centre on the host face
    normal: (
        Vec  # bodies and standing features: the way they grow; cuts: out of the face
    )
    host: tuple[str, int, str] | None  # (item, instance, face)
    #: The axes its length and width run along: the face's, or round a side (around, along).
    face_axes: tuple[str, str] | None = None
    #: Bodies and standing features: the box round them from where they stand
    #: (round a rod, from their point: the foot that follows the curve below it
    #: is not in it, so the box's size out of the side is the item's height).
    lo: Vec | None = None
    hi: Vec | None = None


def _assumed(value: object) -> bool:
    provenance = getattr(value, "provenance", None)
    return getattr(provenance, "source", None) is ValueSource.ASSUMED


#: Said of a problem sent back to the writer because a value it assumed causes it.
_RESTS_ON_AN_ASSUMPTION = " (it rests on an assumed value: choose one that fits)"


def route(kind: str, values: Iterable[object]) -> str:
    """Where a problem goes, given the values it rests on.

    A question or a CAN'T that rests on an assumed value goes back to the
    spec writer as a fault: it chose the value, so it chooses again.
    """
    if kind in ("cant", "question") and any(_assumed(v) for v in values):
        return "fault"
    return kind


@dataclass
class Layout:
    """Every item placed, with what the solver had to assume or couldn't do."""

    instances: dict[str, list[Instance]] = field(default_factory=dict)
    faces: dict[tuple[str, int], dict[str, Face]] = field(default_factory=dict)
    #: Declared faces that can't be used, with the issue kind and the reason.
    closed: dict[tuple[str, int], dict[str, tuple[str, str]]] = field(
        default_factory=dict
    )
    issues: list[Issue] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    diameters: dict[str, float] = field(default_factory=dict)  # holes: resolved, mm
    kinds: dict[str, str] = field(default_factory=dict)  # item id -> kind
    items: dict[str, Item] = field(default_factory=dict)
    #: Each hollowed body's shell item.
    shells: dict[str, Item] = field(default_factory=dict)
    #: The hollow inside each copy of a shelled block or cylinder: its bounds.
    cavities: dict[tuple[str, int], tuple[Vec, Vec]] = field(default_factory=dict)
    #: Items that couldn't be placed; what stands on them isn't placed either.
    unplaced: set[str] = field(default_factory=set)
    #: What has been placed on each flat face so far, in the order it is made:
    #: the solver's working index, not part of what it solves to.
    footprints: dict[tuple[str, int, str], _Footprints] = field(
        default_factory=dict, compare=False, repr=False
    )
    #: Every item, in the order it is made (docs/definitions/frame.md): a
    #: hollowed body followed by its own roundings and chamfers and then its
    #: shell; every other rounding, chamfer and thread last, in the spec's order.
    order: list[str] = field(default_factory=list)

    def issue(self, kind: str, at: str, message: str) -> None:
        found = Issue(kind, at, message)
        if found not in self.issues:  # copies on several hosts say it once
            self.issues.append(found)

    def problem(
        self, kind: str, at: str, message: str, values: Iterable[object]
    ) -> None:
        """An issue routed by what it rests on (see :func:`route`)."""
        values = list(values)
        routed = route(kind, values)
        self.issue(
            routed, at, message + (_RESTS_ON_AN_ASSUMPTION if routed != kind else "")
        )

    def assume(self, at: str, message: str) -> None:
        found = Assumption(at, message)
        if found not in self.assumptions:
            self.assumptions.append(found)

    def close(self, key: tuple[str, int], face: str, kind: str, why: str) -> None:
        self.faces.get(key, {}).pop(face, None)
        self.closed.setdefault(key, {})[face] = (kind, why)

    def values_of(self, sources: Iterable[Source]) -> list[object]:
        found: list[object] = []
        for item_id, name in sources:
            owner = self.items.get(item_id)
            if owner is not None:
                found += _flatten(owner.get(name))
        return found

    def extent(self) -> tuple[Vec, Vec] | None:
        """The bounds of every body and standing feature together."""
        boxes = [
            (i.lo, i.hi) for xs in self.instances.values() for i in xs if i.lo and i.hi
        ]
        if not boxes:
            return None
        lo = tuple(min(b[0][k] for b in boxes) for k in range(3))
        hi = tuple(max(b[1][k] for b in boxes) for k in range(3))
        return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


# ----------------------------------------------------------------------
# Reading items
# ----------------------------------------------------------------------
def _length_of(item: Item, name: str) -> float | None:
    value = item.get(name)
    return mm(value) if isinstance(value, Value) else None


def _size(item: Item, name: str) -> float:
    return _length_of(item, name) or 0.0


def _choice_of(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _count_of(item: Item) -> int | None:
    value = item.get("count")
    return value.n if isinstance(value, Count) else None


def _place_of(item: Item) -> Place | None:
    place = item.get("place")
    return place if isinstance(place, Place) else None


def _is_through(item: Item) -> bool:
    return isinstance(item.get("depth"), Through)


def height_of(item: Item) -> tuple[float, str] | None:
    """How far a body or standing feature rises out of what it stands on, and the field."""
    for name in {"tab": ("length",), "cylinder": ("length",), "tube": ("length",), "cone": ("length",)}.get(
        item.kind, ("height",)
    ):  # fmt: skip
        value = _length_of(item, name)
        if value is not None:
            return value, name
    if item.kind == "sphere":
        d = _size(item, "diameter")
        return (d / 2 if _choice_of(item, "portion") == "upper_half" else d), "diameter"
    return None


def _outline_fields(
    item: Item, axes: tuple[str, str] | None = None, k: int | None = None
) -> tuple[str, ...]:
    """The fields an item's outline on its face comes from; with ``k``, only along that axis."""
    kind = item.kind
    if kind in ("hole",):
        return ("diameter", "counterbore", "countersink")
    if kind in ("boss", "cylinder", "sphere") or (
        kind == "pocket" and _choice_of(item, "shape") == "circle"
    ):
        return ("diameter",)
    if kind == "cone":
        return ("base_diameter",)
    if kind == "tube":
        return ("outer_diameter",)
    if k is None or axes is None:
        return {"pocket": ("length", "width", "corner_radius"), "post": ("length", "width"),
                "region": ("length", "width"), "block": ("length", "width"), "slot": ("length", "width"),
                "rib": ("length", "thickness"), "tab": ("thickness", "width"),
                "text": ("height", "text")}.get(kind, ())  # fmt: skip
    first = k == 0
    if kind in ("pocket", "post", "region", "block"):
        return ("length",) if first else ("width",)
    if kind in ("slot", "rib"):
        along = _choice_of(item, "along") == axes[k]
        return (
            ("length",) if along else (("width",) if kind == "slot" else ("thickness",))
        )
    if kind == "tab":
        return (
            ("thickness",)
            if _choice_of(item, "thickness_along") == axes[k]
            else ("width",)
        )
    if kind == "text":
        return ("height", "text") if first else ("height",)
    return ()


def _flatten(value: object) -> list[object]:
    if isinstance(value, Counterbore):
        return [value.diameter, value.depth]
    if isinstance(value, Countersink):
        return [value.diameter, value.angle]
    return [value]


def _item_values(item: Item, *names: str) -> list[object]:
    found: list[object] = []
    for name in names:
        found += _flatten(item.get(name))
    return found


def _place_values(item: Item, axis: str | None = None) -> list[object]:
    """The values an item's position comes from; with ``axis``, only those along it.

    An assumed "centred" is not counted: on a symmetric face it is the best
    place there is, so whatever doesn't fit centred fits nowhere else either.
    """
    place = _place_of(item)
    if place is None:
        return []
    found: list[object] = [
        p.distance for a, p in place.axes.items() if axis in (None, a)
    ]
    if place.angle is not None:
        found.append(place.angle)
    pattern = place.pattern
    if pattern is not None:
        for name, value in [*pattern.values.items(), *pattern.counts.items()]:
            along = name[-1] if name[-2:-1] == "_" or name in ("x", "y", "z") else None
            if pattern.kind in ("row", "ends") and name in ("pitch", "inset", "count"):
                along = pattern.axis
            if axis is None or along in (None, axis):
                found.append(value)
    return found


def _turn(degrees: float) -> tuple[float, float]:
    """The cosine and sine of an angle in degrees, exact where they are 0 or 1.

    So copies a quarter turn apart sit exactly on the axes, not 1e-15 off them.
    """
    quarters = degrees / 90
    if abs(quarters - round(quarters)) < 1e-12:
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[round(quarters) % 4]
    t = math.radians(degrees)
    return math.cos(t), math.sin(t)


def footing_values(item: Item, axes: tuple[str, str], k: int) -> list[object]:
    """The values that set how far an item standing on a face reaches along the face's axis ``k``."""
    found = [
        v for name in _outline_fields(item, axes, k) for v in _flatten(item.get(name))
    ]
    return found + _place_values(item, axes[k])


def _depends_on(item: Item) -> set[str]:
    """What must be made before an item: what it stands on or cuts into, is concentric with, or changes."""
    needs: set[str] = set()
    on = item.get("on")
    if isinstance(on, On):
        needs.add(on.item)
    place = _place_of(item)
    if place is not None and place.concentric:
        needs.add(place.concentric)
    of = item.get("of")
    if isinstance(of, str):
        needs.add(of)
    edges = item.get("edges")
    if isinstance(edges, EdgeSet):
        needs.add(edges.of)
        if edges.where_meets:
            needs.add(edges.where_meets)
    return needs


def _order(spec: PartSpec, layout: Layout) -> list[Item]:
    """The order items are made in (docs/definitions/frame.md, "The order the part is made in").

    Each time, the next item is the earliest in the spec whose dependencies
    (what it stands on or cuts into, what it is concentric with, what it
    hollows, rounds or threads) are all made. Items caught in a loop are
    reported once and left out. Iterative, so a long chain can't exhaust the
    stack.
    """
    by_id = {item.id: item for item in spec.items}
    position = {item.id: n for n, item in enumerate(spec.items)}
    needs = {
        item.id: {n for n in _depends_on(item) if n in by_id and n != item.id}
        for item in spec.items
    }
    waiting_on: dict[str, list[str]] = {}
    for item_id, wanted in needs.items():
        for other in wanted:
            waiting_on.setdefault(other, []).append(item_id)
    left = {item_id: len(wanted) for item_id, wanted in needs.items()}
    ready = [position[i] for i, n in left.items() if n == 0]
    heapq.heapify(ready)
    done: list[Item] = []
    while ready:
        item = spec.items[heapq.heappop(ready)]
        done.append(item)
        for later in waiting_on.get(item.id, ()):
            left[later] -= 1
            if left[later] == 0:
                heapq.heappush(ready, position[later])
    if len(done) < len(spec.items):
        made = {item.id for item in done}
        loop = [item.id for item in spec.items if item.id not in made]
        layout.issue("fault", pointer("items"),
                     f"items depend on each other in a loop: {', '.join(loop)}")  # fmt: skip
        layout.unplaced.update(loop)
    return done


# ----------------------------------------------------------------------
# Outlines
# ----------------------------------------------------------------------
def _outline(item: Item, layout: Layout, axes: tuple[str, str]) -> tuple[Part, ...]:
    """The item's outline on the face, centred on its position, in the face's axes."""
    kind = item.kind

    def oriented(along: str | None, long: float, short: float) -> tuple[float, float]:
        return (long, short) if along == axes[0] else (short, long)

    if kind == "hole":
        d = layout.diameters.get(item.id, 0.0)
        for extra in (item.get("counterbore"), item.get("countersink")):
            if isinstance(extra, (Counterbore, Countersink)):
                d = max(d, mm(extra.diameter))
        return (disc(d / 2),)
    if kind == "boss" or (kind == "pocket" and _choice_of(item, "shape") == "circle"):
        return (disc(_size(item, "diameter") / 2),)
    if kind == "pocket":
        h1, h2 = _size(item, "length") / 2, _size(item, "width") / 2
        return rounded_rect(h1, h2, min(_size(item, "corner_radius"), h1, h2))
    if kind in ("block", "post", "region"):
        return (rect(_size(item, "length") / 2, _size(item, "width") / 2),)
    if kind in ("cylinder", "cone", "sphere"):
        return (disc(max(_size(item, "diameter"), _size(item, "base_diameter")) / 2),)
    if kind == "tube":
        return (disc(_size(item, "outer_diameter") / 2),)
    if kind == "slot":
        length, width = _size(item, "length"), _size(item, "width")
        along_first = _choice_of(item, "along") == axes[0]
        if _choice_of(item, "ends") != "round" or length < width:
            return (rect(*oriented(_choice_of(item, "along"), length / 2, width / 2)),)
        return slot_outline(length, width, along_first=along_first)
    if kind == "rib":
        return (rect(*oriented(_choice_of(item, "along"), _size(item, "length") / 2,
                                _size(item, "thickness") / 2)),)  # fmt: skip
    if kind == "tab":
        thin, wide = _size(item, "thickness") / 2, _size(item, "width") / 2
        return (rect(*oriented(_choice_of(item, "thickness_along"), thin, wide)),)
    if kind == "text":
        # The line's box in the pinned font: its letters' advances, a capital
        # tall (docs/definitions/text.md). Letters the font lacks are the
        # spec checks' to report; here they take no room.
        text = item.get("text")
        letters = text.text if isinstance(text, Text) else ""
        height = _size(item, "height")
        width = text_width(
            "".join(ch for ch in letters if not missing_letters(ch)), height
        )
        return (rect(width / 2, height / 2),)
    return ()


def _covered(item: Item, layout: Layout, face: FlatFace) -> tuple[Part, ...]:
    """What an item covers on a flat face, for its fit and what it meets: its outline; letters, their ink's box.

    A line of letters is placed by its box (text.md), but its ink reaches
    past it (a j's tail, an f's hook): the ink's box (forge_spec.letters) is
    what must lie on the face and clear of what else is on it
    (docs/V2-stage4.md, 7.1). The letters run left to right along up (the
    face's second axis) cross outward.
    """
    if item.kind != "text":
        return _outline(item, layout, face.axes)
    text = item.get("text")
    letters = "".join(
        ch
        for ch in (text.text if isinstance(text, Text) else "")
        if not missing_letters(ch)
    )
    height = _size(item, "height")
    ink = ink_box(letters, height)
    if ink is None:
        return ()
    (x0, y0), (x1, y1) = ink
    up, out = _dir("+" + face.axes[1]), _dir(face.normal)
    right = (
        up[1] * out[2] - up[2] * out[1],
        up[2] * out[0] - up[0] * out[2],
        up[0] * out[1] - up[1] * out[0],
    )
    sign = right[_INDEX[face.axes[0]]]
    middle = text_width(letters, height) / 2
    return (
        rect(
            (x1 - x0) / 2,
            (y1 - y0) / 2,
            sign * ((x0 + x1) / 2 - middle),
            (y0 + y1) / 2 - height / 2,
        ),
    )


def _profile_shape(item: Item) -> Shape | None:
    """An extrusion's outline, or a revolution's half outline, as the solver reasons with it."""
    profile = item.get("profile")
    return Shape.of_profile(profile) if isinstance(profile, Profile) else None


def _reaches(item: Item) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """How far an extrusion or a revolution reaches back and forth along a face's two axes from the point it stands at."""
    shape = _profile_shape(item)
    if shape is None or item.kind not in ("extrusion", "revolution"):
        return None
    (l1, l2), (h1, h2) = shape.box()
    if item.kind == "extrusion":
        return (l1, h1), (l2, h2)
    return (-h1, h1), (-h1, h1)


def _footing(item: Item) -> Shape | None:
    """What of an extrusion or a revolution meets the face it stands on: its outline; the end at a revolution's height 0."""
    shape = _profile_shape(item)
    if shape is None:
        return None
    if item.kind == "extrusion":
        return shape
    end = turned_extremes(shape, False)
    if end is None or abs(end[0]) > EPS:
        return None
    return Shape.disc((0.0, 0.0), end[2])


def _check_shape(item: Item, at: str, layout: Layout) -> None:
    """What can't be true of an item's own sizes, wherever it is placed."""
    if item.kind == "revolution":
        shape = _profile_shape(item)
        if shape is not None:
            (lo, _hi) = shape.box()
            if lo[0] < -EPS:
                layout.issue("fault", at + pointer("profile"),
                             f"a revolution's outline is a half outline: its first coordinate, the distance from the axis, is "
                             f"never below 0, but it reaches {-lo[0]:g} mm across the axis")  # fmt: skip
            elif isinstance(item.get("on"), On):
                if lo[1] < -EPS:
                    layout.issue("fault", at + pointer("profile"), f"standing on a face, {item.id}'s outline reaches "
                                 f"{-lo[1]:g} mm below it: nothing reaches behind the face it stands on")  # fmt: skip
                elif _footing(item) is None:
                    layout.issue("fault", at + pointer("profile"), f"standing on a face, {item.id} must meet it: its "
                                 "outline runs straight across the axis at height 0")  # fmt: skip
    if item.kind == "pocket" and _choice_of(item, "shape") == "rectangle":
        radius = _length_of(item, "corner_radius")
        length, width = _size(item, "length"), _size(item, "width")
        if radius is not None and radius > min(length, width) / 2 + EPS:
            layout.problem("cant", at + pointer("corner_radius"),
                           f"a {radius:g} mm corner radius doesn't fit a {length:g} x {width:g} mm pocket "
                           f"(at most {min(length, width) / 2:g} mm)",
                           _item_values(item, "corner_radius", "width" if width < length else "length"))  # fmt: skip
    if item.kind == "tab" and _choice_of(item, "end") == "round":
        length, width = _size(item, "length"), _size(item, "width")
        if length < width / 2 - EPS:
            layout.problem("cant", at + pointer("length"),
                           f"a fully round end needs the tab to stick out at least half its width "
                           f"({width / 2:g} mm); it sticks out {length:g} mm",
                           _item_values(item, "length", "width", "end"))  # fmt: skip
    if item.kind == "slot":
        length, width = _size(item, "length"), _size(item, "width")
        if length < width - EPS:
            layout.problem("cant", at + pointer("length"),
                           f"a slot's overall length ({length:g} mm) can't be less than its width ({width:g} mm)",
                           _item_values(item, "length", "width"))  # fmt: skip
    if item.kind == "hole":
        bore, sink, depth = (
            item.get("counterbore"),
            item.get("countersink"),
            item.get("depth"),
        )
        if isinstance(bore, Counterbore) and isinstance(sink, Countersink):
            layout.issue(
                "unable",
                at,
                "a hole with both a counterbore and a countersink isn't built yet",
            )
        if (
            isinstance(bore, Counterbore)
            and isinstance(depth, Value)
            and mm(bore.depth) >= mm(depth) - EPS
        ):
            layout.problem("question", at + pointer("counterbore"),
                           f"the counterbore ({mm(bore.depth):g} mm deep) is as deep as the hole ({mm(depth):g} mm): "
                           "there's no hole left below it", [bore.depth, depth])  # fmt: skip
        hole = layout.diameters.get(item.id)
        if (
            isinstance(sink, Countersink)
            and isinstance(depth, Value)
            and hole is not None
        ):
            cone = (
                (mm(sink.diameter) - hole)
                / 2
                / math.tan(math.radians(degrees(sink.angle)) / 2)
            )
            if cone >= mm(depth) - EPS:
                layout.problem("question", at + pointer("countersink"),
                               f"the countersink ({cone:g} mm deep) is as deep as the hole ({mm(depth):g} mm): "
                               "there's no hole left below it",
                               [sink.diameter, sink.angle, item.get("diameter"), depth])  # fmt: skip


def _resolve_diameter(item: Item, at: str, layout: Layout) -> None:
    diameter = item.get("diameter")
    if isinstance(diameter, Value):
        layout.diameters[item.id] = mm(diameter)
    elif isinstance(diameter, Fit):
        entry = lookup_fit(diameter.fit, diameter.for_, diameter.grade or "normal")
        if entry is None:
            layout.issue("fault", at + pointer("diameter"),
                         f"no {diameter.fit} entry for {diameter.for_!r} in Forge's tables")  # fmt: skip
        else:
            layout.diameters[item.id] = entry.size_mm


# ----------------------------------------------------------------------
# Faces of placed items
# ----------------------------------------------------------------------
def _box_faces(
    lo: Vec, hi: Vec, item_id: str, fields: Mapping[str, str]
) -> dict[str, Face]:
    """A box's six faces; ``fields`` names the item's field for its size along each axis."""
    faces: dict[str, Face] = {}
    for direction, (a1, a2) in FACE_AXES.items():
        k = _INDEX[direction[1]]
        centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
        centre[k] = hi[k] if direction[0] == "+" else lo[k]
        half = (
            (hi[_INDEX[a1]] - lo[_INDEX[a1]]) / 2,
            (hi[_INDEX[a2]] - lo[_INDEX[a2]]) / 2,
        )

        def along(axis: str) -> tuple[Source, ...]:
            return ((item_id, fields[axis]),) if axis in fields else ()

        faces[direction] = FlatFace(
            direction, (centre[0], centre[1], centre[2]), direction, (a1, a2), "rect", half, 0.0,
            hi[k] - lo[k], axis_sources=(along(a1), along(a2)), depth_sources=along(direction[1]),
        )  # fmt: skip
    return faces


def _round_faces(item: Item, base: Vec, up: str, length: float, outer_r: float,
                 top_r: float | None = None, inner_r: float = 0.0) -> dict[str, Face]:  # fmt: skip
    """A round body's ends and side: a cylinder, tube, boss or cone."""
    axis = up[1]
    top = _add(base, _dir(up), length)
    down = _opposite(up)
    a1, a2 = FACE_AXES[up]
    shape = "annulus" if inner_r > 0 else "disc"
    top_radius = outer_r if top_r is None else top_r
    diameters = tuple(
        (item.id, n)
        for n in (
            "diameter",
            "outer_diameter",
            "inner_diameter",
            "base_diameter",
            "top_diameter",
        )
        if item.get(n) is not None
    )
    lengths = tuple(
        (item.id, n) for n in ("length", "height") if item.get(n) is not None
    )
    cone = top_r is not None and abs(top_radius - outer_r) > EPS
    both = (diameters, diameters)
    faces: dict[str, Face] = {}
    if top_radius > EPS:
        model = (
            Taper(outer_r, top_radius, length)
            if cone and top_radius > outer_r
            else None
        )
        faces["+end"] = FlatFace("+end", top, up, (a1, a2), shape, (top_radius, top_radius), inner_r, length,
                                 depth_model=model, axis_sources=both, depth_sources=lengths + (diameters if cone else ()))  # fmt: skip
    model = (
        Taper(top_radius, outer_r, length) if cone and outer_r > top_radius else None
    )
    faces["-end"] = FlatFace("-end", base, down, (a1, a2), shape, (outer_r, outer_r), inner_r, length,
                             depth_model=model, axis_sources=both, depth_sources=lengths + (diameters if cone else ()))  # fmt: skip
    start = base if up[0] == "+" else top
    if not cone:
        wall = (outer_r - inner_r) if inner_r > 0 else 2 * outer_r
        faces["side"] = SideFace("side", axis, start, length, outer_r, True, wall,
                                 radius_sources=diameters, length_sources=lengths, depth_sources=diameters)  # fmt: skip
    if inner_r > 0:
        faces["bore"] = SideFace("bore", axis, start, length, inner_r, False, outer_r - inner_r,
                                 radius_sources=diameters, length_sources=lengths, depth_sources=diameters)  # fmt: skip
    return faces


def _bounds_round(base: Vec, up: str, length: float, radius: float) -> tuple[Vec, Vec]:
    top = _add(base, _dir(up), length)
    lo, hi = [0.0] * 3, [0.0] * 3
    k = _INDEX[up[1]]
    for i in range(3):
        if i == k:
            lo[i], hi[i] = min(base[i], top[i]), max(base[i], top[i])
        else:
            lo[i], hi[i] = base[i] - radius, base[i] + radius
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _bounds_box(
    base: Vec, up: str, along: Mapping[str, float], height: float
) -> tuple[Vec, Vec]:
    """Bounds of a box whose base centre is ``base``, growing ``height`` along ``up``."""
    lo, hi = list(base), list(base)
    for axis, size in along.items():
        k = _INDEX[axis]
        lo[k], hi[k] = base[k] - size / 2, base[k] + size / 2
    k = _INDEX[up[1]]
    end = base[k] + height * (1 if up[0] == "+" else -1)
    lo[k], hi[k] = min(base[k], end), max(base[k], end)
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _with(face: Face, **changes: object) -> Face:
    return replace(face, **changes)  # type: ignore[arg-type]


def _standing(item: Item, inst: Instance, up: str, layout: Layout, at: str,
              host: str | None, host_face: Face | None, host_depth: tuple[Source, ...]) -> Instance:  # fmt: skip
    """Bounds and faces of a body or feature standing on a face (or on the origin).

    The faces get exactly the names the schema declares for the kind; the face
    joined to the host, and faces that aren't flat or can't be placed on yet,
    are closed with the reason. A standing item's far face has its own height
    of material and, at a point over its host's face, the host's material
    there too (frame.md: :class:`~forge_spec.geometry.Over`); round a side,
    the side's under all of it. A hollowed body's far face has its wall alone.
    Its length runs along the first of ``inst.face_axes`` (round a round side:
    around it) and its width along the second.
    """
    kind = item.kind
    base = inst.origin
    a1, a2 = inst.face_axes or FACE_AXES[up]
    key = (item.id, inst.index)
    fields: dict[str, str] = {}
    joined = _opposite(up)
    round_kind = kind in ("cylinder", "boss", "cone", "tube", "sphere")
    if kind in ("block", "post", "region"):
        sizes = {a1: _size(item, "length"), a2: _size(item, "width")}
        lo, hi = _bounds_box(base, up, sizes, _size(item, "height"))
        fields = {a1: "length", a2: "width", up[1]: "height"}
        layout.faces[key] = (
            {} if kind == "region" else _box_faces(lo, hi, item.id, fields)
        )
        far = up
    elif kind == "rib":
        along = _choice_of(item, "along") or a1
        other = a2 if along == a1 else a1
        sizes = {along: _size(item, "length"), other: _size(item, "thickness")}
        lo, hi = _bounds_box(base, up, sizes, _size(item, "height"))
        fields = {along: "length", other: "thickness", up[1]: "height"}
        layout.faces[key] = _box_faces(lo, hi, item.id, fields)
        far = up
    elif kind == "tab":
        lo, hi = _tab(item, base, up, (a1, a2), key, layout)
        far = up
    elif kind in ("cylinder", "boss", "cone", "tube"):
        length = _length_of(item, "length") or _size(item, "height")
        outer = (_length_of(item, "diameter") or _length_of(item, "outer_diameter")
                 or _size(item, "base_diameter")) / 2  # fmt: skip
        top = _length_of(item, "top_diameter")
        inner = _size(item, "inner_diameter") / 2
        # A cone wider at its top than its base is as wide as its top.
        lo, hi = _bounds_round(base, up, length, max(outer, (top or 0.0) / 2))
        layout.faces[key] = _round_faces(item, base, up, length, outer,
                                         None if top is None else top / 2, inner)  # fmt: skip
        if kind == "cone":
            layout.close(key, "side", "unable",
                         f"{item.id}'s side is tapered; Forge places on a cone's ends only, for now")  # fmt: skip
            if "+end" not in layout.faces[key]:
                layout.close(
                    key,
                    "+end",
                    "fault",
                    f"{item.id} comes to a point; it has no +end face",
                )
        far = "+end"
    elif kind == "sphere":
        d = _size(item, "diameter")
        half = _choice_of(item, "portion") == "upper_half"
        if half:
            lo, hi = _bounds_round(base, up, d / 2, d / 2)
            diameter = ((item.id, "diameter"),)
            flat = FlatFace("-end", base, joined, FACE_AXES[up], "disc", (d / 2, d / 2), 0.0, d / 2,
                            depth_model=Dome(d / 2), axis_sources=(diameter, diameter),
                            depth_sources=diameter)  # fmt: skip
            layout.faces[key] = {"-end": flat}
        else:
            # A whole ball standing on a face is centred on it, not touching it at a point.
            centre = base if host is not None else _add(base, _dir(up), d / 2)
            lo = (centre[0] - d / 2, centre[1] - d / 2, centre[2] - d / 2)
            hi = (centre[0] + d / 2, centre[1] + d / 2, centre[2] + d / 2)
            layout.faces[key] = {}
            layout.close(
                key, "-end", "fault", f"{item.id} is a whole ball; it has no flat face"
            )
        layout.close(key, "surface", "unable",
                     f"{item.id}'s surface is curved; Forge places on a ball's flat face only, for now")  # fmt: skip
        far = ""
    elif kind in ("extrusion", "revolution"):
        lo, hi = _profiled(item, base, up, (a1, a2), key, layout)
        far = "+end"
    else:
        lo, hi = base, base
        layout.faces[key] = {}
        far = ""
    faces = layout.faces[key]
    top_face = faces.get(far)
    hollowed = item.id in layout.shells and KINDS[kind].category is Category.BODY
    if isinstance(top_face, FlatFace) and host_face is not None and not hollowed:
        sources = top_face.depth_sources + host_depth
        if isinstance(host_face, FlatFace):
            # Faces facing the same way share their axes (FACE_AXES), so a footprint on one is one on the other.
            assert host_face.axes == top_face.axes, (host_face.axes, top_face.axes)
            i1, i2 = (_INDEX[a] for a in top_face.axes)
            on_host = (
                top_face.centre[i1] - host_face.centre[i1],
                top_face.centre[i2] - host_face.centre[i2],
            )
            # Wholly over a host with the same material under all of it: that, under all of it too.
            if uniform(host_face) and footprint_on_face(
                host_face, face_footprint(top_face), *on_host
            ):
                found = add_material(top_face, host_face.depth_below)
            else:
                found = replace(top_face, over=Over(host_face, on_host))
        else:  # round a side, the side's material is under all of it
            found = add_material(top_face, host_face.wall)
        faces[far] = replace(found, depth_sources=sources)
    if host is not None:
        face = "-end" if round_kind or kind in ("extrusion", "revolution") else joined
        if face in KINDS[kind].faces:
            layout.close(
                key, face, "fault", f"{item.id}'s {face} face is joined to {host}"
            )
        else:  # a boss is always joined by its foot: its kind has no such face
            faces.pop(face, None)
    if item.id in layout.shells and KINDS[kind].category is Category.BODY:
        _hollow(item, key, lo, hi, up, layout, fields if kind == "block" else {})
    for name in KINDS[kind].faces:
        if (
            name.startswith("inner ")
            and name not in faces
            and name not in layout.closed.get(key, {})
        ):
            layout.close(
                key,
                name,
                "fault",
                f"only a hollowed {kind} has inner faces; nothing hollows {item.id}",
            )
    return Instance(
        inst.item, inst.index, base, _dir(up), inst.host, inst.face_axes, lo, hi
    )


def _profiled(item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int],
              layout: Layout) -> tuple[Vec, Vec]:  # fmt: skip
    """An extrusion's or a revolution's bounds and flat ends (extrusion.md, revolution.md; docs/V2-stage4.md, 6.6).

    An extrusion's ends are its outline, in ``axes`` from ``base``, its -end
    at ``base`` and its +end ``length`` along ``up``; each is centred on its
    box's middle, and has the length under it. A revolution turns its half
    outline about ``up`` through ``base``, heights along it: an end where the
    outline runs straight across the axis at its greatest (least) height, a
    disc or a ring, the material under it worked out from the outline
    (:class:`~forge_spec.geometry.Turned`). Their sides take nothing yet.
    """
    shape = _profile_shape(item)
    layout.faces[key] = {}
    if shape is None:
        return base, base
    a1, a2 = axes
    k1, k2, kz = _INDEX[a1], _INDEX[a2], _INDEX[up[1]]
    sign = 1.0 if up[0] == "+" else -1.0
    down = _opposite(up)
    sources = ((item.id, "profile"),)

    def point(u: float, v: float, h: float) -> Vec:
        found = list(base)
        found[k1] += u
        found[k2] += v
        found[kz] += sign * h
        return (found[0], found[1], found[2])

    (l1, l2), (h1, h2) = shape.box()
    faces: dict[str, Face] = {}
    if item.kind == "extrusion":
        length = _size(item, "length")
        c1, c2 = (l1 + h1) / 2, (l2 + h2) / 2
        outline = shape.moved(-c1, -c2)
        half = ((h1 - l1) / 2, (h2 - l2) / 2)
        lengths = ((item.id, "length"),)
        for name, height, normal in (("+end", length, up), ("-end", 0.0, down)):
            faces[name] = FlatFace(name, point(c1, c2, height), normal, FACE_AXES[normal], "profile", half, 0.0,
                                   length, axis_sources=(sources, sources), depth_sources=lengths,
                                   profile=outline)  # fmt: skip
        corners = (point(l1, l2, 0.0), point(h1, h2, length))
    else:
        for name, top in (("+end", True), ("-end", False)):
            end = turned_extremes(shape, top)
            if end is None:
                layout.close(key, name, "fault", f"{item.id}'s outline doesn't run straight across its axis at its "
                             f"{'greatest' if top else 'least'} height: it has no flat {name}")  # fmt: skip
                continue
            height, inner, outer = end
            normal = up if top else down
            ring = inner > EPS
            faces[name] = FlatFace(name, point(0.0, 0.0, height), normal, FACE_AXES[normal],
                                   "annulus" if ring else "disc", (outer, outer), inner if ring else 0.0,
                                   turned_depth(shape, top, inner, outer)[1], depth_model=Turned(shape, top),
                                   axis_sources=(sources, sources), depth_sources=sources)  # fmt: skip
        corners = (point(-h1, -h1, l2), point(h1, h1, h2))
    layout.faces[key] = faces
    layout.close(key, "side", "unable",
                 f"{item.id}'s side is its outline swept; Forge places on its flat ends only, for now")  # fmt: skip
    lo = (
        min(corners[0][0], corners[1][0]),
        min(corners[0][1], corners[1][1]),
        min(corners[0][2], corners[1][2]),
    )
    hi = (
        max(corners[0][0], corners[1][0]),
        max(corners[0][1], corners[1][1]),
        max(corners[0][2], corners[1][2]),
    )
    return lo, hi


def _tab(item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int],
         layout: Layout) -> tuple[Vec, Vec]:  # fmt: skip
    """A tab's bounds and faces; a round end rounds two corners of its flat faces."""
    a1, a2 = axes
    thin = _choice_of(item, "thickness_along") or a2
    wide = a1 if thin == a2 else a2
    thickness, width, length = (
        _size(item, "thickness"),
        _size(item, "width"),
        _size(item, "length"),
    )
    sizes = {thin: thickness, wide: width}
    lo, hi = _bounds_box(base, up, sizes, length)
    fields = {thin: "thickness", wide: "width", up[1]: "length"}
    faces = _box_faces(lo, hi, item.id, fields)
    layout.faces[key] = faces
    if _choice_of(item, "end") != "round":
        return lo, hi
    radius = width / 2
    layout.close(key, up, "unable",
                 f"{item.id}'s round end is curved; Forge places on its flat faces only, for now")  # fmt: skip
    straight = length - radius
    for side in ("+" + wide, "-" + wide):
        if straight > EPS:
            faces[side] = _box_faces(
                *_bounds_box(base, up, sizes, straight), item.id, fields
            )[side]
        else:
            layout.close(key, side, "fault",
                         f"{item.id} is all round end ({length:g} mm long, {width:g} mm wide): it has no {side} face")  # fmt: skip
    for side in ("+" + thin, "-" + thin):
        flat = faces[side]
        assert isinstance(flat, FlatFace)
        k = flat.axes.index(up[1])  # the round end is along this axis of the face
        sign = 1 if up[0] == "+" else -1
        # The two corners at the far end are each a quarter of the half-circle:
        # as big as half the width, and as long as the tab allows.
        size = min(radius, 2 * flat.half[k], flat.half[1 - k])
        corners = tuple(size if (s1, s2)[k] == sign else 0.0
                        for s1, s2 in ((1, 1), (-1, 1), (-1, -1), (1, -1)))  # fmt: skip
        faces[side] = _with(
            flat, corners=(corners[0], corners[1], corners[2], corners[3])
        )
    return lo, hi


def _hollow(item: Item, key: tuple[str, int], lo: Vec, hi: Vec, up: str, layout: Layout,
            fields: Mapping[str, str]) -> None:  # fmt: skip
    """Apply a shell: open faces closed, walls as the material, and the inside faces."""
    shell = layout.shells[item.id]
    shell_at = pointer("items", list(layout.items).index(shell.id))
    thickness_value, floor_value = shell.get("thickness"), shell.get("floor")
    opened = shell.get("open")
    open_faces = set(opened.faces) if isinstance(opened, Faces) else set()
    if not isinstance(thickness_value, Value):
        return
    t = mm(thickness_value)
    f = mm(floor_value) if isinstance(floor_value, Value) else t
    if item.kind not in _HOLLOWABLE:
        layout.issue("unable", shell_at,
                     f"Forge hollows blocks, cylinders and balls for now, not a {item.kind}")  # fmt: skip
        return
    outer = {
        "block": set(DIRECTIONS),
        "cylinder": {"+end", "-end"},
        "sphere": {"-end"},
    }[item.kind]
    if item.kind == "sphere" and _choice_of(item, "portion") != "upper_half":
        outer = set()
    bad = sorted(open_faces - outer)
    if bad:
        layout.issue("fault", shell_at + pointer("open"),
                     f"a shell of {item.id} can leave open {sorted(outer) or 'nothing'}, not {bad}")  # fmt: skip
        return
    opposite = {"+end": "-end", "-end": "+end"}
    floored = [o for o in open_faces if opposite.get(o, _opposite(o)) not in open_faces]
    if (
        isinstance(floor_value, Value)
        and item.kind == "sphere"
        and (not outer or "-end" in open_faces)
    ):
        # A dome's floor is its flat face's wall; a whole ball, or a dome
        # open underneath, has none (docs/definitions/shell.md).
        layout.issue("fault", shell_at + pointer("floor"),
                     f"{item.id} is " + ("a whole ball" if not outer else "open underneath")
                     + ": its hollow has no floor; leave the floor out")  # fmt: skip
        return
    if (
        isinstance(floor_value, Value)
        and item.kind in ("block", "cylinder")
        and not floored
    ):
        layout.issue("fault", shell_at + pointer("floor"),
                     f"a floor is the wall opposite an opening, and {shell.id} has "
                     + ("no opening" if not open_faces else f"none with a wall opposite ({sorted(open_faces)})")
                     + ": leave the floor out")  # fmt: skip
        return
    faces = layout.faces[key]
    for name in sorted(open_faces):
        layout.close(key, name, "unable",
                     f"{shell.id} leaves {item.id}'s {name} open: Forge doesn't place on the rim of an open hollow "
                     "yet; stand things on its inner faces")  # fmt: skip
    walls = ((shell.id, "thickness"), (shell.id, "floor"))

    def wall(name: str, opposite: str) -> float:
        if name in open_faces:
            return 0.0
        return f if opposite in open_faces else t

    if item.kind == "block":
        th = {d: wall(d, _opposite(d)) for d in DIRECTIONS}
        cavity_lo = [lo[i] + th["-" + "xyz"[i]] for i in range(3)]
        cavity_hi = [hi[i] - th["+" + "xyz"[i]] for i in range(3)]
        shut = [a for i, a in enumerate("xyz") if cavity_hi[i] - cavity_lo[i] <= EPS]
        if shut:
            layout.problem("cant", shell_at + pointer("thickness"),
                           f"{t:g} mm walls leave no hollow inside {item.id} along {', '.join(shut)}",
                           [thickness_value, floor_value, *_item_values(item, *(fields.get(a, "height") for a in shut))])  # fmt: skip
            return
        layout.cavities[key] = ((cavity_lo[0], cavity_lo[1], cavity_lo[2]),
                                (cavity_hi[0], cavity_hi[1], cavity_hi[2]))  # fmt: skip
        for d in DIRECTIONS:
            face = faces.get(d)
            if isinstance(face, FlatFace):
                faces[d] = _with(face, depth_below=th[d], depth_sources=walls)
            inner = f"inner {d}"
            if d in open_faces:
                layout.close(
                    key,
                    inner,
                    "fault",
                    f"{item.id}'s {d} side is open: it has no wall there",
                )
                continue
            k = _INDEX[d[1]]
            a1, a2 = FACE_AXES[d]
            centre = [(cavity_lo[i] + cavity_hi[i]) / 2 for i in range(3)]
            centre[k] = cavity_hi[k] if d[0] == "+" else cavity_lo[k]
            half = ((cavity_hi[_INDEX[a1]] - cavity_lo[_INDEX[a1]]) / 2,
                    (cavity_hi[_INDEX[a2]] - cavity_lo[_INDEX[a2]]) / 2)  # fmt: skip
            room = (
                math.inf if _opposite(d) in open_faces else cavity_hi[k] - cavity_lo[k]
            )
            own = (item.id, fields.get(a1, "")), (item.id, fields.get(a2, ""))
            faces[inner] = FlatFace(inner, (centre[0], centre[1], centre[2]), _opposite(d), (a1, a2), "rect", half,
                                    0.0, th[d], axis_sources=((own[0], *walls), (own[1], *walls)),
                                    depth_sources=walls, room=room,
                                    room_sources=((item.id, fields.get(d[1], "")), *walls))  # fmt: skip
        return
    if item.kind == "cylinder":
        radius = (hi[_INDEX[FACE_AXES[up][0]]] - lo[_INDEX[FACE_AXES[up][0]]]) / 2
        length = _size(item, "length")
        top, bottom = wall("+end", "-end"), wall("-end", "+end")
        if radius - t <= EPS or length - top - bottom <= EPS:
            layout.problem("cant", shell_at + pointer("thickness"),
                           f"{t:g} mm walls leave no hollow inside {item.id}",
                           [thickness_value, floor_value, *_item_values(item, "diameter" if radius - t <= EPS else "length")])  # fmt: skip
            return
        for name, depth in (("+end", top), ("-end", bottom)):
            face = faces.get(name)
            if isinstance(face, FlatFace):
                faces[name] = _with(face, depth_below=depth, depth_sources=walls)
        side = faces.get("side")
        if isinstance(side, SideFace):
            faces["side"] = _with(side, wall=t, depth_sources=walls)
        k = _INDEX[up[1]]
        sign = 1.0 if up[0] == "+" else -1.0  # from the -end towards the +end
        plus_end, minus_end = (hi[k], lo[k]) if sign > 0 else (lo[k], hi[k])
        inner_plus, inner_minus = plus_end - sign * top, minus_end + sign * bottom
        centre_line = [(lo[i] + hi[i]) / 2 for i in range(3)]
        a1, a2 = FACE_AXES[up]
        diameter = ((item.id, "diameter"), *walls)
        inner_length = length - top - bottom
        for name, depth, where, normal, far in (("inner +end", top, inner_plus, _opposite(up), "-end"),
                                                ("inner -end", bottom, inner_minus, up, "+end")):  # fmt: skip
            if depth == 0.0:
                layout.close(
                    key,
                    name,
                    "fault",
                    f"{item.id}'s {name[6:]} is open: it has no wall there",
                )
                continue
            position = list(centre_line)
            position[k] = where
            room = math.inf if far in open_faces else inner_length
            faces[name] = FlatFace(name, (position[0], position[1], position[2]), normal, (a1, a2), "disc",
                                   (radius - t, radius - t), 0.0, depth, axis_sources=(diameter, diameter),
                                   depth_sources=walls, room=room,
                                   room_sources=((item.id, "length"), *walls))  # fmt: skip
        start = list(centre_line)
        start[k] = min(inner_plus, inner_minus)
        inner_lo = [centre_line[i] - (radius - t) for i in range(3)]
        inner_hi = [centre_line[i] + (radius - t) for i in range(3)]
        inner_lo[k], inner_hi[k] = (
            min(inner_plus, inner_minus),
            max(inner_plus, inner_minus),
        )
        layout.cavities[key] = (
            (inner_lo[0], inner_lo[1], inner_lo[2]),
            (inner_hi[0], inner_hi[1], inner_hi[2]),
        )
        faces["inner side"] = SideFace("inner side", up[1], (start[0], start[1], start[2]), inner_length,
                                       radius - t, False, t, radius_sources=diameter,
                                       length_sources=((item.id, "length"), *walls), depth_sources=walls)  # fmt: skip
        return
    # A ball, or a dome.
    radius = _size(item, "diameter") / 2
    dome = _choice_of(item, "portion") == "upper_half"
    room_left = radius - t - (0.0 if not dome or "-end" in open_faces else f)
    if room_left <= EPS:
        layout.problem("cant", shell_at + pointer("thickness"), f"{t:g} mm walls leave no hollow inside {item.id}",
                       [thickness_value, floor_value, *_item_values(item, "diameter")])  # fmt: skip
        return
    flat = faces.get("-end")
    if isinstance(flat, FlatFace) and "-end" not in open_faces:
        faces["-end"] = _with(
            flat, depth_below=f, depth_model=None, depth_sources=walls
        )


def _pocket_bottom(item: Item, copy: Instance, face: FlatFace, material: float,
                   key: tuple[str, int], layout: Layout) -> None:  # fmt: skip
    """The floor of a pocket, a face other features can go into."""
    depth = item.get("depth")
    layout.faces.setdefault(key, {})
    if not isinstance(depth, Value):
        layout.close(
            key, "bottom", "fault", f"{item.id} goes through; it has no bottom"
        )
        return
    deep = mm(depth)
    if deep >= material - EPS:
        # As deep as the material: it breaks through and leaves no floor. The
        # brief may say both, so who settles it depends on where they came from.
        kind = route("question", [depth, *layout.values_of(face.depth_sources)])
        layout.close(key, "bottom", kind,
                     f"{item.id} ({deep:g} mm deep) goes right through the {material:g} mm of material; "
                     "it has no bottom" + (_RESTS_ON_AN_ASSUMPTION if kind != "question" else ""))  # fmt: skip
        return
    if face.shape == "annulus":
        i1, i2 = (_INDEX[a] for a in face.axes)
        p1, p2 = copy.origin[i1] - face.centre[i1], copy.origin[i2] - face.centre[i2]
        if not outline_on_face(face, _outline(item, layout, face.axes), p1, p2):
            # It covers the ring's opening: the bore runs on through its floor.
            layout.close(key, "bottom", "unable",
                         f"{item.id}'s floor has the bore through it: Forge doesn't place on that yet")  # fmt: skip
            return
    centre = _add(copy.origin, _dir(face.normal), -deep)
    i1, i2 = (_INDEX[a] for a in face.axes)
    less = Less(
        face, (centre[i1] - face.centre[i1], centre[i2] - face.centre[i2]), deep
    )
    sizes = tuple(
        (item.id, n) for n in ("length", "width", "diameter", "corner_radius")
    )
    depths = ((item.id, "depth"), *face.depth_sources)
    if _choice_of(item, "shape") == "circle":
        r = _size(item, "diameter") / 2
        diameter = ((item.id, "diameter"),)
        floor = FlatFace("bottom", centre, face.normal, face.axes, "disc", (r, r), 0.0, material - deep,
                         axis_sources=(diameter, diameter), depth_sources=depths, less=less)  # fmt: skip
    else:
        h1, h2 = _size(item, "length") / 2, _size(item, "width") / 2
        radius = min(_size(item, "corner_radius"), h1, h2)
        floor = FlatFace("bottom", centre, face.normal, face.axes, "rect", (h1, h2), 0.0, material - deep,
                         (radius, radius, radius, radius),
                         axis_sources=(((item.id, "length"), *sizes[3:]), ((item.id, "width"), *sizes[3:])),
                         depth_sources=depths, less=less)  # fmt: skip
    layout.faces[key] = {"bottom": floor}


# ----------------------------------------------------------------------
# Positions on a face
# ----------------------------------------------------------------------
def _host_faces(on: On, layout: Layout, at: str) -> list[tuple[int, Face]] | None:
    if on.item in layout.unplaced:
        return None  # its own problem says why; what stands on it waits
    hosts = layout.instances.get(on.item)
    if hosts is None:
        layout.issue(
            "fault", at + pointer("on", "item"), f"no item {on.item!r} to stand on"
        )
        return None
    kind = layout.kinds[on.item]
    declared = KINDS[kind].faces
    if on.face not in declared:
        layout.issue("fault", at + pointer("on", "face"),
                     f"a {kind}'s faces are {list(declared)}, not {on.face!r}" if declared
                     else f"nothing stands on or cuts into a {kind}")  # fmt: skip
        return None
    found: list[tuple[int, Face]] = []
    for index, _ in enumerate(hosts):
        key = (on.item, index)
        face = layout.faces.get(key, {}).get(on.face)
        if face is None:
            issue, why = layout.closed.get(key, {}).get(on.face) or (
                "unable", f"Forge can't place on the {on.face} face of a {kind} yet")  # fmt: skip
            layout.issue(issue, at + pointer("on", "face"), why)
            return None
        found.append((index, face))
    return found


def _along(
    position: AxisPosition,
    half: float,
    foot: float,
    extent: tuple[float, float] | None = None,
) -> float:
    """Where along one axis of a face an item's point is, from the face's centre.

    Measured from an edge to the item's edge, its ``foot`` either way, or, for
    an outline not centred on its point (an extrusion's), its ``extent``:
    how far it reaches back and forth from its point.
    """
    if position.mode == "centred" or position.distance is None:
        return 0.0
    distance = mm(position.distance)
    if position.mode == "offset":
        return distance
    lo, hi = extent if extent is not None else (-foot, foot)
    if position.to != "edge":
        lo = hi = 0.0
    if position.side and position.side[0] == "-":
        return -half + distance - lo
    return half - distance - hi


#: The pattern values and counts that run along an axis, by pattern kind.
_AXIS_NAMES = {
    "corners": ("inset_{}",),
    "rectangle": ("{}",),
    "grid": ("pitch_{}", "count_{}"),
}


def _face_position(place: Place | None, face: FlatFace, item: Item, layout: Layout,
                   at: str) -> list[tuple[float, float]] | None:  # fmt: skip
    """Positions on a flat face, in the face's axes, relative to its centre."""
    a1, a2 = face.axes
    f1, f2 = bbox(_outline(item, layout, face.axes))
    reaches = _reaches(item)
    axes = place.axes if place else {}
    pattern = place.pattern if place else None
    for axis in axes:
        if axis not in face.axes:
            layout.issue("fault", at + pointer("place", axis),
                         f"{axis} doesn't lie in face {face.name}; it has {a1} and {a2}")  # fmt: skip
            return None
    fixed_by_pattern: set[str] = set()
    if pattern is not None:
        here = at + pointer("place", "pattern", pattern.kind)
        for template in _AXIS_NAMES.get(pattern.kind, ()):
            for axis in "xyz":
                name = template.format(axis)
                if axis not in face.axes and (
                    name in pattern.values or name in pattern.counts
                ):
                    layout.issue("fault", here + pointer(name),
                                 f"{name} runs along {axis}, which face {face.name} doesn't have; it has {a1} and {a2}")  # fmt: skip
                    return None
        if pattern.kind == "corners":
            fixed_by_pattern = {a1, a2}
        elif pattern.kind == "ends" and pattern.axis:
            fixed_by_pattern = {pattern.axis}
    for axis in sorted(set(axes) & fixed_by_pattern):
        assert pattern is not None
        layout.issue("fault", at + pointer("place", axis),
                     f"the {pattern.kind} pattern sets where copies are along {axis}; leave place.{axis} out")  # fmt: skip
        return None
    anchor: list[float] = []
    for k, (axis, half, foot) in enumerate(
        ((a1, face.half[0], f1), (a2, face.half[1], f2))
    ):
        position = axes.get(axis)
        if position is None:
            if axis not in fixed_by_pattern:
                layout.assume(
                    at,
                    f"{item.id}: centred along {axis} on {face.name}; the brief doesn't say where",
                )
            anchor.append(0.0)
            continue
        if not position.to_given:
            layout.assume(at, f"{item.id}: measured from the {position.side} edge to its centre, along {axis}; "
                          "the brief doesn't say to its centre or its near edge")  # fmt: skip
        anchor.append(
            _along(position, half, foot, None if reaches is None else reaches[k])
        )
    if pattern is not None and pattern.kind in ("circle", "arc"):
        for axis in sorted(axes):
            if axes[axis].mode == "side" and axes[axis].to == "edge":
                layout.issue("fault", at + pointer("place", axis, "to"),
                             f"a {pattern.kind} of copies is placed by its centre: measure from the edge to its "
                             'centre ("to": "centre")')  # fmt: skip
                return None
    offsets = (
        _pattern_offsets(pattern, face, item, layout, at) if pattern else [(0.0, 0.0)]
    )
    if offsets is None:
        return None
    if pattern and pattern.kind == "corners":
        return offsets
    if pattern is not None and pattern.kind not in ("circle", "arc"):
        # From an edge, a row, grid or rectangle is measured to its nearest
        # copy, as a brief means "the first hole 5 mm from the edge"; centred
        # or offset, to its centre (docs/definitions/place.md).
        for k, axis in enumerate((a1, a2)):
            position = axes.get(axis)
            if position is not None and position.mode == "side":
                along = [o[k] for o in offsets]
                anchor[k] -= (
                    min(along) if (position.side or "+").startswith("-") else max(along)
                )
    if pattern and pattern.kind == "ends" and pattern.axis:
        k = 0 if pattern.axis == a1 else 1
        return [(o[0], anchor[1]) if k == 0 else (anchor[0], o[1]) for o in offsets]
    return [(anchor[0] + du, anchor[1] + dv) for du, dv in offsets]


def _pattern_offsets(pattern: Pattern, face: FlatFace, item: Item, layout: Layout,
                     at: str) -> list[tuple[float, float]] | None:  # fmt: skip
    a1, a2 = face.axes
    here = at + pointer("place", "pattern", pattern.kind)
    v = {
        name: degrees(value) if name in PATTERN_ANGLES else mm(value)
        for name, value in pattern.values.items()
    }
    n = {name: count.n for name, count in pattern.counts.items()}
    total = math.prod(c for name, c in n.items() if name != "each")
    if total > MAX_COPIES:
        layout.issue(
            "unable",
            here,
            f"{total} copies: Forge places at most {MAX_COPIES:,} of one item",
        )
        return None
    if n.get("each", 1) != 1:
        layout.issue("unable", here,
                     f"{n['each']} at each position: Forge places one per position for now")  # fmt: skip
        return None

    def need(*names: str) -> bool:
        missing = [x for x in names if x not in v and x not in n]
        if missing:
            layout.issue(
                "fault", here, f"this pattern on face {face.name} needs {missing}"
            )
            return False
        return True

    if pattern.kind in ("corners", "ends") and face.shape != "rect":
        layout.issue("fault", here,
                     f"a {pattern.kind} pattern needs a rectangular face; {face.name} is round")  # fmt: skip
        return None
    if pattern.kind == "corners":
        if not need(f"inset_{a1}", f"inset_{a2}"):
            return None
        c1, c2 = face.half[0] - v[f"inset_{a1}"], face.half[1] - v[f"inset_{a2}"]
        for k, (axis, c) in enumerate(((a1, c1), (a2, c2))):
            if c <= EPS:
                layout.problem("question", here + pointer(f"inset_{axis}"),
                               f"{v[f'inset_{axis}']:g} mm in from the edges is half the face ({face.half[k]:g} mm) or "
                               "more: the corner copies would meet or cross",
                               [pattern.values[f"inset_{axis}"], *layout.values_of(face.axis_sources[k])])  # fmt: skip
        return [(s1 * c1, s2 * c2) for s1 in (-1, 1) for s2 in (-1, 1)]
    if pattern.kind == "rectangle":
        if not need(a1, a2):
            return None
        return [(s1 * v[a1] / 2, s2 * v[a2] / 2) for s1 in (-1, 1) for s2 in (-1, 1)]
    if pattern.kind in ("ends", "row") and pattern.axis not in face.axes:
        layout.issue("fault", here + pointer("axis"),
                     f"{pattern.axis} doesn't lie in face {face.name}; it has {a1} and {a2}")  # fmt: skip
        return None
    if pattern.kind == "ends":
        k = 0 if pattern.axis == a1 else 1
        c = face.half[k] - v["inset"]
        if c <= EPS:
            layout.problem("question", here + pointer("inset"),
                           f"{v['inset']:g} mm in from the ends is half the face ({face.half[k]:g} mm) or more: "
                           "the two copies would meet or cross",
                           [pattern.values["inset"], *layout.values_of(face.axis_sources[k])])  # fmt: skip
        return [(-c, 0.0), (c, 0.0)] if k == 0 else [(0.0, -c), (0.0, c)]
    if pattern.kind == "row":
        count, pitch = n["count"], v["pitch"]
        steps = [(k - (count - 1) / 2) * pitch for k in range(count)]
        return (
            [(s, 0.0) for s in steps]
            if pattern.axis == a1
            else [(0.0, s) for s in steps]
        )
    if pattern.kind == "grid":
        if not need(f"count_{a1}", f"pitch_{a1}", f"count_{a2}", f"pitch_{a2}"):
            return None
        n1, n2 = n[f"count_{a1}"], n[f"count_{a2}"]
        p1, p2 = v[f"pitch_{a1}"], v[f"pitch_{a2}"]
        return [
            ((i - (n1 - 1) / 2) * p1, (j - (n2 - 1) / 2) * p2)
            for i in range(n1)
            for j in range(n2)
        ]
    if pattern.kind in ("circle", "arc"):
        if not need("diameter"):
            return None
        count, radius = n["count"], v["diameter"] / 2
        if "start" not in v:
            layout.assume(
                here,
                f"{item.id}: the first of the {count} starts at 0 degrees, on +{a1}",
            )
        start = v.get("start", 0.0)
        step = 360 / count if pattern.kind == "circle" else v["step"]
        turns = [_turn(start + step * k) for k in range(count)]
        return [(radius * cos, radius * sin) for cos, sin in turns]
    layout.issue("fault", here, f"unknown pattern {pattern.kind}")  # pragma: no cover
    return None


def _check_overlaps(item: Item, parts: Sequence[Part], positions: Sequence[tuple[float, float]],
                    layout: Layout, at: str, first: int, values: Sequence[object]) -> None:  # fmt: skip
    """No two copies of an item overlap or land on each other, unless the brief says so."""
    pair = copies_overlap(parts, positions)
    if pair is None:
        return
    i, j = pair
    (u1, u2), (w1, w2) = positions[i], positions[j]
    how = "land on each other" if math.hypot(u1 - w1, u2 - w2) <= EPS else "overlap"
    layout.problem(
        "question",
        at,
        f"copies {first + i + 1} and {first + j + 1} of {item.id} {how}",
        values,
    )


def _failing_axes(
    face: FlatFace, parts: Sequence[Part], p1: float, p2: float
) -> list[int]:
    """The axes of the face an outline runs past, for routing; both when it can't be said."""
    if face.shape != "rect":
        return [0, 1]
    b1, b2 = bbox(parts)
    found = [
        k
        for k, (p, b) in enumerate(((p1, b1), (p2, b2)))
        if abs(p) + b > face.half[k] + EPS
    ]
    return found or [0, 1]


def _check_fits(item: Item, face: FlatFace, positions: Sequence[tuple[float, float]], layout: Layout,
                at: str, first: int) -> None:  # fmt: skip
    """Every copy lies on the face; a body at least meets it.

    A body may overhang the face it stands on (a bolt's head on its shank) but
    must meet it. A cut that fits nowhere on its face, and goes through, cuts
    the part apart: CAN'T. Anything else that doesn't fit is a question.
    """
    parts = _covered(item, layout, face)
    footing = _footing(item) if item.kind in ("extrusion", "revolution") else None
    if not parts and footing is None:
        return
    category = KINDS[item.kind].category

    def blamed(axes_: Iterable[int], *, placed: bool) -> list[object]:
        values: list[object] = []
        for k in axes_:
            values += _item_values(item, *_outline_fields(item, face.axes, k))
            values += layout.values_of(face.axis_sources[k])
            if placed:
                values += _place_values(item, face.axes[k])
        return values

    if category is Category.BODY:
        for n, (p1, p2) in enumerate(positions):
            met = (shape_meets_face(face, footing, p1, p2) if footing is not None
                   else outline_meets_face(face, parts, p1, p2))  # fmt: skip
            if not met:
                layout.problem("question", at,
                               f"{item.id} copy {first + n + 1} doesn't meet the {face.name} face it stands on",
                               blamed([0, 1], placed=True))  # fmt: skip
                return
        return
    cut = category is Category.CUT
    b1, b2 = bbox(parts)
    fits = fits_somewhere(face, parts, cut=cut)
    if fits is False:
        severs = cut and _is_through(item)
        failing = [k for k, b in enumerate((b1, b2)) if b > face.half[k] + EPS] or [
            0,
            1,
        ]
        shown = (f"{2 * face.half[0]:g} x {2 * face.half[1]:g} mm" if face.shape == "rect"
                 else f"Ø{2 * face.half[0]:g} mm")  # fmt: skip
        layout.problem("cant" if severs else "question", at,
                       f"{item.id} ({2 * b1:g} x {2 * b2:g} mm) is larger than the face it is on "
                       f"({face.name}, {shown})" + (": cut through, it would cut the part apart" if severs else ""),
                       blamed(failing, placed=False) + ([item.get("depth")] if severs else []))  # fmt: skip
        return
    for n, (p1, p2) in enumerate(positions):
        if cut and inside_hole(face, parts, p1, p2):
            layout.problem("question", at, f"{item.id} copy {first + n + 1} lies wholly in the hole in the "
                           f"middle of face {face.name}: it would cut nothing", blamed([0, 1], placed=True))  # fmt: skip
            return
        if not outline_on_face(face, parts, p1, p2, cut=cut):
            into_hole = (
                face.shape == "annulus"
                and reach(parts) + math.hypot(p1, p2) <= face.half[0] + EPS
            )
            where = f"breaks into the hole in the middle of face {face.name}" if into_hole else (
                f"runs past the edge of face {face.name}")  # fmt: skip
            layout.problem("question", at, f"{item.id} copy {first + n + 1} {where}",
                           blamed(_failing_axes(face, parts, p1, p2), placed=True))  # fmt: skip
            return
        if cut and touches_edge(face, parts, p1, p2):
            layout.problem("question", at, f"{item.id} copy {first + n + 1} touches the edge of face {face.name}: "
                           "the wall between them would be nothing there", blamed([0, 1], placed=True))  # fmt: skip
            return


def _check_severs(item: Item, face: FlatFace, host: tuple[str, int, str], parts: Sequence[Part],
                  positions: Sequence[tuple[float, float]], layout: Layout, at: str, first: int) -> None:  # fmt: skip
    """A cut right across a body's face, and through it, cuts the part in two: CAN'T.

    Right across means from one edge of the face to the other, with material
    left on both sides of it; at an end, the same cut only shortens the part.
    Settled only where nothing else could hold the two pieces together: the
    host is a solid body on its own, standing on nothing, with nothing on it.
    A shelled body is left out: through its wall, a cut only opens it.
    """
    owner = layout.items.get(host[0])
    if (
        face.shape != "rect"
        or owner is None
        or KINDS[owner.kind].category is not Category.BODY
    ):
        return
    if owner.get("on") is not None or any(
        (isinstance(on := other.get("on"), On) and on.item == owner.id
         and KINDS[other.kind].category in (Category.BODY, Category.ADD))
        or (other.kind == "shell" and other.get("of") == owner.id)
        for other in layout.items.values()
    ):  # fmt: skip
        return
    depth = item.get("depth")
    far = reach(parts)
    for n, (p1, p2) in enumerate(positions):
        nearest = max(math.hypot(p1, p2) - far, 0.0)
        if not (
            _is_through(item)
            or (
                isinstance(depth, Value)
                and mm(depth) >= material_at(face, nearest, 0.0, 0.0) - EPS
            )
        ):
            continue
        for part in parts:
            if part.disc:
                continue
            centre = (part.centre[0] + p1, part.centre[1] + p2)
            for k in (0, 1):
                j = 1 - k
                across = (centre[k] - part.half[k] <= -face.half[k] + EPS
                          and centre[k] + part.half[k] >= face.half[k] - EPS)  # fmt: skip
                between = (centre[j] - part.half[j] > -face.half[j] + EPS
                           and centre[j] + part.half[j] < face.half[j] - EPS)  # fmt: skip
                if across and between:
                    # Where it is across the cut decides it, centred included: in
                    # the middle is the worst place there is, not the best.
                    place = _place_of(item)
                    where = place.axes.get(face.axes[j]) if place is not None else None
                    values = [where, *_item_values(item, *_outline_fields(item, face.axes, k)), *_place_values(item, face.axes[j]),
                              *layout.values_of(face.axis_sources[k]), depth]  # fmt: skip
                    layout.problem("cant", at,
                                   f"{item.id} copy {first + n + 1} goes right across face {face.name} and through "
                                   "it: it would cut the part in two", values)  # fmt: skip
                    return


def _concentric_positions(item: Item, place: Place, face: FlatFace, host: tuple[str, int, str],
                          host_count: int, layout: Layout, at: str) -> list[tuple[float, float]] | None:  # fmt: skip
    """Where a concentric item goes: on the axis of its partner, projected onto the face."""
    here = at + pointer("place", "concentric")
    if place.axes or place.pattern:
        layout.issue("fault", at + pointer("place"),
                     "concentric fixes the position; give no axes or pattern with it")  # fmt: skip
        return None
    partner_id = place.concentric
    assert partner_id is not None
    if partner_id in layout.unplaced:
        return None
    others = layout.instances.get(partner_id)
    if not others:
        layout.issue("fault", here, f"no placed item {partner_id!r}")
        return None
    if partner_id == host[0]:
        partners = [others[host[1]]]
    elif host_count == 1 or len(others) == 1:
        partners = others  # every copy of the partner on the one host, or the one partner on each
    elif len(others) == host_count:
        partners = [others[host[1]]]
    else:
        layout.issue("fault", here,
                     f"{partner_id} has {len(others)} copies and {host[0]} {host_count}: say which goes with which")  # fmt: skip
        return None
    normal = _dir(face.normal)
    a1, a2 = face.axes
    positions = []
    for other in partners:
        if (
            abs(abs(sum(a * b for a, b in zip(other.normal, normal, strict=True))) - 1)
            > 1e-9
        ):
            layout.issue("fault", here,
                         f"{partner_id}'s axis doesn't run through face {face.name}: it can't be concentric there")  # fmt: skip
            return None
        d = [other.origin[k] - face.centre[k] for k in range(3)]
        positions.append((d[_INDEX[a1]], d[_INDEX[a2]]))
    return positions


@dataclass(frozen=True)
class _Copy:
    instance: Instance
    material: float  # under the copy's footprint, at its thinnest; 0 where it overhangs
    depth_sources: tuple[Source, ...] = ()
    room: float = math.inf
    room_sources: tuple[Source, ...] = ()


def _flat_instances(item: Item, face: FlatFace, host: tuple[str, int, str], host_count: int,
                    layout: Layout, at: str, first: int) -> list[_Copy]:  # fmt: skip
    place = _place_of(item)
    a1, a2 = face.axes
    for name in ("along", "thickness_along"):
        axis = _choice_of(item, name)
        if axis is not None and axis not in face.axes:
            layout.issue("fault", at + pointer(name),
                         f"{name} is {axis}, which doesn't lie in face {face.name}; it has {a1} and {a2}")  # fmt: skip
            return []
    if place is not None and place.angle is not None:
        layout.issue("fault", at + pointer("place", "angle"),
                     "an angle places an item round a round side; on a flat face, place it along the face's axes")  # fmt: skip
        return []
    if place is not None and place.concentric:
        found = _concentric_positions(item, place, face, host, host_count, layout, at)
    else:
        found = _face_position(place, face, item, layout, at)
    if found is None:
        return []
    positions = found
    _check_fits(item, face, positions, layout, at, first)
    parts = _covered(item, layout, face)
    category = KINDS[item.kind].category
    if (
        category is Category.CUT and item.kind != "text"
    ):  # letters, cut in or standing out, never cut through
        _check_severs(item, face, host, parts, positions, layout, at, first)
    if category is not Category.BODY:
        values = [*_item_values(item, *_outline_fields(item)), *_place_values(item)]
        _check_overlaps(item, parts, positions, layout, at, first, values)
    normal = _dir(face.normal)
    footing = _footing(item) if item.kind in ("extrusion", "revolution") else None
    footprint: Footprint = footing if footing is not None else parts
    out = []
    for p1, p2 in positions:
        origin = list(face.centre)
        origin[_INDEX[a1]] += p1
        origin[_INDEX[a2]] += p2
        instance = Instance(
            item.id, 0, (origin[0], origin[1], origin[2]), normal, host, face.axes
        )
        material = least_material_under(face, footprint, p1, p2)
        out.append(
            _Copy(instance, material, face.depth_sources, face.room, face.room_sources)
        )
    if category is Category.CUT and out:
        _check_depth(item, parts,
                     lambda mouth: min(least_material_under(face, mouth, p1, p2) for p1, p2 in positions),
                     layout, at, face.depth_sources)  # fmt: skip
    return out


def _check_depth(item: Item, outline: tuple[Part, ...], material_of: Callable[[tuple[Part, ...]], float],
                 layout: Layout, at: str, sources: Iterable[Source]) -> None:  # fmt: skip
    """A blind cut, a counterbore, a countersink or engraving no deeper than the material.

    Each is measured against the least material under its own mouth
    (``material_of`` its outline, centred on the item's position): a hole's
    under its bore, a counterbore's under its own diameter, anything else's
    under its ``outline``. A cut exactly as deep as the material breaks
    through it, the same as a through cut; a counterbore that deep leaves no
    hole below it.
    """
    deep: list[tuple[str, float, tuple[Part, ...], list[object], bool]] = []
    depth = item.get("depth")
    hole = layout.diameters.get(item.id)
    if isinstance(depth, Value) and not (
        item.kind == "text" and _choice_of(item, "mode") == "emboss"
    ):
        mouth = (disc(hole / 2),) if hole is not None else outline
        deep.append(("depth", mm(depth), mouth, [depth], False))
    bore = item.get("counterbore")
    if isinstance(bore, Counterbore):
        deep.append(
            (
                "counterbore",
                mm(bore.depth),
                (disc(mm(bore.diameter) / 2),),
                [bore.depth],
                True,
            )
        )
    sink = item.get("countersink")
    if isinstance(sink, Countersink) and hole is not None:
        cone = (
            (mm(sink.diameter) - hole)
            / 2
            / math.tan(math.radians(degrees(sink.angle)) / 2)
        )
        deep.append(
            (
                "countersink",
                cone,
                (disc(mm(sink.diameter) / 2),),
                [sink.diameter, sink.angle, item.get("diameter")],
                True,
            )
        )
    for name, how_deep, mouth, values, inclusive in deep:
        material = material_of(mouth)
        if how_deep > material + 1e-9 or (inclusive and how_deep >= material - 1e-9):
            layout.problem("question", at + pointer(name),
                           f"{item.id}'s {name} is {how_deep:g} mm deep in {material:g} mm of material: "
                           + ("should it go through, or be shallower?" if name == "depth"
                              else "it leaves no hole below it"),
                           [*values, *layout.values_of(sources)])  # fmt: skip


def _side_instances(item: Item, face: SideFace, host: tuple[str, int, str], layout: Layout,
                    at: str, first: int) -> list[_Copy]:  # fmt: skip
    place = _place_of(item)
    axis = face.axis
    category = KINDS[item.kind].category
    if item.kind != "hole" and category is not Category.ADD:
        layout.issue("unable", at + pointer("on"),
                     f"on a round side, Forge cuts round holes and stands bosses, posts, tabs and ribs; "
                     f"not a {item.kind}, for now")  # fmt: skip
        return []
    if place is not None and (
        (place.pattern and place.pattern.kind not in ("circle", "arc"))
        or place.concentric
    ):
        layout.issue("unable", at + pointer("place"),
                     "on a round side, Forge places by position along the axis and angle only")  # fmt: skip
        return []
    if place is not None and place.pattern is not None:
        extra = sorted(
            set(place.pattern.values)
            - ({"step"} if place.pattern.kind == "arc" else set())
        )
        if extra:
            kind = place.pattern.kind
            layout.issue("fault", at + pointer("place", "pattern", kind),
                         f"round a side, a {kind} pattern takes only a count"
                         + (" and a step" if kind == "arc" else "")
                         + f"; give the first one's angle as place.angle, not {extra}")  # fmt: skip
            return []
    position = place.axes.get(axis) if place else None
    if position is not None and position.mode == "side" and not position.to_given:
        layout.assume(at, f"{item.id}: measured from the {position.side} end to its centre, along {axis}; "
                      "the brief doesn't say to its centre or its near edge")  # fmt: skip
    others = [a for a in (place.axes if place else {}) if a != axis]
    if others:
        layout.issue("fault", at + pointer("place", others[0]),
                     f"on a round side, position along {axis} and an angle only")  # fmt: skip
        return []
    if place and place.angle is not None:
        angles = [degrees(place.angle)]
    else:
        angles = [0.0]
        layout.assume(
            at, f"{item.id}: at 0 degrees around the {axis} axis; any angle would do"
        )
    if place and place.pattern and place.pattern.kind in ("circle", "arc"):
        count = place.pattern.counts.get("count")
        if count is None:
            layout.issue(
                "fault", at + pointer("place", "pattern"), "say how many around"
            )
            return []
        step_value = place.pattern.values.get("step")
        step = degrees(step_value) if step_value is not None else 360.0 / count.n
        angles = [angles[0] + step * k for k in range(count.n)]
    reference = {"z": ("x", "y"), "x": ("y", "z"), "y": ("z", "x")}[axis]
    half = face.length / 2
    # Blame only what binds: the item's size across and the side's radius for
    # "as wide as"; its size along, its place and the side's length for the rest.
    across_values = [*_item_values(item, *_outline_fields(item, (reference[0], axis), 0)),
                     *layout.values_of(face.radius_sources)]  # fmt: skip
    along_values = [*_item_values(item, *_outline_fields(item, (reference[0], axis), 1)),
                    *_place_values(item, axis), *layout.values_of(face.length_sources)]  # fmt: skip
    severs = category is Category.CUT and _is_through(item)
    out: list[_Copy] = []
    footprints: list[
        tuple[float, float, float, float]
    ] = []  # angle, along, half around, half along
    for angle in angles:
        radial = [0.0, 0.0, 0.0]
        radial[_INDEX[reference[0]]], radial[_INDEX[reference[1]]] = _turn(angle)
        r = (radial[0], radial[1], radial[2])
        outward = r if face.outward else (-r[0], -r[1], -r[2])
        face_axes: tuple[str, str] | None = None
        if category is Category.ADD:
            up = _direction_of(outward)
            if up is None:
                layout.issue("unable", at,
                             f"{item.id} would stand at an angle; Forge builds that in a later stage")  # fmt: skip
                return []
            # Round a side, an item's length runs around it and its width along the axis.
            around = next(a for a in "xyz" if a not in (up[1], axis))
            face_axes = (around, axis)
            for name in ("along", "thickness_along"):
                chosen = _choice_of(item, name)
                if chosen is not None and chosen not in face_axes:
                    layout.issue("fault", at + pointer(name),
                                 f"{name} is {chosen}; standing out of {up} on a round side it can run along "
                                 f"{around} (around) or {axis} (along the axis)")  # fmt: skip
                    return []
            across_size, along_size = bbox(_outline(item, layout, face_axes))
        else:
            across_size = along_size = reach(_outline(item, layout, (axis, axis)))
        if 2 * across_size >= 2 * face.radius - EPS:
            layout.problem("cant" if severs else "question", at,
                           f"{item.id} ({2 * across_size:g} mm across) is as wide as the round {face.name} it is on "
                           f"(\u00d8{2 * face.radius:g} mm)", across_values)  # fmt: skip
            return []
        if 2 * along_size > face.length + EPS:
            layout.problem("cant" if severs else "question", at,
                           f"{item.id} ({2 * along_size:g} mm) is longer than the {face.name} it is on "
                           f"({face.length:g} mm)", along_values)  # fmt: skip
            return []
        along = _along(position, half, along_size) if position else 0.0
        if abs(along) + along_size > half + EPS:
            layout.problem(
                "question",
                at,
                f"{item.id} runs past the end of {host[0]}",
                along_values,
            )
        centre = _add(face.start, _dir("+" + axis), half + along)
        origin = _add(centre, r, face.radius)
        footprints.append((angle, along, across_size, along_size))
        out.append(
            _Copy(
                Instance(item.id, 0, origin, outward, host, face_axes),
                face.wall,
                face.depth_sources,
            )
        )
    if position is None:
        layout.assume(
            at, f"{item.id}: halfway along the {axis} axis; the brief doesn't say where"
        )
    if len(footprints) > 1:
        _check_round_overlaps(item, face, footprints, layout, at, first)
    if category is Category.CUT:
        # Round a side, only how far the mouth reaches counts: any axes give it.
        _check_depth(item, _outline(item, layout, ("x", "y")),
                     lambda mouth: side_material(face, reach(mouth)), layout, at, face.depth_sources)  # fmt: skip
        bore = face.radius - face.wall
        hole = layout.diameters.get(item.id, 0.0) / 2
        if face.outward and _is_through(item) and 0 < bore <= hole + EPS:
            layout.problem("question", at + pointer("depth"),
                           f"{item.id} (\u00d8{2 * hole:g} mm) is as wide as the bore of {host[0]} "
                           f"(\u00d8{2 * bore:g} mm): through one wall only, or right across through both?",
                           [item.get("diameter"), *layout.values_of(face.radius_sources)])  # fmt: skip
    if category is Category.ADD and not face.outward:
        height = height_of(item)
        if height is not None and height[0] >= 2 * face.radius - EPS:
            layout.problem("question", at,
                           f"{item.id} ({height[0]:g} mm) reaches across the {face.name} (Ø{2 * face.radius:g} mm)",
                           [item.get(height[1]), *layout.values_of(face.sources)])  # fmt: skip
    return out


def _check_round_overlaps(item: Item, face: SideFace, footprints: Sequence[tuple[float, float, float, float]],
                          layout: Layout, at: str, first: int) -> None:  # fmt: skip
    """No two copies round a side overlap, measured where they come closest.

    Copies converge as they go in: holes are compared at the deepest radius
    they reach (a tube's bore for a through hole), and what stands inside a
    bore at its tip. A hole through a solid rod passes the axis and comes
    out on the far side, so its far end is compared too; two such holes
    crossing at the axis (a cross-drilled pin) is how they are meant to be.
    """
    category = KINDS[item.kind].category
    if face.outward and category is Category.CUT:
        value = item.get("depth")
        depth = (
            face.wall
            if _is_through(item)
            else (mm(value) if isinstance(value, Value) else 0.0)
        )
        inner = face.radius - depth
    elif not face.outward and category is Category.ADD:
        height = height_of(item)
        inner = face.radius - (height[0] if height is not None else 0.0)
    else:
        inner = (
            face.radius
        )  # standing out of a rod, or cut out of a bore: they only spread
    across_axis = inner <= EPS and category is Category.CUT
    radius = face.radius if across_axis else max(inner, 0.0)
    points: list[tuple[float, float]] = []
    owners: list[int] = []
    sizes: list[tuple[float, float]] = []
    for n, (angle, along, half_around, half_along) in enumerate(footprints):
        for turn in (angle, angle + 180.0) if across_axis else (angle,):
            points.append((math.radians(turn), along))
            owners.append(n)
            sizes.append((half_around, half_along))
    round_ = item.kind in ("hole", "boss")
    reach_ = 2 * max(max(h) for h in sizes)

    def apart(j: int, i: int) -> tuple[float, float]:
        """How far apart two points are, round the side (the straight line) and along it."""
        return 2 * radius * abs(math.sin((points[i][0] - points[j][0]) / 2)), abs(
            points[i][1] - points[j][1]
        )

    def close(j: int, i: int) -> bool:
        chord, gap_along = apart(j, i)
        if round_:
            return math.hypot(chord, gap_along) < sizes[i][0] + sizes[j][0] - EPS
        return (
            chord < sizes[i][0] + sizes[j][0] - EPS
            and gap_along < sizes[i][1] + sizes[j][1] - EPS
        )

    if radius > EPS and reach_ < 2 * radius:
        turn_cell = 2 * math.asin(reach_ / (2 * radius))
    else:
        turn_cell = 2 * math.pi
    pair = first_close_pair(
        points, owners, (turn_cell, reach_), close, wrap=2 * math.pi
    )
    if pair is None:
        return
    j, i = pair
    same = any(
        max(apart(p, q)) <= EPS
        for p in range(len(points)) if owners[p] == j
        for q in range(len(points)) if owners[q] == i
    )  # fmt: skip
    how = "land on each other" if same else "overlap"
    where = (
        ""
        if radius >= face.radius - EPS
        else f" where they meet, {radius:g} mm from the axis"
    )
    layout.problem("question", at, f"copies {first + j + 1} and {first + i + 1} of {item.id} {how}{where}",
                   [*_item_values(item, *_outline_fields(item)), *_place_values(item)])  # fmt: skip


def _make_order(spec: PartSpec, sequence: Sequence[Item], layout: Layout) -> list[str]:
    """Every item's id in the order the part is made (docs/definitions/frame.md, "The order").

    A hollowed body is made whole: itself; the roundings and chamfers of its
    own edges that border no open face, in the spec's order; its shell; then
    those of its edges that border an open face, which round the rim. One
    rounding with edges of both sorts is listed in both places. Every other
    rounding, chamfer and thread comes last, in the spec's order.
    """
    before: dict[str, list[str]] = {}
    after: dict[str, list[str]] = {}
    for item in spec.items:
        edges = item.get("edges")
        if (
            item.kind not in ("fillet", "chamfer")
            or not isinstance(edges, EdgeSet)
            or edges.which == "joint"
        ):
            continue
        shell, target = layout.shells.get(edges.of), layout.items.get(edges.of)
        if shell is None or target is None:
            continue
        opened = shell.get("open")
        open_faces = set(opened.faces) if isinstance(opened, Faces) else set()
        found = [
            pair
            for copy in layout.instances.get(edges.of) or []
            for pair in edges_of(
                target.kind, edges.which, _direction_of(copy.normal) or "+z"
            )
        ]
        if any(not open_faces & set(pair) for pair in found):
            before.setdefault(edges.of, []).append(item.id)
        if any(open_faces & set(pair) for pair in found):
            after.setdefault(edges.of, []).append(item.id)
    order: list[str] = []
    for item in sequence:
        if KINDS[item.kind].category is Category.MODIFY:
            continue
        order.append(item.id)
        if item.id in layout.shells:
            order += [
                *before.get(item.id, []),
                layout.shells[item.id].id,
                *after.get(item.id, []),
            ]
    made = set(order)
    return order + [
        i.id
        for i in spec.items
        if i.kind in ("fillet", "chamfer", "thread") and i.id not in made
    ]


def edges_of(kind: str, which: str, up: str) -> list[tuple[str, str]]:
    """Each edge of an edge set of a body, as the two faces it lies between (docs/definitions/edges.md).

    ``up`` is the way the body rises. A block's vertical edges lie between
    its sides, its top edges between the face it rises to and each side, its
    bottom edges between its base and each side; a round body's top and
    bottom are its ends' rims; a dome's bottom its rim. A joint is not the
    body's alone, and is not listed.

    >>> edges_of("block", "top", "+z")
    [('+z', '+x'), ('+z', '-x'), ('+z', '+y'), ('+z', '-y')]
    >>> len(edges_of("block", "all", "+x"))
    12
    """
    if kind == "block":
        down = _opposite(up)
        sides = [d for d in DIRECTIONS if d[1] != up[1]]
        vertical = [
            (a, b) for n, a in enumerate(sides) for b in sides[n + 1 :] if a[1] != b[1]
        ]
        sets = {
            "vertical": vertical,
            "top": [(up, s) for s in sides],
            "bottom": [(down, s) for s in sides],
        }
        sets["all"] = sets["vertical"] + sets["top"] + sets["bottom"]
        return sets.get(which, [])
    if kind in ("cylinder", "cone"):
        rims = {"top": [("+end", "side")], "bottom": [("-end", "side")]}
        rims["both"] = rims["top"] + rims["bottom"]
        return rims.get(which, [])
    if kind == "sphere" and which == "bottom":
        return [("-end", "surface")]
    return []


def _first_body(item: Item, layout: Layout, at: str) -> Instance:
    up = "+z"
    if item.kind in ("cylinder", "tube", "cone", "extrusion", "revolution"):
        axis = _choice_of(item, "axis")
        if axis is None:
            layout.assume(
                at, f"{item.id}: its axis is z (upright); the brief doesn't say"
            )
            axis = "z"
        up = "+" + axis
    return Instance(item.id, 0, (0.0, 0.0, 0.0), _dir(up), None)


# ----------------------------------------------------------------------
# The solver
# ----------------------------------------------------------------------
def solve(spec: PartSpec) -> Layout:
    """Place every item of the spec; never guess beyond a recorded assumption."""
    layout = Layout()
    layout.kinds = {item.id: item.kind for item in spec.items}
    layout.items = {item.id: item for item in spec.items}
    position = {item.id: n for n, item in enumerate(spec.items)}
    for item in spec.items:
        of = item.get("of")
        if item.kind == "shell" and isinstance(of, str):
            here = pointer("items", position[item.id], "of")
            if of in layout.shells:
                layout.issue(
                    "fault", here, f"{of} is already hollowed by {layout.shells[of].id}"
                )
                continue
            target = layout.kinds.get(of)
            if target is None or KINDS[target].category is not Category.BODY:
                layout.issue("fault", here, f"a shell hollows a body; {of!r} isn't one")
                continue
            if target == "tube":
                layout.issue(
                    "fault",
                    here,
                    f"{of} is a tube, hollow already: give its bore instead of a shell",
                )
                continue
            layout.shells[of] = item
    bodies_seen = 0
    sequence = _order(spec, layout)
    for item in sequence:
        at = pointer("items", position[item.id])
        category = KINDS[item.kind].category
        if item.kind == "hole":
            _resolve_diameter(item, at, layout)
        if category is Category.MODIFY:
            continue  # rounds, chamfers, shells and threads place nothing themselves
        _check_shape(item, at, layout)
        on = item.get("on")
        if category is Category.BODY and not isinstance(on, On):
            if bodies_seen:
                layout.issue("fault", at + pointer("on"),
                             f"only the first body sits on the origin; say what {item.id} stands on")  # fmt: skip
                layout.unplaced.add(item.id)
                continue
            bodies_seen += 1
            first = _first_body(item, layout, at)
            up = _direction_of(first.normal) or "+z"
            layout.instances[item.id] = [
                _standing(item, first, up, layout, at, None, None, ())
            ]
            continue
        if category is Category.BODY:
            bodies_seen += 1
        if not isinstance(on, On):
            layout.issue(
                "fault", at + pointer("on"), f"say which face {item.id} goes on"
            )
            layout.unplaced.add(item.id)
            continue
        hosts = _host_faces(on, layout, at)
        if hosts is None:
            layout.unplaced.add(item.id)
            continue
        made = _place_on_hosts(item, on, hosts, layout, at)
        layout.instances[item.id] = made
        count = item.get("count")
        if isinstance(count, Count) and made and count.n != len(made):
            place = _place_of(item)
            pattern_counts = (
                list(place.pattern.counts.values()) if place and place.pattern else []
            )
            message = (
                f"the count is {count.n}, but the placement makes {len(made)} {item.id}"
            )
            if len(hosts) > 1 and count.n * len(hosts) == len(made):
                # The writer counted one host's copies: a count is the whole part's.
                layout.issue("fault", at + pointer("count"),
                             f"{message}: {count.n} on each of the {len(hosts)} copies of {on.item}; "
                             f"a count is the whole part's, so it is {len(made)}")  # fmt: skip
            elif (
                pattern_counts
            ):  # the brief's own count and pattern may disagree: the person's to settle
                layout.problem(
                    "question", at + pointer("count"), message, [count, *pattern_counts]
                )
            else:  # the writer placed fewer or more than it counted
                layout.issue("fault", at + pointer("count"), message)
        if not made:
            layout.unplaced.add(item.id)
            if not any(i.at == at or i.at.startswith(at + "/") for i in layout.issues):
                layout.issue("fault", at, f"{item.id} was not placed")
    _check_exits(spec, layout)
    # Once the bodies are placed: which of a hollowed body's edges border an
    # open face depends on the way it rises.
    layout.order = _make_order(spec, sequence, layout)
    return layout


#: A body's face and the face across its material from it, where a cut right through comes out.
_ACROSS = {"+end": "-end", "-end": "+end", **{d: _opposite(d) for d in DIRECTIONS}}


def _in_plane(
    face: FlatFace, origin: Vec, parts: Sequence[Part]
) -> list[tuple[Part, dict[str, float]]]:
    """An outline's parts on a face, each with where its centre is along the face's two frame axes (by name)."""
    a1, a2 = face.axes
    found = []
    for part in parts:
        centre = {
            a1: origin[_INDEX[a1]] + part.centre[0],
            a2: origin[_INDEX[a2]] + part.centre[1],
        }
        found.append((Part((0.0, 0.0), part.half, part.disc), centre))
    return found


def _meet(a: tuple[Part, dict[str, float]], b: tuple[Part, dict[str, float]], b_axes: tuple[str, str],
          a_axes: tuple[str, str]) -> bool:  # fmt: skip
    """Whether two parts on parallel faces, each in its own face's axes, overlap seen along the faces' normal."""
    (pa, ca), (pb, cb) = a, b
    if b_axes != a_axes:  # the far face names its axes the other way round
        pb = Part(pb.centre, (pb.half[1], pb.half[0]), pb.disc)
    first, second = a_axes
    return _parts_overlap(pa, (ca[first], ca[second]), pb, (cb[first], cb[second]))


def _check_exits(spec: PartSpec, layout: Layout) -> None:
    """A cut right through its body comes out on the face across from it: not under something standing there.

    Through is through the body it is cut into; what stands on the far face
    over its mouth would close it, the cut ending in that item, which isn't
    through (a hole drilled up through a plate under a boss): asked about,
    with the values that put them there. Inside a tube's bore it comes out
    into the bore, which is open.
    """
    position = {item.id: n for n, item in enumerate(spec.items)}
    standing: dict[tuple[str, int, str], list[Instance]] = {}
    for item in spec.items:
        if (
            KINDS[item.kind].category in (Category.BODY, Category.ADD)
            and item.id not in layout.unplaced
        ):
            for inst in layout.instances.get(item.id, []):
                if inst.host is not None:
                    standing.setdefault(inst.host, []).append(inst)
    for item in spec.items:
        if (
            KINDS[item.kind].category is not Category.CUT
            or not _is_through(item)
            or item.id in layout.unplaced
        ):
            continue
        for cut in layout.instances.get(item.id, []):
            if cut.host is None or cut.host[2] not in _ACROSS:
                continue
            host, index, face_name = cut.host
            far = (host, index, _ACROSS[face_name])
            faces = layout.faces.get((host, index), {})
            near_face, far_face = faces.get(face_name), faces.get(far[2])
            if (
                not (isinstance(near_face, FlatFace) and isinstance(far_face, FlatFace))
                or far not in standing
            ):
                continue
            # It comes out on the far face only where the material under its face is the body's whole thickness
            # (into a hollowed body it comes out into the hollow, short of it).
            normal = _dir(near_face.normal)
            across = abs(
                sum(
                    (a - b) * d
                    for a, b, d in zip(
                        far_face.centre, near_face.centre, normal, strict=True
                    )
                )
            )
            if (
                near_face.depth_model is not None
                or abs(near_face.depth_below - across) > EPS
            ):
                continue
            mouth = _in_plane(
                near_face, cut.origin, _outline(item, layout, near_face.axes)
            )
            for other in standing[far]:
                owner = layout.items[other.item]
                over = _in_plane(
                    far_face, other.origin, _outline(owner, layout, far_face.axes)
                )
                if not any(
                    _meet(m, o, far_face.axes, near_face.axes)
                    for m in mouth
                    for o in over
                ):
                    continue
                if owner.kind == "tube" and _inside_bore(
                    mouth, near_face.axes, other, far_face, owner
                ):
                    continue
                values = [*_item_values(item, *_outline_fields(item)), *_place_values(item),
                          *_item_values(owner, *_outline_fields(owner)), *_place_values(owner)]  # fmt: skip
                layout.problem("question", pointer("items", position[item.id]),
                               f"{item.id} copy {cut.index + 1} goes right through {host} and comes out under "
                               f"{owner.id} copy {other.index + 1} on {far[2]}: should it go on through {owner.id}, "
                               "or stop?", values)  # fmt: skip
                break


def _inside_bore(mouth: list[tuple[Part, dict[str, float]]], axes: tuple[str, str], tube: Instance,
                 face: FlatFace, item: Item) -> bool:  # fmt: skip
    """Whether a cut's mouth lies within the bore of a tube standing over it."""
    r = _size(item, "inner_diameter") / 2
    first, second = axes
    o1, o2 = tube.origin[_INDEX[first]], tube.origin[_INDEX[second]]
    for part, centre in mouth:
        c1, c2 = centre[first] - o1, centre[second] - o2
        reach = (
            math.hypot(c1, c2) + part.half[0]
            if part.disc
            else math.hypot(abs(c1) + part.half[0], abs(c2) + part.half[1])
        )
        if reach > r + EPS:
            return False
    return True


@dataclass
class _Print:
    item: str
    index: int
    parts: tuple[Part, ...]
    at: tuple[float, float]
    half: tuple[float, float]  # half the outline's box


class _Footprints:
    """What stands on one flat face, and what is cut into it, found by where it is.

    Standing items are filed by their centre, cuts by every cell their box
    covers, in a grid of at most 65 x 65 cells over the face: so each new copy
    is compared with the few near it, never with every copy on the face.
    """

    _CELLS = 64

    def __init__(self, face: FlatFace) -> None:
        self.half = face.half
        self.cell = max(face.half[0], face.half[1], EPS) * 2 / self._CELLS
        self.standing: list[_Print] = []
        self.cuts: list[_Print] = []
        self._standing_cells: dict[tuple[int, int], list[int]] = {}
        self._cut_cells: dict[tuple[int, int], list[int]] = {}

    def _index(self, u: float, k: int) -> int:
        return min(max(math.floor((u + self.half[k]) / self.cell), 0), self._CELLS)

    def _cells(self, p: _Print) -> list[tuple[int, int]]:
        lo = [p.at[k] - p.half[k] - EPS for k in (0, 1)]
        hi = [p.at[k] + p.half[k] + EPS for k in (0, 1)]
        return [(i, j) for i in range(self._index(lo[0], 0), self._index(hi[0], 0) + 1)
                for j in range(self._index(lo[1], 1), self._index(hi[1], 1) + 1)]  # fmt: skip

    def _cell(self, p: _Print) -> tuple[int, int]:
        return self._index(p.at[0], 0), self._index(p.at[1], 1)

    def cuts_round(self, p: _Print) -> list[_Print]:
        """The cuts whose box holds this standing copy's centre."""
        return [self.cuts[n] for n in self._cut_cells.get(self._cell(p), [])]

    def standing_in(self, p: _Print) -> list[_Print]:
        """The standing copies whose centres lie in this cut's box."""
        found = {n for key in self._cells(p) for n in self._standing_cells.get(key, [])}
        return [self.standing[n] for n in sorted(found)]

    def add(self, p: _Print, cuts: bool) -> None:
        if cuts:
            self.cuts.append(p)
            for key in self._cells(p):
                self._cut_cells.setdefault(key, []).append(len(self.cuts) - 1)
        else:
            self.standing.append(p)
            self._standing_cells.setdefault(self._cell(p), []).append(
                len(self.standing) - 1
            )


def _boxed(inner: _Print, outer: _Print) -> bool:
    return all(
        abs(inner.at[k] - outer.at[k]) + inner.half[k] <= outer.half[k] + EPS
        for k in (0, 1)
    )


def _check_over_openings(item: Item, copy: Instance, face: FlatFace, host: tuple[str, int, str], layout: Layout,
                         at: str) -> None:  # fmt: skip
    """Nothing stands wholly over a cut's mouth, and no cut takes away all that something stands on.

    Either way, what stands there would be held up by nothing
    (docs/definitions/frame.md): asked about, with the values that put them
    there. Letters are left out: their box isn't their shape.
    """
    i1, i2 = (_INDEX[a] for a in face.axes)
    parts = _outline(item, layout, face.axes)
    here = _Print(item.id, copy.index, parts, (copy.origin[i1] - face.centre[i1], copy.origin[i2] - face.centre[i2]),
                  bbox(parts))  # fmt: skip
    cuts = KINDS[item.kind].category is Category.CUT
    found = layout.footprints.setdefault(host, _Footprints(face))
    for other in found.standing_in(here) if cuts else found.cuts_round(here):
        standing, mouth = (other, here) if cuts else (here, other)
        if not _boxed(standing, mouth) or not outline_within(
            standing.parts, standing.at, mouth.parts, mouth.at
        ):
            continue
        owner = layout.items[other.item]
        values = [*_item_values(item, *_outline_fields(item)), *_place_values(item),
                  *_item_values(owner, *_outline_fields(owner)), *_place_values(owner)]  # fmt: skip
        if cuts:
            message = f"{item.id} copy {copy.index + 1} takes away all that {other.item} copy {other.index + 1} stands on"
        else:
            message = f"{item.id} copy {copy.index + 1} stands wholly over the mouth of {other.item} copy {other.index + 1}"
        layout.problem("question", at, message + ": nothing would hold it up", values)
        break
    found.add(here, cuts)


def _place_on_hosts(item: Item, on: On, hosts: list[tuple[int, Face]], layout: Layout,
                    at: str) -> list[Instance]:  # fmt: skip
    """Every copy of an item, on every copy of its host, numbered in order."""
    category = KINDS[item.kind].category
    copies: list[_Copy] = []
    for host_index, face in hosts:
        host = (on.item, host_index, on.face)
        if isinstance(face, SideFace):
            found = _side_instances(item, face, host, layout, at, len(copies))
        else:
            found = _flat_instances(
                item, face, host, len(hosts), layout, at, len(copies)
            )
        if len(copies) + len(found) > MAX_COPIES:
            layout.issue("unable", at, f"more than {MAX_COPIES:,} copies of {item.id} on every "
                         f"copy of {on.item}: Forge places at most {MAX_COPIES:,} of one item")  # fmt: skip
            return []
        for copy in found:
            index = len(copies)
            placed = Instance(item.id, index, copy.instance.origin, copy.instance.normal,
                              copy.instance.host, copy.instance.face_axes)  # fmt: skip
            if isinstance(face, FlatFace) and item.kind != "text":
                _check_over_openings(item, placed, face, host, layout, at)
            if item.kind == "pocket" and isinstance(face, FlatFace):
                _pocket_bottom(
                    item, placed, face, copy.material, (item.id, index), layout
                )
            copies.append(
                _Copy(
                    placed,
                    copy.material,
                    copy.depth_sources,
                    copy.room,
                    copy.room_sources,
                )
            )
    if category not in (Category.BODY, Category.ADD, Category.REGION):
        return [c.instance for c in copies]
    standing: list[Instance] = []
    height = height_of(item)
    for copy in copies:
        inst = copy.instance
        up = _direction_of(inst.normal)
        if up is None:
            layout.issue("unable", at,
                         f"{item.id} would stand at an angle; Forge builds that in a later stage")  # fmt: skip
            return []
        if item.kind in (
            "cylinder",
            "tube",
            "cone",
            "extrusion",
            "revolution",
        ) and _choice_of(item, "axis") not in (None, up[1]):
            layout.issue("fault", at + pointer("axis"),
                         f"{item.id} stands on a face facing {up}; its axis is {up[1]}")  # fmt: skip
        if height is not None and height[0] > copy.room + EPS:
            layout.problem("question", at,
                           f"{item.id} ({height[0]:g} mm) rises past the far wall of the hollow it stands in "
                           f"({copy.room:g} mm)", [item.get(height[1]), *layout.values_of(copy.room_sources)])  # fmt: skip
        placed = _standing(item, inst, up, layout, at, on.item, _host_face(inst, layout),
                           copy.depth_sources)  # fmt: skip
        if isinstance(_host_face(inst, layout), SideFace):
            _round_footed(item, layout, (item.id, placed.index), up)
        standing.append(placed)
    return standing


def _host_face(inst: Instance, layout: Layout) -> Face | None:
    if inst.host is None:
        return None
    item_id, index, name = inst.host
    return layout.faces.get((item_id, index), {}).get(name)


def _round_footed(item: Item, layout: Layout, key: tuple[str, int], up: str) -> None:
    """A feature standing round a side: only its far face takes anything, for now.

    Its other faces end where its foot follows the curve (docs/definitions/frame.md).
    Its box stays the box from its point, as its height is measured.
    """
    far = "+end" if item.kind == "boss" else up
    for name in list(layout.faces.get(key, {})):
        if name != far:
            layout.close(key, name, "unable",
                         f"{item.id} stands round a side: only its far face takes anything, for now")  # fmt: skip
