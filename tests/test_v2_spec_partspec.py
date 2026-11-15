"""V2 stage 1: the PartSpec, read, placed, checked, worded and locked.

Every draft here is built from a brief in V1's corpus (validation/SUITE.md),
never from a blind set. Citations are found by phrase (tests/v2_drafts.py),
because the first hand-counted draft got its word numbers wrong, and the
checks caught it.
"""

from __future__ import annotations

import copy
import dataclasses
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.draft import read_draft
from forge_spec.lock import LockError, lock, spec_digest, unlock
from forge_spec.render import render
from forge_spec.schema import KINDS
from forge_spec.wire import to_wire

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said

R05 = ("An aluminium mounting plate 70 mm long, 50 mm wide and 4 mm thick. Four 4 mm holes pass "
       "through the plate, one near each corner, with their centres on a 56 mm by 36 mm rectangle. "
       "It carries no load, so there is no load case.")  # fmt: skip
R06 = ("A steel pipe flange. It is a disc 80 mm across and 10 mm thick, with a 30 mm bore through "
       "the centre. Four 8 mm bolt holes pass all the way through the disc, equally spaced on a 60 mm "
       "bolt circle. It carries no load, so there is no load case.")  # fmt: skip
R09 = ("A PLA L-bracket 40 mm wide, made of 5 mm thick plate. The base leg is 50 mm long and lies "
       "flat; the upright leg stands on the back end of the base and is 40 mm tall overall. Two 5 mm "
       "holes pass through the base, 20 mm apart across its width, centred 25 mm from the front end. "
       "Two 5 mm holes pass through the upright, 20 mm apart across its width, centred 25 mm above "
       "the bottom. It carries no load, so there is no load case.")  # fmt: skip
R02 = ("A stainless steel shaft collar. The outer diameter is 30 mm and it is 12 mm long. A 16 mm "
       "bore runs all the way through on the axis. One 5 mm set screw hole passes through the wall "
       "from the outside into the bore, halfway along the length. It carries no load - it is a "
       "locating collar, so there is no load case.")  # fmt: skip


def plate_draft() -> tuple[Any, dict[str, Any]]:
    b = number_words(R05)
    d = draft("mounting plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "mounting plate"),
         "length": mm(b, 70, "70 mm"), "width": mm(b, 50, "50 mm"), "height": mm(b, 4, "4 mm")},
        {"id": "holes", "kind": "hole", "words": cite(b, "holes pass through the plate"),
         "on": {"item": "plate", "face": "+z"}, "diameter": mm(b, 4, "4 mm", 2),
         "depth": {"through": True, "from": said(b, "pass through")},
         "count": count(b, 4, "Four"),
         "place": {"x": {"centred": assumed("a rectangle of holes is centred on the plate")},
                   "y": {"centred": assumed("a rectangle of holes is centred on the plate")},
                   "pattern": {"rectangle": {"x": mm(b, 56, "56 mm"), "y": mm(b, 36, "36 mm"),
                                             "each": count(b, 1, "one")}}}},
    ], material=made_of(b, "aluminium"),
       silent=[{"sentence": 2, "reason": "it says there is no load case"}])  # fmt: skip
    return b, d


def flange_draft() -> tuple[Any, dict[str, Any]]:
    b = number_words(R06)
    d = draft("pipe flange", [
        {"id": "disc", "kind": "cylinder", "words": cite(b, "pipe flange"),
         "diameter": mm(b, 80, "80 mm"), "length": mm(b, 10, "10 mm"),
         "axis": choose("z", assumed("a disc lies flat"))},
        {"id": "bore", "kind": "hole", "words": cite(b, "bore through the centre"),
         "on": {"item": "disc", "face": "+end"}, "diameter": mm(b, 30, "30 mm"),
         "depth": {"through": True, "from": said(b, "bore through")},
         "place": {"x": {"centred": said(b, "the centre")}, "y": {"centred": said(b, "the centre")}}},
        {"id": "bolt_holes", "kind": "hole", "words": cite(b, "bolt holes"),
         "on": {"item": "disc", "face": "+end"}, "diameter": mm(b, 8, "8 mm"),
         "depth": {"through": True, "from": said(b, "all the way through")},
         "count": count(b, 4, "Four"),
         "place": {"x": {"centred": said(b, "equally spaced")}, "y": {"centred": said(b, "equally spaced")},
                   "pattern": {"circle": {"diameter": mm(b, 60, "60 mm"), "count": count(b, 4, "Four")}}}},
    ], material=made_of(b, "steel"),
       silent=[{"sentence": 3, "reason": "it says there is no load case"}])  # fmt: skip
    return b, d


