"""The generated model contract: authoring guide, JSON Schema, example.

Everything the ForgeIR Designer is told is generated from ``FEATURE_SPECS`` --
the same table the compiler enforces. These tests hold that arrangement
together, because the failure it prevents is silent: a prompt that documents a
parameter the compiler no longer accepts produces documents that fail to
compile, and the model gets blamed for a drift in the instructions.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any, Mapping

from forge_ir import Document
from forge_ir.features import FEATURE_SPECS
from forge_ir.measurements import (
    PARAMETERISED_MEASUREMENTS,
    SIMPLE_MEASUREMENTS,
    parse_measurement,
)
from forge_ir.spec import (
    EXAMPLE_DOCUMENT,
    authoring_guide,
    parameter_sort_legend,
    document_schema,
    feature_catalogue,
)
from forge_kernel import Compiler
from forge_pipeline import verify_component
from forge_units import Q


class TheGuideMatchesTheCompiler(unittest.TestCase):
    def test_every_feature_kind_is_documented(self) -> None:
        catalogue = feature_catalogue()
        for kind in FEATURE_SPECS:
            self.assertIn(f"`{kind}`", catalogue, f"{kind} is not in the guide")

    def test_every_documented_parameter_is_one_the_compiler_accepts(self) -> None:
        """The guide is generated, so this can only fail if generation drifts."""
        catalogue = feature_catalogue()
        for kind, spec in FEATURE_SPECS.items():
            for parameter in spec.parameters:
                self.assertIn(
                    f"`{parameter.name}`",
                    catalogue,
                    f"{kind}.{parameter.name} is enforced but not documented",
                )

    def test_the_guide_does_not_teach_what_the_designer_never_writes(self) -> None:
        """The vocabulary belongs to the Requirements Engineer, not here.

        The designer returns `name`, `description` and `components`; the
        requirements are filled in around its answer. Carrying the measurement
        vocabulary in its guide cost 280 tokens of every design call to
        describe a field it cannot emit -- and told it to bind requirements it
        is not asked to write, which is a contradiction, not just waste.
        ``TheVocabularyIsTaughtNotJustEnforced`` holds the prompt that does
        need it.
        """
        guide = authoring_guide(include_catalogue=False)
        self.assertNotIn("Measurement bindings", guide)
        self.assertIn("You design the part, not the paperwork", guide)

    def test_the_schema_covers_every_feature_kind(self) -> None:
        encoded = json.dumps(document_schema())
        for kind in FEATURE_SPECS:
            self.assertIn(f'"{kind}"', encoded)

    def test_the_schema_forbids_unknown_fields(self) -> None:
        """Rejecting an invented field is what turns a guess into a diagnostic."""
        schema = document_schema()
        self.assertIs(schema["additionalProperties"], False)

    def test_the_guide_is_not_unreasonably_long(self) -> None:
        """It is sent on every design call, so its size is a running cost.
        What is sent is the guide without the kinds a brief has to ask for
        -- those come with the brief that names them -- and every such kind
        has the words that ask for it."""
        from forge_ir.spec import KINDS_OFFERED_ON_REQUEST
        from forge_roles.library import _KINDS_A_BRIEF_ASKS_FOR

        self.assertEqual(set(KINDS_OFFERED_ON_REQUEST),
                         set(_KINDS_A_BRIEF_ASKS_FOR))
        guide = authoring_guide()
        self.assertLess(
            len(guide) // 4,
            9000,
            "the authoring guide has grown past a sensible prompt budget",
        )


class TheWorkedExampleIsReal(unittest.TestCase):
    """The guide shows a document. It must be one the compiler accepts."""

    def setUp(self) -> None:
        self.document = Document.from_json(json.dumps(EXAMPLE_DOCUMENT))

    def test_it_appears_in_the_guide(self) -> None:
        guide = authoring_guide(include_catalogue=False)
        self.assertIn('"id": "spacer"', guide)
        # Shown as an answer, not a document: the fields the orchestrator
        # fills in are visibly absent, because an example that contradicts the
        # instruction wins over the instruction.
        self.assertNotIn('"schema_version"', guide)
        self.assertNotIn('"document_id"', guide)

    def test_it_compiles_and_passes_its_own_gates(self) -> None:
        report = verify_component(
            self.document,
            self.document.components[0],
            measurement_depth=6,
            mesh_resolution=48,
        )
        failing = [
            result.gate.identifier
            for result in report.gate_results
            if result.status.value not in ("PASS",)
        ]
        self.assertEqual(failing, [], "the example shown to the model does not pass")

    def test_its_derived_parameter_actually_derives(self) -> None:
        """An example with a hard-coded 'derived' value teaches the wrong thing."""
        component = self.document.components[0]
        widened = Compiler().compile_component(
            component, overrides={"wall": Q(5.0, "mm")}
        )
        self.assertAlmostEqual(
            float(widened.resolution["outer_diameter"].magnitude.midpoint),
            20.0,
            places=6,
        )

    def test_every_requirement_in_it_is_bound_to_a_measurement(self) -> None:
        for requirement in EXAMPLE_DOCUMENT["requirements"]:
            binding = requirement.get("measurement", "")
            self.assertTrue(binding, f"{requirement['id']} is unmeasurable")
            parse_measurement(binding)  # raises if the vocabulary does not know it



class TheVocabularyIsTaughtNotJustEnforced(unittest.TestCase):
    """The most avoidable failure a prompt can have.

    The Requirements Engineer is required to bind every numeric requirement to
    a closed vocabulary, and its prompt did not contain that vocabulary. Both
    models tried produced invalid bindings -- `load`, `parameter:material_grade`,
    `feature_count:mounting_holes` -- and burned three attempts each on a rubric
    they had never been shown.
    """

    def test_the_requirements_prompt_lists_every_binding(self) -> None:
        from forge_roles import RequirementsEngineer

        prompt = RequirementsEngineer().system_prompt()
        for name in SIMPLE_MEASUREMENTS + PARAMETERISED_MEASUREMENTS:
            self.assertIn(name, prompt, f"{name} is enforced but never taught")

    def test_the_prompt_names_the_two_mistakes_models_actually_make(self) -> None:
        from forge_roles import RequirementsEngineer

        prompt = RequirementsEngineer().system_prompt()
        self.assertIn("A load is not a measurement", prompt)
        self.assertIn("material", prompt)


class BindingErrorsArePointed(unittest.TestCase):
    """Each error says what to do about *that* binding.

    The full vocabulary is appended once per repair round by the role, not once
    per offending requirement -- three wrong bindings used to mean three copies
    of a sixty-word list.
    """

    def _message(self, binding: str) -> str:
        from forge_ir.measurements import MeasurementError

        try:
            parse_measurement(binding)
        except MeasurementError as error:
            return str(error)
        self.fail(f"{binding} was accepted")

    def test_the_message_stays_short_enough_to_be_read(self) -> None:
        for binding in ("load", "material_grade", "mas", "nonsense"):
            self.assertLess(len(self._message(binding)), 400, binding)

    def test_a_load_is_told_what_to_do_instead(self) -> None:
        self.assertIn("assumption", self._message("load"))
        self.assertIn("safety_factor", self._message("load"))

    def test_a_material_is_pointed_at_the_component_field(self) -> None:
        self.assertIn("`material` field", self._message("material_grade"))

    def test_a_near_miss_is_suggested(self) -> None:
        self.assertIn("Did you mean `mass`?", self._message("mas"))

    def test_a_prefix_without_its_argument_says_so(self) -> None:
        self.assertIn("parameter:<id>", self._message("parameter"))

    def test_a_valid_binding_is_untouched(self) -> None:
        self.assertEqual(parse_measurement("feature_count:hole").argument, "hole")


class TheLoadGoesWhereItBelongs(unittest.TestCase):
    """A force threshold is the input, not a property of the part.

    Observed live, twice over: told the vocabulary, qwen2.5-coder still wrote a
    `load_magnitude` requirement holding 300 N and bolted `safety_factor:bearing`
    onto it. The generic reply -- "that binding is dimensionless" -- sent it
    round the same loop three times. Naming where the load belongs ends it.
    """

    def _problems(self, unit: str, magnitude: float = 300.0) -> list[str]:
        from forge_roles import RequirementsEngineer, RoleOutputError

        payload = {
            "risk_class": "high",
            "requirements": [
                {
                    "id": "load_magnitude",
                    "statement": "The bracket shall carry the load.",
                    "type": "performance",
                    "strength": "hard",
                    "verification": "analytical",
                    "threshold": {"magnitude": magnitude, "unit": unit},
                    "comparison": "at_least",
                    "measurement": "safety_factor:bearing",
                    "source": "user",
                    "state": "accepted",
                }
            ],
            "assumptions": [],
            "unknowns": [],
        }
        try:
            RequirementsEngineer().parse(payload)
        except RoleOutputError as error:
            return list(error.problems)
        return []

    def test_a_force_threshold_is_redirected_to_an_assumption(self) -> None:
        problem = self._problems("N")[0]
        self.assertIn("not a property of the finished part", problem)
        self.assertIn("ASM_DESIGN_LOAD", problem)
        self.assertIn('"magnitude": 300.0', problem)

    def test_any_spelling_of_force_is_caught(self) -> None:
        """kN and lbf are forces too; the check is dimensional, not textual."""
        for unit in ("kN", "lbf"):
            self.assertTrue(
                any("not a property" in p for p in self._problems(unit)),
                f"{unit} was not recognised as a force",
            )

    def test_a_dimensionless_threshold_is_accepted(self) -> None:
        self.assertEqual(self._problems("", magnitude=2.0), [])

    def test_the_prompt_shows_the_pattern_rather_than_describing_it(self) -> None:
        from forge_roles import RequirementsEngineer

        prompt = RequirementsEngineer().system_prompt()
        self.assertIn("ASM_DESIGN_LOAD", prompt)
        self.assertIn("safety_factor:bearing", prompt)
        self.assertIn('"unit": ""', prompt)


class RepairPromptsStaySmall(unittest.TestCase):
    """Three bad bindings must not mean three copies of the vocabulary.

    Observed live: with the vocabulary appended to every offending requirement,
    a repair prompt grew 2,535 -> 4,505 -> 6,314 input tokens across three
    attempts. On a model running at five tokens a second that is minutes of
    pure overhead, paid to say the same thing three times per round.
    """

    def _problems(self, bindings: list[str]) -> list[str]:
        from forge_roles import RequirementsEngineer, RoleOutputError

        payload = {
            "risk_class": "low",
            "requirements": [
                {
                    "id": f"R{index}",
                    "statement": "A claim.",
                    "type": "geometric",
                    "strength": "hard",
                    "verification": "exact_geometry",
                    "threshold": {"magnitude": 1.0, "unit": "mm"},
                    "comparison": "equals",
                    "measurement": binding,
                    "source": "user",
                    "state": "accepted",
                }
                for index, binding in enumerate(bindings)
            ],
            "assumptions": [],
            "unknowns": [],
        }
        try:
            RequirementsEngineer().parse(payload)
        except RoleOutputError as error:
            return list(error.problems)
        return []

    def test_bad_bindings_no_longer_cost_a_round_at_all(self) -> None:
        """This used to assert the vocabulary appeared once. Now it appears
        never, because a binding nothing can parse no longer sends the answer
        back: the requirement keeps its threshold, loses its measurement, and
        is reported NOT_TESTED. Visibly unchecked beats nine good requirements
        thrown away with it -- and it is what this system already promises for
        a requirement with no binding at all.
        """
        from forge_roles import RequirementsEngineer

        self.assertEqual(self._problems(["nonsense_a", "nonsense_b"]), [])

        result = RequirementsEngineer().parse({
            "risk_class": "low", "assumptions": [], "unknowns": [],
            "requirements": [{
                "id": "R0", "statement": "A claim.",
                "threshold": {"magnitude": 1.0, "unit": "mm"},
                "comparison": "equals", "measurement": "nonsense_a",
            }],
        })
        self.assertEqual(len(result.requirements), 1)
        self.assertFalse(dict(result.requirements[0]).get("measurement"))
        self.assertTrue(
            any("NOT_TESTED" in note for note in result.notes),
            f"the retirement was not recorded: {result.notes}",
        )

    def test_no_listing_when_the_bindings_were_fine(self) -> None:
        problems = self._problems(["mass"])
        self.assertFalse(
            any("complete measurement vocabulary" in p for p in problems)
        )

    def test_a_fastener_is_pointed_at_the_feature_kind_it_really_is(self) -> None:
        from forge_ir.measurements import MeasurementError

        for spelling in ("bolt", "bolts", "mounting_holes", "screw"):
            with self.assertRaises(MeasurementError) as caught:
                parse_measurement(f"feature_count:{spelling}")
            self.assertIn("feature_count:hole", str(caught.exception))

    def test_the_triage_table_is_in_the_prompt(self) -> None:
        from forge_roles import RequirementsEngineer

        prompt = RequirementsEngineer().system_prompt()
        self.assertIn("Before writing a requirement", prompt)
        self.assertIn("feature_count:hole", prompt)
        # Each row of the table names where that kind of fact goes, and the
        # destinations are now the transport's own slots rather than a
        # binding string the model has to spell.
        for destination in ("dimensions", "whole_part", "counts",
                            "safety_factors", "material"):
            self.assertIn(destination, prompt)

    def test_the_prompt_names_no_verification_method(self) -> None:
        """It used to demand one of `exact_geometry`, `analytical`,
        `sampling`, `cross_backend` -- while `verification` is stripped from
        the schema the model fills in, and the last two are not in the enum
        at all. Three ways wrong in one sentence: unwritable, contradicted by
        the line above it, and naming values that do not exist."""
        from forge_ir.spec import _requirement_schema
        from forge_roles import RequirementsEngineer
        from forge_roles.library import _what_a_requirement_needs_from_you

        prompt = RequirementsEngineer().system_prompt()
        for invented in ("sampling", "cross_backend"):
            self.assertNotIn(invented, _requirement_schema()[
                "properties"]["verification"]["enum"])
            self.assertNotIn(invented, prompt)
        self.assertNotIn(
            "verification", _what_a_requirement_needs_from_you()["properties"])


class TheParameterSortsAreShownNotJustNamed(unittest.TestCase):
    """A sort name is half a specification; the JSON form is the other half.

    The catalogue printed `count` and `displacement` and never said what either
    took. Every worked example writes {"magnitude", "unit"}, so that is what a
    model writes everywhere -- and a run that correctly designed a 20 mm shaft
    bracket died on `count: {"magnitude": 4, "unit": ""}` and a scalar
    `spacing`, three times, fifty minutes.

    The legend must therefore be true. These tests build a real document for
    each sort and put it through the decoder, so a legend that drifts from what
    the compiler accepts fails here rather than in a live run.
    """

    def _document(self, **overrides: object) -> dict:
        features = [
            {
                "id": "body",
                "kind": "box",
                "parameters": {"size": {"vector": [20.0, 20.0, 20.0], "unit": "mm"}},
            },
            {
                "id": "pat",
                "kind": "pattern_linear",
                "inputs": ["body"],
                "parameters": {
                    "count": 4,
                    "spacing": {"vector": [10.0, 0, 0], "unit": "mm"},
                    "symmetric": True,
                },
            },
        ]
        features[1]["parameters"].update(overrides)
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "T",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [
                {
                    "id": "c",
                    "name": "C",
                    "parameters": [
                        {"id": "w", "value": {"magnitude": 10.0, "unit": "mm"}}
                    ],
                    "features": features,
                }
            ],
        }

    def _accepts(self, **overrides: object) -> bool:
        from forge_ir import SchemaError, SchemaErrorGroup

        try:
            Document.from_json(json.dumps(self._document(**overrides)))
        except (SchemaError, SchemaErrorGroup):
            return False
        return True

    def test_the_legend_covers_every_sort_in_use(self) -> None:
        from forge_ir.spec import _SORT_FORMS

        for spec in FEATURE_SPECS.values():
            for parameter in spec.parameters:
                self.assertIn(parameter.sort, _SORT_FORMS, parameter.name)

    def test_it_is_in_the_guide_the_designer_is_given(self) -> None:
        guide = authoring_guide()
        self.assertIn("Feature parameter sorts", guide)
        self.assertIn("a bare integer", guide)

    def test_a_count_is_bare_as_the_legend_says(self) -> None:
        """Bare is what the legend teaches; the exact quantity form also works.

        The legend says "bare" because that is the form to write. It is not a
        claim that nothing else parses: a dimensionless whole quantity says the
        same thing unambiguously, and ``ACountSpelledAsAQuantity`` covers why
        refusing it was costing real designs.
        """
        self.assertTrue(self._accepts(count=4))
        self.assertTrue(self._accepts(count={"magnitude": 4, "unit": ""}))
        self.assertFalse(self._accepts(count={"magnitude": 4, "unit": "mm"}))

    def test_a_displacement_is_a_vector_as_the_legend_says(self) -> None:
        self.assertTrue(self._accepts(spacing={"vector": [10.0, 0, 0], "unit": "mm"}))
        self.assertTrue(self._accepts(spacing=[10.0, 0, 0]))
        self.assertFalse(self._accepts(spacing={"magnitude": 10.0, "unit": "mm"}))

    def test_an_expression_may_stand_in_a_vector_as_the_legend_says(self) -> None:
        self.assertTrue(self._accepts(spacing={"vector": ["w", 0, 0], "unit": "mm"}))

    def test_a_flag_is_a_boolean_as_the_legend_says(self) -> None:
        self.assertTrue(self._accepts(symmetric=True))

    def test_the_guide_still_fits_its_prompt_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class TheMessageNamesTheMistake(unittest.TestCase):
    """Three identical answers mean the feedback named nothing.

    Every one of these was observed live, and every one cost a ten-minute
    generation to learn. The rule they share: say what was written, and say
    where the thing the model wanted actually belongs.
    """

    def _problem(self, payload: Mapping[str, Any], pointer_ends: str) -> str:
        from forge_ir import SchemaError, SchemaErrorGroup
        from forge_roles.base import problems_from_schema_error

        try:
            Document.from_json(json.dumps(payload))
        except (SchemaError, SchemaErrorGroup) as error:
            for line in problems_from_schema_error(error):
                if pointer_ends in line:
                    return line
            self.fail(f"no problem mentioned {pointer_ends}")
        self.fail("the document was accepted")

    def _with_component_parameter(self, value: Mapping[str, Any]) -> dict:
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "T",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [
                {
                    "id": "c",
                    "name": "C",
                    "parameters": [{"id": "d", "value": value}],
                    "features": [
                        {
                            "id": "body",
                            "kind": "box",
                            "parameters": {
                                "size": {"vector": [20.0, 20.0, 20.0], "unit": "mm"}
                            },
                        }
                    ],
                }
            ],
        }

    def test_a_direction_parameter_is_told_where_a_load_belongs(self) -> None:
        problem = self._problem(
            self._with_component_parameter({"vector": [0, 0, -1], "unit": "N"}),
            "/components/0/parameters/0/value",
        )
        self.assertIn("a direction is not a parameter", problem)
        self.assertIn("ASM_DESIGN_LOAD", problem)
        self.assertIn("axis", problem)

    def test_an_unrecognised_object_says_what_was_written(self) -> None:
        problem = self._problem(
            self._with_component_parameter({"amount": 3, "units": "mm"}),
            "/components/0/parameters/0/value",
        )
        self.assertIn("amount", problem)
        self.assertIn("units", problem)

    def test_the_keys_reach_the_repair_prompt(self) -> None:
        """`keys` was computed and then filtered out before the model saw it."""
        from forge_roles.base import problems_from_schema_error
        from forge_ir.values import ValueError_ as IRValueError

        error = IRValueError(
            "object is not a recognised quantity or expression",
            pointer="/x",
            keys=["amount", "units"],
        )
        self.assertIn("amount", problems_from_schema_error(error)[0])


class TheVectorAndCountMessages(unittest.TestCase):
    """The two mistakes that follow from the guide's own drumbeat."""

    def _errors(self, **overrides: object) -> list[str]:
        from forge_ir import SchemaError, SchemaErrorGroup
        from forge_roles.base import problems_from_schema_error

        document = TheParameterSortsAreShownNotJustNamed._document(
            TheParameterSortsAreShownNotJustNamed(), **overrides
        )
        try:
            Document.from_json(json.dumps(document))
        except (SchemaError, SchemaErrorGroup) as error:
            return problems_from_schema_error(error)
        return []

    def test_a_wrapped_count_is_read_rather_than_refused(self) -> None:
        """It determines the answer exactly, so it is not an error at all."""
        self.assertEqual(self._errors(count={"magnitude": 4, "unit": ""}), [])

    def test_a_wrapped_count_with_a_real_unit_still_is(self) -> None:
        problems = [p.replace("\\", "") for p in
                    self._errors(count={"magnitude": 4, "unit": "mm"})]
        self.assertTrue(any("carries no unit" in p for p in problems), problems)

    def test_a_bare_count_needs_no_hint(self) -> None:
        self.assertEqual(self._errors(count=4), [])

    def test_a_scalar_where_a_vector_belongs_says_so(self) -> None:
        problems = self._errors(spacing={"magnitude": 10.0, "unit": "mm"})
        self.assertTrue(any("is a vector" in p for p in problems), problems)
        self.assertTrue(any("vector" in p and "[x, y, z]" in p for p in problems), problems)

    def test_a_numeric_string_is_accepted_as_the_expression_it_is(self) -> None:
        """`"4"` parses as an expression that resolves to four.

        A scalar has always accepted the string shorthand. Refusing it in the
        one position that now takes expressions would be an inconsistency no
        author could predict.
        """
        self.assertEqual(self._errors(count="4"), [])

    def test_a_string_that_is_not_an_expression_is_refused(self) -> None:
        problems = self._errors(count="four")
        self.assertTrue(problems)



