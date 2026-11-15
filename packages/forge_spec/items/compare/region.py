"""What the two-draft comparison reads of a region: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, Text
from forge_spec.items.compare._common import Feature, _length, _mid, _r, _sub
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance


class Region(CompareKind):
    key = "region"

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        describe = item.get("describe")
        wall = _length(item, "min_wall")
        return [Feature(n, item.id, kind, "region", sizes, centre,
                        (describe.text if isinstance(describe, Text) else None,
                         None if wall is None else _r(wall)))]  # fmt: skip


ENTRY = Region()
