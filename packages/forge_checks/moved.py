"""A solid moved by a rigid motion: the oracle's copies on a turned item's faces, made upright, then moved (place.md,
"A turned item's faces"; V2-stage4b-0c.md 3.3, 1b's third move, step 2).

Each solid the oracle makes has its own frame (or its centre, or a point and a
normal): moving it moves those, and nothing else about it changes.
"""

from __future__ import annotations

from dataclasses import fields, replace

from .csg import Inter, Minus, Node, Union
from .place import Motion
from .shapes import Ball, Complement, Frame, Halfspace

__all__ = ["moved_frame", "moved_node"]


def moved_frame(frame: Frame, motion: Motion) -> Frame:
    return Frame(motion.point(frame.origin), motion.vector(frame.u), motion.vector(frame.v), motion.vector(frame.w))


def moved_node(node: Node, motion: Motion) -> Node:
    """``node`` moved by ``motion``."""
    if isinstance(node, Union):
        return Union(tuple(moved_node(p, motion) for p in node.parts))
    if isinstance(node, Inter):
        return Inter(tuple(moved_node(p, motion) for p in node.parts))
    if isinstance(node, Minus):
        return Minus(moved_node(node.whole, motion), moved_node(node.less, motion))
    if isinstance(node, Complement):
        return Complement(moved_node(node.of, motion))  # type: ignore[arg-type]
    if isinstance(node, Ball):
        return replace(node, centre=motion.point(node.centre))
    if isinstance(node, Halfspace):
        return replace(node, point=motion.point(node.point), normal=motion.vector(node.normal))
    if any(f.name == "frame" for f in fields(node)):
        return replace(node, frame=moved_frame(node.frame, motion))  # type: ignore[call-arg, attr-defined]
    raise TypeError(f"the oracle doesn't move a {type(node).__name__} yet")
