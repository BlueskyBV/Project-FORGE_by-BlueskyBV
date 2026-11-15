"""V2 stage 4: the reference parts' compiled documents agree with the second kernel (docs/V2-stage4.md, sections 9 and 13.4).

A run judges a built part by its checks and has V1 build the same document
for a second opinion (docs/V2-stage3.md, section 13): the two kernels'
surfaces agree, their volumes and topology too, and every face V1 names is
named on the exact part, or excused for a reason the exact kernel shows
(a face the step that lost it was right to lose: a cut's tool face at its
mouth, a tab's or a post's foot inside the joined part, a pocket's mouth a
lid covers). Each reference part is planned, built through the build loop
and agreed on; and a loss a trace claims while the step's part still has the
face is not excused.
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan import LATER, confirmed
from v2_occ import needs_occ
from v2_reference import PARTS


def agreed(name: str, exact: Any = None) -> tuple[Any, Any, Any]:
    """A reference part planned, built through the build loop and agreed on: (the document, the build, the report)."""
    from forge_occ.agreement import agree
    from forge_occ.planned import build_plan
    from forge_plan import plan

    found = plan(confirmed(PARTS[name]()[0]))
    built = build_plan(found)
    document = found.document(built.choice)
    return (
        document,
        built,
        agree(document, "part", exact=exact(built.result) if exact else built.result),
    )


@needs_occ
class EveryReferencePartAgrees(unittest.TestCase):
    """One test a part, so a slow machine can run them one by one."""


def _one(name: str) -> Any:
    def test(self: unittest.TestCase) -> None:
        _, built, report = agreed(name)
        self.assertIsNone(built.gap, built.refusals)
        self.assertTrue(report.holds, json.dumps(report.as_dict(), default=str)[:2000])

    return test


for _name in PARTS:
    if _name not in LATER:
        setattr(
            EveryReferencePartAgrees, "test_" + _name.replace(" ", "_"), _one(_name)
        )


@needs_occ
class TheLossesExcusedAreRight(unittest.TestCase):
    def test_the_faces_lost_rightly(self) -> None:
        cases = {
            "covered pocket": {"cup.0.cut.end_face"},
            "post round a rod": {
                "post.0.side.lateral",
                "pin.0.bore.base",
                "pin.0.bore.top",
            },
            "tabs": {"lug.0.keep.z_min", "eye.0.bore.base", "eye.0.bore.top"},
        }
        for name, lost in cases.items():
            with self.subTest(part=name):
                _, _, report = agreed(name)
                self.assertEqual(report.names["missing"], [])
                excused = {line.split(":")[0] for line in report.names["excused"]}
                self.assertEqual(excused, lost)

    def test_a_loss_claimed_where_the_face_is_still_on_the_part(self) -> None:
        """The rod's top, dropped from every step after the rod's own and claimed lost by the post's join: not excused."""
        from forge_occ.names import Names
        from forge_occ.products import SolidProduct

        def dropped(result: Any) -> Any:
            def without(names: Names) -> Names:
                table = tuple(frozenset(n for n in held if not (n.step == "rod.0.rod" and n.role == "top"))
                              for held in names.table)  # fmt: skip
                return Names(names.shape, table)

            products = dict(result.products)
            for step in ("post.join", "pin.cut"):
                product = products[step]
                assert isinstance(product, SolidProduct)
                products[step] = replace(product, names=without(product.names))
            traces = tuple(replace(t, lost=(*t.lost, "rod.0.rod.top")) if t.step == "post.join" else t
                           for t in result.traces)  # fmt: skip
            return replace(
                result, names=without(result.names), products=products, traces=traces
            )

        _, _, report = agreed("post round a rod", exact=dropped)
        self.assertFalse(report.names["holds"])
        self.assertIn("rod.0.rod.top", report.names["missing"])


if __name__ == "__main__":
    unittest.main()
