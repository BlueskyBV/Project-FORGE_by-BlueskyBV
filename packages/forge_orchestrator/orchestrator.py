"""The design loop: brief in, verified part out, or an honest reason why not.

The loop, with the reasoning for its shape:

1. **Interpret** the brief, separating what was said from what was not.
2. **Gather requirements**, producing checkable requirements, declared
   assumptions, and unknowns that stay unknown.
3. **Stop if critical unknowns remain** and no answers were supplied. This is a
   pause, not a failure. The alternative is inventing a load, and a design
   verified against an invented load passes gates that mean nothing.
4. **Design** a ForgeIR document.
5. **Compile** it. On failure, diagnose and patch, bounded.
6. **Verify** it. On a failed gate, diagnose and patch, bounded again -- but
   never by weakening the requirement.
7. **Report** everything, including what could not be established.

Two properties are worth stating because they are easy to lose.

**Repair is surgical.** The analyst gets the diagnostic and the slice of document
it points at, and returns pointer-targeted patches. Nothing that was already
right is regenerated, and the patch list is an auditable record of what changed.

**Oscillation ends the loop.** A repair that has been tried before is not tried
again. Models presented with the same failure tend to propose the same fix, and
an unbounded loop spends real money rediscovering that. Detecting the repeat and
stopping produces a better outcome than a fourth attempt: a clear statement of
what could not be fixed.
"""

from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from forge_evidence import Status
from forge_ir import Document, SchemaError, SchemaErrorGroup
from forge_kernel import CompileError, Compiler
from forge_models import (
    BudgetExceededError,
    CancellationToken,
    CancelledError,
    ModelError,
    Provider,
    Usage,
)
from forge_pipeline import (
    LoadCase,
    VerificationReport,
    the_bore_found_material,
    verify_component,
)
from forge_roles import (
    BriefInterpreter,
    ClarificationPrioritiser,
    FailureAnalyst,
    ForgeIRDesigner,
    Patch,
    PatchError,
    RepairExhaustedError,
    RequirementsEngineer,
    RoleError,
    PointerError,
    apply_patches,
    extract_slice,
    parse_pointer,
    problems_from_schema_error,
    resolve,
)
from forge_units import Q, Quantity

from .run import DesignRun, RepairAttempt, State


#: Whether a hole, as compiled, cuts through any material at all. Defined in
#: `forge_pipeline` beside the gate that reports the failure, and imported
#: here rather than copied, because two readers of the same field drift and
#: only one of them ever explains itself to anybody.
_the_bore_found_material = the_bore_found_material


def _is_the_default_axis(axis: Any) -> bool:
    """Whether this axis already points along +Z, however it is written."""
    if axis is None:
        return True
    values = getattr(axis, "components", axis)
    try:
        x, y, z = (_a_plain_number(v) for v in values)
    except (TypeError, ValueError):
        return False
    return abs(x) < 1e-9 and abs(y) < 1e-9 and z > 0.0


def _a_plain_number(value: Any) -> float:
    """A float from a number, a quantity, or a decoded `QuantityValue`.

    A decoded axis component is a `QuantityValue` wrapping a `Quantity`
    whose magnitude is an `Interval`. Read as `float(value.magnitude)` it
    raised, the default axis was never recognised, and the same re-aim was
    applied to the same hole three rounds running."""
    value = getattr(value, "quantity", value)
    value = getattr(value, "magnitude", value)
    if hasattr(value, "lo") and hasattr(value, "hi"):
        return (float(value.lo) + float(value.hi)) / 2
    return float(value)


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    """How hard to try, and what to do when information is missing."""

    #: Attempts to make the document compile.
    max_compile_repairs: int = 3
    #: Attempts to make a failing gate pass, by changing the design.
    max_gate_repairs: int = 2
    #: When the repairs leave the design failing, how many times it is
    #: designed again from the requirements, told what failed and what the
    #: repairs found -- and kept only if the new design measures better.
    #: Off by default for library callers; the command line turns it on.
    redesigns: int = 0
    #: Repair rounds for a design made again.
    max_gate_repairs_after_a_redesign: int = 2
    #: Ask clarifying questions rather than proceeding on critical unknowns.
    #: Turning this off does not invent values: it records each unknown as a
    #: high-risk assumption instead, which blocks release. The design still gets
    #: built, and the report says exactly what was assumed.
    stop_on_critical_unknowns: bool = True
    #: Cap on how many output tokens any role may reserve. The defaults suit a
    #: model with a 200k context; a local runtime with 16k cannot honour a
    #: 16,384-token reservation alongside an 8,000-token prompt, and refusing
    #: the call is correct but unhelpful when the real document is 3,000 tokens
    #: long. Lowering the reservation is what makes the loop fit.
    output_token_cap: int | None = None
    #: Octree depth for the verification measurement.
    measurement_depth: int = 8
    mesh_resolution: int = 96
    verbose: bool = False
    #: When every check passes and the model can see, one last look at the
    #: part against the brief before it is released -- for what no check
    #: measures: material where space should be, a feature on the wrong side.
    #: A change it proposes is kept only if nothing that passed then fails.
    last_look: bool = True


