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

from forge_numeric import scalar as fs

from .draft import (
    PATTERN_ANGLES,
    AxisPosition,
    Counterbore,
    Countersink,
    EdgeSet,
    Faces,
    Item,
    On,
    PartSpec,
    Pattern,
    Place,
)
from .ends import Blind, ThroughAll, end_of
from .geometry import (
    EPS,
    FlatFace,
    Footprint,
    Over,
    Part,
    SideFace,
    Source,
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
    shape_meets_face,
    side_material,
    touches_edge,
    uniform,
)
from .items.solve import SOLVE
from .items.solve._common import (
    _INDEX,
    _RESTS_ON_AN_ASSUMPTION,
    Face,
    Hollowing,
    _choice_of,
    _dir,
    _direction_of,
    _flatten,
    _is_through,
    _item_values,
    _opposite,
    _place_of,
    _size,
    _turn,
    degrees,
    mm,
    route,
)
from .items.solve.pattern import PATTERN_SOLVE
from .outline import Shape
from .problems import pointer
from .schema import DIRECTIONS, FACE_AXES, KINDS
from .values import Count, Value

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

#: The most copies of one item Forge places (a perforated sheet is a later stage).
MAX_COPIES = 10_000


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


def height_of(item: Item) -> tuple[float, str] | None:
    """How far a body or standing feature rises out of what it stands on, and the field."""
    return SOLVE[item.kind].height(item)


def _outline_fields(
    item: Item, axes: tuple[str, str] | None = None, k: int | None = None
) -> tuple[str, ...]:
    """The fields an item's outline on its face comes from; with ``k``, only along that axis."""
    return SOLVE[item.kind].outline_fields(item, axes, k)


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
            if PATTERN_SOLVE[pattern.kind].along_its_axis and name in (
                "pitch",
                "inset",
                "count",
            ):
                along = pattern.axis
            if axis is None or along in (None, axis):
                found.append(value)
    return found


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
    return SOLVE[item.kind].outline(item, layout, axes)


def _covered(item: Item, layout: Layout, face: FlatFace) -> tuple[Part, ...]:
    """What an item covers on a flat face, for its fit and what it meets: its outline; letters, their ink's box."""
    return SOLVE[item.kind].covers(item, layout, face)


def _reaches(item: Item) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """How far an extrusion or a revolution reaches back and forth along a face's two axes from the point it stands at."""
    return SOLVE[item.kind].reaches(item)


def _footing(item: Item) -> Shape | None:
    """What of an extrusion or a revolution meets the face it stands on: its outline; the end at a revolution's height 0."""
    return SOLVE[item.kind].footing(item)


