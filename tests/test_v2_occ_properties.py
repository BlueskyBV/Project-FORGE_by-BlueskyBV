"""V2 stage 3: parameterisations across V1's ranges, built in both kernels and agreeing (docs/V2-stage3.md, 14).

The golden clevis at the corners of its two optimisable ranges (ear
thickness 4 to 10 mm, root blend 0.5 to 5 mm) and at points drawn inside
them; and a plate with a counterbored hole, a blended boss and a bend, its
sizes drawn at random (seeded, so a failure comes back) within the ranges a
part like it takes. Each is built exactly, after-checked at every step, and
held to the implicit kernel's part by the agreement test (13.4).
"""

from __future__ import annotations

import contextlib
import json
import random
import unittest
from typing import Any

from v2_occ import CLEVIS, converted, needs_occ, v2_document

with contextlib.suppress(
    ImportError
):  # no OpenCascade here: every class below is skipped
    from forge_occ.agreement import agree


def _clevis(ear_thickness: float, root_blend: float) -> Any:
    payload = json.loads(CLEVIS.read_text(encoding="utf-8"))
    for parameter in payload["components"][0]["parameters"]:
        if parameter["id"] == "ear_thickness":
            parameter["value"] = {"magnitude": ear_thickness, "unit": "mm"}
        if parameter["id"] == "root_blend":
            parameter["value"] = {"magnitude": root_blend, "unit": "mm"}
    return converted(json.dumps(payload))


def _plate(rng: random.Random) -> Any:
    length, width, thick = rng.uniform(40, 80), rng.uniform(25, 40), rng.uniform(3, 6)
    hole = rng.uniform(3, 6)
    boss = rng.uniform(6, min(width / 3, 12))

    def mm(value: float) -> dict[str, Any]:
        return {"magnitude": round(value, 3), "unit": "mm"}

    def at(*value: float) -> dict[str, Any]:
        return {"vector": [round(c, 3) for c in value], "unit": "mm"}

    steps = [
        {"id": "plate", "op": "box", "role": "plate", "params": {"size": at(length, width, thick)}},
        {"id": "boss", "op": "cylinder", "role": "boss",
         "params": {"diameter": mm(boss), "height": mm(rng.uniform(4, 10)),
                    "origin": at(length * 0.7, width / 2, thick)}},
        {"id": "joined", "op": "union", "inputs": ["plate", "boss"],
         "params": {"blend_radius": mm(rng.uniform(0.5, 1.5))}},
        {"id": "drilled", "op": "hole", "inputs": ["joined"], "role": "mount",
         "params": {"diameter": mm(hole), "position": at(length * 0.25, width / 2, thick / 2), "through": "all",
                    "counterbore_diameter": mm(hole * 1.8), "counterbore_depth": mm(thick / 3)}},
        {"id": "bent", "op": "bend", "inputs": ["drilled"],
         "params": {"angle": {"magnitude": round(rng.uniform(20, 90), 2), "unit": "deg"},
                    "position": at(length * 0.45, width / 2, thick / 2), "along": [1, 0, 0], "toward": [0, 0, 1],
                    "radius": mm(rng.uniform(2, 6))}},
    ]  # fmt: skip
    return v2_document({"schema_version": "2.0.0", "document_id": "p", "project_id": "p", "revision": 1,
                        "name": "plate", "components": [{"id": "plate", "steps": steps}]})  # fmt: skip


@needs_occ
class TheClevisAcrossItsRanges(unittest.TestCase):
    def test_the_corners_and_inside(self) -> None:
        rng = random.Random(3)
        cases = [(4.0, 0.5), (4.0, 5.0), (10.0, 0.5), (10.0, 5.0),
                 *((round(rng.uniform(4, 10), 3), round(rng.uniform(0.5, 5), 3)) for _ in range(2))]  # fmt: skip
        for ear, blend in cases:
            with self.subTest(ear_thickness=ear, root_blend=blend):
                report = agree(_clevis(ear, blend), "clevis")
                self.assertTrue(
                    report.holds, json.dumps(report.as_dict(), default=str)[:1500]
                )


@needs_occ
class APlateDrawnAtRandom(unittest.TestCase):
    def test_built_and_agreeing(self) -> None:
        rng = random.Random(11)
        for k in range(3):
            document = _plate(rng)
            with self.subTest(k):
                report = agree(document, "plate")
                self.assertTrue(
                    report.holds, json.dumps(report.as_dict(), default=str)[:1500]
                )


if __name__ == "__main__":
    unittest.main()
