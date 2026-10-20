"""The role framework: a typed job a model does, with validated output.

A role is a narrow, named responsibility with a versioned prompt, a declared
output schema, and a parser that turns the model's structured answer into a
typed value the deterministic layers can use. Roles never return prose.

Two levels of validation, and the distinction matters:

**Transport validation** is the provider's job. The schema is declared as a tool
input schema with the tool choice forced, so what comes back is already a JSON
object of roughly the right shape. A failure here is a provider fault.

**Semantic validation** is :meth:`Role.parse`'s job, and it is where the real
checking happens: that a requirement's threshold has a unit, that a ForgeIR
document actually compiles, that an identifier the model referenced exists. A
failure here is the model being wrong about the domain, which is normal and
expected, and it is handled by **bounded repair** -- the errors are handed back
with the original answer still in the conversation, and the model is asked to
correct them.

Repair is bounded rather than open-ended for a specific reason. A model that has
failed the same validation three times is not one nudge away from success; it has
misunderstood something, and further attempts spend money to produce the same
answer. The attempt budget makes that a reported outcome rather than a loop.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Mapping, Sequence, TypeVar

from forge_models import (
    CancellationToken,
    Message,
    ModelError,
    ModelRequest,
    ModelResponse,
    Provider,
    StopReason,
    Usage,
    assistant,
    user,
)

T = TypeVar("T")



def _of_type(value: Any) -> str:
    return {dict: "an object", list: "a list", str: "a string",
            bool: "true/false", int: "a number", float: "a number",
            type(None): "null"}.get(type(value), type(value).__name__)


def _shaped(value: Any, spec: Any, path: str, problems: list[str]) -> Any:
    """`value` as the schema `spec` says it is, where that can be read off it
    without guessing; each place it cannot is a problem, named by its path.

    Only what no `parse` can be expected to read is a problem: a list of
    objects that is not a list, or one of its items that is not an object.
    Everything else is left for the role, several of which accept more than
    one shape on purpose -- a bare figure for {magnitude, unit}, a flat list
    of requirements where named groups are asked for."""
    import json

    if not isinstance(spec, Mapping):
        return value
    kind = spec.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    if kind is None and "properties" in spec:
        kinds = ["object"]
    if "object" not in kinds and "array" not in kinds:
        return value
    items = spec.get("items")
    of_objects = "array" in kinds and isinstance(items, Mapping) and (
        items.get("type") == "object" or "properties" in items)
    item_of_a_list = path.endswith("]") and "object" in kinds
    if isinstance(value, str) and "string" not in kinds:
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = None
        if isinstance(decoded, (dict, list)):
            value = decoded
    if of_objects and isinstance(value, Mapping):
        value = [value]  # one object where a list of them goes
    if "object" in kinds and isinstance(value, Mapping):
        properties = spec.get("properties") or {}
        if not isinstance(properties, Mapping):
            return value
        out = dict(value)
        for key, item in value.items():
            if key in properties:
                out[key] = _shaped(item, properties[key], f"{path}.{key}"
                                   if path else key, problems)
        return out
    if "array" in kinds and isinstance(value, list):
        return [_shaped(item, items, f"{path}[{index}]", problems)
                for index, item in enumerate(value)]
    if not (of_objects or item_of_a_list):
        return value
    wanted = "a list of objects" if of_objects else "an object"
    fields = ""
    described = items if of_objects else spec
    if isinstance(described, Mapping) and isinstance(
            described.get("properties"), Mapping):
        fields = (" with the fields "
                  + ", ".join(f"`{f}`" for f in list(described["properties"])[:6]))
    shown = json.dumps(value, default=str)
    problems.append(
        f"`{path}` must be {wanted}{fields}; it was {_of_type(value)}: "
        f"{shown[:160]}{'...' if len(shown) > 160 else ''}. Write it as JSON "
        "of that shape, not as text describing it.")
    return value


def answer_in_shape(structured: Any, schema: Mapping[str, Any]) -> Any:
    """The answer with every object and list where the schema puts one.

    A role's `parse` reads the fields it asked for; it should not have to
    defend each one against arriving as something else. It had not: a
    failure analyst's `patches` came back as a list of strings, the first
    `item.get` on one raised AttributeError, and a stepper plate one gate
    from release ended as "internal error -- a defect in Forge". A value
    the schema says is an object or a list, given as JSON text, is read as
    that JSON; one that is still not the right shape is the model's to
    correct, said with its path, on the next attempt -- never a crash."""
    if not isinstance(structured, Mapping) or not isinstance(schema, Mapping):
        return structured
    problems: list[str] = []
    shaped = _shaped(structured, schema, "", problems)
    if problems:
        raise RoleOutputError("the answer is not in the requested shape",
                              problems)
    return shaped


class RoleError(Exception):
    """A role failed to produce usable output."""

    code = "RL1000_ROLE"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail: Mapping[str, Any] = dict(detail)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
        return f"[{self.code}] {self.message}" + (f" ({rendered})" if rendered else "")


class RoleOutputError(RoleError):
    """The output was structurally fine but semantically wrong.

    Raised by :meth:`Role.parse`. Carries a list of human-readable problems,
    each ideally naming a JSON Pointer, which are fed straight back to the model
    as the repair prompt.
    """

    code = "RL1001_OUTPUT"

    def __init__(self, message: str, problems: Sequence[str] = (), **detail: Any):
        super().__init__(message, **detail)
        self.problems = tuple(problems)


def _small_enough_to_keep(answer: Any, limit: int = 400_000) -> Any:
    """The rejected answer, or a note saying why it is not here.

    Written into `run.json`; a runaway answer is replaced by its size rather
    than truncated into invalid JSON. The limit is a whole design's worth:
    at 20 000 characters a designer's rejected document -- the one answer
    worth replaying offline, bought for a dollar and ten minutes -- was
    always dropped, and only its size kept.
    """
    if answer is None:
        return None
    try:
        rendered = json.dumps(answer, default=str)
    except (TypeError, ValueError):
        return {"note": "the answer could not be rendered as JSON"}
    if len(rendered) > limit:
        return {
            "note": f"the answer was {len(rendered)} characters, too long to "
                    "record here",
        }
    return json.loads(rendered)


class RepairExhaustedError(RoleError):
    """The role could not produce valid output within its attempt budget."""

    code = "RL1002_REPAIR_EXHAUSTED"


class RoleInputError(RoleError):
    """What the role was *given* is unusable, so its output cannot be at fault.

    Distinct from :class:`RoleOutputError`, and deliberately not repairable. A
    role that is handed a malformed input can rewrite its answer as many times
    as the budget allows without ever fixing it, and every one of those rounds
    is charged to the wrong stage. Observed live: a material grade written into
    an assumption's numeric `value` by the Requirements Engineer surfaced as
    three failed attempts by the ForgeIR Designer.

    ``stage`` names the role that actually produced the bad input, so the run
    report points at something a person can act on.
    """

    code = "RL1003_INPUT"

    def __init__(
        self, message: str, problems: Sequence[str] = (), *, stage: str = "", **detail: Any
    ):
        super().__init__(message, stage=stage, **detail)
        self.problems = tuple(problems)
        self.stage = stage


@dataclass(frozen=True, slots=True)
class RoleResult(Generic[T]):
    """What a role produced, and what it cost."""

    value: T
    role: str
    prompt_version: str
    attempts: int
    usage: Usage
    problems_seen: tuple[tuple[str, ...], ...] = ()
    responses: tuple[ModelResponse, ...] = ()
    duration_seconds: float = 0.0
    #: The problems that were still outstanding when the attempt budget ran
    #: out, on a result the role chose to keep rather than lose. Empty for
    #: every answer that validated on its own, which is nearly all of them.
    #: Never empty silently: whatever is here is reported in the run.
    salvaged: tuple[str, ...] = ()

    @property
    def needed_repair(self) -> bool:
        return self.attempts > 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "prompt_version": self.prompt_version,
            "attempts": self.attempts,
            "needed_repair": self.needed_repair,
            "usage": self.usage.as_dict(),
            "duration_s": round(self.duration_seconds, 3),
            "problems_seen": [list(round_) for round_ in self.problems_seen],
            "salvaged": list(self.salvaged),
            "calls": [r.as_dict() for r in self.responses],
        }


class Role(ABC, Generic[T]):
    """Base class for a typed engineering role."""

    #: Stable identifier, used in logs, fixtures and provenance.
    name: str = "role"
    #: Bumped whenever the prompt changes in a way that alters behaviour. It is
    #: recorded in provenance, so a result can be traced to the instructions
    #: that produced it.
    prompt_version: str = "1.0.0"
    #: How many total attempts, including the first. Two repairs is the default
    #: because a third rarely succeeds where the first two did not.
    max_attempts: int = 3
    max_output_tokens: int = 8192
    #: How far `max_output_tokens` may grow when an answer is cut off by it.
    #: An answer that stopped because it ran out of room is not an answer: a
    #: brief interpreter at 2048 tokens returned its summary and nothing after
    #: it, three runs in a row, and the run went on with "0 stated facts" as if
    #: the brief had stated none. The orchestrator lowers this to its own cap.
    output_token_ceiling: int = 32768
    temperature: float = 0.0
    #: How much a model that thinks should put into this role's answers:
    #: "low", "medium", "high", or "" for the model's own default. Read
    #: through `effort_for`, which may vary it by the inputs.
    effort: str = ""

    # -- to implement ---------------------------------------------------
    def effort_for(self, **inputs: Any) -> str:
        """The thinking effort this call deserves; the role's own by default."""
        return self.effort

    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def output_schema(self, **inputs: Any) -> Mapping[str, Any]:
        """The schema for this role's answer, for this run.

        Takes the run's inputs because under grammar-constrained
        decoding the schema is not a description of a valid answer, it
        is the set of tokens the model may emit -- and some of what is
        valid depends on the brief. A whole-part `mass` claim needs a
        mass in the brief; without one, the slot is not a thing the
        model should be able to fill.

        Every override may ignore them, and most do.
        """

    @abstractmethod
    def build_messages(self, **inputs: Any) -> tuple[Message, ...]: ...

    @abstractmethod
    def parse(self, structured: Mapping[str, Any], **inputs: Any) -> T:
        """Validate semantically and build the typed value.

        Raise :class:`RoleOutputError` with concrete problems to trigger repair.
        """

    # -- optional hooks -------------------------------------------------
    def salvage(
        self,
        structured: Mapping[str, Any],
        problems: Sequence[str],
        **inputs: Any,
    ) -> T | None:
        """One last look at an answer the attempt budget is about to discard.

        Called only when the loop has decided to give up: the answer was
        rejected, and there will be no further attempt. Returning None -- the
        default, and what every role does unless it says otherwise -- keeps
        the failure exactly as it was.

        This exists because a run that ends with nothing is the worst outcome
        Forge can produce, and it is not always the honest one. A collar was
        refused three times over a single unread parameter, and the answer
        being thrown away contained a complete, compilable part whose real
        faults were geometric and would have been caught, named and reported
        by the gates. Twenty minutes bought a message about a document
        contract instead of a part with its problems written down.

        The bar for overriding this is deliberately high, and it is not "the
        problem was minor". It is that the problem can be resolved by
        recording LESS confidence rather than by changing the design: a claim
        that cannot be checked becomes a claim that is reported unchecked.
        Nothing here may make a rejected answer pass. A role that cannot do
        that for a given problem returns None and the run fails as before.
        """
        return None

    def schema_description(self) -> str:
        """What the tool is *for*, phrased so it cannot be misread.

        A capable model infers this. A small one does not: given a tool named
        after the role, qwen2.5-coder answered the brief interpreter by calling
        `brief_interpreter` and passing it the brief -- reading the tool as a
        worker to delegate to rather than as the envelope for its own answer.
        It is a fair reading of a bad name, so the name and the description both
        say plainly which it is.
        """
        return (
            f"Submit the completed {self.name.replace('_', ' ')} result. The "
            "arguments you pass ARE your answer -- fill in every required "
            "field with your own analysis. Do not pass the input back."
        )

    def repair_preamble(self) -> str:
        return (
            "Your previous answer did not validate. The problems are listed "
            "below, each naming where it occurred. Correct them and return the "
            "complete structure again. Change only what the problems require."
        )

    def _parse_guarded(self, structured: Any,
                       inputs: Mapping[str, Any]) -> T:
        """`parse`, with a fault in Forge's reading of an answer made a
        retry rather than the end of the run.

        Forge's readers of a design are many and each was written for the
        shapes it had seen. A stepper plate's first answer wrote a size as
        a bare list -- valid ForgeIR -- and one reader's `size["vector"]`
        ended the run as "internal error" with the brief, the requirements
        and twenty cents spent. The reader was fixed; this is so the next
        one like it costs a retry. The model is told what Forge tripped on
        and asked to write the answer exactly in the schema's own forms, and
        the traceback is kept with the problem, so the fault is still seen
        and still fixed."""
        try:
            return self.parse(structured, **inputs)
        except (RoleError, KeyboardInterrupt):
            # Raised on purpose: a role saying what is wrong, with whom.
            raise
        except Exception as error:  # noqa: BLE001 - see the docstring
            import traceback

            frames = traceback.extract_tb(error.__traceback__)
            where = "?"
            if frames:
                import re as _re

                last = frames[-1]
                file = _re.split(r"[/\\]", last.filename)[-1]
                where = f"{last.name} ({file}:{last.lineno})"
            raise RoleOutputError(
                "Forge could not read this answer",
                [f"Forge could not read this answer -- {type(error).__name__}: "
                 f"{str(error)[:200]} in {where}. Write every field exactly "
                 "in the schema's own form -- a position or size as "
                 '{"vector": [x, y, z], "unit": "mm"}, a length as '
                 '{"magnitude": n, "unit": "mm"} or {"expression": "...", '
                 '"unit": "mm"}, parameters as an object keyed by name -- '
                 "and answer again in full."],
                forge_defect=traceback.format_exc()[-4000:],
            ) from error

    def _reject_an_echo(
        self, structured: Mapping[str, Any], schema: Mapping[str, Any]
    ) -> None:
        """Catch an answer that shares no field with the schema at all.

        Observed with a small local model: told to submit its interpretation, it
        called the tool with ``{"brief": "<the brief>"}`` -- handing the input
        back rather than answering. The per-field validator then reported
        "`summary` is empty", which is true, unhelpful, and sends the model off
        to fix a field while repeating the same mistake.

        Saying what actually happened costs one comparison and turns three
        wasted attempts into one corrected answer.

        An answer that is merely *unwrapped* is not an echo, and must not be
        caught here. Observed live, twice over: the designer's wrapper is
        ``{rationale, document}``, and a model that returns the document's own
        fields at the top level -- ``{name, description, components}`` -- shares
        nothing with the wrapper and everything with what the wrapper contains.
        ``parse`` knows how to unwrap that; this guard ran first and threw away
        a design that compiled into a watertight solid. So a payload matching
        any nested object's fields is passed through to the role, which is the
        thing that actually understands the shape.
        """
        expected = set(schema.get("properties", {}))
        if not expected or set(structured) & expected:
            return
        for value in schema.get("properties", {}).values():
            if isinstance(value, Mapping) and set(structured) & set(
                value.get("properties", {})
            ):
                return
        raise RoleOutputError(
            "the answer shares no field with the requested structure",
            [
                "None of the fields you returned ("
                + ", ".join(sorted(structured)[:8])
                + ") belong to the requested structure. Its fields are: "
                + ", ".join(sorted(expected))
                + ". The tool is how you return YOUR answer -- it is not a "
                "function that processes the input for you, and the input must "
                "not be passed back."
            ],
        )

    # -- the run loop ---------------------------------------------------
    def run(
        self,
        provider: Provider,
        *,
        cancellation: CancellationToken | None = None,
        **inputs: Any,
    ) -> RoleResult[T]:
        started = time.perf_counter()
        messages = list(self.build_messages(**inputs))
        schema = dict(self.output_schema(**inputs))
        responses: list[ModelResponse] = []
        problems_seen: list[tuple[str, ...]] = []
        answers_seen: list[Any] = []
        total = Usage()

        budget = self.max_output_tokens
        for attempt in range(1, self.max_attempts + 1):
            while True:
                request = ModelRequest(
                    system=self.system_prompt(),
                    messages=tuple(messages),
                    schema=schema,
                    schema_name=self.name,
                    schema_description=self.schema_description(),
                    max_output_tokens=budget,
                    temperature=self.temperature,
                    purpose=self.name,
                    effort=self.effort_for(**inputs),
                )
                try:
                    response = provider.complete(request,
                                                 cancellation=cancellation)
                except ModelError as stopped:
                    # The budget ran out, or the run was cancelled, between
                    # two of this role's answers. What it had already been
                    # told was wrong, and what it had written, are what the
                    # money bought: kept on the error for the run's record.
                    # A designer that spent $2.70 on two refused documents
                    # stopped with nothing on file saying why.
                    if answers_seen:
                        stopped.detail = {
                            **dict(stopped.detail),
                            "role": self.name,
                            "answers_refused": len(answers_seen),
                            "last_problems": list(problems_seen[-1]),
                            "all_problems": [list(p) for p in problems_seen],
                            "refused_answers": [
                                _small_enough_to_keep(a)
                                for a in answers_seen],
                        }
                    raise
                responses.append(response)
                total = total + response.usage
                # Cut off by the length limit: whatever came back is the first
                # part of an answer, and parsing it would take the missing part
                # as never said. Ask again with room for all of it. This is not
                # a fault in the answer, so it does not spend a repair attempt.
                ceiling = max(self.max_output_tokens,
                              int(self.output_token_ceiling))
                if (response.stop_reason is StopReason.MAX_TOKENS
                        and budget < ceiling):
                    budget = min(budget * 2, ceiling)
                    continue
                break

            structured: Any = None
            try:
                if response.stop_reason is StopReason.MAX_TOKENS:
                    # Cut off at the most this role may write: parsed, the
                    # missing end would read as never said -- a document with
                    # half its features, a record with no assumptions.
                    raise RoleOutputError(
                        "the answer was cut off at the output limit",
                        [f"Your answer was cut off at the {budget}-token "
                         "output limit before it was finished. Answer again, "
                         "complete and SHORTER: leave out every description, "
                         "rationale and optional field, and write each value "
                         "once."])
                if response.structured is None:
                    # No structured answer, and not cut off: a transport that
                    # promised one and returned none. Every live adapter
                    # raises for this itself; a replayed fixture or an
                    # adapter that does not is asked again as a repair, where
                    # `require_structured` raised a ValueError no caller
                    # catches and the run ended as an internal error.
                    raise RoleOutputError(
                        "the answer carried no structured content",
                        ["No tool call and no JSON object came back. Answer "
                         "by calling the tool once, with the complete "
                         "structure as its input."])
                structured = response.structured
                self._reject_an_echo(structured, schema)
                structured = answer_in_shape(structured, schema)
                value = self._parse_guarded(structured, inputs)
            except RoleOutputError as error:
                problems_seen.append(error.problems)
                answers_seen.append(structured)
                # A model that has just returned the identical answer twice,
                # having been shown what was wrong with it, will return it a
                # third time. Observed live: three identical documents, 82
                # minutes, one 25-minute attempt of which was spent confirming
                # what the second already knew. Stopping here costs nothing and
                # gives the run's reader the same diagnosis sooner.
                repeating = (
                    len(problems_seen) >= 2
                    and problems_seen[-1] == problems_seen[-2]
                )
                if attempt == self.max_attempts or repeating:
                    # Before the run ends with nothing, ask the role whether
                    # this answer can be kept by recording less confidence in
                    # it. Almost always it cannot, and this returns None.
                    rescued = None
                    if structured is not None:
                        try:
                            rescued = self.salvage(
                                structured, error.problems, **inputs)
                        except Exception:  # noqa: BLE001 - a salvage that
                            # fails is a salvage that did not happen; the
                            # failure below is the one worth reporting.
                            rescued = None
                    if rescued is not None:
                        return RoleResult(
                            value=rescued,
                            role=self.name,
                            prompt_version=self.prompt_version,
                            attempts=attempt,
                            usage=total,
                            problems_seen=tuple(problems_seen),
                            responses=tuple(responses),
                            duration_seconds=time.perf_counter() - started,
                            salvaged=tuple(error.problems),
                        )
                    raise RepairExhaustedError(
                        f"the {self.name} role could not produce valid output "
                        f"in {attempt} attempt(s)"
                        + (
                            "; it returned the same answer twice, so a third "
                            "would have cost time and told us nothing"
                            if repeating
                            else ""
                        ),
                        role=self.name,
                        attempts=attempt,
                        stopped_early=repeating,
                        last_problems=list(error.problems),
                        all_problems=[list(p) for p in problems_seen],
                        # The answer that was rejected, so the next person to
                        # read this run can see what the model actually wrote.
                        # Without it a failure here says only that something
                        # was wrong, and finding out what it was costs another
                        # twenty-five-minute run to reproduce -- which is what
                        # it cost, twice, on the way to this line.
                        rejected_answer=_small_enough_to_keep(structured),
                        # And every answer before it. A failure on the third
                        # attempt is often caused by the first: kept, the
                        # whole exchange can be replayed offline instead of
                        # bought again.
                        earlier_answers=[_small_enough_to_keep(a)
                                         for a in answers_seen[:-1]],
                        hint="repeated identical failures usually mean the "
                        "instructions are ambiguous rather than the model is "
                        "careless; read the problems as feedback on the prompt",
                    ) from error
                # Keep the failed answer in the conversation. The model repairs
                # its own output far more reliably when it can see what it said
                # than when asked to produce a fresh answer to the same question.
                # Cut off before any answer began -- the thinking took the
                # room -- there is nothing of its own to show it.
                messages.append(
                    assistant(json.dumps(response.structured, indent=2)
                              if response.structured is not None else
                              "(cut off at the output limit before the "
                              "answer began)")
                )
                messages.append(user(self._repair_message(error)))
                continue

            return RoleResult(
                value=value,
                role=self.name,
                prompt_version=self.prompt_version,
                attempts=attempt,
                usage=total,
                problems_seen=tuple(problems_seen),
                responses=tuple(responses),
                duration_seconds=time.perf_counter() - started,
            )

        raise RepairExhaustedError(  # pragma: no cover - loop always returns
            f"the {self.name} role exhausted its attempts", role=self.name
        )

    def _repair_message(self, error: RoleOutputError) -> str:
        lines = [self.repair_preamble(), ""]
        for index, problem in enumerate(error.problems, start=1):
            lines.append(f"{index}. {problem}")
        if not error.problems:
            lines.append(f"1. {error.message}")
        return "\n".join(lines)


