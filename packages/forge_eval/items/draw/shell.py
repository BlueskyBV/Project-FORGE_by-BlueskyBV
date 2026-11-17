"""How the generator draws for a shell: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
shell's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from forge_eval.generator import OPPOSITE, Feature, Plan, _draw, _Part, _shell
from forge_eval.items.draw.protocol import DrawKind


class Shell(DrawKind):
    key = "shell"
    follows_roundings = True
    hollows = True

    def build_one(self, f: Feature, plan: Plan, part: _Part, strict: bool) -> None:
        _shell(f, plan, part)
        return

    def own_changes(
        self, f: Feature, plan: Plan
    ) -> Iterator[tuple[str, list[Feature]]]:
        # Sealed, opened on a face; opened, sealed or opened on the face across instead.
        body = next(g for g in plan if g.id == f.of)
        kind = body.kind
        now = tuple(f.faces or ())
        openings: list[tuple[str, ...]] = (
            [(o,) for o in _draw(kind).openable[-2:]]  # +z or -z; +end or -end; -end
            if not now
            else [(), *([(OPPOSITE[now[0]],)] if len(now) == 1 else [])]
        )
        if body.on is not None:  # a block standing on a face (step 5.1): sealed, or open on its far face
            openings = [()] if now else [(o,) for o in _draw(kind).openable]
        yield "open", [replace(f, faces=o) for o in openings]


ENTRY = Shell()
