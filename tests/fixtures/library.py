"""Turn the hand-written responses into a replayable fixture library.

The scripted responses in :mod:`fixtures.bracket_responses` answer in order and
ignore the request. A fixture library answers by *fingerprint*, which is what
``forge design --provider fixture`` replays -- so testing the CLI needs the
same answers keyed the way the real thing keys them.

Recording one from the other is a single pass: run the orchestrator against the
scripted provider wrapped in :class:`RecordingProvider`, and every request the
real prompts actually produced is written out with its real fingerprint. The
library is therefore never hand-maintained and never stale: it is generated from
the current prompts each time it is built, and a prompt change regenerates it
rather than quietly invalidating it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from forge_models import Budget, RecordingProvider, ScriptedProvider
from forge_orchestrator import Orchestrator, OrchestratorConfig

from .bracket_responses import (
    ANALYST_FIX_BOUNDS,
    BRIEF,
    DESIGNER_BROKEN,
    INTERPRETER,
    REQUIREMENTS,
)

#: The scripted run recorded by default: a design that fails its declared
#: bounds on first compile and is repaired by one surgical patch. Chosen over a
#: clean first pass because the repair path is the one worth exercising through
#: the CLI.
DEFAULT_SCRIPT: tuple[Mapping[str, Any], ...] = (
    INTERPRETER,
    REQUIREMENTS,
    DESIGNER_BROKEN,
    ANALYST_FIX_BOUNDS,
)


def build_library(
    directory: str | Path,
    *,
    brief: str = BRIEF,
    script: Sequence[Mapping[str, Any]] = DEFAULT_SCRIPT,
    assume: bool = True,
) -> Path:
    """Record ``script`` against ``brief`` into ``directory``; return the path."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    provider = RecordingProvider(
        ScriptedProvider(list(script), budget=Budget(max_calls=40)), target
    )
    Orchestrator(
        provider,
        config=OrchestratorConfig(
            stop_on_critical_unknowns=not assume,
            measurement_depth=6,
            mesh_resolution=48,
        ),
    ).design(brief)
    return target


__all__ = ["build_library", "DEFAULT_SCRIPT", "BRIEF"]
