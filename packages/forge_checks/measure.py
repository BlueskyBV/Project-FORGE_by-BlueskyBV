"""Measuring a built part: its points near a surface the spec asks for, and fits with a worst-case uncertainty.

Every check kind (:mod:`forge_checks.kinds`) measures through a
:class:`Probe`: the view's coverage (every point of its surface within the
probe's radius of one, each with its outward normal and how far the view
may be from the true surface there, ``d``) and the spec's own shape (the
oracle), which says where to look.

**Windows.** A check looks for the built surface near the spec's: the
coverage points within ``width`` of the spec surface, facing its way
(within :data:`FACING`), whose foot on the spec surface is where the spec
says that surface is (the oracle has it ON). So a pocket's floor isn't
taken for the face it is cut into, a rounding's zone at a rim isn't taken
for the hole's wall, and a surface built in the wrong place by more than
``width`` isn't found: the spec's surface is missing, and the check fails.
A built point farther from the surface than its deflection that lies where
another surface of the spec's may be is that surface's, and is left out: a
wide window (an angle's, round a big rod) may reach a neighbour facing the
same way, whose points would pull the fit off by how far apart the two are,
which no bound from the points' deflections shows. A point off the surface
and near no other is kept: it may be this surface, built where it shouldn't
be, and is measured.

**Fits, and how far they can be off.** A fit is least squares, from a
starting guess at the spec's own values. Each point may be off the true
surface by up to its ``d`` along the normal, and a fitted value moves, to
first order, by the sum of each point's error times that point's weight in
the fit (a row of the fit's pseudo-inverse): so it is off by at most the sum
of ``|weight| d``. That is the measurement's uncertainty ``u``: the
fitted value of the mesh's own surface plus or minus ``u`` holds the true
surface's. On a full circle it is ``d``; on a short arc much more (the
centre is ill-fixed), which is how an arc's angle enters (about 1.8 times
for half a circle, 9 for a quarter, 37 for an eighth). It is taken to
second order (:class:`Errors`): the residuals bend as the fit moves, by
more the more it may move, so a short arc's first-order bound falls short
of its worst case (a quarter circle's by 4%, an eighth's by 23%); their
second derivatives over how far the fit may be off are added, fed back
until the bound holds itself, and a fit whose second-order part would
outgrow its first can't fix its unknowns. The polygon's own second-order
miss, ``d²/r`` for a circle, is added too, and a fit that can't fix its
unknowns (too few points, all on a line, too short an arc for its points'
deflection) measures nothing. A value made of several unknowns (an arc's
edge: its centre's place plus its radius) is bounded as one, from its own
weight on each point, not as the sum of each unknown's bound: on a short
arc the centre and the radius move together, and the edge between them
is known far better than either.

>>> import numpy as np
>>> angles = np.linspace(0, 2 * np.pi, 40, endpoint=False)
>>> ring = np.stack([3 * np.cos(angles) + 1, 3 * np.sin(angles) - 2], axis=1)
>>> fit = fit_circle(ring, np.full(40, 0.01), (0.0, 0.0), 2.5)
>>> round(fit.radius, 12), [round(c, 12) for c in fit.centre], round(fit.u_radius, 3)
(3.0, [1.0, -2.0], 0.01)
"""

from __future__ import annotations

import contextlib
import functools
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import numpy as np
from forge_units import Interval
from numpy.typing import NDArray

from .classes import Verdict
from .oracle import Oracle
from .view import Box, Resolution, Side, ViewProxy, covered

__all__ = [
    "FACING",
    "CircleFit",
    "ConeFit",
    "Errors",
    "Measurement",
    "Probe",
    "SphereFit",
    "Window",
    "basis",
    "fit_circle",
    "fit_cone",
    "fit_offset",
    "fit_sphere",
]

Array = NDArray[np.float64]
Vec = tuple[float, float, float]

#: A built point faces the spec surface's way when the angle between their normals is at most this (degrees).
FACING = 30.0
#: Fewer points than this on a surface: too little of it is built to measure.
FEWEST = 3
#: Gauss-Newton stops when a step moves nothing more than this, relative to the size fitted.
_STEP = 1e-14
#: How many built points a window needs at most: a fit's bound is as sound on these as on all.
ENOUGH = 4000
#: A fit's normal matrix whose condition number exceeds this can't fix its unknowns.
_CONDITION = 1e12
#: A measurement too uncertain for its tolerance is taken again this many times finer where it looked.
FINER = 4.0
#: But never finer than this (mm),
FINEST = 0.005
#: nor over more than this many of its radius's squares of surface (bounds the memory a finer probe takes),
MOST = 5e5
#: nor where the faces it meets, each covered whole, would come to more points than this.
MOST_POINTS = 2_000_000
#: How much farther from a spec surface than its deflection a built point may be and still be taken for that
#: surface's without asking whether another is nearer (mm): a hair over OpenCascade's own confusion.
OWN = 1e-5


