"""Reading a drafted spec, item by item.

The spec writer answers with JSON shaped by :mod:`forge_spec.schema`. This
module turns it into typed items, keeping every good item and reporting every
fault in one round, each at its JSON Pointer (rule R8). A faulty item is left
out and named; it never takes the rest of the draft with it.

What a draft looks like::

    {
      "spec_format": 1,
      "name": "mounting plate",
      "items": [
        {"id": "plate", "kind": "block", "words": [1, 2],
         "length": {"value": 80, "unit": "mm", "from": {"words": [4, 5]}},
         "width":  {"value": 50, "unit": "mm", "from": {"words": [8, 9]}},
         "height": {"value": 5,  "unit": "mm", "from": {"words": [12, 13]}}},
        {"id": "corner_holes", "kind": "hole", "words": [17, 18],
         "on": {"item": "plate", "face": "+z"},
         "diameter": {"value": 4.5, "unit": "mm", "from": {"words": [16]}},
         "depth": {"through": true, "from": {"assumed": "mounting holes go through"}},
         "count": {"count": 4, "from": {"words": [15]}},
         "place": {"pattern": {"corners": {
             "inset_x": {"value": 6, "unit": "mm", "from": {"words": [26, 27]}},
             "inset_y": {"value": 6, "unit": "mm", "from": {"words": [26, 27]}}}}}}
      ],
      "not_modelled": [{"words": [0], "reason": "the material is not a shape"}],
      "silent": [{"sentence": 2, "reason": "it says how the part will be used"}]
    }
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from forge_numeric import scalar as fs
from forge_units.dimension import DIMENSIONLESS, LENGTH

from .problems import (
    MAX_NAME,
    MAX_REASON,
    Problems,
    clean_text,
    one_line,
    pointer,
    unknown_keys,
)
from .schema import (
    AXES,
    FACE_OWN_AXES,
    IN_FACE_AXES,
    KINDS,
    NUMBER_SOURCES,
    PRESENT,
    STATED_SOURCES,
    Category,
    FieldSpec,
    FieldType,
    KindSpec,
)
from .tables import canonical_designation
from .values import (
    Count,
    Provenance,
    Value,
    made_note,
    read_count,
    read_number,
    read_provenance,
    read_value,
)
from .versions import CURRENT, VersionError, migrate
from .words import WordRef

__all__ = [
    "FITS",
    "GRADES",
    "PATTERN_ANGLES",
    "PATTERN_FIELDS",
    "PATTERN_REQUIRED",
    "SPEC_FORMAT",
    "AxisPosition",
    "Choice",
    "Counterbore",
    "Countersink",
    "Designation",
    "EdgeSet",
    "Faces",
    "Fit",
    "Item",
    "NotModelled",
    "On",
    "PartSpec",
    "Pattern",
    "Place",
    "Profile",
    "Requirements",
    "Segment",
    "Silent",
    "Text",
    "Through",
    "UpTo",
    "axis_names",
    "read_draft",
]

#: The legacy version field's one value: a draft that says ``"spec_format": 1`` is version 1.0 (:mod:`.versions`).
SPEC_FORMAT = 1
_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_ANGLE_UNITS = frozenset({"deg", "rad", "rev", "arcmin", "arcsec"})


@dataclass(frozen=True)
class On:
    item: str
    face: str


@dataclass(frozen=True)
class Choice:
    value: str
    provenance: Provenance


@dataclass(frozen=True)
class Text:
    text: str
    provenance: Provenance


@dataclass(frozen=True)
class Designation(Text):
    """A standard part named by a text, such as a thread: M8, M8x1.

    Read in its one spelling (:func:`forge_spec.tables.canonical_designation`),
    and checked like a fit's part, not like engraved letters: the cited words
    must name it whole, pitch included.
    """


@dataclass(frozen=True)
class Through:
    """A cut through: the material under its face (``{"through": true}``), or, ``everything``, all of the part made so
    far behind its mouth along its axis, cavities and all (``{"through_all": true}``; schema 1.7, item 2b's first
    step)."""

    provenance: Provenance
    everything: bool = False


@dataclass(frozen=True)
class UpTo:
    """A cut's floor in the plane of a flat face of an item made before it, square to the cut, ``offset`` back towards
    its mouth (``{"up_to": {"item": ..., "face": ...}, "offset": size}``; schema 1.7, item 2b's first step)."""

    face: On
    offset: Value | None
    provenance: Provenance


@dataclass(frozen=True)
class Fit:
    """A standard size: a clearance hole for a screw, a tapped hole, a bearing seat."""

    fit: str  # "clearance", "tapped", "bearing_seat"
    for_: str  # "M4", "#6", "608"
    grade: str  # "fine", "normal", "coarse" (clearance); "" otherwise
    provenance: Provenance


@dataclass(frozen=True)
class Counterbore:
    diameter: Value
    depth: Value


@dataclass(frozen=True)
class Countersink:
    diameter: Value
    angle: Value


@dataclass(frozen=True)
class EdgeSet:
    of: str
    which: str
    where_meets: str | None
    words: WordRef


@dataclass(frozen=True)
class Faces:
    faces: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True)
class Segment:
    """One segment of an outline: a straight line, or an arc about a centre."""

    to: tuple[float, float]
    centre: tuple[float, float] | None = None  # None: a straight line
    clockwise: bool = False


@dataclass(frozen=True)
class Profile:
    """A closed outline in millimetres, in the plane of its two coordinates."""

    start: tuple[float, float]
    segments: tuple[Segment, ...]
    provenance: Provenance


