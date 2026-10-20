# Evidence, gates and release decisions

## The invariant

**Evidence outranks language-model opinion.** A deterministic gate that failed
cannot be overruled by a confident summary, and a gate that could not be decided
is reported as undecided rather than rounded up.

Three mechanisms enforce that rather than merely asserting it.

## 1. Six statuses

| Status | Meaning |
| --- | --- |
| `PASS` | Evidence satisfies the gate, within the validity domain the evidence declares |
| `FAIL` | Evidence violates the gate. A real result, and a valuable one |
| `INCONCLUSIVE` | The method ran; the result is too uncertain to decide |
| `BLOCKED` | A required input, tool or human decision is missing |
| `NOT_TESTED` | No test has run. The default, never silently upgraded |
| `NOT_APPLICABLE` | Excluded, with a recorded rationale |

`INCONCLUSIVE` is a failure of the *measurement*, not the design, and asks for
refinement rather than redesign. `NOT_TESTED` is neither.

Combination rules: any `FAIL` wins, then `BLOCKED`, then `INCONCLUSIVE`, then
`NOT_TESTED`. An empty set of gates is `NOT_TESTED` — checking nothing is not
the same as checking everything successfully.

## 2. Verdicts are computed

```python
gate     = Gate("MASS", "body mass within budget", "at_most", Q(40, "g"))
measured = Q(39.95, "g", plus=0.35, minus=0.35)
gate.evaluate(measured, ...).status      # INCONCLUSIVE
```

The quantity carries an interval. The comparison is Kleene three-valued. The
interval straddles the threshold, so the comparison is `INDETERMINATE`, so the
gate is `INCONCLUSIVE`. No judgement is involved at any step, and there is no
code path by which a language model, a summary, or a report writer converts that
into a pass.

A point estimate of 39.95 g would have passed. The interval says the part might
weigh 40.3 g, and so the gate says it does not know.

## 3. Evidence is immutable and self-limiting

`EvidenceGraph.add` refuses to replace an existing identifier. Superseding a
result means appending a node that names the old one as its parent, which keeps
the history intact — including the results that failed and the ones that were
superseded. That makes a report auditable rather than merely current, and it
makes the tempting move of quietly re-running a failing check until it passes
visible instead of invisible.

Any node produced by a numerical, analytical or sampling method **must** declare
its limitations, or construction raises. A node saying "peak von Mises 180 MPa"
without saying "linear static, single load case, unconverged mesh, stress
singularity not excluded" is worse than no evidence, because it invites a
conclusion it cannot support.

## Soft evidence

`VISUAL_REVIEW` and `USER_CONFIRMATION` are marked soft. They are excluded from
the release roll-up entirely, and a soft result that would otherwise `PASS` is
downgraded to `NOT_TESTED`. A vision model can notice a missing feature and ask
for a deterministic check to be run; it cannot stand in for one, in either
direction.

## Release decisions

`release_status` returns a verdict **and the specific reasons** it is not
`PASS`, because "blocked" without a list of what to do about it is not
actionable. Non-critical gates are excluded from the verdict but not from the
report: a soft requirement that failed is surfaced, it simply does not stop a
release on its own.

Unapproved high-risk assumptions block release regardless of gate results. The
golden clevis demonstrates this directly: every gate passes, and the verdict is
`BLOCKED`, because the 500 N load it was checked against is an assumption nobody
accepted and the material grade is an assumption nobody confirmed.

That is the whole point. A design that passes every check it was given is not
thereby ready to release, if the checks rested on values that were invented.
