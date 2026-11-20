"""Parts once accepted and then held, built and judged now (V2-stage4b-0c.md, revision 19).

A rebate along a plate's edge, a groove right across a bar, a notch in its
corner: a straight side along the face's edge only opens the cut there
(place.md), so there is no wall on that side for the cut's size and place
to be measured from. The spec accepted them and the judge held them, for
want of a wall. The check compiler now measures such a side from the face
beside the cut in its plane, wherever it is built (``compiler.cut_wall``).
What these hold:

- **Built as placed:** each, built through the build loop, every face
  accounted for and every check passing.
- **A wrong one is caught:** wider than asked, or set in from the edge.
- **Round bevelled corners:** a box's top edges bevelled or rounded after
  its corners were bevelled, the short stretches round each corner within
  the zones at their ends no longer measured for nothing.
- **A stud bevelled at both ends**, threaded all along: its thread stops in
  the foot's bevel.
- **A knob's bore** up its neck into the knob: the writer told to make the
  knob first, the neck standing on it; so made, built and judged.

The briefs are written here, not taken from any blind set.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft, mm
from v2_occ import needs_occ

_TEXT = "A bar with a rebate cut into its top."


def _bar(b: Any, cut: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": assumed("long", 70.0),
             "width": assumed("wide", 40.0), "height": assumed("thick", 5.0)}, cut]  # fmt: skip


def _pocket(b: Any, place: dict[str, Any], *, length: float = 10.0, width: float = 20.0,
            depth: float | None = 2.0) -> dict[str, Any]:  # fmt: skip
    return {"id": "rebate", "kind": "pocket", "words": cite(b, "rebate"), "on": {"item": "bar", "face": "+z"},
            "shape": {"choose": "rectangle", "from": {"assumed": "square"}}, "length": assumed("long", length),
            "width": assumed("wide", width),
            "depth": assumed("deep", depth) if depth is not None else {"through": True, "from": {"assumed": "t"}},
            "place": place}  # fmt: skip


def _slot(b: Any, place: dict[str, Any]) -> dict[str, Any]:
    return {"id": "rebate", "kind": "slot", "words": cite(b, "rebate"), "on": {"item": "bar", "face": "+z"},
            "length": assumed("long", 20.0), "width": assumed("wide", 6.0),
            "along": {"choose": "x", "from": {"assumed": "along it"}},
            "ends": {"choose": "square", "from": {"assumed": "square"}}, "depth": assumed("deep", 2.0),
            "place": place}  # fmt: skip


def _edge(side: str, distance: float = 0.0) -> dict[str, Any]:
    return {"side": side, "distance": assumed("at the edge", distance), "to": "edge"}


_MIDDLE = {"centred": {"assumed": "in the middle"}}

#: Each cut, by what it is.
CASES: dict[str, Any] = {
    "a rebate along an edge": lambda b: _bar(b, _pocket(b, {"x": _MIDDLE, "y": _edge("+y")})),
    "a rebate right through": lambda b: _bar(b, _pocket(b, {"x": _MIDDLE, "y": _edge("+y")}, depth=None)),
    "a groove right across": lambda b: _bar(b, _pocket(b, {"x": _MIDDLE, "y": _MIDDLE}, width=40.0)),
    "a notch in a corner": lambda b: _bar(b, _pocket(b, {"x": _edge("+x"), "y": _edge("+y")})),
    "a step at an end": lambda b: _bar(b, _pocket(b, {"x": _edge("-x"), "y": _MIDDLE}, width=40.0)),
    "a square-ended slot along an edge": lambda b: _bar(b, _slot(b, {"x": _MIDDLE, "y": _edge("+y")})),
}


def _planned(items: Any) -> tuple[Any, Any]:
    from forge_plan import plan
    from forge_spec.checks import check_draft
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    report = check_draft(brief, draft("bar", items(brief)), strict=False)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, brief, by="draft", strict=False)
    return spec, plan(spec)


@needs_occ
class BuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        for name, make in CASES.items():
            with self.subTest(name):
                spec, planned = _planned(make)
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_a_wrong_one_is_caught(self) -> None:
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        asked, _ = _planned(CASES["a rebate along an edge"])
        wider = {"x": _MIDDLE, "y": _edge("+y")}
        set_in = {"x": _MIDDLE, "y": _edge("+y", 1.0)}  # a wall 1 mm thick left along the edge
        for made in (lambda b: _bar(b, _pocket(b, wider, width=22.0)), lambda b: _bar(b, _pocket(b, set_in))):
            _, planned = _planned(made)
            _, accounting, failed = judged_plan(asked.spec, planned)
            self.assertTrue(accounting.verdict is Verdict.FAIL or failed)


def _box(b: Any, corners: tuple[str, float], top: tuple[str, float]) -> list[dict[str, Any]]:
    def edge(n: int, kind: str, which: str, size: float) -> dict[str, Any]:
        return {"id": f"e{n}", "kind": kind, "words": cite(b, "bar"), "edges": {"of": "bar", "which": which},
                ("size" if kind == "chamfer" else "radius"): assumed("so", size)}  # fmt: skip

    return [{"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": assumed("long", 60.0),
             "width": assumed("wide", 40.0), "height": assumed("tall", 20.0)},
            edge(1, corners[0], "vertical", corners[1]), edge(2, top[0], "top", top[1])]  # fmt: skip


@needs_occ
class RoundBevelledCorners(unittest.TestCase):
    def test_built_and_judged(self) -> None:
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        # A 1 mm bevel or rounding of the top round corners bevelled 2 mm: each corner's stretch of it lies
        # wholly within the zones at its ends; 3 mm, just less than 1.707 times the corners' bevel.
        for corners, top in ((("chamfer", 2.0), ("chamfer", 1.0)), (("chamfer", 2.0), ("fillet", 1.0)),
                             (("chamfer", 2.0), ("chamfer", 3.0))):  # fmt: skip
            with self.subTest(corners=corners, top=top):
                spec, planned = _planned(lambda b, c=corners, t=top: _box(b, c, t))
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


_STUD = "A stud: a rod 8 mm across and 30 mm long, with an M8 thread all along it and a 1 mm chamfer on both ends."


@needs_occ
class AStudBevelledAtBothEnds(unittest.TestCase):
    """Threaded all along, its foot bevelled before the thread: the thread runs on into the bevel and stops where its
    teeth meet it, short of the rod's end (it was held: its length measured 29.33 mm of 30)."""

    def test_built_and_judged(self) -> None:
        from forge_checks.classes import Verdict
        from forge_plan import plan
        from forge_spec.checks import check_draft
        from forge_spec.lock import lock
        from forge_spec.words import number_words
        from test_v2_plan_build import judged_plan

        b = number_words(_STUD)
        report = check_draft(b, draft("stud", [
            {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "axis": {"choose": "z", "from": {"assumed": "up"}},
             "diameter": mm(b, 8, "8 mm across"), "length": mm(b, 30, "30 mm long")},
            {"id": "ends", "kind": "chamfer", "words": cite(b, "chamfer"),
             "edges": {"of": "rod", "which": "both", "words": cite(b, "both ends")},
             "size": mm(b, 1, "1 mm chamfer")},
            {"id": "thread", "kind": "thread", "words": cite(b, "M8 thread"), "of": "rod",
             "designation": {"text": "M8", "from": {"words": cite(b, "M8")}},
             "hand": {"choose": "right", "from": {"assumed": "a standard thread"}}},
        ]), strict=False)  # fmt: skip
        self.assertEqual(report.problems, ())
        spec = lock(report, b, by="draft", strict=False)
        built, accounting, failed = judged_plan(spec.spec, plan(spec))
        self.assertIsNone(built.gap, built.refusals)
        self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
        self.assertEqual(failed, [])