def _check_shape(item: Item, at: str, layout: Layout) -> None:
    """What can't be true of an item's own sizes, wherever it is placed."""
    SOLVE[item.kind].check_shape(item, at, layout)


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
    entry = SOLVE[kind]
    base = inst.origin
    a1, a2 = inst.face_axes or FACE_AXES[up]
    key = (item.id, inst.index)
    joined = _opposite(up)
    lo, hi, far, fields = entry.stand(
        item, base, up, (a1, a2), key, layout, host, joined
    )
    faces = layout.faces[key]
    top_face = faces.get(far)
    hollowed = item.id in layout.shells and entry.body
    if isinstance(top_face, FlatFace) and host_face is not None and not hollowed:
        sources = top_face.depth_sources + host_depth
        if isinstance(host_face, FlatFace):
            # Faces facing the same way share their axes (FACE_AXES), so a footprint on one is one on the other.
            assert host_face.axes == top_face.axes, (host_face.axes, top_face.axes)
            on_host = host_face.frame.on(top_face.centre)
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
        face = "-end" if entry.round or entry.profiled else joined
        if face in KINDS[kind].faces:
            layout.close(
                key, face, "fault", f"{item.id}'s {face} face is joined to {host}"
            )
        else:  # a boss is always joined by its foot: its kind has no such face
            faces.pop(face, None)
    if item.id in layout.shells and entry.body:
        _hollow(item, key, lo, hi, up, layout, fields if entry.shell_fields else {})
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
    entry = SOLVE[item.kind]
    if not entry.hollowable:
        layout.issue("unable", shell_at,
                     f"Forge hollows blocks, cylinders and balls for now, not a {item.kind}")  # fmt: skip
        return
    outer = entry.open_faces_allowed(item)
    bad = sorted(open_faces - outer)
    if bad:
        layout.issue("fault", shell_at + pointer("open"),
                     f"a shell of {item.id} can leave open {sorted(outer) or 'nothing'}, not {bad}")  # fmt: skip
        return
    opposite = {"+end": "-end", "-end": "+end"}
    floored = [o for o in open_faces if opposite.get(o, _opposite(o)) not in open_faces]
    if isinstance(floor_value, Value):
        fault = entry.floor_fault(item, outer, open_faces, floored, shell)
        if fault is not None:
            layout.issue("fault", shell_at + pointer("floor"), fault)
            return
    for name in sorted(open_faces):
        layout.close(key, name, "unable",
                     f"{shell.id} leaves {item.id}'s {name} open: Forge doesn't place on the rim of an open hollow "
                     "yet; stand things on its inner faces")  # fmt: skip
    walls = ((shell.id, "thickness"), (shell.id, "floor"))
    entry.hollow(item, key, lo, hi, up, layout, dict(fields),
                 Hollowing(shell, shell_at, t, f, thickness_value, floor_value, frozenset(open_faces), walls))  # fmt: skip


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
        for template in PATTERN_SOLVE[pattern.kind].axis_names:
            for axis in "xyz":
                name = template.format(axis)
                if axis not in face.axes and (
                    name in pattern.values or name in pattern.counts
                ):
                    layout.issue("fault", here + pointer(name),
                                 f"{name} runs along {axis}, which face {face.name} doesn't have; it has {a1} and {a2}")  # fmt: skip
                    return None
        fixed_by_pattern = PATTERN_SOLVE[pattern.kind].fixed_axes(pattern, a1, a2)
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
    if pattern is not None and PATTERN_SOLVE[pattern.kind].round:
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
    if pattern and PATTERN_SOLVE[pattern.kind].at_the_corners:
        return offsets
    if pattern is not None and not PATTERN_SOLVE[pattern.kind].round:
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
    if pattern and PATTERN_SOLVE[pattern.kind].pinned_along_axis and pattern.axis:
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

    return PATTERN_SOLVE[pattern.kind].offsets(
        pattern, face, item, layout, here, v, n, need, a1, a2
    )


