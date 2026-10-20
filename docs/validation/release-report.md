# Validation report — v0.1.0

**Date:** 2026-09-12 · **Scope:** the deterministic kernel and the design loop

This report states what was tested, how, and — more importantly — what was not.

## Summary

| | |
| --- | --- |
| Tests | **270**, all passing |
| Test framework | `unittest` (standard library) |
| Runtime dependencies | NumPy only |
| Network required | none |
| Model provider required | none, including for every test of the design loop |
| Platforms verified | Linux / CPython 3.11, Windows workspace / CPython 3.10, **and Windows 11 native / CPython 3.12** |

### Second-platform verification

The full suite was re-run on the delivered copy, on a second machine and a
second interpreter version, and passed identically:

| Suite | Tests | Linux, CPython 3.11 | Windows workspace, CPython 3.10 |
| --- | --- | --- | --- |
| `test_units` | 52 | 0.04 s | 0.12 s |
| `test_expr` | 45 | 0.03 s | 0.09 s |
| `test_kernel` | 24 | 4.7 s | 6.2 s |
| `test_golden` | 30 | 93 s | 114 s |
| **Total** | **150** | **OK** | **OK** |

### Third platform: Windows 11 native, CPython 3.12

The complete suite — all 270 tests, the AI layer included — was then run on
Windows 11 under CPython 3.12, installed with `pip install -e .`:

```
Ran 270 tests in 247.905s

OK
```

Three interpreter versions (3.10, 3.11, 3.12) across two operating systems, with
no conditional code and no platform-specific test skips.

The number that matters is not the pass count. The golden clevis compiled to part
hash `f596df96c01cc6259bf9169c3978ccc4fd1f2c3f` on Windows/3.12 — **bit-identical
to the hash produced on Linux/3.11** — and reported volume
`12820.3 ± 387.677 mm³`, mass `34.6252 ± 1.39288 g` and minimum wall
`5.59224 ± 0.00704273 mm`, each identical to the last displayed digit.

That is the content-addressing and determinism claim of ADR-0006 tested the only
way it can be: by computing the same design on unrelated machines and comparing
the hashes. Floating-point geometry that agrees to the last printed digit across
two operating systems and two interpreter versions did not happen by luck; it
happens because nothing in the compile path depends on iteration order, hash
seeding, or platform float formatting.

The golden clevis verification produced byte-identical gate outcomes and
measurements agreeing to within the reported enclosures — volume
`12820.3 ± 387.7 mm³` on both, mass `34.63 ± 1.39 g` on both, and the same
`BLOCKED` verdict for the same two unapproved assumptions.

This is worth stating because it tests something the unit tests do not: that the
determinism claims hold across interpreter versions and filesystems, not merely
across runs on one machine. `requires-python` was lowered from 3.11 to 3.10 on
the strength of it, rather than being guessed at in either direction.

## What was verified

### Dimensional and uncertainty layer — 52 tests

Dimension algebra with fractional exponents; unit parsing including compound
forms with parentheses; interval arithmetic; three-valued comparison; affine
temperature handling; quantity serialisation round-trip.

**Soundness of interval arithmetic** is verified empirically rather than
asserted: 2,000 random interval pairs, 8 sampled points each — 16,000 checks
that the computed interval contains the true result for addition, multiplication
and division.

Notable: `parse_unit("rpm")` and `parse_unit("rev/min")` are asserted
numerically identical, because a factor of 2π hiding between two spellings of
one unit is precisely the failure mode this layer exists to prevent.

### Expression engine — 45 tests

Arithmetic, dimensional checking, tolerance propagation through a stack-up,
Kleene boolean logic, conditional expressions, the function table, parameter
graph resolution, cycle detection reported as a path, deterministic ordering,
dependency analysis, and a 400-deep chain that must not exhaust the stack.

**Security: 18 hostile expressions** are asserted to be refused —
`__import__`, `__class__.__mro__` traversal, `open`, lambdas, comprehensions,
containers, f-strings, walrus, starred arguments, attribute access,
subscripting, and every builtin name.

Two design choices are tested explicitly because they would otherwise be
surprising: `^` means exponentiation with `**` precedence (so `2 * mm^2` is
2 mm², not 4 mm²), and a parameter named `t` shadows the tonne.

### Kernel: lineage and incremental compilation — 24 tests

**Token stability** across 7 parameter variations, asserting every published
entity keeps a bit-identical token — the central claim of ADR-0003.

**Burial detection**: a pad added beneath the base must mark `base.z_min` as
`BURIED`, and resolving it must raise naming the owning feature. This is the
half that a heuristic face matcher gets silently wrong.

**Incremental compilation**: identical rebuild reuses everything; a `root_blend`
change rebuilds only the dirty cone; returning to a previous value is a cache
hit; the cache key is insensitive to unit spelling (`7 mm` and `0.007 m` share
an entry).

