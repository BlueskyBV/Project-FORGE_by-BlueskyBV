"""V2: what is under a hollowed body's closed wall, and a cut right through it (frame.md, "A hollowed body's face").

The solver read a hollowed cone's closed end as the solid cone's (its
length, falling off past its smaller end's radius), so a blind hole 10 mm
deep in a cup's 3 mm floor was accepted, and built as a hole into the cup.
And a cut right through a hollowed body's wall whose mouth ran past the
hollow's edge (a drain hole half under a planter's side wall, a hole in a
tray's side half beside its floor) was built through the wall's thickness:
there it ended in the wall, short of coming out. What these hold:

- **Under a closed wall:** its thickness, and the body's own where that is
  less (near a cone's larger end's rim, near a dome's rim).
- **Right through a wall:** wholly over the hollow behind it, or asked
  about: on a block's face, a cylinder's end or side, a cone's end, a
  dome's floor.
- **Coming out on the wall's other face:** under what stands on the
  hollow's inside floor, or (from inside) under its floor, it is asked about
  as through a solid plate under a boss.
- **Said before anything is built:** a rim rounded right over (the two
  roundings meeting in its middle), and a floor's edge rounded where the
  floor is thicker than the walls, which the part then failed to build.

The briefs are written here, not taken from any blind set.
"""

from __future__ import annotations

import unittest
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.geometry import Taper
from forge_spec.items.solve.cone import walled
from v2_drafts import assumed, cite, draft, mm, said

PAST = "runs past the edge of the hollow behind it"


