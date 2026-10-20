"""Content-addressed caching for the feature graph.

Forge treats a feature graph the way a build system treats a source tree. Each
node's output is keyed by a hash of everything that could change it -- its kind,
its *resolved* parameter values, the hashes of its inputs, and the identity and
version of the backend that will build it. Two nodes with the same key are, by
construction, the same geometry, so the second one is free.

Why this matters more here than in a normal CAD system
------------------------------------------------------
Interactive CAD rebuilds a model occasionally, when a human edits it. Forge
rebuilds it thousands of times, because the optimiser is searching a parameter
space. A campaign varying three parameters over 500 candidates rebuilds the same
datums, the same base plate and the same unaffected sub-assemblies 500 times if
nothing prevents it.

Content addressing prevents it. Changing ``ear_thickness`` changes the hash of
the ear features and of everything downstream of them; the base plate's hash is
unchanged, so it is not rebuilt. On the golden clevis this turns a full rebuild
into a partial one covering roughly half the graph, and the saving grows with
model size because the dirty cone stays local while the graph does not.

The *resolved* parameter values go into the key, not the expressions. Two
parameter sets that evaluate to the same numbers are the same geometry and
should share a cache entry, and a document that merely renames a parameter
should not invalidate anything.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Iterator, Mapping, TypeVar

from forge_units import Quantity

T = TypeVar("T")

#: Any change to how a node is compiled must bump this, or stale entries built
#: by the old code will be served as if they were current.
CACHE_SCHEME_VERSION = "1"


def _canonical(value: Any) -> str:
    """Render a value into a stable string for hashing.

    Floats are formatted with ``repr``, which round-trips exactly in CPython, so
    two bit-identical values always produce the same key and two values that
    differ in the last bit produce different ones. That is the correct
    behaviour: a design differing in the last bit of a dimension is a different
    design, and quietly rounding it here would serve the wrong geometry.
    """
    if isinstance(value, Quantity):
        magnitude = value.magnitude
        return f"Q({magnitude.lo!r},{magnitude.hi!r},{value.unit.symbol})"
    if isinstance(value, bool):
        return f"b({int(value)})"
    if isinstance(value, int):
        return f"i({value})"
    if isinstance(value, float):
        return f"f({value!r})"
    if isinstance(value, str):
        return f"s({value})"
    if value is None:
        return "n()"
    if isinstance(value, Mapping):
        inner = ",".join(
            f"{_canonical(k)}={_canonical(v)}" for k, v in sorted(value.items())
        )
        return f"m({inner})"
    if isinstance(value, (list, tuple)):
        return "l(" + ",".join(_canonical(item) for item in value) + ")"
    return f"o({value!r})"


def content_hash(*parts: Any) -> str:
    """Hash an ordered collection of values into a hex digest."""
    digest = hashlib.blake2b(digest_size=20)
    digest.update(CACHE_SCHEME_VERSION.encode())
    for part in parts:
        digest.update(b"\x1e")
        digest.update(_canonical(part).encode("utf-8"))
    return digest.hexdigest()


def feature_hash(
    *,
    kind: str,
    resolved_parameters: Mapping[str, Any],
    input_hashes: tuple[str, ...],
    backend_identity: str,
) -> str:
    """The cache key of one feature node."""
    return content_hash(
        "feature", kind, resolved_parameters, input_hashes, backend_identity
    )


@dataclass(slots=True)
class CacheStatistics:
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": self.hit_rate,
        }


class ContentCache(Generic[T]):
    """A bounded content-addressed store with least-recently-used eviction."""

    __slots__ = ("_entries", "_capacity", "statistics")

    def __init__(self, capacity: int = 4096) -> None:
        if capacity < 1:
            raise ValueError("cache capacity must be at least one")
        self._entries: dict[str, T] = {}
        self._capacity = capacity
        self.statistics = CacheStatistics()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def get(self, key: str) -> T | None:
        value = self._entries.get(key)
        if value is None:
            self.statistics.misses += 1
            return None
        # Re-insert to mark as most recently used; dicts preserve insertion
        # order, which makes this an LRU without a second data structure.
        del self._entries[key]
        self._entries[key] = value
        self.statistics.hits += 1
        return value

    def put(self, key: str, value: T) -> T:
        if key in self._entries:
            del self._entries[key]
        self._entries[key] = value
        while len(self._entries) > self._capacity:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
            self.statistics.evictions += 1
        return value

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> T:
        existing = self.get(key)
        if existing is not None:
            return existing
        return self.put(key, compute())

    def keys(self) -> Iterator[str]:
        return iter(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self.statistics = CacheStatistics()


__all__ = [
    "CACHE_SCHEME_VERSION",
    "ContentCache",
    "CacheStatistics",
    "content_hash",
    "feature_hash",
]
