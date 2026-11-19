"""How the generator draws for a block: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
block's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

import numpy as np
from forge_numeric import vector as fv

from forge_eval.generator import (
    _BEVEL,
    _OVERHANG,
    GAP,
    OPPOSITE,
    REACH,
    TURN_AXES,
    DoesNotFitError,
    Feature,
    Plan,
    _cos_sin,
    _draw,
    _drop_covered,
    _earlier_vertical,
    _Flat,
    _flat_axes,
    _Foot,
    _footprint,
    _lean_of,
    _margin,
    _named,
    _own_halves,
    _Part,
    _q,
    _round_box,
    _t,
    _v,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy, Outline2, Prism, Pushed, Step, unit_of


class Block(DrawKind):
    key = "block"
    leans = True
    leans_since = (1, 5)
    turnable = True
    flat_weight = 1
    flat_rank = 5
    openable = ("+x", "-x", "+y", "-y", "+z", "-z")
    hosts_standing = True
    drawn_flush = True
    drawn_overhung = True
    stands_flush = True
    stand_height = "height"

    def first(self, f: Feature, part: _Part) -> None:
        s = f.sizes
        length, width, height = s["length"], s["width"], s["height"]
        part.copies[f.id] = [
            Copy(f.id, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y"))
        ]
        part.steps.append(Step(f.id, 0, True, Prism((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                                                     (length / 2, width / 2), 0.0, 0.0, height)))  # fmt: skip
        e = {"x": length, "y": width, "z": height}
        middle = _v((0.0, 0.0, height / 2))
        for axis in "xyz":
            for sign in (1.0, -1.0):
                name = ("+" if sign > 0 else "-") + axis
                fa = _flat_axes(name)
                part.flats[(f.id, 0, name)] = _Flat(
                    (f.id, 0, name), middle + e[axis] / 2 * _v(unit_of(name)), _v(unit_of(name)), fa, "rect",
                    (e[fa[0]] / 2, e[fa[1]] / 2), e[axis], (f.id, 0, ("-" if sign > 0 else "+") + axis), level=True)  # fmt: skip
        return

    def overhang(
        self, f: Feature, face: _Flat, feet: list[_Foot], strict: bool
    ) -> frozenset[tuple[int, float]]:
        if f.pattern is not None or face.shape != "rect":
            return frozenset()
        (foot,) = feet
        centre = face.coords()
        found = set()
        for k in (0, 1):
            for end in (-1.0, 1.0):
                past = end * (foot.at[k] - centre[k]) + foot.half[k] - face.half[k]
                if past <= 0:
                    continue
                plain = (
                    not any(face.corners)
                    and not any(face.margin)
                    and face.hollow is None
                )
                if strict and (
                    past < _OVERHANG[0]
                    or 2 * foot.half[k] - past < _OVERHANG[1]
                    or not plain
                ):
                    raise DoesNotFitError(
                        f"{f.id} overhangs {face.key} only just, or all but leaves it, or overhangs a face that isn't plain"
                    )
                found.add((k, end))
        return frozenset(found)

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+x", "-x", "+y", "-y", "+z", "-z")

    def roundable(self, first: bool) -> tuple[str, ...]:
        return (
            ("vertical", "top", "bottom", "all")
            if first
            else ("vertical", "top", "joint")
        )

    def shell_opening(
        self, rng: random.Random, body: Feature
    ) -> tuple[float, tuple[str, ...], float]:
        s = body.sizes
        sizes = {"x": s["length"], "y": s["width"], "z": s["height"]}
        least = min(sizes.values())
        roll = rng.random()
        if roll < 0.3:
            opened: tuple[str, ...] = ()
        elif roll < 0.8:
            opened = ("+z",) if rng.random() < 0.5 else (rng.choice(self.openable),)
        else:
            axis = rng.choice("xyz")
            opened = ("+" + axis, "-" + axis)
        across = sizes[opened[0][1]] if opened else least
        return least, opened, across

    def hollow(self, f: Feature, body: Feature, plan: Plan, part: _Part, t: float, floor: float, opened: set[str],
               wall: Callable[[str], float]) -> None:  # fmt: skip
        key = (body.id, 0)
        s = body.sizes
        lo = _v((-s["length"] / 2, -s["width"] / 2, 0.0))
        hi = _v((s["length"] / 2, s["width"] / 2, s["height"]))
        low = lo + _v([wall("-" + a) for a in "xyz"])
        high = hi - _v([wall("+" + a) for a in "xyz"])
        if np.any(high - low < 2 * GAP + 1.0):
            raise DoesNotFitError(
                f"{f.id}'s walls leave too little hollow in {body.id}"
            )
        # Its vertical edges rounded or bevelled (made before the hollow, frame.md): the hollow's corners round the
        # same axes, the walls' thickness less, or are bevelled to keep the walls' thickness, (2 - sqrt 2) times
        # it less (shell.md); sharp where that is nothing.
        edge = next((g for g in plan if _draw(g.kind).rounds_edges and g.of == body.id
                     and g.choices["which"] == "vertical"), None)  # fmt: skip
        if edge is not None and opened - {"+z", "-z"}:
            raise DoesNotFitError(
                f"{f.id}: the generator opens a body with rounded vertical edges only at its top or base"
            )
        bevelled = edge is not None and _draw(edge.kind).bevels
        if edge is None:
            corner = 0.0
        elif bevelled:
            corner = max(edge.sizes["size"] - (2 - math.sqrt(2)) * t, 0.0)
        else:
            corner = max(edge.sizes["radius"] - t, 0.0)
        if 2 * corner > min(high[0] - low[0], high[1] - low[1]):
            raise DoesNotFitError(
                f"{f.id}'s hollow is too narrow for its rounded corners"
            )
        # The hollow as a prism along the axis of its opening (carried on out through it), or along z.
        axis = next((name[1] for name in sorted(opened)), "z")
        k = "xyz".index(axis)
        first, second = TURN_AXES[axis]
        middle = (low + high) / 2
        half = tuple((high - low)["xyz".index(a)] / 2 for a in (first, second))
        span = float(high[k] - low[k]) / 2
        ends = (
            REACH if "-" + axis in opened else 0.0,
            REACH if "+" + axis in opened else 0.0,
        )
        frame = (unit_of("+" + first), unit_of("+" + second), unit_of("+" + axis))
        if bevelled and corner > 0:
            # Its section a rectangle with its corners cut square across: an outline of eight sides.
            h1, h2 = half
            ring = ((h1, h2 - corner), (h1 - corner, h2), (-h1 + corner, h2), (-h1, h2 - corner), (-h1, -h2 + corner),
                    (-h1 + corner, -h2), (h1 - corner, -h2), (h1, -h2 + corner))  # fmt: skip
            section = Outline2(ring[-1], tuple((p, None, False) for p in ring))
            part.steps.append(
                Step(
                    f.id,
                    0,
                    False,
                    Pushed(_t(middle), *frame, section, -span, span),
                    ends,
                )
            )
        else:
            part.steps.append(Step(f.id, 0, False, Prism(_t(middle), *frame, (half[0], half[1]), corner, -span, span),
                                   ends))  # fmt: skip
        # Its rim, where nothing rounds its edges: the face less the hollow's mouth, its walls all the way under it
        # (shell.md, "The rim"); a cut through one comes out of its far face, where that is closed.
        rimmed = not any(_draw(g.kind).rounds_edges and g.of == body.id for g in plan)
        for name in self.openable:
            outer = (body.id, 0, name)
            if name in opened:
                fa = _flat_axes(name)
                rim = part.flats[outer]
                mouth = tuple(float(high["xyz".index(a)] - low["xyz".index(a)]) / 2 for a in fa)
                off = [float(middle["xyz".index(a)] - rim.centre["xyz".index(a)]) for a in fa]
                if not rimmed or rim.shape != "rect" or any(abs(o) > 1e-9 for o in off):
                    del part.flats[outer]
                    continue
                rim.shape, rim.mouth = "frame", (mouth[0], mouth[1])
                rim.exit = None if OPPOSITE[name] in opened else (body.id, 0, OPPOSITE[name])
                continue
            a = name[1]
            i = "xyz".index(a)
            inner = (body.id, 0, f"inner {name}")
            fa = _flat_axes(name)
            centre = middle.copy()
            centre[i] = high[i] if name[0] == "+" else low[i]
            face = part.flats[outer]
            face.material, face.exit = wall(name), inner
            room = math.inf if OPPOSITE[name] in opened else float(high[i] - low[i])
            size = high - low
            across = (
                float(size["xyz".index(fa[0])]) / 2,
                float(size["xyz".index(fa[1])]) / 2,
            )
            part.flats[inner] = _Flat(inner, centre, -face.normal, fa, "rect", across, wall(name), outer, room=room,
                                      hollow=key)  # fmt: skip
            if corner and a == "z":
                # A bevelled corner kept clear of as a round one within it, _BEVEL times its size (as on the outer faces).
                kept = _BEVEL * corner if bevelled else corner
                part.flats[inner].corners = (kept, kept, kept, kept)
            elif corner:  # a side wall's inside face ends where it rounds into the next
                other = "x" if a == "y" else "y"
                _margin(part.flats[inner], other, -1.0, corner)
                _margin(part.flats[inner], other, 1.0, corner)

    def standing_shell(
        self, rng: random.Random, body: Feature, up: str
    ) -> tuple[dict[str, float], tuple[str, ...]] | None:
        """A shell of a block standing on a face, ``up`` the way it stands, by its sizes and the faces it leaves open:
        sealed, or open on its far face (a box, a cup standing on the part), its walls 1 mm thick or more, and now
        and then a floor of its own (the wall it stands by)."""
        s = body.sizes
        least = min(s["length"], s["width"], s["height"])
        opened = () if rng.random() < 0.4 else (up,)
        sizes_ = {"thickness": _q(rng.uniform(1.0, max(1.2, least / 6)))}
        if opened and rng.random() < 0.5:
            sizes_["floor"] = _q(rng.uniform(1.0, max(1.2, s["height"] / 5)))
        return sizes_, opened

    def hollow_standing(self, f: Feature, body: Feature, plan: Plan, part: _Part, t: float, floor: float,
                        opened: set[str], wall: Callable[[str], float]) -> None:  # fmt: skip
        """A block standing on a flat face hollowed (shell.md; place.md, "Turned in the face"; V2-stage4b-0c.md,
        step 5.1): every copy's hollow made as with it upright, then turned with it where it is turned; its walls
        the material under its faces, a cut through one coming out on the inside face across the wall; its inside
        faces turned with it. The generator hollows one standing wholly on a face of the part's axes, out of any
        hollow, upright on it or leaning (step 5.5: :meth:`_hollow_leaning`), not turned and leaning, none of its edges
        rounded, sealed or open on its far face."""
        if (body.tilt is not None and body.turn is not None) or any(_draw(g.kind).rounds_edges and g.of == body.id
                                                                    for g in plan):  # fmt: skip
            raise DoesNotFitError(f"{f.id}: the generator hollows a standing block upright or leaning on its face, "
                                  "not turned and leaning, none of its edges rounded")  # fmt: skip
        height = body.sizes["height"]
        for copy in part.copies.get(body.id, []):
            k = copy.index
            face = part.flats.get(copy.host) if copy.host is not None else None
            if face is None or face.turned or face.hollow is not None or not math.isinf(face.room):
                raise DoesNotFitError(f"{f.id}: the generator hollows a block standing on a face of the part's "
                                      "axes, out of any hollow")  # fmt: skip
            if body.tilt is not None:
                self._hollow_leaning(f, body, copy, face, part, opened, wall, height)
                continue
            up = _named(face.normal)
            n = _v(unit_of(up))
            down = OPPOSITE[up]
            if not np.array_equal(face.normal, n) or not opened <= {up}:
                raise DoesNotFitError(f"{f.id}: the generator hollows a block standing on a face of the part's axes, "
                                      "sealed or open on its far face")  # fmt: skip
            (h1, h2), _ = _footprint(body, face.axes)
            if not face.holds(face.foot(body, face.frame.plane(_v(copy.point))), GAP):
                raise DoesNotFitError(f"{f.id}: the generator hollows a block standing wholly on its face")
            axes = face.axes
            c, s = _cos_sin(body.turn or 0.0)
            e1, e2 = _v(unit_of("+" + axes[0])), _v(unit_of("+" + axes[1]))
            # Its own ways on the part: a turned block's first two turned in the face (as _turned_sides has them).
            ways = {axes[0]: c * e1 + s * e2 + 0.0, axes[1]: c * e2 - s * e1 + 0.0, up[1]: _v(unit_of("+" + up[1]))}
            extent = {axes[0]: 2 * h1, axes[1]: 2 * h2, up[1]: height}
            middle = _v(copy.point) + height / 2 * n
            low = {a: -extent[a] / 2 + wall("-" + a) for a in "xyz"}
            high = {a: extent[a] / 2 - wall("+" + a) for a in "xyz"}
            if any(high[a] - low[a] < 2 * GAP + 1.0 for a in "xyz"):
                raise DoesNotFitError(f"{f.id}'s walls leave too little hollow in {body.id}")
            centre = middle + sum(((low[a] + high[a]) / 2 * ways[a] for a in "xyz"), _v((0.0, 0.0, 0.0)))
            # The hollow as a prism along its up axis, carried on out through its far face where that is open.
            axis = up[1]
            first, second = TURN_AXES[axis]
            span = (high[axis] - low[axis]) / 2
            ends = (REACH if "-" + axis in opened else 0.0, REACH if "+" + axis in opened else 0.0)
            part.steps.append(Step(f.id, k, False, Prism(_t(centre), _t(ways[first]), _t(ways[second]), _t(ways[axis]),
                                                         ((high[first] - low[first]) / 2,
                                                          (high[second] - low[second]) / 2), 0.0, -span, span),
                                   ends))  # fmt: skip
            turned = body.turn is not None and body.turn != 0.0
            for name in self.openable:
                outer = (body.id, k, name)
                if name in opened:
                    part.flats.pop(outer, None)
                    continue
                a, sign = name[1], (1.0 if name[0] == "+" else -1.0)
                d = sign * ways[a]
                inner = (body.id, k, f"inner {name}")
                fa = _flat_axes(name)
                own = None if name == down else part.flats.get(outer)
                if own is None and name == up:
                    # Turned on a face without the same material under all of it, its far face is its own top wall's.
                    own = part.flats[outer] = _Flat(outer, middle + height / 2 * n, n.copy(), fa, "rect",
                                                    (extent[fa[0]] / 2, extent[fa[1]] / 2), 0.0, None, level=True,
                                                    turn=body.turn or 0.0)  # fmt: skip
                if own is not None:
                    own.material, own.exit = wall(name), inner
                part.flats[inner] = _Flat(
                    inner, centre + sign * (high[a] - low[a]) / 2 * ways[a], -d, fa, "rect",
                    ((high[fa[0]] - low[fa[0]]) / 2, (high[fa[1]] - low[fa[1]]) / 2), wall(name),
                    outer if own is not None else None,
                    room=math.inf if OPPOSITE[name] in opened else high[a] - low[a], hollow=(body.id, k),
                    oriented=(_t(ways[fa[0]]), _t(ways[fa[1]])) if turned else None)  # fmt: skip

    def _hollow_leaning(self, f: Feature, body: Feature, copy: Copy, face: _Flat, part: _Part, opened: set[str],
                        wall: Callable[[str], float], height: float) -> None:  # fmt: skip
        """A leaning block hollowed (V2-stage4b-0c.md 3.3, step 5.5; shell.md): its hollow as with it upright, its
        floor raised by as much as the face it leans on rises under the hollow's far side along its lean (its half size
        along it less its wall there, times its tilt's tan), then leaned with it: the floor its thickness where it is
        thinnest. Its far face (sealed) and its sides over their walls, a cut through one coming out inside; its
        inside faces leaned with it, the material under its floor its own back along its axis to the face it leans
        on (a :class:`_Flat`'s ``slant``), what goes on them as on a leaning item's faces."""
        k = copy.index
        lean = _lean_of(body, face.axes)
        along, across = _own_halves(body, face.axes, lean)
        n = face.normal
        w = lean.in_part(face)
        u = lean.direction(face)
        tilted = lean.c * w - lean.s * n + 0.0  # its lean's way square to its direction
        side = np.asarray(np.cross(n, w), dtype=np.float64) + 0.0  # across its lean: (tilted, side, u) right-handed
        p = _v(copy.point)
        up = _named(n)
        down = OPPOSITE[up]
        # Upright, along its lean (w), across it (side) and up (n): the hollow's span each way, from its point.
        ways = ((w, tilted, along), (side, side, across), (n, u, height))
        span: list[tuple[float, float]] = []
        for upright, _, half in ways[:2]:
            span.append((-half + wall(_named(-upright)), half - wall(_named(upright))))
        rise = max(span[0][1], 0.0) * lean.tan
        span.append((rise + wall(down), height - wall(up)))
        if any(hi - lo < 2 * GAP + 1.0 for lo, hi in span):
            raise DoesNotFitError(f"{f.id}'s walls leave too little hollow in {body.id}")
        middle = [(lo + hi) / 2 for lo, hi in span]
        centre = p + sum((middle[j] * ways[j][1] for j in range(3)), _v((0.0, 0.0, 0.0)))
        reach = (span[2][1] - span[2][0]) / 2
        part.steps.append(Step(f.id, k, False, Prism(_t(centre), _t(tilted), _t(side), _t(u),
                                                     ((span[0][1] - span[0][0]) / 2, (span[1][1] - span[1][0]) / 2),
                                                     0.0, -reach, reach),
                               (0.0, REACH if up in opened else 0.0)))  # fmt: skip

        def leaned(a: np.ndarray) -> np.ndarray:  # an upright direction, as it leans
            return float(fv.matmul(a, w)) * tilted + float(fv.matmul(a, side)) * side + float(fv.matmul(a, n)) * u + 0.0

        for j, (upright, _, _) in enumerate(ways):
            for sign in (1.0, -1.0):
                d = sign * upright + 0.0
                name = _named(d)
                outer = (body.id, k, name)
                inner = (body.id, k, f"inner {name}")
                if name in opened:
                    part.flats.pop(outer, None)
                    continue
                own = part.flats.get(outer) if name != down else None
                if own is not None:  # its far face and its sides: over their walls, a cut through one coming out inside
                    own.material, own.exit, own.slant, own.leans = wall(name), inner, None, True
                fa = face.axes if j == 2 else _flat_axes(name)
                at = list(middle)
                at[j] = span[j][1] if sign > 0 else span[j][0]
                halves = [(hi - lo) / 2 for lo, hi in span]
                sizes = {_named(ways[i][0])[1]: halves[i] for i in range(3)}
                floor = name == down
                material = wall(name) + (span[0][1] - middle[0]) * lean.tan if floor else wall(name)
                part.flats[inner] = _Flat(
                    inner, p + sum((at[i] * ways[i][1] for i in range(3)), _v((0.0, 0.0, 0.0))), -leaned(d), fa,
                    "rect", (sizes[fa[0]], sizes[fa[1]]), material, None if floor else (outer if own is not None else None),
                    room=math.inf if OPPOSITE[name] in opened else 2 * halves[j], hollow=(body.id, k),
                    oriented=(_t(leaned(_v(unit_of("+" + fa[0])))), _t(leaned(_v(unit_of("+" + fa[1]))))),
                    slant=(lean.way, lean.tan) if floor else None, leans=not floor)  # fmt: skip

    def most_rounding(self, target: Feature, which: str) -> tuple[str, float]:
        s = target.sizes
        across, height = min(s["length"], s["width"]) / 2, s["height"]
        most = {"vertical": across, "top": min(across, height), "bottom": min(across, height),
                "all": min(across, height / 2), "joint": min(height, 3.0)}[which]  # fmt: skip
        return which, most

    def rounded(self, f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part,
                host: _Flat | None, strict: bool, plan: Plan) -> None:  # fmt: skip
        _round_box(
            f,
            target,
            copy,
            which,
            size,
            part,
            host,
            strict,
            _earlier_vertical(f, target, plan),
        )

    def after_rounding(
        self, f: Feature, target: Feature, part: _Part, made: int, strict: bool
    ) -> None:
        _drop_covered(f, target, part, made, strict)


ENTRY = Block()
