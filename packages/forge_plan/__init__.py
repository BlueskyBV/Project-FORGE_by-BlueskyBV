"""forge_plan - the compiler: a confirmed spec in, the ForgeIR v2 document that builds it out.

docs/V2-stage4.md. The compiler reads the spec's fields and the placement
solver's layout (:mod:`forge_spec.placement`), never the judge's, and writes
the construction: each copy of each item a tool built from primitives at
its place, joined to or taken from the part made so far, in the order the
part is made (docs/definitions/frame.md). No model, and the same document
every time for the same spec.

It is part of the trust core: it imports only the standard library and the
trust-core packages it compiles from (``forge_units``, ``forge_ir``,
``forge_spec``), never the checks (``forge_checks``), the generator
(``forge_eval``), the exact kernel it writes for (``forge_occ``) or the
second kernel (``forge_kernel``, ``forge_geom``): rule R2, enforced by
tests/test_v2_architecture.py.

- :mod:`~forge_plan.write`: the document as it is written, step by step;
- :mod:`~forge_plan.tools`: each kind's tool, from the definitions;
- :mod:`~forge_plan.edges`: the edge queries of roundings and chamfers;
- :mod:`~forge_plan.shells`: a shell's hollow;
- :mod:`~forge_plan.planner`: the plan: every item's constructions, in order.
"""

from __future__ import annotations

from .errors import GapError, PlanError
from .planner import Construction, Gap, Plan, PlannedItem, plan, preview_plan

__all__ = [
    "Construction",
    "Gap",
    "GapError",
    "Plan",
    "PlanError",
    "PlannedItem",
    "plan",
    "preview_plan",
]
