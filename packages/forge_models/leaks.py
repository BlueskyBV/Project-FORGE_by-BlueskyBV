"""Fields a model wrote inside another field's string, put back where they go.

Observed on Claude Sonnet 5, on forced tool use, twice in one evening. The
brief interpreter's `stated` came back as one string --

    "\\n<item>Overall shape: 50 mm cube</item>\\n...</stated>\\n<implied>\\n
     <item>...</item>\\n</implied>\\n<unstated>...</unstated>...</invoke>"

-- every later field written inside the first, in the tag form the model
uses for tool calls, and none of them in the input itself. Forge read the
string as a list of 2464 one-character facts, sent them all to the
requirements engineer, and had no unknowns at all. The failure analyst did
the same with `</diagnosis>\\n<parameter name="strategy">...`.

So each top-level string is cut where it closes itself or opens a field the
schema names, and every field found after that point is put back as its own
value, converted to the type the schema gives it, if the input does not
already carry it. A string where the schema wants a list is read as its
`<item>` elements, or its lines. Nothing is invented: only text the model
wrote is moved, and only into fields the schema has.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

_ITEM = re.compile(r"<item>(.*?)</item>", re.S)


def _as(kind: Any, text: str, items: Any = None) -> Any:
    """`text` as a value of the schema type `kind`, or None.

    `items` is the schema of an array's items. A list of objects -- a failure
    analyst's `patches` -- is only ever read as JSON: split into lines, as a
    list of strings is, it became a list of fragments of JSON, and the first
    one reached as a patch took the run down with an internal error."""
    text = text.strip()
    types = kind if isinstance(kind, list) else [kind]
    if "array" in types:
        wants_objects = isinstance(items, Mapping) and (
            items.get("type") == "object" or "properties" in items)
        try:
            value = json.loads(text)
            if isinstance(value, list):
                return value
            if wants_objects and isinstance(value, dict):
                return [value]
        except ValueError:
            pass
        found = [m.strip() for m in _ITEM.findall(text)]
        if wants_objects:
            objects = []
            for piece in found:
                try:
                    value = json.loads(piece)
                except ValueError:
                    return None
                if not isinstance(value, dict):
                    return None
                objects.append(value)
            return objects or None
        if found:
            return found
        return [line.strip(" -*\t") for line in text.splitlines()
                if line.strip(" -*\t")]
    if "boolean" in types:
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        return None
    if "number" in types or "integer" in types:
        try:
            number = float(text)
        except ValueError:
            return None
        if "integer" in types and number.is_integer():
            return int(number)
        return number
    if "object" in types:
        try:
            value = json.loads(text)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None
    return text


def recover_leaked_fields(structured: Any, schema: Any) -> Any:
    """`structured` with fields written inside other fields' strings put
    back as fields, and strings the schema wants as lists made lists."""
    if not isinstance(structured, Mapping) or not isinstance(schema, Mapping):
        return structured
    properties = schema.get("properties") or {}
    if not isinstance(properties, Mapping) or not properties:
        return structured
    names = [n for n in properties if re.fullmatch(r"[A-Za-z_]\w*", str(n))]
    if not names:
        return structured
    alternatives = "|".join(re.escape(n) for n in names)
    opening = re.compile(r"<parameter\s+name=\"(" + alternatives
                         + r")\">|<(" + alternatives + r")>")
    out = dict(structured)
    recovered: dict[str, str] = {}
    # The other form: the string closed and the JSON carried on inside it --
    # `...the redesign.", "strategy": "Abandon", "patches": []` -- with the
    # model's own `\\n` escapes left in as text. Seen in a failure
    # analyst's `abandon_reason`.
    continuing = re.compile(r'"\s*,\s*"(' + alternatives + r')"\s*:')
    values: dict[str, Any] = {}
    for key, value in structured.items():
        if not isinstance(value, str):
            continue
        m = continuing.search(value)
        if not m:
            continue
        tail = value[m.start() + 1:].lstrip(" ,\n")
        parsed = None
        for candidate in ("{" + tail, "{" + tail + "}", "{" + tail + "]}"):
            try:
                parsed = json.loads(candidate)
                break
            except ValueError:
                continue
        head = value[:m.start()]
        if '\\n' in head or '\\"' in head:
            head = head.replace('\\n', "\n").replace('\\"', '"')
        out[key] = head.rstrip()
        if isinstance(parsed, dict):
            for name, item in parsed.items():
                if name in properties and name != key:
                    values.setdefault(name, item)
    for name, item in values.items():
        if out.get(name) in (None, "", [], {}):
            out[name] = item
    structured = dict(out)
    for key, value in structured.items():
        if not isinstance(value, str) or "<" not in value:
            continue
        cut = len(value)
        closing = value.find(f"</{key}>")
        if closing >= 0:
            cut = closing
        first = opening.search(value)
        if first and first.start() < cut:
            cut = first.start()
        if cut == len(value):
            continue
        rest = value[cut:]
        for m in opening.finditer(rest):
            name = m.group(1) or m.group(2)
            start = m.end()
            ends = [i for i in (rest.find("</parameter>", start),
                                rest.find(f"</{name}>", start),
                                rest.find("</invoke>", start)) if i >= 0]
            later = opening.search(rest, start)
            if later:
                ends.append(later.start())
            end = min(ends) if ends else len(rest)
            recovered.setdefault(name, rest[start:end])
        out[key] = value[:cut].rstrip()
    for name, text in recovered.items():
        if out.get(name) not in (None, "", [], {}):
            continue
        spec = properties.get(name)
        converted = _as(spec.get("type") if isinstance(spec, Mapping)
                        else None, text,
                        spec.get("items") if isinstance(spec, Mapping) else None)
        if converted is not None:
            out[name] = converted
    for key, value in list(out.items()):
        spec = properties.get(key)
        kind = spec.get("type") if isinstance(spec, Mapping) else None
        if isinstance(value, str) and (kind == "array" or (
                isinstance(kind, list) and "array" in kind)):
            converted = _as("array", value, spec.get("items"))
            if converted is not None:
                out[key] = converted
    return out


__all__ = ["recover_leaked_fields"]
