"""The old bodies' branch coverage, function by function (V2-stage4b-0b.md, 6.3), on a runner.

python .github/coverage_report.py IN BASE OUT

IN holds a coverage run's artifacts (out-K/cov/.coverage.*), measured on the base branch checked out at
BASE (the same path as in the coverage run, so the data's paths resolve). Every function the step-0
inventory (docs/V2-stage4b-0b-inventory.md, section 3) names is reported: its lines and branches run,
and each branch never taken, with its source line, for review. OUT gets coverage.json, report.md and a
one-line summary per function in summary.tsv.
"""

import glob
import json
import re
import subprocess
import sys
from pathlib import Path

source, base, out = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
data = out / ".coverage"
files = sorted(glob.glob(f"{source}/out-*/cov/.coverage.*"))
subprocess.run([sys.executable, "-m", "coverage", "combine", f"--data-file={data}", "--keep", *files], check=True)
subprocess.run([sys.executable, "-m", "coverage", "json", f"--data-file={data}", "-o", str(out / "coverage.json")],
               check=True, cwd=base)
report = json.loads((out / "coverage.json").read_text(encoding="utf-8"))

# The inventory's functions: "### `forge_x/file.py`: N sites" then rows "| `Class.method` | ...".
inventory: list[tuple[str, str]] = []
current = None
for line in Path("docs/V2-stage4b-0b-inventory.md").read_text(encoding="utf-8").splitlines():
    m = re.match(r"^### `([^`]+\.py)`", line)
    if m:
        current = m.group(1)
        continue
    m = re.match(r"^\| `([^`]+)` \|", line)
    if m and current:
        inventory.append((current, m.group(1)))

by_suffix = {}
for path in report["files"]:
    norm = path.replace("\\", "/")
    for i in range(len(norm)):
        if norm[i:].startswith("packages/"):
            by_suffix[norm[i + len("packages/"):]] = path
            break
lines_out = ["# The old bodies' coverage (V2-stage4b-0b.md, 6.3)", "",
             f"{len(files)} data files; {len(inventory)} inventory functions.", ""]
summary = ["file\tfunction\tlines\tlines_run\tbranches\tbranches_taken\tmissing_branches"]
totals = [0, 0, 0, 0]
for rel, func in inventory:
    entry = report["files"].get(by_suffix.get(rel, ""), None)
    if entry is None:
        summary.append(f"{rel}\t{func}\tNOT MEASURED")
        lines_out.append(f"## {rel} {func}: not measured")
        continue
    key = "" if func == "<module>" else func
    region = entry.get("functions", {}).get(key)
    if region is None:
        summary.append(f"{rel}\t{func}\tNO REGION")
        lines_out.append(f"## {rel} {func}: no such function in the coverage report")
        continue
    s = region["summary"]
    nb, nbt = s.get("num_branches", 0), s.get("covered_branches", 0)
    totals = [totals[0] + s["num_statements"], totals[1] + s["covered_lines"], totals[2] + nb, totals[3] + nbt]
    missing = region.get("missing_branches", [])
    summary.append(f"{rel}\t{func}\t{s['num_statements']}\t{s['covered_lines']}\t{nb}\t{nbt}\t{len(missing)}")
    if missing or region.get("missing_lines"):
        text = (base / "packages" / rel).read_text(encoding="utf-8").splitlines()
        lines_out.append(f"## {rel} {func}: lines {s['covered_lines']}/{s['num_statements']}, branches {nbt}/{nb}")
        for a, b in missing:
            src = text[a - 1].strip() if 0 < a <= len(text) else ""
            dst = text[b - 1].strip() if 0 < b <= len(text) else "(exit)"
            lines_out.append(f"- {a} -> {b}: `{src[:110]}` -> `{dst[:80]}`")
        never = region.get("missing_lines", [])
        if never:
            lines_out.append(f"- lines never run: {never}")
        lines_out.append("")
lines_out.insert(4, f"In all: lines {totals[1]}/{totals[0]}, branches {totals[3]}/{totals[2]}.")
(out / "report.md").write_text("\n".join(lines_out) + "\n", encoding="utf-8")
(out / "summary.tsv").write_text("\n".join(summary) + "\n", encoding="utf-8")
print("\n".join(lines_out[:8]))
