# Forge V2: the code architecture

*Stage 4b (3 November 2026, [V2-stage4b.md](V2-stage4b.md)) supersedes parts of this page, to be refreshed at stage 4b.0a: the verification classes (ADR-0020's three become seven, item 18), one derived spec (ADR-0021: a registry of declared derived products, item 17), the STEP file re-read by OpenCascade (section 6: Forge's own reader in the trust core, item 24), the kernel versions (section 9: OCP 7.9.3 is what is installed; 8.0 decided at 4b.0a), and loft and sweep surfaces computed in `forge_spec` and handed to the kernel (pinned algorithms recomputed independently, item 13).*

Status: revision 2, for agreement, 20 October 2026. Companion to
[V2-plan.md](V2-plan.md), which says what V2 does and in what order it is
built. This document says how the code is shaped and why each boundary is
where it is.

---

## 1. Principles

1. **Correctness is decided by code that no model touches and that can't see
   the design.** The trust core judges; everything else proposes.
2. **Independence is enforced, not hoped for.**
   - The compiler and the oracle both start from the confirmed spec, and share
     no construction code.
   - Relation checks measure on the built part, not from the solver's
     coordinates.
   - An import-graph test fails the build if either changes.
3. **One source for every contract.** The spec schema generates the model's
   tool schema, the validator, the model's guide and the fixed-wording
   renderer. V1 already does this for ForgeIR (`forge_ir/spec.py`); V2
   extends it to the spec.
4. **Fail closed.** A step that can't be done stops with its reason. Nothing
   is skipped and carried on, as V1's compiler already guarantees.
5. **Everything is replayable.** Every model call is recorded (ADR-0011).
   Every step is checkpointed. A resumed run continues from its recorded
   answers.

---

## 2. Packages and layers

```
 L3  orchestration and use     forge_orchestrator  forge_cli  forge_memory
                               forge_eval  (forge_assembly later)
 ─────────────────────────────────────────────────────────────────────────
 L2  model-facing              forge_roles  forge_designer
 ─────────────────────────────────────────────────────────────────────────
 L1  adapters                  forge_occ  forge_print  forge_fonts
                               forge_sandbox  forge_models
 ─────────────────────────────────────────────────────────────────────────
 L0  trust core                stdlib only:  forge_units  forge_expr  forge_ir
     (no model, no CAD lib)                  forge_evidence  forge_analysis
                                             forge_plan
                               NumPy only:   forge_geom  forge_kernel
                                             forge_spec  forge_checks
                               (and Forge's own compiled crate forge_core,
                                ADR-0024, ADR-0034)
```

**Dependency rules, each checked by `tests/test_architecture.py`:**

| Rule | Why |
|---|---|
| A package imports only from its own layer or below | Layering |
| L0 imports only the standard library, NumPy, Forge's own crate `forge_core` and other L0 packages | ADR-0002, ADR-0034, rule R11 |
| `forge_checks` never imports `forge_plan`, `forge_kernel`, `forge_occ`, `forge_designer`, or ForgeIR's construction types | Checks can't see the design (R2) |
| `forge_plan` never imports `forge_checks` | The compiler can't tune itself to the checks |
| `forge_checks.oracle` never imports `forge_geom` | The oracle shares no shape code with the second kernel |
| `forge_designer` reaches checks only through `VisibleChecks`, and never the fresh probe sample | Nothing fitted to the final sample |
| Nothing but `forge_models` reads the API key | No secret in records |

### What each package does

