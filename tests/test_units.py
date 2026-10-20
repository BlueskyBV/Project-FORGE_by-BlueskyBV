"""Tests for the dimensional / uncertainty type system.

Written against ``unittest`` from the standard library so that the trust core
can be verified in any environment, including a network-isolated sandbox
container with no test framework installed.
"""

from __future__ import annotations

import math
import unittest
from fractions import Fraction

from forge_units import (
    Dimension,
    DimensionalityError,
    Interval,
    IntervalError,
    OffsetUnitError,
    Q,
    Quantity,
    Trivalent,
    UnitSyntaxError,
    UnknownUnitError,
    all_true,
    any_true,
    parse_unit,
)
from forge_units import dimension as dims
from forge_units import mathfns
from forge_units.mathfns import MathDomainError


class DimensionAlgebra(unittest.TestCase):
    def test_derived_dimensions_compose_correctly(self) -> None:
        self.assertEqual(dims.LENGTH * dims.LENGTH, dims.AREA)
        self.assertEqual(dims.FORCE / dims.AREA, dims.PRESSURE)
        self.assertEqual(dims.MASS * dims.ACCELERATION, dims.FORCE)
        self.assertEqual(dims.FORCE * dims.LENGTH, dims.ENERGY)
        self.assertEqual(dims.ENERGY / dims.TIME, dims.POWER)

    def test_fractional_exponents_survive(self) -> None:
        half = dims.AREA ** Fraction(1, 2)
        self.assertEqual(half, dims.LENGTH)
        self.assertEqual(dims.AREA.root(2), dims.LENGTH)
        # A half-exponent must not be truncated to zero.
        odd = dims.LENGTH ** Fraction(1, 2)
        self.assertNotEqual(odd, dims.DIMENSIONLESS)
        self.assertEqual(odd * odd, dims.LENGTH)

    def test_round_trip_through_canonical_string(self) -> None:
        for dimension in (dims.FORCE, dims.PRESSURE, dims.THERMAL_CONDUCTIVITY):
            self.assertEqual(Dimension.parse(str(dimension)), dimension)

    def test_dimensionless_renders_as_one(self) -> None:
        self.assertEqual(str(dims.DIMENSIONLESS), "1")
        self.assertEqual(Dimension.parse(""), dims.DIMENSIONLESS)

    def test_describe_names_known_dimensions(self) -> None:
        self.assertEqual(dims.PRESSURE.describe(), "pressure or stress")


class UnitParsing(unittest.TestCase):
    def test_simple_symbols(self) -> None:
        self.assertEqual(parse_unit("mm").dimension, dims.LENGTH)
        self.assertEqual(parse_unit("kg").dimension, dims.MASS)
        self.assertAlmostEqual(parse_unit("mm").scale, 1e-3)

    def test_aliases_resolve_to_one_canonical_unit(self) -> None:
        self.assertIs(parse_unit("millimetre"), parse_unit("mm"))
        self.assertIs(parse_unit("millimeter"), parse_unit("mm"))
        self.assertEqual(parse_unit("millimetre").symbol, "mm")

    def test_compound_units(self) -> None:
        self.assertEqual(parse_unit("N/mm^2").dimension, dims.PRESSURE)
        self.assertAlmostEqual(parse_unit("N/mm^2").scale, 1e6)
        self.assertEqual(parse_unit("kg*m/s^2").dimension, dims.FORCE)
        self.assertAlmostEqual(parse_unit("kg*m/s^2").scale, 1.0)
        self.assertEqual(parse_unit("kg/m^3").dimension, dims.DENSITY)
        self.assertEqual(parse_unit("1/s").dimension, dims.FREQUENCY)

    def test_whitespace_is_implicit_multiplication(self) -> None:
        self.assertEqual(parse_unit("N m").dimension, parse_unit("N*m").dimension)
        self.assertAlmostEqual(parse_unit("N m").scale, parse_unit("N*m").scale)

    def test_trailing_whitespace_is_not_a_dangling_operator(self) -> None:
        self.assertEqual(parse_unit("mm ").dimension, dims.LENGTH)
        self.assertEqual(parse_unit("  N/mm^2  ").dimension, dims.PRESSURE)

    def test_rpm_agrees_with_rev_per_min(self) -> None:
        # A factor of 2*pi hiding between two spellings of the same unit is
        # exactly the class of error this module exists to prevent.
        self.assertAlmostEqual(
            parse_unit("rpm").scale, parse_unit("rev/min").scale, places=12
        )

    def test_unknown_unit_is_reported_with_its_symbol(self) -> None:
        with self.assertRaises(UnknownUnitError) as caught:
            parse_unit("furlong")
        self.assertEqual(caught.exception.detail["symbol"], "furlong")

    def test_malformed_unit_strings_are_rejected(self) -> None:
        for text in ("mm^", "*mm", "mm*", "mm/", "N//m"):
            with self.subTest(text=text):
                with self.assertRaises((UnitSyntaxError, UnknownUnitError)):
                    parse_unit(text)

    def test_affine_unit_inside_a_compound_is_rejected(self) -> None:
        with self.assertRaises(OffsetUnitError):
            parse_unit("W/(m*degC)".replace("(", "").replace(")", ""))
        with self.assertRaises(OffsetUnitError):
            parse_unit("J/degC")


