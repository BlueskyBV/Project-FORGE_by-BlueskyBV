# Forge V2, stage 4b.0c: geometry, on the same numbers everywhere

Status: item 0 built and in its proof (16 November 2026); items 1 to 3
and 14 to be designed here next. Companion to [V2-stage4b.md](V2-stage4b.md),
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
   measured (the fingerprint: about 3% more time, from the per-call
   overhead of a Python wrapper; 4b.0d1's compiled core removes it).

Before the call sites moved, the generator was compared by value on 60
seeds: the same parts, every float within 2.3e-16 of the old one.

### 2.4 Status

| Step | State |
|---|---|
| forge_numeric, its tests and its compiled twin | done (`acf5a9f`, `aed942e`); golden digests reproduced on all four platforms (trust-core run 43880625574), each platform's library equal to the NumPy twin (native run 43880625544) |
| The call sites and the rule | on `numeric/adopt` (`68819ff`), in proof |
| The proof (2.3, 2 to 4) | running |

## 3. Items 1 to 3 and 14: how they are made, in what order

Status: design, revision 1, 16 November 2026, for review before any of it
is built.

### 3.1 The principle: refactor first, then the new ability

Each item changes what every independent program computes (the solver's
placement, the judge's placement and oracle, the check compiler, the
planner and compiler, the generator, the second kernel's capability
table), each its own way, as R2 requires. Each is made in **two moves**:

- **(a) the substrate, byte-identical.** The program's representation
  becomes the general one (a frame of vectors, a host protocol, an end
  condition), carrying exactly today's cases. Proven as 4b.0b was: every
  seed's fingerprint (everything a verdict consumes) byte-identical on the
  sample under two hash seeds, the regressions, the suite. No semantics
  move, so a fault is a refactoring fault, found at once.
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

**Made:**

- `schema_version` ("major.minor") replaces `spec_format` in what Forge
  writes (`to_wire`, the guide's schema, the generator's and the tests'
  drafts). A draft that says `"spec_format": 1` is version 1.0, read and
  migrated; one that says neither is refused, as today.
- **A confirmed spec stays confirmed.** `unlock` checks a lock's hash on
  the spec's wire form **at the version it was confirmed in** (each
  version's `to_wire` kept, as its migrations are), then migrates it; a
  lock is never re-hashed silently. A migrated spec whose shown content
  differs is confirmed again (ADR-0026's re-confirmation rule).
- `forge_spec/migrations/`: one module per major step, each a pure
  function from a draft's JSON at one version to the next, kept forever,
  registered in order; `migrate(raw) -> (raw, steps)`. A minor version only
  adds optional fields and needs none.
- The proof of a migration, `tests/v2_migrations.py`: every draft Forge
  holds (the corpus drafts `v2_corpus`, `v2_suite_specs`, the stage tests'
  drafts, the regressions' and 10,000 generated ones) is migrated, and the
  migrated draft on the new code is held against the old draft on the old
  code (a pair run, as `exitpair`): the same items, the same solved
  layout, the same oracle (the judge's shape, the fingerprint's `judge`
  section) and the same check suite, to the last bit where the step is a
  substrate (a) and to the same endings where it is an ability (b). A
  migration that changes a verdict without changing geometry lists each
  changed verdict.
- The hash: the confirmed spec's hash covers its `schema_version` (item
  27's other inputs land with their items).
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
(origin, and unit vectors `u`, `v`, `n`, right-handed: `n` the outward
normal, `u` and `v` the face's first and second axes), and each copy its
own frame (its item's axes in the world). The axis-name tables become one
function per program that makes the frame for a named face of an aligned
item. An aligned frame is applied by choosing a component and its sign,
never by a product with 0 or 1 (a product would turn 0.0 into -0.0, which
a digest sees), so the bits can't move and byte identity proves the
refactor; a general rotation is applied only to a frame that isn't
aligned. Each program keeps its own `Frame` (R2: the solver's in
`forge_spec`, the judge's in `forge_checks`, the generator's in
`forge_eval`), each built from the definitions, not from another's.

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
| 1a, 3a, 2a | fingerprints byte-identical (sample, two hash seeds), regressions, suite | about an hour each |
| 1b, 3b, 2b | exit pair on 10,000 seeds (same endings, classes, every change listed), corpus migrated oracle-equal, new tests with mutants and near-misses, generator draws | about 6 hours each |

Each step is committed to a branch, proven there, and merged to `main`
(and the laptop) only when its proof passes.
