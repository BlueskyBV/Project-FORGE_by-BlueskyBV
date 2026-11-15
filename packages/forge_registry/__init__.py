"""forge_registry - one dispatch mechanism for every domain (V2-stage4b-0b.md, 3).

A program that does one thing per kind of item, per pattern mode, and later
per load type, solver, mesher, file format or derived product (item 26),
asks a :class:`Registry`: the entry for a key, never a chain of tests on
it. A registry is built from its domain's keys and an entry for each, in
the keys' order, so every aggregate made by walking it keeps that order;
it refuses a key with no entry and an entry with no key, so a domain is
total by construction. Its entries are imported by name where it is made
(no discovery at run time), and each says which key it is for.

A method a later stage will fill is marked :func:`reserved` on the
domain's protocol, with the step that fills it: calling it raises
:class:`NotYetError`, and :meth:`Registry.reserved` lists what is still
reserved, entry by entry, for the domain's totality test. A slot whose
domain has no entries yet (a later stage's) is its protocol alone, and
:func:`reserved_in` lists what is reserved on it.

>>> class Shape:
...     key = ""
...     def area(self) -> float:
...         raise NotImplementedError
...     @reserved("4b.0d")
...     def roles(self) -> tuple[str, ...]: ...
>>> class Square(Shape):
...     key = "square"
...     def area(self) -> float:
...         return 4.0
>>> shapes = Registry("shapes", ["square"], [Square()], protocol=Shape)
>>> shapes["square"].area()
4.0
>>> shapes.reserved()
[('square', 'roles', '4b.0d')]
>>> try:
...     shapes["circle"]
... except RegistryError as error:
...     print(error)
the shapes registry has no entry for 'circle'

Only the standard library is used: this is the trust core (L0).
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Generic, TypeVar

__all__ = ["NotYetError", "Registry", "RegistryError", "reserved", "reserved_in"]

E = TypeVar("E")
F = TypeVar("F", bound=Callable[..., Any])

#: The attribute a reserved method carries: the step that fills it.
_RESERVED = "__forge_reserved__"


class RegistryError(KeyError):
    """A registry asked for a key it hasn't, or made with a key and its entry not matching."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class NotYetError(NotImplementedError):
    """A reserved method was called before the step that fills it."""


def reserved(step: str) -> Callable[[F], F]:
    """Mark a protocol's method as reserved for ``step``: named and owned now, filled then."""

    def mark(method: F) -> F:
        @functools.wraps(method)
        def not_yet(self: Any, *args: Any, **kwargs: Any) -> Any:
            raise NotYetError(
                f"{type(self).__name__}.{method.__name__} is reserved, not yet filled: {step}"
            )

        setattr(not_yet, _RESERVED, step)
        return not_yet  # type: ignore[return-value]

    return mark


def reserved_in(protocol: type) -> list[tuple[str, str]]:
    """Every method still reserved on ``protocol``, as (method, the step that fills it), by name."""
    found: list[tuple[str, str]] = []
    for name in sorted(dir(protocol)):
        step = getattr(getattr(protocol, name, None), _RESERVED, None)
        if step is not None:
            found.append((name, step))
    return found


class Registry(Generic[E]):
    """A domain's entries, one for each of its keys, in the keys' order.

    ``entries`` each carry their own ``key`` attribute (or are given as a
    mapping by key); ``protocol``, when given, is the class every entry is
    an instance of. A key without an entry, an entry without a key, an
    entry given twice and a key given twice are all refused.
    """

    __slots__ = ("_entries", "domain", "protocol")

    def __init__(
        self,
        domain: str,
        keys: Iterable[str],
        entries: Iterable[E] | dict[str, E],
        *,
        protocol: type | None = None,
    ) -> None:
        self.domain = domain
        self.protocol = protocol
        order = tuple(keys)
        twice = sorted({k for k in order if order.count(k) > 1})
        if twice:
            raise RegistryError(f"the {domain} registry's keys repeat: {twice}")
        given: dict[str, E] = {}
        if isinstance(entries, dict):
            given = dict(entries)
        else:
            for entry in entries:
                key = getattr(entry, "key", None)
                if not isinstance(key, str) or not key:
                    raise RegistryError(f"a {domain} entry names no key: {entry!r}")
                if key in given:
                    raise RegistryError(
                        f"the {domain} registry has two entries for {key!r}"
                    )
                given[key] = entry
        missing = [k for k in order if k not in given]
        extra = sorted(k for k in given if k not in order)
        if missing or extra:
            said = [f"no entry for {missing}"] if missing else []
            said += [f"entries for no key {extra}"] if extra else []
            raise RegistryError(f"the {domain} registry has {' and '.join(said)}")
        if protocol is not None:
            wrong = [k for k in order if not isinstance(given[k], protocol)]
            if wrong:
                raise RegistryError(
                    f"the {domain} registry's entries for {wrong} aren't {protocol.__name__}s"
                )
        self._entries: dict[str, E] = {k: given[k] for k in order}

    def __getitem__(self, key: str) -> E:
        try:
            return self._entries[key]
        except KeyError:
            raise RegistryError(
                f"the {self.domain} registry has no entry for {key!r}"
            ) from None

    def get(self, key: str, default: E | None = None) -> E | None:
        return self._entries.get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def keys(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def values(self) -> tuple[E, ...]:
        return tuple(self._entries.values())

    def items(self) -> tuple[tuple[str, E], ...]:
        return tuple(self._entries.items())

    def reserved(self) -> list[tuple[str, str, str]]:
        """Every method still reserved, as (key, method, the step that fills it), in the keys' order."""
        return [
            (key, name, step)
            for key, entry in self._entries.items()
            for name, step in reserved_in(type(entry))
        ]

    def __repr__(self) -> str:
        return f"Registry({self.domain!r}, {len(self._entries)} entries)"
