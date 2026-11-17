"""What stands on, or is cut into, a turned item's faces: built upright, then moved (V2-stage4b-0c.md 3.3, 1b's third
move, step 2).

The solver places such a copy as on that item's face with the item upright
(``Instance.local``) and keeps the motion that takes it onto the part
(``Instance.frame``). Its tools are made from that upright copy as any other
copy's are, each then moved by a ``transform`` (ForgeIR v2's rigid motion,
which keeps the names of a tool's faces on the moved faces); the boxes its
tools take up are moved with them (the box round each, moved), and a face
named by the way it faces is named by the way it faces moved. It is made as
its definition makes it: not carried into the air (5.2) nor sunk (5.3), which
are proven on the part's own boxes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from forge_numeric import scalar as fs
from forge_spec.draft import Item
from forge_spec.frames import Rigid
from forge_spec.placement import Instance

from .items.plan import PLAN
from .tools import Context
from .write import Box, Chain, Ref, direction, num, point

__all__ = ["moved_tools", "moved_where", "transform_params"]

Vec = tuple[float, float, float]


def moved_tools(chain: Chain, ctx: Context, item: Item, copy: Instance, how: str = "flush") -> list[str]:
    """One copy's tool pieces, made upright ``how`` its construction makes them (carried into the air where that is
    proven clear where it is moved to: tools.carried_ways), and moved onto the part by its motion."""
    assert copy.frame is not None and copy.local is not None
    motion, upright = copy.frame, copy.local
    marks = len(chain.added), len(chain.cut), len(chain.boxes.get(chain.planning, []))
    tools = PLAN[item.kind].tool(chain, ctx, item, upright, how)
    key = (item.id, copy.index)
    own = next((b for b in (*chain.added[marks[0]:], *chain.cut[marks[1]:]) if (b.item, b.copy) == key), None)
    moved = [chain.step(f"{tool}.moved", "transform", transform_params(motion), item=item.id, inputs=(tool,))
             for tool in tools]  # fmt: skip
    for found, mark in ((chain.added, marks[0]), (chain.cut, marks[1]), (chain.boxes.setdefault(chain.planning, []), marks[2])):
        found[mark:] = [_moved_box(box, motion) for box in found[mark:]]
    for face, refs in list(chain.faces.get(key, {}).items()):
        chain.faces[key][face] = tuple(sorted({_moved_ref(ref, motion) for ref in refs}))
    # Its edges are found as it stands upright (and unturned, where it is turned there too), then moved: on the box
    # round it so (a cut's, the box its tool takes up).
    standing = (upright.lo, upright.hi) if own is None else (own.lo, own.hi)
    lo, hi, first = chain.motions.get(key, (*standing, None))
    chain.motions[key] = (lo, hi, motion if first is None else motion.after(first))
    return moved


def transform_params(motion: Rigid) -> dict[str, object]:
    """A ``transform``'s parameters for a rigid motion: its turn as an axis and an angle about the part's origin,
    then its shift."""
    r = motion.rows
    twice_sin = (r[2][1] - r[1][2], r[0][2] - r[2][0], r[1][0] - r[0][1])
    sin = fs.hypot(fs.hypot(twice_sin[0], twice_sin[1]), twice_sin[2]) / 2.0
    cos = (r[0][0] + r[1][1] + r[2][2] - 1.0) / 2.0
    found: dict[str, object] = {"translate": point(motion.shift)}
    if sin > 1e-12:
        axis = tuple(c / (2.0 * sin) for c in twice_sin)
    elif cos > 0.0:
        return found  # no turn
    else:  # half a turn: its axis from the diagonal, signed by the largest component's row
        k = max(range(3), key=lambda i: r[i][i])
        big = math.sqrt(max((r[k][k] + 1.0) / 2.0, 0.0))
        axis = tuple(big if i == k else (r[i][k] + r[k][i]) / (4.0 * big) for i in range(3))
    angle = math.degrees(fs.atan2(sin, cos))
    found.update({"rotate_axis": direction(axis), "rotate_angle": {"magnitude": num(angle), "unit": "deg"},
                  "rotate_origin": point((0.0, 0.0, 0.0))})  # fmt: skip
    return found


def moved_where(where: Mapping[str, Any], motion: Rigid) -> dict[str, Any]:
    """An edge query's ``where`` (a line or a circle, and the box it lies within) moved by ``motion``: the box round the
    moved box, its corners moved."""
    found = dict(where)
    if "axis" in where:
        found["axis"] = _listed(motion.vector(tuple(where["axis"])))
    for name in ("through", "centre"):
        if name in where:
            found[name] = _listed(motion.point(tuple(where[name])))
    lo, hi = where["within"]
    moved_lo, moved_hi = motion.box(tuple(lo), tuple(hi))
    found["within"] = [_listed(moved_lo), _listed(moved_hi)]
    return found


def _listed(v: Vec) -> list[float]:
    return [num(c) for c in v]


def _moved_box(box: Box, motion: Rigid) -> Box:
    lo, hi = motion.box(tuple(box.lo), tuple(box.hi))  # type: ignore[arg-type]
    return Box(lo, hi, box.item, box.copy)


def _moved_ref(ref: Ref, motion: Rigid) -> Ref:
    if not ref.normal:
        return ref
    return Ref(ref.step, ref.role, motion.vector(ref.normal))
