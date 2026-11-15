"""V2 stage 1: the spec writer's guide and the JSON Schema it answers with (forge_spec.guide).

Both are generated from the one declaration of the format (rule R8). The
tests pin what that buys:

- every draft the reader takes, the schema takes: the schema may refuse
  less than the reader, never more, or a correct answer could be impossible
  to give;
- the schema refuses the commonest malformed answers, so a first answer is
  more likely to read;
- the instructions name every kind, field, face, pattern and edge the
  format has, so nothing can be added to the format and left out of them;
- the worked example the writer is shown passes the checks with no problem.
"""

from __future__ import annotations

import copy
import json
import random
import sys
import unittest
from pathlib import Path
from typing import Any

import jsonschema
from forge_roles.base import RoleOutputError
from forge_roles.spec_writer import SpecWriter
from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.draft import PATTERN_FIELDS, read_draft
from forge_spec.guide import (
    EXAMPLE_BRIEF,
    EXAMPLE_DRAFT,
    brief_message,
    draft_schema,
    instructions,
)
from forge_spec.schema import KINDS

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_spec_partspec import bracket_draft, flange_draft, plate_draft
from v2_gen import random_draft

VALIDATOR = jsonschema.Draft202012Validator(draft_schema())


def schema_errors(draft: Any) -> list[str]:
    return [error.message for error in VALIDATOR.iter_errors(draft)]


class EveryDraftTheReaderTakesTheSchemaTakes(unittest.TestCase):
    def test_the_schema_is_a_valid_schema(self) -> None:
        jsonschema.Draft202012Validator.check_schema(draft_schema())

    def test_random_drafts_of_every_shape(self) -> None:
        read = 0
        for seed in range(400):
            draft = random_draft(random.Random(seed))
            spec, problems = read_draft(draft)
            if spec is None or problems.faults:
                continue
            read += 1
            self.assertEqual(schema_errors(draft), [], (seed, json.dumps(draft)[:400]))
        self.assertGreater(read, 250)

    def test_the_corpus_drafts(self) -> None:
        for make in (plate_draft, flange_draft, bracket_draft):
            self.assertEqual(schema_errors(make()[1]), [], make.__name__)

    def test_the_example(self) -> None:
        self.assertEqual(schema_errors(EXAMPLE_DRAFT), [])


class TheSchemaRefusesTheCommonestMistakes(unittest.TestCase):
    def broken(self, change: Any) -> list[str]:
        draft = copy.deepcopy(dict(EXAMPLE_DRAFT))
        change(draft)
        self.assertTrue(
            read_draft(draft)[1].faults, "the reader takes it: the schema must too"
        )
        return schema_errors(draft)

    def test_a_field_the_kind_doesn_t_have(self) -> None:
        self.assertTrue(
            self.broken(lambda d: d["items"][0].update(radius=d["items"][0]["width"]))
        )

    def test_a_value_with_no_unit_or_source(self) -> None:
        self.assertTrue(self.broken(lambda d: d["items"][0]["length"].pop("unit")))
        self.assertTrue(self.broken(lambda d: d["items"][0]["length"].pop("from")))

    def test_a_length_in_degrees(self) -> None:
        self.assertTrue(
            self.broken(lambda d: d["items"][0]["length"].update(unit="deg"))
        )

    def test_a_count_with_a_unit(self) -> None:
        self.assertTrue(self.broken(lambda d: d["items"][1]["count"].update(unit="mm")))

    def test_an_unknown_kind_or_choice(self) -> None:
        self.assertTrue(self.broken(lambda d: d["items"][2].update(kind="round")))

        def row(d: dict[str, Any]) -> dict[str, Any]:
            found: dict[str, Any] = d["items"][1]["place"]["pattern"]["row"]
            return found

        self.assertTrue(self.broken(lambda d: row(d)["axis"].update(choose="w")))

    def test_a_citation_that_isn_t_word_numbers(self) -> None:
        self.assertTrue(
            self.broken(
                lambda d: d["items"][0]["length"]["from"].update(words=["80 mm"])
            )
        )


