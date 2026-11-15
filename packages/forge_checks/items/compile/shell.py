"""What the check compiler holds for a shell: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from forge_spec.draft import Faces, Item
from forge_spec.schema import KINDS

from forge_checks.items.compile._common import _WALL_REACH, _mm, _t, _v
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import BallCentre
from forge_checks.kinds.size import Between
from forge_checks.kinds.surfaces import Ball, Plane, Round
from forge_checks.kinds.wall import Annulus
from forge_checks.place import FlatFace, RoundSide, unit
from forge_checks.telling import Alternative

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Shell(CompileKind):
    key = "shell"

    def checks(self, c: CompileContext, item: Item) -> None:
        """A shell's walls and floor, each from the body's face to the hollow's behind it (flat, round a rod's side, or a ball's); its open faces, told from the other choices."""
        of = item.get("of")
        body = c.spec.item(str(of))
        c.skip(
            item, "of", "the body hollowed: its walls are checked", "its walls' checks"
        )
        thickness = _mm(item.get("thickness"))
        c.size(item, thickness)
        floor_value = item.get("floor")
        made = 0
        for (owner, index), hollow in c.placed.hollows.items():
            if owner != str(of) or body is None:
                continue
            faces = c.faces(owner, index)
            walls: list[tuple[float, object]] = []
            for name, wall in hollow.walls.items():
                face = faces.get(name)
                if isinstance(face, FlatFace):
                    n = _v(unit(face.normal))
                    spot = c._wall_spot(face, wall)
                    outer = Plane(_t(spot), unit(face.normal), _WALL_REACH)
                    inner = Plane(_t(spot - wall * n), _t(-n), _WALL_REACH)
                    if c.seen(outer) and c.seen(inner):
                        walls.append((wall, Between(outer, inner, unit(face.normal))))
                elif name == "surface":
                    main = c._main(body, c.copies(body)[index])
                    if isinstance(main, BallCentre):
                        ball = main.ball
                        hollow_ball = Ball(ball.centre, ball.radius - wall, True)
                        if c.seen_ball(ball) and c.seen_ball(hollow_ball):
                            walls.append((wall, Annulus(ball, hollow_ball)))
            side, inside = faces.get("side"), faces.get("inner side")
            if isinstance(side, RoundSide) and isinstance(inside, RoundSide):
                axis = unit("+" + side.axis)
                outer_round = Round(
                    side.start, axis, side.radius, 0.0, side.length, False
                )
                inner_round = Round(
                    inside.start, axis, inside.radius, 0.0, inside.length, True
                )
                if c.seen_round(outer_round) and c.seen_round(inner_round):
                    walls.append((thickness, Annulus(outer_round, inner_round)))
            for wall, target in walls:
                field_name = "floor" if (floor_value is not None and abs(wall - _mm(floor_value)) < 1e-12
                                         and abs(wall - thickness) > 1e-12) else "thickness"  # fmt: skip
                c.check(
                    item,
                    field_name,
                    "wall",
                    wall,
                    c.tol(item.get(field_name)),
                    target,
                    made,
                )
                made += 1
        if not any(c.field == "thickness" for c in c.checks if c.item == item.id):
            c.skip(
                item,
                "thickness",
                "none of its walls is on the part's surface both sides",
            )
        if floor_value is not None and not any(
            c.field == "floor" for c in c.checks if c.item == item.id
        ):
            c.skip(
                item,
                "floor",
                "its floor is as thick as its walls: checked with them",
                "its walls' checks",
            )
        open_faces = item.get("open")
        if isinstance(open_faces, Faces) and body is not None:
            alternatives = []
            # Each face opened or shut in turn: shutting the only open one is the sealed hollow, which is the
            # shape a forgotten opening makes (V1's false pass 16).
            for f in KINDS[body.kind].faces:
                if f.startswith("inner"):
                    continue
                changed = tuple(sorted(set(open_faces.faces) ^ {f}))
                alternatives.append(Alternative(f"open {list(changed)}",
                                                replace(item, fields={**item.fields, "open": replace(open_faces, faces=changed)})))  # fmt: skip
            c._told(item, "open", "choice", alternatives)


ENTRY = Shell()