def bracket_draft() -> tuple[Any, dict[str, Any]]:
    b = number_words(R09)
    width = mm(b, 40, "40 mm")
    thick = mm(b, 5, "5 mm")
    d = draft("L-bracket", [
        {"id": "base", "kind": "block", "words": cite(b, "base leg"),
         "length": mm(b, 50, "50 mm"), "width": width, "height": thick},
        {"id": "upright", "kind": "block", "words": cite(b, "upright leg stands on the back end of the base"),
         "on": {"item": "base", "face": "+z"},
         "length": thick, "width": width,
         "height": {"value": 35, "unit": "mm", "from": {
             "formula": "40 mm - 5 mm", "words": cite(b, "40 mm tall overall") + cite(b, "5 mm thick")}},
         "place": {"x": {"side": "+x", "distance": {"value": 0, "unit": "mm",
                                                     "from": {"assumed": "the back end is +x; the upright is flush with it"}},
                         "to": "edge"},
                   "y": {"centred": assumed("the upright is as wide as the base")}}},
        {"id": "base_holes", "kind": "hole", "words": cite(b, "holes pass through the base"),
         "on": {"item": "base", "face": "+z"}, "diameter": mm(b, 5, "5 mm", 2),
         "depth": {"through": True, "from": said(b, "pass through the base")},
         "count": count(b, 2, "Two"),
         "place": {"x": {"side": "-x", "distance": mm(b, 25, "25 mm"), "to": "centre"},
                   "pattern": {"row": {"axis": choose("y", said(b, "across its width")),
                                       "pitch": mm(b, 20, "20 mm"), "count": count(b, 2, "Two")}}}},
        {"id": "upright_holes", "kind": "hole", "words": cite(b, "holes pass through the upright"),
         "on": {"item": "upright", "face": "-x"}, "diameter": mm(b, 5, "5 mm", 3),
         "depth": {"through": True, "from": said(b, "pass through the upright")},
         "count": count(b, 2, "Two", 2),
         "place": {"z": {"side": "-z", "to": "centre",
                         "distance": {"value": 20, "unit": "mm", "from": {
                             "formula": "25 mm - 5 mm", "words": cite(b, "25 mm above") + cite(b, "5 mm thick")}}},
                   "pattern": {"row": {"axis": choose("y", said(b, "across its width", 2)),
                                       "pitch": mm(b, 20, "20 mm", 2), "count": count(b, 2, "Two", 2)}}}},
    ], material=made_of(b, "PLA"),
       silent=[{"sentence": 5, "reason": "it says there is no load case"}])  # fmt: skip
    return b, d


def run(pair: tuple[Any, dict[str, Any]], **kw: Any) -> SpecReport:
    return check_draft(pair[0], pair[1], **kw)


def problems(report: SpecReport) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in report.problems]


class CompleteDraftsPassTheChecks(unittest.TestCase):
    def test_the_mounting_plate(self) -> None:
        report = run(plate_draft())
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        holes = report.layout.instances["holes"]
        self.assertEqual(sorted((round(h.origin[0], 6), round(h.origin[1], 6)) for h in holes),
                         [(-28, -18), (-28, 18), (28, -18), (28, 18)])  # fmt: skip
        self.assertEqual(report.layout.extent(), ((-35, -25, 0), (35, 25, 4)))

    def test_the_pipe_flange(self) -> None:
        report = run(flange_draft())
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        bolts = report.layout.instances["bolt_holes"]
        self.assertEqual(len(bolts), 4)
        for hole in bolts:
            self.assertAlmostEqual(
                (hole.origin[0] ** 2 + hole.origin[1] ** 2) ** 0.5, 30.0
            )
            self.assertAlmostEqual(hole.origin[2], 10.0)
        self.assertIn(
            "the first of the 4 starts at 0 degrees",
            " ".join(a.message for a in report.assumptions),
        )

    def test_the_l_bracket(self) -> None:
        report = run(bracket_draft())
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        upright = report.layout.instances["upright"][0]
        self.assertEqual(
            (upright.lo, upright.hi), ((20.0, -20.0, 5.0), (25.0, 20.0, 40.0))
        )
        base_holes = sorted(h.origin for h in report.layout.instances["base_holes"])
        self.assertEqual(base_holes, [(-25 + 25, -10.0, 5.0), (0.0, 10.0, 5.0)])
        upright_holes = sorted(
            h.origin for h in report.layout.instances["upright_holes"]
        )
        self.assertEqual(upright_holes, [(20.0, -10.0, 25.0), (20.0, 10.0, 25.0)])
        self.assertEqual(
            report.layout.extent(), ((-25.0, -20.0, 0.0), (25.0, 20.0, 40.0))
        )


