"""Datums and profiles: frames and outlines, as V1 makes them (docs/V2-stage3.md, 7.2)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..errors import DesignError, OperationError
from ..geom import Frame, unit
from ..products import (
    Context,
    DatumAxis,
    DatumPlane,
    DatumPoint,
    Product,
    ProfileProduct,
)
from ..profiles import green_area, profile_of

__all__ = ["BUILDERS"]


def _datum_plane(ctx: Context) -> Product:
    return DatumPlane(
        Frame.standard(ctx.option("base", "XY"), ctx.length("offset", 0.0))
    )


def _datum_axis(ctx: Context) -> Product:
    direction = unit(ctx.vector("direction"), "an axis's direction")
    origin = ctx.vector("origin")
    return DatumAxis(
        origin, (float(direction[0]), float(direction[1]), float(direction[2]))
    )


def _datum_point(ctx: Context) -> Product:
    return DatumPoint(ctx.vector("position"))


def _profile(ctx: Context) -> Product:
    plane = ctx.plane(0)
    try:
        outline = profile_of(ctx.op, ctx.params)
    except DesignError as error:
        raise ctx.fail(error) from error
    if ctx.op == "profile_outline":
        # Its after-check (docs/V2-stage4.md, 6.5): the face drawn encloses what its sides do.
        expected, made = abs(green_area(outline.outline)), outline.area()
        if abs(made - expected) > 1e-7 * max(expected, 1.0):
            raise ctx.fail(OperationError("an outline's face isn't the area its sides enclose: it crosses itself",
                                          made=made, expected=expected))  # fmt: skip
    return ProfileProduct(outline, plane.frame)


BUILDERS: Mapping[str, Callable[[Context], Product]] = {
    "datum_plane": _datum_plane,
    "datum_axis": _datum_axis,
    "datum_point": _datum_point,
    **dict.fromkeys(
        ("profile_rectangle", "profile_circle", "profile_polygon", "profile_slot",
         "profile_sketch", "profile_gear", "profile_outline"),
        _profile,
    ),
}  # fmt: skip
