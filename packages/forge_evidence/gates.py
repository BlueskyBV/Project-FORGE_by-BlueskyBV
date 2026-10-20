"""Gates: checkable statements that turn a measurement into a verdict.

A gate is a comparison between something measured and something required, and
its whole job is to be un-arguable. It takes a :class:`~forge_units.Quantity`
that carries its own uncertainty, compares it three-valuedly against a
threshold, and emits an :class:`~forge_evidence.Evidence` node whose status
followed from the arithmetic rather than from anyone's judgement.

The consequence worth stating plainly: a gate cannot be talked into passing. If
the measured mass is ``[39.6, 40.3] g`` and the budget is 40 g, the comparison
is ``INDETERMINATE``, the gate is ``INCONCLUSIVE``, and the correct response is
to measure more precisely or accept a wider budget. There is no code path by
which a language model, a confident summary, or a report writer converts that
into a pass.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from forge_units import Quantity, Trivalent, all_true

from .evidence import Evidence, Method, ToolIdentity
from .status import Status, combine

Comparison = str


@dataclass(frozen=True, slots=True)
class Gate:
    """A declared acceptance criterion."""

    identifier: str
    claim: str
    comparison: Comparison
    threshold: Quantity | None = None
    upper: Quantity | None = None
    tolerance: Quantity | None = None
    requirement_id: str = ""
    critical: bool = True
    rationale: str = ""

    def evaluate(
        self,
        measured: Quantity | None,
        *,
        method: Method,
        tool: ToolIdentity,
        limitations: Sequence[str] = (),
        validity_domain: str = "",
        input_hashes: Sequence[str] = (),
        detail: Mapping[str, Any] | None = None,
        blocked_reason: str = "",
        duration_seconds: float = 0.0,
    ) -> Evidence:
        """Compare a measurement against this gate and emit evidence."""
        if blocked_reason:
            return Evidence(
                identifier=self.identifier,
                claim=self.claim,
                method=method,
                status=Status.BLOCKED,
                tool=tool,
                threshold=self._shown_threshold(),
                comparison=self.comparison,
                input_hashes=tuple(input_hashes),
                limitations=tuple(limitations) or (blocked_reason,),
                validity_domain=validity_domain,
                detail={**dict(detail or {}), "blocked_reason": blocked_reason},
                duration_seconds=duration_seconds,
            )

        if measured is None:
            return Evidence(
                identifier=self.identifier,
                claim=self.claim,
                method=method,
                status=Status.NOT_TESTED,
                tool=tool,
                threshold=self._shown_threshold(),
                comparison=self.comparison,
                limitations=tuple(limitations) or ("no measurement was taken",),
                validity_domain=validity_domain,
                detail=dict(detail or {}),
                duration_seconds=duration_seconds,
            )

        verdict = self._compare(measured)
        status = Status.from_trivalent(verdict)

        # Soft evidence may never clear a hard gate. It can raise a concern, and
        # that concern is recorded, but the gate stays untested until something
        # deterministic looks at it.
        if method.is_soft and status is Status.PASS:
            status = Status.NOT_TESTED

        annotations = list(limitations)
        if status is Status.INCONCLUSIVE:
            annotations.append(
                "the measured interval straddles the threshold; refine the "
                "measurement or widen the requirement, but do not read this as "
                "a pass"
            )

        return Evidence(
            identifier=self.identifier,
            claim=self.claim,
            method=method,
            status=status,
            tool=tool,
            result=measured,
            threshold=self._shown_threshold(),
            comparison=self.comparison,
            input_hashes=tuple(input_hashes),
            limitations=tuple(annotations),
            validity_domain=validity_domain,
            detail=dict(detail or {}),
            duration_seconds=duration_seconds,
        )

    def _shown_threshold(self) -> Quantity | None:
        """The threshold as evidence records it: for a range, the range.
        Recorded as its lower bound alone, a cross-check read "17420 mm^3
        (required in 13662.1 mm^3)" -- a range shown as one number."""
        if (self.comparison == "within" and self.threshold is not None
                and self.upper is not None):
            from forge_units import Interval

            try:
                upper = self.upper.to(self.threshold.unit)
                return Quantity(Interval(
                    float(self.threshold.magnitude.lo),
                    float(upper.magnitude.hi)), self.threshold.unit)
            except Exception:  # noqa: BLE001 - shown as it was
                return self.threshold
        return self.threshold

    def _compare(self, measured: Quantity) -> Trivalent:
        if self.comparison in ("at_least", "at_most"):
            # A limit is met by a part built exactly to it. Measured, a wall
            # drawn 2 mm comes back 2 mm less a whisker, or as an interval
            # either side of 2, and "at least 2 mm" failed or could not be
            # decided on a part built to the figure. The gate's tolerance --
            # the same one an `equals` on that figure is allowed -- is given
            # the limit too.
            threshold = self._require_threshold()
            tolerance = self.tolerance
            if tolerance is not None:
                try:
                    threshold = (threshold - tolerance
                                 if self.comparison == "at_least"
                                 else threshold + tolerance)
                except Exception:  # noqa: BLE001 - units that do not add
                    threshold = self._require_threshold()
            if self.comparison == "at_least":
                return measured.at_least(threshold)
            return measured.at_most(threshold)
        if self.comparison == "greater_than":
            return measured.greater_than(self._require_threshold())
        if self.comparison == "less_than":
            return measured.less_than(self._require_threshold())
        if self.comparison == "equals":
            tolerance = self.tolerance
            if tolerance is None:
                raise ValueError(
                    f"gate '{self.identifier}' compares for equality but "
                    "declares no tolerance. Exact equality between measured "
                    "quantities is never satisfiable, so a tolerance is "
                    "required rather than assumed."
                )
            return measured.approximately_equals(
                self._require_threshold(), tolerance=tolerance
            )
        if self.comparison == "within":
            if self.threshold is None or self.upper is None:
                raise ValueError(
                    f"gate '{self.identifier}' compares a range and needs both "
                    "a lower and an upper bound"
                )
            return measured.within(self.threshold, self.upper)
        raise ValueError(
            f"gate '{self.identifier}' declares an unknown comparison "
            f"'{self.comparison}'"
        )

    def _require_threshold(self) -> Quantity:
        if self.threshold is None:
            raise ValueError(
                f"gate '{self.identifier}' needs a threshold for comparison "
                f"'{self.comparison}'"
            )
        return self.threshold

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.identifier,
            "claim": self.claim,
            "comparison": self.comparison,
            "critical": self.critical,
        }
        if self.threshold is not None:
            payload["threshold"] = self.threshold.as_dict()
        if self.upper is not None:
            payload["upper"] = self.upper.as_dict()
        if self.tolerance is not None:
            payload["tolerance"] = self.tolerance.as_dict()
        if self.requirement_id:
            payload["requirement"] = self.requirement_id
        if self.rationale:
            payload["rationale"] = self.rationale
        return payload