class IntervalArithmetic(unittest.TestCase):
    def test_exact_interval_has_zero_width(self) -> None:
        self.assertTrue(Interval.exact(3.0).is_exact)
        self.assertEqual(Interval.exact(3.0).width, 0.0)

    def test_addition_and_subtraction_bounds(self) -> None:
        a, b = Interval(1.0, 2.0), Interval(10.0, 20.0)
        self.assertTrue((a + b).contains(11.0))
        self.assertTrue((a + b).contains(22.0))
        difference = b - a
        self.assertTrue(difference.contains(8.0))
        self.assertTrue(difference.contains(19.0))

    def test_multiplication_handles_sign_changes(self) -> None:
        product = Interval(-2.0, 3.0) * Interval(-5.0, 4.0)
        self.assertLessEqual(product.lo, -15.0)
        self.assertGreaterEqual(product.hi, 12.0)

    def test_even_power_over_zero_crossing(self) -> None:
        squared = Interval(-3.0, 2.0) ** 2
        self.assertEqual(squared.lo, 0.0)
        self.assertGreaterEqual(squared.hi, 9.0)

    def test_odd_power_is_monotonic(self) -> None:
        cubed = Interval(-3.0, 2.0) ** 3
        self.assertLessEqual(cubed.lo, -27.0)
        self.assertGreaterEqual(cubed.hi, 8.0)

    def test_division_by_zero_spanning_interval_fails_loudly(self) -> None:
        with self.assertRaises(IntervalError):
            Interval(1.0, 2.0) / Interval(-1.0, 1.0)

    def test_sqrt_of_negative_interval_fails(self) -> None:
        with self.assertRaises(IntervalError):
            Interval(-1.0, 4.0).sqrt()

    def test_soundness_under_random_sampling(self) -> None:
        """The result interval must contain every achievable point result."""
        import random

        rng = random.Random(20260911)
        for _ in range(2000):
            a_lo = rng.uniform(-10, 10)
            a_hi = a_lo + rng.uniform(0, 5)
            b_lo = rng.uniform(1, 10)  # kept positive so division is defined
            b_hi = b_lo + rng.uniform(0, 5)
            a, b = Interval(a_lo, a_hi), Interval(b_lo, b_hi)
            total, product, quotient = a + b, a * b, a / b
            for _ in range(8):
                x = rng.uniform(a_lo, a_hi)
                y = rng.uniform(b_lo, b_hi)
                self.assertTrue(total.contains(x + y))
                self.assertTrue(product.contains(x * y))
                self.assertTrue(quotient.contains(x / y))

    def test_hull_and_intersection(self) -> None:
        a, b = Interval(0.0, 2.0), Interval(1.0, 5.0)
        self.assertEqual(a.hull(b), Interval(0.0, 5.0))
        self.assertEqual(a.intersect(b), Interval(1.0, 2.0))
        self.assertIsNone(Interval(0.0, 1.0).intersect(Interval(2.0, 3.0)))