class TheChecksCatchWhatIsWrong(unittest.TestCase):
    def test_a_misquoted_number_goes_back_to_the_writer(self) -> None:
        b, d = plate_draft()
        d["items"][1]["diameter"]["value"] = 4.5
        report = check_draft(b, d)
        self.assertIn("fault", [p.kind for p in report.problems])
        self.assertTrue(report.needs_redraft)

    def test_a_count_the_placement_does_not_make(self) -> None:
        b, d = plate_draft()
        d["items"][1]["place"]["pattern"] = {"row": {
            "axis": choose("x", assumed("test")), "pitch": mm(b, 56, "56 mm"),
            "count": {"count": 2, "from": {"assumed": "test"}}}}  # fmt: skip
        report = check_draft(b, d)
        self.assertTrue(any("placement makes 2" in m for _, m in problems(report)))

    def test_an_unused_number_becomes_a_question(self) -> None:
        b, d = plate_draft()
        d["items"][1]["place"]["pattern"]["rectangle"]["y"] = assumed("test", 36)
        report = check_draft(b, d)
        self.assertIn(("question", "the brief says '36' (sentence 2); nothing in the spec uses it"),
                      problems(report))  # fmt: skip

    def test_an_unaccounted_sentence_becomes_a_question(self) -> None:
        b, d = plate_draft()
        d["silent"] = []
        report = check_draft(b, d)
        self.assertTrue(
            any(
                k == "question" and "nothing in the spec comes from" in m
                for k, m in problems(report)
            )
        )

    def test_a_hole_wider_than_its_face_cannot_be_made(self) -> None:
        # Written for this test: a brief that asks for the impossible.
        b = number_words(
            "A plate 30 mm long, 20 mm wide and 5 mm thick with a 40 mm hole through it."
        )
        d = draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 30, "30 mm"),
             "width": mm(b, 20, "20 mm"), "height": mm(b, 5, "5 mm")},
            {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "plate", "face": "+z"},
             "diameter": mm(b, 40, "40 mm"), "depth": {"through": True, "from": said(b, "through it")},
             "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}},
        ])  # fmt: skip
        self.assertIn("cant", [p.kind for p in check_draft(b, d).problems])

    def test_an_impossibility_from_an_assumption_goes_back_to_the_writer(self) -> None:
        b, d = plate_draft()
        d["items"][1]["diameter"] = assumed("test", 60)
        d["items"][1].pop("count")
        d["items"][1]["place"] = {
            "x": {"centred": assumed("t")},
            "y": {"centred": assumed("t")},
        }
        kinds = {
            p.kind
            for p in check_draft(b, d).problems
            if "larger than the face" in p.message
        }
        self.assertEqual(kinds, {"fault"})

    def test_a_hole_past_the_edge_is_a_question(self) -> None:
        b = number_words(R05.replace("56 mm by 36 mm", "68 mm by 36 mm"))
        d = plate_draft()[1]
        d["items"][1]["place"]["pattern"]["rectangle"]["x"] = mm(b, 68, "68 mm")
        self.assertTrue(
            any(
                k == "question" and "runs past the edge" in m
                for k, m in problems(check_draft(b, d))
            )
        )
        _, d = plate_draft()
        d["items"][1]["place"]["pattern"]["rectangle"]["x"] = assumed("t", 68)
        self.assertTrue(
            any(
                k == "fault" and "runs past the edge" in m
                for k, m in problems(check_draft(b, d))
            )
        )

    def test_a_bore_wider_than_its_tube(self) -> None:
        b = number_words(
            "A collar 30 mm across and 12 mm long with a 31 mm bore."
        )  # for this test
        d = draft("collar", [{"id": "collar", "kind": "tube", "words": cite(b, "collar"),
                              "outer_diameter": mm(b, 30, "30 mm"), "inner_diameter": mm(b, 31, "31 mm"),
                              "length": mm(b, 12, "12 mm")}])  # fmt: skip
        self.assertIn("cant", [p.kind for p in check_draft(b, d).problems])
        d["items"][0]["inner_diameter"] = assumed("t", 31)
        self.assertNotIn("cant", [p.kind for p in check_draft(b, d).problems])

    def test_a_blind_hole_deeper_than_the_plate(self) -> None:
        b, d = plate_draft()
        d["items"][1]["depth"] = assumed(
            "t", 4
        )  # exactly the plate: it breaks through, fine
        self.assertFalse(
            any("should it go through" in m for _, m in problems(check_draft(b, d)))
        )
        d["items"][1]["depth"] = assumed("t", 4.5)
        self.assertTrue(
            any("should it go through" in m for _, m in problems(check_draft(b, d)))
        )

    def test_a_floor_rounding_bigger_than_the_pocket_s_rounded_corners(self) -> None:
        # Written for this test: round a corner rounded 2 mm, a floor's rounding is 2 mm at most.
        b = number_words("A plate 60 mm long, 40 mm wide and 10 mm thick with a pocket 20 mm long, 12 mm wide "
                         "and 5 mm deep, its corners rounded 2 mm, its floor rounded 3 mm.")  # fmt: skip
        d = draft("plate", [
            {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm"),
             "width": mm(b, 40, "40 mm"), "height": mm(b, 10, "10 mm")},
            {"id": "pocket", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "plate", "face": "+z"},
             "shape": choose("rectangle", assumed("a pocket")), "length": mm(b, 20, "20 mm"),
             "width": mm(b, 12, "12 mm"),
             "depth": mm(b, 5, "5 mm"), "corner_radius": mm(b, 2, "2 mm")},
            {"id": "floor", "kind": "fillet", "words": cite(b, "rounded 3"),
             "edges": {"of": "pocket", "which": "bottom", "words": cite(b, "its floor")}, "radius": mm(b, 3, "3 mm")},
        ])  # fmt: skip
        found = problems(check_draft(b, d))
        self.assertIn("cant", [k for k, _ in found], found)
        self.assertTrue(any("at most 2 mm" in m for _, m in found), found)
        d["items"][2]["radius"] = mm(b, 2, "2 mm")
        self.assertNotIn("cant", [k for k, _ in problems(check_draft(b, d))])

    def test_a_rounding_bigger_than_the_open_rim(self) -> None:
        # Written for this test.
        b = number_words("A box 80 mm long, 60 mm wide and 20 mm tall, hollowed out with 2 mm walls, "
                         "open at the top, with all its edges rounded 4 mm.")  # fmt: skip
        d = draft("box", [
            {"id": "box", "kind": "block", "words": cite(b, "box"), "length": mm(b, 80, "80 mm"),
             "width": mm(b, 60, "60 mm"), "height": mm(b, 20, "20 mm")},
            {"id": "hollow", "kind": "shell", "words": cite(b, "hollowed out"), "of": "box",
             "thickness": mm(b, 2, "2 mm"), "open": {"faces": ["+z"], "from": said(b, "open at the top")}},
            {"id": "round", "kind": "fillet", "words": cite(b, "rounded"),
             "edges": {"of": "box", "which": "all", "words": cite(b, "all its edges")},
             "radius": mm(b, 4, "4 mm")},
        ])  # fmt: skip
        self.assertTrue(
            any(
                k == "question" and "open rim" in m
                for k, m in problems(check_draft(b, d))
            )
        )

    def test_references_that_do_not_exist(self) -> None:
        b, d = plate_draft()
        d["items"][1]["on"] = {"item": "plat", "face": "+z"}
        report = check_draft(b, d)
        self.assertTrue(any("no item 'plat'" in m for _, m in problems(report)))
        b, d = plate_draft()
        d["items"][1]["on"] = {"item": "plate", "face": "top"}
        report = check_draft(b, d)
        self.assertTrue(any(k == "fault" and m.startswith("a block's faces are ['+x', '-x', '+y', '-y', "
                                                        "'+z', '-z', 'inner +x'") and m.endswith("not 'top'")
                            for k, m in problems(report)))  # fmt: skip

    def test_an_unknown_standard_size(self) -> None:
        b, d = plate_draft()
        d["items"][1]["diameter"] = {
            "fit": "clearance",
            "for": "M7",
            "from": {"assumed": "t"},
        }
        report = check_draft(b, d)
        self.assertTrue(any("no clearance entry" in m for _, m in problems(report)))

    def test_a_radial_hole_on_a_collar(self) -> None:
        b = number_words(R02)
        d = draft("collar", [
            {"id": "collar", "kind": "tube", "words": cite(b, "shaft collar"),
             "outer_diameter": mm(b, 30, "30 mm"), "inner_diameter": mm(b, 16, "16 mm"),
             "length": mm(b, 12, "12 mm"), "axis": choose("z", said(b, "on the axis"))},
            {"id": "set_screw", "kind": "hole", "words": cite(b, "set screw hole"),
             "on": {"item": "collar", "face": "side"}, "diameter": mm(b, 5, "5 mm"),
             "depth": {"value": 7, "unit": "mm", "from": {
                 "formula": "(30 mm - 16 mm) / 2",
                 "words": cite(b, "30 mm") + cite(b, "16 mm") + cite(b, "through the wall")}},
             "count": count(b, 1, "One"),
             "place": {"z": {"centred": said(b, "halfway along the length")},
                       "angle": {"value": 0, "unit": "deg", "from": {"assumed": "any angle around the collar"}}}},
        ], material=made_of(b, "stainless steel"),
           silent=[{"sentence": 4, "reason": "no load case"}])  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        hole = report.layout.instances["set_screw"][0]
        self.assertEqual(hole.origin, (15.0, 0.0, 6.0))
        self.assertEqual(hole.normal, (1.0, 0.0, 0.0))


