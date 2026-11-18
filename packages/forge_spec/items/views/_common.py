"""What the confirmation views of several kinds share (the ``views`` role's leaf: it imports neither the kinds' modules nor ``render_views.py``).

Moved from ``render_views.py`` at stage 4b.0b's step 3, unchanged: how a
value is worded on a drawing, the frame-axis helpers, a round solid's
outline; and the parts of a body's drawing several kinds share.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs

from forge_spec.draft import Choice, Fit, Item, Profile, Through, UpTo, outline_points
from forge_spec.geometry import EPS, Vec
from forge_spec.items.words._common import _n as number
from forge_spec.placement import Instance, Layout, mm
from forge_spec.schema import FACE_AXES
from forge_spec.values import Count, Provenance, Source, Value

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


_AXES = "xyz"


#: Where a size along each frame axis is dimensioned: which view, and across ("u") or up ("v") it.
_HOME: Mapping[int, tuple[int, str]] = {0: (0, "u"), 1: (0, "v"), 2: (1, "v")}


# ----------------------------------------------------------------------
# Words
# ----------------------------------------------------------------------
def _tag(provenance: Provenance | None) -> str:
    if provenance is None:
        return ""
    return {Source.ASSUMED: " (assumed)", Source.DERIVED: " (derived)"}.get(
        provenance.source, ""
    )


def _value(value: object) -> str:
    """A spec value as the drawings give it: its number, its unit unless mm, its tolerance, an assumption."""
    if isinstance(value, Count):
        return f"{value.n}{_tag(value.provenance)}"
    if not isinstance(value, Value):
        return "?"
    text = number(value.nominal) + {"mm": "", "deg": "°"}.get(
        value.unit, f" {value.unit}"
    )
    if value.tolerance is not None:
        text += f" +{number(value.tolerance.plus)}/-{number(value.tolerance.minus)}"
    return text + _tag(value.provenance)


def _mm(x: float) -> str:
    """A size the views worked out, in millimetres, without floating-point noise."""
    return number(round(x, 6) + 0.0)


def _through(value: object) -> str:
    if isinstance(value, Through):
        return ("through all" if value.everything else "through") + _tag(value.provenance)
    if isinstance(value, UpTo):  # item 2b's first step
        back = "" if value.offset is None else f" less {_value(value.offset)}"
        return f"down to {value.face.item} {value.face.face}{back}" + _tag(value.provenance)
    return f"{_value(value)} deep"


def _fit(value: Fit, size: float | None) -> str:
    named = {"clearance": f"clearance for {value.for_}", "tapped": f"tapped {value.for_}",
             "bearing_seat": f"seat for a {value.for_} bearing"}.get(value.fit, f"{value.fit} {value.for_}")  # fmt: skip
    if value.fit == "clearance" and value.grade not in ("", "normal"):
        named = f"{value.grade} {named}"
    return (
        f"Ø{_mm(size) if size is not None else '?'} ({named}){_tag(value.provenance)}"
    )


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _length(item: Item, name: str) -> float:
    value = item.get(name)
    return mm(value) if isinstance(value, Value) else 0.0


def _axis_of(direction: Vec) -> int | None:
    """The frame axis a direction runs along, or None for one at an angle."""
    for k in range(3):
        if abs(abs(direction[k]) - 1.0) <= EPS:
            return k
    return None


def _named(direction: Vec, k: int) -> str:
    return ("+" if direction[k] > 0 else "-") + _AXES[k]


def _mid(lo: Vec, hi: Vec) -> Vec:
    return (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2


def _cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit(a: Vec) -> Vec:
    n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    return a[0] / n, a[1] / n, a[2] / n


def _disc(
    canvas: _Canvas, centre: Vec, normal: Vec, r: float
) -> list[tuple[float, float]]:
    """A circle of radius ``r`` about ``centre``, square to ``normal``, as the view sees it."""
    k = min(range(3), key=lambda i: abs(normal[i]))
    helper = (1.0 if k == 0 else 0.0, 1.0 if k == 1 else 0.0, 1.0 if k == 2 else 0.0)
    e1 = _unit(_cross(normal, helper))
    e2 = _cross(normal, e1)
    points = []
    for step in range(48):
        t = 2 * math.pi * step / 48
        c, s = fs.cos(t), fs.sin(t)
        points.append(canvas.at((centre[0] + r * (c * e1[0] + s * e2[0]), centre[1] + r * (c * e1[1] + s * e2[1]),
                                 centre[2] + r * (c * e1[2] + s * e2[2]))))  # fmt: skip
    return points


def _outline_points(profile: Profile, step_degrees: float = 3.0) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:  # fmt: skip
    """An outline followed closely (each arc every few degrees), and its corners and its arcs' points furthest along each axis: where a swept outline shows an edge from the side."""
    chain = [(a, b) for a, b, _ in outline_points(profile, step_degrees)]
    corners = [profile.start, *(seg.to for seg in profile.segments)]
    here = profile.start
    for seg in profile.segments:
        if seg.centre is not None:
            r = fs.dist(here, seg.centre)
            for p in ((seg.centre[0] + r, seg.centre[1]), (seg.centre[0] - r, seg.centre[1]),
                      (seg.centre[0], seg.centre[1] + r), (seg.centre[0], seg.centre[1] - r)):  # fmt: skip
                if any(fs.dist(p, q) <= r * math.radians(step_degrees) for q in chain):
                    corners.append(p)
        here = seg.to
    return chain, corners


