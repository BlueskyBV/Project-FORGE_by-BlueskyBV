"""Values in a spec, each with the reason it is what it is.

Every size, angle and count in a PartSpec says where it came from:

- **brief:** the words of the brief it was read from, by word number;
- **table:** a standard table entry, such as an M4 clearance hole;
- **derived:** a formula over other values, shown to the person;
- **assumed:** nothing in the brief gave it, so Forge assumed it, with a reason.

Assumptions are shown to the person first. A value from the brief is checked
against its words by :mod:`forge_spec.citations`, so a misheard or invented number
can't pass as one the brief stated.

Two rules from V1's failures are built into the types:

- **A unit is mandatory, angles included.** V1 read ``cos(30)`` in radians and
  "1/2 inch" as 2 inches. A :class:`Value` with no unit can't be made.
- **A count is its own type, with no unit.** V1 refused a count's unit as ""
  and again as "turns", and lost the run. A :class:`Count` has no unit to
  argue about.

Values are nominal, and a design tolerance travels beside the value for the
drawing, the fits and the printer. The part is made at the middle of a
value's tolerance (:attr:`Value.made`; sizes.md): the nominal, unless the
value's own tolerance isn't the same both ways (10 mm +0.1/-0 is made at
10.05 mm), so no size is made on a limit of its tolerance.

The wire form the spec writer fills in::

    {"value": 2.8, "unit": "mm", "from": {"words": [12, 13]}}
    {"value": 4.5, "unit": "mm", "from": {"table": "clearance:M4", "words": [7]}}
    {"value": 25, "unit": "mm", "from": {"formula": "50 mm / 2", "words": [8, 9]}}
    {"value": 3, "unit": "mm", "from": {"assumed": "no wall thickness given; 3 mm prints solidly"}}
    {"count": 4, "from": {"words": [9]}}
    {"value": 10, "unit": "mm", "tolerance": {"plus": 0.1, "minus": 0}, "from": {"words": [3, 4]}}
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from forge_units import ForgeUnitsError, Q, Quantity, Unit, known_units, parse_unit
from forge_units.dimension import DIMENSIONLESS

from .citations import CitationCheck, check_count, check_quantity
from .problems import MAX_REASON, READ_REASON, Problems, one_line, pointer, unknown_keys
from .tables import canonical_designation
from .words import NumberedBrief, WordRef

__all__ = [
    "MAX_COUNT",
    "Count",
    "Provenance",
    "Source",
    "Tolerance",
    "Value",
    "check_citation",
    "made_note",
    "read_count",
    "read_number",
    "read_provenance",
    "read_value",
]


#: Dimensionless units a value may have: angles and percentages.
_DIMENSIONLESS_UNITS = frozenset({"deg", "rad", "rev", "arcmin", "arcsec", "%"})


class Source(str, Enum):
    """Where a value came from."""

    BRIEF = "brief"
    TABLE = "table"
    DERIVED = "derived"
    ASSUMED = "assumed"


@dataclass(frozen=True)
class Provenance:
    """Where a value came from, with what the person needs to judge it."""

    source: Source
    words: WordRef = ()
    table: str | None = None
    formula: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if any(
            isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in self.words
        ):
            raise ValueError("cited words are word numbers: non-negative integers")
        if tuple(sorted(set(self.words))) != self.words:
            raise ValueError("cited words are kept sorted and without repeats")
        required = {
            Source.BRIEF: ("words", bool(self.words)),
            Source.TABLE: ("table", bool(self.table)),
            Source.DERIVED: ("formula", bool(self.formula)),
            Source.ASSUMED: ("reason", bool(self.reason and self.reason.strip())),
        }
        name, present = required[self.source]
        if not present:
            raise ValueError(f"a value from {self.source.value} needs its {name}")
        others = {"table": self.table, "formula": self.formula, "reason": self.reason}
        stray = [k for k, v in others.items() if v is not None and k != name]
        if stray:
            raise ValueError(
                f"a value from {self.source.value} can't also have {stray}"
            )

    @property
    def is_assumption(self) -> bool:
        return self.source is Source.ASSUMED


@dataclass(frozen=True)
class Tolerance:
    """A design tolerance on a value: ``+plus / -minus``, in the value's unit."""

    plus: float
    minus: float

    def __post_init__(self) -> None:
        for name, bound in (("plus", self.plus), ("minus", self.minus)):
            if not math.isfinite(bound) or bound < 0:
                raise ValueError(f"tolerance {name} must be a finite number >= 0")


