# Forge V2: the plan

Status: revision 2, agreed 21 October 2026; stages 1 to 4 built, stage 4's
counted exit run passed 9 November 2026, its two live checks awaiting the
owner's key ([V2-stage4-exit.md](V2-stage4-exit.md)). Stage 4b
(coverage) added 3 November 2026, before the construction agent: the spec
brought to a professional part modeller's on a generalised substrate
(section 8; [V2-stage4b.md](V2-stage4b.md), revision 4, agreed 3 November
2026, with the release targets of section 1.3's adopted table). Revision 5
of that page (10 November 2026, the owner) adds part two, still before
stage 5: what a scope audit against the professional tools found missing
for designing and building single parts ([V2-stage4b-audit.md](V2-stage4b-audit.md)),
then a peak check; every capability once left outside V2 that technology
allows is placed in a stage (section 8). **Revision 5 is locked (10
November 2026): its scope, order, decisions (ADR-0022 to ADR-0034) and exit
tests change only by a decision record the owner approves** (the first:
ADR-0035, 13 November 2026). V1 stays
exactly as committed and described in [V1.md](V1.md): V2 is built as new
packages beside it, so V1 keeps working until V2 replaces it. The code
architecture is in [V2-architecture.md](V2-architecture.md).

Revision 2 rechecked the plan three ways:

- against every real V1 failure: about 290 distinct defects, 27 of them wrong
  parts released as PASS;
- against the current state of the art;
- through two rounds of hostile review, which found 33 holes. All are
  closed below.

The main changes:

- **Determinate geometry is compiled by code, not written by a model.** The
  model drafts the spec. Forge compiles the confirmed spec straight to
  geometry. An agent is used only for freeform regions and constructions the
  compiler can't make. This is more reliable and much cheaper.
- **You confirm what you see.** The draft is compiled in seconds and shown to
  you as a 3D part, with every item dimensioned and every word of your brief
  coloured by what it became.
- **Every face is accounted for.** Every built face must lie on a surface
  the spec asks for, and every surface the spec asks for must be built.
  Wherever the shape is exactly known, nothing missing or extra beyond the
  build's own tolerance can pass. The few places that are only bounded, such
  as where three fillets meet, must stay within stated limits, and the
  verdict says how much of the surface they cover.
- **VERIFIED means "matches a spec a person confirmed".** Unconfirmed runs get
  their own label.
- **Every run has an ending that says what happens next.** No dead ends.
- **The shipped files are the checked files:** STEP, STL, 3MF, the drawing
  and an editable parametric script.

---

## 1. What "reliable" means

### 1.1 What 100% can and can't mean

No tool, of any kind, can promise a correct part from every possible prompt.

- Some briefs contradict themselves: "a 10 mm cube with a 12 mm hole across
  it".
- Some need facts only you have.
- Some ask for what no printer or kernel can make.

A plan that promised 100% on all of these would be its own first false pass.

What V2 guarantees instead:

1. **No dead ends.** Every run ends in one of the endings below, and each one
   says what happens next.
2. **No unchecked passes, by construction.** VERIFIED is only ever said about
   items measured on the files Forge ships, against a spec a person confirmed
   (section 1.2).
3. **What can't be proved is measured.** Three things are measured separately
   and continuously (section 7):
   - the pipeline's error rate, on random specs graded against an
     independent model of their shape;
   - how often the spec writer misreads a brief;
   - how often a misread gets past you at confirmation.

**The endings:**

| Ending | Means | What you can do |
|---|---|---|
| **VERIFIED** | Matches the spec you confirmed; every item checked by the views listed on it. The verdict states how much of the surface was checked exactly and how much within bounds | Make it |
| **VERIFIED EXCEPT** | As above, except the listed items: freeform shapes checked by their constraints only, or items you accepted as unchecked | Look at the listed items |
| **BUILT TO DRAFT** | `--auto`, with no person confirming: all checks pass against a spec nobody confirmed | Confirm the spec, and it becomes VERIFIED without a rebuild |
| **HELD** | A check or two views disagree; the numbers and a picture are shown | Accept it with the evidence (VERIFIED EXCEPT), edit the spec, or report it as a Forge bug |
| **CAN'T** | The spec is contradictory or physically impossible, with the proof | Take the nearest buildable alternative offered, or edit |
| **UNABLE** | Forge couldn't build an item it should handle. This is Forge's limit, not proof it can't be made | Report it (it becomes a test), describe it differently, or resume with a larger budget |
| **WAITING** | Needs your answer, or more budget; nothing is lost | Answer or extend, and the run resumes where it stopped. Unattended runs time out to UNABLE with the question saved |

### 1.2 Hard rules

These are properties of the code, not targets. Each is enforced by how the
code is built and has its own test.

| # | Rule | Enforced by |
|---|---|---|
| R1 | Every spec item is checked, or shown as unchecked to you before building and in the report. Every item shows its verification class: exact, bounded or constrained (4.5) | The check compiler covers every field of every item kind; a test enumerates them *(stage 4b, 4b.0: the classes become exact, exact by construction, bounded, defined by properties, constrained, as imported, annotation checked, and (revision 5) per stated method for calculated and analysed requirements, each mapped to an ending, with R1's totality test over them)* |
| R2 | Checks see only the built geometry and the confirmed spec. Relations ("8 mm from the end") are measured on the built part, not read from the solver's coordinates | The check runner's interface; an import-graph test *(stage 4b revision 5: an analysed or calculated requirement is decided only from the confirmed spec's loads, supports and requirements and the built geometry: two analysis programs with their own setups, the applied resultants recomputed by the trust core from the confirmed spec, the analysed mesh face-accounted against the shipped part; V2-stage4b.md, items 18, 25, 26)* |
| R3 | The confirmed spec is locked. Only a person changes it. The one spec derived from it is the print spec, made by one declared transform from the printer profile and choices you confirmed (4.8) | The spec is hashed at confirmation, and every later stage checks the hash *(3 Nov 2026, stage 4b: to become a registry of declared derived products, each one transform defined in the schema, with its own checks and re-open check: the print spec, a flat pattern and its DXF, mold halves, a cut list (a configuration is not derived: each is confirmed); V2-stage4b.md)* |
| R4 | Repairs change how the part is built, never what it is | The construction tools have no operation that reaches the spec or the checks |
| R5 | Every shipped file is re-opened and re-checked: STEP, STL, 3MF, the drawing and the parametric script | The release gate takes the exported files, not the in-memory model *(and every declared derived product's files, stage 4b)* |
| R6 | A disagreement holds the part. A view counts as "not applicable" only by a fixed table of what each view can build, never because it failed | The release gate; the capability table |
| R7 | No silent rewrites. Forge normalises syntax only (number formats, units), and logs it. The print-spec transform is the one declared exception | No other code path rewrites meaning; a test diffs every normalisation *(the declared derived products, stage 4b, are the only other exceptions)* |
| R8 | Every model answer is validated item by item against one schema | One schema source generates the tool schema, validator, guide and renderer |
| R9 | No run loses work. A resumed run continues from its recorded model answers | A checkpoint after every step; `forge resume` |
| R10 | Every bug becomes a test before it is fixed | As in V1 |
| R11 | The decision logic lives in the trust core, which depends on no model and no CAD library. Every OpenCascade answer that decides a verdict (a radius, a pitch, a face's type) is also checked on the shipped mesh by Forge's own code, at the mesh's tolerance | ADR-0002; an import-graph test *(stage 4b: what a mesh can't decide, continuity and curvature of spline faces, is checked on the shipped STEP by Forge's own STEP reader in the trust core; revision 5: no analysis solver or optimiser is in the trust core, which recomputes calculators from a second transcription and checks solver results against the confirmed spec, as V2-stage4b.md 4b.14 and 4b.15 say)* |
| R12 | VERIFIED only for a spec a person confirmed. Confirming needs a short code that Forge shows only in its own window or a system notification, typed by the person, so no program driving a browser can confirm by itself | The release gate; the confirmation code |

### 1.3 The numbers

Measured on sets Forge was never tuned on (section 7). Every rate is reported
with its 95% upper bound and its denominator.

| Measure | What it is | Release target |
|---|---|---|
| **Wrong but VERIFIED** | VERIFIED parts that are wrong, graded against keys written before the run | none observed in 300 or more VERIFIED parts: under 1 in 100 |
| **Pipeline errors** | Random specs where the built part differs from the generator's own model but passed | none in 10,000 or more, weighted like real specs: under 1 in 3,000 overall. Each combination of item kinds reports its own bound |
| **Spec drafting** | Items right before you touch them; parts needing no edit at all | 98% or more of items; 60% or more of parts (98% per item leaves about 67% of 20-item parts with no edit) |
| **Catch rate** | Deliberately planted misreads that people catch at confirmation | 98% or more, shown on at least 150 planted misreads |
| **Completion** | In-scope confirmed specs that end VERIFIED with no further input | 98% or more; every miss becomes a fix |
| **False holds** | HELD or UNABLE on a part whose spec was buildable | 2% or less |
| **Honest endings** | Endings other than VERIFIED that name the item, the reason and the next step | every one |
| **Cost and time** | Total per part, both drafts included, plus your minutes | simple parts: median under $0.25, under 3 minutes of machine time, under 2 minutes of yours |
| **Coverage** | Kinds of item Forge can build and check (4.4) | everything V1 builds, plus 4.4's additions, and stage 4b's professional part-modelling set ([V2-stage4b.md](V2-stage4b.md)) |

**Adopted with stage 4b (3 November 2026): V2's release targets, in place of the table above** (stage 4's own exit is section 8's row 4). Stage
4b's parts are larger (often over 60 items), so the targets above no longer
add up: for `n` items, staying under 1 in 100 needs drafted-wrong times
missed at or under `1 / (100 n)` per item, which for 100 items is a 99.5%
catch rate, shown by about 600 planted misreads, not 150. So the targets
are set per size, and set strictest where proof costs only computer time
(random specs: as many as it takes), while those that need people
confirming planted misreads are set where people's time can show them,
and can be raised later by adding trials:

| Measure | Proposed |
|---|---|
| **Wrong but VERIFIED** | None in 300 or more never-tuned parts, over VERIFIED and VERIFIED EXCEPT on their checked items (a requirement decided per stated method is a checked item, graded against the keys: stage 4b revision 5): under 1 in 100; reported per size tier (20 items or fewer, 21 to 60, over 60, at least 100 parts in the largest) and per family as a smoke test; none in 30 or more assemblies |
| **Catch rate** | Per tier (20 items or fewer, 21 to 60, 61 to 150, over 150), the target from the per-item rule: 98%, 99.2%, 99.5%, and for over 150 the rule's figure for the tier's largest part, each shown by enough planted misreads (150, 360, 600, and 3 over the miss rate for the largest), edits and assemblies included, and (stage 4b revision 5) loads, supports, materials, requirements and derived values among the planted misreads; two drafts always for large parts, confirmation by item group. The trials are dedicated: the person confirming knows a part may hold misreads (none to three, at random, some parts none), but not which items; a weaker design than planting at a low rate in ordinary use, which continues after release and is reported as it accumulates. People's time, estimated: about 8 h, 40 h and 135 h of confirmations for the first three tiers (about 1.5 misreads a part), 350 to 500 h writing keys for the never-tuned parts (2 to 3 h each over 60 items), 60 h for 4b's reference solids, across you and at least two others; model spend for drafting the trial parts, about $2,000 to $3,000 at the cost targets below. Where a tier's trials fall short, the report states the bound its own counts show (none wrong in 100 parts of a tier bounds it at 3 in 100), never the target |
| **Pipeline errors** | Under 1 in 10,000 overall (none wrong in 30,000 counted specs on frozen release code, drawn from the target distribution of kind frequencies from the professional and blind sets, every view judged on every spec, the print path, drawings, scripts and resizes included); per kind under 1 in 1,000 (none wrong in at least 3,000 specs containing it, in separate top-up strata); pairs a smoke test; random assemblies under 1 in 1,000 (none wrong in at least 3,000) |
| **Spec drafting** | 98% or more of items (99% in the largest tier); edits per 100 items in place of "parts needing no edit" |
| **Completion** | 98% or more of in-scope confirmed specs end with their best attainable ending (VERIFIED, or VERIFIED EXCEPT naming only items classed constrained, defined by properties, or per stated method where that method can't reach VERIFIED, before the build); per family 95%, measured on random specs |
| **False holds** | 2% or less overall; 5% per family, measured on random specs |
| **Cost and time** | On a named reference machine. 20 items or fewer: as above; 21 to 60: median under $1, 10 minutes of machine time, 10 of yours; over 60: under $3, 30 minutes, 20 of yours; assemblies the sum of their parts plus a stated overhead |
| **Coverage** | Every kind and mode of V2-stage4b.md through its run; on a blind professional set written by others (at least 50 parts, 10 assemblies), 95% or more expressible by kinds alone (no region, no escape hatch), 90% or more ending with their best attainable ending |

**In scope** is defined in advance: the spec is valid against the schema and
passes the spec checks.

**Where the 1-in-100 has to come from.** A wrong VERIFIED part needs either
a pipeline error, or a misread that is both drafted and missed at
confirmation. For a 20-item part, under 1 in 100 needs "drafted wrong" times
"missed by you" to be at most 1 in 2,000 per item. With 98% right drafting,
people must catch 97.5% of the rest. That is why confirmation gets so much
design effort (4.2), and why its catch rate is measured on its own.

---

## 2. What actually went wrong in V1, and what stops it in V2

The audit grouped V1's defects into 14 causes. Each cause has a V2 mechanism
with its own test.

| Cause | V1 | What happened | What stops it in V2 |
|---|---|---|---|
| **A. Brief misread by a wording rule** | 32 | Rules missed phrasings or broke each other ("each a 5.5 mm hole" counted once; "no taller than 50" became "exactly 50") | No wording rules. The model drafts a typed spec citing your words; code checks every number is used; a second draft is compared by geometry; you confirm the 3D part (4.1, 4.2) |
| **B. Claim never made** | 22 | The brief said it, nothing checked it: a sphere built as a drum, a hollow cube built solid, the strip's ends | R1, and face accounting: a face that isn't in the spec, or a spec surface that isn't built, fails (4.5) |
| **C. Check read the design's own numbers** | 16 | `parameter:` claims passed whatever was built: the lug, a spacer's spacing | R2 |
| **D. Check too strict or mis-measured** | 24 | Ray heuristics, wall lines through dividers, tolerances finer than the instrument | Exact B-rep measurement; every check kind tested on correct parts and near-misses (4.6) |
| **E. Designer construction errors** | 26 | Wrong plane, wrong end, wrong count, blends nobody asked for | Determinate items are compiled by code (4.3); face accounting |
| **F. Kernel limits and bugs** | 22 | Shapes it couldn't make, unsound bounds, a cache serving the wrong geometry | Exact kernel; an after-check on every operation; a second kernel; property tests; a cache that copies, keyed by kernel version (4.4) |
| **G. Repairs that changed the part** | 20 | Repairs hollowed a cube, removed a counterbore, added a riser to satisfy wrong claims | R3, R4. A conflict with the spec comes to you |
| **H. Last look** | 7 | Called square ends round; saw a fault and wrote no fix | Advisory only; runs only on freeform or unchecked items; its hold has a one-click "seen" |
| **I. Orchestration, provider, budget** | ~55 | Whole-reply timeouts, 65-minute runs, retries that taught nothing | Streamed calls with idle timeouts; R9; far fewer model calls; effort set per role |
| **J. Output files** | 6 | STL holes 0.5 mm small from coarse meshing; a skin across the dome's opening | R5; mesh tolerance set from the spec's tolerances |
| **K. Units, angles, frames** | 14 | `cos(30)` in radians, "1/2 inch" read as 2 inches, offsets along the wrong normal | Units mandatory on every value, angles included; conversions shown ("12.7 mm (½ in)"); one frame, drawn in the preview |
| **L. Names matched across model calls** | 17 | Duplicate ids dropped claims; two calls had to invent the same name | Forge owns every id; the two drafts are aligned and compared as geometry, not by matching names |
| **M. All-or-nothing answer rules** | 17 | One bad entry rejected a whole answer; one fault reported per round | R8; items accepted one by one; all problems in one round; counts are their own type, not a quantity with a unit |
| **N. Forge's own rewrites** | 13 | The settle step re-aimed correct holes and rebuilt a cup as a box | R7. The placement solver is rewritten to solve only what is stated; V1's tests are ported, its code is not |

**Acceptance tests from this audit (stage 4):** V1's 27 false passes must all
be caught twice. First, replayed as their wrong geometry against a correct
spec. Second, end to end from their original briefs through the spec writer,
because most of them began as misreads.

---

## 3. The decisions

**Decided (20 Oct):**

- **Scope:** single parts first. The core is built for assemblies from day
  one, and assemblies follow without a rewrite.
- **Geometry:** both kernels. OpenCascade builds the part. V1's implicit
  kernel is a second, independent build where it can build the shape, and
  handles organic shapes OpenCascade can't.
- **You confirm the spec** before anything is released as VERIFIED.
- **The designer: the most reliable method.** Revision 2's answer, in order:
  1. **Compile.** Every item whose geometry the spec fixes is built by
     deterministic code. No model.
  2. **Construct.** A model agent with typed tools handles freeform regions
     and constructions the compiler couldn't make.
  3. **Escape hatch.** A short build123d program in a locked-down container,
     for shapes the spec can describe but the operation set can't build.

  Whichever path builds an item, the same checks judge it.

**Carried over:**

- English only.
- Claude Sonnet 5 as the default model, with a provider-neutral layer. The
  second draft can use a different configured model, so the two drafts'
  mistakes are less alike; that is measured in stage 1 before it is
  recommended.
- No secret ever enters a run's records or the repository. The key comes from
  `ANTHROPIC_API_KEY`.

---

## 4. The architecture

```
 brief ─► words numbered
   │
   ▼
 ① Spec writer (model): draft A  ·  draft B (independent, when used)
   │
   ▼
 ② Spec checks (code): schema · units · every number and sentence cited
   · placement solved from stated relations only · contradictions · fit
   · print orientation · draft A vs B compared as geometry
   │
   ▼
 ③ You confirm ◄── 3D preview of the compiled draft · every item dimensioned
   │               · your brief coloured by what each word became
   │               · assumptions and A/B differences first · questions in one round
   ▼ confirmed, locked spec (hash)
   ├──────────────────────────────► ④ Check compiler (code)
   │                                   item checks · relation checks
   ▼                                   · face accounting · topology counts
 ⑤ Build
     compile (code) ─► construct (agent, only if needed) ─► escape hatch
     every operation after-checked
   │
   ▼
 ⑥ Export: nominal STEP · print STL/3MF compensated for your printer
     · drawing · parametric script
   │
   ▼
 ⑦ Verify every view: B-rep · second kernel · each shipped file
     · fresh probe sample drawn now
   │
   ▼
 ⑧ Release gate (code) ─► one of the endings in 1.1, with the active views listed
```

### 4.1 The PartSpec: the contract

*Stage 4b (3 November 2026) extends this contract: frames and directions, depth by geometry, any face as a host, several bodies, sketches with constraints and parameters, an order graph with `as_of`, selections of edges and faces resolved before confirmation and checked both ways, configurations, composites, schema versions (V2-stage4b.md, section 2). Where this section says the kernel and the checks use the same loft surface, stage 4b's item 13 replaces it: the algorithm is pinned and recomputed independently.*

A **PartSpec** is a typed description of what the part is, not how to build
it. Everything downstream works from it.

- **Frame:** up, origin, and what "length", "from one end", "seen from above"
  and "front" mean for this part.
- **Body:** plate, block, rod, tube, or an outline (lines, arcs, splines)
  extruded, revolved, swept or lofted.
  - Splines and loft sections are stored as explicit control points.
  - Forge computes each loft's surface itself and hands it to OpenCascade, so
    the kernel and the checks use exactly the same surface.
  - Sweeps follow one stated frame rule (rotation-minimising).
- **Items:**
  - holes: through or blind, counterbore, countersink, thread with pitch and
    hand;
  - slots, pockets, bosses, posts, ribs, tabs and lugs, end shapes;
  - fillets and chamfers on edges named by meaning, limited to edges the
    checks can compute from the spec: the edges of a named item's own
    shape, and where two named items meet. Anything else becomes a
    question;
  - patterns, mirror, shells, bends;
  - text in a pinned font, laid out by Forge;
  - standard features from tables: clearance and tapped holes, heat-set
    insert bores, nut traps, bearing seats.
- **Freeform regions:** shapes given by constraints rather than sizes, the
  only places the agent designs. Fixed items always win over a region: a hole
  the spec places through a grip is cut through it.
- **Placement by relation:** "8 mm from the end on the centreline", "in each
  inside corner". The placement solver solves only the relations stated. It
  never guesses an axis or turns a feature.
- **Tolerances:**
  - Each size can carry its own tolerance; the rest use a general class
    (ISO 2768-m by default), shown in the preview.
  - Geometric tolerances (flatness, perpendicularity, position) can be
    given too.
  - Forge builds every size at its nominal value, so the checks use each
    view's own build tolerance. Design tolerances go to the drawing, the fits
    and the printer.
- **Requirements:** material, mass, loads and margins, fits, printer.
- **Print orientation:** chosen by code (largest flat face down, then least
  overhang), shown in the preview, changeable.
- **Interfaces:** faces and holes other parts attach to, for assemblies.
- **Not modelled:** a required list of what the brief says that the part
  won't have. A brief that says the lid "snaps on" but asks for no clip says
  so here, instead of disappearing.

**Every value carries its provenance:**

- from the brief, citing the numbered words it came from;
- from a standard table, such as an M4 clearance hole;
- derived, from a formula shown to you;
- **assumed**, with a reason. Assumptions are shown first.

Counts are their own type with no unit. That ends V1's failures over a count
whose unit was refused as "" and then again as "turns".

**Every number and sentence in the brief is accounted for.**

- Forge numbers the brief's words before the model sees it. The model cites
  word numbers; it never writes character offsets.
- Code checks that each value really comes from its cited words, by number,
  fraction, unit conversion or the formula shown. "1 1/2 in" must be 38.1 mm.
- Code flags any word containing a digit, and any word from a short list
  (one to twenty, dozen, pair, both, half, single, double, twice), that no
  value cites.
- It also flags any sentence that no item, "not modelled" entry or "says
  nothing about the shape" entry cites.

This doesn't decide what anything means. It only stops anything from
quietly disappearing, which was V1's commonest false pass. At worst, a false
flag costs one question.

In `--auto`, the rule is stricter: every word that isn't a common function
word must be cited or listed as not modelled. The function words are a short
fixed list ("a", "the", "of", "with" and the like). Otherwise Forge asks.

### 4.2 Confirming the spec

Confirmation is where a misread is caught, so it gets the most design effort.

**What you see, in this order:**

1. **Assumptions and questions,** all in one round. Questions are multiple
   choice where possible, and each answer is applied by code as a typed edit,
   so no redrafting is needed.
2. **Differences between the two drafts,** when a second draft was made.
   - Both drafts are compiled, aligned and compared as geometry.
   - Two ways of saying the same part, or two choices of origin, don't raise
     false alarms.
   - A real difference can't hide behind matching names.
3. **The 3D part,** compiled from the draft in seconds, at no cost.
4. **Views that dimension every item at least once:** top, front and side,
   and a section through any feature those views don't show. Derived overall
   sizes are labelled (a torus 40 mm at the centre line is 48 mm overall).
5. **Your brief, each word coloured by the item it fed,** with uncited words
   marked.
6. **The fixed-wording list,** written by Forge's renderer, not by the model:
   "4 × Ø2.8 mm hole, 12 mm deep, centred on the top of each corner post".

You approve, or correct items in the live page or the CLI. Each correction
re-runs the spec checks and the preview.

**Why two drafts, and when.**

- **Published evidence:** items two independent extractions agree on were
  right about 94% of the time; items they disagreed on only 41–50%.
  Disagreement is a good misread detector. Agreement is not proof: two drafts
  from one model share blind spots.
- **Proposed default:** the second draft runs in parallel when the first has
  assumptions, the brief is long, or `--auto` is on.
- **Stage 1 measures it:** whether drafting it every time catches misreads
  that people miss, and whether a different model drafts it better. The
  default is set from those results.

**`--auto`.** With no person confirming, the best ending is BUILT TO
DRAFT, never VERIFIED (R12). `--auto` still stops to ask when there are
assumptions, uncited words, "not modelled" entries or draft differences.

Confirming needs the code that Forge shows only in its own window. A person
reads it and types it in. In the CLI, "its own window" is the terminal Forge
runs in, opened by name rather than through standard input and output, so a
program that pipes them never sees the code (stage 1). A program that runs
Forge inside a pseudo-terminal of its own holds that terminal too; a system
notification tells it apart (stage 9).

**Questions.** Published work found almost all remaining failures came from
asking too few questions, not too many. Forge asks whenever an answer would
change the shape.

### 4.3 Building: compile first, then construct

*Stage 4b: "order can't change the shape" holds for the default order; an item's `as_of` makes a stated order part of the spec (V2-stage4b.md, item 11).*

**The compiler (deterministic).** For every item the spec fixes, the
compiler writes the ForgeIR v2 construction: no model, the same output every
time.

- **The schema defines what each combination means, so order can't change
  the shape.** "Walls 2 mm everywhere" with "outside edges rounded 5 mm" is a
  shell offset from the finished outside, so its inside corners are rounded
  3 mm. The compiler finds a construction that makes that shape. It does not
  pick an order and accept whatever comes out. Shelling a sharp box and then
  filleting it would leave a 0.76 mm wall at the corners.
- **Alternative constructions per item,** tried in a fixed order when the
  kernel rejects one. Each alternative is proven to make the same shape as
  the first, with nothing excluded, in its own tests. When an alternative
  can't make the same shape, the difference becomes a question.
- **The compiler may never change a size to make something work.**

**The construction agent (model, only when needed)** handles freeform
regions, and items whose every alternative the kernel rejected.

- **Tools:**
  - `add_step`, `change_step`, `remove_step`: construction only
  - `compile`
  - `measure`: exact misses, such as "hole `post_pilot` #3: expected 12 mm
    deep, found through"
  - `query_geometry`
  - `render`
- **Budget and stop rules:** the same failure twice means change approach.
  Still stuck means the item ends UNABLE, by name.
- **Feedback is the checks' exact misses.** Research found images in the
  loop added nothing measurable, and that a model correcting itself without
  outside feedback gets worse. `render` is a secondary aid.
- **The release gate draws a fresh probe sample after construction,** so the
  agent can't fit the checks it was shown and miss the rest.

**The escape hatch** is for shapes the spec can describe but the operation
set can't build. A shape the spec can't describe is never built unchecked; it
becomes a freeform region with constraints, or UNABLE.

- It runs in Docker:
  - no network, read-only, `/tmp` in memory;
  - all capabilities dropped, `no-new-privileges`, a non-root user;
  - time, memory and process limits.
- The solid it returns is parsed in a separate process.
- Without Docker it is unavailable, and the report says so.

### 4.4 Kernels and views

**OpenCascade builds the part** (`forge_occ` calls it through OCP directly, 7.9.3 through stage 4; 8.0.1 from stage 4b.0a′, ADR-0022): exact faces and
edges, real fillets, sweeps, lofts and shells, and STEP for Fusion, FreeCAD
and SolidWorks.

- **Licences:** build123d is Apache-2.0; OpenCascade is LGPL-2.1 with the
  OCCT exception.
- **Windows:** it has wheels for Python 3.12.

**It isn't trusted blindly.** Testing found real traps:

| Trap | What `forge_occ` does |
|---|---|
| A shell can silently do nothing and still report a valid solid | Every operation is after-checked: volume and faces must change as that operation should |
| build123d never checks OpenCascade's boolean error flags | The flags are read |
| Meshes are cached, so a second export ignores the new tolerance | The mesh cache is cleared before every export |
| Solids can become invalid partway through a build | The solid is validated after every step |

**The views of every part:**

| View | Built from | Catches |
|---|---|---|
| **B-rep** | the OpenCascade solid | sizes, positions, axes, counts, radii, thread pitch, measured exactly |
| **Second kernel** | the same construction, built by V1's implicit kernel | OpenCascade bugs and translation bugs |
| **Shipped files** | the exported STEP, STL and 3MF, re-opened. The STL and 3MF are probed by Forge's own NumPy code, not OpenCascade | export faults: coarse holes, skins, broken meshes, wrong units |

The oracle's checks (4.5) run on every view that can answer them.

**What the second kernel can and can't check, fixed in advance.** V1's
implicit kernel builds boxes, cylinders, extrusions, revolves, holes,
patterns and bends to within tight tolerances. It doesn't build true edge
fillets, and its lofts, sweeps and shells are approximations. A fixed
capability table records, per operation, whether the second kernel's answer
is exact, bounded by a stated tolerance, or not applicable. "Not applicable"
comes only from that table. If a view that should work fails, the part is
held (R6). Every verdict lists the views that were active for each item.

**Choosing faces and edges by meaning.** References are stored as queries:

- **what made it:** the feature and its role ("side wall of `post_pilot`");
- **a geometric test,** to tell split pieces apart;
- **a match condition:** an expected count range, plus a coverage condition
  such as "these arcs together make the whole root circle". A boss's root
  edge cut by a slot is then still found, as two arcs.

Forge resolves each through OpenCascade's history of every operation. A match
outside the condition is a hard error, never "take the first one". This
extends ADR-0003 to splits, which it left open.

**The cache:**

- each entry stores the solid together with its history;
- every hit is copied, so no two builds share a mutable shape;
- the key includes the OpenCascade version and fuzzy tolerance.

This prevents V1's "the cache served the wrong geometry".

**Coverage, each with build and check tests:**

- everything V1 builds (32 feature kinds), now exact: sketches with lines,
  arcs and splines; extrude, revolve, sweep, pipe, coil, loft; holes with
  counterbores; patterns, mirror, shells, bends, gears
- new: fillets and chamfers on edges chosen by meaning
- new: countersinks; threads with pitch and hand; fits, inserts, nut traps
  and bearing seats from standard tables
- new: slots, pockets, bosses and ribs as named items
- new: text in a pinned font, draft angles
- kept from the implicit kernel: smooth organic blends, lattices and infill.

*Coverage still to come* (3 November 2026). The kernel builds every kind
above (stage 3); the spec, which the compiler builds from and the oracle
checks, reached 20 kinds at stage 4: block, cylinder, tube, cone, sphere,
extrusion, revolution, hole, pocket, slot, boss, post, rib, tab, shell,
fillet, chamfer, thread, text and region. Nine of V1's 92 validation briefs
ask for what none of them makes. Stage 4b makes a spec kind of every other
kind the kernel builds, and adds the abilities they need, so that the
construction agent is left only the shapes no kind can say: a freeform
region, or a determinate item every construction of which the kernel
refused. Each new kind is added as the twenty were: checked exactly where
its shape has a closed form or it is exact by construction (its stated
construction computed by the oracle), else bounded or defined by properties, and never
left to the agent's constraints alone. Stage 4b first generalises the
geometric substrate the twenty stand on (frames on every face, depth by
geometry, any face a host, certified solids, several bodies, sketches with
constraints), so that every later kind is added without touching shared
code ([V2-stage4b.md](V2-stage4b.md)).

**Parts that mix the two kernels.** A part with an implicit-kernel region is
built as a mesh:

- the OpenCascade portion is meshed at the export tolerance;
- it is joined to the region with a robust mesh boolean (manifold3d);
- it ships as STL and 3MF only, with fewer views, and the report says so.

### 4.5 The oracle: checking the whole shape

*Stage 4b: the oracle's solids become a protocol of certified methods, with B-spline and screw-symmetric solids, exactness by construction, and the classes R1's note lists (V2-stage4b.md, items 4, 5, 9, 13); the classes in the table below are superseded kind by kind by V2-stage4b.md.*

The oracle is computed from the confirmed spec alone. It shares no
construction code with the compiler.

**Every region of the surface has a verification class,** shown in the
preview and the report. The verdict gives the share of the surface in each.

| Class | Regions | How it is checked |
|---|---|---|
| **Exact** | extrusions and revolves of lines and arcs, holes, slots, pockets, bosses, patterns, mirror, bends; lofts, splines and text, because Forge computes their surfaces itself; fillets and chamfers along their length where the result is a known surface (between flat faces, or a flat face and a cylinder) | every point and every surface known exactly |
| **Bounded** | where fillets meet at a corner or run out into a face; other fillets; sweeps between their stations; shells of curved faces; threads | exact at defining sections and sizes. Between them the built part must lie between an inner and an outer limit (a convex fillet lies between its chamfer and the sharp corner), and the B-rep check measures the radius |
| **Constrained** | freeform regions | envelope; how much of it is filled (section areas and volume fraction, so a small blob fails); thinnest wall; smooth joins; attachment faces. The ending says "freeform: constraints only" |

**The checks:**

- **Item checks:** every field of every item, measured on the built geometry.
  Examples: diameter, depth, axis, thread pitch, radius.
- **Relation checks:** every stated relation, measured on the built part.
  Example: "the axis of `post_pilot` #3 is 8 mm from the built `end_min`
  face". These don't use the placement solver's coordinates, so a solver
  mistake that the compiler copies is still caught, and so is a hole measured
  from the wrong end.
- **Face accounting, both ways.** This is the check that makes "exactly
  what was asked" testable.
  - Forge samples every built face, and every triangle of the shipped
    meshes. Each sample must lie on a surface the spec asks for.
  - It also samples every spec surface, and each must be built.
  - The tolerance is the view's own build tolerance: about 0.001 mm on the
    B-rep, the export deviation on meshes. It is not the design tolerance,
    so an unasked 0.3 mm chamfer fails.
  - An extra pin, a missing counterbore, a 1 mm sealed void or a
    zero-thickness skin fails on exact regions.
- **Topology counts:** solids, inner voids, through-holes, and surfaces by
  type. Faces are counted after merging faces that lie on the same surface,
  so the way OpenCascade happens to split faces doesn't matter.
- **Volume,** with a tolerance per view:
  - tight on the B-rep;
  - deflection × area on meshes;
  - the enclosure's width on the implicit kernel.

  V1's percentage band let a missing counterbore through.
- **Fresh probe sample:** test points inside and outside every item, drawn
  after the build, so nothing could have been fitted to them. The seed is
  recorded in the run.

Example: V1's lug passed 34 checks while square. In V2 the spec says the end
is a semicircle of radius 12 mm, which is exact class. The square corners'
faces lie on no spec surface, and the semicircle's surface isn't built. The
lug fails on the first sample.

### 4.6 Checks that are themselves tested

*Stage 4b: planted-misread counts are per size tier as section 1.3 sets; the runs' throughput follows the compute budget stage 4b.0a sets.*

**Mutants and near-misses**, for every check kind:

- **Mutants:** Forge damages a correct part's geometry directly. A hole is
  moved 1 mm, an end made square, one hole removed, a void hidden inside.
  **Every mutant beyond tolerance must be rejected: 100%.**
- **Near-misses:** changes inside tolerance must pass, so good parts aren't
  held (V1's cause D).
- **Before the compiler exists:** stage 2 uses hand-made reference parts for
  each check kind.

**Random specs (property tests).** A generator makes random specs, and
Forge compiles, builds, verifies and exports each one, with no model and no
cost.

- **Its own model of the shape.** The generator has a minimal shape model of
  its own, in `forge_eval`, sharing no code with the compiler or the oracle.
- **Meanings written down.** What each field means ("8 mm from the end" is
  to the hole's centre) is written down per item kind and approved by you.
  The generator, the compiler and the oracle are each coded from that text.
  Independently written programs still fail together more often than chance,
  so the shared definitions are the one thing they have in common, and they
  are readable.
- **Hard cases on purpose.** Items are generated overlapping and
  interacting: a counterbore breaking into a pocket, a fillet across a hole,
  a pattern running off an edge. Some are impossible on purpose, and their
  expected ending is CAN'T.
- **Graded against the generator's model** by surface deviation, both ways,
  not by the views agreeing with each other.
- **Mutants:** every correct build must pass, and every mutant must fail.
- **Weighting and reporting:** specs are weighted like real ones, for the
  overall bound, and each combination of item kinds reports its own bound,
  so a number earned on easy specs isn't claimed for hard ones.
- **Throughput:** the nightly count is set from the measured time per spec,
  across parallel processes. The target is at least 10,000 a week.

**Mutation testing of Forge's own code** (mutmut, in WSL; cargo-mutants
for Forge's compiled crate, stage 4b ADR-0024): run on the trust core with
its unit tests. A surviving code mutant is a missing test.

### 4.7 The release gate

VERIFIED needs all of these:

1. the spec was confirmed by a person (R12);
2. every item's checks, relation checks, face accounting, topology counts,
   volume and fresh probes pass on every view the capability table says can
   answer. The nominal files are checked against the confirmed spec, and the
   print files against the print spec, each group on its own (4.8);
3. every shipped file passes (R5), including the drawing, whose dimensions
   are measured from the geometry, and the parametric script, which is re-run
   and must rebuild the same part;
4. each body of the part is a valid, watertight solid, each configuration judged (one solid until stage 4b, item 7); each item's verification class leads to its ending as V2-stage4b.md's item 18 fixes;
5. printability in the chosen orientation:
   - thinnest wall at least the nozzle's limit, measured by rays. Thin
     features you asked for, such as a living hinge, are explicit
     requirements and exempt;
   - it fits the bed;
   - overhangs are reported. They hold the part only if the brief forbids
     supports;
6. strength, where a load is given: V1's analytical checks *(stage 4b revision 5: requirements decided per stated method by 4b.14's calculators and 4b.15's analysis, V2-stage4b.md item 18)*.

The visual review is advisory. It runs only on freeform or unchecked items.
It can hold a part with what it saw, and you clear that hold with one click.

### 4.8 Accurate in the real world

A part that matches the spec on screen can still print wrong. V1 found that
printed holes come out small.

- **Two sets of files.**
  - The **nominal STEP** is the part exactly as specified, for any CAD
    program or machine shop.
  - The **print STL and 3MF** are compensated for your printer.
- **How compensation works.** It is one transform, defined in the schema and
  tested on its own.
  - It turns the confirmed spec into a print spec, using your printer
    profile and the print choices you confirmed with the spec. Example: a
    hole on its side given a teardrop top, so it doesn't sag.
  - The profile's version is part of what you confirm.
  - The print spec is compiled and checked like any other.
  - The two groups of files are verified separately: nominal against the
    confirmed spec, print against the print spec. They are never compared
    with each other, since they differ on purpose.
- **Calibration coupon.** Forge makes a small test print with holes, pins and
  slots of known sizes, standing and lying. You measure it with calipers and
  enter the numbers, and Forge stores your printer's real offsets for each
  orientation.
- **Fits use the profile.** "Clearance for M4" or "press fit for a 608
  bearing" is sized for your printer, and the report shows the nominal and
  printed sizes.
- **Build plate.** The 3MF is placed on the plate in the chosen orientation.
- **Slicer, optional.** When PrusaSlicer is installed, Forge runs its
  command-line slicer and reports print time, filament grams with your
  infill, and support volume. A failed slice holds the part. PrusaSlicer is
  AGPL, so it is run as a separate program and never bundled.
- **Finite-element analysis, later,** as a separate process: build123d →
  STEP → gmsh → scikit-fem. In a test it matched beam theory to 0.014% in
  4 seconds. *(Stage 4b revision 5: the analysis core is built at 4b.15,
  two meshers and two solvers per analysis type, each a separate program;
  stage 6 uses it.)*

### 4.9 Speed and cost

V1 used five or more model roles per part, with repair rounds. The arm's
parts cost $0.30–1.00 and took 1–11 minutes. In V2:

- **A typical part takes one or two model calls:** the spec drafts, in
  parallel. The schema and guide are prompt-cached, and word-number citations
  keep the answers short.
- **Answers to questions are applied by code,** so no redrafting.
- **Building, checking and exporting are code,** with no credits.
- **The agent runs only for freeform regions or rejected constructions,**
  with a hard budget that pauses and asks.
- **The visual review runs only where it can add something.**
- **Every operation is cached by content,** so a change rebuilds only what
  changed (ADR-0006).

The cost target counts everything: drafts, questions, construction and your
time.

### 4.10 Editing, memory and families

- **Change requests:** "make the holes 3 mm" is turned into a typed edit to
  the spec. You see the edit as a difference and confirm it. The part then
  rebuilds and re-verifies in seconds. Typing new sizes into the preview
  yourself is already a confirmation.
- **Editable parametric export:** a build123d script with named parameters
  and the spec's relations, not fixed coordinates. Changing a parameter moves
  what depends on it. The script is re-run to check it rebuilds the same part,
  and you can open it and keep designing.
- **Design memory:**
  - confirmed specs and their constructions are kept;
  - a new brief that matches a known family uses it to pre-fill the draft.
    Every value from the family is marked as such and confirmed like any
    other;
  - a resize you type is deterministic: no model call, under 30 seconds,
    fully re-verified (stage 4b revision 5: a resize is a new
    confirmation; a part with analysed requirements or optimised shapes
    re-runs them first, in their own time).
  - The arm's four curved plates would have been one design and four sizes.

---

## 5. Compared with what exists

**What is out there now:**

- Several tools let a model drive Fusion, Onshape, FreeCAD or build123d over
  MCP.
- Zoo's Text-to-CAD generates exact geometry through code.
- No shipping product publishes a check of its result against what was
  asked. The closest, build123d-mcp, gives the model measurements but
  compares them with nothing.
- Research systems such as CADTests do check against the request. Forge V2's
  claim is to put the pieces together in one tool, not to have invented them.

| | Model driving a CAD program over MCP | Forge V2 |
|---|---|---|
| What the part is | decided by the model as it goes | a typed spec you confirm, shown as a 3D part |
| Whether it's right | judged by the model, from screenshots and numbers | judged by code from the spec, on the shipped files, with each item's views listed |
| Known failure | "converges" on plausible sizes and the wrong shape; self-correction without outside feedback makes it worse | the model never grades its own work |
| Breadth today | the whole program: sheet metal, surfacing, assemblies | Forge's item kinds, growing, plus organic shapes; assemblies at stage 8 |
| Simple parts | many model calls | one or two, then code |
| Proof | none | an evidence report for every item |

**No MCP server.** Forge is used through its own command line and its live
page; it is not offered as an MCP server for other programs to drive
(decided 31 October 2026: it was stage 9's, and is dropped).

---

## 6. Assemblies (after parts)

The same pattern, one level up.

**The AssemblySpec** lists:

- the parts;
- how they join: concentric, coincident, offset, bolted through;
- fits: clearance, press;
- motion ranges.

**The checks**, done by hand for the arm, become automatic:

- holes that must line up;
- faces that must share a plane;
- bolt grip and length;
- interference across the whole range of motion;
- a bill of materials.

**Ready from the start.** V1's document format already separates components
from instances, and its mates reference interfaces, never faces. Stage 3
proves V2 keeps that working.

**Acceptance test:** the exo arm as one project, its 13 parts from one
description, passing the 27 interface checks from the arm's plan script. The
script is kept with the arm and copied here as a fixture.

---

## 7. How it is measured

*Stage 4b: the counts below are superseded where section 1.3's adopted table sets more (planted misreads per tier, never-tuned parts per tier, the blind professional set).*

### Three questions, measured separately

| Question | How |
|---|---|
| **Is the pipeline right?** Given a correct spec, is the part right? | Random specs graded against the generator's own model (4.6): thousands per night, with no model and no cost |
| **Is the draft right?** Does the drafted spec match what was meant? | Briefs with locked answer keys |
| **Does confirmation catch what the draft gets wrong?** | Planted misreads (next section) |

### The sets

| Set | What | Used for |
|---|---|---|
| **Random specs** | 10,000+ a week, with mutants | Pipeline error rate, per combination of item kinds |
| **V1 corpus** | 92-brief validation suite, 545 briefs, 187 real-run fixtures, the arm's 13 parts, V1's 27 false passes | Regression. Tuned on, so never in the headline numbers |
| **Blind sets** | 30 new briefs per stage, at least half written by people other than Forge's developers; 100 for the release | The honest numbers. Retired into the corpus once used |
| **Public benchmark** | CADTestBench: 200 prompts with 5,937 tests by its authors | Comparison: the best published pass rate on its detailed prompts is 0.625. Graded by tests we didn't write, and by reference geometry where it is provided |
| **Planted misreads** | A first trial with you and at least two other people. Then, with your agreement, planted at a low rate in ordinary use, so nobody knows which run has one. Each is revealed right after confirmation and undone, so a missed one is never built. At least 150 before the release claim | Catch rate. Never in the release set's denominator |

### Answer keys

They are written before V2 ever runs on their briefs, independently of V2's
schema, so changing the schema can't change a key:

- **For every brief:** facts written by hand for every field: sizes; each
  hole's diameter, depth, position and axis; counts; end shapes; what must be
  solid or empty.
- **For at least 30 briefs:** a reference solid drawn by a person in another
  CAD program. Forge's part is graded against it by surface deviation, in
  both directions.

### The rules

- **Denominators are stated.** Wrong-but-VERIFIED is counted over VERIFIED
  parts.
- **Each mode is reported separately:** confirmed by a person,
  BUILT TO DRAFT, and every other ending.
- **The release claim** is made over at least 300 VERIFIED never-tuned parts:
  the release set, CADTestBench, and later blind sets as needed.
  - A person confirms each spec by reading the prompt, not the answer key.
    For CADTestBench's 200 prompts that is several hours of confirming.
  - Parts with planted misreads are excluded.
- **Every bug becomes a test,** as in V1.

---

## 8. The stages

Each stage ends with an exit test, and the next starts only when it passes.

| # | Stage | Delivers | Exit test |
|---|---|---|---|
| 1 | **The spec** | The measuring kit: answer-key format, grader, confidence bounds; blind set 1 written by you and others, its keys locked before V2 sees it. One-source schema; provenance and word citations; the new placement solver with V1's tests; spec checks; number and sentence accounting; "not modelled"; questions as typed edits; fixed-wording renderer and dimensioned views; confirmation in the CLI and live page | On blind set 1, not the tuned corpus: 98% of items right before confirmation. No uncited number or sentence missed. The two-draft question measured and decided |
| 2 | **Checks and oracle** | `GeometryView`; check kinds with mutants and near-misses; relation checks; face accounting; topology counts; verification classes; capability table; the NumPy mesh view; hand-made reference parts; the written field definitions; the random-spec generator with its own shape model | Every mutant beyond tolerance rejected, every near-miss passed, for every check kind. R1 and R2 tests pass |
| 3 | **Exact kernel** | `forge_occ` with after-checks and error flags; references by query; the copying cache; exact measurement; STEP, STL and 3MF export with re-open checks; second-kernel agreement; install proven on the laptop's Windows and in Docker | Every V1 golden and zoo shape rebuilds in both kernels, and they agree where the capability table says they can. STEP opens in FreeCAD and Fusion. A two-part document with a mate round-trips |
| 4 | **The compiler and preview** | Spec → ForgeIR v2 for every determinate item; proven-equal alternatives; the 3D preview; geometry comparison of two drafts; the coloured brief | 10,000 random specs, interacting items included: all pass, no mutant survives, the impossible ones end CAN'T, graded against the generator's model. Every determinate corpus part builds with no model call after the spec. V1's 27 false passes caught both ways |
| 4b | **Coverage** | Forge's spec brought to a professional part modeller's, on a generalised substrate, with Forge's own geometry where OpenCascade is weak and the implicit kernel as a full partner ([V2-stage4b.md](V2-stage4b.md), revision 5). Part one: 4b.0 first, in steps compared old against new: decisions (and a kernel switch, if chosen, as its own step); a module per kind; geometry (frames, depth by geometry, analytic hosts, schema migration); then the oracle (certified solids, exactness by construction, honest tolerances, freeform hosts), topology (several bodies, order graph, selections), sketches and pinned algorithms, and the cross-cutting rest (views, interfaces, derived products, classes and endings, configurations, composites, tolerance classes, mesh-only parts, the trust core's STEP reader, the guide by family). Then 4b.1 solid features, 4b.2 holes, threads and standard features, 4b.3 modifiers, 4b.4 patterns and mirrors, 4b.5 surfacing, 4b.5a plastic fastening features, 4b.6 sheet metal, 4b.7 mold tools and weldments, 4b.8 configurations and imported geometry, 4b.9 organic, lattice and mixed parts, 4b.10 GD&T, materials and requirements. Part two (revision 5, 10 November 2026): 4b.11 freeform foundations (Forge's own freeform offsets, G2 roundings on freeform faces, G2 corner blends with setbacks), 4b.12 class-A surfacing, 4b.13 subdivision modelling, 4b.14 engineering calculation and materials, 4b.15 analysis (structural, thermal, flow; the core once planned for stage 6, widened), 4b.16 generative design and optimisation, 4b.17 meshes, imports and recognition, 4b.18 breadth. Then the peak check | 4b.0: byte-identical results after the refactor, the same endings after each geometry step; a counted run of 10,000 interacting specs on the new abilities; pathfinders, one simple member per family, each landing in its own kind modules only (a lint forbids kind names outside them); a speed gate. Each of 4b.1 to 4b.10: a shakedown, then 3,000 counted specs on fresh seeds, its kinds interacting with every earlier kind. A counted spec: no wrong part, no surviving mutant, impossible specs CAN'T, holds within the family's budget. Then 10,000 counted on frozen code from the target distribution: none wrong, under 1 in 3,000 (1 in 10,000 is shown at stage 9, on the release code); per kind, top-up strata within the compute budget 4b.0a sets, with a re-plan gate after 4b.0. The nine corpus briefs, the gear and the heart built; a professional set of 30 or more parts graded against reference solids. Part two: each of 4b.11 to 4b.18 counted as part one's (3,000 on fresh seeds, interacting with every earlier kind), calculators reproducing their standards' worked examples, solvers passing benchmarks and agreeing, optimised parts' requirements verified by analysis; then 10,000 on frozen code with part two's kinds, the professional set widened by 15 parts. The peak check: the scope audit made again, every capability still missing added or left out for one of V2-stage4b.md section 4's reasons; the owner's long debugging campaign ending in a clean whole run |
| 5 | **Construction agent** | Tools, budgets, stop rules, freeform regions, the escape hatch in Docker; on stage 4b's frames and placeable faces, Forge's own constructions as ops the agent may use; a rule with 4b.5 for a surface item against a region; whether a region may be built in the implicit kernel (then judged on meshes only); the escape-hatch solid a type of its own that never reaches the oracle | Corpus and a fresh blind set: none wrong but VERIFIED; completion 98% or more; cost under target; drafting accuracy (98% or more per item) and the catch rate measured on 4b kinds, at least 10 professional briefs in the blind set; the guide's cost with about 270 kinds and modes (stage 4b's two parts) reported |
| 6 | **Real-world accuracy** | Orientation; the coupon and printer profile; the print spec; fits, inserts, nut traps and bearing seats; printability; slicer; strength; drawing; parametric script; `requirements.process` (FDM, SLA, SLS, 3-axis CNC, sheet metal, molded, unspecified) and manufacturability checks by process (printing: overhangs, bridges, thinnest wall, trapped resin or powder; CNC: tool reach, inside corner radii, depth to width, undercuts; sheet metal: least flange, hole to bend, bend radius to thickness; molding: 4b.7's draft and undercut, wall uniformity); ISO 286 fits for machined parts beside the printer's compensation; a declared-difference check between nominal and print files, the print transform implemented independently by the generator, random specs through the print path with random profiles; strength analysis by stage 4b.15's analysis core (revision 5: brought forward and widened there), each requirement ending per stated method (V2-stage4b.md, item 18); the drawing: views by hidden lines from the shipped STEP, sections, details, auxiliary views, dimensions placed by the spec's relations, hole and thread callouts, GD&T frames and datums, weld symbols (ISO 2553, AWS A2.4; stage 4b revision 5), general tolerance note, title block, flat pattern with bend table, weldment cut list, as PDF, SVG and DXF, every value re-measured; STEP AP242 with names, colours, materials and GD&T PMI; IGES; 3MF one object per body; JT (ISO 14306) and DWG (R2000), each re-opened by a reader apart from the writer and compared with the part's STEP or DXF (revision 5; Parasolid x_t is read, not written: V2-stage4b.md, section 4); mold-flow simulation by OpenFOAM's free-surface solver, VERIFIED EXCEPT, and sheet metal's bend sequence and press-brake collision (revision 5); CAM toolpaths for 3-axis milling and drilling, then 3+2 and turning (OpenCAMLib), each checked by simulated stock removal against the part, gouge-free within the tolerance (revision 5); photoreal rendering (revision 5); print cost; the parametric script redefined as code on the pinned OpenCascade plus a small Forge runtime for Forge's own constructions; part splitting for printing (added 3 November 2026): a part larger than the printer's bed, or asked for in pieces, cut along stated or chosen planes into bed-sized pieces, with alignment features (dowel holes and pins, keys, dovetails, lap joints) and fastening (bolt bosses, glue gaps), the joints' clearances from the printer profile; each piece judged as a part, and the pieces put back together judged equal to the whole | Every printability check mutation-tested. Printed sizes predicted within 0.1 mm on your printer. The script rebuilds every corpus part; every kind's reserved slots (4b.0 item 6) filled; the corpus and 4b's professional set re-judged under the full gate; a split part: every piece VERIFIED, the pieces reassembled verified against the whole, the joints' fits measured |
| 7 | **Editing and memory** | Change requests, families, deterministic resizing; the sketch solver (ADR-0028) keeping each sketch on its solution branch (a flip is a question); a resize is a new confirmation, what it re-runs shown first (V2-stage4b.md, item 28); families and 4b.8's configurations one concept, VERIFIED per configuration; relations and parameter graphs compared between drafts (a design-intent misread builds the same part); typed edits in the preview need the confirmation code or end BUILT TO DRAFT (R12); revision history with digests, design diffs (typed edits plus geometric difference), revert; version and data management over that history: part numbers, lifecycle states, where-used, check-in and check-out (revision 5) | A resize: no model call, under 30 s, still VERIFIED (a part with analysed requirements or optimised shapes re-runs them first, in their own time, and is re-judged per stated method); random edits on random specs graded against the generator's model of the edited spec; planted misreads in change requests; resize times tiered by part size |
| 8 | **Assemblies** | AssemblySpec, joins, fits, motion and interference, bolt checks, bill of materials; AssemblySpec in `forge_spec`, cited and confirmed; a mate solver that solves only the mates stated, counting degrees of freedom (under-constrained a question, contradictory CAN'T); assembly checks in `forge_checks` over each instance's shipped files, independent of the solver; mates over 4b.0's placeable faces (cone seat, sphere, gear pitch, pin in slot, hinge and slider with limits, screw, ratio, angle, parallel); a library of standard parts compiled from tables (ISO 4762, 4032, 7089, 2338, ISO 15 bearings, inserts, circlips) with BOM designations; derived assembly features (bolted through makes matching holes), cross-part parameters, patterns and mirrors of instances; bodies against components; motion with interference checked across each range by a certified sampling bound; gear pairs and racks; quasi-static torque along a range; worst-case 1-D tolerance stacks, and statistical 3D tolerance analysis by Monte Carlo (revision 5); assembly mass properties; assembly drawings (exploded views, BOM table, balloons); pipe, tube, cable and harness routing with fittings from tables, bend limits and clearances; dynamics (rigid bodies with mass, forces and contact; Project Chrono and MuJoCo, compared; VERIFIED EXCEPT) beside kinematic motion; the impact of a deformable assembly (4b.15's impact programs; VERIFIED EXCEPT); actuators as standard parts from vendor data, each joint's torque and speed checked against the actuator chosen (VERIFIED EXCEPT where it rests on dynamics); assemblies beyond about 200 parts in a lightweight mode (revision 5) | The exo arm as one project, its 27 interface checks automatic; random assemblies with mutants (a hole 0.5 mm off, a bolt too short, interference at the end of a range) and a professional set of assemblies; the arm's 27-check script added to the repository as a fixture |
| 9 | **Release** | planted misreads per tier as section 1.3 sets; the release set: a blind professional set written by others (at least 50 parts and 10 assemblies) and 300 or more never-tuned parts (at least 100 over 60 items); the CADTestBench run, confirmed by a person; docs; licence; the pipeline bound re-measured on the release code through the print path, drawings, scripts, resizes and assemblies; answer keys for flat patterns, configurations, mates and BOMs, and (revision 5) for requirements and derived values, the key writers computing the requirement verdicts with an independent tool, with a band | Section 1.3's targets met, each with its bound and denominator. No open gap: [V2-gaps.md](V2-gaps.md), the register of every place Forge says it can't do something yet (held to the code by `tests/test_v2_gaps.py`), empty but for its stated design bounds, each confirmed by the owner |

Stages 1 and 2 come before the kernel and the builders on purpose: the spec
and the oracle make every later stage measurable.

**No stage 0.** V1 needs no further work, and it is not re-run on new briefs:
its numbers are already measured (89 of 91 on the validation suite; on the
arm, 2 or 3 of 13 parts passed while wrong), and a new baseline would spend
credits measuring the old version. If a side-by-side comparison is ever
wanted, V1 can be run on the same blind set as V2 at that point.

---

## 9. Risks

| Risk | What we do about it |
|---|---|
| A misread that you confirm | 3D preview; every item dimensioned; coloured brief; assumptions and draft differences first; the catch rate measured on its own |
| The oracle and compiler wrong the same way | Written separately from written field definitions; relation checks don't use the solver's coordinates; random specs graded against the generator's own shape model |
| Oracle can't predict a shape exactly | Verification classes: bounded and constrained items are labelled as such, never passed as exact |
| OpenCascade fails or lies on hard shapes | After-checks, error flags, proven alternatives, the agent, the implicit kernel; never a silent pass |
| build123d's history interface is a month old | Not used: `forge_occ` calls OCP directly (V2-stage3.md), pinned, with its own tests |
| Cost runs up | One or two calls for typical parts; answers applied by code; the agent only where needed; a hard budget that pauses |
| Too few parts to prove the error rate | Random specs measure the pipeline at scale; 300+ VERIFIED never-tuned parts for the claim; bounds and denominators always shown |
| Confirmation becomes a chore | Assumptions and differences first; one round of multiple-choice questions; known families pre-fill the draft, so there is less to correct |
| Escape-hatch code is unsafe | Docker only, locked down; output parsed in a separate process |
| Install trouble on Windows | Pinned versions (OpenCascade 7.9.3 through OCP today; 8.0 decided at stage 4b.0a) and a Docker image; checked on the laptop at stage 3 |
| Random-spec runs too slow for a laptop | Throughput measured and sized; parallel processes; the desktop with Docker when available |
| Model behaviour changes | Provider-neutral layer; every call recorded and replayable; Sonnet 5 stays the default |
| Licences | Forge Apache-2.0 fits build123d and OpenCascade used as a library. Slicers (AGPL) and gmsh (GPL) run as separate programs, never bundled. *Stage 4b revision 5:* Netgen, CalculiX, code_aster, OpenFOAM, SU2, OpenRadioss, LibreDWG, `slvs` and `dolfinx_eqlb` also run as separate programs, never imported, the GPL ones' source offered where Docker ships them; OpenSubdiv under Pixar's modified Apache 2.0; Siemens' XT reference terms checked at 4b.0a; NAFEMS benchmarks used under their licence |
| Scope grows without end | Stage gates |

---

## 10. Sources

- build123d 0.13.0: <https://pypi.org/p/build123d>
- OpenCascade 8.0.1 release notes: <https://github.com/Open-Cascade-SAS/OCCT/discussions/1415>
- OpenCascade boolean operations, fuzzy value and error checks: <https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/master/dox/specification/boolean_operations/boolean_operations.md>
- Open CASCADE Exception 1.0: <https://spdx.org/licenses/OCCT-exception-1.0.html>
- CADTests / CADTestBench (2026): spec tests agree with people 93.8% vs 47.4% for a vision model; images in the loop gave no gain; best detailed-prompt pass rate 0.625: <https://arxiv.org/pdf/2605.07807>
- CADSmith (2026), "false convergence": <https://arxiv.org/html/2603.26512v1>
- Text2CAD-Bench (2026), sweep, loft and shell failures: <https://arxiv.org/pdf/2605.18430>
- Hephaestus-CCX (2026), 0 of 400 strict passes on first attempts: <https://arxiv.org/pdf/2605.17448>
- ProCAD (2026), failures mostly from too few questions: <https://arxiv.org/pdf/2602.03045>
- Two independent extractions, agreement 0.94 vs disagreement 0.41–0.50 (medRxiv 2024): <https://www.medrxiv.org/content/10.1101/2024.09.20.24314108.full.pdf>
- Large language models can't self-correct reasoning yet (ICLR 2024): <https://arxiv.org/pdf/2310.01798>
- FutureCAD (2026), B-rep-grounded edge choice, invalid models 8.29% → 1.01%: <https://arxiv.org/pdf/2603.11831>
- build123d-mcp: <https://pypi.org/project/build123d-mcp/0.3.80/>
- Autodesk Fusion MCP: <https://www.autodesk.com/products/fusion-360/blog/introducing-the-fusion-mcp/>
- Zoo Text-to-CAD: <https://zoo.dev/docs/zoo-design-studio/text-to-cad>
- Knight and Leveson, correlated failures in independently written programs: <https://www.kth.se/social/files/564df871f2765419e306178d/KnightLeveson.pdf>
- FreeCAD's topological naming algorithm: <https://github.com/realthunder/FreeCAD_assembly3/wiki/Topological-Naming-Algorithm>
