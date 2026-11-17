"""Items turned in a flat face's plane, as the solver places them (place.turn; schema 1.2; V2-stage4b-0c.md, 3.3, 1b's first move).

- **A turn is read, written and cited** as an angle, only in schema 1.2
  drafts, and only on what can be turned: a slot, a rectangular pocket, a
  rib or a block on a flat face.
- **A turned item is fitted on its turned outline:** where it runs off its
  face it is asked about; measured to its edge, the turned outline's
  nearest point is its edge; copies of it are held apart on their turned
  outlines; a cut's depth is held to the material under its turned mouth.
- **What follows from a turn:** a turned item's faces take nothing yet, a
  standing one's bounds are the box round it turned, and a turned cut that
  goes through is held to what stands on the far face over its mouth.
"""

from __future__ import annotations

import copy
import math
import unittest
from typing import Any

from forge_spec.checks import check_draft
from forge_spec.wire import to_wire
from forge_spec.words import number_words
from v2_drafts import assumed, cite, draft, mm, said

BRIEF = number_words(
    "A plate 100 mm long, 60 mm wide and 8 mm thick. A slot 30 mm long and 6 mm wide goes through it, "
    "turned 30 degrees, 4 mm from the -x edge. A rib 40 mm long, 3 mm thick and 10 mm tall stands on it, "
    "turned 45 degrees. A pocket 20 mm long, 10 mm wide and 5 mm deep is cut into it."
)
B = BRIEF


def _plate() -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(B, "plate"), "length": mm(B, 100, "100 mm"),
            "width": mm(B, 60, "60 mm"), "height": mm(B, 8, "8 mm")}  # fmt: skip


def _slot(**place: Any) -> dict[str, Any]:
    return {"id": "slot", "kind": "slot", "words": cite(B, "slot"), "on": {"item": "plate", "face": "+z"},
            "length": mm(B, 30, "30 mm"), "width": mm(B, 6, "6 mm"),
            "along": {"choose": "x", "from": {"assumed": "its length along the plate"}},
            "ends": {"choose": "round", "from": {"assumed": "a milled slot"}},
            "depth": {"through": True, "from": said(B, "goes through")},
            "place": {"turn": {"value": 30, "unit": "deg", "from": said(B, "30 degrees")}, **place}}  # fmt: skip


def _report(*items: dict[str, Any], version: str = "1.2") -> Any:
    found = draft("plate", [_plate(), *items])
    found["schema_version"] = version
    return check_draft(B, found, strict=False)


def _placing(report: Any) -> list[str]:
    """The problems placing the items finds (not the brief's numbers the spec leaves unused)."""
    return [p.message for p in report.problems
            if "nothing in the spec uses it" not in p.message and "nothing in the spec comes from" not in p.message]  # fmt: skip


def _says(report: Any, text: str) -> bool:
    return any(text in message for message in _placing(report))


class ATurnIsReadWrittenAndCited(unittest.TestCase):
    def test_read_and_written(self) -> None:
        report = _report(_slot())
        self.assertEqual(_placing(report), [])
        place = report.spec.item("slot").get("place")
        self.assertEqual(place.turn.made_in("deg"), 30.0)
        self.assertEqual(to_wire(report.spec)["items"][1]["place"]["turn"]["value"], 30)

    def test_only_in_schema_1_2(self) -> None:
        report = _report(_slot(), version="1.1")
        self.assertIn("/items/1/place/turn", [p.at for p in report.problems])

    def test_only_what_can_be_turned(self) -> None:
        hole = {"id": "hole", "kind": "hole", "words": cite(B, "slot"), "on": {"item": "plate", "face": "+z"},
                "diameter": mm(B, 6, "6 mm"), "depth": {"through": True, "from": said(B, "goes through")},
                "place": {"turn": {"value": 30, "unit": "deg", "from": said(B, "30 degrees")}}}  # fmt: skip
        report = _report(hole)
        self.assertTrue(
            _says(report, "Forge turns a slot, a rectangular pocket, a rib, a tab, a block, a post or a line of letters")
        )