@dataclass(frozen=True)
class Measurement:
    """What a check measured: the value and how far it may be off, from how many built points, and why.

    With no value, ``missing`` says whether the spec's surface isn't built
    (the check fails) or is, but can't be measured (it is inconclusive). A
    kind with no tolerance (a count, a choice, a cut right through) gives its
    own ``verdict``.
    """

    value: Interval | None
    found: int
    reason: str
    missing: bool = True
    verdict: Verdict | None = None

    @staticmethod
    def of(value: float, uncertainty: float, found: int, reason: str) -> Measurement:
        return Measurement(
            Interval(value - uncertainty, value + uncertainty), found, reason
        )

    def with_verdict(self, verdict: Verdict) -> Measurement:
        return Measurement(self.value, self.found, self.reason, self.missing, verdict)


@dataclass(frozen=True, eq=False)
class Window:
    """The built points found near a spec surface: where they are, their normals, and how far each may be off."""

    points: Array
    normals: Array
    deflection: Array

    def __len__(self) -> int:
        return len(self.points)


def _line_box(a: Array, b: Array, reach: float) -> Box:
    """The box round the segment from ``a`` to ``b``, grown by ``reach`` (a little more, for rounding)."""
    grow = reach + 1e-9 * (1.0 + float(np.abs(np.concatenate([a, b])).max()))
    return Box(_t3(np.minimum(a, b) - grow), _t3(np.maximum(a, b) + grow))


def _within_arc(angle: Array, arc: tuple[float, float]) -> NDArray[np.bool_]:
    """Whether each angle lies on the arc from ``arc[0]`` anticlockwise to ``arc[1]``."""
    start, end = arc
    sweep = (end - start) % (2 * math.pi) or 2 * math.pi
    return np.asarray(np.mod(angle - start, 2 * math.pi) <= sweep)


def basis(axis: Vec | Array) -> tuple[Array, Array, Array]:
    """A unit ``axis``, and two unit directions square to it and to each other (right-handed)."""
    w = _unit(axis)
    helper = [1.0, 0.0, 0.0] if abs(w[0]) < 0.9 else [0.0, 1.0, 0.0]
    e1 = _unit(np.asarray(np.cross(w, helper), dtype=np.float64))
    e2 = np.asarray(np.cross(w, e1), dtype=np.float64)
    return w, e1, e2


def _t3(a: Array) -> tuple[float, float, float]:
    return (float(a[0]), float(a[1]), float(a[2]))


def _unit(v: Vec | Array) -> Array:
    a = np.asarray(v, dtype=np.float64)
    return np.asarray(a / float(np.linalg.norm(a)))


