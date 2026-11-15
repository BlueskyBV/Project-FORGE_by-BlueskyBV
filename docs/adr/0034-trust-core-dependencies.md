# ADR-0034: What the trust core may depend on, and where part two's code lives

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a · Supersedes
ADR-0002 in part

## Context

ADR-0002 kept V1's five trust-core packages to the standard library, on
any Python 3.11 or later with no install step. V2 already lets its L0
packages import NumPy (V2-architecture.md, 2). Stage 4b brings Forge's own
compiled crate (ADR-0024), Python 3.14 (ADR-0023), and part two's checking
code: the calculators' verifier, validity conditions, the applied
resultants, the equilibrated-flux estimator. Where each lives was left
undecided (V2-stage4b.md, 2.1).

## Decision

- **L0, the trust core, may import** the standard library, NumPy, other L0
  packages, and Forge's own crate `forge_core`, whose Rust dependencies
  (PyO3, rayon, fearless_simd, robust, the math library) are vendored and
  locked. Nothing else: no CAD library (R11), no model, no solver, no
  SciPy, no SymPy.
- **In L0:** the oracle and checks, as today; the certified solids; the
  calculators' verifier (the second transcription); validity conditions
  and section properties measured on the built geometry; the applied
  resultants recomputed from the confirmed spec; equilibrium and energy
  tests; Forge's own equilibrated-flux estimator, which reads the mesh and
  the solution as data. They live in V2's L0 packages (`forge_checks` and
  its analysis modules), never in V1's `forge_analysis`, which keeps
  ADR-0002's rule.
- **Above L0:** the runner and every solver and mesher adapter (ADR-0033),
  scikit-fem, the calculators' proposers, the optimisers, the sketch
  solver's adapter, and the generator's analysis truths with the SymPy
  generator of manufactured solutions (the generator and tests only).
- **The Python floor** for V2 is ADR-0023's; V1's five packages keep
  ADR-0002's standard-library rule.
- **An import-graph test** enforces all of it, as today's does.

## Consequences

The trust core stays small, auditable and free of anything that computes
the answers it judges; ADR-0002 is superseded where V2 needs it, and only
there.
