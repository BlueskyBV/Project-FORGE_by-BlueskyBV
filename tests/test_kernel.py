"""Tests for lineage-addressed topology and incremental compilation.

The two properties under test are the ones the design claims:

1. A **parameter** change never breaks a semantic selection, because identity is
   derived from the construction and not from the geometry.
2. A **topology** change that buries named geometry breaks the reference
   *loudly*, with a diagnostic naming what was lost.

A heuristic face matcher passes the first test most of the time and fails the
second silently. Both halves are therefore tested.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from forge_geom import (
    BoxSDF,
    CylinderSDF,
    Difference,
    RectangleProfile,
    Revolve,
    SphereSDF,
    Union,
    measure_mass_properties,
)
from forge_geom.measure import _residual_cell_bounds
from forge_ir import Document, SchemaErrorGroup
from forge_kernel import (
    CompileError,
    Compiler,
    EntityStatus,
    SelectionError,
    content_hash,
    lineage_token,
)
from forge_units import Q

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "clevis" / "clevis.forgeir.json"


def load_clevis() -> Document:
    return Document.from_json(EXAMPLE.read_text())


class LineageTokens(unittest.TestCase):
    def test_token_depends_only_on_construction(self) -> None:
        a = lineage_token("pivot", "bore", 0)
        b = lineage_token("pivot", "bore", 0)
        self.assertEqual(a, b)
        self.assertNotEqual(a, lineage_token("pivot", "axis", 0))
        self.assertNotEqual(a, lineage_token("pivot2", "bore", 0))
        self.assertNotEqual(a, lineage_token("pivot", "bore", 1))

    def test_tokens_survive_every_parameter_change(self) -> None:
        """The central claim: parameter edits cannot invalidate a selection."""
        document = load_clevis()
        component = document.component("clevis")
        compiler = Compiler()

        baseline = compiler.compile_component(component)
        expected = {
            name: baseline.geometry_map.get(name).token  # type: ignore[union-attr]
            for name in baseline.geometry_map.names()
        }

        variations = [
            {"ear_thickness": Q(4.0, "mm")},
            {"ear_thickness": Q(10.0, "mm")},
            {"root_blend": Q(0.5, "mm")},
            {"root_blend": Q(5.0, "mm")},
            {"pivot_diameter": Q(6.0, "mm")},
            {"ear_height": Q(24.0, "mm")},
            {"ear_thickness": Q(9.0, "mm"), "root_blend": Q(4.5, "mm")},
        ]
        for overrides in variations:
            with self.subTest(overrides={k: str(v) for k, v in overrides.items()}):
                part = compiler.compile_component(component, overrides=overrides)
                for name, token in expected.items():
                    entity = part.geometry_map.get(name)
                    self.assertIsNotNone(
                        entity, f"{name} disappeared after a parameter change"
                    )
                    self.assertEqual(
                        entity.token,  # type: ignore[union-attr]
                        token,
                        f"{name} changed identity after a parameter change",
                    )

    def test_interfaces_still_resolve_after_parameter_change(self) -> None:
        document = load_clevis()
        component = document.component("clevis")
        compiler = Compiler()
        for thickness in (4.0, 5.5, 7.0, 8.5, 10.0):
            with self.subTest(ear_thickness=thickness):
                part = compiler.compile_component(
                    component, overrides={"ear_thickness": Q(thickness, "mm")}
                )
                for interface in component.interfaces:
                    entity = part.geometry_map.resolve(interface.geometry)
                    self.assertIs(entity.status, EntityStatus.LIVE)

    def test_bore_geometry_tracks_its_parameter(self) -> None:
        """The token is stable; the geometry it names is not, and should not be."""
        document = load_clevis()
        component = document.component("clevis")
        compiler = Compiler()
        for diameter in (6.0, 8.2, 10.0):
            part = compiler.compile_component(
                component, overrides={"pivot_diameter": Q(diameter, "mm")}
            )
            entity = part.geometry_map.resolve("pivot.bore")
            self.assertAlmostEqual(entity.dimensions["radius"], diameter / 2.0)


class BurialDetection(unittest.TestCase):
    """A topology change must break a reference loudly, not silently."""

    def _bury_the_mounting_face(self) -> Document:
        """Add a pad under the base so that ``base.z_min`` is no longer exposed."""
        payload = json.loads(EXAMPLE.read_text())
        component = payload["components"][0]
        component["features"].append(
            {
                "id": "pad",
                "kind": "box",
                "role": "pad",
                "parameters": {
                    "size": {
                        "vector": ["base_length", "base_width", 8],
                        "unit": "mm",
                    },
                    "origin": {"vector": [0, 0, -8], "unit": "mm"},
                    "centered": False,
                },
            }
        )
        component["features"].append(
            {
                "id": "with_pad",
                "kind": "union",
                "role": "with_pad",
                "inputs": ["pivot", "pad"],
            }
        )
        return Document.from_json(json.dumps(payload))

    def test_burying_a_referenced_face_is_detected(self) -> None:
        document = self._bury_the_mounting_face()
        part = Compiler().compile_component(document.component("clevis"))
        entity = part.geometry_map.get("base.z_min")
        self.assertIsNotNone(entity)
        self.assertIs(
            entity.status,  # type: ignore[union-attr]
            EntityStatus.BURIED,
            "a face covered by new material must be reported as buried",
        )

    def test_resolving_a_buried_face_raises_with_a_useful_message(self) -> None:
        document = self._bury_the_mounting_face()
        part = Compiler().compile_component(document.component("clevis"))
        with self.assertRaises(SelectionError) as caught:
            part.geometry_map.resolve("base.z_min")
        detail = caught.exception.detail
        self.assertEqual(detail["owning_feature"], "base_plate")
        self.assertIn("topology change", detail["hint"])
        # It must not silently return a nearby face instead.
        self.assertIn("no longer lies on the solid's boundary", caught.exception.message)

    def test_unknown_selection_names_what_is_available(self) -> None:
        part = Compiler().compile_component(load_clevis().component("clevis"))
        with self.assertRaises(SelectionError) as caught:
            part.geometry_map.resolve("pivot.bore_typo")
        self.assertIn("pivot.bore", caught.exception.detail["did_you_mean"])

    def test_a_live_face_reports_how_much_of_it_survived(self) -> None:
        part = Compiler().compile_component(load_clevis().component("clevis"))
        top = part.geometry_map.resolve("base.z_max")
        self.assertIs(top.status, EntityStatus.LIVE)
        # The ears stand on it, so it is partly consumed and says so.
        self.assertIn("%", top.note)


class IncrementalCompilation(unittest.TestCase):
    def test_identical_rebuild_reuses_everything(self) -> None:
        component = load_clevis().component("clevis")
        compiler = Compiler()
        first = compiler.compile_component(component)
        self.assertEqual(first.features_reused, 0)
        second = compiler.compile_component(component)
        self.assertEqual(second.features_built, 0)
        self.assertEqual(second.features_reused, len(second.traces))
        self.assertEqual(first.part_hash, second.part_hash)

    def test_only_the_dirty_cone_is_rebuilt(self) -> None:
        component = load_clevis().component("clevis")
        compiler = Compiler()
        compiler.compile_component(component)

        # root_blend feeds only the blended union and everything after it.
        part = compiler.compile_component(
            component, overrides={"root_blend": Q(4.0, "mm")}
        )
        reused = {trace.feature_id for trace in part.traces if trace.reused}
        rebuilt = {trace.feature_id for trace in part.traces if not trace.reused}
        self.assertIn("base_plate", reused)
        self.assertIn("ear_left", reused)
        self.assertIn("ear_assembly", reused)
        self.assertIn("joined", rebuilt)
        self.assertIn("pivot", rebuilt)

    def test_returning_to_a_previous_value_is_a_cache_hit(self) -> None:
        component = load_clevis().component("clevis")
        compiler = Compiler()
        original = compiler.compile_component(component)
        compiler.compile_component(component, overrides={"ear_thickness": Q(9.0, "mm")})
        restored = compiler.compile_component(
            component, overrides={"ear_thickness": Q(6.0, "mm")}
        )
        self.assertEqual(restored.part_hash, original.part_hash)
        self.assertEqual(restored.features_built, 0)

    def test_part_hash_changes_with_geometry(self) -> None:
        component = load_clevis().component("clevis")
        compiler = Compiler()
        a = compiler.compile_component(component)
        b = compiler.compile_component(
            component, overrides={"ear_thickness": Q(8.0, "mm")}
        )
        self.assertNotEqual(a.part_hash, b.part_hash)

    def test_cache_key_is_insensitive_to_unit_spelling(self) -> None:
        """0.006 m and 6 mm are the same geometry and must share a cache entry."""
        component = load_clevis().component("clevis")
        compiler = Compiler()
        in_millimetres = compiler.compile_component(
            component, overrides={"ear_thickness": Q(7.0, "mm")}
        )
        built_before = compiler.cache_statistics.misses
        in_metres = compiler.compile_component(
            component, overrides={"ear_thickness": Q(0.007, "m")}
        )
        self.assertEqual(in_millimetres.part_hash, in_metres.part_hash)
        self.assertEqual(compiler.cache_statistics.misses, built_before)

    def test_content_hash_is_stable_and_discriminating(self) -> None:
        self.assertEqual(content_hash("a", 1, 2.0), content_hash("a", 1, 2.0))
        self.assertNotEqual(content_hash("a", 1, 2.0), content_hash("a", 1, 2.5))
        self.assertNotEqual(content_hash("a", 1), content_hash(1, "a"))


class CompileFailures(unittest.TestCase):
    """Compilation fails closed: a bad design stops, it does not degrade."""

    def _mutate(self, mutate) -> Document:
        payload = json.loads(EXAMPLE.read_text())
        mutate(payload)
        return Document.from_json(json.dumps(payload))

    def _set_parameter(self, payload, identifier, magnitude) -> None:
        for parameter in payload["components"][0]["parameters"]:
            if parameter["id"] == identifier:
                parameter["value"]["magnitude"] = magnitude
                return
        raise AssertionError(f"no parameter {identifier}")

    def test_parameter_outside_declared_bounds_is_refused(self) -> None:
        document = self._mutate(
            lambda payload: self._set_parameter(payload, "ear_thickness", 25.0)
        )
        with self.assertRaises(CompileError) as caught:
            Compiler().compile_component(document.component("clevis"))
        self.assertIn("ear_thickness", caught.exception.detail["parameters"])

    def test_zero_dimension_is_refused_not_silently_built(self) -> None:
        document = self._mutate(
            lambda payload: self._set_parameter(payload, "base_thickness", 0.0)
        )
        with self.assertRaises(CompileError) as caught:
            Compiler().compile_component(document.component("clevis"))
        self.assertEqual(caught.exception.detail["feature"], "base_plate")

    def test_unknown_feature_kind_is_refused_at_decode(self) -> None:
        payload = json.loads(EXAMPLE.read_text())
        payload["components"][0]["features"][0]["kind"] = "loft_through_hyperspace"
        with self.assertRaises(SchemaErrorGroup) as caught:
            Document.from_json(json.dumps(payload))
        rendered = str(caught.exception)
        self.assertIn("loft_through_hyperspace", rendered)

    def test_missing_unit_is_refused(self) -> None:
        payload = json.loads(EXAMPLE.read_text())
        for parameter in payload["components"][0]["parameters"]:
            if parameter["id"] == "pivot_diameter":
                parameter["value"] = 8.2  # a bare number, no unit
        with self.assertRaises(SchemaErrorGroup) as caught:
            Document.from_json(json.dumps(payload))
        self.assertIn("must carry a unit", str(caught.exception))

    def test_interface_pointing_at_nothing_is_refused(self) -> None:
        payload = json.loads(EXAMPLE.read_text())
        payload["components"][0]["interfaces"][0]["geometry"] = "pivot.nonexistent"
        with self.assertRaises(SchemaErrorGroup) as caught:
            Document.from_json(json.dumps(payload))
        self.assertIn("no feature publishes", str(caught.exception))

    def test_error_carries_a_json_pointer(self) -> None:
        payload = json.loads(EXAMPLE.read_text())
        del payload["components"][0]["features"][0]["parameters"]["size"]
        with self.assertRaises(SchemaErrorGroup) as caught:
            Document.from_json(json.dumps(payload))
        pointers = [error.pointer for error in caught.exception.errors]
        self.assertTrue(
            any(pointer.startswith("/components/0/features/") for pointer in pointers),
            f"expected a JSON pointer into the offending feature, got {pointers}",
        )


class GeometryAgreement(unittest.TestCase):
    """Both measurement paths must agree, and both must enclose the truth."""

    def test_octree_encloses_analytic_volume(self) -> None:
        cases = [
            (BoxSDF((0, 0, 0), (20, 10, 5)), 40 * 20 * 10),
            (CylinderSDF((0, 0, 0), (0, 0, 1), 5.0, 20.0), math.pi * 25 * 20),
            (
                Difference(
                    BoxSDF((0, 0, 0), (20, 20, 3)),
                    (CylinderSDF((0, 0, -10), (0, 0, 1), 6.0, 20.0),),
                ),
                40 * 40 * 6 - math.pi * 36 * 6,
            ),
            (
                Union(
                    (BoxSDF((0, 0, 0), (10, 10, 10)), BoxSDF((15, 0, 0), (5, 5, 5)))
                ),
                20 * 20 * 20 + 10 * 10 * 10,
            ),
        ]
        for solid, exact in cases:
            with self.subTest(solid=type(solid).__name__):
                measured = measure_mass_properties(solid).volume.magnitude
                self.assertLessEqual(
                    measured.lo, exact, "lower bound exceeded the true volume"
                )
                self.assertGreaterEqual(
                    measured.hi, exact, "upper bound fell below the true volume"
                )

    def test_blend_radius_is_localised(self) -> None:
        """A blend must not affect geometry away from the junction."""
        a = BoxSDF((0, 0, 0), (10, 10, 10))
        b = BoxSDF((0, 0, 15), (5, 5, 5))
        sharp = Union((a, b))
        blended = Union((a, b), blend_radius=2.0)
        far = np.array([[0.0, 0.0, -9.0], [9.0, 9.0, 0.0], [0.0, 0.0, 30.0]])
        np.testing.assert_allclose(sharp(far), blended(far), atol=1e-9)

    def test_lipschitz_bound_holds_numerically(self) -> None:
        """The measurement's soundness rests on this bound; check it empirically."""
        solid = Union(
            (
                BoxSDF((0, 0, 0), (20, 10, 5)),
                CylinderSDF((0, 0, 0), (0, 0, 1), 4.0, 18.0),
            ),
            blend_radius=2.0,
        )
        rng = np.random.default_rng(11)
        points = rng.uniform(-30, 30, size=(4000, 3))
        gradients = solid.gradient(points, step=1e-4)
        magnitudes = np.linalg.norm(gradients, axis=1)
        self.assertLessEqual(
            float(magnitudes.max()),
            solid.lipschitz * 1.02,
            "the field changes faster than its declared Lipschitz bound, which "
            "would invalidate every rigorous measurement built on it",
        )

    def test_interval_bounds_enclose_sampled_values(self) -> None:
        """The cell bounds must contain every field value inside the cell."""
        solid = Difference(
            BoxSDF((0, 0, 0), (20, 12, 6)),
            (CylinderSDF((0, 0, -10), (0, 0, 1), 5.0, 20.0),),
        )
        rng = np.random.default_rng(7)
        centres = rng.uniform(-25, 25, size=(300, 3))
        half = np.array([1.5, 1.5, 1.5])
        lo, hi = solid.bounds((centres - half, centres + half))
        for index in range(centres.shape[0]):
            offsets = rng.uniform(-1.0, 1.0, size=(40, 3)) * half
            values = solid(centres[index] + offsets)
            self.assertLessEqual(
                float(values.min()) + 1e-9,
                float(hi[index]) + 1e-9,
            )
            self.assertGreaterEqual(float(values.max()) + 1e-9, float(lo[index]))
            self.assertTrue(
                np.all(values >= lo[index] - 1e-6),
                "a sampled value fell below the interval lower bound",
            )
            self.assertTrue(
                np.all(values <= hi[index] + 1e-6),
                "a sampled value rose above the interval upper bound",
            )


