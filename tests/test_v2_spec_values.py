"""V2 stage 1: values, counts and where they came from (forge_spec.values).

Two V1 failures are built into these types: a value with no unit (V1 read
``cos(30)`` in radians) and a count argued over as a quantity (V1 refused a
count's unit as "" and then as "turns"). And rule R8: a draft is read item by
item, and every fault in it is reported in one round.
"""

from __future__ import annotations

import math
import unittest

from forge_spec import (
    Count,
    Follows,
    Problems,
    Provenance,
    Source,
    Tolerance,
    Value,
    check_citation,
    number_words,
    read_count,
    read_provenance,
    read_value,
)
from forge_units import Q


def value(raw: object) -> tuple[Value | None, Problems]:
    problems = Problems()
    return read_value(raw, "/items/0/diameter", problems), problems


def count(raw: object) -> tuple[Count | None, Problems]:
    problems = Problems()
    return read_count(raw, "/items/0/count", problems), problems


class AValueNeedsAUnitAndAReason(unittest.TestCase):
    def test_a_value_from_the_brief(self) -> None:
        got, problems = value({"value": 2.8, "unit": "mm", "from": {"words": [12, 13]}})
        self.assertFalse(problems)
        assert got is not None
        self.assertEqual((got.nominal, got.unit), (2.8, "mm"))
        self.assertEqual(got.provenance, Provenance(Source.BRIEF, (12, 13)))

    def test_every_kind_of_source(self) -> None:
        cases = {
            "table": {"table": "iso_273_clearance:M4:normal", "words": [7]},
            "derived": {"formula": "plate.width / 2"},
            "assumed": {"assumed": "no wall given; 3 mm prints solidly"},
        }
        for kind, source in cases.items():
            got, problems = value({"value": 3, "unit": "mm", "from": source})
            self.assertFalse(problems, kind)
            assert got is not None
            self.assertEqual(got.provenance.source.value, kind)
        assumed, _ = value({"value": 3, "unit": "mm", "from": cases["assumed"]})
        assert assumed is not None
        self.assertTrue(assumed.provenance.is_assumption)

    def test_no_unit_is_a_fault_angles_included(self) -> None:
        for raw in ({"value": 30, "from": {"words": [1]}},
                    {"value": 30, "unit": "", "from": {"words": [1]}},
                    {"value": 30, "unit": "1", "from": {"words": [1]}}):  # fmt: skip
            got, problems = value(raw)
            self.assertIsNone(got)
            self.assertIn("/items/0/diameter/unit", [p.at for p in problems.faults])

    def test_an_unknown_unit(self) -> None:
        got, problems = value({"value": 3, "unit": "furlongs", "from": {"words": [1]}})
        self.assertIsNone(got)
        self.assertIn("unknown unit", str(problems.faults[0]))

    def test_a_spelled_out_unit_is_normalised_and_noted(self) -> None:
        got, problems = value(
            {"value": 3, "unit": "millimetres", "from": {"words": [1]}}
        )
        assert got is not None
        self.assertEqual(got.unit, "mm")
        self.assertFalse(problems)
        self.assertIn("read as 'mm'", str(problems.notes[0]))

    def test_not_a_number(self) -> None:
        for bad in ("3", True, None, math.inf, math.nan, [3]):
            got, problems = value({"value": bad, "unit": "mm", "from": {"words": [1]}})
            self.assertIsNone(got, bad)
            self.assertEqual(problems.faults[0].at, "/items/0/diameter/value")

    def test_every_fault_is_reported_in_one_round(self) -> None:
        got, problems = value({"value": "3", "unit": "", "from": {}, "colour": "red"})
        self.assertIsNone(got)
        places = {p.at for p in problems.faults}
        self.assertEqual(
            places,
            {"/items/0/diameter", "/items/0/diameter/value", "/items/0/diameter/unit",
             "/items/0/diameter/from"},
        )  # fmt: skip

    def test_a_tolerance(self) -> None:
        got, problems = value({"value": 10, "unit": "mm", "tolerance": {"plus": 0.1},
                               "from": {"words": [3]}})  # fmt: skip
        assert got is not None
        self.assertEqual(got.tolerance, Tolerance(0.1, 0.0))
        self.assertFalse(problems)

    def test_a_minus_tolerance_written_negative_is_the_same_tolerance(self) -> None:
        got, problems = value({"value": 10, "unit": "mm",
                               "tolerance": {"plus": 0.1, "minus": -0.2},
                               "from": {"words": [3]}})  # fmt: skip
        assert got is not None
        self.assertEqual(got.tolerance, Tolerance(0.1, 0.2))
        self.assertIn("read as 0.2", str(problems.notes[0]))

    def test_a_negative_plus_tolerance_is_a_fault(self) -> None:
        got, problems = value({"value": 10, "unit": "mm", "tolerance": {"plus": -0.1},
                               "from": {"words": [3]}})  # fmt: skip
        self.assertIsNone(got)
        self.assertEqual(problems.faults[0].at, "/items/0/diameter/tolerance/plus")

    def test_the_value_type_refuses_what_the_reader_refuses(self) -> None:
        with self.assertRaises(ValueError):
            Value(Q(30, ""), Provenance(Source.BRIEF, (1,)))
        with self.assertRaises(ValueError):
            Value(Q(30, "mm", plus=1, minus=1), Provenance(Source.BRIEF, (1,)))
        with self.assertRaises(ValueError):
            Tolerance(-0.1, 0.0)


