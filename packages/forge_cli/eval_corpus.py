"""``forge eval-corpus`` and ``forge eval-false-passes``: the spec writer on recorded briefs, every draft built with no further model call (V2, stage 4; docs/V2-stage4.md, 14.2 and 14.3).

``eval-corpus`` drafts every brief it is given (validation/SUITE.md's 92, the
recorded runs' briefs, any file of briefs), as ``forge spec`` drafts one,
and builds each that is determinate, as ``forge build`` builds a spec
locked as a draft. ``eval-false-passes`` does the same for V1's 27 false
passes (validation/false_passes.json: each brief with its right spec, the
answer key), drafting as an automatic run does (--auto), and judges each
part it releases against its key.

For each brief, its own folder holds the model's answer, the draft read
from it, its problems, the spec in fixed wording and every model call, and
last ``record.json``. Running again replays what is recorded at no cost:
a brief with a record is never drafted twice, only read, checked and built
again. ``ledger.jsonl`` says what happened to each brief, in order;
``report.md`` what the run found.

What a brief ends as:

- **refused**: the writer couldn't clear its own faults;
- **CAN'T**, **UNABLE**, **faults**, **questions**: its draft's problems,
  the most final first: the part can't be made, Forge can't make it yet,
  the draft as recorded reads wrong now (the writer's to fix: drafted by an
  earlier Forge), or a person must answer;
- **stops for a person**: under --auto, a draft with assumptions;
- else it is locked as a draft and built: the build's ending (BUILT TO
  DRAFT, HELD, UNABLE, CAN'T; or an error, Forge's own).

A false pass is **caught** unless its part is released (BUILT TO DRAFT)
and its key's judge fails it: a run that stopped to ask, ended otherwise,
or built a part its key passes has caught it. One not caught is V1's false
pass again, and the run's exit code says so.

A model error every brief would meet (the key, the budget) stops the run,
keeping every brief done; one that may pass (a dropped connection) is noted
and the brief is left for the next run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from forge_models import (
    AuthenticationError,
    BudgetExceededError,
    CancelledError,
    ConfigurationError,
    ModelError,
    Provider,
)
from forge_roles.base import RepairExhaustedError
from forge_roles.spec_writer import write_spec
from forge_spec import NumberedBrief, number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.lock import lock
from forge_spec.render import render
from forge_spec.wire import to_wire

from .design import build_provider
from .spec import add_model_flags, priced

__all__ = [
    "Brief",
    "Ended",
    "add_eval_corpus_parsers",
    "corpus_briefs",
    "false_pass_briefs",
    "run_briefs",
]

EXIT_DONE = 0
EXIT_REFUSED = 1
EXIT_STOPPED = 2
#: A false pass not caught: V1's wrong part released again.
EXIT_NOT_CAUGHT = 3

#: Model errors every brief would meet: they stop the run.
_STOPS = (AuthenticationError, BudgetExceededError, CancelledError, ConfigurationError)
#: Where the suite's briefs are, and the false passes' keys, from the repository's root.
SUITE = Path("validation") / "SUITE.md"
RUNS = Path("tests") / "fixtures" / "real_runs"
FALSE_PASSES = Path("validation") / "false_passes.json"
#: What a released part ends as.
RELEASED = ("VERIFIED", "VERIFIED EXCEPT", "BUILT TO DRAFT")

Say = Callable[[str], None]


@dataclass(frozen=True)
class Brief:
    """One brief to draft: its id (a folder's name) and text; a false pass's key, its right spec's draft (None: the brief has no right part, so any part released is wrong)."""

    id: str
    text: str
    title: str = ""
    key: dict[str, Any] | None = None
    false_pass: bool = False


@dataclass(frozen=True)
class Ended:
    """What one brief ended as (see the module's docstring), and for a false pass whether it was caught."""

    id: str
    ending: str
    why: str
    drafted: bool
    caught: bool | None = None


# ----------------------------------------------------------------------
# The briefs
# ----------------------------------------------------------------------
_ENTRY = re.compile(
    r"\*\*(?P<id>[A-Z]\d\d) — (?P<title>[^*]+)\*\*[^\n]*\n> (?P<brief>.+)"
)


def _slug(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def corpus_briefs(sources: Iterable[Path]) -> list[Brief]:
    """Every brief in the sources, each once, in order: a suite's markdown (its ``**ID — title**`` entries, or any ``> `` line), a recorded run's JSON (its ``brief``), a text file (a brief a line), or a folder of these."""
    found: list[Brief] = []
    seen: set[str] = set()

    def add(id_: str, text: str, title: str = "") -> None:
        text = text.strip()
        if text and text not in seen:
            seen.add(text)
            found.append(Brief(re.sub(r"[^A-Za-z0-9_.-]", "_", id_), text, title))

    for source in sources:
        paths = sorted(source.rglob("*")) if source.is_dir() else [source]
        for path in paths:
            if path.suffix == ".md":
                content = path.read_text(encoding="utf-8")
                entries = list(_ENTRY.finditer(content))
                for m in entries:
                    add(m["id"], m["brief"], m["title"].strip())
                if not entries:
                    for line in content.splitlines():
                        if line.startswith("> "):
                            add(_slug(line[2:].strip()), line[2:])
            elif path.suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("brief"), str):
                    add(path.stem, data["brief"])
            elif path.suffix == ".txt":
                for line in path.read_text(encoding="utf-8").splitlines():
                    add(_slug(line.strip()), line)
    return found


def false_pass_briefs(path: Path) -> list[Brief]:
    """V1's false passes, each with its key: validation/false_passes.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Brief(f"fp{case['number']:02d}", case["brief"], case["case"], case["key"], True)
        for case in data
    ]


# ----------------------------------------------------------------------
# A run
# ----------------------------------------------------------------------
def run_briefs(briefs: Sequence[Brief], provider: Provider | None, out: Path, *, strict: bool,
               say: Say = print) -> tuple[list[Ended], str]:  # fmt: skip
    """Draft (or replay), check and build every brief; what each ended as, and what stopped the run ("" if nothing did).

    ``provider`` may be None to replay only: a brief with no record is then
    left for a run with a model. A model error is said by its code and
    message; its details (the answers refused before it, their problems) go
    to the ledger. The report is written however the run ends.
    """
    ended: list[Ended] = []
    for brief in briefs:
        folder = out / brief.id
        try:
            found = _one(brief, provider, folder, strict)
        except _STOPS as error:
            _note(out, brief.id, "stopped", error=_error_record(error))
            stopped = f"{brief.id}: {_said(error)}"
            say(f"Stopped  : {stopped}")
            _write_report(out, briefs, ended, strict, stopped=stopped)
            return ended, stopped
        except ModelError as error:
            _note(out, brief.id, "interrupted", error=_error_record(error))
            say(f"Left     : {brief.id}: {_said(error)}")
            continue
        if found is None:
            continue
        ended.append(found)
        _note(out, brief.id, "ended", **asdict(found))
        mark = (
            ""
            if found.caught is None
            else ("  caught" if found.caught else "  NOT CAUGHT")
        )
        say(f"{brief.id:9s}: {found.ending}{mark}: {found.why}")
    _write_report(out, briefs, ended, strict)
    return ended, ""


def _said(error: ModelError) -> str:
    """A model error in one line: its code and message, not the details it keeps for the record."""
    return f"[{error.code}] {error.message}"


def _error_record(error: ModelError) -> dict[str, Any]:
    """A model error as the ledger keeps it: its kind, code, message and every detail."""
    return {"type": type(error).__name__, **error.as_dict()}


def _one(
    brief: Brief, provider: Provider | None, folder: Path, strict: bool
) -> Ended | None:
    numbered = number_words(brief.text)
    record = folder / "record.json"
    drafted = not record.is_file()
    if drafted:
        if provider is None:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        try:
            result = write_spec(provider, numbered, strict=strict)
        except RepairExhaustedError as error:
            _write(folder, "refused.json", error.as_dict())
            _write(folder, "record.json", {"refused": True, "brief": brief.text})
            return _ended(
                brief, "refused", "the writer couldn't clear its own faults", True
            )
        answer = result.responses[-1].structured if result.responses else None
        _write(folder, "calls.json", result.as_dict())
        _write(folder, "answer.json", answer)
        _write(
            folder, "record.json", {"brief": brief.text, "attempts": result.attempts}
        )
    elif json.loads(record.read_text(encoding="utf-8")).get("refused"):
        return _ended(
            brief, "refused", "the writer couldn't clear its own faults", False
        )
    answer = json.loads((folder / "answer.json").read_text(encoding="utf-8"))
    if answer is None:
        return _ended(brief, "refused", "the writer gave no answer", drafted)
    report = check_draft(numbered, answer, strict=strict)
    if report.spec is not None:
        _write(folder, "draft.json", to_wire(report.spec))
        (folder / "spec.txt").write_text(
            render(report, numbered).text() + "\n", encoding="utf-8"
        )
    _write(folder, "problems.json", [asdict(p) for p in report.problems])
    kinds = {p.kind for p in report.problems}
    for kind, ending in (
        ("cant", "CAN'T"),
        ("unable", "UNABLE"),
        ("fault", "faults"),
        ("question", "questions"),
    ):
        if kind in kinds:
            first = next(p for p in report.problems if p.kind == kind)
            return _ended(brief, ending, first.message, drafted)
    if strict and report.assumptions:
        return _ended(brief, "stops for a person", f"{len(report.assumptions)} assumption(s), the first: "
                      f"{report.assumptions[0].message}", drafted)  # fmt: skip
    return _built(brief, numbered, report, folder, strict, drafted)


def _built(brief: Brief, numbered: NumberedBrief, report: SpecReport, folder: Path, strict: bool,
           drafted: bool) -> Ended:  # fmt: skip
    from .build import run_build
    from .spec import _write_confirmed

    confirmed = lock(report, numbered, by="draft", strict=strict)
    run = folder / "run"
    _write_confirmed(run, confirmed, None)
    said: list[str] = []
    out = folder / "build"
    if out.exists():
        out = folder / f"build-{time.strftime('%Y%m%dT%H%M%S')}"
    # Locked as a draft: no person's seal to read.
    run_build(run, out=out, sealer=None, say=said.append, seed=1, formats=("stl",))
    (folder / "build.txt").write_text("\n".join(said) + "\n", encoding="utf-8")
    if not (
        out / "verdict.json"
    ).is_file():  # Forge's own error stopped the build: record/error.json says what
        error = json.loads((out / "record" / "error.json").read_text(encoding="utf-8"))
        return _ended(brief, "error", f"{error['error']}: {error['message']}", drafted)
    verdict = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    ending = str(verdict["ending"])
    why = (
        "; ".join(str(h.get("why", h)) for h in verdict.get("held", [])[:2])
        or "every check passed on every view"
    )
    if not brief.false_pass or ending not in RELEASED:
        return _ended(brief, ending, why, drafted)
    if brief.key is None:
        return Ended(
            brief.id,
            ending,
            "released, where the brief has no right part",
            drafted,
            False,
        )
    held = _judged_by_key(brief, confirmed)
    if held:
        return Ended(
            brief.id,
            ending,
            f"released, and its key fails it: {held[0]}",
            drafted,
            False,
        )
    return Ended(
        brief.id,
        ending,
        "released, and its key passes it: the right part",
        drafted,
        True,
    )


def _judged_by_key(brief: Brief, confirmed: Any) -> list[str]:
    """What the key's judge holds the built part for (none: the right part)."""
    from forge_checks.judge import Judge
    from forge_checks.view import ViewProxy
    from forge_occ.planned import build_plan
    from forge_occ.view import BrepView
    from forge_plan import plan

    assert brief.key is not None
    numbered = number_words(brief.text)
    key = lock(check_draft(numbered, brief.key), numbered, by="draft", strict=False)
    built = build_plan(plan(confirmed))
    assert built.result is not None
    judged = Judge.of(key.spec).view(
        ViewProxy(BrepView(built.result.shape)), "B-rep", 1
    )
    return [f"{h.what}: {h.why}" for h in judged.held]


def _ended(brief: Brief, ending: str, why: str, drafted: bool) -> Ended:
    """A brief that ended before release: a false pass so ended is caught (the run stopped, or ended otherwise)."""
    return Ended(brief.id, ending, why, drafted, True if brief.false_pass else None)


def _write(folder: Path, name: str, content: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(content, indent=2, ensure_ascii=False, default=str) + "\n",
                               encoding="utf-8")  # fmt: skip


def _note(out: Path, key: str, event: str, **detail: Any) -> None:
    out.mkdir(parents=True, exist_ok=True)
    line = {
        "key": key,
        "event": event,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **detail,
    }
    with (out / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
        ledger.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def report_lines(
    briefs: Sequence[Brief], ended: Sequence[Ended], strict: bool, *, stopped: str = ""
) -> list[str]:
    """What the run found: each ending's count, the false passes caught, what stopped the run, and each brief's line."""
    counts: dict[str, int] = {}
    for e in ended:
        counts[e.ending] = counts.get(e.ending, 0) + 1
    lines = [f"Briefs   : {len(briefs)}, {len(ended)} ended ({sum(e.drafted for e in ended)} drafted this run, "
             f"{sum(not e.drafted for e in ended)} replayed){', as --auto' if strict else ''}"]  # fmt: skip
    lines += [
        f"  {ending}: {n}"
        for ending, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    keyed = [e for e in ended if e.caught is not None]
    if keyed:
        missed = [e for e in keyed if not e.caught]
        lines.append(f"False passes: {len(keyed) - len(missed)} of {len(keyed)} caught" +
                     (f"; NOT CAUGHT: {', '.join(e.id for e in missed)}" if missed else ""))  # fmt: skip
    if stopped:
        lines.append(f"Stopped  : {stopped}. Run it again to go on.")
    titles = {b.id: b.title for b in briefs}
    lines += ["", *(f"- {e.id}{f' ({titles[e.id]})' if titles.get(e.id) else ''}: {e.ending}"
                    f"{'' if e.caught is None else (', caught' if e.caught else ', NOT CAUGHT')}: {e.why}"
                    for e in ended)]  # fmt: skip
    return lines


def _write_report(out: Path, briefs: Sequence[Brief], ended: Sequence[Ended], strict: bool, *,
                  stopped: str = "") -> None:  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    text = (
        "# What the run found\n\n"
        + "\n".join(report_lines(briefs, ended, strict, stopped=stopped))
        + "\n"
    )
    (out / "report.md").write_text(text, encoding="utf-8")


# ----------------------------------------------------------------------
# The commands
# ----------------------------------------------------------------------
def command_eval_corpus(args: argparse.Namespace) -> int:
    sources = [Path(s) for s in args.sources] or [
        p for p in (SUITE, RUNS) if p.exists()
    ]
    briefs = corpus_briefs(sources)
    if args.only:
        briefs = [b for b in briefs if b.id in set(args.only)]
    return _command(
        args, briefs, Path(args.out or Path("runs") / "corpus"), strict=args.auto
    )


def command_eval_false_passes(args: argparse.Namespace) -> int:
    keys = Path(args.keys)
    if not keys.is_file():
        print(f"Refused  : no false passes' keys at {keys}")
        return EXIT_REFUSED
    briefs = false_pass_briefs(keys)
    if args.only:
        briefs = [b for b in briefs if b.id in set(args.only)]
    return _command(
        args, briefs, Path(args.out or Path("runs") / "false_passes"), strict=True
    )


def _command(
    args: argparse.Namespace, briefs: list[Brief], out: Path, *, strict: bool
) -> int:
    provider = None if args.replay else priced(build_provider(args))
    if provider is not None:
        info = provider.info
        remote = "  (remote: the briefs leave this machine)" if info.is_remote else ""
        print(f"Provider : {info.name} / {info.model}{remote}")
    print(f"Briefs   : {len(briefs)}")
    print(f"Run      : {out}")
    ended, stopped = run_briefs(briefs, provider, out, strict=strict)
    for line in report_lines(briefs, ended, strict, stopped=stopped):
        print(line)
    if any(e.caught is False for e in ended):
        return EXIT_NOT_CAUGHT
    return EXIT_STOPPED if stopped else EXIT_DONE


def add_eval_corpus_parsers(subparsers: Any) -> None:
    corpus = subparsers.add_parser(
        "eval-corpus",
        help="draft every recorded brief and build each determinate draft (V2, stage 4)",
        description=("Draft every brief of the sources (default: validation/SUITE.md and the recorded runs) as "
                     "forge spec does, and build each draft with nothing left to settle as forge build does, "
                     "with no further model call. Run it again to replay what is recorded at no cost."),
    )  # fmt: skip
    corpus.add_argument(
        "sources",
        nargs="*",
        help="suite markdown, recorded runs' JSON, text files of briefs, or folders",
    )
    corpus.add_argument("--out", help="the run's folder (default runs/corpus)")
    corpus.add_argument(
        "--auto",
        action="store_true",
        help="draft as an automatic run does: stricter checks",
    )
    _common(corpus)
    corpus.set_defaults(handler=command_eval_corpus)
    passes = subparsers.add_parser(
        "eval-false-passes",
        help="draft V1's 27 false passes as an automatic run would, build them, judge them by their keys (V2, stage 4)",
        description=("Draft each of V1's false passes from its brief under --auto, build what locks, and judge "
                     "each part released against its key: caught unless a wrong part is released."),
    )  # fmt: skip
    passes.add_argument(
        "--keys",
        default=str(FALSE_PASSES),
        help="the keys (default validation/false_passes.json)",
    )
    passes.add_argument("--out", help="the run's folder (default runs/false_passes)")
    _common(passes)
    passes.set_defaults(handler=command_eval_false_passes)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--only", action="append", metavar="ID", help="only this brief (repeatable)"
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="call no model: replay what is recorded, leave the rest",
    )
    add_model_flags(parser, max_tokens=8_000_000, max_calls=400)
