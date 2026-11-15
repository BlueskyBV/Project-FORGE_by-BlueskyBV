"""``forge eval-spec``: draft every brief of a locked set, and grade the drafts (V2, stage 1).

Stage 1's exit test is read here (plan, section 8): on a blind set, the share
of its answer keys' facts the spec writer gets right before anyone touches
the draft, with the 95% upper bound on the share it gets wrong.

1. The set's manifest is checked first: a key changed after it was locked
   would grade nothing (:func:`forge_eval.keys.verify_manifest`).
2. Each brief is drafted once, as ``forge spec`` drafts it, and its records
   go to its own folder: the model's final answer, the draft read from it,
   the spec in fixed wording, its problems, every model call, and last
   ``record.json``, which holds the answer's digest. A brief is graded from
   the model's answer, never from a copy: one changed after drafting is
   refused. ``ledger.jsonl`` lists every brief drafted, so one whose record
   went missing is never quietly drafted a second time.
3. Each draft is graded (:mod:`forge_eval.spec_grade`). Facts in words wait
   for a person: mark them in ``marks.json`` and run the same command again.
   It regrades the recorded drafts and calls no model.

One run folder is one measurement. ``run.json`` records what it measures:
the set (its manifest), the mode, the model, the writer's guide and settings,
and a digest of the code that drafts, checks and grades. Any other set, mode,
model or writer is refused. Other code may regrade what is recorded, flagged
as such, but never draft more into the same folder.

Running it again resumes: a brief already drafted is regraded from its
record, never drafted twice, so a budget that runs out costs nothing already
spent. A model error that may pass (a dropped connection, a rate limit) or
that every brief would meet (the budget, the key) stops the run, keeping
every brief done; one that is this brief's own (a request the endpoint
refuses) is noted in the ledger and the run goes on. Neither is graded as the
writer's failure: those briefs are left ungraded and drafted again on the
next run. Every grading is appended to ``history.jsonl`` with the keys it
graded, so the first measurement stays on record whatever is regraded after.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import forge_spec
from forge_eval.keys import AnswerKey, AnswerKeyError, verify_manifest
from forge_eval.spec_grade import (
    MarksError,
    SetGrade,
    SpecGrade,
    TwoDrafts,
    grade_set,
    grade_spec,
    load_marks,
    marks_template,
    two_drafts,
)
from forge_models import (
    AuthenticationError,
    BudgetExceededError,
    CancelledError,
    ConfigurationError,
    ModelError,
    Provider,
    Usage,
)
from forge_roles.base import RepairExhaustedError, RoleOutputError, answer_in_shape
from forge_roles.spec_writer import SpecWriter, write_spec
from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.compare import differences
from forge_spec.guide import draft_schema
from forge_spec.render import render
from forge_spec.wire import to_wire

from .design import build_provider
from .spec import add_model_flags, priced, share_budget

__all__ = [
    "RUN_FORMAT",
    "RecordError",
    "RunMismatchError",
    "SetRun",
    "add_eval_spec_parser",
    "code_digest",
    "command_eval_spec",
    "run_set",
]

RUN_FORMAT = 1
EXIT_DONE = 0
EXIT_REFUSED = 1
EXIT_STOPPED = 2

#: Model errors every brief would meet: they stop the run, never one brief.
_STOPS = (AuthenticationError, BudgetExceededError, CancelledError, ConfigurationError)

Say = Callable[[str], None]


class RunMismatchError(ValueError):
    """A run folder made for another measurement: resuming would mix two in one."""


class RecordError(ValueError):
    """A brief's record that was changed after it was drafted."""


@dataclass(frozen=True)
class SetRun:
    """What one run of a set did, and the grade it reached."""

    grade: SetGrade
    drafted: int
    reused: int
    usage: Usage = field(default_factory=Usage)
    #: Why the run stopped before every key was graded; "" if it didn't.
    stopped: str = ""
    #: Keys whose marks were made against another draft, and dropped.
    dropped: tuple[str, ...] = ()
    #: Keys left ungraded by a model error of their own, with the error.
    errors: tuple[tuple[str, str], ...] = ()
    #: Regraded by other code than drafted the briefs: not the measurement.
    other_code: bool = False
    #: With two drafts a brief: how well their differences found what was wrong.
    two_drafts: TwoDrafts | None = None
    #: Readings drafted afresh after an error stopped an earlier try partway.
    afresh: tuple[str, ...] = ()


