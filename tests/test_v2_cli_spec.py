"""V2 stage 1: ``forge spec``, the person's side of the spec (forge_cli.spec).

The model is scripted and the person is a list of replies, so these tests pin
the flow, offline:

- a clean draft is shown, its assumptions can be kept, and it is locked only
  when the person types back the code shown in Forge's own window (R12);
- a question is answered by choosing an option, applied by code, with no
  redraft;
- a note for the writer is the one answer that asks for a redraft;
- an automatic run asks nothing: it locks a clean draft as a draft only, and
  stops with the questions it can't answer;
- every draft, round and answer is written down.
"""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

from forge_cli.cli import build_parser
from forge_cli.spec import ControllingTerminal, load_answers, person_code, share_budget
from forge_cli.spec import run_spec as run_spec_as_is
from forge_cli.spec_page import spec_page
from forge_models import ScriptedProvider
from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.guide import EXAMPLE_BRIEF, EXAMPLE_DRAFT
from forge_spec.lock import unlock
from forge_spec.questions import Answer, questions
from forge_spec.wire import to_wire


def run_spec(*args: Any, **options: Any) -> Any:
    """``run_spec`` with one draft unless a test asks for two: each scripted reply is one draft."""
    return run_spec_as_is(*args, **{"two_drafts": "never", **options})


class Person:
    """Replies in order, and everything Forge said."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.heard: list[str] = []

    def ask(self, prompt: str) -> str:
        self.heard.append(prompt)
        if not self.replies:
            raise EOFError("nothing more to type")
        return self.replies.pop(0)

    def say(self, text: str) -> None:
        self.heard.append(text)

    def said(self) -> str:
        return "\n".join(self.heard)


class Window(Person):
    """Forge's own window: the person at it, reading the code and typing it back."""

    def show(self, text: str) -> None:
        self.say(text)

    def read(self, prompt: str) -> str:
        return self.ask(prompt)


def example() -> dict[str, Any]:
    return copy.deepcopy(dict(EXAMPLE_DRAFT))


DEEP = ("A steel plate 70 mm long, 50 mm wide and 4 mm thick with a 6 mm hole 10 mm deep in the middle. "
        "It carries no load.")  # fmt: skip
DEEP_DRAFT: dict[str, Any] = {
    "spec_format": 1, "name": "plate",
    "items": [
        {"id": "plate", "kind": "block", "words": [2], "length": {"value": 70, "unit": "mm", "from": {"words": [3, 4, 5]}},
         "width": {"value": 50, "unit": "mm", "from": {"words": [6, 7, 8]}},
         "height": {"value": 4, "unit": "mm", "from": {"words": [10, 11, 12]}}},
        {"id": "h", "kind": "hole", "words": [17], "on": {"item": "plate", "face": "+z"},
         "diameter": {"value": 6, "unit": "mm", "from": {"words": [15, 16]}},
         "depth": {"value": 10, "unit": "mm", "from": {"words": [18, 19, 20]}},
         "place": {"x": {"centred": {"words": [22, 23]}}, "y": {"centred": {"words": [22, 23]}}}},
    ],
    "requirements": {"material": {"text": "steel", "from": {"words": [1]}}},
    "silent": [{"sentence": 1, "reason": "no load case"}],
}  # fmt: skip
DEPTH_QUESTION = "h's depth is 10 mm deep in 4 mm of material: should it go through, or be shallower?"

CODE = "ABC-234"


def deep(
    person: Person, window: Window | None, *drafts: dict[str, Any], **options: Any
) -> Any:
    provider = ScriptedProvider([copy.deepcopy(d) for d in (drafts or (DEEP_DRAFT,))])
    outcome = run_spec(
        DEEP,
        provider,
        ask=person.ask,
        say=person.say,
        private=window,
        code=lambda: CODE,
        **options,
    )
    return outcome, provider


