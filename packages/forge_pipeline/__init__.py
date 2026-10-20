"""forge_pipeline - the deterministic verification pipeline.

Takes a ForgeIR document, returns an evidence graph. No language model anywhere
in the path, which is what makes the whole thing reproducible, free to run, and
impossible to talk into a pass.

>>> from forge_ir import Document
>>> from forge_pipeline import LoadCase, verify_component
>>> from forge_units import Q
>>> doc = Document.from_json(open("examples/clevis/clevis.forgeir.json").read())
>>> report = verify_component(
...     doc, doc.component("clevis"),
...     load_case=LoadCase("bench", Q(500, "N"), Q(35, "mm"),
...                        assumption_id="ASM_DESIGN_LOAD"),
... )
>>> report.overall_status
<Status.BLOCKED: 'BLOCKED'>
"""

from __future__ import annotations

from .response import (
    ParameterResponse,
    measure_the_response,
)
from .verify import (
    describe_the_part,
    the_bore_found_material,
    render_the_part,
    TOOL_ANALYSIS,
    TOOL_KERNEL,
    TOOL_MEASURE,
    TOOL_MESH,
    LoadCase,
    VerificationReport,
    verify_component,
)

__version__ = "0.1.0"

__all__ = [
    "ParameterResponse",
    "measure_the_response",
    "describe_the_part",
    "the_bore_found_material",
    "render_the_part",
    "__version__",
    "LoadCase",
    "VerificationReport",
    "verify_component",
    "TOOL_KERNEL",
    "TOOL_MEASURE",
    "TOOL_MESH",
    "TOOL_ANALYSIS",
]