#: What a measurement rests on: every module of these packages, and these files.
_MEASURED_PACKAGES = (
    "forge_spec",
    "forge_eval",
    "forge_models",
    "forge_units",
    "forge_expr",
)
_MEASURED_FILES = (("forge_roles", "__init__.py"), ("forge_roles", "base.py"), ("forge_roles", "spec_writer.py"),
                   ("forge_cli", "eval_spec.py"), ("forge_cli", "spec.py"), ("forge_cli", "design.py"))  # fmt: skip


@functools.cache
def code_digest() -> str:
    """A digest of the code a measurement rests on: what reads, drafts, checks and grades.

    Whole packages, read from disk, so the digest doesn't depend on what
    happens to be imported; line endings are read as one, so a checkout on
    Windows and one on Linux of the same code make the same digest. Read
    once a process: the code running is the code it started with.
    """
    root = Path(forge_spec.__file__).resolve().parent.parent
    files = [
        f
        for package in _MEASURED_PACKAGES
        for f in sorted((root / package).rglob("*.py"))
    ]
    files += [root / package / name for package, name in _MEASURED_FILES]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def run_set(directory: Path, provider: Provider, out: Path, *, strict: bool = False,
            only: Sequence[str] = (), say: Say = print, drafts: int = 1,
            second: Provider | None = None, settings: Mapping[str, Any] | None = None) -> SetRun:  # fmt: skip
    """Draft (or reuse the record of) every brief of a locked set, grade each, and write it all down.

    With ``drafts=2`` each brief is drafted a second time, on its own (by
    ``second``, when another model should), and the two are compared
    (:mod:`forge_spec.compare`): the run then measures whether where they
    differ is where the first is wrong (:func:`forge_eval.spec_grade.two_drafts`).
    Only the first draft is graded, and a brief whose first draft gave up is
    not drafted again. Both drafts spend one budget. ``settings`` are how the
    model was asked to run (the command's model flags): they are part of what
    the run measures.
    """
    if drafts not in (1, 2):
        raise ValueError("a brief is drafted once or twice")
    every = verify_manifest(directory)
    if only:
        missing = sorted(set(only) - set(every))
        if missing:
            raise AnswerKeyError(f"no such key in the set: {', '.join(missing)}")
    keys = {k: v for k, v in every.items() if not only or k in only}
    other = second or provider
    if other is not provider:
        share_budget(
            provider, other
        )  # one budget for the run: --max-calls means calls in all
    other_code = _claim(
        out, directory, strict, provider, other if drafts == 2 else None, settings or {}
    )
    readings = [(key, name, folder) for key in keys.values()
                for name, folder in _readings(out, key.id, drafts)]  # fmt: skip
    recorded = {name: _recorded(folder, key, strict) for key, name, folder in readings}
    # A brief whose first draft gave up has nothing for a second to check.
    gave_up = {key.id for key in keys.values() if recorded[key.id] == (True, None)}
    todo = [name for name, (found, _) in recorded.items()
            if not found and name.split("/")[0] not in gave_up]  # fmt: skip
    drafted_before = sorted(set(todo) & _ledger_drafted(out))
    if drafted_before:
        raise RecordError(
            f"{', '.join(drafted_before)} drafted before in {out}, but the record is gone: a second draft is no "
            "first draft. Restore the record, or start a new run with another --out."
        )
    if todo and other_code:
        raise RunMismatchError(
            f"Forge's code changed since {out} was drafted: drafting {', '.join(todo)} there would mix two "
            "versions in one measurement. Start a new run with another --out (regrading what is recorded, "
            "with nothing left to draft, is still allowed)."
        )
    raw_marks = _read_json(out / "marks.json")
    marks = load_marks(out / "marks.json") if raw_marks is not None else {}
    grades: list[SpecGrade] = []
    drafted = reused = 0
    start = provider.budget.usage  # both drafts spend this one budget
    stopped = ""
    dropped: list[str] = []
    errors: list[tuple[str, str]] = []
    flagged: dict[str, bool] = {}
    interrupted = _ledger_interrupted(out)
    for n, key in enumerate(keys.values(), start=1):
        reports: list[SpecReport | None] = []
        made_now = False
        for k, (name, folder) in enumerate(_readings(out, key.id, drafts)):
            found, report = recorded[name]
            if found:
                reports.append(report)
                continue
            if k and reports[0] is None:
                break  # the first draft gave up: there is nothing to compare a second with
            say(f"[{n}/{len(keys)}] drafting {name}...")
            calls = provider.budget.calls
            try:
                report = _draft(other if k else provider, key, folder, strict, second=bool(k),
                                after_interruption=interrupted.get(name, 0))  # fmt: skip
            except ModelError as error:
                # Calls made for this brief before the error are on record: a
                # brief drafted afresh after it says so.
                spent = provider.budget.calls - calls
                if error.retryable or isinstance(error, _STOPS):
                    _note(out, name, "interrupted" if spent else "stopped", calls=spent,
                          error=error.as_dict())  # fmt: skip
                    # Said by its code and message: its details are on the ledger.
                    stopped = f"{name}: [{error.code}] {error.message}"
                    break
                _note(out, name, "model error", calls=spent, error=error.as_dict())
                errors.append((name, f"[{error.code}] {error.message}"))
                break
            _note(out, name, "gave up" if report is None else "drafted")
            made_now = True
            reports.append(report)
        if made_now:
            drafted += 1
        elif reports:
            reused += 1
        if stopped:
            break
        if not reports:
            continue  # the first draft met a model error of its own: not graded
        report = reports[0]
        grade = grade_spec(key, report)
        digest, facts = marks.get(key.id, ("", {}))
        if facts and grade.draft and digest == grade.draft:
            grade = grade_spec(key, report, facts)
        elif facts and grade.draft:
            dropped.append(key.id)
        grades.append(grade)
        _write(out / key.id, "grade.json", grade.as_dict())
        if len(reports) == 2:
            found_differences = _compare(reports[0], reports[1])
            _write(out / key.id, "differences.json", found_differences)
            if isinstance(found_differences, list):
                flagged[key.id] = bool(found_differences)
        elif drafts == 2:
            why = ("the first draft gave up: no second was made" if reports[0] is None
                   else "the second draft wasn't made: a model error of its own")  # fmt: skip
            _write(out / key.id, "differences.json", {"compared": "no", "why": why})
    result = grade_set(grades)
    usage = _spent(start, provider.budget.usage)
    afresh = sorted(k for k in interrupted if (out / k / "record.json").exists())
    compared = two_drafts(grades, flagged) if drafts == 2 else None
    _write(out, "marks.json", marks_template(grades, raw_marks))
    graded = [g.key for g in grades]
    summary = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "set_keys": len(every), "keys": graded,
               "only": list(only), "complete": len(graded) == len(every), "drafted": drafted, "reused": reused,
               "stopped": stopped, "errors": dict(errors), "code": code_digest(), "other_code": other_code,
               "drafted_after_interruption": afresh,
               **result.as_dict(), "two_drafts": compared.as_dict() if compared else None,
               "usage": usage.as_dict()}  # fmt: skip
    _write(out, "summary.json", summary)
    with (out / "history.jsonl").open("a", encoding="utf-8") as history:
        history.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return SetRun(
        result,
        drafted,
        reused,
        usage,
        stopped,
        tuple(dropped),
        tuple(errors),
        other_code,
        compared,
        tuple(afresh),
    )


