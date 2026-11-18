"""Random specs the placement solver accepts, rich enough to exercise every placing rule.

A spec is grown one item at a time: a first body, perhaps hollowed, then items
on faces of what is already there, sized from the face they go on (read from
the solver's layout, which is only a convenience: any spec it accepts is a
fair test). An item the solver turns back is dropped and another tried. Every
kind that is placed, every face, every way of giving a position, every
pattern, positions round a side, concentric items, hollows with their inner
faces and floors, pocket floors, and roundings of hollowed bodies turn up.

The specs test the placements against each other (tests/test_v2_checks_place.py);
nothing here knows where anything should be.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Any

from forge_spec.draft import PartSpec, read_draft
from forge_spec.geometry import BallFace, FlatFace, SideFace
from forge_spec.placement import Layout, solve

WORDS = [0]
SAY = {"assumed": "a random spec"}


def a(value: float, unit: str = "mm") -> dict[str, Any]:
    return {"value": round(value, 3), "unit": unit, "from": SAY}


def n(count: int) -> dict[str, Any]:
    return {"count": count, "from": SAY}


def pick(value: str) -> dict[str, Any]:
    return {"choose": value, "from": SAY}


def draft(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"spec_format": 1, "name": "random", "items": items}


def read(items: list[dict[str, Any]]) -> PartSpec:
    spec, problems = read_draft(draft(items))
    assert spec is not None and not problems.faults, [str(p) for p in problems.faults]
    return spec


def accepted(items: list[dict[str, Any]]) -> tuple[PartSpec, Layout] | None:
    """The spec and its layout, if the reader and the solver take it with no issue."""
    spec, problems = read_draft(draft(items))
    if spec is None or problems.faults:
        return None
    layout = solve(spec)
    return None if layout.issues else (spec, layout)


def _first_body(rng: random.Random) -> dict[str, Any]:
    kind = rng.choice(["block"] * 4 + ["cylinder"] * 2 + ["tube", "cone", "sphere"])
    item: dict[str, Any] = {"id": "body", "kind": kind, "words": WORDS}
    if kind == "block":
        item.update(
            length=a(rng.uniform(30, 120)),
            width=a(rng.uniform(20, 90)),
            height=a(rng.uniform(4, 40)),
        )
    elif kind in ("cylinder", "tube", "cone"):
        d = rng.uniform(20, 80)
        if kind == "cylinder":
            item["diameter"] = a(d)
        elif kind == "tube":
            item.update(
                outer_diameter=a(d), inner_diameter=a(d * rng.uniform(0.3, 0.8))
            )
        else:
            top = rng.choice(
                [0.0, d * rng.uniform(0.2, 0.9), d * rng.uniform(1.1, 1.6)]
            )
            item.update(base_diameter=a(d), top_diameter=a(top))
        item["length"] = a(rng.uniform(10, 80))
        if rng.random() < 0.7:
            item["axis"] = pick(rng.choice("xyz"))
    else:
        item.update(
            diameter=a(rng.uniform(20, 80)),
            portion=pick(rng.choice(["whole", "upper_half"])),
        )
    return item


def _shell(rng: random.Random, body: dict[str, Any]) -> dict[str, Any] | None:
    kind = body["kind"]
    if kind not in ("block", "cylinder", "sphere"):
        return None
    sizes = [
        v["value"] for k, v in body.items() if isinstance(v, dict) and "value" in v
    ]
    t = min(sizes) * rng.uniform(0.05, 0.2)
    shell: dict[str, Any] = {
        "id": "hollow",
        "kind": "shell",
        "words": WORDS,
        "of": "body",
        "thickness": a(t),
    }
    if kind == "block":
        faces = rng.sample(
            ["+x", "-x", "+y", "-y", "+z", "-z"], rng.choice([0, 1, 1, 1, 2])
        )
    elif kind == "cylinder":
        faces = rng.sample(["+end", "-end"], rng.choice([0, 1, 1]))
    elif body["portion"]["choose"] == "upper_half":
        faces = rng.sample(["-end"], rng.choice([0, 1]))
    else:
        faces = []
    shell["open"] = {"faces": sorted(faces), "from": SAY}
    opposite = {"+end": "-end", "-end": "+end"}
    floored = (kind in ("block", "cylinder") and any(
        (opposite.get(f) or ("-" if f[0] == "+" else "+") + f[1]) not in faces for f in faces
    )) or (kind == "sphere" and body["portion"]["choose"] == "upper_half" and not faces)  # fmt: skip
    if floored and rng.random() < 0.5:
        shell["floor"] = a(t * rng.uniform(0.6, 2.0))
    return shell


def _position(
    rng: random.Random, axis: str, half: float, reach: float, *, edge_ok: bool = True
) -> dict[str, Any] | None:
    mode = rng.choice(["none", "centred", "offset", "side", "side", "side"])
    if mode == "none":
        return None
    if mode == "centred":
        return {"centred": SAY}
    room = max(half - reach, 0.0)
    if mode == "offset":
        return {"offset": a(rng.uniform(-room, room))}
    to = (
        rng.choice(["centre", "edge", None])
        if edge_ok
        else rng.choice(["centre", None])
    )
    distance = (
        rng.uniform(0.0, max(room * 1.6, 0.01))
        if to == "edge"
        else rng.uniform(reach, max(reach, 2 * half - reach))
    )
    found: dict[str, Any] = {
        "side": rng.choice([f"+{axis}", f"-{axis}"]),
        "distance": a(distance),
    }
    if to is not None:
        found["to"] = to
    return found


def _flat_place(
    rng: random.Random, face: FlatFace, reach: tuple[float, float], partners: list[str]
) -> dict[str, Any]:
    a1, a2 = face.axes
    h1, h2 = face.half
    place: dict[str, Any] = {}
    roll = rng.random()
    if partners and roll < 0.12:
        return {"concentric": {"item": rng.choice(partners), "from": SAY}}
    pattern: dict[str, Any] | None = None
    if roll < 0.55:
        kind = rng.choice(
            ["corners", "rectangle", "ends", "row", "grid", "circle", "arc"]
        )
        if kind == "corners" and face.shape == "rect":
            pattern = {
                "corners": {
                    f"inset_{a1}": a(rng.uniform(reach[0], h1)),
                    f"inset_{a2}": a(rng.uniform(reach[1], h2)),
                }
            }
        elif kind == "rectangle":
            pattern = {
                "rectangle": {
                    a1: a(rng.uniform(2 * reach[0], 2 * h1)),
                    a2: a(rng.uniform(2 * reach[1], 2 * h2)),
                }
            }
        elif kind == "ends" and face.shape == "rect":
            along = rng.choice([a1, a2])
            k = 0 if along == a1 else 1
            pattern = {
                "ends": {
                    "axis": pick(along),
                    "inset": a(rng.uniform(reach[k], (h1, h2)[k])),
                }
            }
        elif kind == "row":
            along = rng.choice([a1, a2])
            k = 0 if along == a1 else 1
            count = rng.randint(2, 5)
            pitch = rng.uniform(
                2 * reach[k], max(2 * reach[k], 2 * (h1, h2)[k] / count)
            )
            pattern = {
                "row": {"axis": pick(along), "count": n(count), "pitch": a(pitch)}
            }
        elif kind == "grid":
            c1, c2 = rng.randint(1, 4), rng.randint(1, 4)
            pattern = {"grid": {f"count_{a1}": n(c1), f"count_{a2}": n(c2),
                                f"pitch_{a1}": a(rng.uniform(2 * reach[0], max(2 * reach[0], 2 * h1 / c1))),
                                f"pitch_{a2}": a(rng.uniform(2 * reach[1], max(2 * reach[1], 2 * h2 / c2)))}}  # fmt: skip
        elif kind in ("circle", "arc"):
            count = rng.randint(2, 8)
            body: dict[str, Any] = {
                "count": n(count),
                "diameter": a(
                    rng.uniform(2 * max(reach), max(2 * max(reach), 1.6 * min(h1, h2)))
                ),
            }
            if rng.random() < 0.6:
                body["start"] = a(
                    rng.choice([0, 15, 30, 45, 90, rng.uniform(-180, 180)]), "deg"
                )
            if kind == "arc":
                body["step"] = a(
                    rng.choice([30, 45, 60, 90, rng.uniform(10, 120)]), "deg"
                )
            pattern = {kind: body}
    if pattern is not None:
        place["pattern"] = pattern
    chosen = next(iter(pattern)) if pattern else None
    for k, axis in enumerate((a1, a2)):
        if chosen == "corners" or (
            chosen == "ends" and pattern and pattern["ends"]["axis"]["choose"] == axis
        ):
            continue
        position = _position(
            rng, axis, (h1, h2)[k], reach[k], edge_ok=chosen not in ("circle", "arc")
        )
        if position is not None:
            place[axis] = position
    return place


def _feature_on_flat(
    rng: random.Random, face: FlatFace, item_id: str, partners: list[str]
) -> dict[str, Any]:
    """An item on a flat face, sized to it."""
    a1, a2 = face.axes
    small = max(min(face.half), 0.5)
    material = max(face.depth_below, 0.5)
    kind = rng.choice(["hole"] * 5 + ["slot", "pocket", "pocket", "boss", "boss", "post", "post", "tab", "rib",
                       "region", "block", "cylinder", "tube", "cone", "sphere", "text"])  # fmt: skip
    item: dict[str, Any] = {"id": item_id, "kind": kind, "words": WORDS}
    size = small * rng.uniform(0.05, 0.35)
    reach = (size / 2, size / 2)

    def depth() -> dict[str, Any]:
        if rng.random() < 0.4:
            return {"through": True, "from": SAY}
        return a(material * rng.uniform(0.1, 0.8))

    if kind == "hole":
        if rng.random() < 0.2:
            screw = rng.choice(["M2", "M3", "M4", "M5", "M6"])
            fit = rng.choice(["clearance", "tapped"])
            item["diameter"] = {"fit": fit, "for": screw, "from": SAY}
            if fit == "clearance":
                item["diameter"]["grade"] = rng.choice(["fine", "normal", "coarse"])
            size = {"M2": 2.6, "M3": 3.6, "M4": 4.8, "M5": 5.8, "M6": 7.0}[screw]
        else:
            item["diameter"] = a(size)
        item["depth"] = depth()
        extra = rng.random()
        if extra < 0.15:
            item["counterbore"] = {
                "diameter": a(size * 1.8),
                "depth": a(material * 0.05),
            }
            size *= 1.8
        elif extra < 0.3:
            item["countersink"] = {"diameter": a(size * 1.8), "angle": a(90, "deg")}
            size *= 1.8
        reach = (size / 2, size / 2)
    elif kind == "slot":
        width = size * 0.6
        length = width * rng.uniform(1.0, 3.0)
        along = rng.choice([a1, a2])
        item.update(
            width=a(width),
            length=a(length),
            along=pick(along),
            ends=pick(rng.choice(["round", "square"])),
            depth=depth(),
        )
        reach = (length / 2, width / 2) if along == a1 else (width / 2, length / 2)
    elif kind == "pocket":
        if rng.random() < 0.3:
            item.update(shape=pick("circle"), diameter=a(size))
        else:
            length, width = size * rng.uniform(0.6, 1.4), size * rng.uniform(0.6, 1.4)
            item.update(shape=pick("rectangle"), length=a(length), width=a(width))
            if rng.random() < 0.5:
                item["corner_radius"] = a(
                    min(length, width) / 2 * rng.uniform(0.1, 1.0)
                )
            reach = (length / 2, width / 2)
        item["depth"] = depth()
    elif kind == "text":
        item.update(text={"text": rng.choice(["A", "FORGE", "v2", "Hi 7"]), "from": SAY}, height=a(size * 0.4),
                    depth=a(min(material * 0.3, 1.0)), mode=pick(rng.choice(["engrave", "emboss"])))  # fmt: skip
        reach = (size, size * 0.2)
    elif kind in ("boss", "cylinder", "sphere"):
        item["diameter"] = a(size)
        if kind == "boss":
            item["height"] = a(rng.uniform(1, 20))
        elif kind == "cylinder":
            item["length"] = a(rng.uniform(1, 20))
        else:
            item["portion"] = pick(rng.choice(["whole", "upper_half"]))
    elif kind == "tube":
        item.update(
            outer_diameter=a(size),
            inner_diameter=a(size * rng.uniform(0.3, 0.8)),
            length=a(rng.uniform(1, 20)),
        )
    elif kind == "cone":
        item.update(
            base_diameter=a(size),
            top_diameter=a(size * rng.choice([0.0, 0.5, 1.4])),
            length=a(rng.uniform(1, 20)),
        )
    elif kind in ("post", "block", "region"):
        length, width = size * rng.uniform(0.5, 1.5), size * rng.uniform(0.5, 1.5)
        item.update(length=a(length), width=a(width), height=a(rng.uniform(1, 20)))
        if kind == "region":
            item["describe"] = {"text": "a handle to hold it by", "from": SAY}
        reach = (length / 2, width / 2)
    elif kind == "tab":
        thin = rng.choice([a1, a2])
        thickness, width = size * 0.3, size
        length = rng.uniform(width / 2, width * 2)
        item.update(length=a(length), width=a(width), thickness=a(thickness), thickness_along=pick(thin),
                    end=pick(rng.choice(["square", "round"])))  # fmt: skip
        reach = (thickness / 2, width / 2) if thin == a1 else (width / 2, thickness / 2)
    elif kind == "rib":
        along = rng.choice([a1, a2])
        length, thickness = size * 1.5, size * 0.2
        item.update(
            length=a(length),
            thickness=a(thickness),
            height=a(rng.uniform(1, 15)),
            along=pick(along),
        )
        reach = (
            (length / 2, thickness / 2) if along == a1 else (thickness / 2, length / 2)
        )
    item["place"] = _flat_place(rng, face, reach, partners)
    return item


def _feature_on_side(
    rng: random.Random, side: SideFace, item_id: str
) -> dict[str, Any]:
    """A hole, boss, post, tab or rib round a side."""
    kind = rng.choice(["hole"] * 4 + ["boss", "post", "tab", "rib"])
    item: dict[str, Any] = {"id": item_id, "kind": kind, "words": WORDS}
    size = side.radius * rng.uniform(0.1, 0.6)
    axis = side.axis
    if kind == "hole":
        item.update(
            diameter=a(size),
            depth={"through": True, "from": SAY}
            if rng.random() < 0.5
            else a(side.wall * 0.5),
        )
        if rng.random() < 0.15:
            item["countersink"] = {"diameter": a(size * 1.5), "angle": a(90, "deg")}
        angle = rng.choice([0, 90, 180, 270, rng.uniform(0, 360)])
    else:
        angle = rng.choice([0, 90, 180, 270, -90, 450])
        zero, quarter = {"z": ("x", "y"), "x": ("y", "z"), "y": ("z", "x")}[axis]
        around = (
            quarter if angle % 180 == 0 else zero
        )  # neither the side's axis nor the way it faces
        if kind == "boss":
            item.update(diameter=a(size), height=a(rng.uniform(1, 10)))
        elif kind == "post":
            item.update(
                length=a(size), width=a(size * 0.8), height=a(rng.uniform(1, 10))
            )
        elif kind == "tab":
            item.update(length=a(size), width=a(size * 0.8), thickness=a(size * 0.3),
                        thickness_along=pick(rng.choice([axis, around])), end=pick(rng.choice(["square", "round"])))  # fmt: skip
        else:
            item.update(length=a(size), thickness=a(size * 0.25), height=a(rng.uniform(1, 10)),
                        along=pick(rng.choice([axis, around])))  # fmt: skip
    place: dict[str, Any] = {"angle": a(angle, "deg")}
    if rng.random() < 0.35:
        pattern = rng.choice(["circle", "arc"])
        body: dict[str, Any] = {"count": n(rng.randint(2, 6))}
        if pattern == "arc":
            body["step"] = a(rng.choice([30, 45, 90, 120]), "deg")
        place["pattern"] = {pattern: body}
    position = _position(rng, axis, side.length / 2, size / 2)
    if position is not None:
        place[axis] = position
    item["place"] = place
    return item


def _faces(layout: Layout) -> list[tuple[str, str, FlatFace | SideFace]]:
    found = []
    for (item_id, index), faces in layout.faces.items():
        if index:
            continue  # the first copy stands for its item: an item goes on every copy
        for name, face in faces.items():
            if isinstance(face, BallFace):
                continue  # a ball's surface (item 3b's second step): its own tests draw on it
            found.append((item_id, name, face))
    return found


def random_spec(rng: random.Random, size: int = 8, tries: int = 6) -> PartSpec:
    """A spec of up to ``size`` items that the solver places with no issue."""
    return read(random_draft(rng, size, tries))


def random_draft(
    rng: random.Random, size: int = 8, tries: int = 6
) -> list[dict[str, Any]]:
    """The items of a spec of up to ``size`` items that the solver places with no issue, as drafted."""
    items = [_first_body(rng)]
    while accepted(items) is None:
        items = [_first_body(rng)]
    if rng.random() < 0.35:
        shell = _shell(rng, items[0])
        if shell is not None and accepted([*items, shell]) is not None:
            items.append(shell)
    for k in range(size):
        result = accepted(items)
        assert result is not None
        _, layout = result
        faces = _faces(layout)
        if not faces:
            break
        for _ in range(tries):
            host, name, face = rng.choice(faces)
            item_id = f"i{k}"
            partners = [i for i in layout.instances if i != item_id]
            if isinstance(face, SideFace):
                new = _feature_on_side(rng, face, item_id)
            else:
                new = _feature_on_flat(rng, face, item_id, partners)
            new["on"] = {"item": host, "face": name}
            if accepted([*items, new]) is not None:
                items.append(new)
                break
    items += _changes(rng, items)
    while accepted(items) is None:
        items.pop()
    return items


def _changes(rng: random.Random, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roundings, chamfers and threads: they place nothing, but they set the order the part is made in."""
    found: list[dict[str, Any]] = []
    sets = {"block": ["vertical", "top", "bottom", "all"], "cylinder": ["top", "bottom", "both"],
            "post": ["vertical", "top"], "boss": ["top"], "tube": ["outer", "bore", "top"]}  # fmt: skip
    for k, item in enumerate(items):
        if item["kind"] in sets and rng.random() < 0.3:
            kind = rng.choice(["fillet", "chamfer"])
            change = {"id": f"r{k}", "kind": kind, "words": WORDS,
                      "edges": {"of": item["id"], "which": rng.choice(sets[item["kind"]])}}  # fmt: skip
            change["radius" if kind == "fillet" else "size"] = a(0.3)
            if accepted([*items, *found, change]) is not None:
                found.append(change)
        if item["kind"] in ("cylinder", "boss") and rng.random() < 0.2:
            thread = {"id": f"t{k}", "kind": "thread", "words": WORDS, "of": item["id"],
                      "designation": {"text": "M8", "from": SAY}, "hand": pick(rng.choice(["right", "left"]))}  # fmt: skip
            if accepted([*items, *found, thread]) is not None:
                found.append(thread)
    return found


def random_drafts(
    seed: int, count: int, size: int = 8
) -> Iterator[list[dict[str, Any]]]:
    """The items of ``count`` random specs, as drafted (the specs :func:`random_specs` gives)."""
    rng = random.Random(seed)
    for _ in range(count):
        yield random_draft(rng, size)


def random_specs(seed: int, count: int, size: int = 8) -> Iterator[PartSpec]:
    rng = random.Random(seed)
    for _ in range(count):
        yield random_spec(rng, size)
