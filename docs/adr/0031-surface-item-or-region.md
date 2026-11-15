# ADR-0031: When a shape is a surface item, and when a stage 5 region

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

Stage 4b.5 and 4b.12 to 4b.13 make freeform surfaces and cages items; stage
5 makes freeform regions, designed by the agent for a purpose and judged
by constraints (V2-stage5.md, 4). Without a rule, the same shape could be
either, and be judged two ways.

## Decision

**A shape is an item when its geometry is in the confirmed spec**: given by
the brief or a file, or computed before confirmation by a pinned algorithm
or a proposer and stored (item 28): surfaces, fills, cages, fitted
surfaces, optimised shapes. It is judged by its class (exact, by
construction, bounded, defined by properties).

**A shape is a region when its geometry is made after confirmation** by the
agent, inside a confirmed envelope and against confirmed requirements. It
is judged by its constraints and requirements and ends with the
constrained class (VERIFIED EXCEPT), as stage 5 says.

A region the agent wants to turn into an item is proposed, stored and
confirmed again (R12); then it is an item.

**Freeform geometry whose values neither the brief nor a file determines
is defined by properties at best, through any conversion** (item 18): a
region turned item, a cage the model proposed, a fitted or optimised
shape, a boundary surface over proposed curves. Storing it as B-spline
faces never makes it exact.

## Consequences

One rule, decided by when the geometry is fixed, not by how it looks.