| Package | Layer | Responsibility | Status |
|---|---|---|---|
| `forge_units` | L0 | Quantities, intervals, units, three-valued logic | V1, kept |
| `forge_expr` | L0 | Safe expressions, the parameter graph | V1, kept |
| `forge_ir` | L0 | ForgeIR v2 format, v1 → v2 converter, generated guide and schema | V1, extended |
| `forge_evidence` | L0 | Evidence graph, gates, statuses (ADR-0008) | V1, kept |
| `forge_analysis` | L0 | Analytical strength checks, materials | V1, kept |
| `forge_geom`, `forge_kernel` | L0 | The implicit kernel, now the second kernel, plus `ImplicitView` | V1, extended |
| `forge_spec` | L0 | The PartSpec (sections 3, 4.1) | **new** |
| `forge_checks` | L0 | Views, checks and the oracle (4.2, 4.3) | **new** |
| `forge_plan` | L0 | The deterministic compiler: confirmed spec → ForgeIR v2, with proven-equal alternatives per item | **new** |
| `forge_occ` | L1 | OpenCascade through its OCP bindings, directly (V2-stage3.md; ADR-0022: OpenCascade 8.0.1) | **new** |
| `forge_print` | L1 | The calibration coupon, entering measured offsets into a profile, the optional slicer run | **new** |
| `forge_fonts` | L1 | Reads the one pinned font (fontTools) into glyph outlines, stored in the spec when text is resolved | **new** |
| `forge_sandbox` | L1 | Runs escape-hatch code in Docker | **new** |
| `forge_models` | L1 | Providers, streaming with idle timeouts, retries, recorded fixtures, budgets | V1, extended |
| `forge_roles` | L2 | Role framework (`base.py`), patches (`patch.py`), the spec writer, the reviewer | V1, rebuilt |
| `forge_designer` | L2 | The construction agent: tools, budget, progress detector | **new** |
| `forge_orchestrator` | L3 | The run's states, checkpoints, resume, the release gate | V1, rebuilt |
| `forge_cli` | L3 | Commands and the live page, including the preview, the confirmation page and the confirmation code shown in Forge's own window | V1, extended |
| `forge_memory` | L3 | Families that pre-fill drafts, deterministic resizing, change requests as typed edits you confirm | **new** |
| `forge_eval` | L3 | Answer keys, graders, bounds, the random-spec generator with its own shape model, planted misreads | **new** |

**`forge_spec` in detail:**

- schema and values;
- word numbering and citation checks;
- the frame;
- the placement solver;
- spec checks;
- number and sentence accounting;
- "not modelled";
- questions as typed edits;
- standard tables: fits, threads, inserts, nut traps, bearing seats,
  ISO 2768;
- loft surfaces and sweep frames, computed here and handed to the kernel;
- text layout from the stored glyph outlines;
- print orientation;
- the `PrinterProfile` type (plain data; `forge_print` only fills it in) and
  the print-spec transform;
- the fixed-wording renderer and dimensioned views;
- locking.

**`forge_checks` in detail:**

- the `GeometryView` interface;
- check kinds, each with its mutants and near-misses;
- relation checks;
- face accounting;
- topology counts;
- the judge's own placement, from the written definitions, compared with
  the solver's at confirmation (`place.py`, over the outlines in a face's
  plane, `outlines.py`);
- the oracle;
- fresh probes;
- verification classes and the capability table;
- the NumPy mesh view for STL and 3MF.

**`forge_occ` in detail:**

- operations and their after-checks;
- history and references;
- the copying cache;
- exact measurement and `BrepView`;
- export and the re-imported `StepFileView`;
- joining mixed parts: the OpenCascade portion is meshed and joined to an
  implicit-kernel region with manifold3d;
- the parametric-script export, written with the spec's named parameters
  and relations.

**What leaves:**

- **The wording rules in `forge_roles/library.py`.**
- **The placement solver is rewritten, not moved.** V1's
  `_resolve_the_placements` guesses: it turns boxes, picks the up axis from
  parameter names, and reads V1's requirement record. Its tests are ported to
  the new solver, which solves only the relations stated.
- **Measurement algorithms that earned their place,** such as the
  rounded-end measurement, are ported into check kinds.
- **V1's tests** become corpus cases.
- **`forge_pipeline`:** `verify.py` becomes the release gate in the
  orchestrator, and `render.py`'s six-view sheet becomes the agent's `render`
  tool.

---

## 3. The data model

All spec types are frozen dataclasses in `forge_spec`. The JSON schema the
model fills in, the validator, the guide and the renderer's wording table are
generated from them.

```python
# forge_spec/values.py
WordRef = tuple[int, ...]        # indices into the brief's numbered words

@dataclass(frozen=True)
class Provenance:
    kind: Literal["brief", "table", "derived", "assumed"]
    words: WordRef = ()          # kind == "brief": code checks the value follows from these words
    table: str | None = None     # "iso_273_clearance:M4:normal"
    formula: str | None = None   # "plate.width / 2", evaluated by forge_expr
    reason: str | None = None    # kind == "assumed": shown to the person

@dataclass(frozen=True)
class Value:
    quantity: Quantity           # forge_units; a unit is mandatory, angles included
    tolerance: Tolerance | None  # None: the spec's general class (ISO 2768-m by default)
    provenance: Provenance

@dataclass(frozen=True)
class Count:                     # its own type, with no unit
    n: int
    provenance: Provenance
```

