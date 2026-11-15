"""V2 stage 1: nothing in the brief may quietly disappear (forge_spec.accounting).

V1's commonest false pass was a claim nobody made. These tests pin the rule
that replaces it: every number and every sentence of the brief is used by the
spec, listed as not modelled, or (for a sentence) declared to say nothing
about the shape. In --auto mode, every content word too.

A number counts as used only by the reading that matched a value, number by
number inside a word, never by merely appearing in some citation: otherwise a
second number could hide inside another value's citation.
"""

from __future__ import annotations

import time
import unittest
from typing import Any

from forge_spec import (
    FUNCTION_WORDS,
    Reading,
    account,
    check_count,
    check_quantity,
    number_words,
)
from forge_spec.words import NumberedBrief
from forge_units import Q


def ids(brief: NumberedBrief, *texts: str) -> tuple[int, ...]:
    found: list[int] = []
    for text in texts:
        found.append(
            next(
                w.index for w in brief.words if w.text == text and w.index not in found
            )
        )
    return tuple(found)


def size(brief: NumberedBrief, value: float, unit: str, *texts: str) -> Reading:
    check = check_quantity(Q(value, unit), brief, ids(brief, *texts))
    assert check.reading is not None, check.message
    return check.reading


def number(brief: NumberedBrief, n: int, *texts: str) -> Reading:
    check = check_count(n, brief, ids(brief, *texts))
    assert check.reading is not None, check.message
    return check.reading


class EveryNumberIsUsed(unittest.TestCase):
    text = "A plate 60 x 40 x 4 mm with four 3 mm holes. The ends are rounded."

    def test_complete(self) -> None:
        b = number_words(self.text)
        used = [size(b, 60, "mm", "60"), size(b, 40, "mm", "40"), size(b, 4, "mm", "4"),
                number(b, 4, "four"), size(b, 3, "mm", "3", "mm")]  # fmt: skip
        result = account(
            b, readings=used, mentions=[ids(b, "plate", "holes", "ends", "rounded")]
        )
        self.assertTrue(result.complete(strict=False))
        self.assertEqual(result.uncited_numbers, ())

    def test_an_unused_number_is_flagged(self) -> None:
        b = number_words(self.text)
        used = [size(b, 60, "mm", "60"), size(b, 40, "mm", "40"), size(b, 4, "mm", "4"),
                size(b, 3, "mm", "3")]  # fmt: skip
        result = account(b, readings=used, mentions=[ids(b, "ends")])
        self.assertEqual([w.text for w in result.uncited_numbers], ["four"])
        self.assertFalse(result.complete(strict=False))

    def test_a_mention_does_not_account_for_a_number(self) -> None:
        b = number_words(self.text)
        result = account(b, mentions=[ids(b, "four", "holes")])
        self.assertIn("four", [w.text for w in result.uncited_numbers])

    def test_number_words_compounds_and_designations(self) -> None:
        b = number_words(
            "Two M3 bolts, a pair of tabs, a four-hole flange, a half-ball."
        )
        result = account(b, mentions=[ids(b, "bolts")])
        self.assertEqual(
            [w.text for w in result.uncited_numbers],
            ["Two", "M3", "pair", "four-hole", "half-ball"],
        )

    def test_3d_printing_is_not_a_size_but_3d_deep_is(self) -> None:
        b = number_words("A 3D-printed bracket, 3D printed. A hole 3D deep.")
        result = account(b, mentions=[ids(b, "bracket", "hole")])
        self.assertEqual(
            [w.index for w in result.uncited_numbers], [ids(b, "3D", "3D")[1]]
        )

    def test_a_silent_sentence_still_needs_its_numbers(self) -> None:
        b = number_words("A plate. Print 3 of them.")
        result = account(b, mentions=[ids(b, "plate")], silent=[1])
        self.assertEqual([w.text for w in result.uncited_numbers], ["3"])
        self.assertEqual(result.uncited_sentences, ())

    def test_not_modelled_and_table_citations_account_for_a_number(self) -> None:
        b = number_words("A plate. Print 3 of them. Clearance for M4.")
        result = account(
            b,
            mentions=[ids(b, "plate", "Clearance", "for")],
            not_modelled=[ids(b, "Print", "3", "of", "them")],
            cited=[ids(b, "M4")],
        )
        self.assertTrue(result.complete(strict=True), result)


