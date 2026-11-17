"""Questions to the person, and their answers applied by code (plan, section 4.2).

Every question the checks ask, and every assumption the writer made, is put
to the person in one round, multiple choice where it can be: "it goes right
through", "it is __ mm deep", "it says nothing about the shape". Each answer
is a typed edit that code applies to the draft. No model reads it, so no
redraft is needed, unless the person writes a note instead: then the writer
redrafts with it.

An answer becomes part of the brief. Answering "3 mm" for a hole's depth adds
the sentence "Answer about h depth: 3 mm." to the brief, and the depth cites
its words, so the answer is checked like every other value, accounted for
like every other number, and locked with the brief: the confirmed contract is
the brief and the person's answers, together.

- :func:`questions`: the questions of a checked draft, with their options.
- :func:`apply_answers`: the brief and draft with the answers applied.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from .checks import SpecReport, check_draft
from .compare import Difference
from .problems import MAX_REASON, one_line
from .schema import (
    AXES,
    DIRECTIONS,
    FACE_AXES,
    FACE_OWN_AXES,
    FACE_SIDES,
    IN_FACE_AXES,
    KINDS,
    FieldType,
    material_words,
)
from .wire import to_wire
from .words import ANSWER_PREFIXES, REPLACED_BY_ANSWER, NumberedBrief, number_words

__all__ = [
    "ANSWER_PREFIXES",
    "Answer",
    "AnswerError",
    "Answered",
    "Option",
    "Question",
    "apply_answers",
    "questions",
]


class EditKind(StrEnum):
    """What choosing an option does to the draft: set a value, a count, a cut through, a choice or a text; leave a sentence out (not modelled, or silent on the shape); pass a note on; or keep what is drafted."""

    VALUE = "value"
    COUNT = "count"
    THROUGH = "through"
    CHOOSE = "choose"
    TEXT = "text"
    NOT_MODELLED = "not_modelled"
    SILENT = "silent"
    NOTE = "note"
    KEEP = "keep"


#: The edits that set a field of the draft (one answer each).
SETS_A_FIELD = frozenset(
    {EditKind.VALUE, EditKind.COUNT, EditKind.THROUGH, EditKind.CHOOSE, EditKind.TEXT}
)


class AnswerError(ValueError):
    """An answer that doesn't fit its question: the person is asked again."""


@dataclass(frozen=True)
class Option:
    """One answer the person may give, and the edit it makes.

    ``value`` asks the person for a size (in ``unit``, or another they name)
    and ``count`` for a whole number; ``through``, ``choose``,
    ``not_modelled`` and ``silent`` need nothing more; ``note`` takes the
    person's own words, for the writer to redraft with.
    """

    label: str
    kind: EditKind
    at: str = ""  # the draft field it sets
    choice: str = ""
    unit: str = ""
    words: tuple[int, ...] = ()
    sentence: int = -1


@dataclass(frozen=True)
class Question:
    """A question, or an assumption the person may change, with its options."""

    id: str  # "q1", "q2"...: its place in the round
    kind: Literal["question", "assumption"]
    at: str
    text: str
    options: tuple[Option, ...]


@dataclass(frozen=True)
class Answer:
    """The person's answer to one question: which option, and what they gave.

    ``at`` and ``asked``, when given, must be the question's own pointer and
    text: an answer written down for one round (``forge spec --answers``)
    can then never be applied to a different question that took its place.
    """

    question: str
    option: int
    number: float | None = None
    unit: str | None = None
    text: str = ""
    at: str = ""
    asked: str = ""


@dataclass(frozen=True)
class Answered:
    """The brief with the person's answers added, and the draft with them applied."""

    brief: NumberedBrief
    draft: dict[str, Any]
    #: The person's notes: the writer must redraft with them. Empty when
    #: every answer was applied by code.
    notes: tuple[str, ...]


def _note() -> Option:
    return Option("Something else (tell the writer)", EditKind.NOTE)


