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

from forge_numeric import scalar as fs

from .checks import SpecReport
from .draft import (
    AxisPosition,
    Counterbore,
    Countersink,
    Fit,
    Item,
    On,
    Pattern,
    Place,
    Text,
    Through,
)
from .ends import Blind, ThroughAll, end_of
from .geometry import (
    EPS,
    Face,
    FlatFace,
    Part,
    SideFace,
    Vec,
    bbox,
    least_material_under,
    most_material_under,
    reach,
    side_material,
    side_most_material,
)
from .items.solve._common import _turn, degrees
from .items.views import VIEWS
from .items.views._common import (
    _AXES,
    _HOME,
    _axis_of,
    _fit,
    _length,
    _mm,
    _named,
    _neg,
    _round,
    _style,
    _tag,
    _through,
    _value,
)
from .items.views.pattern import PATTERN_VIEWS
from .outline import Arc as OutlineArc
from .outline import Shape
from .placement import Instance, Layout, _along, _outline, _reaches, mm, turned_outline
from .render import _line as item_line
from .schema import FACE_AXES
from .values import Count, Source, Value

__all__ = ["Dimension", "View", "Views", "render_views"]

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
            if value.turn is not None:
                out["place.turn"] = f"turned {_value(value.turn)}"
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
        self, centre: tuple[float, float], text: str, height: float, width: float, angle: float = 0.0
    ) -> None:
        """Engraved or embossed letters, a capital ``height`` tall, filling ``width`` about ``centre``; turned
        ``angle`` degrees (as the drawing's own rotation: clockwise as drawn) where they are turned in their face.

        The width is the solver's estimate of the letters' outline, so they are
        drawn exactly where the checks took them to be.
        """
        cu, cv = centre
        size = height / 0.72  # a capital is about 0.72 of the type size
        turned = f' transform="rotate({self._f(angle)} {self._f(cu)} {self._f(-cv)})"' if abs(angle) > EPS else ""
        self.letters.append(f'<text x="{self._f(cu)}" y="{self._f(-cv)}" font-size="{self._f(size)}" '
                            f'text-anchor="middle" dominant-baseline="central" textLength="{self._f(width)}" '
                            f'lengthAdjust="spacingAndGlyphs"{turned}>{html.escape(text)}</text>')  # fmt: skip

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


# ----------------------------------------------------------------------
# What hides what
# ----------------------------------------------------------------------
_Solid = tuple[tuple[str, int], Vec, Vec]
#: Round each axis, where 0 degrees is: the axis the solver turns a round side's angles from.
_ZERO_ON = {"z": "x", "x": "y", "y": "z"}
#: A hole or cut right through, along a frame axis: the axis, and the box of air it leaves.
_Window = tuple[int, Vec, Vec]


def _unit_axis(name: str) -> Vec:
    k = _AXES.index(name)
    return (1.0 if k == 0 else 0.0, 1.0 if k == 1 else 0.0, 1.0 if k == 2 else 0.0)


