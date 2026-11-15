# ADR-0033: External programs: one runner, separate processes, pinned

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

Stage 4b uses programs Forge must not import (GPL) or should not (crash
isolation, clashing OpenCascade builds): gmsh, Netgen and NGSolve, CalculiX,
code_aster, OpenFOAM, SU2, OpenRadioss, LibreDWG, `slvs`, `dolfinx_eqlb`.

## Decision

- **One runner** (item 26): each program a separate process with its inputs
  as files (STEP, BREP, meshes, decks), a timeout, no network, its stdout,
  stderr and exit code kept with the run, its version recorded in the
  run's evidence and the cache key (ADR-0026). A program's failure is
  UNABLE with its reason, never a guess.
- **Pinned versions,** updated only with a replay of the regressions and
  the analysis benchmarks.
- **Where each runs:** gmsh, Netgen and NGSolve, CalculiX, SU2, LibreDWG
  and `slvs` natively on Windows and Linux; code_aster, OpenFOAM and
  OpenRadioss in Docker (on Windows through WSL2; OpenRadioss's AGPL asks
  nothing more of a program run locally and unmodified). On the laptop that means Docker Desktop
  with WSL2, installed once, for those three only.
- **Licences:** each program's licence and source shipped or offered with
  the Docker image (GPL's obligations for binaries we distribute); Forge's
  small worker scripts that import a GPL library are themselves GPL-3,
  kept apart from Forge's Apache-2.0 packages.

## Consequences

Every external number is reproducible from recorded inputs and versions,
and no licence reaches Forge's own code.
