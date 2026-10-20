# ADR-0008: Six statuses, and `INCONCLUSIVE` is computed rather than judged

**Status:** Accepted · **Date:** 2026-09-11

## Context

Pass/fail forces two very different situations into one bucket: "we checked and
it is fine" and "we could not check". Collapsing them is how a design ships with
an unverified critical requirement that looked green on a dashboard.

## Decision

Six statuses: `PASS`, `FAIL`, `INCONCLUSIVE`, `BLOCKED`, `NOT_TESTED`,
`NOT_APPLICABLE`. The distinctions are load-bearing and are documented at
`forge_evidence.status`.

The part that makes this more than a vocabulary: **`INCONCLUSIVE` is derived from
arithmetic, not decided by anyone.** Quantities carry intervals; comparison is
Kleene three-valued; `Status.from_trivalent` maps `INDETERMINATE` onto
`INCONCLUSIVE`. A measured `[39.6, 40.3] g` against a 40 g budget is
`INCONCLUSIVE` because the interval straddles the threshold, and there is no code
path — no override, no confidence threshold, no report-writing step — that turns
it into a pass.

Supporting rules:

- `Trivalent.__bool__` raises. `if comparison:` would silently treat unknown as
  failure, which is the bug the type exists to prevent.
- Soft evidence (visual review, user confirmation) is excluded from the release
  roll-up entirely, and a soft `PASS` is downgraded to `NOT_TESTED`. A vision
  model can ask for a deterministic check; it cannot stand in for one.
- Combining: any `FAIL` wins (a known failure is the most informative result
  available and is never masked); then `BLOCKED`; then `INCONCLUSIVE`; then
  `NOT_TESTED`. An empty set of gates is `NOT_TESTED`, never `PASS` — checking
  nothing is not the same as checking everything successfully.
- An equality gate with no declared tolerance raises. Exact equality between
  measured quantities is never satisfiable, so a tolerance is required rather
  than assumed.
- Unapproved high-risk assumptions block release regardless of how many gates
  passed. The golden clevis demonstrates this: every gate passes and the verdict
  is `BLOCKED`, because nobody accepted the load it was checked against.

## Consequences

**Good.** The honest answer is the cheap answer — it falls out of the arithmetic.
A report cannot round an uncertain result up. CI can distinguish "failed" from
"could not check" through exit codes 1 and 2.

**Costly.** More `INCONCLUSIVE` results than users expect, especially early, when
measurements are coarse and tolerances are wide. This is working as intended and
is a prompt to refine a measurement or widen a requirement deliberately. The
alternative is a confident number nobody checked.
