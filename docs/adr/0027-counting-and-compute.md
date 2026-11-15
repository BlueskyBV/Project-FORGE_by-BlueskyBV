# ADR-0027: What a kind is, what 4b's runs cost, and the speed gate

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a (the hardware
question at the end is the owner's)

## Context

Stage 4b's exit (section 5) counts specs per sub-stage, per kind and per
pair. Revision 5 grew the kinds and modes from about 150 to about 270. The
reference machine today is the cloud container: two cores, 7 GB, about 86
stage-4 parts an hour with two workers (84 s a part, 3 s of it building).

## Decision

**The unit.** A kind is a registry entry: a kind and mode with its own
definition, compiler module and generator module (4b.0 item 6). Every count
in section 5 is per registry entry. The registry is recounted at each
sub-stage's start; the arithmetic below is redone on it.

**The arithmetic, today's registry.** Counted specs, before shakedowns:
4b.0 13,000; 4b.1 to 4b.10 (with 4b.5a) 33,000; part one's whole 10,000;
per-kind top-ups to 3,000 specs containing each of about 150 kinds, net of
what the other runs already give (about four kinds a spec) about 85,000;
part two 24,000, its whole 10,000 and its top-ups about 84,000; a
covering-array stratum of large specs (eight or more kinds) so every pair
that can meet appears its count (section 5: 50 or 10). Its size is the sum
of the pairs' counts over the interacting pairs a spec gives: of about
36,000 pairs of registry entries, an estimated 12,000 can meet on one part
(families exclude each other: sheet metal and molding, lattices and
threads), averaging about 20 appearances each, about 240,000; an
eight-kind spec has 28 pairs, of which about a third are expected to
interact, so about 25,000 to 40,000 specs. The "can meet" table and the
interaction rate are measured at 4b.0a′ from stage 4's records and the
stratum set from them. In all, about 300,000 counted specs, about 450,000
with shakedowns and the full re-runs a failed counted run requires. At
today's speed: about 215 days of the container. The guide by family (item
23): about 270 entries in about 20 families, loaded a family at a time, so
a brief's guide stays near today's size. Analysis and
optimisation cases cost minutes to hours each (flow and topology
optimisation the most) and run as their own strata, their counts, sizes
and bounds set from the cost measured on their pathfinders before 4b.0's
counted run.

**The speed gate,** before 4b.1's counted runs start: on the reference
machine, parts drawn from 4b.0's counted distribution (not stage 4's
smaller ones) at a median of 6 s or less and a 99th percentile of 60 s or
less, through build, judge, grade and mutants: about 15 to 20 times
today's judging code. The
means: the compiled core (ADR-0024), BVH culling, caching by content
(ADR-0006), and views on the share stage 4 used. At that speed the whole of
4b's counted work is about three weeks of the container.

**If the gate is missed,** in this order: more speed work; more machines
(the owner's desktop through Docker, or a larger cloud machine: today's rule
is cloud only, so this is the owner's call); and only with the owner, fewer
per-kind strata with the weaker bound stated.

**The kernel switch's replay** (ADR-0022): stage 4's whole counted run on
OpenCascade 8.0.1 and today's Python, about five days at today's speed;
the Python move's replay about two (ADR-0023). Writing 4b.0b's code
overlaps them; proving it waits for them.

## Consequences

The exit's numbers are honest about what they cost, and a missed speed gate
is found before the counted runs, not halfway through them.
