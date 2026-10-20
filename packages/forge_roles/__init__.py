"""forge_roles - typed engineering roles with validated output.

Five narrow responsibilities turn a sentence into a verified part:

===========================  ================================================
Brief Interpreter            what was asked, and what was left unsaid
Requirements Engineer        checkable requirements, honest assumptions, unknowns
Clarification Prioritiser    the few questions actually worth the user's attention
ForgeIR Designer             the parametric document
Failure Analyst              a targeted patch when something fails
===========================  ================================================

Every role declares an output schema, gets it enforced at the transport by
forced tool use, and then validates *semantically* -- that a threshold has a
unit, that a document compiles, that a referenced identifier exists. A semantic
failure triggers bounded repair: the errors go back with the model's own answer
still in the conversation, and it is asked to correct them.

Repair is bounded rather than open-ended because a model that has failed the
same validation three times has misunderstood something, and further attempts
buy the same answer at the same price. The budget makes that a reported outcome
instead of a loop.

Repairs are expressed as **RFC 6901 pointer-targeted patches**, never as
rewritten documents. The compiler's diagnostics already carry pointers, so the
error and the fix speak the same language, the edit is minimal and auditable, and
nothing that was already correct is put at risk by a wholesale regeneration.

The rule running through all five prompts: **a number nobody supplied is worse
than a missing number, because it looks checked.**
"""

from __future__ import annotations

from .base import (
    RepairExhaustedError,
    RoleInputError,
    Role,
    RoleError,
    RoleOutputError,
    RoleResult,
    problems_from_schema_error,
)
from .library import (
    BriefInterpreter,
    ClarificationPrioritiser,
    DesignDraft,
    FailureAnalyst,
    ForgeIRDesigner,
    Intent,
    Question,
    RepairProposal,
    RequirementSet,
    RequirementsEngineer,
    Unknown,
)
from .patch import (
    Patch,
    PatchError,
    PointerError,
    apply_patches,
    exists,
    extract_slice,
    parse_pointer,
    resolve,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # framework
    "Role",
    "RoleResult",
    "RoleError",
    "RoleOutputError",
    "RepairExhaustedError",
    "RoleInputError",
    "problems_from_schema_error",
    # roles
    "BriefInterpreter",
    "Intent",
    "RequirementsEngineer",
    "RequirementSet",
    "Unknown",
    "ClarificationPrioritiser",
    "Question",
    "ForgeIRDesigner",
    "DesignDraft",
    "FailureAnalyst",
    "RepairProposal",
    # patching
    "Patch",
    "PatchError",
    "PointerError",
    "apply_patches",
    "parse_pointer",
    "resolve",
    "exists",
    "extract_slice",
]
