"""V2 stage 2: what the adversarial review of the mesh view found, each kept found.

Every case here once gave a wrong answer, crashed, or took unbounded time or
memory. Geometric answers are checked against exact rationals
(tests/v2_exact.py), never against Forge's own arithmetic.
"""

from __future__ import annotations

import io
import math
import struct
import time
import unittest
import zipfile
from fractions import Fraction
from typing import Any

import numpy as np
from forge_checks.intersect import pairs_meet, simple_stars
from forge_checks.mesh import ON_BAND, Mesh, MeshView, box_mesh
from forge_checks.readers import MeshFileError, read_3mf, read_mesh_file, read_stl
from forge_checks.triangles import DISTANCE_ERROR
from forge_checks.view import (
    Capability,
    Crossings,
    NotAnswerableError,
    Side,
    Topology,
    ViewError,
    ViewProxy,
)
from numpy.typing import NDArray
from v2_exact import distance2, exact, side
from v2_meshes import HAVE_MANIFOLD, box_soup, triangles, view

Array = NDArray[np.float64]

#: A sound wedge with a 1e-4 rad knife edge, about 1 m from the origin, and
#: points just outside it whose distances to its two flanks differ by less
#: than rounding: once classified IN by the normal of the wrong flank.
WEDGE = np.array(
    [
        [[828.7165074377963, 781.1328313902139, 575.031131652668], [827.1853211495916, 800.8992098444247, 577.6666111831757], [827.1864778485922, 800.8995130960966, 577.6650080344452]],
        [[832.7774646967454, 781.0586142421266, 577.9471422760914], [831.2474351075414, 800.8252959480093, 580.5810186578686], [831.2462784085407, 800.8249926963374, 580.5826218065991]],
        [[828.7165074377963, 781.1328313902139, 575.031131652668], [827.1864778485922, 800.8995130960966, 577.6650080344452], [831.2474351075414, 800.8252959480093, 580.5810186578686]],
        [[828.7165074377963, 781.1328313902139, 575.031131652668], [831.2474351075414, 800.8252959480093, 580.5810186578686], [832.7774646967454, 781.0586142421266, 577.9471422760914]],
        [[827.1864778485922, 800.8995130960966, 577.6650080344452], [827.1853211495916, 800.8992098444247, 577.6666111831757], [831.2462784085407, 800.8249926963374, 580.5826218065991]],
        [[827.1864778485922, 800.8995130960966, 577.6650080344452], [831.2462784085407, 800.8249926963374, 580.5826218065991], [831.2474351075414, 800.8252959480093, 580.5810186578686]],
        [[827.1853211495916, 800.8992098444247, 577.6666111831757], [828.7165074377963, 781.1328313902139, 575.031131652668], [832.7774646967454, 781.0586142421266, 577.9471422760914]],
        [[827.1853211495916, 800.8992098444247, 577.6666111831757], [832.7774646967454, 781.0586142421266, 577.9471422760914], [831.2462784085407, 800.8249926963374, 580.5826218065991]],
    ]
)  # fmt: skip
WEDGE_POINTS = np.array(
    [
        [831.8388516858378, 781.0757680974009, 577.2731621043423],
        [831.7913152416287, 781.0766368444657, 577.2390282279542],
        [830.8224333611213, 781.0943437964812, 576.543313866041],
        [831.2516829133275, 781.086501138719, 576.8515241664876],
    ]
)


def knife(theta: float, offset: float, turn: float) -> Array:
    """A closed wedge, 20 long and 5 tall, with a knife edge of angle ``theta``, turned and moved."""
    h = 20.0 * math.tan(theta / 2)
    section = [(0.0, 0.0), (20.0, -h), (20.0, h)]
    v = np.array([[x, y, z] for z in (0.0, 5.0) for x, y in section])
    f = [[0, 2, 1], [3, 4, 5]]
    for i in range(3):
        j = (i + 1) % 3
        f += [[i, j, j + 3], [i, j + 3, i + 3]]
    c, s = math.cos(turn), math.sin(turn)
    spin = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]) @ np.array(
        [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]
    )
    v = v @ spin.T + offset
    return np.asarray(v[np.array(f)], dtype=np.float64)


