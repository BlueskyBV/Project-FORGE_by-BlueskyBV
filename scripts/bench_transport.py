"""Measure what Forge's designer request actually costs, and what enforces it.

Everything here answers a question that would otherwise be decided by guessing,
and every answer changes what gets built next:

  A. What does schema size cost in wall-clock time? Ollama reports prompt
     processing and generation separately, so this is measurable without
     generating anything -- one output token per probe. If collapsing the
     schema saves two seconds it is not worth doing; if it saves minutes it is
     the first thing to do.

  B. Is the OpenAI-compatible shim really twice as slow as the native endpoint
     at full schema size, or was that an artifact of a three-field toy?

  C. Is the prompt being silently truncated TODAY? The server reports how many
     prompt tokens it actually processed. If that is below what we sent, the
     designer has been answering from a fragment this whole time and nobody
     has ever checked.

  D. Does `--context-window` do anything? Forge treats it as a planning hint;
     the runtime takes `num_ctx`. This shows what the server actually used.

  E. Does each transport ENFORCE the real designer schema -- 22 `oneOf`
     branches, deeply nested -- rather than merely accepting it? And does it
     still enforce after the repeated subschema is collapsed into `$defs`?
     A three-field toy proves nothing about a grammar converter's behaviour on
     the real thing.

The enforcement test uses a canary: a required field, whose only legal value
is a word no model would volunteer, injected into the quantity subschema --
the exact shape that `$defs` collapses. If the grammar is enforced the canary
appears because nothing else can be emitted. If the reference was dropped, the
canary goes with it. That distinguishes "the endpoint enforced my schema" from
"the model guessed the shape", which well-formed output cannot.

    python scripts/bench_transport.py --model forge-qwen

Phase A is seconds. Phase B generates, so allow ten minutes or so. Add
`--skip-enforcement` for timings only.
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packages"))

from forge_ir.spec import authoring_guide  # noqa: E402
from forge_models import ModelRequest, user  # noqa: E402
from forge_models.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from forge_roles.library import ForgeIRDesigner  # noqa: E402

CANARY = "forge_canary"

#: Deliberately the simplest part that is still a real document, so the answer
#: is short. The question is what the SCHEMA costs, not what the part costs.
BRIEF = "A plain aluminium block, 20 mm by 20 mm by 10 mm. No holes."


# ----------------------------------------------------------------- schemas


def collapse(schema: dict) -> dict:
    """Move repeated subschemas into `$defs`, largest saving first.

    Meaning is untouched: every branch, unit and constraint survives. Only the
    encoding changes, which is the whole point -- if the endpoint resolves the
    references, those tokens were never buying anything.
    """
    schema = copy.deepcopy(schema)
    for round_ in range(8):
        counts: collections.Counter = collections.Counter()

        def walk(node):
            if isinstance(node, dict):
                if "$ref" not in node:
                    counts[json.dumps(node, sort_keys=True)] += 1
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(schema)
        best = max(
            ((c, k) for k, c in counts.items() if c > 1 and len(k) > 80),
            key=lambda pair: (pair[0] - 1) * len(pair[1]),
            default=None,
        )
        if best is None:
            break
        target = json.loads(best[1])
        name = f"shared{round_}"

        def swap(node):
            if isinstance(node, dict):
                for key, value in list(node.items()):
                    if isinstance(value, dict) and value == target:
                        node[key] = {"$ref": f"#/$defs/{name}"}
                    else:
                        swap(value)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    if isinstance(value, dict) and value == target:
                        node[index] = {"$ref": f"#/$defs/{name}"}
                    else:
                        swap(value)

        swap(schema)
        schema.setdefault("$defs", {})[name] = target
    return schema


def with_canary(schema: dict) -> dict:
    """Require the canary on every quantity -- the shape `$defs` collapses."""
    schema = copy.deepcopy(schema)
    touched = 0

    def visit(node):
        nonlocal touched
        if isinstance(node, dict):
            properties = node.get("properties")
            if (
                isinstance(properties, dict)
                and "magnitude" in properties
                and "unit" in properties
            ):
                properties["provenance"] = {"type": "string", "enum": [CANARY]}
                required = node.setdefault("required", [])
                if "provenance" not in required:
                    required.append("provenance")
                touched += 1
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    if not touched:
        raise SystemExit("could not find the quantity subschema to mark")
    return schema


def canaries_in(payload) -> tuple[int, int]:
    """(found, inspected) over every quantity-shaped object in the answer.

    `inspected` of zero is never a pass: nothing was there to check.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return 0, 0
    found = inspected = 0

    def visit(node):
        nonlocal found, inspected
        if isinstance(node, dict):
            if "magnitude" in node and "unit" in node:
                inspected += 1
                if node.get("provenance") == CANARY:
                    found += 1
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    return found, inspected


