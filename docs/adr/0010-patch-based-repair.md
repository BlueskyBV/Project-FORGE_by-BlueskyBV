# ADR-0010: Repair is a patch, not a rewrite

**Status:** Accepted · **Date:** 2026-09-12

## Context

When a generated document fails to compile, the obvious move is to hand the model
the document and the error and ask for a corrected document. It works, and it is
the wrong shape:

- it costs a full document in and a full document out, every attempt;
- it puts everything that was already correct at risk, because a model rewriting
  four hundred lines to fix one field will occasionally change a fifth line too,
  and the diff nobody reads is where that lands;
- it leaves no record of *what the fix was*. A replacement document is not a
  repair; it is a new document that happens to be similar.

## Decision

A repair is a set of **RFC 6901 pointer-targeted patches** — `add`, `remove`,
`replace`, and nothing else. `move`, `copy` and `test` are excluded: each adds a
way for a patch to do something surprising, and none is needed to correct a
malformed feature.

The compiler's diagnostics already carry pointers, so the error and the fix speak
the same language. Four properties follow, and each is tested:

**Patches apply to a deep copy, all or nothing.** A half-applied repair yields a
document neither the model nor the compiler has ever seen. On failure the caller
still holds the original.

**Every pointer refers to the document as its author saw it.** Removals within an
array are applied back to front, so a batch removing features 1 and 3 removes the
features that were at 1 and 3 — not feature 1 and then whatever slid into slot 3.

**Ambiguity is refused rather than resolved.** If a batch removes from an array
that another patch also addresses by position — including *through* that position,
as `/features/2/id` does — then which element the second pointer means depends on
the order of application. That batch is rejected, with an error telling the model
to split the repair so the ordering is its choice. The analyst's prompt states the
rule, so the constraint is known before it is hit.

**The analyst sees a slice, not the document.** `extract_slice` sends the objects
the diagnostic names, anchored on the nearest enclosing identified object. A
parameter-bounds failure sends that parameter and its bounds — about 900 bytes
against a 9 kB document. This is not only a cost saving: a model shown the whole
design will comment on the whole design, and the repair loop is not the place to
renegotiate parts of it that compile.

Each attempt is recorded in the run as a `RepairAttempt` carrying the analyst's
diagnosis, its strategy, the patches, and the outcome. Proposing the same patch
twice ends the loop with `OR1002_OSCILLATION` rather than spending the budget
discovering that the model has run out of ideas.

## Consequences

- A repair is auditable. The run log shows what was tried, in what order, and
  what each attempt changed.
- The analyst can decline. `abandon: true` ends the run with a stated reason,
  which is the correct outcome when the design needs a different approach rather
  than a different value.
- The patch applier is small enough to test exhaustively, and is tested that way
  (`tests/test_patch.py`), because every repair the system makes passes through
  it and a patch landing one position off does not raise — it produces a document
  that compiles, verifies, and is not the design anyone approved.

## Alternatives considered

**Full JSON Patch (RFC 6902).** Rejected for the operations, not the format:
`move` and `copy` express edits that are hard to review and unnecessary here;
`test` invites a patch set that silently does nothing.

**Sequential application with standard RFC 6902 index semantics.** Standard, and
it means a model must simulate its own edits to write correct pointers for later
ones. The snapshot rule matches how the patches are actually authored — against
one view of one document — and the ambiguous cases are refused rather than
resolved differently from the author's intent.
