"""V2 stage 1: the contract's integrity, from the draft to the lock.

What the person confirms must be exactly what is built and checked. So:

- the reader never raises, never coerces silently, and never accepts a field
  that would be ignored;
- the wire form is the exact inverse of the reader, for every shape a draft
  can take (property-tested on random drafts, tests/v2_gen.py);
- the wording the person reads says every field, and two specs that differ
  render differently;
- the lock covers the brief, the spec, who confirmed it and how strictly it
  was checked, and is never taken on trust.

Briefs are from V1's corpus (validation/SUITE.md) or written for one test.
"""

from __future__ import annotations

import copy
import dataclasses
import random
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.draft import read_draft
from forge_spec.items.words import WORDS
from forge_spec.lock import LockError, lock, spec_digest, unlock
from forge_spec.render import _Line, render
from forge_spec.wire import to_wire

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_spec_partspec import R05, plate_draft
from v2_drafts import assumed, choose, cite, draft, made_of, mm
from v2_gen import random_draft

ANY = number_words("A plate of steel. It carries no load.")


def faults(raw: Any) -> list[tuple[str, str]]:
    return [(p.at, p.message) for p in read_draft(raw)[1].faults]


def notes(raw: Any) -> list[str]:
    return [p.message for p in read_draft(raw)[1].notes]


class TheReaderNeverRaisesOrCoerces(unittest.TestCase):
    def setUp(self) -> None:
        self.brief, self.good = plate_draft()

    def test_the_name_is_the_name(self) -> None:
        spec, _ = read_draft(self.good)
        assert spec is not None
        self.assertEqual(spec.name, "mounting plate")

    def test_a_format_must_be_the_format(self) -> None:
        for wrong in (True, 1.0, "1", 2):
            d = dict(self.good, spec_format=wrong)
            self.assertIn("/spec_format", [at for at, _ in faults(d)], wrong)
            d.pop("schema_version", None)
            self.assertIn("/spec_format", [at for at, _ in faults(d)], wrong)
        for wrong in (1.1, "1", "1.1.0", "01.1", "v1.1", "2.0", "1.5", True, None):
            d = dict(self.good, schema_version=wrong)
            self.assertIn("/schema_version", [at for at, _ in faults(d)], wrong)
        d = dict(self.good)
        d.pop("schema_version", None)
        self.assertIn("/schema_version", [at for at, _ in faults(d)])

    def test_text_that_isn_t_valid_unicode(self) -> None:
        d = dict(self.good, name="plate \ud800")
        self.assertIn("/name", [at for at, _ in faults(d)])

    def test_keys_that_aren_t_text(self) -> None:
        d = copy.deepcopy(self.good)
        d["items"][0]["length"][1] = 2
        self.assertTrue(faults(d))

    def test_a_huge_coordinate(self) -> None:
        outline = {"start": [10**400, 0], "segments": [{"line_to": [1, 0]}, {"line_to": [0, 0]}],
                   "from": {"assumed": "t"}}  # fmt: skip
        d = draft("x", [{"id": "e", "kind": "extrusion", "words": [1], "profile": outline,
                         "length": assumed("t", 5)}])  # fmt: skip
        self.assertIn("/items/0/profile/start/0", [at for at, _ in faults(d)])

    def test_an_outline_s_segments_are_each_read_or_faulted(self) -> None:
        def outline(*segments: dict[str, Any]) -> dict[str, Any]:
            return draft("x", [{"id": "e", "kind": "extrusion", "words": [1], "length": assumed("t", 5),
                                "profile": {"start": [0, 0], "segments": list(segments),
                                            "from": {"assumed": "t"}}}])  # fmt: skip

        cases: list[tuple[dict[str, Any], str]] = [
            ({"arc_to": [0, 0], "centre": [5, 0], "clockwise": "yes"}, "/items/0/profile/segments/1/clockwise"),
            ({"line_to": [0, 0], "arc_to": [0, 0]}, "/items/0/profile/segments/1"),
            ({"line_to": [0, 0], "centre": [1, 1]}, "/items/0/profile/segments/1"),
        ]  # fmt: skip
        for second, where in cases:
            self.assertIn(
                where,
                [at for at, _ in faults(outline({"line_to": [10, 0]}, second))],
                second,
            )

    def test_nulls_and_reordered_words_are_noted(self) -> None:
        d = copy.deepcopy(self.good)
        d["items"][1]["counterbore"] = None
        d["items"][0]["words"] = [3, 2]
        self.assertIn("null read as not given", notes(d))
        self.assertIn("word numbers read as [2, 3]", notes(d))

    def test_one_content_one_form(self) -> None:
        d = copy.deepcopy(self.good)
        d["items"][0]["length"]["unit"] = "mm*mm/mm"
        self.assertIn("/items/0/length/unit", [at for at, _ in faults(d)])
        d = copy.deepcopy(self.good)
        d["items"][0]["length"]["tolerance"] = {"plus": 0, "minus": 0}
        self.assertIn("/items/0/length/tolerance", [at for at, _ in faults(d)])

    def test_only_a_size_comes_from_a_table_or_a_formula(self) -> None:
        d = copy.deepcopy(self.good)
        d["items"][1]["depth"] = {
            "through": True,
            "from": {"formula": "made up", "words": [18]},
        }
        self.assertIn("/items/1/depth/from", [at for at, _ in faults(d)])
        d = copy.deepcopy(self.good)
        d["items"][1]["place"]["x"] = {
            "centred": {"table": "no such table", "words": [31]}
        }
        self.assertIn("/items/1/place/x/centred", [at for at, _ in faults(d)])
        d = copy.deepcopy(self.good)
        d["items"][1]["count"] = {
            "count": 4,
            "from": {"table": "clearance:M4", "words": [14]},
        }
        self.assertIn("/items/1/count/from", [at for at, _ in faults(d)])

    def test_a_joint_and_only_a_joint_names_what_it_meets(self) -> None:
        d = copy.deepcopy(self.good)
        d["items"].append({"id": "r", "kind": "fillet", "words": [2], "radius": assumed("t", 1),
                           "edges": {"of": "plate", "which": "top", "where_meets": "holes"}})  # fmt: skip
        self.assertIn("/items/2/edges/where_meets", [at for at, _ in faults(d)])


