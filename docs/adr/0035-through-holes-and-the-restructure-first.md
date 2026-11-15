# ADR-0035: Through-holes counted by the oracle; the restructure before the Python move

**Status:** Accepted · **Date:** 2026-11-13 · Stage 4b.0a′ · The owner's
decision; amends [V2-stage4b.md](../V2-stage4b.md) revision 5 (2.1 and
item 7), ADR-0023 and [V2-stage4b-0b.md](../V2-stage4b-0b.md)

## Context

**Through-holes.** Stages 2 to 4 count a part's through-holes against the
oracle only where the oracle can say ([V2-stage2.md](../V2-stage2.md);
[V2-stage4.md](../V2-stage4.md), 9.3); elsewhere the count is listed in the
verdict as not cross-checked and changes no ending. The guarantee rests on
face accounting both ways, which finds a hole built or missed wherever the
hole has surface past the band. What it can't see is a hole opened or
closed by a contact within the band: two faces touching at a point or along
a line, or a sliver thinner than the band. Revision 5 of the plan left this
limit as it was. The kernel replay showed what an independent count is
worth: on generated part 450 the implicit kernel's count caught the exact
view's miscount ([V2-stage4b-kernel.md](../V2-stage4b-kernel.md), 3.2).

**Order.** Revision 5 had 4b.0a′'s second sub-step, CPython 3.14, replayed
on the unrefactored code, with 4b.0b's code written meanwhile and proven
after both replays. The owner wants each step finished and checked before
the next starts, and then everything checked together.

## Decision

1. **Item 7 (4b.0d's d2, topology):** the oracle counts each body's
   through-holes from its own shape, certified. A count it can't settle (a
   contact within the band) is UNKNOWN and held, false holds budgeted per
   kind, as item 4's tangent crossings are. "Through-holes the oracle
   doesn't count" leaves the verdict's list of what isn't cross-checked.
   Tests: part 450's bosses flush with a face's edges, and the pinch cases
   (faces touching at a point, along a line, and a sliver), each on both
   sides of the band.
2. **The order of 4b.0a′ and 4b.0b:** once the OpenCascade 8.0.1 replay
   passes, 4b.0b is done on the Python that replay ran on, and proven by
   its own byte identity (V2-stage4b-0b.md, 6), its baseline taken on the
   8.0.1 tree after that replay and 6.1. Then CPython 3.14 (ADR-0023), on
   the restructured code: every kept regression, the 2,000 held-out seeds
   and a fixed 2,000 of the counted seeds replayed against the 8.0.1
   replay's records, any difference sending it to a whole replay. Then
   4b.0c.

## Consequences

- One change at a time still: the kernel was replayed on its own; the
  restructure is proven to change no output on the Python it was made on;
  so a difference on 3.14 is Python's alone.
- No overlap: the Python check starts once 4b.0b is merged, about a day
  later than revision 5's order.
- Item 7's count may hold a part that stage 4 passed with its count listed
  (a pinch). Each such hold is examined: a false hold, budgeted, or a fault
  found.

## Alternatives

- **The count fixed now, during the kernel replay:** a judging change mixed
  into the kernel's replay and into 4b.0b's byte identity. Rejected.
- **Revision 5's order** (the Python move first, 4b.0b written alongside):
  about a day shorter. Rejected by the owner, who wants each step finished
  before the next.