class TheInstructionsNameEverything(unittest.TestCase):
    text = instructions()

    def test_every_kind_and_field(self) -> None:
        for kind, spec in KINDS.items():
            self.assertIn(f"### {kind} (", self.text)
            for field in spec.fields:
                self.assertIn(f"- {field.name} (", self.text, (kind, field.name))

    def test_every_face_pattern_and_edge(self) -> None:
        for spec in KINDS.values():
            for face in spec.faces:
                self.assertIn(face, self.text)
            for edge in spec.edges:
                self.assertIn(f"- {edge}: ", self.text)
        for pattern in PATTERN_FIELDS:
            self.assertIn(f"- {pattern}: ", self.text)

    def test_they_are_the_same_every_time(self) -> None:
        self.assertEqual(instructions(), self.text)
        self.assertEqual(
            json.dumps(draft_schema(), sort_keys=True),
            json.dumps(draft_schema(), sort_keys=True),
        )

    def test_they_show_the_brief_numbered(self) -> None:
        message = brief_message(number_words("A plate. Two holes."))
        self.assertIn("S0: [0]A [1]plate\nS1: [2]Two [3]holes", message)
        self.assertIn("words 0 to 3, sentences 0 to 1", message)


class TheExampleIsRight(unittest.TestCase):
    def test_it_passes_the_checks_with_no_problem(self) -> None:
        report = check_draft(number_words(EXAMPLE_BRIEF), dict(EXAMPLE_DRAFT))
        self.assertEqual([(p.kind, p.message) for p in report.problems], [])
        self.assertEqual(report.notes, ())

    def test_it_is_in_the_instructions_as_the_writer_sees_it(self) -> None:
        self.assertIn(number_words(EXAMPLE_BRIEF).for_the_model(), instructions())
        self.assertIn(json.dumps(EXAMPLE_DRAFT, ensure_ascii=False), instructions())


class ARedraftSaysWhatToFix(unittest.TestCase):
    """What goes back to the writer is the role's repair: its faults, each where it is, and its notes."""

    def problems(self, d: dict[str, Any]) -> tuple[str, ...]:
        b = number_words(plate_draft()[0].text)
        with self.assertRaises(RoleOutputError) as caught:
            SpecWriter().parse(d, brief=b)
        return caught.exception.problems

    def test_faults_with_their_place_and_nothing_for_the_person(self) -> None:
        _, d = plate_draft()
        d["items"][1]["diameter"]["value"] = 4.5  # a misquote: the writer's to fix
        d["silent"] = []  # an unaccounted sentence: the person's question
        problems = "\n".join(self.problems(d))
        self.assertIn("/items/1/diameter: ", problems)
        self.assertNotIn("nothing in the spec comes from", problems)

    def test_notes_are_passed_on(self) -> None:
        _, d = plate_draft()
        d["items"][0]["length"]["from"]["words"].reverse()
        d["items"][1]["diameter"]["value"] = 4.5
        self.assertIn("word numbers read as", "\n".join(self.problems(d)))


class AnAutomaticRunsWriterIsToldItsRules(unittest.TestCase):
    def test_the_stricter_rules_are_in_its_prompt_and_its_version(self) -> None:
        auto = SpecWriter(strict=True)
        self.assertIn("## No person will confirm this spec", auto.system_prompt())
        self.assertNotIn(
            "## No person will confirm this spec", SpecWriter().system_prompt()
        )
        self.assertTrue(auto.prompt_version.endswith("-auto"))
        self.assertNotEqual(auto.prompt_version, SpecWriter().prompt_version)
        strict = instructions(strict=True)
        qualify = strict[strict.index("Words such as these qualify:") :].split(";")[0]
        self.assertIn("anodised", qualify)  # what can't be a shape may be left out...
        self.assertNotIn(
            "petg", qualify
        )  # ...but never the part's material, which the checks fault there
        self.assertIn(
            "another thing's material (the part's own is requirements.material)", strict
        )


if __name__ == "__main__":
    unittest.main()
