# Forge

**An evidence-driven parametric design system.** You describe a mechanical part;
Forge produces editable parametric geometry, measures it, checks it against
declared requirements, and hands back an audit trail in which every claim points
at the evidence that supports it — including the claims it could not verify.

Forge is an engineering system that happens to use AI, not an AI demonstration
that happens to output CAD. The deterministic core runs with no model provider
configured and no network access, which is how its tests stay free, fast, and
impossible to influence with a language model's confidence.

---

## Status: V1 complete

Forge V1 is complete and frozen: one mechanical part at a time, from a
plain-English brief to a measured, print-ready STL. What it does, what it was
proven on, and its known limits are in **[docs/V1.md](docs/V1.md)**. New work
goes into V2.

```
2013 tests, all passing, no third-party test framework required
Verified on CPython 3.10, 3.11 and 3.12, across Linux and Windows 11
```

The loop's own tests need no API key and no network: every model response is
replayed from a recorded fixture, so the orchestrator, the repair loop and the
CLI are tested against the real prompts for free and identically on every run.
([ADR-0011](docs/adr/0011-reproducible-model-calls.md))

---

## The five ideas

Most of what distinguishes Forge from a prompt wrapper around a CAD kernel comes
down to five decisions, each recorded as an [ADR](docs/adr/).

### 1. Uncertainty lives in the type system

An engineering value is not a float. Every quantity in Forge carries a unit *and*
an interval, so tolerance propagates through arithmetic without anyone writing
propagation code, and a comparison whose answer the evidence does not determine
returns `INDETERMINATE` rather than guessing.

```python
>>> thickness = Q(3.0, "mm", plus=0.1, minus=0.1)
>>> thickness.at_least(Q(3.0, "mm"))
<Trivalent.INDETERMINATE: 'indeterminate'>
```

A nominally 3 mm wall with a ±0.1 mm tolerance does not reliably satisfy a 3 mm
minimum, and the type system says so without anyone remembering to check. That
three-valued result becomes an `INCONCLUSIVE` gate, and there is no code path
that turns it into a pass.

### 2. Geometry is identified by construction, not by coordinates

The topological naming problem has broken parametric CAD for thirty years: you
select a face, the system records "face 47", you change an upstream dimension,
the faces renumber, and the fillet lands somewhere else. The usual mitigation is
a heuristic matcher that finds the face most similar to the remembered one — and
whose failures are silent, because a matcher always returns *something*.

Forge derives identity from the feature graph instead:

```
token = H(feature_id, output_role, ordinal)
```

Nothing about the geometry enters the hash. Change a parameter and the graph is
structurally identical, so every token is bit-for-bit identical and every
selection still resolves. This is not a success rate; it is a property the
representation cannot fail at.

Change the *topology* so a named face is buried, and the reference breaks loudly:

```
[KN1001_SELECTION] the named geometry no longer lies on the solid's boundary;
a later feature covered or removed it
  (name='base.z_min', owning_feature='base_plate',
   note='only 0% of the named surface remains on the boundary; 100% is now
         interior, so a later feature added material over it')
```

**Stable by construction under parameter change; loudly broken under topology
change.** A heuristic matcher gets the first case usually right and the second
case silently wrong. ([ADR-0003](docs/adr/0003-lineage-addressed-topology.md))

### 3. Measurement returns enclosures, not estimates

Every CAD system answers "what is the volume?" with one number whose error is
unknown to the caller. Forge answers with an interval that provably contains the
true volume.

A cell of the measurement octree is classified by bounding the distance field
over the whole cell with interval arithmetic. Cells that straddle the boundary
are subdivided; those still straddling at the refinement limit contribute to the
upper bound and not the lower one, because that is all that is known about them.

```
volume : 12820.3 ± 387.7 mm³     (5.5% residual uncertainty, stated)
mass   : 34.63 ± 1.39 g
COM    : 30 ± 0.35 mm, 12 ± 0.22 mm, 7.19 ± 0.20 mm
```

The discretisation error is *reported as uncertainty* rather than hidden in a
point estimate, and it flows straight into three-valued gate evaluation. A 40 g
budget compared against a measured `[39.6, 40.3] g` comes back `INCONCLUSIVE`
and asks for refinement — where a point estimate of 39.95 g would have passed.
([ADR-0005](docs/adr/0005-rigorous-measurement.md))

