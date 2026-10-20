"""Grade the Forge V1 validation suite.

    python validation\\check-suite.py            grade every run that exists
    python validation\\check-suite.py R01 P04    grade only these

Reads validation\\suite.json and each validation\\runs\\<id>\\run.json, and
writes validation\\report.md. Standard library only.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = json.loads((HERE / "suite.json").read_text(encoding="utf-8"))
RUNS = HERE / "runs"
OK_STATUSES = {"PASS", "NOT_APPLICABLE"}


def number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("magnitude", "value"):
            if key in value:
                return number(value[key])
    m = re.search(r"-?\d+(?:\.\d+)?(?:e[-+]?\d+)?", str(value))
    return float(m.group(0)) if m else None


def evidence_of(run):
    v = run.get("verification") or {}
    e = (v.get("evidence") or {})
    items = e.get("evidence") if isinstance(e, dict) else e
    return items or []


def measurement_of(item):
    d = item.get("detail") or {}
    return str(d.get("measurement", "") or item.get("measurement", ""))


def geometry(test, run, notes):
    v = run.get("verification") or {}
    m = v.get("measurements") or {}
    part = m.get("part") or {}
    good = True
    env = part.get("envelope_mm")
    if test.get("env_xyz") and env:
        for got, want in zip(env, test["env_xyz"]):
            if abs(got - want) > max(1.0, 0.03 * want):
                good = False
        notes.append(f"envelope {env} vs {test['env_xyz']} (x,y,z)")
    elif test.get("envelope") and env:
        got = sorted(env)
        if any(abs(g - w) > max(1.0, 0.03 * w) for g, w in zip(got, test["envelope"])):
            good = False
        notes.append(f"envelope {[round(x,2) for x in got]} vs {test['envelope']}")
    if test.get("env_z") and env:
        if abs(env[2] - test["env_z"]) > max(1.0, 0.03 * test["env_z"]):
            good = False
        notes.append(f"height {env[2]} vs {test['env_z']}")
    want = test.get("volume")
    got = number(m.get("mesh_volume")) or number(part.get("volume_mm3"))
    if want is not None and got is not None:
        if isinstance(want, list):
            lo, hi = want[0] * 0.99, want[1] * 1.01
        else:
            tol = test["vol_tol"]
            dims = sorted(env) if env else None
            # The mesh measures a part's volume to within 0.3% unless the
            # part is a rod -- two sizes small beside the third: 0.65% on a
            # 12 x 100 rod, 3% on a 3 x 60 pin. A counterbore left off a
            # 60 x 40 x 10 plate is 1.2% of it, and 4% let it through (H03).
            if dims and dims[2] > 0 and dims[1] / dims[2] >= 0.15:
                tol = min(tol, 0.01)
            lo, hi = want * (1 - tol), want * (1 + tol)
        if not lo <= got <= hi:
            good = False
        notes.append(f"volume {got:.0f} vs {round(lo)}..{round(hi)}")
    if test.get("holes") is not None:
        holes = part.get("open_holes")
        if holes != test["holes"]:
            good = False
        notes.append(f"open holes {holes} vs {test['holes']}")
    return good


def grade(test, run):
    state = str(run.get("state", "?"))
    notes = []
    items = evidence_of(run)
    bad = [f"{i.get('id')}={i.get('status')}" for i in items
           if i.get("status") not in OK_STATUSES]
    reasons = (run.get("verification") or {}).get("release_reasons") or []
    expect = test["expect"]
    if expect in ("honest", "honest_fail", "inspect") and not items:
        notes.append(f"no part built ({state})")
    shape_ok = geometry(test, run, notes) if items else False
    if bad:
        notes.append("not passing: " + ", ".join(bad[:6]))
    only_assumptions = bool(reasons) and all(
        str(r).startswith("assumption") for r in reasons)

    if expect == "pass":
        ok = state == "completed" and not bad and shape_ok
    elif expect == "held":
        ok = state == "blocked" and only_assumptions and not bad and shape_ok
    elif expect == "pass_or_held":
        ok = ((state == "completed") or (state == "blocked" and only_assumptions)) \
            and not bad and shape_ok
    elif expect == "honest":
        ok = state != "completed"
        if not ok:
            notes.append("COMPLETED a part the brief cannot honestly give -- review the STL")
    elif expect == "honest_fail":
        need = test.get("needs") or ""
        failed = [i for i in items if measurement_of(i).startswith(need)
                  and i.get("status") == "FAIL"]
        ok = state != "completed" and (bool(failed) or not items)
        if not failed and items:
            notes.append(f"expected a FAIL on {need}")
    else:  # inspect
        return "REVIEW", state, notes
    return ("OK" if ok else "FAIL"), state, notes


def main(argv):
    only = set(argv)
    rows = []
    for test in SUITE["tests"]:
        if only and test["id"] not in only:
            continue
        dirs = sorted(p for p in RUNS.glob(test["id"] + "*") if p.is_dir()) \
            if RUNS.exists() else []
        if not dirs:
            rows.append((test, "-", "NOT RUN", "", []))
            continue
        for d in dirs:
            path = d / "run.json"
            if not path.exists():
                rows.append((test, d.name, "NO RUN.JSON", "", []))
                continue
            run = json.loads(path.read_text(encoding="utf-8"))
            verdict, state, notes = grade(test, run)
            rows.append((test, d.name, verdict, state, notes))

    counts = {}
    for _, _, verdict, _, _ in rows:
        counts[verdict] = counts.get(verdict, 0) + 1
    lines = ["# Forge V1 validation report", "",
             "Verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
             "", "| Test | Run | Expect | Verdict | State | Notes |",
             "|---|---|---|---|---|---|"]
    for test, name, verdict, state, notes in rows:
        lines.append(f"| {test['id']} {test['title']} | {name} | {test['expect']} "
                     f"| **{verdict}** | {state} | {'; '.join(notes)} |")
    (HERE / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for test, name, verdict, state, notes in rows:
        print(f"{verdict:11} {name:12} {test['expect']:12} {state:16} {test['title']}")
        for n in notes:
            print(f"{'':13}{n}")
    print()
    print("Verdicts:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"Written to {HERE / 'report.md'}")


if __name__ == "__main__":
    main(sys.argv[1:])
