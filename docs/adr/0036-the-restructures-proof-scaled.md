# ADR-0036: The restructure's proof, scaled to what it costs

**Status:** Accepted · **Date:** 2026-11-14 · Stage 4b.0b · The owner's
decision; amends [V2-stage4b-0b.md](../V2-stage4b-0b.md), 6.3 and 6.4

## Context

4b.0b moves every program's per-kind code behind registries and must
change nothing any program computes; it is proven by byte-identical
results (V2-stage4b-0b.md, 6). Revision 2 of its design asks, for each
change set, a 1,000-seed sample with every mutant and impossible part, the
corpus, every kept regression and the whole suite, each seed's digest
holding the full judge's verdict on the built part; and at the end all
10,000 seeds the same way.

Measured on 14 November (the 8.0.1 replay's records, two workers): the
judge's compilation and oracle 7.7 s a seed, the build 1.8 s, the judge's
verdict on the built B-rep 16.2 s; a seed's mutant as much again. A seed
with its verdict is about 35 s, so revision 2's proof is about two weeks
of compute, nearly all of it the verdict on a built part.

The verdict is a function of what the judge consumes (the compiled suite,
the nominals, the oracle's node tree, the judge's own placement, the
built part), and the code that turns those into a verdict (face
accounting, the probes, the measures) dispatches on no kind and isn't
moved; the built part is a function of the ForgeIR document, which is
digested.

## Decision

1. **Every seed in a check** is digested on everything V2-stage4b-0b.md 6.2
   lists but the verdict on a built part: the spec's outputs, the
   planner's document, alternatives and exceptions, the compiled suite,
   nominals, the oracle's node tree, expected topology and volume, the
   capability table, the judge's own placement and its comparison of
   layouts, the `Unchecked` and `Rounded` lists, the generator's plan,
   brief, truth and spec grading, and the seed's own mutant and impossible
   part digested the same way; the guide and the JSON schema once.
2. **Each file's change set:** the first 100 seeds of the fixed sample under
   two hash seeds, and the test files that cover the file.
3. **Each role's end** (all its files moved): the fixed 1,000-seed sample
   under two hash seeds, every kept regression, the whole suite, and the
   verdict on the built part (with its first failing check) of 100 seeds.
4. **At the end of 4b.0b:** all 10,000 seeds under one hash seed and the
   sample under the other, every kept regression, the whole suite, and the
   verdict on the built part of the 1,000-seed sample.
5. **The corpus** (`eval/`) is not opened by this work (the owner's
   standing rule) and is left out of the proof.

## Consequences

About three to four days in all, a day of it the end's 10,000 seeds,
instead of about two weeks. A change that altered a verdict without
altering anything it consumes would have to be in the unmoved evaluation
code, and the verdicts of the samples would still catch most such
changes; none is expected, since that code isn't touched.

**As run (15 November 2026):** on GitHub's free runners, twenty and
more at once (the repository public, its code all rights reserved), the
end took an afternoon, not days; so 20,000 seeds past the 10,000 were
run as well, and the old bodies' coverage measured over the sample with
the whole suite (V2-stage4b-0b.md, 6.3 and step 7).

## Alternatives

Revision 2's proof as written: about two weeks of compute before 4b goes
on. Rejected by the owner.
