"""A tree of boxes over a mesh's triangles: what every search through the mesh walks.

Each node's box holds whole the boxes of all the triangles under it, so a
triangle is found from anywhere it reaches, however large it is: a long CAD
triangle is never missed because its centre is far away. The tree is built by
halving: a node's triangles are sorted along the longest spread of their box
centres and split at the middle one, until a node holds at most :data:`LEAF`
(triangles all with one centre, as in a corrupt file of zeros, are halved by
number).
Halving by count, not by space, keeps the tree shallow where a mesh is dense
(a thread's flanks) and coarse where it is sparse (a plate's flat faces).

Searches go down the tree for many points or rays at once, as a frontier of
(query, node) pairs, so NumPy does the work:

- :meth:`Tree.nearest`: each point's nearest triangle, exactly: a first guess
  by walking down to the nearer child, then every node that could hold
  something nearer;
- :meth:`Tree.within`: every triangle whose box is within a given distance
  of a point (what the mesh view uses to find near-ties);
- :meth:`Tree.along`: every triangle whose box a ray passes through or
  touches (boxes are widened a little first, so rounding never loses one);
- :meth:`Tree.touching`: every pair of triangles whose boxes touch.

The last two hand their pairs on in batches, so a million-triangle mesh never
needs them all in memory at once.

>>> import numpy as np
>>> corners = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[5, 0, 0], [6, 0, 0], [5, 1, 0]]], float)
>>> tree = Tree.build(corners.min(axis=1), corners.max(axis=1))
>>> from forge_checks.triangles import unit_normals
>>> a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
>>> found = tree.nearest(np.array([[5.2, 0.2, 2.0]]), a, b, c, unit_normals(a, b, c))
>>> found.triangle.tolist(), found.distance.tolist()
([1], [2.0])
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
from forge_numeric import vector as fv
from numpy.typing import NDArray

from .triangles import closest_points

__all__ = ["FEW", "LEAF", "Nearest", "Tree"]

#: The most triangles a leaf holds.
LEAF = 4
#: Queries searched together: enough for NumPy, few enough for memory.
_BATCH = 16384
#: (point, node) pairs opened at a time in the nearest search.
_OPEN = 16384
#: The most (point, node) pairs a nearest search keeps waiting before it
#: splits its points in two.
_POOL = 1 << 21
#: Rays walked together.
_RAYS = 2048
#: Candidate pairs handed on at a time.
_PAIRS = 1 << 20
#: So few boxes that every point is tried against each in turn, sooner than a walk down the tree (a part's steps).
FEW = 32

Array = NDArray[np.float64]
Index = NDArray[np.int64]


def _ranges(start: Index, count: Index) -> tuple[Index, Index]:
    """Every index in ``[start[i], start[i] + count[i])``, and which ``i`` it came from."""
    owner = np.repeat(np.arange(len(start), dtype=np.int64), count)
    first = np.cumsum(count) - count
    offset = np.arange(int(count.sum()), dtype=np.int64) - np.repeat(first, count)
    return np.repeat(start, count) + offset, owner


def _segment_reduce(
    values: Array, start: Index, end: Index, size: int
) -> tuple[Array, Array]:
    """The least and greatest row of ``values`` within each disjoint range ``[start, end)``."""
    cuts = np.unique(np.concatenate([start, end[end < size]]))
    least = np.minimum.reduceat(values, cuts, axis=0)
    most = np.maximum.reduceat(values, cuts, axis=0)
    at = np.searchsorted(cuts, start)
    return least[at], most[at]


@dataclass(frozen=True, eq=False)
class Nearest:
    """Each query point's nearest triangle, the point on it, and the feature it is on."""

    distance: Array
    triangle: Index
    point: Array
    region: NDArray[np.int8]


