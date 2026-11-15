"""Dimensioned views of a checked draft: top, front and side (plan, section 4.2, item 4).

The person checks sizes and places by eye before confirming. The views draw
the solved layout (:mod:`forge_spec.placement`): the numbers the fixed
wording gives (:mod:`forge_spec.render`), seen another way. Every value of
every item is shown, on a drawing or under it:

- a body's or a standing feature's sizes as dimension lines, each on the view
  that shows its frame axis: X and Y on the top view, Z on the front;
- a round thing's diameters, and a cut's size and depth, in a note with a
  leader on the view that looks down its axis, with how many there are;
- where each item stands or cuts in, measured as its place says: from the
  edge, the centre or the end it names, to the centre or the near edge; and
  the steps of its pattern;
- roundings, chamfers, shells and threads, which no outline shows well, in
  the fixed wording, under the views.

A value no line can show (an offset of nothing) is written in the item's
note instead, so nothing the spec holds goes unseen: :meth:`Views.shown`
lists, per item, the fields that are. Sizes are in millimetres unless a unit
is given, and a value the writer assumed says so. The overall size is
dimensioned too, labelled as such where no single item spans it. An item the
layout couldn't place is listed as not drawn, never drawn as a guess.

Visible edges are solid, hidden ones dashed, centre lines dash-dot.
Something is hidden when it faces away from the viewer or lies wholly behind
one solid that nothing is cut right through where it would be seen; each
circle of a hole (its bore, its counterbore, its countersink, the way out of
it) is judged where it is and as far as it reaches. The reckoning errs one
way only: what may be seen is drawn as seen. The compiled part's own views
and sections, in a later stage, replace it with the real shape. Nothing here
comes from a model.

The drawings are SVG, all three at one scale, drawn in ``currentColor`` so a
page shows them in its own colours, light or dark. Every text in them is
escaped: an item id or engraved letters can't add markup.
"""

from __future__ import annotations

import html
import itertools
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .checks import SpecReport
from .draft import (
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    Fit,
    Item,
    On,
    Pattern,
    Place,
    Profile,
    Text,
    Through,
    outline_points,
)
from .geometry import (
    EPS,
    Face,
    FlatFace,
    Part,
    SideFace,
    Vec,
    bbox,
    disc,
    least_material_under,
    most_material_under,
    reach,
    side_material,
    side_most_material,
)
from .placement import Instance, Layout, _along, _outline, degrees, mm
from .render import _line as item_line
from .render import _n as number
from .render import _outline as item_outline
from .schema import FACE_AXES, KINDS, Category
from .values import Count, Provenance, Source, Value

__all__ = ["Dimension", "View", "Views", "render_views"]

_AXES = "xyz"
_ROUND_KINDS = ("cylinder", "tube", "cone", "boss")
#: The kinds drawn from their outline.
_OUTLINED = ("extrusion", "revolution")
_BOX_KINDS = ("block", "post", "rib", "tab", "region")
#: The kinds of value the views show; a choice is drawn (the way a slot runs, a round end).
_SHOWN = (Value, Count, Through, Fit, Text, Counterbore, Countersink)


@dataclass(frozen=True)
class _Frame:
    """One view: the frame axes across (u) and up (v) the drawing, and the axis looked along (w)."""

    name: str
    caption: str
    u: int
    v: int
    w: int
    #: +1: the viewer is on the plus side of ``w``, looking towards minus.
    facing: int


_FRAMES = (
    _Frame("top", "Top, looking down (X across, Y up)", 0, 1, 2, +1),
    _Frame("front", "Front, looking along +Y (X across, Z up)", 0, 2, 1, -1),
    _Frame("side", "Side, looking along -X (Y across, Z up)", 1, 2, 0, +1),
)

#: Where a size along each frame axis is dimensioned: which view, and across ("u") or up ("v") it.
_HOME: Mapping[int, tuple[int, str]] = {0: (0, "u"), 1: (0, "v"), 2: (1, "v")}

#: The part's largest size spans this many pixels; every view is drawn at that one scale.
_SPAN_PX = 320.0
_FONT_PX = 12.0
_ARROW_PX = 7.0

#: Each kind of line: its width and dashes in pixels, and its opacity.
_STYLES: Mapping[str, tuple[float, tuple[float, ...], float]] = {
    "visible": (1.6, (), 1.0),
    "hidden": (1.0, (5.0, 3.0), 0.7),
    "centre": (0.8, (12.0, 3.0, 2.0, 3.0), 0.6),
    "envelope": (1.0, (8.0, 3.0, 2.0, 3.0), 0.9),
}


# ----------------------------------------------------------------------
# What the views show
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Dimension:
    """One thing the views show about an item, and the fields of the item it shows.

    ``fields`` are the item's field names ("length") or parts of its place
    ("place.x", "place.pattern.pitch"); the part's overall size is
    "overall.x" of item "". ``form`` is "line" (a dimension line), "note"
    (written on the drawing, with a leader to the item) or "words" (under
    the views, in the fixed wording). A line's ``measured`` is the distance
    it spans on the drawing, in millimetres.
    """

    item: str
    fields: tuple[str, ...]
    text: str
    form: str
    measured: float | None = None


@dataclass(frozen=True)
class View:
    """One drawing, and what it dimensions."""

    name: str
    caption: str
    svg: str
    dimensions: tuple[Dimension, ...]


@dataclass(frozen=True)
class Views:
    """Top, front and side; what is said in words under them; and what no view could draw."""

    views: tuple[View, ...]
    #: Roundings, chamfers, shells and threads, in the fixed wording.
    words: tuple[Dimension, ...]
    #: Items no view shows: the layout couldn't place them.
    not_drawn: tuple[str, ...]
    #: The part's overall size along X, Y and Z; None with nothing placed.
    overall: Vec | None

    def dimensions(self) -> tuple[Dimension, ...]:
        return tuple(d for view in self.views for d in view.dimensions) + self.words

    def shown(self, item: str) -> frozenset[str]:
        """The fields of an item the views show, on a drawing or in words."""
        return frozenset(
            f for d in self.dimensions() if d.item == item for f in d.fields
        )


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
        return "through" + _tag(value.provenance)
    return f"{_value(value)} deep"


def _fit(value: Fit, size: float | None) -> str:
    named = {"clearance": f"clearance for {value.for_}", "tapped": f"tapped {value.for_}",
             "bearing_seat": f"seat for a {value.for_} bearing"}.get(value.fit, f"{value.fit} {value.for_}")  # fmt: skip
    if value.fit == "clearance" and value.grade not in ("", "normal"):
        named = f"{value.grade} {named}"
    return (
        f"Ø{_mm(size) if size is not None else '?'} ({named}){_tag(value.provenance)}"
    )


def _generic(value: object) -> str:
    if isinstance(value, (Value, Count)):
        return _value(value)
    if isinstance(value, Through):
        return _through(value)
    if isinstance(value, Fit):
        return _fit(value, None)
    if isinstance(value, Text):
        return f"{value.text!r}{_tag(value.provenance)}"
    if isinstance(value, Counterbore):
        return f"Ø{_value(value.diameter)}, {_value(value.depth)} deep"
    if isinstance(value, Countersink):
        return f"Ø{_value(value.diameter)} at {_value(value.angle)}"
    return str(value)  # pragma: no cover - every shown kind is worded above


def _position_words(axis: str, position: AxisPosition, edge: str = "edge") -> str:
    """A place along one axis in words; ``edge`` is what its sides are called ("end" round a rod)."""
    if position.mode == "centred" or position.distance is None:
        return f"centred along {axis.upper()}{_tag(position.provenance)}"
    if position.mode == "offset":
        return (
            f"offset {_value(position.distance)} along {axis.upper()} from the centre"
        )
    to = "its centre" if position.to == "centre" else "its near edge"
    return f"{_value(position.distance)} from the {position.side} {edge} to {to}"


def _to_show(item: Item) -> dict[str, str]:
    """Every value of an item the views must show, by where it is in the item, each in words."""
    out: dict[str, str] = {}
    for name, value in item.fields.items():
        if isinstance(value, Place):
            for axis, position in sorted(value.axes.items()):
                out[f"place.{axis}"] = _position_words(axis, position)
            if value.angle is not None:
                out["place.angle"] = f"at {_value(value.angle)}"
            if value.pattern is not None:
                given: dict[str, Value | Count] = {
                    **value.pattern.values,
                    **value.pattern.counts,
                }
                for key, held in sorted(given.items()):
                    out[f"place.pattern.{key}"] = (
                        f"{_value(held)} at each place"
                        if key == "each"
                        else f"{key.replace('_', ' ')} {_value(held)}"
                    )
            if value.concentric:
                out["place.concentric"] = f"concentric with {value.concentric}"
        elif isinstance(value, _SHOWN):
            out[name] = f"{name.replace('_', ' ')} {_generic(value)}"
    return out


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


