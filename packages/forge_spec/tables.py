"""Standard sizes: clearance holes, tapped holes and bearing seats.

A spec value can come from a table rather than the brief ("clearance for M4"
is 4.5 mm). The table entry used is recorded as the value's provenance, so
the person sees "4.5 mm (ISO 273 normal, for M4)" and can check it. Sizes are
nominal; the printer's own offsets are applied later, in the print spec (plan,
section 4.8).

Sources: ISO 273 (clearance holes for bolts and screws, fine / medium /
coarse series), ISO 261 coarse pitches with common tap drills, and the
dimensions of standard deep-groove ball bearings.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "BEARINGS",
    "CLEARANCE",
    "TAPPED",
    "Bearing",
    "TableEntry",
    "canonical_designation",
    "lookup_fit",
    "metric_size",
    "table_target",
    "table_value",
]

#: ISO 273 clearance hole diameters (mm): fine, medium ("normal"), coarse.
CLEARANCE: Mapping[str, tuple[float, float, float]] = {
    "M1.6": (1.7, 1.8, 2.0), "M2": (2.2, 2.4, 2.6), "M2.5": (2.7, 2.9, 3.1),
    "M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8), "M5": (5.3, 5.5, 5.8),
    "M6": (6.4, 6.6, 7.0), "M8": (8.4, 9.0, 10.0), "M10": (10.5, 11.0, 12.0),
    "M12": (13.0, 13.5, 14.5), "M16": (17.0, 17.5, 18.5), "M20": (21.0, 22.0, 24.0),
    "M24": (25.0, 26.0, 28.0),
}  # fmt: skip

#: Metric coarse threads: pitch and the usual tap drill (mm).
TAPPED: Mapping[str, tuple[float, float]] = {
    "M2": (0.4, 1.6), "M2.5": (0.45, 2.05), "M3": (0.5, 2.5), "M4": (0.7, 3.3),
    "M5": (0.8, 4.2), "M6": (1.0, 5.0), "M8": (1.25, 6.8), "M10": (1.5, 8.5),
    "M12": (1.75, 10.2), "M16": (2.0, 14.0), "M20": (2.5, 17.5), "M24": (3.0, 21.0),
}  # fmt: skip


@dataclass(frozen=True)
class Bearing:
    outer: float
    width: float
    bore: float


#: Deep-groove ball bearings: outside diameter, width, bore (mm).
BEARINGS: Mapping[str, Bearing] = {
    name: Bearing(*dims)
    for name, dims in {
        "623": (10, 4, 3), "624": (13, 5, 4), "625": (16, 5, 5), "626": (19, 6, 6),
        "608": (22, 7, 8), "688": (16, 5, 8), "693": (8, 4, 3), "6000": (26, 8, 10),
        "6001": (28, 8, 12), "6002": (32, 9, 15), "6200": (30, 9, 10), "6201": (32, 10, 12),
        "6202": (35, 11, 15), "6203": (40, 12, 17), "6204": (47, 14, 20),
        "6800": (19, 5, 10), "6900": (22, 6, 10),
    }.items()
}  # fmt: skip

_GRADE = {"fine": 0, "normal": 1, "coarse": 2}
_METRIC = re.compile(r"^[Mm](\d+(?:\.\d+)?)(?:\s*[xX\u00d7]\s*(\d+(?:\.\d+)?))?$")


@dataclass(frozen=True)
class TableEntry:
    """A size read from a table, with the name of the entry it came from."""

    size_mm: float
    source: str


def metric_size(designation: str) -> tuple[str, float | None] | None:
    """'M4' -> ('M4', None); 'M8x1.25' -> ('M8', 1.25); anything else None."""
    match = _METRIC.match(designation.strip())
    if not match:
        return None
    nominal = (
        match.group(1).rstrip("0").rstrip(".")
        if "." in match.group(1)
        else match.group(1)
    )
    return f"M{nominal}", float(match.group(2)) if match.group(2) else None


def canonical_designation(designation: str) -> str | None:
    """A standard part's one spelling, or None if it isn't one Forge reads.

    A metric size keeps its pitch only when it isn't the coarse one, so one
    thread has one spelling (and one digest):

    >>> [canonical_designation(d) for d in ("M6", "M6x1", "m6 X 1.00", "M6\u00d70.75", " 608 ")]
    ['M6', 'M6', 'M6', 'M6x0.75', '608']
    """
    text = designation.strip()
    if text in BEARINGS:
        return text
    size = metric_size(text)
    if size is None:
        return None
    name, pitch = size
    coarse = TAPPED.get(name, (None, None))[0]
    if pitch is None or (coarse is not None and abs(pitch - coarse) < 1e-9):
        return name
    return f"{name}x{pitch:g}"


def lookup_fit(fit: str, target: str, grade: str = "normal") -> TableEntry | None:
    """The diameter a standard fit gives, or None if the table has no such entry.

    >>> lookup_fit("clearance", "M4")
    TableEntry(size_mm=4.5, source='ISO 273 normal clearance for M4')
    >>> lookup_fit("tapped", "M4").size_mm
    3.3
    >>> lookup_fit("bearing_seat", "608").size_mm
    22.0
    """
    if fit == "bearing_seat":
        bearing = BEARINGS.get(target.strip())
        if bearing is None:
            return None
        return TableEntry(
            float(bearing.outer),
            f"seat for a {target.strip()} bearing (outside diameter)",
        )
    size = metric_size(target)
    if size is None:
        return None
    name, pitch = size
    if fit == "clearance":
        row = CLEARANCE.get(name)
        if row is None or grade not in _GRADE:
            return None
        return TableEntry(row[_GRADE[grade]], f"ISO 273 {grade} clearance for {name}")
    if fit == "tapped":
        thread = TAPPED.get(name)
        if thread is None:
            return None
        coarse, drill = thread
        if pitch is None or abs(pitch - coarse) < 1e-9:
            return TableEntry(drill, f"tap drill for {name}x{coarse:g}")
        nominal = float(name[1:])
        if not 0 < pitch < nominal / 4:
            return None
        # A fine pitch: the usual tap drill is the diameter less the pitch
        # (which also gives the coarse table above, to within 0.05 mm).
        return TableEntry(
            round(nominal - pitch, 3),
            f"tap drill for {name}x{pitch:g} ({nominal:g} - {pitch:g})",
        )
    return None


def table_value(reference: str) -> TableEntry | None:
    """A size named by a table reference, as a value's ``"from": {"table": ...}`` gives it.

    ``clearance:M4`` (or ``clearance:M4:fine``), ``tapped:M8x1``, and
    ``bearing:608:outer`` (or ``:width``, ``:bore``). None for anything else.

    >>> table_value("bearing:608:width")
    TableEntry(size_mm=7.0, source='width of a 608 bearing')
    >>> table_value("clearance:M3:fine").size_mm
    3.2
    """
    parts = [part.strip() for part in reference.split(":")]
    if parts[0] == "bearing" and len(parts) == 3:
        bearing = BEARINGS.get(parts[1])
        if bearing is None or parts[2] not in ("outer", "width", "bore"):
            return None
        size = getattr(bearing, parts[2])
        return TableEntry(
            float(size),
            f"{parts[2]} of a {parts[1]} bearing".replace(
                "outer of", "outside diameter of"
            ),
        )
    if parts[0] == "clearance" and len(parts) in (2, 3):
        return lookup_fit(
            "clearance", parts[1], parts[2] if len(parts) == 3 else "normal"
        )
    if parts[0] == "tapped" and len(parts) == 2:
        return lookup_fit("tapped", parts[1])
    return None


def table_target(reference: str) -> str | None:
    """The standard part a table reference names ("M4", "M8x1", "608"), for checking its citation."""
    parts = [part.strip() for part in reference.split(":")]
    if len(parts) < 2:
        return None
    if parts[0] == "bearing":
        return parts[1] if parts[1] in BEARINGS else None
    if parts[0] in ("clearance", "tapped"):
        size = metric_size(parts[1])
        if size is None:
            return None
        return size[0] if size[1] is None else f"{size[0]}x{size[1]:g}"
    return None
