"""V2 stage 1: the spec writer role (forge_roles.spec_writer), offline.

The model is scripted (forge_models.ScriptedProvider): these tests pin the
control flow, not a model's skill. What they hold:

- the writer is given the guide, the tool schema and the numbered brief;
- a fault goes back to the writer, with its draft kept in the conversation;
- a question or a CAN'T does not: it is the person's, and comes out in the
  report;
- a writer that can't clear its faults stops, with every refused draft kept;
- the second, independent reader has the same guide and reads the brief the
  other way round.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from forge_models import ScriptedProvider
from forge_roles.base import RepairExhaustedError
from forge_roles.spec_writer import SpecWriter, as_drafted, read_answer, write_spec
from forge_spec import number_words
from forge_spec.guide import EXAMPLE_BRIEF, EXAMPLE_DRAFT, draft_schema, instructions


def good() -> dict[str, Any]:
    return copy.deepcopy(dict(EXAMPLE_DRAFT))


def misquoted() -> dict[str, Any]:
    draft = good()
    draft["items"][1]["diameter"]["value"] = 5.5  # the brief says 5 mm
    return draft


class TheWriterIsToldEverything(unittest.TestCase):
    def test_the_guide_the_schema_and_the_numbered_brief(self) -> None:
        provider = ScriptedProvider([good()])
        result = write_spec(provider, EXAMPLE_BRIEF)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.value.problems, ())
        request = provider.requests[0]
        self.assertEqual(request.system, instructions())
        self.assertEqual(dict(request.schema or {}), draft_schema())
        self.assertEqual(request.schema_name, "spec_writer")
        self.assertIn(
            number_words(EXAMPLE_BRIEF).for_the_model(), request.messages[0].content
        )


class TheSecondReaderReadsTheOtherWay(unittest.TestCase):
    def test_the_same_guide_the_brief_last_sentence_first(self) -> None:
        provider = ScriptedProvider([good()])
        result = write_spec(provider, EXAMPLE_BRIEF, second=True)
        self.assertEqual(result.value.problems, ())
        request = provider.requests[0]
        self.assertEqual(request.system, instructions())  # one guide, cached for both
        lines = number_words(EXAMPLE_BRIEF).for_the_model().split("\n")
        self.assertIn("\n".join(reversed(lines)), request.messages[0].content)
        self.assertIn("listed last sentence first", request.messages[0].content)
        self.assertEqual(result.prompt_version, SpecWriter(second=True).prompt_version)
        versions = {
            SpecWriter(strict=a, second=b).prompt_version
            for a in (False, True)
            for b in (False, True)
        }
        self.assertEqual(len(versions), 4)


class AFaultGoesBackToTheWriter(unittest.TestCase):
    def test_its_draft_and_what_is_wrong_with_it(self) -> None:
        provider = ScriptedProvider([misquoted(), good()])
        result = write_spec(provider, EXAMPLE_BRIEF)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.value.problems, ())
        retry = provider.requests[1].messages
        # Its own draft, kept in the conversation, then what is wrong with it.
        self.assertEqual(json.loads(retry[1].content), misquoted())
        self.assertIn("/items/1/diameter: ", retry[2].content)
        self.assertEqual(len(result.problems_seen), 1)

    def test_one_that_can_t_be_cleared_stops_with_every_draft_kept(self) -> None:
        provider = ScriptedProvider(
            [misquoted(), misquoted(), misquoted(), misquoted()]
        )
        with self.assertRaises(RepairExhaustedError) as caught:
            write_spec(provider, EXAMPLE_BRIEF)
        # The same faults twice: a third try would tell nothing new.
        self.assertEqual(len(provider.requests), 2)
        detail = caught.exception.detail
        self.assertEqual(detail["rejected_answer"], misquoted())
        self.assertTrue(any("/items/1/diameter" in p for p in detail["last_problems"]))


class AQuestionIsThePersons(unittest.TestCase):
    def test_it_comes_out_in_the_report_without_a_redraft(self) -> None:
        draft = good()
        draft["silent"] = []  # the last sentence is then unaccounted for: a question
        provider = ScriptedProvider([draft])
        result = write_spec(provider, EXAMPLE_BRIEF)
        self.assertEqual(result.attempts, 1)
        self.assertEqual([p.kind for p in result.value.problems], ["question"])

    def test_an_automatic_run_is_checked_strictly(self) -> None:
        result = write_spec(ScriptedProvider([good()]), EXAMPLE_BRIEF, strict=True)
        self.assertTrue(result.value.strict)
        # In --auto, a sentence taken as silent is asked about.
        self.assertTrue(result.value.problems)
        self.assertEqual(SpecWriter(strict=True).strict, True)


class WhatTheTransportHandsOverIsReadAsWritten(unittest.TestCase):
    """Each observed live on blind set 1, where all 30 drafts gave up: the
    same content in another form, read as the writer wrote it."""

    def test_the_version_as_a_number(self) -> None:
        answer = good()
        answer["schema_version"] = 1.9
        result = write_spec(ScriptedProvider([answer]), EXAMPLE_BRIEF)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.value.problems, ())

    def test_a_number_the_schema_names_no_text_for_is_still_a_fault(self) -> None:
        answer = good()
        answer["schema_version"] = 1.8  # the schema asks for "1.9"
        with self.assertRaises(RepairExhaustedError) as caught:
            write_spec(ScriptedProvider([answer, answer]), EXAMPLE_BRIEF)
        said = " ".join(caught.exception.detail["last_problems"])
        self.assertIn('written as text, in quotes: "1.9", not the number 1.8', said)

    def test_a_figure_is_matched_to_the_text_the_schema_names(self) -> None:
        schema = {"properties": {"schema_version": {"const": "1.10"}, "items": {}}}
        self.assertEqual(as_drafted({"schema_version": 1.1, "items": []}, schema)["schema_version"], "1.10")
        self.assertIs(as_drafted({"schema_version": True, "items": []}, schema)["schema_version"], True)
        enum = {"properties": {"schema_version": {"enum": ["1.1", "1.10"]}}}
        self.assertEqual(as_drafted({"schema_version": 1.1}, enum)["schema_version"], 1.1)  # either: left as given

    def test_the_whole_draft_under_a_wrapper(self) -> None:
        result = write_spec(ScriptedProvider([{"spec": good()}]), EXAMPLE_BRIEF)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.value.problems, ())
        as_text = write_spec(ScriptedProvider([{"spec": json.dumps(good())}]), EXAMPLE_BRIEF)
        self.assertEqual(as_text.value.problems, ())

    def test_a_wrapper_named_as_the_schema_s_own_field_is_left_alone(self) -> None:
        wrapped = {"items": good()}
        self.assertEqual(as_drafted(wrapped)["items"], [good()])  # read as one item, not unwrapped

    def test_items_as_json_text(self) -> None:
        whole = good()
        whole["items"] = json.dumps(good()["items"])
        inside = good()
        inside["items"] = [json.dumps(good()["items"])]
        each = good()
        each["items"] = [json.dumps(item) for item in good()["items"]]
        for answer in (whole, inside, each):
            result = write_spec(ScriptedProvider([answer]), EXAMPLE_BRIEF)
            self.assertEqual((result.attempts, result.value.problems), (1, ()))

    def test_a_replayed_record_is_read_as_the_live_writer_read_it(self) -> None:
        answer = {"spec": good()}
        answer["spec"]["schema_version"] = 1.9
        self.assertEqual(read_answer(answer), good())


if __name__ == "__main__":
    unittest.main()
