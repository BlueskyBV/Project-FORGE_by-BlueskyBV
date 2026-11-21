"""``forge spec``: a brief in, a part spec the person confirms out (V2, stage 1).

1. Forge numbers the brief, and the spec writer drafts its spec
   (:mod:`forge_roles.spec_writer`); the writer's own faults go back to it.
2. The person reads the spec in fixed wording, then answers one round of
   questions and assumptions, each by choosing an option. Code applies the
   answers (:mod:`forge_spec.questions`); a note for the writer asks for a
   redraft instead, and after a redraft every assumption is asked afresh.
3. When nothing is left to settle, the person confirms by typing back a code
   Forge shows only in its own window (plan, rule R12): the terminal it runs
   in, opened by name (:class:`ControllingTerminal`), never standard input
   and output. A program that runs ``forge spec`` with its input and output
   piped reads and answers everything else, but never sees the code, and
   the person then sees the spec again in that window before confirming.
   A program that runs Forge inside a pseudo-terminal of its own does hold
   the terminal, and no software can tell one from a person's: it is told
   apart only by a system notification, planned with the MCP server
   (stage 9).
4. The confirmed spec is locked (:func:`forge_spec.lock.lock`) and written:
   the brief with the person's answers, the spec and its digest.

With ``--auto`` no person takes part: the stricter checks apply, nothing is
asked, and a draft with nothing left to settle is locked as confirmed by
"draft" only, which can never be VERIFIED. One with questions or
assumptions stops, and writes them: each is for a person.

Exit codes: 0 locked; 1 refused (the writer couldn't clear its faults, or
the part can't be made); 2 the person stopped, or an error; 3 questions an
automatic run can't answer.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO

from forge_models import (
    Budget,
    CancellationToken,
    ModelError,
    ModelRequest,
    Provider,
    Usage,
)
from forge_roles.base import RepairExhaustedError, RoleError, RoleResult
from forge_roles.spec_writer import write_spec
from forge_spec import NumberedBrief, number_words
from forge_spec.checks import SpecProblem, SpecReport, check_draft
from forge_spec.compare import Difference, differences
from forge_spec.ends import ThroughNext, end_of
from forge_spec.lock import ConfirmedSpec, lock
from forge_spec.questions import (
    Answer,
    AnswerError,
    EditKind,
    Question,
    apply_answers,
    questions,
)
from forge_spec.render import render
from forge_spec.wire import to_wire

from .design import _slug, build_provider
from .seal import Sealer, SealError
from .spec_page import write_spec_page

__all__ = [
    "ControllingTerminal",
    "Outcome",
    "Private",
    "add_model_flags",
    "add_spec_parser",
    "command_spec",
    "load_answers",
    "person_code",
    "run_spec",
    "share_budget",
]

EXIT_LOCKED = 0
EXIT_REFUSED = 1
EXIT_STOPPED = 2
EXIT_QUESTIONS = 3

Status = Literal["confirmed", "draft", "questions", "refused", "stopped"]
TwoDrafts = Literal["always", "never", "auto"]
#: ``--drafts`` as typed, and what it asks of a run.
_DRAFTS: dict[str, TwoDrafts] = {"1": "never", "2": "always", "auto": "auto"}
Ask = Callable[[str], str]
Say = Callable[[str], None]

#: A code is six of these: no 0/O or 1/I/L, so it reads back unambiguously.
_CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
#: What may separate a code's letters as typed: spaces and any kind of dash.
_CODE_SEPARATORS = re.compile(r"[\s\-\u2010-\u2015\u2212]")


def person_code() -> str:
    """A fresh confirmation code, from a cryptographic source: "K7Q-4M2"."""
    letters = "".join(secrets.choice(_CODE_LETTERS) for _ in range(6))
    return f"{letters[:3]}-{letters[3:]}"


def _same_code(typed: str, code: str) -> bool:
    """Whether the person typed the code: compared as bytes, so any text typed is only a wrong code."""
    return secrets.compare_digest(
        _CODE_SEPARATORS.sub("", typed).upper().encode("utf-8"),
        code.replace("-", "").encode("utf-8"),
    )


class Private(Protocol):
    """Forge's own window: what is shown here only the person at it reads, and only they type into it."""

    def show(self, text: str) -> None: ...

    def read(self, prompt: str) -> str: ...


