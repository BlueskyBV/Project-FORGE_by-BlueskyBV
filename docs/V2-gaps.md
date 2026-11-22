# Forge V2: the open gaps, and where each is closed

Forge never builds what it can't make or check: where a brief asks for
something it can't do yet, it says so (an **UNABLE**, a part **VERIFIED
EXCEPT** a named field, a count **not counted**). Each such place is an
open gap. This page lists every one, and the stage of the plan that closes
it, so that none is forgotten. **Forge V2 is released (stage 9) with no
open gap here**: each closed by its stage, or, where a limit is a design
bound rather than a gap (section 9), stated, its reason given, and
confirmed by the owner.

**How it is kept true.** `tests/test_v2_gaps.py` reads V2's code (the
packages `forge_spec`, `forge_checks`, `forge_plan`, `forge_occ` and
`forge_cli`) and finds every place that says Forge can't do something yet:

- an issue, a problem or a closed face of kind `"unable"`;
- a plan's gap (`Gap`, `GapError`, `HollowGapError`);
- a cut the preview can't find how deep goes (`_UnresolvedError`);
- a field the check compiler gives no check of its own and nothing else
  holds (`skip` with no `held_by`, and not `Buried`: the part is then
  VERIFIED EXCEPT that field);
- a count the oracle doesn't make ("not counted yet").

Each is listed below by its module and function, with how many such places
the function holds. A function not listed, a count that differs, a listed
function with none left, or a row naming no stage of the plan, fails the
test: a new gap can't be written without being scheduled, and a closed one
can't stay listed. Gaps found by the live runs that no code says (section
10) are listed too.

Stages are as the plan names them: 4b.0c's and 4b.0d's items and 4b.1 to
4b.18 ([V2-stage4b.md](V2-stage4b.md)), stages 5 to 9
([V2-plan.md](V2-plan.md), 8).

## 1. Shapes no kind makes yet

| Where | What Forge can't do yet | Closed in |
|---|---|---|
| `forge_spec/checks.py:check_draft` (1) | A shape the brief asks for that no kind makes, listed by the writer in `unable` (blind set 1's spur gear, the corpus's X02: involute teeth; a spring's coils; knurling) | 4b.1 (gears, splines, sprockets, coils and springs, knurling, wrap and emboss); 4b.2 to 4b.9 for every other family; what stays outside V2 is V2-stage4b.md, 4, by decision |
| `forge_plan/planner.py:_constructions` (1) | A kind the compiler writes no construction for yet ("a ... isn't compiled yet") | the kind's own sub-stage, 4b.1 to 4b.18 (each kind lands with its compiler module: V2-stage4b.md, 3) |
| `forge_plan/planner.py:plan` (1) | A region: designed later, by the construction agent | stage 5 |

## 2. Placing on faces

| Where | What Forge can't do yet | Closed in |
|---|---|---|
| `forge_spec/items/solve/_common.py:profiled` (1) | Placing on an extrusion's or a revolution's side (its outline swept): only its flat ends take items | 4b.0d3 (item 3: swept and freeform hosts) |
| `forge_spec/items/solve/pocket.py:floor` (1) | Placing on a pocket's floor that a bore runs through | 4b.0d2 (item 12: a face's loops) |
| `forge_spec/items/solve/sphere.py:hollow` (1) | Placing on a hollowed ball's surface | 4b.0c item 3b (its later step), with 4b.3's shell of any body |
| `forge_spec/placement.py:_ball_instances` (3) | On a ball's surface: kinds other than round holes, bosses and posts; placing by anything but latitude and angle; a hole right through a ball that stands on something | 4b.0c item 3b (its later step); 4b.1 (depth modes) |
| `forge_spec/placement.py:_cone_instances` (3) | On a cone's side: kinds other than round holes, bosses and posts; placing by anything but position and angle; a blind cut, or through the next face or everything, from it | 4b.0c item 3b (its later step); 4b.1 (depth modes) |
| `forge_spec/placement.py:_side_instances` (5) | On a round side: kinds other than round holes, keyways, bosses, posts, tabs and ribs; placing by anything but position and angle and their patterns; a hole into a tab's round end but blind or through the next face; an item standing at an angle there | 4b.0c item 3b (its later step); 4b.1 |
| `forge_spec/placement.py:_curved_footed` (1) | The faces of what stands on a curved face (a ball, a cone): they take nothing yet | 4b.0c item 3b (its later step) |
| `forge_spec/placement.py:_round_footed` (1) | The faces of what stands round a side, but its far face and flat sides | 4b.0c item 3b (its later step) |
| `forge_spec/placement.py:_standing` (2) | The faces of a turned or leaning item that is round; hollowing a turned or leaning round item | 4b.0c item 1b step 5 (what waits for 2b and 4b.0d1) |
| `forge_spec/placement.py:_standing_turned` (4) | A leaning item's side wholly inside its foot; a leaning round item's other faces; hollowing a leaning item that is round or turned in its face | 4b.0c item 1b step 5; 4b.0d1 (a leaning item's joint) |
| `forge_spec/placement.py:_turned_floor` (1) | A turned item's faces other than those placed so far | 4b.0c item 1b step 5 |
| `forge_spec/placement.py:_flat_instances` (1) | An item on a face that is turned with its host, of a kind Forge doesn't turn yet | 4b.0c item 1b step 5 |
| `forge_spec/placement.py:_far_material` (2) | The far face of a turned item, or of one on a turned or leaning item's face, without the same material under all of it | 4b.0c item 2b (the material along a direction) |
| `forge_spec/placement.py:_place_on_hosts` (7) | On a turned host: an item concentric with another, a hollow of what stands on it; on a leaning host: standing or leaning round its round side, leaning on its side, a cut right through its far face; an item standing at an angle; more copies on every copy of a host than a bound (section 9) | 4b.0c items 1b step 5 and 3b; 4b.0d1; the bound: section 9 |
| `forge_spec/placement.py:_leaning_faults` (3) | Leaning past the most degrees Forge leans an item; a countersunk hole leaning; leaning on a face without the same material under all of it | 4b.0c item 1b step 5; 4b.2 (a leaning countersink); 4b.0c item 2b (the material along a direction) |
| `forge_spec/placement.py:_check_turned_edges` (1) | Rounding or chamfering a leaning item's edges where it meets its face | 4b.0d1 (a leaning item's joint), then 4b.3 |

