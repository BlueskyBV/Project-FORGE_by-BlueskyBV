"""End-to-end tests of the AI design loop, against scripted model responses.

Every test here runs the *real* orchestrator, the real roles with their real
generated prompts, the real compiler and the real verifier. Only the model is
scripted -- and the scripted answers in ``fixtures/bracket_responses`` are
complete, plausible answers written as the model would write them, including a
bracket that genuinely compiles.

The tests that matter most are the ones where something goes wrong: an
underspecified brief that must not be answered with invented numbers, a
malformed document that must be repaired surgically, an analyst that gives up,
and a repair loop that starts repeating itself and has to stop.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from fixtures.bracket_responses import (
    ANALYST_BAD_POINTER,
    ANALYST_FIX_BOUNDS,
    ANALYST_GIVES_UP,
    ANALYST_REPEATS,
    BRIEF,
    BRIEF_UNDERSPECIFIED,
    DESIGNER_BROKEN,
    DESIGNER_MALFORMED,
    DESIGNER_VALID,
    INTERPRETER,
    QUESTIONS,
    REQUIREMENTS,
    REQUIREMENTS_UNDERSPECIFIED,
)
from forge_evidence import Status
from forge_kernel import CompileError
from forge_models import Budget, BudgetExceededError, ScriptedProvider
from forge_orchestrator import Orchestrator, OrchestratorConfig, State
from forge_orchestrator.orchestrator import _pointers_from
from forge_roles import (
    BriefInterpreter,
    FailureAnalyst,
    ForgeIRDesigner,
    RepairExhaustedError,
    RequirementsEngineer,
    RoleOutputError,
)
from forge_roles.library import RequirementSet

FAST = OrchestratorConfig(measurement_depth=6, mesh_resolution=48)


def _run(responses: list[Any], brief: str = BRIEF, **kwargs: Any):
    provider = ScriptedProvider(responses)
    config = kwargs.pop("config", FAST)
    orchestrator = Orchestrator(provider, config=config)
    return orchestrator.design(brief, **kwargs), provider


class HappyPath(unittest.TestCase):
    """A well-specified brief goes all the way through."""

    def setUp(self) -> None:
        self.run, self.provider = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_VALID]
        )

    def test_the_loop_reaches_a_verdict(self) -> None:
        self.assertIn(
            self.run.state,
            (State.COMPLETED, State.BLOCKED),
            f"unexpected terminal state; failure was {self.run.failure}",
        )
        self.assertIsNotNone(self.run.report)

    def test_unapproved_high_risk_assumption_blocks_release(self) -> None:
        """The design is sound and still not releasable, which is correct.

        The 300 N load is an assumption the user has not accepted. Every gate
        can pass and the verdict is still BLOCKED, naming it.
        """
        self.assertIs(self.run.state, State.BLOCKED)
        reasons = " ".join(self.run.report.release_reasons)
        self.assertIn("ASM_DESIGN_LOAD", reasons)

    def test_no_repairs_were_needed(self) -> None:
        self.assertEqual(self.run.repairs, [])

    def test_every_role_was_called_once(self) -> None:
        purposes = [request.purpose for request in self.provider.requests]
        self.assertEqual(
            purposes,
            ["brief_interpreter", "requirements_engineer", "forgeir_designer"],
        )

    def test_the_clarifier_was_skipped(self) -> None:
        """No critical unknowns, so no questions. Asking anyway wastes attention."""
        self.assertEqual(self.run.questions, ())

    def test_geometry_was_actually_measured(self) -> None:
        measurements = self.run.report.measurements
        self.assertIn("volume", measurements)
        self.assertIn("mass", measurements)
        self.assertIn("±", measurements["volume"])

    def test_interfaces_resolve_on_the_generated_design(self) -> None:
        interface_gates = [
            result
            for result in self.run.report.gate_results
            if result.gate.identifier.startswith("IFACE_")
        ]
        self.assertEqual(len(interface_gates), 2)
        for gate in interface_gates:
            self.assertIs(gate.status, Status.PASS, gate.gate.claim)

    def test_the_run_serialises_completely(self) -> None:
        payload = self.run.as_dict()
        for key in ("brief", "state", "intent", "requirements", "document",
                    "verification", "events", "usage"):
            self.assertIn(key, payload)
        json.dumps(payload)  # must be JSON-serialisable end to end

    def test_events_are_sequential_and_append_only(self) -> None:
        sequences = [event.sequence for event in self.run.events]
        self.assertEqual(sequences, list(range(len(sequences))))

    def test_the_designer_s_own_answer_is_kept_with_the_run(self) -> None:
        """What the model wrote, before Forge repaired it: a fault in a run
        is read as it was made, not rebuilt from the repaired document."""
        generated = [e for e in self.run.events
                     if e.summary.startswith("document generated")]
        self.assertEqual(len(generated), 1)
        answer = generated[0].detail.get("answer")
        self.assertIsInstance(answer, dict)
        self.assertIn("components", answer)
        json.dumps(self.run.as_dict())

    def test_usage_is_accounted(self) -> None:
        self.assertGreater(self.run.usage.total_tokens, 0)


class RefusesToInvent(unittest.TestCase):
    """The property the whole system exists to protect."""

    def test_an_underspecified_brief_pauses_and_asks(self) -> None:
        run, provider = _run(
            [INTERPRETER, REQUIREMENTS_UNDERSPECIFIED, QUESTIONS],
            brief=BRIEF_UNDERSPECIFIED,
        )
        self.assertIs(run.state, State.AWAITING_ANSWERS)
        self.assertEqual(len(run.questions), 2)
        # It stopped before designing anything.
        self.assertIsNone(run.document_payload)
        self.assertNotIn(
            "forgeir_designer", [r.purpose for r in provider.requests]
        )

    def test_questions_come_back_ranked(self) -> None:
        run, _ = _run(
            [INTERPRETER, REQUIREMENTS_UNDERSPECIFIED, QUESTIONS],
            brief=BRIEF_UNDERSPECIFIED,
        )
        priorities = [q.priority for q in run.questions]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_proceeding_anyway_records_assumptions_rather_than_values(self) -> None:
        """`stop_on_critical_unknowns=False` must not mean "make something up".

        Each unresolved unknown becomes an unapproved high-risk assumption. The
        design still gets built and measured -- which is useful -- and release is
        blocked, with the unknown named.
        """
        run, _ = _run(
            [INTERPRETER, REQUIREMENTS_UNDERSPECIFIED, DESIGNER_VALID],
            brief=BRIEF_UNDERSPECIFIED,
            config=OrchestratorConfig(
                measurement_depth=6,
                mesh_resolution=48,
                stop_on_critical_unknowns=False,
            ),
        )
        self.assertIsNot(run.state, State.AWAITING_ANSWERS)
        absorbed = [
            assumption
            for assumption in run.requirements.assumptions
            if str(assumption.get("id", "")).startswith("ASM_UNRESOLVED_")
        ]
        self.assertEqual(len(absorbed), 2)
        for assumption in absorbed:
            self.assertEqual(assumption["risk"], "high")
            self.assertFalse(assumption["approved"])
            self.assertIn("none was invented", assumption["statement"])

    def test_a_blank_answer_does_not_count_as_answering(self) -> None:
        """The one path that turned "nobody knows" into "somebody said so".

        Found by an external audit and reproduced: `--answer UNK_LOAD=` used
        to satisfy the outstanding-unknowns check by membership alone. No
        question was asked, no unresolved assumption was recorded, nothing
        blocked release, and the empty string was handed to the designer
        under a heading that calls it a fact confirmed by the user.

        A critical unknown exists precisely so that a number nobody supplied
        cannot become a number the report treats as checked. Blank is not an
        answer.
        """
        run, _ = _run(
            [INTERPRETER, REQUIREMENTS_UNDERSPECIFIED, DESIGNER_VALID],
            brief=BRIEF_UNDERSPECIFIED,
            answers={"UNK_SHAFT_DIAMETER": "", "UNK_LOAD": "   "},
            config=OrchestratorConfig(
                measurement_depth=6,
                mesh_resolution=48,
                stop_on_critical_unknowns=False,
            ),
        )
        absorbed = [
            assumption
            for assumption in run.requirements.assumptions
            if str(assumption.get("id", "")).startswith("ASM_UNRESOLVED_")
        ]
        self.assertEqual(
            len(absorbed), 2,
            "a blank answer erased a critical unknown instead of blocking it",
        )
        for assumption in absorbed:
            self.assertFalse(assumption["approved"])

    def test_a_blank_answer_still_gets_the_question_asked(self) -> None:
        run, _ = _run(
            [INTERPRETER, REQUIREMENTS_UNDERSPECIFIED, QUESTIONS],
            brief=BRIEF_UNDERSPECIFIED,
            answers={"UNK_SHAFT_DIAMETER": "", "UNK_LOAD": ""},
        )
        self.assertIs(run.state, State.AWAITING_ANSWERS)
        self.assertTrue(run.questions)

    def test_supplying_answers_lets_the_run_proceed(self) -> None:
        run, provider = _run(
            [INTERPRETER, REQUIREMENTS_UNDERSPECIFIED, DESIGNER_VALID],
            brief=BRIEF_UNDERSPECIFIED,
            answers={"UNK_SHAFT_DIAMETER": "20 mm", "UNK_LOAD": "300 N downward"},
        )
        self.assertIsNot(run.state, State.AWAITING_ANSWERS)
        self.assertIn("forgeir_designer", [r.purpose for r in provider.requests])


class SurgicalRepair(unittest.TestCase):
    """A malformed document is patched, not regenerated."""

    def test_an_out_of_bounds_value_is_repaired_and_the_run_continues(self) -> None:
        """A compile-time failure: the value violates bounds the model itself set."""
        run, provider = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, ANALYST_FIX_BOUNDS]
        )
        self.assertEqual(len(run.repairs), 1)
        repair = run.repairs[0]
        self.assertEqual(repair.outcome, "applied")
        self.assertEqual(repair.trigger, "compile")
        self.assertIn("bounds", repair.diagnosis)
        self.assertIsNotNone(run.report)

    def test_a_malformed_document_is_repaired_before_it_ever_compiles(self) -> None:
        """A decode-time failure never reaches the compiler.

        `diameter` on a `box` is caught by the decoder, so the designer role
        repairs its own output in place. No orchestrator-level repair is
        recorded, because none was needed -- the error was caught one layer
        earlier and one round trip cheaper.
        """
        run, provider = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_MALFORMED, DESIGNER_VALID]
        )
        self.assertEqual(run.repairs, [])
        designer_calls = [
            request
            for request in provider.requests
            if request.purpose == "forgeir_designer"
        ]
        self.assertEqual(len(designer_calls), 2)
        # The failed answer and the pointer-carrying problems are both in the
        # repair turn.
        repair_turn = designer_calls[1].messages[-1].content
        self.assertIn("/components/0/features/0", repair_turn)
        self.assertIsNotNone(run.report)

    def test_the_repair_changed_only_the_offending_node(self) -> None:
        """The central claim of patch-based repair, checked byte for byte."""
        run, _ = _run([INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, ANALYST_FIX_BOUNDS])
        repaired = run.document_payload
        self.assertIsNotNone(repaired)

        expected = copy.deepcopy(DESIGNER_BROKEN["document"])
        expected["components"][0]["parameters"][2]["value"] = {
            "magnitude": 12.0,
            "unit": "mm",
        }
        self.assertEqual(
            json.dumps(repaired, sort_keys=True),
            json.dumps(expected, sort_keys=True),
            "the repair altered something beyond the node it targeted",
        )

    def test_an_abandoning_analyst_ends_the_run_with_its_reason(self) -> None:
        run, _ = _run([INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, ANALYST_GIVES_UP])
        self.assertIs(run.state, State.FAILED)
        self.assertTrue(run.repairs[-1].abandoned)
        self.assertIn("has to change", run.failure["message"])

    def test_a_repeated_repair_stops_the_loop(self) -> None:
        """Proposing the same edit twice ends it, rather than looping."""
        run, _ = _run(
            [
                INTERPRETER,
                REQUIREMENTS,
                DESIGNER_BROKEN,
                ANALYST_REPEATS,
                ANALYST_REPEATS,
            ]
        )
        outcomes = [repair.outcome for repair in run.repairs]
        self.assertIn("oscillation", outcomes)
        self.assertIs(run.state, State.FAILED)
        self.assertEqual(run.failure["code"], "OR1002_OSCILLATION")

    def test_the_analyst_is_shown_previous_attempts(self) -> None:
        _, provider = _run(
            [
                INTERPRETER,
                REQUIREMENTS,
                DESIGNER_BROKEN,
                ANALYST_REPEATS,
                ANALYST_REPEATS,
            ]
        )
        analyst_calls = [
            request
            for request in provider.requests
            if request.purpose == "failure_analyst"
        ]
        self.assertGreaterEqual(len(analyst_calls), 2)
        self.assertIn(
            "previous_repair_attempts", analyst_calls[-1].messages[0].content
        )

    def test_the_analyst_gets_a_slice_not_the_whole_document(self) -> None:
        _, provider = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, ANALYST_FIX_BOUNDS]
        )
        analyst = next(
            r for r in provider.requests if r.purpose == "failure_analyst"
        )
        content = analyst.messages[0].content
        whole = json.dumps(DESIGNER_BROKEN["document"])
        self.assertLess(
            len(content),
            len(whole) // 4,
            "the analyst was sent a slice barely smaller than the document; "
            "the point of slicing is to send the failing node, not the design",
        )

    def test_the_slice_is_the_parameter_the_diagnostic_named(self) -> None:
        """Size alone would be satisfied by sending the wrong small thing.

        A bounds violation names its parameters, so the slice must be those
        parameters -- with their bounds, which are half of what the analyst has
        to reason about -- and nothing else.
        """
        _, provider = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, ANALYST_FIX_BOUNDS]
        )
        analyst = next(
            r for r in provider.requests if r.purpose == "failure_analyst"
        )
        extract = analyst.messages[0].content.split("<document_extract>")[1].split(
            "</document_extract>"
        )[0]
        sliced = json.loads(extract)
        self.assertEqual(list(sliced), ["/components/0/parameters/2"])
        offending = sliced["/components/0/parameters/2"]
        self.assertEqual(offending["id"], "base_thickness")
        self.assertIn("bounds", offending)
        self.assertNotIn("features", extract)

    def test_a_feature_failure_is_sliced_to_that_feature(self) -> None:
        """The same narrowing, driven by a different diagnostic shape."""
        payload = DESIGNER_BROKEN["document"]
        error = CompileError(
            "feature parameter is below its permitted minimum",
            component="bracket",
            feature="upright",
            parameter="size",
        )
        self.assertEqual(_pointers_from(error, payload), ("/components/0/features/1",))

    def test_an_unrecognised_failure_falls_back_to_the_component(self) -> None:
        """Not to the whole document, and not to a guess at what broke."""
        payload = DESIGNER_BROKEN["document"]
        error = CompileError("something unattributed went wrong")
        self.assertEqual(_pointers_from(error, payload), ("/components/0",))


class RoleValidation(unittest.TestCase):
    """Semantic validation catches what a JSON schema cannot."""

    def test_a_threshold_without_a_unit_is_rejected(self) -> None:
        role = RequirementsEngineer()
        with self.assertRaises(RoleOutputError) as caught:
            role.parse(
                {
                    "risk_class": "low",
                    "requirements": [
                        {
                            "id": "R1",
                            "statement": "Mass under 400.",
                            "type": "performance",
                            "strength": "soft",
                            "verification": "exact_geometry",
                            "threshold": {"magnitude": 400.0, "unit": ""},
                            "comparison": "at_most",
                        }
                    ],
                    "assumptions": [],
                    "unknowns": [],
                }
            )
        self.assertTrue(
            any("unit" in problem for problem in caught.exception.problems)
        )

    def test_a_comparison_without_a_threshold_is_rejected(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            RequirementsEngineer().parse(
                {
                    "risk_class": "low",
                    "requirements": [
                        {
                            "id": "R1",
                            "statement": "Light.",
                            "type": "performance",
                            "strength": "soft",
                            "verification": "exact_geometry",
                            "comparison": "at_most",
                        }
                    ],
                    "assumptions": [],
                    "unknowns": [],
                }
            )
        self.assertTrue(
            any("threshold" in p for p in caught.exception.problems)
        )

    def test_a_high_risk_assumption_without_its_consequence_is_noted(self) -> None:
        # This used to fail the whole role. `consequence_if_wrong` is prose
        # for a human reader and nothing computes on it -- `blocks_release`
        # reads `risk` and `state`, both present here -- so an empty one makes
        # the report thinner rather than wrong, and losing a high-risk
        # assumption is a far worse outcome than carrying it with a caveat.
        result = RequirementsEngineer().parse(
            {
                "risk_class": "high",
                "requirements": REQUIREMENTS["requirements"],
                "assumptions": [
                    {
                        "id": "A1",
                        "statement": "Load is 1 kN.",
                        "risk": "high",
                    }
                ],
                "unknowns": [],
            }
        )
        self.assertEqual(len(result.assumptions), 1)
        self.assertTrue(
            any("consequence_if_wrong" in note for note in result.notes),
            result.notes,
        )

    def test_an_interpretation_that_claims_nothing_is_missing_is_noted(
        self,
    ) -> None:
        # Also a rejection once, and also the wrong call: the interpreter is
        # the first and slowest call in the pipeline, `unstated` is advisory
        # prose that only feeds the clarifier's questions, and nothing
        # downstream requires an entry.
        result = BriefInterpreter().parse(
            {
                "summary": "A bracket.",
                "part_kind": "bracket",
                "stated": ["holds a shaft"],
                "implied": [],
                "unstated": [],
            }
        )
        self.assertEqual(result.summary, "A bracket.")
        self.assertTrue(
            any("unstated" in note for note in result.notes), result.notes
        )

    def test_an_interpretation_with_no_summary_is_still_rejected(self) -> None:
        # The line that separates the two: every later role reads `summary`.
        with self.assertRaises(RoleOutputError):
            BriefInterpreter().parse(
                {
                    "summary": "  ",
                    "part_kind": "bracket",
                    "stated": ["holds a shaft"],
                    "implied": [],
                    "unstated": ["the load"],
                }
            )

    def test_an_invalid_document_produces_pointer_carrying_problems(self) -> None:
        broken = copy.deepcopy(DESIGNER_VALID)
        broken["document"]["components"][0]["features"][0]["kind"] = "wormhole"
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(broken)
        joined = " ".join(caught.exception.problems)
        self.assertIn("/components/0/features/0", joined)
        self.assertIn("wormhole", joined)

    def test_a_patch_with_no_pointer_is_rejected(self) -> None:
        with self.assertRaises(RoleOutputError):
            FailureAnalyst().parse(
                {
                    "diagnosis": "bad",
                    "strategy": "fix",
                    "patches": [{"op": "replace", "value": 1}],
                }
            )

    def test_abandoning_without_a_reason_is_rejected(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            FailureAnalyst().parse(
                {
                    "diagnosis": "",
                    "strategy": "",
                    "abandon": True,
                    "patches": [],
                }
            )
        self.assertTrue(
            any("abandon_reason" in p for p in caught.exception.problems)
        )

    def test_an_abandon_whose_reason_is_its_diagnosis_is_kept(self) -> None:
        """The L-bracket's last look: "the part matches the brief" as the
        diagnosis, `abandon` set, the reason field left empty -- and a
        second call bought to have the sentence copied across."""
        proposal = FailureAnalyst().parse(
            {
                "diagnosis": "The slot cannot be 40 mm long on a 30 mm plate.",
                "strategy": "none",
                "abandon": True,
                "patches": [],
            },
            failure={"kind": "last_look"},
        )
        self.assertTrue(proposal.abandon)
        self.assertIn("30 mm plate", proposal.abandon_reason)

    def test_repair_is_bounded(self) -> None:
        """Identical bad answers stop the loop rather than running it out.

        This used to assert the full three attempts. Two is the better answer
        and the same principle: a model shown what was wrong and returning the
        identical answer has told us everything a third attempt would. On the
        run that motivated the change, that third attempt was 25 minutes.
        """
        bad = {
            # An empty `summary`, not an empty `unstated`: the second is a
            # note now, and only a fatal answer exercises the repair loop.
            "summary": "",
            "part_kind": "bracket",
            "stated": [],
            "implied": [],
            "unstated": ["the load"],
        }
        provider = ScriptedProvider([bad, bad, bad, bad, bad])
        with self.assertRaises(RepairExhaustedError) as caught:
            BriefInterpreter().run(provider, brief="anything")
        self.assertEqual(caught.exception.detail["attempts"], 2)
        self.assertTrue(caught.exception.detail["stopped_early"])
        self.assertEqual(len(provider.requests), 2)

    def test_the_failed_answer_stays_in_the_repair_conversation(self) -> None:
        good = dict(INTERPRETER)
        bad = {
            "summary": "",
            "part_kind": "bracket",
            "stated": [],
            "implied": [],
            "unstated": ["a load"],
        }
        provider = ScriptedProvider([bad, good])
        result = BriefInterpreter().run(provider, brief=BRIEF)
        self.assertEqual(result.attempts, 2)
        second = provider.requests[1]
        roles = [message.role for message in second.messages]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertIn("did not validate", second.messages[2].content)


class BudgetAndFailure(unittest.TestCase):
    def test_a_token_budget_stops_the_run(self) -> None:
        provider = ScriptedProvider(
            [INTERPRETER, REQUIREMENTS, DESIGNER_VALID],
            budget=Budget(max_calls=2, max_total_tokens=None),
        )
        run = Orchestrator(provider, config=FAST).design(BRIEF)
        self.assertIs(run.state, State.FAILED)
        self.assertEqual(run.failure["code"], "MD1007_BUDGET_EXCEEDED")

    def test_a_provider_failure_is_reported_not_raised(self) -> None:
        run, _ = _run([INTERPRETER])  # runs out of scripted responses
        self.assertIs(run.state, State.FAILED)
        self.assertIsNotNone(run.failure)

    def test_the_run_renders_without_a_report(self) -> None:
        run, _ = _run([INTERPRETER])
        rendered = run.render()
        self.assertIn("State", rendered)
        self.assertIn("Failed", rendered)


class Provenance(unittest.TestCase):
    def test_the_provider_is_recorded(self) -> None:
        run, _ = _run([INTERPRETER, REQUIREMENTS, DESIGNER_VALID])
        self.assertEqual(run.provider_info["name"], "scripted")
        self.assertIn("remote", run.provider_info)

    def test_whether_data_left_the_machine_is_recorded(self) -> None:
        """A user is entitled to a definite answer to this question."""
        run, _ = _run([INTERPRETER, REQUIREMENTS, DESIGNER_VALID])
        self.assertIs(run.provider_info["remote"], False)

    def test_prompt_versions_are_pinned(self) -> None:
        for role in (
            BriefInterpreter(),
            RequirementsEngineer(),
            ForgeIRDesigner(),
            FailureAnalyst(),
        ):
            self.assertRegex(role.prompt_version, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ProviderFactsAreRecordedAfterUse(unittest.TestCase):
    """Some facts about a provider are only true once it has been called."""

    def test_the_run_records_what_the_provider_became(self) -> None:
        run, provider = _run([INTERPRETER, REQUIREMENTS, DESIGNER_VALID])
        self.assertEqual(run.provider_info["model"], provider.info.model)
        self.assertIn("schema_fidelity", run.provider_info)

    def test_a_failed_run_still_records_the_provider(self) -> None:
        """The run you most want the record of is the one that failed."""
        run, _ = _run([INTERPRETER])
        self.assertIs(run.state, State.FAILED)
        self.assertTrue(run.provider_info)


class SmallContextRuntimes(unittest.TestCase):
    """Making the loop fit a runtime that has 16k of context, not 200k."""

    def test_the_cap_lowers_what_each_role_reserves(self) -> None:
        orchestrator = Orchestrator(
            ScriptedProvider([]), config=OrchestratorConfig(output_token_cap=6144)
        )
        reserved = {
            name: role.max_output_tokens
            for name, role in orchestrator._roles.items()  # noqa: SLF001
        }
        self.assertLessEqual(max(reserved.values()), 6144)
        self.assertEqual(
            reserved["interpreter"], 4096, "a cap must not raise a lower default"
        )
        # Nor may a cut-off answer's retry ask for more than the cap allows.
        self.assertTrue(all(
            role.output_token_ceiling <= 6144
            for role in orchestrator._roles.values()))  # noqa: SLF001

    def test_capping_one_run_does_not_change_the_next(self) -> None:
        """The cap is set on instances. On the classes it would leak into every
        other run in the process, including ones against a large model."""
        Orchestrator(
            ScriptedProvider([]), config=OrchestratorConfig(output_token_cap=512)
        )
        uncapped = Orchestrator(ScriptedProvider([]))
        self.assertEqual(
            uncapped._roles["designer"].max_output_tokens, 16384  # noqa: SLF001
        )


class AnswersThatEchoTheInput(unittest.TestCase):
    """A model that hands the input back, named for what it actually did.

    Observed live with qwen2.5-coder:3b: told to submit its interpretation, it
    replied `{"name": "brief_interpreter", "arguments": {"brief": "<the
    brief>"}}` -- reading the tool as a worker to delegate to. The field-level
    validator then said "`summary` is empty", which is true and useless, and
    three attempts repeated the same mistake.
    """

    def test_an_echo_is_named_rather_than_reported_field_by_field(self) -> None:
        role = BriefInterpreter()
        with self.assertRaises(RoleOutputError) as caught:
            role._reject_an_echo(  # noqa: SLF001
                {"brief": "A bracket..."}, role.output_schema()
            )
        problem = caught.exception.problems[0]
        self.assertIn("brief", problem)
        self.assertIn("summary", problem, "the real fields must be listed")
        self.assertIn("not a function that processes the input", problem)

    def test_a_real_answer_is_not_mistaken_for_an_echo(self) -> None:
        role = BriefInterpreter()
        role._reject_an_echo(  # noqa: SLF001
            {"summary": "a bracket", "unstated": ["the load"]}, role.output_schema()
        )

    def test_a_partial_answer_is_left_to_the_field_validator(self) -> None:
        """One recognised field means the model understood the task and got
        something wrong -- a different problem, with a different remedy."""
        role = BriefInterpreter()
        role._reject_an_echo({"summary": ""}, role.output_schema())  # noqa: SLF001

    def test_the_tool_is_named_for_submitting_an_answer(self) -> None:
        from forge_models import AnthropicProvider

        provider = AnthropicProvider(api_key="x")
        request = BriefInterpreter()
        payload = provider._build_payload(  # noqa: SLF001
            __import__("forge_models").ModelRequest(
                system="s",
                messages=(__import__("forge_models").user("x"),),
                schema=request.output_schema(),
                schema_name=request.name,
                schema_description=request.schema_description(),
            )
        )
        self.assertEqual(payload["tools"][0]["name"], "submit_brief_interpreter")
        self.assertIn("ARE your answer", payload["tools"][0]["description"])


class ADocumentReturnedBare(unittest.TestCase):
    """The designer's wrapper exists to carry a rationale, not to gate the work.

    A local model returned the ForgeIR document at the top level instead of
    nested under `document`. Nineteen minutes of generation were discarded over
    the packaging, and the message said only "`document` is missing".
    """

    DOCUMENT = {
        "schema_version": "1.0.0",
        "document_id": "00000000-0000-4000-8000-000000000123",
        "project_id": "00000000-0000-4000-8000-000000000456",
        "revision": 1,
        "name": "Spacer",
        "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
        "requirements": [],
        "assumptions": [],
        "components": [
            {
                "id": "spacer",
                "name": "Spacer",
                "parameters": [
                    {"id": "height", "value": {"magnitude": 10.0, "unit": "mm"}}
                ],
                "features": [
                    {
                        "id": "body",
                        "kind": "cylinder",
                        "parameters": {
                            "diameter": {"magnitude": 20.0, "unit": "mm"},
                            "height": {"expression": "height", "unit": "mm"},
                        },
                    }
                ],
            }
        ],
    }

    def test_a_bare_document_is_accepted(self) -> None:
        draft = ForgeIRDesigner().parse(self.DOCUMENT)
        self.assertEqual(draft.document.name, "Spacer")
        self.assertEqual(draft.payload["schema_version"], "1.0.0")

    def test_the_wrapper_is_still_preferred_when_present(self) -> None:
        draft = ForgeIRDesigner().parse(
            {"rationale": "a spacer", "document": self.DOCUMENT}
        )
        self.assertEqual(draft.rationale, "a spacer")

    def test_something_that_is_neither_is_refused_with_the_shape(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse({"thoughts": "I had some ideas"})
        self.assertIn('"document"', caught.exception.problems[0])

    def test_a_bare_document_still_faces_the_full_decoder(self) -> None:
        """Unwrapped, not waived: the document is validated either way."""
        broken = dict(self.DOCUMENT)
        broken["components"] = [dict(self.DOCUMENT["components"][0])]
        broken["components"][0]["features"] = [
            {"id": "body", "kind": "cylinder", "parameters": {"diameter": 20.0}}
        ]
        with self.assertRaises(RoleOutputError):
            ForgeIRDesigner().parse(broken)


class TheGuidesExampleIsNotAnAnswer(unittest.TestCase):
    """The failure that passes every gate and is still wrong.

    Asked for a bracket, qwen2.5-coder returned the spacer from the authoring
    guide verbatim -- placeholder ids and all. It validates, it compiles, it
    passes the example's own requirements, and it is not the part in the brief.
    Nothing downstream can catch this: every check the compiler runs, the
    example was written to pass.
    """

    def _example(self) -> dict:
        from forge_ir.spec import EXAMPLE_DOCUMENT

        return json.loads(json.dumps(EXAMPLE_DOCUMENT))

    def test_the_example_returned_verbatim_is_refused(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse({"rationale": "a spacer", "document": self._example()})
        self.assertIn("worked example", str(caught.exception))

    def test_the_refusal_says_what_to_do_instead(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(self._example())
        problem = caught.exception.problems[0]
        self.assertIn("Design the part the", problem)
        self.assertIn("document_id", problem)

    def test_the_example_geometry_under_a_new_name_is_still_the_example(self) -> None:
        """Renaming the document does not make the spacer a bracket."""
        payload = self._example()
        payload["name"] = "Shelf bracket"
        payload["document_id"] = "00000000-0000-4000-8000-0000000000ff"
        with self.assertRaises(RoleOutputError):
            ForgeIRDesigner().parse(payload)

    def test_the_placeholder_identity_alone_is_enough(self) -> None:
        """Real geometry carrying the example's id means it was edited, not written."""
        payload = self._example()
        payload["components"] = ADocumentReturnedBare.DOCUMENT["components"]
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(payload)
        self.assertIn("`document_id`", caught.exception.problems[0])

    def test_a_real_design_is_untouched(self) -> None:
        draft = ForgeIRDesigner().parse(ADocumentReturnedBare.DOCUMENT)
        self.assertEqual(draft.document.name, "Spacer")


class TheDesignerIsNotHandedAFieldItCannotUse(unittest.TestCase):
    """`unknowns` is a requirements field; a document has no such field.

    The designer is told to copy the requirements block across verbatim. Handing
    it a key the document schema rejects is a trap of our own making, and it
    costs a repair round on a model that takes minutes per call.
    """

    def _prompt(self) -> str:
        from forge_roles.library import Intent, RequirementSet, Unknown

        requirements = RequirementSet(
            requirements=(),
            assumptions=(),
            unknowns=(
                Unknown(
                    identifier="U1",
                    question="How thick?",
                    why_it_matters="It sets the stiffness.",
                ),
            ),
            risk_class="low",
        )
        intent = Intent(
            summary="a bracket",
            part_kind="bracket",
            stated=(),
            implied=(),
            unstated=(),
        )
        messages = ForgeIRDesigner().build_messages(
            intent=intent, requirements=requirements
        )
        return "\n".join(m.content for m in messages)

    def test_the_unknowns_block_is_withheld(self) -> None:
        self.assertNotIn("unknowns", self._prompt())

    def test_the_fields_that_do_carry_across_are_named(self) -> None:
        prompt = self._prompt()
        for field in ("risk_class", "requirements", "assumptions"):
            self.assertIn(field, prompt)

    def test_the_closing_instruction_disowns_the_worked_example(self) -> None:
        """Last thing said, because that is what a small model acts on."""
        self.assertIn("not the spacer from the guide", self._prompt())


class AFailureShowsWhatItKnows(unittest.TestCase):
    """The diagnosis is in `detail`, and `detail` was never printed.

    Observed live: a run died with the single line "could not reach the
    endpoint". The reason -- WinError 10061, connection refused -- and the hint
    naming the two things to check were both recorded in run.json and neither
    reached the terminal. Every provider error in Forge puts its diagnosis in
    `detail`; rendering only the headline throws that work away at the last step.
    """

    def _render(self, **detail: Any) -> str:
        from forge_orchestrator.run import _render_detail

        return "\n".join(_render_detail(detail))

    def test_the_reason_is_shown(self) -> None:
        rendered = self._render(
            url="http://localhost:11434/v1", reason="[WinError 10061] refused"
        )
        self.assertIn("WinError 10061", rendered)
        self.assertIn("11434", rendered)

    def test_the_hint_comes_last_and_is_marked(self) -> None:
        rendered = self._render(reason="refused", hint="check the server is running")
        self.assertTrue(rendered.rstrip().endswith("-> check the server is running"))

    def test_a_hint_alone_needs_no_blank_line(self) -> None:
        self.assertEqual(self._render(hint="do the thing"), "  -> do the thing")

    def test_machine_facing_keys_stay_out(self) -> None:
        rendered = self._render(
            reason="refused", last_problems=["a", "b"], fingerprint="deadbeef"
        )
        self.assertNotIn("deadbeef", rendered)
        self.assertNotIn("last_problems", rendered)

    def test_empty_values_are_not_printed_as_blanks(self) -> None:
        rendered = self._render(reason="refused", preview="", options=[], other=None)
        self.assertEqual(rendered, "  reason: refused")

    def test_no_detail_adds_nothing(self) -> None:
        self.assertEqual(self._render(), "")

    def test_it_reaches_the_rendered_run(self) -> None:
        """End to end: the failure a user sees carries the hint."""
        from forge_orchestrator.run import DesignRun, State

        run = DesignRun(brief="a bracket")
        run.record(State.FAILED, "could not reach the endpoint")
        run.failure = {
            "message": "could not reach the endpoint",
            "code": "MD1004_TRANSIENT",
            "problems": [],
            "detail": {"reason": "[WinError 10061] refused", "hint": "start it"},
        }
        rendered = run.render(verbose=True)
        self.assertIn("WinError 10061", rendered)
        self.assertIn("-> start it", rendered)