```python
# forge_spec/schema.py  (abridged)
ItemId = NewType("ItemId", str)  # assigned by Forge, never matched by name

@dataclass(frozen=True)
class Ref:                       # a reference by meaning
    item: ItemId
    role: str                    # from the item kind's role list: "top", "end_min", "bore"
    instance: int | None = None

@dataclass(frozen=True)
class Relation:                  # one stated relation, kept so it can be checked on the part
    kind: Literal["distance", "on_line", "concentric", "centred", "each_of", ...]
    to: Ref
    value: Value | None
    words: WordRef

@dataclass(frozen=True)
class Hole:                      # one of about 30 item kinds
    id: ItemId
    count: Count
    diameter: Value | Fit        # Fit: "clearance for M4", resolved from the tables
    depth: Value | Through
    end: Literal["flat", "drill_point"]
    counterbore: Counterbore | None
    countersink: Countersink | None
    thread: Thread | None        # pitch and hand
    on: Ref
    relations: tuple[Relation, ...]
    words: WordRef

@dataclass(frozen=True)
class FreeformRegion:            # the only items the agent designs
    id: ItemId
    envelope: Box | Sketch
    attaches_to: tuple[Ref, ...]
    fill: FillRule               # section areas or volume fraction, so a small blob fails
    constraints: tuple[Constraint, ...]   # thinnest wall, smooth join, section ranges
    words: WordRef

@dataclass(frozen=True)
class PartSpec:
    frame: Frame
    body: Body                   # splines and loft sections as explicit control points
    items: tuple[Item, ...]
    regions: tuple[FreeformRegion, ...]
    requirements: Requirements   # material, mass, loads, printer profile, general tolerance
    orientation: Orientation     # chosen by code, shown, changeable
    interfaces: tuple[Interface, ...]
    not_modelled: tuple[NotModelled, ...]   # what the brief says that the part won't have
    silent: tuple[Silent, ...]   # sentences that say nothing about the shape, with reasons
```

```python
# forge_spec/lock.py
@dataclass(frozen=True)
class ResolvedSpec:
    spec: PartSpec
    instances: Mapping[ItemId, tuple[Placed, ...]]   # coordinates in the frame
    classes: Mapping[ItemId, VerificationClass]      # EXACT | BOUNDED | CONSTRAINED
    problems: tuple[SpecProblem, ...]                # must be empty to confirm

@dataclass(frozen=True)
class ConfirmedSpec:
    resolved: ResolvedSpec
    digest: str                  # SHA-256 of the canonical JSON, carried by every later stage
    by: Literal["person", "draft"]   # "person" needs the code shown only in Forge's own window
    edits: tuple[SpecEdit, ...]  # what the person changed, for the "edits needed" measure

@dataclass(frozen=True)
class PrintSpec:                 # the one derived spec (R3, R7)
    of: str                      # the ConfirmedSpec digest it was made from
    profile: str                 # the PrinterProfile digest, confirmed with the spec
    resolved: ResolvedSpec
    digest: str
```

**ForgeIR v2** (in `forge_ir`) is the construction: steps, not meaning.

- `schema_version: 2`. Components, instances and mates are kept from V1.
- Each step has a Forge-owned `id`, an `op`, `inputs`, and `params` with
  units.
- Each step records `for_items`, the spec items it builds, so a failure names
  a spec item.
- References are queries with a match condition:

```json
{"created_by": "s14", "role": "side", "where": {"axis": "z", "radius_mm": 1.4},
 "match": {"count": [1, 4], "covers": "full_circle"}}
```

New ops:

- `fillet` and `chamfer` on reference sets
- `thread`, `text`, `draft`, `countersink`
- `freeform`, tagged with its region
- `escape`, with the code's hash

---

## 4. The interfaces

### 4.1 Spec

