"""Generated parts the spec checks over seeds 5,000 to 9,999 stopped on (V2-stage4b-0c.md, revision 19).

The exit pair runs seeds 0 to 4,999; swept through the spec checks, the
next five thousand found the generator drawing what the solver doesn't
take, and the solver asking about what it should take:

- 5332: a hole in the far face of a block leaning on a turned block's side.
  Leaning on a turned item's face, an item's faces take nothing yet; the
  generator kept them open.
- 5469: a ball standing on a block's side, made after a pocket right
  through the next face whose way its sunk half fills. The generator
  counted only the ball's half out of the face against the pocket's way.
- 6642: a square-ended slot right through a hollow cylinder's wall, its
  corners farther round from its centre than the hollow's end is along
  the axis: asked about as running past the hollow's edge, which it
  doesn't. Along the axis it reaches its half length.
- 7380: two blind holes on opposite sides of a leaning boss, their floors
  1.25 mm apart across its axis: asked about as overlapping, their floors'
  centres nearer than their width. Heading towards each other, they don't:
  compared as the strips they sweep across the axis.
- 5143 and 7889: the solver stopped on a face placed in its own axes
  (test_v2_plan_open_sides.py).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class TheirDraftsSolveClean(unittest.TestCase):
    def test_each(self) -> None:
        from forge_eval.generator import draft_of, generate
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words
        from v2_exit4 import resolved

        for seed in (5332, 5469, 6642, 7380):
            with self.subTest(seed=seed):
                case = generate(seed)
                report = check_draft(number_words(case.brief), resolved(draft_of(case.items)))
                self.assertEqual([p.message for p in report.problems], [])


if __name__ == "__main__":
    unittest.main()