class ControllingTerminal:
    """The terminal Forge runs in, opened by name: ``/dev/tty``, or the console on Windows.

    Never standard input and output, which the program that started Forge
    may hold: what is written here goes to the person's screen, and what is
    read comes from their keyboard.
    """

    def __init__(self, reader: TextIO, writer: TextIO) -> None:
        self._reader = reader
        self._writer = writer

    @classmethod
    def open(cls) -> ControllingTerminal | None:
        """The terminal, or None when Forge runs without one (from a service, or detached)."""
        names = ("CONIN$", "CONOUT$") if os.name == "nt" else ("/dev/tty", "/dev/tty")
        try:
            reader = open(names[0], encoding="utf-8", errors="replace")  # noqa: SIM115 - closed by close()
        except OSError:
            return None
        try:
            writer = open(names[1], "w", encoding="utf-8", errors="replace")  # noqa: SIM115 - closed by close()
        except OSError:
            reader.close()
            return None
        return cls(reader, writer)

    def show(self, text: str) -> None:
        try:
            self._writer.write(text + "\n")
            self._writer.flush()
        except OSError as error:  # the terminal hung up
            raise EOFError("the terminal closed") from error

    def read(self, prompt: str) -> str:
        try:
            self._writer.write(prompt)
            self._writer.flush()
            line = self._reader.readline()
        except OSError as error:  # the terminal hung up
            raise EOFError("the terminal closed") from error
        if not line:
            raise EOFError("the terminal closed")
        return line.rstrip("\r\n")

    def close(self) -> None:
        self._reader.close()
        self._writer.close()


@dataclass
class Outcome:
    """How a spec run ended, and what it left."""

    status: Status
    brief: NumberedBrief
    report: SpecReport | None = None
    confirmed: ConfirmedSpec | None = None
    rounds: int = 0
    message: str = ""


class StoppedError(Exception):
    """The person stopped the run."""


