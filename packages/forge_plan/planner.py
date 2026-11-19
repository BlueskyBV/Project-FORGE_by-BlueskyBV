"""The plan: every item's constructions, in the order the part is made (docs/V2-stage4.md, 4.1).

:func:`plan` takes a confirmed spec; :func:`preview_plan` a draft's report,
for the preview. Each planned item has its constructions in a fixed order,
the first its definition's own (section 4) and the rest proven equal to it
(section 5). :meth:`Plan.written` replays every item's chosen construction
into a fresh chain and gives the document, which is a pure function of the
spec and the choice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from forge_ir.v2 import DocumentV2
from forge_spec.checks import SpecReport
from forge_spec.draft import Choice, EdgeSet, Item, On, PartSpec, UpTo
from forge_spec.ends import ThroughNext, end_of
from forge_spec.geometry import FlatFace
from forge_spec.lock import ConfirmedSpec
from forge_spec.placement import Instance, Layout, placed_spec
from forge_spec.values import Value

from .edges import edge_reference
from .errors import GapError, PlanError
from .items.plan import PLAN
from .letters import letters_step
from .moved import moved_tools
from .regions import (
    Stretch,
    box_like,
    follows_a_rounding,
    joint_stretches,
    made_as_regions,
    on_flat,
    own_stretches,
    region_applies,
)
from .shells import hollow_tool
from .threads import thread_step
from .tools import (
    Context,
    early_applies,
)
from .write import Box, Chain, Done, Early, length

__all__ = [
    "Construction",
    "Gap",
    "Plan",
    "PlannedItem",
    "Written",
    "plan",
    "preview_plan",
]


@dataclass(frozen=True)
class Construction:
    """One way to make an item: its steps, written into the chain, and the section that proves it equal to the first."""

    name: str
    proof: str
    write: Callable[[Chain], None]
    #: Whether its proof holds on the chain written so far (the definition's always does).
    applies: Callable[[Chain], bool] = field(default=lambda chain: True)
    #: What it asks of the chain before any item is written, when chosen (a rounding made early, 5.5).
    prepare: Callable[[Chain], None] | None = None


@dataclass(frozen=True)
class PlannedItem:
    key: str
    item: str
    kind: str
    constructions: tuple[Construction, ...]


@dataclass(frozen=True)
class Gap:
    """An item no construction is written for, and why; the run ends UNABLE for it."""

    item: str
    reason: str


@dataclass(frozen=True)
class Written:
    """One replay of the plan: the document, the planned item each step builds, the chain's names, and how each item was made."""

    document: DocumentV2
    owners: Mapping[str, str]
    chain: Chain
    #: Each planned item's construction as written, by index: the one chosen, else its first whose proof holds.
    made: Mapping[str, int] = field(default_factory=dict)
    #: The same, by name.
    made_by: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    """Every item's constructions, in the order the part is made, and the gaps."""

    name: str
    document_id: str
    spec_digest: str | None
    items: tuple[PlannedItem, ...]
    gaps: tuple[Gap, ...]

    def planned(self, key: str) -> PlannedItem:
        for found in self.items:
            if found.key == key:
                return found
        raise KeyError(key)

    def chosen(self, choice: Mapping[str, int], key: str) -> Construction:
        """The construction ``choice`` names for a planned item, its first where it names none.

        What is written for an item ``choice`` names none for is its first
        construction whose proof holds (:meth:`written`): the first itself,
        but for a hole into a round side whose carrying doesn't hold.
        """
        planned = self.planned(key)
        index = choice.get(key, 0)
        if not 0 <= index < len(planned.constructions):
            raise PlanError(f"it has no construction {index}", item=planned.item)
        return planned.constructions[index]

    def _replay(
        self, choice: Mapping[str, int], until: str | None = None
    ) -> tuple[Chain, dict[str, int]]:
        """The chain with each item's construction written, up to (not including) ``until``, and which each was.

        An item ``choice`` names is made by that construction, whose proof
        must hold on the part made so far; any other by its first whose proof
        holds there. That is its definition's, but for a hole into a round
        side from outside, whose carried construction goes first where its
        proof holds and its definition's where it doesn't (section 5;
        generated part 4,935: a hole through a tube hung in a closed hollow,
        no air proven clear past it).
        """
        chain = Chain()
        made: dict[str, int] = {}
        for planned in self.items:
            prepare = self.chosen(choice, planned.key).prepare
            if prepare is not None:
                prepare(chain)
        for planned in self.items:
            if planned.key == until:
                return chain, made
            if planned.key in choice:
                index = choice[planned.key]
                construction = self.chosen(choice, planned.key)
                if not construction.applies(chain):
                    raise PlanError(f"its construction {construction.name!r} doesn't apply here",
                                    item=planned.item)  # fmt: skip
            else:
                index = _first_holding(planned, chain)
                construction = planned.constructions[index]
            made[planned.key] = index
            chain.planning = planned.key
            construction.write(chain)
        if until is not None:
            raise KeyError(until)
        return chain, made

    def written(self, choice: Mapping[str, int] | None = None) -> Written:
        """The document with each planned item's chosen construction (by default its first whose proof holds)."""
        chain, made = self._replay(choice or {})
        document = chain.document(document_id=self.document_id, name=self.name)
        names = {
            planned.key: planned.constructions[made[planned.key]].name
            for planned in self.items
        }
        return Written(document, dict(chain.owners), chain, made, names)

    def document(self, choice: Mapping[str, int] | None = None) -> DocumentV2:
        return self.written(choice).document

    def applying(self, choice: Mapping[str, int], key: str) -> list[int]:
        """Every construction of a planned item whose proof holds on the part made so far with ``choice``, in order."""
        planned = self.planned(key)
        chain, _ = self._replay(choice, until=key)
        return [
            index
            for index, construction in enumerate(planned.constructions)
            if construction.applies(chain)
        ]

    def next_choice(self, choice: Mapping[str, int], key: str) -> int | None:
        """The next construction of a planned item, after the one it is made by with ``choice``, whose proof holds, or None."""
        holding = self.applying(choice, key)
        current = choice.get(key, holding[0] if holding else -1)
        return next((index for index in holding if index > current), None)