@dataclass(frozen=True)
class Value:
    """A nominal quantity, its optional tolerance, and where it came from."""

    quantity: Quantity
    provenance: Provenance
    tolerance: Tolerance | None = None

    def __post_init__(self) -> None:
        if not self.quantity.is_exact:
            raise ValueError("a spec value is nominal; give a range as a tolerance")
        if not _allowed_unit(self.quantity.unit):
            raise ValueError(
                "a spec value needs a real unit, angles included (deg or rad); "
                "a plain number of things is a Count"
            )
        if not math.isfinite(self.quantity.nominal):
            raise ValueError("a spec value must be a finite number")

    @property
    def nominal(self) -> float:
        return self.quantity.nominal

    @property
    def unit(self) -> str:
        return self.quantity.unit.symbol

    @property
    def made(self) -> Quantity:
        """The size the part is made to: the middle of the value's tolerance, in its unit (the nominal without one, or with one the same both ways)."""
        if self.tolerance is None or self.tolerance.plus == self.tolerance.minus:
            return self.quantity
        middle = (
            self.quantity.nominal + (self.tolerance.plus - self.tolerance.minus) / 2
        )
        return Q(middle, self.quantity.unit.symbol)

    def made_in(self, unit: str) -> float:
        """:attr:`made` in ``unit``: what every program that makes geometry from the value reads."""
        return float(self.made.value_in(unit))

    def nominal_in(self, unit: str) -> float:
        """The nominal in ``unit``: for the spec's own text and its citations, never for geometry."""
        return float(self.quantity.value_in(unit))


def made_note(value: Value) -> str:
    """Where a value is made at another size than its nominal, a note saying so for a problem's message; else nothing."""
    made = value.made
    if made == value.quantity:
        return ""
    return (
        f" (it is made at the middle of its tolerance, {made.nominal:g} {value.unit})"
    )


@dataclass(frozen=True)
class Count:
    """A whole number of things. It has no unit, on purpose."""

    n: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if isinstance(self.n, bool) or not isinstance(self.n, int):
            raise ValueError("a count is a whole number")
        if not 0 <= self.n <= MAX_COUNT:
            raise ValueError(f"a count is between 0 and {MAX_COUNT:,}")


# ----------------------------------------------------------------------
# Reading the wire form, item by item
# ----------------------------------------------------------------------
#: More of one thing than any part has; a larger count is a fault, not a part.
MAX_COUNT = 100_000


def _allowed_unit(unit: Unit) -> bool:
    """A value's unit: dimensional, an angle, or a percentage.

    "mm/mm" parses, and is dimensionless; accepted as a unit it would let
    ``30 mm/mm`` stand for 30 rad, which is V1's ``cos(30)`` again.
    """
    if unit.dimension != DIMENSIONLESS:
        return True
    return unit.symbol in _DIMENSIONLESS_UNITS


def _words(raw: Any, at: str, problems: Problems) -> WordRef | None:
    if not isinstance(raw, list) or not raw:
        problems.fault(at, "cite the words as a non-empty list of word numbers")
        return None
    if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in raw):
        problems.fault(at, f"word numbers are non-negative whole numbers, got {raw!r}")
        return None
    ordered = tuple(sorted(set(raw)))
    if list(ordered) != raw:
        problems.note(at, f"word numbers read as {list(ordered)}")
    return ordered


_SOURCE_NAMES = {"words": "the brief's words", "table": "a table", "formula": "a formula",
                 "assumed": "an assumption"}  # fmt: skip