# ----------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------
def run_spec(brief: str, provider: Provider, *, ask: Ask, say: Say, private: Private | None,
             strict: bool = False, out: Path | None = None, answers: Sequence[Answer] = (),
             max_drafts: int = 4, code: Callable[[], str] = person_code, echo: bool = False,
             two_drafts: TwoDrafts = "auto", second: Provider | None = None,
             sealer: Sealer | None = None) -> Outcome:  # fmt: skip
    """Draft, ask, apply, confirm and lock the spec of a brief.

    ``ask`` and ``say`` are the run's input and output (``input`` and
    ``print``). ``private`` is Forge's own window, where the confirmation
    code is shown and typed back (rule R12); with None nobody can confirm,
    and a run that gets that far stops. ``answers`` answer questions of the
    first round without asking (for a scripted run): each must name the
    question it was written for, and every question they don't answer is
    asked. ``out`` is where every draft, round and answer is written.
    ``echo`` shows the spec in Forge's own window too, before the code: when
    the run's output is piped, what ``say`` shows may never reach the person.

    ``two_drafts`` says when the brief is drafted a second time, on its own,
    to be compared with the first (:mod:`forge_spec.compare`): "always",
    "never", or "auto", when the first has assumptions, the brief is long,
    or no person will confirm (plan, 4.2). ``second`` drafts it, when another
    model should; where the two differ, the person is asked. Only the brief
    as the person wrote it is drafted twice: a redraft after a note is not.

    ``sealer`` seals a person's confirmation with this installation's key
    (:mod:`forge_cli.seal`; docs/V2-stage4.md, 9.7), so ``forge build`` can
    tell it was made in Forge's own window; without one it is written
    unsealed, and builds as a draft.
    """
    numbered = number_words(brief)
    report: SpecReport | None = None
    preset = list(answers)
    if (
        second is not None
        and second is not provider
        and second.budget is not provider.budget
    ):
        share_budget(provider, second)  # the run's limits hold for both drafts together
    # The assumptions the person has seen and kept since the last draft: not
    # asked again until the writer drafts afresh.
    kept: set[tuple[str, str]] = set()
    # Where a second draft read the brief otherwise: asked until answered.
    pending: tuple[Difference, ...] = ()
    # Why the second draft can't vouch for the first, if it can't: an
    # automatic run stops on it.
    doubt = ""
    drafts = rounds = 0
    try:
        while True:
            if report is None:
                if drafts == max_drafts:
                    return Outcome("stopped", numbered, rounds=rounds,
                                   message=f"{drafts} drafts and still not settled")  # fmt: skip
                drafts += 1
                say(f"\nDrafting the spec (draft {drafts})...")
                # The second draft runs beside the first when it is wanted
                # whatever the first holds, and has a provider of its own.
                together = (drafts == 1 and second is not None and second is not provider
                            and _wants_second_anyway(numbered, strict, two_drafts))  # fmt: skip
                beside = (
                    _Beside(second, numbered, strict) if together and second else None
                )
                try:
                    try:
                        result = write_spec(provider, numbered, strict=strict)
                    except RepairExhaustedError as error:
                        _write(out, f"draft-{drafts}", refused=error.as_dict())
                        problems = error.detail.get("last_problems", [])
                        return Outcome("refused", numbered, rounds=rounds, message="the writer couldn't clear its faults:\n"
                                       + "\n".join(f"  - {p}" for p in problems))  # fmt: skip
                    report = result.value
                    kept = set()
                    _write(out, f"draft-{drafts}", calls=result.as_dict())
                    if _ending(report):
                        pass  # the run ends below; a second draft has nothing to add
                    elif beside is not None:
                        pending, doubt = _compared(beside.result(), report, out, say)
                    elif drafts == 1 and _wants_second(
                        report, numbered, strict, two_drafts
                    ):
                        say(
                            "Drafting it a second time, on its own, to compare the two..."
                        )
                        made = _draft_second(second or provider, numbered, strict)
                        pending, doubt = _compared(made, report, out, say)
                finally:
                    if beside is not None:
                        beside.drop()  # done with, or not wanted: it makes no further call
            assert report.spec is not None
            report = _resolved(numbered, report, strict)
            assert report.spec is not None
            rounds += 1
            shown = render(report, numbered).text()
            _write(out, f"round-{rounds}", brief=numbered.text, draft=to_wire(report.spec), spec=shown,
                   problems=[asdict(p) for p in report.problems])  # fmt: skip
            say("\n" + shown)
            ending = _ending(report)
            if ending:
                return Outcome("refused", numbered, report, rounds=rounds,
                               message="\n".join(f"{p.kind.upper()}: {p.message}" for p in ending))  # fmt: skip
            round_ = tuple(
                q
                for q in questions(report, pending)
                if not (q.kind == "assumption" and (q.at, q.text) in kept)
            )
            if not round_ and not (strict and doubt):
                # Nothing left to settle: built once, before it is confirmed or locked, to see it holds together.
                held = _held_together(numbered, report, strict, say)
                if held is not report:
                    _write(out, f"round-{rounds}", problems=[asdict(p) for p in held.problems])
                    if out is not None:
                        write_spec_page(out, held, numbered, status=f"Draft {drafts}, round {rounds}: can't be made")
                    return Outcome("refused", numbered, held, rounds=rounds,
                                   message="\n".join(f"{p.kind.upper()}: {p.message}" for p in _ending(held)))  # fmt: skip
            if out is not None:
                status = f"Draft {drafts}, round {rounds}: " + (
                    f"{len(round_)} to settle" if round_ else "ready to confirm"
                )
                write_spec_page(out, report, numbered, status=status, round_=round_)
            if strict:
                # Nobody confirms an automatic run: every question and every
                # assumption is for a person, so it stops on any (plan, 4.2),
                # and on a second draft that can't vouch for the first.
                if round_ or doubt:
                    if round_:
                        _write(
                            out,
                            f"round-{rounds}",
                            questions=[asdict(q) for q in round_],
                        )
                    why = ([f"{len(round_)} question(s) and assumption(s) an automatic run can't settle"]
                           if round_ else [])  # fmt: skip
                    if doubt:
                        why.append(f"{doubt}: an automatic run can't settle that")
                    return Outcome(
                        "questions",
                        numbered,
                        report,
                        rounds=rounds,
                        message="; ".join(why),
                    )
                confirmed = lock(report, numbered, by="draft", strict=True)
                _write_confirmed(out, confirmed)
                return Outcome("draft", numbered, report, confirmed, rounds,
                               "locked as a draft: no person confirmed it")  # fmt: skip
            if not round_:
                return _confirm(
                    report, numbered, private, say, out, rounds, code, echo, sealer
                )
            draft = to_wire(report.spec)
            try:
                given, preset = (
                    _answers_for(numbered, draft, round_, preset, ask, say),
                    [],
                )
                answered = apply_answers(numbered, draft, round_, given)
            except AnswerError as error:
                preset = []
                say(f"That answer doesn't fit: {error}. Asking again.")
                continue
            _write(out, f"round-{rounds}", answers=[asdict(a) for a in given])
            pending = ()  # answered: the person settled where the drafts differ
            answered_ids = {a.question for a in given}
            kept |= {
                (q.at, q.text)
                for q in round_
                if q.kind == "assumption" and q.id not in answered_ids
            }
            numbered = answered.brief
            if answered.notes:
                report = None  # the writer drafts again, from the brief with the person's notes
                continue
            report = check_draft(numbered, answered.draft, strict=strict)
            if report.needs_redraft:
                report = None  # an answer left the draft at odds with itself: the writer follows the answers
    except (StoppedError, EOFError, KeyboardInterrupt):
        return Outcome(
            "stopped", numbered, report, rounds=rounds, message="stopped by the person"
        )
    finally:
        _write_spent(out, provider)


def _resolved(numbered: NumberedBrief, report: SpecReport, strict: bool) -> SpecReport:
    """The draft with each cut through the next face given how deep it goes, as the preview finds it (item 2b's second
    step; :mod:`forge_occ.resolve`), checked again: found afresh every round, so an answer that moves what it goes
    through moves it too. A draft with none is as it is; one the preview can't find is left without it, and is an
    UNABLE: the spec can't be locked without it (:func:`forge_spec.lock.lock`), and Forge can't yet find it."""
    if report.spec is None or not any(isinstance(end_of(item), ThroughNext) for item in report.spec.items):
        return report
    from forge_occ.resolve import resolve_draft

    found = resolve_draft(to_wire(report.spec))
    checked = check_draft(numbered, found.draft, strict=strict)
    return with_unresolved(checked, found.notes)


