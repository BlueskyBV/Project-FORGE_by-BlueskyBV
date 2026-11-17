"""The spec checks: everything code can settle about a draft before anyone sees it.

:func:`check_draft` reads a draft, places every item, and checks:

- **the draft itself:** shape, kinds, fields, references (rule R8);
- **every value against the brief:** a value that says it came from the brief
  must follow from the words it cites (:mod:`forge_spec.citations`), and so
  must its tolerance; a value from a table must be the table's entry for a
  part the cited words name (:mod:`forge_spec.tables`); a worked-out value
  must come out of its formula, from cited numbers (:mod:`forge_spec.derived`);
  a choice must not cite words that name a different option; a text must be
  exactly the words it cites;
- **the whole brief is accounted for:** every number and sentence
  (:mod:`forge_spec.accounting`);
- **the placement:** counts, fits, overlaps, depths and walls
  (:mod:`forge_spec.placement`);
- **what can't be made:** a bore wider than its tube, a rounding larger than
  the edges it rounds, a thread on something it can't go on.

Each problem says where it goes next. A **fault** goes back to the spec
writer: the draft contradicts itself or misquotes the brief, and the person
should never see it. A **question** goes to the person. **cant** and
**unable** end the run honestly (plan, section 1.1). Questions and CAN'Ts
that rest on a value the writer assumed are faults
(:func:`forge_spec.placement.route`). Assumptions are not problems; they are
shown to the person first.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from forge_units import Q
from forge_units.dimension import LENGTH

from .accounting import FUNCTION_WORDS, MATERIAL, Accounting, account
from .citations import (
    Follows,
    Reading,
    check_count,
    check_quantity,
    numeric_at,
    readings,
    slot_count,
    unit_of_word,
)
from .citations import _plain as _plain_text
from .citations import _slots as _slot_spans
from .derived import check_formula
from .draft import (
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    Designation,
    EdgeSet,
    Faces,
    Fit,
    Item,
    PartSpec,
    Place,
    Profile,
    Text,
    Through,
    read_draft,
)
from .items.checks import SPEC_CHECKS
from .items.checks.pattern import PATTERN_CHECKS
from .outline import Shape, sizes
from .placement import (
    Assumption,
    Layout,
    route,
    solve,
)
from .problems import Problem, pointer
from .schema import (
    AXIS_WORDS,
    KINDS,
    NON_SHAPE_WORDS,
    FieldType,
    material_words,
)
from .tables import CLEARANCE, TAPPED, metric_size, table_target, table_value
from .values import Count, Provenance, Source, Value, made_note
from .words import REPLACED_BY_ANSWER, NumberedBrief, Word, WordRef

__all__ = ["SpecProblem", "SpecReport", "check_draft", "item_words"]


@dataclass(frozen=True)
class SpecProblem:
    """One problem, and where it is.

    ``at`` is a JSON Pointer into the draft (``/items/2/depth``), or, for what
    the brief says that nothing uses, into the brief: ``/brief/words/12``,
    ``/brief/sentences/3``.
    """

    kind: str  # "fault", "question", "cant", "unable"
    at: str
    message: str


@dataclass(frozen=True)
class SpecReport:
    """Everything the checks found about one draft."""

    spec: PartSpec | None
    layout: Layout | None
    problems: tuple[SpecProblem, ...]
    assumptions: tuple[Assumption, ...]
    caveats: tuple[Problem, ...]
    notes: tuple[Problem, ...]
    accounting: Accounting | None
    strict: bool = False

    def of_kind(self, kind: str) -> tuple[SpecProblem, ...]:
        return tuple(p for p in self.problems if p.kind == kind)

    @property
    def needs_redraft(self) -> bool:
        return bool(self.of_kind("fault"))

    @property
    def ready_to_confirm(self) -> bool:
        """Nothing left but what the person decides: assumptions and caveats."""
        return not self.problems


@dataclass
class _Collect:
    brief: NumberedBrief
    readings: list[Reading]
    cited: list[WordRef]
    mentions: list[WordRef]
    problems: list[SpecProblem]
    assumptions: list[Assumption]
    caveats: list[Problem]
    strict: bool = False
    #: Every word the item being checked cites, for its fields' choices to be read against.
    item_words: WordRef = ()

    def fault(self, at: str, message: str) -> None:
        self.problems.append(SpecProblem("fault", at, message))

    def add(self, kind: str, at: str, message: str) -> None:
        self.problems.append(SpecProblem(kind, at, message))

    def problem(self, kind: str, at: str, message: str, *values: object) -> None:
        """A problem resting on ``values``: a question instead where one of them is assumed (:func:`route`)."""
        routed = route(kind, values)
        if routed != kind:
            message += " (it rests on an assumed value: choose one that fits)"
        self.problems.append(SpecProblem(routed, at, message))

    def words_exist(self, words: WordRef, at: str) -> bool:
        """Every cited word number is a word of the brief; a fault at ``at`` if not."""
        bad = [i for i in words if not 0 <= i < len(self.brief.words)]
        if bad:
            self.fault(at, f"word {bad[0]} doesn't exist: the brief has words 0 to "
                       f"{len(self.brief.words) - 1}")  # fmt: skip
            return False
        return True


# ----------------------------------------------------------------------
# Walking the spec
# ----------------------------------------------------------------------
_Synonyms = Mapping[str, tuple[str, ...]] | None


def _provenances(
    raw: Any, at: str, synonyms: _Synonyms
) -> Iterator[tuple[str, Any, _Synonyms]]:
    """Every value-like thing in a field, with its pointer and, for a choice, its synonyms."""
    if isinstance(raw, (Value, Count, Choice, Text, Through, Fit, Faces, Profile)):
        yield at, raw, synonyms
    elif isinstance(raw, Counterbore | Countersink):
        yield at + pointer("diameter"), raw.diameter, None
        second = raw.depth if isinstance(raw, Counterbore) else raw.angle
        yield (
            at + pointer("depth" if isinstance(raw, Counterbore) else "angle"),
            second,
            None,
        )
    elif isinstance(raw, Place):
        for axis, position in raw.axes.items():
            yield at + pointer(axis), position, None
        if raw.angle is not None:
            yield at + pointer("angle"), raw.angle, None
        if raw.turn is not None:
            yield at + pointer("turn"), raw.turn, None
        if raw.pattern is not None:
            here = at + pointer("pattern", raw.pattern.kind)
            if raw.pattern.axis is not None and raw.pattern.axis_provenance is not None:
                chosen = Choice(raw.pattern.axis, raw.pattern.axis_provenance)
                yield here + pointer("axis"), chosen, AXIS_WORDS
                fixed = PATTERN_CHECKS[raw.pattern.kind].fixed_count
                if fixed:
                    yield (
                        here + pointer("axis"),
                        _Copies(fixed, raw.pattern.axis_provenance),
                        None,
                    )
            for name, value in raw.pattern.values.items():
                yield here + pointer(name), value, None
            for name, count in raw.pattern.counts.items():
                yield here + pointer(name), count, None
        if raw.concentric_provenance is not None:
            yield at + pointer("concentric"), raw.concentric_provenance, None


@dataclass(frozen=True)
class _Copies:
    """How many copies a pattern places whatever its values are (an ends pattern's two), and the words its axis cites."""

    n: int
    provenance: Provenance


def item_words(item: Item) -> WordRef:
    """Every word of the brief an item cites, its own and its fields', in order.

    What the person sees coloured as the item's in the brief, and what an
    assumed choice of the item is read against.
    """
    cited = [*item.words]
    for raw in item.fields.values():
        if isinstance(raw, EdgeSet):
            cited += raw.words
        for _, thing, _ in _provenances(raw, "", None):
            provenance = (
                thing
                if isinstance(thing, Provenance)
                else getattr(thing, "provenance", None)
            )
            if isinstance(provenance, Provenance):
                cited += provenance.words
            distance = getattr(thing, "distance", None)
            if isinstance(distance, Value):
                cited += distance.provenance.words
    return tuple(sorted(dict.fromkeys(cited)))


def _check_values(spec: PartSpec, c: _Collect) -> None:
    for n, item in enumerate(spec.items):
        base = pointer("items", n)
        if c.words_exist(item.words, base + pointer("words")):
            c.mentions.append(item.words)
        kind = KINDS[item.kind]
        c.item_words = tuple(i for i in item_words(item) if 0 <= i < len(c.brief.words))
        for name, raw in item.fields.items():
            synonyms = kind.field(name).synonyms
            if isinstance(raw, Profile):
                _check_profile(
                    raw,
                    base + pointer(name),
                    f"{item.id}.{name}",
                    SPEC_CHECKS[item.kind].turned,
                    c,
                )
                continue
            for at, thing, words in _provenances(raw, base + pointer(name), synonyms):
                label = item.id + at[len(base) :].replace("/", ".")
                _check_one(thing, at, label, words, c)
            if isinstance(raw, Place):
                _copies_named(item, raw, c)
            if isinstance(raw, EdgeSet) and c.words_exist(
                raw.words, base + pointer(name, "words")
            ):
                c.mentions.append(raw.words)


def _copies_named(item: Item, place: Place, c: _Collect) -> None:
    """A number word in a place's cited words that is the item's number of copies: "both halfway along", the place every copy shares (docs/V2-stage4.md, 14.4)."""
    count = item.get("count")
    if not isinstance(count, Count) or count.n < 2:
        return
    for position in place.axes.values():
        p = position.provenance
        if p is not None and p.source is Source.BRIEF:
            _numbers_named(p.words, c, lambda r: r.value == count.n)


def _assume(p: Provenance, at: str, what: str, c: _Collect) -> None:
    # The writer's reason is quoted: whatever it says, it reads as its words, not Forge's.
    c.assumptions.append(Assumption(at, f"{what} (assumed: {p.reason!r})"))


def _stated(p: Provenance, at: str, what: str, c: _Collect) -> None:
    """A provenance that is the brief's words or an assumption (the reader allows no other)."""
    if p.source is Source.ASSUMED:
        _assume(p, at, what, c)
    elif c.words_exist(p.words, at + pointer("from", "words")):
        c.mentions.append(p.words)


def _numbers_named(
    words: WordRef, c: _Collect, says: Callable[[Reading], bool]
) -> None:
    """Use the numbers in a choice's or a list's cited words that it ``says``: a reading of no unit that it holds."""
    for reading in readings(c.brief, words):
        if reading.unit is None and says(reading):
            c.readings.append(reading)


#: How near a size the brief gives an outline's own must be (mm): an outline is written to a few figures.
OUTLINE_MATCH = 0.005


def _check_profile(
    thing: Profile, at: str, label: str, turned: bool, c: _Collect
) -> None:
    """An outline's cited words: every number in them is one of its sizes (docs/V2-stage4.md, 6.7), and used.

    A length matches a size the outline has (``outline.sizes``) to within
    :data:`OUTLINE_MATCH`; a count, how many pieces or corners it has. A
    number that is neither is a fault: the outline drawn isn't the one the
    words describe, or the words cite what isn't its size.
    """
    p = thing.provenance
    if p.source is Source.ASSUMED:
        _assume(p, at, f"{label}: the outline", c)
        return
    if not c.words_exist(p.words, at + pointer("from", "words")):
        return
    c.mentions.append(p.words)
    numeric = [(i, k) for i in sorted(set(p.words)) if numeric_at(c.brief, i)
               for k in range(slot_count(c.brief, i))]  # fmt: skip
    if not numeric:
        return
    found, counts = sizes(Shape.of_profile(thing), turned=turned)
    good, said = [], []
    for reading in readings(c.brief, p.words):
        if reading.unit is not None and reading.unit.dimension == LENGTH:
            mm_ = reading.value * reading.unit.scale * 1000.0
            said.append((reading, f"{reading.value:g} {reading.unit.symbol}"))
            if any(abs(mm_ - size) <= OUTLINE_MATCH for size in found):
                good.append(reading)
        elif reading.unit is None:
            said.append((reading, f"{reading.value:g}"))
            if reading.value in counts:
                good.append(reading)
    used = {slot for reading in good for slot in reading.numbers}
    missing = [slot for slot in numeric if slot not in used]
    if missing:
        # The number as a size where it reads as one ("20 mm"), else as it stands.
        said.sort(key=lambda found: found[0].unit is None)
        shown = next((text for reading, text in said if missing[0] in reading.numbers),
                     c.brief.word(missing[0][0]).text)  # fmt: skip
        word = c.brief.word(missing[0][0])
        if not any(ch.isdigit() for ch in word.text):
            # A number word ("One end of the bar"): say which, or the writer can't find it to leave out (eval fp24).
            shown += f" (the brief's {word.text!r}, word {word.index})"
        c.fault(at + pointer("from", "words"),
                f"the outline has no size of {shown}: none across it, of a side, between parallel sides or "
                f"corners, of an arc{', or a diameter it turns on' if turned else ''}")  # fmt: skip
        return
    c.readings.extend(good)
    if c.strict:
        # Which size each number is, nothing here checks: an automatic run can't take the outline on trust.
        c.problems.append(SpecProblem("question", at, f"{label}: the outline's sizes are each one it has, but which "
                                      "is which only a person can see: an automatic run can't confirm it"))  # fmt: skip


def _shown(thing: Value | Count) -> str:
    return (
        f"{thing.nominal:.10g} {thing.unit}"
        if isinstance(thing, Value)
        else str(thing.n)
    )


def _check_one(
    thing: Any, at: str, label: str, synonyms: _Synonyms, c: _Collect
) -> None:
    if isinstance(thing, (Value, Count)):
        _check_number(thing, at, label, c)
    elif isinstance(thing, AxisPosition):
        if thing.provenance is not None:
            _stated(thing.provenance, at + pointer("centred"), f"{label}: centred", c)
        if thing.distance is not None:
            name = "distance" if thing.mode == "side" else "offset"
            _check_number(thing.distance, at + pointer(name), f"{label}.{name}", c)
    elif isinstance(thing, Choice):
        _check_choice(thing, at, label, synonyms, c)
    elif isinstance(thing, Designation):
        _check_designation(thing, at, label, c)
    elif isinstance(thing, Text):
        _check_text(thing, at, label, c, lettering=not at.endswith("/describe"))
    elif isinstance(thing, Fit):
        _check_fit(thing, at, label, c)
    elif isinstance(thing, Through):
        _stated(thing.provenance, at, f"{label}: through", c)
    elif isinstance(thing, Faces):
        _stated(thing.provenance, at, f"{label}: {', '.join(thing.faces) or 'none'}", c)
        if thing.provenance.source is Source.BRIEF and thing.faces:
            # "Open at both ends": the count is how many faces it opens.
            _numbers_named(
                thing.provenance.words,
                c,
                lambda r: r.unit is None and r.value == len(thing.faces),
            )
    elif isinstance(thing, _Copies):
        if thing.provenance.source is Source.BRIEF:
            # "Along both long edges": the count is how many copies the pattern places.
            _numbers_named(thing.provenance.words, c, lambda r: r.value == thing.n)
    elif isinstance(thing, Provenance):
        _stated(thing, at, label, c)


def _check_number(thing: Value | Count, at: str, label: str, c: _Collect) -> None:
    p = thing.provenance
    if not c.words_exist(p.words, at + pointer("from", "words")):
        return
    tolerance = thing.tolerance if isinstance(thing, Value) else None
    if p.source is Source.ASSUMED:
        shown = _shown(thing)
        if tolerance is not None:
            shown += f" +{tolerance.plus:g}/-{tolerance.minus:g}"
        _assume(p, at, f"{label}: {shown}", c)
        return
    if tolerance is not None and p.source is not Source.BRIEF:
        c.fault(at + pointer("tolerance"),
                "a looked-up or worked-out value takes no tolerance; give one only where the brief states it")  # fmt: skip
        return
    if p.source is Source.TABLE:
        _check_table(thing, at, label, c)
        return
    if p.source is Source.DERIVED:
        _check_formula(thing, at, label, c)
        return
    marked = _marked_numbers(thing, c.brief) if isinstance(thing, Value) else []
    if isinstance(thing, Value):
        result = check_quantity(thing.quantity, c.brief, p.words)
        if result.follows is Follows.NO and marked:
            # The citation holds the tolerance too: the value is judged on the other numbers.
            slots = {m.slot for m in marked}
            whole = {
                w
                for w, _ in slots
                if all((w, k) in slots for k in range(slot_count(c.brief, w)))
            }
            rest = tuple(i for i in p.words if i not in whole)
            if rest:
                result = check_quantity(thing.quantity, c.brief, rest)
    else:
        result = check_count(thing.n, c.brief, p.words)
    if result.follows is Follows.NO or result.reading is None:
        c.fault(at, result.message)
        return
    c.readings.append(result.reading)
    c.mentions.append(p.words)  # "80 mm long": the words that say what it measures
    if result.follows is Follows.YES_WITH_CAVEAT:
        c.caveats.append(Problem(at, f"{label}: {result.message}"))
    elif result.follows is Follows.UNIT_NOT_STATED:
        c.assumptions.append(Assumption(at, f"{label}: {result.message}"))
    if not isinstance(thing, Value):
        return
    stated = _tolerance_of(_tolerance_run(marked, result.reading, c.brief))
    if stated is not None:
        c.readings.extend(stated.readings)
    if tolerance is not None and stated is None:
        c.fault(at + pointer("tolerance"), "the tolerance isn't in the cited words: cite the brief's "
                "+/- numbers right after the value, or leave the tolerance out")  # fmt: skip
    elif stated is not None and (
        tolerance is None
        or (tolerance.plus, tolerance.minus) != (stated.plus, stated.minus)
    ):
        c.fault(at + pointer("tolerance"),
                f"the brief gives +{stated.plus:g}/-{stated.minus:g} {thing.unit}"
                + (f", not +{tolerance.plus:g}/-{tolerance.minus:g}" if tolerance else ": give the tolerance"))  # fmt: skip


@dataclass(frozen=True)
class _Marked:
    """A number in the citation with a sign or a +/- before it: a tolerance's bound."""

    slot: tuple[int, int]
    mark: str  # "+/-", "+" or "-"
    size: float
    reading: Reading


#: Words that may stand between a value and its tolerance: "60 mm long ±0.1",
#: "±0.05 mm tolerance on its 10 mm diameter". Anything else between them
#: (another number, "offset") means the signed number isn't the tolerance.
_TOLERANCE_JOINERS = frozenset({
    "plus", "or", "minus", "tolerance", "tolerances", "tol", "of", "on", "its", "the", "a", "an",
    "to", "within", "held", "at", "long", "wide", "thick", "tall", "high", "deep", "across",
    "diameter", "dia", "length", "width", "height", "thickness", "depth", "\u00b1", "+/-", "+", "-",
})  # fmt: skip


def _tolerance_run(
    marked: list[_Marked], reading: Reading, brief: NumberedBrief
) -> list[_Marked]:
    """The marked numbers that are the value's tolerance: a run of them right after it, or right before.

    Each must be joined to the value, or to the bound before it, by nothing
    but units and words such as "long" or "tolerance on its", in the same
    sentence: in "a 10 mm hole through it, offset +5 mm" the +5 isn't the
    hole's tolerance.
    """
    used = set(reading.numbers)
    marks = sorted((m for m in marked if m.slot not in used), key=lambda m: m.slot)
    first, last = min(reading.numbers), max(reading.numbers)

    def joined(a: int, b: int) -> bool:
        if a == b:
            return True
        lo, hi = min(a, b), max(a, b)
        if brief.word(lo).sentence != brief.word(hi).sentence:
            return False
        return all(
            unit_of_word(brief.word(i).text) is not None
            or _plain_text(brief.word(i).text).lower() in _TOLERANCE_JOINERS
            for i in range(lo + 1, hi)
        )

    after: list[_Marked] = []
    at = last[0]
    for m in (m for m in marks if m.slot > last):
        if not joined(at, m.slot[0]):
            break
        after.append(m)
        at = m.slot[0]
    if after:
        return after
    before: list[_Marked] = []
    at = first[0]
    for m in reversed([m for m in marks if m.slot < first]):
        if not joined(m.slot[0], at):
            break
        before.insert(0, m)
        at = m.slot[0]
    return before


def _tolerance_of(marked: list[_Marked]) -> _Tolerance | None:
    if not marked:
        return None
    plus = minus = None
    for m in marked:
        if m.mark in ("+/-", "+"):
            plus = m.size
        if m.mark in ("+/-", "-"):
            minus = m.size
    return _Tolerance(plus or 0.0, minus or 0.0, frozenset(m.slot for m in marked),
                      tuple(m.reading for m in marked))  # fmt: skip


@dataclass(frozen=True)
class _Tolerance:
    plus: float
    minus: float
    slots: frozenset[tuple[int, int]]
    readings: tuple[Reading, ...]


_SYMMETRIC = ("\u00b1", "+/-", "+-", "-/+")
_MARKS = frozenset({"\u00b1", "+/-", "+-", "-/+", "+", "-", "\u2212"})


def _marked_numbers(value: Value, brief: NumberedBrief) -> list[_Marked]:
    """The cited numbers with a sign or a +/- before them, in order.

    Only such a number ("\u00b10.1", "+0.1/-0", "plus or minus 0.1", "+0.1
    -0.2") can be a tolerance's bound, and only right next to the value's own
    number (:func:`_tolerance_run`), so a tolerance can't soak up an unrelated
    number and a signed value ("an offset of -10 mm") isn't taken for one.
    """
    found: list[_Marked] = []
    for index in value.provenance.words:
        word = brief.word(index)
        plain = _plain_text(word.text)
        start = brief.words[index - 1].end if index else 0
        if index and brief.words[index - 1].text.strip() in _MARKS:
            start = brief.words[
                index - 1
            ].start  # "8.00 \u00b1 0.02 mm": the mark is a word of its own
        before = _plain_text(brief.text[start : word.start]).lower()
        if (
            index >= 3
            and " ".join(w.text.lower() for w in brief.words[index - 3 : index])
            == "plus or minus"
        ):
            before += "+/-"
        previous_end = 0
        for k, (begin, end) in enumerate(_slot_spans(word.text)):
            context = ((before if k == 0 else "") + plain[previous_end:begin]).rstrip()
            previous_end = end
            if context.endswith(_SYMMETRIC):
                mark = "+/-"
            elif context.endswith("+"):
                mark = "+"
            elif context.endswith(("-", "\u2212")):
                mark = "-"
            else:
                continue
            reading = next(
                (r for r in readings(brief, (index,)) if r.numbers == ((index, k),)),
                None,
            )
            if reading is None:
                continue
            size = abs(reading.value)
            if reading.unit is not None:
                if reading.unit.dimension != value.quantity.unit.dimension:
                    continue
                size = abs(Q(reading.value, reading.unit).value_in(value.unit))
            found.append(_Marked((index, k), mark, size, reading))
    return found


def _plain(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", text.lower()).strip()


#: Words that deny what follows them, to the end of the clause.
_NEGATIONS = frozenset(
    {"not", "no", "none", "without", "never", "non", "neither", "nor", "cannot"}
)
#: Two-word denials: "square rather than round", "square instead of round".
_DENIAL_PAIRS = frozenset({("rather", "than"), ("instead", "of"), ("free", "of")})
#: Words that start a new clause, ending a denial: "not engraved but raised".
_CLAUSE_WORDS = frozenset(
    {"but", "and", "yet", "while", "whereas", "though", "although", "so", "then"}
)
_CLAUSE_MARKS = re.compile(r"[,;:.!?()\[\]{}]")


def _denied(brief: NumberedBrief) -> frozenset[int]:
    """The brief's words that a negation before them denies, within their clause.

    "Square, not rounded", "not at all rounded", "should not be loose",
    "neither round nor square", "square rather than round": the option after
    the denial is ruled out, not named. A comma, a full stop or a word such
    as "but" or "and" ends the denial ("not engraved but raised").
    """
    known = brief.memo.get("denied")
    if isinstance(known, frozenset):
        return known
    found: set[int] = set()
    denying = False
    previous: Word | None = None
    for word in brief.words:
        plain = _plain(word.text)
        new_clause = previous is None or previous.sentence != word.sentence
        if previous is not None and _CLAUSE_MARKS.search(
            brief.text[previous.end : word.start]
        ):
            new_clause = True
        if new_clause or plain in _CLAUSE_WORDS:
            denying = False
        last = _plain(previous.text) if previous is not None and not new_clause else ""
        if (
            plain in _NEGATIONS
            or word.text.lower()
            .replace("\u2019", "'")
            .endswith("n't")  # "isn't", "shouldn't"
            or (last, plain) in _DENIAL_PAIRS
        ):
            denying = True
        elif denying or plain.startswith("non "):
            found.add(word.index)
        previous = word
    result = frozenset(found)
    brief.memo["denied"] = result
    return result


def _choice_tokens(words: WordRef, brief: NumberedBrief) -> tuple[set[str], set[str]]:
    """The cited words, as plain tokens, that name a choice's option, and those that deny one.

    A word a negation denies (:func:`_denied`, read in the brief, not just in
    the citation) names nothing, and "unrounded" denies "rounded"; an "x"
    between two numbers ("30 x 50") is a times sign, not the X axis.
    """
    tokens: set[str] = set()
    denied: set[str] = set()
    ruled_out = _denied(brief)
    for i in sorted(words):
        plain = _plain(brief.word(i).text)
        parts = plain.split()
        if i in ruled_out:
            denied.add(plain)
            denied.update(parts)
            continue
        inside = 0 < i < len(brief.words) - 1
        times = (
            plain == "x"
            and inside
            and numeric_at(brief, i - 1)
            and numeric_at(brief, i + 1)
        )
        if not times:
            tokens.add(plain)
            tokens.update(parts)
            # "unrounded", "unthreaded": the word without its "un" is denied.
            denied.update(
                part[2:] for part in parts if part.startswith("un") and len(part) > 4
            )
    return tokens, denied


def _check_choice(
    thing: Choice, at: str, label: str, synonyms: _Synonyms, c: _Collect
) -> None:
    p = thing.provenance
    if p.source is Source.ASSUMED:
        _assume(p, at, f"{label}: {thing.value}", c)
        _against_the_item(thing, at, label, synonyms, c)
        return
    if not c.words_exist(p.words, at + pointer("from", "words")):
        return
    c.mentions.append(p.words)
    if synonyms is None:
        return
    # A number word that names the option ("half" of a sphere, a dome) is the choice's own.
    named = {_plain(w) for w in synonyms[thing.value]}
    _numbers_named(
        p.words,
        c,
        lambda r: all(_plain(c.brief.word(i).text) in named for i in r.number_words),
    )
    quoted = c.brief.quote(p.words)
    cited, denied = _choice_tokens(p.words, c.brief)
    own = any(_plain(w) in cited for w in synonyms[thing.value])
    if not own and any(_plain(w) in denied for w in synonyms[thing.value]):
        c.fault(at, f"the cited words ({quoted!r}) rule out {thing.value}")
        return
    other = [option for option, words in synonyms.items()
             if option != thing.value and any(_plain(w) in cited for w in words)]  # fmt: skip
    if other and not own:
        c.fault(at, f"the cited words ({quoted!r}) say {other[0]}, not {thing.value}")
    elif not own and denied:
        c.fault(at, f"the cited words ({quoted!r}) deny something and name no option: cite the words "
                    f"that say {thing.value}, or assume it and say why")  # fmt: skip
    elif not own:
        # Read from words that don't name it ("across its width" for y): shown first, as an
        # assumption is, since only the person can tell whether the reading is right.
        c.assumptions.append(Assumption(at, f"{label}: {thing.value} (read from {quoted!r}, which doesn't "
                                            "name it)"))  # fmt: skip


def _against_the_item(
    thing: Choice, at: str, label: str, synonyms: _Synonyms, c: _Collect
) -> None:
    """An assumed choice that the item's own words contradict: they name another option.

    In an automatic run nobody would see the assumption, so it is a question;
    otherwise it is worth a second look.
    """
    if synonyms is None or not c.item_words:
        return
    cited, _ = _choice_tokens(c.item_words, c.brief)
    named = [
        option
        for option, words in synonyms.items()
        if any(_plain(w) in cited for w in words)
    ]
    if not named or thing.value in named:
        return
    naming = tuple(i for i in c.item_words
                   if any(_plain(w) in _choice_tokens((i,), c.brief)[0] for w in synonyms[named[0]]))  # fmt: skip
    message = f"{label}: {thing.value} is assumed, but the item's words say {named[0]} ({c.brief.quote(naming)!r})"
    if c.strict:
        c.problems.append(SpecProblem("question", at, message))
    else:
        c.caveats.append(Problem(at, message))


#: Quotations in a brief: curly quotes, and single quotes that open after a
#: space and close before one (so "JAMES' BIKE" and "IT'S" are not
#: quotations, and 'IT'S OPEN' is one). Straight double quotes are paired by
#: :func:`_straight_quotations`, which knows an inch mark from a quote.
_QUOTATIONS = re.compile(
    r"\u201c([^\u201d]+)\u201d|\u2018([^\u2019]+)\u2019|(?<![\w])'(.+?)'(?![\w])"
)
_QUOTE_MARKS = '"\u201c\u201d\u2018'
#: The marks (not letters, digits or spaces) right before and after a run of words.
_MARKS_BEFORE = re.compile(r"[^\w\s]*\Z")
_MARKS_AFTER = re.compile(r"[^\w\s]*")
#: A full stop that ends its sentence: the brief ends, or a new sentence starts, after it.
_SENTENCE_END = re.compile(r"\.[^\w\s]*(?:\s*\Z|\s+[A-Z\"'(\u201c\u2018])")


def _quotations(brief: NumberedBrief) -> tuple[tuple[int, int], ...]:
    """Where the brief's quotations are: the span inside each pair of quote marks."""
    known = brief.memo.get("quotations")
    if isinstance(known, tuple):
        return known
    spans = tuple(sorted([
        *_straight_quotations(brief.text),
        *(next(m.span(g) for g in range(1, 4) if m.group(g) is not None) for m in _QUOTATIONS.finditer(brief.text)),
    ]))  # fmt: skip
    brief.memo["quotations"] = spans
    return spans


def _straight_quotations(text: str) -> list[tuple[int, int]]:
    """The spans inside pairs of straight double quotes.

    A mark straight after a digit is an inch mark ('2" wide'), as the brief's
    words read it (:mod:`forge_spec.words`), unless it closes a quote opened
    before it ('an "M4" screw').

    >>> _straight_quotations('A 2" wide bar, 6" long, marked "AB 4".')
    [(32, 36)]
    """
    found: list[tuple[int, int]] = []
    opened: int | None = None
    for i, ch in enumerate(text):
        if ch != '"':
            continue
        if opened is not None:
            if i > opened + 1:
                found.append((opened + 1, i))
            opened = None
        elif not (i > 0 and text[i - 1].isdigit()):
            opened = i
    return found


def _check_text(
    thing: Text, at: str, label: str, c: _Collect, *, lettering: bool
) -> None:
    """A text is exactly the brief's words: one run of them, punctuation and all.

    A quoted text is the whole quotation (bar a full stop or comma the
    sentence put inside it), and only it. An unquoted one is the cited words,
    with or without the marks stuck to them, except those that end a clause
    or close a bracket; a full stop may stay ("INC.") unless it ends the
    sentence. Capitals that run on past the cited words ("DO NOT OPEN") must
    be taken whole. A text may not drop or add anything else, or stitch
    words together from different places.
    """
    p = thing.provenance
    if p.source is Source.ASSUMED:
        _assume(p, at, f"{label}: {thing.text!r}", c)
        return
    if not c.words_exist(p.words, at + pointer("from", "words")):
        return
    words = sorted(p.words)
    if words != list(range(words[0], words[-1] + 1)):
        c.fault(
            at + pointer("from", "words"),
            "cite the text's words as one run, with nothing left out between",
        )
        return
    brief = c.brief
    first, last = brief.word(words[0]), brief.word(words[-1])
    core = brief.text[first.start : last.end]
    quote = next(
        ((a, b) for a, b in _quotations(brief) if a < last.end and first.start < b),
        None,
    )
    if quote is not None:
        inside = [
            w.index for w in brief.words if quote[0] <= w.start and w.end <= quote[1]
        ]
        if words != inside:
            c.fault(at + pointer("from", "words"),
                    "the text is part of a quotation: cite all of it, and only it")  # fmt: skip
            return
        said = brief.text[quote[0] : quote[1]]
        candidates = {said, said.rstrip(".,;:")}
    else:
        run_on = _capitals_run_on(brief, words)
        if run_on is not None and not any(ch.islower() for ch in thing.text):
            c.fault(at + pointer("from", "words"),
                    f"the brief's capitals run on ({run_on!r}): cite them all")  # fmt: skip
            return
        head = _MARKS_BEFORE.search(brief.text[: first.start])
        tail = _MARKS_AFTER.match(brief.text, last.end)
        before = head.group() if head else ""
        after = tail.group() if tail else ""
        # The words, with any marks stuck to them that aren't the sentence's
        # (or a stray quote mark's); a full stop right after them may be an
        # abbreviation's ("INC."), unless the sentence ends there.
        lead = before.lstrip("([{").strip(_QUOTE_MARKS)
        trail = after.rstrip(".,;:)]}").strip(_QUOTE_MARKS)
        ends_sentence = (
            _SENTENCE_END.match(brief.text, last.end + len(trail)) is not None
        )
        keeps_stop = after.startswith(trail + ".") and not ends_sentence
        tails = {trail, trail + "."} if keeps_stop else {trail}
        # A bracket the text opens, it may close: "PETG-CF (carbon fibre)".
        closing = _closing_brackets(core)
        if closing and after.startswith(closing):
            tails.add(closing)
        candidates = {core} | {h + core + t for h in ("", lead) for t in tails}
        said = core
    if thing.text not in candidates:
        c.fault(
            at, f"{thing.text!r} is not exactly what the cited words say ({said!r})"
        )
        return
    c.mentions.append(p.words)
    # The numbers in letters to engrave are letters, not sizes, when the
    # brief marks them as letters: quoted, or written in capitals ("SERIAL
    # 42"). A description's numbers, and those of any other run of the
    # brief's prose, are still to be used by values of their own.
    if lettering and (quote is not None or not any(ch.islower() for ch in thing.text)):
        c.cited.append(p.words)


def _closing_brackets(text: str) -> str:
    """The brackets that would close those ``text`` leaves open, innermost first: "" for none.

    >>> _closing_brackets("PETG-CF (carbon fibre"), _closing_brackets("M8 (fine)"), _closing_brackets("a)")
    (')', '', '')
    """
    pairs = {"(": ")", "[": "]", "{": "}"}
    open_: list[str] = []
    for ch in text:
        if ch in pairs:
            open_.append(pairs[ch])
        elif ch in pairs.values():
            if not open_ or open_[-1] != ch:
                return ""  # a bracket closed that this text didn't open: not one text
            open_.pop()
    return "".join(reversed(open_))


def _capitals_run_on(brief: NumberedBrief, words: list[int]) -> str | None:
    """The whole run of capital words when the cited words are only part of it ("OPEN" of "DO NOT OPEN")."""

    def capitals(i: int) -> bool:
        text = brief.word(i).text
        return text.isalpha() and text.isupper() and len(text) > 1

    def joined(
        i: int, j: int
    ) -> bool:  # adjacent in one clause, with nothing but space between
        a, b = brief.word(i), brief.word(j)
        return a.sentence == b.sentence and not brief.text[a.end : b.start].strip()

    if not all(any(ch.isupper() for ch in brief.word(i).text) for i in words):
        return None
    lo, hi = words[0], words[-1]
    while lo > 0 and capitals(lo - 1) and joined(lo - 1, lo):
        lo -= 1
    while hi + 1 < len(brief.words) and capitals(hi + 1) and joined(hi, hi + 1):
        hi += 1
    if (lo, hi) == (words[0], words[-1]):
        return None
    return brief.text[brief.word(lo).start : brief.word(hi).end]


# ----------------------------------------------------------------------
# Standard sizes
# ----------------------------------------------------------------------
#: A metric size in a run of the brief's words: "M8", "M8x1.25", "4xM3" (four
#: of them), "M8 x 1" over three words.
_DESIGNATION = re.compile(
    r"(?<![a-z0-9.])(?:\d+[x\u00d7])?m(\d+(?:\.\d+)?)(?:[x\u00d7](\d+(?:\.\d+)?))?(?![0-9]|\.[0-9])",
    re.IGNORECASE,
)
_GRADE_WORDS = {"fine": ("fine", "close", "tight"), "normal": ("normal", "medium", "standard"),
                "coarse": ("coarse", "loose", "free")}  # fmt: skip


def _naming_words(
    target: str, words: WordRef, brief: NumberedBrief
) -> tuple[list[int], list[tuple[int, int]], str | None]:
    """The cited words that name a standard part, the number slots the name uses, and what's wrong.

    A metric size must match whole, pitch included: "M8" doesn't name an
    M8x1, and "M8x1" isn't an M8 (coarse). A bearing is its number. Only the
    numbers of the name are its own: in "4xM3" the 4 is a count, and in
    "M5x16" the 16 a length, each still to be used by a value of its own.
    """
    size = metric_size(target)
    naming: list[int] = []
    slots: list[tuple[int, int]] = []
    cited = sorted(set(words))
    # A designation may be written over several words: "M8 x 1".
    runs = [
        tuple(range(i, i + n))
        for n in (3, 2, 1)
        for i in cited
        if all(j in cited for j in range(i, i + n))
    ]
    for run in runs:
        if any(i in naming for i in run):
            continue
        text = "".join(_plain_text(brief.word(i).text) for i in run)
        if size is None:
            found = re.search(
                rf"(?<![0-9]){re.escape(target)}(?![0-9])", text, re.IGNORECASE
            )
            if len(run) == 1 and found:
                naming.append(run[0])
                slots += _slots_of(brief, run, [found.span()])
            continue
        whole = _DESIGNATION.fullmatch(text)
        matches = (
            [whole]
            if whole
            else ([] if len(run) > 1 else list(_DESIGNATION.finditer(text)))
        )
        for match in matches:
            assert match is not None
            name = metric_size("M" + match.group(1))
            if name is None or name[0] != size[0]:
                continue
            pitch = float(match.group(2)) if match.group(2) else None
            if pitch is not None and not _a_pitch(size[0], pitch):
                if len(run) > 1:
                    continue  # "M8 x 20": a bolt 20 long; the size is the "M8" alone
                pitch = None
            longer = _whole_designation(brief, run, size[0])
            if longer is not None:
                return [], [], f"the brief gives {longer}: cite all of it"
            coarse = TAPPED.get(size[0], (None, None))[0]
            shown = " ".join(brief.word(i).text for i in run)
            if size[1] is None and pitch is not None and pitch != coarse:
                return (
                    [],
                    [],
                    f"the brief gives {shown}: say its pitch, {size[0]}x{pitch:g}",
                )
            if (
                size[1] is not None
                and (pitch if pitch is not None else coarse) != size[1]
            ):
                return [], [], f"the cited words name {shown}, not {target}"
            naming.extend(run)
            spans = [match.span(1)] + ([match.span(2)] if pitch is not None else [])
            slots += _slots_of(brief, run, spans)
    if not naming:
        return [], [], f"cite the brief's words that name {target}"
    return naming, slots, None


def _slots_of(
    brief: NumberedBrief, run: tuple[int, ...], spans: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """The number slots of ``run``'s words that lie inside ``spans`` of their joined plain text."""
    found: list[tuple[int, int]] = []
    offset = 0
    for i in run:
        text = brief.word(i).text
        for k, (a, b) in enumerate(_slot_spans(text)):
            if any(start <= offset + a and offset + b <= end for start, end in spans):
                found.append((i, k))
        offset += len(_plain_text(text))
    return found


def _a_pitch(size: str, pitch: float) -> bool:
    """Whether a number after a metric size can be its pitch ("M8 x 1"), not a length ("M8 x 20")."""
    return 0 < pitch < float(size[1:]) / 4


def _whole_designation(
    brief: NumberedBrief, run: tuple[int, ...], size: str
) -> str | None:
    """The brief's words for the whole designation, when ``run`` is only its start ("M8" of "M8 x 1")."""
    for n in (3, 2):
        longer = range(run[0], run[0] + n)
        if n <= len(run) or longer[-1] >= len(brief.words):
            continue
        text = "".join(_plain_text(brief.word(i).text) for i in longer)
        whole = _DESIGNATION.fullmatch(text)
        if whole and whole.group(2) and _a_pitch(size, float(whole.group(2))):
            return " ".join(brief.word(i).text for i in longer)
    return None


def _check_naming(target: str, words: WordRef, at: str, c: _Collect) -> bool:
    naming, slots, wrong = _naming_words(target, words, c.brief)
    if wrong is not None:
        c.fault(at + pointer("from", "words"), wrong)
        return False
    numeric_others = [
        i for i in words if i not in naming and any(r for r in readings(c.brief, (i,)))
    ]
    if numeric_others:
        c.fault(at + pointer("from", "words"),
                f"cite only the words that name {target}; {c.brief.word(numeric_others[0]).text!r} "
                "is a number of its own")  # fmt: skip
        return False
    # The name's own numbers are used; any other number in its words is not.
    c.readings.append(
        Reading(
            0.0,
            None,
            tuple(dict.fromkeys(slots)),
            tuple(sorted(set(naming))),
            "designation",
        )
    )
    c.mentions.append(words)
    return True


def _check_designation(thing: Designation, at: str, label: str, c: _Collect) -> None:
    """A standard part named by a text: its words must name it whole, and a pitch must be one."""
    p = thing.provenance
    size = metric_size(thing.text)
    if size is not None and size[1] is not None and not _a_pitch(size[0], size[1]):
        c.fault(at + pointer("text"),
                f"{size[1]:g} mm can't be the pitch of an {size[0]} (it is under {float(size[0][1:]) / 4:g} mm): "
                f"{thing.text!r} reads as an {size[0]} {size[1]:g} long; name it {size[0]}")  # fmt: skip
        return
    if p.source is Source.ASSUMED:
        _assume(p, at, f"{label}: {thing.text}", c)
        return
    if c.words_exist(p.words, at + pointer("from", "words")) and size is not None:
        _check_naming(thing.text, p.words, at, c)


def _check_grade(
    fit: str, target: str, grade: str, words: WordRef, at: str, label: str, c: _Collect
) -> None:
    """A clearance's grade is the brief's, or the normal one, assumed and shown."""
    size = metric_size(target)
    if fit != "clearance" or size is None or size[0] not in CLEARANCE:
        return
    cited, _ = _choice_tokens(words, c.brief)  # "not a close fit" says no grade
    stated = [g for g, names in _GRADE_WORDS.items() if any(n in cited for n in names)]
    if grade in stated:
        return
    if grade == "normal" and not stated:
        c.assumptions.append(Assumption(at, f"{label}: the normal (ISO 273 medium) clearance for {target}; "
                                        "the brief doesn't say how close"))  # fmt: skip
        return
    said = f"says {stated[0]}" if stated else "doesn't say how close"
    c.fault(at + pointer("grade"), f"a {grade} clearance, but the brief {said}")


def _check_table(thing: Value | Count, at: str, label: str, c: _Collect) -> None:
    p = thing.provenance
    reference = p.table or ""
    entry = table_value(reference) if isinstance(thing, Value) else None
    target = table_target(reference)
    if entry is None or target is None:
        c.fault(at + pointer("from", "table"),
                f"no table entry {reference!r}; Forge's tables are clearance:M4[:fine|normal|coarse], "
                "tapped:M4 or tapped:M8x1, bearing:608:outer|width|bore")  # fmt: skip
        return
    assert isinstance(thing, Value)
    if (
        thing.quantity.unit.dimension != LENGTH
        or abs(thing.nominal_in("mm") - entry.size_mm) > 1e-9
    ):
        c.fault(
            at,
            f"the table gives {entry.size_mm:g} mm ({entry.source}), not {thing.nominal:g} {thing.unit}",
        )
        return
    if not _check_naming(target, p.words, at, c):
        return
    parts = [part.strip() for part in reference.split(":")]
    if parts[0] == "clearance":
        _check_grade(
            "clearance",
            target,
            parts[2] if len(parts) == 3 else "normal",
            p.words,
            at,
            label,
            c,
        )


def _check_fit(thing: Fit, at: str, label: str, c: _Collect) -> None:
    p = thing.provenance
    if p.source is Source.ASSUMED:
        grade = f" ({thing.grade})" if thing.grade else ""
        _assume(p, at, f"{label}: {thing.fit}{grade} for {thing.for_}", c)
        return
    if not c.words_exist(p.words, at + pointer("from", "words")):
        return
    if _check_naming(thing.for_, p.words, at, c):
        _check_grade(thing.fit, thing.for_, thing.grade, p.words, at, label, c)


def _check_formula(thing: Value | Count, at: str, label: str, c: _Collect) -> None:
    p = thing.provenance
    target = thing.quantity if isinstance(thing, Value) else thing.n
    result = check_formula(target, p.formula or "", p.words, c.brief)
    if not result.ok:
        c.fault(at + pointer("from", "formula"), result.message)
        return
    c.readings.extend(result.readings)
    c.mentions.append(p.words)
    c.caveats.extend(Problem(at, f"{label}: {message}") for message in result.caveats)
    c.assumptions.extend(
        Assumption(at, f"{label}: {message}") for message in result.unit_assumed
    )


# ----------------------------------------------------------------------
# What can't be made
# ----------------------------------------------------------------------
def _problem(c: _Collect, kind: str, at: str, message: str, *values: object) -> None:
    c.problem(kind, at, message, *values)


def _physical(spec: PartSpec, layout: Layout, c: _Collect) -> None:
    """What can't be made, or needs a person's decision, whatever the brief says."""
    for n, item in enumerate(spec.items):
        at = pointer("items", n)
        for name, value in item.fields.items():
            spec_field = KINDS[item.kind].field(name)
            if spec_field.type is FieldType.LENGTH and isinstance(value, Value) and name != "top_diameter" \
                    and (value.nominal == 0 or value.made.nominal == 0):  # fmt: skip
                c.fault(at + pointer(name), f"{name} can't be 0{made_note(value)}")
        SPEC_CHECKS[item.kind].physical(spec, item, at, layout, c)


# ----------------------------------------------------------------------
# The whole check
# ----------------------------------------------------------------------
def _may_be_shape(brief: NumberedBrief, index: int) -> bool:
    """Whether a word of the brief may say something about the shape (see ``NON_SHAPE_WORDS``).

    A number may; so may any word that isn't a function word, a unit, or a
    material, colour, finish, process or use: the list of what can't is
    closed, so a shape word nobody thought of still counts.
    """
    if numeric_at(brief, index):
        return True
    text = brief.word(index).text
    if unit_of_word(text) is not None:
        return False
    return any(
        part not in FUNCTION_WORDS and part not in NON_SHAPE_WORDS
        for part in _plain(text).split()
    )


def _shape_words(
    brief: NumberedBrief, words: Iterable[int], *, named: Iterable[str] | None = None
) -> str:
    """The words among ``words`` that may say something of the shape, quoted; "" if none may.

    A negation counts only with them: "no load" says nothing of the shape,
    "no holes" does. ``named``, for a sentence taken as silent: the words
    the first body's own words cite elsewhere, which name the part again
    and say nothing new ("it is a locating collar") unless a negation in
    the sentence denies a shape word (docs/V2-stage4.md, 14.4).
    """
    found = [i for i in words if 0 <= i < len(brief.words)]
    leaves = [i for i in found if _may_be_shape(brief, i)]
    if all(_plain(brief.word(i).text) in _NEGATIONS for i in leaves):
        return ""
    if named is not None:
        said = set(named)
        denials = [i for i in leaves if _plain(brief.word(i).text) in _NEGATIONS]
        if not any(_denies_a_shape(brief, i, found) for i in denials):
            rest = [
                i
                for i in leaves
                if i not in denials and _plain(brief.word(i).text) not in said
            ]
            if not rest:
                return ""
    return ", ".join(repr(brief.word(i).text) for i in leaves)


def _denies_a_shape(brief: NumberedBrief, index: int, words: list[int]) -> bool:
    """Whether the negation at ``index`` denies a word that may be a shape: the first after it that isn't a common word ("no load": "load", which can't)."""
    after = [i for i in words if i > index]
    for i in after:
        text = _plain(brief.word(i).text)
        if text in FUNCTION_WORDS or text in _NEGATIONS:
            continue
        return _may_be_shape(brief, i)
    return True  # nothing after it: taken as denying what it may


def _owners(spec: PartSpec, brief: NumberedBrief) -> dict[int, frozenset[str]]:
    """Who cites each word of the brief: the items (their own words and their fields'), and the material."""
    found: dict[int, set[str]] = {}
    for item in spec.items:
        for i in item_words(item):
            if 0 <= i < len(brief.words):
                found.setdefault(i, set()).add(item.id)
    material = spec.requirements.material
    if material is not None and material.provenance.source is Source.BRIEF:
        for i in material.provenance.words:
            if 0 <= i < len(brief.words):
                found.setdefault(i, set()).add(MATERIAL)
    return {i: frozenset(owners) for i, owners in found.items()}


def _part_named(spec: PartSpec, brief: NumberedBrief) -> set[tuple[int, str]]:
    """The words the first body's own words cite, by sentence: the part's name, as the brief gives it."""
    first = next(
        (i for i in spec.items if SPEC_CHECKS[i.kind].body and i.get("on") is None),
        None,
    )
    if first is None:
        return set()
    return {
        (brief.word(i).sentence, _plain(brief.word(i).text))
        for i in first.words
        if 0 <= i < len(brief.words)
    }


def _unused(word: Word, accounting: Accounting) -> str:
    """The brief's number nothing uses, said so the person can find it: "'4' (in '4xM3', sentence 1)"."""
    plain = _plain_text(word.text)
    spans = _slot_spans(word.text)
    unused = [
        plain[a:b]
        for k, (a, b) in enumerate(spans)
        if (word.index, k) not in accounting.used_slots
    ]
    if 0 < len(unused) < len(spans):
        return f"{', '.join(unused)!r} (in {word.text!r}, sentence {word.sentence + 1})"
    return f"{word.text!r} (sentence {word.sentence + 1})"


def _check_requirements(spec: PartSpec, c: _Collect) -> None:
    """The material is the brief's words for it, exactly; and no word naming a material goes unrecorded.

    Its words name a stock: a grade's number with them is part of the name
    ("aluminium 6061", "PA12"), and accounted for by it; a size or a count
    is not ("steel plate 80 mm long", "PETG. Two"), and is a fault. Every
    word of the brief that names a material is the material's, or, being
    another thing's ("it fits a steel shaft"), listed as not modelled, which
    only a part with a material of its own may do. A material word left in a
    silent sentence or among an item's words is a fault: the strength and
    print checks would never hear of it.
    """
    material = spec.requirements.material
    at = pointer("requirements", "material")
    named: set[int] = set()
    if material is not None:
        before = len(c.problems)
        _check_text(material, at, "requirements.material", c, lettering=False)
        if (
            len(c.problems) == before
            and material.provenance.source is not Source.ASSUMED
        ):
            named = set(material.provenance.words)
            _material_words(material.provenance.words, at, c)
    not_modelled = {i for entry in spec.not_modelled for i in entry.words}
    for n, entry in enumerate(spec.not_modelled):
        for i in entry.words:
            if not _names_material(c.brief, i):
                continue
            word = c.brief.word(i).text
            if i in named:
                c.fault(pointer("not_modelled", n, "words"),
                        f"{word!r} is the material: it is requirements.material already, so leave it out here")  # fmt: skip
                break
            if material is None:
                c.fault(pointer("not_modelled", n, "words"),
                        f"{word!r} names a material: give the part's as requirements.material, citing its words; "
                        "another thing's may be left out here once the part has one of its own")  # fmt: skip
                break
    labels = c.brief.answer_labels()
    for i in range(len(c.brief.words)):
        if (
            i in named
            or i in not_modelled
            or i in labels
            or not _names_material(c.brief, i)
        ):
            continue
        word = c.brief.word(i).text
        c.fault(at, f"{word!r} (word {i}) names a material the spec doesn't record: cite it in "
                "requirements.material, or, if it is another thing's, list it in not_modelled saying whose")  # fmt: skip


def _names_material(brief: NumberedBrief, i: int) -> bool:
    known = brief.memo.get("material words")
    if not isinstance(known, frozenset):
        known = material_words([w.text for w in brief.words])
        brief.memo["material words"] = known
    return i in known


def _material_words(words: WordRef, at: str, c: _Collect) -> None:
    """A material's cited words: one sentence, its grade numbers accounted for, never a size or a count."""
    brief = c.brief
    if len({brief.word(i).sentence for i in words}) > 1:
        c.fault(
            at + pointer("from", "words"),
            "a material is named in one sentence: cite only its own words",
        )
        return
    grades: list[int] = []
    for reading in readings(brief, words):
        stated = (
            reading.unit is not None
            and set(reading.words) <= set(words)
            and not reading.chained
        )
        spelled = [
            w
            for w in reading.number_words
            if not any(ch.isdigit() for ch in brief.word(w).text)
        ]
        if stated or spelled:
            what = brief.quote(reading.words)
            c.fault(at + pointer("from", "words"),
                    f"{what!r} is a {'measure' if stated else 'count'}, not part of a material's name: cite only "
                    "the material's own words, and give the measure or count its own value")  # fmt: skip
            return
        grades += reading.number_words
    c.mentions.append(tuple(words))
    if grades:
        c.cited.append(tuple(sorted(set(grades))))


def _replaced_by_answers(spec: PartSpec, c: _Collect) -> None:
    """Brief words are replaced by the person's answers only where the spec uses one.

    That reason is Forge's record of an answer (:mod:`forge_spec.questions`),
    and the person reads it as such: a draft that gives it with no answer of
    theirs in use would pass its own choice off as theirs.
    """
    person = {i for s in c.brief.answers for i in s.words} - c.brief.answer_labels()
    used = {i for r in c.readings for i in r.words} | {
        i for ref in (*c.cited, *c.mentions) for i in ref
    }
    if person & used:
        return
    for n, entry in enumerate(spec.not_modelled):
        if entry.reason.lower().startswith(REPLACED_BY_ANSWER):
            c.fault(pointer("not_modelled", n, "reason"),
                    "only an answer of the person's replaces the brief's words, and the spec uses none: "
                    "say why the part won't have this")  # fmt: skip


def check_draft(brief: NumberedBrief, raw: Any, *, strict: bool = False) -> SpecReport:
    """Read, place and check a draft. ``strict`` is --auto: every word accounted for."""
    spec, read_problems = read_draft(raw)
    problems = [SpecProblem("fault", p.at, p.message) for p in read_problems.faults]
    notes = tuple(read_problems.notes)
    if spec is None:
        return SpecReport(None, None, tuple(problems), (), (), notes, None, strict)
    c = _Collect(brief, [], [], [], problems, [], [], strict)
    _check_values(spec, c)
    _check_requirements(spec, c)
    layout = solve(spec)
    problems.extend(SpecProblem(i.kind, i.at, i.message) for i in layout.issues)
    c.assumptions.extend(layout.assumptions)
    _physical(spec, layout, c)
    not_modelled = []
    for n, entry in enumerate(spec.not_modelled):
        if c.words_exist(entry.words, pointer("not_modelled", n, "words")):
            not_modelled.append(entry.words)
    _replaced_by_answers(spec, c)
    silent = []
    for n, quiet in enumerate(spec.silent):
        if 0 <= quiet.sentence < len(brief.sentences):
            silent.append(quiet.sentence)
        else:
            c.fault(pointer("silent", n, "sentence"),
                    f"sentence {quiet.sentence} doesn't exist: the brief has sentences 0 to "
                    f"{len(brief.sentences) - 1}")  # fmt: skip
    owners = _owners(spec, brief)
    try:
        accounting = account(brief, readings=c.readings, cited=c.cited, mentions=c.mentions,
                             not_modelled=not_modelled, silent=silent, owners=owners)  # fmt: skip
    except LookupError as exc:  # pragma: no cover - every citation was checked above
        problems.append(SpecProblem("fault", "", str(exc)))
        return SpecReport(spec, layout, tuple(problems), tuple(c.assumptions), tuple(c.caveats),
                          notes, None, strict)  # fmt: skip
    for word in accounting.uncited_numbers:
        problems.append(SpecProblem("question", pointer("brief", "words", word.index),
                                    f"the brief says {_unused(word, accounting)}; nothing in the spec uses it"))  # fmt: skip
    for sentence in accounting.uncited_sentences:
        problems.append(SpecProblem("question", pointer("brief", "sentences", sentence.index),
                                    f"nothing in the spec comes from: {brief.sentence_text(sentence)!r}"))  # fmt: skip
    if strict:
        for word in accounting.uncited_words:
            problems.append(SpecProblem("question", pointer("brief", "words", word.index),
                                        f"nothing in the spec uses the word {word.text!r}"))  # fmt: skip
        # An automatic run may leave out, or take as silent, only what can't be a shape.
        named = _part_named(spec, brief)
        for n, quiet in enumerate(spec.silent):
            if 0 <= quiet.sentence < len(brief.sentences):
                said = {t for s, t in named if s != quiet.sentence}
                leaves = _shape_words(
                    brief, brief.sentences[quiet.sentence].words, named=said
                )
                if leaves:
                    problems.append(SpecProblem("question", pointer("silent", n),
                                                f"an automatic run can't take as silent a sentence that may "
                                                f"say something of the shape: {leaves}"))  # fmt: skip
        for n, entry in enumerate(spec.not_modelled):
            leaves = _shape_words(brief, entry.words)
            if leaves:
                problems.append(SpecProblem("question", pointer("not_modelled", n),
                                            f"an automatic run can't leave out what the brief says of the shape: "
                                            f"{leaves}"))  # fmt: skip
    unique: dict[tuple[str, str, str], SpecProblem] = {}
    for problem in problems:
        unique.setdefault((problem.kind, problem.at, problem.message), problem)
    assumptions = tuple(dict.fromkeys(c.assumptions))
    return SpecReport(spec, layout, tuple(unique.values()), assumptions, tuple(c.caveats), notes,
                      accounting, strict)  # fmt: skip
