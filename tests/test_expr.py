"""Tests for the expression engine and parameter graph.

The security tests matter as much as the arithmetic ones: expressions reach this
package from language models and from imported files, so the allowlist is a
trust boundary and is tested as one.
"""

from __future__ import annotations

import unittest

from forge_expr import (
    ArityError,
    DisallowedConstructError,
    EvaluationError,
    Expression,
    ExpressionComplexityError,
    ExpressionSyntaxError,
    ExpressionTypeError,
    Parameter,
    ParameterCycleError,
    ParameterGraph,
    ParameterResolutionError,
    ReservedNameError,
    UnknownFunctionError,
    UnknownNameError,
    evaluate,
)
from forge_units import Interval, Q, Trivalent


class Arithmetic(unittest.TestCase):
    def test_literals_are_dimensionless(self) -> None:
        self.assertTrue(evaluate("2 + 3").is_dimensionless)
        self.assertAlmostEqual(evaluate("2 + 3").magnitude.midpoint, 5.0)

    def test_unit_symbols_act_as_literals(self) -> None:
        value = evaluate("6 * mm")
        self.assertAlmostEqual(value.to("mm").magnitude.midpoint, 6.0)
        self.assertAlmostEqual(evaluate("500 * N").to("N").magnitude.midpoint, 500.0)

    def test_parameters_resolve(self) -> None:
        context = {"width": Q(60, "mm"), "wall": Q(6, "mm")}
        result = Expression.parse("width - 2 * wall").evaluate(context)
        self.assertAlmostEqual(result.to("mm").magnitude.midpoint, 48.0)

    def test_dimensional_mismatch_is_reported_at_the_node(self) -> None:
        context = {"length": Q(10, "mm"), "load": Q(5, "N")}
        with self.assertRaises(EvaluationError) as caught:
            Expression.parse("length + load").evaluate(context)
        rendered = str(caught.exception)
        self.assertIn("length + load", rendered)
        self.assertIn("^", rendered)  # the caret line locates the failure

    def test_operator_precedence_matches_python(self) -> None:
        self.assertAlmostEqual(evaluate("2 + 3 * 4").magnitude.midpoint, 14.0)
        self.assertAlmostEqual(evaluate("(2 + 3) * 4").magnitude.midpoint, 20.0)
        self.assertAlmostEqual(evaluate("2 ** 3 ** 2").magnitude.midpoint, 512.0)

    def test_powers_produce_correct_dimensions(self) -> None:
        area = evaluate("(4 * mm) ** 2")
        self.assertAlmostEqual(area.to("mm^2").magnitude.midpoint, 16.0)

    def test_uncertain_exponent_is_refused(self) -> None:
        context = {"n": Q(2.0, relative=0.1)}
        with self.assertRaises(ExpressionTypeError):
            Expression.parse("(4 * mm) ** n").evaluate(context)

    def test_dimensional_exponent_is_refused(self) -> None:
        with self.assertRaises(ExpressionTypeError):
            Expression.parse("2 ** (3 * mm)").evaluate({})

    def test_tolerance_propagates_through_a_stack_up(self) -> None:
        context = {
            "ear_gap": Q(12.0, "mm", plus=0.05, minus=0.05),
            "link_width": Q(10.0, "mm", plus=0.03, minus=0.03),
        }
        clearance = Expression.parse("(ear_gap - link_width) / 2").evaluate(context)
        self.assertFalse(clearance.is_exact)
        # Worst case both tolerances conspire: (11.95 - 10.03)/2 = 0.96
        self.assertLessEqual(clearance.to("mm").magnitude.lo, 0.96 + 1e-9)
        self.assertGreaterEqual(clearance.to("mm").magnitude.hi, 1.04 - 1e-9)

    def test_modulo_and_floor_division(self) -> None:
        self.assertAlmostEqual(evaluate("7 // 2").magnitude.midpoint, 3.0)
        remainder = evaluate("(7 * mm) % (2 * mm)")
        self.assertAlmostEqual(remainder.to("mm").magnitude.midpoint, 1.0)

    def test_caret_means_exponentiation_with_the_expected_precedence(self) -> None:
        """`^` is exponentiation, and binds tighter than `*` as engineers expect.

        Python reads `^` as XOR with looser precedence than `*`, so an AST-level
        rewrite would turn `2 * mm^2` into `(2 mm)**2`. The lexical rewrite to
        `**` before parsing is what makes this come out right.
        """
        self.assertAlmostEqual(evaluate("3^2").magnitude.midpoint, 9.0)
        area = evaluate("2 * mm^2")
        self.assertAlmostEqual(area.to("mm^2").magnitude.midpoint, 2.0)
        self.assertEqual(area.dimension, Q(1.0, "mm^2").dimension)
        self.assertAlmostEqual(
            evaluate("sqrt(16 * mm^2)").to("mm").magnitude.midpoint, 4.0, places=9
        )

    def test_caret_and_double_star_agree(self) -> None:
        self.assertAlmostEqual(
            evaluate("2 * mm^2").to("mm^2").magnitude.midpoint,
            evaluate("2 * mm**2").to("mm^2").magnitude.midpoint,
        )