```python
# forge_spec
def number_words(brief: str) -> NumberedBrief
def check_draft(brief: NumberedBrief, draft: PartSpec) -> SpecReport
    # schema, units, citations (each value follows from its words), accounting
    # (every number, number word and sentence cited), placement from stated
    # relations only, contradictions, fit, print limits, orientation
def questions(report: SpecReport, differences: Sequence[GeometricDifference]) -> tuple[Question, ...]
def apply_answers(spec: PartSpec, answers: Sequence[Answer]) -> PartSpec   # typed edits, no model
def render(report: SpecReport, brief: NumberedBrief) -> RenderedSpec   # fixed wording, numbered
def render_views(report: SpecReport) -> Views   # top, front, side: every value of every placed item
    # shown, on a view or in words; each line spans what its text says; overall sizes labelled
def print_spec(spec: ConfirmedSpec, profile: PrinterProfile) -> PrintSpec   # the one declared transform
def confirm(spec: ResolvedSpec, code: PersonCode | None) -> ConfirmedSpec   # refuses with problems left
```

`GeometricDifference` comes from compiling both drafts, aligning them, and
comparing them with `forge_checks`. So the drafts' item names are never
matched, and different origins don't count as differences.

The person's code is shown only in Forge's own terminal or a system
notification, never on the web page, and is typed back by the person.

### 4.2 Views

Every kernel and every shipped file is seen through one interface:

```python
# forge_checks/view.py
class GeometryView(Protocol):
    source: str                                 # "brep" "implicit" "step-file" "stl-file" "3mf-file"
    capabilities: frozenset[Capability]         # CLASSIFY RAY VOLUME FACES EDGES SURFACE_SAMPLES
    def classify(self, points: NDArray) -> NDArray[int8]    # +1 inside, 0 on (± eps), -1 outside
    def ray(self, origins: NDArray, directions: NDArray) -> RayHits
    def volume(self) -> Interval
    def bounds(self) -> Box
    def surface_samples(self, density: float) -> SurfaceSamples   # points on every face or triangle
    def faces(self) -> Sequence[FaceFacts]      # exact views only: type, radius, axis, pitch, area
    def edges(self) -> Sequence[EdgeFacts]
```

The implementations:

- `BrepView` and `StepFileView` (in `forge_occ`);
- `ImplicitView` (in `forge_kernel`);
- `MeshView` for STL and 3MF (in `forge_checks`), written in NumPy
  ([V2-stage2.md](V2-stage2.md), section 5.7):
  - soundness first, exactly: closed, consistently oriented, no
    self-intersections, shells nested as they face; a mesh that isn't sound
    classifies nothing;
  - classification by the pseudonormal at the nearest point, with three
    rays where that sign is too small to trust, searched through a tree of
    boxes;
  - watertight ray crossings, for thicknesses.

  So the shipped meshes are checked by code that doesn't use OpenCascade
  (R11).

**The capability table** (`forge_checks/capabilities.py`) fixes, for each
pair of view and operation, whether the view's answer is exact, bounded by a
stated tolerance, or not applicable. A view's failure on an exact or bounded
entry holds the part. "Not applicable" comes only from this table.

### 4.3 Checks and the oracle

```python
# forge_checks
@dataclass(frozen=True)
class Check:
    id: str                      # "<item>/<aspect>[/<instance>]": "post_pilot/depth/3"
    item: ItemId
    aspect: str                  # diameter, depth, axis, count, relation, shape, wall, ...
    klass: VerificationClass
    needs: frozenset[Capability]
    tolerance: Quantity
    def run(self, view: GeometryView) -> Evidence   # PASS / FAIL / INCONCLUSIVE, with numbers

def compile_checks(spec: ConfirmedSpec) -> CheckSuite
    # total over the schema: every field of every item kind gives a check
    # or an explicit UNCHECKED, which test_r1 enumerates
def relation_checks(spec: ConfirmedSpec) -> CheckSuite
    # one per stated Relation, measured from built faces located by role
def oracle(spec: ConfirmedSpec) -> Oracle
    # exact items: point classification and surface samples, trimmed by its own classification
    # bounded items: exact sections plus inner and outer limits between them
    # constrained regions: envelope, fill, walls, joins
def account_faces(oracle: Oracle, view: GeometryView) -> Evidence
    # built samples on spec surfaces, and spec samples on built surfaces,
    # at the view's own build tolerance (not design tolerances);
    # topology counts after merging faces on the same surface;
    # volume with the view's own tolerance
def fresh_probes(oracle: Oracle, seed: int) -> ProbeSet
    # the seed is drawn after the build and recorded in the checkpoint
```

