"""V2 stage 1: the views of a draft show every value it holds (forge_spec.render_views).

Plan, section 4.2, item 4: top, front and side views that dimension every
item at least once, with derived overall sizes labelled. The tests pin:

- every value of every item the layout placed is shown, on a drawing or in
  words, over every kind and over random drafts; what wasn't placed is
  listed as not drawn;
- each line spans what its text says: a size line is as long as its value,
  a place line runs from the edge, end or centre the place names to where
  the solver put the item, a pattern's line is its step;
- a size along X or Y is on the top view, along Z on the front; a cut's size
  is noted on the view that looks into it;
- an edge facing away, or wholly behind a solid, is dashed; a hole right
  through shows from both sides; a hollow shows through its opening;
- the overall size is drawn, labelled, only where no item gives it;
- what is cut right through is seen through; a counterbore or countersink
  is seen as far as it reaches, a hole at an angle where it comes out;
- a cone is drawn by its own diameters, a tab all round end as a half disc,
  never a point twice running;
- the words say a pattern of one, where 0 degrees is round a side and how
  copies round it are spaced, and along which axis a corner's inset runs;
- the drawings are well-formed SVG at one scale, in the page's own colour,
  with every text escaped, the same each time, and many things quickly;
- the spec page shows them after what is to settle and before the brief,
  each at that one scale, never shrunk to fit.

Drafts here are built for the tests, never from the blind sets.
"""

from __future__ import annotations

import itertools
import math
import random
import re
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from forge_spec.checks import SpecReport, check_draft
from forge_spec.draft import (
    Counterbore,
    Countersink,
    Fit,
    Item,
    Place,
    Text,
    Through,
    read_draft,
)
from forge_spec.placement import mm, solve
from forge_spec.render import render
from forge_spec.render_views import Dimension, Views, render_views
from forge_spec.schema import KINDS, Category
from forge_spec.values import Count, Value

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_spec_partspec import bracket_draft, flange_draft, plate_draft
from test_v2_spec_placement import (
    EXAMPLES,
    PLATE,
    a,
    at,
    centred,
    hole,
    item,
    n,
    on,
    pick,
    shell,
    through,
)
from v2_drafts import draft
from v2_gen import random_draft

SVG = "{http://www.w3.org/2000/svg}"


def views_of(*items: dict[str, Any]) -> tuple[Views, SpecReport]:
    spec, read = read_draft(draft("test", list(items)))
    assert spec is not None and not read.faults, [str(p) for p in read.faults]
    report = SpecReport(spec, solve(spec), (), (), (), (), None)
    return render_views(report), report


def degrees(value: float) -> dict[str, Any]:
    return a(value, "deg")


def held(item: Item) -> set[str]:
    """Every value an item holds, by where it is in the item: what the views must show."""
    out: set[str] = set()
    for name, value in item.fields.items():
        if isinstance(value, Place):
            out |= {f"place.{axis}" for axis in value.axes}
            if value.angle is not None:
                out.add("place.angle")
            if value.pattern is not None:
                out |= {
                    f"place.pattern.{k}"
                    for k in (*value.pattern.values, *value.pattern.counts)
                }
            if value.concentric:
                out.add("place.concentric")
        elif isinstance(
            value, (Value, Count, Through, Fit, Text, Counterbore, Countersink)
        ):
            out.add(name)
    return out


def lines(views: Views, view: str, item: str | None = None) -> list[Dimension]:
    (found,) = [v for v in views.views if v.name == view]
    return [
        d
        for d in found.dimensions
        if d.form == "line" and (item is None or d.item == item)
    ]


def note(views: Views, item: str) -> Dimension:
    (found,) = [d for d in views.dimensions() if d.item == item and d.form == "note"]
    return found


def shapes(views: Views, view: str) -> dict[str, list[ET.Element]]:
    """The outlines of a view by how they are drawn: "visible", "hidden", "centre", "envelope"."""
    (found,) = [v for v in views.views if v.name == view]
    root = ET.fromstring(found.svg)
    out: dict[str, list[ET.Element]] = {}
    for group in root.iter(f"{SVG}g"):
        if group.get("class") in ("visible", "hidden", "centre", "envelope"):
            out[str(group.get("class"))] = list(group)
    return out


def circles(views: Views, view: str, style: str) -> list[float]:
    """The radii of a view's circles drawn in one style."""
    return sorted(
        float(str(c.get("r")))
        for c in shapes(views, view).get(style, [])
        if c.tag == f"{SVG}circle"
    )


