# Forge V2, stage 4b: coverage

Status: design, revision 5, **locked 10 November 2026** by the owner's
direction: part one (4b.0 to 4b.10), part two (4b.11 to 4b.18), the peak
check, their order, 4b.0a's decisions (ADR-0022 to ADR-0034) and the exit
tests. Revision 5 was reviewed adversarially twice and its fixes verified
(section 1.1's last rows). From here a change to scope, order, decisions
or exit tests is made only by a decision record the owner approves (2.4);
the first, ADR-0035 (13 November 2026), adds the oracle's count of
through-holes to item 7 and does 4b.0b before the Python move.
Each sub-stage's detail is designed and reviewed adversarially when it
starts.
Revision 1 was reviewed adversarially twice (this page, and the rest of V2's
plan), revision 2 and revision 3 once each, the same day; section 1.1 says what the
reviews changed. Revision 5 follows the scope audit
([V2-stage4b-audit.md](V2-stage4b-audit.md)). Nothing on this
page is built until stage 4's exit test passes (plan, section 8).
Companion to [V2-plan.md](V2-plan.md) (sections 1.2, 1.3, 4.4, 4.5, 8) and
[V2-architecture.md](V2-architecture.md).

---

## 1. What stage 4b delivers

**The goal.** By the end of V2, Forge models any mechanical part a
professional engineer models in SolidWorks, Fusion 360, Onshape or Creo,
using OpenCascade, Forge's own geometry and its implicit kernel to
everything they do well; every part judged as stage 4's are, so that no
wrong part ends VERIFIED; and everything after V2 is added on top, never
rebuilt.

**Where stage 4 leaves Forge.** Three audits of the code (an inventory, a
catalog of professional CAD against OpenCascade 7.9.3, and an adversarial
architecture review) found:

- **The kernel layer is broad.** ForgeIR v2 has 37 operations and
  `forge_occ` builds every one (`forge_occ/ops/__init__.py`). The compiler
  writes about half of them: never `bend`, `coil`, `loft`, `sweep`, `pipe`,
  `torus`, `wedge`, `mirror`, the pattern ops, `transform`, `offset`, IR
  `shell`, IR `hole`, `profile_polygon`, `profile_gear`, `datum_point`; nor
  extrude's draft or symmetric modes, partial revolves or blended booleans.
- **The spec has 20 kinds** (`forge_spec/schema.py:302-773`), all
  axis-aligned (`placement.py:10`), on flat faces and cylinder sides only,
  one connected solid (`placement.py:2243-2248`), profiles of lines and
  arcs (`draft.py:178-193`), no parameters, tolerances as ± values and
  ISO 2768-m.
- **The trust architecture is sound and stays**: the confirmed, cited
  spec; the deterministic compiler with proven-equal alternatives; the
  oracle independent of the compiler; face accounting both ways; every
  field checked or shown unchecked (R1); choices told from the other
  choices; mutants and near-misses; verification classes; the release gate
  and its endings; ForgeIR's declarative ops with after-checks,
  history-carried names and references by query; the generator's truth as
  point membership; the import-graph rules.
- **The geometric substrate under it is not yet a foundation**: faces are
  world directions (about 290 axis-name sites in 20 files); "through" and
  fits come from a symbolic "material under a face" written per kind
  twice (`frame.md:83-113`, `place.py:196-346`); the oracle's solids are
  convex quadrics and tori (`shapes.py:1-26`); roundings are exact only
  along straight and circular edges (`rounds.py`); one fixed build order
  (`frame.md:113-135`); and each kind is written into central chains in
  every program (about 560 dispatch sites, including the preview views,
  the two-draft comparison, the questions and the spec checks).

**So stage 4b is in two halves.** First the substrate is generalised and
today's 20 kinds re-proven on it, byte for byte (4b.0). Then the new kinds
are added (4b.1 to 4b.10), each as modules behind the general protocols,
touching no shared code.

**And in two parts, then a peak check (revision 5, the owner, 10 November
2026).** The goal above is held to its word: by the start of stage 5,
Forge designs and builds single parts as a professional engineer does, at
the limit of what OpenCascade, Forge's own geometry, its implicit kernel
and open-source libraries can do together, so that what it still can't do
is missing only for want of a proprietary kernel, format or licence. The
scope audit ([V2-stage4b-audit.md](V2-stage4b-audit.md)) compared the plan
with SolidWorks, NX, Creo, CATIA, Fusion and Onshape capability by
capability and found most of what was missing to be a choice, not a
constraint. So, in this order:

1. **Part one** (4b.0 to 4b.10, section 2 and 3): the scope agreed on 3
   November, built and counted in full, ending with its whole run on frozen
   code, the corpus and the professional set (section 5).
2. **Part two** (4b.11 to 4b.18, section 3.2): what the audit found
   missing for designing and building single parts, and what revision 4
   left outside V2 that can be done: Forge's own freeform offsets; G2
   roundings on freeform faces and G2 corner blends with setbacks;
   class-A surfacing; subdivision modelling; engineering calculation and
   materials; analysis (structural, thermal, flow) and the solvers under
   it; generative design and optimisation; meshes, more imports and
   feature recognition; and the breadth the professional tools have that
   part one's lists don't. Each sub-stage is counted as part one's are, and
   part two ends with its own whole run.
3. **The peak check** (section 5.1): the audit made again against
   everything built, every capability found missing either added or left
   out for one of section 4's reasons, and the owner's long debugging
   campaign on fresh seeds across all of it.

Then stage 5. Part two is designed into 4b.0 from the start: 4b.0a reviews
the protocols against part two's kinds and against what stages 5 to 9
consume, and the conformance matrix (2.3) holds them, so part two lands as
kind modules on the same foundation, never as a rebuild of it.

### 1.1 What the reviews of revision 1 changed

| Finding | This revision |
|---|---|
| No rule for item order: one fixed order can't say "the hole, then the rounding", a flange on a flange, a split then a shell | 4b.0 item 11: an explicit dependency graph, with `as_of` |
| No contract for referring to the faces and edges new kinds make; "any edge chosen by meaning" undefined | 4b.0 item 12: topology contracts per kind and a selection language, resolved independently by compiler and judge |
| "Exact by invariant" proves a necessary condition only (an overflowing rounding satisfies it; a draft about a shifted neutral line does too) | Renamed **exact by construction**: the definition states the spine, neutral curve or offset rule; the oracle computes it; the invariant is only a fast first test (4b.0 item 5) |
| The same surface said to be both shared and computed independently | 4b.0 item 13: computed once before confirmation, stored as explicit geometry in the confirmed spec, verified by its defining properties independently |
| Imported geometry checked against itself; the trust core can't read STEP | 4b.8: Forge's own STEP reader in the trust core for the entities it accepts; the raw file's faces held; the healed body measured against them |
| Wide view tolerances quietly weaken "exact" | 4b.0 item 9: every region's tolerance capped against its tightest band; above the cap it is bounded |
| Exit runs biased (counted seeds also used to fix), pairs not truly interacting, compute unaffordable, bound only just under 1 in 3,000 | Section 5: fresh seed ranges, interaction defined geometrically, covering arrays, 3,000 counted per sub-stage, a final 30,000 on frozen code, regression replay |
| 4b.0's exit never tests that later work will be additive | 4b.0 exit: one pathfinder kind per family through every program, and a conformance matrix |
| Datums, curves, sheet bodies came after the kinds that need them | Moved into 4b.0 (items 7, 8) |
| Nobody solves the sketches | 4b.0 item 8: Forge's own constraint solver, checked by an independent residual checker |
| The confirmation views can't show 4b parts | 4b.0 item 15: views from the compiled geometry |
| Overclaims: Pappus "exact", drafted area formula, corrected Frenet "independent", `GeomFill_Gordon` on 7.9.3 (it isn't there), morphological rounding "exact" on lower-bound fields, wrap on cones, G2 both in and out, GD&T "measured", standards citations | Corrected where each appears below |
| *Review of revision 2:* "compute once, verify by properties" is again a necessary condition only (a bulging loft meets its sections) | Item 13: the whole algorithm pinned in the definition and recomputed independently by the verifier and the generator; constructions that aren't unique are a class of their own, **defined by properties**, ending VERIFIED EXCEPT |
| Cross-cutting changes left to later sub-stages (derived products, classes and endings, configurations, composites, tolerance classes, mesh-only parts, the guide) | Moved into 4b.0 (items 17 to 24) |
| 4b.0's exit never tests additivity itself; its pathfinders are each family's hardest member; no counted run, no speed gate | 2.3: each pathfinder lands in its own kind modules only (a lint), one simple member per family; a counted run of 10,000; a speed gate |
| Ordering: migration after the steps that need it; a kernel switch mixed with the refactor; freeform hosts before freeform solids; boundary boss in 4b.1; mold halves needing stage 8 | 2.1 reordered; boundary boss and cut in 4b.5; mold halves derived products of one part |
| Selections and the sketch solver assume more than the trust core has | Items 8 and 12: resolved before confirmation, stored, shown, checked both ways; the solver a proposer outside the trust core, its branch verified inside it |
| The trust-core STEP reader under-specified and placed last | Item 24: built in 4b.0d1 as the re-open path of every shipped STEP, planar and analytic imports in 4b.0, the rest at 4b.8 |
| Exit statistics unspecified; the catch-rate target unshowable with its trials | Section 5 specified; plan 1.3 sets trials per tier and the people's time |
| Screw symmetry, analytic roundings, CAN'T for Forge's own limits, the implicit fallback | Corrected in items 4 and 5, 3.1 and 4b.1 |
| *Review of revision 3:* "all pass" contradicts the false-hold budgets | Section 5: no wrong part, no surviving mutant, impossible specs CAN'T; holds and UNABLE within the family's budget, each filed as a bug |
| Compute unbudgeted, kinds under-counted (about 150 with modes, not 40), every view on every spec unaffordable | 4b.0a names the machine and a total compute budget, with a fallback; 4b's whole run is 10,000 (1 in 3,000), the 1 in 10,000 shown at stage 9 on release code |
| 4b.0's order still pointing backwards (reader last, freeform hosts before splines, continuity late) | 2.1 reordered: reader and continuity in d1, freeform hosts after d3, the surface-or-region rule at 4b.0a |
| Classes not mapped to endings; additivity after 4b.0 undefined; strict serial order with no re-plan | Item 18's table; section 2.4's rule; section 6's dependency graph and re-plan gate |
| Selections checked on the wrong shape; the fallback judged against itself; standard tables a single point of failure; 4b.0's exit missing paths | Items 12 and 20, 3.1, 2.3 |
| *Revision 5, the owner and the scope audit (10 November 2026):* T-spline and subdivision modelling, G2 corner blends with setbacks and G2 roundings on freeform faces left outside V2 | Part two: 4b.11, and 4b.13 (subdivision with creases; T-junction refinement a later step, patents checked); section 4 rewritten |
| Freeform offsets, shells and thickening left to OpenCascade's offset, its weak spot, though G2 on freeform faces is built from them | 4b.11: Forge's own offsets (3.1, 3.2) |
| Nothing sizes a part from its loads; materials carry a density only; analysis only passes or fails a part at stage 6 | 4b.14 calculation and materials; 4b.15 analysis, its core brought forward from stage 6 and widened; 4b.16 generative design and optimisation |
| Boundary surfaces, fills and loft ends tangent (G1) only; no G3, bridge surfaces, fairing or reflection checks | 4b.12 class-A surfacing |
| STEP the only import; no meshes, IGES or board outlines; no feature recognition or live rules on imported solids | 4b.17 |
| Lists narrower than the professional tools' (gears, springs, threads, tapers, plastic features, mold feed and cooling, casting and forging, weld profiles, lattices, sketch and feature options) | 4b.18 breadth |
| "Outside V2" mixed constraints of technology with choices of order | Section 4: only what technology blocks, or the owner deferred, stays out; every other capability is placed in its stage |
| *Review of revision 5:* nonlinear, contact and flow had one solver; the two solvers shared a mesher and their setup; equilibrium checks are necessary conditions only; the analysed shape was never shown to be the shipped part | 4b.15: two of everything, each with its own setup and mesher; items 25 and 26 (resultants recomputed from the confirmed spec; the FE boundary face-accounted against the shipped STEP) |
| "Bounded" analysis overclaimed; no class for calculated or analysed requirements | Item 18: per stated method, a guaranteed error bound or VERIFIED EXCEPT naming the method; the worst end of every interval; singular points |
| A model-proposed cage, an optimised refit or a repaired mesh could launder its class into VERIFIED; optimisation, rules and recognition not placed before or after confirmation | Item 18: a result takes the class of its weakest input; item 28: proposals before confirmation, stored, hash-locked, never re-run; 4b.13's cage classes |
| Part two needs what 4b.0's protocols lacked: loads and requirements, analysis registries, continuity tolerances, versions in the hash, full material records, analysis representations, evaluation near irregular points, meshes by winding number | Items 25 to 29; items 2, 4, 5, 6, 9, 14, 15 and 18 widened |
| Part two's exits unmeasurable as written; its pathfinders missed the methods it stresses; the kind count and compute stale | Section 5's part-two bullet (manufactured solutions, interaction for analysis, requirements re-verified); 2.3's pathfinders; 4b.0a's recount and cost measurements |
| No fitter; no freeform offset in part one; edits to earlier modules not replayed; dependencies missed and duplicates; calculators that rate pairs; citations and licences | 4b.13's fitter; 4b.3's constant freeform offset; 2.4's replay rule; 3.2's order and one home each; a mating part's data as confirmed inputs; citations corrected; every external program a separate process |
| Audit gaps neither placed nor excluded | Placed: SAT and x_t import, OBJ and glTF export, checks on one part, patterns on freeform faces, mold flow and bend sequence (stage 6), the sketch, sweep and loft options, more gears, hydraulic ports, roundings on imported edges |
| *The owner's test case, a jointed robotic judo dummy (10 November 2026):* no impact analysis; no actuators | 4b.15's impact (explicit dynamics); stage 8's actuators as standard parts, joint torques checked against them |
| *4b.0a:* what part two needs from the foundation not written down | 2.5: part two against the protocols; the ADRs in 2.1.1 |
| *Second review of revision 5:* items 25 to 29 in no step; the kernel replay split and Python moved with it; the documents disagreeing on what analysis may make VERIFIED; bounds blind to the mesh's departure from the part; per-input worst ends; pair coverage unaffordable; the import graph undecided; loads, materials, expressions and registries too narrow; a region laundered into VERIFIED | 2.1's d4 and 4b.0a′; item 18's one list with domain-perturbation terms and the interval box; section 5's "can meet" table and covering arrays (ADR-0027); ADR-0034; items 8, 25, 26, 29 widened; ADR-0031 and item 18 |
| *The owner, 13 November 2026, during the kernel replay (ADR-0035):* through-holes the oracle doesn't count left listed, never closed; the Python move replayed before the restructure, overlapping it | Item 7: the oracle counts every body's through-holes; 2.1: 4b.0b after the 8.0.1 replay, the Python move after 4b.0b |
| *And:* x_t and JT routes; single-reader imports; the speed gate's measure; resizes and regions against item 28; ADR numbers colliding; tool versions in the spec's hash; one loose tolerance widening every check; the Rust core's agreement, math library and twins; calculators' two kinds of requirement; the judo dummy's impact and torques; audit gaps (weld symbols, DWG export, reactions) | Section 4 (x_t write blocked, DWG export, a fourth reason); 4b.17; ADR-0022 to ADR-0034 renumbered and amended; items 27, 28; 4b.13 to 4b.18 |

---

## 2. Stage 4b.0: the substrate

### 2.1 In four steps, the old code compared with the new at each

- **4b.0a, decisions** (an ADR each, before any code): OpenCascade 7.9.3 or
  8.0 (and the Python floor it needs, the sandbox image's version to
  match, the stale docs naming build123d fixed); whether the trust core
  may hold Forge's own compiled code (still no CAD library, so R11 holds);
  a per-operation tolerance policy (booleans between B-spline faces widen
  edges past today's 1e-4 mm, `aftercheck.py:57`), in the cache key; the
  schema version and migration rule (item 14); the unit a "kind" is
  counted in (a kind or mode of the registry), and the exit runs'
  arithmetic checked against it (about 150 kinds and modes in part
  one, about 120 more in part two); the reference machine and a total compute budget for all of
  4b's runs, with the fallback if pace falls short (more workers or cloud
  machines, fewer per-kind strata with the weaker bound stated, or a family
  moved past V2: section 6); the sketch solver's choice (licence, Windows
  wheels); a check-side DXF reader for R5; the rule for when a shape is a
  surface item and when a stage 5 region; the protocols of 2.2 reviewed
  against every kind planned on this page, part two's included, and
  against what stages 5 to 9 consume (the agent's ops, the print rules,
  drawings, resizes, mates); where part two's analysis core (4b.15) and
  the generator's analysis truths live in the import graph (the trust
  core holds no solver: R11); the placement of every capability section 4
  moves into a stage, written into the plan before any code; a note per part-two sub-stage at the level of the protocols, stating
  what each of its kinds needs from each method of 2.2, so the review has
  something concrete to review; the kinds and modes recounted (about 150 in
  part one, about 120 more in part two) and every exit run's arithmetic
  (top-up strata, pairs seen 50 times, the guide's size) redone on the
  count; each analysis and optimisation type's cost measured on its
  pathfinder, analysis strata given stated size ranges, and a bound claimed
  only within them; each external program's licence, build and Windows
  availability (gmsh, Netgen, CalculiX, code_aster, OpenFOAM, SU2,
  OpenRadioss, LibreDWG, `slvs`, `dolfinx_eqlb`: separate programs, never
  imported; the GPL ones' source offers
  in the Docker image), and the terms of Siemens' XT format reference.
- **4b.0a', the kernel switch** (ADR-0022: 8.0.1 chosen), on its own, so
  kernel differences are never mixed with refactoring ones, in two
  sub-steps each replayed before the next: first OpenCascade 8.0.1 on
  today's Python, with stage 4's whole counted run (10,000 seeds) and every
  kept regression replayed on the unrefactored code; then, once 4b.0b is
  done and proven (the owner, ADR-0035), CPython 3.14 (ADR-0023) on the
  restructured code, with every regression, the 2,000 held-out seeds and a
  fixed 2,000 of the counted seeds replayed against the 8.0.1 replay's
  records, any difference sending it to a whole replay. **Both done**:
  8.0.1 on 14 November 2026, CPython 3.14 on 15 November
  ([V2-stage4b-kernel.md](V2-stage4b-kernel.md), 4 and 5).
- **4b.0b, a module per kind, nothing else** (item 6): every program's
  per-kind code moved behind registries; a lint forbids kind names outside
  kind modules. Proven by byte-identical ForgeIR documents, check suites,
  nominals and verdicts on stage 4's seeds. Done after the 8.0.1 replay
  and before the Python move, on the Python that replay ran on, so the
  move's replay sees Python's differences alone (ADR-0035).
- **4b.0c, geometry:** first, the same numbers on any machine (found at
  4b.0b's end, V2-stage4b-0b.md 6.4: NumPy's and OpenBLAS's last bit
  depends on the CPU's SIMD level, so a part's digests differ between an
  AVX-512 and an AVX2 machine though each repeats itself): every result
  Forge records or decides by made independent of the SIMD level and the
  BLAS, proven by the same seeds' fingerprints equal on both kinds of
  machine with no pins, before anything else in 4b.0c moves; then
  frames, depth by geometry, analytic hosts (items 1
  to 3), with the schema migration (item 14) that they need.
  Status (V2-stage4b-0c.md): the same numbers on any machine **done**
  (six machines equal on 200 seeds; every one of the 10,000 counted seeds
  passing old and new); item 14 done (schema 1.1); item 1a done for the
  solver, the judge and the generator (byte-identical), the planner's and
  the second kernel's with 1b; 2a (end conditions) and 3a (placeable
  faces: frames, outlines and material asked of the face) done; 1b's first move (items turned in their face,
  schema 1.2) and second (holes, bosses and posts leaning on it, schema
  1.3) done; its third's first step (positions along a face's own axes,
  and a turned item's far face, schema 1.4), second (a turned box's
  sides), 2c (a turned item's edges rounded) and third (a body leans,
  schema 1.5) done, its schema 2.0 made with item 2b's (V2-stage4b-0c.md,
  revision 12); its step 5 (revision 13: what a turned or leaning item
  still lacked) done but for what waits for 2b and 4b.0d1; 3b's first
  step (a standing item round a side at any angle), second (on a ball's
  or a dome's surface, schema 1.6), third (on a cone's side) and fourth (on
  a round-ended tab's end) done; its fifth (a torus) waits for 4b.0d1. 2b
  next.
- **4b.0d, the rest, in four parts, old against new after each:** d1 the
  oracle and the reader (items 4, 5, 9, 24, the continuity check kind, and
  the oracle's certified face-face intersections with convex, concave and
  tangent edge classes), on the compiled core (ADR-0024): first today's
  judge ported to it and proven to give identical answers on every test
  and stage 4's seeds, the Python core kept as its specification and
  cross-checked in CI from then on, then the new solids written in it; the
  speed gate (ADR-0027) measured before 4b.1's counted runs; d2 topology (items 7, 11, 12); d3 sketches and
  pinned algorithms (items 8, 13), then freeform hosts (item 3); d4 the
  cross-cutting rest (items 15 to 23), and revision 5's items 25 to 29 and
  the expression language of item 8, each with an old-against-new proof
  (no verdict changes on stage 4's seeds). Then the pathfinders (2.3).

### 2.1.1 4b.0a's decisions (10 November 2026)

Made after research into what is current (kept with the 4b.0a notes), each
an ADR:

| ADR | Decision |
|---|---|
| [0022](adr/0022-opencascade-8.md) | OpenCascade 8.0.1 through `cadquery-ocp-novtk` 8.0.1.1.0, pinned; the switch is 4b.0a′, its own step: the kernel first with stage 4's whole counted run replayed, then Python; 8.0's Gordon surfaces, helices and topology graph used as alternatives proven equal |
| [0023](adr/0023-python-3-14.md) | CPython 3.14 the floor and runtime, after the kernel's replay; the trust core also tested on 3.15 and free-threaded 3.14t |
| [0024](adr/0024-compiled-trust-core.md) | The trust core's hot paths in Forge's own Rust crate (PyO3, maturin): certified intervals by outward rounding, a math library with proven bounds, exact predicates, B-spline evaluation, outward-rounded culling, threads with the GIL released; the Python core kept as the specification, a twin for every new solid, never contradicting each other; python-flint as a referee in CI |
| [0025](adr/0025-tolerance-policy.md) | Every operation states its tolerance class, measured on a freeform fixture set; the file states the loosest, every face is judged at its own; the cap governs; continuity tolerances measured, with floors; the class in the cache key |
| [0026](adr/0026-schema-versions.md) | Schema versions, migrations proven oracle-equal, verdict changes listed; the hash locks what changes a value's meaning; the judging tools' versions go in the evidence and the cache key |
| [0027](adr/0027-counting-and-compute.md) | A kind is a registry entry; about 300,000 counted specs for 4b with a covering-array stratum, about 450,000 with shakedowns and re-runs; analysis strata costed first; a speed gate (median 6 s, 99th percentile 60 s, on 4b.0's distribution) before 4b.1's counted runs; the fallback order, more machines being the owner's call |
| [0028](adr/0028-sketch-solver.md) | `planegcs` as the 2D proposer, `slvs` for 3D and a second opinion, the trust core's residuals the judge |
| [0029](adr/0029-analysis-stack.md) | Two programs for every analysis type; VERIFIED only for energy-norm quantities of steady linear conduction and elasticity under Forge's own guaranteed bounds; everything else VERIFIED EXCEPT, naming the method |
| [0030](adr/0030-geometry-libraries-and-formats.md) | manifold3d, trimesh, lib3mf, libigl's core; OpenSubdiv as a reference; T-splines allowed, three patents avoided by design; a route, a check and a limit for every file format; x_t read, not written |
| [0031](adr/0031-surface-item-or-region.md) | A shape whose geometry is in the confirmed spec is an item; one made after confirmation is a region; undetermined freeform geometry is defined by properties at best, through any conversion |
| [0032](adr/0032-check-side-dxf-reader.md) | Forge's own DXF reader re-opens every DXF shipped |
| [0033](adr/0033-external-programs.md) | One runner, separate processes, pinned versions recorded in the evidence, licences kept apart |
| [0034](adr/0034-trust-core-dependencies.md) | The trust core imports the standard library, NumPy and Forge's own crate only; part two's checking code in it, every solver and proposer above it (supersedes ADR-0002 in part) |
| [0035](adr/0035-through-holes-and-the-restructure-first.md) | The owner, 13 November 2026: the oracle counts every body's through-holes (item 7); 4b.0b done after the 8.0.1 replay, the Python move after it |
| [0036](adr/0036-the-restructures-proof-scaled.md) | The owner, 14 November 2026: 4b.0b's byte-identity proof digests everything a verdict consumes for every seed, and verdicts on built parts for samples; about three to four days instead of two weeks |
| [0037](adr/0037-the-same-numbers-on-every-machine.md) | 16 November 2026, 4b.0c's first item: every V2 number through `forge_numeric` (msun's elementary functions, products and linear algebra in a fixed order, a compiled twin), so a seed is the same part, and its digests the same, on any machine |

ADR-0012 to ADR-0021 are the core V2 decisions listed in
[V2-architecture.md](V2-architecture.md), section 10; stage 4b.0a's begin
at ADR-0022. Section 2.5 holds part two's notes against the protocols; the
doc drift from the 3 November audits is fixed; the second adversarial
review's findings are closed in this revision (1.1).

### 2.2 The generalisations

Each is made in every independent program (solver, judge placement,
oracle, check compiler, compiler, generator, and the second kernel where
its capability table applies), each its own way, as R2 requires.

| # | Generalisation | What it is |
|---|---|---|
| 1 | **Frames everywhere** | Every face and copy carries an orthonormal frame as vectors. Face names are the item's own (`+x` is the block's own +x side). Positions keyed by face-local axes, x, y, z kept as aliases on aligned faces. A typed `direction` field: a frame axis, angles from a face's axes, or a reference (a face's normal, an item's axis, an edge) |
| 2 | **Depth by geometry** | Blind, through-next, through-all, up-to-face, up-to-vertex, up-to-body, offset-from-face, from-to, symmetric, each written in the definitions (feature-level, as CAD means them: up to next is the first face that covers the whole profile, not ray by ray). Before confirmation the preview build resolves them and the spec records the resolved values, which the person confirms; the oracle and generator verify them on their own shapes. The per-kind "material under a face" algebra is retired. Two directions with their own end conditions, and start conditions (from a face, a vertex, an offset), are part of this protocol from the start (revision 5) |
| 3 | **Any face hosts** | A placeable-face protocol: a surface with its frame at each point, its outline, and the foot of what stands on it (the item's section carried back to the host). Analytic hosts at 4b.0c; freeform hosts after 4b.0d3, with the certified solids, splines and datums they need. On a freeform host, a position is a projection from a stated sketch plane along a stated direction, or a geodesic distance where the brief says along the surface; relation checks measure the same |
| 4 | **Certified solids** | The oracle's `Solid` is a protocol of methods (sign-exact classification, a distance lower bound, certified line and circle crossings, parametric patches with curvature bounds), dispatched by method. B-spline patches by certified subdivision with exclusion tests (letters already do this for Bézier outlines); tangent crossings and smoothly joined faces by second-order models, or UNKNOWN and held, with false holds budgeted per kind. Screw-symmetric solids classified exactly by untwisting the point: threads (profile in the axial plane), helical gears and twisted extrusions (profile across the axis); a round-wire coil by a certified distance to its helix; conical coils, tapered threads and run-outs are by construction. Distance to the boundary of a CSG node (for shells, offsets and thickening). Revision 5, for part two: subdivision limit surfaces near irregular points certified by the convex hulls of their control nets (curvature there is unbounded, so no curvature bound is claimed); meshes classified by their generalised winding number, never by a proposer's repair; sampled fields (densities, level sets) by their interpolant with its stated error |
| 5 | **Exact by construction** | Where a shape has no closed form, its definition states how it is constructed (a rounding's spine as the certified intersection of the two faces offset by `r`, the section an arc square to the spine: a cylinder or torus where the spine is a line or circle (a cone for a linear radius law along a line), else a canal surface; a variable radius as a law along the spine, the surface the arcs in planes square to it; a draft as lines through the neutral curve at the angle; an offset's true nearest-point distance), and the oracle computes it. The defining property is checked first as a fast test, never alone. Shells round the hollow's reflex edges by `t`, as `shell.md` defines; an offset past a certified curvature bound is, by default, the exact offset set trimmed where it meets itself (its definition, so the oracle computes the same); rounding it there instead is a separate mode the spec states; where neither is defined, UNABLE or a question, never CAN'T (the shape exists) |
| 6 | **A module per kind** | Every program finds a kind's code in a registry; the central chains go. Slots reserved now, each with a totality test as R1's, for what later stages need: the confirmation and drawing view, the print-spec rule, manufacturability rules per process, the parametric script writer, what a resize moves, and the interfaces a kind publishes for mates; and (revision 5) its analysis representation: how the kind is meshed for analysis (a cosmetic thread as its minor cylinder, text left out), with the error that makes stated |
| 7 | **Several bodies** | Solid, sheet and wire bodies. The oracle labels each step's body; cut and modify items gain a `scope`; topology per body, each body's through-holes counted by the oracle from its own shape, certified, a count it can't settle (a contact within the band) UNKNOWN and held, false holds budgeted per kind (ADR-0035); views and readers report bodies (3MF one object per body); built bodies matched to spec bodies by geometry; touching bodies' shared faces defined. ForgeIR's one-terminal-solid rule (`forge_ir/document.py:354-367`) relaxed; the gate judges each body. Bodies against components: a weldment is one part with members; mold halves are derived products of one part (item 17). Sheet and wire bodies are consumed before export (the gate takes solids, and mesh-only parts by item 22) |
| 8 | **Sketches, curves, datums, parameters** | Profile v2: lines, arcs, circles, ellipses, conics, splines through points with tangents, slots, polygons, text, offsets and projections, sketch fillets and chamfers, equation-driven curves, inner loops, several regions, construction geometry, on any plane or face; DXF and SVG sketch import. 3D curves: through points, projected, composite, intersection, helix and spiral, split lines. Datum planes (offset, angle, three points, normal to a curve, tangent, mid-plane), axes, points, coordinate systems, as items others refer to. Constrained 3D sketches (coincident, parallel, perpendicular, length, angle) for paths and weldment skeletons. Dimensions and constraints as values with provenance. A **constraint solver as a proposer** outside the trust core (Forge's own, or FreeCAD's planegcs, LGPL-2.1, used as a library as OpenCascade is); the solved geometry stored in the confirmed spec with a **branch signature** (the orientation and sign of each ambiguous constraint), shown at confirmation; the trust core checks residuals and the branch, and reports degrees of freedom from the Jacobian's rank at the solution; every dimension also measured on the built part. Named parameters and equations by path, with a component and instance namespace for stage 8; revision 5: one typed expression language (`forge_expr`) for every value and rule, with units, arithmetic, comparisons, booleans, conditionals, min and max, table and standard-series lookups, defined now so rules (4b.16) and calculators (4b.14) land as modules. References to one copy; item-list fields (what a mirror or pattern copies) |
| 9 | **Tolerances honest** | Every bounded region carries its band; every region its view tolerance, capped at an eighth of its tightest band (as stage 2's `u ≤ T/8`); approximated builds refined under the cap; fuzzy and sewing tolerances under it too. Above the cap, or a band too wide: VERIFIED EXCEPT, naming it. The tight corner limits between three single-edge roundings (stage 2, 5.2, not yet built) are built first, so today's parts keep their verdicts. Revision 5: continuity carries its own tolerances beside the positional ones, an angle for G1, a relative curvature for G2 and a relative third derivative for G3, capped per class as positions are |
| 10 | **Speed** | As 4b.0a decides; the coverage rule scales with the part (point count grows with area over `h²`) |
| 11 | **Order as a graph** | Each item names what it acts on, and may say `as_of` (the shape as it stood after an item). The canonical order stays the default, inferred and shown at confirmation. Each program evaluates the graph its own way; the generator draws orders at random |
| 12 | **Topology contracts and selection** | Each kind declares its face roles, edge roles (where two roles meet), how roles split under cuts and merge across tangent joins, and copy identity by pattern coordinates. A selection language: by role, between two items, convex or concave, tangent chain, a face's loop, made by an item, a geometric predicate. A rule selection is resolved before confirmation, stored as explicit edge or face definitions (role pairs and sample points), and shown; the compiler turns it into ForgeIR queries; the judge evaluates the rule itself on the oracle's own `as_of` shape, and the generator on its own, and checks the set both ways against that (every edge of that shape meeting the rule is in the set, every edge of the set is built), with a count and a coverage condition. What the judge can't account for stays outside, as plan 4.1 says. References tested to survive small changes of the values |
| 13 | **Pinned algorithms** | Surfaces defined by an algorithm (skinned lofts, rotation-minimising sweep frames, Coons and Gordon surfaces, unfolding by bend type) are pinned whole in the definitions: degree, parametrisation, knots, stations, worked numbers. The compiler's proposer computes them before confirmation; the verifier in the trust core and the generator each recompute them independently (an import rule keeps both away from the proposer's surface code) and compare at the build tolerance, the cap (item 9) only for what is approximated; the stored result serves only byte-identity across platforms. A resize (stage 7) re-runs them and is verified the same way. Constructions that aren't unique (N-sided fills by plate solving, energy-minimised flattening, freeform deforms) are a class of their own, **defined by properties**, with a fairness band: they end VERIFIED EXCEPT, naming them |
| 14 | **Schema versions** | A schema version on every spec; each change a declared migration proven oracle-equal across the corpus; re-confirmation rules for families. Revision 5: a corrected standard table, material table or calculator changes verdicts without changing geometry; its migration lists every changed verdict over the corpus and the kept parts, and a spec whose verdict changes is re-judged, never silently |
| 15 | **Confirmation views** | Views drawn from the compiled geometry (hidden lines from the B-rep), auxiliary views square to tilted items, sections through any plane, sketch dimensions and constraints, the parameters and their equations, configurations, each body. Revision 5: loads, supports and contacts drawn on their faces; materials; requirements with their thresholds and margins; each derived value with its inputs, the standard's clause and the margin used; subdivision cages; a study's chosen point. Stage 6's drawing reuses it |
| 16 | **Interfaces** | Parts publish interfaces by meaning (a bore, a face, a pattern of holes) in the spec, for stage 8's mates |
| 17 | **Derived products** | The registry of plan R3: each derived product (the print spec, a flat pattern and its DXF, mold halves, a cut list) one transform defined in the schema, its own checks, its own re-open check (R5); the gate judges each |
| 18 | **Classes and endings** | Fixed now, and added to the gate (plan 4.7): exact, exact by construction, and bounded within the cap lead to VERIFIED; as imported leads to VERIFIED relative to the raw faces, the import band named; annotation checked leads to VERIFIED, the GD&T listed as annotation checked; defined by properties and constrained lead to VERIFIED EXCEPT, the best attainable ending for those items; above the cap leads to VERIFIED EXCEPT and is not a best attainable ending; a mesh-only part's endings are the same, its report saying no STEP was made. R1's totality test over them. Revision 5: **a result takes the class of its weakest input** (a G2 rounding on a bounded offset is bounded at best; a refitted optimised shape stays defined by properties); and **per stated method**, the class of a requirement decided by calculation or analysis: VERIFIED only when the method's assumptions are verified on the built part (item 25) and its error is under a guaranteed bound that includes the mesh's departure from the part and the data's approximation (domain perturbation and data oscillation): for analysis, only energy-norm quantities (compliance, stored energy, and region averages by an adjoint) of steady linear elasticity and steady linear conduction, by equilibrated-flux or constitutive-relation error bounds; for a requirement stated as conformance to a standard's calculation, interval arithmetic of that calculation; in every case the worst case over the whole box of input intervals, by proven monotonicity or interval evaluation, never one input's worst end at a time; everything else, point and peak values (stress, deflection at a point, the highest temperature), transient and radiative heat, modal and buckling results, fatigue, plasticity, contact, impact and all flow, or wherever the error is only estimated or the method carries modelling error no mesh removes (turbulence models, fatigue scatter, imperfection-sensitive buckling, a beam theory standing for a solid), VERIFIED EXCEPT, naming the method, the best attainable ending for it. A requirement counts as a checked item (plan 1.3), graded against stage 9's keys. Revision 5 also: **freeform geometry whose values neither the brief nor a file determines is defined by properties at best, through any conversion** (a cage, a fitted or optimised shape, a boundary surface over proposed curves, a region turned item: ADR-0031). Stresses at singular points (re-entrant edges, point loads) are evaluated at a stated distance from them, or asked |
| 19 | **Configurations** | A configuration's identity and hash, its confirmation code, suppression inside the order graph (item 11); each configuration confirmed and judged |
| 20 | **Composites** | Items that expand into ordinary items before confirmation, shown expanded (the hole wizard, standard features, fastening features, weldment members, forming tools, and user-defined features: a person's own composites, saved and reused). Every standard table is transcribed twice from its standard, the copies diffed in a test, and the generator draws from the second copy |
| 21 | **Tolerance classes** | ISO 2768-f, m, c, v and 2768-2 H, K, L; ASME title-block decimals; ISO 286 bands on hole and shaft fields; they set item 9's caps for every kind |
| 22 | **Mesh-only parts** | What the gate and R5 require of a part with no STEP (4b.9's lattices, the implicit fallback), and the named ending it reaches |
| 23 | **The guide by family** | The spec writer's guide loaded by family of kinds, so its size and cost stay bounded as kinds are added |
| 24 | **Forge's own STEP reader** | In the trust core, for the entities Forge writes and accepts: the re-open path of every shipped STEP (today it is re-read with OpenCascade), what R11 needs for spline faces (continuity, curvature) that a mesh can't decide, and planar and analytic imports (the import pathfinder); every other imported file at 4b.8 |
| 25 | **Loads, supports and requirements** (revision 5) | One schema for what part two's calculation and analysis act on: load cases and their combinations; loads (forces, pressures, moments, torques, gravity and accelerations, temperatures and heat flows, spatial fields, flows with their inlets and outlets) with how each is applied (uniform, bearing, remote and rigid or flexible) and, where time matters, its history; initial conditions (a velocity, a drop height, a temperature); cycles, spectra and mean and alternating parts for life; the reference load for buckling; supports (fixed, pinned, sliding, elastic); contacts with friction, and environment bodies (a rigid wall, the ground, a mat); a flow's domain (far field, symmetry); each on faces chosen by item 12's selections, with its unit and provenance; requirements (stiffness, deflection, stress with its safety factor, frequency, buckling factor, life, temperature, pressure drop), each saying whether it is a point value, a peak or a region average, with thresholds and margins as confirmed values; inputs a calculator needs from a mating part (a bolt's class, the other gear) as confirmed requirement inputs, the result saying it rests on them. The trust core recomputes each applied resultant from the confirmed spec on the oracle's own faces, and checks a solver's reactions against that, never against the loads the solver's setup applied; each method's validity conditions (slenderness, thin or thick wall, notch geometry) and section properties are computed by the trust core from the built geometry, and a requirement whose method doesn't hold there is a question, unless a fallback method was confirmed with it (4b.14) |
| 26 | **Analysis and calculation registries** (revision 5) | Analysis types, solvers, meshers, calculators, optimisers and studies, and file formats (each with the reader that re-opens what it writes, R5) each a module behind a registry, as kinds are (item 6), so part two and stage 6's formats land as modules; one shared runner for external programs (a separate process each, its version recorded), designed here. Each solver's setup is written from the definitions of loads and supports separately from every other solver's, on its own mesher; the FE mesh's boundary is face-accounted both ways against the shipped STEP and the oracle at a stated band, so the analysed shape is shown to be the shipped part |
| 27 | **Versions in the hash** (revision 5) | What changes a value's meaning is part of the confirmed spec's hash: a calculator's version and its standard's edition, standard and material tables, files and tables read, stored proposals; a correction is a migration (item 14). The versions of the tools that judge (OpenCascade, meshers, solvers, external programs) are recorded in each run's evidence and in the cache key, not in the spec's hash, so a tool's update changes no confirmed spec. A derived value is re-derived only as a typed edit the person confirms (stage 7), never on its own |
| 28 | **Proposals before confirmation** (revision 5) | Everything a proposer computes that the part's shape or values rest on (solved sketches, selections, optimised shapes, a study's chosen point, recognised features, fitted cages and surfaces, repaired meshes, live-rule moves) is computed before confirmation, stored as explicit geometry or values in the confirmed spec, hash-locked with any table or file it read, and shown (item 15); nothing is re-run at the gate or on a replay. A resize (stage 7) is a new confirmation: what it re-runs (sketches re-solved, pinned algorithms, proposals) is re-run before it and shown. A stage 5 region is stored once made and never re-run. Rules are resolved before confirmation; nothing reacts after it (R3, R7, R9, R12) |
| 29 | **Material records** (revision 5) | The full record is defined here and in 4b.10: density, elastic constants, strengths, endurance and S-N data, hardness, thermal properties, service temperatures, anisotropy for printed materials (resting on a confirmed print orientation), hardening curves, hyperelastic, foam and viscoelastic models (rubber, TPU, padding), strain-rate and failure data, and fluid properties, each an interval or a curve with its source, typed optional records; 4b.10 fills density, 4b.14 the rest, with no schema change between them |

### 2.3 4b.0's exit test

- After 4b.0b: byte-identical documents, check suites and verdicts on stage
  4's counted seeds. After each of 4b.0c and d1 to d4: the same endings,
  classes the same or promoted, every change listed; the corpus specs
  migrated and proven oracle-equal.
- The new abilities on today's kinds, each with mutants and near-misses
  (any angle, every host face kind, several bodies, order with `as_of`,
  selections, depth by geometry, datums and 3D curves, sketches with
  splines and constraints, parameters, tolerance classes, configurations,
  composites), and a counted run of 10,000 interacting specs on fresh
  seeds, graded against the generalised generator; then a counted run of
  3,000 over the pathfinder kinds.
- **Pathfinders**, the simplest member of each family that touches every
  protocol method, through every program: a smooth loft of three sections;
  a variable rounding along an analytic edge; a sheet-metal edge flange
  with its flat pattern; a four-sided boundary surface, thickened; a
  weldment member along a line; a body split then shelled; a thread on a
  tilted boss; a pattern on a cylinder with depth through next; a
  configuration of two variants; a mesh-only gyroid lattice; a counterbored
  hole from the wizard; a block imported from another program's STEP, with
  a hole in it; an N-sided fill (defined by properties); a GD&T frame
  (annotation checked); a helical gear (untwisting across the axis); mold
  halves (a derived STEP product); a drafted profile reaching an offset
  event. And part two's (revision 5; 4b.0's scope grows by them, by the
  owner's direction), each touching a protocol method part two stresses:
  a constant offset of a freeform face past its curvature bound, trimmed
  (4b.3's, item 5); a G2 rounding along an analytic edge, its G3
  neighbour checked (4b.12; item 9's continuity tolerances); a
  subdivision cage of one cube with one crease (4b.13); a shaft sized by
  a calculator, its diameter a derived value, its validity conditions
  measured on the built part (4b.14; items 25, 27); a cantilever's static
  analysis against a manufactured solution, the two solvers on their own
  meshers agreeing, a requirement decided in the gate by it (4b.15; items
  18, 25, 26); a laminar pipe flow against Poiseuille's law through both
  flow solvers (4b.15); a block dropped on a rigid plane through both
  impact programs (4b.15); a two-parameter design study, and a
  topology-optimised plate shipped mesh-only (4b.16; item 28); a rule and
  a design table (4b.16); an STL imported and cut, and a hole recognised
  on an imported block replacing its faces (4b.17).
  **Each lands as a change set confined to its kind modules
  and registry entries; any edit to shared code is a protocol change
  (2.4).**
- A conformance matrix: every kind planned on this page, and every
  consumer in stages 5 to 9, against every protocol method and reserved
  slot.
- A views totality test: every item of every kind dimensioned in the
  confirmation views (item 15).
- A speed gate: median and 99th-percentile judge time per part on the
  reference machine, low enough that all of 4b's remaining runs fit the
  compute budget 4b.0a set.

### 2.4 Additivity after 4b.0

After 4b.0 a change to shared code is a protocol change: an ADR, the
conformance matrix reviewed again, every pathfinder landed again, and
every kept regression and a fixed sample of each earlier sub-stage's
counted specs replayed. The lint forbids kind names and dispatch by family
(`Category`, today at `placement.py:2240`) outside kind modules.

Revision 5: a later sub-stage that adds modes to an earlier one's modules
(4b.11 to 4b.3's roundings and shells, 4b.12 to the continuity check,
4b.18 to every family) replays that sub-stage's kept regressions and its
fixed sample of counted specs, as a change to shared code does.

### 2.5 Part two against the protocols (4b.0a, revision 5)

What each part-two sub-stage needs from 4b.0, so that it lands as kind
modules on this foundation. Every need is met by an item of 2.2; the
conformance matrix (2.3) tests each pairing with the pathfinders.

| Sub-stage | Items it rests on | What it needs from them |
|---|---|---|
| 4b.11 Freeform foundations | 3, 4, 5, 6, 9, 12, 13, 18 | Offsets of freeform hosts (3); offset solids classified with distance lower bounds (4); the offset rule, trimmed or rounded (5); new modes in 4b.3's modules, replayed (6, 2.4); bands and the G1 and G2 tolerances (9); edge roles and tangent chains on freeform faces (12); section laws and corner patches pinned (13); bounded and defined-by-properties classes, the weakest input (18) |
| 4b.12 Class-A surfacing | 8, 9, 13, 15, 18, 24 | Curves and the curvature constraint (8); the G3 tolerance (9); Coons and Gordon of degree 5 and 7, corner compatibility (13); curvature and zebra views at confirmation (15); classes (18); third derivatives read from the shipped STEP (24) |
| 4b.13 Subdivision | 4, 7, 12, 13, 14, 15, 18, 28 | Certified subdivision, control-net hulls near irregular points (4); bodies (7); roles of the faces a cage makes (12); Catmull-Clark with creases pinned (13); the cage in the schema (14); cage views (15); cage classes (18); proposed cages stored before confirmation (28) |
| 4b.14 Calculation and materials | 15, 16, 18, 20, 25, 26, 27, 29 | Derived values shown with inputs and clause (15); a mating part's data through interfaces (16); per stated method (18); tables transcribed twice (20); loads, requirements, validity measured on the built part (25); the calculator registry (26); versions in the hash (27); full material records (29) |
| 4b.15 Analysis | 6, 7, 9, 12, 18, 25, 26, 27 | Each kind's analysis representation (6); bodies and contacts (7); bands (9); loads and supports placed by selections (12); per stated method (18); resultants recomputed from the confirmed spec (25); meshers, solvers and the runner, the mesh face-accounted (26); solver versions in the evidence and the cache key (27) |
| 4b.16 Optimisation | 8, 13, 14, 18, 19, 22, 25, 26, 28 | Parameters (8); the fitter, defined by properties (13); tables hash-locked (14, 27); the weakest input (18); design tables beside configurations (19); mesh-only parts (22); requirements (25); the analysis registry (26); proposals stored, never re-run (28) |
| 4b.17 Meshes, imports, recognition | 4, 7, 8, 12, 18, 22, 24, 28 | Meshes by winding number (4); bodies (7); the face-relation solver checked as the sketch solver is (8); recognised items' roles (12); "as imported" classes (18); mesh-only parts (22); the reader widened to IGES, SAT and XT entities (24); repairs, recognition and live rules stored before confirmation (28) |
| 4b.18 Breadth | 2, 3, 6, 8, 13, 20 | Depth modes in both directions (2); patterns on freeform hosts (3); modules per family, replayed (6, 2.4); the full constraint set (8); generating motions pinned for spiral bevel and hypoid gears (13); composites and vendor tables named (20) |
| Stages 5 to 9 | 6, 15, 16, 17, 19, 28 | The reserved slots (6: views, print rules, manufacturability, scripts, resizes, analysis representation); views (15); interfaces for mates and actuators (16); derived products (17); configurations as families (19); proposals and regions (28; ADR-0031) |

---

## 3. Stages 4b.1 to 4b.10: the new kinds

Each kind arrives as modules: schema entry and written definition (with
worked numbers every program must reproduce, and the algorithms cited),
compiler module with proven-equal alternatives, ForgeIR op, after-check,
oracle module, check kinds with mutants and near-misses, the generator's
module (its own truth, a third implementation), its reserved slots, its
second-kernel entry in the capability table, and its guide entry. Each
field says its class: **exact** (a closed form), **exact by construction**,
**bounded** (with its band), or **constrained**.

### 4b.1 Solid features

| Kind or mode | Built by | Judged |
|---|---|---|
| Extrude, cut, thin versions of each: all depth modes of 4b.0 item 2; drafted (the profile offset with its events defined, UNABLE or a question past the first) | `MakePrism`, `BRepFeat_MakePrism`, `MakeDPrism`; thin by Forge's 2D offset | exact |
| Revolve: any angle, both ways, up to a face | `MakeRevol`, `BRepFeat_MakeRevol` | exact (membership in radius and height) |
| Sweep: along 3D curves; rotation-minimising frames (Wang et al. 2008, stations pinned), fixed or binormal; twist and scale laws; guide curves; variable section; a solid tool swept along a path; CAN'T where it meets itself | Forge's own sweep, pinned (item 13), handed to OpenCascade as surfaces; `MakePipeShell` an alternative only where proven equal | exact by construction |
| Loft: N sections with stated correspondence, ruled or smooth, point ends, closed, centre line, rails, end tangency | Forge's own skinning and Gordon surfaces (NURBS Book; TiGL's Apache-2.0 code a reference), pinned (item 13) | exact by construction |
| Coil, spring (closed and ground ends), helix, spiral; constant, variable and conical pitch | the helix in the surface's parameters, then swept | exact (a certified distance to the helix) for a constant pitch on a cylinder; else by construction |
| Torus, wedge, dome, rib and web from a sketch | primitives; Forge's own rib (thickened, extruded up to the host) | exact |
| Wrap, emboss, deboss | unrolled exactly on cylinders (`u = x / R`) and cones (the developed sector: slant distance, angle `θ sin α`); projected elsewhere | exact on developable faces; bounded elsewhere |
| Gears and drive elements: involute spur, internal, helical, rack, worm, with tip arc, root fillet, profile shift, backlash, undercut; bevel; involute splines (ISO 4156, DIN 5480); sprockets; timing pulleys; cams from a motion law; knurling (DIN 82) | the involute computed, not fitted through points (today's `profiles.py:575-588` fits 49 points: replaced) | exact (involutes and cams by formula, helical by screw symmetry); bevel by construction |
| Bent plate, flex (bend, twist, taper, stretch) | rebuilt exactly where it can be; else control points mapped | exact by the inverse map; the build's error capped (item 9) |

### 4b.2 Holes, threads and standard features

- A hole wizard: simple, counterbore, countersink, both, counterdrill, spot
  face, drill-point bottom, tapered and pipe holes, slotted holes, tapped
  depth apart from drill depth; at any angle; from tables: ISO 273
  clearance, DIN 974-1 and ASME B18.3 counterbores, ISO 15065 countersinks,
  ISO 2306 tap drills, ASME B1.1 (UNC, UNF), ASME B1.20.1 (NPT), ISO 228-1
  and ISO 7-1 (BSP); near-side and far-side elements (a counterbore from
  the far face). Stepped revolved cuts; exact.
- Threads, internal and external, single and multi-start: ISO metric, UN,
  BSP, trapezoidal, ACME, tapered, with run-out. Exact by screw symmetry
  for a parallel thread's profile, tapered threads and run-outs by
  construction; the pitch, diameters and hand checked exactly as
  today. Cosmetic threads as an attribute in Forge's record (their STEP and
  drawing presentation is stage 6).
- Standard features: O-ring grooves (ISO 3601), retaining-ring grooves (DIN
  471, 472), undercuts (DIN 509, DIN 76), centre holes (DIN 332), keyways
  (DIN 6885), T-slots, dovetails. Exact.

### 4b.3 Modifiers

| Kind | Built by | Judged |
|---|---|---|
| Rounding: any selection (item 12) or rule ("all outside edges"), constant, variable (a law), elliptical, chordal width, curvature continuous (G2) along edges between analytic faces (3.1), face rounding, full round, hold line; remove a rounding | `MakeFillet` where robust; Forge's own rolling ball (3.1) | exact by construction; corner blends bounded with their band |
| Chamfer: distance, two distances, distance and angle, face to face, vertex | `MakeChamfer`, `AddDA`; Forge's own vertex plane | exact |
| Shell: any body, inward or outward, several thicknesses, open faces | Forge's offset of the spec's own faces (3.1); `MakeThickSolidByJoin` where proven equal; on freeform faces, a constant offset by Forge's own freeform offset (3.1; revision 5: in part one, so 4b.5's thicken and the thickened pathfinder have it) | exact by construction (reflex edges rounded by `t`); bounded on freeform faces, the band named |
| Draft: neutral plane, parting line, step | drafted faces made directly; `DraftAngle` where proven equal | exact by construction |
| Combine, subtract, intersect (keep regions), cut by any body, indent, delete or keep a body, split by a plane or sketch | `BRepAlgoAPI_*`, `Splitter`, `CellsBuilder` | exact (the operands' models) |
| Scale (uniform, per axis), move and copy a body | `gp_Trsf`, `GTransform`; scaling a thread or a standard hole is a question (it would stop being the standard) | exact |
| Delete a face and heal (Forge's own features) | `BRepAlgoAPI_Defeaturing` | exact for Forge's own features (the shape without them); imported faces in 4b.8 |

### 4b.4 Patterns and mirrors as items

Linear, grid, circular, along a curve, at a sketch's points, from a table,
fill (inside a boundary, with a margin), chain, face patterns, varying (a
value stepping per copy), with copies skipped, of features or bodies, and
patterns of patterns; mirror of features, bodies and the whole part. Each
copy is evaluated where it lands (on a curved host or with depth by
geometry a copy is not a rigid copy); judged exactly, each copy's own
checks too.

### 4b.5 Surfacing

Extruded, revolved, swept, lofted, ruled, planar, radiate, offset,
boundary (two to four curves) and N-sided filled surfaces with tangency to
neighbours; knit, trim, untrim, extend, delete hole, replace face, cut with
a surface, mid-surface, flatten; thicken and split by a surface; surface
to solid; boundary boss and cut; deform (point, curve to curve). Built by
Forge's own constructions and `GeomFill_*`, `MakeFilling`, `GeomPlate`,
`Sewing`. Boundary surfaces of two to four curves (Coons, Gordon) are
pinned (4b.0 item 13) and exact by construction; N-sided fills by plate
solving, flattening and deforms are defined by properties (VERIFIED
EXCEPT). The continuity check kind (G0, G1, G2 across an edge) is 4b.0d1's,
decided on the shipped STEP (item 24); the rule for when a shape is a
surface item and when a stage 5 region is 4b.0a's.

### 4b.5a Fastening features for plastic parts

Mounting boss, snap hook and its groove, lip and groove, vent: composites
expanded into ordinary items before confirmation, each item judged as its
kind.

### 4b.6 Sheet metal

Base, edge, miter and swept flanges; hem (closed, open, teardrop,
rolled); jog; sketched bend; lofted bend; cross break; rip; tab and slot;
gussets; corner and bend reliefs; closed and welded corners; normal cut;
forming tools (louver, lance, dimple, bead); convert a solid to sheet
metal; unfold and fold; gauge, K-factor and bend tables (DIN 6935 and
stated tables). The flat pattern is a declared derived product (plan R3),
from Forge's own unfolder, judged against the oracle's own unfolding
(`BA = θ (R + K t)` along straight bend lines; hems, lofted bends and
forming tools by their own pinned definitions, item 13); CAN'T where the flat pattern
overlaps itself; its DXF re-opened (R5).

### 4b.7 Mold tools and weldments

- Mold: draft analysis against a pull, undercut detection by visibility
  along the pull, parting line, parting, shut-off and interlock surfaces
  (fills, 4b.5), core and cavity split, side cores and lifters, shrinkage
  scale, wall-thickness analysis. The halves are derived products of the
  one part (4b.0 item 17), judged by face accounting each, with the volume
  identity as a first test only.
- Weldments: structural members from tables (EN 10365, EN 10056, EN
  10219, stated profiles) along 3D curves; corner treatments; trim and
  extend; gussets; end caps; weld beads; sub-weldments; a cut list (a
  derived product). Several bodies; exact.

### 4b.8 Configurations and imported geometry

- Configurations: one spec, several stated variants, with items
  suppressed or values changed; each confirmed and judged; one concept
  with stage 7's families. Derived and inserted parts.
- Imported geometry: a STEP body as a spec item, its file's hash locked
  with the spec. Forge's own STEP reader (4b.0 item 24) reads the entities
  Forge accepts and refuses the rest; the oracle holds the raw file's
  faces, sewn at a band measured on the file (its stated uncertainty often
  understates its gaps), confirmed by the person and capped by item 9, with
  an UNKNOWN band there; the "as imported" band is that band; the healed body
  (`ShapeFix`, `UnifySameDomain`) must lie within it of the raw faces both
  ways, measured; the person confirms its scale and box. Derived and
  inserted parts are hash-locked the same way. Its class is "as imported": what Forge adds
  to it is exact relative to the raw faces. Move, replace, offset and
  delete faces of an imported body, the result of a deleted face defined
  by how its neighbours extend, bounded. An imported body is a different
  type from stage 5's escape-hatch solid, which never reaches the oracle
  (an architecture test).

### 4b.9 Organic, lattice and mixed parts

Smooth blends between bodies, strut lattices and triply periodic infills
(gyroid and others), field-driven thickness, mixed parts joined by a
robust mesh boolean (manifold3d), multi-material 3MF by body. Shipped as
STL and 3MF. Judged on the mesh against their closed forms (a gyroid's is
one), relative density, strut and wall sizes, envelope and connection; the
exact portion as today.

### 4b.10 Tolerances, materials and requirements

- (Tolerance classes are 4b.0 item 21; ISO 286 fits are set there, and
  stage 6 adds only the printer's compensation.)
- GD&T (ISO 1101, ASME Y14.5) on items and faces, with datums and material
  conditions. On a nominal model a flatness is zero or mesh noise, so it is
  **annotation checked**, never "measured": datums exist and are features
  that can be datums, material conditions only on features of size, basic
  dimensions match the geometry, tolerances don't conflict. (Its
  presentation and PMI: stage 6.)
- A material per body, from a density table with intervals; mass, centre
  of mass and inertia from the B-rep, cross-checked on the mesh, as
  requirements.

---

## 3.1 Forge's own geometry, where OpenCascade is weak

OpenCascade is strong at primitives, prisms, revolves, booleans between
analytic faces, transforms, sewing and exchange. It is weak at roundings
at mixed-radius corners, on spline faces or with large radii; variable
roundings; offsets and shells of freeform faces; draft beyond planes,
cylinders and cones; lofts of unlike sections; sweeps with guides; filled
patches; booleans of nearly tangent faces; it has no G2 blends, no setback
control, no sketch solver, no sheet metal, no mold tools.

Forge has what a general kernel doesn't: the spec says what every face
is. So the rule is **construct, don't modify**: where OpenCascade's
operation is weak, Forge computes the geometry from the definitions and
gives OpenCascade only what it is strong at (faces from surfaces it is
handed, sewing, booleans between well-separated faces). Each of Forge's
constructions is an alternative of its item, proven to make the same shape,
after-checked and judged like any other; OpenCascade's own operation stays
first wherever it is robust.

| Weak spot | Forge's own construction |
|---|---|
| Roundings at hard edges and corners, variable | The rolling ball from the spec's faces: the spine where the faces offset by `r` meet, an arc square to it; cylinders, cones and tori where the spine is a line or circle, canal surfaces otherwise (within the cap); corner blends as N-sided patches with G1 conditions, bounded with their band |
| G2 roundings | Curvature-matched sections (a conic alone is not G2 with its faces) along edges between analytic faces (4b.3). On freeform faces, the same sections on the spine of Forge's own offsets; G2 corner blends with setbacks as N-sided patches meeting each rounding with matched curvature, the setbacks stated (4b.11; bounded with their band) |
| Shells, offsets, thickening | Offsets of the spec's own faces (a plane stays a plane, a cylinder takes `r ± t`, a torus a torus), reflex edges rounded by `t`, then booleans. Freeform faces (a constant offset in part one, 4b.3; a law in 4b.11): the exact nearest-point offset sampled with certified error, fitted as a B-spline within the cap (item 9), past the certified curvature bound trimmed where it meets itself, or rounded there as a stated mode (item 5); OpenCascade's offset only where proven equal |
| Subdivision surfaces | The limit surface of a control cage with creases (Catmull-Clark), evaluated by Forge (OpenSubdiv as a reference), handed to OpenCascade as B-spline patches: exact where the cage is regular, bounded with their band round irregular points (4b.13) |
| Class-A surfaces | Boundary surfaces, fills and loft ends with curvature (G2) or G3 conditions to their neighbours, bridges between surfaces, fairing; built by Forge, checked by the continuity check kind and by curvature and reflection measures (4b.12) |
| Draft | Drafted faces made directly (a plane turned about its neutral line, a cylinder becomes a cone) |
| Lofts and sweeps | Forge's own skinning, Gordon surfaces and rotation-minimising sweeps (4b.0 item 13); OpenCascade makes the faces and sews |
| Nearly tangent or coincident faces | Coincident faces placed exactly from the spec; the alternatives that keep faces apart (flush, carried into air, sunk: stage 4's); fuzzy booleans only under the cap |

**The implicit kernel, a full partner.** It builds what no B-rep kernel
does well (4b.9), and it is the fallback for parts that are only printed:
where an exact rounding is UNABLE, a selective rounding made in the
implicit kernel from a distance field to the proposer's spine (only the
edges asked for), judged on the mesh against the oracle's own construction
within the mesh's band, the part shipped as STL and 3MF with the mesh-only
ending (4b.0 item 22). Until stage 6 gives parts a process, the fallback is
a question, never automatic. As the second opinion it learns the
cheap exact kinds (torus, wedge, partial revolves, tilted items,
screw-symmetric items); its roundings by opening and closing a field are a
bounded second view only (its fields are lower bounds on distance,
`forge_geom/sdf.py:3-5`, and an opening also takes walls thinner than
`2r`), never exact. Each new kind states its entry in the capability
table.

**What this can't do:** match Parasolid's robustness on arbitrary freeform
geometry imported from other programs. On the parts Forge builds, where
every face's definition is known, it can match it in exactness, and it
adds the proof.

---

## 3.2 Part two: 4b.11 to 4b.18

Revision 5. Each sub-stage is built as part one's are (kind modules behind
the protocols; a written definition with worked numbers; compiler, oracle
and check modules; the generator's own truth; mutants and near-misses;
its capability-table entry and guide entry), counted as part one's are
(section 5), and lands on the foundation part one leaves without touching
shared code (2.2 items 25 to 29 are that foundation's part for part two;
2.4). Calculation and analysis are new to Forge's trust story, so they
carry their own rule: **no computed number decides VERIFIED unless two
independent programs, each with its own setup, agree on it; the loads
they applied are checked by the trust core against the confirmed spec;
the analysed shape is shown to be the shipped part; and its error is
under a guaranteed bound.** Short of that, its requirement ends VERIFIED
EXCEPT, naming the method (item 18). Order: 4b.11 first, as 4b.12 and
4b.13 stand on its offsets; 4b.14 and 4b.17 need only part one; 4b.15
needs 4b.14; 4b.16 needs 4b.13 and 4b.15; 4b.18 needs 4b.11, 4b.12 and
4b.14, and joins each family after the family's sub-stage.

### 4b.11 Freeform foundations

| Kind or mode | Built by | Judged |
|---|---|---|
| Offset, shell and thicken of freeform faces by a law (a constant one is part one's, 4b.3) | Forge's offset (3.1, item 5) | bounded, the band named |
| G2 roundings on freeform faces, constant and variable | the spine where the offset faces meet; a curvature-matched section law pinned in the definitions | bounded (the class of its offset input) |
| Corner blends, G1 and G2, three to six sided, a setback stated per edge | Gregory patches for G1; second-order ribbon patches (Salvi and Várady's curvature-continuous transfinite patches) for G2; pinned where the construction is unique, else defined by properties; the corner data of independent neighbours checked for compatibility, incompatible data a question or CAN'T | bounded; defined by properties where not unique (VERIFIED EXCEPT, naming it) |
| Conic (rho) sections, overflow onto neighbouring faces, several radii along one chain (chordal width stays 4b.3's) | section laws in Forge's rolling ball, pinned, trimmed against the neighbours | exact by construction on analytic spines; bounded on freeform ones |
| Roundings on imported freeform edges | as above, on 4b.8's raw faces | as imported, then bounded |

### 4b.12 Class-A surfacing

| Kind or mode | Built by | Judged |
|---|---|---|
| Boundary surfaces, N-sided fills, loft and sweep ends: per edge G0, G1, G2 or G3 to a neighbour, with tangent and curvature magnitudes | Coons and Gordon surfaces with cross-boundary derivative conditions (degree 5 for G2, degree 7 for G3), the corner compatibility conditions checked (incompatible: a question or CAN'T); plate fills with curvature constraints | exact by construction where pinned; defined by properties for plate fills |
| Bridge and blend surfaces between two surfaces, G1 to G3; variable-distance offset surfaces; extend (natural, linear, curvature continuous); trim by projection along a direction | Forge's own Hermite bridges, pinned; 4b.11's offsets | exact by construction between analytic edges; bounded on freeform faces (the class of the weakest input) |
| Rebuild, fair, match edge to edge, sculpt by control points | least-squares fitting and energy fairing within a stated band | defined by properties, with a fairness band |
| Developable surfaces between two curves | a ruling search, pinned: developable within a stated band (a B-spline ruled surface is developable only approximately); no ruling found, CAN'T; several, a question | bounded |
| G3 across an edge; curvature, zebra and isophote measures; a fairness measure | the continuity check kind (4b.0d1) widened to third derivatives on the shipped STEP, with item 9's continuity tolerances; isophotes and curvature signs computed by Forge | checks, each with mutants and near-misses |

### 4b.13 Subdivision modelling

- **The cage:** an item of vertices, faces, creases with their sharpness
  and corners, edited by the spec as a modeller edits one (moving vertices,
  extruding faces, inserting edge loops, mirror symmetry). Its limit
  surface makes the part's faces: Catmull-Clark with semi-sharp creases
  (DeRose, Kass and Truong) and its boundary rules, the variant pinned in
  the definitions.
- **Evaluation:** where the cage is regular, the limit surface is bicubic
  B-spline patches handed to OpenCascade, exact. Round irregular points
  (three, five or more edges) the limit is G1 and its curvature unbounded:
  it is subdivided to a stated depth and patched there, bounded with its
  band, and certified by its control nets' convex hulls (item 4).
  OpenSubdiv (Pixar's modified Apache 2.0 licence) is the independent
  reference away from irregular points. "Regular" excludes the faces within
  a semi-sharp crease's levels of subdivision; patched regions carry their
  own stated continuity band, never item 9's G1 default. The limit surface is tested for
  self-intersection: CAN'T. The body is thickened, combined and rounded
  like any other.
- **Its class:** a cage the brief determines (its geometry cited from the
  brief or a file) is judged as above. A cage proposed by the model or by
  stage 5's agent, which the brief does not determine, is defined by
  properties (VERIFIED EXCEPT), confirmed by its views before building
  (item 28); one proposed after confirmation is confirmed again (R12).
- **The fitter:** a cage, or B-spline surfaces, fitted to a mesh, a sampled
  field or points, within a deviation band measured both ways from the
  source; defined by properties. 4b.16's optimised shapes reach B-rep by
  it, and a later scan-to-CAD reuses it.
- **T-splines:** modelling as Fusion's Form does it is served by the cage.
  Local refinement by T-junctions (T-splines proper) is a later step of
  4b.13, once 4b.0a has checked that no patent in force covers it; T-spline
  files are not exchanged (no open format).

### 4b.14 Engineering calculation and materials

- **Materials:** the full record (item 29), each value an interval with
  its source; metals by EN and ASTM designation, plastics, and printed
  materials with their anisotropy resting on a confirmed print
  orientation. Transcribed twice from cited sources and diffed, as item
  20's tables; vendor data (printed materials) named with its source and
  licence.
- **Calculators**, each pinned in the definitions: shafts (DIN 743:
  strength, fatigue, deflection, critical speed); bolted joints (VDI 2230;
  the nut and clamped parts as confirmed inputs, the joint itself verified
  at stage 8); springs (EN 13906-1 to 3: compression, extension,
  torsion); gears (ISO 6336, AGMA 2001; the mating gear as confirmed
  inputs, the pair at stage 8); bearing life (ISO 281, from the bearing's
  data); keys, splines and press fits (DIN 6892, DIN 5466, DIN 7190);
  beams, plates, pressure vessels and columns (Roark; Lamé; Euler and
  Johnson); welds (EN 1993-1-8, directional or simplified method); chains
  (ISO 606 dimensions, ISO 10823 selection); belts (ISO 5292, ISO 5295);
  section properties.
- **Validity, measured:** each calculator's conditions (slenderness, thin
  or thick wall, notch geometry) and the section properties it uses are
  computed by the trust core from the built geometry (item 25); where they
  don't hold, the requirement is a question, unless a fallback method was
  confirmed with it. Every result is the worst case over the box of its
  input intervals (proven monotonicity, or interval evaluation).
- **Two kinds of requirement:** one stated as conformance to a standard's
  calculation ("the shaft meets DIN 743 with S ≥ 1.5") can end VERIFIED,
  that calculation being what was asked; one stated as a physical outcome
  ("it will not fail") ends VERIFIED EXCEPT, naming the method (item 18).
- **Sizing:** "a shaft for 40 N·m at 1,500 rpm", "bolts to hold 5 kN": the
  calculator proposes the size from the standard series; the margins it
  sizes to are confirmed requirement values (item 25); the size enters the
  spec as a derived value shown with its inputs, the standard's clause,
  the margin and the full calculation attached (item 15), confirmed by the
  person, never silently (plan 4.1). A choice within the stated tolerance
  of a series boundary is a question. A derived value is re-derived only as
  a confirmed edit (item 27).
- **Judged:** the proposer and the verifier, from the two transcriptions,
  agree within a stated relative tolerance (iterative procedures, such as
  VDI 2230's, can't agree exactly); each reproduces its standard's worked
  examples where the standard gives them, and cited published examples
  where it doesn't; the generator draws random cases through a third
  implementation.

### 4b.15 Analysis

The analysis core planned for stage 6 is brought forward and widened:

- **Structural:** linear static, modal (natural frequencies), linear
  buckling, fatigue (from linear stress, S-N with Goodman or Gerber,
  Miner's rule), nonlinear (large deflection, plasticity) and contact.
- **Thermal:** steady and transient conduction, convection and radiation
  boundaries, thermal stress.
- **Flow:** steady incompressible internal and external flow (pressure
  drop, forces), and conjugate heat transfer.
- **Impact:** explicit dynamics for a short event (a part dropped, a body
  thrown onto a mat): OpenRadioss (AGPL, a separate program, run locally)
  and code_aster's dynamics; always VERIFIED EXCEPT, naming the method.
- **Built by two of everything,** each a separate program with its own
  setup code, written from the definitions of loads and supports apart
  from the other's (item 26; ADR-0029): gmsh → CalculiX and Netgen →
  NGSolve for linear static, modal, buckling and thermal cases; CalculiX
  and code_aster for nonlinear and contact; OpenFOAM and SU2 for flow and
  conjugate heat; OpenRadioss and code_aster for impact; scikit-fem in
  process for small checks and manufactured solutions. A result only one
  program can give is never VERIFIED. Stage 6 uses this core.
- **When a result may decide VERIFIED:** the analysed shape is shown to be
  the shipped part (item 26); the trust core recomputes the applied
  resultants from the confirmed spec on the oracle's faces and checks both
  solvers' reactions against them (item 25); the two agree within the
  band, else the part is held (R6); and the error is under a guaranteed
  bound (equilibrated-flux or constitutive-relation error bounds), for
  energy-norm quantities of steady linear elasticity and conduction only,
  the bound including the mesh's departure from the part and the data's
  approximation (item 18). An estimated error (Richardson
  extrapolation, residual estimators), or a method with modelling error no
  mesh removes (turbulence models, fatigue scatter, imperfection-sensitive
  buckling), ends VERIFIED EXCEPT, naming the method (item 18). Stresses
  at singular points are taken at a stated distance from them, or asked.
- **Verified before it counts:** each solver on cases with known answers
  (NAFEMS benchmarks, under their licence; Timoshenko's and Roark's closed
  forms; Poiseuille flow, Ghia's lid-driven cavity, the backward-facing
  step). The generator's truths, stated per analysis type: manufactured
  solutions on generated parts of any kind (an exact field imposed, its
  loads derived) for linear elasticity, conduction and laminar flow;
  closed forms only, with the weaker bound stated, for turbulent flow,
  contact, impact and fatigue, which take no arbitrary source terms. The solvers run outside the trust core (R11); equilibrium
  and energy are fast first tests there, never alone.

### 4b.16 Generative design and optimisation

- **Topology optimisation:** a design space, keep-ins (the items that must
  stay), keep-outs, loads and supports, several load cases, a mass or
  volume target; SIMP with the MMA optimiser, and level sets in the
  implicit kernel; manufacturing constraints (least member size, an
  overhang angle for printing, an extrusion or pull direction, symmetry, a
  pattern).
- **Lattice and thickness fields** (4b.9) driven by stress.
- **Shape and size optimisation** over the spec's parameters: least mass or
  deflection subject to stress, frequency and fits; design studies (sweeps
  and designed experiments) and Pareto fronts (SciPy, NLopt).
- **Rules and design tables:** conditional items and values (if, then,
  suppress) and checks, as typed expressions; design tables read from a
  spreadsheet and hash-locked with the spec. Nothing reacts after
  confirmation.
- **Before confirmation, once:** every optimisation, study and rule runs
  before confirmation; its output is stored, hash-locked, in the confirmed
  spec and shown (item 28); nothing is re-run at the gate or on a replay; a
  resize re-runs it before the resize's own confirmation (item 28).
- **Judged by its requirements, never by the optimiser's word:** an
  optimised shape ships mesh-only (item 22) or is refitted by 4b.13's
  fitter, and stays defined by properties either way (item 18); its
  requirements are verified by 4b.15's analysis on its own meshes and
  setup, not the optimiser's model. The optimiser itself is verified on
  problems with known optima (the MBB beam, Michell's cantilever).

### 4b.17 Meshes, imports and recognition

- **Mesh import:** STL, OBJ, 3MF, PLY. The oracle classifies a mesh by its
  generalised winding number (item 4), never by a repair. Repairs (holes,
  self-intersections, orientation), remeshing, decimation and smoothing
  are proposals, confirmed, defined by properties, their deviation from
  the raw mesh measured and shown (item 28). Modelling on meshes: booleans
  by manifold3d; signed distance into the implicit kernel; meshes to
  faceted B-rep. Their class is "as imported", the band measured.
- **More imports:** IGES (OpenCascade's reader, the trust core's reader
  widened to its entities); ACIS SAT up to version 7 and Parasolid x_t
  (Forge's own readers of the published formats; their single reader makes
  each import a proposal, confirmed, and each reader is tested on files
  made by other programs that come with a STEP of the same part); STEP
  AP242 PMI (OpenCascade's XCAF), each annotation confirmed; PCB boards by
  STEP from the ECAD tool, and IDF 3.0 and IDX once their specifications'
  terms are confirmed (ADR-0030); DWG, DXF and SVG into sketches, as
  proposals, confirmed (item 28); image tracing into a sketch, as a
  proposal.
- **More exports:** OBJ and glTF.
- **Feature recognition:** holes, threads, roundings, chamfers, pockets,
  bosses and patterns found on imported solids from the face adjacency
  graph and turned into spec items, their deviation from the raw faces
  bounded by the import band and shown at confirmation, then judged
  exactly; faces not recognised stay as imported.
- **Live rules** when an imported face moves: coplanar, concentric,
  tangent, symmetric and equal-radius faces kept so by a face-relation
  solver, whose result is stored, confirmed and checked by its residuals,
  as item 8's sketch solver's is.
- **Mesh files read twice:** trimesh and lib3mf read them for building;
  the trust core's own readers of STL, OBJ, PLY and 3MF read them for
  judging.
- **Truths, per format:** the generator's own geometry exported as meshes
  and IGES; for SAT, x_t, PMI, DWG and boards, files made by other programs
  with a companion STEP of the same part, the STEP as the truth.

### 4b.18 Breadth

What the professional tools have that part one's lists don't, each as
modules of its family, counted in 4b.18's run with every earlier kind:

| Family | Added | Judged |
|---|---|---|
| Sketches and curves | Control-point NURBS with weights; spline fitting within a tolerance; spline handles and the curvature (G2) constraint, and the full 2D constraint set listed (coincident, concentric, collinear, parallel, perpendicular, tangent, curvature, equal, symmetric, midpoint, fixed, pierce, dimensions); sketch mirror, patterns, trim, extend, split, blocks; more 3D sketch constraints; isoparametric, silhouette, offset-on-surface, geodesic and bridge curves; curve fairing | exact, or constrained by item 8's residual check; fitting and fairing defined by properties |
| Features | Thin revolves, sweeps and lofts; sweeps normal to a reference surface, tangent faces merged, ends aligned to faces; loft ends normal to a profile or along a direction, with weights; cage (free-form) deformation and morphing; displacement textures (implicit, mesh-only); knurls on any surface | exact by construction; deformation and morphing defined by properties; textures on the mesh within their band |
| Modifiers | Variable-angle draft, draft both ways from a parting line, draft on freeform faces; chamfer corner treatments; defeaturing (features under a size removed); machining stock (faces offset) | exact by construction; bounded on freeform faces |
| Patterns | UV, geodesic and spiral patterns on freeform faces; spacing driven by a field | each copy as it lands (4b.4) |
| Drive elements | Worm wheels, cycloidal discs, herringbone, face, hypoid, spiral bevel and non-circular gears, harmonic-drive splines, Geneva and ratchet wheels; extension, torsion, disc and wave springs; sprockets (ISO 606); V-belt pulleys and named timing-belt profiles (vendor data, its source and licence named); barrel and globoidal cams | exact by formula (involutes, cycloids, springs, cams by their law); by construction, pinned, where a generating motion or an envelope defines the surface (worm wheels, face gears, non-circular gears, globoidal cams, spiral bevel, hypoid) |
| Standards | Buttress, round, Whitworth, UNJ, MJ and NPSM threads; hydraulic ports (ISO 6149, SAE J1926); thread-forming screws for plastics and wire-thread inserts (vendor data named); drill series and inch clearance holes; Morse, SK and HSK tapers, shaft ends, wrench flats, lock-nut grooves | exact |
| Plastic and printed parts | Living hinges, heat stakes, crush ribs, energy directors, annular and torsion snaps | exact as composites (item 20); their strain per stated method (4b.14) |
| Sheet metal and tube | Flanged holes, hardware holes, more forming tools; bent tube from LRA or YBC data and die tables | exact; flat patterns as 4b.6's |
| Weldments | AISC, JIS and aluminium T-slot profiles; weld preparation (ISO 9692) | exact |
| Mold, casting and forging | Runners, gates, sprues, cooling channels, ejector pins, the mold base, EDM electrodes; machining allowance, the cast and machined states (configurations), core prints, forging flash and draft | as 4b.3's and 4b.7's classes |
| Lattices | Conformal and stochastic (Voronoi) lattices, a named cell library, the 3MF beam-lattice extension | on the mesh against their closed forms (4b.9) |
| Checks on one part | Clash between its bodies, a symmetry check, a shrinkwrap envelope | exact (booleans of the operands' models); the envelope bounded |
| Annotations | Surface texture (ISO 21920), edge conditions (ISO 13715), weld symbols (ISO 2553, AWS A2.4; drawn at stage 6) | annotation checked |


---

## 4. What stays outside V2, and why

Revision 5. Only what a constraint of technology blocks, what has no
value as asked, what the owner has deferred, or what a hard rule forbids
stays out; every other capability is placed in its stage.

- **Blocked by technology:** reading or writing the native files of
  proprietary systems (SLDPRT, F3D, NX and Creo PRT, CATPart, IPT, current
  ACIS binaries): closed formats; and Parasolid's robustness on arbitrary
  freeform geometry imported from other programs (3.1); and writing
  Parasolid x_t, whose only acceptance test, a check by Parasolid itself
  as Siemens' reference advises, needs a proprietary licence (x_t is
  read: 4b.17).
- **Of no value as asked:** lattices as exact B-rep (the industry ships
  them as meshes, as 4b.9 does); an optimised shape is made B-rep by 4b.13
  where it is wanted.
- **Deferred by the owner:** meshes from a scan turned back into B-rep
  (reverse engineering); its tools are 4b.13's and 4b.17's, so it can be
  added without rebuilding anything.
- **Forbidden by a hard rule:** "reactions" that change a confirmed part
  when an event fires (R3, R7); rules are resolved before confirmation
  (item 28).

Placed in a stage (revision 5; plan, section 8):

| Capability | Stage |
|---|---|
| G2 corner blends with setbacks, G2 on freeform faces; subdivision modelling | 4b.11, 4b.13 |
| Fatigue, nonlinear and thermal analysis; modal and buckling; flow | 4b.15 |
| JT export (ISO 14306 and Siemens' JT reference, whose terms allow writing JT): tessellations and the exact B-rep segment, re-opened (R5) by a reader written apart from the writer, from the definitions, and compared with the STEP file the same part ships with | 6 |
| DWG export, R2000, by LibreDWG (a separate program) from Forge's DXF, re-opened through LibreDWG's reader and Forge's DXF reader; its limit stated | 6 |
| Mold-flow simulation (filling, by OpenFOAM's free-surface solver: one program, so always VERIFIED EXCEPT, naming it); bend sequence and press-brake collision for sheet metal | 6 |
| CAM toolpaths (3-axis milling and drilling, then 3+2 and turning; OpenCAMLib), each checked by simulated stock removal against the part, gouge-free within the tolerance | 6 |
| Photoreal rendering (Cycles or Mitsuba, a separate program) | 6 |
| Version and data management: part numbers, lifecycle states, where-used, check-in and check-out over the revision history | 7 |
| Statistical 3D tolerance analysis (Monte Carlo over the stack, beside stage 8's worst-case) | 8 |
| Pipe, tube, cable and harness routing (paths through an assembly with fittings from tables, bend limits, clearances) | 8 |
| Dynamics (rigid bodies with mass, forces and contact), by Project Chrono and MuJoCo, compared; beside stage 8's kinematic motion; VERIFIED EXCEPT, naming the method | 8 |
| Impact of a deformable assembly (a padded, jointed body thrown onto a mat), by 4b.15's impact programs on the assembly; VERIFIED EXCEPT | 8 |
| Actuators as standard parts (servo, stepper and brushless motors, gearmotors, linear actuators, from vendor data with its source named), each joint's torque and speed from motion and dynamics checked against the actuator chosen, VERIFIED EXCEPT where it rests on dynamics | 8 |
| Assemblies beyond about 200 parts, in a lightweight mode | 8 |

Elsewhere in V2: drawings, PMI, manufacturability by process (printing,
CNC, sheet metal, molding), the print path: stage 6; editing, history and
diffs: stage 7; assemblies, standard parts, motion: stage 8 (plan,
section 8).

---

## 5. The exit test

- **Seeds never used to fix:** each counted run draws a fresh seed range,
  never used in a shakedown. A counted run that fails is fixed and run
  again in full on fresh seeds; every attempt is reported, and no run is
  stopped at its first clean stretch.
- **Interaction, defined:** two items interact when one hosts the other,
  or their solids or rounding zones come within reach of each other (the
  reach defined in the generator's definitions at 4b.0a). A "can meet"
  table, written at each sub-stage's start, says which pairs of kinds can
  meet on one part. Pairs within a family, and pairs that can share a host
  or region, appear interacting at least 50 times over 4b's counted runs
  together; every other pair that can meet, at least 10 times, its weaker
  bound stated. A covering-array stratum of large specs (eight or more
  kinds a spec), costed in ADR-0027, makes up what the other runs leave;
  within each family, three-way covering arrays of kinds, modes and hosts.
- **What a counted spec must do:** no wrong part passed, no mutant
  surviving, an impossible spec ending CAN'T. HELD and UNABLE are allowed
  within the family's budget (plan 1.3's completion and false holds), each
  filed as a bug and counted in those rates; over the budget, the run
  fails.
- **Each sub-stage:** a shakedown, fixes, then 3,000 counted specs of its
  kinds interacting with every earlier kind. After any change to shared code, every
  kept regression and a fixed sample of each earlier sub-stage replayed.
- **The whole:** 10,000 counted specs on frozen code, drawn from the
  target distribution (kind frequencies from the professional and blind
  sets): none wrong, under 1 in 3,000; the B-rep judged on every spec, the
  second kernel and the shipped files on a stated share (stage 4 used one
  in ten), each view's bound stated; per kind, separate top-up strata to
  at least 3,000 specs containing it, within the compute budget; per pair, a
  smoke test. The 1 in 10,000 of plan 1.3 is shown at stage 9, on the
  release code, where stages 5 to 8's changes are in.
- **The corpus:** the nine V1 briefs no kind made at stage 4, the gear and
  the heart, built; a professional set of at least 30 parts in the style of
  SolidWorks', Fusion's and Onshape's own tutorials, each with a reference
  solid drawn by a person and graded by deviation both ways, within a band
  per class (a loft drawn in another program differs from Forge's by more
  than the build tolerance), wrong VERIFIED counted over it; drafting and the catch rate re-measured per
  family on recorded drafts, live model calls only for the blind set.
- **Part two (revision 5):** each of 4b.11 to 4b.18 as each of part
  one's sub-stages: a shakedown, then 3,000 counted specs on fresh seeds,
  its kinds interacting with every earlier kind, part one's included. For
  calculation and analysis, an item interacts with another when it lies
  in the loaded path or the evaluated region; analysis truths are
  manufactured solutions on generated parts of every kind (an exact field
  imposed, its loads derived) for linear elasticity, conduction and
  laminar flow, so those counted cases are real parts; for turbulent flow,
  contact, impact and fatigue, closed forms only, with the weaker bound
  stated (4b.15). And more where the sub-stage computes rather
  than builds:
  - 4b.14: every calculator reproduces its standard's worked examples (or
    cited published ones), and the generator draws random cases through a
    third implementation; the proposer and the verifier agree within the
    stated tolerance on all of them.
  - 4b.15: every solver passes its benchmark cases within their bands
    before any of its runs count; counted cases are none wrong beyond
    their band, a disagreement of the two solvers held, and analysis cost
    sized to the strata 4b.0a set.
  - 4b.16: the optimiser on problems with known optima; every optimised or
    refitted part's requirements re-verified by 4b.15 on its own meshes
    and setup; none failing a stated requirement ends VERIFIED.
  - 4b.17: truths from the generator's own exported geometry; every
    recognised item matching its faces both ways within the import band;
    every import's band measured.
  - Then part two's whole: 10,000 counted specs on frozen code from the
    target distribution with part two's kinds in it, under 1 in 3,000; the
    professional set widened by at least 15 parts of part two's kinds (a
    class-A surface, a subdivision body, a sized shaft and the joint it
    rests on, an optimised bracket, an imported mesh modified), those
    whose construction isn't unique graded by their properties and
    requirements rather than by deviation from a person's solid.
- **Where it runs:** on the reference machine ADR-0027 names (the cloud
  container today; more machines are the owner's call).

### 5.1 The peak check

After part two, before stage 5 (revision 5):

- **The audit again** ([V2-stage4b-audit.md](V2-stage4b-audit.md)), made
  afresh against the same professional tools and against everything built:
  each capability still missing is either added (as a further sub-stage,
  counted the same way) or left out for one of section 4's reasons
  (blocked by technology, of no value as asked, deferred by the owner, or
  forbidden by a hard rule), the reason written there.
- **The owner's debugging campaign:** long runs on fresh seed ranges across
  every kind, every interaction and every ending, the corpus and the
  professional sets; each failure traced to its root on a copy, fixed with
  a test kept, every kept regression and each earlier sample replayed
  after each fix. It ends with a whole run on frozen code clean within its
  bound, and the owner's word.

## 6. Size and order

The largest stage of V2: most of a year of work, and months of compute at
today's speed (item 10 and 4b.0a decide how much less). 4b.0 runs in its
steps, in order. After it, the sub-stages follow their dependencies, not a
line: 4b.1 to 4b.4, 4b.8, 4b.9 and 4b.10 need only 4b.0; 4b.5 needs 4b.1;
4b.5a needs 4b.2; 4b.6 needs 4b.1; 4b.7 needs 4b.3 and 4b.5. A sub-stage
starts when everything it needs has passed.

**Part two (revision 5)** starts when part one's whole run, corpus and
professional set have passed. 4b.11 first; then 4b.12 and 4b.13 (on
4b.11), 4b.14 and 4b.17 (on part one); 4b.15 on 4b.14; 4b.16 on 4b.13 and
4b.15; 4b.18 on 4b.11, 4b.12 and 4b.14, each of its module sets after its
family. Part two is about half
as large again as part one: 4b.11's corner patches, 4b.13's irregular
points, 4b.15's solvers and 4b.16's optimisation are each a project of its
own. Then the peak check (5.1), then stage 5.

**A re-plan gate after 4b.0**: the pace and compute measured against the
budget; the owner may move a family past V2, and plan 1.3's coverage
target is restated to match. Likewise at any sub-stage stuck past its
budget. The owner's direction (10 November 2026) is to leave nothing out:
the gate measures and re-budgets; it moves nothing without the owner.

## 7. Risks

- A person confirming specs of hundreds of items: confirmation by item
  group and two drafts for large parts; the catch rate re-measured per size
  (plan 1.3).
- OpenCascade's robustness on freeform booleans: every operation
  after-checked; a refusal is an alternative or UNABLE, never a guess.
- Correlated mistakes in numeric algorithms: each pinned in the
  definitions with worked numbers and recomputed independently (item 13).
- The guide's size with about 150 kinds and modes in part one and about
  120 more in part two (cost and drafting accuracy): families loaded on
  demand (item 23).
- Judge runtime on large parts: item 10.
- *Part two (revision 5):* research-grade constructions (4b.11's N-sided
  G2 patches, 4b.13's patches round irregular points): each starts as a
  bounded class with its band stated, and is promoted only when proven;
  a construction that can't meet the cap ends VERIFIED EXCEPT, never
  VERIFIED.
- A solver converged on a wrong answer: two independent solvers, benchmark
  cases before any run counts, equilibrium and energy checks in the trust
  core (4b.15).
- A calculator wrong in the same way as its check: two transcriptions from
  the standard, diffed, and the standard's own worked examples (4b.14).
- Compute for analysis and optimisation: the budget set at 4b.0a covers
  them; analysis cases in the counted runs are sized to it, and larger
  ones run as a stated stratum.
- Scope: part two is about half as large again as part one; the re-plan
  gate measures it and the owner decides.
