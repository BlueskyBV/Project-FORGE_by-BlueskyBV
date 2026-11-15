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
from forge_roles.spec_writer import SpecWriter, write_spec
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


if __name__ == "__main__":
    unittest.main()
