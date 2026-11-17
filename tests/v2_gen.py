"""Random drafts that read without a fault, for property tests of the spec contract.

They cover every item kind, every field type, every position mode and
pattern, every provenance a field may have, tolerances and fits. They are
not meant to make sense as parts (placement may well question them); they are
meant to exercise reading, writing, wording and hashing every shape a draft
can take. Citations all point at the first words of the brief they are used
with, which the reader doesn't check and the spec checks would.
"""

from __future__ import annotations

import random
from typing import Any

from forge_spec.schema import AXES, KINDS, PRESENT, FieldSpec, FieldType

WORDS = [0, 1]


def _provenance(rng: random.Random, allow: tuple[str, ...]) -> dict[str, Any]:
    kind = rng.choice(allow)
    if kind == "words":
        return {"words": list(WORDS)}
    if kind == "assumed":
        return {
            "assumed": rng.choice(
                ["a guess", "typical for printing", "the brief is silent"]
            )
        }
    if kind == "formula":
        return {
            "formula": rng.choice(["2 mm", "3 mm / 2", "10 mm - 4 mm"]),
            "words": list(WORDS),
        }
    return {
        "table": rng.choice(["clearance:M4", "tapped:M5", "bearing:608:width"]),
        "words": list(WORDS),
    }


def length(rng: random.Random, *, positive: bool = True) -> dict[str, Any]:
    value: dict[str, Any] = {
        "value": rng.choice([1, 2.5, 3, 4.25, 7, 10, 12.7, 20, 33.333])
        if positive
        else 0,
        "unit": rng.choice(["mm", "mm", "mm", "cm", "in"]),
        "from": _provenance(rng, ("words", "assumed", "formula", "table")),
    }
    if value["from"].keys() <= {"words"} and rng.random() < 0.3:
        value["tolerance"] = rng.choice(
            [{"plus": 0.1, "minus": 0}, {"plus": 0.05, "minus": 0.05}, {"minus": 0.2}]
        )
    return value


def angle(rng: random.Random) -> dict[str, Any]:
    return {"value": rng.choice([0, 15, 45, 90, 120.5]), "unit": rng.choice(["deg", "rad"]),
            "from": _provenance(rng, ("words", "assumed", "formula"))}  # fmt: skip


def count(rng: random.Random) -> dict[str, Any]:
    return {
        "count": rng.choice([1, 2, 3, 4, 6]),
        "from": _provenance(rng, ("words", "assumed", "formula")),
    }


def stated(rng: random.Random) -> dict[str, Any]:
    return _provenance(rng, ("words", "assumed"))


def choice(rng: random.Random, options: tuple[str, ...]) -> dict[str, Any]:
    return {"choose": rng.choice(options), "from": stated(rng)}


def position(rng: random.Random, axis: str) -> dict[str, Any]:
    mode = rng.choice(["centred", "offset", "side"])
    if mode == "centred":
        return {"centred": stated(rng)}
    if mode == "offset":
        offset = length(rng)
        offset["value"] = -offset["value"] if rng.random() < 0.5 else offset["value"]
        return {"offset": offset}
    return {
        "side": rng.choice(["+", "-"]) + axis,
        "distance": length(rng),
        "to": rng.choice(["centre", "edge"]),
    }


def pattern(rng: random.Random) -> dict[str, Any]:
    kind = rng.choice(["corners", "rectangle", "ends", "row", "grid", "circle", "arc"])
    a1, a2 = rng.sample(AXES, 2)
    body: dict[str, Any] = {}
    if kind == "corners":
        body = {f"inset_{a1}": length(rng), f"inset_{a2}": length(rng)}
    elif kind == "rectangle":
        body = {a1: length(rng), a2: length(rng)}
    elif kind == "ends":
        body = {"inset": length(rng), "axis": choice(rng, AXES)}
    elif kind == "row":
        body = {"pitch": length(rng), "count": count(rng), "axis": choice(rng, AXES)}
    elif kind == "grid":
        body = {f"pitch_{a1}": length(rng), f"count_{a1}": count(rng),
                f"pitch_{a2}": length(rng), f"count_{a2}": count(rng)}  # fmt: skip
    else:
        body = {"count": count(rng)}
        if kind == "arc":
            body["step"] = angle(rng)
        if rng.random() < 0.8:
            body["diameter"] = length(rng)
        if rng.random() < 0.5:
            body["start"] = angle(rng)
    if rng.random() < 0.2:
        body["each"] = count(rng)
    return {kind: body}


def place(rng: random.Random) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if rng.random() < 0.15:
        return {"concentric": {"item": "body", "from": stated(rng)}}
    for axis in rng.sample(AXES, rng.randint(0, 2)):
        out[axis] = position(rng, axis)
    if rng.random() < 0.3:
        out["angle"] = angle(rng)
    if rng.random() < 0.5:
        out["pattern"] = pattern(rng)
    return out