Check kinds live one per file in `forge_checks/kinds/`. A test requires each
file to hold all four parts:

- its measurement;
- its tolerance policy;
- its mutants;
- its near-misses.

### 4.4 Building

```python
# forge_plan
def plan(spec: ConfirmedSpec) -> Plan
    # Plan.document: ForgeIR v2 for every determinate item
    # Plan.gaps: freeform regions, and items whose every alternative failed

class Strategy(Protocol):        # per item kind: alternatives, each proven to give the same shape
    def constructions(self, item: Item, ctx: PlanContext) -> Iterator[Steps]
```

```python
# forge_occ and forge_kernel implement the same interface
class Backend(Protocol):
    name: str
    version: str
    def build(self, doc: Document, cache: Cache) -> BuildResult
        # after every step: valid solid, boolean error and warning flags read,
        # volume and faces changed as the op should
    def view(self, result: BuildResult) -> GeometryView
    def export(self, result: BuildResult, formats: Formats, tol: ExportTolerance) -> Exported
        # tolerances derived from the spec's; mesh cache cleared first;
        # 3MF placed on the plate in the spec's orientation
```

**The cache:**

- the key is the step's op, resolved parameters, input digests, the backend
  version and OpenCascade's fuzzy tolerance;
- the entry is the serialized solid together with its history;
- every hit is a fresh copy.

### 4.5 The construction agent

```python
# forge_designer
TOOLS = (add_step, change_step, remove_step, compile, measure, query_geometry, render)
    # none can reach the spec or the checks (R4, R2)

def construct(spec: ConfirmedSpec, plan: Plan, visible: VisibleChecks,
              budget: Budget, sandbox: Sandbox | None) -> ConstructResult
```

- **Progress detector:** failing checks and face-accounting misses must fall
  within k rounds, or the agent is told to change approach. A second stall
  ends the item UNABLE.
- **Budget:** rounds, tokens and dollars. When it runs out, the run goes to
  WAITING (R9).

### 4.6 The sandbox

```python
# forge_sandbox
def run(code: str, params: Mapping[str, float], limits: Limits) -> SandboxResult  # BREP bytes or an error
```

- The command is `docker run --rm --network none --read-only --tmpfs /tmp
  --cap-drop ALL --security-opt no-new-privileges --user 10001 --memory 2g
  --cpus 2 --pids-limit 128` on the pinned `forge-sandbox` image.
- A host-side timeout kills the container.
- Code goes in on stdin, and BREP comes out on stdout.
- The BREP is parsed by OpenCascade in a separate host process before
  `forge_occ` takes it in.
- Escape-hatch solids have no history, so references into them use the
  geometric test and match condition alone.

### 4.7 The release gate

```python
# forge_orchestrator/gate.py
class Ending(Enum):
    VERIFIED = ...; VERIFIED_EXCEPT = ...; BUILT_TO_DRAFT = ...
    HELD = ...; CANT = ...; UNABLE = ...; WAITING = ...

def release(nominal: Group, print_: Group, drawing: DrawingFacts,
            script: ScriptRebuild, prints: PrintReport) -> Verdict
    # Group: a spec (ConfirmedSpec or PrintSpec), its checks, its oracle, its views
    #   nominal: brep, implicit, step-file      print: print brep, stl-file, 3mf-file
    # each group is judged against its own spec; groups are never compared
    # Verdict: the ending, each item's evidence and active views, the share of
    # surface checked exactly and within bounds, the next action
```

- Every check runs on every view whose capability-table entry says it can
  answer.
- Agreement between views is itself checked: classification on the fresh
  probes, face accounting and volume, within the table's tolerances.
- **The drawing's dimensions are measured from the geometry.** The drawing
  is then compared with the spec, so it is evidence, not decoration.
- **The parametric script is re-run in a separate process,** and must rebuild
  a solid that passes face accounting against the oracle.
- **`by == "draft"` can at best end BUILT_TO_DRAFT** (R12).

---

## 5. The run

