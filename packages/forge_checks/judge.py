"""The judge: a built part held to its spec, on each view of it (docs/V2-stage4.md, 9.2 and 9.3; V2-plan.md, 4.5 to 4.7).

Nothing here sees how the part was made: the judge reads the confirmed spec,
places it from the definitions and makes its shape (the oracle), compiles
its checks, and looks at the part only through the views it is handed.

**Before building** (:meth:`Judge.of`): the judge's own placement, the
oracle, the check suite, the topology the oracle expects and its volume.
A spec whose shape can't be made raises :class:`~.oracle.CannotMakeError`
(the run ends CAN'T); one the definitions don't give a shape for raises
another :class:`~.oracle.OracleError` or a :class:`~.place.PlaceError` (the
part is held: what can't be made by the judge can't be judged).

**A view** (:meth:`Judge.view`) is judged alike whatever it is (the exact
B-rep, a STEP file read back, an STL or 3MF read back):

1. admitted by the capability table (:func:`~.capabilities.admit`): a view
   that says it can't answer a question its source must answer holds the
   part;
2. every check the table makes applicable to the view (its source, the
   check's needs, its item's kind), run; the rest listed, never run;
3. face accounting at the suite's resolution (its radius, finer in its
   finer boxes) and the view's own tolerance;
4. topology against the oracle's counts, and volume against its interval;
5. the brief's limits on the whole part, its mass and its size along an
   axis (schema 1.11; :mod:`.limits`);
6. fresh probes, drawn from the run's seed after the part is built, with
   one number for the view's tolerance at both ends (:func:`~.probes.draw`
   and :meth:`~.probes.Probes.run`): the greatest point tolerance face
   accounting used on it. Views of one tolerance share one draw.

Anything but PASS holds the part (:attr:`ViewJudgement.held`), with the
item, the view and the numbers. What the spec left unchecked
(:attr:`Judge.unchecked`) and what the detectors don't count
(:attr:`ViewJudgement.not_cross_checked`) are listed beside it: the first
makes a passing part VERIFIED EXCEPT, the second changes no ending.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from forge_spec.draft import PartSpec
from forge_units import Interval

from .accounting import Accounting, Tally, account_faces
from .capabilities import Answer, admit, applicable
from .checks import Evidence
from .classes import Verdict, VerificationClass
from .compiler import CheckSuite, compile_checks
from .limits import judge_limits
from .measure import Probe
from .oracle import ExpectedTopology, Oracle, oracle
from .place import Placed, place
from .probes import Probes, draw
from .topology import TopologyCheck, VolumeCheck, judge_topology, judge_volume
from .view import ViewProxy

__all__ = [
    "DETECTORS",
    "Finding",
    "Judge",
    "Unchecked",
    "ViewJudgement",
    "evidence_dict",
    "loosest",
]

#: The detectors a view is judged by, in the order a verdict lists them.
DETECTORS = (
    "capability",
    "check",
    "face accounting",
    "topology",
    "volume",
    "fresh probes",
    "requirements",
)
#: The oracle's volume is worked out to within this many cells (oracle.volume's budget).
VOLUME_BUDGET = 1_000_000
#: How the verification classes rank, the tightest first.
_CLASSES = (
    VerificationClass.EXACT,
    VerificationClass.BOUNDED,
    VerificationClass.CONSTRAINED,
)


@dataclass(frozen=True)
class Finding:
    """One reason a part is held: on which view, by which detector, about which item (None: the whole part), and why."""

    view: str
    detector: str
    item: str | None
    what: str
    verdict: Verdict
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {"view": self.view, "detector": self.detector, "item": self.item, "what": self.what,
                "verdict": self.verdict.value, "why": self.why}  # fmt: skip


@dataclass(frozen=True)
class Unchecked:
    """Something of the spec left unchecked, and why: a leaf field the checks can't hold, or an item the oracle knows only within bounds."""

    item: str
    field: str | None
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {"item": self.item, "field": self.field, "why": self.why}


def loosest(classes: list[VerificationClass]) -> VerificationClass | None:
    """The loosest of verification classes (exact < bounded < constrained); None for none."""
    return max(classes, key=_CLASSES.index) if classes else None


def evidence_dict(evidence: Evidence) -> dict[str, Any]:
    """A check's evidence, for a record."""
    measured = (
        None
        if evidence.measured is None
        else [evidence.measured.lo, evidence.measured.hi]
    )
    return {"check": evidence.check, "view": evidence.view, "verdict": evidence.verdict.value,
            "measured": measured, "reason": evidence.reason}  # fmt: skip


def _tally(tally: Tally) -> dict[str, int]:
    return {"points": tally.points, "exact": tally.exact, "bounded": tally.bounded,
            "witnessed": tally.witnessed, "missed": tally.missed, "unsure": tally.unsure}  # fmt: skip