def _round(canvas: _Canvas, start: Vec, direction: Vec, length: float, r0: float, r1: float, *,
           start_style: str | None, side_style: str | None, end_style: str | None) -> None:  # fmt: skip
    """A round solid or bore: a disc of radius ``r0`` at ``start``, ``r1`` at ``length`` along ``direction``.

    Looking down its axis the ends are circles about one centre; from the side,
    its outline is two lines and its ends are ellipses (lines, seen edge on).
    """
    end = (
        start[0] + direction[0] * length,
        start[1] + direction[1] * length,
        start[2] + direction[2] * length,
    )
    s, e = canvas.at(start), canvas.at(end)
    across = fs.hypot(direction[canvas.u], direction[canvas.v])
    if across <= EPS:
        for r, style in ((r0, start_style), (r1, end_style)):
            if style is not None and r > EPS:
                canvas.circle(s, r, style)
        return
    du, dv = direction[canvas.u] / across, direction[canvas.v] / across
    pu, pv = -dv, du
    if side_style is not None:
        for sign in (1.0, -1.0):
            canvas.path(((s[0] + sign * r0 * pu, s[1] + sign * r0 * pv),
                         (e[0] + sign * r1 * pu, e[1] + sign * r1 * pv)), side_style, closed=False)  # fmt: skip
    for centre, r, style in ((start, r0, start_style), (end, r1, end_style)):
        if style is None or r <= EPS:
            continue
        c = canvas.at(centre)
        if abs(direction[canvas.w]) <= EPS:
            canvas.path(
                ((c[0] - r * pu, c[1] - r * pv), (c[0] + r * pu, c[1] + r * pv)),
                style,
                closed=False,
            )
        else:
            canvas.path(_disc(canvas, centre, direction, r), style, closed=True)


def _style(seen: bool) -> str:
    return "visible" if seen else "hidden"


def _neg(v: Vec) -> Vec:
    return (-v[0], -v[1], -v[2])


# ----------------------------------------------------------------------
# What several kinds' drawings share
# ----------------------------------------------------------------------
def box_body(d: _Drawing, first: Instance, title: str) -> None:
    """A box-like item's note and its three sizes, each where the solver builds it from."""
    item, home = d.item, d.home
    assert first.lo is not None and first.hi is not None and home is not None
    lo, hi = first.lo, first.hi
    d.say(title)
    turned = d.turned(first) is not None
    up = _axis_of(first.normal)
    for k, name in d._box_fields(first).items():
        if turned and k != up:  # turned in its face, its sizes across run along no frame axis: said, not drawn
            d.say(f"{name} {_value(item.get(name))}", name)
            continue
        canvas, along = d.canvases[_HOME[k][0]], _HOME[k][1]
        across = canvas.v if along == "u" else canvas.u
        d.line(
            canvas,
            along,
            lo[k],
            hi[k],
            (lo[across], lo[across]),
            _value(item.get(name)),
            name,
        )


def box_anchor(d: _Drawing, first: Instance) -> None:
    """The note's place: by the box's far corner on its home view."""
    home = d.home
    assert first.hi is not None and home is not None
    hi = first.hi
    d.anchor = (hi[home.u], hi[home.v])


def round_spans(
    d: _Drawing, first: Instance, up: int | None, *, whole: bool = False
) -> float:
    """A round item's sizes across, which its note's diameter gives (a whole ball's along its axis too); its radius on its home view."""
    home = d.home
    assert first.lo is not None and first.hi is not None and home is not None
    lo, hi = first.lo, first.hi
    r = (hi[home.u] - lo[home.u]) / 2
    spanned = [k for k in range(3) if k != up or whole]
    for k in spanned:  # the note's diameter gives the size across
        d.canvases[_HOME[k][0]].spans.append((_HOME[k][1], lo[k], hi[k]))
    return r


