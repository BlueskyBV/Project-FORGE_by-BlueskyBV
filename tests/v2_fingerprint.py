"""The restructure's proof: every output of every program, per seed, digested (V2-stage4b-0b.md, 6; ADR-0036).

A seed's fingerprint is a digest per section of everything the programs
make from it, in the order they make it, floats by ``float.hex``:

- the generator's case: its plan, brief, items, truth and why it can't be;
- the spec checks: the numbered brief, the report (spec, solved layout,
  problems, assumptions, caveats, notes, accounting) plain and strict, the
  questions, the rendered sentences, the confirmation views, the
  comparison's features;
- the planner: the preview, the plan's document, owners and how each item
  is made, each item's constructions that apply and the next, and the
  document with each other construction that applies;
- the judge: its placement, oracle, compiled suite, expected topology and
  volume, its comparison of layouts, its unchecked, held-otherwise and
  class lists;
- the spec grading of the shape facts, against a key that asks each of them;
- the seed's mutant list, and its mutant (``seed % len``) the same way,
  with the comparison of the two drafts and the questions it asks; and the
  seed's impossible part the same way.

The guide, the JSON schema, the kind table and the capability table are
digested once a run. With ``--verdicts`` the part is built through the
build loop and judged on its B-rep and graded against the generator's own
shape, and the mutant built and judged to its first failing check, as the
exit test does (``tests/v2_exit4.py``; ADR-0036's samples).

The harness calls only entry points 4b.0b doesn't move. Each run records
the harness's own hash, the Python, NumPy and machine, and the hash seed;
``--compare`` holds one run against another: every digest equal, or the
seeds and sections that differ.

    python tests/v2_fingerprint.py --seeds sample --out runs/stage4b0b/base-h0 --workers 2
    python tests/v2_fingerprint.py --compare runs/stage4b0b/base-h0 runs/stage4b0b/base-h1
"""

from __future__ import annotations

import argparse
import dataclasses
import decimal
import enum
import fractions
import functools
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "packages")]
sys.setrecursionlimit(max(sys.getrecursionlimit(), 20_000))

#: The seed every verdict's fresh probes are drawn from (the exit test's).
PROBE_SEED = 2026
#: The fixed sample: this many of the counted seeds 0-9,999, drawn once by this seed.
SAMPLE, SAMPLE_SEED = 1000, 4_000_000_004
#: Seeds a worker process runs before a fresh one takes over.
BATCH = 20
#: A line of a worker's output that carries a record.
_RECORD = "v2_fingerprint record: "


def sample() -> list[int]:
    """The fixed 1,000-seed sample of the counted seeds, in order (the same on every run and machine)."""
    return sorted(random.Random(SAMPLE_SEED).sample(range(10_000), SAMPLE))


# ----------------------------------------------------------------------
# Canonical form
# ----------------------------------------------------------------------
#: Fields a later step added to a class, at their default (None, or no turn) wherever a part has nothing of them:
#: left out there, so a part that has nothing of them digests as it did before (1b's first move, V2-stage4b-0c.md
#: 3.3: a copy's, an item's and a place's turn, and a print's turned outline; its second: an instance's, a copy's and
#: an item's lean; its third's first step: a face's turn and the names of its axes, an item's own axes).
ADDED = frozenset({("Copy", "turn"), ("Feature", "turn"), ("Place", "turn"), ("_Print", "shape"),
                   ("Instance", "direction"), ("Copy", "lean"), ("Feature", "tilt"),
                   ("FlatFace", "turn"), ("FlatFace", "turn_sources"), ("FlatFace", "named"), ("_Flat", "turn"),
                   ("Feature", "own_axes")})  # fmt: skip


def _at_default(value: Any, f: dataclasses.Field[Any]) -> bool:
    """Whether an added field holds its default: None, or the default it was added with (0.0, ())."""
    held = getattr(value, f.name)
    return held is None or (f.default is not dataclasses.MISSING and type(held) is type(f.default) and held == f.default)


