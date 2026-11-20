"""V2 stage 1: what the third review of the spec contract found, pinned.

The third round went after the fixes of the second. Each test is one
finding, fixed at its root. The briefs are written for these tests (or are
V1 corpus briefs, validation/SUITE.md); none comes from a blind set.

- **No number hides:** a standard part's name uses only its own numbers
  ("4xM3" leaves the 4 to a count), a description uses none, and letters
  use theirs only when the brief marks them as letters.
- **An automatic run leaves out only what can't be a shape:** materials,
  colours, finishes, loads; everything else is a question.
- **A denial reaches to the end of its clause**, and a choice read from
  words that don't name it is shown as the assumption it is.
- **A text is the brief's**: a whole quotation, a whole run of capitals.
- **A tolerance sits next to its value.**
- **Placement:** every copy is checked however many there are, round sides
  are routed by the value that binds, and holes are compared where they
  come closest.
- **What the person sees is what is locked**, in one spelling, one line each.
"""

from __future__ import annotations

import dataclasses
import sys
import time
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.citations import check_quantity
from forge_spec.lock import LockError, lock, spec_digest
from forge_spec.render import render
from forge_spec.words import NumberedBrief
from forge_units import Q

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_spec_partspec import R05, flange_draft, plate_draft
from test_v2_spec_placement import (
    ASSUMED,
    PLATE,
    a,
    centred,
    guess,
    hole,
    issues,
    item,
    layout_of,
    on,
    pick,
    shell,
)
from v2_drafts import assumed, choose, cite, count, draft, mm, said, span


def found(report: SpecReport) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in report.problems]


def messages(report: SpecReport, kind: str | None = None) -> list[str]:
    return [p.message for p in report.problems if kind in (None, p.kind)]


def plate(
    b: NumberedBrief, length: float = 60, width: float = 40, height: float = 5
) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, length, f"{length:g} mm"),
            "width": mm(b, width, f"{width:g} mm"), "height": mm(b, height, f"{height:g} mm")}  # fmt: skip


def middle() -> dict[str, Any]:
    return {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}


# ----------------------------------------------------------------------
# No number hides
# ----------------------------------------------------------------------
class ANameUsesOnlyItsOwnNumbers(unittest.TestCase):
    def holes(self, text: str, diameter: Any, **fields: Any) -> list[tuple[str, str]]:
        b = number_words(text)
        d = draft("plate", [plate(b), {"id": "h", "kind": "hole", "words": cite(b, "holes"),
                                       "on": {"item": "plate", "face": "+z"}, "diameter": diameter(b),
                                       "depth": {"through": True, "from": assumed("t")}, "place": middle(),
                                       **{k: v(b) for k, v in fields.items()}}])  # fmt: skip
        return found(check_draft(b, d))

    def test_a_count_joined_to_the_name(self) -> None:
        text = (
            "A plate 60 mm long, 40 mm wide and 5 mm thick with 4xM3 clearance holes."
        )

        def fit(b: NumberedBrief) -> dict[str, Any]:
            return {"fit": "clearance", "for": "M3", "from": said(b, "4xM3")}

        # One hole, and nothing says the brief asked for four: before, the name swallowed the 4.
        self.assertIn(("question", "the brief says '4' (in '4xM3', sentence 1); nothing in the spec uses it"),
                      self.holes(text, fit))  # fmt: skip
        self.assertNotIn(
            "4xM3",
            " ".join(
                m for _, m in self.holes(text, fit, count=lambda b: count(b, 4, "4xM3"))
            ),
        )

    def test_a_length_joined_to_the_name(self) -> None:
        text = (
            "A plate 60 mm long, 40 mm wide and 5 mm thick with holes for M5x16 screws."
        )

        def fit(b: NumberedBrief) -> dict[str, Any]:
            return {"fit": "clearance", "for": "M5", "from": said(b, "M5x16")}

        self.assertIn(("question", "the brief says '16' (in 'M5x16', sentence 1); nothing in the spec uses it"),
                      self.holes(text, fit))  # fmt: skip

    def test_a_bearing_s_count(self) -> None:
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick with holes for 2x608 bearings."

        def seat(b: NumberedBrief) -> dict[str, Any]:
            return {"fit": "bearing_seat", "for": "608", "from": said(b, "2x608")}

        self.assertIn(("question", "the brief says '2' (in '2x608', sentence 1); nothing in the spec uses it"),
                      self.holes(text, seat))  # fmt: skip


