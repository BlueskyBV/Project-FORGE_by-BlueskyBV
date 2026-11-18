"""What the placement solver's kinds share (the ``solve`` role's leaf: it imports neither the kinds' modules, but for the registry when asked, nor ``placement.py``).

Moved from ``placement.py`` at stage 4b.0b's step 3, unchanged: reading an
item's values, routing a problem by what it rests on, directions in the
frame, a box's and a round body's bounds and faces; and the parts of
placing a profiled body and hollowing a body several kinds share.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from forge_spec.draft import (
    Choice,
    Counterbore,
    Countersink,
    Item,
    Place,
    Profile,
)
from forge_spec.ends import ThroughAll, end_of
from forge_spec.frames import Frame, cos_sin
from forge_spec.geometry import (
    EPS,
    BallFace,
    ConeFace,
    FlatFace,
    SideFace,
    Source,
    Taper,
    Vec,
)
from forge_spec.outline import Shape
from forge_spec.schema import DIRECTIONS, FACE_AXES
from forge_spec.values import Count, Value
from forge_spec.values import Source as ValueSource

if TYPE_CHECKING:
    from forge_spec.placement import Layout

_INDEX = {"x": 0, "y": 1, "z": 2}


Face = FlatFace | SideFace | BallFace | ConeFace


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
    return isinstance(end_of(item), ThroughAll)


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


def _profile_shape(item: Item) -> Shape | None:
    """An extrusion's outline, or a revolution's half outline, as the solver reasons with it."""
    profile = item.get("profile")
    return Shape.of_profile(profile) if isinstance(profile, Profile) else None


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


def _oriented(
    axes: tuple[str, str], along: str | None, long: float, short: float
) -> tuple[float, float]:
    """A long and a short half size in a face's two axes: the long along ``along``."""
    return (long, short) if along == axes[0] else (short, long)


#: How a profiled body's flat ends are made: given its outline, a point at (u, v, height), the faces to fill, its
#: sources, the way down, and its outline's box; the two corners of its bounds.
Ends = Callable[
    [
        Shape,
        Callable[[float, float, float], Vec],
        dict[str, "Face"],
        tuple[tuple[str, str], ...],
        str,
        tuple[float, float],
        tuple[float, float],
    ],
    tuple[Vec, Vec],
]


@dataclass(frozen=True)
class Hollowing:
    """A shell's hollowing of one body, as the solver reads the shell: what each hollowable kind's own hollow is made from."""

    shell: Item
    shell_at: str
    thickness: float
    floor: float
    thickness_value: object
    floor_value: object
    open_faces: frozenset[str]
    walls: tuple[tuple[str, str], ...]

    def wall(self, name: str, opposite: str) -> float:
        """A wall's thickness: none where the face is open; the floor's opposite an opening."""
        if name in self.open_faces:
            return 0.0
        return self.floor if opposite in self.open_faces else self.thickness


def profiled(item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
             ends: Ends) -> tuple[Vec, Vec]:  # fmt: skip
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
    frame = Frame.of_names(base, axes[0], axes[1], up)
    down = _opposite(up)
    sources = ((item.id, "profile"),)

    def point(u: float, v: float, h: float) -> Vec:
        return frame.at(u, v, h)

    (l1, l2), (h1, h2) = shape.box()
    faces: dict[str, Face] = {}
    corners = ends(shape, point, faces, sources, down, (l1, l2), (h1, h2))
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


def _turn(degrees: float) -> tuple[float, float]:
    """The cosine and sine of an angle in degrees, exact where they are 0 or 1 (:func:`forge_spec.frames.cos_sin`)."""
    return cos_sin(degrees)
