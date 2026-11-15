# V2 stage 2: the detection matrix and the false-hold rate

Written by `python tests/v2_detection.py` (docs/V2-stage2.md, 8.3), from generated parts 0 to 23, in 89 minutes. Fresh probes drawn from seed 2026.

## False holds

0 of 23 parts as asked held (1 more skipped: the mesh library made their meshes unsoundly).

## Detection

Each cell: how many of the faults in its row the detector failed. A
fault is held when any detector fails it; one only inconclusive is
held too, and listed.

| Fault | angle | choice | corner | count | depth | diameter | on | pattern | position | size | face accounting | topology | volume | fresh probes | held | of |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| an item taken away | 5 | 2 | 2 | 5 | 17 | 15 | 15 | 6 | 22 | 10 | 22 | 0 | 0 | 22 | 22 | 22 |
| leaf: along | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 1 |
| leaf: corner_radius | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 1 | 1 |
| leaf: counterbore | 0 | 0 | 0 | 0 | 2 | 3 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 4 | 5 | 5 |
| leaf: countersink | 3 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 2 | 3 | 3 |
| leaf: depth | 3 | 0 | 0 | 0 | 23 | 0 | 4 | 2 | 0 | 0 | 23 | 0 | 3 | 18 | 23 | 23 |
| leaf: diameter | 0 | 1 | 0 | 4 | 6 | 41 | 4 | 0 | 31 | 2 | 41 | 0 | 3 | 39 | 41 | 41 |
| leaf: end | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 1 | 1 |
| leaf: ends | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 0 | 0 | 2 | 2 | 2 |
| leaf: height | 0 | 0 | 0 | 0 | 1 | 1 | 2 | 0 | 5 | 11 | 11 | 0 | 1 | 8 | 11 | 11 |
| leaf: length | 1 | 4 | 0 | 7 | 7 | 6 | 16 | 1 | 26 | 38 | 38 | 0 | 0 | 36 | 38 | 38 |
| leaf: on | 0 | 4 | 0 | 5 | 12 | 14 | 23 | 6 | 21 | 17 | 23 | 0 | 0 | 23 | 23 | 23 |
| leaf: pattern | 2 | 4 | 0 | 11 | 8 | 10 | 12 | 16 | 14 | 11 | 19 | 0 | 0 | 19 | 19 | 19 |
| leaf: place | 1 | 7 | 2 | 5 | 14 | 13 | 26 | 3 | 68 | 19 | 72 | 0 | 0 | 72 | 72 | 72 |
| leaf: thickness | 0 | 0 | 0 | 0 | 2 | 0 | 2 | 0 | 2 | 4 | 4 | 0 | 0 | 4 | 4 | 4 |
| leaf: thickness_along | 0 | 2 | 0 | 0 | 2 | 1 | 3 | 0 | 3 | 3 | 3 | 0 | 0 | 3 | 3 | 3 |
| leaf: width | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 4 | 9 | 9 | 0 | 0 | 9 | 9 | 9 |
| mirrored | 9 | 9 | 3 | 13 | 23 | 23 | 21 | 13 | 23 | 19 | 23 | 0 | 0 | 23 | 23 | 23 |
| moved 0.05 mm | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 23 | 0 | 0 | 23 | 23 | 23 |
| scaled by 1.001 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 23 | 0 | 0 | 23 | 23 | 23 |
| turned 90 degrees | 10 | 11 | 7 | 15 | 23 | 23 | 23 | 15 | 23 | 22 | 23 | 0 | 0 | 23 | 23 | 23 |

370 of 370 faults held by a FAIL.

None got past every detector.

Left out (the same shape as the part asked for, or an unsound mesh):

- an item taken away: 1
- leaf: counterbore: 1
- leaf: countersink: 1
- leaf: depth: 5
- leaf: length: 2
- leaf: on: 8
- leaf: pattern: 1
- leaf: place: 2
