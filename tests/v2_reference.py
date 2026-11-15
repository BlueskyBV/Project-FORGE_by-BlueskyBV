"""Reference parts: each a spec, and the same part built by hand from the definitions with manifold3d.

The builders here are written from docs/definitions directly, item by item
(where each item goes, what it adds or takes away, in what order), and share
nothing with Forge's placement or oracle. Round surfaces are fine polygons
whose corners lie on the true surface, so a point farther from the mesh than
:data:`MARGIN` is on the same side of the true part as of the mesh.

Solids are never joined or cut exactly along a shared surface: manifold3d's
booleans are fragile there (a boss joined flush to a dome's flat face came
out with faces left in the joint). What joins overlaps a little into what it
joins, and a cut whose end is in air runs on past it through air: the same
solid either way. Each mesh's topology is checked against :data:`TOPOLOGY`.

Each part's spec is checked by the solver as any spec is (and its layout
compared with the judge's own, tests/v2_layouts.py).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from v2_specs import SAY, WORDS, a, n, pick

#: Corners round a full circle in every round solid.
SEGMENTS = 256
#: How far a round surface's polygon may be from it, for a radius of 50 mm: points nearer the mesh are left out.
MARGIN = 50 * (1 - math.cos(math.pi / SEGMENTS)) * 3 + 1e-6

Builder = Callable[[], Any]

#: The sizes of round surfaces in a spec: a diameter's half, or a radius.
_DIAMETERS = (
    "diameter",
    "outer_diameter",
    "inner_diameter",
    "base_diameter",
    "top_diameter",
)
#: A thread's twisted mesh: its triangles cut across the helix between its slices.
THREAD_DEFLECTION = 0.005
#: Letters' polygons: each curved piece cut into chords no farther than this from it (mm).
LETTER_CHORD = 1e-4


def deflection(items: list[dict[str, Any]]) -> float:
    """How far a reference part's mesh is from its true surface, honestly and with room.

    A round surface's polygon, 256-sided, strays r (1 - cos(pi / 256)) from
    it: three times that for the widest round surface the spec has (its
    diameters' halves and its radii, a pocket's corners' and counterbores'
    and countersinks' too, an outline's arcs' radii, and a revolution's
    reach from its axis: every point of its outline turns round it), and
    0.0002 mm for the corners where two round surfaces' facets cross; a
    thread's twisted mesh, :data:`THREAD_DEFLECTION`; letters' chords,
    :data:`LETTER_CHORD`. Face accounting holds each part's mesh to it
    (tests/test_v2_checks_accounting.py).
    """
    widest = 0.0

    def walk(value: Any, key: str = "") -> None:
        nonlocal widest
        if isinstance(value, dict):
            if "value" in value and value.get("unit") == "mm":
                if key in _DIAMETERS:
                    widest = max(widest, float(value["value"]) / 2)
                elif key in ("radius", "corner_radius"):
                    widest = max(widest, float(value["value"]))
                return
            for k, v in value.items():
                walk(v, k)

    for found in items:
        walk(found)
        profile = found.get("profile")
        if isinstance(profile, dict) and "segments" in profile:
            here = profile["start"]
            for seg in profile["segments"]:
                to = seg.get("line_to", seg.get("arc_to"))
                if "centre" in seg:
                    widest = max(widest, math.dist(here, seg["centre"]))
                here = to
            if found["kind"] == "revolution":
                widest = max(widest, *(abs(u) for u, _ in followed(profile)))
    least = THREAD_DEFLECTION if any(i["kind"] == "thread" for i in items) else 0.0
    if any(i["kind"] == "text" for i in items):
        least = max(least, LETTER_CHORD + 2e-4)
    return max(3 * widest * (1 - math.cos(math.pi / SEGMENTS)) + 2e-4, least)


def m3() -> Any:
    import manifold3d

    return manifold3d


def box(lo: tuple[float, float, float], hi: tuple[float, float, float]) -> Any:
    size = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    return m3().Manifold.cube(size).translate(lo)


def _placed(
    solid: Any, start: tuple[float, float, float], axis: tuple[float, float, float]
) -> Any:
    """A solid made along +z from the origin, turned so +z is ``axis`` and moved to ``start``."""
    w = np.asarray(axis, dtype=float)
    w /= np.linalg.norm(w)
    helper = np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, w)
    u /= np.linalg.norm(u)
    v = np.cross(w, u)
    matrix = np.column_stack([u, v, w, np.asarray(start, dtype=float)])
    return solid.transform(matrix)


def rod(
    start: tuple[float, float, float],
    axis: tuple[float, float, float],
    length: float,
    r: float,
    top: float | None = None,
) -> Any:
    """A cylinder (or a cone, to radius ``top``) from ``start`` along ``axis``."""
    made = m3().Manifold.cylinder(length, r, r if top is None else top, SEGMENTS)
    return _placed(made, start, axis)


def ball(centre: tuple[float, float, float], r: float) -> Any:
    return m3().Manifold.sphere(r, SEGMENTS).translate(centre)


#: How far a rounding's solid reaches past the faces it rounds into what is already air (or, filling, into
#: the material): the same solid, without booleans along a shared surface.
OVERLAP = 0.05


def corner(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    n1: tuple[float, float, float],
    n2: tuple[float, float, float],
    size: float,
    fillet: bool = True,
) -> Any:
    """What a rounding of a straight edge from ``p0`` to ``p1`` takes from its corner, or fills into it.

    The corner's region is on the side of both faces ``n1`` and ``n2`` point
    away from (the material, for an outside edge; the air, filling an inside
    one). A fillet: the square of its radius in the corner, less the ball's
    cylinder; a chamfer: the triangle of its size.
    """
    a0, a1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    along = (a1 - a0) / np.linalg.norm(a1 - a0)
    a0, a1 = a0 - OVERLAP * along, a1 + OVERLAP * along
    m1, m2 = np.asarray(n1, dtype=float), np.asarray(n2, dtype=float)
    e = OVERLAP
    if fillet:
        section = [
            e * m1 + e * m2,
            -size * m1 + e * m2,
            -size * m1 - size * m2,
            e * m1 - size * m2,
        ]
    else:
        section = [e * m1 + e * m2, -(size + e) * m1 + e * m2, e * m1 - (size + e) * m2]
    points = [tuple(a + q) for a in (a0, a1) for q in section]
    solid = m3().Manifold.hull_points(points)
    if fillet:
        c = a0 - size * m1 - size * m2 - along
        solid -= rod(tuple(c), tuple(along), float(np.linalg.norm(a1 - a0)) + 2, size)
    return solid


def turned(
    section: list[tuple[float, float]],
    centre: tuple[float, float, float],
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    first: tuple[float, float, float] | None = None,
    degrees: float = 360.0,
) -> Any:
    """A section in (distance from the axis, height) turned round ``axis`` at ``centre`` (from ``first``, by ``degrees``)."""
    w = np.asarray(axis, dtype=float)
    w /= np.linalg.norm(w)
    if first is None:
        helper = (
            np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        )
        u = np.cross(np.cross(w, helper), w)
    else:
        u = np.asarray(first, dtype=float)
    u /= np.linalg.norm(u)
    v = np.cross(w, u)
    lib = m3()
    made = lib.Manifold.revolve(lib.CrossSection([section]), SEGMENTS, degrees)
    matrix = np.column_stack([u, v, w, np.asarray(centre, dtype=float)])
    return made.transform(matrix)


def round_section(
    k: tuple[float, float], n1: tuple[float, float], n2: tuple[float, float], r: float
) -> list[tuple[float, float]]:
    """A fillet's section in a right-angled corner at ``k`` (the region away from ``n1`` and ``n2``), as a polygon.

    The square of the radius in the corner, out a little past the faces,
    less the ball's circle (its arc as many short sides).
    """
    k_, m1, m2 = (
        np.asarray(k, dtype=float),
        np.asarray(n1, dtype=float),
        np.asarray(n2, dtype=float),
    )
    c = k_ - r * m1 - r * m2
    t1, t2 = c + r * m1, c + r * m2
    e = OVERLAP
    points = [t1, t1 + e * m1, k_ + e * m1 + e * m2, t2 + e * m2, t2]
    start = math.atan2(*(t2 - c)[::-1])
    end = math.atan2(*(t1 - c)[::-1])
    sweep = (end - start + math.pi) % (2 * math.pi) - math.pi
    for i in range(1, 64):
        angle = start + sweep * i / 64
        points.append(c + r * np.array([math.cos(angle), math.sin(angle)]))
    ring = [(float(x), float(y)) for x, y in points]
    area = sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1]
        - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring))
    )
    return ring if area > 0 else ring[::-1]


def bevel_section(
    k: tuple[float, float], n1: tuple[float, float], n2: tuple[float, float], c: float
) -> list[tuple[float, float]]:
    """A chamfer's triangle in a right-angled corner at ``k``, out a little past the faces."""
    k_, m1, m2 = (
        np.asarray(k, dtype=float),
        np.asarray(n1, dtype=float),
        np.asarray(n2, dtype=float),
    )
    e = OVERLAP
    ring = [
        tuple(map(float, q))
        for q in (
            k_ + e * m1 + e * m2,
            k_ - (c + e) * m1 + e * m2,
            k_ + e * m1 - (c + e) * m2,
        )
    ]
    area = sum(
        ring[i][0] * ring[(i + 1) % 3][1] - ring[(i + 1) % 3][0] * ring[i][1]
        for i in range(3)
    )
    return ring if area > 0 else ring[::-1]  # type: ignore[return-value]


