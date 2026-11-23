"""V2: what the corpus's second run found the spec checks let through, and the questions it asked that nobody needed
(docs/V2-stage4.md, 14.8).

- **A shape the brief asks for can't be listed as not modelled:** "rounded
  triangular cutouts" were, and the rail was built and released without
  them. A fault, in every mode: it is drafted, or said in ``unable``. One
  the brief denies ("no cutouts") or one the spec has already ("around
  every hole") is not a shape left out; nor which way a part sits ("a dome
  sitting flat side up", built flat side down).
- **Every size assumed is a question,** the spec stage's: "Make a washer."
  was built as a 20 mm washer nobody asked for. Not where the spec says
  Forge can't make what is asked ("Write me a poem"), nor once the person
  has answered (their answer accepts the assumptions, each shown).
- **Strength can't be dropped:** "a PLA hook strong enough to hang a coat
  on", its strength listed as not modelled, was built and released. Asked,
  unless the brief denies it ("carries no load", "Load: none") or says it
  is checked outside Forge; a silent sentence with a number in it is asked
  about already.
- **A dome sits flat side down:** one the brief has sit any other way can't
  be made yet (UNABLE), said once where the draft says so itself.
- **Questions nobody needed,** each still asked where the spec doesn't hold
  it: "a stepped shaft on one axis" (C04); "one divider ... splitting it
  into two compartments" (C10); a ball "half sunk" into a face (C14); "56
  apart one way and 36 the other" (V02); "across its 30 mm width" (L04);
  "both ends fully rounded" on an outline with two arcs.
- **What the writer is told:** a unitless number in a formula is a count,
  said so; an ``unable`` said at too great a length is told how long; and a
  depth the preview can't find behind a question isn't an UNABLE that
  hides the question.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forge_cli.spec import with_unresolved
from forge_spec import number_words
from forge_spec.checks import NO_SIZE, check_draft, sizes_asked
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said, span


def _problems(b: Any, d: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in check_draft(b, d).problems]


def _kinds(b: Any, d: dict[str, Any]) -> list[str]:
    return [kind for kind, _ in _problems(b, d)]


RAIL = ("A PLA rail 180 mm long, 30 mm wide and 8 mm thick with a 6 mm hole through its middle. Keep it light with "
        "rounded triangular cutouts, keeping material around every hole.")  # fmt: skip


def _rail(text: str = RAIL, *, left_out: str = "Keep it light with rounded triangular cutouts, keeping material "
          "around every hole", unable: bool = False) -> tuple[Any, dict[str, Any]]:  # fmt: skip
    b = number_words(text)
    d = draft("rail", [
        {"id": "rail", "kind": "block", "words": cite(b, "rail"), "length": mm(b, 180, "180 mm long"),
         "width": mm(b, 30, "30 mm wide"), "height": mm(b, 8, "8 mm thick")},
        {"id": "hole", "kind": "hole", "words": cite(b, "a 6 mm hole through its middle"),
         "on": {"item": "rail", "face": "+z"}, "diameter": mm(b, 6, "6 mm"),
         "depth": {"through": True, "from": said(b, "through")},
         "place": {"x": {"centred": said(b, "its middle")}, "y": {"centred": said(b, "its middle")}}},
    ], material=made_of(b, "PLA"))  # fmt: skip
    entry = {"words": span(b, left_out)}
    if unable:
        d["unable"] = [{**entry, "what": "rounded triangular cutouts"}]
    else:
        d["not_modelled"] = [{**entry, "reason": "no size, count or place is given for them"}]
    return b, d


class AShapeCantBeLeftOut(unittest.TestCase):
    def test_a_shape_the_brief_asks_for(self) -> None:
        b, d = _rail()
        for strict in (False, True):
            with self.subTest(strict=strict):
                found = [(p.kind, p.at, p.message) for p in check_draft(b, d, strict=strict).problems]
                self.assertIn(("fault", "/not_modelled/0/words", "not_modelled can't hold 'cutouts': it is a shape of "
                               "the part the brief asks for, and the part would be built without it. Draft it, or say "
                               "in unable that Forge can't make it yet"), found)  # fmt: skip
        # Said in unable instead: Forge can't make it yet, and the run ends so.
        b, d = _rail(unable=True)
        self.assertEqual(_problems(b, d), [("unable", "Forge can't make rounded triangular cutouts yet (the brief's "
                                            "'Keep it light with rounded triangular cutouts keeping material around "
                                            "every hole')")])  # fmt: skip

    def test_one_denied_or_had_already_isnt_left_out(self) -> None:
        text = "A PLA rail 180 mm long, 30 mm wide and 8 mm thick with a 6 mm hole through its middle. It has no cutouts."
        b, d = _rail(text, left_out="It has no cutouts")
        self.assertEqual(_problems(b, d), [])
        text = ("A PLA rail 180 mm long, 30 mm wide and 8 mm thick with a 6 mm hole through its middle. The hole takes "
                "an M6 bolt.")  # fmt: skip
        b, d = _rail(text, left_out="The hole takes an M6 bolt")
        self.assertNotIn("fault", _kinds(b, d))

    def test_one_the_person_said_to_leave_out(self) -> None:
        text = RAIL + " Answer about not_modelled 0: leave the cutouts out."
        b = number_words(text, answers_from=text.index("Answer"))
        _, d = _rail()  # the brief's own words are numbered as before: the answer comes after them
        d["not_modelled"][0]["reason"] = "replaced by the person's answer: leave the cutouts out"
        self.assertFalse(any("can't hold" in m for _, m in _problems(b, d)), _problems(b, d))

    def test_which_way_a_part_sits(self) -> None:
        b, d = _dome("A PLA dome, exactly half of a 50 mm sphere, sitting flat side up.", "dome, exactly half of a 50 mm "
                     "sphere")  # fmt: skip
        d["not_modelled"] = [{"words": cite(b, "sitting flat side up"), "reason": "a dome sits flat side down"}]
        self.assertIn(("fault", "not_modelled can't hold which way the part sits ('flat side up'): the part would be "
                       "built some other way. Draft it, or say in unable that Forge can't make it so yet"),
                      _problems(b, d))  # fmt: skip


def _washer(text: str = "Make a washer.", thick: str | None = None) -> tuple[Any, dict[str, Any]]:
    b = number_words(text)
    length = mm(b, 2, thick) if thick else assumed("a typical washer's thickness", 2)
    return b, draft("washer", [
        {"id": "washer", "kind": "tube", "words": cite(b, "washer"),
         "outer_diameter": assumed("a typical small washer", 20), "inner_diameter": assumed("clears a small bolt", 10),
         "length": length, "axis": choose("z", {"assumed": "a washer lies flat"})},
    ])  # fmt: skip


def _asked(b: Any, d: dict[str, Any]) -> list[tuple[str, str]]:
    """What the spec stage asks of a draft: its checks', and its size where every size is assumed."""
    return [(p.kind, p.message) for p in sizes_asked(check_draft(b, d), b).problems]