# ----------------------------------------------------------------------
# One drawing
# ----------------------------------------------------------------------
@dataclass
class _Line:
    """A dimension line still to be laid out: along "u" or "v", from ``a`` to ``b``."""

    along: str
    a: float
    b: float
    #: Where each end's extension line starts, across the line.
    feet: tuple[float, float]
    text: str


@dataclass
class _Note:
    at: tuple[float, float]
    text: str


@dataclass
class _Extent:
    lo: list[float]
    hi: list[float]

    def take(self, u: float, v: float) -> None:
        self.lo[0], self.lo[1] = min(self.lo[0], u), min(self.lo[1], v)
        self.hi[0], self.hi[1] = max(self.hi[0], u), max(self.hi[1], v)


@dataclass
class _Canvas:
    """One view as it is drawn, in its own (u, v) millimetres, v up."""

    frame: _Frame
    #: One pixel, in millimetres.
    px: float
    decimals: int
    layers: dict[str, list[str]] = field(
        default_factory=lambda: {style: [] for style in _STYLES}
    )
    seen: set[str] = field(default_factory=set)
    letters: list[str] = field(default_factory=list)
    lines: list[_Line] = field(default_factory=list)
    #: Spans a note gives in words, along "u" or "v": a round thing's diameter across it.
    spans: list[tuple[str, float, float]] = field(default_factory=list)
    notes: list[_Note] = field(default_factory=list)
    shown: list[Dimension] = field(default_factory=list)
    drawn: _Extent = field(
        default_factory=lambda: _Extent([math.inf, math.inf], [-math.inf, -math.inf])
    )

    @property
    def u(self) -> int:
        return self.frame.u

    @property
    def v(self) -> int:
        return self.frame.v

    @property
    def w(self) -> int:
        return self.frame.w

    def at(self, point: Vec) -> tuple[float, float]:
        return point[self.u], point[self.v]

    def faces_viewer(self, normal: Vec) -> bool:
        return normal[self.w] * self.frame.facing > EPS

    def nearer(self, a: float, b: float) -> bool:
        """Whether depth ``a`` along the line of sight is at least as near the viewer as ``b``."""
        return a * self.frame.facing >= b * self.frame.facing - EPS

    # -- outlines ---------------------------------------------------------
    def _f(self, x: float) -> str:
        text = f"{x:.{self.decimals}f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text

    def _point(self, u: float, v: float) -> str:
        return f"{self._f(u)},{self._f(-v)}"

    def _add(
        self, style: str, element: str, extent: Iterable[tuple[float, float]]
    ) -> None:
        if style + element in self.seen:
            return  # a copy drawn over another, as a grid seen edge on
        self.seen.add(style + element)
        self.layers[style].append(element)
        for u, v in extent:
            self.drawn.take(u, v)

    def rect(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        style: str,
        radius: float = 0.0,
    ) -> None:
        u0, u1 = sorted((a[0], b[0]))
        v0, v1 = sorted((a[1], b[1]))
        rounded = f' rx="{self._f(radius)}"' if radius > EPS else ""
        self._add(style, f'<rect x="{self._f(u0)}" y="{self._f(-v1)}" width="{self._f(u1 - u0)}" '
                         f'height="{self._f(v1 - v0)}"{rounded}/>', ((u0, v0), (u1, v1)))  # fmt: skip

    def circle(self, centre: tuple[float, float], r: float, style: str) -> None:
        cu, cv = centre
        self._add(style, f'<circle cx="{self._f(cu)}" cy="{self._f(-cv)}" r="{self._f(r)}"/>',
                  ((cu - r, cv - r), (cu + r, cv + r)))  # fmt: skip

    def path(
        self, points: Sequence[tuple[float, float]], style: str, *, closed: bool
    ) -> None:
        tag = "polygon" if closed else "polyline"
        written = [self._point(u, v) for u, v in points]
        # A point the one before it lands on, as written, is no point of its own.
        kept = [p for k, p in enumerate(written) if k == 0 or p != written[k - 1]]
        if closed and len(kept) > 1 and kept[-1] == kept[0]:
            kept.pop()
        self._add(style, f'<{tag} points="{" ".join(kept)}"/>', points)

    def mark(self, centre: tuple[float, float]) -> None:
        """A centre mark: where a pattern is measured to, with no copy there."""
        s = 6 * self.px
        cu, cv = centre
        self.path(((cu - s, cv), (cu + s, cv)), "centre", closed=False)
        self.path(((cu, cv - s), (cu, cv + s)), "centre", closed=False)

    def write(
        self, centre: tuple[float, float], text: str, height: float, width: float
    ) -> None:
        """Engraved or embossed letters, a capital ``height`` tall, filling ``width`` about ``centre``.

        The width is the solver's estimate of the letters' outline, so they are
        drawn exactly where the checks took them to be.
        """
        cu, cv = centre
        size = height / 0.72  # a capital is about 0.72 of the type size
        self.letters.append(f'<text x="{self._f(cu)}" y="{self._f(-cv)}" font-size="{self._f(size)}" '
                            f'text-anchor="middle" dominant-baseline="central" textLength="{self._f(width)}" '
                            f'lengthAdjust="spacingAndGlyphs">{html.escape(text)}</text>')  # fmt: skip

    # -- what it shows ------------------------------------------------------
    def dimension(self, item: str, fields: tuple[str, ...], along: str, a: float, b: float,
                  feet: tuple[float, float], text: str) -> bool:  # fmt: skip
        """A dimension line from ``a`` to ``b``; False where they meet, so no line can show it."""
        if abs(b - a) <= EPS:
            return False
        low, high = min(a, b), max(a, b)
        if not any(ln.along == along and ln.text == text and abs(min(ln.a, ln.b) - low) <= EPS
                   and abs(max(ln.a, ln.b) - high) <= EPS for ln in self.lines):  # fmt: skip
            self.lines.append(
                _Line(along, a, b, feet, text)
            )  # drawn once, however many items it shows
        self.shown.append(Dimension(item, fields, text, "line", abs(b - a)))
        return True

    def spans_already(self, along: str, a: float, b: float) -> bool:
        """Whether a line or a note already gives the size from ``a`` to ``b``."""
        given = [
            (ln.along, min(ln.a, ln.b), max(ln.a, ln.b)) for ln in self.lines
        ] + self.spans
        return any(
            on == along and abs(low - a) <= EPS and abs(high - b) <= EPS
            for on, low, high in given
        )

    def note(
        self, item: str, fields: tuple[str, ...], at: tuple[float, float], text: str
    ) -> None:
        self.notes.append(_Note(at, text))
        self.shown.append(Dimension(item, fields, text, "note"))

    # -- the drawing --------------------------------------------------------
    def svg(self) -> str:
        if not any(self.layers.values()):
            return ""
        px, font = self.px, _FONT_PX * self.px
        lines: list[str] = []  # dimension, extension and leader lines
        heads: list[str] = []  # arrowheads and leader dots
        texts: list[str] = []
        geometry = _Extent(list(self.drawn.lo), list(self.drawn.hi))
        extent = _Extent(list(self.drawn.lo), list(self.drawn.hi))
        for along in ("u", "v"):
            self._lay_out([ln for ln in self.lines if ln.along == along], along, geometry, extent,
                          (lines, heads, texts))  # fmt: skip
        self._lay_out_notes(extent, (lines, heads, texts))
        self._triad(extent, (lines, heads, texts))
        pad = 8 * px
        x0, y0 = extent.lo[0] - pad, -(extent.hi[1] + pad)
        width, height = (
            extent.hi[0] - extent.lo[0] + 2 * pad,
            extent.hi[1] - extent.lo[1] + 2 * pad,
        )
        groups = []
        for style, elements in self.layers.items():
            if not elements:
                continue
            stroke, dashes, opacity = _STYLES[style]
            dashed = (
                f' stroke-dasharray="{" ".join(self._f(d * px) for d in dashes)}"'
                if dashes
                else ""
            )
            faint = f' opacity="{opacity:g}"' if opacity < 1 else ""
            groups.append(f'<g class="{style}" stroke-width="{self._f(stroke * px)}"{dashed}{faint}>'
                          + "".join(elements) + "</g>")  # fmt: skip
        letters = ('<g class="letters" fill="currentColor" opacity="0.75" font-family="system-ui, sans-serif">'
                   + "".join(self.letters) + "</g>") if self.letters else ""  # fmt: skip
        caption = html.escape(self.frame.caption)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" class="view" viewBox="{self._f(x0)} {self._f(y0)} '
            f'{self._f(width)} {self._f(height)}" width="{width / px:.1f}" height="{height / px:.1f}" '
            f'role="img" aria-label="{caption}"><title>{caption}</title>'
            '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">'
            + "".join(groups) + "</g>" + letters
            + f'<g class="dimensions" fill="none" stroke="currentColor" stroke-width="{self._f(0.8 * px)}">'
            + "".join(lines) + "</g>"
            + '<g class="heads" fill="currentColor" stroke="none">' + "".join(heads) + "</g>"
            # A halo in the page's own colour keeps every label legible where a line crosses it.
            + f'<g class="labels" fill="currentColor" stroke-width="{self._f(3 * px)}" stroke-linejoin="round" '
            + 'style="paint-order: stroke; stroke: var(--halo, #ffffff)" font-family="system-ui, sans-serif" '
            + f'font-size="{self._f(font)}">' + "".join(texts) + "</g></svg>"
        )  # fmt: skip

    def _segment(self, a: tuple[float, float], b: tuple[float, float]) -> str:
        return (f'<line x1="{self._f(a[0])}" y1="{self._f(-a[1])}" x2="{self._f(b[0])}" '
                f'y2="{self._f(-b[1])}"/>')  # fmt: skip

    def _arrow(self, tip: tuple[float, float], towards: tuple[float, float]) -> str:
        """An arrowhead with its tip at ``tip``, pointing along the unit vector ``towards``."""
        length, half = _ARROW_PX * self.px, 2.2 * self.px
        du, dv = towards
        base = (tip[0] - du * length, tip[1] - dv * length)
        left = (base[0] - dv * half, base[1] + du * half)
        right = (base[0] + dv * half, base[1] - du * half)
        return f'<polygon points="{self._point(*tip)} {self._point(*left)} {self._point(*right)}"/>'

    def _lay_out(self, todo: Sequence[_Line], along: str, geometry: _Extent, extent: _Extent,
                 out: tuple[list[str], list[str], list[str]]) -> None:  # fmt: skip
        """Dimension lines below the drawing (across it) or left of it (up it), shortest nearest.

        Each goes in the first row where it overlaps no other: its span, and its
        text where the text sits outside a span too short to hold it.
        """
        lines, heads, texts = out
        px, font = self.px, _FONT_PX * self.px
        arrow = _ARROW_PX * px
        swap = along == "v"

        def at(x: float, y: float) -> tuple[float, float]:
            return (y, x) if swap else (x, y)

        rows: list[list[tuple[float, float]]] = []
        for line in sorted(
            todo, key=lambda ln: (abs(ln.b - ln.a), min(ln.a, ln.b), ln.text)
        ):
            a, b = sorted((line.a, line.b))
            width = _text_width(line.text, font)
            roomy = b - a >= 2 * arrow + 2 * px  # the arrows fit inside
            inside = width + 2 * arrow + 4 * px <= b - a  # and the text too
            span = (
                a - (0.0 if roomy else arrow),
                b + (0.0 if inside else arrow + 3 * px + width),
            )
            row = next((n for n, taken in enumerate(rows)
                        if all(span[1] + font * 0.6 < s or span[0] - font * 0.6 > e for s, e in taken)),
                       len(rows))  # fmt: skip
            if row == len(rows):
                rows.append([])
            rows[row].append(span)
            level = (geometry.lo[0] if swap else geometry.lo[1]) - font * 2.2 * (
                row + 1
            )
            for end, foot in ((line.a, line.feet[0]), (line.b, line.feet[1])):
                lines.append(
                    self._segment(at(end, foot - 2 * px), at(end, level - 3 * px))
                )
            lines.append(self._segment(at(a, level), at(b, level)))
            point = (
                1.0 if roomy else -1.0
            )  # arrows inside the span, or outside pointing in
            heads.append(self._arrow(at(a, level), at(-point, 0.0)))
            heads.append(self._arrow(at(b, level), at(point, 0.0)))
            if not roomy:
                lines.append(self._segment(at(a - arrow, level), at(a, level)))
                lines.append(self._segment(at(b, level), at(b + arrow, level)))
            text = html.escape(line.text)
            place = (a + b) / 2 if inside else b + arrow + 3 * px
            anchor = "middle" if inside else "start"
            if not swap:
                texts.append(f'<text x="{self._f(place)}" y="{self._f(-(level + 0.3 * font))}" '
                             f'text-anchor="{anchor}">{text}</text>')  # fmt: skip
                extent.take(span[0], level - font * 0.4)
                extent.take(span[1], level + font * 1.2)
            else:
                x = level - 0.3 * font
                texts.append(f'<text x="{self._f(x)}" y="{self._f(-place)}" text-anchor="{anchor}" '
                             f'transform="rotate(-90 {self._f(x)} {self._f(-place)})">{text}</text>')  # fmt: skip
                extent.take(level - font * 1.2, span[0])
                extent.take(level + font * 0.4, span[1])

    def _lay_out_notes(
        self, extent: _Extent, out: tuple[list[str], list[str], list[str]]
    ) -> None:
        """Notes in a column right of everything, each level with its item where there is room."""
        if not self.notes:
            return
        lines, heads, texts = out
        px, font = self.px, _FONT_PX * self.px
        column = extent.hi[0] + font * 1.5
        below = math.inf
        for note in sorted(self.notes, key=lambda n: (-n.at[1], n.at[0], n.text)):
            y = min(note.at[1] - 0.35 * font, below - 1.45 * font)
            below = y
            lines.append(self._segment(note.at, (column - 4 * px, y + 0.35 * font)))
            heads.append(
                f'<circle cx="{self._f(note.at[0])}" cy="{self._f(-note.at[1])}" r="{self._f(1.6 * px)}"/>'
            )
            texts.append(
                f'<text x="{self._f(column)}" y="{self._f(-y)}">{html.escape(note.text)}</text>'
            )
            extent.take(column + _text_width(note.text, font), y + font)
            extent.take(column, y - 0.3 * font)

    def _triad(
        self, extent: _Extent, out: tuple[list[str], list[str], list[str]]
    ) -> None:
        """The frame's axes, as this view shows them, in its lower left corner."""
        lines, heads, texts = out
        px, font = self.px, _FONT_PX * self.px
        length = 3 * font
        origin = (extent.lo[0], extent.lo[1] - 2 * font - length)
        for (du, dv), axis in (((1.0, 0.0), self.u), ((0.0, 1.0), self.v)):
            tip = (origin[0] + du * length, origin[1] + dv * length)
            lines.append(self._segment(origin, tip))
            heads.append(self._arrow(tip, (du, dv)))
            label = (
                (tip[0] + 3 * px, tip[1] - 0.35 * font)
                if du
                else (tip[0] - 0.3 * font, tip[1] + 4 * px)
            )
            texts.append(
                f'<text x="{self._f(label[0])}" y="{self._f(-label[1])}">{_AXES[axis].upper()}</text>'
            )
            extent.take(label[0] + font, label[1] + font)
        extent.take(origin[0], origin[1])