def swept(
    section: list[tuple[float, float]],
    loop: list[tuple[tuple[float, float], tuple[float, float]]],
    height: float,
) -> Any:
    """A section swept once round a smooth closed outline in a plane of constant height (a ring of it).

    ``loop``: the outline's points in turn (anticlockwise), each with its
    outward normal; ``section``: a polygon in (out from the outline, up from
    ``height``). Made as its own mesh.
    """
    lib = m3()
    ring = list(section)
    area = sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1]
        - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring))
    )
    if area < 0:
        ring = ring[::-1]
    m, k = len(loop), len(ring)
    corners = np.array(
        [
            [px + d * nx, py + d * ny, height + h]
            for (px, py), (nx, ny) in loop
            for d, h in ring
        ],
        dtype=np.float32,
    )
    faces = []
    for i in range(m):
        i2 = (i + 1) % m
        for j in range(k):
            j2 = (j + 1) % k
            a_, b_, c_, d_ = i * k + j, i2 * k + j, i2 * k + j2, i * k + j2
            faces += [(a_, b_, c_), (a_, c_, d_)]
    made = lib.Manifold(
        lib.Mesh(vert_properties=corners, tri_verts=np.array(faces, dtype=np.uint32))
    )
    if made.status() != lib.Error.NoError or made.volume() < 0:
        made = lib.Manifold(
            lib.Mesh(
                vert_properties=corners,
                tri_verts=np.array([f[::-1] for f in faces], dtype=np.uint32),
            )
        )
    if made.status() != lib.Error.NoError or made.volume() <= 0:
        raise ValueError(f"a swept section came out broken: {made.status()}")
    return made


def capped(
    profile: list[tuple[float, float]],
    loop: list[tuple[tuple[float, float], tuple[float, float]]],
    height: float,
) -> Any:
    """A solid inside a smooth convex outline, its side the open ``profile`` swept round it, closed by flat caps.

    ``profile`` runs in (out from the outline, up from ``height``) from the
    bottom cap's edge to the top cap's; the caps are flat polygons, each
    fanned from its middle. Made as its own mesh: a rounding's surface
    meeting the faces it rounds tangentially is never left to a boolean.
    """
    lib = m3()
    m, k = len(loop), len(profile)
    rings = [
        [(px + d * nx, py + d * ny, height + h) for (px, py), (nx, ny) in loop]
        for d, h in profile
    ]
    vertices = [q for ring in rings for q in ring]
    vertices += [tuple(np.mean(rings[0], axis=0)), tuple(np.mean(rings[-1], axis=0))]
    vb, vt = len(vertices) - 2, len(vertices) - 1
    faces = []
    for j in range(k - 1):
        for i in range(m):
            i2 = (i + 1) % m
            a_, b_, c_, d_ = j * m + i, j * m + i2, (j + 1) * m + i2, (j + 1) * m + i
            faces += [(a_, b_, c_), (a_, c_, d_)]
    for i in range(m):
        i2 = (i + 1) % m
        faces.append((vb, i2, i))
        faces.append((vt, (k - 1) * m + i, (k - 1) * m + i2))
    corners = np.array(vertices, dtype=np.float32)
    made = lib.Manifold(
        lib.Mesh(vert_properties=corners, tri_verts=np.array(faces, dtype=np.uint32))
    )
    if made.status() != lib.Error.NoError or made.volume() < 0:
        made = lib.Manifold(
            lib.Mesh(
                vert_properties=corners,
                tri_verts=np.array([f[::-1] for f in faces], dtype=np.uint32),
            )
        )
    if made.status() != lib.Error.NoError or made.volume() <= 0:
        raise ValueError(f"a capped sweep came out broken: {made.status()}")
    return made


def rounded_loop(
    centre: tuple[float, float], h1: float, h2: float, r: float, count: int = SEGMENTS
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """A rectangle's outline with every corner rounded by ``r`` > 0, its points in turn with their outward normals."""
    cx, cy = centre
    found = []
    for k, (sx, sy) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        ax, ay = cx + sx * (h1 - r), cy + sy * (h2 - r)
        for i in range(count // 4 + 1):
            t = k * math.pi / 2 + (math.pi / 2) * i / (count // 4)
            n = (math.cos(t), math.sin(t))
            found.append(((ax + r * n[0], ay + r * n[1]), n))
    # The points where a corner's arc meets the next side are listed once.
    unique = [found[0]]
    for q in found[1:]:
        if math.dist(q[0], unique[-1][0]) > 1e-12:
            unique.append(q)
    return unique


def mesh_box(found: Any) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    b = found.bounding_box()
    return np.array(b[:3]), np.array(b[3:])


# ----------------------------------------------------------------------
# The parts: (spec items, builder)
# ----------------------------------------------------------------------
def item(item_id: str, kind: str, **fields: Any) -> dict[str, Any]:
    return {"id": item_id, "kind": kind, "words": WORDS, **fields}


def on(host: str, face: str) -> dict[str, str]:
    return {"item": host, "face": face}


def through() -> dict[str, Any]:
    return {"through": True, "from": SAY}


def side(direction: str, distance: float, to: str = "centre") -> dict[str, Any]:
    return {"side": direction, "distance": a(distance), "to": to}


def offset(d: float) -> dict[str, Any]:
    return {"offset": a(d)}


def concentric(with_: str) -> dict[str, Any]:
    return {"concentric": {"item": with_, "from": SAY}}


def plate_with_holes() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(80), width=a(50), height=a(5)),
        item("corners", "hole", on=on("plate", "+z"), diameter=a(4.5), depth=through(), count=n(4),
             place={"pattern": {"corners": {"inset_x": a(6), "inset_y": a(6)}}}),
        item("blind", "hole", on=on("plate", "+z"), diameter=a(6), depth=a(2), place={"x": offset(20)}),
        item("bored", "hole", on=on("plate", "+z"), diameter=a(4), depth=through(),
             counterbore={"diameter": a(8), "depth": a(2)}, place={"x": offset(-20)}),
        item("sunk", "hole", on=on("plate", "+z"), diameter=a(4), depth=through(),
             countersink={"diameter": a(8), "angle": a(90, "deg")}, place={"y": offset(12)}),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-40, -25, 0), (40, 25, 5))
        for x in (-34, 34):
            for y in (-19, 19):
                part -= rod((x, y, -1), (0, 0, 1), 7, 2.25)
        part -= rod((20, 0, 3), (0, 0, 1), 3, 3)
        part -= rod((-20, 0, -1), (0, 0, 1), 7, 2) + rod((-20, 0, 3), (0, 0, 1), 3, 4)
        # The countersink: 8 wide at the face, narrowing at 90 degrees to the hole's 4, 2 deep
        # (and carried on past the face, still widening, through air).
        part -= rod((0, 12, -1), (0, 0, 1), 7, 2) + rod(
            (0, 12, 3), (0, 0, 1), 3, 2, top=5
        )
        return part

    return items, build


