"""Forge's numbers, the same on every machine (V2-stage4b-0c.md, item 0; ADR-0037).

Every number Forge computes is a function of its inputs alone: the same bits
on an AVX2 or an AVX-512 PC, an ARM Mac or server, under Windows, Linux or
macOS, whatever BLAS, SIMD level or C library is there. IEEE 754 fixes
``+ - * /`` and ``sqrt`` exactly; it fixes nothing about ``sin``, ``atan2``,
``exp``, ``log``, ``cbrt`` or ``hypot`` (each C library and each NumPy SIMD
path rounds its own way), nor about the order of a sum that BLAS adds (``@``,
``dot``, ``einsum``, ``linalg``). So Forge never calls those; it calls these:

- :mod:`forge_numeric.scalar` (``fs``): ``sin``, ``cos``, ``sincos``, ``tan``,
  ``atan``, ``atan2``, ``asin``, ``acos``, ``exp``, ``log``, ``cbrt`` on Python
  floats, raising where ``math`` raises;
- :mod:`forge_numeric.vector` (``fv``): the same on NumPy arrays (``arctan2``,
  ``arccos`` and so on, NaN and infinity where NumPy gives them), bit for bit
  the scalar ones, with ``hypot``, ``dot``, ``norm``, ``unit``, ``matmul``,
  ``solve``, ``det``, ``inv``, ``eigh``, ``cond_symmetric`` and ``real_roots``.

``math.sqrt``, ``math.hypot`` (CPython's own), ``math.fsum``, NumPy's
elementwise arithmetic, ``np.sqrt`` and its sums (``np.sum``, its own pairwise
addition in scalar C) are the same everywhere and stay. The rule is held by
``tests/test_v2_numeric.py`` (the functions: accuracy, the twins bit for bit,
and golden digests every machine must reproduce) and
``tests/test_v2_architecture.py`` (no V2 package calls what they replace).
"""

from __future__ import annotations
