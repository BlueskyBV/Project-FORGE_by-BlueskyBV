"""For the exact kernel's tests (forge_occ): skipped where OpenCascade isn't installed, and the documents they build.

- :data:`needs_occ`: skips a test class when ``forge_occ.status()`` says the
  exact kernel can't run here (it says why);
- :func:`corpus`: every recorded V1 document, by name (the settled designs of
  the recorded runs, replayed through V1's own designer, and the golden
  clevis), as JSON; :func:`zoo` the shape zoo's alone;
- :func:`build`: a V1 document converted to ForgeIR v2 and built by
  ``forge_occ``; :func:`v2` a v2 document from its JSON.
"""

from __future__ import annotations

import contextlib
import functools
import io
import json
import unittest
from pathlib import Path
from typing import Any

import forge_occ

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "tests" / "fixtures" / "real_runs"
CLEVIS = ROOT / "examples" / "clevis" / "clevis.forgeir.json"
CLEVIS_PIN = ROOT / "examples" / "clevis_pin" / "clevis_pin.forgeir.json"

MISSING = forge_occ.status()
needs_occ = unittest.skipIf(MISSING is not None, MISSING or "")


@functools.cache
def _recorded(pattern: str) -> dict[str, str]:
    from test_real_answers import _design, _load

    out: dict[str, str] = {}
    for path in sorted(RUNS.glob(f"{pattern}.json")):
        name = path.stem
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                draft = _design(_load(name))
        except (
            Exception
        ):  # a run whose answer V1 itself refuses records no document: nothing to build
            continue
        out[name] = draft.document.to_json()
    return out


def corpus() -> dict[str, str]:
    """Every recorded V1 document by name, and the golden clevis."""
    return {**_recorded("*"), "golden_clevis": CLEVIS.read_text()}


def zoo() -> dict[str, str]:
    """The shape zoo's documents and the golden clevis (35)."""
    return {**_recorded("zoo*"), "golden_clevis": CLEVIS.read_text()}


def v2(text: str) -> Any:
    """A ForgeIR v2 document from its JSON, or a V1 document's converted."""
    from forge_ir.v2 import DocumentV2

    return DocumentV2.from_any(text)


def converted(text: str) -> Any:
    from forge_ir import Document
    from forge_ir.v2 import convert_v1

    return convert_v1(Document.from_json(text))


def build(text: str, component: str | None = None, **options: Any) -> Any:
    """A V1 document's component (its first, by default) built by ``forge_occ``."""
    from forge_occ.backend import OccBackend

    document = converted(text)
    return OccBackend().build(
        document, component or document.components[0].identifier, **options
    )


def v2_document(payload: dict[str, Any]) -> Any:
    from forge_ir.v2 import DocumentV2

    return DocumentV2.from_json(json.dumps(payload))


def one_step(op: str, params: dict[str, Any], *, steps: tuple[dict[str, Any], ...] = (),
             inputs: tuple[str, ...] = ()) -> Any:  # fmt: skip
    """A v2 document of ``steps`` and then one step ``op`` (``part``)."""
    return v2_document({
        "schema_version": "2.0.0", "document_id": "test", "project_id": "test", "revision": 1, "name": op,
        "components": [{"id": "part", "steps": [*steps, {"id": "part", "op": op, "inputs": list(inputs),
                                                         "params": params}]}],
    })  # fmt: skip
