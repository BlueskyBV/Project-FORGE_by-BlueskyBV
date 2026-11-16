"""Every draft Forge holds, read and judged as it is stored: a schema migration's proof (ADR-0026; V2-stage4b-0c.md, 3.2).

A migration (``forge_spec.migrations``) brings a draft written in one major
version of the schema to the next. It is proven by reading every draft
Forge holds, **as it was stored**, on the code before the migration and on
the code after it (which migrates it as it reads it), and holding what the
two make against each other: the spec, its solved layout, its problems and
accounting (the report, plain and strict), and the judge's placement,
oracle and check suite; every digest the same where the step is a
substrate, each one that differs listed where it is an ability.

The drafts, collected once on the code before (``collect``), each with the
brief it was drafted from:

- V1's validation suite as V2 drafts it (``v2_suite_specs``);
- the kept regressions' parts (``v2_regressions``), as the generator
  renders their plans;
- each counted seed's generated part, its mutant (``seed % len``) and its
  impossible part.

Then each side reads the same file (``record``), and ``--compare`` holds the
two records against each other::

    python tests/v2_migrations.py collect --seeds 0-200 --out runs/migrations/drafts.jsonl
    python tests/v2_migrations.py record --drafts runs/migrations/drafts.jsonl --out runs/migrations/base
    python tests/v2_migrations.py compare runs/migrations/base runs/migrations/fin

(``forge-runs.yml``, mode ``migrations``, does it on one runner, split over
the shards.) A collected draft says the version it was written in, as its
side writes it; the record says nothing of versions, so a minor step
records the same as the code before it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "packages")]
sys.setrecursionlimit(max(sys.getrecursionlimit(), 20_000))

import v2_fingerprint as fp  # noqa: E402  (the fingerprint's canonical digest, sections and environment)


def _header() -> dict[str, Any]:
    """The version line a draft written on this code starts with."""
    try:
        from forge_spec.versions import CURRENT, written
    except ImportError:  # the code before versions
        return {"spec_format": 1}
    return {"schema_version": written(CURRENT)}


def _generated(name: str, case: Any) -> dict[str, Any]:
    return {
        "name": name,
        "brief": case.brief,
        "draft": {**_header(), "name": "generated", "items": list(case.items)},
    }


def held(seeds: list[int], fixed: bool = True) -> Iterator[dict[str, Any]]:
    """Every draft Forge holds, in a fixed order: the suite's and the regressions' (``fixed``), then each seed's three."""
    from forge_eval.generator import generate, impossible, mutants, render
    from forge_spec.words import number_words
    from v2_regressions import REGRESSIONS
    from v2_suite_specs import DRAFTS, suite

    for part in suite().values() if fixed else ():
        if part.id in DRAFTS:
            numbered = number_words(part.brief)
            yield {
                "name": f"suite {part.id}",
                "brief": part.brief,
                "draft": DRAFTS[part.id](numbered),
            }
    for seed, (_why, plan) in sorted(REGRESSIONS.items()) if fixed else ():
        yield _generated(f"regression {seed}", render(plan, strict=False))
    for seed in seeds:
        case = generate(seed)
        yield _generated(f"seed {seed}", case)
        found = list(mutants(case))
        if found:
            key, mutant = found[seed % len(found)]
            yield _generated(f"seed {seed} mutant {'/'.join(key)}", mutant)
        yield _generated(f"seed {seed} impossible", impossible(seed))


def collect(seeds: list[int], out: Path, fixed: bool = True) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", encoding="utf-8") as f:
        for entry in held(seeds, fixed):
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1
    print(f"{count} drafts collected in {out}")
    return 0


