"""V2 stage 1: what the second review of the spec contract found, pinned.

Two reviewers attacked the spec checks a second time and found ways for a
draft to say something the brief doesn't, or for the person to confirm
something other than what would be built. Each test here is one of them,
fixed at its root. The briefs are written for these tests (or are V1 corpus
briefs, validation/SUITE.md); none comes from a blind set.

- **Numbers:** a tolerance is read only from numbers marked as one, a value
  or a formula uses the whole of the brief's number, and a formula can't
  bring in a number of its own.
- **Words:** a text is exactly the brief's characters, a choice can't cite
  the words that deny it, and a standard part is named whole.
- **Placement:** copies don't land on each other, a feature fits the room it
  stands in, and a problem goes to whoever can fix it.
- **What the person sees:** nothing the model writes can add a line to it,
  every number shows exactly, and the lock covers everything it hands on.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.lock import LockError, lock, spec_digest
from forge_spec.render import _n, render
from forge_spec.words import NumberedBrief

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_spec_partspec import R05, flange_draft, plate_draft
from test_v2_spec_placement import (
    ASSUMED,
    PLATE,
    a,
    at,
    centred,
    guess,
    hole,
    issues,
    item,
    kinds,
    layout_of,
    on,
    pick,
    shell,
)
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said, span

NO_LOAD = "It carries no load, so there is no load case."


def found(report: SpecReport) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in report.problems]


def messages(report: SpecReport, kind: str | None = None) -> list[str]:
    return [p.message for p in report.problems if kind in (None, p.kind)]


def plate_items(b: NumberedBrief, **length: Any) -> list[dict[str, Any]]:
    """A plate 60 x 40 x 5 mm whose length cites ``phrase`` (default "60 mm")."""
    value = {
        "value": 60,
        "unit": "mm",
        "from": {"words": span(b, length.pop("phrase", "60 mm"))},
    }
    return [{"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": {**value, **length},
             "width": mm(b, 40, "40 mm"), "height": mm(b, 5, "5 mm")}]  # fmt: skip


# ----------------------------------------------------------------------
# Numbers
# ----------------------------------------------------------------------
class TolerancesAreReadOnlyFromTheirMarks(unittest.TestCase):
    def check(
        self, text: str, phrase: str, tolerance: dict[str, float] | None
    ) -> list[tuple[str, str]]:
        b = number_words(text)
        extra = {"tolerance": tolerance} if tolerance is not None else {}
        return found(
            check_draft(b, draft("plate", plate_items(b, phrase=phrase, **extra)))
        )

    def test_every_way_of_writing_plus_or_minus(self) -> None:
        for written in ("60 mm \u00b10.1 mm", "60 mm \u00b1 0.1 mm", "60 mm +/- 0.1 mm", "60 mm +/-0.1 mm",
                        "60 mm plus or minus 0.1 mm", "60\u00b10.1mm", "60.00 \u00b1 0.10 mm"):  # fmt: skip
            text = f"A plate {written} long, 40 mm wide and 5 mm thick."
            self.assertEqual(
                self.check(text, written, {"plus": 0.1, "minus": 0.1}), [], written
            )
            self.assertEqual(self.check(text, written, {"plus": 0.1, "minus": 0}),
                             [("fault", "the brief gives +0.1/-0.1 mm, not +0.1/-0")], written)  # fmt: skip

    def test_signed_bounds_keep_their_sides(self) -> None:
        for written, plus, minus in (
            ("60 mm +0.1/-0 mm", 0.1, 0),
            ("60 mm +0.2 -0.1 mm", 0.2, 0.1),
        ):
            text = f"A plate {written} long, 40 mm wide and 5 mm thick."
            self.assertEqual(
                self.check(text, written, {"plus": plus, "minus": minus}), [], written
            )
            self.assertEqual(
                self.check(text, written, {"plus": minus, "minus": plus})[0][0],
                "fault",
                written,
            )

    def test_a_tolerance_the_brief_gives_is_kept(self) -> None:
        text = "A plate 60 mm \u00b10.1 mm long, 40 mm wide and 5 mm thick."
        self.assertEqual(self.check(text, "60 mm \u00b10.1 mm", None),
                         [("fault", "the brief gives +0.1/-0.1 mm: give the tolerance")])  # fmt: skip

    def test_another_number_is_never_a_tolerance(self) -> None:
        # The tolerance would take the chamfer's 1 mm, and the chamfer would quietly disappear.
        text = "A plate 60 mm long with a 1 mm chamfer, 40 mm wide and 5 mm thick."
        problems = self.check(text, "60 mm long with a 1 mm", {"plus": 1, "minus": 0})
        self.assertEqual(problems[0][0], "fault")
        self.assertIn("('60', '1')", problems[0][1])
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick."
        self.assertIn("the tolerance isn't in the cited words",
                      self.check(text, "60 mm", {"plus": 0.1, "minus": 0.1})[0][1])  # fmt: skip


class AValueUsesTheWholeOfItsNumber(unittest.TestCase):
    TEXT = "A rod 10 mm across and 1 1/2 in long."

    def rod(self, length: Any) -> list[tuple[str, str]]:
        b = number_words(self.TEXT)
        d = draft("rod", [{"id": "rod", "kind": "cylinder", "words": cite(b, "rod"),
                           "diameter": mm(b, 10, "10 mm"), "length": length(b), "axis": choose("z", assumed("t"))}])  # fmt: skip
        return [(k, m) for k, m in found(check_draft(b, d)) if k == "fault"]

    def formula(self, value: float, formula: str) -> Any:
        return lambda b: {"value": value, "unit": "mm",
                          "from": {"formula": formula, "words": span(b, "1 1/2 in")}}  # fmt: skip

    def test_cited_directly(self) -> None:
        self.assertEqual(
            self.rod(
                lambda b: {
                    "value": 1.5,
                    "unit": "in",
                    "from": {"words": span(b, "1 1/2 in")},
                }
            ),
            [],
        )
        self.assertEqual(self.rod(lambda b: {"value": 0.5, "unit": "in", "from": {"words": span(b, "1/2 in")}}),
                         [("fault", "'1/2' is only part of a number the brief writes over more words: cite all of it")])  # fmt: skip

    def test_in_a_formula(self) -> None:
        self.assertEqual(self.rod(self.formula(38.1, "1.5 in")), [])
        self.assertEqual(self.rod(self.formula(19.05, "1.5 in / 2")), [])
        # 1 inch is in the words, but only as part of 1 1/2 inches: a pin's radius would come out 12.7 mm, not 19.05.
        self.assertEqual(self.rod(self.formula(12.7, "1 in / 2")),
                         [("fault", "1 in in the formula '1 in / 2' is not in the words it cites ('1 1/2 in'), "
                                    "or is used twice")])  # fmt: skip

    def test_inches_read_in_a_formula(self) -> None:
        # "in" is also a keyword of the language formulas are parsed in.
        self.assertEqual(self.rod(self.formula(76.2, "1.5 in * 2")), [])
        self.assertEqual(self.rod(self.formula(76.2, "1.5in * 2")), [])


class AFormulaBringsInNoNumberOfItsOwn(unittest.TestCase):
    TEXT = "A rod 10 mm across and 5 mm long."

    def faults(self, value: float, formula: str, *phrases: str) -> list[str]:
        b = number_words(self.TEXT)
        words = [i for phrase in phrases or ("5 mm",) for i in span(b, phrase)]
        d = draft("rod", [{"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": mm(b, 10, "10 mm"),
                           "length": {"value": value, "unit": "mm", "from": {"formula": formula, "words": words}},
                           "axis": choose("z", assumed("t"))}])  # fmt: skip
        return messages(check_draft(b, d), "fault")

    def test_one_free_two_halves_or_doubles_a_number_of_the_brief(self) -> None:
        self.assertEqual(self.faults(10, "2 * 5 mm"), [])
        self.assertEqual(self.faults(2.5, "5 mm / 2"), [])
        for value, formula in ((20, "2 * 2 * 5 mm"), (1.25, "5 mm / 2 / 2"), (2, "2 mm"), (7, "5 mm + 2 mm"),
                               (15, "5 mm * (2 / 2 + 2 / 2 + 2 / 2)")):  # fmt: skip
            self.assertTrue(self.faults(value, formula), formula)

    def test_no_function_that_can_swallow_a_number(self) -> None:
        for function in ("min", "max"):
            problems = self.faults(5, f"{function}(5 mm, 10 mm)", "5 mm", "10 mm")
            self.assertIn(
                f"{function}() isn't one of the functions a formula may use",
                problems[0],
            )
        self.assertIn(
            "abs() isn't one",
            self.faults(5, "5 mm + abs(10 mm - 10 mm)", "5 mm", "10 mm")[0],
        )

    def test_no_comment_and_no_second_line(self) -> None:
        self.assertEqual(
            self.faults(5, "5 mm # half"), ["a formula is arithmetic only: no comments"]
        )
        self.assertEqual(
            self.faults(5, "(5 mm\n)"),
            [
                "formula must be one line of plain printable text, at most 200 characters"
            ],
        )


# ----------------------------------------------------------------------
# Words
# ----------------------------------------------------------------------
class ATextIsExactlyTheBriefsCharacters(unittest.TestCase):
    def label(self, text: str, lettering: str, phrase: str, *more: str,
              faults_only: bool = True) -> list[tuple[str, str]]:  # fmt: skip
        b = number_words(text)
        words = [i for p in (phrase, *more) for i in span(b, p)]
        d = draft("plate", [*plate_items(b),
                            {"id": "label", "kind": "text", "words": cite(b, "letters"),
                             "on": {"item": "plate", "face": "+z"},
                             "text": {"text": lettering, "from": {"words": words}},
                             "height": mm(b, 8, "8 mm"), "depth": mm(b, 1, "1 mm"),
                             "mode": choose("engrave", said(b, "engraved")),
                             "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}}])  # fmt: skip
        return [
            (k, m)
            for k, m in found(check_draft(b, d))
            if k == "fault" or not faults_only
        ]

    PLAIN = "A plate 60 mm long, 40 mm wide and 5 mm thick, engraved with the letters ACME, INC. 8 mm tall and 1 mm deep."
    QUOTED = 'A plate 60 mm long, 40 mm wide and 5 mm thick, engraved with the letters "NO STEP!" 8 mm tall and 1 mm deep.'

    def test_punctuation_and_all(self) -> None:
        self.assertEqual(self.label(self.PLAIN, "ACME, INC.", "ACME, INC"), [])
        self.assertEqual(
            self.label(self.PLAIN, "ACME, INC", "ACME, INC"), []
        )  # the sentence's full stop
        self.assertEqual(self.label(self.PLAIN, "ACME INC", "ACME, INC"),
                         [("fault", "'ACME INC' is not exactly what the cited words say ('ACME, INC')")])  # fmt: skip

    def test_a_comma_after_the_words_is_the_sentence_s(self) -> None:
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick, with the letters FORGE-2, engraved 8 mm tall and 1 mm deep."
        self.assertEqual(self.label(text, "FORGE-2", "FORGE-2"), [])
        self.assertEqual(self.label(text, "FORGE-2,", "FORGE-2")[0][0], "fault")

    def test_a_quotation_is_taken_whole(self) -> None:
        self.assertEqual(self.label(self.QUOTED, "NO STEP!", "NO STEP"), [])
        self.assertEqual(self.label(self.QUOTED, "NO STEP", "NO STEP"),
                         [("fault", "'NO STEP' is not exactly what the cited words say ('NO STEP!')")])  # fmt: skip
        self.assertEqual(self.label(self.QUOTED, "STEP", "STEP"),
                         [("fault", "the text is part of a quotation: cite all of it, and only it")])  # fmt: skip

    def test_words_from_different_places_are_not_a_text(self) -> None:
        text = ('A plate 60 mm long, 40 mm wide and 5 mm thick, engraved with the letters "TOP" and "SIDE", '
                "8 mm tall and 1 mm deep.")  # fmt: skip
        self.assertEqual(self.label(text, "TOP SIDE", "TOP", "SIDE"),
                         [("fault", "cite the text's words as one run, with nothing left out between")])  # fmt: skip

    def test_the_numbers_in_a_text_are_letters(self) -> None:
        # Short enough to fit the plate in the pinned font (docs/definitions/text.md).
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick, engraved with the letters SN 42 8 mm tall and 1 mm deep."
        self.assertEqual(self.label(text, "SN 42", "SN 42", faults_only=False), [])


class AChoiceCantCiteWhatDeniesIt(unittest.TestCase):
    def slot(self, text: str, ends: str, phrase: str) -> list[str]:
        b = number_words(text)
        d = draft("plate", [*plate_items(b),
                            {"id": "slot", "kind": "slot", "words": cite(b, "slot"), "on": {"item": "plate", "face": "+z"},
                             "width": mm(b, 4, "4 mm"), "length": mm(b, 20, "20 mm"),
                             "along": choose("x", assumed("t")), "ends": choose(ends, {"words": span(b, phrase)}),
                             "depth": {"through": True, "from": said(b, "through")},
                             "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}}])  # fmt: skip
        return messages(check_draft(b, d), "fault")

    TEXT = "A plate 60 mm long, 40 mm wide and 5 mm thick with a 4 mm slot 20 mm long through it, square, not rounded."

    def test_a_negated_option(self) -> None:
        self.assertEqual(
            self.slot(self.TEXT, "round", "not rounded"),
            ["the cited words ('not rounded') rule out round"],
        )
        self.assertEqual(self.slot(self.TEXT, "square", "square, not rounded"), [])
        without = "A plate 60 mm long, 40 mm wide and 5 mm thick with a 4 mm slot 20 mm long through it without round ends."
        self.assertEqual(self.slot(without, "round", "without round ends"),
                         ["the cited words ('without round ends') rule out round"])  # fmt: skip

    def test_a_times_sign_is_not_the_x_axis(self) -> None:
        b = number_words(
            "A plate 60 x 40 x 5 mm with two 4 mm holes 20 mm apart across the 40 x 5 mm end face."
        )
        d = draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60"),
             "width": mm(b, 40, "40"), "height": mm(b, 5, "5 mm")},
            {"id": "h", "kind": "hole", "words": cite(b, "holes"), "on": {"item": "plate", "face": "+x"},
             "diameter": mm(b, 4, "4 mm"), "depth": assumed("t", 5), "count": count(b, 2, "two"),
             "place": {"z": {"centred": assumed("t")},
                       "pattern": {"row": {"axis": choose("y", said(b, "across the 40 x 5 mm end face")),
                                           "pitch": mm(b, 20, "20 mm"), "count": count(b, 2, "two")}}}},
        ])  # fmt: skip
        self.assertEqual(messages(check_draft(b, d), "fault"), [])


class AStandardPartIsNamedWhole(unittest.TestCase):
    def hole(self, text: str, diameter: Any) -> list[str]:
        b = number_words(text)
        d = draft("cube", [
            {"id": "cube", "kind": "block", "words": cite(b, "cube"), "length": mm(b, 20, "20 mm"),
             "width": mm(b, 20, "20 mm"), "height": mm(b, 20, "20 mm")},
            {"id": "h", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "cube", "face": "+z"},
             "diameter": diameter(b), "depth": {"through": True, "from": said(b, "straight through")},
             "place": {"x": {"centred": said(b, "its centre")}, "y": {"centred": said(b, "its centre")}}},
        ])  # fmt: skip
        return messages(check_draft(b, d), "fault")

    FINE = "A 20 mm cube with an M8 x 1 tapped hole straight through its centre."

    def test_a_designation_written_over_three_words(self) -> None:
        def tapped(target: str, phrase: str) -> Any:
            return lambda b: {
                "fit": "tapped",
                "for": target,
                "from": {"words": span(b, phrase)},
            }

        def table(b: NumberedBrief) -> dict[str, Any]:
            return {
                "value": 7,
                "unit": "mm",
                "from": {"table": "tapped:M8x1", "words": span(b, "M8 x 1")},
            }

        self.assertEqual(self.hole(self.FINE, tapped("M8x1", "M8 x 1")), [])
        self.assertEqual(self.hole(self.FINE, table), [])
        self.assertEqual(self.hole(self.FINE, tapped("M8", "M8 x 1")),
                         ["the brief gives M8 x 1: say its pitch, M8x1"])  # fmt: skip
        # Citing "M8" alone would drill 6.8 mm for an M8 x 1 thread, which needs 7 mm.
        self.assertEqual(
            self.hole(self.FINE, tapped("M8", "M8")),
            ["the brief gives M8 x 1: cite all of it"],
        )

    def test_a_bolt_s_length_is_not_its_pitch(self) -> None:
        def clearance(b: NumberedBrief) -> dict[str, Any]:
            return {"fit": "clearance", "for": "M8", "from": {"words": span(b, "M8")}}

        text = "A 20 mm cube with a clearance hole straight through its centre for an M8 x 30 bolt."
        self.assertEqual(self.hole(text, clearance), [])

    def test_grade_words_hyphenated_or_denied(self) -> None:
        def fit(grade: str, phrase: str) -> Any:
            return lambda b: {
                "fit": "clearance",
                "for": "M5",
                "grade": grade,
                "from": {"words": span(b, phrase)},
            }

        for words, grade in (("close-fit", "fine"), ("free-fit", "coarse")):
            text = f"A 20 mm cube with a {words} clearance hole for an M5 screw straight through its centre."
            self.assertEqual(
                self.hole(text, fit(grade, f"{words} clearance hole for an M5")),
                [],
                words,
            )
        text = "A 20 mm cube with a clearance hole for an M5 screw, not a close fit, straight through its centre."
        self.assertEqual(self.hole(text, fit("fine", "M5 screw, not a close fit")),
                         ["a fine clearance, but the brief doesn't say how close"])  # fmt: skip
        self.assertEqual(
            self.hole(text, fit("normal", "M5 screw, not a close fit")), []
        )


# ----------------------------------------------------------------------
# Placement
# ----------------------------------------------------------------------
class CopiesNeverLandOnEachOther(unittest.TestCase):
    big = item("b", "block", length=a(100), width=a(100), height=a(10))

    def holes(self, pattern: dict[str, Any]) -> list[tuple[str, str]]:
        return issues(
            layout_of(
                self.big, hole("b", "+z", 4, depth=a(2), place={"pattern": pattern})
            )
        )

    def test_an_arc_that_comes_round_again(self) -> None:
        for count_, step in ((5, 90), (3, 360), (3, 180), (4, 0)):
            arc = {"arc": {"diameter": a(40), "count": {"count": count_, "from": {"words": [2, 3]}},
                           "step": a(step, "deg"), "start": a(0, "deg")}}  # fmt: skip
            self.assertIn("land on each other", self.holes(arc)[0][1], (count_, step))
        quarter = {"arc": {"diameter": a(40), "count": {"count": 4, "from": {"words": [2, 3]}},
                           "step": a(-90, "deg"), "start": a(0, "deg")}}  # fmt: skip
        self.assertEqual(self.holes(quarter), [])

    def test_a_rectangle_checks_each_axis(self) -> None:
        slots = item("s", "slot", on=on("b", "+z"), width=a(2), length=a(30), along=pick("x"),
                     ends=pick("square"), depth=a(2), place={"pattern": {"rectangle": {"x": a(10), "y": a(5)}}})  # fmt: skip
        self.assertIn("overlap", issues(layout_of(self.big, slots))[0][1])

    def test_round_a_side_where_they_come_closest(self) -> None:
        collar = item(
            "c",
            "tube",
            outer_diameter=a(25),
            inner_diameter=a(12),
            length=a(15),
            axis=pick("z"),
        )

        def side_holes(d: float, n_: int, **fields: Any) -> list[tuple[str, str]]:
            ring = hole("c", "side", d, place={"z": centred(), "angle": a(0, "deg"),
                                                "pattern": {"circle": {"count": {"count": n_, "from": {"words": [2, 3]}}}}},
                        **fields)  # fmt: skip
            return issues(layout_of(collar, ring))

        self.assertEqual(
            side_holes(10, 12)[0][0], "question"
        )  # 6.5 mm apart outside: they overlap
        # Through the wall, 4 mm holes 6.5 mm apart outside are 3.1 mm apart at the bore.
        self.assertEqual(side_holes(4, 12),
                         [("question", "copies 1 and 2 of h overlap where they meet, 6 mm from the axis")])  # fmt: skip
        self.assertEqual(side_holes(2, 12), [])
        self.assertEqual(
            side_holes(4, 12, depth=a(1)), []
        )  # blind, 1 mm deep: 6 mm apart at the bottom

    def test_through_a_solid_rod_and_out_the_far_side(self) -> None:
        pin = item("p", "cylinder", diameter=a(10), length=a(30), axis=pick("z"))

        def cross(step: float) -> list[tuple[str, str]]:
            holes = hole("p", "side", 3, place={"z": centred(), "angle": a(0, "deg"), "pattern": {"arc": {
                "count": {"count": 2, "from": {"words": [2, 3]}}, "step": a(step, "deg")}}})  # fmt: skip
            return issues(layout_of(pin, holes))

        self.assertEqual(
            cross(90), []
        )  # a cross-drilled pin: they cross at the axis, as meant
        self.assertEqual(
            cross(180), [("question", "copies 1 and 2 of h land on each other")]
        )  # one hole, twice
        self.assertEqual(
            cross(170)[0][0], "question"
        )  # each comes out by the other's mouth

    def test_ribs_round_a_rod_are_compared_around_and_along(self) -> None:
        rod = item("c", "cylinder", diameter=a(30), length=a(60), axis=pick("z"))
        ribs = item("r", "rib", on=on("c", "side"), length=a(40), thickness=a(2), height=a(5), along=pick("z"),
                    place={"z": centred(), "angle": a(0, "deg"),
                           "pattern": {"circle": {"count": {"count": 4, "from": {"words": [2, 3]}}}}})  # fmt: skip
        self.assertEqual(
            issues(layout_of(rod, ribs)), []
        )  # 21 mm apart round the rod, 40 mm long along it

    def test_a_quarter_turn_lands_exactly_on_the_axis(self) -> None:
        ring = hole("b", "+z", 4, depth=a(2), place={"pattern": {"circle": {"diameter": a(40), "count": {"count": 4, "from": {"words": [2, 3]}}}}})  # fmt: skip
        origins = sorted(h.origin[:2] for h in layout_of(self.big, ring).instances["h"])
        self.assertEqual(
            origins, [(-20.0, 0.0), (0.0, -20.0), (0.0, 20.0), (20.0, 0.0)]
        )


class WhatStandsOrCutsFitsTheRoomItHas(unittest.TestCase):
    def test_a_pocket_right_through_has_no_floor(self) -> None:
        def stand_in(depth: dict[str, Any]) -> list[tuple[str, str]]:
            pocket = item("p", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(30), width=a(20),
                          depth=depth, place={"x": centred(), "y": centred()})  # fmt: skip
            boss = item("k", "boss", on=on("p", "bottom"), diameter=a(6), height=a(10),
                        place={"x": centred(), "y": centred()})  # fmt: skip
            return issues(layout_of(PLATE, pocket, boss))

        floorless = (
            "p (4 mm deep) goes right through the 4 mm of material; it has no bottom"
        )
        self.assertEqual(
            stand_in(a(4)), [("question", floorless)]
        )  # the brief says both: the person's call
        self.assertEqual(stand_in(guess(4)), [("fault", floorless + ASSUMED)])

    def test_inside_a_sealed_box_up_to_its_lid(self) -> None:
        box = item("box", "block", length=a(60), width=a(40), height=a(30))
        sealed = item(
            "s",
            "shell",
            of="box",
            thickness=a(2),
            open={"faces": [], "from": assumed("sealed")},
        )

        def post(height: float) -> list[tuple[str, str]]:
            inside = item("p", "post", on=on("box", "inner -z"), length=a(5), width=a(5), height=a(height),
                          place={"x": centred(), "y": centred()})  # fmt: skip
            return issues(layout_of(box, sealed, inside))

        self.assertEqual(post(26), [])
        self.assertEqual(
            post(40),
            [
                (
                    "question",
                    "p (40 mm) rises past the far wall of the hollow it stands in (26 mm)",
                )
            ],
        )

    def test_the_rim_of_an_open_box_is_not_a_face_yet(self) -> None:
        box = item("box", "block", length=a(60), width=a(40), height=a(30))
        rim = hole(
            "box", "+z", 2.5, depth=a(8), place={"x": at("+x", 2), "y": at("+y", 2)}
        )
        self.assertEqual(kinds(layout_of(box, shell("box", 4, "+z"), rim)), ["unable"])

    def test_one_host_copy_takes_every_partner(self) -> None:
        bosses = item("b", "boss", on=on("plate", "+z"), diameter=a(10), height=a(5),
                      place={"x": centred(), "y": centred(), "pattern": {"rectangle": {"x": a(40), "y": a(30)}}})  # fmt: skip
        # Blind: right through the plate, each would come out under its boss, a question of its own (place.md).
        below = hole(
            "plate",
            "-z",
            3,
            depth=a(2),
            place={
                "concentric": {"item": "b", "from": assumed("a hole under each boss")}
            },
        )
        layout = layout_of(PLATE, bosses, below)
        self.assertEqual(issues(layout), [])
        self.assertEqual(sorted(h.origin[:2] for h in layout.instances["h"]),
                         [(-20.0, -15.0), (-20.0, 15.0), (20.0, -15.0), (20.0, 15.0)])  # fmt: skip

    def test_round_a_rod_along_y_every_copy_is_the_same_way_round(self) -> None:
        rod = item("c", "cylinder", diameter=a(30), length=a(40), axis=pick("y"))
        posts = item("p", "post", on=on("c", "side"), length=a(4), width=a(10), height=a(5),
                     place={"y": centred(), "angle": a(0, "deg"),
                            "pattern": {"circle": {"count": {"count": 4, "from": {"words": [2, 3]}}}}})  # fmt: skip
        layout = layout_of(rod, posts)
        self.assertEqual(issues(layout), [])
        for copy in layout.instances["p"]:
            assert copy.lo is not None and copy.hi is not None
            size = [round(copy.hi[k] - copy.lo[k], 9) for k in range(3)]
            self.assertEqual(
                size[1], 10.0
            )  # its width runs along the rod on every copy
            self.assertEqual(sorted(size), [4.0, 5.0, 10.0])

    def test_recesses_that_leave_no_hole(self) -> None:
        deep = hole("plate", "+z", 4, counterbore={"diameter": a(8), "depth": a(4)})
        self.assertIn(
            "it leaves no hole below it", issues(layout_of(PLATE, deep))[0][1]
        )
        blind = hole(
            "plate", "+z", 2, depth=a(2), counterbore={"diameter": a(6), "depth": a(3)}
        )
        self.assertIn(
            "there's no hole left below it", issues(layout_of(PLATE, blind))[0][1]
        )
        both = hole("plate", "+z", 4, counterbore={"diameter": a(8), "depth": a(2)},
                    countersink={"diameter": a(9), "angle": a(90, "deg")})  # fmt: skip
        self.assertEqual(kinds(layout_of(PLATE, both)), ["unable"])

    def test_a_hole_in_a_body_runs_on_into_what_it_stands_on(self) -> None:
        body = item("k", "cylinder", on=on("plate", "+z"), diameter=a(10), length=a(5),
                    place={"x": centred(), "y": centred()})  # fmt: skip
        self.assertEqual(
            issues(layout_of(PLATE, body, hole("k", "+end", 3, depth=a(7)))), []
        )


class AProblemGoesToWhoeverCanFixIt(unittest.TestCase):
    def depth(self, text: str, sizes: Any) -> list[str]:
        b = number_words(text + " " + NO_LOAD)
        d = draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "steel plate"), **sizes(b)},
            {"id": "h", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "plate", "face": "+z"},
             "diameter": mm(b, 6, "6 mm"), "depth": mm(b, 10, "10 mm"),
             "place": {"x": {"centred": said(b, "the middle")}, "y": {"centred": said(b, "the middle")}}},
        ], material=made_of(b, "steel"),
            silent=[{"sentence": 1, "reason": "no load case"}])  # fmt: skip
        return [p.kind for p in check_draft(b, d).problems if "deep in" in p.message]

    def test_by_what_the_depth_rests_on(self) -> None:
        # The writer assumed the thickness: the writer's to fix.
        self.assertEqual(self.depth(
            "A steel plate 70 mm long and 50 mm wide with a 6 mm hole 10 mm deep in the middle.",
            lambda b: {"length": mm(b, 70, "70 mm"), "width": mm(b, 50, "50 mm"), "height": assumed("t", 4)}),
            ["fault"])  # fmt: skip
        # The brief gives both: the person's question, however the unrelated length was found.
        self.assertEqual(self.depth(
            "A steel plate 50 mm wide and 4 mm thick with a 6 mm hole 10 mm deep in the middle.",
            lambda b: {"length": assumed("t", 70), "width": mm(b, 50, "50 mm"), "height": mm(b, 4, "4 mm")}),
            ["question"])  # fmt: skip

    def test_a_count_the_brief_s_own_pattern_contradicts(self) -> None:
        b = number_words("A plate 60 mm square and 3 mm thick, with eight 6 mm holes in a 3 by 3 grid on 18 mm "
                         "centres, centred on the plate.")  # fmt: skip
        d = draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm"),
             "width": mm(b, 60, "60 mm"), "height": mm(b, 3, "3 mm")},
            {"id": "h", "kind": "hole", "words": cite(b, "holes"), "on": {"item": "plate", "face": "+z"},
             "diameter": mm(b, 6, "6 mm"), "depth": {"through": True, "from": assumed("t")},
             "count": count(b, 8, "eight"),
             "place": {"x": {"centred": said(b, "centred on the plate")}, "y": {"centred": said(b, "centred on the plate")},
                       "pattern": {"grid": {"count_x": count(b, 3, "3", 2), "count_y": count(b, 3, "3", 3),
                                            "pitch_x": mm(b, 18, "18 mm"), "pitch_y": mm(b, 18, "18 mm")}}}},
        ])  # fmt: skip
        self.assertIn(
            ("question", "the count is 8, but the placement makes 9 h"),
            found(check_draft(b, d)),
        )


# ----------------------------------------------------------------------
# Roundings, regions and what an automatic run may leave out
# ----------------------------------------------------------------------
class AJointRoundingFitsTheCornerItFills(unittest.TestCase):
    # V1 corpus R09: the L-bracket, its upright flush with the back end of the base.
    base = item("base", "block", length=a(50), width=a(40), height=a(5))
    upright = item("up", "block", on=on("base", "+z"), length=a(5), width=a(40), height=a(35),
                   place={"x": at("+x", 0, "edge"), "y": centred()})  # fmt: skip

    def problems(self, *items: dict[str, Any]) -> list[tuple[str, str]]:
        report = check_draft(number_words(R05), draft("t", list(items)))
        return [
            (p.kind, p.message)
            for p in report.problems
            if p.at.startswith("/items") and "cited words" not in p.message
        ]

    def joint(self, of: str, meets: str, radius: float) -> dict[str, Any]:
        return item(
            "f",
            "fillet",
            edges={"of": of, "which": "joint", "where_meets": meets},
            radius=a(radius),
        )

    def test_up_the_upright_and_out_over_the_base(self) -> None:
        self.assertEqual(
            self.problems(self.base, self.upright, self.joint("up", "base", 5)), []
        )
        self.assertEqual(self.problems(self.base, self.upright, self.joint("up", "base", 100)),
                         [("cant", "a 100 mm fillet doesn't fit where up meets base (at most 35 mm)")])  # fmt: skip

    def test_the_face_left_beyond_it_bounds_it(self) -> None:
        near = item("up", "block", on=on("base", "+z"), length=a(5), width=a(40), height=a(35),
                    place={"x": at("+x", 3, "edge"), "y": centred()})  # fmt: skip
        self.assertEqual(self.problems(self.base, near, self.joint("base", "up", 4)),
                         [("cant", "a 4 mm fillet doesn't fit where base meets up (at most 3 mm)")])  # fmt: skip

    def test_two_items_that_don_t_stand_on_each_other(self) -> None:
        boss = item(
            "k",
            "boss",
            on=on("plate", "+z"),
            diameter=a(10),
            height=a(5),
            place={"x": centred(), "y": centred()},
        )
        under = item(
            "u", "block", on=on("plate", "-z"), length=a(5), width=a(5), height=a(5)
        )
        self.assertEqual(self.problems(PLATE, boss, under, self.joint("k", "u", 1)),
                         [("fault", "k and u don't meet: a joint is where one stands on the other")])  # fmt: skip

    def test_flush_all_round_there_is_no_corner(self) -> None:
        stacked = item(
            "top", "block", on=on("base", "+z"), length=a(50), width=a(40), height=a(5)
        )
        self.assertEqual(self.problems(self.base, stacked, self.joint("top", "base", 1)),
                         [("cant", "top is flush with every edge of the +z face of base: where they meet there is "
                                   "no inside corner to round")])  # fmt: skip


class ARegionsWallFitsItsEnvelope(unittest.TestCase):
    def test_min_wall(self) -> None:
        b = number_words("A plate 60 mm long, 40 mm wide and 5 mm thick with a lattice post 20 mm square and 30 mm "
                         "tall on top, no wall under 500 mm.")  # fmt: skip
        region = {"id": "lattice", "kind": "region", "words": cite(b, "lattice post"), "on": {"item": "plate", "face": "+z"},
                  "length": mm(b, 20, "20 mm"), "width": mm(b, 20, "20 mm"), "height": mm(b, 30, "30 mm"),
                  "min_wall": mm(b, 500, "500 mm"), "describe": {"text": "lattice post", "from": said(b, "lattice post")},
                  "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}}  # fmt: skip
        report = check_draft(b, draft("plate", [*plate_items(b), region]))
        self.assertIn(
            ("cant", "a 500 mm wall can't fit in a region 20 mm across"), found(report)
        )


class AnAutomaticRunLeavesNoShapeOut(unittest.TestCase):
    def test_not_modelled_holding_a_number_or_a_shape(self) -> None:
        b, d = plate_draft()
        d["items"] = d["items"][:1]
        d["not_modelled"].append(
            {"words": cite(b, "Four 4 mm holes"), "reason": "left for a later version"}
        )
        strict = messages(check_draft(b, d, strict=True), "question")
        self.assertIn("an automatic run can't leave out what the brief says of the shape: 'Four', '4', 'holes'",
                      strict)  # fmt: skip
        self.assertNotIn("an automatic run", " ".join(messages(check_draft(b, d))))

    def test_the_material_may_still_be_left_out(self) -> None:
        b, d = plate_draft()
        self.assertFalse(
            [
                m
                for m in messages(check_draft(b, d, strict=True))
                if "can't leave out" in m
            ]
        )


# ----------------------------------------------------------------------
# What the person sees, and what the lock covers
# ----------------------------------------------------------------------
class NothingTheModelWritesAddsALine(unittest.TestCase):
    def test_control_and_invisible_characters(self) -> None:
        for sneaky in (
            "\n",
            "\t",
            "\u2028",
            "\u2029",
            "\u202e",
            "\u2066",
            "\u200b",
            "\ufeff",
            "\x85",
        ):
            b, d = plate_draft()
            d["name"] = f"mounting plate{sneaky}Nothing is assumed."
            d["silent"][0]["reason"] = f"no load{sneaky}3. 4 x hole extra"
            d["items"][1]["place"]["x"]["centred"]["assumed"] = (
                f"centred{sneaky}1. Block plate"
            )
            faults = [p.at for p in check_draft(b, d).problems if p.kind == "fault"]
            self.assertEqual(
                sorted(faults),
                ["/items/1/place/x/centred/assumed", "/name", "/silent/0/reason"],
                repr(sneaky),
            )


class EveryNumberShowsExactly(unittest.TestCase):
    def test_two_numbers_never_print_alike(self) -> None:
        self.assertNotEqual(_n(33.333333333333336), _n(33.33333333))
        self.assertEqual([_n(x) for x in (0.0, -0.0, 3.0, 12.7, 0.1 + 0.2, 1e-7)],
                         ["0", "0", "3", "12.7", "0.30000000000000004", "1e-07"])  # fmt: skip

    def test_a_ball_on_a_face_says_it_is_half_sunk(self) -> None:
        b = number_words(
            "A rod 8 mm across and 50 mm long with a 12 mm ball on its end."
        )
        d = draft("rod", [
            {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": mm(b, 8, "8 mm"),
             "length": mm(b, 50, "50 mm"), "axis": choose("z", assumed("t"))},
            {"id": "ball", "kind": "sphere", "words": cite(b, "ball"), "on": {"item": "rod", "face": "+end"},
             "diameter": mm(b, 12, "12 mm"), "portion": choose("whole", said(b, "ball")),
             "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}},
        ])  # fmt: skip
        text = render(check_draft(b, d), b).text()
        self.assertIn(
            "Ball ball (whole): \u00d812 mm, its centre on the +end face of rod (half sunk into it)",
            text,
        )


class TheLockCoversWhatItHandsOn(unittest.TestCase):
    def test_another_layout_or_one_changed_in_place(self) -> None:
        b, d = flange_draft()
        confirmed = lock(check_draft(b, d), b, by="person", strict=False)
        other = check_draft(*plate_draft()).layout
        assert other is not None
        with self.assertRaises(LockError):
            dataclasses.replace(confirmed, _layout=other).check()
        # What it hands out is a copy: changing it changes nothing confirmed.
        handed = confirmed.layout
        handed.instances["bolt_holes"].pop()
        handed.diameters["bolt_holes"] = 99.0
        confirmed.check()
        self.assertEqual(len(confirmed.layout.instances["bolt_holes"]), 4)
        self.assertEqual(confirmed.layout.diameters["bolt_holes"], 8.0)

    def test_what_the_person_was_shown_is_the_spec_s(self) -> None:
        b, d = flange_draft()
        report = check_draft(b, d)
        self.assertTrue(report.assumptions)
        with self.assertRaises(LockError):
            lock(
                dataclasses.replace(report, assumptions=()),
                b,
                by="person",
                strict=False,
            )

    def test_a_brief_whose_words_are_another_brief_s(self) -> None:
        b, d = plate_draft()
        forged = NumberedBrief(
            text=R05.replace("70 mm", "3 in"), words=b.words, sentences=b.sentences
        )
        with self.assertRaises(LockError):
            lock(check_draft(forged, d), forged, by="person", strict=False)

    def test_how_strictly_is_the_caller_s_word(self) -> None:
        b, d = plate_draft()
        relabelled = dataclasses.replace(
            check_draft(b, d, strict=True), strict=False, problems=()
        )
        confirmed = lock(relabelled, b, by="person", strict=False)
        self.assertFalse(confirmed.strict)
        self.assertNotEqual(
            confirmed.digest, spec_digest(confirmed.spec, b, "person", strict=True)
        )
        with self.assertRaises(LockError):
            lock(relabelled, b, by="person", strict=True)


if __name__ == "__main__":
    unittest.main()
