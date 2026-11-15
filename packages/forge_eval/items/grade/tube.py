"""What spec grading reads for a tube: its entry in the ``grade`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
tube's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Sequence

from forge_spec.draft import Item
from forge_spec.placement import Instance, mm
from forge_spec.schema import KINDS, Category
from forge_spec.values import Value

from forge_eval.items.grade.protocol import GradeKind
from forge_eval.spec_grade import _add_run, _axis, _face, _on


class Tube(GradeKind):
    key = "tube"
    bored = True

    def bore_runs(self, item: Item, items: Sequence[Item], copies: Sequence[Instance],
                  runs: dict[tuple[int, float, float], list[tuple[float, float, float]]]) -> str | None:  # fmt: skip
        # Its bore is a through hole only with both ends open: standing on
        # nothing, with nothing standing on either end.
        ends = [x.id for x in items if _on(x) == item.id and _face(x) != "side"
                and KINDS[x.kind].category in (Category.BODY, Category.ADD)]  # fmt: skip
        inner = item.get("inner_diameter")
        if _on(item) or ends:
            return (
                f"{item.id}'s bore may be closed at an end: checked on the built part"
            )
        if isinstance(inner, Value):
            for copy in copies:
                if copy.lo is not None and copy.hi is not None:
                    k = _axis(copy)
                    _add_run(runs, copy, k, copy.lo[k], copy.hi[k], mm(inner))
        return None


ENTRY = Tube()
