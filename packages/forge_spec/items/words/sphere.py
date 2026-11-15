"""How the sentences say a sphere: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Choice, On, Place
from forge_spec.items.words._common import _c, _Line, _place, _where
from forge_spec.items.words.protocol import WordsKind


class Sphere(WordsKind):
    key = "sphere"

    def sentence(self, line: _Line) -> str:
        portion = line.get("portion")
        head = f"{line.item.id} ({_c(portion)}): Ø{line.v('diameter')}, "
        if isinstance(portion, Choice) and portion.value == "upper_half":
            return "Dome (upper half of a ball, flat side down) " + head + _where(line)
        on = line.get("on")
        if not isinstance(on, On):
            return "Ball " + head + "resting on the origin (its lowest point there)"
        place = line.get("place")
        return ("Ball " + head + f"its centre on the {on.face} face of {on.item} (half sunk into it), "
                + _place(place if isinstance(place, Place) else None))  # fmt: skip


ENTRY = Sphere()
