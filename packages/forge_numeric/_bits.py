"""The words of a float64, for the few steps of the elementary functions that read or set them (exact operations)."""

from __future__ import annotations

import struct

_D = struct.Struct("<d")
_Q = struct.Struct("<q")


def bits(x: float) -> int:
    """The 64 bits of ``x`` as a signed integer."""
    return int(_Q.unpack(_D.pack(x))[0])


def high(x: float) -> int:
    """The high 32 bits of ``x`` (sign, exponent and the top 20 bits of the significand), signed as C's int32."""
    return bits(x) >> 32


def from_bits(b: int) -> float:
    return float(_D.unpack(_Q.pack(b))[0])


def with_low_zero(x: float) -> float:
    """``x`` with the low 32 bits of its significand cleared."""
    return from_bits(bits(x) & ~0xFFFFFFFF)


def from_high(h: int) -> float:
    """The float whose high word is ``h`` (taken as 32 bits) and whose low word is 0."""
    b = (h & 0xFFFFFFFF) << 32
    return from_bits(b - (1 << 64) if b >= 1 << 63 else b)
