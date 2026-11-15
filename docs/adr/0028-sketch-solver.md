# ADR-0028: The sketch solver: planegcs as the proposer, Forge as the judge

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

Stage 4b.0 item 8 needs a 2D constraint solver used as a proposer outside
the trust core, its solution stored with its branch signature and checked
by the trust core's residuals. As of 10 November 2026: `planegcs` 0.9.6
(FreeCAD's solver as a standalone package, LGPL-2.1-or-later, wheels for
Windows and Linux on CPython 3.12 to 3.14, conics and B-splines, DogLeg,
Levenberg-Marquardt and BFGS, a diagnosis of degrees of freedom and of
conflicting and redundant constraints, results repeatable since 0.9; one
maintainer); `slvs` 3.3 (SolveSpace's solver, GPL-3, 3D, wheels everywhere).

## Decision

- **2D: `planegcs`, pinned exactly, imported, behind Forge's own solver
  interface,** its source archived with Forge's dependencies. Its
  "converged" is never trusted: the trust core evaluates every constraint's
  residual on the stored geometry in its own code (intervals, ADR-0024),
  checks the branch signature and computes the degrees of freedom from the
  Jacobian's rank.
- **3D sketches, and a second opinion on 2D: `slvs`,** in a separate
  process (GPL-3), behind the same interface.
- **Fallback:** if `planegcs` stops being maintained, Forge's own
  Levenberg-Marquardt on the same constraint equations, which the
  interface already defines; the trust core's checks don't change.

## Consequences

A mature solver from day one, replaceable without touching the checks.
