"""The ``oracle`` role: what the oracle makes for each kind, a module per kind (V2-stage4b-0b.md, 2 and 3).

:data:`ORACLE` holds one entry per kind, in ``KINDS``' order, each module
imported here by name.
"""

from __future__ import annotations

from forge_registry import Registry
from forge_spec.schema import KINDS

from forge_checks.items.oracle import (
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
from forge_checks.items.oracle.protocol import OracleKind

__all__ = ["ORACLE", "OracleKind"]

ORACLE: Registry[OracleKind] = Registry(
    "forge_checks.oracle",
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
    protocol=OracleKind,
)
