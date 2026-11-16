"""A cut's end condition (forge_spec.ends; 4b.0c item 2a; V2-stage4b-0c.md, 3.5).

- **Today's two ends are read from a cut's depth:** a length is blind to
  it, ``{"through": true}`` is through all the material under its mouth,
  and what has no depth has no end.
"""

from __future__ import annotations

import unittest

from forge_spec.checks import check_draft
from forge_spec.ends import Blind, ThroughAll, end_of
from forge_spec.words import number_words

BRIEF = number_words(
    "A plate 80 mm long, 50 mm wide and 5 mm thick, with a 6 mm hole through its middle and a 3 mm deep one."
)


def _v(x: float, words: list[int]) -> dict[str, object]:
    return {"value": x, "unit": "mm", "from": {"words": words}}


DRAFT = {
    "schema_version": "1.1",
    "name": "plate",
    "items": [
        {"id": "plate", "kind": "block", "words": [0, 1], "length": _v(80, [2, 3]),
         "width": _v(50, [5, 6]), "height": _v(5, [9, 10])},
        {"id": "through", "kind": "hole", "words": [16], "on": {"item": "plate", "face": "+z"},
         "diameter": _v(6, [14, 15]), "depth": {"through": True, "from": {"words": [17]}}},
        {"id": "blind", "kind": "hole", "words": [22], "on": {"item": "plate", "face": "-z"},
         "diameter": _v(6, [14, 15]), "depth": _v(3, [20, 21])},
    ],
}  # fmt: skip


class TodaysTwoEnds(unittest.TestCase):
    def test_read_from_the_depth(self) -> None:
        report = check_draft(BRIEF, DRAFT, strict=False)
        assert report.spec is not None
        plate, through, blind = report.spec.items
        self.assertIsNone(end_of(plate))
        self.assertIsInstance(end_of(through), ThroughAll)
        end = end_of(blind)
        assert isinstance(end, Blind)
        self.assertEqual(end.depth.made_in("mm"), 3.0)


if __name__ == "__main__":
    unittest.main()
