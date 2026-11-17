"""What the check compiler holds for a thread: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item, Text
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


ENTRY = Thread()