@dataclass(frozen=True)
class AxisPosition:
    """Where along one axis of the face an item sits.

    ``centred``: on the face's centre line along this axis. ``side``: at
    ``distance`` from the face's edge on that side ("-x"), measured to the
    item's centre or to its nearest edge. ``offset``: at ``distance`` from the
    face's centre, signed.
    """

    mode: str  # "centred", "side", "offset"
    side: str | None
    distance: Value | None
    to: str  # "centre" or "edge"
    provenance: Provenance | None
    #: Whether the draft said what it is measured to; when it didn't, it is to
    #: the centre, and the solver records that as an assumption.
    to_given: bool = True


@dataclass(frozen=True)
class Pattern:
    """Several copies: corners, rectangle, ends, row, grid or circle."""

    kind: str
    values: Mapping[str, Value]
    counts: Mapping[str, Count]
    axis: str | None
    axis_provenance: Provenance | None = None


@dataclass(frozen=True)
class Place:
    axes: Mapping[str, AxisPosition]
    angle: Value | None
    pattern: Pattern | None
    concentric: str | None
    concentric_provenance: Provenance | None
    #: On a flat face, the item turned in the face's plane by this angle, from the face's first axis towards its second
    #: (schema 1.2; V2-stage4b-0c.md, 3.3, 1b's first move).
    turn: Value | None = None
    #: On a ball's or a dome's surface, how far from its equator towards its pole (schema 1.6; V2-stage4b-0c.md, 3.4,
    #: item 3b's second step); ``angle`` is then how far round its pole.
    latitude: Value | None = None


FieldValue = (
    Value
    | Count
    | On
    | Choice
    | Text
    | Through
    | UpTo
    | Fit
    | Counterbore
    | Countersink
    | EdgeSet
    | Faces
    | Profile
    | Place
    | str
)


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    fields: Mapping[str, FieldValue]
    words: WordRef

    @property
    def spec(self) -> KindSpec:
        return KINDS[self.kind]

    def get(self, name: str) -> FieldValue | None:
        return self.fields.get(name)


@dataclass(frozen=True)
class NotModelled:
    words: WordRef
    reason: str


@dataclass(frozen=True)
class Silent:
    sentence: int
    reason: str


@dataclass(frozen=True)
class Requirements:
    """What the part must be beyond its shape (plan, 4.1): for now, its material.

    The material is the brief's words for it, exactly ("PETG", "aluminium
    6061"), or an assumption with its reason. It is recorded, not judged:
    which grade a name means, and whether it is strong enough, is for the
    strength and print checks (stage 6). Loads, mass, fits and the printer
    follow there.
    """

    material: Text | None = None


@dataclass(frozen=True)
class PartSpec:
    name: str
    items: tuple[Item, ...]
    not_modelled: tuple[NotModelled, ...] = ()
    silent: tuple[Silent, ...] = ()
    requirements: Requirements = Requirements()

    def item(self, item_id: str) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)


# ----------------------------------------------------------------------
# Field readers
# ----------------------------------------------------------------------
def _object(
    raw: Any, at: str, problems: Problems, what: str, keys: set[str]
) -> Mapping[str, Any] | None:
    if not isinstance(raw, Mapping):
        problems.fault(at, f"{what} is an object")
        return None
    unknown = unknown_keys(raw, keys)
    if unknown:
        problems.fault(at, f"unknown field(s) {unknown}")
    return raw


def _length(raw: Any, at: str, problems: Problems) -> Value | None:
    value = read_value(raw, at, problems)
    if value is not None and value.quantity.unit.dimension != LENGTH:
        problems.fault(at + pointer("unit"), f"a length, got {value.unit!r}")
        return None
    if value is not None and min(value.nominal, value.made.nominal) < 0:
        problems.fault(
            at + pointer("value"), f"a size can't be negative{made_note(value)}"
        )
        return None
    return value


def _angle(raw: Any, at: str, problems: Problems) -> Value | None:
    value = read_value(raw, at, problems, NUMBER_SOURCES)
    if value is not None and not (
        value.quantity.unit.dimension == DIMENSIONLESS and value.unit in _ANGLE_UNITS
    ):
        problems.fault(
            at + pointer("unit"), f"an angle in deg or rad, got {value.unit!r}"
        )
        return None
    return value


def _choice(
    raw: Any, at: str, problems: Problems, choices: tuple[str, ...]
) -> Choice | None:
    obj = _object(
        raw, at, problems, 'a choice {"choose": ..., "from": ...}', {"choose", "from"}
    )
    if obj is None:
        return None
    value = obj.get("choose")
    if value not in choices:
        problems.fault(
            at + pointer("choose"), f"choose one of {list(choices)}, got {value!r}"
        )
        return None
    provenance = read_provenance(
        obj.get("from"), at + pointer("from"), problems, STATED_SOURCES
    )
    return None if provenance is None else Choice(str(value), provenance)


def _text(raw: Any, at: str, problems: Problems) -> Text | None:
    obj = _object(
        raw, at, problems, 'text {"text": ..., "from": ...}', {"text", "from"}
    )
    if obj is None:
        return None
    text = obj.get("text")
    if not isinstance(text, str) or not text.strip():
        problems.fault(at + pointer("text"), "the text can't be empty")
        return None
    if not clean_text(text):
        problems.fault(at + pointer("text"), "the text must be plain printable text")
        return None
    provenance = read_provenance(
        obj.get("from"), at + pointer("from"), problems, STATED_SOURCES
    )
    return None if provenance is None else Text(text, provenance)


def _designation(raw: Any, at: str, problems: Problems) -> Designation | None:
    text = _text(raw, at, problems)
    if text is None:
        return None
    named = _canonical(text.text, at + pointer("text"), problems)
    return Designation(named, text.provenance)


def _canonical(name: str, at: str, problems: Problems) -> str:
    """A standard part's one spelling, noting a change; a name Forge doesn't know is kept as given."""
    canonical = canonical_designation(name)
    if canonical is None:
        return name.strip()
    if canonical != name:
        problems.note(at, f"{name!r} read as {canonical!r}")
    return canonical


