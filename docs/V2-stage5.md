# Forge V2, stage 5: the construction agent

Status: design, revision 2, 28 October 2026: a draft for your review.
Revision 1 was reviewed adversarially; section 1.1 says what the review
changed. Nothing on this page is built until stage 4b's exit test passes
(plan, section 8: each stage starts only when the one before it has passed
its exit; stage 4b, coverage, was added between stages 4 and 5 on 3
November 2026). Companion to [V2-plan.md](V2-plan.md) (sections 1.2, 1.3, 4.3,
4.5, 4.7, 4.9, 7, 8) and [V2-architecture.md](V2-architecture.md) (sections
2, 4.5, 4.6, 4.7, 5). Where this page is more exact than those, this page
holds; where it differs, it says why (section 2).


**Changes from stage 4b (3 November 2026), to make in revision 3.** Stage
4b comes first and changes what this page rests on: regions stand on 4b.0's
frames and placeable faces, not only inside a flat face's outline; a shell
with walls of different thickness (the example of a determinate gap in
section 2) becomes a 4b.3 kind; organic shapes, lattices and mixed parts
are 4b.9's, so section 2.8's "until a brief needs them" is settled there,
and whether a region may be built in the implicit kernel is decided here;
smooth joins are judged by 4b.5's continuity check kind, one rule for
both; 4b.5 decides when a shape is a surface item and when a region, and
this page follows it; the escape hatch's ForgeIR op is renamed so it can't be confused with
4b.8's imported body, and an architecture test keeps its solid away from
the oracle; Forge's own constructions (4b, section 3.1) become ops the
agent may use; the sandbox image uses the OpenCascade version 4b.0a
decides; the exit adds drafting accuracy and the catch rate on 4b kinds
(plan, section 8).

**Changes from stage 4b's revision 5 (10 November 2026), to make in
revision 3 too.** Part two of stage 4b gives this page more to stand on:
4b.13's subdivision cages, a way for an organic region to become B-rep;
4b.14's calculators and 4b.15's analysis as the agent's tools, so that a
region may carry load, stiffness, frequency and temperature requirements
judged by analysis, not by geometric checks alone (section 4.3); 4b.16's
optimisation as the way a region made for a purpose is proposed, judged
by its requirements; 4b.12's continuity checks for smooth joins (section
2.8).
---

## 1. What stage 5 delivers

The plan's row for stage 5:

> Tools, budgets, stop rules, freeform regions, the escape hatch in Docker.
>
> **Exit test:** Corpus and a fresh blind set: none wrong but VERIFIED;
> completion 98% or more; cost under target.

