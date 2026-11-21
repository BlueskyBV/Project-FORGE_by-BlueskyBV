"""A part as drafted that comes apart, said before it is built and when it is (forge_occ.apart; V2-stage4b-0c.md, revision 20).

- **Built:** generated part 5468 (two holes through everything from a
  dome's surface out round a boss on its flat face, cutting it off) ends
  CAN'T, naming the cut and what it cuts off, not UNABLE.
- **Before it is built:** ``forge spec`` builds a spec with nothing left
  to settle once, and ends CAN'T on 5468 before any code is shown; a spec
  that builds is confirmed as ever.
- **OpenCascade's misreading isn't the spec's:** a second solid where the
  spec has no material (held-out seed 10517's plug, kept beside the part
  as OpenCascade 7.9.3 kept it) is not said, and the gap stands.
- **Said in the person's terms:** what is cut off whole, and a piece of
  what is cut off.
- **A cut through the next face in a replayed corpus** is given how deep it
  goes by the preview, and locks; one the preview can't find is an UNABLE,
  not a crash; Forge's own fault on one brief is that brief's error, and
  the run goes on.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from v2_occ import needs_occ


def _case_5468() -> Any:
    """Generated part 5468 as the generator made it before it refused it (tests/v2_regressions.py's ``REFUSED``)."""
    from forge_eval.generator import render
    from v2_regressions import REFUSED

    return render(REFUSED[5468][2], strict=False)


def _locked(case: Any) -> Any:
    from forge_cli.spec import _resolved
    from forge_eval.generator import draft_of
    from forge_spec import number_words
    from forge_spec.checks import check_draft
    from forge_spec.lock import lock

    numbered = number_words(case.brief)
    report = _resolved(numbered, check_draft(numbered, draft_of(case.items), strict=False), False)
    assert not report.problems, [p.message for p in report.problems]
    return lock(report, numbered, by="draft", strict=False)


class SaidInThePersonsTerms(unittest.TestCase):
    def test_what_it_cuts_off(self) -> None:
        from forge_occ.apart import Apart

        self.assertEqual(Apart("i1", 2, ("i0",)).message(),
                         "i1 would cut i0 off the part: as drafted it comes apart into 2 pieces, and a part is one "
                         "piece")  # fmt: skip
        self.assertEqual(Apart("slot", 3, ("a", "b"), ("body",)).message().split(":")[0],
                         "slot would cut a, b and a piece of body off the part")  # fmt: skip
        self.assertTrue(Apart("cut", 2, ()).message().startswith("cut would cut the part apart:"))

    def test_only_the_builds_own_refusal(self) -> None:
        from forge_occ.apart import split_refusal

        self.assertTrue(split_refusal({"detail": {"step": "i1.cut", "solids": 2}}))
        self.assertFalse(split_refusal({"detail": {"step": "i1.cut"}}))
        self.assertFalse(split_refusal({"detail": {"step": "i1.cut", "solids": 1}}))


@needs_occ
class BuiltItEndsCant(unittest.TestCase):
    def test_5468(self) -> None:
        from forge_cli.build import run_build
        from forge_cli.spec import _write_confirmed

        confirmed = _locked(_case_5468())
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "run"
            _write_confirmed(run, confirmed, None)
            said: list[str] = []
            out = Path(folder) / "build"
            run_build(run, out=out, sealer=None, say=said.append, seed=1, formats=("stl",))
            verdict = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
            shown = (out / "verdict.md").read_text(encoding="utf-8")
        self.assertIn("## Why it can't be made", shown)
        self.assertIn("## What the build refused", shown)
        self.assertNotIn("## The gap", shown)
        self.assertEqual(verdict["ending"], "CAN'T", said)
        self.assertIn("i1 would cut i0 off the part", verdict["cant"])
        self.assertEqual(verdict["gap"]["item"], "i1")  # the build's refusal is kept in the record
        self.assertIn("CAN'T: the shape can't be made: i1 would cut i0 off the part", "\n".join(said))


@needs_occ
class SaidBeforeItIsBuilt(unittest.TestCase):
    def test_5468_ends_cant_before_any_code(self) -> None:
        from forge_cli.spec import run_spec
        from forge_eval.generator import draft_of
        from forge_models import ScriptedProvider
        from test_v2_cli_spec import Person, Window

        case = _case_5468()
        person, window = Person("", "", "", ""), Window()
        outcome = run_spec(case.brief, ScriptedProvider([copy.deepcopy(draft_of(case.items))]), ask=person.ask,
                           say=person.say, private=window, code=lambda: "ABC-234", two_drafts="never")  # fmt: skip
        self.assertEqual(outcome.status, "refused", outcome.message)
        self.assertIn("CANT: i1 would cut i0 off the part", outcome.message)
        self.assertIsNone(outcome.confirmed)
        self.assertNotIn("ABC-234", window.said())  # no code shown: there is nothing to confirm
        assert outcome.report is not None
        self.assertEqual([(p.kind, p.at) for p in outcome.report.problems], [("cant", "/items/2")])

    def test_a_spec_that_builds_is_confirmed(self) -> None:
        from forge_cli.spec import run_spec
        from forge_models import ScriptedProvider
        from forge_spec.guide import EXAMPLE_BRIEF, EXAMPLE_DRAFT
        from test_v2_cli_spec import Person, Window

        person, window = Person("", "", ""), Window("abc 234")
        outcome = run_spec(EXAMPLE_BRIEF, ScriptedProvider([copy.deepcopy(dict(EXAMPLE_DRAFT))]), ask=person.ask,
                           say=person.say, private=window, code=lambda: "ABC-234", two_drafts="never")  # fmt: skip
        self.assertEqual(outcome.status, "confirmed", outcome.message)
        self.assertIn("holds together as one piece", person.said())


@needs_occ
class OpenCascadesMisreadingIsntTheSpecs(unittest.TestCase):
    def test_10517s_plug_kept_beside_the_part(self) -> None:
        """OpenCascade 7.9.3 kept a flush hole's plug beside the part (tests/test_v2_plan_alternatives.py): put back by
        hand, the plug is where the spec has air, so the part doesn't come apart, and the gap stands."""
        import dataclasses

        import v2_detection
        from forge_checks.judge import Judge
        from forge_eval.generator import render
        from forge_occ.apart import comes_apart
        from forge_occ.backend import OccBackend
        from forge_occ.make import compound
        from forge_occ.planned import PlannedBuild, Refusal
        from forge_plan import Gap
        from forge_plan.planner import _plan
        from forge_spec.placement import solve
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        from v2_regressions import REGRESSIONS

        class KeepsThePlug:
            def __init__(self, real: Any) -> None:
                self.real = real

            def build(self, document: Any, component: str, **options: Any) -> Any:
                result = self.real.build(document, component, **options)
                made = result.products
                plug = BRepAlgoAPI_Common(made["i4.cut"].shape, made["i5.0.bore"].shape).Shape()
                return dataclasses.replace(result, shape=compound([result.shape, plug]))

        spec = v2_detection._spec(render(REGRESSIONS[10517][1]).items)
        planned = _plan(spec, solve(spec), digest=None)
        flush = dict.fromkeys(("i0", "i1", "i2", "i4", "i5"), 1)
        refusal = Refusal("i5", "flush", "i5.cut", {"code": "OC1000_OCC", "message": "2 solids after it",
                                                    "detail": {"step": "i5.cut", "solids": 2}})  # fmt: skip
        built = PlannedBuild(None, flush, (refusal,), Gap("i5", "every way left it in two solids"), 1)
        backend = KeepsThePlug(OccBackend())
        self.assertEqual(len(__import__("forge_occ.occt", fromlist=["solids"]).solids(
            backend.build(planned.written(flush).document, "part").shape)), 2)  # fmt: skip
        self.assertIsNone(comes_apart(planned, built, Judge.of(spec), backend=backend))


class AReplayedCorpusThroughTheNextFace(unittest.TestCase):
    def _one(self, make: Any, built: Any = None) -> Any:
        from forge_cli.eval_corpus import Brief, _one
        from test_v2_plan_throughall import _TEXT
        from test_v2_plan_throughnext import _draft

        with tempfile.TemporaryDirectory() as folder:
            where = Path(folder) / "B1"
            where.mkdir()
            (where / "record.json").write_text(json.dumps({"brief": _TEXT}), encoding="utf-8")
            (where / "answer.json").write_text(json.dumps(_draft(make)), encoding="utf-8")
            with mock.patch("forge_cli.eval_corpus._built", built or mock.DEFAULT) as stage:
                found = _one(Brief("B1", _TEXT), None, where, False)
            return found, stage

    @needs_occ
    def test_found_by_the_preview_it_locks(self) -> None:
        from forge_cli.eval_corpus import Ended
        from forge_spec.lock import lock
        from forge_spec.wire import to_wire
        from test_v2_plan_throughnext import CASES

        locked: list[Any] = []

        def built(brief: Any, numbered: Any, report: Any, *_: Any) -> Any:
            locked.append(lock(report, numbered, by="draft", strict=False))
            return Ended(brief.id, "BUILT TO DRAFT", "locked", False)

        found, _ = self._one(CASES["a solid box"][0], built)
        self.assertEqual(found.ending, "BUILT TO DRAFT")
        (confirmed,) = locked
        (hole,) = (item for item in to_wire(confirmed.spec)["items"] if item["id"] == "hole")
        self.assertAlmostEqual(hole["depth"]["reaches"], 30.0, places=6)

    @needs_occ
    def test_one_it_cant_find_is_unable(self) -> None:
        from test_v2_plan_throughnext import _box, _hole, _next, _row, _under

        make = lambda b: [_box(b), _under(b, d=8.0, x=-10.0), _row(_hole(b, _next(), d=4.0))]  # noqa: E731
        found, stage = self._one(make)
        self.assertEqual(found.ending, "UNABLE")
        self.assertIn("different depths", found.why)
        stage.assert_not_called()

    def test_forges_own_fault_is_that_briefs_error(self) -> None:
        from forge_cli.eval_corpus import Brief, run_briefs

        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for name in ("B1", "B2"):
                (out / name).mkdir()
                (out / name / "record.json").write_text(json.dumps({"brief": "a"}), encoding="utf-8")
            calls: list[str] = []

            def one(brief: Any, *_: Any) -> Any:
                from forge_cli.eval_corpus import Ended

                calls.append(brief.id)
                if brief.id == "B1":
                    raise RuntimeError("a stage's own fault")
                return Ended(brief.id, "CAN'T", "as it is", False)

            with mock.patch("forge_cli.eval_corpus._one", one):
                ended, stopped = run_briefs([Brief("B1", "a"), Brief("B2", "b")], None, out, strict=False,
                                            say=lambda _: None)  # fmt: skip
            self.assertEqual((calls, stopped), (["B1", "B2"], ""))
            self.assertEqual([(e.id, e.ending) for e in ended], [("B1", "error"), ("B2", "CAN'T")])
            self.assertIn("RuntimeError: a stage's own fault", ended[0].why)
            self.assertIn("traceback", json.loads((out / "B1" / "error.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
