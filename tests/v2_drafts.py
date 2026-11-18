"""Helpers for writing V2 spec drafts in tests, with citations found by phrase.

Hand-counted word numbers go wrong (the first smoke test of the spec checks
proved it); these find them. Drafts in tests are built from V1's corpus briefs
(validation/SUITE.md), never from the blind sets, which no test may tune on.
"""

from __future__ import annotations

from typing import Any

from forge_spec import NumberedBrief


def cite(brief: NumberedBrief, phrase: str, nth: int = 1) -> list[int]:
    """Word numbers of the ``nth`` occurrence of ``phrase`` (words separated by spaces)."""
    wanted = phrase.split()
    texts = [w.text for w in brief.words]
    seen = 0
    for start in range(len(texts) - len(wanted) + 1):
        if [t.lower() for t in texts[start : start + len(wanted)]] == [
            x.lower() for x in wanted
        ]:
            seen += 1
            if seen == nth:
                return list(range(start, start + len(wanted)))
    raise AssertionError(f"{phrase!r} (occurrence {nth}) not in the brief")


def span(brief: NumberedBrief, text: str, nth: int = 1) -> list[int]:
    """Word numbers of every word inside the ``nth`` occurrence of ``text``, as written.

    For phrases whose words the brief splits in ways a space-separated phrase
    can't spell ("+/-", "60\u00b10.1mm").
    """
    start = -1
    for _ in range(nth):
        start = brief.text.find(text, start + 1)
        if start < 0:
            raise AssertionError(f"{text!r} (occurrence {nth}) not in the brief")
    end = start + len(text)
    found = [w.index for w in brief.words if w.start >= start and w.end <= end]
    assert found, f"no whole word inside {text!r}"
    return found


def mm(
    brief: NumberedBrief, value: float, phrase: str, nth: int = 1, unit: str = "mm"
) -> dict[str, Any]:
    return {"value": value, "unit": unit, "from": {"words": cite(brief, phrase, nth)}}


def count(brief: NumberedBrief, n: int, phrase: str, nth: int = 1) -> dict[str, Any]:
    return {"count": n, "from": {"words": cite(brief, phrase, nth)}}


def said(brief: NumberedBrief, phrase: str, nth: int = 1) -> dict[str, Any]:
    return {"words": cite(brief, phrase, nth)}


def assumed(
    reason: str, value: float | None = None, unit: str = "mm"
) -> dict[str, Any]:
    if value is None:
        return {"assumed": reason}
    return {"value": value, "unit": unit, "from": {"assumed": reason}}


def choose(value: str, source: dict[str, Any]) -> dict[str, Any]:
    return {"choose": value, "from": source}


def made_of(brief: NumberedBrief, phrase: str, nth: int = 1) -> dict[str, Any]:
    """A material, exactly as the brief names it: the text of the cited words."""
    words = cite(brief, phrase, nth)
    first, last = brief.words[words[0]], brief.words[words[-1]]
    return {"text": brief.text[first.start : last.end], "from": {"words": words}}


def draft(name: str, items: list[dict[str, Any]], *, not_modelled: list[dict[str, Any]] | None = None,
          silent: list[dict[str, Any]] | None = None, material: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    found = {"schema_version": "1.6", "name": name, "items": items,
             "not_modelled": not_modelled or [], "silent": silent or []}  # fmt: skip
    if material is not None:
        found["requirements"] = {"material": material}
    return found
