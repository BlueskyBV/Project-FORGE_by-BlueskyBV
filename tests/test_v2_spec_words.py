"""V2 stage 1: numbering the brief (forge_spec.words).

The numbering is what every citation in a spec points at, so it has to be the
same every time, cover the whole brief, and never merge two sentences (a merged
sentence could hide an unaccounted one behind a word cited in the other).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from forge_spec import number_words

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_corpus import suite_briefs


def texts(brief: str) -> list[str]:
    return [w.text for w in number_words(brief).words]


def sentences(brief: str) -> list[str]:
    numbered = number_words(brief)
    return [numbered.sentence_text(s) for s in numbered.sentences]


class WordsAreRunsOfTextWithPunctuationPeeledOff(unittest.TestCase):
    def test_a_plain_sentence(self) -> None:
        self.assertEqual(
            texts("A plate 60 mm long, 4 mm thick."),
            ["A", "plate", "60", "mm", "long", "4", "mm", "thick"],
        )

    def test_brackets_quotes_and_markup_are_peeled_off(self) -> None:
        self.assertEqual(texts('("rounded") [R5] {x}'), ["rounded", "R5", "x"])
        self.assertEqual(
            texts("**four** holes, _two_ `tabs`"), ["four", "holes", "two", "tabs"]
        )

    def test_compound_forms_stay_whole(self) -> None:
        brief = "An M4x0.7 thread, a 1/4-20 bolt, twenty-four teeth, a 4mm-thick wall."
        self.assertEqual(
            texts(brief),
            ["An", "M4x0.7", "thread", "a", "1/4-20", "bolt", "twenty-four",
             "teeth", "a", "4mm-thick", "wall"],
        )  # fmt: skip

    def test_an_inch_or_foot_mark_after_a_digit_is_kept(self) -> None:
        self.assertEqual(
            texts("A 2\" pipe, 3' long."), ["A", '2"', "pipe", "3'", "long"]
        )
        self.assertEqual(texts("A 2'' pipe"), ["A", "2''", "pipe"])
        self.assertEqual(texts("a 2\u201d pipe"), ["a", "2\u201d", "pipe"])

    def test_a_quote_closing_after_a_digit_is_a_quote(self) -> None:
        self.assertEqual(texts('An "M4" screw.'), ["An", "M4", "screw"])
        self.assertEqual(texts("A 'size 10' bolt"), ["A", "size", "10", "bolt"])
        self.assertEqual(texts("a \u201cM4\u201d screw"), ["a", "M4", "screw"])
        # Opened by a mark that is no word, the quote is still open where it closes.
        self.assertEqual(
            texts("reading \u201c\u00b6 Y2\u201d, 3 mm"), ["reading", "Y2", "3", "mm"]
        )

    def test_a_closing_quote_after_a_letter_is_peeled(self) -> None:
        self.assertEqual(texts('the "lid".'), ["the", "lid"])

    def test_measuring_symbols_alone_are_words(self) -> None:
        self.assertEqual(
            texts("30 \u00b0 and \u00b1 0.1"), ["30", "\u00b0", "and", "\u00b1", "0.1"]
        )

    def test_pure_punctuation_is_not_a_word(self) -> None:
        self.assertEqual(texts("plate - 4 mm / thick"), ["plate", "4", "mm", "thick"])

    def test_invisible_spaces_separate_words(self) -> None:
        self.assertEqual(texts("four\u200bholes"), ["four", "holes"])

    def test_offsets_point_at_the_word(self) -> None:
        brief = '  A "plate" (60 mm), 4\u2033 thick.\nTwo holes;three.'
        numbered = number_words(brief)
        for word in numbered.words:
            self.assertEqual(brief[word.start : word.end], word.text)


class SentencesSplitRatherThanMerge(unittest.TestCase):
    def test_full_stops_end_sentences(self) -> None:
        self.assertEqual(
            sentences("A plate. Two holes! Rounded? Yes."),
            ["A plate", "Two holes", "Rounded", "Yes"],
        )

    def test_other_sentence_ends(self) -> None:
        self.assertEqual(len(sentences("Two holes; rounded corners")), 2)
        self.assertEqual(len(sentences("A plate\u2026 hollow")), 2)
        self.assertEqual(len(sentences("A plate... hollow")), 2)
        self.assertEqual(len(sentences("long.Hollow body")), 2)
        self.assertEqual(len(sentences("A plate . Next")), 2)
        self.assertEqual(len(sentences("long\u3002Hollow")), 2)
        self.assertEqual(len(sentences("A plate 60.Two holes")), 2)
        self.assertEqual(len(sentences("A 2.8 mm hole")), 1)

    def test_a_decimal_point_ends_nothing(self) -> None:
        self.assertEqual(len(sentences("A 2.8 mm hole and a 0.5 mm chamfer.")), 1)

    def test_a_number_ending_a_sentence(self) -> None:
        self.assertEqual(len(sentences("The plate is 4. The hole is 2.")), 2)

    def test_listed_abbreviations_end_nothing_before_lower_case(self) -> None:
        self.assertEqual(len(sentences("Round it, e.g. like a coin, approx. 5 mm.")), 1)

    def test_an_abbreviation_ends_a_sentence_before_a_capital(self) -> None:
        self.assertEqual(len(sentences("Round it, e.g. Like a coin.")), 2)

    def test_abbreviations_before_a_number(self) -> None:
        self.assertEqual(len(sentences("A no. 6 screw and a dia. 5 mm pin.")), 1)
        self.assertEqual(len(sentences("Holes: no. none.")), 2)

    def test_abbreviations_that_end_sentences_typed_in_lower_case(self) -> None:
        # Found in review: these once merged, and the second sentence was lost.
        self.assertEqual(
            len(sentences("Rounded corners, chamfers etc. no fillets anywhere.")), 2
        )
        self.assertEqual(len(sentences("Wall 3 mm max. hollow inside.")), 2)
        self.assertEqual(len(sentences("Plate 2 in. no holes.")), 2)
        self.assertEqual(len(sentences("Wall 2 mm nom. hollow body.")), 2)

    def test_abbreviations_that_often_end_sentences_are_not_listed(self) -> None:
        # "dia." and "min." commonly end a sentence; merging would hide one.
        self.assertEqual(len(sentences("Two holes 5 mm dia. The lid is flat.")), 2)
        self.assertEqual(len(sentences("Walls 2 mm min. No holes.")), 2)

    def test_lines_without_full_stops_are_sentences(self) -> None:
        self.assertEqual(
            len(sentences("Plate 60 x 40 x 4 mm\nFour M3 holes\nRounded corners")), 3
        )
        self.assertEqual(
            len(sentences("60mm plate\nfour m3 holes\nhollow\nrounded corners")), 4
        )

    def test_a_line_break_ends_a_sentence_unless_the_line_cannot_end(self) -> None:
        # A line ending in "a", "and", "with"... carries on. Any other line
        # break ends the sentence, even in the middle of prose: splitting
        # costs a question, merging could hide a sentence.
        self.assertEqual(len(sentences("A plate with a\nhole in the middle.")), 1)
        self.assertEqual(len(sentences("A plate 60 mm long and\n40 mm wide.")), 1)
        self.assertEqual(len(sentences("A plate with a hole\nin the middle.")), 2)
        self.assertEqual(len(sentences("a well-\nknown shape")), 1)
        # A line can end in "in" (inches) or "x": those don't carry on.
        self.assertEqual(len(sentences("Width 2 in\nno holes")), 2)
        # "in." ends a sentence: a question at worst, never a lost sentence.
        self.assertEqual(len(sentences("A 2 in. rod")), 2)

    def test_bullets_and_numbered_lines(self) -> None:
        brief = (
            "Parts:\n- a 60 mm plate\n- two holes\n1. round the corners\n2) chamfer it"
        )
        numbered = number_words(brief)
        self.assertEqual(len(numbered.sentences), 5)
        # List numbers stay words: Forge never guesses a number away.
        self.assertIn("1", [w.text for w in numbered.words])
        self.assertIn("2", [w.text for w in numbered.words])

    def test_more_list_styles(self) -> None:
        numbered = number_words("(a) hollow\nii) round\n-hollow\n* flat")
        self.assertEqual(len(numbered.sentences), 4)
        self.assertEqual([w.text for w in numbered.words],
                         ["a", "hollow", "ii", "round", "hollow", "flat"])  # fmt: skip
        self.assertEqual([w.marker for w in numbered.words],
                         [True, False, True, False, False, False])  # fmt: skip

    def test_a_blank_line_ends_a_sentence(self) -> None:
        self.assertEqual(len(sentences("a plate with\n\nholes")), 2)

    def test_every_word_is_in_exactly_one_sentence_in_order(self) -> None:
        numbered = number_words("One. Two three!\n- four\n\nfive six;seven")
        seen: list[int] = []
        for sentence in numbered.sentences:
            seen.extend(sentence.words)
            for i in sentence.words:
                self.assertEqual(numbered.words[i].sentence, sentence.index)
        self.assertEqual(seen, list(range(len(numbered.words))))

    def test_an_empty_brief(self) -> None:
        numbered = number_words("  \n ")
        self.assertEqual((numbered.words, numbered.sentences), ((), ()))


class TheModelSeesNumbersAndCitesOnlyThose(unittest.TestCase):
    def test_the_model_s_view(self) -> None:
        numbered = number_words("A plate. Two holes.")
        self.assertEqual(
            numbered.for_the_model(), "S0: [0]A [1]plate\nS1: [2]Two [3]holes"
        )

    def test_a_brief_cannot_show_the_model_a_fake_word_number(self) -> None:
        self.assertEqual(
            number_words("see x[12]y").for_the_model(), "S0: [0]see [1]x(12)y"
        )

    def test_a_word_that_does_not_exist_is_named(self) -> None:
        numbered = number_words("A plate.")
        with self.assertRaisesRegex(
            LookupError, "word 5 does not exist: the brief has words 0 to 1"
        ):
            numbered.word(5)
        with self.assertRaises(LookupError):
            numbered.word(-1)
        with self.assertRaises(LookupError):
            numbered.word(True)

    def test_quote_shows_cited_words_in_order(self) -> None:
        self.assertEqual(number_words("A plate 60 mm long.").quote((3, 2, 2)), "60 mm")

    def test_not_a_string(self) -> None:
        with self.assertRaises(TypeError):
            number_words(None)  # type: ignore[arg-type]


class OnEveryBriefOfV1sValidationSuite(unittest.TestCase):
    """Invariants on 92 briefs written for real, not for this module."""

    def test_the_suite_is_there(self) -> None:
        self.assertGreaterEqual(len(suite_briefs()), 90)

    def test_numbering_covers_every_brief_exactly(self) -> None:
        for brief in suite_briefs():
            numbered = number_words(brief)
            covered = [i for s in numbered.sentences for i in s.words]
            self.assertEqual(covered, list(range(len(numbered.words))), brief)
            for word in numbered.words:
                self.assertEqual(brief[word.start : word.end], word.text, brief)
                self.assertTrue(word.text.strip(), brief)

    def test_no_letters_or_digits_are_lost(self) -> None:
        for brief in suite_briefs():
            kept = "".join(w.text for w in number_words(brief).words)
            self.assertEqual(
                re.sub(r"[^0-9A-Za-z]", "", kept),
                re.sub(r"[^0-9A-Za-z]", "", brief),
                brief,
            )

    def test_numbering_is_the_same_every_time(self) -> None:
        for brief in suite_briefs():
            self.assertEqual(number_words(brief), number_words(brief))


if __name__ == "__main__":
    unittest.main()
