"""The generator's cones as first bodies (V2-stage4b-0c.md, 3.5, revision 18): plain, to a point, or hollowed.

A cone as the first body, one seed in twenty: narrower or wider at its top,
or to a point; its ends take what an end takes, its side what a cone's side
takes; hollowed half the time where its top is flat, a cut right through a
closed end coming out on the hollow's section there, which takes nothing
else. The exit pair runs them all; these hold what each such part is made
of, cheaply.
"""

from __future__ import annotations

import math
import random
import unittest

import numpy as np
from forge_eval.generator import _CONES, _DOMES, _TUBES, _build, generate


def _first_cone(seed: int) -> bool:
    roll = random.Random(f"forge-eval first bodies {seed}").random()
    return _TUBES + _DOMES <= roll < _TUBES + _DOMES + _CONES


class TheGeneratorsCones(unittest.TestCase):
    def test_one_seed_in_twenty_from_a_stream_of_its_own(self) -> None:
        cones = [seed for seed in range(5000) if _first_cone(seed)]
        self.assertTrue(200 <= len(cones) <= 300, len(cones))
        self.assertEqual(cones[:4], [13, 29, 45, 50])  # a seed it doesn't choose stays as it was drawn

    def test_a_hollow_cup_a_hole_through_its_floor_into_the_hollow(self) -> None:
        case = generate(162)  # narrower at its top, open there, its floor thicker than its walls
        body, shell = case.plan[0], next(f for f in case.plan if f.kind == "shell")
        self.assertEqual((body.kind, shell.faces), ("cone", ("+end",)))
        part = _build(case.plan, True)
        floor = part.flats[("body", 0, "-end")]
        inner = part.flats[("body", 0, "inner -end")]
        self.assertEqual((floor.material, floor.exit), (shell.sizes["floor"], inner.key))
        self.assertFalse(inner.takes)  # the hollow's section takes nothing else
        self.assertNotIn(("body", 0, "+end"), part.flats)  # its open end's rim takes nothing yet
        self.assertNotIn(("body", 0, "side"), part.cones)  # nor its side
        through = [f for f in case.plan if f.kind == "hole" and f.depth is None]
        self.assertEqual([f.on for f in through], [("body", "-end")])
        self.assertTrue(all(f.on is None or not f.on[1].startswith("inner") for f in case.plan))
        # The hollow's radius at its floor: the cone's there less the wall times the side's slant.
        rb, rt, length = body.sizes["base_diameter"] / 2, body.sizes["top_diameter"] / 2, body.sizes["length"]
        slant = math.hypot(length, rt - rb) / length
        t, f = shell.sizes["thickness"], shell.sizes["floor"]
        self.assertAlmostEqual(inner.half[0], rb + (rt - rb) * f / length - t * slant, places=9)
        points = np.array([[0.0, 0.0, f + 1.0], [4.0, -5.0, f - 1.0], [rb - 0.2, 0.0, 0.5], [-1.875, -1.779, 1.0]])
        assert case.truth is not None
        # The hollow, its floor, its wall at its foot, and the hole through its floor.
        self.assertEqual(case.truth.inside(points).tolist(), [False, True, True, False])

    def test_a_cone_wider_at_its_top_its_side_taking_things(self) -> None:
        case = generate(98)
        body = case.plan[0]
        self.assertEqual(body.kind, "cone")
        self.assertGreater(body.sizes["top_diameter"], body.sizes["base_diameter"])
        part = _build(case.plan, True)
        top = part.flats[("body", 0, "+end")]
        # Past its base's radius, what is under its top is the cone alone, down to its flank.
        self.assertEqual(top.flare, (body.sizes["base_diameter"] / 2, body.sizes["length"]))
        self.assertTrue(any(f.on == ("body", "side") for f in case.plan))


if __name__ == "__main__":
    unittest.main()