def slots_and_pockets() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(40), height=a(6)),
        item("long", "slot", on=on("plate", "+z"), width=a(6), length=a(20), along=pick("x"), ends=pick("round"),
             depth=through(), place={"y": offset(10)}),
        item("short", "slot", on=on("plate", "+z"), width=a(4), length=a(12), along=pick("y"), ends=pick("square"),
             depth=a(3), place={"x": side("-x", 8)}),
        item("pocket", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(20), width=a(12),
             corner_radius=a(3), depth=a(2), place={"x": side("+x", 15), "y": offset(-8)}),
        item("pin", "post", on=on("pocket", "bottom"), length=a(4), width=a(4), height=a(5)),
        item("cup", "pocket", on=on("plate", "-z"), shape=pick("circle"), diameter=a(10), depth=a(3.5),
             place={"x": offset(5), "y": offset(-8)}),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-30, -20, 0), (30, 20, 6))
        # A round-ended slot: a box between the two end circles' centres, and the circles.
        part -= (
            box((-7, 7, -1), (7, 13, 7))
            + rod((-7, 10, -1), (0, 0, 1), 8, 3)
            + rod((7, 10, -1), (0, 0, 1), 8, 3)
        )
        part -= box((-24, -6, 3), (-20, 6, 7))
        # The pocket: 20 x 12, centred 15 in from +x and 8 towards -y, its corners rounded 3, 2 deep.
        cx, cy = 15.0, -8.0
        pocket = box((cx - 10, cy - 3, 4), (cx + 10, cy + 3, 7)) + box(
            (cx - 7, cy - 6, 4), (cx + 7, cy + 6, 7)
        )
        for sx in (-1, 1):
            for sy in (-1, 1):
                pocket += rod((cx + sx * 7, cy + sy * 3, 4), (0, 0, 1), 3, 3)
        part -= pocket
        part += box(
            (cx - 2, cy - 2, 3.5), (cx + 2, cy + 2, 9)
        )  # the pin, on the pocket's floor
        # The cup, from below: 3.5 deep, leaving the pocket a floor over it.
        part -= rod((5, -8, -1), (0, 0, 1), 4.5, 5)
        return part

    return items, build


def bracket() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("base", "block", length=a(60), width=a(40), height=a(6)),
        item("upright", "block", on=on("base", "+z"), length=a(6), width=a(40), height=a(30),
             place={"x": side("-x", 0, "edge")}),
        item("bore", "hole", on=on("upright", "+x"), diameter=a(8), depth=through(), place={"z": offset(4)}),
        item("slot", "slot", on=on("base", "+z"), width=a(5), length=a(15), along=pick("x"), ends=pick("round"),
             depth=through(), place={"x": offset(12)}),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-30, -20, 0), (30, 20, 6)) + box((-30, -20, 5), (-24, 20, 36))
        # The upright's +x face is 6 to 36 high: its centre is at z = 21, and the hole 4 above it.
        part -= rod((-23, 0, 25), (-1, 0, 0), 8, 4)
        part -= (
            box((7, -2.5, -1), (17, 2.5, 7))
            + rod((7, 0, -1), (0, 0, 1), 8, 2.5)
            + rod((17, 0, -1), (0, 0, 1), 8, 2.5)
        )
        return part

    return items, build


def flange() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("disc", "cylinder", diameter=a(60), length=a(8)),
        item("neck", "tube", on=on("disc", "+end"), outer_diameter=a(30), inner_diameter=a(20), length=a(20)),
        item("bolts", "hole", on=on("disc", "+end"), diameter=a(5), depth=through(), count=n(6),
             place={"pattern": {"circle": {"count": n(6), "diameter": a(48), "start": a(30, "deg")}}}),
        item("port", "hole", on=on("neck", "side"), diameter=a(6), depth=through(), place={"angle": a(0, "deg")}),
    ]  # fmt: skip

    def build() -> Any:
        part = rod((0, 0, 0), (0, 0, 1), 8, 30) + (
            rod((0, 0, 7), (0, 0, 1), 21, 15) - rod((0, 0, 8), (0, 0, 1), 21, 10)
        )
        for k in range(6):
            t = math.radians(30 + 60 * k)
            part -= rod((24 * math.cos(t), 24 * math.sin(t), -1), (0, 0, 1), 10, 2.5)
        # Through the neck's wall from +x, halfway up it, until it is in the bore all across its mouth:
        # 15 - sqrt(10^2 - 3^2) in from x = 15, and on through the bore's air to x = 9.
        part -= rod((16, 0, 18), (-1, 0, 0), 7, 3)
        return part

    return items, build


def rod_with_boss() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("shaft", "cylinder", diameter=a(20), length=a(50), axis=pick("x")),
        item("lug", "boss", on=on("shaft", "side"), diameter=a(8), height=a(6), place={"angle": a(90, "deg")}),
        item("pin", "hole", on=on("lug", "+end"), diameter=a(3), depth=through(), place=concentric("lug")),
        item("cross", "hole", on=on("shaft", "side"), diameter=a(4), depth=through(),
             place={"angle": a(0, "deg"), "x": side("-x", 10)}),
    ]  # fmt: skip

    def build() -> Any:
        part = rod((0, 0, 0), (1, 0, 0), 50, 10)
        # Round x, 90 degrees is +z: the boss stands up from the top of the shaft, halfway along it,
        # its foot reaching down to the curve: a cylinder from the axis up to 6 above the side, less the
        # shaft (which is already there).
        part += rod((25, 0, 0), (0, 0, 1), 16, 4)
        # Through the boss's top: its own height, and the shaft's whole diameter under it (to z = -10).
        part -= rod((25, 0, 17), (0, 0, -1), 28, 1.5)
        # Round x, 0 degrees is +y: across the shaft from the plane touching it at y = 10.
        part -= rod((10, 11, 0), (0, -1, 0), 22, 2)
        return part

    return items, build


def tray() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("tray", "block", length=a(100), width=a(60), height=a(30)),
        item("hollow", "shell", of="tray", thickness=a(2), open={"faces": ["+z"], "from": SAY}, floor=a(3)),
        item("stand", "post", on=on("tray", "inner -z"), length=a(10), width=a(10), height=a(12)),
        item("drain", "hole", on=on("tray", "inner -z"), diameter=a(5), depth=through(), place={"x": offset(30)}),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-50, -30, 0), (50, 30, 30)) - box((-48, -28, 3), (48, 28, 31))
        part += box((-5, -5, 2.5), (5, 5, 15))
        part -= rod((30, 0, -1), (0, 0, 1), 5, 2.5)
        return part

    return items, build


def sealed_box() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("box", "block", length=a(40), width=a(40), height=a(20)),
        item("hollow", "shell", of="box", thickness=a(2), open={"faces": [], "from": SAY}),
        item("vent", "hole", on=on("box", "+z"), diameter=a(6), depth=through(), place={"x": offset(8)}),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-20, -20, 0), (20, 20, 20)) - box((-18, -18, 2), (18, 18, 18))
        return part - rod((8, 0, 17), (0, 0, 1), 4, 3)

    return items, build


