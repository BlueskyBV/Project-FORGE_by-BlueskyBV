"""What goes on a leaning item's far face (place.md, "A leaning item's far face"; frame.md; V2-stage4b-0c.md, 3.3,
1b's step 5, with item 2b).

- **Placed as with it upright, then leaned:** a hole, a pocket, a slot or a
  boss on the far end of a leaning boss, post, cylinder or block, along the
  face's own axes, u and v; every program's layout agrees.
- **The material under it is its own,** from each point back along its
  axis to the face it leans on: least on the side it leans towards, and
  under a pocket's floor there, less the pocket's depth. A blind
  cut deeper than that, one right through, a turned leaning item's far face
  and a hollowed one are said.
- **What is built is what was placed.** Each part built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing.
- **A wrong lean is caught:** what is on it leaned half a degree more fails
  the judge.
- **The second kernel agrees** with the exact part.
- **The generator draws it:** its own far face, oriented as it leans, the
  material under it falling away the way it leans.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_faceaxes import _TEXT, _judged, _planned, _plate
from v2_drafts import assumed, cite, draft
from v2_occ import needs_occ

_SIZES = {"boss": {"diameter": 16.0, "height": 20.0}, "post": {"length": 16.0, "width": 12.0, "height": 20.0},
          "cylinder": {"diameter": 16.0, "length": 20.0}, "block": {"length": 16.0, "width": 12.0, "height": 20.0}}  # fmt: skip


def _leaning(b: Any, kind: str = "boss", tilt: float = 20.0, way: str = "+x", **more: Any) -> dict[str, Any]:
    sizes = {name: assumed("so", value) for name, value in _SIZES[kind].items()}
    return {"id": "lean", "kind": kind, "words": cite(b, "boss"), "on": {"item": "plate", "face": "+z"}, **sizes,
            "tilt": assumed("leaning", tilt, "deg"), "tilt_towards": {"choose": way, "from": {"assumed": "that way"}},
            **more}  # fmt: skip


def _far(kind: str) -> str:
    return "+end" if kind in ("boss", "cylinder") else "+z"


def _hole(b: Any, face: str, depth: float = 6.0, d: float = 4.0, **place: Any) -> dict[str, Any]:
    found = {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "lean", "face": face},
             "diameter": assumed("across", d), "depth": assumed("deep", depth)}  # fmt: skip
    if place:
        found["place"] = place
    return found


def _pocket(b: Any, face: str, shape: str = "rectangle") -> dict[str, Any]:
    sizes = ({"length": assumed("long", 8.0), "width": assumed("wide", 5.0)} if shape == "rectangle"
             else {"diameter": assumed("across", 6.0)})  # fmt: skip
    return {"id": "hole", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "lean", "face": face},
            "shape": {"choose": shape, "from": {"assumed": "so"}}, **sizes, "depth": assumed("deep", 5.0)}  # fmt: skip


def _slot(b: Any, face: str) -> dict[str, Any]:
    return {"id": "hole", "kind": "slot", "words": cite(b, "hole"), "on": {"item": "lean", "face": face},
            "length": assumed("long", 9.0), "width": assumed("wide", 3.0), "depth": assumed("deep", 4.0),
            "along": {"choose": "u", "from": {"assumed": "along"}}, "ends": {"choose": "round", "from": {"assumed": "round"}}}  # fmt: skip


def _boss(b: Any, face: str) -> dict[str, Any]:
    return {"id": "hole", "kind": "boss", "words": cite(b, "boss"), "on": {"item": "lean", "face": face},
            "diameter": assumed("across", 5.0), "height": assumed("tall", 4.0)}  # fmt: skip


def _pin(b: Any, depth: float = 3.0) -> dict[str, Any]:
    """A hole in the floor of the pocket (``hole``) on the far face, 2 mm along u from its middle."""
    return {"id": "pin", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "hole", "face": "bottom"},
            "diameter": assumed("across", 2.0), "depth": assumed("deep", depth), "place": {"u": {"offset": assumed("off", 2.0)}}}  # fmt: skip


def _row(found: dict[str, Any]) -> dict[str, Any]:
    two = {"count": 2, "from": {"assumed": "two"}}
    return {**found, "count": two, "place": {"pattern": {"row": {"count": two, "pitch": assumed("apart", 6.0),
                                                                  "axis": {"choose": "u", "from": {"assumed": "along"}}}}}}  # fmt: skip


#: Each part: the plate, a leaning item on it, and what is on its far face; and where that is, as (the leaning item's
#: kind, its tilt, the way it leans, how far along u from the far face's centre).
CASES: dict[str, tuple[Any, tuple[str, float, str, float]]] = {
    "a hole in a leaning boss's end": (lambda b: [_leaning(b), _hole(b, "+end")], ("boss", 20.0, "+x", 0.0)),
    "a hole off its middle": (lambda b: [_leaning(b), _hole(b, "+end", u={"offset": assumed("off", 3.0)})],
                              ("boss", 20.0, "+x", 3.0)),
    "a hole in a leaning post's top": (lambda b: [_leaning(b, "post", way="-y"), _hole(b, "+z", depth=10.0)],
                                       ("post", 20.0, "-y", 0.0)),
    "a hole in a leaning cylinder's end": (lambda b: [_leaning(b, "cylinder", 30.0), _hole(b, "+end", depth=8.0)],
                                           ("cylinder", 30.0, "+x", 0.0)),
    "a hole in a leaning block's top": (lambda b: [_leaning(b, "block", 15.0, "+y"), _hole(b, "+z")],
                                        ("block", 15.0, "+y", 0.0)),
    "a pocket in a leaning post's top": (lambda b: [_leaning(b, "post"), _pocket(b, "+z")], ("post", 20.0, "+x", 0.0)),
    "a round pocket in a leaning boss's end": (lambda b: [_leaning(b), _pocket(b, "+end", "circle")],
                                               ("boss", 20.0, "+x", 0.0)),
    "a slot in a leaning post's top": (lambda b: [_leaning(b, "post", way="+y"), _slot(b, "+z")],
                                       ("post", 20.0, "+y", 0.0)),
    "a boss on a leaning post's top": (lambda b: [_leaning(b, "post"), _boss(b, "+z")], ("post", 20.0, "+x", 0.0)),
    "a counterbored hole in a leaning boss": (
        lambda b: [_leaning(b), {**_hole(b, "+end", depth=10.0),
                                 "counterbore": {"diameter": assumed("across", 8.0), "depth": assumed("deep", 3.0)}}],
        ("boss", 20.0, "+x", 0.0)),
    "a row of holes in a leaning post": (lambda b: [_leaning(b, "post"), _row(_hole(b, "+z", d=2.0))],
                                         ("post", 20.0, "+x", -3.0)),
    "a hole in a pocket's floor there": (lambda b: [_leaning(b, "post"), _pocket(b, "+z"), _pin(b)],
                                         ("post", 20.0, "+x", 0.0)),
}


def _report(make: Any) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    b = number_words(_TEXT)
    return check_draft(b, draft("plate", [_plate(b), *make(b)]), strict=False)


class PlacedAsUprightThenLeaned(unittest.TestCase):
    def test_where_it_is(self) -> None:
        for name, (make, (kind, tilt, way, along)) in CASES.items():
            with self.subTest(name):
                report = _report(make)
                self.assertEqual(report.problems, ())
                copy = report.layout.instances["hole"][0]
                c, s = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
                sign, axis = (1.0 if way[0] == "+" else -1.0), "xyz".index(way[1])
                w = tuple(sign if k == axis else 0.0 for k in range(3))
                d = tuple(c * (k == 2) + s * w[k] for k in range(3))  # its axis: the plate's +z turned its tilt its way
                tilted = tuple(c * w[k] - s * (k == 2) for k in range(3))  # u on its far face, where it leans along u
                height = _SIZES[kind].get("height", _SIZES[kind].get("length"))
                u = tilted if axis == 0 else (1.0, 0.0, 0.0)
                want = tuple(8.0 * (k == 2) + height * d[k] + along * u[k] for k in range(3))
                for got, expected in ((copy.origin, want), (copy.normal, d)):
                    for g, e in zip(got, expected, strict=True):
                        self.assertAlmostEqual(g, e, places=9)

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, (make, _) in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class TheMaterialUnderItIsItsOwn(unittest.TestCase):
    def test_least_the_way_it_leans(self) -> None:
        # 20 mm along its axis at its middle; 5 + 2 mm along the way it leans, tan 20 degrees each less.
        report = _report(lambda b: [_leaning(b), _hole(b, "+end", depth=19.0, u={"offset": assumed("off", 5.0)})])
        self.assertTrue(any(f"in {20 - 7 * math.tan(math.radians(20)):g} mm of material" in p.message
                            for p in report.problems), [p.message for p in report.problems])  # fmt: skip
        report = _report(lambda b: [_leaning(b), _hole(b, "+end", depth=19.0, u={"offset": assumed("off", -5.0)})])
        self.assertEqual(report.problems, ())  # against it, there is more

    def test_under_a_pockets_floor_there(self) -> None:
        # 20 mm less the pocket's 5 at its middle; 2 + 1 mm along the way it leans, tan 20 degrees each less.
        report = _report(lambda b: [_leaning(b, "post"), _pocket(b, "+z"), _pin(b, depth=30.0)])
        self.assertTrue(any(f"in {15 - 3 * math.tan(math.radians(20)):g} mm of material" in p.message
                            for p in report.problems), [p.message for p in report.problems])  # fmt: skip

    def test_what_isnt_yet_is_said(self) -> None:
        through = {"through": True, "from": {"assumed": "through"}}
        turned = {"place": {"turn": assumed("turned", 30.0, "deg")}}
        for make, words in (
            (lambda b: [_leaning(b), {**_hole(b, "+end"), "depth": through}], "would come out on the face it leans on"),
            (lambda b: [_leaning(b, "post", **turned), _hole(b, "+z")], "in a later move"),
        ):  # fmt: skip
            with self.subTest(words):
                report = _report(make)
                self.assertTrue(any(p.kind in ("unable", "fault") and words in p.message for p in report.problems),
                                [(p.kind, p.message) for p in report.problems])  # fmt: skip


@needs_occ
class BuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict

        for name, (make, _) in CASES.items():
            with self.subTest(name):
                built, accounting, failed = _judged(make)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


@needs_occ
class AWrongLeanIsCaught(unittest.TestCase):
    def test_leaned_half_a_degree_more(self) -> None:
        import forge_plan.moved as moved
        from forge_checks.classes import Verdict

        real = moved.transform_params

        def more(motion: Any) -> dict[str, Any]:
            found = real(motion)
            angle = found["rotate_angle"]
            return {**found, "rotate_angle": {**angle, "magnitude": angle["magnitude"] + 0.5}}

        for name in ("a pocket in a leaning post's top", "a boss on a leaning post's top"):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, failed = _judged(CASES[name][0])
                self.assertIsNone(built.gap)
                self.assertTrue(accounting.verdict is Verdict.FAIL or failed, failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_on_a_leaning_far_face(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a hole off its middle", "a pocket in a leaning post's top", "a boss on a leaning post's top"):
            with self.subTest(name):
                _, planned = _planned(CASES[name][0])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsIt(unittest.TestCase):
    def test_its_far_face_leans(self) -> None:
        from forge_eval.generator import Feature, _build

        body = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 10.0})
        boss = Feature("i0", "boss", {"diameter": 16.0, "height": 20.0}, ("body", "+z"), tilt=(20.0, "+x"))
        face = _build((body, boss), True).flats[("i0", 0, "+end")]
        c, s = math.cos(math.radians(20.0)), math.sin(math.radians(20.0))
        for got, want in ((face.normal, (s, 0.0, c)), (face.centre, (20 * s, 0.0, 10 + 20 * c))):
            for g, w in zip(got, want, strict=True):
                self.assertAlmostEqual(float(g), w, places=9)
        self.assertEqual(face.slant[0], (1.0, 0.0))
        self.assertAlmostEqual(face.slant[1], s / c, places=12)

    def test_it_draws_on_one(self) -> None:
        from forge_eval.generator import _build, generate

        found = []
        for seed in (18, 95):  # generated parts 41 and 66 are drawn otherwise since (box rims; nut traps)
            plan = generate(seed).plan
            flats = _build(plan, False).flats
            found += [f.id for f in plan if f.on is not None and (f.on[0], 0, f.on[1]) in flats
                      and flats[(f.on[0], 0, f.on[1])].slant is not None]  # on its far face, not its sides  # fmt: skip
        self.assertEqual(len(found), 3)


if __name__ == "__main__":
    unittest.main()
