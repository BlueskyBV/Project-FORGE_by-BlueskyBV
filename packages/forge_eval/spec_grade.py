"""Grading a drafted spec against its answer key, before anything is built (stage 1).

Stage 1's exit test reads the spec writer's drafts: of the facts the answer
keys state, how many a draft gets right before the person touches it (plan,
sections 1.3 and 8). A key says nothing about how V2 describes a part, so a
grade reads the draft's solved layout (:mod:`forge_spec.placement`), never its
wording, and each fact is graded by whoever can settle it now:

- **the spec**: how the run ends (drafted, asked or refused), the part's
  overall size, its round through holes and its sealed hollows, wherever the
  layout settles them exactly;
- **a person**: the key's facts in words, and what a good run asks about,
  read against the rendered spec and marked right or wrong (:func:`load_marks`);
- **the built part**: its volume, and whatever the layout can't settle on its
  own (a hole opening into a hollow, a cross hole in a round side, a turned
  profile's bore). Those wait for stage 4, and are never counted as right.

A key's through holes are taken as the whole list: a round through hole the
key doesn't name is a wrong fact. With no draft at all (the writer couldn't
clear its own faults), every fact is wrong: there is nothing to build.

A person's marks are tied to the draft they were made against by its digest
(:func:`draft_digest`), so a mark can never grade a different draft.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from forge_numeric import scalar as fs
from forge_spec.checks import SpecReport
from forge_spec.draft import (
    Choice,
    Faces,
    Item,
    On,
    PartSpec,
)
from forge_spec.ends import Blind, ThroughAll, ThroughEverything, UpToFace, end_of
from forge_spec.geometry import (
    EPS,
    FlatFace,
    SideFace,
    disc,
    material_at,
)
from forge_spec.placement import Instance, Layout, mm
from forge_spec.wire import to_wire

from .bounds import upper_bound
from .keys import AnswerKey, Expect, HoleFact

__all__ = [
    "MARKS_FORMAT",
    "FactGrade",
    "MarksError",
    "SetGrade",
    "SpecGrade",
    "TwoDrafts",
    "draft_digest",
    "grade_set",
    "grade_spec",
    "load_marks",
    "marks_template",
    "two_drafts",
]

MARKS_FORMAT = 1
_DIGEST = re.compile(r"[0-9a-f]{64}")

Verdict = Literal["right", "wrong", "not graded"]
Grader = Literal["spec", "person", "built part"]
Ending = Literal["drafted", "assumed", "asked", "refused", "gave up"]
Mark = Literal["right", "wrong"]

_AXES = {"x": 0, "y": 1, "z": 2}


if TYPE_CHECKING:
    from .items.grade.protocol import GradeKind


def _grade(kind: str) -> GradeKind:
    """The kind's entry in the ``grade`` registry, asked when called, never when this module is imported: the kinds' modules use this module's own vocabulary."""
    from .items.grade import GRADE

    return GRADE[kind]


class MarksError(ValueError):
    """A marks file that is malformed, or marks a fact its key doesn't state."""


@dataclass(frozen=True)
class FactGrade:
    """One fact of a key, whether the draft has it, and who said so (or will)."""

    fact: str
    verdict: Verdict
    by: Grader
    detail: str = ""


@dataclass(frozen=True)
class SpecGrade:
    """Every fact of one key, against one draft (``draft`` is "" when there was none)."""

    key: str
    expect: Expect
    ending: Ending
    draft: str
    facts: tuple[FactGrade, ...]

    def count(self, verdict: Verdict, by: Grader | None = None) -> int:
        return sum(1 for f in self.facts if f.verdict == verdict and by in (None, f.by))

    @property
    def marked(self) -> bool:
        """Nothing waits for a person's mark."""
        return self.count("not graded", "person") == 0

    @property
    def all_right(self) -> bool:
        """Marked, and no fact wrong: the part needs no edit as far as anyone can tell yet."""
        return self.marked and self.count("wrong") == 0

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "expect": self.expect, "ending": self.ending, "draft": self.draft,
                "facts": [vars(f) for f in self.facts]}  # fmt: skip