class ASecondNumberCannotHide(unittest.TestCase):
    def test_in_another_value_s_citation(self) -> None:
        b = number_words("A plate with a 5 mm hole and 2 mm fillets.")
        sloppy = check_quantity(Q(5, "mm"), b, ids(b, "5", "mm", "2", "mm"))
        self.assertIsNone(sloppy.reading)
        result = account(
            b, readings=[size(b, 5, "mm", "5", "mm")], mentions=[ids(b, "hole")]
        )
        self.assertEqual([w.text for w in result.uncited_numbers], ["2"])

    def test_inside_one_word(self) -> None:
        for text, value, unit, word, left in (
            ("A 60x40x10mm block.", 60, "mm", "60x40x10mm", "60x40x10mm"),
            ("A 5-10mm gap.", 5, "mm", "5-10mm", "5-10mm"),
            ("Use 4xM3 screws.", None, "", "4xM3", "4xM3"),
            ("An M4x0.7 thread.", 4, "mm", "M4x0.7", "M4x0.7"),
        ):
            b = number_words(text)
            reading = (
                number(b, 4, word) if value is None else size(b, value, unit, word)
            )
            result = account(b, readings=[reading])
            self.assertEqual([w.text for w in result.uncited_numbers], [left], text)

    def test_every_number_of_a_word_used_completes_it(self) -> None:
        b = number_words("A 60x40x10mm block.")
        used = [size(b, v, "mm", "60x40x10mm") for v in (60, 40, 10)]
        result = account(b, readings=used, mentions=[ids(b, "block")])
        self.assertTrue(result.complete(strict=True), result)

    def test_behind_a_unit_it_only_lent(self) -> None:
        # "1" with the inch mark of "1/2\"" would be 1 inch: part of the brief's
        # number, so it isn't a reading at all (found in review).
        b = number_words('a 1 1/2" pipe')
        self.assertIsNone(check_quantity(Q(25.4, "mm"), b, ids(b, "1")).reading)
        whole = size(b, 38.1, "mm", "1", '1/2"')
        self.assertEqual(account(b, readings=[whole]).uncited_numbers, ())

    def test_after_a_number_ending_a_sentence(self) -> None:
        b = number_words("A plate 60.Two holes 3 mm.")
        result = account(b, readings=[size(b, 60, "mm", "60")])
        self.assertIn("Two", [w.text for w in result.uncited_numbers])


class EverySentenceIsAccountedFor(unittest.TestCase):
    def test_an_uncited_sentence_is_flagged(self) -> None:
        b = number_words("A plate 60 mm long. The lid snaps on.")
        result = account(
            b, readings=[size(b, 60, "mm", "60")], mentions=[ids(b, "plate")]
        )
        self.assertEqual([s.index for s in result.uncited_sentences], [1])

    def test_lines_of_a_list_are_each_accounted_for(self) -> None:
        b = number_words("60mm plate\nfour m3 holes\nhollow\nrounded corners")
        used = [size(b, 60, "mm", "60mm"), number(b, 4, "four"), size(b, 3, "mm", "m3")]
        result = account(b, readings=used, mentions=[ids(b, "plate", "holes")])
        self.assertEqual([s.index for s in result.uncited_sentences], [2, 3])

    def test_a_line_ending_in_inches_does_not_swallow_the_next(self) -> None:
        b = number_words("Length 4 in\nHollow body\nRounded ends")
        result = account(
            b, readings=[size(b, 4, "in", "4", "in")], mentions=[ids(b, "Length")]
        )
        self.assertEqual([s.index for s in result.uncited_sentences], [1, 2])

    def test_a_sentence_saying_nothing_about_the_shape(self) -> None:
        b = number_words("A plate 60 mm long. It is a gift for my brother.")
        result = account(b, readings=[size(b, 60, "mm", "60")], mentions=[ids(b, "plate")],
                         silent=[1])  # fmt: skip
        self.assertTrue(result.complete(strict=False))
        # ...but an automatic run can't take that on trust.
        self.assertFalse(result.complete(strict=True))

    def test_sentence_numbers_are_checked(self) -> None:
        b = number_words("A plate.")
        for bad in (3, -1, True, 1.0):
            with self.assertRaises(LookupError, msg=repr(bad)):
                account(b, silent=[bad])  # type: ignore[list-item]


class StrictModeForAutomaticRuns(unittest.TestCase):
    def test_every_content_word_is_cited(self) -> None:
        b = number_words("A knurled plate 60 mm long.")
        result = account(b, readings=[size(b, 60, "mm", "60", "mm")],
                         mentions=[ids(b, "plate", "long")])  # fmt: skip
        self.assertTrue(result.complete(strict=False))
        self.assertFalse(result.complete(strict=True))
        self.assertEqual([w.text for w in result.uncited_words], ["knurled"])

    def test_a_reading_s_unit_word_goes_with_it(self) -> None:
        b = number_words("A block 60 x 40 x 10 mm.")
        used = [size(b, float(n), "mm", n) for n in ("60", "40", "10")]
        result = account(b, readings=used, mentions=[ids(b, "block")])
        self.assertTrue(result.complete(strict=True), result.uncited_words)

    def test_list_markers_that_are_not_numbers_need_no_citation(self) -> None:
        b = number_words("a) a plate\nb) a hole")
        result = account(b, mentions=[ids(b, "plate"), ids(b, "hole")])
        self.assertTrue(result.complete(strict=True), result.uncited_words)

    def test_function_words_are_few_and_carry_no_shape(self) -> None:
        for meaningful in ("no", "not", "without", "each", "every", "all", "only",
                           "through", "on", "from", "hollow", "both"):  # fmt: skip
            self.assertNotIn(meaningful, FUNCTION_WORDS)

    def test_a_citation_to_nowhere(self) -> None:
        b = number_words("A plate.")
        for kind in ("cited", "mentions", "not_modelled"):
            with self.assertRaises(LookupError, msg=kind):
                account(b, **{kind: [(7,)]})  # type: ignore[arg-type]

    def test_a_long_brief_is_fast(self) -> None:
        b = number_words(" ".join(["A plate 60 mm long with four holes."] * 3000))
        started = time.perf_counter()
        account(b)
        self.assertLess(time.perf_counter() - started, 3.0)