class Orchestrator:
    """Runs the design workflow against a provider."""

    __slots__ = ("_provider", "_config", "_compiler", "_roles", "_drawn")

    def __init__(
        self,
        provider: Provider,
        *,
        config: OrchestratorConfig | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or OrchestratorConfig()
        self._compiler = Compiler()
        #: The picture of each part drawn so far, by its geometry's hash.
        self._drawn: dict[str, bytes | None] = {}
        self._roles = {
            "interpreter": BriefInterpreter(),
            "requirements": RequirementsEngineer(),
            "clarifier": ClarificationPrioritiser(),
            "designer": ForgeIRDesigner(),
            "analyst": FailureAnalyst(),
        }
        cap = self._config.output_token_cap
        if cap is not None:
            # Set on the instances this orchestrator owns, never on the classes:
            # one run configured for a small local model must not change what
            # every other run in the process reserves.
            for role in self._roles.values():
                role.max_output_tokens = min(role.max_output_tokens, cap)
                role.output_token_ceiling = min(role.output_token_ceiling, cap)

    # ------------------------------------------------------------------
    def design(
        self,
        brief: str,
        *,
        answers: Mapping[str, str] | None = None,
        cancellation: CancellationToken | None = None,
        watch: Any = None,
    ) -> DesignRun:
        """Design a part from `brief`. `watch`, if given, is called as
        `watch(kind, item)` while the run goes: ("event", RunEvent) for each
        step and ("picture", (caption, png)) each time the part is drawn."""
        run = DesignRun(brief, answers=answers)
        run.listener = watch
        run.provider_info = self._provider.info.as_dict()
        before = self._provider.budget.usage
        try:
            return self._design(run, cancellation=cancellation)
        except CancelledError as error:
            # Stopped by the person running it: said as that, not as a fault,
            # and whatever was built and measured is kept for the artefacts.
            run.failure = error.as_dict()
            run.record(State.CANCELLED, "cancelled before the run finished")
            return run
        except BudgetExceededError as error:
            run.failure = error.as_dict()
            # Why the role that was stopped was answering again: the problems
            # its earlier answers were refused for, said with the failure.
            problems = list(error.detail.get("last_problems", []) or [])
            if problems:
                run.failure["problems"] = (
                    [f"{error.detail.get('role', 'a role')} had "
                     f"{error.detail.get('answers_refused', 0)} answer(s) "
                     "refused before the budget ran out; the last was "
                     "refused for:"] + problems)
            # The limit that was reached, by name: a run stopped at the token
            # ceiling was told to raise --max-cost, which it was nowhere near.
            if "projected" in error.detail or "spent" in error.detail:
                which = "--max-tokens (600 000 by default)"
            elif "calls" in error.detail:
                which = "--max-calls (60 by default)"
            else:
                which = "--max-cost (-MaxCost in run-design-claude.ps1)"
            run.failure.setdefault("detail", {}).setdefault(
                "hint", f"the run reached {which}; raise it for a part this "
                "size")
            run.record(State.FAILED, "budget exhausted", **{
                key: value for key, value in error.detail.items()
                if key in ("spent_usd", "limit_usd", "calls", "limit",
                           "spent", "projected", "role", "answers_refused")})
            return run
        except (ModelError, RoleError) as error:  # noqa: B904 - recorded below
            run.failure = {
                "message": error.message,
                "code": error.code,
                "problems": list(getattr(error, "problems", ()))
                or list(error.detail.get("last_problems", [])),
                "detail": dict(error.detail),
            }
            run.record(State.FAILED, error.message, code=error.code)
            return run
        except Exception as error:  # noqa: BLE001 - deliberately everything
            # A bug in Forge must not cost the run its record.
            #
            # Observed live: a model wrote `{"magnitude": "fillet_thickness"}`,
            # `float()` raised a plain ValueError three layers down, and because
            # it was not a ModelError or a RoleError it travelled out of the CLI
            # as a one-line traceback. Fifty minutes of generation, and not one
            # file on disk to show what had been produced or how far it got.
            #
            # Recorded as an internal error, named as ours rather than the
            # design's, so the artefacts are still written and the event log
            # still says where it stopped.
            run.failure = {
                "message": f"internal error: {error}",
                "code": "OR1004_INTERNAL",
                "problems": [f"{type(error).__name__}: {error}"],
                "detail": {
                    "exception": type(error).__name__,
                    "traceback": traceback.format_exc()[-4000:],
                    "hint": "this is a defect in Forge, not in the design. The "
                    "run's artefacts were still written; the traceback in "
                    "run.json says where it stopped.",
                },
            }
            run.record(
                State.FAILED,
                f"internal error: {type(error).__name__}: {error}",
                code="OR1004_INTERNAL",
            )
            return run
        finally:
            # Refreshed rather than left as the snapshot taken before the first
            # call. Some facts about a provider -- notably whether the schema
            # reached it intact -- are only known once it has been used, and a
            # run that reports `exact` for a reduced schema is lying about the
            # one thing the reduction exists to disclose.
            run.provider_info = self._provider.info.as_dict()
            # The provider's budget counts every call, including the ones whose
            # answers were unusable. Those are spending too, and a run that adds
            # up only its successful steps under-reports what it cost -- by a
            # factor of four when a retry loop failed four times.
            run.usage = _spent_since(before, self._provider.budget.usage)

    # ------------------------------------------------------------------
    def _design(
        self, run: DesignRun, *, cancellation: CancellationToken | None
    ) -> DesignRun:
        # -- 1. interpret ------------------------------------------------
        run.record(State.INTERPRETING, "reading the brief")
        interpreted = self._roles["interpreter"].run(
            self._provider, cancellation=cancellation, brief=run.brief
        )
        run.intent = interpreted.value
        run.record(
            State.INTERPRETING,
            f"{len(interpreted.value.stated)} stated facts, "
            f"{len(interpreted.value.unstated)} things left unsaid",
            usage=interpreted.usage,
            part_kind=interpreted.value.part_kind,
            risk_signals=list(interpreted.value.risk_signals),
        )
        for note in getattr(interpreted.value, "notes", ()):
            run.record(State.INTERPRETING, note)
        _note_role_repairs(run, interpreted)
        if not getattr(interpreted.value, "is_a_part", True):
            # "Write me a poem about bridges." The interpreter said it was no
            # part; requirements were written anyway, the designer drew a
            # 1 mm placeholder cube, and every check passed it. Nothing is
            # designed for a brief that asks for no part.
            run.failure = {
                "message": "the brief does not ask for a part, so there is "
                           "nothing to design: "
                           + str(interpreted.value.summary)[:400],
                "code": "OR1008_NOT_A_PART",
                "problems": list(getattr(interpreted.value, "out_of_scope",
                                         ()))[:3],
            }
            run.record(State.FAILED,
                       "not a part: the brief asks for something Forge does "
                       "not design -- " + str(interpreted.value.summary)[:300])
            return run

        # -- 2. requirements ---------------------------------------------
        run.record(State.GATHERING_REQUIREMENTS, "deriving requirements")
        gathered = self._roles["requirements"].run(
            self._provider,
            cancellation=cancellation,
            brief=run.brief,
            intent=interpreted.value,
            # The answers to its questions, when this is the run that has
            # them: "it carries no load" settles the margin it asked about.
            answers=dict(run.answers),
        )
        requirements = gathered.value
        run.requirements = requirements
        run.record(
            State.GATHERING_REQUIREMENTS,
            f"{len(requirements.requirements)} requirements, "
            f"{len(requirements.assumptions)} assumptions, "
            f"{len(requirements.critical_unknowns)} critical unknowns",
            usage=gathered.usage,
            risk_class=requirements.risk_class,
        )
        for note in getattr(requirements, "notes", ()):
            # An answer that was corrected on the way in is not the answer the
            # model gave, and the difference belongs in the record rather than
            # in nobody's head.
            run.record(State.GATHERING_REQUIREMENTS, note)
        _note_role_repairs(run, gathered)

        # -- 3. clarify or proceed on declared assumptions ----------------
        # An answer has to say something. Membership alone used to be enough,
        # so `--answer UNK_LOAD=` erased a critical unknown: no question was
        # asked, no assumption was recorded, nothing blocked release, and the
        # empty string was handed to the designer under a heading that calls
        # it a fact confirmed by the user. That is the one path in Forge that
        # turns "nobody knows" into "somebody said so", which is precisely
        # what the unknown exists to prevent. Blank means unanswered.
        run.answers = {
            identifier: text
            for identifier, text in run.answers.items()
            if str(text).strip()
        }
        outstanding = [
            unknown
            for unknown in requirements.critical_unknowns
            if unknown.identifier not in run.answers
        ]
        if outstanding:
            if self._config.stop_on_critical_unknowns:
                prioritised = self._roles["clarifier"].run(
                    self._provider,
                    cancellation=cancellation,
                    requirements=requirements,
                )
                run.questions = prioritised.value
                run.record(
                    State.AWAITING_ANSWERS,
                    f"{len(prioritised.value)} questions need answering before "
                    "this can be designed honestly",
                    usage=prioritised.usage,
                    unknowns=[u.identifier for u in outstanding],
                )
                _note_role_repairs(run, prioritised)
                return run

            # Proceeding without answers does not mean inventing values. Each
            # unresolved unknown becomes a high-risk, unapproved assumption,
            # which blocks release downstream and is named in the report.
            requirements = _absorb_unknowns(requirements, outstanding)
            run.requirements = requirements
            run.record(
                State.GATHERING_REQUIREMENTS,
                f"proceeding with {len(outstanding)} unknowns recorded as "
                "unapproved high-risk assumptions; release will be blocked",
                absorbed=[u.identifier for u in outstanding],
            )

        # -- 4. design ----------------------------------------------------
        run.record(State.DESIGNING, "generating the parametric document")
        drafted = self._roles["designer"].run(
            self._provider,
            cancellation=cancellation,
            intent=interpreted.value,
            requirements=requirements,
            answers=run.answers,
            # The designer builds from the accepted record, not from the
            # brief, and that is deliberate. It is carried anyway so the
            # parse-time checks can compare what was written against what the
            # user actually said -- a 90 mm spacing on a part 25 mm across is
            # only recognisable as the brief's "90 degrees apart" if the
            # brief is in hand.
            brief=run.brief,
        )
        draft = drafted.value
        run.draft = draft
        run.document_payload = draft.payload
        run.record(
            State.DESIGNING,
            f"document generated: {len(draft.document.components)} component(s)",
            usage=drafted.usage,
            attempts=drafted.attempts,
            rationale=draft.rationale,
            # The designer's answer as written, before Forge repaired it.
            answer=getattr(draft, "answer", None),
        )
        for note in getattr(draft, "notes", ()):
            # Same contract as the requirements notes above: the document of
            # record differs from what the designer returned, and the run has
            # to say how or the provenance is a lie.
            run.record(State.DESIGNING, note)
        _note_role_repairs(run, drafted)

        # -- 5. compile, repairing as needed ------------------------------
        payload: Mapping[str, Any] = draft.payload
        document = draft.document
        component_id = document.components[0].identifier

        compiled = self._compile_with_repair(
            run, payload, document, cancellation=cancellation
        )
        redesigns_left = max(0, int(self._config.redesigns))
        if compiled is None:
            # Repairs could not make the first design compile. Designed again
            # from the requirements, told why, before giving up on the run.
            again = None
            if redesigns_left:
                redesigns_left -= 1
                again = self._design_it_again(
                    run, None, intent=interpreted.value,
                    requirements=requirements, cancellation=cancellation)
            if again is None:
                run.record(State.FAILED,
                           "the design could not be made to compile")
                return run
            payload, document, report = again
            draft = run.draft
        else:
            payload, document = compiled
            run.document_payload = payload
            component_id = document.components[0].identifier
            run.record(State.COMPILING, "compiles cleanly")

            # -- 6. verify, repairing as needed ---------------------------
            run.record(State.VERIFYING, "measuring and gating")
            report = self._verify(document, component_id)
            run.report = report
            self._look(run, report, "first build")

        # Forge's own repairs are answerable to the part too: one the
        # finished part measures worse with is taken back.
        if report.overall_status is Status.FAIL and payload is draft.payload:
            better = self._without_a_repair_that_hurt(
                run, draft, report, intent=interpreted.value,
                requirements=requirements, answers=run.answers,
                brief=run.brief)
            if better is not None:
                draft, report = better
                payload, document = draft.payload, draft.document
                component_id = document.components[0].identifier
                run.draft = draft
                run.document_payload = payload
                run.report = report

        seen_gate_patches: set[str] = set()
        payload, document, report = self._repair_until_it_passes(
            run, payload, document, report, cancellation=cancellation,
            seen_gate_patches=seen_gate_patches,
            budget=self._config.max_gate_repairs)
        for _ in range(redesigns_left):
            if report.overall_status is not Status.FAIL or (
                    run.failure or {}).get("code") == "OR1006_BRIEF_CONFLICT":
                break
            again = self._design_it_again(
                run, report, intent=interpreted.value,
                requirements=requirements, cancellation=cancellation)
            if again is None:
                break
            payload, document, report = again
            seen_gate_patches = set()
            payload, document, report = self._repair_until_it_passes(
                run, payload, document, report,
                cancellation=cancellation,
                seen_gate_patches=seen_gate_patches,
                budget=self._config.max_gate_repairs_after_a_redesign)

        if (report.overall_status is not Status.FAIL and self._config.last_look
                and self._provider.info.supports_images):
            try:
                looked = self._last_look(run, payload, report,
                                         seen_patches=seen_gate_patches,
                                         cancellation=cancellation)
            except CancelledError:
                # Cancelled while looking over a part that passed every
                # check: the part is the answer, and it is released.
                run.record(State.VERIFYING, "cancelled during the last look; "
                           "the part is released as it passed")
                looked = None
            except BudgetExceededError:
                run.record(State.VERIFYING, "no budget left for the last "
                           "look; the part is released as it passed")
                looked = None
            except ModelError as error:
                run.record(State.VERIFYING, "the last look could not be made "
                           f"({error.code}); the part is released as it "
                           "passed")
                looked = None
            except Exception as error:  # noqa: BLE001 - a look is optional;
                # the part passed every check before it, and a fault in the
                # look never costs the user that part.
                run.record(State.VERIFYING,
                           "FORGE DEFECT (survived): the last look failed "
                           f"with {type(error).__name__}: {error}"[:400]
                           + "; the part is released as it passed")
                looked = None
            if looked is not None:
                payload, document, report = looked
                run.document_payload = payload
                run.report = report
        return self._finish(run, report)

    def _design_it_again(
        self,
        run: DesignRun,
        report: VerificationReport | None,
        *,
        intent: Any,
        requirements: Any,
        cancellation: CancellationToken | None,
    ) -> tuple[Mapping[str, Any], Document, VerificationReport] | None:
        """The repairs left the design failing: it is designed once more,
        from the requirements, with what failed and what the repairs found
        in hand -- and the new design is kept only if it measures better.

        A design whose construction is wrong is not one edit from right. An
        L-bracket folded about the wrong line, its legs short by a bend
        allowance: two rounds of the analyst adjusting the bend found
        nothing, where the same part built as two boxes is exact. A repair
        edits the design it is given; this is the engineer starting the
        part again, knowing what went wrong the first time."""
        if report is not None:
            failing = sorted(
                r.gate.identifier for r in report.gate_results
                if r.status in (Status.FAIL, Status.BLOCKED)
                and r.gate.critical)
            if not failing:
                return None
            lessons = _what_the_first_design_taught(run, report)
            said = ("the repairs left " + ", ".join(failing[:6])
                    + (" and more" if len(failing) > 6 else "")
                    + " failing: designing the part again, told what failed")
        else:
            failing = []
            lessons = _why_the_first_design_did_not_build(run)
            said = ("the design could not be made to compile: designing the "
                    "part again, told why")
        kept_failure = run.failure
        kept_from = run.repairs_from
        # The second design's own repairs are what its analyst is shown.
        run.repairs_from = len(run.repairs)
        run.record(State.DESIGNING, said, failing=failing)
        try:
            drafted = self._roles["designer"].run(
                self._provider, cancellation=cancellation, intent=intent,
                requirements=requirements, answers=run.answers,
                brief=run.brief, lessons=lessons)
        except CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the first design stands
            run.failure = kept_failure
            run.repairs_from = kept_from
            run.record(State.DESIGNING,
                       "the part could not be designed again "
                       f"({type(error).__name__}); the first design stands")
            return None
        draft = drafted.value
        run.record(State.DESIGNING, "designed again: "
                   f"{len(draft.document.components)} component(s)",
                   usage=drafted.usage, attempts=drafted.attempts,
                   rationale=draft.rationale,
                   answer=getattr(draft, "answer", None))
        for note in getattr(draft, "notes", ()):
            run.record(State.DESIGNING, note)
        _note_role_repairs(run, drafted)
        try:
            compiled = self._compile_with_repair(
                run, draft.payload, draft.document, cancellation=cancellation)
            if compiled is None:
                raise CompileError("the second design did not compile")
            payload, document = compiled
            after = self._verify(document, document.components[0].identifier)
        except CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the first design stands
            run.failure = kept_failure
            run.repairs_from = kept_from
            run.record(State.DESIGNING,
                       "the second design could not be built and measured "
                       f"({type(error).__name__}); the first design stands")
            return None
        self._look(run, after, "designed again")
        now = sorted(
            r.gate.identifier for r in after.gate_results
            if r.status in (Status.FAIL, Status.BLOCKED) and r.gate.critical)
        if report is not None:
            # Better means fewer checks failing AND every requirement still
            # measured: a part with no surface returns from verification with
            # one or two checks, and "failed fewer" would have replaced a
            # near miss with nothing.
            measured_before = {r.gate.identifier for r in report.gate_results
                               if r.gate.identifier.startswith("REQ_")}
            measured_now = {r.gate.identifier for r in after.gate_results
                            if r.gate.identifier.startswith("REQ_")}
            missing = measured_before - measured_now
            if len(now) >= len(failing) or missing:
                run.failure = kept_failure
                run.repairs_from = kept_from
                run.record(
                    State.DESIGNING,
                    f"the second design fails {len(now)} check(s) where the "
                    f"first fails {len(failing)}"
                    + (f", and does not measure {', '.join(sorted(missing))}"
                       if missing else "")
                    + "; the first design stands")
                return None
        run.record(State.VERIFYING,
                   f"the second design fails {len(now)} check(s) where the "
                   f"first failed {len(failing)}: it replaces the first",
                   failing=now)
        run.draft = draft
        run.document_payload = payload
        run.report = after
        run.failure = None
        run.repairs_from = len(run.repairs)
        return payload, document, after

    def _repair_until_it_passes(
        self,
        run: DesignRun,
        payload: Mapping[str, Any],
        document: Document,
        report: VerificationReport,
        *,
        cancellation: CancellationToken | None,
        seen_gate_patches: set[str],
        budget: int,
    ) -> tuple[Mapping[str, Any], Document, VerificationReport]:
        """The gate repair loop: up to `budget` rounds of the analyst's
        edits, each kept only if the part is better for it. Returns the
        design and its report as the loop left them."""
        component_id = document.components[0].identifier
        gate_repairs = 0
        # Carried across rounds, not rebuilt inside each one. The compile path
        # already did this; the gate path passed a fresh `set()` every time,
        # which meant the oscillation check could never fire -- it was asking
        # whether this round had proposed the same patch twice, and a round
        # only proposes once. Observed live on the first run to reach here: the
        # analyst proposed "Add geometry to interface", it changed nothing, and
        # the identical patch was proposed and applied again on the next round.
        # Ninety seconds of generation to learn what we already knew.
        # Gates a repair broke and was taken back for: the same ones broken
        # twice is a conflict; once is a bad repair.
        broken_by_repairs: set[str] = set()
        # Holes Forge has re-aimed once: never re-aimed again, whatever the
        # evidence says next round.
        re_aimed: set[str] = set()
        while (
            report.overall_status is Status.FAIL
            and gate_repairs < budget
        ):
            gate_repairs += 1
            conflict = _the_brief_s_own_conflict(run, report)
            if conflict:
                # The brief's own figures put two openings into each other;
                # every gate still failing is that collision. No design can
                # fix it, and a model round spent trying only moves one of
                # them somewhere the brief did not put it.
                run.record(
                    State.REPAIRING,
                    "not repairing: the brief's own figures make two of its "
                    "openings run into each other, and every gate still "
                    "failing is that collision",
                )
                run.failure = {
                    "message": "the brief places two of its openings so they "
                               "run into each other",
                    "code": "OR1006_BRIEF_CONFLICT",
                    "problems": conflict,
                }
                break
            # Before spending a model round, spend Forge's own certainty. A
            # hole drilled through empty air has one right answer and Forge
            # can find it in under a millisecond; asking a three-billion
            # parameter model on a laptop cost 275 seconds, an invalid patch
            # set, and then the same answer twice. See
            # `_put_the_holes_back_in_the_part`.
            settled = self._put_the_holes_back_in_the_part(
                run, payload, document, report, tried=re_aimed
            )
            if settled is not None:
                before = (payload, document, report)
                payload, document, aimed = settled
                re_aimed |= aimed
                component_id = document.components[0].identifier
                after = self._verify(document, component_id)
                still = set((after.measurements or {}).get("part", {}).get(
                    "features_without_a_surface", []) or [])
                if aimed & still or _gates_this_repair_broke(report, after):
                    # The probe found material along the new axis, but the
                    # finished part still has no trace of the hole: the
                    # material it found is filled back in later. Aiming was
                    # not the fault. Put it back and let the analyst look.
                    payload, document, report = before
                    self._abandon_the_last_repair(
                        run, "the re-aimed hole is still not on the finished "
                        "part, so aiming was not what was wrong")
                    continue
                run.document_payload = payload
                report = after
                run.report = report
                continue
            repaired = self._repair_gates(
                run,
                payload,
                report,
                gate_repairs,
                seen_patches=seen_gate_patches,
                cancellation=cancellation,
            )
            if repaired is None:
                if _worth_another_round(run):
                    # A patch that would not apply is not a reason to give up
                    # the remaining budget: the analyst is handed every previous
                    # attempt including this one's error, and a bad pointer is
                    # the mistake it most often corrects on being shown it.
                    continue
                break
            kept = (payload, document)
            payload, document = repaired
            component_id = document.components[0].identifier
            try:
                after = self._verify(document, component_id)
            except CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the design before
                # it stands. A repair that builds but cannot be measured is
                # a repair that did not work, not a run that crashed.
                payload, document = kept
                component_id = document.components[0].identifier
                run.document_payload = payload
                self._abandon_the_last_repair(
                    run, "the repaired part could not be measured "
                    f"({type(error).__name__}: {str(error)[:200]}); keeping "
                    "the design before it")
                continue
            if run.repairs and _measures_the_same(report, after):
                # The edit applied and built, and the part is the part it
                # was: the bracket's analyst re-set a bend's `along` to the
                # value it had and moved `position` along the crease, and was
                # shown the same failure with nothing to say its edit had
                # done nothing. Said, so the next round looks elsewhere.
                from dataclasses import replace as _replace

                run.repairs[-1] = _replace(
                    run.repairs[-1],
                    outcome=run.repairs[-1].outcome + "; the part it built "
                    "measures exactly as before -- the same envelope, volume "
                    "and holes -- so this edit did not reach what the failing "
                    "checks measure. Look at a different field.")
            broken = _gates_this_repair_broke(report, after)
            if broken:
                # The repair traded one failure for another. Observed on a
                # shaft collar: told the z extent had to be 12 mm, the analyst
                # set the body's height to 12 -- which is the collar's length,
                # already passing at 15 mm against the requirement that states
                # it. The next round put it back to 15, the round after
                # proposed 15 again, and the loop ended on oscillation three
                # attempts later with the part no better than it started.
                #
                # A repair is only a repair if the design is better after it.
                # Breaking a gate that was passing is how a bounded loop turns
                # into a random walk, and the two requirements in conflict are
                # named here because that conflict -- not the geometry -- is
                # what a person has to resolve.
                run.record(
                    State.REPAIRING,
                    "the repair broke "
                    + ", ".join(sorted(broken))
                    + ", which passed before it; keeping the previous design "
                    "rather than trading one failure for another",
                )
                # One bad repair is not a conflict between requirements. A
                # calf shell's analyst fixed its opening and broke both pivot
                # holes on the same round, and the run ended there, "two
                # requirements disagreeing", with rounds still in hand. It is
                # taken back and the analyst told what it broke; only the
                # same requirements broken again is a conflict.
                fixed = sorted(_failing_gates(report) - _failing_gates(after))
                if run.repairs:
                    from dataclasses import replace as _replace

                    run.repairs[-1] = _replace(
                        run.repairs[-1], abandoned=True,
                        outcome="reverted: it broke " + ", ".join(sorted(
                            broken)) + ", which passed before it"
                        + (" (it did fix " + ", ".join(fixed) + ")"
                           if fixed else "")
                        + ". Fix the failing gates again WITHOUT changing "
                        "what those depend on.")
                broken_before = set(broken_by_repairs)
                broken_by_repairs |= set(broken)
                payload, document = kept
                component_id = document.components[0].identifier
                run.document_payload = payload
                if not (set(broken) & broken_before) and (
                        gate_repairs < budget):
                    continue
                if not (set(broken) & broken_before):
                    # The rounds ran out on one bad repair: that is not two
                    # requirements in conflict, and saying so sent the next
                    # design off to reconcile a disagreement that was not
                    # there.
                    run.failure = {
                        "message": "the last repair broke "
                        + ", ".join(sorted(broken))
                        + " and was taken back; the rounds ran out",
                        "code": "OR1007_LAST_REPAIR_REVERTED",
                        "problems": [run.repairs[-1].diagnosis[:600]
                                     if run.repairs else ""],
                    }
                    break
                run.failure = {
                    "message": (
                        "the repair could not satisfy one requirement without "
                        "breaking another"
                    ),
                    "code": "OR1005_TRADED_FAILURE",
                    "problems": [
                        "These requirements cannot all hold at once: "
                        + ", ".join(sorted(broken))
                        + " passed until a change made to satisfy a failing "
                        "gate broke them. Two requirements are describing the "
                        "same dimension and disagreeing about it."
                    ],
                }
                break
            payload, document = payload, document
            run.document_payload = payload
            report = after
            run.report = report

        return payload, document, report

    def _last_look(
        self,
        run: DesignRun,
        payload: Mapping[str, Any],
        report: VerificationReport,
        *,
        seen_patches: set[str],
        cancellation: CancellationToken | None,
    ) -> tuple[Mapping[str, Any], Document, VerificationReport] | None:
        """Every check passed: the model looks at the part against the brief
        once, as an engineer would before signing it off. The checks measure
        what the brief states in figures; the picture shows everything else
        -- a tab patterned into the hollow, an opening on the wrong side, a
        boss that is a plate. A change is kept only when the part still
        passes everything it passed."""
        picture = self._look(run, report, "last look before release")
        if picture is None:
            return None
        failure = {
            "kind": "last_look",
            "message": (
                "Every check passed. This is the last look before the part is "
                "released: compare the picture with the brief, feature by "
                "feature -- every hole, opening, tab, boss, wall and edge the "
                "brief describes, where it says, and nothing it does not "
                "(material where there should be space, space where there "
                "should be material, a feature on the wrong side or the "
                "wrong face) -- and its proportions: each size you can see "
                "against the size the brief gives it, or the standard it "
                "names. An M8 bolt's head is 13 mm across its flats; one "
                "the size of a saucer is wrong however many checks pass."),
            "note": (
                "If the part matches the brief, set `abandon` true with "
                "`abandon_reason` \"matches the brief\" -- that releases it. "
                "Patch only what is plainly wrong in the picture, and say "
                "what you saw. Do not change what the checks passed on."),
            "the_part_you_built": (report.measurements or {}).get("part"),
        }
        before_failure = run.failure
        repaired = self._apply_repair(
            run, payload, trigger="last_look", failure=failure,
            pointers=("/components/0",), attempt=len(run.repairs) + 1,
            seen_patches=seen_patches, cancellation=cancellation,
            pictures=(picture,))
        if repaired is None:
            run.failure = before_failure
            last = (run.repairs[-1] if run.repairs
                    and run.repairs[-1].trigger == "last_look" else None)
            if last is not None and last.outcome != "abandoned":
                # It saw something and its change could not be used -- would
                # not apply, build, or differ. Said as that, not as "nothing
                # to change": the model may have seen a real fault.
                run.record(State.VERIFYING,
                           ("the last look saw a fault and wrote no edit for "
                            "it; the part is released as it passed -- read "
                            "what it saw"
                            if last.outcome.startswith("saw a fault") else
                            "the last look proposed a change that could not "
                            f"be used ({last.outcome[:200]}); the part is "
                            "released as it passed"),
                           saw=last.diagnosis[:600])
                return None
            if last is not None:
                from dataclasses import replace as _replace

                run.repairs[-1] = _replace(
                    last, outcome="looked: nothing to change",
                    abandoned=False)
            said = last.diagnosis if last is not None else ""
            run.record(State.VERIFYING,
                       "looked at the part against the brief: nothing to change",
                       saw=said[:600])
            return None
        new_payload, document = repaired
        try:
            after = self._verify(document, document.components[0].identifier)
        except Exception as error:  # noqa: BLE001 - the part as it passed
            self._abandon_the_last_repair(            # stands
                run, "the change made on the last look could not be "
                f"measured ({type(error).__name__}); the part is released "
                "as it passed")
            return None
        broken = _gates_this_repair_broke(report, after)
        # Every check that passed still passes, and the part is as
        # releasable as it was: a change that leaves a check inconclusive,
        # or a requirement with nothing to measure, costs the release.
        was = {r.gate.identifier for r in report.gate_results
               if r.status is Status.PASS}
        now = {r.gate.identifier for r in after.gate_results
               if r.status is Status.PASS}
        lost = was - now
        worse = (report.overall_status is Status.PASS
                 and after.overall_status is not Status.PASS)
        if broken or lost or worse or after.overall_status is Status.FAIL:
            # Undoing what a repair did to pass a check is not breaking the
            # part. The validation suite's counterbored plate: Forge counted
            # one counterbore where the brief said two, the repair took the
            # second off to pass, and the last look saw it and put it back
            # -- and was reverted, and a wrong part released as passing.
            # When the look's change fails only checks this run had to be
            # repaired to pass, the brief and a check are read two ways: the
            # part is held for a person, with what the look saw.
            undone = set(broken) | set(lost)
            looked = (run.repairs[-1] if run.repairs
                      and run.repairs[-1].trigger == "last_look" else None)
            if (undone and looked is not None
                    and undone <= _gates_repairs_were_made_for(run)):
                held = self._held_for_a_person(
                    run, payload, sorted(undone), looked.diagnosis)
                if held is not None:
                    return held
            self._abandon_the_last_repair(
                run, "the change made on the last look left "
                + ", ".join(sorted(broken | lost or _failing_gates(after))
                            or ["the part not releasable"])
                + " no longer passing; the part is released as it passed")
            return None
        run.record(State.VERIFYING,
                   "changed what the last look found, and it still passes "
                   "everything")
        return new_payload, document, after

    def _held_for_a_person(
        self,
        run: DesignRun,
        payload: Mapping[str, Any],
        disputed: Sequence[str],
        saw: str,
    ) -> tuple[Mapping[str, Any], Document, VerificationReport] | None:
        """The part as it passed, held: an assumption nobody has accepted
        says what the last look saw and which checks its correction fails.
        A person looks at the part and accepts it, or does not."""
        from dataclasses import replace as _replace

        held = json.loads(json.dumps(payload))
        assumptions = held.setdefault("assumptions", [])
        if not isinstance(assumptions, list):
            return None
        taken = {str(a.get("id", "")) for a in assumptions
                 if isinstance(a, Mapping)}
        identifier = "ASM_LAST_LOOK_DISAGREES"
        while identifier in taken:
            identifier += "_"
        checks = ", ".join(disputed)
        assumptions.append({
            "id": identifier,
            "statement": (
                "The part passes every check, and the last look at it "
                "against the brief found: " + " ".join(saw.split())[:500]
                + f" Correcting that fails {checks}, which this run had to "
                "repair the design to pass. The brief and that check are "
                "read two ways. Accept this only once you have looked at the "
                "part and it is what the brief asks for."),
            "rationale": (
                "The last look's correction undid a repair made to pass "
                f"{checks}; neither reading is kept over the other without "
                "a person."),
            "consequence_if_wrong": (
                "A part that does not match the brief is released with every "
                "check passing."),
            "risk": "high",
            "reversible": True,
            "approved": False,
        })
        try:
            document = Document.from_json(json.dumps(held))
            after = self._verify(document, document.components[0].identifier)
        except Exception:  # noqa: BLE001 - the part as it passed stands
            return None
        if run.repairs:
            run.repairs[-1] = _replace(
                run.repairs[-1], abandoned=True,
                outcome=f"held: the correction fails {checks}, which a repair "
                        "made pass")
        run.record(State.VERIFYING,
                   "the last look found the part does not match the brief, "
                   f"and correcting it fails {checks}, which a repair made "
                   f"pass: held for a person (`{identifier}`), not released",
                   saw=saw[:600], disputed=list(disputed))
        return held, document, after

    #: How many of Forge's repairs, newest first, are tried without when a
    #: design fails its checks. Each costs one build and one verification.
    _REPAIRS_TRIED_WITHOUT = 4

    def _without_a_repair_that_hurt(
        self, run: DesignRun, draft: Any, report: VerificationReport,
        **inputs: Any,
    ) -> tuple[Any, VerificationReport] | None:
        """The design without one of Forge's own repairs, when the part
        measures strictly better without it.

        Every repair Forge makes is a reading of the brief or of the model's
        answer, and a reading can be wrong. The part is the judge: each of
        the last few repairs that changed this design is left out in turn,
        the design rebuilt and measured, and the first that fails fewer of
        the checks -- and breaks none that passed -- replaces it. A repair
        is never taken back to let a design through on a technicality: the
        checks are the same checks.
        """
        designer = self._roles["designer"]
        if not hasattr(designer, "without"):
            return None
        made = list(getattr(draft, "repairs_made", ()) or ())
        if not made:
            return None

        def failing(r: VerificationReport) -> set[str]:
            return {g.gate.identifier for g in r.gate_results
                    if g.status in (Status.FAIL, Status.BLOCKED)
                    and g.gate.critical}

        before = failing(report)
        for name in list(reversed(made))[: self._REPAIRS_TRIED_WITHOUT]:
            try:
                alternative = designer.without(draft, name, **inputs)
                if alternative is None:
                    continue
                document = alternative.document
                after = self._verify(document, document.components[0].identifier)
            except Exception:  # noqa: BLE001 - an alternative that cannot be
                continue       # built is no better; the original stands
            now = failing(after)
            if len(now) < len(before) and not (now - before):
                run.record(
                    State.REPAIRING,
                    f"took back Forge's own repair `{name}`: with it the part "
                    f"failed {len(before)} check(s), without it "
                    f"{len(now)}, and nothing that passed with it fails "
                    "without it",
                    without=name, fixed=sorted(before - now))
                return alternative, after
        return None

    # ------------------------------------------------------------------
    def _finish(self, run: DesignRun, report: VerificationReport) -> DesignRun:
        status = report.overall_status
        self._look(run, report, "the part as finished: "
                   + status.value.lower(), last=True)
        if status is Status.PASS:
            warnings = list(getattr(report, "warnings", ()))
            run.record(
                State.COMPLETED,
                "every gate passed and no assumption blocks release"
                if not warnings else
                # A release candidate with a finding against it is still a
                # release candidate, and a person who reads only this line
                # still has to be told. The spacer built 30 x 12 instead of
                # 30 x 30 ended a run on the unqualified sentence above.
                f"released with {len(warnings)} finding"
                f"{'' if len(warnings) == 1 else 's'} worth reading: "
                + "; ".join(w.split(": ", 1)[-1] for w in warnings),
                gates=report.evidence.summary(),
                warnings=warnings,
            )
        elif status is Status.FAIL:
            run.record(
                State.BLOCKED,
                "the design does not meet its requirements",
                reasons=list(report.release_reasons),
                gates=report.evidence.summary(),
            )
        else:
            run.record(
                State.BLOCKED,
                f"not a release candidate: {status.value.lower()}",
                reasons=list(report.release_reasons),
                gates=report.evidence.summary(),
            )
        return run

    def _look(self, run: DesignRun, report: VerificationReport,
              caption: str, *, last: bool = False) -> bytes | None:
        """The part drawn: six views, what failed marked on them. Kept on
        the run, handed to whoever is watching, and shown to the model when
        it can see. Drawn once per distinct part."""
        if run.listener is None and not self._provider.info.supports_images:
            return None  # nobody to show it to
        key = getattr(report.part, "part_hash", "") + ":" + ",".join(
            sorted(g.gate.identifier for g in report.gate_results
                   if g.status in (Status.FAIL, Status.BLOCKED)))
        fresh = key not in self._drawn
        if fresh:
            from forge_pipeline.render import render_report

            self._drawn[key] = render_report(report)
        png = self._drawn[key]
        # The part as finished is always the last picture, drawn before or
        # not: after a second design was tried and set aside, the last one
        # drawn was the part that was NOT released.
        if fresh or (last and png is not None and (
                not run.pictures or run.pictures[-1][1] is not png)):
            if png is not None:
                run.pictures.append((caption, png))
                listener = run.listener
                if listener is not None:
                    try:
                        listener("picture", (caption, png))
                    except Exception:  # noqa: BLE001 - never stops a run
                        pass
        return self._drawn[key]

    def _verify(self, document: Document, component_id: str) -> VerificationReport:
        load_case = _load_case_from(document)
        return verify_component(
            document,
            document.component(component_id),
            compiler=self._compiler,
            load_case=load_case,
            measurement_depth=self._config.measurement_depth,
            mesh_resolution=self._config.mesh_resolution,
        )

    # ------------------------------------------------------------------
    def _compile_with_repair(
        self,
        run: DesignRun,
        payload: Mapping[str, Any],
        document: Document,
        *,
        cancellation: CancellationToken | None,
    ) -> tuple[Mapping[str, Any], Document] | None:
        seen_patches: set[str] = set()

        for attempt in range(0, self._config.max_compile_repairs + 1):
            try:
                self._compiler.compile_component(document.components[0])
            except CompileError as error:
                if attempt == self._config.max_compile_repairs:
                    run.failure = {
                        "message": "the design could not be made to compile",
                        "code": error.code,
                        "problems": [error.message],
                        "detail": dict(error.detail),
                    }
                    return None
                run.record(
                    State.REPAIRING,
                    f"compile failed: {error.message}",
                    attempt=attempt + 1,
                    code=error.code,
                    **{
                        key: value
                        for key, value in error.detail.items()
                        if key in ("feature", "kind", "parameter", "pointer")
                    },
                )
                outcome = self._apply_repair(
                    run,
                    payload,
                    trigger="compile",
                    failure=_compile_failure_payload(error),
                    pointers=_pointers_from(error, payload),
                    attempt=attempt + 1,
                    seen_patches=seen_patches,
                    cancellation=cancellation,
                )
                if outcome is None:
                    if _worth_another_round(run):
                        continue
                    return None
                payload, document = outcome
                continue
            return payload, document
        return None

    def _put_the_holes_back_in_the_part(
        self,
        run: DesignRun,
        payload: Mapping[str, Any],
        document: Document,
        report: VerificationReport,
        tried: set[str] | None = None,
    ) -> tuple[Mapping[str, Any], Document, set[str]] | None:
        """Re-aim a through-hole that was drilled through empty air.

        The first run ever to reach the designer produced a plate, a post, a
        2 mm fillet and three holes, and every dimension measured correct. It
        was blocked because both mounting holes were at z = 5 with
        `axis: [0, 1, 0]` -- above the plate, outside the post, drilling
        through nothing. They contributed no surface, so the part had no
        mounting holes in it.

        That is a defect with one right answer and no judgement in it. A
        through-hole exists to pass through material; if it passes through
        none, the axis is wrong, and `axis` has a documented default of
        `[0, 0, 1]` which is also the build direction and the direction a hole
        through a flat plate runs. So: try the default. If it puts the hole
        through material, that is the answer, and Forge writes it.

        Cheap enough to be free. Compiling a component warm with
        `validate_geometry=False` is under a millisecond -- measured against
        2.8 seconds for one verification -- because the SDF tree is built
        lazily and every ancestor feature is already a cache hit. The model
        alternative was measured too: 275 seconds over two attempts, an
        invalid patch set, and then the identical proposal, which is what
        ended the run.

        Deliberately conservative in three ways. Only the documented default
        is tried, never a search over all six directions: at z = 5 a hole at
        x = 10 also passes through the post along X, so "whichever axis finds
        the most material" would have drilled sideways through the boss and
        called it done. Only holes the evidence names as contributing no
        surface are touched. And only a hole with no `depth`, because a
        counterbored or blind hole placed in air is a positioning mistake
        rather than an aiming one, and Forge does not know where it was meant
        to go.

        Returns the repaired payload and document and the holes re-aimed,
        or None when there is nothing here Forge can settle.
        """
        from copy import deepcopy

        described = (report.measurements or {}).get("part") or {}
        absent = [str(name) for name in described.get(
            "features_without_a_surface", []) or []]
        if not absent:
            return None

        component = document.components[0]
        try:
            features = {f.identifier: f for f in component.features}
        except Exception:  # noqa: BLE001 - a graph we cannot walk is not ours
            return None

        candidates: list[Any] = []
        patched = deepcopy(dict(payload))
        for identifier in absent:
            feature = features.get(identifier)
            if feature is None or feature.kind != "hole":
                continue
            if tried and identifier in tried:
                continue
            parameters = feature.parameters or {}
            through = parameters.get("through")
            if "depth" in parameters or str(getattr(
                    through, "option", through) or "") == "first_wall":
                # Through one wall, it is aimed at that wall on purpose:
                # turned to z it would go through the roof of the hollow.
                # A blind or counterbored hole placed in air is a positioning
                # mistake, not an aiming one, and where it was meant to go is
                # not something Forge knows.
                continue
            if _is_the_default_axis(parameters.get("axis")):
                # It already points along the default, so the hole is in the
                # wrong place rather than pointed the wrong way.
                continue
            slot = self._slot_in(patched, feature.pointer)
            if slot is None:
                continue
            slot.setdefault("parameters", {})
            slot["parameters"]["axis"] = [0.0, 0.0, 1.0]
            candidates.append(feature)

        if not candidates:
            return None

        # One decode and one compile answers for every candidate at once.
        # Compiling warm without geometry validation is sub-millisecond; the
        # 2.8 seconds is all in the octree measurement, which is not run here.
        try:
            rebuilt = Document.from_json(json.dumps(patched))
            probe = self._compiler.compile_component(
                rebuilt.components[0], validate_geometry=False
            )
        except Exception:  # noqa: BLE001 - a probe that cannot run says nothing
            return None

        fixed: list[str] = []
        for feature in candidates:
            if _the_bore_found_material(probe, feature):
                fixed.append(feature.identifier)
                continue
            # Aiming it along the default did not help either, so put this
            # one back the way the model wrote it and leave it to the analyst.
            slot = self._slot_in(patched, feature.pointer)
            original = (
                self._slot_in(payload, feature.pointer) or {}
            ).get("parameters") or {}
            if slot is None:
                continue
            if "axis" in original:
                slot["parameters"]["axis"] = deepcopy(original["axis"])
            else:
                slot["parameters"].pop("axis", None)

        if not fixed:
            return None
        if len(fixed) != len(candidates):
            try:
                rebuilt = Document.from_json(json.dumps(patched))
            except (SchemaError, SchemaErrorGroup):
                return None

        note = (
            ", ".join(fixed)
            + " left no surface on the part: the axis pointed somewhere there "
            "was no material, so the hole was drilled through open air. "
            "Re-aimed along [0, 0, 1] -- the documented default, the build "
            "direction, and the way a hole through a flat plate runs -- "
            "which does pass through the part."
        )
        run.record(State.REPAIRING, note)
        run.repairs.append(
            RepairAttempt(
                attempt=len(run.repairs) + 1,
                trigger="geometry",
                diagnosis=note,
                strategy="re-aim a through-hole that cut no material",
                patches=tuple(
                    {
                        "op": "replace",
                        "pointer": f"{features[name].pointer}/parameters/axis",
                        "value": [0.0, 0.0, 1.0],
                        "reason": "the hole cut no material as aimed",
                    }
                    for name in fixed
                ),
                outcome="applied",
            )
        )
        return patched, rebuilt, set(fixed)

    @staticmethod
    def _abandon_the_last_repair(run: DesignRun, why: str) -> None:
        """Mark the last repair taken back, and say so in the run."""
        from dataclasses import replace

        if run.repairs:
            run.repairs[-1] = replace(
                run.repairs[-1], outcome="reverted", abandoned=True)
        run.record(State.REPAIRING, f"reverted: {why}")

    @staticmethod
    def _slot_in(payload: Any, pointer: str) -> dict[str, Any] | None:
        """The mutable dict a JSON Pointer addresses, or None.

        Addressed by the feature's own `pointer` rather than by position:
        `FeatureGraph` iterates topologically, not in array order, so
        enumerating it and trusting the index rewires the wrong feature.
        """
        node: Any = payload
        for token in [t for t in str(pointer).split("/") if t]:
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                try:
                    node = node[int(token)]
                except (ValueError, IndexError):
                    return None
            elif isinstance(node, dict) and token in node:
                node = node[token]
            else:
                return None
        return node if isinstance(node, dict) else None

    def _repair_gates(
        self,
        run: DesignRun,
        payload: Mapping[str, Any],
        report: VerificationReport,
        attempt: int,
        *,
        seen_patches: set[str],
        cancellation: CancellationToken | None,
    ) -> tuple[Mapping[str, Any], Document] | None:
        failing = [
            result
            for result in report.gate_results
            if result.status is Status.FAIL and result.gate.critical
        ]
        if not failing:
            return None
        # A check that could not be read is said too: what it needed is
        # often the very thing the failing ones are missing.
        failing += [
            result for result in report.gate_results
            if result.status is Status.BLOCKED and result.gate.critical
        ]

        run.record(
            State.REPAIRING,
            f"{len(failing)} gate(s) failed; attempting a design change",
            attempt=attempt,
            gates=[result.gate.identifier for result in failing],
        )
        measurements = dict(report.measurements)
        facts = measurements.pop("part", None)
        failure = {
            "kind": "gate_failure",
            "message": "the geometry is valid but does not meet its requirements",
            "note": (
                "Change the design so the requirement is met. Do not change the "
                "requirement, the threshold, or the comparison."
            ),
            "failed_gates": [_gate_failure(result) for result in failing],
            "measurements": measurements,
        }
        bends = _what_each_bend_does(report, failing)
        if bends:
            failure["bends"] = bends
        if facts:
            # The analyst has never been able to see what it built. It got gate
            # names and numbers and had to infer the shape from them, which is
            # why it patches dimensions when the real fault is that a hole is
            # missing or a plate is in the wrong plane. This is the measured
            # object, in words.
            failure["the_part_you_built"] = facts
        # And now in a picture, to a model that can see one.
        picture = self._look(run, report, f"repair round {attempt}: "
                             + ", ".join(r.gate.identifier for r in failing))
        pictures = ((picture,) if picture is not None
                    and self._provider.info.supports_images else ())
        return self._apply_repair(
            run,
            payload,
            trigger="gate",
            failure=failure,
            pointers=("/components/0",),
            attempt=attempt,
            seen_patches=seen_patches,
            cancellation=cancellation,
            pictures=pictures,
        )

    # ------------------------------------------------------------------
    def _apply_repair(
        self,
        run: DesignRun,
        payload: Mapping[str, Any],
        *,
        trigger: str,
        failure: Mapping[str, Any],
        pointers: Sequence[str],
        attempt: int,
        seen_patches: set[str],
        cancellation: CancellationToken | None,
        pictures: Sequence[bytes] = (),
    ) -> tuple[Mapping[str, Any], Document] | None:
        # context=0: the pointers are already anchored on whole objects by
        # _pointers_from, so lifting again would hand back the enclosing array
        # -- which for a single-component document is the entire design.
        document_slice = extract_slice(payload, pointers, context=0) or {
            "/components/0": payload.get("components", [{}])[0]
        }

        try:
            proposed = self._roles["analyst"].run(
                self._provider,
                cancellation=cancellation,
                failure=failure,
                document_slice=document_slice,
                attempt=attempt,
                previous_attempts=[r.as_dict() for r in
                                   run.repairs[run.repairs_from:]],
                pictures=tuple(pictures),
                brief=run.brief,
            )
        except RepairExhaustedError as error:
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis="the analyst could not produce a valid proposal",
                    strategy="",
                    patches=(),
                    outcome="analyst_failed",
                )
            )
            run.failure = {
                "message": "repair could not be proposed",
                "code": error.code,
                "problems": list(error.detail.get("last_problems", [])),
            }
            return None
        except (CancelledError, BudgetExceededError):
            raise
        except (ModelError, RoleError) as error:
            # The service failed after its retries, or the answer could not
            # be read at all: this round is lost, and the run is not. The
            # design as it stands is reported, and a second design may still
            # be tried.
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis=f"the analyst could not be asked: {error.message}",
                    strategy="",
                    patches=(),
                    outcome=f"analyst_failed: {error.code}",
                )
            )
            run.failure = {
                "message": "repair could not be proposed",
                "code": error.code,
                "problems": [error.message],
            }
            run.record(State.REPAIRING,
                       f"the analyst could not be asked ({error.code}); the "
                       "design stands as it is")
            return None

        proposal = proposed.value
        run.usage = run.usage + proposed.usage
        _note_role_repairs(run, proposed)

        if proposal.abandon:
            # A last look that saw a fault and wrote no edit for it, asked
            # twice, is not a look that found the part right: the forearm
            # rail's saw its lug rounded 8 mm where the brief says 12 and was
            # recorded "nothing to change". Said as what it was.
            saw_a_fault = trigger == "last_look" and not proposal.found_nothing
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis=proposal.diagnosis,
                    strategy=proposal.strategy,
                    patches=(),
                    outcome=("saw a fault and wrote no edit for it"
                             if saw_a_fault else "abandoned"),
                    abandoned=True,
                )
            )
            if trigger == "last_look":
                # Not a repair given up: the last look found the part as the
                # brief asks. `_last_look` says so in its own words.
                return None
            run.record(
                State.REPAIRING,
                f"repair abandoned: {proposal.abandon_reason}",
                diagnosis=proposal.diagnosis,
            )
            run.failure = {
                "message": proposal.abandon_reason or "repair abandoned",
                "code": "OR1001_REPAIR_ABANDONED",
                "problems": [proposal.diagnosis],
            }
            return None

        signature = _patch_signature(proposal.patches)
        if signature in seen_patches:
            # The same edit, proposed twice, for the same failure. A third
            # attempt buys the same answer at the same price.
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis=proposal.diagnosis,
                    strategy=proposal.strategy,
                    patches=proposal.patches,
                    outcome="oscillation",
                )
            )
            run.record(
                State.REPAIRING,
                "the same repair was proposed twice; stopping rather than "
                "looping",
                diagnosis=proposal.diagnosis,
            )
            run.failure = {
                "message": "the repair loop began repeating itself",
                "code": "OR1002_OSCILLATION",
                "problems": [proposal.diagnosis],
            }
            return None
        seen_patches.add(signature)

        try:
            patches = [Patch.from_dict(p) for p in proposal.patches]
            patched = apply_patches(payload, patches)
        except PatchError as error:
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis=proposal.diagnosis,
                    strategy=proposal.strategy,
                    patches=proposal.patches,
                    outcome=f"patch_rejected: {error.message}",
                )
            )
            run.record(
                State.REPAIRING, f"the proposed patch was invalid: {error.message}"
            )
            return None

        # Forge's own certainties, applied to the analyst's design exactly as
        # to the designer's. A patch that adds a hole with a diameter of "6"
        # at the bore's own position is two mistakes Forge settles in a
        # designer answer; applied raw, the patched document was refused.
        events_before = len(run.events)
        settled = self._settle(run, patched)
        settle_notes = [str(e.summary) for e in run.events[events_before:]]
        if settled is not patched and not self._builds(settled) \
                and self._builds(patched):
            # Forge's settling broke an edit that builds as written: the
            # analyst's `through: first_wall` given a `depth` back by a
            # repair that did not know the option, and refused at compile.
            # The edit stands as the analyst wrote it.
            run.record(State.REPAIRING,
                       "kept the patch as written: Forge's own repairs on it "
                       "did not build")
            settle_notes = []
        else:
            reasserted, kept = _the_analyst_s_edits_kept(
                payload, settled, proposal.patches)
            if kept and self._builds(reasserted):
                # Forge's own repairs, run again over the patched design,
                # undid what the analyst had just set on purpose -- a radius
                # clamped back after every round, a depth put back on a hole
                # through one wall -- and the analyst was told its edit
                # "changed nothing". Its explicit edits stand; the rest of
                # Forge's repairs are kept.
                run.record(State.REPAIRING,
                           "kept the analyst's edits to " + ", ".join(
                               f"`{k}`" for k in kept[:6])
                           + " over Forge's own repairs, which had undone "
                           "them")
                patched = reasserted
            else:
                patched = settled

        if _the_same_design(payload, patched):
            # Applied, valid, and it changed nothing: the analyst re-set a
            # field to the value it already had. Observed live -- `add` at
            # `/components/0/interfaces/0/geometry` with value `shaft.bore`,
            # which was already `shaft.bore`. Recompiling and re-gating an
            # identical document produces an identical failure, so this is
            # caught here rather than a round later. It is a stronger check
            # than comparing patch signatures, because a *different* patch that
            # also changes nothing lands here too.
            #
            # Compared as a graph rather than as text, because the lists a
            # component holds are addressed by `id` and not by position. A
            # literal comparison missed the analyst's commonest move entirely:
            # removing every feature and re-adding the same ones leaves the
            # design untouched and the list in a new order, and for one run
            # that bought a wasted verify, a wasted analyst round, and a
            # document that would not validate. See `_as_a_graph`.
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis=proposal.diagnosis,
                    strategy=proposal.strategy,
                    patches=proposal.patches,
                    outcome="no_change",
                )
            )
            run.record(
                State.REPAIRING,
                "the patch applied cleanly and changed nothing; stopping "
                "rather than re-measuring an identical design",
                diagnosis=proposal.diagnosis,
            )
            run.failure = {
                "message": "the proposed repair did not change the design",
                "code": "OR1003_NO_CHANGE",
                "problems": [proposal.diagnosis],
            }
            return None

        try:
            document = Document.from_json(json.dumps(patched))
            if not document.components:
                raise SchemaError(
                    "the patched document has no component left",
                    pointer="/components",
                    hint="a repair edits the part; it never removes it")
        except (SchemaError, SchemaErrorGroup) as error:
            problems = problems_from_schema_error(error)[:5]
            # Why, in the outcome itself: the next round's analyst is shown
            # every previous attempt, and "did not validate" alone told it
            # nothing to correct. Observed: `base` removed from under the
            # `shell` that read it, and the run stopped there with a round
            # of its budget unspent.
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis=proposal.diagnosis,
                    strategy=proposal.strategy,
                    patches=proposal.patches,
                    outcome="patched document did not validate: "
                    + " | ".join(str(p)[:300] for p in problems[:3]),
                )
            )
            run.record(
                State.REPAIRING,
                "the patch applied but produced an invalid document",
                problems=problems,
            )
            return None

        # A valid document is not yet a buildable one. A patch that wrote a
        # blend radius as the text "3" validated, and the compiler then
        # refused it inside the gate loop -- which took the run down as an
        # internal error, a defect in Forge, on a design one round from done.
        # A patch that does not build is a failed repair like any other: kept
        # out, its reason handed to the next round.
        try:
            if trigger in ("gate", "last_look"):
                # The compile loop compiles each attempt itself, and feeds a
                # failure back as its next round's subject. A last look's
                # change is checked here too: unchecked, one that did not
                # build took down a collar that had passed everything.
                self._compiler.compile_component(document.components[0])
        except CompileError as error:
            run.repairs.append(
                RepairAttempt(
                    attempt=attempt,
                    trigger=trigger,
                    diagnosis=proposal.diagnosis,
                    strategy=proposal.strategy,
                    patches=proposal.patches,
                    outcome="patched document did not compile: "
                    + str(error.message)[:400],
                )
            )
            run.record(
                State.REPAIRING,
                "the patch applied but the design no longer compiles; keeping "
                "the previous design",
                problems=[str(error.message)[:400]],
            )
            return None

        idle = _patches_that_change_nothing(payload, proposal.patches)
        run.repairs.append(
            RepairAttempt(
                attempt=attempt,
                trigger=trigger,
                diagnosis=proposal.diagnosis,
                strategy=proposal.strategy,
                patches=proposal.patches,
                outcome="applied" + (
                    "; patches " + ", ".join(str(i) for i in idle)
                    + " set values the design already had, and changed "
                    "nothing" if idle else "") + (
                    "; then Forge's own repairs changed it: "
                    + " | ".join(n[:240] for n in settle_notes[:3])
                    if settle_notes else ""),
            )
        )
        run.record(
            State.REPAIRING,
            f"applied {len(patches)} patch(es): {proposal.strategy}",
            diagnosis=proposal.diagnosis,
            patches=[p.render() for p in patches],
        )
        return patched, document


    def _builds(self, payload: Mapping[str, Any]) -> bool:
        """Whether a document payload decodes and compiles."""
        try:
            document = Document.from_json(json.dumps(payload))
            self._compiler.compile_component(document.components[0],
                                             validate_geometry=False)
        except Exception:  # noqa: BLE001 - anything that stops it is a no
            return False
        return True

    def _settle(
        self, run: DesignRun, patched: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """The designer's settling pass over a patched design, if it has one.

        Nothing here can reject a patch -- the checks still come after, in
        `Document.from_json` and the gates. Anything the pass cannot handle
        leaves the patch as the analyst wrote it.
        """
        settle = getattr(self._roles.get("designer"), "settle", None)
        if settle is None:
            return patched
        # The record the document itself carries: already reconciled with
        # the design's names, and with any claim the salvage unbound.
        requirements = run.requirements
        carried = patched.get("requirements")
        if isinstance(carried, list):
            from forge_roles.library import RequirementSet

            requirements = RequirementSet(
                requirements=tuple(dict(r) for r in carried
                                   if isinstance(r, Mapping)),
                assumptions=tuple(dict(a) for a in patched.get(
                    "assumptions", []) or [] if isinstance(a, Mapping)),
                unknowns=(), risk_class=patched.get("risk_class", "low"))
        try:
            settled, notes, _ = settle(
                patched, intent=run.intent, requirements=requirements,
                brief=run.brief, answers=run.answers)
        except Exception:  # noqa: BLE001 - the patch stands as written
            return patched
        for note in notes:
            run.record(State.REPAIRING, note)
        return settled


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
#: Gates a collision between two of the brief's openings fails, and only
#: such a collision: the openings and holes counted, a hole with no wall
#: all round it, a cut that left nothing of its own.
_WHAT_AN_OVERLAP_FAILS = frozenset({
    "GEOM_HOLES_ARE_HOLES", "GEOM_BORES_SURVIVE", "GEOM_FEATURES_CONTRIBUTE",
    "GEOM_DIMENSIONS_DRIVE_THE_PART"})
_AN_OVERLAP_SAID = "THE BRIEF'S OWN FIGURES OVERLAP"


def _the_brief_s_own_conflict(run: Any, report: Any) -> list[str]:
    """The design notes saying the brief's figures overlap, when every
    critical gate failing is one such an overlap fails. Else nothing."""
    said = [str(e.summary) for e in getattr(run, "events", ()) or ()
            if str(getattr(e, "summary", "")).startswith(_AN_OVERLAP_SAID)]
    if not said:
        return []
    failing = [r for r in report.gate_results
               if r.status is Status.FAIL and r.gate.critical]
    if not failing:
        return []
    for result in failing:
        detail = getattr(result.evidence, "detail", None) or {}
        measured = str(detail.get("measurement", "")).partition(":")[0]
        if result.gate.identifier in _WHAT_AN_OVERLAP_FAILS or measured in (
                "openings_of_size", "holes_of_diameter", "opening_at"):
            continue
        return []
    return said


def _gates_this_repair_broke(
    before: VerificationReport, after: VerificationReport
) -> set[str]:
    """Requirements that passed before a repair and fail after it.

    A bounded repair loop assumes every attempt is an improvement. Nothing
    enforced that, so an attempt that fixed one gate by breaking another was
    recorded as progress and the loop walked in circles until its budget ran
    out. PASS -> FAIL counts, and PASS -> BLOCKED: a stepper plate's repair
    clipped its boss away, and the claim on the boss went from passing to
    having nothing to measure. PASS -> INCONCLUSIVE does not: that may be a
    measurement that got harder, not evidence the design got worse.
    """
    def failing(report: VerificationReport) -> dict[str, Status]:
        return {
            result.gate.identifier: result.evidence.status
            for result in report.gate_results
            if result.gate.identifier
        }

    was, now = failing(before), failing(after)
    return {
        identifier
        for identifier, status in was.items()
        if status is Status.PASS
        and now.get(identifier) in (Status.FAIL, Status.BLOCKED)
    }


def _as_a_graph(payload: Any) -> Any:
    """The document with its id-addressed lists in a canonical order.

    A component's `features`, `parameters` and `interfaces` are addressed by
    `id`, never by position: the compiler walks the feature graph in
    dependency order, and a feature finds its operands through `inputs`. So
    two documents whose lists hold the same entries in a different order are
    the same design, and rewriting the list in a new order is not a change.

    Written because the repair loop could not see that. Its no-change guard
    compared payloads literally, and the analyst's most common move is to
    remove every feature and re-add them -- which always lands them in a new
    order and so always looked like progress. Observed on a shaft collar: an
    eight-patch repair removed four features and re-added the same four,
    byte-for-byte, and was recorded as `applied`. Forge then recompiled the
    identical design, measured the identical failure, and spent a second
    analyst round on it, which dropped the body and produced a document that
    would not validate. Four minutes of model time and a worse ending, for a
    patch that did nothing at all.

    Order is preserved wherever it might mean something. Only these three
    lists are sorted, only when every entry carries a distinct `id`, and
    anything else -- a vector, an `inputs` list, an operand order a boolean
    depends on -- is left exactly as it is.
    """
    if isinstance(payload, Mapping):
        return {key: _as_a_graph(value) for key, value in payload.items()}
    if not isinstance(payload, list):
        return payload
    canonical = [_as_a_graph(entry) for entry in payload]
    identifiers = [
        entry.get("id") for entry in canonical if isinstance(entry, Mapping)
    ]
    if (
        len(identifiers) == len(canonical) > 1
        and all(isinstance(i, str) and i for i in identifiers)
        and len(set(identifiers)) == len(identifiers)
    ):
        return sorted(canonical, key=lambda entry: str(entry.get("id")))
    return canonical


def _the_same_design(before: Any, after: Any) -> bool:
    """True when a patch changed nothing the compiler will ever see."""
    return _as_a_graph(before) == _as_a_graph(after)


def _patch_signature(patches: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        [
            {"op": p.get("op"), "pointer": p.get("pointer"), "value": p.get("value")}
            for p in patches
        ],
        sort_keys=True,
        default=str,
    )
    return hashlib.blake2b(encoded.encode(), digest_size=12).hexdigest()


def _spent_since(before: Usage, after: Usage) -> Usage:
    """What this run cost, when the provider may have been used before it."""
    costs = [c for c in (after.cost_usd, before.cost_usd) if c is not None]
    return Usage(
        input_tokens=after.input_tokens - before.input_tokens,
        output_tokens=after.output_tokens - before.output_tokens,
        cached_input_tokens=after.cached_input_tokens - before.cached_input_tokens,
        cost_usd=(
            (after.cost_usd or 0.0) - (before.cost_usd or 0.0) if costs else None
        ),
    )


def _note_role_repairs(run: DesignRun, result: Any) -> None:
    """Record a role that had to correct its own output.

    A role repairs inside itself -- it re-asks with the problems attached -- so
    without this the run log shows one event for what was three model calls. The
    tokens were already counted; what was missing was *why*, which is the part
    that says whether a prompt needs work or a model is struggling.
    """
    # What the transport settled before the role ever saw the answer. A
    # provider that repairs an answer has to say so, or the record of what the
    # model produced is quietly not what it produced. Reported even when the
    # role itself needed no repair, because the model still wrote something
    # that had to be corrected.
    for response in getattr(result, "responses", ()) or ():
        for note in getattr(response, "notes", ()) or ():
            run.record(run.state, note, role=getattr(result, "role", ""))

    if not getattr(result, "needed_repair", False):
        return
    problems = [p for round_ in result.problems_seen for p in round_]
    for problem in problems:
        if problem.startswith("Forge could not read this answer"):
            # A fault in Forge, survived by asking again -- said plainly, so
            # it is fixed rather than lived with.
            run.record(run.state, "FORGE DEFECT (survived by a retry): "
                       + problem.split(". Write every field")[0],
                       role=result.role)
    # The answers that were refused, as the model wrote them: without them
    # a re-ask's cause can only be guessed at from the problem it was sent.
    refused = []
    for response in list(getattr(result, "responses", ()) or ())[:-1]:
        try:
            refused.append(json.dumps(getattr(response, "structured", None),
                                      default=str)[:6000])
        except Exception:  # noqa: BLE001 - a record is never worth a crash
            continue
    run.record(
        run.state,
        f"{result.role} corrected its own output over "
        f"{result.attempts} attempts",
        role=result.role,
        attempts=result.attempts,
        problems=problems[:12],
        refused_answers=refused[:3],
    )


#: Repair outcomes that say "this attempt was wasted", not "stop trying".
#:
#: A patch that will not apply -- a pointer naming a key that does not exist is
#: the common one -- says nothing about whether the design can be fixed. It was
#: ending the repair loop anyway: observed live, one malformed pointer on the
#: first of two allowed rounds, and the run reported "blocked" with a whole
#: round of budget unspent. The analyst is handed every previous attempt,
#: including the error text, so the next round is a genuinely different attempt
#: rather than a retry, and repeating the same patch is caught as oscillation.
#: A patch that would not apply, or applied and left a document that does
#: not validate: the design is unchanged either way, and the analyst sees
#: why on the next round.
_RETRYABLE_OUTCOMES = ("patch_rejected", "patched document did not validate",
                       "patched document did not compile")


def _why_the_first_design_did_not_build(run: Any) -> str:
    """The compile failures the repairs could not get past, for designing
    the part again."""
    lines = ["The design did not compile, and repairs did not fix it."]
    failure = getattr(run, "failure", None) or {}
    if failure.get("message"):
        lines.append("Last error: " + str(failure["message"])[:600])
    for problem in list(failure.get("problems") or [])[:6]:
        lines.append("- " + str(problem)[:400])
    tried = [r for r in getattr(run, "repairs", ())[
        getattr(run, "repairs_from", 0):]]
    if tried:
        lines.append("What the repairs tried:")
        for attempt in tried[-4:]:
            lines.append(f"- {attempt.strategy[:300] or attempt.diagnosis[:300]}"
                         f" -- {attempt.outcome[:300]}")
    return "\n".join(lines)


def _what_the_first_design_taught(run: Any, report: Any) -> str:
    """What failed, in the checks' own words, and what each repair tried and
    found -- for designing the part again."""
    lines: list[str] = ["Checks the design failed:"]
    for result in report.gate_results:
        if result.status not in (Status.FAIL, Status.BLOCKED) or \
                not result.gate.critical:
            continue
        detail = getattr(result.evidence, "detail", None) or {}
        hint = str(detail.get("hint", "") or "")
        measured = getattr(result.evidence, "result", None)
        lines.append(f"- {result.gate.claim}"
                     + (f" (measured {measured}, required "
                        f"{result.evidence.comparison} "
                        f"{result.evidence.threshold})"
                        if measured is not None else "")
                     + (f": {hint[:500]}" if hint else ""))
    for bend in _what_each_bend_does(
            report, [r for r in report.gate_results
                     if r.status in (Status.FAIL, Status.BLOCKED)]):
        lines.append("- " + bend)
    tried = [r for r in getattr(run, "repairs", ())[
        getattr(run, "repairs_from", 0):] if r.trigger == "gate"]
    if tried:
        lines.append("What the repairs tried:")
        for attempt in tried:
            lines.append(f"- {attempt.strategy[:300] or attempt.diagnosis[:300]}"
                         f" -- {attempt.outcome[:300]}")
    failure = getattr(run, "failure", None) or {}
    if failure.get("message"):
        lines.append("Why they stopped: " + str(failure["message"])[:600])
    facts = (getattr(report, "measurements", None) or {}).get("part") or {}
    if facts.get("envelope_mm"):
        lines.append("The failed part measured "
                     + " x ".join(str(v) for v in facts["envelope_mm"])
                     + " mm overall.")
    return "\n".join(lines)


def _what_each_bend_does(report: Any, failing: Sequence[Any]) -> list[str]:
    """Each bend in the part, in numbers, when an extent check fails on it.

    A bend keeps the plate's length along its middle, so a leg's outside
    does not end where a flat layout says: the L-bracket's base came out
    51.64 mm where its layout gave 50, and the analyst -- told only that the
    extent was wrong -- could not see why. This says where the crease is,
    which way the plate runs through it, and by how much each leg's outside
    differs from its length measured from `position`."""
    import math as _math

    if not any(str(getattr(r.evidence, "detail", {}) or {}).find(
            "bounding_box") >= 0 or r.gate.identifier.startswith(
            ("REQ_BOUNDING_BOX", "REQ_EXTENT", "REQ_FOOTPRINT"))
            for r in failing):
        return []
    try:
        from forge_geom.sdf import Bend
        import numpy as _np
    except Exception:  # noqa: BLE001 - nothing to describe without it
        return []
    found: list[Any] = []
    seen: set[int] = set()
    stack = [getattr(getattr(report, "part", None), "solid", None)]
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, Bend):
            found.append(node)
        for name in getattr(node, "__dataclass_fields__", {}) or {}:
            value = getattr(node, name, None)
            if isinstance(value, (list, tuple)):
                stack.extend(v for v in value if hasattr(
                    v, "__dataclass_fields__"))
            elif hasattr(value, "__dataclass_fields__"):
                stack.append(value)
    said: list[str] = []
    names = "xyz"

    def way(vector: Any) -> str:
        v = _np.asarray(vector, dtype=float)
        i = int(_np.argmax(_np.abs(v)))
        if abs(abs(float(v[i])) - float(_np.linalg.norm(v))) < 1e-6:
            return ("+" if v[i] > 0 else "-") + names[i]
        return "[" + ", ".join(f"{c:g}" for c in v) + "]"

    for bend in found[:3]:
        try:
            e1, e2, _ = bend.frame
            thickness = float(bend.thickness) if bend.thickness else \
                bend.faces_of(bend.solid)[1]
        except Exception:  # noqa: BLE001 - a bend that cannot be read
            continue
        r, t, theta = float(bend.radius), thickness, float(bend.angle)
        arc = (r + t / 2.0) * theta
        reach = (r + t) * _math.tan(theta / 2.0) - arc / 2.0
        where = float(_np.asarray(bend.position) @ e1)
        said.append(
            f"a bend through {_math.degrees(theta):g} degrees toward "
            f"{way(bend.toward)}: the plate runs along {way(e1)} through it "
            f"(`along`), its crease along {way(e2).lstrip('+-')} at "
            f"{way(e1)[-1]} = "
            f"{where:g} mm (`position`), inside radius {r:g} mm in "
            f"{t:g} mm plate. The curve takes {arc:.3f} mm of the plate's "
            "middle, centred on `position`, and each leg's OUTSIDE reaches "
            f"{reach:.3f} mm further than its flat length from `position`: "
            "a leg meant to measure L outside is laid out L - "
            f"{reach:.3f} mm from `position` to its end. If `along` is the "
            "crease's direction instead of the way the plate runs, the "
            "fold is about the wrong line. A part given by its outside "
            "sizes can instead be built as boxes joined by a `union`, each "
            "exactly its size.")
    return said


