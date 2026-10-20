"""Grade every past run in runs\\ whose brief is one of the suite's tests."""
import json, importlib.util, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check", HERE / "check-suite.py")
check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
by_brief = {t["brief"].strip(): t for t in check.SUITE["tests"]}
rows = []
for path in sorted((HERE.parent / "runs").glob("*/run.json")):
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    test = by_brief.get(str(run.get("brief", "")).strip())
    if test is None or run.get("state") not in ("completed", "blocked"):
        continue
    verdict, state, notes = check.grade(test, run)
    rows.append((path.parent.name, test["id"], verdict, state, notes))
for name, tid, verdict, state, notes in rows:
    if verdict != "OK" or "-v" in sys.argv:
        print(f"{verdict:6} {tid} {state:10} {name}")
        for n in notes: print("        ", n)
print(len(rows), "past runs graded;", sum(1 for r in rows if r[2] == "OK"), "OK")