class Probe:
    """A built part as the checks measure it: the view's coverage at ``radius`` (or at a :class:`~.view.Resolution`: a radius everywhere, finer in its finer boxes), and the spec's shape to window it.

    ``within``: only where the surface meets these boxes, each at the
    radius there (a finer probe of the places one measurement looked,
    :meth:`finer`).
    """

    def __init__(
        self,
        view: ViewProxy,
        part: Oracle,
        radius: float | Resolution,
        within: Sequence[Box] | None = None,
    ) -> None:
        resolution = (
            radius if isinstance(radius, Resolution) else Resolution(float(radius))
        )
        covers = (
            [covered(view, resolution)]
            if within is None
            else [view.coverage(resolution.within(box), box) for box in within]
        )
        self.view = view
        self.part = part
        self.resolution = resolution
        #: The coarsest of its coverages' radii.
        self.radius = max((c.radius for c in covers), default=resolution.radius)
        self.points = np.concatenate([c.points for c in covers] or [np.zeros((0, 3))])
        self.normals = np.concatenate([c.normals for c in covers] or [np.zeros((0, 3))])
        self.deflection = np.concatenate([c.tolerance for c in covers] or [np.zeros(0)])
        #: The face or triangle each point is on.
        self.patch = np.concatenate(
            [c.patch for c in covers] or [np.zeros(0, dtype=np.int64)]
        )
        self._facing = math.cos(math.radians(FACING))
        self._watching: list[list[Box]] = []

    @functools.cached_property
    def _along(self) -> tuple[tuple[NDArray[np.int64], Array], ...]:
        """For each frame axis, the built points' rows in order along it, and their places along it in that order."""
        found = []
        for k in range(3):
            order = np.argsort(self.points[:, k], kind="stable")
            found.append((order, self.points[order, k]))
        return tuple(found)

    def _near(self, lo: Array, hi: Array) -> NDArray[np.int64]:
        """The rows of the built points in the box from ``lo`` to ``hi``, ascending: all a window whose surface lies in it can take.

        Read off the axis the box is thinnest across the points along, so a
        window looks at the points near its surface, not all of them, and
        takes the same ones in the same order.
        """
        spans = []
        for k, (_, along) in enumerate(self._along):
            a = int(np.searchsorted(along, lo[k], "left"))
            b = int(np.searchsorted(along, hi[k], "right"))
            spans.append((b - a, k, a, b))
        _, k, a, b = min(spans)
        rows = self._along[k][0][a:b]
        p = self.points[rows]
        inside = np.all((p >= lo) & (p <= hi), axis=1)
        return np.sort(rows[inside])

    def _near_line(self, a: Array, b: Array, reach: float) -> NDArray[np.int64]:
        """:meth:`_near` the box round the segment from ``a`` to ``b``, grown by ``reach`` (a little more, for rounding)."""
        box = _line_box(a, b, reach)
        return self._near(np.asarray(box.lo), np.asarray(box.hi))

    @contextlib.contextmanager
    def watched(self) -> Iterator[list[Box]]:
        """Within it, the boxes round every window of built points taken, as they are taken."""
        boxes: list[Box] = []
        self._watching.append(boxes)
        try:
            yield boxes
        finally:
            self._watching.remove(boxes)

    def finer(self, boxes: Sequence[Box], factor: float = FINER) -> Probe | None:
        """A probe ``factor`` times finer, where these boxes are (each grown by this probe's radius there); None where it would be no finer, or would cover too much.

        A box whose finer radius would be under :data:`FINEST` is left out.
        A view may cover every face (or triangle) a box meets whole: so the
        faces the boxes meet, as many points as this probe has on them times
        the factor squared, are held to :data:`MOST_POINTS` too (a mutant's
        missing surface, looked for again finer on a block's broad face,
        would have covered all of it 4 times finer: 17 million points).
        """
        grown: list[Box] = []
        squares = 0.0
        for box in boxes:
            wide = box.grown(self.resolution.within(box))
            radius = self.resolution.within(wide) / factor
            if radius >= FINEST:
                grown.append(wide)
                squares += math.prod(sorted(wide.size)[1:]) / radius**2
        if not grown or squares > MOST:
            return None
        inside = np.zeros(len(self.points), dtype=bool)
        for box in grown:
            lo, hi = np.asarray(box.lo), np.asarray(box.hi)
            inside |= np.all((self.points >= lo) & (self.points <= hi), axis=1)
        met = np.isin(self.patch, np.unique(self.patch[inside]))
        if int(met.sum()) * factor * factor > MOST_POINTS:
            return None
        return Probe(self.view, self.part, self.resolution.scaled(factor), grown)

    def _window(
        self,
        rows: NDArray[np.int64],
        feet: Array,
        enough: int | None = ENOUGH,
        searched: Box | None = None,
    ) -> Window:
        """The rows whose feet the spec has on its surface: all of them, or ``enough`` spread over the surface.

        Which side of the spec a foot is costs the most of a measurement, and
        a fit's worst-case bound is as sound on a spread sample of the points
        as on all of them. So the candidates are taken in an order spread
        over the surface (shuffled by a fixed seed, so every run measures the
        same points), a batch at a time, until ``enough`` of them are on the
        spec's surface or none are left: a surface only a few of whose
        candidates are on it is never missed for want of looking.
        """
        if not len(rows):
            empty = Window(self.points[rows], self.normals[rows], self.deflection[rows])
            return self._noted(empty, searched)
        return self._noted(self._taken(rows, feet, enough), searched)

    def _noted(self, window: Window, searched: Box | None = None) -> Window:
        """The window, its box noted for every measurement watching (:meth:`watched`); an empty one's, the box it was ``searched`` for in, where given (looked at again finer, a sliver the coverage passed over is found: generated part 2010)."""
        if not self._watching:
            return window
        if len(window):
            box = Box(_t3(window.points.min(axis=0)), _t3(window.points.max(axis=0)))
        elif searched is not None:
            box = searched
        else:
            return window
        for boxes in self._watching:
            boxes.append(box)
        return window

    def _taken(
        self, rows: NDArray[np.int64], feet: Array, enough: int | None
    ) -> Window:
        """The rows whose feet are on the spec's surface (see :meth:`_window`), and that are its (:meth:`_owned`)."""
        if enough is None or len(rows) <= enough:
            on = self.part.classify(feet) == Side.ON
            kept, kept_feet = rows[on], feet[on]
        else:
            order = np.random.default_rng(len(rows)).permutation(len(rows))
            found: list[NDArray[np.int64]] = []
            have = 0
            for start in range(0, len(order), enough):
                batch = order[start : start + enough]
                on = self.part.classify(feet[batch]) == Side.ON
                found.append(batch[on])
                have += int(on.sum())
                if have >= enough:
                    break
            taken = np.sort(np.concatenate(found))
            kept, kept_feet = rows[taken], feet[taken]
        kept = kept[self._owned(kept, kept_feet)]
        return Window(self.points[kept], self.normals[kept], self.deflection[kept])

    def _owned(self, rows: NDArray[np.int64], feet: Array) -> NDArray[np.bool_]:
        """Which of these built points are the surface's whose feet they have: those within their deflection (and :data:`OWN`) of it, and those farther that no other place the spec's surface may be is as near.

        A built point on another surface of the spec's, near this one and
        facing its way, is that surface's: taken for this one's, it would pull
        a fit off by how far apart they are, and the fit's bound, from the
        points' deflections alone, would not show it (generated part 3767: a
        slot's wall 3 mm from a bore, within an angle's wide window round it,
        put the bore's fitted axis 0.86 mm off, held to 1e-5). A point off
        this surface and near no other may be this one's, built where it
        shouldn't be: it is kept, and measured.
        """
        reach = self.deflection[rows] + OWN
        gap = np.linalg.norm(self.points[rows] - feet, axis=1)
        far = np.flatnonzero(gap > reach)
        owned = np.ones(len(rows), dtype=bool)
        if len(far):
            owned[far] = ~self.part.witness(self.points[rows[far]], reach[far])
        return owned

    def round(
        self,
        centre: Vec,
        axis: Vec,
        radius: float,
        start: float,
        end: float,
        *,
        inside: bool,
        width: float,
    ) -> Window:
        """The built points near a round surface: ``radius`` about the line through ``centre`` along ``axis``, from ``start`` to ``end`` along it.

        ``inside``: the material is outside the surface (a bore), so it faces
        the axis; else it faces away. A point counts within ``width`` of the
        surface, between ``start`` and ``end``, and off the axis.
        """
        return self.turned(
            centre, axis, (radius, radius), (start, end), inside=inside, width=width
        )

    def turned(
        self,
        centre: Vec,
        axis: Vec,
        radii: tuple[float, float],
        ends: tuple[float, float],
        *,
        inside: bool,
        width: float,
    ) -> Window:
        """The built points near a cone (or a cylinder): about the line through ``centre`` along ``axis``, from radius ``radii[0]`` at ``ends[0]`` along it to ``radii[1]`` at ``ends[1]``.

        Within ``width`` of the surface (square to it), between its ends, off
        the axis, facing its way (``inside``: the material is outside it).
        """
        w = _unit(axis)
        c = np.asarray(centre, dtype=np.float64)
        (r0, r1), (s0, s1) = radii, ends
        slope = (r1 - r0) / (s1 - s0) if s1 > s0 else 0.0
        k = 1.0 / math.sqrt(1.0 + slope * slope)
        # Within width of the surface square to it: within width / k of its radius there, across the axis.
        searched = _line_box(c + s0 * w, c + s1 * w, max(r0, r1) + width / k)
        near_rows = self._near(np.asarray(searched.lo), np.asarray(searched.hi))
        d = self.points[near_rows] - c
        along = d @ w
        radial = d - along[:, None] * w
        rho = np.sqrt(np.einsum("ij,ij->i", radial, radial))
        gap = (rho - (r0 + slope * (along - s0))) * k
        near = (np.abs(gap) <= width) & (along >= s0) & (along <= s1) & (rho > 0)
        rows = np.flatnonzero(near)
        out = radial[rows] / rho[rows, None]
        normal = (out - slope * w) * k
        facing = np.einsum(
            "ij,ij->i", self.normals[near_rows[rows]], -normal if inside else normal
        )
        keep = facing >= self._facing
        rows, out, normal = rows[keep], out[keep], normal[keep]
        feet = self.points[near_rows[rows]] - gap[rows, None] * normal
        return self._window(near_rows[rows], feet, searched=searched)

    def tube(
        self,
        centre: Vec,
        axis: Vec,
        big: float,
        radius: float,
        arc: tuple[float, float],
        *,
        inside: bool,
        width: float,
    ) -> Window:
        """The built points near a torus's tube: ``radius`` about the circle of radius ``big`` round the line through ``centre`` along ``axis``.

        Only over ``arc``, the angles (radians) round the tube from the way
        out from the axis towards ``axis``; within ``width`` of the surface,
        facing its way (``inside``: the material is outside the tube).
        """
        w = _unit(axis)
        c = np.asarray(centre, dtype=np.float64)
        searched = _line_box(c, c, abs(big) + radius + width)
        near_rows = self._near(np.asarray(searched.lo), np.asarray(searched.hi))
        d = self.points[near_rows] - c
        along = d @ w
        radial = d - along[:, None] * w
        rho = np.sqrt(np.einsum("ij,ij->i", radial, radial))
        u, v = rho - big, along
        r = np.sqrt(u * u + v * v)
        angle = np.arctan2(v, u)
        near = (np.abs(r - radius) <= width) & (rho > 0) & (r > 0)
        near &= _within_arc(angle, arc)
        rows = np.flatnonzero(near)
        out = radial[rows] / rho[rows, None]
        normal = (u[rows, None] * out + v[rows, None] * w) / r[rows, None]
        facing = np.einsum(
            "ij,ij->i", self.normals[near_rows[rows]], -normal if inside else normal
        )
        keep = facing >= self._facing
        rows, out, normal = rows[keep], out[keep], normal[keep]
        feet = c + big * out + radius * normal
        return self._window(near_rows[rows], feet, searched=searched)

    def ball(
        self, centre: Vec, radius: float, *, width: float, inside: bool = False
    ) -> Window:
        """The built points near a ball's surface: within ``width`` of it, facing out of it (``inside``: into it, a hollow's), where the spec has it."""
        c = np.asarray(centre, dtype=np.float64)
        searched = _line_box(c, c, radius + width)
        near_rows = self._near(np.asarray(searched.lo), np.asarray(searched.hi))
        d = self.points[near_rows] - c
        r = np.sqrt(np.einsum("ij,ij->i", d, d))
        rows = np.flatnonzero((np.abs(r - radius) <= width) & (r > 0))
        out = d[rows] / r[rows, None]
        way = -1.0 if inside else 1.0
        rows = rows[
            way * np.einsum("ij,ij->i", self.normals[near_rows[rows]], out)
            >= self._facing
        ]
        feet = c + radius * d[rows] / r[rows, None]
        return self._window(near_rows[rows], feet, searched=searched)

    def band(
        self,
        centre: Vec,
        axis: Vec,
        radii: tuple[float, float],
        ends: tuple[float, float],
    ) -> Window:
        """Every built point between two radii about the line through ``centre`` along ``axis``, between ``ends`` along it.

        No facing and no surface of the spec's to stand on: for a surface
        the spec bounds rather than gives (a thread's flanks), measured
        against its own definition by the kind that asks.
        """
        w = _unit(axis)
        c = np.asarray(centre, dtype=np.float64)
        searched = _line_box(c + ends[0] * w, c + ends[1] * w, max(radii))
        near_rows = self._near(np.asarray(searched.lo), np.asarray(searched.hi))
        d = self.points[near_rows] - c
        along = d @ w
        radial = d - along[:, None] * w
        rho = np.sqrt(np.einsum("ij,ij->i", radial, radial))
        rows = near_rows[
            np.flatnonzero(
                (rho >= radii[0])
                & (rho <= radii[1])
                & (along >= ends[0])
                & (along <= ends[1])
            )
        ]
        return self._noted(
            Window(self.points[rows], self.normals[rows], self.deflection[rows]),
            searched,
        )

    def flat(
        self,
        point: Vec,
        normal: Vec,
        *,
        width: float,
        reach: float = math.inf,
        box: tuple[Vec, float, float] | None = None,
    ) -> Window:
        """The built points near the plane through ``point`` facing ``normal``: within ``width`` of it, facing its way, and their feet within ``reach`` of ``point``, and within ``box`` (a rectangle round it: its first side's direction and the half sizes along it and along ``normal`` x it)."""
        n = _unit(normal)
        q = np.asarray(point, dtype=np.float64)
        # Within width of the plane, and its foot within reach of the point or in the rectangle: in a box round it.
        grow = np.full(3, reach + width)
        if box is not None:
            first = _unit(box[0])
            second = np.asarray(np.cross(n, first), dtype=np.float64)
            grow = np.minimum(
                grow,
                box[1] * np.abs(first) + box[2] * np.abs(second) + width * np.abs(n),
            )
        searched = (
            Box(_t3(q - grow - 1e-9), _t3(q + grow + 1e-9))
            if np.all(np.isfinite(grow))
            else None
        )
        near_rows = (
            self._near(np.asarray(searched.lo), np.asarray(searched.hi))
            if searched is not None
            else np.arange(len(self.points))
        )
        offset_all = (self.points[near_rows] - q) @ n
        local = np.flatnonzero(np.abs(offset_all) <= width)
        rows = near_rows[local]
        keep = self.normals[rows] @ n >= self._facing
        rows, offset = rows[keep], offset_all[local[keep]]
        feet = self.points[rows] - offset[:, None] * n
        if math.isfinite(reach):
            gap = feet - q
            near = np.einsum("ij,ij->i", gap, gap) <= reach * reach
            rows, feet = rows[near], feet[near]
        if box is not None:
            first = _unit(box[0])
            second = np.asarray(np.cross(n, first), dtype=np.float64)
            gap = feet - q
            # Strictly within: a point on the rectangle's edge may be another face's, beside it in its plane (a
            # host's side a standing item's is flush with), and says nothing of this one.
            near = (np.abs(gap @ first) < box[1] - _WITHIN) & (
                np.abs(gap @ second) < box[2] - _WITHIN
            )
            rows, feet = rows[near], feet[near]
        return self._window(rows, feet, searched=searched)