class TheDesignerDoesNotRetypeWhatWeAlreadyHave(unittest.TestCase):
    """Thirty-nine per cent of a real answer was input, copied back verbatim.

    Requirements and assumptions retyped from the block we had just handed it,
    plus ids and units it had been told what to write. On an endpoint running
    at three tokens a second that is minutes per attempt spent copying -- and
    it was the difference between finishing inside the 4096-token ceiling and
    being truncated at it, three times, across a 72-minute run.

    Not asking is also a stronger guarantee than asking nicely: design
    principle 4 ("requirements come through unchanged") existed only because
    the model had the opportunity to soften a threshold on the way past.
    """

    REQUIREMENTS = RequirementSet(
        requirements=(
            {
                "id": "REQ_LOAD",
                "statement": "The bracket shall carry the load with margin.",
                "type": "performance",
                "strength": "hard",
                "verification": "analytical",
                "threshold": {"magnitude": 2.0, "unit": ""},
                "comparison": "at_least",
                "measurement": "safety_factor:bearing",
                "source": "user",
                "state": "accepted",
            },
        ),
        assumptions=({"id": "ASM_DESIGN_LOAD", "statement": "300 N downward",
                      "risk": "high", "approved": False},),
        unknowns=(),
        risk_class="high",
    )

    DESIGNED = {
        "name": "Shelf bracket",
        "components": [
            {
                "id": "bracket",
                "name": "Bracket",
                "parameters": [
                    {"id": "height", "value": {"magnitude": 10.0, "unit": "mm"}}
                ],
                "features": [
                    {
                        "id": "body",
                        "kind": "box",
                        "parameters": {
                            "size": {"vector": [20.0, 20.0, "height"], "unit": "mm"}
                        },
                    }
                ],
            }
        ],
    }

    def _parse(self, document: dict):
        return ForgeIRDesigner().parse(
            {"rationale": "a box", "document": document},
            requirements=self.REQUIREMENTS,
        )

    def test_the_schema_asks_only_for_what_was_designed(self) -> None:
        document = ForgeIRDesigner().output_schema()["properties"]["document"]
        self.assertEqual(sorted(document["properties"]), 
                         ["components", "description", "name"])
        self.assertEqual(sorted(document["required"]), ["components", "name"])

    def test_an_answer_carrying_only_the_design_is_complete(self) -> None:
        draft = self._parse(copy.deepcopy(self.DESIGNED))
        self.assertEqual(draft.document.name, "Shelf bracket")
        self.assertEqual(
            [r["id"] for r in draft.payload["requirements"]], ["REQ_LOAD"]
        )
        self.assertEqual(draft.payload["risk_class"], "high")
        self.assertEqual(draft.payload["schema_version"], "1.0.0")
        self.assertEqual(draft.payload["units"]["length"], "mm")
        self.assertEqual(draft.payload["revision"], 1)

    def test_the_assumption_survives_to_block_release(self) -> None:
        draft = self._parse(copy.deepcopy(self.DESIGNED))
        self.assertEqual(
            [a["id"] for a in draft.payload["assumptions"]], ["ASM_DESIGN_LOAD"]
        )

    def test_a_softened_threshold_is_replaced_not_merged(self) -> None:
        """The accepted record wins. It cannot drift on the way through."""
        tampered = copy.deepcopy(self.DESIGNED)
        tampered["requirements"] = [
            dict(self.REQUIREMENTS.requirements[0],
                 threshold={"magnitude": 1.0, "unit": ""})
        ]
        draft = self._parse(tampered)
        self.assertEqual(
            draft.payload["requirements"][0]["threshold"],
            {"magnitude": 2.0, "unit": ""},
        )

    def test_a_dropped_requirement_comes_back(self) -> None:
        stripped = copy.deepcopy(self.DESIGNED)
        stripped["requirements"] = []
        self.assertEqual(
            [r["id"] for r in self._parse(stripped).payload["requirements"]],
            ["REQ_LOAD"],
        )

    def test_the_same_design_gets_the_same_identity(self) -> None:
        """Derived, not random: two runs of one brief can be diffed."""
        first = self._parse(copy.deepcopy(self.DESIGNED))
        second = self._parse(copy.deepcopy(self.DESIGNED))
        self.assertEqual(
            first.payload["document_id"], second.payload["document_id"]
        )

    def test_a_supplied_identity_is_respected(self) -> None:
        carried = copy.deepcopy(self.DESIGNED)
        carried["document_id"] = "00000000-0000-4000-8000-0000000000aa"
        self.assertEqual(
            self._parse(carried).payload["document_id"],
            "00000000-0000-4000-8000-0000000000aa",
        )

    def test_the_prompt_says_not_to_repeat_them(self) -> None:
        from forge_roles.library import Intent

        messages = ForgeIRDesigner().build_messages(
            intent=Intent(summary="a bracket", part_kind="bracket",
                          stated=(), implied=(), unstated=()),
            requirements=self.REQUIREMENTS,
        )
        prompt = "\n".join(m.content for m in messages)
        self.assertIn("do not repeat them", prompt)
        self.assertIn("filled in for you", prompt)
        # The requirements are still *shown* -- it has to design against them.
        self.assertIn("REQ_LOAD", prompt)


class TheAnswerShapeAndTheAcceptanceCheckMustAgree(unittest.TestCase):
    """The regression that threw away a working design.

    `_DOCUMENT_MARKERS` looked for `schema_version`, `components` and
    `requirements`, and needed two of them. Then the designer's contract changed
    to `name` + `description` + `components` -- two of those three markers being
    fields it is now explicitly told NOT to send. So the check stopped
    recognising exactly the answers the new instructions ask for.

    What it cost, precisely: an answer whose feature graph was correct -- a box
    and a cylinder as input-free primitives, a `union` consuming both, a `hole`
    consuming the union, a `pattern_linear` consuming the hole -- was refused
    with "`document` is missing". The repair round asked for a `document` key,
    and the model, given no idea what was actually wrong, returned the JSON
    Schema itself on the attempt after that.

    The rule now tracks the contract rather than a snapshot of it: an answer is
    whatever carries `components`, and the wrapper never does.
    """

    ANSWER = {
        "name": "Shelf bracket",
        "description": "A plate with a post.",
        "components": [
            {
                "id": "bracket",
                "name": "Bracket",
                "parameters": [
                    {"id": "height", "value": {"magnitude": 10.0, "unit": "mm"}}
                ],
                "features": [
                    {
                        "id": "body",
                        "kind": "box",
                        "parameters": {
                            "size": {"vector": [20.0, 20.0, "height"], "unit": "mm"}
                        },
                    }
                ],
            }
        ],
    }

    def _parse(self, payload: dict):
        return ForgeIRDesigner().parse(
            payload,
            requirements=RequirementSet(
                requirements=(), assumptions=(), unknowns=(), risk_class="low"
            ),
        )

    def test_the_exact_shape_the_instructions_ask_for_is_accepted_bare(self) -> None:
        draft = self._parse(copy.deepcopy(self.ANSWER))
        self.assertEqual(draft.document.name, "Shelf bracket")

    def test_every_field_the_role_asks_for_is_a_marker_or_optional(self) -> None:
        """The check must not go stale the next time the contract moves."""
        required = ForgeIRDesigner().output_schema()["properties"]["document"][
            "required"
        ]
        self.assertTrue(
            set(ForgeIRDesigner._DOCUMENT_MARKERS) <= set(required),
            "a marker the designer is not required to send will go stale",
        )

    def test_the_wrapper_is_still_recognised_as_a_wrapper(self) -> None:
        draft = self._parse(
            {"rationale": "a box", "document": copy.deepcopy(self.ANSWER)}
        )
        self.assertEqual(draft.rationale, "a box")

    def test_prose_alone_is_still_refused(self) -> None:
        with self.assertRaises(RoleOutputError):
            self._parse({"thoughts": "I had some ideas"})


class TheSchemaIsNotAnAnswer(unittest.TestCase):
    """Returning the specification instead of something matching it.

    A weak model with no idea what is wrong with its answer will sometimes hand
    back the shape it was given. Observed on a third attempt: our own document
    schema, verbatim, description and all. Validated as a document that reads
    "unknown field(s): properties, type" -- the symptom, not the mistake.
    """

    SCHEMA_ECHO = {
        "type": "object",
        "description": "The part you designed.",
        "properties": {
            "name": {"type": "string"},
            "components": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["name", "components"],
    }

    def test_it_is_named_for_what_it_is(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse({"rationale": "r", "document": self.SCHEMA_ECHO})
        self.assertIn("JSON Schema was returned", str(caught.exception))

    def test_it_says_what_an_answer_looks_like_instead(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse({"rationale": "r", "document": self.SCHEMA_ECHO})
        problem = caught.exception.problems[0]
        self.assertIn("not an answer", problem)
        self.assertIn('"components"', problem)

    def test_a_real_part_is_untouched(self) -> None:
        """`type` appears in an interface; that must not trip the check."""
        answer = copy.deepcopy(
            TheAnswerShapeAndTheAcceptanceCheckMustAgree.ANSWER
        )
        answer["components"][0]["interfaces"] = [
            {
                "id": "port",
                "type": "bore",
                "geometry": "body.z_max",
                "nominal_size": {"magnitude": 10.0, "unit": "mm"},
            }
        ]
        draft = ForgeIRDesigner().parse(
            answer,
            requirements=RequirementSet(
                requirements=(), assumptions=(), unknowns=(), risk_class="low"
            ),
        )
        self.assertEqual(draft.document.name, "Shelf bracket")


class EveryGuardOnThePathTheModelActuallyTakes(unittest.TestCase):
    """Two regressions reached a live run because nothing tested `run()`.

    Both were guards written against an older contract, and both destroyed a
    good answer before the role that understands the shape ever saw it.

    `_DOCUMENT_MARKERS` needed two of `schema_version`, `components`,
    `requirements` -- two of which the designer is now told not to send.
    `_reject_an_echo` compared the answer's fields against the *wrapper's*
    fields only, so an unwrapped answer shared nothing with `{rationale,
    document}` and was called an echo of the input.

    Tests of `parse` in isolation could not catch either: `parse` was correct,
    and the damage was done before it and around it. So this class drives the
    whole role -- provider, echo guard, parse, repair loop -- with the shapes a
    model really sends, which is the boundary that matters.
    """

    ANSWER = {
        "name": "Shelf bracket",
        "description": "A plate with a post standing on it.",
        "components": [
            {
                "id": "bracket",
                "name": "Bracket",
                "material": "aluminium_6061_t6",
                "parameters": [
                    {"id": "plate", "value": {"magnitude": 6.0, "unit": "mm"}},
                    {"id": "post_d", "value": {"magnitude": 30.0, "unit": "mm"}},
                    {"id": "rise", "value": {"magnitude": 32.0, "unit": "mm"}},
                    {"id": "bolts", "value": {"magnitude": 4, "unit": ""}},
                ],
                "features": [
                    {
                        "id": "base",
                        "kind": "box",
                        "parameters": {
                            "size": {"vector": [60.0, 40.0, "plate"], "unit": "mm"},
                            "centered": True,
                        },
                    },
                    {
                        "id": "post",
                        "kind": "cylinder",
                        "parameters": {
                            "diameter": {"expression": "post_d", "unit": "mm"},
                            "height": {"expression": "rise", "unit": "mm"},
                        },
                    },
                    {
                        "id": "body",
                        "kind": "union",
                        "inputs": ["base", "post"],
                        "parameters": {
                            "blend_radius": {"magnitude": 2.0, "unit": "mm"}
                        },
                    },
                    {
                        "id": "bore",
                        "kind": "hole",
                        "role": "shaft",
                        "inputs": ["body"],
                        "parameters": {
                            "diameter": {"magnitude": 20.0, "unit": "mm"},
                            "position": {"vector": [0, 0, "rise"], "unit": "mm"},
                            "axis": [1, 0, 0],
                        },
                    },
                ],
            }
        ],
    }

    REQUIREMENTS = RequirementSet(
        requirements=(), assumptions=(), unknowns=(), risk_class="low"
    )

    def _run_role(self, response: dict, *, repeats: int = 1):
        from forge_roles.library import Intent

        provider = ScriptedProvider([response] * repeats)
        return ForgeIRDesigner().run(
            provider,
            intent=Intent(summary="a bracket", part_kind="bracket",
                          stated=(), implied=(), unstated=()),
            requirements=self.REQUIREMENTS,
        )

    def test_a_bare_answer_survives_every_guard(self) -> None:
        """The exact shape the instructions ask for, sent without a wrapper."""
        result = self._run_role(copy.deepcopy(self.ANSWER))
        self.assertEqual(result.value.document.name, "Shelf bracket")
        self.assertEqual(result.attempts, 1, "it should not have needed repair")

    def test_the_wrapped_form_survives_too(self) -> None:
        result = self._run_role(
            {"rationale": "a plate and a post", "document": copy.deepcopy(self.ANSWER)}
        )
        self.assertEqual(result.value.rationale, "a plate and a post")

    def test_that_answer_compiles_into_a_watertight_solid(self) -> None:
        """The guards are only worth passing if what they pass is buildable."""
        from forge_geom import extract_surface
        from forge_kernel import Compiler

        draft = self._run_role(copy.deepcopy(self.ANSWER)).value
        part = Compiler().compile_component(draft.document.components[0])
        mesh = extract_surface(part.solid, resolution=48)
        self.assertTrue(mesh.is_watertight()[0])

    def test_an_actual_echo_of_the_input_is_still_caught(self) -> None:
        """The guard still does the job it was written for."""
        with self.assertRaises(RepairExhaustedError) as caught:
            self._run_role(
                {"brief": "A bracket that holds a 20 mm shaft"}, repeats=3
            )
        problems = " ".join(caught.exception.detail["last_problems"])
        self.assertIn("None of the fields you returned (brief)", problems)
        self.assertIn("must not be passed back", problems)

    def test_the_echo_guard_looks_one_level_down_not_only_at_the_top(self) -> None:
        """The property that fixes it, stated directly."""
        designer = ForgeIRDesigner()
        schema = designer.output_schema()
        # Shares nothing with {rationale, document}, everything with what
        # `document` contains.
        designer._reject_an_echo({"name": "x", "components": []}, schema)


class OscillationIsDetectedOnGatesToo(unittest.TestCase):
    """The check was there, and on the gate path it could never fire.

    `seen_patches` was carried across rounds on the compile path and rebuilt as
    a fresh `set()` inside every gate round. The question it then asked was
    "has this round proposed this patch twice?", and a round proposes once, so
    the answer was always no.

    Observed on the first live run to reach verification: the analyst proposed
    "Add geometry to interface", it changed nothing, the gate failed again, and
    the identical patch was proposed and applied a second time. Ninety seconds
    of generation to arrive back where we started, and a run that reported two
    repairs when it had really made one twice.
    """

    def _run_with_repeated_analyst(self):
        return _run([INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN,
                     ANALYST_REPEATS, ANALYST_REPEATS])

    def test_the_same_patch_twice_stops_the_loop(self) -> None:
        run, provider = self._run_with_repeated_analyst()
        outcomes = [repair.outcome for repair in run.repairs]
        self.assertIn("oscillation", outcomes, f"repairs were {outcomes}")

    def test_it_says_so_rather_than_failing_silently(self) -> None:
        run, _ = self._run_with_repeated_analyst()
        self.assertIsNotNone(run.failure)
        self.assertEqual(run.failure["code"], "OR1002_OSCILLATION")
        self.assertIn("repeating itself", run.failure["message"])

    def test_the_analyst_is_not_asked_a_third_time(self) -> None:
        """The whole point: stopping costs less than one more round."""
        _, provider = self._run_with_repeated_analyst()
        analyst_calls = [
            request for request in provider.requests
            if request.purpose == "failure_analyst"
        ]
        self.assertLessEqual(len(analyst_calls), 2)

    def test_the_memory_is_one_set_for_the_whole_run(self) -> None:
        """A fresh set per round is the defect, stated as a property."""
        import inspect

        from forge_orchestrator import orchestrator as module

        source = inspect.getsource(module.Orchestrator._repair_gates)
        self.assertNotIn("seen_patches=set()", source)


class AGateThatKnowsWhyItFailedSaysSo(unittest.TestCase):
    """What the analyst is handed about a failed gate.

    A threshold miss explains itself: "at most 120 g, measured 141 g" names the
    direction to move. A gate that measures a *structural* fact does not: "every
    through hole is open, at most 0, measured 1" is a true sentence the analyst
    cannot act on, and an analyst that cannot act still answers -- with a patch
    to whichever dimension looked closest. The gate already knows what went
    wrong and how to fix it, and used to keep that in evidence nobody read.
    """

    def _result(self, detail: dict[str, Any]):
        from forge_evidence import Gate, GateResult, Method, ToolIdentity
        from forge_units import Q

        gate = Gate(
            identifier="GEOM_THROUGH_HOLES_OPEN",
            claim="every hole declared without a depth is open through the part",
            comparison="at_most",
            threshold=Q(0),
            critical=True,
        )
        evidence = gate.evaluate(
            Q(1),
            method=Method.EXACT_GEOMETRY,
            tool=ToolIdentity("test", "0"),
            detail=detail,
        )
        return GateResult(gate, evidence)

    def test_the_hint_is_in_what_the_analyst_receives(self) -> None:
        from forge_orchestrator.orchestrator import _gate_failure

        failure = _gate_failure(self._result({"hint": "cut the hole last"}))
        self.assertEqual(failure["how_to_fix"], "cut the hole last")
        self.assertEqual(failure["measured"], "1")

    def test_a_gate_without_a_hint_still_says_how_far_off(self) -> None:
        """No hint is invented for it; what every failure carries -- its
        status and how far off it is, which way -- it carries."""
        from forge_orchestrator.orchestrator import _gate_failure

        failure = _gate_failure(self._result({}))
        self.assertNotIn("how_to_fix", failure)
        self.assertEqual(
            sorted(failure),
            ["claim", "id", "measured", "off_by", "required", "status"])
        self.assertEqual(failure["off_by"], "1 over")

    def test_a_runaway_hint_cannot_crowd_out_the_document(self) -> None:
        from forge_orchestrator.orchestrator import _gate_failure

        failure = _gate_failure(self._result({"hint": "x" * 5000}))
        self.assertLessEqual(len(failure["how_to_fix"]), 1600)


class APatchThatChangesNothing(unittest.TestCase):
    """Applied, valid, and identical to what went in.

    Observed on the first live run to reach verification: the analyst proposed
    `add` at `/components/0/interfaces/0/geometry` with value `"shaft.bore"`,
    which was already `"shaft.bore"`. The patch applied cleanly, the document
    was byte-identical, and the loop recompiled and re-measured it to discover
    the same failure. Reported as two repairs when it had made none.

    A stronger check than comparing patch signatures: a *different* patch that
    also changes nothing lands here too.
    """

    def _no_op_analyst(self) -> dict:
        """A patch setting a field to the value the broken document has."""
        from fixtures.bracket_responses import DESIGNER_BROKEN

        component = DESIGNER_BROKEN["document"]["components"][0]
        return {
            "diagnosis": "The name is wrong.",
            "strategy": "rename",
            "abandon": False,
            "patches": [
                {
                    "op": "add",
                    "pointer": "/components/0/name",
                    "value": component["name"],
                    "reason": "set it to what it already is",
                }
            ],
        }

    def test_it_is_recorded_as_a_non_change_not_a_repair(self) -> None:
        run, _ = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, self._no_op_analyst()]
        )
        self.assertIn("no_change", [repair.outcome for repair in run.repairs])

    def test_the_run_says_what_happened(self) -> None:
        run, _ = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, self._no_op_analyst()]
        )
        self.assertEqual(run.failure["code"], "OR1003_NO_CHANGE")
        self.assertIn("did not change the design", run.failure["message"])

    def test_it_does_not_recompile_an_identical_document(self) -> None:
        """The saving: no second measure, no second analyst call."""
        run, provider = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, self._no_op_analyst()]
        )
        analyst_calls = [
            request for request in provider.requests
            if request.purpose == "failure_analyst"
        ]
        self.assertEqual(len(analyst_calls), 1)

    def test_a_patch_that_does_change_something_is_unaffected(self) -> None:
        run, _ = _run(
            [INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, ANALYST_FIX_BOUNDS]
        )
        self.assertIn("applied", [repair.outcome for repair in run.repairs])


class TheDesignerIsNotBlamedForTheRequirementsEngineersMistake(unittest.TestCase):
    """Fifteen minutes spent asking the wrong role to fix the wrong field.

    Asked for a standoff in 6061-T6 aluminium, the Requirements Engineer wrote
    `{"magnitude": 6061, "unit": "T6 aluminium alloy"}` into an assumption's
    numeric `value`. Nothing checked it. The orchestrator merged the accepted
    assumptions into the document -- as it must, since the designer no longer
    writes them -- the decoder rejected the unit, and the run died reporting

        the forgeir_designer role could not produce valid output in 3 attempts
          At `/assumptions/0/value`: unit symbol is not in the registry

    The designer had not written that field, could not see it, and does not
    emit assumptions at all. It rewrote its geometry three times, correctly,
    and failed three times on someone else's error.

    Two fixes, and both are needed. The value is checked where it is written,
    so the run usually never gets this far; and a failure inside a filled-in
    block is refused by the designer rather than repaired, so the budget is
    never spent on it again.
    """

    BAD_MATERIAL = {
        "id": "ASM_MATERIAL",
        "statement": "The standoff shall be 6061-T6 aluminium.",
        "value": {"magnitude": 6061, "unit": "T6 aluminium alloy"},
        "rationale": "The brief specifies the grade.",
        "consequence_if_wrong": "It may not meet its margins.",
        "risk": "moderate",
        "reversible": False,
        "approved": False,
    }

    ANSWER = {
        "name": "Standoff",
        "components": [{
            "id": "standoff",
            "name": "Standoff",
            "parameters": [],
            "features": [{
                "id": "body",
                "kind": "box",
                "parameters": {
                    "size": {"vector": [50.0, 50.0, 5.0], "unit": "mm"}
                },
            }],
        }],
    }

    def _requirements(self, assumption: dict) -> RequirementSet:
        return RequirementSet(
            requirements=({
                "id": "R1", "statement": "A claim.", "type": "geometric",
                "strength": "hard", "verification": "exact_geometry",
                "threshold": {"magnitude": 8.0, "unit": "mm"},
                "comparison": "equals", "measurement": "mass",
                "source": "user", "state": "accepted",
            },),
            assumptions=(assumption,),
            unknowns=(),
            risk_class="moderate",
        )

    # -- caught where it is written -------------------------------------
    def test_the_requirements_engineer_refuses_a_grade_as_a_quantity(self) -> None:
        payload = {
            "risk_class": "moderate",
            "requirements": [{
                "id": "R1", "statement": "A claim.", "type": "geometric",
                "strength": "hard", "verification": "exact_geometry",
                "threshold": {"magnitude": 8.0, "unit": "mm"},
                "comparison": "equals", "measurement": "mass",
                "source": "user", "state": "accepted",
            }],
            "assumptions": [dict(self.BAD_MATERIAL)],
            "unknowns": [],
        }
        with self.assertRaises(RoleOutputError) as caught:
            RequirementsEngineer().parse(payload)
        problem = " ".join(caught.exception.problems)
        self.assertIn("is not a unit", problem)
        self.assertIn("`statement`", problem)
        self.assertIn("material", problem)

    def test_a_real_quantity_is_still_fine(self) -> None:
        payload = {
            "risk_class": "moderate",
            "requirements": [{
                "id": "R1", "statement": "A claim.", "type": "geometric",
                "strength": "hard", "verification": "exact_geometry",
                "threshold": {"magnitude": 8.0, "unit": "mm"},
                "comparison": "equals", "measurement": "mass",
                "source": "user", "state": "accepted",
            }],
            "assumptions": [{
                "id": "ASM_LOAD", "statement": "300 N downward.",
                "value": {"magnitude": 300.0, "unit": "N"},
                "consequence_if_wrong": "The margins are unfounded.",
                "risk": "high",
            }],
            "unknowns": [],
        }
        RequirementsEngineer().parse(payload)

    def test_an_assumption_with_no_value_at_all_is_fine(self) -> None:
        """Most assumptions are prose. `value` is optional and usually absent."""
        from forge_roles.library import _problems_with_an_assumption_value

        self.assertEqual(
            _problems_with_an_assumption_value("assumptions[0]", {"id": "A"}), []
        )

    # -- and refused if it somehow gets through --------------------------
    def test_the_designer_names_the_stage_that_produced_it(self) -> None:
        from forge_roles import RoleInputError

        with self.assertRaises(RoleInputError) as caught:
            ForgeIRDesigner().parse(
                copy.deepcopy(self.ANSWER),
                requirements=self._requirements(dict(self.BAD_MATERIAL)),
            )
        self.assertEqual(caught.exception.stage, "requirements_engineer")
        self.assertIn("not the designer's output", caught.exception.problems[0])
        self.assertIn("/assumptions/0/value", caught.exception.problems[0])

    def test_it_is_not_a_repairable_output_error(self) -> None:
        """The distinction that stops the budget being spent on it."""
        from forge_roles import RoleInputError

        self.assertFalse(issubclass(RoleInputError, RoleOutputError))

    def test_the_run_stops_at_one_attempt_and_says_who(self) -> None:
        from forge_roles.library import Intent

        provider = ScriptedProvider([copy.deepcopy(self.ANSWER)] * 3)
        with self.assertRaises(Exception) as caught:
            ForgeIRDesigner().run(
                provider,
                intent=Intent(summary="a standoff", part_kind="standoff",
                              stated=(), implied=(), unstated=()),
                requirements=self._requirements(dict(self.BAD_MATERIAL)),
            )
        self.assertEqual(caught.exception.code, "RL1003_INPUT")
        self.assertEqual(len(provider.requests), 1, "it retried someone else's bug")

    def test_the_designer_still_owns_its_own_mistakes(self) -> None:
        """A fault in `components` is the designer's, and stays repairable."""
        broken = copy.deepcopy(self.ANSWER)
        broken["components"][0]["features"][0]["parameters"]["size"] = {
            "magnitude": 50.0, "unit": "mm"
        }
        with self.assertRaises(RoleOutputError):
            ForgeIRDesigner().parse(
                broken,
                requirements=self._requirements({
                    "id": "ASM_LOAD", "statement": "300 N.",
                    "value": {"magnitude": 300.0, "unit": "N"}, "risk": "high",
                }),
            )


