"""The fingerprint's programs run in this process, for coverage: python .github/cov_run.py TREE SEED,SEED,...

TREE is the code measured (its tests/ and packages/ go first on the path); every seed is fingerprinted as
tests/v2_fingerprint.py does, so the branches a proof run takes are the branches measured
(V2-stage4b-0b.md, 6.3).
"""

import sys

tree, seeds = sys.argv[1], [int(s) for s in sys.argv[2].split(",") if s]
sys.path[:0] = [f"{tree}/tests", f"{tree}/packages"]
import v2_fingerprint  # noqa: E402

for seed in seeds:
    v2_fingerprint.fingerprint(seed)
print("done", len(seeds))
