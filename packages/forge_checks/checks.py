"""Checks and their evidence: one aspect of one item, measured on one view (docs/V2-stage2.md, 4.3 and 7).

A :class:`Check` names the item and the leaf field it checks, its kind
(:mod:`forge_checks.kinds`), its verification class, the questions it
needs a view to answer, the nominal value and its tolerance, and its
target: what to measure, placed by the judge's own placement. Run on a view
(through a :class:`~forge_checks.measure.Probe`), it gives
:class:`Evidence`: PASS, FAIL or INCONCLUSIVE, with the measurement and its
worst-case uncertainty.

- A surface the spec asks for and the built part lacks is a FAIL, not an
  INCONCLUSIVE: the part isn't what was asked.
- A measurement too uncertain for the tolerance can still pass or fail when
  its whole interval is within or outside. Otherwise it is taken again
  where it looked, with the view's coverage finer there (up to twice, each
  four times finer: a short surface's points, spread too little along it,
  fix a fit loosely), and if it is still too uncertain it is INCONCLUSIVE,
  and says the view is too coarse to judge the tolerance. So is one whose
  points fixed nothing at all (a short cone's all in one ring round it), or
  that found too few where it looked to fit (a sliver of a face left
  between other items): only if it finds too few still is the surface
  missing.
- A view that can't answer what the check needs is INCONCLUSIVE: whether it
  had to is the capability table's to say, before the check is run.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_units import Interval

from .classes import Tolerance, Verdict, VerificationClass, fine_enough, judge
from .kinds import MEASURES
from .measure import Measurement, Probe
from .view import Capability, NotAnswerableError

__all__ = ["Check", "Evidence"]

#: How many times a measurement too uncertain for its tolerance is taken again, each finer.
_AGAIN = 2


@dataclass(frozen=True)
class Evidence:
    """What one check found on one view."""

    check: str
    view: str
    verdict: Verdict
    measured: Interval | None
    reason: str


@dataclass(frozen=True)
class Check:
    """One aspect of one item: ``id`` is ``<item>/<field path>[/<copy>]``, as ``h/counterbore.depth/3``."""

    id: str
    item: str
    field: str
    kind: str
    klass: VerificationClass
    needs: frozenset[Capability]
    nominal: float
    #: None for a kind that judges itself: a count, a choice, a cut right through.
    tolerance: Tolerance | None
    target: object

    def __post_init__(self) -> None:
        if self.kind not in MEASURES:
            raise ValueError(f"{self.id}: no check kind {self.kind!r}")

    def run(self, probe: Probe) -> Evidence:
        """Measure on the probe's view, and judge (taken again finer where it looked, while too uncertain to)."""
        source = probe.view.source
        try:
            with probe.watched() as looked:
                found = MEASURES[self.kind](
                    self.target, self.nominal, self.tolerance, probe
                )
            for _ in range(_AGAIN):
                if not self._too_coarse(found):
                    break
                finer = probe.finer(looked)
                if finer is None:
                    break
                with finer.watched() as looked:
                    again = MEASURES[self.kind](
                        self.target, self.nominal, self.tolerance, finer
                    )
                if again.value is None:
                    break
                probe, found = finer, again
        except NotAnswerableError as error:
            return Evidence(
                self.id,
                source,
                Verdict.INCONCLUSIVE,
                None,
                f"the view can't answer it: {error}",
            )
        if self.tolerance is None and found.verdict is not None:
            return Evidence(self.id, source, found.verdict, found.value, found.reason)
        if found.value is None:
            # Nothing measured (nor judged, by a kind that judges itself): absent, or not to be found on this view.
            verdict = Verdict.FAIL if found.missing else Verdict.INCONCLUSIVE
            return Evidence(self.id, source, verdict, None, found.reason)
        if self.tolerance is None:
            raise AssertionError(f"{self.kind} judges itself, and gave no verdict")
        verdict = judge(found.value, self.nominal, self.tolerance)
        reason = found.reason
        uncertainty = found.value.width / 2
        if verdict is Verdict.INCONCLUSIVE and not fine_enough(
            uncertainty, self.tolerance
        ):
            reason += (
                f"; measured within ±{uncertainty:.3g}, too coarse to judge"
                f" +{self.tolerance.plus:g}/-{self.tolerance.minus:g}"
            )
        return Evidence(self.id, source, verdict, found.value, reason)

    def _too_coarse(self, found: Measurement) -> bool:
        """Whether a measurement can't judge its tolerance for its uncertainty alone, or measured nothing from the points it took (they fixed no fit, or were too few to); where it took none, nothing is taken again."""
        if self.tolerance is None:
            return False
        if found.value is None:
            return True
        return judge(
            found.value, self.nominal, self.tolerance
        ) is Verdict.INCONCLUSIVE and not fine_enough(
            found.value.width / 2, self.tolerance
        )
