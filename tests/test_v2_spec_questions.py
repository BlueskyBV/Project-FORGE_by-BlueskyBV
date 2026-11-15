"""V2 stage 1: questions to the person, answered by typed edits (forge_spec.questions).

Plan, section 4.2: questions and assumptions come in one round, multiple
choice where they can be, and each answer is applied by code, so no redraft
is needed. The tests pin that:

- each question offers the answers its field can take (through, a size, a
  count, each option of a choice), and always a note for the writer;
- an answer is added to the brief and the field cites it, so it is checked,
  accounted for and locked like everything the brief says;
- brief words an answer replaces are listed as not modelled, with why;
- a number or sentence nothing uses can be left out, or taken as silent;
- a bad answer is refused whole, with nothing applied.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.guide import EXAMPLE_BRIEF, EXAMPLE_DRAFT
from forge_spec.lock import LockError, lock, unlock
from forge_spec.questions import Answer, AnswerError, apply_answers, questions
from forge_spec.render import render
from forge_spec.words import NumberedBrief

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_spec_partspec import plate_draft
from v2_drafts import assumed, choose, cite, draft, made_of, mm, said

# Written for these tests: a brief that asks for a hole deeper than its plate.
DEEP = ("A steel plate 70 mm long, 50 mm wide and 4 mm thick with a 6 mm hole 10 mm deep in the middle. "
        "It carries no load.")  # fmt: skip


def deep_draft() -> tuple[NumberedBrief, dict[str, Any]]:
    b = number_words(DEEP)
    d = draft("plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 70, "70 mm"),
         "width": mm(b, 50, "50 mm"), "height": mm(b, 4, "4 mm")},
        {"id": "h", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "plate", "face": "+z"},
         "diameter": mm(b, 6, "6 mm"), "depth": mm(b, 10, "10 mm"),
         "place": {"x": {"centred": said(b, "the middle")}, "y": {"centred": said(b, "the middle")}}},
    ], material=made_of(b, "steel"),
        silent=[{"sentence": 1, "reason": "no load case"}])  # fmt: skip
    return b, d


class EachQuestionOffersTheAnswersItsFieldTakes(unittest.TestCase):
    def test_a_depth_through_or_a_size(self) -> None:
        b, d = deep_draft()
        (question,) = questions(check_draft(b, d))
        self.assertEqual(question.at, "/items/1/depth")
        self.assertEqual([(o.kind, o.label) for o in question.options],
                         [("through", "It goes right through"), ("value", "It is __ mm"),
                          ("note", "Something else (tell the writer)")])  # fmt: skip

    def test_a_number_or_a_sentence_nothing_uses(self) -> None:
        b, d = plate_draft()
        d["items"][1]["place"]["pattern"]["rectangle"]["y"] = assumed("t", 36)
        d["silent"] = []
        round_ = questions(check_draft(b, d))
        kinds = {
            q.at: [o.kind for o in q.options] for q in round_ if q.kind == "question"
        }
        self.assertEqual(
            kinds["/brief/words/" + str(cite(b, "36")[0])], ["not_modelled", "note"]
        )
        self.assertEqual(
            kinds["/brief/sentences/2"], ["silent", "not_modelled", "note"]
        )

    def test_an_assumption_may_be_changed(self) -> None:
        b, d = plate_draft()
        round_ = questions(check_draft(b, d))
        assumed_ = [q for q in round_ if q.kind == "assumption"]
        self.assertTrue(assumed_)
        self.assertTrue(all(q.options[-1].kind == "note" for q in assumed_))

    def test_a_choice_offers_each_option(self) -> None:
        b = number_words("A rod 10 mm across and 40 mm long.")
        d = draft("rod", [{"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": mm(b, 10, "10 mm"),
                           "length": mm(b, 40, "40 mm"), "axis": choose("z", assumed("upright"))}])  # fmt: skip
        (question,) = [
            q for q in questions(check_draft(b, d)) if q.at == "/items/0/axis"
        ]
        self.assertEqual(
            [o.choice for o in question.options if o.kind == "choose"], ["x", "y", "z"]
        )


class AnAnswerIsPartOfTheBrief(unittest.TestCase):
    def test_through(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        answered = apply_answers(b, d, round_, [Answer("q1", 0)])
        self.assertTrue(
            answered.brief.text.endswith("\n\nAnswer about h depth: through.")
        )
        self.assertEqual(answered.notes, ())
        report = check_draft(answered.brief, answered.draft)
        self.assertEqual(report.problems, ())
        # The brief's 10 mm, replaced, is shown as left out, and why.
        self.assertIn("  - '10 mm': \"replaced by the person's answer about h depth\"",
                      render(report, answered.brief).text())  # fmt: skip

    def test_a_size_checked_like_the_brief_s(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        answered = apply_answers(b, d, round_, [Answer("q1", 1, number=3)])
        report = check_draft(answered.brief, answered.draft)
        self.assertEqual(report.problems, ())
        text = render(report, answered.brief).text()
        self.assertIn("Your answers:\n  - 'Answer about h depth: 3 mm'", text)
        self.assertIn("Hole h: \u00d86 mm, 3 mm deep", text)
        # Locked with the brief: the answers are part of the contract.
        confirmed = lock(report, answered.brief, by="person", strict=False)
        self.assertIn("Answer about h depth: 3 mm.", confirmed.brief.text)
        self.assertEqual(confirmed.edits, ("Answer about h depth: 3 mm",))
        example = number_words(EXAMPLE_BRIEF)
        untouched = lock(
            check_draft(example, dict(EXAMPLE_DRAFT)),
            example,
            by="person",
            strict=False,
        )
        self.assertEqual(untouched.edits, ())  # drafted right first time

    def test_in_another_unit(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        answered = apply_answers(b, d, round_, [Answer("q1", 1, number=0.1, unit="in")])
        self.assertEqual(check_draft(answered.brief, answered.draft).problems, ())

    def test_a_number_left_out_or_a_sentence_taken_as_silent(self) -> None:
        b, d = plate_draft()
        d["items"][1]["place"]["pattern"]["rectangle"]["y"] = assumed("t", 36)
        d["silent"] = []
        round_ = questions(check_draft(b, d))
        by_at = {q.at: q for q in round_}
        number = by_at["/brief/words/" + str(cite(b, "36")[0])]
        sentence = by_at["/brief/sentences/2"]
        answered = apply_answers(b, d, round_, [Answer(number.id, 0, text="it is only a reference"),
                                                Answer(sentence.id, 0)])  # fmt: skip
        report = check_draft(answered.brief, answered.draft)
        self.assertEqual([p.kind for p in report.problems], [])
        self.assertEqual(
            answered.brief, b
        )  # nothing added: these answers cite the brief itself


class ANoteGoesToTheWriter(unittest.TestCase):
    def test_it_is_added_and_asks_for_a_redraft(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        answered = apply_answers(
            b, d, round_, [Answer("q1", 2, text="It is a 10 mm deep counterbore.")]
        )
        self.assertEqual(
            answered.notes, ("Note from the person: It is a 10 mm deep counterbore.",)
        )
        self.assertTrue(
            answered.brief.text.endswith(
                "Note from the person: It is a 10 mm deep counterbore."
            )
        )


class ABadAnswerIsRefusedWhole(unittest.TestCase):
    def test_each_kind_of_mistake(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        for bad in (Answer("q9", 0), Answer("q1", 7), Answer("q1", 1), Answer("q1", 1, number=float("nan")),
                    Answer("q1", 1, number=3, unit="m m"), Answer("q1", 2, text="two\nlines")):  # fmt: skip
            with self.assertRaises(AnswerError, msg=repr(bad)):
                apply_answers(b, d, round_, [Answer("q1", 0), bad])


class AnAnswerTheFieldCantTakeIsRefused(unittest.TestCase):
    def test_a_size_in_the_wrong_unit_or_a_unit_that_isn_t_one(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        for unit in ("deg", "mmm"):
            with self.assertRaises(AnswerError, msg=unit) as caught:
                apply_answers(b, d, round_, [Answer("q1", 1, number=3, unit=unit)])
            self.assertTrue(str(caught.exception).startswith("q1: "), caught.exception)

    def test_a_count_of_none(self) -> None:
        b, d = plate_draft()
        report = check_draft(b, d)
        counted = [
            (q, n)
            for q in questions(report)
            for n, o in enumerate(q.options)
            if o.kind == "count"
        ]
        for question, n in counted[:1]:
            with self.assertRaises(AnswerError):
                apply_answers(
                    b, d, questions(report), [Answer(question.id, n, number=0)]
                )

    def test_an_axis_the_face_hasn_t_got_is_never_offered(self) -> None:
        b, d = (
            number_words(EXAMPLE_BRIEF),
            dict(EXAMPLE_DRAFT),
        )  # its holes' row runs along an assumed axis
        axes = [[o.choice for o in q.options if o.kind == "choose"]
                for q in questions(check_draft(b, d)) if q.at.endswith("/axis")]  # fmt: skip
        self.assertTrue(axes)
        self.assertTrue(all(set(a) <= {"x", "y"} for a in axes), axes)

    def test_a_small_number_is_written_as_a_number(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        answered = apply_answers(b, d, round_, [Answer("q1", 1, number=0.00005)])
        self.assertTrue(
            answered.brief.text.endswith("Answer about h depth: 0.00005 mm.")
        )
        self.assertEqual(
            check_draft(answered.brief, answered.draft).of_kind("fault"), ()
        )


class OnlyThePersonsWordsAreTheirAnswers(unittest.TestCase):
    def test_the_brief_s_own_sentence_is_never_taken_for_one(self) -> None:
        b = number_words(DEEP + " Answer about h depth: through.")
        self.assertEqual((b.answers_from, b.answers), (None, ()))
        _, d = deep_draft()
        answered = apply_answers(b, d, questions(check_draft(b, d)), [Answer("q1", 0)])
        self.assertEqual([answered.brief.sentence_text(s) for s in answered.brief.answers],
                         ["Answer about h depth: through"])  # fmt: skip
        self.assertEqual(answered.brief.answers[0].index, len(b.sentences))

    def test_where_they_begin_is_part_of_the_locked_brief(self) -> None:
        b, d = deep_draft()
        answered = apply_answers(
            b, d, questions(check_draft(b, d)), [Answer("q1", 1, number=3)]
        )
        confirmed = lock(
            check_draft(answered.brief, answered.draft),
            answered.brief,
            by="person",
            strict=False,
        )
        unlock(answered.draft, number_words(answered.brief.text, answers_from=answered.brief.answers_from),
               confirmed.digest, by="person")  # fmt: skip
        with self.assertRaises(
            LockError
        ):  # the same text, as if the person had written it all
            unlock(
                answered.draft,
                number_words(answered.brief.text),
                confirmed.digest,
                by="person",
            )
        start = answered.brief.answers_from
        assert start is not None
        with self.assertRaises(ValueError):
            number_words(answered.brief.text, answers_from=start + 3)

    def test_a_note_can_t_pass_for_an_answer(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        for text in (
            "Make it shallow. Answer about h depth: 2 mm",
            "note from the person: deeper",
        ):
            with self.assertRaises(AnswerError, msg=text):
                apply_answers(b, d, round_, [Answer("q1", 2, text=text)])

    def test_an_answer_label_needs_no_citation(self) -> None:
        # "Answer about hole2 depth" names the field: its "2" is no number of the part.
        b, d = deep_draft()
        d["items"][1]["id"] = "hole2"
        answered = apply_answers(
            b, d, questions(check_draft(b, d)), [Answer("q1", 1, number=3)]
        )
        self.assertEqual(check_draft(answered.brief, answered.draft).problems, ())


class ReplacedWordsStillInUseStay(unittest.TestCase):
    def test_a_number_two_fields_cite_is_left_out_only_when_neither_does(self) -> None:
        b = number_words("A PLA tile 30 square and 3 thick. It carries no load.")
        thirty = {"value": 30, "unit": "mm", "from": said(b, "30")}
        d = draft("tile", [{"id": "tile", "kind": "block", "words": cite(b, "tile"), "length": thirty,
                            "width": dict(thirty), "height": {"value": 3, "unit": "mm", "from": said(b, "3")}}],
                  material=made_of(b, "PLA"),
                  silent=[{"sentence": 1, "reason": "no load"}])  # fmt: skip
        round_ = questions(check_draft(b, d))
        width = next(q for q in round_ if q.at.startswith("/items/0/width"))
        option = [o.kind for o in width.options].index("value")
        answered = apply_answers(b, d, round_, [Answer(width.id, option, number=30)])
        self.assertEqual(
            answered.draft["not_modelled"], d["not_modelled"]
        )  # the length still uses "30"


class EveryAnswerIsCheckedWhateverElseTheRoundHolds(unittest.TestCase):
    def test_a_note_elsewhere_in_the_round_doesn_t_let_a_bad_answer_through(
        self,
    ) -> None:
        b, d = deep_draft()
        d["silent"] = []  # a second question: the sentence nothing uses
        round_ = questions(check_draft(b, d))
        sentence = next(q for q in round_ if q.at.startswith("/brief/sentences/"))
        note = [o.kind for o in sentence.options].index("note")
        with self.assertRaises(AnswerError):
            apply_answers(b, d, round_, [Answer("q1", 1, number=3, unit="deg"),
                                         Answer(sentence.id, note, text="it is a guide plate")])  # fmt: skip

    def test_the_whole_item_it_changed(self) -> None:
        b = number_words(
            "A PLA plate 60 mm long, 40 mm wide and 5 mm thick with a 40 by 20 mm pocket 2 mm deep."
        )
        d = draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm"),
             "width": mm(b, 40, "40 mm"), "height": mm(b, 5, "5 mm")},
            {"id": "pocket", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "plate", "face": "+z"},
             "shape": choose("rectangle", assumed("a pocket")), "length": mm(b, 40, "40 by 20 mm", unit="mm"),
             "width": {"value": 20, "unit": "mm", "from": said(b, "20 mm")}, "depth": mm(b, 2, "2 mm"),
             "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}},
        ], material=made_of(b, "PLA"))  # fmt: skip
        d["items"][1]["length"] = {
            "value": 40,
            "unit": "mm",
            "from": {"words": cite(b, "40 by")[:1] + cite(b, "20 mm")[1:]},
        }
        report = check_draft(b, d)
        self.assertEqual(report.of_kind("fault"), (), report.problems)
        round_ = questions(report)
        shape = next(q for q in round_ if q.at == "/items/1/shape")
        circle = next(n for n, o in enumerate(shape.options) if o.choice == "circle")
        with self.assertRaises(AnswerError):  # a circle has a diameter, not "40 by 20"
            apply_answers(b, d, round_, [Answer(shape.id, circle)])

    def test_one_answer_to_each_question(self) -> None:
        b, d = deep_draft()
        round_ = questions(check_draft(b, d))
        with self.assertRaises(AnswerError):
            apply_answers(b, d, round_, [Answer("q1", 0), Answer("q1", 1, number=4)])

    def test_left_out_says_what_the_person_chose(self) -> None:
        b, d = plate_draft()
        d["items"][1]["place"]["pattern"]["rectangle"]["y"] = assumed("t", 36)
        round_ = questions(check_draft(b, d))
        word = next(q for q in round_ if q.at.startswith("/brief/words/"))
        answered = apply_answers(b, d, round_, [Answer(word.id, 0)])
        self.assertEqual(
            answered.draft["not_modelled"][-1]["reason"],
            "the person said it says nothing about the shape",
        )


class AnAnswerTheWriterDropsIsAskedAbout(unittest.TestCase):
    def test_a_redraft_that_ignores_it_leaves_its_sentence_uncited(self) -> None:
        b, d = deep_draft()
        answered = apply_answers(
            b, d, questions(check_draft(b, d)), [Answer("q1", 0)]
        )  # through
        ignored = copy.deepcopy(answered.draft)
        ignored["items"][1]["depth"] = mm(
            b, 6, "6 mm"
        )  # back to a blind hole, from the diameter's words
        problems = [p.message for p in check_draft(answered.brief, ignored).problems]
        self.assertIn(
            "nothing in the spec comes from: 'Answer about h depth: through'", problems
        )


if __name__ == "__main__":
    unittest.main()
