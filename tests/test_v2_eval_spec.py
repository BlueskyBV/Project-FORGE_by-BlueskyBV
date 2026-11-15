"""V2 stage 1: grading drafts against answer keys, and the set runner (forge_eval.spec_grade, ``forge eval-spec``).

Every brief and key here is written for these tests; none comes from a blind
set, which no test may read or tune on. The model is scripted, so the tests
pin, offline:

- each fact is graded by whoever can settle it now: the spec's layout, a
  person's mark, or the built part; nothing waiting is counted as right;
- the layout's reading is exact where it claims to be (a blind hole as deep
  as its plate goes through; a tube's bore is a through hole) and stands
  aside where it can't be (a hole into a hollow);
- with no draft every fact is wrong; a refusal is right only for a brief
  that can't be made, and only as CAN'T;
- a person's marks are tied to the draft they were made against;
- a run is checked against the set's manifest, resumes without drafting
  twice, stops on a model error without blaming the writer, and keeps every
  grading on record.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from forge_cli.cli import build_parser
from forge_cli.eval_spec import (
    _MEASURED_FILES,
    _MEASURED_PACKAGES,
    RecordError,
    RunMismatchError,
    code_digest,
    report_lines,
    run_set,
)
from forge_eval.bounds import upper_bound
from forge_eval.keys import AnswerKeyError, key_from_dict, lock_set
from forge_eval.spec_grade import (
    MarksError,
    draft_digest,
    grade_set,
    grade_spec,
    load_marks,
)
from forge_models import ScriptedProvider
from forge_models.errors import RequestError, TransientError
from forge_roles.spec_writer import SpecWriter
from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.guide import EXAMPLE_BRIEF, EXAMPLE_DRAFT

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, choose, cite, draft, made_of, mm, said

EDGES = "the vertical edges are rounded to 3 mm"


def key(**fields: Any) -> Any:
    base = {
        "format": 1,
        "written_by": "the tests",
        "independent": False,
        "note": "",
        "brief": "A part.",
    }
    return key_from_dict({**base, **fields})


PLATE_KEY = key(id="plate", brief=EXAMPLE_BRIEF, expect="verified", envelope_mm=[6, 30, 80],
                volume_mm3=[14000, 14200], through_holes=[{"diameter_mm": [4.9, 5.1], "count": 2}],
                facts=[EDGES])  # fmt: skip

DEEP = ("A steel plate 70 mm long, 50 mm wide and 4 mm thick with a 6 mm hole 10 mm deep in the middle. "
        "It carries no load.")  # fmt: skip
DEEP_KEY = key(id="deep", brief=DEEP, expect="question", envelope_mm=[4, 50, 70],
               questions=["whether the 6 mm hole goes through the 4 mm plate"])  # fmt: skip

CUBE = "A PLA cube 20 mm on each side with a 30 mm hole through its top."
CUBE_KEY = key(
    id="cube", brief=CUBE, expect="cant", note="the hole is wider than the cube"
)

BLOCK = "A PLA block 40 mm long, 30 mm wide and 20 mm tall."
BLOCK_KEY = key(
    id="bad",
    brief=BLOCK,
    expect="verified",
    envelope_mm=[20, 30, 40],
    volume_mm3=[23900, 24100],
)


def plate() -> dict[str, Any]:
    return copy.deepcopy(dict(EXAMPLE_DRAFT))


def checked(brief: str, d: dict[str, Any]) -> SpecReport:
    report = check_draft(number_words(brief), d)
    assert not report.needs_redraft, report.problems
    return report


def deep_draft() -> dict[str, Any]:
    b = number_words(DEEP)
    return draft("plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 70, "70 mm"),
         "width": mm(b, 50, "50 mm"), "height": mm(b, 4, "4 mm")},
        {"id": "h", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "plate", "face": "+z"},
         "diameter": mm(b, 6, "6 mm"), "depth": mm(b, 10, "10 mm"),
         "place": {"x": {"centred": said(b, "the middle")}, "y": {"centred": said(b, "the middle")}}},
    ], material=made_of(b, "steel"),
        silent=[{"sentence": 1, "reason": "no load case"}])  # fmt: skip


def cube_draft() -> dict[str, Any]:
    b = number_words(CUBE)
    side = mm(b, 20, "20 mm")
    return draft("cube", [
        {"id": "cube", "kind": "block", "words": cite(b, "cube"), "length": side, "width": side, "height": side},
        {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "cube", "face": "+z"},
         "diameter": mm(b, 30, "30 mm"), "depth": {"through": True, "from": said(b, "through")},
         "place": {"x": {"centred": assumed("its top's middle")}, "y": {"centred": assumed("its top's middle")}}},
    ], material=made_of(b, "PLA"))  # fmt: skip


def bad_draft() -> dict[str, Any]:
    b = number_words(BLOCK)
    return draft("block", [{"id": "block", "kind": "block", "words": cite(b, "block"),
                            "length": mm(b, 45, "40 mm"), "width": mm(b, 30, "30 mm"),
                            "height": mm(b, 20, "20 mm")}],
                 material=made_of(b, "PLA"))  # fmt: skip


def verdicts(grade: Any) -> dict[str, tuple[str, str]]:
    return {f.fact: (f.verdict, f.by) for f in grade.facts}


class EachFactIsGradedByWhoeverCanSettleIt(unittest.TestCase):
    def test_a_draft_that_reads_its_brief_right(self) -> None:
        grade = grade_spec(PLATE_KEY, checked(EXAMPLE_BRIEF, plate()))
        self.assertEqual(verdicts(grade), {
            "it can be made": ("right", "spec"),
            "overall 6 x 30 x 80 mm": ("right", "spec"),
            "2 round through hole(s) of 4.9-5.1 mm": ("right", "spec"),
            "no other round through holes": ("right", "spec"),
            "a volume of 14000-14200 mm³": ("not graded", "built part"),
            EDGES: ("not graded", "person"),
        })  # fmt: skip
        self.assertEqual(
            (grade.ending, grade.marked, grade.all_right), ("assumed", False, False)
        )

    def test_a_misread_size_is_wrong_and_says_what_the_draft_has(self) -> None:
        misread = plate()
        misread["items"][0]["length"] = {
            "value": 90,
            "unit": "mm",
            "from": {"assumed": "for the test"},
        }
        grade = grade_spec(PLATE_KEY, checked(EXAMPLE_BRIEF, misread))
        (size,) = [f for f in grade.facts if f.fact.startswith("overall")]
        self.assertEqual(
            (size.verdict, size.detail), ("wrong", "the draft is 6 x 30 x 90 mm")
        )

    def test_a_blind_hole_as_deep_as_its_plate_goes_through(self) -> None:
        for depth, through in ((6, 2), (5, 0)):
            d = plate()
            d["items"][1]["depth"] = assumed("for the test", depth)
            grade = grade_spec(PLATE_KEY, checked(EXAMPLE_BRIEF, d))
            (holes,) = [f for f in grade.facts if f.fact.startswith("2 round")]
            self.assertEqual(holes.detail, f"the draft has {through}", depth)

    def test_a_hole_the_key_doesn_t_name_is_wrong(self) -> None:
        d = plate()
        d["items"][1]["diameter"] = {
            "value": 5,
            "unit": "mm",
            "from": {"words": [15, 16]},
        }
        key_ = key(
            **{
                **PLATE_KEY.as_dict(),
                "through_holes": [{"diameter_mm": [5.9, 6.1], "count": 2}],
            }
        )
        facts = {f.fact: f for f in grade_spec(key_, checked(EXAMPLE_BRIEF, d)).facts}
        self.assertEqual(
            facts["2 round through hole(s) of 5.9-6.1 mm"].verdict, "wrong"
        )
        self.assertEqual(
            facts["no other round through holes"].detail,
            "others in the draft: 2 of 5 mm",
        )

    def test_a_tube_s_bore_is_a_through_hole(self) -> None:
        brief = "A tube 20 mm across with a 12 mm bore, 30 mm long."
        b = number_words(brief)
        d = draft("tube", [{"id": "tube", "kind": "tube", "words": cite(b, "tube"),
                            "outer_diameter": mm(b, 20, "20 mm"), "inner_diameter": mm(b, 12, "12 mm"),
                            "length": mm(b, 30, "30 mm"), "axis": choose("z", assumed("standing up"))}])  # fmt: skip
        key_ = key(id="tube", brief=brief, expect="verified", envelope_mm=[20, 20, 30], volume_mm3=[5900, 6200],
                   through_holes=[{"diameter_mm": [11.9, 12.1], "count": 1}])  # fmt: skip
        grade = grade_spec(key_, checked(brief, d))
        self.assertEqual(grade.count("wrong"), 0, grade.facts)
        self.assertEqual(grade.count("right"), 4)
        # Standing on a base, its bore is closed at the bottom: the layout doesn't say.
        base = {"id": "base", "kind": "block", "words": cite(b, "tube"), "length": assumed("t", 40),
                "width": assumed("t", 40), "height": assumed("t", 5)}  # fmt: skip
        d["items"] = [base, {**d["items"][0], "on": {"item": "base", "face": "+z"},
                             "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}}]  # fmt: skip
        holes = [
            f for f in grade_spec(key_, checked(brief, d)).facts if "through" in f.fact
        ]
        self.assertEqual({(f.verdict, f.detail) for f in holes},
                         {("not graded", "tube's bore may be closed at an end: checked on the built part")})  # fmt: skip

    def test_a_hollow_is_counted_and_a_hole_into_it_waits_for_the_built_part(
        self,
    ) -> None:
        brief = "A sealed hollow box 40 mm long, 30 mm wide and 20 mm tall with 2 mm walls, completely closed."
        b = number_words(brief)
        box = {"id": "box", "kind": "block", "words": cite(b, "box"), "length": mm(b, 40, "40 mm"),
               "width": mm(b, 30, "30 mm"), "height": mm(b, 20, "20 mm")}  # fmt: skip
        hollow = {"id": "hollow", "kind": "shell", "words": cite(b, "sealed hollow"), "of": "box",
                  "thickness": mm(b, 2, "2 mm walls"), "open": {"faces": [], "from": said(b, "completely closed")}}  # fmt: skip
        key_ = key(id="box", brief=brief, expect="verified", envelope_mm=[20, 30, 40], volume_mm3=[1, 2],
                   inner_voids=1, through_holes=[{"diameter_mm": [4.9, 5.1], "count": 1}])  # fmt: skip
        facts = {
            f.fact: f
            for f in grade_spec(key_, checked(brief, draft("box", [box, hollow]))).facts
        }
        self.assertEqual(
            (facts["1 sealed hollow(s)"].verdict, facts["1 sealed hollow(s)"].by),
            ("right", "spec"),
        )
        self.assertEqual(facts["no other round through holes"].by, "built part")
        hole = {"id": "vent", "kind": "hole", "words": cite(b, "box"), "on": {"item": "box", "face": "+z"},
                "diameter": assumed("for the test", 5), "depth": {"through": True, "from": assumed("a vent")},
                "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}}  # fmt: skip
        vented = checked(brief, draft("box", [box, hollow, hole]))
        facts = {f.fact: f for f in grade_spec(key_, vented).facts}
        self.assertEqual((facts["1 sealed hollow(s)"].verdict, facts["1 sealed hollow(s)"].detail),
                         ("not graded", "vent may open a hollow"))  # fmt: skip

    def test_with_no_draft_every_fact_is_wrong(self) -> None:
        grade = grade_spec(PLATE_KEY, None)
        self.assertEqual(grade.ending, "gave up")
        self.assertEqual(grade.count("wrong"), len(grade.facts))
        self.assertEqual(grade.draft, "")


class WhereTheLayoutCantTellItSaysSo(unittest.TestCase):
    """Never a guess: what the bodies' bounds and the cuts can't settle waits for the built part."""

    POST = ("A PLA plate 40 mm long, 25 mm wide and 5 mm thick, with a post 10 mm across and 8 mm tall in "
            "the middle, and one 4 mm hole right through the post and the plate.")  # fmt: skip

    def post(self, *holes: dict[str, Any]) -> tuple[Any, SpecReport]:
        b = number_words(self.POST)
        middle = {
            "x": {"centred": said(b, "the middle")},
            "y": {"centred": said(b, "the middle")},
        }
        items = [
            {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 40, "40 mm"),
             "width": mm(b, 25, "25 mm"), "height": mm(b, 5, "5 mm")},
            {"id": "post", "kind": "boss", "words": cite(b, "post"), "on": {"item": "plate", "face": "+z"},
             "diameter": mm(b, 10, "10 mm"), "height": mm(b, 8, "8 mm"), "place": middle},
            *holes,
        ]  # fmt: skip
        key_ = key(id="post", brief=self.POST, expect="verified", envelope_mm=[13, 25, 40],
                   volume_mm3=[1, 99999], through_holes=[{"diameter_mm": [3.9, 4.1], "count": 1}])  # fmt: skip
        return key_, check_draft(
            b,
            draft(
                "post",
                items,
                material=made_of(b, "PLA"),
            ),
        )

    def hole(self, name: str, on: str, face: str) -> dict[str, Any]:
        b = number_words(self.POST)
        return {"id": name, "kind": "hole", "words": cite(b, "hole"), "on": {"item": on, "face": face},
                "diameter": mm(b, 4, "4 mm"), "depth": {"through": True, "from": said(b, "right through")},
                "place": {"x": {"centred": said(b, "the middle")}, "y": {"centred": said(b, "the middle")}}}  # fmt: skip

    def test_one_hole_drawn_from_both_sides_is_one(self) -> None:
        key_, report = self.post(
            self.hole("down", "post", "+end"), self.hole("up", "plate", "-z")
        )
        facts = {f.fact: f for f in grade_spec(key_, report).facts}
        self.assertEqual(
            facts["1 round through hole(s) of 3.9-4.1 mm"].detail, "the draft has 1"
        )

    def test_holes_with_air_between_them_are_two(self) -> None:
        # A clevis: two ears with a gap between them, one pin hole through both.
        brief = ("A PLA clevis: a base 60 mm long, 20 mm wide and 5 mm thick, with two ears 10 mm thick, "
                 "20 mm wide and 30 mm tall at its ends, and an 8 mm hole through each ear.")  # fmt: skip
        b = number_words(brief)
        ear = {"kind": "post", "words": cite(b, "ears"), "on": {"item": "base", "face": "+z"},
               "length": mm(b, 10, "10 mm"), "width": mm(b, 20, "20 mm", nth=2), "height": mm(b, 30, "30 mm")}  # fmt: skip
        hole = {"kind": "hole", "words": cite(b, "hole"), "diameter": mm(b, 8, "8 mm"),
                "depth": {"through": True, "from": said(b, "through each ear")},
                "place": {"y": {"centred": assumed("t")}, "z": {"offset": assumed("t", 5)}}}  # fmt: skip
        d = draft("clevis", [
            {"id": "base", "kind": "block", "words": cite(b, "base"), "length": mm(b, 60, "60 mm"),
             "width": mm(b, 20, "20 mm"), "height": mm(b, 5, "5 mm")},
            {**ear, "id": "left", "place": {"x": {"side": "-x", "distance": assumed("t", 0), "to": "edge"},
                                           "y": {"centred": assumed("t")}}},
            {**ear, "id": "right", "place": {"x": {"side": "+x", "distance": assumed("t", 0), "to": "edge"},
                                            "y": {"centred": assumed("t")}}},
            {**hole, "id": "pin_left", "on": {"item": "left", "face": "-x"}},
            {**hole, "id": "pin_right", "on": {"item": "right", "face": "+x"}},
        ], material=made_of(b, "PLA"))  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual(report.of_kind("fault"), (), report.problems)
        key_ = key(id="clevis", brief=brief, expect="verified", envelope_mm=[20, 35, 60], volume_mm3=[1, 99999],
                   through_holes=[{"diameter_mm": [7.9, 8.1], "count": 2}])  # fmt: skip
        holes = next(
            f for f in grade_spec(key_, report).facts if f.fact.startswith("2 round")
        )
        self.assertEqual(holes.detail, "the draft has 2")

    def test_a_hole_anywhere_may_open_a_hollow(self) -> None:
        b = number_words(self.POST)
        key_, report = self.post(self.hole("down", "post", "+end"),
                                 {"id": "hollow", "kind": "shell", "words": cite(b, "plate"), "of": "plate",
                                  "thickness": assumed("t", 1), "open": {"faces": [], "from": assumed("sealed")}})  # fmt: skip
        key_ = key(**{**key_.as_dict(), "inner_voids": 1})
        voids = next(f for f in grade_spec(key_, report).facts if "hollow" in f.fact)
        self.assertEqual((voids.verdict, voids.by), ("not graded", "built part"))

    def test_a_cut_through_at_an_edge_may_shorten_the_part(self) -> None:
        bar = "A PLA bar 70 mm long, 20 mm wide and 5 mm thick, with a 10 mm by 20 mm notch right through one end."
        b = number_words(bar)
        d = draft("bar", [
            {"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": mm(b, 70, "70 mm"),
             "width": mm(b, 20, "20 mm"), "height": mm(b, 5, "5 mm")},
            {"id": "notch", "kind": "pocket", "words": cite(b, "notch"), "on": {"item": "bar", "face": "+z"},
             "shape": choose("rectangle", said(b, "10 mm by 20 mm")), "length": mm(b, 10, "10 mm"),
             "width": mm(b, 20, "20 mm", nth=2), "depth": {"through": True, "from": said(b, "right through")},
             "place": {"x": {"side": "-x", "distance": assumed("at the end", 0), "to": "edge"},
                       "y": {"centred": assumed("t")}}},
        ], material=made_of(b, "PLA"))  # fmt: skip
        key_ = key(
            id="bar",
            brief=bar,
            expect="verified",
            envelope_mm=[5, 20, 60],
            volume_mm3=[1, 99999],
        )
        size = next(
            f
            for f in grade_spec(key_, check_draft(b, d)).facts
            if f.fact.startswith("overall")
        )
        self.assertEqual((size.verdict, size.detail),
                         ("not graded", "notch goes through at the edge of a face: checked on the built part"))  # fmt: skip

    def test_a_draft_that_doesn_t_check_clean_is_no_draft(self) -> None:
        bad = plate()
        bad["items"][0]["length"]["value"] = 75
        grade = grade_spec(PLATE_KEY, check_draft(number_words(EXAMPLE_BRIEF), bad))
        self.assertEqual((grade.ending, grade.draft), ("gave up", ""))
        self.assertTrue(
            grade.facts[0].detail.startswith(
                "the draft doesn't check clean: /items/0/length"
            )
        )
        self.assertEqual(grade.count("wrong"), len(grade.facts))


class HowTheRunShouldEnd(unittest.TestCase):
    def test_a_brief_that_can_t_be_made_is_refused_as_can_t(self) -> None:
        grade = grade_spec(CUBE_KEY, check_draft(number_words(CUBE), cube_draft()))
        self.assertEqual(
            [(f.fact, f.verdict) for f in grade.facts], [("it can't be made", "right")]
        )
        self.assertEqual(grade.ending, "refused")

    def test_a_clean_draft_of_it_is_wrong(self) -> None:
        d = cube_draft()
        d["items"][1]["diameter"] = assumed("smaller", 10)
        (ending,) = grade_spec(CUBE_KEY, checked(CUBE, d)).facts
        self.assertEqual(ending.verdict, "wrong")

    def test_a_brief_that_should_ask(self) -> None:
        grade = grade_spec(DEEP_KEY, check_draft(number_words(DEEP), deep_draft()))
        self.assertEqual(verdicts(grade), {
            "it asks before building": ("right", "spec"),
            "overall 4 x 50 x 70 mm": ("right", "spec"),
            "asks about: whether the 6 mm hole goes through the 4 mm plate": ("not graded", "person"),
        })  # fmt: skip

    def test_only_assumptions_are_the_person_s_to_mark(self) -> None:
        # Centring a hole across the plate is no question about its depth.
        d = deep_draft()
        b = number_words(DEEP)
        d["items"][1]["depth"] = {
            "through": True,
            "from": {"assumed": "it goes through"},
        }
        d["items"][1]["place"]["y"] = {"centred": assumed("across the width")}
        d["not_modelled"].append({"words": cite(b, "10 mm deep"), "reason": "a typo"})
        report = check_draft(b, d)
        self.assertEqual(report.of_kind("question"), (), report.problems)
        (ending, *_) = grade_spec(DEEP_KEY, report).facts
        self.assertEqual((ending.verdict, ending.by), ("not graded", "person"))
        (ending, *_) = grade_spec(
            DEEP_KEY, report, {"it asks before building": "wrong"}
        ).facts
        self.assertEqual((ending.verdict, ending.by), ("wrong", "person"))

    def test_a_refusal_of_a_part_that_can_be_made_is_wrong(self) -> None:
        refused = grade_spec(PLATE_KEY, check_draft(number_words(CUBE), cube_draft()))
        self.assertEqual(refused.facts[0].verdict, "wrong")


class APersonsMarks(unittest.TestCase):
    def test_grade_the_facts_in_words(self) -> None:
        report = checked(EXAMPLE_BRIEF, plate())
        right = grade_spec(PLATE_KEY, report, {EDGES: "right"})
        self.assertTrue(right.all_right)
        wrong = grade_spec(PLATE_KEY, report, {EDGES: "wrong"})
        self.assertEqual(verdicts(wrong)[EDGES], ("wrong", "person"))

    def test_a_mark_for_a_fact_the_key_doesn_t_state_is_refused(self) -> None:
        report = checked(EXAMPLE_BRIEF, plate())
        with self.assertRaises(MarksError):
            grade_spec(PLATE_KEY, report, {"the edges are rounded": "right"})
        with self.assertRaises(MarksError):
            grade_spec(PLATE_KEY, report, {EDGES: "maybe"})  # type: ignore[dict-item]

    def test_a_malformed_marks_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "marks.json"
            for bad in ({"format": 2, "marks": {}}, {"format": 1, "marks": {"k": {"facts": {}}}},
                        {"format": 1, "marks": {"k": {"draft": "d", "facts": {"f": "yes"}}}}):  # fmt: skip
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(MarksError, msg=bad):
                    load_marks(path)


class ASetsGrade(unittest.TestCase):
    def test_counts_and_its_bound(self) -> None:
        grades = [
            grade_spec(PLATE_KEY, checked(EXAMPLE_BRIEF, plate()), {EDGES: "right"}),
            grade_spec(BLOCK_KEY, None),
        ]
        g = grade_set(grades)
        self.assertEqual((g.right, g.wrong, g.waiting("built part")), (5, 3, 1))
        self.assertAlmostEqual(g.wrong_at_most(), upper_bound(3, 8, 0.95))
        self.assertEqual(g.as_dict()["parts_all_right"], 1)
        self.assertEqual(
            grade_set([]).wrong_at_most(), 1.0
        )  # nothing graded: nothing known


def locked(folder: Path) -> Path:
    keys = folder / "set"
    lock_set(keys, [PLATE_KEY, DEEP_KEY, CUBE_KEY, BLOCK_KEY], "test set")
    return keys


def script(*names: str) -> list[Any]:
    drafts = {
        "bad": [bad_draft(), bad_draft()],
        "cube": [cube_draft()],
        "deep": [deep_draft()],
        "plate": [plate()],
    }
    return [d for name in names for d in drafts[name]]


class RunFolder(unittest.TestCase):
    """A locked set written for these tests, and a run folder for it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.keys = locked(self.folder)
        self.out = self.folder / "run"
        self.heard: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_it(self, responses: list[Any], **options: Any) -> Any:
        return run_set(
            self.keys,
            ScriptedProvider(responses),
            self.out,
            say=self.heard.append,
            **options,
        )