def check_every_value_shown(
    case: unittest.TestCase, report: SpecReport, views: Views, label: object
) -> None:
    """The property every draft keeps: each placed item drawn with each value shown, each line true."""
    assert report.spec is not None and report.layout is not None
    layout = report.layout
    for view in views.views:
        if view.svg:
            ET.fromstring(view.svg)  # well-formed
    for it in report.spec.items:
        category = KINDS[it.kind].category
        if category is Category.MODIFY:
            case.assertEqual(views.shown(it.id), frozenset(it.fields), (label, it.id))
            continue
        copies = layout.instances.get(it.id, [])
        placed = bool(copies) and (
            category is Category.CUT or any(c.lo is not None for c in copies)
        )
        case.assertEqual(it.id not in views.not_drawn, placed, (label, it.id))
        if not placed:
            continue
        case.assertLessEqual(held(it), views.shown(it.id), (label, it.kind, it.id))
        for d in views.dimensions():
            if d.item != it.id or d.form != "line" or len(d.fields) != 1:
                continue
            assert d.measured is not None
            name = d.fields[0]
            value: object = it.fields.get(name)
            place = it.fields.get("place")
            if name.startswith("place.") and isinstance(place, Place):
                parts = name.split(".")
                position = place.axes.get(parts[1]) if len(parts) == 2 else None
                if position is not None and position.mode != "centred":
                    value = position.distance
                elif len(parts) == 3 and place.pattern is not None:
                    value = place.pattern.values.get(parts[2])
            if isinstance(value, Value):
                case.assertAlmostEqual(
                    d.measured, abs(mm(value)), 6, (label, it.id, name, d.text)
                )


class EveryValueIsShown(unittest.TestCase):
    def test_on_random_drafts(self) -> None:
        drawn = 0
        for seed in range(600):
            spec, _ = read_draft(random_draft(random.Random(seed)))
            if spec is None:
                continue
            report = SpecReport(spec, solve(spec), (), (), (), (), None)
            views = render_views(report)
            check_every_value_shown(self, report, views, seed)
            drawn += len(spec.items) - len(views.not_drawn) - len(views.words)
        self.assertGreater(
            drawn, 400
        )  # the property held over many drawn items, not a few

    def test_on_every_kind_the_solver_places(self) -> None:
        cases = {
            kind: [*items, hole(items[-1]["id"], "+z", 2)]
            for kind, items in EXAMPLES.items()
        }
        cases["radial"] = [item("rod", "cylinder", diameter=a(20), length=a(40), axis=pick("z")),
                           item("h", "hole", on=on("rod", "side"), diameter=a(4), depth=through(),
                                place={"z": at("-z", 10), "angle": degrees(30)})]  # fmt: skip
        cases["shelled"] = [item("box", "block", length=a(60), width=a(40), height=a(30)), shell("box", 2, "+z"),
                            item("r", "rib", on=on("box", "inner -z"), length=a(30), thickness=a(2), height=a(10),
                                 along=pick("x")),
                            item("f", "fillet", edges={"of": "box", "which": "vertical", "words": [2]}, radius=a(3))]  # fmt: skip
        for kind, items in cases.items():
            views, report = views_of(*items)
            check_every_value_shown(self, report, views, kind)

    def test_on_generated_parts_measured_to_an_edge(self) -> None:
        """Generated parts with items measured to an edge that is no symmetric box's: turned in their face (seeds 6, 10,
        33, 60), and an extrusion's or a revolution's outline, which reaches back and forth from its point unevenly
        (39, 117). Each line from an edge to an item's edge is drawn to where the solver measured it."""
        from forge_eval.generator import draft_of, generate
        from forge_spec.words import number_words

        for seed in (6, 10, 33, 39, 60, 117):
            case = generate(seed)
            report = check_draft(number_words(case.brief), draft_of(case.items), strict=True)
            check_every_value_shown(self, report, render_views(report), seed)

    def test_on_the_corpus_drafts(self) -> None:
        for make in (plate_draft, flange_draft, bracket_draft):
            brief, raw = make()
            report = check_draft(brief, raw)
            self.assertEqual(report.problems, (), make.__name__)
            check_every_value_shown(self, report, render_views(report), make.__name__)