def _text_width(text: str, font: float) -> float:
    """About how wide a line of sans-serif text is: generous, so texts don't collide."""
    return len(text) * font * 0.6


def _cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit(a: Vec) -> Vec:
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
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
        c, s = math.cos(t), math.sin(t)
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
            r = math.dist(here, seg.centre)
            for p in ((seg.centre[0] + r, seg.centre[1]), (seg.centre[0] - r, seg.centre[1]),
                      (seg.centre[0], seg.centre[1] + r), (seg.centre[0], seg.centre[1] - r)):  # fmt: skip
                if any(
                    math.dist(p, q) <= r * math.radians(step_degrees) for q in chain
                ):
                    corners.append(p)
        here = seg.to
    return chain, corners


def _outlined(canvas: _Canvas, item: Item, copy: Instance, up: int, style: str) -> None:
    """An extrusion or a revolution on one view, from its outline.

    Looking down its axis, an extrusion is its outline; a revolution, a
    circle at each distance from the axis where its outline has a corner (or
    an arc reaches furthest out or in). From the side, an extrusion is its box
    with a line along the axis at each corner; a revolution, its half outline
    and that half mirrored across the axis, in the plane through the axis
    square to the line of sight.
    """
    profile = item.get("profile")
    if not isinstance(profile, Profile):
        return
    chain, corners = _outline_points(profile)
    o, n = copy.origin, copy.normal
    a1, a2 = copy.face_axes or FACE_AXES[_named(n, up)]
    k1, k2 = _AXES.index(a1), _AXES.index(a2)

    def placed(
        p: tuple[float, float], height: float = 0.0, across: int = -1, sign: float = 1.0
    ) -> Vec:
        found = list(o)
        if item.kind == "extrusion":
            found[k1] += p[0]
            found[k2] += p[1]
        else:
            found[across] += sign * p[0]
            found[up] += n[up] * p[1]
        found[up] += n[up] * height
        return (found[0], found[1], found[2])

    if item.kind == "extrusion":
        length = _length(item, "length")
        if canvas.w == up:
            canvas.path([canvas.at(placed(p)) for p in chain], style, closed=True)
            return
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        canvas.rect(canvas.at(lo), canvas.at(hi), style)
        for p in corners:
            canvas.path(
                [canvas.at(placed(p)), canvas.at(placed(p, length))],
                style,
                closed=False,
            )
        return
    if canvas.w == up:
        centre = canvas.at(o)
        for r in sorted({round(p[0], 9) for p in corners if p[0] > EPS}):
            canvas.circle(centre, r, style)
        return
    across = canvas.u if canvas.u != up else canvas.v
    for sign in (1.0, -1.0):
        canvas.path(
            [canvas.at(placed(p, across=across, sign=sign)) for p in chain],
            style,
            closed=True,
        )


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
    across = math.hypot(direction[canvas.u], direction[canvas.v])
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