class ACountInAComponentParameter(unittest.TestCase):
    """The trap three of our own sentences built.

    Rule 1 said "every dimensional value carries a unit" -- a count is not
    dimensional, so bare looked right. The sort legend said `count` is a bare
    integer -- true of a FEATURE parameter, which is not where this one was.
    And the error hint proposed `{"magnitude": 4, "unit": "mm"}`: four
    millimetres of bolts, which no sensible model will write. Caught between
    the three, qwen2.5-coder wrote `"value": 4` three times over twenty-five
    minutes. Every part of that is ours to fix.
    """

    def _document(self, value: object) -> dict:
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "T",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [
                {
                    "id": "c",
                    "name": "C",
                    "parameters": [{"id": "bolt_count", "value": value}],
                    "features": [
                        {
                            "id": "body",
                            "kind": "box",
                            "parameters": {
                                "size": {"vector": [20.0, 20.0, 20.0], "unit": "mm"}
                            },
                        }
                    ],
                }
            ],
        }

    def _problem(self, value: object) -> str:
        from forge_ir import SchemaError, SchemaErrorGroup
        from forge_roles.base import problems_from_schema_error

        try:
            Document.from_json(json.dumps(self._document(value)))
        except (SchemaError, SchemaErrorGroup) as error:
            # The detail travels as JSON, so its quotes arrive escaped. The
            # model reads through that; the assertions should too.
            return problems_from_schema_error(error)[0].replace("\\", "")
        self.fail(f"{value!r} was accepted")

    def test_the_empty_unit_form_is_what_actually_works(self) -> None:
        Document.from_json(json.dumps(self._document({"magnitude": 4, "unit": ""})))

    def test_an_integer_is_offered_the_dimensionless_form(self) -> None:
        problem = self._problem(4)
        self.assertIn('"unit": ""', problem)
        self.assertIn("pure count", problem)

    def test_a_measurement_is_not_told_it_might_be_a_count(self) -> None:
        """A float is a dimension that lost its unit, not a count."""
        problem = self._problem(12.5)
        self.assertNotIn("pure count", problem)
        self.assertIn('"unit": "mm"', problem)

    def test_the_rule_and_the_legend_agree_with_the_decoder(self) -> None:
        guide = authoring_guide()
        self.assertIn('{"magnitude": 4, "unit": ""}', guide)
        self.assertIn("never a component parameter", guide.replace("\n", " "))

    def test_the_legend_says_which_parameters_it_describes(self) -> None:
        legend = parameter_sort_legend()
        self.assertIn("Feature parameter sorts", legend)
        self.assertIn("COMPONENT parameter", legend)


class NothingToCutInto(unittest.TestCase):
    """Listing the ids that exist is no help when the first feature is missing.

    Twice over, the designer wrote a `hole` and a `pattern_linear` that both
    consume a `body` it never authored. "available: [bolt_pattern, shaft_hole]"
    is true and says nothing about what to do.
    """

    def _problems(self, features: list) -> list[str]:
        from forge_ir import SchemaError, SchemaErrorGroup
        from forge_roles.base import problems_from_schema_error

        document = {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "T",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [
                {"id": "c", "name": "C", "parameters": [], "features": features}
            ],
        }
        try:
            Document.from_json(json.dumps(document))
        except (SchemaError, SchemaErrorGroup) as error:
            return problems_from_schema_error(error)
        return []

    HOLE = {
        "id": "shaft_hole",
        "kind": "hole",
        "inputs": ["body"],
        "parameters": {
            "diameter": {"magnitude": 20.0, "unit": "mm"},
            "position": {"vector": [0, 0, 0], "unit": "mm"},
            "axis": [0, 0, 1],
        },
    }
    BOX = {
        "id": "body",
        "kind": "box",
        "parameters": {"size": {"vector": [40.0, 40.0, 40.0], "unit": "mm"}},
    }

    def test_a_part_with_no_base_solid_is_told_to_start_with_one(self) -> None:
        problems = [p.replace("\\", "") for p in self._problems([self.HOLE])]
        self.assertTrue(any("creates a solid from nothing" in p for p in problems))
        self.assertTrue(any('"id": "body"' in p for p in problems), problems)

    def test_a_plain_typo_gets_no_such_advice(self) -> None:
        """A base solid exists; the reference is just misspelled."""
        typo = dict(self.HOLE, inputs=["bdy"])
        problems = self._problems([self.BOX, typo])
        self.assertTrue(any("unknown feature" in p for p in problems))
        self.assertFalse(any("creates a solid from nothing" in p for p in problems))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class ACountCanBeDrivenByAParameter(unittest.TestCase):
    """Counts were the one numeric sort a parameter could not drive.

    The guide tells the designer to express anything derivable rather than
    hard-code it, and then offered no way to write a bolt count except by
    hard-coding it. Doing as it was told, qwen2.5-coder wrote
    `{"expression": "bolt_count", "unit": ""}` and was refused, three times,
    across two separate runs. The asymmetry was the defect.
    """

    def _document(self, count: object) -> dict:
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "T",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [
                {
                    "id": "c",
                    "name": "C",
                    "parameters": [
                        {"id": "bolt_count", "value": {"magnitude": 4, "unit": ""}},
                        {"id": "pitch", "value": {"magnitude": 20.0, "unit": "mm"}},
                    ],
                    "features": [
                        {
                            "id": "body",
                            "kind": "box",
                            "parameters": {
                                "size": {"vector": [10.0, 10.0, 10.0], "unit": "mm"}
                            },
                        },
                        {
                            "id": "pat",
                            "kind": "pattern_linear",
                            "inputs": ["body"],
                            "parameters": {
                                "count": count,
                                "spacing": {"vector": ["pitch", 0, 0], "unit": "mm"},
                            },
                        },
                    ],
                }
            ],
        }

    def _build(self, count: object):
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps(self._document(count)))
        return Compiler().compile_component(document.components[0])

    def test_a_literal_still_works(self) -> None:
        self._build(4)

    def test_an_expression_resolves(self) -> None:
        self._build({"expression": "bolt_count"})

    def test_the_unit_models_write_out_of_habit_is_tolerated(self) -> None:
        """Every other expression takes a unit, so one gets written here too."""
        self._build({"expression": "bolt_count", "unit": ""})

    def test_a_real_unit_is_still_refused(self) -> None:
        with self.assertRaises(Exception):
            self._build({"expression": "bolt_count", "unit": "mm"})

    def test_the_string_shorthand_works_as_it_does_for_scalars(self) -> None:
        self._build("bolt_count * 2")

    def test_the_geometry_actually_follows_the_parameter(self) -> None:
        """The point of the feature: changing the parameter changes the part."""
        from forge_geom import measure_mass_properties
        from forge_kernel import Compiler
        from forge_units import Q

        document = Document.from_json(
            json.dumps(self._document({"expression": "bolt_count"}))
        )
        component = document.components[0]
        volumes = []
        for instances in (2, 4, 8):
            part = Compiler().compile_component(
                component, overrides={"bolt_count": Q(float(instances), "")}
            )
            properties = measure_mass_properties(part.solid, max_depth=6)
            volumes.append(properties.volume.magnitude.midpoint)
        self.assertLess(volumes[0], volumes[1])
        self.assertLess(volumes[1], volumes[2])
        # Each instance is a 10 mm cube, so the totals track the count.
        for instances, volume in zip((2, 4, 8), volumes):
            self.assertAlmostEqual(volume / 1000.0, instances, delta=0.5)

    def test_the_parameter_is_visible_to_the_dependency_graph(self) -> None:
        document = Document.from_json(
            json.dumps(self._document({"expression": "bolt_count"}))
        )
        self.assertIn("bolt_count", document.components[0].features.free_names())

    def test_a_dimensional_count_is_refused(self) -> None:
        with self.assertRaises(Exception) as caught:
            self._build({"expression": "pitch"})
        self.assertIn("dimensionless", str(caught.exception))

    def test_a_fractional_count_is_refused(self) -> None:
        with self.assertRaises(Exception) as caught:
            self._build({"expression": "bolt_count / 3"})
        self.assertIn("whole number", str(caught.exception))

    def test_a_count_below_one_is_refused(self) -> None:
        with self.assertRaises(Exception) as caught:
            self._build({"expression": "bolt_count - 4"})
        self.assertIn("at least 1", str(caught.exception))

    def test_an_unknown_name_is_caught_at_decode_time(self) -> None:
        with self.assertRaises(Exception):
            self._build({"expression": "no_such_parameter"})

    def test_the_schema_offers_both_forms(self) -> None:
        encoded = json.dumps(document_schema())
        self.assertIn("A count driven by a parameter", encoded)

    def test_the_legend_says_so(self) -> None:
        self.assertIn("expression", parameter_sort_legend())

    def test_a_literal_and_an_expression_hash_differently(self) -> None:
        """The cache key must not collide across the two forms."""
        from forge_ir.values import CountValue
        from forge_expr import Expression

        literal = CountValue(4)
        derived = CountValue(expression=Expression.parse("bolt_count"))
        self.assertNotEqual(literal.cache_key(), derived.cache_key())

    def test_a_count_is_one_thing_or_the_other(self) -> None:
        from forge_ir.values import CountValue

        with self.assertRaises(Exception):
            CountValue()