class SidesAreRightWhereRoundingIsClose(unittest.TestCase):
    def test_the_knife_edge_near_tie(self) -> None:
        v = view(WEDGE)
        self.assertTrue(v.topology().sound)
        got = v.classify(WEDGE_POINTS)
        for k, p in enumerate(WEDGE_POINTS):
            if got[k] != Side.UNKNOWN:
                self.assertEqual(int(got[k]), side(WEDGE, p), k)

    def test_knife_edges_turned_and_far_off(self) -> None:
        rng = np.random.default_rng(1)
        for theta, offset in ((1e-4, 1e3), (8.7e-4, 1e4), (1e-5, 1e4)):
            soup = knife(theta, offset, 0.7)
            v = view(soup)
            self.assertTrue(v.topology().sound)
            edge = (soup[0, 0] + soup[1, 0]) / 2
            points = edge + rng.normal(size=(150, 3)) * 10.0 ** rng.uniform(
                -8, -4, (150, 1)
            )
            got = v.classify(points)
            decided = got != Side.UNKNOWN
            self.assertGreater(int(decided.sum()), 100)
            for k in np.flatnonzero(decided):
                self.assertEqual(int(got[k]), side(soup, points[k]), (theta, offset, k))

    def test_points_on_a_sliver_are_on(self) -> None:
        # A box whose top face holds a sliver 1e-5 wide along its diagonal:
        # points on it once measured 1.6e-6 away, and came out IN or OUT.
        soup = box_soup((0, 0, -1), (2, 2, 0))
        sides = soup[~(soup[:, :, 2] == 0.0).all(axis=1)]  # all but the top face
        a, c, b = (0.0, 0.0, 0.0), (0.9, 0.9, 0.0), (1.8, 1.8 - 1e-5, 0.0)
        p20, p22, p02 = (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)
        top = np.array(
            [
                [a, b, c],
                [a, p20, b],
                [p20, p22, b],
                [c, b, p22],
                [c, p22, p02],
                [a, c, p02],
            ]
        )
        v = view(np.concatenate([sides, top]))
        self.assertTrue(v.topology().sound, v.topology())
        w = np.random.default_rng(2).dirichlet((1, 1, 1), size=500)
        on = w @ np.array([a, b, c])
        self.assertTrue((v.classify(on) == Side.ON).all())
        self.assertLess(float(v.distance(on).max()), ON_BAND)

    @unittest.skipUnless(HAVE_MANIFOLD, "manifold3d makes the spheres")
    def test_small_parts_far_away_face_the_right_way(self) -> None:
        import manifold3d as m3

        rng = np.random.default_rng(3)
        for radius, far in ((0.05, 1e4), (0.1, 1e5)):
            ball = (
                triangles(m3.Manifold.sphere(radius, 48))
                + rng.uniform(0.5, 1.0, 3) * far
            )
            t = view(ball).topology()
            self.assertTrue(t.sound)
            self.assertEqual(t.solids, 1)
            inside_out = view(ball[:, [0, 2, 1]]).topology()
            self.assertFalse(inside_out.sound)
            self.assertEqual(inside_out.misnested, 1)


