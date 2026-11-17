# Forge V2, stage 4b.0c: geometry, on the same numbers everywhere

Status (17 November 2026): items 0, 14, 1a, 2a and 3a's first part done;
1b's first and second moves done (items turned in their face, schema 1.2;
holes, bosses and posts leaning on it, schema 1.3); its third move's first
step done (positions along a face's own axes and a turned item's far face,
schema 1.4), its second (a turned box's sides) and 2c (a turned item's
edges, rounded), neither a schema minor, and its third (a body leans,
schema 1.5); schema 2.0 next, a leaning item's faces after item 2b. Companion to [V2-stage4b.md](V2-stage4b.md),
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

### 3.6 The proof, and what each step costs

| Step | Proof | Runner time |
|---|---|---|
| 14 | migrations of every held draft oracle-equal; the suite | under an hour |
| 1a (per program), 3a, 2a | 3a and 2a: fingerprints byte-identical (sample, two hash seeds); 1a: every value within a few ulps (`v2_values.py`); regressions, suite | about an hour each |
| 1b, 3b, 2b | exit pair on 10,000 seeds (same endings, classes, every change listed), corpus migrated oracle-equal, new tests with mutants and near-misses, generator draws | about 6 hours each |

Each step is committed to a branch, proven there, and merged to `main`
(and the laptop) only when its proof passes.
