"""The template helpers every kind's sentence is worded with (the ``words`` role's shared leaf: it imports neither the kinds' modules nor ``render.py``).

Moved from ``render.py`` at stage 4b.0b's step 3, unchanged. The position
along an axis and a pattern's words (``_axis``, ``_place``) are the pattern
kind's modes, moved again at step 5 (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from forge_spec.draft import (
    AxisPosition,
    Choice,
    EdgeSet,
    Faces,
    FieldValue,
    Item,
    On,
    Place,
    Profile,
    Text,
    Through,
)
from forge_spec.items.words.pattern import PATTERN_WORDS
from forge_spec.values import Count, Provenance, Source, Value


def _n(x: float) -> str:
    """A number as the shortest text that reads back as exactly it.

    Two values that differ never print alike, so the person confirms what
    the spec holds, not a rounding of it.
    """
    if x == 0:
        return "0"
    text = repr(float(x))
    return text[:-2] if text.endswith(".0") else text


def _tag(p: Provenance) -> str:
    if p.source is Source.ASSUMED:
        return " (assumed)"
    if p.source is Source.TABLE:
        return f" (table {p.table})"
    if p.source is Source.DERIVED:
        return f" (= {p.formula})"
    return ""


def _v(value: object) -> str:
    """A value with its unit, tolerance and source."""
    if isinstance(value, Count):
        return f"{value.n}{_tag(value.provenance)}"
    if not isinstance(value, Value):
        return "?"
    text = f"{_n(value.nominal)} {value.unit}"
    if value.tolerance is not None:
        text += f" +{_n(value.tolerance.plus)}/-{_n(value.tolerance.minus)}"
    return text + _tag(value.provenance)


def _c(value: object) -> str:
    """A choice, with its source."""
    if isinstance(value, Choice):
        return f"{value.value.upper() if len(value.value) == 1 else value.value}{_tag(value.provenance)}"
    return "?"


def _axis(axis: str, position: AxisPosition, pattern: str | None = None) -> str:
    """A position along one axis, said as the solver measures it (docs/definitions/place.md).

    From an edge, a row, grid or rectangle of copies is measured to its
    nearest copy, a circle of them to its centre.
    """
    if position.mode == "centred":
        return f"centred along {axis.upper()}" + (
            _tag(position.provenance) if position.provenance else ""
        )
    distance = _v(position.distance)
    if position.mode == "offset":
        return f"offset {distance} along {axis.upper()} from the centre"
    whose = "its" if pattern is None else "the nearest one's"
    to = f"{whose} centre" if position.to == "centre" else f"{whose} near edge"
    if pattern is not None and PATTERN_WORDS[pattern].placed_by_circle:
        to = "the circle's centre"
    return f"{distance} from the {position.side} edge to {to}" + (
        "" if position.to_given else " (assumed)"
    )


def _place(place: Place | None) -> str:
    if place is None:
        return "where the solver puts it (see the assumptions)"
    kind = place.pattern.kind if place.pattern is not None else None
    parts = [_axis(axis, pos, kind) for axis, pos in sorted(place.axes.items())]
    if place.angle is not None:
        parts.append(f"at {_v(place.angle)} around the axis")
    if place.turn is not None:
        parts.append(f"turned {_v(place.turn)} in the face")
    pattern = place.pattern
    if pattern is not None:
        v, n = pattern.values, pattern.counts
        axis = (pattern.axis or "?").upper() + (
            _tag(pattern.axis_provenance) if pattern.axis_provenance else ""
        )

        def named(prefix: str) -> str:
            keys = sorted(
                k for k in set(v) | set(n) if k.startswith(prefix) and k != "each"
            )
            return ", ".join(
                f"{k[len(prefix) :].upper()} {_v(v[k] if k in v else n[k])}"
                for k in keys
            )

        parts.append(PATTERN_WORDS[pattern.kind].said(v, n, axis, named))
        if "each" in n:
            parts.append(f"{_v(n['each'])} at each position")
    if place.concentric:
        parts.append(f"concentric with {place.concentric}" + (
            _tag(place.concentric_provenance) if place.concentric_provenance else ""))  # fmt: skip
    return ", ".join(parts) if parts else "with no position given (see the assumptions)"


def _depth(value: object) -> str:
    if isinstance(value, Through):
        return "right through" + _tag(value.provenance)
    return f"{_v(value)} deep"


def _text(value: object) -> str:
    return f"{value.text!r}{_tag(value.provenance)}" if isinstance(value, Text) else "?"


def _point(p: tuple[float, float]) -> str:
    return f"({_n(p[0])}, {_n(p[1])})"


def _outline(profile: Profile) -> str:
    steps = []
    for seg in profile.segments:
        if seg.centre is None:
            steps.append(f"line to {_point(seg.to)}")
        else:
            turn = "clockwise" if seg.clockwise else "anticlockwise"
            steps.append(f"arc {turn} to {_point(seg.to)} about {_point(seg.centre)}")
    return f"the outline (mm) from {_point(profile.start)}: {', '.join(steps)}" + _tag(
        profile.provenance
    )


def _generic(value: FieldValue) -> str:
    if isinstance(value, (Value, Count)):
        return _v(value)
    if isinstance(value, Choice):
        return _c(value)
    if isinstance(value, Text):
        return _text(value)
    if isinstance(value, Faces):
        return (", ".join(value.faces) or "none") + _tag(value.provenance)
    if isinstance(value, Profile):
        return _outline(value)
    return str(value)


@dataclass
class _Line:
    """One item's line, built from fields that are each worded once."""

    item: Item
    used: set[str] = field(default_factory=set)

    def get(self, name: str) -> FieldValue | None:
        self.used.add(name)
        return self.item.get(name)

    def v(self, name: str) -> str:
        return _v(self.get(name))

    def rest(self) -> str:
        left = [n for n in self.item.fields if n not in self.used]
        return "".join(f"; {n} {_generic(self.item.fields[n])}" for n in left)


def _where(line: _Line, *, cut: bool = False) -> str:
    on = line.get("on")
    place = line.get("place")
    if not isinstance(on, On):
        return "at the origin"
    verb = "into" if cut else "on"
    tilt, towards = line.get("tilt"), line.get("tilt_towards")
    leaning = f", leaning {_v(tilt)} towards {_c(towards) if towards is not None else '?'}" if tilt is not None else ""
    return f"{verb} the {on.face} face of {on.item}, {_place(place if isinstance(place, Place) else None)}{leaning}"


def _count(line: _Line) -> str:
    count = line.get("count")
    return f"{_v(count)} x " if isinstance(count, Count) else ""


def _axis_of(line: _Line) -> str:
    axis = line.get("axis")
    if isinstance(axis, Choice):
        return f", axis {_c(axis)}"
    return "" if isinstance(line.item.get("on"), On) else ", axis Z (assumed)"


def _edges(value: object) -> str:
    if not isinstance(value, EdgeSet):
        return "?"
    if value.which == "joint":
        return f"the edges where {value.of} meets {value.where_meets}"
    return f"the {value.which} edges of {value.of}"


_Template = Callable[[_Line], str]
