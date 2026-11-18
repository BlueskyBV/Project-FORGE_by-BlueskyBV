"""What is cut into a leaning item's sides (place.md, "A leaning item's sides"; frame.md; V2-stage4b-0c.md, 3.3, a
leaning item's sides).

- **Placed as on its upright side clear of its foot, then leaned:** a hole,
  a pocket or a slot square into a side of a leaning post or block, along
  the face's own axes, u and v, on its upright side less the band along its
  foot as high as its foot rises on the side it leans towards; a hole round
  a leaning boss's or cylinder's side, along its axis and at an angle round
  it, the band its radius times its tilt's tan; every program's layout
  agrees.
- **What isn't yet is said:** something standing or leaning on a side, a
  cut reaching into the band, a box leaning so far that its foot reaches
  all the way up its sides, and a turned leaning box's sides.
- **What is built is what was placed.** Each part built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing; a cut right through comes out on the side across.
- **A wrong lean is caught:** what is on it leaned half a degree more fails
  the judge.
- **The second kernel agrees** with the exact part.
- **The generator draws it:** its own sides, flat and round, oriented as it
  leans, clear of its foot, and a cut on one now and then.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_faceaxes import _judged, _planned
from test_v2_plan_leanfar import (
    _SIZES,
    _boss,
    _hole,
    _leaning,
    _pocket,
    _report,
    _row,
    _slot,
)
from v2_drafts import assumed
from v2_occ import needs_occ

_THROUGH = {"through": True, "from": {"assumed": "through"}}


def _counterbored(b: Any, face: str) -> dict[str, Any]:
    return {**_hole(b, face, depth=8.0), "counterbore": {"diameter": assumed("across", 7.0), "depth": assumed("deep", 2.0)}}


#: Each part: the plate, a leaning box on it, and what is cut into one of its sides; and where that is, as (the box's
#: kind, its tilt, the way it leans, the side, how far along the side's u and its v from the middle of the side clear
#: of its foot).
CASES: dict[str, tuple[Any, tuple[str, float, str, str, float, float]]] = {
    "a hole across its lean": (lambda b: [_leaning(b, "post"), _hole(b, "+y")], ("post", 20.0, "+x", "+y", 0.0, 0.0)),
    "a hole in the side it leans from": (lambda b: [_leaning(b, "post"), _hole(b, "-x")],
                                         ("post", 20.0, "+x", "-x", 0.0, 0.0)),
    "a hole in the side it leans over": (lambda b: [_leaning(b, "post"), _hole(b, "+x")],
                                         ("post", 20.0, "+x", "+x", 0.0, 0.0)),
    "a hole right through it": (lambda b: [_leaning(b, "post"), {**_hole(b, "+y"), "depth": _THROUGH}],
                                ("post", 20.0, "+x", "+y", 0.0, 0.0)),
    "a hole right through it the way it leans": (lambda b: [_leaning(b, "post", 30.0), {**_hole(b, "-x"), "depth": _THROUGH}],
                                                 ("post", 30.0, "+x", "-x", 0.0, 0.0)),
    "a hole low on its side": (lambda b: [_leaning(b, "post"), _hole(b, "-y", v={"offset": assumed("down", -6.0)})],
                               ("post", 20.0, "+x", "-y", 0.0, -6.0)),
    "a hole off its middle": (lambda b: [_leaning(b, "post", way="-y"), _hole(b, "+x", u={"offset": assumed("off", 3.0)},
                                                                          v={"offset": assumed("up", 2.0)})],
                              ("post", 20.0, "-y", "+x", 3.0, 2.0)),
    "a pocket in a leaning block's side": (lambda b: [_leaning(b, "block", 15.0, "+y"), _pocket(b, "-x")],
                                           ("block", 15.0, "+y", "-x", 0.0, 0.0)),
    "a slot along its side": (lambda b: [_leaning(b, "post", way="-y"), _slot(b, "+x")],
                              ("post", 20.0, "-y", "+x", 0.0, 0.0)),
    "a counterbored hole": (lambda b: [_leaning(b, "post", 25.0, "-x"), _counterbored(b, "+y")],
                            ("post", 25.0, "-x", "+y", 0.0, 0.0)),
    "a row of holes along its side": (lambda b: [_leaning(b, "post"), _row({**_hole(b, "+y", d=2.0), "place": {}})],
                                   ("post", 20.0, "+x", "+y", -3.0, 0.0)),
}  # fmt: skip


def _round(b: Any, depth: float = 5.0, d: float = 3.0, **place: Any) -> dict[str, Any]:
    """A hole round the leaning item's side."""
    return {**_hole(b, "side", depth=depth, d=d, **place)}