class TheReaderKeepsGoodItemsAndReportsEveryFault(unittest.TestCase):
    def test_one_bad_item_does_not_take_the_draft(self) -> None:
        _, d = plate_draft()
        d["items"].append({"id": "bad", "kind": "boss", "words": [1]})
        spec, read = read_draft(d)
        assert spec is not None
        self.assertEqual([i.id for i in spec.items], ["plate", "holes"])
        self.assertEqual({p.at for p in read.faults},
                         {"/items/2/on", "/items/2/diameter", "/items/2/height"})  # fmt: skip

    def test_ids_kinds_and_fields(self) -> None:
        _, d = plate_draft()
        bad = copy.deepcopy(d)
        bad["items"][1]["id"] = "Plate Holes"
        bad["items"][0]["colour"] = "red"
        bad["items"].append({"id": "plate", "kind": "block"})
        bad["items"].append({"id": "x", "kind": "widget"})
        _, read = read_draft(bad)
        messages = " | ".join(str(p) for p in read.faults)
        for expected in (
            "an id is lower case",
            "has no field(s) ['colour']",
            "already used",
            "kind is one of",
        ):
            self.assertIn(expected, messages)

    def test_the_top_level(self) -> None:
        spec, read = read_draft({"spec_format": 2, "items": []})
        self.assertEqual(
            {p.at for p in read.faults}, {"/spec_format", "/name", "/items"}
        )
        spec, read = read_draft([])
        self.assertIsNone(spec)

    def test_every_item_cites_its_words(self) -> None:
        _, d = plate_draft()
        d["items"][0]["words"] = []
        _, read = read_draft(d)
        self.assertIn("/items/0/words", {p.at for p in read.faults})