class AnExpressionIsNotAVector(unittest.TestCase):
    """Wanting a spacing parametric is right; the shape was the only problem."""

    def test_it_says_where_the_expression_goes(self) -> None:
        from forge_ir import SchemaError, SchemaErrorGroup
        from forge_roles.base import problems_from_schema_error

        document = ACountCanBeDrivenByAParameter._document(
            ACountCanBeDrivenByAParameter(), 4
        )
        features = document["components"][0]["features"]
        features[1]["parameters"]["spacing"] = {"expression": "pitch", "unit": "mm"}
        try:
            Document.from_json(json.dumps(document))
        except (SchemaError, SchemaErrorGroup) as error:
            problem = problems_from_schema_error(error)[0].replace("\\", "")
            self.assertIn("cannot stand for a whole vector", problem)
            self.assertIn('"vector": ["bolt_pitch", 0, 0]', problem)
            return
        self.fail("the document was accepted")


class APrimitiveGivenSomethingToConsume(unittest.TestCase):
    """The commonest way a model reaches for a boolean without writing one.

    Observed live: two `cylinder` features each given an input, because the
    author wanted to add material with them. "wrong number of inputs, expected
    0, got 1" is true and leaves the author with no idea what to write instead.
    The primitive was right; the missing piece was the boolean around it.
    """

    def _problems(self, features: list) -> list[str]:
        from forge_ir import SchemaError, SchemaErrorGroup
        from forge_roles.base import problems_from_schema_error

        document = {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "T",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [
                {"id": "c", "name": "C", "parameters": [], "features": features}
            ],
        }
        try:
            Document.from_json(json.dumps(document))
        except (SchemaError, SchemaErrorGroup) as error:
            return [p.replace("\\", "") for p in problems_from_schema_error(error)]
        return []

    BOX = {
        "id": "body",
        "kind": "box",
        "parameters": {"size": {"vector": [40.0, 40.0, 40.0], "unit": "mm"}},
    }

    def test_it_names_the_boolean_that_is_missing(self) -> None:
        boss = {
            "id": "boss",
            "kind": "cylinder",
            "inputs": ["body"],
            "parameters": {
                "diameter": {"magnitude": 10.0, "unit": "mm"},
                "height": {"magnitude": 5.0, "unit": "mm"},
            },
        }
        problems = self._problems([self.BOX, boss])
        self.assertTrue(any("takes no `inputs`" in p for p in problems), problems)
        self.assertTrue(any("`union` or `subtract`" in p for p in problems))

    def test_it_names_the_feature_to_put_in_the_boolean(self) -> None:
        boss = {
            "id": "boss",
            "kind": "cylinder",
            "inputs": ["body"],
            "parameters": {
                "diameter": {"magnitude": 10.0, "unit": "mm"},
                "height": {"magnitude": 5.0, "unit": "mm"},
            },
        }
        problems = self._problems([self.BOX, boss])
        self.assertTrue(any('"boss"' in p for p in problems), problems)

    def test_a_round_cut_is_pointed_at_the_hole_feature(self) -> None:
        boss = {
            "id": "boss",
            "kind": "cylinder",
            "inputs": ["body"],
            "parameters": {
                "diameter": {"magnitude": 10.0, "unit": "mm"},
                "height": {"magnitude": 5.0, "unit": "mm"},
            },
        }
        self.assertTrue(
            any("`hole` feature" in p for p in self._problems([self.BOX, boss]))
        )

    def test_a_feature_that_should_have_inputs_gets_the_plain_message(self) -> None:
        """`extrude` takes a profile. Missing one is not a boolean problem."""
        orphan = {
            "id": "pad",
            "kind": "extrude",
            "parameters": {"distance": {"magnitude": 5.0, "unit": "mm"}},
        }
        problems = self._problems([self.BOX, orphan])
        self.assertTrue(any("wrong number of inputs" in p for p in problems))
        self.assertFalse(any("takes no `inputs`" in p for p in problems))


class TheShapeIsShownWhereItIsRead(unittest.TestCase):
    """A legend twenty pages away is not where a model is looking.

    Told three times that `spacing` is a vector, qwen2.5-coder wrote
    `{"expression": "bolt_spacing", "unit": "mm"}` three times: the habit every
    other parameter teaches, against one line in a legend it had scrolled past.
    """

    def test_a_displacement_shows_its_form_on_the_parameter(self) -> None:
        catalogue = feature_catalogue(["pattern_linear"])
        self.assertIn('`spacing` (displacement) {"vector": [x, y, z], "unit": "mm"}',
                      catalogue)

    def test_a_count_shows_both_of_its_forms(self) -> None:
        catalogue = feature_catalogue(["pattern_linear"])
        self.assertIn('`count` (count) 4 or {"expression": "n"}', catalogue)

    def test_a_direction_shows_that_it_is_bare(self) -> None:
        self.assertIn("`axis` (direction, optional) [x, y, z]",
                      feature_catalogue(["cylinder"]))

    def test_an_obvious_sort_is_left_alone(self) -> None:
        """`length` is already shown everywhere; annotating it is just cost."""
        catalogue = feature_catalogue(["cylinder"])
        self.assertIn("`diameter` (length)", catalogue)
        self.assertNotIn('`diameter` (length) {"magnitude"', catalogue)

    def test_options_still_render_after_the_form(self) -> None:
        catalogue = feature_catalogue(["shell"])
        self.assertIn("one of inward | outward | both", catalogue)

    def test_the_guide_still_fits_its_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class TheCompositionExampleIsReal(unittest.TestCase):
    """The guide said "build from primitives and booleans" and never showed one.

    Its only worked example is a spacer: one cylinder, one hole, no boolean. So
    the sole composition pattern the designer had ever seen was a chain -- each
    feature taking the previous one and modifying it. Asked for a bracket, which
    is a plate with something standing on it, qwen2.5-coder wrote
    `{"kind": "cylinder", "inputs": ["shaft"]}`: the chain habit applied to a
    primitive, which takes none. Three attempts, three identical answers,
    against an error message that spelled out the fix in words.

    So the fragment has to be real, and these tests compile it. A fragment that
    drifted into something the compiler rejects would teach the mistake it
    exists to prevent.
    """

    PARAMETERS = [
        {"id": "plate_width", "value": {"magnitude": 60.0, "unit": "mm"}},
        {"id": "plate_depth", "value": {"magnitude": 40.0, "unit": "mm"}},
        {"id": "plate", "value": {"magnitude": 6.0, "unit": "mm"}},
        {"id": "boss_diameter", "value": {"magnitude": 30.0, "unit": "mm"}},
        {"id": "stand_off", "value": {"magnitude": 32.0, "unit": "mm"}},
        {"id": "shaft_diameter", "value": {"magnitude": 20.0, "unit": "mm"}},
    ]

    def _document(self) -> Document:
        from forge_ir.spec import COMPOSITION_EXAMPLE

        return Document.from_json(json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000002",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "Composition",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [{
                "id": "bracket",
                "name": "Bracket",
                "material": "aluminium_6061_t6",
                "parameters": self.PARAMETERS,
                "features": list(COMPOSITION_EXAMPLE),
            }],
        }))

    def test_it_compiles_into_a_solid_with_material_in_it(self) -> None:
        from forge_geom import measure_mass_properties
        from forge_kernel import Compiler

        part = Compiler().compile_component(self._document().components[0])
        properties = measure_mass_properties(part.solid, max_depth=6)
        self.assertGreater(properties.volume.magnitude.lo, 0.0)

    def test_it_leaves_exactly_one_terminal_solid(self) -> None:
        """The rule the designer kept breaking, shown rather than stated."""
        self._document().validate()

    def test_the_primitives_take_no_inputs(self) -> None:
        from forge_ir.spec import COMPOSITION_EXAMPLE

        primitives = [f for f in COMPOSITION_EXAMPLE
                      if f["kind"] in ("box", "cylinder", "sphere")]
        self.assertEqual(len(primitives), 2)
        for feature in primitives:
            self.assertNotIn("inputs", feature, feature["id"])

    def test_a_boolean_is_what_joins_them(self) -> None:
        from forge_ir.spec import COMPOSITION_EXAMPLE

        booleans = [f for f in COMPOSITION_EXAMPLE
                    if f["kind"] in ("union", "subtract", "intersect")]
        self.assertEqual(len(booleans), 1)
        self.assertEqual(sorted(booleans[0]["inputs"]), ["base", "post"])

    def test_it_is_in_the_guide(self) -> None:
        guide = authoring_guide()
        self.assertIn("A part made of more than one solid", guide)
        self.assertIn('"kind": "union"', guide)
        self.assertIn("A primitive never has inputs", guide.replace("\n", " "))

    def test_it_is_driven_by_parameters_not_numbers(self) -> None:
        """An example full of literals teaches a non-parametric habit."""
        from forge_ir.spec import COMPOSITION_EXAMPLE

        rendered = json.dumps(list(COMPOSITION_EXAMPLE))
        for name in ("shaft_diameter", "stand_off", "boss_diameter"):
            self.assertIn(name, rendered)

    def test_the_guide_still_fits_its_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class AnExampleHasToShowWhereItGoes(unittest.TestCase):
    """A fragment shown without its container was read as a different container.

    The composition example went into the guide as a bare JSON array of
    features. The designer read an array of objects carrying `id` and produced
    them as *components* -- `base` and `post` as separate parts, each with its
    own parameters and features -- and the answer ran past 19,000 characters
    before the output ceiling cut it off. The content was right and the framing
    was missing.
    """

    def test_the_composition_example_is_a_component(self) -> None:
        from forge_ir.spec import composition_component

        component = composition_component()
        self.assertEqual(component["id"], "bracket")
        self.assertIn("features", component)
        self.assertIn("parameters", component)

    def test_every_parameter_its_features_use_is_declared(self) -> None:
        """An example referring to parameters it does not define teaches a bug."""
        from forge_ir.spec import composition_component

        component = composition_component()
        declared = {p["id"] for p in component["parameters"]}
        rendered = json.dumps(component["features"])
        for name in declared:
            self.assertIn(name, rendered, f"{name} is declared but never used")

    def test_it_compiles_as_the_component_the_guide_shows(self) -> None:
        from forge_geom import measure_mass_properties
        from forge_ir.spec import composition_component
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000002",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "Composition",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [composition_component()],
        }))
        part = Compiler().compile_component(document.components[0])
        properties = measure_mass_properties(part.solid, max_depth=6)
        self.assertGreater(properties.volume.magnitude.lo, 0.0)

    def test_the_guide_says_it_is_one_entry_of_components(self) -> None:
        guide = authoring_guide(include_catalogue=False).replace("\n", " ")
        self.assertIn("one entry of `components`", guide)
        self.assertIn("features, not components", guide)

    def test_the_guide_says_a_part_is_one_component(self) -> None:
        guide = authoring_guide(include_catalogue=False).replace("\n", " ")
        self.assertIn("A part is one component", guide)
        self.assertIn("assembly of separable parts", guide)

    def test_the_answer_example_shows_only_answer_fields(self) -> None:
        from forge_ir.spec import DESIGNER_ANSWER_FIELDS, designer_answer_json

        answer = json.loads(designer_answer_json())
        self.assertEqual(sorted(answer), sorted(DESIGNER_ANSWER_FIELDS))

    def test_the_answer_example_matches_what_the_role_asks_for(self) -> None:
        """The example and the schema must not disagree about the shape."""
        from forge_ir.spec import designer_answer_json
        from forge_roles import ForgeIRDesigner

        allowed = set(
            ForgeIRDesigner().output_schema()["properties"]["document"]["properties"]
        )
        self.assertEqual(set(json.loads(designer_answer_json())) - allowed, set())

    def test_the_answer_example_is_still_a_buildable_part(self) -> None:
        """Trimming the fields did not break the geometry it shows."""
        from forge_geom import measure_mass_properties
        from forge_ir.spec import designer_answer_json
        from forge_kernel import Compiler

        answer = json.loads(designer_answer_json())
        document = Document.from_json(json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000003",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            **answer,
        }))
        part = Compiler().compile_component(document.components[0])
        properties = measure_mass_properties(part.solid, max_depth=6)
        self.assertGreater(properties.volume.magnitude.lo, 0.0)

    def test_returning_the_trimmed_example_is_still_caught_as_an_echo(self) -> None:
        """Making it shorter must not make it easier to hand back unchanged."""
        from forge_ir.spec import designer_answer_json
        from forge_roles import ForgeIRDesigner, RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(
                {"rationale": "r", "document": json.loads(designer_answer_json())}
            )
        self.assertIn("worked example", str(caught.exception))

    def test_the_guide_still_fits_its_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class ACountSpelledAsAQuantity(unittest.TestCase):
    """Exactly determined is not the same as ambiguous.

    `{"magnitude": 4, "unit": ""}` is the form every *component* parameter
    takes, written in the one *feature* position documented as bare. It was
    refused -- and the design it appeared in was otherwise correct, all the way
    to a watertight solid. A decoder that can compute the value exactly and
    refuses to, on a point of style, spends the author's time to look strict.

    What stays refused is what is genuinely undecided: a dimensional count, a
    fractional one, one below one.
    """

    def _document(self, count: object) -> dict:
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "T",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [{
                "id": "c",
                "name": "C",
                "parameters": [],
                "features": [
                    {"id": "body", "kind": "box",
                     "parameters": {"size": {"vector": [10.0, 10.0, 10.0],
                                             "unit": "mm"}}},
                    {"id": "pat", "kind": "pattern_linear", "inputs": ["body"],
                     "parameters": {"count": count,
                                    "spacing": {"vector": [20.0, 0, 0],
                                                "unit": "mm"}}},
                ],
            }],
        }

    def _build(self, count: object):
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps(self._document(count)))
        return Compiler().compile_component(document.components[0])

    def _refusal(self, count: object) -> str:
        from forge_ir import SchemaError, SchemaErrorGroup

        try:
            self._build(count)
        except (SchemaError, SchemaErrorGroup) as error:
            return str(error)
        self.fail(f"{count!r} was accepted")

    def test_the_dimensionless_quantity_form_is_accepted(self) -> None:
        self._build({"magnitude": 4, "unit": ""})

    def test_it_means_the_same_as_the_bare_form(self) -> None:
        """Same count, same geometry -- and the same content hash."""
        self.assertEqual(
            self._build(4).part_hash,
            self._build({"magnitude": 4, "unit": ""}).part_hash,
        )

    def test_a_missing_unit_is_read_as_dimensionless(self) -> None:
        self._build({"magnitude": 4})

    def test_a_dimensional_count_is_still_refused(self) -> None:
        self.assertIn("carries no unit", self._refusal({"magnitude": 4, "unit": "mm"}))

    def test_a_fractional_count_is_still_refused(self) -> None:
        self.assertIn("whole number", self._refusal({"magnitude": 4.5, "unit": ""}))

    def test_a_count_below_one_is_still_refused(self) -> None:
        self.assertIn("at least 1", self._refusal({"magnitude": 0, "unit": ""}))

    def test_an_invented_field_beside_it_is_still_refused(self) -> None:
        self._refusal({"magnitude": 4, "unit": "", "tolerance": 1})


