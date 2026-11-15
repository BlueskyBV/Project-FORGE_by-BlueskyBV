"""The brief, numbered word by word.

Everything the spec claims about a part has to point back at the words of the
brief it came from. V1 let a model write character offsets, and models count
characters badly, so a citation could point a few letters to one side and
still look plausible. V2 numbers the words before the model ever sees the
brief, shows it the numbers, and accepts only word numbers back. The model can
then cite only words that exist. Whether a value really follows from the words
it cites is checked separately, in :mod:`forge_spec.citations`.

What counts as a word
---------------------
A word is a run of non-space characters with surrounding punctuation and
markup (``*bold*``, ``_this_``, quotes, brackets) removed, and with at least
one letter, digit or measuring symbol left (``°``, ``"``, ``Ø``, ``±``, ``%``,
a multiplication sign, a fraction such as ``½``). Hyphenated and compound
forms stay whole ("M4x0.7", "1/4-20", "twenty-four", "4mm-thick"), because
splitting them would separate a number from the thing that gives it meaning.

A quote or prime mark straight after a digit is a unit (``2"`` and ``2''`` are
two inches, ``3'`` is three feet), unless it closes a quote opened earlier in
the sentence ("an "M4" screw" is an M4 screw, not four inches).

A list marker at the start of a line ("1.", "b)", "(ii)", "- ") starts a new
sentence. A numbered marker stays a word: Forge doesn't guess that "4." at
the start of a line is list numbering rather than a size. The spec writer
lists it as not modelled, and the person sees that. A guess that dropped a
real number would be the one mistake this module must never make.

What counts as a sentence
-------------------------
A sentence ends after ``.``, ``!``, ``?``, ``;`` or an ellipsis, including
where there is no space after it ("long.Hollow"). A decimal point is inside a
word and never ends anything. A few abbreviations that hardly ever end a
sentence ("e.g.", "approx.") end one only before a capital letter, and a few
that stand before numbers ("no. 6", "dia. 5") only before anything but a
digit. Every other full stop ends a sentence, "in." and "max." included.

Every line break ends a sentence too, unless the line before ends with a
hyphen or with a word that can't end one ("and", "with", "of" and the like).
So a brief written as a list of lines without full stops has one sentence per
line.

When in doubt the rules split rather than merge. Merging two sentences could
let one of them go unaccounted for behind a word cited in the other;
splitting one costs at most a question.

None of this decides what a word means. Its only job is to number the words
and sentences the same way every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ABBREVIATIONS",
    "ANSWER_PREFIXES",
    "NUMBER_ABBREVIATIONS",
    "REPLACED_BY_ANSWER",
    "NumberedBrief",
    "Sentence",
    "Word",
    "WordRef",
    "number_words",
]

#: A citation: the indices of the words a value came from.
WordRef = tuple[int, ...]

#: Quote pairs: an opening mark and the mark that closes it.
_QUOTES = {
    '"': '"',
    "'": "'",
    "\u201c": "\u201d",
    "\u2018": "\u2019",
    "\u00ab": "\u00bb",
}
#: Characters peeled off the front of a chunk.
_OPENING = "([{*_`" + "".join(_QUOTES)
#: Characters peeled off the back of a chunk (a unit mark after a digit excepted).
_CLOSING = ")]}*_`.,;:!?\u2026\u3002\uff01\uff1f" + "".join(_QUOTES.values())
#: Marks that, straight after a digit, are a unit: inch and foot, in straight,
#: curly and prime forms.
_UNIT_MARKS = "\"'\u2033\u2032\u201d\u2019"
#: Characters that make a chunk worth numbering without a letter or digit.
_MEASURING_SYMBOLS = "\u00b0\u2033\u2032\"'%\u00d8\u2300\u00f8\u00b1\u00d7\u00bd\u2153\u2154\u00bc\u00be\u2155\u2156\u2157\u2158\u2159\u215a\u215b\u215c\u215d\u215e\u2152\u201d\u2019"
#: Marks that end a sentence. A full stop is handled on its own (decimals,
#: abbreviations).
_ENDERS = "!?;\u2026\u3002\uff01\uff1f"
#: Characters that separate words although they aren't white space.
_INVISIBLE_SPACES = "\u200b\u2060\ufeff"

#: Abbreviations that almost never end a sentence: their full stop ends one
#: only before a capital letter ("e.g. like a coin" carries on).
ABBREVIATIONS = frozenset(
    {"approx", "ca", "cf", "e.g", "eg", "fig", "i.e", "ie", "incl", "vs", "wrt"}
)  # fmt: skip
#: Abbreviations that often end a sentence but also stand before a number
#: ("no. 6 screw", "dia. 5 mm"): their full stop ends one unless a digit
#: follows. Units ("in.", "mm.") and limits ("max.") always end one, because
#: what follows them is far more often a new sentence than a number.
NUMBER_ABBREVIATIONS = frozenset({"dia", "no", "nos", "ref"})

#: Words that can't end a sentence, so a line ending in one carries on.
#: ("in" and "x" are left out: "Width 2 in" and "60 x" can end a line of a
#: list, and merging there could hide the next line.)
_CARRY_ON = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "from", "into", "of", "on", "or",
     "than", "the", "to", "with"}
)  # fmt: skip

_ENUMERATOR = re.compile(r"^\(?(?:\d{1,2}|[A-Za-z]|[ivxlcIVXLC]{1,5})[.)]$")
_BULLETS = "-*\u2022\u2013\u2014+\u00b7"
_INNER_BREAK = re.compile(
    r"(?<=[^\W\d_])(?:[.](?=[A-Z])|[!?;\u2026\u3002\uff01\uff1f](?=[^\W\d_]))"
    r"|(?<=\d)[.](?=[A-Z][a-z])"  # "60.Two holes": a stop after a number, then a word
)


@dataclass(frozen=True)
class Word:
    """One numbered word of the brief.

    ``marker`` is set for a list marker at the start of a line ("1.", "b)").
    """

    index: int
    text: str
    start: int
    end: int
    sentence: int
    marker: bool = False


@dataclass(frozen=True)
class Sentence:
    """One sentence of the brief: a contiguous run of words."""

    index: int
    first: int
    last: int
    start: int
    end: int

    @property
    def words(self) -> range:
        return range(self.first, self.last + 1)


#: How the person's additions read in a brief: each starts a sentence of its
#: own, and only the person's part of a brief (``answers_from`` on) holds them.
ANSWER_PREFIXES = ("Answer about ", "Note from the person: ")
#: How a reason says that brief words were replaced by the person's answer:
#: Forge's own record of an answer, which a draft may give only when the
#: spec uses one of the person's answers.
REPLACED_BY_ANSWER = "replaced by the person's answer"


@dataclass(frozen=True)
class NumberedBrief:
    """The brief with every word and sentence numbered.

    ``answers_from`` is where the person's answers and notes begin, added
    after the brief they wrote (:mod:`forge_spec.questions`); None when there
    are none. It is part of the brief's identity: a sentence of the brief
    itself that happens to read "Answer about ..." is never taken for one.
    """

    text: str
    words: tuple[Word, ...]
    sentences: tuple[Sentence, ...]
    answers_from: int | None = None
    #: Results other modules derive from the brief once and reuse. Not part of
    #: the brief's identity.
    memo: dict[str, Any] = field(
        default_factory=dict, compare=False, hash=False, repr=False
    )

    def word(self, index: int) -> Word:
        """The word with this number, or a ``LookupError`` naming the range."""
        if isinstance(index, bool) or not isinstance(index, int):
            raise LookupError(f"a word number must be an integer, got {index!r}")
        if not 0 <= index < len(self.words):
            raise LookupError(
                f"word {index} does not exist: the brief has words "
                f"0 to {len(self.words) - 1}"
            )
        return self.words[index]

    def sentence_text(self, sentence: Sentence) -> str:
        return self.text[sentence.start : sentence.end]

    @property
    def answers(self) -> tuple[Sentence, ...]:
        """The sentences of the person's answers and notes, in the order they were added."""
        if self.answers_from is None:
            return ()
        return tuple(s for s in self.sentences if s.start >= self.answers_from)

    def answer_labels(self) -> frozenset[int]:
        """The words that only label an answer: "Answer about h2 depth" in "...: 3 mm".

        They say which field an answer is for and nothing about the part, so
        they need no citation (an item called "h2" holds no number).
        """
        found: set[int] = set()
        for sentence in self.answers:
            text = self.sentence_text(sentence)
            colon = text.find(":")
            if not text.startswith(ANSWER_PREFIXES) or colon < 0:
                continue
            end = sentence.start + colon
            found.update(i for i in sentence.words if self.words[i].end <= end)
        return frozenset(found)

    def quote(self, ref: WordRef) -> str:
        """The cited words, in order, as the person will see them quoted."""
        return " ".join(self.word(i).text for i in sorted(set(ref)))

    def for_the_model(self) -> str:
        """The brief as the spec writer sees it: one sentence per line.

        ``S0: [0]A [1]PLA [2]spacer ...``. The numbers are the only thing a
        citation may contain, so square brackets inside a word are shown as
        round ones: a brief can't show the model a word number that isn't one.
        """
        lines = []
        for sentence in self.sentences:
            words = " ".join(
                f"[{i}]{self.words[i].text.replace('[', '(').replace(']', ')')}"
                for i in sentence.words
            )
            lines.append(f"S{sentence.index}: {words}")
        return "\n".join(lines)