### 4. The model writes a document; the kernel decides whether it works

The AI layer never touches geometry. It produces a ForgeIR document, and the
deterministic core compiles, measures and gates it exactly as it would a
hand-written one — which is why a generated design gets the same evidence, the
same enclosures and the same refusal to call an unverified thing verified.

Five narrow roles do the work: interpret the brief, derive checkable
requirements, ask about anything that would otherwise have to be invented,
design, and repair what fails. Each declares an output schema, gets it enforced
at the transport by forced tool use, and is then validated *semantically* — that
a threshold carries a unit, that a referenced identifier exists, that the
document compiles. The rule running through all five prompts:

> **A number you made up is worse than a missing one, because it looks checked.**

That rule is enforced downstream rather than trusted. An unresolved unknown
becomes an unapproved high-risk assumption, and an unapproved high-risk
assumption blocks release however many gates passed.

### 5. Two kernels, cross-checked

The implicit backend (signed distance fields, pure NumPy) and the exact backend
(OpenCascade, planned) build the same design behind one adapter interface. Their
measurements are compared, and a disagreement beyond declared tolerance is
reported as a defect rather than averaged away. Two independent implementations
agreeing is evidence; that is why there are two.

---

## What a run looks like

```console
$ forge verify examples/clevis/clevis.forgeir.json \
      --load 500N --arm 35mm --load-assumption ASM_DESIGN_LOAD

Component      : clevis
Part hash      : f596df96c01cc6259bf9169c3978ccc4fd1f2c3f
Backend        : implicit-sdf/0.1.0
Overall status : BLOCKED

Evidence: PASS (14 claims)

  PASS  Bearing stress at the pivot bore shall keep a safety factor of at
        least 2 against yield.                  = 50.4763 ± 3.5216   (>= 2)
  PASS  Clear internal spacing between the ears must be 12 mm so the link
        fits with axial clearance.              = 12 mm              (== 12 mm)
  PASS  No wall may be thinner than 3 mm, for the CNC aluminium scenario.
                                                = 5.59 ± 0.007 mm    (>= 3 mm)
  PASS  The clevis base length shall be 60 mm.  = 60 mm              (== 60 mm)
  PASS  The clevis body should weigh no more than 40 g in 6061-T6.
                                                = 34.63 ± 1.39 g     (<= 40 g)
  PASS  The finished part shall occupy no more than 61 mm along x, so it
        clears the adjacent rail.               = 59.8 ± 0.246 mm    (<= 61 mm)
  PASS  The pivot bores must be 8.2 mm diameter and coaxial.
                                                = 8.2 mm             (== 8.2 mm)
  PASS  extracted surface is a closed, manifold solid
  PASS  independently extracted mesh volume agrees with the octree enclosure
  PASS  interface 'pivot_port' resolves to live geometry (pivot.bore)
  PASS  named geometry buried by later features is reported
  ... 3 more

Not a release candidate because:
  - assumption ASM_DESIGN_LOAD has not been accepted
  - assumption ASM_MATERIAL has not been accepted
```

**Every gate passed and the verdict is still `BLOCKED`.** The design was checked
against a 500 N load that nobody accepted and a material grade nobody confirmed.
Reporting that as a pass with a footnote is how an unexamined assumption reaches
a released design, so Forge does not. Accept the assumptions and the same run
returns `PASS`.

---

## What a design run looks like

`forge design` takes the sentence and runs the whole loop. The interesting case
is not the one that works.

*The transcripts below are real runs, replayed from recorded fixtures — which is
why the token counts and timings are the fixtures' and not a live provider's. No
run against a live provider has been made yet; that is the user's first test.*

