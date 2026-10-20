"""Five unusual briefs on Claude Sonnet 5: an anatomical calf shell, four
ways, and an exoskeleton side rail.

None of them released, and most of what stopped them was Forge's:

- a brief interpreter cut off at its length limit, read as if the brief had
  stated nothing;
- `w / 2 + 10` in a millimetre parameter, refused at compile;
- one pivot hole "through each tab" counted as one hole in all;
- an 8 mm shell on a lofted calf built 14 mm thick, with a sealed floor
  across the inside at every loft section;
- a height the brief gave the body held against the whole part;
- two different 12 mm dimensions merged into one, and the analyst counting
  parameter positions and editing the wrong one;
- a blend swelling 0.37 mm past a rail's sides;
- a cutout drawn about the plate's corner, notching its edge.

And some were the model's, and passed anyway: mounting holes 130 mm apart
where the brief said 60, mounting holes run on through the facing wall of a
hollow shell, an access opening cut too shallow for a tapering wall, and two
bosses floating in the air behind the calf. Each is now measured on the part.
"""

from __future__ import annotations

import copy
import json
import pathlib
import unittest

HERE = pathlib.Path(__file__).parent / "fixtures" / "real_runs"


def _load(name: str) -> dict:
    return json.loads((HERE / f"{name}.json").read_text())


def _record(case: dict):
    from forge_roles import RequirementsEngineer

    return RequirementsEngineer().parse(case["requirements"],
                                        brief=case["brief"])


def _designed(case: dict, document: dict | None = None):
    from forge_roles import ForgeIRDesigner
    from forge_roles.library import Intent

    return ForgeIRDesigner().parse(
        {"rationale": "r", "document": copy.deepcopy(
            document or case["document"])},
        requirements=_record(case),
        intent=Intent(summary="s", part_kind="", stated=(), implied=(),
                      unstated=()),
        brief=case["brief"], document_id="", project_id="", answers={})


def _verify(draft):
    from forge_pipeline import verify_component

    return verify_component(draft.document, draft.document.components[0],
                            measurement_depth=7)


def _failing(report) -> dict:
    return {r.gate.identifier: r.status.value for r in report.gate_results
            if r.status.value not in ("PASS", "NOT_APPLICABLE")}


def _part(draft):
    from forge_pipeline.verify import Compiler

    return Compiler().compile_component(draft.document.components[0])


def _measure(draft, part, binding: str):
    from forge_pipeline.measure import resolve_measurement
    from forge_pipeline.verify import measure_mass_properties, refine_extents

    properties = refine_extents(part.solid, measure_mass_properties(
        part.solid, max_depth=6))
    return resolve_measurement(binding, component=draft.document.components[0],
                               part=part, properties=properties)


class AnAnswerCutOffIsNotAnAnswer(unittest.TestCase):
    """Three runs: the interpreter's 2048 tokens ran out after `summary`,
    and the run went on with "0 stated facts"."""

    def test_it_is_asked_again_with_room(self) -> None:
        from forge_models import ScriptedProvider
        from forge_roles import BriefInterpreter

        cut = {"_stop_reason": "max_tokens", "summary": "a calf shell",
               "part_kind": "shell"}
        whole = {"summary": "a calf shell", "part_kind": "shell",
                 "stated": ["330 mm tall", "8 mm walls"], "implied": [],
                 "unstated": ["material"], "out_of_scope": [],
                 "risk_signals": [], "suggested_name": "calf"}
        provider = ScriptedProvider([cut, whole])
        result = BriefInterpreter().run(provider, brief="a calf, 330 mm tall")
        self.assertEqual(result.value.stated, ("330 mm tall", "8 mm walls"))
        self.assertEqual(result.attempts, 1)
        self.assertGreater(provider.requests[1].max_output_tokens,
                           provider.requests[0].max_output_tokens)

    def test_a_cap_is_a_cap(self) -> None:
        from forge_models import ScriptedProvider
        from forge_roles import BriefInterpreter

        role = BriefInterpreter()
        role.output_token_ceiling = role.max_output_tokens
        cut = {"_stop_reason": "max_tokens", "summary": "a calf shell",
               "part_kind": "shell", "unstated": ["material"]}
        whole = {"summary": "a calf shell", "part_kind": "shell",
                 "stated": ["330 mm tall"], "implied": [],
                 "unstated": ["material"], "out_of_scope": [],
                 "risk_signals": [], "suggested_name": "calf"}
        provider = ScriptedProvider([cut, whole])
        result = role.run(provider, brief="a calf")
        # Never past the cap -- and a cut-off answer is not taken as whole:
        # it is asked for again, shorter, within the same cap.
        self.assertEqual({r.max_output_tokens for r in provider.requests},
                         {role.max_output_tokens})
        self.assertIn("SHORTER", provider.requests[1].messages[-1].content)
        self.assertEqual(result.value.stated, ("330 mm tall",))