def _depth(raw: Any, at: str, problems: Problems) -> Value | Through | UpTo | None:
    for key in ("through", "through_all"):
        if not (isinstance(raw, Mapping) and key in raw):
            continue
        obj = _object(raw, at, problems, "a through depth", {key, "from"})
        if obj is None:
            return None
        if obj.get(key) is not True:
            problems.fault(at + pointer(key), f'write "{key}": true, or give a depth')
            return None
        provenance = read_provenance(
            obj.get("from"), at + pointer("from"), problems, STATED_SOURCES
        )
        return None if provenance is None else Through(provenance, everything=key == "through_all")
    if isinstance(raw, Mapping) and "up_to" in raw:
        obj = _object(raw, at, problems, "a depth up to a face", {"up_to", "offset", "from"})
        if obj is None:
            return None
        face = _on(obj.get("up_to"), at + pointer("up_to"), problems)
        offset = _length(obj["offset"], at + pointer("offset"), problems) if "offset" in obj else None
        provenance = read_provenance(obj.get("from"), at + pointer("from"), problems, STATED_SOURCES)
        if face is None or provenance is None or ("offset" in obj and offset is None):
            return None
        return UpTo(face, offset, provenance)
    value = _length(raw, at, problems)
    if value is not None and min(value.nominal, value.made.nominal) <= 0:
        problems.fault(
            at + pointer("value"), f"a depth is more than 0{made_note(value)}"
        )
        return None
    return value


#: The standard fits a diameter may be, and the grades each takes ("" for none).
FITS = frozenset({"clearance", "tapped", "bearing_seat"})
GRADES: Mapping[str, tuple[str, ...]] = {
    "clearance": ("fine", "normal", "coarse"),
    "tapped": ("",),
    "bearing_seat": ("",),
}


def _diameter(raw: Any, at: str, problems: Problems) -> Value | Fit | None:
    if isinstance(raw, Mapping) and "fit" in raw:
        obj = _object(
            raw, at, problems, "a standard fit", {"fit", "for", "grade", "from"}
        )
        if obj is None:
            return None
        fit = obj.get("fit")
        if not isinstance(fit, str) or fit not in FITS:
            problems.fault(
                at + pointer("fit"), f"fit is one of {sorted(FITS)}, got {fit!r}"
            )
            return None
        target = one_line(obj.get("for"), 40)
        if target is None:
            problems.fault(
                at + pointer("for"), "say what it fits, in plain text: M4, M8x1, 608"
            )
            return None
        target = _canonical(target, at + pointer("for"), problems)
        grade = obj.get("grade", "normal" if fit == "clearance" else "")
        if not isinstance(grade, str) or grade not in GRADES[str(fit)]:
            problems.fault(
                at + pointer("grade"), f"grade is one of {list(GRADES[str(fit)])}"
            )
            return None
        provenance = read_provenance(
            obj.get("from"), at + pointer("from"), problems, STATED_SOURCES
        )
        return (
            None
            if provenance is None
            else Fit(str(fit), target, str(grade), provenance)
        )
    value = _length(raw, at, problems)
    if value is not None and min(value.nominal, value.made.nominal) <= 0:
        problems.fault(
            at + pointer("value"), f"a diameter is more than 0{made_note(value)}"
        )
        return None
    return value


def _on(raw: Any, at: str, problems: Problems) -> On | None:
    obj = _object(raw, at, problems, '{"item": ..., "face": ...}', {"item", "face"})
    if obj is None:
        return None
    item, face = obj.get("item"), obj.get("face")
    if not isinstance(item, str) or not isinstance(face, str):
        problems.fault(at, "name the item and the face it stands on")
        return None
    return On(item, face)


def _edges(raw: Any, at: str, problems: Problems) -> EdgeSet | None:
    obj = _object(
        raw, at, problems, "an edge set", {"of", "which", "where_meets", "words"}
    )
    if obj is None:
        return None
    of, which = obj.get("of"), obj.get("which")
    if not isinstance(of, str) or not isinstance(which, str):
        problems.fault(at, 'say which edges: {"of": item, "which": ...}')
        return None
    meets = obj.get("where_meets")
    if which == "joint" and not isinstance(meets, str):
        problems.fault(at + pointer("where_meets"), "a joint names the item it meets")
        return None
    if which != "joint" and "where_meets" in obj:
        problems.fault(
            at + pointer("where_meets"), "only a joint names the item it meets"
        )
        return None
    words = _words_or_empty(obj.get("words"), at + pointer("words"), problems)
    return EdgeSet(of, which, meets if isinstance(meets, str) else None, words)


def _faces(raw: Any, at: str, problems: Problems) -> Faces | None:
    obj = _object(raw, at, problems, '{"faces": [...], "from": ...}', {"faces", "from"})
    if obj is None:
        return None
    faces = obj.get("faces")
    if not isinstance(faces, list) or not all(isinstance(f, str) for f in faces):
        problems.fault(
            at + pointer("faces"), "a list of face names, empty for a sealed hollow"
        )
        return None
    if len(set(faces)) != len(faces):
        problems.fault(at + pointer("faces"), "each face is listed once")
        return None
    if faces != sorted(faces):
        problems.note(at + pointer("faces"), f"faces read as {sorted(faces)}")
    provenance = read_provenance(
        obj.get("from"), at + pointer("from"), problems, STATED_SOURCES
    )
    return None if provenance is None else Faces(tuple(sorted(faces)), provenance)


def _point(raw: Any, at: str, problems: Problems) -> tuple[float, float] | None:
    if not isinstance(raw, list) or len(raw) != 2:
        problems.fault(at, "a point is [a, b] in millimetres")
        return None
    a = read_number(raw[0], at + pointer(0), problems)
    b = read_number(raw[1], at + pointer(1), problems)
    return None if a is None or b is None else (a, b)