**In one paragraph.** After stage 4, a confirmed spec builds with no model
call, item by item, each by the first of its proven constructions that
OpenCascade accepts. What is left over, stage 4 ends UNABLE: a **region**
(a shape the brief describes only by what it is for, within an envelope),
and a **determinate gap** (an item every construction of which OpenCascade
refused, or one the compiler can't write: stage 4, 4.9). Stage 5 gives each
gap to a construction agent: a model that may add, change and remove the
steps that build that one item, and nothing else, and that sees the checks'
exact misses after each try. When it is done, the whole part is judged as
stage 4 judges it, with fresh probes the agent never saw. A determinate gap
is checked exactly, like any item, so it can end VERIFIED. A region is
checked by its constraints only (its envelope, how much of it is filled,
its walls and necks, how it is joined), and the ending says so. Where the
operations can't make the shape, the agent may write build123d code that
runs in a locked-down Docker container and hands back a solid. Every run is
checkpointed, so a run stopped by its budget, a provider fault or a crash
resumes where it stopped, with the same answers.

| Deliverable | Done when |
|---|---|
| Regions, checked | A region's constraints are check kinds of their own, each with mutants and near-misses like every stage 2 kind; the oracle keeps every fixed item's shape out of the envelope; the ending names every region and what was checked on it (section 4) |
| The construction agent (`forge_designer`) | Its tools, its view of the checks, its progress detector and its budget, as section 5 says; it can change only its own gap's steps, in its gap's place, and a geometric after-check shows the part changed only there (R4) |
| The escape hatch (`forge_sandbox`) | Build123d code run in Docker with no network, a read-only root, no capabilities, a user that isn't root and limits; the solid read in a separate process; unavailable, and said to be, without Docker (section 6) |
| The run, checkpointed (`forge_orchestrator`) | The run's states of the architecture's section 5, a checkpoint after each and after every tool call, `forge resume` replaying every model answer in order, WAITING on a budget or a provider, and the kill-and-resume test at every state (R9; section 7) |
| The release gate with constructed items | Fresh probes drawn after construction; a determinate gap judged exactly; a region VERIFIED EXCEPT with its constraints listed; a gap the gate fails goes back to the agent once, then ends UNABLE (section 8) |
| Tested without a key | A scripted designer drives every path of the agent offline: right, wrong in each constraint, reaching another item, stalled, out of budget, resumed (section 10) |
| Exit test | Section 11 |

### 1.1 What the review changed

| Finding | This revision |
|---|---|
| The oracle adds a region's whole envelope to the outer form, so a region built over a through hole's mouth passes face accounting and the hole's checks: VERIFIED EXCEPT with no way through | A fixed cut's air is carried out of its face through the envelope, in both forms, whatever the order (4.2); a region capping a hole is a mutant every view must fail (10) |
| `for_items` doesn't say what a step makes (an early rounding folded into its host's step lists only the host), may be empty, and says nothing of where in the order a step goes; bounded zones elsewhere let a change to a neighbour pass face accounting | The agent may change only the steps the plan gives its gap; each of its steps lists exactly its gap and takes its gap's place in the order; and a geometric after-check holds the part with the gap's steps to the part without them outside the gap's own zone, on the B-rep and its meshes (2.1, 5.3) |
| Thickness along the normal misses a thin neck inside a region (two blocks fused along an edge), fails sharp edges under 90°, and takes in the fixed items' surfaces in the envelope (a thin plate under a region held for ever) | Walls measured only on the region's own surface and away from its edges; necks by the region's core, its material at least half `min_wall` from its surface, which must be one piece joined to its host's (4.3) |
| Joined by an area: a rod lying on the face, or a ball touching it, passes; material of fixed items counts | Joined by a disc: each section parallel to the face, up to `min_wall` above it, holds a disc of diameter `min_wall` of the region's own material (4.3) |
| The gate's failure on a constructed gap undefined; meshes' failures first seen at the gate; a held part a person could accept as VERIFIED EXCEPT though the agent made it wrong; regions get no probes, so the probes' secrecy protects nothing there | `done` runs the gate's checks on every view; a gap the gate fails goes back to the agent once with new seeds, then ends UNABLE, never HELD; the region checks' sample grids are offset by the gate's seed (5.7, 8) |
| Replay can't work: fixtures fail on a miss, tool output carries times and seeds, the scripted provider ignores requests, the gate's seed could be drawn twice | A replaying provider asserts each request's fingerprint in order and goes live only where the record ends; nothing the model sees depends on the clock; `measure`'s seeds are derived from the run, the gap and the call; the gate's seed is checkpointed before a probe runs (7) |
| A gap's dependents (a hole into it, a rounding of its edges) find its faces by the compiler's roles; while one gap is open the others' misses count against it | References into a gap's item are found by the face's own surface, which the layout gives exactly; `measure` counts only the gap's own misses (5.4); gaps are constructed in the order the part is made |
| Stage 4's other gaps (a shell's walls meeting at a rounded edge, a rounding with no proven construction) were in neither kind | Every gap that isn't a region is a determinate gap (2.2) |
| The exit can pass with an agent that never works: few gaps in the corpus, region parts outside "wrong but VERIFIED", the refusal hook circular, the blind set written by you alone, no cost target for gaps | Gaps reported on their own with minimum counts, region briefs in the blind set, refusals made at the build loop and constructed by the live model; wrong counted over VERIFIED and VERIFIED EXCEPT on their checked items; at least half the blind set written by others (plan, 7); a cost target for parts with gaps (11) |
| The escape hatch: no `-i`, a timed-out container left running, Docker's log written to disk, swap, an image digest a local build never matches, standard output shared with the solid, the second kernel's agreement holding every imported part | Fixed in 6.2 and 6.3; `imported` is not applicable to the second kernel in the capability table, by name (R6) |
| `fill` of 1 can never pass; specs already sealed get a default silently; envelopes may overlap | `fill` from 0.05 to 0.95; a region without `fill` is a question, never a default (R3, R7); envelopes may not overlap (4.1) |
| Departures from the plan not listed: section areas, smooth joins, the implicit kernel for organic shapes, the visual review, completion counting VERIFIED EXCEPT | Listed in 2.8, with the reasons |
| Rounds, the same miss, grouping, `--more` and nested budgets undefined | Defined in 5.5 |

## 2. Decisions, and where this page differs from the plan

**2.1 The agent changes how a gap is built, never what it is.** The plan
gives each gap's item a place in the order the part is made, and the steps
there are the gap's (`Plan.owner`). The agent may add, change and remove
those steps and no other; each step it writes lists exactly its gap in
`for_items`, and goes in its gap's place. Anything else is refused by code
before the document is built, and the refusal comes back as a tool error.
The spec reaches the agent only as words to read, and the check suite, the
oracle and face accounting only through `VisibleChecks`, which runs them
and gives back their misses: nothing in `forge_designer` can change any of
them, and an import-graph test (`tests/test_architecture.py`) fails if it
could (R2, R4).