class WhereAValueCameFrom(unittest.TestCase):
    def provenance(self, raw: object) -> tuple[Provenance | None, Problems]:
        problems = Problems()
        return read_provenance(raw, "/v/from", problems), problems

    def test_word_numbers_are_sorted_and_noted(self) -> None:
        got, problems = self.provenance({"words": [5, 3, 3]})
        assert got is not None
        self.assertEqual(got.words, (3, 5))
        self.assertTrue(problems.notes)

    def test_bad_word_numbers(self) -> None:
        for bad in ([], [-1], [1.5], [True], "3", None):
            got, problems = self.provenance({"words": bad})
            self.assertIsNone(got, bad)
            self.assertTrue(problems, bad)

    def test_a_value_comes_from_one_place(self) -> None:
        got, problems = self.provenance({"table": "x", "formula": "y"})
        self.assertIsNone(got)
        self.assertIn("one place", str(problems.faults[0]))

    def test_an_assumption_cites_no_words(self) -> None:
        got, problems = self.provenance({"assumed": "reason", "words": [1]})
        self.assertIsNone(got)
        self.assertIn("isn't assumed", str(problems.faults[0]))

    def test_empty_reasons_are_faults(self) -> None:
        for raw in ({"assumed": "  "}, {"table": ""}, {"formula": 3}):
            got, problems = self.provenance(raw)
            self.assertIsNone(got, raw)
            self.assertTrue(problems, raw)

    def test_missing_or_unknown(self) -> None:
        for raw in (None, {}, {"guess": "x"}):
            got, problems = self.provenance(raw)
            self.assertIsNone(got, raw)
            self.assertTrue(problems, raw)

    def test_the_type_keeps_its_invariants(self) -> None:
        with self.assertRaises(ValueError):
            Provenance(Source.BRIEF)
        with self.assertRaises(ValueError):
            Provenance(Source.ASSUMED, reason=" ")
        with self.assertRaises(ValueError):
            Provenance(Source.BRIEF, (3, 1))
        with self.assertRaises(ValueError):
            Provenance(Source.TABLE, table="t", formula="f")


class ACountIsAWholeNumberWithNoUnit(unittest.TestCase):
    def test_a_count(self) -> None:
        got, problems = count({"count": 4, "from": {"words": [9]}})
        assert got is not None
        self.assertEqual(got.n, 4)
        self.assertFalse(problems)

    def test_four_point_zero_is_four_and_noted(self) -> None:
        got, problems = count({"count": 4.0, "from": {"words": [9]}})
        assert got is not None
        self.assertEqual(got.n, 4)
        self.assertTrue(problems.notes)

    def test_not_whole_numbers(self) -> None:
        for bad in (4.5, -1, True, "4", None, math.inf):
            got, problems = count({"count": bad, "from": {"words": [9]}})
            self.assertIsNone(got, bad)
            self.assertEqual(problems.faults[0].at, "/items/0/count/count")

    def test_a_count_has_no_unit_to_argue_about(self) -> None:
        got, problems = count({"count": 10, "unit": "turns", "from": {"words": [9]}})
        self.assertIsNone(got)
        self.assertIn("unknown field", str(problems.faults[0]))

    def test_the_type(self) -> None:
        with self.assertRaises(ValueError):
            Count(-1, Provenance(Source.BRIEF, (1,)))
        with self.assertRaises(ValueError):
            Count(True, Provenance(Source.BRIEF, (1,)))