class ADescriptionUsesNoNumber(unittest.TestCase):
    BRIEF = ("A plate 60 mm long, 40 mm wide and 5 mm thick. Four 4 mm holes pass through the plate, one near "
             "each corner, with their centres on a 56 mm by 36 mm rectangle.")  # fmt: skip

    def test_a_region_described_by_a_sentence_of_the_brief(self) -> None:
        b = number_words(self.BRIEF)
        sentence = "Four 4 mm holes pass through the plate, one near each corner, with their centres on a 56 mm by 36 mm rectangle"
        region = {"id": "later", "kind": "region", "words": cite(b, "holes"), "on": {"item": "plate", "face": "+z"},
                  "length": assumed("t", 1), "width": assumed("t", 1), "height": assumed("t", 1),
                  "describe": {"text": sentence, "from": {"words": span(b, sentence)}}, "place": middle()}  # fmt: skip
        unused = [
            m
            for m in messages(check_draft(b, draft("p", [plate(b), region])))
            if "nothing in the spec uses" in m
        ]
        self.assertEqual(
            len(unused), 5
        )  # Four, 4, one, 56, 36: each still to be used by a value

    def test_letters_use_their_numbers_only_when_marked_as_letters(self) -> None:
        def engrave(text: str, letters: str) -> list[str]:
            b = number_words(text)
            label = {"id": "label", "kind": "text", "words": cite(b, "engraved"), "on": {"item": "plate", "face": "+z"},
                     "text": {"text": letters, "from": {"words": span(b, letters)}},
                     "height": assumed("t", 5), "depth": assumed("t", 0.5),
                     "mode": choose("engrave", said(b, "engraved")), "place": middle()}  # fmt: skip
            report = check_draft(b, draft("p", [plate(b), label]))
            return [m for m in messages(report) if "nothing in the spec uses" in m]

        base = "A plate 60 mm long, 40 mm wide and 5 mm thick, engraved with "
        self.assertEqual(engrave(base + "PART 42.", "PART 42"), [])
        self.assertEqual(engrave(base + '"part 42".', "part 42"), [])
        self.assertEqual(engrave(base + "four 4 mm holes.", "four 4 mm holes"),
                         ["the brief says 'four' (sentence 1); nothing in the spec uses it",
                          "the brief says '4' (sentence 1); nothing in the spec uses it"])  # fmt: skip


