"""V2, schema 1.10: what the brief asks that no kind makes yet, said instead of a stand-in (docs/V2-stage4.md, 14.6).

Blind set 1's gear was drafted as a plain disc, its teeth "not modelled":
the person would have confirmed a disc. A writer now lists such a shape in
``unable``; Forge says it can't make the part yet. Also here: an angle
measured from a face, as a formula on a right angle (the same set's
leaning backrest), and a writer's reason read up to 300 characters.
"""

from __future__ import annotations

import unittest
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.draft import read_draft
from forge_spec.render import render
from forge_spec.wire import to_wire
from v2_drafts import assumed, cite, draft, mm

GEAR = "A spur gear with 24 teeth, module 1, 6 mm thick, with a 5 mm bore."


def gear(*, unable: bool = True, version: str = "1.10") -> dict[str, Any]:
    b = number_words(GEAR)
    d = draft("gear", [
        {"id": "hub", "kind": "cylinder", "words": cite(b, "gear"), "length": mm(b, 6, "6 mm thick"),
         "diameter": assumed("the blank under the teeth", 22)},
        {"id": "bore", "kind": "hole", "words": cite(b, "5 mm bore"), "on": {"item": "hub", "face": "+end"},
         "diameter": mm(b, 5, "5 mm"), "depth": {"through": True, "from": {"assumed": "a bore goes through"}}},
    ])  # fmt: skip
    d["schema_version"] = version
    if unable:
        d["unable"] = [{"words": cite(b, "spur gear with 24 teeth") + cite(b, "module 1"), "what": "involute spur gear teeth"}]
    return d


class WhatNoKindMakes(unittest.TestCase):
    def test_it_ends_the_draft_as_unable_with_its_words_accounted_for(self) -> None:
        b = number_words(GEAR)
        report = check_draft(b, gear())
        kinds = [(p.kind, p.at) for p in report.problems]
        self.assertIn(("unable", "/unable/0"), kinds)
        self.assertFalse([p for p in report.problems if p.kind in ("fault", "question")], report.problems)
        said = next(p.message for p in report.problems if p.kind == "unable")
        self.assertEqual(said, "Forge can't make involute spur gear teeth yet (the brief's 'spur gear with 24 "
                               "teeth module 1')")  # fmt: skip

    def test_without_it_the_numbers_are_unused(self) -> None:
        report = check_draft(number_words(GEAR), gear(unable=False))
        self.assertTrue(any(p.kind == "question" and "'24'" in p.message for p in report.problems))

    def test_it_is_schema_1_10_s(self) -> None:
        _, problems = read_draft(gear(version="1.9"))
        self.assertIn(("/unable/0", 'an "unable" entry is schema 1.10\'s: give the draft\'s "schema_version": '
                                    '"1.10"'), [(p.at, p.message) for p in problems.faults])  # fmt: skip

    def test_it_needs_its_words_and_what_it_is(self) -> None:
        for entry in ({"words": [1]}, {"what": "teeth"}, {"words": [], "what": "teeth"}, {"words": [1], "what": ""},
                      {"words": [1], "what": "x" * 81}):  # fmt: skip
            d = gear()
            d["unable"] = [entry]
            _, problems = read_draft(d)
            self.assertTrue(any(p.at.startswith("/unable/0") for p in problems.faults), entry)

    def test_the_person_reads_it_first_and_the_wire_keeps_it(self) -> None:
        b = number_words(GEAR)
        report = check_draft(b, gear())
        text = render(report, b).text()
        self.assertTrue(text.split("\n")[2].startswith("Forge can't make yet:"), text)
        self.assertIn("involute spur gear teeth: 'spur gear with 24 teeth module 1'", text)
        assert report.spec is not None
        wire = to_wire(report.spec)
        self.assertEqual(wire["unable"], gear()["unable"])
        again, _ = read_draft(wire)
        self.assertEqual(again, report.spec)
        plain = check_draft(b, gear(unable=False)).spec
        assert plain is not None
        self.assertNotIn("unable", to_wire(plain))  # a spec with none writes and hashes as before


BACKREST = "A stand: a base 80 x 70 x 5 mm, and a back 80 mm wide, 5 mm thick and 90 mm long that leans back at " \
           "65 degrees from the base."


class AnAngleFromAFace(unittest.TestCase):
    def test_a_tilt_is_a_right_angle_less_it(self) -> None:
        b = number_words(BACKREST)

        def back(tilt: dict[str, Any]) -> dict[str, Any]:
            return draft("stand", [
                {"id": "base", "kind": "block", "words": cite(b, "base"), "length": mm(b, 80, "80", 1),
                 "width": mm(b, 70, "70"), "height": mm(b, 5, "5 mm", 1)},
                {"id": "back", "kind": "block", "words": cite(b, "back"), "on": {"item": "base", "face": "+z"},
                 "length": mm(b, 80, "80 mm wide"), "width": mm(b, 5, "5 mm thick"),
                 "height": mm(b, 90, "90 mm long"), "tilt": tilt,
                 "tilt_towards": {"choose": "+y", "from": {"assumed": "back is +y"}}},
            ])  # fmt: skip

        right = {"value": 25, "unit": "deg", "from": {"formula": "90 deg - 65 deg",
                                                      "words": cite(b, "65 degrees from the base")}}
        report = check_draft(b, back(right))
        self.assertFalse([p for p in report.problems if p.kind == "fault"], report.problems)
        self.assertFalse([p for p in report.problems if "'65'" in p.message], report.problems)
        wrong = {"value": 25, "unit": "deg", "from": {"formula": "90 deg - 60 deg",
                                                      "words": cite(b, "65 degrees from the base")}}
        self.assertTrue(any(p.kind == "fault" for p in check_draft(b, back(wrong)).problems))


class AReasonALittleLong(unittest.TestCase):
    def test_read_to_300_characters(self) -> None:
        b = number_words(GEAR)
        for length, refused in ((250, False), (301, True)):
            d = gear()
            d["items"][0]["diameter"]["from"]["assumed"] = "y" * length
            faults = [p.at for p in check_draft(b, d).problems if p.kind == "fault"]
            self.assertEqual("/items/0/diameter/from/assumed" in faults, refused, length)


if __name__ == "__main__":
    unittest.main()
