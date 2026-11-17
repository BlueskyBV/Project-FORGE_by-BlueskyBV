"""Stage 4's exit test: random specs planned, built with alternatives, judged and graded (docs/V2-stage4.md, 14.1).

For each seed:

1. **The part as asked.** ``generate(seed)``: its draft read, the solver's
   layout, the judge made (:class:`forge_checks.judge.Judge`), the plan
   built through the build loop (:func:`forge_occ.planned.build_plan`), and
   every detector of the judge run on the B-rep at the suite's radius, with
   fresh probes. It passes when nothing holds it, no gap is left, and it is
   graded against the generator's own shape both ways (12.3,
   :func:`forge_eval.grade.grade`): the built part's surface where the
   truth's is, the truth's where the built part's is, every copy's box the
   same inside, and its volume the truth's made exactly by OpenCascade
   (``tests/v2_truth_occ.py``).
2. **One mutant.** The k-th leaf mutant (k the seed modulo their number),
   compiled and built the same way, judged by the original spec's judge: a
   detector must FAIL it, and judging stops at the first that does, the
   cheapest first (:meth:`forge_checks.judge.Judge.first_failure`). Whether it changes the shape is decided exactly,
   by OpenCascade: the two truths' symmetric difference has a volume.
3. **Every tenth seed** also draws ``impossible(seed)``, which must be
   turned back at the spec's reading or the solver as a brief's would be:
   CAN'T, or a question, never one of the writer's faults (docs/V2-stage4.md,
   12.1); and runs the second kernel's agreement and the three files, each
   re-opened and judged, on the part as asked.

Each seed's record is a line of ``records.jsonl`` in the output folder
(resumable: seeds recorded are not run again), and ``report.md`` sums them,
each count with its denominator and, for a count of failures, a 95% upper
bound on its rate (none in n: 3/n). The script exits 0 only when no seed
fails the exit in any of these ways (:func:`failures`).

Run it: ``python tests/v2_exit4.py --from 0 --to 10000 --workers 2``. It
runs the packages beside it, whatever else is installed, so a copy of the
tree runs as that copy. With ``--views-first`` the seeds that also run the
second kernel and the files (every :data:`EVERY` th) run before the rest, in
order: a fault in them shows on the run's first day, not spread over its
days; the records are the same either way.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, TextIO

#: This tree's own tests and packages, ahead of any installed (an editable install of another copy of
#: the tree): a run, and each of its workers, judges the code it sits beside.
_TESTS = Path(__file__).resolve().parent
sys.path[:0] = [str(_TESTS), str(_TESTS.parent / "packages")]

#: The seed every part's fresh probes are drawn from, recorded with the report.
PROBE_SEED = 2026
#: A symmetric difference smaller than this (mm³) leaves the shape as it was.
SAME_VOLUME = 1e-6
#: Farther than this (mm) from another solid's surface, a point of one's surface shows the two are different solids.
SAME_SURFACE = 1e-5
#: The most points of one solid's surface asked whether they are on another's, and how many at a time.
_STRAY_POINTS, _STRAY_BATCH = 256, 32
#: Every this many seeds also runs the impossible part, the second kernel and the files.
EVERY = 10
#: The fewest parts each pair of kinds is drawn in, over the 10,000 (docs/V2-stage4.md, 12).
FEWEST_PAIRS = 50
#: Seeds a worker process runs before a fresh one takes over (so no worker's memory creeps).
BATCH = 10
#: A worker that makes no record for this long (s) is stopped, and its seed recorded as taking too long.
SEED_LIMIT = 3600.0
#: A record's line on a worker's output: this, then the record; whatever else a library prints there is passed by.
_RECORD = "v2_exit4 record: "
#: A worker's exit code when it ends early, its other seeds to be run by a fresh process.
_FRESH = 75


def _spec(items: Iterable[dict[str, Any]]) -> Any:
    from forge_eval.generator import draft_of
    from forge_spec.draft import read_draft

    spec, problems = read_draft(draft_of(items))
    if spec is None or problems.faults:
        raise ValueError(
            f"the generated draft doesn't read: {[str(p) for p in problems.faults][:3]}"
        )
    return spec


def _built(spec: Any) -> Any:
    """The spec's plan, built through the build loop."""
    from forge_occ.planned import build_plan
    from forge_plan.planner import _plan
    from forge_spec.placement import solve

    layout = solve(spec)
    if layout.issues:
        raise ValueError(
            f"the solver has issues: {[i.message for i in layout.issues][:3]}"
        )
    found = _plan(spec, layout, digest=None)
    return found, build_plan(found)