def cone_on_plate() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(60), height=a(4)),
        item("cup", "cone", on=on("plate", "+z"), base_diameter=a(20), top_diameter=a(40), length=a(30)),
        item("edge", "hole", on=on("cup", "+end"), diameter=a(4), depth=through(), place={"x": offset(15)}),
        item("middle", "hole", on=on("cup", "+end"), diameter=a(4), depth=through()),
    ]  # fmt: skip

    def build() -> Any:
        # The cone, carried a little way down into the plate along its own slope (1 in 3).
        part = box((-30, -30, 0), (30, 30, 4)) + rod(
            (0, 0, 3), (0, 0, 1), 31, 10 - 1 / 3, top=20
        )
        # 13 to 17 mm out, the most material is the taper's at 13: 30 x (20 - 13) / 10 = 21, to z = 13.
        # (Below z = 13 the cone is narrower than 13: carried on down to 12 through air.)
        part -= rod((15, 0, 12), (0, 0, 1), 23, 2)
        # In the middle, within the smaller end: the cone's 30 and the plate's 4.
        part -= rod((0, 0, -1), (0, 0, 1), 36, 2)
        return part

    return items, build


def dome() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("dome", "sphere", diameter=a(40), portion=pick("upper_half")),
        item("vent", "hole", on=on("dome", "-end"), diameter=a(4), depth=through(), place={"x": offset(12)}),
        item("foot", "boss", on=on("dome", "-end"), diameter=a(6), height=a(3), place={"x": offset(-10)}),
    ]  # fmt: skip

    def build() -> Any:
        part = ball((0, 0, 0), 20) - box((-21, -21, -21), (21, 21, 0))
        # Under the flat face 10 to 14 mm from the centre: the dome is tallest at 10, sqrt(400 - 100)
        # (carried on to z = 18 through air).
        part -= rod((12, 0, -1), (0, 0, 1), 19, 2)
        return part + rod((-10, 0, 1), (0, 0, -1), 4, 3)

    return items, build


def tabs() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(50), width=a(30), height=a(4)),
        item("lug", "tab", on=on("plate", "+z"), length=a(12), width=a(10), thickness=a(3), thickness_along=pick("y"),
             end=pick("round"), place={"x": offset(-10)}),
        item("eye", "hole", on=on("lug", "+y"), diameter=a(4), depth=through(), place={"z": side("+z", 5)}),
        item("flat", "tab", on=on("plate", "+z"), length=a(10), width=a(8), thickness=a(2), thickness_along=pick("x"),
             end=pick("square"), place={"x": offset(12)}),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-25, -15, 0), (25, 15, 4))
        # The round-ended lug: 10 wide along x, 3 thick along y, 12 up: a box to 11 and a disc of 5 at 11.
        part += box((-15, -1.5, 3), (-5, 1.5, 11)) + rod(
            (-10, -1.5, 11), (0, 1, 0), 3, 5
        )
        # Its +y face's far edge is the top of the rounding, z = 16: the eye is 5 below it.
        part -= rod((-10, 2.5, 11), (0, -1, 0), 5, 2)
        return part + box((11, -4, 3), (13, 4, 14))

    return items, build


def ball_on_plate() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(40), width=a(40), height=a(5)),
        item(
            "knob",
            "sphere",
            on=on("plate", "+z"),
            diameter=a(30),
            portion=pick("whole"),
        ),
    ]

    def build() -> Any:
        return box((-20, -20, 0), (20, 20, 5)) + ball((0, 0, 5), 15)

    return items, build


def bore_boss() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("sleeve", "tube", outer_diameter=a(40), inner_diameter=a(30), length=a(30)),
        item("key", "boss", on=on("sleeve", "bore"), diameter=a(6), height=a(4)),
        item("oil", "hole", on=on("sleeve", "bore"), diameter=a(4), depth=through(), place={"angle": a(180, "deg")}),
    ]  # fmt: skip

    def build() -> Any:
        part = rod((0, 0, 0), (0, 0, 1), 30, 20) - rod((0, 0, -1), (0, 0, 1), 32, 15)
        # At 0 degrees round z (+x), standing in towards the axis 4 from the bore: from x = 11 out, its
        # foot following the bore (the sleeve is already there beyond it).
        part += rod((11, 0, 15), (1, 0, 0), 4.5, 3)
        # At 180 degrees (-x): from the axis, out through the wall.
        part -= rod((0, 0, 15), (-1, 0, 0), 21, 2)
        return part

    return items, build


def post_round_a_rod() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("rod", "cylinder", diameter=a(30), length=a(40)),
        item("post", "post", on=on("rod", "side"), length=a(8), width=a(6), height=a(5), place={"angle": a(90, "deg")}),
        item("pin", "hole", on=on("post", "+y"), diameter=a(3), depth=through()),
    ]  # fmt: skip

    def build() -> Any:
        part = rod((0, 0, 0), (0, 0, 1), 40, 15)
        # At 90 degrees round z: standing out along +y from y = 15, 8 round (x) and 6 along z, 5 high;
        # its foot reaches down to the curve (the rod fills the rest).
        part += box((-4, 0, 17), (4, 20, 23))
        # Its far face's material: its height and the rod's whole diameter (to y = -15).
        part -= rod((0, 21, 20), (0, -1, 0), 37, 1.5)
        return part

    return items, build


def closed_box() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("box", "block", length=a(40), width=a(30), height=a(20)),
        item("hollow", "shell", of="box", thickness=a(2), open={"faces": [], "from": SAY}),
    ]  # fmt: skip

    def build() -> Any:
        return box((-20, -15, 0), (20, 15, 20)) - box((-18, -13, 2), (18, 13, 18))

    return items, build


def floored_dome() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("dome", "sphere", diameter=a(40), portion=pick("upper_half")),
        item("hollow", "shell", of="dome", thickness=a(2), open={"faces": [], "from": SAY}, floor=a(3)),
        item("seat", "hole", on=on("dome", "-end"), diameter=a(4), depth=a(2), place={"x": offset(6)}),
    ]  # fmt: skip

    def build() -> Any:
        # Its flat face's wall is its own floor (shell.md), 3 thick: the hollow 18 out from the centre, above
        # z = 3; the seat 2 into the floor from below.
        part = ball((0, 0, 0), 20) - box((-21, -21, -21), (21, 21, 0))
        part -= ball((0, 0, 0), 18) - box((-19, -19, -19), (19, 19, 3))
        return part - rod((6, 0, -1), (0, 0, 1), 3, 2)

    return items, build


def covered_pocket() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(40), height=a(6)),
        item("cup", "pocket", on=on("plate", "+z"), shape=pick("circle"), diameter=a(10), depth=a(3)),
        item("lid", "post", on=on("plate", "+z"), length=a(16), width=a(16), height=a(4)),
    ]  # fmt: skip

    def build() -> Any:
        # The lid stands over the cup's mouth: the cup is a hollow sealed inside.
        part = box((-30, -20, 0), (30, 20, 6)) + box((-8, -8, 5), (8, 8, 10))
        return part - rod((0, 0, 3), (0, 0, 1), 3, 5)

    return items, build


def two_hollows() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("low", "block", length=a(40), width=a(40), height=a(20)),
        item("hollow_low", "shell", of="low", thickness=a(2), open={"faces": [], "from": SAY}),
        item("high", "block", on=on("low", "+z"), length=a(20), width=a(20), height=a(20)),
        item("hollow_high", "shell", of="high", thickness=a(2), open={"faces": [], "from": SAY}),
    ]  # fmt: skip

    def build() -> Any:
        low = box((-20, -20, 0), (20, 20, 20)) - box((-18, -18, 2), (18, 18, 18))
        # Each shell hollows its own body: the high one has its own floor on the low one's roof.
        high = box((-10, -10, 19), (10, 10, 40)) - box((-8, -8, 22), (8, 8, 38))
        return low + high

    return items, build


def rounded_block() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("box", "block", length=a(40), width=a(30), height=a(20)),
        item("round", "fillet", edges={"of": "box", "which": "top"}, radius=a(3)),
        item("bevel", "chamfer", edges={"of": "box", "which": "vertical"}, size=a(2)),
    ]

    def build() -> Any:
        part = box((-20, -15, 0), (20, 15, 20))
        z = (0.0, 0.0, 1.0)
        for sx in (-1, 1):
            n = (float(sx), 0.0, 0.0)
            part -= corner((20 * sx, -15, 20), (20 * sx, 15, 20), z, n, 3)
        for sy in (-1, 1):
            n = (0.0, float(sy), 0.0)
            part -= corner((-20, 15 * sy, 20), (20, 15 * sy, 20), z, n, 3)
        for sx in (-1, 1):
            for sy in (-1, 1):
                part -= corner(
                    (20 * sx, 15 * sy, 0),
                    (20 * sx, 15 * sy, 20),
                    (float(sx), 0, 0),
                    (0, float(sy), 0),
                    2,
                    False,
                )
        return part

    return items, build