class ATurnedItemIsFittedOnItsTurnedOutline(unittest.TestCase):
    def test_measured_to_its_edge(self) -> None:
        side = {"x": {"side": "-x", "distance": mm(B, 4, "4 mm"), "to": "edge"}}
        report = _report(_slot(**side))
        self.assertEqual(_placing(report), [])
        (copy_,) = report.layout.instances["slot"]
        # Turned 30 degrees, the slot reaches back along x by its half length's run plus its end's radius.
        reach = 12.0 * math.cos(math.radians(30)) + 3.0
        self.assertAlmostEqual(copy_.origin[0], -50.0 + 4.0 + reach, places=9)

    def test_running_off_its_face(self) -> None:
        report = _report(
            _slot(
                x={"offset": mm(B, 4, "4 mm")},
                y={"side": "+y", "distance": assumed("near", 2.0)},
            )
        )
        self.assertTrue(_says(report, "turned 30°, runs off face +z"))

    def test_copies_apart_on_their_turned_outlines(self) -> None:
        row = {
            "pattern": {
                "row": {
                    "count": {"count": 2, "from": {"assumed": "two slots"}},
                    "pitch": assumed("close", 8.0),
                    "axis": {"choose": "x", "from": {"assumed": "along the plate"}},
                }
            }
        }
        slot = _slot(**row)
        slot["count"] = {"count": 2, "from": {"assumed": "two slots"}}
        report = _report(slot)
        self.assertTrue(_says(report, "copies 1 and 2 of slot overlap"))
        far = copy.deepcopy(slot)
        far["place"]["pattern"]["row"]["pitch"] = assumed("far", 40.0)
        self.assertFalse(_says(_report(far), "overlap"))


class WhatFollowsFromATurn(unittest.TestCase):
    def test_a_turned_ribs_faces_and_bounds(self) -> None:
        rib = {"id": "rib", "kind": "rib", "words": cite(B, "rib"), "on": {"item": "plate", "face": "+z"},
               "length": mm(B, 40, "40 mm"), "thickness": mm(B, 3, "3 mm"), "height": mm(B, 10, "10 mm"),
               "along": {"choose": "x", "from": {"assumed": "along the plate"}},
               "place": {"turn": {"value": 45, "unit": "deg", "from": said(B, "45 degrees")}}}  # fmt: skip
        report = _report(rib)
        self.assertEqual(_placing(report), [])
        (copy_,) = report.layout.instances["rib"]
        half = (20.0 + 1.5) * math.cos(math.radians(45))
        self.assertAlmostEqual(copy_.hi[0] - copy_.lo[0], 2 * half, places=9)
        self.assertAlmostEqual(copy_.hi[2] - copy_.lo[2], 10.0, places=9)
        # Its far face takes things, turned with it (schema 1.4): its own height and the plate's under it; its others
        # are closed.
        (top,) = report.layout.faces[("rib", 0)].values()
        self.assertEqual((top.name, top.turn, top.half, top.depth_below), ("+z", 45.0, (20.0, 1.5), 10.0 + 8.0))
        self.assertIn("+x", report.layout.closed[("rib", 0)])

    def test_a_turned_pockets_depth_and_floor(self) -> None:
        pocket = {"id": "pocket", "kind": "pocket", "words": cite(B, "pocket"), "on": {"item": "plate", "face": "+z"},
                  "shape": {"choose": "rectangle", "from": {"assumed": "a rectangle"}},
                  "length": mm(B, 20, "20 mm"), "width": mm(B, 10, "10 mm"), "depth": mm(B, 5, "5 mm"),
                  "place": {"turn": {"value": 30, "unit": "deg", "from": said(B, "30 degrees")}}}  # fmt: skip
        report = _report(pocket)
        self.assertEqual(_placing(report), [])
        # Its floor takes things, turned with it (schema 1.4): the plate's 8 mm less its 5 under it.
        floor = report.layout.faces[("pocket", 0)]["bottom"]
        self.assertEqual((floor.turn, floor.half, floor.depth_below), (30.0, (10.0, 5.0), 3.0))
        deep = copy.deepcopy(pocket)
        deep["depth"] = assumed("too deep", 12.0)
        self.assertTrue(_says(_report(deep), "deep in 8 mm of material"))


