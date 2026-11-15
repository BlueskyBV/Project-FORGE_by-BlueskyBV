"""How a body's, a cut's and a standing feature's copies are made into tools: the ``plan`` role's families (a leaf: it imports neither the kinds' modules nor the program).

Moved from ``planner.py``'s ``_tools`` and ``_item_constructions`` at stage
4b.0b's step 3: each family makes its kinds' copies the same way, through
the planner's context, and offers the same construction proven equal to
its definition's (V2-stage4.md, 5.2, 5.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from forge_plan.items.plan.protocol import PlanKind

if TYPE_CHECKING:
    from forge_spec.draft import Item
    from forge_spec.placement import Instance

    from forge_plan.tools import Context
    from forge_plan.write import Chain


class BodyPlan(PlanKind):
    """A body: one tool a copy, as the definition makes it (a dome may be cut, 5.4)."""

    made_into_tools = True

    def tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, how: str
    ) -> list[str]:
        return [self.body_tool(chain, ctx, item, copy, how == "dome_cut")]


class CutPlan(PlanKind):
    """A cut: its tool taken from the part, carried into the air past its mouth and far side where that holds (5.2)."""

    made_into_tools = True
    taken = True
    rimmed_cut = True

    def tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, how: str
    ) -> list[str]:
        carry = ctx.carried(chain, item, copy) if how == "carried" else (False, False)
        return ctx.cut_tool(chain, item, copy, carry)

    def other_construction(
        self, ctx: Context, item: Item
    ) -> tuple[str, str, Any] | None:
        """Carried into the air (5.2): offered where any copy's tool can be carried, else the definition's again."""
        copies = ctx.layout.instances.get(item.id, [])

        def applies(chain: Chain) -> bool:
            return any(any(ctx.carried(chain, item, copy)) for copy in copies)

        return ("carried", "5.2", applies)


class StandingPlan(PlanKind):
    """A standing feature: joined to what it stands on, sunk into it where that holds (5.3)."""

    made_into_tools = True

    def tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, how: str
    ) -> list[str]:
        return [ctx.standing_tool(chain, item, copy, how == "sunk")]

    def other_construction(
        self, ctx: Context, item: Item
    ) -> tuple[str, str, Any] | None:
        """Sunk into what it stands on (5.3), where any copy's tool can be."""
        copies = ctx.layout.instances.get(item.id, [])
        return (
            "sunk",
            "5.3",
            lambda chain: any(
                ctx.sink(chain, item, copy) is not None for copy in copies
            ),
        )