# ----------------------------------------------------------------------
# An automatic run leaves out only what can't be a shape
# ----------------------------------------------------------------------
class AnAutomaticRunLeavesOutOnlyWhatCantBeAShape(unittest.TestCase):
    def left_out(self, words: str, *, silent: bool = False) -> list[str]:
        b = number_words(
            f"A rod 10 mm across and 50 mm long, in black PLA, with {words}. It carries no load."
        )
        rod = {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": mm(b, 10, "10 mm"),
               "length": mm(b, 50, "50 mm"), "axis": choose("z", assumed("t"))}  # fmt: skip
        nm = [{"words": cite(b, "black PLA"), "reason": "the material"}]
        if not silent:
            nm.append({"words": span(b, words), "reason": "left for later"})
        quiet = [{"sentence": 1, "reason": "no load"}]
        d = draft("rod", [rod], not_modelled=nm, silent=quiet)
        return [
            m
            for m in messages(check_draft(b, d, strict=True))
            if "an automatic run" in m
        ]

    def test_any_word_that_isn_t_known_to_say_nothing_of_the_shape(self) -> None:
        for feature in ("a keyway", "cooling fins", "a cross-drilled end", "a hex socket", "a dovetail",
                        "a round-ended keyway"):  # fmt: skip
            self.assertTrue(self.left_out(feature), feature)

    def test_the_material_and_a_load_sentence_may_be_left_out(self) -> None:
        self.assertEqual(self.left_out("a polished, anodised finish"), [])
        self.assertEqual(
            self.left_out("a satin finish", silent=True), []
        )  # "It carries no load." as silent

    def test_a_shape_sentence_can_t_be_taken_as_silent(self) -> None:
        b = number_words(
            "A box 60 mm long, 40 mm wide and 30 mm tall. The top is completely open."
        )
        box = {"id": "box", "kind": "block", "words": cite(b, "box"), "length": mm(b, 60, "60 mm"),
               "width": mm(b, 40, "40 mm"), "height": mm(b, 30, "30 mm")}  # fmt: skip
        d = draft("box", [box], silent=[{"sentence": 1, "reason": "nothing to model"}])
        self.assertIn("an automatic run can't take as silent a sentence that may say something of the shape: "
                      "'top', 'completely', 'open'", messages(check_draft(b, d, strict=True)))  # fmt: skip

    def test_an_assumption_the_item_s_own_words_contradict(self) -> None:
        b = number_words(
            "A roller 30 mm in diameter and 50 mm long, lying on its side with its axis along X."
        )
        roller = {"id": "roller", "kind": "cylinder", "words": cite(b, "roller") + cite(b, "axis along X"),
                  "diameter": mm(b, 30, "30 mm"), "length": mm(b, 50, "50 mm"),
                  "axis": choose("z", assumed("upright"))}  # fmt: skip
        said_ = "roller.axis: z is assumed, but the item's words say x ('X')"
        strict = check_draft(b, draft("r", [roller]), strict=True)
        self.assertIn(("question", said_), found(strict))
        normal = check_draft(b, draft("r", [roller]))
        self.assertIn(said_, [p.message for p in normal.caveats])


# ----------------------------------------------------------------------
# Choices and denials
# ----------------------------------------------------------------------
class ADenialReachesToTheEndOfItsClause(unittest.TestCase):
    def ends(self, text: str, ends: str, phrase: str) -> list[str]:
        b = number_words(
            f"A plate 60 mm long, 40 mm wide and 5 mm thick with a 4 mm slot 20 mm long through it, {text}."
        )
        slot = {"id": "slot", "kind": "slot", "words": cite(b, "slot"), "on": {"item": "plate", "face": "+z"},
                "width": mm(b, 4, "4 mm"), "length": mm(b, 20, "20 mm", 1), "along": choose("x", assumed("t")),
                "ends": choose(ends, {"words": span(b, phrase)}), "depth": {"through": True, "from": said(b, "through")},
                "place": middle()}  # fmt: skip
        return messages(check_draft(b, draft("p", [plate(b), slot])), "fault")

    def test_the_denial_is_read_in_the_brief_not_only_in_the_citation(self) -> None:
        self.assertEqual(self.ends("its ends square, not rounded", "round", "rounded"),
                         ["the cited words ('rounded') rule out round"])  # fmt: skip

    def test_however_far_the_clause_runs(self) -> None:
        for text, phrase in (("not fully rounded", "rounded"), ("never to be rounded", "rounded"),
                             ("square rather than round", "round"), ("square instead of round", "round"),
                             ("neither round nor square", "round"), ("unrounded", "unrounded")):  # fmt: skip
            self.assertTrue(self.ends(text, "round", phrase), text)

    def test_a_new_clause_ends_it(self) -> None:
        self.assertEqual(self.ends("not square but round", "round", "round"), [])

    def test_a_denial_that_names_no_option(self) -> None:
        self.assertEqual(self.ends("free of any rounding", "round", "free of any rounding"),
                         ["the cited words ('free of any rounding') deny something and name no option: cite the "
                          "words that say round, or assume it and say why"])  # fmt: skip

    def test_words_that_don_t_name_the_choice_are_shown_as_an_assumption(self) -> None:
        b, d = plate_draft()
        d["items"][1]["place"]["pattern"] = {"row": {"axis": choose("y", said(b, "near each corner")),
                                                     "pitch": mm(b, 36, "36 mm"), "count": count(b, 4, "Four")}}  # fmt: skip
        report = check_draft(b, d)
        self.assertIn("holes.place.pattern.row.axis: y (read from 'near each corner', which doesn't name it)",
                      [a_.message for a_ in report.assumptions])  # fmt: skip


