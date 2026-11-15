"""V2 stage 3: ``forge doctor`` (forge_cli.doctor; docs/V2-stage3.md, section 15).

Every check passes where the exact kernel is installed, one line each; the
probe's volume is the one worked out by hand; a check that fails is said to,
the rest still run, and the exit code says so.
"""

from __future__ import annotations

import io
import json
import math
import unittest
from unittest import mock

from forge_cli.doctor import PROBE, probe_volume, run_doctor
from v2_occ import needs_occ


class TheProbe(unittest.TestCase):
    def test_its_volume_by_hand(self) -> None:
        # The plate, less the hole and its counterbore, less a 1 mm round along a 40 mm edge; the bend
        # keeps a flat plate's volume (its middle surface keeps its length).
        expected = 14400 - math.pi * (9 * 3 + 30.25 * 3) - 40 * (1 - math.pi / 4)
        self.assertAlmostEqual(probe_volume(), expected, places=9)

    def test_it_is_a_v2_document(self) -> None:
        from forge_ir.v2 import DocumentV2

        document = DocumentV2.from_json(json.dumps(PROBE))
        self.assertEqual(
            [s.op for s in document.steps("probe")], ["box", "hole", "fillet", "bend"]
        )


@needs_occ
class TheChecks(unittest.TestCase):
    def test_every_check_passes_here(self) -> None:
        out = io.StringIO()
        self.assertEqual(run_doctor(out), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(
            [line.split()[1] for line in lines[:-1]],
            ["python", "pins", "probe", "step", "meshes"],
        )
        self.assertTrue(all(line.startswith("ok") for line in lines[:-1]))
        self.assertEqual(lines[-1], "all checks passed")

    def test_a_failing_check_is_said_and_the_rest_still_run(self) -> None:
        out = io.StringIO()
        with mock.patch(
            "forge_occ.status",
            return_value="the exact kernel is cadquery-ocp-novtk 7.8.0",
        ):
            self.assertEqual(run_doctor(out), 1)
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[1].startswith("FAIL  pins"))
        self.assertIn("7.8.0", lines[1])
        self.assertTrue(lines[2].startswith("ok    probe"))
        self.assertEqual(lines[-1], "1 of 5 checks failed")


if __name__ == "__main__":
    unittest.main()