def _the_analyst_s_edits_kept(
    before: Mapping[str, Any], settled: Mapping[str, Any],
    patches: Sequence[Any],
) -> tuple[Mapping[str, Any], list[str]]:
    """The settled design with each of the analyst's own edits put back
    where Forge's repairs changed it again, and the pointers put back.

    Only edits that name a value in place -- a `replace`, an `add` of a key,
    a `remove` of a key -- are put back: an element inserted into or taken
    out of a list moved everything after it, and is left as settled."""
    from forge_roles.patch import (
        Patch, PatchError, apply_patches, pointer_by_id, pointer_by_index,
        resolve,
    )

    current: Mapping[str, Any] = settled
    kept: list[str] = []
    for raw in patches:
        if not isinstance(raw, Mapping):
            continue
        op = raw.get("op")
        pointer = str(raw.get("pointer", ""))
        last = pointer.rsplit("/", 1)[-1]
        if op not in ("replace", "add", "remove") or last.isdigit() \
                or last == "-":
            continue
        stable = pointer_by_id(before, pointer)
        try:
            meant = Patch.from_dict({**dict(raw), "pointer": stable})
            if op == "remove":
                try:
                    resolve(current, pointer_by_index(current, stable))
                except Exception:  # noqa: BLE001 - already gone, as meant
                    continue
            else:
                try:
                    if resolve(current, pointer_by_index(
                            current, stable)) == raw.get("value"):
                        continue
                except Exception:  # noqa: BLE001 - absent: put it back
                    pass
            current = apply_patches(current, [meant])
        except (PatchError, Exception):  # noqa: BLE001 - this one stays
            continue                      # as settled
        kept.append(pointer)
    return current, kept