#: How far inside a plane's rectangle a built point's foot must be to be its (mm).
_WITHIN = 1e-6


def fit_offset(window: Window, point: Vec, normal: Vec) -> tuple[float, float]:
    """How far the window's points lie from the plane through ``point`` along ``normal``, on average, and how far that may be off."""
    n = _unit(normal)
    offset = (window.points - np.asarray(point, dtype=np.float64)) @ n
    return float(offset.mean()), float(window.deflection.mean())


@dataclass(frozen=True, eq=False)
class Errors:
    """How far a fit's unknowns may be off, together, to second order.

    ``spread``: each unknown's weight on each point's error times how far
    that point may be off (unknowns by points); ``bend``: for each unknown,
    the sum over the points of its weight on each times that point's second
    derivatives (the residual's, by every two unknowns); ``frame`` and
    ``reach``: directions in the unknowns' space (rows) and how far the fit
    may be off along each; ``miss``: each unknown's share of the polygon's
    own second-order miss.

    The true surface is where every point's residual is its error ``e``;
    expanded about the fit, whose residuals its weights take to nothing,
    the fit is off by its weights times ``e``, less its weights times half
    the residuals' second derivatives taken over how far it is off. So a sum
    of the unknowns, each times a coefficient, is off by at most the sum of
    its own weights' sizes times the points' deflections (bounded as one: on
    a short arc the centre and the radius move together, and the edge
    between them is known far better than either), plus that half over the
    box the fit may be off within: a box that must hold itself, found by
    feeding it back from the first-order bounds (a quarter circle's
    first-order bound falls 4% short of its worst case, a 45° arc's 23%).
    """

    spread: Array
    bend: Array
    frame: Array
    reach: Array
    miss: Array

    @classmethod
    def of(
        cls,
        weights: Array,
        deflection: Array,
        second: Array,
        miss: Sequence[float],
    ) -> Errors | None:
        """From the fit's pseudo-inverse (unknowns by points), each point's deflection, each point's residual's second derivatives (points by unknowns by unknowns), and each unknown's share of the polygon's miss; None where the fit's second-order part would outgrow its first (its unknowns aren't fixed)."""
        d = np.asarray(deflection, dtype=np.float64)
        spread = weights * d[None, :]
        bend = np.einsum("kn,nij->kij", weights, second)
        # Along the directions the first-order errors spread most and least, which they do independently.
        _, vectors = np.linalg.eigh(spread @ spread.T)
        frame = np.ascontiguousarray(vectors.T)
        first = np.abs(frame @ spread).sum(axis=1)
        framed = np.abs(np.einsum("jk,kab,ca,db->jcd", frame, bend, frame, frame))
        reach = first
        for _ in range(_FED_BACK):
            fed = first + 0.5 * np.einsum("jab,a,b->j", framed, reach, reach)
            if float((fed - first).max(initial=0.0)) > float(first.max(initial=0.0)):
                return None
            moved = float(np.abs(fed - reach).max(initial=0.0))
            reach = fed
            if moved <= _SETTLED * float(fed.max(initial=0.0)):
                return cls(spread, bend, frame, reach, np.array(miss, dtype=float))
        return None

    def bound(self, coefficients: Sequence[float] | Array) -> float:
        """How far the sum of the unknowns times these coefficients may be off."""
        a = np.asarray(coefficients, dtype=np.float64)
        bent = self.frame @ np.einsum("k,kab->ab", a, self.bend) @ self.frame.T
        return float(
            np.abs(a @ self.spread).sum()
            + 0.5 * (self.reach @ np.abs(bent) @ self.reach)
            + np.abs(a) @ self.miss
        )


