"""V2 stage 4: V1's 27 false passes, replayed as their wrong geometry (docs/V2-stage4.md, 14.3; tests/v2_false_passes.py).

For each: the right part, built from a V2 spec of its brief, passes that
spec's judge; the wrong part, as V1's document drew it, fails it, and what
caught it is named. The five that are no wrong shape are caught where V2
catches them: a brief that is no part and a washer nobody sized stop an
automatic run (a question; every size an assumption, each of which --auto
stops at); two shipped files, the dome's skinned STL and the rail's coarse
one, fail the judge of the file, which every file Forge releases is put
through; the steel cube shelled to its weight is a wrong shape the judge
catches, its mass left to stage 6. The end-to-end run from the briefs is
``forge eval-false-passes``, with your key.

One test per case, so that each runs in its own call where calls are timed:
``python -m unittest test_v2_false_passes.TheWrongPartsFail.test_case_07``.
"""

from __future__ import annotations

import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from forge_checks.classes import Verdict
from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_false_passes import (
    FALSE_PASSES,
    UNDRAFTED,
    WEAKER,
    FalsePass,
    ball,
    box,
    common,
)
from v2_occ import needs_occ
from v2_suite_specs import DRAFTS

RUNS = Path(__file__).resolve().parent / "fixtures" / "real_runs"
#: What catches a case that is no wrong shape, and how sure each reconstruction is, in the words used.
WHERE = {
    "judge",
    "the accounting",
    "the assumptions --auto stops at",
    "the judge of the file shipped",
}
SURE = ("sure", "fairly sure", "least sure", "weaker")


def report(case: FalsePass, *, strict: bool = False) -> SpecReport:
    b = number_words(case.brief)
    right = case.right
    return check_draft(
        b, DRAFTS[right](b) if isinstance(right, str) else right(b), strict=strict
    )


class TheList(unittest.TestCase):
    def test_twenty_seven_each_sourced(self) -> None:
        self.assertEqual([c.number for c in FALSE_PASSES], list(range(1, 28)))
        for case in (*FALSE_PASSES, *WEAKER):
            with self.subTest(case=case.number):
                self.assertTrue(case.brief and case.built and case.why and case.sources)
                self.assertTrue(case.sure.startswith(SURE), case.sure)
                self.assertIn(case.caught, WHERE)
                self.assertEqual(case.wrong is None, case.caught != "judge")
                if case.run is not None:
                    self.assertTrue((RUNS / f"{case.run}.json").is_file(), case.run)

    def test_the_least_sure_are_the_three_the_page_names(self) -> None:
        least = [c.number for c in FALSE_PASSES if c.sure.startswith("least sure")]
        self.assertEqual(least, [3, 22, 25])
        self.assertEqual(len(WEAKER) + len(UNDRAFTED), 2)

    def test_every_right_spec_checks_clean(self) -> None:
        for case in (*FALSE_PASSES, *WEAKER):
            with self.subTest(case=case.number):
                found = report(case)
                self.assertEqual(
                    [(p.kind, p.at, p.message) for p in found.problems], []
                )


class WhatIsNoWrongShape(unittest.TestCase):
    def test_a_poem_stops_an_automatic_run(self) -> None:
        """21: the brief's words go unused, and V1's placeholder cube is all assumption."""
        case = FALSE_PASSES[20]
        found = report(case, strict=True)
        self.assertTrue(found.problems)
        self.assertEqual({p.kind for p in found.problems}, {"question"})
        self.assertTrue(any("'bridges'" in p.message for p in found.problems))
        self.assertEqual(len(found.assumptions), 3)

    def test_a_washer_nobody_sized_is_all_assumption(self) -> None:
        """22: every size of V1's washer is an assumption, which an automatic run stops at and a person sees first."""
        case = FALSE_PASSES[21]
        found = report(case, strict=True)
        assumed = {a.at.split("/")[-1] for a in found.assumptions}
        self.assertLessEqual({"outer_diameter", "inner_diameter", "length"}, assumed)


