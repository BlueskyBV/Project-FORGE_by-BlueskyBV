# Forge V2, stage 2: the checks and the oracle

Status: built, revision 3, 23 October 2026: all eight steps of section 11
are done, and the exit test passes (8.3). Revision 2 followed an
adversarial review of revision 1; sections 3 to 10 say what was built
where it differs from what was planned ("as built").
Companion to [V2-plan.md](V2-plan.md) (sections 4.5, 4.6, 8) and
[V2-architecture.md](V2-architecture.md) (sections 4.2, 4.3, 6). Where this
page is more exact than those, this page holds; where it differs, it says
why.

---

## 1. What stage 2 delivers

The plan's row for stage 2:

> `GeometryView`; check kinds with mutants and near-misses; relation checks;
> face accounting; topology counts; verification classes; capability table;
> the NumPy mesh view; hand-made reference parts; the written field
> definitions; the random-spec generator with its own shape model.
>
> **Exit test:** every mutant beyond tolerance rejected, every near-miss
> passed, for every check kind. R1 and R2 tests pass.

The written field definitions are done ([definitions/](definitions/README.md))
and wait for your approval. Everything else is below.

Stage 2 builds the judge before anything it judges exists. There is no
compiler yet (stage 4) and no exact kernel (stage 3), so the checks are
proved on **reference parts**: meshes made with a mesh library the tests
alone use, by hand and from random specs, and damaged on purpose. When the
exact kernel arrives, its `BrepView` answers the same interface and the
same tests run on it.

### 1.1 What the review changed

Revision 1 was reviewed adversarially. Its findings, and what this revision
does about each:

| Finding | This revision |
|---|---|
| The sign test along a sample's normal fails correct faceted parts (a spec point on a hole's floor, between the true rim and the facets) | It is only the first, cheap try; a sample that fails it is passed only by a **witness** (5.3) |
| Random sampling can miss a 0.5 mm pin or a 0.2 mm chamfer | **Deterministic coverage** with a stated guarantee (5.4) |
| Roundings and threads as "bounded" let a wrong radius, no rounding at all, or a plain rod for a thread pass | Modelled **exactly** wherever the definitions say they are known; bounded only in stated zones, with tight limits (5.2) |
| The measurement uncertainty `u` was undefined; a fit on facets is biased, and on a short arc wildly so | A **worst-case** bound; interval verdicts; the check compiler sets how fine the export must be (6) |
| The oracle copying the solver's coordinates shares the solver's mistakes | The oracle **places every item itself** from the definitions; any difference from the solver's layout holds the part (5.1) |
| Winding numbers with a cell-centre dipole misclassify CAD meshes | Closest-feature signs near the surface, ray parity away from it (4.3) |
| The exit test's mutants were hand-picked and far from the tolerance | **Generated, bracketed** mutants and near-misses, mesh-integrity and transform mutants, correlated-fault mutants, random reference parts, a detection matrix and a false-hold rate (8) |
| R1 at the level of top fields; R2 by top-level package names only | R1 over **leaf** fields and choices, each with a rejecting mutant; R2 by dotted module and symbol, with a view proxy (9) |
| Sealed voids "unless a cut opens it" miscounts | Counted **geometrically**, or listed as unchecked (5.6) |
| A shelled tray with rounded corners has 0.76 mm corner walls by the definitions | The definitions now round a hollowed body's own edges **before** it is hollowed, so its walls follow them ([frame.md](definitions/frame.md), [shell.md](definitions/shell.md)) |

## 2. Where it sits

```
ConfirmedSpec ─┬─► forge_checks.place ─► Placed (the definitions' own layout) ─┐
 (spec+layout) │          └── compared with the solver's layout: any difference holds
               ├─► forge_checks.oracle ─► Oracle ──────────────────────────────┤
               └─► forge_checks.compile_checks ─► CheckSuite ──────────────────┤
built part ────► a GeometryView (mesh, B-rep, implicit), behind a proxy ───────┴─► Evidence
```

- **In:** a confirmed spec (`PartSpec`, the brief, and the solver's
  `Layout`). Until a run confirms one, tests use a checked draft's
  `SpecReport` the same way.
- **Out:** evidence for every check on every view that can answer it:
  PASS, FAIL or INCONCLUSIVE, with the numbers. INCONCLUSIVE holds the part.
- **Never in:** the construction (ForgeIR), the compiler, a kernel's build
  history, a model, or the solver's coordinates. The checks see the part only
  through a `GeometryView`, and the spec only through its fields (rule R2).

## 3. The packages

All of `forge_checks` is in the trust core (L0): the standard library and
NumPy only.

| Module | What it holds |
|---|---|
| `view.py` | `GeometryView`, its types, and the proxy every view is seen through |
| `readers.py` | STL (binary and text) and 3MF: units, build items, components, object types |
| `mesh.py` | `Mesh` and `MeshView`: welding, topology, closest points, classification, crossings, volume, coverage |
| `predicates.py` | orientation signs, exactly: floating point where it is sure, integers where it isn't |
| `triangles.py` | a point's nearest point on a triangle, and the watertight ray test |
| `tree.py` | the box tree every search through a mesh walks |
| `intersect.py` | whether two triangles meet anywhere but where they are joined |
| `outlines.py` | outlines in a face's plane (rectangles with rounded corners, discs, rings): membership, signed distance, the nearest point of an overlap, the farthest point, lying within |
| `capabilities.py` | the capability table: the questions each kind of view must answer, and how it holds each item kind (exact, bounded, not applicable) |
| `classes.py` | verification classes and the tolerance policy |
| `place.py` | where the definitions put every item: faces, positions, patterns, copies, the material under each face |
| `shapes.py` | exact solids and surfaces: planes, boxes, cylinders, cones, balls, tori, prisms of outlines, helicoid threads; signed distances, closest points, normals |
| `oracle.py` | the spec's shape: the items in the make order, cut, hollowed, rounded, threaded; classification; coverage of its surfaces; expected topology; the unchecked list |
| `accounting.py` | face accounting both ways, with witnesses; deflection measured |
| `topology.py` | built topology against expected |
| `kinds/` | one file per check kind: measurement, tolerance policy, mutants, near-misses |
| ~~`relations.py`~~ | relation checks are the compiler's place checks (5.8): each stated place measured on the built part, between built things |
| `probes.py` | fresh probes, drawn after the build from a recorded seed (8.2) |
| `compiler.py` | `compile_checks`: every leaf field of every item gives a check or an explicit unchecked |

| In `forge_eval` | |
|---|---|
| `truth.py` | the generator's own shape model, from the definitions: a third placement and classifier |
| `generator.py` | random specs, interacting and impossible on purpose, with their truth; a mutant per leaf |

## 4. The interfaces

### 4.1 `GeometryView`

```python
class Side(IntEnum):            # what a view says of a point
    OUT = -1; ON = 0; IN = 1; UNKNOWN = 2

class Capability(Enum):
    CLASSIFY; CROSSINGS; DISTANCE; VOLUME; COVERAGE; TOPOLOGY; FACES; EDGES

@dataclass(frozen=True)
class Coverage:                 # points standing for the whole surface, none left out
    points: NDArray             # (n, 3)
    normals: NDArray            # (n, 3), outward, unit
    patch: NDArray              # (n,), the face or triangle each is on
    tolerance: NDArray          # (n,), how far the view's surface may be from the true one there, mm
    radius: float               # every point of the surface is within this of a point

@dataclass(frozen=True)
class Crossings:                # ahead of each ray's origin, ordered by ray, then distance
    ray: NDArray; t: NDArray; entering: NDArray
    grazed: NDArray             # per ray: it passed exactly through an edge or a corner

@dataclass(frozen=True)
class Topology:
    shells: int
    solids: int | None; voids: int | None; misnested: int | None   # on an otherwise sound surface
    open_edges: int; bad_edges: int; bad_vertices: int; bad_triangles: int
    self_intersections: int
    genus: tuple[int, ...]      # per solid: its through-holes, largest solid first

@dataclass(frozen=True)
class FaceFacts:                # geometry only: nothing about how the face was made
    kind: str                   # "plane", "cylinder", "cone", "sphere", "torus", "other"
    surface: tuple[float, ...]  # its surface's parameters, so faces on one surface can be merged
    area: float
    bounds: Box

class GeometryView(Protocol):
    source: str                 # "mesh-file", "brep", "step-file", "implicit"
    capabilities: frozenset[Capability]
    def classify(self, points) -> NDArray[int8]                   # Side, per point
    def distance(self, points) -> NDArray                         # exact distance to its surface
    def crossings(self, origins, directions) -> Crossings
    def volume(self) -> Interval
    def bounds(self) -> Box
    def coverage(self, radius: float, within: Box | None = None) -> Coverage  # every face or triangle reached (or those meeting a box)
    def topology(self) -> Topology
    def faces(self) -> Sequence[FaceFacts]                        # exact views only
    def edges(self) -> Sequence[EdgeFacts]
```