def _circle(found: dict[str, Any], count: int = 3) -> dict[str, Any]:
    many = {"count": count, "from": {"assumed": "so many"}}
    return {**found, "count": many, "place": {**found.get("place", {}), "pattern": {"circle": {"count": many}}}}


#: Each part: the plate, a leaning boss or cylinder on it, and a hole round its side; and where its first copy is, as
#: (the item's kind, its tilt, the way it leans, the angle round it, how far along its axis from the middle of the side
#: clear of its foot).
ROUND_CASES: dict[str, tuple[Any, tuple[str, float, str, float, float]]] = {
    "a hole into a leaning boss's side": (lambda b: [_leaning(b), _round(b)], ("boss", 20.0, "+x", 0.0, 0.0)),
    "a hole round it at 90 degrees": (lambda b: [_leaning(b), _round(b, angle=assumed("round", 90.0, "deg"))],
                                      ("boss", 20.0, "+x", 90.0, 0.0)),
    "a hole right through it, along its lean": (
        lambda b: [_leaning(b, tilt=30.0), {**_round(b, angle=assumed("round", 180.0, "deg")), "depth": _THROUGH}],
        ("boss", 30.0, "+x", 180.0, 0.0)),
    "a hole low on a leaning cylinder's side": (
        lambda b: [_leaning(b, "cylinder", 30.0, "-y"), _round(b, z={"offset": assumed("down", -4.0)})],
        ("cylinder", 30.0, "-y", 0.0, -4.0)),
    "a circle of holes round it": (lambda b: [_leaning(b, way="+y"), _circle(_round(b, depth=3.0, d=2.0))],
                                   ("boss", 20.0, "+y", 0.0, 0.0)),
}  # fmt: skip


def _leaned(v: tuple[float, ...], tilt: float, way: str) -> tuple[float, ...]:
    """A vector of the box upright (standing on the plate's +z), as it leans: its part along the way it leans and its
    part up turned its tilt, about the line across."""
    c, s = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    sign, axis = (1.0 if way[0] == "+" else -1.0), "xyz".index(way[1])
    w = tuple(sign if k == axis else 0.0 for k in range(3))
    along, up = sum(v[k] * w[k] for k in range(3)), v[2]
    rest = tuple(v[k] - along * w[k] - up * (k == 2) for k in range(3))
    return tuple(rest[k] + along * (c * w[k] - s * (k == 2)) + up * (c * (k == 2) + s * w[k]) for k in range(3))