class EachSizeIsOnTheViewThatShowsIt(unittest.TestCase):
    def test_a_plate_and_its_holes(self) -> None:
        brief, raw = plate_draft()
        views = render_views(check_draft(brief, raw))
        self.assertEqual({d.text for d in lines(views, "top", "plate")}, {"70", "50"})
        self.assertEqual([d.text for d in lines(views, "front", "plate")], ["4"])
        self.assertEqual({d.text for d in lines(views, "top", "holes")} - {"35 (centred, assumed)", "25 (centred, assumed)"},
                         {"56", "36"})  # fmt: skip
        self.assertEqual(
            note(views, "holes").text, "holes: 4 x hole Ø4, through, 1 at each place"
        )
        self.assertEqual(views.overall, (70.0, 50.0, 4.0))

    def test_a_post_its_footprint_from_above_and_its_height_from_the_front(
        self,
    ) -> None:
        views, _ = views_of(PLATE, item("p", "post", on=on("plate", "+z"), length=a(10), width=a(8), height=a(5),
                                         place={"x": at("-x", 20), "y": at("+y", 6, "edge")}))  # fmt: skip
        top = {d.fields: (d.text, d.measured) for d in lines(views, "top", "p")}
        self.assertEqual(top, {("length",): ("10", 10.0), ("width",): ("8", 8.0),
                               ("place.x",): ("20", 20.0), ("place.y",): ("6", 6.0)})  # fmt: skip
        self.assertEqual(
            [(d.fields, d.text) for d in lines(views, "front", "p")],
            [(("height",), "5")],
        )

    def test_a_tab_sticking_out_along_x_has_that_length_from_above(self) -> None:
        views, _ = views_of(*EXAMPLES["tab"])
        self.assertIn(
            (("length",), "10"), [(d.fields, d.text) for d in lines(views, "top", "c")]
        )
        self.assertIn(
            (("thickness",), "2"),
            [(d.fields, d.text) for d in lines(views, "front", "c")],
        )

    def test_a_round_thing_noted_looking_down_its_axis(self) -> None:
        views, _ = views_of(item("tube", "tube", outer_diameter=a(30), inner_diameter=a(20), length=a(50),
                                 axis=pick("x")))  # fmt: skip
        (side,) = [v for v in views.views if v.name == "side"]
        self.assertIn(
            "tube: tube Ø30 outside, Ø20 bore", [d.text for d in side.dimensions]
        )
        self.assertEqual(
            [(d.fields, d.text) for d in lines(views, "top", "tube")],
            [(("length",), "50")],
        )
        self.assertEqual(circles(views, "side", "visible"), [10.0, 15.0])

    def test_a_cut_noted_on_the_view_that_looks_into_it(self) -> None:
        views, _ = views_of(PLATE, item("s", "slot", on=on("plate", "-y"), length=a(20), width=a(2), along=pick("x"),
                                        ends=pick("round"), depth=a(3)))  # fmt: skip
        (front,) = [v for v in views.views if v.name == "front"]
        self.assertIn(
            "s: slot 20 long, 2 wide, round ends, 3 deep",
            [d.text for d in front.dimensions],
        )
        (rect,) = [e for e in shapes(views, "front")["visible"] if e.get("rx")]
        self.assertEqual(
            (rect.get("width"), rect.get("height"), rect.get("rx")), ("20", "2", "1")
        )


class PlacesAreMeasuredAsTheySay(unittest.TestCase):
    def place(self, **place: Any) -> list[Dimension]:
        views, _ = views_of(
            PLATE,
            item(
                "h",
                "hole",
                on=on("plate", "+z"),
                diameter=a(6),
                depth=through(),
                place=place,
            ),
        )
        return lines(views, "top", "h")

    def test_from_an_edge_to_the_centre_or_the_near_edge(self) -> None:
        found = {
            d.fields: (d.text, d.measured)
            for d in self.place(x=at("+x", 10), y=at("-y", 7, "edge"))
        }
        self.assertEqual(found, {("place.x",): ("10", 10.0), ("place.y",): ("7", 7.0)})

    def test_from_the_centre_by_an_offset(self) -> None:
        found = {
            d.fields: (d.text, d.measured)
            for d in self.place(x={"offset": a(-12)}, y=centred())
        }
        self.assertEqual(
            found,
            {
                ("place.x",): ("-12", 12.0),
                ("place.y",): ("25 (centred, assumed)", 25.0),
            },
        )

    def test_an_offset_of_nothing_is_said_in_the_note(self) -> None:
        views, _ = views_of(PLATE, item("h", "hole", on=on("plate", "+z"), diameter=a(6), depth=through(),
                                        place={"x": {"offset": a(0)}, "y": at("-y", 10)}))  # fmt: skip
        self.assertNotIn(("place.x",), [d.fields for d in lines(views, "top", "h")])
        self.assertIn("offset 0 along X from the centre", note(views, "h").text)
        self.assertIn("place.x", views.shown("h"))

    def test_round_a_side_along_its_axis_and_at_an_angle(self) -> None:
        views, _ = views_of(item("rod", "cylinder", diameter=a(20), length=a(40), axis=pick("z")),
                            item("h", "hole", on=on("rod", "side"), diameter=a(4), depth=a(5),
                                 place={"z": at("+z", 8), "angle": degrees(90)}))  # fmt: skip
        self.assertEqual([(d.fields, d.text, d.measured) for d in lines(views, "front", "h")],
                         [(("place.z",), "8", 8.0)])  # fmt: skip
        self.assertEqual(
            note(views, "h").text, "h: hole Ø4, 5 deep, at 90° from +X round Z"
        )

    def test_a_pattern_by_its_steps_and_its_centre(self) -> None:
        views, _ = views_of(PLATE, item("g", "hole", on=on("plate", "+z"), diameter=a(2), depth=through(),
                                        place={"x": at("-x", 30), "pattern": {"grid": {
                                            "count_x": n(3), "count_y": n(2), "pitch_x": a(7), "pitch_y": a(9)}}}))  # fmt: skip
        found = {d.fields: (d.text, d.measured) for d in lines(views, "top", "g")}
        self.assertEqual(found, {("place.x",): ("30", 30.0), (): ("25 (centred, assumed)", 25.0),
                                 ("place.pattern.pitch_x",): ("7 apart", 7.0),
                                 ("place.pattern.pitch_y",): ("9 apart", 9.0)})  # fmt: skip
        self.assertTrue(
            note(views, "g").text.startswith("g: 6 x hole Ø2, through, a grid of 3 x 2")
        )
        self.assertEqual(
            len(shapes(views, "top")["centre"]), 2
        )  # the centre mark the place is measured to


