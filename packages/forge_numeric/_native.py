"""The compiled twin of :mod:`forge_numeric.vector` (native/forge_numeric_native; ADR-0037): its array entry points, when this machine has it.

:mod:`._core` opens the library (refusing one of another interface version
or built from other source); this declares the entry points on arrays, and
:mod:`.vector` uses them only if they reproduce the NumPy twin on a fixed
set of inputs at load. Otherwise :mod:`.vector` computes everything with
NumPy: the same bits, more slowly. (V2 code reads no environment variable,
so nothing turns it off from outside; the tests hold
``forge_numeric.vector.numpy_twin()`` to run the NumPy twin.)
"""

from __future__ import annotations

import ctypes
from typing import Any

import numpy as np

from ._core import ABI, HERE, SOURCE, fnv1a, library_path

__all__ = ["ABI", "HERE", "LIB", "SOURCE", "WHY_NOT", "fnv1a", "library_path"]

_P = ctypes.c_void_p
_N = ctypes.c_size_t


def _array_entries(lib: Any) -> Any:
    """The library, its array entry points declared."""
    for name in (
        "fnum_atan",
        "fnum_asin",
        "fnum_acos",
        "fnum_exp",
        "fnum_log",
        "fnum_cbrt",
    ):
        f = getattr(lib, name)
        f.argtypes = [_P, _P, _N]
        f.restype = None
    lib.fnum_sincos.argtypes = [_P, _P, _P, _N]
    lib.fnum_sincos.restype = _N
    lib.fnum_atan2.argtypes = [_P, _P, _P, _N]
    lib.fnum_atan2.restype = None
    for name in ("fnum_hypot", "fnum_hypot_narrow"):
        f = getattr(lib, name)
        f.argtypes = [_P, _P, _P, _N]
        f.restype = _N
    lib.fnum_matmul.argtypes = [_P, _P, _P, _N, _N, _N]
    lib.fnum_matmul.restype = None
    return lib


def _from_core() -> tuple[Any | None, str]:
    from . import _core

    return (_array_entries(_core.LIB) if _core.LIB is not None else None), _core.WHY_NOT


LIB: Any
WHY_NOT: str
LIB, WHY_NOT = _from_core()


_address = ctypes.addressof
_first_byte = ctypes.c_char.from_buffer


def _at(a: np.ndarray) -> int:
    """The address of a contiguous array's first element: by the buffer protocol where the array can be written (three times quicker), by NumPy's ``ctypes`` otherwise."""
    try:
        return _address(_first_byte(a))
    except TypeError:  # read-only
        pass
    except ValueError:  # empty
        pass
    except BufferError:  # not contiguous
        pass
    return int(a.ctypes.data)


def unary(name: str, x: np.ndarray) -> np.ndarray:
    """``x`` (contiguous float64) through the library's elementwise ``fnum_<name>``."""
    out = np.empty_like(x)
    getattr(LIB, "fnum_" + name)(_at(x), _at(out), x.size)
    return out


def sincos(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """(sin, cos, how many elements were deferred: written NaN, for the caller to compute)."""
    s = np.empty_like(x)
    c = np.empty_like(x)
    return s, c, LIB.fnum_sincos(_at(x), _at(s), _at(c), x.size)


def atan2(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.empty_like(x)
    LIB.fnum_atan2(_at(y), _at(x), _at(out), x.size)
    return out


def hypot(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, int]:
    """(the lengths, how many elements were deferred: none, now; the count is kept for the interface)."""
    out = np.empty_like(x)
    return out, LIB.fnum_hypot(_at(x), _at(y), _at(out), x.size)


def matmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``a`` (rows by k, contiguous float64) times ``b`` (k by cols, the same), sums left to right."""
    out = np.empty((a.shape[0], b.shape[1]))
    LIB.fnum_matmul(_at(a), _at(b), _at(out), a.shape[0], a.shape[1], b.shape[1])
    return out
