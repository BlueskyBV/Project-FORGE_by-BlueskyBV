"""An outside thread, as the plan writes it: one ``thread`` step for each copy of the rod it threads (docs/V2-stage4.md, 7.2).

thread.md: the rod's round side, over ``length`` from its free end (the
whole rod when no length is given), cut into the ISO 68-1 basic profile; its
major diameter the rod's, its pitch the designation's (the one it names, or
the size's coarse pitch), wound as ``hand`` says. The step takes the part
and gives it back threaded; the rod is given by its axis (from the copy's
base along the way it grows), where it starts (0) and where it ends (its
length, or a boss's height). The groove's box, the ring round the threaded
length out to the major radius and a little past, is noted for the search,
as a tool's is.
"""

from __future__ import annotations

import math

from forge_spec.draft import Choice, Item, Text
from forge_spec.placement import Instance
from forge_spec.tables import TAPPED, metric_size
from forge_spec.values import Value

from .errors import PlanError
from .items.plan import PLAN
from .tools import Context
from .write import Box, Chain, add, direction, length, point

__all__ = ["thread_step"]


def thread_step(chain: Chain, ctx: Context, item: Item, copy: Instance) -> None:
    """Write the thread on one copy of its rod: the part made so far, threaded."""
    designation, hand, threaded = (
        item.get("designation"),
        item.get("hand"),
        item.get("length"),
    )
    target = ctx.items.get(str(item.get("of")))
    if target is None or not PLAN[target.kind].threadable:
        raise PlanError("a thread goes on a cylinder or a boss", item=item.id)
    size = metric_size(designation.text) if isinstance(designation, Text) else None
    if size is None:
        raise PlanError("a thread is named by a metric designation", item=item.id)
    pitch = size[1] if size[1] is not None else TAPPED[size[0]][0]
    diameter, whole = (
        target.get("diameter"),
        target.get(PLAN[target.kind].rod_length),
    )
    if not (isinstance(diameter, Value) and isinstance(whole, Value)):
        raise PlanError(
            f"{target.id} has no diameter and length to thread", item=item.id
        )
    radius, rod = diameter.made_in("mm") / 2.0, whole.made_in("mm")
    long = threaded.made_in("mm") if isinstance(threaded, Value) else rod
    if chain.head is None:
        raise PlanError("a thread before any body", item=item.id)
    o, u = copy.origin, copy.direction or copy.normal  # a leaning rod along its lean (step 5.4)
    chain.head = chain.step(
        f"{item.id}.{copy.index}.thread",
        "thread",
        {"axis_origin": point(o), "axis": direction(u), "major_diameter": length(2.0 * radius),
         "pitch": length(pitch), "hand": hand.value if isinstance(hand, Choice) else "right",
         "length": length(long), "rod_start": length(0.0), "rod_end": length(rod)},
        item=item.id,
        inputs=(chain.head,),
    )  # fmt: skip
    # The groove's box: the ring round the threaded length, out past the major radius by a tenth of the pitch.
    reach = radius + pitch / 10.0
    spread = [reach * math.sqrt(max(1.0 - c * c, 0.0)) for c in u]
    ends = (add(o, u, rod - long), add(o, u, rod))
    lo = [min(e[k] for e in ends) - spread[k] for k in range(3)]
    hi = [max(e[k] for e in ends) + spread[k] for k in range(3)]
    chain.cut_box(
        Box((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]), item.id, copy.index)
    )
