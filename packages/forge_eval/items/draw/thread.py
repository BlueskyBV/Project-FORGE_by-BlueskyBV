"""How the generator draws for a thread: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
thread's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from forge_eval.generator import FINE, Feature, Plan, _by, _draw, _Part, _q, _thread_on
from forge_eval.items.draw.protocol import DrawKind


class Thread(DrawKind):
    key = "thread"

    def build_one(self, f: Feature, plan: Plan, part: _Part, strict: bool) -> None:
        _thread_on(f, plan, part, strict)
        return

    def own_changes(
        self, f: Feature, plan: Plan
    ) -> Iterator[tuple[str, list[Feature]]]:
        if "length" not in f.sizes:
            # The whole rod threaded: threaded part way instead.
            rod = next(g for g in plan if g.id == f.of)
            whole = rod.sizes[_draw(rod.kind).rod_length]
            yield (
                "length",
                [
                    replace(f, sizes={"length": _q(whole - d)})
                    for d in (_by(whole)[0], 2 * _by(whole)[0])
                ],
            )
        # Another pitch for the same size: fine for coarse, coarse for fine.
        size = (f.words or "").partition("x")[0]
        others = (
            [f"{size}x{FINE[size]:g}"]
            if "x" not in (f.words or "") and size in FINE
            else [size]
        )
        yield "designation", [replace(f, words=w) for w in others if w != f.words]


ENTRY = Thread()
