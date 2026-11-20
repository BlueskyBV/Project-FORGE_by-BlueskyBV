"""V2 stage 1: what the part must be beyond its shape: its material (forge_spec.draft.Requirements).

Plan, section 4.1: the PartSpec records the part's requirements, starting
with the material, for the strength and print checks to come. The tests pin:

- the material is the brief's words for it, exactly, grade and all, or an
  assumption the person sees first; its words are accounted for by it;
- it is never left out as "not modelled": that is a fault, so the writer
  records it;
- it is shown in the fixed wording, written, read and hashed with the spec,
  and a spec that has none reads and hashes as it always did;
- a second draft that names another material differs.

Briefs written for these tests.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.compare import differences
from forge_spec.draft import read_draft
from forge_spec.lock import lock, spec_digest
from forge_spec.questions import Answer, AnswerError, apply_answers, questions
from forge_spec.render import render
from forge_spec.wire import to_wire

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import cite, draft, made_of, mm, said

BRIEF = "An aluminium 6061 plate 60 mm long, 40 mm wide and 5 mm thick."
B = number_words(BRIEF)


def plate(**options: Any) -> dict[str, Any]:
    return draft("plate", [{"id": "plate", "kind": "block", "words": cite(B, "plate"),
                            "length": mm(B, 60, "60 mm long"), "width": mm(B, 40, "40 mm wide"),
                            "height": mm(B, 5, "5 mm thick")}], **options)  # fmt: skip


class TheMaterialIsTheBriefsWordsForIt(unittest.TestCase):
    def test_grade_and_all_its_number_accounted_for(self) -> None:
        for strict in (False, True):
            report = check_draft(
                B, plate(material=made_of(B, "aluminium 6061")), strict=strict
            )
            self.assertEqual(report.problems, (), strict)
        self.assertIn("Material: 'aluminium 6061'", render(report, B).text())

    def test_or_assumed_with_its_reason(self) -> None:
        b = number_words("A plate 60 mm long, 40 mm wide and 5 mm thick.")
        d = draft("plate", [{"id": "plate", "kind": "block", "words": cite(b, "plate"),
                             "length": mm(b, 60, "60 mm"), "width": mm(b, 40, "40 mm"),
                             "height": mm(b, 5, "5 mm")}],
                  material={"text": "PLA", "from": {"assumed": "the usual for a print"}})  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual([a.at for a in report.assumptions], ["/requirements/material"])
        self.assertIn("Material: 'PLA' (assumed)", render(report, b).text())

    def test_not_what_the_words_say(self) -> None:
        wrong = {"text": "aluminium 7075", "from": said(B, "aluminium 6061")}
        self.assertIn(("fault", "/requirements/material"),
                      [(p.kind, p.at) for p in check_draft(B, plate(material=wrong)).problems])  # fmt: skip


class AnAssumedMaterialIsThePersonsToName(unittest.TestCase):
    def test_named_in_their_words_and_cited(self) -> None:
        b = number_words("A plate 60 mm long, 40 mm wide and 5 mm thick.")
        d = draft("plate", [{"id": "plate", "kind": "block", "words": cite(b, "plate"),
                             "length": mm(b, 60, "60 mm"), "width": mm(b, 40, "40 mm"),
                             "height": mm(b, 5, "5 mm")}],
                  material={"text": "PLA", "from": {"assumed": "the usual for a print"}})  # fmt: skip
        round_ = questions(check_draft(b, d))
        (asked,) = [q for q in round_ if q.at == "/requirements/material"]
        self.assertEqual([o.kind for o in asked.options], ["text", "note"])
        answered = apply_answers(
            b, d, round_, [Answer(asked.id, 0, text="aluminium 6061")]
        )
        self.assertTrue(
            answered.brief.text.endswith("Answer about the material: aluminium 6061.")
        )
        report = check_draft(answered.brief, answered.draft)
        self.assertEqual(report.problems, ())
        self.assertIn(
            "Material: 'aluminium 6061'\n", render(report, answered.brief).text()
        )
        with self.assertRaises(AnswerError):
            apply_answers(b, d, round_, [Answer(asked.id, 0, text="  ")])


class ItIsNeverLeftOut(unittest.TestCase):
    def test_as_not_modelled(self) -> None:
        d = plate(
            not_modelled=[
                {"words": cite(B, "aluminium 6061"), "reason": "the material"}
            ]
        )
        (fault,) = [p for p in check_draft(B, d).problems if p.kind == "fault"]
        self.assertEqual((fault.at, fault.message), ("/not_modelled/0/words",
                         "'aluminium' names a material: give the part's as requirements.material, citing its words; "
                         "another thing's may be left out here once the part has one of its own"))  # fmt: skip

    def test_nor_given_twice(self) -> None:
        d = plate(material=made_of(B, "aluminium 6061"),
                  not_modelled=[{"words": cite(B, "aluminium"), "reason": "the material"}])  # fmt: skip
        faults = [p.message for p in check_draft(B, d).problems if p.kind == "fault"]
        self.assertEqual(faults, ["'aluminium' is the material: it is requirements.material already, "
                                  "so leave it out here"])  # fmt: skip


class LetteringIsNoMaterial(unittest.TestCase):
    def test_letters_that_spell_one(self) -> None:
        # Lettering reading "PC" (polycarbonate's name too) is the lettering's, not a material's (generated part 1528).
        b = number_words("An aluminium 6061 plate 60 mm long, 40 mm wide and 5 mm thick, engraved with the letters "
                         "PC 5 mm tall and 0.5 mm deep in the middle of its top.")  # fmt: skip
        d = draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm long"),
             "width": mm(b, 40, "40 mm wide"), "height": mm(b, 5, "5 mm thick")},
            {"id": "letters", "kind": "text", "words": cite(b, "letters"), "on": {"item": "plate", "face": "+z"},
             "mode": {"choose": "engrave", "from": said(b, "engraved")}, "text": {"text": "PC", "from": said(b, "PC")},
             "height": mm(b, 5, "5 mm tall"), "depth": mm(b, 0.5, "0.5 mm deep"),
             "place": {"x": {"centred": said(b, "in the middle")}, "y": {"centred": said(b, "in the middle")}}},
        ], material=made_of(b, "aluminium 6061"))  # fmt: skip
        self.assertEqual([p.message for p in check_draft(b, d).problems if "names a material" in p.message], [])


class ItTravelsWithTheSpec(unittest.TestCase):
    def test_written_read_and_hashed(self) -> None:
        d = plate(material=made_of(B, "aluminium 6061"))
        report = check_draft(B, d)
        assert report.spec is not None
        wire = to_wire(report.spec)
        self.assertEqual(
            wire["requirements"],
            {"material": {"text": "aluminium 6061", "from": {"words": [1, 2]}}},
        )
        again, problems = read_draft(wire)
        self.assertEqual((again, problems.faults), (report.spec, []))
        other = copy.deepcopy(d)
        other["requirements"]["material"] = {
            "text": "aluminium 6061",
            "from": {"assumed": "for the test"},
        }
        theirs = check_draft(B, other).spec
        assert theirs is not None
        self.assertNotEqual(
            spec_digest(report.spec, B, "person"), spec_digest(theirs, B, "person")
        )
        self.assertEqual(
            lock(report, B, by="person", strict=False).digest,
            spec_digest(report.spec, B, "person"),
        )

    def test_a_spec_without_requirements_writes_as_it_always_did(self) -> None:
        b = number_words("A plate 60 mm long, 40 mm wide and 5 mm thick.")
        d = draft("plate", [{"id": "plate", "kind": "block", "words": cite(b, "plate"),
                             "length": mm(b, 60, "60 mm"), "width": mm(b, 40, "40 mm"),
                             "height": mm(b, 5, "5 mm")}])  # fmt: skip
        report = check_draft(b, d)
        assert report.spec is not None
        self.assertNotIn("requirements", to_wire(report.spec))

    def test_a_second_draft_of_another_material_differs(self) -> None:
        mine = check_draft(B, plate(material=made_of(B, "aluminium 6061")))
        theirs = check_draft(B, plate(material=made_of(B, "aluminium")))
        (found,) = differences(mine, theirs)
        self.assertEqual((found.at, found.message), ("/requirements/material",
                         "the material is 'aluminium 6061' here, 'aluminium' in the second draft"))  # fmt: skip


if __name__ == "__main__":
    unittest.main()