def _first_holding(planned: PlannedItem, chain: Chain) -> int:
    """A planned item's first construction whose proof holds on the part made so far."""
    for index, construction in enumerate(planned.constructions):
        if construction.applies(chain):
            return index
    raise PlanError("none of its constructions applies here", item=planned.item)


# ----------------------------------------------------------------------
# Constructions per kind
# ----------------------------------------------------------------------
def _tools(
    ctx: Context, item: Item, how: str
) -> Callable[[Chain, Instance], list[str]]:
    """One copy's tool pieces, made ``how``: as the definition makes it, carried into the air (5.2), sunk (5.3) or a dome cut (5.4)."""

    def made(chain: Chain, copy: Instance) -> list[str]:
        if copy.frame is not None:
            return moved_tools(chain, ctx, item, copy, how)
        return PLAN[item.kind].tool(chain, ctx, item, copy, how)

    return made


def _made(ctx: Context, item: Item, how: str, *, one_by_one: bool, proof: str,
          applies: Callable[[Chain], bool] | None = None) -> Construction:  # fmt: skip
    """Every copy's tool, joined to or taken from the part in one step (4.2), or one copy at a time (5.1)."""
    copies = ctx.layout.instances.get(item.id, [])
    tools = _tools(ctx, item, how)
    taken = PLAN[item.kind].taken

    def write(chain: Chain) -> None:
        key = chain.planning
        if one_by_one:
            for copy in copies:
                found = tools(chain, copy)
                (chain.take if taken else chain.join)(
                    key, found, item=item.id, copy=copy.index
                )
            return
        found = [piece for copy in copies for piece in tools(chain, copy)]
        (chain.take if taken else chain.join)(key, found, item=item.id)

    name = how + (" one by one" if one_by_one else "")
    return Construction(name, proof, write, applies or (lambda chain: True))