class HiddenAndSeen(unittest.TestCase):
    def test_a_blind_hole_from_the_far_side_is_dashed(self) -> None:
        views, _ = views_of(PLATE, hole("plate", "-z", 6, depth=a(2)))
        self.assertEqual(circles(views, "top", "hidden"), [3.0])
        self.assertEqual(circles(views, "top", "visible"), [])

    def test_a_hole_right_through_shows_from_both_sides(self) -> None:
        views, _ = views_of(
            PLATE,
            hole("plate", "-z", 6, counterbore={"diameter": a(10), "depth": a(2)}),
        )
        self.assertEqual(circles(views, "top", "visible"), [3.0])
        self.assertEqual(
            circles(views, "top", "hidden"), [5.0]
        )  # its counterbore is on the far side

    def test_what_hangs_under_a_plate_is_dashed_from_above(self) -> None:
        views, _ = views_of(
            PLATE,
            item(
                "p", "post", on=on("plate", "-z"), length=a(10), width=a(8), height=a(5)
            ),
        )
        hidden = [e for e in shapes(views, "top")["hidden"] if e.tag == f"{SVG}rect"]
        self.assertEqual(
            [(e.get("width"), e.get("height")) for e in hidden], [("10", "8")]
        )

    def test_a_hollow_shows_through_its_opening_and_hides_what_is_in_it(self) -> None:
        views, _ = views_of(item("box", "block", length=a(60), width=a(40), height=a(30)), shell("box", 2, "+z"),
                            item("r", "rib", on=on("box", "inner -z"), length=a(30), thickness=a(2), height=a(10),
                                 along=pick("x")))  # fmt: skip
        top = {
            (e.get("width"), e.get("height")) for e in shapes(views, "top")["visible"]
        }
        self.assertLessEqual({("60", "40"), ("56", "36"), ("30", "2")}, top)
        front = {
            (e.get("width"), e.get("height")) for e in shapes(views, "front")["hidden"]
        }
        self.assertLessEqual({("56", "28"), ("30", "10")}, front)

    def test_nothing_is_hidden_behind_a_curve_it_might_not_cover(self) -> None:
        # The corner of the disc's bounding square doesn't cover the post: it is drawn as seen.
        views, _ = views_of(item("disc", "cylinder", diameter=a(40), length=a(5), axis=pick("z")),
                            item("p", "post", on=on("disc", "-end"), length=a(4), width=a(4), height=a(3),
                                 place={"x": {"offset": a(18)}, "y": {"offset": a(18)}}))  # fmt: skip
        self.assertIn(
            ("4", "4"),
            {
                (e.get("width"), e.get("height"))
                for e in shapes(views, "top")["visible"]
            },
        )


class TheOverallSize(unittest.TestCase):
    def test_labelled_where_no_item_gives_it(self) -> None:
        views, _ = views_of(*EXAMPLES["boss"])
        overall = [d for v in views.views for d in v.dimensions if d.item == ""]
        self.assertEqual(
            [(d.fields, d.text, d.measured) for d in overall],
            [(("overall.z",), "9 overall", 9.0)],
        )

    def test_not_drawn_where_an_item_gives_it(self) -> None:
        for items in (EXAMPLES["block"], EXAMPLES["cylinder"], EXAMPLES["pocket"]):
            views, _ = views_of(*items)
            self.assertEqual(
                [d for d in views.dimensions() if d.item == ""], [], items[-1]["kind"]
            )