# ----------------------------------------------------------------------
# What hides what
# ----------------------------------------------------------------------
_Solid = tuple[tuple[str, int], Vec, Vec]
#: Round each axis, where 0 degrees is: the axis the solver turns a round side's angles from.
_ZERO_ON = {"z": "x", "x": "y", "y": "z"}
#: A hole or cut right through, along a frame axis: the axis, and the box of air it leaves.
_Window = tuple[int, Vec, Vec]


def _style(seen: bool) -> str:
    return "visible" if seen else "hidden"


def _neg(v: Vec) -> Vec:
    return (-v[0], -v[1], -v[2])


def _cut_span(item: Item, copy: Instance, layout: Layout) -> tuple[float, bool]:
    """How far one copy of a cut goes into the material (embossed letters: out of it), and whether it comes out.

    A cut through goes as deep as the material is deepest under it, and comes
    out all across its mouth; a blind one comes out once it is as deep as the
    least (docs/definitions/frame.md).
    """
    host = copy.host
    face = (
        layout.faces.get((host[0], host[1]), {}).get(host[2])
        if host is not None
        else None
    )
    least = most = 0.0
    if isinstance(face, FlatFace):
        i1, i2 = (_AXES.index(a) for a in face.axes)
        p1, p2 = copy.origin[i1] - face.centre[i1], copy.origin[i2] - face.centre[i2]
        # A hole's bore is what goes through; a counterbore stops short.
        mouth: tuple[Part, ...] = ((disc(layout.diameters.get(item.id, 0.0) / 2),) if item.kind == "hole"
                                   else _outline(item, layout, face.axes))  # fmt: skip
        least = least_material_under(face, mouth, p1, p2)
        most = most_material_under(face, mouth, p1, p2)
    elif isinstance(face, SideFace):
        r = layout.diameters.get(item.id, 0.0) / 2
        least, most = side_material(face, r), side_most_material(face, r)
    emboss = item.kind == "text" and _choice(item, "mode") == "emboss"
    depth = item.get("depth")
    if emboss:
        return (mm(depth) if isinstance(depth, Value) else 0.0), False
    through = isinstance(depth, Through) or (
        isinstance(depth, Value) and least > EPS and mm(depth) >= least - EPS
    )
    deep = (
        most
        if isinstance(depth, Through)
        else (min(mm(depth), most) if isinstance(depth, Value) else 0.0)
    )
    return deep, item.kind != "text" and least > EPS and through


def _windows(items: Iterable[Item], layout: Layout) -> list[_Window]:
    """Every copy of a cut that goes right through, along a frame axis: what can be seen through."""
    found: list[_Window] = []
    for item in items:
        if KINDS[item.kind].category is not Category.CUT or item.kind == "text":
            continue
        round_ = item.kind == "hole" or _choice(item, "shape") == "circle"
        r = (
            layout.diameters.get(item.id, 0.0)
            if item.kind == "hole"
            else _length(item, "diameter")
        ) / 2
        for copy in layout.instances.get(item.id, ()):
            k = _axis_of(copy.normal)
            deep, exits = _cut_span(item, copy, layout)
            if k is None or not exits:
                continue
            halves = [r, r, r]
            if not round_ and copy.face_axes is not None:
                h1, h2 = bbox(_outline(item, layout, copy.face_axes))
                (
                    halves[_AXES.index(copy.face_axes[0])],
                    halves[_AXES.index(copy.face_axes[1])],
                ) = h1, h2
            lo = [copy.origin[i] - halves[i] for i in range(3)]
            hi = [copy.origin[i] + halves[i] for i in range(3)]
            lo[k], hi[k] = sorted(
                (copy.origin[k], copy.origin[k] - copy.normal[k] * deep)
            )
            found.append((k, (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])))
    return found


class _Occlusion:
    """What can hide what on one view: the material of the solids, less what is cut right through them.

    A thing is hidden when one solid covers it and lies wholly nearer the
    viewer, and nothing cut right through that solid lets it be seen. Solids
    and windows are filed in a grid of at most 33 x 33 cells over the part,
    so each question is asked of the few near it, not of every solid and
    every hole of the part. What reaches past the part is filed in the cells
    at its edge: a place maps to its cell the same way whatever holds it, so
    a box holding a place is always filed in that place's cell.
    """

    _CELLS = 32

    def __init__(self, canvas: _Canvas, solids: Sequence[_Solid], windows: Sequence[_Window],
                 extent: tuple[Vec, Vec]) -> None:  # fmt: skip
        self.frame = canvas.frame
        u, v = canvas.u, canvas.v
        lo, hi = extent
        self.origin = (lo[u], lo[v])
        self.cell = max(hi[u] - lo[u], hi[v] - lo[v], EPS) / self._CELLS
        self.last = (self._CELLS, self._CELLS)
        self.solids = list(solids)
        self.windows = [(wlo, whi) for k, wlo, whi in windows if k == canvas.w]
        self._solid_cells: dict[tuple[int, int], list[int]] = {}
        self._window_cells: dict[tuple[int, int], list[int]] = {}
        for n, (_, slo, shi) in enumerate(self.solids):
            for key in self._cells((slo[u], slo[v]), (shi[u], shi[v])):
                self._solid_cells.setdefault(key, []).append(n)
        for n, (wlo, whi) in enumerate(self.windows):
            for key in self._cells((wlo[u], wlo[v]), (whi[u], whi[v])):
                self._window_cells.setdefault(key, []).append(n)

    def _index(self, x: float, k: int) -> int:
        """The cell along one of the view's axes that a place is in; past the part, the cell at its edge."""
        return min(max(math.floor((x - self.origin[k]) / self.cell), 0), self.last[k])

    def _cells(
        self, lo: tuple[float, float], hi: tuple[float, float]
    ) -> Iterable[tuple[int, int]]:
        """The cells a box touches, or comes within EPS of: the tests below allow that much."""
        i0, i1 = self._index(lo[0] - EPS, 0), self._index(hi[0] + EPS, 0)
        j0, j1 = self._index(lo[1] - EPS, 1), self._index(hi[1] + EPS, 1)
        return itertools.product(range(i0, i1 + 1), range(j0, j1 + 1))

    def hides(
        self,
        lo: tuple[float, float],
        hi: tuple[float, float],
        near: float,
        own: tuple[str, int] | None,
    ) -> bool:
        u, v, w, facing = self.frame.u, self.frame.v, self.frame.w, self.frame.facing
        middle = (
            self._index((lo[0] + hi[0]) / 2, 0),
            self._index((lo[1] + hi[1]) / 2, 1),
        )
        for n in self._solid_cells.get(middle, ()):
            key, slo, shi = self.solids[n]
            if (
                key == own
                or slo[u] > lo[0] + EPS
                or shi[u] < hi[0] - EPS
                or slo[v] > lo[1] + EPS
                or shi[v] < hi[1] - EPS
            ):
                continue
            back = slo[w] if facing > 0 else shi[w]
            if back * facing >= near * facing - EPS and not self._pierced(
                slo, shi, lo, hi
            ):
                return True
        return False

    def _pierced(
        self, slo: Vec, shi: Vec, lo: tuple[float, float], hi: tuple[float, float]
    ) -> bool:
        """Whether something cut right through this solid opens onto the region."""
        u, v = self.frame.u, self.frame.v
        near = {
            m for key in self._cells(lo, hi) for m in self._window_cells.get(key, ())
        }
        for m in near:
            wlo, whi = self.windows[m]
            onto = (
                wlo[u] < hi[0] - EPS
                and whi[u] > lo[0] + EPS
                and wlo[v] < hi[1] - EPS
                and whi[v] > lo[1] + EPS
            )
            through = all(
                wlo[k] < shi[k] - EPS and whi[k] > slo[k] + EPS for k in range(3)
            )
            if onto and through:
                return True
        return False


# ----------------------------------------------------------------------
# One item, on every view
# ----------------------------------------------------------------------