class RevolutionEnvelope(unittest.TestCase):
    """A revolved solid's envelope must actually contain the revolved solid.

    The envelope is not decoration: it seeds the octree in
    ``measure_mass_properties``, so a box that misses material silently makes
    the reported volume enclosure stop enclosing.
    """

    #: ``u`` in [0, 10], ``v`` in [-1, 1]: a thin annular disc of outer radius 10.
    PROFILE = RectangleProfile((5.0, 0.0), 5.0, 1.0)

    def _interior_points(self, solid: Revolve, seed: int, count: int = 120000):
        rng = np.random.default_rng(seed)
        points = rng.uniform(-15.0, 18.0, size=(count, 3))
        return points[solid(points) < 0.0]

    def _assert_envelope_contains_interior(self, solid: Revolve, seed: int) -> None:
        envelope = solid.envelope
        lo = np.array(envelope.lo)
        hi = np.array(envelope.hi)
        interior = self._interior_points(solid, seed)
        self.assertGreater(interior.shape[0], 0, "the sampler found no interior")
        escaped = np.any((interior < lo - 1e-9) | (interior > hi + 1e-9), axis=1)
        self.assertFalse(
            bool(escaped.any()),
            f"{int(escaped.sum())} of {interior.shape[0]} interior points fell "
            f"outside the declared envelope {envelope.lo} .. {envelope.hi}; "
            f"they reach {interior.min(axis=0).tolist()} .. "
            f"{interior.max(axis=0).tolist()}",
        )

    def test_diagonal_axis_envelope_contains_the_solid(self) -> None:
        """The counterexample: a disc revolved about ``(1, 1, 0)/sqrt(2)``.

        The old ``radius*(1 - |axis_i|)`` growth reported ``x, y`` in
        [-3.636, 3.636] while interior points reach +/-7.778, putting 43.9% of
        sampled interior points outside the box that was supposed to bound them.
        The correct perpendicular reach is ``radius*sqrt(1 - axis_i**2)``, here
        ``10*sqrt(0.5) = 7.071``, plus the 0.707 axial offset.
        """
        axis = (1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0), 0.0)
        solid = Revolve(self.PROFILE, (0.0, 0.0, 0.0), axis, (1.0, 0.0, 0.0))
        envelope = solid.envelope
        self.assertAlmostEqual(envelope.hi[0], 10.0 * math.sqrt(0.5) + math.sqrt(0.5), places=6)
        self.assertAlmostEqual(envelope.lo[0], -(10.0 * math.sqrt(0.5) + math.sqrt(0.5)), places=6)
        self._assert_envelope_contains_interior(solid, seed=101)

    def test_envelope_contains_the_solid_for_every_axis(self) -> None:
        """Axis-aligned, diagonal, negative and random axes; full and partial."""
        axes = [
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0), 0.0),
            (1.0 / math.sqrt(3.0),) * 3,
            (-1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0), 0.0),
        ]
        rng = np.random.default_rng(5)
        for _ in range(4):
            sample = rng.normal(size=3)
            axes.append(tuple((sample / np.linalg.norm(sample)).tolist()))

        seed = 200
        for axis in axes:
            for angle in (2.0 * math.pi, math.pi, math.pi / 3.0):
                for origin in ((0.0, 0.0, 0.0), (3.0, -2.0, 1.5)):
                    seed += 1
                    with self.subTest(axis=tuple(round(v, 3) for v in axis), angle=angle, origin=origin):
                        self._assert_envelope_contains_interior(
                            Revolve(self.PROFILE, origin, axis, (1.0, 0.0, 0.0), angle),
                            seed=seed,
                        )

    def test_diagonal_revolution_volume_encloses_the_truth(self) -> None:
        """Pappus gives 2*pi*5*20 = 628.3 mm^3 for this disc.

        With the truncated envelope the measurement reported 375.7 mm^3 with an
        uncertainty of +/-12.3 -- an enclosure that excluded the answer by a
        factor of 1.7, because the octree never covered the material the
        envelope had cropped away.
        """
        axis = (1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0), 0.0)
        solid = Revolve(self.PROFILE, (0.0, 0.0, 0.0), axis, (1.0, 0.0, 0.0))
        exact = 2.0 * math.pi * 5.0 * 20.0
        measured = measure_mass_properties(solid).volume.magnitude
        self.assertLessEqual(measured.lo, exact, "lower bound exceeded the true volume")
        self.assertGreaterEqual(measured.hi, exact, "upper bound fell below the true volume")