def _held(judgement: Any) -> list[str]:
    return [
        f"{f.view}: {f.detector}: {f.what}: {f.verdict.value}: {f.why[:200]}"
        for f in judgement.held
    ]


def _graded(shape: Any, truth: Any, seed: int) -> list[str]:
    """What fails when the built part is graded against the generator's own shape both ways (12.3); none: it is that shape."""
    from forge_checks.view import ViewProxy
    from forge_eval.grade import grade
    from forge_occ.view import BrepView
    from v2_truth_occ import build

    exact = ViewProxy(BrepView(build(truth)))
    return grade(truth, ViewProxy(BrepView(shape)), exact=exact, seed=seed).problems()


def _changes_shape(one: Any, other: Any) -> bool:
    """Whether two truths are different solids: their symmetric difference has a volume (OpenCascade, exactly).

    Shown different first where that is cheap and sure: their volumes differ
    by more than the measure's own interval, or a point of either's surface
    is farther than :data:`SAME_SURFACE` from the other's (two equal solids
    have one surface). Only where neither shows it is the symmetric
    difference made: two threads of opposite hands (generated part 7858, a
    left-hand M3 thread mutated to a right-hand one) have the same volume,
    and the boolean between them ran 15 minutes and more; the seed's worker
    died of a segfault.
    """
    from forge_occ.measure import VOLUME_RELATIVE
    from forge_occ.occt import volume
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from v2_truth_occ import build

    a, b = build(one), build(other)
    va, vb = volume(a), volume(b)
    if abs(va - vb) > VOLUME_RELATIVE * max(abs(va), abs(vb), 1.0):
        return True
    if _strays(a, b) or _strays(b, a):
        return True
    return any(
        volume(BRepAlgoAPI_Cut(x, y).Shape()) > SAME_VOLUME for x, y in ((a, b), (b, a))
    )


def _strays(shape: Any, other: Any) -> bool:
    """Whether a point of ``shape``'s surface is farther than :data:`SAME_SURFACE` from ``other``'s.

    The points asked are at most :data:`_STRAY_POINTS` of its coverage at a
    fortieth of its size, spread evenly through it, a few at a time until one
    is found far: each away from a curved face costs a distance OpenCascade
    measures (7858's coverage: 42,912 points).
    Finding none shows nothing; :func:`_changes_shape` then makes the
    symmetric difference.
    """
    import numpy as np
    from forge_occ.view import BrepView

    mine = BrepView(shape)
    points = mine.coverage(max(float(max(mine.bounds().size)) / 40.0, 1e-3)).points
    if not len(points):
        return False
    asked = points[
        np.unique(np.linspace(0, len(points) - 1, _STRAY_POINTS).astype(int))
    ]
    theirs = BrepView(other)
    for start in range(0, len(asked), _STRAY_BATCH):
        batch = asked[start : start + _STRAY_BATCH]
        if not theirs.near(batch, np.full(len(batch), SAME_SURFACE)).all():
            return True
    return False


def _as_asked(seed: int, record: dict[str, Any]) -> Any:
    from forge_checks.judge import Judge
    from forge_checks.view import ViewProxy
    from forge_eval.generator import generate
    from forge_occ.view import BrepView

    case = generate(seed)
    spec = _spec(case.items)
    record["items"] = len(case.items)
    record["kinds"] = sorted({item["kind"] for item in case.items})
    started = time.perf_counter()
    judge = Judge.of(spec)
    record["seconds"]["judge"] = round(time.perf_counter() - started, 2)
    started = time.perf_counter()
    plan, built = _built(spec)
    record["seconds"]["build"] = round(time.perf_counter() - started, 2)
    record["made_by"] = dict(built.made_by)
    record["refusals"] = [
        f"{r.item}: {r.construction}: {str(r.error.get('message', ''))[:150]}"
        for r in built.refusals
    ]
    if built.gap is not None:
        record["outcome"] = "unable"
        record["why"] = f"{built.gap.item}: {built.gap.reason}"
        return None
    started = time.perf_counter()
    judgement = judge.view(ViewProxy(BrepView(built.result.shape)), "B-rep", PROBE_SEED)
    record["seconds"]["judge B-rep"] = round(time.perf_counter() - started, 2)
    held = _held(judgement)
    assert case.truth is not None
    started = time.perf_counter()
    wrong = _graded(built.result.shape, case.truth, seed)
    record["seconds"]["grade"] = round(time.perf_counter() - started, 2)
    record["graded"] = wrong
    record["held"] = held
    record["outcome"] = (
        "passed" if not held and not wrong else "held" if held else "graded wrong"
    )
    return case, spec, judge, plan, built


