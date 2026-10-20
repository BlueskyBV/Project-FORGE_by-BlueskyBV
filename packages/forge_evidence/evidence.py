"""The evidence graph: immutable records of what was measured and how.

Every claim Forge makes about a design points at an evidence node, and every
evidence node records enough to reproduce itself: the method, the tool and its
version, the hashes of its inputs, the numeric result *with its uncertainty*,
the validity domain, and what it does not cover.

Three rules govern this structure.

**Evidence is immutable.** A new run creates a new node. Nothing is overwritten,
so a design's history includes the results that were superseded and the ones
that failed. That is what makes a report auditable rather than merely current --
and it makes the tempting move of quietly re-running a failing check until it
passes visible instead of invisible.

**Evidence carries its limitations.** A node that says "peak von Mises 180 MPa"
without saying "linear static, single load case, unconverged mesh, stress
singularity at the re-entrant corner not excluded" is worse than no evidence,
because it invites a conclusion it cannot support. ``limitations`` is a required
field on every node produced by a numerical method.

**A language model may not create evidence.** It can propose that a gate should
exist, explain what a result means, or draft the prose around it. The numeric
``result`` field is written only by deterministic code. The ``method`` field
records which, and ``VISUAL_REVIEW`` results are explicitly soft: they can
request new deterministic checks but can never pass a failed one.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from forge_units import Quantity, Trivalent

from .status import Status, combine


class Method(Enum):
    """How a piece of evidence was obtained.

    Ordered loosely by the weight it can bear. ``EXACT_GEOMETRY`` measures the
    model itself; ``PHYSICAL_TEST`` measures reality and outranks everything.
    ``VISUAL_REVIEW`` is deliberately listed as soft evidence.
    """

    EXACT_GEOMETRY = "exact_geometry"
    ANALYTICAL = "analytical"
    NUMERICAL_SIMULATION = "numerical_simulation"
    SAMPLING = "sampling"
    CROSS_BACKEND = "cross_backend"
    VISUAL_REVIEW = "visual_review"
    USER_CONFIRMATION = "user_confirmation"
    PHYSICAL_TEST = "physical_test"
    EXTERNAL_CERTIFICATION = "external_certification"

    @property
    def is_soft(self) -> bool:
        """Soft evidence can raise a concern but can never clear a hard gate."""
        return self in (Method.VISUAL_REVIEW, Method.USER_CONFIRMATION)


@dataclass(frozen=True, slots=True)
class ToolIdentity:
    """What produced a result, precisely enough to reproduce it."""

    name: str
    version: str
    configuration: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "configuration": dict(self.configuration),
        }


@dataclass(frozen=True, slots=True)
class Evidence:
    """One immutable observation about a design."""

    identifier: str
    claim: str
    method: Method
    status: Status
    tool: ToolIdentity
    result: Quantity | None = None
    threshold: Quantity | None = None
    comparison: str = ""
    input_hashes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    validity_domain: str = ""
    parents: tuple[str, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if (
            self.method
            in (Method.NUMERICAL_SIMULATION, Method.SAMPLING, Method.ANALYTICAL)
            and not self.limitations
        ):
            raise ValueError(
                f"evidence '{self.identifier}' uses method {self.method.value} "
                "and must declare its limitations; a computed number without "
                "its validity domain invites a conclusion it cannot support"
            )

    @property
    def content_hash(self) -> str:
        """Hash of the evidence's substance, excluding its timestamp.

        Two runs that observed the same thing with the same tools hash the same,
        which is how a reproducibility check distinguishes "re-ran and got the
        same answer" from "re-ran and something moved".
        """
        payload = {
            "claim": self.claim,
            "method": self.method.value,
            "status": self.status.value,
            "tool": self.tool.as_dict(),
            "result": self.result.as_dict() if self.result else None,
            "threshold": self.threshold.as_dict() if self.threshold else None,
            "comparison": self.comparison,
            "inputs": list(self.input_hashes),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode(), digest_size=16).hexdigest()

    @property
    def is_soft(self) -> bool:
        return self.method.is_soft

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.identifier,
            "claim": self.claim,
            "method": self.method.value,
            "status": self.status.value,
            "tool": self.tool.as_dict(),
            "created_at": self.created_at,
            "duration_s": round(self.duration_seconds, 6),
        }
        if self.result is not None:
            payload["result"] = self.result.as_dict()
            payload["result_rendered"] = str(self.result)
        if self.threshold is not None:
            payload["threshold"] = self.threshold.as_dict()
            payload["threshold_rendered"] = str(self.threshold)
        if self.comparison:
            payload["comparison"] = self.comparison
        if self.input_hashes:
            payload["input_hashes"] = list(self.input_hashes)
        if self.limitations:
            payload["limitations"] = list(self.limitations)
        if self.validity_domain:
            payload["validity_domain"] = self.validity_domain
        if self.parents:
            payload["parents"] = list(self.parents)
        if self.detail:
            payload["detail"] = dict(self.detail)
        payload["content_hash"] = self.content_hash
        return payload

    def render(self) -> str:
        """One line, suitable for a terminal summary."""
        parts = [f"{self.status.value:<14} {self.claim}"]
        if self.result is not None:
            parts.append(f"= {self.result}")
            if self.threshold is not None and self.comparison:
                symbol = {
                    "at_least": ">=",
                    "at_most": "<=",
                    "equals": "==",
                    "within": "in",
                }.get(self.comparison, self.comparison)
                parts.append(f"(required {symbol} {self.threshold})")
        return "  ".join(parts)


class EvidenceGraph:
    """An append-only collection of evidence.

    Append-only is enforced rather than encouraged: :meth:`add` refuses to
    replace an existing identifier. Superseding a result means adding a new node
    that names the old one as its parent, which keeps the history intact.
    """

    __slots__ = ("_nodes", "_order")

    def __init__(self) -> None:
        self._nodes: dict[str, Evidence] = {}
        self._order: list[str] = []

    def add(self, evidence: Evidence) -> Evidence:
        if evidence.identifier in self._nodes:
            raise ValueError(
                f"evidence '{evidence.identifier}' already exists; evidence is "
                "immutable. Add a new node naming this one as its parent "
                "instead of overwriting it."
            )
        self._nodes[evidence.identifier] = evidence
        self._order.append(evidence.identifier)
        return evidence

    def extend(self, items: Sequence[Evidence]) -> None:
        for item in items:
            self.add(item)

    def __len__(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[Evidence]:
        return (self._nodes[identifier] for identifier in self._order)

    def __getitem__(self, identifier: str) -> Evidence:
        return self._nodes[identifier]

    def __contains__(self, identifier: str) -> bool:
        return identifier in self._nodes

    def for_claim(self, claim: str) -> tuple[Evidence, ...]:
        return tuple(node for node in self if node.claim == claim)

    def by_status(self, status: Status) -> tuple[Evidence, ...]:
        return tuple(node for node in self if node.status is status)

    def failures(self) -> tuple[Evidence, ...]:
        return self.by_status(Status.FAIL)

    def unresolved(self) -> tuple[Evidence, ...]:
        """Everything that is neither a pass nor a deliberate exclusion."""
        return tuple(node for node in self if node.status.blocks_release)

    def overall_status(self) -> Status:
        """The design's status, computed only from hard evidence.

        Soft evidence is excluded from the roll-up entirely. A vision model's
        opinion that the part "looks correct" must not be able to influence a
        release decision in either direction; it can only prompt a deterministic
        check to be run.
        """
        return combine(node.status for node in self if not node.is_soft)

    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for node in self:
            counts[node.status.value] += 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status().value,
            "summary": self.summary(),
            "evidence": [node.as_dict() for node in self],
        }

    def render(self) -> str:
        # Labelled "Evidence", not "Overall": this is the roll-up of the checks
        # that ran, which is a weaker claim than the release verdict printed
        # above it. Two lines both saying "overall" and disagreeing -- every
        # gate PASS, release BLOCKED -- is how a reader takes away the wrong one.
        lines = [
            f"Evidence: {self.overall_status().value} "
            f"({len(self._order)} claims)",
            "",
        ]
        ordered = sorted(self, key=lambda node: (node.status.severity, node.claim))
        for node in ordered:
            lines.append(f"  {node.render()}")
            # A check that knows what went wrong says so here, under its own
            # line. "FAIL  every through hole is open  = 1  (required <= 0)" is
            # a true sentence that sends the reader to the JSON to find out
            # which hole, and most readers stop at this file.
            if node.status is Status.PASS:
                continue
            hint = node.detail.get("hint")
            if isinstance(hint, str) and hint.strip():
                lines.extend(
                    textwrap.wrap(
                        hint.strip(),
                        width=78,
                        initial_indent="      -> ",
                        subsequent_indent="         ",
                    )
                )
        return "\n".join(lines)


__all__ = ["Evidence", "EvidenceGraph", "Method", "ToolIdentity"]