class ThePersonConfirmsWithTheCode(unittest.TestCase):
    def test_a_clean_draft_its_assumptions_kept(self) -> None:
        person, window = (
            Person("", "", ""),
            Window("abc 234"),
        )  # keep three assumptions; the code, in the window
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=person.ask, say=person.say,
                               private=window, out=out, code=lambda: CODE)  # fmt: skip
            self.assertEqual(outcome.status, "confirmed")
            self.assertIn("type the code ABC-234 here", window.said())
            record = json.loads((out / "confirmed.json").read_text(encoding="utf-8"))
            self.assertEqual((record["by"], record["answers_from"]), ("person", None))
            again = unlock(
                record["spec"],
                number_words(record["brief"]),
                record["digest"],
                by="person",
            )
            self.assertEqual(
                again.digest, outcome.confirmed.digest if outcome.confirmed else ""
            )
            self.assertTrue((out / "round-1" / "spec.txt").exists())
            self.assertTrue((out / "draft-1" / "calls.json").exists())

    def test_the_code_is_never_said_where_a_program_could_read_it(self) -> None:
        # Rule R12: whatever drives the run's input and output never sees the code.
        person, window = Person("", "", ""), Window("ABC234")
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=person.ask, say=person.say,
                           private=window, code=lambda: CODE)  # fmt: skip
        self.assertEqual(outcome.status, "confirmed")
        self.assertNotIn("ABC", person.said())
        self.assertIn("Confirm it in Forge's own window", person.said())

    def test_when_its_output_is_piped_the_window_shows_the_spec_too(self) -> None:
        window = Window("ABC234")
        run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person("", "", "").ask, say=Person().say,
                 private=window, code=lambda: CODE, echo=True)  # fmt: skip
        shown = window.said()
        self.assertLess(
            shown.index("Block plate: 80 mm x 30 mm x 6 mm"),
            shown.index("type the code"),
        )
        quiet = Window("ABC234")
        run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person("", "", "").ask, say=Person().say,
                 private=quiet, code=lambda: CODE)  # fmt: skip
        self.assertNotIn("Block plate", quiet.said())

    def test_without_its_own_window_nothing_can_be_confirmed(self) -> None:
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person("", "", "").ask,
                           say=Person().say, private=None, code=lambda: CODE)  # fmt: skip
        self.assertEqual((outcome.status, outcome.confirmed), ("stopped", None))
        self.assertIn("this run has none", outcome.message)

    def test_without_the_code_nothing_is_locked(self) -> None:
        window = Window("XYZ-999", "abc-235", "")
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person("", "", "").ask,
                           say=Person().say, private=window, code=lambda: CODE)  # fmt: skip
        self.assertEqual((outcome.status, outcome.confirmed), ("stopped", None))

    def test_a_code_typed_with_another_dash_still_reads(self) -> None:
        for typed in ("ABC\u2013234", "abc \u2212 234", " a b c 2 3 4 "):
            _, window = None, Window(typed)
            outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person("", "", "").ask,
                               say=Person().say, private=window, code=lambda: CODE)  # fmt: skip
            self.assertEqual(outcome.status, "confirmed", typed)

    def test_codes_are_fresh_and_unambiguous(self) -> None:
        codes = {person_code() for _ in range(200)}
        self.assertGreater(len(codes), 190)
        self.assertFalse(any(set(c) & set("01OIL") for c in codes))