#: Detail keys that are for machines or for us, not for the model.
#:
#: A deny-list, deliberately, after an allow-list dropped the useful field
#: three separate times: `keys` (which of nine parameters was malformed, and
#: how), `terminals` (which two solids were both unconsumed), `source` (the
#: expression that failed to parse). Each omission cost a repair round that
#: could not possibly succeed, because the model was told something was wrong
#: and not what. A new diagnostic field should reach the model by default; the
#: ones that should not are few, and they are named here.
_NOT_WORTH_SAYING = frozenset(
    {"last_problems", "all_problems", "fingerprint", "cause", "code"}
)

#: Detail values longer than this are truncated. A forty-item list of available
#: names is a hint; a whole document echoed back is noise the model pays for.
_MAX_DETAIL_CHARS = 400


def _shorten(value: Any) -> Any:
    rendered = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(rendered) <= _MAX_DETAIL_CHARS:
        return value
    return rendered[:_MAX_DETAIL_CHARS] + " ...(truncated)"


def problems_from_schema_error(error: Any, *, limit: int = 25) -> list[str]:
    """Render a ForgeIR :class:`SchemaError` (or group) as repair instructions.

    The JSON Pointer is kept at the front of each line deliberately. It is the
    single most useful token in the message: it tells the model exactly which
    node to look at, and it is what makes the difference between "something is
    wrong with your features" and "the third feature's diameter is missing its
    unit".
    """
    from forge_ir import SchemaError, SchemaErrorGroup

    problems: list[str] = []
    errors = (
        list(error.errors) if isinstance(error, SchemaErrorGroup) else [error]
    )
    for item in errors[:limit]:
        if isinstance(item, SchemaError):
            location = item.pointer or "<document root>"
            detail = ""
            if item.detail:
                interesting = {
                    key: _shorten(value)
                    for key, value in item.detail.items()
                    if key not in _NOT_WORTH_SAYING
                }
                if interesting:
                    detail = " " + json.dumps(interesting, default=str)
            problems.append(f"At `{location}`: {item.message}.{detail}")
        else:
            problems.append(str(item))
    if len(errors) > limit:
        problems.append(f"...and {len(errors) - limit} further problems.")
    return problems


__all__ = [
    "Role",
    "RoleResult",
    "RoleError",
    "RoleOutputError",
    "RepairExhaustedError",
    "problems_from_schema_error",
]