@dataclass(frozen=True)
class _Chunk:
    raw: str
    start: int
    line_start: bool
    newline_before: bool
    blank_line_before: bool


def _chunks(text: str) -> list[_Chunk]:
    """Runs of non-space text, split again where a sentence ends inside one."""
    chunks: list[_Chunk] = []
    previous_end = 0
    for match in re.finditer(rf"[^\s{_INVISIBLE_SPACES}]+", text):
        newlines = text[previous_end : match.start()].count("\n")
        previous_end = match.end()
        raw, base = match.group(), match.start()
        cuts = [0, *(m.end() for m in _INNER_BREAK.finditer(raw)), len(raw)]
        for k in range(len(cuts) - 1):
            if cuts[k] == cuts[k + 1]:
                continue
            first = k == 0
            chunks.append(
                _Chunk(
                    raw=raw[cuts[k] : cuts[k + 1]],
                    start=base + cuts[k],
                    line_start=first and (newlines > 0 or base == 0),
                    newline_before=first and newlines > 0,
                    blank_line_before=first and newlines > 1,
                )
            )
    return chunks


def _strip(raw: str, open_quote: str | None) -> tuple[int, int, str | None]:
    """Peel surrounding punctuation off ``raw``.

    Returns the span left, and the quote still open after this chunk. A unit
    mark after a digit stays, unless it closes the open quote: one opened
    earlier in the sentence (``open_quote``) or at the start of this chunk.
    """
    low, high = 0, len(raw)
    while low < high and raw[low] in _OPENING:
        if raw[low] in _QUOTES:
            open_quote = raw[low]
        low += 1
    closer = _QUOTES.get(open_quote) if open_quote else None
    while high > low and raw[high - 1] in _CLOSING:
        mark = raw[high - 1]
        after_digit = high - 2 >= low and raw[high - 2].isdigit()
        two_apostrophes = (
            raw[low:high].endswith("''") and high - 3 >= low and raw[high - 3].isdigit()
        )
        if mark == closer:
            closer = open_quote = None
        elif mark in _UNIT_MARKS and (after_digit or two_apostrophes):
            break
        high -= 1
    return low, high, open_quote


