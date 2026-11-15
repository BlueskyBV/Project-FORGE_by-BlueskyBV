"""Nothing in the brief may quietly disappear.

V1's commonest false pass was a claim nobody made: the brief said "fully
rounded ends" or "hollow", no rule turned it into a check, and the part passed
without it. In V2 the spec writer cites the brief's words for everything it
writes, and this module checks that the citations cover the whole brief:

- **every number** (a word with a digit or a fraction, or a number word such
  as "four", "four-hole" or "pair"; not "both" pairing two short things with
  "and", "through both the flange and the hub", which names them, not a
  count) is used by a value, or listed as not modelled. A number word a spec
  holds otherwise is used by what holds it (forge_spec.checks): the option a
  choice names ("half" of a ball), the faces a shell opens ("open at both
  ends"), the two copies an ``ends`` pattern places ("along both edges");
- **every sentence** has a word used by the spec, is listed as not modelled,
  or is declared to say nothing about the shape (with a reason the person
  sees);
- **in --auto mode, every word** that isn't a common function word is used or
  listed as not modelled. Nobody confirms an automatic run, so nothing may be
  left to judgement. A linking word ("in", "on", "at", "from", "for") is used
  by an item when the nearest used words either side of it in its sentence
  are both that item's, nothing but common or linking words between: it
  joins two parts of the item's own description, whose values account for
  it. So is "in", "of" or "from" just before the material's words ("in
  PLA"). A count word or a negation never is (docs/V2-stage4.md, 14.4).

What counts as *using* a number is strict. A value accounts only for the
numbers its matched reading used (:func:`forge_spec.citations.check_quantity`),
number by number inside a word, not for every word its citation happened to
list. Otherwise a hole's diameter citing "5 mm ... and 2 mm fillets" would
account for the fillets, or a length citing "60x40x10mm" would account for the
width and height, and they could vanish. An item's descriptive citations
("rounded", "hole") count for sentences and words, never for numbers.

This module doesn't decide what anything means, and it can't tell a good
citation from a careless one: that is what the preview, the second draft and
the person are for. It only makes sure every number and every sentence was
looked at. At worst a false flag costs one question.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from .citations import Reading, numeric_at, slot_count
from .words import NumberedBrief, Sentence, Word

__all__ = ["FUNCTION_WORDS", "LINKING_WORDS", "MATERIAL", "Accounting", "account"]

#: Words that carry no meaning about the part on their own. Closed and short
#: on purpose: negations ("no", "not", "without"), quantifiers ("each",
#: "every", "all", "only") and prepositions of place ("on", "through",
#: "from") are left out, because each of them can change the shape.
FUNCTION_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "of", "with", "x", "by", "to",
        "is", "are", "be", "was", "were", "been", "it", "its", "this", "that",
        "these", "those", "which", "there", "so", "then", "also", "just", "as",
        "i", "me", "my", "we", "us", "our", "you", "your", "please", "need",
        "needs", "want", "wants", "would", "like", "should", "must", "will",
        "can", "could", "have", "has", "make", "made", "design", "create",
        "model", "print", "printed",
    }
)  # fmt: skip


#: Words that link two parts of one description ("hollow on the inside", "5 mm deep from the top
#: face"): used by an item whose words stand either side of them (:func:`account`). Not common
#: words: away from one item's words each of them can change the shape.
LINKING_WORDS = frozenset({"in", "on", "at", "from", "for"})
#: Linking words that say what a thing is made of, just before the material's words ("in PLA").
_OF_MATERIAL = frozenset({"in", "of", "from"})
#: The owner the part's material is given as in ``owners`` (:func:`account`).
MATERIAL = "requirements.material"


@dataclass(frozen=True)
class Accounting:
    """What in the brief nothing in the spec accounts for."""

    uncited_numbers: tuple[Word, ...]
    uncited_sentences: tuple[Sentence, ...]
    uncited_words: tuple[Word, ...]
    #: The numbers used, slot by slot: (word, position in the word).
    used_slots: frozenset[tuple[int, int]] = frozenset()

    def complete(self, *, strict: bool) -> bool:
        """Accounted for in full; ``strict`` adds every content word (--auto)."""
        done = not self.uncited_numbers and not self.uncited_sentences
        return done and (not strict or not self.uncited_words)


def _indices(brief: NumberedBrief, refs: Iterable[Iterable[int]]) -> set[int]:
    found: set[int] = set()
    for ref in refs:
        for i in ref:
            brief.word(i)  # a citation to nowhere raises LookupError
            found.add(i)
    return found


def account(
    brief: NumberedBrief,
    *,
    readings: Iterable[Reading] = (),
    cited: Iterable[Iterable[int]] = (),
    mentions: Iterable[Iterable[int]] = (),
    not_modelled: Iterable[Iterable[int]] = (),
    silent: Iterable[int] = (),
    owners: Mapping[int, frozenset[str]] | None = None,
) -> Accounting:
    """Check that the spec accounts for the whole brief.

    ``readings``: the reading each brief value matched
    (``CitationCheck.reading``). Its ``numbers`` say which numbers it used,
    slot by slot, so a word holding "60x40x10mm" is accounted for only once
    all three are used. ``cited``: words cited by table and formula values,
    whose own checks verify them; they account for every number in those
    words. ``mentions``: the words items cite to say what they are
    ("rounded", "hole"); they never account for a number. ``not_modelled``:
    the words of things the brief says that the part won't have.
    ``silent``: the numbers of sentences declared to say nothing about the
    shape. ``owners``: who cites each word, by item id (and :data:`MATERIAL`
    for the material's words), for the linking words of an automatic run.

    A word or sentence number that doesn't exist raises ``LookupError``: a
    citation to nowhere is a fault in the draft, reported before this runs.
    """
    matched = list(readings)
    used_slots: set[tuple[int, int]] = set()
    read_words: set[int] = set()
    for reading in matched:
        read_words |= _indices(brief, [reading.words])
        used_slots |= set(reading.numbers)
    whole = _indices(brief, cited)
    described = _indices(brief, mentions)
    excused = _indices(brief, not_modelled)
    # An answer's label ("Answer about h2 depth:") names a field, not the
    # part: it needs no citation, but it never makes its sentence cited.
    # Only a use of the answer itself does.
    labels = brief.answer_labels()
    quiet: set[int] = set()
    for s in silent:
        if isinstance(s, bool) or not isinstance(s, int):
            raise LookupError(f"a sentence number must be an integer, got {s!r}")
        if not 0 <= s < len(brief.sentences):
            raise LookupError(f"sentence {s} does not exist")
        quiet.add(s)

    def number_used(i: int) -> bool:
        if i in whole or i in excused or i in labels:
            return True
        return all((i, k) in used_slots for k in range(slot_count(brief, i)))

    covered = read_words | whole | described | excused
    # A sentence taken to say nothing about the shape has no word left to cite
    # (its numbers still need a use: they can't be silent).
    words_covered = (
        covered
        | labels
        | {i for s in brief.sentences if s.index in quiet for i in s.words}
    )
    uncited_numbers = tuple(
        w
        for w in brief.words
        if numeric_at(brief, w.index) and not number_used(w.index)
    )
    uncited_sentences = tuple(
        s
        for s in brief.sentences
        if s.index not in quiet and not any(i in covered for i in s.words)
    )
    linked = _linked(brief, owners or {})
    uncited_words = tuple(
        w
        for w in brief.words
        if w.index not in words_covered
        and w.index not in linked
        and w.text.lower() not in FUNCTION_WORDS
        and not (w.marker and not numeric_at(brief, w.index))
    )
    return Accounting(
        uncited_numbers, uncited_sentences, uncited_words, frozenset(used_slots)
    )


def _linked(brief: NumberedBrief, owners: Mapping[int, frozenset[str]]) -> set[int]:
    """The linking words an item, or the material, uses by where they stand (see the module's docstring).

    >>> from .words import number_words
    >>> b = number_words("A 30 mm cube in PLA, hollow on the inside. A slot at each end.")
    >>> sorted(b.word(i).text for i in _linked(b, {3: frozenset({"cube"}), 5: frozenset({MATERIAL}),
    ...     6: frozenset({"hollow"}), 9: frozenset({"hollow"}), 11: frozenset({"slot"}), 15: frozenset({"slot"})}))
    ['in', 'on']
    """
    found: set[int] = set()
    for sentence in brief.sentences:
        words = list(sentence.words)
        for n, i in enumerate(words):
            text = brief.word(i).text.lower()
            if text not in LINKING_WORDS and text not in _OF_MATERIAL:
                continue
            if i in owners:
                continue
            before = _nearest(brief, owners, reversed(words[:n]))
            after = _nearest(brief, owners, iter(words[n + 1 :]))
            if after is None:
                continue
            of_material = text in _OF_MATERIAL and MATERIAL in owners[after]
            one_item = (
                text in LINKING_WORDS
                and before is not None
                and bool((owners[before] & owners[after]) - {MATERIAL})
            )
            if of_material or one_item:
                found.add(i)
    return found


def _nearest(
    brief: NumberedBrief, owners: Mapping[int, frozenset[str]], words: Iterator[int]
) -> int | None:
    """The first word with an owner, over common and linking words only; None if another word comes first."""
    for i in words:
        if i in owners:
            return i
        text = brief.word(i).text.lower()
        if text not in FUNCTION_WORDS and text not in LINKING_WORDS:
            return None
    return None