class BlendedBooleanLipschitz(unittest.TestCase):
    """The declared Lipschitz constant must survive the n-ary fold.

    ``Union._evaluate`` left-folds the blend, feeding each partial result back
    in as one side of the next blend, so the binary ``sqrt(2)`` compounds to
    ``base*sqrt(n)``. ``n`` coincident operands sit exactly on the maximiser at
    every fold step, which makes the peak reachable rather than merely bounding.
    """

    def _peak_gradient(self, solid, seed: int) -> float:
        rng = np.random.default_rng(seed)
        points = rng.uniform(-12.0, 12.0, size=(60000, 3))
        return float(np.linalg.norm(solid.gradient(points, step=1e-4), axis=1).max())

    def test_four_blended_operands_declare_two(self) -> None:
        """The counterexample: n=4 measured 2.0000 against a declared 1.4142."""
        solid = Union(
            tuple(SphereSDF((0.0, 0.0, 0.0), 5.0) for _ in range(4)), blend_radius=2.0
        )
        self.assertAlmostEqual(solid.lipschitz, 2.0, places=9)
        self.assertLessEqual(self._peak_gradient(solid, 11), solid.lipschitz * 1.02)

    def test_six_blended_operands_declare_sqrt_six(self) -> None:
        """The second counterexample: n=6 measured 2.4495 against 1.4142."""
        solid = Union(
            tuple(SphereSDF((0.0, 0.0, 0.0), 5.0) for _ in range(6)), blend_radius=2.0
        )
        self.assertAlmostEqual(solid.lipschitz, math.sqrt(6.0), places=9)
        self.assertLessEqual(self._peak_gradient(solid, 13), solid.lipschitz * 1.02)

    def test_declared_bound_holds_for_every_operand_count(self) -> None:
        for count in (1, 2, 3, 4, 5, 6, 8):
            with self.subTest(operands=count):
                solid = Union(
                    tuple(SphereSDF((0.0, 0.0, 0.0), 5.0) for _ in range(count)),
                    blend_radius=2.0,
                )
                observed = self._peak_gradient(solid, 17 + count)
                self.assertAlmostEqual(solid.lipschitz, math.sqrt(count), places=9)
                self.assertLessEqual(
                    observed,
                    solid.lipschitz * 1.02,
                    "the field changes faster than its declared Lipschitz bound, "
                    "which would invalidate every rigorous measurement built on it",
                )

    def test_blended_difference_counts_base_and_tools(self) -> None:
        """The fold in ``Difference`` runs over the base plus every tool."""
        solid = Difference(
            BoxSDF((0, 0, 0), (10, 10, 10)),
            tuple(SphereSDF((0.0, 0.0, 0.0), 5.0) for _ in range(3)),
            blend_radius=2.0,
        )
        self.assertAlmostEqual(solid.lipschitz, 2.0, places=9)

    def test_a_sharp_boolean_is_unaffected_by_operand_count(self) -> None:
        """min and max select an operand, so no number of them steepens anything."""
        for count in (1, 2, 6, 12):
            with self.subTest(operands=count):
                solid = Union(
                    tuple(SphereSDF((float(i) * 3.0, 0.0, 0.0), 5.0) for i in range(count))
                )
                self.assertAlmostEqual(solid.lipschitz, 1.0, places=9)

    def test_a_larger_constant_only_widens_the_residual_bounds(self) -> None:
        """The one consumer that *divides* by L, and never cross-checks it.

        ``_residual_cell_bounds`` converts a cell's distance value into a
        provably-inside and a provably-outside cube. A larger L shrinks both, so
        the honest constant can only widen the residual enclosure -- it cannot
        smuggle in volume the field does not justify.
        """
        field = np.array([-0.9, -0.2, 0.15, 0.8, 0.0])
        half = np.array([0.5, 0.5, 0.5])
        old_lo, old_hi = _residual_cell_bounds(field, half, math.sqrt(2.0))
        new_lo, new_hi = _residual_cell_bounds(field, half, 2.0)
        self.assertTrue(np.all(new_lo <= old_lo + 1e-12), "the lower bound rose")
        self.assertTrue(np.all(new_hi >= old_hi - 1e-12), "the upper bound fell")
        self.assertTrue(np.any(new_lo < old_lo) or np.any(new_hi > old_hi))

    def test_a_four_way_blended_union_still_encloses_its_volume(self) -> None:
        """End to end: the corrected constant keeps the measurement sound.

        Four coincident radius-5 spheres folded with ``k = 2`` collapse to
        ``f = k - sqrt(4)*(k - a)``, whose zero sits at ``a = k/2 = 1``. So the
        blended solid is exactly a radius-6 sphere, 904.78 mm^3, and its field
        runs at gradient 2 across the whole blend band -- a case where the
        understated 1.4142 is not merely loose but wrong, and where the octree
        was entitled to decide cells it could not decide.
        """
        solid = Union(
            tuple(SphereSDF((0.0, 0.0, 0.0), 5.0) for _ in range(4)), blend_radius=2.0
        )
        # A blend may not leave its operands' own envelope (see
        # `Union._within`): the swelling of four coincident surfaces is cut
        # off at the radius-5 sphere's box, so the solid is the radius-6
        # sphere less the six caps 1 mm tall beyond that box's faces. The
        # field still runs at gradient 2 across the blend band inside it.
        cap = math.pi * 1.0**2 * (3 * 6.0 - 1.0) / 3.0
        exact = 4.0 / 3.0 * math.pi * 6.0**3 - 6.0 * cap
        measured = measure_mass_properties(solid).volume.magnitude
        self.assertLessEqual(measured.lo, exact, "lower bound exceeded the true volume")
        self.assertGreaterEqual(measured.hi, exact, "upper bound fell below the true volume")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class WhatEachDimensionActuallyDoes(unittest.TestCase):
    """Nudge a parameter, rebuild, and see what moved.

    Every dimensional check before this one compares a number in the document
    against the same number in the document. `parameter:plate_thickness
    equals 4 mm` is true of a plate lying flat and equally true of that plate
    stood on its edge -- the oldest unfixed hole in this system, and the one
    that once let a spacer built in the wrong plane report PASS on seven
    requirements that were all telling the truth.

    The kernel could always answer it. Overriding one parameter and
    recompiling is a capability nothing else used.
    """

    @staticmethod
    def _component(parameters, features):
        import json

        from forge_ir import SCHEMA_VERSION

        payload = {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-00000000d001",
            "project_id": "00000000-0000-4000-8000-00000000d0ff",
            "name": "Probe", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [{
                "id": "p", "name": "Probe", "material": "pla_fdm",
                "parameters": parameters, "features": features}],
        }
        return Document.from_json(json.dumps(payload)).components[0]

    @staticmethod
    def _mm(value):
        return {"magnitude": float(value), "unit": "mm"}

    def _responses(self, parameters, features):
        from forge_pipeline.response import measure_the_response

        return {
            r.parameter: r
            for r in measure_the_response(self._component(parameters, features))
        }

    def _plate(self, order):
        return self._responses(
            [{"id": "plate_width", "value": self._mm(30)},
             {"id": "plate_depth", "value": self._mm(30)},
             {"id": "plate_thickness", "value": self._mm(4)}],
            [{"id": "body", "kind": "box", "parameters": {
                "size": {"vector": order, "unit": "mm"}}}])

    # -- the fact that was missing ----------------------------------------

    def test_a_plate_lying_flat_has_its_thickness_along_z(self) -> None:
        responses = self._plate(
            ["plate_width", "plate_depth", "plate_thickness"])
        self.assertEqual(responses["plate_thickness"].axis, "z")
        self.assertEqual(responses["plate_width"].axis, "x")

    def test_a_plate_on_its_edge_says_so(self) -> None:
        """The same document, the same 4 mm, a different direction."""
        responses = self._plate(
            ["plate_width", "plate_thickness", "plate_depth"])
        self.assertEqual(responses["plate_thickness"].axis, "y")

    # -- the negative claim, and what makes it safe ------------------------

    def test_a_dimension_the_part_does_not_have_is_caught(self) -> None:
        responses = self._responses(
            [{"id": "width", "value": self._mm(30)},
             {"id": "ghost", "value": self._mm(9)}],
            [{"id": "body", "kind": "box", "parameters": {
                "size": {"vector": ["width", "width", "width"],
                         "unit": "mm"}}},
             {"id": "buried", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "ghost", "unit": "mm"},
                "height": self._mm(2),
                "origin": {"vector": [15, 15, 5], "unit": "mm"}}},
             {"id": "u", "kind": "union", "inputs": ["body", "buried"]}])
        self.assertTrue(responses["ghost"].drives_nothing)
        self.assertFalse(responses["width"].drives_nothing)

    def test_symmetric_hole_spacing_is_not_inert(self) -> None:
        """The construction the authoring guide teaches, and the blind spot
        that decides how this is measured.

        `+spacing / 2` and `-spacing / 2`: moving the two holes apart changes
        the volume not at all, the extents not at all and the centroid not at
        all. A check built on those three integrals would call
        `mounting_hole_spacing` a dimension the part does not have and fail a
        correct design. The distance field has no such blind spot.
        """
        responses = self._responses(
            [{"id": "plate", "value": self._mm(30)},
             {"id": "thick", "value": self._mm(4)},
             {"id": "mounting_hole_spacing", "value": self._mm(20)},
             {"id": "hole_d", "value": self._mm(3)}],
            [{"id": "body", "kind": "box", "parameters": {
                "size": {"vector": ["plate", "plate", "thick"], "unit": "mm"},
                "centered": True}},
             {"id": "h1", "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": {"expression": "hole_d", "unit": "mm"},
                "position": {"vector": ["mounting_hole_spacing / 2", 0, 0],
                             "unit": "mm"}, "axis": [0, 0, 1]}},
             {"id": "h2", "kind": "hole", "inputs": ["h1"], "parameters": {
                "diameter": {"expression": "hole_d", "unit": "mm"},
                "position": {"vector": ["-mounting_hole_spacing / 2", 0, 0],
                             "unit": "mm"}, "axis": [0, 0, 1]}}])
        spacing = responses["mounting_hole_spacing"]
        self.assertFalse(spacing.drives_nothing)
        self.assertEqual(spacing.moves, ("shape",))
        self.assertIn("a position", spacing.describe())

    def test_a_derived_parameter_is_not_probed(self) -> None:
        """Overriding one would measure a design the document does not
        describe. Its effect shows up through what it is computed from."""
        responses = self._responses(
            [{"id": "w", "value": self._mm(30)},
             {"id": "d", "expression": "w * 2", "unit": "mm"}],
            [{"id": "b", "kind": "box", "parameters": {
                "size": {"vector": ["w", "w", "d"], "unit": "mm"}}}])
        self.assertTrue(responses["d"].skipped)
        self.assertFalse(responses["d"].drives_nothing)

    def test_a_count_is_not_probed_and_not_accused(self) -> None:
        """A probe that did not run is not evidence that nothing happened."""
        responses = self._responses(
            [{"id": "w", "value": self._mm(30)},
             {"id": "n", "value": {"magnitude": 4, "unit": ""}}],
            [{"id": "b", "kind": "box", "parameters": {
                "size": {"vector": ["w", "w", "w"], "unit": "mm"}}}])
        self.assertTrue(responses["n"].skipped)
        self.assertFalse(responses["n"].drives_nothing)

    def test_bounds_are_respected(self) -> None:
        """A bound is a contract the compiler enforces, so a probe that
        violates it measures the refusal and nothing else."""
        responses = self._responses(
            [{"id": "w", "value": self._mm(30),
              "bounds": {"min": self._mm(29), "max": self._mm(31)}}],
            [{"id": "b", "kind": "box", "parameters": {
                "size": {"vector": ["w", "w", "w"], "unit": "mm"}}}])
        self.assertFalse(responses["w"].drives_nothing)


