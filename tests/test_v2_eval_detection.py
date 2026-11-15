"""V2 stage 2, step 8: the detection matrix and the false-hold rate (tests/v2_detection.py), on a part or two.

The full run is a script (``python tests/v2_detection.py --parts 30``), whose
report is docs/V2-detection.md; here, a part as asked holds nothing, its
faults are each held by a FAIL, and the report gives every count with its
denominator.
"""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_detection import WHOLE, Report, judge_part
from v2_meshes import HAVE_MANIFOLD


@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class OnAPart(unittest.TestCase):
    def test_the_parts_as_asked_hold_nothing(self) -> None:
        report = Report()
        for seed in (4, 5):
            judge_part(seed, report, leaves=0, taken=False, transforms=())
        self.assertEqual(report.parts + report.unsound, 2)
        self.assertGreaterEqual(report.parts, 1)
        self.assertEqual(report.held, [])

    def test_its_faults_are_each_held_by_a_fail(self) -> None:
        report = Report()
        judge_part(6, report, leaves=2, taken=True, transforms=())
        self.assertGreaterEqual(sum(report.faults.values()), 2)
        self.assertEqual(report.missed, [])
        self.assertEqual(report.inconclusive_only, [])
        self.assertEqual(report.any_caught, report.faults)


class TheReport(unittest.TestCase):
    def test_every_count_has_its_denominator(self) -> None:
        report = Report(parts=3, unsound=1, kinds={"diameter", "position"})
        report.held.append((2, "position fail: i1/place.x/0: off"))
        report.faults = Counter({"leaf: diameter": 4, "mirrored": 2})
        report.caught["leaf: diameter"].update({"diameter": 4, "face accounting": 3})
        report.caught["mirrored"].update({"face accounting": 2})
        report.any_caught = Counter({"leaf: diameter": 4, "mirrored": 2})
        text = report.render(600.0)
        self.assertIn("1 of 3 parts as asked held (1 more skipped", text)
        self.assertIn("| leaf: diameter | 4 | 0 | 3 | 0 | 0 | 0 | 4 | 4 |", text)
        self.assertIn("6 of 6 faults held by a FAIL.", text)
        self.assertIn("None got past every detector.", text)
        self.assertEqual(
            text.count("| Fault | diameter | position | " + " | ".join(WHOLE)), 1
        )


if __name__ == "__main__":
    unittest.main()