class ARequirementMeasuresWhatItIsAbout(unittest.TestCase):
    """Three false alarms on a part that was exactly right.

    Asked for a 25 mm post on a 50 mm plate 5 mm thick, the designer built
    precisely that -- `diameter` 25, `base_plate_thickness` 5, every number
    from the brief. The report said FAIL three times, because the Requirements
    Engineer had bound the claims to the finished part's envelope:

        "the base plate shall be 5 mm thick"   -> bounding_box_z  (32.5)
        "the standoff shall be 25 mm across"   -> bounding_box_x  (50)

    A bounding box cannot measure one feature of a part that has several. The
    vocabulary offered `parameter:<id>` and said nothing about when to prefer
    it, and the simple bindings rendered with no description at all -- so the
    plainest-looking option was the wrong one.

    A false alarm on a correct design is the worst output an evidence system
    can produce: it is indistinguishable from a real failure, and it teaches
    the reader to stop believing the report.
    """

    def test_the_vocabulary_says_which_to_choose(self) -> None:
        from forge_ir.measurements import vocabulary_help

        help_text = vocabulary_help()
        self.assertIn("ONE NAMED DIMENSION", help_text)
        self.assertIn("parameter:plate_thickness", help_text)

    def test_every_whole_part_binding_says_it_is_whole_part(self) -> None:
        from forge_ir.measurements import SIMPLE_MEASUREMENTS, vocabulary_help

        help_text = vocabulary_help()
        for name in SIMPLE_MEASUREMENTS:
            line = next(
                (l for l in help_text.splitlines() if l.strip().startswith(f"- {name}")),
                "",
            )
            self.assertTrue(line, f"{name} has no line at all")
            self.assertGreater(
                len(line.split(name, 1)[1].strip()), 5,
                f"{name} renders with no description, which is how it got chosen",
            )

    def test_the_bounding_box_warns_that_it_is_the_envelope(self) -> None:
        from forge_ir.measurements import vocabulary_help

        self.assertIn("WHOLE part's overall extent in z", vocabulary_help())

    # -- the contract ---------------------------------------------------
    def _requirements(self, *bindings: str) -> RequirementSet:
        return RequirementSet(
            requirements=tuple(
                {
                    "id": f"REQ_{index}", "statement": "A dimension.",
                    "type": "geometric", "strength": "hard",
                    "verification": "exact_geometry",
                    "threshold": {"magnitude": 5.0, "unit": "mm"},
                    "comparison": "equals", "measurement": binding,
                    "source": "user", "state": "accepted",
                }
                for index, binding in enumerate(bindings)
            ),
            assumptions=(), unknowns=(), risk_class="low",
        )

    ANSWER = {
        "name": "Standoff",
        "components": [{
            "id": "standoff", "name": "Standoff",
            "parameters": [
                {"id": "plate_thickness", "value": {"magnitude": 5.0, "unit": "mm"}}
            ],
            "features": [{
                "id": "base", "kind": "box", "parameters": {
                    "size": {"vector": [50.0, 50.0, "plate_thickness"],
                             "unit": "mm"}}},
            ],
        }],
    }

    def test_the_designer_is_told_which_parameters_to_declare(self) -> None:
        from forge_roles.library import Intent

        messages = ForgeIRDesigner().build_messages(
            intent=Intent(summary="a standoff", part_kind="standoff",
                          stated=(), implied=(), unstated=()),
            requirements=self._requirements(
                "parameter:plate_thickness", "parameter:post_diameter"
            ),
        )
        prompt = "\n".join(m.content for m in messages)
        self.assertIn("must declare a parameter with each of these", prompt)
        self.assertIn("plate_thickness", prompt)
        self.assertIn("post_diameter", prompt)

    def test_a_design_missing_one_is_asked_for_it_by_name(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(
                copy.deepcopy(self.ANSWER),
                requirements=self._requirements(
                    "parameter:plate_thickness", "parameter:post_diameter"
                ),
            )
        problem = caught.exception.problems[0]
        self.assertIn("`post_diameter`", problem)
        self.assertNotIn("`plate_thickness`,", problem, "it declared that one")
        self.assertIn("Declared here", problem)

    def test_a_design_that_declares_them_all_passes(self) -> None:
        draft = ForgeIRDesigner().parse(
            copy.deepcopy(self.ANSWER),
            requirements=self._requirements("parameter:plate_thickness"),
        )
        self.assertEqual(draft.document.name, "Standoff")

    def test_requirements_that_measure_the_whole_part_ask_for_nothing(self) -> None:
        """`bounding_box_z` is legitimate for an envelope claim; no contract."""
        draft = ForgeIRDesigner().parse(
            copy.deepcopy(self.ANSWER),
            requirements=self._requirements("bounding_box_z", "mass"),
        )
        self.assertEqual(draft.document.name, "Standoff")

    def test_the_check_is_caught_at_design_time_not_verification(self) -> None:
        """At verification a missing parameter reads BLOCKED on a good part."""
        from forge_roles.library import _parameters_the_requirements_measure

        self.assertEqual(
            _parameters_the_requirements_measure(
                self._requirements("parameter:a", "bounding_box_z", "parameter:b",
                                   "parameter:a")
            ),
            ("a", "b"),
        )


class TheDesignerIsToldWhichTagsWillBeCounted(unittest.TestCase):
    """The other half of a counted requirement's contract.

    `feature_count:hole:mounting` counts holes tagged `mounting`. Nothing else
    in the prompt says that word was chosen, so an untagged design measures
    zero and a correct part fails -- which is precisely the false alarm the
    tagged form exists to prevent. Same shape as the measured-parameter
    contract: tell the designer, then require it.
    """

    def _intent(self):
        from forge_roles.library import Intent

        return Intent(
            summary="a plate with four mounting holes",
            part_kind="plate",
            stated=("four mounting holes",),
            implied=(),
            unstated=(),
        )

    def _requirements(self, binding: str) -> RequirementSet:
        return RequirementSet(
            requirements=(
                {
                    "id": "REQ_BOLTS",
                    "statement": "There shall be four mounting holes.",
                    "measurement": binding,
                    "comparison": "equals",
                },
            ),
            assumptions=(),
            unknowns=(),
        )

    def test_the_prompt_names_the_tag(self) -> None:
        designer = ForgeIRDesigner()
        messages = designer.build_messages(
            intent=self._intent(),
            requirements=self._requirements("feature_count:hole:mounting"),
        )
        text = "\n".join(m.content for m in messages)
        self.assertIn("mounting", text)
        self.assertIn("tags", text)

    def test_an_untagged_design_is_sent_back_before_it_is_verified(self) -> None:
        designer = ForgeIRDesigner()
        document = {
            "name": "Plate",
            "components": [
                {
                    "id": "plate",
                    "name": "Plate",
                    "parameters": [
                        {"id": "t", "value": {"magnitude": 6, "unit": "mm"}}
                    ],
                    "features": [
                        {
                            "id": "body",
                            "kind": "box",
                            "parameters": {
                                "size": {
                                    "vector": [20, 20, "t"],
                                    "unit": "mm",
                                }
                            },
                        },
                        # Holes exist and none is tagged, and the binding says
                        # `equals` without a magnitude, so nothing singles out
                        # which of them the requirement means. That is the
                        # case where asking the designer is the right answer:
                        # the repair is one key, and Forge would be guessing.
                        {"id": "h1", "kind": "hole"},
                        {"id": "h2", "kind": "hole"},
                    ],
                }
            ],
        }
        with self.assertRaises(RoleOutputError) as caught:
            designer.parse(
                {"rationale": "r", "document": document},
                requirements=self._requirements("feature_count:hole:mounting"),
            )
        self.assertIn("mounting", " ".join(caught.exception.problems))

    def test_an_untagged_count_asks_nothing_of_the_designer(self) -> None:
        """`feature_count:hole` counts every hole; there is no tag to apply."""
        from forge_roles.library import _tags_the_requirements_count

        self.assertEqual(
            _tags_the_requirements_count(
                self._requirements("feature_count:hole")
            ),
            (),
        )


class APatchThatWillNotApplyIsNotTheEndOfTheLoop(unittest.TestCase):
    """One malformed pointer used to spend the whole repair budget.

    Observed live: the analyst addressed a parameter by name --
    `/components/0/parameters/base_thickness/value` -- which JSON Pointer does
    not do. (Forge now reads an element's id as its address; the fixture names
    one nothing has.) The patch was rejected, correctly, and the loop then stopped with a
    round still unspent and the run reported blocked.

    A patch that will not apply says nothing about whether the design can be
    fixed. The analyst sees every previous attempt including the error it just
    caused, so the next round is a different attempt, not a retry -- and an
    identical repeat is still caught as oscillation.
    """

    def _run(self):
        return _run(
            [
                INTERPRETER,
                REQUIREMENTS,
                DESIGNER_BROKEN,
                ANALYST_BAD_POINTER,
                ANALYST_FIX_BOUNDS,
            ]
        )

    def test_the_analyst_is_asked_again(self) -> None:
        _, provider = self._run()
        analyst_calls = [
            request
            for request in provider.requests
            if request.purpose == "failure_analyst"
        ]
        self.assertEqual(
            len(analyst_calls),
            2,
            "the loop gave up after one unusable patch",
        )

    def test_the_rejected_attempt_is_still_recorded(self) -> None:
        run, _ = self._run()
        outcomes = [repair.outcome for repair in run.repairs]
        self.assertTrue(
            any(outcome.startswith("patch_rejected") for outcome in outcomes),
            f"repairs were {outcomes}",
        )

    def test_the_second_attempt_sees_the_first(self) -> None:
        """Otherwise it is a retry, and it makes the same mistake."""
        _, provider = self._run()
        analyst_calls = [
            request
            for request in provider.requests
            if request.purpose == "failure_analyst"
        ]
        text = "\n".join(m.content for m in analyst_calls[-1].messages)
        self.assertIn("patch_rejected", text)

    def test_a_run_that_only_ever_proposes_bad_patches_still_stops(self) -> None:
        """The budget is the backstop; it must still be a backstop."""
        run, provider = _run(
            [
                INTERPRETER,
                REQUIREMENTS,
                DESIGNER_BROKEN,
                ANALYST_BAD_POINTER,
                ANALYST_BAD_POINTER,
                ANALYST_BAD_POINTER,
                ANALYST_BAD_POINTER,
            ]
        )
        self.assertIn(run.state.value, {"blocked", "failed"})


class APatchThatLeavesAnInvalidDocumentIsNotTheEndOfTheLoop(unittest.TestCase):
    """Run 20261003T235448: the analyst removed `base` from under the
    `shell` that read it. The patched document did not validate, and the
    run was blocked there with a round of its budget unspent -- the same
    mistake `patch_rejected` had already been cured of.
    """

    REMOVES_THE_BASE = {
        "diagnosis": "`base` contributes nothing.",
        "strategy": "remove it",
        "confidence": "medium",
        "abandon": False,
        "patches": [{"op": "remove", "pointer": "/components/0/features/0",
                     "reason": "it contributes nothing"}],
    }

    def _run(self, *analyst):
        return _run([INTERPRETER, REQUIREMENTS, DESIGNER_BROKEN, *analyst])

    def test_the_analyst_is_asked_again_and_told_why(self) -> None:
        run, provider = self._run(self.REMOVES_THE_BASE, ANALYST_FIX_BOUNDS)
        analyst_calls = [r for r in provider.requests
                         if r.purpose == "failure_analyst"]
        self.assertEqual(len(analyst_calls), 2)
        first = run.repairs[0].outcome
        self.assertTrue(first.startswith("patched document did not validate"),
                        first)
        # The reason, not just the verdict: what the next round must avoid.
        self.assertIn("unknown feature", first)
        text = "\n".join(m.content for m in analyst_calls[-1].messages)
        self.assertIn("unknown feature", text)

    def test_the_same_invalid_patch_twice_still_stops(self) -> None:
        run, _ = self._run(self.REMOVES_THE_BASE, self.REMOVES_THE_BASE,
                           self.REMOVES_THE_BASE, self.REMOVES_THE_BASE)
        self.assertIn(run.state.value, {"blocked", "failed"})


class TheSameAnswerTwiceIsNotWorthAThirdAttempt(unittest.TestCase):
    """A model shown its mistake and repeating itself will repeat itself again.

    Observed live: the designer returned the identical document three times,
    against the identical problem, at roughly 25 minutes an attempt. The third
    attempt cost half an hour to confirm what the second had already settled.

    This is the role-level twin of the orchestrator's oscillation check, and it
    exists for the same reason: stopping is cheaper than learning nothing.
    """

    def _role(self):
        from forge_roles import BriefInterpreter

        class AlwaysTheSame(BriefInterpreter):
            def parse(self, structured, **inputs):  # noqa: ARG002
                raise RoleOutputError("no", ["the same problem every time"])

        return AlwaysTheSame()

    def test_it_stops_after_the_repeat(self) -> None:
        from forge_models import ScriptedProvider

        answer = {"summary": "s", "part_kind": "p"}
        provider = ScriptedProvider([answer, answer, answer, answer])
        with self.assertRaises(RepairExhaustedError) as caught:
            self._role().run(provider, brief="a plate")
        self.assertEqual(caught.exception.detail["attempts"], 2)
        self.assertTrue(caught.exception.detail["stopped_early"])

    def test_it_says_why_it_stopped_early(self) -> None:
        from forge_models import ScriptedProvider

        answer = {"summary": "s", "part_kind": "p"}
        with self.assertRaises(RepairExhaustedError) as caught:
            self._role().run(
                ScriptedProvider([answer, answer, answer]), brief="a plate"
            )
        self.assertIn("same answer twice", caught.exception.message)

    def test_a_role_that_changes_its_answer_still_gets_every_attempt(self) -> None:
        """Stopping early must not punish a model that is actually trying."""
        from forge_models import ScriptedProvider
        from forge_roles import BriefInterpreter

        class DifferentEveryTime(BriefInterpreter):
            def __init__(self) -> None:
                super().__init__()
                self.seen = 0

            def parse(self, structured, **inputs):  # noqa: ARG002
                self.seen += 1
                raise RoleOutputError("no", [f"problem {self.seen}"])

        role = DifferentEveryTime()
        answer = {"summary": "s", "part_kind": "p"}
        with self.assertRaises(RepairExhaustedError) as caught:
            role.run(ScriptedProvider([answer] * 8), brief="a plate")
        self.assertEqual(caught.exception.detail["attempts"], role.max_attempts)
        self.assertFalse(caught.exception.detail["stopped_early"])


class ABugInForgeDoesNotCostTheRunItsRecord(unittest.TestCase):
    """Fifty minutes of generation, and nothing on disk to show for it.

    `design()` caught ModelError and RoleError -- the failures it expected --
    and let everything else past. Observed live: a model wrote
    `{"magnitude": "fillet_thickness"}`, `float()` raised a plain ValueError
    three layers down in the decoder, and it travelled out of the CLI as a
    one-line traceback. The run had already produced an intent, a requirement
    set and two documents. None of it was written.

    A defect in Forge is not a reason to destroy the evidence of what the run
    did before it hit one.
    """

    def _run_that_breaks(self):
        from forge_models import ScriptedProvider
        from forge_orchestrator import Orchestrator

        class Breaking(Orchestrator):
            def _design(self, run, *, cancellation=None):  # noqa: ARG002
                run.record(State.INTERPRETING, "reading the brief")
                raise ValueError("could not convert string to float: 'x'")

        return Breaking(ScriptedProvider([])).design("a plate")

    def test_it_returns_a_run_rather_than_raising(self) -> None:
        run = self._run_that_breaks()
        self.assertIs(run.state, State.FAILED)

    def test_the_failure_is_named_as_ours(self) -> None:
        """A user reading "your design is invalid" would go and edit the brief."""
        run = self._run_that_breaks()
        self.assertEqual(run.failure["code"], "OR1004_INTERNAL")
        self.assertIn("defect in Forge", run.failure["detail"]["hint"])

    def test_the_traceback_is_kept(self) -> None:
        run = self._run_that_breaks()
        self.assertIn("ValueError", run.failure["detail"]["traceback"])

    def test_what_happened_before_the_bug_survives(self) -> None:
        run = self._run_that_breaks()
        self.assertTrue(
            any(e.state is State.INTERPRETING for e in run.events),
            "the event log was lost with the exception",
        )

    def test_the_artefacts_are_written(self) -> None:
        """The property that actually matters to somebody at a terminal."""
        import tempfile
        from pathlib import Path

        from forge_cli.design import write_artifacts

        run = self._run_that_breaks()
        with tempfile.TemporaryDirectory() as directory:
            written = write_artifacts(run, Path(directory))
            names = {path.name for path in written}
        self.assertIn("run.json", names)
        self.assertIn("run.txt", names)


class ATagACountNeedsIsAppliedOrExplained(unittest.TestCase):
    """`feature_count:hole:mounting` is only checkable once the tag is on.

    The check that enforces this used to reject any document missing a tag
    the requirements count, and that rejection could be unsatisfiable. Forge's
    own authoring guide teaches four bolt holes as a `cylinder`, two
    `pattern_linear`s and a `subtract` -- a construction with no feature of
    kind `hole` at all, on which no tagging will ever produce one. Demanding
    it spent four designer attempts, the most expensive call in the pipeline,
    on something the model could not do however willing it was.

    So the response now depends on whether the tag can be applied: apply it
    when the count singles the features out, ask when it does not, and note it
    when the kind is not in the document at all.
    """

    @staticmethod
    def _requirements(count=None, comparison="equals"):
        entry = {
            "id": "R_COUNT",
            "statement": "Four mounting holes.",
            "measurement": "feature_count:hole:mounting",
            "comparison": comparison,
        }
        if count is not None:
            entry["threshold"] = {"magnitude": count, "unit": ""}
        return type("R", (), {"requirements": (entry,)})()

    @staticmethod
    def _document(kinds):
        return {
            "components": [
                {
                    "id": "c",
                    "features": [
                        {"id": f"f{index}", "kind": kind}
                        for index, kind in enumerate(kinds)
                    ],
                }
            ]
        }

    def test_an_exact_count_that_singles_them_out_is_tagged(self) -> None:
        payload = self._document(["hole"] * 4)
        notes, problems = ForgeIRDesigner._require_the_counted_tags(  # noqa: SLF001
            payload, requirements=self._requirements(count=4))
        tagged = [
            feature["tags"]
            for feature in payload["components"][0]["features"]
        ]
        self.assertEqual(tagged, [["mounting"]] * 4)
        self.assertTrue(any("tagged 4" in note for note in notes), notes)

    def test_an_ambiguous_count_is_asked_about(self) -> None:
        # Five holes, four wanted: Forge does not choose which four.
        payload = self._document(["hole"] * 5)
        _, problems = ForgeIRDesigner._require_the_counted_tags(  # noqa: SLF001
            payload, requirements=self._requirements(count=4))
        self.assertTrue(problems)
        self.assertIn("mounting", " ".join(problems))
        self.assertNotIn(
            "tags", payload["components"][0]["features"][0],
            "nothing may be tagged on the way to asking",
        )

    def test_at_least_never_tags(self) -> None:
        """"At least two" does not say which two of the four it means."""
        payload = self._document(["hole"] * 2)
        _, problems = ForgeIRDesigner._require_the_counted_tags(  # noqa: SLF001
            payload,
            requirements=self._requirements(count=2, comparison="at_least"),
        )
        self.assertTrue(problems)

    def test_a_kind_the_document_does_not_build_is_noted_not_refused(
        self,
    ) -> None:
        # The construction the authoring guide itself teaches.
        payload = self._document(
            ["cylinder", "pattern_linear", "pattern_linear", "subtract"])
        notes, problems = ForgeIRDesigner._require_the_counted_tags(  # noqa: SLF001
            payload, requirements=self._requirements(count=4))
        # Said as what it is: the count reads zero, the binding's answer.
        self.assertTrue(any("reads zero" in note for note in notes), notes)
        self.assertTrue(any("`hole`" in note for note in notes), notes)
        self.assertFalse(problems)

    def test_a_tag_already_applied_is_left_alone(self) -> None:
        payload = self._document(["hole"] * 4)
        payload["components"][0]["features"][0]["tags"] = ["mounting"]
        notes, problems = ForgeIRDesigner._require_the_counted_tags(  # noqa: SLF001
            payload, requirements=self._requirements(count=4))
        self.assertEqual(notes, [])
        self.assertEqual(
            [f.get("tags") for f in payload["components"][0]["features"]],
            [["mounting"], None, None, None],
        )

    def test_the_real_fixture_is_untouched(self) -> None:
        """No count by tag, nothing to do -- the common case must cost
        nothing and change nothing."""
        payload = copy.deepcopy(DESIGNER_VALID["document"])
        before = copy.deepcopy(payload)
        real = type(
            "R", (), {"requirements": tuple(REQUIREMENTS["requirements"])}
        )()
        notes, problems = ForgeIRDesigner._require_the_counted_tags(  # noqa: SLF001
            payload, requirements=real)
        self.assertEqual(notes, [])
        self.assertEqual(payload, before)


class APortThatNamesNothingIsNotWorthADesign(unittest.TestCase):
    """A dangling interface used to cost the whole design.

    `Component.validate` is right to reject an interface whose geometry no
    feature publishes, and that contract is not relaxed here -- a ForgeIR
    document stays valid by construction. What changed is what reaches it: an
    interface naming an owner that does not exist and never did describes
    nothing, so Forge drops it and says so, rather than spending a
    thirteen-minute repair round -- or the run -- on decorative metadata.

    Two things keep that from becoming a licence to delete. A wrong *output*
    on a real owner is a typo the model can see and fix, so it survives. And
    an interface a requirement binds to through `interface_size:<id>` is
    load-bearing, so it survives dangling and the designer is made to fix it.
    """

    @staticmethod
    def _document(interfaces):
        return {
            "components": [
                {
                    "id": "c",
                    "features": [{"id": "plate", "kind": "box"}],
                    "interfaces": interfaces,
                }
            ]
        }

    @staticmethod
    def _measuring(identifier):
        return type(
            "R", (), {
                "requirements": (
                    {"measurement": f"interface_size:{identifier}"},
                )
            }
        )()

    def _interfaces(self, document):
        return [i["id"] for i in document["components"][0]["interfaces"]]

    def test_an_owner_that_never_existed_is_dropped(self) -> None:
        from forge_roles.library import _normalise_document

        document, notes = _normalise_document(self._document([
            {"id": "ghost_port", "type": "bore", "geometry": "ghost.bore"},
            {"id": "face", "type": "planar_mount", "geometry": "plate.top"},
        ]))
        self.assertEqual(self._interfaces(document), ["face"])
        self.assertTrue(any("ghost_port" in note for note in notes), notes)

    def test_a_measured_interface_survives_dangling(self) -> None:
        from forge_roles.library import _normalise_document

        document, notes = _normalise_document(
            self._document([
                {"id": "shaft_port", "type": "bore", "geometry": "ghost.bore"},
            ]),
            self._measuring("shaft_port"),
        )
        self.assertEqual(self._interfaces(document), ["shaft_port"])
        self.assertEqual(notes, [])

    def test_a_wrong_output_on_a_real_owner_survives(self) -> None:
        """`plate` is there and publishes something; which face was meant is
        a question only the author can answer, and the port is a real claim
        about the part."""
        from forge_roles.library import _normalise_document

        document, notes = _normalise_document(self._document([
            {"id": "rim", "type": "bore", "geometry": "plate.rim"},
        ]))
        self.assertEqual(self._interfaces(document), ["rim"])
        self.assertEqual(notes, [])

    def test_a_renamed_owner_is_reconciled_rather_than_dropped(self) -> None:
        """Step 3 runs first, and its repair must not be undone by 3b."""
        from forge_roles.library import _normalise_document

        document, notes = _normalise_document({
            "components": [
                {
                    "id": "c",
                    "features": [
                        {"id": "pivot_hole", "kind": "hole", "role": "pivot"},
                    ],
                    "interfaces": [
                        {"id": "port", "type": "bore",
                         "geometry": "pivot_hole.bore"},
                    ],
                }
            ]
        })
        self.assertEqual(self._interfaces(document), ["port"])
        self.assertEqual(
            document["components"][0]["interfaces"][0]["geometry"],
            "pivot.bore",
        )
        self.assertTrue(notes)

    def test_the_real_fixture_keeps_every_interface(self) -> None:
        from forge_roles.library import _normalise_document

        before = copy.deepcopy(DESIGNER_VALID["document"])
        after, _ = _normalise_document(before)
        self.assertEqual(
            [
                [i["id"] for i in c.get("interfaces", [])]
                for c in after["components"]
            ],
            [
                [i["id"] for i in c.get("interfaces", [])]
                for c in DESIGNER_VALID["document"]["components"]
            ],
        )


class PartialAnswersAreWorthKeeping(unittest.TestCase):
    """All-or-nothing rejection, applied where it does not belong.

    Both of these roles used to discard a whole good answer over one bad
    entry. Neither entry was load-bearing, and both rejections cost a repair
    round at minutes per call -- on the two roles that sit either side of the
    designer, where the user is already waiting.
    """

    def test_one_blank_question_does_not_lose_the_rest(self) -> None:
        from forge_roles.library import ClarificationPrioritiser

        questions = ClarificationPrioritiser().parse({
            "questions": [
                {"id": "UNK_LOAD", "question": "How heavy is the load?",
                 "why": "sizes everything", "priority": 0.9},
                {"id": "UNK_FIT", "question": "", "why": "", "priority": 0.5},
                {"id": "UNK_ENV", "question": "Indoors or out?",
                 "why": "material choice", "priority": 0.4},
            ]
        })
        # The blank one's unknown stays unanswered, stays critical, and still
        # blocks release -- so nothing is lost by not asking it.
        self.assertEqual(
            [q.identifier for q in questions], ["UNK_LOAD", "UNK_ENV"])

    def test_questions_that_are_all_blank_are_still_sent_back(self) -> None:
        from forge_roles.library import ClarificationPrioritiser

        with self.assertRaises(RoleOutputError):
            ClarificationPrioritiser().parse({
                "questions": [
                    {"id": "A", "question": "", "why": "", "priority": 1.0},
                    {"id": "B", "question": "  ", "why": "", "priority": 0.5},
                ]
            })

    def test_a_malformed_patch_does_not_discard_an_abandon_reason(self) -> None:
        """The reason is the most useful thing the analyst produces: it is
        what tells the user the design needs a different construction."""
        proposal = FailureAnalyst().parse({
            "diagnosis": "the bore cannot fit in the wall",
            "strategy": "none",
            "abandon": True,
            "abandon_reason": "the part needs a thicker boss, not an edit.",
            "patches": [{"op": "replace", "value": 1}],
        })
        self.assertTrue(proposal.abandon)
        self.assertIn("thicker boss", proposal.abandon_reason)

    def test_a_malformed_patch_without_abandon_is_still_sent_back(self) -> None:
        """A patch set is atomic -- the analyst reasoned about the edits
        together -- so half of one is not an answer."""
        with self.assertRaises(RoleOutputError):
            FailureAnalyst().parse({
                "diagnosis": "d",
                "strategy": "s",
                "patches": [
                    {"op": "replace", "pointer": "/a", "value": 1},
                    {"op": "replace", "value": 1},
                ],
            })


class AnOrphanedParameterIsWiredWhereItPlainlyBelongs(unittest.TestCase):
    """The check found the site and then asked the model to make the edit.

    Observed live, twice, on a spacer block: `fillet_radius` was declared,
    measured by a requirement, and written out by hand as a bare 2 mm on the
    union's `blend_radius`. Forge located that literal exactly -- the hint
    named the field -- and then spent three designer attempts and
    twenty-eight minutes asking a three-billion-parameter model on a laptop
    to perform the substitution, received the identical answer twice, and
    ended with no part.

    Substituting the reference moves no geometry: the number is the same on
    both sides. What it changes is that the requirement measures the part
    instead of reading back the number the model typed.
    """

    @staticmethod
    def _measuring(*names):
        return type("R", (), {"requirements": tuple(
            {"id": f"R{index}", "measurement": f"parameter:{name}"}
            for index, name in enumerate(names)
        )})()

    def test_the_lone_matching_literal_is_wired_up(self) -> None:
        document = {"components": [{
            "id": "spacer",
            "parameters": [
                {"id": "fillet_radius", "value": {"magnitude": 2, "unit": "mm"}},
            ],
            "features": [
                {"id": "base", "kind": "box",
                 "parameters": {"size": {"vector": [30, 30, 4], "unit": "mm"}}},
                {"id": "body", "kind": "union", "inputs": ["base", "post"],
                 "parameters": {
                     "blend_radius": {"magnitude": 2, "unit": "mm"}}},
            ],
        }]}
        notes, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document, requirements=self._measuring("fillet_radius"))
        blend = document["components"][0]["features"][1]["parameters"]
        self.assertEqual(blend["blend_radius"], {"expression": "fillet_radius"})
        self.assertTrue(any("fillet_radius" in note for note in notes), notes)

    def test_two_candidate_literals_are_still_a_judgement(self) -> None:
        """A 2 mm fillet in a part that also has a 2 mm wall does not say
        which 2 the parameter means, and wiring the wrong one would drive the
        wrong feature from the wrong requirement."""
        document = {"components": [{
            "id": "s",
            "parameters": [
                {"id": "fillet_radius", "value": {"magnitude": 2, "unit": "mm"}},
            ],
            "features": [
                {"id": "a", "kind": "union",
                 "parameters": {"blend_radius": {"magnitude": 2, "unit": "mm"}}},
                {"id": "b", "kind": "box",
                 "parameters": {"wall": {"magnitude": 2, "unit": "mm"}}},
            ],
        }]}
        _, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document, requirements=self._measuring("fillet_radius"))
        self.assertTrue(problems)
        self.assertIn("fillet_radius", " ".join(problems))
        self.assertEqual(
            document["components"][0]["features"][0]["parameters"][
                "blend_radius"],
            {"magnitude": 2, "unit": "mm"},
            "nothing may be rewritten on the way to asking",
        )

    def test_the_unit_has_to_match_too(self) -> None:
        """2 mm and 2 degrees are not the same 2."""
        document = {"components": [{
            "id": "s",
            "parameters": [{"id": "gap", "value": {"magnitude": 2, "unit": "mm"}}],
            "features": [
                {"id": "a", "kind": "revolve",
                 "parameters": {"angle": {"magnitude": 2, "unit": "deg"}}},
            ],
        }]}
        _, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document, requirements=self._measuring("gap"))
        self.assertTrue(problems)

    def test_two_orphans_wanting_one_slot_are_not_split_silently(self) -> None:
        document = {"components": [{
            "id": "s",
            "parameters": [
                {"id": "fillet_radius", "value": {"magnitude": 2, "unit": "mm"}},
                {"id": "edge_break", "value": {"magnitude": 2, "unit": "mm"}},
            ],
            "features": [
                {"id": "a", "kind": "union",
                 "parameters": {"blend_radius": {"magnitude": 2, "unit": "mm"}}},
            ],
        }]}
        _, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document,
            requirements=self._measuring("fillet_radius", "edge_break"))
        self.assertTrue(problems)

    def test_a_parameter_already_driving_geometry_is_left_alone(self) -> None:
        document = {"components": [{
            "id": "s",
            "parameters": [
                {"id": "fillet_radius", "value": {"magnitude": 2, "unit": "mm"}},
            ],
            "features": [
                {"id": "a", "kind": "union",
                 "parameters": {
                     "blend_radius": {"expression": "fillet_radius"}}},
            ],
        }]}
        notes, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document, requirements=self._measuring("fillet_radius"))
        self.assertEqual(notes, [])


class OneBindingCarriesOneClaim(unittest.TestCase):
    """Five requirements measuring `mass`, and a hint about bounding boxes.

    Observed live on the spacer block. The model wanted to talk about the
    weight of the base, the post, the bore and the mounting holes; Forge's
    vocabulary has no way to say any of that, so it wrote `mass` five times.
    The check caught the contradiction correctly -- only one number can be
    the finished part's mass -- and then explained `bounding_box_z` to it,
    because the explanation was a fixed paragraph that ignored which binding
    had actually collided. The model could not act on advice about a field it
    had not used, returned the identical answer twice, and the run ended
    after thirteen minutes with no requirements at all.
    """

    BRIEF = (
        "A 3D-printed PLA spacer block. The base is a 30 mm square plate 4 mm "
        "thick. It must weigh no more than 8 g. It carries no load."
    )

    @staticmethod
    def _mass(identifier, comparison, magnitude):
        return {
            "id": identifier, "statement": identifier, "measurement": "mass",
            "comparison": comparison,
            "threshold": {"magnitude": magnitude, "unit": "g"},
        }

    def _normalised(self, requirements):
        from forge_roles.library import _normalise_requirements

        return _normalise_requirements(
            {"risk_class": "low", "requirements": requirements,
             "assumptions": [], "unknowns": []},
            self.BRIEF,
        )

    @staticmethod
    def _as_supplied(requirements):
        """The answer's own claims, without the claims Forge adds.

        This brief calls the plate square, so Forge now claims both extents
        of it -- rightly, and orthogonally to everything this class is about,
        which is what happens when several claims collide on one binding.
        `SquareMeansBothSides` covers the addition itself. And its weight is
        limited, so Forge claims nothing is sealed inside it:
        `NothingSealedInsideAPartTheBriefDoesNotHollow` covers that.
        """
        return [
            r for r in requirements
            if not str(r.get("id", "")).startswith(
                ("REQ_BOUNDING_BOX", "REQ_NOTHING_SEALED_INSIDE"))
        ]

    def test_the_claim_the_brief_supports_keeps_the_binding(self) -> None:
        answer, notes, retired = self._normalised([
            self._mass("REQ_BASE_MASS", "equals", 3.2),
            self._mass("REQ_POST_MASS", "equals", 1.4),
            self._mass("REQ_TOTAL_MASS", "at_most", 8),
        ])
        bound = {
            r["id"]: r.get("measurement") for r in answer["requirements"]
        }
        # 8 g is the only weight the user wrote, so that is the one claim
        # about the finished part's mass.
        self.assertEqual(bound["REQ_TOTAL_MASS"], "mass")
        self.assertIsNone(bound["REQ_BASE_MASS"])
        self.assertIsNone(bound["REQ_POST_MASS"])
        self.assertEqual(retired, {"REQ_BASE_MASS", "REQ_POST_MASS"})
        self.assertTrue(notes)

    def test_the_unbound_ones_keep_their_statements(self) -> None:
        """Unbind, don't delete. The reader should see that the model made
        claims Forge cannot check, not silently lose them."""
        answer, _, _ = self._normalised([
            self._mass("REQ_BASE_MASS", "equals", 3.2),
            self._mass("REQ_TOTAL_MASS", "at_most", 8),
        ])
        self.assertEqual(len(self._as_supplied(answer["requirements"])), 2)
        kept = [
            r for r in answer["requirements"] if r["id"] == "REQ_BASE_MASS"
        ][0]
        self.assertEqual(kept["threshold"]["magnitude"], 3.2)

    def test_candidates_that_agree_keep_the_least_strict(self) -> None:
        """The brief gives one weight, and the model attached it to more than
        one of its five mass requirements -- an `equals` and an `at_most`
        saying the same thing. They do not disagree, so there is nothing to
        guess: `equals 8 g` implies `at_most 8 g`, and keeping the bound
        cannot fail a part the pin would have passed.

        The first version of this bailed on any tie, and the run died anyway
        on an answer whose candidates agreed.
        """
        answer, _, retired = self._normalised([
            self._mass("REQ_BASE_MASS", "equals", 8),
            self._mass("REQ_POST_MASS", "equals", 8),
            self._mass("REQ_TOTAL_MASS", "at_most", 8),
        ])
        bound = [
            r["id"] for r in answer["requirements"]
            if r.get("measurement") == "mass"
        ]
        self.assertEqual(bound, ["REQ_TOTAL_MASS"])
        self.assertEqual(retired, {"REQ_BASE_MASS", "REQ_POST_MASS"})

    def test_exactly_one_survives_however_many_shared_it(self) -> None:
        """The property that matters, whatever the model wrote: a singleton
        binding ends up on at most one requirement."""
        for comparisons in (
            ["equals"] * 5,
            ["equals", "at_most", "at_most", "equals", "at_most"],
            ["at_most", "equals"],
        ):
            with self.subTest(comparisons=comparisons):
                answer, _, _ = self._normalised([
                    self._mass(f"REQ_{index}", comparison, 8)
                    for index, comparison in enumerate(comparisons)
                ])
                bound = [
                    r for r in answer["requirements"]
                    if r.get("measurement") == "mass"
                ]
                self.assertEqual(len(bound), 1)
                self.assertEqual(
                    len(self._as_supplied(answer["requirements"])),
                    len(comparisons))

    def test_different_stated_figures_are_a_real_disagreement(self) -> None:
        """Two numbers the user wrote, attached to one binding, is a claim
        about what the part weighs that only the author can settle."""
        from forge_roles.library import _one_claim_per_binding

        notes, retired = _one_claim_per_binding(self.BRIEF, [
            {"id": "REQ_A", "statement": "a", "measurement": "bounding_box_z",
             "comparison": "equals",
             "threshold": {"magnitude": 4, "unit": "mm"}},
            {"id": "REQ_B", "statement": "b", "measurement": "bounding_box_z",
             "comparison": "at_most",
             "threshold": {"magnitude": 30, "unit": "mm"}},
        ])
        self.assertEqual(retired, set())
        self.assertEqual(notes, [])

    def test_the_prompt_says_a_singleton_binding_is_singular(self) -> None:
        """The cause, not the symptom: nothing told the model there is only
        one mass, so it used the binding five times, deterministically."""
        from forge_roles.library import _numbers_to_cover

        guidance = _numbers_to_cover(self.BRIEF)
        self.assertIn("WHOLE finished part", guidance)
        self.assertIn("at most one requirement", guidance)

    def test_a_conflict_the_brief_does_not_settle_is_still_asked(self) -> None:
        """No figure here is one the user wrote, so which of them is the
        part's mass is a judgement, and guessing would be inventing."""
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            RequirementsEngineer().parse(
                {"risk_class": "low", "assumptions": [], "unknowns": [],
                 "requirements": [
                     self._mass("REQ_A", "equals", 3.2),
                     self._mass("REQ_B", "at_most", 5.5),
                 ]},
                brief=self.BRIEF,
            )
        self.assertTrue(
            any("measure `mass`" in p for p in caught.exception.problems))

    def test_a_two_sided_range_is_nobody_s_mistake(self) -> None:
        answer, notes, retired = self._normalised([
            {"id": "REQ_LO", "statement": "at least", "measurement": "mass",
             "comparison": "at_least",
             "threshold": {"magnitude": 2, "unit": "g"}},
            {"id": "REQ_HI", "statement": "at most", "measurement": "mass",
             "comparison": "at_most",
             "threshold": {"magnitude": 8, "unit": "g"}},
        ])
        self.assertEqual(retired, set())
        self.assertEqual(
            [r.get("measurement")
             for r in self._as_supplied(answer["requirements"])
             if r.get("measurement") == "mass"],
            ["mass", "mass"],
        )

    def test_the_hint_is_about_the_binding_that_collided(self) -> None:
        from forge_roles.library import _what_that_binding_actually_means

        mass = _what_that_binding_actually_means("mass")
        self.assertIn("mass", mass)
        self.assertNotIn("bounding_box", mass)
        box = _what_that_binding_actually_means("bounding_box_z")
        self.assertIn("bounding_box", box)
        count = _what_that_binding_actually_means("feature_count:hole:mounting")
        self.assertIn("feature_count", count)


class TheMistakeIsUnrepresentable(unittest.TestCase):
    """The architectural answer to three dead runs on one brief.

    The model bound four or five requirements to `mass`, one per piece of the
    part, because it wanted to talk about the weight of the base and the post
    and the vocabulary has no way to say that. Every layer after the model did
    its job: the check caught it, the message explained it, the repair tried
    to settle it. The run died anyway, three times, because all of that
    happens *after* the answer exists -- and at 1.4 tokens a second an answer
    costs six minutes and there are three of them.

    Under grammar-constrained decoding the schema is not a description of a
    valid answer. It is the set of tokens the model may emit. `mass` is one
    number about one finished part; JSON already guarantees object keys are
    unique; so a named slot makes the mistake unemittable rather than caught.
    """

    def _transport(self):
        return RequirementsEngineer().output_schema()["properties"][
            "requirements"]

    def test_a_whole_part_measurement_has_exactly_one_slot(self) -> None:
        from forge_ir.measurements import SIMPLE_MEASUREMENTS

        whole = self._transport()["properties"]["whole_part"]
        self.assertEqual(
            sorted(whole["properties"]), sorted(SIMPLE_MEASUREMENTS))
        # No second home for a mass claim, and no room to invent one.
        self.assertFalse(whole["additionalProperties"])
        self.assertEqual(whole["type"], "object")

    def test_the_model_never_spells_a_binding(self) -> None:
        """`parameter:plate_thickness` cannot be typed as
        `parameters:plate_thickness` if it is never typed at all."""
        self.assertNotIn("measurement", json.dumps(self._transport()))

    def test_the_binding_comes_from_the_position(self) -> None:
        from forge_roles.library import _requirements_from_the_transport

        flat = _requirements_from_the_transport({
            "whole_part": {
                "mass": {"statement": "at most 8 g", "comparison": "at_most",
                         "threshold": {"magnitude": 8, "unit": "g"}},
            },
            "dimensions": [
                {"parameter": "plate_thickness", "statement": "4 mm",
                 "comparison": "equals",
                 "threshold": {"magnitude": 4, "unit": "mm"}},
            ],
            "counts": [
                {"feature_kind": "hole", "tag": "mounting",
                 "statement": "two of them", "comparison": "equals",
                 "threshold": {"magnitude": 2, "unit": ""}},
            ],
            "safety_factors": [
                {"against": "bearing", "statement": "margin of 2",
                 "comparison": "at_least",
                 "threshold": {"magnitude": 2, "unit": ""}},
            ],
        })
        self.assertEqual(
            [r["measurement"] for r in flat],
            ["mass", "parameter:plate_thickness",
             "feature_count:hole:mounting", "safety_factor:bearing"],
        )
        # Ids are Forge's, not the model's -- they were a free-form string
        # that several checks were re-parsing out of their own prose.
        self.assertEqual(
            [r["id"] for r in flat],
            ["REQ_MASS", "REQ_PLATE_THICKNESS",
             "REQ_MOUNTING_HOLE_COUNT", "REQ_SF_BEARING"],
        )

    def test_colliding_targets_still_get_distinct_ids(self) -> None:
        from forge_roles.library import _requirements_from_the_transport

        flat = _requirements_from_the_transport({"dimensions": [
            {"parameter": "width", "statement": "a", "comparison": "equals",
             "threshold": {"magnitude": 1, "unit": "mm"}},
            {"parameter": "width", "statement": "b", "comparison": "equals",
             "threshold": {"magnitude": 2, "unit": "mm"}},
        ]})
        self.assertEqual([r["id"] for r in flat], ["REQ_WIDTH", "REQ_WIDTH_2"])

    def test_the_old_flat_shape_is_still_accepted(self) -> None:
        """Fixtures, recorded runs and the repair conversation carry the old
        shape. A transport change is not a reason to invalidate a run somebody
        recorded last week."""
        result = RequirementsEngineer().parse(
            {"risk_class": "low", "assumptions": [], "unknowns": [],
             "requirements": [
                 {"id": "REQ_M", "statement": "at most 8 g",
                  "measurement": "mass", "comparison": "at_most",
                  "threshold": {"magnitude": 8, "unit": "g"}}]},
            brief="It must weigh no more than 8 g.",
        )
        # The one it was given, and Forge's own that the weight is not met
        # by air sealed inside.
        self.assertEqual([r["id"] for r in result.requirements],
                         ["REQ_M", "REQ_NOTHING_SEALED_INSIDE"])

    def test_the_answer_got_much_shorter(self) -> None:
        """At 1.4 tokens a second, length is the budget. The old transport
        spelled a binding and an id on every requirement; this one spells
        neither."""
        answer = {
            "risk_class": "low", "assumptions": [], "unknowns": [],
            "requirements": {
                "whole_part": {"mass": {
                    "statement": "The part shall weigh no more than 8 g.",
                    "comparison": "at_most",
                    "threshold": {"magnitude": 8, "unit": "g"}}},
                "dimensions": [
                    {"parameter": f"p{index}", "statement": "s",
                     "comparison": "equals",
                     "threshold": {"magnitude": index, "unit": "mm"}}
                    for index in range(8)
                ],
            },
        }
        self.assertLess(len(json.dumps(answer)) // 4, 500)


class TheDesignerSchemaForbidsWhatTheDecoderRefuses(unittest.TestCase):
    """Two constraints the decoder always enforced, moved into the grammar."""

    def _document(self):
        return ForgeIRDesigner().output_schema()["properties"]["document"]

    def test_a_part_is_one_component(self) -> None:
        self.assertEqual(
            self._document()["properties"]["components"]["maxItems"], 1)

    def test_a_parameter_declares_a_value_or_an_expression(self) -> None:
        """Both-present and neither-present were typeable on the most
        frequently emitted object in a document -- eight per simple part."""
        parameter = (
            self._document()["properties"]["components"]["items"]
            ["properties"]["parameters"]["items"]
        )
        self.assertEqual(
            parameter["oneOf"],
            [
                {"required": ["value"], "not": {"required": ["expression"]}},
                {"required": ["expression"], "not": {"required": ["value"]}},
            ],
        )

    def test_the_canonical_contract_is_untouched(self) -> None:
        """Only the designer's private copy is tightened; a stored document
        with two components still decodes."""
        from forge_ir import document_schema

        components = document_schema()["properties"]["components"]
        self.assertNotIn("maxItems", components)


class ACutterIsWhateverTheCatalogueSaysItIs(unittest.TestCase):
    """The hand-written list had drifted in both directions, and the omission
    produced silently wrong geometry rather than a rejection."""

    def test_the_patterns_the_guide_teaches_are_recognised(self) -> None:
        from forge_roles.library import _consumes_a_solid

        kinds = _consumes_a_solid()
        # The authoring guide teaches four bolt holes as a cylinder, two
        # `pattern_linear`s and a `subtract`. Unrecognised, two terminal
        # patterns were unioned into the body instead of chained -- welding
        # the cutter in, so the part measured right and had no holes.
        for kind in ("pattern_linear", "pattern_circular", "mirror",
                     "transform", "hole", "subtract", "union"):
            self.assertIn(kind, kinds)

    def test_kinds_that_do_not_exist_are_gone(self) -> None:
        from forge_ir.features import FEATURE_SPECS
        from forge_roles.library import _consumes_a_solid

        # `fillet` and `chamfer` were in the list and are not feature kinds
        # at all -- a fillet is `blend_radius` on a boolean.
        for kind in _consumes_a_solid():
            self.assertIn(kind, FEATURE_SPECS)

    def test_a_primitive_does_not_consume_a_solid(self) -> None:
        from forge_roles.library import _consumes_a_solid

        for kind in ("box", "cylinder", "sphere"):
            self.assertNotIn(kind, _consumes_a_solid())


class ACountIsWrittenWithTheComparisonTheSchemaAllows(unittest.TestCase):
    """`exactly` is not in the comparison enum, so the auto-tagging repair
    added yesterday could never once have run: `_how_many_of_each_tag`
    returned {} for every schema-valid answer, and four correct untagged
    holes fell straight through to the rejection."""

    def test_equals_reaches_the_count(self) -> None:
        from forge_roles.library import _how_many_of_each_tag

        wanted = _how_many_of_each_tag(type("R", (), {"requirements": (
            {"measurement": "feature_count:hole:mounting",
             "comparison": "equals",
             "threshold": {"magnitude": 4, "unit": ""}},
        )})())
        self.assertEqual(wanted, {("hole", "mounting"): 4})

    def test_the_comparison_used_is_one_the_schema_permits(self) -> None:
        from forge_ir.spec import _requirement_schema

        allowed = _requirement_schema()["properties"]["comparison"]["enum"]
        self.assertIn("equals", allowed)
        self.assertNotIn("exactly", allowed)


class AHoleDrilledThroughAirIsReAimed(unittest.TestCase):
    """The defect that blocked the first run ever to produce a part.

    Plate, post, a 2 mm fillet, three holes, every dimension measured
    correct -- and both mounting holes at z = 5 with `axis: [0, 1, 0]`, which
    is above the plate and outside the post. They drilled through open air,
    contributed no surface, and the part had no mounting holes in it.

    The model was asked to fix it and could not: 275 seconds over two
    attempts, an invalid patch set, then the identical proposal, which ended
    the run. Forge can settle it in under a millisecond, because a
    through-hole exists to pass through material and `axis` has a documented
    default that is also the build direction.
    """

    @staticmethod
    def _hole(identifier, diameter, position, axis, inputs, tags=None):
        feature = {
            "id": identifier, "kind": "hole", "inputs": inputs,
            "parameters": {
                "diameter": {"expression": diameter, "unit": "mm"},
                "position": {"vector": position, "unit": "mm"},
                "axis": axis,
            },
        }
        if tags:
            feature["tags"] = tags
        return feature

    def _payload(self, mounting_axis, **extra):
        return {
            "schema_version": "1.0.0", "revision": 1,
            "document_id": "DOC_T", "project_id": "PRJ_T", "name": "Spacer",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [], "risk_class": "low",
            "components": [{
                "id": "spacer", "name": "Spacer", "material": "pla_fdm",
                "parameters": [
                    {"id": name, "value": {"magnitude": value, "unit": "mm"}}
                    for name, value in (
                        ("plate", 30.0), ("thickness", 4.0),
                        ("post_d", 12.0), ("post_h", 10.0), ("mh", 3.0),
                    )
                ],
                "features": [
                    {"id": "base", "kind": "box", "parameters": {
                        "size": {"vector": ["plate", "plate", "thickness"],
                                 "unit": "mm"}, "centered": True}},
                    {"id": "post", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "post_d", "unit": "mm"},
                        "height": {"expression": "post_h", "unit": "mm"},
                        "origin": {"vector": [0, 0, "thickness / 2"],
                                   "unit": "mm"}}},
                    {"id": "body", "kind": "union", "inputs": ["base", "post"]},
                    self._hole("mounting_hole_1", "mh", [10, 0, 5],
                               mounting_axis, ["body"], ["mounting"], **extra),
                ],
            }],
        }

    def _orchestrator(self):
        from forge_models import ScriptedProvider
        from forge_orchestrator import Orchestrator, OrchestratorConfig

        return Orchestrator(ScriptedProvider([]), config=OrchestratorConfig())

    def _run_it(self, payload):
        import json as _json

        from forge_ir import Document
        from forge_orchestrator.run import DesignRun

        orchestrator = self._orchestrator()
        document = Document.from_json(_json.dumps(payload))
        report = orchestrator._verify(document, "spacer")  # noqa: SLF001
        run = DesignRun("a spacer")
        settled = orchestrator._put_the_holes_back_in_the_part(  # noqa: SLF001
            run, payload, document, report)
        return orchestrator, report, run, settled

    def test_the_hole_that_missed_is_aimed_along_z(self) -> None:
        payload = self._payload([0, 1, 0])
        orchestrator, before, run, settled = self._run_it(payload)
        self.assertEqual(before.overall_status, Status.FAIL)
        self.assertIn(
            "mounting_hole_1",
            before.measurements["part"]["features_without_a_surface"],
        )
        self.assertIsNotNone(settled)
        patched, document, _ = settled
        hole = patched["components"][0]["features"][3]
        self.assertEqual(hole["parameters"]["axis"], [0.0, 0.0, 1.0])

        after = orchestrator._verify(document, "spacer")  # noqa: SLF001
        self.assertEqual(after.overall_status, Status.PASS)
        self.assertEqual(
            after.measurements["part"]["features_without_a_surface"], [])
        self.assertTrue(after.measurements["part"]["holes"][0]["present"])

    def test_the_repair_is_recorded_as_forge_s_own(self) -> None:
        """A document that differs from what the model wrote has to say so."""
        _, _, run, settled = self._run_it(self._payload([0, 1, 0]))
        self.assertIsNotNone(settled)
        self.assertEqual(run.repairs[-1].trigger, "geometry")
        self.assertIn("no material", run.repairs[-1].diagnosis)
        self.assertTrue(
            any("mounting_hole_1" in event.summary for event in run.events))

    def test_a_hole_already_aimed_along_z_is_left_alone(self) -> None:
        """Then it is in the wrong place rather than pointed the wrong way,
        and where it was meant to go is not something Forge knows."""
        payload = self._payload([0, 0, 1])
        payload["components"][0]["features"][3]["parameters"]["position"] = {
            "vector": [40, 0, 0], "unit": "mm"}  # outside the plate entirely
        _, before, _, settled = self._run_it(payload)
        self.assertEqual(before.overall_status, Status.FAIL)
        self.assertIsNone(settled)

    def test_a_blind_hole_is_left_to_the_analyst(self) -> None:
        """A counterbored or blind hole in mid-air is a positioning mistake,
        and re-aiming it would move material Forge was not asked to move."""
        payload = self._payload([0, 1, 0])
        payload["components"][0]["features"][3]["parameters"]["depth"] = {
            "magnitude": 2.0, "unit": "mm"}
        _, _, _, settled = self._run_it(payload)
        self.assertIsNone(settled)

    def test_a_part_whose_holes_are_all_present_is_untouched(self) -> None:
        payload = self._payload([0, 0, 1])
        orchestrator, report, run, settled = self._run_it(payload)
        self.assertEqual(report.overall_status, Status.PASS)
        self.assertIsNone(settled)
        self.assertEqual(run.repairs, [])