def _readings(out: Path, key: str, drafts: int) -> list[tuple[str, Path]]:
    """Each draft of a brief: its name in the ledger, and its folder."""
    first = (key, out / key)
    return [first, (f"{key}/second", out / key / "second")] if drafts == 2 else [first]


def _compare(
    first: SpecReport | None, second: SpecReport | None
) -> list[dict[str, str]] | dict[str, str]:
    """Where the second draft differs from the first; or why the two can't be compared."""
    for report, which in ((first, "first"), (second, "second")):
        if report is None or report.spec is None or report.needs_redraft:
            return {
                "compared": "no",
                "why": f"the {which} draft gave up, or no longer checks clean",
            }
        if any(p.kind in ("cant", "unable") for p in report.problems):
            return {
                "compared": "no",
                "why": f"the {which} draft can't be made (CAN'T or UNABLE): it ends its run",
            }
    assert first is not None and second is not None
    return [{"at": d.at, "message": d.message} for d in differences(first, second)]


def _what_it_measures(directory: Path, strict: bool, provider: Provider, second: Provider | None,
                      settings: Mapping[str, Any]) -> dict[str, Any]:  # fmt: skip
    writer = SpecWriter(strict=strict)
    return {
        "format": RUN_FORMAT,
        "set": directory.name,
        "manifest": hashlib.sha256(
            (directory / "MANIFEST.json").read_bytes()
        ).hexdigest(),
        "strict": strict,
        "model": f"{provider.info.name}/{provider.info.model}",
        # How the model was asked to run: its reasoning and effort as set up
        # (from the flags or the environment), and the transport's flags.
        "model_settings": {
            "thinking": provider.info.thinking,
            "effort": provider.info.effort,
            **{k: settings[k] for k in sorted(settings)},
        },
        # Drafted twice, and by what: another comparison is another measurement.
        "second_model": f"{second.info.name}/{second.info.model}"
        if second is not None
        else None,
        "writer": {
            "role": writer.name,
            "prompt_version": writer.prompt_version,
            "max_attempts": writer.max_attempts,
            "max_output_tokens": writer.max_output_tokens,
            "output_token_ceiling": writer.output_token_ceiling,
            "effort": writer.effort,
        },
        "second_writer": SpecWriter(strict=strict, second=True).prompt_version
        if second is not None
        else None,
        "code": code_digest(),
    }


