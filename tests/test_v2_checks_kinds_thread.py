"""V2 stage 2, step 5: the thread kind, on an M8 stud built right and built wrong.

The stud of tests/v2_reference.py's threaded boss, built by hand with
manifold3d: its thread an ISO 68-1 basic profile, twisted as it rises. The
profile, the hand, the pitch and the length must pass as asked; a plain rod,
the other hand, or a pitch a tenth out must fail the profile; the pitch and
the length must fail ``2u`` beyond each limit of their tolerances and pass
``2u`` within.
"""

from __future__ import annotations

import functools
import math
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from forge_checks.checks import Check
from forge_checks.classes import (
    Tolerance,
    Verdict,
    VerificationClass,
    fine_enough,
    general,
)
from forge_checks.kinds import MUTANTS
from forge_checks.kinds.thread import (
    Hand,
    Helix,
    Length,
    Pitch,
    Profile,
    profile_radius,
)
from forge_checks.measure import Probe
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import place
from forge_checks.view import Capability, ViewProxy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_meshes import HAVE_MANIFOLD, triangles
from v2_reference import OVERLAP, box, m3, rod, threaded_boss
from v2_specs import read

#: The coverage radius the probes take, and how far the stud's mesh is from its true surface.
COVER, DEFLECTION = 1.0, 0.002
#: The stud: on the plate's top at z = 5, 12 high, its M8 thread over the top 8 (from z = 9).
HELIX = Helix((0.0, 0.0, 5.0), (0.0, 0.0, 1.0), 4.0, 1.25, 1, (4.0, 12.0))


def stud(
    pitch: float = 1.25, hand: int = 1, length: float = 8.0, plain: bool = False
) -> Any:
    """The plate and the stud, its top ``length`` threaded at ``pitch`` and ``hand`` (or left plain)."""
    part = box((-20, -15, 0), (20, 15, 5)) + rod(
        (0, 0, 5 - OVERLAP), (0, 0, 1), 12 - length + 2 * OVERLAP, 4
    )
    if plain:
        return part + rod((0, 0, 17 - length), (0, 0, 1), length, 4)
    angles = 2 * math.pi * np.arange(360) / 360
    radius = profile_radius(
        np.mod(-hand * angles * pitch / (2 * math.pi), pitch), 4.0, pitch
    )
    section = m3().CrossSection(
        [np.stack([radius * np.cos(angles), radius * np.sin(angles)], axis=1).tolist()]
    )
    turns = length / pitch
    made = m3().Manifold.extrude(
        section, length, math.ceil(turns * 72), hand * 360 * turns
    )
    return part + made.translate((0, 0, 17 - length))


@functools.cache
def stud_part() -> Oracle:
    items, _ = threaded_boss()
    spec = read(items)
    return oracle(spec, place(spec))


def probe(solid: Any) -> Probe:
    view = ViewProxy(
        MeshView(
            Mesh.from_triangles(triangles(solid)),
            source="mesh-file",
            deflection=DEFLECTION,
        )
    )
    return Probe(view, stud_part(), COVER)


def check(
    name: str, nominal: float, target: object, tolerance: Tolerance | None
) -> Check:
    return Check(f"thread/{name}/0", "thread", name, "thread", VerificationClass.BOUNDED,
                 frozenset({Capability.COVERAGE, Capability.CROSSINGS}), nominal, tolerance, target)  # fmt: skip


PROFILE = check("designation", 0.0, Profile(HELIX), general(HELIX.depth))
HAND = check("hand", 0.0, Hand(HELIX), None)
PITCH = check("designation.pitch", 1.25, Pitch(HELIX), general(1.25))
LENGTH = check("length", 8.0, Length(HELIX), general(8.0))


@unittest.skipUnless(HAVE_MANIFOLD, "the parts are made with manifold3d")
class Thread(unittest.TestCase):
    def test_the_stud_as_asked(self) -> None:
        built = probe(stud())
        for c in (PROFILE, HAND, PITCH, LENGTH):
            with self.subTest(check=c.field):
                found = c.run(built)
                self.assertIs(found.verdict, Verdict.PASS, found)
                if c.tolerance is not None:
                    assert found.measured is not None
                    self.assertTrue(
                        fine_enough(found.measured.width / 2, c.tolerance), found
                    )
        # The pitch as asked; the length, short of it by the plain foot's overlap into the thread.
        pitch, length = PITCH.run(built).measured, LENGTH.run(built).measured
        assert pitch is not None and length is not None
        self.assertTrue(pitch.contains(1.25), pitch)
        self.assertTrue(length.contains(8 - OVERLAP), length)

    def test_a_plain_rod_the_other_hand_and_a_wrong_pitch_fail(self) -> None:
        wrong = {
            "a plain rod": stud(plain=True),
            "left-handed": stud(hand=-1),
            "a pitch of 1.375": stud(pitch=1.375),
        }
        for what, solid in wrong.items():
            with self.subTest(built=what):
                found = PROFILE.run(probe(solid))
                self.assertIs(found.verdict, Verdict.FAIL, found)
        self.assertIs(HAND.run(probe(stud(hand=-1))).verdict, Verdict.FAIL)

    def test_no_stud_fails_each_of_them(self) -> None:
        """The plate alone (a mutant moved its stud away): no thread between its cylinders, a FAIL of each, the hand's too, which judges itself."""
        plate = probe(box((-20, -15, 0), (20, 15, 5)))
        for c in (PROFILE, HAND, PITCH):
            with self.subTest(check=c.field):
                found = c.run(plate)
                self.assertIs(found.verdict, Verdict.FAIL, found)
                self.assertIn("no built thread", found.reason)

    def test_a_hole_across_the_plate_under_a_stud_threaded_all_along(self) -> None:
        """Generated part 423's: a line down the rod comes out into a hole across what the stud stands on, 0.7 mm past the stud's foot, and goes in again 2.3 mm past it. Where the thread starts is on the rod, never past its foot."""
        helix = Helix((0.0, 0.0, 5.0), (0.0, 0.0, 1.0), 4.0, 1.25, 1, (0.0, 12.0))
        whole = check("length", 12.0, Length(helix), general(12.0))
        holed = stud(length=12.0) - rod((-20.0, 0.0, 3.5), (1.0, 0.0, 0.0), 40.0, 0.8)
        found = whole.run(probe(holed))
        self.assertIs(found.verdict, Verdict.PASS, found)

    def test_pitch_and_length_mutants_fail_and_near_misses_pass(self) -> None:
        built = probe(stud())
        made: tuple[tuple[Check, Callable[[float], Any]], ...] = (
            (PITCH, lambda v: stud(pitch=v)),
            (LENGTH, lambda v: stud(length=v + 0.05)),
        )
        for c, make in made:
            found = c.run(built)
            assert found.measured is not None
            u = found.measured.width / 2
            for value, verdict in MUTANTS["thread"](c.nominal, c.tolerance, u):
                with self.subTest(check=c.field, at=value):
                    self.assertIs(c.run(probe(make(value))).verdict, verdict)


if __name__ == "__main__":
    unittest.main()
