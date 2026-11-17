"""The detection matrix and the false-hold rate, on generated parts (docs/V2-stage2.md, 8.3).

For each generated part, the part as asked and its faults are built from the
generator's own truth (tests/v2_truth.py), and every detector the judge has
is run on each: every compiled check (by kind), face accounting, the
topology and volume counts, and fresh probes. Reported, each with its
denominator:

- the **false-hold rate**: the parts as asked that any detector doesn't
  pass (a FAIL, or an INCONCLUSIVE: either holds a correct part);
- the **detection matrix**: for each class of fault, how many of them each
  detector failed, how many any did, and which got past them all.

The faults are a mutant per leaf (the generator's, :func:`~forge_eval.generator.mutants`:
one value moved beyond its tolerance, a count one off, a choice the other
way, an item on another face, through made blind), an item taken away, and
the whole part moved a twentieth of a millimetre, scaled by 1.001,
mirrored and turned. A fault that leaves the shape as it was (a hole
through moved to its far face; a part symmetric under the transform) is
no fault, and is left out.

Run it as a script (``python tests/v2_detection.py --parts 30``) to write the
report; ``tests/test_v2_eval_detection.py`` runs it on a part or two.
"""

from __future__ import annotations

import argparse
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from forge_checks.accounting import account_faces
from forge_checks.classes import Verdict
from forge_checks.compiler import CheckSuite, compile_checks
from forge_checks.measure import Probe
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import place
from forge_checks.probes import draw
from forge_checks.topology import judge_topology, judge_volume
from forge_checks.view import ViewProxy
from forge_eval.generator import Case, draft_of, generate, mutants, render
from forge_eval.truth import Truth
from forge_spec.draft import read_draft
from forge_units import Interval
from v2_meshes import exported
from v2_truth import build, deflection

__all__ = ["Report", "judge_part", "main"]

#: The seed fresh probes are drawn from, recorded with the report.
PROBE_SEED = 2026
#: At most this many leaf mutants per part, spread over its items.
LEAVES = 12
#: The whole-part transforms tried: each one's name, the transform and its inverse, and whether it mirrors.
_STEP = np.array([0.05, 0.0, 0.0])
_MIRROR = np.array([-1.0, 1.0, 1.0])


def _turn(points: Any) -> Any:
    return np.column_stack([-points[:, 1], points[:, 0], points[:, 2]])


TRANSFORMS: dict[str, tuple[Callable[[Any], Any], Callable[[Any], Any], bool]] = {
    "moved 0.05 mm": (lambda p: p + _STEP, lambda p: p - _STEP, False),
    "scaled by 1.001": (lambda p: p * 1.001, lambda p: p / 1.001, False),
    "mirrored": (lambda p: p * _MIRROR, lambda p: p * _MIRROR, True),
    "turned 90 degrees": (_turn, lambda p: _turn(_turn(_turn(p))), False),
}  # fmt: skip

#: The detectors, in the report's order after the check kinds.
WHOLE = ("face accounting", "topology", "volume", "fresh probes")