def _profile(raw: Any, at: str, problems: Problems) -> Profile | None:
    obj = _object(
        raw, at, problems, "an outline", {"start", "segments", "unit", "from"}
    )
    if obj is None:
        return None
    before = len(problems.faults)
    if obj.get("unit", "mm") != "mm":
        problems.fault(at + pointer("unit"), "outline coordinates are in mm")
    start = _point(obj.get("start"), at + pointer("start"), problems)
    raw_segments = obj.get("segments")
    segments: list[Segment] = []
    if not isinstance(raw_segments, list) or len(raw_segments) < 2:
        problems.fault(at + pointer("segments"), "an outline has at least two segments")
    else:
        for n, seg in enumerate(raw_segments):
            here = at + pointer("segments", n)
            seg_obj = _object(seg, here, problems, "a segment",
                              {"line_to", "arc_to", "centre", "clockwise"})  # fmt: skip
            if seg_obj is None:
                continue
            if ("line_to" in seg_obj) == ("arc_to" in seg_obj):
                problems.fault(here, 'a segment is {"line_to": [a, b]} or '
                               '{"arc_to": [a, b], "centre": [a, b], "clockwise": ...}')  # fmt: skip
                continue
            if "line_to" in seg_obj:
                if {"centre", "clockwise"} & set(seg_obj):
                    problems.fault(
                        here, "a straight segment has no centre or direction"
                    )
                    continue
                to = _point(seg_obj["line_to"], here + pointer("line_to"), problems)
                if to is not None:
                    segments.append(Segment(to))
                continue
            to = _point(seg_obj["arc_to"], here + pointer("arc_to"), problems)
            centre = _point(seg_obj.get("centre"), here + pointer("centre"), problems)
            clockwise = seg_obj.get("clockwise", False)
            if not isinstance(clockwise, bool):
                problems.fault(
                    here + pointer("clockwise"), "clockwise is true or false"
                )
                continue
            if to is not None and centre is not None:
                segments.append(Segment(to, centre, clockwise))
    provenance = read_provenance(
        obj.get("from"), at + pointer("from"), problems, STATED_SOURCES
    )
    if len(problems.faults) > before or start is None or provenance is None:
        return None
    if fs.dist(start, segments[-1].to) > 1e-6:
        problems.fault(
            at + pointer("segments"),
            "an outline is closed: the last segment ends at the start",
        )
        return None
    point = start
    for n, seg in enumerate(segments):
        if fs.dist(point, seg.to) <= 1e-6:
            problems.fault(
                at + pointer("segments", n),
                "a segment goes somewhere: it ends where it starts",
            )
            return None
        if seg.centre is not None:
            off = abs(fs.dist(point, seg.centre) - fs.dist(seg.to, seg.centre))
            if off > 1e-3:
                problems.fault(at + pointer("segments", n),
                               "an arc ends on its circle: its end is not as far from its centre as its start is")  # fmt: skip
                return None
            if off > 1e-12:
                segments[n] = Segment(
                    seg.to, _on_bisector(point, seg.to, seg.centre), seg.clockwise
                )
        point = seg.to
    profile = Profile(start, tuple(segments), provenance)
    crossing = outline_crosses_itself(profile)
    if crossing is not None:
        problems.fault(at + pointer("segments", crossing),
                       "an outline doesn't cross or touch itself: this segment meets another one")  # fmt: skip
        return None
    back = outline_turns_back(profile)
    if back is not None:
        problems.fault(at + pointer("segments", back),
                       "an outline doesn't touch itself: it turns straight back where this segment starts")  # fmt: skip
        return None
    return profile


def outline_turns_back(profile: Profile) -> int | None:
    """The first segment that leaves its start the way the one before it arrived from, or None.

    There the outline would turn through half a turn, its two sides meeting
    at no angle: it touches itself (a cusp), however it goes on.
    """
    ends = [profile.start, *(seg.to for seg in profile.segments)]

    def tangent(n: int, at_end: bool) -> tuple[float, float]:
        seg, a, b = profile.segments[n], ends[n], ends[n + 1]
        if seg.centre is None:
            length = fs.dist(a, b)
            return ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        x = b if at_end else a
        dx, dy = x[0] - seg.centre[0], x[1] - seg.centre[1]
        r = fs.hypot(dx, dy)
        return (dy / r, -dx / r) if seg.clockwise else (-dy / r, dx / r)

    count = len(profile.segments)
    for n in range(count):
        before = tangent((n - 1) % count, True)
        after = tangent(n, False)
        if before[0] * after[0] + before[1] * after[1] <= -1.0 + 1e-12:
            return n
    return None