# ----------------------------------------------------------------------
# Texts
# ----------------------------------------------------------------------
class ATextIsTheBriefsWhole(unittest.TestCase):
    def label(self, text: str, letters: str, phrase: str) -> list[str]:
        b = number_words(text)
        label = {"id": "label", "kind": "text", "words": cite(b, "letters"), "on": {"item": "plate", "face": "+z"},
                 "text": {"text": letters, "from": {"words": span(b, phrase)}}, "height": assumed("t", 2),
                 "depth": assumed("t", 0.5), "mode": choose("engrave", assumed("t")), "place": middle()}  # fmt: skip
        return messages(check_draft(b, draft("p", [plate(b), label])), "fault")

    def test_a_word_from_the_middle_of_a_quotation(self) -> None:
        text = 'A plate 60 mm long, 40 mm wide and 5 mm thick with the letters "MADE IN BRASOV ROMANIA".'
        self.assertEqual(
            self.label(text, "MADE IN BRASOV ROMANIA", "MADE IN BRASOV ROMANIA"), []
        )
        self.assertEqual(self.label(text, "IN BRASOV", "IN BRASOV"),
                         ["the text is part of a quotation: cite all of it, and only it"])  # fmt: skip

    def test_a_possessive_is_not_a_quotation(self) -> None:
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick with the letters JAMES' cut into it."
        self.assertEqual(self.label(text, "JAMES'", "JAMES"), [])
        self.assertEqual(self.label(text, "JAMES", "JAMES"), [])

    def test_the_sentence_s_full_stop_is_not_engraved(self) -> None:
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick with the letters ACME. It carries no load."
        self.assertEqual(self.label(text, "ACME", "ACME"), [])
        self.assertEqual(
            self.label(text, "ACME.", "ACME"),
            ["'ACME.' is not exactly what the cited words say ('ACME')"],
        )

    def test_capitals_that_run_on(self) -> None:
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick with the letters DO NOT OPEN on it."
        self.assertEqual(self.label(text, "DO NOT OPEN", "DO NOT OPEN"), [])
        self.assertEqual(self.label(text, "OPEN", "OPEN"),
                         ["the brief's capitals run on ('DO NOT OPEN'): cite them all"])  # fmt: skip