def _claim(out: Path, directory: Path, strict: bool, provider: Provider, second: Provider | None,
           settings: Mapping[str, Any]) -> bool:  # fmt: skip
    """Record what this run folder measures, or refuse another measurement; True when only the code differs.

    A folder that holds drafts but no ``run.json`` measured something no one
    can now say: it is refused, never claimed.
    """
    run = _what_it_measures(directory, strict, provider, second, settings)
    before = _read_json(out / "run.json")
    if before is None:
        if (out / "ledger.jsonl").exists() or any(out.rglob("record.json")):
            raise RunMismatchError(
                f"{out} holds drafts but no run.json saying what they measure: start a new run with another "
                "--out, or restore its run.json"
            )
        _write(out, "run.json", run)
        return False
    # The manifest names the set: the folder it is read from may move.
    changed = sorted(
        k for k in run if k not in ("set", "code") and before.get(k) != run[k]
    )
    if changed:
        raise RunMismatchError(
            f"{out} holds a run of another {', '.join(changed)}: "
            + "; ".join(f"{k} was {before.get(k)!r}, now {run[k]!r}" for k in changed)
            + ". Start a new run with another --out."
        )
    return bool(before.get("code") != run["code"])


def _canonical(content: Any) -> str:
    text = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _recorded(
    folder: Path, key: AnswerKey, strict: bool
) -> tuple[bool, SpecReport | None]:
    """Whether a brief was drafted already, and its draft read again from the model's answer (None: it gave up).

    Only a record finished in full counts: ``record.json`` is written last.
    One whose answer doesn't match the digest it was recorded with is
    refused (:class:`RecordError`).
    """
    record = _read_json(folder / "record.json")
    if not isinstance(record, Mapping):
        return False, None
    if record.get("refused"):
        return True, None
    answer = _read_json(folder / "answer.json")
    if answer is None or _canonical(answer) != record.get("answer"):
        raise RecordError(
            f"{folder}: the model's recorded answer was changed after drafting, or is missing"
        )
    try:
        shaped = answer_in_shape(answer, draft_schema())
    except RoleOutputError:  # read as it was: the checks say what is wrong with it
        shaped = answer
    return True, check_draft(number_words(key.brief), shaped, strict=strict)