@dataclass
class Report:
    """What a run found: the parts as asked and what held them, and each fault class's catches."""

    parts: int = 0
    unsound: int = 0
    held: list[tuple[int, str]] = field(default_factory=list)
    faults: Counter[str] = field(default_factory=Counter)
    caught: dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    any_caught: Counter[str] = field(default_factory=Counter)
    inconclusive_only: list[tuple[int, str, str]] = field(default_factory=list)
    missed: list[tuple[int, str, str]] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    kinds: set[str] = field(default_factory=set)

    def render(self, seconds: float) -> str:
        """The report as Markdown."""
        columns = sorted(self.kinds) + list(WHOLE)
        lines = [
            "# V2 stage 2: the detection matrix and the false-hold rate",
            "",
            "Written by `python tests/v2_detection.py` (docs/V2-stage2.md, 8.3), from"
            f" generated parts 0 to {self.parts + self.unsound - 1}, in {seconds / 60:.0f} minutes."
            f" Fresh probes drawn from seed {PROBE_SEED}.",
            "",
            "## False holds",
            "",
            f"{len(self.held)} of {self.parts} parts as asked held"
            f" ({self.unsound} more skipped: the mesh library made their meshes unsoundly).",
            "",
        ]
        lines += [f"- part {seed}: {why}" for seed, why in self.held]
        lines += [
            "",
            "## Detection",
            "",
            "Each cell: how many of the faults in its row the detector failed. A",
            "fault is held when any detector fails it; one only inconclusive is",
            "held too, and listed.",
            "",
            "| Fault | " + " | ".join(columns) + " | held | of |",
            "|---|" + "---|" * (len(columns) + 2),
        ]
        for name in sorted(self.faults):
            row = [str(self.caught[name][c]) for c in columns]
            lines.append(
                f"| {name} | " + " | ".join(row)
                + f" | {self.any_caught[name]} | {self.faults[name]} |"
            )  # fmt: skip
        total, held = sum(self.faults.values()), sum(self.any_caught.values())
        lines += ["", f"{held} of {total} faults held by a FAIL."]
        if self.inconclusive_only:
            lines += ["", "Held only as inconclusive:", ""]
            lines += [f"- part {s}, {f}: {w}" for s, f, w in self.inconclusive_only]
        lines += [
            "",
            "Got past every detector:"
            if self.missed
            else "None got past every detector.",
            "",
        ]
        lines += [f"- part {s}, {f}: {w}" for s, f, w in self.missed]
        if self.skipped:
            lines += [
                "",
                "Left out (the same shape as the part asked for, or an unsound mesh):",
                "",
            ]
            lines += [f"- {name}: {n}" for name, n in sorted(self.skipped.items())]
        # A list left empty leaves no blank lines behind it.
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)) + "\n"


def _spec(items: tuple[dict[str, Any], ...]) -> Any:
    spec, problems = read_draft(draft_of(items))
    assert spec is not None and not problems.faults, [str(p) for p in problems.faults]
    return spec


def _mesh(truth: Truth) -> tuple[Any, Any]:
    return exported(build(truth))


def _view(vertices: Any, faces: Any, tolerance: float) -> ViewProxy:
    return ViewProxy(
        MeshView(Mesh(vertices, faces), source="mesh-file", deflection=tolerance)
    )


def _same(
    one: Truth, other: Truth, inverse: Callable[[Any], Any] | None = None
) -> bool:
    """Whether two parts are one shape: the same side at 20,000 points round both, seeded (``inverse`` maps the second's points back)."""
    lo1, hi1 = one.box()
    lo2, hi2 = other.box()
    lo, hi = np.minimum(lo1, lo2) - 2, np.maximum(hi1, hi2) + 2
    points = np.random.default_rng(0).uniform(lo, hi, size=(20000, 3))
    back = points if inverse is None else inverse(points)
    sure = ~one.unsure(points) & ~other.unsure(
        back
    )  # a thread's zone: the truth doesn't say
    return bool(np.array_equal(one.inside(points)[sure], other.inside(back)[sure]))


@dataclass(frozen=True)
class _Judge:
    """One part as asked, as the judge sees it: its checks, its shape, what it should count and weigh, its fresh probes."""

    suite: CheckSuite
    part: Oracle
    topology: Any
    volume: Interval
    tolerance: float

    def run(self, view: ViewProxy) -> dict[str, tuple[Verdict, str]]:
        """Every detector's verdict on a built part, and why (its first failing reason)."""
        found: dict[str, tuple[Verdict, str]] = {}

        def note(name: str, verdict: Verdict, why: str) -> None:
            old = found.get(name)
            rank = {Verdict.PASS: 0, Verdict.INCONCLUSIVE: 1, Verdict.FAIL: 2}
            if old is None or rank[verdict] > rank[old[0]]:
                found[name] = (verdict, why)

        accounting = account_faces(self.part, view, 1.0)
        note("face accounting", accounting.verdict,
             str(accounting.misses[0].why) if accounting.misses else "")  # fmt: skip
        topology = judge_topology(self.topology, view.topology())
        note("topology", topology.verdict, str(topology.findings[:1]))
        note("volume", judge_volume(self.volume, view.volume()).verdict, "")
        probes = draw(self.part, PROBE_SEED, self.tolerance)
        for evidence in probes.run(view, self.tolerance):
            note("fresh probes", evidence.verdict, evidence.reason)
        probe = Probe(view, self.part, self.suite.resolution)
        for check in self.suite.checks:
            evidence = check.run(probe)
            note(check.kind, evidence.verdict, f"{check.id}: {evidence.reason}")
        return found