class AMarginNeedsALoadToBeAMarginOf(unittest.TestCase):
    """`safety_factor:bearing` on a brief that says there is no load case.

    Nothing can compute a bearing margin without a load, so the requirement
    reported BLOCKED and stood between a finished part and its release. Forge
    already dropped the load *question* from that brief; the margin
    requirement was the half it missed.
    """

    NO_LOAD = (
        "A printed PLA spacer. It must weigh no more than 8 g. It carries no "
        "load - it is a printed spacer, so there is no load case."
    )
    LOADED = "A steel bracket carrying 300 N downwards at the bore."

    @staticmethod
    def _margin():
        return {
            "id": "REQ_SF_BEARING", "statement": "a margin of 2",
            "measurement": "safety_factor:bearing", "comparison": "at_least",
            "threshold": {"magnitude": 2.0, "unit": ""},
        }

    def _normalise(self, brief, requirements):
        from forge_roles.library import _normalise_requirements

        return _normalise_requirements(
            {"risk_class": "low", "assumptions": [], "unknowns": [],
             "requirements": requirements},
            brief,
        )

    def test_the_margin_goes_when_there_is_no_load_case(self) -> None:
        answer, notes, _ = self._normalise(self.NO_LOAD, [self._margin()])
        # The brief also states a weight, so the mass requirement Forge adds
        # for that is expected here -- and, the weight being limited, that
        # nothing is sealed inside; what must be gone is the margin.
        self.assertEqual(
            [r["id"] for r in answer["requirements"]],
            ["REQ_MASS", "REQ_NOTHING_SEALED_INSIDE"])
        self.assertTrue(any("no load" in note for note in notes), notes)

    def test_the_margin_stays_when_there_is_a_load(self) -> None:
        answer, _, _ = self._normalise(self.LOADED, [self._margin()])
        self.assertEqual(
            [r["id"] for r in answer["requirements"]], ["REQ_SF_BEARING"])


class TheWeightTheBriefStatesGetsChecked(unittest.TestCase):
    """The model left the one whole-part mass slot empty and the run finished
    with the weight budget unchecked -- on a printed part, where it is the
    requirement a user is most likely to care about."""

    def _normalise(self, brief, requirements=None):
        from forge_roles.library import _normalise_requirements

        return _normalise_requirements(
            {"risk_class": "low", "assumptions": [], "unknowns": [],
             "requirements": requirements or []},
            brief,
        )

    def test_a_stated_limit_is_bound(self) -> None:
        answer, notes, _ = self._normalise(
            "A printed spacer. It must weigh no more than 8 g.")
        bound = [r for r in answer["requirements"]
                 if r.get("measurement") == "mass"]
        self.assertEqual(len(bound), 1)
        self.assertEqual(bound[0]["comparison"], "at_most")
        self.assertEqual(bound[0]["threshold"],
                         {"magnitude": 8.0, "unit": "g"})
        self.assertTrue(any("REQ_MASS" in note for note in notes), notes)

    def test_a_bare_weight_is_not_guessed_at(self) -> None:
        """"Weighs 8 g" might be a target. Which way the limit runs is the
        author's to say, so nothing is filled in."""
        answer, notes, _ = self._normalise("A printed spacer that weighs 8 g.")
        self.assertEqual(answer["requirements"], [])
        self.assertEqual(notes, [])

    def test_two_weights_are_not_guessed_at_either(self) -> None:
        answer, _, _ = self._normalise(
            "A spacer no more than 8 g with a 20 g counterweight.")
        self.assertEqual(answer["requirements"], [])

    def test_a_mass_the_model_bound_itself_is_not_duplicated(self) -> None:
        answer, _, _ = self._normalise(
            "It must weigh no more than 8 g.",
            [{"id": "REQ_M", "statement": "mass", "measurement": "mass",
              "comparison": "at_most",
              "threshold": {"magnitude": 8, "unit": "g"}}],
        )
        self.assertEqual(
            [r["id"] for r in answer["requirements"]
             if r.get("measurement") == "mass"], ["REQ_M"])


class AParameterTheDesignWroteOutByHandIsDeclared(unittest.TestCase):
    """Nine parameters named, eight declared, and the run died over the ninth.

    The requirements named `fillet_thickness`; the design wrote the fillet as
    a literal 2 mm on the union's `blend_radius` and never declared the
    parameter. Two designer attempts, twenty-five minutes, the same answer
    twice, no part.

    Both halves of the fix were already in hand and neither is invented: the
    number is the requirement's own threshold, which came from the brief, and
    the place it belongs is the single field holding exactly that number.
    This is the mirror of the orphan wiring -- the same question asked from
    the other end -- so the two share their uniqueness rules.
    """

    PAIRS = [
        ("plate_size_x", 30.0), ("plate_thickness", 4.0),
        ("post_diameter", 12.0), ("fillet_thickness", 2.0),
    ]

    def _requirements(self):
        """Built directly rather than through the role, so this test exercises
        the repair and not the requirements engineer's own checks."""
        from forge_roles.library import (
            RequirementSet, _fill_requirement_defaults,
        )

        return RequirementSet(
            requirements=tuple(
                _fill_requirement_defaults({
                    "id": f"REQ_{name.upper()}", "statement": name,
                    "measurement": f"parameter:{name}",
                    "comparison": "equals",
                    "threshold": {"magnitude": value, "unit": "mm"},
                })
                for name, value in self.PAIRS
            ),
            assumptions=(), unknowns=(),
        )

    def _payload(self, blend):
        declared = [
            {"id": name, "value": {"magnitude": value, "unit": "mm"}}
            for name, value in self.PAIRS if name != "fillet_thickness"
        ]
        return {"components": [{
            "id": "c", "parameters": declared,
            "features": [
                {"id": "base", "kind": "box", "parameters": {
                    "size": {"vector": ["plate_size_x", "plate_size_x",
                                        "plate_thickness"], "unit": "mm"}}},
                {"id": "post", "kind": "cylinder", "parameters": {
                    "diameter": {"expression": "post_diameter",
                                 "unit": "mm"}}},
                {"id": "body", "kind": "union", "inputs": ["base", "post"],
                 "parameters": {"blend_radius": blend}},
            ],
        }]}

    def _declare(self, payload):
        from forge_roles.library import _declare_what_the_requirements_measure

        return _declare_what_the_requirements_measure(
            payload, self._requirements())

    def test_the_lone_literal_is_declared_and_wired(self) -> None:
        payload = self._payload({"magnitude": 2.0, "unit": "mm"})
        notes = self._declare(payload)
        component = payload["components"][0]
        self.assertIn(
            {"id": "fillet_thickness",
             "value": {"magnitude": 2.0, "unit": "mm"}},
            component["parameters"],
        )
        self.assertEqual(
            component["features"][2]["parameters"]["blend_radius"],
            {"expression": "fillet_thickness"},
        )
        self.assertTrue(any("fillet_thickness" in n for n in notes), notes)

    def test_the_value_is_the_requirement_s_own_threshold(self) -> None:
        """Not read off the geometry, so a design that wrote the wrong number
        is still sent back rather than having its mistake enshrined."""
        payload = self._payload({"magnitude": 9.0, "unit": "mm"})
        self.assertEqual(self._declare(payload), [])
        self.assertNotIn(
            "fillet_thickness",
            [p["id"] for p in payload["components"][0]["parameters"]],
        )

    def test_nothing_is_declared_without_somewhere_to_wire_it(self) -> None:
        """Declaring alone would only move the failure: the parameter would
        be an orphan, and the orphan check would reject it for driving no
        geometry."""
        payload = self._payload({"expression": "something_else"})
        self.assertEqual(self._declare(payload), [])

    def test_an_ambiguous_number_is_left_to_the_designer(self) -> None:
        payload = self._payload({"magnitude": 2.0, "unit": "mm"})
        payload["components"][0]["features"].append(
            {"id": "rib", "kind": "box", "parameters": {
                "wall": {"magnitude": 2.0, "unit": "mm"}}})
        self.assertEqual(self._declare(payload), [])

    def test_the_unit_has_to_match(self) -> None:
        payload = self._payload({"magnitude": 2.0, "unit": "deg"})
        self.assertEqual(self._declare(payload), [])

    def test_a_design_that_declared_everything_is_untouched(self) -> None:
        payload = self._payload({"expression": "fillet_thickness"})
        payload["components"][0]["parameters"].append(
            {"id": "fillet_thickness",
             "value": {"magnitude": 2.0, "unit": "mm"}})
        before = copy.deepcopy(payload)
        self.assertEqual(self._declare(payload), [])
        self.assertEqual(payload, before)


class TheVocabulariesForgeChecksAreClosedInTheSchema(unittest.TestCase):
    """`material` is checked against a list after the fact; a family name
    like "aluminium" parses, compiles, and is refused at measurement time
    after twelve minutes of generation."""

    def test_material_is_an_enum(self) -> None:
        from forge_analysis.materials import available

        material = (
            ForgeIRDesigner().output_schema()["properties"]["document"]
            ["properties"]["components"]["items"]["properties"]["material"]
        )
        self.assertEqual(material["enum"], list(available()))
        self.assertNotIn("type", material)

    def test_the_canonical_contract_still_takes_any_string(self) -> None:
        from forge_ir import document_schema

        material = (document_schema()["properties"]["components"]["items"]
                    ["properties"]["material"])
        self.assertEqual(material.get("type"), "string")

    def test_the_schema_did_not_balloon(self) -> None:
        """Enumerating `unit` too was tried and reverted: twenty-one entries
        across fifty-seven occurrences added three thousand tokens to every
        designer prompt, for a failure nobody has hit.

        Raised once, by 1000, for a new feature kind rather than a longer
        enumeration: `bend`, about 700 tokens, the first curved part a
        brief asked for having had no way to be drawn at all."""
        schema = json.dumps(ForgeIRDesigner().output_schema())
        self.assertLess(len(schema) // 4, 13000)


class ARejectedAnswerIsWrittenDown(unittest.TestCase):
    """Finding out what the model actually wrote cost a second
    twenty-five-minute run, twice. The run record now carries it."""

    def test_the_answer_reaches_the_failure_detail(self) -> None:
        from forge_models import ScriptedProvider
        from forge_roles import BriefInterpreter, RepairExhaustedError

        bad = {"summary": "", "part_kind": "p", "stated": [],
               "implied": [], "unstated": ["the load"]}
        with self.assertRaises(RepairExhaustedError) as caught:
            BriefInterpreter().run(ScriptedProvider([bad, bad, bad]),
                                   brief="anything")
        self.assertEqual(
            caught.exception.detail["rejected_answer"]["part_kind"], "p")
        json.dumps(caught.exception.as_dict())

    def test_every_earlier_answer_is_kept_too(self) -> None:
        """Claude's third answer failed for a fault Forge made; its first
        two were lost, and with them whether they had been right."""
        from forge_models import ScriptedProvider
        from forge_roles import BriefInterpreter, RepairExhaustedError
        from forge_orchestrator.run import _render_detail

        first = {"summary": "", "part_kind": "first", "stated": [],
                 "implied": [], "unstated": ["the load"]}
        second = {**first, "part_kind": "second"}
        with self.assertRaises(RepairExhaustedError) as caught:
            BriefInterpreter().run(ScriptedProvider([first, second, second]),
                                   brief="anything")
        detail = caught.exception.detail
        self.assertEqual(detail["rejected_answer"]["part_kind"], "second")
        self.assertEqual([a["part_kind"] for a in detail["earlier_answers"]],
                         ["first"])
        shown = "\n".join(_render_detail(detail))
        self.assertNotIn("'part_kind'", shown)
        self.assertIn("2 kept in run.json", shown)

    def test_a_runaway_answer_is_summarised_not_pasted(self) -> None:
        from forge_roles.base import _small_enough_to_keep

        # A whole design -- 150 000 characters is a large one -- is kept,
        # to be replayed; past that it is a runaway, and summarised.
        self.assertEqual(_small_enough_to_keep({"x": "y" * 150000}),
                         {"x": "y" * 150000})
        kept = _small_enough_to_keep({"x": "y" * 500000})
        self.assertIn("note", kept)
        self.assertNotIn("yyyy", json.dumps(kept))


class EveryProblemIsReportedInOneRound(unittest.TestCase):
    """Three attempts, one problem learned each time, eleven minutes apiece.

    Each check used to raise the moment it found something, so a round
    reported exactly one fault. Observed on the run that motivated this: a
    document whose two mounting holes were identical copies of the bore at
    the origin, and whose last two parameters were defined as themselves, was
    told three times that its parameters drove no geometry -- and never once
    that its feature graph was broken. It fixed nothing, because it was never
    told what was actually wrong.
    """

    BRIEF = (
        "A 3D-printed PLA spacer block. The base is a 30 mm square plate 4 mm "
        "thick. A 12 mm diameter post 10 mm tall stands in the middle of it, "
        "with a 2 mm fillet. A 5 mm hole runs through. Two 3 mm mounting "
        "holes 20 mm apart. It must weigh no more than 8 g. It carries no "
        "load - there is no load case."
    )
    PAIRS = [("plate_size_x", 30.0), ("plate_size_y", 30.0),
             ("plate_thickness", 4.0), ("post_diameter", 12.0),
             ("post_height", 10.0), ("fillet_thickness", 2.0),
             ("hole_diameter", 5.0), ("mounting_hole_diameter", 3.0),
             ("mounting_hole_distance", 20.0)]

    def _requirements(self):
        return RequirementsEngineer().parse(
            {"risk_class": "low", "assumptions": [], "unknowns": [],
             "requirements": {
                 "whole_part": {"mass": {
                     "statement": "8 g", "comparison": "at_most",
                     "threshold": {"magnitude": 8, "unit": "g"}}},
                 "dimensions": [
                     {"parameter": name, "statement": name,
                      "comparison": "equals",
                      "threshold": {"magnitude": value, "unit": "mm"}}
                     for name, value in self.PAIRS],
                 "counts": [{
                     "feature_kind": "hole", "tag": "mounting",
                     "statement": "two", "comparison": "equals",
                     "threshold": {"magnitude": 2, "unit": ""}}]}},
            brief=self.BRIEF)

    @staticmethod
    def _the_answer_from_the_run():
        """Verbatim from `rejected_answer` in the run record."""
        def hole(identifier):
            return {
                "id": identifier, "kind": "hole", "tags": ["mounting"],
                "parameters": {
                    "diameter": {"expression": "hole_diameter",
                                 "unit": "mm"},
                    "position": {"vector": [0, 0, "plate_thickness / 2"],
                                 "unit": "mm"},
                    "axis": [0.0, 0.0, 1.0], "fit": "clearance_normal"},
            }
        declared = [
            {"id": name, "value": {"magnitude": value, "unit": "mm"}}
            for name, value in [
                ("plate_size_x", 30.0), ("plate_size_y", 30.0),
                ("plate_thickness", 4.0), ("post_diameter", 12.0),
                ("post_height", 10.0), ("hole_diameter", 5.0)]
        ] + [
            # Defined as themselves -- a definition with no value in it.
            {"id": "mounting_hole_diameter",
             "value": {"expression": "mounting_hole_diameter", "unit": "mm"}},
            {"id": "mounting_hole_distance",
             "value": {"expression": "mounting_hole_distance", "unit": "mm"}},
            {"id": "fillet_thickness",
             "value": {"magnitude": 2.0, "unit": "mm"}},
        ]
        return {"rationale": "r", "document": {
            "name": "Spacer Block", "components": [{
                "id": "spacer_block", "parameters": declared,
                "features": [
                    {"id": "base", "kind": "box", "parameters": {
                        "size": {"vector": ["plate_size_x", "plate_size_y",
                                            "plate_thickness"], "unit": "mm"},
                        "centered": True}},
                    {"id": "post", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "post_diameter",
                                     "unit": "mm"},
                        "height": {"expression": "post_height", "unit": "mm"},
                        "origin": {"vector": [0, 0, "plate_thickness / 2"],
                                   "unit": "mm"}}},
                    {"id": "body", "kind": "union", "inputs": ["base", "post"],
                     "parameters": {
                         "blend_radius": {"expression": "fillet_thickness"}}},
                    hole("hole_1"), hole("hole_2"),
                ]}]}}

    def test_the_structural_fault_is_named_alongside_the_others(self) -> None:
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(
                self._the_answer_from_the_run(),
                requirements=self._requirements(),
                document_id="DOC_T", project_id="PRJ_T")
        joined = " ".join(caught.exception.problems)
        # The duplicate holes -- never mentioned once across three attempts.
        self.assertIn("same hole", joined)
        # And the orphaned parameters, which were all it used to say.
        self.assertIn("mounting_hole_diameter", joined)
        self.assertGreaterEqual(len(caught.exception.problems), 2)

    def test_a_good_design_still_passes_every_check(self) -> None:
        """Collecting must not make anything laxer."""
        answer = self._the_answer_from_the_run()
        component = answer["document"]["components"][0]
        component["parameters"] = [
            {"id": name, "value": {"magnitude": value, "unit": "mm"}}
            for name, value in self.PAIRS
        ]
        for index, (identifier, sign) in enumerate(
                (("hole_1", ""), ("hole_2", "-")), start=3):
            component["features"][index]["parameters"].update({
                "diameter": {"expression": "mounting_hole_diameter",
                             "unit": "mm"},
                "position": {
                    "vector": [f"{sign}mounting_hole_distance / 2", 0, 0],
                    "unit": "mm"},
            })
        component["features"][3]["inputs"] = ["body"]
        component["features"][4]["inputs"] = ["hole_1"]
        component["features"].append({
            "id": "bore", "kind": "hole", "inputs": ["hole_2"], "parameters": {
                "diameter": {"expression": "hole_diameter", "unit": "mm"},
                "position": {"vector": [0, 0, 0], "unit": "mm"},
                "axis": [0.0, 0.0, 1.0]}})
        draft = ForgeIRDesigner().parse(
            answer, requirements=self._requirements(),
            document_id="DOC_T", project_id="PRJ_T")
        self.assertEqual(len(draft.document.components), 1)


class AParameterDefinedAsItselfIsRefused(unittest.TestCase):
    """`mounting_hole_diameter = mounting_hole_diameter` -- a definition with
    no value in it, written twice in one document.

    The expression layer catches the cycle, but only when parameters are
    resolved, which happens at compile. So the document decoded cleanly, the
    designer was told about something else entirely, and the real fault was
    never named in three attempts.
    """

    @staticmethod
    def _document(parameters):
        return {
            "schema_version": "1.0.0", "revision": 1, "document_id": "D",
            "project_id": "P", "name": "S",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [], "risk_class": "low",
            "components": [{
                "id": "c", "name": "S", "material": "pla_fdm",
                "parameters": parameters,
                "features": [{"id": "b", "kind": "box", "parameters": {
                    "size": {"vector": ["t", "t", "t"], "unit": "mm"}}}],
            }],
        }

    def _decode(self, parameters):
        from forge_ir import Document

        return Document.from_json(json.dumps(self._document(parameters)))

    def test_a_direct_self_reference_is_caught_at_decode(self) -> None:
        from forge_ir import SchemaError, SchemaErrorGroup

        with self.assertRaises((SchemaError, SchemaErrorGroup)) as caught:
            self._decode([{"id": "t", "value": {"expression": "t",
                                                "unit": "mm"}}])
        self.assertIn("defined as itself", str(caught.exception))

    def test_a_self_reference_inside_arithmetic_is_caught_too(self) -> None:
        from forge_ir import SchemaError, SchemaErrorGroup

        with self.assertRaises((SchemaError, SchemaErrorGroup)):
            self._decode([{"id": "t", "value": {"expression": "t * 2",
                                                "unit": "mm"}}])

    def test_a_real_expression_chain_still_decodes(self) -> None:
        document = self._decode([
            {"id": "u", "value": {"magnitude": 3.0, "unit": "mm"}},
            {"id": "t", "value": {"expression": "u * 2", "unit": "mm"}},
        ])
        self.assertEqual(len(document.components), 1)

    def test_a_plain_value_still_decodes(self) -> None:
        document = self._decode(
            [{"id": "t", "value": {"magnitude": 4.0, "unit": "mm"}}])
        self.assertEqual(len(document.components), 1)


class HolesSpreadAlongTheAxisTheyAreDrilledDown(unittest.TestCase):
    """One field wrong, written twice, and the run died.

    The design was otherwise right: nine parameters, every value correct,
    base and post and a blended union correct, two mounting holes at the
    correct diameter, correctly spaced at +/- 20/2 and correctly tagged. The
    only fault was `axis: [1, 0, 0]` on holes offset along X -- so both lay
    on the line y=0, z=2, and the decoder correctly refused them as one hole.
    Three attempts, thirty-six minutes, no part.

    Forge already knew how to re-aim a hole; the repair just lived in the
    orchestrator's gate loop, which only ever runs on a document that already
    validated. A document refused at parse never reached it. That is the
    architectural fault this fixes: every repair Forge knows how to make has
    to be attempted before any rejection, not after some of them.
    """

    @staticmethod
    def _hole(identifier, x, axis):
        return {
            "id": identifier, "kind": "hole", "tags": ["mounting"],
            "parameters": {
                "diameter": {"expression": "d", "unit": "mm"},
                "position": {"vector": [x, 0, "t / 2"], "unit": "mm"},
                "axis": axis,
            },
        }

    def _reaim(self, features):
        from forge_roles.library import _re_aim_holes_that_became_one_line

        return _re_aim_holes_that_became_one_line(features)

    def test_holes_offset_along_x_are_re_aimed_down_z(self) -> None:
        features = [self._hole("mh1", "s / 2", [1.0, 0.0, 0.0]),
                    self._hole("mh2", "-s / 2", [1.0, 0.0, 0.0])]
        notes = self._reaim(features)
        for feature in features:
            self.assertEqual(
                feature["parameters"]["axis"], [0.0, 0.0, 1.0])
        self.assertTrue(any("one line" in note for note in notes), notes)

    def test_holes_offset_across_their_axis_are_left_alone(self) -> None:
        """Spread over x, drilled down z: two perfectly good holes."""
        features = [self._hole("mh1", "s / 2", [0.0, 0.0, 1.0]),
                    self._hole("mh2", "-s / 2", [0.0, 0.0, 1.0])]
        self.assertEqual(self._reaim(features), [])
        self.assertEqual(
            features[0]["parameters"]["axis"], [0.0, 0.0, 1.0])

    def test_identical_positions_are_a_judgement_not_a_repair(self) -> None:
        """Genuinely the same hole. Which one was meant to move somewhere
        else is not something Forge can know."""
        features = [self._hole("mh1", 0, [1.0, 0.0, 0.0]),
                    self._hole("mh2", 0, [1.0, 0.0, 0.0])]
        self.assertEqual(self._reaim(features), [])

    def test_the_positions_are_compared_as_written_never_evaluated(self) -> None:
        """`s / 2` and `-s / 2` are expressions, and no parameter table
        exists at this point. Two components spelled identically are equal
        whatever they resolve to, which is all this needs."""
        features = [self._hole("mh1", "spacing / 2", [1.0, 0.0, 0.0]),
                    self._hole("mh2", "-spacing / 2", [1.0, 0.0, 0.0])]
        self.assertTrue(self._reaim(features))

    def test_a_single_hole_is_never_touched(self) -> None:
        features = [self._hole("only", "s / 2", [1.0, 0.0, 0.0])]
        self.assertEqual(self._reaim(features), [])

    def test_opposite_senses_are_still_one_line(self) -> None:
        features = [self._hole("mh1", "s / 2", [1.0, 0.0, 0.0]),
                    self._hole("mh2", "-s / 2", [-1.0, 0.0, 0.0])]
        self.assertTrue(self._reaim(features))


class TheMaterialTheBriefNamesIsSet(unittest.TestCase):
    """Sixteen passing gates, every dimension right, and BLOCKED.

    `material` was empty, so there was no density, so the one requirement the
    user actually cares about -- "no more than 8 g" -- could not be computed
    at all. The brief's first five words are "A 3D-printed PLA spacer block".
    """

    class _Intent:
        def __init__(self, summary, stated):
            self.summary, self.stated = summary, stated

    class _Requirements:
        def __init__(self, requirements=()):
            self.requirements = requirements

    def _name(self, summary, stated, requirements=(), material=None):
        from forge_roles.library import _name_the_material_the_brief_names

        component = {"id": "c"}
        if material is not None:
            component["material"] = material
        payload = {"components": [component]}
        notes = _name_the_material_the_brief_names(
            payload, self._Intent(summary, stated),
            self._Requirements(requirements))
        return payload["components"][0].get("material"), notes

    def test_pla_names_the_only_pla_forge_knows(self) -> None:
        grade, notes = self._name(
            "A 3D-printed PLA spacer block", ("A 3D-printed PLA spacer",))
        self.assertEqual(grade, "pla_fdm")
        self.assertTrue(any("density" in note for note in notes), notes)

    def test_two_families_in_the_brief_are_a_judgement(self) -> None:
        grade, _ = self._name(
            "A steel bracket with an aluminium cover",
            ("steel bracket, aluminium cover",))
        self.assertIsNone(grade)

    def test_stainless_steel_is_one_family_not_two(self) -> None:
        """This test used to assert the opposite: that "stainless steel"
        names two families, because "steel" alone matched the carbon steel.
        It names one, stainless, and Forge knows one grade of it -- the same
        rule that makes "PLA" the PLA and "aluminium" the 6061-T6. A
        stainless collar came out with no material because of it."""
        grade, _ = self._name(
            "A stainless steel bracket", ("stainless steel bracket",))
        self.assertEqual(grade, "stainless_304")

    def test_a_family_name_buys_nothing_when_a_margin_depends_on_it(
        self,
    ) -> None:
        """The guide refuses to substitute a family for a grade because
        within a family the strength varies threefold. That argument is
        about strength, so it binds exactly where strength is measured."""
        grade, _ = self._name(
            "A PLA arm", ("PLA arm",),
            requirements=({"measurement": "safety_factor:bearing"},))
        self.assertIsNone(grade)

    def test_an_exact_grade_is_honoured_even_under_a_margin(self) -> None:
        grade, _ = self._name(
            "A pla_fdm arm", ("pla_fdm arm",),
            requirements=({"measurement": "safety_factor:bearing"},))
        self.assertEqual(grade, "pla_fdm")

    def test_a_brief_naming_no_material_sets_none(self) -> None:
        grade, notes = self._name("A bracket", ("a bracket",))
        self.assertIsNone(grade)
        self.assertEqual(notes, [])

    def test_a_material_the_designer_chose_is_untouched(self) -> None:
        grade, notes = self._name(
            "A PLA spacer", ("PLA",), material="steel_1018_cd")
        self.assertEqual(grade, "steel_1018_cd")
        self.assertEqual(notes, [])

    def test_every_grade_it_can_choose_is_one_forge_knows(self) -> None:
        from forge_analysis.materials import available

        for summary in ("A PLA part", "An aluminium part"):
            grade, _ = self._name(summary, (summary,))
            if grade is not None:
                self.assertIn(grade, available())