```
DRAFTING ─► SPEC_CHECK ─► QUESTIONS ─(typed edits)─► SPEC_CHECK
                     └──► PREVIEW (compile, no cost) ─► AWAITING_CONFIRMATION
AWAITING_CONFIRMATION ─► CONFIRMED ─► CHECKS ─► PLAN ─► BUILD ─► (CONSTRUCT)
                      ─► EXPORT ─► VERIFY ─► one of the endings
any state ─► WAITING(budget | provider | question) ─► the same state
```

- **Checkpoints:** every transition writes `runs/<id>/state.json` and
  content-addressed blobs.
- **Resume:** `forge resume <run>` continues from the last state, replaying
  recorded model answers rather than calling the model again.
- **Unattended runs** (`--auto`, benchmarks) give WAITING a timeout
  that ends in UNABLE, with the question saved.
- **Resume test:** a run is killed at every state and resumed. Each time, the
  result must equal the uninterrupted run (R9).

**Model calls** go through `forge_models` with:

- streaming, with an idle timeout instead of a whole-reply timeout;
- effort set per role;
- prompt caching of the schema and guide;
- recorded fixtures;
- a configurable model for draft B, so it can differ from draft A's.

The two drafts run in parallel, with different instructions, and neither
sees the other.

---

## 6. Independence: what each check shares with the build

| Check | Code it runs | Shares with the build |
|---|---|---|
| Item checks on the B-rep | `forge_checks.kinds` over `BrepView` | the OpenCascade solid, which is what it measures |
| Relation checks | `forge_checks.relations` | the solid. Relations come from the spec's words, not the solver's coordinates |
| Oracle and face accounting | `forge_checks.oracle` and its own shape code | only the confirmed spec |
| Second kernel | `forge_kernel` building the ForgeIR document | the document, so it checks the kernel, not the compiler |
| Shipped meshes | `forge_checks.MeshView` (NumPy) | the files only; no OpenCascade |
| Shipped STEP | `StepFileView`, plus a text check of its units | the file; OpenCascade reads it back |
| Pipeline overall | random specs graded against the generator's own shape model (`forge_eval`) | the written field definitions, which you approve |

**What is still shared:**

- `forge_units` and NumPy;
- the spec's relations, which you approved in the preview;
- the written meaning of each field.

A further shared risk is a correlated mistake in thinking: Knight and
Leveson showed that independently written programs fail together more often
than chance. That is why the field meanings are written down where you can
read them, and why the pipeline is graded by surface deviation against a
third, separately coded model, not by the views agreeing with each other.

---

## 7. Testing

| Layer | What | When |
|---|---|---|
| **Unit** | Every package, as in V1 (`unittest`) | every change |
| **Rules** | One test per hard rule R1–R12: import graph, schema totality, spec lock, construction tools can't reach the spec, shipped-file re-open, no meaning rewrites, kill-and-resume, the confirmation code | every change |
| **Check kinds** | Mutants 100% rejected beyond tolerance; near-misses all passed; on hand-made reference parts until the compiler exists | every change |
| **Alternatives** | Each alternative construction equals the first, with nothing excluded | every change |
| **Random specs** | Generator with its own shape model; interacting and impossible items on purpose; graded by surface deviation; mutants; weighted like real specs, and per combination of item kinds | 200 per change; nightly count sized from measured time, at least 10,000 a week |
| **Corpus** | V1's validation suite, 545 briefs, 187 replayed runs, the arm, V1's 27 false passes (wrong geometry, and end to end) | every change (replayed, no cost) |
| **Code mutation** | mutmut on L0 with its unit tests, in WSL | weekly |
| **Blind sets and planted misreads** | Live runs on new briefs with locked keys; planted misreads, revealed and undone right after confirmation | each stage exit, and in ordinary use |
| **Static** | mypy strict on new packages, ruff, zero warnings | every change |
| **Performance** | Time budgets for build, verify and export on the corpus | every change |

---

## 8. Repository layout