class RepeatingACutIsNotRepeatingThePart(unittest.TestCase):
    """The mistake that produced four bracket-shaped plates.

    `pattern_linear` repeats a *solid*. Asked for four M5 bolts, the designer
    declared `bolt_count` and `bolt_diameter` as parameters -- it had read the
    brief correctly -- and then wrote
    `{"kind": "pattern_linear", "inputs": ["shaft_hole"]}`: repeat the finished
    body four times. It got precisely what the feature promises. What it wanted
    was four holes, and the route to that (make the cutter, pattern the cutter,
    subtract the result) appeared nowhere in the guide.

    So these tests do two things: hold the note that names the route, and
    compile the route to prove it is the right one.
    """

    def _plate_with_four_holes(self) -> dict:
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-00000000000a",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "Four holes",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [{
                "id": "plate",
                "name": "Plate",
                "parameters": [
                    {"id": "bolt_d", "value": {"magnitude": 5.5, "unit": "mm"}},
                    {"id": "pitch", "value": {"magnitude": 40.0, "unit": "mm"}},
                    {"id": "t", "value": {"magnitude": 6.0, "unit": "mm"}},
                ],
                "features": [
                    {"id": "base", "kind": "box", "parameters": {
                        "size": {"vector": [60.0, 60.0, "t"], "unit": "mm"},
                        "centered": True}},
                    {"id": "pin", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "bolt_d", "unit": "mm"},
                        "height": {"magnitude": 40.0, "unit": "mm"},
                        "origin": {"vector": ["-pitch / 2", "-pitch / 2", -20.0],
                                   "unit": "mm"}}},
                    {"id": "row", "kind": "pattern_linear", "inputs": ["pin"],
                     "parameters": {"count": 2,
                                    "spacing": {"vector": ["pitch", 0, 0],
                                                "unit": "mm"}}},
                    {"id": "grid", "kind": "pattern_linear", "inputs": ["row"],
                     "parameters": {"count": 2,
                                    "spacing": {"vector": [0, "pitch", 0],
                                                "unit": "mm"}}},
                    {"id": "drilled", "kind": "subtract",
                     "inputs": ["base", "grid"], "parameters": {}},
                ],
            }],
        }

    def test_the_route_compiles(self) -> None:
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps(self._plate_with_four_holes()))
        Compiler().compile_component(document.components[0])

    def test_it_removes_exactly_four_holes_worth_of_material(self) -> None:
        """Measured against the arithmetic, not against itself."""
        import math

        from forge_geom import measure_mass_properties
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps(self._plate_with_four_holes()))
        part = Compiler().compile_component(document.components[0])
        properties = measure_mass_properties(part.solid, max_depth=7)
        expected = 60 * 60 * 6 - 4 * math.pi * (5.5 / 2) ** 2 * 6
        self.assertAlmostEqual(
            properties.volume.magnitude.midpoint, expected, delta=expected * 0.02
        )

    def test_the_catalogue_names_the_route(self) -> None:
        catalogue = feature_catalogue(["pattern_linear"])
        self.assertIn("several bodies, not several holes", catalogue)
        self.assertIn("`subtract`", catalogue)

    def test_the_circular_pattern_says_it_too(self) -> None:
        self.assertIn(
            "pattern the cutting primitive",
            feature_catalogue(["pattern_circular"]),
        )

    def test_the_note_reaches_the_guide(self) -> None:
        self.assertIn("several bodies, not several holes", authoring_guide())

    def test_the_guide_still_fits_its_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class TheFixIsWrittenOutNotDescribed(unittest.TestCase):
    """Three identical failures against a hint that said what to do in words.

    A standoff came back as a `base_plate` and a chain ending in `hole`, with
    nothing joining them. The message said "add a `union` or `subtract` that
    consumes them all" -- correct, complete, and delivered three times to a
    model that returned the same two-terminal graph each time.

    Every prompt fix in this system has taught the same lesson: a model copies
    a line far more reliably than it follows a description of one. So the
    message now carries the literal feature, built from the ids the model
    itself wrote. The design decision that is genuinely a decision -- weld or
    cut -- stays with the model, named alongside.
    """

    def _loose(self) -> dict:
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1,
            "name": "Standoff",
            "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
            "requirements": [],
            "assumptions": [],
            "components": [{
                "id": "standoff", "name": "Standoff", "parameters": [],
                "features": [
                    {"id": "base_plate", "kind": "box", "parameters": {
                        "size": {"vector": [50.0, 50.0, 5.0], "unit": "mm"},
                        "centered": True}},
                    {"id": "post", "kind": "cylinder", "parameters": {
                        "diameter": {"magnitude": 25.0, "unit": "mm"},
                        "height": {"magnitude": 30.0, "unit": "mm"}}},
                    {"id": "hole", "kind": "hole", "inputs": ["post"],
                     "parameters": {
                        "diameter": {"magnitude": 8.0, "unit": "mm"},
                        "position": {"vector": [0, 0, 0], "unit": "mm"},
                        "axis": [0, 0, 1]}},
                ],
            }],
        }

    def _hint(self, document: dict) -> str:
        from forge_ir import SchemaError, SchemaErrorGroup
        from forge_roles.base import problems_from_schema_error

        try:
            Document.from_json(json.dumps(document))
        except (SchemaError, SchemaErrorGroup) as error:
            return problems_from_schema_error(error)[0].replace("\\", "")
        self.fail("the document was accepted")

    def test_the_message_contains_the_feature_to_paste(self) -> None:
        hint = self._hint(self._loose())
        self.assertIn(
            '{"id": "part_body", "kind": "union", '
            '"inputs": ["base_plate", "hole"]}',
            hint,
        )

    def test_it_offers_the_cut_as_the_alternative(self) -> None:
        """Weld or cut is design intent, and stays the model's choice."""
        hint = self._hint(self._loose())
        self.assertIn("`subtract`", hint)
        self.assertIn("body first", hint)

    def test_pasting_it_produces_a_part_that_builds(self) -> None:
        """The advice has to be true, not merely encouraging."""
        from forge_geom import extract_surface, measure_mass_properties
        from forge_kernel import Compiler

        document = self._loose()
        document["components"][0]["features"].append(
            {"id": "body", "kind": "union", "inputs": ["base_plate", "hole"]}
        )
        built = Document.from_json(json.dumps(document))
        part = Compiler().compile_component(built.components[0])
        self.assertGreater(
            measure_mass_properties(part.solid, max_depth=6).volume.magnitude.lo,
            0.0,
        )
        self.assertTrue(extract_surface(part.solid, resolution=48).is_watertight()[0])

    def test_the_suggested_id_does_not_encode_the_current_collision(self) -> None:
        """This test used to assert the bug that cost a 64-minute run.

        The old suggestion tried `body`, then `body_2`, `body_3`, until it
        found a name free in the draft it was looking at. A model pasted
        `body_2` exactly as told, then wired its holes to `body` -- the
        obvious name, and by then an unused one, because the collision the
        suffix encoded had been in the *previous* draft. Three attempts died
        on `unknown feature: body`.

        A suggested name must be stable across attempts. `part_body` does not
        move when the graph does, and `_normalise_document` now applies this
        edit itself, so reaching this hint at all is the fallback path.
        """
        document = self._loose()
        document["components"][0]["features"][0]["id"] = "body"
        for feature in document["components"][0]["features"]:
            if feature.get("inputs") == ["base_plate"]:
                feature["inputs"] = ["body"]
        hint = self._hint(document)
        self.assertIn('"id": "part_body"', hint)
        self.assertNotIn("body_2", hint)

    def test_three_loose_solids_are_all_named_in_the_fix(self) -> None:
        document = self._loose()
        document["components"][0]["features"].append(
            {"id": "spare", "kind": "sphere", "parameters": {
                "diameter": {"magnitude": 4.0, "unit": "mm"}}}
        )
        hint = self._hint(document)
        self.assertIn('"inputs": ["base_plate", "hole", "spare"]', hint)


class ThePitfallThatOnlyGeometryCatches(unittest.TestCase):
    """Where a through hole goes to die.

    The live standoff run drilled the post and *then* unioned it to its base
    plate. Nothing in the document is wrong to look at: the hole has no
    `depth`, so it is a through hole, and the union is how a post gets attached
    to a plate. The plate simply fills the bottom of the bore back in, and the
    part prints as a post with a pocket.

    `GEOM_THROUGH_HOLES_OPEN` catches it after the fact, which costs a repair
    round -- roughly half an hour on the self-hosted model this is tested
    against. The guide is what stops it being written in the first place, so
    the rule is asserted here rather than left to survive by good intentions.
    """

    def test_the_guide_says_to_cut_holes_last(self) -> None:
        guide = authoring_guide(include_catalogue=False).replace("\n", " ")
        self.assertIn("Cut holes last", guide)

    def test_the_guide_says_what_goes_wrong(self) -> None:
        """A rule with no failure attached is a rule that gets optimised away."""
        guide = authoring_guide(include_catalogue=False).replace("\n", " ")
        self.assertIn("fills the bore straight back in", guide)

    def test_the_catalogue_entry_says_it_too(self) -> None:
        """The designer reads the catalogue when it reaches for `hole`."""
        from forge_ir.features import feature_spec

        notes = feature_spec("hole").notes
        self.assertIn("CUT HOLES LAST", notes)
        self.assertIn("union", notes)

    def test_the_guide_still_fits_its_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class NamingAGradeYouHaveNeverBeenShown(unittest.TestCase):
    """"Do not write `aluminium`, name a grade" -- and then no list of grades.

    The analysis layer refuses a family name outright, on purpose: within a
    family the yield strength varies by more than threefold, so a margin
    derived from "pla" would be fiction. But the designer was told to be
    specific and shown exactly one specific thing, in an example about a
    clevis. Asked for a printed part it writes `"material": "pla"`, and every
    mass and margin that depends on it is refused at measurement time -- a
    whole run spent on a design that could never report a mass.
    """

    def _prompt(self) -> str:
        from forge_roles import ForgeIRDesigner

        return ForgeIRDesigner().system_prompt()

    def test_every_material_the_analysis_layer_knows_is_offered(self) -> None:
        from forge_analysis import available

        prompt = self._prompt()
        for identifier in available():
            self.assertIn(
                identifier,
                prompt,
                f"{identifier} can be computed with and is never shown to the "
                "designer",
            )

    def test_the_list_comes_from_the_registry_not_a_copy(self) -> None:
        """A hand-written list is one refactor away from being a lie."""
        import inspect

        from forge_roles import library

        source = inspect.getsource(library._materials_forge_knows)
        self.assertIn("available()", source)

    def test_it_says_a_family_name_is_refused(self) -> None:
        """Without the reason, "be specific" reads as a style preference."""
        prompt = self._prompt()
        self.assertIn("family name", prompt)
        self.assertIn("refused", prompt)

    def test_it_says_what_to_do_about_a_material_forge_lacks(self) -> None:
        """Otherwise the honest answer looks like picking the nearest id."""
        self.assertIn("leave `material` empty", self._prompt())


class TheExpressionPutWhereTheLiteralGoes(unittest.TestCase):
    """`{"value": {"expression": "4"}}` on a component parameter.

    Two spellings for one idea, and only one of them was accepted. A *feature*
    parameter writes `{"expression": "..."}` as its value; a *component*
    parameter carries the expression as a sibling of `id`. Writing the feature
    form in the component position is the obvious mistake, and it produced
    "an expression parameter requires a resolved parameter graph" -- a sentence
    about an internal precondition that names neither the mistake nor the fix.

    Live cost: 82 minutes, three identical documents, no part.
    """

    def _document(self, parameter: dict) -> str:
        return json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-00000000c001",
            "project_id": "00000000-0000-4000-8000-00000000c0ff",
            "revision": 1,
            "units": {"length": "mm", "mass": "g", "angle": "deg"},
            "risk_class": "low",
            "requirements": [],
            "assumptions": [],
            "components": [{
                "id": "part", "name": "Part",
                "parameters": [
                    {"id": "plate_length", "value": {"magnitude": 60, "unit": "mm"}},
                    parameter,
                ],
                "features": [{
                    "id": "body", "kind": "box",
                    "parameters": {"size": {
                        "vector": ["plate_length", 20, 6], "unit": "mm"}},
                }],
                "interfaces": [],
            }],
        })

    def test_it_is_read_as_the_expression_it_plainly_is(self) -> None:
        document = Document.from_json(
            self._document({"id": "half", "value": {
                "expression": "plate_length / 2", "unit": "mm"}})
        )
        resolved = document.components[0].parameters.resolve()
        self.assertEqual(str(resolved["half"]), "30 mm")

    def test_a_constant_written_as_an_expression_works_too(self) -> None:
        """The exact value the live run died on."""
        document = Document.from_json(
            self._document({"id": "bolt_count", "value": {"expression": "4"}})
        )
        resolved = document.components[0].parameters.resolve()
        self.assertEqual(resolved["bolt_count"].magnitude.midpoint, 4.0)

    def test_the_literal_form_is_unchanged(self) -> None:
        document = Document.from_json(
            self._document({"id": "width", "value": {
                "magnitude": 20.0, "unit": "mm"}})
        )
        resolved = document.components[0].parameters.resolve()
        self.assertEqual(str(resolved["width"]), "20 mm")

    def test_the_sibling_form_is_unchanged(self) -> None:
        document = Document.from_json(
            self._document({"id": "half", "expression": "plate_length / 2",
                            "unit": "mm"})
        )
        resolved = document.components[0].parameters.resolve()
        self.assertEqual(str(resolved["half"]), "30 mm")