# ----------------------------------------------------------------------
# The questions
# ----------------------------------------------------------------------
def questions(
    report: SpecReport, differences: Sequence[Difference] = ()
) -> tuple[Question, ...]:
    """The round of questions for a checked draft: its questions, then its assumptions.

    Faults are not the person's (they go back to the writer), and a CAN'T or
    UNABLE ends the run; only questions and assumptions are asked.
    ``differences`` are where a second draft read the brief otherwise
    (:mod:`forge_spec.compare`): each is asked too, and may be answered "it
    is right as drafted", which changes nothing.
    """
    raw = _wire(report)
    found: list[Question] = []
    # One question per field: where the second draft differs on a value this
    # draft assumed, the difference is asked, saying so, and not the assumption.
    assumed = {a.at: a.message for a in report.assumptions}
    for difference in differences:
        kept = Option("It is right as drafted here", EditKind.KEEP)
        options = (
            *(o for o in _options(difference.at, raw) if o.kind != EditKind.NOTE),
            kept,
            _note(),
        )
        also = (
            f" (this draft assumed it: {assumed[difference.at]})"
            if difference.at in assumed
            else ""
        )
        found.append(Question(f"q{len(found) + 1}", "question", difference.at,
                              f"the second draft reads this otherwise: {difference.message}{also}", options))  # fmt: skip
    asked = {d.at for d in differences}
    for problem in report.problems:
        if problem.kind == "question":
            options = _options(problem.at, raw)
            found.append(
                Question(
                    f"q{len(found) + 1}",
                    "question",
                    problem.at,
                    problem.message,
                    options,
                )
            )
    for assumption in report.assumptions:
        if assumption.at in asked:
            continue
        options = tuple(
            o
            for o in _options(assumption.at, raw)
            if o.kind not in (EditKind.NOT_MODELLED, EditKind.SILENT)
        )
        found.append(
            Question(
                f"q{len(found) + 1}",
                "assumption",
                assumption.at,
                assumption.message,
                options,
            )
        )
    return tuple(found)


def _wire(report: SpecReport) -> dict[str, Any]:
    return to_wire(report.spec) if report.spec is not None else {}


def _options(at: str, draft: Mapping[str, Any]) -> tuple[Option, ...]:
    parts = (
        [p.replace("~1", "/").replace("~0", "~") for p in at.split("/")[1:]]
        if at
        else []
    )
    if parts[:2] == ["brief", "words"] and len(parts) == 3:
        word = int(parts[2])
        return (
            Option(
                "It says nothing about the shape: leave it out",
                EditKind.NOT_MODELLED,
                words=(word,),
            ),
            _note(),
        )
    if parts[:2] == ["brief", "sentences"] and len(parts) == 3:
        sentence = int(parts[2])
        return (Option("It says nothing about the shape", EditKind.SILENT, sentence=sentence),
                Option("It is something the part won't have: leave it out", EditKind.NOT_MODELLED, sentence=sentence),
                _note())  # fmt: skip
    if parts == ["requirements", "material"]:
        return (Option("It is __ (name it)", EditKind.TEXT, at), _note())
    target = _target(parts, draft)
    if target is None:
        return (_note(),)
    path, node, field_type, choices = target
    here = "/" + "/".join(path)
    found: list[Option] = []
    if field_type is FieldType.DEPTH:
        found.append(Option("It goes right through", EditKind.THROUGH, here))
    if "choose" in node:
        found += [
            Option(f"It is {c}", EditKind.CHOOSE, here, choice=c) for c in choices
        ]
    elif "count" in node:
        found.append(Option("It is this many: __", EditKind.COUNT, here))
    elif "value" in node or "through" in node:
        unit = str(node.get("unit", "mm")) if "value" in node else "mm"
        found.append(Option(f"It is __ {unit}", EditKind.VALUE, here, unit=unit))
    return (*found, _note())


