# Licensing: undecided

No licence is applied yet. This is deliberate: applying one carelessly is harder
to undo than leaving it open, and the dependency picture below constrains the
choice.

## What constrains the decision

| Component | Licence | Implication |
| --- | --- | --- |
| Forge core (this repo) | undecided | Standard-library and NumPy only |
| NumPy | BSD-3-Clause | Permissive; no constraint |
| OpenCascade (planned) | LGPL-2.1 + exception | Dynamic linking is fine; static linking or modification is not, without care |
| CadQuery (planned) | Apache-2.0 | Permissive |
| Gmsh (planned) | **GPL-2.0-or-later** | The strongest constraint. Distributing a combined work may require GPL |
| CalculiX (planned) | **GPL-2.0-or-later** | Same |
| Project Chrono (planned) | BSD-3-Clause | Permissive |
| Autodesk Fusion API | proprietary | Add-in distribution is governed by Autodesk's terms |

Gmsh and CalculiX are the decisive entries. Both are GPL. Whether that reaches
Forge depends on the boundary: invoking them as **separate processes over files**
is generally accepted as not creating a combined work, whereas linking their
libraries is.

The adapter architecture already assumes process isolation for security reasons
(see SECURITY.md), so the licensing-friendly boundary and the security boundary
are the same boundary. That is a fortunate alignment and should be preserved
deliberately rather than by accident.

## Options

**Apache-2.0.** Permissive, with an explicit patent grant. Widest adoption.
Requires keeping solver invocation at the process boundary.

**AGPL-3.0.** Protects against a hosted competitor using the work without
contributing back. Compatible with GPL solvers. Deters commercial adoption and
complicates the add-in story.

**Business Source License.** Source-available, converting to open source after a
delay. Increasingly common for infrastructure. Not an OSI-approved licence.

**Dual licence.** Open core plus a commercial licence for proprietary use.
Requires a CLA from contributors, and that decision should be made before
accepting any outside contribution.

## What to settle before any public release

1. Whether solvers are invoked as separate processes only. **Decide this first**
   — it determines whether GPL reaches the core.
2. Whether outside contributions will be accepted, and under what CLA.
3. Whether the Fusion add-in ships separately, given Autodesk's terms.
4. Whether hosted use should be restricted.

Until then: all rights reserved, no distribution.
