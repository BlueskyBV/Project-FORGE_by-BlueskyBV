"""V2: what the corpus's third run found (docs/V2-stage4.md, 14.9).

- **A part drawn to its limit is within it, in every file:** the stepper
  plate, "so the part is 14 mm tall overall", 14 mm tall, passed on the
  B-rep and was held on its STL, known only to within 0.0055 mm. A limit is
  the part's, judged on the B-rep as exactly as it is made; a file is judged
  as a view of that part, within its own tolerance of the limit.
- **A coordinate below zero can be used in a formula:** the instrument
  bracket's holes "at x = -32 and x = 42" were refused, every formula of a
  number written with its minus ("42 mm - -32 mm") or without it ("42 mm +
  32 mm") read as not in the brief. A minus on a number is read as the
  brief's own sign first; a coordinate with no unit, used for how far, as
  one with a unit is, the sign said to differ.
- **A part's turn can't be listed as not modelled:** "a block turned 30
  degrees about the vertical axis" was built unturned, as a dome "flat side
  up" was (14.8): drafted, or said in ``unable``.
- **Questions nobody needed,** each still asked where the spec doesn't hold
  it: three balls in a row drawn as one turned outline of three arcs (A03);
  a plus sign of "two bars crossing" drawn as one outline (A08); "one pin
  hole through both ears", two ears (the clevis); "a cross hole right
  through both walls" of a tube; "an M8 hex nut ... with an 8 mm hole", the
  thread's own size; a pulley "revolved from its half-section".

The drafts are the run's own (tests/fixtures/corpus_third_run.json).
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forge_roles.spec_writer import read_answer
from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.citations import Follows, check_quantity
from forge_spec.derived import check_formula
from forge_units import Q
from v2_drafts import choose, cite, draft, made_of, mm, said
from v2_occ import needs_occ

RUN = json.loads((Path(__file__).resolve().parent / "fixtures" / "corpus_third_run.json").read_text(encoding="utf-8"))


def _run(key: str, *, brief: str | None = None) -> tuple[Any, dict[str, Any]]:
    """A draft of the run's, against its brief (or one changed word for word, its words numbered as before)."""
    found = RUN["drafts"][key]
    return number_words(brief or found["brief"]), read_answer(copy.deepcopy(found["answer"]))


def _problems(b: Any, d: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in check_draft(b, d).problems]


def _asked(word: str, sentence: int = 1) -> tuple[str, str]:
    return ("question", f"the brief says {word!r} (sentence {sentence}); nothing in the spec uses it")


class QuestionsNobodyNeeded(unittest.TestCase):
    def test_each_draft_of_the_run_asks_nothing(self) -> None:
        for key in ("A03", "A08", "zoo2_clevis", "zoo2_tube_cross_pin", "zoo_hex_nut", "zoo2_pulley"):
            with self.subTest(key=key):
                self.assertEqual(_problems(*_run(key)), [])

    def test_balls_and_bars_counted_on_the_outline(self) -> None:
        # Three arcs, three balls; four is asked. A plus of two bars has four inside corners; three bars, asked.
        brief = RUN["drafts"]["A03"]["brief"].replace("Three", "Four")
        self.assertIn(_asked("Four"), _problems(*_run("A03", brief=brief)))
        brief = RUN["drafts"]["A08"]["brief"].replace("two bars", "three bars")
        self.assertIn(_asked("three"), _problems(*_run("A08", brief=brief)))

    def test_the_ears_a_hole_goes_through(self) -> None:
        b, d = _run("zoo2_clevis")
        d["items"] = [i for i in d["items"] if i["id"] != "ear_right"]
        self.assertIn(_asked("both"), _problems(b, d))

    def test_a_metric_size_that_is_a_thread_s_own(self) -> None:
        # A spacer's M8 is a screw's that passes through it: an 8 mm hole is none of that size's own, and asked.
        brief = RUN["drafts"]["zoo_hex_nut"]["brief"].replace("hex nut", "hex spacer")
        self.assertIn(_asked("M8"), _problems(*_run("zoo_hex_nut", brief=brief)))


class APartsTurn(unittest.TestCase):
    def test_cant_be_listed_as_not_modelled(self) -> None:
        self.assertIn(("fault", "not_modelled can't hold which way the part sits ('turned 30 degrees'): the part "
                       "would be built some other way. Draft it, or say in unable that Forge can't make it so yet"),
                      _problems(*_run("zoo2_rotated_block")))  # fmt: skip


BRACKET = "Four holes at x = -32 and x = 42, y = 32 and y = -32, on a plate."


