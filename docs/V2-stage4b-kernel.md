# Forge V2, stage 4b.0a′: the kernel switch, its record

Status: the first sub-step done, 14 November 2026: the replay passes and
every difference from 7.9.3 is explained (section 4). The first sub-step of
the switch (ADR-0022; [V2-stage4b.md](V2-stage4b.md), 2.1): OpenCascade 8.0.1
through `cadquery-ocp-novtk==8.0.1.1.0` on today's Python, nothing else
changed. Every difference from 7.9.3 is listed and explained here, one by
one, never re-baselined in bulk. The second sub-step, CPython 3.14
(ADR-0023), follows when this one's replay passes and 4b.0b is done
(ADR-0035).

---

## 1. The port

`forge_occ` (24 files) and seven test files, ported to 8.0's bindings; no
behaviour of Forge's changed:

- OCCT's collection classes moved to `OCP.collections` under their
  template names, imported under the old ones
  (`IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher` as
  `TopTools_IndexedMapOfShape`, and the shape lists, point and number
  arrays, and label sequences alike).
- `BRepTopAdaptor_FClass2d` is gone: `IntTools_FClass2d`, the same
  classifier. `GCE2d_MakeSegment` is gone: `GC_MakeSegment2d`.
- The `TopoDS` casts lost their `_s` (`TopoDS.Face_s` is `TopoDS.Face`).
- `Bnd_Box.Get()` returns a struct the bindings can't convert:
  `occt.box_limits(box)`, from `CornerMin` and `CornerMax`, which equal
  `Get()`, gap included, on 7.9.3.
- The pin: `forge_occ.PIN = "8.0.1.1.0"`, `OCCT_VERSION = "8.0.1"`, the
  `exact` extra in `pyproject.toml`.

Seeds 0 to 11 built on both kernels gave the same volumes.

The cloud workspace was wiped on 11 November between 09:45 and 12:18 UTC,
before any of this reached the main project's laptop copy (by design: the
port is synced only when the replay passes). The port was redone from
this section on the laptop's tree, the same changes made by a script, and
every test of section 2 run again on it. The machine came back with
CPython 3.13.18 (3.13.16 before) and NumPy 2.5.3; stage 4's counted run
on 7.9.3 recorded neither version, so a replay difference is first
checked against them (section 4).

## 2. The kernel's tests

The 28 test files that build with the kernel, in two shards.

On the first port, before the wipe:

| Shard | Files | Result |
|---|---|---|
| b | 14 | 236 passed, 154 subtests passed, 57 min |
| a | 14 | 272 passed, 1 skipped, 1,959 subtests passed, 2 h 40 min; one failed, a difference (3.1) |

With 3.1's tests changed, its file (`tests/test_v2_plan_alternatives.py`)
was run again whole: 18 passed, 127 subtests passed. The skipped test is
FreeCAD's second reading of the STEP files, FreeCAD being absent here, as
on 7.9.3.

On the redone port, 11 November from 12:27 UTC, 3.1's tests included:

| Shard | Files | Result |
|---|---|---|
| b | 14 | 230 passed, 6 skipped, 152 subtests passed, 43 min |
| a | 14 | 260 passed, 15 skipped, 1,874 subtests passed, 2 h 9 min |

The fresh machine lacked manifold3d (3.5.4), which the tests alone use to
make reference meshes; it was installed while the shards ran, after each
had loaded. Its 20 skipped tests were run again on their own, every one
passing: `test_v2_checks_brep.py` (6 passed, 2 subtests),
`test_v2_checks_accounting.py` (the file whole, 15 passed, 56 subtests),
`test_v2_plan.py`'s reference parts (1 passed, 33 subtests). With them,
274 tests pass in shard a: the first port's 272, 3.1's test that failed,
and 3.1's new one. The one test left skipped is FreeCAD's, as before.

The owner decided on 11 November, after the wipe, that the port goes to
the main project's laptop copy once these tests pass, rather than after
the replay: one main project, nothing of it held only in the cloud. The
replay still decides the switch; a fix it needs goes to the laptop too.

## 3. Differences

### 3.1 Held-out seed 10517: 8.0.1 cuts the flush hole right

