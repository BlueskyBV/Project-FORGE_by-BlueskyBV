"""V2: a cut just reaching the end of a round side, where the wall between them is nothing (placement, round sides).

A slot the whole length of a tube's side (a cable clip, split into a C)
was accepted, built, and failed its slot's checks: its ends lay on the
tube's ends, so there was no end wall for them to find. A cut touching a
flat face's edge was already asked about ("the wall between them would be
nothing there"); one touching a round side's end is now too. The brief is
written here, not taken from any blind set.
"""

from __future__ import annotations

import unittest

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


class AtTheEndOfARoundSide(unittest.TestCase):
    def test_a_slot_short_of_the_ends(self) -> None:
        self.assertEqual(clip(20), [])

    def test_a_slot_the_whole_length(self) -> None:
        found = clip(30)
        self.assertEqual([k for k, m in found if "touches the end of tube's side" in m], ["question"], found)


if __name__ == "__main__":
    unittest.main()
