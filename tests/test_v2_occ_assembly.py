"""V2 stage 3: assemblies, their placements and their mates (forge_occ.assembly; docs/V2-stage3.md, 6.1 and 16).

The clevis and its pin: the document round-trips through JSON unchanged,
builds, and both mates hold; a pin moved off the bore's axis, tilted, or
lifted off the ear breaks the mate it should and no other; a gap is held to
what it says; a mate between interfaces that aren't one cylinder or one
plane is refused.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from v2_occ import CLEVIS_PIN, needs_occ, v2, v2_document

try:
    from forge_occ.assembly import build_assembly
    from forge_occ.errors import DesignError
except ImportError:  # no OpenCascade here: every class below is skipped
    pass


def pin_at(
    change: dict[str, Any] | None = None, *, gap: dict[str, Any] | None = None
) -> Any:
    payload = json.loads(CLEVIS_PIN.read_text())
    if change is not None:
        payload["instances"][1]["at"].update(change)
    if gap is not None:
        payload["mates"][1]["gap"] = gap
    return v2_document(payload)


@needs_occ
class TheClevisAndItsPin(unittest.TestCase):
    def test_the_document_round_trips_unchanged(self) -> None:
        text = CLEVIS_PIN.read_text()
        document = v2(text)
        self.assertEqual(json.loads(document.to_json()), json.loads(text))
        self.assertEqual(v2(document.to_json()).to_json(), document.to_json())

    def test_both_mates_hold(self) -> None:
        assembly = build_assembly(v2(CLEVIS_PIN.read_text()))
        self.assertEqual(sorted(assembly.parts), ["clevis", "pin"])
        self.assertEqual(
            [(m.mate, m.holds) for m in assembly.mates],
            [("pin_in_bore", True), ("head_on_ear", True)],
        )
        contact = assembly.mates[1]
        self.assertGreater(contact.found["overlap"], 0.0)

    def test_a_pin_off_the_axis_breaks_the_coaxial_mate_only(self) -> None:
        assembly = build_assembly(
            pin_at({"translate": {"vector": [30.01, -3, 18], "unit": "mm"}})
        )
        self.assertEqual([m.holds for m in assembly.mates], [False, True])
        self.assertAlmostEqual(assembly.mates[0].found["apart"], 0.01, delta=1e-9)

    def test_a_tilted_pin_breaks_both(self) -> None:
        assembly = build_assembly(
            pin_at({"rotate_angle": {"magnitude": -89.9, "unit": "deg"}})
        )
        self.assertEqual([m.holds for m in assembly.mates], [False, False])

    def test_a_pin_lifted_off_the_ear_breaks_the_contact_only(self) -> None:
        assembly = build_assembly(
            pin_at({"translate": {"vector": [30, -3.5, 18], "unit": "mm"}})
        )
        self.assertEqual([m.holds for m in assembly.mates], [True, False])
        self.assertAlmostEqual(assembly.mates[1].found["gap"], 0.5, delta=1e-9)

    def test_a_gap_is_held_to_what_it_says(self) -> None:
        lifted = {"translate": {"vector": [30, -3.5, 18], "unit": "mm"}}
        self.assertTrue(
            build_assembly(pin_at(lifted, gap={"magnitude": 0.5, "unit": "mm"})).holds
        )
        self.assertFalse(
            build_assembly(pin_at(lifted, gap={"magnitude": 0.4, "unit": "mm"})).holds
        )

    def test_a_head_smaller_than_the_bore_seats_on_nothing(self) -> None:
        payload = json.loads(CLEVIS_PIN.read_text())
        head = next(
            p
            for p in payload["components"][1]["parameters"]
            if p["id"] == "head_diameter"
        )
        head["value"] = {"magnitude": 8.1, "unit": "mm"}
        assembly = build_assembly(v2_document(payload))
        self.assertEqual([m.holds for m in assembly.mates], [True, False])
        self.assertEqual(assembly.mates[1].why, "the faces don't overlap")

    def test_a_coaxial_mate_on_a_plane_doesnt_hold(self) -> None:
        payload = copy.deepcopy(json.loads(CLEVIS_PIN.read_text()))
        clevis = payload["components"][0]
        clevis["interfaces"].append(
            {"id": "top", "type": "bore", "geometry": "base.z_max"}
        )
        payload["mates"].append({"id": "odd", "kind": "coaxial", "a": {"instance": "clevis_1", "interface": "top"},
                                 "b": {"instance": "pin_1", "interface": "pin_shaft"}})  # fmt: skip
        assembly = build_assembly(v2_document(payload))
        self.assertFalse(assembly.mates[2].holds)
        self.assertEqual(assembly.mates[2].why, "a coaxial mate relates two cylinders")

    def test_no_instances_is_no_assembly(self) -> None:
        payload = json.loads(CLEVIS_PIN.read_text())
        payload.pop("instances")
        payload.pop("mates")
        with self.assertRaises(DesignError):
            build_assembly(v2_document(payload))


if __name__ == "__main__":
    unittest.main()
