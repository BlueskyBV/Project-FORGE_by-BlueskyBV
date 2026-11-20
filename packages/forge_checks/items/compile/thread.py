"""What the check compiler holds for a thread: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from forge_spec.draft import EdgeSet, Item, Text
from forge_spec.values import Value

from forge_checks.classes import general
from forge_checks.items.compile._common import _RAYS, _mm
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.thread import Hand, Helix, Length, Pitch, Profile
from forge_checks.oracle import thread_pitch
from forge_checks.view import Capability

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Thread(CompileKind):
    key = "thread"
    threads = True

    def checks(self, c: CompileContext, item: Item) -> None:
        designation = item.get("designation")
        assert isinstance(designation, Text)
        body = c.spec.item(str(item.get("of")))
        c.skip(
            item, "of", "the rod threaded: its thread is checked", "its thread's check"
        )
        if body is None:
            return
        pitch = thread_pitch(designation.text)
        from forge_checks.items.compile import COMPILE

        whole = _mm(body.get(COMPILE[body.kind].rod_length))
        length = _mm(item.get("length")) if item.get("length") is not None else whole
        hand = 1 if c._choice_value(item, "hand") != "left" else -1
        radius = _mm(body.get("diameter")) / 2
        c.size(item, pitch / 2)
        for copy in c.copies(body):
            helix = Helix(
                copy.point, copy.lean or copy.direction, radius, pitch, hand, (whole - length, whole)
            )
            c.check(item, "designation", "thread", 0.0, general(helix.depth), Profile(helix), copy.index,
                       frozenset({Capability.COVERAGE}))  # fmt: skip
            c.check(item, "designation.pitch", "thread", pitch, general(pitch), Pitch(helix), copy.index,
                       frozenset({Capability.COVERAGE}))  # fmt: skip
            c.check(
                item,
                "hand",
                "thread",
                0.0,
                None,
                Hand(helix),
                copy.index,
                frozenset({Capability.COVERAGE}),
            )
            length_value = item.get("length")
            tolerance = (
                c.tol(length_value)
                if isinstance(length_value, Value)
                else general(length)
            )
            foot = _rounded_foot(c, item, body) if length >= whole - 1e-9 else 0.0
            if foot > 0:
                # All along a rod whose foot an earlier rounding or bevel rounds, the thread runs on into it and
                # stops where its teeth meet it: up to the rounding's size, and a pitch more for where on its
                # turn a tooth is, short of the rod's end (a stud bevelled at both ends, threaded all along).
                tolerance = replace(tolerance, minus=tolerance.minus + foot + pitch)
            c.check(
                item,
                "length",
                "thread",
                length,
                tolerance,
                Length(helix),
                copy.index,
                _RAYS,
            )

    implicit = False


def _rounded_foot(c: CompileContext, item: Item, body: Item) -> float:
    """How big a rounding or a bevel, before the thread in the spec, of the threaded rod's foot (its ``bottom`` edge,
    or ``both``) is: 0 where there is none."""
    found = 0.0
    for other in c.spec.items[: c.spec.items.index(item)]:
        edges = other.get("edges")
        if isinstance(edges, EdgeSet) and edges.of == body.id and edges.which in ("bottom", "both"):
            size = other.get("size") if other.get("size") is not None else other.get("radius")
            if isinstance(size, Value):
                found = max(found, _mm(size))
    return found


ENTRY = Thread()
