"""The capability table: what each kind of view answers, and how it holds each kind of item (rule R6).

A part is judged on every view of it that can answer a check: the exact
B-rep, the STEP file it exports, the meshes it ships as, the second kernel's
implicit build. Which views can answer what is fixed here, in advance,
never decided by a view at run time: a view that the table says answers a
question, and fails to, holds the part; "not applicable" comes from this
table alone (plan, rule R6).

Two tables:

- :data:`QUESTIONS`, for each source and each question of the
  :class:`~.view.GeometryView` protocol: whether the view must answer it.
  A mesh has no faces or edges as curves; everything else, every view
  answers.
- :data:`HOLDS`, for each source and each item kind: whether the view's
  shape of the item is **exact** (to the view's own stated tolerance: about
  0.001 mm on the B-rep, the export's deflection on a mesh), **bounded**
  (within a tolerance the view states, as the implicit kernel's enclosure
  width), or **not applicable**. The implicit kernel builds bodies, cuts and
  standing features, and shells approximately (V1's kernel, plan 4.4), but
  not true edge roundings, threads, letters or freeform regions: its
  entries for those are not applicable, so its answers there are never
  asked for. Stage 3 proves each of its entries.

>>> answers("mesh-file", Capability.FACES), answers("brep", Capability.FACES)
(False, True)
>>> holds("implicit", "fillet").value, holds("mesh-file", "fillet").value
('not applicable', 'exact')
>>> applicable("implicit", frozenset({Capability.CLASSIFY}), ("hole", "block")).value
'bounded'
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping

from forge_spec.schema import KINDS

from .view import Capability, ViewProxy

__all__ = [
    "HOLDS",
    "QUESTIONS",
    "SOURCES",
    "Answer",
    "admit",
    "answers",
    "applicable",
    "holds",
    "required",
]


class Answer(enum.Enum):
    """How a view holds what a check asks of it."""

    EXACT = "exact"
    BOUNDED = "bounded"
    NOT_APPLICABLE = "not applicable"


#: Every kind of view a part is judged on.
SOURCES = ("brep", "step-file", "mesh-file", "implicit")

_ALL = frozenset(Capability)
_NO_CURVES = _ALL - {Capability.FACES, Capability.EDGES}

#: The questions each kind of view must answer.
QUESTIONS: Mapping[str, frozenset[Capability]] = {
    "brep": _ALL,
    "step-file": _ALL,
    "mesh-file": _NO_CURVES,
    "implicit": _NO_CURVES,
}

#: What the implicit kernel doesn't build: true roundings of edges, threads, letters, freeform regions.
_IMPLICIT_CANT = frozenset({"fillet", "chamfer", "thread", "text", "region"})

#: How each kind of view holds each kind of item.
HOLDS: Mapping[str, Mapping[str, Answer]] = {
    "brep": dict.fromkeys(KINDS, Answer.EXACT),
    "step-file": dict.fromkeys(KINDS, Answer.EXACT),
    "mesh-file": dict.fromkeys(KINDS, Answer.EXACT),
    "implicit": {
        kind: Answer.NOT_APPLICABLE if kind in _IMPLICIT_CANT else Answer.BOUNDED
        for kind in KINDS
    },
}


def _source(source: str) -> str:
    if source not in QUESTIONS:
        raise ValueError(
            f"no view comes from {source!r}: the table has {list(SOURCES)}"
        )
    return source


def answers(source: str, question: Capability) -> bool:
    """Whether a view from ``source`` must answer the question."""
    return question in QUESTIONS[_source(source)]


def required(source: str) -> frozenset[Capability]:
    """Every question a view from ``source`` must answer."""
    return QUESTIONS[_source(source)]


def holds(source: str, kind: str) -> Answer:
    """How a view from ``source`` holds an item of this kind."""
    table = HOLDS[_source(source)]
    if kind not in table:
        raise ValueError(f"no item kind {kind!r}")
    return table[kind]


def applicable(
    source: str, needs: frozenset[Capability], kinds: Iterable[str]
) -> Answer:
    """How a view from ``source`` answers a check that asks ``needs`` about items of these kinds.

    Not applicable if the view needn't answer one of the questions, or holds
    one of the items not at all; bounded if it holds one only within bounds;
    exact otherwise.
    """
    if not needs <= required(source):
        return Answer.NOT_APPLICABLE
    found = [holds(source, kind) for kind in kinds]
    if Answer.NOT_APPLICABLE in found:
        return Answer.NOT_APPLICABLE
    return Answer.BOUNDED if Answer.BOUNDED in found else Answer.EXACT


def admit(view: ViewProxy) -> tuple[str, ...]:
    """What is wrong with a view before it is asked anything: an unknown source, or a question it must answer and says it can't.

    Each of these holds the part (R6): the table, not the view, says what a
    view may leave unanswered.
    """
    if view.source not in QUESTIONS:
        return (
            f"no view comes from {view.source!r}: the capability table has {list(SOURCES)}",
        )
    missing = sorted(c.value for c in required(view.source) - view.capabilities)
    if missing:
        return (
            f"a {view.source} view must answer {', '.join(missing)}, and this one doesn't",
        )
    return ()
