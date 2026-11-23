"""What the spec checks read of a sphere: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Choice, Item, PartSpec
from forge_spec.items.checks._common import Collect, size_of
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout
from forge_spec.words import NumberedBrief

#: Words after "half" that say how much of a whole ball on a face is in it, or out of it: "half sunk", "half the ball
#: sticks up".
_SUNK = frozenset({"sunk", "sink", "sinks", "sinking", "embedded", "buried", "recessed", "set", "sticks", "protrudes",
                   "proud", "showing", "exposed", "visible"})  # fmt: skip
#: How far after "half" one of them may be.
_SUNK_REACH = 4
#: A flat side or face, and a direction other than down: which way a dome sits.
_FLAT_FACE = frozenset({"side", "face", "base", "bottom"})
_NOT_DOWN = frozenset({"up", "upward", "upwards", "top", "left", "right", "sideways", "front", "back", "rear",
                       "upright", "vertical", "vertically"})  # fmt: skip


def _plain(text: str) -> str:
    return text.lower().strip(",.;:()!?\"'")


def _portion(item: Item) -> str | None:
    portion = item.get("portion")
    return portion.value if isinstance(portion, Choice) else None


class Sphere(SpecCheckKind):
    key = "sphere"

    def physical(self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect) -> None:
        # A dome standing on nothing sits flat side down: one the brief has sit another way can't be made yet (the
        # corpus's domes "sitting flat side up", "flat side to the right side"; docs/V2-gaps.md, section 10).
        if _portion(item) != "upper_half" or item.get("on") is not None:
            return
        brief = c.brief
        for s in sorted({brief.word(i).sentence for i in item.words if 0 <= i < len(brief.words)}):
            words = list(brief.sentences[s].words)
            for n, i in enumerate(words):
                if _plain(brief.word(i).text) != "flat":
                    continue
                ahead = words[n + 1 : n + 7]
                face = next((k for k, j in enumerate(ahead[:2]) if _plain(brief.word(j).text) in _FLAT_FACE), None)
                if face is None:
                    continue
                way = next((j for j in ahead[face + 1 :] if _plain(brief.word(j).text) in _NOT_DOWN), None)
                if way is not None and any(i in entry.words and way in entry.words for entry in spec.unable):
                    return  # the draft says so itself
                if way is not None:
                    said = brief.quote(tuple(range(i, way + 1)))
                    c.add("unable", at, f"Forge makes a dome flat side down only, for now: {item.id} is to sit "
                          f"{said!r}")  # fmt: skip
                    return

    def held_words(self, item: Item, brief: NumberedBrief) -> tuple[int, ...]:
        # A whole ball on a face is centred on it: half of it is sunk in, half stands out (corpus C14).
        if _portion(item) != "whole" or item.get("on") is None:
            return ()
        found = []
        for i in item.words:
            if not 0 <= i < len(brief.words) or _plain(brief.word(i).text) != "half":
                continue
            ahead = range(i + 1, min(len(brief.words), i + 1 + _SUNK_REACH))
            if any(brief.word(j).sentence == brief.word(i).sentence and _plain(brief.word(j).text) in _SUNK
                   for j in ahead):  # fmt: skip
                found.append(i)
        return tuple(found)

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        diameter = size_of(target, "diameter")
        return None if diameter is None else diameter / 2

    def edges_missing(
        self, target: Item, which: str, layout: Layout
    ) -> tuple[str, str] | None:
        if which == "bottom":
            portion = target.get("portion")
            if isinstance(portion, Choice) and portion.value == "whole":
                return "fault", f"{target.id} is a whole ball: it has no rim to round"
        return super().edges_missing(target, which, layout)


ENTRY = Sphere()
