# Forge V2, stage 4b.0c: geometry, on the same numbers everywhere

Status (18 November 2026): items 0, 14, 1a, 2a and 3a done, and 3b's first
four steps (a standing item round a side at any angle; a hole, a boss or a
post on a ball's or a dome's surface, schema 1.6; on a cone's side; on a
round-ended tab's end); 1b's first and second
moves done (items turned in their face, schema 1.2; holes, bosses and posts
leaning on it, schema 1.3); its third move's first step done (positions
along a face's own axes and a turned item's far face, schema 1.4), its
second (a turned box's sides) and 2c (a turned item's edges, rounded),
neither a schema minor, and its third (a body leans, schema 1.5): its
schema 2.0 made with item 2b (revision 12). Step 5 (revision 13: a turned
box hollowed, round sides on a turned item's faces, a leaning item's edges,
a thread on a leaning rod) done but for what waits for item 2b and 4b.0d1;
3b's last step (a torus) waits for 4b.0d1's certified face-face
intersections; 2b's first step (a cut through everything, or up to a face,
schema 1.7) done, and its second (through the next face, schema 1.8, which
the preview resolves before confirmation: its third step's resolution, for
it), and a leaning item's far face (revision 16); what the exit pairs
found is fixed, and a ball's or a cone's seam is kept clear of what is on
it (revision 16), and a hole goes through the next face on a round side, a
ball or a cone, and a cut on a turned or a leaning item's face (2b's third
step, revision 16), and through everything there too, and a leaning
item's sides, flat and round, take cuts (revision 16), a slot goes round a
side as a keyway and a pocket may be a hexagon or of its own outline
(schema 1.9); next, 2b's
fourth step (schema 2.0).
Companion to [V2-stage4b.md](V2-stage4b.md),
2.1 (4b.0c) and 2.2 items 1 to 3 and 14; the decision is
[ADR-0037](adr/0037-the-same-numbers-on-every-machine.md).

---

## 1. What it does, and in what order

**First, item 0: the same numbers on any machine.** 4b.0b's end proof
found that a part's digests depend on the machine ([V2-stage4b-0b.md](V2-stage4b-0b.md),
6.4). Before anything else in 4b.0c moves, every number Forge computes is
made a function of its inputs alone, and that is proven on Linux, Windows
and macOS, x86 and ARM, with nothing pinned (section 2).

**Then items 1 to 3 and 14:** frames everywhere, depth by geometry,
analytic hosts, and the schema versions they need, each in every
independent program, proven by the same endings on stage 4's seeds,
classes the same or promoted, every change listed, and the corpus migrated
and proven oracle-equal (4b plan, 2.3). Their design follows in sections
3 to 6.

## 2. Item 0: the same numbers on any machine

### 2.1 What differs, measured