- A view that lacks a capability raises `NotAnswerableError`; whether it may
  lack it is the capability table's to say, never the view's (rule R6).
  **As built:** every view must answer every question but `faces` and
  `edges`, which only the B-rep and its STEP file answer; every view holds
  every item kind exactly to its own stated tolerance, except the implicit
  kernel, which holds bodies, cuts, standing features and shells within
  its enclosure (bounded), and true roundings, threads, letters and
  regions not at all. `admit` holds a view from an unknown source, or one
  that says it can't answer what the table says it must.
- `UNKNOWN` is a view saying it can't tell (OpenCascade's classifier can
  fail). It never counts as either side: a check that meets it is
  INCONCLUSIVE.
- Checks reach a view only through `ViewProxy`, which exposes exactly this
  protocol, so nothing about how the part was built can leak through extra
  attributes. It also tidies what is asked (finite points, unit directions)
  and holds the view to its contract: an answer of the wrong shape, a side
  that isn't one, a negative distance, a coverage coarser than asked, is a
  `ViewError`, and the part is held.

### 4.2 The oracle

```python
def place(spec: PartSpec) -> Placed                  # the definitions' own layout
def compare_layouts(placed: Placed, layout: Layout) -> tuple[Difference, ...]
def oracle(spec: PartSpec, placed: Placed) -> Oracle

class Oracle:
    def classify(self, points) -> NDArray[int8]      # strict: IN or OUT; ON only on the surface itself (to 1e-9 mm)
    def limits(self, points) -> tuple[NDArray, NDArray]   # inside the inner limit, inside the outer limit
    def along(self, origins, directions, lengths) -> Along  # the part along segments: places and pieces, exact
    def around(self, centre, u, v, radius) -> NDArray   # the places round a circle where the part can change, exact
    def witness(self, points, radius) -> NDArray[bool]    # the spec's surface comes within radius of each point
    def coverage(self, radius, finest=None) -> OracleCoverage  # every trimmed piece of every surface reached
    def volume(self, rel=1e-3, budget=4_000_000) -> Interval
    def expected_topology(self, resolution=None) -> ExpectedTopology
    unchecked: tuple[Unchecked, ...]
```

### 4.3 Checks and evidence

```python
@dataclass(frozen=True)
class Check:
    id: str                     # "<item>/<field path>[/<copy>]", e.g. "h/counterbore.depth/3"
    item: str
    field: str                  # the leaf field it checks
    klass: VerificationClass    # EXACT, BOUNDED, CONSTRAINED
    needs: frozenset[Capability]
    nominal: float
    tolerance: Tolerance        # +plus / -minus: the value's own, or ISO 2768-m
    def run(self, probe: Probe) -> Evidence   # the view's coverage, windowed by the oracle

@dataclass(frozen=True)
class Evidence:
    check: str; view: str
    verdict: Verdict            # PASS, FAIL, INCONCLUSIVE
    measured: Interval | None   # the measurement and its worst-case uncertainty
    reason: str

def compile_checks(spec: PartSpec, placed: Placed, part: Oracle) -> CheckSuite
```

