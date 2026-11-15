"""Building a plan: each item's constructions tried in order where OpenCascade refuses one (docs/V2-stage4.md, section 8).

1. The plan's document is built with a step cache, so a rebuild reuses
   every step before the one that changed.
2. A step refused (any :class:`~forge_occ.errors.OccError`: OpenCascade
   raised, the solid is invalid, an after-check failed, a reference matched
   outside its condition) names the planned item it was written for. That
   item's next construction whose proof holds is tried. So does a join or
   cut of the part that leaves it more than one solid: the part is one
   solid all the way, and more is OpenCascade misreading the step (a hole's
   plug kept beside the part: held-out seed 10,517).
3. When it has none left, the earlier items whose boxes meet the refused
   item's are tried, latest first, each through its own constructions, with
   the refused item's tried again from its first after each: a refusal can
   be caused by how an earlier item was made (a union whose faces a later
   fillet can't run over). The search is bounded (each earlier item's
   constructions once; at most :data:`MOST` builds in all) and
   deterministic.
4. When it runs out, the refused item is the gap, with every refusal met.

Every refusal is recorded, so a construction OpenCascade often refuses is
seen. The constructions themselves, and the proofs that each makes what the
first makes, are the compiler's (:mod:`forge_plan`); nothing here changes a
shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from forge_plan import Gap, Plan

from .backend import BuildResult, OccBackend
from .cache import StepCache
from .errors import AfterCheckError, OccError
from .occt import solids

__all__ = ["MOST", "PlannedBuild", "Refusal", "build_plan"]

#: The most builds one plan is given.
MOST = 64


@dataclass(frozen=True)
class Refusal:
    """One construction OpenCascade refused: the planned item, the construction, the step, and why."""

    item: str
    construction: str
    step: str
    error: dict[str, Any]


@dataclass(frozen=True)
class PlannedBuild:
    """What building a plan came to: the part (or None), each item's construction, every refusal, and the gap."""

    result: BuildResult | None
    choice: Mapping[str, int]
    refusals: tuple[Refusal, ...]
    gap: Gap | None
    builds: int
    #: Each planned item's chosen construction, by name.
    made_by: Mapping[str, str] = field(default_factory=dict)


def _one_solid(result: BuildResult, parts: list[str]) -> None:
    """The part made so far is one solid after each join or cut of it (V2-stage4.md, 8): the first that isn't is refused."""
    for step in parts:
        product = result.products.get(step)
        if product is None:
            continue
        found = len(solids(product.shape))
        if found != 1:
            raise AfterCheckError(
                f"the part made so far is {found} solids after it, not one: OpenCascade misread the step",
                step=step,
                solids=found,
            )


class _Search:
    def __init__(self, plan: Plan, cache: StepCache, most: int) -> None:
        self.plan = plan
        self.cache = cache
        self.most = most
        self.builds = 0
        self.refusals: list[Refusal] = []
        self.backend = OccBackend()

    def build(self, choice: Mapping[str, int]) -> tuple[BuildResult | None, str | None]:
        """The part with ``choice``, or None and the planned item refused."""
        written = self.plan.written(choice)
        self.builds += 1
        try:
            result = self.backend.build(written.document, "part", cache=self.cache)
            _one_solid(result, written.chain.parts)
            return result, None
        except OccError as error:
            step = str(error.detail.get("step", ""))
            key = written.owners.get(step)
            if key is None:  # a step no item owns: the plan's own fault
                raise
            name = written.made_by[key]
            self.refusals.append(Refusal(key, name, step, error.as_dict()))
            return None, key

    def run(self) -> PlannedBuild:
        choice: dict[str, int] = {}
        result, refused = self.build(choice)
        while result is None:
            assert refused is not None
            following = self.plan.next_choice(choice, refused)
            if following is not None:
                if self.builds >= self.most:
                    return self.out_of_builds(choice)
                choice = {**choice, refused: following}
                result, refused = self.build(choice)
                continue
            found = self.search(choice, refused)
            if found is None:
                if self.builds >= self.most:
                    return self.out_of_builds(choice)
                why = self.refusals[-1].error.get("message", "OpenCascade refused it")
                gap = Gap(
                    self.plan.planned(refused).item,
                    f"OpenCascade refused every way to make it: {why}",
                )
                return self.done(None, choice, gap)
            result, choice, refused = found
        return self.done(result, choice, None)

    def out_of_builds(self, choice: Mapping[str, int]) -> PlannedBuild:
        last = self.refusals[-1]
        gap = Gap(
            self.plan.planned(last.item).item,
            f"no construction built within {self.most} builds",
        )
        return self.done(None, choice, gap)

    def search(
        self, choice: dict[str, int], refused: str
    ) -> tuple[BuildResult | None, dict[str, int], str | None] | None:
        """Earlier items meeting the refused one, latest first, through their constructions, the refused one's again after each.

        A build refused at an item later than ``refused`` has got past it:
        it is handed back to the main loop with the item refused. None where
        every combination is refused at ``refused`` or before it, or the
        builds run out.
        """
        keys = [planned.key for planned in self.plan.items]
        at = keys.index(refused)
        boxes = self.plan.written(choice).chain.boxes
        mine = boxes.get(refused, [])
        meeting = [
            key
            for key in keys[:at]
            if any(a.meets(b, by=1e-6) for a in boxes.get(key, []) for b in mine)
        ]
        for earlier in reversed(meeting):
            base = {k: v for k, v in choice.items() if k != refused}
            holding = self.plan.applying(base, earlier)
            current = base.get(earlier, holding[0] if holding else -1)
            for alternative in holding:
                if alternative == current:
                    continue
                tried = {**base, earlier: alternative}
                for again in self.plan.applying(tried, refused):
                    if self.builds >= self.most:
                        return None
                    attempt = {**tried, refused: again}
                    result, failed = self.build(attempt)
                    if result is not None:
                        return result, attempt, None
                    if failed is not None and keys.index(failed) > at:
                        return None, attempt, failed
        return None

    def done(
        self, result: BuildResult | None, choice: Mapping[str, int], gap: Gap | None
    ) -> PlannedBuild:
        made_by = dict(self.plan.written(choice).made_by)
        return PlannedBuild(
            result, dict(choice), tuple(self.refusals), gap, self.builds, made_by
        )


def build_plan(
    plan: Plan, *, cache: StepCache | None = None, most: int = MOST
) -> PlannedBuild:
    """Build a plan, each item's constructions tried in order where OpenCascade refuses one (section 8).

    A plan with gaps of its own (a region, an item with no construction) is
    built without them, for the preview, and its first gap is the build's:
    the run ends UNABLE for it whatever was built.
    """
    if most < 1:
        raise ValueError("a plan is given one build at least")
    if not plan.items:
        return PlannedBuild(
            None,
            {},
            (),
            plan.gaps[0] if plan.gaps else Gap("", "the spec makes nothing"),
            0,
        )
    found = _Search(plan, cache or StepCache(), most).run()
    if plan.gaps and found.gap is None:
        return PlannedBuild(
            found.result,
            found.choice,
            found.refusals,
            plan.gaps[0],
            found.builds,
            found.made_by,
        )
    return found
