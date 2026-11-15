"""The ``words`` role: how the sentences say for each kind, a module per kind (V2-stage4b-0b.md, 2 and 3).

:data:`WORDS` holds one entry per kind, in ``KINDS``' order, each module
imported here by name.
"""

from __future__ import annotations

from forge_registry import Registry

from forge_spec.items.words import (
    block,
    boss,
    chamfer,
    cone,
    cylinder,
    extrusion,
    fillet,
    hole,
    pocket,
    post,
    region,
    revolution,
    rib,
    shell,
    slot,
    sphere,
    tab,
    text,
    thread,
    tube,
)
from forge_spec.items.words.protocol import WordsKind
from forge_spec.schema import KINDS

__all__ = ["WORDS", "WordsKind"]

WORDS: Registry[WordsKind] = Registry(
    "forge_spec.words",
    KINDS,
    [
        block.ENTRY,
        cylinder.ENTRY,
        tube.ENTRY,
        sphere.ENTRY,
        cone.ENTRY,
        extrusion.ENTRY,
        revolution.ENTRY,
        hole.ENTRY,
        slot.ENTRY,
        pocket.ENTRY,
        boss.ENTRY,
        post.ENTRY,
        tab.ENTRY,
        rib.ENTRY,
        fillet.ENTRY,
        chamfer.ENTRY,
        shell.ENTRY,
        text.ENTRY,
        thread.ENTRY,
        region.ENTRY,
    ],
    protocol=WordsKind,
)
