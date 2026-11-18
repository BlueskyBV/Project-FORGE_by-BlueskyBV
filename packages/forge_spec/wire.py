"""A spec back to its wire form: the exact inverse of :func:`forge_spec.draft.read_draft`.

Used to lock a spec (its canonical JSON is what gets hashed), to hand a spec
back to the spec writer for a targeted correction, and to apply the person's
edits as typed changes. ``read_draft(to_wire(spec))`` gives the same spec
back, which a test checks for every kind.
"""

from __future__ import annotations

from typing import Any

from .draft import (
    SPEC_FORMAT,
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    EdgeSet,
    Faces,
    Fit,
    On,
    PartSpec,
    Place,
    Profile,
    Requirements,
    Text,
    Through,
)
from .values import Count, Provenance, Source, Value
from .versions import CURRENT, Version, written

__all__ = ["provenance_to_wire", "to_wire", "value_to_wire"]


def provenance_to_wire(p: Provenance) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if p.words:
        out["words"] = list(p.words)
    if p.source is Source.TABLE:
        out["table"] = p.table
    elif p.source is Source.DERIVED:
        out["formula"] = p.formula
    elif p.source is Source.ASSUMED:
        out["assumed"] = p.reason
    return out


def value_to_wire(v: Value | Count) -> dict[str, Any]:
    if isinstance(v, Count):
        return {"count": v.n, "from": provenance_to_wire(v.provenance)}
    out: dict[str, Any] = {"value": v.nominal, "unit": v.unit}
    if v.tolerance is not None:
        out["tolerance"] = {"plus": v.tolerance.plus, "minus": v.tolerance.minus}
    out["from"] = provenance_to_wire(v.provenance)
    return out


def _axis(position: AxisPosition) -> dict[str, Any]:
    if position.mode == "centred":
        assert position.provenance is not None
        return {"centred": provenance_to_wire(position.provenance)}
    assert position.distance is not None
    if position.mode == "offset":
        return {"offset": value_to_wire(position.distance)}
    out: dict[str, Any] = {
        "side": position.side,
        "distance": value_to_wire(position.distance),
    }
    if position.to_given:
        out["to"] = position.to
    return out


def _place(place: Place) -> dict[str, Any]:
    out: dict[str, Any] = {axis: _axis(pos) for axis, pos in place.axes.items()}
    if place.angle is not None:
        out["angle"] = value_to_wire(place.angle)
    if place.turn is not None:
        out["turn"] = value_to_wire(place.turn)
    if place.latitude is not None:
        out["latitude"] = value_to_wire(place.latitude)
    if place.pattern is not None:
        body: dict[str, Any] = {
            name: value_to_wire(v) for name, v in place.pattern.values.items()
        }
        body.update(
            {name: value_to_wire(c) for name, c in place.pattern.counts.items()}
        )
        if place.pattern.axis is not None and place.pattern.axis_provenance is not None:
            body["axis"] = {
                "choose": place.pattern.axis,
                "from": provenance_to_wire(place.pattern.axis_provenance),
            }
        out["pattern"] = {place.pattern.kind: body}
    if place.concentric is not None:
        con: dict[str, Any] = {"item": place.concentric}
        if place.concentric_provenance is not None:
            con["from"] = provenance_to_wire(place.concentric_provenance)
        out["concentric"] = con
    return out


def _field(value: Any) -> Any:
    if isinstance(value, (Value, Count)):
        return value_to_wire(value)
    if isinstance(value, On):
        return {"item": value.item, "face": value.face}
    if isinstance(value, Choice):
        return {"choose": value.value, "from": provenance_to_wire(value.provenance)}
    if isinstance(value, Text):
        return {"text": value.text, "from": provenance_to_wire(value.provenance)}
    if isinstance(value, Through):
        return {"through": True, "from": provenance_to_wire(value.provenance)}
    if isinstance(value, Fit):
        out = {
            "fit": value.fit,
            "for": value.for_,
            "from": provenance_to_wire(value.provenance),
        }
        if value.grade:
            out["grade"] = value.grade
        return out
    if isinstance(value, Counterbore):
        return {
            "diameter": value_to_wire(value.diameter),
            "depth": value_to_wire(value.depth),
        }
    if isinstance(value, Countersink):
        return {
            "diameter": value_to_wire(value.diameter),
            "angle": value_to_wire(value.angle),
        }
    if isinstance(value, EdgeSet):
        edges: dict[str, Any] = {"of": value.of, "which": value.which}
        if value.where_meets is not None:
            edges["where_meets"] = value.where_meets
        if value.words:
            edges["words"] = list(value.words)
        return edges
    if isinstance(value, Faces):
        return {
            "faces": list(value.faces),
            "from": provenance_to_wire(value.provenance),
        }
    if isinstance(value, Profile):
        segments: list[dict[str, Any]] = []
        for seg in value.segments:
            if seg.centre is None:
                segments.append({"line_to": list(seg.to)})
            else:
                segments.append(
                    {
                        "arc_to": list(seg.to),
                        "centre": list(seg.centre),
                        "clockwise": seg.clockwise,
                    }
                )
        return {"start": list(value.start), "segments": segments, "unit": "mm",
                "from": provenance_to_wire(value.provenance)}  # fmt: skip
    if isinstance(value, Place):
        return _place(value)
    if isinstance(value, str):
        return value
    raise TypeError(f"no wire form for {type(value).__name__}")  # pragma: no cover


def to_wire(spec: PartSpec, version: Version = CURRENT) -> dict[str, Any]:
    """The spec as the JSON a draft is written in: in the current schema version, or in ``version``.

    An earlier version's form is written for a spec locked in it, whose hash
    is of the form it was confirmed in (:mod:`.lock`); 1.0 differs from 1.1
    only in naming its version (``"spec_format": 1``).
    """
    items = []
    for item in spec.items:
        out: dict[str, Any] = {
            "id": item.id,
            "kind": item.kind,
            "words": list(item.words),
        }
        for name, value in item.fields.items():
            out[name] = _field(value)
        items.append(out)
    return {
        **(
            {"spec_format": SPEC_FORMAT}
            if version == (1, 0)
            else {"schema_version": written(version)}
        ),
        "name": spec.name,
        "items": items,
        "not_modelled": [
            {"words": list(e.words), "reason": e.reason} for e in spec.not_modelled
        ],
        "silent": [{"sentence": e.sentence, "reason": e.reason} for e in spec.silent],
        # Given only when there is something to give: a spec without them
        # reads, writes and hashes as it always has.
        **(
            {"requirements": _requirements(spec.requirements)}
            if spec.requirements != Requirements()
            else {}
        ),
    }


def _requirements(requirements: Requirements) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if requirements.material is not None:
        found["material"] = _field(requirements.material)
    return found