**Compile failures** fail closed: out-of-bounds parameters, zero dimensions,
unknown feature kinds, missing units, dangling interfaces — each refused with a
JSON Pointer.

**Geometry soundness**: octree enclosures contain the analytic volume for box,
cylinder, plate-with-hole and disjoint union; blends are verified local; interval
cell bounds are verified against 12,000 sampled field values; and the declared
Lipschitz bound is checked against 4,000 sampled gradients.

That last test earned its place. It caught a real soundness bug: the exact
circular round-union used for fillets has Lipschitz bound √2, not 1. Declaring 1
would have made cell classification unsound and quietly broken every volume
enclosure on any part with a fillet.

### Golden clevis, end to end — 30 tests

**Baseline**: every gate passes; unapproved assumptions still block release;
accepting them clears it; measurements are intervals; the two backends agree;
analytical evidence declares its limitations; evidence is append-only.

**Eleven injected faults**, each asserted to be caught and never to report `PASS`:

| Fault | Caught by |
| --- | --- |
| Ear spacing 9 mm (too narrow) | `REQ_EAR_SPACING` FAIL |
| Ear spacing 15 mm (too wide) | `REQ_EAR_SPACING` FAIL |
| Bore diameter 9.5 mm | `REQ_PIVOT_BORE` FAIL |
| Base length 72 mm | `REQ_BASE_X` FAIL *and* `REQ_ENVELOPE_X` FAIL |
| 18 mm bore in a 20 mm crown (1 mm wall) | `REQ_MIN_WALL` FAIL |
| Mass driven over budget | `REQ_MASS_BUDGET` FAIL |
| Fillet radius 40 mm | `CompileError`, out of bounds |
| Zero ear height | `CompileError`, degenerate |
| Material given as "aluminium" | `REQ_MASS_BUDGET` BLOCKED |
| Pad burying the mounting face | `IFACE_MOUNTING_FACE` FAIL |

The thin-wall case is the interesting one: every declared dimension is still
exactly what the document says and the part compiles cleanly. The fault is an
emergent property of two dimensions interacting, and only measuring the finished
solid finds it.

A complementary test asserts a *valid* design is not failed — a 4 mm ear passes
the 3 mm minimum-wall rule. A verifier that fails everything is as useless as one
that passes everything.

**Malformed documents**: unknown fields, missing required fields, a future schema
version, cyclic parameters, dangling inputs, wrong product kinds, and hostile
expressions — all refused.

**Determinism**: the same document produces the same part hash across
independent runs; serialisation round-trips losslessly; evidence content hashes
reproduce.


### The design loop — 119 tests

Every one of these runs the *real* orchestrator, the real roles with their real
generated prompts, the real compiler and the real verifier. Only the model is
replaced — by hand-written responses, or by a fixture library recorded from them.

**Patching — 26 tests.** RFC 6901 escaping in the order the standard requires
(`~01` decodes to `~1`, not `/`); all-or-nothing application; refusal to replace
a key that does not exist or to replace the whole document. The ordering tests
are the ones that matter: a batch removing features 1 and 3 must remove the
features that were at 1 and 3, and a batch that both removes from an array and
addresses another position in it — including *through* that position, as
`/features/2/id` does — is refused rather than resolved by a convention its
author never agreed to.

**Model transport — 35 tests.** No network is touched; the HTTP boundary is
exercised by feeding the adapter the shapes a real API returns. A retryable
failure is retried and a rejected credential is not; backoff grows, stays under
its ceiling, and jitters (40 samples must produce more than 30 distinct delays);
a server-supplied `retry-after` is honoured but capped. The budget is checked
*before* the call leaves, so an over-budget request is never sent. A forced tool
call becomes structured output; a truncated answer raises with the remedy named
rather than returning nothing; a 429, a 401, an oversized prompt and a 500 each
become a different, correctly-retryable error.

**The generated contract — 10 tests.** Every feature kind and every parameter the
compiler enforces appears in the authoring guide; every measurement binding is
documented; the JSON Schema covers every kind and refuses unknown fields. The
worked example shown in the guide is compiled and verified by the suite, so the
guide cannot show a document the compiler would reject, and its "derived"
parameter is asserted to actually derive.

**The loop — 39 tests.** A well-specified brief reaches a verdict with every role
called once. An underspecified one pauses, asks ranked questions, and designs
nothing. Proceeding without answers records each unknown as an unapproved
high-risk assumption containing the words "none was invented" — and is asserted
*not* to produce a value. An out-of-bounds design is repaired by one patch and
the run continues; the repaired document is compared byte for byte against the
original with only the offending node changed. An analyst that gives up ends the
run with its reason; one that proposes the same patch twice ends it as
oscillation. The analyst's slice is asserted to be the parameter the diagnostic
named — 944 bytes against a 9,262-byte document — rather than merely smaller.