class TrivalentLogic(unittest.TestCase):
    def test_interval_comparison_yields_three_values(self) -> None:
        self.assertIs(Interval(4.0, 5.0).at_least(3.0), Trivalent.TRUE)
        self.assertIs(Interval(1.0, 2.0).at_least(3.0), Trivalent.FALSE)
        self.assertIs(Interval(2.9, 3.1).at_least(3.0), Trivalent.INDETERMINATE)

    def test_kleene_conjunction(self) -> None:
        T, F, U = Trivalent.TRUE, Trivalent.FALSE, Trivalent.INDETERMINATE
        self.assertIs(T & T, T)
        self.assertIs(T & U, U)
        self.assertIs(F & U, F)  # a known failure is not softened by an unknown
        self.assertIs(U & U, U)

    def test_kleene_disjunction(self) -> None:
        T, F, U = Trivalent.TRUE, Trivalent.FALSE, Trivalent.INDETERMINATE
        self.assertIs(T | U, T)
        self.assertIs(F | U, U)
        self.assertIs(F | F, F)

    def test_negation(self) -> None:
        self.assertIs(~Trivalent.TRUE, Trivalent.FALSE)
        self.assertIs(~Trivalent.INDETERMINATE, Trivalent.INDETERMINATE)

    def test_bool_is_refused(self) -> None:
        # Allowing truthiness would let `if comparison:` silently treat an
        # unknown result as a failure, which is the bug this type prevents.
        with self.assertRaises(TypeError):
            bool(Trivalent.INDETERMINATE)
        with self.assertRaises(TypeError):
            bool(Trivalent.TRUE)

    def test_aggregates(self) -> None:
        self.assertIs(all_true([]), Trivalent.TRUE)
        self.assertIs(any_true([]), Trivalent.FALSE)
        self.assertIs(
            all_true([Trivalent.TRUE, Trivalent.INDETERMINATE]),
            Trivalent.INDETERMINATE,
        )
        self.assertIs(
            all_true([Trivalent.FALSE, Trivalent.INDETERMINATE]), Trivalent.FALSE
        )