def _mutant(seed: int, case: Any, judge: Any, record: dict[str, Any]) -> None:
    from forge_checks.view import ViewProxy
    from forge_eval.generator import mutants
    from forge_occ.view import BrepView

    found = list(mutants(case))
    if not found:
        record["mutant"] = None
        return
    (item, leaf), mutant = found[seed % len(found)]
    entry: dict[str, Any] = {"item": item, "leaf": leaf}
    record["mutant"] = entry
    if not _changes_shape(case.truth, mutant.truth):
        entry["outcome"] = "same shape"
        return
    _, built = _built(_spec(mutant.items))
    if built.gap is not None or built.result is None:
        entry["outcome"] = "not built"
        entry["why"] = None if built.gap is None else built.gap.reason
        return
    # One FAIL turns it back: judged no further than the first, the cheapest first (13.2).
    by = judge.first_failure(ViewProxy(BrepView(built.result.shape)), PROBE_SEED)
    entry["outcome"] = "caught" if by else "survived"
    entry["by"] = [by] if by else []


def _impossible(seed: int, record: dict[str, Any]) -> None:
    from forge_eval.generator import draft_of, impossible
    from forge_spec.draft import read_draft
    from forge_spec.placement import solve

    case = impossible(seed)
    spec, problems = read_draft(draft_of(case.items))
    said = [f"fault: {p}" for p in problems.faults]
    if spec is not None and not said:
        said = [f"{i.kind}: {i.message}" for i in solve(spec).issues]
    kinds = {line.split(":")[0] for line in said}
    record["impossible"] = {
        "why": case.cant,
        "ended": "built"
        if not said
        else "fault"
        if "fault" in kinds
        else "turned back",
        "said": said[:3],
    }


def _views(
    case: Any, plan: Any, built: Any, judge: Any, record: dict[str, Any]
) -> None:
    """The second kernel and the three files, on the part as asked."""
    from forge_checks.mesh import Mesh
    from forge_checks.readers import read_3mf, read_stl
    from forge_checks.view import ViewProxy
    from forge_cli.build import export_tolerance
    from forge_occ.agreement import agree
    from forge_occ.export import (
        StepPart,
        check_step,
        file_view,
        mesh_part,
        plate_shift,
        stl_bytes,
        threemf_bytes,
        write_step,
    )
    from forge_occ.view import BrepView

    shape = built.result.shape
    entry: dict[str, Any] = {}
    record["views"] = entry
    report = agree(plan.document(built.choice), "part", exact=built.result)
    entry["agreement"] = {"holds": report.holds, "disagreements": report.disagreements,
                          "names_missing": report.names["missing"][:5],
                          "names_mismatched": report.names["mismatched"][:5],
                          "volume": report.volume, "topology": report.topology,
                          "notes": list(report.notes)}  # fmt: skip
    data = write_step([StepPart("part", shape)])
    found, _ = check_step(data, [StepPart("part", shape)])
    entry["step"] = _held(
        judge.view(
            ViewProxy(BrepView(found.parts["part"], source="step-file")),
            "STEP",
            PROBE_SEED,
        )
    )
    tolerance = export_tolerance(judge.suite)
    meshed = mesh_part(shape, tolerance)
    stl = stl_bytes(meshed.mesh, "part")
    mesh = Mesh.from_triangles(read_stl(stl).triangles)
    entry["stl"] = _held(
        judge.view(ViewProxy(file_view(mesh, tolerance)), "STL", PROBE_SEED)
    )
    shift = plate_shift(meshed.mesh)
    three = threemf_bytes(meshed.mesh, "part", shift)
    import numpy as np

    mesh = Mesh.from_triangles(read_3mf(three).triangles - np.asarray(shift))
    entry["3mf"] = _held(
        judge.view(ViewProxy(file_view(mesh, tolerance)), "3MF", PROBE_SEED)
    )
    entry["passed"] = (
        report.holds and not entry["step"] and not entry["stl"] and not entry["3mf"]
    )


