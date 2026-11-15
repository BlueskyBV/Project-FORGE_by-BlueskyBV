# Forge V2, stage 4b: the scope audit

Status: an audit, 10 November 2026, input to 4b.0a's re-audit ([V2-stage4b.md](V2-stage4b.md), 2.1). It asks whether stage 4b, with the scope the owner agreed on 10 November (T-spline and subdivision modelling; G2 roundings along edges, G2 corner blends with setbacks and G2 on freeform faces; scan-to-CAD deferred), takes Forge to the peak of what OpenCascade, Forge's own geometry, its implicit kernel and open-source libraries can do, so that what it still can't do is missing only for want of a proprietary kernel, format or licence. Each capability of professional CAD (SolidWorks, NX, Creo, CATIA, Fusion, Onshape) is given its status in the plan and, where it is outside or missing, whether a constraint of technology or a choice keeps it out. Nothing here is decided until 4b.0a writes it into V2-stage4b.md.

## 1. The most important gaps for single-part power and autonomy

1. **Engineering design calculations: MISSING, CHOICE.** Forge records "loads and margins" (plan §4.1) and checks strength afterwards (plan §4.7 item 6; stage 6 FEA). Nothing in the plan works out a shaft, bolt, spring, gear, key, press fit, beam, plate or wall thickness from the loads, and that sizing is what makes Forge act as "a true engineer". **How:** a registry of pinned closed-form calculators: DIN 743, VDI 2230, EN 13906, ISO 6336/AGMA 2001, ISO 281, DIN 6892, DIN 7190, Roark, Euler/Johnson buckling and weld throat. Each is transcribed twice, the way item 20's tables are. Values enter the spec through the existing "derived, from a formula shown to you" provenance. This also needs a material table with E, ν, yield, endurance limit and CTE; 4b.10 has density only.
2. **Forge's own freeform offsets: MISSING, CHOICE.** Section 3.1 names "offsets and shells of freeform faces" as an OpenCascade weak spot, then still says "OpenCascade's offset only for freeform faces". Three things depend on this: the agreed G2 roundings on freeform faces (their spine is the intersection of offset faces), shelled organic housings, and thickening. **How:** sample the exact nearest-point offset, fit a B-spline within item 9's cap, and trim or round locally past the certified curvature bound (Piegl–Tiller, Elber).
3. **G2 and class-A (G3) surfacing: MISSING, CHOICE.** Boundary surfaces, N-sided fills and loft ends allow tangency only (4b.5, 4b.1). There is no G3, no bridge or blend surfaces or curves, and no curvature, zebra or isophote analysis or fairness measure. **How:** Coons/Gordon with cross-boundary derivative conditions (biquintic or Gregory); the G2 constraint order of `BRepFill_Filling`/`GeomPlate`; matching control-point rows for G3; third-derivative checks in the trust core's STEP reader (item 24); numeric isophote and curvature-sign checks.
4. **Topology optimisation and generative design: MISSING, CHOICE.** Stage 5 regions are "shapes for a purpose". A model guesses them, and they are checked only geometrically (stage 5 §4.3): no loads, no stiffness. **How:** SIMP on a voxel or tetrahedral FE mesh (scikit-fem, with the MMA optimiser from NLopt), or level sets in Forge's SDF kernel. Fixed items act as keep-outs, with manufacturing constraints (overhang, extrusion direction, symmetry, minimum member size). The result ships as a mesh-only part (item 22) or fills a region.
5. **Simulation beyond linear static: OUTSIDE/MISSING, CHOICE.** Modal and buckling analysis are named nowhere. Thermal, fatigue, nonlinear and dynamics are "added after V2" (4b §4). Stage 6's FEA is a pass/fail check only. **How:** modal, buckling and steady thermal run on the same gmsh + scikit-fem stack (SciPy `eigsh`). Fatigue comes from linear stress with S-N/Goodman. CalculiX (GPL, run as a separate process) handles nonlinear and contact, and doubles as an independent second solver in the spirit of R2.
6. **Mesh import and mixed mesh + B-rep work: MISSING, CHOICE.** 4b.8 imports STEP only, so "design a holder for this STL" can't be done. This is separate from the deferred scan-to-CAD. **How:** trimesh or lib3mf readers; manifold3d for booleans and repair; signed distance (libigl winding numbers) into the implicit kernel; the mesh-only ending (item 22).
7. **Other imports: MISSING, CHOICE.**
   - IGES: OpenCascade's `IGESControl_Reader`, plus support for its entities in the trust core's reader.
   - ACIS SAT up to about version 7: the format is published, and the FreeCAD InventorLoader add-on (GPL) can serve as a reference.
   - AP242 semantic PMI import: OpenCascade XCAF.
   - IDF 3.0 / IDX board import (open specs), for designing enclosures.
