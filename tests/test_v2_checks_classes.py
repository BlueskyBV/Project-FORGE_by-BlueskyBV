"""V2 stage 2, step 4: tolerances and verdicts (forge_checks.classes), and the capability table (forge_checks.capabilities).

The general tolerance is ISO 2768-1 class m as docs/definitions/sizes.md
writes it out, row by row and at each row's ends; a value's own tolerance is
taken in its own unit; a measurement passes only when all of it is within
the tolerance. The capability table answers for every kind of view and
every item kind, and a view is held when it can't answer what the table
says it must.
"""

from __future__ import annotations

import math
import unittest

from forge_checks.capabilities import (
    HOLDS,
    QUESTIONS,
    SOURCES,
    Answer,
    admit,
    answers,
    applicable,
    holds,
    required,
)
from forge_checks.classes import (
    LINEAR,
    RADIUS,
    Tolerance,
    Verdict,
    brackets,
    fine_enough,
    general,
    general_angle,
    judge,
    tolerance_of,
)
from forge_checks.mesh import MeshView, box_mesh
from forge_checks.view import Capability, ViewProxy
from forge_spec.schema import KINDS
from forge_spec.values import Provenance, Source, Value
from forge_spec.values import Tolerance as Stated
from forge_units import Interval, Q


def value(
    number: float, unit: str, plus: float | None = None, minus: float = 0.0
) -> Value:
    tolerance = None if plus is None else Stated(plus, minus)
    return Value(
        Q(number, unit), Provenance(Source.ASSUMED, reason="a test"), tolerance
    )


class GeneralTolerance(unittest.TestCase):
    def test_every_row_of_sizes_md_at_its_ends(self) -> None:
        rows = [  # (least, most, linear, radius)
            (0.5, 3, 0.1, 0.2), (3, 6, 0.1, 0.5), (6, 30, 0.2, 1.0), (30, 120, 0.3, 1.0),
            (120, 400, 0.5, 1.0), (400, 1000, 0.8, 1.0), (1000, 2000, 1.2, 1.0), (2000, 4000, 2.0, 1.0),
        ]  # fmt: skip
        for least, most, linear, radius in rows:
            for size in (math.nextafter(least, math.inf), (least + most) / 2, most):
                with self.subTest(size=size):
                    self.assertEqual(general(size).plus, linear)
                    self.assertEqual(general(size).minus, linear)
                    self.assertEqual(general(size, RADIUS).plus, radius)
        self.assertEqual(general(0.5).plus, 0.1)  # the first row starts at 0.5
        self.assertEqual(
            general(-25.0).plus, 0.2
        )  # a size's tolerance doesn't go by its sign

    def test_under_half_a_millimetre_and_over_four_metres(self) -> None:
        for size in (0.0, 0.2, math.nextafter(0.5, 0)):
            self.assertEqual(general(size), Tolerance(0.05, 0.05, "ISO 2768-m"))
            self.assertEqual(general(size, RADIUS).plus, 0.05)
        with self.assertRaises(ValueError):
            general(4000.5)
        with self.assertRaises(ValueError):
            general(math.inf)
        with self.assertRaises(ValueError):
            general(10.0, "angle")

    def test_angles_by_their_shorter_side(self) -> None:
        for side, degrees in ((0, 1.0), (10, 1.0), (10.01, 0.5), (50, 0.5), (50.1, 1 / 3),
                              (120, 1 / 3), (121, 1 / 6), (400, 1 / 6), (401, 1 / 12), (1e6, 1 / 12)):  # fmt: skip
            with self.subTest(side=side):
                self.assertAlmostEqual(general_angle(side).plus, degrees, places=12)
        with self.assertRaises(ValueError):
            general_angle(-1.0)


class AValuesTolerance(unittest.TestCase):
    def test_its_own_in_its_unit_half_its_band_about_the_made_size(self) -> None:
        # Made at the middle of its band (sizes.md), and held to the limits written.
        own = value(10, "mm", 0.1, 0.05)
        held = tolerance_of(own)
        self.assertEqual(held.source, "stated")
        self.assertAlmostEqual(held.plus, 0.075, places=12)
        self.assertEqual(held.plus, held.minus)
        self.assertAlmostEqual(own.made_in("mm"), 10.025, places=12)
        limits = tolerance_of(own).limits(own.made_in("mm"))
        self.assertAlmostEqual(limits.lo, 9.95, places=12)
        self.assertAlmostEqual(limits.hi, 10.1, places=12)
        inches = value(1, "in", 0.01, 0.0)
        self.assertAlmostEqual(tolerance_of(inches).plus, 0.127, places=12)
        self.assertAlmostEqual(tolerance_of(inches).minus, 0.127, places=12)
        self.assertAlmostEqual(inches.made_in("mm"), 25.527, places=12)
        radians = tolerance_of(value(0.5, "rad", 0.01, 0.01))
        self.assertAlmostEqual(radians.plus, math.degrees(0.01), places=12)
        # The same both ways: made at the nominal.
        self.assertEqual(value(0.5, "rad", 0.01, 0.01).made_in("rad"), 0.5)
        # A nominal of 0 still takes its tolerance's unit.
        self.assertAlmostEqual(tolerance_of(value(0, "cm", 0.1)).plus, 0.5, places=12)

    def test_the_general_one_otherwise(self) -> None:
        self.assertEqual(tolerance_of(value(2.5, "cm")), general(25.0))
        self.assertEqual(tolerance_of(value(4, "mm"), RADIUS), general(4.0, RADIUS))
        self.assertEqual(
            tolerance_of(value(90, "deg"), shorter_side=30.0), general_angle(30.0)
        )
        with self.assertRaises(ValueError):
            tolerance_of(value(90, "deg"))  # an angle's needs its shorter side
        with self.assertRaises(ValueError):
            tolerance_of(value(50, "%"))
        self.assertEqual(tolerance_of(value(10, "mm"), LINEAR), general(10.0))

    def test_what_isn_t_a_tolerance(self) -> None:
        for plus, minus in ((0.0, 0.0), (-0.1, 0.1), (math.nan, 0.1), (math.inf, 0.0)):
            with self.subTest(plus=plus, minus=minus), self.assertRaises(ValueError):
                Tolerance(plus, minus)
        with self.assertRaises(ValueError):
            Tolerance(1, 1)  # floats only, as everything measured is