def with_unresolved(report: SpecReport, notes: Sequence[tuple[str, str]]) -> SpecReport:
    """A report with an UNABLE for each cut through the next face the preview couldn't find how deep goes (``notes``,
    each the item and why)."""
    if not notes:
        return report
    where = {item.id: n for n, item in enumerate(report.spec.items)} if report.spec is not None else {}
    unable = tuple(
        SpecProblem("unable", f"/items/{where[item]}/depth" if item in where else "/items",
                    f"the preview couldn't find how deep {item} goes through the next face: {why}")
        for item, why in notes
    )  # fmt: skip
    return replace(report, problems=(*report.problems, *unable))


def _held_together(numbered: NumberedBrief, report: SpecReport, strict: bool, say: Say) -> SpecReport:
    """A spec with nothing left to settle, built once before it is confirmed or locked: with a CAN'T where the part as
    drafted comes apart (a cut taking a standing item, or a piece of a body, off the part; :mod:`forge_occ.apart`),
    which the spec's other checks, each item read on its face, don't find. Where it builds, or comes apart only as
    OpenCascade misreads it, the report is as it was; so where it can't be built to see (said): the build says why."""
    from forge_checks.judge import Judge
    from forge_occ.apart import comes_apart
    from forge_occ.planned import build_plan
    from forge_plan import plan

    say("\nBuilding it once to see that it holds together as one piece...")
    try:
        confirmed = lock(report, numbered, by="draft", strict=strict)
        planned = plan(confirmed)
        built = build_plan(planned)
        if built.gap is None:
            return report
        apart = comes_apart(planned, built, Judge.of(confirmed.spec))
    except Exception as error:  # not this check's to say: the build finds it, and says it
        say(f"It couldn't be built to see ({type(error).__name__}: {error}); forge build will say why.")
        return report
    if apart is None:
        return report
    assert report.spec is not None
    where = next((n for n, item in enumerate(report.spec.items) if item.id == apart.item), None)
    problem = SpecProblem("cant", "/items" if where is None else f"/items/{where}", apart.message())
    return replace(report, problems=(*report.problems, problem))


def _ending(report: SpecReport) -> list[Any]:
    """The problems that end a run: it can't be made (CAN'T), or Forge can't make it yet (UNABLE)."""
    return [p for p in report.problems if p.kind in ("cant", "unable")]


#: A brief longer than this many words is drafted twice by default: the
#: longer the brief, the likelier a misread (plan, 4.2).
LONG_BRIEF = 60


def _wants_second_anyway(
    brief: NumberedBrief, strict: bool, two_drafts: TwoDrafts
) -> bool:
    """Whether a second draft is wanted before the first is in: then the two run at once."""
    if two_drafts != "auto":
        return two_drafts == "always"
    return strict or len(brief.words) > LONG_BRIEF


def _wants_second(
    report: SpecReport, brief: NumberedBrief, strict: bool, two_drafts: TwoDrafts
) -> bool:
    return _wants_second_anyway(brief, strict, two_drafts) or (
        two_drafts == "auto" and bool(report.assumptions)
    )


#: What a second draft came to: the draft, or why there is none.
_Second = RoleResult[SpecReport] | RoleError | ModelError


def _draft_second(provider: Provider, brief: NumberedBrief, strict: bool,
                  cancellation: CancellationToken | None = None) -> _Second:  # fmt: skip
    """The second, independent draft; or why there is none: its own faults, or the model's failure.

    Neither is the first draft's concern: the run goes on without a second
    reading, and an automatic run stops for want of one.
    """
    try:
        return write_spec(
            provider, brief, strict=strict, second=True, cancellation=cancellation
        )
    except (RoleError, ModelError) as error:
        return error


class _Beside:
    """The second draft, drafted in a thread of its own while the first is drafted.

    A daemon thread, so a run that stops (Ctrl-C, a refused first draft) never
    waits on it: :meth:`drop` cancels it, and it makes no further call. What
    it spends counts against the run's one budget either way.
    """

    def __init__(self, provider: Provider, brief: NumberedBrief, strict: bool) -> None:
        self.cancellation = CancellationToken()
        self._done = threading.Event()
        self._made: _Second | None = None
        self._crash: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(provider, brief, strict),
                                        name="forge-second-draft", daemon=True)  # fmt: skip
        self._thread.start()

    def _run(self, provider: Provider, brief: NumberedBrief, strict: bool) -> None:
        try:
            budget = provider.budget
            if isinstance(
                budget, SharedBudget
            ):  # the first draft's first call comes first
                while not (
                    budget.owner_started.wait(0.2) or self.cancellation.cancelled
                ):
                    pass
            self._made = _draft_second(provider, brief, strict, self.cancellation)
        except BaseException as crash:  # a bug: handed to the run, which raises it
            self._crash = crash
        finally:
            if isinstance(provider.budget, SharedBudget):
                provider.budget.release()
            self._done.set()

    def result(self) -> _Second:
        """The second draft, once made. Waited for in short steps, so Ctrl-C stops the run at once."""
        while not self._done.wait(0.2):
            pass
        if self._crash is not None:
            raise self._crash
        assert self._made is not None
        return self._made

    def drop(self) -> None:
        self.cancellation.cancel()