@dataclass(frozen=True, slots=True)
class GateResult:
    """A gate together with the evidence that settled it."""

    gate: Gate
    evidence: Evidence

    @property
    def status(self) -> Status:
        return self.evidence.status

    def as_dict(self) -> dict[str, Any]:
        return {"gate": self.gate.as_dict(), "evidence": self.evidence.as_dict()}


def release_status(
    results: Sequence[GateResult],
    *,
    blocking_assumptions: Sequence[str] = (),
) -> tuple[Status, list[str]]:
    """Decide whether a design may be called a release candidate.

    Returns the status and the specific reasons it is not ``PASS``, because
    "blocked" without a list of what to do about it is not actionable.

    Non-critical gates are excluded from the verdict but not from the report:
    a soft requirement that failed is still surfaced, it simply does not stop a
    release on its own.
    """
    reasons: list[str] = []

    critical = [result for result in results if result.gate.critical]
    verdict = combine(result.status for result in critical)

    for result in critical:
        if result.status is Status.FAIL:
            reasons.append(f"{result.gate.identifier}: failed - {result.gate.claim}")
        elif result.status is Status.BLOCKED:
            reasons.append(f"{result.gate.identifier}: blocked - {result.gate.claim}")
        elif result.status is Status.INCONCLUSIVE:
            reasons.append(
                f"{result.gate.identifier}: inconclusive - {result.gate.claim}"
            )
        elif result.status is Status.NOT_TESTED:
            reasons.append(f"{result.gate.identifier}: not tested - {result.gate.claim}")

    if blocking_assumptions:
        verdict = Status.BLOCKED if verdict is not Status.FAIL else verdict
        reasons.extend(
            f"assumption {identifier} has not been accepted"
            for identifier in blocking_assumptions
        )

    return verdict, reasons


__all__ = ["Gate", "GateResult", "Comparison", "release_status"]