def _patches_that_change_nothing(payload: Mapping[str, Any],
                                 patches: Sequence[Any]) -> list[int]:
    """The indices of patches that, applied alone, leave the design as it
    was: a value written back as it already is."""
    from forge_roles.patch import Patch, apply_patches

    idle: list[int] = []
    for index, raw in enumerate(patches):
        if not isinstance(raw, Mapping) or raw.get("op") == "remove":
            continue
        try:
            alone = apply_patches(payload, [Patch.from_dict(raw)])
        except Exception:  # noqa: BLE001 - one that cannot apply alone is
            continue        # not idle; it may need the others
        if _the_same_design(payload, alone):
            idle.append(index)
    return idle


def _measures_the_same(before: Any, after: Any) -> bool:
    """Whether two reports describe a part that measures identically."""
    def facts(report: Any) -> Any:
        part = (getattr(report, "measurements", None) or {}).get("part") or {}
        holes = sorted((str(h.get("feature")), h.get("diameter_mm"),
                        tuple(h.get("centre_mm") or ()), bool(h.get("present")))
                       for h in part.get("holes", []) or [])
        return (tuple(part.get("envelope_mm") or ()), part.get("volume_mm3"),
                tuple(holes))
    one, two = facts(before), facts(after)
    return bool(one[0]) and one == two