class _Search:
    """One nearest search: each point's best so far, and how to better it."""

    def __init__(
        self, points: Array, corners: tuple[Array, Array, Array, Array], tree: Tree
    ) -> None:
        self.points, self.corners, self.tree = points, corners, tree
        n = len(points)
        self.best = np.full(n, np.inf)
        self.triangle = np.full(n, -1, dtype=np.int64)
        self.point = np.full((n, 3), np.nan)
        self.region = np.full(n, -1, dtype=np.int8)

    def visit(self, query: Index, leaves: Index) -> None:
        """Measure each query against every triangle of its leaf; keep the nearer."""
        tree = self.tree
        where, owner = _ranges(tree.start[leaves], tree.count[leaves])
        tri = tree.order[where]
        who = query[owner]
        # A triangle whose own box is farther than the best so far can't be nearer.
        here = self.points[who]
        gap = np.maximum(
            np.maximum(tree.box_lo[tri] - here, here - tree.box_hi[tri]), 0.0
        )
        close = fv.dot(gap, gap) <= self.best[who] * (1.0 + 1e-9)
        tri, who, here = tri[close], who[close], here[close]
        if not tri.size:
            return
        a, b, c, normal = self.corners
        q, r = closest_points(here, a[tri], b[tri], c[tri], normal[tri])
        gap = here - q
        d2 = fv.dot(gap, gap)
        # The nearest per query, the lowest-numbered triangle on a tie.
        names, slot = np.unique(who, return_inverse=True)
        least = np.full(len(names), np.inf)
        np.minimum.at(least, slot, d2)
        tied = d2 == least[slot]
        first = np.full(len(names), np.iinfo(np.int64).max)
        np.minimum.at(first, slot[tied], tri[tied])
        pick = np.flatnonzero(tied & (tri == first[slot]))
        winner = who[pick]
        nearer = d2[pick] < self.best[winner]
        winner, pick = winner[nearer], pick[nearer]
        self.best[winner] = d2[pick]
        self.triangle[winner] = tri[pick]
        self.point[winner] = q[pick]
        self.region[winner] = r[pick]

    def run(self, rows: Index) -> None:
        tree, points = self.tree, self.points
        # A first guess: down to the nearer child, to a leaf.
        node: Index = np.zeros(len(rows), dtype=np.int64)
        while True:
            inner = np.flatnonzero(tree.left[node] >= 0)
            if not inner.size:
                break
            left, right = tree.left[node[inner]], tree.right[node[inner]]
            here = points[rows[inner]]
            nearer_left = tree._box_distance2(here, left) <= tree._box_distance2(
                here, right
            )
            node[inner] = np.where(nearer_left, left, right)
        self.visit(rows, node)
        # Then every node whose box could hold something nearer, nearest first.
        query: Index = rows
        node = np.zeros(len(rows), dtype=np.int64)
        bound = tree._box_distance2(points[query], node)
        while query.size:
            keep = bound <= self.best[query] * (1.0 + 1e-9)
            query, node, bound = query[keep], node[keep], bound[keep]
            if not query.size:
                break
            if query.size > _OPEN:
                now = np.argpartition(bound, _OPEN)[:_OPEN]
                later = np.ones(query.size, dtype=bool)
                later[now] = False
                q, nd = query[now], node[now]
                query, node, bound = query[later], node[later], bound[later]
            else:
                q, nd = query, node
                query, node, bound = query[:0], node[:0], bound[:0]
            leaf = tree.left[nd] < 0
            if leaf.any():
                self.visit(q[leaf], nd[leaf])
            q, nd = q[~leaf], nd[~leaf]
            q = np.concatenate([q, q])
            nd = np.concatenate([tree.left[nd], tree.right[nd]])
            query = np.concatenate([query, q])
            node = np.concatenate([node, nd])
            bound = np.concatenate([bound, tree._box_distance2(points[q], nd)])
            if query.size > _POOL and len(rows) > 1:
                # A crowd of near ties: finish half the points at a time. What
                # is found so far stands; each half starts again from the root.
                half = len(rows) // 2
                self.run(rows[:half])
                self.run(rows[half:])
                return