class EveryNumberTheUserWroteIsChecked(unittest.TestCase):
    """A requirement set that drops eight of ten stated dimensions.

    Observed live. The brief gave a 60 x 40 x 6 plate, an 18 x 25 boss, a 2 mm
    fillet, an 8 mm bore and four 4.5 mm holes on 44 x 24 centres. Two
    requirements came back -- overall height and mass -- and not one dimension.
    The part would have been built, gated and reported green without anything
    ever comparing it to what was asked for.

    The numbers are extracted mechanically, because the failure being guarded
    against is precisely a model's judgement about which of them mattered.
    """

    BRIEF = (
        "The base plate is 60 mm long, 40 mm wide and 6 mm thick. A boss 18 mm "
        "in diameter and 25 mm tall stands in the middle. It must weigh no "
        "more than 30 g."
    )

    def test_every_stated_quantity_is_found(self) -> None:
        from forge_roles.library import _numbers_the_brief_states

        found = [str(q) for q in _numbers_the_brief_states(self.BRIEF)]
        self.assertEqual(
            found, ["60 mm", "40 mm", "6 mm", "18 mm", "25 mm", "30 g"]
        )

    def test_prose_that_only_looks_like_a_quantity_is_not_one(self) -> None:
        """"6 in the middle" is not six inches, and 6061-T6 is not a number."""
        from forge_roles.library import _numbers_the_brief_states

        self.assertEqual(
            _numbers_the_brief_states(
                "6 in the middle, 6061-T6 aluminium, 100% infill, 3D printed"
            ),
            (),
        )

    def test_a_set_that_covers_them_is_accepted(self) -> None:
        from forge_roles.library import _covers, _numbers_the_brief_states

        declared = [
            q for q in _numbers_the_brief_states(self.BRIEF)
        ]
        for quantity in _numbers_the_brief_states(self.BRIEF):
            self.assertTrue(_covers(quantity, declared))

    def test_a_different_unit_for_the_same_amount_still_covers_it(self) -> None:
        """30 g and 0.03 kg are the same fact, and refusing that is pedantry."""
        from forge_roles.library import _covers, _numbers_the_brief_states
        from forge_units import Q

        grams = _numbers_the_brief_states("no more than 30 g")[0]
        self.assertTrue(_covers(grams, [Q(0.03, "kg")]))

    def test_the_prompt_lists_them_before_the_answer_is_written(self) -> None:
        """A contract discovered by being rejected costs a round to learn."""
        from forge_roles import BriefInterpreter, RequirementsEngineer
        from forge_roles.library import Intent

        messages = RequirementsEngineer().build_messages(
            brief=self.BRIEF,
            intent=Intent(
                summary="a plate", part_kind="plate",
                stated=(), implied=(), unstated=(),
            ),
        )
        text = "\n".join(m.content for m in messages)
        for number in ("60 mm", "18 mm", "30 g"):
            self.assertIn(number, text)

    def test_dropping_them_is_rejected_with_the_list(self) -> None:
        from forge_roles import RequirementsEngineer, RoleOutputError

        answer = {
            "risk_class": "low",
            "requirements": [
                {
                    "id": "REQ_MASS",
                    "statement": "The part shall weigh no more than 30 g.",
                    "type": "performance", "strength": "hard",
                    "verification": "exact_geometry",
                    "threshold": {"magnitude": 30.0, "unit": "g"},
                    "comparison": "at_most", "measurement": "mass",
                    "source": "derived", "state": "not_tested",
                }
            ],
            "assumptions": [],
            "unknowns": [],
        }
        with self.assertRaises(RoleOutputError) as caught:
            RequirementsEngineer().parse(answer, brief=self.BRIEF)
        problems = " ".join(caught.exception.problems)
        # The plate's length and width are the whole part's footprint, and
        # Forge measures those on the built part itself; what is still
        # missing is reported.
        self.assertIn("6 mm", problems)
        self.assertIn("18 mm", problems)
        self.assertIn("25 mm", problems)
        self.assertNotIn("30 g", problems)


class ABriefThatAnswersTheLoadQuestion(unittest.TestCase):
    """"It carries no structural load" is an answer, not a silence."""

    def test_the_prompt_says_so(self) -> None:
        from forge_roles import RequirementsEngineer

        prompt = RequirementsEngineer().system_prompt()
        self.assertIn("carries no structural load", prompt)
        self.assertIn("no load unknown", prompt)


class OnePartIsOneComponent(unittest.TestCase):
    """Forge builds and gates `components[0]` and nothing else.

    Asked for a plate with a boss and five holes, the designer returned four
    components, one per piece. Three of them would never have been compiled,
    measured or gated -- and the report would have been green.
    """

    def _answer(self, count: int) -> dict:
        return {
            "rationale": "r",
            "document": {
                "name": "Part",
                "components": [
                    {
                        "id": f"piece_{index}",
                        "name": "Piece",
                        "parameters": [
                            {"id": "t", "value": {"magnitude": 6, "unit": "mm"}}
                        ],
                        "features": [{
                            "id": "body", "kind": "box",
                            "parameters": {"size": {
                                "vector": [20, 20, "t"], "unit": "mm"}},
                        }],
                    }
                    for index in range(count)
                ],
            },
        }

    def test_several_components_are_sent_back(self) -> None:
        from forge_roles import ForgeIRDesigner, RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(self._answer(4))
        problems = " ".join(caught.exception.problems)
        self.assertIn("4 components", problems)
        self.assertIn("FEATURE", problems)

    def test_one_component_passes(self) -> None:
        from forge_roles import ForgeIRDesigner

        draft = ForgeIRDesigner().parse(self._answer(1))
        self.assertEqual(len(draft.document.components), 1)


class AParameterNameWhereTheNumberGoes(unittest.TestCase):
    """`{"magnitude": "fillet_thickness", "unit": "mm"}`.

    The model is saying "this value comes from that parameter", which is what
    an expression is; only the spelling is wrong. It used to reach `float()`
    unguarded and raise a bare ValueError that escaped every handler in the
    stack and ended a fifty-minute run with no artefacts at all.

    Two separate defects, fixed separately: the conversion now states its
    failure in the vocabulary of the layer it happened in, and the intention is
    read rather than rejected.
    """

    def _document(self, blend: dict) -> str:
        return json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-00000000c001",
            "project_id": "00000000-0000-4000-8000-00000000c0ff",
            "revision": 1,
            "units": {"length": "mm", "mass": "g", "angle": "deg"},
            "risk_class": "low",
            "requirements": [],
            "assumptions": [],
            "components": [{
                "id": "part", "name": "Part",
                "parameters": [
                    {"id": "plate_thickness", "value": {"magnitude": 6, "unit": "mm"}},
                    {"id": "fillet_thickness", "value": {"magnitude": 2, "unit": "mm"}},
                ],
                "features": [
                    {"id": "a", "kind": "box", "parameters": {"size": {
                        "vector": [20, 20, "plate_thickness"], "unit": "mm"}}},
                    {"id": "b", "kind": "cylinder", "parameters": {
                        "diameter": {"magnitude": 10, "unit": "mm"},
                        "height": {"magnitude": 9, "unit": "mm"}}},
                    {"id": "body", "kind": "union", "inputs": ["a", "b"],
                     "parameters": {"blend_radius": blend}},
                ],
                "interfaces": [],
            }],
        })

    def test_the_document_that_killed_the_run_now_builds(self) -> None:
        from forge_kernel import Compiler

        document = Document.from_json(
            self._document({"magnitude": "fillet_thickness", "unit": "mm"})
        )
        part = Compiler().compile_component(document.components[0])
        self.assertTrue(part.part_hash)

    def test_it_really_is_the_parameter_and_not_a_zero(self) -> None:
        """Reading the intention is only right if it reads the right value."""
        from forge_kernel import Compiler

        named = Document.from_json(
            self._document({"magnitude": "fillet_thickness", "unit": "mm"})
        )
        spelled = Document.from_json(
            self._document({"expression": "fillet_thickness", "unit": "mm"})
        )
        self.assertEqual(
            Compiler().compile_component(named.components[0]).part_hash,
            Compiler().compile_component(spelled.components[0]).part_hash,
        )

    def test_a_magnitude_that_is_neither_is_a_schema_error(self) -> None:
        """Not a crash: an error with a pointer, which the repair loop can use."""
        from forge_ir import SchemaError, SchemaErrorGroup

        with self.assertRaises((SchemaError, SchemaErrorGroup)) as caught:
            Document.from_json(self._document({"magnitude": "!!!", "unit": "mm"}))
        self.assertIn("blend_radius", str(caught.exception))

    def test_the_units_layer_states_its_own_failure(self) -> None:
        from forge_units import ForgeUnitsError, Quantity

        for magnitude in ("plate_thickness", [1, 2], None, True):
            with self.assertRaises(ForgeUnitsError):
                Quantity.from_dict({"magnitude": magnitude, "unit": "mm"})

    def test_the_message_names_the_spelling_that_works(self) -> None:
        from forge_units import ForgeUnitsError, Quantity

        with self.assertRaises(ForgeUnitsError) as caught:
            Quantity.from_dict({"magnitude": "fillet_thickness", "unit": "mm"})
        self.assertIn("expression", caught.exception.detail["hint"])
        self.assertIn("fillet_thickness", caught.exception.detail["hint"])


class ACountCannotSeeInsideAPattern(unittest.TestCase):
    """Four tagged holes are four features, not one pattern.

    `feature_count:hole:mounting` counts *features* carrying the tag. A
    `pattern_linear` is one feature that makes copies of a solid; the copies
    are not features, cannot carry tags, and do not count. A designer that
    patterns its bolt holes satisfies the geometry and fails the count, and the
    repair loop then has nothing useful to say.
    """

    def test_the_prompt_says_a_pattern_does_not_count(self) -> None:
        from forge_roles import ForgeIRDesigner, RequirementsEngineer
        from forge_roles.library import Intent, RequirementSet

        requirements = RequirementSet(
            requirements=({
                "id": "REQ_BOLTS",
                "statement": "There shall be four mounting holes.",
                "measurement": "feature_count:hole:mounting",
                "comparison": "equals",
            },),
            assumptions=(), unknowns=(),
        )
        messages = ForgeIRDesigner().build_messages(
            intent=Intent(summary="a plate", part_kind="plate",
                          stated=(), implied=(), unstated=()),
            requirements=requirements,
        )
        text = "\n".join(m.content for m in messages)
        self.assertIn("SEPARATE features", text)
        self.assertIn("pattern_linear", text)

    def test_the_guide_says_a_plate_is_a_box(self) -> None:
        guide = authoring_guide(include_catalogue=False).replace("\n", " ")
        self.assertIn("A rectangular plate is a `box`", guide)
        self.assertIn("datum_plane", guide)

    def test_the_guide_still_fits_its_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class OneBindingMeasuresOneThing(unittest.TestCase):
    """`bounding_box_z equals 6` and `bounding_box_z at_most 32`, together.

    Observed live. The first was meant as "the base plate is 6 mm thick" and
    the second as "the part stands no taller than 32 mm". They measure the same
    number, and on a part with a 25 mm boss on a 6 mm plate that number is 31 --
    so the design is correct and the report says it failed.

    Worse than a false alarm: the repair loop acts on it. Told that
    `bounding_box_z` must equal 6, an analyst will shrink the boss.
    """

    def _requirement(self, identifier, measurement, comparison, magnitude):
        return {
            "id": identifier, "statement": identifier, "type": "geometric",
            "strength": "hard", "verification": "exact_geometry",
            "threshold": {"magnitude": magnitude, "unit": "mm"},
            "comparison": comparison, "measurement": measurement,
            "source": "user", "state": "accepted",
        }

    def _problems(self, requirements):
        from forge_roles.library import _one_binding_measures_one_thing

        return _one_binding_measures_one_thing(requirements)

    def test_the_live_collision_is_caught(self) -> None:
        problems = self._problems([
            self._requirement("REQ_PLATE_T", "bounding_box_z", "equals", 6.0),
            self._requirement("REQ_HEIGHT", "bounding_box_z", "at_most", 32.0),
        ])
        self.assertEqual(len(problems), 1)
        self.assertIn("REQ_PLATE_T", problems[0])
        self.assertIn("parameter:<id>", problems[0])

    def test_a_range_on_one_binding_is_fine(self) -> None:
        """at_least and at_most together are a range, not a contradiction."""
        self.assertEqual(self._problems([
            self._requirement("REQ_MIN", "mass", "at_least", 10.0),
            self._requirement("REQ_MAX", "mass", "at_most", 30.0),
        ]), [])

    def test_the_same_binding_once_is_fine(self) -> None:
        self.assertEqual(self._problems([
            self._requirement("REQ_HEIGHT", "bounding_box_z", "at_most", 32.0),
        ]), [])

    def test_different_bindings_do_not_collide(self) -> None:
        self.assertEqual(self._problems([
            self._requirement("REQ_A", "parameter:plate_thickness", "equals", 6.0),
            self._requirement("REQ_B", "bounding_box_z", "at_most", 32.0),
        ]), [])


class ABriefThatSaysThereIsNoLoad(unittest.TestCase):
    """"It carries no structural load - there is no load case."

    The model asked for "the magnitude and direction of the load on the arm" --
    an arm the part does not have -- twice, on two runs. Its prompt's worked
    example is a loaded bracket, and a small model reproduces the shape of its
    example over the content of its input.

    The cost is not cosmetic: a critical unknown stops the run to ask, or under
    --assume becomes a high-risk assumption that blocks release. Either way the
    user is interrogated about something they wrote down.
    """

    BRIEF = ("A printed fixture. It carries no structural load - it is a "
             "printed fixture, so there is no load case.")

    def _problems(self, brief, structured):
        from forge_roles.library import _the_brief_already_answered_the_load

        return _the_brief_already_answered_the_load(brief, structured)

    def test_a_load_unknown_is_refused(self) -> None:
        problems = self._problems(self.BRIEF, {"unknowns": [{
            "id": "UNKNOWN_LOAD",
            "question": "What is the magnitude and direction of the load?"}]})
        self.assertEqual(len(problems), 1)
        self.assertIn("UNKNOWN_LOAD", problems[0])

    def test_a_load_assumption_is_refused_too(self) -> None:
        problems = self._problems(self.BRIEF, {"assumptions": [{
            "id": "ASM_LOAD", "statement": "A design load of 500 N is applied."}]})
        self.assertIn("ASM_LOAD", problems[0])

    def test_saying_nothing_about_loads_is_accepted(self) -> None:
        self.assertEqual(self._problems(self.BRIEF, {
            "unknowns": [{"id": "U", "question": "What surface finish?"}],
            "assumptions": [],
        }), [])

    def test_a_brief_that_is_silent_about_loads_carries_none(self) -> None:
        """The user's rule: say nothing of a load and there is none. A brief
        that names no force, no weight it holds and no word for a strength
        describes a shape, and a question about its load is refused."""
        self.assertEqual(len(self._problems(
            "A bracket 60 mm long.",
            {"unknowns": [{"id": "UNKNOWN_LOAD", "question": "What load?"}]},
        )), 1)

    def test_a_brief_that_names_a_load_without_a_figure_is_asked(self) -> None:
        """"Make it strong enough" names a load and gives no figure: that
        one really is an unknown."""
        self.assertEqual(self._problems(
            "A bracket 60 mm long. Make it strong enough.",
            {"unknowns": [{"id": "UNKNOWN_LOAD", "question": "What load?"}]},
        ), [])