def _post(at: tuple[float, float], face: str = "+z", size: float = 2.0) -> dict[str, Any]:
    """A small block standing on the plate at ``at`` (its sizes and place assumed)."""
    return {"id": "post", "kind": "block", "words": cite(B, "plate"), "on": {"item": "plate", "face": face},
            "length": assumed("small", size), "width": assumed("small", size), "height": assumed("short", 3.0),
            "place": {"x": {"offset": assumed("there", at[0])}, "y": {"offset": assumed("there", at[1])}}}  # fmt: skip


def _pocket(turn: float = 45.0) -> dict[str, Any]:
    return {"id": "pocket", "kind": "pocket", "words": cite(B, "pocket"), "on": {"item": "plate", "face": "+z"},
            "shape": {"choose": "rectangle", "from": {"assumed": "a rectangle"}},
            "length": mm(B, 20, "20 mm"), "width": mm(B, 10, "10 mm"), "depth": mm(B, 5, "5 mm"),
            "place": {"turn": assumed("turned", turn, "deg")}}  # fmt: skip


def _letters(turn: float, **place: Any) -> dict[str, Any]:
    return {"id": "label", "kind": "text", "words": cite(B, "plate"), "on": {"item": "plate", "face": "+z"},
            "text": {"text": "Fjgy", "from": {"assumed": "a label"}}, "height": assumed("tall", 6.0),
            "depth": assumed("deep", 1.0), "mode": {"choose": "engrave", "from": {"assumed": "engraved"}},
            "place": {"turn": assumed("turned", turn, "deg"), **place}}  # fmt: skip


class WhatTurnsAndWhere(unittest.TestCase):
    def test_a_round_footprint_a_round_side_or_concentric(self) -> None:
        boss = {"id": "boss", "kind": "boss", "words": cite(B, "plate"), "on": {"item": "plate", "face": "+z"},
                "diameter": assumed("round", 8.0), "height": assumed("tall", 5.0),
                "place": {"turn": assumed("turned", 30.0, "deg")}}  # fmt: skip
        self.assertTrue(_says(_report(boss), "not a boss"))
        rod = {"id": "rod", "kind": "cylinder", "words": cite(B, "plate"), "on": {"item": "plate", "face": "+z"},
               "diameter": assumed("rod", 20.0), "length": assumed("rod", 20.0)}  # fmt: skip
        post = {"id": "post", "kind": "post", "words": cite(B, "plate"), "on": {"item": "rod", "face": "side"},
                "length": assumed("small", 3.0), "width": assumed("small", 3.0), "height": assumed("short", 3.0),
                "place": {"turn": assumed("turned", 30.0, "deg")}}  # fmt: skip
        self.assertIn("/items/2/place/turn", [p.at for p in _report(rod, post).problems if p.kind == "fault"])
        centred = _pocket()
        centred["place"]["concentric"] = {"item": "plate", "from": {"assumed": "on its axis"}}
        self.assertTrue(_says(_report(centred), "not concentric with another"))

    def test_a_post_and_a_tab_turned(self) -> None:
        post = _post((0.0, 0.0))
        post["place"]["turn"] = assumed("turned", 30.0, "deg")
        tab = {"id": "tab", "kind": "tab", "words": cite(B, "plate"), "on": {"item": "plate", "face": "+z"},
               "length": assumed("out", 12.0), "width": assumed("wide", 9.0), "thickness": assumed("thin", 3.0),
               "thickness_along": {"choose": "x", "from": {"assumed": "across"}},
               "end": {"choose": "round", "from": {"assumed": "round"}},
               "place": {"x": {"offset": assumed("aside", 25.0)}, "turn": assumed("turned", 60.0, "deg")}}  # fmt: skip
        report = _report(post, tab)
        self.assertEqual(_placing(report), [])
        (copy_,) = report.layout.instances["tab"]
        c, s_ = math.cos(math.radians(60)), math.sin(math.radians(60))
        self.assertAlmostEqual(copy_.hi[0] - copy_.lo[0], 2 * (1.5 * c + 4.5 * s_), places=9)
        self.assertAlmostEqual(copy_.hi[2] - copy_.lo[2], 12.0, places=9)
        # The post's far face takes things, turned with it; the round-ended tab's is curved: neither's others do.
        self.assertEqual(list(report.layout.faces.get(("post", 0), {})), ["+z"])
        self.assertEqual(report.layout.faces[("post", 0)]["+z"].turn, 30.0)
        self.assertEqual(report.layout.faces.get(("tab", 0), {}), {})

    def test_letters_placed_by_their_line_fitted_by_their_ink(self) -> None:
        from forge_spec.font import text_width

        line = text_width("Fjgy", 6.0)
        # Turned a quarter, their line's box runs along y: 4 mm from the -y edge to its edge, its middle is half its
        # length further in.
        report = _report(_letters(90.0, y={"side": "-y", "distance": assumed("near", 4.0), "to": "edge"}))
        self.assertEqual(_placing(report), [])
        (copy_,) = report.layout.instances["label"]
        self.assertAlmostEqual(copy_.origin[1], -30.0 + 4.0 + line / 2, places=9)
        # Their ink reaches past their line's box (the j's dot a quarter of a millimetre above a capital's height):
        # turned three quarters, up is +x, and placed 0.2 mm from the +x edge the dot runs off the face, though their
        # line's box is on it.
        near = _report(_letters(270.0, x={"side": "+x", "distance": assumed("near", 0.2), "to": "edge"}))
        self.assertTrue(_says(near, "label copy 1, turned 270\u00b0, runs off face +z"))