class TheBodyAFeatureWasObviouslyAppliedTo(unittest.TestCase):
    """A feature that names no input, where only one input was possible.

    Earned on a shaft collar: a `cylinder` and three `hole` features, every
    diameter and position right, the set screws correctly drilled down Y and
    X ninety degrees apart -- and not one hole said which solid it cut. Two
    attempts, the same answer twice, twenty-three minutes, no part. The
    schema had told it `expected 1, got 0`, which is a count rather than an
    instruction.

    Every timeline modeller applies a feature to the body so far. Naming the
    input is Forge's requirement, not the world's, and a model falls back on
    its prior the moment the shape in front of it is not the worked example.

    Both halves are tested, because a repair that fires everywhere is as bad
    as one that fires nowhere: one candidate is wiring, two is a question.
    """

    def _repair(self, features):
        from forge_roles.library import _give_each_feature_the_thing_it_acts_on

        return _give_each_feature_the_thing_it_acts_on(features)

    def _problems(self, features):
        from forge_roles.library import (
            _features_that_never_say_what_they_act_on,
        )

        return _features_that_never_say_what_they_act_on(features)

    @staticmethod
    def _hole(identifier, axis, inputs=None):
        feature = {
            "id": identifier, "kind": "hole",
            "parameters": {
                "diameter": {"magnitude": 4.0, "unit": "mm"},
                "position": {"vector": [0, 0, "length / 2"], "unit": "mm"},
                "axis": axis,
            },
        }
        if inputs is not None:
            feature["inputs"] = inputs
        return feature

    @staticmethod
    def _collar_body():
        return {
            "id": "body", "kind": "cylinder",
            "parameters": {
                "diameter": {"expression": "outer_diameter", "unit": "mm"},
                "height": {"expression": "length", "unit": "mm"},
            },
        }

    # -- the collar, as the model actually returned it ---------------------

    def test_a_flat_list_of_cutters_becomes_the_chain_it_meant(self) -> None:
        features = [
            self._collar_body(),
            self._hole("bore", [0.0, 0.0, 1.0]),
            self._hole("set_screw_hole_1", [0.0, 1.0, 0.0]),
            self._hole("set_screw_hole_2", [1.0, 0.0, 0.0]),
        ]
        notes = self._repair(features)
        self.assertEqual(features[1]["inputs"], ["body"])
        self.assertEqual(features[2]["inputs"], ["bore"])
        self.assertEqual(features[3]["inputs"], ["set_screw_hole_1"])
        self.assertEqual(len(notes), 1)
        self.assertIn("bore", notes[0])
        self.assertEqual(self._problems(features), [])

    def test_the_whole_collar_survives_normalisation_as_one_chain(self) -> None:
        """Through `_normalise_document`, where step 4 used to weld the
        cutters back into the body because none of them consumed anything."""
        from forge_roles.library import _normalise_document

        document, notes = _normalise_document({"components": [{
            "id": "collar",
            "features": [
                self._collar_body(),
                self._hole("bore", [0.0, 0.0, 1.0]),
                self._hole("set_screw_hole_1", [0.0, 1.0, 0.0]),
                self._hole("set_screw_hole_2", [1.0, 0.0, 0.0]),
            ],
        }]})
        features = document["components"][0]["features"]
        self.assertEqual(
            [f["id"] for f in features],
            ["body", "bore", "set_screw_hole_1", "set_screw_hole_2"],
            "no weld should have been added: there is one loose solid",
        )
        self.assertFalse(
            any(f["kind"] == "union" for f in features),
            "a union here would refill every hole",
        )

    # -- what it must refuse to guess --------------------------------------

    def test_two_loose_solids_are_welded_then_cut(self) -> None:
        """The pulley hub: a flange, a hub on it, and a bore naming neither.

        Neither solid is used by anything else, so they are welded whatever
        happens -- a part is one solid. Cut into one and then welded to the
        other, the hole would be refilled wherever it crosses the other; so
        the weld goes first, where the hole sits, and the hole cuts it."""
        features = [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "height": {"magnitude": 10.0, "unit": "mm"}}},
            self._hole("bore", [0.0, 0.0, 1.0]),
            self._hole("pin", [0.0, 0.0, 1.0]),
        ]
        notes = self._repair(features)
        self.assertEqual([f["id"] for f in features],
                         ["base", "post", "body", "bore", "pin"])
        self.assertEqual(features[2], {"id": "body", "kind": "union",
                                       "inputs": ["base", "post"]})
        self.assertEqual(features[3]["inputs"], ["body"])
        self.assertEqual(features[4]["inputs"], ["bore"],
                         "the next hole cuts the last, not a second weld")
        self.assertIn("welds them first", notes[0])
        self.assertEqual(self._problems(features), [])

    def test_a_solid_the_design_uses_later_is_a_question(self) -> None:
        """`post` is consumed further down: the design has a plan for it that
        Forge cannot see, so which solid the hole cuts stays a question."""
        features = [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "height": {"magnitude": 10.0, "unit": "mm"}}},
            self._hole("bore", [0.0, 0.0, 1.0]),
            {"id": "joined", "kind": "union", "inputs": ["bore", "post"]},
        ]
        self.assertEqual(self._repair(features), [])
        self.assertNotIn("inputs", features[2])
        problems = self._problems(features)
        self.assertEqual(len(problems), 1)
        self.assertIn("`base`", problems[0])
        self.assertIn("`post`", problems[0])
        self.assertIn("inputs", problems[0])

    def test_only_a_hole_welds_what_it_cuts(self) -> None:
        """A shell of the weld is a different part from a shell of one body."""
        features = [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "height": {"magnitude": 10.0, "unit": "mm"}}},
            {"id": "hollow", "kind": "shell", "parameters": {
                "thickness": {"magnitude": 1.0, "unit": "mm"}}},
        ]
        self.assertEqual(self._repair(features), [])
        self.assertEqual([f["id"] for f in features], ["base", "post", "hollow"])
        self.assertNotIn("inputs", features[2])

    def test_nothing_to_act_on_says_so(self) -> None:
        features = [self._hole("bore", [0.0, 0.0, 1.0])]
        self.assertEqual(self._repair(features), [])
        problems = self._problems(features)
        self.assertEqual(len(problems), 1)
        self.assertIn("nothing for it to act on", problems[0])

    def test_a_feature_that_named_its_input_is_untouched(self) -> None:
        features = [
            self._collar_body(),
            self._hole("bore", [0.0, 0.0, 1.0], inputs=["body"]),
        ]
        self.assertEqual(self._repair(features), [])
        self.assertEqual(features[1]["inputs"], ["body"])

    def test_a_feature_cannot_become_its_own_input(self) -> None:
        """The output is available after the feature consumes, never before."""
        features = [self._hole("only", [0.0, 0.0, 1.0])]
        self._repair(features)
        self.assertNotEqual(features[0].get("inputs"), ["only"])

    # -- the same certainty, away from holes and solids --------------------

    def test_an_extrude_after_one_profile_is_wired(self) -> None:
        features = [
            {"id": "pl", "kind": "datum_plane", "parameters": {"base": "XY"}},
            {"id": "pr", "kind": "profile_rectangle", "parameters": {
                "width": {"magnitude": 30.0, "unit": "mm"},
                "height": {"magnitude": 20.0, "unit": "mm"}}},
            {"id": "sol", "kind": "extrude", "parameters": {
                "distance": {"magnitude": 5.0, "unit": "mm"}}},
        ]
        self.assertEqual(len(self._repair(features)), 1)
        self.assertEqual(features[1]["inputs"], ["pl"])
        self.assertEqual(features[2]["inputs"], ["pr"])

    def test_one_datum_plane_carries_several_profiles(self) -> None:
        """A datum is a reference, not material: using it does not spend it."""
        features = [
            {"id": "pl", "kind": "datum_plane", "parameters": {"base": "XY"}},
            {"id": "a", "kind": "profile_circle", "parameters": {
                "diameter": {"magnitude": 20.0, "unit": "mm"}}},
            {"id": "b", "kind": "profile_circle", "parameters": {
                "diameter": {"magnitude": 10.0, "unit": "mm"}}},
        ]
        self._repair(features)
        self.assertEqual(features[1]["inputs"], ["pl"])
        self.assertEqual(features[2]["inputs"], ["pl"])

    def test_a_pattern_after_one_solid_is_wired(self) -> None:
        features = [
            {"id": "pin", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 4.0, "unit": "mm"},
                "height": {"magnitude": 10.0, "unit": "mm"}}},
            {"id": "ring", "kind": "pattern_circular", "parameters": {
                "count": 6,
                "axis_origin": {"vector": [0, 0, 0], "unit": "mm"},
                "axis_direction": [0, 0, 1]}},
        ]
        self.assertEqual(len(self._repair(features)), 1)
        self.assertEqual(features[1]["inputs"], ["pin"])

    def test_a_boolean_is_never_wired_for_the_model(self) -> None:
        """Which two of three solids a union joins is a real choice."""
        features = [
            {"id": "a", "kind": "box", "parameters": {
                "size": {"vector": [10, 10, 10], "unit": "mm"}}},
            {"id": "u", "kind": "union", "parameters": {}},
        ]
        self.assertEqual(self._repair(features), [])
        self.assertNotIn("inputs", features[1])
        self.assertEqual(self._problems(features), [])

    def test_the_kinds_it_wires_come_from_the_catalogue(self) -> None:
        from forge_ir.features import FEATURE_SPECS
        from forge_roles.library import _takes_exactly_one_input

        takes_one = _takes_exactly_one_input()
        for kind, spec in FEATURE_SPECS.items():
            single = (
                getattr(spec, "variadic_input", None) is None
                and len(tuple(spec.inputs or ())) == 1
            )
            self.assertEqual(kind in takes_one, single, kind)
            if single:
                self.assertEqual(takes_one[kind], spec.inputs[0])


class APatchThatOnlyReordersTheFeatureList(unittest.TestCase):
    """A repair that changes nothing must not be counted as progress.

    Earned on a shaft collar. The analyst's commonest move is to remove every
    feature and re-add them; the no-change guard compared payloads literally,
    so the new list order always read as a change. Forge recorded an
    eight-patch no-op as `applied`, recompiled the identical design, measured
    the identical failure, and spent a second analyst round on it -- which
    dropped the body and produced a document that would not validate. Four
    minutes of model time, and a worse ending than stopping would have given.

    A component's `features`, `parameters` and `interfaces` are addressed by
    `id`. Order is not the design.
    """

    def _same(self, before, after):
        from forge_orchestrator.orchestrator import _the_same_design

        return _the_same_design(before, after)

    @staticmethod
    def _document(order):
        features = {
            "body": {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25.0, "unit": "mm"},
                "height": {"magnitude": 15.0, "unit": "mm"}}},
            "bore": {"id": "bore", "kind": "hole", "inputs": ["body"],
                     "parameters": {"diameter": {"magnitude": 12.0, "unit": "mm"}}},
            "ssh": {"id": "ssh", "kind": "hole", "inputs": ["bore"],
                    "parameters": {"diameter": {"magnitude": 4.0, "unit": "mm"}}},
        }
        return {"components": [{
            "id": "collar",
            "features": [features[name] for name in order],
        }]}

    def test_the_same_features_in_a_new_order_are_the_same_design(self) -> None:
        self.assertTrue(self._same(
            self._document(["body", "bore", "ssh"]),
            self._document(["ssh", "bore", "body"]),
        ))

    def test_a_changed_dimension_is_a_change(self) -> None:
        before = self._document(["body", "bore", "ssh"])
        after = self._document(["ssh", "bore", "body"])
        after["components"][0]["features"][1]["parameters"]["diameter"] = {
            "magnitude": 10.0, "unit": "mm"}
        self.assertFalse(self._same(before, after))

    def test_a_dropped_feature_is_a_change(self) -> None:
        self.assertFalse(self._same(
            self._document(["body", "bore", "ssh"]),
            self._document(["body", "bore"]),
        ))

    def test_rewired_inputs_are_a_change(self) -> None:
        before = self._document(["body", "bore", "ssh"])
        after = self._document(["body", "bore", "ssh"])
        after["components"][0]["features"][2]["inputs"] = ["body"]
        self.assertFalse(self._same(before, after))

    def test_a_vector_keeps_its_order(self) -> None:
        """Only id-bearing lists are sorted. [30, 30, 4] is not [4, 30, 30]."""
        before = {"components": [{"id": "c", "features": [
            {"id": "b", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}}}]}]}
        after = {"components": [{"id": "c", "features": [
            {"id": "b", "kind": "box", "parameters": {
                "size": {"vector": [4, 30, 30], "unit": "mm"}}}]}]}
        self.assertFalse(self._same(before, after))

    def test_operand_order_is_kept(self) -> None:
        """`subtract` removes every later operand from the FIRST one."""
        before = {"components": [{"id": "c", "features": [
            {"id": "s", "kind": "subtract", "inputs": ["a", "b"]}]}]}
        after = {"components": [{"id": "c", "features": [
            {"id": "s", "kind": "subtract", "inputs": ["b", "a"]}]}]}
        self.assertFalse(self._same(before, after))

    def test_duplicate_ids_fall_back_to_a_literal_comparison(self) -> None:
        """Sorting by a key that is not unique could hide a real edit."""
        before = {"components": [{"id": "c", "features": [
            {"id": "x", "kind": "box", "parameters": {"n": 1}},
            {"id": "x", "kind": "box", "parameters": {"n": 2}}]}]}
        after = {"components": [{"id": "c", "features": [
            {"id": "x", "kind": "box", "parameters": {"n": 2}},
            {"id": "x", "kind": "box", "parameters": {"n": 1}}]}]}
        self.assertFalse(self._same(before, after))


class ARequirementNobodyAskedFor(unittest.TestCase):
    """An exact whole-part target in a quantity the brief never mentions.

    Earned on the shaft collar, whose brief names four lengths and an angle
    and says nothing about weight: `REQ_MASS`, "The collar's mass is 100 g",
    `equals`, `source: "user"`. The part weighs about fifteen grams. It only
    failed to become a false PASS by accident -- `equals` with no tolerance
    reports BLOCKED. Written `at_most 100 g`, the collar would have passed a
    mass budget nobody set, and the report would have said so.

    The rule is narrow on purpose. `_numbers_nobody_asked_for` was already
    deliberately narrowed because refusing every unstated threshold rejected
    legitimate engineering, and that reasoning still holds: a bound is a
    judgement, a target is a fabrication.
    """

    COLLAR = (
        "A machined aluminium shaft collar. The outer diameter is 25 mm and "
        "it is 15 mm long. A 12 mm bore runs all the way through on the axis. "
        "Two 4 mm set screw holes pass through the wall, 90 degrees apart. It "
        "carries no load - it is a locating collar, so there is no load case."
    )
    SPACER = (
        "A 3D-printed PLA spacer block, a 30 mm square plate 4 mm thick. It "
        "must weigh no more than 8 g. It carries no load - it is a printed "
        "spacer, so there is no load case."
    )

    @staticmethod
    def _requirement(identifier, measurement, comparison, magnitude, unit):
        return {
            "id": identifier, "statement": identifier,
            "measurement": measurement, "comparison": comparison,
            "threshold": {"magnitude": magnitude, "unit": unit},
            "type": "performance", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted",
        }

    def _normalise(self, brief, requirements):
        """The answer's own claims, without the ones Forge adds itself.

        Both briefs here describe a square or round part, so Forge claims
        both of its extents, and the collar states an angle nothing carried,
        so Forge carries it. Both are right and both have nothing to do with
        whether a fabricated target was dropped, which is what this class is
        about. `SquareMeansBothSides` and `AStatedAngleReachesTheDesign`
        cover the additions themselves.
        """
        from forge_roles.library import _normalise_requirements

        answer, notes, _ = _normalise_requirements(
            {"risk_class": "low", "requirements": requirements}, brief)
        added = ("REQ_BOUNDING_BOX", "REQ_ANGLE", "REQ_ROUND", "REQ_HOLES")
        return [
            r for r in answer["requirements"]
            if not str(r.get("id", "")).startswith(added)
        ], notes

    def test_an_invented_mass_target_is_dropped(self) -> None:
        kept, notes = self._normalise(self.COLLAR, [
            self._requirement("REQ_MASS", "mass", "equals", 100.0, "g"),
            self._requirement(
                "REQ_LENGTH", "parameter:length", "equals", 15.0, "mm"),
        ])
        self.assertEqual([r["id"] for r in kept], ["REQ_LENGTH"])
        self.assertTrue(any("nothing behind the figure" in n for n in notes),
                        notes)

    def test_a_weight_the_brief_states_survives(self) -> None:
        kept, _ = self._normalise(self.SPACER, [
            self._requirement("REQ_MASS", "mass", "at_most", 8.0, "g")])
        # With the limit, Forge's own claim that it is not met by air sealed
        # inside.
        self.assertEqual([r["id"] for r in kept],
                         ["REQ_MASS", "REQ_NOTHING_SEALED_INSIDE"])
        self.assertEqual(kept[0]["source"], "user")

    def test_an_exact_mass_survives_when_the_brief_talks_about_mass(self) -> None:
        """Only silence justifies dropping it. A wrong figure is repairable."""
        kept, _ = self._normalise(self.SPACER, [
            self._requirement("REQ_MASS", "mass", "equals", 100.0, "g")])
        self.assertEqual([r["id"] for r in kept], ["REQ_MASS"])

    def test_engineering_bounds_are_not_fabrications(self) -> None:
        """A minimum wall and a weight budget are judgements, and stay."""
        kept, _ = self._normalise(
            "A machined aluminium bracket 60 mm by 40 mm.",
            [self._requirement(
                "REQ_WALL", "minimum_wall_thickness", "at_least", 3.0, "mm"),
             self._requirement("REQ_BUDGET", "mass", "at_most", 400.0, "g")])
        self.assertEqual(
            sorted(r["id"] for r in kept),
            ["REQ_BUDGET", "REQ_NOTHING_SEALED_INSIDE", "REQ_WALL"])

    def test_a_dimension_requirement_is_never_touched(self) -> None:
        """`parameter:` bindings measure the design, not the whole part."""
        kept, _ = self._normalise(self.COLLAR, [
            self._requirement(
                "REQ_ODD", "parameter:pitch", "equals", 7.0, "furlong")])
        self.assertEqual([r["id"] for r in kept], ["REQ_ODD"])

    # -- provenance --------------------------------------------------------

    def test_a_stated_threshold_stays_the_users(self) -> None:
        kept, _ = self._normalise(self.COLLAR, [
            self._requirement(
                "REQ_LENGTH", "parameter:length", "equals", 15.0, "mm")])
        self.assertEqual(kept[0]["source"], "user")

    def test_an_unstated_threshold_is_not_reported_as_the_users(self) -> None:
        kept, notes = self._normalise(
            "A machined aluminium bracket 60 mm by 40 mm.",
            [self._requirement("REQ_BUDGET", "mass", "at_most", 400.0, "g")])
        self.assertEqual(kept[0]["source"], "derived")
        self.assertTrue(any("did not write it" in n for n in notes), notes)


class WithNoBriefNothingIsProved(unittest.TestCase):
    """Silence in a brief Forge cannot see is not silence in the brief.

    Caught by the existing suite the moment the fabricated-target rule went
    in, and it was right to catch it. `RequirementsEngineer.parse` can be
    called with no brief at all -- a direct parse, a requirement set handed
    over on its own -- and a rule that reads "the brief mentions no mass
    anywhere" then reads every requirement as unsupported and empties the
    set. Absence of evidence arriving as evidence of absence is the exact
    failure this system is built to refuse, so it must not be how Forge
    itself reasons.
    """

    @staticmethod
    def _requirement():
        return {
            "id": "R1", "statement": "A claim.", "measurement": "mass",
            "comparison": "equals",
            "threshold": {"magnitude": 8.0, "unit": "g"},
            "type": "performance", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted",
        }

    def _normalise(self, brief):
        from forge_roles.library import _normalise_requirements

        answer, notes, _ = _normalise_requirements(
            {"risk_class": "low", "requirements": [self._requirement()]}, brief)
        # A round collar now gets both its extents claimed, its roundness
        # measured and its stated length measured on the part, which are
        # different rules from the one under test here.
        return [
            r for r in answer["requirements"]
            if not str(r.get("id", "")).startswith(
                ("REQ_BOUNDING_BOX", "REQ_ANGLE", "REQ_ROUND", "REQ_HOLES",
                 "REQ_PART_", "REQ_STACKED"))
        ], notes

    def test_an_empty_brief_drops_nothing(self) -> None:
        kept, notes = self._normalise("")
        self.assertEqual([r["id"] for r in kept], ["R1"])
        self.assertEqual(notes, [])

    def test_a_whitespace_brief_drops_nothing(self) -> None:
        kept, _ = self._normalise("   \n  ")
        self.assertEqual([r["id"] for r in kept], ["R1"])

    def test_an_empty_brief_does_not_relabel_provenance(self) -> None:
        kept, _ = self._normalise("")
        self.assertEqual(kept[0]["source"], "user")

    def test_a_real_brief_still_does_both(self) -> None:
        kept, notes = self._normalise(
            "A collar 25 mm across and 15 mm long. No load case.")
        self.assertEqual(kept, [])
        self.assertTrue(notes)


class ACountIsStatedInWordsNotInUnits(unittest.TestCase):
    """A dimensionless threshold cannot be checked against the brief's numbers.

    `_numbers_the_brief_states` reads only quantities carrying a unit, and
    that restraint is deliberate and documented: "6 in the middle" is not six
    inches. The consequence is that a bare count is invisible to it. So when
    the provenance rule asked "is this threshold one of the brief's numbers?"
    of `feature_count:hole:set_screw equals 2`, the answer was always no, and
    every count requirement on every brief was relabelled as the model's own
    invention.

    "Two 4 mm set screw holes pass through the wall" states the two exactly
    as plainly as it states the 4 mm. Concluding otherwise from a silence
    Forge created itself is the inference this whole system refuses.
    """

    BRIEF = (
        "A machined aluminium shaft collar, 25 mm across and 15 mm long. Two "
        "4 mm set screw holes pass through the wall, 90 degrees apart."
    )

    def _source(self, measurement, magnitude, unit):
        from forge_roles.library import _normalise_requirements

        answer, _, _ = _normalise_requirements({"risk_class": "low", "requirements": [{
            "id": "R", "statement": "A claim.", "measurement": measurement,
            "comparison": "equals",
            "threshold": {"magnitude": magnitude, "unit": unit},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted",
        }]}, self.BRIEF)
        return answer["requirements"][0]["source"]

    def test_a_count_stays_the_users(self) -> None:
        self.assertEqual(
            self._source("feature_count:hole:set_screw", 2, ""), "user")

    def test_a_safety_factor_stays_the_users(self) -> None:
        self.assertEqual(self._source("safety_factor:bearing", 2.0, ""), "user")

    def test_a_stated_length_stays_the_users(self) -> None:
        self.assertEqual(self._source("parameter:length", 15.0, "mm"), "user")

    def test_an_unstated_length_is_still_relabelled(self) -> None:
        """The rule still works where Forge can actually see the numbers."""
        self.assertEqual(
            self._source("minimum_wall_thickness", 3.0, "mm"), "derived")


class AConstantWrittenAsAnExpression(unittest.TestCase):
    """`{"expression": "4.0", "unit": "mm"}` is a number, and only a number.

    Earned on a shaft collar. An expression takes its dimension from what it
    refers to, so `4.0` -- referring to nothing -- is a dimensionless four,
    and a `diameter` declared in millimetres will not take it. The compiler
    said so precisely. The analyst read `declared_unit='mm'`,
    `actual_unit=''`, concluded the unit was wrong, and patched `unit` to the
    `mm` it already said. The no-op guard caught that and stopped the loop,
    which is an improvement on looping, but the design was still dead over a
    fault with exactly one possible reading.
    """

    def _repair(self, component):
        from forge_roles.library import (
            _a_constant_is_a_number_not_an_expression,
        )

        return _a_constant_is_a_number_not_an_expression(component)

    @staticmethod
    def _hole(expression, unit="mm"):
        value = {"expression": expression}
        if unit:
            value["unit"] = unit
        return {"id": "h", "kind": "hole", "parameters": {
            "diameter": value,
            "position": {"vector": [0, 0, "length / 2"], "unit": "mm"}}}

    def test_a_bare_number_becomes_a_magnitude(self) -> None:
        component = {"id": "c", "features": [self._hole("4.0")]}
        notes = self._repair(component)
        self.assertEqual(
            component["features"][0]["parameters"]["diameter"],
            {"magnitude": 4.0, "unit": "mm"},
        )
        self.assertTrue(notes)

    def test_arithmetic_over_no_parameters_is_still_a_constant(self) -> None:
        component = {"id": "c", "features": [self._hole("25 / 2")]}
        self._repair(component)
        self.assertEqual(
            component["features"][0]["parameters"]["diameter"],
            {"magnitude": 12.5, "unit": "mm"},
        )

    def test_a_negative_constant_keeps_its_sign(self) -> None:
        component = {"id": "c", "features": [self._hole("-4.0")]}
        self._repair(component)
        self.assertEqual(
            component["features"][0]["parameters"]["diameter"]["magnitude"], -4.0)

    # -- and what it must not touch ----------------------------------------

    def test_an_expression_naming_a_parameter_is_left_alone(self) -> None:
        """Rewriting this to a number is the hard-coding the guide forbids."""
        component = {"id": "c", "features": [self._hole("bore_diameter")]}
        self.assertEqual(self._repair(component), [])
        self.assertEqual(
            component["features"][0]["parameters"]["diameter"],
            {"expression": "bore_diameter", "unit": "mm"},
        )

    def test_arithmetic_over_a_parameter_is_left_alone(self) -> None:
        component = {"id": "c", "features": [self._hole("length / 2")]}
        self.assertEqual(self._repair(component), [])

    def test_a_dimensionless_slot_is_left_alone(self) -> None:
        """No unit declared means the slot really is a count or a flag."""
        component = {"id": "c", "features": [self._hole("4", unit="")]}
        self.assertEqual(self._repair(component), [])

    def test_an_expression_carrying_its_own_unit_is_left_alone(self) -> None:
        """`4 mm` is already a length and already compiles."""
        component = {"id": "c", "features": [self._hole("4 mm")]}
        self.assertEqual(self._repair(component), [])

    def test_a_vector_of_numbers_is_untouched(self) -> None:
        component = {"id": "c", "features": [self._hole("4.0")]}
        before = dict(component["features"][0]["parameters"]["position"])
        self._repair(component)
        self.assertEqual(
            component["features"][0]["parameters"]["position"], before)

    # -- the same fault in a component parameter ---------------------------

    def test_a_component_parameter_constant_becomes_a_value(self) -> None:
        component = {"id": "c", "parameters": [
            {"id": "wall", "expression": "3.0", "unit": "mm"}], "features": []}
        self._repair(component)
        self.assertEqual(component["parameters"][0],
                         {"id": "wall", "value": {"magnitude": 3.0, "unit": "mm"}})

    def test_a_derived_component_parameter_is_left_alone(self) -> None:
        component = {"id": "c", "parameters": [
            {"id": "od", "expression": "bore + 2 * wall", "unit": "mm"}],
            "features": []}
        self.assertEqual(self._repair(component), [])
        self.assertIn("expression", component["parameters"][0])

    # -- and the message that misled the analyst ---------------------------

    def test_the_compiler_says_the_unit_is_not_the_problem(self) -> None:
        from forge_expr import Expression
        from forge_ir.values import ExpressionValue
        from forge_units import parse_unit

        value = ExpressionValue(
            expression=Expression.parse("4.0"), unit=parse_unit("mm"))
        try:
            from forge_expr import Resolution

            value.resolve(Resolution(values={}, parameters={}, order=()))
        except Exception as error:  # noqa: BLE001 - the thing under test
            message = str(error)
        else:
            self.fail("a dimensionless constant must not resolve into mm")
        self.assertIn("refers to no parameter", message)
        self.assertIn("Its unit is not the problem", message)


class ARepairThatBreaksAPassingGate(unittest.TestCase):
    """A bounded repair loop assumes every attempt is an improvement.

    Nothing enforced that. On the shaft collar the analyst was told the z
    extent had to be 12 mm and set the body's height to 12 -- which is the
    collar's length, passing at 15 mm against the requirement that states it.
    Recorded as `applied`. The next round set it back to 15. The round after
    proposed 15 again and the loop ended on oscillation, three attempts and
    six minutes later, with the design exactly where it started.
    """

    @staticmethod
    def _report(statuses):
        from forge_evidence import Status

        class _Node:
            def __init__(self, status):
                self.status = status

        class _Gate:
            def __init__(self, identifier):
                self.identifier = identifier

        class _Result:
            def __init__(self, identifier, status):
                self.gate = _Gate(identifier)
                self.evidence = _Node(status)

        class _Report:
            def __init__(self, statuses):
                self.gate_results = [
                    _Result(name, getattr(Status, value))
                    for name, value in statuses.items()
                ]

        return _Report(statuses)

    def _broke(self, before, after):
        from forge_orchestrator.orchestrator import _gates_this_repair_broke

        return _gates_this_repair_broke(self._report(before), self._report(after))

    def test_a_pass_turned_into_a_fail_is_caught(self) -> None:
        self.assertEqual(
            self._broke({"REQ_LENGTH": "PASS", "REQ_BB_Z": "FAIL"},
                        {"REQ_LENGTH": "FAIL", "REQ_BB_Z": "PASS"}),
            {"REQ_LENGTH"},
        )

    def test_a_clean_improvement_is_not_flagged(self) -> None:
        self.assertEqual(
            self._broke({"REQ_A": "PASS", "REQ_B": "FAIL"},
                        {"REQ_A": "PASS", "REQ_B": "PASS"}),
            set(),
        )

    def test_a_failure_that_stays_failing_is_not_flagged(self) -> None:
        self.assertEqual(
            self._broke({"REQ_A": "FAIL"}, {"REQ_A": "FAIL"}), set())

    def test_pass_to_inconclusive_is_not_called_damage(self) -> None:
        """A measurement that got harder is not evidence the part got worse."""
        self.assertEqual(
            self._broke({"REQ_A": "PASS"}, {"REQ_A": "INCONCLUSIVE"}), set())

    def test_a_gate_that_appears_later_is_not_a_regression(self) -> None:
        self.assertEqual(
            self._broke({"REQ_A": "PASS"},
                        {"REQ_A": "PASS", "REQ_NEW": "FAIL"}),
            set(),
        )


class APlacementStatedTwice(unittest.TestCase):
    """A circular pattern that gives both angles and agrees with itself.

    The compiler refuses both, because choosing one silently builds a part
    the other half of the document describes differently. When they say the
    same thing there is no choice to make, so Forge drops the redundant one
    rather than spending a repair round on it.
    """

    @staticmethod
    def _repair(features):
        from forge_roles.library import _one_way_of_saying_where_the_copies_go

        return _one_way_of_saying_where_the_copies_go(features)

    @staticmethod
    def _ring(step=None, total=None, count=2):
        parameters = {
            "count": {"magnitude": count, "unit": ""},
            "axis_origin": {"vector": [0, 0, 0], "unit": "mm"},
            "axis_direction": [0, 0, 1],
        }
        if step is not None:
            parameters["step_angle"] = {"magnitude": step, "unit": "deg"}
        if total is not None:
            parameters["total_angle"] = {"magnitude": total, "unit": "deg"}
        return {"id": "ring", "kind": "pattern_circular",
                "inputs": ["pin"], "parameters": parameters}

    def test_agreeing_angles_lose_the_redundant_one(self) -> None:
        ring = self._ring(step=90.0, total=90.0)
        notes = self._repair([ring])
        self.assertEqual(len(notes), 1)
        self.assertNotIn("total_angle", ring["parameters"])
        self.assertEqual(ring["parameters"]["step_angle"]["magnitude"], 90.0)

    def test_the_step_is_what_survives(self) -> None:
        """It is the number the brief states, so it is the number a
        requirement can be bound to."""
        ring = self._ring(step=120.0, total=240.0, count=3)
        self.assertEqual(len(self._repair([ring])), 1)
        self.assertIn("step_angle", ring["parameters"])

    def test_disagreeing_angles_are_left_alone(self) -> None:
        """Where the copies go is then a real question about the part."""
        ring = self._ring(step=90.0, total=45.0)
        self.assertEqual(self._repair([ring]), [])
        self.assertIn("total_angle", ring["parameters"])

    def test_one_angle_is_never_touched(self) -> None:
        for ring in (self._ring(step=90.0), self._ring(total=90.0),
                     self._ring()):
            before = dict(ring["parameters"])
            self.assertEqual(self._repair([ring]), [])
            self.assertEqual(ring["parameters"], before)

    def test_an_expression_is_not_arithmetic_forge_can_check(self) -> None:
        ring = self._ring(step=90.0)
        ring["parameters"]["total_angle"] = {"expression": "screw_angle"}
        self.assertEqual(self._repair([ring]), [])
        self.assertIn("total_angle", ring["parameters"])


class AnOrphanTheDesignHasNowhereToPut(unittest.TestCase):
    """The hint when there is no literal to point at.

    Observed on a shaft collar. The brief said the two set screws are 90
    degrees apart; the requirements bound that to a parameter; the designer
    declared `set_screw_hole_angle = 90 deg` and placed the holes with a
    millimetre vector, because millimetres were the only placement it had
    been taught. Nothing read the angle, so the design was refused -- and the
    advice was "put an expression where a feature carries the bare number".
    There was no bare 90 deg anywhere in the document. Three attempts, 1404
    seconds, no part.
    """

    @staticmethod
    def _hint(orphan_unit, features):
        from forge_roles.library import _where_the_orphan_belongs

        return _where_the_orphan_belongs(
            {
                "id": "collar",
                "parameters": [
                    {"id": "screw_angle",
                     "value": {"magnitude": 90.0, "unit": orphan_unit}},
                ],
                "features": features,
            },
            ["screw_angle"],
        )

    @staticmethod
    def _body():
        return [{"id": "body", "kind": "cylinder", "parameters": {
            "diameter": {"magnitude": 25.0, "unit": "mm"},
            "height": {"magnitude": 15.0, "unit": "mm"}}}]

    def test_it_names_the_fields_that_hold_that_dimension(self) -> None:
        hint = self._hint("deg", self._body())
        self.assertIn("pattern_circular.step_angle", hint)
        self.assertIn("revolve.angle", hint)
        self.assertNotIn("cylinder.diameter", hint)

    def test_it_does_not_send_them_looking_for_a_literal(self) -> None:
        hint = self._hint("deg", self._body())
        self.assertNotIn("where a feature currently carries the bare number",
                         hint)

    def test_it_says_degrees_are_not_a_position(self) -> None:
        hint = self._hint("deg", self._body())
        self.assertIn("millimetre vector", hint)
        self.assertIn("pattern_circular", hint)

    def test_a_literal_that_does_exist_still_wins(self) -> None:
        """The old, better answer is untouched: when the number is written
        out in the geometry, point straight at it."""
        features = self._body() + [{
            "id": "ring", "kind": "pattern_circular", "inputs": ["body"],
            "parameters": {
                "count": {"magnitude": 2, "unit": ""},
                "step_angle": {"magnitude": 90.0, "unit": "deg"},
                "axis_origin": {"vector": [0, 0, 0], "unit": "mm"},
                "axis_direction": [0, 0, 1]}}]
        hint = self._hint("deg", features)
        self.assertIn("`ring.step_angle`", hint)
        self.assertIn("already in the geometry", hint)

    def test_the_fields_come_from_the_catalogue(self) -> None:
        """So a feature added later is named without anyone remembering to."""
        from forge_ir.features import FEATURE_SPECS
        from forge_roles.library import _slots_that_could_read

        for unit, sort in (("deg", "angle"), ("mm", "length")):
            expected = {
                f"{kind}.{parameter.name}"
                for kind, spec in FEATURE_SPECS.items()
                for parameter in spec.parameters
                if parameter.sort == sort
            }
            self.assertEqual(set(_slots_that_could_read(unit)), expected)

    def test_a_dimension_nothing_takes_says_so(self) -> None:
        hint = self._hint("N", self._body())
        self.assertIn("no feature parameter in the vocabulary takes that "
                      "dimension", hint)


class SquareMeansBothSides(unittest.TestCase):
    """One word in the brief, two extents of the part.

    "A 30 mm square plate": claimed on X only, and the released part was
    29.84 x 11.94 x 14.03 with sixteen claims all PASS. Nothing was wrong
    with the checking. The thing that was wrong with the part had never been
    claimed.
    """

    @staticmethod
    def _claim(axis, magnitude):
        return {"id": f"REQ_BB_{axis.upper()}",
                "measurement": f"bounding_box_{axis}",
                "comparison": "equals",
                "statement": f"{magnitude} across {axis}",
                "threshold": {"magnitude": magnitude, "unit": "mm"}}

    @staticmethod
    def _fill(brief, requirements):
        from forge_roles.library import _square_is_square_in_both_directions

        return _square_is_square_in_both_directions(brief, requirements)

    SPACER = ("A 30 mm square plate 4 mm thick with a 12 mm post 10 mm tall "
              "and a 5 mm hole through the middle.")

    def test_the_second_extent_is_claimed(self) -> None:
        requirements = [self._claim("x", 30.0)]
        self.assertEqual(len(self._fill(self.SPACER, requirements)), 1)
        added = requirements[-1]
        self.assertEqual(added["measurement"], "bounding_box_y")
        self.assertEqual(added["threshold"], {"magnitude": 30.0, "unit": "mm"})
        self.assertEqual(added["comparison"], "equals")

    def test_it_works_from_whichever_axis_was_claimed(self) -> None:
        requirements = [self._claim("y", 30.0)]
        self.assertEqual(len(self._fill(self.SPACER, requirements)), 1)
        self.assertEqual(requirements[-1]["measurement"], "bounding_box_x")

    def test_both_already_claimed_is_left_alone(self) -> None:
        requirements = [self._claim("x", 30.0), self._claim("y", 30.0)]
        self.assertEqual(self._fill(self.SPACER, requirements), [])
        self.assertEqual(len(requirements), 2)

    def test_a_part_that_is_not_square_after_all_is_the_models_call(self) -> None:
        requirements = [self._claim("x", 30.0), self._claim("y", 20.0)]
        self.assertEqual(self._fill(self.SPACER, requirements), [])
        self.assertEqual(len(requirements), 2)

    def test_with_nothing_claimed_both_extents_are_claimed(self) -> None:
        """The case that actually happened. Ten requirements, the 30 mm bound
        to `parameter:base_width`, and the part's size measured by none of
        them -- so a repair that waited for an anchor waited forever."""
        requirements = [{
            "id": "REQ_BASE_WIDTH", "measurement": "parameter:base_width",
            "comparison": "equals", "statement": "30 wide",
            "threshold": {"magnitude": 30.0, "unit": "mm"}}]
        self.assertEqual(len(self._fill(self.SPACER, requirements)), 1)
        added = {
            r["measurement"]: r["threshold"] for r in requirements[1:]
        }
        self.assertEqual(added, {
            "bounding_box_x": {"magnitude": 30.0, "unit": "mm"},
            "bounding_box_y": {"magnitude": 30.0, "unit": "mm"}})

    def test_a_round_part_gets_its_diameter_both_ways(self) -> None:
        collar = ("A machined aluminium shaft collar. The outer diameter is "
                  "25 mm and it is 15 mm long. A 12 mm bore runs through.")
        requirements = []
        self.assertEqual(len(self._fill(collar, requirements)), 1)
        self.assertEqual(
            sorted(r["measurement"] for r in requirements),
            ["bounding_box_x", "bounding_box_y"])
        self.assertEqual(requirements[0]["threshold"],
                         {"magnitude": 25.0, "unit": "mm"})

    def test_a_feature_of_something_larger_is_not_the_footprint(self) -> None:
        """The guard. A brief's biggest number is its overall size, so a
        square figure below that describes a feature, not the part."""
        requirements = []
        self.assertEqual(
            self._fill("A 100 mm long arm with a 30 mm square boss on the "
                       "end, 5 mm thick.", requirements),
            [])
        self.assertEqual(requirements, [])

    def test_a_size_already_claimed_is_never_doubled(self) -> None:
        requirements = [self._claim("x", 30.0), self._claim("y", 30.0)]
        self.assertEqual(self._fill(self.SPACER, requirements), [])
        self.assertEqual(len(requirements), 2)

    def test_the_added_claims_are_the_users_own_number(self) -> None:
        requirements = []
        self._fill(self.SPACER, requirements)
        self.assertTrue(all(r["source"] == "user" for r in requirements))

    def test_a_different_number_is_not_the_square_one(self) -> None:
        requirements = [self._claim("x", 12.0)]
        self.assertEqual(self._fill(self.SPACER, requirements), [])
        self.assertEqual(len(requirements), 1)

    def test_a_square_hole_says_nothing_about_the_part(self) -> None:
        requirements = [self._claim("x", 40.0)]
        self.assertEqual(
            self._fill("A 40 mm long bar with a square 5 mm hole.",
                       requirements),
            [])
        self.assertEqual(len(requirements), 1)

    def test_the_word_has_to_touch_the_number(self) -> None:
        """A first draft took a window of a few words and read the 4 mm
        thickness of a square plate as square too."""
        from forge_roles.library import _a_number_that_is_two_extents

        self.assertEqual(_a_number_that_is_two_extents(self.SPACER),
                         [(30.0, "mm")])

    def test_round_is_the_same_statement(self) -> None:
        from forge_roles.library import _a_number_that_is_two_extents

        for brief in ("A collar 25 mm across and 15 mm long.",
                      "A spacer 25 mm outside diameter, 10 mm long.",
                      "A disc 25 mm in diameter and 6 mm thick.",
                      "A washer with a 25 mm OD."):
            self.assertEqual(_a_number_that_is_two_extents(brief),
                             [(25.0, "mm")], brief)

    def test_a_brief_that_says_neither_is_untouched(self) -> None:
        requirements = [self._claim("x", 40.0)]
        self.assertEqual(
            self._fill("A bracket 40 mm by 20 mm and 5 mm thick.",
                       requirements),
            [])
        self.assertEqual(len(requirements), 1)

    def test_it_runs_inside_the_requirements_repair(self) -> None:
        from forge_roles.library import _normalise_requirements

        answer, notes, _ = _normalise_requirements(
            {"requirements": [self._claim("x", 30.0)]}, self.SPACER)
        bindings = [r["measurement"] for r in answer["requirements"]]
        self.assertIn("bounding_box_y", bindings)
        self.assertTrue(any("square or round" in note for note in notes))


