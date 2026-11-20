"""V2: a count word the spec holds by what it is (forge_spec.checks._counts_held; docs/V2-stage4.md, 14.6).

Blind set 1 asked on 11 of 26 clear briefs about count words the spec held
all the same ("all four corners rounded", "a chamfer on both ends", "two
plates", "one in each corner"). Each is used now where what holds it comes
in exactly that many, and asked about still where it doesn't: these tests
hold both sides of every rule. The briefs are written here, not taken from
any blind set.
"""

from __future__ import annotations

import copy
import unittest
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from v2_drafts import assumed, cite, count, draft, mm, said

PLATE = "A plate 60 x 40 x 4 mm with all four corners rounded to 3 mm."
PIN = "A pin 20 mm long and 6 mm across, with a 0.5 mm chamfer on both ends."
BRACKET = "A bracket: two 40 x 40 x 4 mm plates joined at a right angle along one edge."
HOLES = "A plate 80 x 50 x 5 mm with four 4 mm holes, one in each corner, each 6 mm in from both edges."
ROD = "A rod 30 mm long and 10 mm across, with a 4 mm hole 5 mm from one end."
THREE = "A bar 90 x 20 x 6 mm with three 5 mm holes 20 mm apart, the middle one in the middle of the bar."


def asked(brief: str, d: dict[str, Any]) -> list[str]:
    b = number_words(brief)
    report = check_draft(b, d)
    faults = [p.message for p in report.problems if p.kind == "fault"]
    assert not faults, faults
    return [p.message for p in report.problems if p.kind == "question"]


def plate(which: str = "vertical") -> dict[str, Any]:
    b = number_words(PLATE)
    return draft("plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60"),
         "width": {"value": 40, "unit": "mm", "from": {"words": cite(b, "40 x 4 mm")[:1] + cite(b, "4 mm")[1:]}},
         "height": mm(b, 4, "4 mm")},
        {"id": "round", "kind": "fillet", "words": cite(b, "all four corners rounded"),
         "edges": {"of": "plate", "which": which, "words": cite(b, "all four corners")},
         "radius": mm(b, 3, "3 mm")},
    ])  # fmt: skip


def pin(which: str = "both") -> dict[str, Any]:
    b = number_words(PIN)
    return draft("pin", [
        {"id": "pin", "kind": "cylinder", "words": cite(b, "pin"), "length": mm(b, 20, "20 mm long"),
         "diameter": mm(b, 6, "6 mm across")},
        {"id": "bevel", "kind": "chamfer", "words": cite(b, "chamfer on both ends"),
         "edges": {"of": "pin", "which": which, "words": cite(b, "on both ends")},
         "size": mm(b, 0.5, "0.5 mm")},
    ])  # fmt: skip


def bracket(both_cite: bool = True) -> dict[str, Any]:
    b = number_words(BRACKET)
    size = {"length": mm(b, 40, "40", 1), "width": mm(b, 40, "40", 2), "height": mm(b, 4, "4 mm")}
    second_words = cite(b, "two 40 x 40 x 4 mm plates") if both_cite else cite(b, "plates")
    return draft("bracket", [
        {"id": "a", "kind": "block", "words": cite(b, "two 40 x 40 x 4 mm plates"), **copy.deepcopy(size)},
        {"id": "b", "kind": "block", "words": second_words + cite(b, "joined at a right angle along one edge"),
         "on": {"item": "a", "face": "+z"},
         "place": {"x": {"side": "+x", "distance": assumed("flush along that edge", 0), "to": "edge"},
                   "y": {"centred": assumed("the plates share their width")}},
         "length": {"value": 4, "unit": "mm", "from": {"words": cite(b, "4 mm")}},
         "width": mm(b, 40, "40", 2), "height": mm(b, 40, "40", 1)},
    ])  # fmt: skip