class AnEntityBindingWhereAParameterWasMeant(unittest.TestCase):
    """Four requirements in one set, every one `entity:<something>`.

    `entity:` measures a published face's own size, and only resolves if some
    feature publishes that exact name -- a much stronger claim than "the design
    declares this dimension", which is what the author nearly always means. The
    error stated the form and left the author to notice that the whole prefix
    was wrong.
    """

    def test_the_error_names_the_parameter_binding_to_use(self) -> None:
        from forge_ir.measurements import MeasurementError, parse_measurement

        with self.assertRaises(MeasurementError) as caught:
            parse_measurement("entity:post_diameter")
        message = str(caught.exception)
        self.assertIn("parameter:post_diameter", message)
        self.assertIn("required to declare", message)

    def test_a_dotted_name_becomes_a_legal_parameter_id(self) -> None:
        """`entity:shaft.bore` suggests `parameter:shaft_bore`, not a dot."""
        from forge_ir.measurements import MeasurementError, parse_measurement

        with self.assertRaises(MeasurementError) as caught:
            parse_measurement("entity:shaft.bore")
        self.assertIn("parameter:shaft_bore", str(caught.exception))

    def test_a_complete_entity_binding_is_still_accepted(self) -> None:
        binding = parse_measurement("entity:shaft.bore:diameter")
        self.assertEqual(binding.kind, "entity")
        self.assertEqual(binding.argument, "shaft.bore")
        self.assertEqual(binding.sub_argument, "diameter")


class NumbersNobodyAskedFor(unittest.TestCase):
    """An area multiplied out of the brief's own dimensions.

    Observed live on a nine-number brief: `REQ_BASE_AREA` at 900 mm² (30 x 30)
    and `REQ_BASE_VOLUME` at 3600 mm³ (30 x 30 x 4), neither asked for, each
    restating dimensions already being checked -- and each needing a
    measurement that does not exist, so the answer failed on its bindings
    rather than on the invention and the repair loop could not converge.

    The first draft of this rule refused any threshold the brief did not
    state, and rejected the hand-written correct answer for the bracket: a
    3 mm minimum wall and a 400 g budget are legitimate engineering that no
    brief contains. That regression is what the last three tests here protect.
    """

    BRIEF = ("A plate 30 mm square and 4 mm thick, with a 12 mm post. "
             "It must weigh no more than 8 g.")

    def _threshold(self, identifier, magnitude, unit):
        return {"id": identifier,
                "threshold": {"magnitude": magnitude, "unit": unit}}

    def _problems(self, requirements):
        from forge_roles.library import _numbers_nobody_asked_for

        return _numbers_nobody_asked_for(self.BRIEF, requirements)

    def test_an_area_that_is_two_stated_dimensions_multiplied_is_refused(self) -> None:
        problems = self._problems([
            self._threshold("REQ_BASE_AREA", 900.0, "mm\u00b2")
        ])
        self.assertEqual(len(problems), 1)
        self.assertIn("REQ_BASE_AREA", problems[0])

    def test_a_volume_that_is_three_of_them_is_refused(self) -> None:
        self.assertTrue(
            self._problems([self._threshold("REQ_VOL", 3600.0, "mm\u00b3")])
        )

    def test_an_area_that_is_not_a_product_of_them_is_accepted(self) -> None:
        """Only the restatement is refused, not derived numbers as a class."""
        self.assertEqual(
            self._problems([self._threshold("REQ_AREA", 1234.0, "mm\u00b2")]), []
        )

    def test_a_mass_budget_is_legitimate_engineering(self) -> None:
        self.assertEqual(
            self._problems([self._threshold("REQ_MASS", 400.0, "g")]), []
        )

    def test_a_minimum_wall_is_legitimate_engineering(self) -> None:
        self.assertEqual(
            self._problems([self._threshold("REQ_WALL", 3.0, "mm")]), []
        )

    def test_the_bracket_fixture_still_passes_whole(self) -> None:
        """The answer this rule must never reject, checked end to end."""
        from fixtures.bracket_responses import BRIEF, REQUIREMENTS
        from forge_roles import RequirementsEngineer

        engineer = RequirementsEngineer()
        self.assertTrue(engineer.parse(REQUIREMENTS, brief=BRIEF).requirements)


class TheBindingIsChosenBeforeTheAnswerIsWritten(unittest.TestCase):
    """Listing the numbers was half the contract; the other half is how.

    A 3B model choosing from a fifteen-entry vocabulary for each of ten
    requirements gets some wrong, and every wrong one is a repair round at six
    minutes each. Nearly all of them are `parameter:<id>`, and saying so beside
    the list costs forty tokens.
    """

    BRIEF = "A plate 30 mm square and 4 mm thick, weighing no more than 8 g."

    def _prompt(self) -> str:
        from forge_roles import RequirementsEngineer
        from forge_roles.library import Intent

        messages = RequirementsEngineer().build_messages(
            brief=self.BRIEF,
            intent=Intent(summary="a plate", part_kind="plate",
                          stated=(), implied=(), unstated=()),
        )
        return "\n".join(m.content for m in messages)

    def test_it_names_the_default_binding(self) -> None:
        self.assertIn("Bind each of them to `parameter:<id>`", self._prompt())

    def test_it_names_the_exceptions(self) -> None:
        prompt = self._prompt()
        self.assertIn("`mass`", prompt)
        self.assertIn("bounding_box_z", prompt)

    def test_it_warns_off_the_entity_binding(self) -> None:
        self.assertIn("`entity:` is not the binding", self._prompt())

    def test_it_forbids_deriving_extra_numbers(self) -> None:
        self.assertIn("THESE numbers only", self._prompt())