def read_provenance(
    raw: Any,
    at: str,
    problems: Problems,
    allow: tuple[str, ...] = ("words", "table", "formula", "assumed"),
) -> Provenance | None:
    """Read a ``"from"`` object, reporting every fault in it.

    ``allow`` is where this kind of value may come from: a size from any of
    the four, a choice only from the brief's words or an assumption
    (:data:`forge_spec.schema.SOURCES`).
    """
    if not isinstance(raw, Mapping):
        shown = ", ".join(
            {"words": '{"words": [...]}', "table": '{"table": ...}',
             "formula": '{"formula": ..., "words": [...]}',
             "assumed": '{"assumed": ...}'}[k] for k in allow
        )  # fmt: skip
        problems.fault(at, f"say where it came from: {shown}")
        return None
    before = len(problems.faults)
    unknown = unknown_keys(raw, ("words", "table", "formula", "assumed"))
    if unknown:
        problems.fault(at, f"unknown field(s) {unknown}")
    kinds = [k for k in ("table", "formula", "assumed") if k in raw]
    if len(kinds) > 1:
        problems.fault(at, f"a value comes from one place; got {kinds}")
    refused = [k for k in kinds if k not in allow]
    if refused:
        allowed = " or ".join(_SOURCE_NAMES[k] for k in allow)
        problems.fault(
            at, f"this can't come from {_SOURCE_NAMES[refused[0]]}; only from {allowed}"
        )
    words: WordRef = ()
    if "words" in raw:
        words = _words(raw["words"], at + pointer("words"), problems) or ()
    texts: dict[str, str] = {}
    for kind in kinds:
        text = one_line(raw[kind], READ_REASON if kind == "assumed" else MAX_REASON)
        if not isinstance(raw[kind], str) or not raw[kind].strip():
            problems.fault(at + pointer(kind), f"{kind} must be non-empty text")
        elif text is None:
            problems.fault(at + pointer(kind), f"{kind} must be one line of plain printable text, "
                                               f"at most {MAX_REASON} characters")  # fmt: skip
        elif kind == "formula" and "#" in text:
            problems.fault(
                at + pointer(kind), "a formula is arithmetic only: no comments"
            )
        else:
            texts[kind] = _canonical_table(text) if kind == "table" else text
    if not kinds and "words" not in raw:
        problems.fault(at, "a value from the brief cites its words")
    if "assumed" in kinds and "words" in raw:
        problems.fault(
            at, "an assumption cites no words; cite them and it isn't assumed"
        )
    if len(problems.faults) > before:
        return None
    if not kinds:
        return Provenance(Source.BRIEF, words)
    kind = kinds[0]
    source = {
        "table": Source.TABLE,
        "formula": Source.DERIVED,
        "assumed": Source.ASSUMED,
    }
    return Provenance(
        source[kind],
        words,
        table=texts.get("table"),
        formula=texts.get("formula"),
        reason=texts.get("assumed"),
    )


def _canonical_table(reference: str) -> str:
    """A table reference with its part in its one spelling: "tapped: M8x1.25" -> "tapped:M8"."""
    parts = [part.strip() for part in reference.split(":")]
    if len(parts) >= 2 and parts[0] in ("clearance", "tapped", "bearing"):
        parts[1] = canonical_designation(parts[1]) or parts[1]
    return ":".join(parts)