```console
$ forge design "I need a bracket to hold a shaft. Make it strong enough."

Provider  : fixture / fixture
Brief     : I need a bracket to hold a shaft. Make it strong enough.

State     : awaiting_answers
Elapsed   : 0.0 s
Model use : 900 tokens (300 in, 600 out)

Before this can be designed, these need answering:
  - [UNK_LOAD] What load does the shaft carry, and in what direction?
      why: Nothing can be sized or verified without it.
  - [UNK_SHAFT_DIAMETER] What diameter is the shaft?
      why: Sets the bore and drives every other dimension.
      e.g. 8 mm, 10 mm, 12 mm, 20 mm

Nothing was invented to fill these gaps. Answer them and re-run:

  forge design \
    "I need a bracket to hold a shaft. Make it strong enough." \
    --answer UNK_LOAD=<your answer> \
    --answer UNK_SHAFT_DIAMETER=<your answer>

  ...or pass --assume to proceed anyway. That records each unknown as a high-risk
  assumption rather than guessing a value, and the result cannot be released.
```

Exit code `3`: neither success nor breakage, so a script can tell the difference.
`--assume` does not mean making something up — each unresolved unknown becomes an
unapproved high-risk assumption, the design is still built and measured, and
release is still blocked with the unknown named.

A brief that carries what it needs goes all the way through, repairing what fails
on the way:

```console
$ forge design "A bracket that holds a 20 mm shaft. It bolts to a flat plate
    with four M5 bolts. The shaft sits 32 mm above the mounting surface and
    carries 300 N downwards. Make it from 6061-T6 aluminium." -v

[  0] ingested               brief received
[  1] interpreting           reading the brief
[  2] interpreting           5 stated facts, 7 things left unsaid
[  3] gathering_requirements deriving requirements
[  4] gathering_requirements 5 requirements, 3 assumptions, 0 critical unknowns
[  5] designing              generating the parametric document
[  6] designing              document generated: 1 component(s)
[  7] repairing              compile failed: one or more parameters are outside
                             their declared bounds
[  8] repairing              applied 1 patch(es): bring the value back inside
                             its declared bounds
[  9] compiling              compiles cleanly
[ 10] verifying              measuring and gating
[ 11] blocked                not a release candidate: blocked

Component      : bracket
Part hash      : 482f66a2cd7619641b9bafed90726890fa59f97e
Overall status : BLOCKED

Evidence: PASS (10 claims)

  PASS  Bearing stress at the shaft bore shall keep a safety factor of at
        least 2 against yield.                  = 235.6 ± 16.4        (>= 2)
  PASS  No wall shall be thinner than 3 mm, so the part can be machined
        without distortion.                     = 8.01 ± 0.011 mm     (>= 3 mm)
  PASS  The bracket should weigh no more than 400 g.
                                                = 189.2 ± 26.3 g      (<= 400 g)
  PASS  The shaft axis shall sit 32 mm above the mounting face.
                                                = 32 mm               (== 32 mm)
  PASS  The shaft bore shall be 20 mm in diameter.
                                                = 20 mm               (== 20 mm)
  PASS  extracted surface is a closed, manifold solid
  PASS  independently extracted mesh volume agrees with the octree enclosure
  PASS  interface 'shaft_port' resolves to live geometry (shaft.bore)
  ... 2 more

Not a release candidate because:
  - assumption ASM_DESIGN_LOAD has not been accepted

Artefacts : runs/20260912T141903-a-bracket-that-holds-a-20-mm-shaft
  run.json               every event, every repair, every token
  run.txt                the same, rendered
  document.forgeir.json  the design, editable and re-verifiable
  evidence.json          each claim, its method, and its limitations
  evidence.txt
```

The design compiles, every gate passes, the bearing margin is enormous — and the
verdict is `BLOCKED`, because the 300 N came from the brief but nobody has
accepted the assumption about how it acts. That is the same refusal the
hand-written clevis gets. Nothing about a document is treated differently for
having been generated, which is the point.

The repair in the middle is deliberately small. The analyst is sent the parameter
that broke its own declared bounds and nothing else — 944 bytes against a 9,262
byte document, measured by the test that holds it that way. A model shown the
whole design will comment on the whole design, and the repair loop is not where
the parts that already compile should be renegotiated.
([ADR-0010](docs/adr/0010-patch-based-repair.md))

---

## Quick start

No installation, no third-party dependencies beyond NumPy:

```console
$ git clone <this repo> && cd forge
$ make test            # 2013 tests, about 50 minutes
$ make verify          # the golden clevis, end to end
$ make export          # writes build/clevis.stl
```