class AQuestionIsAnsweredByCode(unittest.TestCase):
    def test_through_then_confirm(self) -> None:
        outcome, provider = deep(Person("1"), Window("ABC234"))
        self.assertEqual(outcome.status, "confirmed")
        self.assertEqual(len(provider.requests), 1)  # no redraft
        assert outcome.confirmed is not None
        self.assertIn("Answer about h depth: through.", outcome.confirmed.brief.text)
        self.assertEqual(
            to_wire(outcome.confirmed.spec)["items"][1]["depth"]["through"], True
        )

    def test_a_size_asked_for_and_given(self) -> None:
        outcome, _ = deep(Person("2", "3"), Window("ABC234"))
        self.assertEqual(outcome.status, "confirmed")
        assert outcome.confirmed is not None
        self.assertEqual(
            to_wire(outcome.confirmed.spec)["items"][1]["depth"]["value"], 3
        )

    def test_a_size_that_doesn_t_fit_is_asked_again_and_never_kept(self) -> None:
        person = Person("2", "3 deg", "2", "3")
        outcome, provider = deep(person, Window("ABC234"))
        self.assertEqual(outcome.status, "confirmed", person.said()[-400:])
        self.assertIn("That answer doesn't fit", person.said())
        self.assertEqual(len(provider.requests), 1)  # never sent back to the writer
        assert outcome.confirmed is not None
        self.assertNotIn("deg", outcome.confirmed.brief.text)

    def test_a_note_asks_the_writer_to_redraft(self) -> None:
        # The note becomes the brief's sentences 2 and 3, "Note from the person: It goes
        # through;" and "the 10 mm is a typo.": the redraft follows it, and cites it.
        redrafted = copy.deepcopy(DEEP_DRAFT)
        redrafted["items"][1]["depth"] = {"through": True, "from": {"words": [33, 34]}}
        redrafted["not_modelled"] = [{"words": [18, 19, 20], "reason": "the person says it is a typo"},
                                      {"words": [35, 36, 37, 38, 39, 40], "reason": "the person's note on it"}]  # fmt: skip
        person = Person("3", "It goes through; the 10 mm is a typo")
        outcome, provider = deep(person, Window("ABC234"), DEEP_DRAFT, redrafted)
        self.assertEqual(len(provider.requests), 2)
        self.assertIn("S2: [28]Note [29]from [30]the [31]person [32]It [33]goes [34]through",
                      provider.requests[1].messages[0].content)  # fmt: skip
        self.assertEqual(outcome.status, "confirmed", person.said()[-600:])

    def test_after_a_redraft_every_assumption_is_asked_afresh(self) -> None:
        # Kept once, an assumption is the writer's afresh in a new draft: asked again.
        d = example()
        d["silent"] = []  # sentence 3 then needs an answer: the round's one question
        renoted = (
            example()
        )  # the note is "Note from the person: Keep it for indoor use."
        renoted["not_modelled"] = [
            {"words": [44, 45, 46, 47, 48], "reason": "it says what the part is for"}
        ]
        person = Person("3", "Keep it for indoor use", "", "", "", "", "", "")
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([d, renoted]), ask=person.ask, say=person.say,
                           private=Window("ABC234"), code=lambda: CODE)  # fmt: skip
        self.assertEqual(outcome.status, "confirmed", person.said()[-800:])
        heard = person.said()
        second = heard[heard.index("Drafting the spec (draft 2)") :]
        self.assertEqual(
            (heard.count("(assumption)"), second.count("(assumption)")), (6, 3)
        )

    def test_the_person_may_stop(self) -> None:
        for person in (Person("q"), Person()):  # q, or the terminal closing
            outcome, _ = deep(person, None)
            self.assertEqual(outcome.status, "stopped")

    def test_interrupted_it_stops_and_says_so(self) -> None:
        class Interrupted(Person):
            def ask(self, prompt: str) -> str:
                raise KeyboardInterrupt

        outcome, _ = deep(Interrupted(), None)
        self.assertEqual(
            (outcome.status, outcome.message), ("stopped", "stopped by the person")
        )


class AnswersWrittenDownBeforehand(unittest.TestCase):
    def test_apply_only_to_the_question_they_were_written_for(self) -> None:
        written = Answer("q1", 0, at="/items/1/depth", asked=DEPTH_QUESTION)
        outcome, _ = deep(Person(), Window("ABC234"), answers=[written])
        self.assertEqual(outcome.status, "confirmed")
        stale = Answer(
            "q1", 0, at="/items/1/depth", asked="the depth is 3 mm: is that right?"
        )
        person = Person("2", "3")
        outcome, _ = deep(person, Window("ABC234"), answers=[stale])
        self.assertIn("is now about /items/1/depth", person.said())
        assert outcome.confirmed is not None
        self.assertEqual(
            to_wire(outcome.confirmed.spec)["items"][1]["depth"]["value"], 3
        )

    def test_every_question_they_don_t_answer_is_asked(self) -> None:
        round_ = questions(check_draft(number_words(EXAMPLE_BRIEF), example()))
        axis = next(q for q in round_ if q.at.endswith("/axis"))
        person = Person("", "")  # the two assumptions the written answer doesn't cover
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=person.ask, say=person.say,
                           private=Window("ABC234"), answers=[Answer(axis.id, 0, at=axis.at, asked=axis.text)],
                           code=lambda: CODE)  # fmt: skip
        self.assertEqual(outcome.status, "confirmed")
        for question in round_:
            asked = f"{question.id} ({question.kind}): {question.text}"
            self.assertEqual(asked in person.said(), question is not axis, asked)

    def test_one_that_doesn_t_name_its_question_is_refused(self) -> None:
        person = Person("1")
        outcome, _ = deep(
            person, Window("ABC234"), answers=[Answer("q1", 2, text="anything")]
        )
        self.assertIn("must name its question", person.said())
        self.assertEqual(outcome.status, "confirmed")  # asked, and answered "through"

    def test_an_automatic_run_takes_none(self) -> None:
        args = build_parser().parse_args(["spec", "A plate.", "--auto", "--answers", "a.json",
                                          "--provider", "fixture", "--fixtures", "f"])  # fmt: skip
        with self.assertRaises(SystemExit) as caught:
            args.handler(args)
        self.assertIn("an automatic run asks none", str(caught.exception))

    def test_a_file_of_them_is_checked_before_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "answers.json"
            good: dict[str, Any] = {
                "question": "q1",
                "option": 0,
                "at": "/items/1/depth",
                "asked": DEPTH_QUESTION,
            }
            path.write_text(json.dumps([good]), encoding="utf-8")
            self.assertEqual(load_answers(path), [Answer(**good)])
            for bad in ([{"question": "q1", "option": 0}], [{**good, "option": "0"}], [{**good, "colour": "red"}],
                        [{**good, "at": ""}], [{**good, "asked": " "}],
                        {"q1": 0}, [{**good, "option": True}]):  # fmt: skip
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(SystemExit, msg=bad):
                    load_answers(path)


