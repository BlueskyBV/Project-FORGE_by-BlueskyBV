"""The spec writer: a brief in, a checked draft of its part spec out (V2, stage 1).

The model reads the guide (:func:`forge_spec.guide.instructions`) and the
numbered brief, and answers with a draft through the tool whose input schema
is :func:`forge_spec.guide.draft_schema`. The draft is read and checked in
full against the brief (:func:`forge_spec.checks.check_draft`).

Who fixes what:

- **A fault** is the writer's own mistake: a misquoted number, a citation to
  the wrong words, an item placed where it doesn't fit because of a value it
  assumed. It goes back to the writer, with its draft kept in the
  conversation, for a bounded number of redrafts (the role framework's
  repair loop, :class:`forge_roles.base.Role`).
- **A question or a CAN'T** is not the writer's to settle: the brief is
  unclear, contradicts itself, or asks for something that can't be made. It
  comes out in the report, for the person.

The writer sees the person's answers and notes only as sentences added
after the brief, and never the confirmation; it decides nothing a check
can't hold it to. Before its answer is read, the role framework reads a
list or an object given as JSON text, or a lone object where a list goes,
as what the schema asks for (:func:`forge_roles.base.answer_in_shape`): the
same content, so nothing the checks hold changes. The model and its key are the provider's
business (:mod:`forge_models`): nothing here reads a secret.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from forge_models import CancellationToken, Message, Provider, user
from forge_spec import NumberedBrief, number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.guide import GUIDE_VERSION, brief_message, draft_schema, instructions
from forge_spec.versions import CURRENT

from .base import Role, RoleOutputError, RoleResult, answer_in_shape

__all__ = ["SpecWriter", "as_drafted", "read_answer", "write_spec"]


class SpecWriter(Role[SpecReport]):
    """Drafts a part spec from a numbered brief; redrafts on its own faults."""

    name = "spec_writer"
    #: An automatic run's writer is told the stricter rules: "v2-guide-3-auto".
    prompt_version = f"v2-guide-{GUIDE_VERSION}"
    #: A first draft and up to three redrafts. A fault the writer can't clear
    #: in three tries is a misunderstanding, reported, not a loop.
    max_attempts = 4
    max_output_tokens = 16384
    output_token_ceiling = 65536
    #: Reading a brief right is the whole job: let the model work it out.
    effort = "high"

    def __init__(self, *, strict: bool = False, second: bool = False) -> None:
        #: ``--auto``: no person will confirm, so the stricter checks apply,
        #: and the writer is told them.
        self.strict = strict
        #: The second, independent draft: the same guide, the brief read the
        #: other way round (:func:`forge_spec.guide.brief_message`).
        self.second = second
        self.prompt_version = (
            f"v2-guide-{GUIDE_VERSION}"
            + ("-auto" if strict else "")
            + ("-second" if second else "")
        )

    def system_prompt(self) -> str:
        return instructions(strict=self.strict)

    def output_schema(self, **inputs: Any) -> Mapping[str, Any]:
        return draft_schema()

    def build_messages(self, **inputs: Any) -> tuple[Message, ...]:
        return (user(brief_message(_brief(inputs), second=self.second)),)

    def parse(self, structured: Mapping[str, Any], **inputs: Any) -> SpecReport:
        report = check_draft(_brief(inputs), structured, strict=self.strict)
        faults = report.of_kind("fault")
        if faults:
            problems = [f"{p.at or '(the spec)'}: {p.message}" for p in faults]
            problems += [f"{n.at or '(the spec)'}: read as written, but say it this way: {n.message}"
                         for n in report.notes]  # fmt: skip
            raise RoleOutputError(
                f"the checks found {len(faults)} fault(s) in the draft", problems
            )
        return report

    def received(self, structured: Any, schema: Mapping[str, Any]) -> Any:
        return as_drafted(structured, schema)

    def schema_description(self) -> str:
        return (
            "Submit the part spec you drafted from the brief. The arguments you pass ARE the "
            "spec: every item with its fields, every value with where it came from. Do not "
            "pass the brief back."
        )

    def repair_preamble(self) -> str:
        return (
            "The checks sent your spec back. Each problem below names where it is. Fix each "
            "one, keep everything else as it was, and submit the whole corrected spec."
        )


_A_FIGURE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def read_answer(answer: Any) -> Any:
    """A recorded answer read as the writer read it when it was drafted.

    A run's ``answer.json`` holds what the transport handed over; replayed,
    it goes through the same readings the live writer's did before its
    checks (:func:`as_drafted`, then the role framework's
    :func:`forge_roles.base.answer_in_shape`), or a replay would refuse a
    draft its own run accepted."""
    schema = draft_schema()
    drafted = as_drafted(answer, schema)
    try:
        return answer_in_shape(drafted, schema)
    except RoleOutputError:  # read as it was: the checks say what is wrong with it
        return drafted


def as_drafted(answer: Any, schema: Mapping[str, Any] | None = None) -> Any:
    """A draft as the writer wrote it, from what the transport handed over.

    The same content in another form, so nothing a check holds changes. Each
    was observed live, on a blind set's drafts:

    - **A text the schema fixes, given as the number it reads as.** Every
      draft's ``"schema_version": "1.9"`` arrived as the number 1.9 and was
      refused; told so, the writer wrote it the same way again, and all 30
      briefs gave up. The schema names the one text it may be: 1.9 is
      "1.9", and 1.1 is "1.10" where "1.10" is the text it names. A version
      the schema doesn't name, a record's of an earlier minor version, is
      the earlier version it reads as (1.9 is "1.9" once the schema names
      "1.10"), and the later of two it reads as (1.1 is "1.10" once the
      schema names "1.11": every corpus and blind-set record drafted at 1.10
      arrived as 1.1). Where the schema itself names two it reads as, it is
      left as given.
    - **The whole draft under a lone wrapper the schema doesn't have**:
      ``{"spec": {"schema_version": ..., "items": [...]}}``. A wrapper whose
      one field is the schema's own is left alone.
    - **Items given as JSON text**: one item, or a list of them, as a string.
    """
    schema = draft_schema() if schema is None else schema
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return answer
    answer = _unwrapped(answer, properties)
    if not isinstance(answer, Mapping):
        return answer
    out = dict(answer)
    for name, value in answer.items():
        spec = properties.get(name)
        if isinstance(spec, Mapping) and _a_number(value):
            same = [text for text in _texts_of(spec) if _reads_as(text, value)]
            if not same and name == "schema_version":
                # A record's figure that reads as two versions (1.1: "1.1" or "1.10") is the later one: a minor
                # version only adds, so the later reads every draft the earlier does, and as it did.
                same = [text for text in _versions() if _reads_as(text, value)][-1:]
            if len(same) == 1:
                out[name] = same[0]
    items = out.get("items")
    if isinstance(items, str):
        items = _decoded(items)
    if isinstance(items, Mapping):
        items = [items]  # one item where the list of them goes
    if isinstance(items, list):
        spliced: list[Any] = []
        for item in items:
            decoded = _decoded(item) if isinstance(item, str) else item
            if isinstance(decoded, list):
                spliced.extend(decoded)
            else:
                spliced.append(decoded)
        out["items"] = spliced
    elif items is not None:
        out["items"] = items
    return out


def _versions() -> list[str]:
    """Every version of the current major a draft may be written in, in order: "1.0" to "1.11"."""
    major, minor = CURRENT
    return [f"{major}.{m}" for m in range(minor + 1)]


def _unwrapped(answer: Any, properties: Mapping[str, Any]) -> Any:
    if not isinstance(answer, Mapping) or len(answer) != 1:
        return answer
    ((name, inner),) = answer.items()
    if name in properties:
        return answer
    inner = _decoded(inner) if isinstance(inner, str) else inner
    if isinstance(inner, Mapping) and set(inner) & set(properties):
        return inner
    return answer


def _decoded(text: str) -> Any:
    """JSON text read as what it holds, where it holds an object or a list."""
    try:
        decoded = json.loads(text)
    except ValueError:
        return text
    return decoded if isinstance(decoded, (dict, list)) else text


def _a_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _texts_of(spec: Mapping[str, Any]) -> list[str]:
    """The texts a schema allows and nothing else: its const, or its enum."""
    if isinstance(spec.get("const"), str):
        return [spec["const"]]
    named = spec.get("enum")
    return [text for text in named if isinstance(text, str)] if isinstance(named, list) else []


def _reads_as(text: str, number: int | float) -> bool:
    """Whether a text is a figure, and that figure is the number."""
    return _A_FIGURE.fullmatch(text) is not None and float(text) == float(number)


def _brief(inputs: Mapping[str, Any]) -> NumberedBrief:
    brief = inputs.get("brief")
    if not isinstance(brief, NumberedBrief):
        raise TypeError("the spec writer is given a NumberedBrief as brief=")
    return brief


def write_spec(
    provider: Provider,
    brief: str | NumberedBrief,
    *,
    strict: bool = False,
    second: bool = False,
    cancellation: CancellationToken | None = None,
) -> RoleResult[SpecReport]:
    """Draft and check the spec of a brief: the report, and what it cost.

    ``second`` drafts it as the second, independent reading.

    Raises :class:`forge_roles.base.RepairExhaustedError` when the writer
    can't clear its own faults; the error carries every draft it refused.
    """
    numbered = brief if isinstance(brief, NumberedBrief) else number_words(brief)
    return SpecWriter(strict=strict, second=second).run(
        provider, cancellation=cancellation, brief=numbered
    )