class EverySizeAssumedIsAsked(unittest.TestCase):
    def test_a_washer_of_no_size(self) -> None:
        b, d = _washer()
        self.assertEqual(_asked(b, d), [("question", NO_SIZE)])
        self.assertEqual(NO_SIZE, "the brief gives no size: every size in the spec is assumed, so the part would be a "
                         "guess. What size should it be?")  # fmt: skip
        # One size the brief gives: the rest are assumptions, shown as such.
        b, d = _washer("Make a washer 2 mm thick.", "2 mm thick")
        self.assertEqual(_asked(b, d), [])

    def test_not_where_forge_cant_make_what_is_asked_nor_once_answered(self) -> None:
        b = number_words("Write me a poem about bridges.")
        d = draft("placeholder", [
            {"id": "block", "kind": "block", "words": cite(b, "poem"), "length": assumed("a placeholder", 10),
             "width": assumed("a placeholder", 10), "height": assumed("a placeholder", 10)},
        ])  # fmt: skip
        d["unable"] = [{"words": cite(b, "Write me a poem about bridges"), "what": "a poem, not a part"}]
        self.assertEqual([kind for kind, _ in _asked(b, d)], ["unable"])
        # The person answered, and gave no size ("use yours"): the assumptions are theirs to accept, each shown.
        text = "Make a washer. Answer about items: use your sizes."
        b, d = _washer(text)
        b = number_words(text, answers_from=text.index("Answer"))
        self.assertNotIn(("question", NO_SIZE), _asked(b, d))

    def test_asked_by_the_spec_stage_not_the_checks(self) -> None:
        """The checks read the draft; the spec stage asks it of every round (forge_cli.spec._resolved)."""
        from forge_cli.spec import _resolved

        b, d = _washer()
        self.assertEqual(check_draft(b, d).problems, ())
        self.assertEqual([(p.kind, p.message) for p in _resolved(b, check_draft(b, d), False).problems],
                         [("question", NO_SIZE)])  # fmt: skip