class AnAutomaticRunAsksNothing(unittest.TestCase):
    BLOCK = "A PLA block 40 mm long, 30 mm wide and 20 mm tall."
    BLOCK_DRAFT: ClassVar[dict[str, Any]] = {
        "spec_format": 1, "name": "block",
        "items": [{"id": "block", "kind": "block", "words": [2],
                   "length": {"value": 40, "unit": "mm", "from": {"words": [3, 4, 5]}},
                   "width": {"value": 30, "unit": "mm", "from": {"words": [6, 7, 8]}},
                   "height": {"value": 20, "unit": "mm", "from": {"words": [10, 11, 12]}}}],
        "requirements": {"material": {"text": "PLA", "from": {"words": [1]}}},
    }  # fmt: skip

    def test_a_clean_draft_is_locked_as_a_draft_only(self) -> None:
        outcome = run_spec(self.BLOCK, ScriptedProvider([copy.deepcopy(self.BLOCK_DRAFT)]), ask=Person().ask,
                           say=Person().say, private=None, strict=True)  # fmt: skip
        self.assertEqual(outcome.status, "draft")
        assert outcome.confirmed is not None
        self.assertEqual(
            (outcome.confirmed.by, outcome.confirmed.strict), ("draft", True)
        )

    def test_an_assumption_stops_it_too(self) -> None:
        # Nobody confirms an automatic run, so what the writer chose is for a person.
        d = copy.deepcopy(self.BLOCK_DRAFT)
        d["items"][0]["height"] = {
            "value": 20,
            "unit": "mm",
            "from": {"assumed": "as tall as it is wide"},
        }
        brief = self.BLOCK.replace(" and 20 mm tall", "")
        outcome = run_spec(brief, ScriptedProvider([d]), ask=Person().ask, say=Person().say, private=None,
                           strict=True)  # fmt: skip
        self.assertEqual((outcome.status, outcome.confirmed), ("questions", None))
        self.assertIn("assumption(s) an automatic run can't settle", outcome.message)

    def test_it_stops_with_the_questions_it_can_t_answer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person().ask, say=Person().say,
                               private=None, strict=True, out=Path(folder))  # fmt: skip
            self.assertEqual(outcome.status, "questions")
            self.assertTrue((Path(folder) / "round-1" / "questions.json").exists())


