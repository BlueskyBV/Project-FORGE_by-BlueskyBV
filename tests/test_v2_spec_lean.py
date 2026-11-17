"""Items leaning from square to their flat face, as the solver places them (tilt, tilt_towards; schema 1.3;
V2-stage4b-0c.md, 3.3, 1b's second move; place.md, "Leaning on the face").

- **A lean is read, written and cited** as an angle and a way, only in schema
  1.3 drafts, and only on a hole, a boss or a post.
- **What a lean must say:** its way, one of the face's axes; more than 0 and
  less than 90 degrees; Forge leans at most 75 degrees, a plain or
  counterbored hole, and only on a face with the same material under all of
  it: anything else is CAN'T.
- **A leaning item is placed by its foot,** its cross-section's section by
  the face: measured to its edge, the section's farthest point; copies held
  apart on their sections; its direction the face's normal turned towards
  its lean.
- **Under it, along its direction:** a blind hole stays in the material
  while ``D cos + r sin <= T``; what stands reaches back into the face by
  its half size along its lean times tan, which the face must have; its
  faces take nothing, its edges are not rounded.
- **Words and versions:** the fixed wording says the lean, and a draft says
  1.3 only when something leans.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

from forge_spec.checks import check_draft
from forge_spec.lean import MOST, ellipse
from forge_spec.wire import to_wire
from forge_spec.words import number_words
from v2_drafts import assumed, cite, draft, mm, said

BRIEF = number_words(
    "A plate 100 mm long, 60 mm wide and 8 mm thick. A hole 6 mm across goes through it, leaning 30 degrees "
    "towards +x, 4 mm from the -x edge. A boss 10 mm across and 12 mm tall stands on it. A post 6 mm long, "
    "4 mm wide and 9 mm tall stands on it. A blind hole 5 mm deep."
)
B = BRIEF


def _plate() -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(B, "plate"), "length": mm(B, 100, "100 mm"),
            "width": mm(B, 60, "60 mm"), "height": mm(B, 8, "8 mm")}  # fmt: skip


def _lean(degrees: float = 30.0, way: str = "+x") -> dict[str, Any]:
    return {"tilt": {"value": degrees, "unit": "deg", "from": said(B, "30 degrees") if degrees == 30.0
                     else {"assumed": "leaning"}},
            "tilt_towards": {"choose": way, "from": said(B, "towards +x") if way == "+x"
                             else {"assumed": "that way"}}}  # fmt: skip


def _hole(degrees: float = 30.0, way: str = "+x", **fields: Any) -> dict[str, Any]:
    return {"id": "hole", "kind": "hole", "words": cite(B, "hole"), "on": {"item": "plate", "face": "+z"},
            "diameter": mm(B, 6, "6 mm"), "depth": {"through": True, "from": said(B, "goes through")},
            **_lean(degrees, way), **fields}  # fmt: skip


def _boss(degrees: float = 30.0, way: str = "+x", **fields: Any) -> dict[str, Any]:
    return {"id": "boss", "kind": "boss", "words": cite(B, "boss"), "on": {"item": "plate", "face": "+z"},
            "diameter": mm(B, 10, "10 mm"), "height": mm(B, 12, "12 mm"), **_lean(degrees, way), **fields}  # fmt: skip


def _post(degrees: float = 30.0, way: str = "+x", **fields: Any) -> dict[str, Any]:
    return {"id": "post", "kind": "post", "words": cite(B, "post"), "on": {"item": "plate", "face": "+z"},
            "length": mm(B, 6, "6 mm"), "width": mm(B, 4, "4 mm"), "height": mm(B, 9, "9 mm"),
            **_lean(degrees, way), **fields}  # fmt: skip


def _report(*items: dict[str, Any], version: str = "1.3") -> Any:
    found = draft("plate", [_plate(), *items])
    found["schema_version"] = version
    return check_draft(B, found, strict=False)


def _placing(report: Any) -> list[str]:
    """The problems placing the items finds (not the brief's numbers the spec leaves unused)."""
    return [p.message for p in report.problems
            if "nothing in the spec uses it" not in p.message and "nothing in the spec comes from" not in p.message]  # fmt: skip


def _issues(report: Any) -> list[str]:
    return [str(i) for i in report.layout.issues] if report.layout is not None else []


def _says(report: Any, text: str) -> bool:
    return any(text in message for message in _placing(report) + _issues(report))


class ALeanIsReadWrittenAndCited(unittest.TestCase):
    def test_read_and_written(self) -> None:
        report = _report(_hole())
        self.assertEqual(_placing(report), [])
        self.assertEqual(report.spec.name, "plate")  # the draft's own name, whatever its items say
        hole = report.spec.item("hole")
        self.assertEqual(hole.get("tilt").made_in("deg"), 30.0)
        self.assertEqual(hole.get("tilt_towards").value, "+x")
        wire = to_wire(report.spec)["items"][1]
        self.assertEqual((wire["tilt"]["value"], wire["tilt_towards"]["choose"]), (30, "+x"))

    def test_only_in_schema_1_3(self) -> None:
        report = _report(_hole(), version="1.2")
        self.assertIn("/items/1/tilt", [p.at for p in report.problems])
        self.assertIn("/items/1/tilt_towards", [p.at for p in report.problems])

    def test_only_a_hole_a_boss_or_a_post(self) -> None:
        slot = {"id": "slot", "kind": "slot", "words": cite(B, "hole"), "on": {"item": "plate", "face": "+z"},
                "length": mm(B, 6, "6 mm"), "width": mm(B, 4, "4 mm"),
                "depth": {"through": True, "from": said(B, "goes through")}, **_lean()}  # fmt: skip
        report = _report(slot)
        self.assertIn("a slot has no field(s) ['tilt', 'tilt_towards']", [p.message for p in report.problems])


class WhatALeanMustSay(unittest.TestCase):
    def test_its_way_on_the_face(self) -> None:
        report = _report(_hole(way="+z"))
        self.assertTrue(_says(report, "which isn't one of face +z's axes"))

    def test_its_way_given(self) -> None:
        hole = _hole()
        del hole["tilt_towards"]
        report = _report(hole)
        self.assertTrue(_says(report, "give its tilt_towards"))

    def test_more_than_0_and_less_than_90(self) -> None:
        for degrees in (90.0, 120.0):
            with self.subTest(degrees=degrees):
                self.assertTrue(_says(_report(_hole(degrees)), "more than 0 and less than 90"))

    def test_at_most_75_for_now(self) -> None:
        report = _report(_hole(MOST + 5.0))
        self.assertTrue(_says(report, f"at most {MOST:g} degrees"))
        self.assertEqual(_placing(_report(_hole(MOST, way="+y"))), [])

    def test_a_countersunk_hole_is_a_later_step(self) -> None:
        sink = {"diameter": mm(B, 10, "10 mm"), "angle": {"value": 90, "unit": "deg", "from": {"assumed": "90"}}}
        report = _report(_hole(countersink=sink))
        self.assertTrue(_says(report, "a countersunk one leaning is a later step"))

    def test_only_where_the_material_is_the_same_under_all_of_the_face(self) -> None:
        # Under a pocket's floor is the material the pocket leaves: not all of the face's (its sides are deeper).
        pocket = {"id": "pocket", "kind": "pocket", "words": cite(B, "post"), "on": {"item": "plate", "face": "+z"},
                  "shape": {"choose": "rectangle", "from": {"assumed": "a pocket"}},
                  "length": assumed("long", 30.0), "width": assumed("wide", 20.0), "depth": mm(B, 5, "5 mm")}  # fmt: skip
        hole = _hole(degrees=20.0, way="+y", on={"item": "pocket", "face": "bottom"}, depth=assumed("deep", 2.0))
        report = _report(pocket, hole)
        self.assertTrue(_says(report, "hasn't the same material under all of it"), _issues(report) + _placing(report))


class ALeaningItemIsPlacedByItsFoot(unittest.TestCase):
    def test_measured_to_its_edge(self) -> None:
        side = {"place": {"x": {"side": "-x", "distance": mm(B, 4, "4 mm"), "to": "edge"}}}
        report = _report(_hole(**side))
        self.assertEqual(_placing(report), [])
        (copy_,) = report.layout.instances["hole"]
        # Its foot is the 3 mm circle drawn out along x by 1 / cos 30: its reach back along x.
        reach = 3.0 / math.cos(math.radians(30))
        self.assertAlmostEqual(copy_.origin[0], -50.0 + 4.0 + reach, places=9)

    def test_its_direction(self) -> None:
        report = _report(_hole())
        (copy_,) = report.layout.instances["hole"]
        t = math.radians(30)
        self.assertEqual(copy_.normal, (0.0, 0.0, 1.0))  # its face's, as an unleaning copy's
        for got, want in zip(copy_.direction, (math.sin(t), 0.0, math.cos(t)), strict=True):
            self.assertAlmostEqual(got, want, places=12)

    def test_turned_with_its_post(self) -> None:
        post = _post(way="+x", place={"turn": assumed("turned", 90.0, "deg")})
        report = _report(post, version="1.3")
        (copy_,) = report.layout.instances["post"]
        # Turned a quarter, its own length runs along y: it leans along +y.
        self.assertAlmostEqual(copy_.direction[1], math.sin(math.radians(30)), places=12)
        self.assertAlmostEqual(copy_.direction[0], 0.0, places=12)

    def test_copies_apart_on_their_feet(self) -> None:
        def row(pitch: float) -> dict[str, Any]:
            return {"count": {"count": 2, "from": {"assumed": "two"}},
                    "place": {"pattern": {"row": {"count": {"count": 2, "from": {"assumed": "two"}},
                                                  "pitch": assumed("apart", pitch),
                                                  "axis": {"choose": "x", "from": {"assumed": "along x"}}}}}}  # fmt: skip

        # Unleaning, 6.5 mm apart is apart; leaning 60 degrees along the row, each foot is 12 mm long.
        self.assertTrue(_says(_report(_hole(60.0, **row(6.5))), "copies 1 and 2 of hole overlap"))
        self.assertFalse(_says(_report(_hole(60.0, **row(12.5))), "overlap"))

    def test_its_foot_is_the_section(self) -> None:
        shape = ellipse(3.0 / math.cos(math.radians(30)), 3.0, (1.0, 0.0))
        (l1, l2), (h1, h2) = shape.box()
        self.assertAlmostEqual(h1, 3.0 / math.cos(math.radians(30)), places=12)
        self.assertAlmostEqual(-l1, h1, places=12)
        self.assertAlmostEqual(h2, 3.0, places=12)
        self.assertAlmostEqual(-l2, 3.0, places=12)


class UnderItAlongItsDirection(unittest.TestCase):
    def test_a_blind_hole_stays_in_the_material(self) -> None:
        # 8 mm of plate: 5 cos 30 + 3 sin 30 = 5.83 stays in it; 8 cos 30 + 1.5 doesn't.
        self.assertEqual(_placing(_report(_hole(depth=mm(B, 5, "5 mm")))), [])
        deep = _report(_hole(depth=assumed("deep", 8.0)))
        self.assertTrue(any("deep" in m for m in _placing(deep)), _placing(deep))

    def test_what_stands_reaches_back_into_the_face(self) -> None:
        self.assertEqual(_placing(_report(_boss())), [])
        # A 10 mm boss leaning 60 degrees reaches back 5 tan 60 = 8.66 mm: more than the plate's 8.
        report = _report(_boss(60.0))
        self.assertTrue(_says(report, "reaches 8.66025 mm back into face +z"), _placing(report))

    def test_its_faces_take_nothing(self) -> None:
        report = _report(_boss())
        self.assertEqual(report.layout.faces.get(("boss", 0), {}), {})
        self.assertIn("+end", report.layout.closed[("boss", 0)])

    def test_its_bounds(self) -> None:
        report = _report(_boss())
        (copy_,) = report.layout.instances["boss"]
        t = math.radians(30)
        # Along x: back to its foot's far side (5 / cos 30), on to its top's (12 sin 30 + 5 cos 30).
        self.assertAlmostEqual(copy_.lo[0], -5.0 / math.cos(t), places=9)
        self.assertAlmostEqual(copy_.hi[0], 12.0 * math.sin(t) + 5.0 * math.cos(t), places=9)
        self.assertAlmostEqual(copy_.hi[2], 8.0 + 12.0 * math.cos(t) + 5.0 * math.sin(t), places=9)

    def test_its_far_end_is_rounded_its_joint_not_yet(self) -> None:
        # Step 5.3: its far end's edges (and a box's along its lean) are rounded as upright, then leaned; its joint,
        # where it meets its face, waits.
        fillet = {"id": "round", "kind": "fillet", "words": cite(B, "boss"),
                  "edges": {"of": "boss", "which": "top"}, "radius": assumed("small", 1.0)}  # fmt: skip
        self.assertFalse(_says(_report(_boss(), fillet), "Forge rounds and chamfers"))
        joint = {**fillet, "edges": {"of": "boss", "which": "joint", "where_meets": "plate"}}
        self.assertTrue(_says(_report(_boss(), joint), "where it meets its face, in a later step"))

    def test_threaded_from_its_far_end_clear_of_its_foot(self) -> None:
        # Step 5.4: along its lean from its far end; all along it, it would reach where its side meets the face.
        thread = {"id": "thread", "kind": "thread", "words": cite(B, "boss"), "of": "boss",
                  "designation": {"text": "M10", "from": {"assumed": "M10"}},
                  "hand": {"choose": "right", "from": {"assumed": "right handed"}}}  # fmt: skip
        self.assertTrue(_says(_report(_boss(), thread), "a thread on it runs from its far end, clear of its foot"))
        short = {**thread, "length": assumed("short", 4.0)}
        self.assertFalse(_says(_report(_boss(), short), "a thread on it runs from its far end"))


class TwoDraftsCompareTheirLeans(unittest.TestCase):
    """Two drafts leaning alike build one part; leaning otherwise, or not at all, another (forge_spec.compare)."""

    def _differ(self, first: dict[str, Any], second: dict[str, Any]) -> bool:
        from forge_spec.compare import differences

        return bool(differences(_report(first), _report(second)))

    def test_a_hole(self) -> None:
        self.assertFalse(self._differ(_hole(), _hole()))
        self.assertTrue(self._differ(_hole(), _hole(35.0)))
        # Centred on the plate, leaning the other way is the same part turned half round; off its centre, it isn't.
        self.assertFalse(self._differ(_hole(), _hole(way="-x")))
        off = {"place": {"x": {"offset": assumed("off", 20.0)}}}
        self.assertTrue(self._differ(_hole(**off), _hole(way="-x", **off)))
        plain = _hole()
        del plain["tilt"], plain["tilt_towards"]
        self.assertTrue(self._differ(plain, _hole()))

    def test_a_boss_and_a_post(self) -> None:
        self.assertFalse(self._differ(_boss(), _boss()))
        self.assertTrue(self._differ(_boss(), _boss(20.0)))
        self.assertFalse(self._differ(_post(), _post()))
        self.assertTrue(self._differ(_post(), _post(way="+y")))


class ThroughHolesAreCounted(unittest.TestCase):
    def test_a_leaning_hole_through_is_one(self) -> None:
        from forge_eval.spec_grade import _through_holes

        report = _report(_hole())
        self.assertEqual(_through_holes(report.spec.items, report.layout), ({6.0: 1}, ""))
        blind = _report(_hole(depth=mm(B, 5, "5 mm")))
        self.assertEqual(_through_holes(blind.spec.items, blind.layout), ({}, ""))


class TheViewsShowALean(unittest.TestCase):
    """The confirmation views draw a leaning item as it is seen and show every value of it (forge_spec.render_views)."""

    def test_every_value_shown(self) -> None:
        from forge_spec.render_views import render_views
        from test_v2_spec_views import check_every_value_shown

        for make in (lambda: _hole(), lambda: _hole(depth=mm(B, 5, "5 mm")), lambda: _boss(), lambda: _post(),
                     lambda: _post(place={"turn": assumed("turned", 25.0, "deg")})):  # fmt: skip
            item = make()
            with self.subTest(item["kind"]):
                report = _report(item)
                views = render_views(report)
                check_every_value_shown(self, report, views, item["kind"])
                self.assertIn("tilt", views.shown(item["id"]))
                notes = [d.text for d in views.dimensions() if d.item == item["id"]]
                self.assertTrue(any("leaning 30° towards +X" in text for text in notes), notes)

    def test_seen_along_its_lean(self) -> None:
        """Seen from the front (along y), a boss leaning 30 degrees towards +x is the outline round its foot and its
        top: back along x to its foot's far side, 5 / cos 30 from its point; on to its top's, 12 sin 30 + 5 cos 30."""
        import re

        from forge_spec.render_views import render_views

        views = render_views(_report(_boss()))
        front = next(v for v in views.views if v.name == "front")
        t = math.radians(30)
        spans = [(min(xs), max(xs)) for xs in ([float(q.split(",")[0]) for q in found.split()]
                 for found in re.findall(r'<polygon points="([^"]+)"', front.svg))]  # fmt: skip
        self.assertIn((round(-5.0 / math.cos(t), 2), round(12.0 * math.sin(t) + 5.0 * math.cos(t), 2)), spans)


class TheGeneratorHoldsLeaningFeetApart(unittest.TestCase):
    """What the generator keeps a leaning item's covering clear by holds all of its foot (forge_eval.generator)."""

    def _row(self, height: float, pitch: float) -> Any:
        from forge_eval.generator import Feature, Pattern, Position, render

        body = Feature("body", "block", {"length": 80.0, "width": 60.0, "height": 10.0})
        boss = Feature("i0", "boss", {"diameter": 9.0, "height": height}, ("body", "+z"), None, {}, None,
                       {"x": Position("centred"), "y": Position("centred")}, None,
                       Pattern("row", {"pitch": pitch}, {"count": 2}, "y"), tilt=(45.0, "+y"))  # fmt: skip
        return render((body, boss))

    def test_a_short_one_s_foot_reaches_past_its_top(self) -> None:
        from forge_eval.generator import DoesNotFitError

        # 9 mm across, 2 mm tall, leaning 45 degrees along its row: each foot is 9 / cos 45 = 12.73 mm long, though
        # its top reaches only 2 sin 45 + 4.5 cos 45 = 4.6 mm forward: 12.2 mm apart, the feet overlap (generated
        # part 669); 13.5 mm apart, they are the gap apart.
        with self.assertRaises(DoesNotFitError):
            self._row(2.0, 12.2)
        case = self._row(2.0, 13.5)
        self.assertEqual(len(case.truth.copies["i0"]), 2)

    def test_the_solver_agrees(self) -> None:
        from forge_eval.generator import draft_of
        from forge_spec.draft import read_draft
        from forge_spec.placement import solve

        spec, _ = read_draft(draft_of(self._row(2.0, 13.5).items))
        self.assertEqual([str(i) for i in solve(spec).issues], [])


class WordsAndVersions(unittest.TestCase):
    def test_the_fixed_wording_says_it(self) -> None:
        from forge_spec.render import _line

        report = _report(_hole())
        self.assertTrue(_line(report.spec.item("hole")).endswith("leaning 30 deg towards +x"))

    def test_the_least_version(self) -> None:
        from forge_eval.generator import draft_of

        self.assertEqual(draft_of([{"id": "a", "tilt": {}}])["schema_version"], "1.3")
        self.assertEqual(draft_of([{"id": "a", "kind": "post", "tilt": {}}])["schema_version"], "1.3")
        self.assertEqual(draft_of([{"id": "a", "kind": "block", "tilt": {}}])["schema_version"], "1.5")
        self.assertEqual(draft_of([{"id": "a", "place": {"turn": {}}}])["schema_version"], "1.2")
        self.assertEqual(draft_of([{"id": "a"}]).get("spec_format"), 1)


if __name__ == "__main__":
    unittest.main()