class ACountAChoiceOrAPatternHolds(unittest.TestCase):
    """Number words a spec holds other than as a count value: each used by what holds it, and only by that (V1's validation suite drafted as specs found each)."""

    def problems(self, brief: NumberedBrief, items: list[dict[str, Any]]) -> list[str]:
        from forge_spec.checks import check_draft
        from v2_drafts import draft

        return [p.message for p in check_draft(brief, draft("part", items)).problems]

    def test_both_a_and_b_names_them_but_both_long_edges_counts(self) -> None:
        b = number_words("A bore through both the flange and the hub. "
                         "Walls stand along both long edges of the base and the box is 30 mm tall.")  # fmt: skip
        result = account(
            b,
            readings=[size(b, 30, "mm", "30", "mm")],
            mentions=[ids(b, "bore", "Walls")],
        )
        self.assertEqual(
            [w.index for w in result.uncited_numbers], [ids(b, "both", "both")[1]]
        )

    def test_half_a_ball_is_the_dome_s(self) -> None:
        from v2_drafts import choose, cite, mm, said

        b = number_words("A dome: half of a 40 mm ball.")
        dome = {
            "id": "dome",
            "kind": "sphere",
            "words": cite(b, "dome"),
            "diameter": mm(b, 40, "40 mm ball"),
        }
        self.assertEqual(
            self.problems(
                b, [{**dome, "portion": choose("upper_half", said(b, "half"))}]
            ),
            [],
        )
        unused = self.problems(
            b, [{**dome, "portion": choose("upper_half", said(b, "dome"))}]
        )
        self.assertEqual(
            unused, ["the brief says 'half' (sentence 1); nothing in the spec uses it"]
        )

    def test_open_at_both_ends_is_the_faces_it_opens(self) -> None:
        from v2_drafts import assumed, choose, cite, mm, said

        b = number_words(
            "A tube 30 mm across, 80 mm long, with a 3 mm wall, open at both ends."
        )
        tube = {"id": "tube", "kind": "cylinder", "words": cite(b, "tube"), "diameter": mm(b, 30, "30 mm across"),
                "length": mm(b, 80, "80 mm long"), "axis": choose("z", assumed("it stands up"))}  # fmt: skip
        hollow = {"id": "hollow", "kind": "shell", "words": cite(b, "wall"), "of": "tube",
                  "thickness": mm(b, 3, "3 mm wall")}  # fmt: skip
        both = {"faces": ["+end", "-end"], "from": said(b, "open at both ends")}
        self.assertEqual(self.problems(b, [tube, {**hollow, "open": both}]), [])
        one = {"faces": ["+end"], "from": said(b, "open at both ends")}
        self.assertIn("the brief says 'both' (sentence 1); nothing in the spec uses it",
                      self.problems(b, [tube, {**hollow, "open": one}]))  # fmt: skip

    def test_along_both_edges_is_the_ends_pattern_s_two(self) -> None:
        from v2_drafts import choose, cite, count, mm, said

        b = number_words("A plate 60 mm long, 40 mm wide and 4 mm thick, with two 4 mm ribs 10 mm tall "
                         "along both long edges.")  # fmt: skip
        plate = {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm long"),
                 "width": mm(b, 40, "40 mm wide"), "height": mm(b, 4, "4 mm thick")}  # fmt: skip
        ribs = {"id": "ribs", "kind": "rib", "words": cite(b, "ribs"), "on": {"item": "plate", "face": "+z"},
                "length": {"value": 60, "unit": "mm", "from": {"words": cite(b, "60 mm long") + cite(b, "long edges")}},
                "thickness": mm(b, 4, "4 mm ribs"), "height": mm(b, 10, "10 mm tall"),
                "along": choose("x", said(b, "along")), "count": count(b, 2, "two"),
                "place": {"x": {"centred": said(b, "long edges")}, "pattern": {"ends": {
                    "axis": choose("y", said(b, "both long edges")),
                    "inset": {"value": 2, "unit": "mm", "from": {"formula": "4 mm / 2", "words": cite(b, "4 mm ribs")}}}}}}  # fmt: skip
        self.assertEqual(self.problems(b, [plate, ribs]), [])


if __name__ == "__main__":
    unittest.main()