def _item_constructions(ctx: Context, item: Item) -> tuple[Construction, ...]:
    """A body's, cut's or standing feature's constructions: its definition's first, then those proven equal (section 5).

    A hole into a round side from outside has the carried construction first
    (5.2): its definition's tool touches the side along a line at its mouth,
    which OpenCascade may refuse or cut wrong without a word; and a cut
    through the next face, whose definition's end touches the face it first
    comes out of (at a point, out of a face at a slant: generated part 4944,
    OpenCascade leaving a face across the hole's end without a word). Where
    carrying doesn't hold on the part made so far, its definition's is made
    instead (:meth:`Plan.written`). A hole's last is its definition's with
    its round tools turned about their axes (5.7).
    """
    several = len(ctx.layout.instances.get(item.id, [])) > 1
    found = [_made(ctx, item, "flush", one_by_one=False, proof="4.2")]
    other: tuple[str, str, Callable[[Chain], bool] | None] | None = PLAN[
        item.kind
    ].other_construction(ctx, item)
    if other is not None:
        found.append(
            _made(
                ctx, item, other[0], one_by_one=False, proof=other[1], applies=other[2]
            )
        )
    if several:
        found.append(_made(ctx, item, "flush", one_by_one=True, proof="5.1"))
        if other is not None:
            found.append(
                _made(
                    ctx,
                    item,
                    other[0],
                    one_by_one=True,
                    proof=f"5.1, {other[1]}",
                    applies=other[2],
                )
            )
    if PLAN[item.kind].into_round_side(ctx, item) or isinstance(end_of(item), ThroughNext):
        # Carried first, the definition's after: each pair of all at once and one by one swapped. Through the next face
        # too: its definition's end touches the face it first comes out of, by what that means.
        found = [found[i ^ 1] for i in range(len(found))]
    if PLAN[item.kind].goes_round_side:  # a hole: its definition's, its round tools turned about their axes, last
        found.append(_turned(found[0] if found[0].name == "flush" else found[1]))
    return tuple(found)


def _turned(made: Construction) -> Construction:
    """A construction with every cylinder and cone it makes turned a quarter turn about its own axis (5.7): the same
    tools, their seams elsewhere."""

    def write(chain: Chain) -> None:
        chain.turning = True
        try:
            made.write(chain)
        finally:
            chain.turning = False

    return Construction(f"{made.name} turned", f"{made.proof}, 5.7", write, made.applies)


def _rounding(ctx: Context, item: Item, part: str | None) -> Construction:
    """The definition's own: one fillet or chamfer of every edge it names, on the part made so far (4.7)."""
    bevel = PLAN[item.kind].bevel
    size_field = "size" if bevel else "radius"
    value = item.get(size_field)
    if not isinstance(value, Value):
        raise PlanError(f"its {size_field} is no size", item=item.id)
    mm = value.made_in("mm")
    items = {i.id: i for i in ctx.spec.items}

    def write(chain: Chain) -> None:
        if chain.head is None:
            raise PlanError("a rounding before any body", item=item.id)
        reference, named = edge_reference(chain, item, items=items, copies=ctx.layout.instances,
                                          shells=ctx.layout.shells, part=part, faces=ctx.layout.faces)  # fmt: skip
        op, name = ("chamfer", "distance") if bevel else ("fillet", "radius")
        step = chain.step(f"{chain.planning}.{op}", op, {name: length(mm), "edges": reference},
                          item=item.id, inputs=(chain.head,))  # fmt: skip
        chain.head = step
        for key, pairs in named.items():
            chain.rounded.setdefault(key, []).append(
                Done(step, bevel, mm, pairs, rounding=item.id)
            )
        for query in reference["queries"]:
            lo, hi = query["where"]["within"]
            chain.note(Box((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]), item.id, -1))

    return Construction("on_the_part", "4.7", write)


