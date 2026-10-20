# ADR-0006: The feature graph is compiled like a build system

**Status:** Accepted · **Date:** 2026-09-11

## Context

Interactive CAD rebuilds a model when a human edits it — occasionally, and a
full rebuild is fine. Forge rebuilds it thousands of times, because an optimiser
is searching a parameter space. A campaign varying three parameters over 500
candidates rebuilds every datum, every unaffected sub-body and every untouched
boolean 500 times unless something prevents it.

## Decision

Each feature node is keyed by a hash of everything that could change its output:
its kind, its **resolved** parameter values, its inputs' hashes, and the identity
and version of the backend that will build it. Compilation is memoised evaluation
of the DAG; only nodes whose key changed are rebuilt.

Two details matter more than they look:

**Resolved values, not expressions.** Two parameter sets that evaluate to the
same numbers are the same geometry and share a cache entry; renaming a parameter
invalidates nothing. It also means `6 mm` and `0.006 m` hit the same entry, which
is tested.

**Deterministic ordering.** Ties in both topological sorts break alphabetically.
The order participates in the cache key, so a nondeterministic sort would produce
different keys for an identical document and defeat caching entirely.

Floats are hashed via `repr`, which round-trips exactly. Two dimensions differing
in the last bit are different designs, and rounding here would serve the wrong
geometry.

## Consequences

**Good.** Measured on the golden clevis with `forge sweep`:

| Parameter swept  | Features rebuilt | Avoided |
| ---------------- | ---------------- | ------- |
| `pivot_diameter` | 18 of 90         | 80%     |
| `root_blend`     | 34 of 90         | 62%     |
| `ear_thickness`  | 58 of 70         | 17%     |

The last row is the honest one. `ear_thickness` feeds nearly the whole graph, so
there is little to reuse — the saving depends on where in the graph you edit.
It grows with model size, because the dirty cone stays local while the graph
does not.

**Costly.** Every backend change must bump `BACKEND_IDENTITY` or stale entries
built by old code are served as current. The same applies to
`CACHE_SCHEME_VERSION`. This is a real operational hazard and the reason both
constants are documented at their definition.

**Not yet done.** The cache is in-process only. A persistent content-addressed
store shared across workers is in the backlog and is where the large win for
distributed optimisation lies.