def _on_bisector(a: tuple[float, float], b: tuple[float, float],
                 centre: tuple[float, float]) -> tuple[float, float]:  # fmt: skip
    """An arc's centre as read (extrusion.md): of the circles through both its ends, the one whose centre is nearest the centre written.

    That centre is the written one moved square to the chord onto the line
    through the chord's middle square to it; written within 0.001 mm of its
    circle, it moves no further than that.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = (
        (centre[0] - (a[0] + b[0]) / 2) * dx + (centre[1] - (a[1] + b[1]) / 2) * dy
    ) / (dx * dx + dy * dy)
    return (centre[0] - t * dx, centre[1] - t * dy)


def outline_points(
    profile: Profile, step_degrees: float = 5.0
) -> list[tuple[float, float, int]]:
    """The outline as a closed chain of points, arcs followed every ``step_degrees``: (a, b, segment).

    Each point carries the segment it ends; the first is the start (segment -1).
    """
    points = [(profile.start[0], profile.start[1], -1)]
    here = profile.start
    for n, seg in enumerate(profile.segments):
        if seg.centre is not None:
            cx, cy = seg.centre
            a0 = fs.atan2(here[1] - cy, here[0] - cx)
            a1 = fs.atan2(seg.to[1] - cy, seg.to[0] - cx)
            sweep = (a0 - a1) if seg.clockwise else (a1 - a0)
            sweep %= 2 * math.pi
            if sweep <= 1e-12:
                sweep = 2 * math.pi  # an arc back to where it starts is a full turn
            steps = max(1, math.ceil(math.degrees(sweep) / step_degrees))
            radius = fs.dist(here, seg.centre)
            sign = -1.0 if seg.clockwise else 1.0
            for k in range(1, steps):
                t = a0 + sign * sweep * k / steps
                points.append((cx + radius * fs.cos(t), cy + radius * fs.sin(t), n))
        points.append((seg.to[0], seg.to[1], n))
        here = seg.to
    return points


def outline_crosses_itself(profile: Profile) -> int | None:
    """The first segment that meets a segment it doesn't follow on from, or None."""
    chain = outline_points(profile)
    edges = [
        (chain[k][:2], chain[k + 1][:2], chain[k + 1][2]) for k in range(len(chain) - 1)
    ]

    def orient(
        a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
    ) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def meet(
        p: tuple[float, float],
        q: tuple[float, float],
        r: tuple[float, float],
        t: tuple[float, float],
    ) -> bool:
        tol = 1e-9 * max(1.0, *(abs(v) for pt in (p, q, r, t) for v in pt))
        d1, d2, d3, d4 = (
            orient(r, t, p),
            orient(r, t, q),
            orient(p, q, r),
            orient(p, q, t),
        )
        if ((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol)) and (
            (d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol)
        ):
            return True

        def on(
            a: tuple[float, float],
            b: tuple[float, float],
            c: tuple[float, float],
            d: float,
        ) -> bool:
            return (
                abs(d) <= tol
                and min(a[0], b[0]) - tol <= c[0] <= max(a[0], b[0]) + tol
                and (min(a[1], b[1]) - tol <= c[1] <= max(a[1], b[1]) + tol)
            )

        return on(r, t, p, d1) or on(r, t, q, d2) or on(p, q, r, d3) or on(p, q, t, d4)

    count = len(edges)
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue  # the last edge comes back to the first
            if meet(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return edges[j][2]
    return None


def _words_or_empty(raw: Any, at: str, problems: Problems) -> WordRef:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(
        isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in raw
    ):
        problems.fault(at, "words are a list of word numbers")
        return ()
    ordered = tuple(sorted(set(raw)))
    if list(ordered) != raw:
        problems.note(at, f"word numbers read as {list(ordered)}")
    return ordered


def _axis_position(
    raw: Any, at: str, problems: Problems, axis: str
) -> AxisPosition | None:
    obj = _object(
        raw,
        at,
        problems,
        "a position along an axis",
        {"centred", "side", "distance", "to", "offset"},
    )
    if obj is None:
        return None
    modes = [m for m in ("centred", "offset", "side") if m in obj]
    if (
        len(modes) != 1
        or ("distance" in obj) != (modes == ["side"])
        or ("to" in obj and modes != ["side"])
    ):
        problems.fault(at, 'a position is one of {"centred": ...}, {"offset": length}, or '
                       '{"side": ..., "distance": length, "to": "centre" or "edge"}')  # fmt: skip
        return None
    if "centred" in obj:
        provenance = read_provenance(
            obj["centred"], at + pointer("centred"), problems, STATED_SOURCES
        )
        return (
            None
            if provenance is None
            else AxisPosition("centred", None, None, "centre", provenance)
        )
    to = obj.get("to", "centre")
    if to not in ("centre", "edge"):
        problems.fault(
            at + pointer("to"), 'measured "to" the "centre" or the near "edge"'
        )
        return None
    if "offset" in obj:
        value = read_value(obj["offset"], at + pointer("offset"), problems)
        if value is None:
            return None
        if value.quantity.unit.dimension != LENGTH:
            problems.fault(at + pointer("offset"), "an offset is a length")
            return None
        return AxisPosition("offset", None, value, str(to), None)
    side = obj.get("side")
    if side not in (f"+{axis}", f"-{axis}"):
        problems.fault(
            at + pointer("side"),
            f'say which side it is measured from: "+{axis}" or "-{axis}"',
        )
        return None
    distance = _length(obj.get("distance"), at + pointer("distance"), problems)
    return (
        None
        if distance is None
        else AxisPosition("side", str(side), distance, str(to), None, "to" in obj)
    )


#: Each pattern: its values (lengths, and the angles in PATTERN_ANGLES), its
#: counts, and whether it runs along an axis it names.
PATTERN_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...], bool]] = {
    # kind: (lengths/angles, counts, needs an axis). Every pattern also takes
    # "each": how many at each position, as the brief says ("one in each
    # corner"); only one is supported.
    # Along an axis, a value or count is named by it: the part's, or the face's own u and v (schema 1.4).
    "corners": (("inset_x", "inset_y", "inset_z", "inset_u", "inset_v"), ("each",), False),
    "rectangle": (("x", "y", "z", "u", "v"), ("each",), False),
    "ends": (("inset",), ("each",), True),
    "row": (("pitch",), ("count", "each"), True),
    "grid": (("pitch_x", "pitch_y", "pitch_z", "pitch_u", "pitch_v"),
             ("count_x", "count_y", "count_z", "count_u", "count_v", "each"), False),
    "circle": (("diameter", "start"), ("count", "each"), False),
    # Part of a circle: copies a fixed angle apart ("two holes 90 degrees apart").
    "arc": (("diameter", "start", "step"), ("count", "each"), False),
}  # fmt: skip

