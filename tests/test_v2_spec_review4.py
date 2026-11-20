"""V2 stage 1: findings of the fourth adversarial review of the spec, pinned.

Briefs written for these tests, never from a blind set.

- A cut right across a body's face, and through it, cuts the part in two:
  CAN'T. At an end, the same cut takes the body's end away, leaving it only
  shorter, its length nowhere on the part (accepted once, then held): asked
  about. Where something else stands on the body, the layout can't tell
  whether the two pieces are held together, so it says nothing of that.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, choose, cite, draft, made_of, mm, said

BAR = ("A PLA bar 70 mm long, 20 mm wide and 5 mm thick, with a 10 mm by 20 mm notch cut right through it. "
       "It carries no load.")  # fmt: skip


def bar(place: dict[str, Any], **notch: Any) -> dict[str, Any]:
    b = number_words(BAR)
    return draft("bar", [
        {"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": mm(b, 70, "70 mm"),
         "width": mm(b, 20, "20 mm"), "height": mm(b, 5, "5 mm")},
        {"id": "notch", "kind": "pocket", "words": cite(b, "notch"), "on": {"item": "bar", "face": "+z"},
         "shape": choose("rectangle", said(b, "10 mm by 20 mm")), "length": mm(b, 10, "10 mm"),
         "width": mm(b, 20, "20 mm", nth=2), "depth": {"through": True, "from": said(b, "right through")},
         "place": place, **notch},
    ], material=made_of(b, "PLA"),
        silent=[{"sentence": 1, "reason": "no load case"}])  # fmt: skip


def kinds(d: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in check_draft(number_words(BAR), d).problems]


class ACutRightAcrossAndThrough(unittest.TestCase):
    def test_in_the_middle_cuts_the_part_in_two(self) -> None:
        middle = {
            "x": {"centred": assumed("for the test")},
            "y": {"centred": assumed("for the test")},
        }
        found = kinds(bar(middle))
        self.assertIn(("fault", "notch copy 1 goes right across face +z and through it: it would cut the part in two"
                       " (it rests on an assumed value: choose one that fits)"), found)  # fmt: skip

    def test_resting_on_the_brief_s_words_it_is_can_t(self) -> None:
        b = number_words(BAR + " The notch is centred.")
        d = bar(
            {"x": {"centred": said(b, "centred")}, "y": {"centred": said(b, "centred")}}
        )
        d["silent"] = [{"sentence": 1, "reason": "no load case"}]
        report = check_draft(b, d)
        self.assertEqual([p.kind for p in report.problems], ["cant"], report.problems)

    def test_at_an_end_it_takes_the_end_away(self) -> None:
        end = {"x": {"side": "-x", "distance": assumed("at the end", 0), "to": "edge"},
               "y": {"centred": assumed("for the test")}}  # fmt: skip
        found = kinds(bar(end))
        self.assertEqual([k for k, m in found if "in two" in m], [])
        # Where it is rests on an assumed value: the writer's to settle.
        self.assertEqual([k for k, m in found if "take that end of bar away" in m], ["fault"], found)
        groove = bar(end, depth={"value": 2, "unit": "mm", "from": {"assumed": "a step"}})
        self.assertEqual(kinds(groove), [])  # not through: a step at its end, its end face left below it

    def test_not_through_it_leaves_the_part_whole(self) -> None:
        middle = {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}
        found = kinds(
            bar(
                middle,
                depth={"value": 2, "unit": "mm", "from": {"assumed": "a groove"}},
            )
        )
        self.assertEqual([k for k, m in found if "in two" in m], [])

    def test_through_the_wall_of_a_shelled_body_it_only_opens_it(self) -> None:
        middle = {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}
        d = bar(
            middle,
            depth={"value": 1, "unit": "mm", "from": {"assumed": "through the lid"}},
        )
        d["items"].append({"id": "hollow", "kind": "shell", "words": cite(number_words(BAR), "bar"), "of": "bar",
                           "thickness": assumed("t", 1), "open": {"faces": [], "from": assumed("sealed")}})  # fmt: skip
        self.assertEqual([k for k, m in kinds(d) if "in two" in m], [])


class OnlyThePersonsAnswersReplaceTheBrief(unittest.TestCase):
    PLATE = "A PLA plate 70 mm long, 50 mm wide and 4 mm thick."

    def plate(
        self, b: Any, length: dict[str, Any], replaced: list[int]
    ) -> dict[str, Any]:
        return draft("plate", [{"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": length,
                                "width": mm(b, 50, "50 mm"), "height": mm(b, 4, "4 mm")}],
                     material=made_of(b, "PLA"),
                     not_modelled=[{"words": replaced, "reason": "replaced by the person's answer"}])  # fmt: skip

    def test_a_draft_can_t_claim_one_there_isn_t(self) -> None:
        b = number_words(self.PLATE)
        d = self.plate(b, assumed("a round number", 80), cite(b, "70 mm long"))
        self.assertIn(("fault", "/not_modelled/0/reason"),
                      [(p.kind, p.at) for p in check_draft(b, d).problems])  # fmt: skip

    def test_a_note_the_spec_follows_can_replace_it(self) -> None:
        text = self.PLATE + "\n\nNote from the person: it is 80 mm long, not 70 mm."
        b = number_words(text, answers_from=len(self.PLATE) + 2)
        d = self.plate(
            b, mm(b, 80, "80 mm long"), cite(b, "70 mm long") + cite(b, "not 70 mm")
        )
        self.assertEqual(check_draft(b, d).problems, ())


if __name__ == "__main__":
    unittest.main()