**The command line — 9 tests.** The real CLI, end to end, against a recorded
library: a replayed run produces a document and evidence whose every claim
carries its provenance; the exit code is the verdict and not the absence of a
crash; an underspecified brief exits 3, writes its questions, and writes no
document. Three tests exist purely to keep a key where it belongs: there is no
`--api-key` flag, a missing key is refused before anything is spent, and nothing
the run writes contains anything key-shaped.

## Measured accuracy

Golden clevis, octree depth 9, on two cores:

| Quantity | Result | Reference |
| --- | --- | --- |
| Volume | 12820.3 ± 387.7 mm³ | mesh cross-check 12909.7 mm³, inside the enclosure |
| Mass (6061-T6) | 34.63 ± 1.39 g | budget 40 g |
| Centroid | 30 ± 0.35, 12 ± 0.22, 7.19 ± 0.20 mm | symmetric in x and y, as expected |
| Bounding box | 59.80 ± 0.25, 23.92 ± 0.10, 27.91 ± 0.11 mm | declared 60 × 24, enclosed |
| Minimum wall | 5.592 ± 0.007 mm | ear thickness 6 mm less the blend |
| Residual uncertainty | 5.5% of volume | stated, not hidden |

Analytical checks against textbook cases:

| Check | Computed | Exact |
| --- | --- | --- |
| I, 100 × 50 rectangle | 1.041667 × 10⁶ mm⁴ | 1041666.67 mm⁴ |
| Cantilever tip deflection | 1.6 mm | 1.6 mm |
| Root bending stress | 24 MPa | 24 MPa |

Surface extraction against analytic volumes, at resolution 110: box −0.05%,
sphere −0.01%, cylinder −0.04%, plate-with-hole −0.09%. All meshes watertight
and manifold.

## What was NOT verified

Stated plainly, because a validation report that only lists successes is
marketing.

- **No B-Rep geometry.** No OpenCascade, no STEP, no STEP round-trip tolerance
  check. The implicit kernel's measurements are enclosures, not closed-form.
- **No finite-element analysis.** No Gmsh, no CalculiX, no mesh convergence
  study. Structural results here are closed-form screening estimates against a
  single load case, and every one of them says so.
- **No assembly or kinematics.** No degrees-of-freedom computation, no
  range-of-motion sweep, no interference across a motion range.
- **No Fusion reconstruction.** The add-in does not exist and is not marked
  passed.
- **No optimisation.** The cache that makes it affordable is built and measured;
  the optimiser is not written.
- **No run against a live provider.** Every test of the design loop replays
  recorded responses. The prompts have been read and reasoned about; they have
  not been answered by a model. The first live run is the user's, and it is the
  test that has not been run.
- **No optimisation loop.** The orchestrator repairs what fails; it does not yet
  improve a design that already passes.
- **No multi-component designs.** The orchestrator compiles `components[0]`. The
  document model carries several; the loop does not yet drive them.
- **No file-ingestion hardening.** STEP/STL/archive import limits are designed in
  SECURITY.md and not implemented.
- **No physical validation of anything.** Simulation is not testing.
- **Material data is not certified.** Handbook values with stated ranges,
  adequate for synthetic validation examples and nothing more.
- **Docker and WSL2 paths are untested.** The Dockerfile and compose profile are
  written and reviewed; neither has been built or run. The suite has been
  verified on Linux/CPython 3.11 and on the Windows-hosted Linux workspace under
  CPython 3.10, but not inside a container and not under WSL2 proper.
- **No GPU path.** Nothing uses the RTX 4070 Super; nothing currently would
  benefit from it.

## Known limitations

1. **Burial detection is sampled.** The 25% threshold could in principle
   misjudge a face eaten to a sliver. The surviving fraction is recorded on
   every entity, so a nearly-consumed face is visible in the report.
2. **Wall thickness is sampled** by inward ray marching, so it only finds thin
   walls a sample landed on. It is an upper bound on the true minimum, which is
   the conservative direction for a manufacturability check.
3. **Blended booleans add material across coplanar faces.** A property of
   implicit blending, documented in ADR-0007, worked around in the golden
   example with an explicit envelope trim.
4. **Face splitting is unhandled.** A feature dividing one face into two gives
   both the parent's token. `derived_token` exists for this and no feature uses
   it yet.
5. **The cache is in-process.** No persistence, no sharing across workers.
6. **Two cores.** Nothing is parallelised, though the DAG structure permits it.

## Reproducing

```console
$ make test        # 270 tests
$ make test-ai     # just the design loop, replayed from fixtures
$ make verify      # the golden clevis, end to end
$ make sweep       # incremental compile behaviour
```