def _draft(provider: Provider, key: AnswerKey, folder: Path, strict: bool, *, second: bool = False,
           after_interruption: int = 0) -> SpecReport | None:  # fmt: skip
    """Draft one brief and write its records; None when the writer couldn't clear its own faults.

    ``second`` drafts it as the second, independent reading (:class:`SpecWriter`).
    ``after_interruption`` is how many calls an earlier, interrupted try of
    this brief made: the record says it was drafted afresh after them.
    """
    brief = number_words(key.brief)
    when = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        result = write_spec(provider, brief, strict=strict, second=second)
    except RepairExhaustedError as error:
        _write(folder, "refused.json", error.as_dict())
        _write(folder, "record.json", {"format": RUN_FORMAT, "refused": True, "when": when,
                                       "after_interruption": after_interruption})  # fmt: skip
        return None
    report = result.value
    assert report.spec is not None  # the writer returns only a draft that was read
    answer = result.responses[-1].structured if result.responses else None
    _write(folder, "calls.json", result.as_dict())
    _write(folder, "answer.json", answer)
    _write(
        folder, "draft.json", to_wire(report.spec)
    )  # the answer as read: for reading, never graded from
    _write(folder, "problems.json", [asdict(p) for p in report.problems])
    (folder / "spec.txt").write_text(
        render(report, brief).text() + "\n", encoding="utf-8"
    )
    # Last, so that a record on file is always whole.
    _write(folder, "record.json", {"format": RUN_FORMAT, "answer": _canonical(answer), "attempts": result.attempts,
                                   "when": when, "after_interruption": after_interruption})  # fmt: skip
    return report


