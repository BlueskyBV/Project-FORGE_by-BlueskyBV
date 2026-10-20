# ADR-0007: An implicit kernel ships first, and stays alongside the exact one

**Status:** Accepted · **Date:** 2026-09-11

## Context

The obvious first geometry backend is OpenCascade via CadQuery: true B-Rep, STEP
export, the representation the rest of the industry speaks. It is also a large
compiled dependency that must be installed before anything can be tested.

## Decision

Ship an **implicit backend** (signed distance fields, NumPy only) as the
reference implementation, behind the same adapter interface OpenCascade will use.
Keep both permanently rather than retiring the implicit one.

The implicit kernel earns its place three ways:

**It always runs.** No compiled CAD kernel, no licence, no install. The entire
pipeline — compile, measure, gate, report — is exercisable in a network-isolated
container, which is what makes the deterministic core testable everywhere and is
the only reason this repository has an end-to-end test suite on day one.

**It is fast enough to search with.** A candidate evaluates in milliseconds, so
an optimiser can screen thousands of parameter combinations before the exact
kernel is asked to build anything.

**It cross-checks.** Two independent kernels measuring the same design is real
evidence. A disagreement beyond declared tolerance is a defect in one of them,
and Forge would rather find that than average it away. `GEOM_CROSS_BACKEND` is a
gate in the pipeline today, comparing the octree enclosure against an
independently extracted surface mesh.

## What the implicit kernel cannot do

Stated plainly, and repeated in the capability matrix:

- No B-Rep topology, therefore **no STEP export** and no Fusion feature tree.
- No named faces in the topological sense. Entities are analytic descriptions.
- No closed-form volume. Measurements are rigorous enclosures (ADR-0005).
- Fillets are produced by the boolean, as a blended junction, rather than applied
  afterwards to selected edges.

That last point deserves a note. A blended union produces a *true circular
fillet* of exactly the requested radius — the exact round-union formula was
chosen over the more common polynomial smooth minimum precisely because the
polynomial one's actual radius is not the number you passed in, which is fine for
rendering and not fine for a part someone will machine and inspect.

But where two operands share a *coplanar* face there is no concave crease to
fill, and the blend still adds material there, up to `(√2 - 1)·k`. This is a
property of implicit blending, not a defect. A design needing a flush face across
a blended junction trims the result to its declared envelope with an explicit
intersection — which is both a legitimate modelling operation and a statement of
intent the verifier can then check. The golden clevis does exactly this, and its
envelope requirement passes because of it.

## Consequences

**Good.** A working, tested, verifiable system exists before any CAD kernel is
installed. The adapter boundary is proven by having two implementations rather
than being asserted with one.

**Costly.** Two backends to maintain, and features must be implemented twice.
Some ForgeIR features the exact backend will support have no implicit
implementation and must declare themselves unsupported rather than approximate.
