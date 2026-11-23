"""V1's 27 false passes, reconstructed: each brief, what V1 built and passed, why, and the sources (docs/V2-stage4.md, 14.3 and 16).

They were never written down as a list. Each is put together here from
V1's fix logs (docs/fixlist_v6.txt to fixlist_v8.txt), its recorded runs
(tests/fixtures/real_runs) and its tests, which name the runs and say what
was wrong; how sure each reconstruction is, and why, is said with it.

For each, :mod:`test_v2_false_passes` builds the **right part**, from a V2
spec of the brief (the validation suite's own draft, tests/v2_suite_specs.py,
where the brief is the suite's; else one drafted here, citing its words),
and the **wrong part**, as V1's document drew it (its features and their
sizes, read from the recorded run where there is one, else from what the
sources say it was), made with OpenCascade in V2's frame: the first body
centred on the origin along x and y, standing on z = 0 (V1 centred its
first box on the origin; the part is moved up by half its height, and
turned where V1 ran its length along y). The right part passes the right
spec's judge; the wrong one fails it, and the test names what caught it.

Five are no wrong shape: a brief that is no part (21), a washer nobody
sized (22), and two shipped files (23, 24) are caught where V2 catches them
(the accounting and the assumption --auto stops at; the judge every
released file is put through); the steel cube shelled to pass its weight (19) is a wrong shape the
judge catches, and the right one is left to its mass requirement (stage 6).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge_spec import NumberedBrief, number_words
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said, span
from v2_suite_specs import (
    DRAFTS,
    formula,
    item,
    left_out,
    middle,
    no_load,
    on,
    suite,
    through,
)

Draft = dict[str, Any]
Vec = tuple[float, float, float]


@dataclass(frozen=True)
class FalsePass:
    """One of V1's false passes: the brief, what V1 built and why it passed it, the sources, and how V2 catches it."""

    number: int
    case: str
    brief: str
    #: What V1 built, with its sizes.
    built: str
    #: Why V1's checks passed it.
    why: str
    #: Where that is said: files with lines, tests by name.
    sources: tuple[str, ...]
    #: How sure the reconstruction is: "sure", "fairly sure" or "least sure", and why.
    sure: str
    #: The recorded run that shows it (tests/fixtures/real_runs), if any.
    run: str | None
    #: The right part's spec: the validation suite's draft of the brief (its id), or one drafted here.
    right: str | Callable[[NumberedBrief], Draft]
    #: The wrong part, made in V2's frame (None: no wrong shape to make; :attr:`caught` says where V2 stops it).
    wrong: Callable[[], Any] | None
    #: Where V2 catches it: "judge" (the wrong part fails the right spec's judge), "the judge of the file shipped"
    #: (every file Forge releases is judged as a view of the part), "the accounting", "the assumptions --auto stops at".
    caught: str = "judge"
    #: What in the judge must fail it: a check's id (its item and field), or a detector of the view.
    by: tuple[str, ...] = ()
    #: Where V2 can't make the brief as given yet (it ends UNABLE: the brief's dome sits on its side, 4b.0c item 1), the
    #: brief its right part is drafted from for the judge: the same part as V2 makes it, its judge shown failing the
    #: wrong one. Its key for ``forge eval-false-passes`` is then None: any part released for the brief is wrong.
    judged_on: str | None = None


# ----------------------------------------------------------------------
# Making the wrong parts: OpenCascade's own solids, in V2's frame
# ----------------------------------------------------------------------
def box(lo: Vec, hi: Vec) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*lo), gp_Pnt(*hi)).Shape()


def rod(base: Vec, axis: Vec, diameter: float, length: float) -> Any:
    """A cylinder from ``base`` along ``axis``."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(*base), gp_Dir(*axis)), diameter / 2, length
    ).Shape()


def through_rod(at: Vec, axis: Vec, diameter: float, reach: float = 500.0) -> Any:
    """A cylinder through ``at`` along ``axis`` both ways: a hole right through whatever it is cut from."""
    start = tuple(a - reach * d for a, d in zip(at, axis, strict=True))
    return rod((start[0], start[1], start[2]), axis, diameter, 2 * reach)


def ball(centre: Vec, diameter: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeSphere(gp_Pnt(*centre), diameter / 2).Shape()


def ring(centre: Vec, middle_diameter: float, section: float) -> Any:
    """A torus lying flat: its section's middle on a circle ``middle_diameter`` across."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeTorus
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeTorus(
        gp_Ax2(gp_Pnt(*centre), gp_Dir(0, 0, 1)), middle_diameter / 2, section / 2
    ).Shape()


def pushed(points: Sequence[Sequence[float]], low: float, high: float) -> Any:
    """An outline in the xy plane (forge_occ.profiles.outline's points), pushed from z = ``low`` to ``high``."""
    from forge_occ.geom import Frame
    from forge_occ.make import prism
    from forge_occ.profiles import outline

    face = outline(points).face(
        Frame.through((0.0, 0.0, low), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    )
    return prism(face, (0.0, 0.0, high - low)).shape


def plus(*shapes: Any) -> Any:
    from forge_occ.make import boolean, unify

    return unify(boolean("union", [shapes[0]], list(shapes[1:])).shape).shape


def minus(shape: Any, *tools: Any) -> Any:
    from forge_occ.make import boolean, unify

    return unify(boolean("subtract", [shape], list(tools)).shape).shape


def common(shape: Any, other: Any) -> Any:
    from forge_occ.make import boolean, unify

    return unify(boolean("intersect", [shape], [other]).shape).shape


def rounded(shape: Any, size: float, chosen: Callable[[Any], bool]) -> Any:
    """The shape's edges ``chosen`` (by their middle point, (x, y, z)) rounded by ``size``."""
    from forge_occ.make import round_edges
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    edges: list[Any] = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge(explorer.Current())
        curve = BRepAdaptor_Curve(edge)
        p = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2)
        if chosen((p.X(), p.Y(), p.Z())) and not any(edge.IsSame(e) for e in edges):
            edges.append(edge)
        explorer.Next()
    assert edges, "no edge chosen"
    return round_edges(shape, edges, size).shape