def post_and_joint() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(40), height=a(5)),
        item(
            "post", "post", on=on("plate", "+z"), length=a(12), width=a(8), height=a(10)
        ),
        item(
            "foot",
            "fillet",
            edges={"of": "post", "which": "joint", "where_meets": "plate"},
            radius=a(2),
        ),
        item("crown", "chamfer", edges={"of": "post", "which": "top"}, size=a(1)),
    ]

    def build() -> Any:
        part = box((-30, -20, 0), (30, 20, 5)) + box((-6, -4, 4.9), (6, 4, 15))
        down = (0.0, 0.0, -1.0)
        # Round its foot: the corner above the plate and outside the post, each side.
        for sx in (-1, 1):
            part += corner((6 * sx, -4, 5), (6 * sx, 4, 5), down, (-float(sx), 0, 0), 2)
        for sy in (-1, 1):
            part += corner((-6, 4 * sy, 5), (6, 4 * sy, 5), down, (0, -float(sy), 0), 2)
        up = (0.0, 0.0, 1.0)
        for sx in (-1, 1):
            part -= corner(
                (6 * sx, -4, 15), (6 * sx, 4, 15), up, (float(sx), 0, 0), 1, False
            )
        for sy in (-1, 1):
            part -= corner(
                (-6, 4 * sy, 15), (6, 4 * sy, 15), up, (0, float(sy), 0), 1, False
            )
        return part

    return items, build


def bevelled_inside() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(40), height=a(6)),
        item("pocket", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(20), width=a(12),
             corner_radius=a(3), depth=a(3), place={"x": offset(12)}),
        item("floor", "chamfer", edges={"of": "pocket", "which": "bottom"}, size=a(0.8)),
        item("post", "post", on=on("plate", "+z"), length=a(8), width=a(6), height=a(8), place={"x": offset(-15)}),
        item("foot", "chamfer", edges={"of": "post", "which": "joint", "where_meets": "plate"}, size=a(1)),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-30, -20, 0), (30, 20, 6))
        # Inside edges bevelled: the pocket's floor 0.8 in from its wall rising to 0.8 up it (in, out from its
        # outline and up from its floor at z = 3), and the post's foot filled 1 out over the plate and 1 up it.
        part -= capped(
            [(-0.8, 0.0), (0.0, 0.8), (0.0, 4.0)],
            rounded_loop((12.0, 0.0), 10, 6, 3),
            3.0,
        )
        part += box((-19, -3, 5.9), (-11, 3, 14))
        down = (0.0, 0.0, -1.0)
        for sx in (-1, 1):
            x = -15.0 + 4.0 * sx
            part += corner((x, -3, 6), (x, 3, 6), down, (-float(sx), 0, 0), 1, False)
        for sy in (-1, 1):
            part += corner(
                (-19, 3 * sy, 6), (-11, 3 * sy, 6), down, (0, -float(sy), 0), 1, False
            )
        return part

    return items, build


def cup() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("cup", "cylinder", diameter=a(30), length=a(20)),
        item("base", "fillet", edges={"of": "cup", "which": "bottom"}, radius=a(3)),
        item(
            "hollow",
            "shell",
            of="cup",
            thickness=a(2),
            open={"faces": ["+end"], "from": SAY},
        ),
        item("lip", "fillet", edges={"of": "cup", "which": "top"}, radius=a(0.8)),
    ]

    def build() -> Any:
        # Its section: the base's rounding (3), the wall up to the lip, the lip's two roundings
        # (0.8, outside and in), down the hollow's wall to its corner, which follows the base's
        # rounding (3 less the 2 mm wall: 1, round the same centre), and the floor back to the axis.
        def arc(
            cx: float, cy: float, r: float, a0: float, a1: float
        ) -> list[tuple[float, float]]:
            return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / 64)),
                     cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / 64))) for i in range(65)]  # fmt: skip

        section = [(0.0, 0.0), *arc(12, 3, 3, -90, 0), *arc(14.2, 19.2, 0.8, 0, 90),
                   *arc(13.8, 19.2, 0.8, 90, 180), *arc(12, 3, 1, 0, -90), (0.0, 2.0)]  # fmt: skip
        return turned(section, (0.0, 0.0, 0.0))

    return items, build


def cup_floor() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("cup", "cylinder", diameter=a(30), length=a(20)),
        item("hollow", "shell", of="cup", thickness=a(2), open={"faces": ["+end"], "from": SAY}),
        item("seat", "hole", on=on("cup", "inner -end"), diameter=a(4), depth=a(1),
             place={"x": side("+x", 3, "edge"), "y": offset(2)}),
    ]  # fmt: skip

    def build() -> Any:
        # The floor's edges are the hollow's own side, 13 out (place.md): the seat's edge 3 in from it at
        # x = 10, so its centre at (8, 2); 1 deep from the floor's top at z = 2.
        part = rod((0, 0, 0), (0, 0, 1), 20, 15) - rod((0, 0, 2), (0, 0, 1), 19, 13)
        return part - rod((8, 2, 1), (0, 0, 1), 2, 2)

    return items, build


def plate_with_rims() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(40), height=a(6)),
        item("hole", "hole", on=on("plate", "+z"), diameter=a(6), depth=through(), place={"x": offset(-15)}),
        item("eased", "fillet", edges={"of": "hole", "which": "top"}, radius=a(1)),
        item("pocket", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(20), width=a(12),
             corner_radius=a(3), depth=a(3), place={"x": offset(12)}),
        item("floor", "fillet", edges={"of": "pocket", "which": "bottom"}, radius=a(1)),
        item("mouth", "chamfer", edges={"of": "pocket", "which": "top"}, size=a(0.5)),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-30, -20, 0), (30, 20, 6)) - rod((-15, 0, -1), (0, 0, 1), 8, 3)
        # The hole's rim: material outside it, under the face.
        part -= turned(round_section((3, 6), (0, 1), (-1, 0), 1), (-15, 0, 0))
        # The pocket with its floor's rounding and its mouth's bevel, as one solid: in (out from the
        # wall, up from the floor), the floor 1 in from the wall, the ball's arc round (-1, 1) up to
        # the wall, up the wall to 0.5 under the face, out 0.5 at the face, and on up past it.
        cx = 12.0
        edge = rounded_loop((cx, 0.0), 10, 6, 3)
        arc = [
            (-1 + math.cos(t), 1 + math.sin(t))
            for t in np.linspace(-math.pi / 2, 0.0, 65)
        ]
        e = OVERLAP
        part -= capped(
            [*arc, (0.0, 2.5), (0.5 + e, 3.0 + e), (0.5 + e, 4.0)], edge, 3.0
        )
        return part

    return items, build


def boss_and_dome() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(40), height=a(5)),
        item("boss", "boss", on=on("plate", "+z"), diameter=a(10), height=a(8), place={"x": offset(-15)}),
        item("skirt", "fillet", edges={"of": "boss", "which": "joint", "where_meets": "plate"}, radius=a(2)),
        item("cap", "fillet", edges={"of": "boss", "which": "top"}, radius=a(1)),
        item("dome", "sphere", on=on("plate", "+z"), diameter=a(20), portion=pick("upper_half"),
             place={"x": offset(15)}),
        item("hem", "fillet", edges={"of": "dome", "which": "joint", "where_meets": "plate"}, radius=a(1.5)),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-30, -20, 0), (30, 20, 5)) + rod((-15, 0, 4.9), (0, 0, 1), 8.1, 5)
        part += ball((15, 0, 5), 10) - box((4, -11, -6), (26, 11, 4.9))
        # Round the boss's foot (air above the plate, outside the boss) and its top's rim.
        part += turned(round_section((5, 5), (-1, 0), (0, -1), 2), (-15, 0, 0))
        part -= turned(round_section((5, 13), (1, 0), (0, 1), 1), (-15, 0, 0))
        # Round the dome's foot: the ball, 1.5 in from the plate and out from the ball, touches both.
        r, big = 1.5, 10.0
        c = (math.sqrt((big + r) ** 2 - r * r), r)
        t2 = (c[0] * big / (big + r), c[1] * big / (big + r))
        arc = [(c[0] + r * math.cos(t), c[1] + r * math.sin(t))
               for t in np.linspace(-math.pi / 2, math.atan2(t2[1] - c[1], t2[0] - c[0]), 64)]  # fmt: skip
        section = [(big - 0.3, -OVERLAP), (c[0], -OVERLAP), *arc, (big - 0.3, t2[1])]
        part += turned([(x, y + 5) for x, y in section], (15, 0, 0))
        return part

    return items, build