def _failing_gates(report: Any) -> set[str]:
    """The gates a report fails or could not measure."""
    return {g.gate.identifier for g in getattr(report, "gate_results", ())
            if g.status.value in ("FAIL", "BLOCKED")}


def _worth_another_round(run: Any) -> bool:
    """Whether the last repair failed in a way another round could survive."""
    if not run.repairs:
        return False
    return run.repairs[-1].outcome.startswith(_RETRYABLE_OUTCOMES)


#: How much of a gate's hint the analyst is shown. Long enough for a hint that
#: places six misplaced holes in numbers, short enough that five failing gates
#: cannot crowd the document slice out of the prompt.
_HINT_LIMIT = 1600


#: What usually moves each kind of measurement, said once per kind, for a
#: failing check whose evidence carries no hint of its own.
_WHAT_MOVES_IT: Mapping[str, str] = {
    "bounding_box": "the part's overall extent along that axis: change the "
                    "solid that reaches furthest out that way, not a feature "
                    "inside it",
    "footprint_side": "a side of the whole part, whichever way it is turned: "
                      "the size of the solid that sets that side",
    "extent_side": "a side of the whole part, whichever way it is turned: the "
                   "size of the solid that sets that side",
    "flat_extent_side": "the part's size laid flat, before any bend: the flat "
                        "solid's own size",
    "parameter": "the value a declared parameter resolves to: set that "
                 "parameter's value, and drive the geometry from it",
    "holes_of_diameter": "how many open holes of that size the finished part "
                         "has: a hole cut from the finished body, through "
                         "material, not filled in by a later feature",
    "openings_of_size": "how many openings right through the part, laid flat, "
                        "are that long and wide",
    "opening_at": "where an opening right through the part is, laid flat: "
                  "move the hole or slot to the place the brief gives",
    "openings_on_circle": "how many openings sit on that circle about the "
                          "part's middle: put the holes at its radius",
    "windows_of_size": "an opening of that size through a wall: the cutter "
                       "has to clear the wall over the whole opening",
    "walls_crossed": "how many walls each of those holes cuts: through one "
                     "wall is `through: first_wall` with `position` inside "
                     "the hollow and `axis` pointing at that wall, no "
                     "`depth`",
    "hole_at": "how many open holes of that size have their axis through "
               "the point the brief gives: move the hole there, in the "
               "part's own coordinates",
    "openings_apart": "how many pairs of those openings are that far apart, "
                      "centre to centre: place the holes that far from each "
                      "other",
    "mass": "the part's mass: its volume, or its material",
    "volume": "the part's volume: the sizes of its solids and cuts",
    "roundness_about_z": "how round the part is about Z: a round part is a "
                         "cylinder or a revolved profile, not a box",
    "roundness": "how round the part is about its own axis: a cylinder or a "
                 "revolved profile, not a box",
    "roundness_every_way": "how nearly a ball the part is: a sphere",
    "wall_thickness": "the container's side walls: the inner space's size "
                      "against the outside's",
    "floor_thickness": "the container's floor: how far the inner space stops "
                       "short of the outside's base",
    "opening_depth": "how far the container is open: the inner space must run "
                     "out through the open face",
    "angle_between": "the angle between the two tagged features' axes: their "
                     "`axis` directions",
    "feature_count": "how many features of that kind (and tag) the design has",
    "safety_factor": "a structural margin: the section that carries the load, "
                     "or the material",
    "bend": "the part's bends, read on its surface: the `bend` features' "
            "angle, place, radius and which way they turn",
    "bent": "the part's bends, read on its surface: the `bend` features' "
            "`along` and `toward`",
}