class _Drawing:
    """One item drawn on every view: its outline, its dimensions, and the note that names it."""

    def __init__(self, item: Item, copies: Sequence[Instance], layout: Layout, canvases: Sequence[_Canvas],
                 hiding: Mapping[int, _Occlusion]) -> None:  # fmt: skip
        self.item = item
        self.copies = copies
        self.layout = layout
        self.canvases = canvases
        self.hiding = hiding
        #: What the note says, and the fields it shows.
        self.said: list[str] = []
        self.said_fields: list[str] = []
        #: Every field shown, on a line or in the note.
        self.covered: set[str] = set()
        self.home: _Canvas | None = None
        self.anchor: tuple[float, float] = (0.0, 0.0)

    # -- recording ----------------------------------------------------------
    def say(self, text: str, *fields: str) -> None:
        self.said.append(text)
        self.said_fields += [f for f in fields if f not in self.said_fields]
        self.covered.update(fields)

    def line(self, canvas: _Canvas, along: str, a: float, b: float, feet: tuple[float, float], text: str,
             *fields: str, words: str | None = None) -> None:  # fmt: skip
        """A dimension line; where its ends meet, the note says it instead."""
        if canvas.dimension(self.item.id, fields, along, a, b, feet, text):
            self.covered.update(fields)
        else:
            self.say(words or text, *fields)

    def canvas_along(self, k: int) -> _Canvas:
        return next(c for c in self.canvases if c.w == k)

    def hidden(self, canvas: _Canvas, lo: tuple[float, float], hi: tuple[float, float], near: float,
               own: tuple[str, int] | None) -> bool:  # fmt: skip
        """Whether material wholly nearer than ``near`` covers the region, on this view."""
        return self.hiding[canvas.w].hides(lo, hi, near, own)

    def host_face(self, copy: Instance) -> Face | None:
        if copy.host is None:
            return None
        return self.layout.faces.get((copy.host[0], copy.host[1]), {}).get(copy.host[2])

    # -- the item ---------------------------------------------------------
    def draw(self) -> None:
        if KINDS[self.item.kind].category is Category.CUT:
            self._cut()
        else:
            self._solid()
        if self.home is None:
            return  # nothing could be drawn: the item is listed as not drawn
        self._place()
        self._finish()

    # Bodies and standing features ------------------------------------------
    def _solid(self) -> None:
        item, kind = self.item, self.item.kind
        placed = [c for c in self.copies if c.lo is not None and c.hi is not None]
        if not placed:
            return  # read, but not placed in this version (an extrusion)
        for copy in placed:
            cavity = self.layout.cavities.get((item.id, copy.index))
            for canvas in self.canvases:
                style = self._outline(canvas, copy)
                if cavity is not None:
                    self._cavity(canvas, copy, cavity, style)
        first = placed[0]
        assert first.lo is not None and first.hi is not None
        lo, hi = first.lo, first.hi
        up = _axis_of(first.normal)
        host = self.host_face(first) if isinstance(item.get("on"), On) else None
        round_ = kind in (*_ROUND_KINDS, *_OUTLINED) or (
            kind == "sphere" and _choice(item, "portion") == "upper_half"
        )
        if isinstance(host, FlatFace):
            self.home = self.canvas_along(_AXES.index(host.normal[1]))
        elif round_ and up is not None:
            self.home = self.canvas_along(up)
        else:
            self.home = self.canvases[0]
        home = self.home
        if kind in _BOX_KINDS:
            self.say(
                ("tab (round end)" if _choice(item, "end") == "round" else "tab")
                if kind == "tab"
                else kind
                if kind != "region"
                else "region (designed later, within this envelope)"
            )
            for k, name in self._box_fields(first).items():
                canvas, along = self.canvases[_HOME[k][0]], _HOME[k][1]
                across = canvas.v if along == "u" else canvas.u
                self.line(
                    canvas,
                    along,
                    lo[k],
                    hi[k],
                    (lo[across], lo[across]),
                    _value(item.get(name)),
                    name,
                )
            if kind == "region":
                describe = item.get("describe")
                if isinstance(describe, Text):
                    self.say(
                        f"for {describe.text!r}{_tag(describe.provenance)}", "describe"
                    )
                if item.get("min_wall") is not None:
                    self.say(
                        f"no wall under {_value(item.get('min_wall'))}", "min_wall"
                    )
            self.anchor = (hi[home.u], hi[home.v])
            return
        if kind in _OUTLINED:
            self._outlined(first, up)
            return
        r = (hi[home.u] - lo[home.u]) / 2
        spanned = [
            k
            for k in range(3)
            if k != up
            or (kind == "sphere" and _choice(item, "portion") != "upper_half")
        ]
        for k in spanned:  # the note's diameter gives the size across
            self.canvases[_HOME[k][0]].spans.append((_HOME[k][1], lo[k], hi[k]))
        if kind == "sphere":
            whole = _choice(item, "portion") != "upper_half"
            self.say(
                f"{'ball' if whole else 'dome'} Ø{_value(item.get('diameter'))}",
                "diameter",
            )
            centre = home.at(_mid(lo, hi) if whole or home.w != up else first.origin)
            self.anchor = (
                centre[0] + r * math.sqrt(0.5),
                centre[1] + r * math.sqrt(0.5),
            )
            return
        assert up is not None, "the solver stands every body along a frame axis"
        name = "height" if kind == "boss" else "length"
        canvas, along = self.canvases[_HOME[up][0]], _HOME[up][1]
        side = canvas.v if along == "u" else canvas.u
        self.line(
            canvas,
            along,
            lo[up],
            hi[up],
            (lo[side], lo[side]),
            _value(item.get(name)),
            name,
        )
        if kind == "tube":
            self.say(f"tube Ø{_value(item.get('outer_diameter'))} outside, "
                     f"Ø{_value(item.get('inner_diameter'))} bore", "outer_diameter", "inner_diameter")  # fmt: skip
        elif kind == "cone":
            self.say(f"cone Ø{_value(item.get('base_diameter'))} at the base to "
                     f"Ø{_value(item.get('top_diameter'))} at the top", "base_diameter", "top_diameter")  # fmt: skip
        else:
            self.say(f"{kind} Ø{_value(item.get('diameter'))}", "diameter")
        centre = home.at(first.origin)  # a round item's home looks down its axis
        self.anchor = (centre[0] + r * math.sqrt(0.5), centre[1] + r * math.sqrt(0.5))

    def _outlined(self, first: Instance, up: int | None) -> None:
        """An extrusion's length as a dimension line along its axis, and either's outline in words."""
        item, home = self.item, self.home
        assert first.lo is not None and first.hi is not None and home is not None
        assert up is not None, "the solver stands every body along a frame axis"
        lo, hi = first.lo, first.hi
        if item.kind == "extrusion":
            canvas, along = self.canvases[_HOME[up][0]], _HOME[up][1]
            side = canvas.v if along == "u" else canvas.u
            self.line(
                canvas,
                along,
                lo[up],
                hi[up],
                (lo[side], lo[side]),
                _value(item.get("length")),
                "length",
            )
        profile = item.get("profile")
        outline = (
            item_outline(profile) if isinstance(profile, Profile) else "its outline"
        )
        turned = ", turned about its axis" if item.kind == "revolution" else ""
        self.say(f"{item.kind}: {outline}{turned}", "profile")
        self.anchor = (hi[home.u], hi[home.v])

    def _box_fields(self, copy: Instance) -> dict[int, str]:
        """Which field each frame axis of a box-like item's bounds comes from, as the solver builds it."""
        up = _axis_of(copy.normal)
        assert up is not None, "the solver stands every body along a frame axis"
        a1, a2 = copy.face_axes or FACE_AXES[_named(copy.normal, up)]
        kind, i = self.item.kind, _AXES.index
        if kind == "rib":
            along = _choice(self.item, "along") or a1
            other = a2 if along == a1 else a1
            return {i(along): "length", i(other): "thickness", up: "height"}
        if kind == "tab":
            thin = _choice(self.item, "thickness_along") or a2
            wide = a1 if thin == a2 else a2
            return {i(thin): "thickness", i(wide): "width", up: "length"}
        return {i(a1): "length", i(a2): "width", up: "height"}

    def _outline(self, canvas: _Canvas, copy: Instance) -> str:
        """One copy's outline on one view; the style it was drawn in."""
        item, kind = self.item, self.item.kind
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        if kind == "region":
            style = "envelope"
        else:
            near = hi[canvas.w] if canvas.frame.facing > 0 else lo[canvas.w]
            hidden = self.hidden(
                canvas, canvas.at(lo), canvas.at(hi), near, (item.id, copy.index)
            )
            style = "hidden" if hidden else "visible"
        up = _axis_of(copy.normal)
        if kind in _ROUND_KINDS and up is not None:
            across = (up + 1) % 3
            # A cone's ends are as its fields give them: its bounds are as wide as the wider end.
            r0 = (
                _length(item, "base_diameter") / 2
                if kind == "cone"
                else (hi[across] - lo[across]) / 2
            )
            r1 = _length(item, "top_diameter") / 2 if kind == "cone" else r0
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
            if kind == "tube":
                inner = _length(item, "inner_diameter") / 2
                _round(canvas, copy.origin, copy.normal, length, inner, inner, start_style=style if axial else None,
                       side_style=None if axial else "hidden", end_style=None)  # fmt: skip
            return style
        if kind in _OUTLINED and up is not None:
            _outlined(canvas, item, copy, up, style)
            return style
        if kind == "sphere":
            r = max(hi[k] - lo[k] for k in range(3)) / 2
            if _choice(item, "portion") != "upper_half" or up is None:
                canvas.circle(canvas.at(_mid(lo, hi)), r, style)
            elif canvas.w == up:
                canvas.circle(canvas.at(copy.origin), r, style)
            else:
                b = canvas.at(copy.origin)
                du, dv = copy.normal[canvas.u], copy.normal[canvas.v]
                pu, pv = -dv, du
                arc = [(b[0] + r * (math.cos(t) * pu + math.sin(t) * du), b[1] + r * (math.cos(t) * pv + math.sin(t) * dv))
                       for t in (math.pi * s / 32 for s in range(33))]  # fmt: skip
                canvas.path(arc, style, closed=True)
            return style
        if kind == "tab" and _choice(item, "end") == "round" and up is not None:
            thin = next(
                k for k, name in self._box_fields(copy).items() if name == "thickness"
            )
            r = _length(item, "width") / 2
            # All round end, it is a half disc.
            straight = max(_length(item, "length") - r, 0.0)
            if canvas.w == thin:
                b = canvas.at(copy.origin)
                du, dv = copy.normal[canvas.u], copy.normal[canvas.v]
                pu, pv = -dv, du
                bend = (b[0] + du * straight, b[1] + dv * straight)
                arc = [(bend[0] + r * (-math.cos(t) * pu + math.sin(t) * du),
                        bend[1] + r * (-math.cos(t) * pv + math.sin(t) * dv))
                       for t in (math.pi * s / 32 for s in range(33))]  # fmt: skip
                canvas.path(
                    [
                        (b[0] - r * pu, b[1] - r * pv),
                        *arc,
                        (b[0] + r * pu, b[1] + r * pv),
                    ],
                    style,
                    closed=True,
                )
                return style
        canvas.rect(canvas.at(lo), canvas.at(hi), style)
        return style

    def _cavity(
        self, canvas: _Canvas, copy: Instance, cavity: tuple[Vec, Vec], style: str
    ) -> None:
        """The hollow a shell leaves: seen through an open face, else hidden behind a wall."""
        shell = self.layout.shells.get(self.item.id)
        opened = shell.get("open") if shell is not None else None
        open_faces = set(getattr(opened, "faces", ()))
        lo, hi = cavity
        up = _axis_of(copy.normal)
        if self.item.kind == "cylinder" and up is not None and canvas.w == up:
            end = "+end" if copy.normal[up] * canvas.frame.facing > 0 else "-end"
            r = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
            canvas.circle(
                canvas.at(_mid(lo, hi)), r, style if end in open_faces else "hidden"
            )
            return
        looking_at = ("+" if canvas.frame.facing > 0 else "-") + _AXES[canvas.w]
        seen = self.item.kind == "block" and looking_at in open_faces
        canvas.rect(canvas.at(lo), canvas.at(hi), style if seen else "hidden")

    # Cuts ----------------------------------------------------------------
    def _cut(self) -> None:
        item, kind, layout = self.item, self.item.kind, self.layout
        emboss = kind == "text" and _choice(item, "mode") == "emboss"
        round_ = kind == "hole" or (
            kind == "pocket" and _choice(item, "shape") == "circle"
        )
        r = (
            layout.diameters.get(item.id, 0.0)
            if kind == "hole"
            else _length(item, "diameter")
        ) / 2
        for copy in self.copies:
            deep, exits = _cut_span(item, copy, layout)
            n = copy.normal
            into = n if emboss else _neg(n)
            out = (
                copy.origin[0] + into[0] * deep,
                copy.origin[1] + into[1] * deep,
                copy.origin[2] + into[2] * deep,
            )
            halves = None if round_ else self._halves(copy)
            for canvas in self.canvases:
                axial = math.hypot(n[canvas.u], n[canvas.v]) <= EPS
                if round_:
                    seen_in, seen_out = self._seen(canvas, copy, out, exits, (r, r))
                    _round(canvas, copy.origin, into, deep, r, r,
                           start_style=_style(seen_in or seen_out) if axial else _style(seen_in),
                           side_style="hidden", end_style=None if axial else _style(seen_out))  # fmt: skip
                    self._hole_extras(canvas, copy, into, r, axial)
                elif halves is not None and axial:
                    hu, hv = halves[canvas.u], halves[canvas.v]
                    seen_in, seen_out = self._seen(
                        canvas, copy, out, exits and kind != "text", (hu, hv)
                    )
                    c = canvas.at(copy.origin)
                    canvas.rect((c[0] - hu, c[1] - hv), (c[0] + hu, c[1] + hv), _style(seen_in or seen_out),
                                self._corner_radius())  # fmt: skip
                    text = item.get("text")
                    if kind == "text" and seen_in and isinstance(text, Text):
                        canvas.write(c, text.text, _length(item, "height"), 2 * hu)
                elif halves is not None:
                    self._depth_box(canvas, copy, into, deep, halves, emboss)
        first = self.copies[0]
        k = _axis_of(first.normal)
        if k is not None:
            self.home = self.canvas_along(k)
        else:  # a hole at an angle into a round side: the view down the side's axis
            face = self.host_face(first)
            self.home = self.canvas_along(
                _AXES.index(face.axis) if isinstance(face, SideFace) else 2
            )
        home = self.home
        c = home.at(first.origin)
        halves = None if round_ else self._halves(first)
        if halves is not None and k == home.w:
            self.anchor = (c[0] + halves[home.u], c[1] + halves[home.v])
        else:
            self.anchor = (c[0] + r * math.sqrt(0.5), c[1] + r * math.sqrt(0.5))
        self._cut_words()

    def _seen(self, canvas: _Canvas, copy: Instance, out: Vec, exits: bool,
              reach_: tuple[float, float]) -> tuple[bool, bool]:  # fmt: skip
        """Whether a cut's mouth is seen, and, right through, where it comes out: each about its own place."""

        def clear(at: Vec, facing: Vec) -> bool:
            c = canvas.at(at)
            lo2, hi2 = (
                (c[0] - reach_[0], c[1] - reach_[1]),
                (c[0] + reach_[0], c[1] + reach_[1]),
            )
            return canvas.faces_viewer(facing) and not self.hidden(
                canvas, lo2, hi2, at[canvas.w], None
            )

        return clear(copy.origin, copy.normal), exits and clear(out, _neg(copy.normal))

    def _halves(self, copy: Instance) -> tuple[float, float, float] | None:
        """A square-edged cut's half sizes along the frame axes, 0 along its own axis."""
        if copy.face_axes is None:
            return None  # pragma: no cover - only round holes go into a round side
        h1, h2 = bbox(_outline(self.item, self.layout, copy.face_axes))
        out = [0.0, 0.0, 0.0]
        out[_AXES.index(copy.face_axes[0])], out[_AXES.index(copy.face_axes[1])] = (
            h1,
            h2,
        )
        return out[0], out[1], out[2]

    def _depth_box(self, canvas: _Canvas, copy: Instance, into: Vec, deep: float,
                   halves: tuple[float, float, float], emboss: bool) -> None:  # fmt: skip
        """A square-edged cut seen from the side: hidden in the material; embossed letters stand out of it."""
        k = _axis_of(copy.normal)
        if k is None:  # pragma: no cover - a flat face is square to a frame axis
            return
        lo = [copy.origin[i] - halves[i] for i in range(3)]
        hi = [copy.origin[i] + halves[i] for i in range(3)]
        lo[k], hi[k] = sorted((copy.origin[k], copy.origin[k] + into[k] * deep))
        a, b = (lo[canvas.u], lo[canvas.v]), (hi[canvas.u], hi[canvas.v])
        style = "hidden"
        if emboss:
            near = hi[canvas.w] if canvas.frame.facing > 0 else lo[canvas.w]
            style = "hidden" if self.hidden(canvas, a, b, near, None) else "visible"
        canvas.rect(a, b, style)

    def _corner_radius(self) -> float:
        item = self.item
        if item.kind == "pocket":
            return min(
                _length(item, "corner_radius"),
                _length(item, "length") / 2,
                _length(item, "width") / 2,
            )
        if (
            item.kind == "slot"
            and _choice(item, "ends") == "round"
            and _length(item, "length") >= _length(item, "width")
        ):
            return _length(item, "width") / 2
        return 0.0

    def _hole_extras(
        self, canvas: _Canvas, copy: Instance, into: Vec, r: float, axial: bool
    ) -> None:
        """A counterbore or countersink at the mouth: seen as far out as it reaches, not as far as the bore."""
        bore, sink = self.item.get("counterbore"), self.item.get("countersink")
        end = None if axial else "hidden"
        if isinstance(bore, Counterbore):
            rb = mm(bore.diameter) / 2
            seen, _ = self._seen(canvas, copy, copy.origin, False, (rb, rb))
            _round(canvas, copy.origin, into, mm(bore.depth), rb, rb, start_style=_style(seen), side_style="hidden",
                   end_style=end)  # fmt: skip
        if isinstance(sink, Countersink):
            rs, angle = mm(sink.diameter) / 2, degrees(sink.angle)
            if rs > r and 0 < angle < 180:
                seen, _ = self._seen(canvas, copy, copy.origin, False, (rs, rs))
                deep = (rs - r) / math.tan(math.radians(angle) / 2)
                _round(canvas, copy.origin, into, deep, rs, r, start_style=_style(seen), side_style="hidden",
                       end_style=end)  # fmt: skip

    def _cut_words(self) -> None:
        item, kind = self.item, self.item.kind
        depth = item.get("depth")
        if kind == "hole":
            diameter = item.get("diameter")
            if isinstance(diameter, Fit):
                self.say(
                    "hole " + _fit(diameter, self.layout.diameters.get(item.id)),
                    "diameter",
                )
            else:
                self.say(f"hole Ø{_value(diameter)}", "diameter")
            self.say(_through(depth), "depth")
            bore, sink = item.get("counterbore"), item.get("countersink")
            if isinstance(bore, Counterbore):
                self.say(
                    f"counterbored Ø{_value(bore.diameter)}, {_value(bore.depth)} deep",
                    "counterbore",
                )
            if isinstance(sink, Countersink):
                self.say(
                    f"countersunk Ø{_value(sink.diameter)} at {_value(sink.angle)}",
                    "countersink",
                )
            return
        if kind == "pocket":
            if _choice(item, "shape") == "circle":
                self.say(f"round pocket Ø{_value(item.get('diameter'))}", "diameter")
            else:
                self.say(
                    f"pocket {_value(item.get('length'))} x {_value(item.get('width'))}",
                    "length",
                    "width",
                )
                if item.get("corner_radius") is not None:
                    self.say(
                        f"corners R{_value(item.get('corner_radius'))}", "corner_radius"
                    )
            self.say(_through(depth), "depth")
            return
        if kind == "slot":
            self.say(f"slot {_value(item.get('length'))} long, {_value(item.get('width'))} wide, "
                     f"{_choice(item, 'ends') or 'square'} ends", "length", "width")  # fmt: skip
            self.say(_through(depth), "depth")
            return
        text = item.get("text")
        shown = (
            f"{text.text!r}{_tag(text.provenance)}" if isinstance(text, Text) else "?"
        )
        self.say(
            f"text {shown}, capitals {_value(item.get('height'))} tall",
            "text",
            "height",
        )
        if _choice(item, "mode") == "emboss":
            self.say(f"embossed {_value(depth)} high", "depth")
        else:
            self.say(f"engraved {_value(depth)} deep", "depth")

    # Where it is ------------------------------------------------------------
    def _place(self) -> None:
        item = self.item
        if not isinstance(item.get("on"), On):
            return
        first = self.copies[0]
        face = self.host_face(first)
        local = [c for c in self.copies if c.host == first.host]
        held = item.get("place")
        place = held if isinstance(held, Place) else None
        pattern = place.pattern if place is not None else None
        if place is not None and place.concentric:
            self.say(
                f"concentric with {place.concentric}{_tag(place.concentric_provenance)}",
                "place.concentric",
            )
        if isinstance(face, FlatFace):
            self._on_flat(face, local, place, pattern)
        elif isinstance(face, SideFace):
            self._on_side(face, local, place)
        if pattern is not None:
            self._pattern_words(face, pattern)

    def _on_flat(self, face: FlatFace, local: Sequence[Instance], place: Place | None,
                 pattern: Pattern | None) -> None:  # fmt: skip
        """Where on a flat face: from the edges or the centre its place names; then the steps of its pattern."""
        canvas = self.canvas_along(_AXES.index(face.normal[1]))
        index = (_AXES.index(face.axes[0]), _AXES.index(face.axes[1]))
        feet = bbox(_outline(self.item, self.layout, face.axes))
        concentric = place is not None and bool(place.concentric)
        # What a place is measured to (docs/definitions/place.md): the copy
        # the solver placed; for a row, grid or rectangle measured from an
        # edge, its nearest copy, and centred or offset, its centre; for a
        # circle or arc, its centre.
        anchors, centres = [], []
        for k in (0, 1):
            position = place.axes.get(face.axes[k]) if place is not None else None
            coords = [c.origin[index[k]] for c in local]
            if pattern is None:
                anchors.append(coords[0])
                centres.append(coords[0])
                continue
            if pattern.kind in ("circle", "arc"):
                shift = (
                    _along(position, face.half[k], feet[k])
                    if position is not None
                    else 0.0
                )
                centres.append(face.centre[index[k]] + shift)
                anchors.append(centres[-1])
                continue
            centres.append((min(coords) + max(coords)) / 2)
            if position is not None and position.mode == "side":
                anchors.append(
                    min(coords)
                    if (position.side or "+").startswith("-")
                    else max(coords)
                )
            else:
                anchors.append(centres[-1])
        for k in (0, 1):
            a, i, other = face.axes[k], index[k], 1 - k
            along = "u" if i == canvas.u else "v"
            edge_foot = face.centre[index[other]] - face.half[other]
            low_edge = face.centre[i] - face.half[k]
            if pattern is not None and (
                pattern.kind == "corners"
                or (pattern.kind == "ends" and pattern.axis == a)
            ):
                name = f"inset_{a}" if pattern.kind == "corners" else "inset"
                inset = _value(pattern.values.get(name))
                self.line(canvas, along, low_edge, local[0].origin[i], (edge_foot, local[0].origin[index[other]]),
                          inset, f"place.pattern.{name}", words=f"{inset} in from the edges along {a.upper()}")  # fmt: skip
                continue
            if concentric:
                continue
            position = place.axes.get(a) if place is not None else None
            ref, target, text, fields = _measured(
                a, position, face.centre[i], face.half[k], anchors[k], feet[k]
            )
            self.line(canvas, along, ref, target, (edge_foot, anchors[other]), text, *fields,
                      words=_position_words(a, position) if position is not None else None)  # fmt: skip
        if pattern is None:
            return
        centre = list(face.centre)
        centre[index[0]], centre[index[1]] = centres
        middle = canvas.at((centre[0], centre[1], centre[2]))
        if (
            pattern.kind != "corners"
            and not concentric
            and not any(
                all(abs(c.origin[i] - centre[i]) <= EPS for i in index) for c in local
            )
        ):
            canvas.mark(middle)  # the place is measured to the pattern's centre
        values, counts = pattern.values, pattern.counts

        def between(j: int, k: int, name: str, text: str) -> None:
            """The step from the first copy to copy ``j``, along the face's axis ``k``."""
            if j >= len(local):
                return  # pragma: no cover - a pattern makes all its copies or none
            ax, other = index[k], index[1 - k]
            self.line(canvas, "u" if ax == canvas.u else "v", local[0].origin[ax], local[j].origin[ax],
                      (local[0].origin[other], local[j].origin[other]), text, f"place.pattern.{name}")  # fmt: skip

        if (
            pattern.kind == "row"
            and pattern.axis in face.axes
            and "pitch" in values
            and len(local) > 1
        ):
            between(
                1,
                face.axes.index(pattern.axis),
                "pitch",
                _value(values["pitch"]) + " apart",
            )
        elif pattern.kind == "grid":
            n1, n2 = (
                counts[f"count_{a}"].n if f"count_{a}" in counts else 1
                for a in face.axes
            )
            for k, (step, n) in enumerate(((n2, n1), (1, n2))):
                name = f"pitch_{face.axes[k]}"
                if n >= 2 and name in values:
                    between(step, k, name, _value(values[name]) + " apart")
        elif pattern.kind == "rectangle":
            for k, step in ((0, 2), (1, 1)):
                if face.axes[k] in values:
                    between(step, k, face.axes[k], _value(values[face.axes[k]]))
        elif pattern.kind in ("circle", "arc") and "diameter" in values:
            canvas.circle(middle, mm(values["diameter"]) / 2, "centre")

    def _on_side(
        self, face: SideFace, local: Sequence[Instance], place: Place | None
    ) -> None:
        """Where on a round side: along its axis from the end its place names, and at what angle round it."""
        k = _AXES.index(face.axis)
        home = self.home
        canvas = (
            home
            if home is not None and k in (home.u, home.v)
            else self.canvases[_HOME[k][0]]
        )
        along = "u" if k == canvas.u else "v"
        across = canvas.v if along == "u" else canvas.u
        half = face.length / 2
        position = place.axes.get(face.axis) if place is not None else None
        first = local[0]
        if KINDS[self.item.kind].category is Category.CUT:
            foot = reach(_outline(self.item, self.layout, (face.axis, face.axis)))
        else:
            foot = bbox(
                _outline(
                    self.item, self.layout, first.face_axes or (face.axis, face.axis)
                )
            )[1]
        ref, target, text, fields = _measured(
            face.axis, position, face.start[k] + half, half, first.origin[k], foot
        )
        self.line(canvas, along, ref, target, (face.start[across] - face.radius, first.origin[across]), text,
                  *fields, words=_position_words(face.axis, position, "end") if position is not None else None)  # fmt: skip
        zero = _ZERO_ON[face.axis].upper()
        pattern = place.pattern if place is not None else None
        spread = pattern is not None and pattern.kind in ("circle", "arc")
        lead = "the first at" if spread else "at"
        if pattern is not None and pattern.kind == "circle":
            self.say(f"equally spaced round {face.axis.upper()}")
        if place is not None and place.angle is not None:
            self.say(
                f"{lead} {_value(place.angle)} from +{zero} round {face.axis.upper()}",
                "place.angle",
            )
        else:
            self.say(f"{lead} 0° from +{zero} round {face.axis.upper()} (assumed)")

    def _pattern_words(self, face: Face | None, pattern: Pattern) -> None:
        """What a pattern's lines don't show: its counts, its circle, its first angle and its step."""
        values, counts = pattern.values, pattern.counts
        if pattern.kind == "grid":
            names = sorted(n for n in counts if n.startswith("count_"))
            if names:
                self.say("a grid of " + " x ".join(_value(counts[n]) for n in names),
                         *(f"place.pattern.{n}" for n in names))  # fmt: skip
        if pattern.kind in ("circle", "arc"):
            if "diameter" in values:
                self.say(
                    f"on a Ø{_value(values['diameter'])} circle",
                    "place.pattern.diameter",
                )
            if "step" in values:
                self.say(f"{_value(values['step'])} apart", "place.pattern.step")
            if "start" in values:
                self.say(
                    f"the first at {_value(values['start'])}", "place.pattern.start"
                )
            elif isinstance(face, FlatFace):
                self.say(f"the first at 0°, on +{face.axes[0].upper()} (assumed)")
        if "count" in counts:
            hosts = {c.host for c in self.copies}
            n = counts["count"]
            if len(hosts) == 1 and n.n == len(self.copies) > 1:
                self.covered.add("place.pattern.count")  # the note's "n x" says it
                self.said_fields.append("place.pattern.count")
            elif len(hosts) == 1:
                self.say(f"{_value(n)} in the pattern", "place.pattern.count")
            else:
                host = self.copies[0].host
                self.say(f"{_value(n)} on each of the {len(hosts)} copies of {host[0] if host else 'its host'}",
                         "place.pattern.count")  # fmt: skip

    def _finish(self) -> None:
        item = self.item
        count = item.get("count")
        prefix = ""
        if isinstance(count, Count):
            prefix = f"{_value(count)} x "
            self.covered.add("count")
            self.said_fields.insert(0, "count")
        elif len(self.copies) > 1:
            prefix = f"{len(self.copies)} x "
        for path, words in _to_show(item).items():
            if path not in self.covered:
                self.say(words, path)
        assert self.home is not None
        self.home.note(item.id, tuple(dict.fromkeys(self.said_fields)), self.anchor,
                       f"{item.id}: {prefix}{', '.join(self.said)}")  # fmt: skip