That keeps the agent's steps where they belong, but a step can still reach
past its item: a union that swallows a neighbour, a cut through a rounding's
corner that face accounting leaves to its bounds. So every build the agent
makes is after-checked: the part built with the gap's steps, and the part
built without them (stage 4's build, which leaves the gap out), may differ
only within the gap's zone: a region's room (4.1), or a determinate item's
own solids in the oracle's outer form, grown by the build's tolerance. On
the B-rep by OpenCascade's boolean, and on its mesh by Forge's own code,
classifying a grid of the two meshes' difference (R11).

**2.2 Two kinds of gap, judged differently.** A **determinate gap** is any
item stage 4 couldn't build: every construction refused by OpenCascade, or
none written for it (a shell whose walls of different thickness meet at a
rounded edge; a rounding none of whose proofs held). Its checks are exact,
and the agent's construction is held to them as the compiler's would be (it
can end VERIFIED). A **region** is designed, and only its constraints are
checked (it ends VERIFIED EXCEPT at best, named). They share the agent, its
tools and its budget; they differ in what `measure` reports and what the
ending can be.

**2.3 Feedback is the checks' exact misses; a render is a second aid, and
is measured.** The plan says images in the loop added nothing measurable
(4.3). Work published since says otherwise for the hardest parts: CADSmith
(Barkley, Loghmani and Barati Farimani, 2026) found that taking the
rendered views away from its validator changed little on simple and medium
parts and much on complex ones (its mean Chamfer distance on the hardest
tier rose from 1.42 to 49.68). And a model correcting itself with no
outside feedback doesn't get better (Huang et al., 2024). So `measure` is
the agent's feedback, in numbers and names; `render` stays a tool it may
call; and the exit test constructs the gaps with and without it, keeping
it on only if the numbers say so (section 11).

**2.4 How much of a region is filled is stated, never guessed.** region.md
leaves the fill rule to this stage. It becomes a field, `fill`: the least
share of the envelope's room the shape takes up (4.1). The spec writer
drafts it from the brief's words where they say ("a solid grip", "light",
"mostly hollow"), and otherwise asks: a region without `fill` is a question
at confirmation, never a silent default (R3, R7). A spec confirmed before
`fill` existed is read as one with that question open, so it must be
confirmed again.

**2.5 The escape hatch makes a solid; the document records it.** The
architecture has sandboxed code return a BREP. It enters the document as a
new ForgeIR v2 operation, `imported`, whose parameters are the solid's
SHA-256 and the code that made it; the bytes are kept in the run's folder by
their hash. So the document stays a full record: the build replays from it
with no sandbox, and the code can be read. An imported solid has no history,
so references into it use the geometric test and match condition alone
(architecture, 4.6). The second kernel can't build it: the capability table
says `imported` is not applicable there, by name, so the agreement test
leaves it out as a zone (R6), and the verdict lists the second kernel as
inactive on that item.

**2.6 The run's states are built now.** The architecture's section 5 drew
the run's states; stage 4's `forge build` runs a confirmed spec straight
through, with no model and so nothing to resume. With a model in the build,
R9 applies there too: `forge_orchestrator` is rebuilt as the architecture
says (section 7).

**2.7 The agent never sees the probes that judge it.** `measure` runs the
check suite, face accounting and the topology at the suite's radius, and
fresh probes from seeds derived from the run, the gap and the call (7). The
release gate draws its own seed when construction ends, from the operating
system's randomness, and offsets the region checks' sample grids by it too.
An agent that fitted what it was shown misses the next draw.

**2.8 Where this page differs from the plan, besides the above.**

- **Section areas and smooth joins** (plan 4.5, the constrained class): the
  section areas become the joint's discs and the region's core (4.3), which
  say what the areas were for (a small blob, a thin neck, a joint by a line)
  as checks that can be measured on every view. Smooth joins are not
  checked: no definition of "smooth" was found that a slicer, a person and a
  check would agree on. The ending says the join's shape isn't checked, and
  it is an open question (section 12).
- **The implicit kernel's organic shapes** (plan 4.4, "parts that mix the
  two kernels") are left out: a region is built by OpenCascade's operations
  or the escape hatch, so every part keeps its B-rep, its STEP and its
  exact views. Mixed parts shipping as meshes only wait for a brief that
  needs them.
- **The visual review** (plan 4.7: advisory, on freeform and unchecked
  items) is built for regions: a model looks at the renders beside the
  region's `describe` and says, in the verdict, whether it sees what was
  described. It never changes the ending.
- **Completion** (plan 1.3) counts VERIFIED; a part with a region can't be
  VERIFIED by definition. For those parts completion counts VERIFIED EXCEPT
  whose only exceptions are its regions, and they are reported apart.

## 3. Where it sits

| Package | Layer | What stage 5 adds |
|---|---|---|
| `forge_spec` | L0 | `region.fill`; the spec writer's guide for regions; the spec checks' rules for an envelope (4.1) |
| `forge_checks` | L0 | The oracle's room for a region, keeping fixed items' shapes out (4.2); the region's check kinds (`kinds/region.py`) with their mutants and near-misses; `volume_within` on every view; `VisibleChecks`, the checks the agent is given; `imported` in the capability table |
| `forge_plan` | L0 | `Plan.owner`: each gap's place and steps; references into a gap's item by the face's surface (5.2) |
| `forge_ir` | L0 | The `imported` operation (2.5) |
| `forge_occ` | L1 | `imported` built from BREP bytes found by their hash, after-checked like every step (one valid closed solid; a region's within its envelope's box); the build without a gap's steps, for the after-check of 2.1 |
| `forge_sandbox` | L1 | **new**: the escape hatch (section 6) |
| `forge_models` | L1 | A replaying provider: recorded answers in order, each request's fingerprint asserted, live past the record's end (7) |
| `forge_designer` | L2 | **new**: the agent, its tools, its budget, its progress detector, the visual review of regions (section 5) |
| `forge_orchestrator` | L3 | Rebuilt: the run's states, checkpoints, resume, WAITING (section 7) |
| `forge_cli` | L3 | `forge build` gives gaps to the agent when a model is configured (`--no-agent` ends them UNABLE, as now); `forge resume`; each gap's lines in the verdict |
| `forge_eval` | L3 | The scripted designer; specs with regions, and refusals made at the build loop, for the offline tests (section 10) |

