"""Patterns, mirrors and moves, by exact rigid motions (docs/V2-stage3.md, 7.2).

- ``pattern_linear``: ``count`` copies ``spacing`` apart; ``symmetric`` first
  moves the source back by half the pattern's length, as V1;
- ``pattern_circular``: ``count`` copies about the axis, by ``step_angle``
  (the angle between neighbours) or ``total_angle`` (a full circle divided
  by the count, an arc by the gaps), never both;
- ``mirror``: the reflection in the plane, with the original kept or not (if
  not, the image carries the original's names);
- ``transform``: rotate about ``rotate_origin``, then translate.

Every copy carries the source's names with its own copy number, so V1's
names (copy 0) still mean the original.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from ..errors import AfterCheckError, DesignError
from ..geom import Motion, rotation_about, unit
from ..make import boolean, one_solid, unify
from ..names import Name, Names, carry
from ..occt import vertices
from ..products import Context, Product, SolidProduct

__all__ = ["BUILDERS", "moved"]


#: How exactly a copy's vertex must land where its motion takes the original's (mm, relative to its distance from the origin).
PLACED = 1e-9


def moved(
    product: SolidProduct, motion: Motion, *, copy_offset: int = 0
) -> SolidProduct:
    """``product`` moved (a copy), its names on the moved faces, their copy numbers shifted by ``copy_offset``.

    The copy's motion is checked on a point of it (section 8.2): its first
    vertex is where the motion takes the original's.
    """
    shape = motion.apply(product.shape)
    _check_placed(product.shape, shape, motion)
    names = Names(shape, product.names.table)
    if copy_offset:
        names = Names(shape, tuple(
            frozenset(Name(n.step, n.role, n.copy + copy_offset) for n in held)
            for held in names.table))  # fmt: skip
    return SolidProduct(shape, names)


def _check_placed(original: Any, copy: Any, motion: Motion) -> None:
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS

    before, after = vertices(original), vertices(copy)
    if len(before) != len(after):
        raise AfterCheckError("the operation did not do what it should: a copy has other vertices than its original",
                              original=len(before), copy=len(after))  # fmt: skip
    if not before:
        return
    p, q = (BRep_Tool.Pnt_s(TopoDS.Vertex(v[0])) for v in (before, after))
    want = motion.point((p.X(), p.Y(), p.Z()))
    found = np.array([q.X(), q.Y(), q.Z()])
    if float(np.linalg.norm(found - want)) > PLACED * (
        1.0 + float(np.linalg.norm(want))
    ):
        raise AfterCheckError("the operation did not do what it should: a copy is not where its motion puts it",
                              expected=[round(float(c), 9) for c in want], found=[round(float(c), 9) for c in found])  # fmt: skip


def _stride(product: SolidProduct) -> int:
    return 1 + max((n.copy for n in product.names.every()), default=0)


def _union_of(step: str, pieces: Sequence[SolidProduct]) -> SolidProduct:
    if len(pieces) == 1:
        return pieces[0]
    done = boolean("union", [pieces[0].shape], [p.shape for p in pieces[1:]])
    carried = carry(
        [p.names for p in pieces],
        done.shape,
        done.history,
        fallback=(Name(step, "other"),),
    )
    merged = unify(done.shape)
    again = carry(
        [carried.names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    solid = one_solid(merged.shape)
    return SolidProduct(solid, again.names.on(solid), lost=carried.lost | again.lost)


def _pattern_linear(ctx: Context) -> Product:
    count = ctx.count("count")
    if count < 1:
        raise ctx.fail(DesignError("a pattern has one copy at least", count=count))
    spacing = np.asarray(ctx.vector("spacing"), dtype=np.float64)
    source = ctx.solid(0)
    if ctx.flag("symmetric", False):
        source = moved(source, Motion.of(np.eye(3), -spacing * (count - 1) / 2.0))
    stride = _stride(source)
    copies = [source] + [
        moved(source, Motion.of(np.eye(3), spacing * i), copy_offset=i * stride)
        for i in range(1, count)
    ]
    return _union_of(ctx.step, copies)


def _pattern_circular(ctx: Context) -> Product:
    count = ctx.count("count")
    if count < 1:
        raise ctx.fail(DesignError("a pattern has one copy at least", count=count))
    origin = np.asarray(ctx.vector("axis_origin"), dtype=np.float64)
    try:
        axis = unit(ctx.vector("axis_direction"), "a circular pattern's axis")
    except DesignError as error:
        raise ctx.fail(error) from error
    step_angle = ctx.params.get("step_angle")
    total_given = ctx.params.get("total_angle")
    if step_angle is not None and total_given is not None:
        raise ctx.fail(DesignError("a circular pattern is placed by `step_angle` or by `total_angle`, not by both",
                                   step_angle=float(step_angle), total_angle=float(total_given)))  # fmt: skip
    if step_angle is not None:
        angles = [float(step_angle) * i for i in range(1, count)]
    else:
        total = ctx.angle("total_angle", 2.0 * math.pi)
        divisor = count if total >= 2.0 * math.pi - 1e-9 else max(count - 1, 1)
        angles = [total * i / divisor for i in range(1, count)]
    source = ctx.solid(0)
    stride = _stride(source)
    copies = [source]
    for i, angle in enumerate(angles, start=1):
        rotation = rotation_about(axis, angle)
        copies.append(
            moved(
                source,
                Motion.of(rotation, origin - rotation @ origin),
                copy_offset=i * stride,
            )
        )
    return _union_of(ctx.step, copies)


def _mirror(ctx: Context) -> Product:
    point = np.asarray(ctx.vector("plane_origin", (0.0, 0.0, 0.0)), dtype=np.float64)
    try:
        n = unit(ctx.vector("plane_normal"), "a mirror plane's normal")
    except DesignError as error:
        raise ctx.fail(error) from error
    reflection = np.eye(3) - 2.0 * np.outer(n, n)
    motion = Motion.of(reflection, 2.0 * float(point @ n) * n)
    source = ctx.solid(0)
    if not ctx.flag("keep_original", True):
        return moved(source, motion)
    image = moved(source, motion, copy_offset=_stride(source))
    return _union_of(ctx.step, [source, image])


def _transform(ctx: Context) -> Product:
    translate = np.asarray(ctx.vector("translate", (0.0, 0.0, 0.0)), dtype=np.float64)
    angle = ctx.angle("rotate_angle", 0.0)
    if angle != 0.0:
        try:
            axis = unit(ctx.vector("rotate_axis", (0.0, 0.0, 1.0)), "a rotation's axis")
        except DesignError as error:
            raise ctx.fail(error) from error
        rotation = rotation_about(axis, angle)
        pivot = np.asarray(
            ctx.vector("rotate_origin", (0.0, 0.0, 0.0)), dtype=np.float64
        )
        translation = pivot - rotation @ pivot + translate
    else:
        rotation, translation = np.eye(3), translate
    return moved(ctx.solid(0), Motion.of(rotation, translation))


BUILDERS: Mapping[str, Callable[[Context], Product]] = {
    "pattern_linear": _pattern_linear,
    "pattern_circular": _pattern_circular,
    "mirror": _mirror,
    "transform": _transform,
}