@dataclass(frozen=True)
class SetGrade:
    """A set's facts right before confirmation, with the bound stage 1's test reads."""

    grades: tuple[SpecGrade, ...]
    right: int = field(init=False)
    wrong: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "right", sum(g.count("right") for g in self.grades))
        object.__setattr__(self, "wrong", sum(g.count("wrong") for g in self.grades))

    def waiting(self, by: Grader) -> int:
        """Facts not graded yet, that ``by`` will grade."""
        return sum(g.count("not graded", by) for g in self.grades)

    @property
    def rate(self) -> float:
        """The share of graded facts the drafts got right (0 when nothing is graded)."""
        graded = self.right + self.wrong
        return self.right / graded if graded else 0.0

    def wrong_at_most(self, confidence: float = 0.95) -> float:
        """The one-sided upper bound on the share of facts a draft gets wrong (1 with none graded)."""
        if not self.right + self.wrong:
            return 1.0
        return upper_bound(self.wrong, self.right + self.wrong, confidence)

    @property
    def endings(self) -> Counter[tuple[str, str]]:
        """How many runs of each expected ending ended each way."""
        return Counter((g.expect, g.ending) for g in self.grades)

    def as_dict(self, confidence: float = 0.95) -> dict[str, Any]:
        marked = [g for g in self.grades if g.marked]
        return {
            "facts_right": self.right,
            "facts_wrong": self.wrong,
            "rate": self.rate,
            "wrong_at_most": self.wrong_at_most(confidence),
            "confidence": confidence,
            "waiting_for_a_person": self.waiting("person"),
            "waiting_for_the_built_part": self.waiting("built part"),
            "parts": len(self.grades),
            "parts_marked": len(marked),
            "parts_all_right": sum(1 for g in marked if g.all_right),
            "endings": {
                f"{e} -> {got}": n for (e, got), n in sorted(self.endings.items())
            },
        }


@dataclass(frozen=True)
class TwoDrafts:
    """How well a second draft's differences point at what the first got wrong (plan, 4.2).

    Over the briefs drafted twice and compared: of those with a fact wrong,
    how many the differences flagged (the rest were missed); of those with
    every fact marked right, how many were flagged anyway (false alarms,
    each a question the person needn't have been asked).
    """

    compared: int
    wrong: int
    caught: int
    right: int
    false_alarms: int

    def missed_at_most(self, confidence: float = 0.95) -> float:
        """The one-sided upper bound on the share of wrong drafts the differences miss (1 with none to go on)."""
        if not self.wrong:
            return 1.0
        return upper_bound(self.wrong - self.caught, self.wrong, confidence)

    def as_dict(self, confidence: float = 0.95) -> dict[str, Any]:
        return {"compared": self.compared, "wrong": self.wrong, "caught": self.caught, "right": self.right,
                "false_alarms": self.false_alarms, "missed_at_most": self.missed_at_most(confidence)}  # fmt: skip


def two_drafts(grades: Sequence[SpecGrade], flagged: Mapping[str, bool]) -> TwoDrafts:
    """The two-draft measure: ``flagged`` says, for each brief compared, whether the drafts differed."""
    compared = [g for g in grades if g.key in flagged]
    wrong = [g for g in compared if g.count("wrong")]
    right = [g for g in compared if g.all_right]
    return TwoDrafts(len(compared), len(wrong), sum(1 for g in wrong if flagged[g.key]), len(right),
                     sum(1 for g in right if flagged[g.key]))  # fmt: skip


# ----------------------------------------------------------------------
# One draft
# ----------------------------------------------------------------------
def grade_spec(key: AnswerKey, report: SpecReport | None,
               marks: Mapping[str, Mark] | None = None) -> SpecGrade:  # fmt: skip
    """Grade one draft against its key; ``report`` is ``None`` when the writer gave up.

    A report that doesn't check clean (no spec read, or a fault left in it)
    is no draft to build: it is graded as if the writer gave up, with why.
    ``marks`` are a person's marks for this draft, by fact; a mark for a fact
    the key doesn't state is refused, so a typo can't silently grade nothing.
    """
    marks = dict(marks or {})
    usable, why = _usable(report)
    ending = _ending(usable)
    facts = [_ending_fact(key, usable, ending, why, marks)]
    if key.expect != "cant":
        facts += _shape_facts(key, usable)
        facts += [_by_person(f, usable, marks) for f in key.facts]
    if key.expect == "question":
        facts += [_by_person(f"asks about: {q}", usable, marks) for q in key.questions]
    unknown = sorted(set(marks) - {f.fact for f in facts if f.by == "person"})
    if unknown and usable is not None:
        raise MarksError(f"{key.id}: marks for facts the key doesn't state: {unknown}")
    draft = (
        draft_digest(usable.spec)
        if usable is not None and usable.spec is not None
        else ""
    )
    return SpecGrade(key.id, key.expect, ending, draft, tuple(facts))