def _target(parts: list[str], draft: Mapping[str, Any]) -> tuple[list[str], Mapping[str, Any], FieldType | None,
                                                                  tuple[str, ...]] | None:  # fmt: skip
    """The deepest value, count, depth or choice on the way to ``parts``, with its field's type and choices."""
    if len(parts) < 3 or parts[0] != "items" or not parts[1].isdigit():
        return None
    items = draft.get("items", [])
    n = int(parts[1])
    if n >= len(items):
        return None
    item = items[n]
    spec = KINDS.get(str(item.get("kind")))
    field = spec.field(parts[2]) if spec and parts[2] in spec.field_names else None
    node: Any = item
    best: (
        tuple[list[str], Mapping[str, Any], FieldType | None, tuple[str, ...]] | None
    ) = None
    for depth, key in enumerate(parts[2:], start=3):
        if not isinstance(node, Mapping) or key not in node:
            break
        node = node[key]
        if (
            isinstance(node, Mapping)
            and "from" in node
            and {"value", "count", "through", "choose"} & set(node)
        ):
            kind = field.type if field is not None and depth == 3 else None
            choices = (
                field.choices
                if field is not None and depth == 3
                else (_face_axes(item) if key == "axis" else ())
            )
            chosen = node.get("choose")
            if chosen in FACE_OWN_AXES:  # an axis of its face, named by the face's own names
                choices = FACE_OWN_AXES
            elif choices == IN_FACE_AXES:  # or by the part's
                choices = AXES
            elif choices == (*DIRECTIONS, *FACE_SIDES):  # a way along one, either way
                choices = FACE_SIDES if chosen in FACE_SIDES else DIRECTIONS
            best = (parts[:depth], node, kind, choices)
    return best


def _face_axes(item: Mapping[str, Any]) -> tuple[str, ...]:
    """The axes a pattern, a slot or a rib can run along on the item's face, named by the part's: x or y on +z."""
    on = item.get("on")
    face = on.get("face") if isinstance(on, Mapping) else None
    return FACE_AXES.get(str(face), AXES)


# ----------------------------------------------------------------------
# The answers
# ----------------------------------------------------------------------
def apply_answers(brief: NumberedBrief, draft: Mapping[str, Any], round_: Sequence[Question],
                  answers: Sequence[Answer]) -> Answered:  # fmt: skip
    """The brief and draft with the person's answers applied, each as a typed edit.

    A number or a choice the person gives is added to the brief as a sentence
    of its own, after the brief (:attr:`NumberedBrief.answers_from`), and the
    field cites it; brief words the answer replaces, and nothing else still
    uses, are listed as not modelled, with the answer as the reason.

    The edited draft is checked before it is handed back: an answer the field
    can't take (a depth in degrees, a count of none, an axis the face hasn't
    got) raises :class:`AnswerError`, and then nothing is applied, so the
    person is asked again and no bad answer stays in the brief.
    """
    by_id = {q.id: q for q in round_}
    edits: list[
        tuple[Question, Option, Answer, str]
    ] = []  # with the sentence each adds, or ""
    seen: set[str] = set()
    for answer in answers:
        question = by_id.get(answer.question)
        if question is None:
            raise AnswerError(f"there is no question {answer.question!r} in this round")
        if answer.question in seen:
            raise AnswerError(
                f"{answer.question} is answered twice: give one answer to each question"
            )
        seen.add(answer.question)
        if (answer.at and answer.at != question.at) or (
            answer.asked and answer.asked != question.text
        ):
            raise AnswerError(f"{question.id} is now about {question.at}: {question.text!r}, "
                              f"not the question this answer was written for")  # fmt: skip
        if not 0 <= answer.option < len(question.options):
            raise AnswerError(
                f"{question.id} has options 0 to {len(question.options) - 1}"
            )
        option = question.options[answer.option]
        edits.append(
            (question, option, answer, _sentence(option, answer, question, draft))
        )
    if any(option.kind == EditKind.NOTE for _, option, _, _ in edits):
        # A note sends the draft back to the writer: what the person kept
        # where the drafts differed is said as an answer, so the redraft holds it.
        edits = [
            _held(edit, draft) if edit[1].kind == EditKind.KEEP else edit
            for edit in edits
        ]
    _refuse_two_edits_of_one_field(edits)
    added = [sentence for _, _, _, sentence in edits if sentence]
    kept = brief.text.rstrip()
    start = brief.answers_from if brief.answers_from is not None else len(kept) + 2
    numbered = (
        number_words(kept + "\n\n" + "\n".join(added), answers_from=start)
        if added
        else brief
    )
    if (
        numbered.words[: len(brief.words)] != brief.words
    ):  # pragma: no cover - a blank line ends a sentence
        raise AnswerError("an answer would change how the brief's own words read")
    out = copy.deepcopy(dict(draft))
    replaced: list[tuple[list[int], str]] = []
    at = len(kept) + 2  # where the first added sentence begins
    for question, option, answer, sentence in edits:
        # An answer's words are those of the text it added, found by where
        # that text is: a note may hold several sentences of its own.
        said = tuple(
            w.index for w in numbered.words if at <= w.start < at + len(sentence)
        )
        if sentence:
            _one_sentence(question, option, said, numbered)
            at += len(sentence) + 1
        replaced += _apply(out, option, answer, said, brief, numbered)
    used = _all_cited(out.get("items", []))
    for words, reason in replaced:
        left = [w for w in words if w not in used]
        if left:
            out.setdefault("not_modelled", []).append({"words": left, "reason": reason})
    notes = tuple(
        sentence for _, option, _, sentence in edits if option.kind == EditKind.NOTE
    )
    # Checked with or without notes: a note sends the draft back to the
    # writer, never an answer the field can't take.
    _refuse_what_doesnt_fit(numbered, out, edits)
    return Answered(numbered, out, notes)