class WhatIsNotDrawn(unittest.TestCase):
    def test_an_item_the_layout_couldnt_place(self) -> None:
        views, _ = views_of(PLATE, hole("plate", "+end", 4))
        self.assertEqual(views.not_drawn, ("h",))
        self.assertEqual(views.shown("h"), frozenset())

    def test_an_extrusion_and_a_revolution_from_their_outlines(self) -> None:
        profile = {"start": [0, 0], "segments": [{"line_to": [10, 0]}, {"line_to": [10, 4]},
                                                 {"arc_to": [4, 10], "centre": [4, 4]}, {"line_to": [0, 10]},
                                                 {"line_to": [0, 0]}], "from": {"words": [2]}}  # fmt: skip
        views, _ = views_of(item("e", "extrusion", profile=profile, length=a(5), axis=pick("z")))
        self.assertEqual((views.not_drawn, views.overall), ((), (10.0, 10.0, 5.0)))
        self.assertEqual(views.shown("e"), {"profile", "length"})
        top = next(v for v in views.views if v.name == "top")
        (outline,) = re.findall(r'<polygon points="([^"]+)"/>', top.svg.split('class="dimensions"')[0])
        self.assertGreater(len(outline.split()), 20)  # its arc followed every few degrees
        turned, _ = views_of(item("r", "revolution", profile=profile, axis=pick("z")))
        self.assertEqual((turned.not_drawn, turned.overall), ((), (20.0, 20.0, 10.0)))
        self.assertEqual(turned.shown("r"), {"profile"})
        front = next(v for v in turned.views if v.name == "front")
        drawn = front.svg.split('class="dimensions"')[0]
        self.assertEqual(len(re.findall("<polygon ", drawn)), 2)  # the half outline, and mirrored

    def test_roundings_are_given_in_the_fixed_wording(self) -> None:
        brief, raw = plate_draft()
        raw["items"].append({"id": "round", "kind": "fillet", "words": raw["items"][0]["words"],
                             "edges": {"of": "plate", "which": "vertical", "words": raw["items"][0]["words"]},
                             "radius": {"value": 3, "unit": "mm", "from": {"assumed": "for the test"}}})  # fmt: skip
        report = check_draft(brief, raw)
        (words,) = render_views(report).words
        self.assertEqual(
            words.text, "Round the vertical edges of plate to R3 mm (assumed) (round)"
        )
        self.assertIn(words.text, " ".join(render(report, brief).lines))


class TheDrawings(unittest.TestCase):
    def test_at_one_scale_in_the_pages_own_colour(self) -> None:
        brief, raw = bracket_draft()
        views = render_views(check_draft(brief, raw))
        scales = set()
        for view in views.views:
            root = ET.fromstring(view.svg)
            box = [float(x) for x in str(root.get("viewBox")).split()]
            scales.add(float(str(root.get("width"))) / box[2])
            colours = set(re.findall(r'(?:stroke|fill)="([^"]+)"', view.svg))
            self.assertLessEqual(colours, {"currentColor", "none"}, view.name)
            self.assertEqual(
                re.findall(r"#[0-9a-fA-F]{3,6}", view.svg), ["#ffffff"]
            )  # the halo's fallback only
        self.assertLess(max(scales) - min(scales), 1e-3 * max(scales))

    def test_every_text_is_escaped(self) -> None:
        views, _ = views_of(PLATE, item("t", "text", on=on("plate", "+z"), text={"text": "<b>A&B</b>", "from": {"words": [2]}},
                                        height=a(5), depth=a(0.5), mode=pick("engrave")))  # fmt: skip
        for view in views.views:
            self.assertNotIn("<b>", view.svg)
            ET.fromstring(view.svg)
        (letters,) = [
            e
            for e in ET.fromstring(views.views[0].svg).iter(f"{SVG}text")
            if e.get("textLength")
        ]
        self.assertEqual(
            (letters.text, letters.get("textLength")), ("<b>A&B</b>", "51.829")
        )

    def test_the_same_each_time(self) -> None:
        brief, raw = flange_draft()
        report = check_draft(brief, raw)
        self.assertEqual(render_views(report), render_views(report))

    def test_copies_seen_edge_on_drawn_once(self) -> None:
        views, _ = views_of(PLATE, item("g", "hole", on=on("plate", "+z"), diameter=a(1), depth=through(),
                                        place={"pattern": {"grid": {"count_x": n(40), "count_y": n(30),
                                                                    "pitch_x": a(1.5), "pitch_y": a(1.5)}}}))  # fmt: skip
        self.assertEqual(len(circles(views, "top", "visible")), 1200)
        hidden = shapes(views, "front")["hidden"]
        self.assertEqual(
            len(hidden), 40 * 4
        )  # a bore's four lines per column, not per hole


class ThePage(unittest.TestCase):
    def test_views_after_what_to_settle_and_before_the_brief(self) -> None:
        from forge_cli.spec_page import spec_page

        brief, raw = bracket_draft()
        page = spec_page(check_draft(brief, raw), brief, status="round 1")
        self.assertLess(
            page.index("<h2>Assumed (check these first)</h2>"),
            page.index("<h2>Views</h2>"),
        )
        self.assertLess(page.index("<h2>Views</h2>"), page.index("<h2>Your brief</h2>"))
        self.assertEqual(page.count("<svg "), 3)
        self.assertIn("--halo: var(--panel)", page)

    def test_what_is_in_words_and_what_isnt_drawn(self) -> None:
        from forge_cli.spec_page import spec_page

        brief, raw = plate_draft()
        raw["items"].append({"id": "round", "kind": "fillet", "words": raw["items"][0]["words"],
                             "edges": {"of": "plate", "which": "vertical", "words": raw["items"][0]["words"]},
                             "radius": {"value": 3, "unit": "mm", "from": {"assumed": "for the test"}}})  # fmt: skip
        page = spec_page(check_draft(brief, raw), brief, status="round 1")
        self.assertIn("<h2>Shown in words</h2><ul><li>Round the vertical edges of plate to R3 mm (assumed) (round)</li>",
                      page)  # fmt: skip
        self.assertNotIn("<h2>Not drawn</h2>", page)