class Conditions(unittest.TestCase):
    def test_comparison_returns_trivalent(self) -> None:
        context = {"t": Q(3.0, "mm")}
        self.assertIs(
            Expression.parse("t >= 2 * mm").evaluate_condition(context), Trivalent.TRUE
        )

    def test_uncertain_comparison_is_indeterminate(self) -> None:
        context = {"t": Q(3.0, "mm", plus=0.1, minus=0.1)}
        self.assertIs(
            Expression.parse("t >= 3 * mm").evaluate_condition(context),
            Trivalent.INDETERMINATE,
        )

    def test_chained_comparison(self) -> None:
        context = {"t": Q(3.0, "mm")}
        self.assertIs(
            Expression.parse("2 * mm < t < 5 * mm").evaluate_condition(context),
            Trivalent.TRUE,
        )

    def test_boolean_logic_is_kleene(self) -> None:
        context = {"a": Q(3.0, "mm", plus=0.5, minus=0.5), "b": Q(10.0, "mm")}
        expression = Expression.parse("(a >= 3 * mm) and (b >= 5 * mm)")
        self.assertIs(
            expression.evaluate_condition(context), Trivalent.INDETERMINATE
        )
        failing = Expression.parse("(a >= 3 * mm) and (b >= 50 * mm)")
        # A decisive failure is not softened by an unknown.
        self.assertIs(failing.evaluate_condition(context), Trivalent.FALSE)

    def test_conditional_with_known_condition_picks_a_branch(self) -> None:
        context = {"t": Q(5.0, "mm")}
        result = Expression.parse(
            "(2 * mm) if t >= 4 * mm else (8 * mm)"
        ).evaluate_quantity(context)
        self.assertAlmostEqual(result.to("mm").magnitude.midpoint, 2.0)

    def test_conditional_with_unknown_condition_returns_the_hull(self) -> None:
        """The central honesty property of the expression language.

        When the condition cannot be decided, neither branch may be selected.
        Returning the hull keeps the uncertainty in the value instead of
        resolving it arbitrarily, which is what lets a downstream gate report
        INCONCLUSIVE rather than a fabricated PASS.
        """
        context = {"t": Q(4.0, "mm", plus=0.2, minus=0.2)}
        result = Expression.parse(
            "(2 * mm) if t >= 4 * mm else (8 * mm)"
        ).evaluate_quantity(context)
        magnitude = result.to("mm").magnitude
        self.assertLessEqual(magnitude.lo, 2.0)
        self.assertGreaterEqual(magnitude.hi, 8.0)
        self.assertFalse(result.is_exact)

    def test_quantity_is_not_truthy(self) -> None:
        with self.assertRaises(ExpressionTypeError):
            Expression.parse("t and (t >= 1 * mm)").evaluate({"t": Q(3.0, "mm")})


class Functions(unittest.TestCase):
    def test_vetted_functions_work(self) -> None:
        self.assertAlmostEqual(evaluate("sin(90 * deg)").magnitude.midpoint, 1.0)
        self.assertAlmostEqual(
            evaluate("sqrt(16 * mm^2)").to("mm").magnitude.midpoint, 4.0, places=9
        )
        self.assertAlmostEqual(
            evaluate("hypot(3 * mm, 4 * mm)").to("mm").magnitude.midpoint,
            5.0,
            places=9,
        )
        self.assertAlmostEqual(
            evaluate("clamp(12 * mm, 0 * mm, 10 * mm)").to("mm").magnitude.midpoint,
            10.0,
        )

    def test_unknown_function_is_refused_with_alternatives(self) -> None:
        with self.assertRaises(UnknownFunctionError) as caught:
            Expression.parse("tanh(1)")
        self.assertIn("available", caught.exception.detail)

    def test_wrong_arity_is_caught_at_parse_time(self) -> None:
        with self.assertRaises(ArityError):
            Expression.parse("sin(1, 2)")

    def test_domain_error_propagates_with_position(self) -> None:
        with self.assertRaises(EvaluationError) as caught:
            Expression.parse("asin(2.0)").evaluate({})
        self.assertEqual(caught.exception.detail["function"], "asin")


