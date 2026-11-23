# Forge V2, stage 4: the compiler and the preview

Status: built; its exit's counted run passed 9 November 2026, its two live
checks awaiting the owner's key ([V2-stage4-exit.md](V2-stage4-exit.md)). Design revision 2, 23 October
2026; revision 1 was reviewed adversarially, and section 1.1 says what the
review changed.
Companion to [V2-plan.md](V2-plan.md) (sections 2, 4.2, 4.3, 4.6, 7, 8) and
[V2-architecture.md](V2-architecture.md) (sections 2, 4.1, 4.4, 4.7, 6, 7,
8). Where this page is more exact than those, this page holds; where it
differs, it says why (section 2).

---

## 1. What stage 4 delivers

The plan's row for stage 4:

> Spec → ForgeIR v2 for every determinate item; proven-equal alternatives;
> the 3D preview; geometry comparison of two drafts; the coloured brief.
>
> **Exit test:** 10,000 random specs, interacting items included: all pass,
> no mutant survives, the impossible ones end CAN'T, graded against the
> generator's model. Every determinate corpus part builds with no model
> call after the spec. V1's 27 false passes caught both ways.

**In one paragraph.** A confirmed spec goes in; a ForgeIR v2 document comes
out, written by code with no model, the same document every time
(`forge_plan`). Each item is built by its first construction; where
OpenCascade refuses one, the next construction for that item is tried, and
every alternative is proven, here and in its own tests, to make the same
solid as the first. The built part is then judged by stage 2's checks,
which never see the document. So a part reaches a person only when two
programs written independently from the same field definitions agree on
it, and when every file shipped agrees too. The same compiler gives the 3D
preview the person confirms against, and two drafts of one brief are
compared as the solids they make.

| Deliverable | Done when |
|---|---|
| The compiler (`forge_plan`) | Every determinate item of every kind but `region` (section 2.2) compiles to ForgeIR v2 steps that list the items they build; the document is a pure function of the confirmed spec |
| Extrusions and revolutions | Placed by the solver, made by the oracle, drawn by the generator, compiled and built: as first bodies and standing on flat faces, with things placed on their flat ends (section 6) |
| Proven-equal alternatives | Each item kind's constructions in a fixed order; each alternative proven equal to the first (section 5) and tested by building both; a build that refuses one tries the next (section 8) |
| The build and the verdict | `forge build` takes a confirmed spec to a judged part and its files with no model call: the oracle, the plan, the build, the judge on every view, the files re-opened, one ending (section 9) |
| The 3D preview | The spec page shows the compiled draft in 3D, turnable, each item tinted with its colour in the coloured brief, built in seconds at no cost (section 10) |
| Two drafts as geometry | Where stage 1's comparison finds differences, both drafts are compiled and built and compared as solids; a difference only in how the part is written is dropped, a real one is said in the first draft's terms (section 11) |
| The coloured brief | Done in stage 1 (`forge_cli/spec_page.py`); kept, its colours shared with the preview |
| Letters | Their outlines come from the pinned font, exactly, for the compiler, the oracle and the generator, each with its own layout code (section 7.1) |
| The generator covers every kind | Random specs include every kind the compiler builds, the cases the definitions allow at their limits (flush, tangent, overhanging, round sides of rods, tubes, bores and hollows), and briefs whose words the values cite (section 12) |
| Fast enough | The judge on an exact generated part in seconds, not a minute (section 13) |
| Exit test | Section 14 |

### 1.1 What the review changed

| Finding | This revision |
|---|---|
| Comparing drafts by the oracle's points: a bounded item (a thread's hand, a rounding's radius) can never differ, so a misread hides | Drafts are compared as **built solids**, exactly (11): booleans both ways; and a stage-1 difference touching a bounded item is dropped only if its own fields agree too |
| Letters: the compiler and the oracle sharing one layout function, and one unchecked glyph table | Each program does its own layout from text.md; the table is checked against fontTools' own areas and boxes of each decomposed glyph, and composite, overlapping and nested glyphs are handled by nonzero winding (7.1) |
| The exit test graded too coarsely, threw away hard mutants, counted UNABLE as fine, and never drew the definitions' limit cases | Graded by surface deviation both ways plus points in every copy's box (12.3); "same shape" decided exactly (14.1); UNABLE fails the exit unless declared in advance (14.1); the generator draws flush, tangent, overhanging and round-side cases on purpose (12.2) |
| Impossible specs can never end CAN'T: every generated value is assumed, so a CAN'T routes back as a fault | The generator writes a brief and cites its words for every value (12.1); the test requires `cant` with the generator's reason |
| The ending ignored what the judge left unchecked; a non-CAN'T oracle error unspecified; the oracle ran after the build | VERIFIED EXCEPT with the list; any other `OracleError` holds; the oracle first (9) |
| Edge references: merged faces carry a rounding onto the next item; piece counts too tight; no zero pieces; the solver's `edges_of` covers only bodies; circles not held to their centre; tangent closure unchecked; a pocket's floor named by the wrong end | Each query held to its edge's **extent**; counts from the layout's own crossings; a set may allow zero pieces per edge with at least one in all; the compiler's own complete edge sets; a circle's centre test; closure additions must be named edges or are refused; every face named by its plane (4.6, 4.7) |
| Shells: cylinders' and domes' own roundings not followed; floor rule wrong; the hollow carried into a host; the offset alternative unfounded; one rounding in two places | Rows for every body (4.8); the gap only where two walls of different thickness meet at a rounded edge; the hollow flush, carried only by proof; the offset alternative dropped; a rounding split into its two steps |
| A feature standing inside a bore built from the wrong plane; a countersink in a bore misread | Inside: from the tangent plane out, within the bore (4.5); hole.md's countersink (4.4) |
| Through-cut depths copied a solver fault over an overhang | The solver's material model over overhangs fixed, and outlines' nearest and farthest points defined (6.3) |
| The box proofs: items made before ignored; too strict for a strap's rounded ends; material, hosts, tubes and letters not covered | Proofs by the exact regions a rounding changes (5.5); every item made before or after counted; the host's actual solid, the least material, letters' boxes (5.2, 5.3) |
| Pointed cones always held: the apex is unsure | The oracle bounds a ball of its tolerance round an apex (13.4) |
| Threads: the groove not kept within the rod; "exact" claimed for an approximation; the volume formula | Clipped to the rod between its ends; both constructions within a stated bound of the true helicoids; Pappus for a helix (7.2) |
| Letters touching, overlapping, running off the face | Letters joined before cutting; the ink, not the line's box, held to the face and to what is on it (7.1) |
| Preview: no preview when there are questions; the fallback silently drops items; a thread can't be stopped | Items with issues are preview gaps; every item the fallback can't build is listed; the preview runs in its own process (10) |
| Build loop: an earlier item's choice never revisited | A bounded search over the earlier items that meet the refused step (8) |
| Performance claims unmeasured; quadratic names lookups; exports of millions of triangles; float determinism | Measured before and after (13); names indexed; export deflection with a floor; literals rounded (4.1) |
| Extrusions and revolutions left out, though the row says every determinate item, and false passes 17 and 20 need them | In, as section 6 |
| Every determinate corpus part narrowed to a few specs | The 92-brief validation suite drafted as V2 specs by hand, beside every corpus spec the tests hold; the spec writer's own drafts of all 545 recorded briefs when you run it (14.2) |
| Second kernel and files judged on one part in 50 | On one in 10, each with its denominator, and on every part `forge build` makes (2.7) |

### 1.2 What the review of section 9 changed

Section 9 was written out in full before it was built, and reviewed
adversarially on its own.

| Finding | This revision |
|---|---|
| A one-sided tolerance (10 mm +0.1/-0): the part made at the nominal lies on a limit, and every such part is held | Each size made at the middle of its band, by every program that makes geometry; checks held to the written limits (9.6) |
| The check compiler reaches some nominals through the judge's placement: made sizes there would shift a one-sided band | Every check's nominal is the made size, and a stated tolerance half its band either way: the written limits whichever way the nominal was reached (9.6) |
| The spec checks settle fits and throughs at the nominal, the part is made at the middle | The spec checks read the made size too; a size made at or below 0 is refused (9.6) |
| Exit codes collided with argparse's and the CLI's own 2 | 2 is every refusal and error, as for every Forge command; UNABLE 3, CAN'T 4 (9.1) |
| "Confirmed by a person" could be written by anyone, and its digest recomputed | A person's confirmation is sealed with the installation's key; without the seal a spec builds as a draft (9.7) |
| Through-holes the oracle doesn't count, items no probe is drawn round, and fields other checks hold: VERIFIED would be unreachable, or VERIFIED EXCEPT meaningless | What the spec leaves unchecked makes VERIFIED EXCEPT; what the detectors don't count, and fields held otherwise (`NotChecked.held_by`), are listed and change no ending (9.3) |
| The meshes' floor of 0.002 mm couldn't show the tightest tolerances, and "the smaller side" is wrong once sizes are made at the middle | A twentieth of the smallest half-band, from 0.0005 to 0.01 mm; a tolerance finer still holds the part on its meshes, saying so (9.4) |
| Whether the implicit view is judged like the others | Only by stage 3's agreement test (9.2.4) |
| The probes' tolerance not one number, so a mesh's probes would always be inconclusive | One number, given to the draw and the run alike (9.2.2) |
| Mesh files' views named `stl-file` and `3mf-file`, which the capability table refuses | Every mesh file is a `mesh-file` view; the 3MF moved back by the shift Forge wrote (9.2.5) |
| A build written over an earlier build, or over the user's files; a spec name as a path | A fresh folder each build, files created afresh, the verdict written last and whole; file names of ASCII letters, digits and dashes, Windows' device names refused (9.1, 9.4, 9.5) |
| A kind the compiler doesn't write yet stopped the plan with an error | It is a gap, and the run ends UNABLE for it (4.9) |

## 2. Decisions, and where this page differs from the plan

**2.1 The compiler reads the solver's layout, never the judge's.** The
confirmed spec carries the layout the placement solver solved
(`ConfirmedSpec.layout`, `forge_spec.placement`), and the compiler builds
where it says: every copy's point, direction and axes, every face's
material. The judge places the part again from the definitions
(`forge_checks.place`) and never reads the layout or the document. A
compiler copying a wrong layout builds a part the judge's own placement
rejects (stage 2 planted exactly that and caught it, V2-stage2.md 8.2).
Where this stage finds the solver wrong (6.3), the solver is fixed, and the
judge stays as it was unless it is wrong too.

**2.2 Every kind but `region` is determinate.** Block, cylinder, tube,
sphere, cone, extrusion, revolution; hole, slot, pocket, text; boss, post,
tab, rib; fillet, chamfer, shell, thread. A region is designed later, by
the construction agent (stage 5): the plan lists it as a gap, and the run
ends UNABLE for it until then. Two narrower gaps, each with its reason
(4.9): a shell where two walls of different thickness meet at one of its
body's own rounded or chamfered edges, and a rounding no construction of
section 5 can make (the run says which edge and why).

**2.3 New ForgeIR v2 operations: `profile_outline`, `text`, `thread`.** The
architecture has them arrive "with the stages that need them", each with
its builder, its after-check and its agreement entry, or the decoder
rejects it. An extrusion's or revolution's outline is lines and true arcs,
which no V1 profile draws (V1's sketch rounds corners; it has no arc about
a given centre); letters are quadratic curves; a thread is a helix. Each is
v2-only: down-converted for the implicit kernel to V1's nearest form
(`profile_outline` to a sketch through points within 0.005 mm of the arcs,
its agreement entry bounded by that), or to its input (`text`, `thread`,
with a not-applicable zone: stage 3, 13.2).

**2.4 References name edges by lists of queries, held to their extent.**
Stage 3's edge reference is one query. A spec's edge sets need several at
once (a block's `top` lies between its top and four sides; a joint runs
round every side of a post), and roundings meeting at a corner must be
made in one operation so they run into each other (fillet.md). So a
reference may be a list of edge queries, each side of a `between` a list of
face queries, and a `where` may hold an edge to its **extent** (the
segment or arc it must lie within) and a circle to its **centre**. Each
query keeps its own match, whose least count may be 0 when the list's own
`at_least` is met. The format is extended, not changed: every stage-3
document reads and builds as before.

**2.5 The glyphs are data in the trust core.** The architecture has a
`forge_fonts` adapter "store[ing glyph outlines] in the spec when text is
resolved". Here the outlines of the pinned font are written once, by
`scripts/font_glyphs.py`, into `packages/forge_spec/glyphs.py` beside the
metrics already there (`font.py`), with the font's SHA-256: the data the
spec would store, the same for every reader, needing no fontTools at run
time. The compiler, the oracle and the generator each do their own layout
and geometry with it (7.1).

**2.6 The verdict is stage 4's part of the gate.** The plan's gate (4.7)
also weighs the drawing, the parametric script and the print spec, which
arrive in stage 6. Stage 4's verdict (9.3) is the rest: every check on
every view the capability table allows, face accounting, topology and
volume, fresh probes, second-kernel agreement, the shipped files re-opened.
Its endings are the plan's: VERIFIED, VERIFIED EXCEPT, BUILT TO DRAFT,
HELD, CAN'T, UNABLE (WAITING is for model calls and questions, which a
build has none of).

**2.7 The exit test's views.** On all 10,000 random specs the exact B-rep
is judged in full; the second kernel's agreement and the shipped files
(STEP, STL and 3MF, re-opened and judged) on every tenth, 1,000 of them,
each with its own denominator. Stage 3 measured the agreement test at
about a minute a part, which on every part would add a week of both
cores. Every part `forge build` makes is judged on every view.

**2.8 `forge_plan` is stdlib-only, over the trust core.** The architecture
puts `forge_plan` among L0's standard-library packages. Its own code
imports no NumPy; it imports `forge_units`, `forge_ir` and `forge_spec`
(whose solver and geometry are the layout it reads). It never imports
`forge_checks` (the checks), `forge_eval` (the generator), `forge_occ`
(the kernel it writes for), or `forge_kernel` and `forge_geom` (the second
kernel, which must stay an independent build of its documents).

**2.9 One mutant per spec in the exit test.** "No mutant survives" is
held on one leaf mutant per spec, chosen by the seed, so 10,000 mutants
over every leaf kind; every mutant of every leaf on a few hundred specs
stays stage 2's test. Here the mutants are compiled and built by the exact
kernel, not made from the generator's truth.

## 3. Where it sits

```
 confirmed spec (forge_spec: the spec, the solver's layout, locked by its digest)
   │
   ├─► the oracle (forge_checks, from the spec alone): CAN'T now if the shape can't be made
   ▼
 forge_plan.plan()                L0, no model, no CAD library
   │  Plan: every item's constructions, in order; the gaps
   ▼
 forge_occ.planned.build_plan()   L1: builds; on a refusal tries the next construction
   │  BuildResult, the constructions used, every refusal
   ▼
 forge_cli.build (the verdict)    L3: the judge on the B-rep, the second kernel,
                                      STEP/STL/3MF exported and re-opened; one ending
```

## 4. The compiler

### 4.1 The interface

```python
# forge_plan
def plan(spec: ConfirmedSpec) -> Plan
def preview_plan(report: SpecReport) -> Plan
    # a draft: items with issues, and what stands on or rounds them, become gaps

@dataclass(frozen=True)
class Plan:
    spec_digest: str | None
    items: tuple[PlannedItem, ...]   # in the order the part is made
    gaps: tuple[Gap, ...]
    def document(self, choice: Mapping[str, int] | None = None) -> DocumentV2
    def owner(self, step: str) -> str          # the planned item (4.8) a step builds

@dataclass(frozen=True)
class PlannedItem:
    key: str              # the item's id; a rounding made in two places is "<id>@before", "<id>@after"
    item: str
    kind: str
    constructions: tuple[Construction, ...]    # [0] the definition's own

@dataclass(frozen=True)
class Construction:
    name: str             # "flush", "one_by_one", "carried", "sunk", "early", "flared", ...
    proof: str            # the section of this page that proves it equal to [0]
    write: Callable[[Chain], Chain]   # appends its steps; may be absent for a copy (its proof fails there)
```

The document is made by walking the planned items in the order the part is
made (frame.md, "The order"; `layout.order`), each item's chosen
construction appending its steps to a **chain**: the step holding the part
made so far, and a table of what each item's faces are called in it (4.6).
Its id is the spec digest's first sixteen characters; its one component is
the part; every step lists, in `for_items`, the spec item it builds.

Every number is the layout's or the spec's, in millimetres and degrees,
written as a literal with its unit and rounded to 1e-9 mm and 1e-12 rad
(so the same spec gives byte-identical JSON on every platform, whatever its
`sin` and `cos` round to: tested on the laptop's Linux and here). Step ids
are `<item>.<copy>.<part>` (`holes.3.bore`) and the chain's own
`<item>.join`, `<item>.cut`, within ForgeIR's identifier rule.

### 4.2 Tools, and the part made so far

Each copy of an item becomes a **tool**: a solid of its own, built from
primitives at its place in the frame, exactly the item's points as its
definition gives them, no more. Then:

- a body or a standing feature: the part is the union of the part and every
  copy's tool, in one `union` step;
- a cut: the part less every copy's tool, in one `subtract` step;
- a rounding, chamfer or thread: one step on the part (4.7, 7.2);
- a shell: the hollow is a tool, subtracted (4.8).

The first body is the part's first step.

### 4.3 Bodies

`o` is the copy's point (`Instance.origin`: a body's base centre), `u` its
direction (`Instance.normal`), its axes `Instance.face_axes` (the frame's
for the first body).

| Kind | Tool | Faces (4.6) |
|---|---|---|
| block | `box` from `Instance.lo` to `Instance.hi` | `+x`…`-z`: the box's planes |
| cylinder | `cylinder`, base centre `o`, axis `u`, height `length` | `+end`, `-end`, `side` |
| tube | `subtract` of the outer `cylinder` and a bore `cylinder` from `o − c u` to `o + (length + c) u` (c = 1 mm: built alone, so the bore's ends past the tube's are in nothing), then joined | as a cylinder; `bore` |
| cone | `cone`, base centre `o`, axis `u`, base and top diameters (top 0: a point) | `+end` (none at a point), `-end`, `side` |
| sphere, whole | `sphere` about `o + (d/2) u` as the first body, about `o` standing on a face (sphere.md) | `surface` |
| sphere, dome | `intersect` of the `sphere` about `o` and the `box` beyond the flat face, twice the ball across and deep: from `o − 2r a₁ − 2r a₂` to `o + 2r a₁ + 2r a₂ + 2r u` (one only as big as the ball touches it at its rim and pole, where OpenCascade may leave a sliver: generated part 492, an edge 1.9e-6 mm long) | `-end`, `surface` |
| extrusion | section 6 | `+end`, `-end`, the side's pieces |
| revolution | section 6 | `+end`, `-end` (where the profile has them), the side's pieces |

A tube, cone or dome standing on a face is built alone and joined, so its
bore never cuts what it stands on (tube.md).

### 4.4 Cuts

A cut's tool runs into the material along `−u` (`u` the face's outward
direction at the copy's point), from `start` to `depth`:

- **blind:** to its depth;
- **through:** to the most material under its mouth (frame.md, "The
  material under a face"; for each kind of face, the solver's model, 6.3);
- **start:** 0 on a flat face. Round a side (hole.md): from outside a rod
  or tube, the plane that touches the side at the copy's point, so the
  mouth follows the curve; inside a bore or hollow, the side's axis.

| Kind | Tool |
|---|---|
| hole | a `cylinder` of its diameter (a fit's from the layout's resolved diameters) on the axis through the copy's point, from `start` to the depth. A counterbore: joined with a `cylinder` of its diameter from `start` to its depth. A countersink: joined with a `cone` from its diameter at the face (at the plane that touches the side, round a side) narrowing to the hole's over (D − d)/2/tan(α/2); inside a bore or hollow, also a `cylinder` of its diameter from the axis to that plane (hole.md: no lip of the wall left in front of it) |
| slot | a `profile_slot` (round ends; as long as it is wide, a circle) or a `profile_rectangle` (square ends), in the face's plane, extruded to the depth |
| pocket | a `box` (square corners), or a `profile_rectangle` with its corners rounded (rounded to half its width and length, a `profile_circle`; to half its width only, a `profile_slot`), or a `profile_circle`, extruded |
| text, engraved | a `text` step to its depth (7.1) |

A profile is drawn on a datum plane through the copy's point square to
`u`, its u and v along the face's first and second axes. A slot or pocket
goes into flat faces only (slot.md, pocket.md).

### 4.5 Standing features

On a flat face, a standing feature's tool is its cross-section pushed from
the foot plane along `u` by its height (a boss's `height`, a tab's
`length`):

| Kind | Tool |
|---|---|
| boss | `cylinder` of `diameter`, base at the copy's point, axis `u` |
| post | `box` from `Instance.lo` to `Instance.hi` |
| rib | `box`, `length` along `along`, `thickness` across |
| tab, square end | `box`, `thickness` along `thickness_along`, `width` across |
| tab, round end | the `intersect` of the tab's whole box with the `union` of a `box` `length − width/2` out and a `cylinder` of radius `width/2` along `thickness_along` whose axis is `length − width/2` out (so the half-circle never reaches behind the foot); exactly `width/2` long, the cylinder within the box |
| text, embossed | a `text` step standing out by its depth |

**Round a side** (place.md; the formal shape in boss.md, post.md, tab.md,
rib.md): the feature is its cross-section out to its height, on the open
side of the side's round surface, so its foot follows the curve.

- **On an outside** (a rod's or tube's, a hollowed cylinder's outer side):
  the cross-section's prism from the plane through the side's axis square
  to `u` out to `w + h u` (`w` its point), less a `cylinder` of the side's
  radius along the side's axis and longer than the prism. Every point of
  the result is outside the side's radius and on `u`'s side of the axis:
  the definition's set.
- **On an inside** (a bore, a hollowed cylinder's inner side; `u` points
  towards the axis): the prism from the plane that touches the side at `w`
  out to `w + h u`, within a `cylinder` of the side's radius (their
  `intersect`). A point behind that plane is outside the bore, so the
  result is every point of the cross-section within the bore and no more
  than `h` along `u` from `w`: the definition's set.

### 4.6 Names: what each spec face is called in the part

The compiler keeps, for every copy of every item, a table from each of the
item's faces (the schema's names: `+z`, `side`, `bore`, `+end`, `bottom`,
`inner -z`, …) to the face names OpenCascade's build will carry for it:
`(step, role)` as stage 3 names them (V2-stage3.md 7.2, 9.2). Each entry
is worked out from the face's **plane or surface**, never from which end
of an operation made it: a pocket's `bottom` is whichever of its extrude's
end faces lies in the floor's plane (`start_face` or `end_face`, as the
datum plane's fixed normal and the extrude's mode give it); a box tool's
`+z` is its `z_max`; a cylinder's `+end` is its `top` or `base`, whichever
lies at the far end. A face a rounding made is `(that step, round)` or
`(that step, bevel)`; a shell's inside faces are its hollow tool's. Where
one role covers several faces the table must tell apart, the entry holds
the role's plane faces to the way they face (`where: {normal}`): a
box-like tool made by an extrusion (its vertical edges rounded early, 5.5)
has its four sides all `side`, each named by its role and its normal. The
table is the compiler's alone; the judge never sees it.

Stage 3's names table is made faster for parts with many copies (13.3):
`Names` keeps its face index and an index by `(step, role)`, built once,
so a lookup no longer scans every face.

### 4.7 Roundings and chamfers

A fillet or chamfer item is a `fillet` (radius) or `chamfer` (distance)
step at its place in the order (frame.md), on the part made so far: its
first construction. Its `edges` reference is a list of edge queries, one
per edge of the edge set on each copy of the item it rounds, from the
compiler's own complete table of edge sets (`forge_plan.edges`, written
from edges.md and each kind's page; the solver's `edges_of` covers only
bodies, for its order). Each query:

- is **between** the two faces the edge lies between, each named by 4.6;
- holds the edge by **where**: its kind (line or circle), its direction or
  axis, a point on it or its circle's centre, its radius; and its
  **extent**, the segment or arc the spec's edge is (each piece found must
  lie within it, to 1e-6 mm);
- matches **0 to n** pieces, n one more than the number of the layout's
  copies whose outlines cross the edge (cuts and standing items on either
  face, and letters, counted by their outlines' crossings of the edge's
  line, which the compiler works out from the layout); and the list as a
  whole matches **at least one** piece (`at_least: 1`).

An edge the spec names but whose pieces are all gone leaves its query
finding none; if the whole set finds none, the oracle has already said
CAN'T (it makes the same check from the spec, 9.2) or the reference fails.

