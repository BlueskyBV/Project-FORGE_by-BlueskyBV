"""forge_evidence - immutable evidence, six-status gates, and release decisions.

This package holds the invariant the whole product rests on: **evidence outranks
language-model opinion.** A deterministic gate that failed cannot be overruled by
a confident summary, and a gate that could not be decided is reported as
undecided rather than rounded up.

Three mechanisms enforce that rather than merely asserting it.

*The status vocabulary distinguishes "checked and fine" from "could not check".*
Six statuses, not two. ``INCONCLUSIVE`` and ``NOT_TESTED`` are separate outcomes
and neither can be reported as success. See :mod:`forge_evidence.status`.

*Gate verdicts are computed, not judged.* A gate compares a measured
:class:`~forge_units.Quantity` -- which carries its own uncertainty interval --
against a threshold using three-valued logic. A measurement that straddles its
threshold yields ``INCONCLUSIVE`` by arithmetic, with no code path that converts
it into a pass. See :mod:`forge_evidence.gates`.

*Evidence is immutable and carries its limitations.* Adding a result never
replaces one; superseding means appending a node that names its parent. Any node
produced by a numerical or analytical method must declare what it does not
cover, or construction fails. Soft evidence -- a vision model's review, a user's
say-so -- is excluded from the release roll-up entirely: it can ask for a
deterministic check to be run, never stand in for one.

>>> from forge_units import Q
>>> from forge_evidence import Gate, Method, ToolIdentity
>>> gate = Gate("MASS", "body mass within budget", "at_most", Q(40, "g"))
>>> measured = Q(39.95, "g", plus=0.35, minus=0.35)   # honest measurement
>>> gate.evaluate(measured, method=Method.EXACT_GEOMETRY,
...               tool=ToolIdentity("implicit", "0.1.0")).status
<Status.INCONCLUSIVE: 'INCONCLUSIVE'>

A point estimate of 39.95 g would have passed that gate. The interval says the
part might weigh 40.3 g, and so the gate says it does not know.
"""

from __future__ import annotations

from .evidence import Evidence, EvidenceGraph, Method, ToolIdentity
from .gates import Comparison, Gate, GateResult, release_status
from .status import Status, combine

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Status",
    "combine",
    "Evidence",
    "EvidenceGraph",
    "Method",
    "ToolIdentity",
    "Gate",
    "GateResult",
    "Comparison",
    "release_status",
]
