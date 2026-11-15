"""What the spec checks read of a thread: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, PartSpec, Text
from forge_spec.items.checks._common import Collect
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout, mm
from forge_spec.problems import pointer
from forge_spec.tables import TAPPED, metric_size
from forge_spec.values import Value


class Thread(SpecCheckKind):
    key = "thread"

    def physical(
        self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect
    ) -> None:
        from forge_spec.items.checks import SPEC_CHECKS

        designation = item.get("designation")
        size = metric_size(designation.text) if isinstance(designation, Text) else None
        if isinstance(designation, Text) and size is None:
            c.add("unable", at + pointer("designation"),
                  f"Forge knows metric threads (M3, M8x1.25); not {designation.text!r} yet")  # fmt: skip
            return
        of = item.get("of")
        target = spec.item(of) if isinstance(of, str) else None
        if target is None or not SPEC_CHECKS[target.kind].threadable:
            what = (
                f"{of!r} is a {target.kind}"
                if target is not None
                else f"there is no item {of!r}"
            )
            c.fault(
                at + pointer("of"), f"a thread goes on a cylinder or a boss; {what}"
            )
            return
        assert size is not None
        if size[1] is None and size[0] not in TAPPED:
            c.add("unable", at + pointer("designation"),
                  f"Forge knows the coarse pitches of {', '.join(TAPPED)}; an {size[0]} "
                  f"needs its pitch named ({size[0]}x...)")  # fmt: skip
            return
        nominal = float(size[0][1:])
        diameter = target.get("diameter")
        if isinstance(diameter, Value) and abs(mm(diameter) - nominal) > max(
            0.3, 0.05 * nominal
        ):
            c.problem("question", at + pointer("designation"),
                      f"an {size[0]} thread is {nominal:g} mm across; {target.id} is {mm(diameter):g} mm",
                      diameter, designation)  # fmt: skip
        length = item.get("length")
        room = target.get("length") or target.get("height")
        if (
            isinstance(length, Value)
            and isinstance(room, Value)
            and mm(length) > mm(room) + 1e-9
        ):
            c.problem("cant", at + pointer("length"),
                      f"a {mm(length):g} mm thread is longer than {target.id} ({mm(room):g} mm)", length, room)  # fmt: skip


ENTRY = Thread()