class PlacedOnItsUprightSideClearOfItsFootThenLeaned(unittest.TestCase):
    def test_where_it_is(self) -> None:
        from forge_spec.items.solve._common import FACE_AXES

        for name, (make, (kind, tilt, way, side, du, dv)) in CASES.items():
            with self.subTest(name):
                report = _report(make)
                self.assertEqual(report.problems, ())
                copy = report.layout.instances["hole"][0]
                sizes = _SIZES[kind]
                half = {"x": sizes["length"] / 2, "y": sizes["width"] / 2}
                height = sizes["height"]
                rise = half[way[1]] * math.tan(math.radians(tilt))
                sign, axis = (1.0 if side[0] == "+" else -1.0), side[1]
                normal = tuple(sign if k == "xyz".index(axis) else 0.0 for k in range(3))
                a1, a2 = FACE_AXES[side]
                # Upright, from the box's point: out to the side, up to the middle of it clear of its foot, then
                # along its u and its v.
                upright = [half[axis] * normal[k] + (height + rise) / 2 * (k == 2) for k in range(3)]
                for along, name_ in ((du, a1), (dv, a2)):
                    upright["xyz".index(name_)] += along
                want = tuple(8.0 * (k == 2) + moved for k, moved in enumerate(_leaned(tuple(upright), tilt, way)))
                for got, expected in ((copy.origin, want), (copy.normal, _leaned(normal, tilt, way))):
                    for g, e in zip(got, expected, strict=True):
                        self.assertAlmostEqual(g, e, places=9)

    def test_round_its_side(self) -> None:
        for name, (make, (kind, tilt, way, angle, dz)) in ROUND_CASES.items():
            with self.subTest(name):
                report = _report(make)
                self.assertEqual(report.problems, ())
                copy = report.layout.instances["hole"][0]
                sizes = _SIZES[kind]
                r, length = sizes["diameter"] / 2, sizes.get("height", sizes.get("length"))
                rise = r * math.tan(math.radians(tilt))
                c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                radial = (c, s, 0.0)  # round z, from x towards y
                upright = (r * c, r * s, rise + (length - rise) / 2 + dz)
                want = tuple(8.0 * (k == 2) + moved for k, moved in enumerate(_leaned(upright, tilt, way)))
                for got, expected in ((copy.origin, want), (copy.normal, _leaned(radial, tilt, way))):
                    for g, e in zip(got, expected, strict=True):
                        self.assertAlmostEqual(g, e, places=9)

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, (make, _) in {**CASES, **ROUND_CASES}.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatIsntYetIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        from forge_checks.place import PlaceError, place
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words
        from test_v2_plan_faceaxes import _TEXT, _plate
        from v2_drafts import draft

        short = {"height": assumed("tall", 5.0)}
        for make, words, judged in (
            (lambda b: [_leaning(b, "post"), _boss(b, "+y")], "stands or leans nothing on it", True),
            (lambda b: [_leaning(b), _boss(b, "side")], "stands or leans nothing on it", True),
            (lambda b: [_leaning(b, "post"), {**_hole(b, "+y"), "tilt": assumed("leaning", 10.0, "deg"),
                                              "tilt_towards": {"choose": "+u", "from": {"assumed": "that way"}}}],
             "stands or leans nothing on it", True),
            # Its v runs up the side: 8.54 mm down from the middle of it clear of its foot to the band, 2 mm round.
            (lambda b: [_leaning(b, "post"), _hole(b, "+y", v={"offset": assumed("down", -7.5)})],
             "runs past the edge of face +y", True),
            # Its foot rises 6 mm up its sides (its half width times tan 45 degrees), above its 5.
            (lambda b: [_leaning(b, "post", 45.0, "+y", **short), _hole(b, "+x")], "foot reaches all the way up", True),
            # A boss 8 mm round leaning 35 degrees: its foot rises 5.6 mm up its side, above its 5.
            (lambda b: [_leaning(b, tilt=35.0, height=assumed("tall", 5.0)), _round(b)], "foot reaches all the way up",
             True),
            # Its side runs 17.09 mm from where it is clear of its foot: half of that down, and the hole's own 1.5.
            (lambda b: [_leaning(b), _round(b, z={"offset": assumed("down", -8.0)})], "past", False),
            (lambda b: [_leaning(b, "post", place={"turn": assumed("turned", 30.0, "deg")}), _hole(b, "+y")],
             "in a later move", True),
        ):  # fmt: skip
            with self.subTest(words):
                report = _report(make)
                self.assertTrue(any(p.kind in ("unable", "fault", "question") and words in p.message
                                    for p in report.problems), [(p.kind, p.message) for p in report.problems])  # fmt: skip
                if judged:  # the judge says so on its own
                    brief = number_words(_TEXT)
                    found = check_draft(brief, draft("plate", [_plate(brief), *make(brief)]), strict=False)
                    with self.assertRaises(PlaceError):
                        place(found.spec)


