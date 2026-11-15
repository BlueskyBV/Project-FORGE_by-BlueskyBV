"""V2 stage 1: values worked out or looked up are checked like values read.

A value from a formula must be worked out from numbers the cited words give
(forge_spec.derived); a value from a table must be the table's entry for a
part the cited words name (forge_spec.tables). Briefs are from V1's corpus
(validation/SUITE.md).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import _naming_words, check_draft
from forge_spec.derived import check_formula
from forge_spec.tables import lookup_fit, table_target, table_value
from forge_units import Q

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import cite, draft, made_of, mm

STRIP = number_words(
    "An aluminium strip 120 mm long, 25 mm wide and 5 mm thick, with five 6 mm holes in a "
    "row along its centre line, 20 mm apart, the row centred on the strip. It carries no "
    "load, so there is no load case."
)
SCREWS = number_words(
    "A steel plate 60 mm long, 40 mm wide and 10 mm thick with two counterbored holes for M5 "
    "screws, 40 mm apart along the length: each a 5.5 mm through hole with a 10 mm "
    "counterbore 5 mm deep from the top face. It carries no load, so there is no load case."
)
INCHES = number_words(
    "A steel plate 3 inches long, 2 inches wide and 0.25 inches thick with a 0.5 inch hole "
    "through the middle. It carries no load, so there is no load case."
)


def formula(
    brief: Any, value: float, text: str, *phrases: str, unit: str = "mm"
) -> Any:
    words: list[int] = []
    for phrase in phrases:
        words += cite(brief, phrase)
    return check_formula(Q(value, unit), text, tuple(words), brief)


class Formulas(unittest.TestCase):
    def test_worked_out_from_the_cited_numbers(self) -> None:
        check = formula(
            STRIP, 40, "120 mm / 2 - 2 * 20 mm", "120 mm", "five", "20 mm apart"
        )
        self.assertFalse(check.ok)  # 4 isn't given: the brief says five
        check = formula(
            STRIP, 20, "(120 mm - (5 - 1) * 20 mm) / 2", "120 mm", "five", "20 mm"
        )
        self.assertFalse(check.ok)  # nor is 1
        check = formula(STRIP, 2.5, "25 mm / 2 - 5 mm * 2", "25 mm", "5 mm thick")
        self.assertTrue(check.ok, check.message)
        self.assertEqual([r.describe() for r in check.readings], ["25 mm", "5 mm"])

    def test_the_arithmetic_must_come_out(self) -> None:
        check = formula(STRIP, 12, "25 mm / 2", "25 mm")
        self.assertEqual(check.message, "the formula gives 12.5 mm, not 12 mm")

    def test_a_number_the_words_don_t_give(self) -> None:
        check = formula(STRIP, 20, "25 mm - 5 mm", "25 mm")
        self.assertFalse(check.ok)
        self.assertIn("5 mm in the formula", check.message)
        check = formula(STRIP, 21, "25 mm - 4 mm", "25 mm", "5 mm")
        self.assertIn("4 mm in the formula", check.message)

    def test_a_unit_the_words_don_t_give(self) -> None:
        self.assertFalse(formula(STRIP, 25, "25 cm / 10", "25 mm").ok)

    def test_nothing_from_the_brief_is_an_assumption(self) -> None:
        check = formula(STRIP, 4, "2 * 2", "five", unit="mm")
        self.assertFalse(check.ok)

    def test_counts_and_constants(self) -> None:
        check = check_formula(
            Q(100, "mm"),
            "5 * 20 mm",
            tuple(cite(STRIP, "five") + cite(STRIP, "20 mm")),
            STRIP,
        )
        self.assertTrue(check.ok, check.message)
        check = check_formula(10, "2 * 5", tuple(cite(STRIP, "five")), STRIP)
        self.assertTrue(check.ok, check.message)

    def test_inches_worked_out_in_millimetres(self) -> None:
        check = formula(INCHES, 25.4, "3 inch - 2 inch", "3 inches", "2 inches")
        self.assertTrue(check.ok, check.message)
        check = formula(
            INCHES, 19.05, "(2 inch - 0.5 inch) / 2", "2 inches", "0.5 inch"
        )
        self.assertTrue(check.ok, check.message)

    def test_rounded_only_where_it_does_not_terminate(self) -> None:
        self.assertTrue(
            formula(STRIP, 8.333, "25 mm / 3", "25 mm", "5 mm").ok is False
        )  # 3 isn't given
        self.assertTrue(formula(STRIP, 41.667, "125 mm / 3", "120 mm").ok is False)
        words = cite(STRIP, "120 mm") + cite(STRIP, "five")
        self.assertTrue(
            check_formula(Q(24, "mm"), "120 mm / 5", tuple(words), STRIP).ok
        )
        self.assertFalse(
            check_formula(Q(24.1, "mm"), "120 mm / 5", tuple(words), STRIP).ok
        )

    def test_only_plain_arithmetic(self) -> None:
        for text in ("25 mm overall", "25 mm > 5 mm", "width / 2", "__import__('os')", "25 mm.real",
                     "", "25 mm +", "'25' mm"):  # fmt: skip
            self.assertFalse(formula(STRIP, 25, text, "25 mm", "5 mm").ok, text)

    def test_the_wrong_kind_of_quantity(self) -> None:
        self.assertIn(
            "doesn't give a value in deg",
            formula(STRIP, 25, "25 mm", "25 mm", unit="deg").message,
        )


class FormulasCanTSmuggleNumbers(unittest.TestCase):
    """Found in review: ways a formula once brought in numbers the brief never gave."""

    def test_each_number_is_used_once(self) -> None:
        check = formula(
            STRIP, 20, "(120 mm - 20 mm - 20 mm - 20 mm - 20 mm) / 2", "120 mm", "20 mm"
        )
        self.assertFalse(check.ok)
        self.assertIn("used twice", check.message)

    def test_a_bare_two_only_halves_doubles_or_squares(self) -> None:
        self.assertFalse(formula(STRIP, 75, "25 mm * (2 + 2 / 2)", "25 mm").ok)
        self.assertTrue(formula(STRIP, 12.5, "25 mm / 2", "25 mm").ok)
        words = tuple(cite(STRIP, "25 mm") + cite(STRIP, "120 mm"))
        self.assertTrue(
            check_formula(
                Q(122.577, "mm"), "sqrt((25 mm) ** 2 + (120 mm) ** 2)", words, STRIP
            ).ok
        )
        self.assertTrue(
            check_formula(Q(122.577, "mm"), "hypot(25 mm, 120 mm)", words, STRIP).ok
        )

    def test_no_unit_or_constant_stands_for_a_number(self) -> None:
        for text in (
            "5 mm * cm / mm",
            "25 mm * pi",
            "25 mm * tau",
            "25 mm * exp(2)",
            "mm * 5",
        ):
            self.assertFalse(formula(STRIP, 50, text, "5 mm", "25 mm", "five").ok, text)

    def test_a_number_written_over_two_words(self) -> None:
        brief = number_words("A 1 1/2 in pin.")
        words = tuple(cite(brief, "1 1/2 in"))
        self.assertTrue(check_formula(Q(19.05, "mm"), "1.5 inch / 2", words, brief).ok)


class FormulasInADraft(unittest.TestCase):
    def strip(self, end_gap: dict[str, Any]) -> Any:
        b = STRIP
        return check_draft(b, draft("strip", [
            {"id": "strip", "kind": "block", "words": cite(b, "aluminium strip"),
             "length": mm(b, 120, "120 mm"), "width": mm(b, 25, "25 mm"), "height": mm(b, 5, "5 mm")},
            {"id": "holes", "kind": "hole", "words": cite(b, "holes in a row"), "on": {"item": "strip", "face": "+z"},
             "diameter": mm(b, 6, "6 mm"), "depth": {"through": True, "from": {"assumed": "holes in a strip go through"}},
             "count": {"count": 5, "from": {"words": cite(b, "five")}},
             "place": {"y": {"centred": {"words": cite(b, "along its centre line")}},
                       "x": {"side": "-x", "distance": end_gap, "to": "centre"},
                       "pattern": {"row": {"axis": {"choose": "x", "from": {"words": cite(b, "in a row")}},
                                           "pitch": mm(b, 20, "20 mm"), "count": {"count": 5, "from": {"words": cite(b, "five")}}}}}},
        ], material=made_of(b, "aluminium"),
           silent=[{"sentence": 1, "reason": "no load case"}]))  # fmt: skip

    def test_a_derived_distance_uses_the_brief_s_numbers(self) -> None:
        # From the -x edge, a row is placed by its nearest hole: the row of five,
        # 20 mm apart and centred on the strip, starts 20 mm in.
        words = (
            cite(STRIP, "120 mm")
            + cite(STRIP, "20 mm")
            + cite(STRIP, "centred on the strip")
        )
        good = {
            "value": 20,
            "unit": "mm",
            "from": {"formula": "120 mm / 2 - 2 * 20 mm", "words": words},
        }
        report = self.strip(good)
        self.assertEqual([p.message for p in report.problems], [])
        wrong = {
            "value": 50,
            "unit": "mm",
            "from": {"formula": "120 mm / 2 - 2 * 20 mm", "words": words},
        }
        report = self.strip(wrong)
        self.assertIn(("fault", "the formula gives 20 mm, not 50 mm"),
                      [(p.kind, p.message) for p in report.problems])  # fmt: skip

    def test_the_formula_s_numbers_count_as_used(self) -> None:
        good = {"value": 60, "unit": "mm", "from": {"formula": "120 mm / 2",
                                                    "words": cite(STRIP, "120 mm") + cite(STRIP, "centred on the strip")}}  # fmt: skip
        report = self.strip(good)
        assert report.accounting is not None
        self.assertEqual(report.accounting.uncited_numbers, ())


class Tables(unittest.TestCase):
    def plate(self, hole: dict[str, Any]) -> Any:
        b = SCREWS
        return check_draft(b, draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "steel plate"),
             "length": mm(b, 60, "60 mm"), "width": mm(b, 40, "40 mm"), "height": mm(b, 10, "10 mm")},
            {"id": "h", "kind": "hole", "words": cite(b, "counterbored holes"), "on": {"item": "plate", "face": "+z"},
             "depth": {"through": True, "from": {"words": cite(b, "through hole")}}, **hole},
        ], material=made_of(b, "steel")))  # fmt: skip

    def faults(self, hole: dict[str, Any]) -> list[str]:
        return [p.message for p in self.plate(hole).problems if p.kind == "fault"]

    def test_a_table_value_is_the_table_s_entry(self) -> None:
        good = {
            "value": 5.5,
            "unit": "mm",
            "from": {"table": "clearance:M5", "words": cite(SCREWS, "M5")},
        }
        self.assertEqual(self.faults({"diameter": good}), [])
        wrong = {
            "value": 5.0,
            "unit": "mm",
            "from": {"table": "clearance:M5", "words": cite(SCREWS, "M5")},
        }
        self.assertIn(
            "the table gives 5.5 mm (ISO 273 normal clearance for M5), not 5 mm",
            self.faults({"diameter": wrong}),
        )

    def test_a_table_value_cites_the_part_it_is_for(self) -> None:
        elsewhere = {
            "value": 4.5,
            "unit": "mm",
            "from": {"table": "clearance:M4", "words": cite(SCREWS, "M5")},
        }
        self.assertIn(
            "cite the brief's words that name M4", self.faults({"diameter": elsewhere})
        )
        nothing = {"value": 5.5, "unit": "mm", "from": {"table": "clearance:M5"}}
        self.assertIn(
            "cite the brief's words that name M5", self.faults({"diameter": nothing})
        )

    def test_a_table_that_does_not_exist(self) -> None:
        made_up = {
            "value": 5.5,
            "unit": "mm",
            "from": {"table": "my_table:M5", "words": cite(SCREWS, "M5")},
        }
        self.assertTrue(
            any("no table entry" in m for m in self.faults({"diameter": made_up}))
        )

    def test_a_fit_names_its_part(self) -> None:
        fit = {
            "fit": "clearance",
            "for": "M5",
            "from": {"words": cite(SCREWS, "M5 screws")},
        }
        self.assertEqual(self.faults({"diameter": fit}), [])
        wrong = {
            "fit": "clearance",
            "for": "M6",
            "from": {"words": cite(SCREWS, "M5 screws")},
        }
        self.assertIn(
            "cite the brief's words that name M6", self.faults({"diameter": wrong})
        )

    def test_names_are_matched_whole(self) -> None:
        brief = number_words("Use 4xM3 screws, an M30 nut, an M8x1 stud and M4.")

        def wrong(target: str, phrase: str) -> str | None:
            return _naming_words(target, tuple(cite(brief, phrase)), brief)[2]

        self.assertIsNone(wrong("M3", "4xM3"))
        self.assertIsNotNone(wrong("M3", "M30"))
        self.assertIsNone(wrong("M4", "M4"))  # before the full stop
        self.assertEqual(
            wrong("M8", "M8x1"), "the brief gives M8x1: say its pitch, M8x1"
        )
        self.assertIsNone(wrong("M8x1", "M8x1"))
        self.assertIsNotNone(wrong("M8x1.25", "M8x1"))

    def test_a_name_uses_only_its_own_numbers(self) -> None:
        brief = number_words("Use 4xM3 screws and an M8x1 stud.")
        # "4xM3": the 3 is the name's (word 1, its second number); the 4 is a count.
        self.assertEqual(
            _naming_words("M3", tuple(cite(brief, "4xM3")), brief)[1], [(1, 1)]
        )
        self.assertEqual(
            _naming_words("M8x1", tuple(cite(brief, "M8x1")), brief)[1],
            [(5, 0), (5, 1)],
        )

    def test_a_made_up_pitch(self) -> None:
        brief = number_words(
            "A 20 mm steel cube with an M6 threaded hole straight through its centre."
        )  # H08
        b = brief
        report = check_draft(b, draft("cube", [
            {"id": "cube", "kind": "block", "words": cite(b, "steel cube"), "length": mm(b, 20, "20 mm"),
             "width": mm(b, 20, "20 mm"), "height": mm(b, 20, "20 mm")},
            {"id": "h", "kind": "hole", "words": cite(b, "threaded hole"), "on": {"item": "cube", "face": "+z"},
             "diameter": {"value": 5.5, "unit": "mm", "from": {"table": "tapped:M6x0.5", "words": cite(b, "M6")}},
             "depth": {"through": True, "from": {"words": cite(b, "straight through")}}},
        ]))  # fmt: skip
        self.assertIn(
            "the cited words name M6, not M6x0.5", [p.message for p in report.problems]
        )

    def test_a_clearance_grade_is_stated_or_shown_as_assumed(self) -> None:
        normal = {
            "fit": "clearance",
            "for": "M5",
            "from": {"words": cite(SCREWS, "M5 screws")},
        }
        report = self.plate({"diameter": normal})
        self.assertTrue(
            any(
                "normal (ISO 273 medium) clearance for M5" in a.message
                for a in report.assumptions
            )
        )
        fine = dict(normal, grade="fine")
        self.assertIn(
            "a fine clearance, but the brief doesn't say how close",
            self.faults({"diameter": fine}),
        )

    def test_a_table_citation_holds_only_the_part_it_names(self) -> None:
        sneaky = {"value": 5.5, "unit": "mm",
                  "from": {"table": "clearance:M5", "words": cite(SCREWS, "M5 screws") + cite(SCREWS, "40 mm apart")}}  # fmt: skip
        self.assertTrue(
            any(
                "cite only the words that name M5" in m
                for m in self.faults({"diameter": sneaky})
            )
        )

    def test_entries(self) -> None:
        self.assertEqual(table_value("bearing:608:bore").size_mm, 8.0)  # type: ignore[union-attr]
        self.assertEqual(table_value("tapped:M8x1").size_mm, 7.0)  # type: ignore[union-attr]
        self.assertIsNone(table_value("bearing:608:colour"))
        self.assertIsNone(table_value("tapped:M8x3"))
        self.assertEqual(table_target("clearance:m4"), "M4")
        self.assertEqual(table_target("clearance:M4:fine"), "M4")
        self.assertEqual(table_target("tapped:M6x0.5"), "M6x0.5")
        self.assertEqual(lookup_fit("tapped", "M8x1.25").size_mm, 6.8)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