def grade_set(grades: Sequence[SpecGrade]) -> SetGrade:
    return SetGrade(tuple(grades))


def draft_digest(spec: PartSpec) -> str:
    """The SHA-256 of a draft's wire form: what a person's marks are tied to.

    The form is schema version 1.0's (``"spec_format": 1``), the one marks
    were first tied to: a later minor version names its version otherwise
    and may add fields, and a draft without them keeps its digest, so its
    marks still grade it (ADR-0026).
    """
    body = json.dumps(
        to_wire(spec, (1, 0)), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _usable(report: SpecReport | None) -> tuple[SpecReport | None, str]:
    """The report, if it is a draft that could be built; else None and why not."""
    if report is None:
        return None, "the writer couldn't clear its own faults"
    if report.spec is None or report.layout is None:
        return None, "the draft can't be read"
    faults = report.of_kind("fault")
    if faults:
        return (
            None,
            f"the draft doesn't check clean: {faults[0].at or '(the spec)'}: {faults[0].message}",
        )
    return report, ""


def _ending(report: SpecReport | None) -> Ending:
    if report is None:
        return "gave up"
    kinds = {p.kind for p in report.problems}
    if kinds & {"cant", "unable"}:
        return "refused"
    if "question" in kinds:
        return "asked"
    # Its assumptions are put to the person in the same round as questions.
    return "assumed" if report.assumptions else "drafted"


def _ending_fact(key: AnswerKey, report: SpecReport | None, ending: Ending, why: str,
                 marks: Mapping[str, Mark]) -> FactGrade:  # fmt: skip
    """How the run should end: drafted to build, put to the person first, or refused as can't be made.

    For a brief that should ask, a question settles it. A round of
    assumptions alone may or may not hold what the key asks about (centring
    a hole is no question about its depth), so that is the person's to mark.
    """
    kinds = (
        Counter(p.kind for p in report.problems)
        if report is not None
        else Counter[str]()
    )
    if report is not None and report.assumptions:
        kinds["assumption"] = len(report.assumptions)
    said = (
        why
        or ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        or "nothing to settle"
    )
    if key.expect == "cant":
        if kinds["cant"]:
            return FactGrade("it can't be made", "right", "spec", said)
        unable = "Forge said it can't model it (UNABLE), not that it can't be made"
        return FactGrade(
            "it can't be made", "wrong", "spec", unable if kinds["unable"] else said
        )
    if key.expect == "question":
        name = "it asks before building"
        if ending == "assumed":
            marked = _by_person(name, report, marks)
            if marked.verdict != "not graded":
                return marked
            return FactGrade(name, "not graded", "person",
                             f"only assumptions were put to the person ({said}): mark whether one is what the key asks")  # fmt: skip
        return FactGrade(name, "right" if ending == "asked" else "wrong", "spec", said)
    made = ending in ("drafted", "assumed", "asked")
    return FactGrade("it can be made", "right" if made else "wrong", "spec", said)


def _by_person(
    fact: str, report: SpecReport | None, marks: Mapping[str, Mark]
) -> FactGrade:
    if report is None:
        return FactGrade(fact, "wrong", "spec", "no draft")
    mark = marks.get(fact)
    if mark is None:
        return FactGrade(
            fact, "not graded", "person", "read it against the spec, and mark it"
        )
    if mark not in ("right", "wrong"):
        raise MarksError(f"a mark is right or wrong, not {mark!r}")
    return FactGrade(fact, mark, "person", "marked by a person")


# ----------------------------------------------------------------------
# What the layout settles
# ----------------------------------------------------------------------
def _shape_facts(key: AnswerKey, report: SpecReport | None) -> list[FactGrade]:
    layout = report.layout if report is not None else None
    items = report.spec.items if report is not None and report.spec is not None else ()
    facts: list[FactGrade] = []
    if key.envelope_mm is not None:
        facts.append(_envelope(key, items, layout))
    if key.through_holes:
        facts += _holes(key, items, layout)
    if key.inner_voids is not None:
        facts.append(_voids(key.inner_voids, items, layout))
    if key.volume_mm3 is not None:
        low, high = key.volume_mm3
        name = f"a volume of {low:g}-{high:g} mm\u00b3"
        facts.append(FactGrade(name, "wrong", "spec", "no draft") if layout is None
                     else FactGrade(name, "not graded", "built part", "measured on the built part"))  # fmt: skip
    return facts


def _envelope(
    key: AnswerKey, items: Sequence[Item], layout: Layout | None
) -> FactGrade:
    """The part's overall size, from the bounds of what it is made of, when nothing cut away can change them."""
    assert key.envelope_mm is not None
    name = "overall " + " x ".join(f"{x:g}" for x in key.envelope_mm) + " mm"
    if layout is None:
        return FactGrade(name, "wrong", "spec", "no draft")
    unsettled = _envelope_unsettled(items, layout)
    if unsettled:
        return FactGrade(name, "not graded", "built part", unsettled)
    extent = layout.extent()
    if extent is None:
        return FactGrade(
            name, "not graded", "built part", "the layout placed nothing to measure"
        )
    lo, hi = extent
    have = sorted(hi[k] - lo[k] for k in range(3))
    close = all(
        abs(a - b) <= key.envelope_tolerance_mm + EPS
        for a, b in zip(have, key.envelope_mm, strict=True)
    )
    shown = " x ".join(f"{x:.6g}" for x in have)
    return FactGrade(
        name, "right" if close else "wrong", "spec", f"the draft is {shown} mm"
    )


def _envelope_unsettled(items: Sequence[Item], layout: Layout) -> str:
    """Why the bounds of the bodies may not be the part's, or "" when they are.

    They aren't when the layout couldn't place everything, when a freeform
    region or raised lettering is there, or when a cut goes right through at
    a face's edge, where it can take the end off.
    """
    if layout.unplaced:
        return f"the layout couldn't place {', '.join(sorted(layout.unplaced))}: checked on the built part"
    for item in items:
        entry = _grade(item.kind)
        if entry.freeform:
            return f"{item.id} is a freeform region: checked on the built part"
        if entry.raised(item):
            return f"{item.id} is raised lettering: checked on the built part"
        if not entry.cut_out:
            continue
        reach = _reach(item, layout)
        for copy in layout.instances.get(item.id, ()):
            face = _host_face(copy, layout)
            if not isinstance(face, FlatFace):
                continue
            p1, p2 = _offset(copy, face)
            if (reach is None or _at_edge(face, p1, p2, reach)) and _through_at(
                item, copy, face, reach or 0.0
            ):
                return f"{item.id} goes through at the edge of a face: checked on the built part"
    return ""


def _reach(item: Item, layout: Layout) -> float | None:
    """How far a cut reaches from its centre at most, whatever way it turns; None if unknown."""
    return _grade(item.kind).reach(item, layout)


def _host_face(copy: Instance, layout: Layout) -> object:
    if copy.host is None:
        return None
    return layout.faces.get((copy.host[0], copy.host[1]), {}).get(copy.host[2])


def _offset(copy: Instance, face: FlatFace) -> tuple[float, float]:
    a1, a2 = (_AXES[a] for a in face.axes)
    return copy.origin[a1] - face.centre[a1], copy.origin[a2] - face.centre[a2]


def _at_edge(face: FlatFace, p1: float, p2: float, reach: float) -> bool:
    if face.shape == "rect":
        return (
            abs(p1) + reach >= face.half[0] - EPS
            or abs(p2) + reach >= face.half[1] - EPS
        )
    return fs.hypot(p1, p2) + reach >= face.half[0] - EPS


def _through_at(item: Item, copy: Instance, face: FlatFace, reach: float) -> bool:
    """Whether one copy of a cut leaves no material under any of it."""
    end = end_of(item)
    if isinstance(end, (ThroughAll, ThroughEverything)):
        return True
    if isinstance(end, Blind):
        deep = mm(end.depth)
    elif isinstance(end, UpToFace) and copy.depth is not None:  # up to a face: as deep as the solver found it goes
        deep = copy.depth
    else:
        return False
    p1, p2 = _offset(copy, face)
    # The most material anywhere within its reach (on a turned part's end, not always at the nearest point).
    most = face.most_material_under((disc(reach),), (p1, p2))
    return deep >= most - EPS


def _holes(
    key: AnswerKey, items: Sequence[Item], layout: Layout | None
) -> list[FactGrade]:
    names = [f"{h.count} round through hole(s) of {h.diameter_mm[0]:g}-{h.diameter_mm[1]:g} mm"
             for h in key.through_holes] + ["no other round through holes"]  # fmt: skip
    if layout is None:
        return [FactGrade(n, "wrong", "spec", "no draft") for n in names]
    found, unsettled = _through_holes(items, layout)
    if unsettled:
        return [FactGrade(n, "not graded", "built part", unsettled) for n in names]

    def within(d: float, h: HoleFact) -> bool:
        return h.diameter_mm[0] - EPS <= d <= h.diameter_mm[1] + EPS

    facts = []
    for name, hole in zip(names[:-1], key.through_holes, strict=True):
        have = sum(n for d, n in found.items() if within(d, hole))
        facts.append(
            FactGrade(
                name,
                "right" if have == hole.count else "wrong",
                "spec",
                f"the draft has {have}",
            )
        )
    others = sorted(
        (d, n)
        for d, n in found.items()
        if not any(within(d, h) for h in key.through_holes)
    )
    shown = ", ".join(f"{n} of {d:g} mm" for d, n in others) or "none"
    facts.append(
        FactGrade(
            names[-1],
            "wrong" if others else "right",
            "spec",
            f"others in the draft: {shown}",
        )
    )
    return facts


def _through_holes(
    items: Sequence[Item], layout: Layout
) -> tuple[dict[float, int], str]:
    """The draft's round holes right through the part, by diameter; or why the layout can't tell.

    Copies on one line through the part whose runs of material meet are one
    hole, as wide as the widest: a hole drawn down through a post and up
    through its plate is one. With air between them (a clevis's two ears)
    they are two.
    """
    kinds = [_grade(kind) for kind in {item.kind for item in items}]
    if any(k.hollows for k in kinds):
        return {}, "a hole may open into the hollow: checked on the built part"
    if any(k.freeform for k in kinds):
        return {}, "a freeform region: checked on the built part"
    if any(k.turned for k in kinds):
        return {}, "a turned profile may leave a bore: checked on the built part"
    runs: dict[
        tuple[int, float, float], list[tuple[float, float, float]]
    ] = {}  # line -> (from, to, diameter)
    # A leaning hole's line, by its direction and where it passes nearest the origin.
    slanted: dict[tuple[tuple[float, ...], tuple[float, ...]], list[tuple[float, float, float]]] = {}
    for item in items:
        copies = layout.instances.get(item.id, ())
        entry = _grade(item.kind)
        if entry.bored:
            why = entry.bore_runs(item, items, copies, runs)
            if why is not None:
                return {}, why
            continue
        diameter = entry.through_diameter(item, layout)
        if diameter is None:
            continue
        for copy in copies:
            face = _host_face(copy, layout)
            if isinstance(face, SideFace):
                return (
                    {},
                    f"{item.id} is cut into a round side: checked on the built part",
                )
            if isinstance(face, FlatFace) and copy.direction is not None:
                # Leaning on its face (tilt): through only right through (a blind one stops in the material,
                # D cos + r sin <= T); its run along its own line, from its mouth across the face's T of material.
                if isinstance(end_of(item), ThroughAll):
                    d = copy.direction
                    at = sum(copy.origin[k] * d[k] for k in range(3))
                    foot = tuple(round(copy.origin[k] - at * d[k], 4) + 0.0 for k in range(3))
                    run = face.depth_below / abs(sum(d[k] * copy.normal[k] for k in range(3)))
                    slanted.setdefault((tuple(round(x, 6) + 0.0 for x in d), foot), []).append(
                        (at - run, at, diameter)
                    )
                continue
            if isinstance(face, FlatFace) and _through_at(
                item, copy, face, diameter / 2
            ):
                k = _axis(copy)
                blind = end_of(item)
                p1, p2 = _offset(copy, face)
                deep = (
                    mm(blind.depth)
                    if isinstance(blind, Blind)
                    else copy.depth  # through everything or up to a face: as the solver found it goes
                    if copy.depth is not None
                    else material_at(face, p1, p2, 0.0)
                )
                end = copy.origin[k] - copy.normal[k] * deep
                _add_run(
                    runs,
                    copy,
                    k,
                    min(copy.origin[k], end),
                    max(copy.origin[k], end),
                    diameter,
                )
    found: Counter[float] = Counter()
    for line in [*runs.values(), *slanted.values()]:
        line.sort()
        reach, widest = line[0][1], line[0][2]
        for start, stop, diameter in line[1:]:
            if start <= reach + EPS:  # the runs meet: one hole
                reach, widest = max(reach, stop), max(widest, diameter)
                continue
            found[round(widest, 6)] += 1
            reach, widest = stop, diameter
        found[round(widest, 6)] += 1
    return dict(found), ""


def _axis(copy: Instance) -> int:
    return max(range(3), key=lambda k: abs(copy.normal[k]))


def _add_run(runs: dict[tuple[int, float, float], list[tuple[float, float, float]]], copy: Instance, axis: int,
             start: float, stop: float, diameter: float) -> None:  # fmt: skip
    across = tuple(round(copy.origin[k], 4) for k in range(3) if k != axis)
    runs.setdefault((axis, across[0], across[1]), []).append((start, stop, diameter))


def _voids(want: int, items: Sequence[Item], layout: Layout | None) -> FactGrade:
    name = f"{want} sealed hollow(s)"
    if layout is None:
        return FactGrade(name, "wrong", "spec", "no draft")
    sealed = [item for item in items if _grade(item.kind).hollows and not _open(item)]
    # A cut anywhere may reach a hollow: one down a boss on top opens it too.
    cuts = sorted(item.id for item in items if _grade(item.kind).taken)
    if sealed and cuts:
        return FactGrade(
            name, "not graded", "built part", f"{', '.join(cuts)} may open a hollow"
        )
    return FactGrade(
        name,
        "right" if len(sealed) == want else "wrong",
        "spec",
        f"the draft has {len(sealed)}",
    )


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _open(item: Item) -> bool:
    opened = item.get("open")
    return isinstance(opened, Faces) and bool(opened.faces)


def _on(item: Item) -> str:
    on = item.get("on")
    return on.item if isinstance(on, On) else ""


def _face(item: Item) -> str:
    on = item.get("on")
    return on.face if isinstance(on, On) else ""


# ----------------------------------------------------------------------
# A person's marks
# ----------------------------------------------------------------------
def marks_template(
    grades: Sequence[SpecGrade], kept: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The marks file for these grades: every fact for a person, its mark kept or left blank.

    A mark is kept only for the same draft (by digest): marks made against
    another draft of the brief are dropped, never carried over. Keys not
    graded this time, and keys whose record no longer gives a draft to mark
    (until it is looked into), keep their entries as they were.
    """
    old = dict((kept or {}).get("marks", {}))
    usable = {grade.key for grade in grades if grade.draft}
    marks: dict[str, Any] = {k: v for k, v in old.items() if k not in usable}
    for grade in grades:
        if not grade.draft:
            continue
        before = old.get(grade.key, {})
        same = before.get("draft") == grade.draft
        facts = {f.fact: (before.get("facts", {}).get(f.fact, "") if same else "")
                 for f in grade.facts if f.by == "person"}  # fmt: skip
        if facts:
            marks[grade.key] = {"draft": grade.draft, "facts": facts}
    return {
        "format": MARKS_FORMAT,
        "how": "Read each brief's spec.txt against its key, and mark each fact right or wrong.",
        "marks": marks,
    }


def load_marks(path: Path) -> dict[str, tuple[str, dict[str, Mark]]]:
    """A marks file: for each key, the draft it marks and its facts' marks (blanks left out)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MarksError(f"{path}: {error}") from error
    if (
        not isinstance(raw, dict)
        or raw.get("format") != MARKS_FORMAT
        or not isinstance(raw.get("marks"), dict)
    ):
        raise MarksError(f"{path}: not a marks file of format {MARKS_FORMAT}")
    loaded: dict[str, tuple[str, dict[str, Mark]]] = {}
    for key, entry in raw["marks"].items():
        if not (isinstance(entry, dict) and isinstance(entry.get("draft"), str)
                and _DIGEST.fullmatch(entry["draft"]) and isinstance(entry.get("facts"), dict)):  # fmt: skip
            raise MarksError(
                f"{path}: {key} needs the digest of the draft it marks, and its facts"
            )
        facts: dict[str, Mark] = {}
        for fact, mark in entry["facts"].items():
            if mark == "":
                continue
            if mark not in ("right", "wrong"):
                raise MarksError(
                    f"{path}: {key}: a mark is right, wrong or blank, not {mark!r}"
                )
            facts[str(fact)] = mark
        loaded[str(key)] = (entry["draft"], facts)
    return loaded