def centre_of(element: ET.Element) -> tuple[float, float]:
    """Where a drawn outline is, as the mean of its points; the SVG's y runs down."""
    points = [
        tuple(float(x) for x in p.split(","))
        for p in str(element.get("points")).split()
    ]
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(
        points
    )


class WhatIsCutRightThroughIsSeenThrough(unittest.TestCase):
    """Fifth review: a hole right through a plate let nothing behind it be seen."""

    POST = item("p", "post", on=on("plate", "-z"), length=a(4), width=a(4), height=a(5))

    def rects(self, views: Views, style: str) -> list[tuple[str | None, str | None]]:
        return [
            (e.get("width"), e.get("height"))
            for e in shapes(views, "top").get(style, [])
            if e.tag == f"{SVG}rect"
        ]

    def test_what_hangs_under_a_hole_is_seen_through_it(self) -> None:
        views, _ = views_of(PLATE, hole("plate", "+z", 10), self.POST)
        self.assertIn(("4", "4"), self.rects(views, "visible"))
        self.assertNotIn(("4", "4"), self.rects(views, "hidden"))

    def test_a_hole_elsewhere_lets_nothing_be_seen(self) -> None:
        views, _ = views_of(
            PLATE,
            hole("plate", "+z", 10, place={"x": at("+x", 8), "y": at("+y", 8)}),
            self.POST,
        )
        self.assertEqual(self.rects(views, "hidden"), [("4", "4")])


class EachCircleIsSeenAsFarAsItReaches(unittest.TestCase):
    """Fifth review: a counterbore was judged by its bore, an exit by the mouth."""

    def test_a_counterbore_or_countersink_wider_than_what_covers_its_bore(self) -> None:
        # An arm reaches over the hole: it covers the bore, not what widens its mouth.
        for widening in ({"counterbore": {"diameter": a(20), "depth": a(2)}},
                         {"countersink": {"diameter": a(20), "angle": degrees(90)}}):  # fmt: skip
            views, _ = views_of(PLATE, item("tower", "block", on=on("plate", "+z"), length=a(6), width=a(6), height=a(20),
                                            place={"x": at("-x", 3, "edge"), "y": centred()}),
                                item("arm", "post", on=on("tower", "+x"), length=a(8), width=a(4), height=a(30)),
                                hole("plate", "+z", 6, **widening))  # fmt: skip
            self.assertEqual((circles(views, "top", "visible"), circles(views, "top", "hidden")), ([10.0], [3.0]),
                             widening)  # fmt: skip

    def test_a_hole_at_an_angle_comes_out_where_it_comes_out(self) -> None:
        views, _ = views_of(item("rod", "cylinder", diameter=a(20), length=a(40), axis=pick("x")),
                            item("h", "hole", on=on("rod", "side"), diameter=a(4), depth=through(),
                                 place={"angle": degrees(45)}))  # fmt: skip
        # It goes in at +Y+Z and comes out at -Y-Z: from above, the way in is seen;
        # from the front, the way out.
        for view, seen_at, hidden_at in (("top", -7.07, 7.07), ("front", 7.07, -7.07)):
            drawn = shapes(views, view)
            (seen,) = [e for e in drawn["visible"] if e.tag == f"{SVG}polygon"]
            (hidden,) = [e for e in drawn["hidden"] if e.tag == f"{SVG}polygon"]
            self.assertAlmostEqual(centre_of(seen)[1], seen_at, delta=0.1, msg=view)
            self.assertAlmostEqual(centre_of(hidden)[1], hidden_at, delta=0.1, msg=view)

    def test_what_stands_before_the_way_in_doesnt_hide_the_way_out(self) -> None:
        # Through a boss at 45 degrees: in at +X+Y, out at -X-Y, which faces the front.
        # A post in front of the boss stands before the way in, not the way out.
        views, _ = views_of(PLATE, item("b", "boss", on=on("plate", "+z"), diameter=a(20), height=a(20)),
                            item("h", "hole", on=on("b", "side"), diameter=a(4), depth=through(),
                                 place={"angle": degrees(45), "z": at("+z", 8)}),
                            item("p", "post", on=on("plate", "+z"), length=a(8), width=a(5), height=a(30),
                                 place={"x": {"offset": a(7)}, "y": {"offset": a(-17.5)}}))  # fmt: skip
        drawn = shapes(views, "front")
        ((seen_u, _),) = [
            centre_of(e) for e in drawn["visible"] if e.tag == f"{SVG}polygon"
        ]
        ((hidden_u, _),) = [
            centre_of(e) for e in drawn["hidden"] if e.tag == f"{SVG}polygon"
        ]
        self.assertAlmostEqual(seen_u, -7.07, delta=0.01)
        self.assertAlmostEqual(hidden_u, 7.07, delta=0.01)