The layering rules of the architecture's section 2 hold as they are; one
is added: `forge_designer` imports `forge_checks` only through
`forge_checks.visible`, and never `forge_checks.probes` or the judge.

## 4. Regions

### 4.1 The fields, and the spec's rules

region.md's fields stay as they are (`on`, `place`, `length`, `width`,
`height`, `min_wall`, `describe`), and one is added:

- **`fill`**: the least share of the envelope's **room** the shape takes
  up, from 0.05 to 0.95. The room is the envelope less what the fixed items
  take from it or keep clear in it: a fixed item's material, and a fixed
  cut's air carried out of its face through the envelope (4.2). A region
  meant to fill its room wholly is a fixed item, not a region.

The spec checks add these rules, each a CAN'T or a question with its reason,
as every spec check is:

- the envelope stands on its face (`on`), inside the face's outline;
- no two regions' envelopes overlap;
- `min_wall` is no larger than the envelope's smallest size;
- the fixed items leave the envelope room a wall of `min_wall` fits in: a
  box of `min_wall` each way stands in the room on the face (else CAN'T,
  with what fills the envelope);
- `fill` is stated (else a question; 2.4).

### 4.2 The oracle and the judge

The oracle bounds a region between its forms: the inner form is the part
without it, the outer form the part with its room, which is the envelope
less every fixed item's material and every fixed cut's air **carried out of
its face through the envelope** in both forms, whatever the order the items
are made in. So a hole whose mouth is under the envelope stays open to its
full depth and up through the envelope: a region built over it puts
material where both forms have air, which face accounting fails, as it
fails a fixed item's surface the region buries (its spec points are no
longer on the built surface).

Topology counts solids and voids as the part without the region has them
(a region is joined to what it stands on, and seals no hollow), and leaves
the genus free within the envelope (a grip may have a hole through it).

### 4.3 The region's checks

Each is a check kind of its own (`forge_checks.kinds.region`), with its
mutants and near-misses as every stage 2 kind has (section 10), run on
every view that can answer it: the B-rep, the STEP file, the STL and the
3MF (R11). Every sample grid below is offset by a fraction of its spacing
drawn from the gate's seed (2.7).

The region's **own surface** is the built surface that face accounting
passes as lying between the forms within the region's room; its **own
material** is the built part's material inside the room and outside the
inner form.

