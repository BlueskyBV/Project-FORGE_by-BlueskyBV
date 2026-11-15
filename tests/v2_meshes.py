"""Meshes for testing the checks: made with manifold3d, which Forge itself never uses.

manifold3d (Apache-2.0) makes closed, consistently oriented meshes from
booleans of simple solids; the tests use it to make reference parts whose
answers are known, and then damage them on purpose. Each helper returns a
triangle list ``(n, 3, 3)`` (float64) or a :class:`~forge_checks.mesh.MeshView`.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
from forge_checks.mesh import Mesh, MeshView
from numpy.typing import NDArray

HAVE_MANIFOLD = importlib.util.find_spec("manifold3d") is not None

Triangles = NDArray[np.float64]


def exported(solid: Any) -> tuple[Triangles, NDArray[np.int64]]:
    """A manifold3d solid's vertices and its triangles' corners, in the double precision it works in.

    Its single-precision mesh (``to_mesh``) rounds every coordinate to about
    seven figures, which can bring two of its vertices a few nanometres
    apart (where solids met in one plane, as a block overhanging a face
    meets it) onto one point, and leave triangles with no area.
    """
    mesh = solid.to_mesh64()
    vertices = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    return vertices, np.asarray(mesh.tri_verts, dtype=np.int64)


def origins(solid: Any) -> NDArray[np.int64]:
    """Which solid each of a manifold3d solid's triangles came from (the ``original_id`` the library gave it when made), in :func:`exported`'s order."""
    mesh = solid.to_mesh64()
    runs = np.diff(np.asarray(mesh.run_index, dtype=np.int64) // 3)
    ids = np.asarray(mesh.run_original_id, dtype=np.int64)
    assert len(runs) == len(ids), "a run of triangles for each solid they came from"
    return np.repeat(ids, runs)


def triangles(solid: Any) -> Triangles:
    """A manifold3d solid's triangles, corners as it has them."""
    vertices, faces = exported(solid)
    return np.asarray(vertices[faces], dtype=np.float64)


def view(soup: Triangles, deflection: float = 0.0) -> MeshView:
    return MeshView(
        Mesh.from_triangles(soup), source="mesh-file", deflection=deflection
    )


def nearest_within(points: Triangles, queries: Triangles, radius: float) -> Triangles:
    """Each query's distance to the nearest of ``points``, or inf if none is within ``radius``.

    Independent of Forge's own search: points binned in cubes of side
    ``radius``, and each query looks in the 27 cubes around its own.
    """
    key = np.floor(points / radius).astype(np.int64)
    order = np.lexsort((key[:, 2], key[:, 1], key[:, 0]))
    key, points = key[order], points[order]
    base = key.min(axis=0) - 2
    span = key.max(axis=0) - base + 3
    code = ((key[:, 0] - base[0]) * span[1] + (key[:, 1] - base[1])) * span[2] + (
        key[:, 2] - base[2]
    )
    best = np.full(len(queries), np.inf)
    home = np.floor(queries / radius).astype(np.int64)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                cell = home + np.array([dx, dy, dz])
                inside = ((cell - base >= 0) & (cell - base < span)).all(axis=1)
                want = (
                    (cell[:, 0] - base[0]) * span[1] + (cell[:, 1] - base[1])
                ) * span[2] + (cell[:, 2] - base[2])
                lo = np.searchsorted(code, want, side="left")
                hi = np.searchsorted(code, want, side="right")
                count = np.where(inside, hi - lo, 0)
                who = np.repeat(np.arange(len(queries)), count)
                first = np.cumsum(count) - count
                at = (
                    np.repeat(lo, count)
                    + np.arange(int(count.sum()))
                    - np.repeat(first, count)
                )
                gap = np.linalg.norm(points[at] - queries[who], axis=1)
                np.minimum.at(best, who, gap)
    best[best > radius] = np.inf
    return best


def box_soup(
    lo: tuple[float, float, float], hi: tuple[float, float, float]
) -> Triangles:
    from forge_checks.mesh import box_mesh

    mesh = box_mesh(lo, hi)
    return np.asarray(mesh.vertices[mesh.faces], dtype=np.float64)


def shapes() -> dict[str, Any]:
    """Named reference solids, each with what is known about it."""
    import manifold3d as m3

    cube = m3.Manifold.cube
    cyl = m3.Manifold.cylinder
    hollow = cube((20, 20, 20)) - cube((10, 10, 10)).translate((5, 5, 5))
    return {
        "box": cube((10, 20, 30)),
        "ball": m3.Manifold.sphere(5, 48),
        "rod": cyl(20, 4, 4, 40),
        "cone": cyl(10, 5, 1, 32),
        "ring": cube((20, 20, 5)) - cyl(5, 4, 4, 40).translate((10, 10, 0)),
        "two holes": cube((30, 12, 4))
        - cyl(4, 3, 3, 24).translate((8, 6, 0))
        - cyl(4, 3, 3, 24).translate((22, 6, 0)),
        "three holes": cube((40, 12, 4))
        - cyl(4, 3, 3, 24).translate((8, 6, 0))
        - cyl(4, 3, 3, 24).translate((20, 6, 0))
        - cyl(4, 3, 3, 24).translate((32, 6, 0)),
        "hollow": hollow,
        "island": hollow + cube((4, 4, 4)).translate((8, 8, 8)),
        "two": cube((5, 5, 5)) + cube((5, 5, 5)).translate((10, 0, 0)),
        "torus": m3.Manifold.revolve(
            m3.CrossSection.circle(2, 24).translate((6, 0)), 48
        ),
        "bracket": (
            cube((40, 30, 4))
            + cube((4, 30, 25))
            - cyl(10, 2.5, 2.5, 24).translate((20, 15, -1))
            - cube((6, 6, 3)).translate((30, 5, 2.01))
        ),
    }


#: Each reference shape's solids, voids and genus (through-holes per solid).
KNOWN = {
    "box": (1, 0, (0,)),
    "ball": (1, 0, (0,)),
    "rod": (1, 0, (0,)),
    "cone": (1, 0, (0,)),
    "ring": (1, 0, (1,)),
    "two holes": (1, 0, (2,)),
    "three holes": (1, 0, (3,)),
    "hollow": (1, 1, (0,)),
    "island": (2, 1, (0, 0)),
    "two": (2, 0, (0, 0)),
    "torus": (1, 0, (1,)),
    "bracket": (1, 0, (1,)),
}
