# ADR-0025: Every operation states its tolerance, and the cap bounds it

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

Stage 4's after-check (`forge_occ/aftercheck.py`) holds every built edge to
1e-4 mm. Booleans between B-spline faces, sewing and fitted surfaces widen
edges past that by design; stage 4b brings all three. Revision 5 also adds
continuity tolerances (G1 angle, G2 relative curvature, G3) and a cap on
every region's tolerance at an eighth of its tightest band (item 9).

## Decision

- **Each ForgeIR operation declares a tolerance class** in its registry
  entry: exact analytic (1e-4 mm, today's), B-spline boolean, sewing,
  fitted (the fit's own band), and imported (the file's measured band).
  The numbers for the B-spline classes are measured on OCCT 8.0.1
  (ADR-0022) at 4b.0a′ over a fixture set of freeform booleans, sewings
  and fits made for it (stage 4's corpus has none), and written into the
  definitions.
- **The file states the loosest; every face is judged at its own.** A
  STEP file states the part's loosest tolerance, as stage 3's writer does
  (V2-stage3.md, 12), but every face is re-opened and judged at its own
  region's capped tolerance, so one loose sewing never widens an H7 bore's
  check.
- **The cap governs:** no operation's tolerance may exceed an eighth of
  the tightest band of the faces it touches; above it the part is refined
  or ends VERIFIED EXCEPT, naming it (item 18).
- **Continuity tolerances** (item 9): a G1 angle, a G2 relative curvature
  and a G3 relative third derivative, each with an absolute floor where
  curvature is near zero, measured on the fixture set before they are
  written (0.01°, 1% and 5% are the starting guesses, not the numbers),
  each capped by the item's class; judged on the shipped STEP.
- **The tolerance class is in the content cache's key** (ADR-0006), so a
  change of policy never reuses a stale build.

## Consequences

Booleans of freeform faces stop being after-check failures and become stated,
bounded tolerances. Every number is measured before it is written.
