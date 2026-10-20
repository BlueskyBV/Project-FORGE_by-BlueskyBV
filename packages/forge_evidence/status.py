"""The six-status vocabulary, and why it cannot be shortened.

Most engineering tools report pass or fail. That forces two very different
situations into the same bucket: "we checked and it is fine" and "we could not
check". Collapsing them is how a design ships with an unverified critical
requirement that looked green.

Forge uses six statuses, and the distinctions between them are load-bearing:

``PASS``
    Evidence satisfies the gate, *within the validity domain the evidence
    declares*. A linear-static result passes a stress gate only inside the
    linear-elastic regime it assumed.

``FAIL``
    Evidence violates the gate. This is a real result and it is valuable.

``INCONCLUSIVE``
    The method ran and produced a number too uncertain to decide the question.
    This is not a failure of the design; it is a failure of the measurement, and
    it asks for refinement rather than redesign. In Forge this status is usually
    *derived*, not judged: a measured interval that straddles the threshold
    produces it automatically through three-valued comparison.

``BLOCKED``
    A required input, tool or human decision is missing. An unapproved
    high-risk assumption blocks every requirement that depends on it.

``NOT_TESTED``
    No test has been run. The default, and never silently upgraded.

``NOT_APPLICABLE``
    Excluded, with a recorded rationale. A rationale is required, because
    "not applicable" without one is indistinguishable from an oversight.

The only orderings that matter are these: ``PASS`` requires every contributing
status to be ``PASS`` or ``NOT_APPLICABLE``; a single ``FAIL`` makes the whole
``FAIL``; and neither ``INCONCLUSIVE`` nor ``NOT_TESTED`` may ever be reported
as success, no matter how confident any language model is about the design.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from forge_units import Trivalent


class Status(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"
    NOT_TESTED = "NOT_TESTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @classmethod
    def from_trivalent(cls, value: Trivalent) -> "Status":
        """Map a three-valued comparison onto a gate status.

        This is the join between the type system and the assurance vocabulary,
        and it is the reason ``INCONCLUSIVE`` is not a matter of opinion. A
        measurement whose interval straddles its threshold cannot decide the
        gate, the comparison says ``INDETERMINATE``, and the gate is
        ``INCONCLUSIVE`` -- with no human or model in the loop to round it up.
        """
        if value is Trivalent.TRUE:
            return cls.PASS
        if value is Trivalent.FALSE:
            return cls.FAIL
        return cls.INCONCLUSIVE

    @property
    def is_success(self) -> bool:
        """Strictly passing. Nothing else counts, by design."""
        return self is Status.PASS

    @property
    def is_decided(self) -> bool:
        return self in (Status.PASS, Status.FAIL, Status.NOT_APPLICABLE)

    @property
    def blocks_release(self) -> bool:
        return self is not Status.PASS and self is not Status.NOT_APPLICABLE

    @property
    def severity(self) -> int:
        """Ordering for reports: the most alarming first."""
        return {
            Status.FAIL: 0,
            Status.BLOCKED: 1,
            Status.INCONCLUSIVE: 2,
            Status.NOT_TESTED: 3,
            Status.PASS: 4,
            Status.NOT_APPLICABLE: 5,
        }[self]

    def __str__(self) -> str:
        return self.value


def combine(statuses: Iterable[Status]) -> Status:
    """Roll several gate results into one.

    The rules, in order of precedence:

    - Any ``FAIL`` makes the whole thing ``FAIL``. A known failure is the most
      informative result available and is never masked by other uncertainty.
    - Any ``BLOCKED`` then makes it ``BLOCKED``: something must be supplied
      before the question can even be asked.
    - Any ``INCONCLUSIVE`` or ``NOT_TESTED`` prevents success.
    - Otherwise ``PASS``. An empty collection is ``NOT_TESTED``, never ``PASS``:
      checking nothing is not the same as checking everything successfully.
    """
    seen = list(statuses)
    if not seen:
        return Status.NOT_TESTED
    if any(status is Status.FAIL for status in seen):
        return Status.FAIL
    if any(status is Status.BLOCKED for status in seen):
        return Status.BLOCKED
    if any(status is Status.INCONCLUSIVE for status in seen):
        return Status.INCONCLUSIVE
    if any(status is Status.NOT_TESTED for status in seen):
        return Status.NOT_TESTED
    if all(status is Status.NOT_APPLICABLE for status in seen):
        return Status.NOT_APPLICABLE
    return Status.PASS


__all__ = ["Status", "combine"]
