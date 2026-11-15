# ADR-0024: The trust core may hold Forge's own compiled code, in Rust

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

The plan asked whether the trust core may hold Forge's own compiled code,
still with no CAD library (R11). Measured on the held-out run (2,000 parts,
10 November 2026): a part's mean time is 84 s, of which building is 3 s;
judging the B-rep 27 s, grading against the generator's truth 14 s, the
mesh judge 13 s, the rest mutants and views. Almost all of it is Forge's
own Python and NumPy deciding point membership, distances and crossings.
Stage 4b needs on the order of 250,000 to 400,000 counted specs, heavier
ones (about 300,000 counted, ADR-0027): at today's speed that is months of compute. And 4b's
certified solids (item 4) need exact interval arithmetic and robust
predicates done fast.

## Decision

**A Rust crate, `forge_core`, built with PyO3 0.30 and maturin 1.16**, one
stable-ABI (`abi3`, 3.14) wheel each for Windows x64, Linux x86-64 and
aarch64 and macOS arm64, built in CI, and a free-threaded build for CI's
3.14t run (an `abi3` wheel won't load there); `abi3t` added when Forge
moves to 3.15.
It holds the trust core's hot paths: point classification against every
oracle solid, certified distances and line and circle crossings, B-spline
and rational patch evaluation (Forge's own de Boor), certified subdivision,
the mesh judge's queries, and BVH culling so that most points never reach an
exact test.

- **Certified arithmetic by construction:** Forge's own interval type,
  rounding outward with `next_up` and `next_down` after each correctly
  rounded operation (+, −, ×, ÷, √); never by switching the CPU's rounding
  mode (undefined behaviour in Rust). Transcendental functions (sin, exp)
  from a vendored library with proven error bounds (correctly rounded
  where one exists, CORE-MATH's or equal, chosen at 4b.0d1), never the
  platform's own, widened by their bound. Exact predicates by expansion
  arithmetic (Shewchuk's), from the `robust` crate (MIT/Apache-2.0).
  Bounding boxes for culling are rounded outward too.
- **Speed:** rayon threads with the GIL released (they serve one
  worker's latency, the laptop's single build and interactive use; counted
  runs keep one worker per core); SIMD through
  `fearless_simd` on stable Rust; no GPU (double precision is slow on
  consumer GPUs and its results less reproducible).
- **Two implementations:** the Python and NumPy trust core stays as the
  executable specification, and every new solid gets its Python twin,
  slow but plain. CI runs both on every test and on a sample of every
  counted run's points. They must never contradict each other: one may
  answer UNKNOWN where the other decides (their interval widths differ),
  and UNKNOWN escalates to the referee; a contradiction is a bug in one of
  them.
- **A referee in CI only:** python-flint (FLINT 3.6, Arb) settles points
  too close to call and certifies the test suite at high precision. It is
  not a runtime dependency of the trust core.
- **Its dependencies** are ADR-0034's: every crate (PyO3, rayon,
  fearless_simd, robust, the math library) vendored and locked; mutation
  testing by cargo-mutants beside mutmut (plan 4.6).

## Consequences

- The judging code 15 to 20 times faster, what the speed gate's 6 s
  median needs (ADR-0027 sets and measures it), so 4b's counted runs fit.
- A second language and toolchain (rustup with MSVC on Windows; prebuilt
  wheels mean the owner needs no toolchain to run Forge). PyO3 is pre-1.0:
  pinned, updated deliberately.
- 4b.0d1's certified solids are written once, in the crate, against the
  Python reference.

## Alternatives

Cython or C++ through nanobind: as fast, but without Rust's memory and thread
safety in the code that decides verdicts. Numba: a JIT whose `fastmath`
silently breaks interval guarantees. JAX, CuPy, Warp: GPU or float32
oriented. python-flint at runtime: correct but one scalar at a time, far too
slow for millions of points. All rejected.
