"""A solid moved by a rigid motion: the oracle's copies on a turned item's faces, made upright, then moved (place.md,
"A turned item's faces"; V2-stage4b-0c.md 3.3, 1b's third move, step 2); and a turned item's edges, found as with it
upright, then moved (edges.md, "A turned item's edges"; step 2c).

Each solid the oracle makes has its own frame (or its centre, or a point and a
normal): moving it moves those, and nothing else about it changes; so does an
edge, its section's boundaries in its own frame.
"""

from __future__ import annotations

from dataclasses import fields, replace

from . import rounds
from .csg import Inter, Minus, Node, Union
from .place import Copy, Motion, unit
from .shapes import Ball, Complement, Frame, Halfspace

__all__ = ["moved_chain", "moved_frame", "moved_node", "upright"]


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


def moved_chain(chain: rounds.Chain, motion: Motion) -> rounds.Chain:
    """``chain``'s edges moved by ``motion``, each section's boundaries as they are in its own frame."""
    edges: list[rounds.Edge] = []
    for edge in chain.edges:
        if isinstance(edge, rounds.StraightEdge):
            edges.append(replace(edge, origin=motion.point(edge.origin), along=motion.vector(edge.along),
                                 u=motion.vector(edge.u), v=motion.vector(edge.v)))  # fmt: skip
        else:
            edges.append(replace(edge, centre=motion.point(edge.centre), axis=motion.vector(edge.axis),
                                 u=motion.vector(edge.u), v=motion.vector(edge.v)))  # fmt: skip
    return replace(chain, edges=tuple(edges))


def upright(copy: Copy) -> tuple[Copy, Motion | None]:
    """A copy as it is placed upright and unturned, and the motion that takes it onto the part (None: none does): its
    turn in its face, about the line through its point square to it from the face's first axis towards its second,
    then the motion of the item whose face it is on."""
    base = copy.local if copy.local is not None else copy
    motion = None
    if base.turn is not None:
        assert base.axes is not None
        first, second = unit("+" + base.axes[0]), unit("+" + base.axes[1])
        square = (first[1] * second[2] - first[2] * second[1], first[2] * second[0] - first[0] * second[2],
                  first[0] * second[1] - first[1] * second[0])  # fmt: skip
        motion = Motion.about(base.point, square, base.turn)
        base = replace(base, turn=None)
    if copy.frame is not None:
        motion = copy.frame if motion is None else copy.frame.after(motion)
    return base, motion