def _held(
    edit: tuple[Question, Option, Answer, str], draft: Mapping[str, Any]
) -> tuple[Question, Option, Answer, str]:
    """A "keep" as the typed edit that says the kept value; unchanged where the difference has no one value."""
    question, _, answer, _ = edit
    parts = [
        p.replace("~1", "/").replace("~0", "~") for p in question.at.split("/")[1:]
    ]
    if parts == ["requirements", "material"]:
        material = draft.get("requirements", {}).get("material")
        if not isinstance(material, Mapping) or not isinstance(
            material.get("text"), str
        ):
            return edit
        held = (
            Option("It is __ (name it)", EditKind.TEXT, question.at),
            replace(answer, text=material["text"]),
        )
    else:
        target = _target(parts, draft)
        if target is None or "/" + "/".join(target[0]) != question.at:
            return (
                edit  # an item that sits elsewhere, or is missing: no one value to say
            )
        node = target[1]
        if "choose" in node:
            held = (
                Option("", EditKind.CHOOSE, question.at, choice=str(node["choose"])),
                answer,
            )
        elif "count" in node:
            held = (
                Option("", EditKind.COUNT, question.at),
                replace(answer, number=float(node["count"])),
            )
        elif "through" in node:
            held = (Option("", EditKind.THROUGH, question.at), answer)
        elif "value" in node:
            unit = str(node.get("unit", "mm"))
            held = (
                Option("", EditKind.VALUE, question.at, unit=unit),
                replace(answer, number=float(node["value"]), unit=unit),
            )
        else:  # pragma: no cover - a target is a value, count, depth or choice
            return edit
    return question, held[0], held[1], _sentence(held[0], held[1], question, draft)


def _refuse_two_edits_of_one_field(
    edits: Sequence[tuple[Question, Option, Answer, str]],
) -> None:
    """Raise :class:`AnswerError` when two answers would set one field: which holds would be a guess."""
    setting: dict[str, str] = {}
    for question, option, _, _ in edits:
        if option.kind in SETS_A_FIELD:
            if option.at in setting:
                raise AnswerError(f"{setting[option.at]} and {question.id} both answer {option.at}: "
                                  "answer one of them")  # fmt: skip
            setting[option.at] = question.id


def _one_sentence(
    question: Question, option: Option, said: tuple[int, ...], brief: NumberedBrief
) -> None:
    """Raise :class:`AnswerError` when an answer that sets a field reads as more than one sentence.

    Its words are cited as one sentence of the person's; a full stop inside
    a name ("PLA. ABS") would leave part of it as a sentence of its own.
    """
    if option.kind == EditKind.NOTE or not said:
        return
    if len({brief.word(w).sentence for w in said}) > 1:
        raise AnswerError(
            f"{question.id}: give it as one sentence, with no full stop or semicolon inside it"
        )