def problems(brief: str, items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    report = check_draft(number_words(brief), draft("part", items))
    return [(p.kind, p.message) for p in report.problems]


def shell(b: Any, of: str, opened: list[str], floor: str | None) -> dict[str, Any]:
    found: dict[str, Any] = {"id": "hollow", "kind": "shell", "words": cite(b, "hollow"), "of": of,
                             "thickness": mm(b, 2, "2 mm walls"),
                             "open": {"faces": opened, "from": said(b, "open at the top")}}  # fmt: skip
    if floor is not None:
        found["floor"] = mm(b, 3 if floor == "3" else float(floor), f"{floor} mm floor")
    return found


def hole(b: Any, on: str, face: str, words: str, size: str, place: dict[str, Any],
         depth: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    return {"id": "hole", "kind": "hole", "words": cite(b, words), "on": {"item": on, "face": face},
            "diameter": mm(b, float(size), f"{size} mm"), "place": place, "depth": depth}  # fmt: skip


def off(b: Any, value: float, phrase: str) -> dict[str, Any]:
    return {"x": {"offset": mm(b, value, phrase)}, "y": {"centred": assumed("on a line through its centre")}}


THROUGH = {"through": True, "from": {"assumed": "a drain goes through"}}

PLANTER = ("A planter: a cylinder 50 mm across and 60 mm tall, hollow with 2 mm walls and a 3 mm floor, open at the top, "
           "with a 4 mm drain hole through the floor {} mm from its centre.")  # fmt: skip


def planter(at: int) -> list[tuple[str, str]]:
    brief = PLANTER.format(at)
    b = number_words(brief)
    return problems(brief, [
        {"id": "pot", "kind": "cylinder", "words": cite(b, "cylinder"), "axis": {"choose": "z", "from": assumed("up")},
         "diameter": mm(b, 50, "50 mm across"), "length": mm(b, 60, "60 mm tall")},
        shell(b, "pot", ["+end"], "3"),
        hole(b, "pot", "-end", "drain hole", "4", off(b, at, f"{at} mm from its centre"), THROUGH),
    ])  # fmt: skip


TRAY = ("A tray 60 x 40 x 20 mm, hollow with 2 mm walls and a 3 mm floor, open at the top, with a 4 mm hole through "
        "one long side {} mm up from the bottom.")  # fmt: skip


def tray(up: int) -> list[tuple[str, str]]:
    brief = TRAY.format(up)
    b = number_words(brief)
    return problems(brief, [
        {"id": "tray", "kind": "block", "words": cite(b, "tray"), "length": mm(b, 60, "60"), "width": mm(b, 40, "40"),
         "height": mm(b, 20, "20 mm", 1)},
        shell(b, "tray", ["+z"], "3"),
        hole(b, "tray", "+y", "hole through one long side", "4",
             {"x": {"centred": assumed("in the middle of the side")},
              "z": {"side": "-z", "distance": mm(b, up, f"{up} mm up from the bottom"), "to": "centre"}}, THROUGH),
    ])  # fmt: skip


CUP = ("A cup: a cone 50 mm across at its base and 30 mm across at its top, 60 mm tall, hollow with 2 mm walls and a "
       "3 mm floor, open at the top, with a 4 mm hole {} in its base {} mm from its centre.")  # fmt: skip


def cup(depth: str, at: int) -> list[tuple[str, str]]:
    brief = CUP.format(depth, at)
    b = number_words(brief)
    deep = THROUGH if depth == "through" else mm(b, 10, "10 mm deep")
    return problems(brief, [
        {"id": "cup", "kind": "cone", "words": cite(b, "cone"), "axis": {"choose": "z", "from": assumed("up")},
         "base_diameter": mm(b, 50, "50 mm across at its base"), "top_diameter": mm(b, 30, "30 mm across"),
         "length": mm(b, 60, "60 mm tall")},
        shell(b, "cup", ["+end"], "3"),
        hole(b, "cup", "-end", "4 mm hole", "4", off(b, at, f"{at} mm from its centre"), deep),
    ])  # fmt: skip


DOME = ("A dome 60 mm across, hollow with 2 mm walls and a 10 mm floor, with a 3 mm hole {} in its floor {} mm from "
        "its centre.")  # fmt: skip


def dome(depth: str, at: float) -> list[tuple[str, str]]:
    brief = DOME.format(depth, f"{at:g}")
    b = number_words(brief)
    deep = THROUGH if depth == "through" else mm(b, 8, "8 mm deep")
    hollow = {"id": "hollow", "kind": "shell", "words": cite(b, "hollow"), "of": "dome",
              "thickness": mm(b, 2, "2 mm walls"), "floor": mm(b, 10, "10 mm floor"),
              "open": {"faces": [], "from": {"assumed": "sealed"}}}  # fmt: skip
    return problems(brief, [
        {"id": "dome", "kind": "sphere", "words": cite(b, "dome"), "diameter": mm(b, 60, "60 mm across"),
         "portion": {"choose": "upper_half", "from": said(b, "dome")}},
        hollow,
        hole(b, "dome", "-end", "3 mm hole", "3", off(b, at, f"{at:g} mm from its centre"), deep),
    ])  # fmt: skip


class UnderAClosedWall(unittest.TestCase):
    def test_a_cones_end_falls_off_as_its_own_past_where_its_flank_is_the_walls_height(self) -> None:
        self.assertEqual(walled(Taper(15.0, 25.0, 60.0), 3.0), Taper(24.5, 25.0, 3.0))
        self.assertIsNone(walled(None, 3.0))  # its smaller end: the wall all across

    def test_a_blind_hole_deeper_than_a_cups_floor_anywhere_on_it(self) -> None:
        for at in (5, 20):  # over the hollow, and past its smaller end's radius (where the solid cone is 30 mm)
            with self.subTest(at=at):
                found = cup("10 mm deep", at)
                self.assertTrue(any("10 mm deep in 3 mm of material" in m for _, m in found), found)

    def test_a_blind_hole_near_a_hollow_domes_rim_where_the_dome_is_lower_than_its_floor(self) -> None:
        self.assertEqual(dome("8 mm deep", 20), [])  # over the hollow: its 10 mm floor
        found = dome("8 mm deep", 27.5)  # its edge 29 mm out, the dome there 7.5 mm high
        self.assertTrue(any("8 mm deep" in m and "of material" in m for _, m in found), found)


class RightThroughAWall(unittest.TestCase):
    def test_wholly_over_the_hollow(self) -> None:
        for name, found in (("planter", planter(15)), ("tray", tray(10)), ("cup", cup("through", 15)),
                            ("dome", dome("through", 20))):  # fmt: skip
            with self.subTest(name):
                self.assertEqual(found, [])

    def test_past_the_hollows_edge_is_asked_about(self) -> None:
        for name, found in (("a planter's drain half under its side wall", planter(22)),
                            ("a tray's side hole half beside its floor", tray(3)),
                            ("a cup's hole past its hollow's edge", cup("through", 21)),
                            ("a dome's floor near its rim", dome("through", 27))):  # fmt: skip
            with self.subTest(name):
                self.assertEqual([k for k, m in found if PAST in m], ["question"], found)

    def test_round_a_hollowed_cylinders_side_between_its_hollows_ends(self) -> None:
        brief = ("A pot: a cylinder 50 mm across and 60 mm tall, hollow with 2 mm walls and a 3 mm floor, open at the top, "
                 "with a 4 mm hole through its side {} mm up from the bottom.")  # fmt: skip

        def pot(up: int) -> list[tuple[str, str]]:
            text = brief.format(up)
            b = number_words(text)
            side = {"z": {"side": "-z", "distance": mm(b, up, f"{up} mm up from the bottom"), "to": "centre"},
                    "angle": {"value": 0, "unit": "deg", "from": {"assumed": "facing +x"}}}  # fmt: skip
            return problems(text, [
                {"id": "pot", "kind": "cylinder", "words": cite(b, "cylinder"),
                 "axis": {"choose": "z", "from": assumed("up")}, "diameter": mm(b, 50, "50 mm across"),
                 "length": mm(b, 60, "60 mm tall")},
                shell(b, "pot", ["+end"], "3"),
                hole(b, "pot", "side", "4 mm hole through its side", "4", side, THROUGH),
            ])  # fmt: skip

        self.assertEqual(pot(20), [])
        for up in (3, 2):  # half beside its floor, its edge at its foot
            with self.subTest(up=up):
                self.assertEqual([k for k, m in pot(up) if PAST in m], ["question"], pot(up))


POT = ("A pot: a cylinder 50 mm across and 60 mm tall, hollow with 2 mm walls and a 3 mm floor, open at the top, with "
       "a boss 10 mm across and 5 mm tall on its {} {} mm from its centre, and a 4 mm hole through its floor from {} at "
       "its centre.")  # fmt: skip


def pot_with_a_boss(boss_on: str, at: int, hole_from: str) -> list[tuple[str, str]]:
    brief = POT.format("inside floor" if boss_on == "inner -end" else "underside", at,
                       "inside" if hole_from == "inner -end" else "below")  # fmt: skip
    b = number_words(brief)
    return problems(brief, [
        {"id": "pot", "kind": "cylinder", "words": cite(b, "cylinder"), "axis": {"choose": "z", "from": assumed("up")},
         "diameter": mm(b, 50, "50 mm across"), "length": mm(b, 60, "60 mm tall")},
        shell(b, "pot", ["+end"], "3"),
        {"id": "boss", "kind": "boss", "words": cite(b, "boss"), "on": {"item": "pot", "face": boss_on},
         "diameter": mm(b, 10, "10 mm across"), "height": mm(b, 5, "5 mm tall"),
         "place": off(b, at, f"{at} mm from its centre")},
        hole(b, "pot", hole_from, "4 mm hole through its floor", "4",
             {"x": {"centred": said(b, "at its centre")}, "y": {"centred": said(b, "at its centre")}}, THROUGH),
    ])  # fmt: skip


class ComingOutUnderWhatStandsThere(unittest.TestCase):
    """Through a hollowed body's wall a cut comes out on the wall's other face: under what stands on the hollow's
    inside floor, or under the floor from inside, it is asked about as through a solid plate under a boss."""

    def test_from_outside_under_what_stands_in_the_hollow(self) -> None:
        found = pot_with_a_boss("inner -end", 0, "-end")
        self.assertEqual([k for k, m in found if "comes out under boss" in m and "inner -end" in m], ["question"], found)
        self.assertEqual(pot_with_a_boss("inner -end", 12, "-end"), [])  # beside it

    def test_from_inside_under_what_stands_below(self) -> None:
        found = pot_with_a_boss("-end", 0, "inner -end")
        self.assertEqual([k for k, m in found if "comes out under boss" in m], ["question"], found)
        self.assertEqual(pot_with_a_boss("-end", 12, "inner -end"), [])


CUP_ROUNDED = ("A cup: a cylinder 50 mm across and 60 mm tall, hollow with 2 mm walls and a {} mm floor, open at the top, "
               "its {} edge {} {} mm.")  # fmt: skip


def cup_rounded(floor: int, which: str, kind: str, size: float) -> list[tuple[str, str]]:
    brief = CUP_ROUNDED.format(floor, which, "rounded" if kind == "fillet" else "bevelled", f"{size:g}")
    b = number_words(brief)
    edge = {"id": "edge", "kind": kind, "words": cite(b, f"its {which} edge"),
            "edges": {"of": "cup", "which": which, "words": cite(b, f"its {which} edge")},
            "radius" if kind == "fillet" else "size": mm(b, size, f"{size:g} mm")}  # fmt: skip
    return problems(brief, [
        {"id": "cup", "kind": "cylinder", "words": cite(b, "cylinder"), "axis": {"choose": "z", "from": assumed("up")},
         "diameter": mm(b, 50, "50 mm across"), "length": mm(b, 60, "60 mm tall")},
        shell(b, "cup", ["+end"], str(floor)),
        edge,
    ])  # fmt: skip


class WhatIsNotMadeYetIsSaidBeforeAnythingIsBuilt(unittest.TestCase):
    """Two roundings OpenCascade couldn't make, or the planner had no construction for, were accepted, and the part
    then failed to build: each is said at the spec now, before the person confirms it."""

    def test_a_rim_rounded_right_over(self) -> None:
        self.assertEqual(cup_rounded(3, "top", "fillet", 0.8), [])
        for kind in ("fillet", "chamfer"):
            with self.subTest(kind):
                found = cup_rounded(3, "top", kind, 1)  # half its 2 mm wall: the two meet in its middle
                self.assertEqual([k for k, m in found if "right over" in m], ["question"], found)

    def test_a_floor_edge_rounded_where_the_floor_is_thicker_than_the_walls(self) -> None:
        self.assertEqual(cup_rounded(2, "bottom", "fillet", 4), [])  # one thickness all round: the hollow follows it
        for kind in ("fillet", "chamfer"):
            with self.subTest(kind):
                found = cup_rounded(3, "bottom", kind, 4)
                self.assertEqual([k for k, m in found if "walls of different thickness" in m], ["unable"], found)


if __name__ == "__main__":
    unittest.main()
