"""The brief's limits on the whole part, checked on each view of it (schema 1.11; docs/V2-stage4.md, 14.7).

A limit is on the part's mass or its overall size along an axis
(:class:`forge_spec.draft.Limit`), at most or at least so much. Each is
judged on a view as its other detectors are, three ways:

- **its size** along the axis, the view's box there, known to within the
  view's tolerance (a mesh's corners lie on the surface, so its box may be
  that much short of the part's): PASS where it is within the limit all the
  way, FAIL where it is past it all the way, INCONCLUSIVE between. A part
  drawn to the limit itself ("no taller than 32 mm", 32 mm tall) is within
  it: the limit is read :data:`SLACK` loose, far below any made part's own
  tolerance.
- **its mass**, the view's volume times the material's density
  (:func:`forge_spec.materials.density`, a range over its common grades):
  a part of a printable plastic may be printed with infill, which the spec
  doesn't give, so its mass is known only to be at most its solid mass. A
  material the table has no density for, or none at all, is INCONCLUSIVE:
  said, never passed.

Anything but PASS holds the part, as every detector's does
(:attr:`forge_checks.judge.ViewJudgement.held`).
"""

from __future__ import annotations

from forge_spec.draft import Limit, PartSpec
from forge_spec.materials import density
from forge_units import Interval

from .checks import Evidence
from .classes import Verdict
from .view import ViewProxy

__all__ = ["SLACK", "judge_limits"]

#: How loose a size limit is read (mm): a part drawn to it is within it.
SLACK = 1e-3

#: Each axis's index in a box.
_AXIS = {"x": 0, "y": 1, "z": 2}


def judge_limits(spec: PartSpec, view: ViewProxy, name: str, tolerance: float) -> tuple[Evidence, ...]:
    """Each of the spec's limits on one view (``name`` what the verdict calls it), its size known to within
    ``tolerance`` (mm): see the module."""
    found = []
    for n, limit in enumerate(spec.requirements.limits):
        check = f"requirements/limits/{n}"
        if limit.of.value == "mass":
            found.append(_mass(spec, limit, view, name, check))
        else:
            found.append(_size(limit, view, name, check, tolerance))
    return tuple(found)


def _verdict(measured: Interval, limit: Limit, unit: str, slack: float) -> tuple[Verdict, str]:
    """Whether a measure known as ``measured`` (in ``unit``) is within a limit's bounds: all of it, none, or unknown."""
    verdict, said = Verdict.PASS, []
    for bound, most in ((limit.at_most, True), (limit.at_least, False)):
        if bound is None:
            continue
        value = bound.quantity.value_in(unit)
        inside = measured.hi <= value + slack if most else measured.lo >= value - slack
        outside = measured.lo > value + slack if most else measured.hi < value - slack
        said.append(f"{'at most' if most else 'at least'} {value:g} {unit}")
        if outside:
            verdict = Verdict.FAIL
        elif not inside and verdict is Verdict.PASS:
            verdict = Verdict.INCONCLUSIVE
    return verdict, " and ".join(said)


def _size(limit: Limit, view: ViewProxy, name: str, check: str, tolerance: float) -> Evidence:
    axis = _AXIS[limit.of.value]
    box = view.bounds()
    extent = box.hi[axis] - box.lo[axis]
    measured = Interval(max(extent - tolerance, 0.0), extent + 2 * tolerance)
    verdict, bounds = _verdict(measured, limit, "mm", SLACK)
    reason = (f"its size along {limit.of.value}: {extent:.6g} mm (to within {2 * tolerance:.2g} mm), the brief's "
              f"{bounds}")  # fmt: skip
    return Evidence(check, name, verdict, measured, reason)


def _mass(spec: PartSpec, limit: Limit, view: ViewProxy, name: str, check: str) -> Evidence:
    material = spec.requirements.material
    if material is None:
        return Evidence(check, name, Verdict.INCONCLUSIVE, None,
                        "its mass: the spec names no material to weigh it by")  # fmt: skip
    found = density(material.text)
    if found is None:
        return Evidence(check, name, Verdict.INCONCLUSIVE, None,
                        f"its mass: Forge has no density for {material.text!r} to weigh it by")  # fmt: skip
    volume = view.volume()  # mm³; a density in g/cm³ is a thousandth of a gram a mm³
    solid = Interval(volume.lo * found.lo / 1000.0, volume.hi * found.hi / 1000.0)
    measured = Interval(0.0, solid.hi) if found.printable else solid
    verdict, bounds = _verdict(measured, limit, "g", 0.0)
    how = (f"solid in {found.name} ({found.lo:g} to {found.hi:g} g/cm³) it weighs {solid.lo:.4g} to {solid.hi:.4g} g"
           + ("; printed, less, by its infill, which the spec doesn't give" if found.printable else ""))  # fmt: skip
    return Evidence(check, name, verdict, measured, f"its mass: {how}; the brief's {bounds}")
