"""Where the judge places a shell: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item

from forge_checks.items.place.protocol import PlaceKind
from forge_checks.place import _Layout, _read_shell


class Shell(PlaceKind):
    key = "shell"

    def read(self, item: Item, layout: _Layout) -> None:
        _read_shell(item, layout)


ENTRY = Shell()