class AnAngleThatIsAlreadyInTheGeometry(unittest.TestCase):
    """Two directions an angle apart, and the angle written down separately.

    Two set screws 90 degrees apart through the wall of a collar are two
    holes on the centre line whose axes are `[1, 0, 0]` and `[0, 1, 0]`. The
    90 degrees IS the angle between them -- and it appears nowhere as a
    number, so the literal search that rescues a bare `2.0` has nothing to
    find. The design is right, the parameter is an orphan, and the run dies
    on a document contract with a correct part inside it.
    """

    @staticmethod
    def _hole(identifier, axis, tags=("set_screw",)):
        feature = {
            "id": identifier, "kind": "hole", "parameters": {
                "diameter": {"magnitude": 4.0, "unit": "mm"},
                "position": {"vector": [0, 0, 7.5], "unit": "mm"},
                "axis": list(axis)}}
        if tags:
            feature["tags"] = list(tags)
        return feature

    def _component(self, features, angle=90.0, unit="deg"):
        return {
            "id": "collar", "name": "Collar", "material": "aluminium_6061_t6",
            "parameters": [
                {"id": "screw_angle",
                 "value": {"magnitude": angle, "unit": unit}}],
            "features": features}

    def _wire(self, component):
        from forge_roles.library import _drive_the_geometry_from_the_orphan

        return _drive_the_geometry_from_the_orphan(component, ["screw_angle"])

    def _perpendicular(self):
        return self._component([
            self._hole("screw_1", [1, 0, 0]),
            self._hole("screw_2", [0, 1, 0])])

    def test_the_second_direction_is_written_as_the_first_turned(self) -> None:
        component = self._perpendicular()
        notes, unresolved = self._wire(component)
        self.assertEqual(unresolved, [])
        self.assertEqual(len(notes), 1)
        axis = component["features"][1]["parameters"]["axis"]
        self.assertTrue(all(isinstance(term, str) for term in axis), axis)
        self.assertTrue(any("cos(screw_angle)" in term for term in axis))
        self.assertTrue(any("sin(screw_angle)" in term for term in axis))

    def test_the_first_direction_is_left_alone(self) -> None:
        component = self._perpendicular()
        self._wire(component)
        self.assertEqual(
            component["features"][0]["parameters"]["axis"], [1, 0, 0])

    def test_the_parameter_is_no_longer_an_orphan(self) -> None:
        from forge_roles.library import _identifiers_in

        component = self._perpendicular()
        self._wire(component)
        read = set()
        for feature in component["features"]:
            read |= _identifiers_in(feature.get("parameters"))
        self.assertIn("screw_angle", read)

    def test_the_geometry_does_not_move(self) -> None:
        """The whole licence for doing this without asking: at the angle the
        design already states, the expression is the same unit vector.

        Not bit-identical, and the claim is not made: `cos` of a right angle
        returns 6e-17 rather than 0, which tilts the axis by that much. On a
        25 mm part it displaces the surface by about 1e-15 mm -- eleven
        orders below the octree's measurement floor and below what an STL
        can even record. The assertion is written at 1e-9 mm, which is still
        far stricter than anything downstream can tell apart."""
        import json

        import numpy as np

        from forge_ir import SCHEMA_VERSION, Document
        from forge_kernel import Compiler

        def build(component):
            payload = {
                "schema_version": SCHEMA_VERSION, "revision": 1,
                "document_id": "00000000-0000-4000-8000-0000000000c1",
                "project_id": "00000000-0000-4000-8000-0000000000cf",
                "name": "Collar", "risk_class": "low",
                "units": {"length": "mm", "mass": "kg", "angle": "deg",
                          "force": "N"},
                "requirements": [], "assumptions": [],
                "components": [component]}
            document = Document.from_json(json.dumps(payload))
            return Compiler().compile_component(document.components[0]).solid

        body = {"id": "body", "kind": "cylinder", "parameters": {
            "diameter": {"magnitude": 25.0, "unit": "mm"},
            "height": {"magnitude": 15.0, "unit": "mm"}}}
        before = self._component([
            body,
            dict(self._hole("screw_1", [1, 0, 0]), inputs=["body"]),
            dict(self._hole("screw_2", [0, 1, 0]), inputs=["screw_1"])])
        after = self._component([
            body,
            dict(self._hole("screw_1", [1, 0, 0]), inputs=["body"]),
            dict(self._hole("screw_2", [0, 1, 0]), inputs=["screw_1"])])
        self.assertEqual(self._wire(after)[1], [])

        points = np.array(
            [[8.5, 0, 7.5], [0, 8.5, 7.5], [6.0, 6.0, 7.5], [0, 0, 7.5]],
            dtype=float)
        for was, now in zip(build(before)(points), build(after)(points)):
            self.assertAlmostEqual(float(was), float(now), places=9)

    def test_turning_the_parameter_now_turns_the_hole(self) -> None:
        import json
        import math

        import numpy as np

        from forge_ir import SCHEMA_VERSION, Document
        from forge_kernel import Compiler

        component = self._component([
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25.0, "unit": "mm"},
                "height": {"magnitude": 15.0, "unit": "mm"}}},
            dict(self._hole("screw_1", [1, 0, 0]), inputs=["body"]),
            dict(self._hole("screw_2", [0, 1, 0]), inputs=["screw_1"])])
        self._wire(component)
        component["parameters"][0]["value"]["magnitude"] = 120.0
        payload = {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-0000000000c1",
            "project_id": "00000000-0000-4000-8000-0000000000cf",
            "name": "Collar", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [component]}
        solid = Compiler().compile_component(
            Document.from_json(json.dumps(payload)).components[0]).solid
        turn = math.radians(120)
        moved = np.array(
            [[8.5 * math.cos(turn), 8.5 * math.sin(turn), 7.5]], dtype=float)
        still = np.array([[0, 8.5, 7.5]], dtype=float)
        self.assertGreater(float(solid(moved)[0]), 0.0,
                           "the hole followed the parameter to 120 degrees")
        self.assertLess(float(solid(still)[0]), 0.0,
                        "and is no longer at 90")

    # -- everything it must refuse to touch -------------------------------
    def test_directions_that_are_not_that_angle_apart(self) -> None:
        """The failing run: both set screws drilled down Z, parallel, and an
        angle of 90 that describes nothing in the document."""
        component = self._component([
            self._hole("screw_1", [0, 0, 1]),
            self._hole("screw_2", [0, 0, 1])])
        self.assertEqual(self._wire(component)[1], ["screw_angle"])
        self.assertEqual(
            component["features"][1]["parameters"]["axis"], [0, 0, 1])

    def test_opposed_directions_span_no_plane(self) -> None:
        component = self._component(
            [self._hole("screw_1", [1, 0, 0]), self._hole("screw_2", [-1, 0, 0])],
            angle=180.0)
        self.assertEqual(self._wire(component)[1], ["screw_angle"])

    def test_untagged_features_are_never_paired(self) -> None:
        """A tag is the design's own statement that two features are the same
        thing twice. Without one, Forge is guessing which pair is meant."""
        component = self._component([
            self._hole("screw_1", [1, 0, 0], ()),
            self._hole("screw_2", [0, 1, 0], ())])
        self.assertEqual(self._wire(component)[1], ["screw_angle"])

    def test_the_bore_is_not_one_of_the_set_screws(self) -> None:
        """Three holes pointing three ways, and every pair of them 90 degrees
        apart. The tag is what says which pair the angle is about."""
        component = self._component([
            {"id": "bore", "kind": "hole", "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "position": {"vector": [0, 0, 7.5], "unit": "mm"},
                "axis": [0, 0, 1]}},
            self._hole("screw_1", [1, 0, 0]),
            self._hole("screw_2", [0, 1, 0])])
        self.assertEqual(self._wire(component)[1], [])
        self.assertEqual(
            component["features"][0]["parameters"]["axis"], [0, 0, 1])

    def test_three_alike_features_are_a_pattern_not_a_pair(self) -> None:
        component = self._component([
            self._hole("screw_1", [1, 0, 0]),
            self._hole("screw_2", [0, 1, 0]),
            self._hole("screw_3", [-1, 0, 0])])
        self.assertEqual(self._wire(component)[1], ["screw_angle"])

    def test_two_pairs_the_same_angle_apart_is_a_choice(self) -> None:
        component = self._component([
            self._hole("screw_1", [1, 0, 0]),
            self._hole("screw_2", [0, 1, 0]),
            self._hole("pin_1", [0, 0, 1], ("pin",)),
            self._hole("pin_2", [1, 0, 0], ("pin",))])
        self.assertEqual(self._wire(component)[1], ["screw_angle"])

    def test_an_orphan_that_is_not_an_angle_is_left_to_the_old_path(self) -> None:
        component = self._component([
            self._hole("screw_1", [1, 0, 0]),
            self._hole("screw_2", [0, 1, 0])], angle=90.0, unit="mm")
        self.assertEqual(self._wire(component)[1], ["screw_angle"])

    def test_a_literal_still_wins_where_there_is_one(self) -> None:
        """The older, better repair is untouched: when the number is written
        out in the geometry, point the parameter straight at it."""
        component = {
            "id": "ring", "parameters": [
                {"id": "screw_angle",
                 "value": {"magnitude": 90.0, "unit": "deg"}}],
            "features": [{
                "id": "ring", "kind": "pattern_circular", "parameters": {
                    "count": {"magnitude": 2, "unit": ""},
                    "step_angle": {"magnitude": 90.0, "unit": "deg"},
                    "axis_origin": {"vector": [0, 0, 0], "unit": "mm"},
                    "axis_direction": [0, 0, 1]}}]}
        notes, unresolved = self._wire(component)
        self.assertEqual(unresolved, [])
        self.assertEqual(
            component["features"][0]["parameters"]["step_angle"],
            {"expression": "screw_angle"})

    def test_the_direction_fields_come_from_the_catalogue(self) -> None:
        """So `mirror.plane_normal` and `pattern_circular.axis_direction` are
        answered by the same code, without being named."""
        from forge_ir.features import FEATURE_SPECS
        from forge_roles.library import _the_directions_a_feature_points

        for kind, spec in FEATURE_SPECS.items():
            directions = [p.name for p in spec.parameters
                          if p.sort == "direction"]
            if not directions:
                continue
            feature = {"id": "f", "kind": kind, "parameters": {
                name: [1, 0, 0] for name in directions}}
            self.assertEqual(
                [key for _, key, _ in _the_directions_a_feature_points(feature)],
                directions, kind)


class ARunThatEndsWithNothing(unittest.TestCase):
    """The worst outcome Forge can produce, and not always the honest one.

    A collar was refused three times over one unread parameter. Twenty
    minutes bought a message about a document contract. The answer being
    thrown away held a complete, compilable part whose real faults were
    geometric -- both set screws drilled down the shaft instead of into it --
    and the gates name those in seconds, if anything ever lets them look.

    So on the last attempt the unmeasurable claim loses its binding and the
    design stays. The claim is reported NOT_TESTED, never passed.
    """

    REJECTED = {
        "rationale": "x",
        "document": {"name": "Shaft Collar", "components": [{
            "id": "collar",
            "features": [
                {"id": "body", "kind": "cylinder", "parameters": {
                    "diameter": {"expression": "outer_diameter", "unit": "mm"},
                    "height": {"expression": "length", "unit": "mm"}}},
                {"id": "bore", "kind": "hole", "parameters": {
                    "diameter": {"expression": "bore_diameter", "unit": "mm"},
                    "position": {"vector": [0, 0, "length / 2"], "unit": "mm"},
                    "axis": [0.0, 0.0, 1.0]}},
                {"id": "screw_1", "kind": "hole", "tags": ["set_screw"],
                 "parameters": {
                     "diameter": {"expression": "screw_diameter",
                                  "unit": "mm"},
                     "position": {"vector": ["length / 4", 0, "length / 2"],
                                  "unit": "mm"},
                     "axis": [0.0, 0.0, 1.0]}},
                {"id": "screw_2", "kind": "hole", "tags": ["set_screw"],
                 "parameters": {
                     "diameter": {"expression": "screw_diameter",
                                  "unit": "mm"},
                     "position": {"vector": ["-length / 4", 0, "length / 2"],
                                  "unit": "mm"},
                     "axis": [0.0, 0.0, 1.0]}},
            ],
            "parameters": [
                {"id": "outer_diameter",
                 "value": {"magnitude": 25.0, "unit": "mm"}},
                {"id": "length", "value": {"magnitude": 15.0, "unit": "mm"}},
                {"id": "bore_diameter",
                 "value": {"magnitude": 12.0, "unit": "mm"}},
                {"id": "screw_diameter",
                 "value": {"magnitude": 4.0, "unit": "mm"}},
                {"id": "screw_angle",
                 "value": {"magnitude": 90.0, "unit": "deg"}},
            ]}]}}

    @staticmethod
    def _requirement(identifier, measurement, magnitude, unit):
        return {
            "id": identifier, "statement": identifier,
            "measurement": measurement, "comparison": "equals",
            "threshold": {"magnitude": magnitude, "unit": unit},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted",
        }

    def _requirements(self, *, angle=True):
        from forge_roles.library import RequirementSet

        claims = [
            self._requirement("REQ_OD", "parameter:outer_diameter", 25.0, "mm"),
            self._requirement("REQ_LEN", "parameter:length", 15.0, "mm"),
            self._requirement("REQ_BORE", "parameter:bore_diameter", 12.0, "mm"),
            self._requirement("REQ_BB_X", "bounding_box_x", 25.0, "mm"),
        ]
        if angle:
            claims.append(self._requirement(
                "REQ_ANGLE", "parameter:screw_angle", 90.0, "deg"))
        return RequirementSet(
            requirements=tuple(claims), assumptions=(), unknowns=())

    def _salvage(self, answer=None, **overrides):
        from forge_roles import ForgeIRDesigner

        inputs = {
            "requirements": self._requirements(), "intent": None,
            "document_id": "", "project_id": "",
        }
        inputs.update(overrides)
        return ForgeIRDesigner().salvage(
            answer if answer is not None else self.REJECTED, [], **inputs)

    def _bindings(self, draft):
        return {
            r.identifier: (r.measurement or "") for r in draft.document.requirements
        }

    def test_this_answer_really_is_rejected(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(
                self.REJECTED, requirements=self._requirements(),
                intent=None, document_id="", project_id="")
        self.assertTrue(
            any("no feature reads them" in p for p in caught.exception.problems))

    def test_the_part_survives(self) -> None:
        draft = self._salvage()
        self.assertIsNotNone(draft)
        self.assertEqual(len(draft.document.components), 1)

    def test_only_the_unmeasurable_claim_loses_its_binding(self) -> None:
        bindings = self._bindings(self._salvage())
        self.assertEqual(bindings["REQ_ANGLE"], "")
        self.assertEqual(bindings["REQ_OD"], "parameter:outer_diameter")
        self.assertEqual(bindings["REQ_BB_X"], "bounding_box_x")

    def test_the_claim_keeps_its_threshold(self) -> None:
        """Unbind, don't delete: the reader sees a claim nobody checked, not
        a claim that quietly vanished."""
        angle = next(
            r for r in self._salvage().document.requirements
            if r.identifier == "REQ_ANGLE")
        self.assertEqual(angle.threshold.magnitude.midpoint, 90.0)

    def test_it_is_reported_not_tested_and_never_passed(self) -> None:
        from forge_pipeline import verify_component

        draft = self._salvage()
        report = verify_component(
            draft.document, draft.document.components[0], measurement_depth=6)
        angle = [
            result for result in report.gate_results
            if result.gate.identifier == "REQ_ANGLE"
        ]
        self.assertEqual([r.status.value for r in angle], ["NOT_TESTED"])
        self.assertNotIn(
            "PASS", [r.status.value for r in angle],
            "an unchecked claim is never a passing one")

    def test_the_geometry_is_still_gated(self) -> None:
        """The whole point. The set screws are drilled down the shaft rather
        than into it, and now somebody gets told so."""
        from forge_pipeline import verify_component

        draft = self._salvage()
        report = verify_component(
            draft.document, draft.document.components[0], measurement_depth=6)
        self.assertEqual(report.overall_status.value, "FAIL")
        failed = {
            r.gate.identifier for r in report.gate_results
            if r.status.value == "FAIL"
        }
        self.assertIn("GEOM_BORES_SURVIVE", failed)

    def test_the_run_is_told_what_was_given_up(self) -> None:
        draft = self._salvage()
        self.assertTrue(any("NOT_TESTED" in note for note in draft.notes))
        self.assertTrue(any("REQ_ANGLE" in note for note in draft.notes))

    # -- what it must refuse ---------------------------------------------
    def test_nothing_to_salvage_when_there_is_no_orphan(self) -> None:
        self.assertIsNone(
            self._salvage(requirements=self._requirements(angle=False)))

    def test_a_design_with_other_faults_is_not_rescued(self) -> None:
        """Only a claim that can go unchecked is resolvable this way. Any
        other problem and the re-parse raises, and the run fails as before."""
        from copy import deepcopy

        broken = deepcopy(self.REJECTED)
        broken["document"]["components"][0]["features"][1]["parameters"][
            "diameter"] = {"expression": "no_such_parameter", "unit": "mm"}
        self.assertIsNone(self._salvage(broken))

    def test_an_answer_that_is_not_a_document_is_not_rescued(self) -> None:
        self.assertIsNone(self._salvage({"rationale": "I could not."}))

    def test_the_default_role_salvages_nothing(self) -> None:
        """Every other role keeps the old behaviour exactly."""
        from forge_roles import BriefInterpreter, RequirementsEngineer

        for role in (BriefInterpreter(), RequirementsEngineer()):
            self.assertIsNone(role.salvage({"anything": True}, []))

    def test_a_salvaged_result_says_so(self) -> None:
        from forge_roles.base import RoleResult
        from forge_models import Usage

        clean = RoleResult(value=1, role="r", prompt_version="1", attempts=1,
                           usage=Usage())
        self.assertEqual(clean.as_dict()["salvaged"], [])
        kept = RoleResult(value=1, role="r", prompt_version="1", attempts=3,
                          usage=Usage(), salvaged=("the orphan",))
        self.assertEqual(kept.as_dict()["salvaged"], ["the orphan"])


class TwoNamesForOneDimension(unittest.TestCase):
    """A name the geometry uses that no parameter declares.

    Asked for a 30 mm square plate, the designer wrote
    `size: [base_width, base_height, base_thickness]` -- three names for
    three slots, copied from the 60 by 40 bracket in the guide, which rightly
    has three. Then it had to find a value for the middle one, said 4, and
    left the third undeclared. Three attempts, 2184 seconds, no part.

    The decoder was right and its message was a diagnosis: what is absent,
    and a list of what exists. It never said that two edits resolve it, which
    features are affected, or that the requirements said the part is square.
    """

    @staticmethod
    def _component(*, declare=("base_width", "base_height"), size=None):
        return {
            "id": "spacer",
            "parameters": [
                {"id": name, "value": {"magnitude": 30.0, "unit": "mm"}}
                for name in declare
            ],
            "features": [
                {"id": "base", "kind": "box", "parameters": {
                    "size": {"vector": list(
                        size or ["base_width", "base_height", "base_thickness"]
                    ), "unit": "mm"},
                    "centered": True}},
                {"id": "hole", "kind": "hole", "inputs": ["base"],
                 "parameters": {
                     "diameter": {"magnitude": 5.0, "unit": "mm"},
                     "position": {"vector": [0, 0, "base_thickness / 2"],
                                  "unit": "mm"},
                     "fit": "clearance_normal"}},
            ],
        }

    @staticmethod
    def _requirements(*claims):
        from forge_roles.library import RequirementSet

        return RequirementSet(
            requirements=tuple(claims), assumptions=(), unknowns=())

    @staticmethod
    def _claim(identifier, measurement, magnitude, unit="mm",
               comparison="equals"):
        return {
            "id": identifier, "statement": identifier,
            "measurement": measurement, "comparison": comparison,
            "threshold": {"magnitude": magnitude, "unit": unit},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted",
        }

    def _problems(self, component=None, requirements=None):
        from forge_roles.library import _a_name_nothing_declares

        return _a_name_nothing_declares(
            component if component is not None else self._component(),
            requirements)

    def test_it_names_the_features_that_use_it(self) -> None:
        problem = self._problems()[0]
        self.assertIn("`base_thickness`", problem)
        self.assertIn("`base`", problem)
        self.assertIn("`hole`", problem)

    def test_it_names_both_edits_and_decides_neither(self) -> None:
        problem = self._problems()[0]
        self.assertIn("declare it", problem)
        self.assertIn("point those features at a name you did declare",
                      problem)
        self.assertIn("Forge cannot tell which you meant", problem)

    def test_an_enum_is_not_a_missing_parameter(self) -> None:
        """`"fit": "clearance_normal"` is a word, not an expression. A first
        draft reported it as an undeclared parameter on every hole."""
        self.assertNotIn(
            "clearance_normal", " ".join(self._problems()))

    def test_a_function_is_not_a_missing_parameter(self) -> None:
        """`cos(screw_angle)` refers to `screw_angle`, and Forge itself now
        writes that expression."""
        component = self._component(size=["base_width", "base_width", "4"])
        component["features"][1]["parameters"]["axis"] = [
            "cos(base_width)", "sin(base_width)", "0"]
        component["features"][1]["parameters"]["position"] = {
            "vector": [0, 0, 0], "unit": "mm"}
        self.assertEqual(self._problems(component), [])

    def test_a_design_that_declares_everything_is_quiet(self) -> None:
        self.assertEqual(
            self._problems(self._component(
                declare=("base_width", "base_height", "base_thickness"))),
            [])

    def test_one_candidate_is_named_and_two_are_not(self) -> None:
        """Naming `base_height` and `base_width` together says nothing, and
        naming `base_width` would be worse than silence -- it is a width, and
        `base_thickness` is not. Only the same KIND of size is a candidate,
        so with both declared, `base_height` alone is named."""
        both = self._problems()[0]
        self.assertIn("Note that `base_height`", both)
        self.assertNotIn("Note that `base_width`", both)
        one = self._problems(self._component(declare=("base_height",)))[0]
        self.assertIn("`base_height`", one)
        self.assertIn("one dimension under two names", one)

    def test_the_square_requirement_is_said_out_loud(self) -> None:
        problems = self._problems(requirements=self._requirements(
            self._claim("REQ_X", "bounding_box_x", 30.0),
            self._claim("REQ_Y", "bounding_box_y", 30.0)))
        self.assertTrue(any("same size across X, Y" in p for p in problems))
        self.assertTrue(any("written twice" in p for p in problems))

    def test_nothing_is_said_about_squareness_when_nothing_requires_it(
            self) -> None:
        problems = self._problems(requirements=self._requirements(
            self._claim("REQ_X", "bounding_box_x", 40.0),
            self._claim("REQ_Y", "bounding_box_y", 20.0)))
        self.assertEqual(len(problems), 1)


class TheRecordSaysThePartIsSquare(unittest.TestCase):
    """Two extent claims carrying one number leave no choice about the build.

    Read from the accepted requirements rather than the brief's wording, so
    it is as certain as anything Forge holds -- and said to the designer on
    the first attempt rather than after a failure.
    """

    @staticmethod
    def _claim(measurement, magnitude, comparison="equals", unit="mm"):
        return {
            "id": measurement.upper(), "statement": measurement,
            "measurement": measurement, "comparison": comparison,
            "threshold": {"magnitude": magnitude, "unit": unit},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted",
        }

    def _equal(self, *claims):
        from forge_roles.library import (
            RequirementSet, _extents_the_requirements_make_equal)

        return _extents_the_requirements_make_equal(RequirementSet(
            requirements=tuple(claims), assumptions=(), unknowns=()))

    def test_two_extents_at_one_figure(self) -> None:
        self.assertEqual(
            self._equal(self._claim("bounding_box_x", 30.0),
                        self._claim("bounding_box_y", 30.0),
                        self._claim("bounding_box_z", 4.0)),
            {"x": "30 mm", "y": "30 mm"})

    def test_a_rectangle_is_not_square(self) -> None:
        self.assertEqual(
            self._equal(self._claim("bounding_box_x", 40.0),
                        self._claim("bounding_box_y", 20.0)),
            {})

    def test_one_extent_alone_says_nothing(self) -> None:
        self.assertEqual(self._equal(self._claim("bounding_box_x", 30.0)), {})

    def test_a_bound_is_not_a_size(self) -> None:
        """`at_most 30` twice does not make a part square."""
        self.assertEqual(
            self._equal(self._claim("bounding_box_x", 30.0, "at_most"),
                        self._claim("bounding_box_y", 30.0, "at_most")),
            {})

    def test_different_units_are_not_compared_by_number(self) -> None:
        self.assertEqual(
            self._equal(self._claim("bounding_box_x", 30.0),
                        self._claim("bounding_box_y", 30.0, unit="cm")),
            {})

    def test_the_designer_is_told_before_it_answers(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import Intent, RequirementSet

        messages = ForgeIRDesigner().build_messages(
            intent=Intent(summary="A square plate.", part_kind="plate",
                          stated=(), implied=(), unstated=()),
            requirements=RequirementSet(
                requirements=(self._claim("bounding_box_x", 30.0),
                              self._claim("bounding_box_y", 30.0)),
                assumptions=(), unknowns=()))
        text = "\n".join(m.content for m in messages)
        self.assertIn("same size across X, Y", text)
        self.assertIn('"plate_size", "plate_size"', text)

    def test_a_rectangular_part_is_told_nothing_of_the_sort(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import Intent, RequirementSet

        messages = ForgeIRDesigner().build_messages(
            intent=Intent(summary="A bracket.", part_kind="bracket",
                          stated=(), implied=(), unstated=()),
            requirements=RequirementSet(
                requirements=(self._claim("bounding_box_x", 40.0),
                              self._claim("bounding_box_y", 20.0)),
                assumptions=(), unknowns=()))
        self.assertNotIn(
            "same size across", "\n".join(m.content for m in messages))


class ANameTheFeaturesAlreadyUse(unittest.TestCase):
    """A measured parameter the design refers to and never declared.

    The sibling of the repair that declares a measured parameter from a bare
    literal. Here there is no literal -- the design wrote the NAME, in an
    expression, and forgot the declaration. The features say where it
    belongs, the requirement says what it is worth, and a name the geometry
    refers to and nothing defines is a missing line rather than a decision.
    """

    @staticmethod
    def _payload(*, referenced=True):
        return {"components": [{
            "id": "plate",
            "parameters": [
                {"id": "plate_width",
                 "value": {"magnitude": 30.0, "unit": "mm"}}],
            "features": [{"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [
                    "plate_width", "plate_width",
                    "plate_thickness" if referenced else "4"],
                    "unit": "mm"}}}],
        }]}

    @staticmethod
    def _requirements():
        from forge_roles.library import RequirementSet

        return RequirementSet(requirements=({
            "id": "REQ_T", "statement": "4 mm thick.",
            "measurement": "parameter:plate_thickness", "comparison": "equals",
            "threshold": {"magnitude": 4.0, "unit": "mm"},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted"},
        ), assumptions=(), unknowns=())

    def _repair(self, payload):
        from forge_roles.library import _declare_what_the_requirements_measure

        return _declare_what_the_requirements_measure(
            payload, self._requirements())

    def test_the_missing_declaration_is_written(self) -> None:
        payload = self._payload()
        notes = self._repair(payload)
        declared = {
            p["id"]: p["value"]
            for p in payload["components"][0]["parameters"]
        }
        self.assertEqual(declared["plate_thickness"],
                         {"magnitude": 4.0, "unit": "mm"})
        self.assertTrue(any("plate_thickness" in note for note in notes))

    def test_the_value_is_the_requirements_own_threshold(self) -> None:
        payload = self._payload()
        self._repair(payload)
        written = next(
            p for p in payload["components"][0]["parameters"]
            if p["id"] == "plate_thickness")
        self.assertEqual(written["value"]["magnitude"], 4.0)

    def test_the_geometry_is_not_touched(self) -> None:
        payload = self._payload()
        before = dict(payload["components"][0]["features"][0]["parameters"])
        self._repair(payload)
        self.assertEqual(
            payload["components"][0]["features"][0]["parameters"], before)

    def test_a_name_nothing_refers_to_is_not_invented(self) -> None:
        """Forge declares what the design already asked for by name. A
        parameter nothing mentions is the designer's to supply."""
        payload = self._payload(referenced=False)
        self._repair(payload)
        self.assertEqual(
            [p["id"] for p in payload["components"][0]["parameters"]],
            ["plate_width"])

    def test_the_document_decodes_afterwards(self) -> None:
        import json

        from forge_ir import SCHEMA_VERSION, Document

        payload = self._payload()
        self._repair(payload)
        component = payload["components"][0]
        component.update({"name": "Plate", "material": "pla_fdm"})
        document = Document.from_json(json.dumps({
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-0000000000e1",
            "project_id": "00000000-0000-4000-8000-0000000000ef",
            "name": "Plate", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [component]}))
        self.assertEqual(len(document.components), 1)


class TwoStagesNeedNotAgreeOnAWord(unittest.TestCase):
    """The architectural fault, and the one that cost three runs.

    `parameter:<id>` is the only binding in the vocabulary that requires two
    separate model calls, minutes apart, to invent the same identifier. The
    requirements engineer reads a brief and writes `parameter:base_width`;
    the designer then has to guess that word. A missing `interface_size:` or
    `entity:` is reported BLOCKED by the measurement layer and the run
    carries on. This one ended runs.

    And the invented word is not a label, it is a parameterisation. Told that
    a square plate must use ONE parameter in X and in Y, the designer wrote
    `["base_size", "base_size", "base_thickness"]` -- the first correctly
    square plate any run produced -- and was refused, because the record had
    already decided the plate has a `base_width` and a `base_height`. Forge
    was holding the model to a worse design than the one it wrote.
    """

    @staticmethod
    def _claim(identifier, measurement, magnitude, unit="mm"):
        return {
            "id": identifier, "statement": identifier,
            "measurement": measurement, "comparison": "equals",
            "threshold": {"magnitude": magnitude, "unit": unit},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted",
        }

    def _requirements(self, *claims):
        from forge_roles.library import RequirementSet

        return RequirementSet(
            requirements=tuple(claims), assumptions=(), unknowns=())

    @staticmethod
    def _payload(**declared):
        return {"components": [{
            "id": "spacer",
            "parameters": [
                {"id": name, "value": {"magnitude": value, "unit": "mm"}}
                for name, value in declared.items()],
            "features": [{"id": "base", "kind": "box", "parameters": {
                "size": {"vector": ["base_size", "base_size",
                                    "base_thickness"], "unit": "mm"}}}],
        }]}

    def _rebind(self, payload, requirements):
        from forge_roles.library import (
            _bind_each_claim_to_the_name_the_design_uses)

        return _bind_each_claim_to_the_name_the_design_uses(
            payload, requirements)

    def _bindings(self, requirements):
        return {
            dict(r)["id"]: dict(r).get("measurement")
            for r in requirements.requirements
        }

    def test_the_claim_moves_to_the_designs_own_word(self) -> None:
        reconciled, notes = self._rebind(
            self._payload(base_size=30.0, base_thickness=4.0),
            self._requirements(
                self._claim("REQ_W", "parameter:base_width", 30.0),
                self._claim("REQ_H", "parameter:base_height", 4.0)))
        self.assertEqual(self._bindings(reconciled), {
            "REQ_W": "parameter:base_size",
            "REQ_H": "parameter:base_thickness"})
        self.assertEqual(len(notes), 2)

    def test_no_threshold_moves(self) -> None:
        reconciled, _ = self._rebind(
            self._payload(base_size=30.0, base_thickness=4.0),
            self._requirements(self._claim("REQ_W", "parameter:base_width",
                                           30.0)))
        self.assertEqual(
            dict(reconciled.requirements[0])["threshold"],
            {"magnitude": 30.0, "unit": "mm"})

    def test_a_name_the_design_does_declare_is_left_alone(self) -> None:
        reconciled, notes = self._rebind(
            self._payload(base_width=30.0, base_thickness=4.0),
            self._requirements(self._claim("REQ_W", "parameter:base_width",
                                           30.0)))
        self.assertEqual(notes, [])
        self.assertEqual(self._bindings(reconciled)["REQ_W"],
                         "parameter:base_width")

    def test_two_parameters_at_one_figure_are_ambiguous(self) -> None:
        """Unless one of them is about the same part of the part."""
        reconciled, notes = self._rebind(
            self._payload(rib_height=30.0, slot_length=30.0),
            self._requirements(self._claim("REQ_W", "parameter:base_width",
                                           30.0)))
        self.assertEqual(notes, [])
        self.assertEqual(self._bindings(reconciled)["REQ_W"],
                         "parameter:base_width")

    def test_a_shared_word_settles_an_ambiguous_figure(self) -> None:
        reconciled, _ = self._rebind(
            self._payload(base_size=30.0, post_reach=30.0),
            self._requirements(self._claim("REQ_W", "parameter:base_width",
                                           30.0)))
        self.assertEqual(self._bindings(reconciled)["REQ_W"],
                         "parameter:base_size")

    def test_an_unrelated_parameter_at_the_same_figure_is_refused(self) -> None:
        """A coincidence of numbers is not a name for the same dimension."""
        reconciled, notes = self._rebind(
            self._payload(hole_spacing=30.0),
            self._requirements(self._claim("REQ_W", "parameter:base_width",
                                           30.0)))
        self.assertEqual(notes, [])
        self.assertEqual(self._bindings(reconciled)["REQ_W"],
                         "parameter:base_width")

    def test_a_different_figure_is_a_different_dimension(self) -> None:
        reconciled, notes = self._rebind(
            self._payload(base_size=25.0),
            self._requirements(self._claim("REQ_W", "parameter:base_width",
                                           30.0)))
        self.assertEqual(notes, [])
        self.assertEqual(self._bindings(reconciled)["REQ_W"],
                         "parameter:base_width")

    def test_two_claims_never_collide_on_one_parameter(self) -> None:
        reconciled, _ = self._rebind(
            self._payload(base_size=30.0),
            self._requirements(
                self._claim("REQ_W", "parameter:base_width", 30.0),
                self._claim("REQ_D", "parameter:base_depth", 30.0)))
        bound = [
            binding for binding in self._bindings(reconciled).values()
            if binding == "parameter:base_size"
        ]
        self.assertEqual(len(bound), 1)

    def test_a_parameter_already_measured_is_not_stolen(self) -> None:
        reconciled, notes = self._rebind(
            self._payload(base_size=30.0),
            self._requirements(
                self._claim("REQ_S", "parameter:base_size", 30.0),
                self._claim("REQ_W", "parameter:base_width", 30.0)))
        self.assertEqual(notes, [])
        self.assertEqual(self._bindings(reconciled)["REQ_S"],
                         "parameter:base_size")

    def test_units_are_converted_not_compared_by_number(self) -> None:
        payload = self._payload()
        payload["components"][0]["parameters"] = [
            {"id": "base_size", "value": {"magnitude": 3.0, "unit": "cm"}}]
        reconciled, _ = self._rebind(payload, self._requirements(
            self._claim("REQ_W", "parameter:base_width", 30.0)))
        self.assertEqual(self._bindings(reconciled)["REQ_W"],
                         "parameter:base_size")

    def test_the_square_plate_that_was_refused_now_builds(self) -> None:
        """The whole point, end to end: the answer run three threw away."""
        from forge_pipeline import verify_component
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import Intent

        answer = {"rationale": "x", "document": {
            "name": "Spacer Block", "components": [{
                "id": "spacer_block",
                "features": [
                    {"id": "base", "kind": "box", "parameters": {
                        "size": {"vector": ["base_size", "base_size",
                                            "base_thickness"], "unit": "mm"},
                        "centered": True}},
                    {"id": "post", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "post_diameter",
                                     "unit": "mm"},
                        "height": {"expression": "post_height", "unit": "mm"},
                        "origin": {"vector": [0, 0, "base_thickness / 2"],
                                   "unit": "mm"}}},
                    {"id": "body", "kind": "union", "inputs": ["base", "post"],
                     "parameters": {
                         "blend_radius": {"expression": "fillet_radius"}}},
                    {"id": "hole", "kind": "hole", "parameters": {
                        "diameter": {"expression": "hole_diameter",
                                     "unit": "mm"},
                        "position": {"vector": [0, 0, "base_thickness / 2"],
                                     "unit": "mm"},
                        "axis": [0.0, 0.0, 1.0]}},
                    {"id": "mounting_hole_1", "kind": "hole", "parameters": {
                        "diameter": {"expression": "mounting_hole_diameter",
                                     "unit": "mm"},
                        "position": {"vector": ["mounting_hole_distance / 2",
                                                0, "base_thickness / 2"],
                                     "unit": "mm"},
                        "axis": [0.0, 0.0, 1.0]}},
                    {"id": "mounting_hole_2", "kind": "hole", "parameters": {
                        "diameter": {"expression": "mounting_hole_diameter",
                                     "unit": "mm"},
                        "position": {"vector": ["-mounting_hole_distance / 2",
                                                0, "base_thickness / 2"],
                                     "unit": "mm"},
                        "axis": [0.0, 0.0, 1.0]}},
                ],
                "parameters": [
                    {"id": name, "value": {"magnitude": value, "unit": "mm"}}
                    for name, value in (
                        ("base_size", 30.0), ("base_thickness", 4.0),
                        ("post_diameter", 12.0), ("post_height", 10.0),
                        ("fillet_radius", 2.0), ("hole_diameter", 5.0),
                        ("mounting_hole_diameter", 3.0),
                        ("mounting_hole_distance", 20.0))],
            }]}}
        requirements = self._requirements(
            self._claim("REQ_BASE_WIDTH", "parameter:base_width", 30.0),
            self._claim("REQ_BASE_HEIGHT", "parameter:base_height", 4.0),
            self._claim("REQ_POST_DIAMETER", "parameter:post_diameter", 12.0),
            self._claim("REQ_BOUNDING_BOX_X", "bounding_box_x", 30.0),
            self._claim("REQ_BOUNDING_BOX_Y", "bounding_box_y", 30.0),
            {"id": "REQ_COUNT", "statement": "two mounting holes",
             "measurement": "feature_count:hole:mounting",
             "comparison": "equals",
             "threshold": {"magnitude": 2, "unit": ""},
             "type": "geometric", "verification": "exact_geometry",
             "strength": "hard", "source": "user", "state": "accepted"})
        draft = ForgeIRDesigner().parse(
            answer, requirements=requirements,
            intent=Intent(summary="A PLA spacer.", part_kind="spacer",
                          stated=(), implied=(), unstated=()),
            document_id="", project_id="")
        report = verify_component(
            draft.document, draft.document.components[0],
            measurement_depth=7)
        self.assertEqual(report.overall_status.value, "PASS")
        envelope = report.measurements["part"]["envelope_mm"]
        self.assertAlmostEqual(envelope[0], envelope[1], delta=0.01,
                               msg="the plate is square in X and Y")
        self.assertGreater(envelope[0], 29.0)


