"""What the spec checks read of a revolution: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, Profile
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.outline import Shape, turned_rims
from forge_spec.placement import Layout
from forge_spec.words import NumberedBrief

#: What a turned outline is: its half-section ("revolved from its half-section", the corpus's pulley).
_HALF_SECTION = frozenset({"half-section", "half-sections", "half-profile"})
_SECTION = frozenset({"section", "sectional", "profile", "cross-section"})


def _plain(text: str) -> str:
    return text.lower().strip(",.;:()!?\"'")


class Revolution(SpecCheckKind):
    key = "revolution"

    turned = True

    def edges_missing(
        self, target: Item, which: str, layout: Layout
    ) -> tuple[str, str] | None:
        profile = target.get("profile")
        shape = Shape.of_profile(profile) if isinstance(profile, Profile) else None
        if shape is not None:
            end = "+end" if which == "top" else "-end"
            rims = turned_rims(shape, which == "top")
            if rims is None:
                return (
                    "fault",
                    f"{target.id} has no flat {end}, so no rim there to round",
                )
            if not rims:
                return "fault", (f"{target.id}'s side runs on smoothly into its {end}: "
                                 "where they meet is no edge to round")  # fmt: skip
        return super().edges_missing(target, which, layout)


    def held_words(self, item: Item, brief: NumberedBrief) -> tuple[int, ...]:
        # A revolution's outline is its half-section: "half" there is no number of anything (the corpus's pulley).
        found = []
        for i in item.words:
            if not 0 <= i < len(brief.words):
                continue
            word = _plain(brief.word(i).text)
            after = _plain(brief.word(i + 1).text) if i + 1 < len(brief.words) else ""
            if word in _HALF_SECTION or (word == "half" and after in _SECTION):
                found.append(i)
        return tuple(found)


ENTRY = Revolution()