def read_number(raw: Any, at: str, problems: Problems) -> float | None:
    """A finite number; a bool, a string or an overflowing integer is a fault."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        problems.fault(at, f"expected a number, got {raw!r}")
        return None
    try:
        value = float(raw)
    except OverflowError:
        problems.fault(at, "the number is too large")
        return None
    if not math.isfinite(value):
        problems.fault(at, "the number must be finite")
        return None
    return value


def _tolerance(raw: Any, at: str, problems: Problems) -> Tolerance | None:
    if not isinstance(raw, Mapping):
        problems.fault(at, 'a tolerance is {"plus": ..., "minus": ...}')
        return None
    before = len(problems.faults)
    unknown = unknown_keys(raw, ("plus", "minus"))
    if unknown:
        problems.fault(at, f"unknown field(s) {unknown}")
    if not {"plus", "minus"} & set(raw):
        problems.fault(at, "a tolerance gives plus, minus or both")
    bounds: dict[str, float] = {}
    for side in ("plus", "minus"):
        if side not in raw:
            if {"plus", "minus"} & set(raw):
                problems.note(at + pointer(side), f"{side} not given: read as 0")
            bounds[side] = 0.0
            continue
        number = read_number(raw[side], at + pointer(side), problems)
        if number is None:
            continue
        if side == "minus" and number < 0:
            # "-0.1" below is the same tolerance as 0.1 below: syntax, noted.
            problems.note(at + pointer(side), f"minus {number:g} read as {-number:g}")
            number = -number
        if side == "plus" and number < 0:
            problems.fault(at + pointer(side), "plus is how far above, 0 or more")
            continue
        bounds[side] = number
    if len(problems.faults) > before:
        return None
    if bounds["plus"] == 0 and bounds["minus"] == 0:
        problems.fault(at, "+0/-0 is no tolerance: leave the tolerance out")
        return None
    return Tolerance(bounds["plus"], bounds["minus"])


def read_value(
    raw: Any,
    at: str,
    problems: Problems,
    allow: tuple[str, ...] = ("words", "table", "formula", "assumed"),
) -> Value | None:
    """Read one value, reporting every fault in it."""
    if not isinstance(raw, Mapping):
        problems.fault(at, 'a value is {"value": ..., "unit": ..., "from": ...}')
        return None
    before = len(problems.faults)
    unknown = unknown_keys(raw, ("value", "unit", "tolerance", "from"))
    if unknown:
        problems.fault(at, f"unknown field(s) {unknown}")
    number = read_number(raw.get("value"), at + pointer("value"), problems)
    unit_text = raw.get("unit")
    unit = None
    if not isinstance(unit_text, str) or not unit_text.strip():
        problems.fault(at + pointer("unit"), "a unit is required, angles included")
    else:
        try:
            unit = parse_unit(unit_text)
        except (ForgeUnitsError, ValueError, OverflowError) as exc:
            problems.fault(at + pointer("unit"), f"unknown unit {unit_text!r}: {exc}")
        else:
            if not _allowed_unit(unit):
                problems.fault(
                    at + pointer("unit"),
                    f"{unit_text!r} has no dimension; a value's unit is a length, "
                    "an angle (deg, rad), %, or another real unit; a number of "
                    "things is a count",
                )
                unit = None
            elif unit.symbol not in known_units():
                # "mm*mm/mm" parses to a length, but as its own symbol: the
                # same size could then be written two ways, with two hashes.
                problems.fault(
                    at + pointer("unit"),
                    f"write the unit as one symbol (mm, cm, m, in, ft, deg, rad), not {unit_text!r}",
                )
                unit = None
            elif unit.symbol != unit_text.strip():
                problems.note(
                    at + pointer("unit"), f"unit {unit_text!r} read as {unit.symbol!r}"
                )
    tolerance = None
    if raw.get("tolerance") is not None:
        tolerance = _tolerance(raw["tolerance"], at + pointer("tolerance"), problems)
    provenance = read_provenance(raw.get("from"), at + pointer("from"), problems, allow)
    if (
        len(problems.faults) > before
        or number is None
        or unit is None
        or provenance is None
    ):
        return None
    return Value(Q(number, unit), provenance, tolerance)


def read_count(raw: Any, at: str, problems: Problems) -> Count | None:
    """Read one count, reporting every fault in it. A count isn't in any table."""
    if not isinstance(raw, Mapping):
        problems.fault(at, 'a count is {"count": ..., "from": ...}')
        return None
    before = len(problems.faults)
    unknown = unknown_keys(raw, ("count", "from"))
    if unknown:
        problems.fault(at, f"unknown field(s) {unknown}")
    n = raw.get("count")
    whole: int | None = None
    if (
        isinstance(n, bool)
        or not isinstance(n, (int, float))
        or (isinstance(n, float) and not (math.isfinite(n) and n.is_integer()))
    ):
        problems.fault(at + pointer("count"), f"a count is a whole number, got {n!r}")
    elif n < 0:
        problems.fault(at + pointer("count"), "a count can't be negative")
    elif n > MAX_COUNT:
        problems.fault(
            at + pointer("count"), f"a count above {MAX_COUNT:,} is not a part"
        )
    else:
        whole = int(n)
        if isinstance(n, float):
            problems.note(at + pointer("count"), f"count {n!r} read as {whole}")
    provenance = read_provenance(
        raw.get("from"), at + pointer("from"), problems, ("words", "formula", "assumed")
    )
    if len(problems.faults) > before or whole is None or provenance is None:
        return None
    return Count(whole, provenance)


def check_citation(item: Value | Count, brief: NumberedBrief) -> CitationCheck | None:
    """Check a brief-sourced value against its words; None for other sources.

    Table entries and formulas are checked by the modules that own them; an
    assumption has no words to check.
    """
    if item.provenance.source is not Source.BRIEF:
        return None
    if isinstance(item, Count):
        return check_count(item.n, brief, item.provenance.words)
    return check_quantity(item.quantity, brief, item.provenance.words)
