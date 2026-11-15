# Forge V2, stage 4: the exit

Status: the counted run passed, 9 November 2026. The held-out run of
2,000 fresh seeds ended 10 November: five failed, none releasing a wrong
part, each fixed at its root (section 5). Of the two live checks, run
with the owner's API key, `forge eval-false-passes` caught 27 of 27; the
owner deferred `forge eval-corpus` for its cost (section 4). Stage
4's exit test (plan section 8, row 4; [V2-stage4.md](V2-stage4.md),
section 14) ran on frozen code, and this page records what it found.
Stage 4b ([V2-stage4b.md](V2-stage4b.md)) starts from here.

---

## 1. The verdict

The counted run passes. On frozen code, every one of the 10,000 seeds
passed every part of the test asked of it; no seed failed. With sections
14.2's and 14.3's offline halves passing too, what remains of the exit in
full was its two live checks (section 4), which need the owner's key;
section 5 measures the same code on fresh seeds.

| Part of the exit | Result | Failure rate at most (95%) |
|---|---|---|
| Parts as asked: built, every detector passing, graded against the truth | 10,000 of 10,000 passed | 0.03% |
| Mutants that change the shape, each failed by a detector | 9,702 of 9,702 caught, 0 surviving | 0.03% |
| Mutants that leave the shape as it was (decided exactly) | 298 | (not counted) |
| Impossible specs turned back (CAN'T or a question) | 1,000 of 1,000 | 0.30% |
| The second kernel's agreement, and the STEP, STL and 3MF re-opened and judged | 1,000 of 1,000 | 0.30% |

Each bound is the rule of three: with no failure in n trials, the failure
rate is under 3/n with 95% confidence. Every kind (19) and every pair of
kinds that can meet on one part was drawn at least 50 times (the rarest
pair, a chamfer with a shell, 57 times); the counts per kind and per pair,
and the detector that caught each mutant, are in the run's report
(section 7).

Eleven times a construction was refused and its proven-equal alternative
built instead (`on_the_part` refused, `early`
built); no item had every construction refused.

## 2. How it ran

- **The code:** the tree frozen as snapshot 42 (section 7 gives its hash),
  the same tree on the owner's laptop, checked file by file (md5) before the
  run began. Nothing in it changed while the run went.
- **The command:** `python tests/v2_exit4.py --from 0 --to 10000 --workers 2
  --views-first`, each seed's record a line of `records.jsonl`. With
  `--views-first` the 1,000 seeds that also run the second kernel and the
  files (every tenth) ran first, so a fault in the late export fixes would
  have shown on the first day.
- **The time:** started 05:48 UTC on 6 November, ended 18:00 UTC on
  9 November: 84.2 hours of two workers (168.2 hours of one worker's
  time). The 1,000 view seeds took 19 hours (about 52 an hour); the
  9,000 others ran at 100 to 175 an hour, by how heavy each part was.
- **Interruptions:** the machine running it restarted twice (22:50 UTC on
  6 November, 03:58 UTC on 7 November). Each time the run resumed where it
  stopped: the seeds already recorded were not run again, and the records
  were checked afterwards, every line whole and no seed twice.

## 3. Before it: the pilot, the shakedowns and the practice run

The counted run was the last of several on the same 10,000 seeds. A pilot
(seeds 0 to 99), six shakedowns and a full practice run found parts the
exit would fail; each was fixed at its root, a test kept for it, and the
whole seed run again. [V2-stage4.md](V2-stage4.md), section 14.1, tells
each one in full. The practice run, seeds 0 to 9,999, ended with 17 seeds
failing it (9,988 parts passed, 5 held,
5 errors, 2 graded wrong; mutants 9,694 caught, 304 the same shape, none
surviving; 997 of 997 impossible specs turned back; 992 of 1,000 views
passed). The 17, and what each fixed:

| Seed | What it found | Whose fault, and the fix |
|---|---|---|
| 3151 | A counterbored hole whose own bore lay wholly in a pocket: nothing of it was built to measure. | The generator's: every hole, pocket and slot now keeps enough of its own side built to be measured. |
| 3375 | Holes on a cone that widens upward reached past its base, over the flank. | The generator's: past a cone's base its truth has the cone's own height, and nothing goes through there. |
| 3500 | Its STEP file, its closed faces halved, read back with wires turned against each other. | Forge's STEP writer: the halves are kept only if the file reads back valid, else the part is written unsplit. |
| 3767 | The window measuring a hole's angle round a tube took in a slot's wall 3 mm off. | The judge's: a window now leaves out points that may lie on another of the spec's surfaces. |
| 4050 | A sliver 0.05 mm wide beside a pocket left a shell's wall unmeasurable on the STL. | The judge's: a wall is measured where both its discs are whole surface. |
| 4118 | A counterbore's floor, its bore and a pocket's rounded corner meeting at one corner left face accounting no witness. | The judge's: the witness also tries the point where three surfaces meet. |
| 4180 | Two finer faces meshed apart discretised their shared rim twice, tearing the STL. | Forge's mesher: faces that meet are meshed together, each shared edge once. |
| 6820 | The agreement check's 9 by 9 grid found no point clear of a 0.49 mm L's rim. | Forge's agreement check: the grid is refined until it finds such points. |
| 6950 | A bore's curve read back from STEP strayed 3.9e-5 mm from its edge. | Forge's reading back: every edge is measured along its length and held as loosely as its curves stray. |
| 7250 | Halving a tube's face for STEP left an edge 3.2e-5 mm long, read as the surface meeting itself. | Forge's STEP writer (cuts kept 1e-3 mm from corners) and its topology check (joined corners not counted). |
| 7470 | A letter's side, a Bézier whose speed falls to nothing at its end, made a mesh sample unmeasurable. | Forge's measure: such a sample is measured by OpenCascade's projection. |
| 7858 | A boolean between two threads of opposite hands ran 15 minutes, and the worker died. | The exit test's: a mutant is shown to change the shape by its volume or a far point first. |
| 8032 | A pulley's axis was fitted to its 0.032 mm bore, which the judge could not resolve. | The judge's: a revolution's axis is fitted to its round side with the most surface. |
| 8675 | A pocket meeting a slot's wall at 1.3 degrees: the grader failed a right part. | The exit test's grader: it also looks along ways just off a point's plane. |
| 9213 | A pocket's rounded corner against a slot's wall, the two walls one: a cusp no witness reached. | The judge's and the grader's: the oracle's cusp witness, and finer tilts. |
| 9530 | Holes 0.118 mm from a pocket: a wall under two cells of the implicit mesh. | Forge's agreement check: below two cells the topology is reported, not counted. |
| 9906 | A rounded post lying against a cylinder's end: the truth rounded edges the part does not have. | The exit test's generator: roundings the part lies against are dropped from the truth. |

Before the counted run, all 17 were run again whole on the frozen code and
passed, and the full suite passed: 102 of 102 test files (`eval_truth`
alone 80 tests and 6,877 subtests).

## 4. What this shows, and what it does not

- **It shows** that on frozen code, over 10,000 random parts of up to eight
  items of stage 4's 19 kinds, every part was built and judged right, no
  wrong part was let through by the judge (every shape-changing mutant was
  failed), every impossible spec was turned back, and every tenth part's
  second kernel and shipped files agreed: the failure rates under the
  bounds of section 1.
- **It does not show it on fresh seeds.** The counted run drew the same
  seeds, 0 to 9,999, that the faults were found and fixed on (the stage's
  fixed range, section 14.1). The run shows every fix holds and that
  nothing else broke across the 10,000; it cannot show how often a part
  never seen before fails. The held-out run measured that, on 2,000 fresh
  seeds (section 5): at most 0.47% (95%), not 0.03%. Stage 4b's exit
  requires fresh seeds for every counted run
  ([V2-stage4b.md](V2-stage4b.md), section 5).
- **The rest of the exit.** Section 14.2 (V1's corpus drafted as V2 specs:
  76 of 92 drafted and built, the 16 others each saying why not) and
  section 14.3 (V1's 27 false passes replayed: each wrong part fails the
  judge, or is stopped where V2 stops it) run without a model. Their live
  halves call the spec writer with the owner's key. `forge
  eval-false-passes` was run by the owner on 10 November: 27 of 27 caught
  (14 asked a question, 9 stopped, 3 built with
  no wrong part released, 1 refused). `forge eval-corpus` was deferred by the owner for its cost;
  `--replay` re-runs what is recorded at no cost.

## 5. The held-out run: fresh seeds

Section 4's caveat, measured. The counted run's frozen code (snapshot 42,
unchanged) was run on 2,000 seeds never drawn before, 10,000 to 11,999,
the 200 view seeds first: `python tests/v2_exit4.py --from 10000 --to 12000
--workers 2 --views-first`, from 18:22 UTC on 9 November to 17:25 UTC on
10 November (23 hours; the container restarted twice, at 23:18 and
23:37 UTC on 9 November, and the run resumed where it stopped each time,
every record whole and none twice).

| Part of the exit | Result | Failure rate at most (95%) |
|---|---|---|
| Parts as asked | 1,995 of 2,000 passed; 5 failed (3 held, 2 UNABLE) | 0.47% |
| Mutants that change the shape, each failed | 1,939 of 1,939, none surviving (59 more left the shape the same) | 0.15% |
| Impossible specs turned back | 200 of 200 | 1.50% |
| The second kernel and the files | 199 of 199 (the 200th view seed, 10890, ended UNABLE before its views) | 1.51% |

With five failures in 2,000 the parts' failure rate is at most 0.47%
(95%, exact binomial), against 0.03% claimed on the seeds the faults were
fixed on. That was the caveat's point: a fresh part fails more often than
the fixed range showed. No wrong part was released in any of them: three
were held by the judge and two ended UNABLE. Each was traced to its root
on a copy, fixed with a test kept for it, run again whole on the fixed
code and passed:

| Seed | What it found | Whose fault, and the fix |
|---|---|---|
| 10890 | UNABLE: a hole right through a tube's wall from outside; OpenCascade warned on its flush tool, tangent to the side at its mouth and to the bore at two points, and no other construction was offered. | Forge's: a hole into a round side is carried into the air too ([V2-stage4.md](V2-stage4.md), 5.2). |
| 10517 | Held: a blind hole into a tube's wall, cut flush, its plug kept beside the part as a second solid with no flag raised. | Forge's: such a hole is carried first, and the part is held to one solid after each join or cut (sections 5 and 8). Carried, two parts kept by the STEP tests showed two faults of the STEP writer's, fixed too ([V2-stage3.md](V2-stage3.md), 12). |
| 11384 | UNABLE: a hole right through a tube's wall from outside, as 10890. | Forge's, the same fault: fixed by 10890's fix; kept as a test with it. |
| 10849 | Held: holes drilled down from a block's top, the last row's side exactly on a pocket's wall; the part touched itself along three lines. | The generator's (it promises one solid): it keeps a round rod off another item's flat wall by 0.01 mm either way. Forge built what was asked and held it, as it should. |
| 11645 | Held: a pocket cut between two round-ended bores, its width exactly the wall between them; its walls touched both bores along lines. | The generator's, as 10849: refused by 10849's rule. Forge built what was asked and held it. |

Three of the five were Forge's own faults, all in holes into round sides
(10890 and 11384 the same one), whose definition's tool touches the side
along a line. The other two were the generator's, one fault too: a round
rod touching another item's flat wall. The fixed code passed every test file
(3,677 tests and 66,908 subtests passed, 2 skipped, every one of its
103 test files, in two shards over 4.4 hours on 10 November); it is next
counted by stage 4b's runs, each on fresh seeds.
A further 1,000-part run on the fixed code, then one of 100, was
planned and called off by the owner: this run is the measurement, and
stage 4b's counted runs measure the code that follows.

## 6. The budget (section 13.6): not met

Section 13.6 set two targets: the judge of a generated part under 10 s,
and the 10,000 parts and their mutants within two days of both cores. The
counted run measured both, and both were missed. (The run did more than
the target counts: it also graded every part and ran the impossible specs
and the views. Even without them, the judge alone misses its 10 s.)

| Per part (10,000) | median | 90th percentile | most | under 10 s |
|---|---|---|---|---|
| Making the judge (`Judge.of`) | 5.7 s | 19.5 s | 195.2 s | 71.9% |
| Judging the built B-rep | 12.6 s | 40.4 s | 243.2 s | 40.6% |
| The two together | 20.4 s | 54.1 s | | 16.3% |
| Building the part | 0.7 s | 6.7 s | 103.8 s | 95.3% |
| Grading it against the truth | 7.3 s | 19.7 s | 135.1 s | 65.5% |
| Its whole record (with mutant, impossible spec and views) | 39.4 s | 128.5 s | 1,071.3 s | 1.4% |

The run took 84.2 hours of both cores, not 48. Memory stayed inside each
worker's 2,700 MB, but only just: the most a worker held was 2,666 MB
(seed 8290; median 798 MB). Section 13.6 also asked for each change's
timing on parts 0 to 9 before and after; that log was not kept, and the
final code's times on those parts are in the records (seed 9, the
slowest of them, 183.7 s in all). Stage 4b's plan already makes compute a
first-class budget, decided at 4b.0a with a fallback
([V2-stage4b.md](V2-stage4b.md), section 6); these numbers are its
starting point, and the per-change timing log is kept from 4b.0a on.

## 7. The record

- Tree hash of the frozen code (snapshot 42, `dirhash`):
  `e09c649d2381c38633cfa54813f3587f24f03ad20b7c1e7c9a024d7a682e6999`, the
  sha256 of the manifest of its per-directory hashes (`packages`, `tests`,
  `docs`, `schemas`, `scripts` and the top-level files, caches left out);
  the tree on the laptop matched it file by file before the run, and the
  tree here matched it again when the run ended.
- The run's report: `runs/stage4_exit/report.md` (330 lines), with the
  counts per kind, per pair and per detector; the records, one
  line per seed, in `runs/stage4_exit/records.jsonl`.
- The practice run's report, for comparison: kept beside it as
  `runs/stage4_exit/practice-report.md`.

## 8. Next

Stage 4b, in the order its plan sets, now revision 5
([V2-stage4b.md](V2-stage4b.md)): part one (4b.0 to 4b.10), part two
(4b.11 to 4b.18, the scope audit's gaps, [V2-stage4b-audit.md](V2-stage4b-audit.md)),
then a peak check, then stage 5. 4b.0a's decisions are ADR-0022 to
ADR-0034 (OpenCascade 8.0.1, CPython 3.14, a compiled trust core in Rust,
the tolerance policy, schema versions, the compute budget and its speed
gate, the sketch solver, the analysis stack, libraries and formats, items
against regions, the DXF reader, external programs, the trust core's
dependencies); 4b.0a′ switches the
kernel and Python as its own step, replayed. The owner's direction (8 and
10 November): build every family in full, leave nothing on the table, and
test it as long and as hard as this, on fresh seeds, before calling it
done.
