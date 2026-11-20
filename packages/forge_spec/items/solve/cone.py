"""How the solver places a cone: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_numeric import scalar as fs

from forge_spec.draft import (
    EdgeSet,
    Item,
)
from forge_spec.geometry import (
    EPS,
    ConeFace,
    FlatFace,
    Vec,
    disc,
)
from forge_spec.items.solve._common import (
    _INDEX,
    _add,
    _bounds_round,
    _dir,
    _item_values,
    _length_of,
    _round_faces,
    _size,
    _with,
)
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.items.solve._common import Hollowing
    from forge_spec.placement import Layout


def cone_hollow(base: float, top: float, length: float, t: float, low: float, high: float) -> tuple[float, float, float]:
    """A hollowed cone's hollow along its axis (shell.md, "cone"): where it starts and ends, from the -end, and its slant.

    The side wall is ``t`` thick square to the side, so the hollow's radius at
    a height is the cone's there less ``t`` times the slant (the side's length
    over the cone's: :func:`hollow_radius`). It runs from ``low``, the -end's
    wall, to ``length - high``, the +end's.

    >>> start, end, slant = cone_hollow(20.0, 25.0, 60.0, 2.0, 3.0, 0.0)
    >>> round(start, 9), round(end, 9), round(hollow_radius(20.0, 25.0, 60.0, 2.0, slant, start), 6)
    (3.0, 60.0, 18.243068)
    """
    slant = fs.hypot(length, top - base) / length
    return low, length - high, slant


def hollow_radius(base: float, top: float, length: float, t: float, slant: float, s: float) -> float:
    """The hollow's radius ``s`` along a hollowed cone's axis from its -end: the cone's there less its side wall."""
    return base + (top - base) * s / length - t * slant


class Cone(SolveKind):
    key = "cone"

    rises_by = ("length",)
    round = True
    axial = True

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        return ("base_diameter",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        return (disc(max(_size(item, "diameter"), _size(item, "base_diameter")) / 2),)

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        length = _length_of(item, "length") or _size(item, "height")
        outer = (_length_of(item, "diameter") or _length_of(item, "outer_diameter")
                 or _size(item, "base_diameter")) / 2  # fmt: skip
        top = _length_of(item, "top_diameter")
        inner = _size(item, "inner_diameter") / 2
        # A cone wider at its top than its base is as wide as its top.
        lo, hi = _bounds_round(base, up, length, max(outer, (top or 0.0) / 2))
        layout.faces[key] = _round_faces(item, base, up, length, outer,
                                         None if top is None else top / 2, inner)  # fmt: skip
        # Its tapered side takes a hole, a boss or a post, round it and along it (item 3b's third step).
        top_r = outer if top is None else top / 2
        diameters = tuple((item.id, n) for n in ("base_diameter", "top_diameter") if item.get(n) is not None)
        lengths = tuple((item.id, n) for n in ("length", "height") if item.get(n) is not None)
        forward = up[0] == "+"
        layout.faces[key]["side"] = ConeFace(
            "side", up[1], base if forward else _add(base, _dir(up), length), length,
            outer if forward else top_r, top_r if forward else outer,
            None if host is None else ("start" if forward else "end"),
            radius_sources=diameters, length_sources=lengths, depth_sources=diameters + lengths)  # fmt: skip
        if "+end" not in layout.faces[key]:
            layout.close(
                key,
                "+end",
                "fault",
                f"{item.id} comes to a point; it has no +end face",
            )
        return lo, hi, "+end", {}

    def open_faces_allowed(self, item: Item) -> set[str]:
        return {"-end"} if _size(item, "top_diameter") <= EPS else {"+end", "-end"}

    def floor_fault(self, item: Item, outer: set[str], open_faces: set[str], floored: list[str],
                    shell: Item) -> str | None:  # fmt: skip
        if not floored:
            return (f"a floor is the wall opposite an opening, and {shell.id} has "
                    + ("no opening" if not open_faces else f"none with a wall opposite ({sorted(open_faces)})")
                    + ": leave the floor out")  # fmt: skip
        return None

    def hollow(self, item: Item, key: tuple[str, int], lo: Vec, hi: Vec, up: str, layout: Layout,
               fields: dict[str, str], h: Hollowing) -> None:  # fmt: skip
        """A hollowed cone (shell.md, "cone"): its hollow a cone of its own, its side wall ``thickness`` thick square to
        the side, each end's wall from that end (none where open, ``floor`` opposite an opening). Its ends take what an
        end takes, the wall under them; its side, the rim of an open end and the inside take nothing yet, its edges
        aren't rounded or bevelled yet, and a cone that comes to a point isn't hollowed yet."""
        shell_at, t = h.shell_at, h.thickness
        base, top, length = _size(item, "base_diameter") / 2, _size(item, "top_diameter") / 2, _size(item, "length")
        plus, minus = h.wall("+end", "-end"), h.wall("-end", "+end")
        if top <= EPS:
            # Its hollow would come to a point inside it, which face accounting can't yet tell either side of.
            layout.issue("unable", shell_at, f"Forge hollows a cone with a flat top, not yet {item.id}, which comes to "
                                             "a point")  # fmt: skip
            return
        start, end, slant = cone_hollow(base, top, length, t, minus, plus)
        a = hollow_radius(base, top, length, t, slant, start)
        b = hollow_radius(base, top, length, t, slant, end)
        if end - start <= EPS or a <= EPS or b <= EPS:
            layout.problem("cant", shell_at + pointer("thickness"), f"{t:g} mm walls leave no hollow inside {item.id}",
                           [h.thickness_value, h.floor_value,
                            *_item_values(item, "base_diameter", "top_diameter", "length")])  # fmt: skip
            return
        faces = layout.faces[key]
        for name, depth in (("+end", plus), ("-end", minus)):
            face = faces.get(name)
            if isinstance(face, FlatFace):
                faces[name] = _with(face, depth_below=depth, depth_sources=h.walls)
        layout.close(key, "side", "unable", f"{h.shell.id} hollows {item.id}: Forge doesn't place on a hollow cone's "
                                            "side yet")  # fmt: skip
        for n, other in enumerate(layout.items.values()):
            edges = other.get("edges")
            if isinstance(edges, EdgeSet) and edges.of == item.id:
                layout.issue("unable", pointer("items", n, "edges"),
                             f"{item.id} is hollow: Forge doesn't round or bevel a hollow cone's edges yet")  # fmt: skip
        k = _INDEX[up[1]]
        sign = 1.0 if up[0] == "+" else -1.0  # from the -end towards the +end
        minus_end = lo[k] if sign > 0 else hi[k]
        widest = max(a, b)
        middle = [(lo[i] + hi[i]) / 2 for i in range(3)]
        inner_lo = [middle[i] - widest for i in range(3)]
        inner_hi = [middle[i] + widest for i in range(3)]
        ends = sorted((minus_end + sign * start, minus_end + sign * end))
        inner_lo[k], inner_hi[k] = ends[0], ends[1]
        layout.cavities[key] = ((inner_lo[0], inner_lo[1], inner_lo[2]), (inner_hi[0], inner_hi[1], inner_hi[2]))

    def edges(self, which: str, up: str) -> list[tuple[str, str]]:
        rims = {"top": [("+end", "side")], "bottom": [("-end", "side")]}
        rims["both"] = rims["top"] + rims["bottom"]
        return rims.get(which, [])


ENTRY = Cone()