class QuantityBehaviour(unittest.TestCase):
    def test_conversion_round_trips(self) -> None:
        self.assertAlmostEqual(Q(6.0, "mm").to("m").magnitude.midpoint, 0.006)
        self.assertAlmostEqual(Q(1.0, "in").to("mm").magnitude.midpoint, 25.4)
        self.assertAlmostEqual(Q(1.0, "MPa").to("N/mm^2").magnitude.midpoint, 1.0)
        self.assertAlmostEqual(Q(1.0, "ksi").to("psi").magnitude.midpoint, 1000.0)

    def test_moment_composition(self) -> None:
        moment = Q(500, "N") * Q(35, "mm")
        self.assertAlmostEqual(moment.to("Nm").magnitude.midpoint, 17.5)
        self.assertEqual(moment.dimension, dims.MOMENT)

    def test_adding_incompatible_dimensions_raises(self) -> None:
        with self.assertRaises(DimensionalityError) as caught:
            _ = Q(1, "mm") + Q(1, "N")
        detail = caught.exception.detail
        self.assertIn("length", detail["left_measures"])
        self.assertIn("force", detail["right_measures"])

    def test_tolerance_propagates_through_arithmetic(self) -> None:
        width = Q(20.0, "mm", plus=0.1, minus=0.1)
        height = Q(10.0, "mm", plus=0.05, minus=0.05)
        area = width * height
        self.assertFalse(area.is_exact)
        self.assertTrue(area.magnitude.contains(200.0))
        self.assertTrue(area.magnitude.contains(20.1 * 10.05))
        self.assertTrue(area.magnitude.contains(19.9 * 9.95))

    def test_uncertain_value_against_threshold_is_indeterminate(self) -> None:
        thickness = Q(3.0, "mm", plus=0.1, minus=0.1)
        self.assertIs(thickness.at_least(Q(3.0, "mm")), Trivalent.INDETERMINATE)
        self.assertIs(thickness.at_least(Q(2.5, "mm")), Trivalent.TRUE)
        self.assertIs(thickness.at_least(Q(4.0, "mm")), Trivalent.FALSE)

    def test_exact_value_against_threshold_is_decisive(self) -> None:
        self.assertIs(Q(3.0, "mm").at_least(Q(3.0, "mm")), Trivalent.TRUE)

    def test_ordering_operators_are_refused(self) -> None:
        with self.assertRaises(TypeError):
            _ = Q(1, "mm") < Q(2, "mm")  # noqa: B015

    def test_comparison_across_units(self) -> None:
        self.assertIs(Q(1.0, "m").greater_than(Q(999.0, "mm")), Trivalent.TRUE)

    def test_dimensionless_compares_against_bare_number(self) -> None:
        self.assertIs(Q(2.5).at_least(2.0), Trivalent.TRUE)
        with self.assertRaises(DimensionalityError):
            Q(2.5, "mm").at_least(2.0)

    def test_celsius_difference_is_kelvin(self) -> None:
        difference = Q(80.0, "degC") - Q(20.0, "degC")
        self.assertEqual(difference.unit.symbol, "K")
        self.assertAlmostEqual(difference.magnitude.midpoint, 60.0)

    def test_celsius_to_kelvin(self) -> None:
        self.assertAlmostEqual(Q(25.0, "degC").to("K").magnitude.midpoint, 298.15)
        self.assertAlmostEqual(Q(32.0, "degF").to("degC").magnitude.midpoint, 0.0, places=9)

    def test_arithmetic_on_affine_scale_is_refused(self) -> None:
        with self.assertRaises(OffsetUnitError):
            _ = Q(20.0, "degC") * 2

    def test_serialisation_round_trip(self) -> None:
        for value in (
            Q(6.0, "mm"),
            Q(20.0, "mm", plus=0.1, minus=0.05),
            Q(500, "N"),
            Q(0.25),
        ):
            with self.subTest(value=str(value)):
                restored = Quantity.from_dict(value.as_dict())
                self.assertEqual(restored.unit.dimension, value.unit.dimension)
                self.assertAlmostEqual(restored.magnitude.lo, value.magnitude.lo)
                self.assertAlmostEqual(restored.magnitude.hi, value.magnitude.hi)

    def test_string_parsing(self) -> None:
        self.assertAlmostEqual(Quantity.parse("6 mm").to("mm").magnitude.lo, 6.0)
        self.assertAlmostEqual(Quantity.parse("6mm").to("mm").magnitude.lo, 6.0)
        self.assertAlmostEqual(Quantity.parse("-2.5e3 N").to("N").magnitude.lo, -2500.0)
        self.assertAlmostEqual(Quantity.parse("5 min").to("s").magnitude.lo, 300.0)
        parsed = Quantity.parse("[4, 6] mm")
        self.assertAlmostEqual(parsed.magnitude.lo, 4.0)
        self.assertAlmostEqual(parsed.magnitude.hi, 6.0)

    def test_power_and_root(self) -> None:
        area = Q(4.0, "mm") ** 2
        self.assertEqual(area.dimension, dims.AREA)
        self.assertAlmostEqual(area.to("mm^2").magnitude.midpoint, 16.0)
        side = area.sqrt()
        self.assertEqual(side.dimension, dims.LENGTH)
        self.assertAlmostEqual(side.to("mm").magnitude.midpoint, 4.0)

    def test_hashable_for_cache_keys(self) -> None:
        self.assertEqual(hash(Q(6.0, "mm")), hash(Q(6.0, "mm")))
        self.assertEqual(len({Q(6.0, "mm"), Q(6.0, "mm"), Q(7.0, "mm")}), 2)