class CitationsAreCheckedWhereTheySit(unittest.TestCase):
    def test_a_word_that_doesn_t_exist(self) -> None:
        b, d = plate_draft()
        d["items"][1]["depth"]["from"]["words"] = [999]
        d["not_modelled"] = [{"words": [998], "reason": "for the test"}]
        d["requirements"]["material"]["from"]["words"] = [997]
        d["silent"][0]["sentence"] = 9
        report = check_draft(b, d)
        at = {p.at for p in report.problems if p.kind == "fault"}
        self.assertTrue(
            {
                "/items/1/depth/from/words",
                "/not_modelled/0/words",
                "/silent/0/sentence",
                "/requirements/material/from/words",
            }
            <= at,
            at,
        )
        self.assertIsNotNone(report.accounting)  # the rest is still accounted for

    def test_a_choice_that_names_another_option(self) -> None:
        # V1 corpus: a roller "lying on its side with its axis along X".
        b = number_words("A PLA roller 30 mm in diameter and 50 mm long, lying on its side with its axis along X. "
                         "It carries no load, so there is no load case.")  # fmt: skip
        roller = {"id": "roller", "kind": "cylinder", "words": cite(b, "roller"), "diameter": mm(b, 30, "30 mm"),
                  "length": mm(b, 50, "50 mm"), "axis": choose("z", {"words": cite(b, "axis along X")})}  # fmt: skip
        report = check_draft(b, draft("roller", [roller], material=made_of(b, "PLA")))
        self.assertIn(
            "the cited words ('axis along X') say x, not z",
            [p.message for p in report.problems],
        )
        roller["axis"] = choose("x", {"words": cite(b, "axis along X")})
        self.assertNotIn(
            "fault",
            [
                p.kind
                for p in check_draft(
                    b, draft("roller", [roller], material=made_of(b, "PLA"))
                ).problems
            ],
        )

    def test_a_text_is_exactly_its_words(self) -> None:
        b = number_words(
            "A tag 50 mm long with FORGE engraved on it."
        )  # written for this test
        for text, ok in (
            ("FORGE", True),
            ("ORG", False),
            ("forge", False),
            ("FORGE engraved", False),
        ):
            tag = {"id": "t", "kind": "text", "words": cite(b, "engraved"), "on": {"item": "tag", "face": "+z"},
                   "text": {"text": text, "from": {"words": cite(b, "FORGE")}}, "height": assumed("t", 5),
                   "depth": assumed("t", 0.5), "mode": choose("engrave", {"words": cite(b, "engraved")})}  # fmt: skip
            body = {"id": "tag", "kind": "block", "words": cite(b, "tag"), "length": mm(b, 50, "50 mm"),
                    "width": assumed("t", 20), "height": assumed("t", 3)}  # fmt: skip
            messages = [
                p.message
                for p in check_draft(b, draft("tag", [body, tag])).problems
                if p.kind == "fault"
            ]
            self.assertEqual(
                not any("not exactly what the cited words say" in m for m in messages),
                ok,
                text,
            )

    def test_a_tolerance_is_from_the_brief_or_assumed(self) -> None:
        b = number_words(
            "A pin 10 mm across +0.1/-0 and 30 mm long."
        )  # written for this test
        pin: dict[str, Any] = {"id": "pin", "kind": "cylinder", "words": cite(b, "pin"), "length": mm(b, 30, "30 mm"),
               "diameter": {"value": 10, "unit": "mm", "tolerance": {"plus": 0.1, "minus": 0},
                            "from": {"words": cite(b, "10 mm across +0.1/-0")}}}  # fmt: skip
        report = check_draft(b, draft("pin", [pin]))
        self.assertFalse(
            [p for p in report.problems if p.kind == "fault"], report.problems
        )
        pin["diameter"]["tolerance"] = {"plus": 5, "minus": 5}
        messages = [p.message for p in check_draft(b, draft("pin", [pin])).problems]
        self.assertIn("the brief gives +0.1/-0 mm, not +5/-5", messages)