class TheSetRunner(RunFolder):
    def test_every_brief_drafted_graded_and_written(self) -> None:
        run = self.run_it(
            script("bad", "cube", "deep", "plate")
        )  # the set's keys in order
        self.assertEqual((run.drafted, run.reused, run.stopped), (4, 0, ""))
        self.assertEqual({g.key: g.ending for g in run.grade.grades},
                         {"bad": "gave up", "cube": "refused", "deep": "asked", "plate": "assumed"})  # fmt: skip
        self.assertTrue((self.out / "bad" / "refused.json").exists())
        for name in (
            "draft.json",
            "spec.txt",
            "calls.json",
            "problems.json",
            "grade.json",
        ):
            self.assertTrue((self.out / "plate" / name).exists(), name)
        marks = json.loads((self.out / "marks.json").read_text(encoding="utf-8"))[
            "marks"
        ]
        self.assertEqual(sorted(marks), ["deep", "plate"])
        self.assertEqual(marks["plate"]["facts"], {EDGES: ""})
        self.assertEqual(
            len((self.out / "history.jsonl").read_text(encoding="utf-8").splitlines()),
            1,
        )
        text = "\n".join(report_lines(run))
        self.assertIn("Facts    : 7 of 10 graded right (70.0%); wrong at most", text)
        self.assertIn(
            "Endings  : cant: 1 refused; question: 1 asked; verified: 1 assumed, 1 gave up",
            text,
        )
        self.assertIn(
            "  bad: it can be made (the writer couldn't clear its own faults)", text
        )

    def test_running_again_regrades_the_records_and_drafts_nothing(self) -> None:
        first = self.run_it(script("bad", "cube", "deep", "plate"))
        again = self.run_it([])
        self.assertEqual((again.drafted, again.reused), (0, 4))
        self.assertEqual(
            [g.as_dict() for g in again.grade.grades],
            [g.as_dict() for g in first.grade.grades],
        )
        self.assertEqual(
            len((self.out / "history.jsonl").read_text(encoding="utf-8").splitlines()),
            2,
        )

    def test_marks_are_read_and_tied_to_their_draft(self) -> None:
        self.run_it(script("bad", "cube", "deep", "plate"))
        path = self.out / "marks.json"
        marks = json.loads(path.read_text(encoding="utf-8"))
        marks["marks"]["plate"]["facts"][EDGES] = "right"
        path.write_text(json.dumps(marks), encoding="utf-8")
        graded = {g.key: g for g in self.run_it([]).grade.grades}
        self.assertEqual(verdicts(graded["plate"])[EDGES], ("right", "person"))
        spec = check_draft(number_words(EXAMPLE_BRIEF), plate()).spec
        assert spec is not None
        self.assertEqual(marks["marks"]["plate"]["draft"], draft_digest(spec))
        marks["marks"]["plate"]["draft"] = "0" * 64  # as if made against another draft
        path.write_text(json.dumps(marks), encoding="utf-8")
        run = self.run_it([])
        self.assertEqual(run.dropped, ("plate",))
        self.assertEqual(
            verdicts({g.key: g for g in run.grade.grades}["plate"])[EDGES],
            ("not graded", "person"),
        )

    def test_a_model_error_stops_the_run_without_blaming_the_writer(self) -> None:
        run = self.run_it(
            [*script("bad", "cube"), TransientError("the endpoint went away")]
        )
        self.assertIn("deep: ", run.stopped)
        self.assertEqual([g.key for g in run.grade.grades], ["bad", "cube"])
        self.assertFalse((self.out / "deep").exists())
        resumed = self.run_it(script("deep", "plate"))
        self.assertEqual((resumed.drafted, resumed.reused, resumed.stopped), (2, 2, ""))

    def test_only_some_keys_and_the_others_marks_kept(self) -> None:
        self.run_it(script("bad", "cube", "deep", "plate"))
        run = self.run_it([], only=["plate"])
        self.assertEqual([g.key for g in run.grade.grades], ["plate"])
        marks = json.loads((self.out / "marks.json").read_text(encoding="utf-8"))[
            "marks"
        ]
        self.assertEqual(sorted(marks), ["deep", "plate"])
        with self.assertRaises(AnswerKeyError):
            self.run_it([], only=["nope"])

    def test_a_key_changed_after_locking_is_refused(self) -> None:
        path = self.keys / "plate.json"
        path.write_text(
            path.read_text(encoding="utf-8").replace("80", "90"), encoding="utf-8"
        )
        with self.assertRaises(AnswerKeyError):
            self.run_it([])

    def test_a_run_of_another_mode_is_never_mixed_in(self) -> None:
        self.run_it(script("bad", "cube", "deep", "plate"))
        with self.assertRaises(RunMismatchError):
            self.run_it([], strict=True)