_KNOB = ("A knob: a cylinder 30 mm across and 15 mm tall, on a neck 12 mm across and 10 mm long, with a 6 mm hole "
         "20 mm deep up into it from the neck's end.")  # fmt: skip


def _knob(b: Any, neck_first: bool) -> list[dict[str, Any]]:
    knob = {"id": "knob", "kind": "cylinder", "words": cite(b, "cylinder"), "diameter": mm(b, 30, "30 mm across"),
            "length": mm(b, 15, "15 mm tall")}  # fmt: skip
    neck = {"id": "neck", "kind": "cylinder", "words": cite(b, "neck"), "diameter": mm(b, 12, "12 mm across"),
            "length": mm(b, 10, "10 mm long")}  # fmt: skip
    up = {"choose": "z", "from": {"assumed": "upright"}}
    centred = {"x": {"centred": {"assumed": "on its axis"}}, "y": {"centred": {"assumed": "on its axis"}}}
    hole = {"id": "bore", "kind": "hole", "words": cite(b, "6 mm hole"), "diameter": mm(b, 6, "6 mm hole"),
            "depth": mm(b, 20, "20 mm deep"), "place": centred}  # fmt: skip
    if neck_first:  # the knob standing on the neck's top: the hole up from the neck's foot can't go on into it
        return [neck | {"axis": up}, knob | {"on": {"item": "neck", "face": "+end"}, "place": centred},
                hole | {"on": {"item": "neck", "face": "-end"}}]  # fmt: skip
    return [knob | {"axis": up}, neck | {"on": {"item": "knob", "face": "-end"}, "place": centred},
            hole | {"on": {"item": "neck", "face": "+end"}}]  # fmt: skip


class AKnobsBore(unittest.TestCase):
    """A blind cut stays in the body it is cut into and what that stands on (frame.md): a bore up a knob's neck into
    the knob standing on the neck was asked about as too deep, which the person couldn't settle. The writer is told
    to make the knob first and the neck standing on it; made so, the bore goes on into the knob."""

    def test_the_writer_is_told_to_make_them_the_other_way_round(self) -> None:
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words

        b = number_words(_KNOB)
        found = [(p.kind, p.message) for p in check_draft(b, draft("knob", _knob(b, True)), strict=False).problems]
        self.assertEqual([k for k, m in found if "Make knob first" in m], ["fault"], found)
        self.assertEqual(check_draft(b, draft("knob", _knob(b, False)), strict=False).problems, ())

    @needs_occ
    def test_made_the_other_way_round_it_is_built_and_judged(self) -> None:
        from forge_checks.classes import Verdict
        from forge_plan import plan
        from forge_spec.checks import check_draft
        from forge_spec.lock import lock
        from forge_spec.words import number_words
        from test_v2_plan_build import judged_plan

        b = number_words(_KNOB)
        report = check_draft(b, draft("knob", _knob(b, False)), strict=False)
        spec = lock(report, b, by="draft", strict=False)
        built, accounting, failed = judged_plan(spec.spec, plan(spec))
        self.assertIsNone(built.gap, built.refusals)
        self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
