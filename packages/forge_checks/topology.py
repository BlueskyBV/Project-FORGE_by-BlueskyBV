"""The built part's topology and volume, against the spec's (docs/V2-stage2.md, 5.5 and 5.6).

**Topology.** The built surface must be sound: closed (no open edges), no
edge on three triangles or twice the same way, every corner's triangles one
fan, no bad triangles, no two triangles meeting where they aren't joined,
and its shells nested as their orientations say. On a sound surface it must
be as many solids as the oracle expects (one), with as many sealed voids,
and, where the oracle can say, as many through-holes. What the oracle
doesn't count (voids it couldn't settle, through-holes for now) is listed
as unchecked, with the reason, and never passed silently.

**Volume** is a cross-check, not part of the guarantee: the oracle's
interval, which holds the spec's volume whatever its shape where it is only
bounded, and the view's, which holds the built part's given how far the view
may be from it (a mesh's deflection over its area), must overlap. A view
whose volume is unbounded (a mesh that isn't sound) can't be cross-checked:
INCONCLUSIVE, which holds the part.

>>> from forge_checks.oracle import ExpectedTopology
>>> from forge_checks.view import Topology
>>> sound = Topology(shells=1, solids=1, voids=0, open_edges=0, bad_edges=0, bad_vertices=0,
...                  bad_triangles=0, self_intersections=0, misnested=0, genus=(0,))
>>> judge_topology(ExpectedTopology(1, 0, None, ()), sound).verdict
<Verdict.PASS: 'pass'>
>>> judge_volume(Interval(10.0, 11.0), Interval(12.0, 13.0)).verdict
<Verdict.FAIL: 'fail'>
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from forge_units import Interval

from .classes import Verdict
from .oracle import ExpectedTopology
from .view import Topology

__all__ = ["Finding", "TopologyCheck", "VolumeCheck", "judge_topology", "judge_volume"]

#: A sound surface has none of these.
_DEFECTS = (
    ("open_edges", "open edges (on one triangle)"),
    ("bad_edges", "edges on three triangles, or on two running the same way"),
    ("bad_vertices", "corners whose triangles don't make one fan"),
    ("bad_triangles", "triangles with a coordinate that isn't finite, a repeated corner or no area"),
    ("self_intersections", "pairs of triangles meeting where they aren't joined"),
)  # fmt: skip


@dataclass(frozen=True)
class Finding:
    """One way the built topology differs from the spec's."""

    what: str
    expected: str
    found: str


@dataclass(frozen=True)
class TopologyCheck:
    """The verdict on the built topology, what differs, and what isn't counted (with why)."""

    verdict: Verdict
    built: Topology
    expected: ExpectedTopology
    findings: tuple[Finding, ...]
    unchecked: tuple[str, ...]


@dataclass(frozen=True)
class VolumeCheck:
    """The volume cross-check: the spec's interval and the built part's."""

    verdict: Verdict
    expected: Interval
    built: Interval


def judge_topology(expected: ExpectedTopology, built: Topology) -> TopologyCheck:
    """The built topology against the oracle's: FAIL on any difference, PASS otherwise (with what isn't counted)."""
    findings: list[Finding] = []
    if built.shells == 0:
        findings.append(Finding("surface", "a closed surface", "no surface at all"))
    for name, what in _DEFECTS:
        count = getattr(built, name)
        if count:
            findings.append(Finding(what, "none", str(count)))
    if built.misnested:
        findings.append(
            Finding(
                "shells nested against their orientation", "none", str(built.misnested)
            )
        )
    unchecked = list(expected.unchecked)
    if built.solids is not None and built.solids != expected.solids:
        findings.append(Finding("solids", str(expected.solids), str(built.solids)))
    if expected.voids is None:
        if not any("void" in why for why in unchecked):
            unchecked.append("the oracle didn't count the sealed voids")
    elif built.voids is not None and built.voids != expected.voids:
        findings.append(Finding("sealed voids", str(expected.voids), str(built.voids)))
    if expected.genus is None:
        if not any("through-holes" in why for why in unchecked):
            unchecked.append("the oracle didn't count the through-holes")
    elif built.solids is not None and tuple(built.genus) != tuple(expected.genus):
        findings.append(
            Finding("through-holes", str(list(expected.genus)), str(list(built.genus)))
        )
    verdict = Verdict.FAIL if findings else Verdict.PASS
    return TopologyCheck(verdict, built, expected, tuple(findings), tuple(unchecked))


def judge_volume(expected: Interval, built: Interval) -> VolumeCheck:
    """Whether the built part's volume can be the spec's: their intervals overlap."""
    if not (math.isfinite(built.lo) and math.isfinite(built.hi)):
        return VolumeCheck(Verdict.INCONCLUSIVE, expected, built)
    verdict = Verdict.PASS if expected.overlaps(built) else Verdict.FAIL
    return VolumeCheck(verdict, expected, built)