A 4.552 mm blind hole, 1.845 mm deep, drilled radially into an 88.881 mm
tube's side, its flat mouth touching the side along a line. Made flush,
OpenCascade 7.9.3's subtract kept the hole's plug beside the part as a
second solid and raised no flag; that was the held-out fault fixed in
stage 4 by carrying such a hole first and holding the part to one solid
after each join or cut ([V2-stage4-exit.md](V2-stage4-exit.md), 5).

On 8.0.1 the same flush cut is one solid. It removes 29.788337 mm³: the
tool's 30.025535 mm³ less the sliver of it outside the side, the integral
of R − √(R² − y²) over the mouth, agreeing to 10⁻⁵ mm³. Forge's own
engine agrees with the part. OpenCascade's fix, not Forge's code: nothing
in Forge changed.

The test that pinned 7.9.3's fault
(`test_a_cut_that_leaves_the_part_in_two_solids_is_refused`) now puts the
fault back by hand, the plug (what the tool held of the part) beside the
cut part, so the after-check and the search stay held to it on any
kernel. A new test (`test_opencascade_8_cuts_that_flush_hole_right`)
holds 8.0.1 to the right cut, its volume and Forge's agreement. Carried
still goes first for a hole into a round side from outside (5.2 of
[V2-stage4.md](V2-stage4.md)): the planner's order doesn't rest on which
kernel happens to cut a line contact right.

### 3.2 Seed 450: the exact part's genus miscounted, a Forge fault (not the kernel's)

A dome with two blocks under it, each crossed by a through slot that four
deep round slots meet and each with a boss flush with its edge, and a tube
with a 1.956 mm hole into its bore. The replay's record fails on the second
kernel's topology: the exact part's genus 12, the implicit mesh's 11
(sound, made again at 192 and then 256 cells across). Every compared point
is on the same side in both kernels and the volumes agree.

The implicit kernel was right. Counted by hand the part has 11 handles: 5
in each block (the through slot, and each deep slot meeting it from the
underside) and 1 in the tube. The exact part's genus came from
`forge_occ.view._genus`, the Euler-Poincaré count V − E + 2F − L with L its
faces' wires; that takes each face for a piece of plane with a hole per
wire past the first. Each boss is flush with its block's edge, so its circle
touches the face's outline at a point and the two wires share a vertex: the
face is one piece round the boss, no hole, but counted by wires it lost one
from the Euler characteristic, and the two bosses together made a
through-hole. Counted step by step, the genus went from 10 to 12 at the
step that joined the bosses and cut the tube's hole, where 11 was due; with
the count fixed it is 11, as a mesh of the part says too.

The fix counts a face's boundary in pieces: its wires, two that share a
vertex being one (`_boundary_pieces`). It changes nothing where no wires
touch. Tests: `test_bosses_flush_with_a_faces_edges_make_no_through_hole`
(a block with two bosses flush with its edges: genus 0, as its mesh says;
1 before the fix) and `BossesFlushWithEdges` (seed 450, kept in
`tests/v2_regressions.py`: the exact genus 11, the agreement holds).

Not OpenCascade's: the exact part is the same on both kernels, 12 by the
old count on 9 November's run too. That run didn't see it because the
tube's hole was made flush then and the implicit mesh wasn't sound, so
topology wasn't counted; since the held-out fixes of 10 November the hole
is carried first (5.2 of [V2-stage4.md](V2-stage4.md)) and the mesh is
sound. The through-hole count isn't otherwise judged yet (the oracle
doesn't count through-holes), so only the agreement used it.

First read as the implicit mesh closing a narrow passage; comparing the
mesh with its own field everywhere more than half a cell from the surface
found no difference, and counting each step's genus found the miscount.
Fixed during the replay at the owner's direction, its workers taking it up
at their next batch. Only the second kernel's topology reads the genus, on
the view seeds, which the replay runs first; at the end every view seed
recorded before the fix whose topology was counted, and every seed that
failed, is run again on the fixed code.

### 3.3 Seed 1057: a point beside a letter's edge measured to the edge, a Forge fault (not the kernel's)

A cylinder with letters engraved in its top, two holes into its side and a
rib, a post and a pocket. Held by face accounting: one of its spec's
252,845 points, on the top 7e-6 mm outside a letter (beside a Bézier edge
of the u in "ú"), had nothing built within its tolerance, 1e-6 mm.