@dataclass(frozen=True)
class ViewJudgement:
    """What judging one view found: every detector's word on it."""

    name: str
    source: str
    admitted: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    not_applicable: tuple[str, ...]
    accounting: Accounting
    topology: TopologyCheck
    volume: VolumeCheck
    probes: tuple[Evidence, ...]
    probe_seed: int
    probe_margin: float
    no_probes: tuple[tuple[str, str], ...]
    #: Each check's item, by the check's id.
    items: Mapping[str, str] = field(repr=False)
    #: The brief's limits on the whole part (schema 1.11; :mod:`.limits`), each judged on this view.
    limits: tuple[Evidence, ...] = ()

    @property
    def held(self) -> tuple[Finding, ...]:
        """Every reason this view holds the part: each detector's FAIL or INCONCLUSIVE."""
        found = [
            Finding(self.name, "capability", None, "admission", Verdict.FAIL, why)
            for why in self.admitted
        ]
        found += [Finding(self.name, "check", self.items.get(e.check), e.check, e.verdict, e.reason)
                  for e in self.evidence if e.verdict is not Verdict.PASS]  # fmt: skip
        if self.accounting.verdict is not Verdict.PASS:
            first = (self.accounting.misses or self.accounting.unsure)[:1]
            why = (f"{first[0].side} point at ({', '.join(f'{c:.4g}' for c in first[0].point)}): {first[0].why}"
                   if first else "")  # fmt: skip
            built, spec = self.accounting.built, self.accounting.spec
            found.append(Finding(self.name, "face accounting", None, "face accounting", self.accounting.verdict,
                                 f"{built.missed} built and {spec.missed} spec points missed, "
                                 f"{built.unsure} unsure; first: {why}"))  # fmt: skip
        if self.topology.verdict is not Verdict.PASS:
            why = "; ".join(
                f"{f.what}: {f.found}, not {f.expected}" for f in self.topology.findings
            )
            found.append(
                Finding(
                    self.name, "topology", None, "topology", self.topology.verdict, why
                )
            )
        if self.volume.verdict is not Verdict.PASS:
            made, expected = self.volume.built, self.volume.expected
            why = (f"built {made.lo:.6g} to {made.hi:.6g} mm³, the spec's {expected.lo:.6g} to "
                   f"{expected.hi:.6g} mm³")  # fmt: skip
            found.append(
                Finding(self.name, "volume", None, "volume", self.volume.verdict, why)
            )
        found += [Finding(self.name, "fresh probes", e.check.split("/")[0], e.check, e.verdict, e.reason)
                  for e in self.probes if e.verdict is not Verdict.PASS]  # fmt: skip
        found += [Finding(self.name, "requirements", None, e.check, e.verdict, e.reason)
                  for e in self.limits if e.verdict is not Verdict.PASS]  # fmt: skip
        return tuple(found)

    @property
    def passed(self) -> bool:
        return not self.held

    @property
    def not_cross_checked(self) -> tuple[str, ...]:
        """What the detectors don't count on this view: changes no ending, and is listed."""
        return tuple(self.topology.unchecked) + tuple(
            f"{item}: no fresh probes ({why})" for item, why in self.no_probes
        )

    def item_held(self, item: str) -> bool:
        """Whether everything of an item held on this view: its checks run here, and its fresh probes."""
        mine = [e for e in self.evidence if self.items.get(e.check) == item]
        mine += [e for e in self.probes if e.check.split("/")[0] == item]
        return all(e.verdict is Verdict.PASS for e in mine)

    def as_dict(self) -> dict[str, Any]:
        """Everything this view's judgement found, for the record."""
        a = self.accounting
        return {
            "view": self.name, "source": self.source, "admitted": list(self.admitted),
            "checks": [evidence_dict(e) for e in self.evidence],
            "not_applicable": list(self.not_applicable),
            "face_accounting": {
                "verdict": a.verdict.value, "radius": a.radius, "finest": a.finest, "tolerance": list(a.tolerance),
                "built": _tally(a.built), "spec": _tally(a.spec),
                "misses": [{"side": m.side, "point": list(m.point), "normal": list(m.normal),
                            "tolerance": m.tolerance, "why": m.why} for m in a.misses],
                "unsure": [{"side": m.side, "point": list(m.point), "why": m.why} for m in a.unsure],
            },
            "topology": {
                "verdict": self.topology.verdict.value,
                "findings": [{"what": f.what, "expected": f.expected, "found": f.found}
                             for f in self.topology.findings],
                "not_counted": list(self.topology.unchecked),
            },
            "volume": {"verdict": self.volume.verdict.value, "built": [self.volume.built.lo, self.volume.built.hi],
                       "spec": [self.volume.expected.lo, self.volume.expected.hi]},
            "fresh_probes": {"seed": self.probe_seed, "margin": self.probe_margin,
                             "items": [evidence_dict(e) for e in self.probes],
                             "none_round": [{"item": i, "why": w} for i, w in self.no_probes]},
            "limits": [evidence_dict(e) for e in self.limits],
            "held": [f.as_dict() for f in self.held],
        }  # fmt: skip