def _early(ctx: Context, item: Item, part: str | None) -> Construction | None:
    """A rounding of a box-like item's vertical edges made early, on its own tool before it is joined (5.5); None where not offered."""
    edges = item.get("edges")
    if not isinstance(edges, EdgeSet) or edges.which != "vertical" or part is not None:
        return None
    target = ctx.items.get(edges.of)
    if target is None or target.id in ctx.layout.shells:
        return None
    if not PLAN[target.kind].box_like(target):
        return None
    copies = ctx.layout.instances.get(target.id, [])
    if any(
        copy.host is not None and not isinstance(ctx.face(copy), FlatFace)
        for copy in copies
    ):
        return None
    if any(copy.direction is not None for copy in copies):
        return None  # leaning: its tool is made leaned, its long edges rounded on the part (generated part 596)
    bevel = PLAN[item.kind].bevel
    value = item.get("size" if bevel else "radius")
    if not isinstance(value, Value):
        return None
    mm = value.made_in("mm")

    def prepare(chain: Chain) -> None:
        chain.early.setdefault(target.id, []).append(
            Early(item.id, "vertical", bevel, mm)
        )

    def write(chain: Chain) -> None:
        for copy in copies:
            if (item.id, copy.index) not in chain.made_early:
                raise PlanError(
                    f"its rounding of {target.id}#{copy.index} wasn't made early",
                    item=item.id,
                )
            chain.note(
                next(
                    b
                    for b in chain.added
                    if (b.item, b.copy) == (target.id, copy.index)
                )
            )

    return Construction(
        "early",
        "5.5",
        write,
        lambda chain: early_applies(chain, target, copies, mm, item.id),
        prepare,
    )


def _regions(ctx: Context, item: Item, part: str | None) -> Construction | None:
    """A rounding made as its regions (5.6): of a box-like item's own edges, or of the joint of one standing on a rectangular face; None where not offered."""
    edges = item.get("edges")
    if not isinstance(edges, EdgeSet) or part is not None:
        return None
    bevel = PLAN[item.kind].bevel
    value = item.get("size" if bevel else "radius")
    if not isinstance(value, Value):
        return None
    size = value.made_in("mm")
    target = ctx.items.get(edges.of)
    if target is None:
        return None
    instances = ctx.layout.instances
    if any(copy.direction is not None for copy in instances.get(target.id, ())):
        return None  # leaning: its regions aren't the box round it; rounded on the part
    hollowed = set(ctx.layout.shells)
    pairs: list[tuple[Instance, FlatFace | None]] = []
    if edges.which == "joint":
        meets = ctx.items.get(edges.where_meets or "")
        if meets is None:
            return None
        standing = next((s for s, h in ((target, meets), (meets, target))
                         if any(c.host is not None and c.host[0] == h.id for c in instances.get(s.id, ()))), None)  # fmt: skip
        if (
            standing is None
            or not box_like(standing)
            or {standing.id, meets.id, target.id} & hollowed
            or any(copy.direction is not None for copy in instances.get(standing.id, ()))
        ):
            return None
        host_id = meets.id if standing is target else target.id
        for copy in instances.get(standing.id, []):
            if copy.host is None or copy.host[0] != host_id:
                continue
            face = on_flat(ctx.face(copy))
            if face is None:
                return None
            pairs.append((copy, face))
        target = standing
    else:
        if not box_like(target) or target.id in hollowed:
            return None
        for copy in instances.get(target.id, []):
            if copy.host is not None and not isinstance(ctx.face(copy), FlatFace):
                return None
            pairs.append((copy, None))
    if not pairs:
        return None
    which = edges.which
    owner = target

    def stretches(chain: Chain) -> dict[tuple[str, int], list[Stretch]]:
        found: dict[tuple[str, int], list[Stretch]] = {}
        for copy, face in pairs:
            key = (owner.id, copy.index)
            if face is not None:
                found[key] = joint_stretches(chain, owner, copy, face)
            else:
                found[key] = own_stretches(chain, owner, copy, which)
        return found

    def applies(chain: Chain) -> bool:
        found = stretches(chain)
        for copy, face in pairs:
            if face is None and follows_a_rounding(chain, owner, copy, which):
                return False
            host = (
                (copy.host[0], copy.host[1])
                if face is not None and copy.host is not None
                else None
            )
            if not region_applies(
                chain,
                found[(owner.id, copy.index)],
                size,
                own=(owner.id, copy.index),
                host=host,
            ):
                return False
        return True

    def write(chain: Chain) -> None:
        made_as_regions(chain, item, chain.planning, stretches(chain), size, bevel)

    return Construction("regions", "5.6", write, applies)


