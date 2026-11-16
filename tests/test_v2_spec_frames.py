"""The placement solver's frames (forge_spec.frames; 4b.0c item 1; V2-stage4b-0c.md, 3.3).

- **An aligned frame is exact:** a point placed on a face, a point read
  back off it, a direction split along its axes and a way out round a side
  are the coordinates the axis names choose, with their signs, never a
  product with 0 or 1 (so no 0.0 turns into -0.0).
- **Any other frame is a rotation:** placing and reading back are inverse,
  lengths are kept, and an aligned frame given as a general one gives the
  same numbers to rounding.
- **The faces' frames are frame.md's:** a flat face's axes are its table's,
  a round side's are the ways out at 0 and 90 degrees round it.
"""

from __future__ import annotations

import math
import unittest

from forge_numeric import scalar as fs
from forge_spec.frames import Frame, axis, name_of
from forge_spec.geometry import FlatFace, SideFace
from forge_spec.schema import DIRECTIONS, FACE_AXES


def _bits(values: tuple[float, ...]) -> tuple[str, ...]:
    return tuple(v.hex() for v in values)


class AnAlignedFrameIsExact(unittest.TestCase):
    def test_names_and_vectors(self) -> None:
        for name in DIRECTIONS:
            self.assertEqual(name_of(axis(name)), name)
        self.assertEqual(axis("y"), (0.0, 1.0, 0.0))
        self.assertIsNone(name_of((0.6, 0.8, 0.0)))
        self.assertIsNone(name_of((1.0, 1e-17, 0.0)))

    def test_by_choosing_coordinates(self) -> None:
        origin = (-0.0, 2.5, -7.25)
        for n in DIRECTIONS:
            a1, a2 = FACE_AXES[n]
            frame = Frame.of_names(origin, a1, a2, n)
            self.assertTrue(frame.aligned)
            self.assertEqual(frame.names(), ("+" + a1, "+" + a2, n))
            # The way the solver placed before frames: the face's centre, moved along its axes by name.
            want = list(origin)
            want["xyz".index(a1)] += 1.5
            want["xyz".index(a2)] += -0.0
            self.assertEqual(_bits(frame.at(1.5, -0.0)), _bits(tuple(want)))
            point = frame.at(1.5, -0.0)
            self.assertEqual(
                _bits(frame.on(point)),
                _bits((point["xyz".index(a1)] - origin["xyz".index(a1)],
                       point["xyz".index(a2)] - origin["xyz".index(a2)])),
            )  # fmt: skip
            self.assertEqual(frame.across(frame.n), (0.0, 0.0, 1.0))
        down = Frame.of_names((1.0, 2.0, 3.0), "-x", "+y", "-z")
        self.assertEqual(down.at(1.0, 1.0, 2.0), (0.0, 3.0, 1.0))
        self.assertEqual(down.on((0.0, 3.0, 9.0)), (1.0, 1.0))
        self.assertEqual(_bits(down.radial(0.0, 1.0)), _bits((-0.0, 1.0, 0.0)))
        self.assertEqual(down.across((0.0, 0.0, 5.0)), (-0.0, 0.0, -5.0))

    def test_round_a_side(self) -> None:
        frame = Frame.of_names((0.0, 0.0, 0.0), "y", "z", "x")
        self.assertEqual(_bits(frame.radial(1.0, 0.0)), _bits((0.0, 1.0, 0.0)))
        self.assertEqual(_bits(frame.radial(0.5, -0.25)), _bits((0.0, 0.5, -0.25)))


class AnyOtherFrameIsARotation(unittest.TestCase):
    def _turned(self, degrees: float) -> Frame:
        c, s = fs.cos(math.radians(degrees)), fs.sin(math.radians(degrees))
        return Frame((1.0, -2.0, 0.5), (c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0))

    def test_inverse_and_lengths(self) -> None:
        for degrees in (10.0, 33.0, 135.0, 271.5):
            frame = self._turned(degrees)
            self.assertFalse(frame.aligned)
            self.assertIsNone(frame.names())
            for p in ((0.0, 0.0), (3.0, -4.0), (1e3, 2.5)):
                back = frame.on(frame.at(*p))
                self.assertAlmostEqual(back[0], p[0], delta=1e-12 * (1 + abs(p[0])))
                self.assertAlmostEqual(back[1], p[1], delta=1e-12 * (1 + abs(p[1])))
            point = frame.at(3.0, 4.0, 12.0)
            d = [point[k] - frame.origin[k] for k in range(3)]
            self.assertAlmostEqual(fs.hypot(*d), 13.0, delta=1e-12)
            self.assertAlmostEqual(fs.hypot(*frame.radial(0.6, 0.8)), 1.0, delta=1e-15)

    def test_an_aligned_one_given_generally(self) -> None:
        exact = Frame.of_names((1.0, -2.0, 0.5), "x", "y", "+z")
        turned = self._turned(360.0)
        for p in ((0.0, 0.0), (3.0, -4.0), (1e3, 2.5)):
            for a, b in zip(exact.at(*p), turned.at(*p), strict=True):
                self.assertAlmostEqual(a, b, delta=1e-12)


class TheFacesFramesAreFrameMds(unittest.TestCase):
    def test_flat_faces_and_round_sides(self) -> None:
        for n in DIRECTIONS:
            a1, a2 = FACE_AXES[n]
            face = FlatFace(n, (1.0, 2.0, 3.0), n, (a1, a2), "rect", (5.0, 4.0))
            self.assertEqual(face.frame.names(), ("+" + a1, "+" + a2, n))
            self.assertEqual(face.frame.origin, face.centre)
        for along, (u, v) in (("z", ("x", "y")), ("x", ("y", "z")), ("y", ("z", "x"))):
            side = SideFace("side", along, (0.0, 1.0, 2.0), 10.0, 3.0)
            self.assertEqual(side.reference, (u, v))
            self.assertEqual(side.frame.names(), ("+" + u, "+" + v, "+" + along))
            self.assertEqual(side.frame.origin, side.start)


class AFacesFrameAtAPoint(unittest.TestCase):
    """Item 3a: a placeable face's frame at a point given in its own coordinates."""

    def test_on_a_flat_face(self) -> None:
        face = FlatFace("+z", (1.0, 2.0, 3.0), "+z", ("x", "y"), "rect", (5.0, 4.0))
        here = face.frame_at((1.5, -2.0))
        self.assertEqual(here.origin, (2.5, 0.0, 3.0))
        self.assertEqual(
            (here.u, here.v, here.n), (face.frame.u, face.frame.v, face.frame.n)
        )

    def test_round_a_side(self) -> None:
        def cross(
            a: tuple[float, float, float], b: tuple[float, float, float]
        ) -> tuple[float, float, float]:
            return (
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0],
            )

        rod = SideFace("side", "z", (0.0, 0.0, 0.0), 10.0, 3.0)
        here = rod.frame_at((0.0, 1.0), 2.0)  # 90 degrees round, 2 mm past the middle
        self.assertEqual(here.origin, (0.0, 3.0, 7.0))
        self.assertEqual(here.n, (0.0, 1.0, 0.0))
        self.assertEqual(here.v, (0.0, 0.0, 1.0))
        self.assertEqual(cross(here.u, here.v), here.n)
        bore = SideFace("bore", "x", (1.0, 0.0, 0.0), 4.0, 2.0, outward=False)
        inside = bore.frame_at((1.0, 0.0), 0.0)
        self.assertEqual(inside.origin, (3.0, 2.0, 0.0))
        self.assertEqual(inside.n, (-0.0, -1.0, -0.0))


if __name__ == "__main__":
    unittest.main()
