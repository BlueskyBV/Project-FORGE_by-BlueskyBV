"""Items turned in a flat face's plane, planned, built and judged (place.turn; V2-stage4b-0c.md, 3.3, 1b's first move).

- **What is built is what was placed.** A turned slot, rectangular pocket,
  rib or block is its turned outline (straight sides and true arcs, a
  ``profile_outline``) on its face's plane, pushed into the material or out of
  it; built by the build loop, every face of it is accounted for both ways
  and every check its spec compiles to passes, on every face of a cube and
  for turns of either sign.
- **A wrong turn is caught.** The same plan with its outlines turned half a
  degree more, or moved 0.05 mm, fails the judge's face accounting.
- **The second kernel agrees** with the exact part, point by point.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft, mm, said
from v2_occ import needs_occ

_PLATE = "A plate 100 mm long, 60 mm wide and 8 mm thick. "
_CUBE = "A cube 60 mm long, 60 mm wide and 60 mm tall. "


def _turn(brief: Any, degrees: float) -> dict[str, Any]:
    return {"value": degrees, "unit": "deg", "from": said(brief, f"{degrees:g} degrees")}


def _body(brief: Any, cube: bool) -> dict[str, Any]:
    if cube:
        return {"id": "plate", "kind": "block", "words": cite(brief, "cube"), "length": mm(brief, 60, "60 mm"),
                "width": mm(brief, 60, "60 mm", 2), "height": mm(brief, 60, "60 mm", 3)}  # fmt: skip
    return {"id": "plate", "kind": "block", "words": cite(brief, "plate"), "length": mm(brief, 100, "100 mm"),
            "width": mm(brief, 60, "60 mm"), "height": mm(brief, 8, "8 mm")}  # fmt: skip


def _slot(brief: Any, degrees: float, *, ends: str = "round", through: bool = True, face: str = "+z",
          along: str = "x", **place: Any) -> dict[str, Any]:  # fmt: skip
    found = {"id": "slot", "kind": "slot", "words": cite(brief, "slots" if "slots" in brief.text else "slot"),
             "on": {"item": "plate", "face": face},
             "length": mm(brief, 30, "30 mm"), "width": mm(brief, 6, "6 mm"),
             "along": {"choose": along, "from": {"assumed": "its length along the plate"}},
             "ends": {"choose": ends, "from": {"assumed": "a milled slot"}},
             "place": {"turn": _turn(brief, degrees), **place}}  # fmt: skip
    found["depth"] = (
        {"through": True, "from": said(brief, "goes through")} if through else mm(brief, 3, "3 mm")
    )
    return found


def _pocket(brief: Any, corner: float | None = None) -> dict[str, Any]:
    found = {"id": "pocket", "kind": "pocket", "words": cite(brief, "pocket"), "on": {"item": "plate", "face": "+z"},
             "shape": {"choose": "rectangle", "from": {"assumed": "a rectangle"}},
             "length": mm(brief, 20, "20 mm"), "width": mm(brief, 10, "10 mm"), "depth": mm(brief, 5, "5 mm"),
             "place": {"turn": _turn(brief, 30)}}  # fmt: skip
    if corner is not None:
        found["corner_radius"] = assumed("rounded", corner)
    return found


def _rib(brief: Any, face: str = "+z", along: str = "x") -> dict[str, Any]:
    return {"id": "rib", "kind": "rib", "words": cite(brief, "rib"), "on": {"item": "plate", "face": face},
            "length": mm(brief, 40, "40 mm"), "thickness": mm(brief, 3, "3 mm"), "height": mm(brief, 10, "10 mm"),
            "along": {"choose": along, "from": {"assumed": "along the plate"}}, "place": {"turn": _turn(brief, 45)}}  # fmt: skip


def _block(brief: Any) -> dict[str, Any]:
    return {"id": "boss", "kind": "block", "words": cite(brief, "block"), "on": {"item": "plate", "face": "+z"},
            "length": mm(brief, 20, "20 mm"), "width": mm(brief, 10, "10 mm"), "height": mm(brief, 5, "5 mm"),
            "place": {"turn": _turn(brief, 30)}}  # fmt: skip


def _post(brief: Any) -> dict[str, Any]:
    return {"id": "post", "kind": "post", "words": cite(brief, "post"), "on": {"item": "plate", "face": "+z"},
            "length": mm(brief, 6, "6 mm"), "width": mm(brief, 4, "4 mm"), "height": mm(brief, 12, "12 mm"),
            "place": {"turn": _turn(brief, 30)}}  # fmt: skip


def _tab(brief: Any, end: str, degrees: float, long: float, face: str = "+z") -> dict[str, Any]:
    return {"id": "tab", "kind": "tab", "words": cite(brief, "tab"), "on": {"item": "plate", "face": face},
            "length": mm(brief, long, f"{long:g} mm"), "width": mm(brief, 9, "9 mm"),
            "thickness": mm(brief, 3, "3 mm"), "thickness_along": {"choose": "x", "from": {"assumed": "across"}},
            "end": {"choose": end, "from": {"assumed": end}}, "place": {"turn": _turn(brief, degrees)}}  # fmt: skip


def _letters(brief: Any, mode: str, degrees: float) -> dict[str, Any]:
    return {"id": "label", "kind": "text", "words": cite(brief, "letters"), "on": {"item": "plate", "face": "+z"},
            "text": {"text": "Fjgy 42", "from": said(brief, "Fjgy 42")}, "height": mm(brief, 6, "6 mm"),
            "depth": mm(brief, 1, "1 mm"), "mode": {"choose": mode, "from": said(brief, mode + "d")},
            "place": {"turn": _turn(brief, degrees)}}  # fmt: skip


SLOT = "A slot 30 mm long and 6 mm wide goes through it, turned {} degrees."
BLIND = "A slot 30 mm long and 6 mm wide, 3 mm deep, turned {} degrees."
POCKET = "A pocket 20 mm long, 10 mm wide and 5 mm deep is cut into it, turned 30 degrees."
RIB = "A rib 40 mm long, 3 mm thick and 10 mm tall stands on it, turned 45 degrees."
BLOCK = "A block 20 mm long, 10 mm wide and 5 mm tall stands on it, turned 30 degrees."
ROW = "Two slots 30 mm long and 6 mm wide, 40 mm apart, each goes through it, turned 30 degrees."
POST = "A post 6 mm long, 4 mm wide and 12 mm tall stands on it, turned 30 degrees."
TAB = "A tab {:g} mm long, 9 mm wide and 3 mm thick stands on it, turned {:g} degrees."
LETTERS = 'The letters "Fjgy 42", 6 mm tall and 1 mm deep, are {}d on it, turned {:g} degrees.'



def _planned(text: str, make: Any, *, cube: bool = False) -> tuple[Any, Any]:
    """The draft locked and planned: (the confirmed spec, the plan)."""
    from forge_plan import plan
    from forge_spec.checks import check_draft
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    brief = number_words((_CUBE if cube else _PLATE) + text)
    found = draft("plate", [_body(brief, cube), *make(brief)])
    report = check_draft(brief, found, strict=False)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, brief, by="draft", strict=False)
    planned = plan(spec)
    assert not planned.gaps, [g.reason for g in planned.gaps]
    return spec, planned


def _judged(text: str, make: Any, *, cube: bool = False) -> tuple[Any, Any, list[str]]:
    from test_v2_plan_build import judged_plan

    spec, planned = _planned(text, make, cube=cube)
    return judged_plan(spec.spec, planned)


class WhatIsWrittenIsTheTurnedOutline(unittest.TestCase):
    def test_a_turned_outline_of_sides_and_arcs(self) -> None:
        _, planned = _planned(SLOT.format(30), lambda b: [_slot(b, 30)])
        steps = planned.written().chain.steps
        ops = [step["op"] for step in steps if "slot" in step["for_items"]]
        self.assertIn("profile_outline", ops)
        self.assertNotIn("profile_slot", ops)
        outline = next(step for step in steps if step["op"] == "profile_outline")
        points = outline["params"]["points"]["points"]
        self.assertEqual(points[0], points[-1][:2])
        # Two straight sides and two half-circle ends, each end split into its corners' quarters.
        self.assertEqual(sum(len(p) == 4 for p in points[1:]), 4)
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        # Where its straight side meets its end, 12 mm along it and 3 mm across, turned; its ends' tips, 15 along.
        ends = {(round(p[0], 6), round(p[1], 6)) for p in points}
        self.assertIn((round(12 * c - 3 * s, 6), round(12 * s + 3 * c, 6)), ends)
        self.assertTrue({(round(15 * c, 6), round(15 * s, 6)), (round(-15 * c, 6), round(-15 * s, 6))} <= ends)


@needs_occ
class TurnedItemsAreBuiltAsPlaced(unittest.TestCase):
    def _passes(self, text: str, make: Any, *, cube: bool = False) -> None:
        from forge_checks.classes import Verdict

        built, accounting, failed = _judged(text, make, cube=cube)
        self.assertIsNone(built.gap, built.refusals)
        self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
        self.assertEqual(failed, [])

    def test_cuts(self) -> None:
        cases = {
            "round-ended, through": (SLOT.format(30), lambda b: [_slot(b, 30)]),
            "square-ended, through": (SLOT.format(30), lambda b: [_slot(b, 30, ends="square")]),
            "blind": (BLIND.format(30), lambda b: [_slot(b, 30, through=False)]),
            "measured to its edge": (SLOT.format(30)[:-1] + ", 4 mm from the -x edge.",
                                     lambda b: [_slot(b, 30, x={"side": "-x", "distance": mm(b, 4, "4 mm"),
                                                                "to": "edge"})]),
            "a pocket": (POCKET, lambda b: [_pocket(b)]),
            "a pocket, its corners rounded": (POCKET, lambda b: [_pocket(b, 2.0)]),
        }  # fmt: skip
        for name, (text, make) in cases.items():
            with self.subTest(name):
                self._passes(text, make)

    def test_copies(self) -> None:
        def row(b: Any) -> list[dict[str, Any]]:
            pattern = {"row": {"count": {"count": 2, "from": said(b, "Two")}, "pitch": mm(b, 40, "40 mm"),
                               "axis": {"choose": "x", "from": {"assumed": "along the plate"}}}}  # fmt: skip
            found = _slot(b, 30, pattern=pattern)
            found["count"] = {"count": 2, "from": said(b, "Two")}
            return [found]

        self._passes(ROW, row)

    def test_standing(self) -> None:
        self._passes(RIB, lambda b: [_rib(b)])
        self._passes(BLOCK, lambda b: [_block(b)])
        self._passes(POST, lambda b: [_post(b)])

    def test_tabs(self) -> None:
        # Square-ended; round-ended; round-ended shorter than its width (its rounding's circle reaches past its foot,
        # kept beyond it); on a cube's -y face, turned the other way.
        for end, degrees, long, face in (("square", 30, 12, "+z"), ("round", 30, 12, "+z"), ("round", 120, 5, "+z"),
                                         ("round", -45, 12, "-y")):  # fmt: skip
            with self.subTest(end=end, turn=degrees, length=long, face=face):
                self._passes(TAB.format(long, degrees), lambda b, e=end, d=degrees, n=long, f=face: [_tab(b, e, d, n, f)],
                             cube=face != "+z")  # fmt: skip

    def test_letters(self) -> None:
        # Engraved and embossed, turned by a quarter's third and all but upside down; their ink (a j's tail, a y's)
        # reaches past their line's box.
        for mode, degrees in (("engrave", 30), ("emboss", 120), ("engrave", 270)):
            with self.subTest(mode=mode, turn=degrees):
                self._passes(LETTERS.format(mode, degrees), lambda b, m=mode, d=degrees: [_letters(b, m, d)])

    def test_every_face_and_either_sign(self) -> None:
        along = {"+z": "x", "-z": "x", "+x": "y", "-x": "y", "+y": "x", "-y": "z"}
        rib_along = {"+z": "y", "-z": "y", "+x": "z", "-x": "z", "+y": "z", "-y": "x"}
        for face in along:
            for degrees in (30, -60, 135):
                with self.subTest(face=face, turn=degrees):
                    self._passes(BLIND.format(degrees),
                                 lambda b, f=face, d=degrees: [_slot(b, d, through=False, face=f, along=along[f])],
                                 cube=True)  # fmt: skip
            with self.subTest(face=face, rib=True):
                self._passes(RIB, lambda b, f=face: [_rib(b, f, rib_along[f])], cube=True)


@needs_occ
class AWrongTurnIsCaught(unittest.TestCase):
    def test_turned_more_or_moved(self) -> None:
        import forge_plan.items.plan._tools as tools
        from forge_checks.classes import Verdict

        real = tools.shape_points
        a = math.radians(0.5)
        wrongs = {"turned half a degree more": lambda shape: shape.turned(math.cos(a), math.sin(a)),
                  "moved 0.05 mm": lambda shape: shape.moved(0.05, 0.0)}  # fmt: skip
        cases = {"slot": (SLOT.format(30), lambda b: [_slot(b, 30)]), "rib": (RIB, lambda b: [_rib(b)]),
                 "pocket": (POCKET, lambda b: [_pocket(b, 2.0)]), "block": (BLOCK, lambda b: [_block(b)]),
                 "post": (POST, lambda b: [_post(b)]), "tab": (TAB.format(12, 30), lambda b: [_tab(b, "square", 30, 12)])}  # fmt: skip
        for how, wrong in wrongs.items():
            for name, (text, make) in cases.items():
                with self.subTest(how=how, item=name), mock.patch.object(
                    tools, "shape_points", lambda shape, offset=(0.0, 0.0), w=wrong: real(w(shape), offset)
                ):
                    built, accounting, _ = _judged(text, make)
                    self.assertIsNone(built.gap)
                    self.assertIs(accounting.verdict, Verdict.FAIL)

    def test_a_round_tab_or_letters_turned_more(self) -> None:
        import forge_plan.items.plan.tab as tab
        import forge_plan.letters as letters
        from forge_checks.classes import Verdict

        real_degrees, real_turn = tab.degrees, letters.turn_of

        def more(item: Any) -> tuple[float, float] | None:
            found = real_turn(item)
            if found is None:
                return None
            angle = math.atan2(found[1], found[0]) + math.radians(0.5)
            return math.cos(angle), math.sin(angle)

        with self.subTest("a round-ended tab"), mock.patch.object(tab, "degrees", lambda v: real_degrees(v) + 0.5):
            built, accounting, _ = _judged(TAB.format(12, 30), lambda b: [_tab(b, "round", 30, 12)])
            self.assertIsNone(built.gap)
            self.assertIs(accounting.verdict, Verdict.FAIL)
        with self.subTest("letters"), mock.patch.object(letters, "turn_of", more):
            built, accounting, _ = _judged(LETTERS.format("engrave", 30), lambda b: [_letters(b, "engrave", 30)])
            self.assertIsNone(built.gap)
            self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_round_tab_turned_by_a_rigid_motion(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        _, planned = _planned(TAB.format(5, 120), lambda b: [_tab(b, "round", 120, 5)])
        built = build_plan(planned)
        self.assertIsNone(built.gap, built.refusals)
        report = agree(planned.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))

    def test_a_turned_slot_and_rib(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        text = SLOT.format(30) + " " + RIB
        _, planned = _planned(text, lambda b: [_slot(b, 30), _rib(b)])
        built = build_plan(planned)
        self.assertIsNone(built.gap, built.refusals)
        report = agree(planned.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
