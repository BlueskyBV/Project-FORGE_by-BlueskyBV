"""What the compile role's kinds may ask of the check compiler: their narrow context (V2-stage4b-0b.md, 2).

The kinds (and the pattern modes and shared helpers) are typed against
:class:`CompileContext`, never the compiler's class, so mypy holds them to
these members alone; the object they are given is the compiler, which has
them all. A member the kinds start to use is added here, in sight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import numpy as np
    from forge_spec.draft import Item, PartSpec, Pattern
    from forge_spec.values import Value
    from numpy.typing import NDArray

    from forge_checks.checks import Check
    from forge_checks.classes import Tolerance
    from forge_checks.kinds.position import Ref
    from forge_checks.kinds.surfaces import Ball, Cone, Plane, Round
    from forge_checks.place import Copy, Face, FlatFace, Placed, Vec
    from forge_checks.telling import Alternative
    from forge_checks.view import Capability

    Array = NDArray[np.float64]


class CompileContext(Protocol):
    """The check compiler, as its kinds see it."""

    spec: PartSpec
    placed: Placed
    checks: list[Check]

    def check(
        self,
        item: Item,
        name: str,
        kind: str,
        nominal: float,
        tolerance: Tolerance | None,
        target: object,
        copy: int | None = ...,
        needs: frozenset[Capability] = ...,
    ) -> None: ...
    def skip(
        self, item: Item, name: str, why: str, held_by: str | None = ...
    ) -> None: ...
    def size(self, item: Item, value: float) -> None: ...
    def seen(self, plane: Plane, half: tuple[float, float] | None = ...) -> bool: ...
    def seen_round(self, surface: Round) -> bool: ...
    def seen_cone(self, surface: Cone) -> bool: ...
    def seen_ball(self, ball: Ball) -> bool: ...
    def _wall_spot(self, face: FlatFace, wall: float) -> Array: ...
    def face_plane(self, face: FlatFace, reach: float = ...) -> Plane: ...
    def face_rect(self, face: FlatFace) -> Plane: ...
    @staticmethod
    def along(copy: Copy, axis: str) -> Vec: ...
    def _leaning_rest(self, item: Item, names: Sequence[str]) -> None: ...
    def cut_wall(
        self, copy: Copy, way: Array, at: float, across: Array, half: float
    ) -> Plane: ...
    @staticmethod
    def tol(value: object, column: str = ...) -> Tolerance: ...
    def item(self, item: Item) -> None: ...
    def copies(self, item: Item) -> tuple[Copy, ...]: ...
    def faces(self, item_id: str, index: int) -> dict[str, Face]: ...
    def _not_placed(self, item: Item, why: str) -> None: ...
    def _profile(self, item: Item) -> None: ...
    def _height(
        self,
        item: Item,
        name: str,
        copy: Copy,
        top: Plane,
        bottom: Plane | None,
        value: float,
        footprint: float,
    ) -> None: ...
    def _box_body(
        self,
        item: Item,
        sizes: Callable[[Copy], dict[str, tuple[str, float]]],
        height: str | None,
    ) -> None: ...
    def _round_end(self, item: Item) -> None: ...
    def _plain(self, item: Item) -> float: ...
    def _round_body(
        self, item: Item, diameter: str, length: str, bore: str | None = ...
    ) -> None: ...
    def _axis(self, item: Item) -> None: ...
    def _standing_fields(self, item: Item) -> None: ...
    def _cut_depth(
        self,
        item: Item,
        copy: Copy,
        radius: float,
        reach: float,
        depth: float,
        outline: tuple[str, float, float] | None = ...,
    ) -> None: ...
    def _floor(
        self,
        item: Item,
        name: str,
        copy: Copy,
        floor: Plane,
        depth: float,
        tolerance: Tolerance,
        reach: float,
    ) -> None: ...
    def _cut_fields(self, item: Item) -> None: ...
    def _main(self, item: Item, copy: Copy) -> Ref | None: ...
    def _own_outline(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Ref, Ref, Ref] | None: ...
    def _turned_axis(self, item: Item, copy: Copy) -> Ref | None: ...
    def _turned_edge(self, item: Item, copy: Copy) -> Ref | None: ...
    def _recess(self, item: Item, radius: float) -> float: ...
    def _sides_along(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None: ...
    def _box_sides(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None: ...
    def _round_ends(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Round, Round] | None: ...
    def _tab_end(self, item: Item, copy: Copy) -> Round: ...
    def _turned_rim(
        self, owner: Item, copy: Copy, end: str
    ) -> tuple[Ref | str, Ref | str, Ref] | str: ...
    def _pitches(
        self,
        item: Item,
        at: str,
        pattern: Pattern,
        name: str,
        value: Value,
        group: list[Copy],
    ) -> None: ...
    def _circle(
        self,
        item: Item,
        at: str,
        pattern: Pattern,
        name: str,
        value: Value | None,
        group: list[Copy],
        face: FlatFace,
    ) -> None: ...
    def _insets(
        self,
        item: Item,
        at: str,
        name: str,
        value: Value,
        group: list[Copy],
        face: FlatFace,
        pattern: Pattern,
    ) -> None: ...
    def _choice_value(self, item: Item, name: str) -> str | None: ...
    def _told(
        self, item: Item, name: str, kind: str, alternatives: list[Alternative]
    ) -> None: ...
    def _choice(self, item: Item, name: str) -> None: ...
    def _on(self, item: Item) -> None: ...
    def _rounding(self, item: Item, value_name: str) -> None: ...