class RoundThingsAsTheirFieldsGiveThem(unittest.TestCase):
    def test_a_cone_wider_at_its_top(self) -> None:
        from forge_spec.render_views import _inside

        views, report = views_of(item("c", "cone", base_diameter=a(10), top_diameter=a(30), length=a(20),
                                      axis=pick("z")))  # fmt: skip
        self.assertEqual(
            (circles(views, "top", "visible"), circles(views, "top", "hidden")),
            ([15.0], [5.0]),
        )
        sides = {str(e.get("points")) for e in shapes(views, "front")["visible"]}
        self.assertLessEqual({"-5,0 -15,-20", "5,0 15,-20"}, sides)
        self.assertEqual(views.overall, (30.0, 30.0, 20.0))
        spec, layout = report.spec, report.layout
        assert spec is not None and layout is not None
        # What it hides is the square in its narrow end, all its length.
        ((lo, hi),) = _inside(spec.items[0], layout.instances["c"][0], layout)
        self.assertAlmostEqual(hi[0] - lo[0], 10 / math.sqrt(2))

    def test_a_tab_all_round_end(self) -> None:
        views, _ = views_of(PLATE, item("t", "tab", on=on("plate", "+z"), width=a(10), length=a(5), thickness=a(2),
                                        end=pick("round"), thickness_along=pick("y")))  # fmt: skip
        front = shapes(views, "front")["visible"]
        (disc,) = [e for e in front if e.tag == f"{SVG}polygon"]
        points = [
            tuple(float(x) for x in p.split(","))
            for p in str(disc.get("points")).split()
        ]
        self.assertEqual(
            (min(p[0] for p in points), max(p[0] for p in points)), (-5.0, 5.0)
        )
        self.assertEqual(
            (min(p[1] for p in points), max(p[1] for p in points)), (-9.0, -4.0)
        )
        self.assertEqual(
            [e for e in front if e.tag == f"{SVG}rect" and e.get("width") == "10"], []
        )
        self.assertEqual(note(views, "t").text, "t: tab (round end)")

    def test_no_point_twice_running(self) -> None:
        rng = random.Random(5)
        for _ in range(60):
            spec, read = read_draft(random_draft(rng))
            if spec is None or read.faults:
                continue
            for view in render_views(
                SpecReport(spec, solve(spec), (), (), (), (), None)
            ).views:
                for element in ET.fromstring(view.svg).iter():
                    if element.get("points"):
                        points = str(element.get("points")).split()
                        self.assertFalse(
                            any(x == y for x, y in itertools.pairwise(points)),
                            view.name,
                        )
                        if element.tag == f"{SVG}polygon":
                            self.assertNotEqual(points[0], points[-1], view.name)


class SaidAsItIs(unittest.TestCase):
    def test_a_pattern_of_one_says_its_count(self) -> None:
        views, _ = views_of(PLATE, item("h", "hole", on=on("plate", "+z"), diameter=a(4), depth=through(),
                                        place={"pattern": {"circle": {"count": n(1), "diameter": a(20)}}}))  # fmt: skip
        self.assertTrue(
            note(views, "h").text.endswith(", 1 in the pattern"), note(views, "h").text
        )
        self.assertIn("place.pattern.count", views.shown("h"))

    def test_round_a_side_equally_spaced_from_where(self) -> None:
        views, _ = views_of(item("rod", "cylinder", diameter=a(20), length=a(40), axis=pick("z")),
                            item("h", "hole", on=on("rod", "side"), diameter=a(4), depth=a(5),
                                 place={"z": at("+z", 0, "edge"), "pattern": {"circle": {"count": n(4)}}}))  # fmt: skip
        self.assertEqual(note(views, "h").text, "h: 4 x hole Ø4, 5 deep, 0 from the +z end to its near edge, "
                         "equally spaced round Z, the first at 0° from +X round Z (assumed)")  # fmt: skip

    def test_a_corner_inset_says_along_which_axis(self) -> None:
        views, _ = views_of(PLATE, item("h", "hole", on=on("plate", "+z"), diameter=a(4), depth=through(),
                                        place={"pattern": {"corners": {"inset_x": a(0), "inset_y": a(6)}}}))  # fmt: skip
        self.assertIn("0 in from the edges along X", note(views, "h").text)


Point = tuple[float, float, float]
Box = tuple[Point, Point]