class ANumberAddedToALength(unittest.TestCase):
    """`rear_opening_width / 2 + 10` and `mounting_hole_diameter + 8`, each a
    millimetre parameter: refused at compile, two runs with no part."""

    def test_both_compile(self) -> None:
        for name in ("calf_bare_offset_claude", "calf_boss_diameter_claude"):
            with self.subTest(name):
                draft = _designed(_load(name))
                self.assertTrue(any("a bare number added to" in n
                                    for n in draft.notes))
                _part(draft)

    def test_a_ratio_is_left_alone(self) -> None:
        from forge_roles.library import _a_number_added_to_a_length

        component = {"parameters": [
            {"id": "w", "value": {"magnitude": 60, "unit": "mm"}},
            {"id": "h", "expression": "w / 2", "unit": "mm"},
            {"id": "k", "expression": "w / 2 + 10", "unit": "mm"}],
            "features": []}
        _a_number_added_to_a_length(component)
        self.assertEqual(component["parameters"][1]["expression"], "w / 2")
        self.assertEqual(component["parameters"][2]["expression"],
                         "w / 2 + 10 * mm")


class HolesCountedPerSomething(unittest.TestCase):
    def test_one_through_each_tab_is_no_total(self) -> None:
        from forge_roles.library import _the_holes_the_brief_states

        for name in ("calf_430_overall_claude", "calf_bare_offset_claude"):
            with self.subTest(name):
                added: list = []
                _the_holes_the_brief_states(_load(name)["brief"], added)
                self.assertNotIn("holes_of_diameter:8.5",
                                 [r["measurement"] for r in added])
                self.assertIn("holes_of_diameter:4.5",
                              [r["measurement"] for r in added])

    def test_a_decimal_point_ends_no_clause(self) -> None:
        from forge_roles.library import _the_holes_the_brief_states

        added: list = []
        _the_holes_the_brief_states(
            "Tabs at each end, each extending 37.5 mm beyond the body with a "
            "centred 8.5 mm pivot hole.", added)
        self.assertEqual(added, [])


class AShellOnALoft(unittest.TestCase):
    """Asked for 8 mm walls: 14.07 mm, and a sealed floor across the inside
    at every section the calf was lofted through."""

    def test_the_wall_is_the_wall_asked_for(self) -> None:
        draft = _designed(_load("calf_430_overall_claude"))
        part = _part(draft)
        wall = _measure(draft, part, "wall_thickness")
        magnitude = wall.value.magnitude
        self.assertAlmostEqual(float(magnitude.lo), 8.0, delta=0.05)
        self.assertAlmostEqual(float(magnitude.hi), 8.0, delta=0.05)

    def test_nothing_walls_the_inside_off(self) -> None:
        import numpy as np

        part = _part(_designed(_load("calf_430_overall_claude")))
        zs = np.linspace(-1.0, 331.0, 3321)
        line = np.stack([np.full_like(zs, 25.0), np.zeros_like(zs), zs], 1)
        inside = np.asarray(part.solid(line)) < 0.0
        runs = int(np.count_nonzero(inside[1:] & ~inside[:-1]) + inside[0])
        self.assertEqual(runs, 2, "a closed bottom and a closed top, only")

    def test_a_stacked_loft_keeps_its_slope_bounded(self) -> None:
        import numpy as np

        from forge_geom.sdf import LoftSDF, RectangleProfile, stack_lofts

        outlines = [RectangleProfile((0.0, 0.0), w / 2, d / 2, 12.0)
                    for w, d in ((85, 80), (95, 90), (115, 110), (120, 115))]
        heights = (0.0, 80.0, 190.0, 260.0)
        lofts = [LoftSDF(outlines[i], outlines[i + 1], (0.0, 0.0, heights[i]),
                         (1, 0, 0), (0, 1, 0), (0, 0, 1),
                         heights[i + 1] - heights[i]) for i in range(3)]
        stacked = stack_lofts(lofts[::-1])
        self.assertEqual(len(stacked), 1)
        points = np.random.default_rng(1).uniform(
            [-90, -90, -30], [90, 90, 290], (40000, 3))
        slope = np.linalg.norm(stacked[0].gradient(points, step=1e-4), axis=1)
        self.assertLessEqual(float(slope.max()), stacked[0].lipschitz + 1e-6)
        union = np.min(np.stack([loft(points) for loft in lofts]), axis=0)
        self.assertTrue(np.array_equal(union < 0, stacked[0](points) < 0))


class AHeightTheBodyHas(unittest.TestCase):
    def test_a_part_reaching_past_its_body_is_at_least_it(self) -> None:
        from forge_roles.library import _a_body_the_part_reaches_past

        for name in ("calf_coordinates_claude", "calf_bare_offset_claude"):
            with self.subTest(name):
                case = _load(name)
                record = [dict(r) for r in case["requirements"]["requirements"]]
                for r in record:
                    if r["measurement"] == "bounding_box_z":
                        r["comparison"] = "equals"
                _a_body_the_part_reaches_past(case["brief"], record)
                claim = next(r for r in record
                             if r["measurement"] == "bounding_box_z")
                self.assertEqual(claim["comparison"], "at_least")

    def test_a_brief_with_the_whole_height_keeps_it(self) -> None:
        from forge_roles.library import _a_body_the_part_reaches_past

        case = _load("calf_430_overall_claude")
        record = [dict(r) for r in case["requirements"]["requirements"]]
        _a_body_the_part_reaches_past(case["brief"], record)
        claim = next(r for r in record if r["measurement"] == "bounding_box_z")
        self.assertEqual(claim["comparison"], "equals")