def _compared(
    second: _Second, first: SpecReport, out: Path | None, say: Say
) -> tuple[tuple[Difference, ...], str]:
    """Where the second draft builds otherwise than the first, recorded and said; and any doubt it leaves.

    The doubt is why the second draft can't vouch for the first: there is
    none, or it has questions or assumptions of its own. Only an automatic
    run, which no person confirms, stops on it.
    """
    if not isinstance(second, RoleResult):
        _write(out, "draft-1-second", refused=second.as_dict())
        why = ("couldn't clear its own faults" if isinstance(second, RepairExhaustedError)
               else f"failed ({second.code})")  # fmt: skip
        say(f"The second draft {why}: there is nothing to compare the first with.")
        return (), f"the second draft {why}, so the first can't be compared with one"
    assert second.value.spec is not None
    _write(
        out, "draft-1-second", calls=second.as_dict(), draft=to_wire(second.value.spec)
    )
    if second.value.needs_redraft or _ending(
        second.value
    ):  # pragma: no cover - a returned draft has no faults
        return (), "the second draft can't be compared"
    found = differences(first, second.value)
    say(
        f"The two drafts differ in {len(found)} place(s)."
        if found
        else "The two drafts build the same part."
    )
    own = len(second.value.problems) + len(second.value.assumptions)
    doubt = (
        f"the second draft has {own} question(s) and assumption(s) of its own"
        if own
        else ""
    )
    return found, doubt


def priced(provider: Provider) -> Provider:
    """The provider, its budget given the most a request can cost where it can say: a cost ceiling that holds before a call (docs/V2-stage4.md, 14.4)."""
    price = getattr(provider, "worst_cost_usd", None)
    if callable(price):
        provider.budget.price = price
    return provider


class SharedBudget(Budget):
    """One budget for two drafts drafted at once: what either spends counts against both.

    Each thread's call in flight is held against the budget from its check
    to its record, so two threads can't both pass a check that only one
    call's worth of budget can meet. A thread has one call in flight at a
    time; its next check, its record, or :meth:`release` when it is done
    lets the hold go. A call is held at its tokens and, where the budget
    has a price, at its worst cost: the cost ceiling then holds for both
    drafts together. With no price, the ceiling refuses the call after the
    one that reaches it.
    """

    def __init__(self, limits: Budget) -> None:
        super().__init__(max_total_tokens=limits.max_total_tokens, max_calls=limits.max_calls,
                         max_cost_usd=limits.max_cost_usd, calls=limits.calls, usage=limits.usage,
                         price=limits.price)  # fmt: skip
        self._lock = threading.Lock()
        #: Each thread's call in flight: the tokens it may spend, and its worst cost (0 unpriced).
        self._held: dict[int, tuple[int, float]] = {}
        # The run's own thread drafts the first draft: the second waits until
        # its first call holds its budget, so a tight budget is the first's.
        self._owner = threading.get_ident()
        self.owner_started = threading.Event()

    def check_before(self, request: ModelRequest) -> None:
        me = threading.get_ident()
        with self._lock:
            self._held.pop(me, None)  # this thread's last call is over
            tokens = sum(t for t, _ in self._held.values())
            cost = sum(c for _, c in self._held.values())
            held = Usage(output_tokens=tokens, cost_usd=cost if cost else None)
            others = Budget(max_total_tokens=self.max_total_tokens, max_calls=self.max_calls,
                            max_cost_usd=self.max_cost_usd, calls=self.calls + len(self._held),
                            usage=self.usage + held, price=self.price)  # fmt: skip
            try:
                others.check_before(request)
                worst = self.price(request) if self.price is not None else None
                self._held[me] = (
                    request.approximate_input_tokens() + request.max_output_tokens,
                    worst or 0.0,
                )
            finally:
                if me == self._owner:
                    self.owner_started.set()

    def record(self, usage: Usage) -> None:
        with self._lock:
            self._held.pop(threading.get_ident(), None)
            super().record(usage)

    def release(self) -> None:
        """This thread is done: whatever it held, it no longer will spend."""
        with self._lock:
            self._held.pop(threading.get_ident(), None)


def share_budget(first: Provider, second: Provider) -> None:
    """Give two providers one budget, so the run's limits hold for both drafts together.

    Its price is the dearer of the two providers' for each request, where
    both can price one: the second draft may be another model's.
    """
    shared = (
        first.budget
        if isinstance(first.budget, SharedBudget)
        else SharedBudget(first.budget)
    )
    one, other = first.budget.price, second.budget.price
    if one is not None and other is not None and second.budget is not shared:
        shared.price = _dearer(one, other)
    first.budget = shared
    second.budget = shared


def _dearer(
    a: Callable[[ModelRequest], float | None], b: Callable[[ModelRequest], float | None]
) -> Callable[[ModelRequest], float | None]:
    def price(request: ModelRequest) -> float | None:
        found = [p for p in (a(request), b(request)) if p is not None]
        return max(found) if len(found) == 2 else None

    return price