class CitationsAreCheckedAgainstTheBrief(unittest.TestCase):
    brief = number_words("A plate with four 2.8 mm holes.")

    def test_a_value_that_follows(self) -> None:
        got, _ = value({"value": 2.8, "unit": "mm", "from": {"words": [4, 5]}})
        assert got is not None
        result = check_citation(got, self.brief)
        assert result is not None
        self.assertIs(result.follows, Follows.YES)

    def test_a_misheard_value(self) -> None:
        got, _ = value({"value": 2.5, "unit": "mm", "from": {"words": [4, 5]}})
        assert got is not None
        result = check_citation(got, self.brief)
        assert result is not None
        self.assertIs(result.follows, Follows.NO)

    def test_a_count(self) -> None:
        got, _ = count({"count": 4, "from": {"words": [3]}})
        assert got is not None
        result = check_citation(got, self.brief)
        assert result is not None
        self.assertIs(result.follows, Follows.YES)

    def test_other_sources_are_checked_elsewhere(self) -> None:
        got, _ = value({"value": 3.0, "unit": "mm", "from": {"assumed": "a guess"}})
        assert got is not None
        self.assertIsNone(check_citation(got, self.brief))


class TheReaderReportsEverythingInOneRound(unittest.TestCase):
    """Findings from the stage-1 code review, kept as tests."""

    def test_every_fault_in_a_from(self) -> None:
        problems = Problems()
        read_provenance({"table": "t", "formula": "f", "words": "bad"}, "/f", problems)
        self.assertEqual(len(problems.faults), 2)
        problems = Problems()
        read_provenance({"words": [], "assumed": ""}, "/f", problems)
        self.assertEqual(len(problems.faults), 3)

    def test_a_tolerance_with_an_unknown_key_still_checks_its_sides(self) -> None:
        got, problems = value(
            {"value": 1, "unit": "mm", "tolerance": {"plus": "x", "over": 1},
             "from": {"words": [0]}}
        )  # fmt: skip
        self.assertIsNone(got)
        self.assertEqual(
            {p.at for p in problems.faults},
            {"/items/0/diameter/tolerance", "/items/0/diameter/tolerance/plus"},
        )

    def test_an_empty_tolerance_is_a_fault_and_a_missing_side_is_noted(self) -> None:
        got, problems = value({"value": 1, "unit": "mm", "tolerance": {},
                               "from": {"words": [0]}})  # fmt: skip
        self.assertIsNone(got)
        self.assertIn("plus, minus or both", str(problems.faults[0]))
        got, problems = value({"value": 1, "unit": "mm", "tolerance": {"plus": 0.1},
                               "from": {"words": [0]}})  # fmt: skip
        assert got is not None
        self.assertIn("minus not given", str(problems.notes[0]))

    def test_huge_numbers_are_faults_not_crashes(self) -> None:
        got, problems = value({"value": 10**400, "unit": "mm", "from": {"words": [0]}})
        self.assertIsNone(got)
        self.assertIn("too large", str(problems.faults[0]))
        got, problems = value(
            {
                "value": 1,
                "unit": "mm",
                "tolerance": {"plus": 10**400},
                "from": {"words": [0]},
            }
        )
        self.assertIsNone(got)
        counted, problems = count({"count": 10**400, "from": {"words": [0]}})
        self.assertIsNone(counted)
        self.assertIn("is not a part", str(problems.faults[0]))

    def test_a_dimensionless_compound_unit_is_not_a_unit(self) -> None:
        for unit in ("mm/mm", "mm^0", "in/in", "m/mm"):
            got, problems = value({"value": 30, "unit": unit, "from": {"words": [0]}})
            self.assertIsNone(got, unit)
            self.assertIn("no dimension", str(problems.faults[0]))
        with self.assertRaises(ValueError):
            Value(Q(30, "mm/mm"), Provenance(Source.BRIEF, (0,)))

    def test_angles_and_percentages_are_allowed(self) -> None:
        for unit in ("deg", "rad", "%"):
            got, problems = value({"value": 30, "unit": unit, "from": {"words": [0]}})
            self.assertIsNotNone(got, unit)
            self.assertFalse(problems, unit)


if __name__ == "__main__":
    unittest.main()
