"""What the spec checks read of a tube: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, PartSpec
from forge_spec.items.checks._common import Collect, size_of
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout, mm
from forge_spec.values import Value


class Tube(SpecCheckKind):
    key = "tube"

    def physical(
        self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect
    ) -> None:
        outer, inner = item.get("outer_diameter"), item.get("inner_diameter")
        if (
            isinstance(outer, Value)
            and isinstance(inner, Value)
            and mm(inner) >= mm(outer)
        ):
            c.problem("cant", at, f"the bore ({mm(inner):g} mm) is not smaller than the tube "
                      f"({mm(outer):g} mm)", outer, inner)  # fmt: skip

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        def s(name: str) -> float | None:
            return size_of(target, name)

        outer, inner, length = s("outer_diameter"), s("inner_diameter"), s("length")
        if outer is None or inner is None or length is None:
            return None
        wall = (outer - inner) / 2
        return {"top": min(wall / 2, length), "bottom": min(wall / 2, length), "both": min(wall / 2, length / 2),
                "outer": min(wall, length / 2), "bore": min(wall, length / 2)}.get(which)  # fmt: skip


ENTRY = Tube()