def near(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


# ----------------------------------------------------------------------
# The right parts of briefs the suite doesn't hold
# ----------------------------------------------------------------------
HOLLOW_CUBE = "A 30 mm cube in PLA, hollow on the inside with an open top. It carries no load, so there is no load case."
SPHERE = "A PLA sphere with a 100mm diameter"
L_BRACKET_60 = (
    "A PLA L-bracket 60 mm wide, made of 2 mm thick plate. The base leg is 50 mm long and lies flat; the upright "
    "leg stands on the back end of the base and is 40 mm tall overall. Two 10 mm holes pass through the base, "
    "20 mm apart across its width, centred 25 mm from the front end. Two 5 mm holes pass through the upright, "
    "20 mm apart across its width, centred 25 mm above the bottom. It carries no load, so there is no load case."
)
DOME_70 = (
    "A PLA dome: exactly half of a 70 mm sphere, sitting flat side to the right side, hollow on the inside. It "
    "carries no load, so there is no load case."
)
#: The dome as V2 makes it, flat side down: what the judge of DOME_70's right part is drawn from.
DOME_70_DOWN = (
    "A PLA dome: exactly half of a 70 mm sphere, sitting flat side down, hollow on the inside. It carries no load, so "
    "there is no load case."
)
WRIST_STRIP = (
    "A flat PLA strip 110 mm long, 16 mm wide and 2 mm thick with both ends fully rounded. Two 4.3 mm holes go "
    "through it on its centreline, 8 mm and 28 mm from one end. A slot 4.4 mm wide and 24 mm long overall goes "
    "through it on the centreline, running along the strip, centred 90 mm from that same end. Its strength is "
    "checked outside Forge, so there is no load case."
)
POEM = "Write me a poem about bridges."
WASHER = "Make a washer."
#: The wall a hollow is given where the brief gives none: the spec writer assumes one, and the person sees it.
WALL = 2.0


def _hollow_cube(b: NumberedBrief) -> Draft:
    side = mm(b, 30, "30 mm cube")
    return draft("hollow cube", [
        item("cube", "block", cite(b, "30 mm cube"), length=side, width=side, height=side),
        item("hollow", "shell", cite(b, "hollow on the inside"), of="cube",
             thickness=assumed("the brief gives no wall: 2 mm, a printed wall", WALL),
             open={"faces": ["+z"], "from": said(b, "with an open top")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


def _sphere(b: NumberedBrief) -> Draft:
    return draft("sphere", [
        item("sphere", "sphere", cite(b, "sphere"), diameter=mm(b, 100, "100mm diameter"),
             portion=choose("whole", said(b, "sphere"))),
    ], material=made_of(b, "PLA"))  # fmt: skip


def _l_bracket_60(b: NumberedBrief) -> Draft:
    def holes(
        id_: str,
        host: str,
        face: str,
        nth: int,
        size: str,
        depth: str,
        along: dict[str, Any],
    ) -> dict[str, Any]:
        n = float(size.split()[0])
        return item(id_, "hole", cite(b, "holes", nth), on=on(host, face), diameter=mm(b, n, size),
                    depth=through(b, depth), count=count(b, 2, "Two", nth),
                    place={"y": middle("the pair is centred across the width"), **along,
                           "pattern": {"row": {"axis": choose("y", said(b, "across its width", nth)),
                                               "pitch": mm(b, 20, "20 mm apart", nth),
                                               "count": count(b, 2, "Two", nth)}}})  # fmt: skip

    return draft("L-bracket", [
        item("base", "block", cite(b, "base leg"), length=mm(b, 50, "50 mm long"), width=mm(b, 60, "60 mm wide"),
             height=mm(b, 2, "2 mm thick")),
        item("upright", "block", cite(b, "upright leg"), on=on("base", "+z"), length=mm(b, 2, "2 mm thick"),
             width=mm(b, 60, "60 mm wide"),
             height=formula(38, "40 mm - 2 mm", cite(b, "40 mm tall") + cite(b, "2 mm thick")),
             place={"x": {"side": "+x", "distance": assumed("it stands on the back end, flush with it", 0),
                          "to": "edge"},
                    "y": middle("it spans the base's width")}),
        holes("base_holes", "base", "+z", 1, "10 mm holes", "pass through the base",
              {"x": {"side": "-x", "distance": mm(b, 25, "centred 25 mm from the front end"), "to": "centre"}}),
        holes("upright_holes", "upright", "-x", 2, "5 mm holes", "pass through the upright",
              {"z": {"side": "-z", "to": "centre",
                     "distance": formula(23, "25 mm - 2 mm",
                                         cite(b, "centred 25 mm above the bottom") + cite(b, "2 mm thick"))}}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


def _dome_70(b: NumberedBrief) -> Draft:
    """DOME_70_DOWN's right part (DOME_70's, on its side, V2 can't make yet: :attr:`FalsePass.judged_on`)."""
    return draft("hollow dome", [
        item("dome", "sphere", cite(b, "dome") + cite(b, "sitting flat side down"), diameter=mm(b, 70, "70 mm sphere"),
             portion=choose("upper_half", said(b, "exactly half of a"))),
        item("hollow", "shell", cite(b, "hollow on the inside"), of="dome",
             thickness=assumed("the brief gives no wall: 2 mm, a printed wall", WALL),
             open={"faces": ["-end"], "from": {"assumed": "a dome hollow on the inside is open on its flat side"}}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


def _wrist_strip(b: NumberedBrief) -> Draft:
    from_end = {"side": "-x", "to": "centre"}
    return draft("wrist strip", [
        item("strip", "block", cite(b, "strip"), length=mm(b, 110, "110 mm long"), width=mm(b, 16, "16 mm wide"),
             height=mm(b, 2, "2 mm thick")),
        item("ends", "fillet", cite(b, "both ends fully rounded"),
             radius=formula(8, "16 mm / 2", cite(b, "16 mm wide") + cite(b, "fully rounded")),
             edges={"of": "strip", "which": "vertical", "words": cite(b, "both ends fully rounded")}),
        item("holes", "hole", cite(b, "holes"), on=on("strip", "+z"), diameter=mm(b, 4.3, "4.3 mm holes"),
             depth=through(b, "go through it"), count=count(b, 2, "Two"),
             place={"x": {**from_end, "distance": mm(b, 8, "8 mm")}, "y": at_centreline(b),
                    "pattern": {"row": {"axis": choose("x", said(b, "on its centreline")),
                                        "pitch": formula(20, "28 mm - 8 mm", cite(b, "8 mm and 28 mm")),
                                        "count": count(b, 2, "Two")}}}),
        item("slot", "slot", cite(b, "slot"), on=on("strip", "+z"), width=mm(b, 4.4, "4.4 mm wide"),
             length=mm(b, 24, "24 mm long overall"), along=choose("x", said(b, "running along the strip")),
             ends=choose("round", assumed("a slot's ends are round unless said")),
             depth=through(b, "goes through it"),
             place={"x": {**from_end, "distance": mm(b, 90, "centred 90 mm from that same end")},
                    "y": at_centreline(b, 2)}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "both ends", "how many ends are rounded: both, as the vertical edges' rounding makes "
                                             "them"),
                     left_out(b, "one end", "which end: either; the spec measures from the -x end")],
       silent=[{"sentence": b.word(cite(b, "strength")[0]).sentence,
                "reason": "it says its strength is checked outside Forge: no load case"}])  # fmt: skip


def at_centreline(b: NumberedBrief, nth: int = 1) -> dict[str, Any]:
    return {
        "centred": said(b, "on its centreline" if nth == 1 else "on the centreline")
    }


def _poem(b: NumberedBrief) -> Draft:
    """V1's placeholder for a brief that is no part: a cube a millimetre across, every size assumed."""
    side = assumed("nothing is sized: a placeholder", 1.0)
    return draft(
        "placeholder",
        [item("cube", "block", cite(b, "poem"), length=side, width=side, height=side)],
    )


def _washer(b: NumberedBrief) -> Draft:
    """V1's washer for a brief that sizes nothing: an M10 washer's sizes (ISO 7089), each assumed."""
    return draft("washer", [
        item("washer", "tube", cite(b, "washer"), outer_diameter=assumed("an M10 washer is 20 mm across", 20.0),
             inner_diameter=assumed("an M10 washer's hole is 10.5 mm", 10.5),
             length=assumed("an M10 washer is 2 mm thick", 2.0), axis=choose("z", assumed("a washer lies flat"))),
    ])  # fmt: skip


UPPER_RAIL = (
    "A PLA upper-arm rail for an elbow brace: a flat bar 36 mm wide and 20 mm thick. One end of the bar is a round "
    "end 48 mm in diameter centred on the pivot point. The bar runs along its centreline from the pivot point to a "
    "fully rounded far end whose centre is 245 mm from the pivot point. At the pivot point, cut a round pocket "
    "22.1 mm in diameter and 7 mm deep into the top face and an identical pocket 7 mm deep into the bottom face, "
    "and cut a 17 mm hole through the 6 mm of material left between the two pockets. Add four 8.2 mm through holes "
    "on the bar's centreline at 85, 115, 225 and 245 mm from the pivot point. Give only the two holes at 225 and "
    "245 mm a 15 mm counterbore 5 mm deep from the bottom face. Its strength is checked outside Forge, so there is "
    "no load case."
)
FOREARM_RAIL = (
    "A PLA forearm rail for an elbow brace: a flat bar 36 mm wide and 16 mm thick, lying flat. One end is a round "
    "end 48 mm in diameter centred on the pivot point, with an 8.2 mm hole straight through at the pivot. The bar "
    "runs along its centreline from the pivot point to a fully rounded far end whose centre is 175 mm from the "
    "pivot point. Two more 8.2 mm through holes sit on the centreline at 125 mm and 155 mm from the pivot point. "
    "Seen from above, with the pivot end on the left and the far end on the right, a lug the full 16 mm thick "
    "sticks out from the upper long edge: it is 24 mm wide, centred 46 mm from the pivot point along the bar, and "
    "ends in a semicircle of radius 12 mm whose centre is 28 mm from the bar's centreline. A 6.4 mm hole goes "
    "straight through the lug at that centre. On the top face, a round boss 20 mm in diameter and 6 mm tall stands "
    "centred on that hole, and the hole runs through the boss too. On the bottom face, that 6.4 mm hole has an "
    "11.5 mm counterbore 4 mm deep. Its strength is checked outside Forge, so there is no load case."
)


def _strength(b: NumberedBrief) -> dict[str, Any]:
    return {"sentence": b.word(cite(b, "strength")[0]).sentence,
            "reason": "it says its strength is checked outside Forge: no load case"}  # fmt: skip


#: Where a rail's straight sides meet its round end (48 mm across) on the pivot: the bar is 36 mm wide.
_FOOT = math.sqrt(24.0**2 - 18.0**2)


def _rail(
    b: NumberedBrief, thick: str, far: str, far_value: float, words: list[int]
) -> dict[str, Any]:
    """An elbow brace's rail as one outline pushed its thickness: the round end on the pivot point (the outline's origin), the bar running from it along +x to its fully rounded far end, that end's centre ``far`` from the pivot."""
    segments = [{"line_to": [far_value, -18.0]}, {"arc_to": [far_value, 18.0], "centre": [far_value, 0.0]},
                {"line_to": [_FOOT, 18.0]}, {"arc_to": [_FOOT, -18.0], "centre": [0.0, 0.0]}]  # fmt: skip
    return item("rail", "extrusion", cite(b, "flat bar"), length=mm(b, float(thick.split()[0]), thick),
                axis=choose("z", assumed("the bar lies flat")),
                profile={"start": [_FOOT, -18.0], "segments": segments, "from": {"words": words}})  # fmt: skip


def from_pivot(
    b: NumberedBrief, words: str, value: float, nth: int = 1
) -> dict[str, Any]:
    """Along the rail from the pivot point: from the outline's -x edge, the round end's radius behind it."""
    text = f"{words.split()[0]} mm + 48 mm / 2"
    return {"side": "-x", "to": "centre",
            "distance": formula(value + 24, text, cite(b, words, nth) + cite(b, "48 mm in diameter"))}  # fmt: skip


def _pivot(b: NumberedBrief) -> dict[str, Any]:
    """At the pivot point: 24 mm in from the outline's -x edge, and from its -y edge (the round end's)."""
    return {"x": {"side": "-x", "to": "centre",
                  "distance": formula(24, "48 mm / 2", cite(b, "48 mm in diameter"))},
            "y": _centreline(b, "pivot point")}  # fmt: skip


def _centreline(b: NumberedBrief, words: str) -> dict[str, Any]:
    """On the bar's centre line: the round end's radius in from the outline's -y edge (a lug makes the outline's middle another line)."""
    return {"side": "-y", "to": "centre",
            "distance": formula(24, "48 mm / 2", cite(b, "48 mm in diameter") + cite(b, words))}  # fmt: skip


def _upper_rail(b: NumberedBrief) -> Draft:
    hole = {
        "diameter": mm(b, 8.2, "8.2 mm through holes"),
        "depth": through(b, "through holes"),
    }
    centreline = _centreline(b, "on the bar's centreline")
    counterbore = {
        "diameter": mm(b, 15, "15 mm counterbore"),
        "depth": mm(b, 5, "5 mm deep from the bottom face"),
    }
    outline = (span(b, "36 mm wide") + span(b, "round end 48 mm in diameter centred on the pivot point")
               + span(b, "fully rounded far end whose centre is 245 mm from the pivot point"))  # fmt: skip
    return draft("upper-arm rail", [
        _rail(b, "20 mm thick", "245 mm from the pivot point", 245.0, outline),
        item("top_pocket", "pocket", cite(b, "round pocket"), on=on("rail", "+end"),
             shape=choose("circle", said(b, "round pocket")), diameter=mm(b, 22.1, "22.1 mm in diameter"),
             depth=mm(b, 7, "7 mm deep into the top face"), place=_pivot(b)),
        item("bottom_pocket", "pocket", cite(b, "identical pocket"), on=on("rail", "-end"),
             shape=choose("circle", said(b, "round pocket")), diameter=mm(b, 22.1, "22.1 mm in diameter"),
             depth=mm(b, 7, "7 mm deep into the bottom face"), place=_pivot(b)),
        item("pivot", "hole", cite(b, "17 mm hole"), on=on("top_pocket", "bottom"), diameter=mm(b, 17, "17 mm hole"),
             depth=through(b, "through the 6 mm of material left between the two pockets"),
             place={"concentric": {"item": "top_pocket", "from": said(b, "between the two pockets")}}),
        item("hole_85", "hole", cite(b, "8.2 mm through holes"), on=on("rail", "+end"), **hole,
             place={"x": from_pivot(b, "85", 85), "y": centreline}),
        item("hole_115", "hole", cite(b, "8.2 mm through holes"), on=on("rail", "+end"), **hole,
             place={"x": from_pivot(b, "115", 115), "y": centreline}),
        item("hole_225", "hole", cite(b, "8.2 mm through holes"), on=on("rail", "-end"), **hole,
             counterbore=counterbore, place={"x": from_pivot(b, "225", 225), "y": centreline}),
        item("hole_245", "hole", cite(b, "8.2 mm through holes"), on=on("rail", "-end"), **hole,
             counterbore=counterbore, place={"x": from_pivot(b, "245 mm", 245, 2), "y": centreline}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "for an elbow brace", "what it is for"),
                     left_out(b, "One end", "which end: the pivot's, the round end"),
                     left_out(b, "the 6 mm of material left", "what is left between the pockets: the bar's 20 mm "
                                                             "less their two 7 mm"),
                     left_out(b, "the two pockets", "how many pockets: one item each"),
                     left_out(b, "four", "how many holes: one item each"),
                     left_out(b, "only the two holes at 225 and 245 mm", "which are counterbored: the two at "
                                                                            "225 and 245 mm, each its own item")],
       silent=[_strength(b)])  # fmt: skip


def _forearm_rail(b: NumberedBrief) -> Draft:
    """The forearm rail: the rail's outline with its lug (24 mm wide, centred 46 mm along, its semicircle's centre 28 mm across) in it."""
    segments = [{"line_to": [175.0, -18.0]}, {"arc_to": [175.0, 18.0], "centre": [175.0, 0.0]},
                {"line_to": [58.0, 18.0]}, {"line_to": [58.0, 28.0]},
                {"arc_to": [34.0, 28.0], "centre": [46.0, 28.0]}, {"line_to": [34.0, 18.0]},
                {"line_to": [_FOOT, 18.0]}, {"arc_to": [_FOOT, -18.0], "centre": [0.0, 0.0]}]  # fmt: skip
    outline = (span(b, "36 mm wide") + span(b, "round end 48 mm in diameter centred on the pivot point")
               + span(b, "fully rounded far end whose centre is 175 mm from the pivot point")
               + span(b, "it is 24 mm wide, centred 46 mm from the pivot point along the bar, and ends in a "
                         "semicircle of radius 12 mm whose centre is 28 mm from the bar's centreline"))  # fmt: skip
    lug_centre = {
        "x": {
            "side": "-x",
            "to": "centre",
            "distance": formula(
                70, "46 mm + 48 mm / 2", cite(b, "46 mm") + cite(b, "48 mm in diameter")
            ),
        },
        "y": {
            "side": "-y",
            "to": "centre",
            "distance": formula(
                52, "28 mm + 48 mm / 2", cite(b, "28 mm") + cite(b, "48 mm in diameter")
            ),
        },
    }
    hole = {
        "diameter": mm(b, 8.2, "8.2 mm through holes"),
        "depth": through(b, "through holes"),
    }
    centreline = _centreline(b, "on the centreline")
    return draft("forearm rail", [
        item("rail", "extrusion", cite(b, "flat bar"), length=mm(b, 16, "16 mm thick"),
             axis=choose("z", said(b, "lying flat")),
             profile={"start": [_FOOT, -18.0], "segments": segments, "from": {"words": outline}}),
        item("pivot", "hole", cite(b, "8.2 mm hole"), on=on("rail", "+end"), diameter=mm(b, 8.2, "8.2 mm hole"),
             depth=through(b, "straight through at the pivot"), place=_pivot(b)),
        item("holes", "hole", cite(b, "8.2 mm through holes"), on=on("rail", "+end"), **hole, count=count(b, 2, "Two"),
             place={"x": from_pivot(b, "125 mm", 125), "y": centreline,
                    "pattern": {"row": {"axis": choose("x", said(b, "on the centreline")),
                                        "pitch": formula(30, "155 mm - 125 mm", cite(b, "125 mm and 155 mm")),
                                        "count": count(b, 2, "Two")}}}),
        item("boss", "boss", cite(b, "round boss"), on=on("rail", "+end"), diameter=mm(b, 20, "20 mm in diameter"),
             height=mm(b, 6, "6 mm tall"), place=lug_centre),
        item("lug_hole", "hole", cite(b, "6.4 mm hole"), on=on("boss", "+end"), diameter=mm(b, 6.4, "6.4 mm hole"),
             depth=through(b, "the hole runs through the boss too"),
             place={"concentric": {"item": "boss", "from": said(b, "centred on that hole")}}),
        # Its counterbore on the bottom face: a round recess there, on the hole's axis.
        item("counterbore", "pocket", cite(b, "11.5 mm counterbore"), on=on("rail", "-end"),
             shape=choose("circle", said(b, "11.5 mm counterbore")), diameter=mm(b, 11.5, "11.5 mm counterbore"),
             depth=mm(b, 4, "4 mm deep"),
             place={"concentric": {"item": "boss", "from": said(b, "that 6.4 mm hole")}}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "for an elbow brace", "what it is for"),
                     left_out(b, "One end", "which end: the pivot's, the round end"),
                     left_out(b, "Two more", "how many more: the two the row places"),
                     left_out(b, "the full 16 mm thick", "the lug's thickness: the rail's, the lug in its outline"),
                     left_out(b, "that 6.4 mm hole", "the same hole: drilled through the boss and the lug, its "
                                                    "counterbore a round recess in the bottom face")],
       silent=[_strength(b)])  # fmt: skip


# ----------------------------------------------------------------------
# The wrong parts, as V1's documents drew them, in V2's frame
# ----------------------------------------------------------------------
def _spacer_standing_on_its_edge() -> Any:
    # base [30, 4, 30] centred, standing: up 15; the post from 2 above the plate's middle; the 5 mm hole along x at
    # 5 above it, the 3 mm ones on its line, inside it. V1's 2 mm blend where the post crosses the plate left out.
    plate = box((-15, -2, 0), (15, 2, 30))
    return minus(
        plus(plate, rod((0, 0, 17), (0, 0, 1), 12, 10)),
        through_rod((0, 0, 20), (1, 0, 0), 5),
    )


def _spacer_in_the_wrong_plane() -> Any:
    # Only its envelope (38 x 20 x 38), its holes (none) and its mass are recorded: a plate 38 mm square and 4 mm
    # thick standing on its edge, the post through it along y, as those figures say.
    plate = box((-19, -2, 0), (19, 2, 38))
    return plus(plate, rod((0, -10, 19), (0, 1, 0), 12, 20))


def _spacer_holes_at_the_edges() -> Any:
    # base [30, 4, 30] standing; the post from its middle; the holes along z: 5 mm at the middle, 3 mm at x = 15 and
    # -15, half-moons out of the plate's ends. The blend left out.
    plate = box((-15, -2, 0), (15, 2, 30))
    part = plus(plate, rod((0, 0, 15), (0, 0, 1), 12, 10))
    holes = [
        through_rod((x, 0, 0), (0, 0, 1), d) for x, d in ((0, 5), (15, 3), (-15, 3))
    ]
    return minus(part, *holes)


def _spacer_as_a_bar() -> Any:
    # base [30, 4, 4]: a bar under the post, every hole along z through it. The blend (OpenCascade can't make it
    # where the post overhangs the bar) left out.
    part = plus(box((-15, -2, 0), (15, 2, 4)), rod((0, 0, 4), (0, 0, 1), 12, 10))
    holes = [
        through_rod((x, 0, 0), (0, 0, 1), d) for x, d in ((0, 5), (10, 3), (-10, 3))
    ]
    return minus(part, *holes)


def _spacer_base_a_fillet_thick() -> Any:
    # base [30, 4, 2] (its height the fillet's radius) centred: up 1; the post from 2 above its middle, floating a
    # millimetre over it; the holes along z through both.
    part = plus(box((-15, -2, 0), (15, 2, 2)), rod((0, 0, 3), (0, 0, 1), 12, 10))
    holes = [
        through_rod((x, 0, 0), (0, 0, 1), d) for x, d in ((0, 5), (10, 3), (-10, 3))
    ]
    return minus(part, *holes)


def _collar(bore: bool = True) -> Any:
    body = rod((0, 0, 0), (0, 0, 1), 25, 15)
    return minus(body, through_rod((0, 0, 7.5), (0, 0, 1), 12)) if bore else body


def _collar_screws_half_a_turn_apart() -> Any:
    # The set screws through the wall from the outside into the bore, at 0 and 180 degrees (+x and -x).
    return minus(
        _collar(),
        rod((5, 0, 7.5), (1, 0, 0), 4, 8.5),
        rod((-5, 0, 7.5), (-1, 0, 0), 4, 8.5),
    )


def _collar_screws_parallel() -> Any:
    # Both along y, through, at x = 7.5 and -7.5: two chords across the body.
    return minus(
        _collar(), *(through_rod((x, 0, 7.5), (0, 1, 0), 4) for x in (7.5, -7.5))
    )


def _collar_with_four_openings() -> Any:
    # Along x and along y through the axis: each screw through both walls.
    return minus(
        _collar(),
        through_rod((0, 0, 7.5), (1, 0, 0), 4),
        through_rod((0, 0, 7.5), (0, 1, 0), 4),
    )


def _collar_screws_at_the_bore_s_size() -> Any:
    # No bore; the two screws 12 mm across, along x and y through the axis.
    return minus(
        _collar(bore=False),
        through_rod((0, 0, 7.5), (1, 0, 0), 12),
        through_rod((0, 0, 7.5), (0, 1, 0), 12),
    )


def _l_bracket_upright_too_wide() -> Any:
    # V1 ran the base's 50 mm along y, the upright at its +y end, [50, 5, 40]: turned to run along x here, up 2.5.
    base = box((-25, -20, 0), (25, 20, 5))
    upright = box((20, -25, 0), (25, 25, 40))
    holes = [*(through_rod((0, y, 0), (0, 0, 1), 5) for y in (10, -10)),
             *(through_rod((0, y, 25), (1, 0, 0), 5) for y in (10, -10))]  # fmt: skip
    return minus(plus(base, upright), *holes)


def _box_cut_through_the_middle() -> Any:
    # The box 60 x 40 x 30 less a floor box 60 x 40 x 2 through its middle: two slabs. Up 15; the cut's 2 mm blend
    # left out.
    return plus(box((-30, -20, 0), (30, 20, 14)), box((-30, -20, 16), (30, 20, 30)))


def _hollow_cube_solid() -> Any:
    return box((-15, -15, 0), (15, 15, 30))


def _dome_a_ball_and_a_box() -> Any:
    # A 50 mm ball round the origin and a box 50 x 50 x 25 centred on it, joined: what should have been their common
    # part, the dome on z = 0.
    return plus(ball((0, 0, 0), 50), box((-25, -25, -12.5), (25, 25, 12.5)))


def _sphere_a_drum() -> Any:
    return rod((0, 0, 0), (0, 0, 1), 100, 100)


def _l_bracket_turned() -> Any:
    # The right bracket turned a quarter: the upright on the base's long side, the holes measured along its width.
    base = box((-30, -25, 0), (30, 25, 2))
    upright = box((-30, 23, 0), (30, 25, 40))
    holes = [*(through_rod((x, 0, 0), (0, 0, 1), 10) for x in (10, -10)),
             *(through_rod((x, 24, 25), (0, 1, 0), 5) for x in (10, -10))]  # fmt: skip
    return minus(plus(base, upright), *holes)


def _dome_sealed() -> Any:
    # The half ball shelled 2 mm with every face kept: a skin sealed all round, its flat side shut.
    outer = common(ball((0, 0, 0), 70), box((-40, -40, 0), (40, 40, 40)))
    inner = common(ball((0, 0, 0), 66), box((-40, -40, 2), (40, 40, 40)))
    return minus(outer, inner)


def _ring_on_its_outside() -> Any:
    # The 8 mm section on a 32 mm middle: 40 mm across its outside, not its centre line.
    return ring((0, 0, 4), 32, 8)


def _one_counterbore_of_two() -> Any:
    plate = box((-30, -20, 0), (30, 20, 10))
    holes = [through_rod((x, 0, 0), (0, 0, 1), 5.5) for x in (20, -20)]
    return minus(plate, *holes, rod((20, 0, 5), (0, 0, 1), 10, 6))


def _steel_cube_shelled() -> Any:
    return minus(box((-10, -10, 0), (10, 10, 20)), box((-7, -7, 3), (7, 7, 17)))


def _bolt_head_84_across() -> Any:
    # head_diameter = 13 / cos(30): 30 radians, so 84.3 mm across the corners; the head 5.5 high, the shank 8 x 40.
    r = 13 / math.cos(30) / 2
    corners = [
        [r * math.cos(math.pi / 3 * k), r * math.sin(math.pi / 3 * k)] for k in range(7)
    ]
    return plus(pushed(corners, 0, 5.5), rod((0, 0, 5.5), (0, 0, 1), 8, 40))


def _rail_outline(far: float) -> list[list[float]]:
    return [
        [_FOOT, -18.0],
        [far, -18.0],
        [far, 18.0, far + 18.0, 0.0],
        [_FOOT, 18.0],
        [_FOOT, -18.0, -24.0, 0.0],
    ]


def upper_rail(blend: float = 0.0) -> Any:
    """The upper-arm rail as its brief draws it; with ``blend``, where its round end meets the bar rounded so."""
    rail = pushed(_rail_outline(245.0), 0, 20)
    if blend:
        rail = rounded(
            rail, blend, lambda p: near(p[0], _FOOT) and near(abs(p[1]), 18.0)
        )
    cuts = [rod((0, 0, 13), (0, 0, 1), 22.1, 8), rod((0, 0, -1), (0, 0, 1), 22.1, 8), through_rod((0, 0, 10), (0, 0, 1), 17),
            *(through_rod((x, 0, 10), (0, 0, 1), 8.2) for x in (85, 115, 225, 245)),
            *(rod((x, 0, -1), (0, 0, 1), 15, 6) for x in (225, 245))]  # fmt: skip
    return minus(rail, *cuts)


def _upper_rail_blended() -> Any:
    # V1 kept an 8 mm blend where the 48 mm round end meets the bar, nobody having asked for it.
    return upper_rail(8.0)


def _forearm_rail_lug_square() -> Any:
    # The lug drawn as a box 24 x 22 x 16, its two top edges along y rounded (12 mm asked, clamped to 8): square in
    # plan, where the brief ends it in a semicircle; the boss over the rounding.
    rail = pushed(_rail_outline(175.0), 0, 16)
    lug = rounded(
        box((34, 18, 0), (58, 40, 16)),
        8.0,
        lambda p: near(p[2], 16.0) and (near(p[0], 34.0) or near(p[0], 58.0)),
    )
    part = plus(rail, lug, rod((46, 28, 16), (0, 0, 1), 20, 6))
    cuts = [through_rod((0, 0, 8), (0, 0, 1), 8.2), *(through_rod((x, 0, 8), (0, 0, 1), 8.2) for x in (125, 155)),
            through_rod((46, 28, 8), (0, 0, 1), 6.4), rod((46, 28, -1), (0, 0, 1), 11.5, 5)]  # fmt: skip
    return minus(part, *cuts)


def wrist_strip(round_ends: bool = True) -> Any:
    strip = box((-55, -8, 0), (55, 8, 2))
    if round_ends:
        strip = rounded(
            strip, 8.0, lambda p: near(abs(p[0]), 55.0) and near(abs(p[1]), 8.0)
        )
    # The slot 24 mm long overall, its round ends' centres 9.8 mm either side of 35.
    slot = plus(
        box((25.2, -2.2, -1), (44.8, 2.2, 3)),
        rod((25.2, 0, -1), (0, 0, 1), 4.4, 4),
        rod((44.8, 0, -1), (0, 0, 1), 4.4, 4),
    )
    return minus(
        strip, *(through_rod((x, 0, 1), (0, 0, 1), 4.3) for x in (-47, -27)), slot
    )


def _wrist_strip_square_ended() -> Any:
    # The strip as designed, with its ends' rounding taken off as a fillet nobody asked for.
    return wrist_strip(round_ends=False)


def _post_on_a_riser() -> Any:
    # A 5 mm riser nobody asked for under the post, to make "no taller than 50 mm" exactly 50.
    return plus(box((-20, -20, 0), (20, 20, 5)), rod((0, 0, 5), (0, 0, 1), 15, 45))


# ----------------------------------------------------------------------
# The 27, and two weaker candidates
# ----------------------------------------------------------------------
def _suite(id_: str) -> str:
    """A validation suite brief's text (validation/SUITE.md)."""
    return suite()[id_].brief


R11, R12 = _suite("R11"), _suite("R12")
SPACER = "fairly sure: the geometry is the model's stored answer; whether the run's settle step changed it is not recorded"

FALSE_PASSES: tuple[FalsePass, ...] = (
    FalsePass(1, "R11 spacer, base on its edge", R11,
              "the base plate 30 x 4 x 30 standing on its edge, the post 12 x 10 crossing it, the 5 mm hole and both "
              "3 mm holes drilled along x on one line through it",
              "its record was seven parameter claims and the mass, all true of a standing plate; nothing claimed the "
              "envelope, the height or a hole's direction (fixed by REQ_STACKED_HEIGHT, bounding_box_z = 14)",
              ("tests/fixtures/real_runs/spacer_base_standing_on_its_edge.json (its note: run 20260915T212005)",
               "tests/test_real_answers.py:3459-3468, 3493-3496, 3507-3513", "docs/V2-plan.md:136"),
              "sure (" + SPACER + ")", "spacer_base_standing_on_its_edge", "R11", _spacer_standing_on_its_edge, by=("base/width/0",)),
    FalsePass(2, "R11 spacer, wrong plane", R11,
              "a spacer whose plate was built in the wrong plane and whose holes a boolean filled back in: envelope "
              "38 x 20 x 38 for 30 x 30 x 14, 0 open holes of 3, 6,518 mm3 (8.08 g against 8)",
              "seven parameter claims, all true of the document, and the brief's mass limit dropped by the model; "
              "nothing measured the solid",
              ("tests/test_spec.py:2484-2541", "packages/forge_roles/library.py:14233-14284",
               "packages/forge_pipeline/verify.py:146-151"),
              "fairly sure that it happened and was reported PASS; its brief is inferred (the 30 x 30 x 14 and the "
              "8 g are R11's) and its shape is known only as its envelope, holes and volume: made here as those say",
              None, "R11", _spacer_in_the_wrong_plane, by=("base/height/0",)),
    FalsePass(3, "R11 spacer, mounting holes at the edges", R11,
              "the base standing on its edge, the 3 mm holes drawn 30 mm apart at the plate's ends, half-moons cut "
              "from them, the 20 mm spacing declared and read by nothing",
              "its note says the run failed; what V1 accepted was the spacing read back from the parameter table",
              ("tests/fixtures/real_runs/spacer_holes_at_the_plate_edges.json (its note: run 20260915T172355)",
               "tests/test_real_answers.py:3613-3633", "docs/V2-plan.md:136"),
              "least sure: the run failed rather than passed; kept as the near miss it may have been",
              "spacer_holes_at_the_plate_edges", "R11", _spacer_holes_at_the_edges, by=("base/width/0",)),
    FalsePass(4, "R11 spacer as a bar", R11,
              "the base 30 x 4 x 4, a bar under the post, its holes inside the 4 mm",
              "two names for the 4 mm thickness: the record measured one and the features read the other; nothing "
              "measured the base's width",
              ("tests/fixtures/real_runs/spacer_released_as_a_bar.json (run 20260920T123327, released)",
               "tests/test_real_answers.py:215-231"),
              "sure", "spacer_released_as_a_bar", "R11", _spacer_as_a_bar, by=("base/width/0",)),
    FalsePass(5, "R11 spacer, base a fillet thick", R11,
              "the base 30 x 4 x 2 (the fillet's radius for its thickness), the post floating a millimetre above it",
              "eight parameter claims, the count of two mounting holes and the mass were all true; nothing measured "
              "the base's thickness or the stack's height",
              ("tests/fixtures/real_runs/spacer_base_a_fillet_thick.json (its note: run 20260922T104042)",
               "tests/test_real_answers.py:3459-3468, 3498-3513"),
              "sure", "spacer_base_a_fillet_thick", "R11", _spacer_base_a_fillet_thick, by=("base/height/0", "post/on")),
    FalsePass(6, "R12 collar, “90 degrees” unread", R12,
              "its two set screws 180 degrees apart",
              "“degrees” never matched the unit pattern, so the angle never entered the contract and no "
              "check could miss it",
              ("packages/forge_roles/library.py:259-268, 835-846", "tests/test_spec.py:2799-2810"),
              "fairly sure of the event, least of its run: possibly case 7's run described again; made here as the "
              "sources say, the collar right but for its screws' angle",
              None, "R12", _collar_screws_half_a_turn_apart, by=("set_screws/place.pattern.arc.step/0",)),
    FalsePass(7, "R12 collar, parallel screws", R12,
              "both 4 mm screws along y through the body at x = 7.5 and -7.5: parallel chords, four openings",
              "no claim of the angle, the direction or the count; angle_between didn't exist yet",
              ("tests/fixtures/real_runs/collar_parallel_screws_across_the_body.json (run 20260920T115626, released)",
               "tests/test_real_answers.py:94-96"),
              "sure", "collar_parallel_screws_across_the_body", "R12", _collar_screws_parallel, by=("set_screws/place.pattern.arc.step/0",)),
    FalsePass(8, "R12 collar, four openings", R12,
              "4 mm holes along x and along y through the axis, each through both walls: four openings for two",
              "every gate asked a true question (open, 4 mm, 90 degrees apart, halfway along, round); none counted "
              "openings, and Forge's guide taught set screws as centre-line holes",
              ("tests/fixtures/real_runs/collar_with_four_openings.json (run 20260923T104643, released)",
               "packages/forge_roles/library.py:4405-4418", "tests/test_real_answers.py:572-589"),
              "sure", "collar_with_four_openings", "R12", _collar_with_four_openings, by=("face accounting",)),
    FalsePass(9, "R12 collar, screws at the bore's size", R12,
              "both screws 12 mm across, along x and y through the axis, and no bore",
              "the bore's diameter passed because a hole read it, the angle passed, the 4 mm was not checked, and "
              "nothing counted holes",
              ("tests/fixtures/real_runs/collar_with_its_screws_at_the_bores_size.json (run 20260923T114935, "
               "released)", "packages/forge_roles/library.py:13155-13170", "tests/test_real_answers.py:614-644"),
              "sure", "collar_with_its_screws_at_the_bores_size", "R12", _collar_screws_at_the_bore_s_size, by=("collar/inner_diameter/0", "set_screws/diameter/0")),
    FalsePass(10, "R09 L-bracket, upright too wide", _suite("R09"),
              "the upright 50 mm wide on a 40 mm base, its holes where they belong",
              "every parameter claim was true, and the length claim met because the upright read the length; "
              "nothing claimed the extent across",
              ("tests/fixtures/real_runs/l_bracket_upright_as_long_as_the_base.json (its note: run "
               "20261002T205824, released)", "tests/test_real_answers.py:3459-3491"),
              "sure", "l_bracket_upright_as_long_as_the_base", "R09", _l_bracket_upright_too_wide, by=("upright/width/0",)),
    FalsePass(11, "R08 open-top box", _suite("R08"),
              "the box 60 x 40 x 30 less a floor box 60 x 40 x 2 through its middle: two slabs 14 mm thick",
              "not found in the sources: its record claimed the walls, the floor and the opening's depth",
              ("tests/fixtures/real_runs/open_top_box_cut_through_the_middle.json (run 20260929T101739, released)",
               "tests/test_real_answers.py:2211-2228"),
              "sure that it was released; why it passed is not recorded",
              "open_top_box_cut_through_the_middle", "R08", _box_cut_through_the_middle, by=("hollow/open", "topology")),
    FalsePass(12, "hollow cube", HOLLOW_CUBE,
              "a solid 30 mm cube",
              "no wall was stated, so the record held only the side, which a solid cube has too",
              ("tests/fixtures/real_runs/cube_hollow_open_top_released_solid.json (its note: run 20261003T112602)",
               "tests/test_real_answers.py:3880-3905"),
              "sure", "cube_hollow_open_top_released_solid", _hollow_cube, _hollow_cube_solid, by=("hollow/open",)),
    FalsePass(13, "dome", _suite("P07"),
              "a whole 50 mm ball welded to a box 50 x 50 x 25 round it",
              "both failing extent claims were excused as not applicable, the declared height having “already "
              "checked” the figure",
              ("tests/fixtures/real_runs/dome_released_as_sphere_and_box.json (its note: run 20261003T203015)",
               "tests/test_real_answers.py:4060-4096"),
              "sure", "dome_released_as_sphere_and_box", "P07", _dome_a_ball_and_a_box, by=("dome/diameter/0",)),
    FalsePass(14, "sphere", SPHERE,
              "a drum: a cylinder 100 across and 100 long",
              "100 mm all three ways, the diameter and roundness were all true of a drum, and the roundness claim "
              "told the designer to use one cylinder",
              ("tests/fixtures/real_runs/sphere_drawn_as_a_drum.json (run 20261005T151727)",
               "tests/test_real_answers.py:4810-4846"),
              "sure", "sphere_drawn_as_a_drum", _sphere, _sphere_a_drum, by=("sphere/portion",)),
    FalsePass(15, "L-bracket turned", L_BRACKET_60,
              "the right bracket rebuilt by Forge's layout repair turned a quarter: the upright on the base's side, "
              "the holes 25 mm from the front measured along the width",
              "the envelope is the same either way, the counts and parameters true, and the analyst made the rest "
              "agree",
              ("tests/fixtures/real_runs/bracket_leg_turned_on_its_long_side_claude.json",
               "packages/forge_roles/library.py:6065-6076", "tests/test_the_six_runs.py:7-9",
               "docs/fixlist_v6.txt:25-26"),
              "fairly sure: it was released as PASS, but the rebuilt part isn't stored: made here as the sources say",
              "bracket_leg_turned_on_its_long_side_claude", _l_bracket_60, _l_bracket_turned, by=("base/length/0",)),
    FalsePass(16, "hollow dome, sealed", DOME_70,
              "the half ball shelled 2 mm with every face kept: a sealed skin, no opening",
              "the wall's 2 mm was only in a statement, so no wall or opening was claimed; only the box and the "
              "diameter were checked",
              ("tests/fixtures/real_runs/dome_shelled_after_its_cut_claude.json", "docs/fixlist_v6.txt:27-30",
               "tests/test_the_six_runs.py:1-13"),
              "sure", "dome_shelled_after_its_cut_claude", _dome_70, _dome_sealed, by=("hollow/open",),
              judged_on=DOME_70_DOWN),
    FalsePass(17, "P11 doughnut", _suite("P11"),
              "the 8 mm section on a 32 mm middle: 40 mm across its outside, for 40 across its centre line",
              "the 40 was read as the outside and claimed along x and y; the right 48 mm design failed those claims "
              "and the redesign passed them",
              ("tests/fixtures/real_runs/validation_p11_ring_given_at_its_centre_line.json (answer_redesigned)",
               "docs/fixlist_v8.txt:167-196"),
              "sure", "validation_p11_ring_given_at_its_centre_line", "P11", _ring_on_its_outside, by=("face accounting",)),
    FalsePass(18, "H03 counterbores", _suite("H03"),
              "one counterbore of two: only the hole at x = 20 counterbored",
              "“each a ... hole” was counted as one, so one counterbore was claimed; a repair took the "
              "second off, and the grader's 4% band let the missing 1.2% of volume through",
              ("tests/fixtures/real_runs/validation_h03_each_of_two_counterbored_holes.json (answer_released)",
               "docs/fixlist_v8.txt:198-221"),
              "sure", "validation_h03_each_of_two_counterbored_holes", "H03", _one_counterbore_of_two, by=("holes/counterbore.diameter/0",)),
    FalsePass(19, "L05 steel cube", _suite("L05"),
              "the 20 mm cube shelled 3 mm inward to a sealed skin, 41 g, to pass its 50 g limit",
              "a repair shelled it to meet the mass; every claim passed, and the last look saw only a cube's outside",
              ("tests/fixtures/real_runs/validation_l05_steel_cube_shelled_to_its_weight.json (shelled)",
               "docs/fixlist_v8.txt:381-399"),
              "sure", "validation_l05_steel_cube_shelled_to_its_weight", "L05", _steel_cube_shelled, by=("topology",)),
    FalsePass(20, "X03 bolt", _suite("X03"),
              "the head 84.3 mm across its corners (13 / cos 30, the 30 read as radians), 5.5 high, on an 8 x 40 shank",
              "no claim was about the head, and the last look let it through",
              ("tests/fixtures/real_runs/validation_x03_bolt_head_drawn_with_cos_30.json",
               "docs/fixlist_v8.txt:414-425"),
              "sure", "validation_x03_bolt_head_drawn_with_cos_30", "X03", _bolt_head_84_across, by=("head/length/0",)),
    FalsePass(21, "X09 “a poem about bridges”", POEM,
              "a 1 mm placeholder cube",
              "the interpreter said it was no part, but requirements were written anyway and every check passed the "
              "cube",
              ("docs/fixlist_v8.txt:426-431", "tests/test_the_validation_suite.py:853-886"),
              "fairly sure: one source, and the cube's details aren't recorded",
              None, _poem, None, "the accounting"),
    FalsePass(22, "X01 “make a washer”", WASHER,
              "an M10 washer (ISO 7089: 20 across, a 10.5 mm hole, 2 thick) from sizes nobody gave",
              "all four assumptions were moderate and reversible, so none held the release, and every claim passed "
              "against them",
              ("tests/fixtures/real_runs/validation_x01_washer_nobody_sized.json", "docs/fixlist_v8.txt:432-440",
               "tests/test_the_validation_suite.py:818-850"),
              "least sure: the shape is a real washer; a dishonest assumption, not a wrong part",
              "validation_x01_washer_nobody_sized", _washer, None, "the assumptions --auto stops at"),
    FalsePass(23, "hollow dome's STL", DOME_70,
              "the right document, its STL drawing a skin of no thickness across the opening twice: one piece of "
              "89,778 mm3 with a sealed void of 75,229, for the right 14,549",
              "samples on the cutting plane counted as material, no check read the mesh's pieces and voids, and the "
              "watertight check missed the doubled sheet",
              ("tests/fixtures/real_runs/validation_dome_open_side_drawn_shut.json (run 20261019T131440)",
               "docs/fixlist_v8.txt:561-595", "tests/test_the_validation_suite.py:978-1107"),
              "sure", "validation_dome_open_side_drawn_shut", _dome_70, None, "the judge of the file shipped", by=("topology",),
              judged_on=DOME_70_DOWN),
    FalsePass(24, "exo upper rail's STL", UPPER_RAIL,
              "the right design, its STL meshed in 3 mm cells: the holes 7.3 to 7.7 mm for 8.2, the counterbores "
              "13.5 for 15, the pockets 21.85 for 22.1",
              "all 32 claims were measured on the design, and the shipped file was never measured again",
              ("tests/fixtures/real_runs/exo_upper_rail_holes_meshed_undersize.json (run 20261019T153711)",
               "docs/fixlist_v8.txt:596-628", "tests/test_the_validation_suite.py:1110-1162"),
              "sure", "exo_upper_rail_holes_meshed_undersize", _upper_rail, None, "the judge of the file shipped", by=("face accounting",)),
    FalsePass(25, "exo upper rail, 8 mm blend", UPPER_RAIL,
              "an 8 mm blend where the 48 mm round end meets the bar, nobody having asked for it",
              "“round end” and “fully rounded far end” counted as words asking for rounding, so "
              "the blend was left on and nothing measured it",
              ("tests/fixtures/real_runs/exo_upper_rail_holes_meshed_undersize.json (its document)",
               "docs/fixlist_v8.txt:629-636", "tests/test_the_validation_suite.py:1204-1218"),
              "least sure: a blend V1 kept; the fix log doesn't call the release a false pass",
              "exo_upper_rail_holes_meshed_undersize", _upper_rail, _upper_rail_blended, by=("face accounting",)),
    FalsePass(26, "exo forearm lug", FOREARM_RAIL,
              "the lug a box 24 x 22 x 16, square-ended in plan, its top edges along y rounded 8 (12 asked, clamped); "
              "the boss over the rounding",
              "the semicircle's 12 mm radius was read from the parameter table; the clamp cut the figure short, and "
              "the last look's fix, written in words with no patch, was recorded as nothing to change",
              ("tests/fixtures/real_runs/exo_forearm_rail_lug_clamped.json (run 20261019T190405)",
               "docs/fixlist_v8.txt:677-717", "tests/test_the_validation_suite.py:1526-1711"),
              "sure", "exo_forearm_rail_lug_clamped", _forearm_rail, _forearm_rail_lug_square, by=("face accounting",)),
    FalsePass(27, "exo wrist strip", WRIST_STRIP,
              "the strip as designed with its ends' rounding taken off: square ends for fully rounded ones",
              "Forge took the rounding off as a fillet nobody asked for; nothing measured the ends, and the last look "
              "called them round",
              ("tests/fixtures/real_runs/exo_wrist_strip_ends_taken_off.json (run 20261019T220816)",
               "docs/fixlist_v8.txt:719-752", "tests/test_the_validation_suite.py:1714-1759"),
              "sure", "exo_wrist_strip_ends_taken_off", _wrist_strip, _wrist_strip_square_ended, by=("face accounting",)),
)  # fmt: skip

#: Two weaker candidates, tested beside the least sure (docs/V2-stage4.md, 16): no source says either was released.
WEAKER: tuple[FalsePass, ...] = (
    FalsePass(28, "a riser under L07's post", _suite("L07"),
              "a 5 mm riser nobody asked for, making the part 50 mm tall, “no taller than 50” read as "
              "exactly 50",
              "the limit turned into an equality, which the riser met",
              ("tests/fixtures/real_runs/validation_l07_height_limit_read_as_the_height.json",
               "docs/fixlist_v8.txt:373-380", "docs/V2-plan.md:134, 140"),
              "weaker: where the riser went isn't said (made here under the post), nor that it was released",
              "validation_l07_height_limit_read_as_the_height", "L07", _post_on_a_riser, by=("post/height/0",)),
)  # fmt: skip

#: A weaker candidate with no right part to judge against: V2's schema can't draft its brief.
UNDRAFTED = {
    "four holes drilled straight down through a curved plate": (
        "plate_curved_sized_twice: no kind bends a plate, so V2 can't draft the curved plate (its spec writer "
        "says so: UNABLE); the holes' direction is no question until it can (tests/test_real_answers.py:5043-5060)"
    ),
}


#: Where :func:`keys` are kept for ``forge eval-false-passes``, which reads no test file.
KEYS = Path(__file__).resolve().parent.parent / "validation" / "false_passes.json"


def keys() -> list[dict[str, Any]]:
    """The 27 as ``forge eval-false-passes`` reads them: each brief and its right spec's draft, the answer key (None for the two briefs with no right part, which no released part can answer: 21, 22; and for the two V2 can't make as given yet, so that any part released for them is wrong: 16, 23)."""
    found = []
    for case in FALSE_PASSES:
        b = number_words(case.brief)
        right = case.right
        none = case.caught in ("the accounting", "the assumptions --auto stops at") or case.judged_on is not None
        key = None if none else (DRAFTS[right](b) if isinstance(right, str) else right(b))
        found.append(
            {"number": case.number, "case": case.case, "brief": case.brief, "key": key}
        )
    return found


if __name__ == "__main__":  # writes the keys: python tests/v2_false_passes.py
    KEYS.write_text(
        json.dumps(keys(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