class TheGatesThatWatchTheGeometry(unittest.TestCase):
    """The two gates the response probe makes possible."""

    @staticmethod
    def _verify(order):
        import json

        from forge_ir import SCHEMA_VERSION
        from forge_pipeline import verify_component

        def mm(value):
            return {"magnitude": float(value), "unit": "mm"}

        payload = {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-00000000d001",
            "project_id": "00000000-0000-4000-8000-00000000d0ff",
            "name": "Plate", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "assumptions": [],
            "requirements": [{
                "id": "REQ_THICK", "statement": "The plate is 4 mm thick",
                "measurement": "parameter:plate_thickness",
                "comparison": "equals", "threshold": mm(4),
                "type": "geometric", "verification": "exact_geometry",
                "strength": "hard", "source": "user", "state": "accepted"}],
            "components": [{
                "id": "p", "name": "Plate", "material": "pla_fdm",
                "parameters": [
                    {"id": "plate_width", "value": mm(30)},
                    {"id": "plate_depth", "value": mm(30)},
                    {"id": "plate_thickness", "value": mm(4)}],
                "features": [{"id": "body", "kind": "box", "parameters": {
                    "size": {"vector": order, "unit": "mm"}}}]}],
        }
        document = Document.from_json(json.dumps(payload))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        return report, {
            r.gate.identifier: r for r in report.gate_results}

    def test_the_wrong_plane_is_finally_visible(self) -> None:
        """The original disaster: every dimension right, the part sideways."""
        report, gates = self._verify(
            ["plate_width", "plate_thickness", "plate_depth"])
        self.assertEqual(gates["REQ_THICK"].evidence.status.value, "PASS",
                         "the plate really is 4 mm thick -- that was never "
                         "the lie")
        self.assertEqual(
            gates["GEOM_BUILD_ORIENTATION"].evidence.status.value, "FAIL")
        self.assertIn("its thinnest direction",
                      gates["GEOM_BUILD_ORIENTATION"].evidence.detail["hint"])

    def test_a_plate_lying_flat_passes_it(self) -> None:
        _, gates = self._verify(
            ["plate_width", "plate_depth", "plate_thickness"])
        self.assertEqual(
            gates["GEOM_BUILD_ORIENTATION"].evidence.status.value, "PASS")

    def test_the_orientation_gate_never_blocks_a_release(self) -> None:
        """A convention with a legitimate exception -- a vertical web is a
        real part -- so it reports and does not refuse."""
        report, gates = self._verify(
            ["plate_width", "plate_thickness", "plate_depth"])
        self.assertFalse(gates["GEOM_BUILD_ORIENTATION"].gate.critical)
        self.assertEqual(report.overall_status.value, "PASS")
        self.assertEqual(list(report.release_reasons), [])

    def test_the_report_carries_what_each_dimension_drives(self) -> None:
        report, _ = self._verify(
            ["plate_width", "plate_thickness", "plate_depth"])
        said = " ".join(report.measurements["part"]["dimensions"])
        self.assertIn("plate_thickness: drives the y extent", said)

    def test_the_worked_example_passes_both(self) -> None:
        """The fragment shown to every designer must not trip its own gates.

        It caught a real defect in the first draft of the inert-dimension
        gate: `boss_diameter` moves nearly 4,000 mm^3 and was being read as
        driving nothing, because the noise floor was taken from the width of
        a coarse octree enclosure rather than from the change itself.
        """
        import json

        from forge_ir import SCHEMA_VERSION
        from forge_ir.spec import composition_component
        from forge_pipeline import verify_component

        payload = {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-00000000d001",
            "project_id": "00000000-0000-4000-8000-00000000d0ff",
            "name": "Bracket", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [dict(composition_component())],
        }
        document = Document.from_json(json.dumps(payload))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        failing = [
            r.gate.identifier for r in report.gate_results
            if r.evidence.status.value == "FAIL" and r.gate.critical
        ]
        self.assertEqual(failing, [])