*As built:* a measurement too uncertain to judge its tolerance (its
interval straddles a limit, and its uncertainty is more than an eighth of
the band) is **taken again where it looked**: the probe notes the box round
every window of built points the measurement took, and the view covers
just those boxes four times finer than the radius there
(`coverage(radius, within=box)`), up to twice, never finer than 0.005 mm
nor over more than 500,000 of the finer radius's squares of surface; and,
since a view may cover every face (or triangle) a box meets whole (as the
views did until stage 4's 13.10, which covers only near the box), never
where those faces, at as many points as the probe has on them times the
factor squared, would come to more than two million (stage 4's exit
shakedown: a mutant's missing surface, looked for again finer at a speck of
a block's broad face, covered all of it: 17 million points). A short surface's coverage points can lie in
a few rows across it (a countersink's slivers from rim to rim), which fixes
a fit only loosely; finer, they spread along it. Only if it is still too
uncertain is it INCONCLUSIVE, saying the view is too coarse. *Stage 4's
exit shakedown (part 1159):* a measurement whose points fixed nothing at
all (a 0.64 mm countersink's points all in one ring round it: no slope) is
taken again finer the same way; and so is one that found too few points to
fit at all where it looked (part 2010: a shell's wall measured where a
block stood on all of it but a 0.16 mm sliver, in which an STL's coverage
had two points). Where it looked is the box round each window of points it
took, and, for a window that came out empty, the box it searched (part
2010 again, once the radius there was 0.5 mm: stage 4's 13.10; no point at
all on the sliver). Only if it still finds too few is the surface missing.

## 5. How each part works

### 5.1 Placing, independently

`place.py` puts every item where the definitions say, from the spec's fields
alone: each host's faces from its own fields and copy (its centre, its axes,
its outward direction, its shape, its material), each position, pattern,
angle and concentric copy, the material under each face, shells' hollows,
pockets' floors, tabs' round ends. It shares no code with
`forge_spec.placement` and imports nothing from it.

- At confirmation, and before any check runs, `compare_layouts` compares
  its copies with the solver's: the items placed, each copy's count, order,
  host, point, direction, axes and box (the box from where it stands: a
  feature standing on a rod keeps the foot that follows the curve as its own
  `foot`), hole diameters, the order the part is made in, hollows, and every
  face that can take something, with its centre, direction, axes, shape and
  sizes. All within 1e-6 mm. Any difference is a Forge bug: the part is held,
  with both answers. It reads the solver's layout through two protocols, so it
  never imports the solver.
- What only the definitions' placement works out: the **material** under
  every flat face as a function over it (a block's size across, a cone's
  taper, a dome's height, a standing item's own height plus its host's where
  it is over its host's face, a pocket's floor less its depth, a hollowed
  body's walls), the most and least of it under any mouth (exactly, from the
  outlines' corners, crossings and nearest points), how deep every cut goes
  (`through` is the most material under its mouth; round a side, hole.md's
  rules), and where a hole round a bore starts (the side's axis).
- **Tested** three ways: worked examples from the definitions' text; the most
  and least material against brute force; and the two placements against each
  other on every layout any test makes (`tests/conftest.py` compares each one
  the solver places with no issue: 5,000 in the suite) and on random specs
  that use every kind, face, position, pattern, round side, concentric
  pairing, hollow and stacking (`tests/v2_specs.py`). The first comparison
  found a solver bug: the make order was worked out before anything was
  placed, so a hollowed body standing sideways had its rim's roundings in the
  wrong place.
- The oracle and the checks use `place.py`'s copies, never the solver's.
  So a mistake in the solver that the compiler copies (a tray's floor faced
  the wrong way, a post's length and width swapped) can't pass: face
  accounting finds the built part isn't the oracle's.
- The generator's `truth.py` is a third placement, used to test the other
  two on random specs.
- **What doesn't fit** (place.md, "When it doesn't fit"): `place.py` is
  written for confirmed specs, but the checks also place specs with one
  field changed (the other choices a choice is told from, 5.8), which no one
  confirmed. So it refuses, itself, what can't be placed: a cut or a
  standing feature that doesn't lie wholly on its flat face (on a ring a cut
  may instead cover the whole opening), a body that doesn't meet its face, an
  item that runs past a round side's end, and a cut through no material. The
  other faults (copies that overlap, a blind cut deeper than its material,
  something standing over a cut's mouth) are the solver's to find; a spec
  with one never reaches the judge, and another choice with one tells
  nothing a check needs.

### 5.2 The oracle's shape

- **Solids.** Each item is one or more exact solids from `shapes.py`, each
  with a signed distance, a closest point and an outward normal: exact for
  planes, boxes, cylinders, cones, balls, tori, prisms of lines and arcs,
  rings turned from outlines; helicoid threads for the thread check.
- **Order.** Items are combined in the make order of the definitions
  (frame.md), computed by the oracle itself: bodies and standing features
  added, cuts taken away, a hollowed body's own roundings and then its
  hollow made with it, the other roundings, chamfers and threads last.
  Classification replays the order on each point, sign-exact. Each item is
  culled by its box, so a point meets only the items near it.
- **Roundings and chamfers** are exact along an edge between two flat faces
  (a cylinder; a chamfer's plane), and along a round rim or joint (a torus;
  a cone). They are **bounded** only in stated zones, round where two
  roundings meet, or where one runs out into a face (as built, below).
- **Threads.** Where a thread's helix starts round its axis is not the
  spec's to say, so the oracle **bounds** it (thread.md): over its length
  from the free end, the rod's material between the minor and major
  cylinders is unknown; the core within is surely material, beyond the rod
  surely air. Its pitch, from the designation (a plain size's coarse pitch
  from the judge's own ISO 261 table, which must agree with the spec's), its
  depth, 5/8 of the sharp triangle's height. The `thread` check (section 7)
  then holds the built thread to the ISO 68-1 basic profile exactly, a
  closed-form surface `r(u)` with `u = (z − hand·θ·P/2π − φ) mod P`, at the
  turn φ the built thread has: so a plain rod, or a wrong pitch or hand,
  fails. Only the run-out at the thread's end is bounded.
- **Unchecked** in stage 2, each shown to you before building and in the
  report (R1): letters (their outlines come from the font, in stage 4),
  extrusions and revolutions (not placed yet), regions (constrained).
- **Points on surfaces, as built.** A point within 1e-9 mm of some step's
  surface is settled from every cell of directions round it (5.2's opening
  paragraph, in the module's docstring). The steps' solids are asked about
  all such points at once, and points whose first-order models are the same
  (a hole's floor across the plate's far face) are settled once: the models
  are rows of one table, told apart by a hash of their bits and checked
  whole, so finding the points alike is no work point by point. Which
  points are that near is found from the steps' bounds, where a solid (or a
  union, intersection or difference of them) whose box is farther than
  1e-9 mm from a point is bounded there by its box alone: still a bound,
  its sign exact and its size at most the distance, and far cheaper than a
  rounding's dozens of bands and discs asked one by one.
- **Along lines, as built.** Every solid gives the places a line meets its
  surface (each flat face's plane, each round surface's quadric, a torus's
  quartic; a few too many do no harm and are dropped when off the surface).
  Between those places the part's side can't change, so `Oracle.along`
  settles one point in each piece, and each place on its own: where the
  pieces either side differ it is on the surface; where they agree it is
  classified (a hole's floor in the plate's far face is air: the hole runs
  on). Places nearer each other than 2e-9 mm are one place.
- **Round circles, as built.** The same for a circle (`Oracle.around`):
  each smooth piece of each solid, carried on past its edges, is a
  polynomial of the point (a plane, a quadric, a torus's quartic), so round
  a circle a trigonometric polynomial of the angle. Its coefficients are
  exact from its values at 16 points round the circle, and the places are
  its roots on the unit circle, polished by Newton's method and kept where
  they are on the solid's surface. A circle in a face meets it at the
  places it crosses the face's outline, as a line in a face does.
- **Roundings and chamfers, as built** (`rounds.py`). Each edge is a corner
  in a section across it: two boundaries through the corner point, each a
  line (a flat face; a round side or a cone's slope, seen in a section
  through the axis) or a circle (a ball's surface). A fillet's section is
  what lies between the corner and the rolling ball's arc, a chamfer's the
  triangle the bevel cuts off. Along a straight edge the section is pushed
  along it, less the ball's cylinder; round a rim or a joint it is turned
  round the axis, less the ball's torus, and cut to the stretch it rounds
  by half-spaces through the axis. It is taken away at an outside edge and
  added at an inside one.
  - *What is at the edge.* At each point of an edge, the shape made so far
    just off it (between the two faces, away from both, and beside each)
    says what is there: the corner itself; nothing, where a cut took it; or
    something else: something standing over the edge, or a corner an
    earlier rounding took away where the edge runs on smoothly into that
    rounding's own edge; or not known (letters, a region, an earlier
    rounding's zone). That can change only where the edge crosses a
    surface of the shape made so far, and those places are found exactly
    (`along`, `around`). A rounding runs through every stretch that is the
    corner or that a cut took (the cut's walls cut it off as the cut found
    them), in runs with some of the corner in each. Where the corner is
    there but a face isn't where the rounding would meet it (a hole's rim
    half a millimetre from the plate's side, rounded 2), the round its
    definition gives isn't the one made: that stretch is only bounded; the
    lines where it meets the faces are crossed with the shape made so far
    exactly, like the edge.
  - *Zones.* Balls as wide as what the rounding changes reaches from its
    edge (to where it meets the faces), and the rounding's size again: at
    each corner where its edges meet at an angle,
    each place a run stops other than at a face square across the edge,
    each place two of its runs end together (they blend there); the
    envelope of each stretch where what is there isn't known; and the whole
    band of an edge on a round side (a boss's foot on a rod follows no
    circle; a mouth's rim on a rod, kept to the near side of the rod). In a
    zone, taking away, the inner form loses all of what the
    rounding would round there and the outer form keeps it; filling, the
    outer form gains the whole zone. Outside its zones a rounding is exact,
    so a missing rounding, a wrong radius or a chamfer for a fillet fails
    along every edge. The plan's tighter limits at the corners (the corner
    the rolling ball sweeps; the single-edge roundings met) are not built:
    at a corner the shape is only bounded.
  - *Earlier roundings.* An edge set running round a face whose corners an
    earlier rounding has rounded follows the face's edge as it was left
    (edges.md). A rim the shell opens is rounded inside and out.
  - *Hollows behind roundings.* A hollowed body's walls follow its own
    roundings as shell.md says: the hollow is the body less every closed
    face's reach, every point within its wall's thickness of it. A face's
    reach is the band its wall's thickness in from it; where a rounding
    meets the face, the face ends, so along that stretch its band stops at
    the line square to the face there, with every point within the
    thickness of that line; a rounding's own face reaches the shell's
    thickness in. With one thickness all round this rounds the hollow's
    corner to r − t behind a fillet (sharp if r ≤ t) and bevels it at
    c − (2 − √2)t behind a chamfer; with a floor thicker or thinner than the
    walls, the floor's reach stops where the rounding meets it, and the
    hollow's corner is what the three reaches leave. Where the rounding is
    only bounded (its zones, grown by the walls' thickness), so is the
    hollow. Found by review: the uniform rule, used for every floor, made a
    tray's floor 4 under a 5 mm fillet with 2 mm walls wrong both ways.
  - *Rounds to the middle.* A rim rounded or bevelled right to its middle
    (a bevel as wide as the rim's radius) turns its section touching the
    axis: a solid round it, a side on the axis inside it, a corner on it a
    cone's point (unknown, as every cone's point is). Found by review: such
    a bevel cut a whole slab.
  - *CAN'T.* A rounding whose edge set names no edge on any copy, nor
    where one may be (in an earlier rounding's zone), or that doesn't fit
    (as big as the ball it meets, reaching past a rim's middle), can't be
    made, with the reason.

### 5.3 Face accounting

Face accounting is the check that a built part is exactly what was asked:
no surface that isn't in the spec, no spec surface that isn't built. Each
coverage point has its own tolerance `t`: the view's at that point, plus a
margin of 10% and a floor of 1e-6 mm.

**The first try, cheap and sound:** a coverage point `p` with outward
normal `n` passes if the other side's material changes along the segment
from `p − t·n` to `p + t·n` **the right way round**: inside at `p − t·n`,
outside at `p + t·n`. A change along a segment no longer than `t` proves
the other surface is within `t`, facing the same way.

**A witness, for the points that fail it:** near an edge, or on the flat
floor of a faceted hole between the true rim and the facets, the other
surface is near but not along the normal. Such a point passes only if a
witness shows the other surface within `t`:

- built point against the spec: `Oracle.witness`, from the closed-form
  closest points on the spec's surfaces near the point, on the curves
  where two of them meet, and at the corners where three do (both found by
  alternating projections: near a corner each edge into it runs on one side
  of it only, so the point on two surfaces found beside a point may be in
  the air, and the corner is not), each kept only if it is on the spec's
  surface (all the candidates of a round classified together); and last,
  where a closest point is where surfaces touch, tangent (every facet
  there in one plane: a pocket's rounded corner meeting another pocket's
  wall, the material between them a cusp, part 9213), the first point
  along the surface, each of 8 ways round it, where the oracle's
  first-order shape tells them apart (their normals no longer on one
  line), if they turned apart all the way there (one face two cuts share
  never does) within a micrometre: the cusp's surface found there runs on
  between them to where they touch;
- spec point against the built part: `GeometryView.distance`, exact on a
  mesh (point to triangle) and on the B-rep (projection onto its faces).

A point with no witness fails, with the point, its normal and the nearest
surfaces found.

**What it finds:** an extra pin (built points where the spec has nothing),
a missing counterbore (spec points where the built part is solid), a sealed
void (its points lie on no spec surface), a skin across an opening, a
square end for a round one, a rounding of the wrong radius, a chamfer for a
fillet, a plain rod for a thread, material on the wrong side of a surface.

**As built** (`accounting.py`, `account_faces`):

- **Built points** are the view's coverage. Against the spec, inside and
  outside are its two forms: behind a built point must be inside all the
  part may hold (the outer form) and ahead outside all it must hold (the
  inner form). Where the forms agree that is the exact test; where they
  don't (a rounding's zone at a corner, a thread's flanks, letters, a
  region) the point passes as **bounded**, as does a built point strictly
  between the forms, where the spec lets the surface be anywhere. The rest
  are searched for a witness, except those whose outer form's bound is
  beyond `t`, which have none to find: a part built badly wrong is judged
  in seconds, not minutes. A point the oracle can't place either side of
  (a cone's apex) is **unsure**, which holds the part.
- **Spec points** are the oracle's coverage (5.4), with the tolerance of
  the built points near each (the greatest within reach). A change of side
  across a spec point's segment would put the built surface within `t` of
  it too, so the exact distance alone decides, at half the cost of
  classifying both ends.
- The finding gives `h`, the least and greatest `t`, each side's tally
  (exact, bounded, witnessed, missed, unsure) and the first misses with
  their points and normals.
- **Tested** (tests/test_v2_checks_accounting.py) on every reference part,
  which all pass, and on damage that must fail where it is: a pin, a sealed
  void, a bump or a dent of `2t`, a skin over a through hole, an unasked
  0.3 mm chamfer, a missing hole or counterbore, a fillet of 3.5 for 3, a
  chamfer for a fillet, a dome meshed four times coarser than it says, the
  part moved by `3t`. Near-misses pass: the same coarse dome saying so,
  vertices jittered within the deflection, coordinates in float32, the
  part moved by `t/2`.

### 5.4 Coverage, and what it guarantees

Coverage is deterministic: nothing is left to a random sample.

- **The built side.** Every triangle is tested at its corners, the middles
  of its sides and its centre, and split until no piece is longer than `h`.
  On the B-rep, every face is covered to radius `h` with at least 16 points,
  and every edge along its length.
- **The spec side.** Every trimmed piece of every surface is covered to
  radius `h`: points are spread on the untrimmed surface, kept where the
  oracle says the surface is the part's, and spread finer until every piece
  is reached or proved empty. Bands of points run at fixed distances from
  every trim curve (2t, 0.05, 0.1, 0.2 and 0.5 mm), where small defects sit.
- **`h`** is derived from the spec, place by place: half the smallest
  feature (hole radius, slot width, wall, rounding, step) of the items
  there, and never more than 0.5 mm; a feature's size holds round its
  item's own solids (stage 4, docs/V2-stage4.md 13.10).
- **The guarantee:** a surface wholly extra or wholly missing is found; a
  departure of more than `t` across any patch `h` wide is found, `h` the
  radius where the patch is. The verdict states `h` everywhere, the finer
  `h` round the items that ask for one, and `t`.
- **The spec side, as built.** Each smooth piece of each solid (once,
  whichever steps the solid is in) is split into cells no wider than the
  radius, and each cell kept when its middle is on the part's surface and
  no other solid's surface comes within its reach (other than lying on all
  of it); otherwise it is split in four, down to a sixteenth of the radius,
  where every piece found on the part's surface is kept. A convex solid's
  surface that a cell only runs beside (a face tangent to a rounding) is
  shown to miss it from its convexity: its signed distance at the cell's
  middle, less its slope along the cell times the cell's reach, less how
  far the cell bends from flat (a cylinder's cell: its arc's sagitta; a
  cone's band's, its arc's at its largest radius; a flat ring's, none). A
  solid of revolution's is shown so in its own half-plane, where its
  signed distance is convex (stage 4, docs/V2-stage4.md 13.11).
  Every surface's cells are settled together, a round of splitting at a
  time, and each is asked only what decides it: whether another surface
  comes near only where the cell is wholly on its patch and may still be
  split, and whether the part's surface is there only where the cell would
  be kept.

### 5.5 Topology and volume

- The built part is one solid, with the voids the oracle expects, and with
  no open edges, no bad edges (on three triangles, or twice the same way),
  no bad vertices (a vertex whose triangles don't make one fan), no
  self-intersections (triangle against triangle, through the grid), shells
  nested as their orientation says (a void is inside a solid, by ray
  parity), and the genus (through-holes) the oracle expects where it can say.
- Volume is a cross-check, not part of the guarantee: within the oracle's
  volume interval, widened by the band the view's deflection allows on its
  convex and concave surfaces.
- **The judging, as built** (`topology.py`): `judge_topology` lists every
  way the built topology differs (each kind of soundness defect with its
  count, the solids, the sealed voids, the through-holes where the oracle
  counts them) and fails on any; what the oracle doesn't count is listed
  as unchecked with its reason, never passed silently. `judge_volume`
  passes when the oracle's interval and the view's overlap (a mesh view's
  is its own widened by its deflection over its area), fails when they
  don't, and can't judge a view whose volume is unbounded (a mesh that
  isn't sound).
- **As built,** the oracle's volume is an interval that surely holds it:
  cells whose centre's folded bound (at most the distance to the surface,
  solids farther than the half-diagonal bounded by their boxes) is beyond
  their half-diagonal are wholly in or out; the rest are split until what they
  leave unknown is below `rel` of what is known, or the budget of cells is
  spent. The interval runs from the inner form's least to the outer form's
  most. With the default budget its width is 3% (a dome) to 30% (a tray
  of thin walls) of the volume, because every cell a surface passes through
  counts whole: it finds a missing hollow or a solid that should be a tube,
  not a missing hole (coverage finds that).

### 5.6 Expected topology

- **Solids:** one (a cut that would cut the part in two is a CAN'T).
- **Voids, as built.** Counted on a grid, but never by guessing between its
  points: two neighbouring grid points are joined only where the part along
  the grid line between them is air all the way, worked out exactly
  (`Oracle.along`: where the line meets each step's solids, and each piece
  and place between settled exactly). So a wall however thin keeps them
  apart, and a cut that runs on into air (a through hole's floor in the
  plate's far face, a vent's end in a hollow) joins them. The air the
  grid's border reaches is the outside; the rest is sealed voids, counted as
  the pieces it makes (runs along z, joined across by union-find).
- **The grid** is a quarter of the narrowest thing that makes air (a cut, a
  bore, a hollow; not a rounding or a chamfer, whose air lies along edges
  beside air already there), or a hundredth of the part, whichever is
  finer, so every
  cut has grid points all along it. Air a grid line meets but no grid
  point is in (the wedge under a cone's overhang, the sliver where a boss
  meets a bore) is joined to the grid points round it that a straight line
  all in air reaches; if none, the count isn't made on that grid.
- **Air the grid can't see.** Items added after a cut can fill it but for a
  sliver, and two cuts can only just meet: air, or a passage between two
  pieces of air, finer than the grid, that no grid line crosses. So the
  part's surface is covered to twice the grid step (its finest cells a
  quarter of a step), and a point a hair off each covering point, in the
  air, is a **seed**. Each seed must be joined by a straight line through
  air to a grid point round it, or to seeds that are; and where two seeds
  of different pieces of air lie side by side (within what the covering
  can leave between two seeds on one wall) and the air in front of either
  is thin, a straight line through air must join them. Air the grid can't
  see is thin, so along any way through it such seeds meet where the
  pieces change: a passage the grid misses either joins the pieces it
  links or stops the count. Only air narrower than the covering's finest
  cells everywhere can go unseen (a quarter of the step: 0.1 mm on a
  0.4 mm grid). Found by review: posts filling a covered pocket but for a
  0.2 mm cube were counted as no void, and two hollows joined by a 0.2 mm
  pipe as two.
- **What a grid can still miss** is an opening between two pieces of air
  finer than the grid, where they only just meet. So the count stands only
  if no void's air comes within two grid steps of other air, or of letters
  or a region (whose shape isn't known yet); otherwise it is made again on a
  grid twice as fine, three times at most, and within 16 million points.
  It is made on two grids half a step apart, which must agree. Otherwise
  the voids are **unchecked**, with the reason (a 0.1 mm skin left over a
  hollow by a dimple is one).
- Tested against reference parts made by hand with manifold3d, three with
  sealed voids (a closed box, a pocket a post covers, two hollowed blocks
  stacked), and against a 200 mm box with 2 mm walls (one void, in two
  seconds).
- **Genus:** not counted yet (unchecked, with the reason).

### 5.7 The mesh view

- **Reading.** STL (binary or text; a binary file whose header starts with
  "solid" is still read as binary when its length says so) and 3MF (the model
  part; its `unit`; build items, components and their transforms, a
  transform that mirrors flipping the winding, whether it mirrors or
  flattens decided exactly; object types, a support or second object
  refused). Numbers must be written as numbers. The 3MF model is read as a
  stream by an XML parser that itself refuses document types and entities in
  any encoding; required extensions are looked up where their prefixes are
  declared; an object has one mesh or one set of components, a mesh one
  vertex list and one triangle list; ids and vertex numbers have at most 18
  digits; every way a package can fail to unpack (a bad checksum, a broken
  stream, encryption, an unknown method, two parts with one name) is a
  refusal; components may multiply into at most 50 million triangles in at
  most 100,000 meshes, placed by visiting at most a million objects, counted
  once per object and walked without recursion. An STL has no units: it is read as millimetres, and its
  size is checked against the spec's.
- **Welding.** Vertices at exactly the same coordinates are one; nothing
  closer is merged, so a crack stays a crack. NaN, infinite or degenerate
  triangles are reported, never dropped; so is a coordinate below 1e-50 mm
  that isn't zero, or above 1e30 mm, which the exact predicates can't take.
- **The tree.** A tree of boxes over the triangles, each node's box holding
  its triangles' boxes whole, so a large CAD triangle is found from anywhere
  it reaches. It is built by halving at the middle triangle, not by space,
  so it stays shallow where a mesh is dense (a thread's flanks) and coarse
  where it is sparse. (Revision 1 had a uniform grid of at most 65 cells a
  side; a thread's thousands of triangles in a few cells made it slow, and
  the tree gives the same guarantee.)
- **Distance and closest points,** to within a stated error `E` of 128
  units in the last place of the coordinates' size (measured against exact
  rationals: about 4): each triangle's unit normal is taken at the corner
  opposite its longest side, or worked out exactly for a needle or a cap; a
  point's nearest point is its foot on the plane if that surely falls
  inside, else the nearest point of the three sides (past a needle's tip,
  both long sides' lines pass within rounding of a foot far outside). (Ericson's region formulas square a
  sliver's thinness and lost it: points on a 2.5e-4 rad sliver measured
  1.6e-6 mm away.)
- **Soundness, exactly.** Every edge has two triangles running opposite
  ways; every corner's triangles make one fan; no two triangles meet where
  they aren't joined, decided with exact orientation signs (shared corners
  and sides judged on what lies beyond them; checked against an exact
  Fourier-Motzkin oracle on degenerate cases; a corner with many triangles
  proved a simple fan at once, so a cone's apex costs no pairwise tests; the
  same triangle given many times counted, not searched); and
  the shells nest as their orientations say, by ray parity, each shell's
  volume taken about its own centre with a bound on its rounding.
- **Classification.** A point surely within 1e-9 mm of the surface is ON;
  one that may be on either side of that band is UNKNOWN (the checks'
  tolerances are theirs, not the view's). Elsewhere: the sign of the
  closest feature's angle-weighted pseudonormal (Bærentzen and Aanæs),
  exact on a sound mesh. Because rounding can pick the wrong feature where
  two are almost equally near (a knife-edge far from the origin; the two
  sides at a needle's tip, within one triangle), every corner, side and face
  within `2E` of the nearest is asked too: all must agree, each well clear
  of its own rounding. Where they don't, or a feature's normal
  is too ill-defined (a needle's corner): three rays in fixed directions,
  each counting its crossings and their directions; a ray that grazes an
  edge or a corner, or meets two surfaces at distances rounding can't tell
  apart, is cast again in the next direction, and the three must agree, or
  the point is UNKNOWN. A mesh that isn't sound classifies nothing: every
  point is UNKNOWN, and its volume is the whole real line.
- **Crossings:** the watertight ray test (Woop, Benthin and Wald): a ray
  through the side two triangles share crosses exactly one of them; one that
  passes exactly through a side or a corner, or meets two triangles at
  distances rounding can't tell apart, is reported as grazing, and is cast
  again by whoever cast it.
- **Volume:** the divergence theorem, with a stated bound on its rounding.
- **Coverage:** each triangle covered by rows of points parallel to its
  longest side, the first row that side, `g = r/√2` apart and each row's
  points at most `√2·r` apart from end to end (`r = h − s`, `s` being the
  rounding of a sample's position and of a triangle's height). The angles at
  the longest side's ends are not obtuse, so each row spans the triangle
  above it, and every point is within `√(g² + r²/2) = r` of a point; a
  needle, as exporters make many of, takes one row. The radius reported is
  the one the rows reach. Each triangle's own side middles and centre are
  kept too, with the outward normal of the feature each lies on. About one
  point per `r²` of area: on generated part 0 at `r` = 0.375 mm, 0.54
  million points and 0.24 GB at most for the whole run, where halving each
  triangle until no piece was longer than `√3·r` made 3.5 million and 4.5 GB
  (the laptop has 2 GB). Triangles are covered a batch at a time, so the
  working memory beside the points made is bounded. Within a box, the
  triangles that meet it are split in four (at their sides' middles) until
  their pieces are no wider than a quarter of the box (or four radii), the
  pieces whose own box misses it dropped, and the pieces covered so (stage
  4, docs/V2-stage4.md 13.10).
- **The proxy** turns anything a view does wrong (it raises, or answers out
  of contract: booleans for sides, a NaN, a negative count, a subclass of the
  answer type) into a `ViewError`, which holds the part; only a question the
  view doesn't answer is `NotAnswerableError`. Python can't hide the view
  inside the proxy's closure, so a test forbids any other module of the
  package from naming the proxy's internals or introspecting.
- **Deflection:** declared with the file, never inferred, and **verified**
  by face accounting itself: a mesh farther from the true surface than it
  says has built points (its facets' middles on a round face) beyond their
  tolerance, and fails. Its volume is the mesh's own widened by the
  deflection over its area, an interval that holds the true part's.

### 5.8 The check compiler (as built)

`compile_checks(spec, placed, part)` gives every check of a confirmed spec
and every leaf it can't check, with the reason (`compiler.py`). Every
target is placed by the judge's own placement and the oracle, never the
solver's, and every measurement is between built things: a hole's position
from the face's fitted edge to the hole's fitted axis, never from the
frame's origin.

- **Leaves** (`leaves(item)`): a counterbore's and a countersink's values
  one by one; a place's position along each axis (its side, distance and
  `to` together), its angle, what it is concentric with, and its pattern's
  values, counts and axis; every other field is one leaf (a fit: its kind,
  size and grade give one size). Each gets checks, or a `NotChecked` with
  its reason, shown before building and in the report.
- **What the spec assumes is checked too:** a position left out (centred), an
  angle left out (0 degrees round a side), a circle's start left out
  (0 degrees), a thread's whole length.
- **Each item's centre**, as positions, pitches, circles and counts measure
  it: a round item's fitted axis (a hole's, a boss's, a rod's, a circular
  pocket's), a cone's fitted axis, a ball's fitted centre, or the middle of
  a box item's or a pocket's or a slot's two fitted sides (each a disc as
  wide as the side). A pattern's centre is the mean of its copies' centres,
  an arc's the centre of the circle through them. Round a side, an item's
  angle is round the side's fitted axis, and its place along the side from
  the side's ends: its end faces, the face a standing body is joined to, or
  the rim a shell leaves open.
- **Choices are told, not assumed:** an item's face, a choice, a pattern's
  axis, an edge set and the faces a shell leaves open are each told from the
  shape every other choice makes (the oracle's, with that one field changed
  and placed by the judge, where it fits): points at least the item's widest
  tolerance band and 0.05 mm from both shapes' surfaces, inside one and
  outside the other.
- **Where the built surface is looked for:** a cut's floor over its own
  outline (a rectangle's, or a disc's), and its flat walls over their own
  rectangles, from the mouth down to the floor, so what another cut leaves
  of them (a hole from the far face through most of a pocket's floor) is
  measured wherever it is, and nothing beside them in their plane is.
- **Sides that are all arc:** a side, or a face's edge, whose rounded
  corners leave less than 0.5 mm of it flat (a pocket rounded to half its
  width at its ends, a slot as long as it is wide, a round-ended tab's far
  edge, an all-half-disc tab's sides) is measured from its rounding's
  fitted circle, which reaches as far as the flat side would: a flat side's
  plane would touch it along one line only. A round-ended tab's narrow
  side stops where its rounding starts, with no edge built there: it is
  measured from the rounding's fitted axis, level with it.
- **The coverage radius** the checks measure at is, at each place, half the
  smallest feature of the items there, and never more than 0.5 mm (each
  size holds round the pieces of its item's own solids, grown by 0.5 mm
  and the size: stage 4, docs/V2-stage4.md 13.10).
- **What isn't checked yet,** and why: letters (their outlines come from the
  font in stage 4), regions (designed later, within their envelope),
  extrusions and revolutions (not placed yet); a shell's `of` (its walls
  are checked) and a floor as thick as the walls (checked with them); a
  surface the spec covers all of (a stacked block's base, a post's top under
  a boss), whose size can't be told from the built part at all; a circle or
  an arc of fewer than three copies (no centre to measure round: face
  accounting holds their places); a chamfer beside a ball's surface.
- **Tested** (`tests/test_v2_checks_compiler.py`): on every reference part,
  every check passes on the part as built at its honest deflection (its
  widest circle's 256-sided polygon's, three times, with room), fine enough
  for its tolerance; every leaf, counted from the items as drafted by code
  that shares nothing with the compiler, has a check or a reason; and the
  same holds on random specs. The random specs found, as this was built,
  posts and pockets in rows and circles with no pitch checks, patterns round
  a side with no step or count checks, a boss on a rod with no diameter
  check, a hollowed rod's round wall and a hollow ball's never measured,
  and another choice placed off its face.

## 6. Tolerances and the verdict

- **The design tolerance** `T` is the value's own (`+plus / -minus`), or the
  general one (ISO 2768-m, [sizes.md](definitions/sizes.md)).
- **The measurement's uncertainty** `u` is a **worst-case** bound, never a
  statistical one: the sum over its inputs of how much each can move the
  result, times how far each can be off. Points on a mesh can be off by its
  deflection; a radius fitted to an arc of angle `a` moves by a factor that
  grows as the arc shortens (about 1.8 for 180°, 8.7 for 90°, 37 for 45°).
  Fits use the mesh's vertices where the view declares they lie on the true
  surface (OpenCascade's and the reference meshes' do), and the deflection
  bound otherwise.
- **As built (stage 4's exit shakedown, part 950).** A value made of several
  fitted unknowns is bounded as one: an arc's edge (its axis's place plus
  its radius), a cone's rim, a ball's top, a circle's centre along a
  slant: from its own weight on each point, never its parts' bounds added,
  which on a short arc are far looser (the centre and the radius move
  together: a quarter circle's edge through a 0.005 mm mesh is ±0.012, not
  ±0.078). And every bound is taken to second order: the first-order sum
  fell short of its worst case on a short arc (by 4% on a quarter circle,
  23% on an eighth, 70% on a twelfth), so the residuals' second
  derivatives, over as far as the fit may be off, are added, and that far
  fed back until the bound holds itself. An arc too short for its points'
  deflection to hold such a bound (under about 45° at a radius 200 times
  the deflection) fixes nothing, and its check is INCONCLUSIVE
  (`measure.Errors`).
- **The verdict** is interval logic: PASS when `[m − u, m + u]` lies inside
  `[nominal − minus, nominal + plus]`; FAIL when they don't overlap;
  INCONCLUSIVE otherwise. INCONCLUSIVE holds the part.
- **As built** (`classes.py`): the general tolerance row by row, under
  0.5 mm ±0.05; a value's own tolerance converted from its unit as the
  value is; `judge` as above, INCONCLUSIVE for an unbounded measurement;
  a measurement is fine enough when `u` is at most an eighth of the
  tolerance band (a quarter of a symmetric tolerance's half-width, and
  meaningful for a one-sided fit's +0.015/0 too); `brackets` gives the
  near-misses `2u` inside each limit and the mutants `2u` outside.
- **How fine the export must be** is set by the check compiler from the
  checks: every check's `u` must be at most a quarter of its `T`, so the
  compiler asks for the deflection that gives it, and the release gate
  refuses a file exported coarser.

## 7. Check kinds

Each kind measures one aspect of an item on a view, from geometry only, in
a window the oracle gives (the built points near the surfaces the spec says
are there, facing their way, whose feet the spec has on its surface; a
point farther from the surface than its deflection that lies where another
of the spec's surfaces may be is that surface's, and is left out: stage 4's
exit, part 3767, a slot's wall within an angle's wide window round a bore,
taken for the bore's, put its fitted axis 0.86 mm off with a bound of a
hundredth of a micron). A surface the spec says is there and the built part
lacks is a FAIL, not an INCONCLUSIVE.

| Kind | Measures (its targets, `kinds/`) | Fields |
|---|---|---|
| `diameter` | a circle fitted across the spec's axis (`Round`); a cone's radius at an end (`Across`); a fitted ball (`Ball`) | diameters, bores, counterbore and countersink diameters, fits, a round end's width |
| `size` | two fitted planes' distance (`Between`); or between two located things (`Position`: a round-ended slot's ends; a body's height from the fitted axis of the rod or bore it stands on, less its radius) | lengths, widths, heights, thicknesses |
| `depth` | from the face's fitted plane round the mouth to the floor's; in a round side, from the side's fitted axis to the floor, less its radius; right through, by lines down the axis (`Open`) | depths, a counterbore's depth, through |
| `position` | from the host face's built edges or centre to the item's built centre or edge (`Position` between references: fitted planes and the middle of two, fitted axes and their edges, a cone's axis and its rim, a ball's centre, the mean of a pattern's built centres, an arc's centre `Hub`) | every position along a face's axis or a side's, assumed or stated; concentric |
| `count` | the copies found where the spec puts them (`Copies`) | counts, pattern counts |
| `pattern` | the pitch between pairs of copies' built centres (`Pitches`); the circle through them (`Circle`) | pitches, a rectangle's sides, a circle's or an arc's diameter |
| `angle` | a cone's full angle (`Cone`); copies' angles round a line (`Turns`): round a side, its fitted axis; on a flat face, the circle through the copies' built centres | countersink angle, an angle round a side, a circle's or an arc's start and step |
| `corner` | a fitted arc in the outline | a pocket's corner radius |
| `rounding` | a fitted arc or bevel across the edge, along every stretch the oracle rounds exactly (`Round`, `Tube`, `Bevel`, `RoundBevel`) | fillet radius, chamfer size |
| `wall` | two fitted planes across the wall (`Between`), each within 2 mm of a spot where both are the part's surface whole: the face's middle, else the nearest such spot (stage 4's exit, part 4050); two coaxial round surfaces or two concentric balls (`Annulus`), every part of the wall at once | a shell's thickness, its floor |
| `thread` | the basic profile fitted along the helix; its pitch, hand and length | designation, pitch, hand, length |
| `on` | told from the item on each other face of its host | `on` |
| `choice` | told from each other choice's shape | round or square, rectangle or circle, an axis, a pattern's axis, an edge set, open faces, a ball or a dome |

Each kind's file holds, and a test requires, its measurement, its tolerance
policy, its mutants and its near-misses (section 8).

**Angles round a circle** depend on where its centre is, and its centre on
every copy: so a start or a step is not off by each copy's angle's error
added up as if the centre moved with each copy alone, but by the first-order
worst case over every copy's own error, the centre refitted (each copy
moved a hair along each axis, the circle fitted again). Round a side the
side's fitted axis is independent of the copies, and their errors add.

## 8. Proving the checks

### 8.1 Reference parts

- **By hand:** `tests/v2_reference.py` describes each reference part as a
  small CSG tree (so stage 3 can build the same parts in OpenCascade), with
  the spec it is meant to be. The tests build them with `manifold3d`, which
  Forge itself never uses: flat faces exact, round faces as fine polygons
  with every vertex on the true surface. Near-tangent intersections are kept
  out of them, so their deflection stays what it says.
- **From random specs:** hundreds more, built from `truth.py`'s own
  placement and `manifold3d`, so they depend on neither the solver nor the
  oracle.
  *As built (step 7):* the generator (`forge_eval/generator.py`) chooses a
  part as a plan (a block or a rod; holes, counterbored and countersunk,
  pockets, slots, bosses, posts and blocks standing on it and on each
  other, on every face and round the rod's side; positions of every mode,
  rows, grids, rectangles, corners and circles), works out from the
  definitions where every copy goes and what solid each makes
  (`forge_eval/truth.py`), and writes the draft that says so. It shares
  nothing with the solver, the judge's placement or the oracle, and imports
  none of them (R2). Its parts interact: holes through a boss and what it
  stands on, cuts from two faces meeting inside, holes round a rod crossing
  at its axis. `tests/v2_truth.py` builds them as meshes the way an
  exporter does: every round edge split into a power of two of sides
  within 0.0004 mm of its arc, so one small honest deflection holds for the
  whole part. *As built (stage 4's exit shakedown):* a thread's twisted mesh
  strays farther (0.005 mm), and once fits were bounded to second order
  (section 6) a part's small rounding beside a thread could no longer be
  judged at the thread's deflection (part 53's 0.455 mm fillet, ±0.05). A
  mesh view may say how far each of its triangles may be from the true
  surface (`MeshView`), and a generated part's mesh says its thread's
  triangles (traced through the booleans by the mesh library's note of the
  solid each came from) are the thread's deflection off, the rest its round
  edges'. Tested (`tests/test_v2_eval_truth.py`): the three placements
  agree on every copy of 150 parts; 30 parts made impossible on purpose (a
  cut off its face, deeper than its material, copies overlapping) are each
  turned back by the solver, and by the judge where the rule broken is its
  own; the oracle and the truth agree on the side of 20,000 points of each
  of 10 parts; 12 parts built (and the 5 kept regressions, below) pass face
  accounting and every check compiled from their specs. The first comparisons found the judge's edge of a round
  face measured from the wrong side (a position "from the +x edge" of a
  rod's end), and a mesh made with two solids' vertices meeting is no fair
  reference: the generator keeps them apart, and the few the mesh library
  still makes unsoundly are counted and skipped.

  *Step 8 widened it:* tabs, square and round-ended (holes and pockets on
  their broad faces and narrow sides), and shapes at the ends of their
  ranges on purpose: pockets rounded all across their ends, slots as long
  as they are wide, tabs all half-disc. Each solid is carried past its ends
  only 0.05 mm in a mesh (a countersink carried a millimetre out of its
  mouth cut into the body beside the post it was in), and two round solids
  that meet cross cleanly: their surfaces 0.5 mm apart, or one 0.5 mm within
  the other (two rods of about one size crossing, or one grazing another,
  cross where their polygons do, far from where the surfaces do, beyond any
  deflection their sag gives). Every leaf's mutant of 60 parts is checked to
  be a part the solver takes, differing in that leaf alone. Sweeps of 200
  generated parts, every check and face accounting on each, found the
  judge's faults listed in 5.8 (a floor mostly cut away by a hole from the
  far face, a round-ended tab's edges, corners on a second post measured
  from the first post's face); the parts that found them are kept as plans
  (`tests/v2_regressions.py`) and built with the others. The last sweep,
  generated parts 0 to 199 with every fix in: **all 197 whose meshes the
  mesh library made soundly pass face accounting and every check** (3 of
  200 unsound, skipped: three holes crossing at a rod's axis, and blind
  holes round a rod with slots in its ends).

### 8.2 Mutants and near-misses

Generated, not picked:

- **Bracketed, per check:** each value set to `nominal ± (T − 2u)` must
  PASS; to `nominal ± (T + 2u)` must FAIL (not INCONCLUSIVE). `u` is at most
  `T/4`, or the export is made finer.
- **Face accounting, its own pairs:** departures of `t/2` pass, of `2t`
  fail, on every kind of surface.
- **Placement:** every position, size, pitch and angle at the brackets; the
  wrong face (+z for -z, outer for inner, +end for -end); mirrored; axes
  swapped; a pattern turned half a step; a copy missing or added.
- **Shape class:** a round end for a square one and back; a counterbore for
  a countersink; a fillet for a chamfer of the same size; blind for through
  with a 0.01 mm skin; an open face sealed, a sealed one open; a wrong floor;
  the wrong edge set; one corner's rounding missing; a thread's pitch, hand
  or length wrong; a plain rod for a thread.
- **Unasked geometry,** from `t/2` to 2 mm: bumps, dents, pins, holes, small
  chamfers on random edges, steps of `2t`, slivers, voids at random depths
  (0.1 mm under a face: a skin), a loose chip, a shell floating in a void.
- **Mesh integrity:** a missing, flipped or doubled triangle; a crack at a
  T-junction; a fold through itself; a bad vertex; an inside-out shell; two
  overlapping shells; degenerate triangles; NaN; a binary STL that begins
  "solid"; a 3MF in inches or micrometres, with two objects, or a support;
  a mirrored component; a true deflection five times the declared one.
- **Whole-part transforms:** moved by `T` and a little; scaled by 1.001 and
  by 25.4; mirrored; turned 90 degrees.
- **Correlated faults:** a bug planted in the solver's layout, the reference
  part built from the bugged layout (as a compiler copying the solver
  would), and the checks run with the confirmed spec: the independent
  placement must hold it. This tests the plan's central independence claim.
- **Near-misses that must pass:** remeshed at several deflections, flat
  faces triangulated differently, vertices jittered by up to half the
  deflection, coordinates rounded to float32, the part placed 1000 mm from
  the origin.

*As built (step 8):*

- The kinds' bracketed mutants and near-misses, face accounting's own
  pairs, the mesh-integrity mutants and the unasked geometry are step 4's
  and 5's tests (`test_v2_checks_kinds*.py`, `test_v2_checks_accounting.py`,
  `test_v2_checks_mesh.py`); a mutant per leaf is step 7's (9).
- **Correlated faults** (`tests/test_v2_eval_faults.py`): four bugs planted
  in the solver (a side measured from the far edge, an edge measured to the
  centre, an offset the wrong way, a pattern's pitch a tenth long), each on
  the first two generated parts it moves a copy of and the bugged solver
  accepts. The part is built where the bugged solver puts its items (the
  truth's solids moved by each copy's difference); the judge's placement
  differs from the bugged layout at every moved copy, face accounting
  fails, and a check of each moved item fails.
- **Whole-part transforms** (the same file): moved 0.05 mm, scaled by 1.001
  and by 25.4, mirrored, turned 90 degrees, on generated parts: face
  accounting fails every one that changes the part (a part symmetric that
  way, told from the truth, is left out).
- **Near-misses** (the same file): built four times coarser and saying so,
  vertices jittered by up to half the deflection, coordinates rounded to
  float32: face accounting and every check pass. Placed far from the origin
  is the mesh view's own test, and triangulated differently is every
  generated part's (manifold3d's triangles, not the hand-made parts').
- **Fresh probes** (`forge_checks/probes.py`, tested in
  `tests/test_v2_checks_probes.py`): drawn round every copy of every item
  from a seed the run records, at least four times the view's tolerance
  (and 0.01 mm) clear of the spec's surface by the oracle's bound, kept
  only where both its forms agree. On generated parts every point is on the
  truth's side and clear of its surface by the margin; every item passes on
  the part as asked; an item taken away, or moved well off its place,
  fails its own probes; a view too coarse for the margin, or one that can't
  tell, is inconclusive.

### 8.3 What is reported

A detection matrix (every mutant against every check, which caught it), and
the false-hold rate on correct parts, each with its denominator.

*As built:* `python tests/v2_detection.py --parts N` writes
[V2-detection.md](V2-detection.md): for each generated part, the part as
asked and its faults (leaf mutants spread over its items, an item taken
away, the whole-part transforms), each judged by every check (by kind),
face accounting, topology, volume and fresh probes; the parts as asked
any detector holds, and for each class of fault how many each detector
failed, how many any did, and which got past them all.
`tests/test_v2_eval_detection.py` runs it on a part or two.

**The exit test, as run** (generated parts 0 to 23, 89 minutes): no part
as asked was held (0 of 23; one more skipped, its mesh unsound), and all
370 faults were held by a FAIL, none only inconclusive and none missed.
Face accounting failed every one; fresh probes 356 (the rest moved a
surface by a few tenths, between their points); each leaf's own kind failed
most of its own (rule R1 holds per leaf in `AMutantPerLeaf`); topology
failed none (no fault in the matrix changes how many solids or voids the
part has: the hand-made voids and chips of 8.2 are its own). With the 200
generated parts of 8.1 (197 sound, all passing) and the kinds' bracketed
mutants and near-misses, every mutant beyond tolerance is rejected and
every near-miss passed, for every check kind.

## 9. Rules R1 and R2

- **R1:** the check compiler covers every **leaf** field of every kind: each
  position's side, distance and `to`; each pattern value and count; each
  counterbore and countersink value; a fit's kind, size and grade; an edge
  set's item, edges and joint; a shell's open faces and floor; every choice;
  every copy. Each leaf gives a check that some active view can answer at
  its tolerance, or an unchecked with its reason. A test enumerates the
  leaves from the schema, and requires, for each, a mutant its check
  rejects. Totality is also tested on generated specs.
  *As built (steps 6 and 7):* the leaves are counted from each item as
  drafted, by the test's own walk of it, on every reference part and on
  random specs (5.8); a position's side, distance and `to` are one leaf,
  measured as one place, as a fit's kind, size and grade are one size. The
  mutant per leaf is the generator's (`mutants`): the part with that one
  value moved beyond its tolerance (three times the general tolerance and
  0.3 mm more), a count one fewer or one more, a choice the other way, the
  item on another face of its host, a hole through made blind; its draft
  differs from the original's in that leaf alone, and the solver accepts it
  as a part of its own. Built, it must be rejected by that leaf's own
  checks. A change that leaves the shape as it was (a hole through moved to
  the far face) is no mutant, and a pocket's shape isn't changed (its
  fields change with it).
- **R2:** the import rules are by dotted module and by symbol:
  `forge_checks` never imports `forge_spec.placement`, `forge_spec.geometry`,
  `forge_plan`, `forge_kernel`, `forge_occ`, `forge_designer`, `forge_geom`
  or `forge_eval`; `forge_eval/truth.py` never imports `forge_spec.placement`,
  `forge_spec.geometry`, `forge_checks`, `forge_geom` or `forge_kernel`; no
  re-export through a package's `__init__` gets round a rule; `importlib` and
  `__import__` are refused in both.

## 10. Speed

Face accounting and the oracle must run in minutes on a laptop, on the
largest parts the solver places. Every search walks a tree of boxes, every
item is culled by its box, candidate pairs are handed on in batches so
memory stays bounded (a search keeps at most a fixed number of point-node
pairs waiting, splitting its points in two past it), and time budgets are tested: a 2,000-hole plate, and
a 1M-triangle mesh. (Measured on the cloud machine, an 820,000-triangle
plate: soundness in 16 s, 200,000 points classified in 64 s, coverage at
0.5 mm in 7 s. The pairwise soundness test grows with the square of how
many long triangles' boxes overlap: a cone of 2,000 triangles takes 2 s, one
of 8,000 takes 25 s.)

## 11. The order of work

1. The definitions: shells round their own edges first (done with this
   revision).
2. `view.py`, `readers.py`, `mesh.py`, tested on meshes whose answers are
   known exactly, and on every mesh-integrity mutant.
3. `shapes.py`, `place.py` (with `compare_layouts` against the solver on
   every test spec and random specs), `oracle.py`.
4. `accounting.py`, `topology.py`, `classes.py`, `capabilities.py`, on
   reference parts, correct and damaged.
5. The check kinds, each with its generated mutants and near-misses (done).
6. `compiler.py`, the R1 and R2 tests (done: R1 as in 5.8; R2 in `tests/test_v2_architecture.py`).
7. `truth.py`, `generator.py`, random reference parts, and the three
   placements tested against each other (done: 8.1, and a mutant per leaf, 9).
8. Relation checks, fresh probes, the detection matrix and the false-hold
   rate: the exit test (done: relation checks are the compiler's place
   checks, 5.8; fresh probes, faults and near-misses, 8.2; the matrix and
   the rate, 8.3).

Each step lands with its tests, lint and type checks clean, and is saved to
the laptop.

## 12. Open questions for you

- **A bearing seat's tolerance:** by the definitions a seat takes the
  general tolerance (±0.2 mm on a 608's 22 mm), far looser than a press fit
  (H7 is +0.021/0). Should a seat carry its own, or the brief's?

- **Approve the definitions** ([definitions/](definitions/README.md)): the
  three programs are written from them.
- **The tests' mesh library:** `manifold3d` (Apache-2.0), installed for the
  tests on the laptop too.