def hollow_box() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("box", "block", length=a(40), width=a(30), height=a(20)),
        item(
            "corners", "fillet", edges={"of": "box", "which": "vertical"}, radius=a(4)
        ),
        item(
            "hollow",
            "shell",
            of="box",
            thickness=a(2),
            open={"faces": ["+z"], "from": SAY},
        ),
        item("lip", "chamfer", edges={"of": "box", "which": "top"}, size=a(0.5)),
    ]

    def build() -> Any:
        outer = box((-20, -15, 0), (20, 15, 20))
        # The hollow, 2 in from each closed face, its corners following the box's: 4 - 2 round the same centres.
        hollow = box((-18, -13, 2), (18, 13, 21))
        for sx in (-1, 1):
            for sy in (-1, 1):
                n1, n2 = (float(sx), 0.0, 0.0), (0.0, float(sy), 0.0)
                outer -= corner(
                    (20 * sx, 15 * sy, 0), (20 * sx, 15 * sy, 20), n1, n2, 4
                )
                behind = box(
                    (min(16 * sx, 20 * sx), min(11 * sy, 15 * sy), 1),
                    (max(16 * sx, 20 * sx), max(11 * sy, 15 * sy), 22),
                )
                hollow -= behind - rod((16 * sx, 11 * sy, 0), (0, 0, 1), 23, 2)
        part = outer - hollow
        # The lip: the rim's outside edge all round the rounded box, and its inside edge all round the hollow.
        # (Sampled off the cylinders' own corners, so no two surfaces' facets line up.)
        part -= swept(
            bevel_section((0, 0), (1, 0), (0, 1), 0.5),
            rounded_loop((0.0, 0.0), 20, 15, 4, 268),
            20.0,
        )
        part -= swept(
            bevel_section((0, 0), (-1, 0), (0, 1), 0.5),
            rounded_loop((0.0, 0.0), 18, 13, 2, 268),
            20.0,
        )
        return part

    return items, build


#: Each part's topology, worked out by hand: (solids, voids, through-holes).
def threaded(
    start: tuple[float, float, float], length: float, r: float, pitch: float
) -> Any:
    """A rod of radius ``r`` along +z from ``start``, cut into an ISO 68-1 basic thread: its section, twisted as it rises.

    Across the axis at height z the thread's section is the one at its start
    turned by 2 pi z / pitch: at each angle its radius is the basic profile's
    (a crest flat an eighth of the pitch wide at ``r``, flanks at 60 degrees,
    a root flat a quarter wide 5/8 of the sharp triangle's height in).
    """
    deep = 5 / 8 * math.sqrt(3) / 2 * pitch

    def profile(u: NDArray[np.float64]) -> NDArray[np.float64]:
        off = np.minimum(u, pitch - u)  # from the nearest crest's middle
        return np.clip(r - math.sqrt(3) * (off - pitch / 16), r - deep, r)

    angles = 2 * math.pi * np.arange(360) / 360
    radius = profile(np.mod(-angles * pitch / (2 * math.pi), pitch))
    section = m3().CrossSection(
        [np.stack([radius * np.cos(angles), radius * np.sin(angles)], axis=1).tolist()]
    )
    turns = length / pitch
    rod_ = m3().Manifold.extrude(section, length, math.ceil(turns * 72), 360 * turns)
    return rod_.translate(start)


def threaded_boss() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(40), width=a(30), height=a(5)),
        item("stud", "boss", on=on("plate", "+z"), diameter=a(8), height=a(12)),
        item("thread", "thread", of="stud", designation={"text": "M8", "from": SAY}, hand=pick("right"),
             length=a(8)),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-20, -15, 0), (20, 15, 5))
        # The stud's plain foot, up to where the thread starts 8 under its top (a hair past, into it).
        part += rod((0, 0, 5 - OVERLAP), (0, 0, 1), 4 + 2 * OVERLAP, 4)
        part += threaded((0, 0, 9), 8, 4, 1.25)
        return part

    return items, build


def outline(
    start: tuple[float, float],
    *steps: tuple[tuple[float, float], tuple[float, float] | None, bool],
) -> dict[str, Any]:
    """A spec's outline: from ``start``, each step to a point, straight (no centre) or round a centre (clockwise or not)."""
    segments: list[dict[str, Any]] = []
    for to, centre, clockwise in steps:
        if centre is None:
            segments.append({"line_to": list(to)})
        else:
            segments.append(
                {
                    "arc_to": list(to),
                    "centre": list(centre),
                    **({"clockwise": True} if clockwise else {}),
                }
            )
    return {"start": list(start), "segments": segments, "from": SAY}


def followed(profile: dict[str, Any]) -> list[tuple[float, float]]:
    """An outline as a fine polygon: its corners, and each arc's points every 1/256 of a turn, each on the arc."""
    here = tuple(profile["start"])
    points = [here]
    for seg in profile["segments"]:
        if "line_to" in seg:
            here = tuple(seg["line_to"])
            points.append(here)
            continue
        to, (cx, cy) = tuple(seg["arc_to"]), seg["centre"]
        r = math.dist(here, (cx, cy))
        a0, a1 = (
            math.atan2(here[1] - cy, here[0] - cx),
            math.atan2(to[1] - cy, to[0] - cx),
        )
        clockwise = bool(seg.get("clockwise"))
        sweep = ((a0 - a1) if clockwise else (a1 - a0)) % (2 * math.pi)
        steps = max(2, math.ceil(sweep / (2 * math.pi) * SEGMENTS))
        for k in range(1, steps):
            t = a0 + (-sweep if clockwise else sweep) * k / steps
            points.append((cx + r * math.cos(t), cy + r * math.sin(t)))
        points.append(to)
        here = to
    return points[:-1]  # it closes back on its start


def pushed(
    profile: dict[str, Any],
    low: float,
    high: float,
    at: tuple[float, float] = (0.0, 0.0),
) -> Any:
    """An outline in x and y, moved by ``at``, pushed from z = ``low`` to ``high``."""
    points = [(x + at[0], y + at[1]) for x, y in followed(profile)]
    lib = m3()
    return lib.Manifold.extrude(lib.CrossSection([points]), high - low).translate(
        (0.0, 0.0, low)
    )


#: A plate 30 x 20 with a bite of radius 9 out of the middle of its top edge.
BITTEN = outline((0, 0), ((30, 0), None, False), ((30, 20), None, False), ((24, 20), None, False),
                 ((6, 20), (15, 20), True), ((0, 20), None, False), ((0, 0), None, False))  # fmt: skip
#: A knob's half outline: a stem 8 across, a disc 28 across from 6 to 12 high, its rim rounded 2 above and below.
KNOB = outline((0, 0), ((4, 0), None, False), ((4, 6), None, False), ((12, 6), None, False), ((14, 8), (12, 8), False),
               ((14, 10), None, False), ((12, 12), (12, 10), False), ((0, 12), None, False), ((0, 0), None, False))  # fmt: skip
#: A pulley's half outline: 30 across and 10 thick, a groove of radius 3 round its rim, a bore 6 across.
PULLEY = outline((3, 0), ((15, 0), None, False), ((15, 2), None, False), ((15, 8), (15, 5), True), ((15, 10), None, False),
                 ((3, 10), None, False), ((3, 0), None, False))  # fmt: skip


