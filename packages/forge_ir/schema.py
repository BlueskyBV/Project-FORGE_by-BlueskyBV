"""A small typed-decoding framework with exact error locations.

Forge does not use a general-purpose validation library for the document model.
That is a deliberate choice, recorded in ADR-0002, and it rests on three
requirements that general libraries meet awkwardly:

**Error paths must be RFC 6901 JSON Pointers.** When a language model emits an
invalid document, the Failure Analyst is given the pointer to the exact offending
node -- ``/components/0/features/3/parameters/radius`` -- and can repair that
subtree without being shown, or being able to corrupt, the rest of the document.
A message like "validation error in features" is not actionable.

**Decoding must be total and explicit.** Every field is read through a function
that states its type, its default, and whether it is required. There is no
coercion: a string where a number belongs is an error, not a silent ``float()``
call, because silent coercion is how a unit-less magnitude sneaks past.

**The trust core must have no third-party dependencies.** Everything that makes
a numeric claim about a design bottoms out in this package, so its dependency
surface is the standard library and nothing else.

The framework is a reader, not a schema language: :class:`Reader` wraps a JSON
value and a pointer, and hands out typed accessors that extend the pointer as
they descend. A JSON Schema is *generated* from the dataclasses for external
consumers (see :mod:`forge_ir.jsonschema`); it is not the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, Sequence, TypeVar

T = TypeVar("T")


class SchemaError(Exception):
    """A document failed to decode.

    Carries a JSON Pointer to the offending location, so the message is
    actionable by a human and by a repair strategy.
    """

    code = "IR1000_SCHEMA"

    def __init__(
        self,
        message: str,
        *,
        pointer: str = "",
        code: str | None = None,
        **detail: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.pointer = pointer
        if code is not None:
            self.code = code
        self.detail: dict[str, Any] = dict(detail)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "pointer": self.pointer,
            "detail": dict(self.detail),
        }

    def __str__(self) -> str:
        location = self.pointer or "<root>"
        rendered = f"[{self.code}] {location}: {self.message}"
        if self.detail:
            rendered += (
                " (" + ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items())) + ")"
            )
        return rendered


class MissingFieldError(SchemaError):
    code = "IR1001_MISSING_FIELD"


class TypeMismatchError(SchemaError):
    code = "IR1002_TYPE_MISMATCH"


class UnknownFieldError(SchemaError):
    code = "IR1003_UNKNOWN_FIELD"


class ValueRangeError(SchemaError):
    code = "IR1004_VALUE_RANGE"


class DuplicateIdentifierError(SchemaError):
    code = "IR1005_DUPLICATE_ID"


class DanglingReferenceError(SchemaError):
    code = "IR1006_DANGLING_REFERENCE"


class SchemaErrorGroup(SchemaError):
    """Several independent decoding failures, reported together.

    Returning one error at a time turns document repair into a slow game of
    whack-a-mole, especially when the author is a language model paying for
    every round trip. The decoder collects sibling errors where it safely can
    and raises them as a group.
    """

    code = "IR1007_MULTIPLE"

    def __init__(self, errors: Sequence[SchemaError]) -> None:
        self.errors = tuple(errors)
        summary = f"{len(self.errors)} validation errors"
        super().__init__(summary, pointer="")

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "errors": [error.as_dict() for error in self.errors],
        }

    def __str__(self) -> str:
        lines = [f"[{self.code}] {self.message}:"]
        lines.extend(f"  - {error}" for error in self.errors)
        return "\n".join(lines)


def escape_token(token: str) -> str:
    """Escape a JSON Pointer reference token per RFC 6901."""
    return token.replace("~", "~0").replace("/", "~1")


def join_pointer(pointer: str, token: str | int) -> str:
    return f"{pointer}/{escape_token(str(token))}"


@dataclass(frozen=True, slots=True)
class Reader:
    """A JSON value together with the pointer at which it was found."""

    value: Any
    pointer: str = ""

    # ------------------------------------------------------------------
    # Object access
    # ------------------------------------------------------------------
    def as_object(self) -> Mapping[str, Any]:
        if not isinstance(self.value, Mapping):
            raise TypeMismatchError(
                "expected an object",
                pointer=self.pointer,
                got=_type_name(self.value),
            )
        return self.value

    def child(self, key: str) -> "Reader":
        return Reader(self.as_object().get(key), join_pointer(self.pointer, key))

    def has(self, key: str) -> bool:
        return key in self.as_object()

    def require(self, key: str) -> "Reader":
        obj = self.as_object()
        if key not in obj:
            raise MissingFieldError(
                "required field is absent",
                pointer=join_pointer(self.pointer, key),
                field=key,
                present=sorted(obj.keys())[:30],
            )
        return Reader(obj[key], join_pointer(self.pointer, key))

    def reject_unknown(self, allowed: Sequence[str]) -> None:
        """Strict-mode check: refuse fields outside the allowlist.

        Unknown fields are refused rather than ignored because a misspelled
        field that is silently dropped is the worst outcome available: the
        document looks accepted and the intent is gone. The ``x_`` prefix is
        reserved for forward-compatible extensions and is always permitted.
        """
        allowed_set = set(allowed)
        unknown = [
            key
            for key in self.as_object()
            if key not in allowed_set and not key.startswith("x_")
        ]
        if unknown:
            raise UnknownFieldError(
                "unknown field(s); did you mean one of the allowed names?",
                pointer=self.pointer,
                unknown=sorted(unknown),
                allowed=sorted(allowed_set),
            )

    # ------------------------------------------------------------------
    # Scalars
    # ------------------------------------------------------------------
    def as_str(self, *, allowed: Sequence[str] | None = None) -> str:
        if not isinstance(self.value, str):
            raise TypeMismatchError(
                "expected a string", pointer=self.pointer, got=_type_name(self.value)
            )
        if allowed is not None and self.value not in allowed:
            raise ValueRangeError(
                "value is not one of the permitted options",
                pointer=self.pointer,
                got=self.value,
                allowed=sorted(allowed),
            )
        return self.value

    def as_identifier(self) -> str:
        text = self.as_str()
        if not text:
            raise ValueRangeError(
                "identifier must not be empty", pointer=self.pointer
            )
        if not (text[0].isalpha() or text[0] == "_"):
            raise ValueRangeError(
                "identifier must start with a letter or underscore",
                pointer=self.pointer,
                got=text,
            )
        if not all(char.isalnum() or char in "_-." for char in text):
            raise ValueRangeError(
                "identifier may contain only letters, digits, '_', '-' and '.'",
                pointer=self.pointer,
                got=text,
            )
        return text

    def as_float(
        self, *, minimum: float | None = None, maximum: float | None = None
    ) -> float:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeMismatchError(
                "expected a number", pointer=self.pointer, got=_type_name(self.value)
            )
        number = float(self.value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueRangeError(
                "number must be finite", pointer=self.pointer, got=repr(self.value)
            )
        if minimum is not None and number < minimum:
            raise ValueRangeError(
                "number is below the permitted minimum",
                pointer=self.pointer,
                got=number,
                minimum=minimum,
            )
        if maximum is not None and number > maximum:
            raise ValueRangeError(
                "number is above the permitted maximum",
                pointer=self.pointer,
                got=number,
                maximum=maximum,
            )
        return number

    def as_int(
        self, *, minimum: int | None = None, maximum: int | None = None
    ) -> int:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            # A quantity here is the predictable mistake, not a random one:
            # every worked example writes {"magnitude": .., "unit": ..}, so a
            # count gets wrapped the same way. Naming the fix costs a line and
            # saves a repair round.
            wrapped = isinstance(self.value, Mapping) and "magnitude" in self.value
            hint = (
                'a count is written bare: 4, not {"magnitude": 4, "unit": ""}'
                if wrapped
                else None
            )
            raise TypeMismatchError(
                "expected an integer",
                pointer=self.pointer,
                got=_type_name(self.value),
                **({"hint": hint} if hint else {}),
            )
        if minimum is not None and self.value < minimum:
            raise ValueRangeError(
                "integer is below the permitted minimum",
                pointer=self.pointer,
                got=self.value,
                minimum=minimum,
            )
        if maximum is not None and self.value > maximum:
            raise ValueRangeError(
                "integer is above the permitted maximum",
                pointer=self.pointer,
                got=self.value,
                maximum=maximum,
            )
        return self.value

    def as_bool(self) -> bool:
        if not isinstance(self.value, bool):
            raise TypeMismatchError(
                "expected a boolean",
                pointer=self.pointer,
                got=_type_name(self.value),
            )
        return self.value

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------
    def as_list(self, *, minimum_length: int = 0) -> list["Reader"]:
        if not isinstance(self.value, list):
            raise TypeMismatchError(
                "expected an array", pointer=self.pointer, got=_type_name(self.value)
            )
        if len(self.value) < minimum_length:
            raise ValueRangeError(
                "array is shorter than required",
                pointer=self.pointer,
                length=len(self.value),
                minimum_length=minimum_length,
            )
        return [
            Reader(item, join_pointer(self.pointer, index))
            for index, item in enumerate(self.value)
        ]

    def as_str_list(self) -> list[str]:
        return [item.as_str() for item in self.as_list()]

    def as_float_tuple(self, length: int) -> tuple[float, ...]:
        items = self.as_list()
        if len(items) != length:
            raise ValueRangeError(
                "array has the wrong length",
                pointer=self.pointer,
                expected_length=length,
                got_length=len(items),
            )
        return tuple(item.as_float() for item in items)

    def decode_list(
        self, decoder: Callable[["Reader"], T], *, collect_errors: bool = True
    ) -> list[T]:
        """Decode every element, optionally gathering sibling failures.

        Collecting is the default because an author repairing a document wants
        to see all of its problems at once.
        """
        results: list[T] = []
        errors: list[SchemaError] = []
        for item in self.as_list():
            try:
                results.append(decoder(item))
            except SchemaErrorGroup as group:
                if not collect_errors:
                    raise
                errors.extend(group.errors)
            except SchemaError as error:
                if not collect_errors:
                    raise
                errors.append(error)
        if errors:
            raise SchemaErrorGroup(errors)
        return results

    # ------------------------------------------------------------------
    # Optional access
    # ------------------------------------------------------------------
    def optional(self, key: str) -> "Reader | None":
        obj = self.as_object()
        if key not in obj or obj[key] is None:
            return None
        return Reader(obj[key], join_pointer(self.pointer, key))

    def optional_str(self, key: str, default: str = "") -> str:
        child = self.optional(key)
        return default if child is None else child.as_str()

    def optional_bool(self, key: str, default: bool = False) -> bool:
        child = self.optional(key)
        return default if child is None else child.as_bool()

    def optional_int(self, key: str, default: int = 0, **kwargs: Any) -> int:
        child = self.optional(key)
        return default if child is None else child.as_int(**kwargs)

    def optional_float(self, key: str, default: float = 0.0, **kwargs: Any) -> float:
        child = self.optional(key)
        return default if child is None else child.as_float(**kwargs)

    def optional_str_tuple(self, key: str) -> tuple[str, ...]:
        child = self.optional(key)
        return () if child is None else tuple(child.as_str_list())

    def __iter__(self) -> Iterator[tuple[str, "Reader"]]:
        for key in self.as_object():
            yield key, self.child(key)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def collect(*operations: Callable[[], Any]) -> list[Any]:
    """Run several decode steps, reporting every failure rather than the first."""
    results: list[Any] = []
    errors: list[SchemaError] = []
    for operation in operations:
        try:
            results.append(operation())
        except SchemaErrorGroup as group:
            errors.extend(group.errors)
            results.append(None)
        except SchemaError as error:
            errors.append(error)
            results.append(None)
    if errors:
        raise SchemaErrorGroup(errors)
    return results


def require_unique_ids(
    identifiers: Sequence[str], *, pointer: str, kind: str
) -> None:
    seen: dict[str, int] = {}
    for index, identifier in enumerate(identifiers):
        if identifier in seen:
            raise DuplicateIdentifierError(
                f"duplicate {kind} identifier",
                pointer=join_pointer(pointer, index),
                identifier=identifier,
                first_seen_at=join_pointer(pointer, seen[identifier]),
            )
        seen[identifier] = index


__all__ = [
    "Reader",
    "SchemaError",
    "SchemaErrorGroup",
    "MissingFieldError",
    "TypeMismatchError",
    "UnknownFieldError",
    "ValueRangeError",
    "DuplicateIdentifierError",
    "DanglingReferenceError",
    "escape_token",
    "join_pointer",
    "collect",
    "require_unique_ids",
]