class SecurityBoundary(unittest.TestCase):
    """The allowlist is a trust boundary; these are its tests."""

    def test_dangerous_constructs_are_refused_by_name(self) -> None:
        hostile = [
            "__import__('os').system('id')",
            "().__class__.__bases__[0].__subclasses__()",
            "open('/etc/passwd')",
            "(lambda: 1)()",
            "[x for x in range(10)]",
            "{'a': 1}",
            "[1, 2, 3]",
            "(1, 2)",
            "x := 5",
            "f'{x}'",
            "'literal string'",
            "value.attribute",
            "items[0]",
            "print(1)",
            "eval('1')",
            "exec('1')",
            "globals()",
            "sin(*args)",
        ]
        for source in hostile:
            with self.subTest(source=source):
                with self.assertRaises(
                    (
                        DisallowedConstructError,
                        UnknownFunctionError,
                        ExpressionSyntaxError,
                    )
                ):
                    Expression.parse(source)

    def test_no_builtins_are_reachable_as_names(self) -> None:
        for name in ("len", "range", "type", "id", "dir", "vars", "__builtins__"):
            with self.subTest(name=name):
                with self.assertRaises((UnknownNameError, UnknownFunctionError)):
                    Expression.parse(name).evaluate({})

    def test_depth_budget_is_enforced(self) -> None:
        # Parentheses alone do not create AST nodes, so nesting must be real.
        deep = "1" + " + 1" * 600
        with self.assertRaises(ExpressionComplexityError) as caught:
            Expression.parse(deep)
        self.assertIn("limit", caught.exception.detail)

    def test_node_budget_is_enforced(self) -> None:
        # A wide but shallow expression: a balanced sum tree stays under the
        # depth limit while exceeding the node count.
        def balanced(count: int) -> str:
            if count == 1:
                return "1"
            half = count // 2
            return f"({balanced(half)} + {balanced(count - half)})"

        with self.assertRaises(ExpressionComplexityError):
            Expression.parse(balanced(400))

    def test_boolean_literals_are_refused(self) -> None:
        with self.assertRaises(DisallowedConstructError):
            Expression.parse("True")

    def test_unknown_name_reports_what_was_available(self) -> None:
        with self.assertRaises(UnknownNameError) as caught:
            Expression.parse("widht").evaluate({"width": Q(1, "mm")})
        self.assertIn("width", caught.exception.detail["available"])