def _hook(text: str, *, quiet: int | None = None, left_out: str | None = None) -> tuple[Any, dict[str, Any]]:
    b = number_words(text)
    d = draft("hook", [
        {"id": "hook", "kind": "block", "words": cite(b, "hook"), "length": mm(b, 60, "60 mm tall"),
         "width": mm(b, 40, "40 mm wide"), "height": mm(b, 10, "10 mm thick")},
    ], silent=[{"sentence": quiet, "reason": "about what it carries"}] if quiet is not None else None,
        not_modelled=[{"words": cite(b, left_out), "reason": "what it is for"}] if left_out else None,
        material=made_of(b, "PLA"))  # fmt: skip
    return b, d


class StrengthCantBeDropped(unittest.TestCase):
    ASKED = ("the brief asks for strength ({}), which Forge can't check yet: say what the part must carry, or that its "
             "strength is checked outside Forge")  # fmt: skip

    def test_asked_where_the_spec_leaves_it_out(self) -> None:
        b, d = _hook("A PLA hook 60 mm tall, 40 mm wide and 10 mm thick, strong enough to hang a coat on.",
                     left_out="strong enough to hang a coat on")  # fmt: skip
        self.assertIn(("question", self.ASKED.format("'strong'")), _problems(b, d))
        b, d = _hook("A PLA hook 60 mm tall, 40 mm wide and 10 mm thick. It must be sturdy.", quiet=1)
        self.assertIn(("question", self.ASKED.format("'sturdy'")), _problems(b, d))

    def test_not_where_it_is_denied_checked_elsewhere_or_asked_already(self) -> None:
        for second in ("It carries no load, so there is no load case.", "Load: none.",
                       "Its strength is checked outside Forge, so there is no load case.",
                       "It doesn't need to be strong."):  # fmt: skip
            with self.subTest(second=second):
                b, d = _hook(f"A PLA hook 60 mm tall, 40 mm wide and 10 mm thick. {second}", quiet=1)
                self.assertEqual(_problems(b, d), [])
        # A load with a number: its number is asked about, as before.
        b, d = _hook("A PLA hook 60 mm tall, 40 mm wide and 10 mm thick. It carries a 50 N load.", quiet=1)
        self.assertEqual(_problems(b, d), [("question", "the brief says '50' (sentence 2); nothing in the spec uses "
                                            "it")])  # fmt: skip


def _dome(text: str, words: str) -> tuple[Any, dict[str, Any]]:
    b = number_words(text)
    return b, draft("dome", [
        {"id": "dome", "kind": "sphere", "words": span(b, words), "diameter": mm(b, 50, "50 mm sphere"),
         "portion": choose("upper_half", said(b, "half"))},
    ], material=made_of(b, "PLA"))  # fmt: skip


