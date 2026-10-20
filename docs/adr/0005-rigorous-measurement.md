# ADR-0005: Measurements are enclosures, and discretisation error is reported

**Status:** Accepted · **Date:** 2026-09-11

## Context

Every CAD system answers "what is the volume?" with a single number. The caller
has no idea what its error is. For a B-Rep kernel that error is usually tiny; for
anything mesh-based it is a function of resolution and nobody checks.

Forge compares measurements against thresholds and emits pass or fail. A
measurement with unknown error makes that comparison meaningless near the
threshold, which is exactly where it matters.

## Decision

Measurement returns an **interval that provably contains the true value**.

For a field with Lipschitz bound `L`, a cell of half-diagonal `r` centred at `c`
is entirely inside when `f(c) <= -r*L` and entirely outside when `f(c) >= r*L`.
Neither test can be fooled: the field cannot change fast enough to reach zero
within the cell. Straddling cells are subdivided; those still straddling at the
refinement limit contribute to the upper bound and not the lower one.

Three refinements make the resulting interval tight enough to be useful rather
than merely sound:

**Interval arithmetic over the SDF tree.** The Lipschitz test is sound but badly
pessimistic on the geometry engineers actually build: it assumes the field might
be changing at maximum rate in every direction, when a plate's flat face is
exactly linear and changes only along one axis. Evaluating the field over a whole
cell with interval arithmetic decides such cells outright. On the golden plate
this took residual uncertainty from **13.4% to 2.0%** at the same depth.

**Per-cell distance bounds.** A straddling cell is not wholly unknown. For an
`L`-Lipschitz field, every point within `-f(c)/L` of the centre is inside and
every point within `f(c)/L` is outside; each ball contains an inscribed axis-aligned
cube, giving a sound volume bound with no further evaluations.

**Tight centroid bounds.** Dividing the moment interval by the volume interval is
sound but loose, because it lets numerator and denominator take independent
extremes when both are driven by the *same* unknown fill fractions. The centroid
is a linear-fractional function of those fractions, and Dinkelbach's method gives
its exact extremes over the box in a handful of iterations. This took the
reported centroid of the golden plate from ±0.61 mm to **±0.19 mm** from
identical cells.

## Consequences

**Good.** A gate against a measurement too coarse to decide it returns
`INCONCLUSIVE` automatically, through three-valued comparison, with no human
judgement involved. The refinement limit is a knob the user controls and the
residual uncertainty is always reported.

**Costly.** Slower than a point estimate: roughly a second for a bracket at depth
9. Blended geometry has Lipschitz bound `√2` rather than 1 (see below), so it
needs more refinement for the same tightness.

**A bug this caught.** The exact circular round-union used for fillets is *not*
1-Lipschitz — its gradient is bounded by `√2`, not 1. Declaring 1 would have made
the cell classification unsound and quietly broken every volume enclosure on any
part with a fillet. `test_lipschitz_bound_holds_numerically` samples 4,000
gradients and asserts the declared bound, which is how it was found.