# ----------------------------------------------------------------------
# Tolerances and numbers
# ----------------------------------------------------------------------
class ATolerancesSitsNextToItsValue(unittest.TestCase):
    def hole(self, text: str, phrase: str, tolerance: dict[str, float]) -> list[str]:
        b = number_words(text)
        diameter = {
            "value": 10,
            "unit": "mm",
            "from": {"words": span(b, phrase)},
            "tolerance": tolerance,
        }
        h = {"id": "h", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "plate", "face": "+z"},
             "diameter": diameter, "depth": {"through": True, "from": said(b, "through")}, "place": middle()}  # fmt: skip
        return messages(check_draft(b, draft("p", [plate(b), h])), "fault")

    def test_a_signed_number_further_on_is_not_a_tolerance(self) -> None:
        text = "A plate 60 mm long, 40 mm wide and 5 mm thick with a 10 mm hole through it, offset +5 mm."
        self.assertEqual(self.hole(text, "10 mm hole through it, offset +5", {"plus": 5, "minus": 0}),
                         ["the tolerance isn't in the cited words: cite the brief's +/- numbers right after the "
                          "value, or leave the tolerance out"])  # fmt: skip

    def test_a_tolerance_written_before_its_value(self) -> None:
        text = ("A plate 60 mm long, 40 mm wide and 5 mm thick with a hole through it, held to a \u00b10.05 mm "
                "tolerance on its 10 mm diameter.")  # fmt: skip
        self.assertEqual(
            self.hole(
                text,
                "\u00b10.05 mm tolerance on its 10 mm",
                {"plus": 0.05, "minus": 0.05},
            ),
            [],
        )

    def test_numbers_across_a_comma_are_numbers_of_their_own(self) -> None:
        b = number_words("Spacers 1, 1/2 and 1/4 in thick.")
        for value, phrase in ((1, "1"), (0.5, "1/2")):
            check = check_quantity(
                Q(value, "in"), b, tuple(span(b, phrase)) + tuple(span(b, "in"))
            )
            self.assertIsNotNone(check.reading, (phrase, check.message))


# ----------------------------------------------------------------------
# Placement
# ----------------------------------------------------------------------
class EveryCopyIsChecked(unittest.TestCase):
    def test_however_many_there_are_and_fast(self) -> None:
        big = item("b", "block", length=a(200), width=a(200), height=a(10))
        grid = hole("b", "+z", 5, depth=a(2), place={"pattern": {"grid": {
            "pitch_x": a(2), "count_x": {"count": 50, "from": {"words": [2, 3]}},
            "pitch_y": a(2), "count_y": {"count": 50, "from": {"words": [2, 3]}}}}})  # fmt: skip
        started = time.perf_counter()
        self.assertIn("overlap", issues(layout_of(big, grid))[0][1])  # 2,500 copies
        column = item("p", "pocket", on=on("b", "+z"), shape=pick("rectangle"), length=a(4), width=a(0.05),
                      corner_radius=a(0.02), depth=a(1), place={"pattern": {"row": {
                          "axis": pick("y"), "pitch": a(0.09), "count": {"count": 2000, "from": {"words": [2, 3]}}}}})  # fmt: skip
        self.assertEqual(issues(layout_of(big, column)), [])
        self.assertLess(time.perf_counter() - started, 5.0)


class ARoundSideIsBlamedForWhatBinds(unittest.TestCase):
    def test_a_hole_wider_than_a_rod_whose_length_was_assumed(self) -> None:
        b = number_words("A rod 10 mm across with a 12 mm hole through its side.")
        rod = {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": mm(b, 10, "10 mm"),
               "length": assumed("t", 40), "axis": choose("z", assumed("t"))}  # fmt: skip
        h = {"id": "h", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "rod", "face": "side"},
             "diameter": mm(b, 12, "12 mm"), "depth": {"through": True, "from": said(b, "through")}}  # fmt: skip
        self.assertIn(("cant", "h (12 mm across) is as wide as the round side it is on (\u00d810 mm)"),
                      found(check_draft(b, draft("r", [rod, h]))))  # fmt: skip


class ACountIsTheWholePart(unittest.TestCase):
    def test_a_count_of_one_host_s_copies(self) -> None:
        bosses = item("b", "boss", on=on("plate", "+z"), diameter=a(10), height=a(5),
                      place={"pattern": {"ends": {"inset": a(15), "axis": pick("x")}}})  # fmt: skip
        holes = hole("b", "+end", 2, depth=a(3), count={"count": 3, "from": {"words": [2, 3]}},
                     place={"pattern": {"row": {"axis": pick("y"), "pitch": a(2.5), "count": {"count": 3, "from": {"words": [2, 3]}}}}})  # fmt: skip
        self.assertIn(("fault", "the count is 3, but the placement makes 6 h: 3 on each of the 2 copies of b; "
                                "a count is the whole part's, so it is 6"), issues(layout_of(PLATE, bosses, holes)))  # fmt: skip