def record_one(entry: dict[str, Any]) -> dict[str, Any]:
    """One stored draft's digests, by section: what reading and judging it makes."""
    from forge_checks.judge import Judge
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    out = fp._Sections()
    started = time.perf_counter()
    numbered = out("words", lambda: number_words(entry["brief"]))
    if numbered is not None:
        report = out("report", lambda: check_draft(numbered, entry["draft"]))
        out("report.strict", lambda: check_draft(numbered, entry["draft"], strict=True))
        spec = None if report is None else report.spec
        if spec is not None and report.layout is not None:
            judge = out("judge", lambda: Judge.of(spec))
            if judge is not None:
                out("judge.lists", lambda: (judge.kinds, judge.unchecked, judge.held_otherwise,
                                             judge.classes()))  # fmt: skip
    return {
        "name": entry["name"],
        "digests": out.digests,
        "seconds": round(time.perf_counter() - started, 2),
    }


def record(drafts: Path, out: Path, part: tuple[int, int] = (0, 1)) -> int:
    """Record the drafts in ``drafts`` (every ``part[1]``-th from the ``part[0]``-th) into ``out``."""
    entries = [json.loads(line) for line in drafts.read_text(encoding="utf-8").splitlines()
               if line.strip()]  # fmt: skip
    mine = entries[part[0] :: part[1]]
    out.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in fp.header(False).items() if k != "verdicts"}
    head["harness"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / "header.json").write_text(json.dumps(head, indent=1), encoding="utf-8")
    started = time.monotonic()
    with (out / "records.jsonl").open("w", encoding="utf-8") as f:
        for entry in mine:
            f.write(json.dumps(record_one(entry)) + "\n")
            f.flush()
    print(f"{len(mine)} drafts recorded in {out} ({time.monotonic() - started:.0f} s)")
    return 0


def load(out: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """A record folder (or a folder of shard folders, merged)."""
    folders = (
        [out]
        if (out / "header.json").exists()
        else sorted(p.parent for p in out.glob("*/header.json"))
    )
    if not folders:
        raise SystemExit(f"no records in {out}")
    head = json.loads((folders[0] / "header.json").read_text(encoding="utf-8"))
    records: dict[str, dict[str, str]] = {}
    for folder in folders:
        for line in (folder / "records.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                records[r["name"]] = r["digests"]
    return head, records


def compare(first: Path, second: Path) -> tuple[list[str], list[str]]:
    """Two records held against each other: the drafts and sections that differ, and how the environments differ."""
    (h1, r1), (h2, r2) = load(first), load(second)
    told = [f"{k}: {h1.get(k)} | {h2.get(k)}" for k in ("harness", "code", "python", "numpy", "machine",
                                                         "hash_seed") if h1.get(k) != h2.get(k)]  # fmt: skip
    found = [f"once {k}" for k in sorted(set(h1["once"]) | set(h2["once"]))
             if h1["once"].get(k) != h2["once"].get(k)]  # fmt: skip
    for name in [n for n in r1 if n in r2]:
        a, b = r1[name], r2[name]
        if list(a) != list(b):
            found.append(
                f"{name}: sections {[k for k in a if k not in b]} | {[k for k in b if k not in a]}"
            )
        found += [f"{name} {k}" for k in a if k in b and a[k] != b[k]]
    only = sorted(set(r1) ^ set(r2))
    if only:
        found.append(
            f"{len(only)} drafts in one record only: {only[:10]}{' ...' if len(only) > 10 else ''}"
        )
    return found, told


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="what", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--seeds", default="sample:100")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument(
        "--no-fixed",
        action="store_true",
        help="only the seeds' drafts, not the suite's and regressions'",
    )
    r = sub.add_parser("record")
    r.add_argument("--drafts", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument(
        "--part",
        default="0/1",
        help="k/n: every n-th draft from the k-th (a shard's share)",
    )
    m = sub.add_parser("compare")
    m.add_argument("first", type=Path)
    m.add_argument("second", type=Path)
    args = parser.parse_args(argv)
    if args.what == "collect":
        return collect(fp._seeds(args.seeds), args.out, not args.no_fixed)
    if args.what == "record":
        k, n = (int(x) for x in args.part.split("/"))
        return record(args.drafts, args.out, (k, n))
    found, told = compare(args.first, args.second)
    print("environment: " + ("; ".join(told) if told else "the same"))
    print(f"{len(found)} differences")
    for line in found[:200]:
        print("  " + line)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
