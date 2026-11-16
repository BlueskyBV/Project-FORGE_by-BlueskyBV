"""A line of letters in the pinned font, engraved into the part or embossed on it (docs/definitions/text.md; docs/V2-stage4.md, 7.1).

``text``: each letter its glyph's contours (forge_spec.glyphs), scaled so the
letter H is ``height`` tall, set one after another by advance width with no
kerning; the line's box (first letter's start to the last's advance, baseline
to capital height) centred on ``origin``, the letters running along ``right``
with ``up`` their up, read the right way round from outside the face (the
face's outward normal is ``right`` cross ``up``).

Each contour is a closed wire of the font's own curves, exactly: a straight
piece is a line, a quadratic piece a degree-2 Bézier curve through the same
control points. The letters are the region of **nonzero winding** of all the
contours (TrueType's rule): every contour's face is laid down, the faces are
split where they overlap (OpenCascade's general fuse), and each piece is kept
where the contours round it wind a non-zero number of times (each counted by
its turn: anticlockwise round the face's normal +1, clockwise -1). The pieces
kept, merged where they share an edge, are pushed ``depth`` into the part
(``engrave``, taken away) or out of it (``emboss``, joined). Faces:
``letter_wall`` (their sides), ``letter_floor`` (engraved: the bottoms),
``letter_top`` (embossed: the tops).

After-check: the volume taken (engraved) is that of the part inside the
letters' prism; the volume added (embossed) is the prism's outside the part;
and either is no more than the letters' area times their depth.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
from forge_numeric import vector as fv
from forge_spec.font import ADVANCES, CAP_HEIGHT
from forge_spec.glyphs import CONTOURS
from forge_spec.letters import pieces
from OCP.BOPAlgo import BOPAlgo_Builder
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepGProp import BRepGProp
from OCP.collections import Array1_gp_Pnt as TColgp_Array1OfPnt
from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)
from OCP.Geom import Geom_BezierCurve
from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS_Compound

from ..errors import DesignError
from ..make import FUZZY, boolean, prism, unify
from ..names import Name, carry, named_by
from ..occt import INTEGRATION, boundary, faces, plane_of, volume
from ..products import Context, Product, SolidProduct

__all__ = ["BUILDERS", "letters_region"]

Point = tuple[float, float]
Piece = tuple[Point, Point | None, Point]


def _contours(text: str, height: float) -> list[list[Piece]]:
    """Every contour of every letter, in the line's own plane (x along it from its first letter's start, y up from its baseline), mm."""
    scale = height / CAP_HEIGHT
    found: list[list[Piece]] = []
    advance = 0
    for letter in text:
        for contour in CONTOURS[letter]:
            run: list[Piece] = []
            for a, c, b in pieces(contour):
                if a == b and (c is None or c == a):
                    continue  # a piece of no length
                run.append((((a[0] + advance) * scale, a[1] * scale),
                            None if c is None else ((c[0] + advance) * scale, c[1] * scale),
                            ((b[0] + advance) * scale, b[1] * scale)))  # fmt: skip
            if run:
                found.append(run)
        advance += ADVANCES[letter]
    return found


def _area(face: Any) -> float:
    props = GProp_GProps()
    with boundary("measuring the letters' area"):
        BRepGProp.SurfaceProperties_s(face, props, INTEGRATION, False)
    return float(props.Mass())


def _signed_area(run: Sequence[Piece]) -> float:
    """A contour's signed area (Green's theorem, each piece's share exactly): positive anticlockwise."""

    def cross(p: Point, q: Point) -> float:
        return p[0] * q[1] - p[1] * q[0]

    total = 0.0
    for a, c, b in run:
        total += (
            cross(a, b) / 2
            if c is None
            else (2 * cross(a, c) + 2 * cross(c, b) + cross(a, b)) / 6
        )
    return total


