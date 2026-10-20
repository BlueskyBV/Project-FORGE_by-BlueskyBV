# ADR-0004: Plane angle is dimensionless, and `rpm` means `rev/min`

**Status:** Accepted · **Date:** 2026-09-11

## Context

Whether plane angle should be a base dimension is a genuine and long-running
disagreement. SI treats the radian as dimensionless (a ratio of two lengths);
several engineering unit libraries add angle as an eighth base dimension so that
`rad/s` and `1/s` are distinguishable.

Treating angle as a base dimension catches a real class of error. It also breaks
ordinary mathematics: `sin(x)` requires a dimensionless argument, small-angle
approximations stop type-checking, and `v = omega * r` needs a special case.

## Decision

Plane angle is **dimensionless**, following SI. `deg`, `rad`, `rev`, `arcmin` and
`arcsec` are dimensionless units with different scale factors, so conversion
works normally and `sin(90 deg)` is `1.0`.

The consequence that must be stated explicitly, because it surprises people:
**1 Hz is not 1 rev/s.** A revolution is 2π radians and radians are
dimensionless, so `rev/s` is `2π s⁻¹`. This is the standard convention and it is
self-consistent.

Which forces the second half of the decision: `rpm` is defined as
`2π/60 ≈ 0.10472 s⁻¹`, so that `parse_unit("rpm")` and `parse_unit("rev/min")`
are numerically identical. Defining `rpm` as `1/60` — as several libraries do —
makes two spellings of the same unit disagree by a factor of 2π. A silent factor
of 2π hiding between two spellings of one unit is exactly the class of error this
package exists to prevent, so it is tested (`test_rpm_agrees_with_rev_per_min`).

## Consequences

**Good.** Trigonometry works. Conversions work. No special cases in the algebra.

**Costly.** `rad/s` and `s⁻¹` have the same dimension, so the type system cannot
catch confusing angular velocity with frequency. Mitigation: the unit *symbol* is
preserved through arithmetic rather than normalised, so a quantity reads as
`rad/s` in reports even though its dimension is `T⁻¹`, and a reviewer can see it.

**Revisit if** a robotics or controls domain pack finds this insufficient. The
dimension vector has room for an eighth component, but changing it is a breaking
change to every stored document.