def _end(item: Item) -> str | None:
    value = item.get("end")
    return value.value if isinstance(value, Choice) else None


def _shell(ctx: Context, item: Item) -> Construction:
    """The hollow of each copy of its body, taken from the part made so far (4.8)."""
    of = item.get("of")
    body = next((i for i in ctx.spec.items if i.id == of), None)
    if body is None:
        raise PlanError(f"it hollows {of!r}, which the spec hasn't", item=item.id)

    def write(chain: Chain) -> None:
        tools = [hollow_tool(chain, item, body, copy, ctx.layout.cavities.get((body.id, copy.index)))
                 for copy in ctx.layout.instances.get(body.id, [])]  # fmt: skip
        chain.take(chain.planning, tools, item=item.id)

    return Construction("hollow", "4.8", write)


def _letters(ctx: Context, item: Item) -> Construction:
    """Every copy's letters, engraved into or embossed on the part made so far: a ``text`` step each (7.1)."""

    def write(chain: Chain) -> None:
        for copy in ctx.layout.instances.get(item.id, []):
            letters_step(chain, ctx, item, copy)

    return Construction("letters", "7.1", write)


def _thread(ctx: Context, item: Item) -> Construction:
    """The thread on every copy of its rod, cut into the part made so far: a ``thread`` step each (7.2)."""

    def write(chain: Chain) -> None:
        for copy in ctx.layout.instances.get(str(item.get("of")), []):
            thread_step(chain, ctx, item, copy)

    return Construction("thread", "7.2", write)


def _constructions(
    ctx: Context, item: Item, part: str | None
) -> tuple[Construction, ...]:
    entry = PLAN[item.kind]
    if entry.made_into_tools:
        return _item_constructions(ctx, item)
    if entry.rounding:
        others = (_early(ctx, item, part), _regions(ctx, item, part))
        return (_rounding(ctx, item, part), *(c for c in others if c is not None))
    if entry.hollows:
        return (_shell(ctx, item),)
    if entry.lettered:
        return (_letters(ctx, item),)
    if entry.threads:
        return (_thread(ctx, item),)
    raise GapError(f"a {item.kind} isn't compiled yet", item=item.id)


# ----------------------------------------------------------------------
# Planning
# ----------------------------------------------------------------------
def _parts(spec: PartSpec, layout: Layout) -> list[tuple[str, str, str | None]]:
    """Each item in the order the part is made, as (key, item, part).

    A rounding of a hollowed body made in two places (frame.md, "The
    order") is two planned items: its edges bordering no open face before
    the hollow (``"before"``), those bordering one after it (``"after"``).
    """
    position = {item_id: n for n, item_id in enumerate(layout.order)}
    seen: dict[str, int] = {}
    found: list[tuple[str, str, str | None]] = []
    items = {item.id: item for item in spec.items}
    for item_id in layout.order:
        seen[item_id] = seen.get(item_id, 0) + 1
        item = items[item_id]
        part: str | None = None
        edges = item.get("edges")
        target = getattr(edges, "of", None)
        if (
            PLAN[item.kind].rounding
            and target in layout.shells
            and getattr(edges, "which", "") != "joint"
        ):
            shell = layout.shells[target].id
            twice = layout.order.count(item_id) == 2
            if twice:
                part = "before" if seen[item_id] == 1 else "after"
            else:
                part = "before" if position[item_id] < position[shell] else "after"
        key = item_id if part is None else f"{item_id}-{part}"
        found.append((key, item_id, part))
    return found


