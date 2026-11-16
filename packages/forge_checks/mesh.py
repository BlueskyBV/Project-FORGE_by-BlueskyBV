"""A triangle mesh, and the view of a part it gives: what a shipped STL or 3MF is judged by.

**Welding.** Corners at exactly the same coordinates are one vertex; nothing
merely close is merged, so a crack stays a crack. A coordinate that isn't
finite, is too small to compute with exactly (:data:`~.predicates.SMALLEST`)
or is beyond :data:`LARGEST` makes its triangle bad; bad triangles are
reported, never dropped.

**Soundness** (:meth:`MeshView.topology`). A mesh bounds a solid only if
every edge has exactly two triangles running opposite ways, every corner's
triangles make one fan, no two triangles meet where they aren't joined
(:mod:`.intersect`), and its shells nest as their orientations say: a shell
facing outwards bounds material, one facing inwards bounds a hollow inside
material. A mesh that isn't sound answers :attr:`Side.UNKNOWN` for every
point and the whole real line for its volume: it holds the part.

**Which side** (:meth:`MeshView.classify`). Every distance is known to
within ``E``, :data:`~.triangles.DISTANCE_ERROR` times the size of the
coordinates. A point surely within :data:`ON_BAND` of the surface is ON; one
that might be either side of the band is UNKNOWN. Elsewhere, its side comes
from the nearest point of the surface and the outward normal there: the
face's normal inside a triangle, and on an edge or a corner the
angle-weighted pseudonormal of Bærentzen and Aanæs (*Signed Distance
Computation Using the Angle Weighted Pseudonormal*, 2005), which on a sound
mesh tells inside from outside exactly. Since rounding can pick the wrong
feature where two are almost equally near (a knife-edge; the two sides at a
needle's tip), every corner, side and face within ``2E`` of the nearest is
asked too, and all must give the same side, each well clear of its own
rounding. Where they don't, or a normal is too
ill-defined to trust, three rays are cast from the point; each counts its
crossings and their directions, a ray that grazes an edge or a corner (or
meets two surfaces at the same distance) is cast again in another
direction, and the three must agree, or the answer is UNKNOWN.

**Crossings** are found by the watertight ray test (:mod:`.triangles`),
**volume** by the divergence theorem with a stated bound on its rounding, and
**coverage** by rows of points along each triangle's longest side, ``r/√2``
apart and their points ``√2 r`` apart at most: every point of the triangle
is then within ``r`` of one, and a needle takes one row. Each triangle's own
side middles and centre are kept too, each point with the outward normal of
the feature it lies on.

>>> import numpy as np
>>> view = MeshView(box_mesh((0, 0, 0), (2, 2, 2)), source="mesh-file", deflection=0.0)
>>> view.classify(np.array([[1, 1, 1], [3, 1, 1], [2, 1, 1.5]], float)).tolist()
[1, -1, 0]
>>> view.topology().sound, view.volume().contains(8.0)
(True, True)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import cached_property

import numpy as np
from forge_numeric import vector as fv
from forge_units import Interval
from numpy.typing import NDArray

from .intersect import pairs_meet, simple_stars
from .predicates import LARGEST, SMALLEST, orient2d
from .tree import Tree
from .triangles import (
    DISTANCE_ERROR,
    EDGE_AB,
    EDGE_BC,
    EDGE_CA,
    FACE,
    features,
    ray_hits,
    unit_normals,
)
from .view import (
    Box,
    Capability,
    Coverage,
    Crossings,
    EdgeFacts,
    FaceFacts,
    Side,
    Topology,
)

__all__ = ["LARGEST", "ON_BAND", "Mesh", "MeshShape", "MeshView", "box_mesh"]

#: A point this close to the surface (mm) is on it.
ON_BAND = 1e-9
#: An edge's or a corner's pseudonormal is trusted when the normals it sums
#: (weighted by angle, for a corner) add up to at least this length.
_FEATURE_TRUST = 1e-3
#: How far a trusted feature's normal may point off, in radians: a sum of
#: accurate unit normals, divided by at least _FEATURE_TRUST.
_FEATURE_TILT = 1e7 * 2.0**-53
#: Rays per point, and tries per ray before giving up.
_RAYS = 3
_TRIES = 21
#: Triangles covered at a time: bounds the working memory beside the points made.
_PIECES = 1 << 16

Array = NDArray[np.float64]
Index = NDArray[np.int64]
Bools = NDArray[np.bool_]


def _directions(count: int) -> Array:
    """Directions spread over the sphere by a fixed low-discrepancy rule (the same on every machine)."""
    k = np.arange(count, dtype=np.float64)
    u = (0.5 + k * 0.7548776662466927) % 1.0
    v = (0.5 + k * 0.5698402909980532) % 1.0
    z = 1.0 - 2.0 * (0.05 + 0.9 * ((u + 0.137) % 1.0))
    r = np.sqrt(1.0 - z * z)
    angle = 2.0 * math.pi * v + 0.3
    return np.stack([r * fv.cos(angle), r * fv.sin(angle), z], axis=1)


_DIRECTIONS = _directions(_RAYS * _TRIES)


def _components(size: int, a: Index, b: Index) -> Index:
    """Connected components of ``size`` nodes joined by the pairs ``a[i]``-``b[i]``: a root per node."""
    parent: Index = np.arange(size, dtype=np.int64)
    while True:
        pa, pb = parent[a], parent[b]
        lo, hi = np.minimum(pa, pb), np.maximum(pa, pb)
        apart = lo != hi
        if not apart.any():
            return parent
        np.minimum.at(parent, hi[apart], lo[apart])
        while True:
            grand = parent[parent]
            if np.array_equal(grand, parent):
                break
            parent = grand


def _norms(points: Array) -> Array:
    return np.asarray(np.sqrt(fv.dot(points, points)), dtype=np.float64)


@dataclass(frozen=True, eq=False)
class Mesh:
    """Vertices, and triangles as three vertex indices each, turning anticlockwise seen from outside."""

    vertices: Array
    faces: Index

    def __post_init__(self) -> None:
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise ValueError("vertices must be (n, 3)")
        if self.faces.ndim != 2 or self.faces.shape[1] != 3:
            raise ValueError("faces must be (n, 3)")
        if len(self.faces) and (
            self.faces.min() < 0 or self.faces.max() >= len(self.vertices)
        ):
            raise ValueError("a face names a vertex that isn't there")

    @classmethod
    def from_triangles(cls, triangles: Array) -> Mesh:
        """Weld a list of triangles ``(n, 3, 3)``: corners at exactly the same coordinates become one."""
        corners = (
            np.asarray(triangles, dtype=np.float64).reshape(-1, 3) + 0.0
        )  # -0.0 is 0.0
        finite = np.isfinite(corners).all(axis=1)
        index = np.empty(len(corners), dtype=np.int64)
        rows = np.flatnonzero(finite)
        good = corners[rows]
        ranked = np.lexsort((good[:, 2], good[:, 1], good[:, 0]))
        sorted_ = good[ranked]
        new = np.ones(len(sorted_), dtype=bool)
        new[1:] = (sorted_[1:] != sorted_[:-1]).any(axis=1)
        label = np.cumsum(new) - 1
        index[rows[ranked]] = label
        unique = sorted_[new]
        # A corner that isn't finite is a vertex of its own: never welded to anything.
        lost = np.flatnonzero(~finite)
        index[lost] = len(unique) + np.arange(len(lost))
        vertices = np.concatenate([unique, corners[lost]])
        return cls(vertices=vertices, faces=index.reshape(-1, 3))


def box_mesh(lo: tuple[float, float, float], hi: tuple[float, float, float]) -> Mesh:
    """A box as twelve outward-facing triangles."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array(
        [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
         [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]],
        dtype=np.float64,
    )  # fmt: skip
    f = np.array(
        [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
         [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]],
        dtype=np.int64,
    )  # fmt: skip
    return Mesh(vertices=v, faces=f)