class TwoDrafts(unittest.TestCase):
    """The brief drafted twice, on its own each time: where they differ, the person is asked."""

    def test_where_they_differ_the_person_settles_it(self) -> None:
        other = example()
        other["items"][1]["diameter"] = {
            "value": 6,
            "unit": "mm",
            "from": {"assumed": "an M5 clearance"},
        }
        person = Person(
            "1", "5", "", "", ""
        )  # the diameter first: it is 5 mm; then keep three assumptions
        provider = ScriptedProvider([example(), other])
        outcome = run_spec(EXAMPLE_BRIEF, provider, ask=person.ask, say=person.say, private=Window("ABC234"),
                           code=lambda: CODE, two_drafts="always")  # fmt: skip
        self.assertEqual((outcome.status, len(provider.requests)), ("confirmed", 2))
        self.assertIn("the second draft reads this otherwise: holes is \u00d85 mm here, \u00d86 mm in the second draft",
                      person.said())  # fmt: skip
        assert outcome.confirmed is not None
        self.assertIn(
            "Answer about holes diameter: 5 mm.", outcome.confirmed.brief.text
        )

    def test_it_may_be_kept_as_drafted(self) -> None:
        other = example()
        other["items"][1]["depth"] = {
            "value": 3,
            "unit": "mm",
            "from": {"assumed": "blind"},
        }
        person = Person(
            "3", "", "", ""
        )  # the depth first: right as drafted (its third option)
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example(), other]), ask=person.ask, say=person.say,
                           private=Window("ABC234"), code=lambda: CODE, two_drafts="always")  # fmt: skip
        self.assertEqual(outcome.status, "confirmed", person.said()[-500:])
        assert outcome.confirmed is not None
        self.assertEqual(outcome.confirmed.brief.text, EXAMPLE_BRIEF)  # nothing added

    def test_two_that_agree_add_nothing(self) -> None:
        turned = example()  # the same plate, turned: length along y
        turned["items"][0]["length"], turned["items"][0]["width"] = (
            turned["items"][0]["width"],
            turned["items"][0]["length"],
        )
        turned["items"][1]["place"]["pattern"]["row"]["axis"]["choose"] = "y"
        person = Person("", "", "")
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example(), turned]), ask=person.ask, say=person.say,
                           private=Window("ABC234"), code=lambda: CODE, two_drafts="always")  # fmt: skip
        self.assertEqual(outcome.status, "confirmed")
        self.assertIn("The two drafts build the same part.", person.said())

    def test_drafted_at_once_by_a_provider_of_its_own_under_one_budget(self) -> None:
        first, other = ScriptedProvider([example()]), ScriptedProvider([example()])
        share_budget(first, other)
        outcome = run_spec(EXAMPLE_BRIEF, first, ask=Person("", "", "").ask, say=Person().say,
                           private=Window("ABC234"), code=lambda: CODE, two_drafts="always", second=other)  # fmt: skip
        self.assertEqual(outcome.status, "confirmed")
        self.assertEqual((len(first.requests), len(other.requests)), (1, 1))
        self.assertIn(
            "listed last sentence first", other.requests[0].messages[0].content
        )
        self.assertIs(first.budget, other.budget)
        self.assertEqual(first.budget.calls, 2)

    def test_by_default_when_the_first_draft_assumed_something(self) -> None:
        provider = ScriptedProvider([example(), example()])
        run_spec_as_is(EXAMPLE_BRIEF, provider, ask=Person("", "", "").ask, say=Person().say,
                       private=Window("ABC234"), code=lambda: CODE)  # fmt: skip
        self.assertEqual(len(provider.requests), 2)
        block = ScriptedProvider([copy.deepcopy(AnAutomaticRunAsksNothing.BLOCK_DRAFT)])
        run_spec_as_is(AnAutomaticRunAsksNothing.BLOCK, block, ask=Person().ask, say=Person().say,
                       private=Window("ABC234"), code=lambda: CODE)  # fmt: skip
        self.assertEqual(
            len(block.requests), 1
        )  # nothing assumed, a short brief: one draft

    def test_an_automatic_run_stops_on_a_difference(self) -> None:
        block = copy.deepcopy(AnAutomaticRunAsksNothing.BLOCK_DRAFT)
        alone = run_spec_as_is(AnAutomaticRunAsksNothing.BLOCK, ScriptedProvider([block, copy.deepcopy(block)]),
                               ask=Person().ask, say=Person().say, private=None, strict=True)  # fmt: skip
        self.assertEqual(
            alone.status, "draft"
        )  # drafted twice, the same: locked as a draft
        taller = copy.deepcopy(block)
        taller["items"][0]["height"] = {
            "value": 25,
            "unit": "mm",
            "from": {"assumed": "a misread"},
        }
        with tempfile.TemporaryDirectory() as folder:
            outcome = run_spec_as_is(AnAutomaticRunAsksNothing.BLOCK, ScriptedProvider([block, taller]),
                                     ask=Person().ask, say=Person().say, private=None, strict=True, out=Path(folder))  # fmt: skip
            self.assertEqual(outcome.status, "questions")
            asked = json.loads(
                (Path(folder) / "round-1" / "questions.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(
                asked[0]["text"].startswith(
                    "the second draft reads this otherwise: block is"
                ),
                asked,
            )


class TheWriterThatCantClearItsFaults(unittest.TestCase):
    def test_is_refused(self) -> None:
        bad = example()
        bad["items"][1]["diameter"]["value"] = 5.5
        outcome = run_spec(
            EXAMPLE_BRIEF,
            ScriptedProvider([bad, copy.deepcopy(bad)]),
            ask=Person().ask,
            say=Person().say,
            private=None,
        )
        self.assertEqual(outcome.status, "refused")
        self.assertIn("/items/1/diameter", outcome.message)


class ThePage(unittest.TestCase):
    def test_the_brief_coloured_by_the_spec(self) -> None:
        b = number_words(EXAMPLE_BRIEF)
        draft = example()
        row = draft["items"][1]["place"]["pattern"]["row"]
        row["pitch"] = {
            "value": 60,
            "unit": "mm",
            "from": {"assumed": "for the test"},
        }  # the 60 is then unused
        page = spec_page(check_draft(b, draft), b, status="round 1")
        self.assertIn(
            '<span class="w" style="--c: #2e7dd7" title="fed plate">80</span>', page
        )
        self.assertIn(
            '<span class="unused" title="nothing in the spec uses it">60</span>', page
        )
        self.assertIn(
            '<span class="w" style="--c: #8a8f98" title="fed the material">PETG</span>',
            page,
        )
        self.assertIn("<li>Material: &#x27;PETG&#x27;</li>", page)
        self.assertIn("This page can't confirm anything.", page)

    def test_assumptions_already_kept_are_listed_while_others_are_settled(self) -> None:
        b = number_words(EXAMPLE_BRIEF)
        report = check_draft(b, example())
        axis = [q for q in questions(report) if q.at.endswith("/axis")]
        page = spec_page(report, b, status="round 2", round_=axis)
        kept = page[page.index("<h2>Kept by you</h2>") :]
        self.assertIn("holes.place.x: centred", kept[: kept.index("</ul>")])
        self.assertNotIn("row.axis", kept[: kept.index("</ul>")])

    def test_what_the_model_or_the_brief_wrote_is_escaped(self) -> None:
        b = number_words("A plate <script>alert(1)</script> 60 mm long.")
        draft = {"spec_format": 1, "name": "<b>plate</b>", "items": [
            {"id": "plate", "kind": "block", "words": [1], "length": {"value": 60, "unit": "mm", "from": {"words": [5, 6]}},
             "width": {"value": 60, "unit": "mm", "from": {"assumed": "<i>square</i>"}},
             "height": {"value": 5, "unit": "mm", "from": {"assumed": "a plate"}}}]}  # fmt: skip
        page = spec_page(check_draft(b, draft), b, status="round 1")
        self.assertNotIn("<script>", page)
        self.assertNotIn("<b>plate</b>", page)
        self.assertNotIn("<i>square</i>", page)

    def test_written_each_round_and_never_showing_the_code(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person("", "", "").ask,
                     say=Person().say, private=Window("ABC234"), out=out, code=lambda: CODE)  # fmt: skip
            page = (out / "spec.html").read_text(encoding="utf-8")
            self.assertIn("Confirmed by you.", page)
            self.assertNotIn("ABC", page.replace("ABC234", ""))
            self.assertNotIn(CODE, page)


class ForgesOwnWindow(unittest.TestCase):
    def test_reads_and_writes_the_terminal_it_was_given(self) -> None:
        shown, typed = io.StringIO(), io.StringIO("ABC-234\n")
        terminal = ControllingTerminal(typed, shown)
        terminal.show("the code is ABC-234")
        self.assertEqual(terminal.read("code> "), "ABC-234")
        self.assertEqual(shown.getvalue(), "the code is ABC-234\ncode> ")
        with self.assertRaises(EOFError):
            terminal.read("code> ")


class TheCommand(unittest.TestCase):
    def test_forge_spec_is_wired(self) -> None:
        args = build_parser().parse_args(
            ["spec", "A plate.", "--auto", "--provider", "fixture", "--fixtures", "f"]
        )
        self.assertEqual(
            (args.handler.__name__, args.auto, args.brief),
            ("command_spec", True, "A plate."),
        )


if __name__ == "__main__":
    unittest.main()