## 3. How deep a cut goes

| Where | What Forge can't do yet | Closed in |
|---|---|---|
| `forge_spec/placement.py:_end_depth` (4) | A leaning item cut through everything, through the next face or up to a face; up to a face of an item with several copies, of a face that isn't flat, or of a face not parallel to the one it is cut into | 4b.1 (every depth mode of item 2, as V2-stage4b.md 2.2 defines them); 4b.0c item 2b's fourth step |
| `forge_spec/placement.py:_curved_end` (1) | Up to a face from a curved face | 4b.0c item 2b (its fourth step) |
| `forge_spec/placement.py:_flat_end_only` (1) | Through everything, through the next face or up to a face from a face of kinds that take them only from a flat face | 4b.0c item 2b (its fourth step) |
| `forge_occ/resolve.py:_comes_out` (3) | The preview finding how deep a cut goes when it isn't square to its face; how deep a cut other than a hole goes round a side, on a ball or a cone; a boolean of its mouth OpenCascade refuses | 4b.1 (depth by geometry for every cut and every host); the refused boolean: V2-stage4b.md 3.1 (Forge's own geometry where OpenCascade is weak) |
| `forge_occ/resolve.py:_first_out` (3) | Through the next face where no material is under its mouth, where it doesn't come out, or where less air is past where it comes out than its tool is carried into | the first two are the brief's, said now as UNABLE: said as a question or CAN'T in 4b.0c item 2b's fourth step; the third, 4b.1 (up to next, exactly as the definitions say) |
| `forge_occ/resolve.py:_made_before` (3) | Finding how deep where nothing is made before the cut, or what is made before it doesn't place or build | 4b.0c item 2b's fourth step: said as the earlier item's own ending, not this one's |
| `forge_occ/resolve.py:_mouth` (1) | The preview for a cut that isn't a hole, a pocket or a slot | 4b.1 (each cut kind's depth modes) |
| `forge_occ/resolve.py:reaches` (1) | Copies of one cut through the next face coming out at different depths | 4b.4 (each copy evaluated where it lands, its own depth) |
| `forge_cli/spec.py:with_unresolved` (1) | A cut through the next face the preview couldn't find how deep goes (any of the above, at `forge spec`) | as each cause above is closed |

