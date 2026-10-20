"""The workflow state machine and its append-only event log.

Every transition is an event, and events are never rewritten. A run that took
four repair attempts records four repair attempts, including the ones that
failed and what was tried. That is what makes a run auditable rather than merely
current -- and it is what stops the tempting move of quietly retrying until
something works and reporting only the success.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from forge_models import Usage


class State(Enum):
    """Where a run is.

    Terminal states are ``COMPLETED``, ``BLOCKED``, ``FAILED`` and ``CANCELLED``.
    ``AWAITING_ANSWERS`` is a *pause*, not a failure: the run stopped because it
    refused to invent something, and it resumes when the answers arrive.
    """

    INGESTED = "ingested"
    INTERPRETING = "interpreting"
    GATHERING_REQUIREMENTS = "gathering_requirements"
    AWAITING_ANSWERS = "awaiting_answers"
    DESIGNING = "designing"
    COMPILING = "compiling"
    REPAIRING = "repairing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            State.COMPLETED,
            State.BLOCKED,
            State.FAILED,
            State.CANCELLED,
            State.AWAITING_ANSWERS,
        )

    @property
    def is_success(self) -> bool:
        return self is State.COMPLETED


@dataclass(frozen=True, slots=True)
class RunEvent:
    """One thing that happened."""

    sequence: int
    state: State
    summary: str
    timestamp: float = field(default_factory=time.time)
    detail: Mapping[str, Any] = field(default_factory=dict)
    usage: Usage | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "seq": self.sequence,
            "state": self.state.value,
            "summary": self.summary,
            "at": self.timestamp,
        }
        if self.detail:
            payload["detail"] = dict(self.detail)
        if self.usage is not None:
            payload["usage"] = self.usage.as_dict()
        return payload

    def render(self) -> str:
        return f"[{self.sequence:>3}] {self.state.value:<22} {self.summary}"


@dataclass(frozen=True, slots=True)
class RepairAttempt:
    """One pass through the repair loop, successful or not."""

    attempt: int
    trigger: str
    diagnosis: str
    strategy: str
    patches: tuple[Mapping[str, Any], ...]
    outcome: str
    abandoned: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "trigger": self.trigger,
            "diagnosis": self.diagnosis,
            "strategy": self.strategy,
            "outcome": self.outcome,
            "abandoned": self.abandoned,
            "patches": [dict(p) for p in self.patches],
        }


class DesignRun:
    """The complete record of one prompt-to-part attempt."""

    __slots__ = (
        "brief",
        "_events",
        "_state",
        "intent",
        "requirements",
        "questions",
        "answers",
        "draft",
        "document_payload",
        "report",
        "repairs",
        "usage",
        "provider_info",
        "started_at",
        "finished_at",
        "failure",
        "listener",
        "pictures",
        "repairs_from",
    )

    def __init__(self, brief: str, *, answers: Mapping[str, str] | None = None) -> None:
        self.brief = brief
        self._events: list[RunEvent] = []
        self._state = State.INGESTED
        self.intent: Any = None
        self.requirements: Any = None
        self.questions: tuple[Any, ...] = ()
        self.answers: dict[str, str] = dict(answers or {})
        self.draft: Any = None
        #: Where the repairs to the design now being repaired begin: after a
        #: second design, the analyst is shown its own edits to it, not the
        #: edits to a document that is gone.
        self.repairs_from = 0
        self.document_payload: Mapping[str, Any] | None = None
        self.report: Any = None
        self.repairs: list[RepairAttempt] = []
        self.usage = Usage()
        self.provider_info: Mapping[str, Any] = {}
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.failure: Mapping[str, Any] | None = None
        #: Told of each event as it happens -- `listener(event)` -- by
        #: whoever is watching the run: the live page in the run's folder.
        #: Never allowed to stop the run.
        self.listener: Any = None
        #: Each picture drawn of the part, newest last: (caption, png bytes).
        self.pictures: list[tuple[str, bytes]] = []
        self.record(State.INGESTED, "brief received", brief_chars=len(brief))

    # -- event log ------------------------------------------------------
    def record(
        self,
        state: State,
        summary: str,
        *,
        usage: Usage | None = None,
        **detail: Any,
    ) -> RunEvent:
        self._state = state
        event = RunEvent(
            sequence=len(self._events),
            state=state,
            summary=summary,
            detail=detail,
            usage=usage,
        )
        self._events.append(event)
        if usage is not None:
            self.usage = self.usage + usage
        if state.is_terminal:
            self.finished_at = time.time()
        listener = getattr(self, "listener", None)
        if listener is not None:
            try:
                listener("event", event)
            except Exception:  # noqa: BLE001 - a watcher never stops a run
                pass
        return event

    @property
    def state(self) -> State:
        return self._state

    @property
    def events(self) -> tuple[RunEvent, ...]:
        return tuple(self._events)

    def __iter__(self) -> Iterator[RunEvent]:
        return iter(self._events)

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    @property
    def needs_answers(self) -> bool:
        return self._state is State.AWAITING_ANSWERS

    @property
    def succeeded(self) -> bool:
        return self._state is State.COMPLETED

    # -- serialisation ---------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "brief": self.brief,
            "state": self._state.value,
            "duration_s": round(self.duration_seconds, 3),
            "usage": self.usage.as_dict(),
            "provider": dict(self.provider_info),
            "events": [event.as_dict() for event in self._events],
            "repairs": [repair.as_dict() for repair in self.repairs],
        }
        if self.intent is not None:
            payload["intent"] = self.intent.as_dict()
        if self.requirements is not None:
            payload["requirements"] = self.requirements.as_dict()
        if self.questions:
            payload["questions"] = [q.as_dict() for q in self.questions]
        if self.answers:
            payload["answers"] = dict(self.answers)
        if self.document_payload is not None:
            payload["document"] = dict(self.document_payload)
        if self.report is not None:
            payload["verification"] = self.report.as_dict()
        if self.failure is not None:
            payload["failure"] = dict(self.failure)
        return payload

    def render(self, *, verbose: bool = False) -> str:
        lines: list[str] = []
        if verbose:
            lines.extend(event.render() for event in self._events)
            lines.append("")

        lines.append(f"State     : {self._state.value}")
        lines.append(f"Elapsed   : {self.duration_seconds:.1f} s")
        usage = self.usage.as_dict()
        cost = usage.get("estimated_cost_usd")
        spend = f", ~${cost:.4f} estimated" if cost is not None else ""
        lines.append(
            f"Model use : {usage['total_tokens']} tokens"
            f" ({usage['input_tokens']} in, {usage['output_tokens']} out){spend}"
        )
        made = [r for r in self.repairs if r.trigger != "last_look"]
        looked = len(self.repairs) - len(made)
        if made or looked:
            lines.append(f"Repairs   : {len(made)}"
                         + (" (and a last look at the part against the brief)"
                            if looked else ""))

        if self.questions:
            lines.append("")
            lines.append("Before this can be designed, these need answering:")
            for question in self.questions:
                lines.append(f"  - [{question.identifier}] {question.question}")
                if question.why:
                    lines.append(f"      why: {question.why}")
                if question.options:
                    lines.append(f"      e.g. {', '.join(question.options)}")

        if self.report is not None:
            lines.append("")
            lines.append(self.report.render())

        if self.failure is not None:
            lines.append("")
            lines.append(f"Failed: {self.failure.get('message', '')}")
            for problem in self.failure.get("problems", [])[:10]:
                lines.append(f"  - {problem}")
            lines.extend(_render_detail(self.failure.get("detail", {})))

        return "\n".join(lines)


#: Keys whose value is machine-facing and helps nobody reading a terminal.
_NOISY_DETAIL = frozenset({"last_problems", "all_problems", "fingerprint",
                           "rejected_answer", "earlier_answers",
                           "refused_answers"})


def _render_detail(detail: Mapping[str, Any]) -> list[str]:
    """Show what the error actually knows, not just its headline.

    Every provider error in Forge carries its diagnosis in ``detail`` -- the
    refused URL and the reason, the measured token rate behind a timeout, the
    flag to change. None of it was printed. "could not reach the endpoint" was
    the whole of what a user saw, while `reason='[WinError 10061] connection
    refused'` sat in the run file unread. The care that goes into these messages
    is wasted if the terminal shows only the first line of them.
    """
    if not detail:
        return []
    hint = detail.get("hint")
    body = [
        f"  {key}: {value}"
        for key, value in sorted(detail.items())
        if key != "hint" and key not in _NOISY_DETAIL and value not in (None, "", [])
    ]
    lines = list(body)
    if detail.get("rejected_answer") not in (None, "", []):
        # Pages of JSON in a terminal bury the diagnosis above them; the
        # answers are kept whole in run.json, where they can be replayed.
        kept = 1 + len([a for a in detail.get("earlier_answers") or []
                        if a is not None])
        lines.append(f"  model answers: {kept} kept in run.json "
                     "(failure.detail.rejected_answer, earlier_answers)")
    elif detail.get("refused_answers"):
        lines.append(f"  model answers: {len(detail['refused_answers'])} "
                     "refused answer(s) kept in run.json "
                     "(failure.detail.refused_answers)")
    if hint:
        # Last and unindented, because it is the sentence that says what to do.
        if body:
            lines.append("")
        lines.append(f"  -> {hint}")
    return lines


__all__ = ["State", "RunEvent", "RepairAttempt", "DesignRun"]