class Verdicts(unittest.TestCase):
    def test_within_outside_and_across(self) -> None:
        t = Tolerance(0.1, 0.2)  # good from 9.8 to 10.1
        cases = [
            (Interval(9.8, 10.1), Verdict.PASS),
            (Interval(10.0, 10.0), Verdict.PASS),
            (Interval(10.05, 10.15), Verdict.INCONCLUSIVE),
            (Interval(9.7, 9.85), Verdict.INCONCLUSIVE),
            (Interval(10.11, 10.2), Verdict.FAIL),
            (Interval(9.0, 9.79), Verdict.FAIL),
            (Interval(9.0, 11.0), Verdict.INCONCLUSIVE),
            (Interval(-math.inf, math.inf), Verdict.INCONCLUSIVE),
            (Interval(10.0, math.inf), Verdict.INCONCLUSIVE),
        ]
        for measured, verdict in cases:
            with self.subTest(measured=measured):
                self.assertEqual(judge(measured, 10.0, t), verdict)

    def test_brackets_pass_inside_and_fail_outside(self) -> None:
        t = general(25.0)  # ±0.2
        u = 0.05
        self.assertTrue(fine_enough(u, t))
        self.assertFalse(fine_enough(0.051, t))
        self.assertFalse(fine_enough(-0.01, t))
        b = brackets(25.0, t, u)
        for size in b.near:
            self.assertEqual(judge(Interval(size - u, size + u), 25.0, t), Verdict.PASS)
        for size in b.beyond:
            self.assertEqual(judge(Interval(size - u, size + u), 25.0, t), Verdict.FAIL)
        with self.assertRaises(ValueError):
            brackets(25.0, t, 0.06)
        one_sided = Tolerance(0.015, 0.0)  # a fit's +0.015/0
        b = brackets(22.0, one_sided, 0.0015)
        self.assertAlmostEqual(b.near[0], 22.003, places=12)
        self.assertAlmostEqual(b.beyond[0], 21.997, places=12)


class CapabilityTable(unittest.TestCase):
    def test_every_source_and_every_kind_has_an_entry(self) -> None:
        self.assertEqual(set(QUESTIONS), set(SOURCES))
        self.assertEqual(set(HOLDS), set(SOURCES))
        for source in SOURCES:
            self.assertEqual(set(HOLDS[source]), set(KINDS), source)
            self.assertTrue(
                {Capability.CLASSIFY, Capability.COVERAGE} <= required(source)
            )

    def test_what_each_view_answers(self) -> None:
        for source in ("brep", "step-file"):
            self.assertEqual(required(source), frozenset(Capability))
        for source in ("mesh-file", "implicit"):
            self.assertFalse(answers(source, Capability.FACES))
            self.assertFalse(answers(source, Capability.EDGES))
            self.assertTrue(answers(source, Capability.DISTANCE))
        with self.assertRaises(ValueError):
            answers("photo", Capability.CLASSIFY)

    def test_how_each_view_holds_each_kind(self) -> None:
        for kind in KINDS:
            self.assertIs(holds("brep", kind), Answer.EXACT)
            self.assertIs(holds("mesh-file", kind), Answer.EXACT)
        for kind in ("fillet", "chamfer", "thread", "text", "region"):
            self.assertIs(holds("implicit", kind), Answer.NOT_APPLICABLE)
        for kind in ("block", "hole", "slot", "pocket", "boss", "shell"):
            self.assertIs(holds("implicit", kind), Answer.BOUNDED)
        with self.assertRaises(ValueError):
            holds("brep", "gear")

    def test_a_check_s_applicability_comes_from_the_table(self) -> None:
        classify = frozenset({Capability.CLASSIFY})
        faces = frozenset({Capability.FACES})
        self.assertIs(applicable("brep", faces, ("hole",)), Answer.EXACT)
        self.assertIs(applicable("mesh-file", faces, ("hole",)), Answer.NOT_APPLICABLE)
        self.assertIs(
            applicable("mesh-file", classify, ("hole", "fillet")), Answer.EXACT
        )
        self.assertIs(applicable("implicit", classify, ("hole",)), Answer.BOUNDED)
        self.assertIs(
            applicable("implicit", classify, ("hole", "fillet")), Answer.NOT_APPLICABLE
        )
        self.assertIs(applicable("implicit", classify, ()), Answer.EXACT)

    def test_a_view_that_can_t_answer_what_it_must_is_held(self) -> None:
        mesh = box_mesh((0, 0, 0), (1, 1, 1))
        self.assertEqual(
            admit(ViewProxy(MeshView(mesh, source="mesh-file", deflection=0.0))), ()
        )
        problems = admit(ViewProxy(MeshView(mesh, source="photo", deflection=0.0)))
        self.assertEqual(len(problems), 1)
        self.assertIn("photo", problems[0])

        class Shy(MeshView):
            capabilities = MeshView.capabilities - {Capability.DISTANCE}

        problems = admit(ViewProxy(Shy(mesh, source="mesh-file", deflection=0.0)))
        self.assertEqual(len(problems), 1)
        self.assertIn("distance", problems[0])


if __name__ == "__main__":
    unittest.main()