```
packages/
  forge_units/  forge_expr/  forge_ir/  forge_evidence/  forge_analysis/
  forge_geom/   forge_kernel/                                   # V1 trust core
  forge_spec/      schema.py values.py words.py citations.py problems.py draft.py wire.py
                   geometry.py placement.py derived.py tables.py checks.py accounting.py
                   questions.py orientation.py print_spec.py render.py render_views.py
                   lock.py guide.py
  forge_checks/    view.py readers.py mesh.py predicates.py triangles.py tree.py
                   intersect.py outlines.py place.py capabilities.py classes.py
                   compiler.py relations.py oracle.py shapes.py accounting.py
                   topology.py probes.py
                   kinds/<one file per kind>.py
  forge_plan/      planner.py semantics.py refs.py strategies/<per kind>.py
  forge_occ/       backend.py ops/ aftercheck.py history.py refs.py cache.py
                   measure.py view.py export.py step_view.py script_export.py
                   mixed.py
  forge_print/     coupon.py offsets.py slicer.py
  forge_fonts/     outlines.py fonts/<the pinned font>
  forge_sandbox/   run.py image/Dockerfile
  forge_models/    (V1, extended)
  forge_roles/     base.py patch.py spec_writer.py reviewer.py
  forge_designer/  agent.py tools.py visible.py budget.py progress.py
  forge_orchestrator/  run.py states.py gate.py resume.py
  forge_memory/    signature.py families.py resize.py edits.py
  forge_eval/      keys.py grade.py deviation.py bounds.py generator.py
                   truth_shapes.py planted.py sets.py
  forge_cli/       (V1, plus the preview and confirmation page)
docs/adr/          0001–0011, 0022–0036 (0012–0021: section 10's table; their files written in 4b.0b)
eval/              keys/ references/ blind/ corpus/ planted/    # answer keys, locked
docs/definitions/  what every field of every item kind means    # approved by you
tests/             test_architecture.py test_rules.py ...
```

---

## 9. Dependencies

| Package | Version | Licence | Used by |
|---|---|---|---|
| NumPy | as V1 | BSD | L0 |
| cadquery-ocp-novtk | 8.0.1.1.0, pinned (OpenCascade 8.0.1; ADR-0022, from 4b.0a′; 7.9.3.1.1 until then) | LGPL-2.1 + OCCT exception | `forge_occ` |
| lib3mf | 2.5.0, pinned | BSD | 3MF export |
| manifold3d | 3.5.4 | Apache-2.0 | joining mixed parts (`forge_occ.mixed`) |
| fontTools | current | MIT | `forge_fonts`: reads the pinned font when text is resolved; the outlines are stored in the locked spec |
| Hypothesis | 6.170.x | MPL-2.0 | tests only |
| mutmut | 3.8 | BSD | tests only, in WSL |
| PrusaSlicer console | 2.x, optional | AGPL-3.0 | run as a separate program, never bundled |
| gmsh, scikit-fem | 4.15, 12.0, later | GPL-2+ / BSD | FEA: gmsh in a separate process, scikit-fem in process (ADR-0029) |

- **Install size:** OCP without VTK and lib3mf are what the exact kernel
  needs (build123d is not used: V2-stage3.md). Stage 4b's further
  libraries and programs are ADR-0028 to ADR-0033's; CPython 3.14 is the
  floor (ADR-0023); the compiled core is Forge's own wheel (ADR-0024).
- **Pinning:** versions are pinned in a lock file, and the Docker image is
  the fallback.
- **Windows:** the native install is proven on the laptop at stage 3.

---

## 10. New ADRs

| ADR | Decision |
|---|---|
| 0012 | Exact kernel primary; implicit kernel as an independent second build where the capability table allows (amends ADR-0007) |
| 0013 | The spec is the contract, locked at confirmation, changed only by a person; VERIFIED needs a person |
| 0014 | Checks see only geometry and the confirmed spec; relations are measured on the part |
| 0015 | Checks are tested: mutants, near-misses, random specs graded against the generator's own shape model |
| 0016 | Compile first; an agent only for freeform regions and rejected constructions |
| 0017 | The files shipped are the files verified, the drawing and the script included |
| 0018 | References are queries with match conditions, resolved through history (extends ADR-0003) |
| 0019 | Every spec value carries provenance; every brief number and sentence is accounted for |
| 0020 | Every region of the surface has a verification class (exact, bounded, constrained), shown wherever its result is |
| 0021 | The print spec is the one derived spec: one declared transform, its own checks, never compared with the nominal part |

ADR-0012 to ADR-0021 are recorded in this table. Stage 4b.0a's decisions begin at ADR-0022 (files in `docs/adr/`; [V2-stage4b.md](V2-stage4b.md), 2.1.1); ADR-0034 supersedes ADR-0002 in part.