def _plan(
    spec: PartSpec, layout: Layout, *, digest: str | None, gaps: tuple[Gap, ...] = ()
) -> Plan:
    spec = placed_spec(spec, layout)  # each item as placed: along its face's axes as the part names them, turned with it
    items = {item.id: item for item in spec.items}
    ctx = Context(spec, layout)
    skipped = {gap.item: gap.reason for gap in gaps}
    planned: list[PlannedItem] = []
    trial = Chain()
    for key, item_id, part in _parts(spec, layout):
        if item_id in skipped:
            continue
        item = items[item_id]
        # Written once now: an item no construction can be written for is a gap (4.9), and so is
        # one that depends on a gap; any other refusal is the compiler's to report.
        trial.planning = key
        try:
            candidate = PlannedItem(
                key, item_id, item.kind, _constructions(ctx, item, part)
            )
            candidate.constructions[0].write(trial)
        except GapError as why:
            skipped[item_id] = why.message
            continue
        except PlanError as why:
            if skipped and _depends_on(item) & set(skipped):
                skipped[item_id] = (
                    f"it depends on {sorted(_depends_on(item) & set(skipped))[0]}, which isn't built"
                )
                continue
            raise PlanError(why.message, item=why.item or item_id, at=why.at) from None
        planned.append(candidate)
    found = tuple(Gap(item, reason) for item, reason in skipped.items())
    return Plan(spec.name, (digest or "draft")[:16], digest, tuple(planned), found)


def plan(confirmed: ConfirmedSpec) -> Plan:
    """The plan of a confirmed spec: locked, its layout settled, every item determinate but its gaps."""
    confirmed.check()
    layout = confirmed.layout
    if layout.issues:
        first = layout.issues[0]
        raise PlanError(f"the layout has an issue left: {first.message}", at=first.at)
    gaps = tuple(Gap(item.id, "a region is designed later, by the construction agent (stage 5)")
                 for item in confirmed.spec.items if not PLAN[item.kind].planned)  # fmt: skip
    return _plan(confirmed.spec, layout, digest=confirmed.digest, gaps=gaps)


def preview_plan(report: SpecReport) -> Plan:
    """A draft's plan, for the preview: an item with an issue, and all that depends on it, is a gap."""
    if report.spec is None or report.layout is None:
        raise PlanError("the draft has no spec or layout to preview")
    spec, layout = report.spec, report.layout
    gaps: dict[str, str] = {}
    for item in spec.items:
        if not PLAN[item.kind].planned:
            gaps[item.id] = "a region is designed later"
        elif item.id in layout.unplaced:
            gaps[item.id] = "not placed"
    for problem in report.problems:
        index = _item_index(problem.at)
        if index is not None and index < len(spec.items):
            gaps.setdefault(spec.items[index].id, problem.message)
    changed = True
    while (
        changed
    ):  # what stands on, is cut into, rounds, hollows or threads a gap is one too
        changed = False
        for item in spec.items:
            if item.id in gaps:
                continue
            # In name order, as _plan's reason: a set's own order is the hash seed's (V2-stage4b-0b.md, 6.1).
            for depends in sorted(_depends_on(item)):
                if depends in gaps:
                    gaps[item.id] = f"it depends on {depends}, which can't be previewed"
                    changed = True
                    break
    return _plan(
        spec, layout, digest=None, gaps=tuple(Gap(i, why) for i, why in gaps.items())
    )


def _item_index(at: str) -> int | None:
    parts = at.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "items" and parts[1].isdigit():
        return int(parts[1])
    return None


def _depends_on(item: Item) -> set[str]:
    found: set[str] = set()
    on = item.get("on")
    if isinstance(on, On):
        found.add(on.item)
    of = item.get("of")
    if isinstance(of, str):
        found.add(of)
    edges = item.get("edges")
    for name in ("of", "where_meets"):
        value = getattr(edges, name, None)
        if isinstance(value, str):
            found.add(value)
    place = item.get("place")
    concentric = getattr(place, "concentric", None)
    if isinstance(concentric, str):
        found.add(concentric)
    depth = item.get("depth")
    if isinstance(depth, UpTo):  # a cut up to a face goes as deep as that face is (item 2b's first step)
        found.add(depth.face.item)
    return found