# ---------------------------------------------------------------- transports


def native(args, schema, prompt, predict):
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/chat",
        data=json.dumps(
            {
                "model": args.model,
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "format": schema,
                "options": {
                    "num_ctx": args.context,
                    "num_predict": predict,
                    "temperature": 0,
                    "seed": 42,
                },
                "messages": [
                    {"role": "system", "content": args.system},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        data = json.loads(response.read())
    return {
        "wall": time.time() - started,
        "prompt_tokens": data.get("prompt_eval_count"),
        # Nanoseconds, per Ollama's API.
        "prompt_seconds": (data.get("prompt_eval_duration") or 0) / 1e9,
        "gen_seconds": (data.get("eval_duration") or 0) / 1e9,
        "out_tokens": data.get("eval_count"),
        "stop": data.get("done_reason", ""),
        "payload": data.get("message", {}).get("content", ""),
    }


def shim(args, schema, prompt, predict):
    provider = OpenAICompatibleProvider(
        model=args.model,
        base_url=args.base_url.rstrip("/") + "/v1",
        structured_mode=args.structured_mode,
        schema_dialect="json_schema",
        timeout=args.timeout,
        context_window=args.context,
        allow_schema_reduction=False,
    )
    started = time.time()
    response = provider.complete(
        ModelRequest(
            system=args.system,
            messages=(user(prompt),),
            schema=schema,
            schema_name="document",
            schema_description="The part you designed.",
            max_output_tokens=predict,
            temperature=0.0,
            purpose="bench",
        )
    )
    usage = response.usage
    return {
        "wall": time.time() - started,
        "prompt_tokens": getattr(usage, "input_tokens", None),
        "prompt_seconds": None,
        "gen_seconds": None,
        "out_tokens": getattr(usage, "output_tokens", None),
        "stop": str(response.stop_reason),
        "payload": response.structured or response.text,
    }


# --------------------------------------------------------------------- runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--structured-mode", default="tools")
    parser.add_argument("--skip-enforcement", action="store_true")
    parser.add_argument("--system", default="")
    args = parser.parse_args()

    designer = ForgeIRDesigner()
    full = designer.output_schema()
    guide = authoring_guide()
    args.system = args.system or designer.system_prompt()

    shapes = {
        "full (as shipped)": full,
        "$defs collapsed": collapse(full),
        "toy (3 fields)": {
            "type": "object",
            "additionalProperties": False,
            "required": ["size"],
            "properties": {
                "size": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["magnitude", "unit"],
                    "properties": {
                        "magnitude": {"type": "number"},
                        "unit": {"type": "string", "enum": ["mm"]},
                    },
                }
            },
        },
    }

    print(f"endpoint  : {args.base_url}")
    print(f"model     : {args.model}")
    print(f"num_ctx   : {args.context}")
    print(f"guide     : {len(guide)} chars (~{len(guide)//4} tokens)")
    for name, schema in shapes.items():
        text = json.dumps(schema)
        print(f"schema {name:18s}: {len(text):6d} chars (~{len(text)//4:5d} tokens)")

    # ---- Phase A: what does the prompt cost? One output token per probe.
    print("\n" + "=" * 70)
    print("PHASE A -- input cost (num_predict=1, nothing is generated)")
    print("=" * 70)
    print(f"{'transport':10s} {'schema':20s} {'prompt tok':>10s} "
          f"{'prompt s':>9s} {'wall s':>8s}")
    rows = []
    for label, call in (("native", native), ("shim", shim)):
        for name, schema in shapes.items():
            try:
                result = call(args, schema, BRIEF, 1)
            except Exception as error:  # noqa: BLE001
                print(f"{label:10s} {name:20s}  FAILED: "
                      f"{type(error).__name__}: {str(error)[:60]}")
                continue
            rows.append((label, name, result))
            tokens = str(result["prompt_tokens"] or "?")
            seconds = result["prompt_seconds"]
            # The shim does not report prompt-processing time separately, so
            # only wall clock is comparable there.
            prompt_time = f"{seconds:.1f}" if seconds else "-"
            print(f"{label:10s} {name:20s} {tokens:>10s} "
                  f"{prompt_time:>9s} {result['wall']:>8.1f}")

    # ---- Phase A2: truncation and context reality
    print("\n" + "-" * 70)
    print("TRUNCATION / CONTEXT")
    for label, name, result in rows:
        tokens = result["prompt_tokens"]
        if tokens is None:
            continue
        estimate = (len(json.dumps(shapes[name])) + len(args.system) + len(BRIEF)) // 4
        flag = ""
        if tokens >= args.context - 8:
            flag = "  <<< AT THE CONTEXT LIMIT -- prompt is being cut"
        elif tokens < estimate * 0.6:
            flag = f"  <<< server processed far fewer than the ~{estimate} we sent"
        print(f"  {label:8s} {name:20s} server processed {tokens:6d} tokens "
              f"(we estimate ~{estimate}){flag}")

    if args.skip_enforcement:
        print("\n(enforcement skipped)\n")
        return 0

    # ---- Phase B: is the REAL schema actually enforced?
    print("\n" + "=" * 70)
    print("PHASE B -- enforcement on the real designer schema")
    print("=" * 70)
    marked = {
        "full + canary": with_canary(full),
        "$defs + canary": collapse(with_canary(full)),
    }
    verdicts = {}
    for label, call in (("native", native), ("shim", shim)):
        for name, schema in marked.items():
            print(f"  running {label:8s} {name:16s} ...", flush=True)
            try:
                result = call(args, schema, BRIEF, 900)
            except Exception as error:  # noqa: BLE001
                print(f"    FAILED: {type(error).__name__}: {str(error)[:120]}")
                verdicts[(label, name)] = None
                continue
            found, inspected = canaries_in(result["payload"])
            verdicts[(label, name)] = (found, inspected)
            print(f"    {found}/{inspected} canaries, {result['wall']:.1f}s, "
                  f"stop={result['stop']}, out={result['out_tokens']}")
            if inspected == 0:
                print(f"    raw: {str(result['payload'])[:160]!r}")

    print("\n" + "=" * 70)
    print("VERDICTS")
    print("=" * 70)
    for label in ("native", "shim"):
        base = verdicts.get((label, "full + canary"))
        ref = verdicts.get((label, "$defs + canary"))
        print(f"\n{label}")
        if not base or base[1] == 0:
            print("  NO VERDICT: the full schema produced nothing to inspect.")
            continue
        enforced = base[0] == base[1]
        print(f"  full schema  : {base[0]}/{base[1]} -> "
              f"{'ENFORCED' if enforced else 'NOT ENFORCED'}")
        if not enforced:
            print("  This transport is not constraining generation even as")
            print("  shipped. That matters more than the $defs question.")
            continue
        if not ref or ref[1] == 0:
            print("  $defs        : nothing to inspect -- NO VERDICT")
            continue
        print(f"  $defs schema : {ref[0]}/{ref[1]} -> "
              f"{'ENFORCED -- safe to collapse' if ref[0] == ref[1] else 'SILENTLY DROPPED -- do not collapse here'}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
