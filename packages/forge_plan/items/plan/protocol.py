"""What the planner asks of a kind of item: the ``plan`` role's protocol (V2-stage4b-0b-inventory.md, 2.1).

Each kind's module answers for its own kind (moved from ``planner.py``,
``tools.py``, ``edges.py``, ``shells.py``, ``threads.py`` and ``regions.py``
at stage 4b.0b's step 3); what is here is the default the kinds fall to.
A body's, a cut's and a standing feature's ways of being made into tools
are their families' (``_families.py``). "Published" answers are given by
the item another acts on: the rounded, hollowed, threaded or hosting item.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from forge_registry import reserved
from forge_spec.schema import KINDS, Category

from forge_plan.errors import PlanError

if TYPE_CHECKING:
    from forge_spec.draft import Item
    from forge_spec.geometry import FlatFace, Part, SideFace
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


class PlanKind:
    """One kind of item, as the planner writes it."""

    #: The kind this entry is for.
    key = ""
    #: Its copies are made into tools, joined to or taken from the part (a body's, a cut's, a standing feature's).
    made_into_tools = False
    #: Its tools are taken from the part, not joined to it (a cut's).
    taken = False
    #: It rounds another's edges; ``bevel``: by a chamfer, not a fillet.
    rounding = False
    bevel = False
    #: It hollows another (a shell); it is letters (a text); it threads a rod (a thread).
    hollows = False
    lettered = False
    threads = False
    #: Published: a thread may go on it, ``rod_length`` its threaded length's field.
    threadable = False
    rod_length = "length"
    #: Published: its bore runs its whole length, and past its ends there is nothing (a tube's).
    bored = False
    #: Published: a cut whose rims a rounding names (a hole's, a slot's, a pocket's); one with a floor (a pocket's).
    rimmed_cut = False
    floored = False
    #: Published: a box whose bottom edges a rounding may name, and all twelve (a block's).
    bottom_edges = False
    #: It goes into a round side (a hole).
    goes_round_side = False

    @property
    def planned(self) -> bool:
        """Whether the planner writes it at all (a region is designed later, by stage 5)."""
        return KINDS[self.key].category is not Category.REGION

    # ------------------------------------------------------------------
    # Its own
    # ------------------------------------------------------------------
    def tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, how: str
    ) -> list[str]:
        """One copy's tool pieces, made ``how``."""
        raise PlanError(f"a {item.kind} isn't compiled", item=item.id)

    def other_construction(
        self, ctx: Context, item: Item
    ) -> tuple[str, str, Any] | None:
        """Its construction proven equal to its definition's, if any: (how, proof, whether it applies)."""
        return None

    def into_round_side(self, ctx: Context, item: Item) -> bool:
        """Whether it goes into a round side from outside, its definition's tool touching the side along a line (5.2)."""
        return False

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        """One copy of a body."""
        raise PlanError(f"a {item.kind} body isn't compiled", item=item.id)

    def cut_tool(self, chain: Chain, ctx: Context, item: Item, copy: Instance, face: FlatFace | SideFace,
                 mouth: float, far: float) -> list[str]:  # fmt: skip
        """One copy of a cut: its tool's pieces."""
        raise PlanError(f"a {item.kind} cut isn't compiled", item=item.id)

    def outline_of(
        self, item: Item, face: FlatFace
    ) -> tuple[tuple[float, float], tuple[Part, ...]]:
        """A cut's half sizes along the face's axes, and its outline's parts."""
        raise PlanError(f"a {item.kind} has no outline on a face", item=item.id)

    def air_outline(
        self, ctx: Context, item: Item, face: FlatFace
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[Part, ...]]:
        """A cut's half sizes past its mouth and past its far side, and the outline its depth is measured by (5.2)."""
        halves, parts = self.outline_of(item, face)
        return halves, halves, parts

    def section(
        self, item: Item, axes: tuple[str, str]
    ) -> tuple[dict[str, float], float]:
        """A box-like standing item's half sizes across its direction, by frame axis, and its height."""
        raise PlanError(f"a {item.kind} has no box section", item=item.id)

    def standing_tool(
        self, chain: Chain, item: Item, copy: Instance, behind: float
    ) -> str:
        """One copy of a standing feature on a flat face, sunk ``behind`` into what it stands on."""
        from forge_plan.items.plan._tools import _axes, _box_tool, _span_box, _up
        from forge_plan.write import Box

        k, w, u = copy.index, copy.origin, copy.normal
        halves, height = self.section(item, _axes(copy))
        lo, hi = _span_box(w, u, -behind, height, halves)
        tool = _box_tool(chain, item, k, lo, hi, _up(u))
        chain.add_box(Box(*_span_box(w, u, 0.0, height, halves), item.id, k))
        return tool

    def sinkable(self, item: Item) -> bool:
        """Whether its tool may be sunk into what it stands on (5.3)."""
        return True

    def sink_footprint(
        self, item: Item, face: FlatFace, copy: Instance
    ) -> tuple[tuple[Part, ...], dict[str, float]]:
        """Its foot's outline on the face, and its half sizes along the face's axes: its section's."""
        from forge_spec.geometry import rect

        from forge_plan.items.plan._tools import _axes

        halves, _ = self.section(item, _axes(copy))
        return (rect(halves[face.axes[0]], halves[face.axes[1]]),), halves

    def round_side_prism(
        self, chain: Chain, item: Item, copy: Instance, reach: float
    ) -> tuple[str, Vec, Vec]:
        """A standing feature round a side: its section's prism from ``reach`` behind its point out to its height, and its box."""
        from forge_plan.items.plan._tools import _axes, _box_faces, _id, _span_box

        k, w, u = copy.index, copy.origin, copy.normal
        halves, h = self.section(item, _axes(copy))
        lo_p, hi_p = _span_box(w, u, -reach, h, halves)
        prism = chain.box(_id(item.id, k, "box"), lo_p, hi_p, item=item.id)
        _box_faces(chain, item.id, k, prism)
        lo, hi = _span_box(w, u, -reach, h, halves)
        return prism, lo, hi

    def widest(self, ctx: Context, item: Item) -> tuple[float, float]:
        """A hole's radius and its widest radius."""
        raise PlanError(f"a {item.kind} isn't a hole", item=item.id)

    # ------------------------------------------------------------------
    # Published: asked of the item another acts on
    # ------------------------------------------------------------------
    def box_like(self, item: Item) -> bool:
        """Whether the item is a box: a block, a post, a rib or a straight-ended tab."""
        return False

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        """A rounded item's own edges ``which`` (not a joint), as queries; a box's are the planner's own."""
        raise PlanError(f"a {target.kind}'s edges aren't compiled", item=target.id)

    def rim_radius(self, target: Item, end: str, side: str) -> float:
        """A round item's rim's radius at ``end``, round ``side``: a bore's, else its own."""
        from forge_plan.items.plan._edges import _mm

        if side == "bore":
            return _mm(target, "inner_diameter") / 2
        return self.outer_rim(target, end)

    def outer_rim(self, target: Item, end: str) -> float:
        from forge_plan.items.plan._edges import _mm

        return _mm(target, "diameter") / 2

    def pieces(self, cut: Item) -> int:
        """How many lines and arcs a cut's outline is made of (each may be split once more where a seam crosses it)."""
        corner = cut.get("corner_radius")
        return 8 if corner is not None else 4

    def hollow_tool(
        self,
        chain: Chain,
        shell: Item,
        body: Item,
        copy: Instance,
        cavity: tuple[Vec, Vec] | None,
    ) -> str:
        """One copy's hollow: a tool to take from the part, its inside faces named on the body."""
        raise PlanError(f"a {body.kind} can't be hollowed", item=shell.id)

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("4b.0d2")
    def acts_on(self, item: Item) -> tuple[str, ...]:
        """The items it acts on, by id (item 11): the order's graph, as the planner orders its constructions by it."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def order_rank(self) -> int:
        """Its rank in the canonical order (item 11), the default inferred and shown at confirmation."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def as_of(self, item: Item) -> str | None:
        """The item after which stood the shape it acts on, where it says (item 11's ``as_of``)."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def face_roles(self, item: Item) -> tuple[str, ...]:
        """Its faces' roles (item 12): how they split under cuts and merge across tangent joins, a copy's by its pattern coordinates."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def edge_roles(self, item: Item) -> tuple[tuple[str, str], ...]:
        """Its edges' roles, each the two face roles that meet there (item 12)."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def select(self, item: Item, rule: Any) -> Any:
        """A selection rule's faces or edges of it (item 12), as the ForgeIR queries the compiler turns it into."""
        raise NotImplementedError
