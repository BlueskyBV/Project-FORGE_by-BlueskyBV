"""V2 stage 3: the stage-2 judge on the exact part (docs/V2-stage3.md, 11.2).

The detection matrix's parts, as asked and with faults, built twice from the
generator's own truth: as meshes by manifold3d (tests/v2_truth.py), as
B-reps by OpenCascade (tests/v2_truth_occ.py). The B-rep is the truth's shape
(the same side at 20,000 points, its volume within the mesh's interval, the
same topology); every detector passes each part as asked on it; and on each
fault the same detectors fail on the B-rep as on the mesh. A check that
passes one and fails the other is a defect of one of them, found here.
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np
from v2_meshes import HAVE_MANIFOLD
from v2_occ import needs_occ

try:
    from forge_checks.classes import Verdict
    from forge_checks.compiler import compile_checks
    from forge_checks.oracle import oracle
    from forge_checks.place import place
    from forge_checks.view import Side, ViewProxy
    from forge_eval.generator import generate
    from forge_occ.view import BrepView
    from v2_detection import _faults, _Judge, _mesh, _same, _spec, _view
    from v2_truth import deflection
    from v2_truth_occ import build
except (
    ImportError
):  # no OpenCascade or no manifold3d here: every class below is skipped
    pass

needs_meshes = unittest.skipUnless(
    HAVE_MANIFOLD, "manifold3d isn't installed: the meshes can't be made"
)

#: The generated parts judged as asked, and the one whose faults are.
PARTS = (0, 1)
FAULTS_OF = 0
#: How many of that part's leaf mutants are judged.
LEAVES = 3


def _judge(seed: int) -> tuple[Any, Any]:
    case = generate(seed)
    spec = _spec(case.items)
    placed = place(spec)
    part = oracle(spec, placed)
    tolerance = deflection(case.truth)
    judge = _Judge(compile_checks(spec, placed, part), part, part.expected_topology(),
                   part.volume(budget=1_000_000), tolerance)  # fmt: skip
    return case, judge


def _failed(verdicts: dict[str, tuple[Any, str]]) -> list[str]:
    return sorted(
        name for name, (verdict, _) in verdicts.items() if verdict is Verdict.FAIL
    )


@needs_occ
@needs_meshes
class TheExactPartIsTheTruths(unittest.TestCase):
    def test_sides_volume_and_topology(self) -> None:
        for seed in PARTS:
            with self.subTest(seed=seed):
                case, judge = _judge(seed)
                view = BrepView(build(case.truth))
                lo, hi = case.truth.box()
                points = np.random.default_rng(seed).uniform(
                    np.asarray(lo) - 2, np.asarray(hi) + 2, size=(20000, 3)
                )
                sides = view.classify(points)
                self.assertFalse(bool((sides == Side.ON).any()))
                sure = ~case.truth.unsure(
                    points
                )  # a thread's zone: the truth doesn't say
                np.testing.assert_array_equal(
                    (sides == Side.IN)[sure], case.truth.inside(points)[sure]
                )
                vertices, faces = _mesh(case.truth)
                mesh = _view(vertices, faces, judge.tolerance)
                exact, meshed = view.volume(), mesh.volume()
                self.assertLessEqual(meshed.lo, exact.lo)
                self.assertLessEqual(exact.hi, meshed.hi)
                ours, theirs = view.topology(), mesh.topology()
                self.assertEqual(
                    (ours.solids, ours.voids, ours.genus),
                    (theirs.solids, theirs.voids, theirs.genus),
                )


def _faults_of(seed: int) -> list[tuple[str, Any]]:
    """The part's first leaf mutants and an item taken away, each changing its shape, with a sound mesh."""
    case, judge = _judge(seed)
    found = []
    for _, what, truth, _, _ in _faults(case, LEAVES, True, ()):
        if _same(case.truth, truth):
            continue
        vertices, faces = _mesh(truth)
        if _view(vertices, faces, judge.tolerance).topology().sound:
            found.append((what, truth))
    return found


@needs_occ
@needs_meshes
class TheJudgeOnTheExactPart(unittest.TestCase):
    """Each part as asked passes every detector; each fault fails the same detectors as on the mesh (one test each, so each runs alone)."""

    def part_passes(self, seed: int) -> None:
        case, judge = _judge(seed)
        verdicts = judge.run(ViewProxy(BrepView(build(case.truth))))
        held = {
            name: why
            for name, (verdict, why) in verdicts.items()
            if verdict is not Verdict.PASS
        }
        self.assertEqual(held, {})

    def fault_is_caught_alike(self, k: int) -> None:
        _, judge = _judge(FAULTS_OF)
        faults = _faults_of(FAULTS_OF)
        self.assertGreater(len(faults), k)
        what, truth = faults[k]
        vertices, faces = _mesh(truth)
        exact = _failed(judge.run(ViewProxy(BrepView(build(truth)))))
        self.assertTrue(exact, f"no detector failed {what}")
        self.assertEqual(
            exact, _failed(judge.run(_view(vertices, faces, judge.tolerance))), what
        )

    def test_the_first_part_as_asked(self) -> None:
        self.part_passes(PARTS[0])

    def test_the_second_part_as_asked(self) -> None:
        self.part_passes(PARTS[1])

    def test_a_first_fault(self) -> None:
        self.fault_is_caught_alike(0)

    def test_a_second_fault(self) -> None:
        self.fault_is_caught_alike(1)

    def test_a_third_fault(self) -> None:
        self.fault_is_caught_alike(2)


if __name__ == "__main__":
    unittest.main()
