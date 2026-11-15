"""V2 stage 1: two drafts of one brief, compared by the part they build (forge_spec.compare).

Plan, section 4.2: where two independent drafts differ, the person is asked.
The tests pin that the comparison is by the part, never the wording:

- the same part written otherwise (other ids, another order, turned another
  way, a blind hole exactly as deep as the plate for one "through") is no
  difference;
- a size, a depth, a place, a rounding, a missing or an extra item each is,
  said of the first draft's item and field so the person can answer there;
- a mirror image is another part, not the same one turned;
- each difference becomes a question the person may answer "right as
  drafted", which changes nothing.

Drafts are written for these tests on the guide's example brief.
"""

from __future__ import annotations

import copy
import unittest
from typing import Any

from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.compare import Difference, differences, features
from forge_spec.guide import EXAMPLE_BRIEF, EXAMPLE_DRAFT
from forge_spec.questions import Answer, apply_answers, questions

BRIEF = number_words(EXAMPLE_BRIEF)


def example() -> dict[str, Any]:
    return copy.deepcopy(dict(EXAMPLE_DRAFT))


def checked(d: dict[str, Any]) -> SpecReport:
    report = check_draft(BRIEF, d)
    assert not report.needs_redraft, report.problems
    return report


def assumed(value: float) -> dict[str, Any]:
    return {"value": value, "unit": "mm", "from": {"assumed": "for the test"}}


FIRST = checked(example())


class TheSamePartWrittenOtherwise(unittest.TestCase):
    def test_itself(self) -> None:
        self.assertEqual(differences(FIRST, FIRST), ())

    def test_other_ids_and_another_order(self) -> None:
        d = example()
        d["items"][1]["id"] = "mounting_holes"
        d["items"] = [d["items"][0], d["items"][2], d["items"][1]]
        self.assertEqual(differences(FIRST, checked(d)), ())

    def test_turned_another_way(self) -> None:
        d = example()
        d["items"][0]["length"], d["items"][0]["width"] = (
            d["items"][0]["width"],
            d["items"][0]["length"],
        )
        d["items"][1]["place"]["pattern"]["row"]["axis"]["choose"] = "y"
        self.assertEqual(differences(FIRST, checked(d)), ())

    def test_a_blind_hole_as_deep_as_the_plate_is_through(self) -> None:
        d = example()
        d["items"][1]["depth"] = assumed(6)
        self.assertEqual(differences(FIRST, checked(d)), ())


class WhatDiffersIsSaidWhereItIs(unittest.TestCase):
    def differ(self, d: dict[str, Any]) -> tuple[Difference, ...]:
        return differences(FIRST, checked(d))

    def test_a_size(self) -> None:
        d = example()
        d["items"][1]["diameter"] = assumed(6)
        self.assertEqual(self.differ(d), (Difference("/items/1/diameter",
                                                     "holes is Ø5 mm here, Ø6 mm in the second draft"),))  # fmt: skip

    def test_a_depth(self) -> None:
        d = example()
        d["items"][1]["depth"] = assumed(4)
        self.assertEqual([x.at for x in self.differ(d)], ["/items/1/depth"])

    def test_a_place(self) -> None:
        d = example()
        d["items"][1]["place"]["pattern"]["row"]["pitch"] = assumed(50)
        self.assertEqual([x.at for x in self.differ(d)], ["/items/1/place"])

    def test_a_rounding(self) -> None:
        d = example()
        d["items"][2]["radius"] = assumed(2)
        (found,) = self.differ(d)
        self.assertEqual((found.at, found.message),
                         ("/items/2/radius", "corners's radius is 3 mm here, 2 mm in the second draft"))  # fmt: skip

    def test_an_item_the_second_hasn_t_and_one_it_has(self) -> None:
        d = example()
        del d["items"][2]
        self.assertEqual([x.at for x in self.differ(d)], ["/items/2"])
        found = differences(checked(d), FIRST)
        self.assertEqual([x.at for x in found], [""])
        self.assertIn("the second draft has a fillet", found[0].message)

    def test_a_mirror_image_is_another_part(self) -> None:
        # One blind hole off the middle: its mirror image can't be turned onto it.
        def off_centre(x: float) -> dict[str, Any]:
            d = example()
            hole = d["items"][1]
            hole["depth"] = assumed(3)
            hole["count"] = {"count": 1, "from": {"assumed": "for the test"}}
            hole["place"] = {"x": {"offset": assumed(x)}, "y": {"offset": assumed(8)}}
            return d

        self.assertNotEqual(
            differences(checked(off_centre(20)), checked(off_centre(-20))), ()
        )
        self.assertEqual(
            differences(checked(off_centre(20)), checked(off_centre(20))), ()
        )


class EachDifferenceIsAQuestion(unittest.TestCase):
    def test_answered_by_a_size_or_kept_as_drafted(self) -> None:
        d = example()
        d["items"][1]["diameter"] = assumed(6)
        found = differences(FIRST, checked(d))
        round_ = questions(FIRST, found)
        (asked,) = [
            q
            for q in round_
            if q.text.startswith("the second draft reads this otherwise")
        ]
        self.assertEqual([o.kind for o in asked.options], ["value", "keep", "note"])
        kept = apply_answers(BRIEF, example(), round_, [Answer(asked.id, 1)])
        self.assertEqual((kept.brief, kept.draft), (BRIEF, example()))
        sized = apply_answers(BRIEF, example(), round_, [Answer(asked.id, 0, number=5)])
        self.assertIn("Answer about holes diameter: 5 mm.", sized.brief.text)

    def test_only_drafts_that_check_clean_are_compared(self) -> None:
        d = example()
        d["items"][0]["length"]["value"] = 75  # a misquote: the writer's to fix first
        with self.assertRaises(ValueError):
            differences(FIRST, check_draft(BRIEF, d))

    def test_features_are_every_copy_and_every_rounded_edge(self) -> None:
        self.assertEqual([(f.item, f.shape) for f in features(FIRST)],
                         [("plate", "box"), ("holes", "round cut"), ("holes", "round cut"),
                          *[("corners", "edge")] * 4])  # fmt: skip


if __name__ == "__main__":
    unittest.main()
