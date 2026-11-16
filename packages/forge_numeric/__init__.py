"""Forge's numbers, the same on every machine (V2-stage4b-0c.md, item 0; ADR-0037).

Every number Forge computes is a function of its inputs alone: the same bits
on an AVX2 or an AVX-512 PC, an ARM Mac or server, under Windows, Linux or
macOS, whatever BLAS, SIMD level or C library is there. IEEE 754 fixes
``+ - * /`` and ``sqrt`` exactly; it fixes nothing about ``sin``, ``atan2``,
``exp``, ``log``, ``cbrt`` or ``hypot`` (each C library and each NumPy SIMD
path rounds its own way), nor about the order of a sum that BLAS adds (``@``,
``dot``, ``einsum``, ``linalg``). So Forge never calls those; it calls these:

- :mod:`forge_numeric.scalar` (``fs``): ``sin``, ``cos``, ``sincos``, ``tan``,
  ``atan``, ``atan2``, ``asin``, ``acos``, ``exp``, ``expm1``, ``log``
  (of any integer too, as ``math.log``), ``log1p``, ``cbrt`` on Python floats,
  raising where ``math`` raises; ``decade`` (``floor(log10(x))``, exactly);
  ``sq`` and ``cube`` for ``x ** 2`` and ``x ** 3``. It imports no NumPy, so
  the standard-library packages use it too;
- :mod:`forge_numeric.vector` (``fv``): the same on NumPy arrays (``arctan2``,
  ``arccos`` and so on, NaN and infinity where NumPy gives them, a NumPy float
  for a number), bit for bit the scalar ones, with ``hypot``; products and
  linear algebra in a fixed order: ``dot``, ``norm``, ``unit``, ``matmul``,
  ``solve``, ``det``, ``inv``, ``eigh``, ``cond_symmetric``; polynomial roots
  (``real_roots``, batched; ``roots``, complex, as ``numpy.roots``);
  ``interp`` (``numpy.interp``'s formula, unfused) and ``normal`` (normal
  draws from uniform ones).

A compiled twin (``native/forge_numeric_native``, Rust behind a C interface)
computes the array functions and the larger matrix products where this
machine has it, the same bits faster; numbers and short vectors take Python
float shortcuts, the same bits again.

``math.sqrt``, ``math.hypot`` (CPython's own), ``math.fsum``, NumPy's
elementwise arithmetic, ``np.sqrt`` and its sums (``np.sum``, its own pairwise
addition in scalar C) are the same everywhere and stay. The rule is held by
``tests/test_v2_numeric.py`` (the functions: accuracy, the twins and the
shortcuts bit for bit, and golden digests every machine must reproduce) and
``tests/test_v2_architecture.py`` (no V2 code calls what they replace:
``EveryNumberIsTheSameOnEveryMachine``).
"""

from __future__ import annotations