class WhichHolesTheCountIsAbout(unittest.TestCase):
    """Three holes, a count of two, and no tag on any of them.

    Arity settles the easy case and settled nothing here, so the designer was
    asked for a tag it had already told us where to put -- twice over, in the
    ids it chose and in how it built them.
    """

    @staticmethod
    def _hole(identifier, diameter="hole_diameter", spacing=None):
        position = {"vector": [0, 0, 0], "unit": "mm"}
        if spacing:
            position = {"vector": [spacing, 0, 0], "unit": "mm"}
        return {"id": identifier, "kind": "hole", "parameters": {
            "diameter": {"expression": diameter, "unit": "mm"},
            "position": position}}

    def _choose(self, features, tag="mounting", wanted=2):
        from forge_roles.library import _which_of_these_the_count_is_about

        chosen, why = _which_of_these_the_count_is_about(
            features, tag, wanted)
        return [f["id"] for f in chosen], why

    def _spacer(self):
        return [
            self._hole("hole"),
            self._hole("mounting_hole_1", "mounting_hole_diameter",
                       "mounting_hole_distance / 2"),
            self._hole("mounting_hole_2", "mounting_hole_diameter",
                       "-mounting_hole_distance / 2"),
        ]

    def test_the_ids_say_which_ones(self) -> None:
        chosen, why = self._choose(self._spacer())
        self.assertEqual(chosen, ["mounting_hole_1", "mounting_hole_2"])
        self.assertIn("in their id", why)

    def test_likeness_answers_when_the_ids_do_not(self) -> None:
        features = self._spacer()
        for index, feature in enumerate(features[1:], start=1):
            feature["id"] = f"h{index}"
        chosen, why = self._choose(features)
        self.assertEqual(chosen, ["h1", "h2"])
        self.assertIn("built alike", why)

    def test_it_asks_when_neither_singles_them_out(self) -> None:
        features = [self._hole(f"h{i}") for i in range(4)]
        self.assertEqual(self._choose(features)[0], [])

    def test_it_never_tags_more_than_the_count(self) -> None:
        features = self._spacer()
        self.assertEqual(self._choose(features, wanted=1)[0], [])

    def test_arity_is_left_to_the_caller(self) -> None:
        """Two features and a count of two is the older, simpler case."""
        self.assertEqual(self._choose(self._spacer()[1:], wanted=2)[0], [])

    def test_the_tag_is_applied_through_the_check(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import RequirementSet

        payload = {"components": [{"id": "spacer", "parameters": [],
                                   "features": self._spacer()}]}
        requirements = RequirementSet(requirements=({
            "id": "REQ_COUNT", "statement": "two mounting holes",
            "measurement": "feature_count:hole:mounting",
            "comparison": "equals",
            "threshold": {"magnitude": 2, "unit": ""},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted"},
        ), assumptions=(), unknowns=())
        notes, problems = ForgeIRDesigner()._require_the_counted_tags(
            payload, requirements=requirements)
        self.assertEqual(problems, [])
        tagged = [
            f["id"] for f in payload["components"][0]["features"]
            if "mounting" in (f.get("tags") or [])
        ]
        self.assertEqual(tagged, ["mounting_hole_1", "mounting_hole_2"])
        self.assertTrue(notes)


class ADeclaredNumberIsNotAMeasurement(unittest.TestCase):
    """An `equals` claim on a parameter, in any unit, has to be answerable.

    A collar whose two set screws are 90 degrees apart, built exactly right,
    reported BLOCKED: "compares for equality but declares no tolerance".
    Every safety factor, every declared angle, every dimensionless ratio did
    the same. A default tolerance is a hazard for a quantity somebody had to
    measure; a `parameter:` binding resolves a number the document declares,
    through exact arithmetic, to an interval of no width.
    """

    @staticmethod
    def _tolerance(magnitude, unit, measurement):
        from forge_pipeline.verify import _default_tolerance
        from forge_units import Q

        return _default_tolerance(Q(magnitude, unit), measurement)

    def test_an_angle_is_answerable(self) -> None:
        tolerance = self._tolerance(90.0, "deg", "parameter:screw_angle")
        self.assertIsNotNone(tolerance)
        self.assertGreater(tolerance.magnitude.midpoint, 0.0)

    def test_it_admits_arithmetic_noise_and_nothing_else(self) -> None:
        tolerance = self._tolerance(90.0, "deg", "parameter:screw_angle")
        self.assertLess(tolerance.magnitude.midpoint, 1e-6)

    def test_a_dimensionless_ratio_is_answerable(self) -> None:
        self.assertIsNotNone(
            self._tolerance(2.0, "", "parameter:safety_margin"))

    def test_a_zero_threshold_still_gets_an_epsilon(self) -> None:
        tolerance = self._tolerance(0.0, "deg", "parameter:rotation")
        self.assertIsNotNone(tolerance)
        self.assertGreater(tolerance.magnitude.midpoint, 0.0)

    def test_lengths_keep_the_build_specifications_figure(self) -> None:
        """0.05 mm is a real engineering tolerance and is not touched."""
        tolerance = self._tolerance(30.0, "mm", "parameter:base_size")
        self.assertAlmostEqual(tolerance.to("mm").magnitude.midpoint, 0.05)

    def test_a_measured_quantity_gets_nothing_invented(self) -> None:
        """The hazard the rule was written for: a mass nobody specified a
        tolerance for must not acquire one."""
        self.assertIsNone(self._tolerance(8.0, "g", "mass"))

    def test_a_count_is_still_exact(self) -> None:
        tolerance = self._tolerance(2.0, "", "feature_count:hole:mounting")
        self.assertEqual(tolerance.magnitude.midpoint, 0.0)


class ARepairThatMadeThePartWorse(unittest.TestCase):
    """The only parse-time repair that reinterprets geometry on a guess.

    Every other repair Forge applies is value-preserving -- the same number
    written a different way -- or structural, touching inputs and tags rather
    than shape. This one changes where a hole points, and on the collar it
    changed it from right to wrong.

    The model wrote the set screws with `axis: [1, 0, 0]`, which is the
    correct direction for a hole through the wall of a round body, and put
    them at x = +/-45 mm because it had read "90 degrees apart" as a 90 mm
    spacing. Both then lay on one line through the bore, so the check was
    right to object -- but the fault was the 45 mm, not the axis. Re-aiming
    to Z threw away the one correct field and left two holes 45 mm from the
    centre of a 12.5 mm radius, cutting nothing. One hole through the wall
    became none, and the run ended blocked with a plain ring.
    """

    @staticmethod
    def _hole(identifier, offset, axis, previous):
        return {"id": identifier, "kind": "hole", "inputs": [previous],
                "parameters": {
                    "diameter": {"magnitude": 4.0, "unit": "mm"},
                    "position": {"vector": [offset, 0, "length / 2"],
                                 "unit": "mm"},
                    "axis": list(axis)}}

    def _collar(self, spacing=90.0):
        return {
            "id": "collar",
            "parameters": [
                {"id": "outer_diameter",
                 "value": {"magnitude": 25.0, "unit": "mm"}},
                {"id": "length", "value": {"magnitude": 15.0, "unit": "mm"}},
                {"id": "screw_spacing",
                 "value": {"magnitude": spacing, "unit": "mm"}}],
            "features": [
                {"id": "body", "kind": "cylinder", "parameters": {
                    "diameter": {"expression": "outer_diameter",
                                 "unit": "mm"},
                    "height": {"expression": "length", "unit": "mm"}}},
                self._hole("screw_1", "screw_spacing / 2", [1, 0, 0], "body"),
                self._hole("screw_2", "-screw_spacing / 2", [1, 0, 0],
                           "screw_1")],
        }

    def _plate(self, spacing=20.0):
        return {
            "id": "spacer",
            "parameters": [
                {"id": "plate_size",
                 "value": {"magnitude": 30.0, "unit": "mm"}},
                {"id": "hole_spacing",
                 "value": {"magnitude": spacing, "unit": "mm"}}],
            "features": [
                {"id": "base", "kind": "box", "parameters": {
                    "size": {"vector": ["plate_size", "plate_size", 4],
                             "unit": "mm"}}},
                self._hole("h1", "hole_spacing / 2", [1, 0, 0], "base"),
                self._hole("h2", "-hole_spacing / 2", [1, 0, 0], "h1")],
        }

    @staticmethod
    def _repair(component):
        from forge_roles.library import _re_aim_holes_that_became_one_line

        return _re_aim_holes_that_became_one_line(
            component["features"], component)

    @staticmethod
    def _axes(component):
        return [
            list(f["parameters"]["axis"]) for f in component["features"][1:]
        ]

    def test_a_radial_axis_outside_the_part_is_left_alone(self) -> None:
        collar = self._collar()
        self.assertEqual(self._repair(collar), [])
        self.assertEqual(self._axes(collar), [[1, 0, 0], [1, 0, 0]])

    def test_a_plate_is_still_re_aimed(self) -> None:
        """The case this repair was written for, and it still works: holes
        spread inside the part, drilled the wrong way."""
        plate = self._plate()
        self.assertEqual(len(self._repair(plate)), 1)
        self.assertEqual(self._axes(plate), [[0.0, 0.0, 1.0]] * 2)

    def test_the_boundary_is_the_part_not_the_parameter_table(self) -> None:
        """A first draft took the largest declared length as the part's size,
        which on the collar included the bogus 90 mm itself -- so the part
        measured 90 mm across, 45 mm sat comfortably inside it, and the check
        waved through the very number it existed to catch."""
        from forge_roles.library import _how_big_the_part_can_be

        self.assertAlmostEqual(_how_big_the_part_can_be(self._collar()), 12.5)
        self.assertAlmostEqual(_how_big_the_part_can_be(self._plate()), 15.0)

    def test_a_spacing_that_fits_is_still_a_spacing(self) -> None:
        collar = self._collar(spacing=10.0)
        self.assertEqual(len(self._repair(collar)), 1)

    def test_with_no_primitive_nothing_is_assumed(self) -> None:
        component = self._plate()
        component["features"][0] = {
            "id": "base", "kind": "extrude", "inputs": ["profile"],
            "parameters": {"distance": {"magnitude": 4.0, "unit": "mm"}}}
        from forge_roles.library import _how_big_the_part_can_be

        self.assertIsNone(_how_big_the_part_can_be(component))
        # and the repair falls back to what it always did
        self.assertEqual(len(self._repair(component)), 1)


class AnAngleWrittenAsASpacing(unittest.TestCase):
    """90 mm on a part 25 mm across, and the brief says 90 degrees."""

    BRIEF = ("A machined aluminium shaft collar. The outer diameter is 25 mm "
             "and it is 15 mm long. A 12 mm bore runs all the way through. "
             "Two 4 mm set screw holes pass through the wall, 90 degrees "
             "apart, both halfway along the length.")

    @staticmethod
    def _component(magnitude, unit="mm", name="mounting_hole_spacing"):
        return {
            "id": "collar",
            "parameters": [
                {"id": "outer_diameter",
                 "value": {"magnitude": 25.0, "unit": "mm"}},
                {"id": name, "value": {"magnitude": magnitude, "unit": unit}}],
            "features": [{"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "outer_diameter", "unit": "mm"},
                "height": {"magnitude": 15.0, "unit": "mm"}}}],
        }

    def _problems(self, component, brief=None):
        from forge_roles.library import _an_angle_written_as_a_length

        return _an_angle_written_as_a_length(
            component, self.BRIEF if brief is None else brief)

    def test_it_names_the_figure_and_the_unit_it_should_have(self) -> None:
        problem = self._problems(self._component(90.0))[0]
        self.assertIn("90 mm", problem)
        self.assertIn("90 deg", problem)
        self.assertIn("25 mm across", problem)

    def test_it_prescribes_the_construction(self) -> None:
        problem = self._problems(self._component(90.0))[0]
        self.assertIn("do not differ in POSITION", problem)
        self.assertIn("`axis`", problem)
        self.assertIn("centre line", problem)

    def test_a_length_that_fits_the_part_is_not_an_angle(self) -> None:
        """A 20 mm spacing on a 25 mm part is a spacing, whatever else in the
        brief happens to be 20 of something."""
        self.assertEqual(
            self._problems(
                self._component(20.0),
                "A collar 25 mm across with holes 20 mm apart and a 20 degree "
                "chamfer."),
            [])

    def test_a_figure_the_brief_states_as_a_length_is_left_alone(self) -> None:
        self.assertEqual(
            self._problems(
                self._component(90.0),
                "A 90 mm bar with two holes 90 degrees apart."),
            [])

    def test_an_angle_declared_in_degrees_is_not_the_fault(self) -> None:
        self.assertEqual(
            self._problems(self._component(90.0, unit="deg")), [])

    def test_a_brief_with_no_angle_says_nothing(self) -> None:
        self.assertEqual(
            self._problems(self._component(90.0),
                           "A collar 25 mm across and 15 mm long."), [])

    def test_no_brief_means_no_opinion(self) -> None:
        self.assertEqual(self._problems(self._component(90.0), ""), [])


class AStatedAngleReachesTheDesign(unittest.TestCase):
    """The designer works from the record, so the record has to carry it.

    Six requirements, none of them the brief's 90 degrees. Forge noticed and
    said so in the run, and that was the end of it: the designer's whole
    input had no angle in it anywhere, and out of the brief's prose it made a
    90 mm spacing.
    """

    COLLAR = ("A machined aluminium shaft collar. The outer diameter is 25 mm "
              "and it is 15 mm long. Two 4 mm set screw holes pass through "
              "the wall, 90 degrees apart.")

    @staticmethod
    def _claim(identifier, measurement, magnitude, unit="mm"):
        return {"id": identifier, "statement": identifier,
                "measurement": measurement, "comparison": "equals",
                "threshold": {"magnitude": magnitude, "unit": unit}}

    def _carry(self, brief, requirements):
        from forge_roles.library import (
            _an_angle_the_brief_states_and_nothing_checks)

        return _an_angle_the_brief_states_and_nothing_checks(
            brief, requirements)

    def test_the_angle_becomes_a_requirement(self) -> None:
        requirements = [self._claim("REQ_OD", "parameter:outer_diameter",
                                    25.0)]
        self.assertEqual(len(self._carry(self.COLLAR, requirements)), 1)
        added = requirements[-1]
        self.assertTrue(added["measurement"].startswith("angle_between:hole:"),
                        added["measurement"])
        self.assertEqual(added["threshold"],
                         {"magnitude": 90.0, "unit": "deg"})

    def test_the_tag_reconciles_against_the_designs_own_word(self) -> None:
        """Forge names the two features `spaced`; a design that calls them
        `set_screw` is not wrong, and must not be refused for it."""
        from forge_roles.library import (
            RequirementSet, _bind_each_tag_to_the_word_the_design_uses)

        requirements = []
        self._carry(self.COLLAR, requirements)
        payload = {"components": [{"id": "collar", "parameters": [],
            "features": [
                {"id": "bore", "kind": "hole", "parameters": {}},
                {"id": "s1", "kind": "hole", "tags": ["set_screw"],
                 "parameters": {}},
                {"id": "s2", "kind": "hole", "tags": ["set_screw"],
                 "parameters": {}}]}]}
        reconciled, notes = _bind_each_tag_to_the_word_the_design_uses(
            payload, RequirementSet(requirements=tuple(requirements),
                                    assumptions=(), unknowns=()))
        self.assertTrue(notes)
        self.assertEqual(
            dict(reconciled.requirements[0])["measurement"],
            "angle_between:hole:set_screw")

    def test_a_tag_that_could_mean_two_things_is_left_alone(self) -> None:
        from forge_roles.library import (
            RequirementSet, _bind_each_tag_to_the_word_the_design_uses)

        requirements = []
        self._carry(self.COLLAR, requirements)
        payload = {"components": [{"id": "collar", "parameters": [],
            "features": [
                {"id": "a1", "kind": "hole", "tags": ["set_screw"],
                 "parameters": {}},
                {"id": "a2", "kind": "hole", "tags": ["set_screw"],
                 "parameters": {}},
                {"id": "b1", "kind": "hole", "tags": ["dowel"],
                 "parameters": {}},
                {"id": "b2", "kind": "hole", "tags": ["dowel"],
                 "parameters": {}}]}]}
        _, notes = _bind_each_tag_to_the_word_the_design_uses(
            payload, RequirementSet(requirements=tuple(requirements),
                                    assumptions=(), unknowns=()))
        self.assertEqual(notes, [])

    def test_an_angle_already_carried_is_not_doubled(self) -> None:
        """Carried by the model: no second claim, but measured on the part.

        Every collar run whose record carried the 90 degrees bound it to
        `parameter:<angle>`, which a hole's direction never reads -- and
        which reads back 90 over two parallel holes. The model's claim keeps
        its id and threshold and is rebound to the geometry."""
        requirements = [self._claim("REQ_A", "parameter:screw_angle", 90.0,
                                    "deg")]
        notes = self._carry(self.COLLAR, requirements)
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["id"], "REQ_A")
        self.assertEqual(requirements[0]["measurement"],
                         "angle_between:hole:spaced")
        self.assertIn("rebound REQ_A", notes[0])

    def test_an_angle_carried_by_a_measurement_is_left_alone(self) -> None:
        requirements = [self._claim("REQ_A", "angle_between:hole:set_screw",
                                    90.0, "deg")]
        self.assertEqual(self._carry(self.COLLAR, requirements), [])
        self.assertEqual(requirements[0]["measurement"],
                         "angle_between:hole:set_screw")

    def test_an_angle_between_axial_bolt_holes_is_not_an_axis_angle(
        self,
    ) -> None:
        """`angle_between` measures axes. Two bolt holes 180 degrees apart on
        a circle are parallel, so binding it there would fail a right part."""
        requirements = []
        self.assertEqual(self._carry(
            "A flange 80 mm across with two 6 mm bolt holes 180 degrees "
            "apart on a 60 mm circle.", requirements), [])
        self.assertEqual(self._carry(
            "A hub with two 5 mm holes 90 degrees apart.", requirements), [])
        self.assertEqual(requirements, [])

    def test_a_brief_with_no_angle_gains_nothing(self) -> None:
        requirements = []
        self.assertEqual(
            self._carry("A 30 mm square plate 4 mm thick.", requirements), [])
        self.assertEqual(requirements, [])

    def test_two_angles_are_a_choice_forge_does_not_make(self) -> None:
        requirements = []
        self.assertEqual(
            self._carry("A bracket with a 30 degree web and a 45 degree "
                        "chamfer.", requirements),
            [])
        self.assertEqual(requirements, [])

    def test_it_runs_inside_the_requirements_repair(self) -> None:
        from forge_roles.library import _normalise_requirements

        answer, notes, _ = _normalise_requirements(
            {"requirements": [self._claim("REQ_OD",
                                          "parameter:outer_diameter", 25.0)]},
            self.COLLAR)
        self.assertTrue(
            any(str(r.get("measurement", "")).startswith("angle_between:")
                for r in answer["requirements"]),
            [r.get("measurement") for r in answer["requirements"]])
        self.assertTrue(any("the brief states the angle" in n for n in notes), notes)


class TheCollarBuiltTheWayTheGuideTeaches(unittest.TestCase):
    """End to end: two holes on the centre line, axes 90 degrees apart."""

    BRIEF = ("A machined aluminium shaft collar. The outer diameter is 25 mm "
             "and it is 15 mm long. A 12 mm bore runs all the way through on "
             "the axis. Two 4 mm set screw holes pass through the wall from "
             "the outside into the bore, 90 degrees apart, both halfway along "
             "the length.")

    def _draft(self, features, parameters):
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import (
            Intent, RequirementSet, _normalise_requirements)

        def claim(identifier, measurement, magnitude, unit="mm"):
            return {"id": identifier, "statement": identifier,
                    "measurement": measurement, "comparison": "equals",
                    "threshold": {"magnitude": magnitude, "unit": unit}}

        answer, _, _ = _normalise_requirements({"requirements": [
            claim("REQ_OD", "parameter:outer_diameter", 25.0),
            claim("REQ_LEN", "parameter:length", 15.0),
            claim("REQ_BORE", "parameter:bore_diameter", 12.0),
            claim("REQ_SSD", "parameter:set_screw_hole_diameter", 4.0),
        ], "assumptions": [], "unknowns": []}, self.BRIEF)
        return ForgeIRDesigner().parse(
            {"rationale": "x", "document": {"name": "Collar", "components": [
                {"id": "collar", "parameters": parameters,
                 "features": features}]}},
            requirements=RequirementSet(
                requirements=tuple(answer["requirements"]),
                assumptions=(), unknowns=()),
            intent=Intent(summary="A shaft collar.", part_kind="collar",
                          stated=(), implied=(), unstated=()),
            brief=self.BRIEF, document_id="", project_id="")

    @staticmethod
    def _body():
        return [
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "outer_diameter", "unit": "mm"},
                "height": {"expression": "length", "unit": "mm"}}},
            {"id": "bore", "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": {"expression": "bore_diameter", "unit": "mm"},
                "position": {"vector": [0, 0, "length / 2"], "unit": "mm"},
                "axis": [0.0, 0.0, 1.0]}},
        ]

    @staticmethod
    def _screw(identifier, axis, previous):
        return {"id": identifier, "kind": "hole", "inputs": [previous],
                "tags": ["set_screw"], "parameters": {
                    "diameter": {"expression": "set_screw_hole_diameter",
                                 "unit": "mm"},
                    "position": {"vector": [0, 0, "length / 2"],
                                 "unit": "mm"},
                    "axis": list(axis)}}

    def _parameters(self, angle_name="set_screw_angle"):
        return [
            {"id": "outer_diameter",
             "value": {"magnitude": 25.0, "unit": "mm"}},
            {"id": "length", "value": {"magnitude": 15.0, "unit": "mm"}},
            {"id": "bore_diameter",
             "value": {"magnitude": 12.0, "unit": "mm"}},
            {"id": "set_screw_hole_diameter",
             "value": {"magnitude": 4.0, "unit": "mm"}},
            {"id": angle_name, "value": {"magnitude": 90.0, "unit": "deg"}},
        ]

    def test_it_builds_and_passes(self) -> None:
        from forge_pipeline import verify_component

        draft = self._draft(
            self._body() + [self._screw("set_screw_1", [1, 0, 0], "bore"),
                            self._screw("set_screw_2", [0, 1, 0],
                                        "set_screw_1")],
            self._parameters())
        report = verify_component(
            draft.document, draft.document.components[0],
            measurement_depth=7)
        self.assertEqual(report.overall_status.value, "PASS")

    def test_all_three_holes_are_open(self) -> None:
        from forge_pipeline import verify_component

        draft = self._draft(
            self._body() + [self._screw("set_screw_1", [1, 0, 0], "bore"),
                            self._screw("set_screw_2", [0, 1, 0],
                                        "set_screw_1")],
            self._parameters())
        report = verify_component(
            draft.document, draft.document.components[0],
            measurement_depth=7)
        self.assertEqual(report.measurements["part"]["open_holes"], 3)

    def test_the_angle_is_measured_between_the_two_holes(self) -> None:
        """Bound to the built geometry, under whichever word the design tags
        them with."""
        draft = self._draft(
            self._body() + [self._screw("set_screw_1", [1, 0, 0], "bore"),
                            self._screw("set_screw_2", [0, 1, 0],
                                        "set_screw_1")],
            self._parameters())
        bindings = [r.measurement or "" for r in draft.document.requirements]
        self.assertIn("angle_between:hole:set_screw", bindings)

    def test_the_runs_own_answer_is_built_the_way_the_brief_says(
        self,
    ) -> None:
        """The run's answer, 90 degrees written as a 90 mm spacing.

        This used to be refused with three accurate messages, and the model
        answered the same way three runs running. Every part of the fix is
        already fixed by the brief and the design, so Forge makes it: both
        screws through the design's own point on the axis, the second turned
        by the parameter, which is now in degrees -- and the part passes."""
        from forge_pipeline import verify_component

        screws = [
            {"id": "screw_1", "kind": "hole", "inputs": ["bore"],
             "parameters": {
                 "diameter": {"expression": "set_screw_hole_diameter",
                              "unit": "mm"},
                 "position": {"vector": ["mounting_hole_spacing / 2", 0,
                                         "length / 2"], "unit": "mm"},
                 "axis": [1.0, 0.0, 0.0]}},
            {"id": "screw_2", "kind": "hole", "inputs": ["screw_1"],
             "parameters": {
                 "diameter": {"expression": "set_screw_hole_diameter",
                              "unit": "mm"},
                 "position": {"vector": ["-mounting_hole_spacing / 2", 0,
                                         "length / 2"], "unit": "mm"},
                 "axis": [1.0, 0.0, 0.0]}},
        ]
        parameters = self._parameters("mounting_hole_spacing")
        parameters[-1]["value"] = {"magnitude": 90.0, "unit": "mm"}
        draft = self._draft(self._body() + screws, parameters)
        component = draft.payload["components"][0]
        spacing = next(p for p in component["parameters"]
                       if p["id"] == "mounting_hole_spacing")
        self.assertEqual(spacing["value"], {"magnitude": 90.0, "unit": "deg"})
        one, two = (f for f in component["features"]
                    if f["id"] in ("screw_1", "screw_2"))
        self.assertEqual(one["parameters"]["position"]["vector"],
                         [0, 0, "length / 2"])
        self.assertEqual(two["parameters"]["position"]["vector"],
                         [0, 0, "length / 2"])
        self.assertIn("mounting_hole_spacing", " ".join(
            str(c) for c in two["parameters"]["axis"]))
        self.assertTrue(any("not a distance" in n for n in draft.notes))
        report = verify_component(
            draft.document, draft.document.components[0],
            measurement_depth=7)
        self.assertEqual(report.overall_status.value, "PASS")
        self.assertEqual(report.measurements["part"]["open_holes"], 3)

    def _repaired(self, screws, parameters=None):
        from forge_pipeline import verify_component

        draft = self._draft(self._body() + screws,
                            parameters or self._parameters())
        return draft, verify_component(
            draft.document, draft.document.components[0],
            measurement_depth=7)

    @staticmethod
    def _placed(identifier, position, axis, previous):
        return {"id": identifier, "kind": "hole", "inputs": [previous],
                "parameters": {
                    "diameter": {"expression": "set_screw_hole_diameter",
                                 "unit": "mm"},
                    "position": {"vector": list(position), "unit": "mm"},
                    "axis": list(axis)}}

    def test_an_angle_written_in_degrees_into_a_position(self) -> None:
        """Observed: `+/- spacing / 2` with spacing = 90 deg. Will not compile;
        now it is not asked to."""
        parameters = self._parameters("set_screw_hole_spacing")
        draft, report = self._repaired([
            self._placed("s1", ["set_screw_hole_spacing / 2", 0,
                                "length / 2"], [0, 1, 0], "bore"),
            self._placed("s2", ["-set_screw_hole_spacing / 2", 0,
                                "length / 2"], [0, 1, 0], "s1")], parameters)
        self.assertEqual(report.overall_status.value, "PASS")

    def test_screws_drilled_down_the_shaft(self) -> None:
        """Observed: both screws parallel to the bore at +/- length / 4. The
        spread goes, and the design's declared angle drives the turn."""
        draft, report = self._repaired([
            self._placed("s1", ["length / 4", 0, "length / 2"], [0, 0, 1],
                         "bore"),
            self._placed("s2", ["-length / 4", 0, "length / 2"], [0, 0, 1],
                         "s1")])
        self.assertEqual(report.overall_status.value, "PASS")
        axis = draft.payload["components"][0]["features"][3]["parameters"][
            "axis"]
        self.assertIn("set_screw_angle", " ".join(str(c) for c in axis))

    def test_parallel_screws_across_the_body(self) -> None:
        """Observed, on a run that completed: both screws along Y at x =
        +/- length / 2. Parallel is 0 degrees, whatever way they point."""
        _, report = self._repaired([
            self._placed("s1", ["length / 2", 0, "length / 2"], [0, 1, 0],
                         "bore"),
            self._placed("s2", ["-length / 2", 0, "length / 2"], [0, 1, 0],
                         "s1")])
        self.assertEqual(report.overall_status.value, "PASS")

    def test_a_spread_only_the_design_could_mean_is_left_alone(self) -> None:
        """Across the body, different directions, apart by a length: that is
        not provably wrong, so it is gated, not rebuilt."""
        _, report = self._repaired([
            self._placed("s1", [0, 0, "length / 4"], [1, 0, 0], "bore"),
            self._placed("s2", [0, 0, "3 * length / 4"], [0, 1, 0], "s1")])
        angle = next(r for r in report.gate_results
                     if r.gate.identifier == "REQ_ANGLE")
        self.assertEqual(angle.status.value, "PASS")
        holes = {h["feature"]: h["centre_mm"]
                 for h in report.measurements["part"]["holes"]}
        self.assertNotEqual(holes["s1"][2], holes["s2"][2])

    def test_bolt_holes_on_a_circle_are_never_turned(self) -> None:
        from forge_roles.library import _an_angle_used_as_a_spacing

        component = {"id": "flange", "parameters": [
            {"id": "d", "value": {"magnitude": 80.0, "unit": "mm"}},
            {"id": "t", "value": {"magnitude": 6.0, "unit": "mm"}},
            {"id": "pcd", "value": {"magnitude": 60.0, "unit": "mm"}}],
            "features": [
                {"id": "body", "kind": "cylinder", "parameters": {
                    "diameter": {"expression": "d"},
                    "height": {"expression": "t"}}},
                self._placed("b1", ["pcd / 2", 0, "t / 2"], [0, 0, 1], "body"),
                self._placed("b2", ["-pcd / 2", 0, "t / 2"], [0, 0, 1], "b1")]}
        from forge_roles.library import RequirementSet
        claims = RequirementSet(requirements=({
            "id": "A", "measurement": "angle_between:hole:bolt",
            "comparison": "equals",
            "threshold": {"magnitude": 180.0, "unit": "deg"}},),
            assumptions=(), unknowns=())
        before = json.dumps(component, sort_keys=True)
        self.assertEqual(_an_angle_used_as_a_spacing(
            component, "A flange 80 mm across, 6 mm thick, with two set screw "
            "holes 90 degrees apart on a 60 mm circle.", claims), [])
        self.assertEqual(json.dumps(component, sort_keys=True), before)


