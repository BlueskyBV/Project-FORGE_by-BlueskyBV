"""V2 stage 1: does a value follow from the words it cites (forge_spec.citations).

This is the check that stops a number being misheard, mistyped or invented on
its way from the brief into the spec. It lists every plausible reading of the
cited words and accepts a value if a reading gives it. Choosing the right
meaning is left to the preview and the person, and these tests say so where
the leniency is deliberate. Three rules keep that leniency from becoming a
hole, and each has tests here: a citation is one number, a number with a unit
is not a count, and a conversion is exact unless the number can't be.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

from forge_spec import (
    Follows,
    check_count,
    check_quantity,
    is_numeric_word,
    number_words,
    readings,
    unit_of_word,
)
from forge_spec.citations import numeric_at, phrase_value
from forge_spec.words import NumberedBrief
from forge_units import Q

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_corpus import suite_briefs


def at(brief: NumberedBrief, *texts: str) -> tuple[int, ...]:
    """The numbers of the first words with these texts, in order of appearance."""
    out: list[int] = []
    for text in texts:
        out.append(
            next(w.index for w in brief.words if w.text == text and w.index not in out)
        )
    return tuple(out)


def read(text: str, *cite: str) -> set[str]:
    """What the cited words can be read as, using all of their numbers."""
    brief = number_words(text)
    ref = at(brief, *cite)
    numbers = {i for i in ref if is_numeric_word(brief.words[i].text)}
    return {
        r.describe() for r in readings(brief, ref) if numbers <= set(r.number_words)
    }


def quantity(text: str, value: float, unit: str, *cite: str) -> Follows:
    brief = number_words(text)
    return check_quantity(Q(value, unit), brief, at(brief, *cite)).follows


def count(text: str, n: int, *cite: str) -> Follows:
    brief = number_words(text)
    return check_count(n, brief, at(brief, *cite)).follows


class Numerals(unittest.TestCase):
    def test_whole_and_decimal(self) -> None:
        self.assertIn("2.8 mm", read("a 2.8 mm hole", "2.8"))
        self.assertIn("0.5 mm", read("a .5 mm chamfer", ".5"))

    def test_thousands_and_decimal_commas_are_both_offered(self) -> None:
        self.assertIn("1000 N", read("carries 1,000 N", "1,000"))
        self.assertEqual(read("holes 3,4", "3,4"), {"3", "4", "3.4"})
        self.assertIn("2.8 mm", read("a 2,8 mm hole", "2,8"))
        self.assertIn("1.25 mm", read("a 1,250 mm bar", "1,250"))
        self.assertIn("1250 mm", read("a 1,250 mm bar", "1,250"))

    def test_fractions_mixed_and_vulgar(self) -> None:
        self.assertIn("0.5 in", read("a 1/2 in rod", "1/2"))
        self.assertIn("1.5 in", read("a 1-1/2 in rod", "1-1/2"))
        self.assertIn("1.5 in", read("a 1\u00bd in rod", "1\u00bd"))
        self.assertIn("0.75 in", read("a \u00be in rod", "\u00be"))
        self.assertIn("0.5 in", read("a 1\u20442 in rod", "1\u20442"))  # fraction slash

    def test_a_zero_denominator_reads_as_nothing(self) -> None:
        self.assertEqual(read("ratio 1/0", "1/0"), set())

    def test_huge_numerals_read_as_nothing_without_crashing(self) -> None:
        self.assertEqual(
            read("a 1" + "0" * 400 + "/3 mm bar", "1" + "0" * 400 + "/3"), set()
        )
        self.assertEqual(read("a " + "9" * 5000 + " mm bar", "9" * 5000), set())

    def test_negative(self) -> None:
        self.assertIn("-5 deg", read("tilted -5 deg", "-5"))

    def test_units_attached(self) -> None:
        self.assertEqual(read("a 12mm pin", "12mm"), {"12 mm"})
        self.assertEqual(read("at 30\u00b0", "30\u00b0"), {"30 deg"})
        self.assertEqual(read("at 30\u00ba", "30\u00ba"), {"30 deg"})
        self.assertEqual(read('a 2" pipe', '2"'), {"2 in"})
        self.assertEqual(read("a 2'' pipe", "2''"), {"2 in"})
        self.assertEqual(read("a 2\u201d pipe", "2\u201d"), {"2 in"})
        self.assertEqual(read("a 3' rod", "3'"), {"3 ft"})
        self.assertEqual(read("a 4mm-thick wall", "4mm-thick"), {"4 mm"})
        self.assertEqual(read("25 mm\u00b2 area", "25"), {"25", "25 mm^2"})

    def test_feet_and_inches(self) -> None:
        self.assertIn("66 in", read("5'6\" tall", "5'6\""))
        self.assertIn("66 in", read("5' 6\" tall", "5'", '6"'))

    def test_unit_words_spelled_out_capitalised_or_plural(self) -> None:
        self.assertIn("4 mm", read("4 millimeters", "4"))
        self.assertIn("4 mm", read("4 Millimetres", "4"))
        self.assertIn("4 mm", read("4 MM", "4"))
        self.assertIn("30 deg", read("30 degrees", "30"))
        self.assertIn("2 in", read("2 inches", "2"))
        self.assertIn("10 lb", read("10 lbs", "10"))
        self.assertIn("5 kg", read("5 kgs", "5"))

    def test_words_that_parse_as_units_but_are_not_read_as_them(self) -> None:
        self.assertIsNone(unit_of_word("A"))  # amperes, but "5 A plates" is commoner
        self.assertIsNone(unit_of_word("min"))  # minutes, or minimum
        self.assertIsNone(unit_of_word("holes"))
        self.assertIsNone(unit_of_word("4mm"))
        self.assertEqual(read("4 holes", "4"), {"4"})


class NumberWords(unittest.TestCase):
    def test_words(self) -> None:
        self.assertEqual(read("four holes", "four"), {"4"})
        self.assertEqual(read("twenty-four teeth", "twenty-four"), {"24"})
        self.assertEqual(read("a dozen pins", "dozen"), {"12"})
        self.assertEqual(read("a pair of tabs", "pair"), {"2"})
        self.assertEqual(read("both ends", "both"), {"2"})

    def test_inside_compounds_and_markup(self) -> None:
        self.assertEqual(read("a four-hole bracket", "four-hole"), {"4"})
        self.assertEqual(
            read("a one-and-a-half inch rod", "one-and-a-half"), {"1.5", "1.5 in"}
        )
        self.assertEqual(read("a half-dozen pins", "half-dozen"), {"6"})
        self.assertEqual(read("twenty\u2011four teeth", "twenty\u2011four"), {"24"})
        self.assertEqual(read("fo\u00adur holes", "fo\u00adur"), {"4"})

    def test_phrases_across_words(self) -> None:
        self.assertIn("24", read("twenty four teeth", "twenty", "four"))
        self.assertIn("6", read("half a dozen pins", "half", "a", "dozen"))
        self.assertIn("250 mm", read("two hundred fifty mm", "two", "hundred", "fifty"))
        self.assertIn("1.5 in", read("one and a half inch", "one", "and", "a", "half"))
        self.assertIn("4", read("two pairs of tabs", "two", "pairs"))

    def test_the_phrase_grammar(self) -> None:
        cases = {"twenty four": 24, "two hundred and five": 205, "a hundred": 100,
                 "three thousand two hundred": 3200, "two thirds": 2 / 3,
                 "three quarters": 0.75, "a third": 1 / 3, "two dozen": 24}  # fmt: skip
        for phrase, value in cases.items():
            got = phrase_value(phrase.split())
            assert got is not None, phrase
            self.assertAlmostEqual(got, value, msg=phrase)
        for bad in ("twenty twenty", "four five", "and", "hundred and", "a plate", ""):
            self.assertIsNone(phrase_value(bad.split()), bad)

    def test_what_counts_as_a_number_word(self) -> None:
        for word in ("four", "four-hole", "half-ball", "third", "fourfold", "**four**",
                     "M3", "608ZZ", "\u2152", "\u2163", "3DD"):  # fmt: skip
            self.assertTrue(is_numeric_word(word), word)
        for word in ("first", "phone", "tenon", "plate", "a", "3D-printed", "2D-drawing",
                     "mm\u00b2"):  # fmt: skip
            self.assertFalse(is_numeric_word(word), word)


class Designations(unittest.TestCase):
    def test_metric_threads_imply_millimetres(self) -> None:
        self.assertEqual(read("an M4 screw", "M4"), {"4 mm"})
        self.assertEqual(read("an M4x0.7 thread", "M4x0.7"), {"4 mm", "0.7 mm"})
        self.assertEqual(read('an "M4" screw', "M4"), {"4 mm"})

    def test_diameter_and_radius_marks(self) -> None:
        self.assertEqual(read("a \u00d82.8mm hole", "\u00d82.8mm"), {"2.8 mm"})
        self.assertIn("5 mm", read("corners R5 mm", "R5"))

    def test_unified_threads_are_bare_numbers(self) -> None:
        self.assertEqual(read("a 1/4-20 bolt", "1/4-20"), {"0.25", "20"})

    def test_a_chain_inside_one_word_shares_its_unit(self) -> None:
        self.assertEqual(
            read("a 60x40x10mm block", "60x40x10mm"), {"60 mm", "40 mm", "10 mm"}
        )
        self.assertEqual(read("a 10-12mm gap", "10-12mm"), {"10 mm", "12 mm"})


class ChainsAcrossWords(unittest.TestCase):
    def test_a_size_chain_shares_the_unit_at_its_end(self) -> None:
        for number in ("60", "40", "10"):
            self.assertIn(f"{number} mm", read("a block 60 x 40 x 10 mm", number))
        for number in ("60", "40"):
            self.assertIn(f"{number} mm", read("a block 60 x 40 x 10mm", number))
        self.assertIn("60 mm", read("a block 60 By 40 mm", "60"))

    def test_ranges_share_the_unit(self) -> None:
        self.assertIn("10 mm", read("between 10 and 12 mm", "10"))
        self.assertIn("10 mm", read("from 10 to 12 mm", "10"))
        self.assertIn("10 mm", read("from 10 to 12mm", "10"))

    def test_a_chain_stops_at_a_word_that_is_not_part_of_it(self) -> None:
        self.assertEqual(read("a 5 mm hole and 2 mm fillets", "5"), {"5", "5 mm"})
        self.assertEqual(read("4 3 mm", "4"), {"4"})

    def test_a_chain_stops_at_the_end_of_its_sentence(self) -> None:
        self.assertEqual(read("Make 4. Then mm.", "4"), {"4"})

    def test_a_long_chain_is_fast(self) -> None:
        text = " x ".join(str(i) for i in range(1, 3001)) + " mm"
        brief = number_words(text)
        started = time.perf_counter()
        for i in range(0, len(brief.words), 400):
            readings(brief, (i,))
        self.assertLess(time.perf_counter() - started, 2.0)


class ACitationIsOneNumber(unittest.TestCase):
    """A second number can't ride along in another value's citation."""

    def test_a_mixed_number_cannot_be_read_as_its_whole_part(self) -> None:
        self.assertIs(
            quantity("A 4 1/2 in pipe.", 101.6, "mm", "4", "1/2", "in"), Follows.NO
        )
        self.assertIs(
            quantity("A 4 1/2 in pipe.", 114.3, "mm", "4", "1/2", "in"), Follows.YES
        )
        self.assertIs(quantity('A 1 1/2" pin.', 25.4, "mm", "1", '1/2"'), Follows.NO)
        self.assertIs(quantity('A 1 1/2" pin.', 38.1, "mm", "1", '1/2"'), Follows.YES)

    def test_two_values_in_one_citation(self) -> None:
        brief = number_words("A plate with a 5 mm hole and 2 mm fillets.")
        result = check_quantity(Q(5, "mm"), brief, at(brief, "5", "mm", "2", "mm"))
        self.assertIs(result.follows, Follows.NO)
        self.assertIn("holds 2 numbers", result.message)
        self.assertIs(
            quantity("Two 4 mm holes, 6 mm apart.", 6, "mm", "4", "mm", "6"), Follows.NO
        )

    def test_a_phrase_must_be_read_whole(self) -> None:
        self.assertIs(
            quantity("two hundred mm", 100, "mm", "two", "hundred", "mm"), Follows.NO
        )
        self.assertIs(
            quantity("two hundred mm", 200, "mm", "two", "hundred", "mm"), Follows.YES
        )

    def test_an_article_gives_one_only_when_no_number_is_cited(self) -> None:
        self.assertIs(count("a hole", 1, "a"), Follows.YES)
        self.assertIs(count("a set of four holes", 1, "a", "four"), Follows.NO)


class QuantitiesFollowOrNot(unittest.TestCase):
    def test_exact_in_the_brief_s_own_unit(self) -> None:
        self.assertIs(quantity("a 2.8 mm hole", 2.8, "mm", "2.8", "mm"), Follows.YES)

    def test_a_different_number_does_not_follow(self) -> None:
        self.assertIs(quantity("a 2.8 mm hole", 2.5, "mm", "2.8", "mm"), Follows.NO)

    def test_no_rounding_without_a_conversion(self) -> None:
        self.assertIs(quantity("a 100 mm bar", 100.04, "mm", "100"), Follows.NO)

    def test_exact_conversions_must_be_exact(self) -> None:
        self.assertIs(quantity("a 1/2 in rod", 12.7, "mm", "1/2"), Follows.YES)
        self.assertIs(
            quantity("a 1 1/2 in pin", 38.1, "mm", "1", "1/2", "in"), Follows.YES
        )
        self.assertIs(quantity("a 2 cm tab", 20, "mm", "2"), Follows.YES)
        self.assertIs(quantity("a 2 m rail", 2001, "mm", "2"), Follows.NO)
        self.assertIs(quantity("a 100 in bar", 2541, "mm", "100"), Follows.NO)
        self.assertIs(quantity("a 10 cm bar", 100.05, "mm", "10"), Follows.NO)
        self.assertIs(quantity("a 7.25 in bar", 184.2, "mm", "7.25"), Follows.NO)
        self.assertIs(quantity("a 7.25 in bar", 184.15, "mm", "7.25"), Follows.YES)

    def test_an_endless_conversion_may_be_rounded_a_little(self) -> None:
        self.assertIs(quantity("a 1/3 in rod", 8.467, "mm", "1/3"), Follows.YES)
        self.assertIs(quantity("a 1/3 in rod", 8.47, "mm", "1/3"), Follows.YES)
        self.assertIs(quantity("a 1/3 in rod", 8.5, "mm", "1/3"), Follows.NO)
        self.assertIs(quantity("tilt 30 deg", 0.5236, "rad", "30"), Follows.YES)
        self.assertIs(quantity("tilt 30 deg", 0.5, "rad", "30"), Follows.NO)

    def test_the_wrong_kind_of_quantity_does_not_follow(self) -> None:
        self.assertIs(quantity("a 4 mm hole", 4, "deg", "4"), Follows.NO)
        # Angles and ratios are both dimensionless; "30 deg" is not 52 %.
        self.assertIs(quantity("tilt 30 deg", 52.35987755982988, "%", "30"), Follows.NO)

    def test_a_number_with_no_unit_is_an_assumption(self) -> None:
        brief = number_words("a plate 60 by 40, 4 thick")
        result = check_quantity(Q(4, "mm"), brief, at(brief, "4"))
        self.assertIs(result.follows, Follows.UNIT_NOT_STATED)
        self.assertIn("no unit", result.message)

    def test_a_quoted_number_has_no_foot_mark(self) -> None:
        self.assertIs(quantity("a 'size 10' bolt", 3048, "mm", "10"), Follows.NO)
        self.assertIs(quantity('an "M4" screw', 4, "mm", "M4"), Follows.YES)

    def test_a_different_sign_is_shown_not_hidden(self) -> None:
        self.assertIs(
            quantity("tilted -5 deg", 5, "deg", "-5"), Follows.YES_WITH_CAVEAT
        )
        self.assertIs(
            quantity("a 5 mm hole", -5, "mm", "5", "mm"), Follows.YES_WITH_CAVEAT
        )
        # An absolute temperature's sign is never a direction.
        self.assertIs(quantity("store at -10 degC", 10, "degC", "-10"), Follows.NO)

    def test_in_as_inches_is_shown_when_it_may_be_a_preposition(self) -> None:
        brief = number_words("2 in each corner")
        self.assertIs(check_count(2, brief, (0,)).follows, Follows.YES)
        self.assertIs(
            check_quantity(Q(50.8, "mm"), brief, (0, 1)).follows,
            Follows.YES_WITH_CAVEAT,
        )

    def test_citing_no_number(self) -> None:
        brief = number_words("a round plate")
        result = check_quantity(Q(4, "mm"), brief, (1,))
        self.assertIs(result.follows, Follows.NO)
        self.assertIn("no number", result.message)

    def test_citing_a_word_that_does_not_exist(self) -> None:
        brief = number_words("a round plate")
        result = check_quantity(Q(4, "mm"), brief, (9,))
        self.assertIs(result.follows, Follows.NO)
        self.assertIn("word 9 does not exist", result.message)

    def test_the_message_shows_what_the_words_say(self) -> None:
        brief = number_words("a 2.8 mm hole")
        result = check_quantity(Q(2.5, "mm"), brief, at(brief, "2.8", "mm"))
        self.assertIn("'2.8 mm'", result.message)

    def test_common_phrasings(self) -> None:
        self.assertIs(quantity("a 10-12mm gap", 10, "mm", "10-12mm"), Follows.YES)
        self.assertIs(quantity("5'6\" tall", 1676.4, "mm", "5'6\""), Follows.YES)
        self.assertIs(
            quantity("10 lbs load", 4.5359237, "kg", "10", "lbs"), Follows.YES
        )
        self.assertIs(
            quantity("a 2,8 mm hole", 2.8, "mm", "2,8", "mm"), Follows.YES_WITH_CAVEAT
        )
        self.assertIs(quantity('a 1 1/2" pin', 38.1, "mm", "1", '1/2"'), Follows.YES)


class CountsFollowOrNot(unittest.TestCase):
    def test_numerals_and_words(self) -> None:
        self.assertIs(count("4 holes", 4, "4"), Follows.YES)
        self.assertIs(count("four holes", 4, "four"), Follows.YES)
        self.assertIs(count("a four-hole flange", 4, "four-hole"), Follows.YES)
        self.assertIs(count("twenty four teeth", 24, "twenty", "four"), Follows.YES)
        self.assertIs(count("half a dozen pins", 6, "half", "a", "dozen"), Follows.YES)
        self.assertIs(count("4x M3 holes", 4, "4x"), Follows.YES)
        self.assertIs(count("a pair of tabs", 2, "pair"), Follows.YES)

    def test_a_wrong_count(self) -> None:
        self.assertIs(count("four holes", 1, "four"), Follows.NO)
        self.assertIs(count("each a 5.5 mm hole", 2, "5.5"), Follows.NO)

    def test_a_number_with_a_unit_is_not_a_count(self) -> None:
        brief = number_words("four 4 mm holes")
        result = check_count(4, brief, at(brief, "4", "mm"))
        self.assertIs(result.follows, Follows.NO)
        self.assertIn("a size, not a count", result.message)
        self.assertIs(count("an M4 screw", 4, "M4"), Follows.NO)

    def test_a_fraction_is_not_a_count(self) -> None:
        self.assertIs(count("half the holes", 1, "half"), Follows.NO)


class FoundInTheSecondReview(unittest.TestCase):
    """Each of these once lost a number, misread one, or refused a right one."""

    def test_a_comma_read_as_a_decimal_point_is_shown(self) -> None:
        self.assertIs(
            quantity("carries 1,000 N", 1, "N", "1,000"), Follows.YES_WITH_CAVEAT
        )
        # ...and so is a comma read as a thousands separator: "1,250 mm" is
        # 1250 mm in English and 1.25 mm in much of Europe.
        self.assertIs(
            quantity("carries 1,000 N", 1000, "N", "1,000"), Follows.YES_WITH_CAVEAT
        )
        self.assertIs(
            quantity("a 1,250 mm bar", 1250, "mm", "1,250"), Follows.YES_WITH_CAVEAT
        )
        self.assertIs(count("1,000 holes", 1, "1,000"), Follows.YES_WITH_CAVEAT)

    def test_a_unit_lent_along_a_chain_does_not_veto_a_count(self) -> None:
        self.assertIs(count("Use 4 x M3 screws.", 4, "4"), Follows.YES)
        self.assertIs(count("Drill 4 x 3 mm holes.", 4, "4"), Follows.YES)
        self.assertIs(count("2 x M4 bolts", 2, "2"), Follows.YES)
        self.assertIs(count("4 x M3 x 10 screws", 4, "4"), Follows.YES)

    def test_a_designation_s_millimetres_are_not_lent_along_a_chain(self) -> None:
        self.assertIsNot(quantity("Use 4 x M3 screws.", 4, "mm", "4"), Follows.YES)
        self.assertEqual(read("Use 4xM3 screws.", "4xM3"), {"4", "3 mm"})

    def test_a_unit_after_a_hyphen(self) -> None:
        self.assertIs(quantity("a 2-inch pipe", 50.8, "mm", "2-inch"), Follows.YES)
        self.assertIs(quantity("a 1/2-inch rod", 12.7, "mm", "1/2-inch"), Follows.YES)
        self.assertIs(quantity("a half-inch rod", 12.7, "mm", "half-inch"), Follows.YES)
        self.assertIs(
            quantity("a quarter-inch rod", 6.35, "mm", "quarter-inch"), Follows.YES
        )
        self.assertIs(quantity("a 10-mm hole", 10, "mm", "10-mm"), Follows.YES)

    def test_more_number_words(self) -> None:
        for word in ("dual", "twin", "quad", "quadruple", "once", "thrice"):
            self.assertTrue(is_numeric_word(word), word)
        self.assertIs(count("dual hooks", 2, "dual"), Follows.YES)

    def test_a_numeral_with_a_scale_word(self) -> None:
        self.assertIs(
            quantity("2 thousand mm", 2000, "mm", "2", "thousand", "mm"), Follows.YES
        )
        self.assertIs(count("3 dozen pins", 36, "3", "dozen"), Follows.YES)
        self.assertIs(count("2 pairs of tabs", 4, "2", "pairs"), Follows.YES)

    def test_in_total_is_shown(self) -> None:
        self.assertIs(
            quantity("Make 3 in total", 76.2, "mm", "3", "in"), Follows.YES_WITH_CAVEAT
        )

    def test_a_unit_lent_along_a_short_x_chain_is_shown(self) -> None:
        self.assertIs(
            quantity("Drill 4 x 3 mm holes.", 4, "mm", "4"), Follows.YES_WITH_CAVEAT
        )
        self.assertIs(
            quantity("Print 2 and 10 mm spacers", 2, "mm", "2"), Follows.YES_WITH_CAVEAT
        )
        self.assertIs(
            quantity("Drill 4 x 3 mm holes.", 3, "mm", "3", "mm"), Follows.YES
        )
        # Three sizes in a row, or "by" and "to", are sizes sharing a unit.
        self.assertIs(quantity("a block 60 x 40 x 10 mm", 60, "mm", "60"), Follows.YES)
        self.assertIs(quantity("a 30 by 40 mm plate", 30, "mm", "30"), Follows.YES)
        self.assertIs(quantity("from 10 to 12 mm", 10, "mm", "10"), Follows.YES)

    def test_no_crash_on_a_huge_mixed_number(self) -> None:
        text = "a " + "9" * 5000 + " 1/2 in rod"
        brief = number_words(text)
        result = check_quantity(Q(1, "in"), brief, (1, 2, 3))
        self.assertIs(result.follows, Follows.NO)

    def test_an_unreadable_numeral_says_so(self) -> None:
        brief = number_words("ratio 1/0")
        result = check_quantity(Q(1, "mm"), brief, (1,))
        self.assertIn("can't be read as a number", result.message)


class OnEveryBriefOfV1sValidationSuite(unittest.TestCase):
    def test_every_number_in_every_brief_has_a_reading(self) -> None:
        for brief_text in suite_briefs():
            brief = number_words(brief_text)
            for word in brief.words:
                if numeric_at(
                    brief, word.index
                ):  # in its place: "both A and B" counts nothing
                    self.assertTrue(
                        readings(brief, (word.index,)),
                        f"{word.text!r} in {brief_text!r}",
                    )

    def test_every_number_followed_by_a_length_unit_reads_back_exactly(self) -> None:
        checked = 0
        for brief_text in suite_briefs():
            brief = number_words(brief_text)
            for word in brief.words[:-1]:
                after = brief.words[word.index + 1]
                if after.text == "mm" and word.text.replace(".", "", 1).isdigit():
                    value = Q(float(word.text), "mm")
                    result = check_quantity(value, brief, (word.index, after.index))
                    self.assertIs(result.follows, Follows.YES, brief_text)
                    checked += 1
        self.assertGreater(checked, 300)


if __name__ == "__main__":
    unittest.main()