def _cross_of(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _line_half(item: Item, layout: Layout, axes: tuple[str, str]) -> float:
    """Half a line of letters' length: its line's box's (the solver's estimate of their outline)."""
    return bbox(_outline(item, layout, axes))[0]


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
        turned = turned_outline(item, layout, face.axes)
        mouth: tuple[Part, ...] | Shape = (
            VIEWS[item.kind].cut_mouth(item, layout, face.axes) if turned is None else turned
        )
        least = least_material_under(face, mouth, p1, p2)
        most = most_material_under(face, mouth, p1, p2)
    elif isinstance(face, SideFace):
        r = layout.diameters.get(item.id, 0.0) / 2
        least, most = side_material(face, r), side_most_material(face, r)
    emboss = VIEWS[item.kind].embossed(item)
    end = end_of(item)
    if emboss:
        return (mm(end.depth) if isinstance(end, Blind) else 0.0), False
    through = isinstance(end, ThroughAll) or (
        isinstance(end, Blind) and least > EPS and mm(end.depth) >= least - EPS
    )
    deep = (
        most
        if isinstance(end, ThroughAll)
        else (min(mm(end.depth), most) if isinstance(end, Blind) else 0.0)
    )
    return deep, not VIEWS[item.kind].lettered and least > EPS and through


def _windows(items: Iterable[Item], layout: Layout) -> list[_Window]:
    """Every copy of a cut that goes right through, along a frame axis: what can be seen through."""
    found: list[_Window] = []
    for item in items:
        if not VIEWS[item.kind].window:
            continue
        round_ = VIEWS[item.kind].cut_round(item)
        r = VIEWS[item.kind].cut_radius(item, layout)
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
        if VIEWS[self.item.kind].cut:
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
        up = _axis_of(first.normal)
        host = self.host_face(first) if isinstance(item.get("on"), On) else None
        round_ = VIEWS[kind].homed_down_axis(item)
        if isinstance(host, FlatFace):
            self.home = self.canvas_along(_AXES.index(host.normal[1]))
        elif round_ and up is not None:
            self.home = self.canvas_along(up)
        else:
            self.home = self.canvases[0]
        VIEWS[kind].body(self, first, up)

    def _box_fields(self, copy: Instance) -> dict[int, str]:
        """Which field each frame axis of a box-like item's bounds comes from, as the solver builds it."""
        up = _axis_of(copy.normal)
        assert up is not None, "the solver stands every body along a frame axis"
        a1, a2 = copy.face_axes or FACE_AXES[_named(copy.normal, up)]
        return VIEWS[self.item.kind].box_fields(self.item, a1, a2, up)

    def _outline(self, canvas: _Canvas, copy: Instance) -> str:
        """One copy's outline on one view; the style it was drawn in."""
        item = self.item
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        if VIEWS[item.kind].envelope:
            style = "envelope"
        else:
            near = hi[canvas.w] if canvas.frame.facing > 0 else lo[canvas.w]
            hidden = self.hidden(
                canvas, canvas.at(lo), canvas.at(hi), near, (item.id, copy.index)
            )
            style = "hidden" if hidden else "visible"
        turned = self.turned(copy)
        up = _axis_of(copy.normal)
        if turned is not None and canvas.w == up:  # looked at along its face's normal: its turned outline
            canvas.path(self.on_canvas(canvas, copy, turned), style, closed=True)
            return style
        VIEWS[item.kind].outline(self, canvas, copy, style, up)
        return style

    def turned(self, copy: Instance) -> Shape | None:
        """A copy's outline turned in its flat face's plane (place.turn), about its point, in the face's axes; None if
        it isn't turned."""
        host = self.host_face(copy) if copy.host is not None else None
        if not isinstance(host, FlatFace):
            return None
        return turned_outline(self.item, self.layout, host.axes)

    def on_canvas(self, canvas: _Canvas, copy: Instance, shape: Shape) -> list[tuple[float, float]]:
        """An outline in a copy's face's axes about its point, as points on a view (each arc by chords 3 degrees
        round)."""
        host = self.host_face(copy)
        assert isinstance(host, FlatFace)
        i1, i2 = (_AXES.index(a) for a in host.axes)
        found = []
        for q in shape.pieces:
            if isinstance(q, OutlineArc):
                steps = max(1, math.ceil(abs(q.sweep) / math.radians(3.0)))
                ats = [q.at(k / steps) for k in range(steps)]
            else:
                ats = [q.a]
            for x, y in ats:
                p = list(copy.origin)
                p[i1] += x
                p[i2] += y
                found.append(canvas.at((p[0], p[1], p[2])))
        return found

    def _cavity(
        self, canvas: _Canvas, copy: Instance, cavity: tuple[Vec, Vec], style: str
    ) -> None:
        """The hollow a shell leaves: seen through an open face, else hidden behind a wall."""
        shell = self.layout.shells.get(self.item.id)
        opened = shell.get("open") if shell is not None else None
        open_faces = set(getattr(opened, "faces", ()))
        up = _axis_of(copy.normal)
        VIEWS[self.item.kind].cavity(self, canvas, copy, cavity, style, open_faces, up)

    # Cuts ----------------------------------------------------------------
    def _cut(self) -> None:
        item, layout = self.item, self.layout
        entry = VIEWS[item.kind]
        emboss = entry.embossed(item)
        round_ = entry.cut_round(item)
        r = entry.cut_radius(item, layout)
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
                axial = fs.hypot(n[canvas.u], n[canvas.v]) <= EPS
                if round_:
                    seen_in, seen_out = self._seen(canvas, copy, out, exits, (r, r))
                    _round(canvas, copy.origin, into, deep, r, r,
                           start_style=_style(seen_in or seen_out) if axial else _style(seen_in),
                           side_style="hidden", end_style=None if axial else _style(seen_out))  # fmt: skip
                    self._hole_extras(canvas, copy, into, r, axial)
                elif halves is not None and axial:
                    hu, hv = halves[canvas.u], halves[canvas.v]
                    seen_in, seen_out = self._seen(
                        canvas, copy, out, exits and not entry.lettered, (hu, hv)
                    )
                    c = canvas.at(copy.origin)
                    turned = self.turned(copy)
                    if turned is not None:  # turned in its face: its turned outline
                        canvas.path(self.on_canvas(canvas, copy, turned), _style(seen_in or seen_out), closed=True)
                    else:
                        canvas.rect((c[0] - hu, c[1] - hv), (c[0] + hu, c[1] + hv), _style(seen_in or seen_out),
                                    entry.corner_radius(item))  # fmt: skip
                    text = item.get("text")
                    if entry.lettered and seen_in and isinstance(text, Text):
                        if turned is None:
                            canvas.write(c, text.text, _length(item, "height"), 2 * hu)
                        else:
                            self._turned_letters(canvas, copy, turned, text.text)
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
        entry.cut_words(self)

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
        """A square-edged cut's half sizes along the frame axes, 0 along its own axis: turned in its face, the box
        round its turned outline's."""
        if copy.face_axes is None:
            return None  # pragma: no cover - only round holes go into a round side
        turned = self.turned(copy)
        if turned is not None:
            (l1, l2), (u1, u2) = turned.box()
            h1, h2 = max(-l1, u1), max(-l2, u2)
        else:
            h1, h2 = bbox(_outline(self.item, self.layout, copy.face_axes))
        out = [0.0, 0.0, 0.0]
        out[_AXES.index(copy.face_axes[0])], out[_AXES.index(copy.face_axes[1])] = (
            h1,
            h2,
        )
        return out[0], out[1], out[2]

    def _turned_letters(self, canvas: _Canvas, copy: Instance, turned: Shape, text: str) -> None:
        """Turned letters on the view looking at their face: as wide as their line is long, turned on the drawing as
        their reading way is from where unturned letters' is (up their face's second axis, turned with them; they
        read along up across outward, text.md)."""
        host = self.host_face(copy)
        place = self.item.get("place")
        assert isinstance(host, FlatFace) and isinstance(place, Place) and place.turn is not None
        c, s = _turn(degrees(place.turn))
        first, second = (_unit_axis(a) for a in host.axes)
        out = copy.normal
        up = (-s * first[0] + c * second[0], -s * first[1] + c * second[1], -s * first[2] + c * second[2])
        reads, was = _cross_of(up, out), _cross_of(second, out)
        angle = math.atan2(reads[canvas.v], reads[canvas.u]) - math.atan2(was[canvas.v], was[canvas.u])
        line = 2 * _line_half(self.item, self.layout, host.axes)
        canvas.write(canvas.at(copy.origin), text, _length(self.item, "height"), line,
                     (-math.degrees(angle)) % 360.0)  # fmt: skip

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
                deep = (rs - r) / fs.tan(math.radians(angle) / 2)
                _round(canvas, copy.origin, into, deep, rs, r, start_style=_style(seen), side_style="hidden",
                       end_style=end)  # fmt: skip

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
        # How far it reaches back and forth from its point along each axis, as the solver measures to an edge: an
        # extrusion's or a revolution's outline; turned in its face, the box round its turned outline.
        shape = turned_outline(self.item, self.layout, face.axes)
        reaches = _reaches(self.item)
        if shape is not None:
            (l1, l2), (u1, u2) = shape.box()
            reaches = ((l1, u1), (l2, u2))
        extents = reaches or ((-feet[0], feet[0]), (-feet[1], feet[1]))
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
            if PATTERN_VIEWS[pattern.kind].round:
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
            name = (
                PATTERN_VIEWS[pattern.kind].inset(pattern, a)
                if pattern is not None
                else None
            )
            if name is not None and pattern is not None:
                inset = _value(pattern.values.get(name))
                self.line(canvas, along, low_edge, local[0].origin[i], (edge_foot, local[0].origin[index[other]]),
                          inset, f"place.pattern.{name}", words=f"{inset} in from the edges along {a.upper()}")  # fmt: skip
                continue
            if concentric:
                continue
            position = place.axes.get(a) if place is not None else None
            low, high = extents[k]
            foot = -low if position is not None and (position.side or "+").startswith("-") else high
            ref, target, text, fields = _measured(
                a, position, face.centre[i], face.half[k], anchors[k], foot
            )
            self.line(canvas, along, ref, target, (edge_foot, anchors[other]), text, *fields,
                      words=_position_words(a, position) if position is not None else None)  # fmt: skip
        if pattern is None:
            return
        centre = list(face.centre)
        centre[index[0]], centre[index[1]] = centres
        middle = canvas.at((centre[0], centre[1], centre[2]))
        if (
            PATTERN_VIEWS[pattern.kind].measured_to_centre
            and not concentric
            and not any(
                all(abs(c.origin[i] - centre[i]) <= EPS for i in index) for c in local
            )
        ):
            canvas.mark(middle)  # the place is measured to the pattern's centre

        def between(j: int, k: int, name: str, text: str) -> None:
            """The step from the first copy to copy ``j``, along the face's axis ``k``."""
            if j >= len(local):
                return  # pragma: no cover - a pattern makes all its copies or none
            ax, other = index[k], index[1 - k]
            self.line(canvas, "u" if ax == canvas.u else "v", local[0].origin[ax], local[j].origin[ax],
                      (local[0].origin[other], local[j].origin[other]), text, f"place.pattern.{name}")  # fmt: skip

        PATTERN_VIEWS[pattern.kind].steps(pattern, face, local, middle, canvas, between)

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
        if VIEWS[self.item.kind].cut:
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
        spread = pattern is not None and PATTERN_VIEWS[pattern.kind].round
        lead = "the first at" if spread else "at"
        if pattern is not None and PATTERN_VIEWS[pattern.kind].equally_spaced:
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
        PATTERN_VIEWS[pattern.kind].words(self, face, values, counts)
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
                  for i in spec.items if not VIEWS[i.kind].drawable)  # fmt: skip
    drawable = [i for i in spec.items if VIEWS[i.kind].drawable]
    extent = layout.extent() if layout is not None else None
    if layout is None or extent is None:
        return Views((), words, tuple(i.id for i in drawable), None)
    lo, hi = extent
    size = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    scale = max(size) if max(size) > EPS else 1.0
    decimals = max(2, 4 - fs.decade(scale))
    canvases = [_Canvas(frame, scale / _SPAN_PX, decimals) for frame in _FRAMES]
    solids: list[_Solid] = [((i.item, i.index), *box) for item in drawable
                            if VIEWS[item.kind].hides
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
    up = _axis_of(copy.normal)
    if copy.lo is None or copy.hi is None or up is None:
        return []
    return VIEWS[item.kind].inside(item, copy, layout, up)


def _overall(canvases: Sequence[_Canvas], lo: Vec, hi: Vec, size: Vec) -> None:
    """The part's overall size along each axis, where no one item's dimension spans it already."""
    for k in range(3):
        canvas, along = canvases[_HOME[k][0]], _HOME[k][1]
        if canvas.spans_already(along, lo[k], hi[k]):
            continue
        across = canvas.v if along == "u" else canvas.u
        canvas.dimension("", (f"overall.{_AXES[k]}",), along, lo[k], hi[k], (lo[across], lo[across]),
                         f"{_mm(size[k])} overall")  # fmt: skip