def _measured(axis: str, position: AxisPosition | None, centre: float, half: float, anchor: float,
              foot: float) -> tuple[float, float, str, tuple[str, ...]]:  # fmt: skip
    """How a place along one axis is measured: from where, to where, its text, and the field it shows.

    As the place says: from the edge it names to the centre or the near edge,
    or from the centre by an offset. Centred, it is measured from the low edge.
    """
    fields = (f"place.{axis}",) if position is not None else ()
    low = centre - half
    if position is None:
        return low, anchor, f"{_mm(anchor - low)} (centred, assumed)", fields
    if position.mode == "centred" or position.distance is None:
        assumed = (
            position.provenance is not None
            and position.provenance.source is Source.ASSUMED
        )
        return (
            low,
            anchor,
            f"{_mm(anchor - low)} (centred{', assumed' if assumed else ''})",
            fields,
        )
    if position.mode == "offset":
        return centre, anchor, _value(position.distance), fields
    sign = -1.0 if (position.side or "+").startswith("-") else 1.0
    target = anchor + sign * foot if position.to == "edge" else anchor
    return centre + sign * half, target, _value(position.distance), fields


# ----------------------------------------------------------------------
# The views
# ----------------------------------------------------------------------
def render_views(report: SpecReport) -> Views:
    """The top, front and side views of a checked draft, every value of every placed item shown."""
    spec, layout = report.spec, report.layout
    if spec is None:
        return Views((), (), (), None)
    words = tuple(Dimension(i.id, tuple(i.fields), item_line(i), "words")
                  for i in spec.items if KINDS[i.kind].category is Category.MODIFY)  # fmt: skip
    drawable = [i for i in spec.items if KINDS[i.kind].category is not Category.MODIFY]
    extent = layout.extent() if layout is not None else None
    if layout is None or extent is None:
        return Views((), words, tuple(i.id for i in drawable), None)
    lo, hi = extent
    size = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    scale = max(size) if max(size) > EPS else 1.0
    decimals = max(2, 4 - math.floor(math.log10(scale)))
    canvases = [_Canvas(frame, scale / _SPAN_PX, decimals) for frame in _FRAMES]
    solids: list[_Solid] = [((i.item, i.index), *box) for item in drawable
                            if KINDS[item.kind].category in (Category.BODY, Category.ADD)
                            for i in layout.instances.get(item.id, ()) for box in _inside(item, i, layout)]  # fmt: skip
    windows = _windows(drawable, layout)
    hiding = {c.w: _Occlusion(c, solids, windows, extent) for c in canvases}
    for item in drawable:
        copies = layout.instances.get(item.id, [])
        if copies:
            _Drawing(item, copies, layout, canvases, hiding).draw()
    _overall(canvases, lo, hi, size)
    views = tuple(
        View(c.frame.name, c.frame.caption, c.svg(), tuple(c.shown)) for c in canvases
    )
    drawn = {d.item for view in views for d in view.dimensions}
    return Views(views, words, tuple(i.id for i in drawable if i.id not in drawn), size)