def run_seed(seed: int) -> dict[str, Any]:
    """One seed's record (see the module's docstring)."""
    record: dict[str, Any] = {"seed": seed, "seconds": {}}
    started = time.perf_counter()
    try:
        made = _as_asked(seed, record)
        if made is not None:
            case, _spec, judge, plan, built = made
            _mutant(seed, case, judge, record)
            if seed % EVERY == 0:
                _views(case, plan, built, judge, record)
        if seed % EVERY == 0:
            _impossible(seed, record)
    except Exception as error:  # every fault is a record, and the run goes on
        record["outcome"] = "error"
        # numpy's own kind of MemoryError is named for numpy: every one is called a MemoryError here.
        kind = "MemoryError" if isinstance(error, MemoryError) else type(error).__name__
        record["why"] = f"{kind}: {error}"[:500]
        if isinstance(error, MemoryError):
            # What the failed work held is let go first: formatting the trace needs room too.
            traceback.clear_frames(error.__traceback__)
        try:
            record["trace"] = traceback.format_exc()[-1500:]
        except MemoryError:
            record["trace"] = "(no room left to write the trace)"
    record["seconds"]["all"] = round(time.perf_counter() - started, 2)
    return record


def _bound(failures: int, n: int) -> str:
    """A 95% upper bound on a failure rate seen ``failures`` times in ``n``: 3/n for none (the rule of three), else the normal one."""
    if not n:
        return "n/a"
    if not failures:
        return f"{3 / n:.2%}"
    p = failures / n
    return f"{min(1.0, p + 1.96 * math.sqrt(p * (1 - p) / n)):.2%}"


def failures(record: dict[str, Any]) -> list[str]:
    """Every way a seed's record fails the exit (14.1): the part not passed, its mutant surviving or not built, its impossible part not turned back, its second kernel or a file not passed. None: it passes."""
    found = []
    if record.get("outcome") != "passed":
        why = (
            record.get("why")
            or "; ".join(record.get("held", [])[:3])
            or "graded wrong: " + "; ".join(record.get("graded", [])[:2])
        )
        found.append(f"{record.get('outcome')}: {why}")
    mutant = record.get("mutant") or {}
    if mutant.get("outcome") in ("survived", "not built"):
        why = f": {mutant['why']}" if mutant.get("why") else ""
        found.append(
            f"its mutant {mutant['outcome']}: {mutant['item']} {mutant['leaf']}{why}"
        )
    impossible = record.get("impossible") or {}
    if impossible.get("ended", "turned back") != "turned back":
        said = "; ".join(impossible.get("said", []))
        found.append(
            f"its impossible part ({impossible.get('why')}) ended {impossible.get('ended')}: {said}"
        )
    views = record.get("views") or {}
    if not views.get("passed", True):
        agreement = views.get("agreement", {})
        wrong = (
            []
            if agreement.get("holds")
            else [f"the second kernel: {_disagreed(agreement)}"]
        )
        wrong += [
            f"{name}: {held[0]}"
            for name in ("step", "stl", "3mf")
            if (held := views.get(name))
        ]
        found.append(f"its views: {'; '.join(wrong)}")
    return [why[:400] for why in found]


def _disagreed(agreement: dict[str, Any]) -> str:
    """What of the second kernel's agreement didn't hold, in a line."""
    said = []
    if agreement.get("disagreements"):
        said.append(f"{agreement['disagreements']} points on different sides")
    if agreement.get("volume") and not agreement["volume"].get("holds", True):
        said.append(
            f"volume {agreement['volume'].get('exact')} against {agreement['volume'].get('implicit')}"
        )
    if agreement.get("names_missing") or agreement.get("names_mismatched"):
        said.append(
            f"names {agreement.get('names_missing', []) + agreement.get('names_mismatched', [])}"
        )
    topology = agreement.get("topology")
    if topology and not topology.get("holds", True):
        said.append(
            f"topology {topology.get('exact')} against {topology.get('implicit')}"
        )
    return "; ".join(said) or "not held"


