# System architecture

## Two trust zones

Forge divides into a **deterministic zone** and a **probabilistic zone**, and the
boundary between them is the most important line in the system.

```
        probabilistic                          deterministic
  ┌───────────────────────────┐        ┌──────────────────────────────┐
  │ brief interpretation      │        │ schema validation            │
  │ requirements extraction   │        │ unit and dimension checking  │
  │ clarification ranking     │  ───▶  │ expression evaluation        │
  │ concept synthesis         │  IR    │ CAD compilation              │
  │ ForgeIR proposal          │        │ geometry measurement         │
  │ simulation planning       │        │ collision and clearance      │
  │ failure explanation       │  ◀───  │ meshing and solving          │
  │ revision proposal         │ result │ analytical equations         │
  │ report drafting           │        │ gate evaluation              │
  └───────────────────────────┘        │ hashing and provenance       │
                                       └──────────────────────────────┘
```

A language model may propose that a gate should exist, and may explain what a
result means. **It may not produce the number.** Nothing in the probabilistic
zone can write to an evidence node's `result` field, and nothing there can change
a status. The `Method` on every evidence node records which zone produced it, and
`EvidenceGraph.overall_status()` excludes soft methods from the roll-up entirely.

Both zones are now built. The probabilistic zone is five typed roles behind a
provider-neutral interface: brief interpretation, requirements extraction,
clarification ranking, ForgeIR proposal, and failure analysis. Each declares an
output schema, has it enforced at the transport by forced tool use, and is then
validated *semantically* — a threshold must carry a unit, a referenced identifier
must exist, a document must compile — before anything downstream sees it.

The boundary is enforced by what the roles can express, not by discipline. A role
returns a ForgeIR document or a set of JSON patches; neither can name an evidence
node, a status or a measured result. Everything a report claims about a design is
produced by the deterministic zone measuring the geometry the document describes.

Three things cross the boundary in the other direction, all of them results: a
compiler diagnostic with its pointer, a failing gate with what was measured
against what, and a slice of the document the diagnostic names. The failure
analyst sees those, and nothing else about the run.

## Data flow

```
brief ──▶ requirements ──▶ ForgeIR document
                                │
                                ▼
                    ┌───────────────────────┐
                    │  parameter resolution │  units, bounds, cycles
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │  feature compilation  │  content-addressed, incremental
                    └───────────┬───────────┘
                                ▼
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
   ┌────────────────────┐              ┌────────────────────┐
   │ implicit backend   │              │ exact backend      │  (planned)
   │ SDF, NumPy only    │              │ OpenCascade, B-Rep │
   └─────────┬──────────┘              └─────────┬──────────┘
             │                                   │
             └──────────────┬────────────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ semantic geometry    │  lineage tokens, burial check
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ measurement          │  rigorous enclosures
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ gates → evidence     │  three-valued, immutable
                 └──────────┬───────────┘
                            ▼
                   release decision + report
```

## Package dependencies

```
forge_units      (stdlib)
    ▲
    ├── forge_expr     (stdlib)
    │       ▲
    │       └── forge_ir      (stdlib)
    │               ▲
    ├── forge_geom   (numpy) ─┤
    │       ▲                 │
    │       └── forge_kernel ─┘
    │               ▲
    ├── forge_evidence (stdlib)
    ├── forge_analysis (stdlib)
    │       ▲
    │       └── forge_pipeline
    │                   ▲
    │                   └── forge_cli
```

No cycles. Six of nine packages are standard-library only.

## Failure policy

**Fail closed, everywhere.**

- A feature that cannot be built stops the compile and names the feature, the
  parameter and what the backend said. It is never skipped so the build can
  continue with a part that is missing a hole.
- A parameter outside its declared bounds refuses to compile. Bounds are part of
  the design contract, not a suggestion.
- An empty solid is a compilation failure, never a part with zero mass.
- A semantic reference that no longer resolves raises, and never falls back to a
  nearest match.
- A gate with no measurement is `NOT_TESTED`, not `PASS`.
- An unapproved high-risk assumption blocks release regardless of gate results.

## Scope

### In scope for V1

Mechanical parts and assemblies of roughly 1–20 unique components: brackets,
mounts, plates, flanges, shafts, spacers, bushings, housings, covers, hubs,
pulleys, simple gears, handles, clamps, clevises and linkage members. Processes:
FDM printing, simple CNC milling and turning, laser and waterjet profiles, and
conventional drilled and fastened fabrication.

### Architected, not built

OpenCascade B-Rep backend, STEP export, Fusion add-in, Gmsh meshing, CalculiX
structural and thermal analysis, assembly kinematics, multi-fidelity
optimisation, the web application.

### Out of scope, deliberately

Production CFD, nonlinear plasticity, fracture, impact, composite layup,
certified fatigue life, production-grade topology optimisation, CAM toolpaths,
native SolidWorks/CATIA/Creo/NX feature trees, BIM, PCB design, organic
modelling, animation, and any form of certification.

Domain packs are the extension mechanism. A pack contributes schema extensions,
feature kinds, study adapters, validators, process rules, golden tests and
documentation. **A pack may not weaken core evidence rules or sandbox rules.**

## Security

Covered in [SECURITY.md](../../SECURITY.md). The short version: imported files,
retrieved documents and model output are untrusted data. The expression
allowlist is a structural boundary rather than a heuristic — `eval` is never
called, so there is no sandbox to escape. Generated code, when the escape hatch
is used, runs in a network-disabled non-root container and never in the API or
orchestrator process.
