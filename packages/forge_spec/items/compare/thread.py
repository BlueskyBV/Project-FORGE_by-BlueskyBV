"""What the two-draft comparison reads of a thread: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Designation, Item
from forge_spec.items.compare._common import Feature, _choice, _length, _mid, _r, _up
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Layout


class Thread(CompareKind):
    key = "thread"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        """A thread by its rod."""
        kind = item.kind
        of = item.get("of")
        if not isinstance(of, str):  # pragma: no cover - a checked draft names its body
            return []
        found: list[Feature] = []
        for copy in layout.instances.get(of, ()):
            if copy.lo is None or copy.hi is None:
                continue
            designation = item.get("designation")
            length = _length(item, "length")
            rod = max(copy.hi[k] - copy.lo[k] for k in range(3) if k != _up(copy))
            found.append(Feature(n, item.id, kind, "thread", None, _mid(copy.lo, copy.hi),
                                 (designation.text if isinstance(designation, Designation) else None,
                                  _choice(item, "hand"), None if length is None else _r(length), _r(rod)),
                                 ((copy.normal, False),), field="designation", of=of))  # fmt: skip
        return found


ENTRY = Thread()