def report(records: list[dict[str, Any]], seconds: float) -> str:
    """The exit's report, as Markdown."""
    outcomes = Counter(r.get("outcome", "?") for r in records)
    n = len(records)
    bad = [r for r in records if failures(r)]
    mutants = [r["mutant"] for r in records if r.get("mutant")]
    m_outcomes = Counter(m["outcome"] for m in mutants)
    changed = [m for m in mutants if m["outcome"] in ("caught", "survived")]
    caught_by: Counter[str] = Counter(b for m in changed for b in m.get("by", []))
    by_leaf: dict[str, Counter[str]] = {}
    for m in changed:
        by_leaf.setdefault(m["leaf"].split(".")[0], Counter())[m["outcome"]] += 1
    impossible = [r["impossible"] for r in records if r.get("impossible")]
    views = [r["views"] for r in records if r.get("views")]
    kinds: dict[str, Counter[str]] = {}
    pairs: dict[str, Counter[str]] = {}
    for r in records:
        mine = sorted(r.get("kinds", []))
        fared = "failed" if failures(r) else "passed"
        for kind in mine:
            kinds.setdefault(kind, Counter())[fared] += 1
        for i, a in enumerate(mine):
            for b in mine[i + 1 :]:
                pairs.setdefault(f"{a} + {b}", Counter())[fared] += 1
    alternatives = Counter(v for r in records for v in r.get("made_by", {}).values())
    refusals = Counter(
        x.split(": ")[1] if ": " in x else x
        for r in records
        for x in r.get("refusals", [])
    )
    times = sorted(r["seconds"].get("all", 0.0) for r in records)
    lines = [
        "# V2 stage 4: the exit test",
        "",
        f"Seeds {min(r['seed'] for r in records)} to {max(r['seed'] for r in records)} ({n} parts): "
        f"{sum(times) / 3600:.1f} hours of one worker's time in all, {seconds / 3600:.1f} hours of this run. "
        f"Fresh probes from seed {PROBE_SEED}.",
        "",
        f"The exit passes: {'yes' if not bad else f'no, {len(bad)} of {n} seeds fail it (below)'}.",
        "",
        "## Parts as asked",
        "",
        f"- passed: {outcomes['passed']} of {n} (failure rate at most {_bound(n - outcomes['passed'], n)}, 95%)",
    ]
    lines += [f"- {k}: {v}" for k, v in sorted(outcomes.items()) if k != "passed"]
    lines += ["", "## Mutants", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(m_outcomes.items())]
    survived = sum(1 for m in changed if m["outcome"] == "survived")
    lines.append(f"- surviving: {survived} of {len(changed)} that change the shape "
                 f"(rate at most {_bound(survived, len(changed))}, 95%)")  # fmt: skip
    lines += ["", "Caught, by the first detector to fail it (the checks by field, then topology, the volume, face "
              "accounting and the fresh probes):", ""]  # fmt: skip
    lines += [f"- {k}: {v}" for k, v in caught_by.most_common()]
    lines += ["", "By leaf:", "", "| Leaf | caught | survived |", "|---|---|---|"]
    lines += [
        f"| {k} | {c['caught']} | {c['survived']} |" for k, c in sorted(by_leaf.items())
    ]
    ended = sum(1 for i in impossible if i["ended"] == "turned back")
    lines += ["", "## Impossible parts", "", f"- turned back (CAN'T or a question): {ended} of {len(impossible)} "
              f"(failure rate at most {_bound(len(impossible) - ended, len(impossible))}, 95%)"]  # fmt: skip
    passed_views = sum(1 for v in views if v.get("passed"))
    lines += ["", "## The second kernel and the files", "", f"- passed: {passed_views} of {len(views)} "
              f"(failure rate at most {_bound(len(views) - passed_views, len(views))}, 95%)"]  # fmt: skip
    head = [
        "| {} | seeds | pass the exit | failure rate at most (95%) |",
        "|---|---|---|---|",
    ]

    def row(name: str, fared: Counter[str]) -> str:
        n = sum(fared.values())
        return f"| {name} | {n} | {fared['passed']} | {_bound(fared['failed'], n)} |"

    lines += ["", "## By kind", "", "Each seed counted under every kind of item it has.", "",
              head[0].format("Kind"), head[1]]  # fmt: skip
    lines += [row(k, c) for k, c in sorted(kinds.items())]
    every = sorted(kinds)
    few = sorted(f"{a} + {b}" for i, a in enumerate(every) for b in every[i + 1 :]
                 if sum(pairs.get(f"{a} + {b}", Counter()).values()) < FEWEST_PAIRS)  # fmt: skip
    lines += ["", "## By pair of kinds", "", f"Every pair of the {len(every)} kinds drawn at least {FEWEST_PAIRS} "
              f"times: {'yes' if not few else 'no; fewer: ' + ', '.join(few)}.", "",
              head[0].format("Pair"), head[1]]  # fmt: skip
    lines += [row(k, c) for k, c in sorted(pairs.items())]
    lines += ["", "## Constructions used", ""]
    lines += [f"- {k}: {v}" for k, v in alternatives.most_common()]
    if refusals:
        lines += ["", "Refused:", ""]
        lines += [f"- {k}: {v}" for k, v in refusals.most_common()]
    if times:
        lines += ["", "## Time per part", "", f"- median {times[len(times) // 2]:.1f} s, 90th percentile "
                  f"{times[int(len(times) * 0.9)]:.1f} s, most {times[-1]:.1f} s"]  # fmt: skip
    memory = sorted(r["memory MB"] for r in records if "memory MB" in r)
    if memory:
        lines += ["", "## Memory per part", "", f"- the most a worker held while making a part's record: median "
                  f"{memory[len(memory) // 2]} MB, 90th percentile {memory[int(len(memory) * 0.9)]} MB, most "
                  f"{memory[-1]} MB (seed {max(records, key=lambda r: r.get('memory MB', 0))['seed']})"]  # fmt: skip
    if bad:
        lines += ["", "## Seeds that fail the exit", ""]
        lines += [
            f"- seed {r['seed']}: {why}" for r in bad[:200] for why in failures(r)
        ]
    return "\n".join(lines) + "\n"