#: Pattern values that are angles; every other pattern value is a length.
PATTERN_ANGLES = frozenset({"start", "step"})
#: What each pattern must give wherever it is (a circle or arc on a flat face
#: also needs its diameter; corners, rectangles and grids need their values
#: along both axes of the face).
PATTERN_REQUIRED: Mapping[str, tuple[str, ...]] = {
    "ends": ("inset",),
    "row": ("pitch", "count"),
    "circle": ("count",),
    "arc": ("count", "step"),
}


def _pattern(raw: Any, at: str, problems: Problems) -> Pattern | None:
    if not isinstance(raw, Mapping) or len(raw) != 1:
        problems.fault(
            at, f"a pattern is one of {sorted(PATTERN_FIELDS)}, as {{kind: {{...}}}}"
        )
        return None
    kind, body = next(iter(raw.items()))
    if kind not in PATTERN_FIELDS:
        problems.fault(at, f"unknown pattern {kind!r}; one of {sorted(PATTERN_FIELDS)}")
        return None
    lengths, counts, needs_axis = PATTERN_FIELDS[kind]
    allowed = {*lengths, *counts, *({"axis"} if needs_axis else set())}
    obj = _object(body, at + pointer(kind), problems, f"a {kind} pattern", allowed)
    if obj is None:
        return None
    values: dict[str, Value] = {}
    for name in lengths:
        if name in obj:
            reader = _angle if name in PATTERN_ANGLES else _length
            value = reader(obj[name], at + pointer(kind, name), problems)
            if value is not None:
                values[name] = value
    tallies: dict[str, Count] = {}
    for name in counts:
        if name in obj:
            count = read_count(obj[name], at + pointer(kind, name), problems)
            if count is not None and count.n < 1:
                problems.fault(
                    at + pointer(kind, name, "count"), "a pattern places at least one"
                )
            elif count is not None:
                tallies[name] = count
    axis: Choice | None = None
    if needs_axis:
        axis = _choice(obj.get("axis"), at + pointer(kind, "axis"), problems, IN_FACE_AXES)
        if axis is None:
            return None
    missing = [
        n
        for n in PATTERN_REQUIRED.get(kind, ())
        if n not in values and n not in tallies
    ]
    if missing:
        problems.fault(at + pointer(kind), f"a {kind} pattern needs {missing}")
        return None
    return Pattern(
        str(kind),
        values,
        tallies,
        axis.value if axis else None,
        axis.provenance if axis else None,
    )


def _place(raw: Any, at: str, problems: Problems) -> Place | None:
    obj = _object(
        raw,
        at,
        problems,
        "a placement",
        {*IN_FACE_AXES, "angle", "turn", "latitude", "pattern", "concentric"},
    )
    if obj is None:
        return None
    before = len(problems.faults)
    axes: dict[str, AxisPosition] = {}
    for axis in IN_FACE_AXES:
        if axis in obj:
            position = _axis_position(obj[axis], at + pointer(axis), problems, axis)
            if position is not None:
                axes[axis] = position
    angle = (
        _angle(obj["angle"], at + pointer("angle"), problems)
        if "angle" in obj
        else None
    )
    turn = (
        _angle(obj["turn"], at + pointer("turn"), problems) if "turn" in obj else None
    )
    latitude = (
        _angle(obj["latitude"], at + pointer("latitude"), problems) if "latitude" in obj else None
    )
    pattern = (
        _pattern(obj["pattern"], at + pointer("pattern"), problems)
        if "pattern" in obj
        else None
    )
    concentric: str | None = None
    concentric_provenance: Provenance | None = None
    if "concentric" in obj:
        con = _object(obj["concentric"], at + pointer("concentric"), problems,
                      '{"item": ..., "from": ...}', {"item", "from"})  # fmt: skip
        if con is not None:
            if not isinstance(con.get("item"), str):
                problems.fault(
                    at + pointer("concentric", "item"),
                    "name the item it is concentric with",
                )
            else:
                concentric = str(con["item"])
                concentric_provenance = read_provenance(
                    con.get("from"),
                    at + pointer("concentric", "from"),
                    problems,
                    STATED_SOURCES,
                )
    if len(problems.faults) > before:
        return None
    return Place(axes, angle, pattern, concentric, concentric_provenance, turn, latitude)


def _counterbore(raw: Any, at: str, problems: Problems) -> Counterbore | None:
    obj = _object(raw, at, problems, "a counterbore", {"diameter", "depth"})
    if obj is None:
        return None
    diameter = _positive(obj.get("diameter"), at + pointer("diameter"), problems)
    depth = _positive(obj.get("depth"), at + pointer("depth"), problems)
    return None if diameter is None or depth is None else Counterbore(diameter, depth)


def _countersink(raw: Any, at: str, problems: Problems) -> Countersink | None:
    obj = _object(raw, at, problems, "a countersink", {"diameter", "angle"})
    if obj is None:
        return None
    diameter = _positive(obj.get("diameter"), at + pointer("diameter"), problems)
    angle = _angle(obj.get("angle"), at + pointer("angle"), problems)
    if angle is not None and not all(
        0 < a < 180 for a in (angle.nominal_in("deg"), angle.made_in("deg"))
    ):
        problems.fault(at + pointer("angle"),
                       f"a countersink's angle is between 0 and 180 degrees{made_note(angle)}")  # fmt: skip
        return None
    return None if diameter is None or angle is None else Countersink(diameter, angle)


def _positive(raw: Any, at: str, problems: Problems) -> Value | None:
    value = _length(raw, at, problems)
    if value is not None and min(value.nominal, value.made.nominal) <= 0:
        problems.fault(
            at + pointer("value"), f"this size is more than 0{made_note(value)}"
        )
        return None
    return value


