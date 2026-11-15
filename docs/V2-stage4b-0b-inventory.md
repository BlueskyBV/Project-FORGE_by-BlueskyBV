# Forge V2, stage 4b.0b: the inventory (step 0)

Status: mapped, 14 November 2026 (every file's sites assigned to a role's
protocol method, section 2). Step 0 of
[V2-stage4b-0b.md](V2-stage4b-0b.md): every site that dispatches on an
item's kind, a pattern's mode or an item's category, by file and function,
and the protocol method of section 3 that will hold it. The first
inventory (10 November, 600 sites in 182 functions) was kept outside the
project and lost with the cloud workspace on 11 November; this one is kept
here, and its table is made by `python tests/v2_kind_sites.py --inventory`,
so it can always be made again.

## 1. What a site is

The scanner `tests/v2_kind_sites.py` defines it, as section 5's rule does:
a comparison with a kind or mode literal, with a collection holding one or
a name bound to one, or with a `Category` member; a lookup keyed by a kind
in a table keyed by kind or mode literals; a `match` on them; a display
holding two or more of them (a family tuple or a dispatch table); a
`startswith` or `endswith` with one; a `getattr` built from a kind; a
module constant bound to one. A non-item kind that shares a kind's name
(the edit kind "text", the check kind "thread") counts until it is
compared through its own enum. The draft and wire layer (`schema.py`,
`draft.py`, `wire.py`) and the packages that can't see items
(`forge_occ`, `forge_kernel`, `forge_geom`) are outside.

On 14 November, after the kernel switch: **734 sites in 21 files, 218
functions** (689 comparisons, 27 families and tables, 11 category reads, 6
lookups, 1 prefix). The scanner counts each comparison and each display
on its own, which the first inventory didn't, and takes in the pattern
modes and the non-item kinds sharing a name; so its count is higher. The
per-file counts are the ratchet (`tests/v2_kind_sites.json`).

## 2. The protocol methods

