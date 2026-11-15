"""Shells, offsets, and v2's fillets and chamfers on edges chosen by meaning (docs/V2-stage3.md, 7.2, 9).

- ``shell``: inward, the part minus its inward offset (a sealed hollow, as
  V1); outward, the outward offset minus the part; ``both``, the outward
  half-offset minus the inward one. Never ``MakeThickSolid`` on its word: it
  can return the part unchanged and call it done (section 4). The new wall's
  faces are named ``inner`` and nothing else.
- ``offset``: the true offset, joins as arcs (what V1's field minus a
  distance is), each face keeping its name, the arcs named ``round``.
- ``fillet``, ``chamfer``: the edges an edge reference resolves to (closed
  under tangency, as OpenCascade rounds them anyway), rounded by one radius
  or cut by one distance.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from OCP.BRepOffset import BRepOffset_Skin
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.GeomAbs import GeomAbs_Arc

from ..aftercheck import blend_bounds, check_distance, points_on
from ..errors import AfterCheckError, DesignError, OccError, OperationError
from ..make import boolean, one_solid, round_edges, unify
from ..names import History, Name, carry, named_by
from ..occt import boundary, is_valid, solids, volume
from ..products import Context, Product, SolidProduct

__all__ = ["BUILDERS", "WALL", "offset_shape"]

#: How exactly a shell's wall or an offset's distance must come out (mm).
WALL = 1e-4


def offset_shape(shape: Any, distance: float) -> tuple[Any, History, str]:
    """The true offset of ``shape`` by ``distance`` (out positive), arcs at the joins; and how it was made.

    OpenCascade's offset by joins is tried first; where it fails (it often does
    on B-spline faces, such as a ruled loft's), its simple offset, which offsets
    each face and joins them where they meet. Either way the caller measures
    the result (the wall is at the distance everywhere, section 8.2): the simple
    offset is exact only where faces meet at convex edges, and the measurement
    is what says so.
    """
    attempts = []
    for how in ("by joins", "simple"):
        maker = BRepOffsetAPI_MakeOffsetShape()
        try:
            with boundary("an offset", distance=distance):
                if how == "by joins":
                    maker.PerformByJoin(
                        shape,
                        distance,
                        1e-7,
                        BRepOffset_Skin,
                        False,
                        False,
                        GeomAbs_Arc,
                    )
                else:
                    maker.PerformBySimple(shape, distance)
        except OccError as error:
            attempts.append(f"{how}: {error.message}")
            continue
        if not maker.IsDone():
            attempts.append(f"{how}: not done ({_offset_error(maker)})")
            continue
        result = maker.Shape()
        if result.IsNull() or not solids(result) or not is_valid(result):
            attempts.append(f"{how}: no valid solid")
            continue
        return (
            one_solid(result),
            History(maker),
            how if not attempts else f"{how} ({'; '.join(attempts)})",
        )
    raise OperationError(
        "OpenCascade could not offset the part", distance=distance, tried=attempts
    )


def _offset_error(maker: Any) -> str:
    """What OpenCascade's offset says went wrong, in its own words (``BRepOffset_MixedConnectivity`` and the like)."""
    try:
        return str(maker.MakeOffset().Error()).split(".")[-1]
    except (
        Exception
    ) as error:  # the reason is for the trace only; reading it must never fail the step
        return type(error).__name__


