"""Every layout the placement solver makes in any test is checked against the definitions' own.

Importing this module turns the check on for the whole run, under any runner:
pytest loads it from tests/conftest.py, and unittest's discovery imports it
with tests/test_v2_checks_place.py, before any test runs (discovery imports
every test module first). ``ACTIVE`` says it is on.

The oracle never uses the solver's coordinates: it places every item again
(:mod:`forge_checks.place`), and at confirmation any difference holds the
part (docs/V2-stage2.md, section 5.1). Here that comparison runs on every
spec any test hands the solver, so the two placements are held to each
other on everything the tests make, not only on the specs written for it.

A spec the solver places without an issue is compared; one the spec checks
turn back for a reason the solver doesn't look at (a size of 0, a bore as
wide as its tube, a letter the font lacks) may be refused by the placement
too. Any other refusal, and any difference, fails the test that made it.
"""

from __future__ import annotations

import sys

import forge_spec.placement as _placement
from forge_checks.place import PlaceError, compare_layouts, place
from forge_spec.draft import PartSpec, Text
from forge_spec.font import missing_letters
from forge_spec.placement import Layout
from forge_spec.schema import KINDS, FieldType
from forge_spec.values import Value

_SOLVE = _placement.solve
ACTIVE = False


def _refused_by_the_spec_checks(spec: PartSpec) -> bool:
    """What forge_spec.checks turns back that the solver itself doesn't look at."""
    for item in spec.items:
        for name, value in item.fields.items():
            if (
                KINDS[item.kind].field(name).type is FieldType.LENGTH
                and isinstance(value, Value)
                and (value.nominal == 0 or value.made.nominal == 0)
                and name != "top_diameter"
            ):
                return True
            if (
                isinstance(value, Text)
                and item.kind == "text"
                and missing_letters(value.text)
            ):
                return True
        outer, inner = item.get("outer_diameter"), item.get("inner_diameter")
        if (
            isinstance(outer, Value)
            and isinstance(inner, Value)
            and inner.made_in("mm") >= outer.made_in("mm")
        ):
            return True
    return False


def _solve_and_compare(spec: PartSpec) -> Layout:
    layout = _SOLVE(spec)
    if layout.issues:
        return layout
    try:
        placed = place(spec)
    except PlaceError as exc:
        if _refused_by_the_spec_checks(spec):
            return layout
        raise AssertionError(
            f"the solver placed {spec.name!r} with no issue, but the definitions' placement refuses it: {exc}"
        ) from exc
    differences = compare_layouts(placed, layout)
    if differences:
        shown = "\n  ".join(str(d) for d in differences[:12])
        raise AssertionError(f"the two placements of {spec.name!r} differ:\n  {shown}")
    return layout


def _install() -> None:
    global ACTIVE
    if ACTIVE:
        return
    ACTIVE = True
    for module in list(sys.modules.values()):
        if getattr(module, "solve", None) is _SOLVE:
            setattr(module, "solve", _solve_and_compare)  # noqa: B010 - any module that took the solver by name
    _placement.solve = _solve_and_compare


_install()