class ADomeSitsFlatSideDown(unittest.TestCase):
    def test_any_other_way_cant_be_made_yet(self) -> None:
        for way, said_ in (("up", "flat side up"), ("to the right side", "flat side to the right")):
            with self.subTest(way=way):
                text = f"A PLA dome, exactly half of a 50 mm sphere, sitting flat side {way}."
                b, d = _dome(text, f"dome, exactly half of a 50 mm sphere, sitting flat side {way}")
                self.assertEqual(_problems(b, d), [("unable", "Forge makes a dome flat side down only, for now: dome "
                                                    f"is to sit {said_!r}")])  # fmt: skip
        b, d = _dome("A PLA dome, exactly half of a 50 mm sphere, sitting flat side down.",
                     "dome, exactly half of a 50 mm sphere, sitting flat side down")  # fmt: skip
        self.assertEqual(_problems(b, d), [])

    def test_said_once_where_the_draft_says_so(self) -> None:
        text = "A PLA dome, exactly half of a 50 mm sphere, sitting flat side up."
        b, d = _dome(text, "dome, exactly half of a 50 mm sphere")
        d["unable"] = [{"words": cite(b, "sitting flat side up"), "what": "a dome sitting flat side up"}]
        self.assertEqual(_kinds(b, d), ["unable"])