def canonical(value: Any, _stack: frozenset[int] = frozenset()) -> Any:
    """A JSON-ready form of ``value`` that two equal outputs share and two different ones don't.

    Order is kept where it is behaviour (sequences, mappings); sets are
    sorted. Floats are written by ``float.hex``. A callable is only marked:
    moving code renames functions, and what a callable makes is digested
    where it is made. Fields and attributes named with a leading underscore
    (memos, caches) and cached properties are left out.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return float.hex(value) if math.isfinite(value) else repr(value)
    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, (bytes, bytearray)):
        return {"bytes": hashlib.sha256(bytes(value)).hexdigest()}
    if isinstance(value, fractions.Fraction):
        return {"fraction": [value.numerator, value.denominator]}
    if isinstance(value, decimal.Decimal):
        return {"decimal": str(value)}
    if id(value) in _stack:
        return "<cycle>"
    stack = _stack | {id(value)}
    import numpy as np

    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        if array.dtype == object:
            return {"objects": list(array.shape),
                    "items": [canonical(v, stack) for v in array.ravel()]}  # fmt: skip
        return {"array": str(array.dtype), "shape": list(array.shape),
                "sha256": hashlib.sha256(array.tobytes()).hexdigest()}  # fmt: skip
    if isinstance(value, np.generic):
        return canonical(value.item(), stack)
    if isinstance(value, Mapping):
        return {
            "map": [
                [canonical(k, stack), canonical(v, stack)] for k, v in value.items()
            ]
        }
    if isinstance(value, (list, tuple)):
        return [canonical(v, stack) for v in value]
    if isinstance(value, (set, frozenset)):
        items = [canonical(v, stack) for v in value]
        return {
            "set": sorted(items, key=lambda x: json.dumps(x, separators=(",", ":")))
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        name = type(value).__name__
        return {"type": name,
                "fields": [[f.name, canonical(getattr(value, f.name), stack)]
                           for f in dataclasses.fields(value) if not f.name.startswith("_")
                           and not ((name, f.name) in ADDED and _at_default(value, f))]}  # fmt: skip
    if isinstance(value, type) or callable(value):
        return "<callable>"
    cls = type(value)
    if hasattr(value, "__dict__"):
        return {"type": cls.__name__,
                "attrs": [[k, canonical(v, stack)] for k, v in vars(value).items()
                          if not k.startswith("_")
                          and not isinstance(getattr(cls, k, None), functools.cached_property)]}  # fmt: skip
    slots = [
        n
        for c in cls.__mro__
        for n in getattr(c, "__slots__", ())
        if not n.startswith("_")
    ]
    if slots:
        return {"type": cls.__name__,
                "slots": [[n, canonical(getattr(value, n, None), stack)] for n in slots]}  # fmt: skip
    raise TypeError(
        f"the fingerprint has no canonical form for a {cls.__module__}.{cls.__name__}"
    )


def digest(value: Any) -> str:
    text = json.dumps(canonical(value), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# ----------------------------------------------------------------------
# One seed
# ----------------------------------------------------------------------
class _Sections:
    """A seed's digests by section, in the order made; an exception is digested by its type and message."""

    def __init__(self) -> None:
        self.digests: dict[str, str] = {}

    def __call__(self, name: str, make: Callable[[], Any]) -> Any:
        if name in self.digests:
            raise ValueError(f"the section {name} is digested twice")
        try:
            found = make()
        except Exception as error:  # what a program raises is an output too
            self.digests[name] = digest(
                {"raised": type(error).__name__, "message": str(error)}
            )
            return None
        self.digests[name] = digest(found)
        return found


