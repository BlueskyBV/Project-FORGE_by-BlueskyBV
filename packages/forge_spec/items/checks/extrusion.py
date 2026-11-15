"""What the spec checks read of an extrusion: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, Profile
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.outline import Shape, corners
from forge_spec.placement import Layout


class Extrusion(SpecCheckKind):
    key = "extrusion"

    def edges_missing(
        self, target: Item, which: str, layout: Layout
    ) -> tuple[str, str] | None:
        profile = target.get("profile")
        shape = Shape.of_profile(profile) if isinstance(profile, Profile) else None
        if shape is not None and which == "vertical" and not corners(shape):
            return "fault", (f"{target.id}'s outline runs on smoothly all round, with no corners: "
                             "it has no edges along its length to round")  # fmt: skip
        return super().edges_missing(target, which, layout)


ENTRY = Extrusion()
