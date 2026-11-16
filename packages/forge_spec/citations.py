"""Does a value really follow from the words it cites?

A spec value that says it came from the brief cites word numbers
(:mod:`forge_spec.words`). This module reads the numbers in those words and
checks the arithmetic: "1 1/2 in" must be 38.1 mm, "M4" can be 4 mm, "four" can
be a count of 4, and "2.8 mm" can't be 2.5 mm. It stops a number from being
misheard, mistyped or invented on its way from the brief into the spec.

It does **not** decide what a number means. Words are often ambiguous ("2 in
each corner" is two of something, or two inches; "3,4" is a list, or 3.4), so
every plausible reading of the cited words is listed, and a value is accepted
if a reading gives it. Picking the right meaning is the job of the spec
writer, the second draft and the person confirming the preview. A reading
that needs a second look (a sign the brief doesn't show, "in" read as inches,
a comma read as a decimal point) is accepted with a caveat, so the preview can
show it.

Three rules keep the leniency from becoming a hole:

- **A citation is one number.** The reading that gives the value must use a
  number from every numeric word the citation cites. A hole's diameter citing
  "5 mm ... 2 mm" doesn't follow, so a second number can't hide inside
  another value's citation and escape being accounted for.
- **A number with its own unit isn't a count.** "4 mm" can't be read as 4
  holes. (A unit lent along a chain, as in "4 x M3 screws", doesn't count.)
- **A conversion is exact unless the brief's number can't be.** 1/2 in is
  12.7 mm exactly; 1/3 in may be rounded to 8.467 or 8.47 mm, never 8.5.

A word can hold several numbers ("60x40x10mm", "M4x0.7", "5'6\\""). Each is a
**slot**, and a reading records which slots of which words it used, so that
accounting (:mod:`forge_spec.accounting`) can insist on every slot being used,
not just every word.

Readings come from:

- **numerals:** ``4``, ``2.8``, ``.5``, ``1,000``, ``2,8``, ``1/2``, ``1-1/2``,
  ``1½``;
- **number words, alone, in compounds and in phrases:** "four", "four-hole",
  "half-inch", "twenty four", "half a dozen", "two hundred fifty", "one and a
  half", "two thirds", "3 dozen";
- **mixed and compound measures:** "1 1/2 in", ``5'6"``;
- **designations:** ``M4`` and ``M4x0.7`` (metric threads, millimetres
  implied), ``1/4-20``, ``#6``, ``Ø2.8``, ``R5``.

A unit comes from the word itself (``12mm``, ``30°``, ``2"``, ``2-inch``),
from the word straight after the number, or from the end of a chain that
shares it ("60 x 40 x 10 mm", "10 to 12 mm", "10-12mm"). A number whose words
give no unit can still match the value, but the verdict then says the unit
was not stated, so it becomes an assumption the person sees.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from forge_numeric import scalar as fs
from forge_units import ForgeUnitsError, Q, Quantity, Unit, parse_unit
from forge_units.dimension import DIMENSIONLESS

from .words import NumberedBrief, WordRef

__all__ = [
    "CHAIN_JOINERS",
    "NUMBER_WORDS",
    "CitationCheck",
    "Follows",
    "Reading",
    "Slot",
    "check_count",
    "check_quantity",
    "is_numeric_word",
    "numeric_at",
    "phrase_value",
    "readings",
    "slot_count",
    "unit_after",
    "unit_of_word",
]

#: One number inside one word: (word number, position of the number in the word).
Slot = tuple[int, int]

# ----------------------------------------------------------------------
# Number words
# ----------------------------------------------------------------------
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9}  # fmt: skip
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
          "nineteen": 19}  # fmt: skip
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}  # fmt: skip
_SCALES = {"hundred": 100, "hundreds": 100, "thousand": 1000, "thousands": 1000}
_GROUPS = {"dozen": 12, "dozens": 12, "pair": 2, "pairs": 2}
_DENOMINATORS = {"half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4,
                 "quarters": 4, "fourth": 4, "fourths": 4, "fifth": 5, "fifths": 5,
                 "sixth": 6, "sixths": 6, "eighth": 8, "eighths": 8, "tenth": 10,
                 "tenths": 10}  # fmt: skip
_SINGLES = {"both": 2, "single": 1, "double": 2, "twice": 2, "triple": 3, "dual": 2,
            "twin": 2, "quad": 4, "quadruple": 4, "once": 1, "thrice": 3}  # fmt: skip
_CONNECTORS = frozenset({"and", "a", "an"})

#: Every word that states a number, and so must be accounted for in a brief.
NUMBER_WORDS: frozenset[str] = frozenset(
    {*_ONES, *_TEENS, *_TENS, *_SCALES, *_GROUPS, *_DENOMINATORS, *_SINGLES}
)


def _cardinal(tokens: Sequence[str]) -> float | None:
    """'two hundred and fifty' -> 250; None unless the words are a cardinal."""
    total = current = 0
    last = ""
    for word in tokens:
        if word in _ONES:
            if last in ("one", "teen"):
                return None
            current += _ONES[word]
            last = "one"
        elif word in _TEENS or word in _TENS:
            if last in ("one", "teen", "tens"):
                return None
            current += _TEENS.get(word, 0) + _TENS.get(word, 0)
            last = "teen" if word in _TEENS else "tens"
        elif word in ("hundred", "hundreds"):
            if current >= 100:
                return None
            current = (current or 1) * 100
            last = "hundred"
        elif word in ("thousand", "thousands"):
            total += (current or 1) * 1000
            current = 0
            last = "thousand"
        elif word == "and" and last in ("hundred", "thousand"):
            last = "and"
        else:
            return None
    if not last or last == "and":
        return None
    return float(total + current)


def phrase_value(tokens: Sequence[str]) -> float | None:
    """The number a run of number words states, or None.

    >>> [phrase_value(p.split()) for p in ("twenty four", "half a dozen",
    ...     "two hundred fifty", "one and a half", "two thirds", "a dozen")]
    [24.0, 6.0, 250.0, 1.5, 0.6666666666666666, 12.0]
    """
    t = [w.lower() for w in tokens]
    if not t:
        return None
    if len(t) == 1 and t[0] in _SINGLES:
        return float(_SINGLES[t[0]])
    if len(t) >= 4 and t[-3:] == ["and", "a", "half"]:
        base = phrase_value(t[:-3])
        return None if base is None else base + 0.5
    if t[0] == "half" and t[1:2] in (["a"], ["an"]):
        t = ["half", *t[2:]]  # "half a dozen" is "half dozen"
    if len(t) == 2 and t[0] == "half" and (t[1] in _GROUPS or t[1] in _SCALES):
        return {**_GROUPS, **_SCALES}[t[1]] / 2
    if t[0] in ("a", "an"):
        rest = t[1:]
        if rest and (
            rest[0] in _SCALES or rest[0] in _GROUPS or rest[0] in _DENOMINATORS
        ):
            return phrase_value(["one", *rest])
        return None
    for table, combine in (
        (_GROUPS, float.__mul__),
        (_DENOMINATORS, float.__truediv__),
    ):
        if t[-1] in table:
            n = 1.0 if len(t) == 1 else _cardinal(t[:-1])
            return None if n is None else combine(n, float(table[t[-1]]))
    return _cardinal(t)


# ----------------------------------------------------------------------
# Units
# ----------------------------------------------------------------------
#: Units a brief may state for a number. Anything else that parses ("A",
#: "s", "h", "t", "day") is far more often a word than a unit after a number.
_BRIEF_UNITS = frozenset(
    {
        "mm", "cm", "m", "um", "in", "ft", "mil",
        "mm^2", "cm^2", "m^2", "in^2", "mm^3", "cm^3", "m^3", "in^3",
        "deg", "rad", "rev", "arcmin", "arcsec",
        "g", "kg", "mg", "lb", "oz",
        "N", "kN", "mN", "lbf", "kgf",
        "Pa", "kPa", "MPa", "GPa", "bar", "psi",
        "Nm", "Nmm", "kNm",
        "%",
        "degC", "degF", "K",
    }
)  # fmt: skip
_ANGLE_UNITS = frozenset({"rad", "deg", "rev", "arcmin", "arcsec"})
#: Spellings forge_units doesn't know but briefs use.
_ALIASES = {
    "lbs": "lb",
    "kgs": "kg",
    "degs": "deg",
    "\u00ba": "deg",  # masculine ordinal, typed for a degree sign
    "\u02da": "deg",  # ring above
    "''": "in",
    '"': "in",
    "\u2033": "in",
    "\u201d": "in",
    "'": "ft",
    "\u2032": "ft",
    "\u2019": "ft",
}
_INVISIBLE = {"\u00ad": "", "\u200c": "", "\u200d": "", "\u200b": " ", "\u2060": " ",
              "\ufeff": "", "\u2011": "-", "\u2010": "-", "\u2044": "/"}  # fmt: skip


def _plain(text: str) -> str:
    """Text with invisible characters removed and look-alike marks unified.

    Every replacement is one character for one or for none, before any
    position is taken, so positions are always positions in the plain text.
    """
    return "".join(_INVISIBLE.get(c, c) for c in text)


@functools.lru_cache(maxsize=8192)
def unit_of_word(text: str) -> Unit | None:
    """The unit a word names, if it is one a brief may state for a number.

    >>> unit_of_word("millimetres").symbol
    'mm'
    >>> unit_of_word("holes") is None
    True
    """
    plain = _plain(text)
    candidates = [plain, _ALIASES.get(plain, plain)]
    if len(plain) >= 2:
        candidates += [plain.lower(), _ALIASES.get(plain.lower(), plain.lower())]
    if len(plain) >= 4 and plain.lower().endswith("s"):
        candidates.append(plain.lower()[:-1])
    for candidate in candidates:
        try:
            unit = parse_unit(candidate)
        except (ForgeUnitsError, ValueError, OverflowError):
            continue
        if unit.symbol in _BRIEF_UNITS:
            return unit
    return None


def _same_kind(left: Unit, right: Unit) -> bool:
    """Same dimension, with angles kept apart from plain ratios.

    Angles are dimensionless in forge_units (ADR-0004), so without this a
    brief's "30 deg" could be read as a value of 52 %.
    """
    if left.dimension != right.dimension:
        return False
    if left.dimension == DIMENSIONLESS:
        return (left.symbol in _ANGLE_UNITS) == (right.symbol in _ANGLE_UNITS)
    return True


# ----------------------------------------------------------------------
# Numbers inside one word
# ----------------------------------------------------------------------
_VULGAR: Mapping[str, float] = {
    "\u00bd": 1 / 2,
    "\u2153": 1 / 3,
    "\u2154": 2 / 3,
    "\u00bc": 1 / 4,
    "\u00be": 3 / 4,
    "\u2155": 1 / 5,
    "\u2156": 2 / 5,
    "\u2157": 3 / 5,
    "\u2158": 4 / 5,
    "\u2159": 1 / 6,
    "\u215a": 5 / 6,
    "\u215b": 1 / 8,
    "\u215c": 3 / 8,
    "\u215d": 5 / 8,
    "\u215e": 7 / 8,
    "\u2152": 1 / 10,
}  # fmt: skip  (the vulgar fractions: 1/2 1/3 2/3 1/4 3/4 ... 7/8 1/10)
_VULGAR_CLASS = "".join(_VULGAR)
_LITERAL = re.compile(
    rf"""
      (?P<mixed>(?P<mw>\d+)-(?P<mn>\d+)/(?P<md>\d+))
    | (?P<frac>(?P<fn>\d+)/(?P<fd>\d+))
    | (?P<vulgar>(?P<vw>\d+)?(?P<vc>[{_VULGAR_CLASS}]))
    | (?P<dec>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+\.\d+|\d+|\.\d+)
    """,
    re.VERBOSE,
)
_DECIMAL_COMMA = re.compile(r"(?<![\d,.])(\d+),(\d+)(?![\d,])")
_FEET_INCHES = re.compile(
    r"^(\d+(?:\.\d+)?)['\u2032\u2019](\d+(?:\.\d+)?)[\"\u2033\u201d]$"
)
_UNIT_CHARS = re.compile(
    "-?([A-Za-z\u00b5\u03bc\u00b0\u00ba\u02da\"'\u2033\u2032\u201d\u2019%^\u00b2\u00b3]+)"
)
_IN_WORD_JOINERS = frozenset({"x", "X", "\u00d7", "*", "-", "\u2013"})
#: Words (or word starts) after "3D"/"2D" that make it a kind of thing.
_DIMENSIONAL_KIND = re.compile(
    r"^(?:print|model|scan|render|draw|sketch|view|cad|design)", re.IGNORECASE
)
_KIND_IN_WORD = re.compile(
    r"^[23][dD]-?(?:print|model|scan|render|draw|sketch|view)", re.IGNORECASE
)
_DESIGNATIONS = {"M": "metric thread", "m": "metric thread", "#": "screw number",
                 "R": "radius", "r": "radius", "\u00d8": "diameter", "\u2300": "diameter",
                 "\u00f8": "diameter", "\u00b1": "tolerance"}  # fmt: skip
#: Longer numerals than any real brief has; refused cheaply, never parsed.
_MAX_DIGITS = 30
_LETTER_RUN = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True)
class _Literal:
    value: float
    unit: Unit | None
    form: str
    span: tuple[int, int]
    #: The unit is only implied (by a designation such as "M4"); it isn't
    #: lent along a chain to other numbers.
    implied: bool = False


def _literal_value(match: re.Match[str]) -> tuple[float, str] | None:
    if len(match.group()) > _MAX_DIGITS:
        return None
    try:
        if match.group("mixed"):
            whole, num, den = (int(match.group(k)) for k in ("mw", "mn", "md"))
            return (whole + num / den, "mixed") if den else None
        if match.group("frac"):
            num, den = int(match.group("fn")), int(match.group("fd"))
            return (num / den, "fraction") if den else None
        if match.group("vulgar"):
            whole = int(match.group("vw")) if match.group("vw") else 0
            return whole + _VULGAR[match.group("vc")], "vulgar"
        text = match.group("dec")
        value = float(text.replace(",", ""))
    except (OverflowError, ValueError):
        return None
    form = "thousands" if "," in text else "decimal"
    return (value, form) if math.isfinite(value) else None


@functools.lru_cache(maxsize=8192)
def _slots(text: str) -> tuple[tuple[int, int], ...]:
    """Where the numbers are in a word: numerals and number-word tokens."""
    plain = _plain(text)
    spans = [m.span() for m in _LITERAL.finditer(plain)]
    spans += [
        m.span()
        for m in _LETTER_RUN.finditer(plain)
        if m.group().lower() in NUMBER_WORDS
        or (
            m.group().lower().endswith("fold")
            and m.group().lower()[:-4] in NUMBER_WORDS
        )
    ]
    if not spans and any(c.isnumeric() for c in plain):
        spans = [(0, len(plain))]  # a digit no reading can parse: still a number
    return tuple(sorted(spans))


def _slots_within(text: str, span: tuple[int, int]) -> tuple[int, ...]:
    return tuple(
        k for k, (a, b) in enumerate(_slots(text)) if span[0] <= a and b <= span[1]
    )


def _unit_in_gap(gap: str) -> Unit | None:
    """A unit straight after a number in the same word: "mm", "-inch", "°"."""
    match = _UNIT_CHARS.match(gap)
    return unit_of_word(match.group(1)) if match else None


@functools.lru_cache(maxsize=8192)
def _numerals(text: str) -> tuple[_Literal, ...]:
    """The numerals inside one word, each with any unit the word gives it."""
    plain = _plain(text)
    feet_inches = _FEET_INCHES.match(plain)
    if feet_inches:
        a, b = feet_inches.span(1), feet_inches.span(2)
        feet, inches = float(feet_inches.group(1)), float(feet_inches.group(2))
        return (
            _Literal(feet, parse_unit("ft"), "decimal", a),
            _Literal(inches, parse_unit("in"), "decimal", b),
            _Literal(
                feet * 12 + inches, parse_unit("in"), "feet and inches", (a[0], b[1])
            ),
        )
    matches = list(_LITERAL.finditer(plain))
    parsed: list[tuple[_Literal, bool]] = []
    for position, match in enumerate(matches):
        parsed_value = _literal_value(match)
        if parsed_value is None:
            continue
        value, form = parsed_value
        before = plain[matches[position - 1].end() if position else 0 : match.start()]
        mark = before[-1:] if before[:-1] in ("", *_IN_WORD_JOINERS) else ""
        designation = (
            _DESIGNATIONS.get(mark) if before[:-1] in ("", *_IN_WORD_JOINERS) else None
        )
        if position == 0 and before in ("-", "\u2212"):
            value = -value
        end = (
            matches[position + 1].start() if position + 1 < len(matches) else len(plain)
        )
        gap = plain[match.end() : end]
        unit, implied = _unit_in_gap(gap), False
        if unit is None and mark in ("M", "m"):
            unit, implied = parse_unit("mm"), True
        label = f"{form} ({designation})" if designation else form
        joined = position + 1 < len(matches) and gap.strip() in _IN_WORD_JOINERS
        parsed.append((_Literal(value, unit, label, match.span(), implied), joined))

    out: list[_Literal] = []
    chain: list[_Literal] = []
    for item, joined in parsed:
        chain.append(item)
        if joined:
            continue
        # A chain inside one word ("60x40x10mm", "M4x0.7", "10-12mm") shares
        # the unit at its end, or the one its first number's designation
        # implies (the pitch of "M4x0.7" is in millimetres too).
        explicit = next(
            (x.unit for x in reversed(chain) if x.unit and not x.implied), None
        )
        shared, implied = (
            (explicit, False) if explicit else (chain[0].unit, chain[0].implied)
        )
        for x in chain:
            if x.unit is None and shared is not None:
                out.append(_Literal(x.value, shared, x.form, x.span, implied))
            else:
                out.append(x)
        chain = []
    # "2,8" may be a decimal comma: offered beside the English reading, with
    # a caveat, never instead of it.
    for match in _DECIMAL_COMMA.finditer(plain):
        if len(match.group()) <= _MAX_DIGITS:
            unit = _unit_in_gap(plain[match.end() :])
            out.append(
                _Literal(
                    float(f"{match.group(1)}.{match.group(2)}"),
                    unit,
                    "decimal comma",
                    match.span(),
                )
            )
    return tuple(out)


def _word_number_runs(text: str) -> list[tuple[float, tuple[int, int], Unit | None]]:
    """Number-word runs inside one word: 'one-and-a-half' -> 1.5, 'half-inch' -> 0.5 in."""
    plain = _plain(text)
    tokens = [(m.group().lower(), m.span()) for m in _LETTER_RUN.finditer(plain)]
    found: list[tuple[float, tuple[int, int], Unit | None]] = []
    run: list[tuple[str, tuple[int, int]]] = []
    for position, item in enumerate([*tokens, ("", (len(plain), len(plain)))]):
        token = item[0]
        if token in NUMBER_WORDS or (token in _CONNECTORS and run):
            run.append(item)
            continue
        while run and run[-1][0] in _CONNECTORS:
            run.pop()
        if run:
            unit = unit_of_word(token) if token else None
            span = (run[0][1][0], run[-1][1][1])
            whole = phrase_value([t for t, _ in run])
            if whole is not None:
                found.append((whole, span, unit))
            else:
                for t, s in run:
                    single = phrase_value([t])
                    if single is not None:
                        found.append((single, s, None))
        run = [item] if token in ("a", "an") and position < len(tokens) else []
    return found


@functools.lru_cache(maxsize=8192)
def is_numeric_word(text: str) -> bool:
    """Whether a word states a number that must be accounted for.

    Context-free; :func:`numeric_at` also knows "3D" in "3D printed" is a kind
    of thing, not a size.

    >>> [is_numeric_word(w) for w in ("4", "M3", "four-hole", "pair", "plate",
    ...                               "a", "3D-printed", "mm\\u00b2", "half-ball")]
    [True, True, True, True, False, False, False, False, True]
    """
    plain = _plain(text)
    if _KIND_IN_WORD.match(plain) or unit_of_word(plain) is not None:
        return False
    return bool(_slots(plain))


def numeric_at(brief: NumberedBrief, index: int) -> bool:
    """Whether the word at ``index`` states a number, given its neighbours."""
    known = brief.memo.get("numeric")
    if known is None:
        known = brief.memo["numeric"] = tuple(
            _numeric(brief, i) for i in range(len(brief.words))
        )
    return bool(known[index])


def _numeric(brief: NumberedBrief, index: int) -> bool:
    word = brief.words[index]
    if re.fullmatch(r"[23][dD]", word.text) and index + 1 < len(brief.words):
        after = brief.words[index + 1]
        if after.sentence == word.sentence and _DIMENSIONAL_KIND.match(after.text):
            return False
    if word.text.lower() == "both" and _correlative(brief, index):
        return False
    return is_numeric_word(word.text)


#: What ends a clause between two words.
_CLAUSE_END = re.compile(r"[,;:.!?()\[\]{}]")
#: How many words, at most, the first of the two things "both ... and" pairs takes.
_PAIRED = 3


def _correlative(brief: NumberedBrief, index: int) -> bool:
    """Whether "both" at ``index`` pairs two things with "and" later in its clause ("through both the flange and the hub"): a conjunction, not a count of two.

    "Both ends" and "both halfway along" count; "both A and B" names A and B,
    each counted where it is said. The first thing named is short ("the
    flange"): an "and" further on joins clauses ("along both long edges of the
    base and the box is 30 mm tall"), and "both" counts. Unsure, it counts:
    a count nothing uses is a question, a count passed over is a check lost.

    >>> from forge_spec.words import number_words
    >>> b = number_words("A bore through both the flange and the hub. Holes on both ends, and a slot. "
    ...                  "Walls stand along both long edges of the base and the box is 30 mm tall.")
    >>> [_numeric(b, w.index) for w in b.words if w.text == "both"]
    [False, True, True]
    """
    word = brief.words[index]
    previous = word
    for later in brief.words[index + 1 : index + 2 + _PAIRED]:
        if later.sentence != word.sentence or _CLAUSE_END.search(
            brief.text[previous.end : later.start]
        ):
            return False
        if later.text.lower() == "and":
            return True
        previous = later
    return False


def slot_count(brief: NumberedBrief, index: int) -> int:
    """How many numbers the word at ``index`` holds (0 if it is no number)."""
    return len(_slots(brief.words[index].text)) if numeric_at(brief, index) else 0


# ----------------------------------------------------------------------
# Units across words
# ----------------------------------------------------------------------
CHAIN_JOINERS = frozenset({"x", "\u00d7", "*", "by", "to", "and", "or"})


def _is_bare_fraction(text: str) -> bool:
    literals = _numerals(text)
    return len(literals) == 1 and literals[0].form in ("fraction", "vulgar")


@dataclass(frozen=True)
class _UnitAfter:
    word: int
    unit: Unit
    #: True when the unit word follows the number directly ("4 mm"); False
    #: when it was lent along a chain ("4 x 3 mm", "60 x 40 x 10 mm").
    direct: bool
    #: The chain could as well be a count and a size: two numbers joined by
    #: "x" ("4 x 3 mm holes"), or numbers joined by "and"/"or" ("2 and 10 mm
    #: spacers"). Three or more sizes joined by "x", or "by", "to", aren't.
    unsure: bool


_TIMES = frozenset({"x", "\u00d7", "*"})


@dataclass
class _Chain:
    """Numbers sharing one unit, collected right to left."""

    carry: tuple[int, Unit] | None = None
    members: list[tuple[int, bool]] = field(default_factory=list)
    joiners: list[str] = field(default_factory=list)
    size: int = 0  # numbers in the chain, the one owning the unit included

    def finish(self, found: dict[int, _UnitAfter]) -> None:
        if self.carry is not None:
            unsure = any(j in ("and", "or") for j in self.joiners) or (
                self.size == 2
                and bool(self.joiners)
                and all(j in _TIMES for j in self.joiners)
            )
            word, unit = self.carry
            for j, direct in self.members:
                found[j] = _UnitAfter(word, unit, direct, unsure and not direct)
        self.carry, self.members, self.joiners, self.size = None, [], [], 0


def _chains_in(
    brief: NumberedBrief, words: range, found: dict[int, _UnitAfter]
) -> None:
    """Record, for one sentence, which numbers take their unit from a later word."""
    chain = _Chain()
    state = ""  # what lies to the right: "unit", "number", "fraction", "joiner"
    for j in reversed(words):
        text = brief.words[j].text
        unit = unit_of_word(text)
        if unit is not None:
            chain.finish(found)
            chain.carry, state = (j, unit), "unit"
            continue
        if numeric_at(brief, j):
            own = next(
                (x.unit for x in _numerals(text) if x.unit and not x.implied), None
            )
            mixed = state == "fraction" and re.fullmatch(r"\d+", text) is not None
            if not (state in ("unit", "joiner") or mixed):
                chain.finish(found)
            elif chain.carry is not None and own is None:
                chain.members.append((j, state == "unit" or mixed))
                chain.size += 1
            if own is not None:
                chain.finish(found)
                chain.carry, chain.size = (j, own), 1  # "10 to 12mm": this word's unit
            state = "fraction" if _is_bare_fraction(text) else "number"
            continue
        if text.lower() in CHAIN_JOINERS and state in ("number", "fraction"):
            chain.joiners.append(text.lower())
            state = "joiner"
            continue
        chain.finish(found)
        state = ""
    chain.finish(found)


def unit_after(brief: NumberedBrief) -> Mapping[int, _UnitAfter]:
    """For each number given its unit by a later word: that word and the unit.

    Follows chains that share one unit ("60 x 40 x 10 mm", "10 to 12 mm",
    "1 1/2 in", "1 1/2\\"") within a sentence. Worked out once per brief, right
    to left, and kept in the brief's memo.
    """
    cached = brief.memo.get("unit_after")
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    found: dict[int, _UnitAfter] = {}
    for sentence in brief.sentences:
        _chains_in(brief, sentence.words, found)
    brief.memo["unit_after"] = found
    return found


# ----------------------------------------------------------------------
# Readings
# ----------------------------------------------------------------------
class Follows(str, Enum):
    """Whether a value follows from the words it cites."""

    YES = "yes"
    #: It follows, but only by a reading the person should see: a sign the
    #: brief doesn't show, "in" read as inches, a comma read as a decimal point.
    YES_WITH_CAVEAT = "yes_with_caveat"
    #: The number is there, but no cited or neighbouring word gives its unit.
    UNIT_NOT_STATED = "unit_not_stated"
    NO = "no"


@dataclass(frozen=True)
class Reading:
    """One way the cited words can be read as a number.

    ``numbers`` are the slots (word, position in the word) whose numbers the
    reading uses. ``words`` are every word it uses, the word its unit came
    from included. They differ on purpose: in "1 1/2\\"", reading "1" with the
    inch mark of "1/2\\"" uses the second word's unit, not its number, and
    accounting must not count that number as used.
    """

    value: float
    unit: Unit | None
    numbers: tuple[Slot, ...]
    words: WordRef
    form: str
    #: The unit was lent along a chain rather than stated next to the number.
    chained: bool = False
    #: ...along a chain that could as well be a count and a size (see
    #: ``_UnitAfter.unsure``), so the reading is shown with a caveat.
    unsure: bool = False

    @property
    def number_words(self) -> WordRef:
        return tuple(sorted({word for word, _ in self.numbers}))

    def describe(self) -> str:
        number = f"{self.value:g}"
        return f"{number} {self.unit.symbol}" if self.unit is not None else number


@dataclass(frozen=True)
class CitationCheck:
    """The verdict on one cited value, with the readings it was judged by."""

    follows: Follows
    reading: Reading | None
    candidates: tuple[Reading, ...]
    message: str


def _reading(
    value: float,
    unit: Unit | None,
    numbers: Iterable[Slot],
    extra: Iterable[int],
    form: str,
    chained: bool = False,
    unsure: bool = False,
) -> Reading:
    slots = tuple(sorted(set(numbers)))
    words = tuple(sorted({w for w, _ in slots} | set(extra)))
    return Reading(value, unit, slots, words, form, chained, unsure)


def _with_unit_after(
    brief: NumberedBrief,
    value: float,
    numbers: Sequence[Slot],
    last: int,
    form: str,
    extra: Iterable[int] = (),
) -> list[Reading]:
    out = [_reading(value, None, numbers, extra, form)]
    following = unit_after(brief).get(last)
    if following is not None:
        out.append(
            _reading(
                value,
                following.unit,
                numbers,
                [*extra, following.word],
                form,
                chained=not following.direct,
                unsure=following.unsure,
            )
        )
    return out


def _readings_of_word(brief: NumberedBrief, index: int) -> list[Reading]:
    if not numeric_at(brief, index):
        return []
    text = brief.words[index].text
    found: list[Reading] = []
    for literal in _numerals(text):
        slots = [(index, k) for k in _slots_within(text, literal.span)]
        if literal.unit is not None:
            found.append(_reading(literal.value, literal.unit, slots, (), literal.form))
        else:
            found += _with_unit_after(brief, literal.value, slots, index, literal.form)
    for value, span, unit in _word_number_runs(text):
        slots = [(index, k) for k in _slots_within(text, span)]
        if unit is not None:
            found.append(_reading(value, unit, slots, (), "words"))
        else:
            found += _with_unit_after(brief, value, slots, index, "words")
    return found


def _all_slots(brief: NumberedBrief, index: int) -> list[Slot]:
    return [(index, k) for k in range(slot_count(brief, index))]


def _plain_integer(text: str) -> int | None:
    return int(text) if re.fullmatch(r"\d{1,30}", text) else None


def _touching(brief: NumberedBrief, i: int, j: int) -> bool:
    """Whether words ``i`` and ``j`` (= i + 1) have only spaces between them.

    One number may be written over words ("1 1/2 in", "twenty four"), never
    across a comma or other mark: "1, 1/2 and 1/4 in" is three numbers.
    """
    return not brief.text[brief.words[i].end : brief.words[j].start].strip()


def _combined(brief: NumberedBrief, cited: Sequence[int]) -> list[Reading]:
    """Readings that need two or more adjacent cited words, with only spaces between them."""
    found: list[Reading] = []
    chosen = set(cited)
    for i in cited:
        nxt = i + 1
        if nxt not in chosen or not _touching(brief, i, nxt):
            continue
        here, there = brief.words[i].text, brief.words[nxt].text
        whole = _plain_integer(here)
        fraction = _numerals(there)
        # "1 1/2 in", "1 1/2\""
        if (
            whole is not None
            and len(fraction) == 1
            and fraction[0].form in ("fraction", "vulgar")
        ):
            slots = [*_all_slots(brief, i), *_all_slots(brief, nxt)]
            value = whole + fraction[0].value
            if fraction[0].unit is not None:
                found.append(_reading(value, fraction[0].unit, slots, (), "mixed"))
            else:
                found += _with_unit_after(brief, value, slots, nxt, "mixed")
        # "5' 6\""
        feet, inches = _numerals(here), fraction
        if (
            len(feet) == 1
            and feet[0].unit
            and feet[0].unit.symbol == "ft"
            and len(inches) == 1
            and inches[0].unit
            and inches[0].unit.symbol == "in"
        ):
            slots = [*_all_slots(brief, i), *_all_slots(brief, nxt)]
            total = feet[0].value * 12 + inches[0].value
            found.append(_reading(total, inches[0].unit, slots, (), "feet and inches"))
        # "3 dozen", "2 thousand", "2 pairs"
        scale = there.lower()
        if whole is not None and (scale in _SCALES or scale in _GROUPS):
            multiplier = {**_SCALES, **_GROUPS}[scale]
            slots = [*_all_slots(brief, i), *_all_slots(brief, nxt)]
            found += _with_unit_after(
                brief, float(whole * multiplier), slots, nxt, "words"
            )
    # Runs of whole number words: "twenty four", "half a dozen", "two hundred fifty".
    run: list[int] = []
    for i in [*cited, -1]:
        tokens = (
            _LETTER_RUN.findall(_plain(brief.words[i].text).lower()) if i >= 0 else []
        )
        wordy = (
            bool(tokens)
            and all(t in NUMBER_WORDS or t in _CONNECTORS for t in tokens)
            and not any(c.isdigit() for c in brief.words[i].text)
        )
        if (
            i >= 0
            and wordy
            and (not run or (i == run[-1] + 1 and _touching(brief, run[-1], i)))
        ):
            run.append(i)
            continue
        if len(run) >= 2:
            phrase = [
                t
                for k in run
                for t in _LETTER_RUN.findall(_plain(brief.words[k].text).lower())
            ]
            spoken = phrase_value(phrase)
            if spoken is not None:
                slots = [s for k in run for s in _all_slots(brief, k)]
                found += _with_unit_after(
                    brief, spoken, slots, run[-1], "words", extra=run
                )
        run = [i] if i >= 0 and wordy else []
    return found


def readings(brief: NumberedBrief, ref: Iterable[int]) -> tuple[Reading, ...]:
    """Every plausible reading of the numbers in the cited words."""
    cited = sorted(set(ref))
    for i in cited:
        brief.word(i)  # raises LookupError for a word that doesn't exist
    found: list[Reading] = []
    for i in cited:
        found += _readings_of_word(brief, i)
    found += _combined(brief, cited)
    unique: dict[tuple[object, ...], Reading] = {}
    for reading in found:
        symbol = reading.unit.symbol if reading.unit else ""
        key = (reading.value, symbol, reading.numbers, reading.words, reading.form)
        unique.setdefault(key, reading)
    return tuple(unique.values())


# ----------------------------------------------------------------------
# Verdicts
# ----------------------------------------------------------------------
def _terminates(value: float) -> bool:
    return abs(round(value, 6) - value) <= 1e-9 * max(1.0, abs(value))


def _matches(expected: float, actual: float, *, converted: bool) -> bool:
    """Equal; after a conversion that doesn't terminate, rounded sensibly.

    A converted value may be the exact one rounded to three or more
    significant figures, and never more than 1 part in 2,000 away. So 1/3 in
    can be 8.467 or 8.47 mm but not 8.5, and 2 m can't be 2001 mm.
    """
    scale = max(1.0, abs(expected))
    if abs(expected - actual) <= 1e-9 * scale:
        return True
    if not converted or _terminates(expected) or expected == 0:
        return False
    if abs(expected - actual) > 5e-4 * abs(expected):
        return False
    magnitude = fs.decade(abs(expected))
    return any(
        abs(round(expected, figures - 1 - magnitude) - actual) <= 1e-9 * scale
        for figures in range(3, 16)
    )


#: After "in", these make it read as a preposition as easily as inches.
_PREPOSITION_CUES = frozenset(
    {"a", "an", "the", "each", "every", "all", "both", "either", "its", "this",
     "that", "these", "those", "their", "total", "place", "line", "order", "half",
     "front", "common", "turn", "general", "between", "use", "one", "two", "three",
     "four"}
)  # fmt: skip


def _in_is_ambiguous(brief: NumberedBrief, reading: Reading) -> bool:
    """Whether the reading took "in" as inches where it may be a preposition.

    "a 1/2 in rod" is inches; "2 in each corner" is as likely two of
    something. Either way the reading is offered; this only decides whether
    the person is shown the caveat.
    """
    numbered = set(reading.number_words)
    for i in reading.words:
        if i in numbered or brief.words[i].text.lower() != "in":
            continue
        after = i + 1
        if (
            after < len(brief.words)
            and brief.words[after].sentence == brief.words[i].sentence
        ):
            following = brief.words[after].text.lower()
            if following in _PREPOSITION_CUES or numeric_at(brief, after):
                return True
    return False


def _cited(brief: NumberedBrief, ref: Iterable[int]) -> tuple[WordRef, str | None]:
    words = tuple(sorted(set(ref)))
    for i in words:
        try:
            brief.word(i)
        except LookupError as exc:
            return words, str(exc)
    return words, None


def _numeric_words_in(brief: NumberedBrief, ref: WordRef) -> set[int]:
    return {i for i in ref if numeric_at(brief, i)}


def _uses_each(reading: Reading, numeric_words: set[int]) -> bool:
    """The reading uses a number from every numeric word the citation cites."""
    return numeric_words <= set(reading.number_words)


def _not_usable(
    brief: NumberedBrief, numeric_words: set[int], candidates: tuple[Reading, ...]
) -> str:
    quoted = ", ".join(repr(brief.words[i].text) for i in sorted(numeric_words))
    if not candidates:
        return f"the cited number ({quoted}) can't be read as a number"
    if any(_uses_each(r, numeric_words) and _partial(brief, r) for r in candidates):
        return (
            f"{quoted} is only part of a number the brief writes over more words: "
            "cite all of it"
        )
    count = len(numeric_words)
    return (
        f"the citation holds {count} number{'s' if count != 1 else ''} ({quoted}) and "
        "no reading uses them all; a value cites the words of its own number only"
    )


def _partial(brief: NumberedBrief, reading: Reading) -> bool:
    """Whether a reading is only part of a number the brief writes over more words.

    "1" of "1 1/2 in" is not 1 inch, and "four" of "twenty four" is not 4,
    whether or not the rest of the number is cited: a value must use the
    whole of the brief's number.
    """
    used = {word for word, _ in reading.numbers}
    if not used:
        return False
    for neighbour in (min(used) - 1, max(used) + 1):
        if not 0 <= neighbour < len(brief.words) or not numeric_at(brief, neighbour):
            continue
        group = tuple(range(min(used | {neighbour}), max(used | {neighbour}) + 1))
        for larger in readings(brief, group):
            if used | {neighbour} <= {word for word, _ in larger.numbers}:
                return True
    return False


def _caveat(brief: NumberedBrief, reading: Reading) -> str | None:
    if reading.form.startswith("decimal comma"):
        return "the comma is read as a decimal point"
    if reading.form.startswith("thousands"):
        return "the comma is read as a thousands separator"
    if _in_is_ambiguous(brief, reading):
        return '"in" is read as inches here'
    if reading.unsure:
        return (
            "the unit is taken from further along; the numbers before it may be "
            "a count rather than a size"
        )
    return None


def check_quantity(
    value: Quantity, brief: NumberedBrief, ref: Iterable[int]
) -> CitationCheck:
    """Whether ``value`` follows from the cited words.

    >>> from forge_spec.words import number_words
    >>> brief = number_words("A 1 1/2 in pin.")
    >>> check_quantity(Q(38.1, "mm"), brief, (1, 2, 3)).follows
    <Follows.YES: 'yes'>
    """
    words, missing = _cited(brief, ref)
    if missing is not None:
        return CitationCheck(Follows.NO, None, (), missing)
    numeric = _numeric_words_in(brief, words)
    if not numeric:
        return CitationCheck(Follows.NO, None, (), "the cited words contain no number")
    candidates = readings(brief, words)
    usable = [
        r for r in candidates if _uses_each(r, numeric) and not _partial(brief, r)
    ]
    if not usable:
        return CitationCheck(
            Follows.NO, None, candidates, _not_usable(brief, numeric, candidates)
        )
    target = value.nominal
    affine = value.unit.is_affine
    for reading in usable:
        if reading.unit is None or not _same_kind(reading.unit, value.unit):
            continue
        expected = Q(reading.value, reading.unit).value_in(value.unit)
        converted = reading.unit.symbol != value.unit.symbol
        if _matches(expected, target, converted=converted):
            caveat = _caveat(brief, reading)
            if caveat:
                return CitationCheck(
                    Follows.YES_WITH_CAVEAT, reading, candidates, caveat
                )
            return CitationCheck(Follows.YES, reading, candidates, "follows")
        if not affine and _matches(abs(expected), abs(target), converted=converted):
            return CitationCheck(
                Follows.YES_WITH_CAVEAT,
                reading,
                candidates,
                f"the brief gives {reading.describe()}; the sign differs, which "
                "is right only if a direction carries it",
            )
    for reading in usable:
        if reading.unit is None and _matches(reading.value, target, converted=False):
            stated = [
                r for r in usable if r.unit is not None and r.value == reading.value
            ]
            if stated:
                return CitationCheck(
                    Follows.NO,
                    None,
                    candidates,
                    f"the brief states {stated[0].describe()}, not {target:g} "
                    f"{value.unit.symbol}",
                )
            return CitationCheck(
                Follows.UNIT_NOT_STATED,
                reading,
                candidates,
                f"the brief gives {reading.value:g} but no unit; {value.unit.symbol} "
                "is an assumption",
            )
    shown = ", ".join(r.describe() for r in usable)
    return CitationCheck(
        Follows.NO,
        None,
        candidates,
        f"{target:g} {value.unit.symbol} does not follow from the cited words "
        f"({brief.quote(words)!r} reads as {shown})",
    )


def check_count(n: int, brief: NumberedBrief, ref: Iterable[int]) -> CitationCheck:
    """Whether a count of ``n`` follows from the cited words."""
    words, missing = _cited(brief, ref)
    if missing is not None:
        return CitationCheck(Follows.NO, None, (), missing)
    numeric = _numeric_words_in(brief, words)
    if not numeric:
        articles = [i for i in words if brief.words[i].text.lower() in ("a", "an")]
        if n == 1 and articles:
            article = Reading(1.0, None, (), (articles[0],), "article")
            return CitationCheck(Follows.YES, article, (), "follows")
        return CitationCheck(Follows.NO, None, (), "the cited words contain no number")
    candidates = readings(brief, words)
    usable = [
        r for r in candidates if _uses_each(r, numeric) and not _partial(brief, r)
    ]
    if not usable:
        return CitationCheck(
            Follows.NO, None, candidates, _not_usable(brief, numeric, candidates)
        )
    # A number stated with its own unit ("4 mm", "M4") is a size. A unit lent
    # along a chain ("4 x M3 screws", "4 x 3 mm holes") doesn't make it one.
    sizes = [
        r
        for r in usable
        if r.unit is not None
        and r.value == n
        and not r.chained
        and not _in_is_ambiguous(brief, r)
    ]
    for reading in usable:
        if reading.unit is None and reading.value == n:
            if sizes:
                return CitationCheck(
                    Follows.NO,
                    None,
                    candidates,
                    f"the brief gives {sizes[0].describe()}: a size, not a count",
                )
            if reading.form.startswith(("decimal comma", "thousands")):
                return CitationCheck(
                    Follows.YES_WITH_CAVEAT,
                    reading,
                    candidates,
                    f"the comma is read as a "
                    f"{'decimal point' if reading.form.startswith('decimal') else 'thousands separator'}",
                )
            return CitationCheck(Follows.YES, reading, candidates, "follows")
    shown = ", ".join(r.describe() for r in usable)
    return CitationCheck(
        Follows.NO,
        None,
        candidates,
        f"a count of {n} does not follow from the cited words "
        f"({brief.quote(words)!r} reads as {shown})",
    )