The built part is right there: the letter's edge passes through the same
point as the judge's own letters (2.5e-10 mm apart), and the point is on
the built top. Its distance was measured wrong. `BrepView` takes a point's
foot on a face as surely on it where the face's boundary, as
`forge_occ.uvclass` reads it, says so; a curve that is neither straight nor
circular is read as a polygon with a band round it left unsure, here
7.5e-5 mm wide. A foot in the band went to OpenCascade's classifier, whose
ON (it calls this point ON at every tolerance from 1e-9 to 1e-5) didn't
count, and the distance was OpenCascade's own, to the edge: 7e-6 mm.

Why now: built flush, as on 9 November, a boolean left a vertex nearby a
tolerance of 6.4e-6 mm, which widened the point's tolerance past 7e-6;
carried first since the held-out fixes, the booleans' tolerances are worked
out again tight (1e-7 mm) and the point's fell to the floor. The same code
on 7.9.3 would make the same record.

The fix: a foot left in a band is settled by the face's boundary read
again with its bands narrowed (`uvclass.FINE`, a millionth of the face's
size down to a hundred-millionth, made once a face and only where a foot
needs it); only what is still unsure goes to OpenCascade's classifier. Here
the band falls to 7.7e-7 mm and the foot is on the face: distance 0. Test:
`test_a_foot_left_in_a_band_is_settled_by_a_finer_reading` (seed 1057, kept
in `tests/v2_regressions.py`: OpenCascade's distance 7.0e-6 mm, the view's
now none; it fails before the fix). Fixed during the replay at 13:31 UTC on
12 November; the seeds before it that failed are run again at the end.

### 3.4 Seed 4935: a hole the plan wrote nothing for, a Forge fault (not the kernel's)

A closed block's hollow with a tube hung from its ceiling, a hole right
through the tube's wall, and holes and a pocket in the hollow's walls. The
replay's record is an error before anything was built: the plan's hole
`i4`, "its construction 'carried' doesn't apply here".

A hole into a round side from outside goes first by its carried
construction, its tool carried 0.05 mm into the air past its mouth (5.2 of
[V2-stage4.md](V2-stage4.md)), so that OpenCascade never meets the
definition's tool touching the side along a line. The design puts it first
*where its proof holds*: the air past the mouth clear of every tool made
so far. Here the air past the tube's side, and past its far side, is
inside the hollow and so within the block's own box (the proof reads
boxes, and the part made so far is within its tools'), so the proof
doesn't hold and carrying isn't offered. But the held-out fixes of 10
November swapped the two constructions' order for every such hole, and the
planner took an item's first construction to be always writable (true
until then: the first was the definition's). So the default was a
construction whose proof doesn't hold, and the plan wrote nothing.