def _check_overlaps(item: Item, parts: Sequence[Part], positions: Sequence[tuple[float, float]],
                    layout: Layout, at: str, first: int, values: Sequence[object]) -> None:  # fmt: skip
    """No two copies of an item overlap or land on each other, unless the brief says so."""
    pair = copies_overlap(parts, positions)
    if pair is None:
        return
    i, j = pair
    (u1, u2), (w1, w2) = positions[i], positions[j]
    how = "land on each other" if fs.hypot(u1 - w1, u2 - w2) <= EPS else "overlap"
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
    footing = _footing(item)
    if not parts and footing is None:
        return
    entry = SOLVE[item.kind]

    def blamed(axes_: Iterable[int], *, placed: bool) -> list[object]:
        values: list[object] = []
        for k in axes_:
            values += _item_values(item, *_outline_fields(item, face.axes, k))
            values += layout.values_of(face.axis_sources[k])
            if placed:
                values += _place_values(item, face.axes[k])
        return values

    if entry.body:
        for n, (p1, p2) in enumerate(positions):
            met = (shape_meets_face(face, footing, p1, p2) if footing is not None
                   else outline_meets_face(face, parts, p1, p2))  # fmt: skip
            if not met:
                layout.problem("question", at,
                               f"{item.id} copy {first + n + 1} doesn't meet the {face.name} face it stands on",
                               blamed([0, 1], placed=True))  # fmt: skip
                return
        return
    cut = entry.cut
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
                and reach(parts) + fs.hypot(p1, p2) <= face.half[0] + EPS
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
    if face.shape != "rect" or owner is None or not SOLVE[owner.kind].body:
        return
    if owner.get("on") is not None or any(
        (isinstance(on := other.get("on"), On) and on.item == owner.id
         and SOLVE[other.kind].solid)
        or (SOLVE[other.kind].hollows and other.get("of") == owner.id)
        for other in layout.items.values()
    ):  # fmt: skip
        return
    end = end_of(item)
    far = reach(parts)
    for n, (p1, p2) in enumerate(positions):
        nearest = max(fs.hypot(p1, p2) - far, 0.0)
        if not (
            isinstance(end, ThroughAll)
            or (
                isinstance(end, Blind)
                and mm(end.depth) >= material_at(face, nearest, 0.0, 0.0) - EPS
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
                              *layout.values_of(face.axis_sources[k]), item.get("depth")]  # fmt: skip
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
    normal = face.frame.n
    positions = []
    for other in partners:
        if (
            abs(abs(sum(a * b for a, b in zip(other.normal, normal, strict=True))) - 1)
            > 1e-9
        ):
            layout.issue("fault", here,
                         f"{partner_id}'s axis doesn't run through face {face.name}: it can't be concentric there")  # fmt: skip
            return None
        positions.append(face.frame.on(other.origin))
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
    entry = SOLVE[item.kind]
    if (
        entry.cut and not entry.lettered
    ):  # letters, cut in or standing out, never cut through
        _check_severs(item, face, host, parts, positions, layout, at, first)
    if not entry.body:
        values = [*_item_values(item, *_outline_fields(item)), *_place_values(item)]
        _check_overlaps(item, parts, positions, layout, at, first, values)
    normal = face.frame.n
    footing = _footing(item)
    footprint: Footprint = footing if footing is not None else parts
    out = []
    for p1, p2 in positions:
        instance = Instance(
            item.id, 0, face.frame_at((p1, p2)).origin, normal, host, face.axes
        )
        material = least_material_under(face, footprint, p1, p2)
        out.append(
            _Copy(instance, material, face.depth_sources, face.room, face.room_sources)
        )
    if entry.cut and out:
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
    end = end_of(item)
    hole = layout.diameters.get(item.id)
    if isinstance(end, Blind) and not (SOLVE[item.kind].embossed(item)):
        mouth = (disc(hole / 2),) if hole is not None else outline
        deep.append(("depth", mm(end.depth), mouth, [end.depth], False))
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
            / fs.tan(math.radians(degrees(sink.angle)) / 2)
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
    entry = SOLVE[item.kind]
    if not entry.on_round_side:
        layout.issue("unable", at + pointer("on"),
                     f"on a round side, Forge cuts round holes and stands bosses, posts, tabs and ribs; "
                     f"not a {item.kind}, for now")  # fmt: skip
        return []
    if place is not None and (
        (place.pattern and not PATTERN_SOLVE[place.pattern.kind].round)
        or place.concentric
    ):
        layout.issue("unable", at + pointer("place"),
                     "on a round side, Forge places by position along the axis and angle only")  # fmt: skip
        return []
    if place is not None and place.pattern is not None:
        extra = sorted(
            set(place.pattern.values)
            - ({"step"} if PATTERN_SOLVE[place.pattern.kind].steps_round else set())
        )
        if extra:
            kind = place.pattern.kind
            layout.issue("fault", at + pointer("place", "pattern", kind),
                         f"round a side, a {kind} pattern takes only a count"
                         + (" and a step" if PATTERN_SOLVE[kind].steps_round else "")
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
    if place and place.pattern and PATTERN_SOLVE[place.pattern.kind].round:
        count = place.pattern.counts.get("count")
        if count is None:
            layout.issue(
                "fault", at + pointer("place", "pattern"), "say how many around"
            )
            return []
        step_value = place.pattern.values.get("step")
        step = degrees(step_value) if step_value is not None else 360.0 / count.n
        angles = [angles[0] + step * k for k in range(count.n)]
    reference = face.reference
    half = face.length / 2
    # Blame only what binds: the item's size across and the side's radius for
    # "as wide as"; its size along, its place and the side's length for the rest.
    across_values = [*_item_values(item, *_outline_fields(item, (reference[0], axis), 0)),
                     *layout.values_of(face.radius_sources)]  # fmt: skip
    along_values = [*_item_values(item, *_outline_fields(item, (reference[0], axis), 1)),
                    *_place_values(item, axis), *layout.values_of(face.length_sources)]  # fmt: skip
    severs = entry.cut and _is_through(item)
    out: list[_Copy] = []
    footprints: list[
        tuple[float, float, float, float]
    ] = []  # angle, along, half around, half along
    for angle in angles:
        turn = _turn(angle)
        r = face.frame.radial(*turn)
        outward = r if face.outward else (-r[0], -r[1], -r[2])
        face_axes: tuple[str, str] | None = None
        if entry.adds:
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
        origin = face.frame_at(turn, along).origin
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
    if entry.cut:
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
    if entry.adds and not face.outward:
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
    entry = SOLVE[item.kind]
    if face.outward and entry.cut:
        end = end_of(item)
        depth = (
            face.wall
            if isinstance(end, ThroughAll)
            else (mm(end.depth) if isinstance(end, Blind) else 0.0)
        )
        inner = face.radius - depth
    elif not face.outward and entry.adds:
        height = height_of(item)
        inner = face.radius - (height[0] if height is not None else 0.0)
    else:
        inner = (
            face.radius
        )  # standing out of a rod, or cut out of a bore: they only spread
    across_axis = inner <= EPS and entry.cut
    radius = face.radius if across_axis else max(inner, 0.0)
    points: list[tuple[float, float]] = []
    owners: list[int] = []
    sizes: list[tuple[float, float]] = []
    for n, (angle, along, half_around, half_along) in enumerate(footprints):
        for turn in (angle, angle + 180.0) if across_axis else (angle,):
            points.append((math.radians(turn), along))
            owners.append(n)
            sizes.append((half_around, half_along))
    round_ = entry.round_foot
    reach_ = 2 * max(max(h) for h in sizes)

    def apart(j: int, i: int) -> tuple[float, float]:
        """How far apart two points are, round the side (the straight line) and along it."""
        return 2 * radius * abs(fs.sin((points[i][0] - points[j][0]) / 2)), abs(
            points[i][1] - points[j][1]
        )

    def close(j: int, i: int) -> bool:
        chord, gap_along = apart(j, i)
        if round_:
            return fs.hypot(chord, gap_along) < sizes[i][0] + sizes[j][0] - EPS
        return (
            chord < sizes[i][0] + sizes[j][0] - EPS
            and gap_along < sizes[i][1] + sizes[j][1] - EPS
        )

    if radius > EPS and reach_ < 2 * radius:
        turn_cell = 2 * fs.asin(reach_ / (2 * radius))
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
            not SOLVE[item.kind].rounding
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
        if SOLVE[item.kind].modifies:
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
        i.id for i in spec.items if SOLVE[i.kind].made_last and i.id not in made
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
    return SOLVE[kind].edges(which, up)


def _first_body(item: Item, layout: Layout, at: str) -> Instance:
    up = SOLVE[item.kind].first_up(item, layout, at)
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
        if SOLVE[item.kind].hollows and isinstance(of, str):
            here = pointer("items", position[item.id], "of")
            if of in layout.shells:
                layout.issue(
                    "fault", here, f"{of} is already hollowed by {layout.shells[of].id}"
                )
                continue
            target = layout.kinds.get(of)
            if target is None or not SOLVE[target].body:
                layout.issue("fault", here, f"a shell hollows a body; {of!r} isn't one")
                continue
            if SOLVE[target].bored:
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
        entry = SOLVE[item.kind]
        entry.resolve_diameter(item, at, layout)
        if entry.modifies:
            continue  # rounds, chamfers, shells and threads place nothing themselves
        _check_shape(item, at, layout)
        on = item.get("on")
        if entry.body and not isinstance(on, On):
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
        if entry.body:
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
        if SOLVE[item.kind].solid and item.id not in layout.unplaced:
            for inst in layout.instances.get(item.id, []):
                if inst.host is not None:
                    standing.setdefault(inst.host, []).append(inst)
    for item in spec.items:
        if (
            not SOLVE[item.kind].cut
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
            normal = near_face.frame.n
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
                if SOLVE[owner.kind].bored and _inside_bore(
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
            fs.hypot(c1, c2) + part.half[0]
            if part.disc
            else fs.hypot(abs(c1) + part.half[0], abs(c2) + part.half[1])
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
    parts = _outline(item, layout, face.axes)
    here = _Print(item.id, copy.index, parts, face.frame.on(copy.origin), bbox(parts))
    cuts = SOLVE[item.kind].cut
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
    copies: list[_Copy] = []
    for host_index, face in hosts:
        host = (on.item, host_index, on.face)
        kind = _HOSTS[type(face)]
        found = kind.copies(item, face, host, len(hosts), layout, at, len(copies))
        if len(copies) + len(found) > MAX_COPIES:
            layout.issue("unable", at, f"more than {MAX_COPIES:,} copies of {item.id} on every "
                         f"copy of {on.item}: Forge places at most {MAX_COPIES:,} of one item")  # fmt: skip
            return []
        for copy in found:
            index = len(copies)
            placed = Instance(item.id, index, copy.instance.origin, copy.instance.normal,
                              copy.instance.host, copy.instance.face_axes)  # fmt: skip
            kind.numbered(item, placed, face, host, copy, layout, at)
            copies.append(
                _Copy(
                    placed,
                    copy.material,
                    copy.depth_sources,
                    copy.room,
                    copy.room_sources,
                )
            )
    if not SOLVE[item.kind].stands:
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
        if SOLVE[item.kind].axial and _choice_of(item, "axis") not in (None, up[1]):
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


@dataclass(frozen=True)
class _Host:
    """A kind of face items are put on (item 3a's placeable face): how an item's copies are placed on one, and what is
    checked of each copy once it is numbered. Today's two: a flat face and a round side."""

    copies: Callable[
        [Item, Face, tuple[str, int, str], int, Layout, str, int], list[_Copy]
    ]
    numbered: Callable[
        [Item, Instance, Face, tuple[str, int, str], _Copy, Layout, str], None
    ]


def _flat_copies(item: Item, face: Face, host: tuple[str, int, str], host_count: int, layout: Layout, at: str,
                 first: int) -> list[_Copy]:  # fmt: skip
    assert isinstance(face, FlatFace)
    return _flat_instances(item, face, host, host_count, layout, at, first)


def _flat_numbered(item: Item, placed: Instance, face: Face, host: tuple[str, int, str], copy: _Copy, layout: Layout,
                   at: str) -> None:  # fmt: skip
    """What stands over an opening, and a pocket's floor."""
    assert isinstance(face, FlatFace)
    if not SOLVE[item.kind].lettered:
        _check_over_openings(item, placed, face, host, layout, at)
    SOLVE[item.kind].floor(
        item, placed, face, copy.material, (item.id, placed.index), layout
    )


def _side_copies(item: Item, face: Face, host: tuple[str, int, str], host_count: int, layout: Layout, at: str,
                 first: int) -> list[_Copy]:  # fmt: skip
    assert isinstance(face, SideFace)
    return _side_instances(item, face, host, layout, at, first)


def _nothing_more(item: Item, placed: Instance, face: Face, host: tuple[str, int, str], copy: _Copy, layout: Layout,
                  at: str) -> None:  # fmt: skip
    return None


#: Each kind of face an item can be put on, by its class.
_HOSTS: Mapping[type, _Host] = {
    FlatFace: _Host(_flat_copies, _flat_numbered),
    SideFace: _Host(_side_copies, _nothing_more),
}


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
    far = SOLVE[item.kind].far_face(up)
    for name in list(layout.faces.get(key, {})):
        if name != far:
            layout.close(key, name, "unable",
                         f"{item.id} stands round a side: only its far face takes anything, for now")  # fmt: skip
