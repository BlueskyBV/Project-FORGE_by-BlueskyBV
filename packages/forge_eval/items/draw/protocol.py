"""What the generator's draw asks of a kind of feature: the ``draw`` role's protocol (V2-stage4b-0b-inventory.md, 2.4).

At stage 4b.0b's step 2 each method is a thin wrapper of ``generator.py``'s
function that holds the kind's branch today; step 3 moves each kind's
branch into its module, where it overrides the method. Every seed draws as
before: the draw's weighted lists are rebuilt from the kinds' own weights
in today's order (V2-stage4b-0b.md, 3).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from typing import Any

from forge_registry import reserved

from forge_eval.generator import (
    GAP,
    OPPOSITE,
    REACH,
    Array,
    DoesNotFitError,
    Feature,
    Plan,
    _first,
    _Flat,
    _flat_axes,
    _Foot,
    _footprint,
    _named,
    _on_flat,
    _on_round,
    _overhanging,
    _Part,
    _q,
    _register_box,
    _Round,
    _round_cut,
    _sunk,
    _t,
    _touches_falling_edges,
    _turned_ends,
    _under,
    outline_of,
)
from forge_eval.truth import Copy, Prism, Step, Turned


class DrawKind:
    """One kind of feature, as the generator draws and builds it."""

    #: The kind this entry is for.
    key = ""

    #: A hole, a pocket or a slot: a solid taken from the face it is on, to a depth or through (not letters,
    #: whose category is a cut's too).
    cut_out = False

    #: What a standing item's height is, standing on a flat face: its ``length`` (a rod's, a tab's), or its ``height``.
    stand_height = "length"
    #: A boss's round side may touch a face's edge (tangent to it), and fall with it.
    falls_flush = False
    #: Its far end is a disc (a rod's), not a box's face.
    round_far_end = False
    #: Its foot is round, its diameter across (a boss's), standing round a side.
    round_foot = False
    #: It may stand flush with a face's edge (one box or boss).
    stands_flush = False
    #: Published: a thread may go on it, ``rod_length`` the size its length is.
    threadable = False
    rod_length = "length"
    #: Published: the faces a shell may leave open (shell.md), in this order; none where no shell hollows it.
    openable: tuple[str, ...] = ()
    #: It rounds another's edges (a fillet, a chamfer); ``bevels``, by a chamfer's flat; ``rounding_size``, the size
    #: that says how much.
    rounds_edges = False
    bevels = False
    rounding_size = "radius"
    #: It hollows another (a shell).
    hollows = False
    #: What it makes follows the roundings already made (a rounding's, a shell's), not kept clear of them.
    follows_roundings = False
    #: Published: a rounding rounds its rim, on a flat face (a hole's, a pocket's): never recessed, nor round a side.
    round_rim = False
    #: A face of its first copy may take standing items the generator draws (a body's).
    hosts_standing = False
    #: Drawn now and then flush with a face's edge (a post, a block), over its edge (a block), or touching it (a boss).
    drawn_flush = False
    drawn_overhung = False
    drawn_tangent = False
    #: A cut :func:`~forge_eval.generator.impossible` may make not fit (a hole, a pocket).
    misfits = False
    #: How often :func:`~forge_eval.generator._feature` draws it on a flat face, and where in its list (today's order).
    flat_weight = 0
    flat_rank = 0
    #: How often :func:`~forge_eval.generator._standing_new` draws it, and where in its list (today's order).
    new_weight = 0
    new_rank = 0
    #: Sizes it may have as 0 (a cone's top).
    may_be_zero: frozenset[str] = frozenset()

    # ------------------------------------------------------------------
    # Its own
    # ------------------------------------------------------------------
    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        """An item's outline on a face with these axes, about its centre: half sizes and corner radius (frame.md, place.md)."""
        s = f.sizes
        # a block or a post: its length along the face's first axis
        return (s["length"] / 2, s["width"] / 2), 0.0

    def extent(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """How far an item reaches back and forth along a face's two axes from the point it is placed by (place.md): an extrusion's outline, from its point (0, 0); anything else, its footprint about its centre."""
        (h1, h2), _ = _footprint(f, axes)
        return (-h1, h1), (-h2, h2)

    def foot_of(self, f: Feature, face: _Flat, at: tuple[float, float]) -> _Foot:
        """What a copy centred at ``at`` covers on a flat face: its outline; letters, their ink's box (it reaches past the line's); a cone wider at its top than its base, its top's circle."""
        half, corner = _footprint(f, face.axes)
        return _Foot(at, half, corner)

    def first(self, f: Feature, part: _Part) -> None:
        raise DoesNotFitError(
            f"a first body is a block, a cylinder, a tube, an extrusion or a revolution here, not a {f.kind}"
        )

    def on_flat(
        self, f: Feature, face: Any, index: int, part: Any, strict: bool
    ) -> list[Any]:
        """Its copies on one copy of a flat face (``generator._on_flat``)."""
        from forge_eval import generator

        return generator._on_flat(f, face, index, part, strict)

    def overhang(
        self, f: Feature, face: _Flat, feet: list[_Foot], strict: bool
    ) -> frozenset[tuple[int, float]]:
        """The sides of a rectangle a single block standing on it reaches past, each its axis's index and which end (frame.md: a body may overhang the face it stands on, but must meet it).

        It reaches past by ``_OVERHANG[0]`` at least, and stays over the face by
        ``_OVERHANG[1]``; the face is a plain rectangle (no corner or side a
        rounding has taken: what is under the overhang there would be air), out
        of any hollow.
        """
        return frozenset()

    def flush(self, f: Feature, face: Any) -> frozenset[tuple[int, float]]:
        """The sides of a face it is flush with (``generator._flush``)."""
        from forge_eval import generator

        return generator._flush(f, face)

    def rise(self, f: Feature) -> float:
        """How far a standing item rises out of the face it stands on: its height, its length, a ball's radius, a revolution's greatest height, embossed letters' depth."""
        s = f.sizes
        return s["height"]

    def on_round(
        self, f: Feature, side: _Round, index: int, part: _Part, strict: bool
    ) -> list[Copy]:
        """Holes round a rod's side: at an angle round its axis (a circle of them), along it from its ends; a boss or a post standing round it (:func:`_standing_round`)."""
        raise DoesNotFitError("round a side, only holes, bosses and posts here")

    def standing_round(
        self, f: Feature, side: Any, index: int, part: Any, strict: bool
    ) -> list[Any]:
        """A standing feature round a rod's side (``generator._standing_round``)."""
        from forge_eval import generator

        return generator._standing_round(f, side, index, part, strict)

    def build_one(self, f: Feature, plan: Plan, part: _Part, strict: bool) -> None:
        """One item of a plan: its copies, its solids and the faces it makes or changes."""
        if f.on is None:
            _first(f, part)
            return
        host, face_name = f.on
        made: list[Copy] = []
        for host_copy in part.copies.get(host, []):
            key = (host, host_copy.index, face_name)
            if key in part.flats:
                made += _on_flat(f, part.flats[key], len(made), part, strict)
            elif key in part.rounds:
                made += _on_round(f, part.rounds[key], len(made), part, strict)
            else:
                raise DoesNotFitError(
                    f"{f.id}: {host} has no face {face_name} that takes things"
                )
        part.copies[f.id] = made

    def shell(self, f: Feature, plan: Any, part: Any) -> None:
        """A shell, built (``generator._shell``)."""
        from forge_eval import generator

        generator._shell(f, plan, part)

    def rounding(self, f: Feature, plan: Any, part: Any, strict: bool) -> None:
        """A fillet or a chamfer, built (``generator._rounding``)."""
        from forge_eval import generator

        generator._rounding(f, plan, part, strict)

    def thread_on(self, f: Feature, plan: Any, part: Any, strict: bool) -> None:
        """A thread, built (``generator._thread_on``)."""
        from forge_eval import generator

        generator._thread_on(f, plan, part, strict)

    def sizes_hold(self, f: Feature) -> None:
        """That its sizes make a part (``generator._sizes_hold``)."""
        from forge_eval import generator

        generator._sizes_hold(f)

    def changes(self, f: Feature, plan: Any) -> Iterator[tuple[str, list[Feature]]]:
        """Each leaf of it and the changes of it a mutant tries (``generator._changes``)."""
        from forge_eval import generator

        return generator._changes(f, plan)

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        """The faces of an item that may take things, by name (frame.md and each kind's page)."""
        return ()

    # ------------------------------------------------------------------
    # Published: asked of the feature another acts on
    # ------------------------------------------------------------------
    def round_box(self, f: Feature, target: Feature, copy: Any, which: str, size: float, part: Any,
                  host: Any, strict: bool, rounded: float = 0.0) -> None:  # fmt: skip
        """A box's edges, rounded (``generator._round_box``)."""
        from forge_eval import generator

        generator._round_box(f, target, copy, which, size, part, host, strict, rounded)

    def round_rod(self, f: Feature, target: Feature, copy: Any, which: str, size: float, part: Any,
                  host: Any, strict: bool) -> None:  # fmt: skip
        """A rod's rims, rounded (``generator._round_rod``)."""
        from forge_eval import generator

        generator._round_rod(f, target, copy, which, size, part, host, strict)

    def round_cut(self, f: Feature, target: Feature, copy: Any, which: str, size: float, part: Any,
                  host: Any, strict: bool) -> None:  # fmt: skip
        """A cut's rims, rounded (``generator._round_cut``)."""
        from forge_eval import generator

        generator._round_cut(f, target, copy, which, size, part, host, strict)

    def earlier_vertical(self, f: Feature, target: Feature, plan: Any) -> float:
        """An earlier rounding of a box's vertical edges (``generator._earlier_vertical``)."""
        from forge_eval import generator

        return generator._earlier_vertical(f, target, plan)

    def standing_profile(
        self,
        f: Feature,
        index: int,
        base: Array,
        n: Array,
        face: _Flat,
        part: _Part,
        under: float,
    ) -> None:
        """An extrusion or a revolution standing on a face (extrusion.md, revolution.md), its foot run on a hair into it.

        An extrusion: its outline along the face's axes from its point, pushed
        out of the face its length; its +end that outline, over its length and
        the face's ``under`` material. A revolution: its half outline turned
        about the line out of the face through its point; its +end, where it has
        one, a disc or a ring over the least material under it in the
        revolution, and the face's too where every line down through it runs
        right through to the face.
        """
        assert f.outline is not None
        name, values = f.outline[0], dict(f.outline[1])
        shape = outline_of(name, values)
        up = _named(n)
        part.steps.append(
            Step(f.id, index, True, Turned(_t(base), _t(n), _sunk(shape, REACH)))
        )
        ends = _turned_ends(name, values)
        if "+end" in ends:
            height, inner, outer, least, through = ends["+end"]
            far = (f.id, index, "+end")
            part.flats[far] = _Flat(far, base + height * n, n.copy(), _flat_axes(up), "ring" if inner > 0 else "disc",
                                    (outer, outer), least + under if through else least,
                                    face.exit if through else None, inner=inner)  # fmt: skip

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        """One copy standing on a flat face, at ``p``: a box's, or a rod's (its far end a disc), over an overhang or flush with a hollow's wall as it is placed."""
        height = f.sizes[self.stand_height]
        (h1, h2), r = _footprint(f, face.axes)
        if beyond:
            _overhanging(
                f, copy_index, p, (e1, e2, n), (h1, h2), height, face, part, strict
            )
        else:
            part.steps.append(Step(f.id, copy_index, True, Prism(_t(p), _t(e1), _t(e2), _t(n), (h1, h2), r, 0.0,
                                                                 height), (REACH, 0.0)))  # fmt: skip
            if self.falls_flush and flush:
                _touches_falling_edges(f, p, (e1, e2, n), h1, height, flush, part)
        up = _named(n)
        # Over an overhang, only its own height (frame.md): under its far face the least, and nothing through.
        under = 0.0 if beyond else _under(face, feet[k])
        if f.turn is not None:
            return  # turned in its face, its faces take nothing yet (a later move): none is kept
        if self.round_far_end:
            far = (f.id, copy_index, "+end")
            part.flats[far] = _Flat(far, p + height * n, n.copy(), _flat_axes(up), "disc", (h1, h1),
                                    height + under, face.exit)  # fmt: skip
        else:
            _register_box(part, f.id, copy_index, p, up, face.axes, (2 * h1, 2 * h2, height),
                          under, None if beyond else face.exit)  # fmt: skip
            if face.key[2].startswith("inner"):
                # Flush with an edge of a hollow's inside face, a side is pressed against the wall that rises
                # there: no face of the part, so nothing goes on it; nor on the wall where it is pressed, which
                # is no face of the part either (a cut's mouth there, carried on into what it takes for air,
                # would open into the box: generated part 319). What is on the wall already keeps clear of it.
                for j, end in flush:
                    side = ("+" if end > 0 else "-") + face.axes[j]
                    part.flats.pop((f.id, copy_index, side), None)
                    wall = part.flats.get((face.key[0], face.key[1], f"inner {side}"))
                    if wall is None:
                        continue
                    middle = p + end * (h1, h2)[j] * (e1, e2)[j] + 0.5 * height * n
                    across = {
                        face.axes[1 - j]: (h1, h2)[1 - j],
                        up[1]: 0.5 * height,
                    }
                    u, v = wall.axes
                    pressed = _Foot(
                        wall.frame.plane(middle),
                        (across[u], across[v]),
                        0.0,
                    )
                    if strict and not all(pressed.clear_of(o, GAP) for o in wall.taken):
                        raise DoesNotFitError(
                            f"{f.id} would be pressed against {wall.key} where something is"
                        )
                    wall.taken.append(pressed)

    def cut_solid(
        self,
        f: Feature,
        p: Array,
        e1: Array,
        e2: Array,
        n: Array,
        depth: float,
        face: _Flat,
    ) -> tuple[Prism, float]:
        """What a cut takes away at ``p``, ``depth`` deep: its footprint's prism; and its round radius (none)."""
        (h1, h2), r = _footprint(f, face.axes)
        return Prism(_t(p), _t(e1), _t(e2), _t(n), (h1, h2), r, -depth, 0.0), 0.0

    def stands(self, f: Feature) -> bool:
        """Whether it stands out of the face it is on (not a cut, nor letters cut into it)."""
        return not self.cut_out

    def marks(
        self,
        f: Feature,
        face: _Flat,
        at: tuple[float, float],
        half: tuple[float, float],
        corner: float,
        part: _Part,
    ) -> None:
        """What a copy at ``at`` leaves on the face it is on, besides what it covers: a cut, its mouth (through to the far face) or its floor."""
        if not self.cut_out:
            return
        if f.depth is None and face.exit is not None:
            part.flats[face.exit].taken.append(_Foot(at, half, corner))
        elif f.depth is not None:
            face.dug.append((_Foot(at, half, corner), f.depth))

    def limits(self, f: Feature) -> None:
        """Its own page's limits on its sizes, besides every size being more than 0: a :class:`DoesNotFitError` where one is broken."""

    def roundable(self, first: bool) -> tuple[str, ...]:
        """The edge sets the generator rounds on it: as the first body, or standing on a face."""
        return ()

    def own_changes(
        self, f: Feature, plan: Plan
    ) -> Iterator[tuple[str, list[Feature]]]:
        """Its own ways of being made not quite as drawn (after its sizes, depth, recess and choices), each with its changed copies."""
        yield from ()

    def turned(self, angle: float) -> list[float]:
        """It turned round the side it stands round, a quarter or a half."""
        return [(angle + d) % 360.0 for d in (90.0, -90.0, 180.0)]

    def draw_new(
        self, rng: random.Random, face: _Flat, top: float, choices: dict[str, str]
    ) -> dict[str, float]:
        """A new standing kind's choices and sizes, drawn on a flat face (``top`` its largest size's scale): stage 4's kinds stage 2 didn't draw."""
        raise DoesNotFitError(f"a {self.key} isn't drawn as a new standing kind")

    def draw_on_flat(self, rng: random.Random, face: _Flat, top: float, sizes: dict[str, float],
                     choices: dict[str, str]) -> tuple[str, float, float] | None:  # fmt: skip
        """Its sizes and choices, drawn on a flat face (``top`` its largest size's scale), put in ``sizes`` and ``choices``; its recess (a hole's), or None: a block's or a post's here."""
        sizes["length"], sizes["width"] = (
            _q(rng.uniform(3, top * 2)),
            _q(rng.uniform(3, top * 2)),
        )
        sizes["height"] = _q(rng.uniform(2, 12))
        return None

    def may_hollow(self, body: Feature) -> bool:
        """Whether the generator hollows this first body (one with faces a shell may leave open)."""
        return True

    def floored(self, opened: set[str] | tuple[str, ...]) -> bool:
        """Whether a shell opened on ``opened`` has a floor (a wall opposite an opening)."""
        return any(OPPOSITE[o] not in opened for o in opened)

    def hollow(self, f: Feature, body: Feature, plan: Plan, part: _Part, t: float, floor: float, opened: set[str],
               wall: Callable[[str], float]) -> None:  # fmt: skip
        """Its hollow, taken away just after it is made (shell.md): ``t`` its walls' thickness, ``floor`` its floor's, ``wall`` each face's."""
        raise DoesNotFitError(
            f"{f.id}: the generator hollows a block, a cylinder or a dome, not a {body.kind}"
        )

    def shell_opening(
        self, rng: random.Random, body: Feature
    ) -> tuple[float, tuple[str, ...], float]:
        """How a shell of it is opened: its walls' scale (``least``), the faces it leaves open, and how far it is across them."""
        raise DoesNotFitError(f"the generator doesn't hollow a {self.key}")

    def most_rounding(self, target: Feature, which: str) -> tuple[str, float]:
        """The most a rounding of its edge set ``which`` could be (and the set, where that one isn't there): a cut's rim, by its footprint."""
        if which == "bottom" and target.depth is None:
            which = "top"
        most = min(*(_footprint(target, ("x", "y"))[0]), 4.0)
        return which, most

    def rounded(self, f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part,
                host: _Flat | None, strict: bool, plan: Plan) -> None:  # fmt: skip
        """A rounding ``f`` of its edges ``which`` on one copy of it (``target``): a cut's rim here."""
        assert host is not None
        _round_cut(f, target, copy, which, size, part, host, strict)

    def after_rounding(
        self, f: Feature, target: Feature, part: _Part, made: int, strict: bool
    ) -> None:
        """What a rounding of it leaves to do after every copy is rounded (a box's: drop what it covers)."""

    def round_mouth(self, target: Feature) -> bool:
        """Whether its mouth is a circle (a hole's, a round pocket's)."""
        return False

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("4b.0d2")
    def acts_on(self, f: Feature) -> tuple[str, ...]:
        """The items it acts on, by id (item 11): the order's graph, as the generator draws it at random."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def order_rank(self) -> int:
        """Its rank in the canonical order (item 11), the default inferred and shown at confirmation."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def as_of(self, f: Feature) -> str | None:
        """The item after which stood the shape it acts on, where it says (item 11's ``as_of``)."""
        raise NotImplementedError