def _note(out: Path, key: str, event: str, **detail: Any) -> None:
    """Add a line to the run's ledger: what happened to a brief, and when. Never rewritten."""
    out.mkdir(parents=True, exist_ok=True)
    line = {
        "key": key,
        "event": event,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **detail,
    }
    with (out / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
        ledger.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def _ledger_drafted(out: Path) -> set[str]:
    """The briefs the ledger says were drafted to the end (a draft, or the writer giving up)."""
    path = out / "ledger.jsonl"
    if not path.exists():
        return set()
    lines = (
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return {
        str(line["key"])
        for line in lines
        if line.get("event") in ("drafted", "gave up")
    }


def _ledger_interrupted(out: Path) -> dict[str, int]:
    """The briefs an error stopped partway, and the calls each made before it."""
    path = out / "ledger.jsonl"
    if not path.exists():
        return {}
    found: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if entry.get("event") == "interrupted":
                found[str(entry["key"])] = found.get(str(entry["key"]), 0) + int(
                    entry.get("calls", 0)
                )
    return found


def _spent(start: Usage, end: Usage) -> Usage:
    """What the provider spent between two readings of its budget, refused drafts included."""
    cost = None if end.cost_usd is None else end.cost_usd - (start.cost_usd or 0.0)
    return Usage(input_tokens=end.input_tokens - start.input_tokens, output_tokens=end.output_tokens - start.output_tokens,
                 cached_input_tokens=end.cached_input_tokens - start.cached_input_tokens, cost_usd=cost)  # fmt: skip


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write(folder: Path, name: str, content: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content, indent=2, ensure_ascii=False, default=str) + "\n"
    (folder / name).write_text(text, encoding="utf-8")


# ----------------------------------------------------------------------
# What the person reads
# ----------------------------------------------------------------------
def report_lines(run: SetRun, confidence: float = 0.95) -> list[str]:
    """The run's grade in a few lines: rates with their bound and denominator, and what waits."""
    g = run.grade
    graded = g.right + g.wrong
    marked = [x for x in g.grades if x.marked]
    ends = sorted(g.endings.items())
    by_expect = {
        e: ", ".join(f"{n} {got}" for (x, got), n in ends if x == e)
        for (e, _), _ in ends
    }
    lines = [
        f"Graded   : {len(g.grades)} briefs ({run.drafted} drafted now, {run.reused} from their records)",
        f"Facts    : {g.right} of {graded} graded right ({g.rate:.1%}); "
        f"wrong at most {g.wrong_at_most(confidence):.1%} ({confidence:.0%} upper bound)",
        f"Waiting  : {g.waiting('person')} for your marks (marks.json); "
        f"{g.waiting('built part')} for the built part (stage 4)",
        f"Parts    : {sum(1 for x in marked if x.all_right)} of {len(marked)} fully marked have no fact wrong",
        "Endings  : " + "; ".join(f"{e}: {got}" for e, got in by_expect.items()),
    ]
    if run.usage.total_tokens:
        cost = (
            f" (estimated ${run.usage.cost_usd:.2f})"
            if run.usage.cost_usd is not None
            else ""
        )
        lines.append(f"Spent    : {run.usage.total_tokens:,} tokens{cost}")
    wrong = [(x.key, f) for x in g.grades for f in x.facts if f.verdict == "wrong"]
    if wrong:
        lines.append("Wrong    :")
        lines += [
            f"  {key}: {f.fact}" + (f" ({f.detail})" if f.detail else "")
            for key, f in wrong
        ]
    if run.dropped:
        lines.append(
            f"Dropped  : marks made against another draft of {', '.join(run.dropped)}"
        )
    compared = run.two_drafts
    if compared is not None:
        lines.append(
            f"Two drafts: compared {compared.compared}; they differed on {compared.caught} of the "
            f"{compared.wrong} with a fact wrong (missed at most {compared.missed_at_most(confidence):.1%}), "
            f"and on {compared.false_alarms} of the {compared.right} marked all right"
        )
    for name, error in run.errors:
        brief, _, which = name.partition("/")
        lines.append(f"Error    : {brief}'s second draft not made, a model error of its own ({error}); run again "
                     "to retry it" if which else
                     f"Error    : {brief} not graded, a model error of its own ({error}); run again to retry it")  # fmt: skip
    if run.afresh:
        lines.append(f"Afresh   : {', '.join(run.afresh)} drafted again from the start after an error stopped an "
                     "earlier try partway (in the ledger)")  # fmt: skip
    if run.other_code:
        lines.append(
            "Regraded : by other code than drafted these briefs: not the stage 1 measurement"
        )
    if run.stopped:
        lines.append(f"Stopped  : {run.stopped}. Run the same command again to resume.")
    return lines


#: The model flags that change what a model answers: part of what a run measures.
_MODEL_SETTINGS = ("provider", "thinking", "effort", "base_url", "structured_mode", "schema_dialect",
                   "exact_schema", "context_window")  # fmt: skip


def command_eval_spec(args: argparse.Namespace) -> int:
    directory = Path(args.set)
    out = Path(args.out) if args.out else Path("runs") / f"eval-spec-{directory.name}"
    provider = priced(build_provider(args))
    info = provider.info
    remote = "  (remote: the briefs leave this machine)" if info.is_remote else ""
    print(f"Set      : {directory}")
    print(f"Provider : {info.name} / {info.model}{remote}")
    print(f"Run      : {out}")
    second = (priced(build_provider(argparse.Namespace(**{**vars(args), "model": args.second_model})))
              if args.second_model else None)  # fmt: skip
    settings = {name: getattr(args, name, None) for name in _MODEL_SETTINGS}
    try:
        run = run_set(directory, provider, out, strict=args.auto, only=args.only or (), drafts=args.drafts,
                      second=second, settings=settings)  # fmt: skip
    except (AnswerKeyError, MarksError, RecordError, RunMismatchError) as error:
        print(f"Refused  : {error}")
        return EXIT_REFUSED
    for line in report_lines(run):
        print(line)
    return EXIT_STOPPED if run.stopped else EXIT_DONE


def add_eval_spec_parser(subparsers: Any) -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "eval-spec",
        help="draft every brief of a locked answer-key set and grade the drafts (V2, stage 1)",
        description=(
            "Draft every brief of a locked set of answer keys, grade each draft against its key "
            "before anything is built, and report the facts right with their upper bound. Run it "
            "again to resume, or to regrade after marking facts in marks.json."
        ),
    )
    parser.add_argument("set", help="the set's folder: its keys and MANIFEST.json")
    parser.add_argument("--out", help="the run's folder (default runs/eval-spec-<set>)")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="draft as an automatic run does: stricter checks",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="KEY",
        help="grade only this key (repeatable)",
    )
    parser.add_argument("--drafts", type=int, choices=(1, 2), default=1,
                        help="draft each brief twice, and measure whether their differences find what is wrong")  # fmt: skip
    parser.add_argument(
        "--second-model", help="the model for the second draft (default: the same one)"
    )
    add_model_flags(parser, max_tokens=4_000_000, max_calls=200)
    parser.set_defaults(handler=command_eval_spec)
    return parser