`forge-machines.yml` (run 43869616175, 16 November): the fingerprints of
200 seeds (every program's output, digested) on five machines against a
Linux x86-64 runner held to AVX2 and one OpenBLAS kernel:

| Machine | Seeds that differ | Where |
|---|---|---|
| Linux x86-64, nothing pinned | 16 | the judge |
| Linux ARM (Neoverse) | 3 | an impossible part's judge |
| Windows x86-64 (AMD) | 45 | the judge; on 13 the generator drew another part |
| macOS ARM (M-series) | 199 | almost everything |

Each cause was found by switching it alone: OpenBLAS's kernel for the CPU
(`linalg.norm` of a vector is a BLAS dot; `@`, `dot`, `einsum` and
`linalg` add in its order and fuse its multiply-adds); NumPy's SIMD paths
(AVX-512's `arctan2`, `cbrt`, `exp`, `log` and `arccos` round otherwise
than AVX2's); each operating system's C library (`sin`, `atan2`, `pow`);
and fused multiply-adds in compiled C where the compiler makes them
(Clang on macOS, Microsoft's compiler on ARM; GCC on Linux doesn't):
NumPy's `einsum`, `interp` and complex arithmetic, and CPython's own
`math.hypot` and `math.dist`, found when the adopted code still differed on
a Mac and an ARM PC and nowhere else (2.4). NumPy's elementwise arithmetic,
`sqrt` and its sums are the same everywhere, as are CPython's float
arithmetic, `math.sqrt` and `math.fsum`.

### 2.2 The design

`forge_numeric`, an L0 package (ADR-0037): the elementary functions ported
from FreeBSD's msun on Python floats (`scalar`, imported by NumPy-free
packages too) and on arrays (`vector`), bit for bit each other; products,
norms and small linear algebra summed in an order Forge fixes; polynomial
roots, `interp` and normal draws its own way; a compiled twin in Rust
behind a C interface, loaded with `ctypes` from libraries CI builds for
each platform and the project carries, used only when its interface
version, its source's digest and a self-test against the NumPy twin all
agree. Numbers and short vectors take Python-float shortcuts that perform
the same operations in the same order.

The call sites, 1,000 in all: 935 rewritten by the syntax tree
(`math.sin` to `fs.sin`, `np.arctan2` to `fv.arctan2`, `np.linalg.norm`
to `fv.norm`, `a @ b` to `fv.matmul(a, b)`, `x ** 2` to a product), the
rest by hand:

- `einsum`'s contractions as products: rows with rows (`fv.dot`), stacked
  matrix products (`fv.matmul`, with `swapaxes` for the transposed ones),
  and the second-order error bound's four-way contraction as two products
  in the frame;
- `linalg.solve`, `eigh`, `cond`, `det` to `fv.solve`, `eigh`,
  `cond_symmetric`, `det`; the one `svd` (a planar point set's two main
  directions, whose signs don't matter there) to `fv.eigh` of the scatter
  matrix;
- the companion matrices' eigenvalues (a torus's quartic, a straight
  line's nearest point on a parabola's cubic) to `fv.real_roots`, whose
  near-real pairs are double roots as the eigenvalues' were;
- `circle_crossings`' FFT, `np.roots`, `np.angle` and complex exponentials
  to a fixed DFT table, `fv.roots`, `fv.arctan2` and real arithmetic;
- the generator's `np.interp` to `fv.interp` (NumPy's formula, each
  operation rounded: the same bits as NumPy's on Linux x86);
- the second kernel's agreement jitter, `rng.normal`, to `fv.normal`
  (Box and Muller's transform of uniform draws);
- the error bound's `lgamma` to the exact log of `math.comb`;
  `floor(log10(x))` to `fs.decade` (the power of ten as the number is
  written); Cardano's cube roots to `fs.cbrt`.

The rule that keeps it so: `tests/test_v2_architecture.py`,
`EveryNumberIsTheSameOnEveryMachine`, over every V2 package and V2's
modules in V1's packages (ForgeIR v2, the second kernel's agreement and
view, the CLI's build and doctor).

**What stays outside:** OpenCascade (its own C++ and C library; a built
B-rep's last bits may differ between operating systems) and V1's frozen
implicit kernel, `forge_geom`, whose results enter verdicts through
widened intervals. Their outcomes are compared across machines, not their
bits.

### 2.3 The proof

1. **The functions** (`tests/test_v2_numeric.py`): each within two ulps of
   the platform's `math` (one of the truth); the arrays the scalars bit for
   bit, specials included; the shortcuts the long way bit for bit; the
   compiled twin the NumPy twin bit for bit; and golden digests of fixed
   inputs every machine must reproduce. `trust-core.yml` runs it on every
   push on Linux x86 and ARM, Windows and macOS; `native.yml` with each
   platform's library in use.
2. **The machines:** `forge-machines.yml` on 200 seeds, every row
   unpinned: every fingerprint equal to the reference's.
3. **Old code against new:** stage 4's exit harness on its 10,000 counted
   seeds, both on one runner (`forge-runs.yml`, mode `exitpair`): every
   outcome the same, every other difference listed and explained (last
   bits move once: ADR-0037).
4. **The suite** (every test file) and every kept regression; and the cost
   measured (the fingerprint of five seeds, on one machine: 70.0 s before
   the adoption, 80.6 s adopted, 73.6 s with the speed commit, 2.4).
5. **The speed commit, byte-identical:** the fingerprints of the sample
   equal to the adopted code's (`forge-runs.yml`, mode `pair`), and the
   numeric tests on every platform with its new library (`native.yml`).

Before the call sites moved, the generator was compared by value on 60
seeds: the same parts, every float within 2.3e-16 of the old one.

### 2.4 Status

| Step | State |
|---|---|
| forge_numeric, its tests and its compiled twin | done (`acf5a9f`, `aed942e`); golden digests reproduced on all four platforms (trust-core run 43880625574), each platform's library equal to the NumPy twin (native run 43880625544) |
| The call sites and the rule | done (`ae9dfe5`) |
| The suite on it | every file passes but `test_v2_eval_keys` (it needs the corpus, which runners don't have: run 43926576936) |
| The machines | **the same everywhere**: 200 seeds' fingerprints on Linux x86 (pinned and not), Windows x86, macOS ARM, Linux ARM and Windows ARM, 0 differences, nothing pinned (run 43926561703) |
| Old code against new | stage 4's exit harness on all 10,000 counted seeds, the code before against the adopted on one runner (runs 43926589836, 43926602844): **every seed passed on both**; the only differences are last digits of the second kernel's exact B-rep volume (114 values in 57 seeds, at most 6.8e-13 apart relatively) and of the width the agreement widens it by (89 values, 3.5e-11): ADR-0037's one move of last bits, no outcome, count or verdict |
| The speed commit | done (`fc36206`): the fingerprints of 200 sample seeds byte-identical to the adopted code's on one runner (run 43951936987); each platform's library built and tested (native run 43938379282) |

Item 0 is done.

What the machines found on the way (2.1's last cause): with every
elementary function and product replaced, a Mac and an ARM PC still
differed in the judge on 197 of 200 seeds. Replacing CPython's
`math.hypot` and `math.dist` (whose multiply-adds Clang and Microsoft's
ARM compiler fuse) was not enough; `tests/v2_values.py`, which writes
every value the judge makes and walks two machines' files to the first
that differs, found the next: NumPy's `Generator.uniform`, whose
`low + range * u` is fused in C there. Draws now go through `fv.Draws`
(NumPy's PCG64 bits, the arithmetic in ufuncs, unfused), and with it the
judge's values on seeds 0 to 3 are identical on Linux x86, macOS ARM and
Windows ARM (values run 43918882473). `fs.hypot` first computed
`sqrt(x*x + y*y)` scaled, which moved two tests' 4.0 to
3.9999999999999996; it is now CPython's own algorithm (the coordinates
scaled by a power of two, the squares summed exactly in two parts, the
root corrected once) with Dekker's exact products for its fused ones:
the same bits as CPython's on Linux on 760,000 inputs, in all three twins.

The cost, and the speed commit: the adopted code took 80.6 s for five
seeds' fingerprints against 70.0 s before (+15%), mostly the hypot: the
Python one on numbers, and the compiled one on arrays at 15 ns an element
where NumPy's took 11. The speed commit hands numbers of two and three
coordinates to the compiled twin (opened without NumPy, so the scalar side
stays free of it), reads the array hypot's common case from its bits in
two branch-free passes, four lanes at once where the processor has AVX2
(2.7 ns an element), hands arrays over by the buffer protocol, and
compiles every 2-D matrix product with a short contracted axis: 73.6 s
(+5%), the rest the per-call cost of small Python wrappers, which
4b.0d1's compiled core removes.

## 3. Items 1 to 3 and 14: how they are made, in what order

Status: design, revision 2, 16 November 2026 (revision 1 the same day;
3.3 says what reading the solver changed). Item 14 is built (3.2, on
`spec/versions`: 130 held drafts read and judged the same before and
after, only the guide and the schema changed); the rest is built in 3.1's
order.

### 3.1 The principle: refactor first, then the new ability

Each item changes what every independent program computes (the solver's
placement, the judge's placement and oracle, the check compiler, the
planner and compiler, the generator, the second kernel's capability
table), each its own way, as R2 requires. Each is made in **two moves**:

- **(a) the substrate.** The program's representation becomes the
  general one (a frame of vectors, a host protocol, an end condition),
  carrying exactly today's cases. Proven as 4b.0b was, every seed's
  fingerprint (everything a verdict consumes) byte-identical on the sample
  under two hash seeds, the regressions, the suite, where the
  representation keeps today's arithmetic (3a, 2a); for frames (1a), whose
  oriented boxes compute a centre otherwise than an axis-aligned box's,
  every value within a few ulps of the old (3.3). No semantics move, so a
  fault is a refactoring fault, found at once.
- **(b) the new ability, old against new.** The general cases are let in:
  rotated items, tilted and curved hosts, end conditions. Proven by stage
  4's exit harness on its 10,000 seeds, old code against new on one runner
  (`exitpair`): the same endings, classes the same or promoted, every
  change listed; the corpus specs migrated (item 14) and proven
  oracle-equal; and the new cases each with tests, mutants and near-misses
  in every program, the generator drawing them.

The order: **14 first** (every later change to the spec is a migration),
then **1a, 3a, 2a** (the three substrates, one at a time, each proven
byte-identical before the next), then **1b, 3b, 2b** (each ability proven
before the next starts). 2b last because it retires the solver's
"material under a face" algebra, the largest change of meaning.

### 3.2 Item 14: schema versions and migrations (ADR-0026)

**Today:** every draft says `"spec_format": 1`, an integer the reader
requires and `to_wire` writes, so it is in every confirmed spec's hash
(`lock.spec_digest`); nothing reads a minor version or migrates.

**Made** (`forge_spec/versions.py`, `forge_spec/migrations/`,
`tests/v2_migrations.py`):

- `schema_version` ("major.minor") replaces `spec_format` in what Forge
  writes (`to_wire`, the guide's schema, example and instructions, the
  generator's and the tests' drafts). A draft that says `"spec_format": 1`
  is version 1.0, read and migrated; one that says neither, both, a
  malformed version or one newer than this Forge reads is refused, at the
  field at fault.
- **A spec is read in the current version**, whatever version its draft
  was written in: `PartSpec` carries no version, so every program sees one
  schema.
- **A confirmed spec stays confirmed.** The version lives with the lock:
  `ConfirmedSpec.version` is the version it was confirmed in, and its hash
  is of the spec written in that version's form (`to_wire(spec, version)`,
  each version's form kept, as its migrations are). `unlock` checks a
  lock's hash in the form it was confirmed in, then reads it as this
  version reads it; a lock is never re-hashed silently. A migrated spec
  whose shown content differs is confirmed again (ADR-0026's
  re-confirmation rule: the first major step's to make).
- `forge_spec/migrations/`: one module per major step, each a pure
  function from a draft's JSON at one major version to the next, kept
  forever, registered in order (`STEPS`); `versions.migrate(raw) -> (raw,
  the version it was written in, the steps made)`. A minor version only
  adds optional fields and needs none.
- The proof of a migration, `tests/v2_migrations.py` (and
  `forge-runs.yml`'s mode `migrations`): every draft Forge holds (the
  suite's drafts, `v2_suite_specs`; the kept regressions' parts; and each
  counted seed's part, mutant and impossible part) is collected **as
  stored** on the code before the step, then read and judged on both
  sides (the code after migrates it as it reads it), and the records held
  against each other: the report plain and strict (spec, solved layout,
  problems, accounting) and the judge (placement, oracle, check suite and
  its lists), to the last bit where the step is a substrate (a) and with
  each changed digest listed where it is an ability (b).
- The hash: the confirmed spec's hash covers its version (item 27's other
  inputs land with their items).
- Item 14's own step makes the version 1.1: `schema_version` in place of
  `spec_format`, nothing else (a minor step, so 1.0 drafts read as they
  are). The first major migration, 1.x to 2.0, is items 1b's and 2b's:
  positions keyed by face axes and depth as an end condition (3.3, 3.5).

### 3.3 Item 1: frames everywhere

**Today:** every program reasons in the part's axes. A face is named by a
signed axis (`+z`) and carries its two axes by name (`("x", "y")`, the
table in `frame.md`); an item rises along its face's normal; a copy is a
box (`lo`, `hi`). Axis names appear 114 times in the solver's placement
and views, 124 in the generator and its truth, 44 in the judge's
placement and compiler, 13 in the planner. Only the oracle's solids carry
vector frames (`forge_checks.shapes.Frame`), and ForgeIR v2 places by
rigid motions.

**1a, the substrate:** each program's face and copy carry a `Frame`
(origin, and unit vectors `u`, `v`, `n`: `n` the outward normal, `u` and
`v` the face's first and second axes as `frame.md`'s table gives them, so
`u × v` is `n` on three faces and `-n` on the others, kept so: positions
keep their signs), and each copy its own frame (its item's axes in the
world). The axis-name tables become one
function per program that makes the frame for a named face of an aligned
item. An aligned frame is applied by choosing a component and its sign,
never by a product with 0 or 1 (a product would turn 0.0 into -0.0, which
a digest sees), so the bits can't move and byte identity proves the
refactor; a general rotation is applied only to a frame that isn't
aligned. Each program keeps its own `Frame` (R2: the solver's in
`forge_spec`, the judge's in `forge_checks`, the generator's in
`forge_eval`), each built from the definitions, not from another's.

**Decided in revision 2 (found reading the solver):** the solver's bodies
are axis-aligned boxes (`Instance.lo`, `hi`) and their faces are made from
them (`_box_faces(lo, hi)`: a face's centre is `(lo + hi) / 2`, its half
sizes `(hi - lo) / 2`); the generator's and the judge's placement are the
same. A frame-and-extents body (an oriented box) computes those numbers
otherwise (`centre ± half · n`), so a byte-identical 1a would keep the
boxes' arithmetic behind the frame only to drop it in 1b. Instead, 1a
moves each program to frames and oriented boxes at once, **one program at
a time** (the solver; the judge's placement, oracle and check compiler;
the generator and its truth; the planner and the second kernel's view),
and proves each by **every value of stage 4's parts within a few ulps of
the old** (`tests/v2_values.py`, on the sample, aligned parts only: a
refactoring fault moves a value by far more than an ulp) and the same
fingerprints in every section that holds no computed length. The ability
(1b) is switched on only when every program has it.

**Revised in revision 3 (building the solver's):** a box is kept **in its
own frame**: a copy's frame (its item's axes in the part) and its box's
corners in that frame's coordinates. An aligned copy's frame is the part's
own, so its corners are today's numbers, and the faces made from them
are; only a turned copy's (1b) map through its frame. So 1a moves no bit
after all, and each program's step is proven as 3a and 2a are: the
fingerprints byte-identical. In each program, every place a face's
two coordinates become the part's three, or a direction is read off a
face, goes through the face's `Frame` (origin, `u`, `v`, `n`), applied by
choosing coordinates where it is aligned; the faces' frames are computed
from what they hold, so no record gains a field until 1b.

| Program | 1a | Proof |
|---|---|---|
| The solver (`forge_spec.frames`; its faces, round sides, positions, pockets' floors, letters) | done | the fingerprints of 40 sample seeds byte-identical |
| The judge's placement, oracle and check compiler (`forge_checks.place.FaceFrame`; its faces and round sides, positions, cuts and pockets' floors, the way round a side, the layouts' comparison; the compiler's and the oracle's face directions) | done | the fingerprints of 40 sample seeds byte-identical |
| The generator and its truth (`forge_eval.generator._FaceFrame`; its faces' and round sides' points and plane coordinates, axes, letters' reading direction, extrusions' ends and walls' pressed feet) | done | the fingerprints of 40 sample seeds byte-identical |
| The planner and the second kernel's view | nothing to move (below) | |

The planner and the second kernel need no step of their own: their
geometry is ForgeIR's, each primitive's box in its own frame with its faces
named by role (`x_max`), placed by a rigid motion (ForgeIR v2), so an
aligned copy's motion is a translation and its roles the part's directions.
What the planner reads off a copy's box (an edge's run, a box flattened to
its face, a hollow's walls) it reads in the copy's frame from 1b, when a
copy can turn; the second kernel reads roles in each primitive's own
frame already.

**1b, in three moves (revision 4, 17 November 2026),** each switched on
in every program at once and proven by the exit pair on all 10,000 seeds
(the same endings; the generator's new draws a fraction, so today's
distribution stays the bulk), with tests, mutants and near-misses of its
own:

1. **A turn about the face's normal** (`place.turn`, an angle from the
   face's first axis, optional: schema 1.2, a minor step). What stands on
   or is cut into a flat face may be turned in its plane: a slot, a
   pocket, a rib, a tab, a block or a post, a line of letters. Its
   footprint is its outline turned (the solver's fits, overlaps and edge
   distances on the turned outline; a position measured to its edge, to
   the turned outline's extent); the judge's placement and oracle build it
   in the copy's turned frame, the compiler aims its probes along it; the
   planner writes the copy's placement as a rigid motion (ForgeIR v2); the
   generator draws a turn for some items and its truth builds them turned.
   A turn of a round footprint (a hole, a boss) is refused as meaningless,
   and a pattern's copies turn with the pattern.
2. **A tilted direction** (`direction`: the default `normal`, a tilt from
   it towards one of the face's axes, an item's axis): a hole or a post
   at an angle to its face. Its mouth is the section of its shape by the
   face (an ellipse for a round hole), which fits and overlaps use; the
   material under it is measured along the direction (schema 1.3).
3. **Oriented bodies and item-local faces** (`orientation`), and positions
   keyed by face axes (`place.u`, `place.v`): the major step, 1.x to 2.0,
   its migration proven by `tests/v2_migrations.py`.

**1b's first move, as built (revision 5, 17 November 2026).** `place.turn`
(schema 1.2) turns a slot, a rectangular pocket, a rib, a tab, a block, a
post or a line of letters in its flat face's plane, from the face's first
axis towards its second, about its point; a round footprint (a hole, a
boss, a round pocket), a round side and `concentric` refuse it as a fault
(place.md, "Turned in the face"). In each program:

- **The solver** fits, holds apart and measures the material under each
  copy on its turned outline (letters on their ink's box turned with them),
  measures a position `to` `edge` to the turned outline's extent, and asks
  where what stands on the far face meets a turned cut's mouth, or where
  something stands wholly over one, on the exact turned outlines; a turned
  item's own faces are closed ("a later move"), and a rounding of its edges
  or a shell of it is UNABLE.
- **The judge's placement and oracle** build each copy in its turned axes
  (`Copy.turn`); **the check compiler** measures a turned box's sizes
  between its turned sides, a turned cut's floor and a round-ended tab's
  end along them, and holds a turned copy's position and its turn (a leaf,
  `place.turn`) by face accounting: its faces are where the oracle builds
  them, or it fails (the two placements agreeing besides). What turns, and
  how far round, is each kind's own to say in each program's registry
  (`turnable`), as 4b.0b's ratchet holds every kind's choice.
- **The planner** writes a turned prism or cut as its turned outline, a
  `profile_outline` of straight sides and true arcs on the face's plane,
  pushed out or in (the same numbers as the solver's outline); letters as
  their `text` step with `up` and `right` turned; a round-ended tab (its
  stadium lies in a plane square to the face) by ForgeIR v2's rigid motion,
  a `transform` of its unturned stadium, kept within its turned foot's box
  made after the motion. Every box it proves things by is the box round the
  turned outline, which holds for any proof made with it.
- **The generator** turns one in five of the items that can be, each from a
  stream of its own (a seed that turns nothing draws what it drew before;
  where a turned item doesn't fit, the item as drawn is tried); its truth
  is built in the turned axes; its fits use the box round the turned
  outline; its mutants include the turn moved by 5 and 20 degrees. A draft
  says schema 1.2 only when it turns something (`draft_of`), so every other
  spec keeps its digest.
- **The comparison of two drafts** reads a turned outline by the box round
  it, its own longer way (unsigned) and its own sizes: drafts turned alike
  agree, turned otherwise they differ.

Tests: `tests/test_v2_spec_turn.py` (the solver's and the comparison's),
`tests/test_v2_plan_turn.py` (built and judged on every face of a cube and
both ways round; a turn half a degree off, or a copy 0.05 mm off, fails face
accounting; the second kernel agrees, the rigid motion included).

**1b's second move, as built (revision 6, 17 November 2026).** `tilt` and
`tilt_towards` (schema 1.3) lean a hole (plain or counterbored), a boss or a
post (turned too) from square to its flat face, towards one of the face's
axes, `+` or `-` (turned with the item): its direction is the face's normal
turned that far towards that way, and its height or depth is along it
(place.md, "Leaning on the face"). It leans only where the material under its
face is the same everywhere (a block's face, a cylinder's end, a standing
box's side), so what is under it along its direction is known exactly; more
than 75 degrees, a countersink, or any other face is UNABLE for now (the
material along a direction is item 2b). What leans is each kind's own to say,
in each program's registry (`leans`), as what turns is. In each program:

- **The solver** (`forge_spec.lean`) places a leaning copy by its foot, its
  cross-section's section by the face (the polygon of 128 tangents round the
  ellipse, and the four at its extremes, so its box is the ellipse's own);
  holds a blind hole to `D cos + r sin <= T`, takes a hole right through
  `(T + r sin) / cos` along it, asks where what stands reaches back into the
  face further than `T`, shifts a through cut's way out on the far face by
  `T tan` against the lean, gives the copy its `direction`, and closes its
  faces; a rounding of its edges, a shell or a thread of it is UNABLE.
- **The judge's placement and oracle** build its solid run along its
  direction, a prism kept on the face's open side or within its material by
  a half-space (`Copy.lean`); **the check compiler** fits a leaning hole's or
  boss's side where it is all round (from `r tan` past the face to its floor,
  or right through, `r tan` short of the far side), measures a post's sizes
  between its tilted sides, and leaves its height or depth along the lean,
  and the lean, to face accounting (a lean half a degree off fails it).
- **The planner** writes a hole as its cylinder (and its counterbore's) along
  its direction, `intersect`ed with a box from the face's plane through its
  material; a boss as its cylinder and a post as its upright prism turned by
  ForgeIR v2's rigid motion about the line in the face square to its lean,
  each kept on the face's open side by a box.
- **The generator** leans one in five of the holes, bosses and posts that
  can, from a stream of its own, only on faces with the same material under
  all of them (`_Flat.level`); its truth builds a prism kept between two
  planes (`truth.Kept`), meshed by manifold3d's `trim_by_plane` and built
  exactly by OpenCascade's common with a slab; it keeps each leaning item's
  whole shadow on the face (from its foot to its top's cross-section, or its
  floor, or where it comes out) clear of everything, over the face and over
  its far face; its mutants lean 5 and 15 degrees more or less, or the other
  way. A draft says schema 1.3 only when something leans.
- **The views** draw a leaning item as its outline seen along each view (the
  hull of its foot and its far end), a cut's hidden but where its mouth is
  seen, its sizes said along its lean, and through, what can be seen through
  it where its mouth and its way out overlap. **The comparison of two
  drafts** reads a leaning cut's way in, and a boss's or a post's axis, along
  its direction; **the spec grade** counts a leaning hole right through by its
  own line.

Found on the way and fixed: the views measured a turned item's position to
its edge to its unturned outline's, and an extrusion's or a revolution's to
the box round its outline about its point; each is now drawn as the solver
measures it (`check_every_value_shown` on generated parts).

Tests: `tests/test_v2_spec_lean.py` (the solver's, the comparison's and the
spec grade's), `tests/test_v2_plan_lean.py` (built and judged on every face
of a cube, both ways, a hole's side nowhere all round; a lean half a degree
more, or the other way, fails face accounting; the second kernel agrees, the
rigid motion included).

**1b's third move, designed (revision 7, 17 November 2026): in four
steps, each its own schema minor or major and proof.** A turned or leaning
item's faces are closed today, and a body's axes are the part's. Each
step opens a class of faces whose frame isn't the part's, and only the
last changes what a draft means:

1. **Positions along a face's own axes, and a turned item's far face
   (schema 1.4).** `place.u` and `place.v` name a position along the
   face's first and second axes, on any flat face; `x`, `y`, `z` stay its
   aliases on a face whose axes are the part's, and are a fault on one
   whose aren't. The face opposite the one a turned box stands on (a
   block's, a post's, a rib's or a tab's far face) takes things: its
   normal is its host face's, its axes turned in its plane with it
   (`FlatFace.turn`, each program's own). What is placed on it is placed
   in its frame and, as every other program reads it, is an item turned
   by the face's turn and its own on an aligned plane: a round one is the
   same turned; one whose outline isn't round and that doesn't turn (an
   extrusion) is UNABLE there. Its material is the box's height and,
   where its turned outline lies wholly on a host with the same material
   under all of it, the host's; elsewhere it is closed for now.
2. **A turned or leaning item's other faces (schema 1.5):** faces whose
   normal is no frame axis. Every program places, measures depth and
   builds along a face's frame: the solver's and the judge's faces carry a
   `Frame`, the oracle's solids already do, the compiler aims along it,
   the planner places by ForgeIR v2's rigid motions, the generator's truth
   computes in frames.
3. **Oriented bodies (schema 1.6):** `orientation` on a body, the first
   included: a turn about each of its own axes in order. Its faces are its
   own (`+x` is its own +x side), each with its frame, as step 2 places.
4. **Schema 2.0:** a draft writes positions along `u` and `v` only; the
   migration rewrites every `x`, `y`, `z` position to its face's axis,
   proven on every draft Forge holds by `tests/v2_migrations.py`.

**1b's third move, step 1, as built (revision 8, 17 November 2026).**
Schema 1.4. A position and its side, a pattern's values, counts and axis,
an `along`, a `thickness_along` and a lean's way name a flat face's axes by
the face's own names, `u` (its first) and `v` (its second), or, on a face
whose axes are the part's, by the part's (`x`, `y`, `z`): an item names them
one way, the part's are a fault on a turned face, and `u` and `v` are a
fault round a side (place.md, "On a flat face"). A turned block's, post's,
rib's or square-ended tab's far face takes things: its axes turned in its
plane with it, its own height and its host's material under it where its
turned outline lies wholly on a host with the same material under all of
it, closed elsewhere (place.md, "A turned item's far face"). In each
program:

- **The solver** places an item on a face named as the item names its axes
  (`FlatFace.spelled`: `u` and `v`, its frame the same; on a turned face
  always), so what it says and where it says it are the draft's own; and it
  hands every program after it the item **as placed**
  (`placement.as_placed`, `placed_spec`): named by the part's names for the
  face's axes and, on a turned face, turned by the face's turn and its own,
  an item turned on an aligned plane. So the planner, the views, the
  comparison of drafts, and the solver's own exits, edge checks and order,
  read an item on a turned face as move 1's turned item. `FlatFace.turn`
  turns a face's frame (`Frame.turned`); what stands on a turned face
  carries its turn to its far face (a round item's too, its other faces
  closed); a pocket's floor turns with its face, and a turned pocket's
  takes things too, on a face with the same material under all of it; an
  item whose outline neither turns nor is round is UNABLE there.
- **The judge's placement** reads `u` and `v` as the face's axes
  (`in_axes`), turns its own faces (`FlatFace.turn`), gives a copy on a
  turned face its turn as placed (`Copy.turn`, both turns added in
  degrees, so a quarter turn stays exact), and keeps a turned box's far
  face and a turned pocket's floor by the same rule, the same material
  under a face read alike for those and a lean (`same_under`: a standing item's far face
  wholly over a host with the same material under all of it is such a
  face). **The oracle** builds along the copy's turned axes; **the check
  compiler** names each check and each note as the draft names its leaf
  (`place.u`), tells a choice of axis from the others named the same way,
  and leaves where an item on a turned face is to face accounting, as a
  turned item's.
- **The generator** puts an item on a turned box's far face from a stream
  of its own (a hole, a slot, a pocket, a boss, a cylinder, a block, a post
  or a rib, turned or leaning there too now and then), drafted along `u` and
  `v`; and, from another, now and then names an item's face's axes by `u`
  and `v` on any flat face. A seed that does neither is drawn as it was;
  its truth is built in the turned face's frame (`_Flat.turn`). A draft
  says schema 1.4 only when it names `u` or `v`.
- **The guide** says `u` and `v` and the turned far face; **the views** draw
  an item as placed and name each value as the draft does, saying in words
  where an item on a turned face is.

Found on the way and fixed: the judge refused a lean on a standing item's
far face wholly over a host with the same material under all of it (a
boss's on a plate), which the solver gives one (`same_under`).

Tests: `tests/test_v2_spec_faceaxes.py` (read, written and cited; the same
item said either way placed the same on every face; the far face's turn and
material, the part's axes a fault there, turns adding, a round item the same
turned, a face without the same material under all of it closed, an outline
that doesn't turn UNABLE, leaning and in a pattern on it, a turned
pocket's floor; the views),
`tests/test_v2_plan_faceaxes.py` (built and judged: along `u` and `v` on the
plate; on a turned post's or block's far face a hole through or blind, a
slot along its own axis, a round pocket, a boss, a post turned again, a
leaning hole and a row of holes; a hole in a turned pocket's floor; what is there turned half a degree more
fails face accounting; the second kernel agrees).

**1b's third move, step 2, as built (revision 9, 17 November 2026).** No
schema minor: no field is new, and what was UNABLE now builds, named as
schema 1.4 names a turned face (along `u` and `v` only). So 1.5 is step 3's
(oriented bodies), 2.0 stays step 4's, and a leaning item's faces wait for
item 2b (depth by geometry: the material under a leaning item's far face
isn't the same under all of it, and a cut right through it comes out on a
face that isn't square to it). A turned block's or post's sides take things
(place.md, "A turned item's faces"): each named as with the box upright, its
own size across it under it, a cut through it coming out on the side across.
What is on one is placed on it with the box upright, then moved by the box's
own motion, its turn about the line through its point square to its face.
In each program:

- **The solver** keeps a turned box's sides as found upright, with the
  motion that takes them onto the part (`FlatFace.local`, a
  `frames.Rigid`, which composes, inverts and moves points, vectors, frames
  and boxes); an item on one is placed on the upright face
  (`FlatFace.upright`) and moved: each copy keeps the motion
  (`Instance.frame`) and itself upright (`Instance.local`), its own faces
  moved with it (turned again where it is turned there). Its exits are
  checked upright. The face a box is joined by is a fault; a rounding of a
  moved item's edges, what stands round a moved round side, a concentric
  item and hollowing are UNABLE for now.
- **The judge's placement** does the same in its own code (`Motion`,
  `FlatFace.local`, `Copy.frame` and `Copy.local`), and every layout agrees,
  motions included. **The oracle** builds a moved copy upright and moves its
  solids (`forge_checks/moved.py`); **the check compiler** leaves where it
  is to face accounting, as a turned item's.
- **The planner** makes a moved copy's tools upright and moves each by a
  `transform` step (ForgeIR v2's rigid motion, which keeps a tool's face
  names on the moved faces), its boxes and the faces named by the way they
  face moved with it (`forge_plan/moved.py`).
- **The generator** keeps a turned box's sides (`_Flat.oriented`: their
  axes on the part) and puts cuts and standing items on them from the
  stream that puts items on turned faces; of their faces it keeps none.
- **The views** say in words where an item on a turned item's side is.
  **The second kernel's agreement** excuses a moved tool's faces at its
  mouth as it does any tool's, where the last step that has them leaves
  them, once moved.

Found on the way and fixed: a turned box's open faces were also recorded
closed (a turned pocket's floor rule ran on what stands as well).

Tests: `tests/test_v2_spec_faceaxes.py` (a turned box's sides: their frames
and material; placed on upright, then turned, in a row and leaning; the
part's axes a fault there, its joined face none; a boss's far end and a
post's faces on one; a post's sides turned by both turns on a turned post's
far face; the views), `tests/test_v2_plan_faceaxes.py` (built and judged on
a turned post's sides: a hole right through or blind, a slot, a round
pocket, a boss, a post turned there, a leaning hole, a row of holes, a hole
in the side of a post turned on its side; what is there turned half a degree
more fails face accounting; the second kernel agrees and names alike).

**1b's third move, step 2c, as built (revision 10, 17 November 2026): a
turned item's edges.** No schema minor (what was UNABLE now builds). A
rounding or chamfer of a turned item's edge set, or of what is on a turned
item's faces, rounds the edges the set names with the item upright and
unturned, turned with it (edges.md, "A turned item's edges"); a leaning
item's stay a later move. In each program:

- **The solver** no longer refuses them (its edge sets are by face names,
  the same either way).
- **The judge's oracle** finds a copy's edges as it stands upright and
  unturned (`forge_checks.moved.upright`: its turn in its face, then the
  motion of what it is on; `Motion.inverse`), on its solid moved back, then
  moves each chain onto the part (`moved_chain`); a joint's foot the same.
  What it rounds is then found on the part as any rounding's is.
- **The planner** names a turned box's sides by the way each faces turned
  (an extrusion's `side` faces) and keeps, for a turned box and for what is
  built upright on a turned item's face, the box round it upright and the
  motion onto the part (`Chain.motions`); its edge queries are found on that
  box, then moved (`moved_where`), each counted where it is.
- **The generator** rounds a turned item now and then from the stream that
  rounds the rest, its truth in the item's turned frame (`_round_box`,
  `_round_cut`).

Tests: `tests/test_v2_plan_turnedges.py` (built and judged: a turned post's
vertical, top and joint edges, a turned block's top edges bevelled and its
vertical edges a quarter turn round, a turned rib's top edges, a turned
pocket's floor, a turned slot's mouth, a boss's rim and a hole's mouth on a
turned post's side and on its far face, a block turned on its side, a post
turned on its far face; an edge left out fails; the second kernel agrees).

**1b's third move, step 3, revised and built (revision 11, 17 November
2026): a body leans.** Revision 7's oriented bodies were a turn about each
of a body's own axes, the first body's included. The first body's frame is
the part's by definition (frame.md), so turning it changes no part, only
how its faces are named; a body standing on a face that turns about any
axis but the face's normal meets the face at an edge or a corner, unless it
is cut back by the face's plane, as a leaning post is. So what step 3 adds
is the lean (schema 1.5): a block or a cylinder standing on a flat face may
lean as a post or a boss does (`tilt`, `tilt_towards`; place.md, "Leaning
on the face"), its height (a cylinder's length) along its direction, turned
in its face too where `place.turn` turns it. A body's lean in an older
draft is a fault naming 1.5; a hole's, a boss's and a post's stay 1.3's.
As a leaning post's, its faces take nothing, its edges aren't rounded and
it isn't hollowed yet (after item 2b, with a leaning item's faces). In each
program, the lean reused: **the solver** bounds a leaning body by the
field it rises by (`SolveKind.height`); **the judge** leans a block and a
cylinder (`PlaceKind.leans`, `PlaceKind.rise`), the oracle's solids lean
already; **the planner** builds a leaning block as a leaning post and a
leaning cylinder as a leaning boss (`leaning_standing`); **the generator**
leans a block or a cylinder now and then from the leans stream
(`DrawKind.leans_round`, `leans_since`; a draft says 1.5 only when a body
leans); **the views** say a leaning cylinder's length along its lean.

Tests: `tests/test_v2_plan_leanbody.py` (1.5's own, a fault before; placed
as a post leans; built and judged: a block leaning, turned and leaning, on
the plate's side, a cylinder leaning; half a degree more fails; the second
kernel agrees).

**1b's third move, step 4, decided (revision 12, 17 November 2026): schema
2.0 waits for item 2b.** Two majors are planned: step 4's (positions along
`u` and `v` only) and item 2b's (each `depth` written as an end condition).
Each rewrites every draft Forge holds, and a writer of drafts learns each
once; so they are one major, 2.0, made with 2b, its one migration proven by
`tests/v2_migrations.py`. Until then `x`, `y` and `z` stay a face's axes'
other names wherever the face's axes are the part's, as 1.4 reads them (a
brief's "10 mm along X" is said as said), and a face whose axes aren't the
part's (a turned item's) takes `u` and `v` only. So 1b's third move is done
with step 3; 3a's second part is next, then 3b, then 2b with 2.0.

**1b's third move, step 5, planned (revision 13, 17 November 2026): what a
turned or leaning item still lacks.** Each refusal Forge still gives a
turned or leaning item, and where it is lifted:

1. **A turned box hollowed** (a shell of a turned block): its hollow made as
   with it upright, then turned with it; its inside faces turned so. Now.
2. **A round side on a turned item's face** (the side of a boss, a cylinder
   or a tube standing on a turned box's side, or on anything moved there):
   what is placed on it placed as on that side upright, then moved. Now.
3. **A leaning item's edges**: its far end's (a post's or a block's top
   edges, a boss's or a cylinder's rim) found as upright and moved by its
   lean; a leaning box's edges along its lean the same, each running from
   the face's plane, where it meets it. Now. Its joint (where it meets its
   face: a leaning boss's an ellipse whose angle to the face changes all
   round it) with 4b.0d1's certified face-face intersections.
4. **A thread on a leaning rod**: threaded as upright from its far end,
   moved by its lean, kept clear of its foot. Now.
5. **A leaning item's faces** (its far face, a box's sides), **a leaning
   body hollowed**, and **a turned item's far face over a host without the
   same material under all of it**: the material under each isn't the same
   under all of it, so each comes with item 2b, which measures depth on
   the shape itself.

Steps 5.1 to 5.4 come before 3a's second part, each proven as step 2 was
(the judge's layout and oracle, the planner, the generator, the second
kernel, the exit harness old against new).

**Step 5.1, as built (revision 13).** A turned block is hollowed as it
stands upright, then every face of it, its far face and its inside faces
too, turned with it: the solver hollows it on its upright box and moves its
faces; the judge's placement does the same; the oracle hollows its solid
moved back upright (its own earlier roundings' edges and zones moved back
with it) and moves the hollow onto the part; the check compiler measures
each wall on the face as it is on the part; the planner makes the hollow's
tool upright (following the body's roundings) and turns it with a
`transform`. **The generator** hollows a block it has just stood on a face
now and then (`DrawKind.standing_shell`, `hollow_standing`, from a stream
of its own, so a seed that hollows nothing standing is drawn as it was):
upright or turned in its face, sealed or open on its far face, its walls
the material under its faces and its inside faces turned with it; until
then it hollowed only the first body, so a box standing on the part was
never hollowed in a generated part. And it reads where a cut right through
a turned item's far face comes out at its place there, along that face's
own axes (`_on_exit`): it had read it in the turned face's coordinates, so
a hole through a turned tab could come out under a block standing on the
far end (the exit run's seed 1436, the one part the judge could not
conclude on). A leaning body's hollow waits for item 2b. Tests: `tests/test_v2_plan_turnedhollow.py` (its faces turned; built
and judged: open at its top, a thicker floor, its vertical edges rounded
first, a hole through an inside wall, its rim rounded; its hollow turned
half a degree more fails; the second kernel agrees),
`tests/test_v2_eval_truth.py` (each sort drawn now and then, its mesh its
truth) and `tests/test_v2_plan_build_generated.py` (its first part built,
judged and graded).

**Step 5.2, as built (revision 13).** A round side keeps, as a flat face
does, the motion that takes it onto the part (`SideFace.local`, the judge's
`RoundSide.local`), its axis and start as they are with its item upright;
what is placed round it is placed so and moved, as on a turned box's side
(step 2), and every layout agrees, each side's frame on the part included.
A cut round it is carried into the air past its mouth (5.2's own
construction) where that is proven clear where it is moved to
(`tools.carried_ways`: the regions worked out upright, then moved). Tests:
`tests/test_v2_spec_faceaxes.py` (a hole round a boss on a turned post's
side, placed upright, then moved), `tests/test_v2_plan_faceaxes.py` (built
and judged: a blind hole round a boss on its side, a hole through a rod
and through a tube's wall on its sides, a boss round a rod on its side;
the second kernel agrees).

**Step 5.3, as built (revision 13).** A leaning item's far end's edges
and a leaning box's edges along its lean are rounded and chamfered
(edges.md, "A leaning item's edges"): the judge finds them on its solid
moved back upright (`moved.upright` undoes its lean, about the line
through its point in the face square to it, after its turn), then leans
the chains; the planner names a leaning box's far face and sides (its sides
by the way each faces leaning) and a leaning rod's end and side, and keeps
the box round it upright, from where its tool starts behind its point, with
the motion that turns and leans it, so each long edge's query holds all of
the line it lies on out of the face. Its joint waits for 4b.0d1. Tests:
`tests/test_v2_plan_turnedges.py` (a leaning post's top edges, a leaning
turned post's long edges bevelled, a leaning post's long edges then round
its top, a leaning boss's rim, a leaning block's top edges, a leaning
cylinder's rim; an edge left out fails; the second kernel agrees),
`tests/test_v2_spec_lean.py` (its joint still waits).

**Step 5.4, as built (revision 13).** A thread on a leaning boss or
cylinder runs along its lean from its far end (thread.md), in the oracle,
the check compiler and the planner (each takes the copy's lean for its
axis); the solver keeps it clear of the foot, where the rod's side meets
the face's plane up to its radius times the tangent of its lean from its
point: a thread longer than the rest of the rod (all of it, where no length
is given) is a CAN'T that says how long it may be. Tests:
`tests/test_v2_plan_leanbody.py` (a leaning boss and a leaning cylinder
threaded, built and judged; threaded square to the face instead fails),
`tests/test_v2_spec_lean.py` (all along it, a CAN'T; shorter, read).

**Step 5's leaning far face, as built (revision 16, with item 2b).** The far
face of a leaning boss, post, block or cylinder, not turned and not
hollowed, takes a hole, a pocket, a slot or what stands on a face (place.md,
"A leaning item's far face"); no schema change. It is placed on as with the
item upright and then leaned, as a turned item's faces are (1b's third
move, step 2): about the line through the item's point square to its face's
normal and its lean, by its tilt. **The solver** keeps it as the upright
far face with that motion (`_leaning_motion`) and the material under it a
`Slant` (`forge_spec.geometry`): its height on the axis, `tan` less for each
millimetre towards its lean, read by the least and the most under a
footprint (its reach that way: a disc's, a rectangle's, a turned outline's
sides and arcs), so a blind cut too deep on the low side is asked; a cut
right through it, which would come out on the face it leans on, it can't
yet. **The judge** does the same on its own (its `Slant` material, its
`Motion`), opening only the far face of a leaning copy; **the planner**, the
oracle and the check compiler build and measure what is on it as on any
moved face (built upright, then moved). **The generator** registers each
leaning standing copy's far face (`_leaning_far`), oriented as it leans
(each of its axes' part along the lean tipped with it), with its own slant
of material, and draws a blind hole, pocket or slot on one now and then
(`_onto_leaning`, stream "forge-eval leaning faces", 0.6 where a part has
one); a turned item's face stream leaves it alone. Tests:
`tests/test_v2_plan_leanfar.py` (twelve parts placed where every program
puts them, a hole in a pocket's floor there among them; the least material
the way it leans, more against it, and less the pocket's depth under its
floor; what
isn't yet is said; built and judged; leaned half a degree more fails; the
second kernel agrees; the generator's far face and its draws),
`tests/test_v2_spec_lean.py` and `tests/test_v2_plan_leanbody.py` (only the
far face takes anything). The exit harness's per-seed proof on 15 generated
seeds that put a cut on a leaning item's far face: all passed, and every
mutant was caught. Generator digests on seeds 0-149, old against new: only
the 6 that put one there differ, and the impossible parts whose attempts do.

**Step 5's leaning sides, as built (revision 16, with item 2b).** The four
sides of a leaning post or block, not turned and not hollowed, take a cut
square into them, blind or right through (place.md, "A leaning item's
sides"); no schema change. Each is its upright side less the band along
its foot as high as the foot rises on the side it leans towards (its half
size along its lean times its tilt's tan): above that band all of its
cross-section is clear of the face it leans on, so the side there is its
upright one leaned, as the far face is, with the box's own size across
under all of it and a cut through it coming out on the side across.
Positions are that trimmed rectangle's. **The solver** keeps each side so
(`_clear_of_foot`, then `_moved` by the leaning motion), closes one the
band covers, and says it can't put anything standing or leaning there yet;
**the judge** does the same on its own (its `_clear_of_foot`, its
`Motion`); **the planner**, the oracle and the check compiler build and
measure what is on it as on any moved face. **The generator** registers
each leaning box's sides (`_leaning_sides`), oriented as it leans, its
`leans` flag keeping them from the turned faces' stream, and cuts a hole,
a pocket or a slot into one now and then (`_onto_leaning_side`, stream
"forge-eval leaning sides", 0.5 where a part has one; a cut through the
next face there too, now and then). Tests: `tests/test_v2_plan_leanside.py`
(eleven parts placed where every program puts them, one right through the
way it leans among them; what isn't yet is said, by the judge too; built
and judged; leaned half a degree more fails; the second kernel agrees;
the generator's sides and its draws), `tests/test_v2_plan_leanbody.py`
(a leaning block's sides take things, its foot nothing) and
`tests/test_v2_plan_throughnext.py` (a hole across a leaning post through
the next face). The exit harness's per-seed proof on 66, 267, 517, 888,
914, 975, 998, 1062 and 1162 (the nine of the first 1,200 that cut into a
leaning box's side; 517's through the next face): all passed, every mutant
caught (1162's the same shape). Generator digests on seeds
0-149, old against new: only 66 differs, and the impossible parts 7 and 74,
made from generated ones.

**And a leaning boss's or cylinder's round side (revision 16).** Its side,
likewise, is its upright side less the band along its foot as high as its
foot rises on the low side, its radius times its tilt's tan: from there
all of its cross-section is clear of the face it leans on. It takes a hole
along its radius, blind or right through, one or a circle of them, placed
along its axis and at an angle round it as on the upright side so
trimmed, then leaned. **The solver** keeps it so (the side's start and
length moved past the band, its `local` the leaning motion), **the judge**
its `RoundSide` alike, and both say what can't go there yet as on a box's
sides; **the planner** builds what is cut into it upright and moves it, as
round any moved side (step 5.2). **The generator** registers it
(`_leaning_round_side`: a `_Round` whose frame is `oriented` as it leans,
its `leans` keeping it from the main draws) and drills it now and then
from the leaning sides' stream; a rounding of a leaning rod's far rim keeps
its holes clear of it, its side's far end found by its face's normal, not
its lean. Tests: `tests/test_v2_plan_leanside.py` (five more parts: a hole
round a leaning boss at 0 and 90 degrees, one right through along its
lean, one low on a leaning cylinder, a circle of them; placed where every
program puts them, built and judged, leaned half a degree more fails, the
second kernel agrees; a boss round it, a side all band and a hole into the
band said; the generator's side and its draws), `tests/test_v2_spec_lean.py`
(a leaning boss's side takes things). The exit harness's per-seed proof on
129, 184, 381, 620, 646, 650, 830, 858, 1085, 1099 and 1123 (the eleven of
the first 1,200 that drill a leaning boss's or cylinder's side): all
passed, every mutant caught. Generator digests on seeds 0-149, old against
new: only 129 differs, and the impossible parts 60, 94, 96, 98 and 124,
made from generated ones.

**1b, the ability:**

- **Item-local face names.** `+x` is the item's own +x side: a block
  turned 30 degrees about z keeps its face names, each face's frame turned
  with it. Face axes are the item's own (frame.md's table, applied in the
  item's axes).
- **Positions keyed by face axes**: `place.u` and `place.v` (the face's
  first and second axes); `x`, `y`, `z` stay as aliases on a face whose
  axes are the part's (an aligned face), and are a fault elsewhere. The 1.0
  to 2.0 migration rewrites each position to its face-axis key; the
  aliases are read on input only.
- **A typed `direction`** on what stands or cuts: `normal` (the default:
  today's), a frame axis of a named item (`{"axis": "+x", "of": "i0"}`),
  angles from the face's axes (`{"tilt": angle, "towards": "u"}`, the
  tilt from the normal towards an axis, and a turn about the normal), or a
  reference (a face's normal, an item's axis, an edge's direction). A body
  takes `orientation` (a turn about each of its axes in order, or two
  directions), the first body included.
- **What follows:** a tilted cut's mouth on its face is the section of
  its shape by the face (an ellipse for a round hole), so fits and
  footprints use the section (item 3's foot); a tilted standing item's
  base meets its host in that section too.
- **In each program:** the solver places by frames and checks fits on
  sections; the judge's placement and oracle build their solids in the
  copy's frame (the oracle's `Frame` already takes any); the check
  compiler aims its probes along the frame; the planner writes ForgeIR's
  placements from the frame (v2's rigid motions); the generator draws
  rotations and tilts (a fraction of draws, so today's distribution stays
  the bulk) and its truth computes in frames; the second kernel's view
  reads faces by frame.

### 3.4 Item 3: any analytic face hosts

**Today:** an item goes on a flat face (a rectangle, disc, ring or
outline) or on a cylinder's, tube's or bore's round side, at angles where
its direction is a frame axis; every other curved face turns it back.

**3a, the substrate:** one **placeable face** protocol in each program,
today's two kinds behind it, byte-identical:

- `frame_at(position) -> Frame`: the face's frame at a point given in its
  own coordinates (a flat face's `(u, v)`; a round side's angle and height);
- `outline`: where on the face a point may be (the face's own boundary in
  its coordinates);
- `foot(item, position) -> Shape`: the item's section carried back to the
  host, in the face's coordinates (a hole's circle on a plane; on a round
  side, its curve of contact developed onto the side), which is what fits,
  overlaps and edge distances are decided on;
- `material(position, direction)`: until 2b, today's material model.

Status of 3a: its first part is built in the solver, the judge and the
generator, byte-identical (the fingerprints of 40 sample seeds): each
program's flat face and round side give their `frame_at` a point (a flat
face's at its `(u, v)`; a round side's at its angle and the distance from
its middle, `n` out of the material, `v` its axis), every copy is placed
at its host's frame there, and the solver and the judge place through one
registry of host kinds (`_HOSTS`: how a kind's copies are placed, and what
is checked of each once numbered). Its second part moves `outline`, `foot`
and `material` behind the same protocol.

Status of 3a's second part: built in the generator (with step 5.4) and in
the solver and the judge, byte-identical (the fingerprints of 40 sample
seeds): each program's flat face answers where a footprint lies on it
(the solver's `FlatFace.holds`, `meets`, `fits_somewhere`, `in_its_hole`,
`touches_its_edge`; the judge's `FlatFace.holds`; the generator's
`_Flat.holds`) and the material under one (the solver's `material_under`,
`most_material_under` and `uniform`; the judge's `same_under`,
`material_at`, `most_under` and `least_under`; the generator's
`material_under` and `uniform`), and a round side the material a cut
along its radius meets (the solver's `SideFace.material_under`,
`most_material_under`; the judge's `RoundSide.material`). The placement,
the views, the checks, the comparison, the planner and the spec grading
ask the face. The foot is each kind's own outline in the face's axes
(`foot` in the generator; the solver's and the judge's footprints by
kind): on a flat face, where it is placed only moves it, so the face
needs nothing more; 3b's curved hosts give theirs its development on the
face.

**3b, the ability:** analytic hosts: planes in any orientation (1b), a
cone's side, a sphere, a dome, a torus (a round's face, a toroidal
fillet), a round-ended tab's end (a half cylinder), and a round side at any
angle (today only where the direction is a frame axis). On a curved host,
a position is along the face's own coordinates (angle and height on a
cone; latitude and longitude on a sphere, from a stated pole and zero
meridian), the default direction is the surface normal, and the foot is
computed exactly (a cylinder's circle on a sphere is a circle of the
sphere; on a cone or torus, an intersection curve the oracle certifies,
item 4). Freeform hosts wait for 4b.0d3.

**3b, planned (revision 14, 17 November 2026): one host at a time, the
most asked for first.** Each step is proven as 1b's were (each program's
layout, the oracle, the planner, the generator's draws, the second kernel,
the exit harness old against new) before the next starts.

1. **A standing item round a side at any angle.** A boss, a post, a tab
   or a rib round a rod, a tube or a bore, at any `place.angle`, and a
   circle of any count of them (three bosses 120 degrees apart): today
   one stands only where it faces along a frame axis, so a circle of three
   is refused. It is placed as at the frame axis at or below its angle,
   then turned with the side about its axis by the rest (the motion
   pattern of 1b's third move: its faces, its edges and what stands on
   them moved with it). No schema change: `place.angle` already takes any
   angle.
2. **A ball's or a dome's round surface.** A hole into it, a boss or a
   post on it, at a latitude and a longitude from a stated pole and zero
   meridian; the default direction the surface normal; the foot exact (a
   round item's foot on a sphere is a circle of the sphere). A schema
   minor (the surface's name, the position's fields).
3. **A cone's side.** At an angle round it and a distance along it; the
   default direction the surface normal; the foot the curve where the
   item meets the cone, certified by the oracle (item 4).
4. **A round-ended tab's end** (half a cylinder): as a round side over
   its half.
5. **A torus** (a rounded edge's face): with 4b.0d1's certified
   face-face intersections.

**3b's first step, as built (revision 14).** A boss, a post, a tab or a
rib stands round a rod's, a tube's or a bore's side at any angle, and a
circle of any count of them. At an angle that isn't a frame axis's it is
placed as at the frame axis at or below it, then turned with the side
about its axis by the rest: **the solver** gives such a copy that turn
(`_Copy.motion`) and places it on, before its host's own motion where the
side is moved (`_then`), so its faces, its edges and what is on its far
face are moved with it as a turned item's are; **the judge** turns the
copy so (`Motion.about`), a copy moved already moved on by its host's
motion, its box the upright copy's moved by both (`_moved_copy`); **the
planner** builds it upright and moves its tools (`moved_tools`, as for a
turned item), unchanged; **the generator** draws a boss or a post round a
side at any angle on a half-degree grid now and then, and now and then a
circle of three, five or six (`_angled_now_and_then`, a stream of its
own), its far face's axes turned with it; **the second kernel's
agreement** tells a tool's face lost before the tool is moved (a standing
item's foot trimmed to the side, then turned round it) on the part of the
step that lost it (`_gone_inside`; a kept plan, 24's). The guide says so
(and its version is 7: its text changed with 1b's third move and the
version didn't). Tests: `tests/test_v2_plan_roundangle.py` (placed as at
the axis below, then turned; every program's layout agrees; built and
judged: a boss at 30 degrees, a post at 200, a circle of three bosses, a
tab, a rib along the rod, a boss round a rod lying along x, a boss in a
tube's bore, a hole in its far face, its rim rounded, a post's top edges
bevelled; turned half a degree more fails; the second kernel agrees, a
kept generated part's too).

**3b's second step, as built (revision 14).** A hole, a boss or a post goes
on a ball's or a dome's curved surface (its `surface` face), at a
`place.latitude` (schema 1.6: from its equator towards its pole, the way the
ball stands; 90 degrees, its pole, where none is given) and a `place.angle`
round its pole, and a circle of them round it. It is placed as at the pole
(standing there as on a face facing that way, its length round the pole),
then turned about the ball's centre, down to its latitude and round to its
angle, with 3b's first step's turn (`_Copy.motion`): **the solver** keeps
the surface as a `BallFace` (its centre, pole, radius; a dome's or a whole
ball's, standing or not; the material a cut along its radius meets, a
dome's less towards its rim) and places through `_HOSTS`; **the judge**
keeps it as a `RoundBall`, its copies moved so (`Motion.about`), and
compares the two; **the planner** builds what stands on it from the plane
through the ball's centre, less the ball as the part has it seen from where
the item is placed before it is moved (so the foot lies on the part's own
surface once moved, and OpenCascade's seams don't meet), and a hole as round
a side; **the oracle** keeps a standing item outside the ball; **the
generator** puts holes, bosses and posts on balls' and domes' surfaces now
and then (`_onto_ball`, a stream of its own), at latitudes clear of a
dome's rim or a standing ball's equator, and circles of two to six. Its
edges are rounded and chamfered as at its pole, then turned; its joint with
the ball and a hole's mouth, curves on the ball, all along them: the
planner names the joint's edges by the faces the item has upright (which
also fixed a joint round an angled boss on a side, 3b's first step's), and
the oracle bounds both in the band round the ball's surface, as round a
side's (`round_band`, the ball's or the side's place on the part). Its
faces take nothing yet; a hole goes right through a whole ball standing on
nothing only; a hollowed ball's surface takes nothing; the check compiler
holds its place and sizes by face accounting, as a turned item's, and a
rounding in a band unmeasured, as round a side. With it, a STEP file
states its uncertainty rounded up to the six figures OpenCascade writes
(`export._stated`), so it never states the part tighter than it is
(generated part 0, 3b's first step's, wrote 3.2656402e-06 mm as
3.26564E-06). Tests:
`tests/test_v2_plan_ballsurface.py` (1.6's own; placed as at the pole, then
turned; every program's layout agrees; what isn't built yet is said; built
and judged: a boss and a post on a ball, a post on a dome, a circle of holes
round a ball's pole, a hole right through a ball, a boss at its pole, on a
ball and a dome standing on a plate, round a ball standing on the plate's
side, a boss's joint with the ball rounded, a hole's mouth bevelled, a
post's edges rounded; turned half a degree more fails; the second kernel
agrees); `tests/test_v2_plan_roundangle.py` gains a joint round an angled
boss.

**3b's third step, as built (revision 14).** A hole, a boss or a post goes
on a cone's tapered side (its `side` face, closed before), placed as round
a round side: a position along the cone's axis from its ends or its middle
and a `place.angle` round it, and a circle or an arc of them round it; no
schema change. Its direction is the side's normal, leaned from the radius
towards the narrower end by the half angle. A hole goes in along it; a boss
or a post is placed as at the frame axis at or below its angle, standing
out along the radius there, then leaned with the slope about the line
through its point round the cone, then turned about the axis by the rest
(3b's first step's turn, with the lean before it). Its foot is carried in
twice as far as the side falls away under its farthest reach where the
cone is narrowest under it. **The solver** keeps the side as a `ConeFace`
(its axis, start, length and radii at its ends, which end stands on a face;
the least material under a mouth, from points all round its rim, the cone
being convex: `exit`) and places through `_HOSTS`, saying what runs past an
end, is as wide as the cone there, is too deep, or overlaps; **the judge**
keeps it as a `RoundCone`, its copies leaned and turned so (`Motion.about`),
and compares the two; **the planner** builds what stands on it from as deep
as its foot goes, less the cone as the part has it seen from where the item
is placed before it is moved (turned about its axis a cone is itself, so
only the lean matters to the oracle's `cone_seen_upright`); **the oracle**
keeps a standing item outside that cone, and bounds a joint's or a mouth's
rounding in the band between the cones a reach out from the side and in
from it; **the generator** puts holes, bosses and posts on cones' sides now
and then (`_onto_cone`, a stream of its own), alone or in circles of two to
six, halfway along, offset or from an end. A hole into a cone's side is
blind, for now; its faces take nothing yet. With it, the oracle's sphere of
directions round a point always counts the two circles that make a corner
as through it, however nearly they run together (two faces' normals a hair
apart made a corner the cross product put just off both, and none counted:
an `IndexError`, met on a circle of holes round a cone). Tests:
`tests/test_v2_plan_coneside.py` (placed round it, square to the cone; every
program's layout agrees; what isn't built yet or doesn't fit is said; built
and judged: sixteen parts, a boss, a post, holes, a circle, an arc, on cones
standing, pointing down, lying along x, on a turned block's side, widening,
coming to a point, a joint, a rim and a mouth rounded; turned half a degree
more fails; the second kernel agrees).

**3b's fourth step, as built (revision 14).** A round-ended tab's far end
(closed before) is a round side over its half, named by the way the tab
sticks out: a hole, a boss or a post goes on it by a position along its
axis (the tab's thickness) and an angle round it, within a quarter turn of
its tip, the item's reach round it included; copies go in an arc; no schema
change. **The solver** keeps it as a `SideFace` with its `half` and how far
the tab runs on `behind` it, and says what runs off the half, a circle of
copies, or a hole deeper than the tab holds (the tab's section across its
thickness is convex: the least is along the lines through the mouth's two
sides round the axis, on through the half-disc and the straight part, until
out of its side or at its foot: `_tab_exit`); **the judge** keeps it as a
`RoundSide` with its `half` and holds a copy to it; **the planner** and
**the oracle** build what is on it as round any side (a standing item from
the plane through the axis, outside the side's cylinder); the planner's
edge queries take a mouth's or a joint's whole box on any face that isn't
flat, not only on those named as round ones (a tab's end is named `+z`);
**the generator** puts a hole, a boss or a post on a round tab's end now
and then (`_onto_end`, a stream of its own), one at a time, where nothing
rounds the tab's edges. A hole into it is blind, for now; a turned tab's end
takes nothing yet. With it, the generator's copies of holes on a ball's
surface or a cone's side keep no axes, as the judge's and the solver's keep
none (test_v2_eval_truth's three placements failed on c6a62b3). Tests:
`tests/test_v2_plan_tabend.py` (placed round its half; every program's layout
agrees; what runs off it, a circle, a hole through or too deep, a turned
tab's end are said; built and judged: a hole at its tip and at an angle, a
boss, a post, an arc of holes, a tab thick along x, one on the plate's side,
one all round end, a deep hole, a boss's joint and rim and a hole's mouth
rounded; turned half a degree more fails; the second kernel agrees).

**A ball's and a cone's seam kept clear, as built (revision 16).**
OpenCascade makes a ball about the frame's z, its surface's seam the
half-circle from pole to pole through +x, and a cone about its axis, its
side's seam the line along it at `gp_Ax2`'s first axis. Something on the
surface whose foot crosses the seam, or runs round a pole, was joined or
cut across the seam's two edges, or round the pole's point, and
OpenCascade left the part holding only loosely, by millimetres, or refused
it: all 15 of the exit pair's 5,000 parts that were unable (406, 660,
2270, 2276, 3005, 3295, 3932, 4031, 4989, 2626, 2947 across a ball's seam
or round its pole; 476, 1073, 2288 by it; 644 across a cone's). **The
planner** makes such a ball turned about its centre, or such a cone about
its axis, so that nothing on it comes within a millimetre of its seam or a
pole (`forge_plan.seams`: of some 14,400 turns of a ball, 360 of a cone;
a ball a plane cuts through its centre, a dome or one seated in its face,
with its poles well out of the plane and as little out of its way up as
keeps everything clear). The ball or cone it cuts each thing on it with is
turned alike, and
so is a hollow's inner ball (`Chain.seams`, `Chain.seamed`). Where nothing
comes so near, it is made as it always was, the same document. **The exact
view** takes a ball's face's box from its boundary and those of the ball's
six extremes on it (`_add_face`): OpenCascade's own takes the whole of its
parameters' rectangle, 4.85 mm past a turned dome's flat face, which face
accounting held as material past the spec's. **A hole on a ball's surface
or a cone's side** has its tool carried into the air past its mouth first
(5.2), as a hole into a round side has: its definition's tool's end
touches a ball at the mouth's middle, a cone along a line, and 2947's hole
was made a solid of its own. All 15 parts are built and graded clean now. Tests: `tests/test_v2_plan_ballsurface.py` (a boss
across a ball's seam, a boss and a hole by a dome's pole, built and judged,
the second kernel agreeing; turned only where something is near, and
clear), `tests/test_v2_plan_coneside.py` (a hole across a cone's seam; a
boss at 0 on it).

### 3.5 Item 2: depth by geometry

**Today:** a cut's depth is a length or `through`, and `through` means
through the most material under its mouth, which the solver computes by a
per-kind algebra (a plate's thickness, a cone's taper, a dome's height,
a turned part's profile: `geometry.py`'s depth models); the oracle and
generator compute their own.

**2a, the substrate:** an **end condition** in each program: `blind(d)`
and `through_all`, expressing today's two cases, byte-identical (today's
`through` is `through_all` as the solver's material model defines it).

Status of 2a: built, byte-identical (the fingerprints of 40 sample
seeds): `forge_spec.ends` (`Blind(depth)`, `ThroughAll`, `end_of(item)`),
through which the solver (placement, pockets' floors, holes' shapes), its
comparison and views, the judge's placement and check compiler, the
planner and the spec grading read a cut's end. The generator's own plans
keep a depth or none (through) until 2b gives them its conditions, with
the regressions' plans migrated.

**2b, the ability:** the definitions gain the end conditions as CAD means
them, feature-level: blind, through-next (the first face that covers the
whole profile), through-all, up-to-face, up-to-vertex, up-to-body,
offset-from-face, from-to, symmetric (mid-plane), with **two directions**
(each its own condition) and **start conditions** (from the host face, a
named face, a vertex, an offset). The **preview build resolves** each
before confirmation: the depth it reaches is recorded in the spec with its
condition and shown, and the person confirms the resolved value; the
**oracle and the generator verify** it on their own shapes (the condition
re-evaluated: the face reached is the first covering the profile on the
oracle's shape). The solver's material algebra is **retired**: a blind cut
that breaks through, or a through cut that doesn't come out, is found by
the preview's resolution and the oracle's check, not predicted; the
solver keeps only what it can decide on its own frames (a mouth on its
face, overlaps). What the solver turned back for material (stage 4's
impossible draws: "deeper than the material under it") is turned back by
the preview's resolution with the same question, so the exit harness's
impossible outcomes are part of 2b's proof. The 1.0 to 2.0 migration
writes each `depth` as `blind(d)` and each `through` as `through_all`,
which the proof holds oracle-equal.

**2b, planned (revision 15, 18 November 2026): the conditions each
program can decide on its own first, then those only the shape decides.**
Today's `through` goes through the material under the cut's face as the
definitions model it (frame.md): into a hollowed body's cavity, never out
of its far wall; and a blind depth is a number, which keeps no intent when
the part changes. Each step is proven as 1b's and 3b's were (each
program's layout, the oracle, the planner, the generator's draws, the
second kernel, the exit harness old against new) before the next starts.

1. **Through everything, and up to a face (schema 1.7, a minor):** a
   cut's `depth` may be `{"through_all": true}`, through all of the part
   made so far along its axis, cavities and all (a pin hole through a
   hollow housing's two walls); or `{"up_to": {"item": ..., "face": ...},
   "offset": size}`, its floor in the plane of a flat face of an item made
   before it, square to the cut, the offset back towards its mouth (a
   pocket down to a ledge's height, following it when the ledge moves).
   Each program decides both on its own: the solver, the judge, the
   planner and the generator each from their own faces and boxes, as far
   as everything made so far reaches, or to that face's plane. Today's
   `through` and a blind depth are as they are.
2. **Through the next face that covers it** (`{"through_next": true}`):
   out of the material all across its mouth for the first time, as the
   shape says. The oracle and the generator decide it on their own
   shapes; the solver's material model gives its own answer, and the
   preview build's resolution (step 3) settles a part none of them can.
3. **The preview resolves, the person confirms:** a condition the solver
   can't decide alone is built before confirmation, the depth it reaches
   recorded with its condition and shown, confirmed as any value is; the
   oracle checks it again on its own shape. The solver's material algebra
   is retired where the preview decides better.
4. **Schema 2.0:** positions along a face's own `u` and `v` only, and
   every cut's end written as its condition, the one migration proven on
   every draft Forge holds (`tests/v2_migrations.py`); start conditions
   and two directions with it.

**2b's first step, as built (revision 15, schema 1.7).** A cut square to
a flat face may go `{"through_all": true}` or `{"up_to": {"item": ...,
"face": ...}, "offset": size}` (sizes.md; frame.md: a cut depends on the
item it goes up to, which is made first). **The reader** reads them as
`Through(everything=True)` and `UpTo`, `forge_spec.ends` as
`ThroughEverything` and `UpToFace`; below 1.7 either is a fault; the wire,
the words ("right through everything behind it", "down to the plane of
...'s ... face, ... short of it") and the views say them. **The solver**
works out each copy's depth on its own (`_end_depth`, kept as
`Instance.depth`, read by `cut_depth`): through everything, to the
farthest corner behind the mouth of every body placed before it, and a
millimetre on; up to a face, to the plane of a declared flat face of an
item with one copy, parallel to the cut's, less the offset, which must
leave more than nothing (else it asks), and which is then held as a blind
depth is (it must fit in the material under the mouth, and a counterbore
must leave some of the hole below it). A leaning cut, or
one round a side, on a surface, a tab's end or a turned item's face, it
can't do yet, and says so. A body made after a cut through everything and
standing in its way would close it: asked (`_check_closed`); one made
before it is cut through. **The judge**
works out its own (`_end_depth`, from its own boxes and faces, 2 mm on);
**the check compiler** checks a cut through everything open along its axis
as far as that, and one up to a face by its floor in that plane, within
the general tolerance for the depth it comes to; **the planner** cuts each
copy to its depth. **The generator** draws them now and then (stream
"forge-eval ends", 0.35 of the holes, pockets and slots just drawn on a
flat face): one through goes through everything; a blind one up to a face
of an item with one copy behind it by at least its depth, its offset what
is left, or (0.3) through everything too. It decides both from its own
model: through everything, past the reach of its own solids made before,
every depth along it material all across its mouth and a gap round it or
air all across, coming out of material, or in again, only on a face it
keeps and that holds the mouth, which is then taken (and its way across a
hollow kept clear there), and nothing made after it that adds to the part
stands in its way (the box round its mouth along its axis; what of an item
is carried on into its face counts for nothing: the solver asks about such
a body, as test_v2_eval_truth's mutants found on 58047d1); up to a face,
its depth read from its own faces at every build, so a mutant that moves
that face moves the floor with it.
Its mutants move the offset (the depth with it) and make a cut through
everything blind; `impossible()` leaves an ended cut alone. Spec grading
counts a hole through everything as through, and one up to a face by the
depth it comes to. The guide says them (GUIDE_VERSION 11), its schema
takes them, and a question about such a depth offers "through" or a size.
Tests: `tests/test_v2_plan_throughall.py` (read and written back; below
1.7 a fault; each copy's depth as every program places it; what isn't so
is said, a body made after one through everything in its way asked
about; built and judged: through everything a hollow box's two walls,
from its side, a plate and its block, a hollow box and a boss made before
under it, a row of two, a slot, and up to a face a hole, a pocket down to
a ledge's base, a turned pocket; one wall
for everything, everything for one wall, and a floor a millimetre off
each fail; the second kernel agrees; the generator's drafts say 1.7 and
its cut through everything leaves a hollow's floor open). The exit
harness's per-seed proof on 27 generated seeds that end a cut so: all
passed, and every mutant that changes the shape was caught. Generator
digests on seeds 0-149, old against new: only the 85 that end a cut
differ, and the impossible parts whose attempts do.

**2b's second step, as built (revision 16, schema 1.8), with the third's
resolution for it.** A cut square to a flat face may go
`{"through_next": true}`: on until it is out of the part all across its
mouth for the first time, as the shape says (sizes.md, "Through the next
face"). **The preview resolves it** before confirmation
(`forge_occ.resolve`): what is made before the cut (the spec's items up to
it in the order made, its late roundings not yet) is built through the
build loop, and the cut's mouth, carried along its axis past all of it, is
taken in common with it; each solid of what is left lies across a stretch
of depths, exactly (its bounds with the axis turned to be the third), and
where the stretches that begin at the face end is where it first comes
out. Every copy must come out at the same depth; that depth is written into
the draft as the cut's `reaches` (mm, to six places), shown ("right through
the next face it comes out of (40 mm deep, as the preview found it)"), and
confirmed with the rest; the spec run finds it afresh every round, and a
spec without it can't be locked. **The solver** reads `ThroughNext` as a
through all (`ThroughNext` is one) until it is found, then the depth found
(`Instance.depth`), asks nothing of what stands on the far face (the shape
decides), and asks about a body made after it standing within a millimetre
of where it comes out (`_check_closed`); **the planner** cuts to that
depth; **the judge** finds the depth again on its own (`_next_depth`: the
oracle's shape of what is made before the cut, asked at points round the
mouth's outline and within it every 0.05 mm, then halved to 10⁻⁶ mm),
refuses a `reaches` it doesn't agree with within the general tolerance for
that depth, and cuts the oracle's to its own; **the check compiler** checks
it open as far as that. **The generator** draws it now and then (stream
"forge-eval through next", 0.3 of the holes, pockets and slots just drawn
square to a flat face and not ended so already) and decides it on its own
model: as for through everything, every depth up to where it first comes
out is material all across its mouth and a gap round it, and it comes out
on a face the generator keeps and holds it, which is then taken (out into
a hollow, what stands there after keeps 1.5 mm clear). The exit harness
and the fingerprints resolve its drafts as the spec run does. The guide
says it (GUIDE_VERSION 12); its schema takes it (and the `reaches` Forge
writes). Tests: `tests/test_v2_plan_throughnext.py` (read and written; what
is a fault; the preview finds 30, 3, 40, 20, 40 and 40 mm through a solid
box, a hollow box's top wall, a boss made before under it, a pocket from
the far side, a pocket on through a boss, a row of two; copies that come
out apart are said; the spec waits for it; a body made after it is asked
about; built and judged, the judge finding the same depth; a depth the
preview didn't find is refused, and one never found fails; the second
kernel agrees; the generator's drafts say 1.8, and its own shape stops
where it first comes out). The exit harness's per-seed proof on 20
generated seeds that cut through the next face: all passed, and every
mutant was caught. Generator digests on seeds 0-149, old against new: only
the 50 that cut so differ, and the impossible parts whose attempts do.

**2b's third step, through the next face on a curved face, as built
(revision 16; schema 1.8).** A hole goes `{"through_next": true}` from a
round side's outside, a ball's or a dome's surface, a cone's side or a
round tab's end, along its axis (sizes.md, "Through the next face"): where
plain `through` can't say how far (a dome, a ball standing on something, a
cone's side, a tab's end), the shape says, and the preview finds it before
confirmation. **The solver** lets it be cut there (`_curved_end`), each
copy as deep as the preview found (`_next_on`); through everything and up
to a face there, and anything through the next face from inside a bore,
it still says it can't. **The preview** (`forge_occ.resolve`) carries a
disc of the hole's mouth along its axis from a millimetre out (its end
then meets the curved face nowhere) through what is made before it.
**The judge** finds the depth again on the oracle's shape round the disc's
rim and within it (`_next_round`, `_comes_out`); across a face at a slant
the points round the rim find a hair less than the deepest, so where the
two agree within the general tolerance it is made as deep as the spec
records. **The planner** cuts to that depth, carried into the air past both
ends where that is proven clear. **The generator** puts a hole through the
next face on a ball or a cone now and then (stream "forge-eval through
next round", after `_onto_ball` and `_onto_cone`), how deep from its own
shape of what is made before it, asked round 720 points of the rim and
within it, the same for every copy (`_comes_out_alike`). Tests:
`tests/test_v2_plan_throughnext.py` (a rod right across, a tube's wall
into its bore, a dome out of its flat face, a ball seated in a plate and
on through it, a cone's side, one standing on a plate: the preview's
depths, built and judged; through everything on a ball and through the
next face from inside a bore said; the second kernel agrees). The exit
harness's per-seed proof on the generated seeds that cut so (31, 154,
198, 229, 291 of the first 300): all passed, and every mutant was caught.
Generator digests on seeds 0-149, old against new: only 31 differs, and
the impossible part 119, one of whose attempts does.

**And on a turned or a leaning item's face (revision 16).** A cut through
the next face goes on a turned item's face or a leaning item's far face
too: **the solver** places it upright as any cut there (`_curved_end` in
place of the flat-only rule; plain `through` on a leaning far face is
still said); **the judge** places it upright, then, moved, finds where it
comes out along its moved axis round its mouth's outline moved
(`_next_moved`, `_Layout.upright` keeping the upright placing from asking
the oracle in the wrong place); **the preview** takes the mouth along the
face's own u and v as moved (`face.frame`); **the planner** builds it
upright to that depth and moves it, as any cut there, carried on past its
far end where that is proven clear where it is moved to (`Context.placed`:
a moved cut's carrying was proven on it as it stands upright before), boxes
that overlap by less than a length's sixth place only touching. Slanting
out of a face, its end's rim touches the face where it has come out all
across its mouth, and OpenCascade leaves a shell open there; carried on, it
crosses the face cleanly (generated part 184: a hole down each of a row of
leaning bosses, out of the block's floor). **The generator**
puts a hole through the next face on a turned item's face or a leaning
item's far face now and then (the same stream, after `_onto_turned` and
`_onto_leaning`), how deep from its own shape round its rim
(`_on_flat`'s sampled way). Tests: `tests/test_v2_plan_throughnext.py` (a
hole and a pocket out through a leaning boss's or post's far face and on
through the plate, a hole down through a turned post and the plate, one
across it from its side: built and judged; the second kernel agrees; the
generator's part 0 draws one; `tests/test_v2_plan_build_generated.py`
keeps part 184). The exit harness's per-seed proof on 0, 3, 7, 67, 85,
117, 129, 149, 175, 184 and 186, which draw one: all passed, every mutant
caught.

**And through everything there (revision 16).** A cut goes through
everything (`{"through_all": true}`) from the same faces: a hole round a
rod's side, on a ball's or a dome's surface, on a cone's side, and any cut
on a turned item's face or a leaning item's far face or side (sizes.md,
"Through the next face"): on along its axis until it has passed everything
the part reaches behind its point there, each copy from its own point and
way where it is on the part. **The solver** works that out as on a flat
face, from every copy's box (`_everything_from`), once each copy is where
it is (a ball's copies are moved round it, a turned or leaning item's
face's copies moved with it, the upright copy kept as deep, `_deep`); a
body made after it whose box meets the box round all it sweeps, as wide as
its mouth every way, is asked about (`_check_closed_swept`). **The judge**
does the same on its own boxes (`_everything_at`), and finds a cut through
the next face round the side of what stands on a turned item's face where
it is moved to as well (`_next_round` after the move; upright, it waits).
**The planner** cuts to that depth, carried past both ends where that is
proven clear. **The generator** turns a hole just drawn round a side, on a
ball or on a cone, or a cut on a turned item's face or a leaning box's
side, into one through everything now and then (`_everything_now_and_then`,
stream "forge-eval through everything round", 0.3), as deep as its own
solids reach behind each copy and its own margin on (`_everything_round`
on a curved face: past where it first comes out of what it is cut into all
across, what it goes through lies all across it or not at all, and its way
is kept clear of what is made after; on a flat one as any cut through
everything, where it comes out on faces it keeps). Up to a face from there,
and anything through the next face or everything from inside a bore, is
still said. Tests: `tests/test_v2_plan_throughnext.py` (round a rod, on a
dome and a ball seated in a plate, a cone's side, out through a leaning
boss and the plate, down through a turned post and the plate: as deep as
every box reaches, every program's layout agreeing, built and judged; a
boss made after it under the plate asked about, made before it not; the
second kernel agrees; the generator's draws), and the refusals moved to
up to a face (`tests/test_v2_plan_throughall.py`). The exit harness's
per-seed proof on 0, 16, 26, 29, 31, 57, 84, 85, 106, 115, 118, 196, 209,
229 and 248 (the fifteen of the first 300 that cut so: round a side, on a
ball, on a cone, on a turned item's face): all passed, every mutant
caught; part 31 first held, a counterbore at the middle of a dome's flat
face cut where a hole through everything from its surface had gone through
it, and the generator takes such a crossing on any flat face it keeps.
Generator digests on seeds 0-149, old against new: only the eleven of
those that draw one differ, and the impossible parts 97, 104, 110, 114,
119 and 128.

**And up to a face from a turned or leaning item's face (revision 16).** A
cut goes up to a face from a turned item's face, or a leaning item's far
face or side, too (sizes.md): to that face's plane, square to the cut where
it is on the part, less the offset. **The solver** and **the judge** place
it upright as any cut there, and work out how deep, and whether the face is
square to it and behind its mouth, where it is moved to (`Layout.motion`,
`_Layout.motion`: the face's motion while it is placed upright, which their
`_end_depth` applies to its plane and its way; through everything on such a
face is found so too); so a pocket's floor there is where it ends. **The
generator** ends a blind cut just drawn on a turned item's face or a leaning
box's side up to a face behind it now and then, from the same stream as
through everything (`_everything_now_and_then`, half of those it ends:
`_BLIND_UP_TO`). From a leaning item's far face no face is square to it,
and that is said. Tests: `tests/test_v2_plan_throughnext.py` (down a turned
post to the plate's bottom and top, from a leaning post's side to the
plate's side: placed where every program puts them, built and judged; from
a leaning boss's far face said; the generator's part 66). The exit harness's per-seed proof on 66, 297
and 314 (the three of the first 400 that end so, from a turned item's
face): all passed, every mutant that makes another part caught (314's
makes the same part). Generator digests on seeds 0-149, old against new:
only 66 differs.

**And what stands on a leaning box's side (revision 16).** A leaning post's
or block's flat sides take what stands on a face too, square to it
(place.md, "A leaning item's sides"): a boss, a post, a tab or a rib,
placed on the side less the band along its foot as a cut is, upright, then
leaned with the box. **The solver** keeps it clear of the face the box
leans on: every corner of the box round it, as it stands upright and moved
with the box, is over that face's plane, or it asks whether it should be
shorter or stand higher up the side (`_clear_of_the_lean`). What leans on
such a side, and what stands round a leaning boss's or cylinder's round
side, is still said, by **the solver** and **the judge** alike. **The
generator** stands one on a leaning box's side, or on a leaning item's far
face, now and then, from the streams it cuts there with (`_onto_leaning`,
`_onto_leaning_side`: what that kind takes, while the part is not yet as
big as it is drawn to be), its corners clear of the face it leans on by
the generator's gap (`_clear_of_the_lean`). Tests:
`tests/test_v2_plan_leanside.py` (a boss on each side, across, from and
under the way it leans, and a post on a leaning block's side: where every
program puts them, built and judged, the second kernel agreeing, and a
lean half a degree more caught; a tall one reaching the plate asked
about; what leans there said; the generator's own shape, built and graded,
and one reaching down into the plate not fitting). The exit harness's
per-seed proof on 247 and 1162 (the two of the first 1,163 seeds that
stand something on a leaning item's face, both on its far face): both
passed, 247's mutant caught (1162's makes the same part). Generator
digests on seeds 0-149, old against new: only the impossible part 41
differs (its leaning block's far face drawn from the wider choice).

**And a turned item's far face over any face (revision 16; step 5.5's
second part).** A turned block's or post's far face took things only where
its turned outline lay wholly on a host with the same material under all
of it; on any other flat face (a ledge over the plate's edge, a pocket's
floor, a leaning item's far face) it was closed. Item 2b measures depth on
the shape, and the material under such a face is now as with the item
upright (frame.md): its own height and, where what is cut there is wholly
over its host's face, the host's material there too, read along the host's
axes. **The solver**'s `Over` (forge_spec.geometry) carries the face over
its host, and where the face is turned from the host's axes (the
difference of their turns), `least_material_under` and
`most_material_under` read the host's material under the footprint turned
into the host's axes, piece by piece (`_into_host`: a disc's centre turned,
a rectangle's or an outline's outline turned); `_far_material` gives a
turned item's far face its host so (`_far_over`), closing it only on a
moved face without the same material under all of it, or round a side.
**The judge**'s `Over` keeps the turn, and reads its host's material at a
point or under an outline turned so (`_on_host`, `_host_outline`); its
`_turned_far` gives the far face its host's outline turned into its own
axes. **The generator** keeps a turned box's far face on any face it
stands on (`stand_flat`): its own height and the least of its host's under
its foot. Tests: `tests/test_v2_plan_turnedover.py` (over a ledge, over the
plate and past its edge, right through; in a pocket; on a leaning post's
far face: the least under each hole, deeper asked about, every program's
layout agreeing, built and judged, the second kernel agreeing). The exit
harness's per-seed proof on 54, 110 and 115 (the three of the first 150
that now draw on such a face: a block and a tab turned on an extrusion's
end, a post turned on a revolution's): all passed, every mutant caught.
Generator digests on seeds 0-149, old against new: only those three
differ, and the impossible parts 31, 34, 44 and 124.

**And a leaning block hollowed (revision 16; step 5.5's last part).** A
shell of a leaning block was refused: its hollow as with it upright would
have run down past the face it leans on. Now it is hollowed as it stands
upright, its floor raised by as much as that face rises under the hollow's
far side along its lean (its half size along its lean less its wall there,
times tan(`tilt`)), then leaned with it (shell.md): its floor is its
thickness where it is thinnest, measured along its axis. **The solver**
(`_leaning_hollow`) and **the judge** (`_hollow` with the face's axes)
make the hollow on the raised box and lean every face with it, its far face
and its sides over their walls, its inside faces too, the material under
its inside floor its own back along its axis to the face it leans on (a
`Slant`, as its far face had; a cut right through it there is said, as
there). **The oracle** hollows it by the hollow's box as it stands upright
(its walls' half-spaces, `wall_bands`), and **the planner** makes the
hollow's box upright and leans it with the body's motion, as for a turned
block: neither needed a change. **The generator** hollows a leaning block
it has just stood on a face now and then, from the stream it hollows
standing blocks with (`Block._hollow_leaning`): its hollow upright, raised
so and leaned, its far face and sides over their walls, a cut through one
coming out inside, its inside faces as a leaning item's sides and its
floor as its far face. A leaning cylinder, and a block turned and
leaning, are still said. Tests: `tests/test_v2_plan_leanhollow.py` (open,
sealed and with a thicker floor; a hole into its floor as deep as the
material there, deeper asked about, right through said; holes through an
inside wall, a side and its sealed far face; a boss on its floor: where
every program puts them, built and judged, a lean half a degree more
caught, the second kernel agreeing; the generator's own shape, built and
graded). The exit harness's per-seed proof on 914 and 1162 (the two of
the first 1,500 seeds that hollow a leaning block: a block standing on its
inside wall and a hole in its side; holes through two of its inside walls):
both passed, every mutant caught. Generator digests on seeds 0-149, old
against new: only the impossible part 41 differs.

**And a hollow's rim (revision 16, with item 3: any face hosts).** A face
a shell leaves open was closed: nothing went on a hollow's rim, the top of
an open box's walls or of a cup's. It now keeps its rim (shell.md, "The
rim"): a cylinder's open end a ring, its outer radius the cylinder's and
its inner the hollow's; a block's open face a frame round the hollow's
mouth, `thickness` in from its edges, where the four walls round it are
there (a turned or leaning body's rim takes nothing yet). Under it is the
wall all the way down and, standing on a face, what
is under it there. **The solver** and **the judge** ask each kind for the
rim of an open face (`SolveKind.rim`, `PlaceKind.rim`) and keep it where
they closed the face: a ring as a tube's end is; a frame as a profile face
with the mouth a second outline in it, run the other way round
(`Shape.reversed`), an outline on it lying wholly on its material with no
edge of the face within it (`shape_on_face`; the judge's `Outline.within`);
the solver gives a hollowed body's far face its host's material where it is
left open (`_left_open`). **The generator** keeps a hollowed first
cylinder's open end as a ring (`_hollow_cylinder`), a cut through it coming
out on its other end where that is a face; it draws nothing on a block's
rim yet. Tests: `tests/test_v2_plan_rim.py` (on a cup's rim a blind hole,
one right through the wall and out of its foot, a circle of them, a boss; a
cylinder standing on the plate, a hole into its wall and the plate; on an
open box's rim a blind hole and one right through a wall into the plate;
deeper asked about, into the mouth said: where every program puts them,
built and judged, the second kernel agreeing; the generator's own shape,
built and graded). The exit harness's per-seed proof on 86 (the one of the
first 150 whose draw changed: a cylinder hollowed open at both ends, its
rims now faces of the part): passed, its mutant caught. Generator digests
on seeds 0-149, old against new: only 86 differs, and the impossible parts
58 and 63.

**And the generator draws on a box's rim (revision 16).** A hollowed first
block's open face, where nothing rounds its edges, stays a face of the
generator's part too: a `frame`, its mouth the hollow's (`_Flat.mouth`),
the wall under it all the way down, a cut right through coming out of its
far face where that is closed. What lies on it keeps the gap clear of its
mouth as of its outer edges (`_Flat.holds`); what is drawn there is sized
from the walls' thickness and placed at the middle of one of them. Drawn
from a stream of its own (`_onto_rim`, "forge-eval box rims", 0.5: a hole,
a pocket, a slot or what stands; not in the main loop's hosts, nor among
the decorations'), so a seed with no open box draws as it did. Tests:
`tests/test_v2_plan_rim.py` (its rim a frame; nothing reaching into its
mouth drawn; a blind hole, one right through, a boss: the generator's own
shape, built and graded). The exit harness's per-seed proof on 41, 58, 64, 107,
120 and 121 (the first 150's draws it changed: things on the rim of a box
open at its top, on a side, or at both ends; and 120, a cut up to the
plane of an open bottom's rim): each passed, its mutant caught. Generator
digests on seeds 0-149, old against new: only those differ.

**A keyway: a slot round a side (revision 16, with item 3b).** Round a
side Forge cut round holes only. A slot now goes into a rod's, a boss's or
a tube's side from outside too (slot.md, "Round a side"): along the side's
axis, its outline on the plane touching the side along the line through
its point, square to that plane to its depth from it, or right through (a
tube's wall into its bore; a solid rod across it, a slotted rod); at any
angle, a circle of them too. **The solver** sizes it round the side by its
width and along it by its length, and the material under it by its width
(into a solid rod the far side comes first along its long edges); it says
what isn't yet (one running round the side, from inside a bore, on a tab's
end or round what stands on a turned item's face, through the next face
or everything), and asks about one right through a tube's wall as wide as
its bore or wider (one wall only, or across through both: the generator
keeps it narrower). **The judge** places it the same way (`_round_slot`), and
**the oracle** makes it a prism of its outline square to that plane.
**The check compiler** holds its width between its walls, its length
between its ends, its depth to its floor from the side's fitted axis, its
angle round the side by the middle of its walls, its place along the axis
by its ends, and a circle's count by a wall of each. **The planner** makes
it upright, as at the quarter turn round the side at or below it, on the
plane touching the side there, then turns it with the side about its axis
by the rest; carried first (5.2): its definition's tool touches the side
along a line, and past its mouth, and past the far side of a solid rod,
every point of the carry is beyond a plane touching the side. **The
generator** draws one from a stream of its own (`_onto_keyway`,
"forge-eval keyways", 0.15: blind or right through, now and then a circle
of short ones), its truth a prism as the oracle's; a cut's end it may be
carried past into air is no longer taken for a wall a rod touches along a
line (`_walls_crossed`). Tests: `tests/test_v2_plan_keyway.py` (where each
goes; deeper asked about, and right through as wide as the bore; every
program's layout agrees; round or square
ended, at 30 degrees, a circle of four, right through a tube's wall and a
solid rod: built and judged, every check held; one 0.5 mm shallower or
turned 5 degrees caught; the second kernel agreeing; what isn't yet said;
the generator's own shape, built and graded). The exit harness's per-seed
proof on the 18 of the first 150 whose draws changed (11, 21, 24, 26, 67,
68, 77, 78, 82, 84, 86, 88, 94, 95, 106, 140, 144, 147: keyways in rods,
tubes and bosses, blind, right through, a circle of them) and on 2356
drawn again: each passed, its mutant caught (67's and 77's made the same
shape). Generator digests on seeds 0-149, old against new: those 18
differ, and 17 impossible parts.

**A hexagonal pocket: a nut trap (revision 16, schema 1.9).** A pocket was
a rectangle or a circle. It may now be a regular hexagon (pocket.md):
`"shape": "hexagon"`, `across_flats` between each two opposite sides, two
of its corners on the face's first axis; placed by its centre or its edge
(a corner along the first axis, a flat along the second), turned in the
face by `place.turn` as a rectangle is, in a pattern as any pocket; its
floor a face of its own, the hexagon. A choice's option may now arrive in a
later minor version (`FieldSpec.since`): below 1.9 a hexagon is a fault.
**The solver** places it by its own outline (`SolveKind.shape`, which
`turned_outline` turns where it is turned): fitted to its face, held apart,
its depth held, its floor a profile face, as a turned rectangle is; its
parts are the box round it. **The judge** makes it an outline of six
straight sides, **the oracle** a convex polygon's prism. **The check
compiler** holds its size across its flats between each of its three pairs
of opposite sides, its place along its second axis by the middle of its
two flats there and along its first by the middle of its two corners
there, each where two fitted walls meet (a new reference,
`kinds.position.Corner`: the point both planes' fitted places give, along a
way in the plane of their normals), a pattern's count by a flat of each;
turned, its place is held by the face accounting, as any turned item's.
**The planner** draws its outline as a profile of lines (as a turned
rectangle's). **The comparison** reads it as a hexagonal cut, its box and
its size across its flats. **The generator** cuts one into a flat face now
and then from a stream of its own (`_onto_nut_trap`, "forge-eval nut
traps", 0.04 at each item: blind or right through, a pattern of them, turned
now and then), keeping clear by the box round it (`DrawKind.corners`), its
truth its outline pushed (`Pushed`), its side checked built, its rims
rounded or bevelled along each side, its sharp corners zones, a rod
touching one of its walls along a line refused as a box's is; its draft
says 1.9. Tests: `tests/test_v2_plan_hexagon.py` (its outline, placed by a
corner and a flat; off its face asked; below 1.9 a fault; every program's
layout agrees; blind, turned, right through, a row, near two edges, its
rim rounded or bevelled, its floor's edge rounded: built and judged, every
check held; one moved 0.3 mm either way, turned 5 degrees or 0.2 mm
smaller caught; the second kernel agreeing; the words, the views and the
comparison; the generator's own shape, built and graded). Generator
digests on seeds 0-149, old against new: 23 drawn otherwise, 25 impossible
parts.

**And a pocket of its own outline (revision 16, schema 1.9).** A pocket may
also be `"shape": "profile"`, its `profile` an outline of lines and arcs as
an extrusion's (pocket.md): along the face's axes from the point `place`
puts it at, which may lie off it (a D-shaped hole for a shaft's flat, a
window of any outline); placed, turned and patterned as the hexagon is, by
its own outline (`SolveKind.shape`), its floor a profile face about the
middle of the box round it, turned with it. **The judge** reads its
outline as an extrusion's (`section_of`), its floor centred where that box
is (and, turned, where its own box is turned to). **The oracle** makes it
its convex pieces, each pushed from its mouth to its depth, and its bulges,
as an extrusion's outline is made. **The check compiler** holds its depth
(to its floor over the box round its outline, or right through, open round
a point well within it); its outline and its place, as an extrusion's are,
by face accounting; a pattern's count by a wall of each. Its edges aren't
rounded or bevelled yet: said ("unable"). **The generator** cuts one now and
then from a stream of its own (`_onto_outlined_pocket`, "forge-eval outlined
pockets", 0.03 at each item: an L, a T, a stadium or a plate's corner, sized
from the face, blind or right through, now and then a pattern of them), its
truth its outline pushed, its side checked built (points past it, round its
arcs too), its straight walls kept from a rod touching them along a line.
Tests: `tests/test_v2_plan_outlined.py`.

**And a hole through the next face from a turned item's face keeps its way
(revision 16).** The exit pair on 77fa304 found generated part 2356: a hole
through the next face from the side of a tab turned 120 degrees, and a
revolution standing after it on the body's end, which the solver found in
its way (behind its mouth within its depth, and over it along the face's
axes, by its box) and asked about. The generator kept a way for such a cut
only from a face of the part's axes; it now keeps one from a turned item's
face too, as the solver reads it (`_Part.turned_ways`). Kept in
`REFUSED`. **And the judge's own depth through the next face from a curved
face** (`_next_round`, where the spec has none yet: the reference parts'
test) asked 16 points round the hole's rim; out of a face at a slant the
point out last lies between two of them, and on generated part 4599 (a
dome's flat face, 16.5 degrees off square) it came 4 micrometres short,
its mouth 13 off where the part leaves the face, past the accounting's
tolerance. It asks 128 now.

**And a pattern's insets on such a side (revision 16).** The exit pair on
53f3a9f found generated part 1911: four holes at the corners of a post's
flat side, the post standing round a tube. The check compiler measured
their inset from the side's edge where it meets the post's foot, which runs
on down to where the foot follows the tube's curve: no edge of the side's
own there, and no built face where the check looked. A corners or ends
pattern's inset from that edge is now held by face accounting, as a
position from it already was (`_foot_edge`). Kept in `REGRESSIONS`.

**And what the exit pair on 6229409 found (revision 16).** Of 4,999
generated parts, 47 new ones failed, each of them with a hexagon or a
pocket of its own outline in it, every one the generator's own model of
the part or the solver's reading, never what was built or judged. A
turned hexagon placed by its edge: the generator measured it by the box
round its rectangle turned, the solver by the hexagon turned (43 of them);
the generator now turns the hexagon's own corners (`_turned_half`). A
pocket of its own outline: what it covers was taken about its point in the
generator's checks of the dome over it, where it comes out and what it
leaves (generated parts 2451, 3295); the generator now draws such an
outline about the middle of the box round it, so it covers its footprint
about its point as every other cut does, and those checks take what a copy
covers. A leaning counterbored hole's way out (2345): the generator kept
what stands on the far face clear of its bore, the solver of its widest
circle, as place.md has it; the generator now keeps it clear of that too.
And the solver read the foot of an extrusion or a revolution standing
beside a pocket of its own outline as nothing, wholly within it, and asked
whether it was held up (2279); a profiled item's foot is now its outline
there.

**And the flat sides of what stands round a side (revision 16, with item
3b).** What stood round a rod's side took things only on its far face. Its
flat sides now do too (place.md, "On a round side"): its box's, from its
point out, as its height is measured, so they lie wholly clear of the side
where its foot follows the curve below them; each has its size across it
under it, a cut right through coming out on the side across (a lug's cross
hole). **The solver** (`_round_footed`) and **the judge** close only its
other faces (a boss's round side). **The generator** keeps a post's flat
sides round a rod (`_Flat.footed`), oriented as it is turned, and cuts
square into one now and then from a stream of its own
(`_onto_footed_side`, "forge-eval footed sides", 0.5: blind or right
through, not yet through the next face or everything, which OpenCascade
didn't cut cleanly in its first draws). Tests:
`tests/test_v2_plan_roundsides.py` (holes across a post and along the rod
through it, at 0, 30 and 200 degrees, blind and right through, one through
a tab's broad face: where every program puts them, built and judged, the
second kernel agreeing; a boss's round side said; the generator's own
shape, built and graded). The exit harness's per-seed proof on 25, 72 and
77 (the first 150's draws it changed): each passed, its mutant caught (77
first graded wrong: the generator had a side's up axis signed the wrong
way, fixed). Generator digests on seeds 0-149, old against new: 25, 72
and 77 differ, and the impossible parts 13, 14, 19, 20, 33, 57 and 122.

**What the exit pair on 5e162e1 found, fixed (revision 16).** The exit
pair on 5e162e1 against main at 25418c6 (5,000 seeds) found about twenty
parts held, graded wrong, unable or in error on both sides alike: brought
in with 2b's third step and the seams (b_uv23, b_uv24), whose own exit
pairs had been cancelled for later ones. Three kinds fixed here. **A blind
hole into a narrow cone's side** (658, 948, 1549, 2446, 3935, 4460, 4524):
its depth was checked between the plane at its mouth and its floor, and
round a cone a few millimetres across the side falls away from that plane
too fast for the part to show it there; **the check compiler** now
measures the floor from the cone's fitted axis where the hole's own axis
meets it (`_floor`: the hole runs square to the side, in the plane through
the cone's axis), less how far its mouth is from there, as round a rod's
side. **A hole through the next face of a ball coming out of a dome's flat
face** (816, 1202, 4163): **the generator** didn't take the face where it
came out, so a boss stood there after, and its foot's carry into the dome
filled the hole's end in its own shape and not in the built one; it now
takes every flat face such a hole crosses, as one through everything did
(`_taken_where_it_crosses`). **One coming out at a glancing slant** (2372:
out of a dome's flat face 80 degrees from square, the preview and the
judge 0.3 mm apart, a twentieth of a millimetre of where the face is made
amplified six times): **the generator** draws one only where a mouth a
tenth of a millimetre wider is out all across within a quarter of a
millimetre more. **One through the next face of a ball standing on a
face, going on into what it stands on or past it into another item**
(2157, 2515, 3614, 4059, 4237, 4398: OpenCascade left a shell open, or the
faces built weren't the spec's, where it came out at a joint or a corner):
**the generator** draws one only where it comes out of the ball itself,
into the air beyond it. Each part, drawn again, passes the exit harness
with its mutant caught (2442 and 154 too, drawn again by these). **Two
holes OpenCascade refused every way** (4599, a hole through the next face
of a dome, out of its flat face at its middle; 2231, one from the far face
of a post standing round a rod's side, out into another hole's bore): its
subtract warned of each, flush and carried alike, where a tenth of a
millimetre's offset or half a degree's latitude built: where the tools'
seams fell. **The planner** now offers a hole one more construction, last
(V2-stage4.md, 5.7): its definition's with each cylinder and cone turned a
quarter turn about its own axis, the same points; both build so (2231
with the hole it comes out into made by its definition), graded clean,
kept as regressions (and, with what follows, carried past their
ends, they build first). **And a hole's end touching a face at a
point** (4944: through the next face from a cone's side, out of a
flange's underside 42 degrees from square): with no air past its end
shown by the boxes it wasn't carried there, and at the exact depth (the
preview's, which the underside's plane gives to a tenth of a micrometre)
OpenCascade left a face across the hole's end without a flag, however it
was made (the judge's face accounting and topology held it; the
generator's own shape, its rim asked every half degree, stops 7
micrometres short and built). **The preview** now asks for 0.1 mm of air
past where a cut through the next face first comes out, under all its
mouth, or finds no depth; **the planner** carries such a cut's far end
into it on that showing, carried first (V2-stage4.md, 5.2); **the
generator** draws one only where its own shape has that air. Kept as a
regression; it builds, graded clean.

**What the exit pairs found, fixed (revision 16).** The exit pair on main
with the fp fix (lean-1b2 against it, 5,000 seeds) passed 4,975 of its new
parts; 2b's first step's pair against that main kept those and held two
more. Each is fixed where it was, and the plans that build quickly kept
(`tests/v2_regressions.py`):

- **A leaning item's roundings, in the truth** (3640, 1038, 3551, 1340,
  3950; graded wrong). Each long edge's round began square to the lean
  where the edge meets the face, not at the face's plane, keeping a sliver
  of the corner on one side and taking the face's material on the other; a
  far rim that dips into the face was rounded under it too. The built
  rounds run down to the plane and stop there, as edges.md says. The truth
  now keeps each such round on the face's open side (`Kept`, which holds a
  rounding as it holds the leaning item; the exact and mesh models carry a
  kept rounding's own ends, and trim a rounded loop at the plane), and the
  generator draws no long edge that rises less than twice its round and
  the gap from the face (3344's stayed in the face, and the generator
  failed on it).
- **A leaning box's long edges, in the planner** (596; an error). The
  planner offered to round them early on the box's tool, or as the regions
  round its box; neither is made for a leaning item, and its tool refused
  early with a PlanError. Neither is offered now: they are rounded on the
  part.
- **A side pressed against what is past its face's edge, in the
  generator** (2274; graded wrong). A block on a standing block's side,
  flush with that block's foot, lay against the drum the block stood on; a
  slot cut into that side hid in the part, and its mouth, carried on into
  what the truth took for air, cut the drum in the exact model. Such a side
  is no face of the part now, nor the face it lies against there
  (`_pressed_sides`), as inside a hollow it already wasn't.
- **Letters whose ink lies off their point, in the solver** (2361; an
  error). Asked whether an outline fits anywhere on a face, the solver
  measured it from its point both ways: a cedilla and a stop, their ink
  all below the middle of their line's box, were taken as twice as tall
  as they are. It is measured with its box centred now (`centred`).
- **A cut through everything past a thin wall, in the judge** (127, 4217;
  held). A cut's side is looked for from a margin as wide as its band past
  its mouth; through everything from a floor a millimetre thick, that is
  past the floor, where the cut runs through the hollow and has no side.
  Where a cut's end doesn't follow the material under its face (through
  everything, up to a face), its side is measured as far as that material
  surely goes (`Copy.wall`, the least under its mouth).

The rest were OpenCascade refusing every way to make a part (15, "unable",
the same in both): a ball's or a cone's seam (3.4, "A ball's and a cone's
seam kept clear"); and one mutant it wouldn't build (2629). Tests: `tests/test_v2_plan_build_generated.py` (the
kept plans built, judged and graded), `tests/test_v2_eval_truth.py` (the
refused plans refused), `tests/test_v2_plan_turnedges.py` (only on the
part), `tests/test_v2_plan_throughall.py` (a ring of round pockets through
a floor 1 mm thick and on past a boss beside them).

**What the next exit pair found, fixed (revision 16).** The exit pair on
those fixes (09a3be0 against main, 5,000 seeds) passed 4,981; the 15
OpenCascade refused were the seams above, and three more were the
generator's, each a part Forge rightly wouldn't make as drawn. Each is
refused now (`tests/v2_regressions.py`'s `REFUSED`):

- **A leaning item's foot across a cut's way** (2009; an error). A post
  leaning 48.5 degrees under a block's floor, made after a hole through the
  next face, has its foot carried back into the block across the hole's
  way; the generator measured the post as it stands out of its face, and
  the solver asked whether the post should be cut through too. A leaning
  copy's way is all of its box now, its foot back into the face too
  (`_out_of_its_face`).
- **Copies coming out at different depths** (3633; held). Round pockets
  through the next face at the corners of a hollow box's side: two over
  its thick end came out of its far side, two over its hollow into it. The
  preview records one depth for every copy and says so where they differ;
  the generator asks the same now (`_Part.outs`).
- **Out where something stands** (3877; graded wrong). A slot through the
  next face came out of an extrusion's end under a corner of a turned rib,
  which the points the generator asks along it missed: the shape says it
  comes out of the rib's top. Nothing a cut through everything or through
  the next face comes out through may stand on, or be cut into, the face
  there now (`_through_everything`).

**A hollow cone (revision 17).** Blind set 1 (V2-stage4.md, 14.6) refused
a cup wider at its rim: Forge hollowed blocks, cylinders and balls only. A
shell now hollows a cone with a flat top (shell.md, "cone"): its hollow a
cone of its own, its side wall `thickness` square to its side, so the
hollow's radius at a height is the cone's less the thickness times the
side's slant over its length; its ends' walls in from its ends, none where
open, `floor` opposite an opening. **The solver** (`Cone.hollow`) and
**the judge** keep its ends' walls under its end faces, close its side and
an open end's rim to what would stand there (they take nothing yet), and
refuse a rounding or a chamfer of its edges and a cone that comes to a
point (face accounting can't yet tell either side of the point its hollow
would come to; a solid cone's point it can). **The oracle** takes the
hollow as the body less its bands: outside the hollow's cone, run on a
millimetre past each open end, and past each closed end's wall. **The
planner** cuts a cone of its own and names its inside faces. **The check
compiler** measures its length from an open end's plane, and its side wall
square to its side (`wall._cones`: each built point's distance in from the
outside's fitted cone along its slant, then as a round wall), through a
hook a hollowed body answers (`CompileKind.hollow_side`). Tests:
`tests/test_v2_plan_hollow_cone.py` (a cup wider or narrower at its rim,
a funnel, sealed, upside down; every program's layout agreeing; each built,
every face accounted for and every check passing, its volume within the
oracle's; eight drawn at random; walls 0.3 mm thicker or thinner and a floor
0.3 mm off caught by face accounting and by their own checks; the second
kernel agreeing). Sixty more drawn at random, outside the suite: each built
and judged so.

**Hollow walls (revision 18).** Drawing hollowed cones at random found
what the hand-drawn tests hadn't. The solver kept a hollowed cone's closed
end's material the solid cone's (its length, falling off past its smaller
end's radius), so a blind hole 10 mm deep in a cup's 3 mm floor was
accepted and built as a hole into the cup; it now keeps the wall
(`cone.walled`: the wall's thickness, and the cone's own where that is
less, near its larger end's rim), and a hollowed dome's floor no more than
the dome over it near its rim (`Dome.cap`). And a cut right through a
hollowed body's wall whose mouth ran past the hollow's edge (a drain hole
half under a planter's side wall, a hole in a tray's side half beside its
floor, a hole round a hollowed cylinder's side beside its floor) was built
through the wall's thickness and passed: there it ended in the wall. It is
now asked about (`placement._check_into_hollows`, frame.md): on a block's
face, a cylinder's end or side, a cone's end, a dome's floor, each against
the hollow's section behind the wall (`Layout.insides` for a cone's and a
dome's, whose inside takes nothing yet). And one that comes out on the
wall's other face under what stands there (a drain hole under a boss on a
pot's inside floor, or from inside under a foot below) is asked about as
through a solid plate under a boss (`_check_exits`): it was built ending in
what stood there. **The generator** draws a cone as
the first body (one seed in twenty: narrower or wider at its top, or to a
point; its ends take what an end takes, its side what a cone's side takes),
hollowed half the time where its top is flat (open at an end, both or
none), a cut right through a closed end coming out on the hollow's section
there, which takes nothing else; and a hollowed dome's floor no more than
the dome near its rim. Tests: `tests/test_v2_spec_hollow_walls.py`.

### 3.6 The proof, and what each step costs

| Step | Proof | Runner time |
|---|---|---|
| 14 | migrations of every held draft oracle-equal; the suite | under an hour |
| 1a (per program), 3a, 2a | 3a and 2a: fingerprints byte-identical (sample, two hash seeds); 1a: every value within a few ulps (`v2_values.py`); regressions, suite | about an hour each |
| 1b, 3b, 2b | exit pair on 10,000 seeds (same endings, classes, every change listed), corpus migrated oracle-equal, new tests with mutants and near-misses, generator draws | about 6 hours each |

Each step is committed to a branch, proven there, and merged to `main`
(and the laptop) only when its proof passes.