def random_box(rng: random.Random, reach: float) -> Box:
    lo = [rng.uniform(-20, 100) for _ in range(3)]
    hi = [x + rng.uniform(0, reach) for x in lo]
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def asking_every(frame: Any, solids: list[tuple[Any, Point, Point]], windows: list[tuple[int, Point, Point]],
                 lo: tuple[float, float], hi: tuple[float, float], near: float, own: Any) -> bool:  # fmt: skip
    """Whether a region is hidden, asked of every solid and every window: what the grid must answer."""
    from forge_spec.geometry import EPS

    u: int = frame.u
    v: int = frame.v
    w: int = frame.w
    facing: int = frame.facing

    def covers(slo: Point, shi: Point) -> bool:
        return (
            slo[u] <= lo[0] + EPS
            and shi[u] >= hi[0] - EPS
            and slo[v] <= lo[1] + EPS
            and shi[v] >= hi[1] - EPS
        )

    def pierced(slo: Point, shi: Point) -> bool:
        return any(k == w and wlo[u] < hi[0] - EPS and whi[u] > lo[0] + EPS and wlo[v] < hi[1] - EPS
                   and whi[v] > lo[1] + EPS and all(wlo[i] < shi[i] - EPS and whi[i] > slo[i] + EPS for i in range(3))
                   for k, wlo, whi in windows)  # fmt: skip

    return any(key != own and covers(slo, shi) and (slo[w] if facing > 0 else shi[w]) * facing >= near * facing - EPS
               and not pierced(slo, shi) for key, slo, shi in solids)  # fmt: skip


class WhatHidesWhatIsAskedOfWhatIsNear(unittest.TestCase):
    """Fifth review: whether a thing was hidden was asked of every solid of the part, for every copy."""

    def test_the_same_answer_as_asking_every_solid(self) -> None:
        from forge_spec.render_views import _FRAMES, _Canvas, _Occlusion

        rng = random.Random(7)
        for frame in _FRAMES:
            solids = [
                (("s", k), *random_box(rng, rng.choice((5, 40, 150))))
                for k in range(300)
            ]
            windows = [
                (rng.randrange(3), *random_box(rng, rng.choice((2, 30))))
                for _ in range(120)
            ]
            # Things reach past the part both ways: filed at its edge, they are found all the same.
            hiding = _Occlusion(
                _Canvas(frame, 1.0, 2), solids, windows, ((0, 0, 0), (100, 100, 100))
            )
            hidden = 0
            for _ in range(3000):
                lo, hi = random_box(rng, rng.choice((0, 3, 60)))
                region = (lo[frame.u], lo[frame.v]), (hi[frame.u], hi[frame.v])
                near, own = (
                    rng.uniform(-30, 130),
                    rng.choice((None, ("s", rng.randrange(300)))),
                )
                found = hiding.hides(*region, near, own)
                self.assertEqual(found, asking_every(frame, solids, windows, *region, near, own),
                                 (frame.name, region, near, own))  # fmt: skip
                hidden += found
            self.assertGreater(
                hidden, 150, frame.name
            )  # both answers were given, often

    def test_many_things_quickly(self) -> None:
        big = item("plate", "block", length=a(600), width=a(500), height=a(4))
        grid = {
            "pattern": {
                "grid": {
                    "count_x": n(60),
                    "count_y": n(50),
                    "pitch_x": a(9),
                    "pitch_y": a(9),
                }
            }
        }
        posts = item(
            "p",
            "post",
            on=on("plate", "+z"),
            length=a(3),
            width=a(3),
            height=a(3),
            place=grid,
        )
        holes = item(
            "h", "hole", on=on("plate", "-z"), diameter=a(2), depth=a(2), place=grid
        )
        started = time.perf_counter()
        views, _ = views_of(big, posts, holes)
        self.assertLess(time.perf_counter() - started, 10.0)
        self.assertEqual(len(circles(views, "top", "hidden")), 3000)

    def test_a_hole_far_wider_than_its_part_quickly(self) -> None:
        started = time.perf_counter()
        views, _ = views_of(item("b", "sphere", diameter=a(1), portion=pick("upper_half")),
                            item("h", "hole", on=on("b", "-end"), diameter=a(108), depth=a(5)))  # fmt: skip
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertNotIn("h", views.not_drawn)


class ThePageAtOneScale(unittest.TestCase):
    def test_a_view_is_never_shrunk_to_fit(self) -> None:
        from forge_cli.spec_page import spec_page

        brief, raw = bracket_draft()
        page = spec_page(check_draft(brief, raw), brief, status="round 1")
        (rule,) = re.findall(r"\.views svg \{[^}]*\}", page)
        self.assertNotIn("max-width", rule)
        (figure,) = re.findall(r"\.views figure \{[^}]*\}", page)
        self.assertIn("overflow-x: auto", figure)  # a wide one scrolls instead


if __name__ == "__main__":
    unittest.main()
