# ADR-0037: The same numbers on every machine

**Status:** Accepted · **Date:** 2026-11-16 · Stage 4b.0c, item 0 · Amends
[ADR-0024](0024-compiled-trust-core.md) in part (its math library, and how
the compiled code is loaded)

## Context

4b.0b's end proof found that Forge's digests depend on the machine
([V2-stage4b-0b.md](../V2-stage4b-0b.md), 6.4). Measured on 16 November
(`forge-machines.yml`, 200 seeds, every program's output digested, nothing
pinned, against a Linux x86-64 runner held to AVX2): another Linux x86-64
runner differed on 16 seeds, Linux on ARM on 3, Windows on 45 (on 13 the
generator drew a different part, so a seed means another part there), and
macOS on ARM on 199. The causes, each found by switching it alone:

- **BLAS and LAPACK** (`@`, `dot`, `einsum`, every `linalg` call, and
  `linalg.norm` of a vector, a BLAS dot): the order of their sums and their
  fused multiply-adds depend on the CPU's kernels, the library (OpenBLAS,
  Apple's Accelerate) and its threads.
- **Elementary functions** (`sin`, `atan2`, `exp`, `log`, `cbrt`,
  `hypot`): NumPy's SIMD paths (AVX-512's differ from AVX2's for
  `arctan2`, `cbrt`, `exp`, `log`, `arccos`) and each operating system's C
  library (glibc, Microsoft's, Apple's) round their last bit their own way.
- **Fused multiply-adds in compiled C**: Clang (macOS) fuses `a * b + c`
  into one rounding unless told not to, and Microsoft's compiler does on
  ARM, so NumPy's `einsum`, `interp` and complex arithmetic, and CPython's
  complex numbers, `math.hypot` and `math.dist`, may round otherwise there;
  and `x ** y` is the C library's `pow`.

IEEE 754 fixes `+ - * /` and `sqrt` exactly; NumPy's elementwise arithmetic
and its sums (its own pairwise addition, scalar C) are the same everywhere.

## Decision

**Forge computes every number from operations IEEE 754 fixes, in an order
Forge fixes,** through `forge_numeric`, an L0 package (standard library and
NumPy):

- `forge_numeric.scalar`: `sin`, `cos`, `sincos`, `tan`, `atan`, `atan2`,
  `asin`, `acos`, `exp`, `expm1`, `log`, `log1p`, `cbrt` on floats, ported
  from FreeBSD's msun (Sun's fdlibm), each under one ulp (`tan` two),
  raising where `math` does; arguments past 2^20 pi/2 reduced exactly with
  integers; `decade` (`floor(log10(x))` as the number is written, exactly);
  `sq` and `cube` for `**`. It imports no NumPy, so the standard-library
  packages use it too.
- `forge_numeric.vector`: the same on NumPy arrays, bit for bit the scalar
  ones; `hypot` as `sqrt(x*x + y*y)` (scaled by a power of two first past
  1e150 or below 1e-150), and on numbers `hypot` and `dist` of any number
  of coordinates; and products and small linear algebra in a fixed
  order: `dot`, `norm`, `unit`, `matmul`, `solve` (Gaussian elimination
  with partial pivoting), `det`, `inv`, `eigh` (cyclic Jacobi),
  `cond_symmetric`, `real_roots` (isolated between the derivative's roots,
  bisected to the last bit), `roots` (complex, Aberth and Ehrlich's
  iteration, for `numpy.roots`), `interp` (`numpy.interp`'s formula, each
  operation rounded) and `normal` (normal draws from uniform ones, Box and
  Muller).
- **A compiled twin, for speed:** `native/forge_numeric_native`, a Rust
  library with a C interface (Rust never fuses or reorders floating-point
  operations), the vector functions and the matrix product with a short
  contracted axis, operation for operation. It is loaded
  with `ctypes` from `packages/forge_numeric/_native/<platform>/`, where the
  libraries CI builds for Linux x86-64 and ARM, Windows x86-64 and macOS
  ARM (`native.yml`) are committed: one file per platform serves every
  Python (3.14, 3.15, the free-threaded 3.14t), and the laptop gets it with
  the project, with no install step. It is used only if its interface
  version matches, its compiled-in source digest is the source's, and it
  reproduces the NumPy twin on fixed inputs at load; otherwise NumPy
  computes the same bits more slowly.
- **The rule's guard:** no V2 code (its packages, and its modules in V1's)
  calls `math`'s or NumPy's elementary functions, `@`, `dot`, `einsum`,
  `linalg`, `fft`, `hypot` (NumPy's or CPython's), `math.dist`, `interp`,
  `roots`, `**` other than whole numbers' or two's whole powers, `pow`,
  `cmath`, `statistics`, complex numbers, or a
  random draw other than uniform ones
  (`tests/test_v2_architecture.py`, `EveryNumberIsTheSameOnEveryMachine`).
- **The proof:** golden digests in `tests/test_v2_numeric.py` that every
  machine must reproduce bit for bit, run by `trust-core.yml` on Linux
  x86-64 and ARM, Windows and macOS on every push; and the fingerprints of
  the same seeds equal on all five machines, nothing pinned
  (`forge-machines.yml`).

What stays outside: OpenCascade (its own C++ and C library, so a built
B-rep's last bits may differ between operating systems) and V1's frozen
implicit kernel (`forge_geom`), whose results enter verdicts through
widened intervals. Their outcomes are compared across machines, not their
bits.

## Consequences

- A seed is the same part on every machine; a run on the laptop can be
  held against a runner's digest for digest; the SIMD pins of 4b.0b's
  proof are no longer needed.
- Every digest changes once, by last bits, when the call sites move:
  4b.0c's first change set, proven by every exit outcome the same on
  stage 4's 10,000 seeds (V2-stage4b-0c.md).
- ADR-0024's math library is decided: msun's algorithms, bounded under one
  ulp, in `forge_numeric`, which `forge_core` (4b.0d1) uses rather than
  another; a correctly rounded library replacing them later is a migration
  that changes bits, proven as this one is. ADR-0024's PyO3 crate keeps its
  place for what needs Python objects (4b.0d1); kernels over arrays of
  floats are this library's.

## Alternatives

Pinning one SIMD level and one BLAS (what 4b.0b's proof did): it holds
Linux x86-64 only, not Windows or macOS, and leaves each C library's
`sin`. Correctly rounded functions now (CORE-MATH): the right end state,
but a larger port; msun's bounds are what the trust core's intervals need.
A PyO3 extension: a build per Python and none for the free-threaded one,
and a reinstall on the laptop at each change. Rejected for now.
