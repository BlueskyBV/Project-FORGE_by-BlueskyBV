"""A line of letters, as the plan writes it: one ``text`` step a copy, on the part made so far (docs/V2-stage4.md, 7.1).

text.md: the letters in the pinned font, a capital ``height`` tall, their
line's box centred where the layout put the copy, up the face's second axis
and running along up cross outward, so they read the right way round from
outside the face; cut in to ``depth`` (engraved) or standing out by it
(embossed). The step takes the part and gives it back with the letters; its
box (the ink's box, to its depth) is noted for the search, as a tool's is.
"""

from __future__ import annotations

from forge_spec.draft import Choice, Item, Text
from forge_spec.font import text_width
from forge_spec.geometry import FlatFace
from forge_spec.letters import ink_box
from forge_spec.placement import Instance, mm
from forge_spec.values import Value

from .errors import PlanError
from .tools import Context
from .write import Box, Chain, Vec, add, direction, length, point, scale, unit

__all__ = ["letters_step"]


def _cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def letters_step(chain: Chain, ctx: Context, item: Item, copy: Instance) -> None:
    """Write one copy's ``text`` step: the part made so far, with its letters."""
    text, height, depth, mode = (
        item.get("text"),
        item.get("height"),
        item.get("depth"),
        item.get("mode"),
    )
    if not (
        isinstance(text, Text)
        and isinstance(height, Value)
        and isinstance(depth, Value)
    ):
        raise PlanError("letters have their text, a height and a depth", item=item.id)
    engraved = not (isinstance(mode, Choice) and mode.value == "emboss")
    if chain.head is None:
        raise PlanError("letters before any body", item=item.id)
    face = ctx.face(copy)
    if not isinstance(face, FlatFace):
        raise PlanError("letters go on flat faces only, for now", item=item.id)
    up, out = unit(face.axes[1]), copy.normal
    right = _cross(up, out)
    h, d = mm(height), mm(depth)
    step = f"{item.id}.{copy.index}.letters"
    chain.head = chain.step(
        step,
        "text",
        {"text": text.text, "height": length(h), "origin": point(copy.origin), "up": direction(up),
         "right": direction(right), "depth": length(d), "mode": "engrave" if engraved else "emboss"},
        item=item.id,
        inputs=(chain.head,),
    )  # fmt: skip
    ink = ink_box(text.text, h)
    if ink is None:
        return
    (x0, y0), (x1, y1) = ink
    middle = text_width(text.text, h) / 2
    corners = [
        add(add(copy.origin, right, x - middle), up, y - h / 2)
        for x in (x0, x1)
        for y in (y0, y1)
    ]
    reach = scale(out, -d if engraved else d)
    ends = [*corners, *(add(c, reach) for c in corners)]
    lo = (min(p[0] for p in ends), min(p[1] for p in ends), min(p[2] for p in ends))
    hi = (max(p[0] for p in ends), max(p[1] for p in ends), max(p[2] for p in ends))
    box = Box(lo, hi, item.id, copy.index)
    if engraved:
        chain.cut_box(box)
    else:
        chain.add_box(box)