def _read_field(
    spec: FieldSpec, raw: Any, at: str, problems: Problems
) -> FieldValue | None:
    t = spec.type
    if t is FieldType.LENGTH:
        return _length(raw, at, problems)
    if t is FieldType.ANGLE:
        return _angle(raw, at, problems)
    if t is FieldType.COUNT:
        return read_count(raw, at, problems)
    if t is FieldType.DEPTH:
        return _depth(raw, at, problems)
    if t is FieldType.DIAMETER:
        return _diameter(raw, at, problems)
    if t is FieldType.ON:
        return _on(raw, at, problems)
    if t is FieldType.ITEM:
        if not isinstance(raw, str):
            problems.fault(at, "the id of another item")
            return None
        return raw
    if t is FieldType.CHOICE:
        return _choice(raw, at, problems, spec.choices)
    if t is FieldType.TEXT:
        return _text(raw, at, problems)
    if t is FieldType.DESIGNATION:
        return _designation(raw, at, problems)
    if t is FieldType.PLACE:
        return _place(raw, at, problems)
    if t is FieldType.EDGES:
        return _edges(raw, at, problems)
    if t is FieldType.PROFILE:
        return _profile(raw, at, problems)
    if t is FieldType.FACES:
        return _faces(raw, at, problems)
    if t is FieldType.COUNTERBORE:
        return _counterbore(raw, at, problems)
    if t is FieldType.COUNTERSINK:
        return _countersink(raw, at, problems)
    raise AssertionError(f"no reader for {t}")  # pragma: no cover - every type has one


def _read_item(raw: Any, at: str, problems: Problems, seen: set[str]) -> Item | None:
    if not isinstance(raw, Mapping):
        problems.fault(at, "an item is an object")
        return None
    before = len(problems.faults)
    item_id, kind = raw.get("id"), raw.get("kind")
    if not isinstance(item_id, str) or not _ID.match(item_id):
        problems.fault(
            at + pointer("id"),
            "an id is lower case letters, digits and _, starting with a letter",
        )
        item_id = None
    elif item_id in seen:
        problems.fault(at + pointer("id"), f"the id {item_id!r} is already used")
        item_id = None
    else:
        seen.add(item_id)  # even if the item has faults: a second one is still a clash
    if not isinstance(kind, str) or kind not in KINDS:
        problems.fault(
            at + pointer("kind"), f"kind is one of {list(KINDS)}, got {kind!r}"
        )
        return None
    spec = KINDS[str(kind)]
    unknown = unknown_keys(raw, ("id", "kind", "words", *spec.field_names))
    if unknown:
        problems.fault(at, f"a {kind} has no field(s) {unknown}")
    fields: dict[str, FieldValue] = {}
    for field_spec in spec.fields:
        here = at + pointer(field_spec.name)
        given = field_spec.name in raw and raw[field_spec.name] is not None
        if field_spec.name in raw and raw[field_spec.name] is None:
            problems.note(here, "null read as not given")
        applies = _applies(field_spec, raw, spec)
        if not applies:
            if given:
                other, when = field_spec.only_when or ("", "")
                problems.fault(here, f"a {kind}'s {field_spec.name} applies only "
                               + (f"when it has an {other}" if when == PRESENT
                                  else f"when its {other} is {when}"))  # fmt: skip
            continue
        if not given:
            if field_spec.required:
                problems.fault(
                    here, f"a {kind} needs its {field_spec.name}: {field_spec.meaning}"
                )
            continue
        faults = len(problems.faults)
        value = _read_field(field_spec, raw[field_spec.name], here, problems)
        if value is not None:
            fields[field_spec.name] = value
        elif len(problems.faults) == faults:  # a reader that gave nothing says why
            problems.fault(here, f"the {field_spec.name} could not be read")
    words = _words_or_empty(raw.get("words"), at + pointer("words"), problems)
    if not words:
        problems.fault(at + pointer("words"), "cite the words this item comes from")
    if item_id is None or len(problems.faults) > before:
        return None
    return Item(item_id, str(kind), fields, words)


def _applies(field_spec: FieldSpec, raw: Mapping[str, Any], spec: KindSpec) -> bool:
    """Whether a field applies, given the item's other fields (``only_when``)."""
    if field_spec.only_when is None:
        return True
    other, when = field_spec.only_when
    value = raw.get(other)
    if when == PRESENT:
        return value is not None
    chosen = value.get("choose") if isinstance(value, Mapping) else None
    if chosen not in spec.field(other).choices:
        return True  # the other field is faulty; it says so itself
    return bool(chosen == when)


