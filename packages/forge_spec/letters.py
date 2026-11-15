"""Letters as the placement solver reasons with them: where their ink is (docs/definitions/text.md; docs/V2-stage4.md, 7.1).

A line of text is set in the pinned font: each letter its glyph
(:mod:`forge_spec.glyphs`), scaled so the letter H is ``height`` tall
(:mod:`forge_spec.font`), one after another by advance width, with no
kerning. The line's box runs from the first letter's start to the last
letter's advance, and from the baseline to a capital's top; but ink reaches
past it (a j's tail below the line, an f's hook past its advance, an É's
accent above a capital). The ink's box is the least box round every
letter's curves, worked out exactly: each straight piece's ends, and each
quadratic piece's ends and its turning points along either axis.

This is the solver's own code: the judge has its own (rule R2).

>>> box = ink_box("H", 1493.0)  # an H as tall as the font draws it: its own glyph's box
>>> tuple(round(v, 6) for corner in box for v in corner)
(188.0, 0.0, 1526.0, 1493.0)
>>> ink_box("  ", 10.0) is None
True
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from functools import cache

from .font import ADVANCES, CAP_HEIGHT
from .glyphs import CONTOURS

__all__ = ["glyph_box", "ink_box", "pieces", "signed_area"]

Point = tuple[float, float]
#: A piece of a contour: from its start, round its control point (None for a straight piece), to its end.
Piece = tuple[Point, Point | None, Point]


def pieces(contour: Sequence[tuple[int, int, int]]) -> Iterator[Piece]:
    """A contour as its pieces in turn, closed (TrueType's curves).

    Points on the curve are joined straight, or round the one control point
    between them; between two control points in a row the curve passes
    midway; a contour of control points alone starts midway between its
    last and its first.

    >>> list(pieces([(0, 0, 1), (10, 0, 0), (10, 10, 1)]))
    [((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)), ((10.0, 10.0), None, (0.0, 0.0))]
    """
    points = [(float(x), float(y), bool(on)) for x, y, on in contour]
    if not points:
        return
    first = next((k for k, p in enumerate(points) if p[2]), None)
    if (
        first is None
    ):  # control points alone: start midway between the last and the first
        last, nxt = points[-1], points[0]
        start: Point = ((last[0] + nxt[0]) / 2, (last[1] + nxt[1]) / 2)
        run = points
    else:
        start = (points[first][0], points[first][1])
        run = points[first + 1 :] + points[:first]
    here, control = start, None
    for x, y, on in [*run, (start[0], start[1], True)]:
        if on:
            yield here, control, (x, y)
            here, control = (x, y), None
        elif control is None:
            control = (x, y)
        else:
            middle = ((control[0] + x) / 2, (control[1] + y) / 2)
            yield here, control, middle
            here, control = middle, (x, y)


def _extremes(piece: Piece) -> list[Point]:
    """A piece's ends, and a quadratic's turning points along either axis."""
    a, c, b = piece
    found = [a, b]
    if c is None:
        return found
    for k in (0, 1):
        bend = a[k] - 2 * c[k] + b[k]
        if bend != 0.0:
            t = (a[k] - c[k]) / bend
            if 0.0 < t < 1.0:
                u = 1.0 - t
                found.append(
                    (
                        u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
                        u * u * a[1] + 2 * u * t * c[1] + t * t * b[1],
                    )
                )
    return found


@cache
def glyph_box(letter: str) -> tuple[Point, Point] | None:
    """The least box round a letter's curves, in font units from its origin; None for a letter with no ink (a space)."""
    points = [
        p
        for contour in CONTOURS[letter]
        for piece in pieces(contour)
        for p in _extremes(piece)
    ]
    if not points:
        return None
    return (min(p[0] for p in points), min(p[1] for p in points)), (
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def signed_area(letter: str) -> float:
    """The letter's contours' signed areas added up, in square font units (Green's theorem: each piece's share, exactly).

    A straight piece's share is half the cross product of its ends; a
    quadratic's, a sixth of twice each leg's and once the chord's.
    """

    def cross(p: Point, q: Point) -> float:
        return p[0] * q[1] - p[1] * q[0]

    total = 0.0
    for contour in CONTOURS[letter]:
        for a, c, b in pieces(contour):
            if c is None:
                total += cross(a, b) / 2
            else:
                total += (2 * cross(a, c) + 2 * cross(c, b) + cross(a, b)) / 6
    return total


def ink_box(text: str, height: float) -> tuple[Point, Point] | None:
    """The least box round a line's ink, its capitals ``height`` tall: along the line from its first letter's start, up from its baseline.

    None when it has no ink at all. Letters the font lacks are the spec
    checks' to report: here they take no room.
    """
    scale = height / CAP_HEIGHT
    lo = hi = None
    advance = 0
    for letter in text:
        if letter not in ADVANCES:
            continue
        box = glyph_box(letter)
        if box is not None:
            (x0, y0), (x1, y1) = box
            corners = (
                ((advance + x0) * scale, y0 * scale),
                ((advance + x1) * scale, y1 * scale),
            )
            lo = (
                corners[0]
                if lo is None
                else (min(lo[0], corners[0][0]), min(lo[1], corners[0][1]))
            )
            hi = (
                corners[1]
                if hi is None
                else (max(hi[0], corners[1][0]), max(hi[1], corners[1][1]))
            )
        advance += ADVANCES[letter]
    return None if lo is None or hi is None else (lo, hi)