class ParameterGraphBehaviour(unittest.TestCase):
    def _clevis_graph(self) -> ParameterGraph:
        return ParameterGraph(
            [
                Parameter.literal(
                    "ear_thickness",
                    Q(6.0, "mm"),
                    minimum=Q(4.0, "mm"),
                    maximum=Q(10.0, "mm"),
                    optimizable=True,
                ),
                Parameter.literal("ear_gap", Q(12.0, "mm")),
                Parameter.literal("base_thickness", Q(6.0, "mm")),
                Parameter.derived(
                    "outer_width", "ear_gap + 2 * ear_thickness", "mm"
                ),
                Parameter.derived(
                    "link_width", "ear_gap - 2 * axial_clearance", "mm"
                ),
                Parameter.literal("axial_clearance", Q(1.0, "mm")),
            ]
        )

    def test_resolution_in_dependency_order(self) -> None:
        resolution = self._clevis_graph().resolve()
        self.assertAlmostEqual(
            resolution["outer_width"].to("mm").magnitude.midpoint, 24.0
        )
        self.assertAlmostEqual(
            resolution["link_width"].to("mm").magnitude.midpoint, 10.0
        )
        order = list(resolution.order)
        self.assertLess(order.index("ear_thickness"), order.index("outer_width"))
        self.assertLess(order.index("axial_clearance"), order.index("link_width"))

    def test_resolution_order_is_deterministic(self) -> None:
        first = self._clevis_graph().resolve().order
        for _ in range(5):
            self.assertEqual(self._clevis_graph().resolve().order, first)

    def test_overrides_drive_the_optimiser(self) -> None:
        graph = self._clevis_graph()
        resolution = graph.resolve({"ear_thickness": Q(8.0, "mm")})
        self.assertAlmostEqual(
            resolution["outer_width"].to("mm").magnitude.midpoint, 28.0
        )

    def test_overriding_a_derived_parameter_is_refused(self) -> None:
        with self.assertRaises(ParameterResolutionError):
            self._clevis_graph().resolve({"outer_width": Q(99.0, "mm")})

    def test_cycles_are_reported_as_a_path(self) -> None:
        graph = ParameterGraph(
            [
                Parameter.derived("a", "b + 1 * mm", "mm"),
                Parameter.derived("b", "c * 2", "mm"),
                Parameter.derived("c", "a / 2", "mm"),
            ]
        )
        with self.assertRaises(ParameterCycleError) as caught:
            graph.resolve()
        cycle = caught.exception.detail["cycle"]
        self.assertEqual(cycle[0], cycle[-1])
        self.assertEqual(set(cycle), {"a", "b", "c"})

    def test_missing_dependency_is_named(self) -> None:
        graph = ParameterGraph([Parameter.derived("a", "missing + 1 * mm", "mm")])
        with self.assertRaises(ParameterResolutionError) as caught:
            graph.resolve()
        self.assertEqual(caught.exception.detail["missing"], "missing")

    def test_declared_unit_is_checked_against_the_expression(self) -> None:
        graph = ParameterGraph(
            [
                Parameter.literal("load", Q(500, "N")),
                Parameter.derived("mistake", "load * 2", "mm"),
            ]
        )
        with self.assertRaises(ParameterResolutionError) as caught:
            graph.resolve()
        self.assertIn("force", caught.exception.detail["actual_measures"])

    def test_bounds_are_three_valued(self) -> None:
        graph = ParameterGraph(
            [
                Parameter.literal(
                    "t",
                    Q(4.0, "mm", plus=0.3, minus=0.3),
                    minimum=Q(4.0, "mm"),
                )
            ]
        )
        resolution = graph.resolve()
        self.assertIs(
            resolution.parameters["t"].within_bounds, Trivalent.INDETERMINATE
        )
        self.assertEqual(len(resolution.indeterminate_bounds()), 1)
        self.assertEqual(len(resolution.out_of_bounds()), 0)

    def test_out_of_bounds_is_detected(self) -> None:
        graph = ParameterGraph(
            [Parameter.literal("t", Q(2.0, "mm"), minimum=Q(4.0, "mm"))]
        )
        self.assertEqual(len(graph.resolve().out_of_bounds()), 1)

    def test_named_constants_are_reserved(self) -> None:
        for name in ("pi", "e", "tau", "g0"):
            with self.subTest(name=name):
                with self.assertRaises(ReservedNameError):
                    Parameter.literal(name, Q(1.0, "mm"))

    def test_unit_shaped_names_are_allowed_and_shadow_the_unit(self) -> None:
        """`t` for thickness must be usable even though `t` is the tonne.

        The parameter shadows the unit during evaluation, which is what an
        engineer who declared `t = 6 mm` expects, and the dependency edge must
        survive so ordering stays correct.
        """
        graph = ParameterGraph(
            [
                Parameter.literal("t", Q(6.0, "mm")),
                Parameter.literal("L", Q(60.0, "mm")),
                Parameter.derived("slenderness", "L / t", ""),
            ]
        )
        resolution = graph.resolve()
        self.assertAlmostEqual(resolution["slenderness"].magnitude.midpoint, 10.0)
        order = list(resolution.order)
        self.assertLess(order.index("t"), order.index("slenderness"))
        self.assertLess(order.index("L"), order.index("slenderness"))

    def test_shadowed_units_are_reported_not_hidden(self) -> None:
        graph = ParameterGraph(
            [
                Parameter.literal("t", Q(6.0, "mm")),
                Parameter.literal("width", Q(60.0, "mm")),
            ]
        )
        self.assertEqual(set(graph.shadowed_units()), {"t"})

    def test_unit_reference_still_works_when_not_shadowed(self) -> None:
        graph = ParameterGraph(
            [
                Parameter.literal("thickness", Q(6.0, "mm")),
                Parameter.derived("doubled", "thickness + 6 * mm", "mm"),
            ]
        )
        self.assertAlmostEqual(
            graph.resolve()["doubled"].to("mm").magnitude.midpoint, 12.0
        )

    def test_derived_parameter_cannot_be_optimisable(self) -> None:
        with self.assertRaises(ParameterResolutionError):
            Parameter(
                identifier="x",
                expression=Expression.parse("1 + 1"),
                optimizable=True,
            )

    def test_dependents_drive_incremental_invalidation(self) -> None:
        graph = self._clevis_graph()
        self.assertEqual(
            graph.dependents_of("ear_thickness"), frozenset({"outer_width"})
        )
        self.assertEqual(
            graph.dependents_of("ear_gap"), frozenset({"outer_width", "link_width"})
        )
        self.assertEqual(graph.dependents_of("outer_width"), frozenset())

    def test_deep_chain_does_not_blow_the_stack(self) -> None:
        depth = 400
        parameters = [Parameter.literal("p0", Q(1.0, "mm"))]
        for index in range(1, depth):
            parameters.append(
                Parameter.derived(f"p{index}", f"p{index - 1} + 1 * mm", "mm")
            )
        resolution = ParameterGraph(parameters).resolve()
        self.assertAlmostEqual(
            resolution[f"p{depth - 1}"].to("mm").magnitude.midpoint, float(depth)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