def letters_region(text: str, height: float, origin: Sequence[float], up: Sequence[float],
                   right: Sequence[float]) -> tuple[list[Any], Any]:  # fmt: skip
    """The letters' faces in their plane (the region of nonzero winding, pieces sharing an edge merged), and the plane."""
    o, u, r = (np.asarray(v, dtype=float) for v in (origin, up, right))
    out = np.cross(r, u)
    length = sum(ADVANCES[ch] for ch in text) * height / CAP_HEIGHT

    def world(p: Point) -> gp_Pnt:
        x = o + r * (p[0] - length / 2) + u * (p[1] - height / 2)
        return gp_Pnt(float(x[0]), float(x[1]), float(x[2]))

    plane = gp_Pln(
        gp_Ax3(gp_Pnt(*map(float, o)), gp_Dir(*map(float, out)), gp_Dir(*map(float, r)))
    )
    laid: list[Any] = []
    turns: list[int] = []
    with boundary("drawing the letters"):
        for run in _contours(text, height):
            turn = 1 if _signed_area(run) > 0 else -1
            if (
                turn < 0
            ):  # drawn anticlockwise round the normal, so its face is its inside
                run = [(b, c, a) for a, c, b in reversed(run)]
            wire = BRepBuilderAPI_MakeWire()
            for a, c, b in run:
                if c is None:
                    edge = BRepBuilderAPI_MakeEdge(world(a), world(b))
                else:
                    poles = TColgp_Array1OfPnt(1, 3)
                    for k, p in enumerate((a, c, b), start=1):
                        poles.SetValue(k, world(p))
                    edge = BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles))
                if not edge.IsDone():
                    raise DesignError("a letter's curve couldn't be drawn")
                wire.Add(edge.Edge())
            if not wire.IsDone():
                raise DesignError("a letter's contour doesn't close")
            face = BRepBuilderAPI_MakeFace(plane, wire.Wire(), True)
            if not face.IsDone():
                raise DesignError("a letter's contour bounds no face")
            laid.append(face.Face())
            turns.append(turn)
    if not laid:
        return [], plane
    if (
        len(laid) == 1
    ):  # one contour: its face is the region (the general fuse wants two at least)
        return laid, plane
    with boundary("laying the letters' contours over each other"):
        fuse = BOPAlgo_Builder()
        for face in laid:
            fuse.AddArgument(face)
        fuse.SetRunParallel(False)
        fuse.SetFuzzyValue(FUZZY)
        fuse.SetNonDestructive(True)
        fuse.Perform()
        if fuse.HasErrors():
            raise DesignError(
                "OpenCascade couldn't lay the letters' contours over each other"
            )
        cells = faces(fuse.Shape())
        index = TopTools_IndexedMapOfShape()
        for cell in cells:
            index.Add(cell)
        winding = [0] * len(cells)
        for face, turn in zip(laid, turns, strict=True):
            pieces_of = list(fuse.Modified(face)) or (
                [] if fuse.IsDeleted(face) else [face]
            )
            for piece in pieces_of:
                k = index.FindIndex(piece)
                if k >= 1:
                    winding[k - 1] += turn
        kept = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(kept)
        for cell, w in zip(cells, winding, strict=True):
            if w != 0:
                builder.Add(kept, cell)
    return faces(unify(kept).shape), plane


def _text(ctx: Context) -> Product:
    text = ctx.option("text")
    lacking = sorted({ch for ch in text if ch not in ADVANCES})
    if lacking:
        raise ctx.fail(
            DesignError("the pinned font has no such letters", letters=lacking)
        )
    height, depth = ctx.length("height"), ctx.length("depth")
    if not (height > 0.0 and depth > 0.0):
        raise ctx.fail(
            DesignError("letters have a height and a depth", height=height, depth=depth)
        )
    up, right = (np.asarray(ctx.vector(n), dtype=float) for n in ("up", "right"))
    up, right = up / fv.norm(up), right / fv.norm(right)
    if abs(float(fv.matmul(up, right))) > 1e-9:
        raise ctx.fail(DesignError("letters' up and right are square to each other"))
    out = np.cross(right, up)
    mode = ctx.option("mode", "engrave")
    part = ctx.solid(0)
    region, _ = letters_region(text, height, ctx.vector("origin"), up, right)
    if not region:  # spaces alone: nothing taken, nothing added
        return part
    along = -out * depth if mode == "engrave" else out * depth
    tools = [prism(face, tuple(float(c) for c in along)).shape for face in region]
    step = ctx.step
    far = "letter_floor" if mode == "engrave" else "letter_top"

    def role(face: Any) -> tuple[Name, ...]:
        found = plane_of(face)
        if found is not None and abs(abs(float(fv.dot(found[1], out))) - 1.0) <= 1e-9:
            gone = float(
                fv.dot(np.asarray(found[0]) - np.asarray(ctx.vector("origin")), out)
            )
            return (Name(step, far if abs(gone) > depth / 2 else "letter_mouth"),)
        return (Name(step, "letter_wall"),)

    kind = "subtract" if mode == "engrave" else "union"
    with boundary(f"the letters' {kind}"):
        done = boolean(kind, [part.shape], tools)
    named = [named_by(tool, role) for tool in tools]
    carried = carry(
        [part.names, *named], done.shape, done.history, fallback=(Name(step, "other"),)
    )
    merged = unify(done.shape)
    final = carry(
        [carried.names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    letters = sum(_area(face) for face in region)
    common = sum(
        volume(boolean("intersect", [part.shape], [tool]).shape) for tool in tools
    )
    whole = sum(volume(tool) for tool in tools)
    before = volume(part.shape)
    slack = 1e-6 * max(1.0, whole)
    moved = common if mode == "engrave" else whole - common
    expect = (
        (before - moved - slack, before - moved + slack)
        if mode == "engrave"
        else (before + moved - slack, before + moved + slack)
    )
    if moved > letters * depth * (1 + 1e-9) + slack:
        raise ctx.fail(
            DesignError("the letters moved more than their area times their depth")
        )
    done_how = "engraved" if mode == "engrave" else "embossed"
    note = f"{len(text)} letters {done_how}: {letters:.6g} mm² of them, {depth:g} mm"
    why = "letters take (add) the part inside (outside) their prism, no more than their area times their depth"
    return SolidProduct(
        merged.shape,
        final.names.on(merged.shape),
        notes=(note,),
        lost=frozenset(carried.lost | final.lost),
        expect=(*expect, why),
    )


BUILDERS: Mapping[str, Callable[[Context], Product]] = {"text": _text}