def _is_word(text: str) -> bool:
    return any(c.isalnum() or c in _MEASURING_SYMBOLS for c in text)


def _ends(tail: str) -> str:
    """'yes', 'no' or 'stop' (a full stop, which may be an abbreviation's)."""
    if any(c in _ENDERS for c in tail) or "..." in tail:
        return "yes"
    return "stop" if "." in tail else "no"


def _starts_capital(text: str) -> bool:
    for c in text:
        if c.isalpha():
            return c.isupper()
        if c.isdigit():
            return False
    return False


def number_words(brief: str, *, answers_from: int | None = None) -> NumberedBrief:
    """Number every word and sentence of ``brief``.

    ``answers_from``: where the person's additions begin, at the start of a
    sentence (:attr:`NumberedBrief.answers_from`).

    >>> numbered = number_words("A plate 60 mm long. Two 4 mm holes.")
    >>> [w.text for w in numbered.words]
    ['A', 'plate', '60', 'mm', 'long', 'Two', '4', 'mm', 'holes']
    >>> len(numbered.sentences)
    2
    """
    if not isinstance(brief, str):
        raise TypeError("a brief is text")
    if answers_from is not None and (
        isinstance(answers_from, bool)
        or not isinstance(answers_from, int)
        or not 0 <= answers_from <= len(brief)
    ):
        raise ValueError(
            f"answers_from must be a place in the brief, 0 to {len(brief)}"
        )
    words: list[Word] = []
    sentences: list[Sentence] = []
    first: int | None = None
    previous_raw = ""
    open_quote: str | None = None
    after_abbreviation = ""  # "soft", "number" or ""

    def close() -> None:
        nonlocal first, open_quote, after_abbreviation
        if first is not None:
            last = len(words) - 1
            sentences.append(
                Sentence(
                    len(sentences), first, last, words[first].start, words[last].end
                )
            )
        first, open_quote, after_abbreviation = None, None, ""

    for chunk in _chunks(brief):
        raw, start = chunk.raw, chunk.start
        marker = chunk.line_start and bool(_ENUMERATOR.match(raw))
        bullet = chunk.line_start and raw[0] in _BULLETS
        if bullet and len(raw) > 1 and raw[1].isalpha():
            raw, start = raw[1:], start + 1  # "-hollow": the bullet, then the word
        if chunk.newline_before:
            carries_on = previous_raw.endswith("-") or (
                previous_raw.strip(_OPENING + _CLOSING).lower() in _CARRY_ON
            )
            if chunk.blank_line_before or marker or bullet or not carries_on:
                close()
        previous_raw = chunk.raw

        low, high, still_open = _strip(raw, open_quote)
        text = raw[low:high]
        tail = raw[high:]
        if not text or not _is_word(text):
            # No word, but a quote it opens or closes is opened or closed: "“¶ 5”" quotes a 5, not 5 inches.
            open_quote = still_open
            if first is not None and _ends(raw) != "no":
                close()
            continue
        soft_end = after_abbreviation == "soft" and _starts_capital(text)
        number_end = after_abbreviation == "number" and not text[:1].isdigit()
        if soft_end or number_end:
            close()
        after_abbreviation = ""
        open_quote = still_open

        if first is None:
            first = len(words)
        words.append(
            Word(len(words), text, start + low, start + high, len(sentences), marker)
        )
        ending = "no" if marker else _ends(tail)
        if ending == "stop" and text.lower() in ABBREVIATIONS:
            after_abbreviation = "soft"
        elif ending == "stop" and text.lower() in NUMBER_ABBREVIATIONS:
            after_abbreviation = "number"
        elif ending != "no":
            close()
    close()
    if answers_from is not None and any(
        s.start < answers_from < s.end for s in sentences
    ):
        raise ValueError("the person's additions must begin a sentence of their own")
    return NumberedBrief(
        text=brief,
        words=tuple(words),
        sentences=tuple(sentences),
        answers_from=answers_from,
    )