def _the_difference(result: Any) -> str | None:
    """How far a numeric reading is from what was asked, and which way --
    "12.4 mm over", "2 short" -- or None where that is not a number."""
    measured, threshold = result.evidence.result, result.gate.threshold
    if measured is None or threshold is None:
        return None
    try:
        got = (float(measured.magnitude.lo) + float(measured.magnitude.hi)) / 2
        want_lo = float(threshold.magnitude.lo)
        want_hi = float(threshold.magnitude.hi)
        unit = str(getattr(measured.unit, "symbol", "") or "")
    except Exception:  # noqa: BLE001 - not a plain number; nothing to say
        return None
    comparison = str(result.gate.comparison)
    if comparison in ("at_least", "greater_than"):
        target = want_lo
        if got >= target:
            return None
    elif comparison in ("at_most", "less_than"):
        target = want_hi
        if got <= target:
            return None
    else:
        target = (want_lo + want_hi) / 2
    gap = got - target
    if abs(gap) < 1e-12:
        return None
    return f"{abs(gap):.4g}{(' ' + unit) if unit else ''} " + (
        "over" if gap > 0 else "short")


def _gate_failure(result: Any) -> dict[str, Any]:
    """What the analyst is told about one failed gate, in one shape for
    every kind of check: what was claimed, what was required, what was
    measured, how far off and which way, where on the part the reading was
    taken, and what to change.

    The claim and the two numbers are enough for a threshold miss -- "at most
    120 g, measured 141 g" says what to change. They are useless for a gate
    that measures a *structural* fact: "every through hole is open, at most 0,
    measured 1" tells the analyst nothing it can act on, and it will patch a
    dimension at random. Gates that know why they failed say so in their
    evidence, and that sentence belongs in the prompt; where a gate has no
    sentence of its own, what moves that kind of measurement is said.
    """
    failure: dict[str, Any] = {
        "id": result.gate.identifier,
        "status": result.status.value,
        "claim": result.gate.claim,
        "required": (
            f"{result.gate.comparison} {result.gate.threshold}"
            if result.gate.threshold is not None
            else result.gate.comparison
        ),
        "measured": (
            str(result.evidence.result)
            if result.evidence.result is not None
            else None
        ),
    }
    off = _the_difference(result)
    if off:
        failure["off_by"] = off
    detail = dict(result.evidence.detail or {})
    where = {k: v for k, v in detail.items()
             if k in ("axis", "along", "across", "wanted_at_mm",
                      "nearest_at_mm", "flat_part_mm", "angles_deg",
                      "angles_between_deg", "counted", "every_open_hole_mm",
                      "openings_mm", "notched", "about", "spans")}
    if where:
        text = json.dumps(where, default=str)
        failure["where"] = text[:_HINT_LIMIT]
    hint = detail.get("hint")
    if isinstance(hint, str) and hint.strip():
        failure["how_to_fix"] = hint.strip()[:_HINT_LIMIT]
    else:
        measurement = str(detail.get("measurement", "") or "")
        head = measurement.partition(":")[0]
        for key, words in _WHAT_MOVES_IT.items():
            if head == key or head.startswith(key):
                failure["what_it_measures"] = words
                break
    if result.status.value == "BLOCKED":
        reason = detail.get("blocked_reason") or "; ".join(
            str(x) for x in (result.evidence.limitations or ())[:2])
        if reason:
            failure["why_it_could_not_be_measured"] = str(reason)[:_HINT_LIMIT]
    return failure