class TheWireIsTheReaderBackwards(unittest.TestCase):
    def test_every_shape_a_draft_can_take(self) -> None:
        for seed in range(1500):
            raw = random_draft(random.Random(seed))
            spec, read = read_draft(raw)
            assert spec is not None and not read.faults, (seed, read.faults)
            again, problems = read_draft(to_wire(spec))
            self.assertEqual(again, spec, seed)
            self.assertFalse(problems.faults, seed)

    def test_an_offset_position(self) -> None:
        _, d = plate_draft()
        d["items"][1]["place"]["x"] = {"offset": assumed("t", 3)}
        spec, _ = read_draft(d)
        assert spec is not None
        self.assertEqual(read_draft(to_wire(spec))[0], spec)


def _leaves(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    found: list[tuple[Any, ...]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("words", "id"):
                continue  # citations are judged by the checks; ids are renamed together
            found += _leaves(value, (*path, key))
    elif isinstance(node, list):
        for k, value in enumerate(node):
            found += _leaves(value, (*path, k))
    elif not isinstance(node, bool):
        found.append(path)
    return found


def _mutate(value: Any, rng: random.Random) -> Any:
    if isinstance(value, (int, float)):
        return value + rng.choice([1, 0.5, 2.25])
    if value in ("mm", "cm", "in"):
        return {"mm": "cm", "cm": "in", "in": "mm"}[value]
    if isinstance(value, str):
        return value + "x"
    return value


class TheWordingSaysEverything(unittest.TestCase):
    def test_every_field_is_worded_by_its_template(self) -> None:
        for seed in range(800):
            spec, _ = read_draft(random_draft(random.Random(seed)))
            assert spec is not None
            for item in spec.items:
                line = _Line(item)
                WORDS[item.kind].sentence(line)
                self.assertEqual(set(item.fields) - line.used, set(), (seed, item.kind))

    def test_two_specs_that_differ_read_differently(self) -> None:
        rng = random.Random(7)
        checked = 0
        for seed in range(400):
            raw = random_draft(random.Random(seed))
            spec, _ = read_draft(raw)
            assert spec is not None
            text = render(check_draft(ANY, raw), ANY).text()
            digest = spec_digest(spec, ANY, "person")
            for path in rng.sample(_leaves(raw), min(4, len(_leaves(raw)))):
                changed = copy.deepcopy(raw)
                node = changed
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = _mutate(node[path[-1]], rng)
                other, read = read_draft(changed)
                if other is None or read.faults or other == spec:
                    continue
                checked += 1
                self.assertNotEqual(
                    render(check_draft(ANY, changed), ANY).text(), text, (seed, path)
                )
                self.assertNotEqual(
                    spec_digest(other, ANY, "person"), digest, (seed, path)
                )
        self.assertGreater(checked, 400)

    def test_what_is_left_out_is_shown(self) -> None:
        b, d = plate_draft()
        del d["items"][1]
        d["not_modelled"].append(
            {"words": cite(b, "Four 4 mm holes"), "reason": "left for later"}
        )
        report = check_draft(b, d)
        text = render(report, b).text()
        self.assertIn("'Four 4 mm holes': 'left for later'", text)


class TheLock(unittest.TestCase):
    def test_lock_and_check(self) -> None:
        b, d = plate_draft()
        confirmed = lock(check_draft(b, d), b, by="person", strict=False)
        confirmed.check()
        again = unlock(to_wire(confirmed.spec), b, confirmed.digest, by="person")
        self.assertEqual(
            (again.spec, again.assumptions), (confirmed.spec, confirmed.assumptions)
        )

    def test_a_doctored_report_is_checked_again(self) -> None:
        b, d = plate_draft()
        d["silent"] = []
        report = check_draft(b, d)
        self.assertTrue(report.problems)
        with self.assertRaises(LockError):
            lock(dataclasses.replace(report, problems=()), b, by="person", strict=False)

    def test_a_spec_locked_against_another_brief(self) -> None:
        b, d = plate_draft()
        cube = number_words(
            "A 30 mm cube in PLA. It carries no load, so there is no load case."
        )
        with self.assertRaises(LockError):
            lock(
                dataclasses.replace(check_draft(b, d), problems=()),
                cube,
                by="person",
                strict=False,
            )

    def test_a_confirmed_spec_altered_by_hand(self) -> None:
        b, d = plate_draft()
        confirmed = lock(check_draft(b, d), b, by="person", strict=False)
        with self.assertRaises(LockError):
            dataclasses.replace(confirmed, assumptions=()).check()
        with self.assertRaises(LockError):
            dataclasses.replace(confirmed, by="draft").check()

    def test_how_strictly_it_was_checked_is_in_the_hash(self) -> None:
        b, d = plate_draft()
        confirmed = lock(check_draft(b, d), b, by="person", strict=False)
        with self.assertRaises(LockError):
            unlock(
                to_wire(confirmed.spec), b, confirmed.digest, by="person", strict=True
            )

    def test_a_different_brief_is_a_different_contract(self) -> None:
        b, d = plate_draft()
        confirmed = lock(check_draft(b, d), b, by="person", strict=False)
        other = number_words(R05.replace("4 mm thick", "4 mm  thick"))
        with self.assertRaises(LockError):
            unlock(to_wire(confirmed.spec), other, confirmed.digest, by="person")


if __name__ == "__main__":
    unittest.main()