class OneRunFolderIsOneMeasurement(RunFolder):
    def run_json(self, **changes: Any) -> None:
        path = self.out / "run.json"
        run = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({**run, **changes}), encoding="utf-8")

    def test_another_writer_is_refused(self) -> None:
        self.run_it(script("bad", "cube", "deep", "plate"))
        self.run_json(writer={"role": "spec_writer", "prompt_version": "v2-guide-0"})
        with self.assertRaises(RunMismatchError):
            self.run_it([])

    def test_other_code_regrades_flagged_but_never_drafts_more(self) -> None:
        self.run_it(script("bad", "cube", "deep"), only=["bad", "cube", "deep"])
        self.run_json(code="0" * 64)
        run = self.run_it([], only=["bad", "cube", "deep"])
        self.assertTrue(run.other_code)
        self.assertIn("not the stage 1 measurement", "\n".join(report_lines(run)))
        with self.assertRaises(RunMismatchError):  # plate is still to draft
            self.run_it(script("plate"))

    def test_a_brief_is_graded_from_the_model_s_answer_never_a_copy(self) -> None:
        first = self.run_it(script("bad", "cube", "deep", "plate"))
        draft = self.out / "plate" / "draft.json"
        draft.write_text(
            draft.read_text(encoding="utf-8").replace('"value": 5', '"value": 6'),
            encoding="utf-8",
        )
        self.assertEqual([g.as_dict() for g in self.run_it([]).grade.grades],
                         [g.as_dict() for g in first.grade.grades])  # fmt: skip
        answer = self.out / "plate" / "answer.json"
        answer.write_text(
            answer.read_text(encoding="utf-8").replace('"value": 5', '"value": 6'),
            encoding="utf-8",
        )
        with self.assertRaises(RecordError):
            self.run_it([])

    def test_a_brief_whose_record_is_gone_is_never_drafted_twice(self) -> None:
        self.run_it(script("bad", "cube", "deep", "plate"))
        (self.out / "deep" / "record.json").unlink()
        with self.assertRaises(RecordError):
            self.run_it(script("deep"))

    def test_a_record_left_half_written_is_drafted_again(self) -> None:
        # Drafting stopped before its record was whole: no record, and nothing in the ledger.
        self.run_it(script("bad", "cube", "deep", "plate"))
        (self.out / "deep" / "record.json").unlink()
        ledger = self.out / "ledger.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines()
        ledger.write_text(
            "".join(f"{line}\n" for line in lines if '"deep"' not in line),
            encoding="utf-8",
        )
        run = self.run_it(script("deep"))
        self.assertEqual((run.drafted, run.reused), (1, 3))

    def test_the_code_it_rests_on_is_all_of_it(self) -> None:
        digest = code_digest()
        self.assertEqual(code_digest(), digest)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        measured = {f"{p}/{n}" for p, n in _MEASURED_FILES} | set(_MEASURED_PACKAGES)
        for name in (
            "forge_units",
            "forge_expr",
            "forge_models",
            "forge_cli/eval_spec.py",
            "forge_roles/base.py",
        ):
            self.assertIn(name, measured)

    def test_a_model_error_of_one_brief_s_own_leaves_it_ungraded_and_goes_on(
        self,
    ) -> None:
        run = self.run_it(
            [
                *script("bad"),
                RequestError("this request is refused"),
                *script("deep", "plate"),
            ]
        )
        self.assertEqual(
            ([g.key for g in run.grade.grades], run.stopped),
            (["bad", "deep", "plate"], ""),
        )
        self.assertEqual([k for k, _ in run.errors], ["cube"])
        history = [
            json.loads(line)
            for line in (self.out / "history.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(
            (history[-1]["keys"], history[-1]["complete"]),
            (["bad", "deep", "plate"], False),
        )
        again = self.run_it(script("cube"))
        self.assertEqual((again.drafted, again.errors), (1, ()))
        last = json.loads(
            (self.out / "history.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        )
        self.assertTrue(last["complete"])

    def test_a_mark_must_name_the_draft_it_marks(self) -> None:
        self.run_it(script("bad", "cube", "deep", "plate"))
        path = self.out / "marks.json"
        marks = json.loads(path.read_text(encoding="utf-8"))
        marks["marks"]["plate"]["draft"] = ""
        path.write_text(json.dumps(marks), encoding="utf-8")
        with self.assertRaises(MarksError):
            self.run_it([])


class TwoDraftsMeasured(RunFolder):
    """Drafted twice a brief: do the drafts differ where the first is wrong?"""

    def test_a_misread_the_second_draft_doesn_t_share_is_caught(self) -> None:
        misread = plate()
        misread["items"][0]["length"] = {
            "value": 90,
            "unit": "mm",
            "from": {"assumed": "a misread"},
        }
        responses = [
            *script("bad"),  # it gave up: no second draft is made of it
            *script("cube", "cube"),
            *script("deep", "deep"),
            misread,
            plate(),
        ]
        run = self.run_it(responses, drafts=2)
        self.assertEqual(run.stopped, "")
        compared = run.two_drafts
        assert compared is not None
        # cube can't be made: a draft that ends its run as CAN'T is not compared.
        self.assertEqual((compared.compared, compared.wrong, compared.caught, compared.right, compared.false_alarms),
                         (2, 1, 1, 0, 0))  # fmt: skip
        found = json.loads(
            (self.out / "plate" / "differences.json").read_text(encoding="utf-8")
        )
        self.assertEqual([d["at"] for d in found], ["/items/0"])
        self.assertEqual(json.loads((self.out / "bad" / "differences.json").read_text(encoding="utf-8"))["compared"],
                         "no")  # fmt: skip
        self.assertIn(
            "Two drafts: compared 2; they differed on 1 of the 1 with a fact wrong",
            "\n".join(report_lines(run)),
        )
        again = self.run_it([], drafts=2)  # every reading on record: nothing drafted
        self.assertEqual((again.drafted, again.two_drafts), (0, compared))

    def test_the_second_draft_is_the_second_reader_s_on_its_own_provider(self) -> None:
        other = ScriptedProvider([*script("bad"), *script("cube", "deep"), plate()])
        run = run_set(self.keys, ScriptedProvider(script("bad", "cube", "deep", "plate")), self.out,
                      say=self.heard.append, drafts=2, second=other)  # fmt: skip
        self.assertEqual(run.stopped, "")
        self.assertTrue(
            all(
                "listed last sentence first" in r.messages[0].content
                for r in other.requests
            )
        )
        recorded = json.loads((self.out / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(
            recorded["second_writer"], SpecWriter(second=True).prompt_version
        )

    def test_one_draft_or_two_is_another_measurement(self) -> None:
        self.run_it([*script("bad"), *script("cube", "cube"), *script("deep", "deep"), plate(), plate()],
                    drafts=2)  # fmt: skip
        with self.assertRaises(RunMismatchError):
            self.run_it([])


class TheCommand(unittest.TestCase):
    def test_forge_eval_spec_is_wired(self) -> None:
        args = build_parser().parse_args(
            ["eval-spec", "eval/blind/set1", "--only", "a", "--only", "b"]
        )
        self.assertEqual((args.handler.__name__, args.set, args.only, args.max_calls),
                         ("command_eval_spec", "eval/blind/set1", ["a", "b"], 200))  # fmt: skip


if __name__ == "__main__":
    unittest.main()