def holes(insets: int = 2) -> dict[str, Any]:
    b = number_words(HOLES)
    inset = mm(b, 6, "6 mm in from")
    corners: dict[str, Any] = {"inset_u": inset}
    corners["inset_v"] = copy.deepcopy(inset) if insets == 2 else {"value": 6, "unit": "mm",
                                                                     "from": {"assumed": "the same inset"}}
    return draft("plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 80, "80"),
         "width": mm(b, 50, "50"), "height": mm(b, 5, "5 mm")},
        {"id": "holes", "kind": "hole", "words": cite(b, "four 4 mm holes") + cite(b, "one in each corner"),
         "on": {"item": "plate", "face": "+z"}, "diameter": mm(b, 4, "4 mm"),
         "depth": {"through": True, "from": {"assumed": "mounting holes go through"}},
         "count": count(b, 4, "four"),
         "place": {"pattern": {"corners": corners}}},
    ])  # fmt: skip


def rod(side: bool = True) -> dict[str, Any]:
    b = number_words(ROD)
    x = ({"side": "-x", "distance": mm(b, 5, "5 mm"), "to": "centre"} if side
         else {"centred": assumed("in the middle")})  # fmt: skip
    return draft("rod", [
        {"id": "rod", "kind": "block", "words": cite(b, "rod"), "length": mm(b, 30, "30 mm long"),
         "width": mm(b, 10, "10 mm across"), "height": {"value": 10, "unit": "mm", "from": {"words": cite(b, "10 mm across")}}},
        {"id": "hole", "kind": "hole", "words": cite(b, "a 4 mm hole 5 mm from one end"),
         "on": {"item": "rod", "face": "+z"}, "diameter": mm(b, 4, "4 mm"),
         "depth": {"through": True, "from": {"assumed": "a cross hole"}},
         "place": {"x": x, "y": {"centred": assumed("on the centre line")}}},
    ])  # fmt: skip


class ACountWordHeldByWhatHoldsIt(unittest.TestCase):
    def test_the_edges_a_rounding_picks(self) -> None:
        self.assertEqual(asked(PLATE, plate("vertical")), [])  # four vertical edges

    def test_edges_not_that_many_are_still_asked_about(self) -> None:
        left = asked(PLATE, plate("all"))  # twelve edges for "four"
        self.assertEqual(len(left), 1)
        self.assertIn("'four'", left[0])

    def test_both_ends(self) -> None:
        self.assertEqual(asked(PIN, pin("both")), [])
        self.assertEqual(len(asked(PIN, pin("top"))), 1)  # one rim for "both"

    def test_items_of_one_kind_that_cite_it(self) -> None:
        self.assertEqual(asked(BRACKET, bracket(both_cite=True)), [])
        left = asked(BRACKET, bracket(both_cite=False))  # one plate cites "two": it isn't two
        self.assertEqual(len([q for q in left if "'two'" in q]), 1)

    def test_one_at_each_of_several_and_a_measure_given_to_two(self) -> None:
        self.assertEqual(asked(HOLES, holes(2)), [])
        left = asked(HOLES, holes(1))  # one inset cites "6 mm in from", the other is assumed: "both" isn't two
        self.assertEqual(len(left), 1)
        self.assertIn("'both'", left[0])

    def test_one_end_only_where_the_item_is_measured_from_one(self) -> None:
        self.assertEqual(asked(ROD, rod(side=True)), [])
        left = asked(ROD, rod(side=False))  # centred: neither "5" nor "one" is used
        self.assertEqual(len([q for q in left if "'one'" in q]), 1)

    def test_one_that_points_back_is_no_count(self) -> None:
        b = number_words(THREE)
        middle = [w for w in b.words if w.text == "one"][0]
        from forge_spec.citations import numeric_at

        self.assertFalse(numeric_at(b, middle.index))
        d = draft("bar", [
            {"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": mm(b, 90, "90"),
             "width": mm(b, 20, "20"), "height": mm(b, 6, "6 mm")},
            {"id": "holes", "kind": "hole", "words": cite(b, "three 5 mm holes"), "on": {"item": "bar", "face": "+z"},
             "diameter": mm(b, 5, "5 mm"), "depth": {"through": True, "from": {"assumed": "through"}},
             "place": {"x": {"centred": said(b, "the middle one in the middle of the bar")},
                       "y": {"centred": assumed("on the centre line")},
                       "pattern": {"row": {"axis": {"choose": "x", "from": assumed("along the bar")},
                                            "count": count(b, 3, "three"), "pitch": mm(b, 20, "20 mm apart")}}}},
        ])  # fmt: skip
        self.assertEqual(asked(THREE, d), [])


if __name__ == "__main__":
    unittest.main()