#: A fit's second-order bound is fed back at most this many times to hold itself,
_FED_BACK = 100
#: and holds it once a round moves it by no more than this, relative to it.
_SETTLED = 1e-12


def _round_second(e: Array, rho: Array, others: int) -> Array:
    """A distance from a centre's second derivatives by the centre's coordinates (``e``: the ways out to the points, ``rho``: how far): ``(I - e eᵀ) / rho``, then ``others`` unknowns it doesn't bend by."""
    n, k = e.shape
    second = np.zeros((n, k + others, k + others))
    across = np.eye(k)[None, :, :] - e[:, :, None] * e[:, None, :]
    second[:, :k, :k] = across / rho[:, None, None]
    return second


@dataclass(frozen=True)
class CircleFit:
    """A circle fitted to points in a plane: its centre and radius, how far each may be off, and the worst miss of a point (``errors``: how far a sum of them may be)."""

    centre: tuple[float, float]
    radius: float
    u_centre: tuple[float, float]
    u_radius: float
    worst: float
    errors: Errors = field(compare=False, repr=False)

    def uncertainty(self, x: float, y: float, r: float) -> float:
        """How far ``x`` times the centre's first coordinate, plus ``y`` times its second, plus ``r`` times the radius may be off."""
        return self.errors.bound((x, y, r))