def _faults(
    c: Case, leaves: int, taken: bool, transforms: tuple[str, ...]
) -> Iterator[tuple[str, str, Truth, Callable[[Any], Any] | None, bool]]:
    """Each fault of a part: its class, what it is, its truth, and for a transform, the transform and whether it mirrors."""
    found = list(mutants(c)) if leaves else []
    for (item, leaf), mutant in found[:: max(1, len(found) // max(leaves, 1))][:leaves]:
        assert mutant.truth is not None
        name = (
            "leaf: " + leaf.split(".")[0]
            if not leaf.startswith("place.pattern")
            else "leaf: pattern"
        )
        yield name, f"{item} {leaf}", mutant.truth, None, False
    hosts = {f.on[0] for f in c.plan if f.on is not None}
    for f in c.plan[1:] if taken else ():
        if f.id not in hosts:
            gone = render(tuple(g for g in c.plan if g.id != f.id))
            assert gone.truth is not None
            yield "an item taken away", f.id, gone.truth, None, False
            break
    assert c.truth is not None
    for name in transforms:
        forward, _, mirrors = TRANSFORMS[name]
        yield name, name, c.truth, forward, mirrors


def judge_part(
    seed: int,
    report: Report,
    *,
    leaves: int = LEAVES,
    taken: bool = True,
    transforms: tuple[str, ...] = tuple(TRANSFORMS),
) -> None:
    """Judge one generated part as asked and its faults (up to ``leaves`` leaf mutants, an item ``taken`` away, the ``transforms``), adding to ``report``."""
    c = generate(seed)
    assert c.truth is not None
    spec = _spec(c.items)
    placed = place(spec)
    part = oracle(spec, placed)
    tolerance = deflection(c.truth)
    judge = _Judge(compile_checks(spec, placed, part), part, part.expected_topology(),
                   part.volume(budget=1_000_000), tolerance)  # fmt: skip
    report.kinds |= {check.kind for check in judge.suite.checks}
    vertices, faces = _mesh(c.truth)
    view = _view(vertices, faces, tolerance)
    if not view.topology().sound:
        report.unsound += 1
        return
    report.parts += 1
    for name, (verdict, why) in sorted(judge.run(view).items()):
        if verdict is not Verdict.PASS:
            report.held.append((seed, f"{name} {verdict.value}: {why}"))
    for name, what, truth, transform, mirrors in _faults(c, leaves, taken, transforms):
        if transform is None:
            if _same(c.truth, truth):
                report.skipped[name] += 1
                continue
            fault_vertices, fault_faces = _mesh(truth)
        else:
            inverse = TRANSFORMS[name][1]
            if _same(c.truth, c.truth, inverse):
                report.skipped[name] += 1
                continue
            fault_vertices = transform(vertices)
            fault_faces = faces[:, ::-1] if mirrors else faces
        built = _view(fault_vertices, fault_faces, tolerance)
        if not built.topology().sound:
            report.skipped[name] += 1
            continue
        report.faults[name] += 1
        verdicts = judge.run(built)
        failed = [d for d, (v, _) in verdicts.items() if v is Verdict.FAIL]
        for detector in failed:
            report.caught[name][detector] += 1
        if failed:
            report.any_caught[name] += 1
        elif any(v is Verdict.INCONCLUSIVE for v, _ in verdicts.values()):
            why = next(w for v, w in verdicts.values() if v is Verdict.INCONCLUSIVE)
            report.inconclusive_only.append((seed, what, why))
        else:
            report.missed.append((seed, what, "every detector passed it"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The detection matrix and the false-hold rate, on generated parts."
    )
    parser.add_argument("--parts", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("docs/V2-detection.md"))
    args = parser.parse_args(argv)
    report = Report()
    start = time.time()
    for seed in range(args.parts):
        judge_part(seed, report)
        print(f"part {seed}: {sum(report.faults.values())} faults, {len(report.held)} held parts,"
              f" {len(report.missed)} missed, {time.time() - start:.0f} s", flush=True)  # fmt: skip
    args.out.write_text(report.render(time.time() - start))
    print(f"wrote {args.out}")
    return 0 if not report.held and not report.missed else 1


if __name__ == "__main__":
    raise SystemExit(main())