def _compile_failure_payload(error: CompileError) -> dict[str, Any]:
    return {
        "kind": "compile_failure",
        "code": error.code,
        "message": error.message,
        "detail": {k: v for k, v in error.detail.items()},
    }


def _anchor(payload: Mapping[str, Any], pointer: str) -> str:
    """Lift ``pointer`` to the nearest enclosing object that carries an ``id``.

    A diagnostic pointer can land arbitrarily deep -- on a vector component, on
    one field of one parameter. Sending the analyst that alone strips the
    context needed to read the mistake; sending the whole document buries it.
    Identified objects are the natural unit: a feature, a parameter, a
    component. Walking up to the first one is structural rather than a guessed
    number of levels, so it behaves the same on documents of any shape.
    """
    tokens = list(parse_pointer(pointer))
    while tokens:
        candidate = "/" + "/".join(tokens)
        try:
            value = resolve(payload, candidate)
        except PointerError:
            tokens.pop()
            continue
        if isinstance(value, Mapping) and "id" in value:
            return candidate
        tokens.pop()
    return "/components/0"


def _component_index(payload: Mapping[str, Any], identifier: Any) -> int:
    components = payload.get("components")
    if isinstance(components, list) and isinstance(identifier, str):
        for index, component in enumerate(components):
            if isinstance(component, Mapping) and component.get("id") == identifier:
                return index
    return 0


