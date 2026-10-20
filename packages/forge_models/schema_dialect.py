"""Reducing a JSON Schema to the subset a given endpoint will actually accept.

Forge's document schema is generated from the feature table, so it is large
(about 45 KB), deeply nested (22 levels) and uses the full JSON Schema
vocabulary -- ``oneOf`` across 22 feature branches, ``const`` discriminators,
``additionalProperties: false`` to refuse invented fields. The Anthropic
Messages API takes it verbatim.

Not every endpoint does. Several accept "a subset of the OpenAPI schema" and
reject the rest with a bare 400, and some reject a schema merely for being large
or deeply nested. An adapter that hits this has two honest options: fail, or send
less schema and say so.

This module is the second option, and the "say so" is the important half. A
reduction is never silent: :class:`ReducedSchema` records every keyword that was
dropped and every subschema that was collapsed, the provider reports a
``schema_fidelity`` other than ``exact``, and that lands in the run log.

**Reducing the schema does not reduce what is checked.** The transport schema is
a convenience that makes the model's first attempt more likely to be right; the
actual contract is enforced afterwards, locally, by the decoder and the compiler,
neither of which knows or cares what the endpoint promised. A reduced schema
means more repair attempts, not weaker verification -- which is exactly the
trade a smaller endpoint should be allowed to make.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

#: ``json_schema`` sends the schema as written. ``openapi`` keeps only keywords
#: in the widely-supported OpenAPI 3.0 subset. ``opaque`` additionally collapses
#: unions and deep nesting, for endpoints that reject large schemas outright.
SchemaDialect = Literal["json_schema", "openapi", "opaque"]

#: Keywords kept by the ``openapi`` dialect. Deliberately conservative: these
#: are the ones every OpenAPI-subset endpoint documents support for, and a
#: keyword that is merely *probably* fine is not worth a 400 the user has to
#: diagnose.
_OPENAPI_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "description",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "nullable",
        "anyOf",
    }
)

_UNION_KEYWORDS = ("oneOf", "anyOf", "allOf")


@dataclass(frozen=True, slots=True)
class ReducedSchema:
    """A schema as it will be sent, and an account of what changed."""

    schema: Mapping[str, Any]
    dialect: SchemaDialect
    #: Keyword names removed, sorted and de-duplicated.
    dropped: tuple[str, ...] = ()
    #: Subschemas replaced by an unconstrained object.
    collapsed: int = 0
    original_bytes: int = 0
    sent_bytes: int = 0

    @property
    def lossless(self) -> bool:
        return not self.dropped and not self.collapsed

    @property
    def fidelity(self) -> str:
        """One word for the run log."""
        if self.lossless:
            return "exact"
        return "collapsed" if self.collapsed else "reduced"

    def as_dict(self) -> dict[str, Any]:
        return {
            "dialect": self.dialect,
            "fidelity": self.fidelity,
            "dropped_keywords": list(self.dropped),
            "collapsed_subschemas": self.collapsed,
            "original_bytes": self.original_bytes,
            "sent_bytes": self.sent_bytes,
        }

    def note(self) -> str:
        """A sentence for a human, or empty when nothing was lost."""
        if self.lossless:
            return ""
        parts = []
        if self.dropped:
            parts.append("dropped " + ", ".join(self.dropped))
        if self.collapsed:
            parts.append(f"collapsed {self.collapsed} subschema(s)")
        return (
            f"the schema was reduced for this endpoint ({'; '.join(parts)}); "
            f"{self.original_bytes} bytes became {self.sent_bytes}. The full "
            "contract is still enforced locally after the answer arrives."
        )


def reduce_schema(
    schema: Mapping[str, Any],
    dialect: SchemaDialect = "json_schema",
    *,
    max_depth: int = 6,
) -> ReducedSchema:
    """Reduce ``schema`` to what ``dialect`` permits, recording what was lost."""
    original = json.dumps(dict(schema))
    if dialect == "json_schema":
        return ReducedSchema(
            schema=schema,
            dialect=dialect,
            original_bytes=len(original),
            sent_bytes=len(original),
        )

    state = _State(collapse=dialect == "opaque", max_depth=max_depth)
    reduced = _reduce(schema, state, depth=0)
    sent = json.dumps(reduced)
    return ReducedSchema(
        schema=reduced,
        dialect=dialect,
        dropped=tuple(sorted(state.dropped)),
        collapsed=state.collapsed,
        original_bytes=len(original),
        sent_bytes=len(sent),
    )


@dataclass(slots=True)
class _State:
    collapse: bool
    max_depth: int
    dropped: set[str] = None  # type: ignore[assignment]
    collapsed: int = 0

    def __post_init__(self) -> None:
        if self.dropped is None:
            self.dropped = set()


def _opaque(description: Any) -> dict[str, Any]:
    """What a collapsed subschema becomes: an object with no constraints.

    The description survives, because it is the only thing left telling the
    model what belongs there -- and by this point the prompt's authoring guide
    is doing most of that work anyway.
    """
    node: dict[str, Any] = {"type": "object"}
    if isinstance(description, str) and description:
        node["description"] = description
    return node


def _reduce(node: Any, state: _State, *, depth: int) -> Any:
    """Reduce one schema node.

    The distinction that matters: some keys hold *subschemas* and must be
    recursed into, some hold *names or values* and must be copied through. A
    reducer that filters the keys of ``properties`` deletes the document's
    fields rather than the schema's keywords -- which is a 45 KB schema becoming
    91 bytes, and every field the model was told about disappearing.
    """
    if not isinstance(node, Mapping):
        return node

    if state.collapse and depth > state.max_depth and (
            "properties" in node or "items" in node
            or node.get("type") in ("object", "array")
            or any(key in node for key in ("oneOf", "anyOf", "allOf"))):
        # Only something with structure collapses to an opaque object. A
        # string or a number past the depth limit was being sent as an
        # object too, so a model following the sent schema wrote `{}` where
        # a number belonged and failed the full contract locally.
        state.collapsed += 1
        return _opaque(node.get("description"))

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, Mapping):
            out["properties"] = {
                name: _reduce(sub, state, depth=depth + 1)
                for name, sub in value.items()
            }
        elif key == "items":
            out["items"] = _reduce(value, state, depth=depth + 1)
        elif key in ("enum", "required") and isinstance(value, list):
            out[key] = list(value)
        elif key == "const":
            # A discriminator the subset cannot express as such, but can as a
            # one-value enum, which is the same constraint.
            out["enum"] = [value]
        elif key in _UNION_KEYWORDS and isinstance(value, list):
            if state.collapse:
                state.collapsed += 1
                state.dropped.add(key)
                return _opaque(node.get("description"))
            if key == "allOf":
                state.dropped.add("allOf")
                continue
            if key == "oneOf":
                state.dropped.add("oneOf->anyOf")
            out["anyOf"] = [
                _reduce(branch, state, depth=depth + 1) for branch in value
            ]
        elif key in _OPENAPI_KEYWORDS:
            out[key] = value
        else:
            state.dropped.add(key)

    # A node that lost everything still has to say what it is, or a strict
    # endpoint rejects the empty schema.
    if not out:
        return {"type": "object"}
    if "properties" in out and "type" not in out:
        out["type"] = "object"
    if "items" in out and "type" not in out:
        out["type"] = "array"
    return out


__all__ = ["SchemaDialect", "ReducedSchema", "reduce_schema"]