def rod_body(
    d: _Drawing, first: Instance, up: int | None, name: str, words: tuple[str, ...]
) -> None:
    """A rod's length (or height) along its axis, and its note (``words``: what it says, then the fields it shows)."""
    item, home = d.item, d.home
    assert first.lo is not None and first.hi is not None and home is not None
    lo, hi = first.lo, first.hi
    r = round_spans(d, first, up)
    assert up is not None, "the solver stands every body along a frame axis"
    canvas, along = d.canvases[_HOME[up][0]], _HOME[up][1]
    side = canvas.v if along == "u" else canvas.u
    d.line(
        canvas,
        along,
        lo[up],
        hi[up],
        (lo[side], lo[side]),
        _value(item.get(name)),
        name,
    )
    d.say(*words)
    centre = home.at(first.origin)  # a round item's home looks down its axis
    d.anchor = (centre[0] + r * math.sqrt(0.5), centre[1] + r * math.sqrt(0.5))


def round_outline(
    canvas: _Canvas, copy: Instance, style: str, up: int, r0: float, r1: float
) -> bool:
    """A round body's outline on one view, its radius ``r0`` at its base and ``r1`` at its far end; whether its axis is the view's."""
    lo, hi = copy.lo, copy.hi
    assert lo is not None and hi is not None
    length = hi[up] - lo[up]
    axial = canvas.w == up
    if axial:
        start_near = canvas.nearer(
            copy.origin[up], copy.origin[up] + copy.normal[up] * length
        )
        near_r, far_r = (r0, r1) if start_near else (r1, r0)
        far = (
            style
            if far_r > near_r + EPS
            else ("hidden" if far_r < near_r - EPS else None)
        )
        starts, ends = (style, far) if start_near else (far, style)
        _round(canvas, copy.origin, copy.normal, length, r0, r1,
               start_style=starts, side_style=None, end_style=ends)  # fmt: skip
    else:
        _round(canvas, copy.origin, copy.normal, length, r0, r1,
               start_style=style, side_style=style, end_style=style)  # fmt: skip
    return axial


def profile_frame(item: Item, copy: Instance, up: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]], Vec, Vec, int, int] | None:  # fmt: skip
    """An outlined body's outline points and corners, its base point and axis, and the frame axes its outline is drawn in; None without one."""
    profile = item.get("profile")
    if not isinstance(profile, Profile):
        return None
    chain, corners = _outline_points(profile)
    o, n = copy.origin, copy.normal
    a1, a2 = copy.face_axes or FACE_AXES[_named(n, up)]
    k1, k2 = _AXES.index(a1), _AXES.index(a2)
    return chain, corners, o, n, k1, k2


def outlined_body(d: _Drawing, first: Instance, up: int | None, turned: str) -> None:
    """An outlined body's note: its outline in words (``turned``: how it is made from it)."""
    from forge_spec.items.words._common import _outline as item_outline

    item, home = d.item, d.home
    assert first.lo is not None and first.hi is not None and home is not None
    hi = first.hi
    profile = item.get("profile")
    outline = item_outline(profile) if isinstance(profile, Profile) else "its outline"
    d.say(f"{item.kind}: {outline}{turned}", "profile")
    d.anchor = (hi[home.u], hi[home.v])


def box_inside(item: Item, copy: Instance, layout: Layout) -> list[tuple[Vec, Vec]]:
    """A box's inside: the whole of it, or a hollowed box's walls but where it is open."""
    lo, hi = copy.lo, copy.hi
    assert lo is not None and hi is not None
    cavity = layout.cavities.get((item.id, copy.index))
    if cavity is None:
        return [(lo, hi)]
    shell = layout.shells.get(item.id)
    opened = shell.get("open") if shell is not None else None
    open_faces = set(getattr(opened, "faces", ()))
    walls = []
    for k in range(3):
        for side, inner in (("-", cavity[0][k]), ("+", cavity[1][k])):
            if side + _AXES[k] in open_faces:
                continue
            wlo, whi = list(lo), list(hi)
            if side == "-":
                whi[k] = inner
            else:
                wlo[k] = inner
            if whi[k] - wlo[k] > EPS:
                walls.append(((wlo[0], wlo[1], wlo[2]), (whi[0], whi[1], whi[2])))
    return walls


def round_inside(copy: Instance, up: int, across: float) -> list[tuple[Vec, Vec]]:
    """A round thing's inside: the square in its circle, ``across`` its radius, all its length."""
    lo, hi = copy.lo, copy.hi
    assert lo is not None and hi is not None
    r = across
    if r <= EPS:
        return []
    half = r / math.sqrt(2)
    centre = _mid(lo, hi)
    blo = [centre[k] - half if k != up else lo[k] for k in range(3)]
    bhi = [centre[k] + half if k != up else hi[k] for k in range(3)]
    return [((blo[0], blo[1], blo[2]), (bhi[0], bhi[1], bhi[2]))]