Or drive it directly:

```console
$ forge design   "a 20 mm shaft bracket, 300 N down, 6061-T6"   # needs a key
$ forge inspect  examples/clevis/clevis.forgeir.json
$ forge verify   examples/clevis/clevis.forgeir.json --set ear_thickness=8mm
$ forge sweep    examples/clevis/clevis.forgeir.json \
      --parameter root_blend --start 1mm --stop 5mm --steps 9
$ forge export   examples/clevis/clevis.forgeir.json -o part.stl
```

Exit codes are `0` for `PASS`, `1` for `FAIL`, and `2` for anything undecided —
so a CI pipeline cannot script "we could not check" as success. `forge design`
adds `3`: the run stopped to ask a question rather than invent an answer.

`forge design` needs a model provider. The key is read from `ANTHROPIC_API_KEY`
in the environment and never from a flag, a file or a document; nothing Forge
writes contains it. `--provider openai --base-url ...` points at any
OpenAI-compatible endpoint, including a local one, in which case no design data
leaves the machine. `--record DIR` saves every response so the run can be
replayed offline for free, and `--provider fixture --fixtures DIR` replays it.

### Incremental rebuild, measured

`forge sweep` reports what the content-addressed compiler actually avoided:

| Parameter swept   | Features rebuilt | Avoided |
| ----------------- | ---------------- | ------- |
| `pivot_diameter`  | 18 of 90         | **80%** |
| `root_blend`      | 34 of 90         | **62%** |
| `ear_thickness`   | 58 of 70         | 17%     |

The last row is the honest one: `ear_thickness` feeds nearly the whole graph, so
there is little to reuse. The saving depends on where in the graph you edit, and
it grows with model size, because the dirty cone stays local while the graph does
not. ([ADR-0006](docs/adr/0006-content-addressed-compilation.md))

---

## Capability matrix

Verified means there is a test in this repository that exercises it and fails
when it breaks.

### Built and verified

| Capability | Notes |
| --- | --- |
| Dimensional type system | 7 SI base dimensions, fractional exponents, affine temperature scales handled separately |
| Interval arithmetic | Soundness verified against 16,000 random samples |
| Three-valued comparison | Kleene logic; `bool()` raises by design |
| Unit parser | Recursive descent with parentheses; `W/(m*K)` ≠ `W/m*K` |
| Safe expression engine | Allowlisted AST, never `eval`; 18 hostile inputs refused in tests |
| Parameter graph | Cycle detection reported as a path, deterministic ordering |
| ForgeIR document model | RFC 6901 JSON Pointer on every error; unknown fields refused |
| Feature graph | 22 feature kinds, typed inputs, declared semantic outputs |
| Lineage-addressed topology | Token stability verified across 7 parameter variations |
| Burial detection | Neighbourhood probe, normal-free |
| Content-addressed compilation | Cache key insensitive to unit spelling |
| Implicit geometry kernel | SDF primitives, CSG, exact circular fillets, shell, patterns, mirror, transform |
| Rigorous measurement | Volume, mass, centroid, bounding box as enclosures |
| Tight centroid bounds | Dinkelbach's method on the linear-fractional form |
| Surface extraction | Surface nets; watertight and manifold, volume within 0.1% |
| Evidence graph | Immutable, append-only, limitations required on computed results |
| Six-status gates | `INCONCLUSIVE` derived from arithmetic, not judgement |
| Analytical library | 18 checks, validated against textbook cases |
| Material records | Ranges and sources; family names refused |
| Verification pipeline | End to end with no model provider |
| Measurement bindings | Closed vocabulary; a requirement declares what measures it |
| Model transport | Forced tool use, full-jitter retry, hard budget, cancellation |
| Provider adapters | Anthropic and any OpenAI-compatible endpoint, stdlib `urllib` only |
| Reproducible calls | Fingerprinted requests, recorded fixtures, derived document ids |
| Five design roles | Schema-enforced output, then semantic validation and bounded repair |
| Surgical repair | RFC 6901 patches, all-or-nothing, ambiguous batches refused |
| Orchestration | 12-state run log, oscillation detection, unknowns absorbed not invented |
| CLI | `design`, `verify`, `export`, `inspect`, `sweep`, `capability` |
| Live provider runs | Claude Sonnet 5: the 92-brief validation suite and a 13-part exo-arm project ([V1](docs/V1.md)) |