class MathFunctions(unittest.TestCase):
    def test_trig_accepts_degrees_and_radians(self) -> None:
        self.assertAlmostEqual(mathfns.sin(Q(90, "deg")).magnitude.midpoint, 1.0)
        self.assertAlmostEqual(mathfns.cos(Q(0, "deg")).magnitude.midpoint, 1.0)
        self.assertAlmostEqual(
            mathfns.sin(Q(math.pi / 2, "rad")).magnitude.midpoint, 1.0
        )

    def test_periodic_interval_range_is_sound(self) -> None:
        # An interval spanning a turning point must report the true extremum,
        # not merely the endpoint values.
        wide = mathfns.sin(Q(Interval(0.0, math.pi), "rad"))
        self.assertAlmostEqual(wide.magnitude.hi, 1.0, places=9)
        full = mathfns.cos(Q(Interval(0.0, 7.0), "rad"))
        self.assertAlmostEqual(full.magnitude.lo, -1.0, places=9)
        self.assertAlmostEqual(full.magnitude.hi, 1.0, places=9)

    def test_trig_requires_dimensionless(self) -> None:
        with self.assertRaises(DimensionalityError):
            mathfns.sin(Q(1.0, "mm"))

    def test_domain_violations_raise(self) -> None:
        with self.assertRaises(MathDomainError):
            mathfns.asin(Q(1.5))
        with self.assertRaises(MathDomainError):
            mathfns.ln(Q(0.0))
        with self.assertRaises(MathDomainError):
            mathfns.sqrt(Q(-1.0, "mm^2"))

    def test_tan_across_a_pole_raises(self) -> None:
        with self.assertRaises(MathDomainError):
            mathfns.tan(Q(Interval(1.5, 1.7), "rad"))

    def test_hypot_preserves_dimension(self) -> None:
        result = mathfns.hypot(Q(3.0, "mm"), Q(4.0, "mm"))
        self.assertEqual(result.dimension, dims.LENGTH)
        self.assertAlmostEqual(result.to("mm").magnitude.midpoint, 5.0, places=9)

    def test_round_to_widens_outward(self) -> None:
        snapped = mathfns.round_to(Q(7.3, "mm"), Q(0.5, "mm"))
        self.assertLessEqual(snapped.magnitude.lo, 7.0)
        self.assertGreaterEqual(snapped.magnitude.hi, 7.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ExponentsAsPeopleWriteThem(unittest.TestCase):
    """`mm²` is a unit. Refusing it teaches nothing and costs a round.

    Observed live: a requirements set carrying `mm²` and `mm³` thresholds,
    refused three times with "`mm²` is not a unit" -- against a model that
    takes six minutes an attempt. The superscript is how the unit is written
    everywhere except a code editor, and the meaning is not in question.
    """

    def test_a_squared_unit_parses(self) -> None:
        self.assertEqual(parse_unit("mm²").symbol, "mm^2")
        self.assertEqual(parse_unit("mm²").dimension, parse_unit("mm^2").dimension)

    def test_a_cubed_unit_parses(self) -> None:
        self.assertEqual(parse_unit("mm³").symbol, "mm^3")

    def test_it_works_inside_a_compound_unit(self) -> None:
        self.assertEqual(
            parse_unit("N/mm²").dimension, parse_unit("MPa").dimension
        )
        self.assertEqual(
            parse_unit("kg/m³").dimension, parse_unit("kg/m^3").dimension
        )

    def test_consecutive_superscripts_are_one_exponent(self) -> None:
        """m¹² is m^12, not m^1^2."""
        self.assertEqual(parse_unit("m¹²").symbol, "m^12")

    def test_the_ascii_spelling_is_unchanged(self) -> None:
        self.assertEqual(parse_unit("mm^2").symbol, "mm^2")

    def test_a_superscript_quantity_round_trips(self) -> None:
        self.assertEqual(str(Q(900.0, "mm²")), "900 mm^2")
