"""V2: cuts that only just touch a face, where the wall between them is nothing (placement).

A slot the whole length of a tube's side (a cable clip, split into a C)
was accepted, built, and failed its slot's checks: its ends lay on the
tube's ends, so there was no end wall for them to find. A cut touching a
flat face's edge was already asked about ("the wall between them would be
nothing there"); one touching a round side's end is now too.

A set screw's hole into a collar's wall, as deep as the wall, was
accepted, built and held: its flat floor met the bore along a line, the
part's surface pinched there. A blind cut as deep as the least material
under it, where the far side curves or slopes away under the rest of its
mouth, only touches it: asked about, as one deeper is. As deep as a flat
far side, it comes out across it, as a through cut does: not asked.
The briefs are written here, not taken from any blind set.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from v2_drafts import assumed, cite, draft, mm

CLIP = ("A cable clip: a tube 20 mm across outside and 16 mm inside, 30 mm long, with a slot 6 mm wide and {} mm long "
        "through its side along its length, in the middle of it.")  # fmt: skip


def clip(length: int) -> list[tuple[str, str]]:
    brief = CLIP.format(length)
    b = number_words(brief)
    report = check_draft(b, draft("clip", [
        {"id": "tube", "kind": "tube", "words": cite(b, "tube"), "axis": {"choose": "z", "from": assumed("up")},
         "outer_diameter": mm(b, 20, "20 mm across"), "inner_diameter": mm(b, 16, "16 mm inside"),
         "length": mm(b, 30, "30 mm long")},
        {"id": "gap", "kind": "slot", "words": cite(b, "slot"), "on": {"item": "tube", "face": "side"},
         "width": mm(b, 6, "6 mm wide"), "length": mm(b, length, f"{length} mm long", 2 if length == 30 else 1),
         "along": {"choose": "z", "from": {"words": cite(b, "along its length")}},
         "ends": {"choose": "round", "from": {"assumed": "a slot's ends are round"}},
         "depth": {"through": True, "from": {"words": cite(b, "through its side")}},
         "place": {"z": {"centred": {"words": cite(b, "in the middle of it")}},
                   "angle": {"value": 0, "unit": "deg", "from": {"assumed": "facing +x"}}}},
    ]))  # fmt: skip
    return [(p.kind, p.message) for p in report.problems]


COLLAR = "A collar 25 mm across and 15 mm long, with a 12 mm bore, and a 4 mm set screw hole into its wall."
ROD = "A collar 25 mm across and 15 mm long, solid, with a 4 mm set screw hole into its wall."


def collar(depth: Any, kind: str = "tube") -> list[tuple[str, str]]:
    b = number_words(COLLAR if kind == "tube" else ROD)
    body = {"id": "collar", "kind": kind, "words": cite(b, "collar"), "axis": {"choose": "z", "from": assumed("up")},
            "length": mm(b, 15, "15 mm long")}  # fmt: skip
    if kind == "tube":
        body.update(outer_diameter=mm(b, 25, "25 mm across"), inner_diameter=mm(b, 12, "12 mm bore"))
    else:
        body["diameter"] = mm(b, 25, "25 mm across")
    report = check_draft(b, draft("collar", [body, {
        "id": "screw", "kind": "hole", "words": cite(b, "set screw hole"), "on": {"item": "collar", "face": "side"},
        "diameter": mm(b, 4, "4 mm"), "depth": depth,
        "place": {"z": {"centred": {"assumed": "halfway along it"}},
                  "angle": {"value": 0, "unit": "deg", "from": {"assumed": "facing +x"}}}}]))  # fmt: skip
    return [(p.kind, p.message) for p in report.problems]


def plate(depth: float, tilt: float | None = None) -> list[tuple[str, str]]:
    b = number_words("A plate 10 mm thick with a 4 mm hole in its top.")
    hole: dict[str, Any] = {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "plate", "face": "+z"},
                            "diameter": mm(b, 4, "4 mm"), "depth": assumed("deep", depth)}  # fmt: skip
    if tilt is not None:
        hole.update(tilt={"value": tilt, "unit": "deg", "from": assumed("leaning")},
                    tilt_towards={"choose": "+x", "from": assumed("that way")})
    report = check_draft(b, draft("plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": assumed("long", 60.0),
         "width": assumed("wide", 40.0), "height": mm(b, 10, "10 mm thick")}, hole]))  # fmt: skip
    return [(p.kind, p.message) for p in report.problems]


TOUCHING = "its floor just touching the far side"


class AFloorJustTouchingTheFarSide(unittest.TestCase):
    def test_into_a_collars_bore(self) -> None:
        found = collar({"value": 6.5, "unit": "mm", "from": {"assumed": "the wall"}})
        self.assertEqual([k for k, m in found if TOUCHING in m], ["fault"], found)  # its depth assumed: the writer's
        b = number_words(COLLAR)
        self.assertEqual(collar({"value": 6.4, "unit": "mm", "from": {"assumed": "short of the bore"}}), [])
        self.assertEqual(collar({"through_next": True, "from": {"words": cite(b, "into its wall")}}), [])

    def test_into_a_rod(self) -> None:
        least = 12.5 + math.sqrt(12.5**2 - 2**2)  # the far side comes first at its edge
        found = collar({"value": least, "unit": "mm", "from": {"assumed": "deep"}}, "cylinder")
        self.assertEqual([k for k, m in found if TOUCHING in m], ["fault"], found)
        self.assertEqual(collar({"value": 20.0, "unit": "mm", "from": {"assumed": "deep"}}, "cylinder"), [])

    def test_leaning_into_a_plate(self) -> None:
        least = (10 - 2 * 0.5) / math.cos(math.radians(30))  # its floor comes down to the far side at its low edge
        found = plate(least, 30.0)
        self.assertEqual([k for k, m in found if TOUCHING in m], ["fault"], found)
        self.assertEqual(plate(9.0, 30.0), [])

    def test_as_deep_as_a_flat_far_side_comes_out_across_it(self) -> None:
        self.assertEqual(plate(10.0), [])


class AtTheEndOfARoundSide(unittest.TestCase):
    def test_a_slot_short_of_the_ends(self) -> None:
        self.assertEqual(clip(20), [])

    def test_a_slot_the_whole_length(self) -> None:
        found = clip(30)
        self.assertEqual([k for k, m in found if "touches the end of tube's side" in m], ["question"], found)


if __name__ == "__main__":
    unittest.main()
