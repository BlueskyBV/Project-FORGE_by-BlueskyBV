"""What the placement solver asks of a kind of item: the ``solve`` role's protocol (V2-stage4b-0b-inventory.md, 2.3).

Each kind's module answers for its own kind (moved from ``placement.py`` at
stage 4b.0b's step 3); what is here is the default the kinds fall to.
"Published" answers are given by the item another acts on: the hollowed
body, the rounded body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from forge_registry import reserved

from forge_spec.schema import KINDS, Category

if TYPE_CHECKING:
    from forge_spec.draft import Item
    from forge_spec.geometry import FlatFace, Part
    from forge_spec.items.solve._common import Hollowing
    from forge_spec.outline import Shape
    from forge_spec.placement import Instance, Layout

Vec = tuple[float, float, float]


class SolveKind:
    """One kind of item, as the solver places it."""

    #: The kind this entry is for.
    key = ""
    #: The fields it rises by from what it stands on, the first given.
    rises_by: tuple[str, ...] = ("height",)
    #: Made from an outline: an extrusion, a revolution.
    profiled = False
    #: Round: it stands on its -end, and rises along its axis.
    round = False
    #: It has an axis to choose (``axis``): a first body's points along it, a standing one's along its face's normal.
    axial = False

    @property
    def hollowable(self) -> bool:
        """Published: a shell may hollow it (its definition says so: shell.md)."""
        return KINDS[self.key].hollowable

    #: Hollow already, by its bore: no shell may hollow it.
    bored = False
    #: It hollows another (a shell).
    hollows = False
    #: It rounds another's edges (a fillet, a chamfer).
    rounding = False
    #: Made after everything else, if nothing made it earlier (roundings and threads).
    made_last = False
    #: Letters: it covers its ink's box, and isn't checked over openings or severing as a cut.
    lettered = False
    #: Its foot on a round side is round (a hole's, a boss's).
    round_foot = False
    #: A shell's inner faces of it are named by its own fields (a block's).
    shell_fields = False

    # ------------------------------------------------------------------
    # What it is to the part
    # ------------------------------------------------------------------
    @property
    def body(self) -> bool:
        return KINDS[self.key].category is Category.BODY

    @property
    def cut(self) -> bool:
        return KINDS[self.key].category is Category.CUT

    @property
    def adds(self) -> bool:
        """Whether it stands on what it is placed on (a boss, a post, a tab, a rib)."""
        return KINDS[self.key].category is Category.ADD

    @property
    def modifies(self) -> bool:
        """Whether it places nothing itself (a rounding, a shell, a thread)."""
        return KINDS[self.key].category is Category.MODIFY

    @property
    def solid(self) -> bool:
        """Whether it is material: a body or a standing item."""
        return KINDS[self.key].category in (Category.BODY, Category.ADD)

    @property
    def stands(self) -> bool:
        """Whether it stands where it is placed, with bounds and faces of its own: a body, a standing item, a region."""
        return KINDS[self.key].category in (
            Category.BODY,
            Category.ADD,
            Category.REGION,
        )

    @property
    def on_round_side(self) -> bool:
        """Whether it may go round a round side (a standing item; a hole)."""
        return self.adds

    # ------------------------------------------------------------------
    # Its own
    # ------------------------------------------------------------------
    def height(self, item: Item) -> tuple[float, str] | None:
        """How far it rises out of what it stands on, and the field."""
        from forge_spec.items.solve._common import _length_of

        for name in self.rises_by:
            value = _length_of(item, name)
            if value is not None:
                return value, name
        return None

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        """The fields its outline on its face comes from; with ``k``, only along that axis."""
        return ()

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        """Its outline on the face, centred on its position, in the face's axes."""
        return ()

    def covers(self, item: Item, layout: Layout, face: FlatFace) -> tuple[Part, ...]:
        """What it covers on a flat face, for its fit and what it meets: its outline."""
        return self.outline(item, layout, face.axes)

    def reaches(
        self, item: Item
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """How far a profiled body reaches back and forth along a face's two axes from the point it stands at."""
        return None

    def footing(self, item: Item) -> Shape | None:
        """What of a profiled body meets the face it stands on."""
        return None

    def turnable(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[float, float, float] | None:
        """Its outline on a flat face as a rounded rectangle about its point, before any turn: its half sizes along the
        face's two axes and its corners' radius; None for a kind ``place.turn`` doesn't turn (1b's first move)."""
        return None

    def check_shape(self, item: Item, at: str, layout: Layout) -> None:
        """What can't be true of its own sizes, wherever it is placed."""

    def resolve_diameter(self, item: Item, at: str, layout: Layout) -> None:
        """Its diameter, as the layout holds it, where it is given as a fit (a hole's)."""

    def first_up(self, item: Item, layout: Layout, at: str) -> str:
        """The way the first body rises from the origin: along its axis, assumed z (upright) where the brief doesn't say."""
        if not self.axial:
            return "+z"
        from forge_spec.items.solve._common import _choice_of

        axis = _choice_of(item, "axis")
        if axis is None:
            layout.assume(
                at, f"{item.id}: its axis is z (upright); the brief doesn't say"
            )
            axis = "z"
        return "+" + axis

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        """Its bounds and faces standing at ``base``, rising along ``up``: its bounds, its far face, and the field each axis is."""
        layout.faces[key] = {}
        return base, base, "", {}

    def far_face(self, up: str) -> str:
        """Its far face, standing round a side: the only one that takes anything there, for now."""
        return up

    def floor(self, item: Item, copy: Instance, face: FlatFace, material: float, key: tuple[str, int],
              layout: Layout) -> None:  # fmt: skip
        """A floor others can go into (a pocket's)."""

    def embossed(self, item: Item) -> bool:
        """Whether it stands out of its face (raised letters), not into it."""
        return False

    # ------------------------------------------------------------------
    # Published: asked of the item another acts on
    # ------------------------------------------------------------------
    def open_faces_allowed(self, item: Item) -> set[str]:
        """The faces a shell may leave open."""
        return set()

    def floor_fault(
        self,
        item: Item,
        outer: set[str],
        open_faces: set[str],
        floored: list[str],
        shell: Item,
    ) -> str | None:
        """Why a shell of it can't have the floor it gives, if it can't."""
        return None

    def hollow(self, item: Item, key: tuple[str, int], lo: Vec, hi: Vec, up: str, layout: Layout,
               fields: dict[str, str], h: Hollowing) -> None:  # fmt: skip
        """Its hollow: its walls as the material, its cavity and its inner faces."""

    def edges(self, which: str, up: str) -> list[tuple[str, str]]:
        """Each edge of its edge set ``which``, as the two faces it lies between (docs/definitions/edges.md)."""
        return []

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("4b.0d2")
    def acts_on(self, item: Item) -> tuple[str, ...]:
        """The items it acts on, by id (item 11): the order's graph, as the spec infers it and shows it at confirmation."""
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
        """A selection rule's faces or edges of it (item 12), resolved before confirmation and stored as explicit face or edge definitions (role pairs and sample points)."""
        raise NotImplementedError

    @reserved("4b.0d4")
    def expand(self, item: Item) -> tuple[Item, ...]:
        """A composite's ordinary items, expanded before confirmation and shown expanded (item 20)."""
        raise NotImplementedError

    @reserved("4b.0d4")
    def tables_read(self, item: Item) -> tuple[str, ...]:
        """The standard and material tables, files and editions it reads, locked in the confirmed spec's hash (item 27)."""
        raise NotImplementedError

    @reserved("4b.0d4")
    def proposals(self, item: Item) -> dict[str, Any]:
        """What it resolves before confirmation, stored as explicit geometry or values and shown (item 28)."""
        raise NotImplementedError

    @reserved("stage 8")
    def interfaces(self, item: Item) -> tuple[Any, ...]:
        """The interfaces it publishes in the spec for mates and actuators (item 16): section 4's slot, judged by stage 8's checks in ``forge_checks``."""
        raise NotImplementedError
