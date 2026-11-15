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

from collections.abc import Mapping
from typing import Any

from forge_models import CancellationToken, Message, Provider, user
from forge_spec import NumberedBrief, number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.guide import GUIDE_VERSION, brief_message, draft_schema, instructions

from .base import Role, RoleOutputError, RoleResult

__all__ = ["SpecWriter", "write_spec"]


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