## 4. Hollows

| Where | What Forge can't do yet | Closed in |
|---|---|---|
| `forge_spec/items/solve/_common.py:uneven_roundings` (1) | Rounding or bevelling an edge of a hollowed body where walls of different thickness meet (blind set 1's B1-24: a soap dish, its 3 mm floor and 2.5 mm walls, every edge rounded 5 mm) | 4b.3 (shell: several thicknesses, by Forge's own offset of the spec's faces, exact by construction: item 5) |
| `forge_plan/items/plan/_shells.py:_check_walls` (1) | The same, at the planner: no construction for it | 4b.3, with the row above |
| `forge_spec/placement.py:_hollow` (2) | Hollowing a kind other than blocks, cylinders, cones and balls; placing on the rim of an open hollow | 4b.3 (shell: any body); 4b.0d2 (item 12: a hollow's rim as a face) |
| `forge_spec/items/solve/cone.py:hollow` (3) | Hollowing a cone that comes to a point; placing on a hollow cone's side; rounding a hollow cone's edges | 4b.3 (shell: any body, reflex edges rounded by its thickness) |

## 5. Roundings, chamfers, holes, threads and letters

| Where | What Forge can't do yet | Closed in |
|---|---|---|
| `forge_spec/items/checks/pocket.py:edges_missing` (1) | Rounding or bevelling the edges of a pocket of its own outline | 4b.3 (rounding and chamfer on any selection: item 12) |
| `forge_plan/items/plan/tab.py:_round_tab_edges` (1) | Rounding a round-ended tab's vertical edges, which run on smoothly into its rounding | 4b.3 (rounding along tangent chains, item 12) |
| `forge_spec/items/solve/hole.py:check_shape` (1) | A hole with both a counterbore and a countersink | 4b.2 (the hole wizard) |
| `forge_spec/items/checks/thread.py:physical` (2) | A thread that isn't metric (UN, BSP, trapezoidal, ACME); a metric size whose coarse pitch Forge doesn't know, unless its pitch is named | 4b.2 (threads and their tables) |
| `forge_spec/placement.py:_leaning_thread` (1) | A thread on a leaning item running into its foot | 4b.2 (threads with run-out), with 4b.0d1's joint |
| `forge_spec/items/checks/text.py:physical` (1) | A letter Forge's font has no glyph for | 4b.1 (wrap, emboss, deboss), with item 8's text in profile v2 |

## 6. Patterns

| Where | What Forge can't do yet | Closed in |
|---|---|---|
| `forge_spec/placement.py:_pattern_offsets` (2) | More than one copy at each position of a pattern; more copies of one item than a bound (section 9) | 4b.4 (patterns as items); the bound: section 9 |

## 7. Building

| Where | What Forge can't do yet | Closed in |
|---|---|---|
| `forge_occ/planned.py:run` (1) | A part where OpenCascade refuses every construction of an item (one that comes apart is a CAN'T, `forge_occ.apart`) | V2-stage4b.md 3.1 (Forge's own geometry where OpenCascade is weak), each case kept as a regression as found |
| `forge_occ/planned.py:out_of_builds` (1) | A part not built within the builds a plan is given | the bound: section 9 |
| `forge_occ/planned.py:build_plan` (1) | A spec that makes nothing (every item a region) | stage 5 (regions made by the construction agent) |
| `forge_plan/planner.py:_plan` (1) | An item the planner meets a gap in (any of sections 1 to 6) | as each cause is closed |
| `forge_plan/planner.py:preview_plan` (1) | The same, in the preview's plan | as each cause is closed |

## 8. What the judge leaves unchecked or uncounted

A part whose field no check holds is VERIFIED EXCEPT that field, named in
its verdict; never VERIFIED.

| Where | What Forge can't check yet | Closed in |
|---|---|---|
| `forge_checks/compiler.py:_axis_position` (5) | A position along a face's axis where the face's edges or the item can't be fitted on the part's surface | 4b.0d1 (fields measured on the oracle's own shape, held by face accounting where no check of their own can see them, as buried faces are) |
| `forge_checks/compiler.py:_along_side` (2) | A position along a round side where its ends or the item's edge can't be fitted | 4b.0d1 |
| `forge_checks/compiler.py:_row_along_side` (3) | A row's position along a round side where the side's ends or the item can't be fitted | 4b.0d1 |
| `forge_checks/compiler.py:_concentric` (1) | Two items concentric where their centres can't both be fitted | 4b.0d1 |
| `forge_checks/compiler.py:_circle` (2) | A circle of copies whose centre or diameter can't be found | 4b.0d1 |
| `forge_checks/compiler.py:_pitches` (2) | A pattern's pitch where its copies' centres can't be fitted, or it makes one copy along an axis | 4b.0d1; 4b.4 |
| `forge_checks/compiler.py:_insets` (1) | A corner pattern's insets where the copy or the face's edge can't be fitted | 4b.0d1 |
| `forge_checks/compiler.py:_count_of` (1) | A count where the copies' own surfaces can't be found | 4b.0d2 (item 12: copy identity by pattern coordinates) |
| `forge_checks/compiler.py:_place` (1) | An angle round a round side, checked by no placement check of its own | 4b.0d1 |
| `forge_checks/compiler.py:_height` (2) | A height where the item stands on no flat face, or its foot's face isn't seen | 4b.0d1 |
| `forge_checks/compiler.py:_round_end` (1) | A round-ended item's length where the face round its foot isn't seen | 4b.0d1 |
| `forge_checks/compiler.py:_floor` (3) | A cut's depth where its floor, or the face round its mouth, isn't on the part's surface | 4b.0d1 |
| `forge_checks/compiler.py:_rounding` (1) | A rounding none of whose stretches is along a straight edge between flat faces or round a rim | 4b.3 (rounding's checks on any edge, exact by construction) |
| `forge_checks/compiler.py:_not_placed` (1) | An item's fields where the judge's placement couldn't place it | 4b.0d1 (placement and the oracle on the compiled core) |
| `forge_checks/items/compile/extrusion.py:checks` (1) | An extrusion's length where it has no flat ends | 4b.0d1 |
| `forge_checks/items/compile/shell.py:checks` (1) | A hollow's wall thickness where none of its walls is on the part's surface both sides | 4b.0d1 (a wall measured on the oracle's own shell) |
| `forge_checks/items/compile/text.py:checks` (1) | Letters' depth where their tops, or the face round them, aren't on the part's surface | 4b.0d1 |
| `forge_checks/oracle.py:_topology` (2) | Through-holes: not counted by the oracle (listed as not cross-checked; no ending changes) | 4b.0d2 (item 7: each body's through-holes counted by the oracle from its own shape, certified) |

## 9. Design bounds

Not gaps: limits Forge keeps on purpose, each with its reason. At release
the owner confirms each, or it is raised.

- **Copies of one item** (`placement.MAX_COPIES`, in `_pattern_offsets` and
  `_place_on_hosts`): a pattern of more copies than this is refused, so
  that every program can place, build and judge each copy within its time
  budget. Raised with 4b.4's patterns and the compiled core (4b.0d1) as
  their measured speed allows; confirmed at stage 9.
- **Builds a plan is given** (`planned.MOST`, `out_of_builds`): the build
  loop's search for constructions OpenCascade accepts is bounded so a run
  ends. Confirmed at stage 9, with each refusal behind it a kept
  regression.

## 10. Gaps the live runs found that no code site says

| Gap | Found by | Closed in |
|---|---|---|
| A load, a stress or a safety factor ("a load of 150 N ... a safety factor of at least 2"): asked about, as Forge can't check strength | the corpus's R10 | the schema: V2-stage4b.md 2.2 item 25 (loads, supports and requirements); 4b.14 (engineering calculation); 4b.15 (analysis); stage 6 (strength, by 4b.15's core) |
| Mass properties beyond a limit (centre of mass, inertia), and a material per body | the corpus's R01, R11 and R13 (their mass limits, checked since schema 1.11) | 4b.10 (a material per body, mass, centre of mass and inertia from the B-rep) |
| A part to fit within a box in any orientation, or a limit on a size not along the part's own axes | the corpus's R13 (its height limit, checked along z since schema 1.11) | 4b.10 (requirements), with item 15's views of them |