@dataclass(eq=False)
class Judge:
    """A spec's judge: its placement, its shape, its checks, and what it expects of the part as a whole."""

    spec: PartSpec
    placed: Placed
    part: Oracle
    suite: CheckSuite
    expected: ExpectedTopology
    volume: Interval
    _draws: dict[float, Probes] = field(default_factory=dict, repr=False)

    @classmethod
    def of(cls, spec: PartSpec) -> Judge:
        """The judge of a spec, made before anything is built (raises as the module's docstring says)."""
        placed = place(spec)
        part = oracle(spec, placed)
        suite = compile_checks(spec, placed, part)
        return cls(
            spec,
            placed,
            part,
            suite,
            part.expected_topology(),
            part.volume(budget=VOLUME_BUDGET),
        )

    @property
    def kinds(self) -> dict[str, str]:
        """Each item's kind, by its id."""
        return {item.id: item.kind for item in self.spec.items}

    @property
    def unchecked(self) -> tuple[Unchecked, ...]:
        """What of the spec is left unchecked: the fields no check holds, and nothing else does; the items the oracle knows only within bounds."""
        found = [
            Unchecked(n.item, n.field, n.why)
            for n in self.suite.unchecked
            if n.held_by is None
        ]
        found += [Unchecked(u.item, None, u.why) for u in self.part.unchecked]
        return tuple(found)

    @property
    def held_otherwise(self) -> tuple[Unchecked, ...]:
        """The fields with no check of their own that other checks, or face accounting, hold: checked, and listed."""
        return tuple(Unchecked(n.item, n.field, f"{n.why} (held by {n.held_by})")
                     for n in self.suite.unchecked if n.held_by is not None)  # fmt: skip

    def classes(self) -> dict[str, VerificationClass | None]:
        """Each item's verification class: the loosest of its checks' (None: it has no checks)."""
        found: dict[str, list[VerificationClass]] = {
            item.id: [] for item in self.spec.items
        }
        for check in self.suite.checks:
            found.setdefault(check.item, []).append(check.klass)
        return {item: loosest(classes) for item, classes in found.items()}

    def probes(self, seed: int, tolerance: float) -> Probes:
        """Fresh probes from ``seed`` for a view within ``tolerance`` of the part's true surface: one draw a tolerance."""
        drawn = self._draws.get(tolerance)
        if drawn is None or drawn.seed != seed:
            drawn = draw(self.part, seed, tolerance)
            self._draws[tolerance] = drawn
        return drawn

    def first_failure(self, view: ViewProxy, seed: int) -> str | None:
        """The first detector that fails a view, the cheapest first, or None where none does: what turns back a part one FAIL is enough for, a mutant (docs/V2-stage4.md, 13.2), judged no further.

        The view's admission ("admission"), then each check that applies (by
        its field), the topology, the volume, face accounting, the brief's
        limits ("requirements") and the fresh probes, each as :meth:`view`
        runs it. An INCONCLUSIVE fails nothing.
        """
        if admit(view):
            return "admission"
        kinds = self.kinds
        probe = Probe(view, self.part, self.suite.resolution)
        for check in self.suite.checks:
            kind = (kinds[check.item],) if check.item in kinds else ()
            if applicable(view.source, check.needs, kind) is Answer.NOT_APPLICABLE:
                continue
            if check.run(probe).verdict is Verdict.FAIL:
                return check.field
        if judge_topology(self.expected, view.topology()).verdict is Verdict.FAIL:
            return "topology"
        if judge_volume(self.volume, view.volume()).verdict is Verdict.FAIL:
            return "volume"
        accounting = account_faces(self.part, view, self.suite.resolution)
        if accounting.verdict is Verdict.FAIL:
            return "face accounting"
        tolerance = float(accounting.tolerance[1])
        if any(e.verdict is Verdict.FAIL for e in judge_limits(self.spec, view, "", tolerance)):
            return "requirements"
        found = self.probes(seed, tolerance).run(view, tolerance)
        if any(e.verdict is Verdict.FAIL for e in found):
            return "fresh probes"
        return None

    def view(self, view: ViewProxy, name: str, seed: int) -> ViewJudgement:
        """Judge one view of the built part (see the module's docstring): ``name`` is what the verdict calls it."""
        source = view.source
        admitted = admit(view)
        kinds = self.kinds
        probe = Probe(view, self.part, self.suite.resolution)
        evidence: list[Evidence] = []
        not_applicable: list[str] = []
        for check in self.suite.checks:
            kind = (kinds[check.item],) if check.item in kinds else ()
            if applicable(source, check.needs, kind) is Answer.NOT_APPLICABLE:
                not_applicable.append(check.id)
                continue
            evidence.append(check.run(probe))
        accounting = account_faces(self.part, view, self.suite.resolution)
        topology = judge_topology(self.expected, view.topology())
        volume = judge_volume(self.volume, view.volume())
        tolerance = float(accounting.tolerance[1])
        drawn = self.probes(seed, tolerance)
        probes = drawn.run(view, tolerance)
        items = {check.id: check.item for check in self.suite.checks}
        limits = judge_limits(self.spec, view, name, tolerance)
        return ViewJudgement(name, source, admitted, tuple(evidence), tuple(not_applicable), accounting, topology,
                             volume, probes, seed, drawn.margin, drawn.empty, items, limits)  # fmt: skip