class EveryKindIsDeclaredOnceAndRoundTrips(unittest.TestCase):
    def test_every_kind_declares_its_fields_and_meanings(self) -> None:
        for kind, spec in KINDS.items():
            self.assertTrue(spec.summary, kind)
            for field in spec.fields:
                self.assertTrue(field.meaning, (kind, field.name))
                if field.type.value == "choice":
                    self.assertTrue(field.choices, (kind, field.name))

    def test_wire_round_trip(self) -> None:
        for pair in (plate_draft(), flange_draft(), bracket_draft()):
            spec, read = read_draft(pair[1])
            assert spec is not None
            self.assertFalse(read.faults)
            again, _ = read_draft(to_wire(spec))
            self.assertEqual(again, spec)


class TheFixedWording(unittest.TestCase):
    def test_lines_and_assumptions(self) -> None:
        b, d = flange_draft()
        text = render(check_draft(b, d), b).text()
        self.assertIn("Assumed (check these first):", text)
        self.assertIn("  - disc.axis: z (assumed: 'a disc lies flat')", text)
        self.assertIn(
            "4 x hole bolt_holes: \u00d88 mm, right through, into the +end face of disc",
            text,
        )
        self.assertIn(
            "4 equally spaced on a 60 mm circle, the first at 0 deg (assumed)", text
        )
        self.assertIn(
            "Cylinder disc: \u00d880 mm, 10 mm long, axis Z (assumed), at the origin  [exact]",
            text,
        )
        self.assertIn("pipe flange - 3 item(s)\n\nMaterial: 'steel'\n", text)
        self.assertIn("Taken to say nothing about the shape:\n  - 'It carries no load, so there is no "
                      "load case': 'it says there is no load case'", text)  # fmt: skip

    def test_the_bracket_reads_as_built(self) -> None:
        pair = bracket_draft()
        text = render(run(pair), pair[0]).text()
        self.assertIn("Block upright: 5 mm x 40 mm x 35 mm (= 40 mm - 5 mm)", text)
        self.assertIn(
            "  - upright.place.x.distance: 0 mm (assumed: 'the back end is +x;", text
        )
        self.assertIn("0 mm (assumed) from the +x edge to its near edge", text)


