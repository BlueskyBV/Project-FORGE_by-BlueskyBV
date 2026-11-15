"""A pair run's records held against each other, on a runner: python .github/compare_run.py IN OUT.

IN holds a pair run's artifacts (out-K/base/shard-K and out-K/fin/shard-K, as the workflow writes them);
the shards of each side are merged into OUT/base and OUT/fin and held against each other with the
fingerprint harness's own comparison. The summary is printed and written to OUT/compare.txt: the
seeds each side recorded, the environments' differences, and every differing section.
"""

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "tests")
from v2_fingerprint import compare  # noqa: E402

source, out = Path(sys.argv[1]), Path(sys.argv[2])
lines = []
for side in ("base", "fin"):
    dirs = sorted(glob.glob(f"{source}/out-*/{side}/shard-*"))
    heads, records = [], []
    for d in dirs:
        heads.append(json.loads(Path(d, "header.json").read_text(encoding="utf-8")))
        records += [r for r in Path(d, "records.jsonl").read_text(encoding="utf-8").splitlines() if r.strip()]
    codes = {h["code"] for h in heads}
    if len(codes) != 1:
        raise SystemExit(f"{side}: shards from different code: {codes}")
    target = out / side
    target.mkdir(parents=True, exist_ok=True)
    (target / "header.json").write_text(json.dumps(heads[0], indent=1), encoding="utf-8")
    (target / "records.jsonl").write_text("".join(r + "\n" for r in records), encoding="utf-8")
    seeds = [json.loads(r)["seed"] for r in records]
    lines.append(f"{side}: {len(dirs)} shards, {len(seeds)} seeds ({len(set(seeds))} distinct), "
                 f"code {heads[0]['code'][:12]}, hash seed {heads[0].get('hash_seed')}, verdicts {heads[0].get('verdicts')}")
found, told = compare(out / "base", out / "fin")
lines += [f"environment: {t}" for t in told]
lines += found
lines.append(f"{len(found)} differences")
text = "\n".join(lines) + "\n"
(out / "compare.txt").write_text(text, encoding="utf-8")
print(text)
