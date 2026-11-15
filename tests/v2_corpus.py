"""Real wording for V2's tests: the briefs of V1's 92-brief validation suite.

They were written to build parts, not to test V2, which is what makes them a
fair check of anything that reads a brief.
"""

from __future__ import annotations

from pathlib import Path

SUITE = Path(__file__).resolve().parent.parent / "validation" / "SUITE.md"


def suite_briefs() -> list[str]:
    """Every brief in ``validation/SUITE.md`` (the lines quoted with "> ")."""
    if not SUITE.exists():
        return []
    lines = SUITE.read_text(encoding="utf-8").splitlines()
    return [line[2:] for line in lines if line.startswith("> ")]