class AJointUnderAnOverhang(unittest.TestCase):
    def check(self, *items: dict[str, Any]) -> list[tuple[str, str]]:
        report = check_draft(number_words(R05), draft("t", list(items)))
        return [
            (p.kind, p.message)
            for p in report.problems
            if p.at.startswith("/items") and "cited" not in p.message
        ]

    def test_it_runs_down_the_host_s_own_side(self) -> None:
        base = item("base", "block", length=a(60), width=a(40), height=a(10))
        post = item("post", "post", on=on("base", "+z"), length=a(10), width=a(10), height=a(3),
                    place={"x": centred(), "y": centred()})  # fmt: skip
        bar = item("bar", "block", on=on("post", "+z"), length=a(60), width=a(10), height=a(4),
                   place={"x": centred(), "y": centred()})  # fmt: skip

        def joint(radius: float) -> dict[str, Any]:
            return item(
                "f",
                "fillet",
                edges={"of": "bar", "which": "joint", "where_meets": "post"},
                radius=guess(radius),
            )

        self.assertEqual(self.check(base, post, bar, joint(3)), [])
        self.assertEqual(self.check(base, post, bar, joint(10)),
                         [("fault", "a 10 mm fillet doesn't fit where bar meets post (at most 3 mm)" + ASSUMED)])  # fmt: skip


class AFloorNeedsAnOpening(unittest.TestCase):
    def test_a_floor_with_nothing_open_opposite(self) -> None:
        box = item("box", "block", length=a(60), width=a(40), height=a(30))
        self.assertEqual(issues(layout_of(box, shell("box", 2, "+z", floor=a(5)))), [])
        for opened in ((), ("+z", "-z")):
            self.assertEqual(
                [
                    k
                    for k, _ in issues(
                        layout_of(box, shell("box", 2, *opened, floor=a(5)))
                    )
                ],
                ["fault"],
            )


# ----------------------------------------------------------------------
# Threads, fits and what the person sees
# ----------------------------------------------------------------------
class AThreadIsNamedWhole(unittest.TestCase):
    def thread(self, text: str, designation: str, phrase: str) -> SpecReport:
        b = number_words(text)
        rod = {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": mm(b, 8, "8 mm"),
               "length": mm(b, 40, "40 mm"), "axis": choose("z", assumed("t"))}  # fmt: skip
        th = {"id": "th", "kind": "thread", "words": cite(b, "thread"), "of": "rod",
              "designation": {"text": designation, "from": {"words": span(b, phrase)}},
              "hand": choose("right", assumed("t"))}  # fmt: skip
        return check_draft(b, draft("r", [rod, th]))

    def test_a_length_is_not_a_pitch(self) -> None:
        report = self.thread(
            "A rod 8 mm across and 40 mm long with an M8x40 thread.", "M8x40", "M8x40"
        )
        self.assertIn("40 mm can't be the pitch of an M8 (it is under 2 mm): 'M8x40' reads as an M8 40 long; "
                      "name it M8", messages(report, "fault"))  # fmt: skip

    def test_a_size_with_no_coarse_pitch_names_its_pitch(self) -> None:
        report = self.thread(
            "A rod 8 mm across and 40 mm long with an M7 thread.", "M7", "M7"
        )
        self.assertIn("Forge knows the coarse pitches of M2, M2.5, M3, M4, M5, M6, M8, M10, M12, M16, M20, "
                      "M24; an M7 needs its pitch named (M7x...)", messages(report, "unable"))  # fmt: skip
        report = self.thread(
            "A rod 8 mm across and 40 mm long with an M7x1 thread.", "M7x1", "M7x1"
        )
        self.assertNotIn("unable", [p.kind for p in report.problems])

    def test_one_spelling_and_its_pitch_said_outright(self) -> None:
        b = number_words("A rod 8 mm across and 40 mm long with an M8x1.25 thread.")
        report = self.thread(
            "A rod 8 mm across and 40 mm long with an M8x1.25 thread.",
            "m8 X 1.25",
            "M8x1.25",
        )
        self.assertEqual(found(report), [])
        assert report.spec is not None
        self.assertEqual(report.spec.items[1].get("designation").text, "M8")  # type: ignore[union-attr]
        self.assertIn(
            "Thread th: 'M8' (coarse, 1.25 mm pitch)", render(report, b).text()
        )