@dataclass(frozen=True, eq=False)
class _Edges:
    """The mesh's edges, each once, and how the triangles use them."""

    ends: Index  # (E, 2), lower vertex first
    of_face: Index  # (F, 3): face k's edge from corner k to corner k+1
    uses: Index  # (E,): how many triangles use it
    forward: Index  # (E,): how many of them run from the lower vertex to the higher
    by_edge: Index  # the directed edges (3f + k), ordered by edge
    first_use: Index  # (E,): where each edge's uses start in by_edge


@dataclass(frozen=True, eq=False)
class _Hits:
    """Crossings of rays ahead of their origins, ordered by ray then distance; grazes per ray."""

    ray: Index
    face: Index
    t: Array
    entering: Bools
    grazed: Bools  # per ray


@dataclass(frozen=True, eq=False)
class _Near:
    distance: Array
    triangle: Index
    point: Array
    region: NDArray[np.int8]


class MeshShape:
    """What a mesh is, worked out once from its triangles alone.

    Everything here is cached on first use and shared by every view of the
    mesh (:meth:`MeshView.with_deflection`). A question the mesh can't answer
    at all (a distance to a mesh with no finite triangle) raises ValueError.
    """

    def __init__(self, mesh: Mesh) -> None:
        if not len(mesh.faces):
            raise ValueError("a mesh needs at least one triangle")
        self.mesh = mesh

    # --- the triangles --------------------------------------------------------

    @cached_property
    def _corners(self) -> tuple[Array, Array, Array]:
        v, f = self.mesh.vertices, self.mesh.faces
        return v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]

    @cached_property
    def _finite(self) -> Bools:
        a, b, c = self._corners
        finite = np.isfinite(a).all(1) & np.isfinite(b).all(1) & np.isfinite(c).all(1)
        return np.asarray(finite, dtype=bool)

    @cached_property
    def _good(self) -> Bools:
        """Triangles with computable coordinates, three different corners, and area."""
        f = self.mesh.faces
        a, b, c = self._corners
        odd = np.zeros(len(f), dtype=bool)
        for corner in (a, b, c):
            size = np.abs(np.where(np.isfinite(corner), corner, 1.0))
            odd |= (((size > 0.0) & (size < SMALLEST)) | (size > LARGEST)).any(axis=1)
        distinct = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])
        good: Bools = self._finite & ~odd & distinct
        rows = np.flatnonzero(good)
        flat = np.ones(len(rows), dtype=bool)
        for i, j in ((0, 1), (1, 2), (2, 0)):
            flat &= (
                orient2d(a[rows][:, [i, j]], b[rows][:, [i, j]], c[rows][:, [i, j]])
                == 0
            )
        good[rows[flat]] = False
        return good

    @cached_property
    def _searchable(self) -> Index:
        """The triangles the searches walk: finite and within :data:`LARGEST`."""
        a, b, c = self._corners
        within = np.ones(len(a), dtype=bool)
        for corner in (a, b, c):
            within &= (
                np.abs(np.where(np.isfinite(corner), corner, np.inf)) <= LARGEST
            ).all(1)
        return np.flatnonzero(within)

    @cached_property
    def _tree(self) -> Tree | None:
        """The tree over the searchable triangles (indexed as :attr:`_searchable`)."""
        rows = self._searchable
        if not rows.size:
            return None
        a, b, c = (x[rows] for x in self._corners)
        return Tree.build(
            np.minimum(np.minimum(a, b), c), np.maximum(np.maximum(a, b), c)
        )

    def _searched(self) -> tuple[Tree, Index]:
        tree = self._tree
        if tree is None:
            raise ValueError("the mesh has no finite triangle to measure to")
        return tree, self._searchable

    @cached_property
    def _reach(self) -> float:
        """The largest distance of a searchable corner from the origin: the scale of rounding."""
        rows = self._searchable
        if not rows.size:
            return 0.0
        a, b, c = (x[rows] for x in self._corners)
        return float(max(_norms(a).max(), _norms(b).max(), _norms(c).max()))

    # --- edges and normals ------------------------------------------------------

    @cached_property
    def _edges(self) -> _Edges:
        f = self.mesh.faces
        nv = np.int64(len(self.mesh.vertices))
        start = f.reshape(-1)
        end = f[:, [1, 2, 0]].reshape(-1)
        lo, hi = np.minimum(start, end), np.maximum(start, end)
        unique, inverse, uses = np.unique(
            lo * nv + hi, return_inverse=True, return_counts=True
        )
        inverse = inverse.reshape(-1)
        forward = np.bincount(inverse, weights=(start < end), minlength=len(unique))
        return _Edges(
            ends=np.stack([unique // nv, unique % nv], 1).astype(np.int64),
            of_face=inverse.reshape(-1, 3).astype(np.int64),
            uses=uses.astype(np.int64),
            forward=forward.astype(np.int64),
            by_edge=np.argsort(inverse, kind="stable").astype(np.int64),
            first_use=(np.cumsum(uses) - uses).astype(np.int64),
        )

    @cached_property
    def _normals(self) -> Array:
        """Each searchable triangle's unit normal (zero for one with no area), indexed by face."""
        unit = np.zeros((len(self.mesh.faces), 3))
        rows = self._searchable
        a, b, c = (x[rows] for x in self._corners)
        unit[rows] = unit_normals(a, b, c)
        unit[~self._good] *= 0.0
        return unit

    @cached_property
    def _pseudonormals(self) -> tuple[Array, Bools, Array, Bools]:
        """Each vertex's and each edge's outward pseudonormal (unit), and whether to trust it."""
        f = self.mesh.faces
        unit = self._normals
        good = self._good
        a, b, c = self._corners
        nv = len(self.mesh.vertices)
        vertex: Array = np.zeros((nv, 3))
        vertex_ok = np.ones(nv, dtype=bool)
        for k, (here, nxt, prv) in enumerate(((a, b, c), (b, c, a), (c, a, b))):
            u, w = nxt - here, prv - here
            with np.errstate(invalid="ignore", over="ignore"):
                cross = np.asarray(np.cross(u, w), dtype=np.float64)
                angle = fv.arctan2(_norms(cross), fv.dot(u, w))
            weight = np.where(good, angle, 0.0)
            for axis in range(3):
                vertex[:, axis] += np.bincount(
                    f[:, k], weights=weight * unit[:, axis], minlength=nv
                )
            np.logical_and.at(vertex_ok, f[:, k], good)
        length = _norms(vertex)
        vertex_ok &= length >= _FEATURE_TRUST
        vertex = vertex / np.where(length > 0.0, length, 1.0)[:, None]

        edges = self._edges
        ne = len(edges.ends)
        edge: Array = np.zeros((ne, 3))
        of = edges.of_face.reshape(-1)
        owner = np.repeat(np.arange(len(f)), 3)
        for axis in range(3):
            edge[:, axis] = np.bincount(of, weights=unit[owner, axis], minlength=ne)
        edge_ok = np.ones(ne, dtype=bool)
        np.logical_and.at(edge_ok, of, good[owner])
        length = _norms(edge)
        edge_ok &= length >= _FEATURE_TRUST
        edge = edge / np.where(length > 0.0, length, 1.0)[:, None]
        return (
            vertex,
            np.asarray(vertex_ok, dtype=bool),
            edge,
            np.asarray(edge_ok, dtype=bool),
        )

    def _feature_normal(
        self, face: Index, region: NDArray[np.int8]
    ) -> tuple[Array, Bools]:
        """The outward normal at each point of ``face`` on feature ``region``, and whether to trust it."""
        vertex, vertex_ok, edge, edge_ok = self._pseudonormals
        f = self.mesh.faces
        of = self._edges.of_face
        normal = self._normals[face].copy()
        ok = self._good[face].copy()
        for code in (0, 1, 2):
            here = region == code
            v = f[face[here], code]
            normal[here], ok[here] = vertex[v], vertex_ok[v]
        for code, k in ((EDGE_AB, 0), (EDGE_BC, 1), (EDGE_CA, 2)):
            here = region == code
            e = of[face[here], k]
            normal[here], ok[here] = edge[e], edge_ok[e]
        return normal, ok

    # --- topology -----------------------------------------------------------------

    @cached_property
    def _shells(self) -> Index:
        """Each triangle's shell: the triangles joined to it through shared edges."""
        edges = self._edges
        d = edges.by_edge
        same = np.ones(len(d), dtype=bool)
        same[edges.first_use] = False  # a use is joined to the previous use of its edge
        join = same[1:]
        return _components(
            len(self.mesh.faces), (d[:-1] // 3)[join], (d[1:] // 3)[join]
        )

    @cached_property
    def _self_intersections(self) -> int:
        """Pairs of good triangles that meet where they aren't joined.

        The same triangle given more than once meets each of its copies: those
        pairs are counted, not searched, so a file of thousands of copies
        costs no more than one. The rest are searched in a tree of their own
        (bad triangles have no part in it).
        """
        good = np.flatnonzero(self._good)
        if not good.size:
            return 0
        faces = self.mesh.faces
        _, first, copies = np.unique(
            np.sort(faces[good], axis=1), axis=0, return_index=True, return_counts=True
        )
        doubled = int((copies * (copies - 1) // 2).sum())
        rows = good[first]
        a, b, c = (x[rows] for x in self._corners)
        tree = Tree.build(
            np.minimum(np.minimum(a, b), c), np.maximum(np.maximum(a, b), c)
        )
        simple = simple_stars(self.mesh.vertices, faces, self._good)
        found = doubled
        for one, other in tree.touching(tree.box_lo, tree.box_hi):
            found += int(
                pairs_meet(
                    self.mesh.vertices, faces, rows[one], rows[other], simple
                ).sum()
            )
        return found

    def _bad_vertices(self) -> int:
        """Corners whose triangles don't make one fan."""
        f = self.mesh.faces
        edges = self._edges
        two = np.flatnonzero(edges.uses == 2)
        d1 = edges.by_edge[edges.first_use[two]]
        d2 = edges.by_edge[edges.first_use[two] + 1]

        def ends(d: Index) -> tuple[Index, Index]:
            """The corners at a directed edge's start and end."""
            k = d % 3
            return d, d - k + (k + 1) % 3

        s1, e1 = ends(d1)
        s2, e2 = ends(d2)
        flat = f.reshape(-1)
        alike = flat[s1] == flat[s2]
        a = np.concatenate([s1, e1])
        b = np.concatenate([np.where(alike, s2, e2), np.where(alike, e2, s2)])
        label = _components(len(flat), a, b)
        distinct = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])
        corners = np.flatnonzero(np.repeat(distinct, 3))
        pairs = np.unique(np.stack([flat[corners], label[corners]], axis=1), axis=0)
        fans = np.bincount(pairs[:, 0], minlength=len(self.mesh.vertices))
        return int((fans > 1).sum())

    @cached_property
    def _topology(self) -> Topology:
        edges = self._edges
        f = self.mesh.faces
        distinct = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])
        open_edges = int((edges.uses == 1).sum())
        bad_edges = int(
            ((edges.uses > 2) | ((edges.uses == 2) & (edges.forward != 1))).sum()
        )
        bad_triangles = int((~self._good).sum())
        crossing = self._self_intersections
        bad_vertices = self._bad_vertices()
        topology = Topology(
            shells=len(np.unique(self._shells[distinct])) if distinct.any() else 0,
            solids=None,
            voids=None,
            open_edges=open_edges,
            bad_edges=bad_edges,
            bad_vertices=bad_vertices,
            bad_triangles=bad_triangles,
            self_intersections=crossing,
            misnested=None,
            genus=(),
        )
        if open_edges or bad_edges or bad_vertices or bad_triangles or crossing:
            return topology
        return self._nesting(topology)

    def _nesting(self, topology: Topology) -> Topology:
        """On an otherwise sound mesh: which shells bound material, which hollows, and do they nest."""
        a, b, c = self._corners
        names, shell = np.unique(self._shells, return_inverse=True)
        shell = shell.reshape(-1)
        count = len(names)
        # Each shell's volume about its own centre, so that a small part far
        # from the origin isn't lost in rounding, with a bound on the rounding.
        lo = np.full((count, 3), np.inf)
        hi = np.full((count, 3), -np.inf)
        for corner in (a, b, c):
            np.minimum.at(lo, shell, corner)
            np.maximum.at(hi, shell, corner)
        centre = ((lo + hi) * 0.5)[shell]
        u, v, w = a - centre, b - centre, c - centre
        signed = fv.dot(u, np.cross(v, w))
        sizes = _norms(u) * _norms(v) * _norms(w)
        volume = np.bincount(shell, weights=signed, minlength=count)
        faces = np.bincount(shell, minlength=count)
        rounding = 64.0 * 2.0**-53 * np.bincount(
            shell, weights=sizes, minlength=count
        ) + faces * 2.0**-53 * np.bincount(
            shell, weights=np.abs(signed), minlength=count
        )
        outward = volume > 0.0
        flat = np.abs(volume) <= rounding
        # A point on each shell: the centre of its first triangle.
        first = np.zeros(count, dtype=np.int64)
        first[shell[::-1]] = np.arange(len(shell))[::-1]
        on_shell = (a[first] + b[first] + c[first]) / 3.0
        inside = self._parities(on_shell, shell, count)
        if inside is None:
            return replace(topology, misnested=count)
        depth = inside.sum(axis=1)
        misnested = int((flat | (outward != (depth % 2 == 0))).sum())
        solids = [s for s in range(count) if outward[s] and not flat[s]]
        genus = []
        f = self.mesh.faces
        of = self._edges.of_face
        for s in sorted(solids, key=lambda s: -volume[s]):
            mine = shell == s
            chi = len(np.unique(f[mine])) - len(np.unique(of[mine])) + int(mine.sum())
            genus.append((2 - chi) // 2)
        return replace(
            topology,
            solids=len(solids),
            voids=int((~outward & ~flat).sum()),
            misnested=misnested,
            genus=tuple(genus),
        )

    def _parities(
        self, points: Array, shell: Index, count: int
    ) -> NDArray[np.bool_] | None:
        """For the point on each shell: is it inside each other shell? ``None`` if rays kept grazing."""
        answer = np.zeros((count, count), dtype=bool)
        todo: Index = np.arange(count)
        for attempt in range(_TRIES):
            if not todo.size:
                return answer
            direction = np.repeat(
                _DIRECTIONS[attempt * _RAYS][None, :], len(todo), axis=0
            )
            # Its own shell is where each ray starts: crossings of it don't count.
            found = self._cast(points[todo], direction, skip=(shell, todo))
            crossings = np.zeros((len(todo), count), dtype=np.int64)
            np.add.at(crossings, (found.ray, shell[found.face]), 1)
            settled = ~found.grazed
            answer[todo[settled]] = (crossings[settled] % 2) == 1
            todo = todo[found.grazed]
        return answer if not todo.size else None

    def _cast(
        self,
        origins: Array,
        directions: Array,
        skip: tuple[Index, Index] | None = None,
    ) -> _Hits:
        """Every crossing ahead of each ray (unit directions), and which rays grazed.

        A ray grazes where it meets a triangle exactly on a side or a corner,
        or meets two triangles at distances rounding can't tell apart (it
        clips an edge or a corner, or two surfaces touch there). ``skip`` is
        (each face's shell, each ray's shell): crossings of a ray's own
        shell are left out.
        """
        tree, rows = self._searched()
        reach = self._reach + float(np.abs(origins).max(initial=0.0)) * math.sqrt(3.0)
        pad = 1e-9 * (1.0 + reach)
        grazed = np.zeros(len(origins), dtype=bool)
        found: list[tuple[Index, Index, Array, Bools]] = []
        for ray, entry in tree.along(origins, directions, pad):
            face = rows[entry]
            if skip is not None:
                mine = skip[0][face] == skip[1][ray]
                ray, face = ray[~mine], face[~mine]
            a, b, c = (x[face] for x in self._corners)
            hit, t, touch, front = ray_hits(origins[ray], directions[ray], a, b, c)
            grazed[ray[touch]] = True
            found.append((ray[hit], face[hit], t[hit], front[hit]))
        none = np.zeros(0, dtype=np.int64)
        ray, face, t, entering = (
            (np.concatenate(x) for x in zip(*found, strict=True))
            if found
            else (none, none, np.zeros(0), np.zeros(0, dtype=bool))
        )
        order = np.lexsort((t, ray))
        ray, face, t, entering = ray[order], face[order], t[order], entering[order]
        # Two crossings of one ray closer than rounding can tell apart: a graze.
        scale = DISTANCE_ERROR * (reach + np.abs(t))
        close = (ray[1:] == ray[:-1]) & (t[1:] - t[:-1] <= scale[1:] + scale[:-1])
        grazed[ray[1:][close]] = True
        return _Hits(ray, face, t, entering, grazed)

    # --- the questions ------------------------------------------------------------

    def topology(self) -> Topology:
        return self._topology

    def _nearest(self, points: Array) -> _Near:
        tree, rows = self._searched()
        a, b, c = (x[rows] for x in self._corners)
        found = tree.nearest(points, a, b, c, self._normals[rows])
        return _Near(found.distance, rows[found.triangle], found.point, found.region)

    def _error(self, points: Array) -> Array:
        """How far each point's computed distance to any triangle may be from the true one."""
        return DISTANCE_ERROR * (_norms(points) + self._reach)

    def classify(self, points: Array) -> NDArray[np.int8]:
        points = np.asarray(points, dtype=np.float64)
        sides = np.full(len(points), Side.UNKNOWN, dtype=np.int8)
        if not self._topology.sound or not len(points):
            return sides
        near = self._nearest(points)
        error = self._error(points)
        sides[near.distance + error <= ON_BAND] = Side.ON
        off = np.flatnonzero(near.distance - error > ON_BAND)
        if not off.size:
            return sides
        decided = self._by_normals(points[off], near.distance[off], error[off])
        sides[off] = decided
        rest = off[decided == Side.UNKNOWN]
        if rest.size:
            sides[rest] = self.sides_by_rays(points[rest])
        return sides

    def _by_normals(
        self, points: Array, distance: Array, error: Array
    ) -> NDArray[np.int8]:
        """Each point's side from the normal of every feature that may be its nearest.

        Every corner, side and face within ``2E`` of the nearest distance, of
        every triangle: rounding can pick the wrong one of two near-equal
        features, even within one triangle (the two sides at a needle's tip).
        The truly nearest is among them, and its normal gives the true side;
        so all must agree, each clear of its rounding, or the answer is
        UNKNOWN (and rays are cast).
        """
        tree, rows = self._searched()
        a, b, c = (x[rows] for x in self._corners)
        normals = self._normals[rows]
        lowest = np.full(len(points), 2, dtype=np.int8)
        highest = np.full(len(points), -2, dtype=np.int8)
        reach = distance + 2.0 * error
        for who, entry in tree.within(points, reach):
            here = points[who]
            # A triangle's plane is no farther than the triangle: a cheap cut.
            height = np.abs(fv.dot(here - a[entry], normals[entry]))
            close = height <= reach[who] + error[who]
            who, entry, here = who[close], entry[close], here[close]
            at, d, valid = features(here, a[entry], b[entry], c[entry], normals[entry])
            valid &= d <= reach[who][:, None]
            pair, region = np.nonzero(valid)
            who, face = who[pair], rows[entry[pair]]
            gap = here[pair] - at[pair, region]
            normal, ok = self._feature_normal(face, region.astype(np.int8))
            lean = fv.dot(gap, normal)
            margin = error[who] + d[pair, region] * _FEATURE_TILT
            sign = np.where(
                ok & (lean > margin), 1, np.where(ok & (lean < -margin), -1, 0)
            )
            np.minimum.at(lowest, who, sign.astype(np.int8))
            np.maximum.at(highest, who, sign.astype(np.int8))
        sides = np.full(len(points), Side.UNKNOWN, dtype=np.int8)
        agreed = (lowest == highest) & (lowest != 0)
        sides[agreed] = np.where(lowest[agreed] > 0, Side.OUT, Side.IN)
        return sides

    def sides_by_rays(self, points: Array) -> NDArray[np.int8]:
        """Each point's side from three rays alone, which must agree (UNKNOWN on an unsound mesh).

        For points off the surface: a point on it may come out either side.
        """
        n = len(points)
        if not self._topology.sound or not n:
            return np.full(n, Side.UNKNOWN, dtype=np.int8)
        # 1 inside, 0 outside, -1 not yet, -2 inconsistent (a sound mesh never is).
        verdict = np.full((n, _RAYS), -1, dtype=np.int8)
        for slot in range(_RAYS):
            todo: Index = np.arange(n)
            for attempt in range(_TRIES):
                if not todo.size:
                    break
                direction = np.repeat(
                    _DIRECTIONS[slot + _RAYS * attempt][None, :], len(todo), axis=0
                )
                found = self._cast(points[todo], direction)
                crossings = np.bincount(found.ray, minlength=len(todo))
                entering = np.bincount(
                    found.ray, weights=found.entering, minlength=len(todo)
                )
                winding = crossings - 2 * entering.astype(
                    np.int64
                )  # leaving minus entering
                inside = crossings % 2 == 1
                fair = winding == inside.astype(np.int64)
                settled = ~found.grazed
                verdict[todo[settled & fair], slot] = inside[settled & fair]
                verdict[todo[settled & ~fair], slot] = -2
                todo = todo[found.grazed]
        sides = np.full(n, Side.UNKNOWN, dtype=np.int8)
        agreed = (verdict == verdict[:, :1]).all(axis=1) & (verdict[:, 0] >= 0)
        sides[agreed] = np.where(verdict[agreed, 0] == 1, Side.IN, Side.OUT)
        return sides

    def distance(self, points: Array) -> Array:
        points = np.asarray(points, dtype=np.float64)
        if not len(points):
            return np.zeros(0)
        return self._nearest(points).distance

    def near(self, points: Array, tolerances: Array) -> NDArray[np.bool_]:
        """Whether each point is within its tolerance of the mesh: ``distance(points) <= tolerances``, by the tree's own search (:meth:`~.tree.Tree.near`)."""
        points = np.asarray(points, dtype=np.float64)
        if not len(points):
            return np.zeros(0, dtype=bool)
        tree, rows = self._searched()
        a, b, c = (x[rows] for x in self._corners)
        t = np.broadcast_to(np.asarray(tolerances, dtype=np.float64), (len(points),))
        return tree.near(points, t, a, b, c, self._normals[rows])

    def crossings(self, origins: Array, directions: Array) -> Crossings:
        origins = np.asarray(origins, dtype=np.float64)
        directions = np.asarray(directions, dtype=np.float64)
        found = self._cast(origins, directions)
        return Crossings(
            ray=found.ray, t=found.t, entering=found.entering, grazed=found.grazed
        )

    def volume(self) -> Interval:
        if not self._topology.sound:
            return Interval(-math.inf, math.inf)
        a, b, c = self._corners
        lo, hi = self._bounds_arrays
        centre = (lo + hi) * 0.5
        a, b, c = a - centre, b - centre, c - centre
        six = fv.dot(a, np.cross(b, c))
        sizes = _norms(a) * _norms(b) * _norms(c)
        value = math.fsum(six.tolist()) / 6.0
        # Each determinant's rounding, and moving the corners to the centre,
        # are each a few units in the last place of |a||b||c|.
        error = 64.0 * 2.0**-53 * math.fsum(
            sizes.tolist()
        ) / 6.0 + 4.0 * 2.0**-53 * abs(value)
        return Interval(value - error, value + error)

    @cached_property
    def _bounds_arrays(self) -> tuple[Array, Array]:
        v = self.mesh.vertices
        finite = v[np.isfinite(v).all(axis=1)]
        if not len(finite):
            raise ValueError("the mesh has no finite vertex")
        return finite.min(axis=0), finite.max(axis=0)

    def area(self, weights: Array | None = None) -> float:
        """The area of its good triangles, a little more than it is (never less): its rounding is added; with ``weights``, each triangle's (one for each triangle, not negative) times its weight."""
        a, b, c = (x[self._good] for x in self._corners)
        twice = _norms(np.asarray(np.cross(b - a, c - a), dtype=np.float64))
        if weights is not None:
            twice = twice * weights[self._good]
        return math.fsum(twice.tolist()) / 2.0 * (1.0 + 1e-12)

    def bounds(self) -> Box:
        lo, hi = self._bounds_arrays
        return Box(
            (float(lo[0]), float(lo[1]), float(lo[2])),
            (float(hi[0]), float(hi[1]), float(hi[2])),
        )

    def coverage(
        self, radius: float, deflection: float | Array, within: Box | None = None
    ) -> Coverage:
        return _cover(self, radius, deflection, within)


class MeshView:
    """A mesh seen as a part: the :class:`~.view.GeometryView` for STL and 3MF files.

    ``deflection`` is how far the mesh may be from the true surface (declared
    with the file; the checks verify it against the spec's surfaces): one
    distance for the whole mesh, as a file's export tolerance is, or one for
    each of its triangles (a test's reference mesh, honest about a thread's
    twisted facets and the rest apart). ``deflection`` is then the most of
    them, and ``deflections`` each.
    """

    capabilities: frozenset[Capability] = frozenset(
        {
            Capability.CLASSIFY,
            Capability.CROSSINGS,
            Capability.DISTANCE,
            Capability.VOLUME,
            Capability.COVERAGE,
            Capability.TOPOLOGY,
        }
    )

    def __init__(
        self,
        mesh: Mesh,
        *,
        source: str,
        deflection: float | Array,
        shape: MeshShape | None = None,
    ) -> None:
        each = np.asarray(deflection, dtype=np.float64)
        if each.ndim and each.shape != (len(mesh.faces),):
            raise ValueError("a mesh's deflections must be one for each triangle")
        if not (np.all(np.isfinite(each)) and np.all(each >= 0.0)):
            raise ValueError("a mesh's deflection must be finite and not negative")
        if shape is not None and shape.mesh is not mesh:
            raise ValueError("a shared shape must be the same mesh's")
        self.shape = shape if shape is not None else MeshShape(mesh)
        self.source = source
        self.deflections: Array | None = each if each.ndim else None
        self.deflection = float(each.max(initial=0.0))

    @property
    def mesh(self) -> Mesh:
        return self.shape.mesh

    def with_deflection(self, deflection: float | Array) -> MeshView:
        """The same mesh, said to be within ``deflection`` of the true surface (or each triangle within its own)."""
        return MeshView(
            self.mesh, source=self.source, deflection=deflection, shape=self.shape
        )

    def topology(self) -> Topology:
        return self.shape.topology()

    def classify(self, points: Array) -> NDArray[np.int8]:
        return self.shape.classify(points)

    def distance(self, points: Array) -> Array:
        return self.shape.distance(points)

    def near(self, points: Array, tolerances: Array) -> NDArray[np.bool_]:
        return self.shape.near(points, tolerances)

    def crossings(self, origins: Array, directions: Array) -> Crossings:
        return self.shape.crossings(origins, directions)

    def volume(self) -> Interval:
        """The volume of the part the mesh stands for: the mesh's own, widened by its deflection over its area.

        The true surface is within the deflection of the mesh's, so the space
        between them is no more than that over the area.
        """
        own = self.shape.volume()
        if not (math.isfinite(own.lo) and math.isfinite(own.hi)) or not self.deflection:
            return own
        band = (
            self.deflection * self.shape.area()
            if self.deflections is None
            else self.shape.area(self.deflections)
        )
        return Interval(own.lo - band, own.hi + band)

    def bounds(self) -> Box:
        return self.shape.bounds()

    def coverage(self, radius: float, within: Box | None = None) -> Coverage:
        each = self.deflection if self.deflections is None else self.deflections
        return self.shape.coverage(radius, each, within)

    def faces(self) -> tuple[FaceFacts, ...]:
        raise NotImplementedError("a mesh has no faces, only triangles")

    def edges(self) -> tuple[EdgeFacts, ...]:
        raise NotImplementedError("a mesh has no edges as curves")


# --- coverage -------------------------------------------------------------------------


def _first_of_each(points: Array) -> Index:
    """The index of the first of each set of exactly equal rows, in order."""
    ranked = np.lexsort((points[:, 2], points[:, 1], points[:, 0]))
    new = np.ones(len(ranked), dtype=bool)
    new[1:] = (points[ranked][1:] != points[ranked][:-1]).any(axis=1)
    # Of equal rows, the lexsort (stable) puts the earliest first.
    return np.sort(ranked[new])


def _regions(weights: Array) -> NDArray[np.int8]:
    """Which feature of its triangle each point lies on, from its exact weights on the corners."""
    zero = weights == 0.0
    region = np.full(len(weights), FACE, dtype=np.int8)
    for k in range(3):
        region[~zero[:, k] & zero[:, (k + 1) % 3] & zero[:, (k + 2) % 3]] = (
            k  # VERTEX_A, _B, _C
        )
    for code, missing in ((EDGE_AB, 2), (EDGE_BC, 0), (EDGE_CA, 1)):
        region[(zero.sum(axis=1) == 1) & zero[:, missing]] = code
    return region


def _cover(
    shape: MeshShape,
    radius: float,
    deflection: float | Array,
    within: Box | None = None,
) -> Coverage:
    """Points on every good triangle (or near the box ``within``: the pieces of the triangles that meet it, :func:`_clipped`), every point of them within ``radius`` of one; each as far off the true surface as its triangle may be (``deflection``: the mesh's, or each triangle's).

    Each triangle is covered by rows of points parallel to its longest side,
    the first row that side itself: ``g`` apart, each row's points at most
    ``s`` apart from end to end of the row. The angles at the longest side's
    ends are not obtuse, so the triangle narrows from that side to its apex
    and each row is no shorter than the triangle anywhere above it: every
    point of the triangle is within ``g`` of the row below it (or within the
    triangle's height of the first), over that row, and so within
    ``sqrt(g² + (s/2)²)`` of a point. With ``g = r/√2`` and ``s = √2 r`` that
    is the radius ``r``, as few points as rows can make it, and a needle
    (a triangle no higher than ``g``, as exporters make many of) takes one row
    along its side. Each triangle's own side middles and centre are kept too.
    """
    good = np.flatnonzero(shape._good)
    if not good.size:
        raise ValueError("a mesh with no good triangle has no surface to cover")
    each = np.asarray(deflection, dtype=np.float64)
    corners = shape._corners
    pieces: tuple[Index, Array] | None = None
    if within is not None:
        a, b, c = (x[good] for x in corners)
        lo, hi = np.minimum(np.minimum(a, b), c), np.maximum(np.maximum(a, b), c)
        meets = np.all(lo <= np.asarray(within.hi), axis=1) & np.all(
            hi >= np.asarray(within.lo), axis=1
        )
        good = good[meets]
        if not good.size:
            empty = np.zeros((0, 3))
            return Coverage(
                empty, empty, np.zeros(0, dtype=np.int64), np.zeros(0), float(radius)
            )
        pieces = _clipped(corners, good, within, radius)
    # A sample's position is a weighted sum of corners, and a triangle's sides
    # and height are worked out from them: each rounded by a few units in the
    # last place of the corners' size. The rows are made that much closer, and
    # the radius stated that much larger, so it is a true bound.
    slack = 64.0 * 2.0**-53 * shape._reach
    if radius <= 4.0 * slack:
        raise ValueError(
            f"a coverage radius of {radius} mm is below rounding at this size"
        )
    reach = (radius - slack) * (1.0 - 1e-12)
    gap, spacing = reach / math.sqrt(2.0), reach * math.sqrt(2.0)
    weights: list[Array] = []
    owners: list[Index] = []
    own = np.array(
        [[0.5, 0.5, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [1 / 3, 1 / 3, 1 / 3]],
        dtype=np.float64,
    )
    weights.append(np.tile(own, (len(good), 1)))
    owners.append(np.repeat(good, len(own)))
    reached = 0.0
    if pieces is None:
        for begin in range(0, len(good), _PIECES):
            batch = good[begin : begin + _PIECES]
            found, reached_here = _rows(corners, batch, gap, spacing)
            if found is not None:
                weights.append(found[0])
                owners.append(found[1])
            reached = max(reached, reached_here)
    else:
        whose, shares = pieces
        for begin in range(0, len(whose), _PIECES):
            batch, share = (
                whose[begin : begin + _PIECES],
                shares[begin : begin + _PIECES],
            )
            a, b, c = (
                fv.matmul(share[:, k][:, None, :], _stacked(corners, batch))[:, 0]
                for k in range(3)
            )
            on_pieces, reached_here = _rows_of(a, b, c, gap, spacing)
            if on_pieces is not None:
                w, piece = on_pieces
                # Weights on the piece's corners, as weights on its triangle's: exact zeros stay zeros.
                weights.append(fv.matmul(w[:, None, :], share[piece])[:, 0])
                owners.append(batch[piece])
            reached = max(reached, reached_here)
    weight = np.concatenate(weights)
    owner = np.concatenate(owners)
    a, b, c = (x[owner] for x in corners)
    points = weight[:, :1] * a + weight[:, 1:2] * b + weight[:, 2:] * c
    keep = _first_of_each(points)
    points, weight, owner = points[keep], weight[keep], owner[keep]
    normal, _ = shape._feature_normal(owner, _regions(weight))
    # Where an edge or a corner has no outward direction of its own (a
    # knife-edge), the face's normal stands in: no point is dropped.
    length = _norms(normal)
    flat = length < 0.5
    normal[flat] = shape._normals[owner[flat]]
    normal /= _norms(normal)[:, None]
    return Coverage(
        points=points,
        normals=normal,
        patch=owner.astype(np.int64),
        tolerance=each[owner] if each.ndim else np.full(len(points), float(each)),
        radius=reached * (1.0 + 1e-12) + slack,
    )


#: How many times :func:`_clipped` may split a triangle in four looking for a box.
_SPLITS = 40


def _stacked(corners: tuple[Array, Array, Array], faces: Index) -> Array:
    """The triangles' corners, (n, 3 corners, 3)."""
    return np.stack([x[faces] for x in corners], axis=1)


def _clipped(
    corners: tuple[Array, Array, Array], faces: Index, box: Box, radius: float
) -> tuple[Index, Array]:
    """The triangles near a box, in pieces: each split in four (at its sides' middles) until its pieces are no wider than a quarter of the box (or four radii), the pieces whose own box misses it dropped (no point of them is in it).

    Each piece's triangle, and its corners as weights on the triangle's
    corners (n, 3, 3): a triangle no wider than that is its own one piece.
    """
    lo, hi = np.asarray(box.lo), np.asarray(box.hi)
    enough = max(max(box.size) / 4.0, 4.0 * radius)
    whose = np.asarray(faces, dtype=np.int64)
    shares = np.broadcast_to(np.eye(3), (len(whose), 3, 3)).copy()
    done: list[tuple[Index, Array]] = []
    for _ in range(_SPLITS):
        if not len(whose):
            break
        at = fv.matmul(shares, _stacked(corners, whose))
        meets = np.all(at.min(axis=1) <= hi, axis=1) & np.all(
            at.max(axis=1) >= lo, axis=1
        )
        whose, shares, at = whose[meets], shares[meets], at[meets]
        sides = fv.norm(at - np.roll(at, 1, axis=1), axis=2).max(axis=1)
        small = sides <= enough
        done.append((whose[small], shares[small]))
        whose, shares = whose[~small], shares[~small]
        w0, w1, w2 = shares[:, 0], shares[:, 1], shares[:, 2]
        m01, m12, m20 = (w0 + w1) / 2.0, (w1 + w2) / 2.0, (w2 + w0) / 2.0
        quarters = [(w0, m01, m20), (m01, w1, m12), (m20, m12, w2), (m01, m12, m20)]
        shares = np.concatenate([np.stack(q, axis=1) for q in quarters])
        whose = np.tile(whose, 4)
    done.append((whose, shares))
    return np.concatenate([d[0] for d in done]), np.concatenate([d[1] for d in done])


def _rows(
    corners: tuple[Array, Array, Array], faces: Index, gap: float, spacing: float
) -> tuple[tuple[Array, Index] | None, float]:
    """The rows of points covering some triangles (see :func:`_cover`), as weights on their corners and the triangles they are on; and the radius they reach."""
    a, b, c = (x[faces] for x in corners)
    found, reached = _rows_of(a, b, c, gap, spacing)
    return ((found[0], faces[found[1]]) if found is not None else None), reached


def _rows_of(
    a: Array, b: Array, c: Array, gap: float, spacing: float
) -> tuple[tuple[Array, Index] | None, float]:
    """The rows of points covering triangles with these corners (see :func:`_cover`), as weights on their corners and which triangle each is on; and the radius they reach."""
    faces = np.arange(len(a))
    sides = np.stack([_norms(b - a), _norms(c - b), _norms(a - c)], axis=1)
    k = np.argmax(sides, axis=1)
    length = sides[np.arange(len(faces)), k]
    height = _norms(np.asarray(np.cross(b - a, c - a), dtype=np.float64)) / np.where(
        length > 0, length, 1.0
    )
    # Rows j = 0 .. J at heights j g (J g within the height), each from the side running up from
    # the longest side's first end to the one from its second.
    rows = np.floor(height / gap).astype(np.int64) + 1
    rows = np.where(length > 0, rows, 1)
    tri = np.repeat(np.arange(len(faces)), rows)
    j = np.arange(len(tri)) - np.repeat(np.cumsum(rows) - rows, rows)
    up = np.where(
        height[tri] > 0,
        np.minimum(j * gap / np.where(height[tri] > 0, height[tri], 1.0), 1.0),
        0.0,
    )
    width = length[tri] * (1.0 - up)
    count = np.maximum(np.ceil(width / spacing).astype(np.int64), 1)
    reach_rows = np.sqrt(
        fv.sq(np.minimum(gap, height[tri])) + fv.sq(width / (2 * count))
    )
    reached = float(reach_rows.max(initial=0.0))
    row = np.repeat(np.arange(len(tri)), count + 1)
    along = (
        np.arange(len(row)) - np.repeat(np.cumsum(count + 1) - (count + 1), count + 1)
    ) / count[row]
    first = k[tri][row]
    second = (first + 1) % 3
    apex = (first + 2) % 3
    t = up[row]
    w = np.zeros((len(row), 3))
    n = np.arange(len(row))
    # On the row at height t: (1 - along) of the way from the first end's side and along of the
    # second's: exact zeros on the triangle's sides, so each point's feature is known.
    w[n, first] = (1.0 - along) * (1.0 - t)
    w[n, second] = along * (1.0 - t)
    w[n, apex] = t
    return ((w, faces[tri][row]) if len(row) else None), reached