def outline_plate() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "extrusion", profile=BITTEN, length=a(8), axis=pick("z")),
        item("hole", "hole", on=on("plate", "+end"), diameter=a(4), depth=through(),
             place={"x": side("-x", 3), "y": side("-y", 4)}),
        item("pocket", "pocket", on=on("plate", "+end"), shape=pick("circle"), diameter=a(5), depth=a(3),
             place={"x": side("+x", 4, "edge"), "y": side("-y", 3, "edge")}),
    ]  # fmt: skip

    def build() -> Any:
        part = pushed(BITTEN, 0, 8)
        part -= rod((3, 4, -1), (0, 0, 1), 10, 2)
        # Its edges are those of the outline's box: 4 in from x = 30 and 3 up from y = 0, to the pocket's edge.
        part -= rod((23.5, 5.5, 5), (0, 0, 1), 4, 2.5)
        return part

    return items, build


def knob() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("knob", "revolution", profile=KNOB, axis=pick("z")),
        item("socket", "hole", on=on("knob", "+end"), diameter=a(3), depth=a(5)),
        item("pin", "hole", on=on("knob", "-end"), diameter=a(2), depth=a(4)),
        item(
            "grip",
            "hole",
            on=on("knob", "+end"),
            diameter=a(2),
            depth=a(3),
            place={"x": offset(6)},
        ),
    ]

    def build() -> Any:
        part = turned(followed(KNOB), (0.0, 0.0, 0.0))
        part -= rod((0, 0, 7), (0, 0, 1), 6, 1.5)
        part -= rod((0, 0, -1), (0, 0, 1), 5, 1)
        # 6 along x from its +end's centre, the knob's axis.
        part -= rod((6, 0, 9), (0, 0, 1), 4, 1)
        return part

    return items, build


def outlines_standing() -> tuple[list[dict[str, Any]], Builder]:
    angle = outline((0, 0), ((10, 0), None, False), ((10, 3), None, False), ((3, 3), None, False), ((3, 12), None, False),
                    ((0, 12), None, False), ((0, 0), None, False))  # fmt: skip
    items = [
        item("plate", "block", length=a(60), width=a(40), height=a(6)),
        item("angle", "extrusion", on=on("plate", "+z"), profile=angle, length=a(5), place={"x": side("-x", 5, "edge")}),
        item("pulley", "revolution", on=on("plate", "+z"), profile=PULLEY, place={"x": side("+x", 10)}),
        item("eye", "hole", on=on("angle", "+end"), diameter=a(1.5), depth=through(),
             place={"x": side("-x", 1.5), "y": offset(3)}),
    ]  # fmt: skip

    def build() -> Any:
        part = box((-30, -20, 0), (30, 20, 6))
        # The angle's outline is 10 x 12 from its point (0, 0): its box's edge 5 in from x = -30, its
        # point at y = 0 (centred), so its point at (-25, 0); it rises from the plate's top to z = 11.
        part += pushed(angle, 6 - OVERLAP, 11, (-25, 0))
        # On its +end (the box's middle at (-20, 6)): the eye 1.5 in from its -x edge, 3 along y from the
        # middle, at (-23.5, 9) on the upright (x from -25 to -22, y from 3 to 12), through it and the plate
        # it stands on (frame.md: under its far face, the plate's material too).
        part -= rod((-23.5, 9, -1), (0, 0, 1), 13, 0.75)
        # The pulley turned about the line up through x = 20 (10 in from x = 30), overhanging the plate's
        # edge; where it is over the plate, a hair of it sunk into it.
        part += turned(followed(PULLEY), (20.0, 0.0, 6.0))
        sunk = [
            (3.0, -OVERLAP),
            (15.0, -OVERLAP),
            (15.0, OVERLAP),
            (3.0, OVERLAP),
        ]  # its foot: a ring
        part += turned(sunk, (20.0, 0.0, 6.0)) ^ box((-30, -20, 5), (30, 20, 7))
        return part

    return items, build


def rounded_angle() -> tuple[list[dict[str, Any]], Builder]:
    angle = outline((0, 0), ((30, 0), None, False), ((30, 6), None, False), ((6, 6), None, False), ((6, 20), None, False),
                    ((0, 20), None, False), ((0, 0), None, False))  # fmt: skip
    items = [
        item("angle", "extrusion", profile=angle, length=a(12), axis=pick("z")),
        item(
            "round", "fillet", edges={"of": "angle", "which": "vertical"}, radius=a(1)
        ),
    ]

    def build() -> Any:
        # Every edge along its length rounded: its outline's outer corners rounded off by 1 and its inner
        # corner (6, 6) filled by 1 (its arc round (7, 7), clockwise), pushed from z = 0 to 12.
        rounded = outline((1, 0), ((29, 0), None, False), ((30, 1), (29, 1), False), ((30, 5), None, False),
                          ((29, 6), (29, 5), False), ((7, 6), None, False), ((6, 7), (7, 7), True),
                          ((6, 19), None, False), ((5, 20), (5, 19), False), ((1, 20), None, False),
                          ((0, 19), (1, 19), False), ((0, 1), None, False), ((1, 0), (1, 1), False))  # fmt: skip
        return pushed(rounded, 0, 12)

    return items, build


def rounded_ring() -> tuple[list[dict[str, Any]], Builder]:
    # A ring turned from 1 to 6 out and 4 high, its outside rounding over into its top by 2: only its bore's
    # rim is an edge there (edges.md: where two faces meet at an angle).
    ring = outline((1, 0), ((6, 0), None, False), ((6, 2), None, False), ((4, 4), (4, 2), False),
                   ((1, 4), None, False), ((1, 0), None, False))  # fmt: skip
    items = [
        item("ring", "revolution", profile=ring, axis=pick("z")),
        item("round", "fillet", edges={"of": "ring", "which": "top"}, radius=a(0.5)),
    ]

    def build() -> Any:
        # The bore's rim at (1, 4) rounded by 0.5: the arc about (1.5, 3.5) from the top to the bore.
        rounded = outline((1, 0), ((6, 0), None, False), ((6, 2), None, False), ((4, 4), (4, 2), False),
                          ((1.5, 4), None, False), ((1, 3.5), (1.5, 3.5), False), ((1, 0), None, False))  # fmt: skip
        return turned(followed(rounded), (0.0, 0.0, 0.0))

    return items, build


#: A disc's half outline: 10 out from its axis and 4 high.
DISC = outline((0, 0), ((10, 0), None, False), ((10, 4), None, False), ((0, 4), None, False), ((0, 0), None, False))  # fmt: skip


def over_the_edge() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(70), width=a(50), height=a(4)),
        item("shelf", "block", on=on("plate", "+z"), length=a(20), width=a(20), height=a(10),
             place={"x": offset(30)}),
        item("disc", "revolution", on=on("plate", "+z"), profile=DISC, place={"x": offset(-30)}),
        item("inner", "hole", on=on("shelf", "+z"), diameter=a(2), depth=through(), place={"x": offset(-5)}),
        item("edge", "hole", on=on("shelf", "+z"), diameter=a(2), depth=through(), place={"x": offset(4.5)}),
        item("pin", "hole", on=on("disc", "+end"), diameter=a(2), depth=through(), place={"x": offset(5)}),
        item("pk", "pocket", on=on("shelf", "+z"), shape=pick("rectangle"), length=a(4), width=a(4), depth=a(2),
             place={"y": offset(6)}),
        item("vent", "hole", on=on("pk", "bottom"), diameter=a(1), depth=through()),
    ]  # fmt: skip

    def build() -> Any:
        # frame.md: the far face of what stands on a host has the host's material under it where it is over
        # the host's face, and only its own over the overhang. The plate runs from x = -35 to 35.
        part = box((-35, -25, 0), (35, 25, 4))
        # The shelf from x = 20 to 40, over air beyond 35; its foot sunk a hair into the plate where over it.
        part += box((20, -10, 4), (40, 10, 14))
        part += box((20, -10, 4 - OVERLAP), (35, 10, 4 + OVERLAP))
        # The disc turned about the line up through x = -30, from -40 to -20, over air beyond -35.
        part += turned(followed(DISC), (-30.0, 0.0, 4.0))
        sunk = [(0.0, -OVERLAP), (10.0, -OVERLAP), (10.0, OVERLAP), (0.0, OVERLAP)]
        part += turned(sunk, (-30.0, 0.0, 4.0)) ^ box((-35, -25, 3), (35, 25, 5))
        # Through the shelf at x = 25, over the plate: through the plate too.
        part -= rod((25, 0, -1), (0, 0, 1), 16, 1)
        # At x = 34.5, from 33.5 to 35.5: over the plate's edge, so through the plate where it is under it.
        part -= rod((34.5, 0, -1), (0, 0, 1), 16, 1)
        # Through the disc at x = -25, over the plate: through both.
        part -= rod((-25, 0, -1), (0, 0, 1), 10, 1)
        # The pocket 2 deep in the shelf's top at (30, 6), over the plate; the vent through its floor and the plate.
        part -= box((28, 4, 12), (32, 8, 15))
        part -= rod((30, 6, -1), (0, 0, 1), 14, 0.5)
        return part

    return items, build