def _write_spent(out: Path | None, provider: Provider) -> None:
    """What the run spent, both drafts together, written however it ended."""
    if out is None:
        return
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "spent.json").write_text(
            json.dumps(provider.budget.as_dict(), indent=2), encoding="utf-8"
        )
    except (
        OSError
    ):  # pragma: no cover - a record that can't be written never stops a run
        pass


def _answers_for(brief: NumberedBrief, draft: dict[str, Any], round_: Sequence[Question],
                 preset: Sequence[Answer], ask: Ask, say: Say) -> list[Answer]:  # fmt: skip
    """The round's answers: those written down beforehand, then the person's for every other question."""
    if any(not (a.at and a.asked) for a in preset):
        raise AnswerError(
            "an answer written down beforehand must name its question: its pointer and its text"
        )
    # An answer is the question it names by its pointer and its text, not
    # by its number: a second draft's differences, asked first, renumber the rest.
    by_question = {(q.at, q.text): q.id for q in round_}
    preset = [
        replace(a, question=by_question.get((a.at, a.asked), a.question))
        for a in preset
    ]
    if preset:  # one that doesn't fit is refused before anyone is asked
        apply_answers(brief, draft, round_, preset)
    answered = {a.question for a in preset}
    remaining = [q for q in round_ if q.id not in answered]
    return [*preset, *(_ask_round(remaining, ask, say) if remaining else [])]


def _ask_round(round_: Sequence[Question], ask: Ask, say: Say) -> list[Answer]:
    """One round: every question and assumption, answered by choosing an option."""
    given: list[Answer] = []
    say(
        f"\n{len(round_)} to settle. Answer each by its number; Enter keeps an assumption; q stops."
    )
    for question in round_:
        say(f"\n{question.id} ({question.kind}): {question.text}")
        for n, option in enumerate(question.options, start=1):
            say(f"  {n}. {option.label}")
        while True:
            reply = ask("> ").strip()
            if reply.lower() == "q":
                raise StoppedError
            if not reply and question.kind == "assumption":
                break
            if not (reply.isascii() and reply.isdigit()) or not 1 <= int(reply) <= len(
                question.options
            ):
                keep = ", or Enter to keep it" if question.kind == "assumption" else ""
                say(f"Answer 1 to {len(question.options)}{keep}.")
                continue
            answer = _detail(question, int(reply) - 1, ask, say)
            if answer is not None:
                given.append(answer)
                break
    return given


#: A size as typed: a number, signed or not, and the unit if the person says one.
_SIZE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*([A-Za-z]*)")


def _detail(question: Question, index: int, ask: Ask, say: Say) -> Answer | None:
    """What the chosen option needs from the person: a number, a size, or a note."""
    option = question.options[index]
    at, asked = question.at, question.text
    if option.kind == EditKind.COUNT:
        reply = ask("How many? ").strip()
        if re.fullmatch(r"\d+", reply):
            return Answer(question.id, index, number=float(reply), at=at, asked=asked)
    elif option.kind == EditKind.VALUE:
        reply = ask(
            f"How much, in {option.unit or 'mm'} (or say the unit: 0.5 in)? "
        ).strip()
        found = _SIZE.fullmatch(reply.replace("\u2212", "-"))
        if found:
            unit = found.group(2) or option.unit or "mm"
            return Answer(
                question.id,
                index,
                number=float(found.group(1)),
                unit=unit,
                at=at,
                asked=asked,
            )
    elif option.kind == EditKind.TEXT:
        reply = ask("Name it, as you would write it: ").strip()
        if reply:
            return Answer(question.id, index, text=reply, at=at, asked=asked)
        say("Say what it is; choose again.")
        return None
    elif option.kind == EditKind.NOTE:
        return Answer(
            question.id,
            index,
            text=ask("Tell the writer, in one line: ").strip(),
            at=at,
            asked=asked,
        )
    else:
        return Answer(question.id, index, at=at, asked=asked)
    say("That isn't a number; choose again.")
    return None


def _confirm(report: SpecReport, brief: NumberedBrief, private: Private | None, say: Say, out: Path | None,
             rounds: int, code: Callable[[], str], echo: bool, sealer: Sealer | None) -> Outcome:  # fmt: skip
    """The person confirms by typing back the code shown in Forge's own window; then the spec is locked."""
    if private is None:
        return Outcome("stopped", brief, report, rounds=rounds,
                       message="Nothing is left to settle, but confirming takes the code Forge shows in its own "
                       "terminal, and this run has none. Run forge spec in a terminal, or lock the spec as a "
                       "draft with --auto.")  # fmt: skip
    shown = code()
    spec = report.spec
    assert spec is not None
    say(
        "\nNothing is left to settle. Confirm it in Forge's own window, with the code shown there."
    )
    if (
        echo
    ):  # the person reads here what they confirm: the run's output may not reach them
        private.show("\n" + render(report, brief).text())
    private.show(f"\nForge: to confirm the spec {spec.name!r} ({len(spec.items)} item(s)) as shown, "
                 f"type the code {shown} here (or q to stop).")  # fmt: skip
    for _ in range(3):
        typed = private.read("code> ")
        if typed.strip().lower() == "q":
            break
        if _same_code(typed, shown):
            confirmed = lock(report, brief, by="person", strict=False)
            _write_confirmed(
                out,
                confirmed,
                None if sealer is None else sealer.seal(confirmed.digest),
            )
            if out is not None:
                write_spec_page(
                    out,
                    report,
                    brief,
                    status=f"Confirmed by you. Digest {confirmed.digest}",
                )
            private.show("Confirmed.")
            say(f"Confirmed. Digest {confirmed.digest}")
            return Outcome(
                "confirmed", brief, report, confirmed, rounds, "confirmed by the person"
            )
        private.show("That isn't the code.")
    return Outcome("stopped", brief, report, rounds=rounds, message="not confirmed")


