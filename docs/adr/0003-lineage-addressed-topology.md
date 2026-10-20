# ADR-0003: Geometry identity comes from the construction, not the geometry

**Status:** Accepted · **Date:** 2026-09-11

## Context

This is the topological naming problem, and it is the single hardest unsolved
problem in parametric CAD. FreeCAD names it as such; every kernel has a version
of it.

A user selects a face and fillets it. The system records the selection the only
way the kernel offers — "face 47". An upstream dimension changes, the kernel
rebuilds, the faces renumber, and "face 47" is now a different face, or gone. The
fillet lands elsewhere, or the rebuild fails, and in the worst case the model
looks right and is wrong.

The industry mitigation is a *persistent geometric signature*: remember the
face's area, centroid, normal, curvature class and adjacency, and after a rebuild
find the face most similar to the remembered one. This works until it does not,
and its failure mode is the bad one — the matcher always returns something, so a
wrong match is indistinguishable from a right one until a part is machined.

## Decision

Identity does not come from geometry at all.

When a feature publishes geometry, that geometry's identity is a hash of the
feature's stable identifier and the output's declared role:

```
token = H(scheme_version, feature_id, output_suffix, ordinal)
```

Nothing about coordinates, area, normals or topology enters the hash.

**Under a parameter change** the feature graph is structurally identical, so
every token is bit-for-bit identical and every selection resolves. This is not a
success rate to be measured; it is a property the representation cannot fail at.

**Under a topology change** the token still exists but may no longer name
anything on the boundary. `validate_entities` samples each named surface and
probes its neighbourhood; a surface with material on every side has been buried,
and the entity is marked `BURIED`. Resolving it then raises a `SelectionError`
naming the entity, the feature that owns it, and how much of it survived.

Entities are described **analytically** — a cylindrical face is an axis, a radius
and an extent — not as a reference into a topological data structure. That is
what lets the same entity mean something to the implicit kernel, to OpenCascade
and to Fusion, none of which share a notion of "face 47".

### Why the burial check probes a neighbourhood

The obvious implementation asks whether the distance field is near zero on the
named surface. That is wrong, and subtly so: `min(f_a, f_b)` is the exact
distance field of a union only *outside* it. Inside, it is merely an upper bound.
Where two operands share a face — a pad sitting flush under a plate — both fields
read exactly zero along that face, and a near-zero test declares a thoroughly
interior surface to be on the boundary. A buried reference then passes as live,
which is the exact failure this ADR exists to prevent.

The neighbourhood probe asks instead whether a small ball around each sample
contains *both* material and empty space. It cannot be fooled that way, and it
needs no surface normal — which matters, because the outward direction differs
between a boss (material inside) and a bore (material outside).

## Consequences

**Good.** Parameter changes never break selections, by construction. Topology
changes break them loudly and precisely. The mechanism is backend-independent
and testable — `tests/test_kernel.py` asserts token stability across seven
parameter variations and asserts that burying a referenced face fails.

**Costly.** Burial detection is a sampled test, so it has a threshold (25% of the
named surface must remain on the boundary) and can in principle misjudge a face
eaten down to a sliver. The surviving fraction is recorded in every entity's note
so that a nearly-consumed face is visible in the report rather than passing
quietly. Rim samples are inset, because a point on a face's perimeter lies on the
neighbouring face too.

**What this does not solve.** Splitting: if a feature divides one face into two,
both inherit the parent's token today. Distinguishing them needs derived tokens
with an ordinal rule, which `derived_token` supports but no feature yet uses.