class QuestionsNobodyNeeded(unittest.TestCase):
    def test_a_shaft_on_one_axis(self) -> None:
        text = ("An aluminium stepped shaft on one axis: a section 20 mm in diameter and 30 mm long, followed by a "
                "section 12 mm in diameter and 40 mm long.")  # fmt: skip
        b = number_words(text)

        def shaft(on: str = "+end") -> dict[str, Any]:
            return draft("stepped shaft", [
                {"id": "big", "kind": "cylinder", "words": cite(b, "a section 20 mm in diameter and 30 mm long"),
                 "diameter": mm(b, 20, "20 mm in diameter"), "length": mm(b, 30, "30 mm long"),
                 "axis": choose("x", {"assumed": "lying along its length"})},
                {"id": "small", "kind": "cylinder", "words": cite(b, "a section 12 mm in diameter and 40 mm long"),
                 "diameter": mm(b, 12, "12 mm in diameter"), "length": mm(b, 40, "40 mm long"),
                 "on": {"item": "big", "face": on},
                 "place": {"u": {"centred": {"assumed": "coaxial"}}, "v": {"centred": {"assumed": "coaxial"}}}},
            ], material=made_of(b, "aluminium"))  # fmt: skip

        self.assertEqual(_problems(b, shaft()), [])
        d = shaft()  # the second section off the first's axis: "one" is asked about
        d["items"][1]["place"]["u"] = {"offset": assumed("off its axis", 2)}
        self.assertIn(("question", "the brief says 'one' (sentence 1); nothing in the spec uses it"), _problems(b, d))

    def test_one_divider_into_two_compartments(self) -> None:
        def tray(n: str) -> tuple[Any, dict[str, Any]]:
            text = (f"A PLA tray 100 mm long, 60 mm wide and 25 mm tall on the outside, with 2 mm walls and a 2 mm "
                    f"floor, open at the top, and one 2 mm thick divider wall across the middle splitting it into {n} "
                    "equal compartments.")  # fmt: skip
            b = number_words(text)
            return b, draft("tray", [
                {"id": "tray", "kind": "block", "words": cite(b, "tray"), "length": mm(b, 100, "100 mm long"),
                 "width": mm(b, 60, "60 mm wide"), "height": mm(b, 25, "25 mm tall")},
                {"id": "hollow", "kind": "shell", "words": span(b, "with 2 mm walls and a 2 mm floor, open at the top"),
                 "of": "tray", "thickness": mm(b, 2, "2 mm walls"), "floor": mm(b, 2, "2 mm floor"),
                 "open": {"faces": ["+z"], "from": said(b, "open at the top")}},
                {"id": "divider", "kind": "rib",
                 "words": cite(b, f"one 2 mm thick divider wall across the middle splitting it into {n} equal "
                               "compartments"),
                 "on": {"item": "tray", "face": "inner -z"},
                 "place": {"x": {"centred": said(b, "across the middle")},
                           "y": {"centred": {"assumed": "it spans the inner width"}}},
                 "length": {"value": 56, "unit": "mm",
                            "from": {"formula": "60 mm - 2 mm * 2", "words": cite(b, "60 mm") + cite(b, "2 mm")}},
                 "thickness": mm(b, 2, "2 mm thick"),
                 "height": {"value": 23, "unit": "mm",
                            "from": {"formula": "25 mm - 2 mm", "words": cite(b, "25 mm") + cite(b, "2 mm floor")}},
                 "along": choose("y", {"assumed": "across the width"}), "count": count(b, 1, "one")},
            ], material=made_of(b, "PLA"))  # fmt: skip

        self.assertEqual(_problems(*tray("two")), [])
        self.assertIn(("question", "the brief says 'three' (sentence 1); nothing in the spec uses it"),
                      _problems(*tray("three")))  # fmt: skip

    def test_a_ball_half_sunk_into_a_face(self) -> None:
        text = ("A PLA ornament: a 30 mm cube with a 20 mm ball half sunk into the middle of its top face, so half the "
                "ball sticks up.")  # fmt: skip
        b = number_words(text)
        ball_words = "a 20 mm ball half sunk into the middle of its top face, so half the ball sticks up"
        d = draft("ornament", [
            {"id": "cube", "kind": "block", "words": cite(b, "a 30 mm cube"), "length": mm(b, 30, "30 mm cube"),
             "width": mm(b, 30, "30 mm cube"), "height": mm(b, 30, "30 mm cube")},
            {"id": "ball", "kind": "sphere", "words": span(b, ball_words), "diameter": mm(b, 20, "20 mm ball"),
             "portion": choose("whole", said(b, "ball")), "on": {"item": "cube", "face": "+z"},
             "place": {"x": {"centred": said(b, "the middle")}, "y": {"centred": said(b, "the middle")}}},
        ], material=made_of(b, "PLA"))  # fmt: skip
        self.assertEqual(_problems(b, d), [])

    def test_one_way_and_the_other(self) -> None:
        def plate(inset_y: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
            text = ("An aluminium plate 70 mm by 50 mm and 4 mm thick with a 4 mm hole near each corner. The holes are "
                    "56 mm apart one way and 36 mm the other.")  # fmt: skip
            b = number_words(text)
            return b, draft("plate", [
                {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 70, "70 mm"),
                 "width": mm(b, 50, "50 mm"), "height": mm(b, 4, "4 mm thick")},
                {"id": "holes", "kind": "hole", "words": cite(b, "a 4 mm hole near each corner") +
                 cite(b, "The holes are 56 mm apart one way and 36 mm the other"),
                 "on": {"item": "plate", "face": "+z"}, "diameter": mm(b, 4, "4 mm hole"),
                 "depth": {"through": True, "from": {"assumed": "through a thin plate"}},
                 "count": {"count": 4, "from": {"assumed": "a plate has four corners"}},
                 "place": {"pattern": {"corners": {
                     "inset_x": {"value": 7, "unit": "mm", "from": {"formula": "(70 mm - 56 mm) / 2",
                                                                    "words": cite(b, "70 mm") + cite(b, "56 mm")}},
                     "inset_y": inset_y}}}},
            ], material=made_of(b, "aluminium"))  # fmt: skip

        b = number_words("An aluminium plate 70 mm by 50 mm and 4 mm thick with a 4 mm hole near each corner. The holes "
                         "are 56 mm apart one way and 36 mm the other.")  # fmt: skip
        both = {"value": 7, "unit": "mm", "from": {"formula": "(50 mm - 36 mm) / 2",
                                                   "words": cite(b, "50 mm") + cite(b, "36 mm")}}  # fmt: skip
        self.assertEqual(_problems(*plate(both)), [])

    def test_a_size_the_brief_gives_again(self) -> None:
        def block(across: float) -> tuple[Any, dict[str, Any]]:
            text = (f"An aluminium bearing block 40 mm long, 30 mm wide and 20 mm tall with a 10 mm hole straight "
                    f"through it across its {across:g} mm width, through the middle.")  # fmt: skip
            b = number_words(text)
            return b, draft("bearing block", [
                {"id": "block", "kind": "block", "words": cite(b, "bearing block"), "length": mm(b, 40, "40 mm long"),
                 "width": mm(b, 30, "30 mm wide"), "height": mm(b, 20, "20 mm tall")},
                {"id": "pin_hole", "kind": "hole",
                 "words": span(b, f"a 10 mm hole straight through it across its {across:g} mm width, through the "
                               "middle"),
                 "on": {"item": "block", "face": "+y"}, "diameter": mm(b, 10, "10 mm"),
                 "depth": {"through": True, "from": said(b, "straight through")},
                 "place": {"x": {"centred": said(b, "the middle")}, "z": {"centred": said(b, "the middle")}}},
            ], material=made_of(b, "aluminium"))  # fmt: skip

        self.assertEqual(_problems(*block(30)), [])
        # A size the face hasn't: the brief and the spec disagree, and it is asked.
        self.assertIn(("question", "the brief says '25' (sentence 1); nothing in the spec uses it"),
                      _problems(*block(25)))  # fmt: skip

    def test_both_ends_rounded_on_an_outline_with_two_arcs(self) -> None:
        text = "A flat PLA strip 110 mm long, 16 mm wide and 2 mm thick with both ends fully rounded."
        b = number_words(text)
        d = draft("strip", [
            {"id": "strip", "kind": "extrusion", "words": cite(b, "flat PLA strip") + cite(b, "with both ends fully "
                                                                                              "rounded"),
             "profile": {"start": [-47, -8], "segments": [{"line_to": [47, -8]},
                                                          {"arc_to": [47, 8], "centre": [47, 0], "clockwise": False},
                                                          {"line_to": [-47, 8]},
                                                          {"arc_to": [-47, -8], "centre": [-47, 0], "clockwise": False}],
                         "unit": "mm", "from": {"words": span(b, "110 mm long, 16 mm wide") + cite(b, "ends fully rounded")}},
             "length": mm(b, 2, "2 mm thick"), "axis": choose("z", {"assumed": "it lies flat"})},
        ], material=made_of(b, "PLA"))  # fmt: skip
        self.assertEqual(_problems(b, d), [])