class FindingsMustNotBeQuieterThanTheVerdict(unittest.TestCase):
    """A non-critical gate is excluded from the decision, not from the reader.

    A spacer whose brief asked for a 30 mm SQUARE plate came back 30 x 12,
    because the base box carried the POST's diameter in its second slot.
    Every number in the document was correct, so every dimensional
    requirement passed, and the run ended on `completed` under the heading
    `Overall status: PASS`. The only thing in the whole run that had noticed
    was one non-critical FAIL, printed among fifteen PASSes.
    """

    @staticmethod
    def _spacer(y_driver):
        import json

        from forge_ir import SCHEMA_VERSION

        def mm(value):
            return {"magnitude": float(value), "unit": "mm"}

        return json.dumps({
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-00000000e001",
            "project_id": "00000000-0000-4000-8000-00000000e0ff",
            "name": "Spacer", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "assumptions": [], "requirements": [],
            "components": [{
                "id": "s", "name": "Spacer", "material": "pla_fdm",
                "parameters": [
                    {"id": "base_width", "value": mm(30)},
                    {"id": "base_height", "value": mm(4)},
                    {"id": "post_diameter", "value": mm(12)},
                    {"id": "post_height", "value": mm(10)}],
                "features": [
                    {"id": "base", "kind": "box", "parameters": {
                        "size": {"vector": ["base_width", y_driver,
                                            "base_height"], "unit": "mm"},
                        "centered": True}},
                    {"id": "post", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "post_diameter",
                                     "unit": "mm"},
                        "height": {"expression": "post_height", "unit": "mm"},
                        "origin": {"vector": [0, 0, "base_height / 2"],
                                   "unit": "mm"}}},
                    {"id": "body", "kind": "union",
                     "inputs": ["base", "post"]}]}],
        })

    def _report(self, y_driver):
        from forge_pipeline import verify_component

        document = Document.from_json(self._spacer(y_driver))
        return verify_component(
            document, document.components[0], measurement_depth=8)

    def test_the_slip_is_named_in_the_report(self) -> None:
        """`post_diameter: drives the y extent` on a part whose plate is
        supposed to be square. The defect in five words."""
        rendered = self._report("post_diameter").render()
        self.assertIn("each dimension, and what it actually drives", rendered)
        self.assertIn("post_diameter: drives the y extent", rendered)

    def test_the_part_as_asked_reads_differently(self) -> None:
        rendered = self._report("base_width").render()
        self.assertNotIn("post_diameter: drives the y extent", rendered)

    def test_a_non_critical_failure_is_surfaced_beside_the_verdict(self) -> None:
        """The plate stood on its edge: a finding that does not block."""
        import json

        from forge_ir import SCHEMA_VERSION
        from forge_pipeline import verify_component

        def mm(value):
            return {"magnitude": float(value), "unit": "mm"}

        document = Document.from_json(json.dumps({
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-00000000e001",
            "project_id": "00000000-0000-4000-8000-00000000e0ff",
            "name": "Plate", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "assumptions": [], "requirements": [],
            "components": [{
                "id": "p", "name": "Plate", "material": "pla_fdm",
                "parameters": [
                    {"id": "plate_width", "value": mm(30)},
                    {"id": "plate_depth", "value": mm(30)},
                    {"id": "plate_thickness", "value": mm(4)}],
                "features": [{"id": "body", "kind": "box", "parameters": {
                    "size": {"vector": ["plate_width", "plate_thickness",
                                        "plate_depth"], "unit": "mm"}}}]}],
        }))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        self.assertEqual(report.overall_status.value, "PASS")
        self.assertTrue(report.warnings, "a failed non-critical gate is a "
                                         "finding and must be reported")
        self.assertIn("GEOM_BUILD_ORIENTATION", report.warnings[0])
        self.assertIn("Worth looking at (does not block release)",
                      report.render())
        self.assertIn("warnings", report.as_dict())

    def test_a_clean_part_carries_no_warnings(self) -> None:
        self.assertEqual(self._report("base_width").warnings, ())

    def test_thinness_is_read_off_the_part_not_off_the_nudge(self) -> None:
        """The first version ranked axes by how far each extent moved when
        its dimension was nudged -- the size of the NUDGE, not of the part.
        A 30 x 12 x 14 spacer was called thin along y on that basis."""
        from forge_pipeline import verify_component

        document = Document.from_json(self._spacer("post_diameter"))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        gate = {r.gate.identifier: r for r in report.gate_results}
        orientation = gate.get("GEOM_BUILD_ORIENTATION")
        if orientation is not None:
            extents = orientation.evidence.detail.get("extent_mm", {})
            if extents:
                self.assertGreater(extents.get("x", 0), 20.0,
                                   "the x extent is the part's 30 mm, not a "
                                   "nudge")