def _draft(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    from forge_eval.generator import draft_of

    return draft_of(items)


def _drafted(
    out: _Sections, prefix: str, brief: str, items: Iterable[dict[str, Any]]
) -> tuple[Any, Any]:
    """Every program's output for one draft, under ``prefix``; its report and judge (None where none was made)."""
    from forge_checks.judge import Judge
    from forge_checks.place import compare_layouts
    from forge_plan.planner import _plan, preview_plan
    from forge_spec.checks import check_draft
    from forge_spec.compare import features
    from forge_spec.questions import questions
    from forge_spec.render import render
    from forge_spec.render_views import render_views
    from forge_spec.words import number_words

    items = list(items)
    numbered = out(f"{prefix}words", lambda: number_words(brief))
    if numbered is None:
        return None, None
    report = out(f"{prefix}report", lambda: check_draft(numbered, _draft(items)))
    out(
        f"{prefix}report.strict",
        lambda: check_draft(numbered, _draft(items), strict=True),
    )
    if report is None:
        return None, None
    out(f"{prefix}questions", lambda: questions(report))
    out(f"{prefix}sentences", lambda: render(report, numbered))
    out(f"{prefix}views", lambda: render_views(report))
    out(f"{prefix}features", lambda: features(report))
    out(f"{prefix}preview", lambda: _plan_outputs(preview_plan(report)))
    out(f"{prefix}grading", lambda: _shape_grades(report))
    spec, layout = report.spec, report.layout
    if spec is None or layout is None:
        return report, None
    plan = out(f"{prefix}plan", lambda: _plan(spec, layout, digest=None))
    if plan is not None:
        out(f"{prefix}plan.document", lambda: _plan_outputs(plan))
        out(f"{prefix}plan.alternatives", lambda: _alternatives(plan))
    judge = out(f"{prefix}judge", lambda: Judge.of(spec))
    if judge is not None:
        out(f"{prefix}judge.lists", lambda: (judge.kinds, judge.unchecked, judge.held_otherwise,
                                              judge.classes()))  # fmt: skip
        out(f"{prefix}judge.layouts", lambda: compare_layouts(judge.placed, layout))
    return report, judge


def _plan_outputs(plan: Any) -> Any:
    """A plan as it is written: its items and constructions by name, its gaps, and its first replay."""
    written = plan.written()
    return {"name": plan.name, "id": plan.document_id, "digest": plan.spec_digest,
            "items": [(p.key, p.item, p.kind, [(c.name, c.proof, c.prepare is not None)
                                                for c in p.constructions]) for p in plan.items],
            "gaps": plan.gaps, "document": written.document.to_json(),
            "owners": written.owners, "made": written.made, "made_by": written.made_by}  # fmt: skip


def _alternatives(plan: Any) -> Any:
    """Each planned item's constructions that apply and the next, and the document with each other one that applies."""
    found = []
    for planned in plan.items:

        def each(index: int, key: str = planned.key) -> Any:
            written = plan.written({key: index})
            return written.document.to_json(), written.made_by

        holding = plan.applying({}, planned.key)
        found.append((planned.key, holding, plan.next_choice({}, planned.key),
                      [_caught(each, i) for i in holding[1:]]))  # fmt: skip
    return found


def _caught(make: Callable[..., Any], *args: Any) -> Any:
    try:
        return make(*args)
    except Exception as error:  # an exception is an output too
        return {"raised": type(error).__name__, "message": str(error)}


def _shape_grades(report: Any) -> Any:
    """The spec grading of the shape facts, against a key that asks each of them (so every path runs)."""
    from forge_eval.keys import AnswerKey, HoleFact
    from forge_eval.spec_grade import grade_spec

    key = AnswerKey(id="fingerprint", brief="fingerprint", written_by="fingerprint",
                    independent=True, expect="verified", note="", envelope_mm=(1.0, 1.0, 1.0),
                    volume_mm3=(1.0, 2.0), through_holes=(HoleFact((0.01, 1e4), 1),),
                    inner_voids=0)  # fmt: skip
    return grade_spec(key, report)


def _held(judgement: Any) -> list[str]:
    return [
        f"{f.view}: {f.detector}: {f.what}: {f.verdict.value}: {f.why}"
        for f in judgement.held
    ]


def _built(report: Any) -> Any:
    from forge_occ.planned import build_plan
    from forge_plan.planner import _plan

    found = _plan(report.spec, report.layout, digest=None)
    built = build_plan(found)
    return built, {"made_by": dict(built.made_by), "choice": dict(built.choice),
                   "refusals": [(r.item, r.construction, str(r.error.get("message", "")))
                                for r in built.refusals],
                   "gap": None if built.gap is None else (built.gap.item, built.gap.reason)}  # fmt: skip


def _verdict(report: Any, judge: Any, truth: Any, seed: int) -> Any:
    """The part as asked, built, judged on its B-rep and graded against the generator's shape (the exit test's)."""
    from forge_checks.view import ViewProxy
    from forge_eval.grade import grade
    from forge_occ.view import BrepView
    from v2_truth_occ import build

    built, said = _built(report)
    if built.gap is not None or built.result is None:
        return said
    judgement = judge.view(ViewProxy(BrepView(built.result.shape)), "B-rep", PROBE_SEED)
    said["held"] = _held(judgement)
    said["passed"] = judgement.passed
    exact = ViewProxy(BrepView(build(truth)))
    said["graded"] = grade(truth, ViewProxy(BrepView(built.result.shape)), exact=exact,
                           seed=seed).problems()  # fmt: skip
    return said


def _mutant_verdict(judge: Any, mutant: Any) -> Any:
    """The mutant built and judged by the part's own judge, to its first failing check (the exit test's)."""
    from forge_checks.view import ViewProxy
    from forge_occ.view import BrepView

    built, said = _built(mutant)
    if built.gap is not None or built.result is None:
        return said
    said["first"] = judge.first_failure(
        ViewProxy(BrepView(built.result.shape)), PROBE_SEED
    )
    return said


def fingerprint(seed: int, *, verdicts: bool = False) -> dict[str, Any]:
    """One seed's digests, by section (see the module's docstring); the verdicts, when asked, last."""
    from forge_eval.generator import generate, impossible, mutants
    from forge_spec.compare import differences
    from forge_spec.questions import questions

    out = _Sections()
    started = time.perf_counter()
    report = judge = other = case = None
    case = out("generator", lambda: generate(seed))
    if case is not None:
        report, judge = _drafted(out, "", case.brief, case.items)
        found = out("mutants", lambda: list(mutants(case)))
        if found:
            key, mutant = found[seed % len(found)]
            out("mutant.key", lambda: key)
            other, _ = _drafted(out, "mutant.", mutant.brief, mutant.items)
            if report is not None and other is not None:
                differ = out("mutant.differences", lambda: differences(report, other))
                if differ is not None:
                    out("mutant.asked", lambda: questions(report, differ))
    bad = out("impossible", lambda: impossible(seed))
    if bad is not None:
        _drafted(out, "impossible.", bad.brief, bad.items)
    if verdicts and judge is not None:
        out("verdict", lambda: _verdict(report, judge, case.truth, seed))
        if other is not None and other.spec is not None and other.layout is not None:
            out("mutant.verdict", lambda: _mutant_verdict(judge, other))
    return {
        "seed": seed,
        "digests": out.digests,
        "seconds": round(time.perf_counter() - started, 2),
    }


def once() -> dict[str, str]:
    """What is digested once a run: the guide, the JSON schema, the kind table and the capability table."""
    from forge_checks.capabilities import SOURCES, holds, required
    from forge_spec.guide import draft_schema, instructions
    from forge_spec.schema import KINDS

    out = _Sections()
    out("guide", lambda: (instructions(), instructions(strict=True)))
    out("schema", draft_schema)
    out("kinds", lambda: KINDS)
    out("capabilities", lambda: [(s, required(s), [(k, _caught(holds, s, k)) for k in KINDS])
                                 for s in SOURCES])  # fmt: skip
    return out.digests


# ----------------------------------------------------------------------
# A run
# ----------------------------------------------------------------------
def code() -> str:
    """The digest of the packages' Python source the run imports: which code made it."""
    found = hashlib.sha256()
    root = HERE.parent / "packages"
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in path.parts:
            found.update(
                path.relative_to(root).as_posix().encode()
                + b"\0"
                + path.read_bytes()
                + b"\0"
            )
    return found.hexdigest()


def header(verdicts: bool) -> dict[str, Any]:
    import numpy

    head = {"harness": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "code": code(), "python": sys.version.split()[0], "numpy": numpy.__version__,
            "machine": f"{platform.system()} {platform.machine()}",
            "hash_seed": os.environ.get("PYTHONHASHSEED", "random"),
            "verdicts": verdicts, "once": once()}  # fmt: skip
    if verdicts:
        import OCP

        head["ocp"] = getattr(OCP, "__version__", "unknown")
    return head


def _work(seeds: list[int], verdicts: bool) -> None:
    for seed in seeds:
        print(_RECORD + json.dumps(fingerprint(seed, verdicts=verdicts)), flush=True)


def run(seeds: list[int], out: Path, workers: int, verdicts: bool) -> int:
    """Fingerprint ``seeds`` into ``out``, ``workers`` processes at a time (resumable: seeds recorded aren't run again)."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / "records.jsonl"
    done: set[int] = set()
    if path.exists():
        done = {json.loads(line)["seed"] for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()}  # fmt: skip
    head = header(verdicts)
    kept = out / "header.json"
    if kept.exists() and done and json.loads(kept.read_text(encoding="utf-8")) != head:
        raise SystemExit(
            f"{out} was begun by another harness, environment or code: start a fresh folder"
        )
    kept.write_text(json.dumps(head, indent=1), encoding="utf-8")
    todo = [s for s in seeds if s not in done]
    batches = [todo[k : k + BATCH] for k in range(0, len(todo), BATCH)]
    command = [sys.executable, str(Path(__file__).resolve())] + (
        ["--verdicts"] if verdicts else []
    )
    lock = threading.Lock()
    failed: list[tuple[list[int], int]] = []
    started = time.monotonic()
    with path.open("a", encoding="utf-8") as f:

        def slot() -> None:
            while True:
                with lock:
                    if not batches:
                        return
                    batch = batches.pop(0)
                proc = subprocess.Popen([*command, "--worker", ",".join(map(str, batch))],
                                        stdout=subprocess.PIPE, text=True)  # fmt: skip
                assert proc.stdout is not None
                for line in proc.stdout:
                    if line.startswith(_RECORD):
                        with lock:
                            f.write(line[len(_RECORD) :])
                            f.flush()
                if proc.wait() != 0:
                    with lock:
                        failed.append((batch, proc.returncode))

        threads = [threading.Thread(target=slot) for _ in range(max(1, workers))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    _, records = load(out)
    missing = sorted(set(seeds) - set(records))
    print(
        f"{len(records)} seeds recorded in {out} ({time.monotonic() - started:.0f} s this run)"
    )
    if failed or missing:
        print(
            f"workers failed: {[(b[0], b[-1], code) for b, code in failed]}; seeds missing: {missing[:20]}"
        )
        return 1
    return 0


def load(out: Path) -> tuple[dict[str, Any], dict[int, dict[str, str]]]:
    head = json.loads((out / "header.json").read_text(encoding="utf-8"))
    records: dict[int, dict[str, str]] = {}
    for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            records[r["seed"]] = r["digests"]
    return head, records


def compare(first: Path, second: Path) -> tuple[list[str], list[str]]:
    """Two runs held against each other: the differences, and how their environments differ."""
    (h1, r1), (h2, r2) = load(first), load(second)
    told = [f"{k}: {h1.get(k)} | {h2.get(k)}"
            for k in ("harness", "code", "python", "numpy", "machine", "hash_seed", "verdicts", "ocp")
            if h1.get(k) != h2.get(k)]  # fmt: skip
    found = [f"once {k}" for k in sorted(set(h1["once"]) | set(h2["once"]))
             if h1["once"].get(k) != h2["once"].get(k)]  # fmt: skip
    judged = ("verdict", "mutant.verdict")
    for seed in sorted(set(r1) & set(r2)):
        a, b = r1[seed], r2[seed]
        if h1.get("verdicts") != h2.get("verdicts"):
            # One run built and judged the parts and the other didn't: the sections both have are held.
            a = {k: v for k, v in a.items() if k not in judged}
            b = {k: v for k, v in b.items() if k not in judged}
        if list(a) != list(b):
            found.append(
                f"seed {seed}: sections {[k for k in a if k not in b]} | {[k for k in b if k not in a]}"
            )
        found += [f"seed {seed} {k}" for k in a if k in b and a[k] != b[k]]
    only = sorted(set(r1) ^ set(r2))
    if only:
        found.append(
            f"{len(only)} seeds in one run only: {only[:20]}{' ...' if len(only) > 20 else ''}"
        )
    return found, told


def _seeds(text: str) -> list[int]:
    """``sample``, ``sample:100`` (its first hundred), ``A-B`` (A to B-1), or a comma list."""
    if text.startswith("sample"):
        n = int(text.split(":")[1]) if ":" in text else SAMPLE
        return sample()[:n]
    if "-" in text and "," not in text:
        a, b = text.split("-")
        return list(range(int(a), int(b)))
    return [int(s) for s in text.split(",") if s]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seeds", default="sample:100")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--verdicts", action="store_true")
    parser.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker is not None:
        _work([int(s) for s in args.worker.split(",") if s], args.verdicts)
        return 0
    if args.compare:
        found, told = compare(*args.compare)
        for line in told:
            print(f"environment: {line}")
        for line in found[:200]:
            print(line)
        print(f"{len(found)} differences")
        return 1 if found else 0
    if args.out is None:
        parser.error("--out is needed to run")
    return run(_seeds(args.seeds), args.out, args.workers, args.verdicts)


if __name__ == "__main__":
    raise SystemExit(main())