class WhatTheWriterIsTold(unittest.TestCase):
    def test_a_unitless_number_in_a_formula(self) -> None:
        text = "An aluminium bar 50 mm long, 20 mm wide and 10 mm thick with a 5 mm hole 12.5 mm from one end."
        b = number_words(text)
        d = draft("bar", [
            {"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": mm(b, 50, "50 mm long"),
             "width": mm(b, 20, "20 mm wide"), "height": mm(b, 10, "10 mm thick")},
            {"id": "hole", "kind": "hole", "words": cite(b, "a 5 mm hole 12.5 mm from one end"),
             "on": {"item": "bar", "face": "+z"}, "diameter": mm(b, 5, "5 mm hole"),
             "depth": {"through": True, "from": {"assumed": "through"}},
             "place": {"x": {"offset": {"value": -12.5, "unit": "mm",
                                        "from": {"formula": "12.5 - 25", "words": cite(b, "12.5 mm")}}},
                       "y": {"centred": {"assumed": "the middle"}}}},
        ], material=made_of(b, "aluminium"))  # fmt: skip
        self.assertIn("12.5 in the formula '12.5 - 25' has no unit: a number with none is a count of things; write a "
                      "size with its unit (\"37.5 mm\")", " ".join(m for _, m in _problems(b, d)))  # fmt: skip

    def test_an_unable_said_too_long(self) -> None:
        b, d = _rail(unable=True)
        d["unable"][0]["what"] = "x" * 170
        self.assertIn(("fault", "say what no kind makes in a few words, at most 80 characters: this is 170 (\"involute "
                       "gear teeth\")"), _problems(b, d))  # fmt: skip

    def test_a_depth_the_preview_cant_find_behind_a_question(self) -> None:
        b, d = _washer()
        asked = sizes_asked(check_draft(b, d), b)
        self.assertIs(with_unresolved(asked, [("washer", "what is made before it doesn't place")]), asked)
        # Nothing else to settle: the depth it can't find is an UNABLE.
        b, d = _washer("Make a washer 2 mm thick.", "2 mm thick")
        clean = check_draft(b, d)
        self.assertEqual(clean.problems, ())
        self.assertEqual([(p.kind, p.at) for p in with_unresolved(clean, [("washer", "why")]).problems],
                         [("unable", "/items/0/depth")])  # fmt: skip


if __name__ == "__main__":
    unittest.main()