class Locking(unittest.TestCase):
    def test_lock_and_check(self) -> None:
        b, d = plate_draft()
        report = check_draft(b, d)
        confirmed = lock(report, b, by="person", strict=False)
        confirmed.check()
        self.assertEqual(confirmed.digest, spec_digest(confirmed.spec, b, "person"))
        again = unlock(to_wire(confirmed.spec), b, confirmed.digest, by="person")
        self.assertEqual((again.spec, again.digest, again.assumptions),
                         (confirmed.spec, confirmed.digest, confirmed.assumptions))  # fmt: skip

    def test_any_change_changes_the_hash(self) -> None:
        b, d = plate_draft()
        first = lock(check_draft(b, d), b, by="person", strict=False).digest
        d["items"][1]["place"]["pattern"]["rectangle"]["x"] = assumed("t", 56.0001)
        changed = to_wire(read_draft(d)[0])  # type: ignore[arg-type]
        with self.assertRaises(LockError):
            unlock(changed, b, first, by="person")

    def test_the_same_content_has_the_same_hash(self) -> None:
        b, d = plate_draft()
        as_floats = copy.deepcopy(d)
        as_floats["items"][0]["length"]["value"] = 70.0
        self.assertEqual(lock(check_draft(b, d), b, by="person", strict=False).digest,
                         lock(check_draft(b, as_floats), b, by="person", strict=False).digest)  # fmt: skip

    def test_a_draft_can_t_pass_for_confirmed(self) -> None:
        b, d = plate_draft()
        drafted = lock(check_draft(b, d), b, by="draft", strict=False)
        with self.assertRaises(LockError):
            unlock(to_wire(drafted.spec), b, drafted.digest, by="person")
        relabelled = dataclasses.replace(drafted, by="person")
        with self.assertRaises(LockError):
            relabelled.check()

    def test_a_different_brief_is_a_different_contract(self) -> None:
        b, d = plate_draft()
        confirmed = lock(check_draft(b, d), b, by="person", strict=False)
        other = number_words(R05.replace("4 mm thick", "4 mm  thick"))
        with self.assertRaises(LockError):
            unlock(to_wire(confirmed.spec), other, confirmed.digest, by="person")

    def test_a_spec_with_problems_cannot_be_locked(self) -> None:
        b, d = plate_draft()
        d["silent"] = []
        with self.assertRaises(LockError):
            lock(check_draft(b, d), b, by="person", strict=False)
        with self.assertRaises(LockError):
            lock(check_draft(b, plate_draft()[1]), b, by="someone", strict=False)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
