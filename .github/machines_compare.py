"""Every machine's fingerprints held against the first's, section by section: python .github/machines_compare.py IN

IN holds one folder per machine (fp-0, fp-1, ...; fp-0 the reference), each with fp/records.jsonl,
fp/header.json and fp/machine.json, as forge-machines.yml uploads them.
"""

import json
import sys
from collections import Counter
from pathlib import Path


def load(folder: Path) -> tuple[dict, dict, dict[int, dict]]:
    fp = folder / "fp"
    machine = json.loads((fp / "machine.json").read_text(encoding="utf-8")) if (fp / "machine.json").exists() else {}
    header = json.loads((fp / "header.json").read_text(encoding="utf-8")) if (fp / "header.json").exists() else {}
    records = {}
    if (fp / "records.jsonl").exists():
        for line in (fp / "records.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                records[record["seed"]] = record["digests"]
    return machine, header, records


def main(root: Path) -> None:
    rows = sorted((p for p in root.iterdir() if p.name.startswith("fp-")), key=lambda p: int(p.name[3:]))
    loaded = [(p.name, *load(p)) for p in rows]
    name0, m0, h0, r0 = loaded[0]
    print(f"reference {name0}: {m0} | {len(r0)} seeds")
    for name, m, h, r in loaded[1:]:
        print(f"\n== {name}: {m} | {len(r)} seeds")
        for key in ("code", "harness", "python", "numpy", "hash_seed"):
            if h.get(key) != h0.get(key):
                print(f"  header {key}: {h0.get(key)} | {h.get(key)}")
        for key in sorted(set(h0.get("once", {})) | set(h.get("once", {}))):
            if h0.get("once", {}).get(key) != h.get("once", {}).get(key):
                print(f"  once {key} differs")
        common = sorted(set(r0) & set(r))
        differing = Counter()
        seeds = []
        for seed in common:
            d = [k for k in sorted(set(r0[seed]) | set(r[seed])) if r0[seed].get(k) != r[seed].get(k)]
            if d:
                seeds.append(seed)
                differing.update(d)
        print(f"  {len(common)} seeds in both; {len(seeds)} differ: {seeds[:30]}")
        for section, n in differing.most_common():
            print(f"    {n:5d}  {section}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