class TheSecondReview(unittest.TestCase):
    """What a second adversarial review found in the fixes, each kept found."""

    def test_two_sides_at_a_needle_s_tip_near_tied(self) -> None:
        r, length, off = 1e-4, 10.0, 1000.0
        v = (
            np.array(
                [[r * math.cos(a), r * math.sin(a), 0.0] for a in (0.0, 2.1, 4.2)]
                + [[0.0, 0.0, length]]
            )
            + off
        )
        f = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
        view = MeshView(Mesh(v, f), source="m", deflection=0.0)
        self.assertTrue(view.topology().sound)
        tip = v[3]
        rng = np.random.default_rng(4)
        points = np.concatenate(
            [
                np.array([[1000.0000000089443, 1000.0, 1009.9999999955279]]),
                tip + rng.normal(size=(300, 3)) * 10.0 ** rng.uniform(-9, -5, (300, 1)),
            ]
        )
        got = view.classify(points)
        self.assertEqual(int(got[0]), Side.OUT)
        decided = np.flatnonzero(got != Side.UNKNOWN)
        self.assertGreater(len(decided), 200)
        for k in decided:
            if got[k] == Side.ON:  # within the band: the exact distance must say so
                d2 = min(
                    distance2(exact(points[k]), *(exact(x) for x in t)) for t in v[f]
                )
                self.assertLessEqual(d2, Fraction(ON_BAND) ** 2, k)
            else:
                self.assertEqual(int(got[k]), side(v[f], points[k]), k)

    def test_points_at_a_sphere_s_centre(self) -> None:
        soup = box_soup((-5, -5, -5), (5, 5, 5))
        rng = np.random.default_rng(5)
        if HAVE_MANIFOLD:
            import manifold3d as m3

            soup = triangles(m3.Manifold.sphere(5.0, 48))
        v = view(soup)
        points = rng.normal(size=(2000, 3)) * 1e-4
        started = time.perf_counter()
        self.assertTrue((v.classify(points) == Side.IN).all())
        self.assertLess(time.perf_counter() - started, 30.0)

    def test_a_corrupt_file_of_zeros(self) -> None:
        data = b"\0" * 80 + struct.pack("<I", 40000) + b"\0" * (50 * 40000)
        v = read_stl(data).view(0.0)
        started = time.perf_counter()
        self.assertEqual(v.topology().bad_triangles, 40000)
        self.assertLess(time.perf_counter() - started, 10.0)

    def test_thousands_of_copies_of_one_triangle(self) -> None:
        soup = np.repeat(box_soup((0, 0, 0), (1, 1, 1))[:1], 3000, axis=0)
        started = time.perf_counter()
        t = view(soup).topology()
        self.assertEqual(t.self_intersections, 3000 * 2999 // 2)
        self.assertLess(time.perf_counter() - started, 10.0)

    def test_many_fans_cost_what_they_are(self) -> None:
        n, k = 16, 4
        verts: dict[tuple[object, ...], int] = {}
        points: list[tuple[float, float, float]] = []

        def vid(key: tuple[object, ...], xyz: tuple[float, float, float]) -> int:
            if key not in verts:
                verts[key] = len(points)
                points.append(xyz)
            return verts[key]

        faces: list[list[int]] = []
        for z, flip in ((1.0, False), (0.0, True)):
            for i in range(n):
                for j in range(n):
                    c = vid(("c", i, j, z), (i + 0.5, j + 0.5, z))
                    ring = [(i * k + s, j * k) for s in range(k)]
                    ring += [((i + 1) * k, j * k + s) for s in range(k)]
                    ring += [((i + 1) * k - s, (j + 1) * k) for s in range(k)]
                    ring += [(i * k, (j + 1) * k - s) for s in range(k)]
                    ids = [vid(("g", a, b, z), (a / k, b / k, z)) for a, b in ring]
                    for t in range(len(ids)):
                        tri = [c, ids[t], ids[(t + 1) % len(ids)]]
                        faces.append(tri[::-1] if flip else tri)
        mesh = Mesh(np.array(points, dtype=np.float64), np.array(faces, dtype=np.int64))
        good = np.ones(len(faces), dtype=bool)
        started = time.perf_counter()
        simple = simple_stars(mesh.vertices, mesh.faces, good)
        self.assertEqual(int(simple.sum()), 2 * n * n)
        self.assertLess(time.perf_counter() - started, 5.0)

    def test_empty_components_doubled_forty_deep(self) -> None:
        resources = TRIANGLE + '<object id="2"><components/></object>'
        for k in range(40):
            resources += (
                f'<object id="{k + 3}"><components><component objectid="{k + 2}"/>'
                f'<component objectid="{k + 2}"/></components></object>'
            )
        resources += '<object id="43"><components><component objectid="42"/><component objectid="1"/></components></object>'
        started = time.perf_counter()
        read = read_3mf(package(model(resources, '<item objectid="43"/>')))
        self.assertEqual(len(read.triangles), 1)
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_a_chain_of_three_thousand_components(self) -> None:
        resources = TRIANGLE + "".join(
            f'<object id="{k + 2}"><components><component objectid="{k + 1}"/></components></object>'
            for k in range(3000)
        )
        read = read_3mf(package(model(resources, '<item objectid="3001"/>')))
        self.assertEqual(len(read.triangles), 1)

    def test_numbers_ids_and_parts_out_of_bounds(self) -> None:
        refused = {
            "a huge vertex number": TRIANGLE.replace(
                'v3="2"', 'v3="99999999999999999999"'
            ),
            "a 5000-digit id": TRIANGLE.replace('id="1"', 'id="1' + "0" * 5000 + '"'),
            "two meshes": TRIANGLE.replace(
                "</mesh>", "</mesh><mesh><vertices/><triangles/></mesh>"
            ),
            "two vertex lists": TRIANGLE.replace(
                "<triangles>", "<vertices/><triangles>"
            ),
            "a number with a trailing point": TRIANGLE.replace('x="1"', 'x="1."'),
        }
        for why, resources in refused.items():
            item = (
                '<item objectid="1"/>' if "5000" not in why else '<item objectid="2"/>'
            )
            with self.assertRaises(MeshFileError, msg=why):
                read_3mf(package(model(resources, item)))
        spaced = TRIANGLE.replace('x="1"', 'x=" 1 "')
        self.assertEqual(
            read_3mf(package(model(spaced, '<item objectid="1"/>'))).triangles[0, 1, 0],
            1.0,
        )
        dotted = RELS.replace('Target="/3D/', 'Target="./3D/')
        self.assertEqual(
            len(
                read_3mf(
                    package(model(TRIANGLE, '<item objectid="1"/>'), dotted)
                ).triangles
            ),
            1,
        )

    def test_the_proxy_takes_no_masked_answers_and_no_broken_views(self) -> None:
        class Subclass(np.ndarray[Any, np.dtype[np.float64]]):  # as a masked array is
            pass

        hiding = np.array([1.0, 2.0]).view(Subclass)
        with self.assertRaises(ViewError):
            ViewProxy(Answering(hiding)).distance(np.zeros((2, 3)))

        class Broken:
            @property
            def source(self) -> str:
                raise RuntimeError("the kernel crashed")

            capabilities = frozenset(Capability)

        with self.assertRaises(ViewError):
            ViewProxy(Broken())  # type: ignore[arg-type]


class TheThirdReview(unittest.TestCase):
    """What a third adversarial review found, each kept found."""

    def test_just_past_a_needle_s_tip(self) -> None:
        # The foot on a long side's plane, judged inside by rounding though far
        # past the tip: once measured too near, and called IN.
        v = np.array(
            [
                [0.20091575102000453, 0.5805309931367143, -0.3947221348966251],
                [0.20091918661981237, 0.5805205782594368, -0.3947086925677281],
                [0.20092344510468788, 0.5805373841701601, -0.3947080633680426],
                [-89.27718234236713, 21.782374299222752, 38.90097485617946],
            ]
        )
        f = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
        view = MeshView(Mesh(v, f), source="m", deflection=0.0)
        self.assertTrue(view.topology().sound)
        point = np.array([[-89.27718234042881, 21.782374304893978, 38.90097486007803]])
        want = math.sqrt(
            min(distance2(exact(point[0]), *(exact(x) for x in t)) for t in v[f])
        )
        got = float(view.distance(point)[0])
        self.assertLessEqual(abs(got - want), DISTANCE_ERROR * 200.0)
        self.assertEqual(int(view.classify(point)[0]), side(v[f], point[0]))
        # And around the tip, every decided side is the exact one.
        rng = np.random.default_rng(6)
        near = v[3] + rng.normal(size=(300, 3)) * 10.0 ** rng.uniform(-10, -6, (300, 1))
        got_sides = view.classify(near)
        for k in np.flatnonzero((got_sides == Side.IN) | (got_sides == Side.OUT)):
            self.assertEqual(int(got_sides[k]), side(v[f], near[k]), k)

    def test_a_long_chain_under_a_diamond(self) -> None:
        resources = TRIANGLE + "".join(
            f'<object id="{k}"><components><component objectid="{k - 1}"/></components></object>'
            for k in range(2, 1002)
        )
        top = 1001
        for _ in range(16):
            resources += (
                f'<object id="{top + 1}"><components><component objectid="{top}"/>'
                f'<component objectid="{top}"/></components></object>'
            )
            top += 1
        started = time.perf_counter()
        with self.assertRaises(MeshFileError):
            read_3mf(package(model(resources, f'<item objectid="{top}"/>')))
        self.assertLess(time.perf_counter() - started, 5.0)

    def test_a_corrupt_lzma_part(self) -> None:
        good = package(
            model(TRIANGLE, '<item objectid="1"/>'), compress=zipfile.ZIP_LZMA
        )
        self.assertEqual(len(read_3mf(good).triangles), 1)
        info = zipfile.ZipFile(io.BytesIO(good)).getinfo("3D/3dmodel.model")
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        for at in (2, 4):
            broken = bytearray(good)
            broken[start + at] = 0
            with self.assertRaises(MeshFileError, msg=at):
                read_3mf(bytes(broken))

    def test_numbers_and_names_as_3mf_writes_them(self) -> None:
        odd_space = "1\u20030 0 0 1 0 0 0 1 0 0 0"  # an em space between the first two
        with self.assertRaises(MeshFileError):
            read_3mf(
                package(
                    model(TRIANGLE, f'<item objectid="1" transform="{odd_space}"/>')
                )
            )
        padded = TRIANGLE.replace('id="1"', 'id="0000000000000000001"')
        self.assertEqual(
            len(read_3mf(package(model(padded, '<item objectid="1"/>'))).triangles), 1
        )
        with self.assertRaises(MeshFileError):  # ids are 1 or more
            read_3mf(
                package(
                    model(TRIANGLE.replace('id="1"', 'id="0"'), '<item objectid="0"/>')
                )
            )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("_rels/.rels", RELS.replace("3dmodel.model", "my%20model.model"))
            z.writestr("3D/my%20model.model", model(TRIANGLE, '<item objectid="1"/>'))
        self.assertEqual(len(read_3mf(buffer.getvalue()).triangles), 1)

    def test_a_source_that_misbehaves(self) -> None:
        class Odd(str):
            def __len__(self) -> int:
                raise RuntimeError("no length")

        class View:
            source = Odd("odd")
            capabilities = frozenset(Capability)

        with self.assertRaises(ViewError):
            ViewProxy(View())  # type: ignore[arg-type]


class NothingMalformedComesBack(unittest.TestCase):
    def test_a_sliver_too_thin_for_a_float_normal(self) -> None:
        # Exact area, but a floating-point cross product of zero: once a NaN
        # normal in the coverage.
        soup = box_soup((0, 0, 0), (1, 1, 1))
        top = np.flatnonzero(soup[:, :, 2].min(axis=1) == 1.0)[0]
        a, b, c = soup[top]
        thin = np.nextafter(
            a, a + (b - a)
        )  # a corner nudged by one unit in the last place
        soup = np.concatenate(
            [np.delete(soup, top, axis=0), [[a, thin, c], [thin, b, c]]]
        )
        v = view(soup)
        cover = ViewProxy(v).coverage(0.2)
        self.assertTrue(np.isfinite(cover.normals).all())

    def test_no_finite_triangle(self) -> None:
        nan = math.nan
        soup = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [nan, 1.0, 0.0]]])
        v = view(soup)
        self.assertEqual(v.topology().bad_triangles, 1)
        self.assertEqual(v.classify(np.zeros((1, 3))).tolist(), [Side.UNKNOWN])
        proxy = ViewProxy(v)
        for ask in (
            lambda: proxy.distance(np.zeros((1, 3))),
            lambda: proxy.coverage(0.5),
        ):
            with self.assertRaises(ViewError):
                ask()

    def test_huge_coordinates(self) -> None:
        proxy = ViewProxy(
            MeshView(box_mesh((0, 0, 0), (1, 1, 1)), source="m", deflection=0.0)
        )
        with self.assertRaises(ValueError):
            proxy.distance(np.array([[1e155, 0.0, 0.0]]))
        self.assertEqual(
            proxy.distance(np.array([[1e29, 0.0, 0.0]])).tolist(), [1e29 - 1]
        )
        far = box_soup((0, 0, 0), (1, 1, 1))
        far[0, 0, 0] = 1e31
        self.assertGreaterEqual(view(far).topology().bad_triangles, 1)