def fit_circle(
    points: Array, deflection: Array, centre: tuple[float, float], radius: float
) -> CircleFit | None:
    """The circle nearest the points (least squares of their distances from it), from a guess; None if they can't fix one.

    Each point may be off by its ``deflection`` along the radius: the
    centre and radius are off by at most the sums of those times the
    points' weights in the fit, and ``d² / r`` more.
    """
    if len(points) < FEWEST:
        return None
    p = np.asarray(points, dtype=np.float64)
    c = np.array(centre, dtype=np.float64)
    r = float(radius)
    scale = max(r, float(np.abs(p - c).max()), 1e-300)
    for _ in range(100):
        d = p - c
        rho = np.sqrt(np.einsum("ij,ij->i", d, d))
        if np.any(rho == 0):
            return None
        e = d / rho[:, None]
        residual = rho - r
        jacobian = np.column_stack([-e, -np.ones(len(p))])
        step = _solve(jacobian, -residual)
        if step is None:
            return None
        c = c + step[:2]
        r = r + float(step[2])
        if float(np.abs(step).max()) <= _STEP * scale:
            break
    else:
        return None
    if r <= 0:
        return None
    d = p - c
    rho = np.sqrt(np.einsum("ij,ij->i", d, d))
    jacobian = np.column_stack([-(d / rho[:, None]), -np.ones(len(p))])
    weights = _pseudo_inverse(jacobian)
    if weights is None:
        return None
    dmax = float(deflection.max(initial=0.0))
    miss = dmax * dmax / r
    errors = Errors.of(
        weights, deflection, _round_second(d / rho[:, None], rho, 1), (miss,) * 3
    )
    if errors is None:
        return None
    u = [errors.bound(unit) for unit in np.eye(3)]
    return CircleFit(
        (float(c[0]), float(c[1])),
        r,
        (u[0], u[1]),
        u[2],
        float(np.abs(rho - r).max()),
        errors,
    )