def work(seeds: Iterable[int]) -> None:
    """A worker process: each seed's record on its own line of the output, as soon as it is made, with the most memory the process held while it was made (sampled every tenth of a second).

    After a seed that ran out of memory it ends, with :data:`_FRESH`, and its
    other seeds go to a fresh process.
    """
    most = [0.0]

    def watch() -> None:
        while (now := _resident()) is not None:
            most[0] = max(most[0], now)
            time.sleep(0.1)

    threading.Thread(target=watch, daemon=True).start()
    for seed in seeds:
        most[0] = _resident() or 0.0
        record = run_seed(seed)
        if most[0]:
            record["memory MB"] = round(most[0])
        print(_RECORD + json.dumps(record), flush=True)
        if record.get("why", "").startswith("MemoryError"):
            raise SystemExit(
                _FRESH
            )  # whatever the failed allocation left half made, the rest start afresh


def _resident() -> float | None:
    """This process's resident memory, in MB (None where the system can't say)."""
    try:
        with open("/proc/self/statm", encoding="ascii") as fh:
            pages = int(fh.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 2**20
    except (OSError, ValueError, IndexError):
        return None


def run(
    seeds: Sequence[int],
    workers: int,
    out: TextIO,
    command: Sequence[str] = (
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
    ),
) -> None:
    """Every seed's record appended to ``out`` as it is made, by ``workers`` worker processes at once, each given :data:`BATCH` seeds (``command`` and them, as 1,2,3).

    A worker that dies (killed for want of memory) or makes no record for
    :data:`SEED_LIMIT` seconds is recorded as the fault of the seed it was on,
    and the rest of its seeds are given to the next: one part can't stop the
    run, nor hang it.
    """
    queue = list(seeds)
    lock = threading.Lock()

    def keep(record: dict[str, Any]) -> None:
        with lock:
            out.write(json.dumps(record) + "\n")
            out.flush()
            print(
                f"seed {record['seed']}: {record.get('outcome')} ({record['seconds'].get('all')} s)",
                flush=True,
            )

    def slot() -> None:
        while True:
            with lock:
                mine, queue[:BATCH] = queue[:BATCH], []
            if not mine:
                return
            child = subprocess.Popen([*command, ",".join(map(str, mine))], stdout=subprocess.PIPE,
                                     text=True, encoding="utf-8")  # fmt: skip
            assert child.stdout is not None
            stopped = threading.Event()

            def stop(
                child: subprocess.Popen[str] = child, stopped: threading.Event = stopped
            ) -> None:
                stopped.set()
                child.kill()

            made: set[int] = set()
            timer = threading.Timer(SEED_LIMIT, stop)
            timer.start()
            for line in child.stdout:
                if _RECORD in line:
                    timer.cancel()
                    record = json.loads(line[line.index(_RECORD) + len(_RECORD) :])
                    made.add(record["seed"])
                    keep(record)
                    timer = threading.Timer(SEED_LIMIT, stop)
                    timer.start()
            timer.cancel()
            code = child.wait()
            left = [seed for seed in mine if seed not in made]
            if left and not (code == _FRESH and made and not stopped.is_set()):
                keep(_lost(left[0], code, stopped.is_set()))
                left = left[1:]
            with lock:
                queue[:0] = left

    slots = [threading.Thread(target=slot) for _ in range(max(1, workers))]
    for thread in slots:
        thread.start()
    for thread in slots:
        thread.join()


def _lost(seed: int, code: int, stopped: bool) -> dict[str, Any]:
    """The record of a seed whose worker died on it, or was stopped."""
    if stopped:
        how = f"it made no record in {SEED_LIMIT:.0f} s, and was stopped"
    elif code < 0:
        how = f"it was killed by signal {-code}" + (
            " (for want of memory?)" if code == -9 else ""
        )
    else:
        how = f"it ended with code {code}"
    return {
        "seed": seed,
        "seconds": {},
        "outcome": "error",
        "why": f"its worker process died on it: {how}",
    }


def order_views_first(seeds: Iterable[int]) -> list[int]:
    """The seeds that also run the second kernel and the files (every :data:`EVERY` th), then the rest, each in order."""
    given = list(seeds)
    return [s for s in given if s % EVERY == 0] + [s for s in given if s % EVERY != 0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage 4's exit test: random specs built, judged and graded."
    )
    parser.add_argument("--from", dest="first", type=int, default=0)
    parser.add_argument("--to", dest="last", type=int, default=100)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("runs/stage4_exit"))
    parser.add_argument("--memory", type=int, default=None,
                        help="the most memory (MB) each worker may take for its data: a part that needs more is "
                             "recorded as running out of it, and can be run again with more (--again)")  # fmt: skip
    parser.add_argument("--again", action="store_true",
                        help="run again each seed in the range whose record fails the exit, its record replaced")  # fmt: skip
    parser.add_argument("--views-first", action="store_true",
                        help="run the seeds that also run the second kernel and the files first, then the rest")  # fmt: skip
    # A worker's own seeds, as 1,2,3: it runs them and prints their records.
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker is not None:
        if args.memory is not None:
            import resource

            limit = args.memory * 2**20
            resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))
        work([int(seed) for seed in args.worker.split(",")])
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "records.jsonl"
    kept = (
        [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if path.exists()
        else []
    )
    if args.again:
        kept = [
            line
            for line in kept
            if not (
                args.first <= (r := json.loads(line))["seed"] < args.last
                and failures(r)
            )
        ]
        spare = path.with_suffix(".jsonl.new")
        spare.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
        spare.replace(path)
    done = {json.loads(line)["seed"] for line in kept}
    seeds = [s for s in range(args.first, args.last) if s not in done]
    if args.views_first:
        seeds = order_views_first(seeds)
    command = [sys.executable, str(Path(__file__).resolve())]
    if args.memory is not None:
        command += ["--memory", str(args.memory)]
    started = time.time()
    with path.open("a", encoding="utf-8") as out:
        run(seeds, args.workers, out, [*command, "--worker"])
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = [r for r in records if args.first <= r["seed"] < args.last]
    (args.out / "report.md").write_text(
        report(records, time.time() - started), encoding="utf-8"
    )
    print(f"wrote {args.out / 'report.md'}")
    return 0 if not any(failures(r) for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
