"""Surface extraction and mesh export.

A mesh is an *output* of Forge, never its representation. Principle: do not use a
mesh as the canonical form of an exact CAD part. Everything Forge asserts about a
design is measured from the implicit field or from the B-Rep, and the mesh exists
only so that a person can look at the result and a printer can consume it.

Extraction uses naive surface nets rather than marching cubes. The choice is
deliberate: surface nets place one vertex per boundary cell, positioned at the
estimated surface crossing, and stitch neighbouring vertices into quads. That
gives a closed, manifold, well-shaped mesh in a fraction of the code of a
marching-cubes edge table, and -- because the vertex position comes from the
distance field rather than from linear interpolation along an edge -- it renders
curved surfaces more faithfully at the same grid resolution.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .sdf import SDF, GeometryError

Array = np.ndarray


@dataclass(frozen=True, slots=True)
class TriangleMesh:
    """An indexed triangle mesh in millimetres."""

    vertices: Array  # (V, 3)
    faces: Array  # (F, 3) int

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def face_count(self) -> int:
        return int(self.faces.shape[0])

    def face_normals(self) -> Array:
        a = self.vertices[self.faces[:, 0]]
        b = self.vertices[self.faces[:, 1]]
        c = self.vertices[self.faces[:, 2]]
        normals = np.cross(b - a, c - a)
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        lengths[lengths < 1e-15] = 1.0
        return normals / lengths

    def surface_area(self) -> float:
        a = self.vertices[self.faces[:, 0]]
        b = self.vertices[self.faces[:, 1]]
        c = self.vertices[self.faces[:, 2]]
        return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())

    def signed_volume(self) -> float:
        """Volume by the divergence theorem.

        Used only as a cross-check against the rigorous octree measurement. If
        the two disagree by more than the octree's own stated uncertainty, one of
        them is wrong and Forge wants that surfaced rather than averaged.
        """
        a = self.vertices[self.faces[:, 0]]
        b = self.vertices[self.faces[:, 1]]
        c = self.vertices[self.faces[:, 2]]
        return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)

    def pieces(self) -> list[tuple[float, Array]]:
        """Each separate piece of material: its volume and its vertices,
        largest first. Hollows (closed surfaces of the opposite sign) are left
        out, as in :meth:`piece_volumes`."""
        return self.pieces_and_hollows()[0]

    def hollows(self) -> list[tuple[float, Array]]:
        """Each pocket of air sealed inside the part: its volume and the
        vertices of the closed surface round it, largest first.

        A closed surface connected to nothing else whose volume has the
        opposite sign to the part's is the inside of a void: air the part
        closes in on every side, with no way out."""
        return self.pieces_and_hollows()[1]

    def pieces_and_hollows(
        self,
    ) -> tuple[list[tuple[float, Array]], list[tuple[float, Array]]]:
        """:meth:`pieces` and :meth:`hollows`, from one pass over the
        surface."""
        faces = self.faces
        if faces.shape[0] == 0:
            return [], []
        label = self._piece_labels()
        a = self.vertices[faces[:, 0]]
        b = self.vertices[faces[:, 1]]
        c = self.vertices[faces[:, 2]]
        each = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
        roots, piece = np.unique(label[faces[:, 0]], return_inverse=True)
        volumes = np.bincount(piece, weights=each)
        sign = 1.0 if volumes.sum() >= 0 else -1.0
        material: list[tuple[float, Array]] = []
        air: list[tuple[float, Array]] = []
        for index, root in enumerate(roots):
            volume = float(volumes[index] * sign)
            if volume > 0:
                material.append((volume, self.vertices[label == root]))
            elif volume < 0:
                air.append((-volume, self.vertices[label == root]))
        return (sorted(material, key=lambda item: -item[0]),
                sorted(air, key=lambda item: -item[0]))

    def _piece_labels(self) -> Array:
        faces = self.faces
        label = np.arange(self.vertex_count)
        while True:
            before = label.copy()
            lowest = np.minimum(
                np.minimum(label[faces[:, 0]], label[faces[:, 1]]),
                label[faces[:, 2]],
            )
            for corner in range(3):
                np.minimum.at(label, faces[:, corner], lowest)
            while True:
                jumped = label[label]
                if np.array_equal(jumped, label):
                    break
                label = jumped
            if np.array_equal(label, before):
                break
        return label

    def piece_volumes(self) -> list[float]:
        """The material volume of each separate piece, largest first.

        A piece is a connected part of the surface. A closed surface round a
        void inside the part is connected to nothing else, but the volume it
        encloses has the opposite sign to the part's: it is a hollow, not a
        piece of material, and is left out.
        """
        faces = self.faces
        if faces.shape[0] == 0:
            return []
        label = np.arange(self.vertex_count)
        while True:
            before = label.copy()
            lowest = np.minimum(
                np.minimum(label[faces[:, 0]], label[faces[:, 1]]),
                label[faces[:, 2]],
            )
            for corner in range(3):
                np.minimum.at(label, faces[:, corner], lowest)
            while True:
                jumped = label[label]
                if np.array_equal(jumped, label):
                    break
                label = jumped
            if np.array_equal(label, before):
                break
        a = self.vertices[faces[:, 0]]
        b = self.vertices[faces[:, 1]]
        c = self.vertices[faces[:, 2]]
        each = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
        _, piece = np.unique(label[faces[:, 0]], return_inverse=True)
        volumes = np.bincount(piece, weights=each)
        sign = 1.0 if volumes.sum() >= 0 else -1.0
        return sorted((float(v * sign) for v in volumes if v * sign > 0),
                      reverse=True)

    def non_manifold_edges(self) -> Array:
        """The edges shared by more than two faces, as vertex index pairs."""
        edges = np.vstack([self.faces[:, [0, 1]], self.faces[:, [1, 2]],
                           self.faces[:, [2, 0]]])
        edges = np.sort(edges, axis=1)
        unique, counts = np.unique(edges, axis=0, return_counts=True)
        return unique[counts > 2]

    def bounding_box(self) -> tuple[Array, Array]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def is_watertight(self) -> tuple[bool, dict[str, int]]:
        """Every edge must be shared by exactly two faces.

        A mesh that fails this cannot be printed and usually indicates the
        extraction grid was too coarse for a thin feature -- which is itself
        worth reporting, so the check returns the counts rather than a bare
        boolean.
        """
        edges = np.vstack(
            [
                self.faces[:, [0, 1]],
                self.faces[:, [1, 2]],
                self.faces[:, [2, 0]],
            ]
        )
        edges = np.sort(edges, axis=1)
        unique, counts = np.unique(edges, axis=0, return_counts=True)
        boundary = int((counts == 1).sum())
        non_manifold = int((counts > 2).sum())
        stats = {
            "boundary_edges": boundary,
            "non_manifold_edges": non_manifold,
            "total_edges": int(counts.shape[0]),
        }
        on_each_other = self._edges_drawn_twice(unique)
        if on_each_other:
            stats["edges_drawn_twice"] = on_each_other
        return (boundary == 0 and non_manifold == 0
                and on_each_other == 0), stats

    def surfaces_on_each_other(self) -> int:
        """How many edges two separate surfaces of the mesh draw at one place.

        See :meth:`is_watertight`, which counts them as a defect."""
        if self.face_count == 0:
            return 0
        edges = np.sort(np.vstack([self.faces[:, [0, 1]],
                                   self.faces[:, [1, 2]],
                                   self.faces[:, [2, 0]]]), axis=1)
        return self._edges_drawn_twice(np.unique(edges, axis=0))

    def _edges_drawn_twice(self, edges: Array) -> int:
        """Of these edges -- each once, as vertex index pairs -- how many lie
        where another edge, between other vertices, lies too.

        Every edge can be shared by its two faces and still the mesh be no
        solid's surface: two sheets drawn on each other, each closed on its
        own, back to back -- a skin of no thickness. A hollow dome came back
        closed across its open side that way, 22,000 faces lying on 22,000
        others, and every edge was shared by exactly two faces of its own
        sheet. Surface nets give each cell its own vertex, inside that cell,
        so two vertices at one place are two cells' -- on either side of a
        sheet with nothing between its faces -- and never one solid's.
        """
        if edges.shape[0] == 0:
            return 0
        vertices = self.vertices
        span = float(np.max(np.ptp(vertices, axis=0))) if vertices.size else 0.0
        # Rounding apart, not geometry: a billionth of the part's size.
        quantum = max(span, 1e-9) * 1e-9
        rounded = np.round(vertices / quantum)
        # Two vertices at one place have one sum here, to the last bit; a
        # mesh with no such pair -- nearly every mesh -- is done in one sort.
        sums = np.sort(rounded[:, 0] + rounded[:, 1] * 1.4142135623730951
                       + rounded[:, 2] * 3.141592653589793)
        if not np.any(sums[1:] == sums[:-1]):
            return 0
        where = rounded.astype(np.int64)
        _, place = np.unique(where, axis=0, return_inverse=True)
        place = np.asarray(place).reshape(-1)
        if int(place.max()) + 1 == vertices.shape[0]:
            return 0  # every vertex at a place of its own
        ends = np.sort(place[edges], axis=1)
        ends = ends[ends[:, 0] != ends[:, 1]]
        if ends.shape[0] == 0:
            return 0
        key = ends[:, 0].astype(np.int64) * (int(place.max()) + 1) + ends[:, 1]
        _, drawn = np.unique(key, return_counts=True)
        return int((drawn > 1).sum())


def floats_free(solid: SDF, vertices: Array, cell: float) -> bool:
    """Whether a small piece the mesh found is really apart from the rest.

    A piece the extraction grid splits off a thin feature is still joined to
    the part; a boss drawn 14 mm behind the shell it was meant to stand on is
    not, and both are under 1% of a calf shell's volume. So the piece's
    neighbourhood is sampled again, four times finer, and the material round
    the piece followed outward: material joined to the rest of the part runs
    out of the neighbourhood, a piece on its own does not.
    """
    vertices = np.asarray(vertices, dtype=float)
    if vertices.size == 0:
        return False
    for fineness in (4.0, 8.0):
        step = cell / fineness
        lo = vertices.min(axis=0) - 2.0 * cell
        hi = vertices.max(axis=0) + 2.0 * cell
        counts = np.maximum(np.ceil((hi - lo) / step).astype(int) + 1, 3)
        if int(np.prod(counts)) > 3_000_000:
            return False  # too big to look at closely: not called floating
        axes = [np.linspace(lo[i], hi[i], counts[i]) for i in range(3)]
        grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
        at = grid.reshape(-1, 3)
        inside = (_material_only_where_material_is(
            solid, at, np.asarray(solid(at), dtype=float), step)
            <= 0.0).reshape(tuple(counts))
        # Seeds: material within half a coarse cell of the piece's surface.
        index = np.clip(np.round((vertices - lo) / step).astype(int), 0,
                        counts - 1)
        seed = np.zeros_like(inside)
        reach = max(1, int(round(fineness / 2)))
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                for dz in range(-reach, reach + 1):
                    j = np.clip(index + np.array([dx, dy, dz]), 0, counts - 1)
                    seed[j[:, 0], j[:, 1], j[:, 2]] = True
        reached = seed & inside
        if not reached.any():
            return False
        while True:
            grown = reached.copy()
            grown[1:] |= reached[:-1]
            grown[:-1] |= reached[1:]
            grown[:, 1:] |= reached[:, :-1]
            grown[:, :-1] |= reached[:, 1:]
            grown[:, :, 1:] |= reached[:, :, :-1]
            grown[:, :, :-1] |= reached[:, :, 1:]
            grown &= inside
            if np.array_equal(grown, reached):
                break
            reached = grown
        edge = (reached[0].any() or reached[-1].any() or reached[:, 0].any()
                or reached[:, -1].any() or reached[:, :, 0].any()
                or reached[:, :, -1].any())
        if edge:
            return False
    return True


def meets_itself_at(solid: SDF, points: Array, cell: float,
                    fineness: float = 8.0) -> Array:
    """For each point -- where surface nets drew an edge shared by four
    faces -- whether the solid really meets itself there.

    Four faces on one edge is drawn two ways. A solid that touches itself
    along an edge -- two blocks meeting at a corner line -- draws it on any
    grid. A valid solid met at a slant -- a coil's wire, a rod along
    (1, 2, 2) -- draws it where a cell face has the surface crossing all four
    of its edges, and which way to join them is the grid's guess. A coil
    spring, right in every figure, was held for 13 of these on every grid.

    So each is looked at again, `fineness` times finer, in a cube a cell
    across each way: the material there is split into its face-joined
    pieces, and the solid meets itself only where two different pieces
    touch -- along an edge or at a corner of the fine grid, and nowhere
    through a face. A sheet met at a slant is one piece however it is cut.
    """
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if points.size == 0:
        return np.zeros(0, dtype=bool)
    step = cell / fineness
    count = int(round(2.0 * fineness)) + 1
    offsets = (np.arange(count) - (count - 1) / 2.0) * step
    cube = np.stack(np.meshgrid(offsets, offsets, offsets, indexing="ij"),
                    axis=-1).reshape(-1, 3)
    samples = (points[:, None, :] + cube[None, :, :]).reshape(-1, 3)
    inside = (_material_only_where_material_is(
        solid, samples, np.asarray(solid(samples), dtype=float), step)
        <= 0.0).reshape(points.shape[0], count, count, count)
    big = np.iinfo(np.int64).max
    meets = np.zeros(points.shape[0], dtype=bool)
    diagonal = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                for dz in (-1, 0, 1)
                if abs(dx) + abs(dy) + abs(dz) >= 2]
    for index in range(points.shape[0]):
        solid_here = inside[index]
        labels = np.where(solid_here,
                          np.arange(solid_here.size).reshape(solid_here.shape),
                          big)
        while True:
            before = labels
            labels = labels.copy()
            for axis in range(3):
                for shift in (1, -1):
                    moved = np.roll(before, shift, axis=axis)
                    edge = [slice(None)] * 3
                    edge[axis] = 0 if shift == 1 else -1
                    moved[tuple(edge)] = big
                    labels = np.minimum(labels, moved)
            labels = np.where(solid_here, labels, big)
            if np.array_equal(labels, before):
                break
        if len(np.unique(labels[solid_here])) < 2:
            continue
        n = count
        for dx, dy, dz in diagonal:
            a = labels[max(0, -dx):n - max(0, dx), max(0, -dy):n - max(0, dy),
                       max(0, -dz):n - max(0, dz)]
            b = labels[max(0, dx):n - max(0, -dx), max(0, dy):n - max(0, -dy),
                       max(0, dz):n - max(0, -dz)]
            if np.any((a != big) & (b != big) & (a != b)):
                meets[index] = True
                break
    return meets


def extract_manifold_surface(
    solid: SDF, *, resolution: int = 96, padding: float = 0.02
) -> TriangleMesh:
    """The surface, on a grid that does not cut a feature ambiguously.

    Surface nets join one vertex per cell, and where a cell face has the
    surface crossing all four of its edges -- a hole's rim met at a slant,
    on a plate turned 20 or 45 degrees to the grid -- four quads share one
    edge, and the mesh is not manifold although the solid is. That is the
    grid's, not the part's: the same rim on a grid shifted by a fraction of
    a cell is cut cleanly. So the grid is shifted, a few ways, until the
    surface comes out closed and manifold; a solid that really is not --
    two bodies touching along an edge -- comes out that way on every grid,
    and the first is returned to be reported.
    """
    first, banded = _extracted(solid, resolution, padding, 0.0)
    if first.is_watertight()[0]:
        return first
    if banded:
        # Read on the fine band, round something thinner than a cell, and
        # not closed: the coarse grids as before, which draw a skin thinner
        # than a cell as no skin at all but may well close where a skin
        # half a millimetre thick, drawn, does not. The band is read once,
        # on the first grid only: it is dear on a part with many features.
        try:
            coarse, _ = _extracted(solid, resolution, padding, 0.0, band=False)
            if coarse.is_watertight()[0]:
                return coarse
        except GeometryError:
            pass
    for shift, extra in ((0.37, 0), (0.71, 0), (0.19, 0), (0.0, 7),
                         (0.53, 7)):
        try:
            mesh, _ = _extracted(solid, resolution + extra, padding, shift,
                                 band=False)
        except GeometryError:
            continue
        if mesh.is_watertight()[0]:
            return mesh
    # A feature about one cell across -- a 4 mm ring round a mounting hole,
    # on a 430 mm calf meshed in 3.9 mm cells -- is cut ambiguously on every
    # grid that coarse, however it is shifted. Finer grids, before the solid
    # is called what it is not; one that really touches along an edge is
    # still not manifold at any of them.
    for scale, shift in ((1.5, 0.0), (1.5, 0.37), (2.0, 0.0)):
        try:
            mesh, _ = _extracted(solid, int(resolution * scale), padding,
                                 shift, band=False)
        except GeometryError:
            continue
        if mesh.is_watertight()[0]:
            return mesh
    return first


def extract_surface(
    solid: SDF, *, resolution: int = 96, padding: float = 0.02,
    shift: float = 0.0,
) -> TriangleMesh:
    """Extract a triangle mesh of the solid's boundary by surface nets.

    ``resolution`` is the number of samples along the longest envelope axis;
    the other axes are sampled proportionally so cells stay near-cubic.
    ``shift`` moves the grid by that fraction of a cell (by different
    fractions on each axis), for :func:`extract_manifold_surface`.
    """
    return _extracted(solid, resolution, padding, shift)[0]


#: The cell a surface to print from is meshed in, in millimetres. A printed
#: hole is as round as its facets: an 8.2 mm bolt hole on a 287 mm rail,
#: meshed in the 3 mm cells that find the surface, came out of the STL
#: 7.3 mm across at its narrowest, and a 15 mm counterbore 13.5 -- the part
#: measured exactly right and could not take its own bolts. In half-millimetre
#: cells a hole that size is round to a hundredth of a millimetre, well inside
#: what a 0.4 mm nozzle lays down.
PRINT_CELL = 0.5


def extract_print_surface(
    solid: SDF, *, cell: float = PRINT_CELL, resolution: int = 96,
    padding: float = 0.02,
) -> TriangleMesh | None:
    """The surface to print from: meshed in ``cell`` mm cells, closed and
    manifold, or None when no grid gives one.

    The grid that finds the surface is the one :func:`extract_manifold_surface`
    uses; only the band of cells round the surface is sampled again, ``cell``
    fine, so a large part costs its surface, not its volume. A part whose band
    will not fit the budget at that fineness is meshed as finely as it fits.
    """
    nearly: TriangleMesh | None = None
    for shift in (0.0, 0.37, 0.71):
        try:
            mesh, _ = _extracted(solid, resolution, padding, shift, fine=cell)
        except GeometryError:
            continue
        closed, stats = mesh.is_watertight()
        if closed:
            return mesh
        if (nearly is None and stats["boundary_edges"] == 0
                and not stats.get("edges_drawn_twice")
                and stats["non_manifold_edges"] <= _SHARED_EDGES_LOOKED_AT):
            nearly = mesh
    if nearly is None:
        return None
    # Closed, with a few edges shared by four faces on every grid tried: a
    # 430 mm calf shell meshed in 600,000 faces had three. Surface nets draw
    # that where a slanted surface crosses all four edges of a cell face, on
    # a solid that is perfectly manifold -- or where the solid really meets
    # itself. Each is looked at closely, as the watertight gate does; a
    # surface whose shared edges are all the grid's guess is printed from.
    shared = nearly.non_manifold_edges()
    where = nearly.vertices[shared].mean(axis=1)
    facet = float(np.median(np.linalg.norm(
        nearly.vertices[nearly.faces[:, 1]]
        - nearly.vertices[nearly.faces[:, 0]], axis=1)))
    if meets_itself_at(solid, where, facet).any():
        return None
    return nearly


#: The most edges shared by four faces a surface to print from may have and
#: still be looked at closely, edge by edge.
_SHARED_EDGES_LOOKED_AT = 64


def surface_deviation(solid: SDF, mesh: TriangleMesh,
                      quantile: float = 1.0) -> float:
    """How far the mesh strays from the solid's surface, in millimetres,
    read at every facet's centre and every edge's middle -- where a flat
    facet cuts a curve shortest. ``quantile`` 1.0 is the largest, which is
    at a sharp edge: facets round an edge off by up to about half their
    size. 0.99 is how closely nearly all of the surface follows the design.
    """
    if mesh.face_count == 0:
        return float("inf")
    a = mesh.vertices[mesh.faces[:, 0]]
    b = mesh.vertices[mesh.faces[:, 1]]
    c = mesh.vertices[mesh.faces[:, 2]]
    points = np.vstack([(a + b + c) / 3.0, (a + b) / 2.0, (b + c) / 2.0,
                        (c + a) / 2.0])
    away = np.abs(_evaluate(solid, points))
    return float(np.quantile(away, quantile)) if quantile < 1.0 \
        else float(away.max())


def _extracted(
    solid: SDF, resolution: int, padding: float, shift: float,
    band: bool = True, fine: float | None = None,
) -> tuple[TriangleMesh, bool]:
    """The surface, and whether it was read on the fine band round it.

    ``fine``, when given, is the cell the surface is wanted in: the band
    round the surface is sampled that finely (or as finely as the band's
    budget allows), whatever the grid that found it -- see
    :func:`extract_print_surface`.
    """
    envelope = solid.envelope
    size = np.array(envelope.size, dtype=float)
    if not np.all(np.isfinite(size)) or np.any(size <= 0.0):
        raise GeometryError(
            "cannot mesh a solid with a degenerate or unbounded envelope",
            size=size.tolist(),
        )
    margin = float(size.max()) * padding
    lo = np.array(envelope.lo, dtype=float) - margin
    hi = np.array(envelope.hi, dtype=float) + margin
    span = hi - lo

    spacing = float(span.max()) / max(resolution, 8)
    # Never coarser than a third of the part's thinnest extent: a needle or
    # a thin sheet sampled with cells wider than itself has no boundary cell
    # at all, and a 200 mm rod 1 mm thick was reported as having no surface.
    # Bounded so the grid stays a few million points.
    thinnest = float(size.min())
    if spacing > thinnest / 3.0:
        floor = (float(np.prod(span)) / 4.0e6) ** (1.0 / 3.0)
        spacing = max(thinnest / 3.0, floor)
    if shift:
        nudge = np.array([shift, (shift * 1.618) % 1.0, (shift * 2.414) % 1.0])
        lo = lo - nudge * spacing
        span = hi - lo
    counts = np.maximum(np.ceil(span / spacing).astype(int) + 1, 4)

    axes = [np.linspace(lo[i], lo[i] + spacing * (counts[i] - 1), counts[i]) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    flat = grid.reshape(-1, 3)
    field = _material_only_where_material_is(
        solid, flat, np.asarray(solid(flat), dtype=float), spacing
    ).reshape(counts)

    # A wall, a web or a slot thinner than a cell can lie wholly between two
    # neighbouring samples, and the grid never sees it: a 1000 by 600 by 400
    # box with 3 mm walls, meshed in 9.5 mm cells, had no boundary cell at
    # all, and a perfectly good part "had no surface". Where the field says
    # the grid has stepped over something, the band of cells round the
    # surface is sampled again, finely enough to see it.
    thinnest_missed = (_the_thinnest_the_grid_misses(solid, lo, spacing, field)
                       if band else None)
    if fine is not None and fine < spacing:
        wanted = fine if thinnest_missed is None else min(fine, thinnest_missed)
        banded = _banded_surface(solid, lo, spacing, field, wanted, fit=True)
        if banded is not None:
            return banded, True
    elif thinnest_missed is not None:
        banded = _banded_surface(solid, lo, spacing, field, thinnest_missed)
        if banded is not None:
            return banded, True

    inside = field <= 0.0
    nx, ny, nz = counts

    # A cell is a boundary cell when its eight corners are not all on one side.
    corner = [
        inside[i : i + nx - 1, j : j + ny - 1, k : k + nz - 1]
        for i in (0, 1)
        for j in (0, 1)
        for k in (0, 1)
    ]
    any_inside = np.zeros_like(corner[0])
    all_inside = np.ones_like(corner[0])
    for block in corner:
        any_inside |= block
        all_inside &= block
    boundary = any_inside & ~all_inside

    if not np.any(boundary):
        raise GeometryError(
            "surface extraction found no boundary cells",
            hint="the solid may be empty, or smaller than one grid cell; "
            "increase the resolution",
            resolution=resolution,
        )

    cell_index = -np.ones((nx - 1, ny - 1, nz - 1), dtype=np.int64)
    cells = np.argwhere(boundary)
    cell_index[cells[:, 0], cells[:, 1], cells[:, 2]] = np.arange(cells.shape[0])

    # Place each vertex at the cell centre, then pull it onto the surface with
    # two Newton steps along the gradient. This is what gives surface nets their
    # accuracy on curved geometry.
    centres = lo + (cells + 0.5) * spacing
    for _ in range(2):
        value = solid(centres)
        gradient = solid.gradient(centres, step=spacing * 0.25)
        norm = np.linalg.norm(gradient, axis=1, keepdims=True)
        norm[norm < 1e-12] = 1.0
        centres = centres - gradient / norm * value[:, None]
    # Keep every vertex inside its own cell, so the mesh cannot self-intersect
    # when the field is noisy.
    cell_lo = lo + cells * spacing
    centres = np.clip(centres, cell_lo, cell_lo + spacing)

    faces: list[Array] = []
    for axis in range(3):
        faces.extend(_quads_along_axis(inside, cell_index, axis))

    if not faces:
        raise GeometryError("surface extraction produced no faces")

    quads = np.vstack(faces)
    triangles = np.vstack(
        [quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]]
    )
    return TriangleMesh(vertices=centres, faces=triangles), False


#: How many fine cells the band round the surface may hold, which is about
#: how many points it samples.
_BAND_BUDGET = 10_000_000
#: About how many faces a surface meshed for printing may have: some 40 MB
#: of STL.
_PRINT_FACES = 800_000
#: Points evaluated at a time, to keep the field's working memory bounded.
_CHUNK = 1_000_000


def _evaluate(solid: SDF, points: Array) -> Array:
    """The field at many points, a bounded batch at a time."""
    out = np.empty(points.shape[0], dtype=float)
    for start in range(0, points.shape[0], _CHUNK):
        out[start:start + _CHUNK] = np.asarray(
            solid(points[start:start + _CHUNK]), dtype=float).reshape(-1)
    return out


#: How near nought a sample's field has to be to lie on the surface: the
#: arithmetic's rounding, a billionth of a cell, not the size of anything.
_ON_THE_SURFACE = 1e-9
#: How far beside such a sample the field is read again, in cells.
_BESIDE = 1e-3
#: The 26 ways out of a point, to a cube round it.
_ROUND_A_POINT = np.array(
    [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
     for dz in (-1, 0, 1) if (dx, dy, dz) != (0, 0, 0)], dtype=float)


def _material_only_where_material_is(
    solid: SDF, points: Array, values: Array, step: float
) -> Array:
    """The field sampled at `points`, with every sample that lies exactly
    on the surface and has no material beside it read as air.

    A sample on the surface counts as material (`f <= 0`), which is right on
    a face: the material is just behind it. It is wrong where the field only
    touches nought and goes below it nowhere -- a cut whose face lies exactly
    on the part's own face, a hollow dome's cavity cut by the very plane
    that cuts the dome. There the field is nought across the whole opening
    and above it on either side: a skin of no thickness. When the grid's
    samples landed on that plane, each was counted as material, and the mesh
    drew the skin -- twice, back to back -- sealing the cavity; a slicer
    showed the dome closed across its open side.

    So a sample within rounding of nought is read again, a thousandth of a
    cell away in each of 26 directions. With material beside it -- below
    nought by more than rounding -- it is on a face, an edge or a corner of
    the part, and stays material; with none, it lies on a skin, a line or a
    point of no thickness, and is air. Two solids that touch face to face
    have material on both sides of the plane they share, and stay one.
    """
    values = np.array(values, dtype=float)
    flat = values.reshape(-1)
    tolerance = _ON_THE_SURFACE * step
    on = np.flatnonzero((flat <= 0.0) & (flat >= -tolerance))
    if on.size == 0:
        return values
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    away = _ROUND_A_POINT * (_BESIDE * step)
    per_batch = max(1, _CHUNK // away.shape[0])
    for start in range(0, on.size, per_batch):
        some = on[start:start + per_batch]
        probes = (points[some][:, None, :] + away[None, :, :]).reshape(-1, 3)
        beside = _evaluate(solid, probes).reshape(some.size, away.shape[0])
        alone = ~np.any(beside < -tolerance, axis=1)
        flat[some[alone]] = 2.0 * tolerance
    return values


def _the_thinnest_the_grid_misses(
    solid: SDF, lo: Array, spacing: float, field: Array
) -> float | None:
    """How thin the thinnest thing the grid stepped over is, or None.

    Two neighbouring samples on the same side of the surface, closer to it
    between them than the step that separates them -- `|f(p)| + |f(q)| <
    spacing` -- may have material (or a gap in it) lying wholly between
    them. Each such segment is walked by the field's own distances; where
    the walk meets the other side, something thinner than a cell is there,
    and its thickness is read as twice the deepest the walk went into it.
    """
    hits: list[float] = []
    floor = spacing / 32.0
    nx, ny, nz = field.shape
    any_inside = np.zeros((nx - 1, ny - 1, nz - 1), dtype=bool)
    all_inside = np.ones_like(any_inside)
    for i in (0, 1):
        for j in (0, 1):
            for m in (0, 1):
                corner = field[i:i + nx - 1, j:j + ny - 1, m:m + nz - 1] <= 0.0
                any_inside |= corner
                all_inside &= corner
    # Padded by one cell all round, so every edge has its four cells.
    boundary = np.zeros((nx + 1, ny + 1, nz + 1), dtype=bool)
    boundary[1:-1, 1:-1, 1:-1] = any_inside & ~all_inside
    for axis in range(3):
        lower = [slice(None)] * 3
        upper = [slice(None)] * 3
        lower[axis] = slice(0, -1)
        upper[axis] = slice(1, None)
        a = field[tuple(lower)]
        b = field[tuple(upper)]
        candidate = ((a <= 0.0) == (b <= 0.0)) & (
            np.abs(a) + np.abs(b) < spacing)
        if not candidate.any():
            continue
        # Only where the surface is nowhere round the segment: a curved face
        # grazing a segment between two cells that already carry it -- a
        # slanted hole's wall -- is drawn by them, and is not something the
        # grid stepped over. A wall lying wholly between two planes of
        # samples has no boundary cell round it at all.
        other = _RIGHT_HANDED_PAIR[axis]
        shape = a.shape
        near = np.zeros(shape, dtype=bool)
        for da in (0, 1):
            for db in (0, 1):
                index = [slice(None)] * 3
                index[axis] = slice(1, shape[axis] + 1)
                index[other[0]] = slice(da, da + shape[other[0]])
                index[other[1]] = slice(db, db + shape[other[1]])
                near |= boundary[tuple(index)]
        candidate &= ~near
        if not candidate.any():
            continue
        where = np.argwhere(candidate)
        if where.shape[0] > 400_000:
            # Enough to find what is there: the walk is a detector, and a
            # thin wall is stepped over along a whole sheet of segments.
            pick = np.random.default_rng(0).choice(
                where.shape[0], 400_000, replace=False)
            where = where[pick]
        start = lo + where * spacing
        solid_side = (a[tuple(where.T)] <= 0.0)
        travelled = np.abs(a[tuple(where.T)])
        entered = np.full(where.shape[0], np.nan)
        deepest = np.zeros(where.shape[0])
        active = np.arange(where.shape[0])
        for _ in range(48):
            if not active.size:
                break
            here = start[active].copy()
            here[:, axis] += travelled[active]
            value = _evaluate(solid, here)
            other = (value <= 0.0) != solid_side[active]
            inside_it = active[other]
            entered[inside_it] = np.where(np.isnan(entered[inside_it]),
                                          travelled[inside_it],
                                          entered[inside_it])
            deepest[inside_it] = np.maximum(deepest[inside_it],
                                            np.abs(value[other]))
            # Outside it, step by the clear distance; inside it, in small
            # steps, to find how deep it goes.
            stride = np.where(other, floor,
                              np.maximum(np.abs(value), floor))
            travelled[active] += stride
            keep = travelled[active] < spacing
            # Once through it and out again, the walk is done.
            leaving = ~other & ~np.isnan(entered[active])
            active = active[keep & ~leaving]
        found = ~np.isnan(entered)
        if found.any():
            hits.extend((2.0 * deepest[found]).tolist())
    # A surface that only grazes a segment -- a cylinder touching it, a face
    # lying on a plane of samples -- is entered by nothing: hundredths of a
    # cell deep, drawn already by the cells round it. Something stepped over
    # is a tenth of a cell thick at least, and stepped over more than once.
    real = sorted(t for t in hits if t >= spacing / 10.0)
    if len(real) < 3:
        return None
    # The thinnest of them, less the odd one: a tenth of the way up.
    best = real[len(real) // 10]
    return best


def _banded_surface(
    solid: SDF, lo: Array, spacing: float, field: Array, thinnest: float,
    fit: bool = False,
) -> TriangleMesh | None:
    """Surface nets on a fine grid, sampled only in the band round the
    surface.

    The coarse cells that can hold surface -- a sign change among their
    corners, or a corner nearer the surface than half the cell's diagonal
    (with a margin, for a field stretched by a bend or a blend) -- are each
    cut into k by k by k fine cells, k enough to put a sample across the
    thinnest thing the coarse grid missed wherever it lies, within a fixed
    budget of points.
    Every other coarse cell is wholly in or wholly out, so the fine grid's
    surface lies in the band, and the mesh is the one a dense fine grid
    would give. None when the band would not fit the budget at any useful
    fineness, and the coarse grid is used as before.
    """
    counts = np.array(field.shape)
    nx, ny, nz = counts
    # Half the cell's diagonal is where a cell with no sign change can still
    # hold surface; a little more, for a field a bend or a blend stretches.
    reach = 1.0 * spacing
    nearest = None
    any_inside = np.zeros((nx - 1, ny - 1, nz - 1), dtype=bool)
    all_inside = np.ones_like(any_inside)
    for i in (0, 1):
        for j in (0, 1):
            for m in (0, 1):
                corner = field[i:i + nx - 1, j:j + ny - 1, m:m + nz - 1]
                size = np.abs(corner)
                nearest = size if nearest is None else np.minimum(nearest, size)
                any_inside |= corner <= 0.0
                all_inside &= corner <= 0.0
    band = (any_inside & ~all_inside) | (nearest <= reach)
    cells = np.argwhere(band)
    count = cells.shape[0]
    if count == 0:
        return None
    # A sample across the thinnest thing missed wherever it lies -- a step
    # no wider than it is thick -- and no finer: every step finer is eight
    # times the points, and the mesh a printer is sent eight times the
    # size. None of it when that will not fit: the coarse grid is then used
    # as before, rather than a band too coarse to see what it was read for.
    k = max(2, int(np.ceil(spacing / max(thinnest, 1e-9))))
    if fit:
        # As fine as asked, or as fine as the budget allows: a surface to
        # print from is still better a little coarser than not at all. The
        # surface comes out at about k * k faces for every coarse cell in the
        # band, and is bounded too, so a large part's STL stays a file a
        # slicer opens.
        k = min(k, 32, int((_BAND_BUDGET / count) ** (1.0 / 3.0)),
                int((_PRINT_FACES / count) ** 0.5))
        if k < 2:
            return None
    elif count * k ** 3 > _BAND_BUDGET or k > 32:
        return None
    fine = spacing / k
    K = k + 1
    nodes_per_axis = (counts - 1) * k + 1
    offsets = np.stack(np.meshgrid(np.arange(K), np.arange(K), np.arange(K),
                                   indexing="ij"), axis=-1).reshape(-1, 3)
    block = np.empty((count, K, K, K), dtype=bool)
    # A slab of cells at a time, so memory stays bounded whatever the band;
    # a node two neighbouring slabs share is evaluated in each.
    per_chunk = max(1, 2_000_000 // (K ** 3))
    for start in range(0, count, per_chunk):
        some = cells[start:start + per_chunk]
        nodes = some[:, None, :].astype(np.int64) * k + offsets[None, :, :]
        keys = (nodes[..., 0] * nodes_per_axis[1] + nodes[..., 1]) \
            * nodes_per_axis[2] + nodes[..., 2]
        del nodes
        unique, inverse = np.unique(keys.ravel(), return_inverse=True)
        del keys
        coords = np.stack([unique // (nodes_per_axis[1] * nodes_per_axis[2]),
                           (unique // nodes_per_axis[2]) % nodes_per_axis[1],
                           unique % nodes_per_axis[2]], axis=1)
        at = lo + coords * fine
        inside_at = _material_only_where_material_is(
            solid, at, _evaluate(solid, at), fine) <= 0.0
        del at
        block[start:start + per_chunk] = inside_at[inverse].reshape(
            some.shape[0], K, K, K)
        del coords, unique, inverse, inside_at

    # The fine boundary cells, block by block.
    any_in = np.zeros((count, k, k, k), dtype=bool)
    all_in = np.ones_like(any_in)
    for i in (0, 1):
        for j in (0, 1):
            for m in (0, 1):
                corner = block[:, i:i + k, j:j + k, m:m + k]
                any_in |= corner
                all_in &= corner
    which = np.argwhere(any_in & ~all_in)
    del any_in, all_in
    if which.shape[0] == 0:
        return None
    fine_cells = cells[which[:, 0]].astype(np.int64) * k + which[:, 1:]
    cells_per_axis = nodes_per_axis - 1
    cell_keys = (fine_cells[:, 0] * cells_per_axis[1] + fine_cells[:, 1]) \
        * cells_per_axis[2] + fine_cells[:, 2]
    order = np.argsort(cell_keys)
    sorted_keys = cell_keys[order]

    centres = lo + (fine_cells + 0.5) * fine
    for _ in range(2):
        value = _evaluate(solid, centres)
        gradient = solid.gradient(centres, step=fine * 0.25)
        norm = np.linalg.norm(gradient, axis=1, keepdims=True)
        norm[norm < 1e-12] = 1.0
        centres = centres - gradient / norm * value[:, None]
    cell_lo = lo + fine_cells * fine
    centres = np.clip(centres, cell_lo, cell_lo + fine)

    def vertex_of(cell: Array) -> Array:
        key = (cell[:, 0] * cells_per_axis[1] + cell[:, 1]) \
            * cells_per_axis[2] + cell[:, 2]
        inside_grid = np.all((cell >= 0) & (cell < cells_per_axis), axis=1)
        at = np.clip(np.searchsorted(sorted_keys, key), 0,
                     sorted_keys.size - 1)
        found = inside_grid & (sorted_keys[at] == key)
        return np.where(found, order[at], -1)

    faces: list[Array] = []
    for axis in range(3):
        lower = [slice(None)] * 4
        upper = [slice(None)] * 4
        lower[axis + 1] = slice(0, k)
        upper[axis + 1] = slice(1, k + 1)
        low = block[tuple(lower)]
        crossing = low != block[tuple(upper)]
        where = np.argwhere(crossing)
        if where.shape[0] == 0:
            continue
        lower_inside = low[crossing]
        edge_nodes = cells[where[:, 0]].astype(np.int64) * k + where[:, 1:]
        edge_keys = (edge_nodes[:, 0] * nodes_per_axis[1] + edge_nodes[:, 1]) \
            * nodes_per_axis[2] + edge_nodes[:, 2]
        _, first = np.unique(edge_keys, return_index=True)
        edge_nodes = edge_nodes[first]
        lower_inside = lower_inside[first]
        other = _RIGHT_HANDED_PAIR[axis]
        corners = []
        for da, db in ((0, 0), (0, -1), (-1, -1), (-1, 0)):
            cell = edge_nodes.copy()
            cell[:, other[0]] += da
            cell[:, other[1]] += db
            corners.append(vertex_of(cell))
        quad = np.stack(corners, axis=1)
        valid = np.all(quad >= 0, axis=1)
        quad = quad[valid]
        oriented = np.where(lower_inside[valid][:, None], quad[:, ::-1], quad)
        faces.append(oriented)
    if not faces:
        return None
    quads = np.vstack(faces)
    if quads.shape[0] == 0:
        return None
    triangles = np.vstack([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])
    return TriangleMesh(vertices=centres, faces=triangles)


#: For each axis, the two perpendicular axes in right-handed order, so that
#: ``u x v = +axis``. Getting this wrong reverses the face winding for that
#: family of edges only -- see the note in :func:`_quads_along_axis`.
_RIGHT_HANDED_PAIR: tuple[tuple[int, int], ...] = ((1, 2), (2, 0), (0, 1))


def _quads_along_axis(
    inside: Array, cell_index: Array, axis: int
) -> list[Array]:
    """Emit one quad per grid edge that crosses the surface.

    The four cells sharing that edge supply the quad's corners. Winding is
    chosen from the sign change so that every face points out of the solid.
    """
    nx, ny, nz = inside.shape
    quads: list[Array] = []

    # Index the grid edges along `axis` that lie interior to the cell grid.
    if axis == 0:
        a = inside[:-1, 1:-1, 1:-1]
        b = inside[1:, 1:-1, 1:-1]
    elif axis == 1:
        a = inside[1:-1, :-1, 1:-1]
        b = inside[1:-1, 1:, 1:-1]
    else:
        a = inside[1:-1, 1:-1, :-1]
        b = inside[1:-1, 1:-1, 1:]

    crossing = a != b
    if not np.any(crossing):
        return quads
    positions = np.argwhere(crossing)
    # Convert to grid-node coordinates of the edge's lower node.
    offset = np.array([1, 1, 1])
    offset[axis] = 0
    nodes = positions + offset

    # The four cells around an edge along `axis` are obtained by stepping back
    # by one in each of the two perpendicular axes.
    #
    # The pair must be *right-handed* with respect to `axis` -- (y, z) for x,
    # (z, x) for y, (x, y) for z -- not merely "the other two in ascending
    # order". Taking (x, z) for the y edges reverses the handedness of that
    # family alone, which produces a mesh that is still watertight and still
    # looks correct, but whose faces along one axis point inward. Nothing in the
    # topology catches it; the signed volume comes out wrong by roughly a third
    # and every normal-dependent downstream step is quietly corrupted.
    other = _RIGHT_HANDED_PAIR[axis]
    corners = []
    for da, db in ((0, 0), (0, -1), (-1, -1), (-1, 0)):
        shift = np.zeros(3, dtype=int)
        shift[other[0]] = da
        shift[other[1]] = db
        cell = nodes + shift
        cell[:, axis] = nodes[:, axis]
        corners.append(cell)

    valid = np.ones(nodes.shape[0], dtype=bool)
    limits = np.array(cell_index.shape)
    indices = []
    for cell in corners:
        within = np.all((cell >= 0) & (cell < limits), axis=1)
        valid &= within
        safe = np.clip(cell, 0, limits - 1)
        indices.append(cell_index[safe[:, 0], safe[:, 1], safe[:, 2]])

    stacked = np.stack(indices, axis=1)
    valid &= np.all(stacked >= 0, axis=1)
    if not np.any(valid):
        return quads

    quad = stacked[valid]
    # Orient: when the lower node is inside and the upper is outside, the face
    # normal points along +axis, otherwise the winding is reversed.
    # With the offsets above traversed in a right-handed (u, v) frame, the quad
    # as built winds so its normal points along -axis. That is the outward
    # direction when the *upper* node is the solid one, so the winding is
    # reversed in the opposite case.
    lower_inside = a[crossing][valid]
    flipped = quad[:, ::-1]
    oriented = np.where(lower_inside[:, None], flipped, quad)
    quads.append(oriented)
    return quads


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
def write_stl(mesh: TriangleMesh, path: str | Path, *, name: str = "forge") -> Path:
    """Write a binary STL.

    STL is a mesh interchange format with no units and no topology. Forge emits
    it for additive manufacturing only, and the assurance report says so: an STL
    is never the exchange format of record, because it cannot carry the design
    intent that ForgeIR exists to preserve.
    """
    target = Path(path)
    # All facets at once: a surface meshed for printing has a few hundred
    # thousand, and writing them one at a time took minutes.
    record = np.zeros(mesh.face_count, dtype=_STL_FACET)
    record["normal"] = mesh.face_normals()
    record["corners"] = mesh.vertices[mesh.faces]
    with target.open("wb") as handle:
        header = f"Forge implicit backend - {name}".encode()[:80]
        handle.write(header.ljust(80, b"\0"))
        handle.write(struct.pack("<I", mesh.face_count))
        handle.write(record.tobytes())
    return target


#: One facet of a binary STL: its normal, its three corners, two spare bytes.
_STL_FACET = np.dtype([("normal", "<f4", (3,)), ("corners", "<f4", (3, 3)),
                       ("spare", "<u2")])


def write_obj(mesh: TriangleMesh, path: str | Path, *, name: str = "forge") -> Path:
    target = Path(path)
    lines = [f"# Forge implicit backend - {name}", "# units: millimetre"]
    lines.extend(
        f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in mesh.vertices
    )
    lines.extend(
        f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh.faces
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


__all__ = [
    "TriangleMesh",
    "extract_surface",
    "write_stl",
    "write_obj",
]