def _built(case: FalsePass) -> tuple[Any, Any]:
    """The right part's judge, and the right part built from its spec."""
    from forge_checks.judge import Judge
    from forge_occ.planned import build_plan
    from forge_plan import plan
    from forge_spec.lock import lock

    confirmed = lock(report(case), number_words(case.brief), by="draft", strict=False)
    built = build_plan(plan(confirmed))
    assert built.result is not None, built.gap
    return Judge.of(confirmed.spec), built.result.shape


def _brep(shape: Any) -> Any:
    from forge_checks.view import ViewProxy
    from forge_occ.view import BrepView

    return ViewProxy(BrepView(shape))


def _file(triangles: Any, deflection: float) -> Any:
    """A mesh file as Forge reads one back: an STL of these triangles, read, said to be within ``deflection``."""
    from forge_checks.mesh import Mesh, MeshView
    from forge_checks.readers import read_stl
    from forge_checks.view import ViewProxy
    from forge_occ.export import stl_bytes

    mesh = Mesh.from_triangles(np.asarray(triangles, dtype=np.float64))
    found = read_stl(stl_bytes(mesh)).triangles
    return ViewProxy(
        MeshView(Mesh.from_triangles(found), source="mesh-file", deflection=deflection)
    )


def _triangles(shape: Any, linear: float, angular: float = 0.1) -> Any:
    from forge_occ.export import ExportTolerance, mesh_part

    meshed = mesh_part(shape, ExportTolerance(linear=linear, angular=angular))
    return meshed.mesh.vertices[meshed.mesh.faces]


@needs_occ
class TheWrongPartsFail(unittest.TestCase):
    """One test per case (made below): the right part passes its judge, the wrong one fails it, caught as said."""

    def replayed(self, case: FalsePass) -> None:
        judge, right = _built(case)
        passed = judge.view(_brep(right), "B-rep", 1)
        self.assertEqual([h.as_dict() for h in passed.held], [])
        if case.number in (23, 24):
            wrong = self.shipped_file(case, judge, right)
        else:
            assert case.wrong is not None
            shape = case.wrong()
            wrong = judge.view(_brep(shape), "B-rep", 1)
            # Judged only as far as its first FAIL, as a mutant is: one of the detectors that fail it.
            failing = {h.what.split("/")[1] if h.detector == "check" else
                       "admission" if h.detector == "capability" else h.detector
                       for h in wrong.held if h.verdict is Verdict.FAIL}  # fmt: skip
            self.assertIn(judge.first_failure(_brep(shape), 1), failing or {None})
        held = {h.what for h in wrong.held} | {h.detector for h in wrong.held}
        self.assertTrue(wrong.held, "the wrong part passed")
        self.assertLessEqual(set(case.by), held, sorted(held))

    def shipped_file(self, case: FalsePass, judge: Any, right: Any) -> Any:
        """The file V1 shipped for a right design, judged as Forge judges every file it releases."""
        from forge_cli.build import export_tolerance

        tolerance = export_tolerance(judge.suite).linear
        if case.number == 23:
            # The dome's opening drawn shut by a skin of no thickness, twice: the outer half ball closed, the inner
            # one closed the other way round, a sealed void, their flat sides on one plane.
            top = box((-40, -40, 0), (40, 40, 40))
            outer = _triangles(common(ball((0, 0, 0), 70), top), tolerance)
            inner = _triangles(common(ball((0, 0, 0), 66), top), tolerance)[:, ::-1]
            return judge.view(
                _file(np.concatenate([outer, inner]), tolerance), "dome.stl", 1
            )
        # The rail meshed coarsely (V1's 3 mm cells left its holes 7.3 to 7.7 mm for 8.2), said to be as fine as Forge
        # writes its own.
        return judge.view(_file(_triangles(right, 0.4, 0.5), tolerance), "rail.stl", 1)


def _test(case: FalsePass) -> Callable[[TheWrongPartsFail], None]:
    def test(self: TheWrongPartsFail) -> None:
        self.replayed(case)

    test.__doc__ = f"{case.number}: {case.case}: {case.built}"
    return test


for _case in (*FALSE_PASSES, *WEAKER):
    if _case.wrong is not None or _case.number in (23, 24):
        setattr(TheWrongPartsFail, f"test_case_{_case.number:02d}", _test(_case))


if __name__ == "__main__":
    unittest.main()
