"""Fresh probes: points round every copy of every item, drawn after the part is built, from a recorded seed (docs/V2-plan.md, 4.5).

Every other check is known before the part is built, and a designer shown
them could fit them and miss the rest. These points are drawn only once the
part is built, from a seed the run records (so the draw can be replayed),
and nothing could have been fitted to them.

**Drawing** (:func:`draw`). For each step of the spec's shape (each copy of
each item, its solid added or taken away, :mod:`forge_checks.oracle`),
points are drawn at random in the box round its solid, grown by the
margin, and kept where the spec's shape is sure of their side by the
margin: inside what the part must hold (its inner form) or outside all it
may hold (its outer form) by at least ``margin``, by the oracle's bound
(:meth:`~forge_checks.oracle.Oracle.bound`). So no point is within the
margin of the part's surface, nor where the shape is only bounded (a
rounding's zone, a thread's flanks). Up to ``each`` are kept inside and
``each`` outside, spread over the box (each the farthest from those already
kept); an item too small or too buried to hold any is named, with the
reason.

**Judging** (:meth:`Probes.run`). The built part must put every point on
the same side: its view classifies them. Per item, the probes FAIL where any
point lands on the other side (or on the built surface), naming the first
few; they are INCONCLUSIVE where the view can't tell; else they PASS. The
margin is at least the view's tolerance four times over (and
:data:`LEAST`), so a part that is what was asked passes them all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from forge_numeric import vector as fv
from numpy.typing import NDArray

from .checks import Evidence
from .classes import Verdict
from .oracle import INNER, OUTER, Oracle
from .view import NotAnswerableError, Side, ViewProxy

__all__ = ["EACH", "LEAST", "Probes", "draw"]

Array = NDArray[np.float64]

#: How many points each copy of each item gets, at most, on each side.
EACH = 24
#: The margin is never less than this (mm): a point this far from the spec's surface is on its side.
LEAST = 0.01
#: How many candidates are drawn round each copy, at most, to find them.
_TRIES = 4096
#: How many wrong points a failing item names.
_SHOWN = 3


@dataclass(frozen=True, eq=False)
class Probes:
    """Fresh probes, drawn from ``seed`` at ``margin`` from the spec's surface: each point, its item and copy, and whether the spec has it inside.

    ``empty`` names the items no point could be drawn round, and why: they
    have no fresh probes (face accounting and their checks still judge
    them), and the report says so.
    """

    seed: int
    margin: float
    points: Array
    inside: NDArray[np.bool_]
    items: tuple[str, ...]
    copies: NDArray[np.int64]
    empty: tuple[tuple[str, str], ...]

    def __len__(self) -> int:
        return len(self.points)

    def _show(self, k: int) -> str:
        where = ", ".join(f"{v:.4g}" for v in self.points[k])
        side = "inside" if self.inside[k] else "outside"
        return f"{side} expected at ({where}), copy {int(self.copies[k]) + 1}"

    def run(self, view: ViewProxy, tolerance: float) -> tuple[Evidence, ...]:
        """Each probed item's verdict on the built part: its view, which is within ``tolerance`` of the part's true surface."""
        if not (math.isfinite(tolerance) and tolerance >= 0):
            raise ValueError(f"a view's tolerance is a size, not {tolerance}")
        source = view.source
        names = sorted(set(self.items))
        if 4 * tolerance > self.margin:
            why = (
                f"drawn {self.margin:g} mm from the spec's surface, closer than four"
                f" times the view's tolerance ({tolerance:g} mm)"
            )
            return tuple(
                Evidence(f"{n}/fresh", source, Verdict.INCONCLUSIVE, None, why)
                for n in names
            )
        try:
            sides = np.asarray(view.classify(self.points)) if len(self) else np.zeros(0)
        except NotAnswerableError as error:
            why = f"the view can't answer it: {error}"
            return tuple(
                Evidence(f"{n}/fresh", source, Verdict.INCONCLUSIVE, None, why)
                for n in names
            )
        expected = np.where(self.inside, Side.IN, Side.OUT)
        unknown = sides == Side.UNKNOWN
        wrong = ~unknown & (sides != expected)
        items = np.asarray(self.items, dtype=object)
        found: list[Evidence] = []
        for name in names:
            mine = items == name
            count = int(mine.sum())
            bad = np.flatnonzero(mine & wrong)
            unsure = int(np.sum(mine & unknown))
            drawn = f"fresh probes (seed {self.seed})"
            if len(bad):
                shown = "; ".join(self._show(k) for k in bad[:_SHOWN])
                verdict = Verdict.FAIL
                why = f"{len(bad)} of {count} {drawn} on the wrong side: {shown}"
            elif unsure:
                verdict = Verdict.INCONCLUSIVE
                why = f"the view can't tell the side of {unsure} of {count} {drawn}"
            else:
                verdict, why = Verdict.PASS, f"all {count} {drawn} on their side"
            found.append(Evidence(f"{name}/fresh", source, verdict, None, why))
        return tuple(found)


def draw(
    part: Oracle, seed: int, tolerance: float, *, each: int = EACH, tries: int = _TRIES
) -> Probes:
    """Fresh probes round every copy of every item of the spec's shape, from ``seed``, for a view within ``tolerance`` of the part's true surface (see the module's docstring)."""
    if not (math.isfinite(tolerance) and tolerance >= 0):
        raise ValueError(f"a view's tolerance is a size, not {tolerance}")
    if each < 1 or tries < 1:
        raise ValueError("fresh probes need some points and some tries")
    margin = max(4 * tolerance, LEAST)
    rng = np.random.default_rng(seed)
    points: list[Array] = []
    inside: list[NDArray[np.bool_]] = []
    items: list[str] = []
    copies: list[NDArray[np.int64]] = []
    empty: dict[str, str] = {}
    drawn: set[str] = set()
    for step in part.steps:
        lo = np.asarray(step.lo, dtype=np.float64) - 2 * margin
        hi = np.asarray(step.hi, dtype=np.float64) + 2 * margin
        candidates = rng.uniform(lo, hi, size=(tries, 3))
        sure_in = part.bound(candidates, INNER, margin) <= -margin
        sure_out = part.bound(candidates, OUTER, margin) >= margin
        kept_in = _spread(candidates[sure_in], each)
        kept_out = _spread(candidates[sure_out], each)
        found = len(kept_in) + len(kept_out)
        if not found:
            if step.item not in drawn:
                empty.setdefault(
                    step.item,
                    f"nothing round it is {margin:g} mm clear of the spec's surface",
                )
            continue
        drawn.add(step.item)
        empty.pop(step.item, None)
        for kept, side in ((kept_in, True), (kept_out, False)):
            points.append(kept)
            inside.append(np.full(len(kept), side))
            items += [step.item] * len(kept)
            copies.append(np.full(len(kept), step.copy, dtype=np.int64))
    return Probes(
        seed,
        margin,
        np.concatenate(points) if points else np.zeros((0, 3)),
        np.concatenate(inside) if inside else np.zeros(0, dtype=bool),
        tuple(items),
        np.concatenate(copies) if copies else np.zeros(0, dtype=np.int64),
        tuple(sorted(empty.items())),
    )


def _spread(points: Array, keep: int) -> Array:
    """Up to ``keep`` of the points, each the farthest from those already kept (the first, the first drawn)."""
    if len(points) <= keep:
        return points
    chosen = [0]
    gap = fv.norm(points - points[0], axis=1)
    for _ in range(keep - 1):
        k = int(np.argmax(gap))
        chosen.append(k)
        gap = np.minimum(gap, fv.norm(points - points[k], axis=1))
    return np.asarray(points[np.asarray(chosen)], dtype=np.float64)
