"""Locking a spec: the hash every later stage carries (rule R3).

A confirmed spec is the contract. Its canonical JSON (sorted keys, no
whitespace, floats as Python writes them) is hashed with SHA-256 together with
the brief it was read from, and every later stage refuses to work on a spec
whose hash doesn't match. Only a person changes a confirmed spec; any change
makes a new spec with a new hash, confirmed again.

``by`` records who confirmed it. "person" needs the one-time code Forge shows
only in its own window (rule R12), which the orchestrator checks before
calling :func:`lock`; "draft" is an unconfirmed spec, which can at best end
BUILT TO DRAFT.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .checks import SpecReport, check_draft
from .draft import PartSpec
from .ends import ThroughNext, end_of
from .placement import Assumption, Layout
from .problems import Problem
from .versions import CURRENT, Version, version_of
from .wire import to_wire
from .words import NumberedBrief, number_words

__all__ = [
    "ConfirmedSpec",
    "LockError",
    "canonical_json",
    "lock",
    "spec_digest",
    "unlock",
    "wire_digest",
]

Confirmer = Literal["person", "draft"]
_CONFIRMERS = ("person", "draft")


class LockError(ValueError):
    """A spec that can't be locked, or a locked spec that was changed."""


def canonical_json(data: Any) -> str:
    """One text for one content: sorted keys, no spaces, and 70.0 written as 70.

    >>> canonical_json({"b": [1.0, 2.5], "a": True})
    '{"a":true,"b":[1,2.5]}'
    """
    return json.dumps(
        _normal(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )  # fmt: skip


def _normal(data: Any) -> Any:
    if isinstance(data, float) and data.is_integer():
        return int(data)
    if isinstance(data, dict):
        return {key: _normal(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_normal(value) for value in data]
    return data


def spec_digest(
    spec: PartSpec,
    brief: NumberedBrief,
    by: Confirmer,
    *,
    strict: bool = False,
    version: Version = CURRENT,
) -> str:
    """The SHA-256 of the brief, the spec, who confirmed it and how strictly it was checked.

    Who confirmed it is part of the hash, so a draft can't be relabelled as
    confirmed by a person; so is ``strict``, so a spec checked under --auto
    can't be passed off as checked under the person's rules, or the reverse.
    The spec is hashed as it was shown, in its order: the same items listed
    in another order make another digest, never a false match. Where the
    person's answers begin is hashed with the brief, when it has any. The
    spec is written in the schema version it is locked in (``version``: the
    current one, or the one a spec confirmed before it was confirmed in), so
    its version is hashed too and a lock is never re-hashed (ADR-0026).
    """
    return wire_digest(to_wire(spec, version), brief, by, strict=strict)


def wire_digest(
    wire: Mapping[str, Any],
    brief: NumberedBrief,
    by: Confirmer,
    *,
    strict: bool = False,
) -> str:
    """:func:`spec_digest` of a spec's wire form, as written."""
    content: dict[str, Any] = {
        "brief": brief.text,
        "by": by,
        "strict": strict,
        "spec": dict(wire),
    }
    if brief.answers_from is not None:
        content["answers_from"] = brief.answers_from
    body = canonical_json(content)
    try:
        data = body.encode("utf-8")
    except (
        UnicodeEncodeError
    ) as exc:  # the reader refuses such text; this is a backstop
        raise LockError(
            f"the spec holds text that isn't valid Unicode: {exc}"
        ) from None
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ConfirmedSpec:
    """A spec someone approved, locked by its hash.

    Made only by :func:`lock` or :func:`unlock`, which check the spec in
    full; :meth:`check` checks it in full again, so a ConfirmedSpec built or
    altered by hand is refused wherever it is used.
    """

    spec: PartSpec
    #: The solved layout, kept private: :attr:`layout` hands out a copy, so
    #: nothing that uses it can change what was confirmed.
    _layout: Layout
    brief: NumberedBrief
    digest: str
    by: Confirmer
    assumptions: tuple[Assumption, ...]
    strict: bool = False
    #: What the person was asked to give a second look.
    caveats: tuple[Problem, ...] = ()
    #: The schema version it was confirmed in, whose form its hash is of (ADR-0026).
    version: Version = CURRENT

    @property
    def layout(self) -> Layout:
        """The layout the spec solves to: a copy, to use as you like."""
        return copy.deepcopy(self._layout)

    @property
    def edits(self) -> tuple[str, ...]:
        """What the person changed before confirming: their answers and notes, as added to the brief.

        None at all is a part drafted right first time, the plan's "parts
        needing no edit" measure (section 1.3).
        """
        return tuple(self.brief.sentence_text(s) for s in self.brief.answers)

    def check(self) -> None:
        """Refuse a spec changed since it was locked, or one that no longer checks clean.

        Everything it hands on is checked: the brief's numbering, the spec's
        hash, the checks, the assumptions and second looks shown, and the
        solved layout.
        """
        if self.by not in _CONFIRMERS:
            raise LockError("a spec is confirmed by a person, or stays a draft")
        brief = _renumbered(self.brief)
        if (
            spec_digest(
                self.spec, brief, self.by, strict=self.strict, version=self.version
            )
            != self.digest
        ):
            raise LockError("the confirmed spec was changed after it was locked")
        report = check_draft(
            brief, to_wire(self.spec, self.version), strict=self.strict
        )
        if report.problems:
            raise LockError(
                f"the checks now find {len(report.problems)} problem(s) in the locked spec"
            )
        if report.assumptions != self.assumptions or report.caveats != self.caveats:
            raise LockError(
                "the assumptions shown when it was confirmed are not the spec's"
            )
        if report.layout != self._layout:
            raise LockError("the layout handed on is not the one the spec solves to")


def _renumbered(brief: NumberedBrief) -> NumberedBrief:
    """The brief numbered afresh from its text: words handed in are never trusted."""
    fresh = number_words(brief.text, answers_from=brief.answers_from)
    if fresh != brief:
        raise LockError("the brief's words are not the numbering of its text")
    return fresh


def _clean(brief: NumberedBrief, data: dict[str, Any], strict: bool) -> SpecReport:
    report = check_draft(brief, data, strict=strict)
    if report.spec is None or report.layout is None or report.needs_redraft:
        raise LockError("the spec doesn't read cleanly")
    if report.problems:
        raise LockError(
            f"{len(report.problems)} problem(s) left: answer or fix them first"
        )
    for item in report.spec.items:
        end = end_of(item)
        if isinstance(end, ThroughNext) and end.reaches is None:
            # Item 2b's second step: the person confirms how deep it goes, which the preview finds.
            raise LockError(f"{item.id} goes through the next face: build the preview to find how deep, then confirm "
                            "it")  # fmt: skip
    return report


def lock(
    report: SpecReport, brief: NumberedBrief, *, by: Confirmer, strict: bool
) -> ConfirmedSpec:
    """Lock a checked spec. Refuses one that still has problems.

    The report is not taken on trust: the spec is checked again, in full,
    against ``brief`` (renumbered from its text), under the rules the caller
    names (``strict`` is --auto), whatever the report says.
    """
    if report.spec is None:
        raise LockError("there is no spec to lock")
    if by not in _CONFIRMERS:
        raise LockError("a spec is confirmed by a person, or stays a draft")
    if report.problems:
        raise LockError(
            f"{len(report.problems)} problem(s) left: answer or fix them first"
        )
    brief = _renumbered(brief)
    checked = _clean(brief, to_wire(report.spec), strict)
    assert checked.spec is not None and checked.layout is not None
    if (report.assumptions, report.caveats) != (checked.assumptions, checked.caveats):
        # The person confirmed what the report showed them; it must be the spec's own.
        raise LockError(
            "the assumptions shown are not the spec's: show the person its own report"
        )
    digest = spec_digest(checked.spec, brief, by, strict=strict)
    return ConfirmedSpec(checked.spec, checked.layout, brief, digest, by, checked.assumptions, strict,
                         checked.caveats)  # fmt: skip


def unlock(data: dict[str, Any], brief: NumberedBrief, digest: str, *, by: Confirmer,
           strict: bool = False) -> ConfirmedSpec:  # fmt: skip
    """Read a locked spec back from its wire form, checked again in full.

    Refuses it if the hash differs, or if this version of Forge's checks find
    a problem the version that locked it didn't: a locked spec is never used
    on trust. A spec locked in an earlier schema version is checked against
    its hash in the form it was confirmed in, then read as this version reads
    it (ADR-0026).
    """
    if by not in _CONFIRMERS:
        raise LockError("a spec is confirmed by a person, or stays a draft")
    brief = _renumbered(brief)
    report = check_draft(brief, data, strict=strict)
    if report.spec is None or report.layout is None or report.needs_redraft:
        raise LockError("the locked spec no longer reads")
    version = version_of(data)
    if spec_digest(report.spec, brief, by, strict=strict, version=version) != digest:
        raise LockError("the locked spec was changed")
    if report.problems:
        raise LockError(
            f"the checks now find {len(report.problems)} problem(s) in the locked spec"
        )
    return ConfirmedSpec(report.spec, report.layout, brief, digest, by, report.assumptions, strict,
                         report.caveats, version)  # fmt: skip
