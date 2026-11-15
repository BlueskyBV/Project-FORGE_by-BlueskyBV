# ADR-0030: Geometry libraries, file formats, and what is avoided

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

Stage 4b uses libraries for meshes, subdivision and file formats, and must
respect licences (Forge is Apache-2.0: GPL only in separate processes) and
patents. Versions and terms as found on 10 November 2026.

## Decision

**Meshes:** manifold3d 3.5 (Apache-2.0) for mesh booleans; trimesh 5.2
(MIT) for mesh files; lib3mf 2.5 (BSD) for 3MF, its beam-lattice extension
included; libigl 2.6's core (MPL-2.0) for winding numbers as a cross-check
of Forge's own (ADR-0024). A CI test fails if `igl.copyleft` or
`igl.triangle` (GPL and non-free modules in the same wheel) is ever imported.

**NURBS:** OpenCascade builds; Forge's own evaluator (ADR-0024) is the
oracle's. No third-party NURBS library is a truth.

**Subdivision (4b.13):** Forge's own Catmull-Clark evaluator is the truth.
OpenSubdiv 3.8 (the TOST licence, Pixar's modified Apache 2.0: no trademark
use) is the reference away from irregular points, through Forge's own small
binding to its Bfr API. **T-splines:** the core patent (US 7,274,364)
expired in March 2024, so T-junction refinement (analysis-suitable
T-splines, Bézier extraction) is allowed. **Avoided by design:** BYU's
US 10,249,086 (refinement round extraordinary points for G1 manufacturing
surfaces, by eigen-polyhedra; in force to about 2038), Autodesk's
US 9,269,189 (trim-free T-spline conversion) and its mesh-to-watertight
B-rep family. Forge's patches round irregular points use a different,
published construction (Loop and Schaefer's approximation, or Forge's own
fitter), chosen at 4b.13's start. A freedom-to-operate opinion is taken
before any commercial release; this is not legal advice.

**File formats:**
| Format | Read | Write |
|---|---|---|
| DXF, SVG | ezdxf 1.4 (MIT); into sketches as proposals, confirmed | ezdxf; re-opened by Forge's own reader (ADR-0032) |
| DWG | LibreDWG's `dwg2dxf` in a sandboxed separate process (GPL; untrusted input), then ezdxf; proposals only | R2000 by LibreDWG from Forge's DXF (stage 6), re-opened through `dwg2dxf` and Forge's DXF reader |
| IGES | OpenCascade, behind a lock (not thread-safe in 8.0) | OpenCascade (stage 6) |
| ACIS SAT | Forge's own reader of the published SAT 7.0 format; later versions refused; a proposal, confirmed (one reader), tested on files from other programs with a STEP of the same part | no |
| Parasolid x_t | Forge's own reader from Siemens' published XT format reference (its stated purpose is translators; schema 12006); later schema features refused, naming them; a proposal, confirmed, tested as SAT is | no: its acceptance test needs Parasolid itself (V2-stage4b.md, section 4) |
| JT | — | from ISO 14306 and Siemens' JT reference (whose terms allow writing JT and readers): tessellations and the JT B-rep segment (never the XT segment: V2-stage4b.md, section 4), re-opened by Forge's own JT reader, written apart from the writer, and compared with the part's STEP; FerroJT for the meshes only once its licence is confirmed (stage 6) |
| PCB | boards by STEP from the ECAD tool (KiCad's `kicad-cli pcb export step`); IDF 3.0 and IDX only once their specifications' terms are confirmed | no |
| STL, OBJ, PLY, 3MF | trimesh and lib3mf to build; the trust core's own readers to judge | STL, 3MF as today; OBJ and glTF by OpenCascade's `RWObj` and `RWGltf` |

## Consequences

Every format Forge reads has a stated route and a stated limit; nothing is
read by a tool whose licence or terms are unknown.
