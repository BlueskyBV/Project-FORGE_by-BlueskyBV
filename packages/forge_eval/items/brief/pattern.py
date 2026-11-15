"""How the brief says each pattern mode: the ``brief`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_BRIEF` holds one entry per mode, in ``PATTERN_FIELDS``' order.
"""

from __future__ import annotations

from typing import Any

from forge_registry import Registry
from forge_spec.draft import PATTERN_FIELDS

from forge_eval.brief import Writer
from forge_eval.generator import Pattern, _chosen, _counted, _mm


class PatternBrief:
    """One pattern mode, as the ``brief`` role holds it."""

    #: The mode this entry is for.
    key = ""

    def said(self, p: Pattern, w: Writer, body: dict[str, Any]) -> None:
        """Its copies in the brief's words, and what each says in ``body``."""
        w.say("at the face's corners, ")
        for k, (name, v) in enumerate(p.values.items()):
            w.say(" and " if k else "")
            body[name] = _mm(w, v, after=f" in along {name[-1]}")


class Corners(PatternBrief):
    key = "corners"


class Rectangle(PatternBrief):
    key = "rectangle"

    def said(self, p: Pattern, w: Writer, body: dict[str, Any]) -> None:
        w.say("at the corners of a rectangle ")
        for k, (name, v) in enumerate(p.values.items()):
            w.say(" and " if k else "")
            body[name] = _mm(w, v, after=f" along {name[-1]}")


class Ends(PatternBrief):
    key = "ends"


class Row(PatternBrief):
    key = "row"

    def said(self, p: Pattern, w: Writer, body: dict[str, Any]) -> None:
        w.say("in a row of ")
        body["count"] = _counted(w, p.counts["count"])
        w.say(" ")
        body["axis"] = _chosen(w, p.axis, f"along {p.axis}")
        w.say(", ")
        body["pitch"] = _mm(w, p.values["pitch"], after=" apart")


class Grid(PatternBrief):
    key = "grid"

    def said(self, p: Pattern, w: Writer, body: dict[str, Any]) -> None:
        w.say("in a grid of ")
        for k, name in enumerate(p.counts):
            w.say(" and " if k else "")
            body[name] = _counted(w, p.counts[name], f" along {name[-1]}")
        for name, v in p.values.items():
            w.say(", ")
            body[name] = _mm(w, v, after=f" apart along {name[-1]}")


class Circle(PatternBrief):
    key = "circle"

    def said(self, p: Pattern, w: Writer, body: dict[str, Any]) -> None:
        w.say("in a circle of ")
        body["count"] = _counted(w, p.counts["count"])
        if "diameter" in p.values:
            w.say(", ")
            body["diameter"] = _mm(w, p.values["diameter"], after=" across")
        if "start" in p.values:
            w.say(", ")
            body["start"] = _mm(w, p.values["start"], before="the first at ", unit="deg")  # fmt: skip


class Arc(PatternBrief):
    key = "arc"


PATTERN_BRIEF: Registry[PatternBrief] = Registry(
    "forge_eval.brief.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternBrief,
)