def _solve(jacobian: Array, residual: Array) -> Array | None:
    """The least-squares step, or None if the normal equations can't be solved well."""
    normal = jacobian.T @ jacobian
    if not np.all(np.isfinite(normal)) or np.linalg.cond(normal) > _CONDITION:
        return None
    return np.asarray(np.linalg.solve(normal, jacobian.T @ residual))


def _pseudo_inverse(jacobian: Array) -> Array | None:
    """(JᵀJ)⁻¹Jᵀ: each unknown's weight on each point's error; None if ill-fixed."""
    normal = jacobian.T @ jacobian
    if not np.all(np.isfinite(normal)) or np.linalg.cond(normal) > _CONDITION:
        return None
    return np.asarray(np.linalg.solve(normal, jacobian.T))


@dataclass(frozen=True)
class ConeFit:
    """A cone fitted about an axis: radius ``a + b (s - at)`` at ``s`` along it, its axis moved by ``centre`` across; each value's uncertainty.

    ``a`` is the radius at ``at``: where the points are, a cone's radius is
    known to about its points' deflection, and its uncertainty grows from
    there by about ``u_b`` a millimetre (:meth:`radius_at` bounds the two as
    one); a radius fitted at a height far from them (the body's far end)
    would be off by millimetres, and the slope with it.
    """

    centre: tuple[float, float]
    a: float
    b: float
    u_centre: tuple[float, float]
    u_a: float
    u_b: float
    worst: float
    errors: Errors = field(compare=False, repr=False)
    at: float = 0.0

    def radius_at(self, s: float) -> tuple[float, float]:
        """The radius at ``s`` along the axis, and how far it may be off."""
        return self.a + self.b * (s - self.at), self.uncertainty(0.0, 0.0, 1.0, s)

    def uncertainty(self, x: float, y: float, r: float, s: float) -> float:
        """How far ``x`` times the axis's place along the first way across, plus ``y`` times along the second, plus ``r`` times the radius at ``s`` along it, may be off."""
        return self.errors.bound((x, y, r, r * (s - self.at)))


