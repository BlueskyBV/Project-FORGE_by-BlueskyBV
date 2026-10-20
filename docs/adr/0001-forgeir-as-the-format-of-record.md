# ADR-0001: ForgeIR is the format of record, not any CAD application

**Status:** Accepted · **Date:** 2026-09-11

## Context

A design system that talks to CAD has to decide what the design *is*. Three
options were live:

1. The design is a Fusion file, and everything else is an export.
2. The design is a script (CadQuery, OpenSCAD), and the geometry is whatever the
   script produces this time.
3. The design is a neutral document, and every CAD application is a backend.

Option 1 makes Fusion's feature set the ceiling, ties the product to a
proprietary runtime and licence, and makes headless verification impossible.
Option 2 is tempting because generating code is easy for a language model, but a
script is not analysable: you cannot ask a script what its pivot bore is, you can
only run it and hope. It also means arbitrary generated code executes to produce
geometry, which is a security problem before it is an engineering one.

## Decision

The design is a **ForgeIR document**: a versioned, strictly validated,
CAD-neutral description of intent. Every CAD application — the implicit kernel,
OpenCascade, Fusion — is a backend that consumes it. None is privileged, and none
of their idioms leak into the language.

Consequences that follow from this and are non-negotiable:

- Typed operations before generated code. The model emits validated ForgeIR; a
  sandboxed code escape hatch exists but is a controlled fallback, marked as
  such in the report, and never the default.
- Every dimensional value carries a unit at the document boundary.
- Geometry is referenced by *meaning* (`pivot.bore`), never by index.
- Unknown fields are refused rather than ignored, because a silently dropped
  misspelled field loses intent while appearing to succeed.

## Consequences

**Good.** The same document compiles to a fast implicit kernel for screening and
an exact kernel for STEP. Verification runs headless with no licence. A design
outlives any one CAD vendor. The document is diffable and reviewable.

**Costly.** Every feature must be designed into the language before any backend
can build it, which is slower than emitting code. Some proprietary features will
have no faithful representation and must degrade explicitly rather than
silently — see ADR-0007.

**Accepted trade-off.** ForgeIR portability is worth more than perfect
replication of any one CAD application's feature set.
