"""V2 stage 1: findings of the fifth adversarial review, pinned.

Briefs written for these tests, never from a blind set.

The person's answers:

- naming a material the first draft didn't give makes the requirement,
  never a crash;
- a note may hold several sentences, and the other answers still cite their
  own words; a name with a full stop or semicolon inside is asked again;
- a name is kept exactly as given, a closing bracket and all, without the
  quote marks round it;
- a field is asked once, even when the second draft differs on a value this
  draft assumed, and two answers to one field are refused;
- what the person kept where the drafts differ holds through a redraft.

The material (plan, 4.1):

- it is named by its own words: a grade's number is part of the name, a
  size or a count is not, and it is named in one sentence;
- no word naming a material goes unrecorded: the part's is
  requirements.material, another thing's is listed as not modelled, which
  only a part with a material of its own may do; "carbon fibre" is one;
- an inch mark is no quotation; a sentence the person says says nothing
  records the other thing's material it names.

Two drafts compared (forge_spec.compare):

- roundings and chamfers by the edges they touch, on the item they touch: one
  item on all edges is three on vertical, top and bottom, and two bosses as
  a pattern with one rounding are two bosses with one each; a hollow by its
  openings; neither differs only because the item it is on does;
- a size that differs moves nothing else; a corner radius, a tab's end, a
  region's words differ; a counterbore entered from the other side, and
  letters turned over, are other parts;
- one shape built from other kinds (a post or a block, a boss or a rod, a
  tube or a rod with a hole down it, a hole or a round pocket) is one; a hole
  right through is one wherever it enters; holes round a rod at 45 degrees
  are where they are, however the angle is written;
- what differs is said of the right item, and a material differs by its
  name, not its case; drafts that can't be made aren't compared.

The run (``forge spec``):

- a second draft that fails is only "nothing to compare": the first is kept,
  and an automatic run stops for want of the second's check;
- stopping during the first draft never waits for the second, which is
  cancelled; the first draft's first call has the budget first, and two
  drafts in flight can't both spend what only one call's worth allows;
- whatever is typed at the code or an option prompt is only a wrong answer,
  never a crash; answers written down beforehand find their questions by
  pointer and text; what the run spent is written however it ended; and two
  runs never share a folder.

The measurement (``forge eval-spec``):

- both drafts spend one budget; how the model was asked to run is part of
  what a run measures; a folder of drafts with no run.json is refused;
- a brief an error stopped partway is drafted afresh, and says so; a brief
  whose first draft gave up gets no second; briefs, not drafts, are counted.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from forge_cli.eval_spec import RunMismatchError, report_lines, run_set
from forge_cli.spec import SharedBudget, _fresh, run_spec
from forge_models import (
    Budget,
    BudgetExceededError,
    ModelRequest,
    ScriptedProvider,
    TransientError,
    Usage,
    user,
)
from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.compare import differences
from forge_spec.questions import Answer, AnswerError, apply_answers, questions

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_spec.guide import EXAMPLE_BRIEF
from test_v2_cli_spec import CODE, Person, Window, example
from test_v2_eval_spec import RunFolder, bad_draft, script
from v2_drafts import assumed, cite, draft, made_of, mm

PLATE = (
    "A PLA plate 60 mm long, 40 mm wide and 5 mm thick, with a 6 mm hole through it."
)
P = number_words(PLATE)
#: The same plate, its material not named.
Q = number_words(PLATE.replace("A PLA plate", "A plate"))
_GIVEN = object()


def plate(*, material: Any = _GIVEN, diameter: dict[str, Any] | None = None, depth: dict[str, Any] | None = None,
          brief: Any = P) -> dict[str, Any]:  # fmt: skip
    """The plate drafted: its material as the brief names it, unless a test gives another (or None)."""
    if material is _GIVEN:
        material = made_of(brief, "PLA") if brief is P else None
    return draft("plate", [
        {"id": "plate", "kind": "block", "words": cite(brief, "plate"), "length": mm(brief, 60, "60 mm"),
         "width": mm(brief, 40, "40 mm"), "height": mm(brief, 5, "5 mm")},
        {"id": "h", "kind": "hole", "words": cite(brief, "hole"), "on": {"item": "plate", "face": "+z"},
         "diameter": diameter or mm(brief, 6, "6 mm"),
         "depth": depth or {"through": True, "from": {"words": cite(brief, "through")}},
         "place": {"x": {"centred": assumed("for the test")}, "y": {"centred": assumed("for the test")}}},
    ], material=material)  # fmt: skip


def asked(round_: tuple[Any, ...], at: str) -> Any:
    (found,) = [q for q in round_ if q.at == at]
    return found


class TheMaterialNamedInAnAnswer(unittest.TestCase):
    def test_where_the_first_draft_gave_none(self) -> None:
        usual = {"text": "PLA", "from": {"assumed": "the usual"}}
        mine, theirs = (
            check_draft(Q, plate(brief=Q)),
            check_draft(Q, plate(brief=Q, material=usual)),
        )
        round_ = questions(mine, differences(mine, theirs))
        q = asked(round_, "/requirements/material")
        out = apply_answers(Q, plate(brief=Q), round_, [Answer(q.id, 0, text="PLA")])
        self.assertEqual(out.draft["requirements"]["material"]["text"], "PLA")
        self.assertEqual(check_draft(out.brief, out.draft).problems, ())

    def test_kept_exactly_as_given(self) -> None:
        d = plate(brief=Q, material={"text": "PLA", "from": {"assumed": "the usual"}})
        round_ = questions(check_draft(Q, d))
        q = asked(round_, "/requirements/material")
        for given, kept in (("PETG-CF (carbon fibre)", "PETG-CF (carbon fibre)"), ('"PETG"', "PETG"),
                            ("aluminium 6061-T6.", "aluminium 6061-T6")):  # fmt: skip
            out = apply_answers(Q, d, round_, [Answer(q.id, 0, text=given)])
            self.assertEqual(out.draft["requirements"]["material"]["text"], kept)
            self.assertEqual(check_draft(out.brief, out.draft).problems, (), given)

    def test_one_sentence_or_asked_again(self) -> None:
        d = plate(brief=Q, material={"text": "PLA", "from": {"assumed": "the usual"}})
        round_ = questions(check_draft(Q, d))
        q = asked(round_, "/requirements/material")
        for given in ("PLA. ABS", "PETG; black"):
            with self.assertRaisesRegex(AnswerError, "one sentence"):
                apply_answers(Q, d, round_, [Answer(q.id, 0, text=given)])

    def test_a_name_never_holds_a_size_or_a_count(self) -> None:
        d = plate(brief=Q, material={"text": "PLA", "from": {"assumed": "the usual"}})
        round_ = questions(check_draft(Q, d))
        q = asked(round_, "/requirements/material")
        with self.assertRaisesRegex(
            AnswerError, "'3 mm' is a measure, not part of a material's name"
        ):
            apply_answers(Q, d, round_, [Answer(q.id, 0, text="PETG, 3 mm walls")])


def bar(brief: Any, **options: Any) -> dict[str, Any]:
    return draft("bar", [{"id": "bar", "kind": "block", "words": cite(brief, "bar"), "length": mm(brief, 60, "60 mm"),
                          "width": mm(brief, 20, "20 mm"), "height": mm(brief, 5, "5 mm")}], **options)  # fmt: skip


def faults(brief: Any, d: dict[str, Any]) -> list[str]:
    return [p.message for p in check_draft(brief, d).problems if p.kind == "fault"]


class TheMaterialIsNamedByItsOwnWords(unittest.TestCase):
    def test_a_grade_is_part_of_the_name(self) -> None:
        for name in (
            "aluminium 6061-T6",
            "316L stainless",
            "Grade 5 titanium",
            "carbon fibre PETG",
        ):
            b = number_words(f"A {name} bar 60 mm long, 20 mm wide and 5 mm thick.")
            self.assertEqual(faults(b, bar(b, material=made_of(b, name))), [], name)

    def test_a_size_or_a_count_is_not(self) -> None:
        b = number_words("A steel bar 60 mm long, 20 mm wide and 5 mm thick.")
        self.assertIn("'60 mm' is a measure, not part of a material's name: cite only the material's own words, and "
                      "give the measure or count its own value", faults(b, bar(b, material=made_of(b, "steel bar 60 mm"))))  # fmt: skip
        two = number_words(
            "Two PLA bars. Each bar is 60 mm long, 20 mm wide and 5 mm thick."
        )
        found = faults(two, bar(two, material=made_of(two, "Two PLA")))
        self.assertTrue(any("'Two' is a count" in f for f in found), found)

    def test_in_one_sentence(self) -> None:
        b = number_words(
            "A bar 60 mm long, 20 mm wide and 5 mm thick in PETG. Two holes go through it."
        )
        self.assertIn("a material is named in one sentence: cite only its own words",
                      faults(b, bar(b, material=made_of(b, "PETG Two"))))  # fmt: skip


class NoMaterialGoesUnrecorded(unittest.TestCase):
    BRIEF = number_words(
        "A bar 60 mm long, 20 mm wide and 5 mm thick. It is made of PETG."
    )

    def test_not_in_a_silent_sentence_nor_an_items_words_nor_anywhere(self) -> None:
        b = self.BRIEF
        unrecorded = "'PETG' (word 16) names a material the spec doesn't record"
        for d in (bar(b, silent=[{"sentence": 1, "reason": "how it is made"}]), bar(b)):
            for strict in (False, True):
                self.assertTrue(any(f.startswith(unrecorded) for f in [p.message for p in check_draft(b, d, strict=strict).problems]))  # fmt: skip
        d = bar(b)
        d["items"][0]["words"] += cite(b, "made of PETG")
        self.assertTrue(any(f.startswith(unrecorded) for f in faults(b, d)))

    def test_another_things_material_is_left_out_once_the_part_has_its_own(
        self,
    ) -> None:
        b = number_words(
            "A PLA bar 60 mm long, 20 mm wide and 5 mm thick. It slides on a steel rod."
        )
        other = [{"words": cite(b, "steel"), "reason": "the rod it slides on"}]
        silent = [{"sentence": 1, "reason": "what it is for"}]
        self.assertEqual(
            faults(
                b, bar(b, material=made_of(b, "PLA"), not_modelled=other, silent=silent)
            ),
            [],
        )
        self.assertIn("'steel' names a material: give the part's as requirements.material, citing its words; another "
                      "thing's may be left out here once the part has one of its own",
                      faults(b, bar(b, not_modelled=other, silent=silent)))  # fmt: skip

    def test_two_words_may_name_one(self) -> None:
        b = number_words("A carbon fibre bar 60 mm long, 20 mm wide and 5 mm thick.")
        self.assertTrue(
            any("'carbon' (word 1) names a material" in f for f in faults(b, bar(b)))
        )

    def test_a_sentence_answered_as_saying_nothing_records_whose_it_is(self) -> None:
        b = number_words(
            "A PLA bar 60 mm long, 20 mm wide and 5 mm thick. It sits next to a steel shaft."
        )
        d = bar(b, material=made_of(b, "PLA"))
        round_ = questions(check_draft(b, d))
        q = asked(round_, "/brief/sentences/1")
        silent = next(n for n, o in enumerate(q.options) if o.kind == "silent")
        out = apply_answers(b, d, round_, [Answer(q.id, silent)])
        self.assertEqual(check_draft(out.brief, out.draft).problems, ())
        self.assertEqual(
            [e["words"] for e in out.draft["not_modelled"]], [cite(b, "steel")]
        )


class AnInchMarkIsNoQuotation(unittest.TestCase):
    def test_a_material_between_inch_sizes(self) -> None:
        b = number_words('A 2" wide PLA bar, 6" long.')
        d = draft("bar", [{"id": "bar", "kind": "block", "words": cite(b, "bar"),
                           "length": {"value": 6, "unit": "in", "from": {"words": cite(b, '6" long')}},
                           "width": {"value": 2, "unit": "in", "from": {"words": cite(b, '2" wide')}},
                           "height": {"value": 5, "unit": "mm", "from": {"assumed": "a thin bar"}}}],
                  material=made_of(b, "PLA"))  # fmt: skip
        self.assertEqual(faults(b, d), [])


class ANoteOfSeveralSentences(unittest.TestCase):
    def test_leaves_the_other_answers_their_own_words(self) -> None:
        d = plate(depth={"value": 3, "unit": "mm", "from": {"assumed": "for the test"}})
        round_ = questions(check_draft(P, d))
        place, depth = round_[0], asked(round_, "/items/1/depth")
        for answers in ([Answer(place.id, 0, text="Put it near the left end. Not centred."), Answer(depth.id, 1, number=2)],
                        [Answer(depth.id, 1, number=2), Answer(place.id, 0, text="Put it near the left end. Not centred.")]):  # fmt: skip
            out = apply_answers(P, d, round_, answers)
            cited = out.draft["items"][1]["depth"]["from"]["words"]
            self.assertEqual([out.brief.word(w).text for w in cited], ["2", "mm"])
            self.assertEqual(
                out.notes,
                ("Note from the person: Put it near the left end. Not centred.",),
            )


class OneFieldOneAnswer(unittest.TestCase):
    def test_a_difference_on_an_assumed_value_is_asked_once(self) -> None:
        mine = check_draft(
            P,
            plate(
                diameter={"value": 5, "unit": "mm", "from": {"assumed": "for the test"}}
            ),
        )
        theirs = check_draft(
            P,
            plate(
                diameter={"value": 6, "unit": "mm", "from": {"assumed": "for the test"}}
            ),
        )
        round_ = questions(mine, differences(mine, theirs))
        q = asked(round_, "/items/1/diameter")
        self.assertEqual(q.kind, "question")
        self.assertIn("(this draft assumed it:", q.text)

    def test_two_answers_to_one_field_are_refused(self) -> None:
        d = plate(depth={"value": 3, "unit": "mm", "from": {"assumed": "for the test"}})
        report = check_draft(P, d)
        (depth,) = [q for q in questions(report) if q.at == "/items/1/depth"]
        twin = type(depth)("q9", "question", depth.at, "asked again", depth.options)
        with self.assertRaisesRegex(AnswerError, "both answer /items/1/depth"):
            apply_answers(
                P,
                d,
                (depth, twin),
                [Answer(depth.id, 1, number=2), Answer("q9", 1, number=4)],
            )


class AKeptReadingHoldsThroughARedraft(unittest.TestCase):
    def test_it_is_said_as_an_answer_when_a_note_asks_for_a_redraft(self) -> None:
        mine = check_draft(
            P,
            plate(
                diameter={"value": 5, "unit": "mm", "from": {"assumed": "for the test"}}
            ),
        )
        theirs = check_draft(
            P,
            plate(
                diameter={"value": 6, "unit": "mm", "from": {"assumed": "for the test"}}
            ),
        )
        round_ = questions(mine, differences(mine, theirs))
        diameter = asked(round_, "/items/1/diameter")
        keep = next(n for n, o in enumerate(diameter.options) if o.kind == "keep")
        d = plate(
            diameter={"value": 5, "unit": "mm", "from": {"assumed": "for the test"}}
        )
        alone = apply_answers(P, d, round_, [Answer(diameter.id, keep)])
        self.assertEqual(
            alone.brief.text, P.text
        )  # kept, with nothing to redraft: nothing to say
        place = round_[-1]
        noted = apply_answers(
            P,
            d,
            round_,
            [Answer(diameter.id, keep), Answer(place.id, 0, text="Move it left.")],
        )
        self.assertIn("Answer about h diameter: 5 mm.", noted.brief.text)


PART = number_words("A part.")


def given(value: float, unit: str = "mm") -> dict[str, Any]:
    return {"value": value, "unit": unit, "from": {"assumed": "for the test"}}


def thing(item_id: str, kind: str, **fields: Any) -> dict[str, Any]:
    return {"id": item_id, "kind": kind, "words": [1], **fields}


def chose(value: str) -> dict[str, Any]:
    return {"choose": value, "from": {"assumed": "for the test"}}


def centred() -> dict[str, Any]:
    return {"centred": {"assumed": "for the test"}}


def slab(
    length: float = 80, width: float = 40, height: float = 6, item_id: str = "plate"
) -> dict[str, Any]:
    return thing(
        item_id, "block", length=given(length), width=given(width), height=given(height)
    )


def compared(*drafts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    reports = []
    for items in drafts:
        report = check_draft(PART, draft("part", items))
        assert not report.needs_redraft, [p.message for p in report.problems]
        reports.append(report)
    return [(d.at, d.message) for d in differences(reports[0], reports[1])]


class RoundingsHollowsAndThreads(unittest.TestCase):
    def rounded(self, which: str, of: str = "plate") -> list[dict[str, Any]]:
        return [
            slab(),
            slab(10, 10, 10, "cube") | {"on": {"item": "plate", "face": "+z"}},
            thing(
                "r",
                "fillet",
                edges={"of": of, "which": which, "words": [1]},
                radius=given(2),
            ),
        ]

    def test_by_the_edges_they_touch_on_the_item_they_touch(self) -> None:
        self.assertEqual(compared(self.rounded("vertical"), self.rounded("top")),
                         [("/items/2/edges", "r rounds other edges in the second draft: check which the brief means")])  # fmt: skip
        self.assertNotEqual(
            compared(self.rounded("vertical"), self.rounded("vertical", "cube")), []
        )
        split = [slab(), *(thing(f"r{n}", "fillet", edges={"of": "plate", "which": w, "words": [1]}, radius=given(2))
                           for n, w in enumerate(("vertical", "top", "bottom")))]  # fmt: skip
        self.assertEqual(compared([slab(), thing("r", "fillet", edges={"of": "plate", "which": "all", "words": [1]},
                                                 radius=given(2))], split), [])  # fmt: skip

    def test_a_pattern_and_its_copies_alike(self) -> None:
        row = {"x": centred(), "y": centred(), "pattern": {"row": {"axis": chose("x"), "pitch": given(40),
                                                                   "count": {"count": 2, "from": {"assumed": "t"}}}}}  # fmt: skip
        patterned = [slab(), thing("bosses", "boss", on={"item": "plate", "face": "+z"}, diameter=given(8), height=given(5),
                                   place=row),
                     thing("r", "fillet", edges={"of": "bosses", "which": "top", "words": [1]}, radius=given(1))]  # fmt: skip
        separate = [slab(), *(thing(f"b{n}", "boss", on={"item": "plate", "face": "+z"}, diameter=given(8),
                                    height=given(5), place={"x": {"offset": given(x)}, "y": centred()})
                              for n, x in enumerate((-20, 20))),
                    *(thing(f"r{n}", "fillet", edges={"of": f"b{n}", "which": "top", "words": [1]}, radius=given(1))
                      for n in range(2))]  # fmt: skip
        self.assertEqual(compared(patterned, separate), [])

    def test_a_hollow_by_its_openings(self) -> None:
        def box(face: str) -> list[dict[str, Any]]:
            return [slab(60, 40, 30, "box"), thing("hollow", "shell", of="box", thickness=given(2),
                                                   open={"faces": [face], "from": {"assumed": "t"}})]  # fmt: skip

        self.assertNotEqual(compared(box("+z"), box("+x")), [])
        self.assertEqual(compared(box("+z"), box("+z")), [])

    def test_following_a_changed_item_is_no_difference_of_its_own(self) -> None:
        def rounded(length: float) -> list[dict[str, Any]]:
            return [slab(length), thing("r", "fillet", edges={"of": "plate", "which": "vertical", "words": [1]},
                                        radius=given(2))]  # fmt: skip

        self.assertEqual(compared(rounded(80), rounded(81)),
                         [("/items/0", "plate is 80 x 40 x 6 mm here, 81 x 40 x 6 mm in the second draft")])  # fmt: skip


class OneSizeMovesNothingElse(unittest.TestCase):
    def part(self, boss: float) -> list[dict[str, Any]]:
        return [slab(80, 30, 6),
                thing("boss", "boss", on={"item": "plate", "face": "+z"}, diameter=given(10), height=given(boss),
                      place={"x": centred(), "y": centred()}),
                thing("pk", "pocket", on={"item": "plate", "face": "-z"}, shape=chose("circle"), diameter=given(8),
                      depth=given(2), place={"x": {"offset": given(20)}, "y": centred()})]  # fmt: skip

    def test_only_the_boss(self) -> None:
        self.assertEqual(compared(self.part(10), self.part(11)),
                         [("/items/1", "boss is 10 x 10 x 10 mm here, 10 x 10 x 11 mm in the second draft")])  # fmt: skip

    def test_a_corner_a_tab_s_end_a_region_s_words(self) -> None:
        def pocket(radius: float) -> list[dict[str, Any]]:
            return [slab(), thing("pk", "pocket", on={"item": "plate", "face": "+z"}, shape=chose("rectangle"),
                                  length=given(20), width=given(10), corner_radius=given(radius), depth=given(2))]  # fmt: skip

        self.assertEqual(
            [at for at, _ in compared(pocket(1), pocket(4))], ["/items/1/corner_radius"]
        )

        def tab(end: str) -> list[dict[str, Any]]:
            return [slab(), thing("t", "tab", on={"item": "plate", "face": "+x"}, length=given(10), width=given(12),
                                  thickness=given(4), thickness_along=chose("z"), end=chose(end))]  # fmt: skip

        self.assertEqual(compared(tab("square"), tab("round")), [("/items/1/end", "t's end is square here, round in the second draft")])  # fmt: skip


class MirrorsAreOtherParts(unittest.TestCase):
    def test_a_counterbore_from_the_other_side(self) -> None:
        def bored(face: str) -> list[dict[str, Any]]:
            return [slab(), thing("h", "hole", on={"item": "plate", "face": face}, diameter=given(5),
                                  depth={"through": True, "from": {"assumed": "t"}},
                                  counterbore={"diameter": given(9), "depth": given(1)},
                                  place={"x": {"offset": given(10)}, "y": {"offset": given(5)}})]  # fmt: skip

        self.assertEqual(compared(bored("+z"), bored("-z")), [("/items/1/counterbore", "h's counterbore is on another side in the second draft")])  # fmt: skip

    def test_letters_turned_over(self) -> None:
        def lettered(face: str) -> list[dict[str, Any]]:
            return [slab(), thing("t", "text", on={"item": "plate", "face": face},
                                  text={"text": "FORGE", "from": {"assumed": "t"}}, height=given(5), depth=given(0.5),
                                  mode=chose("engrave"), place={"x": {"offset": given(10)}, "y": centred()})]  # fmt: skip

        self.assertNotEqual(compared(lettered("+z"), lettered("-z")), [])


class OneShapeFromOtherKinds(unittest.TestCase):
    def test_built_alike(self) -> None:
        on_top = {"item": "plate", "face": "+z"}
        pairs = [
            ([slab(), thing("p", "post", on=on_top, length=given(10), width=given(8), height=given(5))],
             [slab(), thing("p", "block", on=on_top, length=given(10), width=given(8), height=given(5))]),
            ([slab(), thing("b", "boss", on=on_top, diameter=given(8), height=given(5))],
             [slab(), thing("b", "cylinder", on=on_top, diameter=given(8), length=given(5))]),
            ([thing("t", "tube", outer_diameter=given(20), inner_diameter=given(10), length=given(30), axis=chose("z"))],
             [thing("t", "cylinder", diameter=given(20), length=given(30), axis=chose("z")),
              thing("h", "hole", on={"item": "t", "face": "+end"}, diameter=given(10),
                    depth={"through": True, "from": {"assumed": "t"}}, place={"x": centred(), "y": centred()})]),
            ([slab(), thing("h", "hole", on=on_top, diameter=given(8), depth={"through": True, "from": {"assumed": "t"}})],
             [slab(), thing("h", "pocket", on=on_top, shape=chose("circle"), diameter=given(8),
                            depth={"through": True, "from": {"assumed": "t"}})]),
        ]  # fmt: skip
        for mine, theirs in pairs:
            self.assertEqual(compared(mine, theirs), [], mine[-1]["kind"])

    def test_a_hole_right_through_wherever_it_enters(self) -> None:
        through = {"through": True, "from": {"assumed": "t"}}
        place = {"x": {"offset": given(10)}, "y": centred()}
        top = [
            slab(),
            thing(
                "h",
                "hole",
                on={"item": "plate", "face": "+z"},
                diameter=given(4),
                depth=through,
                place=place,
            ),
        ]
        bottom = [slab(), thing("h", "hole", on={"item": "plate", "face": "-z"}, diameter=given(4), depth=through,
                                place={"x": {"offset": given(10)}, "y": centred()})]  # fmt: skip
        self.assertEqual(compared(top, bottom), [])

    def test_holes_round_a_rod_at_45_degrees(self) -> None:
        def radial(start: float) -> list[dict[str, Any]]:
            return [thing("rod", "cylinder", diameter=given(20), length=given(40), axis=chose("z")),
                    thing("h", "hole", on={"item": "rod", "face": "side"}, diameter=given(4), depth=given(5),
                          place={"angle": given(start, "deg"), "pattern": {"circle": {"count": {"count": 4, "from": {"assumed": "t"}}}}})]  # fmt: skip

        self.assertEqual(compared(radial(45), radial(-45)), [])
        self.assertEqual(compared(radial(135), radial(-225)), [])


class WhatDiffersIsSaidRightly(unittest.TestCase):
    def test_a_narrow_hole_s_depth(self) -> None:
        def hole(depth: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                slab(80, 40, 20),
                thing(
                    "h",
                    "hole",
                    on={"item": "plate", "face": "+z"},
                    diameter=given(3),
                    depth=depth,
                ),
            ]

        self.assertEqual(compared(hole({"through": True, "from": {"assumed": "t"}}), hole(given(10))),
                         [("/items/1/depth", "h goes right through here, 10 mm deep in the second draft")])  # fmt: skip

    def test_a_material_by_its_name_not_its_case(self) -> None:
        mine = check_draft(
            PART,
            draft(
                "part", [slab()], material={"text": "PETG", "from": {"assumed": "t"}}
            ),
        )
        theirs = check_draft(
            PART,
            draft(
                "part", [slab()], material={"text": "petg ", "from": {"assumed": "t"}}
            ),
        )
        self.assertEqual(differences(mine, theirs), ())

    def test_drafts_that_can_t_be_made_aren_t_compared(self) -> None:
        rod = thing(
            "rod", "cylinder", diameter=given(10), length=given(50), axis=chose("z")
        )
        pocket = thing("p", "pocket", shape=chose("rectangle"), length=given(6), width=given(4), depth=given(2),
                       on={"item": "rod", "face": "side"})  # fmt: skip
        unable = check_draft(PART, draft("part", [rod, pocket]))
        self.assertEqual(
            [p.kind for p in unable.problems], ["unable"]
        )  # a pocket round a side isn't made yet
        with self.assertRaises(ValueError):
            differences(unable, unable)


class Slow(ScriptedProvider):
    """A scripted model that takes its time, or fails."""

    def __init__(
        self,
        replies: list[Any],
        seconds: float = 0.0,
        error: BaseException | None = None,
    ) -> None:
        super().__init__(replies)
        self.seconds, self.error = seconds, error

    def _send(self, request: Any) -> Any:
        time.sleep(self.seconds)
        if self.error is not None:
            raise self.error
        return super()._send(request)


def two(first: ScriptedProvider, second: ScriptedProvider, **options: Any) -> Any:
    return run_spec(EXAMPLE_BRIEF, first, ask=Person("", "", "").ask, say=Person().say, private=Window("ABC234"),
                    code=lambda: CODE, two_drafts="always", second=second, **options)  # fmt: skip


class ASecondDraftThatFails(unittest.TestCase):
    def test_leaves_the_first_and_the_run_goes_on(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            outcome = two(
                ScriptedProvider([example()]),
                Slow([], error=TransientError("the line dropped")),
                out=out,
            )
            self.assertEqual(outcome.status, "confirmed")
            self.assertTrue((out / "draft-1" / "calls.json").exists())
            self.assertIn(
                "MD1004",
                (out / "draft-1-second" / "refused.json").read_text(encoding="utf-8"),
            )
            self.assertTrue((out / "spent.json").exists())

    def test_stops_an_automatic_run(self) -> None:
        outcome = two(
            ScriptedProvider([example()]),
            Slow([], error=TransientError("the line dropped")),
            strict=True,
        )
        self.assertEqual(outcome.status, "questions")
        self.assertIn("the second draft failed (MD1004", outcome.message)


class StoppingNeverWaitsForTheSecondDraft(unittest.TestCase):
    def test_ctrl_c_during_the_first(self) -> None:
        second = Slow([example()], seconds=5.0)
        began = time.monotonic()
        outcome = two(Slow([], error=KeyboardInterrupt()), second)
        self.assertEqual(outcome.status, "stopped")
        self.assertLess(time.monotonic() - began, 2.0)


class OneBudgetForTwoDrafts(unittest.TestCase):
    def test_two_calls_in_flight_cant_both_pass_a_check_only_one_fits(self) -> None:
        budget = SharedBudget(Budget(max_calls=1, max_total_tokens=None))
        request = ModelRequest(
            system="", messages=(user("a brief"),), max_output_tokens=10
        )
        passed: list[str] = []
        gate = threading.Barrier(2)

        def call(name: str) -> None:
            gate.wait()
            try:
                budget.check_before(request)
                passed.append(name)
                time.sleep(0.05)
                budget.record(Usage(input_tokens=1, output_tokens=1))
            except BudgetExceededError:  # the one refused
                return

        threads = [threading.Thread(target=call, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((len(passed), budget.calls), (1, 1))

    def test_the_first_drafts_first_call_comes_first(self) -> None:
        budget = Budget(max_calls=1, max_total_tokens=None)
        first, second = (
            ScriptedProvider([example()], budget=budget),
            ScriptedProvider([example()]),
        )
        outcome = two(first, second)
        self.assertEqual(
            (outcome.status, len(first.requests), len(second.requests)),
            ("confirmed", 1, 0),
        )


class WhateverIsTyped(unittest.TestCase):
    def test_at_the_code_is_only_a_wrong_code(self) -> None:
        window = Window("\u00c4BC234", "ABC\u00b7234", "abc 234")
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=Person("", "", "").ask, say=Person().say,
                           private=window, code=lambda: CODE, two_drafts="never")  # fmt: skip
        self.assertEqual(outcome.status, "confirmed")
        self.assertEqual(window.said().count("That isn't the code."), 2)

    def test_at_an_option_is_asked_again(self) -> None:
        person = Person("\u00b9", "", "", "")
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([example()]), ask=person.ask, say=person.say,
                           private=Window("ABC234"), code=lambda: CODE, two_drafts="never")  # fmt: skip
        self.assertEqual(outcome.status, "confirmed")
        self.assertIn("Answer 1 to", person.said())


class RunFolders(unittest.TestCase):
    def test_two_runs_never_share_one(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            taken = Path(folder) / "spec-1-plate"
            taken.mkdir()
            self.assertEqual(_fresh(taken).name, "spec-1-plate-2")
            self.assertEqual(_fresh(Path(folder) / "spec-2-plate").name, "spec-2-plate")


class TheMeasurement(RunFolder):
    def test_both_drafts_spend_one_budget(self) -> None:
        first = ScriptedProvider(
            script("bad", "cube", "deep", "plate"),
            budget=Budget(max_calls=4, max_total_tokens=None),
        )
        second = ScriptedProvider(script("cube", "deep", "plate"))
        run = run_set(
            self.keys, first, self.out, say=self.heard.append, drafts=2, second=second
        )
        self.assertIs(first.budget, second.budget)
        self.assertEqual(first.budget.calls, 4)
        self.assertIn("model-call budget", run.stopped)

    def test_how_the_model_runs_is_part_of_what_it_measures(self) -> None:
        run_set(self.keys, ScriptedProvider(script("bad", "cube", "deep", "plate")), self.out, say=self.heard.append,
                settings={"effort": "high", "thinking": None})  # fmt: skip
        with self.assertRaisesRegex(RunMismatchError, "model_settings"):
            run_set(self.keys, ScriptedProvider([]), self.out, say=self.heard.append,
                    settings={"effort": "low", "thinking": None})  # fmt: skip

    def test_drafts_with_no_run_json_are_refused(self) -> None:
        self.run_it(script("bad", "cube", "deep", "plate"))
        (self.out / "run.json").unlink()
        with self.assertRaisesRegex(RunMismatchError, "no run.json"):
            self.run_it([])

    def test_a_brief_stopped_partway_is_drafted_afresh_and_says_so(self) -> None:
        self.run_it([bad_draft(), TransientError("the line dropped")])
        resumed = self.run_it(script("bad", "cube", "deep", "plate"))
        self.assertEqual(resumed.afresh, ("bad",))
        self.assertIn(
            "Afresh   : bad drafted again from the start",
            "\n".join(report_lines(resumed)),
        )
        record = (self.out / "bad" / "record.json").read_text(encoding="utf-8")
        self.assertIn('"after_interruption": 1', record)

    def test_a_brief_whose_first_draft_gave_up_gets_no_second(self) -> None:
        second = ScriptedProvider(script("cube", "deep", "plate"))
        run = run_set(self.keys, ScriptedProvider(script("bad", "cube", "deep", "plate")), self.out,
                      say=self.heard.append, drafts=2, second=second)  # fmt: skip
        self.assertEqual((run.stopped, len(second.requests)), ("", 3))
        self.assertEqual((run.drafted, run.reused), (4, 0))  # briefs, not drafts


if __name__ == "__main__":
    unittest.main()