class TwoDimensionsAtOneFigure(unittest.TestCase):
    def test_a_thickness_is_not_a_reach(self) -> None:
        """The design as the model wrote it -- the run's record holds it
        after the merge. Unmerged, the reach the record measures and nothing
        reads is put back to the designer, which is what it is: a dimension
        the tongue was not built from."""
        from forge_roles.base import RoleOutputError

        case = _load("calf_coordinates_claude")
        document = copy.deepcopy(case["document"])
        for parameter in document["components"][0]["parameters"]:
            if parameter["id"] in ("hinge_tongue_thickness_x",
                                   "lower_tongue_top_z"):
                figure = (12.0 if parameter["id"] == "hinge_tongue_thickness_x"
                          else 25.0)
                parameter.pop("expression", None)
                parameter.pop("unit", None)
                parameter["value"] = {"magnitude": figure, "unit": "mm"}
        with self.assertRaises(RoleOutputError) as raised:
            _designed(case, document)
        said = " ".join(raised.exception.problems)
        self.assertIn("hinge_tongue_extension_beyond_pivot", said)
        self.assertIn("no feature reads them", said)

    def test_two_sizes_that_say_different_things_stay_two(self) -> None:
        from forge_roles.library import _an_orphan_that_is_another_name

        component = {"parameters": [
            {"id": "tongue_thickness_x", "value": {"magnitude": 12.0,
                                                   "unit": "mm"}},
            {"id": "tongue_extension_beyond_pivot",
             "value": {"magnitude": 12.0, "unit": "mm"}},
            {"id": "base_leg_length", "value": {"magnitude": 50.0,
                                                "unit": "mm"}},
            {"id": "length", "value": {"magnitude": 50.0, "unit": "mm"}}],
            "features": [{"id": "b", "kind": "box", "parameters": {
                "size": {"vector": ["length", "tongue_thickness_x", 4],
                         "unit": "mm"}}}]}
        notes, left = _an_orphan_that_is_another_name(
            component, ["tongue_extension_beyond_pivot", "base_leg_length"])
        self.assertEqual(left, ["tongue_extension_beyond_pivot"])
        self.assertEqual(len(notes), 1)
        self.assertIn("base_leg_length", notes[0])

    def test_a_dead_duplicate_is_dropped(self) -> None:
        draft = _designed(_load("calf_coordinates_claude"))
        names = {p["id"] for p in draft.payload["components"][0]["parameters"]}
        self.assertNotIn("overall_height", names)
        self.assertIn("z_section_5", names)