class Answering:
    """A view that gives the same answer to every question."""

    source = "fake"
    capabilities = frozenset(Capability)

    def __init__(self, answer: object) -> None:
        self.answer = answer

    def __getattr__(self, name: str) -> Any:
        return lambda *args: self.answer


class TheProxyHoldsTheLine(unittest.TestCase):
    def proxy(self) -> ViewProxy:
        return ViewProxy(
            MeshView(box_mesh((0, 0, 0), (1, 1, 1)), source="m", deflection=0.0)
        )

    def test_directions_of_any_size(self) -> None:
        proxy = self.proxy()
        for size in (1e200, 1e-200):
            found = proxy.crossings(
                np.array([[0.3, 0.6, -1.0]]), np.array([[0.0, 0.0, size]])
            )
            np.testing.assert_allclose(found.t, [1.0, 2.0])
            self.assertEqual(found.grazed.tolist(), [False])

    def test_only_the_protocol_can_be_asked(self) -> None:
        proxy = self.proxy()
        for question in ("__getattribute__", "with_deflection", "mesh", "shape"):
            with self.assertRaises(AttributeError):
                proxy._answer(question)

    def test_answers_of_the_wrong_kind(self) -> None:
        for question, answer in (
            ("classify", np.ones(2, dtype=bool)),  # booleans for sides
            ("distance", np.array([0.0, np.nan])),
        ):
            with self.assertRaises(ViewError, msg=question):
                getattr(ViewProxy(Answering(answer)), question)(np.zeros((2, 3)))
        with self.assertRaises(ViewError):  # grazes that aren't booleans
            Crossings(
                np.zeros(0, np.int64), np.zeros(0), np.zeros(0, bool), np.full(1, 7)
            )
        with self.assertRaises(ViewError):  # a negative count
            Topology(-1, 1, 0, 0, 0, 0, 0, 0, 0, (0,))

    def test_a_view_that_fails_holds_the_part(self) -> None:
        class Failing:
            source = "failing"
            capabilities = frozenset(Capability)

            def topology(self) -> Topology:
                raise RuntimeError("the kernel fell over")

            def faces(self) -> Any:
                raise NotAnswerableError("no faces here")

        proxy = ViewProxy(Failing())  # type: ignore[arg-type]
        with self.assertRaises(ViewError):
            proxy.topology()
        with self.assertRaises(NotAnswerableError):
            proxy.faces()


