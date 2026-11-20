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
import itertools
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from forge_numeric import scalar as fs
from forge_units import Q

from .draft import (
    PATTERN_ANGLES,
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    EdgeSet,
    Faces,
    Item,
    On,
    PartSpec,
    Pattern,
    Place,
    UpTo,
    axis_names,
)
from .ends import Blind, ThroughAll, ThroughEverything, ThroughNext, UpToFace, end_of
from .frames import Rigid
from .geometry import (
    _REFERENCE,
    EPS,
    BallFace,
    ConeFace,
    FlatFace,
    Footprint,
    Over,
    Part,
    SideFace,
    Slant,
    Source,
    Vec,
    _parts_overlap,
    _point_in_parts,
    add_material,
    bbox,
    centred,
    cone_sag,
    copies_overlap,
    disc,
    face_footprint,
    first_close_pair,
    outline_within,
    reach,
    shape_holds,
    shapes_overlap,
    side_material,
    side_most_material,
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
from .lean import MOST, Lean, ellipse, lean_of, leaning
from .outline import Piece, Shape, boundary_within
from .problems import pointer
from .schema import DIRECTIONS, FACE_AXES, FACE_OWN_AXES, KINDS
from .values import Count, Provenance, Value

__all__ = [
    "MAX_COPIES",
    "Assumption",
    "FlatFace",
    "Instance",
    "Issue",
    "Layout",
    "SideFace",
    "as_placed",
    "edges_of",
    "footing_values",
    "height_of",
    "mm",
    "placed_spec",
    "route",
    "solve",
    "turned_outline",
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
    #: Leaning on its flat face (tilt; 1b's second move): its direction, the face's normal turned towards its lean.
    direction: Vec | None = None
    #: On a face of a turned or leaning item (1b's third move, step 2): the motion that takes it, as it is placed on
    #: that face upright (``local``), onto the part. Every program places, builds and judges it upright, then moves it.
    frame: Rigid | None = None
    local: Instance | None = None
    #: A cut through everything or up to a face (item 2b's first step): how deep it goes from its point, as the solver
    #: worked it out.
    depth: float | None = None


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
    #: Behind each closed end of a hollowed cone or dome, whose inside takes nothing yet, the hollow's section there,
    #: where the wall's inner face would be (a block's or a cylinder's is its inner face): a cut right through the
    #: wall comes out into the hollow only within it (:func:`_check_into_hollows`).
    insides: dict[tuple[str, int, str], FlatFace] = field(default_factory=dict)
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
    #: Placing on a face as it stands upright, before it is moved (a turned or leaning item's): the motion that takes
    #: it onto the part, so a cut through everything or up to a face is worked out where it is (item 2b's third
    #: step). The solver's working state, not part of what it solves to.
    motion: Rigid | None = field(default=None, compare=False, repr=False)

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
    """The values an item's position comes from; with ``axis``, only those along it (not its angle round a side,
    which is along none: a slot running past a tube's end isn't where it is round it).

    An assumed "centred" is not counted: on a symmetric face it is the best
    place there is, so whatever doesn't fit centred fits nowhere else either.
    """
    place = _place_of(item)
    if place is None:
        return []
    found: list[object] = [
        p.distance for a, p in place.axes.items() if axis in (None, a)
    ]
    if place.angle is not None and axis is None:
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
    depth = item.get("depth")
    if isinstance(depth, UpTo):  # the face it is cut up to (item 2b's first step)
        needs.add(depth.face.item)
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
    turned = (
        turned_outline(item, layout, (a1, a2))
        if isinstance(host_face, FlatFace)
        else None
    )
    if turned is not None:
        return _standing_turned(item, inst, up, layout, at, turned, lo, hi, far, host_face, fields)
    faces = layout.faces[key]
    top_face = faces.get(far)
    hollowed = item.id in layout.shells and entry.body
    turn = _turn_value(item)
    if turn is not None and isinstance(host_face, FlatFace):
        # Round, on a turned face: the same turned, its far face turned with it; its others take nothing yet.
        top_face = _turned_far(faces, far, item, turn)
        for name in [n for n in KINDS[kind].faces if n != far and n in faces]:
            layout.close(key, name, "unable", _TURNED_FACES.format(item.id))
        if hollowed:
            layout.issue("unable", at, f"Forge doesn't hollow a turned or leaning {item.kind} yet")
            hollowed = False
    if isinstance(top_face, FlatFace) and host_face is not None and (not hollowed or _left_open(item, far, layout)):
        # A hollowed body's far face has its wall alone; left open, its rim the wall all the way down, and the host.
        sources = top_face.depth_sources + host_depth
        if isinstance(host_face, FlatFace):
            # Faces facing the same way share their axes (FACE_AXES), so a footprint on one is one on the other; on a
            # turned face, what stands on it is turned with it.
            assert (host_face.part_axes, host_face.turn) == (top_face.axes, top_face.turn), (host_face, top_face)
            on_host = host_face.frame.on(top_face.centre)
            # Wholly over a host with the same material under all of it: that, under all of it too.
            if host_face.uniform and host_face.holds(face_footprint(top_face), on_host):
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
    if item.id in layout.shells and entry.body and turn is None:
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


def _left_open(item: Item, name: str, layout: Layout) -> bool:
    """Whether the shell hollowing ``item`` leaves its face ``name`` open (its rim: shell.md, "The rim")."""
    shell = layout.shells.get(item.id)
    opened = shell.get("open") if shell is not None else None
    return isinstance(opened, Faces) and name in opened.faces


#: Why a turned item's faces take nothing.
_TURNED_FACES = (
    "{} is turned in, or leans on, the face it is on: Forge places on such an item's faces in a later move"
)
#: Why a turned item's far face takes nothing.
_TURNED_FAR = (
    "{} stands turned round a side, or on a turned or leaning item's face without the same material under all of it: "
    "Forge places on its far face in a later move"
)


def _turn_value(item: Item) -> Value | None:
    """An item's turn in its face's plane as placed: its own, and the turn of a turned face it is on (:func:`as_placed`)."""
    place = _place_of(item)
    return None if place is None else place.turn


def _turned_far(faces: dict[str, Face], far: str, item: Item, turn: Value) -> FlatFace | None:
    """A standing item's far face turned with it (schema 1.4): its axes turned in its plane by the item's turn, as placed."""
    face = faces.get(far)
    if not isinstance(face, FlatFace):
        return None
    turned = replace(face, turn=degrees(turn), turn_sources=((item.id, "place"),))
    faces[far] = turned
    return turned


def _standing_turned(item: Item, inst: Instance, up: str, layout: Layout, at: str, turned: Shape, lo: Vec,
                     hi: Vec, far: str = "", host_face: Face | None = None,
                     fields: Mapping[str, str] | None = None) -> Instance:  # fmt: skip
    """A body or feature standing turned in its face's plane, or leaning on it: its bounds the box round it turned, or
    round it leaning (its foot's section and its far end's cross-section), its faces closed but a turned one's far face
    (schema 1.4): turned with it, its height of material under it and, wholly over a host with the same material under
    all of it, the host's too; partly off it, or on any other, it is closed for now. A turned block hollowed (step 5.1):
    hollowed as it stands upright, then every face of it, its far face and its inside faces too, turned with it. A
    leaning block hollowed (step 5.5): hollowed as it stands upright, its floor raised clear of the face it leans on
    (:func:`_leaning_hollow`), then every face of it leaned with it, the material under its inside floor its own back
    along its axis to that face."""
    key = (item.id, inst.index)
    a1, a2 = inst.face_axes or FACE_AXES[up]
    lean = lean_of(item, (a1, a2)) if leaning(item) else None
    if lean is not None and inst.direction is not None:
        low, high = _leaning_bounds(item, inst, lean, layout, (a1, a2))
    else:
        (l1, l2), (h1, h2) = turned.box()
        low, high = list(lo), list(hi)
        for axis, (a, b) in ((a1, (l1, h1)), (a2, (l2, h2))):
            k = _INDEX[axis]
            low[k], high[k] = inst.origin[k] + a, inst.origin[k] + b
    faces = layout.faces.setdefault(key, {})
    for name in [name for name in faces if name not in KINDS[item.kind].faces]:
        faces.pop(name)  # a boss is always joined by its foot: its kind has no such face
    turn = _turn_value(item) if lean is None else None
    hollowed = turn is not None and item.id in layout.shells and SOLVE[item.kind].body
    # Leaning, not turned (1b's step 5, with item 2b): its far face placed on as with it upright, then leaned so; a
    # leaning block hollowed (step 5.5) so too.
    shelled = item.id in layout.shells and SOLVE[item.kind].body
    leaned = (_leaning_motion(inst, lean, up) if lean is not None and inst.direction is not None
              and _turn_value(item) is None
              and (not shelled or SOLVE[item.kind].turnable(item, layout, (a1, a2)) is not None) else None)  # fmt: skip
    if hollowed:  # step 5.1: its hollow made as it stands upright (its faces so), all of it then turned below
        _hollow(item, key, lo, hi, up, layout, dict(fields or {}))
    floor = None  # a leaning block's hollow (step 5.5): the material under its inside floor's middle
    if leaned is not None and lean is not None and shelled:
        floor = _leaning_hollow(item, key, inst, lo, hi, up, (a1, a2), lean, layout, dict(fields or {}))
        hollowed = True
    top = _turned_far(faces, far, item, turn) if turn is not None and far in faces and not hollowed else None
    joined = _opposite(up)
    motion = _turned_motion(inst, (a1, a2), turn) if turn is not None else None
    for name in KINDS[item.kind].faces:
        found = faces.get(name)
        if (top is not None and name == far) or name in layout.closed.get(key, {}):
            continue
        if leaned is not None and lean is not None and isinstance(found, FlatFace) and name.startswith("inner "):
            # Inside a leaning block's hollow (step 5.5): as upright, leaned so; under its floor, its own material back
            # along its axis to the face it leans on.
            if name == f"inner {joined}" and floor is not None:
                found = replace(found, depth_below=floor, depth_model=Slant(lean.way, lean.tan))
            faces[name] = _moved(found, leaned)
        elif leaned is not None and lean is not None and name == far and isinstance(found, FlatFace) and hollowed:
            # A leaning block's far face over its hollow: its wall under it (step 5.5).
            faces[name] = _moved(found, leaned)
        elif leaned is not None and lean is not None and name == far and isinstance(found, FlatFace) \
                and found.axes == (a1, a2):  # fmt: skip
            # The material under it is its own: from each point back along its axis to the face it leans on.
            faces[name] = _moved(replace(found, depth_model=Slant(lean.way, lean.tan), over=None), leaned)
        elif leaned is not None and lean is not None and isinstance(found, FlatFace) and name != joined \
                and up[1] in found.axes:  # fmt: skip
            # A side: its upright side where it is clear of its foot, leaned so (V2-stage4b-0c.md 3.3, a leaning item's
            # sides).
            side = _clear_of_foot(found, up, (a1, a2), lean, lo, hi)
            if side is None:
                layout.close(key, name, "unable", f"{item.id} leans so far that its foot reaches all the way up its "
                             f"{name} side")  # fmt: skip
            else:
                faces[name] = _moved(side, leaned)
        elif leaned is not None and lean is not None and isinstance(found, SideFace) and found.outward \
                and found.half is None and found.axis == up[1]:  # fmt: skip
            # Its round side: as upright where it is clear of its foot, leaned so (V2-stage4b-0c.md 3.3, a leaning
            # item's sides).
            rise = found.radius * lean.tan
            if found.length <= rise:
                layout.close(key, name, "unable", f"{item.id} leans so far that its foot reaches all the way up its "
                             "side")  # fmt: skip
            else:
                step = rise if up[0] == "+" else 0.0  # its foot at its start, or at its far end
                lift = _dir("+" + up[1])
                start = (found.start[0] + lift[0] * step, found.start[1] + lift[1] * step,
                         found.start[2] + lift[2] * step)  # fmt: skip
                faces[name] = replace(found, start=start, length=found.length - rise, local=leaned)
        elif motion is not None and name == joined and inst.host is not None:
            layout.close(key, name, "fault", f"{item.id}'s {name} face is joined to {inst.host[0]}")
        elif motion is not None and isinstance(found, FlatFace) and (hollowed or not name.startswith("inner ")):
            # Its other faces are its own, turned with it (1b's third move, step 2): placed on as upright, then turned.
            faces[name] = _moved(found, motion)
        else:
            layout.close(key, name, "unable", _TURNED_FACES.format(item.id))
    if top is not None:
        _far_material(item, inst, top, host_face, layout)
    if item.id in layout.shells and not hollowed:
        layout.issue("unable", at, f"Forge hollows a leaning block, not yet a leaning {item.kind} that is round or "
                     "turned in its face")  # fmt: skip
    return Instance(inst.item, inst.index, inst.origin, _dir(up), inst.host, inst.face_axes,
                    (low[0], low[1], low[2]), (high[0], high[1], high[2]), inst.direction)  # fmt: skip


def _leaning_hollow(item: Item, key: tuple[str, int], inst: Instance, lo: Vec, hi: Vec, up: str, axes: tuple[str, str],
                    lean: Lean, layout: Layout, fields: Mapping[str, str]) -> float | None:  # fmt: skip
    """A leaning block hollowed (V2-stage4b-0c.md 3.3, step 5.5; shell.md): its hollow as with it upright, its floor
    raised by as much as the face it leans on rises under the hollow's far side along its lean (its half size along
    its lean less its wall there, times its tilt's tan), so that the floor is its thickness where it is thinnest,
    measured along its axis. The material under its inside floor's middle, back along its axis to that face (it is
    ``tan`` less for each millimetre the way it leans); None where it isn't hollowed."""
    shell = layout.shells[item.id]
    thickness_value, floor_value = shell.get("thickness"), shell.get("floor")
    if not isinstance(thickness_value, Value):
        return None
    opened = shell.get("open")
    open_faces = set(opened.faces) if isinstance(opened, Faces) else set()
    t = mm(thickness_value)
    f = mm(floor_value) if isinstance(floor_value, Value) else t
    k = _INDEX[axes[0] if lean.along_first else axes[1]]
    sign = 1.0 if lean.way[0] + lean.way[1] > 0 else -1.0
    towards = ("+" if sign > 0 else "-") + "xyz"[k]

    def wall(name: str) -> float:  # as Hollowing.wall: none where open, the floor's opposite an opening
        return 0.0 if name in open_faces else f if _opposite(name) in open_faces else t

    reach = max((hi[k] - lo[k]) / 2 - wall(towards), 0.0)  # the hollow's far side along its lean, from its axis
    rise = reach * lean.tan
    j = _INDEX[up[1]]
    low, high = list(lo), list(hi)
    if up[0] == "+":
        low[j] += rise
    else:
        high[j] -= rise
    _hollow(item, key, (low[0], low[1], low[2]), (high[0], high[1], high[2]), up, layout, fields)
    cavity = layout.cavities.get(key)
    if cavity is None:
        return None
    middle = sign * ((cavity[0][k] + cavity[1][k]) / 2 - inst.origin[k])  # its middle along its lean, from its axis
    return wall(_opposite(up)) + (reach - middle) * lean.tan


def _clear_of_foot(face: FlatFace, up: str, axes: tuple[str, str], lean: Lean, lo: Vec, hi: Vec) -> FlatFace | None:
    """A leaning box's side (V2-stage4b-0c.md 3.3, a leaning item's sides): the side it has upright, less the band
    along its foot as high as its foot rises on the low side, its half size along its lean times its tilt's tan. Above
    that its cross-section is wholly clear of the face it leans on, and the side is its upright one leaned, with the
    box's own size across under all of it. None where the band is all of it."""
    k = _INDEX[axes[0] if lean.along_first else axes[1]]
    rise = (hi[k] - lo[k]) / 2 * lean.tan
    j = face.axes.index(up[1])
    if 2.0 * face.half[j] <= rise:
        return None
    half = (face.half[0] - rise / 2, face.half[1]) if j == 0 else (face.half[0], face.half[1] - rise / 2)
    lift = _dir(up)
    return replace(face, centre=(face.centre[0] + lift[0] * rise / 2, face.centre[1] + lift[1] * rise / 2,
                                 face.centre[2] + lift[2] * rise / 2), half=half)  # fmt: skip


def _leaning_motion(inst: Instance, lean: Lean, up: str) -> Rigid:
    """A leaning item's own motion (1b's step 5, with item 2b): the turn about the line through its point square to its
    face's normal and the way it leans, by its tilt, which takes it upright to as it leans; its direction is the
    normal so moved."""
    a1, a2 = inst.face_axes or FACE_AXES[up]
    e1, e2, n = _axis_vec(a1), _axis_vec(a2), _dir(up)
    w = tuple(lean.way[0] * e1[k] + lean.way[1] * e2[k] for k in range(3))
    axis = (n[1] * w[2] - n[2] * w[1], n[2] * w[0] - n[0] * w[2], n[0] * w[1] - n[1] * w[0])
    return Rigid.turn_about(inst.origin, axis, lean.c, lean.s)


def _turned_motion(inst: Instance, axes: tuple[str, str], turn: Value) -> Rigid:
    """A turned item's own motion: its turn about the line through its point square to its face, from the face's
    first axis towards its second."""
    e1, e2 = _axis_vec(axes[0]), _axis_vec(axes[1])
    square = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    return Rigid.turn_about(inst.origin, square, *_turn(degrees(turn)))


def _moved(face: FlatFace, motion: Rigid) -> FlatFace:
    """A face found upright, moved by its item's motion (after any it has of its own)."""
    return replace(face, centre=motion.point(face.centre),
                   local=motion if face.local is None else motion.after(face.local))  # fmt: skip


def _far_material(item: Item, inst: Instance, top: FlatFace, host_face: Face | None, layout: Layout) -> None:
    """The material under a turned item's far face: its own height and, where its outline turned as it is in its face
    lies wholly on a host with the same material under all of it, the host's under all of it too. Over any other flat
    face, or partly off one, its host's where it is over it (:class:`Over`, turned from the host's axes: V2-stage4b-0c.md
    3.3, step 5), as with it upright; on a turned or leaning item's face without the same material under all of it, or
    round a side, it is closed."""
    key = (item.id, inst.index)
    if host_face is None:  # the first body, turned on the origin: its own height is all there is
        return
    if not isinstance(host_face, FlatFace) or (host_face.local is not None and not host_face.uniform):
        layout.close(key, top.name, "unable", _TURNED_FAR.format(item.id))
        return
    if not host_face.uniform:
        _far_over(top, host_face, layout, key)
        return
    own = degrees(_turn_value(item)) - host_face.turn  # type: ignore[arg-type]
    sizes = SOLVE[item.kind].turnable(item, layout, host_face.part_axes)
    assert sizes is not None
    h1, h2, r = sizes
    foot = Shape.rect((0.0, 0.0), (h1, h2), (r, r, r, r)).turned(*_turn(own))
    if not host_face.holds(foot, host_face.frame.on(inst.origin)):
        if host_face.local is not None:
            layout.close(key, top.name, "unable", _TURNED_FAR.format(item.id))
        else:
            _far_over(top, host_face, layout, key)
        return
    found = add_material(top, host_face.depth_below)
    layout.faces[key][top.name] = replace(found, depth_sources=top.depth_sources + host_face.depth_sources)


def _far_over(top: FlatFace, host_face: FlatFace, layout: Layout, key: tuple[str, int]) -> None:
    """A turned item's far face over its host's material where it is over its host's face (frame.md)."""
    over = Over(host_face, host_face.frame.on(top.centre))
    layout.faces[key][top.name] = replace(top, over=over, depth_sources=top.depth_sources + host_face.depth_sources)


def _leaning_bounds(item: Item, inst: Instance, lean: Lean, layout: Layout,
                    axes: tuple[str, str]) -> tuple[list[float], list[float]]:  # fmt: skip
    """The box round a leaning boss, post, block or cylinder: its foot (its cross-section's section by its face, about its
    point) and its far end (its cross-section square to its direction, its height along it from its point)."""
    assert inst.direction is not None
    p, u = inst.origin, inst.direction
    e1, e2 = _axis_vec(axes[0]), _axis_vec(axes[1])
    w = tuple(lean.way[0] * e1[k] + lean.way[1] * e2[k] for k in range(3))  # the lean's way, in the face
    across = (-lean.way[1], lean.way[0])
    q = tuple(across[0] * e1[k] + across[1] * e2[k] for k in range(3))  # in the face, square to the lean
    n = inst.normal
    tilted = tuple(lean.c * w[k] - lean.s * n[k] for k in range(3))  # the lean's way square to its direction
    rises = SOLVE[item.kind].height(item)  # its height (a cylinder's length) along its direction
    height = rises[0] if rises is not None else 0.0
    top = tuple(p[k] + height * u[k] for k in range(3))
    sizes = SOLVE[item.kind].turnable(item, layout, axes)
    if sizes is not None:  # a post: its half sizes along and across its lean
        along, other = (sizes[0], sizes[1]) if lean.along_first else (sizes[1], sizes[0])
        points = [tuple(c[k] + i * a * x[k] + j * b * y[k] for k in range(3))
                  for c, a, x in ((p, along * lean.stretch, w), (top, along, tilted))
                  for b, y in ((other, q),) for i in (-1, 1) for j in (-1, 1)]  # fmt: skip
        low = [min(pt[k] for pt in points) for k in range(3)]
        high = [max(pt[k] for pt in points) for k in range(3)]
        return low, high
    r = SOLVE[item.kind].outline(item, layout, axes)[0].half[0]
    low, high = [0.0] * 3, [0.0] * 3
    for k in range(3):
        foot = fs.hypot(r * lean.stretch * w[k], r * q[k])
        cap = r * math.sqrt(max(1.0 - u[k] * u[k], 0.0))
        low[k], high[k] = min(p[k] - foot, top[k] - cap), max(p[k] + foot, top[k] + cap)
    return low, high


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
                     f"Forge hollows blocks, cylinders, cones and balls for now, not a {item.kind}")  # fmt: skip
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
    walls = ((shell.id, "thickness"), (shell.id, "floor"))
    rims: dict[str, FlatFace] = {}
    square = _turn_value(item) is None and not leaning(item)  # a turned or leaning body's rim takes nothing yet
    for name in sorted(open_faces):
        # The rim it leaves of an open face (shell.md, "The rim"): a ring round a cylinder's mouth, a frame round a
        # block's.
        face = layout.faces.get(key, {}).get(name)
        rim = entry.rim(face, t, frozenset(open_faces)) if isinstance(face, FlatFace) and square else None
        if rim is not None:
            rims[name] = replace(rim, axis_sources=tuple(s + walls for s in rim.axis_sources))  # type: ignore[arg-type]
            continue
        inside = any(f.startswith("inner ") for f in KINDS[item.kind].faces)
        layout.close(key, name, "unable",
                     f"{shell.id} leaves {item.id}'s {name} open: Forge doesn't place on the rim of an open hollow "
                     "yet" + ("; stand things on its inner faces" if inside else ""))  # fmt: skip
    entry.hollow(item, key, lo, hi, up, layout, dict(fields),
                 Hollowing(shell, shell_at, t, f, thickness_value, floor_value, frozenset(open_faces), walls))  # fmt: skip
    if key in layout.cavities:
        layout.faces[key].update(rims)


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


def _face_position(place: Place | None, face: FlatFace, item: Item, layout: Layout, at: str,
                   turned: Shape | None = None) -> list[tuple[float, float]] | None:  # fmt: skip
    """Positions on a flat face, in the face's axes, relative to its centre (a ``turned`` outline measured to its edge by
    how far it reaches back and forth along each axis)."""
    a1, a2 = face.axes
    f1, f2 = bbox(_outline(item, layout, face.axes))
    reaches = _reaches(item)
    if turned is not None:
        (l1, l2), (h1, h2) = turned.box()
        reaches = ((l1, h1), (l2, h2))
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
            if not face.meets(footing if footing is not None else parts, (p1, p2)):
                layout.problem("question", at,
                               f"{item.id} copy {first + n + 1} doesn't meet the {face.name} face it stands on",
                               blamed([0, 1], placed=True))  # fmt: skip
                return
            if _against_a_wall(item, face, parts, (p1, p2), layout, at, first + n, blamed([0, 1], placed=True)):
                return
        return
    cut = entry.cut
    b1, b2 = bbox(centred(parts))
    fits = face.fits_somewhere(parts, cut=cut)
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
        if cut and face.in_its_hole(parts, (p1, p2)):
            layout.problem("question", at, f"{item.id} copy {first + n + 1} lies wholly in the hole in the "
                           f"middle of face {face.name}: it would cut nothing", blamed([0, 1], placed=True))  # fmt: skip
            return
        if not face.holds(parts, (p1, p2), cut=cut):
            into_hole = (
                face.shape == "annulus"
                and reach(parts) + fs.hypot(p1, p2) <= face.half[0] + EPS
            )
            where = f"breaks into the hole in the middle of face {face.name}" if into_hole else (
                f"runs past the edge of face {face.name}")  # fmt: skip
            layout.problem("question", at, f"{item.id} copy {first + n + 1} {where}",
                           blamed(_failing_axes(face, parts, p1, p2), placed=True))  # fmt: skip
            return
        if cut and face.touches_its_edge(parts, (p1, p2)):
            layout.problem("question", at, f"{item.id} copy {first + n + 1} touches the edge of face {face.name}: "
                           "the wall between them would be nothing there", blamed([0, 1], placed=True))  # fmt: skip
            return
        if not cut and _against_a_wall(item, face, parts, (p1, p2), layout, at, first + n, blamed([0, 1], placed=True)):
            return


def _against_a_wall(item: Item, face: FlatFace, parts: Sequence[Part], at_: tuple[float, float], layout: Layout,
                    at: str, n: int, values: list[object]) -> bool:  # fmt: skip
    """Something round standing inside a hollow, on a face at whose edge a wall rises, touching that edge from within:
    it would lie against the wall along a line, on which the part meets itself (a boss in a box's corner, its side
    just touching the two walls). Asked how far clear of it (it can't run into the wall: off its face). A flat side
    flush with the wall joins it."""
    if not face.name.startswith("inner ") or not parts or not face.touches_its_edge(parts, at_):
        return False
    layout.problem("question", at,
                   f"{item.id} copy {n + 1} touches the wall at the edge of face {face.name} along a line, where the "
                   "part would meet itself: how far clear of the wall should it stand?", values)  # fmt: skip
    return True


def _check_severs(item: Item, face: FlatFace, host: tuple[str, int, str], parts: Sequence[Part],
                  positions: Sequence[tuple[float, float]], layout: Layout, at: str, first: int,
                  resolved: float | None = None) -> None:  # fmt: skip
    """A cut right across a body's face, and through it, cuts the part in two: CAN'T.

    Right across means from one edge of the face to the other, with material
    left on both sides of it. Settled only where nothing else could hold the
    two pieces together: the host is a solid body on its own, standing on
    nothing, with nothing on it. A shelled body is left out: through its
    wall, a cut only opens it.

    At an end, the same cut takes the body's end away: the body is only
    shorter, its end face gone, and the length it was given is nowhere on the
    part (a bar's notch right across its end and through it was accepted,
    built, and held: neither the bar's length nor the notch's was there to
    measure). Asked about: a shorter body, or some of its end left?
    """
    owner = layout.items.get(host[0])
    if face.shape != "rect" or owner is None or not SOLVE[owner.kind].body:
        return
    if any(SOLVE[other.kind].hollows and other.get("of") == owner.id for other in layout.items.values()):
        return
    alone = owner.get("on") is None and not any(
        isinstance(on := other.get("on"), On) and on.item == owner.id and SOLVE[other.kind].solid
        for other in layout.items.values()
    )  # fmt: skip
    end = end_of(item)
    far = reach(parts)
    for n, (p1, p2) in enumerate(positions):
        nearest = max(fs.hypot(p1, p2) - far, 0.0)
        deep = mm(end.depth) if isinstance(end, Blind) else resolved
        if not (
            isinstance(end, (ThroughAll, ThroughEverything))
            or (deep is not None and deep >= face.material_under((disc(0.0),), (nearest, 0.0)) - EPS)
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
                if not across or (between and not alone):
                    continue
                # Where it is across the cut decides it, centred included: in
                # the middle is the worst place there is, not the best.
                place = _place_of(item)
                where = place.axes.get(face.axes[j]) if place is not None else None
                values = [where, *_item_values(item, *_outline_fields(item, face.axes, k)), *_place_values(item, face.axes[j]),
                          *layout.values_of(face.axis_sources[k]), item.get("depth")]  # fmt: skip
                if between:
                    layout.problem("cant", at,
                                   f"{item.id} copy {first + n + 1} goes right across face {face.name} and through "
                                   "it: it would cut the part in two", values)  # fmt: skip
                else:
                    layout.problem("question", at,
                                   f"{item.id} copy {first + n + 1} goes right across face {face.name} at its end, "
                                   f"and through it: it would take that end of {owner.id} away, leaving {owner.id} "
                                   f"only shorter. Should {owner.id} be shorter instead, or some of its end be left?",
                                   values)  # fmt: skip
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
    #: A copy standing round a side at an angle that isn't a frame axis's (item 3b's first step): placed as at the
    #: frame axis at or below its angle, and this turn about the side's axis by the rest takes it where it is.
    motion: Rigid | None = None


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
    if (face.turn != 0.0 and SOLVE[item.kind].turnable(item, layout, face.axes) is None and not _round(item, layout, face)
            and SOLVE[item.kind].shape(item, layout, face.axes) is None):  # fmt: skip
        layout.issue("unable", at + pointer("on", "face"),
                     f"face {face.name} of {host[0]} is turned with it, and so is what is placed on it: Forge turns a "
                     f"{item.kind} in a later step")  # fmt: skip
        return []
    placeable, resolved = _end_depth(item, face, layout, at) if SOLVE[item.kind].cut else (True, None)
    if not placeable:
        return []
    if ((place is not None and place.turn is not None) or leaning(item)
            or SOLVE[item.kind].shape(item, layout, face.axes) is not None):  # fmt: skip
        # Turned, leaning, or an outline of lines of its own (a hexagonal pocket): placed by that outline.
        return _turned_copies(item, place, face, host, layout, at, first, resolved)
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
        _check_severs(item, face, host, parts, positions, layout, at, first, resolved)
    if not entry.body:
        values = [*_item_values(item, *_outline_fields(item)), *_place_values(item)]
        _check_overlaps(item, parts, positions, layout, at, first, values)
    normal = face.frame.n
    footing = _footing(item)
    footprint: Footprint = footing if footing is not None else parts
    out = []
    for p1, p2 in positions:
        instance = Instance(
            item.id, 0, face.frame_at((p1, p2)).origin, normal, host, face.part_axes, depth=resolved
        )
        material = face.material_under(footprint, (p1, p2))
        out.append(
            _Copy(instance, material, face.depth_sources, face.room, face.room_sources)
        )
    if entry.cut and out:
        _check_depth(item, parts,
                     lambda mouth: min(face.material_under(mouth, (p1, p2)) for p1, p2 in positions),
                     layout, at, face.depth_sources, resolved, _most_of_flat(face, positions),
                     beyond=_standing_beyond(item, face, host, [o.instance for o in out], layout))  # fmt: skip
    return out


def _round(item: Item, layout: Layout, face: FlatFace) -> bool:
    """Whether an item's outline on a face is round about its point, the same however it is turned."""
    entry = SOLVE[item.kind]
    parts = () if entry.profiled else entry.outline(item, layout, face.axes)
    return bool(parts) and all(p.disc and p.centre == (0.0, 0.0) for p in parts)


# ----------------------------------------------------------------------
# Turned in the face's plane (V2-stage4b-0c.md, 3.3, 1b's first move)
# ----------------------------------------------------------------------
def turned_outline(item: Item, layout: Layout, axes: tuple[str, str]) -> Shape | None:
    """An item's outline on a flat face, turned by its ``place.turn``, about its point; leaning (``tilt``), its section
    by the face's plane (:mod:`forge_spec.lean`); an outline of lines its parts can't make (a hexagonal pocket's:
    SolveKind.shape), as it is or turned; None if it neither turns nor leans and its outline is its parts."""
    lean = lean_of(item, axes) if leaning(item) else None
    if lean is not None:
        return _leaning_outline(item, layout, axes, lean)
    place = _place_of(item)
    own = SOLVE[item.kind].shape(item, layout, axes)
    if own is not None:
        return own if place is None or place.turn is None else own.turned(*_turn(degrees(place.turn)))
    if place is None or place.turn is None:
        return None
    sizes = SOLVE[item.kind].turnable(item, layout, axes)
    if sizes is None:
        return None
    h1, h2, r = sizes
    return Shape.rect((0.0, 0.0), (h1, h2), (r, r, r, r)).turned(
        *_turn(degrees(place.turn))
    )


def _leaning_outline(item: Item, layout: Layout, axes: tuple[str, str], lean: Lean) -> Shape | None:
    """A leaning item's foot on its face: its cross-section drawn out along its lean by 1 / cos(tilt), turned with it
    (a post's rectangle), or the polygon round the ellipse its circle draws (a hole's widest, a boss's)."""
    sizes = SOLVE[item.kind].turnable(item, layout, axes)
    if sizes is not None:  # a post: its own half sizes along the face's axes, before it is turned
        h1, h2, r = sizes
        h1, h2 = (h1 * lean.stretch, h2) if lean.along_first else (h1, h2 * lean.stretch)
        place = _place_of(item)
        turn = _turn(degrees(place.turn)) if place is not None and place.turn is not None else (1.0, 0.0)
        return Shape.rect((0.0, 0.0), (h1, h2), (r, r, r, r)).turned(*turn)
    parts = SOLVE[item.kind].outline(item, layout, axes)
    if len(parts) != 1 or not parts[0].disc or parts[0].half[0] <= 0.0:
        return None
    r = parts[0].half[0]
    return ellipse(r * lean.stretch, r, lean.way)


def _leaning_faults(item: Item, face: FlatFace, layout: Layout, at: str) -> Lean | None:
    """A leaning item's lean on its face, or None and why not: its way not one of the face's axes, its tilt out of
    range, a countersink (a later step), or a face without the same material under all of it."""
    tilt, towards = item.get("tilt"), item.get("tilt_towards")
    if not isinstance(towards, Choice):
        layout.issue("fault", at + pointer("tilt"), "a tilt says which way it leans: give its tilt_towards")
        return None
    if towards.value[1] not in face.axes:
        layout.issue("fault", at + pointer("tilt_towards"),
                     f"it leans towards {towards.value}, which isn't one of face {face.name}'s axes {face.axes}")  # fmt: skip
        return None
    assert isinstance(tilt, Value)
    t = degrees(tilt)
    if not 0.0 < t < 90.0:
        layout.issue("fault", at + pointer("tilt"), f"a tilt is more than 0 and less than 90 degrees, not {t:g}")
        return None
    if t > MOST + EPS:
        layout.issue("unable", at + pointer("tilt"), f"Forge leans an item at most {MOST:g} degrees, for now")
        return None
    if isinstance(item.get("countersink"), Countersink):
        layout.issue("unable", at + pointer("countersink"), "Forge leans a plain or counterbored hole; a "
                     "countersunk one leaning is a later step")  # fmt: skip
        return None
    if not face.uniform:
        layout.issue("unable", at + pointer("tilt"),
                     f"face {face.name} hasn't the same material under all of it: Forge leans items on such faces "
                     "in a later step (the material along a direction, item 2b)")  # fmt: skip
        return None
    return lean_of(item, face.axes)


def _axis_vec(axis: str) -> Vec:
    k = _INDEX[axis]
    return (1.0 if k == 0 else 0.0, 1.0 if k == 1 else 0.0, 1.0 if k == 2 else 0.0)


def _turned_copies(item: Item, place: Place | None, face: FlatFace, host: tuple[str, int, str], layout: Layout,
                   at: str, first: int, resolved: float | None = None) -> list[_Copy]:  # fmt: skip
    """The copies of an item turned in the face's plane, or leaning on it: placed, fitted to the face, held apart and
    its depth checked on its outline turned, or its section by the face (forge_spec.lean)."""
    lean = None
    if leaning(item):
        lean = _leaning_faults(item, face, layout, at)
        if lean is None:
            return []
    here = at + pointer("place", "turn")
    if (lean is None and SOLVE[item.kind].turnable(item, layout, face.axes) is None
            and SOLVE[item.kind].shape(item, layout, face.axes) is None):  # fmt: skip
        parts = SOLVE[item.kind].outline(item, layout, face.axes)
        what = f"a {item.kind}" + (" with a round outline" if len(parts) == 1 and parts[0].disc else "")
        layout.issue("fault", here,
                     f"Forge turns a slot, a pocket that isn't round, a rib, a tab, a block, a post or a line of letters in a face's plane, not {what}")  # fmt: skip
        return []
    if place is not None and place.concentric:
        layout.issue(
            "fault",
            here if lean is None else at + pointer("tilt"),
            "a turned or leaning item is placed along the face's axes, not concentric with another",
        )
        return []
    shape = turned_outline(item, layout, face.axes)
    assert shape is not None
    # Placed by its turned outline (a line of letters by its line's box); fitted, held apart and its depth held
    # on what it covers turned with it (letters, their ink's box: text.md).
    positions = _face_position(place, face, item, layout, at, shape)
    if positions is None:
        return []
    entry = SOLVE[item.kind]
    covered = (_turned_covers(item, layout, face, place) if place is not None else None) or shape
    turn = degrees(place.turn) if place is not None and place.turn is not None else 0.0
    values = [
        *_item_values(item, *_outline_fields(item)),
        *_place_values(item),
        *([place.turn] if place is not None and place.turn is not None else []),
        *([item.get("tilt"), item.get("tilt_towards")] if lean is not None else []),
    ]
    how = (f"turned {turn:g}\u00b0" if lean is None
           else f"leaning {lean.tilt:g}\u00b0" + (f" and turned {turn:g}\u00b0" if turn else ""))  # fmt: skip
    if lean is None and (place is None or place.turn is None):  # an outline of its own, not turned (a hexagon)
        how = ""
    for n, (p1, p2) in enumerate(positions):
        if not face.holds(covered, (p1, p2)):
            severs = entry.cut and _is_through(item)
            layout.problem("question", at,
                           f"{item.id} copy {first + n + 1}" + (f", {how}," if how else "") + f" runs off face {face.name}"
                           + (": cut through, it could cut the part apart" if severs else ""),
                           [*values, *layout.values_of(face.sources)])  # fmt: skip
            return []
    if not entry.body:
        pair = turned_copies_overlap(covered, positions)
        if pair is not None:
            i, j = pair
            layout.problem(
                "question",
                at,
                f"copies {first + i + 1} and {first + j + 1} of {item.id} overlap",
                values,
            )
    if lean is not None:
        return _leaning_copies(item, lean, face, host, layout, at, first, positions, values)
    out = []
    for p1, p2 in positions:
        instance = Instance(
            item.id, 0, face.frame_at((p1, p2)).origin, face.frame.n, host, face.part_axes, depth=resolved
        )
        material = face.material_under(covered, (p1, p2))
        out.append(
            _Copy(instance, material, face.depth_sources, face.room, face.room_sources)
        )
    if entry.cut and out:
        _check_depth(item, (), lambda _mouth: min(face.material_under(covered, (p1, p2)) for p1, p2 in positions),
                     layout, at, face.depth_sources, resolved, _most_of_flat(face, positions, covered),
                     beyond=_standing_beyond(item, face, host, [o.instance for o in out], layout))  # fmt: skip
    return out


def _leaning_copies(item: Item, lean: Lean, face: FlatFace, host: tuple[str, int, str], layout: Layout, at: str,
                    first: int, positions: Sequence[tuple[float, float]], values: list[object]) -> list[_Copy]:  # fmt: skip
    """A leaning item's copies, placed on a face with the same material under all of it, ``T`` thick: each with its
    direction, the material along its axis that a blind cut of its radius stays in, ``(T - r sin) / cos``; a cut's
    depths held to that; what stands reaching back into the face from its foot by its half size along its lean times
    tan(tilt), which the face must have under it (forge_spec.lean)."""
    entry = SOLVE[item.kind]
    thick = face.depth_below
    direction = lean.direction(face.frame.n, face.frame.u, face.frame.v)

    def along(radius: float) -> float:
        return (thick - radius * lean.s) / lean.c

    if entry.cut:
        hole = layout.diameters.get(item.id, 0.0) / 2
        material = along(hole)
        # Its floor, square to its axis, comes down to the far side first at its lowest edge.
        _check_depth(item, (), lambda mouth: along(max(p.half[0] for p in mouth) if mouth else hole),
                     layout, at, face.depth_sources,
                     most_of=lambda mouth: along(-max(p.half[0] for p in mouth) if mouth else -hole))  # fmt: skip
    else:
        sizes = entry.turnable(item, layout, face.axes)
        if sizes is not None:
            half = sizes[0] if lean.along_first else sizes[1]
        else:
            parts = entry.outline(item, layout, face.axes)
            half = parts[0].half[0] if parts else 0.0
        reach = half * lean.tan
        material = thick
        if reach > thick - EPS:
            layout.problem("question", at,
                           f"{item.id}, leaning {lean.tilt:g}\u00b0, reaches {reach:g} mm back into face {face.name} "
                           f"from its foot, which has {thick:g} mm of material under it",
                           [*values, *layout.values_of(face.depth_sources)])  # fmt: skip
            return []
    out = []
    for p1, p2 in positions:
        instance = Instance(item.id, 0, face.frame_at((p1, p2)).origin, face.frame.n, host, face.part_axes,
                            direction=direction)  # fmt: skip
        out.append(_Copy(instance, material, face.depth_sources, face.room, face.room_sources))
    return out


def _turned_covers(item: Item, layout: Layout, face: FlatFace, place: Place) -> Shape | None:
    """What a line of letters covers turned with it: its ink's box (off its line's middle where a letter's tail or
    hook reaches past the line), turned about its point; None for anything else, which covers its outline."""
    if not SOLVE[item.kind].lettered or place.turn is None:
        return None
    parts = _covered(item, layout, face)
    if not parts:
        return None
    (ink,) = parts
    return Shape.rect(ink.centre, ink.half).turned(*_turn(degrees(place.turn)))


def turned_copies_overlap(
    shape: Shape, positions: Sequence[tuple[float, float]]
) -> tuple[int, int] | None:
    """The first two copies of a turned outline, at these positions, whose insides meet, or None (touching is apart)."""
    if len(positions) < 2:
        return None
    (l1, l2), (h1, h2) = shape.box()

    def close(j: int, i: int) -> bool:
        return shapes_overlap(shape.moved(*positions[j]), shape.moved(*positions[i]))

    return first_close_pair(positions, range(len(positions)), (h1 - l1, h2 - l2), close)


def _leaning_thread(item: Item, of: str, layout: Layout, at: str) -> None:
    """A thread on a leaning rod (step 5.4): along its lean from its far end, clear of its foot: the rod's side meets
    the face's plane up to its radius times the tangent of its lean from its point, so a thread longer than the rest
    of it is a CAN'T."""
    rod = layout.items[of]
    for copy in layout.instances.get(of, []):
        if copy.direction is None:
            continue
        c = sum(copy.direction[k] * copy.normal[k] for k in range(3))
        s = math.sqrt(max(1.0 - c * c, 0.0))
        rises = SOLVE[rod.kind].height(rod)
        diameter = rod.get("diameter")
        if rises is None or not isinstance(diameter, Value):
            return
        clear = rises[0] - mm(diameter) / 2 * s / c
        long = item.get("length")
        threaded = mm(long) if isinstance(long, Value) else rises[0]
        if threaded > clear - EPS:
            layout.issue("unable", at + pointer("length" if isinstance(long, Value) else "of"),
                         f"{of} leans on its face: a thread on it runs from its far end, clear of its foot, at most "
                         f"{clear:.3g} mm along it; this one is {threaded:g} mm")  # fmt: skip
            return


def _check_turned_edges(
    spec: PartSpec, layout: Layout, position: Mapping[str, int]
) -> None:
    """A rounding or chamfer of a leaning item's edges is a later move; so is a thread on a leaning rod. A turned
    item's edges, and those of what is on a turned item's faces, are rounded as with it upright (edges.md)."""
    for item in spec.items:
        of = item.get("of")
        if SOLVE[item.kind].threads and isinstance(of, str) and leaning(layout.items.get(of) or item):
            _leaning_thread(item, of, layout, pointer("items", position[item.id]))
        edges = item.get("edges")
        if not isinstance(edges, EdgeSet):
            continue
        target = layout.items.get(edges.of)
        if target is not None and leaning(target) and edges.which not in ("top", "vertical"):
            # Its far end's edges and those along its lean are rounded as upright, then leaned (step 5.3); its joint
            # waits for 4b.0d1.
            layout.issue("unable", pointer("items", position[item.id], "edges"),
                         f"{edges.of} leans on its face: Forge rounds and chamfers its far end's edges and those along "
                         "its lean; where it meets its face, in a later step")  # fmt: skip


#: How far past everything made so far a cut through everything is carried (mm): through the air beyond, so its far
#: end is in no face of the part.
THROUGH_PAST = 1.0


def _end_depth(item: Item, face: FlatFace, layout: Layout, at: str) -> tuple[bool, float | None]:
    """A cut through everything or up to a face (item 2b's first step), on a flat face: how deep it goes from its point,
    the same from every point of the face. Through everything: as far as everything made so far reaches behind it, and
    on past it; up to a face: to that face's plane, square to the cut, less its offset. Whether it is placed (False:
    the problem is said), and that depth (None for any other cut). Through the next face (its second step): as deep
    as the preview found it goes (None until it has: the material under its face, as through all)."""
    end = end_of(item)
    if not isinstance(end, (ThroughEverything, ThroughNext, UpToFace)):
        return True, None
    if leaning(item):
        layout.issue("unable", at + pointer("depth"),
                     "Forge cuts a leaning item through everything, through the next face or up to a face in a later "
                     "step")  # fmt: skip
        return False, None
    if isinstance(end, ThroughNext):
        return True, end.reaches
    n, centre = face.frame.n, face.centre
    if layout.motion is not None:  # a turned or leaning item's face, placed upright: where it is moved to (2b's third)
        n, centre = layout.motion.vector(n), layout.motion.point(centre)
    level = sum(centre[k] * n[k] for k in range(3))
    if isinstance(end, ThroughEverything):
        reach = 0.0
        for copies in layout.instances.values():
            for copy in copies:
                if copy.lo is None or copy.hi is None:
                    continue
                for corner in itertools.product(*zip(copy.lo, copy.hi, strict=True)):
                    reach = max(reach, level - sum(corner[k] * n[k] for k in range(3)))
        return True, reach + THROUGH_PAST
    target, name = end.face.item, end.face.face
    here = at + pointer("depth", "up_to")
    if target not in layout.instances:
        if target not in layout.items:
            layout.issue("fault", here, f"no item {target!r} to cut up to")
        return False, None  # not placed: its own problem says why
    if len(layout.instances[target]) != 1:
        layout.issue("unable", here, f"{target} has {len(layout.instances[target])} copies: Forge cuts up to a face of "
                     "an item with one, for now")  # fmt: skip
        return False, None
    other = layout.faces.get((target, 0), {}).get(name)
    if name not in KINDS[layout.kinds[target]].faces:
        layout.issue("fault", here, f"{target} has no face {name!r}")
        return False, None
    if not isinstance(other, FlatFace):
        layout.issue("unable", here, f"{target}'s {name} isn't a flat face: Forge cuts up to the plane of a flat face")
        return False, None
    m = other.frame.n
    if abs(abs(sum(m[k] * n[k] for k in range(3))) - 1.0) > EPS:
        layout.issue("unable", here, f"{target}'s {name} face isn't square to {item.id}: Forge cuts up to a face "
                     "parallel to the one it is cut into, for now")  # fmt: skip
        return False, None
    offset = mm(end.offset) if end.offset is not None else 0.0
    depth = level - sum(other.centre[k] * n[k] for k in range(3)) - offset
    if depth <= EPS:
        layout.problem("question", here, f"the plane of {target}'s {name} face"
                       + (f", {offset:g} mm back," if offset else "") + f" isn't behind {item.id}'s mouth",
                       [*([end.offset] if end.offset is not None else []), *layout.values_of(face.depth_sources)])  # fmt: skip
        return False, None
    bore = item.get("counterbore")
    if isinstance(bore, Counterbore) and mm(bore.depth) >= depth - EPS:
        layout.problem("question", at + pointer("counterbore"),
                       f"the counterbore ({mm(bore.depth):g} mm deep) is as deep as the hole goes, up to {target}'s "
                       f"{name} face ({depth:g} mm): there's no hole left below it",
                       [bore.depth, *([end.offset] if end.offset is not None else [])])  # fmt: skip
        return False, None
    return True, depth


def _next_on(item: Item) -> float | None:
    """How deep a cut through the next face goes, as the preview found it (item 2b's second step); None for any other
    end, or one the preview hasn't found yet."""
    end = end_of(item)
    return end.reaches if isinstance(end, ThroughNext) else None


def _curved_end(item: Item, layout: Layout, at: str, where: str) -> bool:
    """Round a side from outside, on a ball's surface or on a cone's side, and on a turned or leaning item's face, a
    cut goes through the next face as on a flat one, how deep as the preview finds it, and through everything, as far
    as everything made before it reaches along its axis from its point (item 2b's third step); up to a face only from
    a flat face, for now: whether this one isn't such a cut (False: the problem is said)."""
    if SOLVE[item.kind].cut and isinstance(end_of(item), UpToFace):
        layout.issue("unable", at + pointer("depth"),
                     f"Forge cuts up to a face from a flat face, for now, not {where}")  # fmt: skip
        return False
    return True


def _everything_from(point: Vec, out: Vec, layout: Layout) -> float:
    """How deep a cut through everything goes from a point, into the part along ``-out``: as far as everything made
    so far reaches behind it (each copy's box), and on past it by :data:`THROUGH_PAST` (item 2b; as :func:`_end_depth`
    on a flat face, from each copy's own point and way where they differ: round a side, on a ball or a cone, on a
    turned or leaning item's face)."""
    level = sum(point[k] * out[k] for k in range(3))
    reach = 0.0
    for copies in layout.instances.values():
        for copy in copies:
            if copy.lo is None or copy.hi is None:
                continue
            for corner in itertools.product(*zip(copy.lo, copy.hi, strict=True)):
                reach = max(reach, level - sum(corner[k] * out[k] for k in range(3)))
    return reach + THROUGH_PAST


def _flat_end_only(item: Item, layout: Layout, at: str, where: str) -> bool:
    """A cut through everything or up to a face is cut into a flat face, for now (item 2b's first step): whether this
    one, ``where`` it is, isn't such a cut (False: the problem is said)."""
    if SOLVE[item.kind].cut and isinstance(end_of(item), (ThroughEverything, ThroughNext, UpToFace)):
        layout.issue("unable", at + pointer("depth"),
                     "Forge cuts through everything, through the next face or up to a face from a flat face, for "
                     f"now, not {where}")  # fmt: skip
        return False
    return True


def cut_depth(item: Item, copy: Instance, layout: Layout) -> float | None:
    """How deep a cut goes from its point, as the solver has it: a blind one's depth, one through everything or up to a
    face as it worked it out (item 2b's first step), one through the next face as the preview found it (its second);
    None for one through the material under its face (one through the next face the preview hasn't found yet), or
    none."""
    end = end_of(item)
    if isinstance(end, Blind):
        return mm(end.depth)
    if isinstance(end, (ThroughEverything, ThroughNext, UpToFace)):
        return copy.depth
    return None


def _standing_beyond(item: Item, face: FlatFace, host: tuple[str, int, str], copies: Sequence[Instance],
                     layout: Layout) -> tuple[str, str] | None:  # fmt: skip
    """What stands on the far face of the body a cut goes into, over the cut's mouth there: the body that a blind
    cut deeper than its own would go on into (a knob's bore up through its neck into the knob standing on it), and
    that face's name; None where nothing does, or the body's far face isn't straight across from it.

    A blind cut stays in the body it is cut into and in what that stands on (frame.md): what stands on its far face
    is made on top of it. Made the other way round, the knob first and the neck standing on it, the bore up the neck
    goes on into the knob."""
    name = host[2]
    if name not in _ACROSS or face.depth_model is not None or face.less is not None or face.over is not None:
        return None
    far_key = (host[0], host[1], _ACROSS[name])
    back = layout.faces.get((host[0], host[1]), {}).get(far_key[2])
    if not isinstance(back, FlatFace) or back.local is not None or face.local is not None:
        return None
    far = back.upright()
    if not {*face.axes, *far.axes} <= {"x", "y", "z"}:  # a face's own axes (u, v): placed in them, not the part's
        return None
    across = abs(sum((a - b) * d for a, b, d in zip(far.centre, face.centre, face.frame.n, strict=True)))
    if abs(face.depth_below - across) > EPS:
        return None
    for other_id, instances in layout.instances.items():
        owner = layout.items.get(other_id)
        if owner is None or not SOLVE[owner.kind].solid or other_id == item.id:
            continue
        for other in instances:
            if other.host != far_key or other.local is not None:
                continue
            over = _in_plane(far, other.origin, _outline(owner, layout, far.axes))
            for cut in copies:
                # A drawn or turned outline, by the disc round it.
                mouth = _in_plane(face, cut.origin, _outline(item, layout, face.axes)
                                  or (disc(reach(_covered(item, layout, face))),))  # fmt: skip
                if any(_meet(m, o, far.axes, face.axes) for m in mouth for o in over):
                    return other_id, far_key[2]
    return None


def _most_of_flat(face: FlatFace, positions: Sequence[tuple[float, float]],
                  footprint: Footprint | None = None) -> Callable[[tuple[Part, ...]], float] | None:
    """The most material under a mouth on a flat face, where the face's far side curves or slopes away under it (its
    depth model: a hollow ball's floor, a hollow cone's walls, a turned or leaning item's): there a blind cut as deep
    as the least only touches it. None where it is flat: as deep as the material, the cut comes out across a face, or
    onto one beside it (a boss's top over its host's edge), the same as a through cut."""
    if face.depth_model is None:
        return None
    return lambda mouth: min(face.most_material_under(footprint if footprint is not None else mouth, (p1, p2))
                             for p1, p2 in positions)  # fmt: skip


def _most_round_a_side(face: SideFace, mouth: tuple[Part, ...], angle: float) -> float:
    """The most material a radial cut of that mouth meets round a side: into a round-ended tab's end, the farther of
    its two sides' (:meth:`SideFace._half_exits`); else until it is out all across its mouth."""
    if face.half is not None:
        return max(face._half_exits(reach(mouth), angle))
    return face.most_material_under(mouth, (angle, 0.0))


def _check_depth(item: Item, outline: tuple[Part, ...], material_of: Callable[[tuple[Part, ...]], float],
                 layout: Layout, at: str, sources: Iterable[Source], up_to: float | None = None,
                 most_of: Callable[[tuple[Part, ...]], float] | None = None,
                 beyond: tuple[str, str] | None = None) -> None:  # fmt: skip
    """A blind cut, a counterbore, a countersink or engraving no deeper than the material.

    Each is measured against the least material under its own mouth
    (``material_of`` its outline, centred on the item's position): a hole's
    under its bore, a counterbore's under its own diameter, anything else's
    under its ``outline``. A cut exactly as deep as the material breaks
    through it, the same as a through cut; a counterbore that deep leaves no
    hole below it.

    Where the far side curves or slopes away under the mouth (``most_of``,
    the most material under it, is more), a blind cut exactly as deep as the
    least only touches it there, along a line or at a point: asked about too.
    A set screw's hole into a collar's wall, as deep as the wall, met the
    bore along its middle and was built with its faces touching there (held:
    its surface wasn't closed).

    Deeper than its body, where a body stands on the far face over its mouth
    (``beyond``: a knob's bore up through its neck, the knob standing on the
    neck), it would go on into that body, which a blind cut doesn't: the
    writer's to make the two the other way round, the cut then going on into
    what its body stands on.
    """
    deep: list[tuple[str, float, tuple[Part, ...], list[object], bool]] = []
    end = end_of(item)
    hole = layout.diameters.get(item.id)
    if isinstance(end, Blind) and not (SOLVE[item.kind].embossed(item)):
        mouth = (disc(hole / 2),) if hole is not None else outline
        deep.append(("depth", mm(end.depth), mouth, [end.depth], False))
    if isinstance(end, UpToFace) and up_to is not None:  # as deep as the plane it is cut up to (item 2b's first step)
        mouth = (disc(hole / 2),) if hole is not None else outline
        deep.append(("depth", up_to, mouth, [*([end.offset] if end.offset is not None else [])], False))
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
        if name == "depth" and beyond is not None and how_deep > material + 1e-9:
            other, far = beyond
            layout.issue("fault", at + pointer(name),
                         f"{item.id} is {how_deep:g} mm deep, past the {material:g} mm of the body it is cut into, on "
                         f"into {other}, which stands on that body's {far} face: a blind cut stays in its body and "
                         f"what that stands on. Make {other} first, and stand the body {item.id} is cut into on it, "
                         "so that it goes on into it")  # fmt: skip
            continue
        touching = (not inclusive and most_of is not None and abs(how_deep - material) <= 1e-9
                    and most_of(mouth) > material + EPS)  # fmt: skip
        if how_deep > material + 1e-9 or (inclusive and how_deep >= material - 1e-9) or touching:
            layout.problem("question", at + pointer(name),
                           f"{item.id}'s {name} is {how_deep:g} mm deep in {material:g} mm of material"
                           + (", its floor just touching the far side, which falls away under the rest of it"
                              if touching else "") + ": "
                           + ("should it go through, or be shallower?" if name == "depth"
                              else "it leaves no hole below it"),
                           [*values, *layout.values_of(sources)])  # fmt: skip


def _side_instances(item: Item, face: SideFace, host: tuple[str, int, str], layout: Layout,
                    at: str, first: int) -> list[_Copy]:  # fmt: skip
    if not (_curved_end(item, layout, at, "round a side") if face.outward
            else _flat_end_only(item, layout, at, "round the inside of a bore")):  # fmt: skip
        return []
    place = _place_of(item)
    axis = face.axis
    entry = SOLVE[item.kind]
    if not entry.on_round_side:
        layout.issue("unable", at + pointer("on"),
                     f"on a round side, Forge cuts round holes and keyways and stands bosses, posts, tabs and ribs; "
                     f"not a {item.kind}, for now (a round leg or peg there is a post, a square lug a tab)")  # fmt: skip
        return []
    # A slot round a side (slot.md, "Round a side"): a keyway, along the side's axis, square to the plane touching it.
    keyway = entry.cut and not entry.round_foot
    if keyway:
        why = None
        if not face.outward or face.half is not None or face.local is not None:
            why = ("round a side, Forge cuts a slot into the side of a rod, a boss or a tube from outside, not round "
                   "what stands on a turned item's face, for now")  # fmt: skip
        elif _choice_of(item, "along") != axis:
            why = (f"round a side, Forge cuts a slot along the side's axis ({axis}), a keyway, for now, not along "
                   f"{_choice_of(item, 'along')}")  # fmt: skip
        elif isinstance(end_of(item), (ThroughNext, ThroughEverything)):
            why = "round a side, a slot goes in to a depth or right through, for now"
        if why is not None:
            layout.issue("unable", at, why)
            return []
    if place is not None and (
        (place.pattern and not PATTERN_SOLVE[place.pattern.kind].round
         and not (PATTERN_SOLVE[place.pattern.kind].along_a_side and face.half is None))
        or place.concentric
    ):
        layout.issue("unable", at + pointer("place"),
                     "on a round side, Forge places by position along the axis and angle only, and copies in a circle or "
                     "an arc round it or a row along it")  # fmt: skip
        return []
    if place is not None and place.pattern is not None:
        kind = place.pattern.kind
        row = PATTERN_SOLVE[kind].along_a_side
        extra = sorted(
            set(place.pattern.values)
            - ({"step"} if PATTERN_SOLVE[kind].steps_round else {"pitch"} if row else set())
        )
        if extra:
            layout.issue("fault", at + pointer("place", "pattern", kind),
                         f"round a side, a {kind} pattern takes only a count"
                         + (" and a step" if PATTERN_SOLVE[kind].steps_round else " and a pitch" if row else "")
                         + (f", along the side's axis {axis}" if row else "; give the first one's angle as place.angle")
                         + f", not {extra}")  # fmt: skip
            return []
        if row and place.pattern.axis != axis:
            layout.issue("fault", at + pointer("place", "pattern", kind, "axis"),
                         f"round a side, a row runs along the side's axis, {axis}, not {place.pattern.axis}")  # fmt: skip
            return []
    if place is not None and place.turn is not None:
        layout.issue("fault", at + pointer("place", "turn"),
                     "a turn turns an item in a flat face's plane; round a side, place.angle says where round it is")  # fmt: skip
        return []
    if leaning(item):
        layout.issue("fault", at + pointer("tilt"),
                     "a tilt leans an item from square to a flat face; round a side, it stands along the radius")  # fmt: skip
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
    if face.half is not None and entry.cut and _is_through(item) and not isinstance(end_of(item), ThroughNext):
        layout.issue("unable", at + pointer("depth"),
                     f"Forge cuts a blind hole into a tab's round end, or one through the next face, for now: give the hole into {host[0]} a depth")  # fmt: skip
        return []
    if place and place.angle is not None:
        angles = [degrees(place.angle)]
    elif face.half is not None:  # a round-ended tab's end: at its tip, the middle of its half
        angles = [face.middle]
        layout.assume(at, f"{item.id}: at the tip of {host[0]}'s round end; the brief doesn't say where round it")
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
        if face.half is not None and step_value is None:
            layout.issue("fault", at + pointer("place", "pattern"),
                         "round a tab's round end, copies go in an arc over its half, not all round: give the arc's "
                         "step")  # fmt: skip
            return []
        step = degrees(step_value) if step_value is not None else 360.0 / count.n
        angles = [angles[0] + step * k for k in range(count.n)]
    # A row along the side (place.md, "On a round side"): copy k (k - (count - 1)/2) * pitch along its axis from the
    # row's centre, from its minus end; from an end, the position is to its nearest copy.
    steps = [0.0]
    if place and place.pattern and PATTERN_SOLVE[place.pattern.kind].along_a_side:
        count, pitch = place.pattern.counts.get("count"), place.pattern.values.get("pitch")
        if count is None or pitch is None:
            layout.issue("fault", at + pointer("place", "pattern"), "say how many along the side, and their pitch")
            return []
        steps = [(k - (count.n - 1) / 2) * mm(pitch) for k in range(count.n)]
    nearest = 0.0
    if position is not None and position.mode == "side":
        nearest = min(steps) if (position.side or "+").startswith("-") else max(steps)
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
    for angle, step in [(a, s) for a in angles for s in steps]:
        turn = _turn(angle)
        r = face.frame.radial(*turn)
        outward = r if face.outward else (-r[0], -r[1], -r[2])
        face_axes: tuple[str, str] | None = None
        motion: Rigid | None = None
        if entry.adds and _direction_of(outward) is None:
            # Standing at an angle that isn't a frame axis's (item 3b's first step): placed as at the frame axis at or
            # below it, then turned with the side about its axis by the rest (as a turned item's faces are moved).
            below = 90.0 * math.floor(angle / 90.0)
            turn = _turn(below)
            r = face.frame.radial(*turn)
            outward = r if face.outward else (-r[0], -r[1], -r[2])
            frame = face.frame
            motion = Rigid.turn_about(frame.origin, frame.n, *_turn(angle - below))
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
        elif keyway:  # its width round the side, its length along it
            across_size, along_size = bbox(_outline(item, layout, (reference[0], axis)))
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
        along = (_along(position, half, along_size) if position else 0.0) - nearest + step
        if abs(along) + along_size > half + EPS:
            layout.problem(
                "question",
                at,
                f"{item.id} runs past the end of {host[0]}",
                along_values,
            )
        elif entry.cut and abs(along) + along_size > half - EPS:
            # Its mouth just reaching an end of the side (a slot the side's whole length, splitting a tube into a C):
            # the wall between it and the end is nothing there, as a cut touching a flat face's edge.
            layout.problem("question", at, f"{item.id} touches the end of {host[0]}'s {face.name}: the wall between "
                                           "them would be nothing there", along_values)  # fmt: skip
        if face.half is not None:
            # On a round-ended tab's end, all of it stays on the half: no further round from its middle than a
            # quarter turn, its reach round it from its point included.
            spread = math.degrees(fs.asin(min(across_size / face.radius, 1.0)))
            if abs(math.remainder(angle - face.middle, 360.0)) + spread > 90.0 + EPS:
                layout.problem("question", at,
                               f"{item.id}, at {angle:g}\u00b0, runs off the round end of {host[0]} (its half is "
                               f"from {face.middle - 90.0:g}\u00b0 to {face.middle + 90.0:g}\u00b0 round it)",
                               [*across_values, *_place_values(item)])  # fmt: skip
                return []
        origin = face.frame_at(turn, along).origin
        footprints.append((angle, along, across_size, along_size))
        out.append(
            _Copy(
                Instance(item.id, 0, origin, outward, host, face_axes, depth=_next_on(item)),
                face.wall,
                face.depth_sources,
                motion=motion,
            )
        )
    if position is None:
        layout.assume(
            at, f"{item.id}: halfway along the {axis} axis; the brief doesn't say where"
        )
    if len(footprints) > 1:
        _check_round_overlaps(item, face, footprints, layout, at, first)
    if entry.cut:
        # Round a side, only how far the mouth reaches counts: any axes give it; on a round-ended tab's end, where. A
        # keyway's, how far it reaches round the side: along the axis the side is the same all the way.
        if keyway:
            _check_depth(item, _outline(item, layout, (reference[0], axis)),
                         lambda mouth: side_material(face, bbox(mouth)[0]), layout, at, face.depth_sources,
                         most_of=lambda mouth: side_most_material(face, bbox(mouth)[0]))  # fmt: skip
        else:
            _check_depth(item, _outline(item, layout, ("x", "y")),
                         lambda mouth: min(face.material_under(mouth, (angle, 0.0)) for angle in angles), layout, at,
                         face.depth_sources,
                         most_of=lambda mouth: min(_most_round_a_side(face, mouth, angle) for angle in angles))  # fmt: skip
        bore = face.radius - face.wall
        hole = layout.diameters.get(item.id, 0.0) / 2
        if face.outward and _is_through(item) and not isinstance(end_of(item), ThroughNext) and 0 < bore <= hole + EPS:
            layout.problem("question", at + pointer("depth"),
                           f"{item.id} (\u00d8{2 * hole:g} mm) is as wide as the bore of {host[0]} "
                           f"(\u00d8{2 * bore:g} mm): through one wall only, or right across through both?",
                           [item.get("diameter"), *layout.values_of(face.radius_sources)])  # fmt: skip
        if keyway and _is_through(item) and 0 < bore <= across_size + EPS:
            layout.problem("question", at + pointer("depth"),
                           f"{item.id} ({2 * across_size:g} mm wide) is as wide as the bore of {host[0]} "
                           f"(\u00d8{2 * bore:g} mm): through one wall only, or right across through both?",
                           [item.get("width"), *layout.values_of(face.radius_sources)])  # fmt: skip
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


# ----------------------------------------------------------------------
# On a ball's or a dome's surface (item 3b's second step; place.md, "On a ball's surface")
# ----------------------------------------------------------------------
def _ball_instances(item: Item, face: BallFace, host: tuple[str, int, str], layout: Layout,
                    at: str, first: int) -> list[_Copy]:  # fmt: skip
    """Every copy of a hole, a boss or a post on a ball's or a dome's surface: placed as at its pole (standing on it as
    on a face facing that way), then turned about its centre, down to its latitude and round to its angle."""
    if not _curved_end(item, layout, at, "on a ball's surface"):
        return []
    place = _place_of(item)
    entry = SOLVE[item.kind]
    if not entry.on_curved:
        layout.issue("unable", at + pointer("on"),
                     f"on a ball's surface, Forge cuts round holes and stands bosses and posts; not a {item.kind}, "
                     "for now")  # fmt: skip
        return []
    if place is not None and ((place.pattern and not PATTERN_SOLVE[place.pattern.kind].round) or place.concentric):
        layout.issue("unable", at + pointer("place"),
                     "on a ball's surface, Forge places by a latitude and an angle round its pole only")  # fmt: skip
        return []
    if place is not None and place.axes:
        layout.issue("fault", at + pointer("place", next(iter(place.axes))),
                     "on a ball's surface, place gives a latitude and an angle round its pole, not a position along an "
                     "axis")  # fmt: skip
        return []
    if place is not None and place.turn is not None:
        layout.issue("fault", at + pointer("place", "turn"),
                     "a turn turns an item in a flat face's plane; on a ball's surface, place.angle says where round "
                     "its pole it is")  # fmt: skip
        return []
    if leaning(item):
        layout.issue("fault", at + pointer("tilt"),
                     "a tilt leans an item from square to a flat face; on a ball's surface, it stands along its "
                     "radius")  # fmt: skip
        return []
    if place is not None and place.pattern is not None:
        extra = sorted(set(place.pattern.values)
                       - ({"step"} if PATTERN_SOLVE[place.pattern.kind].steps_round else set()))  # fmt: skip
        if extra:
            kind = place.pattern.kind
            layout.issue("fault", at + pointer("place", "pattern", kind),
                         f"round a ball's pole, a {kind} pattern takes only a count"
                         + (" and a step" if PATTERN_SOLVE[kind].steps_round else "")
                         + f"; give the first one's angle as place.angle, not {extra}")  # fmt: skip
            return []
    if place is not None and place.latitude is not None:
        latitude = degrees(place.latitude)
        if not -90.0 - EPS <= latitude <= 90.0 + EPS:
            layout.issue("fault", at + pointer("place", "latitude"),
                         f"a latitude is from -90 to 90 degrees, not {latitude:g}")  # fmt: skip
            return []
    else:
        latitude = 90.0
        layout.assume(at, f"{item.id}: at the top of {host[0]}'s surface, its pole; the brief doesn't say where")
    if place is not None and place.angle is not None:
        angles = [degrees(place.angle)]
    else:
        angles = [0.0]
        if latitude < 90.0 - EPS or (place is not None and place.pattern is not None):
            layout.assume(at, f"{item.id}: at 0 degrees round the pole of {host[0]}; any angle would do")
    if place is not None and place.pattern is not None and PATTERN_SOLVE[place.pattern.kind].round:
        count = place.pattern.counts.get("count")
        if count is None:
            layout.issue("fault", at + pointer("place", "pattern"), "say how many round its pole")
            return []
        step_value = place.pattern.values.get("step")
        step = degrees(step_value) if step_value is not None else 360.0 / count.n
        angles = [angles[0] + step * k for k in range(count.n)]
    up = face.up
    # Its length round the pole (east at its point), its width along its meridian: as round a side.
    meridian, east = _REFERENCE[up[1]]
    axes = (east, meridian)
    outline = _outline(item, layout, axes)
    far = reach(outline)
    sizes = [*_item_values(item, *_outline_fields(item, axes)), *layout.values_of(face.radius_sources)]
    severs = entry.cut and _is_through(item)
    if far >= face.radius - EPS:
        layout.problem("cant" if severs else "question", at,
                       f"{item.id} ({2 * far:g} mm across) is as wide as the ball {host[0]} it is on "
                       f"(\u00d8{2 * face.radius:g} mm)", sizes)  # fmt: skip
        return []
    spread = math.degrees(fs.asin(far / face.radius))  # how far round the ball its foot reaches from its point
    if latitude - spread < face.lowest - EPS:
        where = "past the rim of the dome" if face.dome else "into what the ball stands on"
        if not face.dome and not face.standing:
            where = "round past the ball's south pole"
        layout.problem("question", at,
                       f"{item.id}, {spread:g}\u00b0 round the ball from its point at latitude {latitude:g}\u00b0, "
                       f"runs {where}", [*sizes, *([place.latitude] if place is not None else [])])  # fmt: skip
        return []
    if severs and (face.standing or face.dome) and not isinstance(end_of(item), (ThroughNext, ThroughEverything)):
        layout.issue("unable", at + pointer("depth"),
                     "Forge cuts right through a whole ball only, standing on nothing, for now: go through the next "
                     f"face, or through everything, or give the hole into {host[0]} a depth")  # fmt: skip
        return []
    if entry.cut:
        _check_depth(item, outline, lambda mouth: face.material_under(mouth, (angles[0], latitude)), layout, at,
                     face.depth_sources,
                     most_of=lambda mouth: face.most_material_under(mouth, (angles[0], latitude)))  # fmt: skip
    if len(angles) > 1:
        _check_ball_overlaps(item, face, angles, latitude, far, layout, at, first)
    frame = face.frame
    pole = face.frame_at((1.0, 0.0), (0.0, 1.0))
    out: list[_Copy] = []
    for angle in angles:
        motion: Rigid | None = None
        if abs(latitude - 90.0) > EPS or abs(math.remainder(angle, 360.0)) > EPS:
            # Down from its pole to its latitude about the line through its centre along v, then round its pole.
            down = Rigid.turn_about(frame.origin, frame.v, *_turn(90.0 - latitude))
            motion = Rigid.turn_about(frame.origin, frame.n, *_turn(angle)).after(down)
        out.append(_Copy(Instance(item.id, 0, pole.origin, pole.n, host, axes if entry.adds else None,
                                  depth=_next_on(item)),
                         face.wall, face.depth_sources, motion=motion))  # fmt: skip
    return out


def _cone_instances(item: Item, face: ConeFace, host: tuple[str, int, str], layout: Layout,
                    at: str, first: int) -> list[_Copy]:  # fmt: skip
    """Every copy of a hole, a boss or a post on a cone's side (item 3b's third step; place.md, "On a cone's side"): at
    its angle round the axis and its place along it, as round a side; along the cone's normal there. A hole goes in
    along it; a boss or a post is placed as at the frame axis at or below its angle, standing out along the radius
    there, then leaned with the side's slope about its way round and turned about the axis by the rest."""
    if not _curved_end(item, layout, at, "on a cone's side"):
        return []
    place = _place_of(item)
    entry = SOLVE[item.kind]
    axis = face.axis
    if not entry.on_curved:
        layout.issue("unable", at + pointer("on"),
                     f"on a cone's side, Forge cuts round holes and stands bosses and posts; not a {item.kind}, "
                     "for now")  # fmt: skip
        return []
    if place is not None and ((place.pattern and not PATTERN_SOLVE[place.pattern.kind].round) or place.concentric):
        layout.issue("unable", at + pointer("place"),
                     "on a cone's side, Forge places by position along the axis and angle only")  # fmt: skip
        return []
    if place is not None and place.latitude is not None:
        layout.issue("fault", at + pointer("place", "latitude"),
                     "a latitude places on a ball's surface; on a cone's side, give a position along its axis and an "
                     "angle round it")  # fmt: skip
        return []
    if place is not None and place.pattern is not None:
        extra = sorted(set(place.pattern.values)
                       - ({"step"} if PATTERN_SOLVE[place.pattern.kind].steps_round else set()))  # fmt: skip
        if extra:
            kind = place.pattern.kind
            layout.issue("fault", at + pointer("place", "pattern", kind),
                         f"round a cone, a {kind} pattern takes only a count"
                         + (" and a step" if PATTERN_SOLVE[kind].steps_round else "")
                         + f"; give the first one's angle as place.angle, not {extra}")  # fmt: skip
            return []
    if place is not None and place.turn is not None:
        layout.issue("fault", at + pointer("place", "turn"),
                     "a turn turns an item in a flat face's plane; round a cone, place.angle says where round it is")  # fmt: skip
        return []
    if leaning(item):
        layout.issue("fault", at + pointer("tilt"),
                     "a tilt leans an item from square to a flat face; on a cone's side, it stands square to the side")  # fmt: skip
        return []
    position = place.axes.get(axis) if place else None
    others = [a for a in (place.axes if place else {}) if a != axis]
    if others:
        layout.issue("fault", at + pointer("place", others[0]),
                     f"on a cone's side, position along {axis} and an angle only")  # fmt: skip
        return []
    if position is not None and position.mode == "side" and not position.to_given:
        layout.assume(at, f"{item.id}: measured from the {position.side} end to its centre, along {axis}; "
                      "the brief doesn't say to its centre or its near edge")  # fmt: skip
    if entry.cut and _is_through(item) and not isinstance(end_of(item), (ThroughNext, ThroughEverything)):
        layout.issue("unable", at + pointer("depth"),
                     "Forge cuts a blind hole into a cone's side, or one through the next face or through "
                     f"everything, for now: give the hole into {host[0]} a depth, or go through the next face or "
                     "through everything")  # fmt: skip
        return []
    if place and place.angle is not None:
        angles = [degrees(place.angle)]
    else:
        angles = [0.0]
        layout.assume(at, f"{item.id}: at 0 degrees around the {axis} axis; any angle would do")
    if place and place.pattern and PATTERN_SOLVE[place.pattern.kind].round:
        count = place.pattern.counts.get("count")
        if count is None:
            layout.issue("fault", at + pointer("place", "pattern"), "say how many around")
            return []
        step_value = place.pattern.values.get("step")
        step = degrees(step_value) if step_value is not None else 360.0 / count.n
        angles = [angles[0] + step * k for k in range(count.n)]
    reference = face.reference
    half = face.length / 2
    c, s = face.lean
    frame = face.frame
    # As round a side: its length round the cone, its width along it (up its slope, once leaned).
    across_values = [*_item_values(item, *_outline_fields(item, (reference[0], axis), 0)),
                     *layout.values_of(face.radius_sources)]  # fmt: skip
    along_values = [*_item_values(item, *_outline_fields(item, (reference[0], axis), 1)),
                    *_place_values(item, axis), *layout.values_of(face.length_sources)]  # fmt: skip
    face_axes = (axis, axis)
    if entry.adds:
        up = _direction_of(frame.radial(1.0, 0.0))
        assert up is not None
        face_axes = (next(a for a in "xyz" if a not in (up[1], axis)), axis)
        across_size, along_size = bbox(_outline(item, layout, face_axes))
    else:
        across_size = along_size = reach(_outline(item, layout, face_axes))
    # Along the axis its foot reaches its width up and down the slope (measured from an end, to its edge so), and
    # a little more where the side curves away under it, round it, at its narrowest there.
    reach_along = along_size * c
    along = _along(position, half, reach_along) if position else 0.0
    if position is None:
        layout.assume(at, f"{item.id}: halfway along the {axis} axis; the brief doesn't say where")
    if 2 * reach_along > face.length + EPS:
        layout.problem("question", at,
                       f"{item.id} ({2 * along_size:g} mm) is longer than the side of {host[0]} it is on "
                       f"({face.length:g} mm along it)", along_values)  # fmt: skip
        return []
    narrowest = min(face.radius_at(along - reach_along), face.radius_at(along + reach_along))
    if across_size >= narrowest - EPS:
        layout.problem("question", at,
                       f"{item.id} ({2 * across_size:g} mm across) is as wide as the side of {host[0]} it is on, "
                       f"there (\u00d8{2 * max(narrowest, 0.0):g} mm)", across_values)  # fmt: skip
        return []
    # Its foot is carried into the cone twice as far as the side falls away under its farthest reach, at its narrowest.
    far = reach(_outline(item, layout, face_axes)) if entry.adds else across_size
    foot = reach_along + 2 * cone_sag(face, narrowest, far) * abs(s)
    if abs(along) + foot > half + EPS:
        layout.problem("question", at, f"{item.id} runs past the end of {host[0]}'s side", along_values)
        return []
    if entry.cut:
        _check_depth(item, _outline(item, layout, ("x", "y")),
                     lambda mouth: face.material_under(mouth, (0.0, along)), layout, at, face.depth_sources,
                     most_of=lambda mouth: face.most_material_under(mouth, (0.0, along)))  # fmt: skip
    if len(angles) > 1:
        _check_cone_overlaps(item, face, angles, along, across_size, layout, at, first)
    material = face.material_under((disc(across_size),), (0.0, along))
    out: list[_Copy] = []
    for angle in angles:
        here = face.frame_at(_turn(angle), along)
        if entry.cut:
            out.append(_Copy(Instance(item.id, 0, here.origin, here.n, host, None, depth=_next_on(item)), material,
                             face.depth_sources))  # fmt: skip
            continue
        below = 90.0 * math.floor(angle / 90.0 + EPS)
        upright = face.frame_at(_turn(below), along)
        radial = frame.radial(*_turn(below))
        motion: Rigid | None = None
        if abs(s) > EPS:  # leaned with the slope, about its way round, from the radius to the normal
            motion = Rigid.turn_about(upright.origin, upright.u, c, s)
        if abs(angle - below) > EPS:
            turned = Rigid.turn_about(frame.origin, frame.n, *_turn(angle - below))
            motion = turned if motion is None else turned.after(motion)
        up = _direction_of(radial)
        assert up is not None
        axes = (next(a for a in "xyz" if a not in (up[1], axis)), axis)
        out.append(_Copy(Instance(item.id, 0, upright.origin, radial, host, axes), material, face.depth_sources,
                         motion=motion))  # fmt: skip
    return out


def _check_cone_overlaps(item: Item, face: ConeFace, angles: Sequence[float], along: float, across: float,
                         layout: Layout, at: str, first: int) -> None:  # fmt: skip
    """No two copies round a cone overlap where they come closest: standing ones at their feet, holes where they reach
    deepest (they converge towards its axis)."""
    entry = SOLVE[item.kind]
    radius = face.radius_at(along)
    if entry.cut:
        end = end_of(item)
        depth = mm(end.depth) if isinstance(end, Blind) else 0.0
        radius -= depth * face.lean[0]
        if radius <= EPS:
            return
    for j in range(len(angles)):
        for i in range(j):
            turned = math.radians(angles[j] - angles[i])
            chord = 2 * radius * abs(fs.sin(turned / 2))
            if chord < 2 * across - EPS:
                layout.problem("question", at, f"copies {first + i + 1} and {first + j + 1} of {item.id} overlap",
                               [*_item_values(item, *_outline_fields(item)), *_place_values(item)])  # fmt: skip
                return


def _check_ball_overlaps(item: Item, face: BallFace, angles: Sequence[float], latitude: float, far: float,
                         layout: Layout, at: str, first: int) -> None:  # fmt: skip
    """No two copies on a ball's surface overlap where they come closest: standing ones at their feet, holes where they
    reach deepest (they converge towards its centre; holes that reach it meet there, as a cross-drilled ball's)."""
    entry = SOLVE[item.kind]
    radius = face.radius
    if entry.cut:
        end = end_of(item)
        depth = face.wall if isinstance(end, ThroughAll) else (mm(end.depth) if isinstance(end, Blind) else 0.0)
        radius = face.radius - depth
        if radius <= EPS:
            return
    c, s = _turn(latitude)
    for j in range(len(angles)):
        for i in range(j):
            turned = math.radians(angles[j] - angles[i])
            # The angle between the two points, seen from the centre, and the chord between them at ``radius``.
            cos_apart = min(1.0, max(-1.0, s * s + c * c * fs.cos(turned)))
            chord = 2 * radius * fs.sin(fs.acos(cos_apart) / 2)
            if chord < 2 * far - EPS:
                layout.problem("question", at, f"copies {first + i + 1} and {first + j + 1} of {item.id} overlap",
                               [*_item_values(item, *_outline_fields(item)), *_place_values(item)])  # fmt: skip
                return


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
        # Every copy of the face as it names it: an arc of ribs round a side has its far faces turned with it, past
        # its first, at angles that aren't a frame axis's.
        if hosts is None or not all(_names_fit(item, on, face, layout, at) for _, face in hosts):
            layout.unplaced.add(item.id)
            continue
        placed = as_placed(item, _upright(hosts[0][1]), layout)
        layout.items[item.id] = placed
        made = _place_on_hosts(item, placed, on, hosts, layout, at)
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
    spec = placed_spec(spec, layout)
    _check_exits(spec, layout)
    _check_into_hollows(spec, layout)
    _check_turned_edges(spec, layout, position)
    # Once the bodies are placed: which of a hollowed body's edges border an
    # open face depends on the way it rises.
    layout.order = _make_order(spec, [layout.items[i.id] for i in sequence], layout)
    _check_closed(spec, layout)
    return layout


# ----------------------------------------------------------------------
# A face's own axes (schema 1.4; V2-stage4b-0c.md, 3.3, 1b's third move)
# ----------------------------------------------------------------------
def _spelled(item: Item) -> str | None:
    """How an item names its face's axes: ``"uv"``, by the face's own; ``"xyz"``, by the part's; None if it names none."""
    named = axis_names(item)
    if any(axis in FACE_OWN_AXES for _, axis in named):
        return "uv"
    return "xyz" if named else None


def _in_its_axes(item: Item, face: FlatFace) -> FlatFace:
    """The face with its axes named as the item names them: its own, u and v, where the item names them so or the face
    is turned (whose axes aren't the part's); the part's otherwise. Its frame is the same either way."""
    if face.turn != 0.0 or _spelled(item) == "uv":
        return face.spelled(FACE_OWN_AXES)
    return face


def _upright(face: Face) -> Face:
    """A face of a turned item's as it would be with its item upright; any other as it is."""
    return face.upright()


def _names_fit(item: Item, on: On, face: Face, layout: Layout, at: str) -> bool:
    """An item names a face's axes as the face has them: a turned face's only by its own, u and v; a round side's by
    neither (it is placed along its axis and by angle)."""
    spelled = _spelled(item)
    if spelled is None:
        return True
    where = next(p for p, axis in axis_names(item) if (axis in FACE_OWN_AXES) == (spelled == "uv"))
    if isinstance(face, FlatFace) and not face.axes_are_the_parts and spelled == "xyz":
        layout.issue("fault", at + where,
                     f"face {on.face} of {on.item} is turned with it: name its axes by its own, u and v; the part's "
                     "x, y and z don't run along them")  # fmt: skip
        return False
    if isinstance(face, (SideFace, ConeFace)) and spelled == "uv":
        layout.issue("fault", at + where,
                     f"u and v name a flat face's own axes; round the {on.face} of {on.item}, place along its axis "
                     f"({face.axis}) and by angle")  # fmt: skip
        return False
    return True


def as_placed(item: Item, face: Face, layout: Layout) -> Item:
    """An item on a face as every program after the solver reads it (schema 1.4): what it names along the face's own
    axes, u and v, named by the part's names for them, and, on a turned face, turned by the face's turn and its own
    (``place.turn``), an item on an aligned plane. An item that names the part's axes on a face that isn't turned is
    itself."""
    if not isinstance(face, FlatFace) or (face.turn == 0.0 and _spelled(item) != "uv"):
        return item
    names = dict(zip(FACE_OWN_AXES, face.part_axes, strict=True))

    def axis(name: str) -> str:
        return names.get(name, name)

    def way(value: str) -> str:
        return value[:-1] + axis(value[-1])

    def pattern_name(name: str) -> str:
        before, _, last = name.rpartition("_")
        return name if last not in names else (before + "_" if before else "") + names[last]

    fields = dict(item.fields)
    for name in ("along", "thickness_along", "tilt_towards"):
        chosen = fields.get(name)
        if isinstance(chosen, Choice):
            fields[name] = replace(chosen, value=way(chosen.value))
    place = _place_of(item)
    if place is not None or face.turn != 0.0:
        place = place or Place({}, None, None, None, None)
        pattern = place.pattern
        if pattern is not None:
            pattern = replace(pattern, values={pattern_name(k): v for k, v in pattern.values.items()},
                              counts={pattern_name(k): c for k, c in pattern.counts.items()},
                              axis=None if pattern.axis is None else axis(pattern.axis))  # fmt: skip
        turn = place.turn
        if face.turn != 0.0:
            own = 0.0 if turn is None else degrees(turn)
            source = turn.provenance if turn is not None else _turn_provenance(face, layout)
            turn = Value(Q(face.turn + own, "deg"), source)
        fields["place"] = replace(place, axes={axis(a): replace(p, side=None if p.side is None else way(p.side))
                                               for a, p in place.axes.items()}, pattern=pattern, turn=turn)  # fmt: skip
    return replace(item, fields=fields)


def _turn_provenance(face: FlatFace, layout: Layout) -> Provenance:
    """Where a turned face's turn comes from: the turn, as placed, of the item it is the far face of."""
    (owner, _), *_ = face.turn_sources
    turn = _turn_value(layout.items[owner])
    assert turn is not None
    return turn.provenance


def placed_spec(spec: PartSpec, layout: Layout) -> PartSpec:
    """The spec as placed: each item as every program after the solver reads it (:func:`as_placed`)."""
    items = tuple(layout.items.get(item.id, item) for item in spec.items)
    return spec if all(a is b for a, b in zip(items, spec.items, strict=True)) else replace(spec, items=items)


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


#: How far past where a cut through the next face comes out a body made after it is in its way (mm).
_CLOSED_PAST = 1.0


def _check_closed(spec: PartSpec, layout: Layout) -> None:
    """A cut through everything (item 2b's first step) goes on past everything made before it; a body made after it in
    its way would close it, the cut ending in that body, which isn't through everything: asked about, with the values
    that put them there.

    In its way: across the stretch it goes behind its mouth, and over its mouth seen along its axis, where the body
    stands on a face parallel to the cut's (its foot against the mouth's outline); else its box against the box round
    the mouth.
    """
    position = {item.id: n for n, item in enumerate(spec.items)}
    made: dict[str, int] = {}
    for k, item_id in enumerate(layout.order):
        made.setdefault(item_id, k)

    def owners_after(item: Item) -> list[Item]:
        return [owner for owner in spec.items if SOLVE[owner.kind].solid and owner.id not in layout.unplaced
                and made.get(owner.id, -1) > made.get(item.id, -1)]  # fmt: skip

    for item in spec.items:
        end = end_of(item)
        if not SOLVE[item.kind].cut or not isinstance(end, (ThroughEverything, ThroughNext)) or item.id in layout.unplaced:
            continue
        # Through the next face, it comes out at its depth: a body made after it standing over where it does closes it.
        past = _CLOSED_PAST if isinstance(end, ThroughNext) else 0.0
        how = "goes through the next face" if isinstance(end, ThroughNext) else "goes through everything made before it"
        for cut in layout.instances.get(item.id, []):
            face = layout.faces.get(cut.host[:2], {}).get(cut.host[2]) if cut.host is not None else None
            if cut.depth is None:
                continue
            if not isinstance(face, FlatFace) or (face.local is not None and isinstance(end, ThroughEverything)):
                # Round a side, on a ball or a cone, or on a turned or leaning item's face, through everything (item
                # 2b's third step): the box round all it sweeps, as wide as its mouth's widest every way.
                if isinstance(end, ThroughEverything):
                    _check_closed_swept(item, cut, owners_after(item), layout, position[item.id], how)
                continue
            n = face.frame.n
            level = sum(cut.origin[k] * n[k] for k in range(3))
            outline = _outline(item, layout, face.axes)
            mouth_turned = turned_outline(item, layout, face.axes)
            for owner in spec.items:
                if (not SOLVE[owner.kind].solid or owner.id in layout.unplaced
                        or made.get(owner.id, -1) <= made.get(item.id, -1)):  # fmt: skip
                    continue
                for other in layout.instances.get(owner.id, []):
                    if other.lo is None or other.hi is None:
                        continue
                    behind = [level - sum(c[k] * n[k] for k in range(3))
                              for c in itertools.product(*zip(other.lo, other.hi, strict=True))]  # fmt: skip
                    if max(behind) <= EPS or min(behind) >= cut.depth + past - EPS:
                        continue
                    if not _in_its_way(outline, mouth_turned, cut, face, owner, other, layout):
                        continue
                    values = [*_item_values(item, *_outline_fields(item)), *_place_values(item),
                              *_item_values(owner, *_outline_fields(owner)), *_place_values(owner)]  # fmt: skip
                    layout.problem("question", pointer("items", position[item.id]),
                                   f"{item.id} copy {cut.index + 1} {how}, and {owner.id} copy {other.index + 1}, "
                                   f"made after it, stands in its way: should {owner.id} be cut through too (made "
                                   f"first), or {item.id} stop short of it?", values)  # fmt: skip
                    break


def _check_closed_swept(item: Item, cut: Instance, owners: Sequence[Item], layout: Layout, position: int,
                        how: str) -> None:  # fmt: skip
    """A cut through everything from a curved face, or a turned or leaning item's (:func:`_check_closed`): a body made
    after it whose box meets the box round all the cut sweeps, from its point to its depth along its way, as wide as
    its mouth's widest every way, is asked about."""
    assert cut.depth is not None
    hole = layout.diameters.get(item.id)
    wide = hole / 2 if hole is not None else max(fs.hypot(abs(p.centre[0]) + p.half[0], abs(p.centre[1]) + p.half[1])
                                                 for p in _outline(item, layout, ("x", "y")))  # fmt: skip
    end = tuple(cut.origin[k] - cut.depth * cut.normal[k] for k in range(3))
    lo = tuple(min(cut.origin[k], end[k]) - wide for k in range(3))
    hi = tuple(max(cut.origin[k], end[k]) + wide for k in range(3))
    for owner in owners:
        for other in layout.instances.get(owner.id, []):
            if other.lo is None or other.hi is None:
                continue
            if any(other.hi[k] <= lo[k] + EPS or other.lo[k] >= hi[k] - EPS for k in range(3)):
                continue
            values = [*_item_values(item, *_outline_fields(item)), *_place_values(item),
                      *_item_values(owner, *_outline_fields(owner)), *_place_values(owner)]  # fmt: skip
            layout.problem("question", pointer("items", position),
                           f"{item.id} copy {cut.index + 1} {how}, and {owner.id} copy {other.index + 1}, made after "
                           f"it, stands in its way: should {owner.id} be cut through too (made first), or {item.id} "
                           "stop short of it?", values)  # fmt: skip
            return


def _in_its_way(outline: Sequence[Part], mouth_turned: Shape | None, cut: Instance, face: FlatFace, owner: Item,
                other: Instance, layout: Layout) -> bool:  # fmt: skip
    """Whether a body's copy is over a cut's mouth seen along the cut's axis (:func:`_check_closed`): standing upright
    on a face parallel to the cut's, by its foot against the mouth's outline; else by its box against the box round
    the mouth (round its turned outline however it is turned)."""
    host = layout.faces.get(other.host[:2], {}).get(other.host[2]) if other.host is not None else None
    n = face.frame.n
    if (isinstance(host, FlatFace) and other.direction is None and other.local is None and host.local is None
            and abs(abs(sum(host.frame.n[k] * n[k] for k in range(3))) - 1.0) <= EPS):  # fmt: skip
        mouth = _in_plane(face, cut.origin, outline)
        over = _in_plane(host, other.origin, _outline(owner, layout, host.axes))
        over_turned = turned_outline(owner, layout, host.axes)
        if mouth_turned is None and over_turned is None:
            return any(_meet(m, o, host.axes, face.axes) for m in mouth for o in over)
        near = _seen(mouth, mouth_turned, cut.origin, face.axes, face.axes)
        far = _seen(over, over_turned, other.origin, host.axes, face.axes)
        return any(shapes_overlap(a, b) for a in near for b in far)
    assert other.lo is not None and other.hi is not None
    turned = mouth_turned is not None
    reach = max(fs.hypot(abs(p.centre[0]) + p.half[0], abs(p.centre[1]) + p.half[1]) for p in outline) if turned else 0.0
    for j, a in enumerate(face.axes):
        k = _INDEX[a]
        low = cut.origin[k] + (-reach if turned else min(p.centre[j] - p.half[j] for p in outline))
        high = cut.origin[k] + (reach if turned else max(p.centre[j] + p.half[j] for p in outline))
        if other.hi[k] <= low + EPS or other.lo[k] >= high - EPS:
            return False
    return True


def _check_exits(spec: PartSpec, layout: Layout) -> None:
    """A cut right through its body comes out on the face across from it: not under something standing there.

    Through is through the body it is cut into; what stands on the far face
    over its mouth would close it, the cut ending in that item, which isn't
    through (a hole drilled up through a plate under a boss): asked about,
    with the values that put them there. Inside a tube's bore it comes out
    into the bore, which is open. Through a hollowed body's wall, it comes
    out on the wall's inner face, under what stands there in the hollow (a
    drain hole under a boss on a pot's inside floor).
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
            or not isinstance(end_of(item), ThroughAll)  # through everything cuts on through what stands there
            or isinstance(end_of(item), ThroughNext)  # so does one through the next face: the shape says how far
            or item.id in layout.unplaced
        ):
            continue
        for cut in layout.instances.get(item.id, []):
            if cut.host is None:
                continue
            host, index, face_name = cut.host
            faces = layout.faces.get((host, index), {})
            # Through a hollowed body's wall it comes out on the wall's other face: its inner face from outside, the
            # outside from within.
            inner = f"inner {face_name}"
            if face_name.startswith("inner "):
                far = (host, index, face_name.removeprefix("inner "))
            elif isinstance(faces.get(inner), FlatFace):
                far = (host, index, inner)
            elif face_name in _ACROSS:
                far = (host, index, _ACROSS[face_name])
            else:
                continue
            near, back = faces.get(face_name), faces.get(far[2])
            near_face = None if near is None else _upright(near)
            far_face = None if back is None else _upright(back)
            if (
                not (isinstance(near_face, FlatFace) and isinstance(far_face, FlatFace))
                or far not in standing
            ):
                continue
            # On a turned item's faces, everything is held to it upright (its faces, and what is on them, alike).
            cut = cut.local or cut
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
            mouth_turned = turned_outline(item, layout, near_face.axes)
            # Leaning, it comes out where its axis meets the far face: across / cos(tilt) along it.
            out_at = cut.origin
            if cut.direction is not None:
                square = sum(cut.direction[k] * normal[k] for k in range(3))
                out_at = tuple(cut.origin[k] - across / square * cut.direction[k] for k in range(3))  # type: ignore[assignment]
            for other in standing[far]:
                other = other.local or other
                owner = layout.items[other.item]
                over = _in_plane(
                    far_face, other.origin, _outline(owner, layout, far_face.axes)
                )
                over_turned = turned_outline(owner, layout, far_face.axes)
                if mouth_turned is None and over_turned is None:
                    met = any(
                        _meet(m, o, far_face.axes, near_face.axes)
                        for m in mouth
                        for o in over
                    )
                else:
                    near_shapes = _seen(
                        mouth, mouth_turned, out_at, near_face.axes, near_face.axes
                    )
                    far_shapes = _seen(
                        over, over_turned, other.origin, far_face.axes, near_face.axes
                    )
                    met = any(
                        shapes_overlap(a, b) for a in near_shapes for b in far_shapes
                    )
                if not met:
                    continue
                if SOLVE[owner.kind].bored and _inside_bore(
                    mouth,
                    near_face.axes,
                    other,
                    far_face,
                    owner,
                    mouth_turned,
                    out_at,
                ):
                    continue
                values = [*_item_values(item, *_outline_fields(item)), *_place_values(item),
                          *_item_values(owner, *_outline_fields(owner)), *_place_values(owner)]  # fmt: skip
                layout.problem("question", pointer("items", position[item.id]),
                               f"{item.id} copy {cut.index + 1} goes right through {host} and comes out under "
                               f"{owner.id} copy {other.index + 1} on {far[2]}: should it go on through {owner.id}, "
                               "or stop?", values)  # fmt: skip
                break


def _check_into_hollows(spec: PartSpec, layout: Layout) -> None:
    """A cut right through a hollowed body's wall comes out into the hollow all across its mouth (frame.md, "A hollowed
    body's face"; shell.md).

    The material under a closed face of a hollowed body is its wall: a cut
    right through goes through the wall and comes out on the wall's inner
    face. Where its mouth runs past the hollow's edge it is over more than
    the wall there (a side wall under a floor's rim, a floor's edge beside a
    side wall's foot): it would stop in the wall there, or, through the most
    under its mouth, go on through all of it. Neither is plainly what was
    meant: asked about, with the values that put it there. Round a hollowed
    cylinder's side, it comes out into the hollow only between the hollow's
    ends.
    """
    position = {item.id: n for n, item in enumerate(spec.items)}
    for item in spec.items:
        if (
            not SOLVE[item.kind].cut
            or type(end_of(item)) is not ThroughAll  # through the next face, or everything: as the shape says
            or item.id in layout.unplaced
        ):
            continue
        for cut in layout.instances.get(item.id, []):
            if cut.host is None:
                continue
            host, index, face_name = cut.host
            faces = layout.faces.get((host, index), {})
            near, inner = faces.get(face_name), faces.get(f"inner {face_name}") or layout.insides.get(cut.host)
            mine = cut.local or cut  # on a turned body, everything held to it upright
            placed = _place_values(item)
            if isinstance(near, SideFace) and isinstance(inner, SideFace):
                k = _INDEX[inner.axis]
                half = reach(_outline(item, layout, (near.reference[0], inner.axis)))
                lo, hi = inner.start[k], inner.start[k] + inner.length
                if lo - EPS <= mine.origin[k] - half and mine.origin[k] + half <= hi + EPS:
                    continue
                where = _place_of(item)  # where along it, not round it
                placed = [] if where is None else [p.distance for a, p in where.axes.items() if a == inner.axis]
            elif isinstance(near, FlatFace) and isinstance(inner, FlatFace):
                near_face, inner_face = near.upright(), inner.upright()
                if inner_face.axes != near_face.axes:
                    continue
                parts = _outline(item, layout, near_face.axes)
                turned = turned_outline(item, layout, near_face.axes)
                normal = near_face.frame.n
                out_at = mine.origin
                if mine.direction is not None:  # leaning, it comes out where its axis meets the inner face
                    across = abs(sum((a - b) * d for a, b, d in zip(inner_face.centre, near_face.centre, normal,
                                                                    strict=True)))  # fmt: skip
                    square = sum(mine.direction[j] * normal[j] for j in range(3))
                    out_at = tuple(mine.origin[j] - across / square * mine.direction[j] for j in range(3))  # type: ignore[assignment]
                if inner_face.holds(turned if turned is not None else parts, inner_face.frame.on(out_at), cut=True):
                    continue
            else:
                continue
            values = [*_item_values(item, *_outline_fields(item)), *placed, *layout.values_of(near.depth_sources),
                      *layout.values_of(inner.sources)]  # fmt: skip
            layout.problem("question", pointer("items", position[item.id]),
                           f"{item.id} copy {cut.index + 1} goes right through {host}'s {face_name} wall but runs past "
                           "the edge of the hollow behind it: there it would end in the wall, not come out. Should it "
                           "lie wholly over the hollow, or stop short?", values)  # fmt: skip
            break


def _seen(parts: list[tuple[Part, dict[str, float]]], turned: Shape | None, origin: Vec, axes: tuple[str, str],
          seen_axes: tuple[str, str]) -> list[Shape]:  # fmt: skip
    """An outline on a face, in the part's coordinates along the two axes ``seen_axes`` names (the same two as ``axes``,
    in either order): its turned outline, or each of its parts'."""
    first, second = seen_axes
    if turned is not None:
        moved = turned.moved(origin[_INDEX[axes[0]]], origin[_INDEX[axes[1]]])
        return [moved if axes == seen_axes else moved.swapped()]
    found = []
    for part, centre in parts:
        c = (centre[first], centre[second])
        half = part.half if axes == seen_axes else (part.half[1], part.half[0])
        found.append(Shape.disc(c, part.half[0]) if part.disc else Shape.rect(c, half))
    return found


def _inside_bore(mouth: list[tuple[Part, dict[str, float]]], axes: tuple[str, str], tube: Instance,
                 face: FlatFace, item: Item, turned: Shape | None = None, at: Vec | None = None) -> bool:  # fmt: skip
    """Whether a cut's mouth lies within the bore of a tube standing over it (a turned mouth's turned outline)."""
    r = _size(item, "inner_diameter") / 2
    first, second = axes
    o1, o2 = tube.origin[_INDEX[first]], tube.origin[_INDEX[second]]
    if turned is not None and at is not None:
        bore = Shape.disc((o1, o2), r)
        moved = turned.moved(at[_INDEX[first]], at[_INDEX[second]])
        return boundary_within(
            moved.pieces, lambda q: shape_holds(bore, q), bore.pieces
        )
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
    #: A turned item's outline (its ``parts`` then the box round it, for finding it).
    shape: Shape | None = None


def _pieces_of(p: _Print) -> list[Piece]:
    """A print's outline where it is: its turned outline, or each of its parts'."""
    if p.shape is not None:
        return list(p.shape.moved(*p.at).pieces)
    found: list[Piece] = []
    for part in p.parts:
        c = (part.centre[0] + p.at[0], part.centre[1] + p.at[1])
        found += (
            Shape.disc(c, part.half[0]) if part.disc else Shape.rect(c, part.half)
        ).pieces
    return found


def _print_within(inner: _Print, outer: _Print) -> bool:
    """Whether one print lies wholly in another; exactly, for a turned one too."""
    if inner.shape is None and outer.shape is None:
        return outline_within(inner.parts, inner.at, outer.parts, outer.at)
    pieces = _pieces_of(inner)
    if outer.shape is not None:
        region = outer.shape.moved(*outer.at)
        return boundary_within(pieces, lambda q: shape_holds(region, q), region.pieces)
    return boundary_within(
        pieces,
        lambda q: _point_in_parts(outer.parts, outer.at, q[0], q[1]),
        _pieces_of(outer),
    )


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
    turned = turned_outline(item, layout, face.axes)
    if turned is None and SOLVE[item.kind].profiled:
        # An extrusion's or a revolution's foot is its outline, not parts (generated part 2279: a pulley's foot, read
        # as nothing, was taken for wholly within a pocket of its own outline beside it).
        turned = _footing(item)
    if turned is None:
        parts = _outline(item, layout, face.axes)
        here = _Print(
            item.id, copy.index, parts, face.frame.on(copy.origin), bbox(parts)
        )
    else:
        (l1, l2), (h1, h2) = turned.box()
        box = (Part(((l1 + h1) / 2, (l2 + h2) / 2), ((h1 - l1) / 2, (h2 - l2) / 2)),)
        here = _Print(
            item.id, copy.index, box, face.frame.on(copy.origin), bbox(box), turned
        )
    cuts = SOLVE[item.kind].cut
    found = layout.footprints.setdefault(host, _Footprints(face))
    for other in found.standing_in(here) if cuts else found.cuts_round(here):
        standing, mouth = (other, here) if cuts else (here, other)
        if not _boxed(standing, mouth) or not _print_within(standing, mouth):
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


def _place_on_hosts(item: Item, placed_item: Item, on: On, hosts: list[tuple[int, Face]], layout: Layout,
                    at: str) -> list[Instance]:  # fmt: skip
    """Every copy of an item, on every copy of its host, numbered in order: placed on each as the item names the face's
    axes, and standing as placed (:func:`as_placed`)."""
    copies: list[_Copy] = []
    motions: list[Rigid | None] = []
    rounded: list[bool] = []  # each copy's host face curved (round a side, on a ball or a cone)
    for host_index, face in hosts:
        host = (on.item, host_index, on.face)
        motion = face.local
        if motion is not None:
            # A face of a turned item's (1b's third move, step 2), or the round side of what stands on one (step 5.2):
            # placed on as that face upright, then moved.
            place = _place_of(item)
            if place is not None and place.concentric:
                layout.issue("unable", at + pointer("place", "concentric"),
                             f"{on.item} is turned: Forge places an item concentric with another on its faces in a "
                             "later step")  # fmt: skip
                return []
            if item.id in layout.shells:
                layout.issue("unable", at, f"{on.item} is turned: Forge hollows what stands on its faces in a later step")
                return []
            # Through the next face, through everything and up to a face too (item 2b's third step): placed upright,
            # how deep along its axis where it is moved to. Round the side of what stands on one, as round any side.
            face = _upright(face)
            host_item = layout.items.get(on.item)
            if isinstance(face, SideFace) and host_item is not None and leaning(host_item) \
                    and (not SOLVE[item.kind].cut or leaning(item)):  # fmt: skip
                # A leaning item's round side (V2-stage4b-0c.md 3.3): only a hole square to it, which stays where the
                # side is clear of its foot.
                layout.issue("unable", at + (pointer("tilt") if leaning(item) else ""),
                             f"{on.item} leans: Forge only cuts into its round side, square to it, and stands or leans "
                             "nothing round it, for now")  # fmt: skip
                return []
            if isinstance(face, FlatFace) and not isinstance(face.depth_model, Slant) and host_item is not None \
                    and leaning(host_item) and leaning(item):  # fmt: skip
                # A leaning box's side: what is cut into it or stands on it, square to it (step 5's sides).
                layout.issue("unable", at + pointer("tilt"),
                             f"{on.item} leans: Forge leans nothing on its side, for now")  # fmt: skip
                return []
            if isinstance(face, FlatFace) and isinstance(face.depth_model, Slant) and SOLVE[item.kind].cut \
                    and isinstance(end_of(item), ThroughAll) and not isinstance(end_of(item), ThroughNext):  # fmt: skip
                layout.issue("unable", at + pointer("depth"),
                             f"{on.item} leans: a cut right through its {on.face} face would come out on the face it "
                             "leans on, for now; give it a depth, or go through the next face")  # fmt: skip
                return []
        kind = _HOSTS[type(face)]
        named = _in_its_axes(item, face) if isinstance(face, FlatFace) else face
        layout.motion = motion
        try:
            found = kind.copies(item, named, host, len(hosts), layout, at, len(copies))
        finally:
            layout.motion = None
        if len(copies) + len(found) > MAX_COPIES:
            layout.issue("unable", at, f"more than {MAX_COPIES:,} copies of {item.id} on every "
                         f"copy of {on.item}: Forge places at most {MAX_COPIES:,} of one item")  # fmt: skip
            return []
        for copy in found:
            index = len(copies)
            placed = Instance(item.id, index, copy.instance.origin, copy.instance.normal, copy.instance.host,
                              copy.instance.face_axes, direction=copy.instance.direction, depth=copy.instance.depth)  # fmt: skip
            kind.numbered(item, placed, face, host, copy, layout, at)
            moving = _then(motion, copy.motion)
            if moving is not None:
                _moved_faces((item.id, index), moving, layout, item)
            copies.append(
                _Copy(
                    placed,
                    copy.material,
                    copy.depth_sources,
                    copy.room,
                    copy.room_sources,
                )
            )
            motions.append(moving)
            rounded.append(not isinstance(face, FlatFace))
    if not SOLVE[item.kind].stands:
        found_cuts = [_moved_instance(c.instance, m) for c, m in zip(copies, motions, strict=True)]
        if isinstance(end_of(item), ThroughEverything):
            # Through everything from a curved face, or a turned or leaning item's (item 2b's third step): from each
            # copy's own point along its own way, where it is on the part.
            found_cuts = [cut if m is None and not curved else _deep(cut, _everything_from(cut.origin, cut.normal, layout))
                          for cut, m, curved in zip(found_cuts, motions, rounded, strict=True)]  # fmt: skip
        return found_cuts
    standing: list[Instance] = []
    height = height_of(item)
    item = placed_item
    for copy, motion in zip(copies, motions, strict=True):
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
        host_face = _host_face(inst, layout)
        placed = _standing(item, inst, up, layout, at, on.item, None if host_face is None else _upright(host_face),
                           copy.depth_sources)  # fmt: skip
        if isinstance(_host_face(inst, layout), SideFace):
            _round_footed(item, layout, (item.id, placed.index), up)
        elif isinstance(_host_face(inst, layout), (BallFace, ConeFace)):
            _curved_footed(item, layout, (item.id, placed.index), _host_face(inst, layout))
        if motion is not None:
            _moved_faces((item.id, placed.index), motion, layout, item)
            if not _clear_of_the_lean(item, on, placed, motion, layout, at):
                return []
            placed = _moved_instance(placed, motion)
        standing.append(placed)
    return standing


def _clear_of_the_lean(item: Item, on: On, placed: Instance, motion: Rigid, layout: Layout, at: str) -> bool:
    """What stands on a leaning box's side stays clear of the face the box leans on (V2-stage4b-0c.md 3.3, step 5's
    sides): every corner of the box round it, as it stands upright on the side and moved with the box, is over that
    face's plane. Whether it is (False: it is asked about)."""
    host_item = layout.items.get(on.item)
    if host_item is None or not leaning(host_item) or placed.lo is None or placed.hi is None:
        return True
    index = placed.host[1] if placed.host is not None else 0
    leaner = next((c for c in layout.instances.get(on.item, []) if c.index == index and c.host is not None), None)
    plane = layout.faces.get(leaner.host[:2], {}).get(leaner.host[2]) if leaner is not None and leaner.host else None
    if not isinstance(plane, FlatFace):
        return True
    n, o = plane.frame.n, plane.frame.origin
    lo, hi = placed.lo, placed.hi
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    low = math.inf
    for c in corners:
        q = motion.point(c)
        low = min(low, (q[0] - o[0]) * n[0] + (q[1] - o[1]) * n[1] + (q[2] - o[2]) * n[2])
    if low > EPS:
        return True
    layout.problem("question", at, f"{item.id} reaches down to the face {on.item} leans on, {-low:g} mm past it: "
                   "should it be shorter, or stand higher up the side?",
                   [*_item_values(item, "height", "length"), *_place_values(item)])  # fmt: skip
    return False


def _deep(cut: Instance, depth: float) -> Instance:
    """A cut's copy as deep as ``depth``, and the upright one it was placed as, where it was moved."""
    return replace(cut, depth=depth, local=None if cut.local is None else replace(cut.local, depth=depth))


def _then(outer: Rigid | None, inner: Rigid | None) -> Rigid | None:
    """``inner``, then ``outer``: a copy's own turn round a side (item 3b), then its host's motion onto the part."""
    if inner is None:
        return outer
    return inner if outer is None else outer.after(inner)


def _moved_instance(inst: Instance, motion: Rigid | None) -> Instance:
    """A copy placed upright on a face of a turned item's, moved by that item's motion (1b's third move, step 2)."""
    if motion is None:
        return inst
    lo, hi = motion.box(inst.lo, inst.hi) if inst.lo is not None and inst.hi is not None else (None, None)
    return replace(inst, origin=motion.point(inst.origin), normal=motion.vector(inst.normal), lo=lo, hi=hi,
                   direction=None if inst.direction is None else motion.vector(inst.direction), frame=motion,
                   local=inst)  # fmt: skip


def _moved_faces(key: tuple[str, int], motion: Rigid, layout: Layout, item: Item) -> None:
    """A copy's faces found upright, moved by its motion: a flat face's centre moved, a round side kept upright (step 5.2),
    each with the motion onto the part."""
    faces = layout.faces.get(key, {})
    for name, face in list(faces.items()):
        if isinstance(face, FlatFace):
            faces[name] = _moved(face, motion)
        else:
            faces[name] = replace(face, local=motion if face.local is None else motion.after(face.local))


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
    """What stands over an opening, and a pocket's floor: turned with a turned face (schema 1.4)."""
    assert isinstance(face, FlatFace)
    if not SOLVE[item.kind].lettered:
        _check_over_openings(item, placed, _in_its_axes(item, face), host, layout, at)
    item = layout.items[item.id]  # as placed
    key = (item.id, placed.index)
    if turned_outline(item, layout, face.part_axes) is not None:
        if SOLVE[item.kind].cut:  # a standing one's faces are its standing's (_standing_turned)
            _turned_floor(item, placed, face, copy, layout)
        return
    SOLVE[item.kind].floor(item, placed, face, copy.material, key, layout)
    if face.turn != 0.0:
        faces = layout.faces.get(key, {})
        for name, found in list(faces.items()):
            if isinstance(found, FlatFace):
                faces[name] = replace(found, turn=face.turn, turn_sources=face.turn_sources)


def _turned_floor(item: Item, placed: Instance, face: FlatFace, copy: _Copy, layout: Layout) -> None:
    """A turned pocket's floor (schema 1.4): turned with it, the material under its face less its depth under it, where
    its face has the same material under all of it; closed on any other face, as a turned cut's other faces are."""
    key = (item.id, placed.index)
    layout.faces.setdefault(key, {})
    SOLVE[item.kind].floor(item, placed, face, copy.material, key, layout)
    turn = _turn_value(item)
    for name in KINDS[item.kind].faces:
        found = layout.faces[key].get(name)
        if isinstance(found, FlatFace) and turn is None:  # unturned, an outline of its own (a hexagonal pocket's)
            if face.turn != 0.0:
                layout.faces[key][name] = replace(found, turn=face.turn, turn_sources=face.turn_sources)
        elif isinstance(found, FlatFace) and face.uniform and turn is not None:
            layout.faces[key][name] = replace(found, less=None, turn=degrees(turn), turn_sources=((item.id, "place"),))
        elif name not in layout.closed.get(key, {}):
            layout.close(key, name, "unable", _TURNED_FACES.format(item.id))


def _side_copies(item: Item, face: Face, host: tuple[str, int, str], host_count: int, layout: Layout, at: str,
                 first: int) -> list[_Copy]:  # fmt: skip
    assert isinstance(face, SideFace)
    return _side_instances(item, face, host, layout, at, first)


def _nothing_more(item: Item, placed: Instance, face: Face, host: tuple[str, int, str], copy: _Copy, layout: Layout,
                  at: str) -> None:  # fmt: skip
    return None


def _ball_copies(item: Item, face: Face, host: tuple[str, int, str], host_count: int, layout: Layout, at: str,
                 first: int) -> list[_Copy]:  # fmt: skip
    assert isinstance(face, BallFace)
    return _ball_instances(item, face, host, layout, at, first)


def _cone_copies(item: Item, face: Face, host: tuple[str, int, str], host_count: int, layout: Layout, at: str,
                 first: int) -> list[_Copy]:  # fmt: skip
    assert isinstance(face, ConeFace)
    return _cone_instances(item, face, host, layout, at, first)


#: Each kind of face an item can be put on, by its class.
_HOSTS: Mapping[type, _Host] = {
    FlatFace: _Host(_flat_copies, _flat_numbered),
    SideFace: _Host(_side_copies, _nothing_more),
    BallFace: _Host(_ball_copies, _nothing_more),
    ConeFace: _Host(_cone_copies, _nothing_more),
}


def _host_face(inst: Instance, layout: Layout) -> Face | None:
    if inst.host is None:
        return None
    item_id, index, name = inst.host
    return layout.faces.get((item_id, index), {}).get(name)


def _curved_footed(item: Item, layout: Layout, key: tuple[str, int], face: Face | None) -> None:
    """A boss or a post standing on a ball's surface or a cone's side (item 3b's second and third steps): its faces
    take nothing, for now."""
    where = "a cone's side" if isinstance(face, ConeFace) else "a ball's surface"
    for name in list(layout.faces.get(key, {})):
        layout.close(key, name, "unable", f"{item.id} stands on {where}: its faces take nothing, for now")


def _round_footed(item: Item, layout: Layout, key: tuple[str, int], up: str) -> None:
    """A feature standing round a side: its far face and its flat sides take things (place.md, "Round a side").

    Its box stays the box from its point, as its height is measured, and its
    flat sides are that box's: from its point out, wholly clear of the side
    it stands on, where its foot follows the curve below them
    (docs/definitions/frame.md). Its other faces (a boss's round side) take
    nothing, for now.
    """
    far = SOLVE[item.kind].far_face(up)
    for name, face in list(layout.faces.get(key, {}).items()):
        if name != far and not (isinstance(face, FlatFace) and up[1] in face.axes):
            layout.close(key, name, "unable",
                         f"{item.id} stands round a side: only its far face and its flat sides take anything, "
                         "for now")  # fmt: skip