def profile(rng: random.Random) -> dict[str, Any]:
    w, h = rng.choice([(10, 5), (20, 8), (6, 6)])
    segments: list[dict[str, Any]] = [{"line_to": [w, 0]}, {"line_to": [w, h]}]
    if rng.random() < 0.5:
        # A half-circle bulging out of the top; or, clockwise, a quarter-circle
        # dipping into it (from above, so it never reaches the bottom edge, nor
        # turns straight back where it meets the sides: an outline never does).
        dips = rng.random() < 0.5
        centre = [w / 2, h + w / 2] if dips else [w / 2, h]
        segments.append({"arc_to": [0, h], "centre": centre, "clockwise": dips})
    else:
        segments.append({"line_to": [0, h]})
    segments.append({"line_to": [0, 0]})
    return {"start": [0, 0], "segments": segments, "unit": "mm", "from": stated(rng)}


def value_for(rng: random.Random, spec: FieldSpec, kind: str, others: list[str]) -> Any:
    t = spec.type
    if t is FieldType.LENGTH:
        return length(rng)
    if t is FieldType.ANGLE:
        return angle(rng)
    if t is FieldType.COUNT:
        return count(rng)
    if t is FieldType.DEPTH:
        return (
            {"through": True, "from": stated(rng)}
            if rng.random() < 0.4
            else length(rng)
        )
    if t is FieldType.DIAMETER:
        if rng.random() < 0.3:
            fit = rng.choice([("clearance", "M4", "fine"), ("clearance", "M3", None), ("tapped", "M5", None),
                              ("bearing_seat", "608", None)])  # fmt: skip
            out: dict[str, Any] = {"fit": fit[0], "for": fit[1], "from": stated(rng)}
            if fit[2]:
                out["grade"] = fit[2]
            return out
        return length(rng)
    if t is FieldType.ON:
        faces = KINDS[others[0]].faces if others else ()
        return {"item": "body", "face": rng.choice(faces) if faces else "+z"}
    if t is FieldType.ITEM:
        return "body"
    if t is FieldType.CHOICE:
        return choice(rng, spec.choices)
    if t is FieldType.DESIGNATION:
        return {
            "text": rng.choice(["M8", "M8x1", "M3", "M6x0.75"]),
            "from": stated(rng),
        }
    if t is FieldType.TEXT:
        return {
            "text": rng.choice(["FORGE", "M8", "for a bracket", "A-1"]),
            "from": stated(rng),
        }
    if t is FieldType.PLACE:
        return place(rng)
    if t is FieldType.EDGES:
        which = rng.choice(KINDS[others[0]].edges or ("top",)) if others else "top"
        edges: dict[str, Any] = {"of": "body", "which": which}
        if which == "joint":
            edges["where_meets"] = "body"
        if rng.random() < 0.5:
            edges["words"] = list(WORDS)
        return edges
    if t is FieldType.PROFILE:
        return profile(rng)
    if t is FieldType.FACES:
        names = list(KINDS[others[0]].faces[:3]) if others else ["+z"]
        return {
            "faces": sorted(rng.sample(names, rng.randint(0, len(names)))),
            "from": stated(rng),
        }
    if t is FieldType.COUNTERBORE:
        return {"diameter": length(rng), "depth": length(rng)}
    if t is FieldType.COUNTERSINK:
        sink = angle(rng)
        sink["value"], sink["unit"] = rng.choice([82, 90, 100]), "deg"
        return {"diameter": length(rng), "angle": sink}
    raise AssertionError(t)  # pragma: no cover


def random_item(
    rng: random.Random, item_id: str, kind: str, body_kind: str | None
) -> dict[str, Any]:
    spec = KINDS[kind]
    out: dict[str, Any] = {"id": item_id, "kind": kind, "words": list(WORDS)}
    others = [body_kind] if body_kind else []
    choices: dict[str, str] = {}
    for field in spec.fields:
        if field.type is FieldType.CHOICE:
            pass
        if field.only_when is not None:
            other, when = field.only_when
            if when == PRESENT:
                if other not in out:
                    continue
            elif choices.get(other) != when:
                continue
        elif not field.required and rng.random() < 0.4:
            continue
        if field.name == "on" and body_kind is None:
            continue
        value = value_for(rng, field, kind, others)
        if field.type is FieldType.CHOICE:
            choices[field.name] = value["choose"]
        out[field.name] = value
    return out


def random_draft(rng: random.Random) -> dict[str, Any]:
    """A draft of a first body and a few items on it, that reads without a fault."""
    body_kind = rng.choice(
        ["block", "cylinder", "tube", "sphere", "cone", "extrusion", "revolution"]
    )
    items = [random_item(rng, "body", body_kind, None)]
    for k in range(rng.randint(0, 4)):
        kind = rng.choice(
            [k for k in KINDS if KINDS[k].category.value != "body"]
            + ["block", "cylinder"]
        )
        items.append(random_item(rng, f"item{k}", kind, body_kind))
    draft: dict[str, Any] = {
        "schema_version": "1.3",
        "name": rng.choice(["part", "a bracket", "plate 2"]),
        "items": items,
    }
    if rng.random() < 0.5:
        draft["not_modelled"] = [{"words": [2], "reason": "its finish"}]
    if rng.random() < 0.5:
        draft["requirements"] = {
            "material": {
                "text": rng.choice(["PLA", "PETG", "aluminium 6061"]),
                "from": stated(rng),
            }
        }
    if rng.random() < 0.5:
        draft["silent"] = [{"sentence": 0, "reason": "no load case"}]
    return draft