The fix makes the plan as the design says: an item no choice names is made
by its first construction whose proof holds (`Plan.written`), here the
definition's; the build loop's search, the refusals and the record's
`made_by` read the construction actually written. Nothing changes where an
item's first construction's proof holds; where it didn't, the plan raised.
Built so, the part passes as on 7.9.3, every item flush and the mutant
caught. Tests:
`test_a_hole_whose_carrying_doesnt_hold_is_made_by_its_definition` (seed
4935, kept in `tests/v2_regressions.py`: the plan writes and builds the
definition's, a refusal of it is named for it; it fails before the fix
with the replay's error), and the part built, judged and graded with the
others kept (`test_v2_plan_build_generated.py`).

Not OpenCascade's: the plan is written before any kernel is called, and
the same code on 7.9.3 makes the same error. The 9 November run planned
the hole flush, before the held-out fixes. Fixed during the replay at
11:13 UTC on 13 November; the seeds that failed before it are run again at
the end.

## 4. The replay

Stage 4's whole counted run (seeds 0 to 9,999) replayed on 8.0.1 against
its 7.9.3 records (`runs/stage4_exit/records.jsonl`), the view seeds
first, two workers. Started at 09:43 UTC on 11 November and lost with the
wipe before its first record; started again at 14:44 UTC once section 2's
rerun passed. Its records are copied to the session's lasting storage
every few minutes, so a wipe costs minutes of it, not days.

Those 7.9.3 records were made on 9 November, before the held-out run's
fixes of 10 November (to Forge: holes into round sides carried first, one
solid after each join or cut; to the generator: items touching along a
line refused). Each difference is therefore first checked against those
fixes: a construction now carried, a mutant drawn from a changed list, a
part the generator now draws otherwise. A difference none of them
explains is run again on 7.9.3 with today's code, so that what is left is
the kernel's alone.

### 4.1 The result

Done at 16:11 UTC on 14 November. The container restarted three times
during it, none a wipe; each time the run went on from its saved records,
the batches then running made again. Of the 10,000 seeds:

| | 7.9.3, 9 November | 8.0.1, the replay |
|---|---|---|
| Parts as asked, passed | 10,000 | 9,998 (1057 held, 3.3; 4935 an error, 3.4) |
| Mutants that change the shape, caught | 9,702 of 9,702 | 9,702 of 9,702 |
| Impossible parts turned back | 1,000 of 1,000 | 1,000 of 1,000 |
| Second kernel and files, passed | 1,000 of 1,000 | 999 of 1,000 (450, 3.2) |
| One worker's time | 168.2 h | 146.7 h |

Then the seeds a fix of section 3 touched were run again on today's code:
the three that failed, and the 28 view seeds from 0 to 990 whose topology
was counted before 3.2's fix. All 31 pass; 450's exact genus is now 11, as
the implicit kernel's, and the other 28 are as they were. With them the
exit passes on 8.0.1: 10,000 of 10,000, every mutant that changes the shape
caught, every impossible part turned back, the second kernel and the files
passed on all 1,000 view seeds. The records are kept in
`runs/stage4b_kernel/`: the replay's (`records.jsonl`, `report.md`) and the
reruns' (`reruns.jsonl`).

The time is 13% less (the builds' 21% less), the held-out fixes'
constructions included, so not the kernel's gain alone; measured like for
like before the replay, the same parts on both kernels with the same code,
builds took about 17% less and whole parts about 7% less.

### 4.2 Every difference from 7.9.3, explained

Record against record, every field: how each item was made, refusals, the
outcome, what was held, the grading, the mutant, the impossible part, and
the views. What differs:

- **How items are made (1,970 seeds, 4,287 items).** Each changed from flush
  to carried, and each is a hole into a cylinder's side (2,116) or a tube's
  (2,171) from outside: the held-out fix, carried first where its proof
  holds (5.2 of [V2-stage4.md](V2-stage4.md)). 4935 is made as on 7.9.3,
  every item flush (3.4).
- **Parts the generator now draws otherwise (12 seeds).** Seven with an
  item more or fewer (1020, 2998, 4780, 5510, 7170, 7761, 9330), and five
  of the view seeds with the same items but other values (3890, 6090,
  6280, 9550, 9960): their exact volumes moved by 0.06% to 16%, and the
  implicit kernel's intervals, which are worked out from the spec and not
  from OpenCascade, moved with them. The generator imports nothing of
  OpenCascade, so these (with their mutants), the 34 other mutants drawn
  from changed lists and the impossible part of 3650 (another item running
  off its face) are its held-out changes (items touching along a line
  refused), not the kernel's. Two mutants are the same but caught first by
  another check (1725 by its diameter for its depth; 6137 by its face for
  its diameter), both still caught.
- **Volumes.** Where the part is the same, the exact volumes of the other
  995 view seeds agree to 2.4e-6 mm³ at most, a relative 1e-11. The implicit
  kernel's intervals and soundness moved on 207 and 42 seeds, as the
  documents differ where holes are carried (the implicit kernel reads the
  document's tools): its mesh sound where it wasn't on 22, not where it
  was on 20. The agreement held on every view seed.
- **The exact genus.** It changed on 11 view seeds. On 450 it is 3.2's fix.
  The other 10 are among the parts drawn otherwise, and each new count is
  the count an independent reading of the same part gives: the implicit
  kernel's on 8, and on 9550 and 9960, whose implicit mesh isn't sound, a
  fine mesh of the built part (10 and 14, at 0.05 and at 0.02 mm).

Nothing else differs. No difference was left for a run on 7.9.3 with
today's code to settle: each is one of the held-out fixes, a fix of
section 3, or the kernels' arithmetic in a volume's eleventh digit.

### 4.3 What it shows

OpenCascade 8.0.1 makes every part of stage 4's counted run that 7.9.3 made,
to the same exit; cuts right the flush hole 7.9.3 cut wrong (3.1); and takes
less time. The three failures were Forge's own faults, older than the
switch and shown by the held-out fixes' new constructions; each is fixed
at its root with a regression kept (3.2 to 3.4). The second sub-step,
CPython 3.14, follows 4b.0b (ADR-0035).
