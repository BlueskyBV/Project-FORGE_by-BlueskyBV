# ADR-0022: OpenCascade 8.0.1, through OCP, pinned exactly

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

Stage 4 was built and counted on OpenCascade 7.9.3 (`cadquery-ocp-novtk`
7.9.3.1.1, pinned in `forge_occ`). Stage 4b's plan asked 4b.0a to choose
between 7.9.3 and 8.0 ([V2-stage4b.md](../V2-stage4b.md), 2.1).

As of 10 November 2026 (research kept in the 4b.0a notes):

- OCCT 8.0.0 was released on 7 May 2026, after three betas and five
  release candidates, with more than 500 changes since 7.9.0; 8.0.1, a
  maintenance release keeping 8.0's API and ABI, on 30 July 2026. Licence
  unchanged: LGPL-2.1 with the OCCT exception.
- `cadquery-ocp-novtk` 8.0.1.1.0 (5 October 2026) wraps 8.0.1, with pip
  wheels for CPython 3.11 to 3.14 on Windows x64, Linux x86-64 and aarch64
  and macOS. build123d 0.13 already requires it.
- What 8.0 gives Forge: boolean and fillet hangs and crashes fixed (the
  fuse of lofts, periodic B-spline sections, `MakePipeShell`), interference
  by BVH, faster B-spline evaluation and booleans (about 17 to 20% in
  8.0.1), fillet state per thread; new modules Forge's plan names:
  `GeomFill_Gordon` (Gordon surfaces from curve networks: revision 4 noted
  it missing from 7.9.3), `TKHelix`, `BRepGraph` (a graph of the topology:
  4b.0d2's contracts and 4b.17's recognition), `GeomProp` (local
  properties), per-type bounding boxes.
- What it costs: API breaks (C++17, `Standard_Failure` from
  `std::exception`, collections' `Size()`, final `Geom_*` leaves, handles
  returned by value) and numeric shifts in booleans and fillets, so golden
  values move. IGES reading is not thread-safe.

## Decision

Forge moves to **OCCT 8.0.1 through `cadquery-ocp-novtk==8.0.1.1.0`**,
pinned exactly as today (`forge_occ.PIN`), with no VTK. It calls OCP
directly; nothing in Forge depends on CadQuery or build123d.

The switch is **4b.0a′, its own step**, as the plan requires, in two
sub-steps: first `forge_occ` ported to 8.0's API on today's Python with
nothing else changed, and every stage 3 and stage 4 test, every kept
regression and stage 4's whole counted run (10,000 seeds) replayed on the
unrefactored code (about five days at today's speed, ADR-0027); then
CPython 3.14 (ADR-0023), replayed as ADR-0023 says. Each difference is
listed and explained before 4b.0b's code is proven or merged. A later 8.0.x is adopted only after the same
replay passes. IGES calls are serialised behind a lock.

8.0's new modules are used as **alternatives proven equal**, never as
truths: `GeomFill_Gordon` beside Forge's own Gordon surfaces (4b.0 item
13), `BRepGraph` inside the compiler and recognition (the oracle keeps its
own topology), `TKHelix` beside Forge's helix.

## Consequences

- The newest kernel, with its robustness fixes, on Windows and Linux, from
  the first line of 4b code: nothing built in 4b is ported later.
- One step of porting and replay (about a day of work; the replay's compute
  per ADR-0027).
- Golden numbers that move are explained one by one, never re-baselined in
  bulk.

## Alternatives

- **Stay on 7.9.3:** no porting now, but every 4b kind would be written
  against an API about to be left behind, and Gordon surfaces would be
  missing. Rejected.
- **pythonocc-core 8.0.1:** conda only, LGPL-3, a different binding style.
  Rejected.