class TheSideRail(unittest.TestCase):
    """Its mounting holes 130 mm apart, where the brief said 60 and the
    record's parameter said 60; a cutout drawn about the plate's corner; a
    blend swelling past its sides; a boss nothing could count."""

    def test_what_the_model_got_wrong_is_found(self) -> None:
        report = _verify(_designed(_load("exoskeleton_side_rail_claude")))
        self.assertEqual(_failing(report),
                         {"REQ_HOLES_8_2MM_60MM_APART": "FAIL"})

    def test_built_as_asked_it_passes(self) -> None:
        case = _load("exoskeleton_side_rail_claude")
        document = copy.deepcopy(case["document"])
        for feature in document["components"][0]["features"]:
            if feature["id"] == "mounting_hole_1":
                feature["parameters"]["position"]["vector"][1] = (
                    "rail_length - mounting_hole_group_offset_from_top"
                    " - mounting_hole_spacing / 2")
            if feature["id"] == "mounting_hole_2":
                feature["parameters"]["position"]["vector"][1] = (
                    "rail_length - mounting_hole_group_offset_from_top"
                    " + mounting_hole_spacing / 2")
        self.assertEqual(_failing(_verify(_designed(case, document))), {})

    def test_the_cutout_is_moved_off_the_edge(self) -> None:
        draft = _designed(_load("exoskeleton_side_rail_claude"))
        sketch = next(f for f in draft.payload["components"][0]["features"]
                      if f["id"] == "weight_cutout_profile")
        xs = [str(p[0]) for p in sketch["parameters"]["points"]["points"]]
        self.assertTrue(all("rail_width / 2" in x for x in xs), xs)

    def test_a_boss_it_already_claims_is_not_counted(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("exoskeleton_side_rail_claude")
        raw = copy.deepcopy(case["requirements"])
        raw["requirements"].append({
            "id": "REQ_PIVOT_REINFORCEMENT_BOSS_COUNT",
            "statement": "The rail shall have exactly one circular boss.",
            "measurement": "feature_count:boss", "comparison": "equals",
            "threshold": {"magnitude": 1, "unit": ""}, "source": "user"})
        record = RequirementsEngineer().parse(raw, brief=case["brief"])
        self.assertNotIn("REQ_PIVOT_REINFORCEMENT_BOSS_COUNT",
                         [r["id"] for r in record.requirements])


class TheCalfShells(unittest.TestCase):
    def test_what_the_model_got_wrong_is_found(self) -> None:
        report = _verify(_designed(_load("calf_430_overall_claude")))
        self.assertEqual(_failing(report), {
            "REQ_HOLES_4_5MM_ONE_WALL": "FAIL",
            "REQ_OPENINGS_210X60": "FAIL"})

    def test_built_as_asked_it_passes(self) -> None:
        case = _load("calf_430_overall_claude")
        document = copy.deepcopy(case["document"])
        for feature in document["components"][0]["features"]:
            if feature["id"] == "opening_cut_box":
                feature["parameters"]["size"]["vector"][1] = 60
            if feature["id"].startswith("mount_hole_"):
                vector = feature["parameters"]["position"]["vector"]
                vector[1] = 70
                feature["parameters"]["axis"] = [0, -1, 0]
                feature["parameters"]["depth"] = {"magnitude": 40,
                                                  "unit": "mm"}
        self.assertEqual(_failing(_verify(_designed(case, document))), {})

    def test_bosses_in_the_air_are_found(self) -> None:
        report = _verify(_designed(_load("calf_coordinates_claude")))
        failing = _failing(report)
        self.assertIn("GEOM_ONE_PIECE", failing)
        self.assertNotIn("GEOM_WATERTIGHT", failing)
        self.assertNotIn("REQ_BOUNDING_BOX_Z", failing)
        self.assertNotIn("GEOM_DIMENSIONS_DRIVE_THE_PART", failing)

    def test_an_interface_on_a_sketch_is_dropped(self) -> None:
        draft = _designed(_load("calf_430_overall_claude"))
        self.assertNotIn("rear_access", [
            i["id"] for i in draft.payload["components"][0]["interfaces"]])


class TheAnalystsAddresses(unittest.TestCase):
    def test_a_parameter_miscounted_is_caught(self) -> None:
        from forge_roles.library import _patches_aimed_at_another_feature

        component = _load("calf_coordinates_claude")["document"][
            "components"][0]
        index = [p["id"] for p in component["parameters"]].index("z_section_4")
        problems = _patches_aimed_at_another_feature(
            [{"op": "remove",
              "pointer": f"/components/0/parameters/{index}/value",
              "reason": "z_section_5 duplicates overall_height"}],
            {"/components/0": component})
        self.assertEqual(len(problems), 1)
        self.assertIn("z_section_5", problems[0])

    def test_an_insertion_is_not_an_aim(self) -> None:
        from forge_roles.library import _patches_aimed_at_another_feature

        component = _load("calf_coordinates_claude")["document"][
            "components"][0]
        problems = _patches_aimed_at_another_feature(
            [{"op": "add", "pointer": "/components/0/features/3",
              "value": {}, "reason": "a rib after plane3"}],
            {"/components/0": component})
        self.assertEqual(problems, [])

    def test_a_step_removed_from_a_chain_closes_it(self) -> None:
        from forge_roles.patch import Patch, apply_patches

        document = _load("calf_430_overall_claude")["document"]
        patched = apply_patches(document, [Patch(
            op="remove", pointer="/components/0/features/mount_hole_2l",
            reason="surplus")])
        features = {f["id"]: f for f in patched["components"][0]["features"]}
        self.assertNotIn("mount_hole_2l", features)
        self.assertEqual(features["mount_hole_2r"]["inputs"],
                         ["mount_hole_1r"])


if __name__ == "__main__":
    unittest.main()


class TheSecondRound(unittest.TestCase):
    """The same briefs again, on the fixes above, and what they showed next:
    a tab rounded past half its thickness, a plate whose top-edge chamfer
    had nowhere to go, a mounting hole drilled where the pivot was, a floor
    read against a tab hanging below it -- and an analyst that wrote each
    fix out in words and then gave up, because it had been told a different
    construction was a reason to stop."""

    def test_a_tab_rounded_past_half_its_side_compiles(self) -> None:
        draft = _designed(_load("calf_tab_corners_claude"))
        self.assertTrue(any("past half the shorter side" in n
                            for n in draft.notes))
        _part(draft)

    def test_the_stepper_plate_releases(self) -> None:
        draft = _designed(_load("stepper_plate_chamfer_claude"))
        self.assertTrue(any("chamfered by" in n for n in draft.notes))
        self.assertEqual(_failing(_verify(draft)), {})

    def test_a_box_rounded_upright_is_limited_by_its_footprint(self) -> None:
        from forge_roles.library import _a_corner_rounder_than_its_side

        component = {"parameters": [], "features": [{"id": "b", "kind": "box",
            "parameters": {"size": {"vector": [120, 80, 8], "unit": "mm"},
                           "edge_radius": {"magnitude": 10, "unit": "mm"},
                           "edges": "vertical"}}]}
        self.assertEqual(_a_corner_rounder_than_its_side(component), [])
        component["features"][0]["parameters"]["edges"] = "all"
        self.assertTrue(_a_corner_rounder_than_its_side(component))

    def test_two_holes_down_one_line_are_refused(self) -> None:
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as raised:
            _designed(_load("side_rail_coincident_holes_claude"))
        said = " ".join(raised.exception.problems)
        self.assertIn("`mounting_hole_1` and `pivot_hole`", said)

    def test_two_holes_down_one_line_count_once(self) -> None:
        from forge_ir import Document

        case = _load("side_rail_coincident_holes_claude")
        built = Document.from_json(json.dumps(case["document"]))

        class Draft:
            document = built

        part = _part(Draft)
        holes = _measure(Draft, part, "holes_of_diameter:8.2")
        self.assertEqual(float(holes.value.magnitude.midpoint), 2.0)

    def test_a_thickness_except_at_the_boss_is_not_the_part_s(self) -> None:
        record = _record(_load("side_rail_coincident_holes_claude"))
        claim = next(r for r in record.requirements
                     if r["measurement"] == "bounding_box_z")
        self.assertEqual(claim["comparison"], "at_least")

    def test_a_floor_is_read_from_the_walls_not_a_tab(self) -> None:
        from forge_ir import Document

        case = _load("calf_round_opening_claude")
        built = Document.from_json(json.dumps(case["document"]))

        class Draft:
            document = built

        floor = _measure(Draft, _part(Draft), "floor_thickness")
        self.assertGreater(float(floor.value.magnitude.midpoint), 7.9)

    def test_json_written_on_inside_a_string_is_put_back(self) -> None:
        from forge_models.leaks import recover_leaked_fields
        from forge_roles import FailureAnalyst

        schema = FailureAnalyst().output_schema()
        out = recover_leaked_fields({
            "diagnosis": 'Two faults:\\n\\n1. holes miss.", "strategy": '
                         '"Abandon", "patches": []',
            "abandon": True, "abandon_reason": "x"}, schema)
        self.assertEqual(out["diagnosis"], "Two faults:\n\n1. holes miss.")
        self.assertEqual(out["strategy"], "Abandon")
        self.assertEqual(out["patches"], [])

    def test_the_analyst_knows_a_construction_change_is_a_patch(self) -> None:
        from forge_roles import FailureAnalyst

        prompt = FailureAnalyst().system_prompt()
        self.assertIn("A different construction is a patch too", prompt)
        self.assertIn("`box` (size", prompt)
        self.assertNotIn("the design needs a different\nconstruction", prompt)


class TheRewordedBrief(unittest.TestCase):
    """The calf shell once more, its brief reworded to state every
    coordinate. The design was wrong in four places -- each tab's rounded
    end drawn 15 mm short, so the part stood 400 mm of 430 and both pivots
    sat on the tab tips; four mounting holes drilled 20 mm from the middle of
    the hollow toward the shin, into air; an access cutter too shallow for
    the bulging rear wall -- and the analyst gave up on the first round,
    because Forge said two contradicting things about the holes and gave no
    numbers for any of it. Each failure now says where, in millimetres."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.draft = _designed(_load("calf_reworded_claude"))
        cls.report = _verify(cls.draft)
        cls.by_id = {r.gate.identifier: r for r in cls.report.gate_results}

    def _hint(self, gate: str) -> str:
        return str(self.by_id[gate].evidence.detail.get("hint", ""))

    def test_it_still_fails_where_the_design_is_wrong(self) -> None:
        failing = _failing(self.report)
        for gate in ("REQ_BOUNDING_BOX_Z", "REQ_HOLES_4_5MM",
                     "REQ_OPENINGS_210X60", "GEOM_FEATURES_CONTRIBUTE"):
            self.assertEqual(failing.get(gate), "FAIL", gate)

    def test_a_hole_that_cut_nothing_says_where_the_wall_is(self) -> None:
        hint = self._hint("GEOM_FEATURES_CONTRIBUTE")
        self.assertIn("`mount_hole_3` runs along y through (x=-36, z=165) "
                      "and cuts y = 0.0 to 20.0", hint)
        self.assertIn("material is at y = -58.8 to -50.8", hint)
        self.assertNotIn("put it on the centre line", hint)

    def test_a_pivot_off_its_tab_says_which_way_the_tab_is(self) -> None:
        # On the tab's tip, half the pivot's bore is on the part: it cut a
        # channel there, and is failed as a channel, with where the tab is.
        hint = self._hint("GEOM_HOLES_ARE_HOLES")
        self.assertIn("`pivot_hole_lower`, centred at (0, 0, -35)", hint)
        self.assertIn("along z, material at -30.6 to 25.1", hint)

    def test_a_hole_that_never_cut_is_not_said_to_be_filled_in(self) -> None:
        hint = self._hint("GEOM_BORES_SURVIVE")
        self.assertIn("never cut any material", hint)
        self.assertNotIn("filled", hint.replace("Nothing filled it in", ""))

    def test_the_height_says_where_it_starts_and_ends(self) -> None:
        detail = self.by_id["REQ_BOUNDING_BOX_Z"].evidence.detail
        self.assertEqual(detail.get("spans"), "z = -35.0 to 365.0 mm")

    def test_a_shallow_opening_says_where_the_wall_still_stands(self) -> None:
        hint = self._hint("REQ_OPENINGS_210X60")
        self.assertIn("Through the nearest one", hint)
        self.assertIn("z=141: -54.7 to -46.7, 38.3 to 46.3", hint)

    def test_a_hole_that_grazes_a_wall_is_a_groove_not_a_hole(self) -> None:
        """The two lowest mounting holes, drilled into the hollow, nicked
        the side wall 0.75 mm deep and counted as open holes."""
        holes = self.by_id["REQ_HOLES_4_5MM"].evidence
        self.assertEqual(float(holes.result.magnitude.midpoint), 0.0)
        self.assertIn("mount_hole_1", holes.detail.get("not_holes", []))
        notched = self.by_id["GEOM_HOLES_ARE_HOLES"].evidence.detail["notched"]
        self.assertIn("mount_hole_1", [e["feature"] for e in notched])

    def test_each_hole_the_brief_places_is_claimed_where_it_is(self) -> None:
        claims = {r["measurement"]: r for r in _record(
            _load("calf_reworded_claude")).requirements}
        self.assertIn("hole_at:4.5:-36,*,165", claims)
        self.assertIn("hole_at:8.5:0,0,-37.5", claims)
        self.assertEqual(claims["hole_at:8.5:0,0,367.5"]["comparison"],
                         "at_least")
        failing = _failing(self.report)
        self.assertEqual(failing.get("REQ_HOLE_8_5MM_AT_0_0_M37_5"), "FAIL")

    def test_a_hole_where_the_brief_puts_it_is_found_there(self) -> None:
        from forge_ir import Document

        case = _load("calf_reworded_claude")
        document = copy.deepcopy(case["document"])
        for feature in document["components"][0]["features"]:
            if feature["id"] == "mount_hole_1":
                feature["parameters"]["position"] = {
                    "vector": [-36, -30, 50], "unit": "mm"}
                feature["parameters"]["axis"] = [0, -1, 0]
        built = Document.from_json(json.dumps(document))

        class Draft:
            document = built

        part = _part(Draft)
        here = _measure(Draft, part, "hole_at:4.5:-36,*,50")
        self.assertEqual(float(here.value.magnitude.midpoint), 1.0)
        there = _measure(Draft, part, "hole_at:4.5:-36,*,51")
        self.assertEqual(float(there.value.magnitude.midpoint), 0.0)
        self.assertIn("1.00 mm from (x=-36, z=51)", there.detail["hint"])

    def test_the_analyst_is_shown_the_numbers_whole(self) -> None:
        from forge_orchestrator.orchestrator import _gate_failure

        failure = _gate_failure(self.by_id["GEOM_FEATURES_CONTRIBUTE"])
        self.assertIn("`mount_hole_6` runs along y", failure["how_to_fix"])
        failure = _gate_failure(self.by_id["REQ_BOUNDING_BOX_Z"])
        self.assertIn("-35.0 to 365.0", failure["where"])


class AnAbandonOnTheFirstRound(unittest.TestCase):
    """Giving up before any edit, on a design whose checks failed, is asked
    once to write the edits it can; given again, the abandon is kept."""

    ANSWER = {"diagnosis": "Six faults, not one field.", "strategy": "None.",
              "patches": [], "abandon": True,
              "abandon_reason": "Not clearly attributable to one edit."}
    FAILURE = {"kind": "gate_failure", "failed_gates": []}

    def _parse(self, **inputs):
        from forge_roles import FailureAnalyst

        return FailureAnalyst().parse(self.ANSWER, document_slice={},
                                      **inputs)

    def test_it_is_asked_once_to_write_what_it_can(self) -> None:
        from forge_roles import FailureAnalyst
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as raised:
            self._parse(failure=self.FAILURE, attempt=1, previous_attempts=())
        said = " ".join(raised.exception.problems)
        self.assertIn("before any edit has been tried", said)
        kept = FailureAnalyst().salvage(self.ANSWER, raised.exception.problems)
        self.assertTrue(kept.abandon)
        self.assertIn("Not clearly attributable", kept.abandon_reason)

    def test_after_a_round_of_edits_it_is_the_analyst_s_call(self) -> None:
        proposal = self._parse(failure=self.FAILURE, attempt=2,
                               previous_attempts=[{"trigger": "gate"}])
        self.assertTrue(proposal.abandon)

    def test_a_compile_failure_is_the_analyst_s_call(self) -> None:
        proposal = self._parse(failure={"kind": "compile_failure"}, attempt=1,
                               previous_attempts=())
        self.assertTrue(proposal.abandon)

    def test_the_second_abandon_ends_the_role_with_it(self) -> None:
        from forge_models.fixtures import ScriptedProvider
        from forge_roles import FailureAnalyst

        provider = ScriptedProvider([self.ANSWER, self.ANSWER])
        result = FailureAnalyst().run(
            provider, failure=self.FAILURE, document_slice={}, attempt=1,
            previous_attempts=())
        self.assertTrue(result.value.abandon)
        self.assertEqual(result.attempts, 2)


class HolesAtTheBriefsCoordinates(unittest.TestCase):
    """Where the brief sets its own origin and puts holes at points in it,
    each point is a claim on the part."""

    def _claims(self, brief: str) -> list[str]:
        from forge_roles.library import (
            _holes_at_the_coordinates_the_brief_gives)

        requirements: list = []
        _holes_at_the_coordinates_the_brief_gives(brief, requirements)
        return [r["measurement"] for r in requirements]

    def test_a_list_ending_comma_and_keeps_its_last_point(self) -> None:
        said = self._claims(
            "The origin is at the centre of the bottom face. Create six 4.5 "
            "mm diameter mounting holes at X/Z coordinates (-36,50), (36,50), "
            "(-36,165), (36,165), (-36,280), and (36,280).")
        self.assertEqual(len(said), 6)
        self.assertIn("hole_at:4.5:36,*,280", said)

    def test_a_point_given_coordinate_by_coordinate(self) -> None:
        said = self._claims(
            "The origin is at the centre of the base. Each tab has one 8.5 mm "
            "pivot hole drilled along X, the lower one centred at X=0, Y=0, "
            "Z=-37.5 and the upper one at X=0, Y=0, Z=367.5.")
        self.assertEqual(said, ["hole_at:8.5:0,0,-37.5",
                                "hole_at:8.5:0,0,367.5"])

    def test_no_origin_no_claim(self) -> None:
        self.assertEqual(self._claims(
            "A 5 mm hole centred at X=10, Y=20 through the plate."), [])

    def test_two_sizes_in_one_sentence_no_claim(self) -> None:
        self.assertEqual(self._claims(
            "Origin at the corner. A 5 mm hole and an 8 mm hole at X/Y "
            "positions (10, 10) and (30, 10)."), [])


class TheThirdRound(unittest.TestCase):
    """The calf shell and the stepper plate once more, on Claude, and what
    they showed: an analyst's patches given as text that took the run down;
    an opening on the rear wall cut through the front because an XZ plane's
    offset ran along its -Y normal; a tab end rounded across a 12 mm side,
    3 mm short; a 400 mm cutter through an 8 mm wall called a cutter that did
    nothing; two tabs as one pattern counted as one; and one bad repair
    ending the run as a conflict between requirements."""

    @staticmethod
    def _built(document):
        from forge_ir import Document

        built = Document.from_json(json.dumps(document))

        class Draft:
            pass

        Draft.document = built
        return Draft

    def test_an_xz_plane_sits_at_its_offset_in_y(self) -> None:
        case = _load("calf_tabs_and_opening_claude")
        draft = self._built(case["document"])
        part = _part(draft)
        rear = _measure(draft, part, "windows_of_size:210x60:-y")
        front = _measure(draft, part, "windows_of_size:210x60:+y")
        self.assertEqual(float(rear.value.magnitude.midpoint), 1.0)
        self.assertEqual(float(front.value.magnitude.midpoint), 0.0)
        self.assertIn("wrong wall (-y)", front.detail["hint"])

    def test_the_brief_s_rear_wall_is_claimed_on_its_side(self) -> None:
        record = _record(_load("calf_tabs_and_opening_claude"))
        bindings = [r["measurement"] for r in record.requirements]
        self.assertIn("windows_of_size:210x60:-y", bindings)

    def test_a_long_cutter_through_one_wall_contributed(self) -> None:
        from forge_evidence import EvidenceGraph
        from forge_pipeline.verify import _check_features_contribute

        case = _load("calf_tabs_and_opening_claude")
        draft = self._built(case["document"])
        part = _part(draft)
        results = _check_features_contribute(
            draft.document.components[0], part, EvidenceGraph(),
            part.part_hash)
        absent = [e["feature"] for e in
                  results[0].evidence.detail.get("absent", [])]
        self.assertNotIn("access_opening_cutter", absent)

    def test_a_tab_rounded_past_its_thickness_keeps_its_length(self) -> None:
        draft = _designed(_load("calf_tabs_and_opening_claude"))
        self.assertTrue(any("`edges: bottom_along_x`" in n
                            for n in draft.notes), draft.notes)
        import numpy as np

        part = _part(draft)
        # The tip where the brief puts it, the end round across its 30 mm
        # width, and full thickness right out to the tip.
        probe = np.array([[0.0, 0.0, -49.9], [0.0, 0.0, -50.1],
                          [0.0, 14.0, -49.0], [5.9, 0.0, -49.8],
                          [5.9, 14.5, 20.0]])
        inside = list(np.asarray(part.solid(probe)) < 0.0)
        self.assertEqual(inside, [True, False, False, True, True])

    def test_a_box_rounded_along_x_is_a_link(self) -> None:
        import numpy as np

        case = _load("calf_tabs_and_opening_claude")
        document = copy.deepcopy(case["document"])
        component = document["components"][0]
        component["features"] = [{
            "id": "link", "kind": "box", "parameters": {
                "size": {"vector": [12, 30, 75], "unit": "mm"},
                "origin": {"vector": [0, 0, -12.5], "unit": "mm"},
                "centered": True,
                "edge_radius": {"magnitude": 15, "unit": "mm"},
                "edges": "along_x"}}]
        component["parameters"], component["interfaces"] = [], []
        document["requirements"], document["assumptions"] = [], []
        part = _part(self._built(document))
        probe = np.array([[0, 0, -49.9], [0, 0, 24.9], [5.9, 0, -12.5],
                          [0, 14, -49], [0, 14, 24]])
        inside = list(np.asarray(part.solid(probe)) < 0.0)
        self.assertEqual(inside, [True, True, True, False, False])

    def test_a_tagged_pattern_counts_as_what_it_makes(self) -> None:
        case = _load("calf_tabs_and_opening_claude")
        draft = self._built(case["document"])
        counted = _measure(draft, _part(draft),
                           "feature_count:pattern_linear:hinge_tab")
        self.assertEqual(float(counted.value.magnitude.midpoint), 2.0)

    def test_a_hole_through_the_first_wall_finds_it(self) -> None:
        case = _load("calf_tabs_and_opening_claude")
        document = copy.deepcopy(case["document"])
        for feature in document["components"][0]["features"]:
            if feature["id"].startswith("mount_hole_"):
                feature["parameters"]["axis"] = [0, -1, 0]
                feature["parameters"]["through"] = "first_wall"
        draft = self._built(document)
        part = _part(draft)
        holes = _measure(draft, part, "holes_of_diameter:4.5")
        walls = _measure(draft, part, "walls_crossed:4.5")
        at = _measure(draft, part, "hole_at:4.5:36,*,280")
        self.assertEqual(float(holes.value.magnitude.midpoint), 6.0)
        self.assertEqual(float(walls.value.magnitude.midpoint), 1.0)
        self.assertEqual(float(at.value.magnitude.midpoint), 1.0)

    def test_a_hole_aimed_at_nothing_says_so(self) -> None:
        from forge_kernel import CompileError

        case = _load("calf_tabs_and_opening_claude")
        document = copy.deepcopy(case["document"])
        for feature in document["components"][0]["features"]:
            if feature["id"] == "mount_hole_1":
                feature["parameters"]["position"] = {
                    "vector": [-36, -300, 50], "unit": "mm"}
                feature["parameters"]["axis"] = [0, -1, 0]
                feature["parameters"]["through"] = "first_wall"
        with self.assertRaises(CompileError) as raised:
            _part(self._built(document))
        self.assertIn("meets no material", str(raised.exception))

    def test_patches_written_as_text_are_a_retry_not_a_crash(self) -> None:
        from forge_roles import FailureAnalyst
        from forge_roles.base import RoleOutputError, answer_in_shape

        schema = FailureAnalyst().output_schema()
        with self.assertRaises(RoleOutputError) as raised:
            answer_in_shape({"diagnosis": "d", "strategy": "s",
                             "patches": ["replace /a with 3"]}, schema)
        self.assertIn("`patches[0]` must be an object",
                      raised.exception.problems[0])
        fixed = answer_in_shape(
            {"diagnosis": "d", "strategy": "s",
             "patches": '[{"op": "remove", "pointer": "/a"}]'}, schema)
        self.assertEqual(fixed["patches"], [{"op": "remove", "pointer": "/a"}])

    def test_a_list_where_named_groups_go_is_still_the_role_s(self) -> None:
        """Only what no `parse` can read is refused: the requirements engineer
        takes a flat list where it asks for named groups."""
        from forge_roles import RequirementsEngineer
        from forge_roles.base import answer_in_shape

        schema = RequirementsEngineer().output_schema()
        answer = {"requirements": [{"id": "R"}], "unknowns": [],
                  "assumptions": [], "risk_class": "low"}
        self.assertEqual(answer_in_shape(answer, schema)["requirements"],
                         [{"id": "R"}])

    def test_a_leaked_list_of_objects_is_never_split_into_lines(self) -> None:
        from forge_models.leaks import recover_leaked_fields
        from forge_roles import FailureAnalyst

        schema = FailureAnalyst().output_schema()
        out = recover_leaked_fields({"diagnosis": "d", "strategy": "s",
                                     "patches": "replace /a\nremove /b"},
                                    schema)
        self.assertEqual(out["patches"], "replace /a\nremove /b")

    def test_a_parameter_named_by_its_id_is_found(self) -> None:
        from forge_roles.library import _pointers_the_document_does_not_have

        component = {"parameters": [{"id": "lever_arm", "value": {}}]}
        self.assertEqual(_pointers_the_document_does_not_have(
            [{"op": "replace",
              "pointer": "/components/0/parameters/lever_arm/value"}],
            {"/components/0": component}), [])

    def test_a_derived_length_is_a_length(self) -> None:
        from forge_roles.library import _a_length_of

        component = {"parameters": [
            {"id": "a", "value": {"magnitude": 50, "unit": "mm"}},
            {"id": "b", "value": {"magnitude": 25, "unit": "mm"}},
            {"id": "total", "expression": "a + b", "unit": "mm"}]}
        self.assertEqual(_a_length_of(component, "total"), 75.0)


class AHoleSkippedWhereItCannotReach(unittest.TestCase):
    """A difference's tool is not evaluated where it cannot change the field,
    and the field is the same to the last bit."""

    def test_the_same_field_sharp_and_blended(self) -> None:
        import numpy as np

        from forge_geom.sdf import BoxSDF, CylinderSDF, Difference, _smooth_max

        base = BoxSDF((0, 0, 0), (60, 40, 4))
        tools = tuple(CylinderSDF((x, y, -10), (0, 0, 1), 2.5, 20)
                      for x in range(-50, 51, 10) for y in (-30, 0, 30))
        points = np.random.default_rng(3).uniform(
            [-70, -50, -10], [70, 50, 10], (50_000, 3))
        for blend in (0.0, 1.0):
            expected = base(points)
            for tool in tools:
                expected = (_smooth_max(expected, -tool(points), blend)
                            if blend else np.maximum(expected, -tool(points)))
            got = Difference(base, tools, blend_radius=blend)(points)
            self.assertLess(float(np.abs(got - expected).max()), 1e-9)
