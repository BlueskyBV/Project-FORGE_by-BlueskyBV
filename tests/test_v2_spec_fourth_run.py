"""V2: what the corpus's fourth run found (docs/V2-stage4.md, 14.10).

- **A ball's crossings were thrown away:** A03, three balls fused, drawn as
  one turned outline, built right, and Forge stopped on its own error
  before judging it: no grid line along the balls met them, and their voids
  couldn't be counted. A ball's quartic is a square, its roots double; the
  root finder found them, and Newton's method, its slope there rounding
  alone, threw them 0.05 mm away. A step is now taken only where it brings
  the quartic nearer zero.
- **An angle an outline is drawn at is one of its sizes:** the turned block,
  drafted again, was drawn as a rectangle turned 30 degrees, and "30" was
  asked about. An outline is drawn at the angles of its straight sides to
  its axes and of its corners; the brief's angle, cited by the outline or
  by its item, is used where it is one of them.
- **A coordinate is read as one:** the lower-leg shell gave its holes at
  "(-36,50), (36,50), (-36,165)": "-36,165" was read as -36165 or 36.165,
  never as -36 and 165, and "0,0,-37.5" lost its minus. A word of numbers
  joined by commas in brackets, or signed, or three or more, is a
  coordinate: each its own number, a minus after a comma its sign.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forge_roles.spec_writer import read_answer
from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.citations import readings, slot_count
from v2_occ import needs_occ

HERE = Path(__file__).resolve().parent
THIRD = json.loads((HERE / "fixtures" / "corpus_third_run.json").read_text(encoding="utf-8"))
FOURTH = json.loads((HERE / "fixtures" / "corpus_fourth_run.json").read_text(encoding="utf-8"))


def _draft(run: dict[str, Any], key: str, *, brief: str | None = None) -> tuple[Any, dict[str, Any]]:
    found = run["drafts"][key]
    return number_words(brief or found["brief"]), read_answer(copy.deepcopy(found["answer"]))


def _problems(b: Any, d: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in check_draft(b, d).problems]


class ABallsCrossings(unittest.TestCase):
    def test_a_line_meets_a_ball_where_it_does(self) -> None:
        from forge_checks.shapes import Frame, Torus

        for big in (0.0, 2.7e-6):  # a ball; a tube a few micrometres off its axis, as A03's first arc
            with self.subTest(big=big):
                ball = Torus(Frame.along(np.array([15.0, 0, 0]), np.array([1.0, 0, 0])), big, 10.0)
                origins = np.array([[7.9677499999998975, -10.282264367989681, 6.967735632010575],
                                    [-10.8145, -4.81451437, -0.31451437]])  # fmt: skip
                directions = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
                found = ball.crossings(origins, directions)
                # Across the axis: |(x - 15, y, z)| = 10; along it, at the line's distance from it.
                across = 10.282264367989681 + np.array([-1, 1]) * np.sqrt(100 - 7.03225 ** 2 - 6.967735632010575 ** 2)
                along = 10.8145 + 15 + np.array([-1, 1]) * np.sqrt(100 - 4.81451437 ** 2 - 0.31451437 ** 2)
                for row, want in ((0, across), (1, along)):
                    got = np.unique(np.round(found[row][np.isfinite(found[row])], 4))
                    np.testing.assert_allclose(got, want, atol=1e-3)

    def test_the_three_balls_are_judged(self) -> None:
        from forge_checks.judge import Judge
        from forge_spec.lock import lock

        b, d = _draft(THIRD, "A03")
        judge = Judge.of(lock(check_draft(b, d), b, by="draft", strict=False).spec)
        self.assertEqual((judge.expected.solids, judge.expected.voids), (1, 0))

    @needs_occ
    def test_and_pass_as_built(self) -> None:
        from forge_checks.judge import Judge
        from forge_checks.view import ViewProxy
        from forge_occ.planned import build_plan
        from forge_occ.view import BrepView
        from forge_plan import plan
        from forge_spec.lock import lock

        b, d = _draft(THIRD, "A03")
        confirmed = lock(check_draft(b, d), b, by="draft", strict=False)
        shape = build_plan(plan(confirmed)).result.shape
        judged = Judge.of(confirmed.spec).view(ViewProxy(BrepView(shape)), "B-rep", 1)
        self.assertEqual([h.as_dict() for h in judged.held], [])


class AnAngleAnOutlineIsDrawnAt(unittest.TestCase):
    def test_the_turned_block(self) -> None:
        b, d = _draft(FOURTH, "zoo2_rotated_block")
        self.assertEqual(_problems(b, d), [])
        # Cited by the outline, it is checked there as its sizes are.
        d["items"][0]["profile"]["from"]["words"] = [1, 3, 6, 9, 10]
        self.assertEqual(_problems(b, d), [])

    def test_one_it_isn_t_drawn_at_is_asked(self) -> None:
        brief = FOURTH["drafts"]["zoo2_rotated_block"]["brief"].replace("30 degrees", "25 degrees")
        b, d = _draft(FOURTH, "zoo2_rotated_block", brief=brief)
        self.assertIn(("question", "the brief says '25' (sentence 1); nothing in the spec uses it"), _problems(b, d))
        d["items"][0]["profile"]["from"]["words"] = [1, 3, 6, 9, 10]
        self.assertTrue(any(kind == "fault" and "nor an angle it is drawn at" in m for kind, m in _problems(b, d)))


def _read(text: str, word: str) -> tuple[int, list[float]]:
    b = number_words(text)
    i = next(k for k, w in enumerate(b.words) if w.text == word)
    return slot_count(b, i), sorted({r.value for r in readings(b, (i,))})


class ACoordinateIsReadAsOne(unittest.TestCase):
    def test_a_coordinate_s_numbers(self) -> None:
        self.assertEqual(_read("holes at (-36,165) and (36,165)", "-36,165"), (2, [-36.0, 165.0]))
        self.assertEqual(_read("holes at (-36,165) and (36,165)", "36,165"), (2, [36.0, 165.0]))
        self.assertEqual(_read("a pivot at 0,0,-37.5 mm", "0,0,-37.5"), (3, [-37.5, 0.0]))
        self.assertEqual(_read("its centre at -36,50", "-36,50"), (2, [-36.0, 50.0]))

    def test_a_number_with_a_comma_is_as_it_was(self) -> None:
        self.assertEqual(_read("a 1,200 mm beam", "1,200"), (1, [1.2, 1200.0]))
        self.assertEqual(_read("a pitch of 2,5 mm", "2,5"), (2, [2.0, 2.5, 5.0]))


if __name__ == "__main__":
    unittest.main()