### Interfaces exist, implementations do not

| Capability | What is missing |
| --- | --- |
| OpenCascade B-Rep backend | The adapter boundary is defined; the backend is not written |
| STEP export | Requires B-Rep topology the implicit kernel does not carry |
| Fusion add-in | Not started |
| Gmsh meshing | Semantic groups are designed for it; no adapter yet |
| CalculiX FEA | No adapter; only analytical screening exists today |
| Assembly and kinematics | Interfaces and mates are in the schema; no transform solver yet |
| Optimisation | The cache that makes it affordable exists; the optimiser does not |
| Optimisation loop | The orchestrator repairs failures; it does not yet improve a passing design |
| Web application | Not started |

### Deliberately out of scope for V1

CFD, nonlinear plasticity, fracture, certified fatigue life, topology
optimisation, CAM toolpaths, BIM, PCB design, organic modelling, and anything
resembling certification. See [scope](docs/architecture/system.md#scope).

---

## What Forge will not tell you

- That a design is safe. It reports what was checked, against what, under which
  assumptions, and what remains unverified.
- That a simulation result is correct because it converged. Convergence is
  necessary and nowhere near sufficient.
- That a material is "aluminium". Asking for a family name raises an error
  listing the specific grades available, because yield strength within that
  family varies by more than a factor of three.
- That an unapproved assumption is fine because everything else passed.

Simulation is not physical validation. Nothing here constitutes engineering
certification, and a part that matters should be tested.

---

## Repository layout

```
packages/
  forge_units/      dimensional algebra, intervals, three-valued logic   (stdlib only)
  forge_expr/       safe expressions, parameter graph                    (stdlib only)
  forge_ir/         the ForgeIR document model and feature graph         (stdlib only)
  forge_geom/       implicit kernel, rigorous measurement, meshing       (numpy)
  forge_kernel/     lineage, content-addressed incremental compilation   (numpy)
  forge_evidence/   evidence graph, gates, release decisions             (stdlib only)
  forge_analysis/   analytical checks and material records               (stdlib only)
  forge_pipeline/   the deterministic verification pipeline
  forge_models/     provider adapters, retry, budget, fixtures            (stdlib only)
  forge_roles/      the five roles, their prompts, pointer patching        (stdlib only)
  forge_orchestrator/
                    the design loop: state machine, repair, provenance
  forge_cli/        the `forge` command
examples/clevis/    the golden reference design
tests/              2013 tests including fault injection, replayed design runs
                    and 157 recorded real model answers
docs/               architecture, ADRs, developer setup, validation
```

Nine of the twelve packages depend on nothing but the standard library. That is
deliberate: everything that makes a numeric claim about a design bottoms out in
the trust core, so its dependency surface is kept as small as it can be.
([ADR-0002](docs/adr/0002-zero-dependency-trust-core.md))

---

## Documentation

- [Designing from a sentence](docs/user/designing.md) — the `forge design` loop
- [Your first project](docs/user/first-project.md) — the golden clevis, walked through
- [System architecture](docs/architecture/system.md) — trust zones, data flow, scope
- [ForgeIR language reference](docs/architecture/forgeir.md)
- [Evidence and gates](docs/architecture/evidence.md)
- [Developer setup](docs/developer/setup.md) — including Docker and WSL2
- [Architecture decision records](docs/adr/) — including
  [measurement bindings](docs/adr/0009-measurement-bindings.md),
  [patch-based repair](docs/adr/0010-patch-based-repair.md) and
  [reproducible model calls](docs/adr/0011-reproducible-model-calls.md)
- [Validation report](docs/validation/release-report.md) — what was tested and what was not
- [V1.1 backlog](docs/validation/backlog.md) — prioritised from evidence, not speculation
- [Security model](SECURITY.md)

---

## Licensing

Not yet decided. See [LICENSE-DECISION.md](LICENSE-DECISION.md) for the
considerations and what needs settling before any public release.