def _inside(item: Item, copy: Instance, layout: Layout) -> list[tuple[Vec, Vec]]:
    """Boxes wholly inside one copy's material: what can hide something behind it.

    A box is the whole of it; a hollowed box, its walls. A round thing hides
    only what the box inside it would: the square in its circle, the cube in a
    ball. A tube's ring, and a hollowed round thing, hide nothing here. So
    nothing is ever drawn hidden that can be seen; something hidden behind a
    curve may be drawn as seen.
    """
    lo, hi, kind = copy.lo, copy.hi, item.kind
    up = _axis_of(copy.normal)
    if lo is None or hi is None or up is None:
        return []
    cavity = layout.cavities.get((item.id, copy.index))
    if kind in ("block", "post", "rib") or (
        kind == "tab" and _choice(item, "end") != "round"
    ):
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
    if cavity is not None or kind == "tube" or item.id in layout.shells:
        return []
    base, direction = copy.origin, copy.normal
    if kind == "tab":  # its square part, short of the round end
        straight = _length(item, "length") - _length(item, "width") / 2
        if straight <= EPS:
            return []
        blo, bhi = list(lo), list(hi)
        far = base[up] + direction[up] * straight
        blo[up], bhi[up] = min(base[up], far), max(base[up], far)
        return [((blo[0], blo[1], blo[2]), (bhi[0], bhi[1], bhi[2]))]
    if kind == "sphere":
        r = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
        if _choice(item, "portion") != "upper_half":
            half = r / math.sqrt(3)
            c = _mid(lo, hi)
            return [
                (
                    (c[0] - half, c[1] - half, c[2] - half),
                    (c[0] + half, c[1] + half, c[2] + half),
                )
            ]
        blo, bhi = (
            [base[k] - r / 2 for k in range(3)],
            [base[k] + r / 2 for k in range(3)],
        )
        far = base[up] + direction[up] * r / math.sqrt(2)
        blo[up], bhi[up] = min(base[up], far), max(base[up], far)
        return [((blo[0], blo[1], blo[2]), (bhi[0], bhi[1], bhi[2]))]
    across = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
    if kind == "cone":  # the square in its narrower end, all its length
        across = min(_length(item, "base_diameter"), _length(item, "top_diameter")) / 2
    r = across
    if r <= EPS:
        return []
    half = r / math.sqrt(2)
    centre = _mid(lo, hi)
    blo = [centre[k] - half if k != up else lo[k] for k in range(3)]
    bhi = [centre[k] + half if k != up else hi[k] for k in range(3)]
    return [((blo[0], blo[1], blo[2]), (bhi[0], bhi[1], bhi[2]))]


def _overall(canvases: Sequence[_Canvas], lo: Vec, hi: Vec, size: Vec) -> None:
    """The part's overall size along each axis, where no one item's dimension spans it already."""
    for k in range(3):
        canvas, along = canvases[_HOME[k][0]], _HOME[k][1]
        if canvas.spans_already(along, lo[k], hi[k]):
            continue
        across = canvas.v if along == "u" else canvas.u
        canvas.dimension("", (f"overall.{_AXES[k]}",), along, lo[k], hi[k], (lo[across], lo[across]),
                         f"{_mm(size[k])} overall")  # fmt: skip