The pieces found are then closed under tangency once (stage 3, 9.4). Each
edge the closure adds must be one the definition names (edges.md: where an
earlier rounding has rounded a face's corners, the set "follows the face's
edge as that rounding left it", so the compiler writes those arcs into the
list too, between the face and the earlier rounding's `round` faces); an
edge the closure adds that no query names is a refusal.

Per edge set:

| Edge set | The queries |
|---|---|
| a box-like item's `vertical`, `top`, `bottom`, `all` | between each pair of its faces the set names; arcs of earlier roundings of the same item between them, as above |
| `bottom` of a body standing on a face | only the stretches of its base outside the face's outline (edges.md), each between its base and its side |
| a round body's `top`, `bottom`, `both`; a tube's `outer`, `bore` | each rim circle between its end and its side or bore |
| an extrusion's or revolution's | section 6.4 |
| a hole's, slot's or pocket's `top` | between its tool's walls (with a counterbore or countersink, those walls) and the face it is cut into |
| a pocket's `bottom` | between its walls and its floor |
| a dome's `bottom` | between its surface and its flat face |
| a tab's `top`, round end | the two half-circles between its rounding and its broad faces |
| `joint` | between the standing item's sides and the host's face, on each side not flush with the face's edge; where it overhangs, between its base and the host's sides (edges.md) |
| an edge set of a hollowed body bordering an open face | both rims: between the open face's ring and the outer walls, and between it and the hollow's walls (shell.md, edges.md) |

**Other constructions** (section 5.5): made early, on the rounded item's
own tool before it is joined; and, for a cut's rim, a flared tool.

### 4.8 Shells

A hollowed body is made whole first (frame.md, "The order"): the body, its
own roundings that border no open face, the hollow, the roundings of its
rim. A rounding whose edges are of both sorts is two planned items
(`<id>@before`, `<id>@after`), each one step, one each side of the hollow.
The hollow is a tool subtracted from the part made so far, every face of it
named `inner …` in the table. With every wall `t` thick and the floor `f`
(`t` when not given):

| Body | Hollow |
|---|---|
| block | a `box`, each side in from the block's by its wall's thickness, flush with every open face (5.2 may carry it out through one) |
| block with its own roundings or chamfers | the same box, each of its edges under a rounded edge of the block rounded by `r − t`, under a chamfered one chamfered by `c − (2 − √2) t`, sharp where that is 0 or less: the points at least `t` from each wall, both faces of the rounded edge being `t` walls |
| cylinder | a `cylinder`, radius `t` less, its ends in by their walls, flush with an open end |
| cylinder with its rims rounded or chamfered | the same, its rims under a rounded rim rounded by `r − t` (chamfered `c − (2 − √2) t`) |
| sphere, whole | a `sphere`, radius `t` less, the same centre |
| dome | the `intersect` of a `sphere` `t` smaller about the flat face's centre and the half-space `f` above the flat face (the flat face open: from the flat face) |
| dome with its rim rounded or chamfered | the same, its rim rounded by `r − t` (chamfered `c − (2 − √2) t`), where the floor is `t` too |

Where an edge of the body is rounded or chamfered between two walls of
**different** thickness (a block's floor edge with `f ≠ t`, a dome's rim
over a floor of its own), the hollow there is what the two walls' distances
leave (shell.md), not an offset of either: that hollow is the one gap of
this table (4.9). A rounded edge between two `t` walls (a tray's vertical
edges, whatever its floor) is in the table.

### 4.9 What the compiler refuses, and gaps

`plan` raises `PlanError` (naming the item and the field) for a spec it
must not plan: one whose layout has an issue left, or one not locked.
(`preview_plan` instead makes each item with an issue a gap, with what
stands on it, is cut into it or rounds it.) A determinate item no
construction can be written for is a **gap**, never a guess:

- a shell's hollow where walls of different thickness meet at a rounded or
  chamfered edge of its body (4.8);
- a rounding none of whose constructions' proofs hold where its first was
  refused (section 8 says when that is known);
- an item of a kind whose constructions aren't written yet, and whatever
  depends on it (none now: threads are compiled since 7.2; a region is the
  construction agent's, stage 5).

A gap's item can't be built; the run ends UNABLE for it, by name, with the
rest built and previewed.

## 5. Proven-equal alternatives

An item's first construction is its definition's (section 4). When
OpenCascade refuses it (section 8), the next is tried. There are two
exceptions: a hole into a round side from outside (5.2), and a cut through
the next face (5.2, its far end), whose definition's end touches the face
it comes out of. The hole's definition's
tool touches the side along a line at its mouth. OpenCascade's boolean
may refuse that tool, or, worse, cut it wrong without a word: held-out
seed 10,890 warned, and seed 10,517 left its hole's plug in place. So
there the carried construction goes first where its proof holds, and the
definition's goes after it. Each alternative
makes **the same set of points** as the first, outside the zones the
definitions themselves leave bounded (a thread's run-out, where roundings
meet: the oracle's zones), and within those zones' bounds. The proof is
written here; a test per alternative builds both on parts where it applies
and finds the same solid (the symmetric difference's volume within
OpenCascade's volume tolerance outside the zones, the same faces) and,
where its proof fails, finds it isn't offered (section 15). No alternative
is approximate. The plan's "when an alternative can't make the same shape,
the difference becomes a question" has no case in this stage: such an
item is a gap.

The proofs use the layout and the plan's own tools, never the built part.
`P` is the part made so far; every added item's tool lies within its box
(the compiler makes the boxes of every tool it writes, letters included:
their ink's box, 7.1), so `P` lies within the union of the boxes of the
tools added so far.

### 5.1 All copies at once, or one by one

`P − (T₁ ∪ … ∪ Tₙ) = (…(P − T₁) − …) − Tₙ` and the same for `∪`: set
algebra. The first construction makes one boolean of every copy's tool;
the second, one per copy in copy order. OpenCascade fails differently
between the two (a tool touching another's face), so each is worth trying.
Every cut and every add with more than one copy; and the same for the
carried (5.2) and sunk (5.3) tools, one copy at a time.

The constructions of an item, in the order they are tried: its
definition's; carried (a cut), sunk (a standing feature) or cut (a dome);
one by one; carried or sunk one by one; a hole's, its round tools turned
about their axes (5.7). A rounding's: on the part made so
far (its definition's); early (5.5); as its regions (5.6). An alternative
whose proof holds for no copy isn't offered: it would make the first again.

### 5.2 Carried into air

A cut's tool `T` carried on past its mouth, or past the far side of a cut
through, by `c` = 0.05 mm along its axis is `T ∪ E`. If `E ∩ P = ∅`,
`P − (T ∪ E) = P − T`. Proof: `E`'s box meets the interior of no added
tool's box (all of `P` is within those), except the host's, which it meets
only across the face it leaves (the mouth's plane, or the far side's: `E`
lies wholly on the open side of it, beyond the host's box). A shell's
hollow carried out through an open face: the same, the host being the
hollowed body. Where any other box meets `E`, this alternative isn't
offered for that copy. Carried, no face of the tool lies in one of the
part's, so the boolean has no coplanar faces to settle.

As built: `E` is the cut's widest outline (a counterbore's or a
countersink's included; a countersink carried runs on into the air as
wide as its mouth) from its face out by `c`, and for a cut through,
its outline from where it comes out on by `c`; each is carried where its
box meets no added box, the mouth and the far side apart. A shell's hollow
isn't carried yet. The cut's own box, which later proofs read, is the
cut's: what is carried is in air.

A hole into a round side (hole.md) is carried too. The host's box holds
the side's air as well as its material, so for the host the box test is
replaced by an exact one from the side's own radius `R`, its axis and the
hole's radius `r`; every other added tool's box must still meet `E`'s box
(the box round `E`'s cylinder) in no interior. The host's tool lies within
`R` of the side's axis (a rod's, a tube's or a boss's cylinder, a tube's
bore taken from it), and nothing else is made under the host's name.

- **Past the mouth, from outside:** the flush tool starts on the plane
  that touches the side along the line through its point, and `E` (its
  widest outline, out by `c`) lies beyond that plane. Every point of `E` is
  at least `R` from the axis, so `E` meets the host only on that line,
  within the tool's own mouth.
- **Past the far side of a solid rod or boss:** the hole comes out where
  the plane on the far side touches it, `2R` in; `E` lies beyond that
  plane, the same.
- **Past the far side of a tube's wall, or a hollowed cylinder's, from
  outside:** the hole stops where its rim reaches the bore, its far end's
  centre `h = √(r_in² − r²)` from the axis (hole.md). `E`, its outline from
  there by `c` towards the axis, lies within `r_in` of the axis when
  `h > c` (each point's distance² is at most `h² + r² = r_in²`), touching
  the bore only at the two points where the tool's rim already does. A
  tube's bore runs its whole length (and past its ends there is no tube);
  a hollowed cylinder's hollow must hold `E`'s span along the axis, `r`
  each way of the hole's point, strictly inside its cavity's. Otherwise
  the far side isn't carried.
- **Past the far side, out from a bore or a hollow:** the hole comes out
  where the plane touching the outside (`r_in` plus the wall from the
  axis) touches it; `E` lies beyond that plane, as past a mouth.
- A hole into a bore or a hollow starts at the side's axis (hole.md): its
  mouth is in air already, and isn't carried.

Found by the held-out run's seed 10,890 (V2-stage4-exit.md): a 1.528 mm
hole through the wall of an 81.5 mm tube with a 62.5 mm bore, its flush
tool tangent to the outside along its mouth and to the bore at two points
of its far rim. OpenCascade's subtract warned
(`BOPAlgo_AlertSolidBuilderUnusedFaces`), and with no other construction
offered the item was UNABLE; carried past either end, it builds.

Seed 10,517 showed the same tangency failing silently. A 4.55 mm blind
hole 1.85 mm into an 88.9 mm tube's wall, cut flush, raised no flag. But
the result was two solids: the part, and the hole's plug beside it,
touching along six edges (29.8 mm³ too much). The judge held the part,
so no wrong part was released. Two changes fix it at the root:
- **The carried tool goes first** for a hole into a round side from
  outside (section 5's opening), so the tangency doesn't arise wherever
  the air past the mouth is proven.
- **The part stays one solid** after each item's join or cut (section 8,
  step 2). Where the definition's tool is still used, a cut misread this
  way is a refusal, and the next construction is tried.

**Past the far end of a cut through the next face** (V2-stage4b-0c.md,
3.5), `E` is shown air by the preview itself, not by boxes. Its
definition's end is where it first comes out of the part all across its
mouth, so it touches the face it comes out of: across it, out of a face
square to it; along a line; or at a point, out of a face at a slant or a
curved one, where the boxes round `E` meet the host's or another's box
across that face and prove nothing. The preview (`forge_occ.resolve`)
finds that depth on the part made before the cut, built, from the
stretches of material under its whole mouth along its axis; it now also
asks that the next stretch begin at least `2c` past it, or it finds no
depth (and says so). So under all its mouth `P` holds nothing from that
depth to `c` past it: `E ∩ P = ∅` on the part made so far, which is the
part the preview built, the same items made in the same order (any
construction of each makes the same points). A cut through the next face
is carried first, as a hole into a round side is (section 5's opening).
Found by generated part 4944: a hole through the next face from a cone's
side, out of a flange's underside 42 degrees from square, its end touching
the underside at a point. Flush, or carried at its mouth only (the body's
box over its end), OpenCascade left a face across the hole's end without
a flag (the judge held the part: face accounting, topology); carried past
it, it builds. The generator draws a cut through the next face only where
its own shape has that air past it.

### 5.3 Sunk into what it stands on

A standing item's tool `T` carried into its host by `c` = 0.05 mm behind its
foot is `T ∪ E`. If `E ⊆ P`, `P ∪ (T ∪ E) = P ∪ T`. Proof, all from the
layout: `E` lies within the host's own solid as made (a box host: within
its box; a round host: within its radius and between its ends; a hollowed
host: within its walls, the least wall under the foot more than `c`), the
least material under the foot (`material_at` over the foot's outline, not
the face's centre's `depth_below`) is more than `c`, and `E`'s box meets
the interior of no cut's box made so far. Otherwise not offered. Round an
outside, the first construction (4.5) already reaches into the host; its
alternative is the prism from `c` under the side's surface where that is
lowest under the foot, joined without the subtraction, offered when the
same proof holds and the side's wall is thicker there than the foot's
sagitta plus `c` (so `E` never reaches a bore).

As built: on a flat face, for a boss, a post, a rib, a straight-ended tab
and a block standing on it as a feature does (a body standing on a face
may overhang it, and isn't sunk): `E` within the host copy's box and `c`
clear of its sides (a foot flush with the face's edge, or a boss tangent
to it, would sink a face of the tool onto or tangent to the host's side:
generated part 3's boss, so sunk, left the union an open shell), the
least material under the footprint (`least_material_under`, the face's
own depth model) more than `c`, and no cut's box meeting `E`. The feature's
box, which later proofs read, is its own: the sunk part is within `P`
already. Round a side, and a round-ended tab, not yet offered.

### 5.4 A dome cut instead of kept

The dome of 4.3 is the sphere `∩` the box beyond its flat face; the second
construction is the sphere `−` the box on the other side,
`o − 2r a₁ − 2r a₂ − 2r u` to `o + 2r a₁ + 2r a₂`, which holds all of the
sphere outside the first box: `S ∩ B = S − B'` when `S ⊆ B ∪ B'` and the
two boxes meet only on the flat face's plane.

### 5.5 A rounding made early, or a flared tool

The definition rounds an item's edges on the part made so far. Rounding
instead the item's own tool before it is joined (early) gives the same set
when the regions the rounding changes meet nothing else:

- **An outside edge** (a body's or standing feature's own): the rounding
  takes away `K`, the material between the round and the edge, a region
  known exactly from the edge's two faces and the size (for faces at right
  angles, the corner square of side `r` along the edge less its quarter
  disc; for a chamfer, the corner's triangle). Made late it gives
  `(T ∪ A) − C − K`; early, `((T − K) ∪ A) − C`, `A` everything else added
  and `C` everything cut (before or after, since cuts commute with taking
  `K` away). They are equal when `A ∩ K = ∅`: no other added tool's box
  meets `K`'s box's interior (a body stacked flush on the item meets `K`'s
  box only on a plane, so the rounding stops there, exactly as the oracle
  makes it). And the edge must exist as the item's own fields make it: no
  added item covers it (a post standing flush over a block's top edge
  covers that stretch, and there is no edge to round there; early would
  round it anyway), proved by the same test on the edge's own box.
- **An inside edge of a cut** (a pocket's floor edge): the rounding fills
  `F`, the corner between the round and the edge. Early, the tool's own
  outside edges are rounded, so the cut leaves `F`. Equal when `F ⊆ P` before
  the cut: `F` within the host's solid as made and no earlier cut's box
  meeting it.
- **A cut's rim** (its `top` edges, an outside edge of the part): the flared
  tool is the cut's tool joined with the region `K` the rim rounding takes
  from the host round its mouth (for a round hole, the revolution of the
  corner's region about its axis; for a slot or pocket, the corner's
  region swept round its outline). Equal when `K ⊆ P` (within the host's
  solid as made, no earlier cut's box meeting it) and no other added box
  meets `K`.

Where it applies, and why it matters:

- a block's `vertical` edges rounded by `r`: early, the block's tool is
  the `extrude` of its rectangle with its corners rounded by `r` (to half
  its width, a `profile_slot`: a strap whose ends are fully rounded, which
  OpenCascade's fillet refuses at exactly half the width and which is V1's
  false pass 27). A strap's holes on its centreline, inside its rounded
  ends, meet no `K` and change nothing: the test is the region, not a box
  round the edge.
- a body's `top`, or `all`; a round body's rims: the same operation on the
  tool alone. Never a `bottom` of a body standing on another (its base is
  joined, and only where it overhangs does it have an edge: early would
  round the joined stretch too).
- an edge set that the item shares with a body stacked flush on it
  (where late, OpenCascade's merged faces carry one edge across both items
  and the extent test refuses it).

As built in this stage, the vertical edges of a block, a post, a rib or a
straight-ended tab (each copy a body or on a flat face, the item not
hollowed): its tool is the `profile_rectangle` of its section with a
`corner_radius` (to half its shorter side) or a `corner_chamfer` of the
rounding's size, extruded from its low end to its high end, its sides
named by their facing (4.6) and its corners noted as the rounding's faces,
so a later rounding of a face's edges follows them (4.7). Offered where no
other tool added before the rounding meets the box of `K` at any of the
edges, none meets the edge's own box (shrunk at its ends by 2e-9 mm, so a
body stacked flush, touching only an end, doesn't count), and no earlier
rounding of the item has rounded one of the edges. Made early, it is made
before a rounding of the item's other edges that the order puts before it
(a block's top filleted, then its vertical edges chamfered: OpenCascade
runs the chamfer on into the fillet's own mitre, which edges.md leaves
unrounded, and the reference refuses the edges no query names). The two
orders differ only where the roundings meet, round the item's corners, and
there the oracle's zone takes away in the inner form all either rounds and
keeps it all in the outer: what is made there is within its bounds, and
the accounting holds it to them. The rest of 5.5 (a body's `top` or `all`,
a pocket's floor, a cut's rim flared) is not yet offered.

### 5.6 A rounding made as its regions

Along a straight edge between two flat faces at right angles, a rounding
changes exactly one region (5.5): taking an outside edge away, `K`, the
corner's square of the rounding's size less the quarter disc about its far
corner (a fillet), or the corner's triangle (a chamfer); filling an inside
edge, `F`, the same on the air's side. Made so, a rounding is the part less
every `K` (or with every `F`), each a prism along its stretch of edge: the
square's box less the round's cylinder, or the triangle's sketch pushed
along the edge; one boolean each (neighbouring regions overlap round a
corner, which OpenCascade settles less surely in one). Along each stretch
it is the definition's own round. Where stretches meet (a box's corner, a
post's, where a joint runs off a face under an overhang) the definitions
leave the shape to the oracle's zones, which take all of what either
rounding rounds away in the inner form and keep it all in the outer: the
prisms there are within them. The reference parts the oracle is tested
against are made the same way (`tests/v2_reference.py`).

Offered for a box-like item's own edge sets (block, post, rib, straight
tab; each copy a body or on a flat face; not hollowed; no earlier rounding
of its faces' corners to follow, 4.7) and for the joint of a box-like item
standing on a rectangular flat face: its sides within the face (a side
flush with the face's edge has no corner), and under where it hangs over
the face's edges, between its underside and the host's side. The proof:

- taking away: as 5.5, no other tool added so far meets `K`'s box and none
  covers the edge; the prism reaches 0.05 mm past each face into air shown
  clear by the boxes (its margins), and as far past each end of its
  stretch where that air is clear (else it stops at the end);
- filling: no tool but the two it fills between meets `F`'s box, no cut
  made so far meets it with its margins, and its margins, 0.05 mm behind
  each face, lie within those two tools' boxes.

Its faces are noted on each copy as the rounding's (the cylinders' or the
bevels'), so a later rounding follows them as it would OpenCascade's.
Where OpenCascade's own fillet can't run round a joint under an overhang,
this makes it; a fillet's cylinder meets the faces it rounds tangentially,
which OpenCascade's booleans sometimes warn of, and the build loop then
goes on to the next.

### 5.7 A hole's round tools turned about their axes

A cylinder or a cone turned about its own axis, by any angle, is the
same set of points: `R(T) = T` for a turn `R` about the line it is
round. OpenCascade makes each with its seam (the one edge along its side)
and its end circles' vertex where its frame's first axis points, and a
boolean can go wrong for where they fall: generated part 2231, a hole
through the next face from the far face of a post standing round a rod's
side, out into another hole's bore, and 4599, one from a dome's surface
out of its flat face at its middle, each warned of flush (the subtract's
"bad positioning"), and of carried while only its mouth was, and with an
offset of a tenth of a millimetre, or a latitude half a degree off, each
built. So a hole's last construction is its definition's with each
cylinder and cone it makes turned a quarter turn about its own axis, a
`transform` written after it; what takes the tool takes it turned, and its
faces keep the names its own step gives them (a transform moves names with
the faces). Offered for every hole, always: its bore is a cylinder. Tested
as every alternative is (the same solid, the same faces), and on those two
parts, which build so where flush warns (2231 with the hole it comes out
into made by its definition too; tests/v2_regressions.py); carried past
their ends now (5.2), they build first.

## 6. Extrusions and revolutions

### 6.1 The shapes

The definitions (extrusion.md, revolution.md) define both as the first
body; "standing on a face, it would run out of the face, the outline in
the face's own axes from the point `place` puts it at: not yet built". This
stage builds that, as the definitions describe it, and the pages lose their
"not yet" status:

- **extrusion:** the outline, in the plane across its axis, swept along it
  by `length`. As the first body, its -end in the plane through the origin
  across `axis`, the outline's coordinates along that face's two axes (for
  Z, x then y), from the origin. Standing on a face: its -end on the face,
  the outline's coordinates along the face's two axes from the point
  `place` puts it at, its axis out of the face.
- **revolution:** the half outline turned about the axis. As the first
  body, about the frame axis through the origin, heights from the origin.
  Standing on a face: about the line out of the face through the point
  `place` puts it at, heights from the face (an outline that reaches below
  height 0 is turned back: "a body may overhang the face it stands on, but
  must meet it" holds, and nothing reaches behind the face).

### 6.2 Faces, and placing on them

- **An extrusion's ends** are its outline: a flat face of a new shape, an
  **outline face**, alongside rectangles, discs and rings. An item on one
  must lie wholly within the outline (place.md): the solver and the judge
  each test it exactly, the item's outline (rounded rectangles and discs)
  against lines and arcs. Positions on it are measured as on a rectangle
  (place.md: an edge is where the face ends along that axis, the
  outline's extreme), its centre the outline's box's centre. The material
  under an end is the extrusion's length.
- **An extrusion's side** is its outline's segments, each a flat face or a
  round one: nothing is placed on them, for now (they are closed with the
  reason, as a cone's side is).
- **A revolution's ends** are where its outline runs straight across the
  axis at its greatest and least height: a disc or a ring, placeable as a
  cylinder's are. The material under an end, at a distance from the axis,
  is the outline's height there down to where it leaves the material (a
  new depth model, worked out from the outline's segments exactly).
- **A revolution's side**: closed, as a cone's.

### 6.3 The solver, put right where it was wrong

Two faults the review found, fixed in `forge_spec`, with tests:

- **The material over an overhang.** frame.md: the far face of an item
  standing on a host has, at a point over the host's face, the host's
  material under it too; over the overhang, only the item's own. The
  solver gave the whole far face the item's own height alone (so a hole
  through a shelf and the plate under it was cut too shallow).
- **Outlines on varying material.** `material_at` and `most_material_at`
  took a disc's radius. For a slot's, pocket's or letters' outline on a
  cone's end, a dome or an overhang, the least material is at the
  outline's farthest point from the face's centre, the most at its nearest
  (the centre itself when the outline covers it): both now computed for
  the outline, not a disc round it.

As built:

- **Footprints.** `least_material_under` and `most_material_under` take a
  footprint: the item's outline as parts (rectangles and discs: their
  farthest and nearest distances from the face's centre exact), or an
  outline of lines and arcs (an extrusion or a revolution standing on the
  face: its farthest point, and its nearest, 0 where it covers the centre).
  A blind cut's depth is held to the least under its own mouth (a hole's
  bore, a counterbore's or countersink's disc, else its outline); the views
  draw a cut through to the most under its mouth, as the planner cuts it.
  `material_at` is the least under a disc (a point, radius 0); the disc-only
  `most_material_at` is gone.
- **`Over`.** A standing item's far face keeps its own material
  (`depth_below`, `depth_model`) and, in `over`, the face it stands on and
  where its centre is on it. Under a footprint wholly over the host's face,
  the least is its own with the least of the host's under the footprint
  added where its own runs right down to its foot (`add_material`: a
  constant own, a cone's within its smaller end, a revolution's where the
  line runs right through it); under one reaching over the overhang, its
  own. The most: its own, or, where the footprint meets the host's face,
  its own with the most of the host's added, whichever is more. Where the
  far face lies wholly over a host face with the same material under all
  of it (`uniform`), the two are simply added (a stack of bosses stays one
  number); round a side, the side's material is under all of it, as before.
  A hollowed body's far face has its wall alone.
- **`Less`.** A pocket's floor keeps the face it was cut into, where its
  centre is on it, and its depth: the material under a footprint on it is
  what was under it there, less the depth (it was the least under the whole
  pocket, so a hole through the floor of a pocket over a host and an
  overhang was cut too shallow over the host).
- The walk down a stack of faces (a far face, its host's, a floor, what it
  was cut into, ...) is a loop, not recursion: 2,000 stacked items are
  placed as quickly as one.
- A reference part pins it end to end: a shelf and a disc each over the
  plate's edge, holes through each over the plate and one across its edge,
  a pocket in the shelf with a vent through its floor: the oracle, the
  plan, the build and the second kernel all agree with the part made by
  hand from frame.md.

The judge's placement already had both right (`forge_checks.place`,
`Over`, `Less`), but for a revolution: its far end took its host's
material only when it stood wholly on its host. Its `Over` now takes a
`Turned` too, its host's material added where the line runs right through
it (the same rule as the solver's), and its brute-force test draws turned
parts among its random materials. The two agree but in one corner the
solver alone is conservative: through a cone's wide top, straddling both
the edge of the host it overhangs and its own smaller end, the solver may
go deeper than the judge (the host added wherever the mouth meets the host
and reaches inside the smaller end, not only where both hold at once);
the judge then says so. Their tests and the solver's are held to each
other as before (`tests/v2_layouts.py`).

### 6.4 Edge sets

- extrusion `vertical`: each corner of the outline (where two segments meet
  not tangent), the edge along the axis there; `top`, `bottom`: every edge
  round the +end, the -end; `all`.
- revolution `top`, `bottom`: the rims of the +end and the -end.

Their queries are as 4.7's: between the end face and each side piece.

As built: a rim is an edge only where the end meets the side next to it at
an angle (edges.md: an edge is where two faces meet at an angle); where the
side runs on smoothly into the end (a knob's rounded-over top) there is
none, and the solver, the planner and the judge each skip it by the same
rule as an extrusion's smooth corners (the two pieces' directions there
within 1e-9 of each other: `forge_spec.outline.runs_on`, `turned_rims`,
`corners`; the judge's own in `forge_checks.oracle`). An edge set naming no
edges at all is a fault the writer is asked again about (edges.md): an
extrusion's `vertical` with an outline that has no corners, a revolution's
`top` or `bottom` with no flat end there or only smooth rims. A reference
part pins it: a ring rounded over into its top, its `top` rounding its
bore's rim alone.

### 6.5 Compiled as

- `profile_outline` (a v2 operation): the outline's start and pieces on a
  datum plane, each row `[u, v]` a straight piece to that point, or
  `[u, v, mu, mv]` an arc to it through its middle (three points on the
  circle: exact, and nothing to read the sweep's way round from), as
  `forge_occ.profiles` draws them. Its after-check: the face's area equals
  the outline's, worked out from its pieces exactly (Green's theorem: each
  line's and each arc's share).
- **extrusion:** `extrude` of it by `length` along the axis.
- **revolution:** `revolve` of it about the axis through 360 degrees, the
  outline's first coordinate the radius (V1's reading, stage 3 7.2).
- the oracle makes both as solids of its own: a prism of the outline (a new
  2D shape with exact signed distance to lines and arcs), and a revolution
  (a point is inside when its radius and height lie inside the outline).
- the generator draws outlines with lines and arcs (L-shapes, plates with
  rounded ends, flanges and knobs turned, each closed and never crossing),
  its truth its own inside test, and places things on their ends.

### 6.6 How it is built

Each program that makes geometry from the definitions has its own outline
code (rule R2): the solver's (`forge_spec.outline`), the judge's
(`forge_checks.outlines`, its `Outline` extended to any outline of lines and
arcs), the generator's (`forge_eval.truth`). Each reads the profile's
pieces from its own reading of the field (start, then each line or arc,
an arc's sweep anticlockwise unless `clockwise`, an arc back to its start
a whole circle), and answers exactly, never by sampling:

- **inside, and the signed distance**: a point's distance to the nearest
  piece, negative inside; inside by the crossing rule (a ray along the
  first axis, each line and arc crossed exactly, a piece's end counted on
  one side only);
- **within**: whether a footprint (a rectangle, its corners possibly
  rounded, a disc, or the parts a slot or pocket is made of: each convex)
  lies in an outline. A convex footprint lies in a simple outline when a
  point of it does and no piece of the outline enters it: each piece's ends
  are outside it, and each stretch of the piece between where it meets the
  footprint's boundary has its middle outside (a convex footprint holds a
  straight stretch whose ends are on its boundary, so its middle is at least
  half as deep as the deepest point). An outline standing on a face lies in
  it when its own pieces do: on a convex face (a rectangle, a disc), each
  piece's ends and its arcs' points farthest from the face's own arc
  centres; on a ring, besides, the bore's circle no nearer than its radius;
  on another outline, each of its pieces split where it meets the face's,
  each stretch's ends and middle on the face (a simple outline whose
  boundary lies in another simple outline lies in it);
- **the box** round it (its corners, and its arcs' points furthest along
  each axis), its **area** (Green's theorem: each line's and each arc's share).

**Faces.** An extrusion's ends are flat faces of a new shape, `profile`
(the solver's `FlatFace.profile`, the judge's `Outline` of shape
`"profile"`), in the face's axes: centred, as every face is, on the middle
of its box, its half sizes the box's. A position on one is measured as on a
rectangle, from its box. The material under either end is the extrusion's
length (and, under its far end where the extrusion stands wholly on its
host, the host's too, as for any standing body). A revolution's end exists
where the profile has one straight piece across the axis at its greatest
(least) height and no other piece there: a disc when it reaches the axis,
else a ring; the material under it, at a distance `ρ` from the axis, is from
the end down the line at `ρ` to where it first leaves the profile (the
pieces that line crosses, each worked out exactly), and the least and most
under a footprint are at the ends of its run of distances, the pieces' ends
and the arcs' centres between them. The sides of both are closed: nothing
is placed on them yet.

**Placing them.** As the first body, an extrusion's -end is the plane
through the origin across its axis and the profile's coordinates are along
that end's face axes (frame.md's table), a revolution's axis is the frame
axis through the origin; standing on a face, the -end (the profile's height
0) is on the face, the profile's coordinates along the face's axes from the
point `place` puts it at (its `(0, 0)`), the axis out of the face. Standing,
the whole profile must lie on the host face (as any footprint must), and a
revolution's profile reaching below height 0 is refused (nothing reaches
behind the face it stands on).

**The oracle's solids.** A profile is made of convex pieces, exactly: its
arcs split until the region between each and its chord holds nothing else
of the outline; the polygon through their ends (simple, then) cut into
convex pieces (ears clipped, then joined while convex); the region is the
union of those pieces and of the arcs' segments bulging out of the polygon,
less the segments bulging into it. An extrusion's step is that, each piece
a `Prism` (a polygon, or a disc meeting a `Halfspace` for a segment); a
revolution's is the same in its half-plane, each polygon a `Revolved`, each
segment a `Torus` (a ball for an arc centred on the axis) meeting the
`Revolved` of its side of the chord. Unions and differences are the CSG the
oracle already folds.

**The checks.** An extrusion's `length` is a `size` check between its two
ends (where both are on the part's surface); its `profile`, and a
revolution's, have no single size: face accounting holds every point of
them to the build's own tolerance (`NotChecked.held_by` "face accounting").

**The compiler.** `profile_outline` (a v2 operation: a datum plane, the
start and pieces as written), its after-check its face's area against the
profile's by Green's theorem; an extrusion is that extruded by `length`, a
revolution that drawn in the plane through the axis and revolved a full
turn. Down-converted for the implicit kernel to V1's `profile_sketch`
through points within 0.005 mm of every arc, its agreement entry bounded
by that. Names: the extrusion's `+end`, `-end`, `side`; the revolution's
ends by the piece that makes them, the rest `side`.

**Edge sets.** An extrusion's `vertical`: its sides' edges along the axis
where two pieces meet at a corner (not tangent); `top`, `bottom`: round
the +end and the -end; `all`. A revolution's `top`, `bottom`: round its
ends (each a circle).

**The generator** draws, as a first body, an extrusion of an L, a T, a
plate with round ends, or a polygon with a rounded corner, and a revolution
of a flange, a knob with a rounded rim or a pulley with a groove; and places
cuts and standing features on their flat ends; its truth is its own
outline code.

**As built, what the building added.**

- *Reading an arc.* Written to a few decimals, an arc's ends are rarely
  exactly as far from its centre as each other. extrusion.md: within 0.001
  mm it is the circle through both ends whose centre is nearest the one
  written (the written centre moved square to the chord onto its
  bisector); every program reads it so (`forge_spec.draft._on_bisector`,
  and each reader after it from the spec), so the solver, the judge, the
  compiler and the generator all have the same circle.
- *An outline never turns straight back* where one segment meets the next
  (extrusion.md): a cusp is a sliver of no width, which OpenCascade builds
  but no mesh or oracle can hold to anything. The reader refuses it
  (`outline_turns_back`), as it refuses an outline crossing or touching
  itself; a whole circle can't be written (an arc can't end where it
  starts).
- *Which way a face faces.* An OpenCascade plane's frame may be indirect
  (a revolved end's often is), so a face's outward direction is the
  plane's axis, flipped for an indirect frame and again for a reversed
  face (`forge_occ.occt.plane_of`); the views, the references and the
  names all read it from there. A revolution's faces: every face `side`,
  and its flat ends at its outline's greatest and least height also `top`
  and `base`.
- *Edges along a line.* An edge query `within` a box drops the pieces of an
  edge's line or circle wholly clear of the box (an extrusion's side runs
  on past a corner along the same line, cut where the next piece meets
  it); a piece partly beyond the box is still an error (`forge_occ.refs`).
- *An inside corner's rounding.* Where a rounding fills an inside corner of
  an extrusion, the oracle asks whether the corner's edge is held by the
  solid on both sides; along a face two convex pieces share (inside the
  solid, not on its surface), a point exactly on it was found on neither.
  `held_all` nudges such a point a micrometre into each piece in turn.
- *The generator* measures a position on an outline's end along each of
  the face's axes by that axis's own half size (it had used the first for
  both).
- The compiler places on an extrusion's end and a revolution's flat end by
  the outline's own edge (`outline_edge`, `_turned_rim`): a position "from
  the -x edge" is from where the outline ends along x.

### 6.7 An outline's sizes, cited

**The gap.** A profile cites words, but nothing read the numbers in them:
they were used by no value, so every brief that gives an outline's sizes
("a hexagonal prism 20 mm across the corners", "an 8 mm round section bent
into a ring 40 mm across at the centre line") was a question for each of
them, and an automatic run of it always stopped; and a writer could cite
any words at all for an outline.

**The rule.** Every number a profile's cited words give is a size the
outline has, or the citation is a fault ("the outline has no size of
12 mm"); each number matched is used, as a value's is (accounting). The
outline's sizes, each worked out exactly from its pieces in its own
coordinates (`forge_spec.outline.sizes`; a number in another length unit
converts):

- across it along each of its two axes (its box);
- each straight piece's length, and the distance between two parallel
  straight pieces (a leg's thickness, a hexagon across its flats);
- the distance between two of its piece ends (a hexagon across its
  corners);
- each arc's radius and diameter;
- for a revolution, the diameter of the circle each piece end and each
  arc's centre turns on, and its widest.

A count in the cited words must be how many pieces or corners the outline
has ("six-sided"); any other number (an angle) is a fault. Sizes match
within 5 microns: an outline is written to a few figures.

The points measured between are the outline's piece ends and its arcs'
centres, straight and along each of its axes: a drawing dimensions a lever
from its pivot to its far end's centre, and a lug by how far along the bar
and how far across its end's centre is (found drafting V1's exo rails,
14.3; an arc split in two, a circle's halves, has one centre).

**What it is not.** It reads which sizes the words give, not which size
each one is: a doughnut drawn 40 mm across its outside, on a 32 mm middle,
has a 40 mm size too, so "40 mm across at the centre line" doesn't fault it
(V1's false pass 17). That is caught where it was always to be caught: the
judge against the right spec (14.3), the preview and the person. What this
adds is that an outline's stated sizes are accounted for, and each is one
the outline has. So in an automatic run, where no person sees the outline,
one that cites sizes is still a question (which is which is a judgement):
the run stops for a person, as it did, now with that reason.

## 7. The two new operations for letters and threads

### 7.1 `text`

**The glyph table.** `scripts/font_glyphs.py` reads the pinned font with
fontTools, decomposes every composite glyph into its components' contours,
and writes `packages/forge_spec/glyphs.py`: for every character `font.py`
has an advance for, its contours in font units, each a closed run of
on-curve and off-curve points (TrueType's quadratic B-splines), with the
font file's SHA-256. Tests: the table regenerates byte-identical; for every
glyph, its area by Green's theorem on its curves and its box equal
fontTools' own (`AreaPen`, `BoundsPen` on the decomposed glyph), an
independent path; the H's height is `CAP_HEIGHT`. Overlapping components
(Ç, ç) and contours nested three deep (©, ®) are kept as the font draws
them: the letter is the region of **nonzero winding**, TrueType's own
rule.

**Layout** (text.md), done by each program on its own: each letter's
glyph scaled so the H is `height` tall, set by its advance with no
kerning; the line's box (first letter's start to the last's advance,
baseline to capital height) centred on the copy's point; reading the right
way round from outside the face (up its second axis; left to right along
up × outward). The compiler writes it into the `text` step; the oracle and
the generator each have their own (so a mistake in one is a disagreement,
not a shared blind spot).

**The ink is held to the face.** The solver held only the line's box to the
face; letters' ink reaches below the baseline and past their advances (a j,
a J, an f). The solver now holds the ink's box (the glyphs' boxes, laid
out) to the face and to what else is on it; the judge's placement too.

**The operation.** `{"op": "text", "params": {"text", "height", "origin",
"up", "right", "depth", "mode"}}`, one input, the part. Its builder makes
each contour a degree-2 `Geom2d_BSplineCurve` (exactly the font's curves:
an on-off-on run is one Bézier arc; two off-curve points in a row have
their midpoint on the curve), builds each component's faces by nesting
(outer contours and the holes inside them, the next level a face again),
**joins every face of every letter** (so overlapping components and
touching letters, "YY", "fT", "__", make one region), extrudes the region
by the depth inward (engrave, subtracted) or outward (emboss, joined).
Faces: `letter_wall`, `letter_floor`, `letter_top`. After-check: the volume
taken or added lies between the region's area × depth less what overlaps
earlier cuts and the area × depth (the area worked out exactly from the
curves, overlaps by the join).

**The oracle's letters become exact.** Stage 2 held letters to their
line's box (`Unchecked`: "letters' outlines come from the font in stage
4"). Now a point is inside a letter by nonzero winding (each quadratic arc
crossed exactly: a quadratic's roots), its distance to the ink the least
over the arcs (a cubic's roots, each bracketed), and face accounting and
the checks hold the letters as they hold a pocket. The `Unchecked` entry
goes.

**As built.** Where the build differs from the plan above, and what was
added:

- *The region* (`forge_occ/ops/letters.py`). Each contour is a closed
  wire of lines and degree-2 `Geom_BezierCurve`s through the font's own
  control points, its face laid on the letters' plane. The faces of all
  the contours are laid over each other by OpenCascade's general fuse
  (`BOPAlgo_Builder`), and each cell it splits them into is kept where the
  contours round it wind a non-zero number of times (each contour counted
  +1 if it runs anticlockwise round the face's normal, -1 if clockwise):
  nonzero winding by construction, with no nesting to work out. The cells
  kept, merged where they share an edge, are each pushed `depth`. A line
  of one contour (an I, an F) is its face: the general fuse wants two
  arguments at least. Tested for every letter of the font alone and for
  runs that touch, overlap and cross ("__", "ff", "%%", "ÇÇ", "@@"): the
  region's area is the judge's, worked out by Green's theorem round the
  judge's own edge, to 1e-7.
- *Faces*: `letter_wall`, `letter_floor` (engraved), `letter_top`
  (embossed); a piece of the prism lying in the face's own plane is
  `letter_mouth`.
- *After-check*: engraved, the volume taken is the volume of the part
  inside the letters' prism (each region face's prism intersected with the
  part, measured); embossed, the volume added is the prism's outside the
  part; and either is no more than the region's area × depth.
- *The judge's letters* (`forge_checks/letters.py`, its own reading of the
  table). The pieces are split wherever they meet; a stretch whose two
  sides differ (the winding number read 1e-7 mm off it either side) is the
  edge's, its letters' side recorded. The winding number counts the pieces
  split where they turn along y, each crossed at most once by a line along
  x, on the half-open rule. A point's distance to the edge is the least
  over the stretches of the cubic's roots (closed form, Cardano's or the
  trigonometric one, each polished by Newton's method), and only the
  stretches that may be nearest are looked at: the edge has a grid of
  about four cells a stretch, each listing the stretches whose boxes come
  within its centre's distance to the edge plus its whole diagonal; a
  point in a cell is held to those within its distance from the centre
  plus the centre's (the triangle inequality); a point outside the grid,
  to those within the same bound from the nearest cell. The answers are
  the exhaustive search's exactly (tested on random points, on and off the
  edge). The places a line meets the letters' prism are solved only on the
  stretches whose boxes the line passes, and a place on the floor's or
  top's plane off the letters' box is left out unmeasured.
- *First-order models* (`LetterPrism.locals`): along a stretch, its wall;
  at a corner of the edge where the letters lie on the inside (an inside
  corner, the letters the union of the two walls' half-planes), the two
  walls are one group of the `Local`'s conjunction of disjunctions (either
  holds); with the floor or top, another group; a point where three ways
  of the edge meet is unsure. Each stretch pushed along the prism is a
  `WallPatch` (`own_patches`), so the patches and witnesses of 13.5 work
  on letters too. The letters' finest detail, for the probes' spacing, is
  a tenth of a capital.
- *The second kernel* has no letters: V1 holds a `text` step as an
  identity of its input (the IR's down-conversion), and the agreement
  (`forge_kernel/agreement.py`) holds it as not applicable within its
  depth (and τ) of the letters' faces: every point the letters take or add
  is that near their floor or top.
- *The reference part* `lettered plate` (tests/v2_reference.py): a plate
  engraved "FORGE Ç&j" on its top and embossed "V2" on a side, built with
  manifold3d from the table read by the test's own TrueType decoding, each
  arc cut into chords within 1e-4 mm, the region manifold3d's nonzero
  cross-section. Face accounting, topology and volume hold the oracle to
  it; plan, build and the judge to both.

### 7.2 `thread`

**The operation.** `{"op": "thread", "params": {"axis_origin", "axis",
"major_diameter", "pitch", "hand", "length", "rod_start", "rod_end"}}`, one
input, the part. The rod's round side, over `length` from its free end, cut
into the ISO 68-1 basic profile (thread.md): flanks at 60°, crest flat P/8
at the major radius, root flat P/4 at 5H/8 in (H = √3/2 · P).

**The construction.** The groove (what the thread takes from the rod) is,
in the half-plane through the axis, a trapezoid per pitch: P/4 wide at the
minor radius, 7P/8 wide at the major, carried out past the major radius by
`c`. It is swept along the helix of the pitch (`BRepOffsetAPI_MakePipeShell`
with the helix as a 2D line on a cylinder, the section kept in the plane
through the axis by an auxiliary spine), the sweep starting 7P/16 + `c` past
the free end, so the thread runs out fully there, and ending at the
threaded length. The swept solid is then **intersected with the rod's own
cylinder between its ends** (radius the major radius plus `c`, from the
rod's start to its end), so the groove never reaches anything beyond the
rod (a plate the boss stands on, a cap on its end), and subtracted. Where
the sweep stops is the run-out, which thread.md leaves to the build
(bounded). Faces: `flank`, `root`, `runout`.

**Exactness.** OpenCascade has no helicoid surface: the sweep's flanks are
B-splines within 1e-5 mm of the true helicoids (measured by the
after-check). The definition is bounded there anyway (the thread check
holds the flanks to the profile at ISO 2768-m on the thread's depth, ±0.1
mm and more), so that is far inside it, and is stated as the step's
tolerance.

**The second construction** makes each flank as a ruled surface between two
helices (its lines on the minor and major cylinders), closes them with the
root's cylindrical band, and subtracts that solid, within the same 1e-5 mm
of the true surfaces: equal to the first within that bound, and proven so
by both meeting it.

**After-check.** The volume taken: by Pappus for a helical sweep, the
section's area × 2π × its centroid's radius × (threaded length / pitch),
less at most the run-out's bound (a section's area × the run-out's length);
and points of known profile coordinate between the minor and major radii
on the right side of the profile.

**As built** (`forge_occ/ops/threads.py`, `forge_plan/threads.py`). Where
the build differs from the plan above:

- *The groove* is the trapezoid above, carried out past the major radius
  by P/20, swept along the helix of its root with the binormal held along
  the axis (the section is carried by the screw motion itself), the sweep's
  own tolerance 1e-6 mm. It is swept **in pieces of one turn or less**, one
  after another, each piece's section the first's turned and raised by the
  screw motion: OpenCascade's booleans go wrong **silently** with a helical
  face of many turns against a rod's cylinder (seen: a groove of seven turns
  taken from a rod left it whole, for some starts round the axis and not
  others; cut in pieces of a turn or of half a turn it never did, in 96
  tries over starts, the rod's seam and both hands).
  The pieces that reach the threaded length's start or the free end are cut
  down to the cylinder of radius R + 2c between them; the rest are left as
  swept. All are taken from the part in one subtract. The run-out is square
  to the axis at the threaded length's start (`runout`); the groove never
  reaches past the free end.
- *After-check.* The pieces' volume is the threaded length times the
  groove's cross-section (∫ 2πr f(r) dr from the minor radius to R + c,
  exact), within 1e-5 mm times their surface; and points spread over their
  flanks and root lie on the section, in the half-plane through the axis,
  within 1e-5 mm (the step's stated tolerance). Then the cut itself: where
  the part round the threaded length is the rod alone (a cylinder of the
  major radius between the ends: three faces and its volume), it must lose
  exactly the threaded length times the groove's area to the major radius;
  elsewhere (a hole across the rod), what it loses is measured, must be no
  more than that, and 96 points (a fifth of the depth from every surface,
  spread by the golden ratio along and across) must be out of the part in
  the groove and as they were in the thread between. A try that fails that
  (or that OpenCascade refuses) is made again with pieces of half a turn
  started a quarter turn round, then of a quarter turn started half a turn
  round; only when all three fail does the step fail. Something besides the
  rod in the groove's way fails the step at once.
- *The second construction* (ruled flanks between two helices) isn't built:
  the first holds by its own after-check, and a rod's thread has no other
  sweep to fall back to that the pieces don't already give.
- *The planner* writes one `thread` step for each copy of the rod (a
  cylinder body, or a boss on every copy of a pattern), on the part made so
  far: the axis from the copy's base along the way it grows, the rod from 0
  to its length (a boss's height), the major diameter the rod's (made at its
  middle), the pitch the designation's (named, or the size's coarse one).
- *The judge* holds the thread as stage 2 does (the zone between the minor
  and major cylinders; the thread's own check of profile, pitch, hand and
  length). Face accounting's witness now finds, for a built point that
  fails the first try, a place within its tolerance where the spec lets the
  surface be anywhere (between the two forms) as well as a point on the
  spec's surface: the run-out's edge on the root lies on the zone's corner,
  a nanometre either side of it as OpenCascade makes it.
- *The second kernel* has no threads (V1 holds the step as an identity);
  the agreement holds it as not applicable within the thread's depth (and
  τ) of its faces.
- *Measured*: the threaded boss (an M8 on a boss, 8 mm of thread), planned,
  built and judged with every check passing, ~10 s; a 24-turn M4x0.7 on a
  tilted rod built and held to its exact volume in ~30 s.

## 8. Building with alternatives

```python
# forge_occ.planned
def build_plan(plan: Plan, *, cache: StepCache | None = None) -> PlannedBuild

@dataclass(frozen=True)
class PlannedBuild:
    result: BuildResult | None
    choice: Mapping[str, int]          # each planned item's construction
    refusals: tuple[Refusal, ...]      # item, construction, the OccError, its step
    gap: Gap | None
```

1. Build `plan.document()` with a step cache, so a rebuild reuses every step
   before the one that changed.
2. A step refused (any `OccError`: OpenCascade raised, the solid is invalid,
   an after-check failed, a reference matched outside its condition) names
   its item, `plan.owner(step)`. That item's next construction is tried.
   So does a step that leaves the part made so far in more than one
   solid. The part is one solid all the way (frame.md: every body stands
   on an earlier one, and a cut that would cut it in two is a CAN'T), so
   after each item's join or cut of it, more is OpenCascade misreading the
   step. Held-out seed 10,517: a hole's plug kept beside the part, touching
   it along six edges, with no flag raised. That stays a stage 4 rule, not
   a stage 3 after-check, because stage 3's `subtract` may leave lumps
   where its document asks.
3. When it has none left, the earlier items whose tools' boxes meet the
   refused step's box are tried, latest first, each through its own
   constructions, with the refused item's tried again after each (a
   refusal can be caused by how an earlier item was made: a union whose
   faces a later fillet can't run over). The search is bounded (each
   earlier item's constructions once; at most 64 builds), and deterministic.
4. When it runs out, the refused item is the gap, with every refusal it
   met, and the run ends UNABLE for it (in stage 5 the construction agent
   gets it).

Every refusal is recorded, so a construction OpenCascade often refuses is
visible in the exit test's report.

As built (`forge_occ.planned`): the build records each item's chosen
construction by name (`made_by`) beside the choice. A refusal at an item
later than the one searched for has got past it, and goes back to the main
loop with that item, without building again. A plan with gaps of its own
(a region, an item no construction is written for) is built without them,
for the preview, and its first gap is the build's: the run ends UNABLE for
it whatever was built.

## 9. The build and the verdict

### 9.1 `forge build`

```
forge build RUN_FOLDER | confirmed.json [--out FOLDER] [--formats step,stl,3mf] [--seed N]
```

No model is called and no key is read. In order:

1. **The confirmed spec.** `confirmed.json` (a run folder is read through
   its own) is unlocked (`forge_spec.lock.unlock`): the brief numbered
   afresh from its text, the digest and every spec check run again by this
   Forge. A file that can't be read, or a spec changed since it was
   locked, is refused, and nothing is written. A person's confirmation is
   taken only with its seal (9.7); without one the spec is built as a
   draft, and the verdict says why.
2. **The folder.** The verdict, its record and the files go into a folder
   of their own: `--out`, which must not exist or be empty, or else a
   fresh `build` folder in the run's folder (`build`, `build-2`, …). So no
   build writes over another's, or over any file of yours.
3. **The judge before building** (9.2.1): CAN'T or HELD end the run here.
4. **The plan and the build** (`forge_plan.plan`, `forge_occ.planned.build_plan`).
   A gap ends it UNABLE (by name), with what was built recorded.
5. **The judge** on the B-rep, the second kernel, and every file asked for
   (9.2).
6. **The ending** (9.3); the record, the files released (9.5) and the
   verdict, written last; the ending printed, with each reason a line.

Exit codes: 0 the files released (VERIFIED, VERIFIED EXCEPT or BUILT TO
DRAFT; `verdict.json` says which); 1 HELD; 2 a command line or a confirmed
spec refused, or an error of Forge's own (the compiler's `PlanError`, any
exception), as every Forge command's 2: then, once the folder is made,
`record/error.json` says what, and no `verdict.json` is written; 3 UNABLE;
4 CAN'T. A file that can't be written, read back or judged
(`OperationError` from the exporter, the agreement test's) holds the part;
it is no error. `--formats` takes any of `step`, `stl`, `3mf` (all three by
default; at least one); `--seed` replays a run's fresh probes (by default a
seed is drawn from the operating system's random source, and recorded).

### 9.2 The judge

With nothing from the document. Its code is `forge_checks.judge` (L0: the
views it is handed, the spec, the oracle; never the plan or the kernel),
the production form of stage 2's detection harness (`tests/v2_detection.py`).

1. **Before building:** the judge's placement and the oracle from the spec.
   A `CannotMakeError` (a rounding whose edges are all gone, or that doesn't
   fit them) ends the run CAN'T; any other `OracleError`, or a `PlaceError`,
   holds it (the judge can't make the shape the spec asks for, so it can't
   judge it). Then the check suite (`compile_checks`), the topology the
   oracle expects, and its volume interval.
2. **Each view** of the part as built (the B-rep, the STEP, the STL, the
   3MF; not the implicit kernel's, which 4 judges) is judged alike
   (`Judge.view`): admitted by the capability table (a view that says it
   can't answer a question its source must answer holds the part); every
   check the table makes applicable to the view's source, the check's needs
   and its item's kind, run (the rest listed as not applicable to that
   view, never run); face accounting at the suite's radius and the view's
   own tolerance; topology against the expected counts; volume against the
   oracle's interval; fresh probes. Anything but PASS holds the part, with
   the item, the view and the numbers. Fresh probes come from one seed for
   every view, drawn (`draw`) and run (`Probes.run`) with one number for the
   view's tolerance: the greatest point tolerance face accounting used on
   it; views of one tolerance share one draw.
3. **The B-rep**, as built (`BrepView`).
4. **The second kernel:** the document down-converted and built by the
   implicit kernel, and stage 3's agreement test (`forge_occ.agreement.agree`),
   and nothing else: its disagreements, volume, names and topology hold the
   part where they don't agree.
5. **The files** (9.4), each written, read back and held to the exact part
   by the exporter's own checks (`check_step`, `check_mesh_file`), then
   re-opened and judged as a view: the STEP by OpenCascade (`BrepView`,
   source `step-file`), the STL and the 3MF by Forge's own mesh reader
   (`MeshView`, source `mesh-file`, its deflection the export tolerance; the
   3MF moved back by the shift Forge wrote, `plate_shift`, never by the
   file's own word).

### 9.3 The ending

- **CAN'T:** the shape can't be made (9.2.1, or the solver's own CAN'T,
  settled at confirmation).
- **UNABLE:** a gap, by name (4.9, 8).
- **HELD:** any check, face accounting, topology, volume, probes, agreement
  or file check that fails, or is inconclusive where the capability table
  says the view must answer; or an `OracleError`; each with the item, the
  view and the numbers.
- **VERIFIED:** all pass, a person's sealed confirmation (9.7), and
  nothing of the spec left unchecked.
- **VERIFIED EXCEPT:** all pass and a person confirmed it, but something of
  the spec was left unchecked: a field `compile_checks` gave no check and
  nothing else holds (a centre that can't be fitted, a round face's rim not
  fitted for now), or an item the oracle knows only within bounds (its
  `unchecked`: letters' outlines, a region), each with its reason; listed,
  so you see what wasn't checked. A field with no check of its own that
  other checks or face accounting hold (`NotChecked.held_by`: a shell's
  `of`, held by its walls' checks; the places of two copies on a circle,
  by face accounting) is checked, and listed as checked otherwise. So is a
  field whose faces aren't on the part's surface as the spec has it,
  inside the part or pressed against another item's (a divider flush with
  a box's walls, a bar's ends in the balls on them, a top under what stands
  on it): built otherwise, such a face changes the surface only where it
  comes out of the material, a surface the spec doesn't have, and face
  accounting holds every point of the surface both ways; built otherwise
  and still inside, the part is the same. It is held by face accounting.
- **BUILT TO DRAFT:** all pass, and the spec was locked as a draft (`--auto`;
  R12) or its confirmation has no seal here, with anything unchecked
  listed.

The detectors' own limits change no ending, and are listed in the verdict
as not cross-checked: counts the oracle doesn't make (through-holes, voids
it couldn't settle), items no fresh probe could be drawn round. Each field
of such a part is still checked, and its whole surface accounted for both
ways.

The verdict lists, per item, its verification class (the loosest of its
checks': exact, bounded, constrained) and, per view, whether everything of
it held there (its checks and its fresh probes); what was left unchecked;
and the share of the B-rep's surface checked exactly and within bounds
(plan 4.7): face accounting's built points that passed where the spec's
shape is exact (by its first try or a witness) and where it is bounded, of
all it covered.

### 9.4 Export tolerances from the spec

The STL's and 3MF's deflection is a twentieth of the smallest half-band
(9.6) of any check of the part that holds a size (not an angle), and no
more than a cone's angle needs (a countersink's: half the deflection at
which its angle, fitted to points on the cone, would be measured to an
eighth of its band, read off the fit's own weights; found by the exit
test's pilot, where generated parts 20 and 40 were held on their meshes,
each countersink's 90° measured to ±1.2° to 1.6° for ±1°), at most 0.01 mm
and at least 0.0005 mm; angular 0.1 rad. A circle fitted to a mesh
is uncertain by about twice its deflection, and a size made at the middle
of its band passes while its measurement is within half the band, so a
twentieth leaves room fivefold; the general tolerance (ISO 2768-m, ±0.1 mm
and more) gives 0.005 to 0.01 mm. A check measured on its own surface
alone (a diameter, a cone's angle) asks its tolerance there only: in the
box round that surface, grown by 1 mm, where finer than the rest ask
everywhere (13.10). A part with a tolerance finer than a mesh
at 0.0005 mm can show is held on its meshes, saying so (its STEP alone,
`--formats step`, carries it). Each file is named for the spec: its name
in lower-case ASCII letters, digits and dashes (others dropped, runs of
them one dash), at most 64 characters, `part` when nothing is left or it
is a name Windows reserves (`con`, `nul`, `com1`, …).

### 9.5 The record, and the files released

Written into the build's folder (9.1.2):

- `record/`: `document.json` (the ForgeIR v2 document built, its
  constructions chosen), `build.json` (each step's trace, each item's
  construction by name, every refusal, the builds tried, the gap),
  `judge.json` (every check's evidence on every view, face accounting's
  tallies and first misses, topology, volume, probes, agreement's report,
  each file's own read-back check).
- **The files**, released into the folder only when the run ends VERIFIED,
  VERIFIED EXCEPT or BUILT TO DRAFT, each created afresh (never over an
  existing file). A part held keeps its files in `record/files/`, to look
  at, never beside a verdict that doesn't release them.
- `verdict.md`: the verdict for a person.
- `verdict.json`, last (written whole, then renamed into place): the
  ending and its exit code; the spec's name, digest, who confirmed it,
  whether strictly, and whether the seal held; Forge's version; the probe
  seed; per item as 9.3 says; what was unchecked and what not
  cross-checked; the surface shares; every reason the part is held, each
  with its item, view and numbers; the gap or the CAN'T's reason; the files
  released, each with its bytes and SHA-256; seconds per stage. A folder
  without one is a build that didn't finish.

### 9.6 Sizes made at the middle of their tolerance

A value with its own tolerance that isn't the same both ways (10 mm +0.1/-0:
a hole a pin must pass) is made at the middle of its band (10.05 mm), and
held to the same limits it was written with. Made at the nominal it would
lie on a limit, and no measurement can show a size on its limit within it
(a measurement is an interval; stage 2, 4.3): every such part would be
held, on its exact model and its meshes alike.

So the definitions (`sizes.md`) say a part is made to each value's middle,
and every program that turns a value into geometry reads the middle
(`Value.made`, a quantity in the value's unit): the solver and the spec
checks (`forge_spec.placement.mm` and `degrees`, which the checks, the
comparison of drafts and the views read through), the compiler
(`forge_plan`), the judge's placement, oracle and check compiler
(`forge_checks`), and the generator's model when it draws tolerances
(`forge_eval`). A check is held to the band about the middle:
`tolerance_of` gives a stated tolerance as half its band either way, and
every check's nominal is the made size, so its limits are the written ones
whichever way the compiler reached its nominal (from the value, or from the
judge's placement). Only the spec's text, the spec page and the questions
show the nominal and the tolerance as written. A test holds every module
that makes geometry to reading no `.quantity` of a value. A tolerance the
same both ways (every general one) leaves the middle at the nominal, and
nothing changes.

A size whose middle is at or below zero (1 mm +0/-3) is refused as written;
the spec checks, which judge the part as it will be made, settle fits,
flushes and throughs at the middle.

### 9.7 A person's confirmation, sealed

The digest proves a spec unchanged, not who confirmed it: anyone can write
`"by": "person"` and hash again. So when a person confirms in Forge's own
window, `forge spec` seals the digest with a key of this installation's
(HMAC-SHA256; the key made once from the operating system's random source,
kept in the user's own Forge folder, `~/.forge/confirm.key`, readable by
the user alone, never in a run's folder, never printed), and writes the
seal into `confirmed.json`. `forge build` takes "person" only with a seal
its own key makes; without one (another computer's run, a hand-written
file, a run from before seals) the spec is built as a draft, ending at
best BUILT TO DRAFT, and the verdict says why. A program with the user's
files can still read the key: the seal stops a confirmation written
without Forge's window, not one forged by a program that already owns the
user's account.

## 10. The 3D preview

At every round of `forge spec`, after the spec checks, `preview_plan` plans
the draft and a separate process builds it (OpenCascade where it is
installed; else the implicit kernel's build of the down-converted
document, and the page says so and lists every item that build can't make:
roundings, letters, threads), meshes it at 0.05 mm (0.02 mm under 50 mm),
and the mesh is written into `spec.html` with each triangle's item, tinted
with the item's colour from the brief's legend (the item a face came from
is its name's step's item). The page embeds three.js and its orbit
controls, shipped with Forge (`forge_cli/viewer`, as V1's live page), so it
opens from disk with no server and no network. The preview's gaps (items
with issues, and what depends on them) are listed under it by name.

- **The order on the page** is the plan's (4.2): assumptions and questions;
  differences between the drafts; the 3D part; the dimensioned views; the
  coloured brief; the fixed wording.
- **Time:** the process is stopped after 20 s, and the page then says the
  preview wasn't built in time (measured on every corpus part, 15).
- **Never evidence:** the preview is shown, never judged.

## 11. Two drafts as geometry

Stage 1 compares two drafts feature by feature (`forge_spec.compare`): each
layout reduced to boxes, rods, holes and the rest, the second turned and
moved to match the first best. Where that finds differences:

1. Both drafts are planned (`preview_plan`) and built by OpenCascade, the
   second moved by the rotation and translation stage 1 found.
2. **Exactly:** the volume of each less the other (two booleans); each
   within OpenCascade's volume tolerance means the solids are one.
3. **Independently:** both drafts' oracles classify points drawn round them
   (each oracle's surface samples at 0.5 mm, 20,000 points in the box round
   both, and 2,000 in each stage-1 difference's own box), each pair on the
   same side, a point one oracle puts on its surface and the other inside
   or outside counting as a disagreement.
4. A stage-1 difference is dropped only if 2 and 3 both say the parts are
   one, and, where it touches an item either oracle only bounds (a thread,
   a rounding, letters), that item's own fields agree too (its designation
   and hand, its radius, its edge set, its text): so a left-hand thread
   for a right-hand one, or a 2 mm rounding for a 3 mm one, is never
   dropped. The page then says "the two drafts are written differently
   and make the same part".
5. Otherwise each region where they differ (the first's less the second's,
   and the other way, each piece of the booleans' results) is said in the
   first draft's terms: the item whose surface is nearest it, which draft
   has material there, its box and volume. Each becomes one question, as
   stage 1's differences are.

Where OpenCascade isn't installed, step 2 is skipped and the page says the
comparison was by the definitions only. This differs from the plan (4.2,
"compiled, aligned and compared as geometry") only in using the oracle as
a second, independent opinion beside the compiled solids.

## 12. The generator, widened

### 12.1 Briefs the values cite

Stage 2's drafts gave every value as assumed, so a CAN'T always routed
back to the writer as a fault (`route`). Now `render` also writes a brief
(one sentence per item, its numbers and choices in words: "i3 is a hole
4.2 mm across and 7.5 mm deep, on the +z face of body, offset 12 mm along
x, …") and cites its words for every value, so the solver routes as it
would a person's brief. The spec checks run on that brief in full
(citations, accounting); only the positions the generator leaves unsaid
are assumed, as a person's would be.

**As built.** `forge_eval.brief` writes the brief a phrase at a time: each
value's words are marked as they are written, and the marks become word
numbers only once the whole brief is numbered as the spec checks number it
(`number_words`), so no word is counted by hand. Every word of an item's
sentence that no value cites is the item's own (what it is, what it stands
on), so the brief is accounted for to the last word, and the drafts are
checked as an automatic run checks them (`strict`): of the first 400,
nothing to ask, no caveat, and no assumption but a position the plan left
unsaid (an item centred along an axis, halfway along a side, a circle's
first copy at 0 degrees). For example, generated part 1:

> The body is a block 107.795 mm long, 75.826 mm wide and 11.377 mm tall.
> Boss Alpha is a boss 3.598 mm across and 5.796 mm tall, on the -y face
> of the body, offset -30.505 mm along x, offset -0.459 mm along z. …

- Items are named after their kind and a name of their own ("Hole Alpha",
  the first body "the body"): a name with a digit in it ("i3") would be a
  number the brief says and nothing uses. The names are no number, unit,
  axis or option word (tested).
- An offset is written with its sign ("offset -12.5 mm along x"), so the
  value follows from its words with no caveat; a distance from a side names
  the side and what is measured ("its edge 2.77 mm from the +z edge").
- Options are said in a word that names them ("a round pocket", "raised
  lettering", "right-hand", "a dome", "along y"); "half" and "both" are
  never written, since they are numbers ("a dome", "the edges at each end").
- Letters are quoted (curly quotes). A line no quotation can hold whole (a
  quote mark or a full stop in it, or no letter or figure) is "as drawn with
  this brief", and its text assumed: the one value a brief can't carry.
- An outline's sizes are the drawing's: the brief names it ("an L-shaped
  outline drawn with this brief") and the draft's outline cites those words,
  since an outline in a draft cites no numbers.
- The first round or pushed body says its axis ("its axis along z"), which
  the solver otherwise assumes.
- So an impossible part is turned back to the person, as their brief's
  would be: its problems are questions (the solver's CAN'T or question
  resting on the brief's values), never the writer's faults (tested on 30).
- A mutant's draft differs from the original's in its one leaf's value; its
  citations may move with the words (a depth "right through" made "4 mm
  deep"), which the mutant tests leave out of the comparison.

### 12.2 Every kind, and the limits

Each with its own truth (`forge_eval.truth`, sharing nothing with the
solver, the judge or the compiler):

| Kind | Drawn | Truth |
|---|---|---|
| tube | first body, or standing on a flat face | outer prism less bore prism, its own length |
| cone | first body or standing; top 0 sometimes | frustum |
| sphere | whole standing on a face; a dome first or standing | ball; ball within a half-space |
| extrusion | first body or standing: L-shapes, plates with rounded ends, outlines with arcs | prism of the outline (its own inside test) |
| revolution | first body or standing: knobs, flanges, pulleys | its own inside test in (radius, height) |
| rib | standing, along either axis | prism |
| text | engraved or embossed on a flat face, 1 to 8 characters of the font | the glyphs by nonzero winding, its own layout |
| shell | of the first block, cylinder or dome: sealed, open on one face or two opposite, with or without a floor; of a block or cylinder whose own edges are rounded | its hollow as shell.md says |
| fillet, chamfer | a box-like item's `vertical`, `top`, `all`; a round body's or boss's rims; a hole's or pocket's `top`; a pocket's `bottom`; a joint | exact where the rounding's section is known (along a straight edge between faces at right angles: a rounded or bevelled corner); a zone where the oracle bounds it (where roundings meet, end, or run round a curve) |
| thread | on a cylinder or a boss, M3 to M12, either hand, with or without a length | the core within the minor radius, nothing beyond the major; a zone between |

**The definitions' limits, drawn on purpose** (the gaps between things are
0.5 mm in stage 2's generator, so it never reached them): items flush with
a face's edge (`distance 0 to edge`); bodies stacked flush on bodies; posts
flush in a block's corners; a boss tangent to a face's edge; bodies
overhanging the face they stand on; standing items round a rod's side, a
tube's side, inside a tube's bore and inside a hollowed cylinder; holes
round a tube and out through a wall from inside; two roundings on the same
item (`vertical` then `top`); roundings of edges other items cut across;
roundings on a body that is then shelled; cuts through standing items and
their hosts; items on a shelled block's floor and walls.

**Interacting kinds** are drawn by weight: the kinds' frequencies in the
corpus specs (14.2), so the random parts resemble real ones, with every
pair of kinds drawn at least 50 times in the 10,000 (14.1's report counts
them).

As built: the corpus drafted (14.2) is V1's validation suite, 76 parts of
blocks, holes, cylinders, bosses and balls, with no pocket, slot, tab,
chamfer or text among them. Weighted by it, five kinds would come once in
hundreds of parts and the floor of 50 a pair would draw nearly all of
them; and every seed the tests know would move. So the kinds stay drawn as
stage 2 drew them and the new kinds from their own streams; counted over
seeds 0 to 9,999, every one of the 171 pairs of the 19 kinds is drawn 50
times or more (a chamfer with a shell the fewest, 57, once bevelled
hollows were drawn: 12; before, 35), and every seed draws a part (seed
2,868's line of letters, "¶ Ý²", broke the brief's words: the quote opened
with the ¶, no word, was forgotten, and its closing mark after the ² read
as inches; fixed in `forge_spec.words`). The report lists each pair.

**As built so far.** The kinds stage 2 didn't draw come from streams of
their own, so a seed none of them chooses stays exactly as stage 2 drew it
(and the tests that know such a seed hold): the first body from
`forge-eval first bodies <seed>`, each item from `forge-eval items <seed>
<k>` (drawn as stage 2 would, then replaced), the items drawn after the rest
from `forge-eval decorations <seed>`.

- *tube*, as the first body one time in twelve (30 to 90 mm across, its
  wall 3 to 15 mm, 10 to 50 long): its ends rings, its side a round side
  whose holes go through its wall only, until they are in the bore all
  across their mouths (hole.md), a blind one no deeper than its wall less
  the gap; standing on a flat face (below), its bore open to the face, its
  far end a ring, its side round, measured along its frame axis from its
  end with the lesser coordinate.
- *rib*, *cone*, *tube*, *sphere* standing on a flat face, one item in
  eight: a rib along either of the face's axes; a cone narrowing, coming to
  a point (one in four) or widening (its footprint is its base, place.md,
  but it is kept clear of the rest by its top's circle where that is
  wider); a tube; a whole ball (its centre on the face, its lower half in
  what it stands on, which must be thicker than its radius) or a dome.
  Their truths are a prism, a frustum and outlines turned about the axis
  (a ring; a half disc).
- *extrusion*, *revolution* standing on a flat face, from a stream of
  their own (`forge-eval profiles <seed> <k>`), one item in about fourteen
  of those that aren't one of the kinds above: one of the outlines a first
  body is drawn with (an L, a T, a stadium, a plate with a corner rounded
  and one cut; a flange, a knob, a pulley), sized from the face. An
  extrusion's outline runs along the face's axes from its point, so what it
  covers is its outline's box off that point, and a position to its edge
  is measured to that box's (place.md: its extent); its +end is the
  outline, over its length and the face's material. A revolution covers its
  widest circle (the overhang of a knob's disc too), placed to that; its
  +end a disc or a ring over the least material under it in the revolution,
  and the face's too where every line down through it runs right through
  to the face (a flange's hub). Their truths are the generator's own
  outline pushed or turned, its foot run on a hair into the face.
- What stands on a dome's flat face has under its far face its own height
  and the dome's least height under its footprint, not the dome's radius.
- *shell*, of the first body when it is a block, a cylinder or a dome, one
  time in seven, from a stream of its own (`forge-eval shells <seed>`):
  sealed (three times in ten), open on one face (a tray: on +z half the
  time) or, for a block or a cylinder, on two across from each other; its
  walls 1 mm thick or more, and half the time, where it has one, a floor of
  its own. Its truth is the hollow shell.md gives, taken away just after
  the body (a box; a cylinder; a ball's outline above the floor, turned),
  carried on out through an open face. The material under each closed face
  is its wall; a cut through one comes out into the hollow, on the inside
  face, which must take all of its mouth; a recess must fit in the wall too.
  An open face takes nothing; a cylinder's side becomes a tube's; a dome's
  flat face is its floor all across. The inside faces of a block's and a
  cylinder's walls take items as any face does: what stands on one keeps
  0.5 mm short of the wall across the hollow, its box 0.5 mm clear of what
  else stands there, and nothing stands on the faces round its sides.
  Mutants: its thickness, its floor, its opening (sealed opened; opened
  sealed, or opened on the face across instead). Two faults this found,
  both fixed at the root: the plan made a dome's floor its wall's thickness
  whatever the shell gave (shell.md: the floor is the flat face's own wall),
  and the judge measured a position on a hollow cylinder's inner end from
  the cylinder's outside, not the hollow's own side (place.md: a face's
  edges are its own). Each has a reference part now (`a dome with a floor`,
  `a cup's floor`).
- *fillet*, *chamfer*: an item just drawn has one of its edge sets rounded
  (three times in four) or bevelled one time in seven or so, from a stream
  of its own (`forge-eval roundings <seed> <k>`): a first block's
  `vertical`, `top`, `bottom` or `all`; a standing block's or post's
  `vertical`, `top` or `joint`; a first cylinder's `top`, `bottom` or
  `both`; a boss's `top` or `joint`; a plain hole's `top`; a pocket's `top`
  or (blind) `bottom`; a quarter of the most it could be or less, 0.3 mm or
  more. A rounded body that is hollowed, or anything in a hollow, isn't
  drawn yet. Its truth is made last, in the plan's order (frame.md), with
  the threads': along a straight edge between faces at right angles the
  corner the round (or the bevel) takes away or fills
  (`forge_eval.truth.Corner`), round a rim the same turned about its axis
  (`RingCorner`; a rounded corner's quarter of a pocket's rim), each exact;
  where two rounded straight edges meet at a corner the definitions bound
  the shape rather than give it (fillet.md), and the truth leaves a cube
  round the corner unsaid (`Truth.zones`). From then on what it takes stays
  clear: a rounded edge's faces keep things further in from it (`margin`,
  `rim`; a vertical edge's round, the far face's corner), and a rounded
  joint, mouth or rim takes up room round what it rounds on the face; and
  no solid of another item, made before it or after, reaches within half
  the gap of a box round any of its pieces (an edge another item cuts
  across is rounded only where it is left, which the truth doesn't follow:
  a deep hole from another face through a pocket's floor, say). Mutants:
  its radius or size, and another of the item's edge sets. Two on one
  box, now and then (four times in ten after its vertical edges are
  rounded): its top's, its base's or its joint's edges then follow the
  rounded corners (edges.md), straight runs and a quarter of a ring round
  each corner's axis, smaller than the corner's rounding: all exact, with
  no zone. One already rounding (or bevelling) edges another would is no
  part; nor is rounding what meets bevelled vertical edges. A first block's
  own roundings are drawn before its shell (they are made before its
  hollow, frame.md), and a block whose vertical edges are rounded or
  bevelled is hollowed half the time: its hollow's corners round the same
  axes, the walls' thickness less, or are bevelled to keep the walls'
  thickness, (2 − √2) times it less (shell.md; sharp where that is
  nothing; the hollow then an outline of eight sides pushed along z), its
  inside faces keeping clear of them; only its top or base may be open, and
  nothing else of a body it hollows is rounded, for now. (Bevelled ones
  came later: the kinds' pairs counted over the 10,000 had a chamfer and a
  shell together 35 times, short of 14.1's 50; now 57.)
  For the meshes (tests/v2_truth.py), a piece's round has no vertex where
  it touches a face (a side from there would graze the face, and a hair's
  difference between them makes slivers), its vertices start a different
  part of a step on by the way it runs (two pieces that meet have none at
  one height), a bevel's line runs on behind both faces, and a straight
  run stops a little more than its size short of a corner in a zone (two
  runs' rounds are tangent at the corner). A rounding's pieces round a loop
  of straight runs and rounded corners (a pocket's rim, a box's top round
  its rounded corners) are made as one mesh, its section swept once round
  the loop (each corner's points a quarter of a step on): pieces whose
  round surfaces run on into each other are never left to a boolean. One fault in the judge this
  found, fixed: a bevel of an inside edge (a pocket's floor, a joint) had
  each leg's uncertainty negative, and its measurement failed to be made;
  `bevelled inside` is its reference part.
- *flush*: one block or post in four standing on a rectangle (one copy,
  from a stream of its own, `forge-eval flush <seed> <k>`) stands flush
  with one of its sides, or with two (in a corner): 0 from that edge, to
  its own (place.md), its side in the plane of the face's side there, so
  the two make one face. Its joint isn't rounded (along a flush side there
  is no corner, edges.md). A side a rounding has taken takes nothing flush.
- *overhang*: a single block standing on a rectangle may reach past its
  sides (frame.md: a body may overhang the face it stands on, but must meet
  it), by half a millimetre at least, staying over the face by a millimetre
  at least; one in three (not flush) is offset to on purpose, from a stream
  of its own (`forge-eval overhang <seed> <k>`), and a position near an edge
  may make one too. Under its far face is its own height only, and nothing
  goes through it; its joint isn't rounded. Its truth is the block from the
  face's plane up and, where it is over the face, its foot run a hair into
  the face and out of it, its sides a micron in from the block's and the
  face's edges (so nothing hangs under the overhang, and no side of the
  foot lies within a rounding error of one of theirs in a mesh); what hangs
  past each edge is kept clear of everything else made before or after (a
  post on the plate below, taller than the block's host, would run into
  it), but what stands on it or is cut into it. Only over a plain
  rectangle: none of its corners or sides taken by a rounding.
- *a boss touching an edge*: a single boss standing on a rectangle touches
  one of its sides, or two in a corner (0 from that edge, to its edge:
  place.md), one in seven, from a stream of its own (`forge-eval tangent
  <seed> <k>`): its round side tangent to the face's side at one point. Its
  joint isn't rounded.
- *standing round a rod*: what is drawn round a rod's side (a cylinder's, a
  tube's outside) is a boss or a post standing round it about one time in
  three, from a stream of its own (`forge-eval round standing <seed>
  <k>`): out along a frame axis (0, 90, 180 or 270 degrees: place.md, for
  now), one copy or a circle of two or four, its length round the side and
  its width along the axis, placed along the axis as a hole round a side is,
  no wider round than half the rod's radius. Its height is from its point
  on the side's surface; its truth runs on into the rod past where the side
  curves away under its foot (the side's sag across its round extent, and
  `REACH`), all of it in the material (a tube's wall must hold it, a gap
  clear of the bore). Only its far face takes anything, over its own height
  (place.md, for now). What stands out is kept clear of everything else made
  before or after (but what stands on it or is cut into it), and of the
  holes round the side as holes are of each other; a rounding of the rod's
  rim and a thread on the rod keep clear of it. Mutants: its angle a
  quarter or a half turn round, as well as its sizes and place.
- *holes out through a wall from inside*: a cut through on a hollow's inner
  face goes on out through the wall (its exit the outer face's), as drawn
  since shells were.

**What building, judging and grading these found** (each kept as a plan in
`tests/v2_regressions.py`, built, judged and graded in
`test_v2_plan_build_generated.py`):

- *Posts in a circle round a rod* (77): the judge measured every copy's
  length and width along the first copy's axes, though copies round a side
  face different ways. Each copy's sizes now run along its own axes.
- *A box flush with an edge of a hollow's inside face* (50): its side there
  is pressed against the wall that rises from the edge, so it is a face of
  neither the part nor the wall, yet the judge took it for one wherever the
  oracle put the plane on the surface (it is on the surface of each item).
  A plane is now on the part's surface only where it parts the part from
  air (in behind it, out ahead of it, a micron either way), and a box side
  that isn't is no side to fit. The generator registers no face there, so
  nothing stands on it or cuts into it (a cut's mouth against the wall would
  be a sealed void, its truth carried a hair on into the wall).
- *A boss touching an edge inside a hollow*: it would lie along the wall that
  rises there, touching it along a line: the generator touches only edges a
  face falls away from.
- *A point beside raised letters* (76): OpenCascade's classifier, its one
  ray at a time, put a point most of a millimetre from every face inside the
  part. The B-rep view of a part of analytic faces now reads a point's side
  off three rays of its own first (`forge_occ.view`, `_by_rays`: the first
  face each crosses, entered or left; all three must tell and agree), and
  asks the classifier only where they don't; it is faster too (about half
  the time a point).
- *The grade's grid* lay along a part's faces (both on the thousandth-of-a-
  millimetre grid), where the truth's answer on a face's very boundary made
  a crossing of nothing (a hole's far end a hair short of its face): it
  starts at irrational shares of its step now.
- *dome* as the first body, one time in twenty-five (30 to 100 mm across):
  its flat face takes cuts and standing items; a blind cut there must fit
  under the dome at its farthest from the centre (its height over a point,
  frame.md).
- *For the meshes the reference parts are made of* (tests/v2_truth.py), a
  standing dome's outline runs on a hair into what it stands on as the ball
  it is part of, and a whole ball's arc is drawn in two, split below its
  equator, so no polygon corner of either lies in the face it stands on; a
  thread's mesh runs on a hair before its start (into the plain rod, or what
  the rod stands on) and the rod's stretch it replaces a hair past its free
  end, its crests 2 microns in: no plane or surface of one all but lies in
  another's, and none of the first 40 generated parts' meshes is unsound.
  The meshes are read out of manifold3d in the double precision it works in
  (`tests/v2_meshes.py`, `exported`): its single-precision mesh rounds each
  coordinate to about seven figures, which brought vertices a few nanometres
  apart onto one point where a block overhanging a face meets it, leaving
  triangles with no area (the overhanging parts' meshes were unsound until
  then).

- *text*: three parts in ten get a line of 1 to 8 letters (mostly capitals
  and figures, now and then any letter the font has; a space only within
  the line), a capital 3 to 10 mm tall, engraved or embossed 0.3 to 1.5 mm,
  on any flat face of the part as made, placed as any item is. What it
  covers on the face is its ink's box, as the solver and the judge hold it
  (7.1); engraved, it is a blind cut a cut from the far side may not all
  but break into. Its truth (`forge_eval.truth.Letters`) reads the font's
  table with its own TrueType decoding and its own nonzero winding (tested
  equal to the judge's on random points, and its ink's box to both
  programs'). Mutants: its height and depth, its mode the other way, its
  words with one letter the font's next, its face, its place; its words and
  height are held by face accounting, which the mutant test then asks.
- *thread*: one part in five gets a threaded stud: a boss of a metric size
  (M3 to M12) standing on a flat face, and a thread on it, coarse or (one
  in four, where ISO 261 has one) fine, right-handed three times in four,
  over its whole height or part of it. Its truth is the zone
  (`forge_eval.truth.Threaded`): the core within the minor radius is the
  part's, nothing past the major is, and between them the truth doesn't
  say (`Truth.unsure`), so no test compares sides there. Built as a mesh,
  the stretch is twisted from the basic profile's section; built exactly,
  cut by the build's own groove (`forge_occ.ops.threads.groove`), whose
  points are in the zone. Mutants: its designation's pitch (coarse for
  fine, fine for coarse), its hand, its length (a whole-rod thread made
  part-length). The judge fits a threaded rod's side only where it is
  plain; with less than 1 mm of it plain, its diameter and place are held
  by its thread's check.

### 12.3 Graded against the generator's model

Both ways, as the plan grades (4.6):

- **The built part's surface** (its coverage at 0.5 mm): each point's
  short segment along its normal, 0.01 mm either way, must cross the
  truth's surface the same way round (inside behind, outside ahead),
  outside the truth's zones.
- **The truth's surface** (each of its solids' surfaces sampled at 0.5 mm,
  kept where the truth says it is the part's surface): each point must be
  within 0.01 mm of the built part (`near`, 13.1).
- **Points in every copy's box:** 200 drawn in each item copy's box grown by
  1 mm, on the same side in the truth and the built part, outside zones and
  0.01 mm clear of the truth's surface; and the volume within the truth's
  interval.

**As built** (`forge_eval.grade`, `grade(truth, built, exact=...)`):

- *The truth's surface* is found where the lines of a grid 0.5 mm apart
  cross it (`surface_of`): each crossing placed to half a nanometre by
  halving the grid's segment, asking the truth alone. So no kind of solid
  needs a sampler of its own, and only the part's surface is sampled (where
  one solid's face lies inside another, no line crosses it). A crossing
  whose search met a point the truth isn't sure of is left out: a zone's
  edge (a thread's ring, which the truth takes away, ends at its minor
  radius) is no surface of the part.
- *The built part's surface*: a point tests something only where both ends
  of its segment are clear of the truth's other surfaces by 0.005 mm,
  looked round from along the axes and the cube's diagonals (looked round
  along the axes alone, a point on an edge of a box stays on one face's
  plane or the other's and never sees which side it is on), and of the built
  part's other faces (asked only of the segments that would fail: at an
  edge, or in a sharp inner corner of a letter, the segment runs on into the
  material across). The rest are counted as unsettled. Where the truth's
  own surface is nearer than 0.01 mm (an edge meeting its own face at a
  shallow angle; the tip of a letter's stroke, thinner than the segment is
  long; a knife edge of material between two strokes), a point whose
  segment doesn't cross passes if, at a distance halved again and again
  (to 2^-20 of 0.01 mm), the truth is air somewhere ahead of it and
  material somewhere behind it, along its normal or one of 270 ways round
  it, each on its own side of the point's plane (two letters touching at a
  corner: the line ahead of one's face runs into the other), or material
  ahead of its plane along one of them with air a step of that distance
  along the normal from it; or, where none of those finds it, one of 1,280
  ways just off the point's own plane (tilted 10, 3, 1, 0.3, 0.1, 0.03,
  0.01, 0.003, 0.001 and 0.0003 degrees to either side, round 64
  directions in it: the 270 are some 13 degrees apart, and where a bore
  grazes a face its edge meets the face at a degree or so, part 8675;
  where an edge's two faces are tangent, a pocket's rounded corner
  touching another pocket's wall, the material between them is a cusp
  s / 2r across at s from the edge, seen by the finest tilt at 0.005 mm
  for r up to 470 mm, and from the rounded face it lies ahead of the
  point's plane, so only the step along the normal finds the air past it,
  part 9213): the truth's surface, facing the way the point's does, that
  near (or twice it). The truth alone decides, so a face of the built part
  inside the material (two halves not joined), in the air (a skin) or
  facing the wrong way fails at every distance.
- *The volume*: the built part's interval must meet the truth's exact model's
  (`tests/v2_truth_occ.py`), widened by all the zones could hold (their
  boxes, and each thread's ring).
- Graded so, every generated part built in the tests passes
  (`test_v2_plan_build_generated.py`, the widened sorts included), in about
  10 seconds a part; a hole moved 0.05 mm, a pocket 0.02 mm shallower and a
  hole left out each fail the tests that see them, as do two halves of a
  plate not joined, a skin in the air and a face turned inside out, and a
  wedge 20 degrees across passes along its edge only with its material
  looked for round it (`test_v2_eval_grade.py`). To speed the truth's answers, each solid is
  asked only about the points in its box.

## 13. Fast enough

### 13.1 What it costs now

Measured here on generated parts 0 to 2 as exact B-reps, the whole judge
takes 64 to 81 s a part: 41 to 65 s of it is face accounting asking the
B-rep's distance to 170,000 points of the spec's surface one at a time
(`BRepExtrema_DistShapeShape`, 0.36 ms a point); 3.7 to 6.2 s covering the
B-rep's surface at the checks' radius; the oracle, the check suite and
the rest a few seconds. At that rate the exit test would take weeks.

### 13.2 Four changes, each exact

1. **`near(points, t)`**, a new `GeometryView` question: whether each point
   is within its `t` of the surface (accounting's spec side asks only
   that). Its default is `distance(points) <= t`. The B-rep answers it with a
   certificate first: for each face whose box grown by `t` holds the point,
   the point's foot on the face's surface in closed form (planes,
   cylinders, cones, spheres, tori), and the foot's parameters classified
   on the face by its boundary as read in 2 below: a foot surely on the
   face (inside it, or within 1e-9 of a straight or circular edge in its
   parameters) and within `t` proves the point near. Never OpenCascade's
   ON here: it reaches as far as an edge's tolerance, which would count a
   foot past a loose edge. Where the boundary as read leaves a foot unsure
   (within the band round a curve it follows, or on a face it can't read),
   OpenCascade's classifier settles it by its IN alone: by a thread's
   helical edges on a 49 mm boss the band was 2.4e-3, and 50,489 points of
   generated part 171's spec went to the exact distance at 2.9 ms each,
   62% of its judging (the exit run's shakedown); now none does. A point
   in no grown box is far; any other point gets the exact distance, as
   before. That band was then narrowed (2 below), and the B-rep's own
   distance found wrong beside it: OpenCascade's classifier calls a point
   on a face within its tolerance of a curved edge on the edge, and
   measures to the edge (on embossed letters' tops, a point 4.9e-6 mm in
   from where two Bézier edges join measured 4.9e-6, not 0). So the
   B-rep's `distance` is OpenCascade's, or nearer where the point's foot is
   surely on a face, a point of the surface, never nearer than the truth;
   and `near` is that distance's within `t`, exactly. A mesh answers it
   by its own tree: each triangle whose box is within `t`, measured as the
   nearest search measures it (the same rounding, so the same answer),
   until one is near enough; 2.3 times as fast on a part's spec side
   (generated part 30's STL, a million points: 21 s against 50). Tested
   against `distance(points) <= t` on analytic solids, a fillet, the
   clevis, the zoo, letters cut and embossed, and a plate round a B-spline
   hole, on, just off and far from their surfaces: never a different
   answer.
2. **Covering a face** evaluates its surface for all its parameters at
   once, in closed form for the analytic surfaces, and finds which grid
   points are on the face all at once (`forge_occ.uvclass`): the face's
   boundary is read once in its parameters as pieces monotone in u
   (straight; circular arcs cut at their least and greatest u; any other
   curve followed by a polygon fine enough that the band round it, four
   times its measured error, is a millionth of the face's parameter box,
   up to 4,096 pieces an edge: a ten-thousandth at first, which left a
   thread's crest unsure all along it, generated part 171), each
   end joined to the nearest start so the chains close exactly, and each
   point classified by the parity of the pieces crossing the ray above it,
   half-open in u so a vertex or a touching circle counts as it must. Within
   a followed curve's band OpenCascade's classifier is asked. Equal to
   OpenCascade's classifier at all 15 million grid points of generated
   parts 0 to 79 at two radii, and on every face of the zoo.
3. **The oracle settles points on surfaces many at once.** A point whose
   facets' normals lie along one line (on one surface) or two (on an edge)
   has two or four cells of directions round it, one for each sign of
   `d·n1` and `d·n2`: each leaf's answer in each cell is read off its model
   for all such points together, and the steps replayed on those answers;
   a corner keeps the replay one point at a time. Points' sets of steps are
   grouped by a signature, each member checked against its group's first
   step by step. The same answers as one at a time on every reference
   part's surface points and step corners.
4. **Shared work:** the oracle, the placement and the check suite are made
   once per spec and kept for its mutant, whose judging stops at its first
   FAIL.

### 13.3 Many copies

`Names` (stage 3) rebuilt its face index on every lookup and scanned every
face for a role: quadratic in a plate of 2,000 holes. It now builds both
indexes once per shape. `between` matched edges by `IsSame` over every
pair; it now uses an indexed map of the second face set's edges.

### 13.4 Pointed cones

A cone's apex is a point the oracle can't classify (no tangent plane), so a
built point there was "unsure" and every pointed cone was held. The oracle
now bounds a ball of `OFF` (its own surface tolerance) round an apex: a
point within it passes as bounded, as at a rounding's corner.

### 13.5 Between the forms, on their surfaces too

A built point passes as bounded where it lies between the spec's two forms;
measured to the inner form's ON and the outer's ON too where the other is
clear of it (a chamfer's mitred corner lies on the outer form, where the
inner form is cut back round the corner): the closed band the spec lets the
surface lie in. Found by the post and its joint, whose built mitres the
strict band refused.

A face's edge, measured as the plane of the wall or side there (the
place checks' reference), is told a wall from a side by the part as it is
before its roundings: just past the edge under the face's level is where a
joint's fill under an overhang sits, which the finished part holds.

### 13.6 The budget

Measured, not promised: each change lands with its timing on generated
parts 0 to 9 before and after, in `docs/V2-stage4-exit.md`. The target is
the judge of a generated part under 10 s here; then 10,000 parts and their
mutants within two days of both cores, run as two worker processes with
results appended to a record a restarted run continues from (14.1).

### 13.7 A million points, a share at a time

A part with a small feature has a small coverage radius, and its B-rep's
surface is covered by as many more points (generated part 9: 1.6 million at
0.154 mm). Settling the ones on the spec's surface held every facet's
normal of every solid round each of them at once: 6 GB, and the exit
script's process was killed. The oracle now settles a view's points 100,000
at a time (`forge_checks.oracle.AT_ONCE`), the models it has found alike
shared between the shares, and the answers the same.

### 13.8 Measured again on generated parts 0 to 8

The whole judge of a part as an exact B-rep took 7 to 81 s (radius 0.5 to
0.125 mm), most of it face accounting and the checks. Four changes, each
giving the same answers:

- **The directions round a point on several surfaces** (13.2's third
  change) were worked as numpy arrays of three: a corner's thousands of
  them cost more to hold than to work. In plain floats, ten times faster
  (`forge_checks.oracle.probes`), the same directions to rounding, tested
  against the old on 20,000 random sets of planes.
- **A part's few steps** (32 or fewer) are tried against each point's box
  in turn, not walked down a tree (`forge_checks.tree.FEW`): twice as
  fast.
- **A window of built points** (a check's round surface, ball, plane) is
  read off the points sorted along the axis its surface's box is thinnest
  across, not out of every point (`Probe._near`): every check's measurement
  on parts 0, 2, 3 and 6 the same to the bit, the checks a third faster.
- **A coverage is made once** for each radius and kept, read-only: the
  B-rep's (the checks' probe and face accounting covered it alike), and the
  spec's (each of a build's four views is accounted for against the same
  points).

### 13.9 A share of the cells at a time

Covering the spec's surfaces split every surface's cells round by round,
all of a round's together: at a fine radius on a part with letters, seven
million cells, each holding its corners and its surface's side either way,
and the exit's workers, each allowed 2.7 GB, ran out of memory on two parts
in the first 137. The cells are now settled 200,000 at a time
(`forge_checks.oracle.CELLS_AT_ONCE`), in order; each cell is settled on
its own, so the points kept, their normals, their surfaces and their order
are the same as all at once, to the bit (tested on 36 parts, a share of 397
cells against all at once). The most a worker held making a part's record,
before and after: part 110, 3,216 and 1,697 MB; part 81, more than 2,700
(it ran out) and 1,456; part 9, 2,699 and 1,303; the time the same.

### 13.10 Resolution where it is needed

The exit's shakedown (14.1) ran parts out of memory that need fine
resolution at one small feature and got it everywhere. Run again alone with
5.5 GB, as the exit run would: part 1295, 106 mm across, whose revolution's
outline has a 0.11 mm arc, had its B-rep covered at 0.056 mm all over (21
million points) and still ran out; part 1325's spec surface took 33 million
points; part 2000 passed, but took 5.2 GB and 11 minutes meshing an 82 mm
half ball at the 0.00057 mm a 7.6 mm countersink's angle asks of its own
cone. Each fine size belongs to one item, a few millimetres across (1295:
3 by 13 by 3 mm). So the resolution is made local to what asks for it.

**The coverage radius.** Each size the compiler notes for the radius (5.8)
is noted with its item, and holds where the item is: round each piece of
each of the item's steps (`forge_checks.csg.pieces`: the box round each
solid the step is made of, cut to where the rest of it lets that solid's
surface be the step's: within an intersection, where each other part may
be; a difference's taken part, where its whole may be; so a rounding's
pieces are its strips along the edges, not the body they are cut from,
and a step of more than 256 pieces is held by its own box), grown by
0.5 mm and the size itself (a wall's far face). The radius at a point is
half the smallest size whose box holds it, never more than 0.5 mm; a size
whose item makes no solid holds everywhere. The check
suite carries the radius everywhere (0.5 mm, or the sizes that hold
everywhere) and the finer boxes, each with its item and radius
(`CheckSuite.finer`, `CheckSuite.resolution`; `forge_checks.view.Resolution`).

- *A view's coverage* (`forge_checks.view.covered`) is its coverage
  everywhere at that radius, and in each finer box at the box's radius, the
  coarser points more than the coarser radius inside a finer box left out
  (the finer covers all the surface there, and every point outside it is
  still within the coarser radius of a coarser point outside it), and a
  point boxes that overlap give again (the same place on the same face or
  triangle) kept once. A B-rep keeps each box's coverage, so the checks
  and face accounting share it, and each face's grid at a radius, so many
  boxes share that. A view
  asked to cover within a box covers only near it, as the protocol has
  always allowed ("points of it near the box may come too"): a B-rep face
  by the pieces of its parameters that may reach the box, halved until no
  wider than a quarter of it (a piece's points are within
  `(Lu·Δu + Lv·Δv)/2` of its middle's), the whole grid's points of every
  cell that meets one, and its edges' samples within the radius of the
  box: the very points the whole grid has there; a mesh by its triangles
  that meet the box, each split in four at its sides' middles until its
  pieces are no wider than a quarter of the box (or four radii), the pieces
  whose own box misses it dropped.
- *The spec's coverage* splits each cell until it is no wider than the
  radius wherever it may reach (its middle's reach), and down to a
  sixteenth of that where surfaces meet.
- *The probe and face accounting* use both coverages so made; a
  measurement taken again finer is four times finer than the radius where
  it looked. The verdict states the radius everywhere and the finer one
  round each item that asks for one.

**What it guarantees** (V2-stage2.md, 5.4) is then stated per place: a
departure of more than `t` across any patch `h` wide is found, `h` the
radius there. At every feature `h` is what it was; away from the small
ones it is what a part without them has. Surface wholly missing or extra is
found anywhere, as before: every face and triangle, and every trimmed
piece of the spec's surface, is reached whatever the radius.

**The meshes' tolerance** (9.4) is local where a check is measured on its
own surface alone: a diameter (a round surface, a cone's end, a ball) and a
cone's angle ask their need in the box round that surface, grown by 1 mm,
where finer than the rest ask everywhere; every other check (a position, a
size between two faces, a depth from a face round a mouth) still asks
everywhere, as its windows lie on other items' faces. Each face whose
surface may come within the coarser tolerance of a finer box (the same
halving of its parameters, `forge_occ.view.may_reach`: an 82 mm dome's face
doesn't come near a countersink in its base) is meshed first at the box's
tolerance, then the whole part at the coarser (OpenCascade's mesher keeps a
face's finer mesh and its edges' polygons). The finer faces are meshed in
groups of those that meet along an edge, each group at its finest: the
mesher, meshing one face on its own, discretises its edges afresh to that
face's deflection, so two finer faces meshed apart at two tolerances had
different nodes along the edge they share, and the weld tore (part 4180);
each face is refined and measured against its own (`face_tolerances`).
The STL and 3MF can't carry a tolerance per triangle, so the judge works it
out as the reader does, from the spec alone (`ExportTolerance.of_triangles`,
`file_view`): a triangle that meets a finer box is held to the box's
tolerance (it lies on a face meshed at it, or finer), any other to the
coarser; the file read back is refused if a triangle's face was meshed
looser than that.

**The same as before** where no size is under a millimetre and no own
surface asks finer than the rest: no finer box, and the coverages, checks
and meshes are as they were, to the bit (the whole coverage path, the
mesher's single call). **Tested:** a resolution's radius at each place and
its coverage on a plate (every point of a dense sampling of its top within
the finer radius in the box, within the radius elsewhere; the coarser
points deep in the box left out; with no finer box, the view's own
coverage); a B-rep's coverage within a box on a drilled plate, round a
ball's pole and across its seam, and on a B-spline ball (the very points
the whole coverage has in the box, and under three times as many in all);
a mesh's within a box on a plate of 12 triangles (every point of the
surface in it within the radius, each point on its triangle with its
face's normal, under 40,000 points where the whole plate at that radius
has 7.9 million); the spec's coverage finer in a box (every point of the
surface a line finds within the radius there); a small hole's finer box
round itself alone; a probe looked at again finer in and out of a finer
box; a countersink in a dome's base meshed finer than the dome, each face
within its own, the file read back held to what a reader works out, and a
mesh made to the coarser alone refused.

**Measured** (each worker given 2.4 GB, two at a time; before, each part
alone with 5.5 GB):

| Part | Before: most memory, time | After |
|---|---|---|
| 738 | 2,367 MB, 166 s | 1,361 MB, 85 s |
| 1266 | 2,542 MB, 401 s | 1,132 MB, 138 s |
| 1295 | ran out of 5.5 GB (21 million points) | 954 MB, 105 s |
| 1300 | 2,910 MB, 358 s | 1,110 MB, 100 s |
| 1325 | ran out of 5.5 GB (33 million points) | 1,018 MB, 70 s |
| 1892 | 2,435 MB, 185 s | 960 MB, 83 s |
| 2000 | 5,179 MB, 662 s | 1,508 MB, 156 s |
| 2021 | 2,773 MB, 345 s | 1,034 MB, 161 s |

The exit run's first 474 parts on the first cut of this showed part 405
(a body rounded along all its edges, 0.35 mm) at 2,315 MB where it had
taken 1,959: the rounding's box was the whole body, so a finer box covered
all of the part on top of the coarser coverage, and twice (the checks'
probe and face accounting each made it). Its box is now its strips along
the edges (`csg.pieces`), a B-rep keeps each box's coverage, and the part
takes 1,787 MB and 259 s (269 s before).

Still seen on part 1325: its revolution's concave arc is taken away by a
ring meeting a square round the arc's disc, and that square's side came
0.0005 mm under the part's base (the arc's radius times 1.25, and a
millimetre, from its centre's height), a surface of another solid within a
cell's reach of the whole base: the spec's coverage there split to its
finest, 2.1 million points at 0.5 mm (13.11).

### 13.11 A solid of revolution beside a cell

The spec's coverage keeps a cell whole where another solid's surface comes
within its reach but surely doesn't divide it: shown for a convex solid
from its convexity (V2-stage2.md, 5.4), never for a solid of revolution,
nor for a cell on a cone's band, a flat ring, a torus or a ball (how far
such a cell bends from flat wasn't bounded). Both are now:

- **How far a cell bends** is now bounded two ways: from the flat cell
  through its middle (what a solid's distance there is measured against),
  and from the flat pieces between its corners (what its corners stand
  for); a flat ring's cell lies in its middle's plane, but its arcs bulge
  past its corners' piece in that plane. A cone's band's cell (a flat
  ring's, a cylinder's) bends no more than `size_v²/8R`, its arc round the
  axis measured at its largest radius `R` (an arc at radius `r` turns
  through `size_v/R`, and strays `r(1 - cos(a/2))`; the band's straight
  lines lie two by two in a plane), a flat ring's not at all from its
  middle's plane. A torus's cell bends no more than
  `size_u²/8(R + r) + size_u·size_v/4(R + r) + size_v²/8r` both ways (its
  surface's second derivatives, in those lengths, are at most `1/(R + r)`
  round the axis and across and `1/r` round the tube: Taylor's remainder
  from the tangent plane, and the bilinear piece's error and twist from
  the corners' flat pieces), and a ball's `(size_u + size_v)²/8r`.
- **A solid of revolution's** signed distance is its outline's, `f(r, z)`,
  at a point's distance from its axis and height along it, and `f` is
  convex. A step `δ` from a cell's middle changes `z` by `w·δ` and `r` by
  at least `e·δ` (`r` is convex in the point; `e` the way out from the
  axis there) and at most that plus `|δ|²/2(r0 - |δ|)`. So outside the
  solid, `f` over the cell is at least its middle's value less the 3D
  gradient along the cell times its reach, less the bend, less `-g_r`
  times `reach²/2(r0 - reach)` where the outline's gradient points
  towards the axis; inside it, at most its greatest at the corners of the
  rectangle of `(r, z)` the cell's points may have (`r` within the reach,
  `z` within the reach times how far the axis runs along the cell, and the
  bend). Tested on 12,000 cells beside four outlines (a cylinder, a ring, two
  cones' points on the axis, a pentagon), each one said clear sampled 400
  times on one side; and on 1325's base above its square's side.

Part 1325's spec surface at 0.5 mm: 2.1 million points in 15 s before,
287,000 in 5.9 s after; part 738's (a 98 mm dome, an M3 boss and four
fillets): 461,617 points in 11.2 s, 425,329 in 9.2 s. The radius at a
cell's place asks only the finer boxes that come near the cells settled
together.

## 14. The exit test

### 14.1 10,000 random specs

`tests/v2_exit4.py --from 0 --to 10000 --workers 2` (resumable: one record
per seed in `runs/stage4_exit/records.jsonl`; the report in
`runs/stage4_exit/report.md` and `docs/V2-stage4-exit.md`). For each seed:

1. `generate(seed)` (up to 8 items): its brief and draft checked
   (`check_draft`), locked as a draft (`lock(..., by="draft")`: the
   generator is both writer and reader, so its assumptions are kept, as
   `--auto` would keep them for a person to see), the oracle made, planned,
   built with alternatives.
2. **All pass:** every detector of 9.2 on the B-rep passes, and the part is
   graded against the truth (12.3). An UNABLE fails the exit (the generator
   draws no gap of 4.9, so none is expected); so does a refusal of every
   construction of any item.
3. **No mutant survives:** one leaf mutant (`mutants(case)`, the k-th with
   k = seed mod their number), compiled and built the same way, judged by
   the original spec's judge: a detector must fail it. Whether a mutant
   changes the shape is decided exactly, never by sampling: the generator
   knows which changes leave it (a through hole moved to its far face), and
   for the rest the two truths are built by OpenCascade (`tests/v2_truth_occ.py`)
   and their symmetric difference measured, unless they are already shown
   different: their volumes differ by more than the measure's interval, or
   a point of one's surface is farther than 1e-5 mm from the other's
   (measured exactly; a few hundred of its coverage's points are asked, so
   a sample can show two solids differ, never that they are the same).
   A boolean between two threads of opposite hands ran 15 minutes and more,
   and the seed's worker died of a segfault (part 7858). A mutant in a zone (a thread's
   hand or pitch, a rounding's radius) always changes the shape and is
   counted on its own line. A mutant the solver refuses is a fault of the
   generator's, and fails the exit.
4. **The impossible ones are turned back:** every tenth seed also draws
   `impossible(seed)`; its draft must end at the spec checks as a brief's
   would, CAN'T or a question resting on the brief's values, never one of
   the writer's faults (or at the oracle, before building, where the rule
   broken is the oracle's), with the reason the generator gave (12.1).
5. Every tenth seed also runs the second kernel's agreement, exports STEP,
   STL and 3MF, and judges the re-opened files.

As built, the script (`tests/v2_exit4.py`) grades each part as asked with
12.3's grader (`forge_eval.grade.grade`, both ways, the volume against the
truth made exactly), judges each mutant only as far as its first FAIL, the
cheapest detector first (`Judge.first_failure`: the checks, the topology,
the volume, face accounting, the fresh probes; 13.2), and counts an
impossible part as turned back only when it ends CAN'T or a question, never
a fault of the writer's; a seed fails the exit by any of its four parts
(the part not passed, its mutant surviving or not built, its impossible part
built or ended at a fault, its second kernel or a file not passed:
`failures`), and the report's opening and the script's exit code say
whether any seed does. The seeds are run by worker processes, each given
ten (a fresh process then takes over, so no worker's memory creeps); a
worker killed for want of memory, or making no record for an hour, is
recorded as a fault of the seed it was on, and its other seeds go to the
next, so one part can neither stop the run nor hang it. `--memory` bounds
each worker's data (two workers here share 6 GB): a part that needs more
is recorded as running out of it, its worker ends and a fresh one takes the
rest, and `--again` runs each seed whose record fails the exit again, with
one worker and more memory, its record replaced. `--views-first` runs the
seeds that also run the second kernel and the files (every tenth) before
the rest, each in order, so a fault in the files or the views shows on the
run's first day; the counted run is made so.
`tests/test_v2_exit4.py` runs seeds 9 to 11, resumes, and reads the
report; it gives each way of failing to the report, a stand-in worker that
is killed on one seed, hangs on another and runs out of memory on a third to
the runner, a record file with failed seeds to `--again`, and one with a
seed done to `--views-first`.

**The pilot**, seeds 0 to 99 before the 10,000, found six parts wrong, each
fixed at its root and kept (`tests/v2_regressions.py`, built, judged and
graded in `test_v2_plan_build_generated.py`; the countersink in
`test_v2_build.py`):

- *Parts 20 and 40, held on their meshes:* a countersink's 90° measured to
  ±1.6° for ±1°; the meshes are now as fine as a cone's angle needs (9.4).
- *Part 61, no judge:* a pulley standing on a hollowed block's side; a grid
  line of the void count along the pulley's axis met its flat ends as a
  square's double root, a micrometre off, and missed them, so the line ran
  on in material past the part. A revolution's flat side is now a plane,
  met exactly, and any place found to half the digits is polished onto the
  surface by Newton's method (`Solid.crossings`): one step at first; now up
  to three, from anywhere past 1e-12 mm of the surface, so that a place lands
  on its root and not only within a micrometre of the surface, which along a
  shallow line left it up to 8e-8 mm off, a sliver between it and the same
  place found exactly.
- *Parts 53, 83 and 93, graded wrong, judged right:* built points the
  grader's segment along the normal can't test: on the shallow edge where a
  through hole breaks into a pocket's ceiling (its end just past nine
  tenths of the reach from the ceiling), and at a letter's stroke's tip,
  thinner than the segment is long. The grader first left such a point
  untested where the truth's surface was within its reach, or where the
  built part's own segment wasn't across it; a review found that let the
  built part excuse its own faces (two halves not joined, a skin in the
  air, a face turned inside out), each now a test the old rule fails. The
  segment is now shortened by halves where the truth's surface is nearer,
  the truth alone deciding (12.3's first test).

**Started four times before it ran through**, each stopped and its
records set aside, and every seed run again on the fixed code:

- after 137 seeds: two parts ran out of their worker's memory covering the
  spec's surfaces (13.9);
- after 45: a review of the grader found that the built part could excuse
  its own faces (12.3);
- after 120: part 108's letters touch at a corner, and along the line
  where they meet, the line ahead of one letter's face runs into the other.
  The grader now asks, at each shortened distance, for air somewhere ahead
  of the point and material somewhere behind it, each on its own side of
  the point's plane, not along the normal alone (12.3); the part is kept
  (`tests/v2_regressions.py`, built, judged and graded in
  `test_v2_plan_build_generated.py`);
- after 149: part 140, a cylinder chamfered at both ends, held on its
  meshes: the chamfer at its far end measured to ±2 mm for ±0.2. A cone was
  fitted about the body's other end, and its radius at the chamfer bounded
  from there, the radius's and the slope's uncertainties each on its own:
  millimetres on a mesh. Every cone is now fitted about the middle of its
  own stretch, so its radius is known best where its points are (the
  chamfer then to ±0.032 mm on the mesh, ±0.0001 on the B-rep); the part's
  numbers are a test of their own (`test_v2_build.py`).

**Then a shakedown run**, 359 seeds on that code, found nine more parts
wrong, each fixed at its root before the run that counts, and kept
(`tests/v2_regressions.py`):

- *Parts 168 and 275, held:* built points a micrometre past a bore, at a
  radial hole's seam end, counted on a face: OpenCascade's classifier
  called the corner of the face's parameter box ON. A coverage's grid now
  counts its ON as off the face; the face's edges, sampled on their own,
  stand for its boundary.
- *Part 190, the second kernel disagreeing:* its mesh, 96 cells across a
  100 mm block, closed a 1.52 mm hole (genus 3 for 4). Where the mesh is
  sound but the counts differ, it is made again at 192, then 256 cells
  (V2-stage3.md, 13.4); first also where it wasn't sound, until the batch
  of tests ran out of memory on a cone's apex.
- *Parts 219 and 297, no exact model to grade by:* OpenCascade warned
  cutting a pocket rounding's corner, and letters. The truth's builder
  takes a warned boolean only if the result is valid and on the truth's
  side at 4,000 points round the step.
- *Parts 233 and 326, held:* a grid of posts' pitch measured 13.083 for
  12.761. A box's sides were fitted as whole planes, and the pitch's window
  took in the block's bottom, 0.66 mm off; each side is now fitted within
  its own rectangle.
- *Part 244, graded wrong:* a needle's apex. The face's bounds reach
  1.2e-7 mm past it, onto the cone's other nappe, where the normal faces
  the other way; at or by a singular point the B-rep view's normal now
  faces the way the face's do just inside it.
- *Part 319, graded wrong:* a block flush with a hollow's wall, a through
  hole in the wall behind it. The hole's mouth, carried on 0.05 mm into
  what the truth took for air, cut into the block in the exact model. The
  generator now keeps whatever is on a wall off where a box is pressed
  against it, and the other way round.

**Two more shakedowns**, seeds 359 to 909 on the code so fixed, found nine
more parts wrong, each fixed at its root and kept (`tests/v2_regressions.py`: a plan the
generator now refuses is kept with its refusal, in `REFUSED`):

- *Part 423, held:* an M8 thread all along a boss whose block has a hole
  running across 1.3 mm past the boss's foot: the thread's length was read
  where a line down the rod came out of the hole into the block again. Where
  a thread starts is looked for on the rod only, never past its foot.
- *Part 492, held:* a dome's rim on a cylinder's end: the box that took the
  ball's half touched it at its rim, and OpenCascade left an edge 1.9e-6 mm
  long there, its two vertices one within the other's tolerance. The box is
  twice the ball across and deep (4.3).
- *Parts 566 and 655:* a through hole round a hollowed cylinder's side by
  its end, half its mouth into the hollow and half into the end's wall
  (held: the judge couldn't tell where the material ended), or its mouth
  1e-3 mm past the wall's inside (graded wrong by 0.28 mm³: the exact model
  carried the cut on past the mouth). The generator keeps such a hole where
  the bore is, across all its mouth.
- *Part 771, a mutant survived:* a through hole in a flange's hub moved to
  the flange's foot, where the hub runs deeper than the rim: the truth cut
  it the rim's depth, the build right through, the part as asked. A cut
  goes right through only a face every line through comes out of.
- *Part 868, held:* a block's vertical edges rounded, then its bottom
  edges bevelled 5.5 of its 6.8 mm: the fillets were checked all along,
  where the bevel had left only their top 1.3 mm. A stretch of rounding is
  checked where its section's middle is still on the part, or where the
  oracle can't tell (where roundings meet): only air or material there
  says a later step took it away.
- *Part 870, an impossible part built:* "deeper than the material under
  it", a boss's height round a tube's side: the tube's wall is under it
  too. Too deep is drawn only through a face whose way out is known.
- *Part 874, held:* a boss's joint bevelled on a face whose far edge a
  block hangs over: the oracle bevelled the corner under the block too. A
  joint's rounding is kept by the copy that stands there.
- *Part 886, UNABLE:* an M4 boss on the first of a row of two blocks ran
  through the second, and the thread's groove would have cut it. The
  generator keeps a thread's stretch clear of anything but its rod.
- *Part 738* ran out of the 2.4 GB its worker was given, covering a 98 mm
  dome at an M3 thread's radius: four million points. The coverage radius
  was the whole part's; it is now local to the features that ask for it
  (13.10), and the part takes 1.4 GB.

The same run showed where the judge's time went, and it was made faster,
each change giving the same answers (13.2): a foot near a curve the
boundary follows is settled by OpenCascade's classifier, not the exact
distance; the band round such a curve is narrower; and a mesh answers
`near` by its own tree. Part 204's B-rep judging took 215 s, now 51.
Later, compiling a part's checks asked whether each face it measures is on
the part at up to 40,000 points; it now asks 256 at a time, spread over
the face, and stops at the first that is (the same checks for seeds 0 to
59; that question's time fell from 23.5 s to 6.9 s over seeds 0 to 9).

**A fourth shakedown**, seeds 906 to 1072 on the code so fixed, found:

- *Part 950, held on the STL and the 3MF:* a rounded pocket's length on a
  tube's end, its corners' radius 0.989 leaving 0.434 of its ends straight,
  is measured between its corners' edges: each a quarter circle's centre
  plus its radius, whose bounds were added (±0.156 through a 0.005 mm mesh,
  too coarse for ±0.1). A value made of several fitted unknowns is bounded
  as one (±0.024 here), and every fit's bound is taken to second order, a
  short arc's first-order one having fallen short of its worst case
  ([V2-stage2.md](V2-stage2.md), section 6). A reference part's mesh now
  says how far each triangle may be off, a thread's apart: kept part 53's
  0.455 mm fillet could no longer be judged at its thread's deflection.

**A fifth**, seeds 0 to 1109 on the code so fixed (every earlier failure
passed, but part 738 ran out of its memory again), and on from 1110, found:

- *Part 1101, an error:* a needle (a cone to a point) on a block. The exact
  model's cone ended at a radius of 4e-16 mm, a rounding error from
  nothing, and OpenCascade refuses an end's radius between nothing and its
  confusion (1e-7 mm). An end that close to nothing is nothing.
- *Part 1130, held on the STEP file:* a tube's bore, halved for STEP,
  was cut 6e-5 mm from where a small through hole met it, leaving an edge
  that short; reading the file back widened the vertex at its end to
  1.9e-4 mm, over its neighbour. A part whose halves read back held more
  loosely than a step's solid may be is written unsplit
  ([V2-stage3.md](V2-stage3.md), section 12).
- *Part 1159, held:* a countersink 0.64 mm deep. On the B-rep at the
  suite's radius, its points within the cone's stretch were one ring round
  it, which fixes no slope: nothing was measured. A measurement whose
  points fix nothing is taken again finer where it looked, as one too
  uncertain is ([V2-stage2.md](V2-stage2.md), 4.3).
- *Part 1340, an error:* a block's vertical edges rounded 1.351 mm, then
  its top edges 0.879: each corner is a spindle torus (its tube wider than
  its ring), which STEP brings back as a surface of revolution, and reading
  the file back said the part had other faces. It is the same surface, and
  is counted as one.
- *Part 1566, held:* a boss on a standing block's side, flush with the
  block's foot, lay along the plate the block stands on, touching it on a
  line: two solids meeting along an edge, and face accounting found that
  line's points on no face of the part. The generator stands a boss flush
  only with an edge its face falls away from, nothing just past it in
  front of the face (a spec may ask it; the part held is the honest end).
- *Part 1574, held:* an L engraved 1.3 mm deep in an M6 stud's end, its
  corner 2.66 mm from the axis, past the thread's root (2.46): its walls
  stood among the thread's flanks. The rod's material is kept whole where
  its thread is cut, from a wall's width in from the root out, by
  everything made before the thread or after it.
- *Part 2010, failed on the STL and the 3MF:* a shell's wall was measured
  round its face's middle, where a block stood on all of it but a 0.16 mm
  sliver; the STL's coverage had two points there, too few to fit, and the
  wall's inner face was never looked at. A measurement that found too few
  points where it looked is taken again finer, as one whose points fixed
  nothing is; and a measurement of two surfaces looks at both before
  either is judged missing, so finer it covers both. The next seeds
  (2063, 2072, 2077) then ran out of memory judging their mutants: a
  missing surface looked for again finer covered whole the broad faces its
  boxes met. A finer probe is held to two million points over the faces it
  would cover. With the coverage radius local (13.10), the sliver lay where
  the radius is 0.5 mm, and the STL's coverage had no point on it at all:
  a window that comes out empty notes the box it searched, and the
  measurement is taken again finer there too.
- *Part 2115, graded wrong:* a post standing round a tube's side, its
  foot carried 1.5 mm into the wall under the side's curve, over a hole
  drilled along the wall from the tube's end: the truth's foot filled the
  hole's air (4.6 mm3), and the build didn't. What of a standing item's foot
  lies within its rod's surface must lie in the part's material already.
- *Part 2404, held:* a block on each of a grid of blocks standing on a
  block's side, two copies up, so tall that the lower one's ran into the
  upper block; a hole through it, through by its own faces, ran on into
  the upper block's material. What stands on a face stands in air: no
  point within it above the face (past its foot) is in what was made
  before.
- *Parts 1266, 1295, 1300 and 1325* ran out of the 2.4 GB their workers
  were given, as 738 did: the coverage of a part 80 to 106 mm across at a
  radius set by its smallest feature (0.06 to 0.28 mm); and the STL's mesh
  of a 56 mm ball at the 0.0006 mm a short countersink's angle asked. The
  void count's joining of 2 million seeds now takes a corner at a time
  (the same answers), and a worker that runs out writes its record still.
  Run alone with 5.5 GB, 1295 and 1325 still ran out, and 2000 (an 82 mm
  half ball's mesh, for a countersink in its base) took 5.2 GB: the
  coverage radius and the meshes' tolerance are now local to what asks for
  them (13.10), and every one of these parts takes under 1.6 GB.

It also showed the runner judging the working tree's packages, not those
of the copy it was started in (an editable install put them on the path
first); it now puts its own tree's packages first, for itself and each
worker.

**A sixth shakedown.** The run meant to count, started on that code,
found faults of the generator's first. While only the generator was
changed, a seed it now draws otherwise was found exactly (any refusal of a
new rule while drawing its part, its mutants or its impossible part: 32 of
the first 2,541 for 2511's rule, 8 of the first 3,007 for 2995's) and run
again, and the rest stood. At part 3767 it found a fault of the judge's,
which no such argument spares: it went on as a shakedown over the seeds not
yet run, each fault fixed as it was found, and the run that counts started
again from seed 0 on the code with every fix. It found:

- *Part 2511, held:* a line engraved 1.363 mm into a block's top (three
  copies) over round pockets drilled into the block's side, their crests
  0.53 mm under the top: each D's inside came loose, and the part was four
  solids. So was the generator's own exact model, and the part graded right:
  Forge built what was asked and held it, as it should. The fault was the
  generator's, which promises one solid. It now stands every line of
  letters on material: ``GAP`` of the part under its ink, under an
  engraving's floor or an embossed line's foot, whatever cuts there from
  another face (`_letters_stand`, looked at on a grid 0.1 mm apart over the
  ink's box).
- *Part 2995, held:* a hole drilled right through a block along y, then a
  whole ball 15.7 mm across sunk to its middle in the block's top, 6.6 mm
  off the hole's line: its lower half refilled 4 mm of the hole, and the
  depth check found material 24.03 mm in, of 55.3. The truth was the same
  (graded right): the hole went right through only by the definitions'
  order, and the part was held, as it should be. The generator's rule that
  what stands on a face stands in air (2404) looked above the face only, and
  its rule for a rod's foot (2115) at rods: what of a standing item lies
  under its face, past the hair its foot is carried in by, now lies in the
  part made so far, looked at 0.25 mm apart over it and a tenth of each
  earlier cut's box apart where the cut meets it.
- *Part 3151, held:* a counterbored hole into a post's side whose bore,
  past its counterbore, lay wholly in a pocket cut 19 mm into the post from
  another side: nothing of the hole's own bore was built, and its diameter
  and place had nothing to be measured on. Each hole's, pocket's and slot's
  side is now built: a tenth at least of points just past it, spread round
  it and through its depth, in the part (the least of the 1,012 cuts of
  seeds 0 to 149: an eighth).
- *Part 3375, an error:* a row of holes 21.5 mm deep on the top of a cone
  that widens as it rises (16.5 mm across at its base, 19.0 at its top, 7.0
  long), standing on a knob. The farthest hole reached 8.44 mm from the
  cone's axis, past its base's radius: there the cone's flank comes out
  under the top 0.98 mm up, and the solver, rightly, asked whether 21.5 mm
  in 6.0 of material should go through. The generator took a cone's top to
  have its length and what is under it everywhere; past its base's radius
  it now has the cone's own height over the point, from its flank up (as a
  dome's flat face has the dome's), for what is cut, engraved or stands
  there, and nothing goes right through it there.
- *Part 3500, an error at its files:* its STEP file, each closed face
  halved, read back with a plane's and a cylinder's wires turned against
  each other (OpenCascade's checker: unorientable), though the halves were
  a valid solid and the file held tightly everywhere. A fault of Forge's
  writer, which kept the halves unless the file read back loose: it now
  keeps them only if the file reads back valid too, and else writes the
  part unsplit, which reads back valid and as the part written.
- *Part 3767, held:* two holes round a tube's side, 180 degrees apart; the
  angle round the side is measured within a window wide enough for 1 degree
  at 44 mm (4.17 mm), and round one copy that window reached a through
  slot's wall 3 mm off, facing the bore's way. Its points were taken for the
  bore's and put the fitted axis 0.86 mm off, held to a hundredth of a
  micron by the points' deflections, which no misplaced point moves: the
  angle 1.11 degrees off, inconclusive, though both holes were built exactly
  where asked. A fault of the judge's: a window now leaves out a point
  farther from its surface than its deflection that lies where another of
  the spec's surfaces may be (the oracle's witness, as face accounting asks
  it); a point off the surface and near no other is kept and measured, so a
  surface built in the wrong place is still found there
  ([V2-stage2.md](V2-stage2.md), section 7). Kept with the parts the
  tests build as meshes, it showed the tests' own mesh of a thread too
  coarse for an M10: cut into 72 slices a turn, its root strayed 0.0057 mm
  under the minor radius, past the 0.0052 it declared; a wider thread's mesh
  is now cut into more slices (141 for an M10), and strays 0.002.
- *Part 4050, held on its STL and 3MF:* a shell's wall is measured between
  two discs 2 mm round the middle of its face, one each side; a round pocket
  8 mm across on the inner wall, its centre 2 mm off the middle, left of the
  inner disc a sliver 0.05 mm wide. The B-rep's coverage had seven points on
  it; the files' meshes had none, and the wall was missing. A fault of the
  judge's: a wall is now measured at its face's middle where both discs
  are the part's surface whole, and else at the place nearest it on a grid
  over the face where they are (or, where nowhere they are, most of them),
  as the oracle has them.
- *Part 4118, failed by face accounting:* corner counterbored holes on the
  bottom face, and a grid of pockets 65 mm deep along x whose rounded
  bottom corners cross the counterbores' floors and cut into the bores. A
  counterbore's floor, its bore and a pocket's rounded corner meet at a
  corner of the part, the material past it a thin wedge. The built corner
  lay 1.3e-9 mm inside the bore, in the air; its witness was sought on each
  of the three surfaces and where each two meet, but every point found
  beside it was in the air too: each edge into a corner runs on one side of
  it only. A fault of the judge's: the witness now also tries the point
  where three surfaces meet, and the corner itself is the part's surface
  ([V2-stage2.md](V2-stage2.md), 5.3).
- *Part 4180, an error at its STL and 3MF:* its top face reached a finer
  box round a tube (0.0005 mm), and a countersink sat in another box round
  itself (0.00066 mm). Each finer face was meshed on its own at its own
  tolerance, and the mesher discretised their shared rim afresh for each:
  233 nodes on one side, 202 on the other. The weld by the edge's nodes
  tore the mesh (33 open edges), and the file was refused. A fault of
  Forge's mesher: the faces asking for finer are now meshed in groups of
  those that meet along an edge, each group at its finest, so an edge
  between two of them is discretised once (13.10).
- *Part 6820, held at the second kernel:* an extrusion standing on the
  block's -x face, its profile an L with legs 0.49 mm wide, joined flush.
  V1's kernel names its foot live, its samples being the box round the L,
  most of which lies on the block's face; the exact part rightly names no
  face for it. The agreement's excuse for such a name samples the face's
  inside clear of its rim, but on a 9 by 9 grid, 0.35 mm apart across the
  legs, no point was clear, and it couldn't tell. A fault of Forge's
  agreement check, not of the part: the grid is now refined (17, 33, ...
  up to 129 points a side) until it finds points clear of the rim
  ([V2-stage3.md](V2-stage3.md), 13).
- *Part 6950, failed by face accounting at its STEP file:* small through
  bores (0.963 mm round) from the side meet big blind holes (4.595 mm
  round) from the top. Read back, a bore's curve on its face strayed
  3.9e-5 mm from the edge where it meets a big hole (2.7e-6 mm from the
  edge's curve), between the few dozen points at which OpenCascade's reader
  makes it follow the edge and its checker checks it; the edge stated
  1e-7 mm, and a spec point on the bore 1.3e-6 mm from it fell outside the
  face as read. The part built was right, and its file: a fault of Forge's
  reading back, which took the reader's tolerances as measured. Every edge
  read back, and every edge of the halves a closed face is split into for
  the file, is now measured along its whole length and held as loosely as
  its curves stray (of 25 generated parts surveyed, 8 read back with an
  edge stating less than its curves stray, up to 1.4e-4 mm; of the parts
  as built, none). Writing the file had also changed the part: making the
  halves' new edges agree with their faces changed the tolerances of edges
  they share with the part's whole faces (24 of this part's). The halves
  are now made of a copy ([V2-stage3.md](V2-stage3.md), 12).
- *Part 7250, failed by topology at its STEP file:* holes round a tube's
  side. Halved for the file, the tube's outer face was cut 3.2e-5 mm from
  where a hole met it, an edge that short; read back, held as loosely as
  its curves stray (part 6950's fix), the corner at its end was held
  6.2e-5 mm loosely, over its neighbour, and the checker counted the two as
  the surface meeting itself. Two faults of Forge's. Its writer cut a
  closed face across the middle of its parameters wherever the part's
  corners were: it now cuts where it passes none nearer than 1e-3 mm (in
  halves, else thirds, else fifths; part 1130's bore, whose halves read
  back loose, is now split in thirds). And its topology counted two corners
  joined by an edge as meeting where they aren't joined: they are joined,
  and no longer counted ([V2-stage3.md](V2-stage3.md), 11.1 and 12).
- *Part 3500 again, an error at its STEP file:* found rerunning the
  shakedown's failures on the code that fixed them: written unsplit (as its
  fix said), the file read back with two edges 1.7e-8 mm long where a
  boss's rim, its edge 0 mm from the block's, touches the block's edge (the
  reader cut both there, the corner the boolean made 1.7e-8 mm from where
  the rim and the edge touch). The view couldn't divide edges that short
  by length, and its topology counted their ends as meeting. Faults of the
  view: an edge no longer than its sampling's spacing is its ends, and
  corners an edge joins are joined (above). Each fix's seed is now rerun
  whole before its fix is taken as done.
- *Part 7470, an error at its STL and 3MF:* raised lettering on a
  cylinder's end. A letter's side is the extrusion of a quadratic Bézier
  curve whose last two poles coincide, so its speed falls to nothing at its
  end. The mesh was measured from it at each sample's own parameters, then
  by a local search from there; from a sample whose triangle's parameters
  put it 0.092 mm off, the search went nowhere, and the mesh was refused at
  every refinement, though the sample was 1e-14 mm from the surface. A
  fault of Forge's measure: where the local search leaves a sample far, it
  is measured by OpenCascade's projection over the face's parameters
  ([V2-stage3.md](V2-stage3.md), 12).
- *Part 7858, an error: its worker died of a segfault:* a dome with tabs,
  a boss on each, and a left-hand M3 thread cut into the bosses; its mutant
  turned the thread right-hand. Whether the mutant changed the shape was
  decided by a boolean between the two threaded truths, which have one
  volume: run again, it was still running after 15 minutes. A fault of the
  exit test's script, not of Forge: a mutant is now shown to change the
  shape first by its volume, or by a point of either's surface far from the
  other's (each exact); the boolean is made only where neither shows it
  (3 above).
- *Part 8032, held:* a pulley turned on the block's -y face, its outline
  starting 0.016 mm off its axis. Its place along x and z is measured at
  its axis, fitted to one of its round sides; the compiler took the
  longest, the bore down its middle, 0.032 mm across, and at the judge's
  resolution its built points there lie on one line: no circle, and both
  checks held the part as asked. A fault of the judge's: a revolution's
  axis is now fitted to its round side with the most surface (its rim
  here, 6.276 mm across), else to its cone with the most.
- *Part 8675, graded wrong though the part was right:* round pockets run
  along x through the block, one 0.001 mm into the end wall of a slot,
  taking a strip 0.18 mm wide from it; along the strip's edges the wall and
  the pocket meet at 1.3 degrees. 45 points of the built surface there,
  each exactly on the truth's surface, failed the grader: their segments
  behind ran into the pocket's air, and the truth's material, a wedge
  1.3 degrees across, lay between the 270 ways it looks round along. A
  fault of the exit test's grader, not of the part (the judge had passed
  it): where those ways find nothing, it looks along ways just off the
  point's own plane too (12.3).
- *Part 9213, held though the part was right:* a slot 77 mm deep along x,
  and four rounded pockets up from the bottom, one of whose -y walls is the
  slot's +y wall, to the micrometre (both at y = 24.191). The two open into
  each other where their walls are one, and beside it each of the pocket's
  rounded corners (1.503 mm) leaves a cusp of material against the slot's
  wall, its edge along the line the corner touches the wall at. OpenCascade
  built it exactly. 198 built points on those lines failed face
  accounting: every facet there lies in one plane, so the oracle's
  first-order shape sees only the plane's two sides, both in the air, and
  along the surfaces until they turn apart past what it tells apart
  (2e-6 mm from the line here, a nanometre beyond the points' tolerance):
  no witness. The grader failed 200 of the same points (the cusp is
  thinner than its finest tilt, and from the rounded face the material
  lies ahead of the point's plane). Faults of the judge's and of the
  grader's: the witness now walks along the surface from where surfaces
  touch, tangent, to the first point it tells them apart at (within a
  micrometre, if they turned apart all the way:
  [V2-stage2.md](V2-stage2.md), 5.3), and the grader tilts down to
  0.0003 degrees and counts material ahead of the point's plane with air a
  step along the normal from it (12.3). It is not kept with the generated
  parts the judge is tested on (`tests/v2_regressions.py`): their reference
  is the truth meshed by manifold3d, whose vertices are single floats, and
  where two cuts share a face its mesh leaves a membrane between them a few
  nanometres thick (each cut's wall rounded apart), which face accounting
  rightly fails; the B-rep of the same corner is in
  `test_v2_checks_accounting.py`, with the oracle's and the grader's own.
- *Part 9530, its second kernel disagreeing:* four holes stand 0.118 mm
  from a pocket's side. The implicit kernel's field and the exact part
  agreed at every point compared, and their volumes, but its mesh, made
  again at 256 cells across in cells of some 0.42 mm, stepped over each
  wall: genus 8 for 4. Stage 3 takes the implicit kernel's topology from a
  mesh finer than the part's thinnest wall, and here none could be. A fault
  of the agreement's: where the counts still differ at the finest mesh,
  the exact part's thinnest wall and narrowest gap are measured, and one
  under two of the mesh's cells leaves the counts reported, not counted
  ([V2-stage3.md](V2-stage3.md), 13.4).
- *Part 9906, graded wrong though the part was right:* a post standing out
  from a block's side, flush with the block's foot, lies along the end of
  the cylinder the block stands on, its vertical edges rounded. Its two
  lower edges lie on that end: no edges of the part, and the definition,
  which rounds the item's edges on the part made so far, rounds nothing
  there. Forge rounded the two upper edges only, and the judge passed it;
  the generator's truth took the rounding's corner from all four, and the
  part graded 0.68 mm3 fuller than the truth's volume allows. A fault of
  the exit test's generator, not of the part: of a box's rounded edges,
  those the part made so far lies against (asked just outside both faces,
  all along the edge) are not rounded in the truth, and a plan where
  something lies against part of one is refused, as the truth can't follow
  where the rounding ends.

Reported, each with its denominator and a 95% upper bound on its failure
rate (zero failures in n: 3/n): parts passed; held, with why; mutants
caught, by leaf and by detector; impossible ones ending CAN'T; per kind and
per pair of kinds; each alternative's use and each refusal's reason; time
per part, and the most memory a worker held making each part's record. The
exit needs zero held, zero UNABLE, zero mutants surviving, zero impossible
built.

**The held-out run** (fresh seeds 10,000 to 11,999, on the counted run's
frozen code, so that how often a part never seen before fails is measured:
[V2-stage4-exit.md](V2-stage4-exit.md)). Each failure was traced to its
root on a copy, fixed with a test kept for it, and its seed run again
whole on the fixed code, while the run went on unchanged:

- *Part 10890, UNABLE:* a hole right through a tube's wall from outside.
  OpenCascade's subtract warned on its flush tool, which touches the side
  along its mouth and the bore at two points, and no other construction
  was offered. Forge's fault: a hole into a round side is now carried into
  the air too (5.2).
- *Part 10517, held:* a blind hole into a tube's wall, cut flush, its plug
  kept beside the part as a second solid with no flag raised. The judge
  held it. Forge's fault: such a hole is now carried first (section 5),
  and the part is held to one solid after each join or cut, a step that
  leaves more being refused (section 8). Carried, two parts kept by the
  STEP tests were built a little otherwise. Each showed a fault of the
  STEP writer's, now fixed ([V2-stage3.md](V2-stage3.md), 12):
  - Part 1130's split faces read back loose halved, in thirds and in
    fifths. The writer now tries further splits, each read back, before
    writing a part unsplit.
  - Part 0's file stated a finer uncertainty than the part held. A file now
    states no finer uncertainty than the part as built.
- *Part 11384, UNABLE:* a hole right through a tube's wall from outside,
  as 10890: run on the frozen code, it found no new fault. On the fixed
  code it builds, carried, and passes. It is kept with 10890.
- *Part 10849, held:* a row of holes drilled 7.25 mm down from a block's
  top, the last row's side exactly on the +y wall of a pocket bored in from
  a boss's end (both at y = −10.182). The part touched itself along three
  lines: no solid. The judge's topology held it, as it should. So was the
  truth, and the part graded right. The fault was the generator's, which
  promises one solid (as at 2511). It now keeps a round rod off a flat wall
  of another item that it runs along, by 0.01 mm either way
  (`_walls_crossed`). Its own host's side is left out, so a boss flush
  with it stands. 0.01 mm is a margin, not the limit: seed 505's hole
  crossed a slot's wall by 0.0085 mm and passed the counted run. The rule
  changes 1 seed's draw in the first 600 (505).
- *Part 11645, held:* two disc-ended pockets bored 58.4 mm in from a
  block's −x side, one over the other, and a rectangular pocket cut down
  from +y between them, its width (5.334 mm) exactly the wall left between
  the two. Its ±z walls touched both bores along lines: two edges on three
  faces, and the judge's topology held it. The generator's fault, the
  10849 class, drawn on the frozen code: the fixed generator refuses the
  plan ("i0 touches i4's wall along a line") and draws another part for
  the seed, which passes. Kept with 10849 as a plan now refused.

### 14.2 Every determinate corpus part

- **Drafted by hand, as V2 specs:** the 92 briefs of V1's validation suite
  (`validation/SUITE.md`), each drafted from its words as the spec writer's
  guide says, citing them (`tests/v2_suite_specs.py`; a brief that asks for
  something the schema can't say, or that V1 expected to be refused, is
  marked so with the reason); with every corpus spec the tests already
  hold (`test_v2_spec_corpus.py`, `v2_specs.py`, the reference parts).
  Each is locked, planned and built with no model call: every determinate
  one ends VERIFIED (BUILT TO DRAFT as locked by a draft), every check
  passing; the suite's own expected envelope and volume (V1's, measured
  independently) are met too. `tests/test_v2_plan_corpus.py`.
- **As built.** 76 of the 92 are drafted; 16 say why not, each in a
  sentence (V10 is Romanian, and Forge reads English; nine ask for what no
  kind makes yet: an intersection, a ball cut out, balls on balls, a
  turned bar, a hole into a ball, crossing rods, rods at 60 degrees round a
  pole, a coil, two loose parts; four V1 had to turn back have no honest
  draft but a question, and the gear's teeth and the heart's curves would
  be Forge's own). X06 (a hole wider than its cube) ends CAN'T at the spec checks,
  never built. Every other draft checks clean, locks as a draft, and is
  built by `forge build` with no model call: BUILT TO DRAFT, nothing held,
  on the B-rep, the second kernel and the STL; its envelope within 0.01 mm
  of the suite's, its volume within 0.1% (the suite's are rounded to the
  cubic millimetre), its open holes the released mesh's genus (two say
  why V1's count isn't the genus: three crossing holes, a doughnut). The
  three X parts V1 expected turned back but V2 builds (a bolt and its
  thread, a pointed cone, a ball too big for its box) take figures worked
  out from their briefs. Under --auto no draft has a fault; eight lock
  (seven before 14.4: P01's "cube in PLA" asked about its "in"), the rest
  stop for a person. One test per part
  (`test_v2_plan_corpus.TheSuiteBuilt.test_R01`), 15 to 230 s each.
- **What drafting and building them found**, each fixed at its root and
  tested on its own:
  - *Accounting:* "both" pairs two things with "and" only when the first
    is short ("both the flange and the hub", not "both long edges of the
    base and the channel is"), unsure, it counts; an `ends` pattern's two
    copies use the "both" or "two" its axis cites, as open faces do.
  - *The solver:* a round cut touching its face's edge at a point from
    inside pinches the material to nothing (V1's bolt holes side by side
    across a cantilever's 20 mm, the old R10 draft: the kernel built it and
    the judge held it, its mesh not watertight); a through cut coming out
    under something standing on the far face. Both are questions now
    (docs/definitions/place.md).
  - *The kernel:* an outline of two pieces with an arc among them (a
    ring's round section, two half circles) was refused as too few sides:
    P11 ended UNABLE.
  - *The judge:* a pointed cone's apex is where its surface may be (13.4,
    not yet built till now): X04 was held, 422 built points at its apex
    unsure. A shell's open faces are told from the sealed hollow too (V1's
    false pass 16 passed that check). A box's sides and top are measured on
    their own rectangle of their plane, and a point on its edge is no
    point of it: an upright flush with its base's sides had its width
    measured on the base's. A choice whose other shape differs from the
    spec's by less than the tolerances (a small tab's round end and its
    square one) is told by no point: that is said, and face accounting,
    which holds every built face far more tightly, holds the choice,
    where the check used to pass as "no other choice makes a different
    shape". Copies of a ball (C12's half-ball bumps) are counted on their
    own surfaces; a position measured from one edge of a face needs only
    that edge built (C13's holes, 8 mm below the top of an ear whose foot
    is joined to the block); and a field whose faces are inside the part (a
    rod's end in a ball, C05; C10's divider flush with the walls; C15's bar
    ends in its balls, and the balls' places on them) is held by face
    accounting (9.3), where five drafts listed fields as unchecked.
  - *The judge's round walls,* found running the tests again: a wall round
    a rod or a ball was measured between two surfaces each fitted, and so
    uncertain by how far apart their axes or centres might be, each fitted
    to within a few times the deflection: ±0.05 mm on the floored dome's
    2 mm wall, not fine enough for its ±0.1 mm. And that took the error of
    the centres' gap along the gap's own way alone, no bound where they all
    but coincide. Now each built point's distance from the outside's fitted
    axis or centre is taken (within its deflection of its surface's in its
    own direction), and the wall is from the outside's least less the
    hollow's greatest to the other way round: an off-centre hollow is found
    thin on one side and thick on the other on its own points. The dome's
    wall is measured to ±0.013 mm, the cups' to ±0.008.
  - *Found the same way:* the B-rep view told a point on a face by three
    rays cast from it, which see only crossings ahead of the point, so a
    point exactly on a face was put inside or outside by the next face on
    (the classifier's to say); the rays now start a hair behind it. A
    self-judging check (a thread's hand) whose feature was moved away gave
    no verdict and stopped the judge: it FAILs, as a check that finds
    nothing built does. A reference part's mesh was said to be finer than it
    is (a pocket's rounded corners left out of its deflection). And a test
    taking an item away left its rounding behind.
  - *The generator and its reference meshes:* a through cut whose far face
    is pressed against a wall has nowhere to come out (seed 617 raised); a
    block pressed flush against a wall left a crack of no width along the
    corner in manifold3d's mesh of the truth, kept as surface: added blocks
    are grown 0.00001 mm round their sides there, far within the mesh's
    deflection. The mutant tests take the first part of each sort with
    enough leaves to change, the generator's draws having moved.
- **Drafted by the spec writer:** `forge eval-corpus` runs the spec writer
  on every recorded brief (the 92, the 545, the arm's 13 parts) with your
  key, records each draft, and builds every determinate one with no further
  model call; the recorded drafts then replay at no cost in later runs. You
  run it (section 17).

### 14.3 V1's 27 false passes, both ways

Never written down before, they are reconstructed from V1's fix logs, its
recorded runs and its tests, and kept in `tests/v2_false_passes.py`, each
with its brief (quoted), what V1 built, why V1 passed it, and its sources
(section 16).

- **Replayed as their wrong geometry** (`tests/test_v2_false_passes.py`):
  for each, a correct V2 spec of its brief, and the wrong part, V1's own
  released document from the recorded run where there is one (built by the
  exact kernel through the v1 converter), or else built from what the
  sources say it was. The correct spec, compiled and built, passes the
  judge; the wrong part fails it, and the test names the detector that
  caught it. Five are not a wrong shape: a brief that is no part (21), a
  washer nobody sized (22), the steel cube shelled to pass its weight (19:
  its wrong shape is caught, and the right one fails its mass
  requirement), and two shipped files (23, 24). Each is caught where V2
  catches it (the spec writer's refusal and the accounting; the assumption
  `--auto` stops at; the mass requirement; the shipped file's re-open
  check), and the test says where.
- **End to end from their briefs:** `forge eval-false-passes` runs the spec
  writer on each brief (live, with your key; no secret enters this
  conversation), locks by `--auto`, builds, and judges the part against
  the correct spec as its answer key. Caught means: the run stopped to ask,
  ended other than VERIFIED or BUILT TO DRAFT, or built a part its key
  passes. You run it (17); its report is `runs/false_passes/report.md`.
- **As built.** The 27 and the two weaker candidates are written down,
  each with its brief, what V1 built, why it passed, its sources (fix logs
  and tests by line, the recorded run) and how sure the reconstruction is:
  3, 22 and 25 least sure, as above; 2, 6, 15 and 21 fairly sure (2's shape
  is known only as its envelope, holes and volume; 6 may be 7 told again;
  15's rebuilt part isn't stored); the riser under L07's post is the one
  weaker candidate built, the curved plate's holes the other, which V2
  can't draft (no kind bends a plate). Their right specs are the suite's
  drafts where the brief is the suite's, and seven drafted beside them
  (the hollow cube, the sphere, the 60 mm L-bracket, the 70 mm dome, the
  wrist strip and the two exo rails, each rail one outline pushed its
  thickness). V1's recorded documents mostly no longer read (V1's own
  checks refuse them now, or they lack the fields a document needs), so
  every wrong part is made with OpenCascade's own solids, from the
  document's features and sizes in V2's frame: the first body centred on
  the origin and standing on z = 0, a run's length turned along x where V1
  ran it along y. Each right part passes its judge with nothing held; each
  wrong part fails it, and the test names what must catch it, the most
  telling check where one does (the spacer's base width, the collar's
  screws' arc step, the upright's width, the shell's open faces, the
  dome's diameter, the sphere's portion, the counterbore, the bolt's
  head, the post's height) or the detector (face accounting: the four
  openings, the doughnut, the rail's blend, the lug, the strip's ends;
  topology: the sealed cube, the dome's skinned file). The dome's file is
  its two closed half balls, the inner one turned inside out; the rail's,
  its right part meshed to 0.4 mm and said to be as fine as Forge writes
  its own. One test per case.
- **The commands.** `forge eval-corpus [sources...]` and
  `forge eval-false-passes` (`forge_cli/eval_corpus.py`): each brief's
  answer, draft, problems, fixed wording and calls in its own folder,
  `record.json` last; run again, a recorded brief is replayed (read,
  checked, built) with no model call, `--replay` calling none at all.
  `eval-false-passes` reads `validation/false_passes.json`, the 27 briefs
  and their keys as `tests/v2_false_passes.py` makes them (`python
  tests/v2_false_passes.py` writes it; a test holds the two equal). 21 and
  22 have no key: no part released for them can be right. A false pass not
  caught sets exit code 3. Tested with a scripted model
  (`test_v2_eval_corpus.py`): a block drafted, built, replayed; a question;
  the block drafted turned, released, and found not caught.

### 14.4 The live half's first run, and what it changed

The owner ran `forge eval-false-passes` with Claude Sonnet 5 on
9 November. 23 of the 27 ended before `--max-cost 5` stopped the run
at fp24, and all 23 were caught: 15 asked a question, 5 stopped for a
person (their assumptions), and 3 were built to draft and right (the
open box, the dome and the sphere). No wrong part was released. But many
of the questions were Forge's to fix, and so were some faults in the run
itself. Each fix below is checked by replaying the owner's 23 recorded
drafts on the new code: no model is called, every ending is listed, and
all 23 must still be caught.

1. **The cost ceiling was passed:** $5.76 spent under `--max-cost 5`. The
   budget refused only the call after the one that reached the ceiling
   (`forge_models.Budget`, and the two drafts' shared budget in
   `forge spec`). A transport retry inside a call wasn't checked again at
   all. The ceiling now holds. `forge_models` (V1, extended, additively):
   a `Budget` may be given a `price`, the most one request can cost.
   `AnthropicProvider.worst_cost_usd` works it out from its price table:
   the approximate input at the input price, a quarter more as if all of
   it were written to the cache, plus the output limit at the output
   price. With a price set:
   - A call is refused when what is spent, plus that worst cost, would
     pass the ceiling.
   - Each retry is checked again.
   - The shared budget holds each call in flight at its worst cost, as it
     already holds its tokens.

   V2's commands (`forge spec`, `forge eval-corpus`,
   `forge eval-false-passes`) give their budget the provider's price.
   V1's commands keep theirs. A run so stops with up to one call's worst
   cost unspent, and never past its ceiling.
2. **The stop line printed every refused answer.** The error carries each
   refused answer and its problems for the record, and all of it was
   printed. The stop line now prints the error's code and message; the
   details go to the ledger.
3. **A stopped run wrote no report.** `report.md` still showed an earlier
   run of one brief. It is now written however the run ends, and says
   what stopped it.
4. **"Both" for an item's copies** (fp06 to fp09: "Two 4 mm set screw
   holes ... 90 degrees apart, both halfway along the length"). The
   writer cited "both" with the holes' place along the length. A number
   word was used only by a value that reads it, so "both" was asked
   about. Now a number word with no unit, in the words a place cites,
   is used by that place when it equals the item's number of copies: the
   place every copy shares, said of all of them. Any other count still
   needs a value that reads it.
5. **The sentence naming the part, taken as silent** (fp01, fp02, fp06 to
   fp09: "It carries no load - it is a locating collar, so there is no
   load case"). An automatic run takes a sentence as silent only if
   nothing in it may be a shape word. Here "collar" (and "spacer") were
   shape words, and the negations "no" counted with them. Three changes,
   for silent sentences only:
   - **A negation counts only with the shape word it denies:** the first
     word after it that isn't a common word. In "no load", that word is
     "load", which isn't a shape word.
   - **The part named again says nothing new:** a word the first body's
     own words cite in another sentence is taken as said, unless a
     negation in the sentence denies a shape word. This is the first
     body only, because a feature named again in a silent sentence can
     say more of it ("the boss has a rounded top").
   - **"Locating" joins the closed list of words for what a part is for.**

   A list of what isn't modelled keeps the old rule. Leaving out words
   that repeat an item's can leave out a second feature of that kind.
6. **Small linking words** (fp12: "cube in PLA", "hollow on the inside";
   fp18: "5 mm deep from the top face"). In an automatic run every word
   is used, except the common ones. "In", "on", "at", "from" and "for"
   were left out of the common words on purpose, because they can change
   the shape. They still are. But such a word now counts as used by an
   item when the nearest used words on each side of it in its sentence
   are both that item's, with only common or linking words between. It
   then joins two parts of that item's own description, and each part's
   value accounts for its meaning. The same holds for "in", "of" or
   "from" right before the words the material cites ("in PLA"). A count
   word ("each", "every", "all", "both", "only") and a negation are never
   taken this way: "a slot at each end" read as one slot would be V1's
   false pass again.
7. **Not changed, and why:**
   - **A mass limit** ("It must weigh no more than 8 g": fp01 to fp05,
     fp19). Forge can't check mass until stage 6, so an automatic run
     can't leave the limit out: it stops for a person.
   - **"For M5 screws" listed as not modelled** (fp18). "M5" is a size, so
     the run stops.
   - **The dome "sitting flat side to the right"** (fp16, fp23). This sets
     its orientation, so it can't be left out.
   - **"Each"** is a count word (as above).
   - **Assumptions, and an outline's sizes, stop an automatic run.** That
     is by design (fp10, fp15, fp17, fp20 to fp22).
   - **An assumption's reason over 200 characters** (fp24) goes back to
     the writer once, like any fault. The limit is in the schema and in
     the guide.
   - **The eval drafts each brief once.** `forge spec --auto` drafts it
     twice and needs the drafts to agree, so the eval's "caught" holds
     without the second draft, the stronger claim.

**The second run (10 November)** was on the code with all of the above.
It replayed the 23 at no cost, as the replay above found them, and drafted
fp24 to fp27 (the exo-brace rails and the strip) within `--max-cost 20`.
**All 27 were caught.** The endings: 14 questions, 9 stops for a person,
3 built to draft and right, 1 refused. The four new ones:

- **fp24, refused.** The writer cited "One end of the bar is a round end
  48 mm in diameter" for the bar's outline. Forge read "One" as a count of
  1, which the outline doesn't have. Told only "the outline has no size of
  1", the writer gave the same answer three times. The fault now names the
  brief's word: "of 1 (the brief's 'One', word 18)".
- **fp25, questions.** The same brief drafted otherwise left numbers
  unused ("36", "245", "One", "two", "four").
- **fp26, questions.** Its outline (an automatic run can't confirm which
  size is which, by design), and a real question: does the lug's hole go
  on through the boss over it?
- **fp27, questions.** Its outline, "both" (both ends rounded) and "one"
  ("from one end") not used.

Not changed:
- **"One end", "from one end".** A number word that picks one of a
  thing's ends isn't told from a count here, so it is still asked about.
- **The closing sentence of these four briefs.** "Its strength is checked
  outside Forge" has "outside", a word of place, so it still stops an
  automatic run.

fp25 and fp26 drafted for $2.93 and $4.04, fp27 for $0.41.

### 14.5 Blind set 1's first run: every draft gave up, and why

The owner ran `forge eval-spec eval\blind\set1` with Claude Sonnet 5 on
19 November, on 389db2f (guide 26, schema 1.9). **All 30 briefs gave up**
("the writer couldn't clear its own faults"): no fact was graded right,
for $9.25. Every refused draft is kept with its problems
(`refused.json`), and they all said one thing: `/schema_version: schema_version
is a major and a minor number, "1.9"`. The writer wrote `"1.9"`, as the
guide and the schema's `const` ask; it arrived as the **number** 1.9. Told
so, it wrote it the same way again, and the run stopped each brief when the
same problem came back. Inside a wrapper the same draft's version arrived
as text: the number is the transport's reading of a top-level field, not
the writer's. The November false-pass drafts never met it: they were
written before drafts named a version.

Fixed in the writer, V1's roles unchanged. The role framework gives a role
a hook to read what the transport hands over before any check
(`Role.received`, by default unchanged); the spec writer's
(`forge_roles.spec_writer.as_drafted`) reads only the same content in
another form, so nothing a check holds changes:

- **A text the schema fixes, given as the number it reads as**, is that
  text: 1.9 is "1.9", and 1.1 is "1.10" where "1.10" is the text named.
  A number that reads as none of them, or as two, is left as given, and
  the fault now says what to write: `schema_version is a major and a minor
  number written as text, in quotes: "1.9", not the number 1.8`.
- **The whole draft under a lone wrapper the schema doesn't have**
  (`{"spec": {...}}`, on seven briefs, six of them redrafts) is the draft.
- **Items as JSON text**, the list, one item, or a list inside the list,
  are the items.

**A replay reads a record the same way** (`read_answer`): a run's
`answer.json` holds what was handed over. `forge eval-corpus` read it raw
after drafting, so every one of its drafts would have been refused the
same way; nothing was spent on it, the owner having been told to stop
before it.

**Proof without a model call.** With the owner's leave, the run's 91
refused answers were read again on the fixed code against the set's
briefs: 29 of the 30 briefs have an answer that now checks clean, 17 of
them the first answer drafted, before any repair. The 30th (B1-15) had no
clean answer: its redrafts broke its items' JSON, put an assumption past
200 characters, and leaned its backrest past the material under its foot.
Tests: `test_v2_spec_writer.py` (`WhatTheTransportHandsOverIsReadAsWritten`:
each reading, a number naming no text still a fault, a wrapper named as
the schema's own field left alone, a replay read as the live writer read
it); `test_v2_eval_spec.py` (a set drafted with numeric versions, graded
and regraded from its records alike); `test_v2_eval_corpus.py` (a corpus
brief drafted so, built, and replayed at no cost: it fails on the old code).

**Set 1 is no longer blind.** The report's list of what each brief got
wrong prints the keys' facts, and it was pasted whole; the owner then
gave leave to read the run. Set 1 is a practice set from here: its
numbers measure a change against itself (schema 2.0 against 1.9), not
Forge against new briefs. An honest blind number needs a fresh set
(plan, section 7). Its first measurement is the rerun into a new folder:
the first one's records are of other code, and a folder is one
measurement.

Two other things the run showed: `forge doctor` passed any Python from
3.10, while pyproject has asked for 3.14 since 4b.0b (its floor is now
pyproject's, held by a test); and `tests/test_v2_eval_keys.py`'s check of
the blind set fails wherever `eval/` isn't, which is everywhere but the
owner's machine (it is skipped there now, with that reason).

### 14.6 Blind set 1's second run, and what it changed

The owner ran it again on 96f534a, into a new folder (20 November):
**80 of the 83 facts Forge grades itself right (96.4%), wrong at most
9.1% at 95%**, 30 briefs drafted for $8.42, the one that can't be made
refused. The three wrong: a spur gear drafted as a plain disc at its pitch
diameter, its teeth "not modelled"; a hollow cone and legs standing under a
round bar, both refused as Forge can't make them yet. With the owner's
leave, the run was read (set 1 is a practice set, 14.5), and the drafts
replayed on each change below, no model called.

**Questions nobody needed: 11 of the 26 clear briefs.** Nearly all of them
"the brief says 'four' ('one', 'both', 'two'); nothing in the spec uses
it", where the spec held the count all the same. A count word is now used
where what holds it comes in exactly that many (`_counts_held`), and still
asked about where it doesn't: an item's copies, the count word in its own
words (one copy for "one", and where "one" picks an end, an edge or a side,
only if the item is placed on one or measured from one; "one in each
corner", one at each of several); the edges an edge set picks ("all four
corners": four vertical edges; "both ends": two rims); the items of one
kind that cite it ("two plates", two blocks); the values one measure is
given to ("6 mm in from both edges", two insets). A "one" that points back
("the middle one in the middle of the bar") is no count at all
(`citations._pronoun`). A sentence that only names the part ("An
L-bracket.", "Part: sensor mount"), every word of it the spec's name's, is
the name's (`_named_by_the_spec`). Replayed: 11 asking become 2, one a
clearance to another part the brief gives (now listed as not modelled, the
guide says), one an angle from the base (below).

**An angle measured from a face.** "Leans back at 65 degrees from the
base" is a tilt of 25 degrees from square to it; no formula could say so
while every number had to be the brief's, so the writer assumed it, and 65
was asked about. A formula may now add or take away 90 deg or 180 deg
where its other side holds an angle from the brief (`derived._right_angle`):
it brings in no size. The same brief spent $3.49 on three drafts, one of
them over a reason 230 characters long; the writer is asked for 200 and
read to 300 now (`READ_REASON`), a redraft being a paid call.

**What no kind makes, said (schema 1.10).** A draft lists it in `unable`,
its words and what it is ("involute spur gear teeth"), and drafts no
stand-in for it; Forge says it can't make the part yet, first in what the
person reads. Below 1.10 such an entry is a fault. A record's version given
as a number of an earlier minor ("1.9" as 1.9) still reads as that version.

**A live smoke check.** `forge eval-corpus --smoke` drafts four of the
suite's briefs afresh (R05, R02, C09, X02: counts and corners, a cross hole
in a round side, a hollow, a gear), into a new folder each time, within
`--max-cost` (default $2): the cheap live run after a change to the guide,
the schema or the writer, before any big one. And the owner's second
false-pass run (fp24 to fp27) joins the first's 23 in the replayed
fixtures, every ending pinned and every false pass caught.

**The report keeps a blind set blind.** Each fact graded wrong, with the
key's own fact, goes to the run's `wrong.txt`; the report says how many
and where. Set 1's keys reached the conversation in a report pasted whole.

Proof: the 27 false passes replayed, endings and reasons byte-identical
old and new; set 1's 30 drafts regraded (79 of 82 right; asking 11 to 2);
tests `test_v2_spec_counts.py` (each rule both ways), `test_v2_spec_unable.py`
(unable, the right angle, the reason's length).

### 14.7 The corpus's first run, and what it changed

The owner ran `forge eval-corpus --smoke` (four briefs, $0.67: three built
right, the gear UNABLE), blind set 1 a third time on b98f6cb (81 of 84
facts right, 96.4%; asking nobody needed 11 to 3; $6.64), and the corpus
to `--max-cost 5` (41 of 161 briefs, $4.16): **37 built, each the size
and the volume validation/SUITE.md expects of it**, and four stopped on
questions. Read, with the set's (a practice set, 14.5):

- **A limit on the whole part was never checked, and said as if it were.**
  R01 and R11 ("it must weigh no more than 10 g", 8 g) were drafted with
  the limit not modelled, built, and released with "every check passed on
  every view": the limit was on the spec page alone. R13 ("no taller than
  32 mm and no more than 30 g") stopped on both numbers, though its part
  is 31 mm and about 23 g. **Schema 1.11, `requirements.limits`:** a limit
  the brief sets on the whole part, its "mass" or its overall size along
  "x", "y" or "z" (how tall it stands), at most and at least so much, cited
  as any value (a limit is said as a denial, "no taller than", and its
  words name what it holds all the same). It is checked on every view of
  the built part (`forge_checks.limits`): its size by the view's box, to
  within the view's tolerance, a part drawn to the limit within it; its
  mass by the view's volume and the material's density, a range over its
  common grades (`forge_spec.materials`). A part of a printable plastic is
  known only to weigh at most its solid mass: its infill isn't the spec's.
  A material with no density there (a filled one, wood), or none at all,
  can't be weighed, and is said so. Anything but PASS holds the part. A
  build lists, beside any ending, the limits it checked and what the spec
  leaves out (not modelled), which nothing checks; and two drafts that read
  a limit otherwise differ, and it is asked (`compare._limits`).
- **A record's version given as a number reads as the later of two.** With
  the schema at 1.11, every record drafted at 1.10 (handed over as 1.1)
  read as "1.1" or "1.10" and was refused: every corpus and blind-set
  replay would have been. A minor version only adds, so the later reads
  each draft the earlier does (`spec_writer.as_drafted`).
- **Questions nobody needed,** each still asked where the spec doesn't hold
  it: "fixed at one end by two 5 mm bolt holes near that end" (R10), "one"
  picking the end they are measured from, whatever their count; a tube
  "open at both ends" (P08), the two ends its bore opens; a screw's size
  ("for M5 socket head screws", B1-11) where a hole in its sentence is one
  of that size's own, a clearance or its tap drill; a number in a name the
  spec repeats ("Raspberry Pi 4", B1-30), a numeral just after a
  capitalised word not beginning its sentence (`checks._counts_held`,
  `_screws_held`, `_names_held`). P06's hexagon "20 mm across the
  corners" was drafted right and assumed: an outline cites the sizes it is
  drawn to, even where its corners are worked out (guide 33), as its
  checks already read them.
- **Not changed:** R10's load and safety factor are still asked: Forge
  can't check strength yet (stage 6). B1-16's gear teeth and B1-24's
  rounding where a 3 mm floor meets 2.5 mm walls are still UNABLE: neither
  is made yet. Each, and every other place Forge says it can't do
  something yet, is in [V2-gaps.md](V2-gaps.md) with the stage that closes
  it, held to the code by `tests/test_v2_gaps.py`: V2 is released with
  none open.

Replayed with no model call: the corpus's 41 drafts and the set's 30 are
read on the new code as on the old, but for exactly those four questions,
and R01, R11, R13 and P06 are drafted again by the next run. Tests:
`tests/test_v2_spec_limits.py`; `tests/test_v2_spec_writer.py` (a 1.10
record under 1.11).

### 14.8 The corpus's second run, and what it changed

The owner ran the corpus on 1373566 to `--max-cost 45`: 116 of its 161
briefs ($31.47; the corpus's 41 before it, $34.84 in all), stopped at the
budget with 45 to go. **Every SUITE part that was built has the size and
the volume it should**, A06's included (validation/SUITE.md said its
envelope was 40 mm along the hole: the hole takes the ball's poles off, so
it is 38.73 mm, as suite.json already said; corrected). The stops were
right: the mass and size limits held (L05, X07), the parts that come apart
CAN'T (X06), the gear, the spring and the lofts UNABLE, and the loads asked
about (R10, L01 to L04). Read:

- **Seven parts were built that the brief didn't ask for.** The rail's
  "rounded triangular cutouts" were listed as not modelled, and it was built
  and released without them; three domes "sitting flat side up" or "flat
  side to the right side" were built flat side down (one with the
  orientation not modelled, two with it cited by the dome's portion); and
  "Make a washer.", "Make me something cool." and "A PLA hook strong
  enough to hang a coat on." were built with every size made up, the
  hook's strength listed as not modelled. Now:
  - **A shape the brief asks for can't be listed as not modelled**
    (`checks._shapes_left_out`): a fault in every mode, the part drafted
    again with it, or with it in `unable`. A shape the brief denies ("no
    cutouts") or one the spec has already ("around every hole") is not a
    shape left out. Nor is which way a part sits.
  - **Every size assumed is a question** (`_sizes_all_assumed`): the part
    would be a guess. Not where the draft says Forge can't make what is
    asked ("Write me a poem").
  - **Strength can't be dropped** (`_strength_unchecked`): a strength in
    `silent` or `not_modelled` ("strong enough", "sturdy") is asked about,
    as Forge can't check it yet, unless the brief denies it ("carries no
    load", "Load: none") or says it is checked outside Forge. A silent
    sentence with a number is asked about already, by its numbers.
  - **A dome standing on nothing sits flat side down** (the sphere's
    `physical`): one the brief has sit any other way is UNABLE (a gap,
    V2-gaps.md: 4b.0c item 1), said once where the draft says so itself.
- **Questions nobody needed,** each still asked where the spec doesn't hold
  it: "a stepped shaft on one axis" (C04), where every body after the first
  stands centred on an end of one before it; "one divider ... splitting it
  into two compartments" (C10), one more than the divider's copies; a ball
  "half sunk" into a face (C14), as a whole ball on a face is (a kind's
  `held_words`); "56 apart one way and 36 the other" (V02), where the item
  is measured along two axes; a size the brief gives again of the face an
  item is on, "across its 30 mm width" (L04), "through one of the 50 mm end
  walls"; "both ends fully rounded" where the outline has two arcs.
- **What the writer is told.** A depth the preview can't find behind a
  fault or a question isn't an UNABLE: it hid a cross hole running past a
  face's edge, which is asked, and the redraft is previewed again
  (`forge_cli.spec.with_unresolved`). A number with no unit in a formula is
  a count, and the writer is told so ("-37.5 - (-50)" for a length was
  "not in the words it cites"). An `unable` said at too great a length is
  told how long (A04's was 170 characters, of 80).
- **Not changed, and scheduled:** bodies that cross or overlap (A03's three
  balls, A08's plus sign, C07's jack), the first body turned (A04),
  positions from a point of the part (an exoskeleton rail's "from the pivot
  point"), one body intersected with or subtracted from another (A01, A02)
  and two parts in one brief (X12) are listed in V2-gaps.md, section 10,
  with the stages that close them.

Replayed with no model call: the corpus's 117 drafts and blind set 1's 30
are read on the new code as on the old but for exactly those, and B1-20 ("A
rectangular mounting plate with four screw holes, one near each corner",
every size assumed) is now asked its size. Of the owner's first live run
(14.4), the two domes "sitting flat side to the right side" (fp16, fp23)
are now UNABLE, and the poem and the washer (fp21, fp22), drafted with
every size assumed, are asked their size. The briefs whose drafts are now
faults are drafted again by the next run. Tests:
`tests/test_v2_spec_second_run.py`; `tests/test_v2_eval_first_live_run.py`
(the endings).

## 15. What is tested

| Test file | What |
|---|---|
| `test_v2_plan.py` | Each kind's tool on every face kind: steps and numbers against hand-worked ones; determinism across runs; `for_items`; names (4.6); refusals and gaps (4.9) |
| `test_v2_plan_refs.py` | Every edge set of every kind compiled to queries that find exactly the spec's edges: plain; cut across; after an earlier rounding; flush; overhanging; on a hollowed body |
| `test_v2_plan_alternatives.py` | Each alternative of section 5 built both ways on parts where its proof holds: the same solid; where it fails: not offered. Holes into round sides carried (5.2): through a tube's wall from outside and out of its bore, blind, across a rod (counterbored too), through a hollowed cylinder's wall and out of its hollow; the host's box left out but no other's. A cut through the next face carried first, past its end into the air the preview shows (5.2): generated part 4944. A hole's round tools turned about their axes (5.7): each a transform after it, taken turned; generated parts 2231 and 4599, refused flush, built so |
| `test_v2_plan_build.py` (split into files under 3 minutes) | The stage-2 reference parts' specs and generated specs, planned, built and judged; graded against the truth |
| `test_v2_occ_outline.py`, `test_v2_occ_text.py`, `test_v2_occ_thread.py` | The three new operations: build, after-check, names, down-conversion; the glyph table against fontTools; letters' areas; threads held to the profile by stage 2's check, both constructions |
| `test_v2_spec_outlines.py` | The solver: extrusions and revolutions placed; outline faces; the overhang's material; outlines on varying material; the ink held to the face |
| `test_v2_checks_outlines.py`, `test_v2_checks_letters.py` | The oracle's and the judge's: outline prisms, revolutions, exact letters; their placements against the solver's |
| `test_v2_build.py`, `test_v2_checks_judge.py`, `test_v2_sizes_made.py` | `forge build` end to end: each ending, exit codes, the record, the folder rules, the seal, unchecked fields listed; the judge on every view; sizes made at the middle of their band, judged to the written limits |
| `test_v2_preview.py` | The preview's mesh in the page, colours, gaps, the fallback's list, the time limit |
| `test_v2_compare_geometry.py` | The same part written two ways: dropped; a real difference, a bounded item's field difference: kept and said in the first draft's terms |
| `test_v2_view_near.py` | `near` against `distance <= t`, everywhere, and faster |
| `test_v2_eval_widened.py` | The generator's new kinds and limits: the three placements agree; the truth on hand-worked points; mutants change one leaf; briefs cite their words; impossible ones end `cant` |
| `test_v2_plan_corpus.py`, `test_v2_false_passes.py`, `test_v2_eval_corpus.py` | 14.2 and 14.3: the suite's drafts checked, locked and built; the false passes' right parts passing and wrong parts failing; the two commands with a scripted model |
| `test_v2_eval_first_live_run.py` | 14.4: the cost ceiling with and without a price, a retry checked again, the two drafts' calls held at their worst, the dearer of two prices; a stopped run's line, ledger and report; an automatic run's accounting (the part named again, linking words, "both" of an item's copies) and where it still asks; the owner's 23 recorded drafts replayed, every ending and all caught |
| `test_v2_spec_limits.py`, `test_v2_spec_second_run.py` | 14.7 and 14.8: limits on the part, read, written and judged on the built part; a shape, a size or a strength the spec can't leave out, a dome that sits flat side down, and the questions the corpus's runs asked that nobody needed |
| `v2_exit4.py`, `test_v2_exit4.py` | 14.1 as a script; the test runs it on 3 seeds |

Every test file runs in under 3 minutes on the laptop's VM (its shell's
limit), or is split.

## 16. V1's 27 false passes

| # | Case | What V1 built, and passed |
|---|---|---|
| 1 | R11 spacer, base on its edge | the base plate stood on its edge, its holes one line through it |
| 2 | R11 spacer, wrong plane | 38 × 20 × 38 for 30 × 30 × 14, every hole filled back in |
| 3 | R11 spacer, mounting holes at the edges | the holes 30 mm apart, half-moons cut from the plate's sides |
| 4 | R11 spacer as a bar | the base 30 × 4 × 4 |
| 5 | R11 spacer, base a fillet thick | the base 2 mm thick, the post floating above it |
| 6 | R12 collar, "90 degrees" unread | the set screws 180° apart |
| 7 | R12 collar, parallel screws | both screws parallel, across the body |
| 8 | R12 collar, four openings | each screw through both walls |
| 9 | R12 collar, screws at the bore's size | both 12 mm across, no bore |
| 10 | R09 L-bracket, upright too wide | the upright 50 mm wide on a 40 mm base |
| 11 | R08 open-top box | cut through the middle into two slabs |
| 12 | hollow cube | solid |
| 13 | dome | a whole sphere welded to a box |
| 14 | sphere | a drum, 100 × 100 |
| 15 | L-bracket turned | the upright along the plate's long side |
| 16 | hollow dome | sealed, no opening |
| 17 | P11 doughnut | 40 mm across on a 32 mm middle (a revolution of a circle) |
| 18 | H03 counterbores | one counterbore of two |
| 19 | L05 steel cube | a sealed 3 mm skin, to pass its weight |
| 20 | X03 bolt | the head 84 mm across its corners (an extruded hexagon) |
| 21 | X09 "a poem about bridges" | a 1 mm cube |
| 22 | X01 "make a washer" | an M10 washer from sizes nobody gave |
| 23 | hollow dome's STL | a skin drawn across the opening |
| 24 | exo upper rail's STL | the holes 0.5 to 0.9 mm small |
| 25 | exo upper rail | an 8 mm blend nobody asked for |
| 26 | exo forearm lug | square-ended, its top rounded, the boss over the rounding |
| 27 | exo wrist strip | square ends for fully rounded ones |

Each case's sources and how sure the reconstruction is are in
`tests/v2_false_passes.py`. Three (3, 22, 25) are the least sure: the
sources could also be read as a near-miss, a dishonest assumption, or a
blend V1 kept; they are kept, and two weaker candidates (V1's riser added
to a post to meet "no taller than 50", and four holes drilled straight
down through a curved plate) are tested beside them.

## 17. Open questions for you

1. **Run the false passes end to end** (14.3) and **the corpus** (14.2)
   with your key: both are built. From the repository's root, the key in
   your environment (`$env:ANTHROPIC_API_KEY = "<your key>"` in PowerShell,
   for that window only; it is read by `forge_models` alone):
   `forge eval-false-passes`, then `forge eval-corpus`, which drafts
   validation/SUITE.md's 92 and the recorded runs' briefs (each once) by default.
   The 545 briefs and the arm's 13 aren't in the repository I have: give
   their files or folders after the command (`.md` with `> ` lines, `.json`
   with a `brief`, or `.txt` a brief a line). Each stops on a budget
   (`--max-cost`, `--max-calls`) keeping what is done; run it again to go
   on. Their reports are `runs/false_passes/report.md` and
   `runs/corpus/report.md`; exit code 3 means a false pass not caught.
2. **A shell's floor of its own thickness at rounded floor edges** (4.8):
   build it now, or wait for a design that needs it?

## 18. The order of work

1. `forge_plan` for bodies, cuts and standing features on flat faces and
   round sides; names by plane; the document; `test_v2_plan.py`.
2. References: lists, extents, centres, `at_least` in `forge_ir.v2` and
   `forge_occ.refs`; the names indexes; roundings, chamfers and their
   queries; shells; `test_v2_plan_refs.py`.
3. `forge_occ.planned`, the alternatives and their proofs;
   `test_v2_plan_alternatives.py`.
4. The judge made fast (13); the pointed cone's apex.
5. `test_v2_plan_build.py` on the reference parts and generated parts;
   every disagreement found settled at its root.
6. The solver's fixes (6.3); extrusions and revolutions through the solver,
   the judge, the oracle, the compiler and the kernel (6).
7. The glyphs; `text` through all of them (7.1); `thread` (7.2).
8. The generator widened, with briefs (12).
9. `forge build`, the verdict, export tolerances; the preview; the
   comparison of drafts.
10. The validation suite drafted as V2 specs, the corpus build, the false
    passes (14.2, 14.3); `forge eval-corpus`, `forge eval-false-passes`.
11. The exit test (14.1), run to 10,000; the report; sync.

Each step lands with its tests, lint and type checks clean, and is saved
to the laptop.