def _refuse_what_doesnt_fit(brief: NumberedBrief, draft: dict[str, Any],
                            edits: Sequence[tuple[Question, Option, Answer, str]]) -> None:  # fmt: skip
    """Raise :class:`AnswerError` when the draft, read with the answers, faults in an item they changed.

    The whole item, not only the field: a pocket answered "circle" whose
    length and width the brief gives conflicts there, and the person, who
    chose it, is the one to say again.
    """
    report = check_draft(brief, draft)
    for question, option, _, _ in edits:
        if option.kind in (
            EditKind.NOTE,
            EditKind.KEEP,
            EditKind.NOT_MODELLED,
            EditKind.SILENT,
        ):
            continue
        at = option.at or question.at
        parts = at.split("/")
        # The item an edit changed, or the requirement.
        scope = (
            "/".join(parts[:3])
            if len(parts) >= 3 and parts[1] == "items" and parts[2].isdigit()
            else at
        )
        for problem in report.of_kind("fault"):
            if problem.at == scope or problem.at.startswith(scope + "/"):
                raise AnswerError(f"{question.id}: {problem.message}")


def _sentence(
    option: Option, answer: Answer, question: Question, draft: Mapping[str, Any]
) -> str:
    """The sentence an answer adds to the brief, or "" for one that adds none."""
    about = _about(option.at or question.at, draft)
    if option.kind in (EditKind.VALUE, EditKind.COUNT):
        number = answer.number
        if number is None or not math.isfinite(number):
            raise AnswerError(f"{question.id}: give the number")
        if option.kind == EditKind.COUNT:
            if number < 1 or not float(number).is_integer():
                raise AnswerError(
                    f"{question.id}: a count is a whole number, 1 or more"
                )
            return f"{ANSWER_PREFIXES[0]}{about}: {int(number)}."
        unit = (answer.unit or option.unit or "mm").strip()
        if not unit.isalpha():
            raise AnswerError(
                f"{question.id}: give the unit as a word: mm, cm, in, deg"
            )
        return f"{ANSWER_PREFIXES[0]}{about}: {_number(number)} {unit}."
    if option.kind == EditKind.THROUGH:
        return f"{ANSWER_PREFIXES[0]}{about}: through."
    if option.kind == EditKind.CHOOSE:
        return f"{ANSWER_PREFIXES[0]}{about}: {option.choice.replace('_', ' ')}."
    if option.kind == EditKind.TEXT:
        text = _named_text(answer)
        if not text:
            raise AnswerError(f"{question.id}: name it, in one line")
        if any(prefix.strip().lower() in text.lower() for prefix in ANSWER_PREFIXES):
            raise AnswerError(f"{question.id}: name it in your own words")
        return f"{ANSWER_PREFIXES[0]}{about}: {text}."
    if option.kind == EditKind.NOTE:
        note = one_line(answer.text, MAX_REASON)
        if note is None:
            raise AnswerError(
                f"{question.id}: write the note as one line, at most {MAX_REASON} characters"
            )
        if any(prefix.strip().lower() in note.lower() for prefix in ANSWER_PREFIXES):
            raise AnswerError(f"{question.id}: write the note in your own words, without "
                              + " or ".join(repr(p.strip()) for p in ANSWER_PREFIXES))  # fmt: skip
        return f"{ANSWER_PREFIXES[1]}{note.rstrip('.')}."
    return ""


def _named_text(answer: Answer) -> str:
    """What the person named, as one line, without the full stop that ends it: "" for nothing."""
    text = one_line(answer.text, MAX_REASON)
    # Quote marks round it are the person's way of naming it, not part of the name.
    return (
        text.rstrip(".").strip().strip("\"'\u201c\u201d\u2018\u2019").strip()
        if text is not None
        else ""
    )


def _about(at: str, draft: Mapping[str, Any]) -> str:
    """What a field is called in an answer: "/items/1/depth" of hole h is "h depth"."""
    parts = [p for p in at.split("/")[1:] if p]
    if len(parts) >= 2 and parts[0] == "items" and parts[1].isdigit():
        items = draft.get("items", [])
        n = int(parts[1])
        name = str(items[n].get("id", "item")) if n < len(items) else "item"
        return " ".join([name, *(p.replace("_", " ") for p in parts[2:])])
    if parts == ["requirements", "material"]:
        return "the material"
    return "the spec"


