"""The judge's placement's face frames (forge_checks.place.FaceFrame; 4b.0c item 1a; V2-stage4b-0c.md, 3.3).

- **An aligned frame is exact:** a face's plane coordinates of a point are
  the coordinates its axis names choose, and a point placed in the plane
  sets them, keeping the face's level: no product with 0 or 1.
- **Any other frame is a rotation:** placing in the plane and reading back
  are inverse, and a point keeps its level along the normal.
- **The faces' frames are frame.md's and place.md's.**
"""

from __future__ import annotations

import math
import unittest

from forge_checks.outlines import Outline
from forge_checks.place import (
    FLAT_AXES,
    TURN_AXES,
    FaceFrame,
    FlatFace,
    RoundSide,
    Solid,
    unit,
)
from forge_numeric import scalar as fs


class AnAlignedFrameIsExact(unittest.TestCase):
    def test_plane_and_point(self) -> None:
        for n in ("+x", "-x", "+y", "-y", "+z", "-z"):
            a1, a2 = FLAT_AXES[n[1]]
            centre = (1.5, -0.0, 7.25)
            frame = FaceFrame.of_names(centre, a1, a2, n)
            k1, k2 = "xyz".index(a1), "xyz".index(a2)
            self.assertEqual(frame.plane(centre), (centre[k1], centre[k2]))
            point = frame.point(-0.0, 3.0)
            want = list(centre)
            want[k1], want[k2] = -0.0, 3.0
            self.assertEqual([v.hex() for v in point], [v.hex() for v in want])
            self.assertEqual(frame.level(point), frame.level(centre))
        down = FaceFrame.of_names((0.0, 0.0, 2.0), "x", "y", "-z")
        self.assertEqual(down.level((5.0, 6.0, 2.0)), -2.0)
        self.assertEqual(down.at_level((5.0, 6.0, 2.0), -3.0), (5.0, 6.0, 3.0))


class AnyOtherFrameIsARotation(unittest.TestCase):
    def test_inverse_and_level(self) -> None:
        c, s = fs.cos(math.radians(30.0)), fs.sin(math.radians(30.0))
        frame = FaceFrame((1.0, 2.0, 3.0), (c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0))
        for p in ((0.0, 0.0), (4.0, -2.5), (100.0, 1e-3)):
            back = frame.plane(frame.point(*p))
            self.assertAlmostEqual(back[0], p[0], delta=1e-12 * (1 + abs(p[0])))
            self.assertAlmostEqual(back[1], p[1], delta=1e-12 * (1 + abs(p[1])))
            self.assertAlmostEqual(frame.level(frame.point(*p)), 3.0, delta=1e-12)


class TheFacesFramesAreTheDefinitions(unittest.TestCase):
    def test_flat_faces_and_round_sides(self) -> None:
        face = FlatFace(
            "+y",
            (0.0, 5.0, 1.0),
            "+y",
            FLAT_AXES["y"],
            Outline.rect(2.0, 1.0, (0.0, 1.0)),
            Solid(10.0),
        )
        self.assertEqual(
            (face.frame.u, face.frame.v, face.frame.n),
            (unit("+x"), unit("+z"), unit("+y")),
        )
        for axis in "xyz":
            side = RoundSide("side", axis, (0.0, 0.0, 0.0), 10.0, 2.0, True, 0.0)
            u, v = TURN_AXES[axis]
            self.assertEqual((side.frame.u, side.frame.v, side.frame.n),
                             (unit("+" + u), unit("+" + v), unit("+" + axis)))  # fmt: skip


if __name__ == "__main__":
    unittest.main()