def _letter_rings(text: str, height: float) -> list[list[tuple[float, float]]]:
    """A line's contours as fine polygons in its own plane: x along it from its first letter's start, y up from its baseline.

    TrueType's rules, from the font's own points (forge_spec/glyphs.py, the
    file's): two control points in a row have a point on the curve midway
    between them; two points on the curve in a row are joined straight, and
    a control point between two makes a quadratic arc, cut here into chords
    no farther than :data:`LETTER_CHORD` from it (a quadratic's chord over a
    stretch dt of it strays |P0 - 2 P1 + P2| dt^2 / 4). Each letter is set at
    the advances before it; a capital is ``height`` tall.
    """
    from forge_spec.font import ADVANCES, CAP_HEIGHT
    from forge_spec.glyphs import CONTOURS

    scale = height / CAP_HEIGHT
    rings: list[list[tuple[float, float]]] = []
    pen = 0
    for letter in text:
        for contour in CONTOURS[letter]:
            points: list[tuple[float, float, bool]] = []
            for k, (x, y, on) in enumerate(contour):
                before = contour[k - 1]
                if not on and not before[2]:
                    points.append(((before[0] + x) / 2, (before[1] + y) / 2, True))
                points.append((float(x), float(y), bool(on)))
            first = next(k for k, p in enumerate(points) if p[2])
            points = points[first:] + points[:first]
            ring: list[tuple[float, float]] = []
            k = 0
            while k < len(points):
                p0, p1 = points[k], points[(k + 1) % len(points)]
                if p1[2]:
                    ring.append((p0[0], p0[1]))
                    k += 1
                    continue
                p2 = points[(k + 2) % len(points)]
                bend = (
                    math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
                    * scale
                )
                count = max(1, math.ceil(math.sqrt(bend / (4 * LETTER_CHORD))))
                for j in range(count):
                    t = j / count
                    ring.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))  # fmt: skip
                k += 2
            rings.append([((pen + x) * scale, y * scale) for x, y in ring])
        pen += ADVANCES[letter]
    return rings


def letters(text: str, height: float) -> Any:
    """A line of letters as a cross-section (the region of nonzero winding of its contours), its box centred on the origin.

    text.md: the box runs from the first letter's start to the last letter's
    advance, and from the baseline to a capital's top.
    """
    from forge_spec.font import ADVANCES, CAP_HEIGHT

    lib = m3()
    width = sum(ADVANCES[letter] for letter in text) * height / CAP_HEIGHT
    region = lib.CrossSection(
        _letter_rings(text, height), fillrule=lib.FillRule.NonZero
    )
    return region.translate((-width / 2, -height / 2))


def lettered_plate() -> tuple[list[dict[str, Any]], Builder]:
    items = [
        item("plate", "block", length=a(60), width=a(30), height=a(6)),
        item("name", "text", on=on("plate", "+z"), text={"text": "FORGE Ç&j", "from": SAY}, height=a(6),
             depth=a(0.6), mode=pick("engrave")),
        item("tag", "text", on=on("plate", "-y"), text={"text": "V2", "from": SAY}, height=a(3), depth=a(0.4),
             mode=pick("emboss")),
    ]  # fmt: skip

    def build() -> Any:
        lib = m3()
        part = box((-30, -15, 0), (30, 15, 6))
        # On +z, centred on the face: up +y, running along +x; 0.6 deep, the cut running on through the air above.
        part -= lib.Manifold.extrude(letters("FORGE Ç&j", 6.0), 1.6).translate(
            (0, 0, 5.4)
        )
        # On -y, centred on the face at (0, -15, 3): up +z, running along up x outward = +x; standing 0.4 out,
        # its foot sunk a hair into the plate. Turned a quarter about x, (u, v, w) goes to (u, -w, v).
        stand = lib.Manifold.extrude(letters("V2", 3.0), 0.4 + OVERLAP).rotate(
            (90.0, 0.0, 0.0)
        )
        part += stand.translate((0, -15 + OVERLAP, 3))
        return part

    return items, build


TOPOLOGY = {
    "plate with holes": (1, 0, 6),
    "slots and pockets": (1, 0, 1),
    "bracket": (1, 0, 2),
    "flange": (1, 0, 7),
    "rod with a boss": (1, 0, 2),
    "tray": (1, 0, 1),
    "sealed box": (1, 0, 0),
    "cone on a plate": (1, 0, 2),
    "dome": (1, 0, 1),
    "tabs": (1, 0, 1),
    "ball on a plate": (1, 0, 0),
    "boss in a bore": (1, 0, 2),
    "post round a rod": (1, 0, 1),
    "closed box": (1, 1, 0),
    "a dome with a floor": (1, 1, 0),
    "covered pocket": (1, 1, 0),
    "two hollows": (1, 2, 0),
    "rounded block": (1, 0, 0),
    "post and its joint": (1, 0, 0),
    "cup": (1, 0, 0),
    "bevelled inside": (1, 0, 0),
    "a cup's floor": (1, 0, 0),
    "plate with rims": (1, 0, 1),
    "boss and dome": (1, 0, 0),
    "hollow box": (1, 0, 0),
    "threaded boss": (1, 0, 0),
    "outline plate": (1, 0, 1),
    "knob": (1, 0, 0),
    "outlines standing": (1, 0, 1),
    "rounded angle": (1, 0, 0),
    "rounded ring": (1, 0, 1),
    "over the edge": (1, 0, 4),
    "lettered plate": (1, 0, 0),
}

PARTS: dict[str, Callable[[], tuple[list[dict[str, Any]], Builder]]] = {
    "plate with holes": plate_with_holes,
    "slots and pockets": slots_and_pockets,
    "bracket": bracket,
    "flange": flange,
    "rod with a boss": rod_with_boss,
    "tray": tray,
    "sealed box": sealed_box,
    "cone on a plate": cone_on_plate,
    "dome": dome,
    "tabs": tabs,
    "ball on a plate": ball_on_plate,
    "boss in a bore": bore_boss,
    "post round a rod": post_round_a_rod,
    "closed box": closed_box,
    "a dome with a floor": floored_dome,
    "covered pocket": covered_pocket,
    "two hollows": two_hollows,
    "rounded block": rounded_block,
    "post and its joint": post_and_joint,
    "cup": cup,
    "bevelled inside": bevelled_inside,
    "a cup's floor": cup_floor,
    "plate with rims": plate_with_rims,
    "boss and dome": boss_and_dome,
    "hollow box": hollow_box,
    "threaded boss": threaded_boss,
    "outline plate": outline_plate,
    "knob": knob,
    "outlines standing": outlines_standing,
    "rounded angle": rounded_angle,
    "rounded ring": rounded_ring,
    "over the edge": over_the_edge,
    "lettered plate": lettered_plate,
}