def _number(x: float) -> str:
    """A number as the person would write it: 0.00005, never 5e-05, which reads as no number.

    >>> _number(5e-05), _number(70.0), _number(-2.5), _number(1e16)
    ('0.00005', '70', '-2.5', '10000000000000000')
    """
    text = format(Decimal(repr(float(x))), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _apply(draft: dict[str, Any], option: Option, answer: Answer, said: tuple[int, ...],
           brief: NumberedBrief, numbered: NumberedBrief) -> list[tuple[list[int], str]]:  # fmt: skip
    """Make one answer's edit; return the brief words it replaced, with why."""
    if option.kind in SETS_A_FIELD:
        parent, key = _parent(draft, option.at)
        replaced = parent.get(key)
        if option.kind == EditKind.TEXT:
            # The words after its label ("Answer about the material: PETG"),
            # and the text exactly as the person gave it, brackets and all.
            label = f"{ANSWER_PREFIXES[0]}{_about(option.at, draft)}: "
            begins = numbered.word(said[0]).start + len(label)
            words = [w for w in said if numbered.word(w).start >= begins]
            if not words:  # pragma: no cover - the answer's sentence always names it
                raise AnswerError(f"{option.at}: name it")
            parent[key] = {"text": _named_text(answer), "from": {"words": words}}
        elif option.kind == EditKind.THROUGH:
            parent[key] = {"through": True, "from": {"words": [said[-1]]}}
        elif option.kind == EditKind.CHOOSE:
            parent[key] = {"choose": option.choice, "from": {"words": [said[-1]]}}
        elif option.kind == EditKind.COUNT:
            parent[key] = {
                "count": int(answer.number or 0),
                "from": {"words": [said[-1]]},
            }
        else:
            unit = (answer.unit or option.unit or "mm").strip()
            parent[key] = {
                "value": answer.number,
                "unit": unit,
                "from": {"words": list(said[-2:])},
            }
        words = _cited(replaced)
        reason = f"{REPLACED_BY_ANSWER} about {_about(option.at, draft)}"
        return [(words, reason)] if words else []
    if option.kind == EditKind.NOT_MODELLED:
        excused = option.words or tuple(brief.sentences[option.sentence].words)
        why = (
            "the person said it says nothing about the shape"
            if option.words
            else "the person said the part won't have it"
        )
        reason = one_line(answer.text, MAX_REASON) or why
        draft.setdefault("not_modelled", []).append(
            {"words": list(excused), "reason": reason}
        )
    elif option.kind == EditKind.SILENT:
        reason = (
            one_line(answer.text, MAX_REASON)
            or "the person said it says nothing about the shape"
        )
        draft.setdefault("silent", []).append(
            {"sentence": option.sentence, "reason": reason}
        )
        # A material it names is then another thing's ("a steel shaft"):
        # recorded as such, as a material word must be.
        words = list(brief.sentences[option.sentence].words)
        named = material_words([brief.word(w).text for w in words])
        mine = set(_cited(draft.get("requirements", {}).get("material")))
        others = [words[k] for k in sorted(named) if words[k] not in mine]
        if others:
            draft.setdefault("not_modelled", []).append(
                {"words": others, "reason": "another thing's material: the person said the sentence says nothing "
                 "about the shape"})  # fmt: skip
    return []


def _all_cited(node: Any) -> set[int]:
    """Every brief word anything in the items cites."""
    found: set[int] = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "words" and isinstance(value, list):
                found.update(w for w in value if isinstance(w, int))
            else:
                found |= _all_cited(value)
    elif isinstance(node, list):
        for value in node:
            found |= _all_cited(value)
    return found


def _cited(node: Any) -> list[int]:
    """The brief words a field cited, if it cited any."""
    source = node.get("from") if isinstance(node, Mapping) else None
    words = source.get("words") if isinstance(source, Mapping) else None
    return [w for w in words if isinstance(w, int)] if isinstance(words, list) else []


def _parent(draft: dict[str, Any], at: str) -> tuple[dict[str, Any], str]:
    """The object holding the field ``at`` points to, and the field's name.

    A requirement the draft didn't give yet ("requirements" of a draft with
    no material) is made; anything else not there can't be answered.
    """
    parts = [p.replace("~1", "/").replace("~0", "~") for p in at.split("/")[1:]]
    node: Any = draft
    for depth, key in enumerate(parts[:-1]):
        if isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        elif isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, dict) and parts[0] == "requirements" and depth == 0:
            node = node.setdefault(key, {})
        else:
            raise AnswerError(f"{at} can't be answered: the draft has no such field")
    if not isinstance(node, dict):
        raise AnswerError(f"{at} can't be answered: it is not a field")
    return node, parts[-1]