| Check | What it holds | How it is measured |
|---|---|---|
| **within** | No material of the region outside its room, and every fixed item's surface still built | Face accounting, its misses within the envelope's box (grown by the coverage radius) reported as the region's |
| **filled** | The shape takes up at least `fill` of its room | The view's volume inside the envelope's box (a new view question, `volume_within(box)`: the B-rep exactly, by its common with the box; a mesh by the divergence theorem over its triangles clipped to the box and its sections on the box's faces), less the inner form's inside the box, over the room's volume, both of those the oracle's intervals. The share is an interval: at or above `fill` passes, below fails, across it holds |
| **walls** | No wall of the region thinner than `min_wall` | At every point of its own surface (the view's coverage at a quarter of `min_wall`), farther than `min_wall` from the surface's edges, how far the line into the part along the surface's normal runs before it leaves the part (`crossings`): at least `min_wall`, less the view's tolerance there. A thin place narrower than half `min_wall` every way may pass unseen; the necks below find the rest |
| **necks** | The region is not held together, or to its host, by anything thinner than `min_wall` | Its **core**: the points of a grid (spacing a quarter of `min_wall`) in its own material whose distance from the part's surface is at least half `min_wall`, less the spacing. The core must be one piece (grid neighbours joined), and must meet the core of what the region stands on, or the face itself where the host is thinner than `min_wall`. A neck thinner than three quarters of `min_wall` splits the core, so it fails; one between that and `min_wall` may pass, and the ending says to what width necks were checked |
| **joined** | Joined to its face over an area, not along a line or at a point | Each section parallel to the face, from a hundredth of `min_wall` above it to `min_wall`, at steps of a quarter of `min_wall`, holds a disc of diameter `min_wall` of the region's own material (on a grid of an eighth of `min_wall` over the envelope's footprint, classified; a disc found by the grid's distance to the nearest point that isn't the region's) |

Why these, and not one: the line along the normal is how a wall's thickness
is measured where there is a wall; it says nothing inside the material,
where a neck is, and near an edge sharper than a right angle it runs out
through the other face, so the band along the edges is the necks' to judge.
The core is how a neck is measured; by itself it would fail every sharp
convex edge (no ball inside a block reaches its corner), which is why only
its being one piece is asked, not that it reaches every point.

### 4.4 What the ending says

A part with a region ends VERIFIED EXCEPT at best, the region named with
what was checked on it and what was not, in fixed words:

> r1, the grip (designed to "comfortable to hold in a gloved hand"): within
> its 80 x 40 x 30 mm envelope; filled 64% of its room (at least 50%); walls
> at least 2.1 mm (at least 2 mm); no neck thinner than 1.5 mm; joined
> over a 2 mm disc at every height to 2 mm. Its shape is not checked, nor
> how smoothly it joins: look at it. The visual review saw: "a rounded
> handle rising from the plate, with finger grooves".

The preview shows the envelope as a box, tinted as the region's words in the
coloured brief are, before the spec is confirmed; after the build, the
designed shape inside it.

## 5. The construction agent

### 5.1 When it runs

After stage 4's build loop, on each gap in the order the part is made: its
dependents (a hole into it, a rounding of its edges) are compiled when it is
built, and built after it. Never on anything else: a determinate item built
and then failed by the judge is the compiler's fault or the kernel's, not a
shape to be found; the part is HELD and the fault is Forge's, as in stage 4.
A spec that can't be made ends CAN'T before anything is built. Without a
model configured, or with `--no-agent`, a gap ends UNABLE as it does now,
naming the item.

### 5.2 What it is given

- The confirmed spec in the fixed-wording renderer's words (stage 1), the
  gap's item marked, and its kind's definition page
  (`docs/definitions/<kind>.md`, or region.md).
- The document as built so far: every step, its item, and the faces and
  edges each made, by query (stage 3, section 6). Its own steps are the
  only ones it may change.
- For a determinate gap: each construction tried and what OpenCascade said
  (the after-check's words and the step), or why none was written; and the
  item's named faces with the surfaces the layout gives them. Its
  dependents find those faces by those surfaces (a plane, a cylinder),
  never by the roles of the steps the agent wrote, so whatever it builds
  them with, they are found, or the build says which isn't.
- For a region: its envelope, its room, `fill`, `min_wall` and `describe`.
- The guide to ForgeIR v2's operations, generated from `forge_ir`'s one
  source as V1's guide is (R8), and the tools' schemas, generated the same
  way.

### 5.3 The tools

Each tool's input is validated against its schema field by field before
anything is done (R8); a call that doesn't validate comes back as an error
the model reads, not as a fault of the run.

| Tool | What it does | What it gives back |
|---|---|---|
| `add_step` | Adds a step to its gap, in its gap's place: an operation of ForgeIR v2, its parameters, its inputs and its references by query | The step's name, or why it was refused (its schema; another item's place) |
| `change_step` | Changes one of its gap's steps | The same |
| `remove_step` | Removes one of its gap's steps | The same |
| `compile` | Builds the document (stage 3's cache copies every step that didn't change) and after-checks it (2.1) | Built; or each step OpenCascade refused, with the after-check's words; or where the part changed outside the gap's zone |
| `measure` | Runs the checks the agent may see on the last build (`VisibleChecks`, 2.7) | The gap's misses by name, with what was measured and what was asked (5.4); none: every visible check of the gap passes |
| `query_geometry` | Asks the last build: its box, a face's or an edge's facts, the faces near a point, a distance, a section through a plane | Numbers |
| `render` | Draws the last build from six sides and one corner, the gap's item tinted | Images, a second aid (2.3) |
| `run_code` | Runs build123d code in the escape hatch (section 6), when Docker is there | Its solid, kept as the gap's `imported` step; or the error, its last lines |
| `done` | Ends the agent's work on the gap: the gate's checks run on every view (5.7) | Accepted, or the misses the gate's checks found |

### 5.4 Feedback: the misses

`measure` reports what fails in the words the verdict uses, each with its
numbers, the largest first, at most forty lines, with a count of the rest:

> i3 diameter: built 5.912 mm, asked 6.000 mm ±0.050: 0.038 mm under the
> limit.
>
> Face accounting: 214 points of the built part, round (12.0, 4.5, 30.0),
> lie on no surface the spec asks for: material where the spec has none.
>
> r1 walls: 1.42 mm at (3.1, 8.0, 21.6), at least 2.00 mm.

Only the gap's own misses are counted (its item's checks; face accounting's
misses within its zone, grouped into places by joining misses less than five
coverage radii apart; a region's constraints); the rest of the part's are
listed after them, uncounted, so another gap still open never counts against
this one. Nothing in the text depends on the clock or on anything but the
document, the spec and the call's number (7).

### 5.5 Progress, budget and stop rules

- **A round** is a model turn that changes the gap's steps; after it,
  `compile` and `measure` run if the turn didn't run them. A turn that
  changes nothing is no round, and three of them in a row are a stall.
- **The misses' count** is the number of the gap's failing checks, places
  of face accounting's misses, and failing constraints. **The same miss** is
  the same check of the same item failing with its measurement unchanged
  within its tolerance, or a place of misses within five coverage radii of
  the last.
- **Progress:** the count must fall below its best within three rounds. If
  it doesn't, the agent is told so, in those words, with the advice to
  change approach (another operation, another construction, or the escape
  hatch); if it stalls again, the gap ends UNABLE, named, with its last
  misses. The same step refused with the same parameters twice is a stall
  at once (plan, 4.3).
- **`done` with misses** ends the gap UNABLE, with them: the agent can stop,
  but not pass.
- **Budget:** each gap has its own rounds, tokens and dollars, within the
  run's (`forge_models.Budget`, nested; section 9). When either is spent, the
  run goes to WAITING with what was spent named; `forge resume --more`
  raises the budgets, all three in the same proportion, and goes on from the
  same place with every model answer so far replayed (7). An unattended run
  (`--auto`, the exit test) ends UNABLE when its WAITING times out, the
  state kept.

### 5.6 The model

Claude Sonnet 5, as for every role, through `forge_models`: streaming with
an idle timeout, the guide and the schemas cached as the prompt's prefix,
every call recorded (ADR-0011), the cost counted per gap. Which model is
configuration; the recorded fixtures make every run replayable offline.

### 5.7 When it is done

`done` runs the release gate's checks on every view the gate will judge
(the B-rep, and the STEP and meshes at the export tolerances, which find
what the exact view can't: a wall a mesh's deflection makes thin), all but
the gate's fresh probes. With misses, the gap goes on (or ends UNABLE, 5.5);
without, its steps stay in the document, listing their item, and the whole
part goes to the release gate (section 8).

## 6. The escape hatch

### 6.1 What it runs

Build123d code, for a shape the operations can describe only badly (a
grip's swept, blended form) or an item OpenCascade refused every way the
compiler and the agent wrote it. The code is given the gap's frame (the
face's origin and axes, so it can work in the face's own coordinates) and,
for a region, its envelope; it leaves its solid in a variable named
`result`. Nothing else goes in.

### 6.2 The container

- **The image**, `forge-sandbox`: Python, build123d 0.13.0 and OpenCascade
  8.0.1, the versions the host builds with, and nothing else; its base image
  and every wheel pinned by hash in `forge_sandbox/image/`. Docker builds
  aren't reproducible to the byte, so the image's ID is recorded when it is
  built (`forge doctor --sandbox`), and a run refuses any other.
- **Each run** is `docker run -i --rm --name <the run's own name>
  --network none --read-only --tmpfs /tmp:size=64m --cap-drop ALL
  --security-opt no-new-privileges --user 10001 --memory 2g
  --memory-swap 2g --cpus 2 --pids-limit 128 --log-driver none` on that
  image (architecture, 4.6, with `-i`, the name, swap and logs added), with
  no folder of the host mounted.
- **In and out:** the code goes in on standard input. Inside, a fixed
  runner moves standard output to standard error while the code runs, so
  nothing it or OpenCascade prints can mix with the solid; then it writes
  the solid as BREP, its length first, at most 64 MB. The last 4 KB of
  standard error come back to the agent; the rest is dropped.
- **Time:** after 120 s on the host's clock, `docker kill` by name; a run
  that ends any way (a crash, a resume) first kills and removes every
  container of its own name left behind.
- **Without Docker** the tool is not offered, and the verdict says the
  escape hatch was unavailable and why.

### 6.3 What comes back

The BREP is read by OpenCascade in a separate process on the host, with a
time and a memory limit of its own: a file made to crash the reader crashes
that process only. It must be one valid, closed solid, of finite size,
within a metre of the part; a region's within its envelope's box, grown by
the build's tolerance. Only then does `forge_occ` take it in, as the gap's
`imported` step (2.5), which the agent then joins to the part or cuts from
it with ordinary steps, and the after-check of 2.1 holds as for any step.
Stage 6's parametric script will have to carry an imported solid as its
file, since no parameter rebuilds it; that is for stage 6 to settle.

### 6.4 What it is guarded against

| Threat | Guard |
|---|---|
| The code reaches the network (a brief's words written into code, a model misled) | `--network none` |
| It reads or writes the host's files | No mount; the root read-only; `/tmp` in memory, 64 MB; no log written by Docker |
| It takes the machine down | Memory with no swap, CPUs, processes and time all limited; the container killed by name; the output's size capped |
| It gains privileges | A user that isn't root, every capability dropped, `no-new-privileges`, Docker's default seccomp profile |
| An image that isn't Forge's | The image's ID recorded at build and checked before each run |
| Its output attacks the host | Read in a separate process with its own limits; its size capped; one valid solid or nothing |

Each guard has a test that tries to break it (section 10).

## 7. The run, checkpointed

The states are the architecture's (section 5), built in
`forge_orchestrator` (`states.py`, `run.py`, `resume.py`):

```
CONFIRMED ─► CHECKS ─► PLAN ─► BUILD ─► CONSTRUCT (each gap) ─► EXPORT ─► VERIFY ─► an ending
any state ─► WAITING (budget | provider | question) ─► the same state
```

(Drafting, the spec checks, the questions and the preview before
confirmation are stage 1's and stay as they are.)

- **A checkpoint after every state, and after every tool call within
  CONSTRUCT:** `runs/<id>/state.json` (the state, the spec's digest, the
  document so far, the budgets spent), with every model call recorded beside
  it and every solid and file kept by its hash. The gate's probe seed is
  drawn, and checkpointed, before any probe runs, so a resumed VERIFY uses
  the same seed and a held part can't be judged again with another.
- **Nothing the model sees varies between runs:** no times, no sizes of
  memory, no paths; `measure`'s probe seeds are a hash of the run's
  identity, the gap and the call's number; a render is drawn by fixed code
  at a fixed size.
- **`forge resume <run>`** goes on from the last checkpoint. A replaying
  provider in `forge_models` gives back the recorded answers in their order,
  and checks that each request is, to its fingerprint, the one recorded: a
  request that differs is a fault of Forge's (something the model saw
  changed), reported as such, never answered from the record. Past the
  record's end it calls the model and records (R9).
- **WAITING** names what it waits for: more budget, a provider that failed
  (after its retries), or an answer. Unattended runs time out to UNABLE, the
  state kept.
- **The kill-and-resume test:** a run is stopped at every state and after
  every tool call, and resumed; each time, every request's fingerprint, the
  document, the verdict and the files are the uninterrupted run's, byte for
  byte (the designer scripted, and its scripted answers checked against the
  requests' fingerprints too; section 10).

## 8. The release gate, with constructed items

The ending (stage 4, 9.3) is decided the same way, with gaps in it:

- **Every gap built:** the part is judged on every view as stage 4 judges
  it, with fresh probes drawn now (2.7, 7). A determinate gap is checked
  exactly, like every item, and can end VERIFIED; a region makes the ending
  VERIFIED EXCEPT at best, as 4.4 says.
- **The gate fails a gap's item** (its fresh probes, most often, since
  `done` ran everything else): the gap goes back to the agent once, with
  the misses that aren't the probes' and new `measure` seeds; failed again,
  it ends UNABLE, never HELD, so an agent's wrong part can't be accepted as
  VERIFIED EXCEPT with the evidence. A failure elsewhere in the part holds
  it, as in stage 4.
- **A gap not built** (no model, two stalls, `done` with misses): UNABLE,
  the item named, with the agent's last misses and its cost; no files are
  released. Stage 4's rule that an UNABLE is never silent holds.
- **A budget spent:** WAITING, to be resumed (section 7).
- The verdict lists for each gap what the agent made (its steps, or the
  escape hatch's code), its rounds, tokens, dollars and time, whether it
  drew renders or ran code, and for a region the visual review's words.

## 9. Cost and time

The plan's targets (1.3) are for the whole run, both drafts included: a
simple part's median under $0.25 and three minutes of machine time. A part
with no gap costs what stage 4's build costs, with no model call after the
spec. For a gap:

- **Budgets, each a hard stop:** per gap, 20 rounds, 400,000 tokens and $1;
  per run, $2 and as many tokens as its gaps' together (configurable; an
  open question, section 12).
- **The prompt's prefix is cached:** the guide, the schemas and the spec's
  words, which are most of each call.
- **A target for parts with gaps,** the median under $1 and ten minutes,
  the 90th percentile under $3 and thirty: proposed for your agreement
  (section 12), and measured over the corpus and the blind set (section 11).

## 10. Tested without a key

Every path of the agent runs offline, so the suite needs no key and no
network, as every Forge suite does.

- **The region's checks**, as every stage 2 kind: on hand-made region
  shapes inside their envelopes, each mutant beyond its tolerance fails (a
  little outside the room; over a hole's mouth; a fixed boss's side buried;
  filled a step short; a wall a little thin; two blocks fused along an edge;
  a rod lying on the face; a ball touching it; standing a little off it),
  and each near-miss passes (at each limit, within the view's tolerance), on
  the B-rep and on its meshes.
- **The scripted designer** (`forge_eval`): a provider whose answers are
  tool calls, so the agent's loop runs as with a model, and which checks
  each request's fingerprint as the replaying provider does. It writes a
  construction of a determinate gap through the tools (the part passes); a
  known shape for a region (it passes); and each way of going wrong: a step
  for another item's place (refused), a step that eats a neighbour (the
  after-check), a shape past its room, under-filled, thin, necked or loose
  (each found by `measure` and, if left, by `done` and the gate), misses
  that never fall (UNABLE at the second stall), `done` with misses (UNABLE),
  a budget spent (WAITING, then resumed to the same end).
- **Refusals made at the build loop:** a test hook tells the build loop
  that every construction of a chosen item of a generated spec was refused,
  without building them, so the gap's path runs on random specs: the
  scripted designer builds it its own way through the tools (a block as an
  extruded outline, a hole as a revolved cut), and the part must pass the
  judge and the grader as it did without the hook.
- **Random specs with regions:** the generator draws regions (an envelope
  on a face, `fill`, `min_wall`), its own model of the shape leaves the room
  unknown (a zone, as a rounding's corner is), and the scripted designer
  builds a random shape that keeps every constraint (boxes and rods joined
  well within the room, no thinner than `min_wall`): every one passes; a
  mutant of it that breaks one constraint fails.
- **The escape hatch**, where Docker runs (in the cloud workspace always;
  on the laptop only with Docker Desktop): a solid made and taken in; and
  code that tries the network, writes outside `/tmp`, forks without end,
  fills memory, runs forever, prints into its output or writes 100 MB, each
  stopped by its guard; a container killed on its timeout is gone after;
  a BREP made to be malformed is read without harm.
- **Kill and resume** at every state and after every tool call (section 7).
- **The layers:** `forge_designer` reaches the checks only through
  `VisibleChecks`, and never the probes the gate draws, nor the spec's lock
  (`tests/test_architecture.py`).

## 11. The exit test

The plan's row: the corpus and a fresh blind set; none wrong but VERIFIED;
completion 98% or more; cost under target. In full:

1. **The offline suites pass** (section 10), with 1,000 random specs with
   regions and 1,000 with refusals made at the build loop: every part
   passes, no mutant survives.
2. **The agent, live, on gaps whose answer is known:** 50 or more random
   specs with refusals made at the build loop, constructed by the model
   and graded against the generator's own model (stage 4, 12.3): none wrong
   but passed; at least 98% constructed.
3. **The corpus, end to end, with your key:** V1's validation suite (92
   briefs), the recorded runs' briefs, the arm's 13 when you give them,
   and V1's 27 false passes: each drafted twice, confirmed, built, its gaps
   constructed, judged, and graded against the answer keys written before
   the run (`forge_eval` reads them; I never open them):
   - **wrong but VERIFIED:** none, counted over the VERIFIED parts and the
     VERIFIED EXCEPT ones on their checked items, each with its 95% bound
     and its denominator;
   - **completion:** at least 98% of in-scope confirmed specs end VERIFIED
     (or VERIFIED EXCEPT for their regions alone) with no further input;
   - **cost:** the simple parts' median under $0.25 and three minutes, both
     drafts included; the parts with gaps under their own target (9).

   Parts with gaps are reported on their own, as well as in the whole.
4. **A fresh blind set** of 30 briefs, at least half written by people
   other than Forge's developers (plan, 7), at least 10 of them calling for
   a region, their keys locked before Forge sees them: the same measures.
5. **Renders measured:** the gaps of 3 and 4 are constructed twice, with
   `render` and without; it stays on only if completion with it is higher
   and the difference's 95% interval is above zero, and its cost is
   reported either way.

## 12. Open questions for you

1. **A region's fill:** always asked when the brief doesn't say (as now),
   or a default the spec writer may assume and show?
2. **Smooth joins** (plan 4.5): drop them, as now, or say what makes a join
   smooth enough (a least radius where the region meets its face?)?
3. **Budgets:** $1 a gap and $2 a run to start with; and the target for
   parts with gaps: the median under $1 and ten minutes?
4. **The escape hatch on the laptop** needs Docker Desktop. Without it, the
   escape hatch is unavailable there and the verdict says so: fine, or
   should it be installed?
5. **Who confirms the corpus's specs for the exit test?** Every one by
   hand is days of your time; the other way is to confirm a sample (each
   wrong-but-VERIFIED count needs confirmed specs in its denominator) and
   report the rest as BUILT TO DRAFT, graded the same way. This must be
   settled before the run.
6. **The blind set:** who writes the half not written by you?

## 13. The order of work

1. `region.fill` in the schema and region.md (for your approval), and the
   spec checks' rules for an envelope.
2. The oracle's room (a fixed item's shape kept out, cuts carried through
   the envelope); the region's check kinds and `volume_within` on every
   view, with their mutants and near-misses; the ending's words.
3. The run's states, checkpoints, the replaying provider and
   `forge resume` in `forge_orchestrator` and `forge_models`, first on
   stage 4's build with no model, with the kill-and-resume test.
4. `forge_designer`: the tools, `VisibleChecks`, the misses' words, the
   progress detector, the budgets; `Plan.owner` and references by surface;
   the after-check of 2.1; the scripted designer; the layer test.
5. Refusals made at the build loop and generated regions, through the
   agent, offline (section 10).
6. The escape hatch: the image, the runner, the separate reader, `imported`
   in `forge_ir`, `forge_occ` and the capability table, the tests that try
   its guards.
7. The visual review of regions; `forge build` and `forge resume` with the
   agent; each gap's lines in the verdict.
8. The exit test (section 11).

Each step lands with its tests, lint and type checks clean, and is saved to
the laptop.

## Sources

- J. Barkley, R. Loghmani, A. Barati Farimani, *CADSmith: Multi-Agent CAD
  Generation with Programmatic Geometric Validation*, arXiv:2603.26512,
  March 2026: <https://arxiv.org/abs/2603.26512>.
- G. Son et al., *Self-Improving CAD Generation Agents with Finite Element
  Analysis as Feedback*, arXiv:2605.17448, May 2026:
  <https://arxiv.org/abs/2605.17448>.
- J. Huang et al., *Large Language Models Cannot Self-Correct Reasoning
  Yet*, ICLR 2024: <https://arxiv.org/abs/2310.01798>.