class AnAnswerThatIsMostlyRight(unittest.TestCase):
    """The strategy change: repair, report, or reject -- in that order.

    Every check added to this role made it stricter, and for a model that
    answers once every six minutes each strict check is another way to lose the
    whole answer. Observed live: three attempts, each producing ten good
    requirements and the same two pieces of junk, and Forge discarding all
    thirty over the six. The model never removed them; it renumbered them.

    So the rules are now sorted by who can fix them. Forge repairs what is
    unambiguous, reports what cannot be checked as NOT_TESTED -- which is what
    this system already promises for a requirement with no binding -- and
    rejects only an answer that is not usable. Nothing is silent: every repair
    and every drop is recorded and lands in the run.
    """

    BRIEF = (
        "A PLA spacer. The base is a 30 mm square plate 4 mm thick. A 12 mm "
        "post 10 mm tall stands on it. Two 3 mm holes 20 mm apart. It must "
        "weigh no more than 8 g. It carries no load - there is no load case."
    )

    def _parse(self, **overrides):
        from forge_roles import RequirementsEngineer

        answer = {
            "risk_class": "low", "assumptions": [], "unknowns": [],
            "requirements": [
                {"id": "REQ_SIZE", "statement": "30 mm square.",
                 "threshold": {"magnitude": 30.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "parameter:plate_size"},
                {"id": "REQ_T", "statement": "4 mm thick.",
                 "threshold": {"magnitude": 4.0, "unit": "mm"},
                 "comparison": "equals",
                 "measurement": "parameter:plate_thickness"},
                {"id": "REQ_POST_D", "statement": "12 mm post.",
                 "threshold": {"magnitude": 12.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "parameter:post_d"},
                {"id": "REQ_POST_H", "statement": "10 mm tall.",
                 "threshold": {"magnitude": 10.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "parameter:post_h"},
                {"id": "REQ_HOLE_D", "statement": "3 mm holes.",
                 "threshold": {"magnitude": 3.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "parameter:hole_d"},
                {"id": "REQ_HOLE_S", "statement": "20 mm apart.",
                 "threshold": {"magnitude": 20.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "parameter:hole_s"},
                {"id": "REQ_MASS", "statement": "8 g.",
                 "threshold": {"magnitude": 8.0, "unit": "g"},
                 "comparison": "at_most", "measurement": "mass"},
                # A plate the brief calls square states BOTH extents, and a
                # set that claims neither is the set that released a 30 x 12
                # plate with every claim green. `parameter:plate_size` above
                # is declared just as truthfully by either plate.
                {"id": "REQ_BB_X", "statement": "30 mm across X.",
                 "threshold": {"magnitude": 30.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "bounding_box_x"},
                {"id": "REQ_BB_Y", "statement": "30 mm across Y.",
                 "threshold": {"magnitude": 30.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "bounding_box_y"},
                # And the two holes the brief sizes, counted on the built
                # part: `parameter:hole_d` passes whenever SOME hole reads it,
                # which is how a collar with no bore was released.
                {"id": "REQ_HOLES", "statement": "Two 3 mm holes.",
                 "threshold": {"magnitude": 2, "unit": ""},
                 "comparison": "equals",
                 "measurement": "holes_of_diameter:3"},
                # And how far apart they are, on the part: `parameter:hole_s`
                # reads back the 20 mm the design declares wherever the two
                # holes are, which is how a rail with its holes 130 mm apart
                # passed "spaced 60 mm apart".
                {"id": "REQ_HOLES_APART", "statement": "20 mm apart.",
                 "threshold": {"magnitude": 1, "unit": ""},
                 "comparison": "at_least",
                 "measurement": "openings_apart:3:20"},
                # And how tall the whole thing is: the post stands on the
                # plate, 4 and 10. Parameters read back what a design
                # declares; a base built 2 mm thick declared 4 all the same.
                {"id": "REQ_BB_Z", "statement": "14 mm tall overall.",
                 "threshold": {"magnitude": 14.0, "unit": "mm"},
                 "comparison": "equals", "measurement": "bounding_box_z",
                 "source": "derived"},
                # And, the weight being limited, that the limit is not met by
                # air sealed inside: a steel cube over its limit was shelled
                # inside to pass it, and looked the same from every side.
                {"id": "REQ_NOTHING_SEALED_INSIDE",
                 "statement": "Nothing sealed inside.",
                 "threshold": {"magnitude": 0, "unit": ""},
                 "comparison": "at_most", "measurement": "sealed_voids",
                 "source": "derived"},
            ],
        }
        extra = overrides.pop("extra", ())
        drop = set(overrides.pop("drop", ()))
        brief = overrides.pop("brief", self.BRIEF)
        answer.update(overrides)
        answer["requirements"] = [
            r for r in answer["requirements"] if r["id"] not in drop
        ] + list(extra)
        return RequirementsEngineer().parse(answer, brief=brief)

    # -- repair -----------------------------------------------------------
    def test_an_entity_binding_becomes_the_parameter_it_meant(self) -> None:
        result = self._parse(extra=[{
            "id": "REQ_FILLET", "statement": "2 mm fillet.",
            "threshold": {"magnitude": 2.0, "unit": "mm"},
            "comparison": "equals", "measurement": "entity:fillet_radius"}])
        binding = next(
            dict(r)["measurement"] for r in result.requirements
            if dict(r)["id"] == "REQ_FILLET"
        )
        self.assertEqual(binding, "parameter:fillet_radius")
        self.assertTrue(any("fillet_radius" in n for n in result.notes))

    def test_a_count_of_a_feature_id_becomes_a_count_of_a_tag(self) -> None:
        """`feature_count:mounting_hole` is perfectly clear and expressible."""
        result = self._parse(extra=[{
            "id": "REQ_N", "statement": "Two mounting holes.",
            "threshold": {"magnitude": 2.0, "unit": ""},
            "comparison": "equals", "measurement": "feature_count:mounting_hole"}])
        binding = next(
            dict(r)["measurement"] for r in result.requirements
            if dict(r)["id"] == "REQ_N"
        )
        self.assertEqual(binding, "feature_count:hole:mounting")

    def test_the_boilerplate_fields_are_filled_in(self) -> None:
        """Five of the eight fields followed from the binding. Now they do."""
        first = dict(self._parse().requirements[0])
        self.assertEqual(first["strength"], "hard")
        self.assertEqual(first["verification"], "exact_geometry")
        self.assertEqual(first["type"], "geometric")

    def test_a_safety_factor_is_analytical_and_about_safety(self) -> None:
        """On a brief that has a load. This class's own brief says there is
        no load case, and a margin against a load that does not exist is now
        dropped -- see the test below."""
        result = self._parse(
            brief=self.BRIEF.replace(
                "It carries no load - there is no load case.",
                "It carries a static load at the post.",
            ),
            extra=[{
                "id": "REQ_SF", "statement": "Margin of 2.",
                "threshold": {"magnitude": 2.0, "unit": ""},
                "comparison": "at_least",
                "measurement": "safety_factor:bearing"}],
        )
        entry = next(
            dict(r) for r in result.requirements if dict(r)["id"] == "REQ_SF"
        )
        self.assertEqual(entry["type"], "safety")
        self.assertEqual(entry["verification"], "analytical")

    def test_a_margin_on_a_part_with_no_load_case_is_dropped(self) -> None:
        """It reported BLOCKED and stood between a finished part and its
        release, on a brief that says in as many words that nothing loads it.
        Nothing can compute a bearing margin without a load."""
        result = self._parse(extra=[{
            "id": "REQ_SF", "statement": "Margin of 2.",
            "threshold": {"magnitude": 2.0, "unit": ""},
            "comparison": "at_least", "measurement": "safety_factor:bearing"}])
        self.assertNotIn(
            "REQ_SF", [dict(r)["id"] for r in result.requirements])
        self.assertTrue(
            any("no load" in note for note in result.notes), result.notes)

    def test_the_weight_the_brief_states_is_bound(self) -> None:
        """The brief says "no more than 8 g" and the model left the slot
        empty, so Forge binds it rather than leaving it unchecked."""
        result = self._parse(drop=("REQ_MASS",))
        mass = [dict(r) for r in result.requirements
                if dict(r).get("measurement") == "mass"]
        self.assertEqual(len(mass), 1)
        self.assertEqual(mass[0]["comparison"], "at_most")
        self.assertEqual(mass[0]["threshold"]["magnitude"], 8.0)

    # -- report -----------------------------------------------------------
    def test_a_binding_nothing_can_parse_is_retired_not_rejected(self) -> None:
        result = self._parse(extra=[{
            "id": "REQ_AREA_CHECK", "statement": "Area.",
            "threshold": {"magnitude": 7.0, "unit": "mm"},
            "comparison": "at_most",
            "measurement": "bounding_box_x * bounding_box_y"}])
        entry = next(
            dict(r) for r in result.requirements
            if dict(r)["id"] == "REQ_AREA_CHECK"
        )
        self.assertFalse(entry.get("measurement"))
        self.assertEqual(entry["threshold"]["magnitude"], 7.0)
        self.assertTrue(any("NOT_TESTED" in n for n in result.notes))

    # -- drop -------------------------------------------------------------
    def test_a_product_of_the_briefs_dimensions_is_dropped(self) -> None:
        result = self._parse(extra=[{
            "id": "REQ_BASE_AREA", "statement": "Area.",
            "threshold": {"magnitude": 900.0, "unit": "mm²"},
            "comparison": "equals", "measurement": "surface_area"}])
        self.assertNotIn(
            "REQ_BASE_AREA", [dict(r)["id"] for r in result.requirements]
        )
        self.assertTrue(any("REQ_BASE_AREA" in n for n in result.notes))

    def test_a_load_question_the_brief_answered_is_dropped(self) -> None:
        result = self._parse(unknowns=[{
            "id": "UNKNOWN_LOAD", "question": "What load does it carry?",
            "why_it_matters": "margins", "critical": True}])
        self.assertEqual(result.unknowns, ())
        self.assertTrue(any("load" in n for n in result.notes))

    # -- reject -----------------------------------------------------------
    def test_an_answer_that_ignores_the_brief_is_still_rejected(self) -> None:
        """Repairing does not mean accepting anything."""
        from forge_roles import RequirementsEngineer, RoleOutputError

        with self.assertRaises(RoleOutputError):
            RequirementsEngineer().parse({
                "risk_class": "low", "assumptions": [], "unknowns": [],
                "requirements": [{
                    "id": "REQ_MASS", "statement": "8 g.",
                    "threshold": {"magnitude": 8.0, "unit": "g"},
                    "comparison": "at_most", "measurement": "mass"}],
            }, brief=self.BRIEF)

    def test_one_missed_number_is_a_recorded_gap_not_a_rejection(self) -> None:
        """Losing the whole answer over one number costs more than it is worth."""
        answer = self._parse(drop=["REQ_POST_H"])  # six of the brief's seven
        self.assertTrue(answer.requirements)
        self.assertTrue(
            any("not checked against" in n for n in answer.notes),
            f"the gap was not recorded: {answer.notes}",
        )
        self.assertTrue(any("10 mm" in n for n in answer.notes))

    # -- nothing is silent -------------------------------------------------
    def test_a_clean_answer_produces_no_notes(self) -> None:
        """Silence means Forge changed nothing, and that must stay meaningful."""
        self.assertEqual(self._parse().notes, ())

    def test_every_change_is_recorded(self) -> None:
        result = self._parse(
            unknowns=[{"id": "U", "question": "What load?",
                       "why_it_matters": "x", "critical": True}],
            extra=[{"id": "REQ_E", "statement": "e.",
                    "threshold": {"magnitude": 2.0, "unit": "mm"},
                    "comparison": "equals", "measurement": "entity:fillet"}],
        )
        self.assertGreaterEqual(len(result.notes), 2)
        self.assertIn("notes", result.as_dict())


class RequirementsThatOnlyEverMeasureTheDocument(unittest.TestCase):
    """Seven requirements, all `parameter:<id>`, all passing, part wrong.

    `parameter:<id>` reads the design's own parameter table. It is the right
    binding for a stated dimension -- it exists because binding a plate's
    thickness to `bounding_box_z` fails a correct part -- but a set made
    entirely of them checks the paperwork and never the object.

    Observed live: a spacer whose plate was built in the wrong plane, whose
    holes had all been filled back in by a boolean, and whose envelope was
    38 x 20 x 38 instead of 30 x 30 x 14. Every requirement passed, because the
    document really did declare `plate_width = 30` -- and a plate standing on
    its edge declares it just as truthfully as a plate lying flat.
    """

    def _problems(self, bindings):
        from forge_roles.library import _nothing_measures_the_part

        return _nothing_measures_the_part([
            {"id": f"R{i}", "measurement": b} for i, b in enumerate(bindings)
        ])

    def test_a_set_that_only_reads_parameters_is_refused(self) -> None:
        problems = self._problems([
            "parameter:plate_width", "parameter:plate_thickness",
            "parameter:post_height",
        ])
        self.assertEqual(len(problems), 1)
        self.assertIn("Nothing measures the part", problems[0])
        self.assertIn("`mass`", problems[0])

    def test_one_geometric_binding_is_enough(self) -> None:
        self.assertEqual(self._problems([
            "parameter:plate_width", "parameter:post_height", "mass",
        ]), [])

    def test_a_count_counts_as_measuring_the_part(self) -> None:
        self.assertEqual(self._problems([
            "parameter:plate_width", "feature_count:hole:mounting",
        ]), [])

    def test_an_envelope_binding_counts(self) -> None:
        self.assertEqual(
            self._problems(["parameter:plate_width", "bounding_box_z"]), []
        )

    def test_a_set_with_no_bindings_at_all_is_left_to_other_checks(self) -> None:
        """Qualitative requirements are a different problem with its own message."""
        self.assertEqual(self._problems(["", ""]), [])

    def test_the_live_answer_is_refused(self) -> None:
        """The exact seven bindings from the run that reported PASS."""
        self.assertTrue(self._problems([
            "parameter:plate_width", "parameter:plate_thickness",
            "parameter:post_diameter", "parameter:post_height",
            "parameter:hole_diameter", "parameter:mounting_hole_diameter",
            "parameter:mounting_hole_spacing",
        ]))


class TheGuideTeachesBothHalvesOfTheInputRule(unittest.TestCase):
    """The rule about `inputs` said which KIND, never whether to write one.

    Earned on a shaft collar returned twice, identically: a `cylinder` and
    three `hole` features, not one of which named the solid it cut. Reading
    the guide back afterwards, it says a primitive takes no `inputs` three
    separate times -- rule 6's old text, and both points 2 and 3 of the
    worked example -- and never once said that everything else must name
    one. A model that over-generalises "features do not list inputs" was
    being taught to.

    The example is a plate, a post, a union and a hole. A collar is a
    cylinder and three holes: no boolean, nothing to pattern-match, and the
    only stated rule about `inputs` was the half that says leave them out.
    """

    @staticmethod
    def _flowed() -> str:
        """The guide as one line, with runs of whitespace collapsed.

        `.replace("\\n", " ")` alone leaves the indentation of a wrapped line
        behind, so a phrase that happens to break across lines is unfindable
        and the test fails for a reason that has nothing to do with the
        prompt. This asserts about the words, not about where they wrap.
        """
        return re.sub(r"\s+", " ", authoring_guide(include_catalogue=False))

    def test_it_says_a_feature_must_name_what_it_acts_on(self) -> None:
        guide = self._flowed()
        self.assertIn("must name it", guide)
        self.assertIn('There is no "current body"', guide)

    def test_it_shows_the_chain_a_run_of_cutters_makes(self) -> None:
        """The case the worked example does not contain."""
        self.assertIn(
            "three holes in a row are a chain", self._flowed().lower())

    def test_it_still_says_primitives_take_none(self) -> None:
        self.assertIn("Only primitives", self._flowed())

    def test_it_still_says_the_kinds_must_match(self) -> None:
        self.assertIn("an `extrude` takes a `profile`", self._flowed())

    def test_the_guide_still_fits_its_budget(self) -> None:
        self.assertLess(len(authoring_guide()) // 4, 9000)


class TheBriefDecidesWhichWholePartSlotsExist(unittest.TestCase):
    """A slot the brief supplies no number for is not offered at all.

    The last act of a three-run story. A requirement set made only of
    `parameter:<id>` bindings is refused, rightly -- that check exists because
    a run once reported PASS on a spacer built in the wrong plane with no
    holes in it. The refusal told the model to measure the part and listed
    `mass` among the options. Asked for a shaft collar, whose brief holds four
    lengths, an angle, and not one word about weight, it answered `mass equals
    100 g`. Twice, identically. The part weighs fifteen grams.

    Dropping the fabrication afterwards is necessary and not sufficient: it
    leaves the set with nothing measuring the part, and the run dies at the
    very check the invention was answering. Under grammar-constrained
    decoding there is a better place to put this. `whole_part` is an object
    of named slots with `additionalProperties: False`, so a slot that is not
    there cannot be written, on any attempt, at any temperature.
    """

    COLLAR = (
        "A machined aluminium shaft collar. The outer diameter is 25 mm and "
        "it is 15 mm long. A 12 mm bore runs all the way through on the axis. "
        "Two 4 mm set screw holes pass through the wall, 90 degrees apart. It "
        "carries no load - it is a locating collar, so there is no load case."
    )
    SPACER = (
        "A 3D-printed PLA spacer block, a 30 mm square plate 4 mm thick. It "
        "must weigh no more than 8 g."
    )

    def _slots(self, brief):
        from forge_roles.library import RequirementsEngineer

        schema = RequirementsEngineer().output_schema(brief=brief)
        return schema["properties"]["requirements"]["properties"]["whole_part"][
            "properties"]

    def test_a_brief_with_no_weight_cannot_state_a_mass(self) -> None:
        self.assertNotIn("mass", self._slots(self.COLLAR))

    def test_a_brief_with_a_weight_keeps_its_mass_slot(self) -> None:
        self.assertIn("mass", self._slots(self.SPACER))

    def test_the_overall_size_slots_stay_open(self) -> None:
        """Where "25 mm across, 15 mm long" belongs."""
        slots = self._slots(self.COLLAR)
        for name in ("bounding_box_x", "bounding_box_y", "bounding_box_z"):
            self.assertIn(name, slots)

    def test_a_manufacturing_limit_stays_available(self) -> None:
        """A minimum wall is a length, and every brief here states lengths."""
        self.assertIn("minimum_wall_thickness", self._slots(self.COLLAR))

    def test_volume_and_area_close_on_a_brief_of_lengths(self) -> None:
        """A second prize: inventing them by multiplying stated dimensions is
        a real failure with a check of its own, and now an unwritable one."""
        slots = self._slots(self.COLLAR)
        self.assertNotIn("volume", slots)
        self.assertNotIn("surface_area", slots)

    def test_a_brief_with_no_numbers_narrows_nothing(self) -> None:
        """No quantities is no evidence, and an empty object is a trap.

        Only the bend's slots close, and not for want of numbers: they are
        offered to a brief that bends its part, and a bracket is not bent."""
        from forge_ir.measurements import SIMPLE_MEASUREMENTS
        from forge_roles.library import _BEND_MEASUREMENTS

        self.assertEqual(
            sorted(self._slots("A bracket, please.")),
            sorted(m for m in SIMPLE_MEASUREMENTS
                   if m not in _BEND_MEASUREMENTS),
        )

    def test_the_slots_are_still_closed_to_anything_else(self) -> None:
        from forge_roles.library import RequirementsEngineer

        schema = RequirementsEngineer().output_schema(brief=self.COLLAR)
        whole = schema["properties"]["requirements"]["properties"]["whole_part"]
        self.assertFalse(whole["additionalProperties"])

    def test_every_measurement_is_described_by_the_table(self) -> None:
        """A measurement added later must not default to 'always offered'."""
        from forge_ir.measurements import SIMPLE_MEASUREMENTS
        from forge_roles.library import (
            _WHAT_A_WHOLE_PART_CLAIM_IS_MEASURED_IN as TABLE,
        )

        self.assertEqual(sorted(TABLE), sorted(SIMPLE_MEASUREMENTS))

    def test_the_rejection_names_what_this_brief_offers(self) -> None:
        from forge_roles.library import _nothing_measures_the_part

        problem = _nothing_measures_the_part(
            [{"measurement": "parameter:outer_diameter"}], self.COLLAR)[0]
        self.assertIn("bounding_box_x", problem)
        self.assertNotIn("`mass`", problem)
        self.assertIn("do not introduce one it does not", problem)

    def test_the_rejection_still_works_with_no_brief(self) -> None:
        from forge_roles.library import _nothing_measures_the_part

        problem = _nothing_measures_the_part(
            [{"measurement": "parameter:outer_diameter"}])[0]
        self.assertIn("bounding_box_x", problem)


class TheRequirementsEngineerIsToldWhichWayIsUp(unittest.TestCase):
    """The role that writes bounding-box claims never heard the convention.

    The designer gets a section of the authoring guide headed "Which way is
    up". The requirements engineer, which is what actually decides a
    `bounding_box_x` claim, got one line: "Overall size along X of the
    finished part."

    On a collar stating 25 mm across, 15 mm long and a 12 mm bore, it
    answered x=25, y=15, z=12 -- the brief's three numbers poured into the
    three slots in the order written. Only the first is right: a 25 mm collar
    is 25 mm in BOTH x and y, the 15 mm is its length along z, and the bore
    is a hole rather than an extent of anything. Two gates would have failed
    on the built part, which is the system working and the run dying anyway.
    """

    def _slot(self, name):
        from forge_roles.library import _what_this_measures

        return _what_this_measures(name)

    def test_z_is_named_as_up(self) -> None:
        self.assertIn("Z IS UP", self._slot("bounding_box_z"))

    def test_a_bore_is_not_an_extent(self) -> None:
        self.assertIn("never an internal bore", self._slot("bounding_box_z"))

    def test_a_round_part_carries_its_diameter_in_both_x_and_y(self) -> None:
        self.assertIn("BOTH X", self._slot("bounding_box_x"))
        self.assertIn("the same number as X", self._slot("bounding_box_y"))

    def test_the_block_warns_against_filling_them_in_order(self) -> None:
        from forge_roles.library import _what_the_requirements_look_like

        blurb = _what_the_requirements_look_like("A 30 mm plate 4 mm thick.")[
            "properties"]["whole_part"]["description"]
        self.assertIn("not three slots to pour", blurb)
        self.assertIn("better left empty", blurb)

    def test_every_slot_still_has_a_description(self) -> None:
        from forge_ir.measurements import SIMPLE_MEASUREMENTS

        for name in SIMPLE_MEASUREMENTS:
            self.assertNotEqual(self._slot(name), name, name)


class GuidanceMustLiveWhereTheModelCanReadIt(unittest.TestCase):
    """On the grammar path the schema never enters the prompt.

    `forge_models.ollama_native` says it in its own module docstring: on
    `/api/chat` the `format` field is compiled into a grammar, and "three
    schemas of 11,215, 4,003 and 68 tokens all reported the same 7,177 prompt
    tokens, because only the system message and the brief are text."

    The consequence went unnoticed until a run proved it. A `description` in
    the output schema is invisible to the model: it constrains nothing and it
    teaches nothing. Guidance written there is decorative.

    Proved by accident and then on purpose. Axis guidance was added to the
    whole-part slot descriptions; the next run reported byte-identical token
    counts -- 3343 in / 238 out, then 3855 in / 454 out, the same as the run
    before it -- and produced the byte-identical wrong answer. The model had
    not seen a word of it.

    So anything that must be READ goes in the system prompt. The schema is
    for what must be IMPOSSIBLE.
    """

    def _prompt(self):
        from forge_roles.library import RequirementsEngineer

        return RequirementsEngineer().system_prompt()

    def test_the_axis_convention_is_in_the_prompt(self) -> None:
        self.assertIn("Z IS UP", self._prompt())

    def test_a_round_part_rule_is_in_the_prompt(self) -> None:
        prompt = self._prompt()
        self.assertIn("round", prompt.lower())
        self.assertIn("BOTH `bounding_box_x` AND `bounding_box_y`", prompt)

    def test_a_bore_is_excluded_in_the_prompt(self) -> None:
        self.assertIn("never a bounding box", self._prompt())

    def test_it_warns_against_filling_the_slots_in_order(self) -> None:
        self.assertIn(
            "not three slots to pour the brief's first three\n  numbers into",
            self._prompt().replace("**", ""),
        )

    def test_the_designer_gets_its_convention_in_text_too(self) -> None:
        """The authoring guide is rendered into the prompt, so the feature
        catalogue's descriptions do reach the designer. Asserted so the two
        roles cannot silently drift apart on where guidance lives."""
        from forge_ir import authoring_guide

        guide = authoring_guide()
        self.assertIn("Z is up", guide)
        self.assertIn("INSIDE the material", guide)


class UnitsPeopleSpellOut(unittest.TestCase):
    """"90 degrees" must be a number Forge can see.

    The brief said "90 degrees apart". The symbol pattern matched `deg` and
    then required a non-word character, which "degrees" fails on its fourth
    letter -- so the angle was never a quantity, never entered the contract,
    and the coverage check had nothing to miss. The collar came back with its
    two set screws 180 degrees apart and not one line of the report mentioned
    that the constraint had gone unchecked.

    The same silence swallowed "30 millimetres", "200 newtons" and every
    other unit written out in full, on every brief, since the beginning.
    """

    def _seen(self, brief):
        from forge_roles.library import _numbers_the_brief_states

        return [str(q) for q in _numbers_the_brief_states(brief)]

    def test_the_angle_that_went_missing(self) -> None:
        self.assertIn("90 deg", self._seen(
            "Two 4 mm set screw holes, 90 degrees apart."))

    def test_the_singular_too(self) -> None:
        self.assertIn("1 deg", self._seen("A draft of 1 degree."))

    def test_both_spellings_of_every_word(self) -> None:
        seen = self._seen(
            "A plate 30 millimetres square and 4 millimeters thick, under "
            "8 grams, carrying 200 newtons.")
        for quantity in ("30 mm", "4 mm", "8 g", "200 N"):
            self.assertIn(quantity, seen)

    def test_case_does_not_matter_for_words(self) -> None:
        self.assertIn("45 deg", self._seen("Chamfered at 45 Degrees."))

    def test_the_trap_the_old_comment_warns_about(self) -> None:
        """"6 in the middle" is not six inches -- the bare symbol stays out."""
        self.assertEqual(
            self._seen("A bracket with 6 in the middle and 4 mm holes."),
            ["4 mm"])

    def test_inches_spelled_out_are_unambiguous(self) -> None:
        """The reason `in` is excluded is ambiguity, and the word has none."""
        self.assertIn("2 in", self._seen("A 2 inch shaft."))

    def test_symbols_are_unchanged(self) -> None:
        self.assertEqual(
            self._seen("A 30 mm plate 4 mm thick, under 8 g, at 45 deg."),
            ["30 mm", "4 mm", "8 g", "45 deg"])

    def test_a_word_inside_a_longer_word_is_not_a_unit(self) -> None:
        self.assertEqual(self._seen("Part 3 degreesomething"), [])

    def test_the_collar_brief_now_carries_its_angle(self) -> None:
        self.assertEqual(
            self._seen(
                "A machined aluminium shaft collar. The outer diameter is "
                "25 mm and it is 15 mm long. A 12 mm bore runs all the way "
                "through. Two 4 mm set screw holes pass through the wall, "
                "90 degrees apart."),
            ["25 mm", "15 mm", "12 mm", "4 mm", "90 deg"])

    def test_an_uncarried_angle_is_reported_as_a_gap(self) -> None:
        """The point of seeing the number: the report can now say nothing
        checked it."""
        from forge_roles.library import _covers, _numbers_the_brief_states

        stated = _numbers_the_brief_states(
            "A collar 25 mm across, 15 mm long, set screws 90 degrees apart.")
        from forge_units import Q

        declared = [Q(25.0, "mm"), Q(15.0, "mm")]
        missing = [q for q in stated if not _covers(q, declared)]
        self.assertEqual([str(q) for q in missing], ["90 deg"])


class AnAngleIsNotAPosition(unittest.TestCase):
    """The idiom has to live where the model reads it.

    Schema `description` fields never enter the prompt on the grammar path --
    three schemas of 11,215, 4,003 and 68 tokens all reported the same 7,177
    prompt tokens. Guidance that must be READ goes in the system prompt and
    in the generated catalogue; the schema is for what must be impossible.
    """

    def test_the_authoring_guide_teaches_the_circular_pattern(self) -> None:
        from forge_ir.spec import AUTHORING_RULES

        self.assertIn("An angle is not a position", AUTHORING_RULES)
        self.assertIn("pattern_circular", AUTHORING_RULES)
        self.assertIn("step_angle", AUTHORING_RULES)

    def test_the_guide_warns_about_degrees_in_a_vector(self) -> None:
        from forge_ir.spec import AUTHORING_RULES

        self.assertIn("millimetre", " ".join(AUTHORING_RULES.split()))
        self.assertIn(
            "value in `deg` written into a millimetre vector",
            " ".join(AUTHORING_RULES.split()))

    def test_the_guide_teaches_the_two_hole_case(self) -> None:
        """The collar's set screws need no pattern at all: two holes on the
        centre line whose axes are the stated angle apart."""
        from forge_ir.spec import AUTHORING_RULES

        rules = " ".join(AUTHORING_RULES.split())
        self.assertIn('"axis": [1, 0, 0]', rules)
        self.assertIn('"axis": [0, 1, 0]', rules)
        self.assertIn("angle between those two axes", rules)
        self.assertIn('"cos(screw_angle)", "sin(screw_angle)", 0', rules)

    def test_the_catalogue_carries_the_worked_case(self) -> None:
        from forge_ir.spec import feature_catalogue

        rendered = feature_catalogue(["pattern_circular"])
        self.assertIn("step_angle", rendered)
        self.assertIn("90 deg", rendered)
        self.assertIn("subtract", rendered)

    def test_the_guide_compiles_the_pattern_it_describes(self) -> None:
        """The guide may not teach something the compiler refuses."""
        import json

        from forge_ir import SCHEMA_VERSION, Document
        from forge_kernel import Compiler

        payload = {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-0000000000a1",
            "project_id": "00000000-0000-4000-8000-0000000000af",
            "name": "Collar", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [{
                "id": "collar", "name": "Collar", "material": "steel_1018_cd",
                "parameters": [
                    {"id": "screw_angle",
                     "value": {"magnitude": 90.0, "unit": "deg"}},
                ],
                "features": [
                    {"id": "body", "kind": "cylinder", "parameters": {
                        "diameter": {"magnitude": 25.0, "unit": "mm"},
                        "height": {"magnitude": 15.0, "unit": "mm"}}},
                    {"id": "screw", "kind": "cylinder", "parameters": {
                        "diameter": {"magnitude": 4.0, "unit": "mm"},
                        "height": {"magnitude": 30.0, "unit": "mm"},
                        "axis": [1, 0, 0],
                        "origin": {"vector": [0, 0, 7.5], "unit": "mm"}}},
                    {"id": "screws", "kind": "pattern_circular",
                     "inputs": ["screw"], "parameters": {
                         "count": {"magnitude": 2, "unit": ""},
                         "step_angle": {"expression": "screw_angle"},
                         "axis_origin": {"vector": [0, 0, 0], "unit": "mm"},
                         "axis_direction": [0, 0, 1]}},
                    {"id": "drilled", "kind": "subtract",
                     "inputs": ["body", "screws"], "parameters": {}},
                ]}],
        }
        document = Document.from_json(json.dumps(payload))
        built = Compiler().compile_component(document.components[0])
        self.assertIsNotNone(built.solid)


class ARelationshipTheBriefStatesInOneWord(unittest.TestCase):
    """"Square" and "round" carry as much geometry as any figure."""

    def test_the_requirements_prompt_says_two_claims_not_one(self) -> None:
        from forge_roles.library import RequirementsEngineer

        prompt = RequirementsEngineer().system_prompt()
        self.assertIn("TWO extents", prompt)
        self.assertIn("two claims of 30, not one", prompt)


class OneParameterUsedTwice(unittest.TestCase):
    """A square part is one dimension, not two.

    The only worked plate the designer had ever seen was the 60 by 40
    bracket, whose `size` is three separate parameters -- and rightly so, for
    a rectangle. Asked for a 30 mm square plate it copied that shape, had to
    pick a number for the second side, and picked one: first 10, releasing a
    plate 30 by 12; then 4, with the third name left undeclared and the run
    dead. Neither was carelessness. Nothing it had been shown ever used one
    parameter in two slots.
    """

    def test_the_guide_shows_the_parametric_square(self) -> None:
        from forge_ir.spec import AUTHORING_RULES

        rules = " ".join(AUTHORING_RULES.split())
        self.assertIn('"plate_size", "plate_size", "plate_thickness"', rules)
        self.assertIn("ONE parameter twice", rules)

    def test_the_guide_says_why_two_parameters_fail(self) -> None:
        from forge_ir.spec import AUTHORING_RULES

        rules = " ".join(AUTHORING_RULES.split())
        self.assertIn("30 by 12", rules)
        self.assertIn("round part is the same rule", rules)

    def test_the_bracket_example_is_still_a_rectangle(self) -> None:
        """It is not wrong and is not changed: 60 by 40 needs two names. The
        guide now says so, so its shape is copied and its count is not."""
        from forge_ir.spec import COMPOSITION_EXAMPLE

        base = next(f for f in COMPOSITION_EXAMPLE if f["id"] == "base")
        self.assertEqual(
            list(base["parameters"]["size"]["vector"])[:2],
            ["plate_width", "plate_depth"])

    def test_a_square_plate_written_that_way_compiles(self) -> None:
        """The guide may not teach something the compiler refuses."""
        import json

        from forge_ir import SCHEMA_VERSION, Document
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps({
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-0000000000f1",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "name": "Plate", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [{
                "id": "plate", "name": "Plate", "material": "pla_fdm",
                "parameters": [
                    {"id": "plate_size",
                     "value": {"magnitude": 30.0, "unit": "mm"}},
                    {"id": "plate_thickness",
                     "value": {"magnitude": 4.0, "unit": "mm"}}],
                "features": [{"id": "base", "kind": "box", "parameters": {
                    "size": {"vector": ["plate_size", "plate_size",
                                        "plate_thickness"], "unit": "mm"},
                    "centered": True}}]}]}))
        built = Compiler().compile_component(document.components[0])
        envelope = built.solid.envelope
        self.assertAlmostEqual(envelope.hi[0] - envelope.lo[0], 30.0, places=6)
        self.assertAlmostEqual(envelope.hi[1] - envelope.lo[1], 30.0, places=6)
        self.assertAlmostEqual(envelope.hi[2] - envelope.lo[2], 4.0, places=6)


class EveryWayOfSayingNoLoad(unittest.TestCase):
    """"It carries no load" was the one wording read; "it does not carry any
    load", "no load", "it bears no load" each left the margin standing and
    the run asking -- or blocked -- for a load the user had ruled out."""

    def test_wordings(self) -> None:
        from forge_roles.library import _says_there_is_no_load

        for brief in ("It carries no load.", "It does not carry any load.",
                      "It doesn't carry any load.", "No load.",
                      "There is no load on it.", "It bears no load.",
                      "The part is unloaded.", "It is purely decorative.",
                      "It won't carry any weight.",
                      "It has no forces on it."):
            with self.subTest(brief=brief):
                self.assertTrue(_says_there_is_no_load(brief))
        for brief in ("It carries a 150 N load.",
                      "A load of 20 N pushes on its end.",
                      "It must not carry more than 5 kg.",
                      "A shelf bracket that holds up to 5 kilos.",
                      "Make it strong enough."):
            with self.subTest(brief=brief):
                self.assertFalse(_says_there_is_no_load(brief))



class TheLoadTheBriefStatesIsPickedUp(unittest.TestCase):
    """A load stated as a force or as a mass held up is carried as the load;
    one not stated at all is none, and the margin goes with it."""

    ANSWER = {"risk_class": "low", "requirements": [
        {"id": "REQ_L", "statement": "60 mm long",
         "measurement": "parameter:length", "comparison": "equals",
         "threshold": {"magnitude": 60, "unit": "mm"}},
        {"id": "REQ_SF", "statement": "a margin of 2",
         "measurement": "safety_factor:bending", "comparison": "at_least",
         "threshold": {"magnitude": 2, "unit": ""}}],
        "assumptions": [], "unknowns": []}

    def _record(self, brief):
        from forge_roles import RequirementsEngineer

        return RequirementsEngineer().parse(self.ANSWER, brief=brief)

    def test_silence_is_no_load(self) -> None:
        record = self._record("A shelf bracket 60 mm long.")
        self.assertNotIn("REQ_SF", [r["id"] for r in record.requirements])
        self.assertEqual(record.unknowns, ())

    def test_a_force_is_the_load(self) -> None:
        record = self._record("A shelf bracket 60 mm long. It carries 150 N.")
        loads = {a["id"]: a.get("value") for a in record.assumptions}
        self.assertEqual(loads["ASM_DESIGN_LOAD"],
                         {"magnitude": 150.0, "unit": "N"})

    def test_a_mass_it_holds_is_its_weight(self) -> None:
        record = self._record(
            "A shelf bracket 60 mm long that holds up to 5 kg.")
        loads = {a["id"]: a.get("value") for a in record.assumptions}
        self.assertAlmostEqual(loads["ASM_DESIGN_LOAD"]["magnitude"], 49.033,
                               places=2)
        self.assertIn("REQ_SF", [r["id"] for r in record.requirements])

    def test_its_own_weight_is_not_a_load(self) -> None:
        from forge_roles.library import _the_masses_the_brief_loads_it_with

        self.assertEqual(_the_masses_the_brief_loads_it_with(
            "A spacer that weighs no more than 8 g."), [])
        self.assertEqual(_the_masses_the_brief_loads_it_with(
            "A tray that holds 20 screws."), [])