class CoordinatesBelowZero(unittest.TestCase):
    def test_in_a_formula(self) -> None:
        b = number_words(BRACKET)
        words = (*cite(b, "-32", 1), *cite(b, "42"))
        for formula, target in (("42 mm - -32 mm", 74), ("42 mm - (-32 mm)", 74), ("(-32 mm + 42 mm) / 2", 5),
                                ("42 mm + 32 mm", 74)):  # fmt: skip
            with self.subTest(formula=formula):
                found = check_formula(Q(target, "mm"), formula, words, b)
                self.assertTrue(found.ok, found.message)
        # Written with its sign, it is the brief's; taken the other way, said so.
        signed = check_formula(Q(5, "mm"), "(-32 mm + 42 mm) / 2", words, b)
        self.assertFalse(any("sign differs" in m for m in signed.unit_assumed))
        magnitude = check_formula(Q(74, "mm"), "42 mm + 32 mm", words, b)
        self.assertTrue(any("sign differs" in m for m in magnitude.unit_assumed))
        # A number not in the brief at all is still refused.
        self.assertFalse(check_formula(Q(75, "mm"), "42 mm + 33 mm", words, b).ok)

    def test_cited_as_a_value(self) -> None:
        b = number_words(BRACKET)
        found = check_quantity(Q(32, "mm"), b, cite(b, "-32", 1))
        self.assertIs(found.follows, Follows.UNIT_NOT_STATED)
        self.assertIn("the sign differs", found.message)
        self.assertIs(check_quantity(Q(-32, "mm"), b, cite(b, "-32", 1)).follows, Follows.UNIT_NOT_STATED)
        self.assertIs(check_quantity(Q(31, "mm"), b, cite(b, "-32", 1)).follows, Follows.NO)
        # A size the person gave with its unit is as before: "15 mm" for -15 mm, its sign said to differ.
        b = number_words("A hole 15 mm from the edge.")
        self.assertIs(check_quantity(Q(-15, "mm"), b, cite(b, "15 mm")).follows, Follows.YES_WITH_CAVEAT)


PLATE = ("A PLA plate 60 mm long, 40 mm wide and 8 mm thick, with a boss 20 mm in diameter standing {proud:g} mm proud "
         "of its top, so the part is 14 mm tall overall.")  # fmt: skip


def _plate(proud: float = 6) -> tuple[Any, dict[str, Any]]:
    """The plate, its boss as the brief says (a brief that says 6.2 mm and 14 mm overall: the part is past its
    limit)."""
    b = number_words(PLATE.format(proud=proud))
    d = draft("plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm long"),
         "width": mm(b, 40, "40 mm wide"), "height": mm(b, 8, "8 mm thick")},
        {"id": "boss", "kind": "boss", "words": cite(b, f"a boss 20 mm in diameter standing {proud:g} mm proud of its top"),
         "on": {"item": "plate", "face": "+z"}, "diameter": mm(b, 20, "20 mm in diameter"),
         "height": mm(b, proud, f"{proud:g} mm proud"),
         "place": {"x": {"centred": {"assumed": "the middle"}}, "y": {"centred": {"assumed": "the middle"}}}},
    ], material=made_of(b, "PLA"))  # fmt: skip
    d["requirements"]["limits"] = [{"of": choose("z", said(b, "tall overall")),
                                    "at_least": mm(b, 14, "14 mm tall overall"),
                                    "at_most": mm(b, 14, "14 mm tall overall")}]  # fmt: skip
    return b, d


def _limits_on_views(b: Any, d: dict[str, Any]) -> dict[str, str]:
    """The limit's verdict on the part's B-rep and on its STL, as ``forge build`` writes and judges it."""
    from forge_checks.judge import Judge
    from forge_checks.mesh import Mesh, MeshView
    from forge_checks.readers import read_stl
    from forge_checks.view import ViewProxy
    from forge_cli.build import export_tolerance
    from forge_occ.export import mesh_part, stl_bytes
    from forge_occ.planned import build_plan
    from forge_occ.view import BrepView
    from forge_plan import plan
    from forge_spec.lock import lock

    confirmed = lock(check_draft(b, d), b, by="draft", strict=False)
    shape = build_plan(plan(confirmed)).result.shape
    judge = Judge.of(confirmed.spec)
    tolerance = export_tolerance(judge.suite)
    meshed = mesh_part(shape, tolerance)
    stl = read_stl(stl_bytes(meshed.mesh)).triangles
    view = ViewProxy(MeshView(Mesh.from_triangles(stl), source="mesh-file", deflection=tolerance.linear))
    found = {"B-rep": judge.view(ViewProxy(BrepView(shape)), "B-rep", 1), "STL": judge.view(view, "STL", 1)}
    return {name: judged.limits[0].verdict.value for name, judged in found.items()}


@needs_occ
class APartDrawnToItsLimit(unittest.TestCase):
    def test_is_within_it_on_the_b_rep_and_its_files(self) -> None:
        b, d = _plate()
        self.assertEqual(_problems(b, d), [])
        self.assertEqual(_limits_on_views(b, d), {"B-rep": "pass", "STL": "pass"})

    def test_one_past_it_fails_on_both(self) -> None:
        b, d = _plate(proud=6.2)
        self.assertEqual(_limits_on_views(b, d), {"B-rep": "fail", "STL": "fail"})


if __name__ == "__main__":
    unittest.main()