def _list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def read_draft(raw: Any) -> tuple[PartSpec | None, Problems]:
    """Read a drafted spec, keeping every good item and reporting every fault."""
    problems = Problems()
    if not isinstance(raw, Mapping):
        problems.fault("", "a draft is a JSON object")
        return None, problems
    version = CURRENT
    try:
        raw, version, _made = migrate(raw)
    except VersionError as error:
        problems.fault(pointer(error.field), str(error))
    unknown = unknown_keys(
        raw,
        (
            "schema_version",
            "spec_format",
            "name",
            "items",
            "not_modelled",
            "silent",
            "requirements",
        ),
    )
    if unknown:
        problems.fault("", f"unknown field(s) {unknown}")
    name = one_line(raw.get("name"), MAX_NAME)
    if name is None:
        problems.fault(
            pointer("name"),
            f"give the part a short name (at most {MAX_NAME} characters), in plain text",
        )
        name = "part"
    raw_items = raw.get("items")
    items: list[Item] = []
    if not isinstance(raw_items, list) or not raw_items:
        problems.fault(pointer("items"), "a spec has at least one item")
    else:
        seen: set[str] = set()
        for n, raw_item in enumerate(raw_items):
            item = _read_item(raw_item, pointer("items", n), problems, seen)
            if item is not None:
                items.append(item)
                place = item.get("place")
                if (
                    isinstance(place, Place)
                    and place.turn is not None
                    and version < (1, 2)
                ):
                    problems.fault(pointer("items", n, "place", "turn"),
                                   'a turn is schema 1.2\'s: give the draft\'s "schema_version": "1.2"')  # fmt: skip
                if isinstance(place, Place) and place.latitude is not None and version < (1, 6):
                    problems.fault(pointer("items", n, "place", "latitude"),
                                   'a latitude is schema 1.6\'s: give the draft\'s "schema_version": "1.6"')  # fmt: skip
                depth = item.get("depth")
                if ((isinstance(depth, Through) and depth.everything) or isinstance(depth, UpTo)) and version < (1, 7):
                    problems.fault(pointer("items", n, "depth"),
                                   'a depth through all or up to a face is schema 1.7\'s: give the draft\'s '
                                   '"schema_version": "1.7"')  # fmt: skip
                # A body leans in 1.5 (step 3), a hole, a boss or a post in 1.3.
                since = (1, 5) if KINDS[item.kind].category is Category.BODY else (1, 3)
                for leans in ("tilt", "tilt_towards"):
                    if item.get(leans) is not None and version < since:
                        problems.fault(pointer("items", n, leans),
                                       f'a {item.kind}\'s {leans} is schema {since[0]}.{since[1]}\'s: give the '
                                       f'draft\'s "schema_version": "{since[0]}.{since[1]}"')  # fmt: skip
                _check_axis_names(item, pointer("items", n), version, problems)
    for listed in ("not_modelled", "silent"):
        if not isinstance(raw.get(listed, []), list):
            problems.fault(pointer(listed), f"{listed} is a list")
    not_modelled: list[NotModelled] = []
    for n, entry in enumerate(_list(raw.get("not_modelled"))):
        at = pointer("not_modelled", n)
        obj = _object(entry, at, problems, "a not-modelled entry", {"words", "reason"})
        if obj is None:
            continue
        words = _words_or_empty(obj.get("words"), at + pointer("words"), problems)
        reason = one_line(obj.get("reason"), MAX_REASON)
        if not words or reason is None:
            problems.fault(at, f"cite the words and give the reason they aren't modelled, in one line "
                               f"of at most {MAX_REASON} characters")  # fmt: skip
            continue
        not_modelled.append(NotModelled(words, reason))
    silent: list[Silent] = []
    for n, entry in enumerate(_list(raw.get("silent"))):
        at = pointer("silent", n)
        obj = _object(entry, at, problems, "a silent sentence", {"sentence", "reason"})
        if obj is None:
            continue
        sentence, reason = obj.get("sentence"), one_line(obj.get("reason"), MAX_REASON)
        if isinstance(sentence, bool) or not isinstance(sentence, int) or sentence < 0:
            problems.fault(at + pointer("sentence"), "a sentence number")
            continue
        if reason is None:
            problems.fault(at + pointer("reason"), f"say why it says nothing about the shape, in one line "
                                                   f"of at most {MAX_REASON} characters")  # fmt: skip
            continue
        silent.append(Silent(sentence, reason))
    requirements = _requirements(raw.get("requirements"), problems)
    return PartSpec(
        str(name).strip(),
        tuple(items),
        tuple(not_modelled),
        tuple(silent),
        requirements,
    ), problems


def axis_names(item: Item) -> list[tuple[str, str]]:
    """Each axis an item names in its face, where: (the pointer below the item, the axis), as a position, a pattern's
    value, count or axis, an ``along``, a ``thickness_along`` or a lean's way names it (``"u"``, ``"x"``; a side or a way
    by its axis)."""
    found: list[tuple[str, str]] = []
    place = item.get("place")
    if isinstance(place, Place):
        found += [(pointer("place", axis), axis) for axis in place.axes]
        pattern = place.pattern
        if pattern is not None:
            here = pointer("place", "pattern", pattern.kind)
            for name in (*pattern.values, *pattern.counts):
                axis = name.rpartition("_")[2]
                if axis in IN_FACE_AXES and (name == axis or name.rpartition("_")[0] in _ALONG_AN_AXIS):
                    found.append((here + pointer(name), axis))
            if pattern.axis is not None:
                found.append((here + pointer("axis"), pattern.axis))
    for name in ("along", "thickness_along", "tilt_towards"):
        chosen = item.get(name)
        if isinstance(chosen, Choice) and chosen.value[-1] in IN_FACE_AXES:
            found.append((pointer(name), chosen.value[-1]))
    return found


#: What a pattern value or count along an axis is named by, before the axis: "inset_x", "count_u".
_ALONG_AN_AXIS = frozenset({"inset", "pitch", "count"})


def _check_axis_names(item: Item, at: str, version: tuple[int, int], problems: Problems) -> None:
    """A face's own axes, u and v, are schema 1.4's; an item names its face's axes one way, the face's own or the
    part's, not both."""
    named = axis_names(item)
    own = [(where, axis) for where, axis in named if axis in FACE_OWN_AXES]
    if own and version < (1, 4):
        problems.fault(at + own[0][0],
                       'a face\'s own axes, u and v, are schema 1.4\'s: give the draft\'s "schema_version": "1.4"')  # fmt: skip
    part = [(where, axis) for where, axis in named if axis in AXES]
    if own and part:
        problems.fault(at + part[0][0],
                       f"{item.id} names its face's axes by the face's own u and v at {own[0][0]}: name them all so, "
                       f"not by the part's {part[0][1]} as well")  # fmt: skip


def _requirements(raw: Any, problems: Problems) -> Requirements:
    """The part's requirements: absent, or an object with what it says."""
    if raw is None:
        return Requirements()
    at = pointer("requirements")
    obj = _object(raw, at, problems, 'requirements {"material": ...}', {"material"})
    if obj is None:
        return Requirements()
    material = obj.get("material")
    return Requirements(
        _text(material, at + pointer("material"), problems)
        if material is not None
        else None
    )
