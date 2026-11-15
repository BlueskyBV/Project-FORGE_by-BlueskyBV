"""What the two-draft comparison reads of a post: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.compare._common import Feature, _mid, _sub
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance


class Post(CompareKind):
    key = "post"

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        return [Feature(n, item.id, kind, "box", sizes, centre)]


ENTRY = Post()