class ATurnedOutlineIsHeldExactly(unittest.TestCase):
    """What stands by a turned item is held to its turned outline, not the box round it."""

    def test_standing_over_a_turned_mouth(self) -> None:
        # At the pocket's middle, the post stands wholly over its mouth: held up by nothing.
        self.assertTrue(_says(_report(_pocket(), _post((0.0, 0.0))), "stands wholly over the mouth of pocket"))
        # In the box round the turned pocket (10.6 mm each way), but clear of the pocket itself.
        clear = _report(_pocket(), _post((8.0, -8.0)))
        self.assertFalse(_says(clear, "stands wholly over"))
        self.assertFalse(_says(clear, "overlap"))

    def test_coming_out_under_what_stands_on_the_far_face(self) -> None:
        slot = _slot()  # 30 mm by 6 turned 30 degrees, right through
        self.assertTrue(_says(_report(slot, _post((0.0, 0.0), "-z")), "comes out under post copy 1 on -z"))
        # In the box round the turned slot, clear of its outline: through, it comes out in the open.
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        at = (-6.0 * s + 0.0, 6.0 * c)  # 6 mm across the slot's middle from its axis, 3 mm past its side
        self.assertFalse(_says(_report(slot, _post(at, "-z", 1.0)), "comes out under"))


class TwoDraftsCompareTheirTurns(unittest.TestCase):
    """Two drafts turned alike build one part; turned otherwise, another (forge_spec.compare)."""

    def _differ(self, first: dict[str, Any], second: dict[str, Any]) -> bool:
        from forge_spec.compare import differences

        return bool(differences(_report(first), _report(second)))

    def _turned(self, degrees: float, along: str = "x") -> dict[str, Any]:
        slot = _slot()
        slot["place"]["turn"] = assumed(f"turned {degrees:g} degrees", degrees)
        slot["place"]["turn"]["unit"] = "deg"
        slot["along"]["choose"] = along
        return slot

    def test_turned_alike_or_otherwise(self) -> None:
        self.assertFalse(self._differ(self._turned(30), self._turned(30)))
        self.assertTrue(self._differ(self._turned(30), self._turned(35)))
        # A slot is the same turned half a turn, and the same along y a quarter turn back.
        self.assertFalse(self._differ(self._turned(30), self._turned(210)))
        self.assertFalse(self._differ(self._turned(120), self._turned(30, along="y")))

    def test_turned_or_not(self) -> None:
        plain = _slot()
        del plain["place"]["turn"]
        self.assertTrue(self._differ(plain, self._turned(30)))
        # A quarter turn is the slot along the other axis.
        across = copy.deepcopy(plain)
        across["along"]["choose"] = "y"
        self.assertFalse(self._differ(across, self._turned(90)))
        self.assertTrue(self._differ(plain, self._turned(90)))


if __name__ == "__main__":
    unittest.main()
