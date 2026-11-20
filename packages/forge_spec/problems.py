"""Problems found in a draft, collected rather than raised one at a time.

V1 refused a whole answer for one bad entry, and reported one fault per round,
so a draft with five faults cost five paid rounds (rule R8 exists because of
it). V2 reads a draft item by item, keeps every good item, and reports every
fault it found in one round. Each problem carries a JSON Pointer to the place it
is about, so the model and the person both see exactly which value is wrong.

Syntax that Forge normalises without changing meaning (``4.0`` as a count,
"millimetres" as ``mm``, citations in a different order) is recorded as a
**note**, never done silently (rule R7).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "MAX_NAME",
    "MAX_REASON",
    "READ_REASON",
    "Problem",
    "Problems",
    "clean_text",
    "one_line",
    "pointer",
    "unknown_keys",
]


def unknown_keys(raw: Mapping[Any, Any], keys: Iterable[str]) -> list[str]:
    """The keys of ``raw`` that aren't in ``keys``, shown as text, sorted.

    A key that isn't a string is always unknown (JSON can't make one, but a
    Python caller can), and never makes the sort raise.
    """
    allowed = set(keys)
    return sorted(
        repr(k) if not isinstance(k, str) else k
        for k in raw
        if not isinstance(k, str) or k not in allowed
    )


def clean_text(text: str) -> bool:
    """Whether a text is one line of plain, printable Unicode.

    No lone surrogates, no control codes (newlines and tabs included), no
    format characters (bidirectional overrides, zero-width joiners), no line
    or paragraph separators: model-written text is shown to the person, and
    must not be able to start a line of its own or reorder what they read.
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return not any(unicodedata.category(c) in _UNPRINTABLE for c in text)


_UNPRINTABLE = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})

#: The longest a model-written name, reason or reference may be: the person
#: reads each whole, on one line.
MAX_NAME = 80
MAX_REASON = 200
#: The longest a writer's reason may be and still be read: it is asked for MAX_REASON, and a little over is
#: read rather than sent back, since sending it back is a paid model call (blind set 1: 5 of 403 reasons ran
#: 201 to 240 characters, and two of its briefs spent a redraft on one).
READ_REASON = 300


def one_line(raw: object, limit: int) -> str | None:
    """Model-written text the person will read, as one tidy line, or None if it can't be one.

    Runs of spaces of any kind become one space, so padding can't push the
    rest of it onto a line of its own; text that isn't clean, is empty, or is
    longer than ``limit`` is refused.

    >>> one_line("  the   material\u3000\u3000is steel ", 200)
    'the material is steel'
    >>> one_line("a" + chr(10) + "b", 200) is None
    True
    """
    if not isinstance(raw, str) or not clean_text(raw):
        return None
    text = " ".join(raw.split())
    return text if text and len(text) <= limit else None


def pointer(*parts: str | int) -> str:
    """An RFC 6901 JSON Pointer: ``pointer("items", 3, "depth")`` -> ``/items/3/depth``."""
    escaped = (str(p).replace("~", "~0").replace("/", "~1") for p in parts)
    return "".join(f"/{p}" for p in escaped)


@dataclass(frozen=True)
class Problem:
    """One fault, at one place in the draft."""

    at: str
    message: str

    def __str__(self) -> str:
        return f"{self.at or '/'}: {self.message}"


@dataclass
class Problems:
    """Faults and notes collected while reading one draft."""

    faults: list[Problem] = field(default_factory=list)
    notes: list[Problem] = field(default_factory=list)

    def fault(self, at: str, message: str) -> None:
        self.faults.append(Problem(at, message))

    def note(self, at: str, message: str) -> None:
        self.notes.append(Problem(at, message))

    def __bool__(self) -> bool:
        """True when there is at least one fault (notes don't count)."""
        return bool(self.faults)

    def extend(self, other: Problems) -> None:
        self.faults.extend(other.faults)
        self.notes.extend(other.notes)
