# ADR-0029: The analysis stack: two of everything, and what may be VERIFIED

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a (for 4b.14 to
4b.16; the protocols, items 25 and 26, are built in 4b.0)

## Context

Revision 5's rule: no computed number decides VERIFIED unless two
independent programs, each with its own setup and mesher, agree; the loads
are checked against the confirmed spec; the analysed shape is the shipped
part; and the error is under a guaranteed bound (V2-stage4b.md 3.2, item
18). The research of 10 November 2026 found which tools exist, and that
guaranteed bounds exist in practice only for energy-norm quantities.

## Decision

**Meshers:** gmsh 4.15 and Netgen 6.2 (independent algorithms and code),
each in a worker process (gmsh is GPL; Netgen's bundled OpenCascade must not
meet Forge's in one process); MMG (through mmgpy) for adaptation; fTetWild
only to repair dirty imported geometry, never for a verifying mesh.

**Structural and thermal, linear:** two pipelines, gmsh → CalculiX 2.23 and
Netgen → NGSolve 6.2, sharing no solver code. Linear static, modal and
thermal in both; linear buckling in CalculiX, and in NGSolve from Forge's
own geometric stiffness. scikit-fem (BSD) in process for small checks and
manufactured solutions.

**Nonlinear and contact:** CalculiX and code_aster (stable 17.x, in Docker),
each a separate program.

**Flow:** OpenFOAM v2606 (openfoam.com) with snappyHexMesh, and SU2 8.5 on
gmsh meshes: independent discretisations; for laminar internal flow, a
third, NGSolve's Navier-Stokes.

**Impact:** OpenRadioss (AGPL, a separate program, run locally) and
code_aster's dynamics.

**What may end VERIFIED** (item 18, the one list; a requirement stated as
conformance to a standard's calculation, such as DIN 743's safety factors,
is 4b.14's and may end VERIFIED, being what was asked; the list below is
for physical outcomes decided by analysis):
- **Steady linear conduction:** energy-norm quantities and region averages
  by an adjoint, once Forge's own Prager-Synge equilibrated-flux estimator
  gives a guaranteed bound in 3D that includes the mesh's departure from
  the part and the data's approximation (4b.15; cross-checked in 2D
  against `dolfinx_eqlb`, run apart as it is GPL).
- **Steady linear elasticity:** the same quantities (compliance,
  stiffness, region averages), once Forge's own 3D stress equilibration
  gives such a bound: research-grade, built and proven in 4b.15; until
  then VERIFIED EXCEPT, naming the method.
- **Never VERIFIED, always VERIFIED EXCEPT naming the method:** point and
  peak values (stress, deflection at a point, the highest temperature;
  unbounded at re-entrant corners, taken at a stated distance), transient
  and radiative heat, modal and buckling (guaranteed lower bounds are 2D
  research only; a conforming upper bound is the unsafe side for
  buckling), fatigue, plasticity, contact, impact and all flow (turbulence
  models share their modelling error even when two codes agree), and any
  result only one program gives.

**Optimisation:** Forge's own SIMP (density filter, Heaviside projection) on
scikit-fem or NGSolve, driven by NLopt's MMA and CCSA built without the
LGPL Luksan code, or pyMOTO (MIT); level sets in the implicit kernel. The
optimised field is a proposal (item 28).

**Verification of the tools:** Forge's own SymPy generator of manufactured
solutions (exact on any geometry) and order-of-accuracy tests; closed forms
(Lamé, Kirsch, Timoshenko, Euler, de Vahl Davis, Poiseuille, Ghia's cavity,
NASA's turbulence-model cases); NAFEMS P18 bought for internal targets,
its documents kept out of the repository.

## Consequences

The analysis Forge does is as strong as open tools allow, and its ending
says exactly how strong: a guaranteed bound where mathematics gives one, a
named method where it doesn't.