class WhereTheHolesPoint(unittest.TestCase):
    """The first measurement of a RELATIONSHIP between two features.

    A collar passed every geometric gate it had and was still the wrong part.
    Its two set screw holes were drilled parallel to the bore, down the
    length of the wall, 180 degrees apart, opening into nothing. They cut
    material, they reached the surface, their bores survived, every declared
    dimension drove something -- so GEOM_BORES_SURVIVE,
    GEOM_FEATURES_CONTRIBUTE and the rest were all satisfied, correctly.
    Nothing in the system looked at where the holes POINTED.

    The brief said "90 degrees apart". The only binding for that was
    `parameter:<id>`, which reads back a number the design wrote about
    itself, and the design duly declared `angle = 90 deg` while building 0.
    """

    BRIEF = ("A machined aluminium shaft collar. The outer diameter is 25 mm "
             "and it is 15 mm long. A 12 mm bore runs all the way through on "
             "the axis. Two 4 mm set screw holes pass through the wall from "
             "the outside into the bore, 90 degrees apart, both halfway along "
             "the length.")

    @staticmethod
    def _screw(identifier, position, axis, previous, tags=("set_screw",)):
        feature = {"id": identifier, "kind": "hole", "inputs": [previous],
                   "parameters": {
                       "diameter": {"magnitude": 4.0, "unit": "mm"},
                       "position": {"vector": list(position), "unit": "mm"},
                       "axis": list(axis)}}
        if tags:
            feature["tags"] = list(tags)
        return feature

    def _component(self, screws):
        return {
            "id": "collar", "name": "Collar",
            "material": "aluminium_6061_t6", "parameters": [],
            "features": [
                {"id": "body", "kind": "cylinder", "parameters": {
                    "diameter": {"magnitude": 25.0, "unit": "mm"},
                    "height": {"magnitude": 15.0, "unit": "mm"}}},
                {"id": "bore", "kind": "hole", "inputs": ["body"],
                 "parameters": {
                     "diameter": {"magnitude": 12.0, "unit": "mm"},
                     "position": {"vector": [0, 0, 7.5], "unit": "mm"},
                     "axis": [0.0, 0.0, 1.0]}},
            ] + screws,
        }

    def _measure(self, screws, binding="angle_between:hole:set_screw"):
        import json

        from forge_ir import SCHEMA_VERSION, Document
        from forge_kernel import Compiler
        from forge_pipeline.measure import resolve_measurement

        component = self._component(screws)
        document = Document.from_json(json.dumps({
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-000000000a01",
            "project_id": "00000000-0000-4000-8000-000000000a0f",
            "name": "Collar", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [component]}))
        built = Compiler().compile_component(document.components[0])
        from forge_geom.measure import measure_mass_properties

        return resolve_measurement(
            binding, component=document.components[0], part=built,
            properties=measure_mass_properties(built.solid, max_depth=4))

    def _radial(self, first=(1, 0, 0), second=(0, 1, 0)):
        return [self._screw("s1", [0, 0, 7.5], first, "bore"),
                self._screw("s2", [0, 0, 7.5], second, "s1")]

    def test_two_radial_holes_ninety_degrees_apart(self) -> None:
        measured = self._measure(self._radial())
        self.assertTrue(measured.ok, measured.blocked_reason)
        self.assertAlmostEqual(
            measured.value.to("deg").magnitude.midpoint, 90.0, places=6)

    def test_the_part_the_run_actually_built(self) -> None:
        """Both drilled down Z, so zero degrees apart however far apart their
        positions are. This is the case every other gate called fine."""
        measured = self._measure([
            self._screw("s1", [10, 0, 7.5], [0, 0, 1], "bore"),
            self._screw("s2", [-10, 0, 7.5], [0, 0, 1], "s1")])
        self.assertTrue(measured.ok, measured.blocked_reason)
        self.assertAlmostEqual(
            measured.value.to("deg").magnitude.midpoint, 0.0, places=6)

    def test_it_measures_the_part_not_a_declared_number(self) -> None:
        """A design may declare whatever it likes; this reads the axes."""
        measured = self._measure(self._radial(second=(0.7071, 0.7071, 0.0)))
        self.assertAlmostEqual(
            measured.value.to("deg").magnitude.midpoint, 45.0, places=3)

    def test_the_bore_is_not_one_of_the_pair(self) -> None:
        """Three holes, and the tag says which two the angle is about."""
        measured = self._measure(self._radial())
        self.assertEqual(sorted(measured.detail["between"]), ["s1", "s2"])

    def test_an_angle_is_between_exactly_two(self) -> None:
        third = self._screw("s3", [0, 0, 7.5], [0.7071, -0.7071, 0.0], "s2")
        for screws in (self._radial() + [third],
                       [self._screw("s1", [0, 0, 7.5], [1, 0, 0], "bore")]):
            measured = self._measure(screws)
            self.assertFalse(measured.ok)
            self.assertIn("between two features", measured.blocked_reason)

    def test_an_untagged_pair_says_what_to_tag(self) -> None:
        measured = self._measure(
            [self._screw("s1", [0, 0, 7.5], [1, 0, 0], "bore", ()),
             self._screw("s2", [0, 0, 7.5], [0, 1, 0], "s1", ())])
        self.assertFalse(measured.ok)
        self.assertIn("tags", measured.detail["hint"])

    def test_the_binding_is_in_the_vocabulary(self) -> None:
        from forge_ir.measurements import (
            PARAMETERISED_MEASUREMENTS, parse_measurement, vocabulary_help)

        self.assertIn("angle_between", PARAMETERISED_MEASUREMENTS)
        binding = parse_measurement("angle_between:hole:set_screw")
        self.assertEqual(
            (binding.kind, binding.argument, binding.sub_argument),
            ("angle_between", "hole", "set_screw"))
        self.assertIn("angle_between", vocabulary_help())

    def test_a_tagless_binding_is_refused_with_the_reason(self) -> None:
        from forge_ir.measurements import MeasurementError, parse_measurement

        with self.assertRaises(MeasurementError) as caught:
            parse_measurement("angle_between:hole")
        self.assertIn("needs a tag", str(caught.exception))

    # -- the tolerance, and why it is not an epsilon ----------------------
    def test_an_angular_claim_is_answerable_at_all(self) -> None:
        from forge_pipeline.verify import _default_tolerance
        from forge_units import Q

        tolerance = _default_tolerance(
            Q(90.0, "deg"), "angle_between:hole:set_screw")
        self.assertIsNotNone(tolerance)

    def test_it_admits_a_hand_written_direction_vector(self) -> None:
        """`[0.7071, 0.7071, 0]` is 45 degrees written by a person, and an
        epsilon would call it wrong."""
        from forge_pipeline.verify import _default_tolerance
        from forge_units import Q

        tolerance = _default_tolerance(
            Q(45.0, "deg"), "angle_between:hole:set_screw")
        measured = self._measure(
            self._radial(second=(0.7071, 0.7071, 0.0))
        ).value.to("deg").magnitude.midpoint
        self.assertLess(abs(measured - 45.0),
                        tolerance.to("deg").magnitude.midpoint)

    def test_it_refuses_every_mistake_this_check_is_for(self) -> None:
        from forge_pipeline.verify import _default_tolerance
        from forge_units import Q

        slack = _default_tolerance(
            Q(90.0, "deg"), "angle_between:hole:set_screw"
        ).to("deg").magnitude.midpoint
        self.assertLess(slack, 45.0)


class TheAngleIsCheckedOnTheBuiltPart(unittest.TestCase):
    """Forge's added angle requirement binds to the geometry.

    Binding it to `parameter:<id>` was the first thing tried and it does not
    work: the run after that change declared `angle = 90 deg`, drilled both
    set screws parallel to the bore, and the claim came back unmeasurable
    rather than false.
    """

    BRIEF = WhereTheHolesPoint.BRIEF

    @staticmethod
    def _claim(identifier, measurement, magnitude, unit="mm"):
        return {"id": identifier, "statement": identifier,
                "measurement": measurement, "comparison": "equals",
                "threshold": {"magnitude": magnitude, "unit": unit}}

    def _carried(self, requirements):
        from forge_roles.library import (
            _an_angle_the_brief_states_and_nothing_checks)

        _an_angle_the_brief_states_and_nothing_checks(self.BRIEF, requirements)
        return requirements[-1]

    def test_it_binds_to_the_geometry(self) -> None:
        added = self._carried([self._claim("REQ_OD",
                                           "parameter:outer_diameter", 25.0)])
        self.assertTrue(
            added["measurement"].startswith("angle_between:hole:"),
            added["measurement"])

    def test_it_never_binds_to_a_declared_parameter(self) -> None:
        added = self._carried([])
        self.assertNotIn("parameter:", added["measurement"])

    def test_it_reuses_the_tag_a_count_already_named(self) -> None:
        """The record has already said which features these are."""
        added = self._carried([
            {"id": "REQ_N", "statement": "two", "comparison": "equals",
             "measurement": "feature_count:hole:set_screw",
             "threshold": {"magnitude": 2, "unit": ""}}])
        self.assertEqual(added["measurement"],
                         "angle_between:hole:set_screw")

    def test_the_tag_reaches_the_tagging_repair(self) -> None:
        from forge_roles.library import _tags_the_requirements_count

        class Record:
            requirements = ({"id": "REQ_ANGLE",
                             "measurement": "angle_between:hole:spaced"},)

        self.assertIn(("hole", "spaced"),
                      _tags_the_requirements_count(Record()))

    def test_an_angle_is_two_features_for_the_tagging_repair(self) -> None:
        from forge_roles.library import _how_many_of_each_tag

        class Record:
            requirements = ({"id": "REQ_ANGLE", "comparison": "equals",
                             "measurement": "angle_between:hole:spaced",
                             "threshold": {"magnitude": 90.0,
                                           "unit": "deg"}},)

        self.assertEqual(_how_many_of_each_tag(Record())[("hole", "spaced")],
                         2)

    def test_end_to_end_the_wrong_collar_fails_with_a_number(self) -> None:
        from forge_pipeline import verify_component
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import (
            Intent, RequirementSet, _normalise_requirements)

        answer, _, _ = _normalise_requirements({"requirements": [
            self._claim("REQ_OD", "parameter:outer_diameter", 25.0),
            self._claim("REQ_LEN", "parameter:length", 15.0),
        ], "assumptions": [], "unknowns": []}, self.BRIEF)

        def screw(identifier, position, axis, previous):
            return {"id": identifier, "kind": "hole", "inputs": [previous],
                    "parameters": {
                        "diameter": {"magnitude": 4.0, "unit": "mm"},
                        "position": {"vector": list(position), "unit": "mm"},
                        "axis": list(axis)}}

        body = [
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "outer_diameter", "unit": "mm"},
                "height": {"expression": "length", "unit": "mm"}}},
            {"id": "bore", "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "position": {"vector": [0, 0, 7.5], "unit": "mm"},
                "axis": [0.0, 0.0, 1.0]}}]
        parameters = [
            {"id": "outer_diameter",
             "value": {"magnitude": 25.0, "unit": "mm"}},
            {"id": "length", "value": {"magnitude": 15.0, "unit": "mm"}}]

        def report(screws):
            draft = ForgeIRDesigner().parse(
                {"rationale": "x", "document": {"name": "Collar",
                 "components": [{"id": "collar", "parameters": parameters,
                                 "features": body + screws}]}},
                requirements=RequirementSet(
                    requirements=tuple(answer["requirements"]),
                    assumptions=(), unknowns=()),
                intent=Intent(summary="A collar.", part_kind="collar",
                              stated=(), implied=(), unstated=()),
                brief=self.BRIEF, document_id="", project_id="")
            return verify_component(
                draft.document, draft.document.components[0],
                measurement_depth=7)

        # Radial, through one point, and 45 degrees apart: a design Forge
        # has no business rebuilding, and the wrong part. The gate says so,
        # with the number.
        wrong = report([screw("s1", [0, 0, 7.5], [1, 0, 0], "bore"),
                        screw("s2", [0, 0, 7.5],
                              [0.7071067811865476, 0.7071067811865476, 0],
                              "s1")])
        self.assertEqual(wrong.overall_status.value, "FAIL")
        angle = next(r for r in wrong.gate_results
                     if r.gate.identifier == "REQ_ANGLE")
        self.assertEqual(angle.status.value, "FAIL")
        self.assertAlmostEqual(
            angle.evidence.result.to("deg").magnitude.midpoint, 45.0, places=6)

        right = report([screw("s1", [0, 0, 7.5], [1, 0, 0], "bore"),
                        screw("s2", [0, 0, 7.5], [0, 1, 0], "s1")])
        self.assertEqual(right.overall_status.value, "PASS")


class AnAngleIsNotAlwaysBetweenTwoThings(unittest.TestCase):
    """The false alarm this would have produced on most briefs.

    Carrying a stated angle into the record was right for "two set screws 90
    degrees apart" and wrong for almost every other way a brief mentions an
    angle. A verification sweep before a run caught it demanding two holes 30
    degrees apart on a plate whose only angle was a chamfer, 90 apart for a
    vee groove, 82 for a countersink and 5 for a taper -- four correct parts
    that would each have been reported unsatisfiable.

    A chamfer angle is a property of one face; a taper, of one solid. Neither
    is an angle BETWEEN two features, which is the only kind
    `angle_between` can measure.
    """

    @staticmethod
    def _carried(brief):
        from forge_roles.library import _normalise_requirements

        answer, _, _ = _normalise_requirements(
            {"requirements": [], "assumptions": [], "unknowns": []}, brief)
        added = [
            r for r in answer["requirements"]
            if str(r.get("measurement", "")).startswith("angle_between")
        ]
        return added[0]["threshold"]["magnitude"] if added else None

    def test_a_chamfer_is_a_face_not_a_pair(self) -> None:
        self.assertIsNone(self._carried(
            "A bracket 60 mm long, 40 mm wide, 6 mm thick, with a 30 degree "
            "chamfer on the front edge."))

    def test_a_vee_groove_is_an_included_angle(self) -> None:
        self.assertIsNone(self._carried(
            "A steel V-block 50 mm long with a 90 degree vee groove."))

    def test_a_taper_is_one_solid(self) -> None:
        self.assertIsNone(self._carried(
            "A 40 mm long steel pin, 8 mm at the base, tapering at 5 "
            "degrees."))

    def test_a_countersink_is_a_hole_shape(self) -> None:
        self.assertIsNone(self._carried(
            "A 50 mm plate 5 mm thick with four 5 mm holes countersunk at 82 "
            "degrees."))

    def test_a_separation_between_two_is_carried(self) -> None:
        self.assertEqual(self._carried(
            "A shaft collar 25 mm across, 15 mm long. Two 4 mm set screw "
            "holes 90 degrees apart."), 90.0)

    def test_other_ways_of_saying_apart(self) -> None:
        for brief in (
            "A hub 30 mm across with two 3 mm radial holes at 60 degrees to "
            "each other.",
            "A collar 25 mm across with two set screws spaced 60 degrees.",
            "A collar 25 mm across. Both set screws are 60 degrees apart.",
            "A collar 25 mm across with a pair of cross holes 60 degrees "
            "apart.",
        ):
            self.assertEqual(self._carried(brief), 60.0, brief)

    def test_three_of_something_is_not_a_pair(self) -> None:
        """`angle_between` measures a pair. Three bolts 120 degrees apart is
        a real statement Forge cannot check, and saying so beats demanding a
        pair on a correct part."""
        self.assertIsNone(self._carried(
            "Three 5 mm bolts 120 degrees apart on a 40 mm disc 6 mm thick."))

    def test_a_brief_can_state_both_kinds(self) -> None:
        """Only one of these two angles is a separation, and asking whether
        the brief states exactly one angle would have thrown it away."""
        self.assertEqual(self._carried(
            "A collar 25 mm across with two set screws 90 degrees apart and "
            "a 30 degree chamfer."), 90.0)

    def test_two_separations_are_a_choice_forge_does_not_make(self) -> None:
        self.assertIsNone(self._carried(
            "A plate 50 mm across with two holes 90 degrees apart and two "
            "slots 45 degrees apart."))

    def test_the_separation_word_must_touch_the_angle(self) -> None:
        """`a|b|c$` anchors only the last branch. Unparenthesised, a bare
        "apart" earlier in the brief matched for every angle after it."""
        from forge_roles.library import _an_angle_between_two_of_something

        self.assertEqual(
            _an_angle_between_two_of_something(
                "A collar with two set screws 90 degrees apart and a 30 "
                "degree chamfer."),
            [90.0])

    def test_the_two_real_briefs_still_behave(self) -> None:
        self.assertEqual(self._carried(
            "A machined aluminium shaft collar. The outer diameter is 25 mm "
            "and it is 15 mm long. A 12 mm bore runs all the way through on "
            "the axis. Two 4 mm set screw holes pass through the wall from "
            "the outside into the bore, 90 degrees apart, both halfway along "
            "the length."), 90.0)
        self.assertIsNone(self._carried(
            "A 3D-printed PLA spacer block. The base is a 30 mm square plate "
            "4 mm thick. Two 3 mm mounting holes pass through the plate, "
            "20 mm apart."))


class AcrossTheFlatsIsNotAcross(unittest.TestCase):
    """A hex 17 across the flats is 19.6 across the corners.

    "17 mm across the flats" is the standard way to state a hex size, and it
    is the one phrase where `across` says the part is specifically NOT the
    same width both ways. Caught by the same sweep, which had Forge claiming
    a hex nut was 17 mm in both X and Y.
    """

    @staticmethod
    def _extents(brief):
        from forge_roles.library import _a_number_that_is_two_extents

        return _a_number_that_is_two_extents(brief)

    def test_a_hex_nut_is_not_round(self) -> None:
        self.assertEqual(
            self._extents("A hex nut 17 mm across the flats, 8 mm thick."),
            [])

    def test_without_the_article_either(self) -> None:
        self.assertEqual(
            self._extents("A hex bolt head 13 mm across flats."), [])

    def test_across_the_corners_too(self) -> None:
        self.assertEqual(
            self._extents("A hex bar 20 mm across the corners."), [])

    def test_a_plain_across_still_means_round(self) -> None:
        self.assertEqual(
            self._extents("A collar 25 mm across and 15 mm long."),
            [(25.0, "mm")])
        self.assertEqual(
            self._extents("A disc 40 mm across, 6 mm thick."),
            [(40.0, "mm")])


class TheSizeBoundKnowsThePrimitives(unittest.TestCase):
    """The table that says how big each primitive is must match the catalogue.

    It listed a sphere's size under `radius`, which the catalogue calls
    `diameter`, so a part made of spheres contributed nothing to the bound
    and every position looked as if it sat outside it.
    """

    def test_every_named_field_exists_on_its_kind(self) -> None:
        from forge_ir.features import FEATURE_SPECS
        from forge_roles.library import _HOW_BIG_A_PRIMITIVE_IS

        for kind, fields in _HOW_BIG_A_PRIMITIVE_IS.items():
            self.assertIn(kind, FEATURE_SPECS)
            declared = {p.name for p in FEATURE_SPECS[kind].parameters}
            for field in fields:
                self.assertIn(field, declared, f"{kind}.{field}")

    def test_every_shape_making_primitive_is_listed(self) -> None:
        """A primitive added later must be added here, or it vouches for
        nothing and the guard it feeds silently loosens."""
        from forge_ir.features import FEATURE_SPECS
        from forge_roles.library import _HOW_BIG_A_PRIMITIVE_IS

        # A boolean produces a solid and declares no fixed inputs either --
        # it takes a variadic list of them. It combines solids rather than
        # making one, and its own size is whatever its operands are.
        primitives = {
            kind for kind, spec in FEATURE_SPECS.items()
            if spec.produces == "solid"
            and not spec.inputs
            and not getattr(spec, "variadic_input", None)
        }
        self.assertEqual(primitives, set(_HOW_BIG_A_PRIMITIVE_IS))

    def test_a_sphere_contributes_its_size(self) -> None:
        from forge_roles.library import _how_big_the_part_can_be

        component = {
            "id": "p",
            "parameters": [{"id": "ball",
                            "value": {"magnitude": 10.0, "unit": "mm"}}],
            "features": [{"id": "b", "kind": "sphere", "parameters": {
                "diameter": {"expression": "ball", "unit": "mm"}}}]}
        self.assertAlmostEqual(_how_big_the_part_can_be(component), 5.0)


class TwoEqualBoundingBoxesDoNotMakeAPartRound(unittest.TestCase):
    """A 25 mm square block has a 25 by 25 bounding box, same as a cylinder.

    Asked for a shaft collar 25 mm in outer diameter, a design built a 25 by
    25 by 15 BOX. `bounding_box_x` and `bounding_box_y` both measured 25 and
    both passed -- correctly, because a square and its circumscribed circle
    have the same bounding box. Every geometric gate passed too. It had a
    bore and two set screws 90 degrees apart, and it was not a collar.

    Nothing in the system had ever asked whether a round part was round.
    """

    @staticmethod
    def _measure(solid):
        from forge_pipeline.measure import _roundness_about_z

        class Part:
            pass

        part = Part()
        part.solid = solid
        return _roundness_about_z(part)

    @staticmethod
    def _cylinder(radius=12.5, height=15.0):
        from forge_geom.sdf import CylinderSDF

        return CylinderSDF(base=(0, 0, 0), axis=(0, 0, 1), radius=radius,
                           height=height)

    @staticmethod
    def _box(half=(12.5, 12.5, 7.5)):
        from forge_geom.sdf import BoxSDF

        return BoxSDF(centre=(0, 0, 7.5), half_extent=half)

    def _value(self, solid):
        measured = self._measure(solid)
        self.assertTrue(measured.ok, measured.blocked_reason)
        return measured.value.magnitude.midpoint

    def test_a_cylinder_is_round(self) -> None:
        self.assertGreater(self._value(self._cylinder()), 0.99)

    def test_a_square_block_is_not(self) -> None:
        self.assertAlmostEqual(self._value(self._box()), 0.7071, places=3)

    def test_a_flat_plate_is_not_round_either(self) -> None:
        self.assertAlmostEqual(
            self._value(self._box(half=(15.0, 15.0, 2.0))), 0.7071, places=3)

    def test_holes_do_not_disturb_it(self) -> None:
        """A width across a direction is set by the outermost surface, and
        holes take material from inside the silhouette."""
        from forge_geom.sdf import CylinderSDF, Difference

        drilled = Difference(base=self._cylinder(), tools=(
            CylinderSDF(base=(0, 0, -1), axis=(0, 0, 1), radius=6.0,
                        height=17.0),
            CylinderSDF(base=(-20, 0, 7.5), axis=(1, 0, 0), radius=2.0,
                        height=40.0),
            CylinderSDF(base=(0, -20, 7.5), axis=(0, 1, 0), radius=2.0,
                        height=40.0)))
        self.assertGreater(self._value(drilled), 0.95)

    def test_the_threshold_separates_every_case_that_matters(self) -> None:
        """A regular n-sided prism measures cos(pi/n): a hexagon 0.866, an
        octagon 0.924. The bar is above both and below every cylinder."""
        import math

        from forge_roles.library import _ROUND_ENOUGH

        self.assertGreater(_ROUND_ENOUGH, math.cos(math.pi / 8))
        self.assertLess(_ROUND_ENOUGH, 0.99)
        self.assertGreater(self._value(self._cylinder()), _ROUND_ENOUGH)
        self.assertLess(self._value(self._box()), _ROUND_ENOUGH)

    def test_it_is_in_the_vocabulary(self) -> None:
        from forge_ir.measurements import (
            SIMPLE_MEASUREMENTS, parse_measurement, vocabulary_help)

        self.assertIn("roundness_about_z", SIMPLE_MEASUREMENTS)
        self.assertEqual(parse_measurement("roundness_about_z").kind,
                         "roundness_about_z")
        self.assertIn("roundness_about_z", vocabulary_help())


class ARoundPartIsClaimedRound(unittest.TestCase):
    """Forge carries roundness for a part the brief gives as a diameter."""

    @staticmethod
    def _carried(brief):
        from forge_roles.library import _normalise_requirements

        answer, _, _ = _normalise_requirements(
            {"requirements": [], "assumptions": [], "unknowns": []}, brief)
        return [str(r.get("measurement", "")) for r in answer["requirements"]]

    def test_a_collar_given_as_a_diameter(self) -> None:
        self.assertIn("roundness", self._carried(
            "A shaft collar. The outer diameter is 25 mm and it is 15 mm "
            "long."))

    def test_a_disc(self) -> None:
        self.assertIn("roundness", self._carried(
            "A disc 40 mm in diameter and 6 mm thick."))

    def test_a_square_plate_is_not_claimed_round(self) -> None:
        self.assertNotIn("roundness", self._carried(
            "A 30 mm square plate 4 mm thick with a 12 mm post."))

    def test_a_rectangular_bracket_gets_nothing(self) -> None:
        self.assertNotIn("roundness", self._carried(
            "A bracket 60 mm long and 40 mm wide, 6 mm thick."))

    def test_a_hex_nut_is_not_round(self) -> None:
        self.assertNotIn("roundness", self._carried(
            "A hex nut 17 mm across the flats, 8 mm thick."))

    def test_nothing_is_doubled(self) -> None:
        from forge_roles.library import _a_round_part_has_to_be_round

        requirements = [
            {"id": "R", "measurement": "roundness_about_z",
             "comparison": "at_least",
             "threshold": {"magnitude": 0.9, "unit": ""}},
            {"id": "X", "measurement": "bounding_box_x", "comparison": "equals",
             "threshold": {"magnitude": 25.0, "unit": "mm"}}]
        self.assertEqual(
            _a_round_part_has_to_be_round(
                "A collar 25 mm in diameter.", requirements), [])
        self.assertEqual(len(requirements), 2)

    def test_the_designer_is_told_cylinder_not_box(self) -> None:
        """The instruction that caused the block. "The same size across X and
        Y" with a square plate as the example is an order to build a box."""
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import (
            Intent, RequirementSet, _normalise_requirements)

        def told(brief):
            answer, _, _ = _normalise_requirements(
                {"requirements": [], "assumptions": [], "unknowns": []}, brief)
            messages = ForgeIRDesigner().build_messages(
                intent=Intent(summary=brief, part_kind="p", stated=(),
                              implied=(), unstated=()),
                requirements=RequirementSet(
                    requirements=tuple(answer["requirements"]),
                    assumptions=(), unknowns=()))
            return "\n".join(m.content for m in messages)

        collar = told("A shaft collar. The outer diameter is 25 mm and it is "
                      "15 mm long.")
        self.assertIn("This part is ROUND", collar)
        self.assertIn("`cylinder`", collar)
        self.assertIn("NOT a `box`", collar)

        plate = told("A 30 mm square plate 4 mm thick.")
        self.assertIn("This part is SQUARE", plate)
        self.assertNotIn("This part is ROUND", plate)

    def test_the_square_collar_fails_and_a_real_one_passes(self) -> None:
        import json

        from forge_ir import SCHEMA_VERSION, Document
        from forge_kernel import Compiler
        from forge_pipeline import verify_component
        from forge_pipeline.measure import resolve_measurement
        from forge_geom.measure import measure_mass_properties

        def roundness(body):
            document = Document.from_json(json.dumps({
                "schema_version": SCHEMA_VERSION, "revision": 1,
                "document_id": "00000000-0000-4000-8000-000000000b01",
                "project_id": "00000000-0000-4000-8000-000000000b0f",
                "name": "Collar", "risk_class": "low",
                "units": {"length": "mm", "mass": "kg", "angle": "deg",
                          "force": "N"},
                "requirements": [], "assumptions": [],
                "components": [{
                    "id": "collar", "name": "Collar",
                    "material": "aluminium_6061_t6", "parameters": [],
                    "features": [body, {
                        "id": "bore", "kind": "hole", "inputs": [body["id"]],
                        "parameters": {
                            "diameter": {"magnitude": 12.0, "unit": "mm"},
                            "position": {"vector": [0, 0, 7.5], "unit": "mm"},
                            "axis": [0.0, 0.0, 1.0]}}]}]}))
            built = Compiler().compile_component(document.components[0])
            return resolve_measurement(
                "roundness_about_z", component=document.components[0],
                part=built,
                properties=measure_mass_properties(built.solid, max_depth=4)
            ).value.magnitude.midpoint

        square = roundness({"id": "base", "kind": "box", "parameters": {
            "size": {"vector": [25, 25, 15], "unit": "mm"}, "centered": True}})
        round_ = roundness({"id": "body", "kind": "cylinder", "parameters": {
            "diameter": {"magnitude": 25.0, "unit": "mm"},
            "height": {"magnitude": 15.0, "unit": "mm"}}})
        self.assertAlmostEqual(square, 0.7071, places=3)
        self.assertGreater(round_, 0.95)


class ASizeAndADiameterAreOneDimension(unittest.TestCase):
    """`outer_diameter` and `collar_size` share no word and are the same.

    Requiring a shared word cost a run: the design named everything
    `collar_*`, the record named it `outer_diameter` and `length`, and both
    claims lost their binding on a part that was perfectly measurable.
    """

    @staticmethod
    def _rebound(declared, binding, figure):
        from forge_roles.library import (
            RequirementSet, _bind_each_claim_to_the_name_the_design_uses)

        payload = {"components": [{
            "id": "p", "features": [],
            "parameters": [
                {"id": name, "value": {"magnitude": value, "unit": "mm"}}
                for name, value in declared]}]}
        record = RequirementSet(requirements=({
            "id": "R", "statement": "R", "measurement": binding,
            "comparison": "equals",
            "threshold": {"magnitude": figure, "unit": "mm"}},),
            assumptions=(), unknowns=())
        out, _ = _bind_each_claim_to_the_name_the_design_uses(payload, record)
        return dict(out.requirements[0])["measurement"]

    def test_a_diameter_finds_a_size(self) -> None:
        self.assertEqual(
            self._rebound([("collar_size", 25.0)], "parameter:outer_diameter",
                          25.0),
            "parameter:collar_size")

    def test_a_length_finds_a_thickness(self) -> None:
        self.assertEqual(
            self._rebound([("collar_thickness", 15.0)], "parameter:length",
                          15.0),
            "parameter:collar_thickness")

    def test_across_and_along_are_different_kinds(self) -> None:
        self.assertEqual(
            self._rebound([("plate_thickness", 25.0)],
                          "parameter:outer_diameter", 25.0),
            "parameter:outer_diameter")

    def test_a_coincidence_of_numbers_is_still_refused(self) -> None:
        self.assertEqual(
            self._rebound([("hole_spacing", 30.0)], "parameter:base_width",
                          30.0),
            "parameter:base_width")

    def test_two_of_the_same_kind_is_a_choice(self) -> None:
        self.assertEqual(
            self._rebound([("collar_size", 25.0), ("boss_diameter", 25.0)],
                          "parameter:outer_diameter", 25.0),
            "parameter:outer_diameter")

    def test_a_shared_word_still_works(self) -> None:
        self.assertEqual(
            self._rebound([("base_size", 30.0)], "parameter:base_width", 30.0),
            "parameter:base_size")

    def test_the_table_holds_only_unambiguous_words(self) -> None:
        """A word that could mean either kind is left out, so the
        reconciliation falls back to needing a shared word."""
        from forge_roles.library import _WHAT_KIND_OF_DIMENSION

        self.assertEqual(set(_WHAT_KIND_OF_DIMENSION.values()),
                         {"across", "along"})
        for ambiguous in ("span", "pitch", "spacing", "distance", "gap"):
            self.assertNotIn(ambiguous, _WHAT_KIND_OF_DIMENSION)


class TheLBracketRunEndToEnd(unittest.TestCase):
    """Run 20260929T184133, replayed through the whole orchestrator.

    The designer's answer wired one upright hole into the base's chain. The
    part built with a hole missing, and the re-aim repair was applied three
    rounds running because it never recognised the axis it had just written.
    """

    def _case(self):
        import json as _json
        import pathlib

        here = pathlib.Path(__file__).parent / "fixtures" / "real_runs"
        return _json.loads(
            (here / "l_bracket_holes_cut_before_the_union.json").read_text())

    def test_it_passes_with_no_repair_round(self) -> None:
        case = self._case()
        run, provider = _run(
            [case["intent"], case["requirements"], case["answer"]],
            brief=case["brief"])
        self.assertEqual(run.report.overall_status, Status.PASS)
        self.assertEqual(run.repairs, [])
        self.assertEqual(len(provider.requests), 3)

    def test_a_decoded_axis_is_read_as_the_default(self) -> None:
        import json as _json

        from forge_ir import Document
        from forge_orchestrator.orchestrator import _is_the_default_axis

        payload = {"document_id": "d", "components": [{"id": "p", "parameters": [],
                   "features": [
                       {"id": "b", "kind": "box", "parameters": {
                           "size": {"vector": [10, 10, 2], "unit": "mm"}}},
                       {"id": "h", "kind": "hole", "inputs": ["b"], "parameters": {
                           "diameter": {"magnitude": 2, "unit": "mm"},
                           "position": {"vector": [5, 5, 1], "unit": "mm"},
                           "axis": [0.0, 0.0, 1.0]}}]}]}
        from forge_ir.spec import EXAMPLE_DOCUMENT

        whole = {**{k: v for k, v in EXAMPLE_DOCUMENT.items()
                    if k != "components"}, **payload}
        document = Document.from_json(_json.dumps(whole))
        hole = [f for f in document.components[0].features
                if f.identifier == "h"][0]
        self.assertTrue(_is_the_default_axis(hole.parameters.get("axis")))
        self.assertTrue(_is_the_default_axis([0, 0, 1]))
        self.assertFalse(_is_the_default_axis([0, 1, 0]))


class TheLoadedCantileverEndToEnd(unittest.TestCase):
    """Run 20261002T150340, prompt 10, replayed through the orchestrator: the
    load drawn as a 150 N tall cylinder, the bolt holes at one point, their
    size a name nothing declared. Built, gated, and held only for the user
    to approve the load and the grade -- with no repair round spent."""

    def test_it_is_held_only_for_approval(self) -> None:
        import json as _json
        import pathlib

        here = pathlib.Path(__file__).parent / "fixtures" / "real_runs"
        case = _json.loads(
            (here / "cantilever_with_its_load_drawn_as_a_solid.json").read_text())
        run, provider = _run(
            [case["intent"], case["requirements"], case["answer"]],
            brief=case["brief"])
        self.assertEqual(run.repairs, [])
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(run.report.overall_status, Status.BLOCKED)
        failing = [g.gate.identifier for g in run.report.gate_results
                   if g.status not in (Status.PASS, Status.NOT_APPLICABLE)]
        self.assertEqual(failing, [])


class APatchThatDoesNotCompileIsNotTheEndOfTheRun(unittest.TestCase):
    """Run 20261005T171148: the analyst's patch validated, and the compiler
    refused it inside the gate loop -- which took the run down as an internal
    error, "a defect in Forge", on a design one round from a better answer.
    A patch that does not build is a failed repair like any other: kept out,
    and its reason handed to the next round."""

    BREAKS_THE_BLEND = {
        "diagnosis": "the blend is too small",
        "strategy": "make it 3",
        "confidence": "medium",
        "abandon": False,
        "patches": [{"op": "replace",
                     "pointer": "/components/0/features/3/parameters/"
                                "blend_radius",
                     "value": {"expression": "3 * N"},
                     "reason": "bigger"}],
    }

    def test_it_is_refused_and_another_round_is_worth_it(self) -> None:
        from forge_orchestrator.orchestrator import _worth_another_round

        run, _ = _run([INTERPRETER, REQUIREMENTS, DESIGNER_VALID])
        payload = copy.deepcopy(run.document_payload)
        orchestrator = Orchestrator(
            ScriptedProvider([self.BREAKS_THE_BLEND]), config=FAST)
        before = len(run.repairs)
        outcome = orchestrator._apply_repair(
            run, payload, trigger="gate", failure={"id": "X"},
            pointers=("/components/0",), attempt=1, seen_patches=set(),
            cancellation=None)
        self.assertIsNone(outcome)
        last = run.repairs[before].outcome
        self.assertTrue(last.startswith("patched document did not compile"),
                        last)
        self.assertTrue(_worth_another_round(run))


class TheAnswersReachTheRequirements(unittest.TestCase):
    """Asked what load the part carries, the user answers "it carries no
    load". The answer went to the designer only: the record, written again
    from the brief alone, kept the margin it had asked about, and the part
    was held BLOCKED for a load the user had said does not exist."""

    def test_the_requirements_engineer_is_shown_them(self) -> None:
        run, provider = _run([INTERPRETER, REQUIREMENTS, DESIGNER_VALID],
                             answers={"UNK_LOAD": "300 N at the bore"})
        asked = [r for r in provider.requests
                 if r.purpose == "requirements_engineer"]
        text = "\n".join(m.content for m in asked[0].messages)
        self.assertIn("<user_answers>", text)
        self.assertIn("300 N at the bore", text)

    def test_no_load_said_in_an_answer_drops_the_margin(self) -> None:
        from forge_roles import RequirementsEngineer

        answer = {"risk_class": "low", "requirements": [
            {"id": "REQ_L", "statement": "60 mm long",
             "measurement": "parameter:length", "comparison": "equals",
             "threshold": {"magnitude": 60, "unit": "mm"}},
            {"id": "REQ_SF", "statement": "a margin of 2",
             "measurement": "safety_factor:bending", "comparison": "at_least",
             "threshold": {"magnitude": 2, "unit": ""}}],
            "assumptions": [], "unknowns": []}
        brief = "A mounting plate 60 mm long. It must be strong."
        asked = RequirementsEngineer().parse(answer, brief=brief)
        self.assertIn("UNK_LOAD", [u.identifier for u in asked.unknowns])
        settled = RequirementsEngineer().parse(
            answer, brief=brief, answers={"UNK_LOAD": "it carries no load"})
        self.assertNotIn("REQ_SF", [r["id"] for r in settled.requirements])
        self.assertEqual(settled.unknowns, ())


class TheBriefsOwnConflictStopsTheRepairs(unittest.TestCase):
    """The curved plate's brief puts an 8.2 mm hole inside a 28 x 5 slot.
    No design can give it both; the analyst was asked anyway, moved a hole
    off the plate, and the run ended on "traded one failure for another"."""

    def _report(self, *failing):
        from types import SimpleNamespace as N

        from forge_evidence import Status

        return N(gate_results=[
            N(status=Status.FAIL, gate=N(identifier=g, critical=True),
              evidence=N(detail={"measurement": m}))
            for g, m in failing])

    def _run(self, *summaries):
        from types import SimpleNamespace as N

        return N(events=[N(summary=s) for s in summaries])

    def test_only_when_said_and_only_its_gates_fail(self) -> None:
        from forge_orchestrator.orchestrator import _the_brief_s_own_conflict

        said = "THE BRIEF'S OWN FIGURES OVERLAP: `a` and `b` run into each other"
        collision = self._report(("GEOM_HOLES_ARE_HOLES", ""),
                                 ("REQ_OPENINGS_28X5", "openings_of_size:28x5"))
        self.assertEqual(_the_brief_s_own_conflict(
            self._run("designing", said), collision), [said])
        self.assertEqual(_the_brief_s_own_conflict(
            self._run("designing"), collision), [])
        more = self._report(("GEOM_HOLES_ARE_HOLES", ""),
                            ("REQ_PART_LONG", "flat_extent_side:120"))
        self.assertEqual(_the_brief_s_own_conflict(
            self._run(said), more), [])