def _shell(ctx: Context) -> Product:
    part = ctx.solid(0)
    thickness = ctx.length("thickness")
    direction = ctx.option("direction", "inward")
    if thickness <= 0.0:
        raise ctx.fail(
            DesignError("a shell's thickness must be positive", thickness=thickness)
        )
    if direction not in ("inward", "outward", "both"):
        raise ctx.fail(
            DesignError("a shell is inward, outward or both", direction=direction)
        )
    step = ctx.step
    try:
        if direction == "inward":
            outer, inner = part, _named_offset(step, part, -thickness, "inner")
        elif direction == "outward":
            outer, inner = _named_offset(step, part, thickness, "inner"), part
        else:
            outer = _named_offset(step, part, thickness / 2.0, "inner")
            inner = _named_offset(step, part, -thickness / 2.0, "inner")
    except OccError as error:
        raise ctx.fail(DesignError(
            f"a {thickness:g} mm wall doesn't fit in this part ({error.message})",
            thickness=thickness, direction=direction)) from error  # fmt: skip
    # The wall: every new face is the thickness (or half of it) from the part's own surface.
    gap = thickness if direction != "both" else thickness / 2.0
    for new in (outer, inner):
        if new is not part:
            try:
                check_distance(points_on(new.shape), part.shape, gap, WALL,
                               f"a shell's wall is {gap:g} mm from the part's surface")  # fmt: skip
            except AfterCheckError as error:
                raise ctx.fail(
                    error.where(offset=list(new.notes) or ["made by joins"])
                ) from None
    done = boolean("subtract", [outer.shape], [inner.shape])
    carried = carry(
        [outer.names, inner.names],
        done.shape,
        done.history,
        fallback=(Name(step, "other"),),
    )
    merged = unify(done.shape)
    again = carry(
        [carried.names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    solid = one_solid(merged.shape)
    if volume(solid) >= volume(part.shape) and direction == "inward":
        raise AfterCheckError(
            "the operation did not do what it should: an inward shell made no hollow"
        )
    notes = tuple(n for p in (outer, inner) for n in p.notes)
    return SolidProduct(
        solid, again.names.on(solid), lost=carried.lost | again.lost, notes=notes
    )


def _named_offset(
    step: str, part: SolidProduct, distance: float, role: str
) -> SolidProduct:
    shape, _, how = offset_shape(part.shape, distance)
    notes = (
        ()
        if how == "by joins"
        else (f"offset {distance:g} mm made {how}; its wall measured",)
    )
    return SolidProduct(
        shape, named_by(shape, lambda _f: (Name(step, role),)), notes=notes
    )


def _offset(ctx: Context) -> Product:
    part = ctx.solid(0)
    distance = ctx.length("distance")
    if distance == 0.0:
        return part
    try:
        shape, history, how = offset_shape(part.shape, distance)
    except OccError as error:
        raise ctx.fail(error) from error
    carried = carry([part.names], shape, history, lambda _f: (Name(ctx.step, "round"),))
    check_distance(points_on(shape), part.shape, abs(distance), WALL,
                   f"an offset's surface lies {abs(distance):g} mm from the part's")  # fmt: skip
    notes = () if how == "by joins" else (f"offset made {how}; its distance measured",)
    return SolidProduct(shape, carried.names, lost=carried.lost, notes=notes)


def _round(bevel: bool) -> Callable[[Context], Product]:
    def build(ctx: Context) -> Product:
        from ..refs import resolve_reference

        part = ctx.solid(0)
        size = ctx.length("distance" if bevel else "radius")
        if size <= 0.0:
            raise ctx.fail(
                DesignError(
                    f"a {'chamfer' if bevel else 'fillet'} needs a size above zero"
                )
            )
        query = ctx.references["edges"]
        chosen = resolve_reference(part, query, tangent=True)
        try:
            made = round_edges(part.shape, chosen.edges, size, bevel=bevel)
        except OccError as error:
            raise ctx.fail(error) from error
        role = "bevel" if bevel else "round"
        carried = carry(
            [part.names], made.shape, made.history, lambda _f: (Name(ctx.step, role),)
        )
        notes = list(chosen.notes)
        extra = [e for e in made.rounded if not any(e.IsSame(c) for c in chosen.edges)]
        if extra:
            notes.append(f"OpenCascade rounded {len(extra)} edges more, along tangents")
        merged = unify(made.shape)
        again = carry(
            [carried.names],
            merged.shape,
            merged.history,
            fallback=(Name(ctx.step, "other"),),
        )
        solid = one_solid(merged.shape)
        names = again.names.on(solid)
        if not any(Name(ctx.step, role) in held for held in names.table):
            raise ctx.fail(AfterCheckError(
                f"the operation did not do what it should: a {'chamfer' if bevel else 'fillet'} made no face"))  # fmt: skip
        # Volume moved the right way (taken off a ridge, added in a crease), and no further than the blends can.
        before = volume(part.shape)
        removed, added = blend_bounds(part.shape, made.rounded, made.sizes, bevel=bevel)
        expect = (before - removed, before + added,
                  f"a {'chamfer' if bevel else 'fillet'} takes material off a ridge and adds it in a crease, "
                  "no more than its section along the edges")  # fmt: skip
        return SolidProduct(
            solid,
            names,
            notes=tuple(notes),
            lost=carried.lost | again.lost,
            expect=expect,
        )

    return build


BUILDERS: Mapping[str, Callable[[Context], Product]] = {
    "shell": _shell,
    "offset": _offset,
    "fillet": _round(False),
    "chamfer": _round(True),
}
