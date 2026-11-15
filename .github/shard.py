"""One runner's share of a seed list: python .github/shard.py SPEC SHARDS INDEX prints a comma list.

SPEC is anything ``tests/v2_fingerprint.py --seeds`` takes, or ``others``: stage 4's 10,000 counted seeds
less the fixed sample. The shard takes every SHARDS-th seed of it from INDEX, so the shards together are
the list, each seed once.
"""

import sys

sys.path.insert(0, "tests")
from v2_fingerprint import _seeds, sample  # noqa: E402

spec, shards, index = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
if spec == "others":
    kept = set(sample())
    seeds = [s for s in range(10000) if s not in kept]
else:
    seeds = _seeds(spec)
print(",".join(str(s) for s in seeds[index::shards]))