8. **Feature recognition and live rules on imported bodies: MISSING, CHOICE.** 4b.8 edits imported faces only "bounded". It doesn't recognise holes, fillets, chamfers or patterns and turn them into exact spec items. It doesn't keep faces coplanar, concentric or tangent when moving them. **How:** a recogniser over the face adjacency graph (Analysis Situs as a reference), plus a solver for face relations.
9. **Design studies, optimisation and rules: MISSING, CHOICE.** Items 8 and 19 give parameters, equations and configurations. There is no "minimise mass subject to stress, deflection or frequency" and no conditional rules (if/then suppression, a rule choosing a kind). **How:** scipy.optimize or Optuna over the parameter graph, using stage 7's deterministic resize and stage 6's FEA. Rules become typed expressions resolved before confirmation and shown.
10. **Breadth of drive elements and standards: too narrow, CHOICE (tables and formulas).**
    - Gears: cycloidal discs, worm wheels, herringbone, face gears, Geneva wheels, ratchets.
    - Springs: extension, torsion, disc and wave springs.
    - Belts: V-belt grooves and named timing-belt profiles.
    - Threads: buttress, round, Whitworth, UNJ/MJ.
    - Other: Morse/SK/HSK tapers, drill size series, inch clearance holes.
11. **Mold tooling and casting/forging: MISSING, CHOICE.** Runners, gates, cooling channels, ejectors and the mold base. Machining allowance (Forge's face offsets), cast and machined states (configurations or derived products), core prints and forging flash.
12. **Plastic and printed-part features: MISSING, CHOICE.** Living hinges, heat stakes, crush ribs, energy directors, and annular or torsion snaps with strain checks. Displacement textures and conformal or stochastic lattices in the implicit kernel.

**Bottom line.** Only two things are truly blocked by technology:
- the native proprietary formats (SLDPRT, F3D, NX/Creo PRT, CATPart, IPT, and current ACIS/ShapeManager binaries);
- Parasolid-level robustness on arbitrary foreign freeform geometry, which section 3.1 itself concedes.

Everything else that is missing or outside is a planning choice. Section 4's reason for most entries is "can be added after V2", which is about order, not technology. Its one claimed constraint, "Parasolid and JT export (no licence)", is overstated:
- JT is a published ISO standard (ISO 14306), and writing a published format needs no licence.
- Siemens publishes an XT format reference (its terms to be checked). So the real barrier for x_t is writing a large converter yourself with no open library, not a licence.

## 2. The catalogue

Key: "4b" is V2-stage4b.md, "item N" is 4b §2.2 item N, "plan" is V2-plan.md, S5/S6/S7/S8 are stages 5–8 (plan §8), "§4" is 4b's outside list. AGREED means the owner moved it into 4b but the document still says otherwise.

**Sketching and constraints**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Lines, arcs, circles, ellipses, conics, slots, polygons, text, offsets, projections, sketch fillets and chamfers, regions, construction geometry, on any plane or face | IN-4B (item 8) | – | |
| Splines through points with tangents; equation-driven curves | IN-4B (item 8) | – | interpolating splines only |
| Control-point NURBS splines (weights), G2 "style" splines, fit within a tolerance | MISSING | CHOICE: own NURBS code; `GeomAPI_PointsToBSpline` | |
| 2D constraint solver, degrees of freedom, branch signature | IN-4B (item 8) | – | the constraint set isn't listed |
| Curvature (G2) constraint; spline-handle constraints | MISSING | CHOICE: own solver equations | |
| Sketch mirror, sketch patterns, trim/extend/split, blocks | MISSING | CHOICE: easy | |
| DXF/SVG into a sketch | IN-4B (item 8) | – | |
| Trace an image | MISSING | CHOICE: OpenCV contours + spline fit | low priority |
| 3D sketches with constraints | IN-4B (item 8) | – | five constraint types only |
| 3D curves: through points, projected, composite, intersection, helix, spiral, split lines | IN-4B (item 8) | – | |
| Isoparametric, silhouette, offset-on-surface and geodesic curves; G1–G3 bridge curves; curve fairing | MISSING | CHOICE: OpenCascade iso-curves; own geodesics | silhouette curves feed 4b.7's parting line |
| Datums: planes, axes, points, coordinate systems | IN-4B (item 8) | – | |

**Solid features**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Extrude and cut, thin, every depth mode, drafted | IN-4B (4b.1, item 2) | – | two directions with independent end conditions not stated |
| Revolve at any angle, up to a face | IN-4B (4b.1) | – | |
| Thin revolve, sweep, loft | MISSING | CHOICE: Forge's 2D offset of the profile | |
| Sweep: rotation-minimising/fixed/binormal frames, twist and scale laws, guides, variable section, solid tool | IN-4B (4b.1) | – | no "normal to a surface" orientation |
| Loft: N sections, ruled or smooth, rails, centre line, closed, point ends, end tangency | IN-4B (4b.1) | – | no G2 end conditions |
| Boundary boss and cut | IN-4B (4b.5) | – | |
| Helix, coil, spring | IN-4B (4b.1) | – | compression springs only |
| Rib/web, dome, torus, wedge | IN-4B (4b.1) | – | |
| Wrap, emboss, deboss | IN-4B (4b.1) | – | |
| Gears, splines, sprockets, pulleys, cams, knurl | IN-4B (4b.1) | – | list is narrow |
| Flex (bend, twist, taper, stretch); deform (point, curve to curve) | IN-4B (4b.1, 4b.5) | – | |
| Cage (FFD) deformation, morph, wrapping features onto a surface | MISSING | CHOICE: defined by properties (item 13) | |
| 3D displacement textures | MISSING | CHOICE: implicit kernel, shipped mesh-only | |

**Roundings, chamfers, shell, draft, booleans**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Constant, variable, elliptical, chordal, face, full round, hold line, rule selections, remove a rounding | IN-4B (4b.3, 3.1) | – | |
| G2 roundings along edges between analytic faces | IN-4B (3.1) | – | |
| G2 corner blends with setbacks; G2 on freeform faces | AGREED | – | 3.1 and §4 still list them as outside; depends on gap 2 |
| Conic (rho) section; overflow/spill-over control; several radii along a chain | MISSING | CHOICE: a section law in Forge's rolling ball; trim against neighbouring faces | |
| Roundings on imported freeform edges | implied (4b.8) | – | depends on gap 2 |
| Chamfer: distance, two distances, distance and angle, face to face, vertex | IN-4B (4b.3) | – | corner treatment not stated |
| Shell: any body, inward or outward, several thicknesses, open faces | IN-4B (4b.3) | – | freeform faces left to OpenCascade (3.1) |
| Shell with a thickness law | MISSING | CHOICE: own offsets | |
| Draft: neutral plane, parting line, step | IN-4B (4b.3) | – | |
| Variable-angle draft, draft both sides of a parting line, draft on freeform faces | MISSING | CHOICE: item 5's construction with an angle law | |
| Offset a face on a native part (machining stock) | MISSING | CHOICE: 3.1's face offsets | |
| Remove all features under a size (defeaturing) | MISSING | CHOICE: `BRepAlgoAPI_Defeaturing` + item 12's rules | |
| Booleans, keep regions, split, indent, cut by a body, scale, move/copy | IN-4B (4b.3) | – | |

**Surfacing (class-A, freeform, subdivision)**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Extruded, revolved, swept, lofted, ruled, planar, radiate, offset surfaces | IN-4B (4b.5) | – | |
| Boundary surfaces from 2–4 curves (Coons/Gordon); N-sided fills | IN-4B (4b.5, item 13) | – | tangency (G1) only |
| G2 conditions on boundaries, fills and loft ends | MISSING | CHOICE: biquintic/Gregory patches; `GeomPlate` G2 | |
| G3 construction and check | MISSING | CHOICE: control-point row matching | |
| G0–G2 continuity check | IN-4B (4b.0d1, 4b.5) | – | |
| Curvature combs and maps, zebra, isophote and highlight lines | MISSING | CHOICE: `GeomLProp`; images for the visual review | |
| Knit, trim, untrim, extend, delete hole, replace face, cut with a surface, mid-surface, thicken, split, surface to solid, flatten | IN-4B (4b.5) | – | extend and trim modes not stated |
| Bridge or blend surface (G1/G2) between surfaces | MISSING | CHOICE: own Hermite or rolling-ball bridge | 4b.3's face rounding is only a partial substitute |
| Variable-distance offset surface | MISSING | CHOICE: own offset construction | |
| Rebuild, fair, match edge to edge, control-point sculpting | MISSING | CHOICE: least-squares fit and energy fairing, defined by properties | |
| Developable surface between two curves | MISSING | CHOICE: own ruling search | low priority |
| T-spline/SubD modelling and SubD to B-rep | AGREED | – | §4 still lists it as outside; OpenSubdiv (Apache-2.0) to evaluate the limit surface |

**Direct/synchronous modelling**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Move, replace, offset, delete faces of imported bodies | IN-4B (4b.8, bounded) | – | |
| Delete a face and heal, on Forge's own features | IN-4B (4b.3) | – | |
| Editing native parts | LATER S7 | – | spec edits play the role of push/pull |
| Live rules (keep coplanar, concentric, tangent, symmetric) | MISSING | CHOICE: own solver for face relations; SolveSpace's solver (GPL, separate process) | the pros' solver (D-Cubed) is proprietary but not needed |
| Feature recognition on dumb solids | MISSING | CHOICE: recogniser over the face adjacency graph | |

**Multibody and booleans**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Solid, sheet and wire bodies; scope; topology per body | IN-4B (item 7) | – | |
| Derived, inserted and mirrored parts | IN-4B (4b.8) | – | |
| Bodies saved as separate parts | LATER S8 | – | |
| Clash check between bodies of one part | not stated | CHOICE: `BRepAlgoAPI_Common` | |
| Simplified envelope ("shrinkwrap") | MISSING | CHOICE: SDF closing | low priority |

**Patterns and mirrors**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Linear, grid, circular, along a curve, at sketch points, from a table, fill, chain, face, varying, skipped copies, nested; mirror | IN-4B (4b.4) | – | |
| UV or geodesic patterns on a freeform face, spiral patterns, spacing driven by a field | not stated | CHOICE: item 3's placeable-face protocol | "face patterns" is vague |

**Parameters, configurations, rules (KBE)**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Named parameters and equations | IN-4B (item 8) | – | |
| Configurations | IN-4B (item 19, 4b.8) | – | |
| Design tables from a spreadsheet or CSV | MISSING | CHOICE: easy | |
| User-defined features | IN-4B (item 20) | – | |
| Families | LATER S7 | – | |
| Conditional rules, checks, reactions | MISSING | CHOICE: typed expressions in the spec | |
| Design studies, parameter optimisation | MISSING | CHOICE: SciPy/Optuna | |
| Cross-part parameters | LATER S8 | – | |
| Requirements | IN-4B (4b.10) | – | mass properties only |

**Sheet metal**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Flanges, hems, jog, sketched and lofted bends, cross break, rip, tab and slot, gussets, reliefs, corners, normal cut, 4 forming tools, convert a solid, unfold/fold, gauge, K-factor and bend tables, flat-pattern DXF | IN-4B (4b.6) | – | |
| Flanged holes, self-clinching hardware holes, more forming tools | MISSING | CHOICE: composites (item 20) | |
| Bend sequence and press-brake collision | MISSING | CHOICE: own search | stage 6 has rules only |
| Tube bending (LRA/YBC, die tables) | MISSING | CHOICE: sweep + bend tables | |

**Weldments**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Members from EN tables, corners, trim, gussets, end caps, beads, sub-weldments, cut list | IN-4B (4b.7) | – | |
| AISC, JIS, aluminium T-slot profiles | MISSING | CHOICE: tables | |
| Weld preparation bevels, weld symbols | MISSING | CHOICE: ISO 9692 tables; symbols in the S6 drawing | |

**Mold, casting, forging**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Draft analysis, undercuts, parting line and surfaces, shut-off, interlocks, core/cavity, side cores, lifters, shrinkage, wall thickness | IN-4B (4b.7) | – | |
| Runners, gates, sprues, cooling, ejectors, mold base, EDM electrodes | MISSING | CHOICE: sweeps and composites | |
| Mold-flow simulation | MISSING | CHOICE (research-grade; OpenFOAM) | low priority |
| Machining allowance, cast and machined states, core prints, forging flash | MISSING | CHOICE: face offsets + configurations | |

**Plastic part features**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Mounting boss, snap hook and groove, lip and groove, vent | IN-4B (4b.5a) | – | |
| Living hinge, heat stakes, crush ribs, energy directors, annular and torsion snaps | MISSING | CHOICE: composites | |
| Snap-fit strain; rib-to-wall rules | MISSING / LATER S6 | CHOICE: closed-form strain | |

**Holes, threads, standard features**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Hole wizard and its tables; modelled and cosmetic threads; O-ring, retaining-ring, undercut, centre hole, keyway, T-slot, dovetail | IN-4B (4b.2) | – | |
| Heat-set insert bores, nut traps, bearing seats | plan §4.1; LATER S6 | – | |
| Buttress, round, Whitworth, UNJ/MJ, NPSM threads; thread-forming screws for plastics; wire-thread insert holes; drill series; ASME B18.2.8 clearance holes | MISSING | CHOICE: tables | |
| Morse/SK/HSK tapers, shaft ends, wrench flats, lock-nut grooves, V-belt grooves | MISSING | CHOICE: tables | |

**Mesh and mixed mesh + B-rep**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Mixed parts by mesh boolean (manifold3d); mesh-only endings | IN-4B (4b.9, item 22) | – | |
| Import STL, OBJ, 3MF, PLY | MISSING | CHOICE: trimesh, lib3mf | |
| Mesh repair, remesh, decimate, smooth | MISSING | CHOICE: manifold3d, Open3D | |
| Mesh to faceted B-rep | MISSING | CHOICE: sew triangles in OpenCascade | |
| Scan to B-rep | OUTSIDE (§4; deferred by the owner) | CHOICE: RANSAC primitive fitting, quad remeshing + B-spline/SubD fit | |

**Lattices**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Strut and TPMS lattices, field-driven thickness, multi-material 3MF | IN-4B (4b.9) | – | |
| Conformal, stochastic (Voronoi), named cell library | not stated | CHOICE: implicit kernel | |
| 3MF beam-lattice extension | MISSING | CHOICE: lib3mf | |
| Lattices as exact B-rep | OUTSIDE (§4) | CHOICE, of little value | the industry ships lattices as meshes |

**Generative design and topology optimisation**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| SIMP or level-set optimisation with keep-ins and keep-outs | MISSING | CHOICE: scikit-fem + MMA; SDF level sets | |
| Manufacturing constraints | MISSING | CHOICE: filters and projections | |
| Optimised shapes as exact B-rep | OUTSIDE (§4) | CHOICE: SubD fit | same technology as the deferred scan-to-CAD |

**Simulation**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Analytical strength checks | plan §4.7 item 6 | – | |
| Linear static FEA with a convergence bound | LATER S6 | – | used as a check only |
| Modal, buckling | MISSING | CHOICE: SciPy `eigsh` | |
| Thermal, fatigue | OUTSIDE (§4) | CHOICE: scikit-fem; S-N curves | |
| Nonlinear, contact, dynamics | OUTSIDE (§4) | CHOICE: CalculiX or Code_Aster (separate process) | |
| CFD | MISSING | CHOICE: OpenFOAM (separate process) | |

**Engineering design calculations: all MISSING, CHOICE.** Loads appear only as requirements (plan §4.1) and checks (plan §4.7 item 6).
| Capability | Method or standard |
|---|---|
| Shafts | DIN 743, deflection, critical speed |
| Bolted joints | VDI 2230 |
| Springs | EN 13906 |
| Gears, belts, chains | ISO 6336 / AGMA 2001; ISO 606 |
| Bearing life | ISO 281 |
| Keys, press fits | DIN 6892, DIN 7190 |
| Beams, plates, pressure walls, buckling | Roark, Lamé, Euler/Johnson |
| Welds | throat sizing |
| Section properties | own code |
| Material property library | own tables |

**Analysis tools**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| Draft, undercut, wall thickness | IN-4B (4b.7) | – | |
| Continuity G0–G2 | IN-4B (4b.0d1, 4b.5) | – | |
| Curvature, zebra, isophotes | MISSING | CHOICE | |
| Mass properties | IN-4B (4b.10) | – | |
| Sections | IN-4B (item 15) | – | |
| Deviation | IN-4B (4b.8; 4b §5) | – | |
| Measure | LATER S5 (`query_geometry`) | – | |
| Minimum radius, tool reach, overhangs | LATER S6 | – | |
| Interference | LATER S8 | – | |
| Symmetry check | MISSING | CHOICE | |
| Compare versions | LATER S7 | – | |

**Imports and exports**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| STEP import | IN-4B (4b.8, item 24) | – | |
| STEP export; AP242 with names, colours, PMI | stage 3 (built); LATER S6 | – | |
| IGES export | LATER S6 | – | |
| IGES import | MISSING | CHOICE: `IGESControl_Reader` | |
| Parasolid x_t export | OUTSIDE (§4, "no licence") | mostly CHOICE: documented format, no open library | large own writer |
| Parasolid x_t import | MISSING | same as export | |
| JT | OUTSIDE (export) | CHOICE: ISO 14306 | the licence claim is overstated |
| ACIS SAT | MISSING | CHOICE for older SAT; TECH for current binary versions | |
| Native SLDPRT, F3D, NX/Creo PRT, CATPart, IPT | MISSING | TECH: proprietary formats, vendor SDK licences | |
| STL and 3MF export | stage 3 (built) | – | |
| STL, 3MF, OBJ, PLY import; OBJ and glTF export | MISSING | CHOICE: trimesh, OpenCascade's `RWObj`/`RWGltf` | |
| DXF and SVG import | IN-4B (item 8) | – | |
| DXF, SVG and PDF output | 4b.6; LATER S6 | – | |
| DWG | MISSING | CHOICE: LibreDWG (GPL, separate process) | risk of losing detail |
| PCB IDF/IDX | MISSING | CHOICE: open specs | |
| AP242 PMI import | MISSING | CHOICE: OpenCascade XCAF | |
| Parametric script | LATER S6 | – | |

**PMI/MBD**
| Capability | Status | Constrained or choice | Note |
|---|---|---|---|
| GD&T | IN-4B (4b.10) | – | annotation checked |
| Tolerance classes, ISO 286 | IN-4B (item 21) | – | |
| PMI presentation and AP242 export | LATER S6 | – | |
| Surface texture (ISO 21920), edge conditions (ISO 13715), weld symbols | MISSING | CHOICE | |
| Worst-case 1-D stacks | LATER S8 | – | |
| Statistical 3D tolerance analysis | OUTSIDE (§4) | CHOICE: Monte Carlo | |

**Later stages, in brief**
| Area | Status | Constrained or choice |
|---|---|---|
| 2D drawings | LATER S6 | DWG MISSING (above) |
| Single-part tube along a 3D path | IN-4B (sweep) | – |
| Pipe and harness routing | OUTSIDE (§4) | CHOICE |
| ECAD-MCAD | MISSING | CHOICE: IDF/IDX |
| Assemblies (mates, BOM, derived features, standard parts) | LATER S8 | – |
| Skeletons, in-context references | MISSING | CHOICE |
| Assemblies over about 200 parts | OUTSIDE (§4) | CHOICE |
| Kinematic motion | LATER S8 | – |
| Dynamics | OUTSIDE (§4) | CHOICE: Project Chrono, MuJoCo |
| CAM | OUTSIDE (§4) | CHOICE: OpenCAMLib, FreeCAD CAM; FDM slicing is S6 |
| Rendering | preview S4, render tool S5; photoreal OUTSIDE (§4) | CHOICE: Cycles, Mitsuba 3 |
| PDM | OUTSIDE (§4); revisions are S7 | CHOICE |

## 3. Planned, but narrower than the professional tools

1. **The agreed scope isn't written yet.** The 3.1 G2 row and §4 still list SubD/T-splines, G2 corner blends and G2 on freeform faces as outside. There is no sub-stage, kind, verification class, pathfinder or exit stratum for them. Plan §8 still cites 4b revision 3 (the page is at revision 4). Still to write:
   - SubD: control cage, creases, a pinned limit surface, and patches at extraordinary vertices.
   - G2 corners: setback values and the corner patch type.
2. **3.1:** freeform offsets, shells and thickening are left to OpenCascade's weak offset.
3. **4b.5 surfaces:**
   - Boundary surfaces and fills are G1 only, with no continuity choice per edge and no tangent magnitude.
   - Extend has no natural, linear or curvature-continuous modes; trim has no projection direction.
   - No bridge surfaces, variable offset, rebuild or fairing.
4. **4b.1 loft and sweep:**
   - Loft ends allow tangency only: no curvature, normal-to-profile or direction conditions, and no weights.
   - Sweep has no "normal to a reference surface" orientation, merging of tangent faces, or alignment with end faces.
5. **4b.1 thin features:** only on extrude and cut.
6. **Item 2 depth modes:** no two directions with independent end conditions, and no start condition (from a surface, vertex or offset).
7. **Item 8 sketches:**
   - The 2D constraint set isn't listed, and there is no G2 constraint.
   - Splines interpolate only; there is no sketch mirror, pattern or trim.
   - 3D sketches have five constraint types.
   - Isoparametric, silhouette, offset-on-surface, geodesic and bridge curves are absent.
8. **4b.3 roundings and chamfers:**
   - No conic (rho) section and no overflow control.
   - Corner blends are G1 N-sided patches only.
   - Chamfer corner treatment is unstated.
9. **4b.3 draft and shell:** draft has no variable angle, no both-sides parting-line draft and doesn't mention freeform faces; shell has no thickness law.
10. **4b.1 gears and springs:**
    - Gears: no cycloidal, worm wheel, herringbone, face, spiral bevel, hypoid, non-circular, Geneva, ratchet or harmonic profiles.
    - "Timing pulleys" names no profiles (GT2, HTD, T5, XL) and "sprockets" no standard; no V-belt pulleys.
    - Cams lack barrel and globoidal types.
    - Springs are compression only.
11. **4b.2:** the thread and standard-feature gaps listed in the catalogue above.
12. **4b.4:** "face patterns" is undefined on freeform faces.
13. **4b.5a, 4b.6, 4b.7:** the omissions in the catalogue tables above:
    - plastic-part features;
    - forming tools, tube bending and bend sequence;
    - weld profiles outside EN, weld preparation and symbols;
    - mold feed and cooling systems;
    - casting and forging.
14. **4b.8:** imports STEP only, with no feature recognition and no live rules.
15. **4b.9:** no conformal or stochastic lattices, no cell library, no 3MF beam-lattice extension, no textures.
16. **4b.10:**
    - Materials carry density only.
    - The annotation set has no surface texture or edge conditions.
    - Requirements stop at mass properties: nothing for stiffness, deflection, frequency or temperature.
17. **Stage 5 §4.3 and §5.3:** region checks are purely geometric. The agent has no load or stiffness requirement and no tool to simulate or optimise. §2.8 still says smooth joins are unchecked.
18. **Stage 6 FEA:** linear static only, and used only to pass or fail, never to size or shape.
19. **4b §4's reasons:** "can be added after V2" is a sequencing choice. The "no licence" reason is overstated for JT and only partly true for x_t.

## 4. Open points

- The terms of Siemens' XT format reference.
- Whether any T-spline patent is still in force. Catmull-Clark subdivision (OpenSubdiv, Apache-2.0) is the route either way.