def _write(out: Path | None, folder: str, **files: Any) -> None:
    """Write a run's records: text as .txt, everything else as JSON."""
    if out is None:
        return
    directory = out / folder
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if isinstance(content, str):
            (directory / f"{name}.txt").write_text(content, encoding="utf-8")
        else:
            text = json.dumps(content, indent=2, ensure_ascii=False, default=str)
            (directory / f"{name}.json").write_text(text, encoding="utf-8")


def _write_confirmed(
    out: Path | None, confirmed: ConfirmedSpec, seal: str | None = None
) -> None:
    """``confirmed.json``: the brief, the spec, its digest, who confirmed it, and a person's confirmation's seal (9.7)."""
    if out is None:
        return
    out.mkdir(parents=True, exist_ok=True)
    record = {"by": confirmed.by, "strict": confirmed.strict, "digest": confirmed.digest,
              "brief": confirmed.brief.text, "answers_from": confirmed.brief.answers_from, "edits": list(confirmed.edits),
              "spec": to_wire(confirmed.spec)}  # fmt: skip
    if seal is not None:
        record["seal"] = seal
    (out / "confirmed.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ----------------------------------------------------------------------
# The command
# ----------------------------------------------------------------------
_ANSWER_FIELDS: dict[str, type | tuple[type, ...]] = {"question": str, "option": int, "number": (int, float), "unit": str, "text": str,
                  "at": str, "asked": str}  # fmt: skip


def load_answers(path: Path) -> list[Answer]:
    """A file of answers for ``--answers``: each names its question, by id, pointer and text.

    Refused whole, with what is wrong, when it isn't a list of such answers:
    an answer that can't say which question it was written for could be
    applied to another.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"--answers {path}: {error}") from None
    if not isinstance(raw, list):
        raise SystemExit(f"--answers {path}: a list of answers, one object each")
    found: list[Answer] = []
    for n, entry in enumerate(raw):
        where = f"--answers {path}, answer {n}"
        if not isinstance(entry, dict):
            raise SystemExit(f"{where}: an object such as "
                             '{"question": "q1", "at": "/items/1/depth", "asked": "...", "option": 0}')  # fmt: skip
        unknown = sorted(set(entry) - set(_ANSWER_FIELDS))
        missing = sorted({"question", "option", "at", "asked"} - set(entry))
        if unknown or missing:
            raise SystemExit(f"{where}: " + "; ".join(
                ([f"unknown {', '.join(unknown)}"] if unknown else [])
                + ([f"needs {', '.join(missing)}"] if missing else [])))  # fmt: skip
        for name, value in entry.items():
            kind = _ANSWER_FIELDS[name]
            if isinstance(value, bool) or not isinstance(value, kind):
                raise SystemExit(
                    f"{where}: {name} has the wrong type ({type(value).__name__})"
                )
        if not (entry["at"].strip() and entry["asked"].strip()):
            raise SystemExit(
                f"{where}: at and asked name the question it answers; they can't be empty"
            )
        if isinstance(entry.get("number"), float) and not math.isfinite(
            entry["number"]
        ):
            raise SystemExit(f"{where}: number must be finite")
        found.append(Answer(**entry))
    return found


def command_spec(args: argparse.Namespace) -> int:
    brief = (
        Path(args.brief_file).read_text(encoding="utf-8")
        if args.brief_file
        else (args.brief or "")
    )
    if not brief.strip():
        raise SystemExit("the brief is empty; describe the part you want")
    if args.auto and args.answers:
        raise SystemExit("--answers answers a person's questions, and an automatic run asks none: "
                         "run it without --auto, or without --answers")  # fmt: skip
    provider = priced(build_provider(args))
    # The second draft gets a provider of its own (another model, if asked),
    # so the two can draft at once, under one budget.
    second = None
    if args.drafts != "1":
        second = priced(
            build_provider(
                argparse.Namespace(
                    **{**vars(args), "model": args.second_model or args.model}
                )
            )
        )
    out = (
        Path(args.out)
        if args.out
        else _fresh(
            Path("runs") / f"spec-{time.strftime('%Y%m%dT%H%M%S')}-{_slug(brief)}"
        )
    )
    preset = load_answers(Path(args.answers)) if args.answers else []
    info = provider.info
    remote = "  (remote: the brief leaves this machine)" if info.is_remote else ""
    print(f"Provider : {info.name} / {info.model}{remote}")
    print(f"Run      : {out}")
    print(
        f"Page     : {out / 'spec.html'} (open it to read the brief coloured by the spec)"
    )
    terminal = None if args.auto else ControllingTerminal.open()
    sealer = None
    if terminal is not None:
        try:
            sealer = Sealer.of_install(create=True)
        except SealError as error:
            print(f"Seal    : none ({error}): a spec confirmed here builds as a draft")
    try:
        # Where the run's input or output isn't the terminal, the person may
        # see nothing of it: the spec is then shown again in Forge's window.
        piped = not (sys.stdin.isatty() and sys.stdout.isatty())
        outcome = run_spec(brief, provider, ask=input, say=print, private=terminal, strict=args.auto,
                           out=out, answers=preset, echo=piped, second=second,
                           two_drafts=_DRAFTS[args.drafts], sealer=sealer)  # fmt: skip
    finally:
        if terminal is not None:
            terminal.close()
    if outcome.message:
        print("\n" + outcome.message)
    return {"confirmed": EXIT_LOCKED, "draft": EXIT_LOCKED, "refused": EXIT_REFUSED,
            "stopped": EXIT_STOPPED, "questions": EXIT_QUESTIONS}[outcome.status]  # fmt: skip


def _fresh(folder: Path) -> Path:
    """A run folder no other run has: two runs of one brief in one second get one each."""
    found, n = folder, 1
    while found.exists():
        n += 1
        found = folder.with_name(f"{folder.name}-{n}")
    return found


def add_spec_parser(subparsers: Any) -> argparse.ArgumentParser:
    """``forge spec``: its flags are those of ``forge design`` that a spec run reads."""
    spec: argparse.ArgumentParser = subparsers.add_parser(
        "spec",
        help="draft the part spec of a brief, settle its questions, and confirm it (V2)",
        description=(
            "Draft the part spec of a brief, check it against the brief, ask what only you can "
            "settle, and lock it when you confirm it with the code shown here."
        ),
    )
    spec.add_argument(
        "brief", nargs="?", help="the brief, in a sentence or a paragraph"
    )
    spec.add_argument("--brief-file", help="read the brief from this file instead")
    spec.add_argument("--auto", action="store_true",
                      help="no person: stricter checks, nothing asked, locked only as a draft")  # fmt: skip
    spec.add_argument(
        "--answers", help="JSON list of answers to the first round (scripted runs)"
    )
    spec.add_argument(
        "--out", help="directory for the run's records (default runs/spec-...)"
    )
    spec.add_argument("--drafts", choices=("1", "2", "auto"), default="auto",
                      help="draft the brief twice and ask where the drafts differ: 2 always, 1 never, auto when "
                      "the first has assumptions, the brief is long, or with --auto")  # fmt: skip
    spec.add_argument(
        "--second-model", help="the model for the second draft (default: the same one)"
    )
    add_model_flags(spec, max_tokens=400_000, max_calls=20)
    spec.set_defaults(handler=command_spec)
    return spec


def add_model_flags(
    parser: argparse.ArgumentParser, *, max_tokens: int, max_calls: int
) -> None:
    """The model and budget flags of a command that drafts specs (read by ``build_provider``)."""
    model = parser.add_argument_group("model")
    model.add_argument(
        "--provider",
        choices=("anthropic", "ollama", "openai", "fixture"),
        default="anthropic",
    )
    model.add_argument("--model", help="model identifier (default: Claude Sonnet 5)")
    model.add_argument("--base-url", help="endpoint for --provider openai or ollama")
    model.add_argument("--api-key-env", default="OPENAI_API_KEY",
                       help="environment variable holding the key for --provider openai")  # fmt: skip
    model.add_argument(
        "--structured-mode",
        choices=("json_schema", "tools", "json_object"),
        default="json_schema",
    )
    model.add_argument(
        "--schema-dialect",
        choices=("json_schema", "openapi", "opaque"),
        default="json_schema",
    )
    model.add_argument(
        "--exact-schema",
        action="store_true",
        help="refuse a request rather than narrow its schema",
    )
    model.add_argument(
        "--timeout", type=float, default=300.0, help="seconds to wait for one response"
    )
    model.add_argument(
        "--context-window", type=int, default=None, help="the endpoint's context length"
    )
    model.add_argument(
        "--thinking", choices=("auto", "adaptive", "enabled", "off"), default=None
    )
    model.add_argument(
        "--effort", choices=("low", "medium", "high", "xhigh", "max"), default=None
    )
    model.add_argument("--fixtures", help="directory to replay with --provider fixture")
    model.add_argument("--record", help="record every response into this directory")
    limits = parser.add_argument_group("budget")
    limits.add_argument("--max-tokens", type=int, default=max_tokens)
    limits.add_argument("--max-calls", type=int, default=max_calls)
    limits.add_argument(
        "--max-cost", type=float, default=None, help="hard stop, estimated USD"
    )