def fit_cone(
    across: Array, along: Array, deflection: Array, a: float, b: float
) -> ConeFit | None:
    """The cone nearest the points (least squares of their distances from it, square to its surface), from a guess.

    ``across`` are the points' coordinates across the axis (n, 2), ``along``
    along it; the cone's radius is ``a + b s`` about a centre fitted across.
    Each point may be off by its ``deflection`` square to the surface.
    """
    if len(across) < FEWEST + 1:
        return None
    q = np.asarray(across, dtype=np.float64)
    s = np.asarray(along, dtype=np.float64)
    theta = np.array([0.0, 0.0, a, b], dtype=np.float64)
    scale = max(abs(a) + abs(b) * float(np.abs(s).max()), 1e-300)

    def model(theta: Array) -> tuple[Array, Array]:
        c, a_, b_ = theta[:2], theta[2], theta[3]
        d = q - c
        rho = np.sqrt(np.einsum("ij,ij->i", d, d))
        k = 1.0 / math.sqrt(1.0 + b_ * b_)
        gap = rho - a_ - b_ * s
        e = d / np.where(rho > 0, rho, 1.0)[:, None]
        jacobian = np.column_stack(
            [-e * k, -np.full(len(q), k), -s * k - gap * b_ * k**3]
        )
        return gap * k, jacobian

    for _ in range(100):
        residual, jacobian = model(theta)
        step = _solve(jacobian, -residual)
        if step is None:
            return None
        theta = theta + step
        if float(np.abs(step).max()) <= _STEP * scale:
            break
    else:
        return None
    residual, jacobian = model(theta)
    weights = _pseudo_inverse(jacobian)
    if weights is None:
        return None
    dmax = float(deflection.max(initial=0.0))
    # The polygon's second-order miss is greatest where the cone is narrowest among the points.
    narrowest = float(np.abs(theta[2] + theta[3] * s).min())
    miss = dmax * dmax / max(narrowest, 1e-300)
    errors = Errors.of(
        weights, deflection, _cone_second(q, s, theta), (miss, miss, miss, 0.0)
    )
    if errors is None:
        return None
    u = [errors.bound(unit) for unit in np.eye(4)]
    return ConeFit(
        (float(theta[0]), float(theta[1])),
        float(theta[2]),
        float(theta[3]),
        (u[0], u[1]),
        u[2],
        u[3],
        float(np.abs(residual).max()),
        errors,
    )


def _cone_second(across: Array, along: Array, theta: Array) -> Array:
    """A cone's residuals' second derivatives (points by unknowns by unknowns: the centre's two coordinates, ``a`` and ``b``) at ``theta``.

    The residual is ``k (rho - a - b s)``, ``k = 1 / sqrt(1 + b²)`` making it
    square to the surface: the distance from the axis bends it as a
    circle's does, times ``k``; ``k`` bends it by ``b`` with the rest.
    """
    c, a, b = theta[:2], float(theta[2]), float(theta[3])
    d = across - c
    rho = np.sqrt(np.einsum("ij,ij->i", d, d))
    e = d / np.where(rho > 0, rho, 1.0)[:, None]
    gap = rho - a - b * along
    k = 1.0 / math.sqrt(1.0 + b * b)
    dk, ddk = -b * k**3, (2 * b * b - 1) * k**5
    second = k * _round_second(e, np.where(rho > 0, rho, np.inf), 2)
    second[:, :2, 3] = second[:, 3, :2] = -dk * e
    second[:, 2, 3] = second[:, 3, 2] = -dk
    second[:, 3, 3] = ddk * gap - 2 * dk * along
    return second


@dataclass(frozen=True)
class SphereFit:
    """A sphere fitted to points: its centre and radius, how far each may be off, and the worst miss of a point (``errors``: how far a sum of them may be)."""

    centre: tuple[float, float, float]
    radius: float
    u_centre: tuple[float, float, float]
    u_radius: float
    worst: float
    errors: Errors = field(compare=False, repr=False)

    def uncertainty(self, along: Sequence[float], r: float) -> float:
        """How far the centre's place along ``along`` (its coordinates times that vector's), plus ``r`` times the radius, may be off."""
        return self.errors.bound((*along, r))


def fit_sphere(
    points: Array, deflection: Array, centre: Vec, radius: float
) -> SphereFit | None:
    """The sphere nearest the points (least squares of their distances from it), from a guess; None if they can't fix one."""
    if len(points) < FEWEST + 1:
        return None
    p = np.asarray(points, dtype=np.float64)
    c = np.array(centre, dtype=np.float64)
    r = float(radius)
    scale = max(r, float(np.abs(p - c).max()), 1e-300)
    for _ in range(100):
        d = p - c
        rho = np.sqrt(np.einsum("ij,ij->i", d, d))
        if np.any(rho == 0):
            return None
        jacobian = np.column_stack([-(d / rho[:, None]), -np.ones(len(p))])
        step = _solve(jacobian, -(rho - r))
        if step is None:
            return None
        c = c + step[:3]
        r = r + float(step[3])
        if float(np.abs(step).max()) <= _STEP * scale:
            break
    else:
        return None
    if r <= 0:
        return None
    d = p - c
    rho = np.sqrt(np.einsum("ij,ij->i", d, d))
    weights = _pseudo_inverse(np.column_stack([-(d / rho[:, None]), -np.ones(len(p))]))
    if weights is None:
        return None
    dmax = float(deflection.max(initial=0.0))
    miss = dmax * dmax / r
    errors = Errors.of(
        weights, deflection, _round_second(d / rho[:, None], rho, 1), (miss,) * 4
    )
    if errors is None:
        return None
    u = [errors.bound(unit) for unit in np.eye(4)]
    return SphereFit(
        (float(c[0]), float(c[1]), float(c[2])),
        r,
        (u[0], u[1], u[2]),
        u[3],
        float(np.abs(rho - r).max()),
        errors,
    )