@dataclass(frozen=True, eq=False)
class Tree:
    """The nodes, as arrays: node 0 is the root; a leaf has no children (-1)."""

    lo: Array
    hi: Array
    left: Index
    right: Index
    start: Index
    count: Index
    #: The triangles, in the order the leaves' ranges index.
    order: Index
    #: Each triangle's own box.
    box_lo: Array
    box_hi: Array

    @classmethod
    def build(cls, lo: Array, hi: Array) -> Tree:
        """The tree over boxes ``lo``, ``hi`` (one row per triangle; none may be NaN)."""
        size = len(lo)
        centre = (lo + hi) * 0.5
        order = np.arange(size, dtype=np.int64)
        node_lo: list[Array] = []
        node_hi: list[Array] = []
        node_left: list[Index] = []
        node_right: list[Index] = []
        node_start: list[Index] = []
        node_count: list[Index] = []
        start = np.array([0], dtype=np.int64)
        end = np.array([size], dtype=np.int64)
        made = 1
        while start.size:
            box_lo, _ = _segment_reduce(lo[order], start, end, size)
            _, box_hi = _segment_reduce(hi[order], start, end, size)
            c_lo, c_hi = _segment_reduce(centre[order], start, end, size)
            spread = c_hi - c_lo
            count = end - start
            # Boxes all with one centre are halved by number alone: no leaf grows past LEAF.
            split = count > LEAF
            children = np.full(len(start), -1, dtype=np.int64)
            parents = np.flatnonzero(split)
            children[parents] = made + 2 * np.arange(len(parents), dtype=np.int64)
            made += 2 * len(parents)
            node_lo.append(box_lo)
            node_hi.append(box_hi)
            node_left.append(children)
            node_right.append(np.where(children >= 0, children + 1, -1))
            node_start.append(start)
            node_count.append(count)
            if not len(parents):
                break
            s, e = start[parents], end[parents]
            axis = np.argmax(spread[parents], axis=1)
            where, owner = _ranges(s, e - s)
            key = centre[order[where], axis[owner]]
            ranked = np.lexsort((order[where], key, owner))
            order[where] = order[where[ranked]]
            middle = (s + e) // 2
            start = np.stack([s, middle], axis=1).reshape(-1)
            end = np.stack([middle, e], axis=1).reshape(-1)
        return cls(
            lo=np.concatenate(node_lo),
            hi=np.concatenate(node_hi),
            left=np.concatenate(node_left),
            right=np.concatenate(node_right),
            start=np.concatenate(node_start),
            count=np.concatenate(node_count),
            order=order,
            box_lo=lo,
            box_hi=hi,
        )

    def _box_distance2(self, points: Array, nodes: Index) -> Array:
        gap = np.maximum(
            np.maximum(self.lo[nodes] - points, points - self.hi[nodes]), 0.0
        )
        return np.asarray(fv.dot(gap, gap), dtype=np.float64)

    def nearest(
        self, points: Array, a: Array, b: Array, c: Array, normal: Array
    ) -> Nearest:
        """Each point's nearest triangle (corners ``a``, ``b``, ``c``, unit ``normal``).

        A first guess walks each point down to the nearer child at every level.
        Then the (point, node) pairs that could still hold something nearer are
        opened nearest first, :data:`_OPEN` at a time, so each point's best so
        far shrinks before far-off nodes are reached, and the pairs waiting are
        never more than the points times a few.
        """
        search = _Search(points, (a, b, c, normal), self)
        for first in range(0, len(points), _BATCH):
            rows = np.arange(first, min(len(points), first + _BATCH), dtype=np.int64)
            search.run(rows)
        return Nearest(
            np.sqrt(search.best), search.triangle, search.point, search.region
        )

    def near(
        self,
        points: Array,
        tolerances: Array,
        a: Array,
        b: Array,
        c: Array,
        normal: Array,
    ) -> NDArray[np.bool_]:
        """Whether each point has a triangle within its tolerance: :meth:`nearest`'s distance ``<= tolerances``, exactly.

        Each triangle whose box is within the tolerance (:meth:`within`) is
        measured as :meth:`nearest` measures it, with the same rounding, so
        the answer is the nearest's; a point is asked no more once one is
        near enough. No best so far is kept, and nothing past the tolerance
        is searched: on a part's spec side, 2.3 times as fast (generated part
        30's STL, a million points: 21 s against 50).
        """
        out = np.zeros(len(points), dtype=bool)
        # Boxes are compared squared: a little wider, so that rounding leaves out no triangle the measure takes.
        reach = tolerances * (1.0 + 1e-9) + 1e-12
        for who, tri in self.within(points, reach):
            left = ~out[who]
            who, tri = who[left], tri[left]
            if not len(who):
                continue
            q, _ = closest_points(points[who], a[tri], b[tri], c[tri], normal[tri])
            gap = points[who] - q
            near = np.sqrt(fv.dot(gap, gap)) <= tolerances[who]
            out[who[near]] = True
        return out

    def within(self, points: Array, radius: Array) -> Iterator[tuple[Index, Index]]:
        """Every (point, triangle) pair whose triangle's box is within each point's ``radius``, in batches.

        The (point, node) pairs are walked depth first, at most :data:`_OPEN`
        at a time, so that a crowd of near ties (a point at the centre of a
        sphere is near every facet's box) stays bounded in memory.
        """
        if len(self.box_lo) <= FEW:
            yield from self._within_few(points, radius)
            return
        step = _PAIRS // (8 * LEAF)
        for first in range(0, len(points), _BATCH):
            rows = np.arange(first, min(len(points), first + _BATCH), dtype=np.int64)
            waiting: list[tuple[Index, Index]] = [
                (rows, np.zeros(len(rows), dtype=np.int64))
            ]
            while waiting:
                query, node = waiting.pop()
                if len(query) > _OPEN:
                    half = len(query) // 2
                    waiting += [
                        (query[half:], node[half:]),
                        (query[:half], node[:half]),
                    ]
                    continue
                keep = (
                    self._box_distance2(points[query], node)
                    <= radius[query] * radius[query]
                )
                query, node = query[keep], node[keep]
                leaf = self.left[node] < 0
                lq, ln = query[leaf], node[leaf]
                for part in range(0, len(lq), step):
                    where, owner = _ranges(self.start[ln[part : part + step]],
                                           self.count[ln[part : part + step]])  # fmt: skip
                    who, tri = lq[part : part + step][owner], self.order[where]
                    here = points[who]
                    gap = np.maximum(
                        np.maximum(self.box_lo[tri] - here, here - self.box_hi[tri]),
                        0.0,
                    )
                    close = fv.dot(gap, gap) <= radius[who] * radius[who]
                    yield who[close], tri[close]
                query, node = query[~leaf], node[~leaf]
                if query.size:
                    children = np.concatenate([self.left[node], self.right[node]])
                    waiting.append((np.concatenate([query, query]), children))

    def _within_few(
        self, points: Array, radius: Array
    ) -> Iterator[tuple[Index, Index]]:
        """:meth:`within` for a tree of :data:`FEW` boxes or fewer: each batch of points against each box."""
        for first in range(0, len(points), _BATCH):
            here = points[first : first + _BATCH]
            reach = fv.sq(radius[first : first + _BATCH])
            for k in range(len(self.box_lo)):
                gap = np.maximum(
                    np.maximum(self.box_lo[k] - here, here - self.box_hi[k]), 0.0
                )
                close = np.flatnonzero(fv.dot(gap, gap) <= reach)
                if len(close):
                    yield close + first, np.full(len(close), k, dtype=np.int64)

    def along(
        self,
        origins: Array,
        directions: Array,
        pad: float,
        lengths: Array | None = None,
    ) -> Iterator[tuple[Index, Index]]:
        """Every (ray, triangle) pair whose box the ray reaches ahead of its origin, in batches.

        Boxes are widened by ``pad`` on every side first, so that rounding in the
        slab test never loses a triangle the ray touches. With ``lengths``, each
        ray is a segment that long: a box it reaches only beyond its end is left
        out.
        """
        reach = (
            np.full(len(origins), np.inf)
            if lengths is None
            else np.asarray(lengths, dtype=float) + pad
        )
        lo, hi = self.lo - pad, self.hi + pad
        for first in range(0, len(origins), _RAYS):
            rays: list[Index] = []
            tris: list[Index] = []
            held = 0
            query: Index = np.arange(
                first, min(len(origins), first + _RAYS), dtype=np.int64
            )
            node: Index = np.zeros(len(query), dtype=np.int64)
            while query.size:
                o, d = origins[query], directions[query]
                box_lo, box_hi = lo[node], hi[node]
                with np.errstate(divide="ignore", invalid="ignore"):
                    t1 = (box_lo - o) / d
                    t2 = (box_hi - o) / d
                flat = d == 0.0
                within = (box_lo <= o) & (o <= box_hi)
                near = np.where(
                    flat, np.where(within, -np.inf, np.inf), np.minimum(t1, t2)
                )
                far = np.where(
                    flat, np.where(within, np.inf, -np.inf), np.maximum(t1, t2)
                )
                enter = near.max(axis=1)
                leave = far.min(axis=1)
                keep = (leave >= enter) & (leave >= 0.0) & (enter <= reach[query])
                query, node = query[keep], node[keep]
                leaf = self.left[node] < 0
                if leaf.any():
                    where, owner = _ranges(
                        self.start[node[leaf]], self.count[node[leaf]]
                    )
                    rays.append(query[leaf][owner])
                    tris.append(self.order[where])
                    held += len(where)
                    if held >= _PAIRS:
                        yield np.concatenate(rays), np.concatenate(tris)
                        rays, tris, held = [], [], 0
                query, node = query[~leaf], node[~leaf]
                query = np.concatenate([query, query])
                node = np.concatenate([self.left[node], self.right[node]])
            if rays:
                yield np.concatenate(rays), np.concatenate(tris)

    def touching(self, lo: Array, hi: Array) -> Iterator[tuple[Index, Index]]:
        """Every pair ``i < j`` of triangles whose boxes ``lo``, ``hi`` touch or overlap, in batches."""
        one: Index = np.zeros(1, dtype=np.int64)
        other: Index = np.zeros(1, dtype=np.int64)
        while one.size:
            meet = np.all(
                (self.lo[one] <= self.hi[other]) & (self.lo[other] <= self.hi[one]),
                axis=1,
            )
            one, other = one[meet], other[meet]
            leaf_one, leaf_other = self.left[one] < 0, self.left[other] < 0
            both = np.flatnonzero(leaf_one & leaf_other)
            for start in range(0, len(both), _PAIRS // (LEAF * LEAF)):
                chosen = both[start : start + _PAIRS // (LEAF * LEAF)]
                i, j = self._leaf_pairs(one[chosen], other[chosen])
                close = np.all((lo[i] <= hi[j]) & (lo[j] <= hi[i]), axis=1)
                yield np.minimum(i, j)[close], np.maximum(i, j)[close]
            rest = ~(leaf_one & leaf_other)
            one, other = one[rest], other[rest]
            leaf_one, leaf_other = leaf_one[rest], leaf_other[rest]
            same = one == other
            # A node against itself: its children against themselves and each other.
            s = one[same]
            next_one = [self.left[s], self.left[s], self.right[s]]
            next_other = [self.left[s], self.right[s], self.right[s]]
            # Two nodes: open the one with more triangles (or the only one that opens).
            p, q = one[~same], other[~same]
            lp, lq = leaf_one[~same], leaf_other[~same]
            open_p = ~lp & (lq | (self.count[p] >= self.count[q]))
            fixed = np.where(open_p, q, p)
            opened = np.where(open_p, p, q)
            next_one += [self.left[opened], self.right[opened]]
            next_other += [fixed, fixed]
            one = np.concatenate(next_one)
            other = np.concatenate(next_other)

    def _leaf_pairs(self, one: Index, other: Index) -> tuple[Index, Index]:
        """The triangle pairs of each pair of leaves: within a leaf, each pair once."""
        ca, cb = self.count[one], self.count[other]
        total = ca * cb
        pair = np.repeat(np.arange(len(one), dtype=np.int64), total)
        first = np.cumsum(total) - total
        k = np.arange(int(total.sum()), dtype=np.int64) - np.repeat(first, total)
        x, y = k // cb[pair], k % cb[pair]
        i = self.order[self.start[one][pair] + x]
        j = self.order[self.start[other][pair] + y]
        keep = (one[pair] != other[pair]) | (x < y)
        return i[keep], j[keep]
