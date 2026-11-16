"""Every value a program makes for some seeds, written out in full: where two machines' fingerprints differ, which values (4b.0c, item 0).

The fingerprint (``v2_fingerprint.py``) digests each section; this writes
the same canonical form with every float as its value and every array's
elements, so two machines' files can be walked side by side to the first
value that differs and the path to it:

    python tests/v2_values.py dump --seeds 0-3 --sections judge --out values.json
    python tests/v2_values.py diff a.json b.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "packages")]


def _canonical_with_values() -> Any:
    import numpy as np
    import v2_fingerprint as fp

    original = fp.canonical

    def canonical(value: Any, _stack: frozenset[int] = frozenset()) -> Any:
        if isinstance(value, float):
            return {"f": value.hex()} if math.isfinite(value) else repr(value)
        if isinstance(value, np.ndarray) and value.dtype != object:
            flat = value.ravel().tolist()
            if value.dtype.kind == "f":
                flat = [
                    {"f": float(v).hex()} if math.isfinite(v) else repr(v) for v in flat
                ]
            elif value.dtype.kind == "c":
                flat = [
                    [float(v.real).hex(), float(v.imag).hex()] for v in value.ravel()
                ]
            return {
                "array": str(value.dtype),
                "shape": list(value.shape),
                "values": flat,
            }
        if isinstance(value, np.generic):
            return canonical(value.item(), _stack)
        return original(value, _stack)

    fp.canonical = canonical
    return canonical


def dump(seeds: list[int], sections: set[str], out: Path) -> None:
    canonical = _canonical_with_values()
    import v2_fingerprint as fp
    from forge_checks.judge import Judge
    from forge_eval.generator import generate
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    rows: dict[str, Any] = {}
    for seed in seeds:
        case = generate(seed)
        numbered = number_words(case.brief)
        report = check_draft(numbered, fp._draft(case.items))
        row: dict[str, Any] = {}
        if "report" in sections:
            row["report"] = canonical(report)
        if "judge" in sections and report.spec is not None:
            judge = Judge.of(report.spec)
            row["judge"] = canonical(judge)
        rows[str(seed)] = row
    out.write_text(json.dumps(rows), encoding="utf-8")


def diff(a: Path, b: Path, limit: int = 40) -> None:
    left = json.loads(a.read_text(encoding="utf-8"))
    right = json.loads(b.read_text(encoding="utf-8"))
    found: list[str] = []

    def walk(x: Any, y: Any, where: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(x, dict) and isinstance(y, dict):
            if set(x) != set(y):
                found.append(f"{where}: keys differ")
                return
            for k in x:
                walk(x[k], y[k], f"{where}.{k}")
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                found.append(f"{where}: lengths {len(x)} | {len(y)}")
                return
            for i, (p, q) in enumerate(zip(x, y, strict=True)):
                walk(p, q, f"{where}[{i}]")
        elif x != y:
            text = f"{where}: {str(x)[:80]} | {str(y)[:80]}"
            if (
                isinstance(x, str)
                and isinstance(y, str)
                and x.startswith(("0x", "-0x"))
            ):
                u, v = float.fromhex(x), float.fromhex(y)
                text += f"  ({u!r} | {v!r})"
            found.append(text)

    for seed in left:
        walk(left[seed], right.get(seed), f"seed {seed}")
    print("\n".join(found) or "the same")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="what", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--seeds", default="0-3")
    d.add_argument("--sections", default="judge")
    d.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("diff")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    c.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    if args.what == "dump":
        first, _, last = args.seeds.partition("-")
        seeds = list(range(int(first), int(last))) if last else [int(first)]
        dump(seeds, set(args.sections.split(",")), args.out)
    else:
        diff(args.a, args.b, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