class AnAngleStatedInABriefBecomesGeometry(unittest.TestCase):
    """`pattern_circular` in the words a brief uses.

    "Two set screws 90 degrees apart" is one number and a relationship, and
    until this existed the only angle a circular pattern took was the span
    from the first copy to the last -- so the designer had to work out that
    two copies spanning 90 degrees means a step of 90, three copies 120 apart
    means a span of 240, and every count changes the arithmetic. It did not
    work it out. It placed the holes with a millimetre vector, declared an
    angle parameter nothing read, and the run ended with no part.

    The number the brief states now goes straight into a field.
    """

    @staticmethod
    def _ring(parameters):
        from forge_geom.sdf import CylinderSDF
        from forge_kernel.implicit_backend import (
            BuildContext,
            SolidProduct,
            _build_pattern_circular,
        )

        source = SolidProduct(
            solid=CylinderSDF(base=(10.0, 0.0, -2.0), axis=(0, 0, 1),
                              radius=2.0, height=4.0),
            entities=(),
        )
        return _build_pattern_circular(BuildContext(
            feature_id="ring", kind="pattern_circular", role="ring",
            parameters=parameters, inputs=(source,))).solid

    @staticmethod
    def _at(degrees, radius=10.0):
        turn = math.radians(degrees)
        return [radius * math.cos(turn), radius * math.sin(turn), 0.0]

    def _inside(self, solid, *angles):
        points = np.array([self._at(a) for a in angles], dtype=float)
        return [float(d) < 0.0 for d in solid(points)]

    def _base(self):
        return {"count": 2, "axis_origin": (0.0, 0.0, 0.0),
                "axis_direction": (0.0, 0.0, 1.0)}

    def test_two_things_ninety_degrees_apart(self) -> None:
        solid = self._ring({**self._base(), "step_angle": math.radians(90)})
        self.assertEqual(self._inside(solid, 0, 90), [True, True])
        self.assertEqual(self._inside(solid, 180, 270), [False, False])

    def test_three_things_a_hundred_and_twenty_apart(self) -> None:
        solid = self._ring({
            **self._base(), "count": 3, "step_angle": math.radians(120)})
        self.assertEqual(self._inside(solid, 0, 120, 240), [True] * 3)
        self.assertEqual(self._inside(solid, 60, 180), [False, False])

    def test_the_step_is_between_neighbours_not_across_the_span(self) -> None:
        """The whole reason for the field. `total_angle` of 90 over three
        copies puts them 45 apart; `step_angle` of 90 puts them 90 apart,
        which is what "90 degrees apart" says however many there are."""
        span = self._ring({
            **self._base(), "count": 3, "total_angle": math.radians(90)})
        step = self._ring({
            **self._base(), "count": 3, "step_angle": math.radians(90)})
        self.assertEqual(self._inside(span, 45, 90), [True, True])
        self.assertEqual(self._inside(step, 45), [False])
        self.assertEqual(self._inside(step, 90, 180), [True, True])

    def test_the_old_spelling_is_untouched(self) -> None:
        """`total_angle` and the full circle behave exactly as before."""
        arc = self._ring({**self._base(), "total_angle": math.radians(90)})
        self.assertEqual(self._inside(arc, 0, 90), [True, True])
        whole = self._ring({**self._base(), "count": 4})
        self.assertEqual(self._inside(whole, 0, 90, 180, 270), [True] * 4)

    def test_a_pattern_is_placed_one_way_or_the_other(self) -> None:
        """Both angles at once is the design disagreeing with itself about
        where the copies are, and picking a winner silently would build a
        part half the document describes differently."""
        from forge_kernel import BackendError

        with self.assertRaises(BackendError) as caught:
            self._ring({**self._base(), "step_angle": math.radians(90),
                        "total_angle": math.radians(45)})
        self.assertIn("not by both", str(caught.exception))

    def test_the_catalogue_declares_it_as_an_angle(self) -> None:
        from forge_ir.features import FEATURE_SPECS

        sorts = {
            parameter.name: parameter.sort
            for parameter in FEATURE_SPECS["pattern_circular"].parameters
        }
        self.assertEqual(sorts["step_angle"], "angle")
        self.assertEqual(sorts["total_angle"], "angle")
        self.assertFalse(
            next(p for p in FEATURE_SPECS["pattern_circular"].parameters
                 if p.name == "step_angle").required,
            "a pattern that spreads evenly round the circle needs neither",
        )
