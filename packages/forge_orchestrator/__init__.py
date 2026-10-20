"""forge_orchestrator - the design loop.

Brief in, verified part out, or an honest reason why not.

    interpret -> requirements -> [clarify] -> design -> compile -> verify -> report
                                                  ^          |         |
                                                  +-- repair -+---------+

Three properties the loop is built around:

**It refuses to invent.** If critical information is missing the run *pauses* and
asks, rather than picking a plausible load. Told to proceed anyway, it records
each unknown as an unapproved high-risk assumption -- which blocks release and is
named in the report -- instead of fabricating a value. A design verified against
an invented load passes gates that mean nothing.

**Repair is surgical.** A failure hands the analyst the diagnostic and the slice
of document its pointer refers to; the fix comes back as pointer-targeted
patches. Nothing already correct is regenerated, and the patch list is an
auditable record of what changed and why.

**Oscillation ends the loop.** A repair proposed twice is not applied twice.
Models shown the same failure tend to propose the same fix, and an unbounded loop
spends real money rediscovering that. Stopping produces a better outcome than a
fourth attempt: a clear statement of what could not be fixed.

>>> from forge_models import FixtureProvider
>>> from forge_orchestrator import Orchestrator
>>> run = Orchestrator(FixtureProvider("tests/fixtures/models")).design(
...     "a bracket that holds a 20 mm shaft and bolts to a flat plate"
... )
>>> run.state
<State.AWAITING_ANSWERS: 'awaiting_answers'>
"""

from __future__ import annotations

from .orchestrator import Orchestrator, OrchestratorConfig
from .run import DesignRun, RepairAttempt, RunEvent, State

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Orchestrator",
    "OrchestratorConfig",
    "DesignRun",
    "RunEvent",
    "RepairAttempt",
    "State",
]