Role by role (section 3 of the design): for each function, the protocol
method that will hold its per-kind branches, and whether it dispatches on
its own item's kind or on another's (a modifier's target, a standing
item's host: a method the target publishes). Roles not yet mapped are
marked so.

### 2.1 `forge_plan`: the `plan` role (74 sites, 34 functions)

`forge_plan/items/plan/<kind>.py`, one module per kind, its protocol
`PlanKind`:

| Method | Holds (function: what its branches choose) | Own or published |
|---|---|---|
| `constructions(ctx, item, part)` | `planner._constructions` (a rounding's, a shell's, letters', a thread's), `planner._item_constructions` (a cut's carried, a standing item's sunk, a dome's cut), `planner._into_a_round_side` (a hole only), `planner._rounding`, `_early`, `_regions` (the bevel: fillet or chamfer) | own |
| `tool(chain, ctx, item, copy, how)` | `planner._tools.made` (body, cut or standing), `tools.body_tool` (seven bodies), `tools.cut_tool` (hole, slot, pocket), `tools.standing_tool` (a boss's, a round tab's) | own |
| `taken` | `planner._made` (a cut is taken, others joined) | own |
| `air_boxes(ctx, item, copy)`, `side_air_boxes(ctx, item, copy)` | `tools.air_boxes`, `tools.side_air_boxes` (a hole's into a round side), `tools._outline_of`, `tools._pocket` (a slot's or a pocket's outline; a pocket's circle) | own |
| `sink(chain, ctx, item, copy)` | `tools.sink_box`, `tools._section`, `tools._round_side` (post and block, rib, tab, boss) | own |
| `edges(chain, queries, copy, which, shell, part)` | `edges._own` (box-like, round tab, rims, dome, extrusion, revolution), `edges.box_pairs` (a block's bottom and all), `edges._rims`, `edges._rim_radius` (cone, tube), `edges._cut_rims`, `edges._pieces`, `edges.edge_reference` (a cut's rims) | published by the rounded item |
| `box_like` | `regions.box_like`, `planner._early` (the target's test), `edges._own`'s first branch | published |
| `hollow(chain, body, shell)` | `shells.hollow_tool` (block, cylinder, sphere) | published by the hollowed body |
| `threadable` | `threads.thread_step` (a cylinder's length, a boss's height) | published by the threaded item |
| `bore_holds` | `tools._inside_holds` (a tube's bore runs its length) | published by the host |
| `round_host` | `edges._flat_at` (a host in `_ROUND`) | published by the host |
| order: `split_at_shell` | `planner._parts` (a rounding split before and after a shell) | own (the rounding kinds) |
| registry: `planned` | `planner.plan`, `preview_plan` (a region is left to stage 5) | the registry's entry |

The family tuples `_BODIES`, `_CUTS`, `_STANDING` (planner) and `_ROUND`
(edges) become the plan role's own (section 8 of the design). The shape
choice `"circle"` of a pocket (`tools._outline_of`, `_pocket`;
`edges._pieces`) names a pattern mode's word only by sharing it: it is
compared through the pocket's own choice constant.

### 2.2 `forge_checks`: the `oracle`, `place` and `compile` roles (195 sites, 64 functions)

**`oracle`** (`oracle.py`, 48 sites in 16 functions),
`forge_checks/items/oracle/<kind>.py`, protocol `OracleKind`:

| Method | Holds | Own or published |
|---|---|---|
| `node(item, copy)` | `oracle.oracle` (shell, rounding, thread, text, region; a cut's category subtracts), `_body_node` (box-like and region, rib, tab, extrusion, revolution, cylinder and boss, tube, cone, sphere), `_cut_node` (a hole), `_outline` (a slot's, a pocket's circle) | own |
| `hollow(body)` | `_hollow_node`, `_wall_bands` (block, cylinder), `_wall` (the shell of a target) | published by the hollowed body |
| `edge_chains(target, which)` | `_edge_chains` (box-like, tab, rims, sphere, revolution; a cut's category), `_rim_chains` (cone, tube, a boss's height), `_cut_chains` (a hole), `_footprint_chain` (cylinder, boss, cone, sphere), `_rounding` (an extrusion's) | published by the rounded item |
| `rounding` | `_rounding`, `_hollow_loop` (fillet or chamfer) | own (the rounding kinds) |
| `threadable` | `_thread` (a cylinder's length, a boss's height) | published |

Not kinds, sharing a name: an outline segment's kind `"arc"`
(`_outline_chain`) and a corner's kind `"fillet"` (`_corner_pieces`),
compared through their own enums.

**`place`** (`place.py`, 88 sites in 21 functions), the judge's own
placement, `forge_checks/items/place/<kind>.py`, protocol `PlaceKind`:

| Method | Holds | Own or published |
|---|---|---|
| order: `rank`, `made_last` | `_sequence` (a region isn't made), `_order` (roundings and threads after what they act on) | own |
| `place(item, ...)` | `place` (a shell read, a hole, the first body) | own |
| `first_frame` | `_first_body` (round first bodies) | own |
| `footprint(item, copy)` | `_footprint` (16: hole, boss, pocket's circle, and the rest) | own |
| `extent`, `outline` | `_extent`, `_outlined` (revolution, extrusion) | own |
| `covers` | `_covering` (text) | own |
| `lies_on`, `flat_copies`, `flat_cut`, `mouth` | `_lies_on` (body, cut categories), `_flat_copies` (cut), `_flat_cut` (embossed text, pocket), `_mouth` (hole) | own |
| `round_copies`, `standing` | `_round_copies` (hole, the add category), `_standing` (body, standing kinds) | own |
| `body(item, copy)` | `_body` (18: box-like and region, rib, tab, round bodies, sphere, extrusion, revolution) | own |
| `edges`, rims | `body_edges` (box-like, block, round), `_RIMS` | published by the rounded item |
| `hollow` | `_read_shell` (block, cylinder, sphere: `_HOLLOWABLE`), `_hollow` (a dome, the faces each body allows) | published by the hollowed body |
| `same_as` | `compare_layouts` (a sphere's) | own |

**`compile`** (`compiler.py`, 54 sites in 24 functions; `capabilities.py`,
2 in its module), `forge_checks/items/compile/<kind>.py`, protocol
`CompileKind`:

| Method | Holds | Own or published |
|---|---|---|
| `main(item, copy)` | `_Compiler._main` (hole, boss, a pocket's circle, cone, cylinder, sphere, revolution, tube), `_plain`, `_round_body` (boss, cylinder) | own |
| `sides(item, copy)` | `_sides_along` (box-like, pocket and slot), `_box_sides` (a round tab), `_no_centre`, `_round_copy` (box-like) | own |
| `references` | `_centre_ref`, `_shift` (extrusion), `_edge_ref` (a hole's span, extrusion, revolution), `_round_ends` (slot, pocket) | own |
| `face_refs(owner)` | `_face_refs` (round, sphere, a pocket's circle), `_seam` (a tab) | published by the owning item |
| `place` | `_place` (boss, cylinder: the plain length) | own |
| `threadable` | `_thread`, `_plain` (a thread on the item) | published |
| `capability` | `capabilities._IMPLICIT_CANT` (fillet, chamfer, thread, text, region) | own |
| registry: `checked` | `compile_checks` (a region) | the registry's entry |

Pattern modes, as the pattern kind's (`items/<role>/pattern.py`, a
handler per mode): `_Compiler._axis_position`, `_pattern_centre`,
`_round_place`, `_pattern`, `_pitches`, `_circle`; `place._flat_positions`
(15), `place._round_copies`' circle and arc.

The family tuples: `_BOXES` (compiler) the compile role's own, diffed
against the schema-derived fact; `_RIMS` the place role's;
`_IMPLICIT_CANT` each kind's capability entry (design, section 8).

Not kinds, sharing a name: the check kinds of `checks.py` (`MEASURES`,
which holds `"thread"`), compared through a check-kind enum.

### 2.3 `forge_spec`: the `solve`, `views`, `compare`, `checks` and `words` roles (275 sites, 72 functions)

**`solve`** (`placement.py`, 130 sites in 29 functions),
`forge_spec/items/solve/<kind>.py`, protocol `SolveKind`:

| Method | Holds | Own or published |
|---|---|---|
| order: `rank`, `made_last` | `_make_order` (roundings after, the modify category) | own |
| `solve` pre-passes | `solve` (a shell's target, the hole and shell passes) | own |
| `first_frame` | `_first_body` (round first bodies) | own |
| `outline(item)`, `outline_fields` | `_outline`, `_outline_fields` (12 each: hole, boss and round, pocket's circle, ...), `_pocket_bottom` | own |
| `height`, `footing`, `reach`, `profiled` | `height_of`, `_footing`, `_reaches`, `_profiled` (extrusion, revolution, tab, cylinder, sphere) | own |
| `shape_check` | `_check_shape` (revolution, a pocket's rectangle, ...) | own |
| `stand(item, face)` | `_standing` (13: round kinds, box-like and region), `_round_footed` (a boss's far end), `_place_on_hosts` (text, pocket) | own |
| `flat_instances`, `side_instances` | `_flat_instances` (the cut category but text), `_side_instances` (hole, the add category) | own |
| checks of a placed item | `_check_fits`, `_check_severs`, `_check_exits`, `_check_over_openings`, `_check_round_overlaps`, `_check_depth` (by category; embossed text) | own |
| `covers` | `_covered` (text) | own |
| `hollow` | `_hollow` (`_HOLLOWABLE`: block, cylinder, sphere) | published by the hollowed body: the schema fact of section 8 |
| `edges` | `edges_of` (block, cylinder and cone, ...) | published by the rounded item |
| pattern modes | `_place_values`, `_face_position` (`_AXIS_NAMES`), `_pattern_offsets` | the pattern kind's modes |

**`views`** (`render_views.py`, 76 sites in 19 functions),
`forge_spec/items/views/<kind>.py`, protocol `ViewKind`: `solid` (the
drawing's body: `_Drawing._solid`, `_box_fields`, `_outline`, `_outlined`,
`_cavity`), `cut` (`_Drawing._cut`, `_cut_words`, `_corner_radius`,
`_cut_span`, `_windows`, `_Drawing.draw`'s cut category), `inside`
(`_inside`: box-like and the rest), `outline` (`_outlined`, extrusion),
`drawable` (`render_views`: the modify category isn't drawn); pattern
modes in `_Drawing._on_flat`, `_on_side`, `_pattern_words`. The family
tuples `_ROUND_KINDS`, `_BOX_KINDS`, `_OUTLINED` are the views role's own.

**`compare`** (`compare.py`, 33 sites in 10 functions), protocol
`CompareKind`: `solid` (`_solid`), `cut` (`_cut`, `_corner`,
`_cut_edges`), `modifier` (`_modifier`: fillet, chamfer), `edges`
(`_edges`, `_rims`: round kinds, cone, tube: published by the rounded
item), `contrast` (`_contrast`: pocket, tab), `features`' category. The
tuples `_BOXES`, `_RODS`, `_ROUND` are its own.

**`checks`** (`checks.py`, 24 sites in 8 functions), protocol
`SpecCheckKind`: `physical` (`_physical`: tube, hole, ...),
`check_values` (`_check_values`: revolution), `rounding_limit` (`_rounding_limit`, 9:
published by the rounded item), `edges_missing` (`_edges_missing`:
sphere's bottom, extrusion: published), `threadable` (`_check_thread`:
published), `rounding` (`_check_rounding`: fillet's radius, chamfer's
size), `part_named` (`_part_named`: the body category); `_provenances`'
ends mode is the pattern kind's.

**`words`** (`render.py`, 11 sites in 5 functions): the sentence
templates `_TEMPLATES` (a table by kind) and `_line`'s lookup become each
kind's `words` entry; `_pocket`'s shape word is the pocket's own; `_axis`,
`_place` are the pattern kind's modes.

The guide's `_PATTERN_MEANINGS` (`guide.py`) becomes each mode's guide
entry (item 23's reserved method).

### 2.4 `forge_eval`: the `draw`, `brief`, `truth` and `grade` roles (185 sites, 44 functions)

**`draw`** (`generator.py`, most of its 168 sites), protocol `DrawKind`,
with the per-kind draw weight and host predicate of section 3:
`footprint` (`_footprint`, 14; `_extent`, `_foot_of`), `first` (`_first`),
`on_flat` (`_on_flat`, 17; `_overhang`, `_flush`), `rise` (`_rise`),
`on_round` (`_on_round`, `_standing_round`, `_standing_profile`),
`feature` and `standing_new` (`_feature`, `_standing_new`: the weighted
lists, rebuilt in today's order), `build` (`_build`, `_build_one`: thread,
shell), `shell` (`_shell`, `_choose_shell`: `OPENABLE`), `rounding`
(`_rounding`, `_earlier_vertical`, `_round_box`, `_round_rod`,
`_round_cut`, `_choose_rounding`, `_round_now_and_then`: published by the
rounded item), `thread_on` (`_thread_on`: published), `sizes_hold`
(`_sizes_hold`: cone), `mutants` (`_changes`, 9; `_faces_of`),
`generate`'s and `impossible`'s family tests; pattern modes in `_offsets`,
`_names_the_axes`, `_flat_spots`, `_pattern_changes`.

**`brief`** (`generator.py`): `_draft`, `_rounding_said`, `_item_said`,
`_place_said` (modes), `_OPTION_WORDS`.

**`truth`** (`generator.py`'s `_cuts_sided`, `_SIDED`; `truth.py` has
none).

**`grade`** (`spec_grade.py`, 17 sites in 4 functions):
`envelope_unsettled` (`_envelope_unsettled`: region, embossed text),
`reach` (`_reach`: hole, a pocket's circle), `through_holes`
(`_through_holes`, 9: the kinds present), `voids` (`_voids`: shell, by
category).

The generator keeps its own copies of schema facts, diffed against the
schema by a test (design, section 8): `OPENABLE`, `ROUNDABLE` in
`items/_common.py`.

### 2.5 Not item kinds: names shared with a kind or mode

Compared through their own enums, which the fingerprint proves an
equivalent change: an edit's option kind `"text"` (`questions.py`, 4
sites in `_refuse_two_edits_of_one_field`, `_sentence` and `_apply`;
`forge_cli/spec.py`, 1 in `_detail`), a check kind holding `"thread"`
(`forge_checks/checks.py`, 3 in `Check.__post_init__` and `Check.run`), an outline segment's `"arc"` and a
corner's `"fillet"` (`oracle.py`), and a pocket's shape choice
`"circle"` (planner, compiler, spec, render).

### 2.6 What the inventory leaves to decide at the moves

Step 0's design asks for the protocols derived and checked complete: the
methods above are that derivation, one role at a time, each method
holding named functions. Two things are settled as each role moves, not
here: each chain whose branches overlap (an item matching two branches,
whose order then decides) is listed in the move's change set with its
order kept; and each method's signature, which stays provisional until
4b.0d (design, section 4).

## 3. The sites, by file and function

### `forge_checks/capabilities.py`: 2 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `<module>` | 2 | 79, 87 | chamfer, fillet, region, text, thread |

### `forge_checks/checks.py`: 3 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `Check.__post_init__` | 1 | 71 |  |
| `Check.run` | 2 | 79, 89 |  |

### `forge_checks/compiler.py`: 54 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `<module>` | 1 | 145 | block, post, rib, tab |
| `_Compiler._plain` | 2 | 913, 915 | boss, thread |
| `_Compiler._round_body` | 1 | 933 | boss, cylinder |
| `_Compiler._pocket` | 1 | 1265 | circle |
| `_Compiler._main` | 10 | 1324, 1329, 1334, 1334, 1340, 1349, ... | boss, circle, cone, cylinder, hole, pocket, revolution, sphere, tube |
| `_Compiler._shift` | 1 | 1382 | extrusion |
| `_Compiler._sides_along` | 5 | 1482, 1501, 1505, 1505, 1512 | circle, pocket, slot |
| `_Compiler._box_sides` | 1 | 1544 | tab |
| `_Compiler._centre_ref` | 1 | 1563 | extrusion |
| `_Compiler._no_centre` | 1 | 1577 |  |
| `_Compiler._edge_ref` | 3 | 1600, 1624, 1627 | extrusion, hole, revolution |
| `_Compiler._round_ends` | 4 | 1662, 1673, 1675, 1688 | circle, pocket, slot, tab |
| `_Compiler._seam` | 1 | 1776 | tab |
| `_Compiler._face_refs` | 6 | 1841, 1845, 1849, 1849, 1853, 1855 | boss, circle, cone, cylinder, pocket, revolution, sphere, tube |
| `_Compiler._place` | 2 | 1874, 1890 | boss, cylinder |
| `_Compiler._axis_position` | 1 | 1934 | arc, circle |
| `_Compiler._pattern_centre` | 1 | 2011 | arc |
| `_Compiler._round_copy` | 1 | 2063 |  |
| `_Compiler._round_place` | 1 | 2112 | circle |
| `_Compiler._pattern` | 3 | 2231, 2233, 2237 | arc, circle, corners, ends, grid, rectangle, row |
| `_Compiler._pitches` | 3 | 2250, 2252, 2258 | grid, row |
| `_Compiler._circle` | 2 | 2313, 2320 | circle |
| `_Compiler._thread` | 1 | 2665 | boss |
| `compile_checks` | 1 | 2742 | Category.REGION |

### `forge_checks/oracle.py`: 48 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_body_node` | 12 | 927, 928, 932, 939, 952, 954, ... | block, boss, cone, cylinder, extrusion, post, region, revolution, rib, sphere, tab, tube |
| `_hollow_node` | 2 | 1124, 1127 | block, cylinder |
| `_cut_node` | 1 | 1158 | hole |
| `_outline` | 2 | 1186, 1192 | circle, slot |
| `oracle` | 6 | 1230, 1233, 1236, 1241, 1247, 1264 | Category.CUT, chamfer, fillet, region, shell, text, thread |
| `_rounding` | 2 | 1325, 1357 | extrusion, fillet |
| `_wall_bands` | 2 | 1531, 1543 | block, cylinder |
| `_edge_chains` | 7 | 1642, 1653, 1654, 1687, 1689, 1691, ... | Category.CUT, block, boss, cone, cylinder, post, revolution, rib, sphere, tab, tube |
| `_wall` | 1 | 1718 | shell |
| `_hollow_loop` | 1 | 1733 | fillet |
| `_rim_chains` | 3 | 1787, 1788, 1793 | boss, cone, tube |
| `_cut_chains` | 1 | 2086 | hole |
| `_outline_chain` | 2 | 2166, 2166 | arc |
| `_corner_pieces` | 1 | 2185 | fillet |
| `_footprint_chain` | 3 | 2323, 2325, 2334 | boss, cone, cylinder, sphere |
| `_thread` | 2 | 2431, 2440 | boss, cylinder |

### `forge_checks/place.py`: 88 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_sequence` | 1 | 550 | Category.MODIFY |
| `<module>` | 1 | 583 |  |
| `body_edges` | 3 | 619, 629, 634 | block, cone, cylinder, post, rib, tab, tube |
| `place` | 3 | 664, 666, 673 | Category.BODY, hole, shell |
| `_read_shell` | 1 | 705 | block, cylinder, sphere |
| `_first_body` | 1 | 734 | cone, cylinder, extrusion, revolution, tube |
| `_footprint` | 16 | 765, 771, 771, 771, 773, 782, ... | block, boss, circle, cone, cylinder, extrusion, hole, pocket, post, region, revolution, rib, slot, sphere, tab, text, tube |
| `_extent` | 1 | 888 | revolution |
| `_covering` | 1 | 906 | text |
| `_flat_positions` | 15 | 1025, 1027, 1036, 1040, 1048, 1053, ... | arc, circle, corners, ends, grid, rectangle, row |
| `_lies_on` | 2 | 1230, 1236 | Category.BODY, Category.CUT |
| `_flat_copies` | 1 | 1262 | Category.CUT |
| `_mouth` | 1 | 1278 | hole |
| `_flat_cut` | 3 | 1292, 1294, 1305 | pocket, text |
| `_round_copies` | 9 | 1356, 1356, 1366, 1382, 1385, 1391, ... | Category.ADD, arc, circle, hole |
| `_standing` | 2 | 1452, 1456 | Category.BODY |
| `_outlined` | 1 | 1512 | extrusion |
| `_body` | 18 | 1610, 1611, 1623, 1639, 1647, 1649, ... | block, boss, cone, cylinder, extrusion, post, region, revolution, rib, sphere, tab, tube |
| `_hollow` | 5 | 1838, 1839, 1854, 1901, 1916 | block, sphere |
| `_order` | 2 | 2012, 2055 | chamfer, fillet, thread |
| `compare_layouts` | 1 | 2212 | sphere |

### `forge_cli/spec.py`: 1 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_detail` | 1 | 681 | text |

### `forge_eval/generator.py`: 168 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_footprint` | 14 | 418, 423, 424, 424, 428, 430, ... | boss, circle, cone, cylinder, extrusion, hole, pocket, revolution, rib, slot, sphere, tab, text, tube |
| `_extent` | 1 | 480 | extrusion |
| `_foot_of` | 3 | 505, 509, 513 | cone, extrusion, text |
| `_offsets` | 4 | 555, 561, 571, 575 | circle, grid, rectangle, row |
| `_names_the_axes` | 1 | 590 |  |
| `_flat_spots` | 2 | 630, 643 | circle, corners |
| `_first` | 6 | 696, 713, 729, 742, 767, 770 | block, cylinder, extrusion, revolution, sphere, tube |
| `_on_flat` | 17 | 965, 997, 998, 1012, 1082, 1083, ... | block, boss, cone, corners, cylinder, extrusion, hole, pocket, post, revolution, rib, slot, sphere, tab, text, tube |
| `_overhang` | 1 | 1242 | block |
| `_flush` | 2 | 1277, 1281 | block, boss, post |
| `_rise` | 4 | 1365, 1367, 1369, 1371 | cone, cylinder, extrusion, revolution, sphere, tab, text, tube |
| `_on_round` | 3 | 1501, 1503, 1505 | boss, circle, hole, post |
| `_standing_round` | 4 | 1596, 1601, 1651, 1674 | boss, circle |
| `_standing_profile` | 1 | 1810 | extrusion |
| `<module>` | 3 | 1981, 2380, 3323 | circle, hole, pocket, rectangle, slot |
| `_draft` | 3 | 2041, 2043, 2056 | chamfer, fillet, shell, thread |
| `_rounding_said` | 2 | 2077, 2088 | fillet |
| `_item_said` | 9 | 2103, 2105, 2107, 2116, 2118, 2128, ... | cone, cylinder, extrusion, hole, pocket, revolution, slot, sphere, text, tube |
| `_place_said` | 5 | 2205, 2212, 2220, 2232, 2237 | circle, grid, rectangle, row |
| `_sizes_hold` | 7 | 2248, 2254, 2256, 2258, 2261, 2269, ... | cone, pocket, slot, tab, text, tube |
| `_build` | 1 | 2311 | chamfer, fillet, shell |
| `_build_one` | 3 | 2352, 2355, 2358 | chamfer, fillet, shell, thread |
| `_shell` | 9 | 2412, 2413, 2420, 2422, 2426, 2437, ... | chamfer, cylinder, fillet, sphere |
| `_rounding` | 8 | 2626, 2632, 2639, 2647, 2659, 2664, ... | block, boss, chamfer, cylinder, fillet, hole, pocket, post, shell |
| `_earlier_vertical` | 2 | 2766, 2774 | chamfer, fillet |
| `_round_box` | 1 | 2792 | fillet |
| `_round_rod` | 2 | 2931, 2934 | cylinder, fillet |
| `_round_cut` | 3 | 2991, 2997, 2997 | circle, fillet, hole |
| `_thread_on` | 2 | 3087, 3095 | boss, cylinder |
| `_cuts_sided` | 1 | 3340 |  |
| `_choose_shell` | 3 | 3431, 3443, 3454 | block, cylinder, sphere |
| `_choose_rounding` | 3 | 3469, 3473, 3477 | block, boss, cylinder, hole, post |
| `_round_now_and_then` | 2 | 3511, 3525 | fillet |
| `_feature` | 9 | 3683, 3690, 3700, 3723, 3731, 3739, ... | block, boss, circle, corners, hole, pocket, post, slot, tab |
| `_standing_new` | 4 | 3790, 3792, 3795, 3800 | cone, rib, sphere, tube |
| `generate` | 6 | 4100, 4103, 4128, 4139, 4146, 4153 | block, boss, chamfer, fillet, post |
| `impossible` | 1 | 4183 | hole, pocket |
| `_changes` | 9 | 4302, 4324, 4338, 4353, 4363, 4366, ... | boss, chamfer, fillet, hole, pocket, shell, slot, text, thread |
| `_faces_of` | 6 | 4425, 4427, 4429, 4431, 4433, 4435 | block, boss, cone, cylinder, extrusion, post, revolution, rib, sphere, tab, tube |
| `_pattern_changes` | 1 | 4445 | grid |

### `forge_eval/spec_grade.py`: 17 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_envelope_unsettled` | 3 | 406, 408, 410 | hole, pocket, region, slot, text |
| `_reach` | 3 | 427, 439, 439 | circle, hole, pocket |
| `_through_holes` | 9 | 532, 534, 536, 543, 547, 547, ... | Category.ADD, Category.BODY, circle, hole, pocket, region, revolution, shell, tube |
| `_voids` | 2 | 624, 627 | Category.CUT, shell |

### `forge_plan/edges.py`: 19 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `box_pairs` | 1 | 117 | block |
| `edge_reference` | 1 | 211 | hole, pocket, slot |
| `_own` | 7 | 236, 237, 250, 252, 254, 256, ... | block, boss, cone, cylinder, extrusion, post, revolution, rib, sphere, tab, tube |
| `_rims` | 3 | 562, 564, 565 | boss, tube |
| `_rim_radius` | 2 | 605, 607 | cone, tube |
| `_cut_rims` | 1 | 714 | pocket |
| `_pieces` | 3 | 733, 735, 737 | circle, hole, slot |
| `_flat_at` | 1 | 746 |  |

### `forge_plan/planner.py`: 23 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `<module>` | 3 | 212, 213, 214 | block, boss, cone, cylinder, extrusion, hole, pocket, post, revolution, rib, slot, sphere, tab, tube |
| `_tools.made` | 3 | 223, 225, 232 |  |
| `_made` | 1 | 244 |  |
| `_item_constructions` | 3 | 292, 294, 296 | sphere |
| `_into_a_round_side` | 1 | 327 | hole |
| `_rounding` | 1 | 343 | chamfer |
| `_early` | 3 | 379, 380, 389 | block, chamfer, post, rib, tab |
| `_regions` | 1 | 429 | chamfer |
| `_constructions` | 4 | 554, 557, 559, 561 | chamfer, fillet, shell, text, thread |
| `_parts` | 1 | 587 | chamfer, fillet |
| `plan` | 1 | 645 | Category.REGION |
| `preview_plan` | 1 | 656 | Category.REGION |

### `forge_plan/regions.py`: 2 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `box_like` | 2 | 380, 383 | block, post, rib, tab |

### `forge_plan/shells.py`: 3 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `hollow_tool` | 3 | 122, 124, 126 | block, cylinder, sphere |

### `forge_plan/threads.py`: 2 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `thread_step` | 2 | 38, 46 | boss, cylinder |

### `forge_plan/tools.py`: 25 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `body_tool` | 7 | 319, 324, 326, 344, 359, 361, ... | block, cone, cylinder, extrusion, revolution, sphere, tube |
| `cut_tool` | 3 | 577, 581, 583 | hole, pocket, slot |
| `air_boxes` | 1 | 603 | hole |
| `side_air_boxes` | 1 | 648 | hole |
| `_inside_holds` | 1 | 680 | tube |
| `_outline_of` | 2 | 708, 718 | circle, slot |
| `_pocket` | 1 | 856 | circle |
| `_section` | 3 | 911, 915, 921 | block, post, rib, tab |
| `standing_tool` | 2 | 943, 957 | boss, tab |
| `sink_box` | 2 | 983, 987 | boss, tab |
| `_round_side` | 2 | 1083, 1093 | boss, tab |

### `forge_spec/checks.py`: 24 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_provenances` | 1 | 204 | ends |
| `_check_values` | 1 | 264 | revolution |
| `_physical` | 6 | 1237, 1246, 1258, 1260, 1262, 1277 | chamfer, fillet, hole, region, text, thread, tube |
| `_check_thread` | 1 | 1290 | boss, cylinder |
| `_rounding_limit` | 9 | 1346, 1353, 1361, 1369, 1375, 1381, ... | block, boss, cone, cylinder, hole, pocket, post, rib, slot, sphere, tab, tube |
| `_edges_missing` | 4 | 1550, 1558, 1564, 1572 | Category.BODY, extrusion, revolution, sphere |
| `_check_rounding` | 1 | 1623 | fillet |
| `_part_named` | 1 | 1746 | Category.BODY |

### `forge_spec/compare.py`: 33 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `<module>` | 3 | 73, 74, 75 | block, boss, cone, cylinder, post, rib, sphere, tube |
| `features` | 2 | 131, 135 | Category.CUT, Category.MODIFY |
| `_solid` | 8 | 196, 196, 198, 212, 218, 232, ... | cone, region, sphere, tab, tube |
| `_cut` | 5 | 298, 321, 321, 321, 324 | circle, hole, pocket, text |
| `_corner` | 1 | 364 | slot |
| `_modifier` | 5 | 375, 377, 382, 393, 406 | chamfer, fillet, shell, thread |
| `_edges` | 1 | 448 |  |
| `_rims` | 2 | 493, 501 | cone, tube |
| `_cut_edges` | 2 | 521, 523 | hole |
| `_contrast` | 4 | 944, 955, 967, 972 | ends, pocket, region, tab, text |

### `forge_spec/guide.py`: 1 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `<module>` | 1 | 478 |  |

### `forge_spec/placement.py`: 130 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `<module>` | 2 | 126, 1363 | block, cylinder, sphere |
| `height_of` | 2 | 332, 338 | cone, cylinder, sphere, tab, tube |
| `_outline_fields` | 12 | 349, 351, 352, 352, 355, 357, ... | block, boss, circle, cone, cylinder, hole, pocket, post, region, rib, slot, sphere, tab, text, tube |
| `_place_values` | 1 | 416 | ends, row |
| `_outline` | 12 | 512, 518, 518, 518, 520, 523, ... | block, boss, circle, cone, cylinder, hole, pocket, post, region, rib, slot, sphere, tab, text, tube |
| `_covered` | 1 | 564 | text |
| `_reaches` | 2 | 604, 607 | extrusion, revolution |
| `_footing` | 1 | 617 | extrusion |
| `_check_shape` | 6 | 627, 642, 642, 650, 657, 663 | hole, pocket, rectangle, revolution, slot, tab |
| `_standing` | 13 | 840, 841, 846, 849, 857, 860, ... | Category.BODY, block, boss, cone, cylinder, extrusion, post, region, revolution, rib, sphere, tab, tube |
| `_profiled` | 1 | 991 | extrusion |
| `_hollow` | 7 | 1091, 1095, 1100, 1111, 1122, 1142, ... | block, cylinder, sphere |
| `_pocket_bottom` | 1 | 1290 | circle |
| `_face_position` | 7 | 1386, 1395, 1397, 1423, 1435, 1437, ... | arc, circle, corners, ends |
| `_pattern_offsets` | 9 | 1485, 1489, 1500, 1504, 1508, 1517, ... | arc, circle, corners, ends, grid, rectangle, row |
| `_check_fits` | 3 | 1593, 1607, 1617 | Category.BODY, Category.CUT, extrusion, revolution |
| `_check_severs` | 4 | 1668, 1673, 1673, 1674 | Category.ADD, Category.BODY, shell |
| `_flat_instances` | 5 | 1789, 1789, 1792, 1796, 1810 | Category.BODY, Category.CUT, extrusion, revolution, text |
| `_check_depth` | 1 | 1832 | text |
| `_side_instances` | 10 | 1878, 1878, 1884, 1893, 1899, 1918, ... | Category.ADD, Category.CUT, arc, circle, hole |
| `_check_round_overlaps` | 4 | 2031, 2039, 2046, 2056 | Category.ADD, Category.CUT, boss, hole |
| `_make_order` | 3 | 2113, 2136, 2149 | Category.MODIFY, chamfer, fillet, thread |
| `edges_of` | 3 | 2167, 2180, 2184 | block, cone, cylinder, sphere |
| `_first_body` | 1 | 2191 | cone, cylinder, extrusion, revolution, tube |
| `solve` | 7 | 2213, 2221, 2224, 2237, 2239, 2243, ... | Category.BODY, Category.MODIFY, hole, shell, tube |
| `_check_exits` | 4 | 2345, 2345, 2353, 2400 | Category.ADD, Category.BODY, Category.CUT, tube |
| `_check_over_openings` | 1 | 2510 | Category.CUT |
| `_place_on_hosts` | 6 | 2551, 2553, 2566, 2566, 2566, 2577 | Category.ADD, Category.BODY, Category.REGION, pocket, text |
| `_round_footed` | 1 | 2611 | boss |

### `forge_spec/questions.py`: 4 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_refuse_two_edits_of_one_field` | 1 | 422 | text |
| `_sentence` | 1 | 495 | text |
| `_apply` | 2 | 552, 555 | text |

### `forge_spec/render.py`: 11 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `_axis` | 1 | 145 | arc, circle |
| `_place` | 7 | 175, 179, 181, 185, 189, 191, ... | arc, circle, corners, ends, grid, rectangle, row |
| `_pocket` | 1 | 366 |  |
| `<module>` | 1 | 399 |  |
| `_line` | 1 | 442 |  |

### `forge_spec/render_views.py`: 76 sites

| Function | Sites | Lines | Names |
|---|---|---|---|
| `<module>` | 3 | 88, 90, 91 | block, boss, cone, cylinder, extrusion, post, region, revolution, rib, tab, tube |
| `_outlined.placed` | 1 | 738 | extrusion |
| `_outlined` | 1 | 747 | extrusion |
| `_cut_span` | 3 | 851, 858, 870 | hole, text |
| `_windows` | 5 | 877, 877, 879, 879, 882 | Category.CUT, circle, hole, text |
| `_Drawing.draw` | 1 | 1056 | Category.CUT |
| `_Drawing._solid` | 11 | 1083, 1092, 1095, 1097, 1112, 1124, ... | boss, cone, region, sphere, tab, tube |
| `_Drawing._outlined` | 2 | 1178, 1194 | extrusion, revolution |
| `_Drawing._box_fields` | 2 | 1204, 1208 | rib, tab |
| `_Drawing._outline` | 8 | 1219, 1228, 1233, 1236, 1255, 1260, ... | cone, region, sphere, tab, tube |
| `_Drawing._cavity` | 2 | 1314, 1322 | block, cylinder |
| `_Drawing._cut` | 7 | 1328, 1329, 1330, 1330, 1334, 1358, ... | circle, hole, pocket, text |
| `_Drawing._corner_radius` | 2 | 1432, 1439 | pocket, slot |
| `_Drawing._cut_words` | 4 | 1468, 1490, 1491, 1505 | circle, hole, pocket, slot |
| `_Drawing._on_flat` | 9 | 1566, 1590, 1591, 1593, 1612, 1630, ... | arc, circle, corners, ends, grid, rectangle, row |
| `_Drawing._on_side` | 3 | 1673, 1688, 1690 | Category.CUT, arc, circle |
| `_Drawing._pattern_words` | 2 | 1703, 1708 | arc, circle, grid |
| `render_views` | 4 | 1791, 1792, 1802, 1802 | Category.ADD, Category.BODY, Category.MODIFY |
| `_inside` | 6 | 1832, 1833, 1853, 1856, 1864, 1883 | block, cone, post, rib, sphere, tab, tube |