class OneFitOneSpelling(unittest.TestCase):
    def test_seven_ways_to_write_an_m6(self) -> None:
        b = number_words(
            "A plate 60 mm long, 40 mm wide and 5 mm thick with an M6 tapped hole through it."
        )
        digests = set()
        for spelling in (
            "M6",
            "M6x1",
            "M6 x 1",
            "M6X1",
            "M6\u00d71",
            "M6x1.0",
            "M6x1.00",
        ):
            h = {"id": "h", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "plate", "face": "+z"},
                 "diameter": {"fit": "tapped", "for": spelling, "from": said(b, "M6")},
                 "depth": {"through": True, "from": said(b, "through")}, "place": middle()}  # fmt: skip
            report = check_draft(b, draft("p", [plate(b), h]))
            self.assertEqual(messages(report, "fault"), [], spelling)
            assert report.spec is not None
            digests.add(spec_digest(report.spec, b, "draft"))
        self.assertEqual(len(digests), 1)

    def test_a_fit_s_part_is_one_line_of_plain_text(self) -> None:
        b, d = plate_draft()
        d["items"][1]["diameter"] = {
            "fit": "clearance",
            "for": "M4 x\n\u20280.7",
            "from": {"assumed": "t"},
        }
        self.assertIn(
            "/items/1/diameter/for",
            [p.at for p in check_draft(b, d).problems if p.kind == "fault"],
        )


class WhatThePersonReadsIsOneLineEach(unittest.TestCase):
    def test_padding_is_squeezed_and_a_long_reason_refused(self) -> None:
        b, d = plate_draft()
        d["not_modelled"] = [
            {
                "words": cite(b, "mounting"),
                "reason": "what it" + "\u3000" * 120 + "is for",
            }
        ]
        report = check_draft(b, d)
        assert report.spec is not None
        self.assertEqual(report.spec.not_modelled[0].reason, "what it is for")
        # Asked for at most 200 characters, read up to 300 (READ_REASON): a redraft is a paid call.
        d["not_modelled"][0]["reason"] = "x" * 260
        self.assertNotIn("/not_modelled/0", [p.at for p in check_draft(b, d).problems])
        d["not_modelled"][0]["reason"] = "x" * 301
        self.assertIn("/not_modelled/0", [p.at for p in check_draft(b, d).problems])

    def test_the_writer_s_words_are_quoted(self) -> None:
        b, d = flange_draft()
        text = render(check_draft(b, d), b).text()
        self.assertIn("  - disc.axis: z (assumed: 'a disc lies flat')", text)
        self.assertIn("Material: 'steel'\n", text)


class TheLockKeepsWhatWasShown(unittest.TestCase):
    def test_second_looks_shown_are_the_spec_s(self) -> None:
        b = number_words("A plate 60,5 mm long, 40 mm wide and 5 mm thick.")
        d = draft("p", [{"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60.5, "60,5 mm"),
                         "width": mm(b, 40, "40 mm"), "height": mm(b, 5, "5 mm")}])  # fmt: skip
        report = check_draft(b, d)
        self.assertTrue(report.caveats)
        confirmed = lock(report, b, by="person", strict=False)
        self.assertEqual(confirmed.caveats, report.caveats)
        with self.assertRaises(LockError):
            lock(dataclasses.replace(report, caveats=()), b, by="person", strict=False)
        with self.assertRaises(LockError):
            dataclasses.replace(confirmed, caveats=()).check()


if __name__ == "__main__":
    unittest.main()