@needs_occ
class BuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict

        for name, (make, _) in {**CASES, **ROUND_CASES}.items():
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

        for name, make in (("a hole across its lean", CASES["a hole across its lean"][0]),
                           ("a pocket in a leaning block's side", CASES["a pocket in a leaning block's side"][0]),
                           ("a hole into a leaning boss's side", ROUND_CASES["a hole into a leaning boss's side"][0])):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, failed = _judged(make)
                self.assertIsNone(built.gap)
                self.assertTrue(accounting.verdict is Verdict.FAIL or failed, failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_on_a_leaning_side(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name, make in (("a hole right through it the way it leans", CASES["a hole right through it the way it leans"][0]),
                           ("a pocket in a leaning block's side", CASES["a pocket in a leaning block's side"][0]),
                           ("a hole right through it, along its lean",
                            ROUND_CASES["a hole right through it, along its lean"][0])):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(make)
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsIt(unittest.TestCase):
    def test_its_sides_lean_clear_of_its_foot(self) -> None:
        from forge_eval.generator import Feature, _build

        body = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 10.0})
        post = Feature("i0", "post", {"length": 16.0, "width": 12.0, "height": 20.0}, ("body", "+z"), tilt=(20.0, "+x"))
        flats = _build((body, post), True).flats
        rise = 8.0 * math.tan(math.radians(20.0))
        for side, half, across in (("+x", 8.0, 12.0), ("-x", 8.0, 12.0), ("+y", 6.0, 16.0), ("-y", 6.0, 16.0)):
            # Its u across it (y, or x), its v up it (z): the box's size across, and its height less the band.
            with self.subTest(side):
                face = flats[("i0", 0, side)]
                sign, k = (1.0 if side[0] == "+" else -1.0), "xyz".index(side[1])
                normal = tuple(sign if j == k else 0.0 for j in range(3))
                upright = tuple(half * normal[j] + (20.0 + rise) / 2 * (j == 2) for j in range(3))
                want = tuple(10.0 * (j == 2) + moved for j, moved in enumerate(_leaned(upright, 20.0, "+x")))
                for got, expected in ((face.normal, _leaned(normal, 20.0, "+x")), (face.centre, want)):
                    for g, e in zip(got, expected, strict=True):
                        self.assertAlmostEqual(float(g), e, places=9)
                self.assertTrue(face.leans)
                self.assertEqual(face.exit, ("i0", 0, ("-" if side[0] == "+" else "+") + side[1]))
                self.assertAlmostEqual(face.material, 2 * half, places=12)
                for got, expected in zip(face.half, (across / 2, (20.0 - rise) / 2), strict=True):
                    self.assertAlmostEqual(got, expected, places=12)

    def test_a_round_side_leans_clear_of_its_foot(self) -> None:
        from forge_eval.generator import Feature, _build

        body = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 10.0})
        boss = Feature("i0", "boss", {"diameter": 16.0, "height": 20.0}, ("body", "+z"), tilt=(20.0, "+x"))
        side = _build((body, boss), True).rounds[("i0", 0, "side")]
        rise = 8.0 * math.tan(math.radians(20.0))
        frame = side.frame
        for got, want in ((frame.origin, tuple(10.0 * (k == 2) + m for k, m in enumerate(_leaned((0.0, 0.0, rise), 20.0, "+x")))),
                          (frame.u, _leaned((1.0, 0.0, 0.0), 20.0, "+x")), (frame.v, (0.0, 1.0, 0.0)),
                          (frame.n, _leaned((0.0, 0.0, 1.0), 20.0, "+x"))):  # fmt: skip
            for g, w in zip(got, want, strict=True):
                self.assertAlmostEqual(float(g), w, places=9)
        self.assertTrue(side.leans)
        self.assertAlmostEqual(side.length, 20.0 - rise, places=12)

    def test_it_draws_on_one(self) -> None:
        from forge_eval.generator import _build, generate

        for seed, item, face in ((66, "i2", "+x"), (129, "i4", "side")):
            with self.subTest(seed=seed):
                case = generate(seed)
                part = _build(case.plan, False)
                found = [(f.id, f.on[1]) for f in case.plan if f.on is not None
                         and (((key := (f.on[0], 0, f.on[1])) in part.flats and part.flats[key].leans)
                              or (key in part.rounds and part.rounds[key].leans))]  # fmt: skip
                self.assertEqual(found, [(item, face)])


if __name__ == "__main__":
    unittest.main()
