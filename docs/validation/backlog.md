# V1.1 backlog

Ordered by evidence from what was actually built, not by feature wishlist. Each
item says *why now* — what the day-one work showed about its priority.

> **Item 5 has been built.** The AI role layer shipped alongside the kernel, so
> it is kept below as a record of the reasoning and marked with what it actually
> became. Its remaining work now leads the list as item 0.

## 0. A live provider run, and what it will change

**Why now.** This is the only part of the loop that has never executed. Every
test replays a recorded response, which proves the plumbing, the repair path and
the refusals — and proves nothing at all about whether a model, given the real
generated prompts, produces a good document. That question has exactly one way to
be answered.

What to look at when it runs, in order of what would change the design:

1. **Does the designer use the feature vocabulary, or fight it?** Reaching for
   `extrude` where `box` would do, or building a bore from `subtract` instead of
   `hole`, means the guide is explaining rather than teaching.
2. **Are the requirements bound to measurements?** An unbound numeric
   requirement is reported `NOT_TESTED` and is a prompt failure, not a model one.
3. **What does the repair loop actually see?** The failures worth counting are
   the ones the fixtures could not anticipate.
4. **Does it invent anything?** The refusals are enforced downstream, so an
   invented load shows up as an assumption nobody made — which is exactly what
   should be looked for first.

Record it (`--record`), because the first real run is worth more as a fixture
library than as a transcript.

## 1. OpenCascade backend and STEP export

**Why now.** The single largest gap between this and a usable product. Without
B-Rep there is no STEP, so no exchange with any other CAD system, and no path to
the Fusion bridge. The adapter boundary is already defined and already has two
consumers' worth of design pressure behind it; what is missing is the
implementation.

The cross-backend gate (`GEOM_CROSS_BACKEND`) already exists and currently
compares the octree enclosure against a surface mesh. Pointing it at a second
*kernel* is where it starts earning its keep.

## 2. Gmsh and CalculiX adapters, with mesh convergence

**Why now.** The analytical library is in place and validated against textbook
cases, which means there is finally something to check a finite-element result
*against*. Building FEA first would have meant trusting it; building it second
means cross-checking it.

Non-negotiable, from the specification and from experience: a result that changes
materially between coarse, medium and fine meshes is `INCONCLUSIVE`, never
`PASS`. The three-valued machinery for that already exists.

## 3. Persistent content-addressed artifact store

**Why now.** `forge sweep` measured 62–80% of features avoided on a single
parameter sweep, in-process. The number that matters for a real optimisation
campaign is across workers and across sessions, and that needs persistence. This
is also the prerequisite for distributing the optimiser at all.

## 4. Assembly, interfaces and kinematics

**Why now.** Interfaces already exist in the schema and already carry fit class,
allowable motion and load transfer. The clevis has a `pivot_port` that means
something and nothing consumes it. The transform solver, degrees-of-freedom
diagnostics and swept collision checking are what make that port do work.

## 5. The AI role layer — **built**

**Why it was fifth, and why it shipped anyway.** Placing it after the
deterministic core was the right call: the roles are only useful because there is
now something that can check their output. That ordering held — the kernel was
finished first — and the layer then followed directly, because everything it
needed was in place.

What it became: five typed roles, provider-neutral, structured output enforced by
forced tool use and then validated semantically, patch-based bounded repair
(ADR-0010), a fixture provider that makes the whole loop testable offline
(ADR-0011), and a `forge design` command. The contract this item asked for is
tested: an underspecified brief produces questions and no design, and proceeding
anyway produces an unapproved high-risk assumption rather than a value.

What is still missing is in item 0, and in these:

- **Multi-component designs.** The orchestrator drives `components[0]`. The
  document model carries several.
- **Answers that reopen a run in place.** Today answering means re-running with
  `--answer`, which is honest and stateless but re-pays for the earlier calls.
- **A cheaper first pass.** Interpretation and requirements could run on a
  smaller model than the designer; the provider interface allows it and nothing
  uses it yet.

## 6. Multi-fidelity optimiser

**Why now.** Everything it needs is present — bounded optimisable parameters,
fast screening geometry, caching, and gates that can reject a candidate. What is
missing is the search itself, Pareto tracking, and finalist revalidation at
higher fidelity.

## 7. Face splitting in the lineage system

**Why now.** A known, documented hole (ADR-0003, limitation 4). It will start
mattering as soon as patterns and mirrors are used on referenced geometry, which
item 4 will drive.

## 8. File ingestion hardening

**Why now.** SECURITY.md designs it and nothing implements it. It becomes
load-bearing the moment users can import STEP, which item 1 enables.

## 9. Web workspace

**Why now, and deliberately last among the substantial items.** The
specification is right that a visually impressive frontend over a fictional
engineering core is the failure mode to avoid. The core is no longer fictional,
so the workspace can now show real evidence.

---

## Smaller, worth doing

- **Parallel feature compilation.** The DAG already supports it; nothing uses it.
- **GPU field evaluation** for the implicit kernel, once an optimisation campaign
  exists to justify it by measurement.
- **A cheap local model for the interpreter role**, so an underspecified brief
  costs almost nothing to bounce back as questions.
- **A `forge diff` command** showing which evidence a proposed parameter change
  would invalidate. `dependents_of` already computes exactly this.
- **DFM rule packs** for FDM and CNC beyond minimum wall thickness.
- **Tolerance sampling** — Monte Carlo stack-ups. Interval arithmetic already
  gives a conservative outer bound; sampling gives the distribution inside it.

## Explicitly not planned for V1.1

CFD, nonlinear analysis, CAM, BIM, PCB, organic modelling, and certification of
any kind. These are domain packs or non-goals, per ADR-0001 and the scope
section of the architecture.
