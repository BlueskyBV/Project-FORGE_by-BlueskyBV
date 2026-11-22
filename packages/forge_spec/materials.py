"""What a part's material weighs: densities, for a limit on its mass (schema 1.11; docs/V2-stage4.md, 14.7).

A spec's material is the brief's words for it, exactly ("6061-T6
aluminium", "PETG"): :func:`density` reads the material those words name and
gives its density as a range, wide enough for every common grade of it
(aluminium alloys from 2.63 to 2.85 g/cm³), so that a part's mass, its
volume times the density, is an interval the part's true mass is in.

A part of a plastic that is printed weighs what its infill leaves, which
the spec doesn't say: such a material is **printable**, and its part's mass
is known only to be at most what it would weigh solid. A filled material
(carbon or glass fibre in it), a blend, wood (from 0.3 to 1 g/cm³), or a
name the table doesn't hold has no density here: a limit on its mass can't be checked, and is said so.

Sources: the materials' published data sheets' ranges (MatWeb's typical
values for each family; the filament makers' for printed plastics).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Density", "density"]


@dataclass(frozen=True)
class Density:
    """A material's density (g/cm³) as a range, what the table calls it, and whether its parts may be printed with
    infill (their mass then known only to be at most the solid's)."""

    lo: float
    hi: float
    name: str
    printable: bool


#: Each material's words, its density range (g/cm³), what it is called, and whether it is printable. The first whose
#: word the material's text holds is it, so a more particular name comes first ("stainless" before "steel").
_TABLE: tuple[tuple[frozenset[str], float, float, str, bool], ...] = (
    (frozenset({"stainless"}), 7.70, 8.05, "stainless steel", False),
    (frozenset({"steel"}), 7.75, 8.05, "steel", False),
    (frozenset({"aluminium", "aluminum"}), 2.63, 2.85, "aluminium", False),
    (frozenset({"brass"}), 8.40, 8.75, "brass", False),
    (frozenset({"bronze"}), 7.40, 8.90, "bronze", False),
    (frozenset({"copper"}), 8.89, 8.96, "copper", False),
    (frozenset({"titanium"}), 4.40, 4.55, "titanium", False),
    (frozenset({"iron"}), 6.80, 7.90, "iron", False),
    (frozenset({"zinc"}), 6.60, 7.20, "zinc", False),
    (frozenset({"nickel"}), 8.80, 8.91, "nickel", False),
    (frozenset({"magnesium"}), 1.74, 1.84, "magnesium", False),
    (frozenset({"pla"}), 1.21, 1.26, "PLA", True),
    (frozenset({"petg"}), 1.23, 1.29, "PETG", True),
    (frozenset({"pctg"}), 1.23, 1.27, "PCTG", True),
    (frozenset({"abs"}), 1.03, 1.08, "ABS", True),
    (frozenset({"asa"}), 1.05, 1.10, "ASA", True),
    (frozenset({"tpu"}), 1.10, 1.25, "TPU", True),
    (frozenset({"hips"}), 1.03, 1.06, "HIPS", True),
    (frozenset({"nylon", "pa", "pa6", "pa12"}), 1.01, 1.15, "nylon", True),
    (frozenset({"pc", "polycarbonate"}), 1.19, 1.22, "polycarbonate", True),
    (frozenset({"pom", "acetal", "delrin"}), 1.39, 1.43, "acetal", True),
    (frozenset({"pp", "polypropylene"}), 0.89, 0.92, "polypropylene", True),
    (frozenset({"hdpe"}), 0.93, 0.97, "HDPE", True),
    (frozenset({"ldpe"}), 0.91, 0.94, "LDPE", True),
    (frozenset({"uhmw", "uhmwpe"}), 0.93, 0.95, "UHMW-PE", False),
    (frozenset({"peek"}), 1.30, 1.32, "PEEK", True),
    (frozenset({"pei", "ultem"}), 1.27, 1.30, "PEI", True),
    (frozenset({"pvc"}), 1.30, 1.45, "PVC", False),
    (frozenset({"acrylic", "pmma", "perspex", "plexiglass", "plexiglas"}), 1.17, 1.20, "acrylic", False),
    (frozenset({"ptfe", "teflon"}), 2.13, 2.20, "PTFE", False),
    (frozenset({"resin"}), 1.05, 1.25, "resin", True),
)

#: Words that say a material is filled or a blend, or one whose density ranges too widely to judge a mass by (wood):
#: its density isn't one of the table's.
_FILLED = frozenset({"cf", "gf", "filled", "carbon", "glass", "fibre", "fiber", "composite", "blend", "wood"})


def density(material: str) -> Density | None:
    """The density of the material a spec's text names, or None where the table has none for it.

    >>> density("6061-T6 aluminium")
    Density(lo=2.63, hi=2.85, name='aluminium', printable=False)
    >>> density("stainless steel").name, density("PLA").printable
    ('stainless steel', True)
    >>> density("PETG-CF") is None, density("unobtainium") is None
    (True, True)
    """
    words = re.sub(r"[^0-9a-z]+", " ", material.lower()).split()
    if set(words) & _FILLED:
        return None
    for names, lo, hi, name, printable in _TABLE:
        if names & set(words):
            return Density(lo, hi, name, printable)
    return None