def _index_of(entries: Any, identifier: Any) -> int | None:
    if not isinstance(entries, list):
        return None
    for index, entry in enumerate(entries):
        if isinstance(entry, Mapping) and entry.get("id") == identifier:
            return index
    return None


def _pointers_from(error: CompileError, payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Where in the document this compile failure lives.

    The diagnostics already name what broke -- which parameters left their
    bounds, which feature would not build -- so the analyst is given exactly
    those objects. The fallback to the whole component is deliberate and last:
    it is the honest answer when the error names nothing narrower, not a
    default to reach for.
    """
    detail = error.detail
    pointer = detail.get("pointer")
    if isinstance(pointer, str) and pointer.startswith("/"):
        return (_anchor(payload, pointer),)

    index = _component_index(payload, detail.get("component"))
    component = payload.get("components", [{}])
    component = component[index] if isinstance(component, list) and component else {}
    base = f"/components/{index}"

    named = detail.get("parameters")
    if isinstance(named, list) and named:
        pointers = tuple(
            f"{base}/parameters/{position}"
            for position in (
                _index_of(component.get("parameters"), identifier)
                for identifier in named
            )
            if position is not None
        )
        if pointers:
            return pointers

    feature = detail.get("feature")
    if feature is not None:
        position = _index_of(component.get("features"), feature)
        if position is not None:
            return (f"{base}/features/{position}",)

    return (base,)


def _gates_repairs_were_made_for(run: DesignRun) -> set[str]:
    """Every check this run sent the design to a repair round to pass."""
    gates: set[str] = set()
    for event in run.events:
        if event.state is not State.REPAIRING:
            continue
        named = (event.detail or {}).get("gates")
        if isinstance(named, (list, tuple)):
            gates |= {str(g) for g in named}
    return gates


def _absorb_unknowns(requirements: Any, unknowns: Sequence[Any]) -> Any:
    """Turn unresolved unknowns into unapproved high-risk assumptions.

    This is the honest form of "proceed anyway". No value is invented: the
    assumption records that something is unknown, marks it high-risk and
    unapproved, and the release gate refuses to pass while any such assumption
    stands. The design still gets built and measured, which is useful; it simply
    cannot be called ready.
    """
    from forge_roles.library import RequirementSet

    absorbed = list(requirements.assumptions)
    taken = {str(dict(a).get("id", "")) if isinstance(a, Mapping) else
             str(getattr(a, "identifier", "")) for a in absorbed}
    for unknown in unknowns:
        # One id each: the document refuses a second, and the run would end
        # before a design was asked for.
        identifier = f"ASM_UNRESOLVED_{unknown.identifier}"
        while identifier in taken:
            identifier += "_"
        taken.add(identifier)
        absorbed.append(
            {
                "id": identifier,
                "statement": (
                    f"Unresolved at design time: {unknown.question} "
                    "No value was supplied and none was invented."
                ),
                "rationale": unknown.why_it_matters,
                "consequence_if_wrong": (
                    "Any conclusion depending on this is unfounded. "
                    f"It blocks: {', '.join(unknown.blocks) or 'the design as a whole'}."
                ),
                "risk": "high",
                "reversible": False,
                "approved": False,
            }
        )
    return RequirementSet(
        requirements=requirements.requirements,
        assumptions=tuple(absorbed),
        unknowns=requirements.unknowns,
        risk_class=requirements.risk_class,
    )


def _load_case_from(document: Document) -> LoadCase | None:
    """Find a declared load to screen against, if the document states one.

    Looks only at assumptions and requirements that actually carry a force. If
    nothing in the document states a load, no structural screening runs, and the
    report says the structural gates were not tested -- which is correct. An
    orchestrator that supplied a default load here would be doing exactly what
    the whole system is built to prevent.
    """
    force_dimension = Q(1.0, "N").dimension
    length_dimension = Q(1.0, "mm").dimension

    force: Quantity | None = None
    assumption_id = ""
    for assumption in document.assumptions:
        if assumption.value is not None and assumption.value.dimension == force_dimension:
            force = assumption.value
            assumption_id = assumption.identifier
            break
    if force is None:
        for requirement in document.requirements:
            if (
                requirement.threshold is not None
                and requirement.threshold.dimension == force_dimension
            ):
                force = requirement.threshold
                assumption_id = requirement.identifier
                break
    if force is None:
        return None

    arm: Quantity | None = None
    for component in document.components:
        resolution_names = component.parameters.identifiers()
        for candidate in ("lever_arm", "load_arm", "arm", "overhang"):
            if candidate in resolution_names:
                parameter = component.parameters[candidate]
                if parameter.value is not None:
                    arm = parameter.value
                break
        if arm is not None:
            break
    if arm is None or arm.dimension != length_dimension:
        return None

    return LoadCase(
        identifier="declared_load",
        force=force,
        lever_arm=arm,
        description="Taken from the document's own declared load.",
        assumption_id=assumption_id,
    )


__all__ = ["Orchestrator", "OrchestratorConfig"]