RELS = (
    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="r0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
)


def package(
    model: str | bytes, rels: str = RELS, *, compress: int = zipfile.ZIP_STORED
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compress) as z:
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return buffer.getvalue()


CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
TRIANGLE = (
    '<object id="1"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>'
    '<vertex x="0" y="1" z="0"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/>'
    "</triangles></mesh></object>"
)


def model(resources: str, build: str, extra: str = "") -> str:
    return f'<model unit="millimeter" xmlns="{CORE}" {extra}><resources>{resources}</resources><build>{build}</build></model>'


class FilesAreReadForSureOrRefused(unittest.TestCase):
    def test_a_transform_that_flattens_exactly(self) -> None:
        flat = "2.0 1.8571428571428572 -2.142857142857143 -2.857142857142857 2.0 1.1428571428571428 4.571428571428571 22.857142857142858 -12.571428571428571 0 0 0"
        with self.assertRaises(MeshFileError):
            read_3mf(
                package(model(TRIANGLE, f'<item objectid="1" transform="{flat}"/>'))
            )
        tiny = "1e-110 0 0 0 1e-110 0 0 0 1e-110 0 0 0"  # doesn't flatten: read, and judged later
        read = read_3mf(
            package(model(TRIANGLE, f'<item objectid="1" transform="{tiny}"/>'))
        )
        self.assertEqual(len(read.triangles), 1)

    def test_a_document_type_in_any_encoding(self) -> None:
        text = model(TRIANGLE, '<item objectid="1"/>').replace(
            "<model", '<!DOCTYPE model [<!ENTITY far "1e6">]><model', 1
        )
        for encoding, declared in (("utf-8", "UTF-8"), ("utf-16", "UTF-16")):
            data = f'<?xml version="1.0" encoding="{declared}"?>{text}'.encode(encoding)
            with self.assertRaises(MeshFileError, msg=encoding):
                read_3mf(package(data))

    def test_every_way_a_package_fails_to_unpack(self) -> None:
        good = package(
            model(TRIANGLE, '<item objectid="1"/>'), compress=zipfile.ZIP_DEFLATED
        )
        read_3mf(good)
        stored = package(model(TRIANGLE, '<item objectid="1"/>'))
        where = stored.find(b"<model")
        bad_crc = stored[:where] + bytes([stored[where] ^ 1]) + stored[where + 1 :]
        start = good.rfind(b"PK\x03\x04")
        body = start + 30 + len("3D/3dmodel.model")
        broken = good[: body + 5] + bytes([good[body + 5] ^ 0xFF]) + good[body + 6 :]

        def flagged(data: bytes, offset: int, value: int) -> bytes:
            return data[:offset] + struct.pack("<H", value) + data[offset + 2 :]

        central = stored.find(
            b"PK\x01\x02"
        )  # the first member's central directory entry
        encrypted = flagged(stored, central + 8, 1)  # its general-purpose flag
        unknown = flagged(
            flagged(stored, central + 10, 99), 8, 99
        )  # its compression method
        for why, data in {"a bad checksum": bad_crc, "broken deflate": broken,
                          "encrypted": encrypted, "an unknown method": unknown}.items():  # fmt: skip
            with self.assertRaises(MeshFileError, msg=why):
                read_mesh_file(data)

    def test_two_parts_with_one_name(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("_rels/.rels", "x")
            z.writestr("_RELS/.rels", "y")
        with self.assertRaises(MeshFileError):
            read_3mf(buffer.getvalue())

    def test_components_that_multiply(self) -> None:
        resources = TRIANGLE + "".join(
            f'<object id="{k + 2}"><components><component objectid="{k + 1}"/>'
            f'<component objectid="{k + 1}" transform="1 0 0 0 1 0 0 0 1 0 0 {k + 1}"/>'
            "</components></object>"
            for k in range(20)
        )
        started = time.perf_counter()
        with self.assertRaises(MeshFileError):
            read_3mf(package(model(resources, '<item objectid="21"/>')))
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_a_prefix_is_looked_up_where_it_is_declared(self) -> None:
        lattice = (
            'xmlns:b="http://schemas.microsoft.com/3dmanufacturing/beamlattice/2017/02"'
        )
        text = model(
            TRIANGLE, '<item objectid="1"/>', extra='requiredextensions="b"'
        ).replace("<resources>", f"<resources {lattice}>")
        with self.assertRaises(MeshFileError):
            read_3mf(package(text))

    def test_a_percent_encoded_start_part(self) -> None:
        rels = RELS.replace("3dmodel.model", "3d%6Dodel.model")
        self.assertEqual(
            len(
                read_3mf(
                    package(model(TRIANGLE, '<item objectid="1"/>'), rels)
                ).triangles
            ),
            1,
        )

    def test_numbers_are_written_as_numbers(self) -> None:
        for odd in (
            "1_0",
            chr(0x661),
            "0x1",
            "1e",
            ".",
            "+-1",
        ):  # 0x661: an Arabic-Indic one
            with self.assertRaises(MeshFileError, msg=odd):
                read_3mf(
                    package(
                        model(
                            TRIANGLE.replace('x="1"', f'x="{odd}"'),
                            '<item objectid="1"/>',
                        )
                    )
                )
        text = (
            "solid a\nfacet normal 0 0 0\nouter loop\nvertex 0 0 0\nvertex 1_0 0 0\nvertex 0 1 0\n"
            "endloop\nendfacet\nendsolid a\n"
        )
        with self.assertRaises(MeshFileError):
            read_stl(text.encode("ascii"))
        with self.assertRaises(MeshFileError):
            read_stl(
                text.replace("1_0", "1").replace("\nouter", "\x0couter").encode("ascii")
            )
        nan = text.replace("1_0", "nan").encode("ascii")
        self.assertTrue(np.isnan(read_stl(nan).triangles).any())


class BoundedTimeAndMemory(unittest.TestCase):
    def test_a_cone_with_a_thousand_sides(self) -> None:
        n = 1000
        angle = np.linspace(0, 2 * np.pi, n, endpoint=False)
        ring = np.stack([10 * np.cos(angle), 10 * np.sin(angle), np.zeros(n)], 1)
        v = np.concatenate([ring, [[0, 0, 5.0], [0, 0, 0.0]]])
        faces = [[i, (i + 1) % n, n] for i in range(n)] + [
            [(i + 1) % n, i, n + 1] for i in range(n)
        ]
        mesh = Mesh(v, np.array(faces))
        simple = simple_stars(
            mesh.vertices, mesh.faces, np.ones(len(faces), dtype=bool)
        )
        self.assertTrue(simple[n] and simple[n + 1])
        started = time.perf_counter()
        self.assertTrue(MeshView(mesh, source="m", deflection=0.0).topology().sound)
        self.assertLess(time.perf_counter() - started, 20.0)

    def test_a_fan_folded_over_itself_is_not_simple(self) -> None:
        # Flat, round its centre twice: the second turn lies over the first.
        n = 40
        angle = np.linspace(0, 4 * np.pi, n, endpoint=False)
        radius = np.where(np.arange(n) < n // 2, 1.0, 2.0)
        ring = np.stack(
            [radius * np.cos(angle), radius * np.sin(angle), np.zeros(n)], 1
        )
        v = np.concatenate([ring, [[0.0, 0.0, 0.0]]])
        faces = np.array([[i, (i + 1) % n, n] for i in range(n)])
        simple = simple_stars(v, faces, np.ones(n, dtype=bool))
        self.assertFalse(simple[n])
        self.assertTrue(pairs_meet(v, faces, np.array([0]), np.array([n // 2]))[0])
        # A helical fan goes round twice too, though its turns never touch:
        # not proved simple, so its pairs are tested one by one.
        helix = np.stack([np.cos(angle), np.sin(angle), 0.01 * np.arange(n)], 1)
        w = np.concatenate([helix, [[0.0, 0.0, 1.0]]])
        self.assertFalse(simple_stars(w, faces, np.ones(n, dtype=bool))[n])
        self.assertFalse(pairs_meet(w, faces, np.array([0]), np.array([n // 2]))[0])

    def test_coverage_of_a_large_box_at_a_fine_radius(self) -> None:
        v = MeshView(box_mesh((0, 0, 0), (50, 50, 5)), source="m", deflection=0.0)
        cover = v.coverage(0.25)
        self.assertLessEqual(cover.radius, 0.25)
        self.assertLess(len(cover.points), 400_000)

    def test_coverage_far_from_the_origin_keeps_its_promise(self) -> None:
        soup = box_soup((0, 0, 0), (1, 1, 1)) + 1e6
        v = view(soup)
        cover = v.coverage(0.01)
        self.assertLessEqual(cover.radius, 0.01)
        with self.assertRaises(ValueError):
            v.coverage(1e-12)

    def test_two_crossings_rounding_can_not_tell_apart_graze(self) -> None:
        # A ray clipping a box's corner exactly: entering and leaving at once.
        v = MeshView(box_mesh((0, 0, 0), (1, 1, 1)), source="m", deflection=0.0)
        found = v.crossings(
            np.array([[1.0 - 1e-17, -1.0, 0.5]]), np.array([[0.0, 1.0, 0.0]])
        )
        if len(found.t) >= 2:
            self.assertTrue(found.grazed[0])


if __name__ == "__main__":
    unittest.main()
